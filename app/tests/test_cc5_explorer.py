"""K3 section 5.3: the Music explorer (screen primary; the knob mirrors): open, tabs, per-source
positions, states, Play at 380 ms, Back, bumps and a refused open (C5-9, C5-30, C5-42, C5-55)."""
import unittest

from cc5_support import Fixture, fail, queue_state, recent_page


def playlists(n=3):
    return [{"id": f"pl-{i}", "title": f"Playlist {i}", "artist": "", "kind": "playlist", "available": True,
             "accent": 0x300000 + i, "favourite": True, "auto": i == 0, "art_template": ""} for i in range(n)]


class ExplorerCase(Fixture):
    def open(self, index=0):
        self.browse(total=60)
        if index:
            self.turn_to(index)
        self.c.drain()
        self.press(1)
        return self.effects()

    def meta_request(self, playlist):
        return next(e for e in self.c.pending.values() if e["kind"] == "playlist_meta" and e["playlist_id"] == playlist)

    def load_favourites(self, n=3):
        effect = self.pending("favourite_playlists")
        self.c.complete(effect["request"], playlists(n))


class OpenTests(ExplorerCase):
    def test_opens_at_the_recent_index(self):
        effects = self.open(7)
        opened = self.one("explorer_open", effects)
        self.assertEqual((opened["source"], opened["index"], opened["count"], opened["state"]), ("recent", 7, 60, "ready"))
        self.assertEqual((opened["items_first"], len(opened["items"])), (0, 24))
        self.assertTrue(all("_resource" not in item for item in opened["items"] if item))
        self.assertEqual((opened["control_min"], opened["sonos_available"]), (0, True))
        self.assertEqual((self.c.screen.mode, self.c.screen.index), ("explorer", 7))
        frame = self.frame()
        self.assertEqual((frame["layout"], frame["page"], frame["heading"]), ("explorer", 0, "RECENT"))

    def test_favourites_load_on_the_library_lane_without_a_cache(self):
        effects = self.open()
        load = self.one("favourite_playlists", effects)
        self.assertEqual((load["force"], load["lane"]), (True, "library"))

    def test_fresh_cache_is_used_stale_refreshes_on_lookahead(self):
        self.open()
        self.load_favourites()
        self.press(0)
        self.press(1)
        self.assertFalse(self.effects("favourite_playlists"))
        self.press(0)
        self.tick(601)
        self.c.last_knob_input = self.clock()
        self.press(1)
        refresh = self.one("favourite_playlists")
        self.assertEqual(refresh["lane"], "lookahead")

    def test_sonos_down_still_opens_with_play_dimmed(self):
        self.publish(queue_state(online=False))
        effects = self.open()
        self.assertFalse(self.one("explorer_open", effects)["sonos_available"])
        self.assertFalse(self.frame()["buttons"][3]["enabled"])
        self.press(3)
        self.assertEqual(self.transient(), "Sonos unavailable")


