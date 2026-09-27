"""K3 section 5.6: Up next (open gates, windows, roles, ledger contexts, hearts, add-only Like,
the shuffle hybrid, ring wire forms, changes while open, Play) (C5-45, C5-54, C5-61..C5-64, C5-67)."""
from pathlib import Path
import re
import unittest

from cc5_support import Fixture, Harness, fail, queue_state, window_result
from control_center.queue_context import Segment


class OpenTests(Fixture):
    def test_open_gates_per_source(self):
        for source, copy_text in (("airplay", "Up next is in Music app"), ("radio", "Radio · no Up next"),
                                  ("linein", "Line-in · no Up next"), ("none", "Nothing playing")):
            with self.subTest(source=source):
                self.publish(queue_state(source=source))
                self.tracks()
                self.press(1)
                self.assertEqual(self.c.screen.mode, "tracks")
                self.assertEqual(self.transient(), copy_text)
                self.assertFalse(self.effects("upnext_open"))
                self.press(0)
        self.publish(queue_state())

    def test_open_payload_reads_and_loading_frame(self):
        self.tracks(2)
        self.press(1)
        effects = self.effects()
        opened = self.one("upnext_open", effects)
        self.assertEqual((opened["now"], opened["focus"], opened["count"], opened["card"], opened["loading"],
                          opened["rows"], opened["shuffle"], opened["likes_known"]),
                         (4, 4, 12, None, True, [], "off", False))
        read = self.one("queue_window", effects)
        self.assertEqual((read["start"], read["count"]), (0, 21))
        self.assertEqual((self.c.screen.mode, self.c.screen.index, self.c.screen.parent_index), ("upnext", 4, 2))
        frame = self.frame()
        self.assertEqual((frame["layout"], frame["heading"], frame["meta"], frame["activity"]),
                         ("upnext", "UP NEXT", "Loading queue…", "loading"))
        self.assertEqual(frame["ring"]["style"], "off")

    def test_upcoming_rows_read_for_the_shuffle_plan(self):
        self.publish(queue_state(P=5, T=40))
        self.tracks()
        self.press(1)
        read = self.pending("queue_window")
        self.c.complete(read["request"], window_result(read["start"], read["count"], 40))
        second = self.pending("queue_window")
        self.assertEqual((second["start"], second["count"], second["purpose"]), (5, 35, "shuffle"))

    def test_rows_roles_and_frame(self):
        self.upnext()
        frame = self.frame()
        self.assertEqual((frame["title"], frame["subtitle"], frame["meta"], frame["activity"]),
                         ("Song 5", "Artist", "5 / 12 · playing", "idle"))
        ring = frame["ring"]
        self.assertEqual((ring["style"], ring["index"], ring["count"], ring["now"]), ("selection", 4, 12, 4))
        self.assertNotIn("unavailable", ring)
        self.turn_to(6)
        self.assertEqual(self.frame()["meta"], "7 / 12")
        roles = {row["row"]: row["role"] for row in self.c.upnext_view()["rows"]}
        self.assertEqual((roles[4], roles[5], roles[6], roles[7]), ("played", "now", "next", "upcoming"))

    def test_placeholders_are_warm_entries(self):
        self.publish(queue_state(P=5, T=80))
        self.tracks()
        self.press(1)
        read = self.pending("queue_window")
        self.c.complete(read["request"], window_result(read["start"], read["count"], 80))
        self.turn_to(40)
        frame = self.frame()
        self.assertEqual((frame["title"], frame["meta"]), ("", "41 / 80"))
        ring = frame["ring"]
        self.assertEqual(ring["colors"][40 - ring["first"]], 0)
        self.assertEqual(ring["style"], "selection")

    def test_edge_refill(self):
        self.publish(queue_state(P=5, T=80))
        self.tracks()
        self.press(1)
        read = self.pending("queue_window")
        self.c.complete(read["request"], window_result(read["start"], read["count"], 80))
        self.c.drain()
        self.turn_to(18)                    # within 5 rows of the loaded window's edge (row 21)
        refill = self.pending("queue_window")
        self.assertEqual((refill["start"], refill["count"]), (8, 21))


