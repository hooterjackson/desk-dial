"""r3 Navigator: content per state, keys, visibility and the Tk-side wiring (README section 5; checklist
NV-1 ... NV-24). Headless: the controller on the cc5 fake clock (R3Fixture), no window, no port."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r3_support import R3Fixture  # noqa: E402
from control_center import navigator_model as NM  # noqa: E402
from control_center.navigator import Navigator  # noqa: E402


def content(fixture, pressed=None):
    return NM.build_content(NM.read_snapshot(fixture.c, fixture.c.frame()), pressed=pressed)


def keys(c):
    return [(k.label, k.enabled) for k in c.keys]


class ContentFromTheController(R3Fixture):
    def test_launcher_is_home_now_playing(self):
        c = content(self)
        # r3.1: the hold line names hold 4 (the knob's domain swap), the launcher has no hold 1.
        self.assertEqual((c.kind, c.path, c.depth, c.sticky, c.hold_hint), ("now", "Home", 0, False, True))
        self.assertEqual(c.hold_text, "4 Knob to lights")   # r3.1 design HOLD chip
        self.assertEqual(c.holds, (("4", "Knob to lights", 0.0),))
        self.assertEqual((c.title, c.artist), ("Pressure Front", "Mira Vale"))
        self.assertEqual(c.status, "Playing · 1:14 of 3:30")
        self.assertEqual(c.volume, 28)
        self.assertFalse(c.volume_active, "the volume row rests at 60 %")
        self.assertEqual(keys(c), [("Music", True), ("Windows", True), ("Lights", True), ("Pause", True)])

    def test_volume_row_is_active_while_turning(self):
        self.turn_to(31)
        c = content(self)
        self.assertTrue(c.volume_active)
        self.assertEqual(c.volume, 31)

    def test_music_space(self):
        self.press(0)
        c = content(self)
        self.assertEqual((c.kind, c.path, c.depth), ("now", "Music", 1))
        self.assertEqual(keys(c), [("Home", True), ("Recent", True), ("Tracks", True), ("Pause", True)])

    def test_paused_status(self):
        self.publish(dict(self.c.state, playback="PAUSED_PLAYBACK"))
        self.assertEqual(content(self).status, "Paused")

    def test_tracks_rows_around_the_playing_song(self):
        self.press(0)
        self.press(2)
        c = content(self)
        self.assertEqual((c.kind, c.path, c.sticky, c.hold_hint, c.plate), ("rows", "Music › Tracks", True, True, 0))
        self.assertEqual(c.hold_text, "1 Home")
        self.assertEqual([(r.offset, r.number, r.tag) for r in c.rows],
                         [(-2, "3", ""), (-1, "4", ""), (0, "♪", "Now"), (1, "6", ""), (2, "7", "")])
        self.assertEqual(c.rows[2].title, "Pressure Front")
        self.assertEqual(c.rows[2].title_rgb, NM.PLAYING_TITLE)
        self.assertEqual(c.status, "Turn to browse the queue")      # r3.1: the whole queue
        self.assertEqual(keys(c), [("Back", True), ("Up next", True), ("Seek", True), ("Play", False)])

    def test_tracks_rows_follow_the_focus_across_the_whole_queue(self):
        # r3.1: the rows stay centred on the focus (the plate), the playing row keeps ♪ / Now.
        self.press(0)
        self.press(2)
        self.turn_to(8)                                  # row 9 of 12
        c = content(self)
        self.assertEqual(c.plate, 0)
        self.assertEqual([(r.offset, r.number) for r in c.rows], [(-2, "7"), (-1, "8"), (0, "9"), (1, "10"),
                                                                   (2, "11")])
        target = [r for r in c.rows if r.offset == 0][0]
        self.assertEqual((target.tag, target.tag_rgb), ("Skip to", NM.GREEN_TAG))
        self.assertEqual(c.status, "9 / 12 · Press 4 to play")
        self.assertEqual(keys(c)[3], ("Play", True))
        self.turn_to(5)                                  # row 6: the playing row (5) is one above
        c = content(self)
        self.assertEqual([(r.offset, r.number, r.tag) for r in c.rows][1], (-1, "♪", "Now"))
        self.turn_to(1)                                  # row 2: before the playing row
        c = content(self)
        self.assertEqual([r for r in c.rows if r.offset == 0][0].tag, "Back to")

    def test_rows_stop_at_the_queue_ends(self):
        # r3.1: the whole queue has ends (no wrap): row 1 is the first.
        self.publish(dict(self.c.state, playlist_position=1, queue_length=12, track_id="track-1"))
        self.press(0)
        self.press(2)
        self.assertEqual([r.number for r in content(self).rows], ["♪", "2", "3"])

    def test_rows_use_the_controllers_queue_titles(self):
        self.press(0)
        self.press(2)
        P = self.c.state["playlist_position"]
        # what the Tracks neighbour read leaves behind (test setup): the accessor reports it
        self.c._neighbours[(self.c.state.get("queue_revision"), P)] = {P - 1: "Prev song", P + 1: "Next song"}
        self.assertEqual(self.c.queue_titles([P - 1, P + 1]), {P - 1: "Prev song", P + 1: "Next song"})
        titles = [r.title for r in content(self).rows]
        self.assertEqual(titles, ["—", "Prev song", "Pressure Front", "Next song", "—"])

    def test_queue_titles_accessor_is_used_when_present(self):
        self.press(0)
        self.press(2)
        self.c.queue_titles = lambda rows: {r: f"Song {r}" for r in rows}
        titles = [r.title for r in content(self).rows]
        self.assertEqual(titles, ["Song 3", "Song 4", "Pressure Front", "Song 6", "Song 7"])
        self.c.queue_titles = lambda rows: 1 / 0          # a failing accessor: dashes, never a crash
        self.assertEqual([r.title for r in content(self).rows][0], "—")

    def test_lights_brightness(self):
        self.lights()
        c = content(self)
        self.assertEqual((c.kind, c.path, c.caption, c.big, c.unit), ("lights", "Lights › Demo", "Brightness", "62", "%"))
        self.assertEqual((c.bri, c.kelvin, c.bri_a, c.temp_a, c.sticky), (62, 3200, 1.0, 0.5, False))
        self.assertAlmostEqual(c.bri_frac, 0.62)
        self.assertAlmostEqual(c.temp_frac, (3200 - 2200) / 4300)
        self.assertEqual(c.kelvin_rgb, NM.kelvin_rgb(3200))
        self.assertEqual(keys(c), [("Home", True), ("Scenes", True), ("Temperature", True), ("All off", True)])
        self.assertEqual(c.status, "", "the Lights card has no status line (B14)")

    def test_lights_temperature_mode_auto_hides(self):
        self.lights()
        self.press(2)
        self.serve()
        c = content(self)
        self.assertEqual((c.caption, c.big, c.unit, c.bri_a, c.temp_a), ("Colour temperature", "3200", "K", 0.5, 1.0))
        self.assertFalse(c.sticky, "user 2026-09-29: the Lights card hides after the last touch")
        self.assertEqual(keys(c)[2], ("Brightness", True))

    def test_lights_off(self):
        self.lights()
        self.press(3)
        self.serve()
        c = content(self)
        self.assertEqual((c.caption, c.big, c.unit, c.bri_frac), ("Lights", "Off", "", 0.0))
        self.assertEqual(keys(c)[3], ("Turn on", True))

    def test_scenes_list(self):
        self.lights()
        self.press(1)
        self.serve()
        c = content(self)
        self.assertEqual((c.kind, c.path, c.plate, c.sticky, c.hold_hint),
                         ("scenes", "Lights › Demo › Scenes", 0, True, True))
        self.assertEqual([(r.offset, r.number, r.title) for r in c.rows][:3], [(0, "1", "Focus"), (1, "2", "Evening"),
                                                                              (2, "3", "Movie")])
        self.assertEqual(c.status, "Press 4 to run · 62% · 3200 K")   # r3.1 design
        self.assertEqual(keys(c), [("Back", True), ("—", False), ("—", False), ("Run", True)])
        self.turn_to(2)
        c = content(self)
        self.assertEqual([r.offset for r in c.rows], [-2, -1, 0, 1, 2])

    def test_windows_and_overlays_have_no_navigator(self):
        from cc5_support import windows_snapshot
        self.press(1)                       # r3 Home 2 = Windows (the picker opens at once)
        for effect in [e for e in self.c.pending.values() if e["kind"] == "windows_open"]:
            self.c.complete(effect["request"], windows_snapshot(4))
        self.assertEqual(self.c.screen.mode, "windows")
        self.assertIsNone(content(self))

    def test_pressed_key_fills(self):
        c = content(self, pressed=1)
        self.assertEqual([k.pressed for k in c.keys], [False, True, False, False])
        c = content(self, pressed=3)
        self.assertEqual([k.pressed for k in c.keys], [False] * 4, "r3.1 design: key 4 shows its hold chip instead")


class ContentFromSnapshots(unittest.TestCase):
    """Modes the fixture reaches only through the r2.2 lists (the words are the prototype's, B12/B13)."""

    def buttons(self, labels, disabled=()):
        return [{"label": l, "enabled": i not in disabled} for i, l in enumerate(labels)]

    def test_recently_added_keys_and_covers(self):
        items = [{"id": f"a{i}", "title": f"Album {i}", "artist": "X", "accent": 0x112233, "year": 1990 + i}
                 for i in range(9)]
        snap = {"mode": "recent", "index": 3, "recent": items, "frame": {"title": "Album 3", "subtitle": "X",
                                                                          "meta": "4 / 9", "artKey": "k3"},
                "buttons": self.buttons(["Back", "Open", "Play next", "Play"])}
        c = NM.build_content(snap)
        self.assertEqual((c.kind, c.path, c.sticky, c.hold_hint), ("covers", "Music › Recently Added", True, True))
        self.assertEqual([k.label for k in c.keys], ["Back", "Full screen", "Play next", "Play"])
        self.assertEqual([cv.offset for cv in c.covers], [-2, -1, 0, 1, 2])
        self.assertEqual(c.covers[2].art_key, "k3")
        self.assertEqual(c.status, "4 / 9 · 1993")

    def test_seek_keys_and_value(self):
        snap = {"mode": "seek", "frame": {"title": "Song"}, "state": {"title": "Song"},
                "seek": {"target": 131, "D": 252}, "buttons": self.buttons(["Back", "Up next", "Seek", "Skip"])}
        c = NM.build_content(snap)
        self.assertEqual((c.kind, c.path, c.big, c.unit), ("seek", "Music › Tracks › Seek", "2:11", "of 4:12"))
        self.assertAlmostEqual(c.seek_frac, 131 / 252)
        self.assertEqual([(k.label, k.enabled) for k in c.keys],
                         [("Cancel", True), ("Up next", True), ("Set", True), ("Play", False)])   # r3.1 design

    def test_message_replaces_the_status_in_its_colour(self):
        snap = {"mode": "recent", "index": 0, "recent": [{"id": "a", "title": "A"}],
                "frame": {"meta": "Shuffle on · turn it off", "metaTone": "error"}, "buttons": []}
        c = NM.build_content(snap)
        self.assertEqual((c.status, c.status_rgb, c.status_a), ("Shuffle on · turn it off", NM.ERROR, 1.0))

    def test_snapshot_never_raises(self):
        self.assertEqual(NM.read_snapshot(object(), None)["mode"], "")
        self.assertIsNone(NM.build_content(NM.read_snapshot(None, None)))

    def test_kelvin_colours(self):
        self.assertEqual(NM.kelvin_rgb(2200), (255, 146, 39))     # README section 3
        self.assertEqual(NM.kelvin_rgb(6500)[0], 255)
        self.assertGreater(NM.kelvin_rgb(6500)[2], 240)


class VisibilityRules(unittest.TestCase):
    def c(self, mode="launcher", sticky=False):
        return NM.NavContent(kind="now", mode=mode, path="", depth=0, sticky=sticky)

    def test_auto_hides_four_seconds_after_the_last_input(self):
        v = NM.Visibility()
        self.assertFalse(v.visible(0.0, self.c()), "nothing shows before an input")
        v.note_input(10.0)
        self.assertTrue(v.visible(13.9, self.c()))
        self.assertAlmostEqual(v.next_change(12.0, self.c()), 2.0)
        self.assertFalse(v.visible(14.0, self.c()))

    def test_sticky_modes_stay_longer_but_not_forever(self):
        v = NM.Visibility()
        v.note_input(0.0)
        sticky = self.c("tracks", sticky=True)
        self.assertTrue(v.visible(NM.STICKY_HIDE_S - 0.1, sticky))
        self.assertAlmostEqual(v.next_change(5.0, sticky), NM.STICKY_HIDE_S - 5.0)
        self.assertFalse(v.visible(NM.STICKY_HIDE_S + 0.1, sticky), "user 2026-09-29: never on screen forever")
        self.assertFalse(v.visible(NM.AUTO_HIDE_S + 0.1, self.c()))

    def test_pinned_and_off(self):
        v = NM.Visibility(mode="pinned")
        self.assertTrue(v.visible(99.0, self.c()))
        v.set_mode("off")
        v.note_input(99.0)
        self.assertFalse(v.visible(99.0, self.c("tracks", sticky=True)))
        v.set_mode("bogus")
        self.assertEqual(v.mode, "auto")

    def test_hidden_under_an_overlay_or_without_the_knob(self):
        v = NM.Visibility(mode="pinned")
        self.assertFalse(v.visible(0.0, self.c(), overlay_open=True))
        self.assertFalse(v.visible(0.0, self.c(), connected=False))
        self.assertFalse(v.visible(0.0, None))


class Runtime:
    """A runtime stand-in over a real controller (what ui.ControlCenterApp hands the Navigator)."""

    def __init__(self, controller, level=6):
        self.controller = controller
        self.presentation_level = level
        self.touch_seq = 0
        self.device_connected = True
        self.reduced_motion = False
        self.open_surfaces = set()

    def lcd_media(self, frame, item=None, *, hires=False):
        return None, None, False, ("",), None, None


class Backend:
    def __init__(self):
        self.posts, self.touches, self.disabled, self.hwnd = [], 0, None, 0x1234

    def post(self, state):
        self.posts.append(state)

    def post_touch(self):
        self.touches += 1

    def metrics(self):
        return {}

    def close(self, timeout=2.0):
        return True


class FacadeTests(R3Fixture):
    def setUp(self):
        super().setUp()
        self.t = [100.0]
        self.backend = Backend()
        self.nav = Navigator(self.backend, clock=lambda: self.t[0])
        self.rt = Runtime(self.c)

    def tick(self, dt=0.0):
        self.t[0] += dt
        return self.nav.update(self.rt, self.c.frame())

    def test_replaces_the_floating_knob_only_for_presentation_6(self):
        self.rt.presentation_level = 5
        self.assertFalse(self.tick())
        self.assertEqual(self.backend.posts, [])
        self.rt.presentation_level = 6
        self.assertTrue(self.tick())
        self.assertTrue(NM.applies(self.rt))

    def test_touch_shows_then_auto_hides(self):
        self.tick()
        self.assertFalse(self.backend.posts[-1]["visible"])
        self.rt.touch_seq += 1
        self.tick(0.025)
        self.assertTrue(self.backend.posts[-1]["visible"])
        n = len(self.backend.posts)
        self.tick(1.0)
        self.assertEqual(len(self.backend.posts), n, "nothing changed: nothing posted")
        self.tick(3.1)
        self.assertFalse(self.backend.posts[-1]["visible"])

    def test_fast_path_turn_shows_an_eligible_navigator_at_once(self):
        self.tick()
        self.nav.note_turn()
        self.assertEqual(self.backend.touches, 1)
        self.tick()
        self.assertTrue(self.backend.posts[-1]["visible"], "the Tk tick confirms the turn")

    def test_press_fills_the_key_briefly(self):
        self.tick()
        self.nav.note_press(1)
        self.tick(0.01)
        self.assertTrue(self.backend.posts[-1]["content"].keys[1].pressed)
        self.tick(0.3)
        self.assertFalse(self.backend.posts[-1]["content"].keys[1].pressed)

    def test_off_setting_never_shows(self):
        self.nav.set_mode("off")
        self.rt.touch_seq += 1
        self.tick()
        self.assertFalse(self.backend.posts[-1]["visible"])
        self.assertFalse(self.backend.posts[-1]["eligible"])

    def test_overlay_open_hides(self):
        self.nav.set_mode("pinned")
        self.tick()
        self.assertTrue(self.backend.posts[-1]["visible"])
        self.rt.open_surfaces = {"explorer"}
        self.tick()
        self.assertFalse(self.backend.posts[-1]["visible"])

    def test_a_disabled_backend_keeps_the_floating_knob(self):
        self.backend.disabled = "no device"
        self.assertFalse(self.tick())


class FastPathHook(unittest.TestCase):
    def test_turns_and_presses_reach_the_navigator(self):
        from control_center.ui import FastPath
        calls = []

        class Nav:
            def note_turn(self):
                calls.append("turn")

            def note_press(self, slot):
                calls.append(("press", slot))
        fast = FastPath(navigator=Nav())
        fast.button_order = [0, 1, 2, 3]
        fast.handle("position", {"id": 1, "position": 5}, 1.0)
        fast.handle("limit", {"id": 1, "dir": 1}, 1.0)
        fast.handle("button", {"id": 1, "button": 2}, 1.0)
        self.assertEqual(calls, ["turn", "turn", ("press", 2)])


class SettingsTests(unittest.TestCase):
    def test_setting_values(self):
        from control_center import ui
        self.assertEqual(ui.NAVIGATOR_CHOICES, (("Auto-hide", "auto"), ("Pinned", "pinned"), ("Off", "off")))
        self.assertEqual(ui.DEFAULT_NAVIGATOR, "auto")

    def test_apply_presentation_sets_the_mode(self):
        from control_center import ui
        app = ui.ControlCenterApp.__new__(ui.ControlCenterApp)
        app.config = {"navigator": "pinned"}
        app.navigator = Navigator(None)

        class RT:
            pass
        app._apply_presentation(RT())
        self.assertEqual(app.navigator.mode, "pinned")
        app.config = {"navigator": "nonsense"}
        app._apply_presentation(RT())
        self.assertEqual(app.navigator.mode, "auto")


class SuppressionWiring(R3Fixture):
    """ui.ControlCenterApp._render_overlay holds the floating knob with 'navigator' for an r3 knob."""

    def make_app(self, level):
        from control_center import ui

        class Overlay:
            state, hwnd, wants_frames = "hidden", 0, False

            def __init__(self):
                self.reasons = {}

            def set_suppressed(self, reason, on):
                self.reasons[reason] = on

            def touch(self):
                pass
        app = ui.ControlCenterApp.__new__(ui.ControlCenterApp)
        app.chrome = False
        app.overlay = Overlay()
        app.runtime = Runtime(self.c, level)
        app.runtime.windows = None
        app.runtime.alive = False
        app.navigator = Navigator(Backend(), clock=lambda: 5.0)
        app._reset_mirror_state()
        app._overlay_blank = False
        return app

    def test_r3_knob_suppresses_the_floating_knob(self):
        app = self.make_app(6)
        app._render_overlay(self.c.frame())
        self.assertTrue(app.overlay.reasons.get("navigator"))

    def test_r22_knob_keeps_the_floating_knob(self):
        app = self.make_app(5)
        try:
            app._render_overlay(self.c.frame())
        except Exception:
            pass                        # the v5 scene path needs the full app; the reason is what counts
        self.assertNotIn("navigator", app.overlay.reasons)


if __name__ == "__main__":
    unittest.main()
