"""Desk Dial r3 on hardware (2026-09-29 audit): the regressions the user met on a presentation-6 knob, and the
r3 README items delivered with them (overshoot guard, 1 on release, Seek Set / Cancel, Tracks copy, the arc
breadcrumb token, the warm tone, the unavailable-press flash, the marker ring, the hold-1 ring).

1. The Windows picker never opened: r3 moved Windows to the launcher's button 2 but the knob's F24 stayed on
   button 4 (and off), so the picker opened from a serial press, which Windows refuses the foreground
   (WindowsAdapter.show raises). Now the Win slot's raw sends F24 on the launcher and the hid-tagged kd is
   dropped by the runtime / controller whatever its slot.
2. Lights refused the knob (and killed the session): its brightness control had min 1, which the bridge and
   the firmware reject (min is always 0); the DeviceBridge error marked the knob unsupported, so every later
   screen (Recently Added included) stayed stale / blank and no surface opened.

The full-stack checks drive tests/tools/capture_r3_session.py (real Controller + Runtime + DeviceBridge on an
in-memory presentation-6 knob; the picker under the Windows foreground rule).
"""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
from r3_support import CAPS_V6, R3Fixture  # noqa: E402
from cc5_support import recent_page, windows_snapshot  # noqa: E402
from control_center import alive_lights as al, crumb_arc, device, lcd_preview, presentation  # noqa: E402
from control_center.controller import COPY, HOME_GUARD  # noqa: E402

_CAPTURE = None


def capture():
    """One full-stack r3 session for the whole module (it takes a few seconds)."""
    global _CAPTURE
    if _CAPTURE is None:
        import capture_r3_session
        records, audit, info = capture_r3_session.capture()
        _CAPTURE = (records, audit, info)
    return _CAPTURE


def wire_frames(records):
    out = []
    for record in records:
        if record.get("kind") in ("frame", "control"):
            message = json.loads(record["line"])
            out.append((record, message["frame"] if "frame" in message else message["control"]["frame"]))
    return out


class FullStackTests(unittest.TestCase):
    """The hardware symptoms, end to end at presentation 6."""

    def test_the_session_never_errors_or_is_refused(self):
        _records, audit, info = capture()
        self.assertIsNone(info["error"], info["error"])
        self.assertEqual(info["bridgeErrors"], [], "every control / frame passes the bridge's own validation")
        self.assertEqual(info["refusals"], [], "the knob accepted every line")
        self.assertTrue(audit, "the script ran")

    def test_the_picker_opens_from_home_2_by_f24(self):
        _records, audit, info = capture()
        self.assertGreaterEqual(info["picker"]["opened"], 4, "Home 2 opened the picker every time")
        self.assertEqual(info["picker"]["refused"], 0, "never a serial-only show (Windows refuses the foreground)")
        self.assertGreaterEqual(info["knobInput"].get("hid", 0), 4, "the launcher's Win press sent F24")
        row = next(r for r in audit if r["path"] == "Home · 2")
        self.assertEqual(row["mode"], "windows")

    def test_explorer_and_upnext_open_on_screen(self):
        _records, _audit, info = capture()
        self.assertGreaterEqual(info["stagePosted"].get("explorer_open", 0), 1)
        self.assertGreaterEqual(info["stagePosted"].get("upnext_open", 0), 1)

    def test_recently_added_shows_its_text(self):
        _records, audit, _info = capture()
        row = next(r for r in audit if r["path"] == "Music · 2")
        self.assertEqual((row["mode"], row["layout"]), ("recent", "recent"))
        self.assertTrue(row["title"] and row["subtitle"] and row["meta"], row)

    def test_every_line_parses_as_presentation_6(self):
        records, _audit, _info = capture()
        frames = wire_frames(records)
        self.assertGreater(len(frames), 100)
        for record, frame in frames:
            with self.subTest(n=record["n"], step=record["step"]):
                stored, invalid = lcd_preview.v6_parse(frame)
                self.assertEqual(invalid, [])
                self.assertEqual(stored["crumb"], frame.get("crumb", ""))

    def test_every_screen_is_audited(self):
        _records, audit, _info = capture()
        paths = {row["path"] for row in audit}
        for path in ("Home", "Home · 2", "Windows · 1", "Windows · 4", "Home · 1", "Music · 2", "Recent · 2",
                     "Explorer · 1", "Music · 3", "Tracks · 3", "Tracks · 2", "Up next · 1", "Home · 3",
                     "Lights · turn", "Lights · 3", "Lights · 4", "Lights · 2", "Scenes · 2", "Scenes · 4",
                     "Scenes · hold 1"):
            self.assertIn(path, paths)


