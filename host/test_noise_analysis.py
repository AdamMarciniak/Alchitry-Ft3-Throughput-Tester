import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from noise_analysis import (
    CaptureData,
    CaptureSettings,
    FrameParser,
    FS_HZ,
    analyze_capture,
    depth_to_words,
    export_bundle,
    load_capture_npz,
    simulate_capture,
)


def encoded_frame(element, counter, codes, start_tag=0):
    codes = np.asarray(codes, dtype=np.uint16)
    if codes.size % 2:
        raise ValueError("test frame needs an even sample count")
    tags = (start_tag + np.arange(codes.size)) & 0xF
    raw16 = ((tags.astype(np.uint16) << 12) | (codes & 0xFFF)).astype(np.uint16)
    pairs = raw16.reshape(-1, 2)
    words = pairs[:, 0].astype(np.uint32) | (pairs[:, 1].astype(np.uint32) << 16)
    header = np.uint32((0xE1 << 24) | ((element & 0x3F) << 16) | (counter & 0xFFFF))
    return np.concatenate((np.array([header], dtype=np.uint32), words))


class FrameParserTests(unittest.TestCase):
    def test_fragmented_stream_decodes_only_clean_requested_element(self):
        words = 8
        parser = FrameParser(words, expected_element=7, signed_adc=False)
        codes = 2048 + np.arange(2 * words, dtype=np.uint16)
        good0 = encoded_frame(7, 10, codes, 2)
        wrong = encoded_frame(8, 11, codes, 3)
        damaged = encoded_frame(7, 12, codes, 4)
        # Force a tag repetition inside the packed payload.
        half = damaged.view(np.uint16)
        half[5] = (half[5] & 0x0FFF) | (half[4] & 0xF000)
        good1 = encoded_frame(7, 13, codes + 1, 5)
        stream = np.concatenate((np.array([0xDEADBEEF], np.uint32), good0, wrong, damaged, good1))

        out = []
        for a, b in ((0, 5), (5, 23), (23, stream.size)):
            out.extend(parser.feed(stream[a:b]))
        self.assertEqual(len(out), 2)
        np.testing.assert_array_equal(out[0], np.arange(2 * words))
        np.testing.assert_array_equal(out[1], np.arange(2 * words) + 1)
        self.assertEqual(parser.stats["wrong_element_frames"], 1)
        self.assertEqual(parser.stats["tag_damaged_frames"], 1)
        self.assertGreaterEqual(parser.stats["resync_events"], 1)

    def test_signed_coding(self):
        parser = FrameParser(4, expected_element=0, signed_adc=True)
        codes = np.array([0, 1, 2047, 2048, 2049, 4094, 4095, 2], np.uint16)
        out = parser.feed(encoded_frame(0, 0, codes))
        np.testing.assert_array_equal(out[0], [0, 1, 2047, -2048, -2047, -2, -1, 2])


class NoiseAnalysisTests(unittest.TestCase):
    def make_tonal_capture(self):
        rng = np.random.default_rng(99)
        frames, samples = 48, 4096
        t = np.arange(samples) / FS_HZ
        rows = []
        for i in range(frames):
            # Random phase keeps the 3 MHz line in the random residual rather
            # than the repeatable mean waveform.
            phase = rng.uniform(0, 2 * np.pi)
            row = rng.normal(0, 2.0, samples)
            row += 18.0 * np.sin(2 * np.pi * 3e6 * t + phase)
            row[2300:2600] += rng.normal(0, 18.0, 300)
            rows.append(row)
        data = CaptureData(
            frames=np.rint(rows).astype(np.int16),
            settings={
                "element": 4,
                "sample_rate_hz": FS_HZ,
                "sound_speed_m_s": 1500.0,
                "delay_us": 5.0,
                "tgc_start": 900,
                "tgc_end": 900,
                "sample_coding": "offset_binary",
                "estimated_frame_rate_hz": 3000.0,
            },
            transport={"accepted_frames": frames},
        )
        return data

    def test_detects_tone_and_localized_noise(self):
        result = analyze_capture(self.make_tonal_capture())
        tones = result.report["spectrum"]["random_noise_tones"]
        self.assertTrue(any(abs(t["frequency_hz"] - 3e6) < 2 * result.report["spectrum"]["frequency_resolution_hz"] for t in tones))
        regions = result.report["time_depth_localization"]["localized_regions"]
        self.assertTrue(any(r["start_us"] < 65 and r["end_us"] > 55 for r in regions))

    def test_fault_rich_simulation_is_repeatable(self):
        settings = CaptureSettings(frames=24, depth_cm=3)
        a = simulate_capture(settings)
        b = simulate_capture(settings)
        np.testing.assert_array_equal(a.frames, b.frames)
        result = analyze_capture(a)
        self.assertGreater(result.report["summary"]["coherent_rms_counts"], result.report["summary"]["random_rms_counts"])

    def test_bundle_round_trip(self):
        data = simulate_capture(CaptureSettings(frames=16, depth_cm=2))
        result = analyze_capture(data)
        with tempfile.TemporaryDirectory() as td:
            paths = export_bundle(data, result, Path(td))
            self.assertEqual(set(paths), {"capture", "analysis", "report", "waveform", "overview", "llm_prompt"})
            self.assertTrue(all(path.exists() for path in paths.values()))
            loaded = load_capture_npz(paths["capture"])
            np.testing.assert_array_equal(loaded.frames, data.frames)
            report = json.loads(paths["analysis"].read_text(encoding="utf-8"))
            self.assertEqual(report["schema"], "usb3_tester.single_element_noise.v2")
            self.assertIn("Separate these failure classes", paths["llm_prompt"].read_text(encoding="utf-8"))

    def test_expected_near_field_is_excluded_from_assessment(self):
        rng = np.random.default_rng(7)
        frames = rng.normal(0, 0.8, (32, 4096))
        frames[:, :500] += 1500.0  # expected limiter interval before the gate
        data = CaptureData(
            frames=np.clip(np.rint(frames), -2048, 2047).astype(np.int16),
            settings={
                "element": 0,
                "sample_rate_hz": FS_HZ,
                "sound_speed_m_s": 1500.0,
                "delay_us": 0.0,
                "analysis_start_depth_cm": 3.0,
                "transmit_trim_bias_ns": 0.0,
                "selected_transmit_trim_ns": 0.0,
                "tgc_start": 800,
                "tgc_end": 800,
                "sample_coding": "offset_binary",
            },
            transport={"accepted_frames": 32},
        )
        result = analyze_capture(data)
        self.assertEqual(result.report["overall_status"], "baseline_or_clean")
        self.assertTrue(result.report["excluded_near_field"]["available"])
        self.assertGreater(result.report["excluded_near_field"]["peak_counts"], 1000)
        self.assertLess(result.report["summary"]["random_rms_counts"], 1.0)

    def test_depth_window_bounds(self):
        self.assertEqual(depth_to_words(0.001, 1500), 320)
        self.assertEqual(depth_to_words(10000, 1500), 0xFFFF)


if __name__ == "__main__":
    unittest.main()
