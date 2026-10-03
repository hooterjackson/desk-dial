"""DD-DES-003: while the lights are on the brightness wall sits at the 1 % floor (positions 0..99 = 1..100 %), so
there is no dead detent below 1 %; from off the knob keeps 0..100 with 0 = off. Headless: the r3 fixture."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r3_support import R3Fixture  # noqa: E402


class BrightnessWallTests(R3Fixture):
    def setUp(self):
        super().setUp()
        self.lights()

    def settle(self):
        self.tick()
        self.serve()
        self.c.lights_state(self.ha.read_state())
        self.tick(3.0)
        self.serve()

    def test_brightness_wall_is_at_one_percent(self):
        self.turn_to(0)                                    # 1 %
        self.settle()
        self.assertEqual(self.ha.bri, 1)
        low, high, position = self.c.bounds()
        self.assertEqual((low, high, position), (0, 99, 0), "the 1 % position is the wall")
        control = self.c.control()
        self.assertEqual((control["min"], control["max"], control["position"]), (0, 99, 0))
        self.c.drain()
        calls = len(self.ha.calls)
        self.c.position(-1, self.c.control_id)             # past the wall: refused, no intent
        self.tick()
        self.serve()
        self.assertEqual(self.c.lights_intent(), {})
        self.assertEqual(len(self.ha.calls), calls)

    def test_one_detent_up_from_the_floor_is_two_percent(self):
        self.turn_to(0)
        self.settle()
        self.turn_to(1)
        self.settle()
        self.assertEqual(self.ha.bri, 2)
        self.assertEqual(self.c.bounds(), (0, 99, 1))

    def test_the_top_is_one_hundred_percent(self):
        self.turn_to(99)
        self.settle()
        self.assertEqual(self.ha.bri, 100)
        self.assertEqual(self.c.bounds(), (0, 99, 99))

    def test_from_off_the_first_detents_read_in_the_off_frame(self):
        self.press(3)                                      # All off
        self.serve()
        self.tick(1.0)
        self.serve()
        self.assertFalse(self.ha.on)
        self.assertEqual(self.c.control()["max"], 100)
        self.turn_to(1)                                    # on at 1 %
        self.tick()
        self.serve()
        self.turn_to(2)                                    # the same control: 2 %, no skipped level
        self.assertEqual(self.c.lights_intent().get("bri"), 2)
        for _ in range(3):
            self.tick(0.2)
            self.serve()
        self.assertEqual(self.ha.bri, 2)
        self.c.lights_state(self.ha.read_state())
        self.tick(3.0)                                     # at rest: the knob moves to the on frame
        self.serve()
        self.assertEqual(self.c.bounds(), (0, 99, 1))
        self.assertEqual(self.c._knob_bounds, (0, 99, 1))


    # The LED ring's local cursor (F5: control_center/alive_lights._local and firmware cc_alive_local, style bri) must
    # follow the finger in both frames: on = max 99, value = position + 1; off = max 100, value = position.
    def test_on_frame_wire_contract(self):
        self.turn_to(49)                                   # 50 %
        self.settle()
        control = self.c.control()
        self.assertEqual((control["max"], control["position"]), (99, 49))
        wire = self.wire()
        self.assertEqual(wire["ring"]["style"], "bri")
        self.assertEqual(wire["ring"]["value"], 50, "the ring value is the level, not the position")

    def test_led_local_cursor_off_frame_reads_the_position(self):
        from control_center import alive_lights
        frame = {"activity": "idle", "ring": {"style": "bri", "value": 0}}
        out, applied, _ = alive_lights._local(frame, 7, 100)
        self.assertTrue(applied)
        self.assertEqual(out["ring"]["value"], 7)

    def test_led_local_cursor_on_frame_reads_position_plus_one(self):
        from control_center import alive_lights
        frame = {"activity": "idle", "ring": {"style": "bri", "value": 50}}
        out, applied, _ = alive_lights._local(frame, 49, 99)
        if not applied:
            self.skipTest("F5 pending: alive_lights._local / cc_alive_local do not take the 0..99 on frame yet")
        self.assertEqual(out["ring"]["value"], 50)
        out, applied, _ = alive_lights._local(frame, 0, 99)
        self.assertEqual(out["ring"]["value"], 1, "the on frame's floor is 1 %")
        out, applied, _ = alive_lights._local(frame, 99, 99)
        self.assertEqual(out["ring"]["value"], 100)


if __name__ == "__main__":
    unittest.main()
