"""DD-BUG-006: a key line's `ks` re-seed after a key-up lost to a full key queue.

(a) kd0 ks1, its ku lost, then kd1 ks2: the re-seed would clear bit 0 silently; the bridge now emits
    release(0) before button(1).
(b) kd0 ks1, its ku lost, then kd0 ks1 again: the kd used to be swallowed (bit still set); it is now
    release(0) then button(0).
In-memory serial only (test_cc_device_f1.BridgeHarness): no port, window or network.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cc_device_f1 import BridgeHarness  # noqa: E402


def kinds(events):
    return [(e["kind"], e.get("button")) for e in events if e["kind"] in ("button", "release")]


class KeyLineReseedTests(unittest.TestCase):
    def setUp(self):
        self.h = BridgeHarness(self)

    def test_key_line_ks_clearing_a_bit_emits_its_release(self):
        self.h.bridge._consume({"id": 1, "ks": 1, "kd": 0})
        self.assertEqual(kinds(self.h.events()), [("button", 0)])
        # ku 0 lost; the next key line names only button 1
        self.h.bridge._consume({"id": 1, "ks": 2, "kd": 1})
        self.assertEqual(kinds(self.h.events()), [("release", 0), ("button", 1)])
        self.assertEqual(self.h.bridge._pressed, 2)

    def test_repress_after_lost_ku_is_a_press(self):
        self.h.bridge._consume({"id": 1, "ks": 1, "kd": 0})
        self.h.events()
        self.assertEqual(self.h.bridge._pressed, 1)
        self.h.bridge._consume({"id": 1, "ks": 1, "kd": 0})
        self.assertEqual(kinds(self.h.events()), [("release", 0), ("button", 0)])
        self.assertEqual(self.h.bridge._pressed, 1)

    def test_ku_line_releases_once(self):
        self.h.bridge._consume({"id": 1, "ks": 3, "kd": 1})   # bit 0 re-seeded (its kd was dropped)
        self.h.events()
        self.h.bridge._consume({"id": 1, "ks": 0, "ku": 1})   # ku 1 and ks also clears 0
        self.assertEqual(sorted(kinds(self.h.events())), [("release", 0), ("release", 1)])
        self.assertEqual(self.h.bridge._pressed, 0)

    def test_hold_line_with_lost_ku_releases_the_stale_bit(self):
        self.h.bridge._consume({"id": 1, "ks": 1, "kd": 0})
        self.h.bridge._consume({"id": 1, "ks": 8, "kd": 3})
        self.assertEqual(kinds(self.h.events()), [("button", 0), ("release", 0), ("button", 3)])
        self.h.bridge._consume({"id": 1, "ks": 8, "kh": 3})
        self.assertEqual(kinds(self.h.events()), [])

    def test_kd_of_a_button_held_at_ready_is_still_not_a_second_press(self):
        h = self.h
        h.serial.ready_ks = 0b0001
        h.bridge._enter({"id": 2, "profile": "MIDI CLACK JONES", "min": 0, "max": 100, "position": 0,
                         "windowsButton": 3, "windowsHidEnabled": False, "buttonOrder": [0, 1, 2, 3],
                         "frame": h.bridge.latest_frame and {k: v for k, v in h.bridge.latest_frame.items()
                                                             if k != "id"}})
        h.events()
        h.bridge._consume({"id": 2, "ks": 1, "kd": 0})       # the racing kd of the press ready reported
        self.assertEqual(kinds(h.events()), [])
        h.bridge._consume({"id": 2, "ks": 1, "kd": 0})       # a later kd: its ku was lost, a new press
        self.assertEqual(kinds(h.events()), [("release", 0), ("button", 0)])


if __name__ == "__main__":
    unittest.main()
