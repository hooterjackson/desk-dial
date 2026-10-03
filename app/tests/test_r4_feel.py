"""r4 FEEL + SOUND on the Desk Dial side (firmware 1.0.0-cc5.7, plan F2 / F3; firmware HAPTICS.md, CONTROL_CENTER.md).

1. The `feel` token per screen (r4 section 4.4) in every control, sent only to a knob with capabilities.feel 1
   (device._feel_fields), with Reduced haptics and the Knob sounds volume (knobVolume 1: `soundVolume` 0..100 and
   `sound` 0 / 3; knobSound 1 alone: the volume's `sound` level); an older knob's control line has none of them.
2. The frame's `haptic` event per action (r4 4.4: only four things thump; refusals and errors buzz at most once a
   second; Tracks jumps and window snaps nudge their way), kept only for a hapticFx knob (device._frame) and read
   exactly as the firmware reads it (haptic_parse; harness/haptic_fx_tests.py holds the parity table).
3. Walls everywhere, no wrap-around (r4 4.3): every list and range is bounded, Tracks no longer wraps at the queue's
   ends under repeat-all.
4. Settings > Knob (knob_sounds / knob_sound_volume, default 100 / reduced_haptics), the runtime's re-entry on a
   change, status.json `knobFeel`, recalibration (the calibrating / calibrated lines; nothing enters meanwhile), the
   r4 diag fields and `soundVolume`.
Headless: the cc5 / r3 fixtures, never a port or a window.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from r3_support import CAPS_V6, R3Fixture  # noqa: E402
from cc5_support import Fixture, queue_state, recent_page, windows_snapshot  # noqa: E402
from control_center import controller as cmod, device, runtime as rmod  # noqa: E402

CAPS_R4 = {**CAPS_V6, "feel": 1, "hapticFx": 1, "knobSound": 1, "offlineVolume": 1, "recalibration": 1}
CAPS_VOLUME = {**CAPS_R4, "knobVolume": 1}


def control_line(control, caps, volume=0, reduced=False):
    """What DeviceBridge._enter puts on the wire for `control` (the r4 fields only)."""
    bridge = device.DeviceBridge.__new__(device.DeviceBridge)
    bridge.capabilities = caps
    bridge._knob_volume, bridge._reduced_haptics = volume, reduced
    value = dict(control)
    bridge._feel_fields(value)
    return value


class FeelMapTests(R3Fixture):
    """r4 4.4: the turn feel of each screen."""

    def feel(self):
        return self.c.control()["feel"]

    def test_home_volume_and_lights_domain(self):
        self.assertEqual(self.c.screen.mode, "launcher")
        self.assertEqual(self.feel(), "detent.value")
        self.c.hold(3, self.c.control_id)            # hold 4 on Home: the knob swaps to the lights
        self.serve()
        self.assertEqual(self.c.home_domain, "lights")
        self.assertEqual(self.feel(), "detent.dimmer")

    def test_lights_brightness_temperature_and_scenes(self):
        self.lights()
        self.assertEqual(self.c.screen.mode, "lights")
        self.assertEqual(self.feel(), "detent.dimmer")
        self.press(2)                                 # 3: temperature
        self.serve()
        self.assertEqual(self.feel(), "detent.fine")
        self.press(1)                                 # 2: scenes
        self.serve()
        self.assertEqual((self.c.screen.mode, self.feel()), ("scenes", "detent.coarse"))

    def test_music_space_tracks_and_seek(self):
        self.press(0)                                 # Music
        self.tick(0.1)
        self.assertEqual((self.c.screen.mode, self.feel()), ("home", "detent.value"))
        self.press(2)                                 # Tracks
        self.c.drain()
        self.assertEqual((self.c.screen.mode, self.feel()), ("tracks", "detent.list"))
        self.assertEqual(self.c.feel("seek"), "fluid.scrub")
        self.assertEqual(self.c.feel("upnext"), "detent.list")
        self.assertEqual(self.c.feel("windows"), "detent.coarse")

    def test_lists_coast_only_over_twenty_items(self):
        self.press(0)
        self.tick(0.1)
        self.press(1)                                 # Recently Added
        self.complete("recent", recent_page(0, 60, count=25))
        self.c.drain()
        self.assertEqual(self.c.screen.mode, "recent")
        self.assertGreater(self.c._list_count(), cmod.FREE_SPIN_MIN_ITEMS)
        self.assertEqual(self.feel(), "free.spin")
        self.c._list_count = lambda: cmod.FREE_SPIN_MIN_ITEMS   # a list of twenty (or fewer) items clicks without coasting
        self.assertEqual(self.feel(), "detent.list")

    def test_onshape_zooms_in_detents_and_orbits_fluid(self):
        self.assertTrue(self.c.enter_onshape("test"))
        self.c.drain()
        self.assertEqual(self.feel(), "detent.value")
        self.c.feel_supported = True
        before = self.c.control_id
        self.c.onshape_input("down", 1)               # hold 2: orbit
        self.assertEqual(self.feel(), "fluid.light")
        self.assertEqual(self.c.control_id, before + 1, "an r4 knob re-enters for the fluid feel")
        self.c.onshape_input("up", 1)
        self.assertEqual(self.feel(), "detent.value")
        self.assertEqual(self.c.control_id, before + 2)

    def test_onshape_never_re_enters_for_an_older_knob(self):
        self.assertTrue(self.c.enter_onshape("test"))
        self.c.drain()
        before = self.c.control_id
        self.c.onshape_input("down", 1)
        self.c.onshape_input("up", 1)
        self.assertEqual(self.c.control_id, before)

    def test_every_feel_is_a_firmware_token(self):
        for mode in cmod.MODES:
            self.assertIn(self.c.feel(mode), device.FEEL_TOKENS, mode)
        self.assertEqual(set(cmod.FEEL_TOKENS), set(device.FEEL_TOKENS))
        self.assertEqual(set(cmod.HAPTIC_TOKENS), set(device.HAPTIC_TOKENS))


class ControlLineTests(R3Fixture):
    """The r4 fields reach only an r4 knob; the line is otherwise unchanged."""

    def test_older_knob_gets_no_r4_field(self):
        line = control_line(self.c.control(), CAPS_V6, volume=60, reduced=True)
        for name in ("feel", "reducedHaptics", "sound", "soundVolume"):
            self.assertNotIn(name, line)

    def test_r4_knob_gets_feel_reduced_and_sound(self):
        line = control_line(self.c.control(), CAPS_R4, volume=40, reduced=True)
        self.assertEqual((line["feel"], line["reducedHaptics"], line["sound"]), ("detent.value", True, 1))
        self.assertNotIn("soundVolume", line, "a cc5.7 knob without knobVolume gets the level only")

    def test_feel_without_sound_capability(self):
        line = control_line(self.c.control(), {**CAPS_V6, "feel": 1}, volume=100)
        self.assertEqual(line["feel"], "detent.value")
        self.assertNotIn("sound", line)
        self.assertNotIn("soundVolume", line)

    def test_volume_knob_gets_the_volume_and_sound_off_or_high(self):
        for volume, sound in ((0, 0), (5, 3), (40, 3), (41, 3), (100, 3)):
            line = control_line(self.c.control(), CAPS_VOLUME, volume=volume)
            self.assertEqual((line["soundVolume"], line["sound"]), (volume, sound), volume)
            self.assertIs(type(line["soundVolume"]), int)

    def test_sound_knob_gets_the_volume_level(self):
        for volume, sound in ((0, 0), (1, 1), (40, 1), (41, 2), (70, 2), (71, 3), (100, 3)):
            line = control_line(self.c.control(), CAPS_R4, volume=volume)
            self.assertEqual(line["sound"], sound, volume)
            self.assertNotIn("soundVolume", line)
            self.assertEqual(device.sound_level_for_volume(volume), sound)

    def test_volume_without_sound_capability_and_a_stale_field(self):
        # knobVolume alone still sends both (the contract); a soundVolume in the payload never reaches a knob
        # without it.
        line = control_line(self.c.control(), {**CAPS_V6, "knobVolume": 1}, volume=55)
        self.assertEqual((line["soundVolume"], line["sound"]), (55, 3))
        line = control_line({**self.c.control(), "soundVolume": 80}, CAPS_R4, volume=55)
        self.assertEqual(line["sound"], 2)
        self.assertNotIn("soundVolume", line)

    def test_volume_capability(self):
        self.assertTrue(device.knob_volume_capability(CAPS_VOLUME))
        self.assertFalse(device.knob_volume_capability(CAPS_R4))
        self.assertFalse(device.knob_volume_capability({"knobVolume": True}))
        self.assertFalse(device.knob_volume_capability(None))

    def test_invalid_feel_is_stripped(self):
        line = control_line({**self.c.control(), "feel": "wall.bounce"}, CAPS_R4)
        self.assertNotIn("feel", line)
        self.assertIn("sound", line)

    def test_set_knob_feel_validates(self):
        bridge = device.DeviceBridge.__new__(device.DeviceBridge)
        bridge._knob_volume, bridge._reduced_haptics = 0, False
        bridge.set_knob_feel(sound="medium", reduced_haptics=True)
        self.assertEqual((bridge._knob_volume, bridge._reduced_haptics), (70, True), "a level is its top volume")
        bridge.set_knob_feel(sound="loud", reduced_haptics="yes")
        self.assertEqual((bridge._knob_volume, bridge._reduced_haptics), (70, True))
        bridge.set_knob_feel(sound=0)
        self.assertEqual(bridge._knob_volume, 0)
        bridge.set_knob_feel(volume=85)
        self.assertEqual(bridge._knob_volume, 85)
        for bad in (101, -1, 50.0, True, "80", None):
            bridge.set_knob_feel(volume=bad)
            self.assertEqual(bridge._knob_volume, 85, bad)
        bridge.set_knob_feel(sound="low", volume=100)
        self.assertEqual(bridge._knob_volume, 100, "a volume wins over a level")
        bridge.set_knob_feel(volume=0)
        self.assertEqual(bridge._knob_volume, 0)


class HapticFrameTests(R3Fixture):
    """The frame's `haptic` event, gated by hapticFx, parsed as the firmware parses it."""

    def test_kept_only_for_a_hapticfx_knob(self):
        self.c._haptic("confirm.tick")
        self.assertEqual(self.wire(CAPS_R4)["haptic"], {"token": "confirm.tick", "seq": self.c.haptic_seq})
        self.assertNotIn("haptic", self.wire(CAPS_V6))

    def test_invalid_haptic_is_stripped_not_sent(self):
        frame = {"id": self.c.control_id, **self.c.frame(), "haptic": {"token": "boom", "seq": 1}}
        self.assertNotIn("haptic", device._frame(frame, CAPS_R4))
        frame["haptic"] = {"token": "confirm.tick", "seq": True}
        self.assertNotIn("haptic", device._frame(frame, CAPS_R4))

    def test_parse_table(self):
        self.assertEqual(device.haptic_parse({"token": "nudge.left", "seq": 5}), ({"fx": 3, "seq": 5}, True))
        for bad in (None, "confirm.tick", {"token": "confirm.tick"}, {"token": "confirm.tick", "seq": 0},
                    {"token": "confirm.tick", "seq": 2 ** 31}, {"token": "confirm.tick", "seq": 1.0},
                    {"token": "detent.list", "seq": 1}, {"seq": 1}):
            self.assertEqual(device.haptic_parse(bad), (None, False), bad)

    def test_each_event_is_a_new_seq(self):
        self.c._haptic("confirm.tick")
        first = self.c.haptic["seq"]
        self.c._haptic("confirm.tick")
        self.assertEqual(self.c.haptic["seq"], first + 1)
        self.c._haptic("not.a.token")
        self.assertEqual(self.c.haptic["seq"], first + 1)


