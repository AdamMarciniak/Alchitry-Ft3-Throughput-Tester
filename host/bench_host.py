"""Locally controlled acquisition host for fixed wire-in-water bench experiments.

Simulation: python host/bench_host.py --sim --control-dir bench_runs/control
Hardware additionally requires --bench-ready and a validated programming receipt.
The offscreen renderer uses the same shaders and receive pipeline as tfm_gl_host.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import uuid

import numpy as np
import rf_debug as files
from pulse_methods import fpga_method
from bench_client import pid_alive, server_info
from bench_render import Renderer, wire_metrics

ROOT = Path(__file__).resolve().parents[1]
WAVEFORM_FIELDS = ('shot_method', 'chirp_on', 'chirp_f0_mhz', 'chirp_f1_mhz', 'chirp_us',
                   'n_cycles', 't_drive_ns', 't_dead_ns')


def bounded_number(value, low, high, label, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number')
    if not low <= value <= high or integer and int(value) != value:
        raise ValueError(f'{label} must be in [{low}, {high}]')
    return int(value) if integer else float(value)


def output_directory(path):
    p = Path(path).resolve()
    if not p.is_relative_to(ROOT / 'bench_runs'):
        raise ValueError('Bench output must stay inside this project\'s bench_runs folder')
    p.mkdir(parents=True, exist_ok=False)
    return p


def receipt(path):
    sys.path.insert(0, str(ROOT / 'tools'))
    from bench_build import validated_build, sha
    value = json.loads(Path(path).read_text())
    if value.get('state') != 'programmed':
        raise ValueError('Hardware acquisition requires a successful programming receipt')
    manifest = validated_build(value['build_dir'])
    if (value['bitstream_sha256'] != manifest['bitstream_sha256'] or
            value['manifest_sha256'] != sha(Path(value['build_dir']) / 'manifest.json')):
        raise ValueError('Programming receipt does not match the checked FPGA build')
    return value


class Control:
    def __init__(self, host, window, app, directory, programmed, ready):
        from PySide6.QtCore import QTimer
        self.h, self.w, self.app = host, window, app
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        previous = server_info(self.directory)
        # Windows may immediately reuse the exited host's PID for this process.
        if previous.get('pid') != os.getpid() and pid_alive(previous.get('pid')):
            raise RuntimeError('A bench host already owns this control directory')
        self.server_id = uuid.uuid4().hex
        self.ready, self.programmed = ready, programmed
        self.active = None
        self.closed = False
        self.renewed = 0
        self.last_status = 0
        self.renderer = Renderer(host)
        self.base = host.settings_snapshot(window)
        self.waveform = {k: self.base['transmit'][k] for k in WAVEFORM_FIELDS}
        window.b_freeze.setChecked(True)  # idle server must not accumulate a 2 GiB cine
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(25)
        # The GUI/worker still exist, but all acquisitions are bounded by the
        # controller. No GUI background reference or changing controls mid-shot.
        window.setEnabled(False)
        for pending in self.directory.glob('*.processing.json'):
            try:
                command = json.loads(pending.read_text())
                self.respond(command, error='Previous host exited during this request')
            finally:
                pending.unlink(missing_ok=True)
        self.publish_status()

    def status(self):
        return {'pid': os.getpid(), 'server_id': self.server_id,
                'state': 'closed' if self.closed else 'running',
                'heartbeat_unix': time.time(), 'source': 'hardware' if self.h.HW else 'simulation',
                'pulser_requested_armed_now': self.h.pulser.arm,
                'active_operation': 'capture' if self.active else None,
                'frames': self.h.cine.status()[0],
                'drain_words': self.h.debug_discard_words,
                'settings': self.h.settings_snapshot(self.w),
                'programming': self.programmed,
                'scope': 'fixed wire-in-water; transmit waveform unchanged; software does not control HV supply'}

    def publish_status(self):
        files.atomic_json(self.directory / 'server.json', self.status())
        self.last_status = time.monotonic()

    def respond(self, command, result=None, error=None):
        key = command['id']
        if len(key) != 32 or any(c not in '0123456789abcdef' for c in key):
            raise ValueError('Invalid request ID')
        files.atomic_json(self.directory / (key + '.response.json'),
                          {'ok': error is None, 'result': result, 'error': error,
                           'finished_unix': time.time()})

    def stop_transmit(self):
        # Bypass replay's command suppression only for the lease release; first
        # disarm through the existing path, then release the optional watchdog.
        self.h.pulser.set_arm(False)
        if self.h.HW:
            old = self.h.debug_replay_only
            try:
                self.h.debug_replay_only = False
                self.h.send_cmd(self.h.cmd(0x1e, 0), 'bench_lease_release')
            finally:
                self.h.debug_replay_only = old
        self.w.cb_arm.setChecked(False)

    def configure(self, supplied):
        value = files.validate_settings(supplied, self.h.settings_snapshot(self.w))
        requested = {k: value['transmit'][k] for k in WAVEFORM_FIELDS}
        expected = self.waveform.copy()
        for waveform in (requested, expected):
            waveform['shot_method'] = fpga_method(waveform['shot_method'])
        if requested != expected:
            raise ValueError('This bench session keeps the transmit waveform unchanged')
        if self.w.debug_offline:
            self.w.debug_new_live()
        self.w.b_freeze.setChecked(False)
        self.w.debug_apply(value)
        self.w.debug_tick()
        self.w.b_freeze.setChecked(True)
        return self.h.settings_snapshot(self.w)

    def begin_capture(self, command):
        if self.h.HW and (not self.ready or not self.programmed):
            raise RuntimeError('Fixed bench target and programmed lease firmware are required')
        count = bounded_number(command.get('frames', 16), 1, 256, 'frames', True)
        seconds = bounded_number(command.get('timeout_s', 15), 1, 30, 'timeout_s')
        if self.h.HW:
            current = receipt(ROOT / 'bench_runs/program-receipt.json')
            if current != self.programmed:
                raise RuntimeError('FPGA was programmed since this host started; restart the host')
        if self.w.debug_offline:
            self.w.debug_new_live()
        self.w.b_freeze.setChecked(False)
        self.w.debug_dirty = True
        self.w.debug_note.setText(str(command.get('note', 'Automated wire bench run')))
        self.w.debug_tick()
        if not self.h.stats['alive']:
            raise RuntimeError('Acquisition worker stopped; restart the host')
        firmware_info = None
        if self.h.HW:
            from bench_transport import query_firmware, check_configuration
            try:
                firmware_info = query_firmware(self.h, self.programmed['runtime_build_id'])
                check_configuration(self.h, self.w, firmware_info)
            except BaseException:
                self.stop_transmit()
                raise
        out = output_directory(command['output'])
        self.active = {'command': command, 'output': out, 'frames': count,
                       'deadline': time.monotonic()+seconds, 'start': time.monotonic(),
                       'firmware_readback': firmware_info}
        if self.h.HW:
            self.h.send_cmd(self.h.cmd(0x1e, 2000), 'bench_lease_renew')
            self.renewed = time.monotonic()
        self.h.pulser.set_arm(True)
        self.w.debug_tick()

    def finish_capture(self, reason=None):
        active, self.active = self.active, None
        if active is None:
            return
        command, out = active['command'], active['output']
        try:
            self.stop_transmit()
            self.w.b_freeze.setChecked(True)
            items = self.w.review[-active['frames']:]
            qualities = copy.deepcopy(self.w.debug_review_quality[-active['frames']:])
            if not items:
                raise RuntimeError(reason or 'Capture produced no complete sweep')
            settings = self.h.settings_snapshot(self.w, self.w.debug_note.text())
            meta = {'created_utc': datetime.now(timezone.utc).isoformat(),
                    'acquired_settings': copy.deepcopy(self.w.debug_epoch),
                    'review_settings': settings,
                    'context': {'note': self.w.debug_note.text(), 'setup': self.w.debug_setup},
                    'provenance': self.w.debug_source, 'programming_receipt': self.programmed,
                    'firmware_readback_before_arm': active['firmware_readback'],
                    'command_log': copy.deepcopy(self.w.debug_events),
                    'bench': {'request': command, 'termination': reason or 'frame count reached',
                              'elapsed_s': time.monotonic()-active['start'],
                              'ready_asserted': self.ready, 'requested_lease_ms': 2000 if self.h.HW else None}}
            if active['firmware_readback'] is not None:
                meta['provenance'] = copy.deepcopy(self.w.debug_source)
                meta['provenance'].update(
                    loaded_fpga_build=active['firmware_readback']['runtime_build_id'],
                    hardware_register_readback='Subset verified before ARM; see firmware_readback_before_arm. Analog voltages and AFE registers are not read back.')
            path = out / 'capture.rf.npz'
            times = np.array([item[0] for item in items]); times -= times[0]
            frames = [item[1] for item in items]
            files.save_session(path, frames, times, meta, qualities, self.h.mf_reference(), self.h.bg['ref'])
            report = files.diagnostics(frames, qualities, shot_method=self.h.pulser.shot_method)
            files.atomic_json(out / 'capture.report.json', report)
            files.atomic_json(out / 'settings.json', settings)
            result = {'session': str(path), 'report': str(out / 'capture.report.json'),
                      'frames': len(items), 'accepted': reason is None and all(q['valid'] for q in qualities),
                      'termination': reason or 'frame count reached',
                      'source': 'hardware' if self.h.HW else 'simulation'}
            files.atomic_json(out / 'result.json', result)
            self.respond(command, result=result)
        except Exception as exc:
            files.atomic_json(out / 'failure.json', {'error': str(exc), 'request': command})
            self.respond(command, error=str(exc))

    def render(self, command):
        path = Path(command['session']).resolve()
        if getattr(self, 'loaded_path', None) != path or not self.w.debug_session:
            self.stop_transmit()
            self.w.debug_open_rf(path, raise_errors=True)
            self.loaded_path = path
        patch = command.get('settings', {})
        if not isinstance(patch, dict) or not set(patch) <= {'receive', 'beamformer', 'display'}:
            raise ValueError('Replay changes must be receive, beamformer, or display settings')
        session = self.w.debug_session
        # Every candidate starts from the saved baseline, never the previous trial.
        base = copy.deepcopy(session.metadata.get('review_settings', session.metadata['acquired_settings']))
        base['acquisition'] = session.metadata['acquired_settings']['acquisition']
        base['transmit'] = session.metadata['acquired_settings']['transmit']
        desired = files.validate_settings(patch or {'display': {}}, base)
        self.w.debug_apply(desired, replay=True)
        self.h.bg['ref'] = session.background
        self.h.bg['on'] = bool(desired['receive'].get('bg_subtract') and session.background is not None)
        frame = bounded_number(command.get('frame', 0), 0, len(session.rf)-1, 'frame', True)
        box = command.get('box_mm', [-50, 50, 0, 140])
        search = command.get('search_mm', [-20, 20, 40, 110])
        for label, values in [('box_mm', box), ('search_mm', search)]:
            if not isinstance(values, list) or len(values) != 4:
                raise ValueError(f'{label} needs x0,x1,z0,z1')
            for value in values:
                bounded_number(value, -1000, 1000, label)
            if values[0] >= values[1] or values[2] >= values[3]:
                raise ValueError(f'{label} is not ordered')
        anchor = command.get('anchor_mm')
        if anchor is not None:
            if not isinstance(anchor, list) or len(anchor) != 2:
                raise ValueError('anchor_mm needs x,z')
            for value in anchor:
                bounded_number(value, -1000, 1000, 'anchor_mm')
        out = output_directory(command['output'])
        transformed = self.h.prepare_analytic(self.w._review_rf(frame), self.h.cfg['samps'], live=False)
        mag, image = self.renderer.render(transformed, box)
        np.save(out / 'magnitude.npy', mag, allow_pickle=False)
        if not image.save(str(out / 'image.png')):
            raise OSError('Could not save rendered image')
        view_name = ['weighted', 'DAS', 'CF map'][self.h.state.get('debug_view', 0)]
        source_name = session.metadata['acquired_settings'].get('source', 'RF')
        caption = f"{source_name} | {view_name} | t0 {self.h.state['t0_ns']:g} ns"
        capture = self.h.Capture(image, tuple(v/1000 for v in box), [], caption)
        capture.n, capture.stamp = frame, ''
        annotated = self.h.render_capture(capture, s=1)
        if not annotated.save(str(out / 'image-axes.png')):
            raise OSError('Could not save annotated image')
        settings = self.h.settings_snapshot(self.w)
        settings['display']['grid'] = [mag.shape[1], mag.shape[0]]
        metric = wire_metrics(mag, box, search, anchor)
        metric.update(normalized_peak=metric['peak']/self.h.full_scale(self.h.state['apod'], getattr(transformed, 'bank', None)),
                      frame=frame, quality=session.quality[frame], box_mm=box,
                      view=['weighted', 'ordinary_DAS', 'coherence_map'][self.h.state.get('debug_view', 0)])
        files.atomic_json(out / 'metrics.json', metric)
        files.atomic_json(out / 'settings.json', settings)
        return {'output': str(out), 'image': str(out / 'image-axes.png'), 'metrics': metric}

    def execute(self, command):
        op = command.get('op')
        if op == 'status':
            return self.status()
        if op == 'stop':
            self.finish_capture('cancelled')
            self.stop_transmit()
            return {'stopped': True}
        if op == 'shutdown':
            self.finish_capture('host shutdown')
            self.stop_transmit()
            self.closed = True
            self.publish_status()
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, self.app.quit)
            return {'closed': True}
        if self.active:
            raise RuntimeError('A capture is active; wait or stop it before changing settings')
        if op == 'configure':
            return self.configure(command['settings'])
        if op == 'capture':
            try:
                self.begin_capture(command)
            except BaseException:
                self.stop_transmit()
                self.w.b_freeze.setChecked(True)
                if self.active:
                    self.finish_capture('capture startup failed')
                raise
            return None
        if op == 'render':
            return self.render(command)
        raise ValueError('Unknown operation')

    def tick(self):
        if self.closed:
            return
        try:
            if self.active:
                now = time.monotonic()
                if not self.h.stats['alive']:
                    self.finish_capture('acquisition worker stopped')
                elif now >= self.active['deadline']:
                    self.finish_capture('timeout before requested frame count')
                elif self.h.cine.status()[0] >= self.active['frames']:
                    self.finish_capture()
                elif self.h.HW and now-self.renewed >= .25:
                    self.h.send_cmd(self.h.cmd(0x1e, 2000), 'bench_lease_renew')
                    self.renewed = now
            for path in sorted(self.directory.glob('*.request.json'))[:1]:
                command = None
                processing = path.with_name(path.name.replace('.request.json', '.processing.json'))
                try:
                    if path.stat().st_size > 262144:
                        raise ValueError('Request is too large')
                    path.rename(processing)
                    command = json.loads(processing.read_text())
                    if command['server_id'] != self.server_id:
                        raise ValueError('Request belongs to another host session')
                    if not 0 <= time.time()-command['created_unix'] <= command['ttl_s'] <= 300:
                        raise ValueError('Request expired or TTL is invalid')
                    result = self.execute(command)
                    if command.get('op') != 'capture' or result is not None:
                        self.respond(command, result=result)
                except Exception as exc:
                    if command:
                        self.respond(command, error=str(exc))
                    else:
                        print(f'Rejected request {path.name}: {exc}', flush=True)
                finally:
                    processing.unlink(missing_ok=True)
            if time.monotonic()-self.last_status > 1:
                self.publish_status()
        except BaseException as exc:
            # A controller fault cannot leave an acquisition renewing indefinitely.
            try:
                self.stop_transmit()
            finally:
                print(f'Bench controller stopped: {exc}', flush=True)
                self.closed = True
                self.publish_status()
                self.app.exit(1)

    def close(self):
        self.timer.stop()
        try:
            self.stop_transmit()
        finally:
            self.closed = True
            self.publish_status()
            self.renderer.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sim', action='store_true')
    p.add_argument('--bench-ready', action='store_true', help='Fixed wire in water; hardware ready for unattended acquisition')
    p.add_argument('--control-dir', type=Path, default=ROOT / 'bench_runs/control')
    args = p.parse_args()
    if not args.sim and not args.bench_ready:
        p.error('Use --sim for rehearsal, or --bench-ready after the fixed water/wire setup is ready')
    programmed = None if args.sim else receipt(ROOT / 'bench_runs/program-receipt.json')
    if server_info(args.control_dir).get('state') == 'running' and pid_alive(server_info(args.control_dir).get('pid')):
        raise RuntimeError('Bench host is already running')
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    sys.argv = [str(ROOT / 'host/tfm_gl_host.py')] + (['sim'] if args.sim else [])
    import tfm_gl_host as h
    if not args.sim and not h.HW:
        h.stats['alive'] = False
        raise RuntimeError('Hardware unavailable; automated acquisition will not substitute simulation')
    app = h.QApplication(sys.argv)
    # Qt's offscreen plugin does not enumerate Windows system fonts itself.
    from PySide6.QtGui import QFontDatabase, QFont
    for name in ('consola.ttf', 'arial.ttf'):
        font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / name
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont('Consolas', 10))
    window = h.Main()
    controller = Control(h, window, app, args.control_dir, programmed, args.bench_ready)
    print(f'BENCH_HOST_READY {args.control_dir}', flush=True)
    try:
        return app.exec()
    finally:
        controller.close()
        window.close()


if __name__ == '__main__':
    sys.exit(main())
