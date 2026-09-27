"""K3 section 3: the per-mode button map, dim reasons, the Head-shake-with-reason rule and the silent
busy guards (CONTROL_CENTER_V5.md sections 3.1-3.4; VOC section 2; C5-4, C5-59, C5-67, C5-72)."""
import unittest

from cc5_support import COPY, Fixture, fail, queue_state, recent_page, window_result
from control_center import controller as controller_module
from control_center.controller import measure


def tokens(frame):
    return [b["icon"] for b in frame["buttons"]]


class HomeMapTests(Fixture):
    def test_playing_home(self):
        frame = self.frame()
        self.assertEqual(tokens(frame), ["pause", "list", "tracks", "win"])
        self.assertEqual([b["label"] for b in frame["buttons"]], ["Pause", "Browse", "Tracks", "Win"])
        self.assertTrue(all(b["enabled"] for b in frame["buttons"]))

    def test_paused_home_label_follows_the_icon(self):
        self.publish(queue_state(playback="PAUSED_PLAYBACK", can_play=True, can_pause=False))
        frame = self.frame()
        self.assertEqual((frame["buttons"][0]["icon"], frame["buttons"][0]["label"]), ("play", "Play"))

    def test_every_home_label_fits_the_idle_row(self):
        for label in controller_module.HOME_LABELS:
            with self.subTest(label=label):
                self.assertLessEqual(measure(label, 12), 46)

    def test_no_desktop_legend_strings_exist(self):
        """VOC-R24: the floating knob has no tooltip; no `legend.*` copy is built."""
        self.assertFalse([key for key in COPY if key.startswith("legend.")])
        self.assertNotIn("legend", self.frame())

    def test_sonos_unavailable_dims_play_and_tracks(self):
        self.publish(queue_state(online=False))
        frame = self.frame()
        self.assertEqual([b["enabled"] for b in frame["buttons"]], [False, True, False, True])
        self.press(0)
        self.assertEqual(self.transient(), "Sonos unavailable")
        self.assertEqual(self.c.transient.copy_id, "knob.status.sonos_unavailable")  # the Home status twin
        self.assertEqual(self.c.feedback["kind"], "err")

    def test_nothing_playing(self):
        self.publish(queue_state(playback="STOPPED", can_play=False, can_pause=False, can_next=False,
                                 can_previous=False, queue_length=0, playlist_position=0, source="none"))
        frame = self.frame()
        self.assertFalse(frame["buttons"][0]["enabled"])
        self.assertFalse(frame["buttons"][2]["enabled"])
        self.press(2)
        self.assertEqual(self.transient(), "Nothing playing")
        self.assertEqual(self.c.screen.mode, "home")

    def test_starting_is_ignored_on_home_1(self):
        self.browse()
        self.press(3)                     # a Recent start: Home at once
        self.c.drain()
        self.assertFalse(self.frame()["buttons"][0]["enabled"])
        seq = self.c.feedback_seq
        self.press(0)
        self.assertEqual(self.c.feedback_seq, seq, "ignored: only the knob's Press moment")
        self.assertIsNone(self.c._transient())

    def test_transport_pending_shows_the_requested_state_dimmed(self):
        self.press(0)                     # Pause out
        frame = self.frame()
        self.assertEqual((frame["buttons"][0]["icon"], frame["buttons"][0]["enabled"]), ("play", False))
        self.assertEqual(frame["status"], "Pausing…")
        seq = self.c.feedback_seq
        self.press(0)
        self.assertEqual(self.c.feedback_seq, seq)
        self.assertEqual(len([e for e in self.c.pending.values() if e["kind"] == "transport"]), 1)