class HapticEventTests(R3Fixture):
    """r4 4.4's button events."""

    def token(self):
        return self.c.haptic["token"] if self.c.haptic else None

    def test_play_pause_ticks(self):
        self.press(3)                                 # launcher 4: Play / Pause
        self.assertEqual(self.token(), "confirm.tick")

    def test_every_press_ticks(self):
        # 2026-09-30 (the user: every interaction has a sound and a haptic): opening a menu ticks too, and the screen it
        # enters carries the tick in its entry frame; a press with its own event (Turn on thumps) keeps that one.
        self.c.haptic = None
        self.press(0)                                 # Music: opens the Music screen
        self.assertEqual(self.c.screen.mode, "home")
        self.assertEqual(self.token(), "confirm.tick")
        seq = self.c.haptic["seq"]
        self.tick(0.1)
        self.press(1)                                 # another navigation press: a new tick
        self.assertEqual(self.token(), "confirm.tick")
        self.assertNotEqual(self.c.haptic["seq"], seq)

    def test_hold_1_home_thumps(self):
        self.press(0)                                 # Music
        self.tick(0.1)
        self.c.haptic = None
        self.hold()
        self.assertEqual(self.c.screen.mode, "launcher")
        self.assertEqual(self.token(), "confirm.thump")

    def test_domain_swap_landing_thumps(self):
        self.c.hold(3, self.c.control_id)
        self.assertEqual(self.token(), "confirm.thump")

    def test_turn_on_thumps_and_all_off_is_soft(self):
        self.lights()
        self.press(3)                                 # All off (the simulated lights are on)
        self.assertEqual(self.token(), "confirm.off")
        self.serve()
        self.tick(0.1)
        self.press(3)                                 # Turn on
        self.assertEqual(self.token(), "confirm.thump")

    def test_scene_run_thumps_once(self):
        self.lights()
        self.press(1)
        self.serve()
        self.press(3)                                 # Run
        self.assertEqual(self.token(), "confirm.thump")
        seq = self.c.haptic["seq"]
        self.serve()                                  # the scene's result: its green wash, no second event
        self.assertEqual(self.c.haptic["seq"], seq)

    def test_refusals_buzz_at_most_once_a_second(self):
        self.c._refuse(1, "no_scenes")
        self.assertEqual(self.token(), "refuse.buzz")
        seq = self.c.haptic["seq"]
        self.tick(0.5)
        self.c._refuse(1, "no_scenes")
        self.assertEqual(self.c.haptic["seq"], seq, "a second refusal within 1 s does not buzz")
        self.tick(0.6)
        self.c._refuse(1, "no_scenes")
        self.assertEqual(self.c.haptic["seq"], seq + 1)

    def test_default_moment_mapping(self):
        f = cmod.Controller._feedback_haptic
        self.assertEqual(f("err", 0, "refused", None), "refuse.buzz")
        self.assertEqual(f("err", 0, None, None), "error.buzz")
        self.assertEqual(f("ok", 1, None, None), "nudge.right")
        self.assertEqual(f("ok", -1, None, None), "nudge.left")
        self.assertEqual(f("ok", 0, "snap", -1), "nudge.left")
        self.assertEqual(f("ok", 0, "snap", 1), "nudge.right")
        self.assertEqual(f("ok", 0, "queued", None), "confirm.thump")
        self.assertEqual(f("ok", 0, "started", None), "confirm.thump")
        self.assertEqual(f("ok", 0, "shuffle", None), "confirm.tick")
        self.assertEqual(f("ok", 0, "like", None), "confirm.tick")
        self.assertEqual(f("ok", 0, None, None), "confirm.tick")

    def test_only_four_things_thump(self):
        """r4 4.4 thump budget: the sources of confirm.thump in controller.py are exactly the hold landings (hold 1,
        the domain swap, the list / Up next queue at the hold), Play (a started list), Turn on and Scene run."""
        source = (HERE.parent / "control_center" / "controller.py").read_text(encoding="utf-8")
        explicit = source.count('"confirm.thump"')
        # FEEDBACK default (queued / started) + hold 1 + domain swap + Turn on + Scene run + the HAPTIC_TOKENS tuple.
        self.assertEqual(explicit, 6, "a new thump source needs the design's thump budget (r4 4.4)")


