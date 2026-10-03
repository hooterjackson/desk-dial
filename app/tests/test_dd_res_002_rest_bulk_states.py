"""DD-RES-002: the REST fallback's request count does not grow with the area.

While the WebSocket is down the reader polls REST. One poll reads every state with ONE GET
/api/states (not one GET per light / scene), renders the admin-only area template at most every
REGISTRY_POLL_SECONDS, and the poll stretches 2 s -> 10 s after repeated WebSocket failures.
Offline fakes and a fake clock only.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import home_assistant as ha_module  # noqa: E402
from control_center.home_assistant import HomeAssistantAdapter  # noqa: E402
from test_cc_home_assistant import FakeHttp, light_state  # noqa: E402

BASE = "http://homeassistant.local:8123"


def area_states(lights=30, scenes=20):
    states = []
    for n in range(lights):
        state = light_state(brightness=100 + n)
        state["entity_id"] = f"light.hall_{n:02d}"
        states.append(state)
    for n in range(scenes):
        states.append({"entity_id": f"scene.hall_{n:02d}", "state": "2026-09-28",
                       "attributes": {"friendly_name": f"Hall scene {n:02d}", "entity_id": ["light.hall_00"]}})
    return states


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class RestBulkTests(unittest.TestCase):
    def make_area(self):
        states = area_states()
        http = FakeHttp(states=states)
        http.template_answer = json.dumps({"known": True, "name": "Hall",
                                           "lights": [s["entity_id"] for s in states if s["entity_id"].startswith("light.")],
                                           "extras": [s["entity_id"] for s in states if s["entity_id"].startswith("scene.")]})
        clock = Clock()
        adapter = HomeAssistantAdapter(BASE, "t0k", "", area_id="hall", http=http, clock=clock,
                                       ws_factory=lambda url, timeout: None)
        self.addCleanup(adapter.close)
        return adapter, http, clock

    def test_rest_refresh_request_count_is_independent_of_area_size(self):
        adapter, http, clock = self.make_area()
        self.assertTrue(adapter._rest_refresh())
        self.assertLessEqual(len(http.requests), 2, [r[:2] for r in http.requests])
        state = adapter.read_state()
        self.assertTrue(state["online"], state)
        self.assertEqual(state["count"], 30)
        self.assertEqual(len(state["scenes"]), ha_module.SCENES_MAX)
        # The next polls inside REGISTRY_POLL_SECONDS: one request each; a 30 s window at 2 s is
        # at most 2 * 30 / 2 requests (here 1 per poll plus nothing for the template).
        http.requests.clear()
        for _ in range(15):
            clock.now += ha_module.REST_POLL_SECONDS
            adapter._rest_refresh()
        self.assertLessEqual(len(http.requests), 2 * 30 / ha_module.REST_POLL_SECONDS)
        self.assertEqual(len([r for r in http.requests if r[1].endswith("/api/template")]), 0)
        self.assertEqual({r[1] for r in http.requests}, {BASE + "/api/states"})
        # The template is rendered again once REGISTRY_POLL_SECONDS have passed.
        clock.now += ha_module.REGISTRY_POLL_SECONDS
        http.requests.clear()
        adapter._rest_refresh()
        self.assertEqual([r[1] for r in http.requests], [BASE + "/api/template", BASE + "/api/states"])

    def test_a_light_gone_from_the_bulk_read_leaves_the_aggregate(self):
        adapter, http, clock = self.make_area()
        adapter._rest_refresh()
        del http.states["light.hall_29"]
        clock.now += 2
        adapter._rest_refresh()
        rows = {row["entity_id"]: row for row in adapter.read_state()["lights"]}
        self.assertFalse(rows["light.hall_29"]["available"])

    def test_a_small_single_light_setup_reads_its_entities(self):
        http = FakeHttp()
        adapter = HomeAssistantAdapter(BASE, "t0k", "light.hall", ws_factory=lambda url, timeout: None, http=http)
        self.addCleanup(adapter.close)
        adapter._rest_refresh()
        self.assertEqual([r[1] for r in http.requests],
                         [BASE + "/api/states/light.hall", BASE + "/api/states/scene.desk_dial_snapshot"])

    def test_the_poll_stretches_after_repeated_websocket_failures(self):
        adapter = HomeAssistantAdapter(BASE, "t0k", "light.hall", http=FakeHttp())
        self.assertEqual([adapter._rest_poll_for(n) for n in range(5)], [2.0, 2.0, 2.0, 10.0, 10.0])


if __name__ == "__main__":
    unittest.main()
