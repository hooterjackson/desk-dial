"""K3 section 8, row by row: when `ok` is sent and what it carries (VOC-D03, VOC-R08; C5-18)."""
import unittest

from cc5_support import Fixture, fail, queue_state


class ConfirmationTests(Fixture):
    def test_volume_is_silent(self):
        self.turn_to(40)
        self.tick(0.1)
        volume = self.one("volume")
        self.assertEqual(self.frame()["status"], "Setting…")
        self.c.complete(volume["request"], {**queue_state(volume=40), "_applied_volume": 40})
        self.assertIsNone(self.c.feedback)

    def test_volume_failure_shakes(self):
        self.turn_to(40)
        self.tick(0.1)
        self.complete("volume", error=fail("offline"))
        self.assertEqual(self.c.feedback["kind"], "err")

    def test_play_pause_is_silent_and_never_toasts(self):
        self.press(0)
        self.complete("transport", queue_state(playback="PAUSED_PLAYBACK", can_play=True, can_pause=False))
        self.assertIsNone(self.c.feedback)
        self.assertFalse(self.effects("toast"))
        self.assertIs(self.frame()["playing"], False)

    def test_skip_ok_is_verified_with_sweep_and_no_moment(self):
        self.tracks(2)
        self.press(3)
        self.complete("transport", queue_state(P=6, track_id="track-6"))
        self.assertEqual(self.c.feedback.get("skip"), 1)
        self.assertNotIn("moment", self.c.feedback)

    def test_start_ok_carries_started_and_the_accent(self):
        self.browse()
        self.press(3)
        self.complete("play_items", {**queue_state(), "_start": {"k": 9, "n": 9, "u": 0}})
        self.assertEqual((self.c.feedback["moment"], self.c.feedback["color"]), ("started", 0x102030))

    def test_play_next_is_verified_queued(self):
        self.browse()
        self.press(2)
        self.complete("play_next", queue_state())
        self.assertEqual(self.c.feedback["moment"], "queued")

    def test_seek_is_silent(self):
        self.seek()
        self.turn_to(20)
        self.tick(0.3)
        seek = self.one("seek")
        self.c.complete(seek["request"], {**queue_state(), "_applied_seek": 99})
        self.assertIsNone(self.c.feedback)

    def test_companion_shuffle_on_acceptance(self):
        self.upnext()
        self.ratings()
        self.press(1)
        job = self.one("shuffle_reorder")
        self.assertIsNone(self.c.feedback)
        self.c.progress(job["request"], {"phase": "accepted"})
        self.assertEqual(self.c.feedback["moment"], "shuffle")
        seq = self.c.feedback_seq
        self.c.complete(job["request"], queue_state(queue_revision="rev-2"))
        self.assertEqual(self.c.feedback_seq, seq, "no second moment at completion")

    def test_sonos_shuffle_on_verified_completion(self):
        self.publish(queue_state(P=5, T=80))
        self.upnext()
        self.ratings()
        self.press(1)
        self.assertIsNone(self.c.feedback)
        self.complete("set_shuffle", queue_state(P=5, T=80, shuffle=True, play_mode="SHUFFLE_NOREPEAT"))
        self.assertEqual(self.c.feedback["moment"], "shuffle")

    def test_like_on_verified_completion(self):
        self.upnext()
        self.ratings()
        self.turn_to(6)
        self.press(2)
        self.assertIsNone(self.c.feedback)
        self.complete("like", {"liked": True})
        self.assertEqual(self.c.feedback["moment"], "like")

    def test_snap_on_acceptance(self):
        self.open_windows()
        self.press(1)
        self.assertIsNone(self.c.feedback)
        self.c.snap_result("left", "accepted")
        self.assertEqual(self.c.feedback["moment"], "snap")

    def test_switch_confirmed_plain_ok(self):
        self.open_windows()
        self.press(3)
        self.assertIsNone(self.c.feedback)
        self.complete("windows_activate", True)
        self.assertEqual(self.c.feedback, {"kind": "ok", "seq": self.c.feedback_seq})

    def test_moments_never_carry_skip(self):
        self.browse()
        self.press(2)
        self.complete("play_next", queue_state())
        self.assertNotIn("skip", self.c.feedback)


class GroupChangedToneTests(Fixture):
    """Lead ruling R-j (phase 3, gatekeeper KD-4): `Speaker group changed` uses the `error` tone on
    whichever line shows it (Home `status`, else its `meta` twin, C5-56), for `group_changed_ms`
    2600 (C5-76), from a state poll, a start's own result and a volume write's own result."""

    def assert_copy(self, line, feedback=None):
        frame = self.frame()
        self.assertEqual((frame[line], frame[line + "Tone"]), ("Speaker group changed", "error"))
        if feedback is not None:
            self.assertEqual(self.c.feedback["kind"], feedback)
        self.tick(2.6)
        self.assertNotEqual(self.frame()[line], "Speaker group changed", "gone after group_changed_ms")

    def test_a_poll_on_home_uses_the_status_line(self):
        self.publish(queue_state(group="group-b"))
        self.assertEqual(self.c.transient.copy_id, "knob.status.group_changed")
        self.assertIsNone(self.c.feedback, "copy only, no err (C5-76)")
        self.assert_copy("status")

    def test_a_poll_elsewhere_uses_the_meta_twin(self):
        self.tracks(index=2)
        self.publish(queue_state(group="group-b"))
        self.assertEqual(self.c.transient.copy_id, "knob.meta.group_changed")
        self.assert_copy("meta")

    def test_a_start_that_fails_with_group_changed(self):
        self.browse()
        self.press(3)
        start = self.one("play_items")
        self.c.complete(start["request"], error=fail("group", outcome="group_changed"))
        self.assertEqual(self.c.screen.mode, "home")
        self.assert_copy("status", feedback="err")

    def test_a_volume_write_that_fails_with_group_changed(self):
        self.turn_to(40)
        self.tick(0.1)
        self.complete("volume", error=fail("group", outcome="group_changed"))
        self.assertEqual(self.c.transient.tone, "error")
        self.assertEqual(self.c.feedback["kind"], "err")


if __name__ == "__main__":
    unittest.main()