class TabTests(ExplorerCase):
    def test_switch_enters_at_the_remembered_favourite_by_id(self):
        self.open(4)
        self.load_favourites()
        self.press(2)
        source = self.one("explorer_source")
        self.assertEqual((source["source"], source["index"], source["state"], source["count"]), ("favourites", 0, "ready", 3))
        self.tick(0.2)
        self.turn_to(2)
        self.press(1)
        self.tick(0.2)
        self.assertEqual((self.c.screen.explorer.source, self.c.screen.index), ("recent", 4))
        self.press(2)
        self.tick(0.2)
        self.assertEqual(self.c.screen.index, 2, "focus remembered by playlist id")
        self.c.favourites.items.insert(0, dict(playlists(1)[0], id="pl-new", title="A new one"))
        self.press(1)
        self.tick(0.2)
        self.press(2)
        self.tick(0.2)
        self.assertEqual(self.c.screen.index, 3)

    def test_positions_of_the_old_control_are_discarded(self):
        self.open(4)
        self.load_favourites()
        self.press(2)
        old = self.c.control_id
        self.tick(0.05)
        self.c.position(1, old)
        self.tick(0.2)
        self.assertEqual(self.c.screen.index, 0)
        self.assertEqual(self.c.screen.explorer.index_by_source["recent"], 4)

    def test_active_tab_press_is_ignored(self):
        self.open()
        self.c.drain()
        self.press(1)
        self.assertFalse(self.effects())

    def test_favourites_frames(self):
        self.open()
        self.press(2)
        self.tick(0.2)
        frame = self.frame()
        self.assertEqual((frame["page"], frame["heading"], frame["meta"], frame["activity"]),
                         (1, "FAVOURITES", "Loading…", "loading"))
        self.assertEqual(frame["ring"]["style"], "off")
        self.load_favourites()
        meta = self.meta_request("pl-0")
        self.assertTrue(meta["duration"])
        self.assertFalse(self.meta_request("pl-1")["duration"])
        self.c.complete(meta["request"], {"id": "pl-0", "count": 34, "mosaic": [], "accent": 0x123456,
                                          "duration_ms": 7_500_000, "empty": False})
        frame = self.frame()
        self.assertEqual((frame["title"], frame["subtitle"], frame["meta"]), ("Playlist 0", "34 songs", "1 / 3"))
        self.assertEqual(frame["buttons"][2].get("lit"), "on")

    def test_empty_and_signin_favourites(self):
        self.open()
        self.c.complete(self.pending("favourite_playlists")["request"], [])
        self.press(2)
        self.tick(0.2)
        frame = self.frame()
        self.assertEqual((frame["title"], frame["subtitle"]), ("No favourites yet", "Star one in Music"))
        self.assertFalse(frame["buttons"][3]["enabled"])

    def test_signin_state_block(self):
        self.open()
        self.c.complete(self.pending("favourite_playlists")["request"], None, fail("x", outcome="signin_expired", status=401))
        self.press(2)
        source = self.one("explorer_source")
        self.assertEqual(source["state"], "signin")

    def test_empty_playlist_is_unavailable(self):
        self.open()
        self.load_favourites()
        self.press(2)
        self.tick(0.2)
        meta = self.meta_request("pl-0")
        self.c.complete(meta["request"], {"id": "pl-0", "count": 0, "mosaic": [], "accent": 0, "empty": True})
        frame = self.frame()
        self.assertEqual((frame["titleTone"], frame.get("artDim")), ("muted", True))
        self.press(3)
        self.assertEqual(self.transient(), "Not available")


class StateChangeTests(ExplorerCase):
    def test_a_state_change_while_open_goes_out_in_highlight(self):
        self.press(1)                      # Recent loading
        self.c.drain()
        self.press(1)                      # the explorer opens while the list loads
        opened = self.one("explorer_open")
        self.assertEqual((opened["state"], opened["count"]), ("loading", None))
        self.complete("recent", recent_page(0, 60))
        highlight = [e for e in self.effects() if e["kind"] == "explorer_highlight"][-1]
        self.assertEqual((highlight["state"], highlight["count"]), ("ready", 60))
        self.assertEqual(len(highlight["items"]), 17)

    def test_bumps(self):
        self.open()
        self.c.drain()
        self.c.limit(-1, self.c.control_id)
        self.assertEqual(self.one("explorer_highlight")["bump"], -1)


class PlayTests(ExplorerCase):
    def test_play_at_380_ms_then_home_starting(self):
        self.open(3)
        self.c.drain()
        self.press(3)
        effects = self.effects()
        start = self.one("play_items", effects)
        close = self.one("explorer_close", effects)
        self.assertEqual((close["reason"], close["close_at_ms"]), ("play", 380))
        self.assertEqual(start["item"]["id"], "album-3")
        self.tick(0.38)
        frame = self.frame()
        self.assertEqual((self.c.screen.mode, frame["status"], frame["activity"]), ("home", "Starting…", "pending"))
        self.assertNotIn("playing", frame)

    def test_click_action_is_button_4(self):
        self.open(2)
        self.c.drain()
        self.c.presenter_event({"kind": "click_action", "surface": "explorer"})
        self.assertEqual(self.one("play_items", self.c.effects[:])["item"]["id"], "album-2")

    def test_refused_returns_to_recent_with_a_shake(self):
        self.open(5)
        self.c.presenter_event({"kind": "refused", "surface": "explorer", "reason": "device"})
        self.assertEqual((self.c.screen.mode, self.c.screen.index), ("recent", 5))
        self.assertEqual(self.c.feedback["kind"], "err")
        self.assertEqual(self.transient(), "Couldn’t open on screen")
        self.assertEqual(self.c.transient.tone, "error")
        self.assertFalse(self.effects("explorer_close"))


if __name__ == "__main__":
    unittest.main()
