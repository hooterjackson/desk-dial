"""DD-BUG-011: a command the injector did not send (refused off target, skipped for a held real modifier, a short
SendInput, a refused search tail) must not leave the app in parameter mode or echo it as run. Headless: the
recording fake backend, never SendInput."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cc5_support import Clock  # noqa: E402
from test_onshape import FakeBackend  # noqa: E402

from control_center.onshape import OnshapeInjector, chord_events  # noqa: E402
from control_center.onshape_app import SHIFT, OnshapeApp  # noqa: E402

HOME, ORBIT, WHEEL, PAN = 0, 1, 2, 3


class RefusedCommandTests(unittest.TestCase):
    CONTROL = 9

    def make(self, **kwargs):
        self.clock = Clock(100.0)
        self.backend = FakeBackend(**kwargs)
        self.inj = OnshapeInjector(self.backend, clock=self.clock, start=False)
        self.inj.activate(self.CONTROL, [0, 1, 2, 3], 120, app=True)
        self.inj.step()

    def post(self, kind, **values):
        values.setdefault("id", self.CONTROL)
        self.inj.post(kind, values)
        self.inj.step()

    def kd(self, raw):
        self.post("button", button=raw, index=raw)

    def ku(self, raw):
        self.post("release", button=raw, index=raw)

    def run_extrude(self):
        self.kd(WHEEL)
        self.post("position", delta=1)                       # reveal
        self.post("position", delta=10)                      # EXTRUDE
        self.ku(WHEEL)

    def assert_nothing_entered(self):
        state = self.inj.app_state()
        self.assertNotIn("param", state)
        self.assertNotIn("echo", state)
        self.assertFalse(self.inj.app.busy)

    def assert_later_input_sends_nothing_keyed(self):
        """Pointing at the model afterwards: 1 held + turn tilts (a drag, no Ctrl+wheel), tap 3 is Undo (no Enter)."""
        self.backend.target = True
        self.backend.modifiers = False
        self.backend.short_after = None
        self.backend.batches.clear()
        self.kd(HOME)
        self.post("position", delta=5)
        self.ku(HOME)
        events = self.backend.events()
        self.assertNotIn(("wheel", 120), events, "no parameter-mode scroll")
        self.assertNotIn(("key", 0x11, False), events, "no Ctrl held for a fine step")
        self.backend.batches.clear()
        self.kd(WHEEL)
        self.clock.advance(0.1)
        self.ku(WHEEL)
        self.assertEqual(self.backend.events(), chord_events(("ctrl",), "Z"), "tap 3 is Undo, not OK")
        self.assertNotIn("echo", self.inj.app_state())

    def test_a_refused_parameter_command_does_not_enter_parameter_mode(self):
        self.make(target=False)
        self.run_extrude()
        self.assertEqual(self.backend.events(), [])
        self.assert_nothing_entered()
        self.assertEqual(self.inj.take_events(), ["refused"])
        self.assert_later_input_sends_nothing_keyed()

    def test_a_chord_skipped_for_a_held_modifier_does_not_enter_parameter_mode(self):
        self.make(modifiers=True)
        self.run_extrude()
        self.assertEqual(self.backend.events(), [])
        self.assertEqual(self.inj.status()["commandsSkipped"], 1)
        self.assert_nothing_entered()
        self.assert_later_input_sends_nothing_keyed()

    def test_a_short_send_does_not_enter_parameter_mode(self):
        self.make(short_after=0)
        self.run_extrude()
        self.assertEqual(self.inj.status()["short"], 1)
        self.assert_nothing_entered()
        self.assert_later_input_sends_nothing_keyed()

    def test_a_refused_command_is_not_echoed_and_the_ring_entry_is_kept(self):
        self.make(target=False)
        self.kd(WHEEL)
        self.post("position", delta=1)
        self.post("position", delta=20)                      # REVOLVE (no parameter)
        self.ku(WHEEL)
        self.assert_nothing_entered()
        self.assertEqual(self.inj.app._ring_entry[0], 0, "the wheel reopens where it did before")

    def test_a_refused_search_tail_aborts_parameter_mode(self):
        self.make()
        self.kd(WHEEL)
        self.post("position", delta=1)
        self.post("position", delta=40)                      # CHAMFER: tool search + parameter
        self.ku(WHEEL)
        self.assertIn("param", self.inj.app_state(), "the search chord went out: the dialog is opening")
        self.backend.target = False                          # the cursor leaves the model before the phrase
        self.clock.advance(0.26)
        self.inj.step()
        self.assert_nothing_entered()
        self.assertEqual(self.inj.take_events(), ["refused"])
        self.clock.advance(1.0)
        self.inj.step()
        self.assertFalse(any(e[0] == "char" for e in self.backend.events()), "the phrase never typed")

    def test_a_sent_command_still_enters_parameter_mode_and_echoes_on_ok(self):
        self.make()
        self.run_extrude()
        self.assertEqual(self.backend.events(), chord_events((SHIFT,), "E"))
        self.assertIn("param", self.inj.app_state())
        self.kd(WHEEL)
        self.ku(WHEEL)
        self.assertEqual(self.inj.app_state()["echo"], {"ring": 0, "index": 2, "seq": 1})

    def test_a_refused_ok_keeps_parameter_mode_open(self):
        self.make()
        self.run_extrude()
        self.backend.target = False
        self.kd(WHEEL)
        self.ku(WHEEL)                                       # OK refused: the dialog is still open
        state = self.inj.app_state()
        self.assertIn("param", state)
        self.assertNotIn("echo", state)
        self.backend.target = True
        self.kd(WHEEL)
        self.ku(WHEEL)
        self.assertEqual(self.backend.events()[-2:], chord_events((), "ENTER"))
        self.assertEqual(self.inj.app_state()["echo"], {"ring": 0, "index": 2, "seq": 1})

    def test_app_abort_without_a_pending_transaction_changes_nothing(self):
        app = OnshapeApp(120, clock=Clock(1.0))
        app.abort()
        app.settle()
        self.assertEqual(app.snapshot(), {"flash": 0})


if __name__ == "__main__":
    unittest.main()
