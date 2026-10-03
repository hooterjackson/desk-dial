"""DD-BUG-002: the Lights settle correction is bounded to the write's settle window.

Before the fix `_lights_final` never expired once the echo matched: minutes later a close external change
(the HA app at 76 % after the knob set 80 %) was masked back to 80 and "corrected" with a lights_set; a
scene landing within LIGHTS_NEAR of the last write was reverted right after SCENE_SETTLE."""
import unittest

from r3_support import R3Fixture  # noqa: I001  (sets the import path first)


class SettleWindowTests(R3Fixture):
    def setUp(self):
        super().setUp()
        self.press(2)
        self.serve()

    def sets(self):
        return [e for e in self.c.drain() if e["kind"] == "lights_set"]

    def set_to(self, level):
        self.turn_to(level - 1)                         # DD-DES-003: while on, position = level - 1
        self.tick()
        self.serve()
        self.c.lights_state(self.ha.read_state())

    def report(self, **values):
        self.ha.external(**values)
        self.c.lights_state(self.ha.read_state())

    def test_a_close_external_change_long_after_the_write_is_shown_not_reverted(self):
        self.set_to(80)
        self.assertEqual(self.c.lights.bri, 80)
        for _ in range(600):                           # ten minutes at rest
            self.tick(1.0)
            self.serve()
        self.sets()
        self.report(bri=76)                            # the HA app sets 76 %
        self.assertEqual(self.c.lights.bri, 76)
        for _ in range(15):
            self.tick(1.0)
            self.assertEqual(self.sets(), [])
        self.assertEqual(self.ha.read_state()["bri"], 76)
        self.assertEqual(self.c.lights.bri, 76)

    def test_a_close_scene_right_after_the_write_is_not_reverted(self):
        self.set_to(80)
        scene = self.c.lights.scenes[0]
        for row in self.ha.scenes:
            if row["entity_id"] == scene["entity_id"]:
                row.update(bri=76, kelvin=self.c.lights.kelvin)
        self.press(1)                                  # Scenes
        self.serve()
        self.assertEqual(self.c.screen.mode, "scenes")
        self.press(3)                                  # run the focused (first) scene
        self.serve()
        self.assertEqual(self.c.lights.bri, 76)
        for _ in range(15):
            self.tick(1.0)
            effects = self.c.drain()
            self.assertEqual([e for e in effects if e["kind"] == "lights_set"], [])
            self.serve(effects)
        self.assertEqual(self.c.lights.bri, 76)

    def test_the_short_report_right_after_the_write_is_still_corrected_once(self):
        from control_center.controller import LIGHTS_SETTLE
        self.set_to(100)
        self.report(bri=95)
        self.assertEqual(self.c.lights.bri, 100)
        self.tick(LIGHTS_SETTLE + 0.1)
        self.assertEqual([e.get("transition") for e in self.sets()], [0])


if __name__ == "__main__":
    unittest.main()