class RecentMapTests(Fixture):
    def test_loaded_item(self):
        self.browse()
        self.assertEqual(self.labels(), [("back", "Back", True), ("expand", "Open", True),
                                         ("playnext", "Play next", True), ("play", "Play", True)])

    def test_first_page_loading_dims_are_ignored(self):
        self.press(1)
        self.c.drain()
        self.assertEqual([b["enabled"] for b in self.frame()["buttons"]], [True, True, False, False])
        seq = self.c.feedback_seq
        self.press(3)
        self.press(2)
        self.assertEqual(self.c.feedback_seq, seq)

    def test_signin_and_error_dim_open_play_next_and_play(self):
        for outcome, copy_id, tone in (("signin_expired", "knob.meta.signin_expired", "error"),
                                       (None, "knob.meta.library_error", "meta")):
            with self.subTest(outcome=outcome):
                self.c.screen.mode = "home"
                self.press(1)
                self.complete("recent", error=fail("nope", outcome=outcome, status=401 if outcome else 500))
                self.assertEqual([b["enabled"] for b in self.frame()["buttons"]], [True, False, False, False])
                self.press(1)
                self.assertEqual(self.c.transient.copy_id, copy_id)
                self.assertEqual(self.c.transient.tone, tone)
                self.assertEqual(self.c.feedback["kind"], "err")

    def test_unavailable_item(self):
        self.browse(overrides={3: {"available": False}})
        self.turn_to(3)
        frame = self.frame()
        self.assertEqual([b["enabled"] for b in frame["buttons"]], [True, True, False, False])
        self.press(3)
        self.assertEqual(self.transient(), "Not available")

    def test_source_dims_for_play_next_with_toast(self):
        for source, meta, toast in (("airplay", "AirPlay · use Play", "Not playing from the queue · use Play"),
                                    ("radio", "Radio · use Play", "Not playing from the queue · use Play"),
                                    ("linein", "Line-in · use Play", "Not playing from the queue · use Play"),
                                    ("none", "Nothing playing · Play", "Nothing playing · use Play")):
            with self.subTest(source=source):
                self.publish(queue_state(source=source))
                self.browse()
                frame = self.frame()
                self.assertEqual((frame["buttons"][2]["enabled"], frame["buttons"][3]["enabled"]), (False, True))
                self.press(2)
                self.assertEqual(self.transient(), meta)
                toasts = self.effects("toast")
                self.assertEqual([(t["text"], t["exit"]) for t in toasts], [(toast, False)])
                self.press(0)
                self.c.drain()

    def test_sonos_shuffle_dims_play_next(self):
        self.publish(queue_state(shuffle=True, play_mode="SHUFFLE_NOREPEAT"))
        self.browse()
        self.press(2)
        self.assertEqual(self.transient(), "Shuffle on · turn it off")
        self.assertEqual([t["text"] for t in self.effects("toast")], ["Shuffle is on · turn it off to play next"])

    def test_evaluation_order_loading_before_sonos(self):
        self.publish(queue_state(online=False))
        self.press(1)
        self.c.drain()
        seq = self.c.feedback_seq
        self.press(3)                     # loading wins: ignored
        self.assertEqual(self.c.feedback_seq, seq)
        self.complete("recent", recent_page())
        self.press(3)                     # now sonos_unavailable: reason + shake
        self.assertEqual(self.transient(), "Sonos unavailable")

    def test_queueing_is_ignored_in_recent_and_explained_elsewhere(self):
        self.browse()
        self.press(2)                     # Play next out
        seq = self.c.feedback_seq
        self.press(3)
        self.press(2)
        self.assertEqual(self.c.feedback_seq, seq, "Recent shows the busy line itself")
        self.press(1)                     # the explorer: queueing is not on screen there
        self.c.drain()
        self.press(3)
        self.assertEqual(self.transient(), "Finding songs…")
        self.assertEqual(self.c.feedback["kind"], "err")


