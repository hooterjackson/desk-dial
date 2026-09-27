"""K3 section 9 Sonos services (WP6): read_state additions, start staging, Play next, Seek,
the shuffle hybrid, queue windows, jump and move_next, and the section 9.10 outcomes.

Headless: the FakeSpeaker of test_cc_music.py (positional inserts, ReorderTracksInQueue,
SetPlayMode, REL_TIME seek scripts) on a fake clock with a per-call latency; no network,
no Sonos, no Tk.
"""
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import sonos as S  # noqa: E402
from control_center.sonos import (  # noqa: E402
    GroupChanged, NotQueueSource, NothingPlaying, PlayNextFailed, QueueChanged, QueueReplacementFailed,
    SeekNotConfirmed, SeekUnavailable, ShuffleFailed, SongChanged, SonosAdapter, SonosError, SonosShuffleOn,
    TrackChanged, row_signature, sonos_outcome,
)
from test_cc_music import FakeClock, FakeItem, FakeSpeaker, MemoryStore, UPnPError  # noqa: E402


def song(n):
    return {"catalog_id": str(n), "title": f"Song {n}", "url": f"https://music.apple.com/ca/album/a/999?i={n}"}


def ids(items):
    return [int(item.title.split()[-1]) for item in items]


class Rig:
    """One pinned room on a fake clock (latency per SOAP call, default 50 ms)."""

    def __init__(self, queue=(90, 91), position=1, latency=0.05, **attrs):
        self.clock = FakeClock()
        self.speaker = FakeSpeaker()
        self.speaker.clock, self.speaker.latency = self.clock, latency
        self.speaker.items = [FakeItem(i) for i in queue]
        for name, value in attrs.items():
            setattr(self.speaker, name, value)
        self.zone_reads = 0

        def clear_cache():
            self.zone_reads += 1
        self.speaker.zone_group_state.clear_cache = clear_cache
        self.store, self.shuffle = MemoryStore(), MemoryStore()
        self.adapter = SonosAdapter("192.168.1.50", soco_factory=lambda host: self.speaker,
                                    share_link_factory=lambda value: value, recovery_store=self.store,
                                    shuffle_store=self.shuffle, clock=self.clock.now, sleep=self.clock.sleep)
        if position:
            self.play(position)
        self.state = self.adapter.read_state()

    def play(self, row):
        item = self.speaker.items[row - 1]
        self.speaker.track.update(uri=item.resources[0].uri, playlist_position=str(row), title=item.title)

    def refresh(self):
        self.state = self.adapter.read_state()
        return self.state

    def lock_free(self):
        """Whether another thread can take the adapter lock right now."""
        taken = []

        def probe():
            if self.adapter._lock.acquire(timeout=0.2):
                taken.append(True)
                self.adapter._lock.release()
        thread = threading.Thread(target=probe)
        thread.start()
        thread.join(1)
        return bool(taken)


# ---------------------------------------------------------------------------------- 9.1
class ReadStateTests(unittest.TestCase):
    def source(self, uri, playback="PLAYING", queue=(1, 2), position=1, track_uri="x"):
        rig = Rig(queue=queue, position=position if queue else 0, media_uri=uri, transport_state=playback)
        if track_uri is not None and not queue:
            rig.speaker.track["uri"] = track_uri
        return rig.refresh()["source"]

    def test_source_classes_for_every_uri_prefix(self):
        cases = [("x-rincon-queue:ROOM#0", "queue"), ("x-sonos-vli:RINCON_1:1,airplay:abc", "airplay"),
                 ("x-sonos-vli:RINCON_1:2,spotify:xyz", "radio"), ("x-rincon-stream:RINCON_1", "linein"),
                 ("x-sonos-htastream:RINCON_1:spdif", "linein"), ("x-sonosapi-radio:s1?sid=254", "radio"),
                 ("x-sonosapi-hls:station", "radio"), ("x-sonosapi-stream:s2", "radio"),
                 ("x-rincon-mp3radio:http://example", "radio"), ("aac://example", "radio"),
                 ("hls-radio://example", "radio"), ("x-sonos-http:sonos.example", "radio")]
        for uri, expected in cases:
            with self.subTest(uri=uri):
                self.assertEqual(self.source(uri), expected)
        self.assertEqual(self.source("x-rincon-queue:ROOM#0", playback="PAUSED_PLAYBACK"), "queue")
        self.assertEqual(self.source("x-rincon-queue:ROOM#0", playback="STOPPED"), "none")
        self.assertEqual(self.source("x-rincon-queue:ROOM#0", queue=()), "none", "an empty queue")
        rig = Rig(queue=(1, 2), position=0)
        rig.speaker.track["playlist_position"] = "0"
        self.assertEqual(rig.refresh()["source"], "none", "no valid row")
        self.assertEqual(self.source("", queue=(), track_uri=""), "none")

    def test_transitioning_keeps_the_previous_class(self):
        rig = Rig()
        self.assertEqual(rig.state["source"], "queue")
        rig.speaker.media_uri, rig.speaker.transport_state = "x-sonosapi-radio:x", "TRANSITIONING"
        self.assertEqual(rig.refresh()["source"], "queue")
        rig.speaker.transport_state = "PLAYING"
        self.assertEqual(rig.refresh()["source"], "radio")

    def test_can_seek_needs_the_queue_seektime_a_length_up_to_59999_s_and_a_position(self):
        def can(**track):
            rig = Rig(available_actions=["Play", "Pause", "SeekTime", "SeekTrackNr"])
            rig.speaker.track.update({"position": "0:01:00", "duration": "0:03:30", **track})
            return rig.refresh()
        state = can()
        self.assertTrue(state["can_seek"])
        self.assertEqual((state["position_s"], state["duration_s"]), (60, 210))
        self.assertTrue(can(duration="16:39:59")["can_seek"], "D = 59 999 s")
        self.assertFalse(can(duration="16:40:00")["can_seek"], "D = 60 000 s (C5-51)")
        self.assertFalse(can(duration="NOT_IMPLEMENTED")["can_seek"])
        self.assertIsNone(can(duration="0:00:00")["duration_s"])
        self.assertFalse(can(position="NOT_IMPLEMENTED")["can_seek"])
        rig = Rig()
        rig.speaker.track.update(position="0:01:00", duration="0:03:30")
        self.assertFalse(rig.refresh()["can_seek"], "no SeekTime")
        rig = Rig(available_actions=["SeekTime"], transport_state="STOPPED")
        rig.speaker.track.update(position="0:01:00", duration="0:03:30")
        self.assertFalse(rig.refresh()["can_seek"])
        rig = Rig(available_actions=["SeekTime"], media_uri="x-sonosapi-radio:x")
        rig.speaker.track.update(position="0:01:00", duration="0:03:30")
        self.assertFalse(rig.refresh()["can_seek"], "radio")

    def test_play_mode_position_song_id_actions_and_read_time(self):
        for mode, shuffle, repeat in (("NORMAL", False, "off"), ("REPEAT_ALL", False, "all"),
                                      ("REPEAT_ONE", False, "one"), ("SHUFFLE_NOREPEAT", True, "off"),
                                      ("SHUFFLE", True, "all"), ("SHUFFLE_REPEAT_ONE", True, "one")):
            with self.subTest(mode=mode):
                state = Rig(play_mode=mode).state
                self.assertEqual((state["shuffle"], state["repeat"]), (shuffle, repeat))
        rig = Rig(queue=(90, 91, 92), position=2, available_actions=["Next", "Previous", "SeekTime"])
        state = rig.state
        self.assertEqual((state["playlist_position"], state["song_id"]), (2, "91"))
        self.assertEqual(state["actions"], ["Next", "Previous", "SeekTime"])
        self.assertIsInstance(state["read_at"], float)
        self.assertFalse(state["companion_shuffle"])

    def test_the_poll_can_reuse_a_recent_group_context_but_writes_never_do(self):
        rig = Rig()
        before = rig.zone_reads
        rig.adapter.read_state(reuse_context_s=3.0)
        self.assertEqual(rig.zone_reads, before, "reused")
        rig.clock.advance(3.5)
        rig.adapter.read_state(reuse_context_s=3.0)
        self.assertEqual(rig.zone_reads, before + 1, "older than 3 s: read again")
        rig.adapter.set_volume(30, rig.state["group_revision"])
        self.assertGreater(rig.zone_reads, before + 1)


