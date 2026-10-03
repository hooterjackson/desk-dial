"""HomeAssistantAdapter (Desk Dial r3 release 1, README section 7; r3.1 area bridge) against a fake
WebSocket server and a fake HTTP session: auth, the subscriptions, call_service, the allowlist guard,
reconnect with backoff, the REST fallback, the <= 10 Hz spacing, read_state never raising and the token
never logged; r3.1: the area resolution from the registries, live registry updates (a light added to
the Hall appears without a restart), the aggregate state, area-targeted commands, the area-scoped
allowlist and auto scenes, checked replies, the frame-id race, the REST template fallback, the
status.json view and the Settings area probe.

Offline: no socket, no Home Assistant, no credential store (the store is an in-memory fake). The module
patches the adapter's real WebSocket / HTTP factories so no test can ever reach a real Home Assistant.
"""
import json
import logging
import queue
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import home_assistant as ha_module  # noqa: E402
from control_center.home_assistant import (HomeAssistantAdapter, HomeAssistantError, build_adapter,  # noqa: E402
                                           entity_lists, kelvin_bounds, light_facts, load_token,
                                           normalize_base_url, normalize_scenes, save_token, websocket_url)

_REAL_FACTORY_CALLS = []


def setUpModule():
    """Never the user's Home Assistant: the real WebSocket library reads as missing and a real
    HTTP session cannot be made (every adapter here gets fakes; a slip fails loudly)."""
    def no_ws():
        _REAL_FACTORY_CALLS.append("ws")
        return None

    def no_http(*_args):
        _REAL_FACTORY_CALLS.append("http")
        raise AssertionError("a real HTTP session was requested in a test")
    for name, value in (("_default_ws_factory", no_ws), ("_default_http", no_http)):
        patcher = patch.object(ha_module, name, value)
        patcher.start()
        unittest.addModuleCleanup(patcher.stop)


def tearDownModule():
    if "http" in _REAL_FACTORY_CALLS:   # _rest turns any session failure into "offline": check here
        raise AssertionError("a test asked for a real HTTP session")

TOKEN = "secret-token-abc123"
SCENES = [{"entity_id": "scene.focus", "label": "Focus"}, {"entity_id": "script.movie", "type": "script"},
          {"entity_id": "automation.wake", "type": "automation", "label": "Wake"}]


def light_state(on=True, brightness=158, kelvin=3200, **attributes):
    attrs = {"friendly_name": "Hall lights", "brightness": brightness if on else None, "color_temp_kelvin": kelvin,
             "min_color_temp_kelvin": 2000, "max_color_temp_kelvin": 6535, "supported_color_modes": ["color_temp"]}
    attrs.update(attributes)
    return {"entity_id": "light.den", "state": "on" if on else "off", "attributes": attrs}


class FakeSocket:
    def __init__(self, server):
        self.server = server
        self.inbox = queue.Queue()
        self.sent = []
        self.closed = False
        self.timeout = 5.0
        self.last_id = 0
        self.id_errors = []

    def send(self, text):
        if self.closed:
            raise ConnectionError("closed")
        message = json.loads(text)
        self.sent.append(message)
        ident = message.get("id")
        if ident is not None:
            # Home Assistant refuses an id that does not increase (websocket_api "id_reuse").
            if ident <= self.last_id:
                self.id_errors.append(ident)
                self.push({"id": ident, "type": "result", "success": False,
                           "error": {"code": "id_reuse", "message": "Identifier values have to increase."}})
                return
            self.last_id = ident
        self.server.handle(self, message)

    def recv(self):
        try:
            return self.inbox.get(timeout=self.timeout)
        except queue.Empty:
            raise TimeoutError("timeout") from None

    def settimeout(self, value):
        self.timeout = value

    def close(self):
        self.closed = True
        self.inbox.put("")

    def push(self, message):
        self.inbox.put(json.dumps(message))


class FakeServer:
    """Home Assistant's WebSocket API, as much of it as the adapter uses."""

    def __init__(self, token=TOKEN, states=None, answer_pings=True):
        self.token = token
        self.states = {s["entity_id"]: s for s in (states or [light_state(),
                                                                {"entity_id": "scene.focus", "state": "2026-09-28",
                                                                 "attributes": {"friendly_name": "Focus"}}])}
        self.sockets = []
        self.urls = []
        self.calls = []
        self.subscription = None
        self.answer_pings = answer_pings
        self.refuse_connect = False

    def connect(self, url, timeout):
        if self.refuse_connect:
            raise ConnectionRefusedError("down")
        self.urls.append(url)
        socket = FakeSocket(self)
        self.sockets.append(socket)
        socket.push({"type": "auth_required", "ha_version": "2026.9.0"})
        return socket

    def handle(self, socket, message):
        kind = message.get("type")
        if kind == "auth":
            socket.push({"type": "auth_ok" if message.get("access_token") == self.token else "auth_invalid"})
        elif kind == "get_states":
            socket.push({"id": message["id"], "type": "result", "success": True, "result": list(self.states.values())})
        elif kind == "subscribe_events":
            self.subscription = message["id"]
            socket.push({"id": message["id"], "type": "result", "success": True, "result": None})
        elif kind == "ping":
            if self.answer_pings:
                socket.push({"id": message["id"], "type": "pong"})
        elif kind == "call_service":
            self.calls.append((message["domain"], message["service"], message.get("service_data"),
                               message.get("target")))
            socket.push({"id": message["id"], "type": "result", "success": True, "result": {"context": {}}})
            if message["domain"] == "light":
                data = message.get("service_data") or {}
                on = message["service"] == "turn_on"
                old = self.states["light.den"]["attributes"]
                new = light_state(on, brightness=round(data.get("brightness_pct", round(old.get("brightness") or 158)
                                                                * 100 / 255) * 255 / 100),
                                  kelvin=data.get("color_temp_kelvin", old.get("color_temp_kelvin")))
                self.change(new)

    def change(self, state):
        self.states[state["entity_id"]] = state
        for socket in self.sockets:
            if not socket.closed and self.subscription is not None:
                socket.push({"id": self.subscription, "type": "event",
                             "event": {"event_type": "state_changed",
                                       "data": {"entity_id": state["entity_id"], "new_state": state}}})


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class FakeHttp:
    def __init__(self, states=None, status=200, fail=False):
        self.states = {s["entity_id"]: s for s in (states or [light_state()])}
        self.status = status
        self.fail = fail
        self.requests = []
        self.template_answer = None       # the area template's rendered JSON (POST /api/template)
        self.areas_answer = None          # the areas() template's rendered JSON
        self.refuse_hidden_test = False   # an older HA without is_hidden_entity

    def get(self, url, headers=None, timeout=None, allow_redirects=True):
        self.requests.append(("GET", url, headers, None, allow_redirects))
        if self.fail:
            raise ConnectionError("no route")
        path = url.split("8123", 1)[1]
        if path == "/api/":
            return FakeResponse(self.status, {"message": "API running."})
        if path == "/api/states":
            return FakeResponse(self.status, list(self.states.values()))
        entity = path.rsplit("/", 1)[1]
        if entity not in self.states:
            return FakeResponse(404, {})
        return FakeResponse(self.status, self.states[entity])

    def post(self, url, headers=None, data=None, timeout=None, allow_redirects=True):
        body = json.loads(data)
        self.requests.append(("POST", url, headers, body, allow_redirects))
        if self.fail:
            raise ConnectionError("no route")
        if url.endswith("/api/template"):
            template = body.get("template", "")
            answer = self.areas_answer if "areas()" in template else self.template_answer
            if answer is None or (self.refuse_hidden_test and "is_hidden_entity" in template):
                return FakeResponse(400, {"message": "Error rendering template"})
            return FakeResponse(self.status, answer)
        return FakeResponse(self.status, [])


