"""K3 sections 5.4-5.5: Tracks (neighbour lines, skips, end refusals) and Seek (mapping, debounce,
landing, the one follow-up jump, exits; a start drops a waiting follow-up) (C5-15, C5-16, C5-19, C5-25,
C5-47, C5-51, C5-65, C5-68, C5-77)."""
import unittest

from cc5_support import Fixture, fail, queue_state, rows, window_result


class TracksLineTests(Fixture):
    def enter(self, **state):
        if state:
            self.publish(queue_state(**state))
        self.press(2)
        effects = self.effects()
        reads = [e for e in effects if e["kind"] == "queue_window"]
        for read in reads:
            P, T = self.c._position()
            self.c.complete(read["request"], window_result(read["start"], read["count"], T))
        return reads

    def test_neighbour_read_on_entry_never_in_the_poll(self):
        reads = self.enter()
        self.assertEqual([(r["start"], r["count"], r["purpose"]) for r in reads], [(3, 3, "tracks")])
        self.publish(queue_state())
        self.assertFalse(self.effects("queue_window"), "cached per (queue_revision, P)")
        self.publish(queue_state(P=6, track_id="track-6"))
        self.assertEqual(self.one("queue_window")["start"], 4)

    def test_lines_per_index(self):
        self.enter()
        frame = self.frame()
        self.assertEqual((frame["heading"], frame["title"], frame["subtitle"], frame["meta"]),
                         ("TRACKS", "Turn to choose", "Now: Cloudbusting", "5 / 12"))
        self.turn_to(2)
        frame = self.frame()
        self.assertEqual((frame["title"], frame["subtitle"], frame["meta"]), ("Next track", "Next: Song 6", "Press 4 to skip"))
        self.turn_to(0)
        self.assertEqual(self.frame()["subtitle"], "Prev: Song 4")

    def test_shuffle_lines(self):
        self.enter(shuffle=True, play_mode="SHUFFLE_NOREPEAT")
        self.turn_to(2)
        self.assertEqual(self.frame()["subtitle"], "Next: shuffle pick")
        self.turn_to(0)
        self.assertEqual(self.frame()["subtitle"], "Prev: last played")
        self.turn_to(1)
        self.assertEqual(self.frame()["meta"], "5 / 12 · shuffle")

    def test_companion_shuffle_shows_the_real_neighbour(self):
        self.enter(companion_shuffle=True)
        self.turn_to(2)
        self.assertEqual(self.frame()["subtitle"], "Next: Song 6")
        self.turn_to(1)
        self.assertEqual(self.frame()["meta"], "5 / 12 · shuffle")

    def test_ends_and_repeat_all(self):
        self.enter(P=12, T=12, can_next=False)
        self.turn_to(2)
        self.assertEqual(self.frame()["subtitle"], "End of queue")
        self.press(0)
        self.enter(P=12, T=12, repeat="all", play_mode="REPEAT_ALL")
        self.turn_to(2)
        self.assertEqual(self.frame()["subtitle"], "Next: back to track 1")
        self.press(0)
        reads = self.enter(P=1, T=12, repeat="all", play_mode="REPEAT_ALL", track_id="track-1")
        self.assertIn((11, 1, "tracks_last"), [(r["start"], r["count"], r["purpose"]) for r in reads])
        self.turn_to(0)
        self.assertEqual(self.frame()["subtitle"], "Prev: Song 12")

    def test_non_queue_sources_show_now_at_every_index(self):
        self.enter(source="radio", queue_length=0, playlist_position=0)
        for index in (0, 1, 2):
            self.turn_to(index)
            self.assertEqual(self.frame()["subtitle"], "Now: Cloudbusting")
        self.turn_to(1)
        self.assertEqual(self.frame()["meta"], "")

    def test_transport_ring_unavailable_bits(self):
        self.enter(can_previous=False)
        self.assertEqual(self.frame()["ring"], {"style": "transport", "value": 0, "index": 1, "count": 3,
                                               "unavailable": 1})


