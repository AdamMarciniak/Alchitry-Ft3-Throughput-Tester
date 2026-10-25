"""Launch/control a bench host and run repeatable wire-image experiments.

python tools/bench.py experiment --sim
python tools/bench.py experiment --session recording.rf.npz
python tools/bench.py experiment --bench-ready --build BUILD_DIRECTORY
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import html
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from bench_client import request, server_alive, server_info, pid_alive
from rf_debug import atomic_json, load_session


def stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]


def start(directory, simulation=False, ready=False):
    directory = Path(directory).resolve()
    if server_alive(directory):
        status = request(directory, {'op': 'status'})
        expected = 'simulation' if simulation else 'hardware'
        if status['source'] != expected:
            raise RuntimeError('Existing host has a different source; stop it or use another control directory')
        return status
    # A shutdown response precedes USB/worker cleanup and actual process exit.
    previous = server_info(directory)
    deadline = time.monotonic() + 15
    while pid_alive(previous.get('pid')) and time.monotonic() < deadline:
        time.sleep(.1)
    if pid_alive(previous.get('pid')):
        raise RuntimeError('Previous host has not exited; wait for it to release USB')
    directory.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, str(ROOT / 'host/bench_host.py'), '--control-dir', str(directory)]
    if simulation:
        argv += ['--sim']
    elif ready:
        argv += ['--bench-ready']
    else:
        raise ValueError('Hardware runs require the fixed wire-in-water bench to be ready')
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    with (directory / 'host.log').open('w', encoding='utf-8') as stream:
        proc = subprocess.Popen(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                creationflags=flags)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        info = server_info(directory)
        if info.get('pid') == proc.pid and info.get('state') == 'running':
            return request(directory, {'op': 'status'})
        if proc.poll() is not None:
            raise RuntimeError((directory / 'host.log').read_text(errors='replace')[-5000:])
        time.sleep(.1)
    proc.terminate()
    proc.wait(5)
    raise TimeoutError(f'Bench host did not become ready; see {directory / "host.log"}')


def merged(first, second):
    value = copy.deepcopy(first)
    for section, fields in second.items():
        value.setdefault(section, {}).update(fields)
    return value


def score(metric, baseline):
    """Provisional finite-wire tradeoff, evaluated only on ordinary DAS."""
    for item in (metric, baseline):
        if item['view'] != 'ordinary_DAS' or not item['quality']['valid']:
            return None
        if any(not math.isfinite(item[k]) for k in ('peak', 'normalized_peak',
                'clutter_p95_relative_db', 'clutter_to_target_energy')):
            return None
    wl, wa = metric['lateral_width_6db_mm'], metric['axial_width_6db_mm']
    bl, ba = baseline['lateral_width_6db_mm'], baseline['axial_width_6db_mm']
    if not all(x is not None and x > 0 and math.isfinite(x) for x in (wl,wa,bl,ba)):
        return None
    retained = metric['normalized_peak'] / max(baseline['normalized_peak'], 1e-12)
    if retained < .5 or baseline['peak'] <= 0:
        return None
    if (metric['clutter_p95_relative_db'] > baseline['clutter_p95_relative_db'] + 3 or
            metric['clutter_to_target_energy'] > max(baseline['clutter_to_target_energy']*1.5, 1e-8)):
        return None  # do not buy a narrow wire response with much stronger side arcs
    clutter_ratio = (metric['clutter_to_target_energy']+1e-8)/(baseline['clutter_to_target_energy']+1e-8)
    return (math.log(wl/bl) + .25*math.log(wa/ba) + .15*math.log(clutter_ratio)
            + .2*math.log(max(1, 1/retained)))


def report_html(path, summary):
    root = Path(path).parent
    rows = []
    for trial in summary['trials']:
        m = trial['metrics']
        label = html.escape(trial['name'])
        image = html.escape(Path(trial['image']).relative_to(root).as_posix())
        fmt = lambda v: 'unresolved' if v is None else f'{v:.3f}'
        rows.append(f'<tr><td><a href="{image}">{label}</a></td><td>{fmt(trial.get("score"))}</td>'
                    f'<td>{fmt(m["lateral_width_6db_mm"])}</td><td>{fmt(m["axial_width_6db_mm"])}</td>'
                    f'<td>{m["clutter_p95_relative_db"]:.1f}</td><td>{m["normalized_peak"]:.4f}</td></tr>')
    images = []
    for name in ('baseline', summary['selected_trial'], 'display-cf-0.25', 'display-cf-0.5', 'display-cf-1.0', 'coherence-map'):
        trial = next((t for t in summary['trials'] if t['name'] == name), None)
        if trial:
            src = html.escape(Path(trial['image']).relative_to(root).as_posix())
            images.append(f'<figure><figcaption>{html.escape(name)}</figcaption><a href="{src}"><img src="{src}"></a></figure>')
    document = ('<!doctype html><meta charset="utf-8"><title>Wire bench experiment</title>'
                '<style>body{font:16px system-ui;background:#101418;color:#dce5ee;max-width:1250px;margin:30px auto;padding:0 20px}'
                'a{color:#85c7ff}table{border-collapse:collapse;width:100%}td,th{padding:9px;text-align:left;border-bottom:1px solid #334}'
                '.images{display:grid;grid-template-columns:1fr 1fr;gap:20px}figure{margin:0}img{width:100%}figcaption{padding:10px 0}'
                'pre{white-space:pre-wrap;background:#1a242d;padding:18px}</style>'
                f'<h1>Wire bench experiment · {html.escape(summary["source"])}</h1>'
                f'<p>{html.escape(summary["conclusion"])}</p>'
                '<p>Scores use linear ordinary-DAS data with fixed physical regions. Lower is preferred; '
                'candidates losing more than half the normalized reflector peak, increasing clutter p95 by over 3 dB, '
                'or increasing clutter energy ratio by over 50% are rejected. '
                'Coherence-weighted images are comparisons only. A wire cannot establish tissue texture quality.</p>'
                f'<div class="images">{"".join(images)}</div><h2>Measured trials</h2><table><tr><th>Trial</th><th>Score</th>'
                '<th>Lateral −6 dB mm</th><th>Axial −6 dB mm</th><th>Clutter p95 dB</th><th>Normalized peak</th></tr>'
                + ''.join(rows) + '</table><h2>Validation</h2><pre>'
                + html.escape(json.dumps(summary['validation'], indent=2)) + '</pre>')
    Path(path).write_text(document, encoding='utf-8')


def experiment(args):
    if args.session and args.settings:
        raise ValueError('Offline experiments use the recording settings; --settings is for new acquisitions')
    directory = args.control_dir.resolve()
    out = ROOT / 'bench_runs/experiments' / stamp()
    out.mkdir(parents=True)
    if args.build:
        if args.sim or args.session:
            raise ValueError('Programming a build is a hardware experiment; omit --sim/--session')
        if not args.bench_ready:
            raise ValueError('Prepare the fixed bench target before programming/running a hardware experiment')
        from bench_build import program
        import shutil
        program(args.build, shutil.which('alchitry') or 'alchitry', directory)
    start(directory, simulation=args.sim or args.session is not None, ready=args.bench_ready)
    status = request(directory, {'op': 'status'})
    source = status['source']
    summary = {'created_utc': datetime.now(timezone.utc).isoformat(), 'source': source,
               'trials': [], 'validation': [], 'state': 'running',
               'objective_version': 2,
               'objective': 'Minimize log lateral width + 0.25 log axial width + 0.15 log clutter-energy ratio + 0.2 log peak-loss penalty, relative to baseline. Reject >50% normalized peak loss, >3 dB clutter-p95 increase, or >50% clutter-energy increase. Validate score < -0.03 on two other frames.',
               'source_hashes': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in [ROOT/'tools/bench.py', ROOT/'host/bench_host.py', ROOT/'host/bench_render.py', ROOT/'host/bench_client.py', ROOT/'host/bench_transport.py']}}
    atomic_json(out / 'experiment.json', summary)
    try:
        if args.session:
            path = args.session.resolve()
        else:
            if args.settings:
                document = json.loads(args.settings.read_text(encoding='utf-8-sig'))
                request(directory, {'op': 'configure', 'settings': document})
                summary['input_settings_file'] = str(args.settings.resolve())
                summary['input_settings_sha256'] = hashlib.sha256(args.settings.read_bytes()).hexdigest()
            capture = request(directory, {'op': 'capture', 'frames': args.frames,
                              'timeout_s': 20, 'output': str(out / 'acquisition'), 'note': args.note}, timeout=45)
            if not capture['accepted']:
                raise RuntimeError(f'Acquisition did not pass integrity/frame-count checks: {capture}')
            path = Path(capture['session'])
        session = load_session(path)
        try:
            settings = copy.deepcopy(session.metadata.get('review_settings', session.metadata['acquired_settings']))
            indices = [i for i,q in enumerate(session.quality) if q['valid']]
            count = len(session.rf)
            source = session.metadata['acquired_settings'].get('source', source)
        finally:
            session.close()
        if len(indices) < 3:
            raise ValueError('Need at least three valid frames for search and held-frame validation')
        summary.update(source=source, session=str(path), frame_count=count)
        training, held = indices[0], [indices[len(indices)//2], indices[-1]]
        anchor = None
        def trial(name, patch, frame=training):
            item = request(directory, {'op': 'render', 'session': str(path), 'frame': frame,
                            'settings': patch, 'box_mm': args.box_mm, 'search_mm': args.search_mm,
                            'anchor_mm': anchor, 'output': str(out / name)}, timeout=60)
            item.update(name=name, patch=copy.deepcopy(patch))
            summary['trials'].append(item)
            print(f'{name}: width={item["metrics"]["lateral_width_6db_mm"]} mm, '
                  f'clutter={item["metrics"]["clutter_p95_relative_db"]:.1f} dB', flush=True)
            return item
        current_patch = {'receive': {'avg_sweeps': 1, 'frequency_compounding': False,
                                     'bg_subtract': False, 'dejitter_on': False},
                         'beamformer': {'cf': 0}, 'display': {'debug_view': 1, 'auto_gain': False,
                                                            'dyn_db': 80, 'curve': 1}}
        reference = trial('display-reference', current_patch)
        if reference['metrics']['clutter_p95_relative_db'] > -10:
            raise ValueError('No sufficiently distinct reflector in the search region; inspect the reference image and RF before optimizing')
        current_patch['display']['gain_db'] = min(40, max(-40,
            -20*math.log10(max(reference['metrics']['normalized_peak'], 1e-12))-8))
        summary['display_reference'] = 'Baseline target mapped near 90% gray at 80 dB range; gain held fixed thereafter. Linear RF/image metrics are independent of this display adjustment.'
        baseline = trial('baseline', current_patch)
        anchor = baseline['metrics']['peak_position_mm']
        baseline['score'] = score(baseline['metrics'], baseline['metrics'])
        if baseline['score'] is None:
            raise ValueError('Baseline target is unresolved or invalid; inspect baseline/image-axes.png and refine the target region')
        best = baseline
        centre = settings['beamformer']['t0_ns']
        groups = [
            ('t0', [{'beamformer': {'t0_ns': v}} for v in sorted(set(max(-2000, min(4000, centre+d)) for d in (-1000,-500,0,500,1000,2000)))]),
            ('band', [{'receive': {'bandpass_on': True, 'band_f0_mhz': f, 'band_bw_mhz': b}} for f in (3,3.5,4) for b in (3,5)]),
            ('apod', [{'beamformer': {'apod': v}} for v in (0,.5,.74,1)]),
            ('matched', [{'receive': {'matched_filter': v}} for v in (False,True)])]
        for group, choices in groups:
            entering = copy.deepcopy(best['patch'])
            for i, change in enumerate(choices):
                item = trial(f'{group}-{i}', merged(entering, change))
                item['score'] = score(item['metrics'], baseline['metrics'])
                if item['score'] is not None and item['score'] < best['score']:
                    best = item
                atomic_json(out / 'experiment.json', summary)
        validated = best is not baseline
        for i, frame in enumerate(held):
            b = trial(f'validation-{i}-baseline', baseline['patch'], frame)
            candidate = trial(f'validation-{i}-candidate', best['patch'], frame)
            value = score(candidate['metrics'], b['metrics'])
            summary['validation'].append({'frame': frame, 'score': value, 'passed': value is not None and value < -.03})
            validated &= value is not None and value < -.03
        selected = best if validated else baseline
        for cf in (.25, .5, 1.0):
            trial(f'display-cf-{cf}', merged(selected['patch'], {'beamformer': {'cf': cf}, 'display': {'debug_view': 0}}))
        trial('coherence-map', merged(selected['patch'], {'display': {'debug_view': 2}}))
        selected_settings = json.loads((Path(selected['output']) / 'settings.json').read_text())
        selected_settings['transmit']['armed'] = False
        selected_settings['note'] = 'Wire-bench candidate; validate another target position before generalizing'
        atomic_json(out / 'selected-settings.json', selected_settings)
        summary.update(state='complete', selected_trial=selected['name'], improvement_validated=bool(validated),
                       conclusion=('A candidate improved the declared wire score on separate frames; test another target position next.'
                                   if validated else 'No candidate cleared the separate-frame improvement threshold; baseline retained.'))
        if source == 'simulation':
            summary['conclusion'] = 'SIMULATION REHEARSAL ONLY. ' + summary['conclusion'] + ' This is not evidence of improvement on the physical probe.'
        report_html(out / 'report.html', summary)
        print(f'Experiment saved: {out}', flush=True)
    except BaseException as exc:
        summary.update(state='failed', error=str(exc))
        raise
    finally:
        atomic_json(out / 'experiment.json', summary)
        try:
            request(directory, {'op': 'stop'}, timeout=10)
        except Exception:
            pass  # FPGA lease expires independently if the host cannot respond
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--control-dir', type=Path, default=ROOT / 'bench_runs/control')
    sub = p.add_subparsers(dest='op', required=True)
    launch = sub.add_parser('start')
    launch.add_argument('--sim', action='store_true')
    launch.add_argument('--bench-ready', action='store_true')
    sub.add_parser('status')
    sub.add_parser('stop')
    sub.add_parser('shutdown')
    send = sub.add_parser('request')
    send.add_argument('json_file', type=Path)
    configure = sub.add_parser('configure')
    configure.add_argument('settings_file', type=Path)
    e = sub.add_parser('experiment')
    e.add_argument('--sim', action='store_true')
    e.add_argument('--bench-ready', action='store_true')
    e.add_argument('--build', type=Path)
    e.add_argument('--session', type=Path)
    e.add_argument('--settings', type=Path, help='Restore a settings JSON before a new capture; waveform must match the session baseline')
    e.add_argument('--frames', type=int, default=16)
    e.add_argument('--note', default='Fixed wire in water; automated bench experiment')
    e.add_argument('--box-mm', type=float, nargs=4, default=[-50,50,0,140], metavar=('X0','X1','Z0','Z1'))
    e.add_argument('--search-mm', type=float, nargs=4, default=[-20,20,40,110], metavar=('X0','X1','Z0','Z1'))
    args = p.parse_args()
    if args.op == 'start':
        result = start(args.control_dir, args.sim, args.bench_ready)
    elif args.op == 'experiment':
        result = {'experiment': str(experiment(args))}
    elif args.op == 'request':
        result = request(args.control_dir, json.loads(args.json_file.read_text()), timeout=60)
    elif args.op == 'configure':
        result = request(args.control_dir, {'op': 'configure',
                         'settings': json.loads(args.settings_file.read_text(encoding='utf-8-sig'))})
    else:
        result = request(args.control_dir, {'op': args.op})
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
