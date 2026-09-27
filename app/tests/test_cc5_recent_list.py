"""K3 section 5.2: the flat Recently Added list (U5; C5-1, C5-31, C5-61) and its frames."""
import unittest

from cc5_support import Fixture, Harness, fail, queue_state, recent_page


class VisitTests(Fixture):
    def test_browse_starts_a_new_visit_at_item_1(self):
        self.browse()
        self.turn_to(9)
        self.press(0)
        self.press(1)
        request = self.pending("recent")
        self.assertEqual((request["offset"], request["limit"], request["visit"]), (0, 25, None))
        self.assertEqual(self.c.screen.index, 0)

    def test_a_page_of_an_older_visit_never_commits(self):
        self.press(1)
        old = self.pending("recent")
        self.press(0)
        self.press(1)
        self.c.complete(old["request"], recent_page(0, 60))
        self.assertEqual(self.c.recent.items, [])
        self.assertEqual(self.c.recent.state, "loading")

    def test_the_explorer_back_keeps_the_visit(self):
        self.browse()
        visit = self.c.recent.visit
        self.press(1)
        self.press(0)
        self.assertEqual((self.c.recent.visit, self.c.screen.mode), (visit, "recent"))


class PagingTests(Fixture):
    def test_pages_of_25_and_16_ahead(self):
        self.browse()
        self.assertFalse(self.effects("recent_lookahead"))
        self.turn_to(8)                    # 24 - 8 = 16 left: still enough
        self.assertFalse([e for e in self.c.pending.values() if e["kind"].startswith("recent")])
        self.turn_to(9)
        request = self.pending("recent_lookahead")
        self.assertEqual((request["offset"], request["limit"], request["visit"]), (25, 25, 1))

    def test_an_unloaded_focus_asks_on_the_library_lane(self):
        self.browse(total=60)
        self.turn_to(40)                   # a fast spin past the prefetch (the total is known)
        self.assertEqual(self.pending("recent")["offset"], 25)

    def spin_past_the_lookahead_page(self):
        """WP5-R6: a prefetch is out on the lookahead lane, then a fast spin lands on an unloaded
        item: the same page is asked for on the library lane."""
        self.browse(total=100)
        self.turn_to(10)
        lookahead = self.pending("recent_lookahead")
        self.assertEqual(lookahead["offset"], 25)
        self.turn_to(30)
        library = self.pending("recent")
        self.assertEqual(library["offset"], 25)
        self.assertEqual(self.c.recent.inflight_lane, "library")
        self.assertEqual(self.frame()["meta"], "Loading…")
        return lookahead, library

    def test_an_unloaded_focus_moves_a_lookahead_page_to_the_library_lane(self):
        lookahead, library = self.spin_past_the_lookahead_page()
        self.c.complete(library["request"], recent_page(25, 100))
        self.assertEqual(self.frame()["title"], "Album 30")
        self.c.complete(lookahead["request"], recent_page(25, 100))
        self.assertEqual([i["id"] for i in self.c.recent.items], [f"album-{i}" for i in range(50)],
                         "the other copy is dropped by its offset, never appended twice")

    def test_the_lookahead_copy_landing_first_is_kept(self):
        lookahead, library = self.spin_past_the_lookahead_page()
        self.c.complete(lookahead["request"], recent_page(25, 100))
        self.assertEqual(self.frame()["title"], "Album 30")
        self.assertIsNone(self.c.recent.inflight, "the library copy no longer blocks the next page")
        self.turn_to(55)
        self.assertEqual(self.pending("recent")["offset"], 50)
        self.c.complete(library["request"], recent_page(25, 100))
        self.assertEqual(len(self.c.recent.items), 50)

    def test_a_failed_copy_waits_for_the_other(self):
        lookahead, library = self.spin_past_the_lookahead_page()
        self.c.complete(lookahead["request"], error=fail("boom"))
        self.assertEqual(self.c.recent.retry_at, 0.0, "no retry delay while the library copy is out")
        self.c.complete(library["request"], recent_page(25, 100))
        self.assertEqual(len(self.c.recent.items), 50)

    def test_a_copy_of_a_page_that_landed_is_not_wanted(self):
        self.browse(total=100)
        visit = self.c.recent.visit
        self.assertTrue(self.c.recent_wanted(visit))
        self.assertTrue(self.c.recent_wanted(visit, offset=25))
        self.assertFalse(self.c.recent_wanted(visit, offset=0))
        self.assertFalse(self.c.recent_wanted(visit - 1, offset=25))

    def test_total_known_gives_the_bounds_from_page_1(self):
        self.browse(total=60)
        self.assertEqual(self.c.bounds()[1], 59)
        self.turn_to(40)
        frame = self.frame()
        self.assertEqual((frame["title"], frame["meta"], frame["activity"]), ("", "Loading…", "idle"))
        ring = frame["ring"]
        self.assertEqual(ring["style"], "selection")
        self.assertEqual(ring["colors"][ring["index"] - ring["first"]], 0)

    def test_total_unknown_grows(self):
        self.press(1)
        self.complete("recent", recent_page(0, total=None, count=25, complete=False))
        self.assertEqual(self.c.bounds()[1], 24)
        self.turn_to(9)
        self.complete("recent_lookahead", recent_page(25, total=None, count=10, complete=True))
        self.tick(0.5)
        self.assertEqual(self.c.bounds()[1], 34)
        self.assertTrue(self.c.recent.complete)

    def test_end_meta(self):
        self.browse(total=20)
        self.turn_to(19)
        self.assertEqual(self.frame()["meta"], "20 / 20 · end")
        self.turn_to(18)
        self.assertEqual(self.frame()["meta"], "19 / 20")

    def test_a_failed_later_page_is_retried_later(self):
        self.browse(total=60)
        self.turn_to(10)
        self.complete("recent_lookahead", error=fail("boom"))
        self.assertEqual(self.c.recent.state, "ready")
        self.turn_to(11)
        self.assertFalse([e for e in self.c.pending.values() if e["kind"].startswith("recent")])
        self.tick(5.1)
        self.assertTrue([e for e in self.c.pending.values() if e["kind"].startswith("recent")])


