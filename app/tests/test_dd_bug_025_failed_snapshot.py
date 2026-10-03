"""DD-BUG-025: when All off cannot take its snapshot (scene.create times out or is refused), an older
snapshot must not be replayed by the next Turn on: it reads as none, so Turn on uses light.turn_on.

Offline: fake WebSocket server from test_cc_home_assistant (no network, no Tk)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import home_assistant as ha_module  # noqa: E402

import test_cc_home_assistant as base  # noqa: E402
from test_cc_home_assistant import AdapterCase, wait_for  # noqa: E402

setUpModule = base.setUpModule          # never a real WebSocket / HTTP session
tearDownModule = base.tearDownModule


class FailedSnapshotTests(AdapterCase):
    def setUp(self):
        self.adapter = self.make()
        self.adapter.start()
        self.assertTrue(wait_for(lambda: self.adapter.read_state()["online"]))

    def break_scene_create(self, answer):
        original = self.server.handle

        def handle(socket, message):
            if message.get("type") == "call_service" and message.get("service") == "create":
                self.server.calls.append(("scene", "create", message.get("service_data"), None))
                if answer:
                    socket.push({"id": message["id"], "type": "result", "success": False,
                                 "error": {"code": "home_assistant_error", "message": "busy"}})
                return                                  # no answer: a timeout
            original(socket, message)
        self.server.handle = handle

    def check(self, answer):
        self.adapter.power(False)                       # the morning snapshot
        self.assertTrue(self.adapter.read_state()["snapshot"])
        self.adapter.power(True)
        self.assertEqual(self.server.calls[-1][:2], ("scene", "turn_on"))
        self.break_scene_create(answer)
        with patch.object(ha_module, "CALL_TIMEOUT", 0.2), self.assertLogs(ha_module._log, "WARNING"):
            self.adapter.power(False)                   # the evening snapshot fails
        self.assertEqual(self.server.calls[-1], ("light", "turn_off", {}, {"entity_id": "light.hall"}),
                         "the lights still go off")
        self.assertFalse(self.adapter.read_state()["snapshot"])
        self.adapter.power(True)
        self.assertEqual(self.server.calls[-1], ("light", "turn_on", {}, {"entity_id": "light.hall"}),
                         "never the morning snapshot")

    def test_turn_on_after_failed_snapshot_does_not_replay_old_snapshot(self):
        self.check(answer=False)

    def test_turn_on_after_a_refused_snapshot_does_not_replay_old_snapshot(self):
        self.check(answer=True)

    def test_the_next_good_snapshot_is_used_again(self):
        self.break_scene_create(answer=True)
        with self.assertLogs(ha_module._log, "WARNING"):
            self.adapter.power(False)
        del self.server.handle                          # the class's own handler again
        self.adapter.power(False)
        self.adapter.power(True)
        self.assertEqual(self.server.calls[-1][:2], ("scene", "turn_on"))


if __name__ == "__main__":
    unittest.main()
