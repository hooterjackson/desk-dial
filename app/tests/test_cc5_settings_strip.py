"""K3 14.1 / 14.3 (WP10): the Settings status strip and the Motion setting.

Headless: the strip's model (``ui.strip_model``) over stand-in runtimes, its Tk widget over stand-in
widgets, the action routing, and the effective Motion value through the real runtime (``set_motion``,
the 5 s backstop and the stage's ``system(motion)``). No Tk, window, port or network.
"""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import runtime as runtime_module  # noqa: E402
from control_center import ui  # noqa: E402
from control_center.controller import Controller  # noqa: E402
from control_center.runtime import Runtime  # noqa: E402
from control_center.simulation import SimulatedAppleMusic, SimulatedSonos, SimulatedWindows  # noqa: E402

OK, PROBLEM = "#6ED996", "#FF7A66"


def runtime(connected=True, supported=True, online=True, source="queue", host="192.168.1.40",
            expired=False, signed_in=True, room="Den"):
    state = {"online": online, "room_label": room, "source": source, "host": host}
    apple = SimpleNamespace(has_credentials=lambda: signed_in)
    return SimpleNamespace(device_connected=connected, device_supported=supported, device_status="Knob ready",
                           controller=SimpleNamespace(state=state), music_signin_expired=expired, apple=apple)


