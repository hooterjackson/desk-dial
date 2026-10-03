"""Plan sections 3a / 3c (S1 DD-C): the tray's App mode submenu (runtime.app_menu() entries, Manual toggles through
runtime.toggle_app on the Tk thread) and status.json's `app` block (runtime.app_status(), never a title or URL).
pystray's real Menu / MenuItem (pure Python); no tray icon, no window."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import standalone  # noqa: E402
from standalone import (TrayState, app_menu_entries, build_tray_menu, route_request, toggle_app_request,  # noqa: E402
                        tray_app_entries, tray_menu_model)


class SubmenuTests(unittest.TestCase):
    def menu(self, apps):
        import pystray
        state, queued = TrayState("Knob ready", True, True, apps=apps), []
        menu = build_tray_menu(SimpleNamespace(Menu=pystray.Menu, MenuItem=pystray.MenuItem), state, queued.append)
        return state, queued, list(menu.items)[5]

    def test_app_mode_is_a_submenu_of_the_runtime_entries(self):
        state, queued, item = self.menu([("onshape", "Onshape", True), ("figma", "Figma", False)])
        self.assertEqual(item.text, "App mode")
        entries = list(item.submenu.items)
        self.assertEqual([(e.text, e.checked, e.enabled) for e in entries],
                         [("Onshape", True, True), ("Figma", False, True)])
        entries[1](object())
        self.assertEqual(queued, ["app:figma"], "the tray thread only queues")
        state.apps = [("figma", "Figma", True)]
        entries = list(item.submenu.items)
        self.assertEqual([(e.text, e.checked) for e in entries], [("Figma", True)], "rebuilt from the state each time")

    def test_no_app_in_manual_shows_a_disabled_hint(self):
        _state, queued, item = self.menu([])
        (entry,) = list(item.submenu.items)
        self.assertEqual((entry.text, entry.enabled), ("Set an app to Manual in Settings › Apps", False))
        entry(object())
        self.assertEqual(queued, [])

    def test_entries_are_cleaned(self):
        self.assertEqual(tray_app_entries([("figma", "Figma\nmore", 1), ("bad id that is long", "x", 0), "junk",
                                           ("plasticity", "P" * 80, 0)]),
                         [("Figma more", "app:figma", True), ("P" * 39 + "…", "app:plasticity", False)])

    def test_the_menu_model_keeps_its_order(self):
        model = tray_menu_model("", True, True, [("figma", "Figma", True)])
        self.assertEqual([entry[1] for entry in model], [None, None, "peek", "settings", "connect", "apps", "quit"])
        self.assertNotIn("Onshape mode", [entry[0] for entry in model])


class RoutingTests(unittest.TestCase):
    def test_app_requests_toggle_on_the_tk_thread(self):
        toggled = []
        handlers = {"app": toggled.append, "quit": lambda: None}
        self.assertFalse(route_request("app:figma", handlers))
        self.assertEqual(toggled, ["figma"])
        self.assertTrue(route_request("quit", handlers))
        self.assertFalse(route_request("onshape", handlers), "the old request does nothing")

    def test_a_refusal_becomes_a_balloon(self):
        runtime = SimpleNamespace(toggle_app=lambda pid: "Figma isn't in front" if pid == "figma" else None)
        app = SimpleNamespace(runtime=runtime, tray_messages=[])
        self.assertEqual(toggle_app_request(app, "figma"), "Figma isn't in front")
        toggle_app_request(app, "onshape")
        self.assertEqual(app.tray_messages, ["Figma isn't in front"])

    def test_a_runtime_from_before_app_profiles(self):
        calls = []
        runtime = SimpleNamespace(toggle_onshape=lambda: calls.append(1), onshape_menu_text=lambda: "Leave Onshape mode")
        toggle_app_request(SimpleNamespace(runtime=runtime, tray_messages=[]), "onshape")
        self.assertEqual(calls, [1])
        self.assertEqual(app_menu_entries(runtime), [("onshape", "Onshape", True)])

    def test_menu_entries_come_from_the_runtime(self):
        runtime = SimpleNamespace(app_menu=lambda: [["figma", "Figma", False]])
        self.assertEqual(app_menu_entries(runtime), [("figma", "Figma", False)])
        broken = SimpleNamespace(app_menu=lambda: 1 / 0)
        with self.assertLogs(level="WARNING"):
            self.assertEqual(app_menu_entries(broken), [])

    def test_the_tray_wires_the_app_handler(self):
        source = (Path(__file__).resolve().parents[1] / "standalone.py").read_text(encoding="utf-8")
        self.assertIn("'app': lambda pid: toggle_app_request(app, pid),", source)
        self.assertIn("tray_state.apps = app_menu_entries(app.runtime)", source)
        self.assertNotIn("'onshape': toggle_onshape", source)


class StatusTests(unittest.TestCase):
    def app(self, runtime):
        controller = SimpleNamespace(ready=True, screen=SimpleNamespace(mode="onshape", status="", loading=False,
                                                                        index=0, pages=[]), state={})
        defaults = dict(device_connected=False, apple=SimpleNamespace(), device_status="", led_style="color",
                        artwork_enabled=True, artwork_status={}, onshape_status=lambda: {"mode": "auto"})
        for key, value in defaults.items():
            if not hasattr(runtime, key):
                setattr(runtime, key, value)
        return SimpleNamespace(runtime=runtime, controller=controller, live=True)

    def test_the_app_block_sits_next_to_onshape(self):
        block = {"id": "figma", "match": "host", "modes": {"onshape": "auto", "figma": "auto"}, "active": True}
        status = standalone.status_payload(self.app(SimpleNamespace(app_status=lambda: block)),
                                           standalone.RetryPolicy(), {"exists": False})
        self.assertEqual(status["app"], block)
        self.assertEqual(status["onshape"], {"mode": "auto"}, "the legacy key stays")

    def test_never_a_title_or_url(self):
        leaky = {"id": "figma", "match": "host", "title": "Secret design - Figma", "windowTitle": "x",
                 "url": "https://www.figma.com/file/abc", "last": {"note": "https://x.example/a", "url": "y",
                                                                     "kept": 1},
                 "hosts": ["https://a.example/b", "exe"]}
        status = standalone.status_payload(self.app(SimpleNamespace(app_status=lambda: leaky)),
                                           standalone.RetryPolicy(), {"exists": False})
        self.assertEqual(status["app"], {"id": "figma", "match": "host", "last": {"kept": 1}, "hosts": ["exe"]})
        import json
        text = json.dumps(status)
        self.assertNotIn("Secret design", text)
        self.assertNotIn("figma.com/file", text)

    def test_a_failing_or_missing_app_status(self):
        status = standalone.status_payload(self.app(SimpleNamespace(app_status=lambda: 1 / 0)),
                                           standalone.RetryPolicy(), {"exists": False})
        self.assertEqual(status["app"], {"error": "ZeroDivisionError"})
        status = standalone.status_payload(self.app(SimpleNamespace()), standalone.RetryPolicy(), {"exists": False})
        self.assertIsNone(status["app"])


if __name__ == "__main__":
    unittest.main()
