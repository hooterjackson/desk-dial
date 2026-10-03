"""DD-SEC-001 review: a keystroke refused because the keyboard focus is outside the page (the cursor IS on the
model) raises its own result, ``focus_refused``, so the knob can say "Click the model first"; a cursor off the
model still raises ``refused`` ("Point at the model"). Headless: fake backend, never SendInput, never COM."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cc5_support import Clock  # noqa: E402
from test_dd_sec_001_keyboard_focus import FocusBackend  # noqa: E402

from control_center import onshape  # noqa: E402
from control_center.onshape import OnshapeInjector  # noqa: E402

HOME, ORBIT, WHEEL, PAN = 0, 1, 2, 3


class FocusRefusedEventTests(unittest.TestCase):
    CONTROL = 9

    def make(self, **kwargs):
        self.clock = Clock(100.0)
        self.backend = FocusBackend(**kwargs)
        self.inj = OnshapeInjector(self.backend, clock=self.clock, start=False)
        self.inj.activate(self.CONTROL, [0, 1, 2, 3], 120, app=True)
        self.inj.step()

    def post(self, kind, **values):
        values.setdefault("id", self.CONTROL)
        self.inj.post(kind, values)
        self.inj.step()

    def tap_undo(self):
        self.post("button", button=WHEEL, index=WHEEL)
        self.clock.advance(0.1)
        self.post("release", button=WHEEL, index=WHEEL)

    def test_the_constant(self):
        self.assertEqual(onshape.FOCUS_REFUSED, "focus_refused")
        self.assertNotEqual(onshape.FOCUS_REFUSED, onshape.REFUSED)

    def test_focus_outside_the_page_raises_focus_refused(self):
        self.make(focus=False)
        self.tap_undo()
        self.assertEqual(self.inj.take_events(), [onshape.FOCUS_REFUSED])
        status = self.inj.status()
        self.assertEqual(status["focusRefused"], 1)
        self.assertEqual(status["refusals"], 1, "still one refusal in the totals")

    def test_cursor_off_the_model_still_raises_refused(self):
        self.make(focus=False, target=False)
        self.tap_undo()
        self.assertEqual(self.inj.take_events(), [onshape.REFUSED], "the cursor gate speaks first")
        self.assertEqual(self.inj.status()["focusRefused"], 0)

    def test_one_result_per_burst(self):
        self.make(focus=False)
        self.tap_undo()
        self.tap_undo()
        self.assertEqual(self.inj.take_events(), [onshape.FOCUS_REFUSED])

    def test_focus_in_the_page_sends_and_raises_no_refusal(self):
        self.make(focus=True)
        self.tap_undo()
        self.assertEqual(self.inj.take_events(), [onshape.UNDO])


if __name__ == "__main__":
    unittest.main()
