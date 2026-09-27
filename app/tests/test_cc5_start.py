"""K3 section 8 starts: Recent (Home at once), explorer / Up next (380 ms); Starting…; the started
moment; partial playlists; failures; busy dims (sections 2.3, 5.1.2, 8, 9.2; K2 M16; C5-37)."""
import unittest

from cc5_support import Fixture, fail, queue_state


class RecentStartTests(Fixture):
    def start(self, index=0, **overrides):
        self.browse(overrides={index: overrides} if overrides else None)
        if index:
            self.turn_to(index)
        self.press(3)
        return self.one("play_items")

    def test_home_at_once_with_starting(self):
        start = self.start(3)
        self.assertEqual((start["source"], start["lenient"], start["item_kind"], start["item"]["id"]),
                         ("recent", False, "album", "album-3"))
        frame = self.frame()
        self.assertEqual((self.c.screen.mode, frame["status"], frame["activity"]), ("home", "Starting…", "pending"))
        self.assertFalse(frame["buttons"][0]["enabled"])
        self.assertNotIn("playing", frame, "omitted while a start is pending (K2 M16)")

    def test_ok_started_moment_wherever_the_knob_is(self):
        start = self.start(3)
        self.press(2)                        # the knob went to Tracks meanwhile
        self.c.complete(start["request"], {**queue_state(title="Promises"),
                                           "_start": {"k": 9, "n": 9, "u": 0, "name": "Album 3"}})
        self.assertEqual(self.c.feedback, {"kind": "ok", "seq": self.c.feedback_seq, "moment": "started",
                                           "color": 0x102033})
        self.assertEqual([t["text"] for t in self.effects("toast")], ["Playing Album 3"])

    def test_started_frame_omits_playing_once(self):
        start = self.start()
        self.c.complete(start["request"], {**queue_state(), "_start": {"k": 9, "n": 9, "u": 0}})
        first = self.frame()
        self.assertEqual(first["feedback"]["moment"], "started")
        self.assertNotIn("playing", first)
        self.assertIs(self.frame()["playing"], True)

    def test_partial_playlist(self):
        start = self.start(2, kind="playlist", title="PAPER LANTERN Ep. 1")
        self.assertTrue(start["lenient"])
        self.c.complete(start["request"], {**queue_state(), "_start": {"k": 33, "n": 34, "u": 1}})
        frame = self.frame()
        self.assertEqual(frame["status"], "Playing 33 of 34")
        self.assertAlmostEqual(self.c.transient.until - self.clock(), 3.0)
        self.assertEqual([t["text"] for t in self.effects("toast")], ["Playing 33 of 34 · 1 song unavailable"])

    def test_partial_plural(self):
        start = self.start(2, kind="playlist", title="Mix")
        self.c.complete(start["request"], {**queue_state(), "_start": {"k": 30, "n": 34, "u": 4}})
        self.assertEqual([t["text"] for t in self.effects("toast")], ["Playing 30 of 34 · 4 songs unavailable"])

    def test_album_blocked(self):
        start = self.start(1)
        self.c.complete(start["request"], error=fail("blocked", outcome="album_blocked", unavailable=True))
        frame = self.frame()
        self.assertEqual((frame["status"], frame["statusTone"]), ("Album unavailable", "error"))
        self.assertAlmostEqual(self.c.transient.until - self.clock(), 2.6)
        self.assertEqual(self.c.feedback["kind"], "err")
        self.assertEqual([t["text"] for t in self.effects("toast")], ["Album 1 can’t play · a song is unavailable"])

    def test_start_failed_including_the_staging_deadline(self):
        start = self.start(1)
        self.c.complete(start["request"], error=fail("timeout", outcome="start_failed"))
        self.assertEqual(self.frame()["status"], "Didn’t start")
        self.assertEqual([t["text"] for t in self.effects("toast")], ["Couldn’t start Album 1"])

    def test_busy_dims_while_starting(self):
        self.start()
        self.press(1)
        self.c.drain()
        self.pending("recent")
        from cc5_support import recent_page
        self.complete("recent", recent_page())
        frame = self.frame()
        self.assertFalse(frame["buttons"][2]["enabled"])
        self.assertFalse(frame["buttons"][3]["enabled"])
        self.press(3)
        self.assertEqual(self.transient(), "Starting…")
        self.press(0)
        self.tracks()
        self.assertFalse(self.frame()["buttons"][2]["enabled"], "Seek dims with starting")


