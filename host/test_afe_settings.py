import unittest

from afe_settings import metadata, register_writes
from acquisition_timing import tgc_increment


class AfeSettingsTests(unittest.TestCase):
    def test_recommended_profile_exact_registers(self):
        self.assertEqual(register_writes(), [
            (0x16, 0x00DB), (0x0F, 0x00F7), (0x14, 0x0000), (0x2A, 0x0006)])
        self.assertEqual(metadata()["requested_registers"]["0x2A"], "0x0006")

    def test_tgc_knee_changes_slope(self):
        full = tgc_increment(1400, 4095, 4545, 100)
        early = tgc_increment(1400, 4095, 4545, 56)
        self.assertGreater(early, full)
        self.assertEqual(early, 2695 * 4096 // round(4545 * .56))


if __name__ == "__main__":
    unittest.main()
