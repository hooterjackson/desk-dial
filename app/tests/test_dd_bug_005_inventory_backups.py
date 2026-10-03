"""DD-BUG-005: the inventory backup written at every connect is bounded.

An unchanged inventory reuses (and touches) the newest matching backup instead of adding a file, so a
replug, or a stock-firmware knob reconnected over and over, no longer grows the backups folder; a changed
inventory (firmware, settings, profiles, capabilities) still gets its own new file, and nothing is deleted.
In-memory serial only (test_cc_device.FakeSerial): no port, window or network.
"""
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from control_center.device import DeviceBridge  # noqa: E402
from test_cc_device import Clock, FakeSerial  # noqa: E402


class InventoryBackupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.clock = Clock()
        self.serial = FakeSerial(self.clock)
        self.bridge = DeviceBridge(temp.name, lambda port: self.serial, request_timeout=0.1, autostart=False,
                                   clock=self.clock)

    def files(self):
        return sorted(self.dir.glob("control-center-inventory-*.json"))

    def connect(self, port="COM-FAKE"):
        self.serial.buffer.clear()
        self.bridge._connect(port)
        path = self.bridge.backup_path
        self.bridge._disconnect()
        return path

    def test_fifty_unchanged_connects_keep_one_backup(self):
        first = self.connect()
        for n in range(49):
            self.assertEqual(self.connect(port=f"COM{n % 3}"), first)   # the port alone is no new inventory
        self.assertEqual(len(self.files()), 1)
        self.assertTrue(first.is_file())

    def test_stock_firmware_knob_reconnect_loop_adds_no_files(self):
        self.serial.capabilities = False           # stock firmware: no capabilities reply, no controlCenter
        for _ in range(30):
            self.connect()
        self.assertEqual(len(self.files()), 1)
        self.assertEqual(json.loads(self.files()[0].read_text(encoding="utf-8"))["capabilities"], {})

    def test_a_changed_inventory_gets_its_own_file_and_nothing_is_deleted(self):
        first = self.connect()
        self.serial.profiles["MIDI CLACK JONES"] = {**self.serial.profiles["MIDI CLACK JONES"], "desc": "edited"}
        second = self.connect()
        self.assertNotEqual(first, second)
        self.assertEqual(json.loads(second.read_text(encoding="utf-8"))["profiles"]["MIDI CLACK JONES"]["desc"],
                         "edited")
        self.assertEqual(len(self.files()), 2)
        self.assertTrue(first.is_file())
        self.assertEqual(self.connect(), second)   # unchanged again: reused

    def test_reused_backup_is_touched_newest(self):
        first = self.connect()
        os.utime(first, (1_000_000, 1_000_000))
        self.assertEqual(self.connect(), first)
        self.assertGreater(first.stat().st_mtime, 1_000_000)

    def test_unreadable_or_foreign_files_are_ignored(self):
        (self.dir / "control-center-inventory-garbage.json").write_text("{not json", encoding="utf-8")
        path = self.connect()
        self.assertNotEqual(path.name, "control-center-inventory-garbage.json")
        self.assertEqual(self.connect(), path)
        self.assertEqual(len(self.files()), 2)


if __name__ == "__main__":
    unittest.main()
