"""K3 section 16: every simulator control reaches its state end to end through the runtime and the
controller (no I/O: the sim clock runs every slow option synchronously)."""
import unittest

from cc5_support import Harness
from control_center.simulation import PLAYLISTS, SimControls, SimulatedDevice


class SimCase(unittest.TestCase):
    def setUp(self):
        self.controls = SimControls()
        self.h = Harness(self, self.controls)
        self.h.run(1)

    def poll_state(self):
        self.h.clock.advance(1.1)
        self.h.run(2)

    def press(self, *logicals):
        for logical in logicals:
            self.h.press(logical)
            self.h.run(2)

    def home(self):
        while self.h.c.screen.mode != "home":
            self.h.c.hold(0, self.h.c.control_id)
            self.h.runtime.dispatch()
        self.h.run(1)


class SourceTests(SimCase):
    def test_every_source_class(self):
        for source, upnext in (("queue", True), ("airplay", False), ("radio", False), ("linein", False),
                               ("none", False)):
            with self.subTest(source=source):
                self.controls.source = source
                self.poll_state()
                self.press(2)                       # Tracks
                self.assertEqual(self.h.frame()["buttons"][1]["enabled"], upnext)
                self.home()

    def test_play_modes(self):
        self.controls.play_mode = "SHUFFLE"
        self.poll_state()
        self.press(2)
        self.h.c.position(2, self.h.c.control_id)
        self.assertEqual(self.h.frame()["subtitle"], "Next: shuffle pick")
        self.home()
        self.controls.play_mode = "REPEAT_ALL"
        self.poll_state()
        self.assertEqual(self.h.c.state["repeat"], "all")


class PlayNextTests(SimCase):
    def test_outcomes(self):
        for mode, toast in (("ok", "Queued next · Promises"), ("slow", "Queued next · Promises"),
                            ("live", "Queued next · Promises"), ("proto", "Queued next · Promises"),
                            ("partial", "Partly queued · check the Sonos queue"),
                            ("nothing", "Couldn’t queue Promises · nothing added"),
                            ("changed", "Song changed · try again")):
            with self.subTest(pn=mode):
                self.controls.pn = mode
                self.h.apple._cache.clear()
                self.home()
                self.press(1, 2)
                self.assertEqual(self.h.toasts.shown[-1], (toast, False))
                ok = toast.startswith("Queued next")
                self.assertEqual(self.h.c.feedback.get("moment") if ok else self.h.c.feedback["kind"],
                                 "queued" if ok else "err")


class StartTests(SimCase):
    def start_item(self, index):
        self.home()
        self.press(1)
        self.h.c.position(index, self.h.c.control_id)
        self.h.run(1)
        self.press(3)
        self.h.run(2)

    def test_ok_slow_fail_blocked(self):
        for mode, status in (("ok", ""), ("slow", ""), ("fail", "Didn’t start"), ("blocked", "Album unavailable")):
            with self.subTest(start=mode):
                self.controls.start = mode
                self.start_item(0)
                frame = self.h.frame()
                self.assertEqual(self.h.c.screen.mode, "home")
                self.assertEqual(frame["status"], status)

    def test_memento_mori_plays_33_of_34(self):
        items = self.h.apple._library()
        index = next(i for i, item in enumerate(items) if item["title"] == PLAYLISTS[1][0])
        self.start_item(index)
        self.assertEqual(self.h.frame()["status"], "Playing 33 of 34")
        self.assertEqual(self.h.toasts.shown[-1][0], "Playing 33 of 34 · 1 song unavailable")


class SeekTests(SimCase):
    def test_outcomes(self):
        for mode, ok in (("ok", True), ("slow", True), ("slow5", True), ("live", True), ("noresume", False),
                         ("fail", False)):
            with self.subTest(seek=mode):
                self.controls.seek = mode
                self.home()
                self.press(2, 2)                    # Tracks, Seek
                self.assertEqual(self.h.c.screen.mode, "seek")
                self.h.c.position(self.h.c.screen.index + 2, self.h.c.control_id)
                self.h.clock.advance(0.3)
                self.h.run(3)
                meta = self.h.frame()["meta"]
                if ok:
                    self.assertTrue(meta.startswith("of "), meta)
                else:
                    self.assertEqual(meta, "Didn’t jump · try again")
                self.assertEqual(len(self.h.sonos.seeks), 1, "never resent")
                self.h.sonos.seeks.clear()


