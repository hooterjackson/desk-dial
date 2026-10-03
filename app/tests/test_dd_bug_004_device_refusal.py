"""DD-BUG-004 (device side): a control _enter refuses is reported as non-retryable, never as a plain link error."""
from pathlib import Path
import queue
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.device import ControlRefused, DeviceBridge
from test_cc_device import Clock, FakeSerial, control


class DeviceRefusalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.serial = FakeSerial(self.clock)
        self.bridge = DeviceBridge(self.temp.name, lambda port: self.serial, request_timeout=0.1,
                                   autostart=False, clock=self.clock)
        self.bridge._connect("COM-FAKE")
        self.drain()

    def tearDown(self):
        self.temp.cleanup()

    def drain(self):
        output = []
        while True:
            try:
                output.append(self.bridge.events.get_nowait())
            except queue.Empty:
                return output

    def run_once(self, command, value):
        """One pass of the worker loop (_run) for one queued command."""
        bridge = self.bridge
        bridge.commands.put((command, value))
        service = bridge._service
        def service_then_stop():
            bridge._closing = True
            service()
        bridge._service = service_then_stop
        bridge._run()
        return [event for event in self.drain() if event["kind"] == "error"]

    def test_missing_profile_is_a_non_retryable_error_with_its_name(self):
        payload = control(); payload["profile"] = "NOT ON THIS KNOB"
        before = list(self.serial.writes)
        errors = self.run_once("enter", payload)
        self.assertEqual(len(errors), 1)
        error = errors[0]
        self.assertIs(error["retry"], False)
        self.assertEqual(error["profile"], "NOT ON THIS KNOB")
        self.assertEqual(error["error"], "ValueError")   # consumers keyed on the name keep working
        self.assertTrue(error["message"].startswith("Choose an inventoried existing profile"))
        self.assertIsNotNone(self.bridge.serial)          # the bridge does not drop the link itself
        self.assertFalse(self.serial.closed)
        self.assertEqual(self.serial.writes, before)      # nothing sent, nothing created

    def test_malformed_control_is_non_retryable_without_a_profile(self):
        payload = control(); payload["buttonOrder"] = [0, 0, 1, 2]
        error, = self.run_once("enter", payload)
        self.assertIs(error["retry"], False)
        self.assertNotIn("profile", error)

    def test_stale_control_id_stays_retryable(self):
        self.assertEqual(self.run_once("enter", control(5)), [])
        self.bridge._closing = False
        error, = self.run_once("enter", control(5))
        self.assertTrue(error["message"].startswith("Control IDs must increase"))
        self.assertNotIn("retry", error)
        self.assertEqual(error["error"], "ValueError")

    def test_refusal_is_still_a_value_error(self):
        payload = control(); payload["profile"] = "TYPO"
        with self.assertRaises(ValueError) as caught:
            self.bridge._enter(payload)
        self.assertIsInstance(caught.exception, ControlRefused)
        self.assertEqual(caught.exception.details, {"profile": "TYPO"})


if __name__ == "__main__":
    unittest.main()
