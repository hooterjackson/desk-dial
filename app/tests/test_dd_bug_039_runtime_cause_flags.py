"""DD-BUG-039 (runtime follow-up): the runtime exposes device_stock_firmware and hotkey_busy as explicit
flags, so the Settings strip need not parse device_status. Both are set only for their own cause and are
cleared by a disconnect, a device error and a host-control release. Real Runtime and Controller; no Tk,
no port, no network, no thread pool."""
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
from test_dd_bug_039_hotkey_busy_flag import BusyWindows
from test_cc_touch import FakeDevice, InlineExecutor


class RuntimeCauseFlagTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(runtime_module, "ThreadPoolExecutor", InlineExecutor)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.windows = BusyWindows()
        self.windows.busy = False
        self.device = FakeDevice()
        self.runtime = Runtime(Controller(), SimulatedSonos(), SimulatedAppleMusic(), self.windows, self.device)
        self.addCleanup(self.runtime.shutdown)

    def emit(self, kind, **values):
        self.device.events.put({"kind": kind, **values})
        self.runtime._device_events()

    def stock(self):
        self.emit("connected", profiles={}, capabilities={})

    def busy(self):
        self.windows.busy = True
        self.emit("connected", profiles={}, capabilities={"controlCenter": 1})

    def flags(self):
        return self.runtime.device_stock_firmware, self.runtime.hotkey_busy

    def test_starts_clear(self):
        self.assertEqual(self.flags(), (False, False))

    def test_stock_firmware_sets_only_its_flag(self):
        self.stock()
        self.assertEqual(self.flags(), (True, False))

    def test_hotkey_busy_is_not_stock_firmware(self):
        self.busy()
        self.assertEqual(self.flags(), (False, True))

    def test_a_supported_knob_has_neither(self):
        self.emit("connected", profiles={}, capabilities={"controlCenter": 1})
        self.assertTrue(self.runtime.device_supported)
        self.assertEqual(self.flags(), (False, False))

    def test_reconnecting_with_supported_firmware_clears_stock(self):
        self.stock()
        self.emit("connected", profiles={}, capabilities={"controlCenter": 1})
        self.assertEqual(self.flags(), (False, False))

    def test_disconnect_clears_both(self):
        for setup in (self.stock, self.busy):
            with self.subTest(setup=setup.__name__):
                setup()
                self.emit("disconnected", message="Knob disconnected")
                self.assertEqual(self.flags(), (False, False))

    def test_error_clears_both(self):
        for setup in (self.stock, self.busy):
            with self.subTest(setup=setup.__name__):
                setup()
                self.emit("error", message="Device error")
                self.assertEqual(self.flags(), (False, False))

    def test_release_clears_both(self):
        for setup in (self.stock, self.busy):
            with self.subTest(setup=setup.__name__):
                setup()
                self.emit("released")
                self.assertEqual(self.flags(), (False, False))


if __name__ == "__main__":
    unittest.main()
