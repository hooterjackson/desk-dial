"""DD-SEC-001 follow-up (frame): on the knob's own Onshape canvas a keyboard-focus refusal is told apart from a
cursor refusal. Both set ``app.refused``; only the focus refusal adds ``app.refusedFocus`` so the firmware can read
CLICK MODEL FIRST instead of POINT AT MODEL. The key is unknown to an older firmware, which ignores it (the frame is
still accepted). Headless: no Tk, no ports, no network."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r3_support import CAPS_V5, CAPS_V6, R3Fixture  # noqa: E402

from control_center import device, onshape, presentation  # noqa: E402


class RefusedFocusFlagTests(R3Fixture):
    def enter(self):
        self.assertTrue(self.c.enter_onshape("test"))
        self.c.drain()
        self.c.onshape_app = {}

    def test_focus_refusal_flags_refused_focus(self):
        self.enter()
        self.c.onshape_input(onshape.FOCUS_REFUSED)
        app = self.frame()["app"]
        self.assertIs(app["refused"], True)
        self.assertIs(app["refusedFocus"], True)

    def test_cursor_refusal_has_no_focus_flag(self):
        self.enter()
        self.c.onshape_input(onshape.REFUSED)
        app = self.frame()["app"]
        self.assertIs(app["refused"], True)
        self.assertNotIn("refusedFocus", app)

    def test_flag_clears_with_the_refusal_window(self):
        self.enter()
        self.c.onshape_input(onshape.FOCUS_REFUSED)
        self.tick(2.1)
        app = self.frame()["app"]
        self.assertNotIn("refused", app)
        self.assertNotIn("refusedFocus", app)

    def test_older_firmware_reading_still_accepts_the_frame(self):
        self.enter()
        self.c.onshape_input(onshape.FOCUS_REFUSED)
        stored, ok = device.app_parse(self.frame()["app"])
        self.assertTrue(ok)
        self.assertTrue(stored["refused"])
        wire = self.wire(CAPS_V6)
        self.assertLessEqual(device.frame_line_bytes(wire), presentation.FRAME_BUDGET_BYTES_V5)
        _stored, invalid = device.v5_parse(dict(device._frame({"id": 3, **self.c.frame()}, CAPS_V5)))
        self.assertEqual(invalid, [])


if __name__ == "__main__":
    unittest.main()