def wait_for(condition, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


class AdapterCase(unittest.TestCase):
    def make(self, server=None, http=None, token=TOKEN, **kwargs):
        self.server = server or FakeServer()
        adapter = HomeAssistantAdapter("http://homeassistant.local:8123", token, "light.den", SCENES,
                                       ws_factory=self.server.connect, http=http or FakeHttp(), **kwargs)
        self.addCleanup(adapter.close)
        return adapter


class ConnectionTests(AdapterCase):
    def test_auth_subscribe_and_state(self):
        states = []
        adapter = self.make()
        adapter.set_listener(states.append)
        adapter.start()
        self.assertTrue(wait_for(lambda: adapter.read_state()["online"]))
        self.assertEqual(self.server.urls, ["ws://homeassistant.local:8123/api/websocket"])
        state = adapter.read_state()
        self.assertEqual((state["on"], state["bri"], state["kelvin"], state["min_k"], state["max_k"], state["name"]),
                         (True, 62, 3200, 2200, 6500, "Hall lights"))
        self.assertEqual([s["label"] for s in state["scenes"]], ["Focus", "movie", "Wake"])
        self.assertEqual(state["transport"], "ws")
        self.assertTrue(states and states[-1]["online"], "the listener hears the first full state")
        sent = self.server.sockets[0].sent
        self.assertEqual([m["type"] for m in sent[:3]], ["auth", "get_states", "subscribe_events"])
        self.assertNotIn(TOKEN, json.dumps(state), "read_state never carries the token")

    def test_state_changes_are_pushed(self):
        seen = []
        adapter = self.make()
        adapter.set_listener(lambda s: seen.append(s.get("bri")))
        adapter.start()
        self.assertTrue(wait_for(lambda: adapter.read_state()["online"]))
        self.server.change(light_state(brightness=26))
        self.assertTrue(wait_for(lambda: adapter.read_state()["bri"] == 10))
        self.assertIn(10, seen)
        # Entities that are not configured are ignored.
        self.server.change({"entity_id": "light.kitchen", "state": "on", "attributes": {}})
        time.sleep(0.05)
        self.assertEqual(adapter.read_state()["entity"], "light.den")

    def test_auth_invalid(self):
        adapter = self.make(token="wrong-token")
        with patch.object(ha_module, "AUTH_BACKOFF", 30.0):
            adapter.start()
            self.assertTrue(wait_for(lambda: adapter.read_state()["reason"] == "auth"))
        self.assertFalse(adapter.read_state()["online"])
        with self.assertRaises(HomeAssistantError) as caught:
            adapter.set_light(bri=40)
        self.assertEqual(caught.exception.outcome, "auth")

    def test_the_token_is_never_logged(self):
        records = []

        class Keep(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())
        handler = Keep(level=logging.DEBUG)
        logger = logging.getLogger("control_center.home_assistant")
        logger.addHandler(handler)
        old_level = logger.level
        logger.setLevel(logging.DEBUG)
        self.addCleanup(lambda: (logger.removeHandler(handler), logger.setLevel(old_level)))
        with patch.object(ha_module, "BACKOFF", (0.02,)):
            adapter = self.make()
            adapter.start()
            self.assertTrue(wait_for(lambda: adapter.read_state()["online"]))
            self.server.sockets[0].close()          # a drop is logged (by exception type only)
            self.assertTrue(wait_for(lambda: len(self.server.sockets) >= 2))
            try:
                adapter.call_service("switch", "turn_on", {"entity_id": "switch.kettle"})
            except HomeAssistantError:
                pass
        self.assertTrue(records)
        self.assertFalse([r for r in records if TOKEN in r])

    def test_reconnects_with_a_fresh_socket_after_a_drop(self):
        with patch.object(ha_module, "BACKOFF", (0.02, 0.05)):
            adapter = self.make()
            adapter.start()
            self.assertTrue(wait_for(lambda: adapter.read_state()["online"]))
            first = self.server.sockets[0]
            first.close()
            self.assertTrue(wait_for(lambda: len(self.server.sockets) == 2 and adapter.read_state()["transport"] == "ws"))
        self.assertIsNot(self.server.sockets[1], first, "the old socket is never reused")
        self.assertTrue(first.closed)

    def test_a_missing_pong_reconnects(self):
        server = FakeServer(answer_pings=False)
        with patch.object(ha_module, "PING_SECONDS", 0.05), patch.object(ha_module, "PONG_TIMEOUT", 0.1), \
                patch.object(ha_module, "RECV_TIMEOUT", 0.02), patch.object(ha_module, "BACKOFF", (0.02,)):
            adapter = self.make(server)
            adapter.start()
            self.assertTrue(wait_for(lambda: len(server.sockets) >= 2, timeout=5))
        self.assertIn("ping", [m["type"] for m in server.sockets[0].sent])

    def test_rest_fallback_without_websocket(self):
        http = FakeHttp()
        adapter = HomeAssistantAdapter("http://homeassistant.local:8123", TOKEN, "light.den", SCENES,
                                       ws_factory=lambda url, timeout: None, http=http, rest_poll=0.02)
        self.addCleanup(adapter.close)
        with patch.object(ha_module, "BACKOFF", (0.05,)):
            adapter.start()
            self.assertTrue(wait_for(lambda: adapter.read_state()["online"]))
        self.assertEqual(adapter.read_state()["transport"], "rest")
        adapter.set_light(bri=40)
        post = [r for r in http.requests if r[0] == "POST"][-1]
        self.assertEqual(post[1], "http://homeassistant.local:8123/api/services/light/turn_on")
        self.assertEqual(post[3], {"entity_id": "light.den", "brightness_pct": 40, "transition": 0.4})
        self.assertEqual(post[2]["Authorization"], "Bearer " + TOKEN)
        self.assertFalse(post[4], "redirects are never followed")

    def test_offline_when_nothing_answers(self):
        server = FakeServer()
        server.refuse_connect = True
        with patch.object(ha_module, "BACKOFF", (0.05,)):
            adapter = self.make(server, http=FakeHttp(fail=True), rest_poll=0.02)
            adapter.start()
            self.assertTrue(wait_for(lambda: adapter.read_state()["reason"] == "offline"))
        self.assertFalse(adapter.read_state()["online"])


class ServiceTests(AdapterCase):
    def setUp(self):
        self.adapter = self.make()
        self.adapter.start()
        self.assertTrue(wait_for(lambda: self.adapter.read_state()["online"]))

    def test_brightness_and_temperature_calls(self):
        result = self.adapter.set_light(bri=40)
        self.assertEqual(self.server.calls[-1], ("light", "turn_on", {"brightness_pct": 40, "transition": 0.4},
                                                 {"entity_id": "light.den"}))
        self.assertEqual(result["_applied"], {"bri": 40, "kelvin": None})
        self.adapter.set_light(kelvin=3456)
        self.assertEqual(self.server.calls[-1][2], {"color_temp_kelvin": 3500, "transition": 0.4}, "100 K steps")
        self.adapter.set_light(kelvin=9000)
        self.assertEqual(self.server.calls[-1][2], {"color_temp_kelvin": 6500, "transition": 0.4}, "clamped to the group's range")

    def test_turn_on_by_temperature_uses_the_stored_level(self):
        self.server.change(light_state(on=False))
        self.assertTrue(wait_for(lambda: not self.adapter.read_state()["on"]))
        self.adapter.set_light(kelvin=2700, on_bri=35)
        self.assertEqual(self.server.calls[-1][2], {"color_temp_kelvin": 2700, "brightness_pct": 35, "transition": 0.4})

    def test_all_off_is_a_snapshot_then_off_and_turn_on_restores_it(self):
        self.adapter.power(False)
        self.assertEqual([c[:2] for c in self.server.calls], [("scene", "create"), ("light", "turn_off")])
        self.assertEqual(self.server.calls[0][2], {"scene_id": "desk_dial_snapshot",
                                                   "snapshot_entities": ["light.den"]})
        self.adapter.power(True)
        self.assertEqual(self.server.calls[-1], ("scene", "turn_on", {}, {"entity_id": "scene.desk_dial_snapshot"}))

    def test_turn_on_without_a_snapshot_turns_the_light_on(self):
        self.adapter.power(True)
        self.assertEqual(self.server.calls[-1], ("light", "turn_on", {}, {"entity_id": "light.den"}))

    def test_scenes_run_by_type(self):
        self.adapter.run_scene("scene.focus")
        self.adapter.run_scene("script.movie")
        self.adapter.run_scene("automation.wake")
        self.assertEqual([c[:2] for c in self.server.calls],
                         [("scene", "turn_on"), ("script", "turn_on"), ("automation", "trigger")])

    def test_the_allowlist_refuses_before_any_io(self):
        before = len(self.server.sockets[0].sent)
        refused = [("light", "turn_on", {"entity_id": "light.kitchen"}),
                   ("light", "turn_on", {"entity_id": "light.den", "rgb_color": [255, 0, 0]}),
                   ("light", "turn_on", {"entity_id": "light.den", "brightness_pct": 0}),
                   ("light", "turn_on", {"entity_id": "light.den", "color_temp_kelvin": 9000}),
                   ("switch", "turn_on", {"entity_id": "switch.kettle"}),
                   ("scene", "turn_on", {"entity_id": "scene.party"}),
                   ("scene", "create", {"scene_id": "other", "snapshot_entities": ["light.den"]}),
                   ("scene", "create", {"scene_id": "desk_dial_snapshot", "snapshot_entities": ["light.den", "lock.door"]}),
                   ("script", "turn_on", {"entity_id": "script.unknown"}),
                   ("script", "turn_on", {"entity_id": "scene.focus"}),
                   ("automation", "trigger", {"entity_id": "script.movie"}),
                   ("homeassistant", "restart", {}),
                   ("lock", "unlock", {"entity_id": "lock.door"})]
        for domain, service, data in refused:
            with self.subTest(call=(domain, service, data)):
                with self.assertRaises(HomeAssistantError) as caught:
                    self.adapter.call_service(domain, service, data)
                self.assertEqual(caught.exception.outcome, "not_allowed")
        self.assertEqual(len(self.server.sockets[0].sent), before, "nothing was sent")
        with self.assertRaises(HomeAssistantError):
            self.adapter.run_scene("scene.party")

    def test_writes_are_spaced_to_ten_per_second(self):
        stamps = []
        original = self.adapter.call_service

        def record(*args):
            stamps.append(time.monotonic())
            return original(*args)
        self.adapter.call_service = record
        for value in (10, 11, 12, 13):
            self.adapter.set_light(bri=value)
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        self.assertTrue(all(gap >= ha_module.WRITE_INTERVAL - 0.01 for gap in gaps), gaps)

    def test_a_failed_call_is_an_error_with_an_outcome(self):
        socket = self.server.sockets[0]
        original = self.server.handle

        def refuse(sock, message):
            if message.get("type") == "call_service":
                sock.push({"id": message["id"], "type": "result", "success": False,
                           "error": {"code": "service_not_found", "message": "x"}})
                return
            original(sock, message)
        self.server.handle = refuse
        with self.assertRaises(HomeAssistantError) as caught:
            self.adapter.set_light(bri=20)
        self.assertEqual(caught.exception.outcome, "unavailable")
        self.assertFalse(socket.closed)


class ReadStateTests(unittest.TestCase):
    def test_read_state_never_raises(self):
        adapter = HomeAssistantAdapter("http://ha.local:8123", TOKEN, "light.den", SCENES)
        adapter._states["light.den"] = light_state()
        adapter._online = True
        with patch.object(ha_module, "light_facts", side_effect=RuntimeError("boom")):
            state = adapter.read_state()
        self.assertEqual((state["online"], state["reason"]), (False, "failed"))

    def test_not_configured(self):
        adapter = HomeAssistantAdapter("", "", "light.den")
        self.assertEqual(adapter.read_state()["reason"], "not_configured")
        adapter.start()
        self.assertIsNone(adapter._thread, "nothing connects without an address and a token")
        with self.assertRaises(HomeAssistantError):
            adapter.set_light(bri=10)

    def test_unavailable_light(self):
        adapter = HomeAssistantAdapter("http://ha.local:8123", TOKEN, "light.den")
        adapter._states["light.den"] = {"entity_id": "light.den", "state": "unavailable", "attributes": {}}
        adapter._online = True
        state = adapter.read_state()
        self.assertEqual((state["online"], state["reason"]), (False, "unavailable"))


class SettingsProbeTests(unittest.TestCase):
    def test_test_connection_is_read_only(self):
        http = FakeHttp(states=[light_state(), {"entity_id": "scene.focus", "state": "x",
                                                "attributes": {"friendly_name": "Focus"}},
                                {"entity_id": "script.movie", "state": "off", "attributes": {}},
                                {"entity_id": "switch.kettle", "state": "off", "attributes": {}},
                                {"entity_id": "scene.desk_dial_snapshot", "state": "x", "attributes": {}}])
        adapter = HomeAssistantAdapter("http://homeassistant.local:8123", TOKEN, "", http=http,
                                       ws_factory=lambda url, timeout: None)
        result = adapter.test_connection()
        self.assertTrue(result["ok"])
        self.assertEqual(result["entities"]["light"], [("light.den", "Hall lights")])
        self.assertEqual(result["entities"]["scene"], [("scene.focus", "Focus")], "Desk Dial's snapshot is hidden")
        self.assertEqual(result["entities"]["script"], [("script.movie", "script.movie")])
        self.assertNotIn("switch", result["entities"])
        writes = [r for r in http.requests if r[0] != "GET" and not r[1].endswith("/api/template")]
        self.assertEqual(writes, [], "never a write (a template render is read-only)")
        self.assertEqual(result["areas"], [], "no area registry and no template answer")

    def test_test_connection_failures(self):
        refused = HomeAssistantAdapter("http://ha.local:8123", TOKEN, "", http=FakeHttp(status=401),
                                       ws_factory=lambda url, timeout: None)
        self.assertEqual(refused.test_connection()["outcome"], "auth")
        down = HomeAssistantAdapter("http://ha.local:8123", TOKEN, "", http=FakeHttp(fail=True),
                                    ws_factory=lambda url, timeout: None)
        result = down.test_connection()
        self.assertEqual((result["ok"], result["outcome"]), (False, "offline"))
        self.assertEqual(HomeAssistantAdapter("http://ha.local:8123", "", "").test_connection()["outcome"],
                         "not_configured")


class HelperTests(unittest.TestCase):
    def test_urls(self):
        self.assertEqual(normalize_base_url(" http://homeassistant.local:8123/ "), "http://homeassistant.local:8123")
        self.assertEqual(websocket_url("https://ha.example.org"), "wss://ha.example.org/api/websocket")
        self.assertEqual(websocket_url("http://10.0.0.5:8123"), "ws://10.0.0.5:8123/api/websocket")
        for bad in ("", "ftp://ha", "homeassistant.local", "http://user:pw@ha.local", "http://ha.local/?x=1"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                normalize_base_url(bad)

    def test_scenes_config(self):
        scenes = normalize_scenes([{"entity_id": "scene.a", "label": " A "}, "script.b",
                                   {"entity_id": "scene.a"}, {"entity_id": "light.x"},
                                   {"entity_id": "script.c", "type": "scene"},
                                   {"entity_id": "automation.d", "bri": 40, "kelvin": 2700}, 7])
        self.assertEqual(scenes, [{"entity_id": "scene.a", "type": "scene", "label": "A"},
                                  {"entity_id": "script.b", "type": "script", "label": ""},
                                  {"entity_id": "automation.d", "type": "automation", "label": "", "bri": 40,
                                   "kelvin": 2700}])

    def test_light_facts(self):
        facts = light_facts(light_state(brightness=255, kelvin=None, color_temp=370))
        self.assertEqual((facts["bri"], facts["kelvin"]), (100, 2700))
        self.assertEqual(light_facts(light_state(on=False))["bri"], 0)
        self.assertEqual(light_facts(light_state(brightness=1))["bri"], 1, "never 0 while on")
        self.assertEqual(kelvin_bounds({"min_color_temp_kelvin": 2702, "max_color_temp_kelvin": 4000}), (2800, 4000))
        self.assertEqual(kelvin_bounds({}), (2200, 6500))
        self.assertFalse(light_facts(light_state(supported_color_modes=["brightness"]))["supports_ct"])

    def test_entity_lists_sorted_by_name(self):
        lists = entity_lists([{"entity_id": "light.b", "attributes": {"friendly_name": "Zeta"}},
                              {"entity_id": "light.a", "attributes": {"friendly_name": "alpha"}},
                              {"entity_id": "bad id"}])
        self.assertEqual(lists["light"], [("light.a", "alpha"), ("light.b", "Zeta")])


class FakeStore:
    def __init__(self, value=None):
        self.value = dict(value or {})

    def load(self):
        return dict(self.value)

    def save(self, credentials):
        self.value = dict(credentials)


class CredentialTests(unittest.TestCase):
    def test_token_lives_in_the_store_beside_musickit(self):
        store = FakeStore({"music_user_token": "m", "team_id": "t"})
        save_token(store, TOKEN)
        self.assertEqual(store.value, {"music_user_token": "m", "team_id": "t", "ha_token": TOKEN})
        self.assertEqual(load_token(store), TOKEN)
        save_token(store, "")
        self.assertNotIn("ha_token", store.value)

    def test_build_adapter_needs_url_light_and_token(self):
        config = {"ha_base_url": "http://ha.local:8123", "ha_light_entity": "light.den",
                  "ha_scenes": [{"entity_id": "scene.focus"}]}
        self.assertIsNone(build_adapter(config, FakeStore()))
        self.assertIsNone(build_adapter({**config, "ha_base_url": ""}, FakeStore({"ha_token": TOKEN})))
        adapter = build_adapter(config, FakeStore({"ha_token": TOKEN}))
        self.assertIsInstance(adapter, HomeAssistantAdapter)
        self.assertIsNone(adapter._thread, "built, not started: the runtime starts it")
        self.assertEqual(adapter.scenes, [{"entity_id": "scene.focus", "type": "scene", "label": ""}])

    def test_a_broken_store_reads_as_no_token(self):
        class Broken:
            def load(self):
                raise OSError("locked")
        self.assertEqual(load_token(Broken()), "")


# ------------------------------------------------------------------ r3.1: the area bridge
def area_light(entity, on=True, brightness=158, kelvin=3200, name=None, **attributes):
    attrs = {"friendly_name": name or entity, "brightness": brightness if on else None,
             "color_temp_kelvin": kelvin if on else None, "min_color_temp_kelvin": 2000,
             "max_color_temp_kelvin": 6535, "supported_color_modes": ["color_temp"]}
    attrs.update(attributes)
    return {"entity_id": entity, "state": "on" if on else "off", "attributes": attrs}


def scene_state(entity, name, members=()):
    return {"entity_id": entity, "state": "2026-09-28T20:00:00", "attributes": {"friendly_name": name,
                                                                                "entity_id": list(members)}}


class AreaServer(FakeServer):
    """Home Assistant with areas: the Hall holds a desk lamp (its own area), a floor lamp (its device's
    area), a brightness-only strip and, to be skipped, a light group, a hidden, a disabled and a config
    light; the kitchen light sits on a kitchen device; ``light.moved_out`` overrides the Hall device's
    area with the kitchen's."""

    REGISTRY = {"config/area_registry/list": "areas", "config/entity_registry/list": "entities",
                "config/device_registry/list": "devices"}

    def __init__(self, **kwargs):
        states = [area_light("light.den_desk", name="Desk lamp"),
                  area_light("light.den_floor", brightness=77, kelvin=2700, name="Floor lamp",
                             min_color_temp_kelvin=2700, max_color_temp_kelvin=5000),
                  area_light("light.den_strip", on=False, name="Shelf strip", supported_color_modes=["brightness"]),
                  area_light("light.den_all", name="Hall group",
                             entity_id=["light.den_desk", "light.den_floor", "light.den_strip"]),
                  area_light("light.den_hidden"), area_light("light.den_indicator"),
                  area_light("light.kitchen", name="Kitchen"), area_light("light.moved_out", name="Moved out"),
                  scene_state("scene.den_relax", "Relax", ["light.den_desk"]),
                  scene_state("scene.evening", "Evening", ["light.den_desk", "light.kitchen"]),
                  scene_state("scene.kitchen_cook", "Cook", ["light.kitchen", "light.den_desk"]),
                  scene_state("scene.whole_house", "Whole house", ["light.kitchen"]),
                  {"entity_id": "script.den_movie", "state": "off", "attributes": {"friendly_name": "Movie night"}},
                  {"entity_id": "automation.wake", "state": "on", "attributes": {"friendly_name": "Wake"}},
                  {"entity_id": "switch.kettle", "state": "off", "attributes": {}}]
        super().__init__(states=states, **kwargs)
        self.areas = [{"area_id": "hall", "name": "Hall"}, {"area_id": "kitchen", "name": "Kitchen"},
                      {"area_id": "attic", "name": "Attic"}]
        self.devices = [{"id": "dev_floor", "area_id": "hall", "disabled_by": None},
                        {"id": "dev_kitchen", "area_id": "kitchen", "disabled_by": None}]
        self.entities = [
            {"entity_id": "light.den_desk", "area_id": "hall", "device_id": None, "platform": "hue"},
            {"entity_id": "light.den_floor", "area_id": None, "device_id": "dev_floor", "platform": "zha"},
            {"entity_id": "light.den_strip", "area_id": "hall", "device_id": None, "platform": "esphome"},
            {"entity_id": "light.den_all", "area_id": "hall", "device_id": None, "platform": "group"},
            {"entity_id": "light.den_hidden", "area_id": "hall", "hidden_by": "user", "platform": "hue"},
            {"entity_id": "light.den_disabled", "area_id": "hall", "disabled_by": "user", "platform": "hue"},
            {"entity_id": "light.den_indicator", "area_id": None, "device_id": "dev_floor",
             "entity_category": "config", "platform": "zha"},
            {"entity_id": "light.kitchen", "area_id": None, "device_id": "dev_kitchen", "platform": "hue"},
            {"entity_id": "light.moved_out", "area_id": "kitchen", "device_id": "dev_floor", "platform": "zha"},
            {"entity_id": "scene.den_relax", "area_id": "hall", "platform": "homeassistant"},
            {"entity_id": "scene.kitchen_cook", "area_id": "kitchen", "platform": "homeassistant"},
            {"entity_id": "script.den_movie", "area_id": "hall", "platform": "script"},
            {"entity_id": "automation.wake", "area_id": None, "platform": "automation"},
        ]
        self.subscriptions = {}
        self.refuse = set()          # message types answered with success False

    def handle(self, socket, message):
        kind = message.get("type")
        if kind in self.refuse:
            socket.push({"id": message["id"], "type": "result", "success": False,
                         "error": {"code": "unauthorized", "message": "refused"}})
            return
        if kind in self.REGISTRY:
            socket.push({"id": message["id"], "type": "result", "success": True,
                         "result": json.loads(json.dumps(getattr(self, self.REGISTRY[kind])))})
        elif kind == "subscribe_events":
            self.subscriptions[message["event_type"]] = message["id"]
            if message["event_type"] == "state_changed":
                self.subscription = message["id"]
            socket.push({"id": message["id"], "type": "result", "success": True, "result": None})
        elif kind == "call_service":
            self.calls.append((message["domain"], message["service"], message.get("service_data"),
                               message.get("target")))
            socket.push({"id": message["id"], "type": "result", "success": True, "result": {"context": {}}})
            target = message.get("target") or {}
            if message["domain"] == "light" and ("area_id" in target or "entity_id" in target):
                data = message.get("service_data") or {}
                if "area_id" in target:
                    lights = ha_module.resolve_area(target["area_id"], self.entities, self.devices)[0]
                else:
                    ids = target["entity_id"]
                    lights = [ids] if isinstance(ids, str) else list(ids)
                for entity in lights:
                    old = self.states[entity]["attributes"]
                    on = message["service"] == "turn_on"
                    brightness = round(data["brightness_pct"] * 255 / 100) if "brightness_pct" in data \
                        else (old.get("brightness") or 128)
                    kelvin = data.get("color_temp_kelvin", old.get("color_temp_kelvin") or 3000)
                    self.change(area_light(entity, on, brightness=brightness, kelvin=kelvin,
                                           **{k: v for k, v in old.items() if k not in
                                              ("brightness", "color_temp_kelvin")}))
        else:
            super().handle(socket, message)

    def change(self, state):
        self.states[state["entity_id"]] = state
        self._event("state_changed", {"entity_id": state["entity_id"], "new_state": state})

    def _event(self, event_type, data):
        ident = self.subscriptions.get(event_type)
        for socket in self.sockets:
            if not socket.closed and ident is not None:
                socket.push({"id": ident, "type": "event", "event": {"event_type": event_type, "data": data}})

    def registry_event(self, event_type, **data):
        self._event(event_type, data)

    def add_light(self, entity, area="hall", name=None, **state):
        """A new light in Home Assistant: its state first, then the registry's create event."""
        self.change(area_light(entity, name=name, **state))
        self.entities.append({"entity_id": entity, "area_id": area, "device_id": None, "platform": "hue"})
        self.registry_event("entity_registry_updated", action="create", entity_id=entity)


def den_scenes(state):
    return [scene["entity_id"] for scene in state["scenes"]]


class AreaCase(unittest.TestCase):
    def make(self, server=None, http=None, area="hall", scenes=(), **kwargs):
        self.server = server or AreaServer()
        adapter = HomeAssistantAdapter("http://homeassistant.local:8123", TOKEN, "", scenes, area_id=area,
                                       ws_factory=self.server.connect, http=http or FakeHttp(), **kwargs)
        self.addCleanup(adapter.close)
        return adapter

    def started(self, **kwargs):
        with patch.object(ha_module, "RECV_TIMEOUT", 0.02), patch.object(ha_module, "REGISTRY_DEBOUNCE", 0.05):
            adapter = self.make(**kwargs)
            self.seen = []
            adapter.set_listener(self.seen.append)
            adapter.start()
            self.assertTrue(wait_for(lambda: adapter.read_state()["online"]), adapter.read_state())
        return adapter


class AreaResolutionTests(AreaCase):
    def test_the_den_resolves_and_aggregates(self):
        adapter = self.started()
        state = adapter.read_state()
        self.assertEqual((state["area_id"], state["name"], state["count"]), ("hall", "Hall", 3))
        self.assertEqual(state["entities"], ["light.den_desk", "light.den_floor", "light.den_strip"],
                         "own area, device area; never a group, hidden, disabled or config light")
        # on = any; bri = mean of the on lights (62 and 30); kelvin = mean of the on colour lights
        # (3200, 2700 -> 3000 in 100 K steps); range = the one the colour lights share.
        self.assertEqual((state["on"], state["on_count"], state["bri"], state["kelvin"]), (True, 2, 46, 3000))
        self.assertEqual((state["min_k"], state["max_k"], state["supports_ct"], state["available"]),
                         (2700, 5000, True, True))
        self.assertEqual((state["reason"], state["detail"], state["transport"]), ("", "", "ws"))
        self.assertNotIn(TOKEN, json.dumps(state))
        sent = [m["type"] if m["type"] != "subscribe_events" else "sub:" + m["event_type"]
                for m in self.server.sockets[0].sent]
        self.assertEqual(sent[:9], ["auth", "config/area_registry/list", "config/entity_registry/list",
                                    "config/device_registry/list", "get_states", "sub:state_changed",
                                    "sub:entity_registry_updated", "sub:device_registry_updated",
                                    "sub:area_registry_updated"])
        self.assertTrue(self.seen and self.seen[-1]["count"] == 3, "the listener hears the area")

    def test_auto_scenes_after_the_manual_ones(self):
        adapter = self.started(scenes=[{"entity_id": "automation.wake", "label": "Good morning"}])
        state = adapter.read_state()
        # Manual first (its label), then by name: the area's own scene and script and the scene
        # touching a Hall light without an area of its own; never the kitchen's scene (it touches the
        # desk lamp but belongs to the kitchen), a scene elsewhere or Desk Dial's snapshot.
        self.assertEqual(den_scenes(state), ["automation.wake", "scene.evening", "script.den_movie",
                                             "scene.den_relax"])
        self.assertEqual([s["label"] for s in state["scenes"]], ["Good morning", "Evening", "Movie night", "Relax"])
        self.assertEqual([s["type"] for s in state["scenes"]], ["automation", "scene", "script", "scene"])

    def test_a_light_outside_the_area_is_not_pushed(self):
        adapter = self.started()
        before = len(self.seen)
        self.server.change(area_light("light.kitchen", brightness=20))
        self.server.change(area_light("light.den_desk", brightness=255))
        self.assertTrue(wait_for(lambda: adapter.read_state()["bri"] == 65))   # (100 + 30) / 2
        self.assertEqual(len(self.seen), before + 1, "only the Hall light's change reached the listener")

    def test_a_removed_light_leaves_the_aggregate(self):
        adapter = self.started()
        self.server._event("state_changed", {"entity_id": "light.den_floor", "new_state": None})
        self.assertTrue(wait_for(lambda: adapter.read_state()["bri"] == 62))
        self.assertEqual(adapter.read_state()["count"], 3, "still in the registry until it is removed there")

    def test_an_unknown_area(self):
        adapter = self.make(area="garage")
        with patch.object(ha_module, "RECV_TIMEOUT", 0.02):
            adapter.start()
            self.assertTrue(wait_for(lambda: adapter.read_state()["detail"] == "area_missing"))
        state = adapter.read_state()
        self.assertEqual((state["online"], state["reason"], state["count"]), (False, "unavailable", 0))

    def test_an_area_without_lights(self):
        adapter = self.make(area="attic")
        with patch.object(ha_module, "RECV_TIMEOUT", 0.02):
            adapter.start()
            self.assertTrue(wait_for(lambda: adapter.read_state()["detail"] == "no_lights"))
        self.assertEqual((adapter.read_state()["name"], adapter.read_state()["reason"]), ("Attic", "unavailable"))

    def test_connecting_until_the_registry_is_read(self):
        adapter = self.make()
        self.assertEqual(adapter.read_state()["reason"], "connecting")


class LiveRegistryTests(AreaCase):
    def test_a_new_light_added_to_the_den_appears_without_a_restart(self):
        with patch.object(ha_module, "RECV_TIMEOUT", 0.02), patch.object(ha_module, "REGISTRY_DEBOUNCE", 0.05):
            adapter = self.started()
            self.server.add_light("light.den_reading", name="Reading lamp", brightness=255, kelvin=4000)
            self.assertTrue(wait_for(lambda: adapter.read_state()["count"] == 4), adapter.read_state())
        state = adapter.read_state()
        self.assertIn("light.den_reading", state["entities"])
        self.assertEqual((state["on_count"], state["bri"]), (3, 64), "(62 + 30 + 100) / 3")
        self.assertTrue(any(seen.get("count") == 4 for seen in self.seen), "the listener heard it")
        self.assertEqual(len(self.server.sockets), 1, "no reconnect, no restart")
        # The new light is in the snapshot of the next All off; commands still target the area.
        adapter.power(False)
        self.assertEqual(self.server.calls[0][2]["snapshot_entities"],
                         ["light.den_desk", "light.den_floor", "light.den_reading", "light.den_strip"])
        self.assertEqual(self.server.calls[1][3], {"area_id": "hall"})

    def test_a_light_moved_in_by_its_device(self):
        with patch.object(ha_module, "RECV_TIMEOUT", 0.02), patch.object(ha_module, "REGISTRY_DEBOUNCE", 0.05):
            adapter = self.started()
            self.server.devices[1]["area_id"] = "hall"           # the kitchen light's device moves to the Hall
            self.server.registry_event("device_registry_updated", action="update", device_id="dev_kitchen")
            self.assertTrue(wait_for(lambda: "light.kitchen" in adapter.read_state()["entities"]))
            self.server.entities[0]["area_id"] = "kitchen"       # the desk lamp moves out
            self.server.registry_event("entity_registry_updated", action="update", entity_id="light.den_desk")
            self.assertTrue(wait_for(lambda: "light.den_desk" not in adapter.read_state()["entities"]))

    def test_an_area_rename(self):
        with patch.object(ha_module, "RECV_TIMEOUT", 0.02), patch.object(ha_module, "REGISTRY_DEBOUNCE", 0.05):
            adapter = self.started()
            self.server.areas[0]["name"] = "Study"
            self.server.registry_event("area_registry_updated", action="update", area_id="hall")
            self.assertTrue(wait_for(lambda: adapter.read_state()["name"] == "Study"))

    def test_registry_events_are_debounced(self):
        with patch.object(ha_module, "RECV_TIMEOUT", 0.02), patch.object(ha_module, "REGISTRY_DEBOUNCE", 0.2):
            adapter = self.started()
            for _ in range(6):
                self.server.registry_event("entity_registry_updated", action="update", entity_id="light.x")
            self.assertTrue(wait_for(lambda: sum(m["type"] == "config/entity_registry/list"
                                                 for m in self.server.sockets[0].sent) == 2))
            time.sleep(0.4)
        lists = [m["type"] for m in self.server.sockets[0].sent if m["type"] == "config/entity_registry/list"]
        self.assertEqual(len(lists), 2, "one re-resolve for the burst")
        self.assertTrue(adapter.read_state()["online"])


class RepliesAreCheckedTests(AreaCase):
    def refused(self, kind):
        server = AreaServer()
        server.refuse.add(kind)
        return server

    def test_a_refused_get_states_reconnects(self):
        server = self.refused("get_states")
        with patch.object(ha_module, "BACKOFF", (0.02,)), patch.object(ha_module, "RECV_TIMEOUT", 0.02):
            adapter = self.make(server, rest_poll=0.01)
            adapter.start()
            self.assertTrue(wait_for(lambda: len(server.sockets) >= 2))
        self.assertNotEqual(adapter.read_state()["transport"], "ws")

    def test_a_refused_state_subscription_reconnects(self):
        server = AreaServer()
        original = server.handle

        def refuse_state_changed(socket, message):
            if message.get("type") == "subscribe_events" and message.get("event_type") == "state_changed":
                socket.push({"id": message["id"], "type": "result", "success": False,
                             "error": {"code": "unauthorized", "message": "no"}})
                return
            original(socket, message)
        server.handle = refuse_state_changed
        with patch.object(ha_module, "BACKOFF", (0.02,)), patch.object(ha_module, "RECV_TIMEOUT", 0.02):
            self.make(server, rest_poll=0.01).start()
            self.assertTrue(wait_for(lambda: len(server.sockets) >= 2))

    def test_refused_registry_lists_fall_back_to_the_rest_template(self):
        server = self.refused("config/entity_registry/list")
        http = FakeHttp()
        http.refuse_hidden_test = True        # an older HA: the plain template is used
        http.template_answer = json.dumps({"known": True, "name": "Hall",
                                           "lights": ["light.den_desk", "light.den_floor", "light.den_all"],
                                           "extras": ["script.den_movie", "scene.desk_dial_snapshot"]})
        adapter = self.started(server=server, http=http)
        state = adapter.read_state()
        self.assertEqual(state["entities"], ["light.den_desk", "light.den_floor"], "the group is skipped by its state")
        self.assertIn("script.den_movie", den_scenes(state))
        self.assertNotIn("scene.desk_dial_snapshot", den_scenes(state))
        templates = [r[3]["template"] for r in http.requests if r[1].endswith("/api/template")]
        self.assertEqual(len(templates), 2)
        self.assertIn("set a = 'hall'", templates[0])


class IdRaceTests(AreaCase):
    def test_ids_reach_home_assistant_in_increasing_order(self):
        """r3.1 fix: an id allocated by one thread (a call) and sent after a later id (the ping) was
        refused by Home Assistant ("id_reuse"). Allocation and send now share one lock."""
        adapter = self.started()

        class SlowIds:
            def __init__(self):
                self.value = 1000
                self.lock = threading.Lock()

            def __next__(self):
                with self.lock:
                    self.value += 1
                    value = self.value
                time.sleep(0.003)             # widen the window between allocation and send
                return value
        adapter._ids = SlowIds()
        errors = []

        def burst(level):
            try:
                for step in range(4):
                    adapter.call_service("light", "turn_on", {"area_id": "hall", "brightness_pct": level + step})
            except HomeAssistantError as exc:
                errors.append(exc.outcome)

        def pings():
            for _ in range(12):
                adapter._send_frame(adapter._ws, {"type": "ping"})
        threads = [threading.Thread(target=burst, args=(10 * n + 1,)) for n in range(6)]
        threads.append(threading.Thread(target=pings))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        socket = self.server.sockets[0]
        ids = [m["id"] for m in socket.sent if "id" in m]
        self.assertEqual(socket.id_errors, [])
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(errors, [])


class AreaServiceTests(AreaCase):
    def setUp(self):
        self.adapter = self.started()

    def test_a_turn_changes_only_the_lights_that_are_on(self):
        """r3.1: every light that is on gets the same value; the lights that are off stay off."""
        result = self.adapter.set_light(bri=40)
        on = ["light.den_desk", "light.den_floor"]
        self.assertEqual(self.server.calls[-1], ("light", "turn_on", {"brightness_pct": 40, "transition": 0.4}, {"entity_id": on}))
        self.assertEqual(result["_applied"], {"bri": 40, "kelvin": None})
        self.assertEqual(result["_targets"], on)
        self.assertTrue(wait_for(lambda: self.adapter.read_state()["bri"] == 40))
        self.adapter.set_light(kelvin=6500)
        self.assertEqual(self.server.calls[-1][2:], ({"color_temp_kelvin": 5000, "transition": 0.4}, {"entity_id": on}),
                         "clamped to the shared range")
        time.sleep(0.05)
        self.assertEqual(self.adapter.read_state()["on_count"], 2, "the strip stayed off")

    def test_a_turn_from_all_off_switches_on_every_available_light(self):
        self.adapter.power(False)
        self.assertTrue(wait_for(lambda: not self.adapter.read_state()["on"]))
        self.server.change(area_light("light.den_floor", on=False, name="Floor lamp"))
        self.server.change({"entity_id": "light.den_strip", "state": "unavailable", "attributes": {}})
        self.assertTrue(wait_for(lambda: self.adapter.read_state()["unavailable_count"] == 1))
        self.adapter.set_light(bri=1)
        self.assertEqual(self.server.calls[-1], ("light", "turn_on", {"brightness_pct": 1, "transition": 0.4},
                                                 {"entity_id": ["light.den_desk", "light.den_floor"]}),
                         "never the unavailable strip")

    def test_the_controller_can_name_the_targets(self):
        self.adapter.set_light(bri=70, targets=["light.den_floor"])
        self.assertEqual(self.server.calls[-1][3], {"entity_id": ["light.den_floor"]})
        before = len(self.server.calls)
        with self.assertRaises(HomeAssistantError) as caught:
            self.adapter.set_light(bri=70, targets=["light.den_floor", "light.kitchen"])
        self.assertEqual(caught.exception.outcome, "not_allowed")
        self.assertEqual(len(self.server.calls), before)

    def test_per_light_rows_and_the_last_level(self):
        state = self.adapter.read_state()
        self.assertEqual(state["lights"], [
            {"entity_id": "light.den_desk", "name": "Desk lamp", "on": True, "bri": 62, "kelvin": 3200,
             "available": True},
            {"entity_id": "light.den_floor", "name": "Floor lamp", "on": True, "bri": 30, "kelvin": 2700,
             "available": True},
            {"entity_id": "light.den_strip", "name": "Shelf strip", "on": False, "bri": 0, "kelvin": None,
             "available": True}])
        self.assertEqual(state["unavailable_count"], 0)
        self.server.change({"entity_id": "light.den_strip", "state": "unavailable", "attributes": {}})
        self.assertTrue(wait_for(lambda: self.adapter.read_state()["unavailable_count"] == 1))
        row = next(r for r in self.adapter.read_state()["lights"] if r["entity_id"] == "light.den_strip")
        self.assertEqual((row["name"], row["available"]), ("den_strip", False), "no name without a state")
        self.assertEqual(self.adapter.read_state()["count"], 3, "an unavailable light still counts")

    def test_all_off_snapshots_the_resolved_lights_and_turn_on_restores(self):
        self.adapter.power(False)
        self.assertEqual(self.server.calls[0][:3], ("scene", "create", {
            "scene_id": "desk_dial_snapshot", "snapshot_entities": ["light.den_desk", "light.den_floor",
                                                                     "light.den_strip"]}))
        self.assertEqual(self.server.calls[1], ("light", "turn_off", {}, {"area_id": "hall"}))
        self.assertTrue(wait_for(lambda: not self.adapter.read_state()["on"]))
        state = self.adapter.read_state()
        self.assertEqual((state["bri"], state["kelvin"]), (46, 3000), "off keeps the level from before All off")
        self.adapter.power(True)
        self.assertEqual(self.server.calls[-1], ("scene", "turn_on", {}, {"entity_id": "scene.desk_dial_snapshot"}))

    def test_turn_on_after_the_area_changed_uses_the_area_not_an_old_snapshot(self):
        self.adapter.power(False)
        with self.adapter._lock:
            self.adapter._snapshot_members = ["light.den_desk"]      # taken before a light joined
        self.adapter.power(True)
        self.assertEqual(self.server.calls[-1], ("light", "turn_on", {}, {"area_id": "hall"}))

    def test_the_allowlist_is_area_scoped(self):
        before = len(self.server.sockets[0].sent)
        refused = [("light", "turn_on", {"entity_id": "light.kitchen"}),
                   ("light", "turn_on", {"entity_id": ["light.den_desk", "light.kitchen"]}),
                   ("light", "turn_on", {"entity_id": []}),
                   ("light", "turn_on", {"entity_id": ["light.den_desk", "light.den_desk"]}),
                   ("light", "turn_on", {"entity_id": ["light.den_all"]}),
                   ("light", "turn_on", {"entity_id": ["light.den_desk"], "rgb_color": [255, 0, 0]}),
                   ("light", "turn_on", {"area_id": "kitchen", "brightness_pct": 10}),
                   ("light", "turn_on", {"area_id": "hall", "entity_id": "light.kitchen"}),
                   ("light", "turn_on", {"area_id": "hall", "rgb_color": [255, 0, 0]}),
                   ("light", "turn_off", {"area_id": "kitchen"}),
                   ("light", "turn_off", {"entity_id": "light.den"}),
                   ("scene", "create", {"scene_id": "desk_dial_snapshot", "snapshot_entities": ["light.den_desk"]}),
                   ("scene", "create", {"scene_id": "desk_dial_snapshot",
                                        "snapshot_entities": ["light.den_desk", "light.den_floor", "light.den_strip",
                                                              "light.kitchen"]}),
                   ("scene", "turn_on", {"entity_id": "scene.kitchen_cook"}),
                   ("scene", "turn_on", {"entity_id": "scene.whole_house"}),
                   ("script", "turn_on", {"entity_id": "script.other"}),
                   ("automation", "trigger", {"entity_id": "automation.wake"}),
                   ("switch", "turn_on", {"entity_id": "switch.kettle"})]
        for domain, service, data in refused:
            with self.subTest(call=(domain, service, data)):
                with self.assertRaises(HomeAssistantError) as caught:
                    self.adapter.call_service(domain, service, data)
                self.assertEqual(caught.exception.outcome, "not_allowed")
        self.assertEqual(len(self.server.sockets[0].sent), before, "nothing was sent")

    def test_scene_entries_carry_a_preview_or_none(self):
        scenes = {s["entity_id"]: s for s in self.adapter.read_state()["scenes"]}
        self.assertEqual((scenes["script.den_movie"]["bri"], scenes["script.den_movie"]["kelvin"]), (None, None))
        self.server.change(scene_state("scene.den_relax", "Relax", ["light.den_desk"]) |
                           {"attributes": {"friendly_name": "Relax", "entity_id": ["light.den_desk"], "brightness": 40}})
        self.assertTrue(wait_for(lambda: {s["entity_id"]: s for s in self.adapter.read_state()["scenes"]}
                                 ["scene.den_relax"]["bri"] == 40))

    def test_the_area_scenes_run(self):
        self.adapter.run_scene("scene.den_relax")
        self.adapter.run_scene("scene.evening")
        self.adapter.run_scene("script.den_movie")
        self.assertEqual([c[:2] for c in self.server.calls], [("scene", "turn_on"), ("scene", "turn_on"),
                                                              ("script", "turn_on")])
        with self.assertRaises(HomeAssistantError):
            self.adapter.run_scene("scene.kitchen_cook")


class AreaRestTests(unittest.TestCase):
    def test_rest_fallback_resolves_through_the_template(self):
        http = FakeHttp(states=[area_light("light.den_desk", name="Desk lamp"),
                                area_light("light.den_floor", brightness=77, kelvin=2700)])
        http.template_answer = json.dumps({"known": True, "name": "Hall", "lights": ["light.den_desk", "light.den_floor"],
                                           "extras": []})
        adapter = HomeAssistantAdapter("http://homeassistant.local:8123", TOKEN, "", area_id="hall",
                                       ws_factory=lambda url, timeout: None, http=http, rest_poll=0.02)
        self.addCleanup(adapter.close)
        with patch.object(ha_module, "BACKOFF", (0.05,)):
            adapter.start()
            self.assertTrue(wait_for(lambda: adapter.read_state()["online"]), adapter.read_state())
        state = adapter.read_state()
        self.assertEqual((state["transport"], state["name"], state["count"], state["bri"]), ("rest", "Hall", 2, 46))
        adapter.set_light(bri=40)
        post = [r for r in http.requests if r[1].endswith("/api/services/light/turn_on")][-1]
        self.assertEqual(post[3], {"entity_id": ["light.den_desk", "light.den_floor"], "brightness_pct": 40, "transition": 0.4})
        self.assertFalse(post[4], "redirects are never followed")
        template = [r for r in http.requests if r[1].endswith("/api/template")][0][3]["template"]
        self.assertIn("is_hidden_entity", template)


class AreaProbeTests(unittest.TestCase):
    def test_settings_lists_areas_from_the_registry(self):
        server = AreaServer()
        http = FakeHttp(states=list(server.states.values()))
        adapter = HomeAssistantAdapter("http://homeassistant.local:8123", TOKEN, "", http=http,
                                       ws_factory=server.connect)
        result = adapter.test_connection()
        self.assertTrue(result["ok"])
        self.assertEqual(result["areas"], [("attic", "Attic", 0), ("hall", "Hall", 3), ("kitchen", "Kitchen", 2)])
        self.assertEqual(result["default_area"],"attic", "no configured area: the first one")
        self.assertEqual(result["version"], "2026.9.0", "from the WebSocket hello when /api/config has none")
        den = result["area_details"]["hall"]
        self.assertEqual([(row["name"], row["on"], row["bri"]) for row in den["lights"]],
                         [("Desk lamp", True, 62), ("Floor lamp", True, 30), ("Shelf strip", False, 0)])
        self.assertEqual([(row["name"], row["type"]) for row in den["scenes"]],
                         [("Evening", "scene"), ("Movie night", "script"), ("Relax", "scene")])
        self.assertEqual([row["name"] for row in result["area_details"]["kitchen"]["scenes"]],
                         ["Cook", "Evening", "Whole house"])
        self.assertEqual(result["area_details"]["attic"], {"lights": [], "scenes": []})
        self.assertTrue(server.sockets[0].closed, "the one-shot socket is closed")
        self.assertFalse([m for m in server.sockets[0].sent if m["type"] in ("call_service", "subscribe_events")])
        self.assertEqual({r[0] for r in http.requests}, {"GET"})

    def test_settings_falls_back_to_the_areas_template(self):
        http = FakeHttp()
        http.areas_answer = json.dumps([["office", "Office", 2], ["hall", "Hall", 3], ["bad id", "x", 1]])
        adapter = HomeAssistantAdapter("http://homeassistant.local:8123", TOKEN, "", http=http,
                                       ws_factory=lambda url, timeout: None)
        result = adapter.test_connection()
        self.assertEqual(result["areas"], [("hall", "Hall", 3), ("office", "Office", 2)])
        self.assertEqual(result["default_area"], "hall")
        # The r3.1 template form (ids per area) also fills the live lists from /api/states.
        http = FakeHttp(states=[area_light("light.den_desk", name="Desk lamp"),
                                scene_state("scene.relax", "Relax", ["light.den_desk"])])
        http.areas_answer = json.dumps([["hall", "Hall", ["light.den_desk"], ["scene.relax", "script.gone"]]])
        adapter = HomeAssistantAdapter("http://homeassistant.local:8123", TOKEN, "", http=http,
                                       ws_factory=lambda url, timeout: None)
        result = adapter.test_connection()
        self.assertEqual(result["areas"], [("hall", "Hall", 1)])
        self.assertEqual(result["area_details"]["hall"]["lights"][0]["name"], "Desk lamp")
        self.assertEqual([row["entity_id"] for row in result["area_details"]["hall"]["scenes"]],
                         ["script.gone", "scene.relax"], "by name ('gone' has none: its id)")


class AreaHelperTests(unittest.TestCase):
    def test_aggregate(self):
        facts = [light_facts(area_light("light.a", brightness=255, kelvin=2200, min_color_temp_kelvin=2200,
                                        max_color_temp_kelvin=3000)),
                 light_facts(area_light("light.b", brightness=128, kelvin=6000, min_color_temp_kelvin=4000,
                                        max_color_temp_kelvin=6500))]
        aggregate = ha_module.aggregate_facts(facts)
        self.assertEqual((aggregate["bri"], aggregate["min_k"], aggregate["max_k"]), (75, 2200, 6500),
                         "no shared range: their union")
        self.assertEqual(aggregate["kelvin"], 4100)
        off = ha_module.aggregate_facts([light_facts(area_light("light.a", on=False))])
        self.assertEqual((off["on"], off["bri"], off["kelvin"], off["available"]), (False, 0, None, True))
        gone = ha_module.aggregate_facts([light_facts({"entity_id": "light.a", "state": "unavailable"})])
        self.assertFalse(gone["available"])
        plain = ha_module.aggregate_facts([light_facts(area_light("light.a", supported_color_modes=["onoff"]))])
        self.assertEqual((plain["supports_ct"], plain["kelvin"], plain["min_k"], plain["max_k"]),
                         (False, None, 2200, 6500))

    def test_valid_area_and_default(self):
        for good in ("hall", "living_room", "4f2a9c"):
            self.assertTrue(ha_module.valid_area(good))
        for bad in ("", "Hall", "den room", "den'", None, "x" * 101):
            self.assertFalse(ha_module.valid_area(bad))
        self.assertEqual(ha_module.default_area([("a", "Attic", 0), ("d", " den ", 2)]), "a")
        self.assertEqual(ha_module.default_area([("a", "Attic", 0)], "a"), "a")

    def test_scene_previews(self):
        preview = ha_module.scene_preview
        self.assertEqual(preview(scene_state("scene.a", "A") | {"attributes": {"brightness": 50}}), (50, None),
                         "Hue scenes report a percentage")
        self.assertEqual(preview({"attributes": {"brightness": 128, "color_temp_kelvin": 2730}}), (50, 2700))
        self.assertEqual(preview({"attributes": {"brightness_pct": 80, "color_temp": 250}}), (80, 4000))
        self.assertEqual(preview(scene_state("scene.a", "A")), (None, None))
        self.assertEqual(preview({"attributes": {"brightness": 0}}), (None, None))

    def test_light_rows(self):
        self.assertEqual(ha_module.light_row("light.x", None), {"entity_id": "light.x", "name": "x", "on": False,
                                                                "bri": 0, "kelvin": None, "available": False})
        row = ha_module.light_row("light.a", area_light("light.a", name="Lamp", supported_color_modes=["brightness"]))
        self.assertEqual((row["name"], row["on"], row["bri"], row["kelvin"]), ("Lamp", True, 62, None))

    def test_groups_by_state(self):
        self.assertTrue(ha_module.is_light_group(area_light("light.g", entity_id=["light.a"])))
        self.assertTrue(ha_module.is_light_group(area_light("light.g", is_hue_group=True)))
        self.assertFalse(ha_module.is_light_group(area_light("light.a")))


class AreaConfigTests(unittest.TestCase):
    def logs(self, config, store):
        with self.assertLogs("control_center.home_assistant", "INFO") as captured:
            adapter = build_adapter(config, store)
        return adapter, " ".join(captured.output)

    def test_build_adapter_prefers_the_area_and_logs_why_not(self):
        config = {"ha_base_url": "http://ha.local:8123", "ha_area": "hall", "ha_light_entity": "light.den"}
        adapter, text = self.logs(config, FakeStore({"ha_token": TOKEN}))
        self.assertEqual((adapter.area_id, adapter.light_entity, adapter.configured), ("hall", "", True))
        self.assertIn("area hall", text)
        self.assertIsNone(self.logs(config, FakeStore())[0])
        self.assertIn("no access token", self.logs(config, FakeStore())[1])
        self.assertIn("no address", self.logs({**config, "ha_base_url": ""}, FakeStore())[1])
        self.assertIn("no area", self.logs({"ha_base_url": "http://ha.local:8123"}, FakeStore())[1])
        self.assertIn("not valid", self.logs({**config, "ha_area": "Hall Room", "ha_light_entity": ""},
                                             FakeStore({"ha_token": TOKEN}))[1])
        for message in (self.logs(config, FakeStore({"ha_token": TOKEN}))[1],
                        self.logs(config, FakeStore())[1]):
            self.assertNotIn(TOKEN, message)

    def test_status_json_lights_section(self):
        self.assertEqual(ha_module.lights_status(None)["reason"], "not_configured")
        server = AreaServer()
        adapter = HomeAssistantAdapter("http://homeassistant.local:8123", TOKEN, "", area_id="hall",
                                       ws_factory=server.connect, http=FakeHttp())
        self.addCleanup(adapter.close)
        with patch.object(ha_module, "RECV_TIMEOUT", 0.02):
            adapter.start()
            self.assertTrue(wait_for(lambda: adapter.read_state()["online"]))
        status = ha_module.lights_status(adapter)
        text = json.dumps(status)
        self.assertNotIn(TOKEN, text)
        self.assertNotIn("homeassistant.local", text, "not even the address")
        self.assertEqual((status["area_id"], status["name"], status["count"], status["online"]), ("hall", "Hall", 3, True))
        self.assertIn("scene.den_relax", status["scenes"])


class SimulatedAreaTests(unittest.TestCase):
    """SimulatedHomeAssistant(area="demo"): the simulator's multi-light Demo, shaped like the adapter."""

    def setUp(self):
        from control_center.simulation import SimControls, SimulatedHomeAssistant
        self.ha = SimulatedHomeAssistant(SimControls(), area="demo")
        self.heard = []
        self.ha.set_listener(self.heard.append)

    def test_the_demo(self):
        state = self.ha.read_state()
        self.assertEqual((state["online"], state["area_id"], state["name"], state["count"]), (True, "demo", "Demo", 3))
        self.assertEqual(state["entities"], ["light.demo_desk", "light.demo_floor", "light.demo_shelf"])
        self.assertEqual((state["on"], state["bri"], state["kelvin"], state["supports_ct"]), (True, 62, 3200, True))
        self.assertEqual(state["scenes"][0]["label"], "Focus")

    def test_a_light_added_to_the_demo_appears(self):
        self.ha.add_light("light.demo_reading", "Reading lamp", bri=100)
        self.assertEqual(self.heard[-1]["count"], 4, "the listener hears the new count at once")
        self.assertEqual(self.heard[-1]["bri"], 72, "(62 + 62 + 62 + 100) / 4")
        self.ha.add_light("light.kitchen_spot", "Spot", area="kitchen")
        self.assertEqual(self.ha.read_state()["count"], 4, "another area's light is not the Demo's")

    def test_commands_target_the_area_and_snapshot_its_lights(self):
        self.ha.set_light(bri=40, kelvin=2700)
        demo = ["light.demo_desk", "light.demo_floor", "light.demo_shelf"]
        self.assertEqual(self.ha.calls[-1], ("light", "turn_on", {"entity_id": demo, "brightness_pct": 40,
                                                                  "color_temp_kelvin": 2700}))
        self.assertEqual(self.ha.lights["light.demo_shelf"]["kelvin"], 3200, "a brightness-only light keeps its own")
        self.ha.power(False)
        self.assertEqual(self.ha.calls[-2], ("scene", "create", {"scene_id": "desk_dial_snapshot", "snapshot_entities":
                                                                 ["light.demo_desk", "light.demo_floor",
                                                                  "light.demo_shelf"]}))
        self.assertEqual(self.ha.calls[-1], ("light", "turn_off", {"area_id": "demo"}))
        self.assertEqual((self.ha.read_state()["on"], self.ha.read_state()["bri"], self.ha.read_state()["kelvin"]),
                         (False, 40, 2700), "off keeps the last level")
        self.ha.power(True)
        self.assertEqual(self.ha.calls[-1][:2], ("scene", "turn_on"))
        self.assertEqual(self.ha.read_state()["bri"], 40)
        self.ha.power(False)
        self.ha.add_light("light.demo_new", "New")
        self.ha.power(True)
        self.assertEqual(self.ha.calls[-1], ("light", "turn_on", {"area_id": "demo"}),
                         "the snapshot predates the new light: the area turns on instead")

    def test_a_turn_changes_only_the_lights_that_are_on(self):
        self.ha.external(on=False, entity="light.demo_floor")
        state = self.ha.set_light(bri=10)
        self.assertEqual(state["_targets"], ["light.demo_desk", "light.demo_shelf"])
        self.assertEqual(self.ha.calls[-1][2]["entity_id"], ["light.demo_desk", "light.demo_shelf"])
        self.assertFalse(self.ha.lights["light.demo_floor"]["on"], "an off light stays off")
        self.assertEqual((state["bri"], state["on_count"]), (10, 2))
        self.ha.power(False)
        self.ha.set_available("light.demo_shelf", False)
        state = self.ha.set_light(bri=1)
        self.assertEqual(state["_targets"], ["light.demo_desk", "light.demo_floor"],
                         "from all off every available light turns on")
        self.assertEqual((state["on_count"], state["unavailable_count"], state["count"]), (2, 1, 3))
        self.ha.set_light(bri=50, targets=["light.demo_floor"])
        self.assertEqual(self.ha.calls[-1][2]["entity_id"], ["light.demo_floor"])

    def test_rows_and_previews(self):
        state = self.ha.read_state()
        self.assertEqual([row["name"] for row in state["lights"]], ["Desk lamp", "Floor lamp", "Shelf strip"])
        self.assertEqual(state["lights"][2], {"entity_id": "light.demo_shelf", "name": "Shelf strip", "on": True,
                                              "bri": 62, "kelvin": None, "available": True})
        previews = {s["label"]: (s["bri"], s["kelvin"]) for s in state["scenes"]}
        self.assertEqual(previews["Focus"], (62, 3200))
        self.assertEqual(previews["Movie"], (None, None), "a script has no preview")
        self.assertEqual(previews["Daylight"], (None, None), "an automation has none either")

    def test_the_allowlist(self):
        from control_center.home_assistant import HomeAssistantError
        with self.assertRaises(HomeAssistantError):
            self.ha._record("light", "turn_on", {"entity_id": "light.kitchen_ceiling"})
        with self.assertRaises(HomeAssistantError):
            self.ha._record("light", "turn_on", {"entity_id": ["light.demo_desk", "light.kitchen_ceiling"]})
        with self.assertRaises(HomeAssistantError):
            self.ha._record("light", "turn_on", {"area_id": "kitchen"})
        with self.assertRaises(HomeAssistantError):
            self.ha._record("scene", "create", {"scene_id": "desk_dial_snapshot", "snapshot_entities": ["light.x"]})

    def test_unavailable_reasons(self):
        for entity in self.ha.members():
            self.ha.move_light(entity, "office")
        self.assertEqual((self.ha.read_state()["reason"], self.ha.read_state()["detail"]), ("unavailable", "no_lights"))
        self.ha.area_id = "attic"
        self.assertEqual(self.ha.read_state()["detail"], "area_missing")

    def test_rename_and_external(self):
        self.ha.rename_area("Study")
        self.assertEqual(self.heard[-1]["name"], "Study")
        self.ha.external(bri=20, entity="light.demo_desk")
        self.assertEqual(self.heard[-1]["bri"], 48, "(20 + 62 + 62) / 3")

    def test_settings_probe(self):
        result = self.ha.test_connection()
        self.assertEqual(result["areas"], [("demo", "Demo", 3), ("kitchen", "Kitchen", 1), ("office", "Office", 0)])
        self.assertEqual(result["default_area"], "demo")

    def test_the_single_light_shape_is_unchanged(self):
        from control_center.simulation import SimControls, SimulatedHomeAssistant
        ha = SimulatedHomeAssistant(SimControls())
        ha.set_light(bri=63)
        self.assertEqual(ha.calls[-1], ("light", "turn_on", {"entity_id": "light.demo", "brightness_pct": 63}))
        state = ha.read_state()
        self.assertEqual((state["name"], state["area_id"], state["count"]), ("Demo", "", None))




class TransitionGuardTests(unittest.TestCase):
    """2026-09-29: every knob write fades over LIGHT_TRANSITION; the guard bounds `transition`."""

    def test_constants(self):
        from control_center import home_assistant as ha
        from control_center import controller
        self.assertEqual(ha.LIGHT_TRANSITION, 0.4)
        self.assertEqual(ha.WRITE_INTERVAL, 0.25)
        self.assertEqual(controller.LIGHTS_WRITE_INTERVAL, ha.WRITE_INTERVAL)
        self.assertGreater(ha.LIGHT_TRANSITION, ha.WRITE_INTERVAL)   # the fades overlap into one glide


if __name__ == "__main__":
    unittest.main()
