"""FW-BUG-035: the device-side register-range check, driven against a fake knob (no port, no network)."""
import json
from pathlib import Path
import sys
import unittest

WORK = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(WORK))

import nanod_register_range_check as rr  # noqa: E402


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 0.05
        return self.t


class FakeKnob:
    """Answers R commands the way the fixed (or, with fixed=False, the old aliasing) firmware does."""

    def __init__(self, fixed=True):
        self.fixed = fixed
        self.out = []
        self.sent = []
        self.calibrations = 0

    def write(self, data):
        command = json.loads(data.decode("utf-8"))["R"]
        self.sent.append(command)
        reg_text, _, value_text = command.partition("=")
        reg, value = int(reg_text), int(value_text or 0)
        if self.fixed and not 0 <= reg <= 255:
            self._line({"error": "R: register must be 0..255"})
            return
        reg &= 0xFF
        if self.fixed and reg == 129 and value not in (0, 1):
            self._line({"error": "R: recalibrate value must be 0 or 1"})
            return
        value &= 0xFF
        self._line({"r": f"r{reg}=0"})
        if reg == 129 and value == 1:
            self.calibrations += 1
            self._line({"calibrating": True})
            self._line({"calibrated": {"ok": True, "reason": ""}})

    def _line(self, message):
        self.out.append((json.dumps(message) + "\n").encode("utf-8"))

    def read(self, n):
        return self.out.pop(0) if self.out else b""


class RegisterRangeCheck(unittest.TestCase):
    def test_fixed_firmware_passes(self):
        knob = FakeKnob(fixed=True)
        report = rr.register_number_out_of_range_is_refused(knob, clock=FakeClock())
        self.assertEqual(knob.sent, ["385=1", "129=257", "129=1"])
        self.assertEqual(knob.calibrations, 1)
        for command in rr.REFUSED_COMMANDS:
            self.assertEqual(report["refused"][command], dict(error=True, r=False, calibrating=False))
        self.assertEqual(report["accepted"]["r"], "r129=0")
        self.assertTrue(report["accepted"]["calibrated"]["ok"])

    def test_aliasing_firmware_fails(self):
        with self.assertRaises(AssertionError) as caught:
            rr.register_number_out_of_range_is_refused(FakeKnob(fixed=False), clock=FakeClock())
        self.assertIn("385=1", str(caught.exception))

    def test_noise_lines_are_skipped(self):
        knob = FakeKnob(fixed=True)
        knob.out.append(b"not json\n{\"debug\":\"boot\"}\n")
        report = rr.register_number_out_of_range_is_refused(knob, clock=FakeClock())
        self.assertEqual(report["accepted"]["r"], "r129=0")


if __name__ == "__main__":
    unittest.main()
