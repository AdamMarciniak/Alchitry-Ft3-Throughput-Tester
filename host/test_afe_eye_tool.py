import unittest

from afe_eye_tool import (
    TapScore,
    _word,
    eye_map,
    find_eye,
    ramp_error_count,
    score_data_blocks,
    score_fclk_blocks,
    score_sync_blocks,
)


class EyeAnalysisTests(unittest.TestCase):
    def test_fclk_accepts_strict_alternation(self):
        block = [_word(0x3F if i & 1 else 0x00, 0x15) for i in range(32)]
        score = score_fclk_blocks([block], tap=7)
        self.assertTrue(score.passed)
        self.assertEqual(score.observations, 32)

    def test_fclk_rejects_stuck_or_invalid_data(self):
        stuck = [_word(0x3F, 0x15) for _ in range(32)]
        invalid = [_word(0x1F if i == 9 else (0x3F if i & 1 else 0), 0x15)
                   for i in range(32)]
        self.assertFalse(score_fclk_blocks([stuck]).passed)
        self.assertFalse(score_fclk_blocks([invalid]).passed)

    def test_data_requires_exact_stable_deskew_code(self):
        good = [_word(0x3F if i & 1 else 0, 0x15) for i in range(32)]
        changed = good.copy()
        changed[10] = _word(0, 0x2A)
        stuck_wrong = [_word(0x3F if i & 1 else 0, 0x00) for i in range(32)]
        self.assertTrue(score_data_blocks([good]).passed)
        self.assertFalse(score_data_blocks([changed]).passed)
        self.assertFalse(score_data_blocks([stuck_wrong]).passed)

    def test_sync_accepts_constant_complement_relation(self):
        inverse = [_word(0x3F if i & 1 else 0x00,
                         0x00 if i & 1 else 0x3F) for i in range(32)]
        score = score_sync_blocks([inverse])
        self.assertTrue(score.passed)

    def test_sync_rejects_shifted_words(self):
        shifted = [_word(0x3F if i & 1 else 0x00,
                         0x1F if i & 1 else 0x20) for i in range(32)]
        self.assertFalse(score_sync_blocks([shifted]).passed)

    def test_eye_window_selection(self):
        passed = {4, 5, 6, 7, 8, 9, 10, 11}
        scores = [TapScore(tap, 32, 0 if tap in passed else 1, {})
                  for tap in range(32)]
        window = find_eye(scores, minimum=6, guard=2)
        self.assertIsNotNone(window)
        self.assertEqual((window.start, window.end, window.width), (4, 11, 8))
        self.assertIn(window.center, (7, 8))
        self.assertEqual(eye_map(scores), "....########....................")

    def test_eye_rejects_narrow_window(self):
        scores = [TapScore(tap, 32, 0 if 10 <= tap <= 13 else 1, {})
                  for tap in range(32)]
        self.assertIsNone(find_eye(scores, minimum=6, guard=2))

    def test_eye_marks_boundary_clipping(self):
        scores = [TapScore(tap, 32, 0 if tap <= 7 else 1, {})
                  for tap in range(32)]
        window = find_eye(scores, minimum=6, guard=2)
        self.assertIsNotNone(window)
        self.assertTrue(window.touches_edge)

    def test_ramp_validation(self):
        good = [((4090 + i) & 0x0FFF) for i in range(20)]
        bad = good.copy()
        bad[9] = bad[8]
        self.assertEqual(ramp_error_count(good), 0)
        self.assertGreater(ramp_error_count(bad), 0)


if __name__ == "__main__":
    unittest.main()
