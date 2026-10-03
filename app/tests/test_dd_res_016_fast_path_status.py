"""DD-RES-016 (standalone side): status.json carries the knob fast path's counters under
``fastPath`` (``{'posted', 'failures'}`` from ``FastPath.status()``), beside ``overlay`` so they are
there even without a floating knob. Headless: stand-ins and a real FastPath; no Tk, no ports."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import standalone  # noqa: E402
from control_center import ui  # noqa: E402
from control_center.controller import Controller  # noqa: E402


class BrokenOverlay:
    def post_input(self, *args):
        raise RuntimeError("post_input regression")


def runtime():
    return SimpleNamespace(device_connected=False, device_status="Knob disconnected", led_style="color",
                           artwork_enabled=True, artwork_status=None,
                           apple=SimpleNamespace(credentials={}))


class FastPathStatusTests(unittest.TestCase):
    def test_status_json_reports_a_real_fast_path_failure(self):
        fast = ui.FastPath(overlay=BrokenOverlay(), clock=lambda: 0.0)
        with self.assertLogs(ui._log, level="WARNING"):
            fast.handle("position", {"id": "volume", "position": 3, "delta": 1}, t=1.0)
        self.assertEqual(fast.failures, 1)
        app = SimpleNamespace(runtime=runtime(), controller=Controller(), live=True, fast_path=fast)
        status = standalone.status_payload(app, standalone.RetryPolicy(), {})
        self.assertEqual(status["fastPath"], {"posted": fast.posted, "failures": fast.failures})
        self.assertIsNone(status["overlay"])          # no floating knob: the counters are still there
        json.dumps(status)

    def test_counters_sit_beside_the_overlay_metrics(self):
        overlay = SimpleNamespace(metrics=lambda: {"state": "hidden"})
        fast = SimpleNamespace(status=lambda: {"posted": 12, "failures": 3})
        app = SimpleNamespace(runtime=runtime(), controller=Controller(), live=True, overlay=overlay,
                              overlay_submits=2, fast_path=fast)
        status = standalone.status_payload(app, standalone.RetryPolicy(), {})
        self.assertEqual(status["fastPath"], {"posted": 12, "failures": 3})
        self.assertEqual(status["overlay"], {"state": "hidden", "scenesSubmitted": 2})

    def test_no_fast_path_or_a_failing_status(self):
        app = SimpleNamespace()
        self.assertIsNone(standalone.fast_path_status(app))
        app.fast_path = None
        self.assertIsNone(standalone.fast_path_status(app))
        app.fast_path = SimpleNamespace(status="not callable")
        self.assertIsNone(standalone.fast_path_status(app))
        app.fast_path = SimpleNamespace(status=Mock(side_effect=RuntimeError("gone")))
        self.assertEqual(standalone.fast_path_status(app), {"error": "RuntimeError"})
        app.fast_path = SimpleNamespace(status=lambda: None)
        self.assertEqual(standalone.fast_path_status(app), {})


if __name__ == "__main__":
    unittest.main()