# ---------------------------------------------------------------------------------- 9.2
class StartTests(unittest.TestCase):
    def test_staging_reads_the_queue_once_before_and_after_and_one_tail_row_per_song(self):
        for count in (1, 5):
            with self.subTest(songs=count):
                rig = Rig(queue=(90, 91))
                zone_before = rig.zone_reads
                rig.speaker.queue_reads.clear()
                result = rig.adapter.play_items([song(n) for n in range(1, count + 1)], rig.state["group_revision"])
                self.assertEqual(ids(rig.speaker.items), list(range(1, count + 1)))
                tails = [read for read in rig.speaker.queue_reads if read[1] == 1 and read[0] >= 2]
                self.assertEqual(tails[:count], [(2 + i, 1) for i in range(count)], "one 1-row tail read per song")
                full = [read for read in rig.speaker.queue_reads if read == (0, 100)]
                self.assertEqual(len(full), 4, "before, after, the replacement's own two reads")
                self.assertEqual(rig.zone_reads - zone_before, 6, "no per-song group read")
                self.assertEqual(result["_final_song_ids"], [str(n) for n in range(1, count + 1)])

    def test_the_w5_fallback_verifies_the_whole_tail_once(self):
        rig = Rig(queue=(90, 91))
        rig.adapter.stage_tail_reads = False
        rig.speaker.queue_reads.clear()
        rig.adapter.play_items([song(1), song(2), song(3)], rig.state["group_revision"])
        self.assertEqual(ids(rig.speaker.items), [1, 2, 3])
        self.assertFalse([read for read in rig.speaker.queue_reads if read[1] == 1 and read[0] >= 2])
        rig = Rig(queue=(90, 91))
        rig.adapter.stage_tail_reads = False
        original = rig.speaker.add_share_link_to_queue
        rig.speaker.add_share_link_to_queue = lambda url, **kw: original(url.replace("i=2", "i=7"), **kw)
        with self.assertRaises(QueueReplacementFailed):
            rig.adapter.play_items([song(1), song(2)], rig.state["group_revision"])
        self.assertEqual(rig.speaker.played, [], "a wrong song is caught by the one read after staging")

    def test_the_result_carries_start_and_accepts_a_resolve_result(self):
        rig = Rig()
        result = rig.adapter.play_items({"tracks": [song(1), song(2)], "total": 3, "unavailable": 1},
                                        rig.state["group_revision"], name="PAPER LANTERN Ep. 1")
        self.assertEqual(result["_start"], {"k": 2, "n": 3, "u": 1, "name": "PAPER LANTERN Ep. 1"})
        self.assertEqual(result["_final_song_ids"], ["1", "2"])
        self.assertEqual(rig.speaker.played, [0])
        self.assertEqual(rig.shuffle.saves, 0, "a start never reads or writes a record it did not load")

    def test_a_wrong_song_or_position_stops_staging_and_never_plays(self):
        rig = Rig()
        original = rig.speaker.add_share_link_to_queue

        def wrong_song(url, **kwargs):
            return original(url.replace("i=2", "i=7"), **kwargs)
        rig.speaker.add_share_link_to_queue = wrong_song
        with self.assertRaises(QueueReplacementFailed) as error:
            rig.adapter.play_items([song(1), song(2)], rig.state["group_revision"])
        self.assertTrue(error.exception.partial, "the tail is not provably ours: kept, reported")
        self.assertEqual(rig.speaker.played, [])
        rig = Rig()

        def wrong_position(url, **kwargs):
            return original_b(url, **kwargs) + 5
        original_b = rig.speaker.add_share_link_to_queue
        rig.speaker.add_share_link_to_queue = wrong_position
        with self.assertRaises(QueueReplacementFailed):
            rig.adapter.play_items([song(1)], rig.state["group_revision"])
        self.assertEqual(rig.speaker.played, [])

    def test_the_staging_deadline_rolls_back_and_is_start_failed(self):
        rig = Rig()
        steps = []

        def slow():
            steps.append(rig.clock.now())
            rig.clock.advance(8.0)   # 6 + 0.75·2 = 7.5 s (revised 2026-09-27: ~0.5 s/song measured)
        with self.assertRaises(QueueReplacementFailed) as error:
            rig.adapter.play_items([song(1), song(2)], rig.state["group_revision"], between_steps=slow)
        self.assertTrue(error.exception.timeout)
        self.assertFalse(error.exception.partial, "our staged row was removed")
        self.assertEqual(ids(rig.speaker.items), [90, 91])
        self.assertEqual(rig.speaker.played, [])
        self.assertEqual(sonos_outcome(error.exception, "play_items"), "start_failed")
        self.assertEqual(len(steps), 1)

    def test_a_partly_playable_playlist_reports_its_counts_and_copy(self):
        # [r2.2] C5-70: `Playing {k} of {n} · {u} songs unavailable`, `1 song` when u = 1; Home's
        # status `Playing {k} of {n}` (VOC section 8.5 `playlist_partial`).
        rig = Rig()
        resolved = {"tracks": [song(n) for n in range(1, 34)], "total": 34, "unavailable": 1}
        result = rig.adapter.play_items(resolved, rig.state["group_revision"], name="PAPER LANTERN Ep. 1")
        start = result["_start"]
        self.assertEqual((start["k"], start["n"], start["u"]), (33, 34, 1))
        self.assertEqual(S.start_outcome(start), "playlist_partial")
        self.assertEqual(S.start_partial_copy(start),
                         {"status": "Playing 33 of 34", "toast": "Playing 33 of 34 · 1 song unavailable"})
        start = {"k": 30, "n": 34, "u": 4, "name": "x"}
        self.assertEqual(S.start_partial_copy(start)["toast"], "Playing 30 of 34 · 4 songs unavailable")
        full = {"k": 34, "n": 34, "u": 0, "name": "x"}
        self.assertEqual((S.start_outcome(full), S.start_partial_copy(full)), ("ok", None))
        self.assertEqual(S.start_outcome({"k": 1, "n": 1, "u": 0, "name": None, "row": 3}), "ok", "a jump")
        for broken in (None, {}, {"k": 0, "n": 1, "u": 1}, {"k": "33", "n": 34, "u": 1}, {"k": 3, "n": 2, "u": 1},
                       {"k": 33, "n": 34, "u": True}):
            with self.subTest(start=broken):
                self.assertEqual((S.start_outcome(broken), S.start_partial_copy(broken)), ("ok", None))

    def test_between_steps_runs_after_each_insert_with_the_lock_released_never_in_the_destructive_step(self):
        rig = Rig()
        seen = []

        def step():
            seen.append((len(rig.speaker.inserts), rig.lock_free(), len(rig.store.saved["items"])))
        rig.adapter.play_items([song(1), song(2), song(3)], rig.state["group_revision"], between_steps=step)
        self.assertEqual([entry[0] for entry in seen], [1, 2, 3])
        self.assertTrue(all(entry[1] for entry in seen), "the adapter lock is free between steps")
        self.assertEqual(rig.speaker.played, [0])

    def test_a_start_plays_unshuffled_with_repeat_kept_and_drops_the_companion_record(self):
        rig = Rig(play_mode="SHUFFLE")
        rig.shuffle.saved = {"room_uid": "ROOM", "base_rows": [["x", "1"]]}
        rig.adapter.load_shuffle_record()   # the runtime loads it once at start
        order = []
        play = rig.speaker.avTransport.Play
        rig.speaker.avTransport.Play = lambda *a, **k: (order.append(list(rig.speaker.play_modes)), play(*a, **k))
        rig.adapter.play_items([song(1)], rig.state["group_revision"])
        self.assertEqual(rig.speaker.play_modes, ["REPEAT_ALL"])
        self.assertEqual(order, [["REPEAT_ALL"]], "the mode changed before Play")
        self.assertEqual(rig.shuffle.saved, {})

    def test_a_refused_unshuffle_never_stops_the_start(self):
        # C5-20 is best effort inside the destructive step (section 1.1): the start still plays.
        for error in (UPnPError(712), TimeoutError("timed out")):
            with self.subTest(error=type(error).__name__):
                rig = Rig(play_mode="SHUFFLE", play_mode_error=error)
                with self.assertLogs(S.__name__, level="WARNING") as logs:
                    result = rig.adapter.play_items([song(1), song(2)], rig.state["group_revision"])
                self.assertEqual(ids(rig.speaker.items), [1, 2])
                self.assertEqual(rig.speaker.played, [0])
                self.assertEqual(result["_final_song_ids"], ["1", "2"])
                self.assertEqual(result["play_mode"], "SHUFFLE", "the state shows the mode that stayed")
                self.assertNotIn("Song", " ".join(logs.output), "status only, never a title")

    def test_a_group_change_mid_staging_rolls_our_rows_back_and_is_group_changed(self):
        for after in (1, 2, 3):
            with self.subTest(after_insert=after):
                rig = Rig(queue=(90, 91))

                def regroup():
                    if len(rig.speaker.inserts) == after:
                        rig.speaker.group.uid = "NEWGROUP"   # the room joined another group
                with self.assertRaises(QueueReplacementFailed) as raised:
                    rig.adapter.play_items([song(1), song(2), song(3)], rig.state["group_revision"],
                                           between_steps=regroup)
                error = raised.exception
                self.assertFalse(error.partial, "our staged rows were proven and removed")
                self.assertTrue(error.group_changed)
                self.assertEqual(ids(rig.speaker.items), [90, 91])
                self.assertEqual(rig.speaker.played, [])
                self.assertEqual(sonos_outcome(error, "play_items"), "group_changed")
        self.assertEqual(sonos_outcome(QueueReplacementFailed("x", partial=True), "play_items"), "start_failed")