class TracksNoWrapTests(Fixture):
    """r4 4.3: the queue's ends are walls, repeat-all or not."""

    def test_next_at_the_end_is_refused_under_repeat_all(self):
        self.publish(queue_state(P=12, T=12, repeat="all", play_mode="REPEAT_ALL"))
        self.press(2)                                 # Tracks (the presentation-5 Home: 3)
        self.c.drain()
        self.turn_to(2)
        self.assertEqual(self.frame()["subtitle"], "End of queue")
        self.assertEqual(self.c._queue_end(2), "end")
        self.assertEqual(self.c._queue_end(0), None)

    def test_previous_at_the_start_is_refused_under_repeat_all(self):
        self.publish(queue_state(P=1, T=12, repeat="all", play_mode="REPEAT_ALL", track_id="track-1"))
        self.press(2)
        effects = self.c.drain()
        self.assertFalse([e for e in effects if e.get("purpose") == "tracks_last"], "no wrap neighbour is read")
        self.turn_to(0)
        self.assertEqual(self.frame()["subtitle"], "Start of queue")
        self.assertEqual(self.c._queue_end(0), "start")

    def test_the_wrap_copy_is_gone(self):
        self.assertNotIn("knob.line.tracks.next_wrap", cmod.COPY)

    def test_volume_is_bounded(self):
        low, high, _ = self.c.bounds()
        self.assertEqual((low, high), (0, 100))       # volume: 0 / 100 walls

    def test_every_list_bound_is_its_first_and_last_item(self):
        self.browse(total=60, count=25)
        low, high, _ = self.c.bounds()
        self.assertEqual((low, high), (0, self.c._list_count() - 1))


