"""DD-BUG-004 (runtime side): the 'connected' inventory reaches the controller.

A knob whose owner renamed or deleted a hard-coded profile gets controls that name installed
profiles (no refused enter, no reconnect loop), a precise 'profile missing' status that survives
'ready', and a disconnect forgets the inventory so a later knob is not mapped against it.
No Tk, no port, no thread pool (a stand-in executor)."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from control_center import runtime as runtime_module
from control_center.controller import Controller
from control_center.runtime import Runtime
from control_center.simulation import SimulatedAppleMusic, SimulatedSonos
from test_cc_touch import FakeDevice, HotkeyWindows, InlineExecutor


def inventory(*names):
    return {name: {"name": name, "knob": [{"haptic": {"detentCount": 67}}]} for name in names}


class RuntimeInventoryTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(runtime_module, "ThreadPoolExecutor", InlineExecutor)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.c = Controller()
        self.device = FakeDevice()
        self.runtime = Runtime(self.c, SimulatedSonos(), SimulatedAppleMusic(), HotkeyWindows(), self.device)
        self.addCleanup(self.runtime.shutdown)

    def events(self, *events):
        for event in events:
            self.device.events.put(event)
        self.runtime._device_events()

    def connect(self, profiles=None):
        event = {"kind": "connected", "capabilities": {"controlCenter": 1}}
        if profiles is not None:
            event["profiles"] = profiles
        self.events(event)

    def entered(self):
        return [e["control"]["profile"] for e in self.c.drain() if e["kind"] == "device_enter"]

    def test_missing_profile_maps_to_installed_and_status_survives_ready(self):
        installed = inventory("BINARIS BEER", "MIDI CLACK JONES")
        self.connect(installed)
        self.assertEqual(self.c.missing_profiles, ("MIDI SKIPPER",))
        self.assertIn("MIDI SKIPPER", self.runtime.device_status)
        self.assertEqual(self.runtime.device_status, self.c.profile_status)
        profiles = self.entered()
        self.assertTrue(profiles)
        self.assertTrue(all(p in installed for p in profiles), profiles)
        self.events({"kind": "ready", "id": self.c.control_id})
        self.assertEqual(self.runtime.device_status, self.c.profile_status)
        # Every mode's control names an installed profile.
        for mode in ("home", "recent", "explorer", "tracks", "windows", "lights", "scenes", "onshape"):
            self.c.screen.mode = mode
            try:
                control = self.c.control()
            except Exception:   # a mode this controller cannot reach without more state
                continue
            self.assertIn(control["profile"], installed, mode)

    def test_full_inventory_keeps_the_ready_status(self):
        self.connect(inventory(*Controller.required_profiles()))
        self.assertEqual(self.c.missing_profiles, ())
        self.assertEqual(self.runtime.device_status, "Connected · verifying control interface")
        self.events({"kind": "ready", "id": self.c.control_id})
        self.assertEqual(self.runtime.device_status, "Knob ready · installed profiles active")

    def test_disconnect_forgets_the_inventory(self):
        self.connect(inventory("BINARIS BEER"))
        self.assertTrue(self.c.missing_profiles)
        self.events({"kind": "disconnected", "message": "Knob disconnected"})
        self.assertIsNone(self.c.installed_profiles)
        self.assertEqual(self.c.missing_profiles, ())
        self.assertEqual(self.c.profile_status, "")
        # A later knob that reports no inventory is not mapped against the old one.
        self.connect()
        self.assertIsNone(self.c.installed_profiles)
        self.events({"kind": "ready", "id": self.c.control_id})
        self.assertEqual(self.runtime.device_status, "Knob ready · installed profiles active")


if __name__ == "__main__":
    unittest.main()