class StripModelTests(unittest.TestCase):
    """Three columns x states, the copy of VOC 9.3 / 9.5 and K3 14.1's sources of truth."""

    def column(self, rt, index, **kwargs):
        return ui.strip_model(rt, **kwargs)[index]

    def test_three_columns_in_order(self):
        self.assertEqual([c["name"] for c in ui.strip_model(runtime())], ["Knob", "Sonos", "Apple Music"])

    def test_knob_ok_and_problem(self):
        knob = self.column(runtime(), 0, firmware="1.0.0-cc5.4")
        self.assertEqual((knob["ok"], knob["state"], knob["detail"], knob["action"], knob["key"]),
                         (True, "Connected", "USB · firmware 1.0.0-cc5.4", "Knob settings…",
                          "knob_settings"))
        self.assertEqual(self.column(runtime(), 0)["detail"], "USB", "no version: none invented")
        for rt in (runtime(connected=False), runtime(supported=False)):
            knob = self.column(rt, 0)
            self.assertEqual((knob["ok"], knob["state"], knob["action"], knob["key"]),
                             (False, "Not connected", "Troubleshoot…", "troubleshoot"))
            self.assertEqual(knob["detail"], "Waiting for the knob on USB. The knob’s own controls still work.")
            self.assertNotIn("Nano_D", knob["detail"])       # Desk Dial (VOC-R32): the column is titled Knob

    def test_sonos_source_phrases_and_problem(self):
        phrases = {"queue": "Playing from the Sonos queue", "airplay": "Playing via AirPlay", "radio": "Playing radio",
                   "linein": "Playing line-in", "none": "Idle"}
        for source, phrase in phrases.items():
            with self.subTest(source=source):
                sonos = self.column(runtime(source=source), 1)
                self.assertEqual((sonos["ok"], sonos["state"], sonos["detail"]),
                                 (True, "Den", f"{phrase} · 192.168.1.40"))
                self.assertEqual((sonos["action"], sonos["key"]), ("Set manual IP…", "manual_ip"))
        self.assertEqual(self.column(runtime(source="podcast"), 1)["detail"], "Idle · 192.168.1.40")
        self.assertEqual(self.column(runtime(host=""), 1, speaker_ip="10.0.0.9")["detail"],
                         "Playing from the Sonos queue · 10.0.0.9", "the configured IP when the state has no host")
        sonos = self.column(runtime(online=False), 1)
        self.assertEqual((sonos["ok"], sonos["state"], sonos["detail"], sonos["action"]),
                         (False, "Not found", "Can’t reach Sonos on this network", "Set manual IP…"))

    def test_apple_music_signed_in_expired_and_none(self):
        apple = self.column(runtime(), 2)
        self.assertEqual((apple["ok"], apple["state"], apple["detail"], apple["action"], apple["primary"]),
                         (True, "Signed in", "Library and likes available", "Renew sign-in…", False))
        apple = self.column(runtime(expired=True), 2)
        self.assertEqual((apple["ok"], apple["state"], apple["action"], apple["key"], apple["primary"]),
                         (False, "Sign-in expired", "Renew sign-in…", "renew_signin", True))
        self.assertEqual(apple["detail"], "Like and Favourite playlists are paused until you sign in again.")
        apple = self.column(runtime(signed_in=False), 2)
        self.assertEqual((apple["ok"], apple["state"], apple["action"], apple["key"], apple["primary"]),
                         (False, "Not signed in", "Sign in…", "sign_in", True))
        self.assertEqual(apple["detail"], "Sign in to use Recently Added, Favourite playlists and Like.")
        self.assertEqual(self.column(runtime(expired=True, signed_in=False), 2)["state"], "Sign-in expired",
                         "an expiry the runtime saw wins")

    def test_a_failing_credential_check_is_not_signed_in(self):
        rt = runtime()
        rt.apple = SimpleNamespace(has_credentials=lambda: (_ for _ in ()).throw(OSError("store locked")))
        self.assertEqual(self.column(rt, 2)["state"], "Not signed in")
        rt.apple = object()                             # the simulator's client has no credentials check
        self.assertEqual(self.column(rt, 2)["state"], "Signed in")

    def test_the_firmware_version_is_read_once_from_the_connect_inventory(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "control-center-inventory.json"
            path.write_text(json.dumps({"settings": {"firmwareVersion": "1.0.0-cc5.4", "deviceName": "x"}}),
                            encoding="utf-8")
            device = SimpleNamespace(backup_path=path)
            self.assertEqual(ui.firmware_version(device), "1.0.0-cc5.4")
            path.write_text("{}", encoding="utf-8")
            self.assertEqual(ui.firmware_version(device), "1.0.0-cc5.4", "cached per connection")
            self.assertIsNone(ui.firmware_version(SimpleNamespace(backup_path=Path(temp) / "missing.json")))
        self.assertIsNone(ui.firmware_version(SimpleNamespace()))
        self.assertIsNone(ui.firmware_version(None))


class Widget:
    """A stand-in Tk widget: records configure and pack; never creates a window."""

    def __init__(self, *args, **kwargs):
        self.values = dict(kwargs)
        self.packed = False

    def configure(self, **kwargs):
        self.values.update(kwargs)

    def pack(self, *args, **kwargs):
        self.packed = True

    def pack_forget(self):
        self.packed = False


class StripWidgetTests(unittest.TestCase):
    def build(self):
        self.buttons = []

        def button(parent, text, command, **kwargs):
            widget = Widget(text=text, command=command, **kwargs)
            self.buttons.append(widget)
            return widget
        with patch.object(ui.tk, "Frame", Widget), patch.object(ui, "label", lambda *a, **k: Widget(**k)), \
                patch.object(ui, "button", button):
            self.calls = []
            strip = ui.SettingsStrip(Widget(), {key: (lambda key=key: self.calls.append(key))
                                                for key in ("knob_settings", "troubleshoot", "manual_ip",
                                                            "renew_signin", "sign_in")})
        return strip

    def test_marks_states_actions_and_the_primary_button(self):
        strip = self.build()
        self.assertTrue(strip.update(ui.strip_model(runtime(expired=True))))
        self.assertFalse(strip.update(ui.strip_model(runtime(expired=True))), "unchanged: nothing repainted")
        marks = [column["mark"].values["bg"] for column in strip.columns]
        self.assertEqual(marks, [OK, OK, PROBLEM])
        self.assertEqual([column["name"].values["text"] for column in strip.columns], ["KNOB", "SONOS", "APPLE MUSIC"])
        self.assertEqual(strip.columns[2]["action"].values["text"], "Renew sign-in…")
        self.assertEqual(strip.columns[2]["action"].values["bg"], ui.TEXT, "a primary light button")
        self.assertEqual(strip.columns[0]["action"].values["bg"], ui.SURFACE)
        for widget in self.buttons:
            widget.values["command"]()
        self.assertEqual(self.calls, ["knob_settings", "manual_ip", "renew_signin"])
        strip.update(ui.strip_model(runtime(connected=False, online=False, signed_in=False)))
        self.calls.clear()
        for widget in self.buttons:
            widget.values["command"]()
        self.assertEqual(self.calls, ["troubleshoot", "manual_ip", "sign_in"])
        self.assertEqual([column["mark"].values["bg"] for column in strip.columns], [PROBLEM] * 3)

    def test_the_troubleshoot_detail_shows_under_the_strip(self):
        strip = self.build()
        strip.show_detail("Stock firmware · display/control extension required")
        self.assertTrue(strip.detail.packed)
        self.assertEqual(strip.detail.values["text"], "Stock firmware · display/control extension required")
        strip.show_detail("")
        self.assertFalse(strip.detail.packed)


class InlineExecutor:
    def __init__(self, *args, **kwargs):
        pass

    def submit(self, function, *args):
        from concurrent.futures import Future
        future = Future()
        try:
            future.set_result(function(*args))
        except BaseException as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, wait=True, cancel_futures=False):
        pass


