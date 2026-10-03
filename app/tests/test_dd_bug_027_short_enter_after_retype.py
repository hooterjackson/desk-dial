"""DD-BUG-027 review: a B-mode OK with a pending value types it, then sends Enter. Each settle belongs to its own
transaction, so a short or refused Enter after the typed value reopens parameter mode with its value and shows no
echo (the DD-BUG-011 rollback). Headless: the recording fake backend, never SendInput."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cc5_support import Clock  # noqa: E402
from test_onshape import FakeBackend  # noqa: E402

from control_center.onshape import OnshapeInjector, chord_events  # noqa: E402

HOME, ORBIT, WHEEL, PAN = 0, 1, 2, 3
VK_RETURN = 0x0D


class ShortEnterBackend(FakeBackend):
    """Every batch carrying the Enter key goes out short while ``enter_short`` is set."""
    enter_short = False

    def send(self, events):
        sent = super().send(events)
        if self.enter_short and any(e[0] == "key" and e[1] == VK_RETURN for e in events):
            return len(events) - 1
        return sent


class ShortEnterAfterRetypeTests(unittest.TestCase):
    CONTROL = 9

    def setUp(self):
        self.clock = Clock(100.0)
        self.backend = ShortEnterBackend()
        self.inj = OnshapeInjector(self.backend, clock=self.clock, start=False)
        self.inj.activate(self.CONTROL, [0, 1, 2, 3], 120, app=True)
        self.inj.step()
        self.inj.app.typed = True
        self.kd(WHEEL)
        self.post("position", delta=1)
        self.post("position", delta=10)                      # EXTRUDE: parameter mode, B
        self.ku(WHEEL)
        self.assertIn("param", self.inj.app_state())
        self.start_value = self.inj.app_state()["param"]["value"]
        self.post("position", delta=8)                       # the value changes: pending (not typed yet)
        self.assertTrue(self.inj.app._dirty)
        self.changed = self.inj.app.value

    def post(self, kind, **values):
        values.setdefault("id", self.CONTROL)
        self.inj.post(kind, values)
        self.inj.step()

    def kd(self, raw):
        self.post("button", button=raw, index=raw)

    def ku(self, raw):
        self.post("release", button=raw, index=raw)

    def tap3(self):
        self.kd(WHEEL)
        self.clock.advance(0.1)
        self.ku(WHEEL)
        for _ in range(4):                                   # let any wait in the list run out
            self.clock.advance(0.05)
            self.inj.step()

    def test_a_short_enter_after_the_retype_reopens_parameter_mode(self):
        self.backend.enter_short = True
        self.tap3()
        self.assertTrue(any(e[0] == "char" for e in self.backend.events()), "the value was typed")
        state = self.inj.app_state()
        self.assertIn("param", state, "Enter never fully went out: the dialog is still open")
        self.assertNotIn("echo", state, "not confirmed")
        self.assertEqual(self.inj.app.value, self.changed, "the value is kept")
        self.assertTrue(self.inj.app.busy)

    def test_the_next_tap_confirms_once_enter_goes_out(self):
        self.backend.enter_short = True
        self.tap3()
        self.backend.enter_short = False
        self.backend.batches.clear()
        self.tap3()
        self.assertEqual(self.backend.events()[-2:], chord_events((), "ENTER"))
        state = self.inj.app_state()
        self.assertNotIn("param", state)
        self.assertEqual(state["echo"], {"ring": 0, "index": 2, "seq": 1})

    def test_a_full_send_still_confirms_once(self):
        self.tap3()
        state = self.inj.app_state()
        self.assertNotIn("param", state)
        self.assertEqual(state["echo"], {"ring": 0, "index": 2, "seq": 1})
        self.assertEqual(self.inj.app._txns, [])

    def test_settle_order_matches_action_order(self):
        app = self.inj.app
        actions = app._param_end(True)
        kinds = [t["kind"] for t in app._txns]
        self.assertEqual(kinds, ["retype", "end"])
        self.assertEqual([a for a in actions if a[0] == "settle"], [("settle",), ("settle",)])
        app.settle()                                         # the typed value went out
        self.assertNotEqual(app.echo_seq, 1, "typing the value is not the confirmation")
        app.abort()                                          # Enter did not go out
        self.assertIsNotNone(app.param)
        self.assertTrue(app._dirty)


if __name__ == "__main__":
    unittest.main()
