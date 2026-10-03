"""DD-SEC-001 follow-up (runtime): a keystroke refused because the keyboard focus is outside the page
(``focus_refused``) is a refusal like any other, so status.json ``onshape.refusals`` counts it, and the result
still reaches the controller. Uses test_onshape's RuntimeHarness (simulated device): no window, port or network.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from control_center import onshape  # noqa: E402
from test_onshape import RuntimeHarness  # noqa: E402


class StubInjector:
    def __init__(self):
        self.events = []

    def take_events(self):
        events, self.events = self.events, []
        return events

    def status(self):
        return {}

    def close(self):
        pass

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class FocusRefusalCountTests(unittest.TestCase):
    def make(self):
        injector = StubInjector()
        h = RuntimeHarness(self, injector=injector)
        seen = []
        original = h.c.onshape_input
        h.c.onshape_input = lambda result: (seen.append(result), original(result))[1]
        return h, injector, seen

    def test_focus_refused_counts_as_a_refusal(self):
        h, injector, seen = self.make()
        injector.events = [onshape.FOCUS_REFUSED]
        h.runtime._poll_onshape(1000.0)
        self.assertEqual(h.runtime.onshape_refusals, 1)
        self.assertEqual(h.runtime.onshape_status()["refusals"], 1)
        self.assertEqual(seen, ["focus_refused"])

    def test_both_refusal_kinds_add_up_and_other_results_do_not(self):
        h, injector, seen = self.make()
        injector.events = ["refused", "focus_refused", "undo"]
        h.runtime._poll_onshape(1000.0)
        self.assertEqual(h.runtime.onshape_refusals, 2)
        self.assertEqual(seen, ["refused", "focus_refused", "undo"])


if __name__ == "__main__":
    unittest.main()
