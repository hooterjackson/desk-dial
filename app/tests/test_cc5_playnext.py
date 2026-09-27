"""K3 section 9.3 on the controller side: gates, progress meta ([r2.2] `Finding songs…` until the
first verified insert, then `Queueing… {k} of {n}`), results, failures (C5-21, C5-66, C5-69, C5-71)."""
import unittest

from cc5_support import Fixture, Harness, fail, queue_state
from control_center.simulation import SimControls


class ProgressMetaTests(Fixture):
    def start(self):
        self.browse()
        self.press(2)
        return self.one("play_next")

    def test_payload(self):
        job = self.start()
        self.assertEqual((job["item"]["id"], job["name"], job["item_kind"], job["expected_track_id"]),
                         ("album-0", "Album 0", "album", "track-5"))

    def test_finding_songs_until_the_first_insert(self):
        job = self.start()
        seen = []

        def meta():
            frame = self.frame()
            seen.append(frame["meta"])
            self.assertEqual(frame["activity"], "pending", "the comet never gaps")
        meta()
        self.c.progress(job["request"], {"phase": "resolving", "n": 9})
        meta()
        self.c.progress(job["request"], {"phase": "inserting", "k": 0, "n": 9})
        meta()
        for k in range(1, 10):
            self.c.progress(job["request"], {"phase": "inserting", "k": k, "n": 9})
            meta()
        self.assertEqual(seen[:3], ["Finding songs…"] * 3)
        self.assertEqual(seen[3:5], ["Queueing… 1 of 9", "Queueing… 2 of 9"])
        self.assertNotIn("Queueing… 0 of 9", seen)

    def test_ok(self):
        job = self.start()
        self.c.complete(job["request"], {**queue_state(T=21), "_inserted": {"start_row": 6, "song_ids": ["1"]}})
        frame = self.frame()
        self.assertEqual((frame["meta"], frame["activity"]), ("Queued next", "idle"))
        self.assertAlmostEqual(self.c.transient.until - self.clock(), 1.5)
        self.assertEqual(self.c.feedback, {"kind": "ok", "seq": self.c.feedback_seq, "moment": "queued"})
        self.assertEqual([t["text"] for t in self.effects("toast")], ["Queued next · Album 0"])

    def test_failure_outcomes(self):
        cases = (("nothing_added", "Nothing added · retry", "Couldn’t queue Album 0 · nothing added"),
                 ("partial", "Partly queued", "Partly queued · check the Sonos queue"),
                 ("song_changed", "Song changed · retry", "Song changed · try again"),
                 ("sonos_shuffle_on", "Shuffle on · turn it off", "Shuffle is on · turn it off to play next"))
        for outcome, meta, toast in cases:
            with self.subTest(outcome=outcome):
                job = self.start()
                self.c.complete(job["request"], error=fail(outcome, outcome=outcome))
                frame = self.frame()
                self.assertEqual((frame["meta"], frame["metaTone"]), (meta, "error"))
                self.assertAlmostEqual(self.c.transient.until - self.clock(), 2.4)
                self.assertEqual(self.c.feedback["kind"], "err")
                self.assertEqual([t["text"] for t in self.effects("toast")], [toast])
                self.press(0)
                self.c.drain()

    def test_not_queue_source_per_class(self):
        job = self.start()
        self.c.complete(job["request"], error=fail("x", outcome="not_queue_source", source="airplay"))
        self.assertEqual(self.frame()["meta"], "AirPlay · use Play")
        self.assertEqual([t["text"] for t in self.effects("toast")], ["Not playing from the queue · use Play"])

    def test_a_stale_progress_is_ignored(self):
        job = self.start()
        self.c.complete(job["request"], {**queue_state()})
        self.c.progress(job["request"], {"phase": "inserting", "k": 3, "n": 9})
        self.assertIsNone(self.c.play_next_job)

    def test_no_toast_while_an_overlay_is_open(self):
        job = self.start()
        self.press(1)                       # the explorer opened meanwhile
        self.c.drain()
        self.c.complete(job["request"], {**queue_state()})
        self.assertFalse(self.effects("toast"))


class RuntimePlayNextTests(unittest.TestCase):
    def setUp(self):
        self.controls = SimControls()
        self.h = Harness(self, self.controls)
        self.h.run(1)
        self.h.press(1)
        self.h.run(2)

    def test_uncached_resolves_then_inserts_with_progress(self):
        metas = []
        original = self.h.c.progress

        def spy(request, payload):
            original(request, payload)
            metas.append((payload.get("phase"), payload.get("k"), self.h.frame()["meta"]))
        self.h.c.progress = spy
        self.h.press(2)
        self.h.run(3)
        self.assertEqual(metas[0][0], "resolving")
        self.assertEqual(metas[0][2], "Finding songs…")
        self.assertEqual(metas[1][2], "Queueing… 1 of 9")
        self.assertEqual(self.h.apple.resolve_calls, 1)
        self.assertEqual(self.h.frame()["meta"], "Queued next")
        self.assertEqual(self.h.toasts.shown[-1], ("Queued next · Promises", False))
        self.assertEqual(self.h.runtime.ledger.playnext[0].song_ids[:2], ["1400000000", "1400000001"])

    def test_a_pre_resolved_item_makes_no_lookup(self):
        self.h.apple.resolve(self.h.c.recent.items[0])
        calls = self.h.apple.resolve_calls
        phases = []
        original = self.h.c.progress
        self.h.c.progress = lambda request, payload: (phases.append(payload.get("phase")), original(request, payload))
        self.h.press(2)
        self.h.run(3)
        self.assertEqual(self.h.apple.resolve_calls, calls)
        self.assertEqual(phases[0], "inserting")

    def test_sonos_shuffle_refusal_comes_from_the_dim(self):
        self.controls.play_mode = "SHUFFLE_NOREPEAT"
        self.h.clock.advance(1.1)            # the next 1 s state poll reads it
        self.h.run(1)
        self.h.press(2)
        self.assertEqual(self.h.frame()["meta"], "Shuffle on · turn it off")
        self.assertEqual(self.h.toasts.shown[-1], ("Shuffle is on · turn it off to play next", False))

    def test_simulated_failures(self):
        for mode, meta in (("nothing", "Nothing added · retry"), ("partial", "Partly queued"),
                           ("changed", "Song changed · retry")):
            with self.subTest(mode=mode):
                self.controls.pn = mode
                self.h.press(2)
                self.h.run(3)
                self.assertEqual(self.h.frame()["meta"], meta)


if __name__ == "__main__":
    unittest.main()
