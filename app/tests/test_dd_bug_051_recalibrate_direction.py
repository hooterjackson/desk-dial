"""DD-BUG-051: after the knob refuses a motor direction change, a later plain Recalibrate never
accepts it; only the explicit Keep new direction does, and a disconnect / reconnect withdraws the
offer. Headless: ui.RecalibrationGuard over a runtime stand-in that answers like runtime.py (a new
``calibration_result`` tuple per ``calibrated`` event); no Tk, no ports."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import ui  # noqa: E402

UI_SOURCE = (Path(__file__).resolve().parents[1] / "control_center" / "ui.py").read_text(encoding="utf-8")


class Runtime:
    def __init__(self):
        self.device_connected = True
        self.calibrating = False
        self.calibration_result = None
        self.sent = []

    def recalibrate_motor(self, accept_direction=False):
        if self.calibrating:
            return "The knob is already recalibrating."
        if not self.device_connected:
            return "Recalibration needs the knob connected."
        self.calibrating = True
        self.sent.append({"acceptDirection": bool(accept_direction)})
        return None

    def calibrated(self, ok, reason=""):
        self.calibrating = False
        self.calibration_result = (ok is True, str(reason))     # a new tuple, as runtime.py builds it


class RecalibrateDirectionTests(unittest.TestCase):
    def setUp(self):
        self.rt = Runtime()
        self.guard = ui.RecalibrationGuard()

    def refuse(self):
        self.assertIsNone(self.guard.press(self.rt))
        self.guard.observe(self.rt)                       # a tick while it aligns
        self.assertFalse(self.guard.pending(self.rt))
        self.rt.calibrated(False, "direction-changed")
        self.guard.observe(self.rt)

    def test_recalibrate_after_direction_refusal_requires_explicit_confirmation(self):
        self.refuse()
        self.assertTrue(self.guard.pending(self.rt), "Settings offers Keep new direction")
        self.assertIsNone(self.guard.press(self.rt))     # the owner presses Recalibrate again
        self.assertEqual(self.rt.sent, [{"acceptDirection": False}, {"acceptDirection": False}],
                         "a plain press never accepts the direction change")
        self.assertFalse(self.guard.pending(self.rt), "the new run withdrew the offer")
        self.rt.calibrated(False, "direction-changed")   # refused again
        self.assertTrue(self.guard.pending(self.rt))
        self.assertIsNone(self.guard.confirm(self.rt))   # Keep new direction
        self.assertEqual(self.rt.sent[-1], {"acceptDirection": True})
        self.assertFalse(self.guard.pending(self.rt))
        self.rt.calibrated(True, "ok")
        self.assertFalse(self.guard.pending(self.rt))
        self.assertIsNotNone(self.guard.confirm(self.rt), "nothing left to keep")
        self.assertEqual(len(self.rt.sent), 3)

    def test_reconnect_withdraws_the_offer(self):
        self.refuse()
        self.assertTrue(self.guard.pending(self.rt))
        self.rt.device_connected = False                 # unplugged
        self.guard.observe(self.rt)
        self.rt.device_connected = True                  # replugged; the stale result is still there
        self.assertFalse(self.guard.pending(self.rt))
        self.assertIsNotNone(self.guard.confirm(self.rt))
        self.assertIsNone(self.guard.press(self.rt))
        self.assertEqual(self.rt.sent[-1], {"acceptDirection": False})

    def test_a_refusal_not_started_here_is_never_offered(self):
        self.rt.calibrated(False, "direction-changed")   # e.g. a result left from before Settings ran one
        self.assertFalse(self.guard.pending(self.rt))
        self.assertIsNone(self.guard.press(self.rt))
        self.assertEqual(self.rt.sent, [{"acceptDirection": False}])

    def test_dismiss_and_a_new_runtime_withdraw_the_offer(self):
        self.refuse()
        self.guard.dismiss()
        self.assertFalse(self.guard.pending(self.rt))
        self.refuse()
        other = Runtime()
        other.calibration_result = self.rt.calibration_result
        self.assertFalse(self.guard.pending(other))

    def test_other_refusals_are_not_offered(self):
        self.assertIsNone(self.guard.press(self.rt))
        self.rt.calibrated(False, "pole-check-failed")
        self.assertFalse(self.guard.pending(self.rt))

    def test_settings_uses_the_guard(self):
        self.assertNotIn("accept = bool(last) and last[0] is False", UI_SOURCE)
        self.assertIn("guard.press(self.runtime)", UI_SOURCE)
        self.assertIn('"Keep new direction", keep_direction', UI_SOURCE)
        self.assertIn("self._recal_guard().observe(self.runtime)", UI_SOURCE)


if __name__ == "__main__":
    unittest.main()
