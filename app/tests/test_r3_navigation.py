"""Desk Dial r3 release 1: the spaces navigation (README 1, options 1a + 1e) and the r2.2 fallback.

Presentation >= 6: the launcher Home (1 Music · 2 Windows · 3 Lights · 4 Play/Pause), the Music space
(today's Home with 1 Home · 2 Recently Added · 3 Tracks · 4 Play/Pause), Windows straight from Home 2,
the Lights space; hold 1 = the launcher. Presentation < 6: r2.2 exactly (no Lights entry).
"""
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cc5_support import Clock, Fixture, FakeDevice, ManualExecutor, queue_state, recent_page, windows_snapshot  # noqa: E402
from r3_support import CAPS_V5, CAPS_V6, R3Fixture  # noqa: E402
from control_center import device, presentation, runtime as runtime_module  # noqa: E402
from control_center.controller import Controller, MODES  # noqa: E402
from control_center.runtime import Runtime  # noqa: E402
from control_center.simulation import (SimControls, SimulatedAppleMusic, SimulatedHomeAssistant,  # noqa: E402
                                       SimulatedSonos, SimulatedWindows)


class R22FallbackTests(Fixture):
    """Without presentation 6 nothing changes: r2.2's Home, no Lights, F24 on Home."""

    def test_home_keeps_the_r22_map(self):
        self.assertFalse(self.c.spaces)
        self.assertEqual([(i, l) for i, l, _ in self.labels()],
                         [("pause", "Pause"), ("list", "Browse"), ("tracks", "Tracks"), ("win", "Win")])
        self.assertTrue(self.c.control()["windowsHidEnabled"])

    def test_no_lights_entry_and_hold_stays_home(self):
        self.press(2)
        self.assertEqual(self.c.screen.mode, "tracks", "r2.2 Home 3 is Tracks")
        self.hold()
        self.assertEqual(self.c.screen.mode, "home")
        self.assertNotIn("lights", [e.get("kind") for e in self.c.drain()])

    def test_set_spaces_off_leaves_an_r3_space_for_home(self):
        self.c.set_spaces(True)
        self.assertEqual(self.c.screen.mode, "launcher")
        self.c.set_spaces(False)
        self.assertEqual(self.c.screen.mode, "home")


