"""DD-BUG-004 (standalone side): a control the bridge refuses with a ValueError ('Choose an inventoried existing
profile' or other control validation) used to go through the 'error' path: maintain disconnected the knob and
retried every 2-30 s forever, writing a new inventory backup each time. Now the refusal is shown as status, the
knob stays connected (no disconnect, no reconnect) and the auto-connect resumes only when a connect reports a
different inventory, a control is accepted or the owner chooses Connect."""
from pathlib import Path
import sys
import unittest
from unittest.mock import call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import standalone
from connector_support import connector, fake_app, fresh_controller, knob

REFUSAL = 'Choose an inventoried existing profile'


def connects(app):
    return [c for c in app.device.submit.call_args_list if c.args and c.args[0] == 'connect']


def disconnects(app):
    return [c for c in app.device.submit.call_args_list if c == call('disconnect')]


class LifecycleItemTests(unittest.TestCase):
    def test_control_refusals_are_refused_items(self):
        for message in standalone.CONTROL_REFUSALS:
            self.assertEqual(standalone.lifecycle_item('error', {'error': 'ValueError', 'message': message}),
                             ('refused', message))

    def test_link_failures_stay_errors(self):
        self.assertEqual(standalone.lifecycle_item('error', {'error': 'OSError', 'message': REFUSAL}), 'error')
        self.assertEqual(standalone.lifecycle_item('error', {'error': 'ValueError', 'message': 'Invalid frame id'}),
                         'error')
        self.assertEqual(standalone.lifecycle_item('error', {'error': 'ValueError',
                                                             'message': 'Control IDs must increase within a connection'}),
                         'error')
        self.assertEqual(standalone.lifecycle_item('disconnected', {}), 'disconnected')


class RefusalHoldTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(standalone, 'fresh_controller', fresh_controller)
        patcher.start()
        self.addCleanup(patcher.stop)

    def connected_then_refused(self):
        app = fake_app()
        made, policy, lifecycle = connector(standalone, app, [knob('COM5')])
        app.controller.state['online'] = True
        made.step(0.0)                      # found: prepare a fresh controller
        app.controller.state['online'] = True
        made.step(1.0)                      # connect
        self.assertEqual(len(connects(app)), 1)
        app.device.serial = object()
        lifecycle.put('connected')
        made.step(2.0)
        lifecycle.put(standalone.lifecycle_item('error', {'error': 'ValueError', 'message': REFUSAL}))
        made.step(3.0)
        return app, made, policy, lifecycle

    def test_missing_profile_does_not_loop_reconnect_over_five_minutes(self):
        app, made, policy, lifecycle = self.connected_then_refused()
        app.runtime.device_connected = True                 # the knob stays connected while held
        app.runtime.device_status = REFUSAL                 # what the runtime shows for the 'error' event
        for second in range(4, 304):
            made.step(float(second))
        self.assertEqual(len(connects(app)), 1)
        self.assertEqual(disconnects(app), [])
        self.assertEqual(policy.attempts, 0)
        self.assertFalse(policy.inflight)
        self.assertIn(REFUSAL, app.runtime.device_status)
        self.assertNotEqual(app.runtime.device_status, REFUSAL)   # the status says what to do

    def test_a_drop_while_held_waits_for_a_replug_and_a_different_inventory(self):
        app, made, policy, lifecycle = self.connected_then_refused()
        app.device.serial = None
        lifecycle.put('disconnected')
        for second in range(4, 64):                         # the same knob still plugged in: no retry
            made.step(float(second))
        self.assertEqual(len(connects(app)), 1)
        self.assertEqual(policy.attempts, 0)
        made.comports = lambda: []                          # unplugged
        made.step(70.0)
        self.assertTrue(made.replugged)
        self.assertEqual(app.runtime.device_status, 'Knob disconnected')
        made.comports = lambda: [knob('COM5')]              # plugged back in: one connect reads its inventory
        for second in range(74, 90):
            made.step(float(second))
            app.controller.state['online'] = True
        self.assertEqual(len(connects(app)), 2)
        app.device.serial = object()
        lifecycle.put(('connected', frozenset({'BINARIS BEER'})))
        made.step(91.0)
        self.assertIsNone(made.refused)                     # a different profile set ends the hold

    def test_the_same_inventory_keeps_the_hold(self):
        app = fake_app()
        made, policy, lifecycle = connector(standalone, app, [knob('COM5')])
        app.device.serial = object()
        lifecycle.put(standalone.lifecycle_item('connected', {'profiles': {'BINARIS BEER': {}}}))
        lifecycle.put(standalone.lifecycle_item('error', {'error': 'ValueError', 'message': REFUSAL, 'retry': False}))
        made.step(1.0)
        self.assertEqual(made.refused_profiles, frozenset({'BINARIS BEER'}))
        lifecycle.put(('connected', frozenset({'BINARIS BEER'})))
        made.step(2.0)
        self.assertEqual(made.refused, REFUSAL)
        lifecycle.put(('connected', frozenset({'BINARIS BEER', 'MIDI SKIPPER'})))
        made.step(3.0)
        self.assertIsNone(made.refused)
        self.assertEqual(disconnects(app), [])

    def test_retry_false_marks_any_error_as_refused(self):
        self.assertEqual(standalone.lifecycle_item('error', {'error': 'ValueError', 'message': 'x', 'retry': False}),
                         ('refused', 'x'))

    def test_manual_connect_clears_the_hold(self):
        app, made, policy, lifecycle = self.connected_then_refused()
        app.device.serial = None
        lifecycle.put('disconnected')
        made.step(4.0)
        made.clear_refusal()
        for second in range(5, 20):
            made.step(float(second))
            app.controller.state['online'] = True
        self.assertEqual(len(connects(app)), 2)

    def test_link_error_still_reconnects(self):
        app = fake_app()
        app.device.serial = object()
        made, policy, lifecycle = connector(standalone, app)
        lifecycle.put(standalone.lifecycle_item('error', {'error': 'OSError', 'message': 'port gone'}))
        made.step(100.0)
        self.assertEqual(disconnects(app), [call('disconnect')])
        self.assertEqual((policy.attempts, policy.due), (1, 102.0))
        self.assertIsNone(made.refused)


if __name__ == '__main__':
    unittest.main()