class TracksSeekMapTests(Fixture):
    def test_tracks_map(self):
        self.tracks()
        self.assertEqual(self.labels(), [("back", "Back", True), ("expand", "Up next", True),
                                         ("seek", "Seek", True), ("next", "Skip", False)])
        self.turn_to(0)
        self.assertEqual(self.labels()[3], ("prev", "Skip", True))
        self.turn_to(2)
        self.assertEqual(self.labels()[3], ("next", "Skip", True))

    def test_neutral_is_ignored(self):
        self.tracks()
        seq = self.c.feedback_seq
        self.press(3)
        self.assertEqual(self.c.feedback_seq, seq)
        self.assertFalse(self.effects("transport"))

    def test_source_dims_for_up_next_and_seek(self):
        for source, upnext, seek in (("airplay", "Up next is in Music app", "Can’t seek · AirPlay"),
                                     ("radio", "Radio · no Up next", "Can’t seek · radio"),
                                     ("linein", "Line-in · no Up next", "Can’t seek · line-in")):
            with self.subTest(source=source):
                self.publish(queue_state(source=source))
                self.tracks()
                self.press(1)
                self.assertEqual(self.transient(), upnext)
                self.press(2)
                self.assertEqual(self.transient(), seek)
                self.assertEqual(self.c.screen.mode, "tracks")
                self.press(0)

    def test_no_length_for_d_60000(self):
        self.publish(queue_state(duration_s=60000, can_seek=False))
        self.tracks()
        self.assertFalse(self.frame()["buttons"][2]["enabled"])
        self.press(2)
        self.assertEqual(self.transient(), "Can’t seek · no length")

    def test_skip_unavailable_and_queue_ends(self):
        self.publish(queue_state(P=12, T=12, can_next=False))
        self.tracks(2)
        self.assertTrue(self.frame()["buttons"][3]["enabled"], "a queue end is refused at the press")
        self.press(3)
        self.assertEqual(self.transient(), "End of queue")
        self.assertFalse(self.effects("transport"))
        self.publish(queue_state(source="radio", can_next=False, queue_length=0, playlist_position=0))
        self.assertFalse(self.frame()["buttons"][3]["enabled"])
        self.press(3)
        self.assertEqual(self.transient(), "Next unavailable")

    def test_shuffling_elsewhere_gets_the_busy_line(self):
        self.upnext()
        self.ratings()
        self.press(1)                     # companion shuffle
        self.c.drain()
        self.press(0)                     # Back to Tracks
        self.turn_to(2)
        self.press(3)
        self.assertEqual(self.transient(), "Shuffling…")

    def test_seek_map(self):
        self.seek()
        frame = self.frame()
        self.assertEqual(tokens(frame), ["back", "expand", "seek", "next"])
        self.assertEqual(frame["buttons"][2].get("lit"), "on")
        self.assertFalse(frame["buttons"][3]["enabled"])
        seq = self.c.feedback_seq
        self.press(3)
        self.assertEqual(self.c.feedback_seq, seq, "seeking: ignored")


class UpNextMapTests(Fixture):
    def test_loaded_map_and_liked_heart(self):
        self.upnext()
        self.ratings(liked={"1005"})
        frame = self.frame()
        self.assertEqual(tokens(frame), ["back", "shuffle", "heart", "play"])
        heart = frame["buttons"][2]
        self.assertEqual((heart["label"], heart["enabled"], heart.get("lit")), ("Liked", True, "on"))
        self.assertEqual(frame["buttons"][1].get("lit"), "off")
        self.turn_to(5)
        heart = self.frame()["buttons"][2]
        self.assertEqual((heart["label"], heart["enabled"], heart.get("lit")), ("Like", True, None))

    def test_liked_row_press_is_refused_without_a_request(self):
        self.upnext()
        self.ratings(liked={"1005"})
        self.press(2)
        self.assertEqual(self.transient(), "Unfavourite in Music app")
        self.assertEqual(self.c.transient.tone, "meta")
        self.assertAlmostEqual(self.c.transient.until - self.clock(), 2.2)
        self.assertEqual(self.c.feedback["kind"], "err")
        self.assertFalse([e for e in self.effects() if e["kind"] in ("like", "unlike")])
        seq = self.c.feedback_seq
        self.press(2)
        self.assertEqual(self.c.feedback_seq, seq + 1, "one shake per press")

    def test_likes_unknown_and_not_catalog(self):
        self.upnext()
        self.assertFalse(self.frame()["buttons"][2]["enabled"])
        self.press(2)
        self.assertEqual(self.transient(), "Checking likes…")
        self.assertEqual(self.c.feedback["kind"], "err")
        for effect in list(self.c.pending.values()):
            if effect["kind"] == "catalog_songs":
                self.c.complete(effect["request"], {song: {"catalog": False} for song in effect["ids"]})
        self.press(2)
        self.assertEqual(self.transient(), "Not an Apple Music song")

    def test_loading_before_the_first_window(self):
        self.upnext(loaded=False)
        self.assertEqual([b["enabled"] for b in self.frame()["buttons"]], [True, False, False, False])
        seq = self.c.feedback_seq
        for logical in (1, 2, 3):
            self.press(logical)
        self.assertEqual(self.c.feedback_seq, seq)

    def test_nothing_next(self):
        self.publish(queue_state(P=11, T=12))
        self.upnext()
        seq = self.c.feedback_seq
        self.press(1)                     # U = 1 < 2: the list shows it
        self.assertEqual(self.c.feedback_seq, seq)

    def test_play_next_block_only_is_nothing_to_shuffle(self):
        from control_center.queue_context import Segment
        self.publish(queue_state(P=10, T=12))
        self.c.ledger.record_start(Segment(kind="album", name="A"), [str(1000 + n) for n in range(1, 11)])
        self.c.ledger.append_playnext(11, ["1011", "1012"])
        self.upnext()
        self.assertFalse(self.frame()["buttons"][1]["enabled"])
        self.press(1)
        self.assertEqual(self.transient(), "Nothing to shuffle")

    def test_sonos_card(self):
        self.publish(queue_state(shuffle=True, play_mode="SHUFFLE_NOREPEAT"))
        self.upnext()
        self.turn_to(5)                   # the card at index P
        frame = self.frame()
        self.assertEqual(frame["title"], "Shuffled by Sonos")
        self.assertEqual([b["enabled"] for b in frame["buttons"]], [True, True, False, False])
        seq = self.c.feedback_seq
        self.press(3)
        self.assertEqual(self.c.feedback_seq, seq)