class SettingsTests(unittest.TestCase):
    """Settings > Knob: the effective volume (and the old level), the runtime's re-entry, status.json."""

    def test_effective_sound(self):
        self.assertEqual(rmod.knob_sound_setting({}), "low")
        self.assertEqual(rmod.knob_sound_setting({"knob_sounds": False, "knob_sound_level": "high"}), "off")
        self.assertEqual(rmod.knob_sound_setting({"knob_sounds": True, "knob_sound_level": "high"}), "high")
        self.assertEqual(rmod.knob_sound_setting({"knob_sound_level": "loud"}), "low")
        self.assertEqual(rmod.normal_knob_sound("medium"), "medium")
        self.assertEqual(rmod.normal_knob_sound(3), "low")

    def test_effective_volume_defaults_to_100(self):
        self.assertEqual(rmod.DEFAULT_KNOB_VOLUME, 100)
        self.assertEqual(rmod.knob_volume_setting({}), 100)
        self.assertEqual(rmod.knob_volume_setting(None), 100)
        # A settings.json from before the volume (a level, no volume) starts at 100 %.
        self.assertEqual(rmod.knob_volume_setting({"knob_sounds": True, "knob_sound_level": "low"}), 100)
        self.assertEqual(rmod.knob_volume_setting({"knob_sounds": True, "knob_sound_volume": 35}), 35)
        self.assertEqual(rmod.knob_volume_setting({"knob_sounds": False, "knob_sound_volume": 35}), 0)
        self.assertEqual(rmod.knob_volume_setting({"knob_sound_volume": 0}), 0)
        for bad in (101, -5, 50.5, True, "80", None):
            self.assertEqual(rmod.knob_volume_setting({"knob_sound_volume": bad}), 100, bad)
        self.assertEqual([rmod.knob_sound_for_volume(v) for v in (0, 1, 40, 41, 70, 71, 100)],
                         ["off", "low", "low", "medium", "medium", "high", "high"])

    def runtime(self, caps=CAPS_R4):
        class Bridge:
            def __init__(self):
                self.calls = []
                self.capabilities = caps

            def set_knob_feel(self, **values):
                self.calls.append(values)

        runtime = rmod.Runtime.__new__(rmod.Runtime)
        runtime.device = Bridge()
        runtime.knob_volume, runtime.knob_sound, runtime.reduced_haptics = 100, "high", False
        runtime.feel_capable, runtime.volume_capable = True, device.knob_volume_capability(caps)
        runtime.device_connected, runtime.device_supported = True, True
        runtime.calibrating = False
        runtime.calibration_result = None
        entered = self.entered = []

        class C:
            def _request_passive(self, cause, now_if_waiting=False):
                entered.append(cause)
        runtime._controller = C()
        runtime.dispatch = lambda: None
        return runtime

    def test_runtime_sends_the_volume_and_re_enters_once_per_change(self):
        runtime = self.runtime(CAPS_VOLUME)
        runtime.set_knob_feel(volume=55)
        self.assertEqual(runtime.device.calls[-1], {"volume": 55, "reduced_haptics": False})
        self.assertEqual(self.entered, ["knob feel"])
        runtime.set_knob_feel(volume=55)
        self.assertEqual(self.entered, ["knob feel"], "no change, no re-entry")
        runtime.set_knob_feel(volume=0)
        self.assertEqual((runtime.device.calls[-1]["volume"], self.entered), (0, ["knob feel"] * 2))
        runtime.set_knob_feel(volume=250)                 # invalid: the default (100)
        self.assertEqual(runtime.knob_volume, 100)
        runtime.set_knob_feel(sound="medium")             # an older caller's level: its top volume
        self.assertEqual((runtime.knob_volume, runtime.knob_sound), (70, "medium"))

    def test_knob_feel_status(self):
        runtime = self.runtime(CAPS_VOLUME)
        runtime.set_knob_feel(volume=35, reduced_haptics=True)
        status = runtime.knob_feel_status()
        self.assertEqual({k: status[k] for k in ("volume", "sound", "reducedHaptics", "capable", "volumeCapable")},
                         {"volume": 35, "sound": "low", "reducedHaptics": True, "capable": True,
                          "volumeCapable": True})
        self.assertIs(type(status["volume"]), int)
        self.assertEqual(self.runtime(CAPS_R4).knob_feel_status()["volumeCapable"], False)
        import standalone
        self.assertEqual(standalone._knob_feel_status(runtime), status)

    def test_a_new_runtime_starts_at_100(self):
        from unittest.mock import patch
        from control_center.simulation import SimulatedAppleMusic, SimulatedSonos, SimulatedWindows
        from test_cc_controller import FakeDevice, ManualExecutor
        with patch.object(rmod, "ThreadPoolExecutor", ManualExecutor):
            runtime = rmod.Runtime(cmod.Controller(), SimulatedSonos(), SimulatedAppleMusic(), SimulatedWindows(),
                                   FakeDevice())
            self.addCleanup(runtime.shutdown)
        status = runtime.knob_feel_status()
        self.assertEqual((status["volume"], status["sound"], status["volumeCapable"]), (100, "high", False))

    def test_an_older_callers_level_re_enters_once_per_change(self):
        runtime = self.runtime(CAPS_R4)
        runtime.set_knob_feel(sound="low", reduced_haptics=True)
        self.assertEqual(runtime.device.calls[-1], {"volume": 40, "reduced_haptics": True})
        self.assertEqual(self.entered, ["knob feel"])
        runtime.set_knob_feel(sound="low", reduced_haptics=True)
        self.assertEqual(self.entered, ["knob feel"], "no change, no re-entry")
        self.assertEqual(runtime.knob_feel_status()["sound"], "low")

    def test_load_config_defaults(self):
        from control_center.ui import ControlCenterApp
        config = ControlCenterApp.load_config()
        self.assertIn(config["knob_sounds"], (True, False))
        self.assertIn(config["knob_sound_level"], rmod.KNOB_SOUND_LEVELS)
        self.assertIn(config["knob_sound_volume"], range(0, 101))
        self.assertIn(config["reduced_haptics"], (True, False))

    def test_load_config_volume_migration(self):
        import json
        import tempfile
        from unittest.mock import patch
        from control_center import ui
        with tempfile.TemporaryDirectory() as temp, patch.object(ui, "DATA_DIR", Path(temp)):
            settings = Path(temp) / "settings.json"
            self.assertEqual(ui.ControlCenterApp.load_config()["knob_sound_volume"], 100, "no file")
            settings.write_text(json.dumps({"knob_sounds": True, "knob_sound_level": "low"}), encoding="utf-8")
            config = ui.ControlCenterApp.load_config()
            self.assertEqual((config["knob_sound_volume"], config["knob_sound_level"]), (100, "low"),
                             "a file from before the volume starts at 100 % and keeps its level")
            settings.write_text(json.dumps({"knob_sound_volume": 45}), encoding="utf-8")
            self.assertEqual(ui.ControlCenterApp.load_config()["knob_sound_volume"], 45)
            settings.write_text(json.dumps({"knob_sound_volume": "loud"}), encoding="utf-8")
            self.assertEqual(ui.ControlCenterApp.load_config()["knob_sound_volume"], 100)
            settings.write_text(json.dumps({"knob_sounds": False, "knob_sound_volume": 45}), encoding="utf-8")
            app = object.__new__(ui.ControlCenterApp)
            app.config = ui.ControlCenterApp.load_config()
            sent = []
            ui.ControlCenterApp._apply_presentation(app, SimpleNamespace(
                windows=None, set_knob_feel=lambda **values: sent.append(values)))
            self.assertEqual(sent, [{"volume": 0, "reduced_haptics": False}], "Off sends 0")