class SkipTests(Fixture):
    def test_end_refusal_without_toast(self):
        self.publish(queue_state(P=12, T=12))
        self.tracks(2)
        self.press(3)
        self.assertEqual(self.transient(), "End of queue")
        self.assertAlmostEqual(self.c.transient.until - self.clock(), 1.5)
        self.assertEqual(self.c.feedback["kind"], "err")
        self.assertFalse(self.effects("toast"))
        self.publish(queue_state(P=1, T=12))
        self.turn_to(0)
        self.press(3)
        self.assertEqual(self.transient(), "Start of queue")

    def test_skip_ok_sweeps_toasts_and_recentres(self):
        self.tracks(2)
        self.press(3)
        transport = self.one("transport")
        self.assertEqual((transport["direction"], transport["index"]), ("next", 2))
        self.assertEqual(self.frame()["meta"], "Skipping…")
        self.assertEqual(self.frame()["activity"], "pending")
        self.c.complete(transport["request"], queue_state(P=6, title="Under Ice", track_id="track-6"))
        self.assertEqual(self.c.screen.index, 1)
        self.assertEqual(self.c.feedback, {"kind": "ok", "seq": self.c.feedback_seq, "skip": 1})
        self.assertEqual([t["text"] for t in self.effects("toast")], ["Next · Under Ice"])

    def test_previous_under_shuffle_is_sent(self):
        self.publish(queue_state(shuffle=True, play_mode="SHUFFLE"))
        self.tracks(0)
        self.press(3)
        self.assertEqual(self.one("transport")["direction"], "previous")

    def test_skip_failure_shakes_and_keeps_the_notice(self):
        self.tracks(2)
        self.press(3)
        self.complete("transport", error=fail("Sonos refused"))
        self.assertEqual(self.c.feedback["kind"], "err")
        self.assertEqual(self.c.notice, "Sonos refused")


class SeekMappingTests(Fixture):
    initial = queue_state(position_s=74, duration_s=210, playback="PAUSED_PLAYBACK", can_play=True, can_pause=False)

    def test_example_from_a04(self):
        self.seek()
        seek = self.c.screen.seek
        self.assertEqual((seek.n0, seek.max, seek.D), (15, 42, 210))
        self.assertEqual((seek.t(0), seek.t(15), seek.t(42)), (0, 74, 207))
        self.assertEqual(self.c.bounds(), (0, 42, 15))
        self.assertEqual(self.c.control()["profile"], "BINARIS BEER")
        frame = self.frame()
        self.assertEqual((frame["layout"], frame["heading"], frame["title"], frame["meta"]),
                         ("seek", "SEEK", "Cloudbusting", "of 3:30"))
        self.assertEqual(frame["ring"], {"style": "lap", "value": 0, "index": 74, "count": 210})

    def test_longest_offer(self):
        self.publish(queue_state(duration_s=59999, position_s=0, playback="PAUSED_PLAYBACK"))
        self.seek()
        self.assertLessEqual(self.c.screen.seek.max, 12001)
        self.turn_to(self.c.screen.seek.max)
        self.assertEqual(self.frame()["ring"]["index"], 59996)

    def test_playing_extrapolates_the_position(self):
        self.publish(queue_state(position_s=74, duration_s=210, playback="PLAYING"))
        self.tick(6.0)
        self.seek()
        self.assertEqual(self.c.screen.seek.p0, 80)


