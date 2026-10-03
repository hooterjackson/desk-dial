"""DD-RES-016: a failure on the serial reader's fast path is logged (the first, then one in
FAST_PATH_LOG_EVERY, at WARNING with the traceback) and reported (``FastPath.status()`` and the Tk
tick's ``failure_counts['fast-path']``), instead of only bumping a counter nothing reads.
Headless: FastPath over raising stand-ins; no Tk, no ports."""
import logging
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import ui  # noqa: E402


class BrokenOverlay:
    def post_input(self, *args):
        raise RuntimeError("post_input regression")


class BrokenNavigator:
    def note_turn(self):
        raise RuntimeError("note_turn regression")

    def note_press(self, slot):
        raise RuntimeError("note_press regression")


class FastPathFailureTests(unittest.TestCase):
    def handle_twice(self, fast):
        with self.assertLogs(ui._log, level="WARNING") as logs:
            self.assertFalse(fast.handle("position", {"id": "volume", "position": 3, "delta": 1}, t=1.0))
            self.assertFalse(fast.handle("position", {"id": "volume", "position": 4, "delta": 1}, t=1.1))
        return logs

    def test_fast_path_failure_is_logged_once_and_reported(self):
        fast = ui.FastPath(overlay=BrokenOverlay())
        logs = self.handle_twice(fast)
        warnings = [r for r in logs.records if r.levelno == logging.WARNING]
        self.assertEqual(len(warnings), 1, "the first failure only")
        self.assertIsNotNone(warnings[0].exc_info, "with the traceback")
        self.assertIn("post_input regression", logs.output[0])
        self.assertEqual(fast.failures, 2)
        self.assertEqual(fast.status(), {"posted": 0, "failures": 2})

    def test_navigator_failures_are_logged_too(self):
        fast = ui.FastPath(navigator=BrokenNavigator())
        with self.assertLogs(ui._log, level="WARNING") as logs:
            self.assertTrue(fast.handle("position", {"id": "volume", "position": 3}, t=1.0))
        self.assertEqual(fast.failures, 1)
        self.assertIn("note_turn regression", "\n".join(logs.output))

    def test_logging_is_rate_limited_by_count(self):
        fast = ui.FastPath(overlay=BrokenOverlay())
        with patch.object(ui, "FAST_PATH_LOG_EVERY", 10), self.assertLogs(ui._log, level="WARNING") as logs:
            for i in range(25):
                fast.handle("position", {"id": "volume", "position": i}, t=float(i))
        self.assertEqual(fast.failures, 25)
        self.assertEqual(len(logs.records), 3, "failures 1, 10 and 20")

    def test_the_tk_tick_reports_the_count(self):
        fast = ui.FastPath(overlay=BrokenOverlay())
        self.handle_twice(fast)
        app = object.__new__(ui.ControlCenterApp)
        app.fast_path = fast
        app.failure_counts = {}
        app.runtime = SimpleNamespace(button_order=[0, 1, 2, 3],
                                      controller=SimpleNamespace(screen=SimpleNamespace(mode="launcher")))
        try:
            ui.ControlCenterApp._sync_presenters(app)
        except Exception:
            pass                      # later steps need a fuller app; the count is taken first
        self.assertEqual(app.failure_counts.get("fast-path"), 2)


if __name__ == "__main__":
    unittest.main()