# ---------------------------------------------------------------------------------- 9.3
class PlayNextTests(unittest.TestCase):
    def rig(self, queue=(90, 91, 92, 93), position=2, **attrs):
        return Rig(queue=queue, position=position, **attrs)

    def run_next(self, rig, songs, **kwargs):
        return rig.adapter.play_next(songs, rig.state["group_revision"], rig.state["track_id"], **kwargs)

    def test_inserts_land_at_p_plus_1_plus_i_in_order_and_are_verified(self):
        rig = self.rig()
        progress = []
        result = self.run_next(rig, [song(1), song(2)], progress=progress.append)
        self.assertEqual(ids(rig.speaker.items), [90, 91, 1, 2, 92, 93])
        self.assertEqual([(p, i) for p, i, _ in rig.speaker.inserts], [(3, "1"), (4, "2")])
        self.assertTrue(all(not as_next for _, _, as_next in rig.speaker.inserts), "never EnqueueAsNext")
        self.assertEqual(progress, [{"phase": "inserting", "k": 1, "n": 2}, {"phase": "inserting", "k": 2, "n": 2}])
        self.assertEqual(result["_inserted"], {"start_row": 3, "song_ids": ["1", "2"]})
        self.assertEqual(rig.speaker.track["playlist_position"], "2", "playback untouched")

    def test_k_counts_only_verified_inserts_and_is_never_0(self):
        # [r2.2] C5-69 / C5-71: `Finding songs…` holds until song 1's insert is verified, so the
        # adapter reports k only after each verified insert; it never reports k = 0.
        rig = self.rig(fail_enqueue_at=2)
        progress = []
        with self.assertRaises(PlayNextFailed):
            self.run_next(rig, [song(1), song(2)], progress=progress.append)
        self.assertEqual(progress, [{"phase": "inserting", "k": 1, "n": 2}], "the failed insert is not counted")
        rig = self.rig(enqueue_error=UPnPError(800))
        progress = []
        with self.assertRaises(PlayNextFailed):
            self.run_next(rig, [song(1)], progress=progress.append)
        self.assertEqual(progress, [], "nothing queued: the knob never left `Finding songs…`")
        rig = self.rig()
        original = rig.speaker.add_share_link_to_queue
        seen = []

        def timed_out(url, **kwargs):
            original(url, **kwargs)
            raise RuntimeError("read timed out")
        rig.speaker.add_share_link_to_queue = timed_out
        rig.speaker.on_call = lambda count, name: seen.append(name)
        progress = []
        self.run_next(rig, [song(1)], progress=lambda payload: progress.append((payload, list(seen))))
        (payload, calls), = progress
        self.assertEqual(payload, {"phase": "inserting", "k": 1, "n": 1})
        self.assertEqual(calls[-2:], ["AddURIToQueue", "Browse"], "an ambiguous insert counts once its row is read")

    def test_the_knob_line_for_each_progress_payload(self):
        # [r2.2] C5-69 (VOC-R28, VOC-R30): `Finding songs…` while resolving and while k == 0 (a
        # pre-resolved item's first payload), `Queueing… {k} of {n}` from k = 1.
        cases = [(S.playnext_resolving(), (S.PLAYNEXT_RESOLVING, {})),
                 (S.playnext_resolving(8), (S.PLAYNEXT_RESOLVING, {})),
                 (S.playnext_inserting(0, 8), (S.PLAYNEXT_RESOLVING, {})),
                 (S.playnext_inserting(1, 8), (S.PLAYNEXT_PROGRESS, {"k": 1, "n": 8})),
                 (S.playnext_inserting(8, 8), (S.PLAYNEXT_PROGRESS, {"k": 8, "n": 8})),
                 ({}, (S.PLAYNEXT_RESOLVING, {})), (None, (S.PLAYNEXT_RESOLVING, {})),
                 ({"phase": "inserting", "k": True, "n": 2}, (S.PLAYNEXT_RESOLVING, {})),
                 ({"phase": "inserting", "k": 3, "n": 2}, (S.PLAYNEXT_RESOLVING, {}))]
        for payload, expected in cases:
            with self.subTest(payload=payload):
                self.assertEqual(S.playnext_meta(payload), expected)
        self.assertEqual(S.playnext_resolving(8), {"phase": "resolving", "n": 8})
        self.assertEqual(S.playnext_resolving(None), {"phase": "resolving", "n": None})
        self.assertEqual(S.playnext_inserting(0, 8), {"phase": "inserting", "k": 0, "n": 8})
        self.assertEqual(S.playnext_line(S.playnext_resolving()), "Finding songs…")
        self.assertEqual(S.playnext_line(S.playnext_inserting(0, 8)), "Finding songs…")
        self.assertEqual(S.playnext_line(S.playnext_inserting(3, 8)), "Queueing… 3 of 8")
        self.assertNotIn("0 of", S.playnext_line(S.playnext_inserting(0, 8)))
        rig = self.rig()
        lines = []
        self.run_next(rig, [song(1), song(2)], progress=lambda payload: lines.append(S.playnext_line(payload)))
        self.assertEqual(lines, ["Queueing… 1 of 2", "Queueing… 2 of 2"])

    def test_the_last_row_appends_and_stacking_puts_the_newest_block_first(self):
        rig = self.rig(queue=(90, 91), position=2)
        self.run_next(rig, [song(1), song(2)])
        self.assertEqual([(p, i) for p, i, _ in rig.speaker.inserts], [(0, "1"), (0, "2")])
        self.assertEqual(ids(rig.speaker.items), [90, 91, 1, 2])
        rig.refresh()
        self.run_next(rig, [song(5)])
        self.assertEqual(ids(rig.speaker.items), [90, 91, 5, 1, 2])

    def test_between_steps_runs_after_every_insert_with_the_lock_free(self):
        rig = self.rig()
        seen = []
        self.run_next(rig, [song(1), song(2), song(3)],
                      between_steps=lambda: seen.append((len(rig.speaker.inserts), rig.lock_free())))
        self.assertEqual(seen, [(1, True), (2, True), (3, True)])

    def test_at_most_100_songs_the_first_100_in_order(self):
        rig = self.rig(latency=0.0)
        result = self.run_next(rig, [song(n) for n in range(1, 121)])
        self.assertEqual(len(rig.speaker.inserts), 100)
        self.assertEqual(result["_inserted"]["song_ids"], [str(n) for n in range(1, 101)])
        self.assertEqual(ids(rig.speaker.items)[2:102], list(range(1, 101)))

    def test_gates_refuse_before_any_insert(self):
        cases = [({"media_uri": "x-sonosapi-radio:x"}, NotQueueSource, "not_queue_source"),
                 ({"play_mode": "SHUFFLE_NOREPEAT"}, SonosShuffleOn, "sonos_shuffle_on")]
        for attrs, error, outcome in cases:
            with self.subTest(attrs=attrs):
                rig = self.rig(**attrs)
                with self.assertRaises(error) as raised:
                    self.run_next(rig, [song(1)])
                self.assertEqual(sonos_outcome(raised.exception, "play_next"), outcome)
                self.assertEqual(rig.speaker.inserts, [])
        rig = self.rig()
        self.assertEqual(self.rig(media_uri="x-sonos-vli:R:1,airplay:x").state["source"], "airplay")
        with self.assertRaises(NotQueueSource) as raised:
            self.rig(media_uri="x-sonos-vli:R:1,airplay:x").adapter.play_next(
                [song(1)], rig.state["group_revision"], rig.state["track_id"])
        self.assertEqual(raised.exception.source, "airplay")
        rig = self.rig()
        rig.speaker.track["title"] = "Another song"
        with self.assertRaises(TrackChanged) as raised:
            self.run_next(rig, [song(1)])
        self.assertEqual(sonos_outcome(raised.exception, "play_next"), "song_changed")
        rig = self.rig()
        rig.speaker.items = []
        with self.assertRaises(NothingPlaying) as raised:
            self.run_next(rig, [song(1)])
        self.assertEqual(sonos_outcome(raised.exception, "play_next"), "not_queue_source")
        self.assertEqual(rig.speaker.inserts, [])

    def test_a_refused_first_insert_adds_nothing(self):
        rig = self.rig(enqueue_error=UPnPError(800))
        with self.assertRaises(PlayNextFailed) as raised:
            self.run_next(rig, [song(1), song(2)])
        self.assertEqual((raised.exception.outcome, raised.exception.inserted), ("nothing_added", 0))
        self.assertEqual(ids(rig.speaker.items), [90, 91, 92, 93])
        self.assertEqual(rig.speaker.removals, [])

    def test_a_failure_after_an_insert_rolls_back_exactly_our_rows(self):
        rig = self.rig(fail_enqueue_at=2)
        with self.assertRaises(PlayNextFailed) as raised:
            self.run_next(rig, [song(1), song(2)])
        self.assertEqual((raised.exception.outcome, raised.exception.inserted), ("nothing_added", 1))
        self.assertTrue(raised.exception.rolled_back)
        self.assertEqual(ids(rig.speaker.items), [90, 91, 92, 93])
        self.assertEqual(rig.speaker.removals, [(2, 1)], "StartingIndex P+1, one row, fresh UpdateID")
        self.assertNotIn("secret", str(raised.exception))

    def test_rows_that_are_not_provably_ours_stay_and_are_partial(self):
        rig = self.rig()
        original = rig.speaker.add_share_link_to_queue

        def second_fails_after_a_foreign_edit(url, **kwargs):
            if rig.speaker.enqueue_count == 1:
                rig.speaker.enqueue_count += 1
                rig.speaker.items.insert(0, FakeItem(777))   # another controller edits above us
                rig.speaker.revision += 1
                raise RuntimeError("timeout")
            return original(url, **kwargs)
        rig.speaker.add_share_link_to_queue = second_fails_after_a_foreign_edit
        with self.assertRaises(PlayNextFailed) as raised:
            self.run_next(rig, [song(1), song(2)])
        self.assertEqual(raised.exception.outcome, "partial")
        self.assertEqual(rig.speaker.removals, [])
        self.assertIn(1, ids(rig.speaker.items))

    def test_an_ambiguous_timeout_that_did_insert_continues(self):
        rig = self.rig()
        original = rig.speaker.add_share_link_to_queue

        def inserted_then_timed_out(url, **kwargs):
            original(url, **kwargs)
            raise RuntimeError("read timed out")
        rig.speaker.add_share_link_to_queue = inserted_then_timed_out
        result = self.run_next(rig, [song(1), song(2)])
        self.assertEqual(ids(rig.speaker.items), [90, 91, 1, 2, 92, 93])
        self.assertEqual(result["_inserted"]["song_ids"], ["1", "2"])

    def test_the_song_ending_before_the_first_insert_is_song_changed_and_rolled_back(self):
        rig = self.rig(queue=(90, 91, 92, 93, 94), position=2)

        def end_song(count, name):
            if name == "Browse" and len(rig.speaker.inserts) == 2:
                rig.play(5)   # rows 3, 4 are ours; the playhead is now past the block
        rig.speaker.on_call = end_song
        with self.assertRaises(SongChanged) as raised:
            self.run_next(rig, [song(1), song(2)])
        self.assertTrue(raised.exception.rolled_back)
        self.assertEqual(sonos_outcome(raised.exception, "play_next"), "song_changed")
        self.assertEqual(ids(rig.speaker.items), [90, 91, 92, 93, 94])

    def test_the_song_ending_into_the_block_is_still_ok(self):
        rig = self.rig()

        def end_song(count, name):
            if name == "Browse" and len(rig.speaker.inserts) == 2:
                rig.play(3)   # playback moved into song 1 of the block
        rig.speaker.on_call = end_song
        result = self.run_next(rig, [song(1), song(2)])
        self.assertEqual(result["_inserted"]["start_row"], 3)

    def test_a_verification_mismatch_after_the_inserts_rolls_back(self):
        rig = self.rig()

        def external_removal(count, name):
            if name == "Browse" and len(rig.speaker.inserts) == 2 and len(rig.speaker.items) == 6:
                del rig.speaker.items[-1]   # another controller removed the last row
                rig.speaker.revision += 1
        rig.speaker.on_call = external_removal
        with self.assertRaises(PlayNextFailed) as raised:
            self.run_next(rig, [song(1), song(2)])
        self.assertEqual(raised.exception.outcome, "nothing_added")
        self.assertEqual(ids(rig.speaker.items), [90, 91, 92])

    def test_a_group_change_is_group_changed_whatever_the_rollback_did(self):
        # [WP6-r22] Section 9.10: GroupChanged → group_changed (`Speaker group changed`) for any
        # Sonos op, as play_items does; the rollback still runs and `outcome` keeps what it did.
        for into_block, rolled in ((False, True), (True, False)):
            with self.subTest(rolled_back=rolled):
                rig = self.rig()
                fired = []

                def zone_read():
                    rig.zone_reads += 1
                    if len(rig.speaker.inserts) == 2 and not fired:
                        fired.append(True)
                        rig.speaker.group.uid = "NEWGROUP"   # the room joined another group
                        if into_block:
                            rig.play(3)                        # and the playhead entered our block
                rig.speaker.zone_group_state.clear_cache = zone_read
                with self.assertRaises(SonosError) as raised:
                    self.run_next(rig, [song(1), song(2)])
                error = raised.exception
                self.assertEqual(sonos_outcome(error, "play_next"), "group_changed")
                if rolled:
                    self.assertIsInstance(error, GroupChanged)
                    self.assertEqual(ids(rig.speaker.items), [90, 91, 92, 93])
                else:
                    self.assertEqual((error.outcome, error.group_changed, error.inserted), ("partial", True, 2))
                    self.assertEqual(ids(rig.speaker.items), [90, 91, 1, 2, 92, 93], "not provably ours: kept")
        self.assertFalse(PlayNextFailed("x", outcome="partial").group_changed)
        self.assertEqual(sonos_outcome(PlayNextFailed("x", outcome="partial"), "play_next"), "partial")

    def test_the_group_changed_message_names_the_speaker_group(self):
        # [r2.2] C5-70: `Speaker group changed` ("Group" alone is ambiguous); the desktop notice
        # keeps the full sanitised text, which the v6 controller still matches by "group changed".
        rig = self.rig()
        rig.speaker.group.uid = "NEWGROUP"
        with self.assertRaises(GroupChanged) as raised:
            self.run_next(rig, [song(1)])
        self.assertIn("speaker group changed", str(raised.exception).lower())
        self.assertEqual(rig.speaker.inserts, [])

    @staticmethod
    def misplace(rig, at, to=0):
        """Insert number ``at`` (1-based) lands at row ``to`` (0 = appended) and Sonos says so."""
        original = rig.speaker.add_share_link_to_queue

        def insert(url, **kwargs):
            if rig.speaker.enqueue_count + 1 == at:
                kwargs["position"] = to
            return original(url, **kwargs)
        rig.speaker.add_share_link_to_queue = insert

    def test_a_misplaced_first_insert_counts_and_is_rolled_back(self):
        rig = self.rig()                       # [90, 91, 92, 93], P = 2
        self.misplace(rig, 1)                  # Sonos appends song 1 and returns row 5
        with self.assertRaises(PlayNextFailed) as raised:
            self.run_next(rig, [song(1), song(2)])
        error = raised.exception
        self.assertEqual((error.outcome, error.inserted, error.rolled_back), ("nothing_added", 1, True))
        self.assertEqual(ids(rig.speaker.items), [90, 91, 92, 93], "nothing of ours is left")
        self.assertEqual(rig.speaker.removals, [(4, 1)], "exactly the stray row 5")
        self.assertEqual(len(rig.speaker.inserts), 1, "no insert after the failed check")

    def test_a_misplaced_later_insert_rolls_back_the_stray_first_then_the_block(self):
        rig = self.rig()
        self.misplace(rig, 2)                  # song 1 at row 3, song 2 appended at row 6
        with self.assertRaises(PlayNextFailed) as raised:
            self.run_next(rig, [song(1), song(2), song(3)])
        error = raised.exception
        self.assertEqual((error.outcome, error.inserted, error.rolled_back), ("nothing_added", 2, True))
        self.assertEqual(ids(rig.speaker.items), [90, 91, 92, 93])
        self.assertEqual(rig.speaker.removals, [(5, 1), (2, 1)])

    def test_a_misplaced_insert_inside_the_block_is_removed_with_it(self):
        rig = self.rig()
        self.misplace(rig, 3, to=3)            # songs 1, 2 at rows 3, 4; song 3 lands at row 3
        with self.assertRaises(PlayNextFailed) as raised:
            self.run_next(rig, [song(1), song(2), song(3)])
        self.assertEqual((raised.exception.outcome, raised.exception.rolled_back), ("nothing_added", True))
        self.assertEqual(ids(rig.speaker.items), [90, 91, 92, 93])
        self.assertEqual(rig.speaker.removals, [(2, 3)], "rows P+1..P+3 in the order the inserts made")

    def test_a_misplaced_insert_above_the_current_row_stays_and_is_partial(self):
        rig = self.rig()
        self.misplace(rig, 1, to=1)
        with self.assertRaises(PlayNextFailed) as raised:
            self.run_next(rig, [song(1), song(2)])
        self.assertEqual((raised.exception.outcome, raised.exception.inserted), ("partial", 1))
        self.assertEqual(sonos_outcome(raised.exception, "play_next"), "partial")
        self.assertEqual(rig.speaker.removals, [])
        self.assertEqual(ids(rig.speaker.items), [1, 90, 91, 92, 93])

    def test_a_stray_that_is_not_provably_ours_stays_and_is_partial(self):
        rig = self.rig()
        self.misplace(rig, 2)                  # song 2 appended at row 6

        def foreign_edit(count, name):          # another controller replaces the stray row
            if name == "Browse" and len(rig.speaker.inserts) == 2 and ids(rig.speaker.items)[-1] == 2:
                rig.speaker.items[-1] = FakeItem(555)
                rig.speaker.revision += 1
        rig.speaker.on_call = foreign_edit
        with self.assertRaises(PlayNextFailed) as raised:
            self.run_next(rig, [song(1), song(2)])
        self.assertEqual(raised.exception.outcome, "partial")
        self.assertEqual(rig.speaker.removals, [], "nothing removed on a failed proof")
        self.assertIn(1, ids(rig.speaker.items))

    def test_an_ambiguous_insert_that_grew_the_queue_elsewhere_is_partial(self):
        rig = self.rig()
        original = rig.speaker.add_share_link_to_queue

        def appended_then_timed_out(url, **kwargs):
            original(url, **dict(kwargs, position=0))
            raise RuntimeError("read timed out")
        rig.speaker.add_share_link_to_queue = appended_then_timed_out
        with self.assertRaises(PlayNextFailed) as raised:
            self.run_next(rig, [song(1)])
        self.assertEqual((raised.exception.outcome, raised.exception.inserted), ("partial", 0))
        self.assertEqual(ids(rig.speaker.items), [90, 91, 92, 93, 1])
        rig = self.rig()
        calls = []

        def second_appended_then_timed_out(url, **kwargs):
            calls.append(url)
            if len(calls) == 2:
                original_b(url, **dict(kwargs, position=0))
                raise RuntimeError("read timed out")
            return original_b(url, **kwargs)
        original_b = rig.speaker.add_share_link_to_queue
        rig.speaker.add_share_link_to_queue = second_appended_then_timed_out
        with self.assertRaises(PlayNextFailed) as raised:
            self.run_next(rig, [song(1), song(2)])
        self.assertEqual(raised.exception.outcome, "partial", "song 2 may be queued elsewhere")
        self.assertEqual(rig.speaker.removals, [(2, 1)], "the verified block is still cleaned up")
        self.assertEqual(ids(rig.speaker.items), [90, 91, 92, 93, 2])