class SeekSendTests(Fixture):
    initial = queue_state(position_s=74, duration_s=210)

    def test_debounce_and_latest_wins(self):
        self.seek()
        self.turn_to(20)
        self.tick(0.2)
        self.turn_to(22)
        self.tick(0.2)
        self.assertFalse(self.effects("seek"))
        self.tick(0.06)
        seek = self.one("seek")
        self.assertEqual(seek["target_s"], 74 + 35)

    def test_frozen_clock_jumping_and_comet_until_landed(self):
        self.seek()
        self.turn_to(20)
        self.tick(0.3)
        seek = self.one("seek")
        for _ in range(26):                  # 2.6 s of polls reading the target while TRANSITIONING
            self.tick(0.1)
            self.publish(queue_state(position_s=99, playback="TRANSITIONING"))
            frame = self.frame()
            self.assertEqual((frame["meta"], frame["activity"], frame["ring"]["index"]), ("Jumping…", "pending", 99))
        self.c.complete(seek["request"], {**queue_state(position_s=99), "_applied_seek": 99})
        frame = self.frame()
        self.assertEqual((frame["meta"], frame["activity"]), ("of 3:30", "idle"))
        self.assertEqual(self.c.feedback, None, "silent success")

    def test_one_follow_up_jump_after_landing(self):
        self.seek()
        self.turn_to(20)
        self.tick(0.3)
        first = self.one("seek")
        for position in (21, 22, 23, 24):   # turns during the jump move the frozen target
            self.tick(0.1)
            self.turn_to(position)
            self.assertEqual(self.frame()["ring"]["index"], self.c.screen.seek.t(position))
        self.tick(1.0)
        self.assertFalse(self.effects("seek"), "never two in flight")
        self.c.complete(first["request"], {**queue_state(), "_applied_seek": 99})
        frame = self.frame()
        self.assertEqual((frame["meta"], frame["activity"]), ("Jumping…", "pending"), "no gap between the jumps")
        self.tick(0.0)
        follow = self.one("seek")
        self.assertEqual(follow["target_s"], self.c.screen.seek.t(24))
        self.tick(5.0)
        self.assertEqual(self.c.screen.mode, "seek", "the idle exit waits while a jump is out")
        self.c.complete(follow["request"], {**queue_state(), "_applied_seek": follow["target_s"]})
        self.assertEqual(self.frame()["meta"], "of 3:30")
        self.tick(2.9)
        self.assertEqual(self.c.screen.mode, "seek", "the 3 s count starts at the last landing")
        self.tick(0.2)
        self.assertEqual(self.c.screen.mode, "tracks")

    def land_on_the_newest(self, back_during_the_jump):
        """WP5-R3: turn +1 (sent), +1 again before the job starts (the job reads the newer
        target), then back to the first value, during the jump or after it landed."""
        self.seek()
        n0 = self.c.screen.index
        self.turn_to(n0 + 1)
        self.tick(0.3)
        first = self.one("seek")
        sent = first["target_s"]
        self.turn_to(n0 + 2)
        newer = self.c.screen.seek.target_s
        self.assertNotEqual(newer, sent)
        self.assertEqual(self.c.seek_target(first), newer, "a job still queued reads the newest target")
        if back_during_the_jump:
            self.tick(0.1)
            self.turn_to(n0 + 1)
        self.c.complete(first["request"], {**queue_state(position_s=newer), "_applied_seek": newer})
        if back_during_the_jump:
            frame = self.frame()
            self.assertEqual((frame["meta"], frame["activity"]), ("Jumping…", "pending"),
                             "the speaker is at the newer target: a follow-up waits")
        else:
            self.assertEqual(self.frame()["meta"], "of 3:30", "landed on the target the knob shows")
            self.tick(0.5)
            self.turn_to(n0 + 1)
        self.assertEqual(self.frame()["ring"]["index"], sent)
        self.tick(0.3)
        seeks = self.effects("seek")
        self.assertEqual([s["target_s"] for s in seeks], [sent], "exactly one follow-up, to the knob's target")
        self.assertEqual(self.c.seek_target(seeks[0]), sent)
        self.c.complete(seeks[0]["request"], {**queue_state(position_s=sent), "_applied_seek": sent})
        self.tick(0.5)
        self.assertFalse(self.effects("seek"))
        frame = self.frame()
        self.assertEqual((frame["meta"], frame["activity"], frame["ring"]["index"]), ("of 3:30", "idle", sent))
        self.tick(2.6)
        self.assertEqual(self.c.screen.mode, "tracks", "the idle exit counts from the last landing")

    def test_turning_back_to_the_sent_target_during_the_jump_is_sent(self):
        self.land_on_the_newest(back_during_the_jump=True)

    def test_turning_back_to_the_sent_target_after_the_landing_is_sent(self):
        self.land_on_the_newest(back_during_the_jump=False)

    def test_follow_up_waits_250_ms_after_the_last_detent(self):
        self.seek()
        self.turn_to(20)
        self.tick(0.3)
        first = self.one("seek")
        self.tick(0.5)
        self.turn_to(25)
        self.c.complete(first["request"], {**queue_state(), "_applied_seek": 99})
        self.tick(0.1)
        self.assertFalse(self.effects("seek"))
        self.tick(0.2)
        self.assertEqual(len(self.effects("seek")), 1)

    def test_failure_line_2200_and_the_follow_up_is_dropped(self):
        self.seek()
        self.turn_to(20)
        self.tick(0.3)
        first = self.one("seek")
        self.turn_to(24)
        self.c.complete(first["request"], error=fail("not confirmed", outcome="not_confirmed"))
        frame = self.frame()
        self.assertEqual((frame["meta"], frame["metaTone"], frame["activity"]), ("Didn’t jump · try again", "error", "idle"))
        self.assertEqual(self.c.feedback["kind"], "err")
        self.assertEqual(self.c.screen.mode, "seek")
        self.tick(1.0)
        self.assertFalse(self.effects("seek"))
        self.tick(1.3)
        self.assertEqual(self.frame()["meta"], "of 3:30")

    def test_limit_line_1500(self):
        self.seek()
        self.turn_to(self.c.screen.seek.max)
        self.c.drain()
        self.c.limit(1, self.c.control_id)
        self.assertEqual(self.frame()["meta"], "Stops 3 s before end")
        self.tick(1.6)
        self.assertEqual(self.frame()["meta"], "Jumping…" if self.c.screen.seek.busy else "of 3:30")

    def test_limit_rearms_the_idle_exit(self):
        self.seek()
        self.tick(2.5)
        self.c.limit(-1, self.c.control_id)
        self.tick(2.5)
        self.assertEqual(self.c.screen.mode, "seek")


