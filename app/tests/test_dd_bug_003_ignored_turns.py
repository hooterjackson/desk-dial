"""DD-BUG-003: turns the controller ignores on a value control re-anchor the knob.

Before the fix the knob's absolute position drifted while Sonos was offline (or an Onshape switch was
pending, or Lights was blocked/offline); the first detent afterwards wrote the drifted value."""
import unittest

from cc5_support import Fixture, queue_state
from r3_support import R3Fixture


class IgnoredVolumeTurnTests(Fixture):
    def enters(self):
        return [e["control"] for e in self.c.drain() if e["kind"] == "device_enter"]

    def test_turns_ignored_while_offline_reanchor_the_knob(self):
        self.assertEqual(self.c.screen.mode, "home")
        self.publish(queue_state(volume=20, online=False))
        self.c.drain()
        for position in range(21, 51):                 # +30 detents while Sonos is offline
            self.turn_to(position)
        self.assertIsNone(self.c.desired_volume)
        self.publish(queue_state(volume=20))            # Sonos returns at 20
        self.tick(0.5)                                  # the knob rests: passive re-entry
        enters = self.enters()
        self.assertTrue(enters, "the knob is re-anchored")
        self.assertEqual(enters[-1]["position"], 20)
        self.c.position(21, self.c.control_id)          # the next detent from the anchor
        self.tick(0.2)
        writes = [e for e in self.c.drain() if e["kind"] == "volume"]
        self.assertEqual([e["value"] for e in writes], [21])

    def test_turns_ignored_while_onshape_switch_is_pending_reanchor(self):
        self.c.onshape_pending = True
        self.c.position(40, self.c.control_id)
        self.tick(0.5)
        enters = self.enters()
        self.assertTrue(enters)
        self.assertEqual(enters[-1]["position"], 28)


class IgnoredLightsTurnTests(R3Fixture):
    def test_turns_ignored_while_lights_offline_reanchor_the_knob(self):
        self.press(2)
        self.serve()
        level = self.c.control()["position"]
        self.controls.ha = "offline"
        self.c.lights_state(self.ha.read_state())
        self.serve()
        self.c.position(level + 15, self.c.control_id)
        self.assertEqual(self.c.lights_intent(), {})
        self.tick(0.5)
        rest = self.serve()
        enters = [e["control"] for e in rest if e["kind"] == "device_enter"]
        self.assertTrue(enters, "the knob is re-anchored")
        self.assertEqual(enters[-1]["position"], level)

if __name__ == "__main__":
    unittest.main()