class LauncherTests(R3Fixture):
    def test_launcher_buttons_and_idle_row(self):
        self.assertEqual(self.c.screen.mode, "launcher")
        self.assertEqual([(i, l) for i, l, _ in self.labels()],
                         [("list", "Music"), ("win", "Win"), ("bulb", "Lights"), ("pause", "Pause")])
        control = self.c.control()
        # r3 (2026-09-29 hardware fix): F24 comes from the launcher's Win slot (button 2), whose F24 grant is the
        # only way Windows lets the picker take the foreground; button 4 is Play/Pause.
        self.assertTrue(control["windowsHidEnabled"])
        self.assertEqual(control["windowsButton"], self.c.button_order[1])
        self.assertEqual((control["profile"], control["min"], control["max"]), ("BINARIS BEER", 0, 100))
        wire = self.wire()
        self.assertEqual(wire["layout"], "nowPlaying")
        self.assertEqual([b["icon"] for b in wire["buttons"]], ["list", "win", "bulb", "pause"])

    def test_knob_is_volume_on_the_launcher(self):
        self.turn_to(40)
        self.assertEqual(self.c.desired_volume, 40)
        self.assertEqual(self.frame()["layout"], "volume")

    def test_button_4_is_play_pause(self):
        self.press(3)
        effect = self.one("transport")
        self.assertEqual(effect["direction"], "pause")

    def test_button_1_opens_music_and_music_1_returns(self):
        self.press(0)
        self.assertEqual(self.c.screen.mode, "home")
        self.assertEqual([(i, l) for i, l, _ in self.labels()],
                         [("house", "Home"), ("album", "Recent"), ("tracks", "Tracks"), ("pause", "Pause")])
        self.assertEqual(self.wire()["heading"], "MUSIC")
        self.turn_to(35)
        self.assertEqual(self.c.desired_volume, 35, "Music keeps the volume knob")
        self.press(3)
        self.assertEqual(self.one("transport")["direction"], "pause")
        self.press(0)
        self.assertEqual(self.c.screen.mode, "launcher")

    def test_music_deeper_levels_back_to_music_and_hold_to_launcher(self):
        self.press(0)
        self.press(1)
        self.assertEqual(self.c.screen.mode, "recent")
        self.complete("recent", recent_page(0, 30))
        self.press(0)
        self.assertEqual(self.c.screen.mode, "home", "Recently Added 1 = Back → Music")
        self.press(2)
        self.assertEqual(self.c.screen.mode, "tracks")
        self.press(0)
        self.assertEqual(self.c.screen.mode, "home", "Tracks 1 = Back → Music")
        self.press(2)
        self.hold()
        self.assertEqual(self.c.screen.mode, "launcher", "hold 1 = Home (the launcher)")
        self.press(0)
        self.hold()
        self.assertEqual(self.c.screen.mode, "launcher", "hold 1 at the Music root = Home")

    def test_music_play_goes_to_music(self):
        self.press(0)
        self.press(1)
        self.complete("recent", recent_page(0, 30))
        self.press(3)
        self.assertEqual(self.c.screen.mode, "home", "a start lands on the now-playing Music space")

    def test_windows_opens_from_home_2_and_returns_home(self):
        self.press(1)
        effect = self.one("windows_open")
        self.c.complete(effect["request"], windows_snapshot(4))
        self.assertEqual(self.c.screen.mode, "windows")
        self.press(0)
        self.assertEqual(self.c.screen.mode, "launcher", "the picker's 1 returns Home")
        self.press(1)
        effect = self.one("windows_open")
        self.c.complete(effect["request"], windows_snapshot(4))
        self.press(3)
        activate = self.one("windows_activate")
        self.c.complete(activate["request"], True)
        self.assertEqual(self.c.screen.mode, "launcher", "Switch → Home")

    def test_windows_hold_returns_to_the_launcher(self):
        self.press(1)
        effect = self.one("windows_open")
        self.c.complete(effect["request"], windows_snapshot(4))
        self.hold()
        self.assertEqual(self.c.screen.mode, "launcher")

    def test_lights_entry_and_exits(self):
        self.lights()
        self.assertEqual(self.c.screen.mode, "lights")
        self.press(0)
        self.assertEqual(self.c.screen.mode, "launcher", "Lights 1 = Home")
        self.lights()
        self.press(1)
        self.assertEqual(self.c.screen.mode, "scenes")
        self.press(0)
        self.assertEqual(self.c.screen.mode, "lights", "Scenes 1 = Back → Lights")
        self.press(1)
        self.hold()
        self.assertEqual(self.c.screen.mode, "launcher", "hold 1 from Scenes = Home")

    def test_reconnect_and_disconnect_land_on_the_launcher(self):
        self.lights()
        self.c.disconnected()
        self.assertEqual(self.c.screen.mode, "launcher")
        self.c.set_hardware(True)
        self.assertEqual(self.c.screen.mode, "launcher")

    def test_every_new_frame_validates_for_presentation_6(self):
        for step in ("launcher", "music", "lights", "scenes"):
            with self.subTest(step=step):
                self.wire()
                if step == "launcher":
                    self.press(0)
                elif step == "music":
                    self.press(0)
                    self.lights()
                elif step == "lights":
                    self.press(1)

    def test_a_v6_frame_downgrades_for_presentation_5(self):
        self.press(0)
        wire = self.wire(CAPS_V5)
        self.assertEqual([b["icon"] for b in wire["buttons"]], ["home", "list", "tracks", "pause"])
        self.press(0)
        self.lights()
        wire = self.wire(CAPS_V5)
        self.assertEqual(wire["layout"], "recent")
        self.assertEqual(wire["ring"]["style"], "off")
        self.assertTrue(all(b.get("icon", "") in presentation.ICONS for b in wire["buttons"]))
        stored, invalid = device.v5_parse(wire)
        self.assertEqual(invalid, [], "a cc5.4 parser accepts the downgrade")