class LauncherWindowsTests(R3Fixture):
    def test_the_launcher_win_slot_sends_f24(self):
        control = self.c.control()
        self.assertEqual(control["windowsButton"], self.c.button_order[1])
        self.assertTrue(control["windowsHidEnabled"])
        wire = device._frame({"id": self.c.control_id, **control["frame"]}, CAPS_V6)
        self.assertEqual(wire["buttons"][1]["icon"], "win", "the knob's F24 icon gate")

    def test_f24_is_off_everywhere_else(self):
        self.press(0)
        self.assertFalse(self.c.control()["windowsHidEnabled"], "Music: no F24")
        self.c.button_order = [2, 0, 3, 1]
        self.assertEqual(self.c.control()["windowsButton"], 0, "the raw of slot 1, never a literal")

    def test_a_hid_tagged_press_is_dropped_on_any_slot(self):
        self.press(1, hid=True)
        self.assertEqual(self.c.screen.mode, "launcher", "the hotkey path already acted")
        self.assertFalse([e for e in self.c.drain() if e["kind"] == "windows_open"])


class LightsControlTests(R3Fixture):
    def test_every_lights_control_passes_the_bridge_rules(self):
        self.press(2)
        self.serve()
        for step in ("on", "temp", "off"):
            control = self.c.control()
            with self.subTest(step=step):
                self.assertEqual(control["min"], 0, "the contract's min is always 0")
                self.assertTrue(0 <= control["position"] <= control["max"])
            if step == "on":
                self.press(2)
            elif step == "temp":
                self.press(2)
                self.press(3)
                self.serve()

    def test_position_0_while_on_is_the_one_percent_floor(self):
        self.press(2)
        self.serve()
        self.c.position(0, self.c.control_id)
        self.tick()
        self.serve()
        self.assertEqual(self.ha.bri, 1)
        self.assertTrue(self.ha.on)


class GrammarTests(R3Fixture):
    def test_overshoot_guard(self):
        self.press(0)                                   # Music
        self.clock.advance(1.0)
        self.press(0)                                   # Home
        self.press(0)                                   # mashed: ignored
        self.assertEqual(self.c.screen.mode, "launcher")
        self.assertEqual(self.frame()["status"], COPY["knob.status.home_guard"])
        self.clock.advance(HOME_GUARD + 0.01)
        self.press(0)
        self.assertEqual(self.c.screen.mode, "home")

    def test_tracks_r3_copy_and_play_at_now(self):
        # r3.1: Tracks browses the whole queue from the playing row; 4 there is unavailable.
        self.press(0)
        self.press(2)
        frame = self.frame()
        self.assertEqual((frame["title"], frame["meta"]), (self.c.state["title"], COPY["knob.meta.tracks.browse"]))
        self.assertEqual(frame["crumb"], "tracks")
        self.assertEqual((frame["ring"]["style"], frame["ring"]["now"]), ("queue", self.c._position()[0] - 1))
        self.press(3)                                   # Play at the playing row: unavailable
        frame = self.frame()
        self.assertEqual((frame["meta"], frame["metaTone"]), (COPY["knob.meta.tracks.browse"], "error"))
        self.assertEqual(frame["feedback"]["moment"], "refused")
        P, T = self.c._position()
        self.turn_to(P)                                 # the next row
        frame = self.frame()
        self.assertEqual((frame["title"], frame["meta"], frame["metaTone"]),
                         (f"Track {P + 1}", f"Skip to {P + 1} / {T} · 4 plays", "success"))   # r3.1 design

    def test_seek_set_and_cancel(self):
        self.press(0)
        self.press(2)
        self.press(2)                                   # Seek
        self.assertEqual(self.c.screen.mode, "seek")
        self.assertEqual([b["label"] for b in self.frame()["buttons"]], ["Cancel", "Up next", "Set", "Play"])
        self.assertEqual(self.frame()["metaTone"], "warm")
        self.turn_to(self.c.bounds()[2] + 3)
        self.tick(1.0)
        self.assertFalse([e for e in self.c.drain() if e["kind"] == "seek"], "a scrub is not sent before Set")
        self.press(3)                                   # Skip in Seek: unavailable
        self.assertEqual(self.frame()["meta"], COPY["knob.meta.skip.seeking"])
        self.press(0)                                   # Cancel
        self.assertEqual(self.c.screen.mode, "tracks")
        self.assertEqual(self.frame()["meta"], COPY["knob.meta.seek.cancelled"])
        self.tick(1.0)
        self.assertFalse([e for e in self.c.drain() if e["kind"] == "seek"], "Cancel sends nothing")
        self.press(2)
        self.turn_to(self.c.bounds()[2] + 2)
        self.press(2)                                   # Set
        seeks = [e for e in self.c.drain() if e["kind"] == "seek"]
        self.assertEqual(len(seeks), 1)
        self.assertEqual(self.frame()["meta"], COPY["knob.meta.seek.set"])

    def test_windows_r3_screen(self):
        self.press(1)
        effect = self.one("windows_open")
        self.c.complete(effect["request"], windows_snapshot(4))
        frame = self.frame()
        self.assertEqual(frame["buttons"][0]["icon"], "house")
        self.assertEqual(frame["ring"], {"style": "marker", "value": 0, "index": frame["ring"]["index"], "count": 4})
        self.assertEqual(frame["crumb"], "windows")
        self.assertRegex(frame["meta"], r"^\d+ / 4$")

    def test_crumbs_and_explorer_album_tab(self):
        self.assertNotIn("crumb", self.frame(), "the launcher has none")
        self.press(0)
        self.assertEqual(self.frame()["crumb"], "music")
        self.press(1)
        self.complete("recent", recent_page(0, 30))
        self.assertEqual(self.frame()["crumb"], "recent")
        self.press(1)
        self.assertEqual(self.frame()["crumb"], "onScreenRecent")
        self.assertEqual(self.frame()["buttons"][1]["icon"], "album")

    def test_r2_2_keeps_its_grammar(self):
        self.c.set_spaces(False)
        self.c._reenter("r2.2")
        self.assertNotIn("crumb", self.frame())
        self.assertEqual(self.c.control()["windowsButton"], self.c.button_order[3])


