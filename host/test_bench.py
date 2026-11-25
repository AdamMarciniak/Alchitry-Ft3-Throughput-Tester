"""Bench checks: FPGA handshake, honest image scoring, and real host IPC in SIM.

No test opens physical USB or invokes the FPGA uploader.
"""
import copy
import json
import math
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
import uuid

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import bench
import bench_build
from bench_client import request, pid_alive
from bench_render import wire_metrics
from bench_transport import InfoProbe, MAGIC, check_configuration, query_firmware
from rf_debug import atomic_json, load_session


class HandshakeTests(unittest.TestCase):
    def packet(self, nonce=123, build=0x12345678):
        return np.array([MAGIC, nonce, build, 0x10002, 1900,
                         2047, 500, 5000, (4095 << 12), 8194, (2 << 16) | 10,
                         4, 500, 450, 300, 13000], np.uint32)

    def test_fragmented_packet_and_stale_identity(self):
        p = InfoProbe(123, 0x12345678)
        p.feed(self.packet(nonce=122))
        p.feed(self.packet(build=0x98765432))
        self.assertFalse(p.event.is_set())
        good = self.packet()
        p.feed(good[:7])
        self.assertFalse(p.event.is_set())
        p.feed(good[7:])
        info = p.result()
        self.assertEqual(info['runtime_build_id'], '12345678')
        self.assertEqual(info['n_cycles'], 2)
        self.assertEqual(info['drive_cycles'], 10)
        self.assertFalse(info['pulser_fault'])
        self.assertEqual(info['pulser_frames'], 0)
        self.assertFalse(info['armed'])
        self.assertTrue(info['lease_enabled'])

    def test_failed_query_restores_source_without_arming(self):
        events = []
        h = SimpleNamespace(debug_replay_only=False, debug_probe_consumer=None,
                            stats={'alive': True}, OP_STOP=2, OP_RST_CNT=3,
                            OP_SET_SRC=7, OP_START=1, SRC_SEQ=2)
        h.cmd = lambda op, payload=0: (op << 24) | payload
        h.send_cmd = lambda word, name: events.append(word)
        h.pulser = SimpleNamespace(set_arm=lambda on: events.append(h.cmd(16, int(on))))
        with self.assertRaises(TimeoutError):
            query_firmware(h, '12345678', timeout=.02)
        self.assertNotIn(h.cmd(16, 1), events)
        self.assertEqual(events[-3:], [h.cmd(2), h.cmd(7, 2), h.cmd(1)])
        self.assertIsNone(h.debug_probe_consumer)
        self.assertFalse(h.debug_replay_only)

    def test_configuration_readback_blocks_mismatch(self):
        h = SimpleNamespace(cfg={'win_words': 2047}, state={'dly_us': 5},
                            us_to_cycles=lambda v: round(v*100),
                            pls_us_to_cyc=lambda v: max(1, round(v*100)),
                            pls_ns_to_cyc=lambda v: max(1, round(v/10)))
        h.pulser = SimpleNamespace(n_cycles=2, t_drive_ns=100, t_dead_ns=40,
                                  t_settle_us=5, t_inhib_us=4.5, t_ring_us=3, t_rx_us=130)
        w = SimpleNamespace(tgc_lo=0, tgc_hi=4095, tgc_reach_pct=100, gap=50)
        p = InfoProbe(123, 0x12345678)
        p.feed(self.packet())
        info = p.result()
        check_configuration(h, w, info)
        info['dly_cycles'] += 1
        with self.assertRaisesRegex(RuntimeError, 'dly_cycles'):
            check_configuration(h, w, info)

    def test_capability_query_requires_nonce_and_distinguishes_old_firmware(self):
        p=InfoProbe(123,None)
        p.feed(self.packet(nonce=122))
        self.assertFalse(p.event.is_set())
        p.feed(self.packet())
        self.assertFalse(p.result()['capture_ready_interlock'])
        new=self.packet(build=0x87654321);new[3]|=4
        p.feed(new)
        self.assertTrue(p.result()['capture_ready_interlock'])
        self.assertEqual(p.result()['runtime_build_id'],'87654321')


