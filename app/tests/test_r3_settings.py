"""Desk Dial r3 release 1: the Home Assistant settings (settings.json keys, the dialog's validation, the
status strip's fourth column, the providers). No Tk, no credential store, no network.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import ui  # noqa: E402
from control_center.controller import LightsState  # noqa: E402
from control_center.simulation import SimControls, SimulatedHomeAssistant  # noqa: E402


class ConfigTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data_dir = Path(temp.name)
        patcher = patch.object(ui, "DATA_DIR", self.data_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, value):
        (self.data_dir / "settings.json").write_text(json.dumps(value), encoding="utf-8")

    def test_defaults(self):
        config = ui.ControlCenterApp.load_config()
        self.assertEqual((config["ha_base_url"], config["ha_light_entity"], config["ha_scenes"]), ("", "", []))
        self.assertEqual(config["ha_area"], "")
        self.assertNotIn("ha_token", config, "the token is never a setting")

    def test_the_area_is_validated(self):
        self.write({"ha_base_url": "http://ha.local:8123", "ha_area": "demo"})
        self.assertEqual(ui.ControlCenterApp.load_config()["ha_area"], "demo")
        for bad in ("Demo", "demo area", "../x", 7, ""):
            self.write({"ha_area": bad})
            with self.subTest(bad=bad):
                self.assertEqual(ui.ControlCenterApp.load_config()["ha_area"], "")

    def test_values_are_validated(self):
        self.write({"ha_base_url": "http://homeassistant.local:8123/", "ha_light_entity": "light.demo",
                    "ha_scenes": [{"entity_id": "scene.focus", "label": "Focus"}, {"entity_id": "switch.x"}],
                    "ha_token": "must-not-load"})
        config = ui.ControlCenterApp.load_config()
        self.assertEqual(config["ha_base_url"], "http://homeassistant.local:8123")
        self.assertEqual(config["ha_light_entity"], "light.demo")
        self.assertEqual(config["ha_scenes"], [{"entity_id": "scene.focus", "type": "scene", "label": "Focus"}])
        self.assertNotIn("ha_token", config)
        self.write({"ha_base_url": "ftp://x", "ha_light_entity": "switch.demo", "ha_scenes": "nope"})
        config = ui.ControlCenterApp.load_config()
        self.assertEqual((config["ha_base_url"], config["ha_light_entity"], config["ha_scenes"]), ("", "", []))


class FormTests(unittest.TestCase):
    def test_valid_form(self):
        values = ui.ha_form_values(" http://ha.local:8123/ ", "light.demo",
                                   [("scene.focus", "Focus"), ("script.movie", "Movie")], token="tok")
        self.assertEqual(values, {"ha_base_url": "http://ha.local:8123", "ha_area": "", "ha_light_entity": "light.demo",
                                  "ha_scenes": [{"entity_id": "scene.focus", "type": "scene", "label": "Focus"},
                                                {"entity_id": "script.movie", "type": "script", "label": "Movie"}]})

    def test_the_area_is_preferred_and_scenes_are_optional(self):
        values = ui.ha_form_values("http://ha.local:8123", "light.desk", [], token="tok", area="demo")
        self.assertEqual(values, {"ha_base_url": "http://ha.local:8123", "ha_area": "demo", "ha_light_entity": "",
                                  "ha_scenes": []})
        self.assertEqual(ui.ha_form_values("http://ha.local:8123", "", [], saved_token=True, area="demo")["ha_area"],
                         "demo")
        with self.assertRaises(ValueError):
            ui.ha_form_values("http://ha.local:8123", "", [], token="tok")          # neither an area nor a light
        with self.assertRaises(ValueError):
            ui.ha_form_values("http://ha.local:8123", "", [], token="tok", area="Demo Room")

    def test_area_choices_default_to_demo(self):
        areas = [("demo", "Demo", 3), ("kitchen", "Kitchen", 1)]
        choices, chosen = ui.ha_area_choices(areas)
        self.assertEqual(choices, [("demo", "Demo · 3 lights"), ("kitchen", "Kitchen · 1 light")])
        self.assertEqual(chosen, "demo")
        self.assertEqual(ui.ha_area_choices(areas, "kitchen")[1], "kitchen", "the saved area wins")
        self.assertEqual(ui.ha_area_choices([("office", "Office", 2)])[1], "office", "no Demo: the first")
        choices, chosen = ui.ha_area_choices(areas, "attic")
        self.assertEqual((choices[-1], chosen), (("attic", "attic (not found) · 0 lights"), "attic"),
                         "a saved area HA no longer lists stays selected, marked")
        self.assertEqual(ui.ha_area_choices([]), ([], ""))

    def test_a_saved_token_can_be_kept(self):
        self.assertTrue(ui.ha_form_values("http://ha.local:8123", "light.demo", [], saved_token=True))

    def test_invalid_forms(self):
        for args in (("", "light.demo", []), ("http://ha.local:8123", "switch.demo", []),
                     ("http://ha.local:8123", "light.demo", [])):
            with self.subTest(args=args), self.assertRaises(ValueError):
                ui.ha_form_values(*args, token="" if args[0] and args[1] == "light.demo" else "tok")


class StripTests(unittest.TestCase):
    def runtime(self, ha=True, **lights):
        state = LightsState(**lights)
        return SimpleNamespace(device_connected=True, device_supported=True, music_signin_expired=False,
                               apple=None, ha=object() if ha else None,
                               controller=SimpleNamespace(state={"online": True, "source": "queue",
                                                                 "room_label": "Demo"}, lights=state))

    def test_a_runtime_without_the_bridge_keeps_three_columns(self):
        stand_in = SimpleNamespace(device_connected=False, device_supported=False, controller=None, apple=None)
        self.assertEqual(len(ui.strip_model(stand_in)), 3)

    def test_the_fourth_column(self):
        column = ui.strip_model(self.runtime(ha=False))[3]
        self.assertEqual((column["name"], column["state"], column["detail"], column["key"], column["ok"]),
                         ("Home Assistant", "Not connected", "Add your address and token below", "home_assistant",
                          False), "r3.1 copy")
        column = ui.ha_strip_column(self.runtime(configured=True, online=True, reason="", known=True, on=True,
                                                 name="Demo lights",
                                                 scenes=[{"entity_id": "scene.a"}, {"entity_id": "scene.b"}]))
        self.assertEqual((column["ok"], column["state"], column["detail"]), (True, "Connected", "Demo lights · 2 scenes"))
        column = ui.ha_strip_column(self.runtime(configured=True, online=False, reason="auth", known=True))
        self.assertEqual((column["state"], column["primary"]), ("Token rejected", True))
        column = ui.ha_strip_column(self.runtime(configured=True, online=False, reason="offline", known=True))
        self.assertEqual(column["state"], "Not reachable")

    def test_the_area_column(self):
        ha = SimulatedHomeAssistant(SimControls(), area="demo")
        runtime = self.runtime(configured=True, online=True, reason="", known=True, on=True, name="Demo",
                               scenes=[{"entity_id": "scene.a"}])
        runtime.ha = ha
        column = ui.ha_strip_column(runtime)
        self.assertEqual((column["ok"], column["state"], column["detail"]), (True, "Connected", "Demo · 3 lights · 1 scene"))
        for entity in list(ha.members()):
            ha.move_light(entity, "kitchen")
        runtime.controller.lights = LightsState(configured=True, online=False, reason="unavailable", known=True)
        column = ui.ha_strip_column(runtime)
        self.assertEqual(column["state"], "No lights in Demo")
        ha.area_id = "attic"
        column = ui.ha_strip_column(runtime)
        self.assertEqual((column["state"], column["primary"]), ("Area not found", True))

    def test_no_column_text_carries_a_token(self):
        column = ui.ha_strip_column(self.runtime(configured=True, online=True, reason="", known=True))
        self.assertNotIn("token-", json.dumps(column))


# DD-BUG-037: a saved token belongs to the saved address (settings.json writes both on Save).
SAVED = {"ha_base_url": ui.HA_DEFAULT_ADDRESS}


class SettingsPageModelTests(unittest.TestCase):
    """Settings > Home Assistant (Claude Design r3.1 C1): the page's logic without Tk."""

    def probe(self, model):
        ha = SimulatedHomeAssistant(SimControls(), area="demo")
        base, error = model.begin_test()
        self.assertIsNone(error)
        self.assertEqual(model.status_line(), (f"Connecting to {model.address.strip()}…", "#FFBE69"))
        self.assertEqual(model.test_label(), "Testing…")
        self.assertTrue(model.finish_test(ha.test_connection(), model.generation))
        return ha

    def test_defaults_and_the_untested_status(self):
        model = ui.HaSettingsModel({})
        self.assertEqual(model.address, "http://homeassistant.local:8123")
        self.assertEqual(model.status_line(), ("Not tested since the last change", ui.TERTIARY))
        self.assertEqual(model.placeholder(), "Test the connection to see the lights and scenes in your area.")
        self.assertEqual(model.test_label(), "Test connection")
        self.assertFalse(model.can_save)
        self.assertIsNone(model.lists())
        with self.assertRaises(ValueError):
            model.save_values()

    def test_a_successful_test_lists_the_demo_and_enables_save(self):
        model = ui.HaSettingsModel(SAVED, saved_token=True)
        self.probe(model)
        self.assertEqual(model.status_line(), ("Connected · Home Assistant 2026.9 (simulated) · token valid", ui.OK))
        self.assertEqual(model.area, "demo", "Demo by default")
        self.assertEqual(model.area_choices(), [("demo", "Demo"), ("kitchen", "Kitchen"), ("office", "Office")])
        lists = model.lists()
        self.assertEqual(lists["lights_head"], "Lights in Demo · 3")
        self.assertEqual(lists["lights"][0], ("Desk lamp", "62% · 3200 K", ui.OK, ui.SECONDARY))
        self.assertEqual(lists["lights"][2], ("Shelf strip", "62%", ui.OK, ui.SECONDARY), "no colour temperature")
        self.assertEqual(lists["scenes_head"], "Scenes, scripts and automations · 5")
        self.assertEqual(lists["scenes"][2], ("Movie", "SCRIPT"))
        self.assertEqual((lists["lights_empty"], lists["scenes_empty"]), ("", ""))
        self.assertTrue(model.can_save)
        self.assertEqual(model.save_values(), {"ha_base_url": "http://homeassistant.local:8123", "ha_area": "demo",
                                               "ha_light_entity": ""}, "ha_scenes is left as it is")
        model.mark_saved(100.0)
        self.assertEqual(model.saved_text(101.0), "Saved · the knob now controls Demo")
        self.assertEqual(model.saved_text(102.6), "")

    def test_rows_off_unavailable_and_empty_areas(self):
        model = ui.HaSettingsModel(SAVED, saved_token=True)
        ha = SimulatedHomeAssistant(SimControls(), area="demo")
        ha.external(on=False, entity="light.demo_floor")
        ha.set_available("light.demo_shelf", False)
        model.begin_test()
        model.finish_test(ha.test_connection(), model.generation)
        lights = model.lists()["lights"]
        self.assertEqual(lights[1], ("Floor lamp", "Off", ui.RULE, ui.SECONDARY))
        self.assertEqual(lights[2], ("Shelf strip", "Unavailable", ui.ERROR, ui.ERROR))
        model.choose_area("office")
        self.assertEqual(model.status, "ok", "changing the area keeps the test status")
        lists = model.lists()
        self.assertEqual(lists["lights_head"], "Lights in Office · 0")
        self.assertEqual(lists["lights_empty"], "No lights in Office yet. Assign lights to this area in Home Assistant "
                                                "and they appear here and on the knob automatically.")
        self.assertEqual(lists["scenes_empty"], "No scenes, scripts or automations in this area.")

    def test_edits_reset_the_status_and_cancel_reverts_the_area(self):
        model = ui.HaSettingsModel({"ha_base_url": "http://ha.local:8123", "ha_area": "kitchen"}, saved_token=True)
        self.probe(model)
        self.assertEqual(model.area, "kitchen", "the saved area stays chosen")
        model.choose_area("demo")
        model.cancel()
        self.assertEqual(model.area, "kitchen", "Cancel reverts the area choice")
        model.edit_token("new-token")
        self.assertEqual(model.status_line()[0], "Not tested since the last change")
        self.assertFalse(model.can_save)
        self.probe(model)
        model.edit_address("http://ha.local:8124")
        self.assertEqual((model.status, model.can_save), ("idle", False))
        model.edit_address("http://ha.local:8124")                  # the same text: no reset needed
        self.assertEqual(model.status, "idle")

    def test_errors(self):
        model = ui.HaSettingsModel({"ha_base_url": "http://ha.local:8123"})
        self.assertEqual(model.begin_test(), (None, ui.HA_TOKEN_REJECTED), "no token at all")
        model.edit_token("tok")
        base, _ = model.begin_test()
        self.assertEqual(base, "http://ha.local:8123")
        model.finish_test({"ok": False, "outcome": "offline"}, model.generation)
        self.assertEqual(model.status_line(), ("Can’t reach http://ha.local:8123. Check the address and that Home "
                                               "Assistant is running.", ui.ERROR))
        self.assertEqual(model.placeholder(), "Fix the connection to see what’s in your area.")
        model.begin_test()
        model.finish_test({"ok": False, "outcome": "auth"}, model.generation)
        self.assertEqual(model.status_line(), ("Token rejected (401). Create a long-lived access token in your Home "
                                               "Assistant profile.", ui.ERROR))
        model.edit_address("homeassistant.local")
        self.assertEqual(model.begin_test()[0], None)
        self.assertIn("Can’t reach homeassistant.local.", model.status_line()[0])

    def test_a_late_result_after_an_edit_is_ignored(self):
        model = ui.HaSettingsModel(SAVED, saved_token=True)
        model.begin_test()
        generation = model.generation
        model.edit_address("http://other:8123")
        self.assertFalse(model.finish_test({"ok": True, "areas": [("demo", "Demo", 1)]}, generation))
        self.assertEqual(model.status, "idle")

    def test_show_hide(self):
        model = ui.HaSettingsModel({})
        model.toggle_token()
        self.assertTrue(model.show_token)
        model.toggle_token()
        self.assertFalse(model.show_token)

    def test_the_pages(self):
        self.assertEqual([title for _key, title in ui.SETTINGS_PAGES],
                         ["General", "Music", "Windows", "Home Assistant", "Knob", "Apps"])


