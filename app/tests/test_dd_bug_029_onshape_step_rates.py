"""DD-BUG-029: the wheel and parameter steps keep their per-turn rates at any detent count (12 wheel entries,
16 parameter steps, 48 fine steps a turn). The carry used to drop a rounded amount: at 67 detents the fine step
ran 66 a turn and the wheel 11. Pure state machine; nothing is sent."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from control_center import onshape_app as A  # noqa: E402

LONG_RING = (A.Ring("LONG", 0, tuple(A.Command(f"C{i}", (), "L") for i in range(500))),) + A.RINGS[1:]


def wheel_entries(detents, direction=1):
    with patch.object(A, "RINGS", LONG_RING):
        app = A.OnshapeApp(detents, clock=lambda: 0.0)
        app.down(A.WHEEL_SLOT, 0.0)
        app.turn(1, 0.0)                              # the first detent only reveals the wheel
        app.entry = 250
        for _ in range(detents):
            app.turn(direction, 0.0)
        return abs(app.entry - 250)


def param_steps(detents, hold=None, direction=1):
    app = A.OnshapeApp(detents, clock=lambda: 0.0)
    app.param = (0, 2, A.RINGS[0].commands[1].param)
    if hold is not None:
        app._down[hold] = 0.0
    total = 0
    for _ in range(detents):
        consumed, actions = app.turn(direction, 0.0)
        total += sum(abs(a[1]) for a in actions if a[0] == "scroll")
    return total


class StepRateTests(unittest.TestCase):
    def test_step_rates_per_turn_match_spec(self):
        for detents in (67, 127, 24, 48):
            for direction in (1, -1):
                with self.subTest(detents=detents, direction=direction):
                    self.assertEqual(wheel_entries(detents, direction), A.WHEEL_ENTRIES_PER_TURN)
                    self.assertEqual(param_steps(detents, None, direction), A.PARAM_STEPS_PER_TURN)
                    self.assertEqual(param_steps(detents, 0, direction), min(detents, A.PARAM_FINE_PER_TURN))

    def test_ten_turns_never_drift(self):
        app = A.OnshapeApp(67, clock=lambda: 0.0)
        app.param = (0, 2, A.RINGS[0].commands[1].param)
        app._down[0] = 0.0
        total = 0
        for _ in range(67 * 10):
            total += sum(a[1] for a in app.turn(1, 0.0)[1] if a[0] == "scroll")
        self.assertEqual(total, 480)


if __name__ == "__main__":
    unittest.main()
