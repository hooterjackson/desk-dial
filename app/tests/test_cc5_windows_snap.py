"""K3 section 5.7: the picker, snap (acceptance, failures, advance, pair close, latched closes),
U12 on closes, the close reason in `windows_cancel` (R8), Switch and focus loss (C5-10, C5-11, C5-12,
C5-18, C5-36, C5-46, C5-53); lock, sleep and idle are never latched behind a snap (WP5R-2)."""
from pathlib import Path
import re
import unittest

from cc5_support import Fixture, windows_snapshot

K3 = Path(__file__).resolve().parents[1] / "CONTROL_CENTER_V5.md"


class SnapCase(Fixture):
    def snap(self, side="left"):
        self.press(1 if side == "left" else 2)
        return self.one("windows_snap")


class OpenTests(SnapCase):
    def test_open_only_on_home(self):
        self.tracks()
        self.c.open_windows()
        self.assertFalse(self.effects("windows_open"))
        self.press(0)
        self.c.open_windows()
        self.c.open_windows()
        self.assertEqual(len(self.effects("windows_open")), 1)

    def test_frame(self):
        self.open_windows()
        frame = self.frame()
        self.assertEqual((frame["layout"], frame["heading"], frame["title"], frame["subtitle"], frame["meta"]),
                         ("windows", "", "Window 1", "App1", ""))
        self.assertEqual(frame["ring"]["colors"][:2], [0x204060, 0x204061])

    def test_highlight_follows_turns(self):
        self.open_windows()
        self.turn_to(3)
        highlight = self.one("windows_highlight")
        self.assertEqual((highlight["index"], highlight["bump"]), (3, 0))


class SnapTests(SnapCase):
    def test_assign_on_acceptance_only(self):
        self.open_windows()
        snap = self.snap("left")
        self.assertEqual((snap["side"], snap["index"], snap["place_at_ms"]), ("left", 1, 360))
        self.assertIsNone(self.c.screen.windows.left)
        self.c.snap_result("left", "accepted")
        self.assertEqual(self.c.screen.windows.left, "1")
        self.assertEqual(self.c.feedback, {"kind": "ok", "seq": self.c.feedback_seq, "moment": "snap", "side": -1,
                                           "color": 0x204061})
        button = self.frame()["buttons"][1]
        self.assertEqual((button.get("lit"), button.get("color")), ("on", 0x204061))
        self.assertEqual(self.frame()["meta"], "Left: App1 · pick right")

    def test_move_from_the_other_side_and_same_side_noop(self):
        self.open_windows()
        self.snap("left")
        self.c.snap_result("left", "accepted")
        self.c.snap_result("left", "ok")
        self.turn_to(1)
        self.c.drain()
        self.press(1)
        self.assertFalse(self.effects("windows_snap"), "C5-11: already holds this side")
        self.snap("right")
        self.c.snap_result("right", "accepted")
        self.assertEqual((self.c.screen.windows.left, self.c.screen.windows.right), (None, "1"))

    def test_precheck_failures(self):
        for outcome, text in (("hung", "App1 not responding"), ("move_rejected", "Couldn’t move App1")):
            with self.subTest(outcome=outcome):
                self.open_windows()
                self.snap("left")
                self.c.snap_result("left", outcome)
                self.assertIsNone(self.c.screen.windows.left)
                self.assertEqual((self.transient(), self.c.transient.tone), (text, "error"))
                self.assertAlmostEqual(self.c.transient.until - self.clock(), 2.4)
                self.assertEqual(self.c.feedback["kind"], "err")
                self.assertEqual(self.c.windows_view()["failure"]["reason"], outcome)
                self.press(0)
                self.c.drain()

    def test_placement_failures_unassign(self):
        for outcome, text in (("move_rejected", "Couldn’t move App1"), ("cant_fit", "App1 can’t fit half")):
            with self.subTest(outcome=outcome):
                self.open_windows()
                self.snap("right")
                self.c.snap_result("right", "accepted")
                self.c.snap_result("right", outcome)
                self.assertIsNone(self.c.screen.windows.right)
                self.assertEqual(self.transient(), text)
                self.press(0)
                self.c.drain()

    def test_a_missing_result_counts_as_move_rejected_after_1000_ms(self):
        self.open_windows()
        self.snap("left")
        self.tick(0.99)
        self.assertIsNotNone(self.c.screen.windows.snap_busy)
        self.tick(0.02)
        self.assertIsNone(self.c.screen.windows.snap_busy)
        self.assertEqual(self.transient(), "Couldn’t move App1")

    def test_in_flight_ignores_snap_and_switch(self):
        self.open_windows()
        self.snap("left")
        self.press(2)
        self.press(3)
        self.assertFalse([e for e in self.effects() if e["kind"] in ("windows_snap", "windows_activate")])


