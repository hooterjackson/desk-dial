"""DD-TST-001: in Onshape mode, keys the command wheel or parameter mode swallow never change the feel, so they never
re-enter (a re-entry re-activates the injector, whose app reset would close the wheel / parameter mode unsent).
Headless: the r3 fixture, never a port or a window."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from r3_support import R3Fixture  # noqa: E402


class OnshapeSwallowedKeysTests(R3Fixture):

    def enter(self, app):
        self.assertTrue(self.c.enter_onshape("test"))
        self.c.drain()
        self.c.feel_supported = True
        self.c.onshape_app = app

    def feel(self):
        return self.c.control()["feel"]

    def test_parameter_mode_keys_never_re_enter(self):
        self.enter({"param": {"step": 1}})
        before = self.c.control_id
        for slot in (0, 1, 3):
            self.c.onshape_input("down", slot)
            self.assertEqual(self.feel(), "detent.value")
            self.c.onshape_input("up", slot)
        self.assertEqual(self.c.control_id, before, "a parameter step never re-enters")

    def test_open_wheel_keys_never_re_enter(self):
        self.enter({"wheel": {"ring": 0}})
        self.c.onshape_input("down", 2)                # hold 3: the wheel
        before = self.c.control_id
        for slot in (0, 1, 3):
            self.c.onshape_input("down", slot)
            self.assertIn(slot, self.c._onshape_swallowed)
            self.assertEqual(self.feel(), "detent.value")
            self.c.onshape_input("up", slot)
        self.c.onshape_input("up", 2)
        self.assertEqual(self.c.control_id, before, "a ring switch never re-enters")

    def test_key_two_down_without_wheel_state_swallows_too(self):
        self.enter({})
        self.c.onshape_input("down", 2)
        before = self.c.control_id
        self.c.onshape_input("down", 0)
        self.c.onshape_input("up", 0)
        self.assertEqual(self.c.control_id, before)

    def test_plain_modifier_still_turns_fluid(self):
        self.enter({})
        before = self.c.control_id
        self.c.onshape_input("down", 1)
        self.assertEqual(self.feel(), "fluid.light")
        self.assertEqual(self.c.control_id, before + 1)
        self.c.onshape_input("up", 1)
        self.assertEqual(self.feel(), "detent.value")
        self.assertEqual(self.c.control_id, before + 2)

    def test_wheel_key_under_a_held_modifier_opens_nothing(self):
        # OnshapeApp.down: 3 pressed while 1 is held does nothing (no wheel). Once 1 is up, a modifier pressed next
        # drags in the injector, so the knob turns fluid with it (it used to stay in detents, swallowed).
        self.enter({})
        self.c.onshape_input("down", 0)                # tilt (fluid)
        self.c.onshape_input("down", 2)                # swallowed by the injector: no wheel
        self.assertFalse(self.c._onshape_wheel_open())
        self.assertEqual(self.feel(), "fluid.light")
        self.c.onshape_input("up", 0)
        self.assertEqual(self.feel(), "detent.value")
        before = self.c.control_id
        self.c.onshape_input("down", 1)                # orbit: drags in the injector
        self.assertNotIn(1, self.c._onshape_swallowed)
        self.assertEqual(self.feel(), "fluid.light")
        self.assertEqual(self.c.control_id, before + 1, "the drag turns the knob fluid")

    def test_three_keys_are_a_chord_never_a_drag(self):
        # The reviewer's order 1, 3, 2: three buttons down are the Home chord building (CHORD_KEYS); the injector
        # starts no drag (OnshapeApp.chord) and the knob zooms in detents, as before DD-TST-001.
        self.enter({})
        self.c.onshape_input("down", 0)
        self.c.onshape_input("down", 2)
        self.c.onshape_input("down", 1)
        self.assertTrue(self.c.onshape_keys.chording)
        self.assertEqual(self.feel(), "detent.value")

    def test_wheel_mirrors_the_injector_against_onshape_app(self):
        from control_center.onshape import KeyTracker
        from control_center.onshape_app import OnshapeApp
        for order in ([0, 2, 1], [2, 0, 1], [2, 1], [2, 3], [0, 2], [3, 2], [2, 0, 3]):
            with self.subTest(order=order):
                self.c.exit_onshape("test")
                self.enter({})
                app = OnshapeApp(67, clock=self.clock)
                keys = KeyTracker()
                for slot in order:
                    keys.down(slot)
                    if keys.chording:
                        app.chord(slot)
                    else:
                        app.down(slot)
                    self.c.onshape_input("down", slot)
                    self.assertEqual(self.c._onshape_wheel_open(), app.wheel_open)
                    if not keys.chording and slot != 2:
                        injector_drags = not app.busy and not app.swallowed(slot)
                        self.assertEqual(slot not in self.c._onshape_swallowed, injector_drags)
                        self.assertEqual(self.feel() == "fluid.light", injector_drags)

    def test_modifier_right_after_parameter_mode_closes_drags(self):
        # The snapshot still says `param` until the next poll: 3's release ended parameter mode, so the next modifier
        # drags in the injector, and the knob turns fluid with it.
        self.enter({"param": {"step": 1}})
        self.c.onshape_input("down", 2)                # F3 in parameter mode
        self.c.onshape_input("up", 2)                  # OK: parameter mode ends
        self.c.onshape_input("down", 1)                # orbit, snapshot not yet polled
        self.assertNotIn(1, self.c._onshape_swallowed)
        self.assertEqual(self.feel(), "fluid.light")

    def test_parameter_mode_still_owns_keys_once_the_lag_passed(self):
        self.enter({"param": {"step": 1}})
        self.c.onshape_input("down", 2)
        self.c.onshape_input("up", 2)                  # an OK the injector rolled back (abort): param reopened
        self.clock.advance(1.0)
        before = self.c.control_id
        self.c.onshape_input("down", 1)
        self.assertIn(1, self.c._onshape_swallowed)
        self.assertEqual(self.feel(), "detent.value")
        self.assertEqual(self.c.control_id, before)

if __name__ == "__main__":
    unittest.main()
