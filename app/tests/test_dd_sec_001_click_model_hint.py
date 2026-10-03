"""DD-SEC-001 follow-up (controller): the injector's ``focus_refused`` result (the cursor is on the model but the
keyboard focus is outside the page) is a refusal like ``refused`` (same sound, buzz and red flash) whose words say
"Click the model first" instead of "Point at the model". Before this, the controller ignored ``focus_refused``:
no sound, no haptic, no words. Headless: no Tk, no ports, no network."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r3_support import CAPS_V5, CAPS_V6, R3Fixture  # noqa: E402

from control_center import device, onshape, presentation  # noqa: E402
from control_center.controller import COPY  # noqa: E402


class ClickModelHintTests(R3Fixture):
    def enter(self):
        self.assertTrue(self.c.enter_onshape("test"))
        self.c.drain()

    def test_the_copy(self):
        self.assertEqual(COPY["knob.title.onshape.focus_refused"], "Click the model first")
        self.assertIn("knob.sub.onshape.focus_refused", COPY)
        self.assertEqual(COPY["knob.title.onshape.refused"], "Point at the model", "unchanged")

    def test_focus_refused_says_click_the_model_first_with_sound_and_buzz(self):
        self.enter()
        self.c.onshape_input(onshape.FOCUS_REFUSED)
        frame = self.frame()
        self.assertEqual(frame["title"], "Click the model first")
        self.assertEqual(frame["subtitle"], COPY["knob.sub.onshape.focus_refused"])
        self.assertEqual((frame["feedback"]["kind"], frame["feedback"]["moment"]), ("err", "refused"))
        self.assertEqual(self.c.onshape_action(), "focus_refused")
        self.tick(2.1)
        self.assertEqual(self.frame()["title"], "ZOOM")

    def test_focus_refused_arms_the_refuse_buzz(self):
        self.enter()
        calls = []
        original = self.c._haptic
        self.c._haptic = lambda token, *a, **k: (calls.append(token), original(token, *a, **k))[1]
        self.c.onshape_input(onshape.FOCUS_REFUSED)
        self.assertIn("refuse.buzz", calls)

    def test_cursor_refusal_still_says_point_at_the_model(self):
        self.enter()
        self.c.onshape_input(onshape.FOCUS_REFUSED)
        self.c.onshape_input(onshape.REFUSED)
        self.assertEqual(self.frame()["title"], "Point at the model")
        self.c.onshape_input(onshape.FOCUS_REFUSED)
        self.assertEqual(self.frame()["title"], "Click the model first", "the latest refusal speaks")

    def test_the_app_canvas_flags_it_refused(self):
        self.enter()
        self.c.onshape_app = {}
        self.c.onshape_input(onshape.FOCUS_REFUSED)
        self.assertTrue(self.frame()["app"]["refused"])

    def test_the_frame_passes_the_device_validator(self):
        self.enter()
        self.c.onshape_input(onshape.FOCUS_REFUSED)
        wire = self.wire(CAPS_V6)
        self.assertLessEqual(device.frame_line_bytes(wire), presentation.FRAME_BUDGET_BYTES_V5)
        stored, invalid = device.v5_parse(dict(device._frame({"id": 3, **self.c.frame()}, CAPS_V5)))
        self.assertEqual(invalid, [])

    def test_reentry_clears_the_hint(self):
        self.enter()
        self.c.onshape_input(onshape.FOCUS_REFUSED)
        self.c.exit_onshape("test")
        self.enter()
        self.assertEqual(self.frame()["title"], "ZOOM")


if __name__ == "__main__":
    unittest.main()
