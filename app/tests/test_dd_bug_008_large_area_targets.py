"""DD-BUG-008: a turn in a Lights area with more than 32 lights targets every light that is on.

Before the fix the adapter's per-light rows were cut to 32 (sorted by name), so lights 33.. kept their
level on every turn and the area then looked mixed / drew a settle write."""
import unittest

from r3_support import R3Fixture  # noqa: I001  (sets the import path first)

from control_center import controller

LIGHTS_MEMBERS_DRAWN = getattr(controller, "LIGHTS_MEMBERS_DRAWN", 32)


def big_area(state, n=40, on=True):
    rows = [{"entity_id": f"light.test_{i:02d}", "name": f"Light {i:02d}", "on": on, "bri": 62, "kelvin": 3200,
             "available": True} for i in range(n)]
    return {**state, "lights": rows, "count": n, "on_count": n if on else 0}


class LargeAreaTests(R3Fixture):
    def setUp(self):
        super().setUp()
        self.press(2)
        self.serve()
        self.c.lights_state(big_area(self.ha.read_state()))
        self.c.drain()

    def test_a_turn_targets_every_on_light_in_a_large_area(self):
        self.turn_to(self.c.control()["position"] + 1)
        self.tick()
        sets = [e for e in self.c.drain() if e["kind"] == "lights_set"]
        self.assertEqual(len(sets), 1)
        self.assertEqual(len(sets[0]["targets"]), 40)
        self.assertIn("light.test_39", sets[0]["targets"])

    def test_the_area_counts_every_light_and_draws_at_most_the_cap(self):
        area = self.c.lights_area()
        self.assertEqual((area["ok"], area["on"]), (40, 40))
        self.assertFalse(area["mixed"])
        self.assertEqual(len(area["members"]), LIGHTS_MEMBERS_DRAWN)

    def test_lights_beyond_the_cap_being_off_make_the_area_mixed(self):
        state = big_area(self.ha.read_state())
        for row in state["lights"][35:]:
            row["on"] = False
        self.c.tick()
        self.clock.advance(10)
        self.c.lights_state(state)
        self.assertTrue(self.c.lights_area()["mixed"])
        self.assertEqual(len(self.c._lights_targets()), 35)


if __name__ == "__main__":
    unittest.main()