class SeekExitTests(Fixture):
    initial = queue_state(position_s=74, duration_s=210)

    def test_explicit_exits_flush_the_pending_target(self):
        for exit_press in ("back", "seek", "upnext", "hold"):
            with self.subTest(exit=exit_press):
                self.seek()
                self.turn_to(20)
                if exit_press == "back":
                    self.press(0)
                elif exit_press == "seek":
                    self.press(2)
                elif exit_press == "upnext":
                    self.press(1)
                else:
                    self.hold()
                seeks = [e for e in self.c.pending.values() if e["kind"] == "seek"]
                self.assertEqual([s["target_s"] for s in seeks], [99])
                self.c.complete(seeks[0]["request"], {**queue_state(), "_applied_seek": 99})
                self.assertIsNone(self.c.feedback, "a result after Seek was left is silent")
                self.c.screen.mode = "home"
                self.c.drain()

    def test_exit_while_in_flight_keeps_one_follow_up(self):
        self.seek()
        self.turn_to(20)
        self.tick(0.3)
        first = self.one("seek")
        self.turn_to(26)
        self.press(0)
        self.assertEqual(self.c.screen.mode, "tracks")
        self.assertFalse(self.effects("seek"))
        self.c.complete(first["request"], {**queue_state(), "_applied_seek": 99})
        self.tick(0.0)
        self.assertEqual(self.one("seek")["target_s"], 74 + 55)

    def test_track_change_exits_and_drops_the_target(self):
        self.seek()
        self.turn_to(20)
        self.publish(queue_state(P=6, track_id="track-6"))
        self.assertEqual((self.c.screen.mode, self.c.screen.index), ("tracks", 1))
        self.tick(0.5)
        self.assertFalse(self.effects("seek"))
        self.assertIsNone(self.c.feedback, "no shake")

    def assert_pending_target(self):
        seek = self.c.screen.seek
        self.assertEqual(self.c.screen.mode, "seek")
        self.assertIsNotNone(seek.due)
        self.assertNotEqual(seek.target_s, seek.acked_s)

    def test_group_change_drops_the_target(self):
        self.seek()
        self.turn_to(20)
        self.assert_pending_target()
        self.publish(queue_state(group="group-b"))
        self.tick(0.5)
        self.assertFalse(self.effects("seek"))

    def test_disconnect_drops_the_target(self):
        # WP5-R7: Seek entered from Home (a known mode), a target debouncing, then a disconnect.
        self.seek()
        self.turn_to(18)
        self.assert_pending_target()
        self.c.disconnected()
        self.assertEqual(self.c.screen.mode, "home")
        self.tick(0.5)
        self.assertFalse(self.effects("seek"))
        self.tick(5.0)
        self.assertFalse(self.effects("seek"))

    def test_disconnect_during_a_jump_sends_no_follow_up(self):
        self.seek()
        self.turn_to(20)
        self.tick(0.3)
        first = self.one("seek")
        self.turn_to(26)                     # a follow-up target waits for the landing
        self.c.disconnected()
        self.c.complete(first["request"], {**queue_state(), "_applied_seek": first["target_s"]})
        self.tick(0.5)
        self.assertFalse(self.effects("seek"))
        self.assertIsNone(self.c._seek_bg)

    def test_a_dropped_target_is_not_sent_when_the_job_read_a_newer_one(self):
        # The queued job read the newest turn; the drop (a track change) happens before it lands.
        self.seek()
        self.turn_to(20)
        self.tick(0.3)
        first = self.one("seek")
        self.turn_to(24)
        newer = self.c.seek_target(first)            # the job starts now and reads the newest turn
        self.assertNotEqual(newer, first["target_s"])
        self.publish(queue_state(group="group-b"))   # a group change drops the pending target
        self.c.complete(first["request"], {**queue_state(group="group-b"), "_applied_seek": newer})
        self.tick(0.5)
        self.assertFalse(self.effects("seek"), "never a jump back to the dropped burst's first target")

    def test_a_job_still_queued_at_a_drop_reads_no_newer_target(self):
        self.seek()
        self.turn_to(20)
        self.tick(0.3)
        first = self.one("seek")
        self.turn_to(24)
        self.publish(queue_state(P=6, track_id="track-6"))   # a track change drops it
        self.assertEqual(self.c.seek_target(first), first["target_s"])

    def test_late_failure_after_leaving_shakes(self):
        self.seek()
        self.turn_to(20)
        self.tick(0.3)
        seek = self.one("seek")
        self.press(0)
        self.c.complete(seek["request"], error=fail("x", outcome="not_confirmed"))
        self.assertEqual(self.c.feedback["kind"], "err")


