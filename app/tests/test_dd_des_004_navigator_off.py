"""DD-DES-004: Navigator Off (and a mode without a Navigator card, Onshape) hands the desktop back
to the floating knob on an r3 knob: ``Navigator.update`` returns False, so ui releases the
'navigator' suppression. Headless: a real controller, a recording backend; no Tk, no ports."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r3_support import R3Fixture  # noqa: E402
from test_r3_navigator_model import Backend, Runtime  # noqa: E402
from control_center.navigator import Navigator  # noqa: E402


class FacadeTests(R3Fixture):
    def setUp(self):
        super().setUp()
        self.t = [100.0]
        self.backend = Backend()
        self.nav = Navigator(self.backend, clock=lambda: self.t[0])
        self.rt = Runtime(self.c)

    def tick(self, dt=0.0):
        self.t[0] += dt
        return self.nav.update(self.rt, self.c.frame())

    def test_off_hands_back_to_floating_knob(self):
        self.nav.set_mode("pinned")
        self.assertTrue(self.tick())
        self.assertTrue(self.backend.posts[-1]["visible"])
        self.nav.set_mode("off")
        self.assertFalse(self.tick(), "Off: the floating knob covers the desktop again")
        self.assertFalse(self.nav.active)
        self.assertFalse(self.backend.posts[-1]["visible"])
        self.assertFalse(self.backend.posts[-1]["eligible"])
        n = len(self.backend.posts)
        self.rt.touch_seq += 1
        self.nav.note_turn()
        self.assertFalse(self.tick(0.1))
        self.assertEqual(len(self.backend.posts), n, "hidden once, nothing more posted")
        self.assertEqual(self.backend.touches, 0, "a turn never shows an Off Navigator")
        self.nav.set_mode("pinned")
        self.assertTrue(self.tick(), "back on: the Navigator stands in again")

    def test_onshape_mode_hands_back_to_floating_knob(self):
        self.nav.set_mode("pinned")
        self.assertTrue(self.tick())
        self.c.screen.mode = "onshape"                    # A0: no Navigator card for Onshape yet
        self.assertFalse(self.tick())
        self.assertFalse(self.backend.posts[-1]["visible"])
        self.c.screen.mode = "launcher"
        self.assertTrue(self.tick())
        self.assertTrue(self.backend.posts[-1]["visible"])

    def test_overlay_modes_keep_the_floating_knob_suppressed(self):
        self.nav.set_mode("pinned")
        self.tick()
        from unittest import mock
        from control_center import navigator_model as NM
        real = NM.read_snapshot

        def upnext(controller, frame):                    # a full-screen overlay of its own
            snap = real(controller, frame)
            snap["mode"] = "upnext"
            return snap
        with mock.patch.object(NM, "read_snapshot", upnext):
            self.assertTrue(self.tick())
        self.assertFalse(self.backend.posts[-1]["visible"])


if __name__ == "__main__":
    unittest.main()
