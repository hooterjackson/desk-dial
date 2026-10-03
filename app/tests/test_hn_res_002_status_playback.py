"""HN-RES-002 (standalone side): status.json carries the Sonos transport state under ``playback``
(PLAYING / PAUSED_PLAYBACK / STOPPED / TRANSITIONING / UNKNOWN), a scalar beside ``sonosOnline``,
so the soak sampler can read it. Headless: stand-ins and a real Controller; no Tk, no ports."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import standalone  # noqa: E402
from control_center.controller import Controller  # noqa: E402


def runtime():
    return SimpleNamespace(device_connected=False, device_status="Knob disconnected", led_style="color",
                           artwork_enabled=True, artwork_status=None,
                           apple=SimpleNamespace(credentials={}))


def status_for(controller):
    app = SimpleNamespace(runtime=runtime(), controller=controller, live=True)
    return standalone.status_payload(app, standalone.RetryPolicy(), {})


class StatusPlaybackTests(unittest.TestCase):
    def test_fresh_controller_reports_unknown(self):
        status = status_for(Controller())
        self.assertIn("playback", status)
        self.assertEqual(status["playback"], "UNKNOWN")
        json.dumps(status)

    def test_reports_each_transport_state_as_a_scalar(self):
        for state in ("PLAYING", "PAUSED_PLAYBACK", "STOPPED", "TRANSITIONING"):
            controller = Controller()
            controller.state["playback"] = state
            status = status_for(controller)
            self.assertEqual(status["playback"], state)
            self.assertIsInstance(status["playback"], str)

    def test_no_title_leaks_into_playback(self):
        controller = Controller()
        controller.state["playback"] = "PLAYING"
        controller.state["title"] = "Some Song Title"
        status = status_for(controller)
        self.assertEqual(status["playback"], "PLAYING")
        self.assertNotIn("Some Song Title", json.dumps(status["playback"]))


if __name__ == "__main__":
    unittest.main()
