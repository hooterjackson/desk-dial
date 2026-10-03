"""Per-mode knob copy on the desktop v7 grammar (CONTROL_CENTER_V5.md sections 2.4, 5 and 15):
Home layouts, status precedence and tones, captions, notices, the retired v6 strings, and the
frames every mode sends through the host validator (presentation 4 and 5).

Pure controller tests: no device, network, Win32 or LED renderer is involved.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from control_center.controller import COPY, Controller, Screen
from control_center.device import _frame, v5_parse
from control_center.presentation import button_tone_v5
from cc5_support import Clock, Fixture as V7Fixture, queue_state, recent_page, state

P4 = {"controlCenter": 1, "presentation": 4, "glyphs": "latin-ext-a"}
P5 = {"controlCenter": 1, "presentation": 5, "glyphs": "latin-ext-a"}
PLAYING = dict(playback="PLAYING", can_pause=True, can_play=False, title="Pressure Front",
               artist="Mira Vale", queue_length=4)
PAUSED = dict(PLAYING, playback="PAUSED_PLAYBACK", can_pause=False, can_play=True)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.c = Controller(clock=self.clock)
        self.publish(state(**PLAYING))
        self.c.last_poll = self.clock()
        self.c.drain()

    def publish(self, value):
        self.c.complete(self.c.request("state"), value)

    def effects(self, kind=None):
        return [e for e in self.c.drain() if kind is None or e["kind"] == kind]

    def one(self, kind):
        effects = self.effects(kind)
        self.assertEqual(len(effects), 1, effects)
        return effects[0]

    def f(self, *names):
        frame = self.c.frame()
        return frame if not names else tuple(frame.get(name) for name in names)

    def tones(self):
        frame = self.c.frame()
        return [button_tone_v5(i, b["icon"], b["enabled"], b.get("lit"), frame["layout"])
                for i, b in enumerate(frame["buttons"])]

    def confirm_volume(self, value, **extra):
        self.c.tick()
        effect = self.one("volume")
        self.c.complete(effect["request"], state(value, **{**PLAYING, **extra}))

    def slot0(self):
        button = self.c.frame()["buttons"][0]
        return button["label"], button["icon"], button["enabled"]


class HomeCopyTests(Fixture):
    def test_playing_rest(self):
        frame = self.c.frame()
        self.assertEqual((frame["layout"], frame["restLayout"], frame["heading"]), ("nowPlaying", "nowPlaying", ""))
        self.assertEqual((frame["title"], frame["subtitle"], frame["status"], frame["value"]),
                         ("Pressure Front", "Mira Vale", "", "28%"))
        self.assertEqual(self.tones(), ["nav", "nav", "nav", "nav"])

    def test_setting_is_meta_until_confirmed_then_blank(self):
        self.c.turn(1)
        self.assertEqual(self.f("layout", "status", "statusTone", "activity", "value"),
                         ("volume", "Setting…", "meta", "pending", "29%"))
        self.confirm_volume(29)
        self.assertEqual(self.f("layout", "status", "activity"), ("volume", "", "idle"))
        self.clock.advance(1.41)
        self.assertEqual(self.f("layout"), ("nowPlaying",))

    def test_minimum_and_maximum(self):
        for value, text in ((0, "Minimum"), (100, "Maximum")):
            with self.subTest(value=value):
                self.c.position(value)
                self.confirm_volume(value)
                self.assertEqual(self.f("layout", "status", "statusTone", "value"),
                                 ("volume", text, "meta", f"{value}%"))
                self.clock.advance(0.2)

    def test_minimum_while_paused_uses_the_secondary_tone(self):
        self.publish(state(**PAUSED))
        self.c.position(0)
        self.confirm_volume(0, **PAUSED)
        self.assertEqual(self.f("status", "statusTone"), ("Minimum", "secondary"))

    def test_changed_on_sonos_is_secondary(self):
        self.publish(state(61, **PLAYING))
        frame = self.c.frame()
        self.assertEqual((frame["layout"], frame["status"], frame["statusTone"], frame["value"]),
                         ("volume", "Changed on Sonos", "secondary", "61%"))
        self.assertTrue(frame["ring"]["external"])
        self.clock.advance(2.7)
        self.assertEqual(self.f("layout"), ("nowPlaying",))

    def test_starting_and_pausing_are_meta_and_paused_is_secondary(self):
        self.c.button(0)
        pause = self.one("transport")
        self.assertEqual(self.f("status", "statusTone", "activity", "layout"), ("Pausing…", "meta", "pending", "nowPlaying"))
        self.c.complete(pause["request"], state(**PAUSED))
        self.assertEqual(self.f("status", "statusTone", "activity", "layout"), ("Paused", "secondary", "idle", "nowPlaying"))
        self.assertEqual(self.c.frame()["volumeCaption"], "Paused · Pressure Front")
        self.c.button(0)
        self.one("transport")
        self.assertEqual(self.f("status", "statusTone", "activity"), ("Starting…", "meta", "pending"))

    def test_paused_keeps_now_playing_and_rest_under_a_reveal(self):
        # r3.1 (2026-09-29): paused keeps the Now Playing layout (art + buttons); no paused idle.
        self.publish(state(**PAUSED))
        self.clock.advance(4.01)
        self.assertEqual(self.f("layout", "restLayout", "status"), ("nowPlaying", "nowPlaying", "Paused"))
        self.assertEqual(self.slot0(), ("Play", "play", True))
        self.assertEqual(self.tones()[0], "go", "the paused Home Play is green")
        self.c.turn(1)
        self.assertEqual(self.f("layout", "restLayout", "status"), ("volume", "nowPlaying", "Setting…"))
        self.confirm_volume(29, **PAUSED)
        self.clock.advance(1.41)
        self.assertEqual(self.f("layout", "restLayout"), ("nowPlaying", "nowPlaying"))

    def test_a_home_play_press_cancels_the_paused_idle(self):
        self.publish(state(**PAUSED))
        self.clock.advance(2.0)
        self.c.button(0)
        play = self.one("transport")
        self.c.complete(play["request"], error="Sonos did not confirm playback")
        self.clock.advance(5.0)
        self.assertEqual(self.f("layout"), ("nowPlaying",))

    def test_nothing_playing_idle_rest_layout(self):
        self.publish(state(playback="STOPPED", title="", artist="", queue_length=0, can_play=False,
                           can_pause=False, can_next=False, can_previous=False))
        self.assertEqual(self.f("layout", "restLayout", "title"), ("idle", "idle", "Nothing playing"))
        self.assertEqual(self.tones(), ["dim", "nav", "dim", "nav"])
        self.c.turn(1)
        self.assertEqual(self.f("layout", "restLayout"), ("volume", "idle"))

    def test_sonos_offline_is_the_notice(self):
        self.publish(state(31, online=False))
        frame = self.c.frame()
        self.assertEqual((frame["layout"], frame["activity"], frame["heading"]), ("notice", "offline", ""))
        self.assertEqual((frame["title"], frame["subtitle"], frame["meta"]),
                         ("Sonos unavailable", "Looking for Sonos…", "Windows still works"))
        self.assertEqual((frame["ring"]["style"], frame["ring"]["value"], frame["confirmedVolume"]), ("level", 31, 31))
        self.assertNotIn("external", frame["ring"])
        self.assertEqual([(b["label"], b["icon"], b["enabled"]) for b in frame["buttons"]],
                         [("Play", "play", False), ("Browse", "list", True), ("Tracks", "tracks", False),
                          ("Win", "win", True)])

    def test_looking_for_sonos_before_the_first_read(self):
        c = Controller(clock=self.clock)
        frame = c.frame()
        self.assertEqual((frame["layout"], frame["activity"], frame["title"], frame["subtitle"], frame["meta"]),
                         ("notice", "idle", "Looking for Sonos…", "", ""))
        self.assertEqual(frame["ring"]["style"], "off")
        self.assertEqual(c.control()["frame"]["title"], "Looking for Sonos…", "the entry frame too")
        c.complete(c.request("state"), error="Speaker offline")
        self.assertEqual((c.frame()["title"], c.frame()["activity"]), ("Sonos unavailable", "offline"))

    def test_pending_pause_and_play_show_the_requested_control_dim(self):
        self.assertEqual(self.slot0(), ("Pause", "pause", True))
        self.c.button(0)
        pause = self.one("transport")
        self.assertEqual(self.slot0(), ("Play", "play", False))
        self.assertEqual(self.f("status", "volumeCaption"), ("Pausing…", "Pressure Front"))
        self.c.complete(pause["request"], state(**PAUSED))
        self.assertEqual(self.slot0(), ("Play", "play", True))
        self.assertEqual(self.c.frame()["volumeCaption"], "Paused · Pressure Front")
        self.c.button(0)
        play = self.one("transport")
        self.assertEqual(self.slot0(), ("Pause", "pause", False))
        self.assertEqual(self.f("status", "volumeCaption"), ("Starting…", "Pressure Front"),
                         "no 'Paused · ' while a play request is out")
        self.c.complete(play["request"], error="Sonos did not confirm playback")
        self.assertEqual(self.slot0(), ("Play", "play", True), "a failed request shows the confirmed state again")
        self.assertEqual(self.c.frame()["feedback"]["kind"], "err")

    def test_pending_request_survives_browse_then_home(self):
        self.c.button(0)
        command = self.one("transport")
        view = self.c.screen.view_id
        self.c.button(1)
        self.c.button(0)
        self.c.drain()
        self.assertNotEqual(self.c.screen.view_id, view)
        self.assertEqual(self.slot0(), ("Play", "play", False))
        self.assertEqual(self.f("status", "activity"), ("Pausing…", "pending"))
        self.c.complete(command["request"], state(**PAUSED))
        self.assertEqual(self.f("status", "activity"), ("Paused", "idle"))

    def test_a_pending_home_request_is_shown_elsewhere_only_as_a_dim_reason(self):
        self.c.button(0)
        self.one("transport")
        self.c.button(2)                    # Tracks
        self.c.position(2)
        frame = self.c.frame()
        self.assertEqual((frame["meta"], frame["activity"]), ("Press 4 to skip", "idle"))
        self.assertFalse(frame["buttons"][3]["enabled"])
        self.c.button(3)
        self.assertEqual(self.c.frame()["meta"], "Pausing…")

    def test_the_contract_accepts_every_home_projection(self):
        for setup in (lambda: None, lambda: self.c.turn(1), lambda: self.publish(state(**PAUSED)),
                      lambda: self.publish(state(online=False))):
            setup()
            for caps in (P4, P5):
                sent = _frame({"id": 1, **self.c.frame()}, caps)
                self.assertIn(sent.get("layout"), ("nowPlaying", "volume", "idle", "notice"))


class RetiredCopyTests(Fixture):
    """Section 15.2: v6 statuses never reach the knob; retired strings are never built."""
    RETIRED = ("Music login needed", "Playback incomplete", "Action failed: see app", "Last action failed",
               "Preparing playback", "Stopped", "One press, one skip", "Skipped · back at neutral",
               "Turn to choose · Green to skip", "Next unavailable for this source", "· Replaces queue",
               "Loads, doesn’t play", "Cancel to return", "Turn to preview · Green to switch", "More",
               "Next 10 items", "Queueing… 0 of")

    def assertNoRetired(self, frame):
        for text in (frame.get(name, "") for name in ("title", "subtitle", "meta", "status", "heading")):
            for retired in self.RETIRED:
                self.assertNotIn(retired, text)

    def test_desktop_statuses_never_reach_the_knob(self):
        self.c.screen.status = "Playback partially failed after an external queue change"
        frame = self.c.frame()
        self.assertEqual((frame["status"], frame["activity"]), ("", "idle"))

    def test_no_mode_builds_a_retired_string(self):
        v7 = V7Fixture("run")
        v7.setUp()
        frames = [v7.frame()]
        v7.browse()
        frames.append(v7.frame())
        v7.press(0)
        v7.tracks(1)
        frames.append(v7.frame())
        v7.turn_to(2)
        frames.append(v7.frame())
        v7.press(0)
        v7.open_windows()
        frames.append(v7.frame())
        for frame in frames:
            self.assertNoRetired(frame)

    def test_retained_and_added_copy(self):
        self.assertEqual(COPY["knob.sub.library_error"], "Home, then Browse")
        self.assertEqual(COPY["knob.meta.shuffle.queue_changed"], "Queue changed")
        self.assertEqual(COPY["knob.status.group_changed"], "Speaker group changed")
        self.assertEqual(COPY["knob.meta.stage_unavailable"], "Couldn’t open on screen")
        self.assertEqual(COPY["knob.meta.like.unlike_in_music"], "Unfavourite in Music app")
        self.assertEqual(COPY["knob.meta.playnext.resolving"], "Finding songs…")
        self.assertNotIn("knob.meta.like.off", COPY)
        for key, text in COPY.items():
            with self.subTest(key=key):
                self.assertNotIn("'", text, "typography: U+2019, never an ASCII apostrophe")
                self.assertNotIn("...", text)


class AllModesContractTests(V7Fixture):
    """Every mode's frame passes the host validator and the cc5.4 parser (presentation 5) and the
    presentation-4 downgrade."""

    def check(self):
        frame = {"id": 7, **self.frame()}
        for caps in (P4, P5):
            with self.subTest(layout=frame["layout"], presentation=caps["presentation"]):
                sent = _frame(dict(frame), caps)
                if caps is P5:
                    stored, invalid = v5_parse(dict(sent))
                    self.assertEqual(invalid, [])

    def test_every_mode(self):
        self.check()
        self.browse()
        self.check()
        self.press(1)
        self.check()
        self.press(2)
        self.tick(0.2)
        self.check()
        self.hold()
        self.tracks(2)
        self.check()
        self.press(2)
        self.check()
        self.press(0)
        self.press(1)
        self.check()
        self.ratings(liked={"1005"})
        self.check()
        self.hold()
        self.open_windows()
        self.check()
        self.press(1)
        self.c.snap_result("left", "accepted")
        self.check()


if __name__ == "__main__":
    unittest.main()
