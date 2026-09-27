"""K-docs: claims of the frozen contracts pinned to the code, so text and code cannot drift apart silently.

K3 = CONTROL_CENTER_V5.md, VOC = firmware/V5_VOCABULARY.md. Written for the phase-2a K-docs
review fixes; each class pins one of them (tag [P2a] in both documents):

- AppendixASignOffTests (KD-R6, K3 Appendix A): the footer slots where the controller differs from the
  r2.2 prototype are exactly the 23 signed-off rows of A.2 (case, button, both token·tone pairs, the
  oracle's tag and the rulings), and A.1's counts are the run's. The oracle's own test tags whole regions,
  so a slot inside a region could change without a failure; this closes that.
- ShuffleOffRestoreOrderTests (KD-R1, K3 9.5.3 limitations, C5-73): the adapter restores the record's
  order (the base rows' order at Shuffle on) behind the Play-next block; the controller's preview ranks
  base rows by the ledger's start order. Equal when the rows still stood in that order at Shuffle on;
  different after an Up next move_next of an upcoming row, a reorder in another Sonos app, or on a queue
  the companion did not start.
- SeekFollowUpAtStartTests (KD-R2, K3 C5-77): a start drops a Seek follow-up still waiting after Seek was
  left. Pending WP5 (PENDING_WP5): the start cases skip with the handoff reason while the controller
  still sends the follow-up, and fail once it does not, so the entry is removed with the fix.
- GroupChangedPerOpTests (KD-R3, K3 8 and 9.10, C5-76): which ops show `Speaker group changed` from
  their own result and which show their own failure first.
- SeekConfirmTimerTests (KD-R7, K3 7 and VOC 10 `seek_confirm_ms`, C5-74): the rows name the Up next
  jump's use of the window, and the adapter uses that value for it.

Headless: the fake clock, the FakeSpeaker, the real Controller, the runtime's audio dispatch, the
SonosAdapter and the QueueLedger; no device, port, network, window or Tk.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT), str(Path(__file__).resolve().parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from cc5_support import Fixture, fail, queue_state, window_result  # noqa: E402
from control_center import sonos as S  # noqa: E402
from control_center.queue_context import QueueLedger, Segment  # noqa: E402
from control_center.runtime import Runtime  # noqa: E402
import test_cc5_grammar_oracle as oracle  # noqa: E402
import test_cc_sonos_v7 as sonos_v7  # noqa: E402

K3 = ROOT / "CONTROL_CENTER_V5.md"
VOC = ROOT.parent / "firmware" / "V5_VOCABULARY.md"
UNUSED_LEDGER = Path(__file__).with_name("unused-ledger.json")   # never written (autosave off)

# A contract rule another package still has to implement: {C5 id: the handoff}. A case pinned to it skips
# with this reason while the code still differs, and fails once the code follows the rule, so the entry
# is removed together with the fix.
# C5-77 landed in phase 3 (WP5-fixes: controller `_drop_seek_follow_up` at `_dispatch_start` and the Up
# next jump press; cases in test_cc5_tracks_seek.SeekStartDropsFollowUpTests).
PENDING_WP5 = {}


def section(text, start, end):
    """The text from the line matching `start` up to the next line matching `end`."""
    m = re.search(start, text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    e = re.search(end, rest, re.M)
    return text[m.start(): m.end() + (e.start() if e else len(rest))]


def table_row(text, first_cell):
    rows = [line for line in text.splitlines() if line.startswith(f"| {first_cell} |")]
    return rows[0] if len(rows) == 1 else None


def unstruck(text):
    return re.sub(r"~~.*?~~", "", text, flags=re.S)


# ---------------------------------------------------------------------------------- KD-R6
# K3 Appendix A.2: (golden case, button) -> (row, controller token·tone, prototype token·tone, oracle tag,
# the rulings the row must cite).
SIGNED_OFF = {
    ("home-playing-none", 1): ("A1", ("play", "dim"), ("pause", "nav"), "VOC-R14", ("C5-38", "VOC-R14")),
    ("home-playing-none", 3): ("A2", ("tracks", "dim"), ("tracks", "nav"), "VOC-R14", ("VOC-R14",)),
    ("home-playing-starting-none", 1): ("A3", ("play", "dim"), ("pause", "dim"), "VOC-R14", ("C5-38",)),
    ("home-playing-starting-none", 3): ("A4", ("tracks", "dim"), ("tracks", "nav"), "VOC-R14", ("VOC-R14",)),
    ("home-paused-none", 1): ("A5", ("play", "dim"), ("play", "go"), "VOC-R14", ("VOC-R14",)),
    ("home-paused-none", 3): ("A6", ("tracks", "dim"), ("tracks", "nav"), "VOC-R14", ("VOC-R14",)),
    ("home-paused-starting-none", 3): ("A7", ("tracks", "dim"), ("tracks", "nav"), "VOC-R14", ("VOC-R14",)),
    ("tracks--1-none", 4): ("A8", ("prev", "dim"), ("prev", "go"), "skip_unavailable", ("C5-4",)),
    ("tracks-1-none", 4): ("A9", ("next", "dim"), ("next", "go"), "skip_unavailable", ("C5-4",)),
    ("tracks-1-queue-start", 3): ("A10", ("seek", "dim"), ("seek", "nav"), "C5-4", ("C5-3", "C5-4")),
    ("tracks-1-queue-start", 4): ("A11", ("next", "dim"), ("next", "go"), "C5-4", ("C5-3", "C5-4")),
    ("tracks-1-queue-pn", 4): ("A12", ("next", "dim"), ("next", "go"), "C5-4", ("C5-3", "C5-4")),
    ("recent-queue-shuffle_off-idle-list", 3): ("A13", ("playnext", "dim"), ("playnext", "nav"), "C5-61",
                                                ("C5-4", "C5-61")),
    ("recent-queue-shuffle_off-idle-list", 4): ("A14", ("play", "dim"), ("play", "go"), "C5-61", ("C5-4", "C5-61")),
    ("recent-queue-shuffle_on-idle-list", 4): ("A15", ("play", "dim"), ("play", "go"), "C5-61", ("C5-4", "C5-61")),
    ("recent-airplay-shuffle_off-idle-list", 4): ("A16", ("play", "dim"), ("play", "go"), "C5-61",
                                                  ("C5-4", "C5-61")),
    ("recent-airplay-shuffle_on-idle-list", 4): ("A17", ("play", "dim"), ("play", "go"), "C5-61",
                                                 ("C5-4", "C5-61")),
    ("recent-radio-shuffle_off-idle-list", 4): ("A18", ("play", "dim"), ("play", "go"), "C5-61", ("C5-4", "C5-61")),
    ("recent-radio-shuffle_on-idle-list", 4): ("A19", ("play", "dim"), ("play", "go"), "C5-61", ("C5-4", "C5-61")),
    ("recent-linein-shuffle_off-idle-list", 4): ("A20", ("play", "dim"), ("play", "go"), "C5-61",
                                                 ("C5-4", "C5-61")),
    ("recent-linein-shuffle_on-idle-list", 4): ("A21", ("play", "dim"), ("play", "go"), "C5-61", ("C5-4", "C5-61")),
    ("recent-none-shuffle_off-idle-list", 4): ("A22", ("play", "dim"), ("play", "go"), "C5-61", ("C5-4", "C5-61")),
    ("recent-none-shuffle_on-idle-list", 4): ("A23", ("play", "dim"), ("play", "go"), "C5-61", ("C5-4", "C5-61")),
}


def _pair(cell):
    """'`play · dim`' (optionally followed by the dim code) -> ('play', 'dim')."""
    m = re.match(r"`([a-z]+) · ([a-z]+)`", cell.strip())
    return (m.group(1), m.group(2)) if m else None


class AppendixASignOffTests(unittest.TestCase):
    """KD-R6: K3 Appendix A.2 is the exact set of differing footer slots, pinned both ways."""

    @classmethod
    def setUpClass(cls):
        cls.observed, cls.compared = {}, 0
        for case in oracle.GOLDEN["cases"]:
            if case["name"] in oracle.NOT_TESTED:
                continue
            got = oracle.build(case).footer()
            for slot, bs in enumerate(case["foot"]):
                cls.compared += 1
                want = oracle.bs_slot(bs)
                if tuple(got[slot]) != tuple(want):
                    cls.observed[(case["name"], slot + 1)] = (tuple(got[slot]), tuple(want),
                                                             oracle.deviation(case, slot))

    def test_the_observed_differences_are_exactly_the_signed_off_rows(self):
        expected = {key: (row[1], row[2], row[3]) for key, row in SIGNED_OFF.items()}
        new = {k: v for k, v in self.observed.items() if k not in expected}
        gone = sorted(k for k in expected if k not in self.observed)
        changed = {k: (self.observed[k], expected[k]) for k in expected
                   if k in self.observed and self.observed[k] != expected[k]}
        self.assertEqual((new, gone, changed), ({}, [], {}),
                         "a footer difference appeared, vanished or changed: fix the controller to match the r2.2 "
                         "prototype, or add its ruling to K3 Appendix A (and a C5 entry) and to SIGNED_OFF")
        self.assertGreater(self.compared, 900)

    @unittest.skipUnless(K3.is_file(), "CONTROL_CENTER_V5.md is not next to the companion")
    def test_appendix_a2_is_the_signed_off_set(self):
        text = K3.read_text(encoding="utf-8")
        appendix = section(text, r"^### A\.2 ", r"^### A\.3 ")
        rows = [line for line in appendix.splitlines() if re.match(r"^\| A\d+ \|", line)]
        self.assertEqual(len(rows), len(SIGNED_OFF))
        parsed = {}
        for line in rows:
            cells = [cell.strip() for cell in line.strip().strip("|").split(" | ")]
            self.assertEqual(len(cells), 9, line[:120])
            row, case, button, host, bs, _differs, tag, ruling, verdict = cells
            key = (case.strip("`"), int(button.replace("Button", "").strip()))
            parsed[key] = (row, _pair(host), _pair(bs), tag.strip("`"), ruling)
            self.assertEqual(verdict, "documented", row)
        self.assertEqual(set(parsed), set(SIGNED_OFF))
        for key, (row, host, bs, tag, rulings) in SIGNED_OFF.items():
            with self.subTest(row=row):
                got_row, got_host, got_bs, got_tag, ruling_text = parsed[key]
                self.assertEqual((got_row, got_host, got_bs, got_tag), (row, host, bs, tag))
                for ruling in rulings:
                    self.assertRegex(ruling_text, rf"{re.escape(ruling)}(?!\d)", f"{row} cites {ruling}")

    @unittest.skipUnless(K3.is_file(), "CONTROL_CENTER_V5.md is not next to the companion")
    def test_appendix_a1_counts_are_the_runs(self):
        result = [line for line in section(K3.read_text(encoding="utf-8"), r"^### A\.1 ", r"^### A\.2 ").splitlines()
                  if line.startswith("- **Result")]
        self.assertEqual(len(result), 1)
        line, cases = result[0], len(oracle.GOLDEN["cases"])
        differ = len(self.observed)
        self.assertIn(f"{cases} golden cases; {cases - len(oracle.NOT_TESTED)} compared", line)
        self.assertIn(f"**{self.compared} slots**, **{self.compared - differ} equal**, **{differ} differ**", line)
        for tag, count in Counter(v[2] for v in self.observed.values()).items():
            self.assertIn(f"`{tag}` {count}", line)


# ---------------------------------------------------------------------------------- KD-R1
class ShuffleOffRestoreOrderTests(unittest.TestCase):
    """KD-R1 (K3 9.5.3 limitations, C5-73): the realised order is the record's (the base rows' order at
    Shuffle on); the preview ranks base rows by the ledger's start order, rows it does not know after them
    in their current order. Album 90..99 started by the companion, row 2 playing, no Play-next rows."""

    @classmethod
    def setUpClass(cls):
        cls.e2e = sonos_v7.ShuffleOffPreviewEndToEndTests("test_the_preview_is_the_realised_order_in_both_twin_cases")
        cls.e2e.setUpClass()

    def run_history(self, before_shuffle_on=None, ledger=None):
        rig, started = self.e2e.start()
        ledger = started if ledger is None else ledger
        if before_shuffle_on is not None:
            before_shuffle_on(rig)
        rig.refresh()
        at_shuffle_on = sonos_v7.ids(rig.speaker.items)
        c = self.e2e.upnext(rig, ledger, 7)
        c.button(1, c.control_id, False)                     # Shuffle on (companion regime, U = 8)
        jobs = [e for e in c.drain() if e["kind"] == "shuffle_reorder"]
        self.assertTrue(jobs and jobs[0]["on"])
        self.assertEqual(jobs[0]["playnext_offsets"], [], "no Play-next rows in these histories")
        Runtime._audio_op(SimpleNamespace(sonos=rig.adapter, _check_epoch=lambda epoch: None,
                                          _post_progress=lambda request, value: None), jobs[0], 0, lambda: None)
        shuffled = sonos_v7.ids(rig.speaker.items)
        self.assertNotEqual(shuffled, at_shuffle_on)
        effect, preview, realised = self.e2e.shuffle(rig, ledger, 7)   # Shuffle off: preview, then the job
        self.assertFalse(effect["on"])
        self.assertEqual(rig.shuffle.saved, {}, "restored: the record is gone")
        return ledger, at_shuffle_on, shuffled, preview, realised

    @staticmethod
    def ledger_ranked(shuffled, played, ledger):
        """K3 9.5.3: the preview's base-row order (no Play-next rows here)."""
        base = list(ledger.base.song_ids) if ledger.base else []
        known, unknown = [], []
        for number in shuffled[played:]:
            if str(number) in base:
                rank = base.index(str(number))
                base[rank] = None
                known.append((rank, number))
            else:
                unknown.append(number)
        return shuffled[:played] + [n for _, n in sorted(known)] + unknown

    def test_rows_in_the_ledgers_start_order_at_shuffle_on_preview_the_realised_order(self):
        _ledger, at_on, _shuffled, preview, realised = self.run_history()
        self.assertEqual(realised, at_on)
        self.assertEqual(preview, realised)

    def check_limitation(self, before_shuffle_on=None, ledger=None):
        ledger, at_on, shuffled, preview, realised = self.run_history(before_shuffle_on, ledger)
        self.assertEqual(realised, at_on, "the adapter restores the order the rows had at Shuffle on")
        self.assertEqual(preview, self.ledger_ranked(shuffled, 2, ledger), "the preview ranks by the ledger")
        self.assertNotEqual(preview, realised, "the documented limitation: the list re-reads after the job")

    def test_limitation_2_a_move_next_of_an_upcoming_row(self):
        def move_next(rig):                                  # Up next Button 3 in the Play-next fallback
            rig.refresh()
            state = rig.adapter.move_next(8, rig.state["group_revision"], rig.state["queue_revision"])
            self.assertNotIn("_inserted", state, "no ledger entry for an upcoming row")
        self.check_limitation(move_next)

    def test_limitation_2_a_reorder_in_another_sonos_app(self):
        def swap(rig):                                       # same ids: every row still classifies as base
            rig.speaker.items[4], rig.speaker.items[6] = rig.speaker.items[6], rig.speaker.items[4]
        self.check_limitation(swap)

    def test_limitation_3_a_queue_the_companion_did_not_start(self):
        self.check_limitation(ledger=QueueLedger("ROOM", path=UNUSED_LEDGER, autosave=False))
        older = QueueLedger("ROOM", path=UNUSED_LEDGER, autosave=False)
        older.record_start(Segment("album", name="Older"), ["97", "96", "95", "300", "301"])
        self.check_limitation(ledger=older)
        self.assertFalse(UNUSED_LEDGER.exists())


