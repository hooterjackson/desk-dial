"""Desk Dial r3 release 1: the Lights space (README 1.2, 2.2, 3, 6, 7) on the SimulatedHomeAssistant.

Brightness 1 % per detent (writes <= 10 Hz, the final value on settle), temperature 100 K per detent
clamped to the group's range, turn-on from off, All off (snapshot + off) / Turn on (the snapshot),
the external-change reveal, the Scenes list, the allowlist refusal and the offline / sign-in copy.
Every frame is also validated as the bridge sends it to a presentation-6 knob.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r3_support import R3Fixture  # noqa: E402
from control_center import presentation  # noqa: E402
from control_center.controller import EXTERNAL_REVEAL_SECONDS, VOLUME_REVEAL_SECONDS  # noqa: E402
from control_center.home_assistant import HomeAssistantError  # noqa: E402


class BrightnessTests(R3Fixture):
    def setUp(self):
        super().setUp()
        self.lights()

    def test_rest_screen(self):
        wire = self.wire()
        self.assertEqual((wire["layout"], wire["heading"], wire["title"], wire["subtitle"]),
                         ("lights", "LIGHTS", "Demo", "62% · 3200 K"))
        self.assertEqual(wire["ring"], {"style": "bri", "value": 62, "index": 0, "count": 0, "kelvin": 3200})
        self.assertEqual([(b["icon"], b["label"]) for b in wire["buttons"]],
                         [("house", "Home"), ("wand", "Scenes"), ("thermo", "Temp"), ("power", "All off")])
        control = self.c.control()
        self.assertEqual((control["profile"], control["min"], control["max"], control["position"]),
                         ("BINARIS BEER", 0, 99, 61), "while on 0..99 = 1..100 % (min is always 0; 0 = the 1 % floor)")

    def test_one_percent_per_detent_and_the_big_reveal(self):
        self.turn_to(62)                       # one detent up from 62 % (position 61)
        wire = self.wire()
        self.assertEqual((wire["layout"], wire["volumeCaption"], wire["value"], wire["valueUnit"]),
                         ("lightsbig", "Brightness", "63", "%"))
        self.assertEqual(wire["ring"]["style"], "bri")
        self.tick()
        self.serve()
        self.assertEqual(self.ha.calls[-1], ("light", "turn_on", {"entity_id": "light.demo", "brightness_pct": 63}))
        self.tick(VOLUME_REVEAL_SECONDS + 0.1)
        self.assertEqual(self.wire()["layout"], "lights")
        self.assertEqual(self.c.lights.bri, 63)

    def test_writes_are_coalesced_to_ten_per_second_and_the_last_value_lands(self):
        sent = []
        position = 62
        for step in range(40):                 # 40 detents over 1 s (25 ms apart)
            position += 1
            self.turn_to(position)
            self.tick(0.025)
            for effect in [e for e in self.c.drain() if e["kind"] == "lights_set"]:
                sent.append(self.clock())
                # The lane takes the newest target when the job starts, a little later.
                self.serve([effect])
        for _ in range(10):
            self.tick(0.1)
            for effect in [e for e in self.c.drain() if e["kind"] == "lights_set"]:
                sent.append(self.clock())
                self.serve([effect])
        gaps = [b - a for a, b in zip(sent, sent[1:])]
        self.assertTrue(all(gap >= 0.1 - 1e-9 for gap in gaps), gaps)
        self.assertLessEqual(len(sent), 11)
        self.assertEqual(self.ha.bri, 100, "the final value is sent on settle")
        self.assertEqual(self.c.lights_intent(), {})

    def test_the_lowest_level_is_one_percent(self):
        self.c.position(0, self.c.control_id)
        self.tick()
        self.serve()
        self.assertEqual(self.ha.bri, 1)
        self.assertEqual(self.c.bounds(), (0, 99, 0), "the contract's min (the bridge and the knob reject any other)")

    def test_turning_while_off_turns_on_at_one_percent(self):
        self.press(3)
        self.serve()
        self.assertFalse(self.ha.on)
        self.tick(1.0)
        self.serve()
        self.assertEqual(self.c.bounds(), (0, 100, 0), "from off the knob starts at 0")
        wire = self.wire()
        self.assertEqual((wire["title"], wire["subtitle"], wire["ring"]["style"]),
                         ("Lights off", "Tap 4 to turn on", "off"))
        self.assertEqual(wire["buttons"][3]["label"], "Turn on")
        self.turn_to(1)
        self.tick()
        self.serve()
        self.assertTrue(self.ha.on)
        self.assertEqual(self.ha.calls[-1], ("light", "turn_on", {"entity_id": "light.demo", "brightness_pct": 1}))

    def test_an_external_change_shows_for_2_6_s(self):
        self.tick(5)
        self.serve()
        self.ha.external(bri=30)
        self.c.lights_state(self.ha.read_state())
        wire = self.wire()
        # The firmware draws the lights 12 px line from `meta` (lightsbig included).
        self.assertEqual((wire["layout"], wire["value"], wire["meta"], wire["metaTone"]),
                         ("lightsbig", "30", "Changed in Home Assistant", "secondary"))
        self.tick(EXTERNAL_REVEAL_SECONDS - 0.2)
        self.assertEqual(self.wire()["layout"], "lightsbig")
        self.tick(0.3)
        self.assertEqual(self.wire()["layout"], "lights")
        # The knob follows (a passive re-entry once it has rested).
        self.tick(0.5)
        self.assertEqual(self.c.control()["position"], 29)

    def test_our_own_echo_is_not_an_external_change(self):
        self.turn_to(70)
        self.tick()
        self.serve()
        self.tick(VOLUME_REVEAL_SECONDS + 0.1)
        self.c.lights_state(self.ha.read_state())       # the event of our own write
        self.assertEqual(self.wire()["layout"], "lights")
        self.assertNotEqual(self.c._lights_reveal_source, "external")


class TemperatureTests(R3Fixture):
    def setUp(self):
        super().setUp()
        self.lights()
        self.press(2)
        self.c.drain()

    def test_temperature_mode(self):
        wire = self.wire()
        self.assertEqual(wire["buttons"][2]["lit"], "on", "button 3 lit warm while active")
        self.assertEqual((wire["meta"], wire["metaTone"]), ("Knob: temperature", "warm"))
        self.assertEqual(wire["ring"]["style"], "ctemp")
        self.assertEqual(wire["ring"]["kelvin"], 3200)
        self.assertEqual(wire["ring"]["value"], round((3200 - 2200) * 100 / 4300))
        control = self.c.control()
        self.assertEqual((control["profile"], control["min"], control["max"], control["position"]),
                         ("MIDI SKIPPER", 0, 43, 10), "100 K per detent over 2200..6500")

    def test_one_hundred_kelvin_per_detent(self):
        self.turn_to(13)
        wire = self.wire()
        self.assertEqual((wire["layout"], wire["volumeCaption"], wire["value"], wire["valueUnit"]),
                         ("lightsbig", "Colour temperature", "3500", "K"))
        self.tick()
        self.serve()
        self.assertEqual(self.ha.calls[-1], ("light", "turn_on", {"entity_id": "light.demo", "color_temp_kelvin": 3500}))

    def test_range_clamped_to_the_group(self):
        self.ha.min_k, self.ha.max_k = 2700, 4000
        self.c.lights_state(self.ha.read_state())
        self.tick(1.0)
        self.assertEqual(self.c.bounds()[:2], (0, 13), "(4000 - 2700) / 100 + 1 positions")
        self.c.position(13, self.c.control_id)
        self.assertEqual(self.c.lights_intent(), {"kelvin": 4000})

    def test_turning_temperature_while_off_turns_on_at_the_stored_level(self):
        self.press(3)
        self.serve()
        self.tick(1.0)
        self.serve()
        low, high, position = self.c.bounds()
        self.turn_to(position + 2)
        self.tick()
        self.serve()
        self.assertTrue(self.ha.on)
        self.assertEqual(self.ha.calls[-1], ("light", "turn_on", {"entity_id": "light.demo",
                                                                  "color_temp_kelvin": 3400,
                                                                  "brightness_pct": 62}))

    def test_tapping_3_again_returns_to_brightness(self):
        self.press(2)
        wire = self.wire()
        self.assertNotIn("lit", wire["buttons"][2])
        self.assertEqual((wire["meta"], wire["metaTone"]), ("Knob: brightness", "warm"))
        self.assertEqual(self.c.control()["profile"], "BINARIS BEER")

    def test_entering_lights_from_home_starts_in_brightness(self):
        self.press(0)
        self.lights()
        self.assertEqual(self.c.lights_mode, "bri")


class PowerTests(R3Fixture):
    def setUp(self):
        super().setUp()
        self.lights()

    def test_all_off_snapshots_then_turns_off_and_turn_on_restores_it(self):
        self.press(3)
        self.serve()
        self.assertEqual([call[:2] for call in self.ha.calls],
                         [("scene", "create"), ("light", "turn_off")])
        self.assertEqual(self.ha.calls[0][2], {"scene_id": "desk_dial_snapshot",
                                               "snapshot_entities": ["light.demo"]})
        wire = self.wire()
        self.assertEqual((wire["title"], wire["meta"]), ("Lights off", "Lights off"))
        self.assertEqual(wire["buttons"][3]["icon"], "power")
        self.press(3)
        self.serve()
        self.assertEqual(self.ha.calls[-1], ("scene", "turn_on", {"entity_id": "scene.desk_dial_snapshot"}))
        self.assertTrue(self.ha.on)
        self.assertEqual(self.wire()["subtitle"], "62% · 3200 K")

    def test_power_button_is_white_never_red(self):
        tone = presentation.button_tone_v5(3, "power", True)
        self.assertEqual(tone, "nav")


class ScenesTests(R3Fixture):
    def setUp(self):
        super().setUp()
        self.lights()
        self.press(1)
        self.c.drain()

    def test_scenes_list_frame(self):
        self.turn_to(1)
        wire = self.wire()
        self.assertEqual((wire["layout"], wire["heading"], wire.get("prevTitle"), wire["title"], wire.get("nextTitle")),
                         ("scenes", "SCENES", "Focus", "Evening", "Movie"))
        self.assertEqual(wire["meta"], "2 / 5 · 48% · 2700 K")
        self.assertEqual(wire["ring"], {"style": "clusters", "value": 0, "index": 1, "count": 5})
        self.assertEqual([(b["icon"], b["enabled"]) for b in wire["buttons"]],
                         [("back", True), ("", False), ("", False), ("switch", True)])
        self.assertEqual(self.c.control()["profile"], "MIDI SKIPPER")
        self.assertEqual(self.c.bounds(), (0, 4, 1))

    def test_2_and_3_show_the_reason(self):
        self.press(1)
        self.assertEqual(self.transient(), "Turn to choose · 4 runs it")
        self.assertEqual((self.wire()["meta"], self.wire()["metaTone"]), ("Turn to choose · 4 runs it", "error"))
        self.assertEqual(self.c.feedback["kind"], "err")
        self.press(2)
        self.assertEqual(self.transient(), "Turn to choose · 4 runs it")

    def test_run_goes_back_to_lights_and_signals_the_green_wash(self):
        self.turn_to(2)
        self.press(3)
        self.assertEqual(self.c.screen.mode, "lights")
        self.serve()
        self.assertEqual(self.ha.calls[-1], ("script", "turn_on", {"entity_id": "script.movie"}))
        self.assertEqual(self.c.feedback["kind"], "ok")
        self.assertNotIn("moment", self.c.feedback)
        wire = self.wire()
        self.assertEqual((wire["title"], wire["subtitle"], wire["meta"], wire["metaTone"]),
                         ("Movie", "12% · 2200 K", "Scene running", "success"))
        # Back in the list the scene reads as running now.
        self.press(1)
        self.assertEqual(self.wire()["meta"], "3 / 5 · running now")

    def test_a_manual_change_after_a_scene_titles_it_adjusted(self):
        self.press(3)
        self.serve()
        self.tick(4)
        self.serve()
        self.turn_to(self.c.bounds()[2] + 1)
        self.assertEqual(self.wire()["title"], "Demo", "r3.1 design: an adjustment returns the title to the area")

    def test_scene_types_use_their_service(self):
        for index, expected in ((0, ("scene", "turn_on")), (4, ("automation", "trigger"))):
            with self.subTest(index=index):
                if self.c.screen.mode != "scenes":
                    self.press(1)
                self.turn_to(index)
                self.press(3)
                self.serve()
                self.assertEqual(self.ha.calls[-1][:2], expected)


class FailureTests(R3Fixture):
    def test_offline_copy_and_dimmed_buttons(self):
        self.controls.ha = "offline"
        self.c.lights_state(self.ha.read_state())
        self.lights()
        wire = self.wire()
        # r3.1 design (blockedView `nc`): Not connected / Home Assistant / Open Settings on your PC.
        self.assertEqual((wire["title"], wire["subtitle"], wire["meta"], wire["metaTone"]),
                         ("Not connected", "Home Assistant", "Open Settings on your PC", "error"))
        self.assertEqual([b["enabled"] for b in wire["buttons"]], [True, False, False, False])
        self.press(1)
        self.assertEqual(self.transient(), "Home Assistant not connected")
        self.turn_to(80)
        self.assertEqual(self.c.lights_intent(), {}, "no write while offline")

    def test_auth_copy(self):
        self.controls.ha = "auth"
        self.c.lights_state(self.ha.read_state())
        self.lights()
        wire = self.wire()
        self.assertEqual((wire["title"], wire["subtitle"], wire["activity"]), ("Not connected", "Home Assistant", "error"))
        self.press(3)
        self.assertEqual(self.transient(), "Home Assistant not connected")

    def test_not_set_up_copy(self):
        self.controls.ha = "notset"
        self.c.lights_state(self.ha.read_state())
        self.lights()
        self.assertEqual(self.wire()["title"], "Not connected")   # r3.1 design

    def test_going_offline_during_a_write(self):
        self.lights()
        self.turn_to(80)
        self.tick()
        self.controls.ha = "offline"
        self.serve()
        self.assertEqual(self.c.feedback["kind"], "err")
        self.assertEqual(self.transient(), "Didn’t change · try again")
        self.assertEqual(self.c.lights_intent(), {})
        self.assertFalse(self.c.lights.online)

    def test_an_allowlist_refusal_is_reported(self):
        self.lights()
        effect = self.c.request("scene_run", entity_id="scene.not_configured", label="Other")
        self.c.lights_command = effect
        self.serve()
        self.assertEqual(self.transient(), "Not allowed in Desk Dial")
        self.assertEqual(self.c.feedback["kind"], "err")
        self.assertFalse(any(call[2].get("entity_id") == "scene.not_configured" for call in self.ha.calls))

    def test_the_simulator_refuses_like_the_adapter(self):
        with self.assertRaises(HomeAssistantError) as caught:
            self.ha.run_scene("switch.kettle")
        self.assertEqual(caught.exception.outcome, "not_allowed")


class FirmwareParserTests(R3Fixture):
    """Every r3 frame the controller emits, as the bridge sends it, is accepted by the firmware's
    presentation-6 reading (control_center.lcd_preview.v6_parse, the reference for cc_parse_frame)
    and by the presentation-5 rules it keeps (device.v5_parse, v6 tokens aside)."""

    def check(self, name):
        from control_center.lcd_preview import v6_parse
        wire = self.wire()
        stored, invalid = v6_parse(wire)
        self.assertEqual(invalid, [], name)
        self.assertEqual(stored["layout"], wire.get("layout", "nowPlaying"), name)
        if wire["ring"]["style"] in ("bri", "ctemp"):
            self.assertEqual(stored["ringKelvin"], wire["ring"]["kelvin"], name)
        if wire.get("layout") == "lightsbig":
            self.assertEqual(stored["valueUnit"], wire["valueUnit"], name)
        if wire.get("layout") == "scenes":
            self.assertEqual((stored["prevTitle"], stored["nextTitle"]),
                             (wire.get("prevTitle", ""), wire.get("nextTitle", "")), name)
        return wire

    def test_every_screen(self):
        self.check("launcher")
        self.press(0)
        self.check("music")
        self.press(0)
        self.lights()
        self.check("lights")
        self.turn_to(70)
        self.check("lightsbig bri")
        self.tick(2)
        self.serve()
        self.press(2)
        self.check("lights temperature")
        self.turn_to(self.c.bounds()[2] + 1)
        self.check("lightsbig temperature")
        self.tick(2)
        self.serve()
        self.press(3)
        self.serve()
        self.check("lights off")
        self.press(3)
        self.serve()
        self.press(1)
        for index in range(5):
            if index:
                self.turn_to(index)
            self.check(f"scenes {index}")
        self.press(1)
        self.check("scenes reason")
        self.press(3)
        self.serve()
        wire = self.check("scene ran")
        self.assertEqual((wire["layout"], wire["feedback"]), ("lights", {"kind": "ok", "seq": self.c.feedback_seq}))
        self.tick(4)
        self.serve()
        self.ha.external(kelvin=4000)
        self.c.lights_state(self.ha.read_state())
        self.check("external")
        self.controls.ha = "offline"
        self.c.lights_state(self.ha.read_state())
        self.check("offline")


class SettleTests(R3Fixture):
    """User 2026-09-29: 100 % drifted back to 95 %, then (after a 1 s check) to 97 % (the light's report came
    late). The knob keeps what was set while the lights report something close; from LIGHTS_SETTLE after the
    last write a close-but-different report gets the level once more without a fade; a far report is shown."""

    def setUp(self):
        super().setUp()
        self.lights()

    def sets(self):
        return [e for e in self.c.drain() if e["kind"] == "lights_set"]

    def set_to(self, level):
        self.turn_to(level - 1)                         # DD-DES-003: while on, position = level - 1
        self.tick()
        self.serve()
        self.c.lights_state(self.ha.read_state())

    def report(self, **values):
        self.ha.external(**values)
        self.c.lights_state(self.ha.read_state())

    def test_a_short_report_gets_the_level_once_more_without_a_fade(self):
        from control_center.controller import LIGHTS_SETTLE
        self.set_to(100)
        self.report(bri=95)                             # the light reports 95 after the fade
        self.assertEqual(self.c.lights.bri, 100)
        self.tick(LIGHTS_SETTLE + 0.1)
        effects = self.sets()
        self.assertEqual([e.get("transition") for e in effects], [0])
        self.serve(effects)
        self.assertEqual(self.ha.calls[-1][2].get("brightness_pct"), 100)
        self.report(bri=97)                             # still short: the knob keeps 100, never a second retry
        self.tick(LIGHTS_SETTLE + 0.1)
        self.assertEqual(self.sets(), [])
        self.assertEqual(self.c.lights.bri, 100)

    def test_a_late_short_report_is_corrected_when_it_arrives(self):
        from control_center.controller import LIGHTS_SETTLE
        self.set_to(100)
        self.tick(LIGHTS_SETTLE + 0.5)                  # the report still said 100 at the settle point
        self.assertEqual(self.sets(), [])
        self.tick(1.0)
        self.report(bri=97)                             # then the light's own report lands, short
        self.assertEqual(self.c.lights.bri, 100)
        self.tick()
        effects = self.sets()
        self.assertEqual([e.get("transition") for e in effects], [0])

    def test_a_far_change_is_shown(self):
        self.set_to(100)
        self.report(bri=40)                             # another app / a switch
        self.assertEqual(self.c.lights.bri, 40)
        self.tick(2.0)
        self.assertEqual(self.sets(), [])

    def test_a_temperature_drift_mid_turn_keeps_the_brightness_caption(self):
        """User 2026-09-29: the caption above the % flashed to Temperature while turning brightness (the
        light reported 3200 -> 3300 K after each write)."""
        self.turn_to(70)
        self.tick()
        self.serve()
        self.report(kelvin=3300)                        # the light's own drift, mid-turn
        wire = self.wire()
        self.assertEqual((wire["layout"], wire["volumeCaption"], wire["valueUnit"]), ("lightsbig", "Brightness", "%"))
        self.turn_to(71)
        self.tick(5.0)
        self.serve()
        self.report(kelvin=3400)                        # a small drift at rest: no Temperature reveal either
        self.assertNotEqual(self.wire().get("valueUnit"), "K")

    def test_a_real_temperature_change_is_still_revealed(self):
        self.tick(5.0)
        self.report(kelvin=4500)                        # another app: 3200 -> 4500 K
        wire = self.wire()
        self.assertEqual((wire["layout"], wire["valueUnit"]), ("lightsbig", "K"))

    def test_no_settle_write_when_the_report_matches(self):
        from control_center.controller import LIGHTS_SETTLE
        self.set_to(80)
        self.tick(LIGHTS_SETTLE + 0.1)
        self.assertEqual(self.sets(), [])


if __name__ == "__main__":
    unittest.main()
