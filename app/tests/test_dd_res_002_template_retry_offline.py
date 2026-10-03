"""DD-RES-002 review: an offline area-template attempt does not hold the next one back 60 s.

A REST-only setup that starts while Home Assistant is unreachable has never resolved its area.
Once Home Assistant answers again, the area resolves on the very next poll, not after
REGISTRY_POLL_SECONDS. A successful template still waits REGISTRY_POLL_SECONDS. Offline fakes only.
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


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_area(test):
    state = light_state()
    state["entity_id"] = "light.office_lamp"
    http = FakeHttp(states=[state])
    http.template_answer = json.dumps({"known": True, "name": "Office",
                                       "lights": ["light.office_lamp"], "extras": []})
    clock = Clock()
    adapter = HomeAssistantAdapter(BASE, "t0k", "", area_id="office", http=http, clock=clock,
                                   ws_factory=lambda url, timeout: None)
    test.addCleanup(adapter.close)
    return adapter, http, clock


class TemplateRetryAfterOffline(unittest.TestCase):
    def test_area_resolves_on_the_next_poll_after_recovery(self):
        adapter, http, clock = make_area(self)
        http.fail = True
        adapter._rest_refresh()
        self.assertFalse(adapter.read_state()["online"])
        http.fail = False
        clock.now += ha_module.REST_POLL_SECONDS
        http.requests.clear()
        self.assertTrue(adapter._rest_refresh())
        self.assertIn(BASE + "/api/template", [r[1] for r in http.requests])
        state = adapter.read_state()
        self.assertTrue(state["online"], state)
        self.assertEqual(state["count"], 1)
        self.assertEqual(state["entities"], ["light.office_lamp"])

    def test_a_template_5xx_is_retried_on_the_next_poll(self):
        adapter, http, clock = make_area(self)
        calls = []
        real = adapter._rest

        def failing_rest(method, path, body=None):
            if path == "/api/template" and not calls:
                calls.append(path)
                raise ha_module.HomeAssistantError("Home Assistant answered 503", "offline", 503)
            return real(method, path, body)

        adapter._rest = failing_rest
        adapter._rest_refresh()
        self.assertFalse(adapter.read_state()["online"])
        clock.now += ha_module.REST_POLL_SECONDS
        http.requests.clear()
        adapter._rest_refresh()
        self.assertIn(BASE + "/api/template", [r[1] for r in http.requests])
        self.assertTrue(adapter.read_state()["online"])

    def test_a_successful_template_still_waits_the_registry_poll(self):
        adapter, http, clock = make_area(self)
        self.assertTrue(adapter._rest_refresh())
        clock.now += ha_module.REST_POLL_SECONDS
        http.requests.clear()
        adapter._rest_refresh()
        self.assertNotIn(BASE + "/api/template", [r[1] for r in http.requests])


if __name__ == "__main__":
    unittest.main()