class SeekStartDropsFollowUpTests(Fixture):
    """[P2a] C5-77 (K3 1.1, 5.5.5, 9.6.2): a start sent while a Seek follow-up waits for the in-flight
    jump to land (kept across an explicit exit, C5-68) drops it as a track change does (C5-47): never
    sent, a job still queued reads no newer target, and the in-flight jump still resolves first."""

    initial = queue_state(position_s=74, duration_s=210)

    def leave_with_a_follow_up(self, exit_logical):
        self.seek()
        self.turn_to(20)
        self.tick(0.3)
        first = self.one("seek")
        self.turn_to(26)                                     # the follow-up target waits for the landing
        self.press(exit_logical)
        bg = self.c._seek_bg
        self.assertIsNotNone(bg, "kept across the explicit exit (C5-68)")
        self.assertNotEqual(bg.target_s, bg.acked_s)
        return first

    def recent_start(self):
        self.press(0)                                        # Tracks -> Home
        self.browse()
        self.press(3)                                        # Recent Play: play_items
        return self.one("play_items")

    def explorer_start(self):
        self.press(0)
        self.browse()
        self.press(1)                                        # Recent -> explorer
        self.c.drain()
        self.press(3)                                        # explorer Play: play_items
        start = self.pending("play_items")
        self.assertEqual(start["source"], "explorer")
        self.c.drain()
        return start

    def upnext_jump(self):
        self.assertEqual(self.c.screen.mode, "upnext")
        _P, T = self.c._position()
        while any(e["kind"] == "queue_window" for e in self.c.pending.values()):
            effect = self.pending("queue_window")
            self.c.complete(effect["request"], window_result(effect["start"], effect["count"], T))
        self.ratings()
        self.press(3)                                        # Up next Play: a jump
        return self.one("jump")

    def seeks_after_the_landing(self, first):
        self.c.complete(first["request"], {**queue_state(), "_applied_seek": first["target_s"]})
        sent = []
        for _ in range(6):
            self.tick(0.3)
            sent += [e for e in self.c.drain() if e["kind"] == "seek"]
        return sent

    def test_every_start_drops_the_waiting_follow_up(self):
        for source, exit_logical, start in (("recent", 0, self.recent_start), ("explorer", 0, self.explorer_start),
                                            ("upnext", 1, self.upnext_jump)):
            with self.subTest(source=source):
                self.setUp()
                first = self.leave_with_a_follow_up(exit_logical)
                start()
                self.assertEqual(self.c._busy_code(), "starting")
                bg = self.c._seek_bg
                self.assertTrue(bg.dropped)
                self.assertEqual((bg.due, bg.target_s), (None, first["target_s"]), "back to the acked target")
                self.assertEqual(self.c.seek_target(first), first["target_s"], "a queued job reads no newer one")
                self.assertEqual(self.seeks_after_the_landing(first), [])
                self.assertIsNone(self.c._seek_bg)

    def test_without_a_start_the_follow_up_is_still_sent(self):
        first = self.leave_with_a_follow_up(0)
        self.assertEqual([e["target_s"] for e in self.seeks_after_the_landing(first)], [74 + 55])

    def test_the_in_flight_jump_still_resolves_first(self):
        first = self.leave_with_a_follow_up(0)
        self.recent_start()
        seq = self.c.feedback_seq
        self.c.complete(first["request"], error=fail("x", outcome="not_confirmed"))
        self.assertEqual((self.c.feedback["kind"], self.c.feedback_seq), ("err", seq + 1), "C5-16: still err")
        self.tick(1.0)
        self.assertFalse(self.effects("seek"))
        self.assertIsNone(self.c._seek_bg)

    def test_a_start_with_nothing_waiting_changes_nothing(self):
        self.seek()
        self.turn_to(20)
        self.tick(0.3)
        first = self.one("seek")
        self.press(0)                                        # nothing waits: the jump in flight is the target
        bg = self.c._seek_bg
        self.assertEqual(bg.target_s, bg.acked_s)
        self.recent_start()
        self.assertEqual(self.c.seek_target(first), first["target_s"])
        self.assertEqual(self.seeks_after_the_landing(first), [])


if __name__ == "__main__":
    unittest.main()