# ---------------------------------------------------------------------------------- 9.4
class SeekTests(unittest.TestCase):
    def rig(self, script=None, latency=0.0, **attrs):
        rig = Rig(queue=(90, 91), position=1, latency=latency,
                  available_actions=["Play", "Pause", "SeekTime", "SeekTrackNr"], **attrs)
        rig.speaker.track.update(position="0:00:10", duration="0:03:30")
        rig.speaker.seek_script = script or {"transition_s": 2.65}
        rig.refresh()
        return rig

    def seek(self, rig, seconds, **kwargs):
        return rig.adapter.seek(seconds, rig.state["group_revision"], rig.state["track_id"], **kwargs)

    def test_the_target_is_clamped_to_d_minus_3_and_sent_once(self):
        rig = self.rig(script={"transition_s": 0.3})
        result = self.seek(rig, 400)
        self.assertEqual(rig.speaker.rel_seeks, ["0:03:27"])
        self.assertEqual(result["_applied_seek"], 207)
        rig = self.rig(script={"transition_s": 0.3})
        self.assertEqual(self.seek(rig, -5)["_applied_seek"], 0)

    def test_the_live_script_confirms_at_the_first_settled_read_after_transitioning(self):
        rig = self.rig()
        start = rig.clock.now()
        reads = []
        rig.speaker.on_call = lambda n, name: reads.append((round(rig.clock.now() - start, 2), name))
        result = self.seek(rig, 100)
        elapsed = rig.clock.now() - start
        self.assertAlmostEqual(elapsed, 2.7, delta=0.06)
        self.assertEqual((rig.speaker.rel_seeks, result["_applied_seek"]), (["0:01:40"], 100))
        self.assertTrue(result["_seek_kept_state"])
        polls = [t for t, name in reads if name == "GetTransportInfo" and t < 2.65]
        self.assertGreater(len(polls), 20, "position already at the target while TRANSITIONING never confirmed")

    def test_a_read_3_s_off_after_transitioning_is_ok_and_only_logged(self):
        # [r2.2] C5-68: landed = playback resumed; the position is logged, not checked
        # (rev 4 kept polling here).
        rig = self.rig(script={"transition_s": 1.0})
        start = rig.clock.now()

        def drift(count, name):
            if name == "GetPositionInfo" and rig.speaker.rel_seeks:
                rig.speaker.track["position"] = "0:01:37"   # 3 s before the target
        rig.speaker.on_call = drift
        with self.assertLogs(S.__name__, level="DEBUG") as logs:
            result = self.seek(rig, 100)
        self.assertLess(rig.clock.now() - start, 1.2, "the first read out of TRANSITIONING")
        self.assertEqual(result["_applied_seek"], 100)
        self.assertTrue(result["_seek_kept_state"])
        self.assertEqual(len(logs.records), 1)
        self.assertIn("-3", logs.output[0])
        self.assertNotIn("Song", logs.output[0], "numbers only, never a title")

    def test_without_transitioning_it_confirms_only_from_1_s_after_the_reply(self):
        rig = self.rig(script={"never": True})
        start = rig.clock.now()
        self.seek(rig, 100)
        self.assertGreaterEqual(rig.clock.now() - start, 1.0)
        self.assertLess(rig.clock.now() - start, 1.15)

    def test_without_transitioning_a_read_3_s_off_is_ok_from_1_s(self):
        rig = self.rig(script={"never": True})
        rig.speaker.on_call = lambda count, name: rig.speaker.track.update(position="0:01:43") \
            if name == "GetPositionInfo" and rig.speaker.rel_seeks else None
        start = rig.clock.now()
        self.assertEqual(self.seek(rig, 100)["_applied_seek"], 100)
        self.assertGreaterEqual(rig.clock.now() - start, 1.0)
        self.assertLess(rig.clock.now() - start, 1.15)

    def test_a_resume_after_6_s_is_inside_the_8_s_window(self):
        rig = self.rig(script={"transition_s": 6.0}, latency=0.05)
        sent = []
        rig.speaker.on_call = lambda count, name: sent.append(rig.clock.now()) if name == "Seek" else None
        result = self.seek(rig, 100)
        self.assertEqual((rig.speaker.rel_seeks, result["_applied_seek"]), (["0:01:40"], 100))
        self.assertGreaterEqual(rig.clock.now() - sent[0], 6.0)
        self.assertLess(rig.clock.now() - sent[0], 6.35)

    def test_a_paused_seek_lands_on_paused_playback(self):
        rig = self.rig(script={"transition_s": 0.8, "then": "PAUSED_PLAYBACK"}, transport_state="PAUSED_PLAYBACK")
        result = self.seek(rig, 100)
        self.assertEqual((result["_applied_seek"], result["_seek_kept_state"]), (100, True))
        rig = self.rig(script={"transition_s": 0.8, "then": "PAUSED_PLAYBACK"})
        self.assertFalse(self.seek(rig, 100)["_seek_kept_state"], "another controller paused meanwhile")

    def test_stopped_after_transitioning_keeps_polling_and_is_not_confirmed(self):
        rig = self.rig(script={"transition_s": 1.0, "then": "STOPPED"}, latency=0.05)
        sent = []
        rig.speaker.on_call = lambda count, name: sent.append(rig.clock.now()) if name == "Seek" else None
        with self.assertRaises(SeekNotConfirmed):
            self.seek(rig, 100)   # the position reads the target all along
        self.assertGreaterEqual(rig.clock.now() - sent[0], 8.0 - 1e-6)
        self.assertEqual(len(rig.speaker.rel_seeks), 1)
        rig = self.rig(script={"never": True}, transport_state="PLAYING")
        rig.speaker.on_call = lambda count, name: setattr(rig.speaker, "transport_state", "STOPPED") \
            if name == "Seek" else None
        with self.assertRaises(SeekNotConfirmed):
            self.seek(rig, 100)

    def test_no_resume_in_8_s_is_not_confirmed_with_exactly_one_seek(self):
        # K3 section 16 [r2.2]: a resume after the window, and a speaker that never leaves
        # TRANSITIONING (the sim's `noresume`), are both `not_confirmed` at 8 s.
        for transition in (9.0, float("inf")):
            with self.subTest(transition_s=transition):
                rig = self.rig(script={"transition_s": transition}, latency=0.05)
                sent = []
                rig.speaker.on_call = lambda count, name, rig=rig, sent=sent:                     sent.append(rig.clock.now()) if name == "Seek" else None
                with self.assertRaises(SeekNotConfirmed) as raised:
                    self.seek(rig, 100)
                self.assertEqual(len(rig.speaker.rel_seeks), 1)
                self.assertEqual(S.SEEK_CONFIRM_S, 8.0)
                self.assertGreaterEqual(rig.clock.now() - sent[0], 8.0 - 1e-6)
                self.assertLess(rig.clock.now() - sent[0], 8.25)
                self.assertEqual(sonos_outcome(raised.exception, "seek"), "not_confirmed")

    def test_a_follow_up_jump_after_a_landing_is_one_more_seek_of_its_own(self):
        # [r2.2] C5-68: a turn during a jump moves the target; when the jump lands the controller
        # sends at most one follow-up jump with the latest target, on the same expected track id
        # (a seek never changes it). The adapter treats it as a new seek: one Seek, its own landing.
        rig = self.rig()
        revision, track = rig.state["group_revision"], rig.state["track_id"]
        sends = []
        rig.speaker.on_call = lambda count, name: sends.append(rig.clock.now()) if name == "Seek" else None
        first = rig.adapter.seek(100, revision, track)
        landed = rig.clock.now()
        second = rig.adapter.seek(150, revision, track)
        self.assertEqual(rig.speaker.rel_seeks, ["0:01:40", "0:02:30"], "one Seek per jump, never resent")
        self.assertEqual((first["_applied_seek"], second["_applied_seek"]), (100, 150))
        self.assertEqual(first["track_id"], track)
        self.assertGreaterEqual(sends[1], landed, "the follow-up goes out after the first landed")
        self.assertAlmostEqual(rig.clock.now() - sends[1], 2.7, delta=0.06, msg="its own ≈ 2.7 s landing")

    def test_between_steps_runs_between_polls_with_the_lock_released(self):
        rig = self.rig(latency=0.05)
        seen = []
        self.seek(rig, 100, between_steps=lambda: seen.append(rig.lock_free()))
        self.assertGreater(len(seen), 10)
        self.assertTrue(all(seen))

    def test_the_group_is_read_every_500_ms_and_before_the_result(self):
        rig = self.rig()
        before = rig.zone_reads
        self.seek(rig, 100)
        self.assertIn(rig.zone_reads - before, range(6, 10))

    def test_a_track_change_near_the_end_is_the_song_ending_otherwise_track_changed(self):
        rig = self.rig(script={"transition_s": 0.5})

        def next_song(count, name):
            if name == "GetPositionInfo" and rig.speaker.rel_seeks:
                rig.play(2)
        rig.speaker.on_call = next_song
        result = self.seek(rig, 205)
        self.assertTrue(result["_seek_song_ended"])
        rig = self.rig(script={"transition_s": 0.5})
        rig.speaker.on_call = lambda count, name: rig.play(2) if name == "GetPositionInfo" and rig.speaker.rel_seeks else None
        with self.assertRaises(TrackChanged) as raised:
            self.seek(rig, 100)
        self.assertEqual(sonos_outcome(raised.exception, "seek"), "song_changed")

    def test_seek_is_refused_without_a_length_seektime_or_playback(self):
        rig = self.rig()
        rig.speaker.available_actions.remove("SeekTime")
        with self.assertRaises(SeekUnavailable):
            self.seek(rig, 50)
        rig = self.rig()
        rig.speaker.track["duration"] = "NOT_IMPLEMENTED"
        rig.refresh()
        with self.assertRaises(SeekUnavailable):
            self.seek(rig, 50)
        rig = self.rig(transport_state="STOPPED")
        with self.assertRaises(SeekUnavailable):
            self.seek(rig, 50)
        self.assertEqual(rig.speaker.rel_seeks, [])

    def test_upnp_701_710_711_are_not_confirmed_and_800_is_sonos_unavailable(self):
        for code, outcome in ((701, "not_confirmed"), (711, "not_confirmed"), (800, "sonos_unavailable")):
            with self.subTest(code=code):
                rig = self.rig()

                def refuse(args, **kwargs):
                    raise UPnPError(code)
                rig.speaker.avTransport.Seek = refuse
                with self.assertRaises(SonosError) as raised:
                    self.seek(rig, 50)
                self.assertEqual(sonos_outcome(raised.exception, "seek"), outcome)
                self.assertNotIn("UPnP", str(raised.exception))