class OverlayStartTests(Fixture):
    def test_explorer_start_toast_after_the_close(self):
        self.browse()
        self.press(1)
        self.c.drain()
        self.press(3)
        start = self.pending("play_items")
        self.assertEqual(start["source"], "explorer")
        self.tick(0.38)
        self.c.complete(start["request"], {**queue_state(), "_start": {"k": 9, "n": 9, "u": 0}})
        self.assertFalse(self.effects("toast"), "at max(close + 360 ms, the result)")
        self.tick(0.36)
        self.assertEqual([t["text"] for t in self.effects("toast")], ["Playing Album 0"])

    def early_result(self, surface, outcome):
        """WP5-R4: a cached start or a fast jump answers at t0 + 0.1, while the overlay is still
        closing. closed_at is the close (t0 + 380 ms), so the exit toast is due at
        max(t0 + 380 + 360 ms, result) = t0 + 740 ms (section 12.3), not dropped."""
        if surface == "explorer":
            self.browse()
            self.press(1)
        else:
            self.upnext()
        self.c.drain()
        t0 = self.clock()
        self.press(3)
        start = self.pending("play_items" if surface == "explorer" else "jump")
        self.tick(0.1)
        if outcome == "ok":
            self.c.complete(start["request"], {**queue_state(), "_start": {"k": 9, "n": 9, "u": 0}})
        else:
            self.c.complete(start["request"], error=fail("x", outcome="start_failed"))
        shown = []
        while self.clock() < t0 + 1.2:
            self.tick(0.025)
            shown += [(self.clock() - t0, t["exit"]) for t in self.effects("toast")]
        self.assertEqual(self.c.screen.mode, "home")
        self.assertEqual(len(shown), 1, shown)
        self.assertTrue(shown[0][1], "an exit toast")
        self.assertGreaterEqual(shown[0][0], 0.74 - 1e-9)
        self.assertLess(shown[0][0], 0.74 + 0.025 + 1e-9)

    def test_an_explorer_start_answered_before_the_close_toasts_after_it(self):
        self.early_result("explorer", "ok")

    def test_an_explorer_failure_answered_before_the_close_toasts_after_it(self):
        self.early_result("explorer", "failed")

    def test_an_upnext_jump_answered_before_the_close_toasts_after_it(self):
        self.early_result("upnext", "ok")

    def test_an_upnext_failure_answered_before_the_close_toasts_after_it(self):
        self.early_result("upnext", "failed")

    def test_late_result_toasts_at_once(self):
        self.browse()
        self.press(1)
        self.press(3)
        start = self.pending("play_items")
        self.tick(2.0)
        self.c.complete(start["request"], {**queue_state(), "_start": {"k": 9, "n": 9, "u": 0}})
        self.tick(0.0)
        self.assertEqual([(t["text"], t["exit"]) for t in self.effects("toast")], [("Playing Album 0", True)])

    def test_album_start_hold_every_kind(self):
        self.browse()
        self.press(3)
        start = self.pending("play_items")
        self.c.complete(start["request"], {**queue_state(playback="TRANSITIONING"), "_start": {"k": 1, "n": 1, "u": 0}})
        self.frame()
        self.publish(queue_state(playback="PAUSED_PLAYBACK"))
        self.assertNotIn("playing", self.frame())
        self.tick(10.1)
        self.assertIs(self.frame()["playing"], False)


if __name__ == "__main__":
    unittest.main()