class ProviderTests(unittest.TestCase):
    def test_the_simulator_gets_the_simulated_home_assistant(self):
        app = object.__new__(ui.ControlCenterApp)
        app.sim_controls = SimControls()
        ha = ui.ControlCenterApp.ha_provider(app, False)
        self.assertIsInstance(ha, SimulatedHomeAssistant)
        self.assertEqual((ha.area_id, ha.read_state()["count"]), ("demo", 3), "r3.1: the simulator's multi-light Demo")

    def test_live_without_settings_builds_nothing_and_reads_no_credentials(self):
        app = object.__new__(ui.ControlCenterApp)
        app.config = {"ha_base_url": "", "ha_light_entity": "", "ha_scenes": []}
        with patch("control_center.credentials.CredentialStore.load",
                   side_effect=AssertionError("the store must not be read")):
            self.assertIsNone(ui.ControlCenterApp.ha_provider(app, True))
            app.config = {"ha_base_url": "http://ha.local:8123", "ha_area": "", "ha_light_entity": ""}
            with self.assertLogs("control_center.home_assistant", "INFO") as logs:
                self.assertIsNone(ui.ControlCenterApp.ha_provider(app, True))
            self.assertIn("no area chosen", " ".join(logs.output), "why Lights are not set up is logged")

    def test_every_new_mode_has_a_description(self):
        for mode in ("launcher", "lights", "scenes"):
            self.assertIn(mode, ui.MODE_DESCRIPTIONS)



