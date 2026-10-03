"""DD-BUG-027: no keys go out while a real modifier is held (ONSHAPE.md): parameter mode's wheel notches and B's
typed value are skipped like a chord, counted in commandsSkipped. Headless: the recording fake backend."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cc5_support import Clock  # noqa: E402
from test_onshape import FakeBackend  # noqa: E402

from control_center.onshape import OnshapeInjector, chord_events, text_events  # noqa: E402

HOME, ORBIT, WHEEL, PAN = 0, 1, 2, 3


class ModifierHeldTests(unittest.TestCase):
    CONTROL = 9

    def make(self, typed=False):
        self.clock = Clock(100.0)
        self.backend = FakeBackend()
        self.inj = OnshapeInjector(self.backend, clock=self.clock, start=False)
        self.inj.activate(self.CONTROL, [0, 1, 2, 3], 120, app=True)
        self.inj.step()
        self.inj.app.typed = typed
        self.kd(WHEEL)
        self.post("position", delta=1)
        self.post("position", delta=10)                      # EXTRUDE: parameter mode
        self.ku(WHEEL)
        self.assertIn("param", self.inj.app_state())
        self.backend.batches.clear()
        self.skipped = self.inj.status()["commandsSkipped"]

    def post(self, kind, **values):
        values.setdefault("id", self.CONTROL)
        self.inj.post(kind, values)
        self.inj.step()

    def kd(self, raw):
        self.post("button", button=raw, index=raw)

    def ku(self, raw):
        self.post("release", button=raw, index=raw)

    def test_scroll_and_text_skipped_with_real_modifier(self):
        self.make()
        self.backend.modifiers = True                        # a real Ctrl still down
        self.post("position", delta=8)                       # A: one plain notch
        self.assertEqual(self.backend.events(), [])
        self.assertEqual(self.inj.status()["commandsSkipped"], self.skipped + 1)
        self.assertEqual(self.inj.status()["scrolls"], 0)

    def test_a_b_retype_is_skipped_and_types_once_the_modifier_is_up(self):
        self.make(typed=True)
        self.backend.modifiers = True
        self.post("position", delta=16)                      # 25.00 -> 25.20
        self.clock.advance(0.4)
        self.inj.step()                                      # the rest: the retype is due
        self.clock.advance(0.05)
        self.inj.step()
        self.assertEqual(self.backend.events(), [], "no Ctrl+A, no digits with the real modifier down")
        self.assertGreaterEqual(self.inj.status()["commandsSkipped"], self.skipped + 1)
        self.assertEqual(self.inj.status()["typed"], 0)
        self.backend.modifiers = False
        self.clock.advance(0.4)
        self.inj.step()
        self.clock.advance(0.05)
        self.inj.step()
        self.assertEqual(self.backend.events(), chord_events(("ctrl",), "A") + text_events("25.20 mm"),
                         "the pending value goes out once the modifier is released")

    def test_a_text_step_after_its_chord_is_skipped_when_a_modifier_goes_down_meanwhile(self):
        self.make(typed=True)
        self.post("position", delta=16)
        self.clock.advance(0.4)
        self.inj.step()                                      # Ctrl+A went out, the digits wait 20 ms
        self.assertEqual(self.backend.events(), chord_events(("ctrl",), "A"))
        self.backend.modifiers = True
        self.clock.advance(0.05)
        self.inj.step()
        self.assertFalse(any(e[0] == "char" for e in self.backend.events()))
        self.assertEqual(self.inj.status()["typed"], 0)

    def test_without_a_modifier_the_notch_goes_out(self):
        self.make()
        self.post("position", delta=8)
        self.assertEqual(self.backend.events(), [("wheel", 120)])


if __name__ == "__main__":
    unittest.main()