class ContextTests(Fixture):
    def test_foreign_queue(self):
        self.upnext()
        context = self.c.upnext_view()["context"]
        self.assertEqual(context, {"kind": "foreign", "title": "Sonos queue", "sub": "Started in another app · 12 songs"})

    def test_album_and_playlist_contexts(self):
        ids = [str(1000 + n) for n in range(1, 13)]
        self.c.ledger.record_start(Segment(kind="album", name="Hounds of Love", artist="Kate Bush", year=1985), ids)
        self.upnext()
        self.assertEqual(self.c.upnext_view()["context"], {"kind": "album", "title": "Hounds of Love",
                                                           "sub": "Kate Bush · 1985"})
        self.press(0)
        self.c.ledger.record_start(Segment(kind="playlist", name="PAPER LANTERN Ep. 1", favourite=True, count=34,
                                           duration_ms=7_500_000), ids)
        self.press(1)
        read = self.pending("queue_window")
        self.c.complete(read["request"], window_result(read["start"], read["count"], 12))
        self.assertEqual(self.c.upnext_view()["context"]["sub"], "Favourite playlist · 34 songs · 2 h 05 min")

    def test_play_next_rows_are_attributed(self):
        ids = [str(1000 + n) for n in range(1, 11)]
        self.c.ledger.record_start(Segment(kind="album", name="A"), ids)
        self.c.ledger.append_playnext(6, ["1011", "1012"])
        self.publish(queue_state(P=5, T=12))
        self.upnext()
        segments = {row["row"]: row["segment"] for row in self.c.upnext_view()["rows"]}
        self.assertEqual((segments[5], segments[11], segments[12]), ("base", "playnext", "playnext"))


class HeartTests(Fixture):
    def test_hearts_only_from_ratings_and_data_patches_do_not_pop(self):
        self.upnext()
        self.c.drain()
        for effect in list(self.c.pending.values()):
            if effect["kind"] == "catalog_songs":
                self.c.complete(effect["request"], {song: {"catalog": True, "liked": True} for song in effect["ids"]})
        self.assertIsNone(self.c._upnext_focus_row()["liked"], "a catalog batch never sets liked")
        self.ratings(liked={"1005"})
        patches = [e for e in self.c.drain() if e["kind"] == "upnext_rows"]
        self.assertTrue(all(p["reason"] == "data" for p in patches))
        self.assertTrue(self.c._upnext_focus_row()["liked"])

    def test_like_flow_comet_bloom_and_likes_patch(self):
        self.upnext()
        self.ratings()
        self.turn_to(6)
        self.press(2)
        like = self.one("like")
        self.assertEqual((like["song_id"], like["row"]), ("1007", 7))
        self.assertEqual(self.frame()["activity"], "pending")
        self.c.complete(like["request"], {"liked": True})
        self.assertEqual(self.c.feedback["moment"], "like")
        self.assertEqual(self.transient(), "Liked")
        patch = [e for e in self.effects() if e["kind"] == "upnext_rows"][-1]
        self.assertEqual((patch["reason"], patch["rows"]), ("likes", [{"row": 7, "liked": True}]))
        frame = self.frame()
        self.assertEqual((frame["buttons"][2]["label"], frame["buttons"][2].get("lit"), frame["activity"]),
                         ("Liked", "on", "idle"))
        self.assertEqual(self.c.upnext_view()["hints"][2], "Liked")

    def test_add_only_never_emits_an_unlike(self):
        self.upnext()
        self.ratings(liked={"1005"})
        for _ in range(3):
            self.press(2)
        kinds = [e["kind"] for e in self.effects()]
        self.assertNotIn("unlike", kinds)
        self.assertNotIn("like", kinds)
        self.assertNotEqual(self.c.feedback.get("moment"), "unlike")

    def test_save_failure(self):
        self.upnext()
        self.ratings()
        self.turn_to(6)
        self.press(2)
        self.complete("like", error=fail("busy", outcome="rate_limited", status=429))
        self.assertEqual(self.transient(), "Didn’t save · try again")
        self.assertEqual(self.c.transient.tone, "error")
        self.assertAlmostEqual(self.c.transient.until - self.clock(), 2.2)
        self.assertEqual(self.c.feedback["kind"], "err")

    def test_read_back_timeout_then_the_late_check(self):
        self.upnext()
        self.ratings()
        self.turn_to(6)
        self.press(2)
        self.complete("like", error=fail("not confirmed", outcome="failed", late_check=True))
        self.assertEqual(self.transient(), "Didn’t save · try again")
        self.tick(4.9)
        self.assertFalse([e for e in self.c.pending.values() if e.get("purpose") == "late_check"])
        self.tick(0.2)
        late = [e for e in self.c.pending.values() if e.get("purpose") == "late_check"][0]
        self.assertEqual(late["ids"], ["1007"])
        seq = self.c.feedback_seq
        self.c.complete(late["request"], {"1007": 1})
        patch = [e for e in self.effects() if e["kind"] == "upnext_rows"][-1]
        self.assertEqual(patch["reason"], "data")
        self.assertEqual(self.c.feedback_seq, seq, "no moment")

    def test_not_catalog_result(self):
        self.upnext()
        self.ratings()
        self.turn_to(6)
        self.press(2)
        self.complete("like", error=fail("404", outcome="not_catalog", status=404))
        self.assertEqual(self.transient(), "Not an Apple Music song")
        self.assertFalse(self.c._upnext_focus_row()["catalog"])
        self.assertFalse(self.frame()["buttons"][2]["enabled"])

    def test_signin_expired_arms_the_exit_toast_for_back_only(self):
        self.upnext()
        self.ratings()
        self.c.music_signin_expired = True
        self.turn_to(6)
        self.press(2)
        self.assertFalse(self.effects("like"))
        self.assertEqual(self.transient(), "Sign-in expired")
        self.press(0)
        self.tick(0.3)
        self.assertFalse(self.effects("toast"))
        self.tick(0.1)
        self.assertEqual([t["text"] for t in self.effects("toast")], ["Apple Music sign-in expired · open Settings"])