class KnobVolumeSettingsTests(unittest.TestCase):
    """Settings > Knob: the volume slider (0..100 %, step 5) beside Knob sounds On / Off, on stand-in widgets (no
    Tk). Both apply and save at once (the slider on release); Save keeps the volume."""

    def setUp(self):
        import json
        import tempfile
        from unittest.mock import patch
        from control_center import ui
        from test_cc_controller import FakeScale, FakeVariable, FakeWidget
        self.ui, self.json = ui, json
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data_dir = Path(temp.name)
        self.made, self.labels = [], []

        def button(parent, text, command, **kwargs):
            self.made.append(("button", text, command))
            return FakeWidget()

        def label(parent, text="", *args, **kwargs):
            widget = FakeWidget(text=text, **kwargs)
            self.labels.append(widget)
            return widget

        def scale(*args, **kwargs):
            widget = FakeScale(*args, **kwargs)
            self.made.append(("scale", widget))
            return widget
        for target, name, value in (
            (ui, "DATA_DIR", self.data_dir), (ui, "button", button), (ui, "label", label),
            (ui.tk, "Toplevel", FakeWidget), (ui.tk, "Frame", FakeWidget), (ui.tk, "Entry", FakeWidget),
            (ui.tk, "StringVar", FakeVariable), (ui.tk, "Scale", scale),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sent = []
        app = self.app = object.__new__(ui.ControlCenterApp)
        app.root, app.setup_window, app.auth = FakeWidget(), None, None
        app.runtime = SimpleNamespace(device_connected=True, device_supported=True, button_order=[0, 1, 2, 3],
                                      on_button_probe=None, windows=None,
                                      set_knob_feel=lambda **values: self.sent.append(values))
        app.controller = SimpleNamespace(ready=True)

    def open(self, settings=None):
        if settings is not None:
            (self.data_dir / "settings.json").write_text(self.json.dumps(settings), encoding="utf-8")
        self.app.config = self.ui.ControlCenterApp.load_config()
        self.app.setup()
        at = next(i for i, made in enumerate(self.made) if made[0] == "scale")
        self.slider = self.made[at][1]
        on, off = self.made[at - 2], self.made[at - 1]          # Knob sounds On / Off, just before the slider
        self.assertEqual((on[1], off[1]), ("On", "Off"))
        self.sounds = {"on": on[2], "off": off[2]}
        self.percent = next(w for w in self.labels if str(w.values.get("text", "")).endswith(" %"))

    def saved(self):
        return self.json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))

    def test_the_slider_starts_at_100_and_steps_by_5(self):
        self.open()
        values = self.slider.values
        self.assertEqual((values["from_"], values["to"], values["resolution"]), (0, 100, 5))
        self.assertEqual((self.slider.get(), self.percent.values["text"]), (100, "100 %"))
        self.assertNotIn("Sound level", [w.values.get("text") for w in self.labels], "the level is gone")

    def test_release_applies_and_saves_the_volume(self):
        self.open({"knob_sounds": True, "knob_sound_level": "medium", "speaker_ip": "192.0.2.120"})
        self.assertEqual(self.slider.get(), 100, "an older file starts at 100 %")
        self.slider.set(35)
        self.assertEqual(self.percent.values["text"], "35 %")
        self.assertEqual(self.sent, [], "dragging sends nothing")
        self.slider.bindings["<ButtonRelease-1>"](None)
        self.assertEqual(self.sent, [{"volume": 35}])
        self.assertEqual((self.saved()["knob_sound_volume"], self.saved()["knob_sounds"]), (35, True))
        self.sounds["off"]()
        self.assertEqual(self.sent[-1], {"volume": 0}, "Off sends 0")
        self.assertEqual((self.saved()["knob_sound_volume"], self.saved()["knob_sounds"]), (35, False))
        self.sounds["on"]()
        self.assertEqual(self.sent[-1], {"volume": 35})
        self.slider.set(0)
        self.slider.bindings["<KeyRelease>"](None)
        self.assertEqual(self.sent[-1], {"volume": 0})
        self.slider.set(80)
        next(made[2] for made in self.made if made[0] == "button" and made[1] == "Save settings")()
        saved = self.saved()
        self.assertEqual((saved["knob_sound_volume"], saved["knob_sounds"], saved["knob_sound_level"]),
                         (80, True, "medium"), "Save keeps the volume; the old level is kept as it was")


