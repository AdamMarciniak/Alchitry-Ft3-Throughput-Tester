"""Portable format, settings, and measurement regression tests; no hardware."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import rf_debug as rf


class AtomicJsonTests(unittest.TestCase):
    def test_transient_windows_reader_lock_preserves_complete_json_then_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'status.json'
            rf.atomic_json(path, {'state': 'old'})
            replace = rf.os.replace
            locked = PermissionError('reader temporarily holds destination')
            locked.winerror = 5
            calls = []

            def contend(source, destination):
                self.assertEqual(json.loads(path.read_text()), {'state': 'old'})
                calls.append(1)
                if len(calls) < 3:
                    raise locked
                replace(source, destination)

            with patch.object(rf.os, 'replace', side_effect=contend), patch.object(rf.time, 'sleep'):
                rf.atomic_json(path, {'state': 'new'})
            self.assertEqual(json.loads(path.read_text()), {'state': 'new'})
            self.assertFalse(list(Path(directory).glob('*.tmp')))

    def test_persistent_lock_is_bounded_and_leaves_previous_file_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'status.json'
            rf.atomic_json(path, {'state': 'old'})
            locked = PermissionError('persistent lock')
            locked.winerror = 32
            with patch.object(rf.os, 'replace', side_effect=locked) as replace, patch.object(rf.time, 'sleep') as sleep:
                with self.assertRaises(PermissionError):
                    rf.atomic_json(path, {'state': 'new'})
            self.assertEqual(replace.call_count, 5)
            self.assertLessEqual(sum(c.args[0] for c in sleep.call_args_list), .151)
            self.assertEqual(json.loads(path.read_text()), {'state': 'old'})
            self.assertFalse(list(Path(directory).glob('*.tmp')))


def fixture():
    a = np.random.default_rng(17).integers(-2048, 2048, (3, 48, 640), dtype=np.int16)
    meta = {"acquired_settings": {"acquisition": {"win_words": 320, "fs_hz": 40000000},
                                  "transmit": {"trim_ns": [0]*48},
                                  "display": {"signed": False}},
            "context": {"note": "3 mm wire; water; test only"}}
    q = [{"valid": True, "valid_elements": list(range(48))} for _ in a]
    return a, meta, q


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.rf.npz"
        self.a, self.meta, self.q = fixture()

    def tearDown(self):
        self.temp.cleanup()

    def save(self, **kwargs):
        rf.save_session(self.path, self.a, [0, .1, .2], self.meta, self.q,
                        np.array([0, 1, -1], np.float32), **kwargs)

    def test_roundtrip_exact_rf_metadata_reference_background(self):
        bg = self.a[0].astype(np.float32) / 3
        self.q[1] = {"valid": False, "valid_elements": [0, 4], "missing_elements": [2]}
        self.save(background=bg)
        s = rf.load_session(self.path)
        directory = Path(s.directory.name)
        try:
            self.assertIsInstance(s.rf, np.memmap)
            np.testing.assert_array_equal(s.rf, self.a)
            np.testing.assert_array_equal(s.tx_reference, [0, 1, -1])
            np.testing.assert_array_equal(s.background, bg)
            self.assertEqual(s.metadata["context"], self.meta["context"])
            self.assertEqual(s.quality, self.q)
        finally:
            s.close()
        self.assertFalse(directory.exists())

    def test_failed_save_preserves_previous_file(self):
        self.save()
        before = self.path.read_bytes()
        frames = list(self.a)
        frames[1] = frames[1].astype(np.float32)
        with self.assertRaises(ValueError):
            rf.save_session(self.path, frames, [0, .1, .2], self.meta, self.q, [1])
        self.assertEqual(before, self.path.read_bytes())
        self.assertFalse(list(self.path.parent.glob("*.tmp")))

    def test_uncompressed_rf_loads_without_copying_or_modifying_the_archive(self):
        self.save()
        before = self.path.read_bytes()
        with patch.object(rf.shutil, 'copyfileobj', side_effect=AssertionError('no disk copy allowed')):
            s = rf.load_session(self.path)
        try:
            np.testing.assert_array_equal(s.rf, self.a)
            self.assertFalse(s.rf.flags.writeable)
            self.assertEqual(Path(s.rf.filename).resolve(), self.path.resolve())
            self.assertFalse(list(Path(s.directory.name).iterdir()))
        finally:
            s.close()
        self.assertEqual(before, self.path.read_bytes())

    def test_compressed_archive_keeps_compatible_extraction_fallback(self):
        self.save()
        with zipfile.ZipFile(self.path) as z:
            entries = {name: z.read(name) for name in z.namelist()}
        with zipfile.ZipFile(self.path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            for name, value in entries.items():
                z.writestr(name, value)
        s = rf.load_session(self.path)
        try:
            np.testing.assert_array_equal(s.rf, self.a)
            self.assertNotEqual(Path(s.rf.filename).resolve(), self.path.resolve())
        finally:
            s.close()

    def test_stored_member_payload_size_must_match_header(self):
        self.save()
        self.rewrite(lambda entries: entries.update({'rf.npy': entries['rf.npy'][:-2]}))
        with self.assertRaisesRegex(ValueError, 'size'):
            rf.load_session(self.path)

    def test_direct_mapping_still_checks_zip_crc_for_the_entire_payload(self):
        self.save()
        s = rf.load_session(self.path)
        offset = s.rf.offset + s.rf.nbytes - 10
        s.close()
        with self.path.open('r+b') as stream:
            stream.seek(offset)
            value = stream.read(1)
            stream.seek(offset)
            stream.write(bytes([value[0] ^ 1]))
        with self.assertRaises(zipfile.BadZipFile):
            rf.load_session(self.path)

    def rewrite(self, mutate):
        with zipfile.ZipFile(self.path) as z:
            entries = {name: z.read(name) for name in z.namelist()}
        mutate(entries)
        with zipfile.ZipFile(self.path, 'w') as z:
            for name, data in entries.items():
                z.writestr(name, data)

    def test_checksum_corruption_rejected(self):
        self.save()
        def mutate(entries):
            meta = json.loads(entries['metadata.json'])
            meta['rf_sha256'] = '0'*64
            entries['metadata.json'] = json.dumps(meta)
        self.rewrite(mutate)
        with self.assertRaisesRegex(ValueError, "checksum"):
            rf.load_session(self.path)

    def test_invalid_element_indices_and_archive_paths_rejected(self):
        self.q[0]['valid_elements'] = [-1]
        with self.assertRaises(ValueError):
            self.save()
        self.q[0]['valid_elements'] = [0]
        self.save()
        self.rewrite(lambda entries: entries.update({'../outside': b'not allowed'}))
        with self.assertRaisesRegex(ValueError, "entries"):
            rf.load_session(self.path)

    def test_measurements_find_late_clipping_and_exclude_invalid_elements(self):
        self.a.fill(0)
        self.a[:, 1, :] = 50
        self.a[:, 2, :] = 2000  # must not affect measurements when invalid
        self.a[:, 3, -1] = 2047
        for q in self.q:
            q['valid_elements'] = [0, 1, 3]
            q['valid'] = False
        result = rf.diagnostics(self.a, self.q)
        self.assertEqual(result['elements'][1]['rms_counts'], 50)
        self.assertEqual(result['elements'][2]['frames_measured'], 0)
        self.assertEqual(result['elements'][3]['clipped_fraction'], 1/640)
        self.assertEqual(result['degraded_frames_total'], 3)
        self.assertEqual(result['elements'][1]['temporal_residual_rms_counts'], 0)


class SettingsTests(unittest.TestCase):
    def test_load_never_arms_or_evaluates_unknown_fields(self):
        value = rf.validate_settings({'transmit': {'armed': True}, 'execute': 'anything'})
        self.assertFalse(value['transmit']['armed'])
        self.assertNotIn('execute', value)

    def test_validation_does_not_modify_defaults(self):
        defaults = {'transmit': {'n_cycles': 2}}
        before = copy.deepcopy(defaults)
        with self.assertRaises(ValueError):
            rf.validate_settings({'transmit': {'n_cycles': 3, 't_dead_ns': 0}}, defaults)
        self.assertEqual(defaults, before)

    def test_rejects_nonfinite_invalid_types_and_lengths(self):
        for doc in ({'beamformer': {'c_m_s': float('nan')}},
                    {'display': {'auto_gain': 'false'}},
                    {'transmit': {'n_cycles': 2.5}},
                    {'transmit': {'trim_ns': [0]*47}},
                    {'acquisition': {'tgc_min': 100, 'tgc_max': 50}},
                    {'settings_schema': 2}):
            with self.subTest(doc=doc), self.assertRaises(ValueError):
                rf.validate_settings(doc)

    def test_epoch_ignores_render_settings_but_tracks_capture_and_trim(self):
        _, doc, _ = fixture()
        s = doc['acquired_settings']
        key = rf.acquisition_key(s)
        s['beamformer'] = {'cf': 3}
        self.assertEqual(key, rf.acquisition_key(s))
        s['transmit']['trim_ns'][0] = 10
        self.assertNotEqual(key, rf.acquisition_key(s))


if __name__ == '__main__':
    unittest.main()
