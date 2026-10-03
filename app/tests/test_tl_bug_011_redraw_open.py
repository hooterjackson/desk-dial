"""TL-BUG-011: tooling.redraw_check opens the knob inside its try, so a port that cannot be reopened (Desk Dial grabbed
it, Windows still holds the handle, the knob re-enumerated) is one recorded problem with passed False, never an
uncaught exception (check_nanod_cc5_look.py then writes its record, or NOT RUN when a companion owns the port).
Fake knob factories only: no port."""
import unittest

import test_cc5_tooling as base

t = base.t


class FakeRedrawKnob:
    def __init__(self):
        self.calls, self.errors = [], []

    def enter(self, control):
        self.calls.append("enter")
        raise OSError("lost the port")

    def release_quietly(self):
        self.calls.append("release")

    def close(self):
        self.calls.append("close")


@base.needs_tooling
class RedrawOpenTests(unittest.TestCase):
    def test_redraw_check_port_open_failure_is_a_problem_not_an_exception(self):
        for exc in (OSError("could not open port 'COMX': PermissionError(13, 'Access is denied.')"),
                    RuntimeError("serial exception")):
            def factory(port, exc=exc):
                raise exc
            with self.subTest(exc=type(exc).__name__):
                result = t.redraw_check("COMX", knob_factory=factory, sleep=lambda s: None)
                self.assertFalse(result["passed"])
                self.assertEqual(len(result["problems"]), 1)
                self.assertIn("the redraw check could not run", result["problems"][0])
                self.assertIn(type(exc).__name__, result["problems"][0])
                self.assertEqual(result["samples"], [])
                self.assertEqual(result["claimErrors"], [])

    def test_a_failure_after_the_open_still_releases_and_closes(self):
        knob = FakeRedrawKnob()
        result = t.redraw_check("COMX", knob_factory=lambda port: knob, sleep=lambda s: None)
        self.assertFalse(result["passed"])
        self.assertEqual(knob.calls, ["enter", "release", "close"])
        self.assertIn("the redraw check could not run (OSError", result["problems"][0])


if __name__ == "__main__":
    unittest.main()
