"""DD-BUG-007: a re-home without a disconnect (the knob after a recalibration: runtime calls
set_hardware(True)) closes an open overlay, leaves Seek and lets go of Onshape before Home's entry.

Before the fix the Screen was replaced under the overlay: the explorer / Up next / picker stayed drawn
(no close effect) and the next Full screen was refused as busy."""
import unittest

from cc5_support import Fixture
from r3_support import R3Fixture

CLOSES = ("explorer_close", "upnext_close", "windows_hide", "windows_cancel")


class RehomeTests(Fixture):
    def rehome(self):
        self.c.drain()
        self.c.set_hardware(True)
        effects = self.c.drain()
        kinds = [e["kind"] for e in effects]
        closes = [k for k in kinds if k in CLOSES]
        enters = [i for i, k in enumerate(kinds) if k == "device_enter"]
        self.assertEqual(len(closes), 1, kinds)
        self.assertEqual(len(enters), 1, kinds)
        self.assertLess(kinds.index(closes[0]), enters[0], kinds)
        self.assertEqual(self.c.screen.mode, "home")
        return effects

    def test_set_hardware_rehome_closes_open_explorer(self):
        self.browse()
        self.press(1)
        self.assertEqual(self.c.screen.mode, "explorer")
        effects = self.rehome()
        self.assertEqual([e["reason"] for e in effects if e["kind"] == "explorer_close"], ["disconnect"])

    def test_set_hardware_rehome_closes_open_upnext(self):
        self.upnext()
        self.assertEqual(self.c.screen.mode, "upnext")
        self.rehome()

    def test_set_hardware_rehome_hides_the_picker_without_u12(self):
        self.open_windows()
        self.assertEqual(self.c.screen.mode, "windows")
        effects = self.rehome()
        self.assertEqual([e["kind"] for e in effects if e["kind"].startswith("windows_")], ["windows_hide"])

    def test_set_hardware_rehome_leaves_seek_dropping_its_target(self):
        self.seek()
        self.assertEqual(self.c.screen.mode, "seek")
        seek = self.c.screen.seek
        self.turn_to(self.c.screen.index + 3)
        self.c.drain()
        self.c.set_hardware(True)
        self.assertTrue(seek.left)
        self.assertTrue(seek.dropped)
        self.assertIsNone(seek.due)
        self.assertEqual(self.c.screen.mode, "home")
        self.assertEqual([e["kind"] for e in self.c.drain()].count("device_enter"), 1)

    def test_rehome_at_root_is_one_entry_and_no_close(self):
        self.c.set_hardware(True)
        kinds = [e["kind"] for e in self.c.drain()]
        self.assertEqual(kinds.count("device_enter"), 1)
        self.assertFalse([k for k in kinds if k in CLOSES])


class OnshapeRehomeTests(R3Fixture):
    def test_set_hardware_rehome_lets_go_of_onshape(self):
        self.assertTrue(self.c.enter_onshape())
        self.c.onshape_input("down", 0)
        self.c.onshape_app = {"wheel": True}
        self.c.drain()
        self.c.set_hardware(True)
        self.assertEqual(self.c.screen.mode, "launcher")
        self.assertIsNone(self.c.onshape_app)
        self.assertEqual([e["kind"] for e in self.c.drain()].count("device_enter"), 1)


if __name__ == "__main__":
    unittest.main()
