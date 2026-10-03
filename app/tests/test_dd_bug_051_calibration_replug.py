"""DD-BUG-051 (runtime side): a recalibration result belongs to one connection. The real Runtime's
device event handler clears ``calibration_result`` on connected, disconnected / closed, released and
error, so status.json knobFeel.lastCalibration never carries a refusal across a replug.
No Tk, no port, no network (an inline executor and a queue-backed device stand-in)."""
from pathlib import Path
from queue import Queue
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from control_center import runtime as runtime_module
from control_center.controller import Controller
from control_center.runtime import Runtime
from control_center.simulation import SimulatedAppleMusic, SimulatedSonos
from test_cc_touch import HotkeyWindows, InlineExecutor


class Device:
    def __init__(self):
        self.events = Queue()
        self.serial = None
        self.media_capability = None

    def submit(self, command, value=None):
        pass


class CalibrationReplugTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(runtime_module, "ThreadPoolExecutor", InlineExecutor)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.device = Device()
        controller = Controller()
        controller.state_known = True
        self.rt = Runtime(controller, SimulatedSonos(), SimulatedAppleMusic(), HotkeyWindows(), self.device)
        self.addCleanup(self.rt.shutdown)

    def feed(self, kind, **values):
        self.device.events.put({"kind": kind, **values})
        self.rt._device_events()

    def refuse(self):
        self.feed("calibrated", ok=False, reason="direction-changed")
        self.assertEqual(self.rt.calibration_result, (False, "direction-changed"))

    def test_each_lifecycle_event_clears_the_result(self):
        for kind in ("connected", "disconnected", "closed", "released", "error"):
            with self.subTest(kind=kind):
                self.feed("connected", capabilities={"controlCenter": 1})
                self.refuse()
                self.feed(kind, **({"capabilities": {"controlCenter": 1}} if kind == "connected" else
                                   {"message": "x"}))
                self.assertIsNone(self.rt.calibration_result)

    def test_status_reports_no_stale_last_calibration_after_replug(self):
        self.feed("connected", capabilities={"controlCenter": 1})
        self.refuse()
        self.feed("disconnected", message="Knob disconnected")
        self.feed("connected", capabilities={"controlCenter": 1})
        self.assertIsNone(self.rt.calibration_result)

    def test_a_result_inside_one_connection_is_kept(self):
        self.feed("connected", capabilities={"controlCenter": 1})
        self.refuse()
        self.feed("diag")
        self.assertEqual(self.rt.calibration_result, (False, "direction-changed"))


if __name__ == "__main__":
    unittest.main()