class UpNextTests(SimCase):
    def open(self):
        self.home()
        self.press(2, 1)

    def test_normal_foreign_loading_longshuffle(self):
        self.open()
        self.assertEqual(self.h.c.screen.mode, "upnext")
        self.assertFalse(self.h.c.screen.upnext.loading)
        self.home()
        self.controls.upnext = "foreign"
        self.open()
        rows = self.h.c.upnext_view()["rows"]
        self.assertTrue(any(row.get("catalog") is False for row in rows))
        self.home()
        self.controls.upnext = "loading"
        self.open()
        self.assertEqual(self.h.frame()["meta"], "Loading queue…")
        self.home()
        self.controls.upnext = "longshuffle"            # the control alone (WP5-R10): > 60 upcoming
        self.poll_state()
        self.open()
        upnext = self.h.c.screen.upnext
        self.assertGreater(upnext.T - upnext.P, 60)
        self.assertEqual(upnext.regime, "sonos")
        self.press(1)                                   # U > 60: Sonos shuffle
        self.h.clock.advance(0.25)
        self.h.run(2)
        self.assertEqual(self.h.frame()["title"], "Shuffled by Sonos")
        self.assertEqual(self.h.sonos.calls[-1], ("set_shuffle", True))
        self.home()
        self.controls.upnext = "normal"                 # back to the album
        self.controls.play_mode = "NORMAL"
        self.poll_state()
        self.assertEqual(self.h.c.state["queue_length"], 12)

    def test_like_states(self):
        for row, (mode, meta) in enumerate((("ok", "Liked"), ("expired", "Sign-in expired"),
                                            ("fail", "Didn’t save · try again")), start=6):
            with self.subTest(like=mode):
                self.controls.like = mode
                self.open()
                self.h.c.position(row, self.h.c.control_id)
                self.press(2)
                self.assertEqual(self.h.frame()["meta"], meta)
        self.controls.like = "loading"
        self.open()
        self.h.c.position(8, self.h.c.control_id)
        self.assertEqual(self.h.frame()["buttons"][2]["enabled"], False)

    def test_companion_shuffle_and_restore(self):
        self.open()
        before = [row["song_id"] for row in self.h.sonos.queue]
        self.press(1)
        self.h.clock.advance(0.25)
        self.h.run(3)
        self.assertTrue(self.h.sonos.record)
        self.assertEqual(self.h.frame()["buttons"][1].get("lit"), "on")
        self.press(1)
        self.h.clock.advance(0.25)
        self.h.run(3)
        self.assertEqual([row["song_id"] for row in self.h.sonos.queue], before)


class FavouritesTests(SimCase):
    def test_real_empty_many(self):
        for mode, count in (("real", 2), ("empty", 0), ("many", 32)):
            with self.subTest(favs=mode):
                self.controls.favs = mode
                self.home()
                self.h.c.favourites.state = "none"
                self.h.c.favourites.items = []
                self.press(1, 1, 2)
                self.h.clock.advance(0.2)
                self.h.run(2)
                self.assertEqual(self.h.c.favourites.count(), count)


class SnapAndStageTests(SimCase):
    def test_snap_outcomes(self):
        for mode, assigned in (("ok", True), ("hung", False), ("move", False), ("fit", False),
                               ("integrity", False)):
            with self.subTest(snap=mode):
                self.controls.snap = mode
                self.home()
                self.h.c.open_windows()
                self.h.runtime.dispatch()
                self.press(1)
                self.assertEqual(self.h.c.screen.windows.left is not None, assigned)

    def test_stage_options(self):
        for mode, expected in (("ok", "explorer"), ("refused", "recent"), ("display", "recent")):
            with self.subTest(stage=mode):
                self.controls.stage = mode
                self.home()
                self.press(1, 1)
                self.assertEqual(self.h.c.screen.mode, expected)