class WireTests(unittest.TestCase):
    def frame(self, **extra):
        base = {"id": 5, "mode": "TRACKS", "target": "Hall", "value": "", "detail": "", "status": "", "layout": "tracks",
                "buttons": [{"label": "Back", "enabled": True, "icon": "back"}] * 4,
                "ring": {"style": "transport", "value": 0, "index": 1, "count": 3}}
        base.update(extra)
        return base

    def test_presentation_6_keeps_the_r3_fields(self):
        wire = device._frame(self.frame(crumb="tracks", metaTone="warm", meta="x",
                                        feedback={"kind": "err", "seq": 3, "moment": "refused"}), CAPS_V6)
        self.assertEqual((wire["crumb"], wire["metaTone"], wire["feedback"]["moment"]), ("tracks", "warm", "refused"))
        marker = device._frame(self.frame(layout="windows", ring={"style": "marker", "value": 0, "index": 2,
                                                                  "count": 5}), CAPS_V6)
        self.assertEqual(marker["ring"]["style"], "marker")

    def test_presentation_5_gets_a_valid_downgrade(self):
        from r3_support import CAPS_V5
        wire = device._frame(self.frame(crumb="tracks", metaTone="warm", meta="x",
                                        feedback={"kind": "err", "seq": 3, "moment": "refused"}), CAPS_V5)
        self.assertNotIn("crumb", wire)
        self.assertEqual(wire.get("metaTone", "meta"), "secondary")
        self.assertNotIn("moment", wire["feedback"])
        self.assertEqual(device.v5_parse(wire)[1], [])
        marker = device._frame(self.frame(layout="windows", ring={"style": "marker", "value": 0, "index": 2,
                                                                  "count": 5}), CAPS_V5)
        self.assertEqual(marker["ring"]["style"], "selection")
        self.assertEqual(device.v5_parse(marker)[1], [])

    def test_crumb_masks(self):
        self.assertEqual(crumb_arc.TOKENS, presentation.CRUMBS)
        for token in crumb_arc.TOKENS:
            ancestors, current = crumb_arc.render(token)
            self.assertIsNotNone(current)
            self.assertEqual(ancestors is None, len(crumb_arc.PATHS[token]) == 1)
            for mask in (ancestors, current):
                if mask is not None:
                    self.assertEqual(len(mask.data), mask.w * mask.h)
                    self.assertTrue(0 <= mask.x and mask.x + mask.w <= 240 and 0 <= mask.y and mask.y + mask.h <= 120)

    def test_the_mirror_draws_the_crumb_instead_of_the_heading(self):
        frame = self.frame(heading="TRACKS", crumb="tracks")
        scene = lcd_preview.compose(frame)
        self.assertEqual(scene.crumb, "tracks")
        self.assertFalse(scene.texts("heading"))
        image = lcd_preview.render_lcd(frame)
        self.assertEqual(image.size, (240, 240))