class RecalibrationTests(unittest.TestCase):
    """The calibrating / calibrated lines and the runtime's hold on entries."""

    def bridge(self):
        bridge = device.DeviceBridge.__new__(device.DeviceBridge)
        import queue
        bridge.events = queue.Queue()
        bridge.calibrating = False
        bridge.control_id = None
        bridge.ready_id = None
        return bridge

    def test_lines_become_events(self):
        bridge = self.bridge()
        bridge._consume({"calibrating": True})
        self.assertTrue(bridge.calibrating)
        bridge._consume({"calibrated": {"ok": False, "reason": "direction-changed"}})
        self.assertFalse(bridge.calibrating)
        events = [bridge.events.get_nowait() for _ in range(2)]
        self.assertEqual([e["kind"] for e in events], ["calibrating", "calibrated"])
        self.assertEqual((events[1]["ok"], events[1]["reason"]), (False, "direction-changed"))
        bridge._consume({"calibrated": {"ok": True, "reason": "weird"}})
        event = bridge.events.get_nowait()
        self.assertEqual((event["ok"], event["reason"]), (True, ""))

    def test_capability(self):
        self.assertTrue(device.recalibration_capability(CAPS_R4))
        self.assertFalse(device.recalibration_capability(CAPS_V6))
        self.assertFalse(device.recalibration_capability({"recalibration": True}))


