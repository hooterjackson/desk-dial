"""TL-BUG-008: Ctrl+C (KeyboardInterrupt) during check_nanod_cc5.py writes the record as passed False, completed
False with an 'interrupted' failure, prints no PASSED verdict and re-raises; a run whose gates are not all true is
never passed. main() runs with the port, the watch and the checks replaced (no port, no device)."""
import contextlib
import io
import unittest
from unittest import mock

import test_cc5_tooling as base

t = base.t


@base.needs_tooling
class CheckInterruptTests(unittest.TestCase):
    def setUp(self):
        self.module = base.load_script("check_nanod_cc5.py")
        self.out = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.out))
        self.written = []
        for target, name, value in (
                (t, "require_companion_quit", lambda: False),
                (t, "find_app_port", lambda *a, **k: "FAKEAPP"),
                (t, "write_json_evidence", lambda path, data, **k: self.written.append((path, data))),
                (self.module, "RebootWatch", mock.MagicMock()),
                (self.module.time, "sleep", lambda s: None)):
            self.enterContext(mock.patch.object(target, name, value))

    def run_main(self, bridge=None, raw=None):
        self.enterContext(mock.patch.object(self.module, "bridge_checks", bridge or (lambda *a, **k: {})))
        self.enterContext(mock.patch.object(self.module, "raw_checks", raw or (lambda *a, **k: None)))
        return self.module.main([])

    def interrupt(self, *args, **kwargs):
        raise KeyboardInterrupt()

    def test_keyboard_interrupt_is_recorded_as_not_passed(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_main(bridge=self.interrupt)
        [(path, data)] = self.written                              # the record is written before the re-raise
        self.assertEqual(path, t.CURRENT.device_checks)
        self.assertIs(data["passed"], False)
        self.assertIs(data["completed"], False)
        self.assertIs(data["interrupted"], True)
        self.assertIn(self.module.INTERRUPTED_CHECK, data["failures"])
        self.assertIn("interrupted", self.module.INTERRUPTED_CHECK)
        output = self.out.getvalue()
        self.assertNotIn("PASSED", output)
        self.assertIn("INTERRUPTED", output)

    def test_keyboard_interrupt_in_the_raw_checks_also_stops_the_run(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_main(raw=self.interrupt)
        [(_, data)] = self.written
        self.assertEqual((data["passed"], data["completed"]), (False, False))

    def test_a_run_without_failures_but_with_false_gates_is_not_passed(self):
        self.assertEqual(self.run_main(), 1)                      # nothing ran, so every gate is still false
        [(_, data)] = self.written
        self.assertEqual(data["failures"], [])
        self.assertIs(data["passed"], False)
        self.assertIs(data["completed"], True)
        self.assertEqual(set(data["gatesFalse"]), set(t.CURRENT.gates))
        self.assertNotIn("PASSED;", self.out.getvalue())
        self.assertIn("FAILED (gates not passed:", self.out.getvalue())

    def test_a_run_with_every_gate_true_and_no_failure_passes(self):
        def all_gates(port, report, caps, args, watch, profile):
            for name in report.gates:
                report.gates[name] = True
        self.assertEqual(self.run_main(raw=all_gates), 0)
        [(_, data)] = self.written
        self.assertEqual((data["passed"], data["completed"], data["interrupted"], data["gatesFalse"]),
                         (True, True, False, []))
        self.assertIn("PASSED;", self.out.getvalue())


if __name__ == "__main__":
    unittest.main()