class AliveTests(unittest.TestCase):
    def music(self, **extra):
        frame = {"id": 1, "mode": "VOLUME", "target": "Hall", "value": "", "detail": "", "status": "",
                 "layout": "nowPlaying", "ledStyle": "color", "crumb": "music",
                 "buttons": [{"label": "Home", "enabled": True, "icon": "house"}] * 4,
                 "ring": {"style": "level", "value": 40, "index": 0, "count": 101}}
        frame.update(extra)
        return frame

    def engine(self, frame):
        lights = al.AliveLights(0)
        lights.claim(0)
        for t in range(0, 1000, 20):
            lights.render(t, frame)
        return lights

    def lit(self, targets):
        return [i for i, cell in enumerate(targets.ring) if cell is not None and cell.alpha > 0]

    def test_hold_ring_fills_then_flashes_home(self):
        lights = self.engine(self.music())
        lights.press(1000, 0)
        lights.render(1040, self.music())
        self.assertTrue(self.lit(lights.targets), "before 12 %: the ring as it was")
        lights.render(1300, self.music())
        filled = self.lit(lights.targets)
        self.assertEqual(len(filled), (300 * 45 + 300) // 600)
        self.assertEqual(filled, sorted(al.ARC_START + k - (60 if al.ARC_START + k >= 60 else 0) for k in range(len(filled))))
        lights.render(1620, self.music())
        self.assertEqual(lights.targets.flash, "home")
        self.assertEqual(len(self.lit(lights.targets)), 60)
        lights.render(2100, self.music())
        self.assertIsNone(lights.targets.flash)

    def test_no_hold_ring_on_the_launcher(self):
        launcher = self.music()
        del launcher["crumb"]
        lights = self.engine(launcher)
        lights.press(1000, 0)
        lights.render(1700, launcher)
        self.assertNotEqual(lights.targets.flash, "home")

    def test_refused_flash_is_the_bottom_segments(self):
        lights = self.engine(self.music())
        lights.render(1000, self.music(feedback={"kind": "err", "seq": 9, "moment": "refused"}))
        self.assertEqual(lights.targets.flash, "refused")
        # r4 3.4 (ALIVE.md 16): the deny glow is 255,60,40 at 0.9 on 26..34 for 480 ms.
        red = [i for i, c in enumerate(lights.targets.ring)
               if c is not None and c.role == al.ROLE_ACCENT and c.rgb == al.REFUSED_RGB and c.alpha == 0.9]
        self.assertEqual(red, list(range(26, 35)))
        self.assertEqual(al.REFUSED_MS, 480)
        self.assertFalse([e for e in lights.animator.effects if e.type == "fail"], "no shake")

    def test_marker_ring(self):
        frame = self.music(layout="windows", crumb="windows",
                           ring={"style": "marker", "value": 0, "index": 3, "count": 7})
        lights = self.engine(frame)
        cells = lights.targets.ring
        pos = (2 * 3 * 44 + 6) // 12
        marker = [al.ARC_START + pos + k for k in (-1, 0, 1)]
        for i in marker:
            self.assertEqual(cells[i % 60].role, al.ROLE_ACCENT)
        self.assertEqual(lights.targets.tint, None, "the white marker never tints")


if __name__ == "__main__":
    unittest.main()


class QueueTitlesTests(R3Fixture):
    def test_tracks_reads_its_queue_page_and_queue_titles_serves_them(self):
        # r3.1 whole queue: the page of the playing row (20 rows, here the whole 12-row queue).
        from cc5_support import window_result
        self.press(0)
        self.press(2)
        read = [e for e in self.c.pending.values() if e["kind"] == "queue_window"
                and e.get("purpose") == "tracks_page"][-1]
        P, T = self.c._position()
        self.assertEqual((read["start"], read["count"]), (0, min(T, 20)))
        self.c.complete(read["request"], window_result(read["start"], read["count"], T,
                                                       revision=self.c.state.get("queue_revision", "rev-1")))
        titles = self.c.queue_titles([P - 2, P - 1, P, P + 1, P + 2])
        self.assertEqual(sorted(titles), [P - 2, P - 1, P, P + 1, P + 2])
        self.assertEqual(titles[P], self.c.state["title"])
        self.assertEqual(self.c.queue_titles([T + 5]), {}, "an unknown row is absent")