class DiagTests(unittest.TestCase):
    def test_r4_fields(self):
        fields, invalid = device.diag_parse({
            "supplyVolts": 5, "feel": "detent.list", "reducedHaptics": False, "soundLevel": 1, "fxPlayed": 3,
            "fxPulses": 10, "fxDropped": 0, "wallHits": 4, "wallDir": -1, "foldbackPct": 100, "foldbackEvents": 0,
            "tripLatched": False, "spinTrips": 0, "offlineVolume": False, "calState": "idle", "calOutcome": "",
            "audioReady": True, "audioPlayed": 7, "audioUnderruns": 0, "audioDropped": 0})
        self.assertEqual(invalid, [])
        self.assertEqual(len(fields), len(device.DIAG_R4_FIELDS))
        fields, invalid = device.diag_parse({"feel": "wall.bounce", "wallDir": 2, "foldbackPct": 101,
                                            "calState": "busy", "tripLatched": 1, "soundLevel": 4})
        self.assertEqual(fields, {})
        self.assertEqual(sorted(invalid), sorted(["feel", "soundLevel", "wallDir", "foldbackPct", "tripLatched",
                                                  "calState"]))

    def test_sound_volume(self):
        self.assertIn("soundVolume", device.DIAG_FIELDS)
        for good in (0, 55, 100):
            self.assertEqual(device.diag_parse({"soundVolume": good}), ({"soundVolume": good}, []), good)
        for bad in (101, -1, 50.0, True, "100"):
            self.assertEqual(device.diag_parse({"soundVolume": bad}), ({}, ["soundVolume"]), bad)
        fields, invalid = device.diag_parse({"soundLevel": 3, "soundVolume": 100})
        self.assertEqual((fields, invalid), ({"soundLevel": 3, "soundVolume": 100}, []))


if __name__ == "__main__":
    unittest.main()