class StateFrameTests(Fixture):
    def test_first_page_loading_is_off_plus_loading(self):
        self.press(1)
        frame = self.frame()
        self.assertEqual((frame["layout"], frame["heading"], frame["meta"], frame["activity"]),
                         ("recent", "RECENTLY ADDED", "Loading…", "loading"))
        self.assertEqual(frame["ring"]["style"], "off")
        self.assertEqual(frame["page"], 0)

    def test_loaded_item(self):
        self.browse(total=60)
        frame = self.frame()
        self.assertEqual((frame["title"], frame["subtitle"], frame["meta"]), ("Album 0", "Artist", "1 / 60"))
        self.assertNotIn("artDim", frame)
        ring = frame["ring"]
        self.assertEqual((ring["style"], ring["count"], ring["first"]), ("selection", 60, 0))
        self.assertEqual(ring["colors"][:2], [0x102030, 0x102031])
        self.assertNotIn("moreIndex", ring)
        self.turn_to(30)
        self.assertEqual(self.frame()["ring"]["first"], 20)   # clamp(index - 10, 0, count - 20)

    def test_kind_label_when_no_artist(self):
        self.browse(overrides={0: {"artist": "", "kind": "playlist"}})
        self.assertEqual(self.frame()["subtitle"], "Playlist")

    def test_unavailable_item_dims_art_only_there(self):
        self.browse(overrides={3: {"available": False}})
        self.turn_to(3)
        frame = self.frame()
        self.assertEqual((frame["titleTone"], frame["artDim"]), ("muted", True))
        self.assertEqual(frame["ring"]["unavailable"], 1 << 3)
        self.turn_to(4)
        self.assertNotIn("artDim", self.frame())

    def test_empty(self):
        self.press(1)
        self.complete("recent", recent_page(0, total=0, count=0, complete=True))
        frame = self.frame()
        self.assertEqual((frame["title"], frame["subtitle"], frame["meta"], frame["activity"]),
                         ("Nothing recently added", "Apple Music library", "", "idle"))
        self.assertEqual(frame["ring"]["style"], "off")

    def test_signin_and_error(self):
        for outcome, title, sub in (("signin_expired", "Apple Music sign-in expired", "Renew on your PC"),
                                    ("failed", "Library not loaded", "Home, then Browse")):
            with self.subTest(outcome=outcome):
                self.c.screen.mode = "home"
                self.press(1)
                self.complete("recent", error=fail("x", outcome=outcome))
                frame = self.frame()
                self.assertEqual((frame["title"], frame["subtitle"], frame["meta"], frame["metaTone"],
                                  frame["activity"]),
                                 (title, sub, "Windows still works", "secondary", "error"))
                self.assertEqual(frame["ring"]["style"], "off")

    def test_play_next_progress_owns_the_meta_and_the_comet(self):
        self.browse()
        self.press(2)
        frame = self.frame()
        self.assertEqual((frame["meta"], frame["activity"]), ("Finding songs…", "pending"))
        self.turn_to(5)
        self.assertEqual(self.frame()["meta"], "Finding songs…")

    def test_ring_colours_for_unloaded_entries_are_warm(self):
        self.browse(total=60)
        self.turn_to(24)
        ring = self.frame()["ring"]
        colours = ring["colors"]
        self.assertEqual(len(colours), 20)
        self.assertTrue(all(c == 0 for c in colours[25 - ring["first"]:]))

    def test_a_held_first_page_keeps_the_list_loading_and_asks_again(self):
        # A discarded first page (the simulator's `art = "list"`) is not a library error.
        self.press(1)
        self.complete("recent", error=fail("Simulated loading list: request discarded"))
        self.assertEqual(self.c.recent.state, "loading")
        self.assertEqual(self.frame()["meta"], "Loading…")
        self.tick(1.0)
        self.assertFalse([e for e in self.c.pending.values() if e["kind"] == "recent"])
        self.tick(4.1)
        self.assertEqual(self.pending("recent")["offset"], 0)