class WindowsMapTests(Fixture):
    def test_map_and_closed(self):
        self.open_windows()
        self.assertEqual(self.labels(), [("back", "Back", True), ("snapleft", "Snap left", True),
                                         ("snapright", "Snap right", True), ("switch", "Switch", True)])
        self.c.screen.windows.items[1]["available"] = False
        self.assertEqual([b["enabled"] for b in self.frame()["buttons"]], [True, False, False, False])
        self.press(3)
        self.assertEqual(self.transient(), "Closed · can’t switch")

    def test_empty_is_ignored(self):
        self.press(3)
        self.c.complete(self.one("windows_open")["request"], {"items": [], "index": 0, "origin": None})
        self.assertEqual(self.frame()["title"], "No eligible windows")
        seq = self.c.feedback_seq
        for logical in (1, 2, 3):
            self.press(logical)
        self.assertEqual(self.c.feedback_seq, seq)


class SilentGuardTests(Fixture):
    def test_like_in_flight(self):
        self.upnext()
        self.ratings()
        self.press(2)
        self.assertEqual(len(self.effects("like")), 1)
        self.press(2)
        self.assertFalse(self.effects("like"))

    def test_tab_swap_ignores_tab_presses(self):
        self.browse()
        self.press(1)
        self.press(2)                     # tab press at t0
        self.c.drain()
        self.tick(0.1)
        self.press(1)                     # during the 190 ms swap: ignored
        self.press(2)
        self.assertFalse(self.effects("explorer_source"))

    def test_play_window_ignores_every_button_and_hold(self):
        self.browse()
        self.press(1)
        self.c.drain()
        self.press(3)                     # Play at t0
        self.tick(0.1)
        for logical in (0, 1, 2, 3):
            self.press(logical)
        self.hold()
        kinds = [e["kind"] for e in self.effects()]
        self.assertEqual((kinds.count("play_items"), kinds.count("explorer_close")), (1, 1))
        self.assertEqual(self.c.screen.mode, "explorer")

    def test_shuffle_swap_ignores_button_2(self):
        self.upnext()
        self.ratings()
        self.press(1)
        self.tick(0.1)
        self.press(1)
        kinds = [e["kind"] for e in self.effects()]
        self.assertEqual(kinds.count("shuffle_reorder"), 1)

    def test_switch_in_flight_ignores_every_button(self):
        self.open_windows()
        self.press(3)
        self.assertEqual(len(self.effects("windows_activate")), 1)
        for logical in (0, 1, 2, 3):
            self.press(logical)
        self.assertEqual([e["kind"] for e in self.effects()], [])


class RefusalRuleTests(Fixture):
    def test_each_press_rearms_2000_ms_and_a_new_seq(self):
        self.publish(queue_state(online=False))
        self.press(2)
        first = (self.c.feedback_seq, self.c.transient.until)
        self.tick(1.0)
        self.press(2)
        self.assertEqual(self.c.feedback_seq, first[0] + 1)
        self.assertAlmostEqual(self.c.transient.until, first[1] + 1.0)
        self.tick(2.1)
        self.assertIsNone(self.c._transient())

    def test_no_reentry_on_a_refusal(self):
        self.publish(queue_state(online=False))
        control = self.c.control_id
        self.press(2)
        self.assertEqual(self.c.control_id, control)
        self.assertFalse(self.effects("device_enter"))


if __name__ == "__main__":
    unittest.main()
