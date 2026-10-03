"""DD-RES-017: a found knob waited the whole 5 s preparation fallback whenever Sonos answered offline (no
speaker set up, or one switched off): the gate only looked for 'online'. It now connects as soon as the fresh
controller's Sonos state is in, online or not, and the maintain tick runs every 250 ms while it waits."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import standalone
from connector_support import connector, fake_app, fresh_controller, knob


class ConnectOnSonosAnswerTests(unittest.TestCase):
    def prepared(self):
        app = fake_app()
        made, policy, lifecycle = connector(standalone, app, [knob('COM5')])
        with patch.object(standalone, 'fresh_controller', fresh_controller):
            made.step(100.0)
        self.assertEqual(made.preparing, ('COM5', 105.0))
        return app, made, policy

    def test_connect_does_not_wait_for_deadline_when_sonos_state_answered_offline(self):
        app, made, policy = self.prepared()
        app.controller.state_known, app.controller.state['online'] = True, False
        made.step(100.25)
        app.device.submit.assert_called_once_with('connect', 'COM5')
        self.assertIsNone(made.preparing)
        self.assertEqual(policy.due, 140.25)
        self.assertEqual(app.config['port'], 'COM5')

    def test_connect_waits_while_sonos_has_not_answered(self):
        app, made, _ = self.prepared()
        made.step(104.0)
        app.device.submit.assert_not_called()
        self.assertIsNotNone(made.preparing)
        made.step(105.0)                                   # the fallback still covers no answer at all
        app.device.submit.assert_called_once_with('connect', 'COM5')

    def test_online_still_connects_at_once(self):
        app, made, _ = self.prepared()
        app.controller.state['online'] = True
        made.step(100.25)
        app.device.submit.assert_called_once_with('connect', 'COM5')

    def test_the_tick_is_faster_while_preparing(self):
        self.assertEqual((standalone.MAINTAIN_MS, standalone.MAINTAIN_PREPARING_MS), (1000, 250))
        source = (ROOT / "standalone.py").read_text(encoding="utf-8")
        self.assertIn("root.after(MAINTAIN_PREPARING_MS if connector.preparing is not None else MAINTAIN_MS, maintain)",
                      source)


if __name__ == "__main__":
    unittest.main()