class ArtTests(SimCase):
    """WP5-R10: each `art` value reaches its K4 section 13.6 state through the item art keys."""

    def recent_items(self, art):
        self.controls.art = art
        self.home()
        self.press(1)
        return self.h.c.recent.items

    def explorer_open(self):
        if self.h.c.screen.mode != "explorer":
            self.press(1)
        return self.h.stage.of("explorer_open")[-1]

    def test_missing_art_uses_the_generated_accent(self):
        from control_center.artwork import gen_sleeve
        items = self.recent_items("missing")
        item = items[0]
        self.assertEqual(item["art_template"], "")
        self.assertEqual(self.h.frame()["ring"]["colors"][0],
                         gen_sleeve(item["title"], item["artist"])["ring_accent"])

    def test_full_small_loading_keys(self):
        for art, scheme, size in (("full", "art", 1200), ("small", "art", 400), ("loading", "loading", 1200)):
            with self.subTest(art=art):
                item = self.recent_items(art)[0]
                self.assertTrue(item["art_template"].startswith(f"simulation://{scheme}/"))
                self.assertEqual(item["art_max"], size)
                self.assertNotEqual(item["art_bg"], 0)
                opened = self.explorer_open()
                self.assertEqual(opened["items"][0]["art_max"], size, "the presenter receives the keys")

    def test_mixed_is_the_real_library_mix(self):
        items = self.recent_items("mixed")
        sizes = {item["art_max"] for item in items}
        self.assertEqual(sizes, {0, 300, 400, 1200})
        self.assertEqual((items[4]["art_max"], items[10]["art_max"], items[7]["art_template"]), (400, 300, ""))

    def test_up_next_rows_follow_the_art_value(self):
        self.controls.art = "small"
        self.home()
        self.press(2, 1)
        rows = [row for row in self.h.c.upnext_view()["rows"] if row.get("catalog")]
        self.assertTrue(rows)
        self.assertTrue(all(row["art_max"] == 400 for row in rows))

    def test_the_simulator_never_causes_a_download(self):
        from control_center.artwork import template_url
        for art in ("full", "mixed", "small", "loading"):
            for item in self.recent_items(art):
                self.assertEqual(template_url(item["art_template"], 240), "", "the allowlist rejects it")

    def test_list_holds_the_explorer_lists_loading(self):
        self.controls.art = "list"
        self.home()
        self.press(1)
        self.assertEqual(self.h.c.recent.state, "loading")
        self.assertEqual(self.h.frame()["meta"], "Loading…")
        opened = self.explorer_open()
        self.assertEqual((opened["state"], opened["count"]), ("loading", None))  # K3 11.1: None while loading
        self.h.clock.advance(1.0)
        self.h.run(2)
        self.assertEqual(self.h.c.recent.state, "loading", "held: still loading")
        self.controls.art = "full"                       # the list arrives when the control changes
        self.h.clock.advance(5.1)
        self.h.run(3)
        self.assertEqual(self.h.c.recent.state, "ready")
        self.assertEqual(len(self.h.c.recent.items), 25)


class ConnectionTests(SimCase):
    def test_connected_and_disconnected_from_the_control(self):
        # WP5-R10: SimControls.connected drives the device bridge fake (section 16 "PC connection").
        runtime = self.h.runtime
        runtime.device = SimulatedDevice(self.controls)
        self.h.run(2)
        self.assertTrue(runtime.device_connected)
        self.assertTrue(self.h.c.hardware and self.h.c.ready, "claimed, entered and ready")
        self.press(1)
        self.assertEqual(self.h.c.screen.mode, "recent")
        self.controls.connected = False
        self.h.run(1)
        self.assertEqual(self.h.c.screen.mode, "home")
        self.assertFalse(runtime.device_connected)
        self.controls.connected = True
        self.h.run(2)
        self.assertTrue(runtime.device_connected)
        self.assertEqual(self.h.c.last_reentry_cause, "reconnect")
        enters = [command for command in runtime.device.commands if command[0] == "enter"]
        self.assertGreaterEqual(len(enters), 2)


if __name__ == "__main__":
    unittest.main()