class MetricTests(unittest.TestCase):
    def test_gaussian_width_and_fixed_target(self):
        x = np.linspace(-30, 30, 601)
        z = np.linspace(30, 90, 601)
        xx, zz = np.meshgrid(x, z)
        mag = np.exp(-.5*((xx/1.2)**2 + ((zz-60)/.6)**2))
        mag += 2*np.exp(-.5*(((xx-12)/1.2)**2 + ((zz-60)/.6)**2))
        # Pixel-centre coordinates match the axes used to make the phantom.
        result = wire_metrics(mag, [-30.05,30.05,29.95,90.05], [-20,20,40,80], [0,60])
        np.testing.assert_allclose(result['peak_position_mm'], [0,60], atol=.001)
        self.assertAlmostEqual(result['lateral_width_6db_mm'], 2.35482*1.2, delta=.015)
        self.assertAlmostEqual(result['axial_width_6db_mm'], 2.35482*.6, delta=.015)

    def test_missing_clutter_region_is_not_zero_clutter(self):
        with self.assertRaisesRegex(ValueError, 'side-clutter'):
            wire_metrics(np.ones((40,40)), [-1,1,59,61], [-1,1,59,61], [0,60])

    def test_score_rejects_display_cheats_and_clutter_tradeoff(self):
        base = dict(view='ordinary_DAS', quality={'valid': True}, peak=100,
                    normalized_peak=.1, lateral_width_6db_mm=2, axial_width_6db_mm=1,
                    clutter_p95_relative_db=-30, clutter_to_target_energy=.01)
        self.assertAlmostEqual(bench.score(base, base), 0)
        for patch in ({'view': 'coherence_map'}, {'view': 'weighted'},
                      {'normalized_peak': .04}, {'clutter_p95_relative_db': -26},
                      {'clutter_to_target_energy': .016}, {'peak': math.nan},
                      {'lateral_width_6db_mm': None}, {'quality': {'valid': False}}):
            with self.subTest(patch=patch):
                self.assertIsNone(bench.score(dict(base, **patch), base))
        self.assertLess(bench.score(dict(base, lateral_width_6db_mm=1.8), base), -.03)


class BuildManifestTests(unittest.TestCase):
    def test_actual_uploader_listing_and_ambiguous_counts(self):
        self.assertEqual(bench_build.board_index('WARNING: Java native access\nDetected 1 Alchitry Au V2\n'), '0')
        self.assertEqual(bench_build.board_index('0: Alchitry Au V2\n'), '0')
        for text in ('No devices detected.', 'Detected 2 Alchitry Au V2',
                     'Detected 1 Alchitry Au', '0: Au V2\n1: Au V2'):
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                bench_build.board_index(text)

    def test_modified_or_unchecked_build_cannot_program(self):
        with tempfile.TemporaryDirectory() as name:
            out = Path(name)
            binary, rtl = out/'alchitry_top.bin', out/'source.v'
            binary.write_bytes(b'test bitstream')
            rtl.write_text('test source')
            manifest = dict(schema='usb3-bench-build', state='passed', part=bench_build.PART,
                            board='AuV2', lease_simulation='passed', capture_ready_simulation='passed', capabilities=bench_build.CAPABILITIES,
                            checks=dict(setup_slack_ns=.1, hold_slack_ns=.02, drc_failures=0),
                            bitstream_sha256=bench_build.sha(binary), source_sha256={'source.v': bench_build.sha(rtl)})
            atomic_json(out/'manifest.json', manifest)
            bench_build.validated_build(out)
            for patch in ({'state': 'failed'}, {'capabilities': []},
                          {'checks': dict(setup_slack_ns=-.01, hold_slack_ns=.02, drc_failures=0)}):
                atomic_json(out/'manifest.json', dict(manifest, **patch))
                with self.assertRaises(ValueError):
                    bench_build.validated_build(out)
            atomic_json(out/'manifest.json', manifest)
            binary.write_bytes(b'changed bitstream')
            with self.assertRaisesRegex(ValueError, 'Bitstream hash'):
                bench_build.validated_build(out)
            binary.write_bytes(b'test bitstream')
            rtl.write_text('changed source')
            with self.assertRaisesRegex(ValueError, 'Frozen build input'):
                bench_build.validated_build(out)


class HostProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Keep logs/recordings for inspection; no recursive removal is needed.
        cls.out = ROOT/'bench_runs/tests'/uuid.uuid4().hex
        cls.control = cls.out/'control'
        process = subprocess.run([sys.executable, str(ROOT/'tools/bench.py'),
                                  '--control-dir', str(cls.control), 'start', '--sim'],
                                 cwd=ROOT, capture_output=True, text=True, timeout=40,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if process.returncode:
            raise RuntimeError(process.stderr + process.stdout)
        cls.info = json.loads(process.stdout)

    @classmethod
    def tearDownClass(cls):
        request(cls.control, {'op': 'shutdown'})
        deadline = time.monotonic()+15
        while pid_alive(cls.info['pid']) and time.monotonic() < deadline:
            time.sleep(.05)
        if pid_alive(cls.info['pid']):
            raise AssertionError('Simulation host did not exit')

    def test_capture_replay_configuration_and_idle(self):
        status = request(self.control, {'op': 'status'})
        self.assertEqual(status['source'], 'simulation')
        self.assertFalse(status['settings']['transmit']['armed'])
        before = copy.deepcopy(status['settings']['transmit'])
        with self.assertRaisesRegex(RuntimeError, 'waveform unchanged'):
            request(self.control, {'op': 'configure', 'settings': {'transmit': {'n_cycles': before['n_cycles']+1}}})
        unchanged = request(self.control, {'op': 'status'})
        self.assertEqual(unchanged['settings']['transmit'], before)
        settings_path = self.out/'known-settings.json'
        atomic_json(settings_path, {'beamformer': {'cf': .5, 't0_ns': 125}})
        result = subprocess.run([sys.executable, str(ROOT/'tools/bench.py'), '--control-dir',
                                 str(self.control), 'configure', str(settings_path)],
                                capture_output=True, text=True, timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.assertEqual(result.returncode, 0, result.stderr)
        configured = json.loads(result.stdout)
        self.assertEqual(configured['beamformer']['t0_ns'], 125)
        self.assertFalse(configured['transmit']['armed'])
        idle = request(self.control, {'op': 'status'})['frames']
        time.sleep(.3)
        self.assertEqual(request(self.control, {'op': 'status'})['frames'], idle)
        with self.assertRaisesRegex(RuntimeError, 'inside this project'):
            request(self.control, {'op': 'capture', 'frames': 4, 'output': str(ROOT/'invalid-bench-output')})
        self.assertFalse((ROOT/'invalid-bench-output').exists())
        result = request(self.control, {'op': 'capture', 'frames': 4, 'timeout_s': 8,
                          'output': str(self.out/'capture'), 'note': 'SIM integration test'}, timeout=15)
        self.assertTrue(result['accepted'])
        self.assertEqual(result['frames'], 4)
        session = load_session(result['session'])
        try:
            self.assertEqual(session.rf.shape[:2], (4,48))
            self.assertEqual(session.rf.dtype, np.int16)
            self.assertEqual(session.metadata['acquired_settings']['source'], 'simulation')
            self.assertIsNone(session.metadata['firmware_readback_before_arm'])
            self.assertTrue(all(q['valid'] for q in session.quality))
        finally:
            session.close()
        rendered = request(self.control, {'op': 'render', 'session': result['session'],
                          'settings': {'display': {'debug_view': 1}, 'beamformer': {'t0_ns': 0}},
                          'output': str(self.out/'render')})
        self.assertEqual(rendered['metrics']['view'], 'ordinary_DAS')
        self.assertTrue(Path(rendered['image']).is_file())
        mag = np.load(self.out/'render/magnitude.npy', allow_pickle=False)
        self.assertEqual(mag.shape, (640,512))
        self.assertTrue(np.isfinite(mag).all())
        self.assertGreater(float(mag.max()), 0)
        self.assertFalse(request(self.control, {'op': 'status'})['pulser_requested_armed_now'])

    def test_stale_control_request_rejected(self):
        key = uuid.uuid4().hex
        atomic_json(self.control/(key+'.request.json'),
                    dict(id=key, server_id=self.info['server_id'], op='status',
                         created_unix=time.time()-10, ttl_s=1))
        response = self.control/(key+'.response.json')
        deadline = time.monotonic()+5
        while not response.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        value = json.loads(response.read_text())
        self.assertFalse(value['ok'])
        self.assertIn('expired', value['error'])


if __name__ == '__main__':
    unittest.main()