class ShuffleTests(Fixture):
    def test_companion_on_with_the_play_next_block_first(self):
        ids = [str(1000 + n) for n in range(1, 11)]
        self.c.ledger.record_start(Segment(kind="album", name="A"), ids)
        self.c.ledger.append_playnext(6, ["1011", "1012"])
        self.publish(queue_state(P=5, T=12))
        self.upnext()
        self.ratings()
        self.press(1)
        effects = self.effects()
        job = self.one("shuffle_reorder", effects)
        self.assertEqual(job["plan"][:2], [5, 6], "the Play-next block stays directly after the current song")
        self.assertEqual(sorted(job["plan"]), list(range(7)))
        self.assertEqual(job["playnext_offsets"], [5, 6])
        self.assertEqual(job["expected_rows"], [f"sig-{n}" for n in range(6, 13)])
        rows = self.one("upnext_rows", effects)
        self.assertEqual((rows["reason"], rows["shuffle"], rows["focus"]), ("shuffle", "companion", 5))
        self.assertEqual(self.frame()["activity"], "pending")
        self.c.progress(job["request"], {"phase": "accepted"})
        self.assertEqual((self.c.feedback["moment"], self.transient()), ("shuffle", "Shuffle on"))

    def test_seeded_plan_is_deterministic(self):
        self.upnext()
        self.ratings()
        self.press(1)
        plan = self.one("shuffle_reorder")["plan"]
        import random
        expected = list(range(7))
        random.Random(7).shuffle(expected)
        self.assertEqual(plan, expected)

    def test_off_restores_with_play_next_ids(self):
        self.publish(queue_state(companion_shuffle=True))
        self.upnext()
        self.ratings()
        self.c.ledger.append_playnext(6, ["1006"])
        self.press(1)
        job = self.one("shuffle_reorder", self.c.effects[:])
        # [WP6-r22] the ledger's [song_id, start_row] units (queue_context.playnext_units).
        self.assertEqual((job["on"], job["playnext_song_ids"]), (False, [["1006", 6]]))
        rows = [e for e in self.effects() if e["kind"] == "upnext_rows"][-1]
        self.assertEqual(rows["shuffle"], "off")
        self.c.progress(job["request"], {"phase": "accepted"})
        self.assertEqual(self.transient(), "Shuffle off · in order")

    def test_queue_changed_failure(self):
        self.upnext()
        self.ratings()
        self.press(1)
        self.complete("shuffle_reorder", error=fail("changed", outcome="queue_changed"))
        self.assertEqual((self.transient(), self.c.transient.tone), ("Queue changed", "error"))
        self.assertAlmostEqual(self.c.transient.until - self.clock(), 2.4)
        read = self.pending("queue_window")
        self.c.complete(read["request"], window_result(read["start"], read["count"], 12))
        self.assertEqual([e["reason"] for e in self.effects() if e["kind"] == "upnext_rows"][-1], "queue_changed")

    def test_native_regime_card_and_bounds(self):
        self.publish(queue_state(P=5, T=80))
        self.tracks()
        self.press(1)
        read = self.pending("queue_window")
        self.c.complete(read["request"], window_result(read["start"], read["count"], 80))
        self.ratings()
        self.press(1)
        job = self.one("set_shuffle")
        self.assertTrue(job["on"])
        self.c.complete(job["request"], queue_state(P=5, T=80, shuffle=True, play_mode="SHUFFLE_NOREPEAT"))
        self.assertEqual((self.c.feedback["moment"], self.transient()), ("shuffle", "Sonos is shuffling"))
        rows = [e for e in self.effects() if e["kind"] == "upnext_rows"][-1]
        self.assertEqual((rows["reason"], rows["card"], rows["shuffle"]), ("shuffle", {"n": 75}, "sonos"))
        self.tick(0.21)
        self.assertEqual((self.c.bounds()[1], self.c.screen.index), (5, 5))
        ring = self.frame()["ring"]
        self.assertEqual((ring["card"], ring["count"], ring["now"]), (True, 6, 4))
        self.assertEqual(ring["colors"][5 - ring["first"]], 0)

    def test_native_off_rereads_then_reenters(self):
        self.publish(queue_state(shuffle=True, play_mode="SHUFFLE_NOREPEAT"))
        self.upnext()
        self.ratings()
        self.press(1)
        job = self.one("set_shuffle")
        self.assertFalse(job["on"])
        self.c.complete(job["request"], queue_state())
        self.assertEqual(self.transient(), "Shuffle off · in order")
        read = self.pending("queue_window")
        control = self.c.control_id
        self.c.complete(read["request"], window_result(read["start"], read["count"], 12))
        rows = [e for e in self.effects() if e["kind"] == "upnext_rows"][-1]
        self.assertEqual((rows["reason"], rows["shuffle"]), ("shuffle", "off"))
        self.tick(0.21)
        self.assertEqual(self.c.control_id, control + 1)
        self.assertEqual(self.c.bounds()[1], 11)


