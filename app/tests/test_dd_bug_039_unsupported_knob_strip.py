"""DD-BUG-039: a knob on USB that Desk Dial can't drive (stock firmware, or F24 owned by another app)
is not reported as "Not connected · Waiting for the knob on USB"; the strip names the runtime's cause,
and Troubleshoot no longer focuses the Knob USB port field. Headless: no Tk window, port or network."""
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import ui  # noqa: E402

STOCK = "Stock firmware · display/control extension required"
F24 = "F24 is unavailable · close the conflicting hotkey app"


def runtime(connected=True, supported=False, status=STOCK):
    apple = SimpleNamespace(has_credentials=lambda: True)
    return SimpleNamespace(device_connected=connected, device_supported=supported, device_status=status,
                           controller=SimpleNamespace(state={"online": False}), music_signin_expired=False,
                           apple=apple)


class UnsupportedKnobStripTests(unittest.TestCase):
    def knob(self, rt):
        return ui.strip_model(rt)[0]

    def test_connected_unsupported_knob_is_not_reported_as_waiting_for_usb(self):
        knob = self.knob(runtime())
        self.assertFalse(knob["ok"])
        self.assertEqual(knob["state"], "Firmware needed")
        self.assertEqual(knob["detail"], STOCK)
        self.assertNotIn("Waiting for the knob", knob["detail"])
        self.assertEqual(knob["key"], "troubleshoot")

    def test_f24_busy_is_its_own_state(self):
        knob = self.knob(runtime(status=F24))
        self.assertEqual((knob["ok"], knob["state"], knob["detail"]), (False, "Hotkey busy", F24))

    def test_empty_status_still_names_a_cause(self):
        knob = self.knob(runtime(status=""))
        self.assertEqual(knob["state"], "Needs attention")
        self.assertTrue(knob["detail"])
        self.assertNotIn("Waiting for the knob", knob["detail"])

    def test_unplugged_and_supported_are_unchanged(self):
        self.assertEqual(self.knob(runtime(connected=False))["state"], "Not connected")
        self.assertEqual(self.knob(runtime(supported=True))["state"], "Connected")

    def test_troubleshoot_does_not_focus_the_usb_port_field(self):
        source = Path(ui.__file__).read_text(encoding="utf-8")
        body = re.search(r"def troubleshoot\(\):\n(.*?)\n        # K3 14\.1", source, re.S)
        self.assertIsNotNone(body)
        self.assertNotIn("Knob USB port", body.group(1))
        self.assertIn("show_detail(self.runtime.device_status)", body.group(1))


if __name__ == "__main__":
    unittest.main()