# ---------------------------------------------------------------------------------- KD-R2
class SeekFollowUpAtStartTests(Fixture):
    """KD-R2 (K3 C5-77, 1.1, 5.5.5): a start sent while a Seek follow-up waits for the in-flight jump
    to land drops the follow-up; without a start it is still sent (C5-68)."""

    initial = queue_state(position_s=74, duration_s=210)

    def leave_seek_with_a_follow_up(self, exit_logical):
        self.seek()
        self.turn_to(20)
        self.tick(0.3)
        first = self.one("seek")
        self.turn_to(26)                                     # a follow-up target waits for the landing
        self.press(exit_logical)
        self.assertIsNotNone(self.c._seek_bg, "kept across the explicit exit (C5-68)")
        return first

    def seeks_after_the_landing(self, first):
        self.c.complete(first["request"], {**queue_state(), "_applied_seek": first["target_s"]})
        sent = []
        for _ in range(6):
            self.tick(0.3)
            sent += [e for e in self.c.drain() if e["kind"] == "seek"]
        return sent

    def assert_dropped(self, sent):
        if "C5-77" in PENDING_WP5:
            if sent:
                self.skipTest(PENDING_WP5["C5-77"])
            self.fail("C5-77 is implemented: remove it from PENDING_WP5 and the K3 section 18 handoff")
        self.assertEqual(sent, [])
        self.assertIsNone(self.c._seek_bg)

    def test_without_a_start_the_follow_up_is_sent_after_the_landing(self):
        first = self.leave_seek_with_a_follow_up(0)
        self.assertEqual([e["target_s"] for e in self.seeks_after_the_landing(first)], [74 + 55])

    def test_an_up_next_play_drops_the_waiting_follow_up(self):
        first = self.leave_seek_with_a_follow_up(1)          # Button 2: Seek -> Up next
        self.assertEqual(self.c.screen.mode, "upnext")
        _P, T = self.c._position()
        while any(e["kind"] == "queue_window" for e in self.c.pending.values()):
            effect = self.pending("queue_window")
            self.c.complete(effect["request"], window_result(effect["start"], effect["count"], T))
        self.ratings()
        self.press(3)                                        # Up next Play on the playing row: a jump
        self.assertEqual(len(self.effects("jump")), 1)
        self.assertEqual(self.c._busy_code(), "starting")
        self.assert_dropped(self.seeks_after_the_landing(first))

    def test_a_recent_play_drops_the_waiting_follow_up(self):
        first = self.leave_seek_with_a_follow_up(0)          # Button 1: Seek -> Tracks
        self.press(0)                                        # Tracks -> Home
        self.browse()
        self.press(3)                                        # Recent Play: play_items
        self.assertEqual(len(self.effects("play_items")), 1)
        self.assertEqual(self.c._busy_code(), "starting")
        self.assert_dropped(self.seeks_after_the_landing(first))