class ShuffleAfterRereadTests(Fixture):
    """WP5-R5: every re-read after a revision change reads rows P+1..T again when U <= 60 and the
    window does not cover them, so Shuffle never stays dimmed `loading` (section 5.6.5)."""
    initial = queue_state(P=5, T=40)

    def reads(self, revision="rev-1"):
        done = []
        while any(e["kind"] == "queue_window" for e in self.c.pending.values()):
            read = self.pending("queue_window")
            done.append((read["start"], read["count"], read["purpose"]))
            self.c.complete(read["request"], window_result(read["start"], read["count"], 40, revision=revision))
        self.ratings()
        return done

    def shuffle(self):
        return self.frame()["buttons"][1]

    def test_an_external_revision_change_rereads_the_upcoming_rows(self):
        self.upnext()
        self.ratings()
        self.assertTrue(self.shuffle()["enabled"])
        self.publish(queue_state(P=5, T=40, queue_revision="rev-2"))
        self.assertEqual(self.reads("rev-2"), [(0, 21, "requeue"), (5, 35, "shuffle")])
        self.assertTrue(self.shuffle()["enabled"])
        self.c.drain()
        self.press(1)
        self.assertEqual(len(self.effects("shuffle_reorder")), 1)

    def test_a_reread_that_covers_the_upcoming_rows_reads_them_once(self):
        self.publish(queue_state(P=5, T=12))
        self.upnext()
        self.publish(queue_state(P=5, T=12, queue_revision="rev-2"))
        self.assertEqual(self.reads("rev-2"), [(0, 21, "requeue")])

    def test_a_reread_far_down_the_queue_still_reads_the_upcoming_rows(self):
        self.upnext()
        for position in range(5, 31):
            self.turn_to(position)
            self.reads()
        self.publish(queue_state(P=5, T=40, queue_revision="rev-2"))
        done = self.reads("rev-2")
        self.assertEqual(done[0][2], "requeue")
        self.assertIn((5, 35, "shuffle"), done)
        self.assertTrue(self.shuffle()["enabled"])

    def test_no_upcoming_read_in_the_sonos_regime(self):
        self.publish(queue_state(P=5, T=80))
        self.upnext()
        self.publish(queue_state(P=5, T=80, queue_revision="rev-2"))
        self.assertEqual([purpose for _s, _c, purpose in self.reads("rev-2")], ["requeue"])