# ---------------------------------------------------------------------------------- 9.5
class CompanionShuffleTests(unittest.TestCase):
    QUEUE = tuple(range(90, 100))   # rows 1..10; P = 2 → U = 8 upcoming rows (92..99)

    def rig(self, position=2, **attrs):
        return Rig(queue=self.QUEUE, position=position, latency=0.0, **attrs)

    def on(self, rig, plan, pn=(), **kwargs):
        rows = rig.speaker.items[rig.state["playlist_position"]:]
        return rig.adapter.shuffle_reorder(True, rig.state["group_revision"], rig.state["track_id"], plan=plan,
                                           playnext_offsets=list(pn), expected_rows=[row_signature(x) for x in rows],
                                           **kwargs)

    def off(self, rig, playnext_song_ids=(), **kwargs):
        rig.refresh()
        return rig.adapter.shuffle_reorder(False, rig.state["group_revision"], rig.state["track_id"],
                                           playnext_song_ids=list(playnext_song_ids), **kwargs)

    def test_the_plan_is_realised_after_the_current_row_and_the_record_is_kept_before_acceptance(self):
        rig = self.rig()
        plan = [3, 0, 7, 1, 6, 2, 5, 4]
        accepted = []

        def progress(payload):
            accepted.append((payload, dict(rig.shuffle.saved or {}), len(rig.speaker.reorders)))
        state = self.on(rig, plan, progress=progress)
        upcoming = list(self.QUEUE[2:])
        self.assertEqual(ids(rig.speaker.items), [90, 91] + [upcoming[j] for j in plan])
        (payload, record, moves_then), = accepted
        self.assertEqual(payload, {"phase": "accepted"})
        self.assertEqual(moves_then, 0, "accepted before any move")
        self.assertEqual(len(record["base_rows"]), 8)
        self.assertEqual([entry[1] for entry in record["base_rows"]], [str(v) for v in upcoming])
        self.assertTrue(all(len(entry[0]) == 24 for entry in record["base_rows"]), "digests, no titles")
        self.assertIsNotNone(rig.shuffle.saved["update_id_after"])
        self.assertTrue(state["companion_shuffle"])
        self.assertLessEqual(len(rig.speaker.reorders), 7, "at most U_r − 1 moves")
        self.assertTrue(all(before >= 3 for _, _, before in rig.speaker.reorders), "nothing at or before P moves")

    def test_the_play_next_block_stays_first_and_is_not_in_the_record(self):
        rig = self.rig()
        plan = [0, 1, 5, 2, 7, 3, 6, 4]
        self.on(rig, plan, pn=[0, 1])
        self.assertEqual(ids(rig.speaker.items)[2:4], [92, 93])
        self.assertEqual([entry[1] for entry in rig.shuffle.saved["base_rows"]],
                         ["94", "95", "96", "97", "98", "99"])

    def test_gates_refuse_without_moving_anything(self):
        cases = [([0, 1, 2, 3, 4, 5, 6, 7], list(range(7)), ShuffleFailed),      # U_r = 1
                 ([1, 0, 2, 3, 4, 5, 6, 7], [0], ShuffleFailed),                  # the block not first
                 ([0, 1, 2, 3, 4, 5, 6], [], ShuffleFailed)]                      # not a permutation
        for plan, pn, error in cases:
            with self.subTest(plan=plan, pn=pn):
                rig = self.rig()
                with self.assertRaises(error):
                    self.on(rig, plan, pn=pn)
                self.assertEqual((rig.speaker.reorders, rig.shuffle.saved), ([], None))
        rig = Rig(queue=tuple(range(1, 70)), position=2, latency=0.0)
        with self.assertRaises(ShuffleFailed):
            self.on(rig, list(range(67)))
        rig = self.rig()
        with self.assertRaises(QueueChanged) as raised:
            rig.adapter.shuffle_reorder(True, rig.state["group_revision"], rig.state["track_id"],
                                        plan=list(range(8)), expected_rows=["stale"] * 8)
        self.assertEqual(sonos_outcome(raised.exception, "shuffle_reorder"), "queue_changed")
        self.assertEqual(rig.speaker.reorders, [])

    def test_a_song_ending_mid_shuffle_freezes_the_rows_up_to_it_and_the_plan_continues(self):
        rig = self.rig()
        plan = [7, 6, 5, 4, 3, 2, 1, 0]   # reverse: every step moves a row
        at_advance = []

        def song_ends(count, name):
            if name == "GetPositionInfo" and len(rig.speaker.reorders) == 1 and not at_advance:
                rig.play(5)   # three songs "ended" after the first move
                at_advance.append(ids(rig.speaker.items))
        rig.speaker.on_call = song_ends
        self.on(rig, plan)
        frozen = at_advance[0]
        after = rig.speaker.reorders[1:]
        self.assertTrue(all(start >= 6 and before >= 6 for start, _, before in after),
                        "no row at or before the new playing row moves")
        self.assertEqual(ids(rig.speaker.items)[:5], frozen[:5])
        rest = [v for v in [99, 98, 97, 96, 95, 94, 93, 92] if v not in frozen[:5]]
        self.assertEqual(ids(rig.speaker.items)[5:], rest)

    def test_a_jump_elsewhere_stops_with_queue_changed_and_keeps_the_record(self):
        rig = self.rig()

        def jump(count, name):
            if name == "ReorderTracksInQueue" and len(rig.speaker.reorders) == 1:
                rig.play(1)
        rig.speaker.on_call = jump
        with self.assertRaises(QueueChanged):
            self.on(rig, [7, 6, 5, 4, 3, 2, 1, 0])
        self.assertTrue(rig.shuffle.saved["base_rows"], "Shuffle off can still restore")

    def test_verification_includes_the_playing_row(self):
        rig = self.rig()
        rig.speaker.on_call = lambda count, name: rig.speaker.track.update(playlist_position="9") \
            if name == "Browse" and len(rig.speaker.reorders) == 7 else None
        with self.assertRaises(ShuffleFailed):
            self.on(rig, [7, 6, 5, 4, 3, 2, 1, 0])

    def test_off_restores_the_base_order_behind_the_play_next_rows(self):
        rig = self.rig()
        self.on(rig, [0, 1, 5, 2, 7, 3, 6, 4], pn=[0, 1])
        rig.refresh()
        # A newer Play next block while shuffled (ids 5, 6 right after the current song).
        rig.adapter.play_next([song(5), song(6)], rig.state["group_revision"], rig.state["track_id"])
        state = self.off(rig, playnext_song_ids=["5", "6", "92", "93"])
        self.assertEqual(ids(rig.speaker.items), [90, 91, 5, 6, 92, 93, 94, 95, 96, 97, 98, 99])
        self.assertEqual(rig.shuffle.saved, {})
        self.assertFalse(state["companion_shuffle"])

    def test_off_after_songs_played_never_moves_them(self):
        rig = self.rig()
        self.on(rig, [7, 6, 5, 4, 3, 2, 1, 0])
        rig.play(4)                        # rows 3, 4 played meanwhile
        frozen = ids(rig.speaker.items)[:4]
        self.off(rig)
        self.assertEqual(ids(rig.speaker.items)[:4], frozen)
        self.assertEqual(ids(rig.speaker.items)[4:], sorted(set(range(92, 100)) - set(frozen)))

    def test_off_with_a_foreign_row_drops_the_record(self):
        rig = self.rig()
        self.on(rig, [7, 6, 5, 4, 3, 2, 1, 0])
        rig.speaker.items.append(FakeItem(555))
        rig.speaker.revision += 1
        with self.assertRaises(QueueChanged):
            self.off(rig)
        self.assertEqual(rig.shuffle.saved, {})

    # [WP6-r22] The phase-1 review's open edge case: a Play next of a song the shuffle already
    # played has the same fingerprint (row signature) as that played base row, which the record
    # still holds. With the ledger's units (start row 4) off keeps it next, as the controller's
    # preview shows it. Plain ids (K3 section 9.5.3) are attributed record first (phase 1): they
    # cannot tell this row from the played-Play-next twin case below, and the record holds 97.
    def test_off_keeps_a_play_next_of_a_song_the_shuffle_already_played_next(self):
        for units, expected in (([["97", 4]], [90, 91, 97, 97, 92, 93, 94, 95, 96, 98, 99]),
                                (["97"], [90, 91, 97, 92, 93, 94, 95, 96, 97, 98, 99])):
            with self.subTest(units=units):
                rig = self.rig()
                self.on(rig, [5, 0, 1, 2, 3, 4, 6, 7])   # 97 first after the current song
                rig.play(3)                              # the shuffle reached 97 (row 3)
                rig.refresh()
                result = rig.adapter.play_next([song(97)], rig.state["group_revision"], rig.state["track_id"])
                self.assertEqual(result["_inserted"]["start_row"], 4)
                self.assertEqual(row_signature(rig.speaker.items[2]), row_signature(rig.speaker.items[3]),
                                 "the same fingerprint as the played base row")
                self.off(rig, playnext_song_ids=units)
                self.assertEqual(ids(rig.speaker.items), expected)
                self.assertEqual(rig.shuffle.saved, {})

    def test_off_keeps_a_play_next_of_the_same_album_first_after_the_shuffle_played_some(self):
        album = list(range(90, 100))
        for kind in ("units", "plain"):
            with self.subTest(payload=kind):
                rig = self.rig()
                self.on(rig, [5, 3, 0, 7, 1, 6, 2, 4])   # 97, 95, 92, 99, 93, 98, 94, 96
                rig.play(4)                              # 97 and 95 played
                rig.refresh()
                result = rig.adapter.play_next([song(n) for n in album], rig.state["group_revision"],
                                               rig.state["track_id"])
                start = result["_inserted"]["start_row"]
                self.off(rig, playnext_song_ids=[[str(n), start] if kind == "units" else str(n) for n in album])
                if kind == "units":
                    self.assertEqual(ids(rig.speaker.items), [90, 91, 97, 95] + album + [92, 93, 94, 96, 98, 99])
                else:
                    # Record first (phase 1's counts): the record still holds the played 97 and 95, so
                    # those two go back to their base places; of identical rows the earliest stay Play
                    # next, so the album keeps its own order (phase 1 put the base 92, 99, 93 … there).
                    self.assertEqual(ids(rig.speaker.items), [90, 91, 97, 95, 90, 91, 92, 93, 94, 96, 98, 99,
                                                              92, 93, 94, 95, 96, 97, 98, 99])

    def test_off_sorts_a_base_twin_of_a_played_play_next_row_back_to_its_place(self):
        # Play next '95' before the shuffle (row 3); it is played; its base twin (the album's 95)
        # is now the first upcoming row. The ledger's unit (start row 3) proves the played row held
        # it; with a plain id the record holds the twin (phase 1's rule), with the same result.
        for units in ([["95", 3]], ["95"]):
            with self.subTest(units=units):
                rig = self.rig()
                rig.adapter.play_next([song(95)], rig.state["group_revision"], rig.state["track_id"])
                rig.refresh()                            # [90, 91, 95*, 92..99], P = 2
                self.on(rig, [0, 4, 1, 2, 3, 5, 6, 7, 8], pn=[0])   # 95*, then 95, 92, 93, 94, 96..99
                rig.play(3)
                self.off(rig, playnext_song_ids=units)
                self.assertEqual(ids(rig.speaker.items), [90, 91, 95, 92, 93, 94, 95, 96, 97, 98, 99])

    def test_off_with_plain_ids_keeps_a_play_next_block_in_its_order(self):
        # Play next [93, 201] while the album's 93 is still upcoming: record first leaves one 93 to
        # Play next; it is the earliest of the identical rows (the block's), so the block keeps its
        # order. Phase 1 gave the block's 93 to the record and realised [201, 93].
        rig = self.rig()
        self.on(rig, [0, 1, 2, 3, 4, 5, 6, 7][::-1])     # 99 … 92
        rig.refresh()
        rig.adapter.play_next([song(93), song(201)], rig.state["group_revision"], rig.state["track_id"])
        self.off(rig, playnext_song_ids=["93", "201"])
        self.assertEqual(ids(rig.speaker.items), [90, 91, 93, 201, 92, 93, 94, 95, 96, 97, 98, 99])

    def test_off_with_the_ledgers_units_end_to_end(self):
        from control_center.queue_context import QueueLedger, Segment
        ledger = QueueLedger("ROOM", path=Path(__file__).with_name("unused-ledger.json"), autosave=False)
        ledger.record_start(Segment("album", name="Album"), [str(n) for n in self.QUEUE])
        rig = self.rig()
        result = rig.adapter.play_next([song(95)], rig.state["group_revision"], rig.state["track_id"])
        ledger.append_playnext(result["_inserted"]["start_row"], result["_inserted"]["song_ids"])
        rig.refresh()
        self.on(rig, [0, 4, 1, 2, 3, 5, 6, 7, 8], pn=[0])
        rig.play(3)
        self.off(rig, playnext_song_ids=ledger.playnext_units())
        self.assertEqual(ids(rig.speaker.items), [90, 91, 95, 92, 93, 94, 95, 96, 97, 98, 99])
        self.assertFalse(Path(__file__).with_name("unused-ledger.json").exists())

    def test_off_never_refuses_a_row_the_shuffle_kept_as_play_next(self):
        # A base row that the shuffle kept first as Play next (the ledger attributed it so) is not in
        # the record; with its unit already given back by a played row it is still Play next, never
        # foreign.
        rig = self.rig()
        rig.adapter.play_next([song(95)], rig.state["group_revision"], rig.state["track_id"])
        rig.refresh()                                    # [90, 91, 95*, 92, 93, 94, 95, 96..99]
        rig.play(3)                                      # 95* played
        rig.refresh()                                    # upcoming 92, 93, 94, 95, 96..99 (P = 3)
        self.on(rig, [3, 0, 1, 2, 4, 5, 6, 7], pn=[3])   # 95 kept first as Play next
        self.assertNotIn("95", [entry[1] for entry in rig.shuffle.saved["base_rows"]])
        self.off(rig, playnext_song_ids=[["95", 3]])
        self.assertEqual(ids(rig.speaker.items), [90, 91, 95, 95, 92, 93, 94, 96, 97, 98, 99])

    def test_off_play_next_units_still_detect_a_foreign_row(self):
        rig = self.rig()
        self.on(rig, [7, 6, 5, 4, 3, 2, 1, 0])
        rig.speaker.items.insert(2, FakeItem(555))       # another app queued a song next
        rig.speaker.revision += 1
        with self.assertRaises(QueueChanged):
            self.off(rig, playnext_song_ids=[["97", 3], "96"])
        self.assertEqual(rig.shuffle.saved, {})

    def test_the_record_is_per_room_and_loaded_once(self):
        rig = self.rig()
        rig.shuffle.saved = {"room_uid": "OTHER", "base_rows": [["x", "1"]]}
        self.assertEqual(rig.adapter.load_shuffle_record(), {})
        self.assertFalse(rig.refresh()["companion_shuffle"])
        rig.shuffle.saved = {"room_uid": "ROOM", "base_rows": [["x", "1"]]}
        rig.adapter.load_shuffle_record()
        self.assertTrue(rig.refresh()["companion_shuffle"])