class MotionTests(unittest.TestCase):
    """K3 14.3: system follows Windows Animation effects, full / reduced are fixed; re-evaluated at
    once by set_motion and by the stage's system(motion), every 5 s as the backstop."""

    def make(self, probe):
        with patch.object(runtime_module, "ThreadPoolExecutor", InlineExecutor):
            rt = Runtime(Controller(), SimulatedSonos(), SimulatedAppleMusic(), SimulatedWindows(), motion_probe=probe)
        self.addCleanup(rt.shutdown)
        return rt

    def test_effective_motion(self):
        self.assertFalse(ui.effective_motion("full", lambda: True))
        self.assertTrue(ui.effective_motion("reduced", lambda: False))
        self.assertTrue(ui.effective_motion("system", lambda: True))
        self.assertFalse(ui.effective_motion("system", lambda: False))
        self.assertFalse(ui.effective_motion("system", lambda: 1 / 0), "a failing probe keeps full motion")

    def test_the_setting_applies_at_once_and_system_follows_windows(self):
        windows_off = {"value": False}
        rt = self.make(lambda: windows_off["value"])
        rt.set_motion("reduced")
        self.assertTrue(rt.reduced_motion and rt.controller.reduced_motion)
        rt.set_motion("full")
        self.assertFalse(rt.reduced_motion)
        rt.set_motion("system")
        self.assertFalse(rt.reduced_motion)
        windows_off["value"] = True
        rt._presenter_events()                                # nothing new yet: the backstop waits 5 s
        self.assertFalse(rt.reduced_motion)
        rt._events.append({"kind": "system", "what": "motion"})
        rt._presenter_events()                                # the stage saw SPI_SETCLIENTAREAANIMATION
        self.assertTrue(rt.reduced_motion and rt.controller.reduced_motion)
        rt.set_motion("bogus")
        self.assertEqual(rt.motion_setting, "system", "an unknown value is Match Windows")

    def test_the_stage_tuple_form_of_system_motion(self):
        state = {"value": False}
        rt = self.make(lambda: state["value"])
        rt.set_motion("system")
        state["value"] = True
        rt.stage = SimpleNamespace(take_events=lambda: [("system", {"kind": "motion", "t0": 1.0})])
        rt._presenter_events()
        self.assertTrue(rt.reduced_motion)

    def test_settings_keep_and_validate_the_motion_key(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as temp, patch.object(ui, "DATA_DIR", Path(temp)):
            self.assertEqual(ui.ControlCenterApp.load_config()["motion"], "system")
            for stored, loaded in (("reduced", "reduced"), ("full", "full"), ("Reduced", "system"), (1, "system")):
                (Path(temp) / "settings.json").write_text(json.dumps({"motion": stored}), encoding="utf-8")
                self.assertEqual(ui.ControlCenterApp.load_config()["motion"], loaded, stored)
        self.assertEqual([text for text, _value in ui.MOTION_CHOICES], ["Match Windows", "Full", "Reduced"])

    def test_apply_presentation_hands_the_setting_to_the_runtime_and_the_picker_follows(self):
        applied = []
        app = SimpleNamespace(config={"motion": "reduced", "led_style": "color", "artwork": True,
                                      "picker_background": "glass"})
        app._picker_background = lambda: "glass"
        rt = SimpleNamespace(windows=None, set_motion=applied.append, apply_led_tuning=lambda config: None)
        ui.ControlCenterApp._apply_presentation(app, rt)
        self.assertEqual(applied, ["reduced"])
        picker = []
        app = SimpleNamespace(runtime=SimpleNamespace(reduced_motion=True, windows=SimpleNamespace(
            set_reduced_motion=picker.append)), fast_path=None, _presenter_motion=None)
        ui.ControlCenterApp._sync_presenters(app)
        ui.ControlCenterApp._sync_presenters(app)
        self.assertEqual(picker, [True], "sent once per change")


if __name__ == "__main__":
    unittest.main()