class ShuffleOnOffOnTests(unittest.TestCase):
    """WP5-R5 end to end on the simulator: 40 rows, P = 5 (U = 35 is more than the window covers)."""

    def boot(self):
        h = Harness(self, album=False)
        h.sonos.load_rows(40, position=5)
        h.run(2)
        h.press(2)
        h.press(1)
        h.run(4)
        self.assertEqual(h.c.screen.mode, "upnext")
        return h

    def settle(self, h):
        for _ in range(3):
            h.clock.advance(0.3)
            h.run(3)

    def test_on_off_on(self):
        h = self.boot()
        self.assertTrue(h.frame()["buttons"][1]["enabled"])
        for on in (True, False, True):
            with self.subTest(on=on):
                h.press(1)
                self.settle(h)
                self.assertEqual(h.sonos.calls[-1], ("shuffle_reorder", on))
                upnext = h.c.screen.upnext
                self.assertTrue(all(row in upnext.rows for row in range(upnext.P + 1, upnext.T + 1)))
                self.assertTrue(h.frame()["buttons"][1]["enabled"])

    def test_an_external_edit_then_shuffle(self):
        h = self.boot()
        with h.sonos._lock:
            queue = h.sonos.queue
            queue[10], queue[11] = queue[11], queue[10]
            h.sonos.update_id += 1
            h.sonos._sync()
        h.clock.advance(1.1)
        self.settle(h)
        self.assertEqual(h.c.screen.upnext.revision, str(h.sonos.update_id))
        self.assertTrue(h.frame()["buttons"][1]["enabled"])
        h.press(1)
        self.settle(h)
        self.assertEqual(h.sonos.calls[-1], ("shuffle_reorder", True))


