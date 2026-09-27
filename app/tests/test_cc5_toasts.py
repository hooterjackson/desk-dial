"""K3 section 12: toast service rules, the catalogue, exit-toast arming and balloons (C5-26, C5-36)."""
import unittest

from cc5_support import Fixture, Harness, fail, queue_state


class ServiceRuleTests(Fixture):
    def test_dropped_while_an_overlay_is_open(self):
        self.browse()
        self.press(2)                       # Play next out
        self.press(1)                       # the explorer is open when it lands
        self.c.drain()
        self.complete("play_next", queue_state())
        self.assertFalse(self.effects("toast"))

    def test_dropped_while_the_picker_is_opening(self):
        self.tracks(2)
        self.press(3)
        self.press(0)
        self.c.open_windows()
        self.complete("transport", queue_state(P=6, track_id="track-6"))
        self.assertFalse(self.effects("toast"))

    def test_exit_toast_360_ms_after_the_close(self):
        self.open_windows()
        self.press(3)
        self.complete("windows_activate", True)
        self.tick(0.35)
        self.assertFalse(self.effects("toast"))
        self.tick(0.02)
        self.assertEqual([(t["text"], t["exit"]) for t in self.effects("toast")], [("App1 · Window 1", True)])

    def test_exit_toast_dropped_when_another_overlay_is_open_at_that_moment(self):
        self.open_windows()
        self.press(3)
        self.complete("windows_activate", True)
        self.open_windows()
        self.tick(0.4)
        self.assertFalse(self.effects("toast"))

    def test_no_toast_for_play_pause_back_or_volume(self):
        self.press(0)
        self.complete("transport", queue_state(playback="PAUSED_PLAYBACK"))
        self.browse()
        self.press(0)
        self.turn_to(35)
        self.tick(0.2)
        self.complete("volume", {**queue_state(volume=35), "_applied_volume": 35})
        self.assertFalse(self.effects("toast"))

    def test_arming_dropped_by_non_back_closes(self):
        for reason in ("hold", "idle", "lock", "sleep", "group", "foreground", "display", "device"):
            with self.subTest(reason=reason):
                self.upnext()
                self.ratings()
                self.c.music_signin_expired = True
                self.turn_to(6)
                self.press(2)
                if reason == "hold":
                    self.hold()
                elif reason in ("display", "device"):
                    self.c.presenter_event({"kind": "closed", "surface": "upnext", "reason": reason})
                else:
                    self.c.close_overlay(reason)
                self.tick(0.5)
                self.assertFalse(self.effects("toast"))
                self.c.music_signin_expired = False
                self.c.screen.mode = "home"
                self.c.drain()


class BalloonTests(Fixture):
    def test_failures_without_a_toast_keep_the_notice(self):
        self.press(0)
        self.complete("transport", error=fail("Sonos said no"))
        self.assertEqual(self.c.notice, "Sonos said no")

    def test_failures_with_a_toast_do_not_balloon(self):
        self.browse()
        self.press(2)
        self.complete("play_next", error=fail("x", outcome="nothing_added"))
        self.assertEqual(self.c.notice, "")

    def test_no_balloon_while_an_overlay_is_open(self):
        self.turn_to(40)
        self.tick(0.1)
        self.open_windows()
        self.complete("volume", error=fail("offline"))
        self.assertEqual(self.c.notice, "")


class RuntimeToastTests(unittest.TestCase):
    def test_toasts_reach_the_toast_service(self):
        h = Harness(self)
        h.run(1)
        h.press(2)                          # Tracks
        h.c.position(2, h.c.control_id)
        h.press(3)
        h.run(3)
        self.assertEqual(h.toasts.shown[-1][1], False)
        self.assertTrue(h.toasts.shown[-1][0].startswith("Next · "))


if __name__ == "__main__":
    unittest.main()