class BusyLookaheadLaneTests(unittest.TestCase):
    """WP5-R6 on the runtime's lanes: the lookahead lane is busy (its page queued behind other
    work), the knob spins onto an unloaded item, and the library lane loads the page."""

    def test_the_page_the_user_waits_for_is_loaded_on_the_library_lane(self):
        h = Harness(self)
        h.controls.recent = "many"
        h.run(1)
        h.press(1)
        h.runtime.library.run_all()
        h.runtime.poll()
        self.assertEqual(len(h.c.recent.items), 25)
        offsets = []
        original = h.apple.recent_page
        h.apple.recent_page = lambda offset=0, **kw: (offsets.append(offset), original(offset, **kw))[1]
        h.c.position(10, h.c.control_id)
        h.runtime.dispatch()
        kinds = sorted(e["kind"] for e in h.c.pending.values() if e["kind"].startswith("recent"))
        self.assertEqual(kinds, ["recent_lookahead"])
        h.c.position(30, h.c.control_id)            # the lookahead lane is never run: it is busy
        h.runtime.dispatch()
        self.assertEqual(h.frame()["meta"], "Loading…")
        h.runtime.library.run_all()
        h.runtime.poll()
        frame = h.frame()
        self.assertEqual(frame["title"], h.c.recent.items[30]["title"])
        self.assertEqual(frame["meta"], "31 / 100")
        h.runtime.lookahead.run_all()                # the lane frees up: its copy is no longer wanted
        h.runtime.poll()
        self.assertEqual(offsets, [25], "the queued lookahead copy never calls Apple")
        self.assertEqual(len(h.c.recent.items), 50)


if __name__ == "__main__":
    unittest.main()