class ShuffleOffRecordPreviewTests(Fixture):
    """[P3] K3 9.5.3 (the phase-2a review's recommended fix, KD-R1): the Shuffle-off preview ranks the
    base rows by the restore record (their order at Shuffle on) when the controller knows it, from its
    own accepted Shuffle on or from the record the runtime loaded at start; the ledger's start order
    only when it does not (the P2a rule, limitations 2 and 3)."""

    def preview(self):
        rows = [e for e in self.effects() if e["kind"] == "upnext_rows" and e.get("shuffle") == "off"][-1]["rows"]
        return [int(row["song_id"]) - 1000 for row in rows]

    def shuffle_off(self):
        self.publish(queue_state(companion_shuffle=True))
        self.upnext()
        self.ratings()
        self.press(1)
        job = self.one("shuffle_reorder", self.c.effects[:])
        self.assertFalse(job["on"])
        return self.preview()

    def test_a_loaded_record_orders_the_base_rows(self):
        self.c.shuffle_record([f"sig-{n}" for n in (9, 6, 12, 7, 8, 10, 11)])   # the order at Shuffle on
        self.assertEqual(self.shuffle_off(), [1, 2, 3, 4, 5, 9, 6, 12, 7, 8, 10, 11])

    def test_without_a_record_the_ledgers_start_order_is_used(self):
        ids = [str(1000 + n) for n in (1, 2, 3, 4, 5, 12, 11, 10, 9, 8, 7, 6)]
        self.c.ledger.record_start(Segment(kind="album", name="A"), ids)
        self.assertEqual(self.shuffle_off(), [1, 2, 3, 4, 5, 12, 11, 10, 9, 8, 7, 6])

    def test_play_next_rows_stay_first_and_rows_outside_the_record_go_last(self):
        self.c.ledger.record_start(Segment(kind="album", name="A"), [str(1000 + n) for n in range(1, 11)])
        self.c.ledger.append_playnext(6, ["1011"])
        self.c.shuffle_record([f"sig-{n}" for n in (10, 9, 8, 7)])          # 6 and 12 are not in it
        self.assertEqual(self.shuffle_off(), [1, 2, 3, 4, 5, 11, 10, 9, 8, 7, 6, 12])

    def test_a_record_the_state_no_longer_reports_is_forgotten(self):
        self.c.shuffle_record(["sig-9", "sig-6"])
        self.publish(queue_state(companion_shuffle=True))
        self.assertEqual(self.c.shuffle_record_order, ["sig-9", "sig-6"])
        self.publish(queue_state(companion_shuffle=False))
        self.assertIsNone(self.c.shuffle_record_order)
        for bad in (None, [], ["sig-1", None], "sig-1"):
            self.c.shuffle_record(bad)
            self.assertIsNone(self.c.shuffle_record_order)

    def test_our_own_shuffle_on_is_remembered_at_its_acceptance(self):
        self.c.ledger.record_start(Segment(kind="album", name="A"), [str(1000 + n) for n in range(1, 11)])
        self.c.ledger.append_playnext(6, ["1011", "1012"])
        self.upnext()
        self.ratings()
        self.press(1)
        job = self.one("shuffle_reorder")
        self.assertIsNone(self.c.shuffle_record_order, "nothing before the record is persisted")
        self.c.progress(job["request"], {"phase": "accepted"})
        self.assertEqual(self.c.shuffle_record_order, [f"sig-{n}" for n in range(6, 11)], "base rows only")

    def test_a_failure_before_acceptance_remembers_nothing(self):
        self.upnext()
        self.ratings()
        self.press(1)
        self.complete("shuffle_reorder", error=fail("changed", outcome="queue_changed"))
        self.assertIsNone(self.c.shuffle_record_order)

    def test_a_completed_shuffle_off_forgets_the_record(self):
        self.c.shuffle_record([f"sig-{n}" for n in range(6, 13)])
        self.shuffle_off()
        job = self.pending("shuffle_reorder")
        self.c.complete(job["request"], queue_state(queue_revision="rev-2"))
        self.assertIsNone(self.c.shuffle_record_order)


K3 = Path(__file__).resolve().parents[1] / "CONTROL_CENTER_V5.md"


def _unstruck(text):
    """K3 with its struck-through text (``~~...~~``, superseded in place) removed."""
    return re.sub(r"~~.*?~~", "", text)


class ShuffleOffPreviewTextTests(unittest.TestCase):
    """WP5R-1 (the phase-3 review): every K3 place that names the ledger's start order as the Shuffle-off
    preview's rule says it is only the fallback when the controller does not know the record (C5-79),
    and no live text still hands the fix to WP5 and WP6."""

    @classmethod
    def setUpClass(cls):
        cls.text = K3.read_text(encoding="utf-8")
        cls.live = _unstruck(cls.text)

    def row(self, rule):
        rows = [line for line in self.text.splitlines() if line.startswith(f"| **{rule}** |")]
        self.assertEqual(len(rows), 1, rule)
        return rows[0]

    def test_c5_73_strikes_the_handoff_and_names_the_fallback(self):
        row = self.row("C5-73")
        self.assertIn("~~fix handed to WP5 and WP6 (§18)~~", row)
        self.assertNotIn("handed to WP5 and WP6", _unstruck(row))
        live = _unstruck(row)
        self.assertIn("C5-79", live)
        self.assertIn("only the fallback when the controller does not know the record", live)

    def test_the_restore_step_3_note_carries_the_qualifier(self):
        lines = self.text.splitlines()
        at = next(i for i, line in enumerate(lines)
                  if "[P2a] not the ledger's start order, which the controller's preview uses" in line)
        note = " ".join(lines[at + 1:at + 3])
        self.assertIn("[P3]", note)
        self.assertIn("only when the controller does not know the record", note)
        self.assertIn("C5-79", note)

    def test_the_limitations_lead_in_carries_the_qualifier(self):
        lead = next(line for line in self.text.splitlines() if line.startswith("**[P2a] Limitations**"))
        head, _, _ = lead.partition("They differ in three cases")
        self.assertIn("**ledger's start order**", head)
        self.assertIn("only when the controller does not know the record (C5-79", head)

    def test_no_live_text_in_9_5_3_hands_the_preview_fix_to_wp5_and_wp6(self):
        section = self.live[self.live.index("**9.5.3 "):self.live.index("**9.5.4 ")]
        self.assertNotIn("handed to WP5 and WP6", section)


