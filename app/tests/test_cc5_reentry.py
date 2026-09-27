"""K3 section 6: the re-entry helper, input blackouts and the passive rule (C5-9, C5-10, C5-13, C5-14)."""
import unittest

from cc5_support import Fixture, Harness, queue_state, recent_page, window_result
from control_center.controller import PROFILES


class ReentryCauseTests(Fixture):
    def entries(self):
        return [e for e in self.effects() if e["kind"] == "device_enter"]

    def test_control_ids_are_monotonic_and_profiles_follow_the_mode(self):
        seen = []
        self.browse()
        seen.append((self.c.control_id, self.c.control()["profile"]))
        self.press(1)
        seen.append((self.c.control_id, self.c.control()["profile"]))
        self.press(0)
        self.press(0)
        self.tracks()
        seen.append((self.c.control_id, self.c.control()["profile"]))
        self.press(2)
        seen.append((self.c.control_id, self.c.control()["profile"]))
        ids = [s[0] for s in seen]
        self.assertEqual(ids, sorted(set(ids)))
        self.assertEqual([s[1] for s in seen], [PROFILES["recent"], PROFILES["explorer"], PROFILES["tracks"],
                                                "BINARIS BEER"])

    def test_explorer_tab_switch_reenters_at_190_ms(self):
        self.browse()
        self.press(1)
        self.c.drain()
        control = self.c.control_id
        self.press(2)
        self.assertEqual(self.c.control_id, control)
        self.tick(0.180)
        self.assertEqual(self.c.control_id, control)
        self.tick(0.015)
        self.assertEqual(self.c.control_id, control + 1)
        self.assertEqual(self.c.screen.explorer.source, "favourites")

    def test_turns_during_the_swap_are_ignored(self):
        self.browse()
        self.press(1)
        self.press(2)
        self.tick(0.05)
        self.turn_to(5)
        self.assertEqual(self.c.screen.index, 0)

    def test_overlay_play_goes_home_at_380_ms(self):
        self.browse()
        self.press(1)
        self.c.drain()
        self.press(3)
        self.tick(0.37)
        self.assertEqual(self.c.screen.mode, "explorer")
        self.tick(0.02)
        self.assertEqual(self.c.screen.mode, "home")

    def test_shuffle_reenters_at_200_ms_on_row_p_plus_1(self):
        self.upnext()
        self.ratings()
        control = self.c.control_id
        self.press(1)
        self.tick(0.19)
        self.turn_to(8)
        self.assertEqual(self.c.screen.index, 4, "turns ignored in [t0, t0 + 200)")
        self.tick(0.02)
        self.assertEqual(self.c.control_id, control + 1)
        self.assertEqual(self.c.screen.index, 5)  # index P = row P+1

    def test_skip_ok_reenters_neutral(self):
        self.tracks(2)
        self.press(3)
        control = self.c.control_id
        self.complete("transport", queue_state(P=6, track_id="track-6"))
        self.assertEqual((self.c.control_id, self.c.screen.index), (control + 1, 1))

    def test_seek_idle_exit_after_3000_ms(self):
        self.seek()
        self.tick(2.9)
        self.assertEqual(self.c.screen.mode, "seek")
        self.tick(0.2)
        self.assertEqual((self.c.screen.mode, self.c.screen.index), ("tracks", 1))

    def test_reconnect_reenters_home(self):
        self.browse()
        self.c.set_hardware(True)
        self.assertEqual(self.c.screen.mode, "home")

    def test_due_reentries_are_cancelled_when_their_screen_leaves(self):
        self.browse()
        self.press(1)
        self.press(2)                     # swap scheduled at +190
        self.hold()                       # leaves the explorer
        control = self.c.control_id
        self.tick(0.3)
        self.assertEqual((self.c.screen.mode, self.c.control_id), ("home", control))