class AdvanceTests(SnapCase):
    def test_advance_to_the_next_unassigned_window_wrapping(self):
        self.open_windows()                  # A, B, C, D = 0..3
        self.turn_to(2)
        self.tick(0.5)
        self.snap("left")                    # snap C
        self.c.snap_result("left", "accepted")
        self.c.snap_result("left", "ok")
        self.tick(0.43)
        self.assertEqual(self.c.screen.index, 3, "C → D")
        self.tick(0.5)
        self.snap("right")                   # snap D
        self.c.snap_result("right", "accepted")
        self.c.snap_result("right", "ok")
        self.tick(0.83)
        self.assertEqual(self.c.screen.mode, "home", "both sides: the pair closes")

    def test_advance_skips_closed_windows(self):
        self.open_windows()
        self.c.screen.windows.items[2]["available"] = False
        self.tick(0.5)
        self.snap("left")                    # snap B (index 1)
        self.c.snap_result("left", "accepted")
        self.tick(0.43)
        self.assertEqual(self.c.screen.index, 3)

    def test_pair_close_focus_and_toast(self):
        self.open_windows()
        self.snap("left")
        self.c.snap_result("left", "accepted")
        self.c.snap_result("left", "ok")
        self.tick(0.5)
        self.snap("right")
        self.c.snap_result("right", "accepted")
        self.c.snap_result("right", "ok")
        self.tick(0.83)
        effects = self.effects()
        pair = self.one("windows_close_pair", effects)
        self.assertEqual((pair["left"], pair["right"], pair["focus"]), ("1", "2", "right"))
        self.tick(0.37)
        self.assertEqual([t["text"] for t in self.effects("toast")], ["Side by side · App1 and App2"])


class CloseTests(SnapCase):
    def test_back_with_one_side_completes_u12_and_toasts_after_the_result(self):
        self.open_windows()                  # origin = hwnd 1 = item "0"
        self.snap("left")                    # snap item "1"
        self.c.snap_result("left", "accepted")
        self.c.snap_result("left", "ok")
        self.press(0)
        cancel = self.one("windows_cancel")
        self.assertEqual((cancel["home"], cancel["complete"]), (True, "right"))
        self.tick(0.5)
        self.assertFalse(self.effects("toast"))
        self.c.cancel_result(True, True)
        self.assertEqual([t["text"] for t in self.effects("toast")], ["App1 left · App0 right"])

    def test_no_toast_without_completion_or_on_hold(self):
        self.open_windows()
        self.press(0)
        self.c.cancel_result(True, False)
        self.tick(0.5)
        self.assertFalse(self.effects("toast"))
        self.open_windows()
        self.snap("left")
        self.c.snap_result("left", "accepted")
        self.c.snap_result("left", "ok")
        self.hold()
        self.assertEqual(self.one("windows_cancel", self.c.effects[:])["complete"], "right")
        self.c.cancel_result(True, True)
        self.tick(0.5)
        self.assertFalse(self.effects("toast"))

    def test_u12_applies_on_lifetime_closes_but_not_disconnect_or_focus_lost(self):
        for reason in ("lock", "sleep", "idle"):
            with self.subTest(reason=reason):
                self.open_windows()
                self.snap("left")
                self.c.snap_result("left", "accepted")
                self.c.snap_result("left", "ok")
                self.c.close_overlay(reason)
                self.assertEqual(self.one("windows_cancel")["complete"], "right")
                self.assertEqual(self.c.screen.mode, "home")
        self.open_windows()
        self.c.dismiss_windows()
        effects = self.effects()
        self.assertFalse([e for e in effects if e["kind"] == "windows_cancel"])
        self.assertEqual(len([e for e in effects if e["kind"] == "windows_hide"]), 1)
        self.open_windows()
        self.c.presenter_event({"kind": "closed", "surface": "picker", "reason": "display"})
        self.assertEqual(self.c.screen.mode, "home")
        self.assertFalse([e for e in self.effects() if e["kind"] in ("windows_cancel", "windows_hide")])

    def test_latched_back_runs_when_the_snap_resolves(self):
        self.open_windows()
        self.snap("left")
        self.press(0)
        self.assertEqual(self.c.screen.mode, "windows")
        self.c.snap_result("left", "hung")
        self.assertEqual(self.c.screen.mode, "home")
        self.assertEqual(self.one("windows_cancel")["complete"], None)

    def test_idle_closes_after_60_s_without_knob_input(self):
        self.open_windows()
        self.tick(59.9)
        self.assertEqual(self.c.screen.mode, "windows")
        self.tick(0.2)
        self.assertEqual(self.c.screen.mode, "home")


