"""DD-RES-003: the REST fallback does not report Lights online when every request failed.

Home Assistant behind a reverse proxy restarts: the proxy answers 502 / 503 to everything (and, while
Home Assistant loads, the states answer 404). A REST poll goes online only when a state read came
back; otherwise Lights are offline (5xx) or unavailable (all 404). Offline fakes and a fake clock.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import home_assistant as ha_module  # noqa: E402
from control_center.home_assistant import HomeAssistantAdapter  # noqa: E402
from test_cc_home_assistant import FakeHttp, FakeResponse, light_state  # noqa: E402

BASE = "http://homeassistant.local:8123"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class BadGatewayHttp(FakeHttp):
    """FakeHttp that can answer one status (502, 404) to every request."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.broken = None

    def get(self, url, **kwargs):
        if self.broken is not None:
            self.requests.append(("GET", url, None, None, False))
            return FakeResponse(self.broken, {})
        return super().get(url, **kwargs)

    def post(self, url, **kwargs):
        if self.broken is not None:
            self.requests.append(("POST", url, None, None, False))
            return FakeResponse(self.broken, {})
        return super().post(url, **kwargs)


class RestFailureStatusTests(unittest.TestCase):
    def area(self):
        state = light_state()
        state["entity_id"] = "light.hall_desk"
        http = BadGatewayHttp(states=[state])
        http.template_answer = json.dumps({"known": True, "name": "Hall", "lights": ["light.hall_desk"], "extras": []})
        clock = Clock()
        adapter = HomeAssistantAdapter(BASE, "t0k", "", area_id="hall", http=http, clock=clock,
                                       ws_factory=lambda url, timeout: None)
        self.addCleanup(adapter.close)
        return adapter, http, clock

    def single(self):
        http = BadGatewayHttp()
        adapter = HomeAssistantAdapter(BASE, "t0k", "light.hall", http=http, ws_factory=lambda url, timeout: None)
        self.addCleanup(adapter.close)
        return adapter, http

    def test_rest_refresh_all_5xx_reports_offline(self):
        adapter, http, clock = self.area()
        self.assertTrue(adapter._rest_refresh())
        self.assertTrue(adapter.read_state()["online"])
        http.broken = 502
        clock.now += 2                                   # template not due: the states read fails
        adapter._rest_refresh()
        state = adapter.read_state()
        self.assertFalse(state["online"])
        self.assertTrue(state["reason"])
        self.assertEqual(state["reason"], "offline")

    def test_a_5xx_from_the_template_is_offline(self):
        adapter, http, clock = self.area()
        adapter._rest_refresh()
        http.broken = 503
        clock.now += ha_module.REGISTRY_POLL_SECONDS     # the template is due again
        adapter._rest_refresh()
        self.assertEqual((adapter.read_state()["online"], adapter.read_state()["reason"]), (False, "offline"))
        self.assertTrue(http.requests[-1][1].endswith("/api/template"), "nothing else is asked once it is down")

    def test_single_light_all_5xx_is_offline_and_all_404_is_unavailable(self):
        adapter, http = self.single()
        self.assertTrue(adapter._rest_refresh())
        self.assertTrue(adapter.read_state()["online"])
        http.broken = 502
        self.assertFalse(adapter._rest_refresh())
        self.assertEqual((adapter.read_state()["online"], adapter.read_state()["reason"]), (False, "offline"))
        http.broken = 404
        self.assertFalse(adapter._rest_refresh())
        self.assertEqual((adapter.read_state()["online"], adapter.read_state()["reason"]), (False, "unavailable"))
        http.broken = None
        self.assertTrue(adapter._rest_refresh())
        self.assertTrue(adapter.read_state()["online"], "back online once a read answers again")


if __name__ == "__main__":
    unittest.main()