def _phase1_restore(items, position, record_rows, playnext_ids):
    """Phase 1's shuffle-off attribution (row by row: the record, then a Play-next id), as the
    ids of the order it realises; None when it refuses (a foreign row). A reference only."""
    order = {}
    for index, entry in enumerate(record_rows):
        order.setdefault(entry[0], []).append(index)
    left, pn, base = list(playnext_ids), [], []
    for item in items[position:]:
        digest, song = row_signature(item), S._song_id(item)
        if order.get(digest):
            base.append((order[digest].pop(0), item))
        elif song in left:
            left.remove(song)
            pn.append(item)
        else:
            return None
    return ids(items[:position]) + ids(pn) + ids([item for _, item in sorted(base, key=lambda pair: pair[0])])


class ShuffleOffPreviewEndToEndTests(unittest.TestCase):
    """[WP6-r22] Controller → runtime → adapter: the Up next restore preview (the controller's
    `upnext_rows` patch with shuffle "off", ranked by the ledger's roles, section 5.6) equals the
    order the adapter realises. The real Controller on a fake clock builds the effect from a
    press, the real Runtime audio dispatch hands it to the real SonosAdapter on the FakeSpeaker,
    with the real QueueLedger; no lanes, threads, windows or network."""

    QUEUE = tuple(range(90, 100))
    PLAYED_BASE_PLAIN = [90, 91, 97, 92, 93, 94, 95, 96, 97, 98, 99]

    @classmethod
    def setUpClass(cls):
        import random
        from types import SimpleNamespace
        from cc5_support import Clock
        from control_center.controller import Controller
        from control_center.queue_context import QueueLedger, Segment
        from control_center.runtime import Runtime
        cls.random, cls.SimpleNamespace, cls.Clock = random, SimpleNamespace, Clock
        cls.Controller, cls.QueueLedger, cls.Segment, cls.Runtime = Controller, QueueLedger, Segment, Runtime

    def start(self, album=QUEUE, position=2):
        ledger = self.QueueLedger("ROOM", path=Path(__file__).with_name("unused-ledger.json"), autosave=False)
        ledger.record_start(self.Segment("album", name="Album"), [str(n) for n in album])
        return Rig(queue=tuple(album), position=position, latency=0.0), ledger

    def play_next(self, rig, ledger, numbers):
        rig.refresh()
        result = rig.adapter.play_next([song(n) for n in numbers], rig.state["group_revision"], rig.state["track_id"])
        ledger.append_playnext(result["_inserted"]["start_row"], result["_inserted"]["song_ids"])

    def upnext(self, rig, ledger, seed=7):
        """A controller in Up next with every row read from the adapter (Tracks → Up next)."""
        c = self.Controller(clock=self.Clock(), rng=self.random.Random(seed))
        c.ledger = ledger
        c.complete(c.request("state"), rig.refresh())
        c.drain()
        c.button(2, c.control_id, False)
        c.drain()
        c.button(1, c.control_id, False)
        while any(e["kind"] == "queue_window" for e in c.pending.values()):
            read = [e for e in c.pending.values() if e["kind"] == "queue_window"][-1]
            c.complete(read["request"], rig.adapter.queue_window(read["start"], min(100, read["count"])))
        for effect in list(c.pending.values()):
            if effect["kind"] == "ratings":
                c.complete(effect["request"], {})
            elif effect["kind"] == "catalog_songs":
                c.complete(effect["request"], {song_id: {"catalog": True} for song_id in effect["ids"]})
        c.drain()
        self.assertEqual(c.screen.mode, "upnext")
        return c

    def shuffle(self, rig, ledger, seed=7, payload=None):
        """Press Shuffle in Up next; run the effect through the runtime's audio dispatch. Returns
        (effect, preview ids or None, realised ids)."""
        c = self.upnext(rig, ledger, seed)
        c.button(1, c.control_id, False)
        effects = c.drain()
        jobs = [e for e in effects if e["kind"] == "shuffle_reorder"]
        self.assertEqual(len(jobs), 1, [e["kind"] for e in effects])
        effect = dict(jobs[0])
        patches = [e for e in effects if e["kind"] == "upnext_rows" and e.get("shuffle") == "off"]
        preview = [int(row["song_id"]) for row in patches[-1]["rows"]] if patches else None
        if payload is not None:
            effect["playnext_song_ids"] = payload(ledger)
        runtime = self.SimpleNamespace(sonos=rig.adapter, _check_epoch=lambda epoch: None,
                                       _post_progress=lambda request, value: None)
        self.Runtime._audio_op(runtime, effect, 0, lambda: None)
        return effect, preview, ids(rig.speaker.items)

    def played_play_next(self):
        """Play next 95 at row 3, shuffle on keeping it first with the album's 95 next, row 3 plays."""
        rig, ledger = self.start()
        self.play_next(rig, ledger, [95])
        rig.refresh()
        rows = rig.speaker.items[2:]
        rig.adapter.shuffle_reorder(True, rig.state["group_revision"], rig.state["track_id"],
                                    plan=[0, 4, 1, 2, 3, 5, 6, 7, 8], playnext_offsets=[0],
                                    expected_rows=[row_signature(x) for x in rows])
        rig.play(3)
        return rig, ledger

    def played_base(self):
        """Shuffle on with 97 first, row 3 (the album's 97) plays, then Play next 97 (row 4)."""
        rig, ledger = self.start()
        rows = rig.speaker.items[2:]
        rig.adapter.shuffle_reorder(True, rig.state["group_revision"], rig.state["track_id"],
                                    plan=[5, 0, 1, 2, 3, 4, 6, 7], expected_rows=[row_signature(x) for x in rows])
        rig.play(3)
        self.play_next(rig, ledger, [97])
        return rig, ledger

    def test_the_preview_is_the_realised_order_in_both_twin_cases(self):
        for case in ("played_play_next", "played_base"):
            for payload in (None, lambda ledger: ledger.playnext_units()):
                with self.subTest(case=case, payload="controller" if payload is None else "units"):
                    rig, ledger = getattr(self, case)()
                    effect, preview, realised = self.shuffle(rig, ledger, payload=payload)
                    self.assertFalse(effect["on"])
                    self.assertEqual(rig.shuffle.saved, {}, "restored: the record is gone")
                    units = any(isinstance(v, (list, tuple)) for v in effect["playnext_song_ids"])
                    if units or case == "played_play_next":
                        self.assertEqual(realised, preview)
                    else:
                        # The controller still sends plain ids (controller.py `playnext_song_ids()`;
                        # WP5 handoff: send `ledger.playnext_units()`). Plain ids follow K3 section
                        # 9.5.3's record-first rule, which cannot see that row 3 was the album's 97.
                        self.assertEqual(realised, self.PLAYED_BASE_PLAIN)
                        self.assertNotEqual(realised, preview)
        self.assertFalse(Path(__file__).with_name("unused-ledger.json").exists())

    def test_random_histories_realise_the_preview_with_the_ledgers_units(self):
        # Random Play next (album twins included), playback and a companion shuffle, then Shuffle
        # off: with units the adapter realises exactly the preview; with plain ids it is never
        # further from the preview than phase 1's rule.
        checked = plain_misses = phase1_misses = 0
        for seed in range(160):
            r = self.random.Random(seed)
            album, first = list(range(90, 90 + r.randint(5, 12))), r.randint(1, 3)
            histories = []
            for payload in (lambda ledger: ledger.playnext_units(), lambda ledger: ledger.playnext_song_ids()):
                rig, ledger = self.start(album, position=first)
                histories.append((rig, ledger, payload))
            steps = [(r.choice(["pn", "pn", "play", "on"]), [r.choice(album + [200, 201]) for _ in range(3)],
                      r.randint(1, 3), r.randint(1, 2)) for _ in range(r.randint(2, 6))]
            outcome = []
            for rig, ledger, payload in histories:
                shuffled = False
                for action, numbers, count, advance in steps:
                    P, T = rig.refresh()["playlist_position"], len(rig.speaker.items)
                    if action == "pn":
                        self.play_next(rig, ledger, numbers[:count])
                    elif action == "play" and P < T - 2:
                        rig.play(P + min(advance, T - P - 2))
                    elif action == "on" and not shuffled and T - P >= 3:
                        c = self.upnext(rig, ledger, seed)
                        c.button(1, c.control_id, False)
                        jobs = [e for e in c.drain() if e["kind"] == "shuffle_reorder"]
                        if jobs and jobs[0]["on"]:
                            self.Runtime._audio_op(self.SimpleNamespace(
                                sonos=rig.adapter, _check_epoch=lambda epoch: None,
                                _post_progress=lambda request, value: None), jobs[0], 0, lambda: None)
                            shuffled = True
                if not shuffled:
                    break
                position = rig.refresh()["playlist_position"]
                phase1 = _phase1_restore(rig.speaker.items, position, rig.shuffle.saved["base_rows"],
                                         ledger.playnext_song_ids())
                effect, preview, realised = self.shuffle(rig, ledger, seed, payload=payload)
                outcome.append((preview, realised, phase1))
            if len(outcome) != 2:
                continue
            checked += 1
            (preview, realised, _), (plain_preview, plain, phase1) = outcome
            with self.subTest(seed=seed):
                self.assertEqual(realised, preview, "units: the realised order is the preview")
                self.assertEqual(plain_preview, preview)
                if plain != preview:
                    self.assertNotEqual(phase1, preview, "plain ids: never worse than phase 1")
            plain_misses += plain != plain_preview
            phase1_misses += phase1 != plain_preview
        self.assertGreater(checked, 80)
        self.assertLess(plain_misses, phase1_misses)


