"""Frozen-source Vivado builds and Alchitry Au V2 programming.

python tools/bench_build.py doctor
python tools/bench_build.py build
python tools/bench_build.py program BUILD_DIRECTORY
python tools/bench_build.py program BUILD_DIRECTORY --flash
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from rf_debug import atomic_json

DEFAULT_VIVADO = Path('E:/Vivado/2025.2/Vivado/bin/vivado.bat')
PART = 'xc7a35tftg256-2'
BASE_CAPABILITIES = ['boot_disarmed', 'tx_lease_v1', 'runtime_info_v1']
CAPABILITIES = BASE_CAPABILITIES + ['capture_ready_interlock_v1', 'tagged_pulse_methods_v1',
                                    'multi_rx_v1', 'pulser_status_v1']


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]


def run_logged(args, cwd, log, timeout=3600):
    # Pass arguments as an array, never as interpolated shell code.
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    with Path(log).open('w', encoding='utf-8') as stream:
        p = subprocess.Popen([str(a) for a in args], cwd=cwd, stdout=stream,
                             stderr=subprocess.STDOUT, creationflags=flags)
        try:
            code = p.wait(timeout)
        except BaseException:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=flags)
            else:
                p.kill()
            p.wait()
            raise
    if code:
        tail = Path(log).read_text(encoding='utf-8', errors='replace')[-6000:]
        raise RuntimeError(f'Command failed ({code}); log: {log}\n{tail}')
    return Path(log).read_text(encoding='utf-8', errors='replace')


def safe_batch_path(path):
    value = str(Path(path).resolve())
    # Windows batch dispatch still passes through cmd.exe. These paths are
    # local tool/build inputs, not arbitrary strings to embed in shell code.
    if any(c in value for c in '&|<>^%!\n\r"'):
        raise ValueError('Batch-tool paths cannot contain shell metacharacters')
    return value


def build(vivado, output=None):
    vivado = Path(vivado).resolve()
    if not vivado.is_file():
        raise FileNotFoundError(f'Vivado not found: {vivado}')
    out = Path(output).resolve() if output else ROOT / 'bench_runs/builds' / stamp()
    out.mkdir(parents=True, exist_ok=False)
    safe_batch_path(out)
    safe_batch_path(vivado)
    src = out / 'source'
    inputs = {}
    for rel, target, pattern in (
        ('usb3-tester.srcs/sources_1/new', 'rtl', '*.v'),
        ('usb3-tester.srcs/constrs_1/new', 'constraints', '*.xdc'),
        ('tests/rtl', 'tests', 'tb_*.v')):
        (src / target).mkdir(parents=True)
        for path in (ROOT / rel).glob(pattern):
            dest = src / target / path.name
            shutil.copy2(path, dest)
            inputs[str(dest.relative_to(out)).replace('\\', '/')] = sha(dest)
    for name in ('bench_build.tcl', 'bench_vivado.ps1', 'bench_lease_sim.ps1', 'bench_capture_sim.ps1', 'bench_build.py'):
        shutil.copy2(ROOT / 'tools' / name, src / name)
        inputs['source/' + name] = sha(src / name)
    project = ET.parse(ROOT / 'usb3-tester.xpr')
    part = project.find("./Configuration/Option[@Name='Part']").attrib['Val']
    if part != PART:
        raise ValueError(f'Unexpected FPGA part: {part}; uploader target needs review')
    manifest = {'schema': 'usb3-bench-build', 'version': 1, 'state': 'building',
                'created_utc': datetime.now(timezone.utc).isoformat(), 'part': part,
                'board': 'AuV2', 'vivado': str(vivado), 'source_sha256': inputs}
    manifest['runtime_build_id'] = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:8]
    atomic_json(out / 'manifest.json', manifest)
    print(f'Build directory: {out}', flush=True)
    try:
        sim = out / 'simulation'
        sim.mkdir()
        print('Testing reset and transmit lease...', flush=True)
        text = run_logged(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
                           src / 'bench_lease_sim.ps1', '-Bin', vivado.parent,
                           '-Source', src / 'rtl/ctrl_decode.v',
                           '-Testbench', src / 'tests/tb_ctrl_lease.v'],
                          sim, out / 'lease-test.log', timeout=180)
        if 'LEASE_TEST_PASS' not in text:
            raise RuntimeError('Lease simulation did not report success')
        print('Testing capture backpressure and complete element order...', flush=True)
        text = run_logged(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
                           src / 'bench_capture_sim.ps1', '-Bin', vivado.parent,
                           '-Source', src / 'rtl', '-Testbench', src / 'tests/tb_capture_ready.v'],
                          sim, out / 'capture-test.log', timeout=180)
        if text.count('CAPTURE_READY_TEST_PASS') != 4:
            raise RuntimeError('Capture-ready simulation did not report success')
        manifest['capture_ready_simulation']='passed'
        print('Both simulations passed. Synthesizing and routing frozen inputs...', flush=True)
        text = run_logged(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
                           src / 'bench_vivado.ps1', '-Vivado', vivado,
                           '-Script', src / 'bench_build.tcl', '-Source', src,
                           '-Output', out, '-Part', part, '-BuildId', manifest['runtime_build_id']], out, out / 'build.log')
        if 'BENCH_BUILD_PASS' not in text or not (out / 'alchitry_top.bin').is_file():
            raise RuntimeError('Build did not produce a validated bitstream')
        checks = json.loads((out / 'checks.json').read_text())
        if checks['setup_slack_ns'] < 0 or checks['hold_slack_ns'] < 0 or checks['drc_failures']:
            raise RuntimeError('Build failed timing/DRC checks')
        manifest.update(state='passed', checks=checks, capabilities=CAPABILITIES,
                        bitstream_sha256=sha(out / 'alchitry_top.bin'), lease_simulation='passed')
        print(f'Build passed: {checks}', flush=True)
    except BaseException as exc:
        manifest.update(state='failed', error=str(exc))
        raise
    finally:
        atomic_json(out / 'manifest.json', manifest)
    return out


def validated_build(directory):
    directory = Path(directory).resolve()
    m = json.loads((directory / 'manifest.json').read_text())
    if (m.get('schema') != 'usb3-bench-build' or m.get('state') != 'passed'
            or m.get('part') != PART or m.get('board') != 'AuV2'
            or m.get('lease_simulation') != 'passed'
            or not set(BASE_CAPABILITIES) <= set(m.get('capabilities', []))
            or ('capture_ready_interlock_v1' in m.get('capabilities', []) and m.get('capture_ready_simulation') != 'passed')):
        raise ValueError('Build has not passed the required checks')
    checks = m['checks']
    if any(not math.isfinite(checks[k]) or checks[k] < 0 for k in ('setup_slack_ns', 'hold_slack_ns')) or checks['drc_failures']:
        raise ValueError('Build timing/DRC checks failed')
    if sha(directory / 'alchitry_top.bin') != m['bitstream_sha256']:
        raise ValueError('Bitstream hash differs from the tested build manifest')
    for rel, digest in m['source_sha256'].items():
        p = (directory / rel).resolve()
        if not p.is_relative_to(directory) or sha(p) != digest:
            raise ValueError(f'Frozen build input changed: {rel}')
    return m


def board_index(listing):
    # Current V2 CLI reports a count per model, rather than numbered devices.
    counts = re.findall(r'^\s*Detected (\d+) Alchitry Au V2(?: 35T)?\s*$', listing, re.MULTILINE)
    if counts:
        if counts == ['1']:
            return '0'  # --device is zero-based within the selected --board model
        raise RuntimeError('Expected exactly one detected Au V2; inspect boards.log')
    boards = re.findall(r'^\s*(\d+)\s*[:.)-]\s*(?:Alchitry\s+)?Au\s*V2(?: 35T)?\s*$', listing,
                        re.MULTILINE | re.IGNORECASE)
    if len(boards) != 1:
        raise RuntimeError('Expected exactly one detected Au V2; inspect boards.log before selecting a device')
    return boards[0]


def program(directory, uploader, control_dir, flash=False):
    directory = Path(directory).resolve()
    manifest = validated_build(directory)
    # Close the controlled host before resetting hardware. Its response follows
    # disarming; waiting for process exit releases the D3XX acquisition handle.
    control_dir = Path(control_dir).resolve()
    from bench_client import request, server_alive, server_info, pid_alive
    previous = server_info(control_dir)
    if server_alive(control_dir):
        request(control_dir, {'op': 'shutdown'}, timeout=15)
    deadline = time.monotonic() + 15
    while pid_alive(previous.get('pid')) and time.monotonic() < deadline:
        time.sleep(.1)
    if pid_alive(previous.get('pid')):
        raise RuntimeError('Acquisition host did not close; programming cancelled')
    lock = ROOT / 'bench_runs/program.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('x') as lock_file:
        lock_file.write(str(os.getpid()))
    receipt_path = ROOT / 'bench_runs/program-receipt.json'
    receipt = {'state': 'programming', 'build_dir': str(directory),
               'bitstream_sha256': manifest['bitstream_sha256']}
    atomic_json(receipt_path, receipt)
    try:
        listing = run_logged([uploader, 'load', '--list'], directory,
                             directory / 'boards.log', timeout=30)
        print(listing, flush=True)
        index = board_index(listing)
        model = 'AuV2-35T' if 'Alchitry Au V2 35T' in listing else 'AuV2'
        storage = 'flash' if flash else 'ram'
        output = run_logged([uploader, 'load', '--board', model, '--device', index,
                             '--' + storage, '--bin', directory / 'alchitry_top.bin'],
                            directory, directory / 'program.log', timeout=120)
        if not re.search(r'^Done\.?\s*$', output, re.MULTILINE | re.IGNORECASE):
            raise RuntimeError('Uploader did not report completion; acquisition remains blocked')
        warnings = [line.strip() for line in output.splitlines() if 'overflow' in line.lower()]
        if warnings:
            receipt['loader_warnings'] = warnings
            print('\n'.join(warnings), flush=True)
        receipt.update(state='programmed', programmed_utc=datetime.now(timezone.utc).isoformat(),
                       capabilities=manifest['capabilities'], board=model, storage=storage, device_index=int(index),
                       manifest_sha256=sha(directory / 'manifest.json'),
                       runtime_build_id=manifest['runtime_build_id'],
                       provenance_note='Uploader operation and file hashes; host verifies runtime build tag before each capture')
    except BaseException as exc:
        receipt.update(state='failed', error=str(exc))
        raise
    finally:
        atomic_json(receipt_path, receipt)
        lock.unlink(missing_ok=True)
    print(f'{storage.upper()} programmed; transmit starts off. Receipt: {receipt_path}', flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='op', required=True)
    sub.add_parser('doctor')
    b = sub.add_parser('build')
    b.add_argument('--vivado', type=Path, default=DEFAULT_VIVADO)
    b.add_argument('--output', type=Path)
    u = sub.add_parser('program')
    u.add_argument('build_dir', type=Path)
    u.add_argument('--flash', action='store_true', help='Program persistent flash instead of temporary RAM')
    u.add_argument('--uploader', default=shutil.which('alchitry') or 'alchitry')
    u.add_argument('--control-dir', type=Path, default=ROOT / 'bench_runs/control')
    args = p.parse_args()
    if args.op == 'doctor':
        print(json.dumps({'vivado': str(DEFAULT_VIVADO), 'vivado_found': DEFAULT_VIVADO.is_file(),
                          'uploader': shutil.which('alchitry'), 'project_part': PART,
                          'board': 'AuV2', 'programming_mode': 'RAM by default; --flash for persistent programming'}, indent=2))
    elif args.op == 'build':
        build(args.vivado, args.output)
    else:
        program(args.build_dir, args.uploader, args.control_dir, flash=args.flash)


if __name__ == '__main__':
    main()