class SwitchTests(SnapCase):
    def test_switch_ok(self):
        self.open_windows()
        self.press(3)
        activate = self.one("windows_activate")
        self.assertEqual(self.frame()["meta"], "Switching…")
        self.c.complete(activate["request"], True)
        self.assertEqual(self.c.screen.mode, "home")
        self.assertEqual(self.c.feedback, {"kind": "ok", "seq": self.c.feedback_seq})
        self.tick(0.37)
        self.assertEqual([t["text"] for t in self.effects("toast")], ["App1 · Window 1"])

    def test_switch_failure_unfreezes(self):
        self.open_windows()
        self.press(3)
        activate = self.one("windows_activate")
        self.c.complete(activate["request"], False)
        self.assertEqual(self.c.screen.mode, "windows")
        self.assertEqual((self.transient(), self.c.transient.tone), ("Didn’t come forward · retry", "error"))
        self.assertEqual(self.c.feedback["kind"], "err")


class CancelReasonTests(SnapCase):
    """C5-78 (review item R8; K3 5.7.4, 9.9, 11 payloads): `windows_cancel` carries the close `reason`, so
    the picker no longer infers it (WP7b-D6 stays only as the fallback for a payload without one)."""

    def close(self, reason):
        if reason == "back":
            self.press(0)
        elif reason == "hold":
            self.hold()
        elif reason in ("lock", "sleep"):
            self.c.presenter_event({"kind": "system", "what": reason})
        else:
            self.tick(60.2)                  # idle: 60 s without knob input
        return self.one("windows_cancel")

    def test_every_cancel_close_carries_its_reason(self):
        for reason in ("back", "hold", "lock", "sleep", "idle"):
            with self.subTest(reason=reason):
                self.open_windows()
                cancel = self.close(reason)
                self.assertEqual(cancel["reason"], reason)
                self.assertEqual(self.c._cancel_pending["reason"], reason, "the latched reason is the payload's")
                self.assertEqual(self.c.screen.mode, "home")

    def test_a_back_or_hold_latched_behind_a_snap_keeps_its_reason(self):
        """C5-12: only Back and hold are latched while a snap is in flight."""
        for reason in ("back", "hold"):
            with self.subTest(reason=reason):
                self.open_windows()
                self.snap("left")
                if reason == "back":
                    self.press(0)
                else:
                    self.hold()
                self.assertEqual(self.c.screen.mode, "windows", "latched while the snap is in flight")
                self.assertFalse(self.effects("windows_cancel"))
                self.c.snap_result("left", "hung")
                self.assertEqual(self.one("windows_cancel")["reason"], reason)
                self.assertEqual(self.c.screen.mode, "home")

    def lifetime(self, reason):
        if reason == "idle":
            self.c.close_overlay("idle")
        else:
            self.c.presenter_event({"kind": "system", "what": reason})

    def test_lock_sleep_and_idle_during_a_snap_close_at_once(self):
        """WP5R-2: K3 5.7.4 and K4 15 make lock, sleep and idle instant for the picker; C5-12 latches
        Back and hold only. The close carries its reason and U12 as assigned at that moment, and the
        snap's late results change nothing (no second close, no failure copy, no err)."""
        for reason in ("lock", "sleep", "idle"):
            for accepted in (False, True):
                with self.subTest(reason=reason, accepted=accepted):
                    self.open_windows()      # origin = item "0"
                    self.snap("left")        # item "1"
                    if accepted:
                        self.c.snap_result("left", "accepted")
                    self.c.drain()
                    self.lifetime(reason)
                    feedback = (self.c.feedback, self.c.feedback_seq)
                    self.assertEqual(self.c.screen.mode, "home", "not latched behind the snap")
                    cancel = self.one("windows_cancel")
                    self.assertEqual((cancel["reason"], cancel["complete"]),
                                     (reason, "right" if accepted else None))
                    self.assertEqual(self.c._cancel_pending["reason"], reason)
                    for outcome in (("accepted", "ok") if not accepted else ("move_rejected",)):
                        self.c.snap_result("left", outcome)
                    self.tick(1.1)           # past the 1000 ms snap backstop and the 420 ms advance
                    self.assertEqual(self.c.screen.mode, "home")
                    self.assertFalse([e for e in self.effects()
                                      if e["kind"] in ("windows_cancel", "windows_hide", "windows_highlight",
                                                       "windows_close_pair")])
                    self.assertEqual((self.c.feedback, self.c.feedback_seq), feedback,
                                     "a late result sends no feedback")
                    self.assertIsNone(self.transient(), "and no failure copy")

    def test_a_lifetime_close_overrides_a_latched_back(self):
        for reason in ("lock", "sleep", "idle"):
            with self.subTest(reason=reason):
                self.open_windows()
                self.snap("left")
                self.press(0)                # Back: latched
                self.assertEqual(self.c.screen.mode, "windows")
                self.lifetime(reason)
                self.assertEqual(self.c.screen.mode, "home")
                self.assertEqual(self.one("windows_cancel")["reason"], reason)
                self.c.snap_result("left", "hung")
                self.assertFalse(self.effects("windows_cancel"), "the latched Back never runs")

    def test_k3_latches_back_and_hold_only(self):
        """WP5R-2: K3 says what the controller does (5.7.3's latched-close bullet and C5-12)."""
        k3 = re.sub(r"~~.*?~~", "", K3.read_text(encoding="utf-8"))
        bullet = next(line for line in k3.splitlines() if line.startswith("- Latched close:"))
        self.assertIn("Only Back and hold are latched", bullet)
        self.assertIn("closes the picker **at once**", bullet)
        c5_12 = next(line for line in k3.splitlines() if line.startswith("| C5-12 |"))
        self.assertIn("Lock, sleep and idle are never latched", c5_12)

    def test_hide_closes_carry_no_cancel(self):
        self.open_windows()
        self.c.dismiss_windows()
        self.assertFalse([e for e in self.effects() if e["kind"] == "windows_cancel"])

    def test_a_lock_or_sleep_close_that_restores_nothing_raises_no_notice(self):
        for reason, notice in (("lock", ""), ("sleep", ""), ("back", "Original window no longer available"),
                               ("idle", "Original window no longer available")):
            with self.subTest(reason=reason):
                self.c.notice = ""
                self.open_windows()
                self.close(reason)
                self.c.cancel_result(False, False)       # K4 15: lock and sleep never restore focus
                self.assertEqual(self.c.notice, notice)


if __name__ == "__main__":
    unittest.main()
