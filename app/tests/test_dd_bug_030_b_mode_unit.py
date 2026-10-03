"""DD-BUG-030: parameter mode B types its value with an explicit unit, so a document set to inches still gets the
millimetre value the starts and ranges assume (Onshape converts "25.10 mm"). Headless, no SendInput."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cc5_support import Clock  # noqa: E402

from control_center.onshape_app import CTRL, RINGS, OnshapeApp, Param  # noqa: E402

HOME, ORBIT, WHEEL, PAN = 0, 1, 2, 3


class BModeUnitTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock(10.0)
        self.app = OnshapeApp(120, clock=self.clock)
        self.app.typed = True                           # B

    def start(self, ring, index):
        self.app.down(WHEEL)
        self.clock.advance(0.26)
        self.app.tick()
        self.app.ring, self.app.entry = ring, index
        self.app.up(WHEEL)
        self.assertIsNotNone(self.app.param)

    def typed_after_rest(self):
        self.clock.advance(0.4)
        actions = self.app.tick()
        return [a[1] for a in actions if a[0] == "text"]

    def test_b_mode_types_explicit_unit(self):
        self.start(0, 2)                                # EXTRUDE, DEPTH 25
        self.app.turn(1)                                # +0.1 (7.5 detents per step: one detent rounds into it)
        self.app.turn(7)
        self.assertEqual(self.typed_after_rest(), ["25.10 mm"])

    def test_confirm_retype_carries_the_unit(self):
        self.start(0, 4)                                # FILLET, RADIUS 1
        self.app.turn(8)
        self.app.down(WHEEL)
        actions = self.app.up(WHEEL)
        self.assertIn(("text", "1.10 mm"), actions)
        self.assertEqual(actions[0], ("chord", (CTRL,), "A"))

    def test_every_parameter_is_a_millimetre_length(self):
        params = [c.param for ring in RINGS for c in ring.commands if c.param is not None]
        self.assertEqual(len(params), 6)
        self.assertTrue(all(p.unit == "mm" for p in params))

    def test_a_unitless_param_types_the_bare_number(self):
        self.assertEqual(Param("X", 1.0, 0.0, 2.0).unit, "mm")
        self.app.param = (0, 2, Param("X", 1.0, 0.0, 2.0, unit=""))
        self.app.value = 1.5
        self.assertIn(("text", "1.50"), self.app._retype())


if __name__ == "__main__":
    unittest.main()
