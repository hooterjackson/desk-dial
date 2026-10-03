"""DD-TST-001 (injector side): a re-activation within one Onshape session (a host re-entry hands the injector a new
control id) keeps the command wheel / parameter mode open, only the detent count follows; a new session (after a
deactivate) starts clean. Fake backend, no thread, never SendInput."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cc5_support import Clock  # noqa: E402
from test_onshape import FakeBackend  # noqa: E402

from control_center.onshape import OnshapeInjector, chord_events  # noqa: E402
from control_center.onshape_app import SHIFT  # noqa: E402

WHEEL = 2


class ReactivateKeepsAppTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock(100.0)
        self.backend = FakeBackend()
        self.inj = OnshapeInjector(self.backend, clock=self.clock, start=False)
        self.control = 9
        self.inj.activate(self.control, [0, 1, 2, 3], 120, app=True)
        self.inj.step()

    def post(self, kind, **values):
        values.setdefault("id", self.control)
        self.inj.post(kind, values)
        self.inj.step()

    def open_wheel_on_entry_two(self):
        self.post("button", button=WHEEL, index=WHEEL)
        self.clock.advance(0.3)
        self.inj.step()
        self.post("position", delta=10)
        self.assertEqual(self.inj.app_state()["wheel"]["index"], 2)

    def test_re_entry_keeps_the_open_wheel_and_its_release_sends(self):
        self.open_wheel_on_entry_two()
        app = self.inj.app
        self.control = 10                                    # host re-entry: new control id, same session
        self.inj.activate(self.control, [0, 1, 2, 3], 96, app=True)
        self.inj.step()
        self.assertIs(self.inj.app, app)
        self.assertEqual(self.inj.app.detents, 96, "the detent count follows the profile")
        self.assertEqual(self.inj.app_state()["wheel"]["index"], 2, "the wheel stays open")
        self.post("release", button=WHEEL, index=WHEEL)
        self.assertEqual(self.backend.events(), chord_events((SHIFT,), "E"))
        self.assertEqual(self.inj.app_state()["param"]["mode"], "A")

    def test_same_id_re_activation_keeps_parameter_mode(self):
        self.open_wheel_on_entry_two()
        self.post("release", button=WHEEL, index=WHEEL)
        self.assertIsNotNone(self.inj.app_state()["param"])
        self.inj.activate(self.control, [0, 1, 2, 3], 120, app=True)
        self.inj.step()
        self.assertIsNotNone(self.inj.app_state()["param"], "parameter mode survives a re-activation")

    def test_a_new_session_after_deactivate_starts_clean(self):
        self.open_wheel_on_entry_two()
        self.inj.deactivate()
        self.inj.step()
        self.control = 11
        self.inj.activate(self.control, [0, 1, 2, 3], 120, app=True)
        self.inj.step()
        state = self.inj.app_state()
        self.assertFalse(state.get("wheel"), "a new session never inherits an open wheel")
        self.assertFalse(state.get("param"))
        self.assertFalse(self.inj.app.wheel_open)


if __name__ == "__main__":
    unittest.main()
