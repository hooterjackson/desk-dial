"""DD-BUG-010: a non-admin Home Assistant user is not a revoked token.

Home Assistant's POST /api/template is admin-only (401 for a non-admin user). While the WebSocket
is down the REST fallback asks it for the area; that refusal must read as "template unavailable"
(keep the area as last read), not as "Home Assistant refused the token". Offline fakes only.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import home_assistant as ha_module  # noqa: E402
from control_center.home_assistant import HomeAssistantAdapter  # noqa: E402

BASE = "http://homeassistant.local:8123"


def light(entity, on=True, brightness=128):
    return {"entity_id": entity, "state": "on" if on else "off",
            "attributes": {"friendly_name": entity, "brightness": brightness if on else None,
                           "supported_color_modes": ["brightness"]}}


class Response:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload

    def json(self):
        return self._payload


class NonAdminHttp:
    """A non-admin token: every read works, the template API answers 401."""

    def __init__(self, states):
        self.states = {s["entity_id"]: s for s in states}
        self.requests = []

    def get(self, url, headers=None, timeout=None, allow_redirects=True):
        path = url[len(BASE):]
        self.requests.append(("GET", path))
        if path in ("/api/", "/api/config"):
            return Response(200, {"message": "API running."})
        if path == "/api/states":
            return Response(200, list(self.states.values()))
        entity = path.rsplit("/", 1)[1]
        return Response(200, self.states[entity]) if entity in self.states else Response(404, {})

    def post(self, url, headers=None, data=None, timeout=None, allow_redirects=True):
        path = url[len(BASE):]
        self.requests.append(("POST", path))
        if path == "/api/template":
            return Response(401, {"message": "Unauthorized"})
        return Response(200, list(self.states.values()))


class TemplateAdminOnlyTests(unittest.TestCase):
    def make(self, http):
        adapter = HomeAssistantAdapter(BASE, "t0k", "", area_id="hall", http=http,
                                       ws_factory=lambda url, timeout: None)
        self.addCleanup(adapter.close)
        return adapter

    def test_rest_fallback_with_admin_only_template_refused_stays_online(self):
        http = NonAdminHttp([light("light.den_desk"), light("light.den_floor", brightness=64)])
        adapter = self.make(http)
        # The WebSocket had resolved the area (registry), then dropped: the REST window begins.
        adapter._set_resolution(True, "Hall", ["light.den_desk", "light.den_floor"], [], {})
        adapter._rest_refresh()
        state = adapter.read_state()
        self.assertNotEqual(state["reason"], "auth")
        self.assertTrue(state["online"], state)
        self.assertEqual((state["name"], state["count"]), ("Hall", 2), "the registry resolution is kept")
        adapter.call_service("light", "turn_on", {"area_id": "hall", "brightness_pct": 40})   # not refused
        self.assertIn(("POST", "/api/services/light/turn_on"), http.requests)

    def test_never_resolved_reads_as_unavailable_not_auth(self):
        adapter = self.make(NonAdminHttp([light("light.den_desk")]))
        adapter._rest_refresh()
        state = adapter.read_state()
        self.assertNotEqual(state["reason"], "auth")
        self.assertEqual(state["detail"], "registry")

    def test_a_401_from_the_states_api_is_still_a_refused_token(self):
        class Revoked(NonAdminHttp):
            def get(self, url, **kwargs):
                return Response(401, {})
        adapter = self.make(Revoked([]))
        adapter._set_resolution(True, "Hall", ["light.den_desk"], [], {})
        adapter._rest_refresh()
        self.assertEqual(adapter.read_state()["reason"], "auth")

    def test_settings_says_the_area_list_needs_the_websocket_or_an_admin_token(self):
        adapter = self.make(NonAdminHttp([light("light.den_desk")]))
        with patch.object(ha_module, "_default_ws_factory", lambda: None):
            result = adapter.test_connection()
        self.assertTrue(result["ok"])
        self.assertEqual(result["areas"], [])
        self.assertEqual(result["areas_note"], ha_module.AREAS_NEED_ADMIN)
        self.assertIn("admin", result["areas_note"])
        self.assertNotIn("t0k", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
