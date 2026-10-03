"""DD-BUG-045: one knob link failure was counted twice in the reconnect back-off. The bridge reports a drop as
'error' (or 'released') and then 'disconnected' (in the same maintain pass for an OSError, in the next one when
maintain asks for the disconnect), and both ran RetryPolicy.failed, so the delays went 4 s, 16 s, 30 s instead
of 2 s, 4 s, 8 s. Now each connection attempt fails once."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import standalone
from connector_support import connector, fake_app, fresh_controller, knob


class OneFailureOneStepTests(unittest.TestCase):
    def test_error_then_disconnected_in_one_pass_counts_once(self):
        app = fake_app()
        made, policy, lifecycle = connector(standalone, app)
        for kind in ('error', 'disconnected'):
            lifecycle.put(kind)
        made.step(100.0)
        self.assertEqual(policy.attempts, 1)
        self.assertEqual(policy.due, 102.0)

    def test_error_then_disconnected_in_the_next_pass_counts_once(self):
        app = fake_app()
        app.device.serial = object()          # the bridge still holds the port: maintain asks it to let go
        made, policy, lifecycle = connector(standalone, app)
        lifecycle.put('error')
        made.step(100.0)
        app.device.submit.assert_called_once_with('disconnect')
        app.device.serial = None
        lifecycle.put('disconnected')
        made.step(101.0)
        self.assertEqual((policy.attempts, policy.due), (1, 102.0))

    def test_released_then_disconnected_counts_once(self):
        app = fake_app()
        made, policy, lifecycle = connector(standalone, app)
        lifecycle.put('released')
        lifecycle.put('disconnected')
        made.step(50.0)
        self.assertEqual((policy.attempts, policy.due), (1, 52.0))

    def test_connect_timeout_and_its_disconnected_count_once(self):
        app = fake_app()
        made, policy, lifecycle = connector(standalone, app)
        policy.inflight, policy.due = True, 10.0
        made.step(11.0)
        self.assertEqual((policy.attempts, policy.due), (1, 13.0))
        lifecycle.put('disconnected')
        made.step(12.0)
        self.assertEqual(policy.attempts, 1)

    def test_back_off_grows_two_four_eight_over_failed_attempts(self):
        app = fake_app()
        made, policy, lifecycle = connector(standalone, app, [knob('COM5')])
        app.controller.state['online'] = True    # connect right after preparing (not the subject here)
        now, delays = 0.0, []
        with patch.object(standalone, 'fresh_controller', lambda previous, runtime=None: app.controller):
            for _ in range(3):
                made.step(now)                    # port found: preparing
                made.step(now)                    # connect submitted
                self.assertEqual(app.device.submit.call_args.args, ('connect', 'COM5'))
                lifecycle.put('error')
                lifecycle.put('disconnected')
                made.step(now)
                delays.append(policy.due - now)
                now = policy.due
        self.assertEqual(delays, [2.0, 4.0, 8.0])

    def test_a_ready_knob_that_drops_later_starts_again_at_two_seconds(self):
        app = fake_app()
        made, policy, lifecycle = connector(standalone, app)
        lifecycle.put('error'); lifecycle.put('disconnected')
        made.step(0.0)
        lifecycle.put('ready')
        made.step(5.0)
        self.assertEqual(policy.attempts, 0)
        lifecycle.put('disconnected')
        made.step(60.0)
        self.assertEqual((policy.attempts, policy.due), (1, 62.0))

    def test_a_connect_from_settings_that_fails_counts_once(self):
        app = fake_app()
        made, policy, lifecycle = connector(standalone, app)
        lifecycle.put('error'); lifecycle.put('disconnected')
        made.step(0.0)
        for kind in ('connected', 'error', 'disconnected'):   # Settings' Connect, not submitted by the connector
            lifecycle.put(kind)
        made.step(10.0)
        self.assertEqual((policy.attempts, policy.due), (2, 14.0))


if __name__ == "__main__":
    unittest.main()