class ShuffleOffRecordEndToEndTests(unittest.TestCase):
    """[P3] Controller → runtime → the real SonosAdapter on the FakeSpeaker (the KD-R1 histories of
    tests\\test_kdocs_contract.py): with the record known, the preview IS the realised order in the
    three cases where the ledger's start order is not (a move_next of an upcoming row, a reorder in
    another Sonos app, a queue the companion did not start), in session and after a restart."""

    @classmethod
    def setUpClass(cls):
        import test_cc_sonos_v7 as sonos_v7
        cls.v7 = sonos_v7
        cls.e2e = sonos_v7.ShuffleOffPreviewEndToEndTests("test_the_preview_is_the_realised_order_in_both_twin_cases")
        cls.e2e.setUpClass()

    @staticmethod
    def runtime_for(rig, controller):
        from types import SimpleNamespace
        return SimpleNamespace(sonos=rig.adapter, _check_epoch=lambda epoch: None,
                               _post_progress=lambda request, value: controller.progress(request, value))

    def settle(self, c, rig):
        for _ in range(6):
            c.clock.advance(0.25)
            c.tick()
            for effect in list(c.pending.values()):
                if effect["kind"] == "queue_window":
                    c.complete(effect["request"], rig.adapter.queue_window(effect["start"], min(100, effect["count"])))
                elif effect["kind"] == "ratings":
                    c.complete(effect["request"], {})
                elif effect["kind"] == "catalog_songs":
                    c.complete(effect["request"], {song_id: {"catalog": True} for song_id in effect["ids"]})
                elif effect["kind"] == "state":
                    c.complete(effect["request"], rig.refresh())
            c.drain()

    def history(self, before_shuffle_on=None, empty_ledger=False, restart=False):
        from control_center.queue_context import QueueLedger
        from control_center.runtime import Runtime, shuffle_record_order
        v7 = self.v7
        rig, ledger = self.e2e.start()
        if empty_ledger:
            ledger = QueueLedger("ROOM", path=v7.Path(v7.__file__).with_name("unused-ledger.json"), autosave=False)
        if before_shuffle_on is not None:
            before_shuffle_on(rig)
        rig.refresh()
        at_on = v7.ids(rig.speaker.items)
        c = self.e2e.upnext(rig, ledger, 7)
        c.button(1, c.control_id, False)                               # Shuffle on (companion)
        job = [e for e in c.drain() if e["kind"] == "shuffle_reorder"][0]
        self.assertTrue(job["on"])
        c.complete(job["request"], Runtime._audio_op(self.runtime_for(rig, c), job, 0, lambda: None))
        self.assertNotEqual(v7.ids(rig.speaker.items), at_on)
        if restart:                                                    # a new companion: the runtime loads it
            c = self.e2e.upnext(rig, ledger, 7)
            self.assertIsNone(c.shuffle_record_order)
            c.shuffle_record(shuffle_record_order(rig.adapter.load_shuffle_record()))
        else:
            self.settle(c, rig)
        self.assertEqual(c.screen.mode, "upnext")
        c.button(1, c.control_id, False)                               # Shuffle off: the preview, then the job
        effects = c.drain()
        job = [e for e in effects if e["kind"] == "shuffle_reorder"][0]
        self.assertFalse(job["on"])
        rows = [e for e in effects if e["kind"] == "upnext_rows" and e.get("shuffle") == "off"][-1]["rows"]
        preview = [int(row["song_id"]) for row in rows]
        Runtime._audio_op(self.runtime_for(rig, c), job, 0, lambda: None)
        realised = v7.ids(rig.speaker.items)
        self.assertEqual(rig.shuffle.saved, {}, "restored: the record is gone")
        return at_on, preview, realised

    def check(self, **kwargs):
        for restart in (False, True):
            with self.subTest(restart=restart):
                at_on, preview, realised = self.history(restart=restart, **kwargs)
                self.assertEqual(realised, at_on)
                self.assertEqual(preview, realised)

    def test_rows_in_the_ledgers_start_order(self):
        self.check()

    def test_a_move_next_of_an_upcoming_row(self):
        def move_next(rig):
            rig.refresh()
            rig.adapter.move_next(8, rig.state["group_revision"], rig.state["queue_revision"])
        self.check(before_shuffle_on=move_next)

    def test_a_reorder_in_another_sonos_app(self):
        def swap(rig):
            rig.speaker.items[4], rig.speaker.items[6] = rig.speaker.items[6], rig.speaker.items[4]
        self.check(before_shuffle_on=swap)

    def test_a_queue_the_companion_did_not_start(self):
        self.check(empty_ledger=True)