# ---------------------------------------------------------------------------------- KD-R3
class GroupChangedPerOpTests(Fixture):
    """KD-R3 (K3 8, 9.10, C5-76): a start shows `Speaker group changed` from its own result with no
    toast; a seek, a shuffle and a transport press show their own failure first and the group copy from
    the next state poll; move_next keeps the Play next rule."""

    initial = queue_state(position_s=74, duration_s=210)

    def assert_group_copy(self, ms, tone="error"):    # lead ruling R-j (phase 3): was the `meta` tone
        transient = self.c.transient
        self.assertIn(transient.copy_id, ("knob.status.group_changed", "knob.meta.group_changed"))
        self.assertEqual((transient.text, transient.tone), ("Speaker group changed", tone))
        self.assertAlmostEqual(transient.until - self.clock(), ms / 1000.0, places=6)

    def poll_new_group(self):
        seq = self.c.feedback_seq
        self.tick(1.0)
        self.publish(queue_state(group="group-b"))
        self.assertEqual(self.c.feedback_seq, seq, "no second err from the poll")
        self.assert_group_copy(2600)

    def no_toasts(self):
        toasts = []
        for _ in range(4):
            toasts += [e for e in self.c.drain() if e["kind"] == "toast"]
            self.tick(0.5)
        self.assertEqual((toasts, self.c._toasts), ([], []))

    def test_a_recent_start_shows_the_group_copy_and_no_toast(self):
        self.browse()
        self.press(3)
        start = self.one("play_items")
        self.c.complete(start["request"], error=fail("group", outcome="group_changed"))
        self.assertEqual(self.c.feedback["kind"], "err")
        self.assert_group_copy(2600)
        self.assertEqual(self.c.transient.copy_id, "knob.status.group_changed", "Home's status line")
        self.no_toasts()

    def test_an_up_next_jump_shows_the_group_copy_and_no_exit_toast(self):
        self.upnext()
        self.ratings()
        self.press(3)
        jump = self.one("jump")
        self.tick(0.4)                                       # the overlay closed at t0 + 380
        self.c.complete(jump["request"], error=fail("group", outcome="group_changed"))
        self.assertEqual(self.c.feedback["kind"], "err")
        self.assert_group_copy(2600)
        self.no_toasts()

    def test_a_seek_shows_its_failure_line_then_the_poll_the_group_copy(self):
        self.seek()
        self.turn_to(20)
        self.tick(0.3)
        seek = self.one("seek")
        self.c.complete(seek["request"], error=fail("group", outcome="group_changed"))
        self.assertEqual(self.c.feedback["kind"], "err")
        self.assertEqual((self.c.screen.mode, self.frame()["meta"]), ("seek", "Didn’t jump · try again"))
        self.poll_new_group()
        self.assertEqual(self.c.screen.mode, "tracks", "the group change exits Seek (C5-47)")

    def test_a_shuffle_shows_its_failure_copy_then_the_poll_the_group_copy(self):
        self.upnext()
        self.ratings()
        self.press(1)
        job = self.one("shuffle_reorder")
        self.c.complete(job["request"], error=fail("group", outcome="group_changed"))
        self.assertEqual(self.c.feedback["kind"], "err")
        transient = self.c.transient
        self.assertEqual((transient.copy_id, transient.tone), ("knob.meta.shuffle.failed", "error"))
        self.assertAlmostEqual(transient.until - self.clock(), 2.4, places=6)
        self.poll_new_group()
        self.assertNotEqual(self.c.screen.mode, "upnext", "Up next closes `group`")

    def test_a_transport_press_shows_the_notice_then_the_poll_the_group_copy(self):
        self.tracks(index=2)
        self.press(3)
        skip = self.one("transport")
        self.c.complete(skip["request"], error=fail("group", outcome="group_changed"))
        self.assertEqual(self.c.feedback["kind"], "err")
        self.assertEqual((self.c.notice, self.c.transient), ("group", None), "the desktop notice, no knob copy")
        self.poll_new_group()

    def test_move_next_keeps_the_play_next_rule(self):
        self.c.upnext_button3 = "playnext"
        self.upnext()
        self.ratings()
        self.turn_to(8)
        self.press(2)
        move = self.one("move_next")
        self.c.complete(move["request"], error=fail("group", outcome="group_changed"))
        self.assertEqual(self.c.feedback["kind"], "err")
        self.assert_group_copy(2400, tone="error")
        self.assertEqual(self.c.transient.copy_id, "knob.meta.group_changed")
        self.no_toasts()


