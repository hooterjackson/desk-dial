"""DD-DES-003: the LED ring's local brightness cursor reads both brightness frames.

The controller sends brightness in two frames: lights off 0..100 (position 0 = off), lights on
0..99 (positions 0..99 = 1..100 %). The twin (alive_lights._local, mirrored by the firmware's
cc_alive_local) must map the on frame to value = position + 1 and the off frame to value = position.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from control_center import alive_lights  # noqa: E402


def _bri(value=40):
    return {"activity": "idle", "ring": {"style": "bri", "value": value}}


class BriLocalCursor(unittest.TestCase):
    def check(self, pos, high, expected):
        out, applied, index = alive_lights._local(_bri(), pos, high)
        self.assertTrue(applied, (pos, high))
        self.assertIsNone(index)
        self.assertEqual(out["ring"]["value"], expected, (pos, high))

    def test_off_frame_unchanged(self):
        for pos, expected in ((0, 0), (1, 1), (50, 50), (100, 100), (120, 100)):
            self.check(pos, 100, expected)

    def test_on_frame_starts_at_one_percent(self):
        for pos, expected in ((0, 1), (49, 50), (99, 100), (120, 100), (-3, 1)):
            self.check(pos, 99, expected)

    def test_other_max_refused(self):
        for high in (98, 101, 2):
            frame = _bri()
            out, applied, index = alive_lights._local(frame, 5, high)
            self.assertFalse(applied)
            self.assertIs(out, frame)

    def test_frame_not_mutated(self):
        frame = _bri(40)
        alive_lights._local(frame, 10, 99)
        self.assertEqual(frame["ring"]["value"], 40)


if __name__ == "__main__":
    unittest.main()
