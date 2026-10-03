"""DD-BUG-004: a knob whose inventory lacks a hard-coded profile never gets a control it refuses.

Before the fix every control asked for PROFILES[mode] whatever the knob had installed; device._enter
raised "Choose an inventoried existing profile" and the standalone loop reconnected forever.

Scope: these tests prove the CONTROLLER side only (every device_enter names an installed profile once
set_installed_profiles has the inventory). The loop stops end to end only when runtime.py hands the
'connected' inventory to Controller.set_installed_profiles and the standalone/device side treats an
_enter ValueError as non-retryable; those parts belong to other lanes."""
import unittest

from cc5_support import Fixture
from control_center.controller import LIGHTS_TEMP_PROFILE, PROFILES, Controller


def inventory(*names):
    return {name: {"name": name, "knob": [{"haptic": {"detentCount": 67}}]} for name in names}


class MissingProfileTests(Fixture):
    def entered_profiles(self):
        return [e["control"]["profile"] for e in self.c.drain() if e["kind"] == "device_enter"]

    def test_missing_required_profile_maps_every_control_to_an_installed_profile(self):
        installed = inventory("BINARIS BEER", "MIDI CLACK JONES", "OTHER")
        missing = self.c.set_installed_profiles(installed)
        self.assertEqual(missing, ("MIDI SKIPPER",))
        self.assertIn("MIDI SKIPPER", self.c.profile_status)
        self.c.set_hardware(True)
        self.c.device_ready(self.c.control_id)
        # Walk the modes whose profile is MIDI SKIPPER (Recently Added, explorer) and back, then 5 minutes.
        self.browse()
        self.press(1)
        for _ in range(300):
            self.tick(1.0)
        self.c.set_hardware(True)
        profiles = self.entered_profiles()
        self.assertTrue(profiles)
        # The device's rule (device._enter): the profile must be in the inventory. No refusal = no
        # 'error' event = no reconnect.
        self.assertTrue(all(p in installed for p in profiles), profiles)
        for mode in PROFILES:
            self.assertIn(self.c._installed_profile(PROFILES[mode]), installed)
        self.assertEqual(self.c._installed_profile(LIGHTS_TEMP_PROFILE), "MIDI CLACK JONES")

    def test_every_mode_maps_into_an_inventory_without_any_known_name(self):
        installed = inventory("CUSTOM A", "CUSTOM B")
        self.c.set_installed_profiles(installed)
        for name in Controller.required_profiles():
            self.assertEqual(self.c._installed_profile(name), "CUSTOM A")
        self.assertIn("using CUSTOM A", self.c.profile_status)

    def test_a_complete_inventory_keeps_the_profiles_and_no_status(self):
        self.assertEqual(self.c.set_installed_profiles(inventory(*Controller.required_profiles())), ())
        self.assertEqual(self.c.profile_status, "")
        self.c.set_hardware(True)
        self.assertEqual(self.entered_profiles(), [PROFILES[self.c.screen.mode]])

    def test_unknown_inventory_changes_nothing(self):
        self.c.set_installed_profiles(None)
        self.assertEqual(self.c._installed_profile("MIDI SKIPPER"), "MIDI SKIPPER")
        self.assertEqual(self.c.profile_status, "")


if __name__ == "__main__":
    unittest.main()
