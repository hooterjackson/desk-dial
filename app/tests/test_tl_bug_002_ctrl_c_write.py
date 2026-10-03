"""TL-BUG-002: Ctrl+C (KeyboardInterrupt) while app0 is written must still restore (install), warn not to reset,
and record the real outcome instead of STARTED (install and rollback). Runs the scripts' main() against the fake
esptool of test_cc5_tooling (no process, no port)."""
import unittest

import test_cc5_tooling as base

t = base.t


class InstallInterruptTests(base.InstallFlowTests):
    def test_keyboard_interrupt_during_write_restores_and_warns(self):
        code, report, fake = self.run_install(write=KeyboardInterrupt())
        self.assertNotEqual(report["outcome"], "STARTED")
        self.assertEqual((code, report["outcome"]), (3, t.CURRENT.restored_outcome))
        self.assertTrue(report["interrupted"])
        self.assertTrue(report["restoreAttempted"])
        self.assertEqual(fake.names()[-4:], ["restore-write", "restore-verify-app0", "restore-verify-full", "restore-reset"])
        self.assertEqual(fake.resets(), ["restore-reset"])
        self.assertIn("Do not reset or power-cycle", self.out.getvalue())

    def test_keyboard_interrupt_with_a_failing_restore_never_resets(self):
        code, report, fake = self.run_install(write=KeyboardInterrupt(), **{"restore-verify-full": False})
        self.assertEqual((code, report["outcome"], fake.resets()), (4, "RESTORE_FAILED_NO_RESET", []))
        self.assertIn("Do not reset or power-cycle", self.out.getvalue())

    def test_keyboard_interrupt_before_the_write_sends_nothing_more(self):
        code, report, fake = self.run_install(**{"before-verify": KeyboardInterrupt()})
        self.assertEqual((code, report["outcome"], fake.resets()), (2, "STOPPED_BEFORE_WRITE", []))
        self.assertNotIn("write", fake.names())


class RollbackInterruptTests(base.RollbackFlowTests):
    def test_keyboard_interrupt_during_write_warns_and_records(self):
        code, report, fake = self.run_rollback(write=KeyboardInterrupt())
        self.assertEqual((code, report["outcome"]), (4, "FAILED_AFTER_WRITE_NO_RESET"))
        self.assertTrue(report["interrupted"])
        self.assertEqual((fake.resets(), self.records), ([], []))
        self.assertIn("Do not reset or power-cycle", self.out.getvalue())


def load_tests(loader, tests, pattern):
    """Only this file's tests (the base classes' own tests run in test_cc5_tooling.py)."""
    suite = unittest.TestSuite()
    for cls in (InstallInterruptTests, RollbackInterruptTests):
        suite.addTests(cls(name) for name in vars(cls) if name.startswith("test_"))
    return suite


if __name__ == "__main__":
    unittest.main()
