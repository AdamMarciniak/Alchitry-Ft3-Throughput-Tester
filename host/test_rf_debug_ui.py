"""Hardware-free tests of the real Qt host, parser, settings and replay path."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
import rf_debug as files


class HostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Explicit simulation BEFORE import: importing the live host normally
        # opens USB. No physical device is opened by this test suite.
        with patch.object(sys, 'argv', ['tfm_gl_host.py', 'sim']):
            import tfm_gl_host as host
        cls.h = host
        host.stats['alive'] = False
        host.hil_ev.set()
        host.reader_thread.join(3)
        host.hilbert_thread.join(3)
        cls.app = host.QApplication.instance() or host.QApplication([])

    def setUp(self):
        self.h.debug_replay_only = False
        self.h.state['frozen'] = False
        self.h.cine.resume()
        self.h.recorded_tx_reference = None
        self.w = self.h.Main()
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.rf.npz'
        self.base = self.h.settings_snapshot(self.w)
        self.base['acquisition'].update(win_words=320, depth_cm=2)
        self.base['transmit'].update(single_elem=None, n_elem=48)
        self.w.debug_apply(self.base)
        self.w.debug_tick()

    def tearDown(self):
        self.w.close()
        self.temp.cleanup()

    def make_session(self):
        frames = np.random.default_rng(11).integers(-100, 100, (3, 48, 640), dtype=np.int16)
        meta = {'acquired_settings': self.h.settings_snapshot(self.w),
                'context': {'note': 'offline test'}, 'initial_review_index': 1}
        meta['acquired_settings']['transmit']['armed'] = True
        q = [{'valid': True, 'valid_elements': list(range(48))} for _ in frames]
        files.save_session(self.path, frames, [0, .1, .2], meta, q, [0, .25, -.5, 1])
        return frames

    def test_settings_restore_exact_geometry_and_fractional_delay_without_arming(self):
        s = copy.deepcopy(self.base)
        s['beamformer'].update(R_mm=67.52, pitch_mm=.3375, dead=[2, 6])
        s['acquisition']['dly_us'] = 5.25
        s['transmit']['armed'] = True
        self.w.debug_apply(s)
        self.assertFalse(self.h.pulser.arm)
        self.assertEqual(self.h.geom['R_mm'], 67.52)
        self.assertEqual(self.h.geom['pitch_mm'], .3375)
        self.assertEqual(self.h.state['dly_us'], 5.25)
        self.assertEqual(self.h.us_to_cycles(5.25), 525)
        commands = [int(e['word_hex'], 16) for e in self.w.debug_events]
        self.assertNotIn(self.h.cmd(0x10, 1), commands)
        self.assertFalse(self.w.cb_arm.isChecked())

    def test_invalid_settings_have_no_side_effect(self):
        before = self.h.settings_snapshot(self.w)
        count = len(self.w.debug_events)
        with self.assertRaises(ValueError):
            self.w.debug_apply({'transmit': {'t_dead_ns': 1}})
        self.assertEqual(self.h.settings_snapshot(self.w)['transmit'], before['transmit'])
        self.assertEqual(len(self.w.debug_events), count)

    def test_fast12_keeps_waveform_and_full_aperture_disarmed(self):
        self.h.state['frozen']=False
        self.base['acquisition'].update(win_words=4545,depth_cm=17,tgc_min=1000,tgc_max=3678,damp_gap_us=313)
        self.w.debug_apply(self.base)
        before=self.h.settings_snapshot(self.w)
        self.w.debug_fast12()
        after=self.h.settings_snapshot(self.w)
        self.assertEqual(after['acquisition']['win_words'],3208)
        self.assertEqual(after['acquisition']['damp_gap_us'],50)
        self.assertEqual(after['acquisition']['tgc_max'],2890)
        self.assertFalse(self.h.pulser.arm)
        self.assertEqual(after['transmit']['n_elem'],48)
        self.assertIsNone(after['transmit']['single_elem'])
        for key in ('chirp_on','chirp_us','chirp_f0_mhz','chirp_f1_mhz','t_dead_ns','t_settle_us','t_inhib_us','trim_ns'):
            self.assertEqual(after['transmit'][key],before['transmit'][key])

    def test_fast12_rejects_old_firmware_before_timing_changes(self):
        events=[]
        send=lambda word,name='':events.append(word)
        before=self.h.cfg['win_words']
        with patch.object(self.h,'HW',True), patch.object(self.h,'send_cmd',send), \
             patch.object(self.h.pulser,'_send',send), \
             patch('bench_transport.query_firmware',return_value={'capture_ready_interlock':False}), \
             patch('rf_debug_ui.QMessageBox.warning') as warning:
            self.w.debug_fast12()
        warning.assert_called_once()
        self.assertEqual(self.h.cfg['win_words'],before)
        self.assertFalse(self.h.pulser.arm)
        self.assertNotIn(self.h.cmd(16,1),events)
        self.assertTrue(all((v>>24) in (16,30) for v in events))

    def test_file_replay_uses_saved_reference_and_never_changes_acquisition(self):
        frames = self.make_session()
        before = len(self.w.debug_events)
        with patch('rf_debug_ui.QMessageBox.warning', side_effect=AssertionError('load failed')):
            self.w.debug_open_rf(self.path)
        self.assertTrue(self.w.debug_offline)
        self.assertFalse(self.h.pulser.arm)
        self.assertEqual(self.w.cur_idx, 1)
        self.assertFalse(self.w.cb_arm.isEnabled())
        self.assertFalse(self.w.depth_s.isEnabled())
        np.testing.assert_array_equal(self.h.mf_reference(), [0, .25, -.5, 1])
        self.assertEqual(self.h._tx_spec_now()['gen'], self.h._mf_ref['gen'])
        np.testing.assert_array_equal(self.w.review[2][1], frames[2])
        self.h.pulser.set_arm(True)  # even a direct setter cannot send an ARM in replay
        self.h.pulser.arm = False
        new = self.w.debug_events[before:]
        self.assertTrue(all(int(e['word_hex'], 16) == self.h.cmd(0x10, 0) for e in new))
        self.w.debug_new_live()
        self.assertFalse(self.w.debug_offline)
        self.assertFalse(self.h.state['frozen'])
        self.assertIsNone(self.w.debug_session)
        self.assertIsNone(self.h.recorded_tx_reference)
        self.assertFalse(self.h.pulser.arm)

    def test_render_changes_keep_rf_but_acquisition_changes_begin_new_epoch(self):
        self.h.cine.push(np.zeros((48, 640), np.int16))
        self.h.state['cf'] = .25
        self.w.debug_tick()
        self.assertEqual(self.h.cine.status()[0], 1)
        old = self.w.debug_run_id
        self.w.set_tgc_lo(1000)
        self.assertEqual(self.h.debug_discard_words, -1)
        self.w.debug_tick()
        self.assertEqual(self.w.debug_run_id, old + 1)
        self.assertEqual(self.h.cine.status()[0], 0)

    def test_diagnostic_views_use_full_band_and_frozen_settings_keep_acquisition(self):
        h = self.h
        h.state.update(freq_comp=True, mf=False)
        self.w.debug_set_mode(1)
        out = h.prepare_analytic(np.zeros((48, 640), np.int16), 640)
        self.assertEqual(out.shape, (48, 640, 2))
        self.w.debug_set_mode(0)
        out = h.prepare_analytic(np.zeros((48, 640), np.int16), 640)
        self.assertEqual(out.shape, (3, 48, 640, 2))
        h.cine.push(np.zeros((48, 640), np.int16))
        self.w.b_freeze.setChecked(True)
        expected = copy.deepcopy(self.w.debug_epoch['transmit'])
        h.pulser.arm = False
        self.assertEqual(h.settings_snapshot(self.w)['transmit'], expected)

    def rows(self, elems, first=0, holes=False):
        h = self.h
        rows = np.zeros((len(elems), 321), np.uint32)
        raw = ((np.arange(640, dtype=np.uint16) % 16) << 12) | 2148
        if holes:
            raw[-1] ^= 0x1000
        rows[:, 1:] = raw.view(np.uint32)
        rows[:, 0] = [0xE1000000 | (e << 16) | ((first+i) & 0xffff)
                       for i, e in enumerate(elems)]
        return rows

    def test_parser_exact_decode_chunking_and_counter_rollover(self):
        count=self.h.stats['complete_sweeps']
        stream = self.rows(list(range(48)) + [0], first=65520).ravel()
        self.h.process(stream[:913])
        self.h.process(stream[913:])
        self.assertEqual(self.h.cine.status()[0], 1)
        np.testing.assert_array_equal(self.h.cine.buf[0][1], np.full((48, 640), 100))
        self.assertTrue(self.h.cine.quality[0]['valid'])
        self.assertEqual(self.h.stats['complete_sweeps'],count+1)

    def test_single_element_repeated_shots_form_separate_valid_frames(self):
        self.h.pulser.single_elem = 7
        self.h.process(self.rows([7, 7, 7]).ravel())
        self.assertEqual(self.h.cine.status()[0], 2)
        self.assertEqual(self.h.cine.quality[0]['valid_elements'], [7])
        self.assertEqual(np.flatnonzero(self.h.alive_mask()).tolist(), [7])

    def test_missing_element_fail_open_is_flagged_and_zero_filled(self):
        count=self.h.stats['complete_sweeps']
        elems = [e for e in range(48) if e != 3]
        elems = elems * (self.h.REJECT_MAX + 1) + [0]
        self.h.process(self.rows(elems).ravel())
        self.assertGreater(self.h.cine.status()[0], 0)
        self.assertFalse(self.h.cine.quality[0]['valid'])
        self.assertIn(3, self.h.cine.quality[0]['missing_elements'])
        self.assertTrue(np.all(self.h.cine.buf[0][1][3] == 0))
        self.assertEqual(self.h.stats['complete_sweeps'],count)

    def test_sample_counter_holes_are_flagged_in_saved_quality(self):
        elems = list(range(48)) * (self.h.REJECT_MAX + 1) + [0]
        self.h.process(self.rows(elems, holes=True).ravel())
        self.assertGreater(self.h.cine.status()[0], 0)
        self.assertFalse(self.h.cine.quality[0]['valid'])
        self.assertEqual(self.h.cine.quality[0]['valid_elements'], [])

    def test_save_button_includes_average_history_and_freezes_until_finished(self):
        for value in (10, 20, 30):
            self.h.cine.push(np.full((48, 640), value, np.int16))
        self.h.rf_avg.set_n(3)
        with patch('rf_debug_ui.QFileDialog.getSaveFileName', return_value=(str(self.path), '')), \
             patch.object(self.h.QInputDialog, 'getItem', return_value=('Current frame', True)):
            self.w.debug_save_rf()
        for job in self.w.debug_jobs:
            job.join(5)
        self.w.debug_tick()
        self.assertTrue(self.h.state['frozen'])
        self.assertFalse(self.h.pulser.arm)
        s = files.load_session(self.path)
        try:
            self.assertEqual(len(s.rf), 3)
            self.assertEqual(s.metadata['initial_review_index'], 2)
            self.assertEqual(s.metadata['selected_original_frame_indices'], [2])
            self.assertEqual(s.metadata['review_settings']['receive']['avg_sweeps'], 3)
            self.assertTrue(self.path.with_suffix('.report.json').exists())
        finally:
            s.close()

    def test_gpu_das_weighted_and_coherence_map_values(self):
        import moderngl
        try:
            ctx = moderngl.create_standalone_context(require=330)
        except Exception as exc:
            self.skipTest(f'OpenGL 3.3 unavailable: {exc}')
        try:
            p = ctx.program(vertex_shader=self.h.VERT, fragment_shader=self.h.BEAMFORM)
            vbo = ctx.buffer(np.array([-1,-1, 1,-1, -1,1, 1,1], np.float32).tobytes())
            vao = ctx.simple_vertex_array(p, vbo, 'in_pos')
            a = np.zeros((48, 640, 2), np.float32)
            a[:36, :, 0], a[36:, :, 0] = 1, -1
            tex = ctx.texture((640, 48), 2, a.tobytes(), dtype='f4')
            tex.use(0)
            geom = np.zeros((48, 4), np.float32)
            geom[:, 3] = 1
            p['elems'].write(geom.tobytes())
            p['alive'].write(np.ones(48, np.float32).tobytes())
            for k, v in {'rf0': 0, 'rf1': 0, 'rf2': 0, 'viewbox': (0,0,.01,.01),
                         'c': 1540, 'dly_s': 0, 'fs': 40e6, 'samps': 640,
                         'cos_acc': .5, 'apod': 0, 'cf_pow': 1,
                         't0_s': 0, 'freq_comp': 0}.items():
                p[k].value = v
            mag = ctx.texture((1, 1), 1, dtype='f4')
            fbo = ctx.framebuffer([mag])
            fbo.use()
            for mode, expected in ((0, 6), (1, 24), (2, .25)):
                p['debug_view'].value = mode
                vao.render(moderngl.TRIANGLE_STRIP)
                got = np.frombuffer(fbo.read(components=1, dtype='f4'), np.float32)[0]
                self.assertAlmostEqual(got, expected, places=5)
            cp = ctx.program(vertex_shader=self.h.VERT, fragment_shader=self.h.COMPRESS)
            cv = ctx.simple_vertex_array(cp, vbo, 'in_pos')
            for k, v in {'magtex': 0, 'maxtex': 0, 'full_scale': 200000,
                         'dyn_db': 80, 'gain_db': 40, 'auto_gain': 1,
                         'curve': .3, 'debug_view': 2}.items():
                cp[k].value = v
            color = ctx.texture((1, 1), 4, dtype='f4')
            target = ctx.framebuffer([color])
            target.use()
            mag.use(0)
            cv.render(moderngl.TRIANGLE_STRIP)
            rgba = np.frombuffer(target.read(components=4, dtype='f4'), np.float32)
            np.testing.assert_allclose(rgba, [.25, .25, .25, 1], atol=1e-6)
        finally:
            ctx.release()


if __name__ == '__main__':
    unittest.main()
