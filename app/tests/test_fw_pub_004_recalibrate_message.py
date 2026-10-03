"""FW-PUB-004: the message Settings shows when recalibration is not available names the public version of the
Desk Dial + knob pair (2.0.0, the first public release with recalibration), never an internal build id such as
cc5.7. Headless: Runtime.recalibrate_motor on an instance built without __init__; no Tk, no ports."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import runtime  # noqa: E402

SOURCE = (Path(__file__).resolve().parents[1] / "control_center" / "runtime.py").read_text(encoding="utf-8")
INTERNAL_ID = re.compile(r"cc\d+\.\d+")


def bare_runtime(connected):
    rt = runtime.Runtime.__new__(runtime.Runtime)
    rt.calibrating = False
    rt.device_connected = connected
    rt.device_supported = connected
    rt.device = None
    return rt


class RecalibrateMessageTests(unittest.TestCase):
    def test_unavailable_message_names_public_version(self):
        message = bare_runtime(False).recalibrate_motor()
        self.assertIsInstance(message, str)
        self.assertIn("firmware 2.0.0 or later", message)
        self.assertIsNone(INTERNAL_ID.search(message), message)

    def test_no_user_facing_recalibration_text_carries_an_internal_id(self):
        for line in SOURCE.splitlines():
            if "Recalibration needs" in line:
                self.assertIsNone(INTERNAL_ID.search(line), line)


if __name__ == "__main__":
    unittest.main()