class NativeShuffleTests(unittest.TestCase):
    def test_play_mode_mapping_and_read_back(self):
        for mode, on, off in (("NORMAL", "SHUFFLE_NOREPEAT", "NORMAL"), ("REPEAT_ALL", "SHUFFLE", "REPEAT_ALL"),
                              ("REPEAT_ONE", "SHUFFLE_REPEAT_ONE", "REPEAT_ONE")):
            with self.subTest(mode=mode):
                rig = Rig(play_mode=mode)
                self.assertEqual(rig.adapter.set_shuffle(True, rig.state["group_revision"])["play_mode"], on)
                self.assertEqual(rig.adapter.set_shuffle(False, rig.state["group_revision"])["play_mode"], off)
                self.assertEqual(rig.speaker.play_modes, [on, off])
        rig = Rig(play_mode="SHUFFLE")
        rig.adapter.set_shuffle(True, rig.state["group_revision"])
        self.assertEqual(rig.speaker.play_modes, [], "already on: nothing sent")

    def test_712_and_an_unconfirmed_mode_are_failed(self):
        rig = Rig(play_mode_error=UPnPError(712))
        with self.assertRaises(ShuffleFailed) as raised:
            rig.adapter.set_shuffle(True, rig.state["group_revision"])
        self.assertEqual(sonos_outcome(raised.exception, "set_shuffle"), "failed")
        rig = Rig(play_mode_sticks=False)
        start = rig.clock.now()
        with self.assertRaises(ShuffleFailed):
            rig.adapter.set_shuffle(True, rig.state["group_revision"])
        self.assertAlmostEqual(rig.clock.now() - start, 2.0, delta=0.2)
        self.assertEqual(rig.speaker.play_modes, ["SHUFFLE_NOREPEAT"], "never resent")