class StandInVar:
    """tk.StringVar without Tk (get / set / trace_add)."""

    def __init__(self, value="", **_kwargs):
        self.value = value
        self.traces = []

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        for callback in self.traces:
            callback("", "", "write")

    def trace_add(self, _mode, callback):
        self.traces.append(callback)


class SettingsWindowPagesTests(unittest.TestCase):
    """The r3.1 Settings window on stand-in widgets (no Tk, no credential store, no network): every
    page builds, the Home Assistant page is built on its first show, and its Test / Save / Cancel
    run against the simulator's Home Assistant."""

    def setUp(self):
        from unittest.mock import MagicMock
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data_dir = Path(temp.name)
        self.buttons = {}
        self.vars = []
        self.saved_tokens = []
        test = self

        class Store:
            def __init__(self, *_args, **_kwargs):
                pass

            def load(self):
                return {}

            def save(self, credentials):
                test.saved_tokens.append(dict(credentials))

        def button(parent, text, command, **kwargs):
            self.buttons[text] = command
            return MagicMock()

        def variable(*args, **kwargs):
            var = StandInVar(*args, **kwargs)
            self.vars.append(var)
            return var
        for target, name, value in (
            (ui, "DATA_DIR", self.data_dir), (ui, "button", button), (ui, "label", lambda *a, **k: MagicMock()),
            (ui.tk, "Toplevel", lambda *a, **k: MagicMock()), (ui.tk, "Frame", lambda *a, **k: MagicMock()),
            (ui.tk, "Entry", lambda *a, **k: MagicMock()), (ui.tk, "OptionMenu", lambda *a, **k: MagicMock()),
            (ui.tk, "Scale", lambda *a, **k: MagicMock()),
            (ui.tk, "StringVar", variable), (ui, "show_fitted", lambda *a, **k: None),
            (ui.ControlCenterApp, "_refresh_strip", lambda self: None),
            (ui.ControlCenterApp, "_schedule_strip", lambda self, win: None),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch("control_center.credentials.CredentialStore", Store)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ha = SimulatedHomeAssistant(SimControls(), area="demo")
        app = self.app = object.__new__(ui.ControlCenterApp)
        app.root, app.setup_window, app.auth = MagicMock(), None, None
        app.chrome, app.setup_actions, app.live = True, None, False
        app.config = ui.ControlCenterApp.load_config()
        app.runtime = SimpleNamespace(ha=self.ha, device_status="", on_button_probe=None, device_supported=True,
                                      windows=None)
        app.controller = SimpleNamespace(ready=True)

    def test_every_page_builds_and_the_settings_save_as_before(self):
        self.app.setup()
        for title in ("General", "Music", "Windows", "Home Assistant", "Knob", "Save settings",
                      "Authorize Apple Music", "Verify physical button order", "Warm only", "Frosted"):
            self.assertIn(title, self.buttons)
        self.assertEqual(self.vars[2].get(), "0,1,2,3", "the button order keeps its StringVar position")
        for key, _title in ui.SETTINGS_PAGES:
            self.app._setup_open_page(key)
        self.buttons["Warm only"]()
        self.buttons["Save settings"]()
        saved = json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["led_style"], "white")

    def test_the_home_assistant_page(self):
        self.app.home_assistant_settings()                  # opens Settings on the Home Assistant page
        model = self.app.ha_model
        self.assertEqual(model.status, "idle")
        self.buttons["Save"]()                               # not tested yet: nothing happens
        self.assertFalse((self.data_dir / "settings.json").exists())
        self.buttons["Test connection"]()
        self.assertEqual((model.status, model.area), ("ok", "demo"))
        self.assertEqual(model.lists()["lights_head"], "Lights in Demo · 3")
        model.choose_area("kitchen")
        self.buttons["Cancel"]()
        self.assertEqual(model.area, "demo", "Cancel reverts the area (none was saved: the default)")
        address, token = self.vars[-3], self.vars[-2]      # the page's address and token fields
        token.set("a-new-token")
        self.assertEqual(model.status, "idle", "a token edit needs a new test")
        self.buttons["Test connection"]()
        model.choose_area("kitchen")
        self.buttons["Save"]()
        saved = json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual((saved["ha_area"], saved["ha_base_url"], saved["ha_light_entity"]),
                         ("kitchen", "http://homeassistant.local:8123", ""))
        self.assertNotIn("a-new-token", json.dumps(saved), "the token never goes to settings.json")
        self.assertEqual(self.saved_tokens[-1].get("ha_token"), "a-new-token", "it goes to the credential store")
        self.assertEqual(self.ha.area_id, "kitchen", "the simulator now drives the saved area")
        self.assertTrue(model.saved_text(model.saved_at).startswith("Saved · the knob now controls Kitchen"))
        address.set("http://ha.local:8123")
        self.assertEqual(model.address, "http://ha.local:8123")


