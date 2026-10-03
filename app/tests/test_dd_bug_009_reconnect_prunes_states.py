"""DD-BUG-009: a (re)connect's get_states replaces the stored states instead of merging them, so an
entity removed while the socket was down (Desk Dial's scene.create snapshot lost to a Home Assistant
restart, a deleted scene) is forgotten; Turn on then uses light.turn_on, not a missing snapshot. The
REST fallback forgets a snapshot that answers 404 (or is missing from /api/states) too.

Offline: fake WebSocket server and fake HTTP session from test_cc_home_assistant (no network)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import home_assistant as ha_module  # noqa: E402
from control_center.home_assistant import HomeAssistantAdapter  # noqa: E402

import test_cc_home_assistant as base  # noqa: E402
from test_cc_home_assistant import (SCENES, TOKEN, AdapterCase, AreaCase, FakeHttp, light_state,  # noqa: E402
                                    scene_state, wait_for)

setUpModule = base.setUpModule          # never a real WebSocket / HTTP session
tearDownModule = base.tearDownModule

SNAPSHOT = "scene.desk_dial_snapshot"


class ReconnectPrunesTests(AdapterCase):
    def reconnect(self, adapter):
        count = len(self.server.sockets)
        self.server.sockets[-1].close()
        self.assertTrue(wait_for(lambda: len(self.server.sockets) > count
                                 and adapter.read_state()["transport"] == "ws"
                                 and adapter.read_state()["online"]))

    def test_a_restart_that_lost_the_snapshot_turns_the_area_on(self):
        with patch.object(ha_module, "BACKOFF", (0.02,)):
            adapter = self.make()
            adapter.start()
            self.assertTrue(wait_for(lambda: adapter.read_state()["online"]))
            adapter.power(False)
            self.assertTrue(adapter.read_state()["snapshot"])
            # Home Assistant restarts: scene.create scenes are not persisted and no removal event
            # reached Desk Dial while the socket was down.
            self.server.states.pop(SNAPSHOT, None)
            self.reconnect(adapter)
            self.assertTrue(wait_for(lambda: adapter.read_state()["snapshot"] is False))
        adapter.power(True)
        self.assertEqual(self.server.calls[-1], ("light", "turn_on", {}, {"entity_id": "light.den"}))

    def test_a_snapshot_still_there_after_a_reconnect_is_kept(self):
        with patch.object(ha_module, "BACKOFF", (0.02,)):
            adapter = self.make()
            adapter.start()
            self.assertTrue(wait_for(lambda: adapter.read_state()["online"]))
            adapter.power(False)
            self.server.states[SNAPSHOT] = scene_state(SNAPSHOT, "desk dial", ["light.den"])
            self.reconnect(adapter)
        self.assertTrue(adapter.read_state()["snapshot"])
        adapter.power(True)
        self.assertEqual(self.server.calls[-1], ("scene", "turn_on", {}, {"entity_id": SNAPSHOT}))

    def test_a_scene_deleted_while_offline_is_forgotten(self):
        with patch.object(ha_module, "BACKOFF", (0.02,)):
            adapter = self.make()
            adapter.start()
            self.assertTrue(wait_for(lambda: adapter.read_state()["online"]))
            self.assertIn("scene.focus", adapter._states)
            del self.server.states["scene.focus"]
            self.reconnect(adapter)
            self.assertTrue(wait_for(lambda: "scene.focus" not in adapter._states))
        self.assertIn("light.den", adapter._states)


class AreaReconnectTests(AreaCase):
    def test_area_mode_forgets_a_lost_snapshot_and_a_deleted_scene(self):
        with patch.object(ha_module, "BACKOFF", (0.02,)), patch.object(ha_module, "RECV_TIMEOUT", 0.02):
            adapter = self.started()
            adapter.power(False)
            self.assertTrue(adapter.read_state()["snapshot"])
            self.assertIn("scene.den_relax", [s["entity_id"] for s in adapter.read_state()["scenes"]])
            self.server.states.pop(SNAPSHOT, None)
            del self.server.states["scene.den_relax"]       # deleted: gone from the registry too
            self.server.entities = [e for e in self.server.entities if e["entity_id"] != "scene.den_relax"]
            self.server.sockets[-1].close()
            self.assertTrue(wait_for(lambda: len(self.server.sockets) >= 2
                                     and adapter.read_state()["transport"] == "ws"
                                     and adapter.read_state()["snapshot"] is False))
        self.assertTrue(wait_for(lambda: "scene.den_relax" not in adapter._states))
        self.assertNotIn("scene.den_relax", [s["entity_id"] for s in adapter.read_state()["scenes"]])
        adapter.power(True)
        self.assertEqual(self.server.calls[-1], ("light", "turn_on", {}, {"area_id": "hall"}))


class RestForgetsTheSnapshotTests(unittest.TestCase):
    def adapter(self, http, scenes=()):
        # No scenes: two watched entities, read one by one (REST_EACH_MAX).
        adapter = HomeAssistantAdapter("http://homeassistant.local:8123", TOKEN, "light.den", scenes,
                                       ws_factory=lambda url, timeout: None, http=http, rest_poll=0.02)
        self.addCleanup(adapter.close)
        return adapter

    def test_a_404_for_the_snapshot_clears_it(self):
        http = FakeHttp(states=[light_state()])
        adapter = self.adapter(http)
        with adapter._lock:
            adapter._snapshot, adapter._snapshot_members = True, ["light.den"]
        self.assertTrue(adapter._rest_refresh())
        self.assertFalse(adapter.read_state()["snapshot"])

    def test_a_404_while_nothing_answers_keeps_it(self):
        http = FakeHttp(states=[{"entity_id": "light.other", "state": "on", "attributes": {}}])
        adapter = self.adapter(http)
        with adapter._lock:
            adapter._snapshot = True
        self.assertFalse(adapter._rest_refresh())          # Home Assistant still loading
        self.assertTrue(adapter._snapshot)

    def test_the_bulk_read_forgets_a_snapshot_it_does_not_list(self):
        http = FakeHttp(states=[light_state(), {"entity_id": "scene.focus", "state": "x", "attributes": {}},
                                {"entity_id": "script.movie", "state": "off", "attributes": {}},
                                {"entity_id": "automation.wake", "state": "on", "attributes": {}}])
        adapter = self.adapter(http, SCENES)          # five watched entities: one GET /api/states
        with adapter._lock:
            adapter._snapshot = True
        with patch.object(ha_module, "REST_EACH_MAX", 1):   # more entities than read one by one
            self.assertTrue(adapter._rest_refresh())
        self.assertFalse(adapter.read_state()["snapshot"])


if __name__ == "__main__":
    unittest.main()
