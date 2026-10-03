"""DD-BUG-046: every knob reports the USB serial NANO_D, so with two knobs plugged the auto-connect matched
neither and kept waiting with no reason shown. The remembered port (config['port'], saved at every connect
or chosen in Settings) now breaks the tie; without one, the status says two knobs were found."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import standalone
from connector_support import connector, fake_app, fresh_controller, knob, other


class MatchingPortTests(unittest.TestCase):
    def test_two_knobs_prefer_the_remembered_port(self):
        ports = [knob('COM5'), knob('COM6'), other('COM3')]
        self.assertEqual(standalone.matching_port(ports, remembered='COM6'), 'COM6')
        self.assertEqual(standalone.matching_port(ports, remembered='com5 '), 'COM5')

    def test_two_knobs_without_a_usable_remembered_port_match_none(self):
        ports = [knob('COM5'), knob('COM6')]
        for remembered in (None, '', 'COM9'):
            with self.subTest(remembered=remembered):
                self.assertIsNone(standalone.matching_port(ports, remembered=remembered))

    def test_one_knob_is_used_whatever_was_remembered(self):
        self.assertEqual(standalone.matching_port([knob('COM7'), other('COM3')], remembered='COM6'), 'COM7')
        self.assertIsNone(standalone.matching_port([other('COM3')], remembered='COM3'))


class ConnectorTwoKnobTests(unittest.TestCase):
    def test_remembered_port_is_prepared_for_connect(self):
        app = fake_app(port='COM6')
        made, policy, _ = connector(standalone, app, [knob('COM5'), knob('COM6')])
        with patch.object(standalone, 'fresh_controller', fresh_controller):
            made.step(100.0)
        self.assertEqual(made.preparing, ('COM6', 100.0 + made.PREPARE_SECONDS))
        self.assertTrue(policy.inflight)

    def test_no_remembered_port_reports_two_knobs_and_retries(self):
        app = fake_app(port='')
        made, policy, _ = connector(standalone, app, [knob('COM5'), knob('COM6')])
        made.step(100.0)
        self.assertIsNone(made.preparing)
        self.assertFalse(policy.inflight)
        self.assertEqual(policy.due, 103.0)
        self.assertEqual(app.runtime.device_status, standalone.TWO_KNOBS_STATUS)
        self.assertIn('Two knobs', app.runtime.device_status)
        app.device.submit.assert_not_called()

    def test_the_two_knob_status_clears_when_both_are_gone(self):
        app = fake_app(port='')
        app.runtime.device_status = standalone.TWO_KNOBS_STATUS
        made, _, _ = connector(standalone, app, [])
        made.step(100.0)
        self.assertEqual(app.runtime.device_status, 'Knob disconnected')

    def test_other_statuses_are_left_alone_with_no_knob(self):
        app = fake_app(port='')
        app.runtime.device_status = 'Host control released · disconnect and reconnect'
        made, _, _ = connector(standalone, app, [])
        made.step(100.0)
        self.assertEqual(app.runtime.device_status, 'Host control released · disconnect and reconnect')


if __name__ == "__main__":
    unittest.main()