# ---------------------------------------------------------------------------------- 9.6
class QueueReadAndMoveTests(unittest.TestCase):
    def test_queue_window_rows(self):
        rig = Rig(queue=(90, 91, 92, 93), position=2)
        rig.speaker.items.append(FakeItem(0))
        rig.speaker.items[-1].resources[0].uri = "x-sonosapi-radio:station"
        window = rig.adapter.queue_window(1, 21)
        self.assertEqual((window["start"], window["total"], window["update_id"]), (1, 5, "10"))
        first = window["rows"][0]
        self.assertEqual({key: first[key] for key in ("row", "title", "artist", "album", "song_id", "duration_s",
                                                      "service")},
                         {"row": 2, "title": "Song 91", "artist": "Artist", "album": "Album", "song_id": "91",
                          "duration_s": 210, "service": "apple"})
        self.assertTrue(first["sonos_art"].startswith("http://192.168.1.50:1400/getaa?"))
        self.assertEqual(first["signature"], row_signature(rig.speaker.items[1]))
        self.assertEqual((window["rows"][-1]["song_id"], window["rows"][-1]["service"]), (None, "other"))
        with self.assertRaises(SonosError):
            rig.adapter.queue_window(0, 101)

    def test_jump_guards_seeks_the_row_and_plays(self):
        rig = Rig(queue=(90, 91, 92), position=1, transport_state="PAUSED_PLAYBACK")
        rig.speaker.avTransport.Play = lambda *a, **k: setattr(rig.speaker, "transport_state", "PLAYING")
        with self.assertRaises(QueueChanged):
            rig.adapter.jump(3, rig.state["group_revision"], rig.state["track_id"], "stale")
        self.assertEqual(rig.speaker.seeks, [])
        result = rig.adapter.jump(3, rig.state["group_revision"], rig.state["track_id"],
                                  rig.state["queue_revision"], name="Song 92")
        self.assertEqual(rig.speaker.seeks, [3])
        self.assertEqual(result["playback"], "PLAYING")
        self.assertEqual(result["_start"], {"k": 1, "n": 1, "u": 0, "name": "Song 92", "row": 3})
        rig.speaker.track["title"] = "changed"
        with self.assertRaises(TrackChanged):
            rig.adapter.jump(1, rig.state["group_revision"], rig.state["track_id"], rig.state["queue_revision"])

    def test_move_next_moves_an_upcoming_row_to_p_plus_1(self):
        rig = Rig(queue=(90, 91, 92, 93, 94, 95), position=2)
        rig.adapter.move_next(6, rig.state["group_revision"], rig.state["queue_revision"])
        self.assertEqual(rig.speaker.reorders, [(6, 1, 3)])
        self.assertEqual(ids(rig.speaker.items), [90, 91, 95, 92, 93, 94])
        rig.refresh()
        rig.adapter.move_next(3, rig.state["group_revision"], rig.state["queue_revision"])
        self.assertEqual(len(rig.speaker.reorders), 1, "P+1 needs no change")

    def test_move_next_reinserts_a_played_row_from_its_catalog_link(self):
        rig = Rig(queue=(90, 91, 92, 93), position=3)
        result = rig.adapter.move_next(1, rig.state["group_revision"], rig.state["queue_revision"], item=song(90))
        self.assertEqual(ids(rig.speaker.items), [90, 91, 92, 90, 93])
        self.assertEqual(result["_inserted"], {"start_row": 4, "song_ids": ["90"]})
        rig.refresh()
        with self.assertRaises(SonosError):
            rig.adapter.move_next(1, rig.state["group_revision"], rig.state["queue_revision"], item=None)

    def test_move_next_guards(self):
        rig = Rig(queue=(90, 91, 92, 93), position=2)
        with self.assertRaises(QueueChanged):
            rig.adapter.move_next(4, rig.state["group_revision"], "stale")
        with self.assertRaises(NotQueueSource) as raised:
            Rig(media_uri="x-rincon-stream:R").adapter.move_next(2, rig.state["group_revision"], None)
        self.assertEqual(sonos_outcome(raised.exception, "move_next"), "not_queue_source")
        shuffled = Rig(queue=(90, 91, 92), play_mode="SHUFFLE")
        with self.assertRaises(SonosShuffleOn):
            shuffled.adapter.move_next(3, shuffled.state["group_revision"], None)
        self.assertEqual(rig.speaker.reorders, [])


class JumpConfirmationTests(unittest.TestCase):
    """[WP6-r22] Up next Play (section 9.6.2) is confirmed by the seek rule ([r2.2] C5-68):
    the first PLAYING read at the row after TRANSITIONING (or from 1.0 s after the Seek reply),
    within 8 s, in 100 ms polls that are steps of their own (section 1.1)."""

    def rig(self, transition_s=None, then="PLAYING", latency=0.05, transport_state="PLAYING"):
        rig = Rig(queue=(90, 91, 92, 93), position=1, latency=latency, transport_state=transport_state)
        speaker, rig.sent, rig.plays = rig.speaker, [], []
        seek = speaker.seek_action

        def track_nr(args, **kwargs):
            seek(args, **kwargs)                        # the row reads the target at once
            rig.sent.append(rig.clock.now())
            if transition_s is not None:                # then TRANSITIONING, then `then`
                speaker.seek_script = {"then": then}
                speaker._seek_until = rig.clock.now() + transition_s

        def play(args, **kwargs):
            speaker.tick("Play")
            rig.plays.append(rig.clock.now())
            if speaker._seek_until is None:
                speaker.transport_state = "PLAYING"
        speaker.avTransport.Seek, speaker.avTransport.Play = track_nr, play
        return rig

    def jump(self, rig, row=3, **kwargs):
        return rig.adapter.jump(row, rig.state["group_revision"], rig.state["track_id"],
                                rig.state["queue_revision"], name=f"Song {89 + row}", **kwargs)

    def test_a_transition_as_long_as_the_live_seeks_is_ok(self):
        # Live check W2: a Seek stayed TRANSITIONING 2.64-2.69 s; the 2 s read-back failed these.
        for transition in (0.5, 2.0, 2.3, 2.65, 2.7, 6.0, 7.8):
            with self.subTest(transition_s=transition):
                rig = self.rig(transition, latency=0.0)
                result = self.jump(rig)
                self.assertEqual(result["_start"], {"k": 1, "n": 1, "u": 0, "name": "Song 92", "row": 3})
                self.assertEqual((result["playback"], result["playlist_position"]), ("PLAYING", 3))
                elapsed = rig.clock.now() - rig.sent[0]
                self.assertGreaterEqual(elapsed, transition)
                self.assertLess(elapsed, transition + 0.1 + 1e-6, "the first PLAYING read after TRANSITIONING")
                self.assertEqual(rig.speaker.seeks, [3], "one Seek, never resent")
        rig = self.rig(2.65)                            # with 50 ms calls, as the live gates
        self.assertEqual(self.jump(rig)["_start"]["row"], 3)

    def test_without_transitioning_playing_counts_only_from_1_s_after_the_seek(self):
        rig = self.rig(latency=0.0)                     # PLAYING at row 3 from the first read
        self.jump(rig)
        elapsed = rig.clock.now() - rig.sent[0]
        self.assertGreaterEqual(elapsed, 1.0)
        self.assertLess(elapsed, 1.1 + 1e-6)
        self.assertEqual(rig.plays, [], "already PLAYING: no Play")
        rig = self.rig(transport_state="PAUSED_PLAYBACK", latency=0.0)
        self.jump(rig)
        self.assertEqual(len(rig.plays), 1, "one Play when not PLAYING")
        self.assertGreaterEqual(rig.clock.now() - rig.sent[0], 1.0)

    def test_a_row_that_does_not_play_within_8_s_is_start_failed(self):
        def skipped(rig):
            # The speaker skipped the row (an unplayable song): it resumes PLAYING at the next row.
            rig.speaker.on_call = lambda count, name: rig.speaker.track.update(playlist_position="4") \
                if name == "GetTransportInfo" and rig.sent and rig.clock.now() - rig.sent[0] > 0.5 else None
        for label, transition, then, arrange in (("stopped", 1.0, "STOPPED", None),
                                                 ("never resumes", float("inf"), "PLAYING", None),
                                                 ("after the window", 9.0, "PLAYING", None),
                                                 ("another row", 1.0, "PLAYING", skipped)):
            with self.subTest(label):
                rig = self.rig(transition, then)
                if arrange:
                    arrange(rig)
                with self.assertRaises(SonosError) as raised:
                    self.jump(rig)
                self.assertEqual(sonos_outcome(raised.exception, "jump"), "start_failed")
                self.assertEqual(str(raised.exception), "Play was not confirmed.")
                elapsed = rig.clock.now() - rig.sent[0]
                self.assertGreaterEqual(elapsed, S.SEEK_CONFIRM_S - 1e-6)
                self.assertLess(elapsed, S.SEEK_CONFIRM_S + 0.25)
                self.assertEqual(rig.speaker.seeks, [3])

    def test_the_polls_are_steps_with_the_lock_released(self):
        rig = self.rig(2.65)
        seen, reads = [], []

        def between():
            seen.append(rig.lock_free())
            reads.append(rig.speaker.calls.count("GetTransportInfo"))
        self.jump(rig, between_steps=between)
        self.assertGreater(len(seen), 20)
        self.assertTrue(all(seen), "no step runs with the adapter lock held")
        self.assertTrue(all(b - a <= 1 for a, b in zip(reads, reads[1:])), "at most one poll per step")

    def test_the_group_is_checked_while_confirming(self):
        rig = self.rig(2.65)
        before = rig.zone_reads
        self.jump(rig)
        self.assertIn(rig.zone_reads - before, range(6, 11), "every 500 ms and before the result")
        rig = self.rig(2.65)

        def regroup(count, name):
            if name == "GetTransportInfo" and rig.sent and rig.clock.now() - rig.sent[0] > 0.8:
                rig.speaker.group.uid = "OTHER"
        rig.speaker.on_call = regroup
        with self.assertRaises(GroupChanged) as raised:
            self.jump(rig)
        self.assertEqual(sonos_outcome(raised.exception, "jump"), "group_changed")
        self.assertLess(rig.clock.now() - rig.sent[0], 1.6)


class OutcomeTests(unittest.TestCase):
    def test_section_9_10_mapping(self):
        cases = [(GroupChanged("x"), "play_next", "group_changed"), (GroupChanged("x"), "seek", "group_changed"),
                 (S.SonosUnavailable("x"), "volume", "sonos_unavailable"),
                 (S.QueueFull("x"), "play_next", "nothing_added"),
                 (PlayNextFailed("x", outcome="partial"), "play_next", "partial"),
                 (QueueChanged("x"), "shuffle_reorder", "queue_changed"),
                 (TrackChanged("x"), "shuffle_reorder", "failed"),
                 (SeekUnavailable("x"), "seek", "not_confirmed"),
                 (S.StartTimeout("x"), "play_items", "start_failed"),
                 (QueueReplacementFailed("x", partial=True), "play_items", "start_failed"),
                 (QueueChanged("x"), "jump", "start_failed"),
                 (SonosError("x"), "transport", "failed")]
        for error, op, outcome in cases:
            with self.subTest(error=type(error).__name__, op=op):
                self.assertEqual(sonos_outcome(error, op), outcome)


if __name__ == "__main__":
    unittest.main()