class ChangeTests(Fixture):
    def test_a_song_end_retags_without_moving_the_focus(self):
        self.upnext()
        self.turn_to(7)
        self.publish(queue_state(P=6, track_id="track-6"))
        self.assertEqual(self.c.screen.index, 7)
        self.assertEqual(self.frame()["ring"]["now"], 5)

    def test_our_own_revision_change_waits_for_the_job(self):
        self.upnext()
        self.ratings()
        self.press(1)
        self.c.drain()
        self.publish(queue_state(queue_revision="rev-9"))
        self.assertFalse(self.effects("queue_window"))

    def test_source_leaves_the_queue(self):
        self.upnext()
        self.publish(queue_state(source="radio"))
        self.assertEqual(self.one("upnext_close")["reason"], "source")
        self.assertEqual(self.c.screen.mode, "tracks")

    def test_group_change_closes(self):
        self.upnext()
        self.publish(queue_state(group="group-b"))
        self.assertEqual(self.one("upnext_close")["reason"], "group")
        self.assertEqual(self.c.screen.mode, "tracks")


class PlayTests(Fixture):
    def test_jump_at_t0_close_at_380(self):
        self.upnext()
        self.ratings()
        self.turn_to(7)
        self.press(3)
        effects = self.effects()
        jump = self.one("jump", effects)
        self.assertEqual((jump["row"], jump["name"], jump["expected_update_id"]), (8, "Song 8", "rev-1"))
        self.assertEqual(self.one("upnext_close", effects)["close_at_ms"], 380)
        self.tick(0.38)
        self.assertEqual((self.c.screen.mode, self.frame()["status"]), ("home", "Starting…"))

    def test_the_now_playing_row_restarts_it(self):
        self.upnext()
        self.ratings()
        self.press(3)
        self.assertEqual(self.one("jump")["row"], 5)

    def test_click_action(self):
        self.upnext()
        self.ratings()
        self.c.presenter_event({"kind": "click_action", "surface": "upnext"})
        self.assertEqual(len([e for e in self.c.effects if e["kind"] == "jump"]), 1)

    def test_refused_returns_to_tracks(self):
        self.tracks(2)
        self.press(1)
        self.c.presenter_event({"kind": "refused", "surface": "upnext", "reason": "busy"})
        self.assertEqual((self.c.screen.mode, self.c.screen.index), ("tracks", 2))
        self.assertEqual(self.transient(), "Couldn’t open on screen")

    def test_bumps(self):
        self.upnext()
        self.c.limit(1, self.c.control_id)
        self.assertEqual(self.one("upnext_highlight")["bump"], 1)


class Button3FallbackTests(Fixture):
    def test_play_next_mode_runs_move_next(self):
        self.c.upnext_button3 = "playnext"
        self.upnext()
        self.ratings()
        self.turn_to(9)
        frame = self.frame()
        self.assertEqual((frame["buttons"][2]["icon"], frame["buttons"][2]["label"]), ("playnext", "Play next"))
        self.press(2)
        move = self.one("move_next")
        self.assertEqual((move["row"], move["expected_update_id"]), (10, "rev-1"))
        self.c.complete(move["request"], queue_state())
        self.assertEqual((self.c.feedback["moment"], self.transient()), ("queued", "Queued next"))
        self.assertFalse(self.effects("toast"))


if __name__ == "__main__":
    unittest.main()
