"""DD-BUG-039 review: a supported knob whose host control was released, or whose last command raised a
device error, is still on USB with device_supported=False. The strip must not tell its owner to reflash
("Firmware needed"); only a stock-firmware status does. Headless: no Tk window, port or network."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import ui  # noqa: E402

RELEASED = "Host control released · disconnect and reconnect"
ERROR = "Knob rejected the frame (timeout)"


def knob(status, connected=True, supported=False):
    rt = SimpleNamespace(device_connected=connected, device_supported=supported, device_status=status,
                         controller=SimpleNamespace(state={"online": False}), music_signin_expired=False,
                         apple=SimpleNamespace(has_credentials=lambda: True))
    return ui.strip_model(rt)[0]


class ReleasedOrErrorIsNotFirmwareNeeded(unittest.TestCase):
    def test_released_host_control_is_neutral(self):
        k = knob(RELEASED)
        self.assertEqual((k["ok"], k["state"], k["detail"]), (False, "Needs attention", RELEASED))
        self.assertEqual(k["key"], "troubleshoot")

    def test_arbitrary_device_error_is_neutral(self):
        k = knob(ERROR)
        self.assertEqual((k["state"], k["detail"]), ("Needs attention", ERROR))

    def test_neither_reads_firmware_needed(self):
        for status in (RELEASED, ERROR, "Device error", "Knob disconnected", ""):
            with self.subTest(status=status):
                self.assertNotEqual(knob(status)["state"], "Firmware needed")

    def test_stock_firmware_and_f24_keep_their_states(self):
        self.assertEqual(knob("Stock firmware · display/control extension required")["state"], "Firmware needed")
        self.assertEqual(knob("F24 is unavailable · close the conflicting hotkey app")["state"], "Hotkey busy")

    def test_unplugged_and_connected_unchanged(self):
        self.assertEqual(knob(RELEASED, connected=False)["state"], "Not connected")
        self.assertEqual(knob("Knob ready", supported=True)["state"], "Connected")


if __name__ == "__main__":
    unittest.main()
