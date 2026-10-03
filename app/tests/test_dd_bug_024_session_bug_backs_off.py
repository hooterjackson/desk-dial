"""DD-BUG-024 review: only a network drop of a healthy session starts the reconnect back-off over.
A bug that fires after the first states (here _store raising on a state_changed event, as another
Home Assistant's data shape could) would fire again on every reconnect, so the attempts keep growing
(0, 1, 2, ...) instead of reconnecting about once a second forever.

Offline: fake WebSocket server from test_cc_home_assistant (no network, no Tk)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import home_assistant as ha_module  # noqa: E402

import test_cc_home_assistant as base  # noqa: E402
from test_cc_home_assistant import AdapterCase, FakeServer, light_state, wait_for  # noqa: E402

setUpModule = base.setUpModule          # never a real WebSocket / HTTP session
tearDownModule = base.tearDownModule


class OddEventServer(FakeServer):
    """Right after the state_changed subscription it sends one event in a shape the adapter trips on."""

    def handle(self, socket, message):
        super().handle(socket, message)
        if message.get("type") == "subscribe_events" and message.get("event_type") == "state_changed":
            odd = light_state(True)
            odd["odd_shape"] = True
            socket.push({"id": message["id"], "type": "event",
                         "event": {"event_type": "state_changed",
                                   "data": {"entity_id": odd["entity_id"], "new_state": odd}}})


class SessionBugBackoffTests(AdapterCase):
    def attempts_with(self, server, adapter_patch=None, cycles=4):
        seen = []

        def recorded(attempt):
            seen.append(attempt)
            return 0.02
        with patch.object(ha_module, "reconnect_delay", recorded):
            adapter = self.make(server, rest_poll=0.01)
            if adapter_patch:
                adapter_patch(adapter)
            adapter.start()
            self.assertTrue(wait_for(lambda: len(seen) >= cycles, timeout=3))
            adapter.close()
        return seen[:cycles]

    def test_a_bug_after_the_first_states_keeps_backing_off(self):
        def patch_store(adapter):
            store = adapter._store

            def broken(state):
                if isinstance(state, dict) and state.get("odd_shape"):
                    raise TypeError("unexpected state shape")
                return store(state)
            adapter._store = broken
        self.assertEqual(self.attempts_with(OddEventServer(), patch_store), [0, 1, 2, 3])

    def test_a_network_drop_of_a_healthy_session_still_resets(self):
        server = FakeServer()
        seen = []

        def recorded(attempt):
            seen.append(attempt)
            return 0.02
        with patch.object(ha_module, "reconnect_delay", recorded):
            adapter = self.make(server, rest_poll=0.01)
            adapter.start()
            for drop in range(3):
                self.assertTrue(wait_for(lambda: len(server.sockets) == drop + 1
                                         and adapter.read_state()["transport"] == "ws"))
                server.sockets[-1].close()                       # ConnectionError("closed")
                self.assertTrue(wait_for(lambda: len(seen) == drop + 1))
            adapter.close()
        self.assertEqual(seen[:3], [0, 0, 0])


if __name__ == "__main__":
    unittest.main()