if __name__ == "__main__":
    unittest.main()


class HaResyncTests(unittest.TestCase):
    """2026-09-30: the controller's lights view is re-read from the adapter's cached state every
    HA_RESYNC_S, so a failed lights_read can't leave the Settings strip at Not connected."""

    def test_resync_hands_the_cached_state_to_the_controller(self):
        from types import SimpleNamespace
        from control_center.runtime import Runtime
        seen = []
        rt = SimpleNamespace(ha=SimpleNamespace(read_state=lambda: {"configured": True, "online": True}),
                             controller=SimpleNamespace(lights_state=seen.append), HA_RESYNC_S=Runtime.HA_RESYNC_S)
        Runtime._ha_resync(rt, 100.0)
        Runtime._ha_resync(rt, 105.0)                      # within the interval: nothing
        Runtime._ha_resync(rt, 100.0 + Runtime.HA_RESYNC_S + 0.1)
        self.assertEqual(len(seen), 2)
        self.assertTrue(seen[0]["online"])

    def test_no_adapter_is_a_no_op(self):
        from types import SimpleNamespace
        from control_center.runtime import Runtime
        rt = SimpleNamespace(ha=None, controller=None, HA_RESYNC_S=Runtime.HA_RESYNC_S)
        Runtime._ha_resync(rt, 1.0)
