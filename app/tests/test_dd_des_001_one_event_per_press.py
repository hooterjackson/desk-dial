"""DD-DES-001: an async action plays one haptic event, at the press (the way Scene run does), never a second one when
the speaker answers. Play thumps at the press, a skip and a Tracks / Up next jump nudge their way (a jump never
thumps, r4 4.4's thump budget), shuffle and Like keep their press tick. The success feedback still arms its sound
moment (ID-SOUND-ALL: every interaction has a sound and a haptic); a refusal or a failure keeps its own buzz.
Headless: the cc5 / r3 fixtures, never a port or a window."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cc5_support import Fixture, fail, queue_state  # noqa: E402
from r3_support import R3Fixture  # noqa: E402


class OneEventMixin:
    def token(self):
        return self.c.haptic["token"] if self.c.haptic else None

    def assert_result_silent(self, seq, moment_seq):
        """The result left the haptic seq where the press put it, and armed a new (sound) moment."""
        self.assertEqual(self.c.haptic["seq"], seq, "a second haptic event at the result")
        self.assertNotEqual(self.c.feedback_seq, moment_seq, "the result still arms its sound moment")
        self.assertEqual(self.c.feedback["kind"], "ok")


class AsyncActionsOneEvent(OneEventMixin, Fixture):
    # -------------------------------------------------------------- Play (a started list)
    def test_play_thumps_at_the_press_only(self):
        self.browse()
        self.turn_to(3)
        self.press(3)
        self.assertEqual(self.token(), "confirm.thump")
        seq, moment = self.c.haptic["seq"], self.c.feedback_seq
        start = self.pending("play_items")
        self.c.complete(start["request"], {**queue_state(title="Promises"), "_start": {"k": 9, "n": 9, "u": 0}})
        self.assertEqual(self.c.feedback["moment"], "started")
        self.assert_result_silent(seq, moment)

    def test_explorer_play_thumps_at_the_press_only(self):
        self.browse()
        self.press(1)
        self.c.drain()
        self.press(3)
        self.assertEqual(self.token(), "confirm.thump")
        seq, moment = self.c.haptic["seq"], self.c.feedback_seq
        self.tick(0.38)
        self.c.complete(self.pending("play_items")["request"], {**queue_state(), "_start": {"k": 9, "n": 9, "u": 0}})
        self.assert_result_silent(seq, moment)

    def test_play_failure_keeps_its_error_buzz(self):
        self.browse()
        self.press(3)
        self.tick(1.1)
        self.complete("play_items", error=fail("x", outcome="start_failed"))
        self.assertEqual(self.c.feedback["kind"], "err")
        self.assertEqual(self.token(), "error.buzz")

    # -------------------------------------------------------------- skip
    def test_skip_nudges_at_the_press_only(self):
        for index, token in ((2, "nudge.right"), (0, "nudge.left")):
            with self.subTest(index=index):
                self.publish(queue_state())
                self.tracks(index)
                self.press(3)
                self.assertEqual(self.token(), token)
                seq, moment = self.c.haptic["seq"], self.c.feedback_seq
                transport = self.one("transport")
                self.c.complete(transport["request"], queue_state(P=6 if index else 4, track_id="track-x"))
                self.assertEqual(self.c.feedback.get("skip"), 1 if index else -1)
                self.assert_result_silent(seq, moment)
                self.press(0)
                self.c.drain()
                self.tick(1.0)

    def test_skip_failure_keeps_its_error_buzz(self):
        self.tracks(2)
        self.press(3)
        self.complete("transport", error=fail("Sonos refused"))
        self.assertEqual(self.token(), "error.buzz")

    # -------------------------------------------------------------- Up next: jump, shuffle, Like
    def test_upnext_jump_nudges_and_never_thumps(self):
        self.upnext()
        self.ratings()
        self.turn_to(7)                               # row 8, after the playing row 5
        self.press(3)
        self.assertEqual(self.token(), "nudge.right")
        seq, moment = self.c.haptic["seq"], self.c.feedback_seq
        self.tick(0.38)
        self.c.complete(self.pending("jump")["request"], {**queue_state(P=8), "_start": {}})
        self.assertEqual(self.c.feedback["moment"], "started")
        self.assert_result_silent(seq, moment)

    def test_upnext_jump_back_nudges_left(self):
        self.upnext()
        self.ratings()
        self.turn_to(2)                               # row 3, before the playing row 5
        self.press(3)
        self.assertEqual(self.token(), "nudge.left")

    def test_upnext_jump_failure_keeps_its_error_buzz(self):
        self.upnext()
        self.ratings()
        self.turn_to(7)
        self.press(3)
        self.tick(1.1)
        self.complete("jump", error=fail("x", outcome="start_failed"))
        self.assertEqual(self.token(), "error.buzz")

    def test_companion_shuffle_ticks_at_the_press_only(self):
        self.upnext()
        self.ratings()
        self.press(1)
        self.assertEqual(self.token(), "confirm.tick")
        seq, moment = self.c.haptic["seq"], self.c.feedback_seq
        job = self.pending("shuffle_reorder")
        self.c.progress(job["request"], {"phase": "accepted"})
        self.assertEqual(self.c.feedback["moment"], "shuffle")
        self.assert_result_silent(seq, moment)
        moment = self.c.feedback_seq
        self.c.complete(job["request"], queue_state(companion_shuffle=True))
        self.assertEqual(self.c.haptic["seq"], seq)
        self.assertEqual(self.c.feedback_seq, moment, "accepted already played the moment")

    def test_sonos_shuffle_ticks_at_the_press_only(self):
        self.publish(queue_state(T=200))              # beyond the companion limit: Sonos native shuffle
        self.upnext()
        self.ratings()
        self.press(1)
        self.assertEqual(self.token(), "confirm.tick")
        seq, moment = self.c.haptic["seq"], self.c.feedback_seq
        self.complete("set_shuffle", queue_state(T=200, shuffle=True, play_mode="SHUFFLE"))
        self.assertEqual(self.c.feedback["moment"], "shuffle")
        self.assert_result_silent(seq, moment)

    def test_shuffle_failure_keeps_its_error_buzz(self):
        self.upnext()
        self.ratings()
        self.press(1)
        self.complete("shuffle_reorder", error=fail("changed", outcome="queue_changed"))
        self.assertEqual(self.token(), "error.buzz")

    def test_like_ticks_at_the_press_only(self):
        self.upnext()
        self.ratings()
        self.turn_to(6)
        self.press(2)
        self.assertEqual(self.token(), "confirm.tick")
        seq, moment = self.c.haptic["seq"], self.c.feedback_seq
        self.complete("like", {"liked": True})
        self.assertEqual(self.c.feedback["moment"], "like")
        self.assert_result_silent(seq, moment)

    def test_like_failure_keeps_its_error_buzz(self):
        self.upnext()
        self.ratings()
        self.turn_to(6)
        self.press(2)
        self.complete("like", error=fail("busy", outcome="rate_limited", status=429))
        self.assertEqual(self.token(), "error.buzz")


class TracksJumpOneEvent(OneEventMixin, R3Fixture):
    """The audit repro (dd4_jump_thump.py): Tracks 4 on row 9 nudged at the press, then thumped at the result."""

    def test_tracks_jump_nudges_and_never_thumps(self):
        self.c._enter_tracks(1, "tracks")
        self.c.drain()
        self.turn_to(8)                               # row 9
        self.press(3)                                 # 4: jump
        self.assertEqual(self.token(), "nudge.right")
        seq, moment = self.c.haptic["seq"], self.c.feedback_seq
        self.c.complete(self.pending("jump")["request"], {**queue_state(P=9, T=12, track_id="track-9"), "_start": {}})
        self.assertEqual(self.c.feedback["moment"], "started")
        self.assert_result_silent(seq, moment)


if __name__ == "__main__":
    unittest.main(verbosity=2)