class SnapTimingTests(Fixture):
    def test_advance_at_420_and_pair_close_at_820(self):
        self.open_windows()
        self.turn_to(2)
        self.tick(0.5)
        self.press(1)
        self.c.snap_result("left", "accepted")
        self.c.snap_result("left", "ok")
        self.tick(0.41)
        self.assertEqual(self.c.screen.index, 2)
        self.tick(0.02)
        self.assertEqual(self.c.screen.index, 3)
        self.press(2)
        self.c.snap_result("right", "accepted")
        self.c.snap_result("right", "ok")
        self.tick(0.81)
        self.assertEqual(self.c.screen.mode, "windows")
        self.tick(0.02)
        self.assertEqual(self.c.screen.mode, "home")

    def test_a_detent_cancels_the_advance(self):
        self.open_windows()
        self.press(1)
        self.c.snap_result("left", "accepted")
        self.tick(0.1)
        self.turn_to(3)
        self.c.snap_result("left", "ok")
        self.tick(0.5)
        self.assertEqual(self.c.screen.index, 3)


class PassiveRuleTests(Fixture):
    def test_growth_waits_400_ms_after_the_last_detent(self):
        self.press(1)
        self.complete("recent", recent_page(0, total=None, count=25, complete=False))
        self.turn_to(10)
        effect = self.pending("recent_lookahead")
        control = self.c.control_id
        self.c.complete(effect["request"], recent_page(25, total=None, count=25, complete=False))
        self.assertEqual(self.c.control_id, control, "deferred")
        self.assertEqual(self.frame()["ring"]["count"], 50, "frames already show the new content")
        self.tick(0.41)
        self.assertEqual(self.c.control_id, control + 1)
        self.assertEqual(self.c.bounds()[1], 49)

    def test_loaded_end_growth_reenters_at_once(self):
        self.press(1)
        self.complete("recent", recent_page(0, total=None, count=25, complete=False))
        self.turn_to(24)
        self.c.drain()
        effect = self.pending("recent_lookahead")
        control = self.c.control_id
        self.c.complete(effect["request"], recent_page(25, total=None, count=25, complete=False))
        self.assertEqual(self.c.control_id, control + 1)

    def test_upnext_queue_change_keeps_the_focus_by_identity(self):
        self.upnext()
        self.ratings()
        self.turn_to(7)                   # row 8, signature sig-8
        self.tick(1.0)
        self.publish(queue_state(queue_revision="rev-2", T=13))
        read = self.pending("queue_window")
        result = window_result(read["start"], read["count"], 13, revision="rev-2")
        for row in result["rows"]:        # one row inserted before the focus
            if row["row"] >= 3:
                row["signature"] = f"sig-{row['row'] - 1}"
        self.c.complete(read["request"], result)
        self.tick(0.5)
        self.assertEqual(self.c.screen.index, 8)


class EntryArtRuleTests(unittest.TestCase):
    """Section 6.3: an entry keeps the previous frame's artKey; the new one follows `ready`."""

    def test_entry_keeps_the_previous_cover(self):
        from types import SimpleNamespace
        h = Harness(self)
        h.runtime.device_connected = h.runtime.device_supported = True

        class Art:
            version = 1

            def cached(self, url, token=None, **kwargs):
                return SimpleNamespace(token=token, key="cover_" + str(token[1]), error="", rgb565=b"") if url else None

            def request(self, *a, **k): pass
            def clear(self): pass
            def poll(self): return []
            def close(self): pass
        h.sonos.state["artwork_url"] = "https://example.invalid/now.jpg"
        h.run(1)
        h.runtime.artwork = Art()
        h.c.set_hardware(True)
        h.runtime.dispatch()
        h.c.device_ready(h.c.control_id)
        h.runtime.poll()
        home_key = h.runtime.last_frame["artKey"]
        self.assertTrue(home_key.startswith("cover_"))
        h.device.commands.clear()
        for logical in (2, 0):                   # Tracks and back: the same identity (now playing)
            h.c.button(logical, h.c.control_id)
            h.runtime.dispatch()
            h.c.device_ready(h.c.control_id)
        h.c.button(1, h.c.control_id)            # Browse: the list is loading (no cover)
        h.runtime.dispatch()
        entries = [c[1] for c in h.device.commands if c[0] == "enter"]
        self.assertEqual(entries[-1]["frame"]["artKey"], home_key, "the entry keeps the previous cover")
        h.c.device_ready(h.c.control_id)
        h.runtime.poll()
        self.assertEqual(h.runtime.last_frame["artKey"], "", "the first frame after ready has the new one")


if __name__ == "__main__":
    unittest.main()
