"""DD-BUG-039 (runtime side): the runtime exposes hotkey_busy, True when a supported knob connects while
another app owns F24, False on a clean (re)connect and on a lost knob, so the Settings strip need not match
"F24" in device_status. Real Runtime and Controller; no Tk, no port, no network, no thread pool."""
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


class BusyWindows(HotkeyWindows):
    """F24 already registered by another app: enabling the hotkey raises, as the live adapter does."""

    def __init__(self):
        super().__init__()
        self.busy = True

    def set_hotkey_enabled(self, enabled):
        if enabled and self.busy:
            raise OSError("hotkey already registered")
        return super().set_hotkey_enabled(enabled)


class HotkeyBusyFlagTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(runtime_module, "ThreadPoolExecutor", InlineExecutor)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.windows = BusyWindows()
        self.device = FakeDevice()
        self.runtime = Runtime(Controller(), SimulatedSonos(), SimulatedAppleMusic(), self.windows, self.device)
        self.addCleanup(self.runtime.shutdown)

    def emit(self, kind, **values):
        self.device.events.put({"kind": kind, **values})
        self.runtime._device_events()

    def connect(self):
        self.emit("connected", profiles={}, capabilities={"controlCenter": 1})

    def test_starts_clear(self):
        self.assertFalse(self.runtime.hotkey_busy)

    def test_busy_f24_sets_the_flag(self):
        self.connect()
        self.assertTrue(self.runtime.hotkey_busy)
        self.assertFalse(self.runtime.device_supported)
        self.assertIn("F24", self.runtime.device_status)

    def test_a_clean_reconnect_clears_the_flag(self):
        self.connect()
        self.windows.busy = False
        self.connect()
        self.assertFalse(self.runtime.hotkey_busy)
        self.assertTrue(self.runtime.device_supported)

    def test_a_lost_knob_clears_the_flag(self):
        self.connect()
        self.emit("disconnected", message="Knob disconnected")
        self.assertFalse(self.runtime.hotkey_busy)

    def test_stock_firmware_is_not_hotkey_busy(self):
        self.emit("connected", profiles={}, capabilities={})
        self.assertFalse(self.runtime.hotkey_busy)
        self.assertTrue(self.runtime.device_status.startswith("Stock firmware"))


if __name__ == "__main__":
    unittest.main()
