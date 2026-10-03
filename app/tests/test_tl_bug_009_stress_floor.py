"""TL-BUG-009: the stress hard gates have a floor, like the soak's SOAK_GATE_MINUTES. stressUntouched and stressTurn
are true only when each pass sent at least STRESS_GATE_FRAMES (300) frame updates and an unpaced artwork2 pass lasted
at least STRESS_GATE_SECONDS; --stress-frames 0 is refused by argparse; main() records the effective arguments.
raw_checks() runs against test_cc5_tooling's FakeFirmware (no port, no device, fake clock)."""
import contextlib
import io
import itertools
import unittest
from types import SimpleNamespace
from unittest import mock

import test_cc5_tooling as base

t = base.t


@base.needs_tooling
class StressFloorTests(unittest.TestCase):
    PROFILE = t.PROFILES["cc5.3"] if t else None

    def setUp(self):
        self.module = base.load_script("check_nanod_cc5.py")
        self.out = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.out))

    def raw(self, stress_frames, stress_seconds, floor=None):
        """raw_checks with the real floor (or `floor` = (frames, seconds)), a 1 min soak counted as enough."""
        firmware = base.FakeFirmware()
        real = t.RawKnob
        clock = itertools.count(0, 0.001).__next__
        factory = lambda port: real(port, serial_factory=lambda name: firmware, clock=clock, sleep=lambda s: None)  # noqa: E731
        firmware.clock = clock
        base.FakeOperator(firmware)
        report = self.module.Report("FAKEAPP", self.PROFILE)
        args = SimpleNamespace(turn_seconds=1.0, stress_frames=stress_frames, replay_transfers=3, soak_minutes=1.0,
                               stress_seconds=stress_seconds, step_timeout=30.0)
        patches = [mock.patch.object(t, "RawKnob", factory), mock.patch.object(t, "SOAK_GATE_MINUTES", 1.0)]
        if floor is not None:
            patches += [mock.patch.object(self.module, "STRESS_GATE_FRAMES", floor[0]),
                        mock.patch.object(self.module, "STRESS_GATE_SECONDS", floor[1])]
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            self.module.raw_checks("FAKEAPP", report, {}, args, base.FakeCheckpoints(report), self.PROFILE)
        return report

    def test_stress_gate_needs_minimum_frames(self):
        # The finding's run: --stress-frames 0 --stress-seconds 0 (argparse now refuses it; raw_checks still guards).
        report = self.raw(0, 0.0)
        self.assertFalse(report.gates["stressUntouched"])
        self.assertFalse(report.gates["stressTurn"])
        sections = report.data["sections"]
        for name in ("stress", "stressTurn"):
            floor = sections[name]["gateFloor"]
            self.assertEqual(floor["frames"], 300)
            self.assertTrue(floor["problems"], name)
        self.assertIn("Note: the stressUntouched gate needs a full-length pass", self.out.getvalue())

    def test_a_short_run_is_recorded_but_does_not_pass_the_gates(self):
        report = self.raw(40, 2.0)
        sections = report.data["sections"]
        self.assertTrue(sections["stress"]["passed"] and sections["stressTurn"]["passed"])   # the pass itself was clean
        self.assertFalse(report.gates["stressUntouched"] or report.gates["stressTurn"])
        problems = sections["stress"]["gateFloor"]["problems"]
        self.assertTrue(any("< 300" in p for p in problems), problems)
        self.assertTrue(any("v1 art" in p for p in problems), problems)               # the v1 part has the floor too
        self.assertTrue(any("s of unpaced media stress" in p for p in problems), problems)

    def test_a_run_at_the_floor_passes(self):
        report = self.raw(40, 2.0, floor=(40, 2.0))
        self.assertTrue(report.gates["stressUntouched"] and report.gates["stressTurn"])
        self.assertEqual(report.data["sections"]["stress"]["gateFloor"]["problems"], [])

    def test_floor_problems(self):
        f = self.module.stress_floor_problems
        self.assertEqual(f({"framesSent": 300, "window": [0.0, 20.0]}, media=object()), [])
        self.assertEqual(f({"framesSent": 300, "window": [0.0, 1.0]}), [])             # paced v1: frames only
        self.assertEqual(len(f({"framesSent": 0, "window": [0.0, 0.0]}, media=object())), 2)
        self.assertEqual(self.module.STRESS_GATE_SECONDS, t.STRESS_MIN_SECONDS)

    def test_argparse_rejects_stress_frames_below_one(self):
        err = io.StringIO()
        for value in ("0", "-5"):
            with self.subTest(value=value), contextlib.redirect_stderr(err), \
                    mock.patch.object(t, "require_companion_quit", side_effect=AssertionError("ran")):
                with self.assertRaises(SystemExit) as raised:
                    self.module.main(["--stress-frames", value])
                self.assertEqual(raised.exception.code, 2)
        self.assertIn("must be at least 1", err.getvalue())

    def test_main_records_the_effective_arguments(self):
        written = []
        with mock.patch.object(t, "require_companion_quit", lambda: False), \
                mock.patch.object(t, "find_app_port", lambda *a, **k: "FAKEAPP"), \
                mock.patch.object(t, "write_json_evidence", lambda path, data, **k: written.append(data)), \
                mock.patch.object(self.module, "RebootWatch", mock.MagicMock()), \
                mock.patch.object(self.module, "bridge_checks", lambda *a, **k: {}), \
                mock.patch.object(self.module, "raw_checks", lambda *a, **k: None), \
                mock.patch.object(self.module.time, "sleep", lambda s: None):
            self.module.main(["--stress-frames", "12", "--stress-seconds", "3", "--soak-minutes", "0"])
        [data] = written
        self.assertEqual((data["arguments"]["stress_frames"], data["arguments"]["stress_seconds"],
                          data["arguments"]["soak_minutes"]), (12, 3.0, 0.0))


if __name__ == "__main__":
    unittest.main()
