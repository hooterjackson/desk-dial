"""DD-RES-011: ``navigator_model.read_snapshot`` keeps never raising, but the first failure of each
kind is logged at WARNING (with its traceback) and the partial snapshot is marked. No Tk, no ports."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import navigator_model as NM  # noqa: E402


class _Screen:
    mode = "launcher"
    index = 0


class BrokenController:
    screen = _Screen()

    @property
    def spaces(self):
        raise TypeError("spaces reshaped in a split")   # getattr would swallow an AttributeError


class SnapshotLogTests(unittest.TestCase):
    def setUp(self):
        NM._SNAPSHOT_FAILURES_LOGGED.clear()

    def test_snapshot_failure_is_logged_once(self):
        with self.assertLogs("control_center.navigator_model", "WARNING") as cm:
            first = NM.read_snapshot(BrokenController(), {})
            second = NM.read_snapshot(BrokenController(), {})
        self.assertIsInstance(first, dict)
        self.assertIsInstance(second, dict)
        self.assertEqual(first["mode"], "launcher")            # what was read before the failure stays
        self.assertEqual(first.get("error"), "TypeError")
        self.assertEqual(len(cm.records), 1)
        self.assertIsNotNone(cm.records[0].exc_info)

    def test_a_healthy_snapshot_logs_nothing(self):
        class Fine:
            screen = _Screen()
            spaces = False
        with self.assertNoLogs("control_center.navigator_model", "WARNING"):
            snap = NM.read_snapshot(Fine(), {})
        self.assertNotIn("error", snap)


if __name__ == "__main__":
    unittest.main()