class ModeTablesTests(unittest.TestCase):
    def test_every_mode_has_a_profile_title_frame_and_buttons(self):
        from control_center import controller as module
        for mode in MODES:
            with self.subTest(mode=mode):
                self.assertIn(mode, module.PROFILES)
                self.assertIn(mode, module.MODE_TITLES)
                self.assertTrue(hasattr(Controller, "_frame_" + mode))
                self.assertTrue(hasattr(Controller, "_buttons_" + mode))
                self.assertTrue(hasattr(Controller, "_press_" + mode))


class RuntimeCapabilityTests(unittest.TestCase):
    """The runtime turns r3 on for presentation 6 only, and carries the HA state stream."""

    def make(self, level, ha=None):
        with patch.object(runtime_module, "ThreadPoolExecutor", ManualExecutor):
            self.device = FakeDevice()
            controller = Controller(clock=Clock(), rng=random.Random(3))
            runtime = Runtime(controller, SimulatedSonos(), SimulatedAppleMusic(), SimulatedWindows(), self.device,
                              ha=ha)
        self.addCleanup(runtime.shutdown)
        self.device.events.put({"kind": "connected", "capabilities": {"controlCenter": True, "presentation": level}})
        runtime.poll()
        return runtime

    def test_presentation_6_turns_the_spaces_on(self):
        runtime = self.make(6, SimulatedHomeAssistant(SimControls()))
        self.assertTrue(runtime.controller.spaces)
        self.assertEqual(runtime.controller.screen.mode, "launcher")
        enter = [c for c in self.device.commands if c[0] == "enter"][-1][1]
        self.assertFalse(enter["windowsHidEnabled"])
        self.assertEqual([b["icon"] for b in enter["frame"]["buttons"]][2], "bulb")

    def test_presentation_5_keeps_r22(self):
        runtime = self.make(5, SimulatedHomeAssistant(SimControls()))
        self.assertFalse(runtime.controller.spaces)
        self.assertEqual(runtime.controller.screen.mode, "home")
        enter = [c for c in self.device.commands if c[0] == "enter"][-1][1]
        self.assertEqual([b["icon"] for b in enter["frame"]["buttons"]][1:], ["list", "tracks", "win"])

    def test_the_state_stream_reaches_the_controller(self):
        ha = SimulatedHomeAssistant(SimControls())
        runtime = self.make(6, ha)
        ha.external(bri=21)
        runtime.poll()
        self.assertEqual(runtime.controller.lights.bri, 21)
        self.assertTrue(runtime.controller.lights.online)

    def test_lights_jobs_run_on_the_home_lane_and_read_the_newest_target(self):
        ha = SimulatedHomeAssistant(SimControls())
        runtime = self.make(6, ha)
        c = runtime.controller
        c.device_ready(c.control_id)
        runtime.poll()
        c.button(2, c.control_id)          # Lights
        runtime.dispatch()
        runtime.home_lane.run_all()
        runtime.poll()
        c.device_ready(c.control_id)
        c.position(69, c.control_id)       # 70 % (while on, position = level - 1)
        c.tick()
        runtime.dispatch()
        self.assertEqual(len(runtime.home_lane.jobs), 1, "one lights_set on nanod-home, not the audio lane")
        c.position(74, c.control_id)       # a later detent before the job starts (75 %)
        runtime.home_lane.run_all()
        runtime.poll()
        self.assertEqual(ha.calls[-1], ("light", "turn_on", {"entity_id": "light.demo", "brightness_pct": 75}))
        self.assertEqual([call for call in ha.calls if call[1] == "turn_on"].__len__(), 1)

    def test_without_home_assistant_lights_say_not_set_up(self):
        runtime = self.make(6, None)
        c = runtime.controller
        c.device_ready(c.control_id)
        c.button(2, c.control_id)
        runtime.dispatch()
        runtime.home_lane.run_all()
        runtime.poll()
        frame = c.frame()
        self.assertEqual((frame["title"], frame["subtitle"]), ("Not connected", "Home Assistant"))   # r3.1 design


if __name__ == "__main__":
    unittest.main()
