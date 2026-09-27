"""Real lifecycle logic with a fake firmware transport; no hardware is opened."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from session import DeviceSession, SerialWorker, demo_verified, mapping_updates


ORIGINAL = {
    "name": "My Profile", "description": "Existing configuration",
    "keys": [{"pressed": [{"type": "key", "keyCodes": [4]}]}, {}, {}, {}],
    "knob": [{"type": "midi", "channel": 1, "cc": 7, "valueMin": 0,
              "valueMax": 127, "step": 1, "haptic": {"mode": 1, "detentCount": 127}}],
    "led": {"brightness": 42},
}


class FakeSerial:
    def __init__(self):
        self.profile = deepcopy(ORIGINAL)
        self.commands = []
        self.pending = bytearray()
        self.closed = False
        self.reject_demo = False
        self.reject_restore = False
        self.partial_demo_write = False
        self.silent = False

    def reply(self, value):
        self.pending.extend((json.dumps(value) + "\n").encode())

    def write(self, data):
        message = json.loads(data)
        self.commands.append(message)
        if self.silent:
            return len(data)
        if message == {"settings": "?"}:
            self.reply({"settings": {"deviceName": "Test Knob", "firmwareVersion": "2.0", "serialNumber": "TEST-123", "wifiPassword": "do-not-log"}})
        elif message == {"profiles": "#all"}:
            self.reply({"profiles": [ORIGINAL["name"]], "current": ORIGINAL["name"]})
        elif "updates" in message:
            update = message["updates"]
            is_demo = update["knob"][0]["type"] == "actions"
            if not ((is_demo and self.reject_demo) or (not is_demo and self.reject_restore)):
                self.profile.update(deepcopy(update))
                # Match firmware serialization: empty key-action lists are omitted.
                self.profile["keys"] = [{k: v for k, v in key.items() if v} for key in self.profile["keys"]]
                if is_demo:
                    for knob in self.profile["knob"]:
                        knob.pop("channel", None)
                        knob.pop("cc", None)
            if is_demo and self.partial_demo_write:
                return len(data) - 1
        elif message == {"profile": ORIGINAL["name"]}:
            self.reply({"profile": deepcopy(self.profile)})
        else:
            raise AssertionError(f"Unexpected command: {message}")
        return len(data)

    def read(self, count):
        if not self.pending:
            time.sleep(0.001)
        result = bytes(self.pending[:count])
        del self.pending[:count]
        return result

    def close(self):
        self.closed = True


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.events = []
        self.serial = FakeSerial()
        self.session = DeviceSession(self.events.append, self.temp.name,
                                     serial_factory=lambda port: self.serial, request_timeout=0.04)

    def connect(self):
        self.session.connect("COM_TEST")

    def test_connect_only_reads_and_redacts_settings(self):
        self.connect()
        self.assertFalse(self.session.armed)
        self.assertEqual(self.serial.commands, [{"settings": "?"}, {"profiles": "#all"}, {"profile": ORIGINAL["name"]}])
        self.assertNotIn("do-not-log", json.dumps(self.events))
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_arm_backups_then_verifies_and_restores(self):
        self.connect()
        self.session.arm()
        self.assertTrue(self.session.armed)
        self.assertTrue(self.session.needs_restore)
        self.assertTrue(demo_verified(self.serial.profile, ORIGINAL))
        backup = json.loads(self.session.backup_path.read_text(encoding="utf-8"))
        self.assertEqual(backup["profile"], ORIGINAL)
        self.assertNotIn("do-not-log", json.dumps(backup))
        self.session.restore()
        self.assertFalse(self.session.armed)
        self.assertFalse(self.session.needs_restore)
        self.assertEqual(mapping_updates(self.serial.profile), mapping_updates(ORIGINAL))
        self.assertEqual(self.serial.profile["led"], ORIGINAL["led"])
        mutations = [m for m in self.serial.commands if "updates" in m]
        self.assertEqual(len(mutations), 2)
        self.assertTrue(all(set(m["updates"]) == {"keys", "knob"} for m in mutations))
        self.assertTrue(all("save" not in m and "load" not in m and "recalibrate" not in m for m in self.serial.commands))

    def test_failed_demo_readback_never_arms_and_disconnect_restores(self):
        self.connect()
        self.serial.reject_demo = True
        with self.assertRaisesRegex(RuntimeError, "did not confirm"):
            self.session.arm()
        self.assertFalse(self.session.armed)
        self.assertFalse(any(e["kind"] == "armed" for e in self.events))
        self.session.disconnect()
        self.assertTrue(self.serial.closed)
        self.assertFalse(self.session.needs_restore)
        self.assertEqual(mapping_updates(self.serial.profile), mapping_updates(ORIGINAL))

    def test_partial_write_retains_restore_obligation(self):
        self.connect()
        self.serial.partial_demo_write = True
        with self.assertRaisesRegex(OSError, "incomplete"):
            self.session.arm()
        self.assertTrue(self.session.needs_restore)
        self.assertTrue(self.session.backup_path.exists())
        self.session.disconnect()
        self.assertFalse(self.session.needs_restore)
        self.assertEqual(mapping_updates(self.serial.profile), mapping_updates(ORIGINAL))

    def test_restore_failure_keeps_backup_and_closes_transport(self):
        self.connect()
        self.session.arm()
        self.serial.reject_restore = True
        with self.assertRaisesRegex(RuntimeError, "Could not verify"):
            self.session.disconnect()
        self.assertFalse(self.session.armed)
        self.assertTrue(self.session.needs_restore)
        self.assertTrue(self.session.backup_path.exists())
        self.assertTrue(self.serial.closed)
        self.assertIsNone(self.session.serial)

    def test_input_baseline_and_arm_status_are_recorded(self):
        self.connect()
        self.serial.reply({"p": 20})
        self.serial.reply({"p": 21})
        self.session.poll()
        inputs = [e for e in self.events if e["kind"] == "input"]
        self.assertEqual([(e["action"], e["value"], e["armed"]) for e in inputs], [("turn", 1, False)])
        self.session.arm()
        self.serial.reply({"p": 90})
        self.serial.reply({"p": 91})
        self.session.poll()
        inputs = [e for e in self.events if e["kind"] == "input"]
        self.assertEqual(inputs[-1]["value"], 1)
        self.assertTrue(inputs[-1]["armed"])

    def test_timeout_is_bounded_without_mapping_mutation(self):
        self.serial.silent = True
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            self.connect()
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(self.serial.commands, [{"settings": "?"}])
        self.assertFalse(self.session.armed)

    def test_named_profile_actions_are_restorable_despite_firmware_spelling(self):
        original = deepcopy(ORIGINAL)
        original["keys"][0]["pressed"] = [{"type": "profiles", "name": "Other Profile"}]
        original["knob"][0] = {"type": "actions", "haptic": {"mode": 1}, "cw": {"type": "profiles", "name": "Other Profile"}}
        normalized = mapping_updates(original)
        self.assertEqual(normalized["keys"][0]["pressed"][0]["type"], "profile")
        self.assertEqual(normalized["knob"][0]["cw"]["type"], "profile")
        self.assertEqual(original["keys"][0]["pressed"][0]["type"], "profiles")

    def test_pending_restore_reconnect_is_bound_to_original_device(self):
        self.connect()
        self.session.arm()
        self.serial.reject_restore = True
        with self.assertRaises(RuntimeError):
            self.session.disconnect()
        self.serial.reject_restore = False
        with self.assertRaisesRegex(RuntimeError, "original device"):
            self.session.connect("COM_OTHER")
        # A failed identity check must not write any profile update on that port.
        self.assertEqual(self.serial.commands[-2:], [{"settings": "?"}, {"profiles": "#all"}])
        commands_before_close = len(self.serial.commands)
        with self.assertRaisesRegex(RuntimeError, "different device or port"):
            self.session.disconnect()
        self.assertEqual(len(self.serial.commands), commands_before_close)
        self.assertTrue(self.serial.closed)

    def test_worker_closes_and_restores_without_gui_thread(self):
        worker = SerialWorker(self.temp.name, serial_factory=lambda port: self.serial)
        worker.submit("connect", "COM_TEST")
        worker.submit("arm")
        worker.submit("close")
        worker.thread.join(timeout=3)
        self.assertFalse(worker.thread.is_alive())
        self.assertTrue(self.serial.closed)
        self.assertEqual(mapping_updates(self.serial.profile), mapping_updates(ORIGINAL))
        events = []
        while not worker.events.empty():
            events.append(worker.events.get_nowait())
        self.assertEqual(events[-1]["kind"], "closed")
        self.assertFalse(any(e["kind"] == "error" for e in events))


if __name__ == "__main__":
    unittest.main()