# ---------------------------------------------------------------------------------- KD-R7
class SeekConfirmTimerTests(unittest.TestCase):
    """KD-R7 (K3 7, VOC 10, C5-74): `seek_confirm_ms` bounds the Seek landing and the Up next jump; the
    rows say both, and the adapter uses the one value for both."""

    def rows(self):
        rows = []
        for path, sec in ((K3, (r"^## 7\. Timers", r"^## 8\. ")), (VOC, (r"^## 10\. ", r"^## 11\. "))):
            row = table_row(section(path.read_text(encoding="utf-8"), *sec), "`seek_confirm_ms`")
            self.assertIsNotNone(row, path.name)
            rows.append((path.name, unstruck(row)))
        return rows

    @unittest.skipUnless(K3.is_file() and VOC.is_file(), "the contracts are not next to the companion")
    def test_both_timer_rows_name_the_seek_and_the_jump_use(self):
        for name, row in self.rows():
            with self.subTest(doc=name):
                self.assertRegex(row, r"\b8000\b")
                for needle in ("`not_confirmed`", "`jump`", "`start_failed`", "`PLAYING`", "C5-74", "C5-68"):
                    self.assertIn(needle, row)

    @unittest.skipUnless(K3.is_file() and VOC.is_file(), "the contracts are not next to the companion")
    def test_the_adapter_times_a_jump_out_at_that_value_as_start_failed(self):
        for name, row in self.rows():
            value = re.search(r"\| \*\*(?:\[r2\.2\] )?(\d+)\*\*", row)
            self.assertIsNotNone(value, name)
            self.assertEqual(S.SEEK_CONFIRM_S * 1000, int(value.group(1)), name)
        jumps = sonos_v7.JumpConfirmationTests("test_a_transition_as_long_as_the_live_seeks_is_ok")
        rig = jumps.rig(transition_s=60.0, latency=0.0)      # TRANSITIONING past the window
        with self.assertRaises(S.SonosError) as raised:
            jumps.jump(rig)
        self.assertEqual(S.sonos_outcome(raised.exception, "jump"), "start_failed")
        self.assertAlmostEqual(rig.clock.now() - rig.sent[0], S.SEEK_CONFIRM_S, delta=0.11)
        self.assertEqual(rig.speaker.seeks, [3], "one Seek, never resent")


if __name__ == "__main__":
    unittest.main()
