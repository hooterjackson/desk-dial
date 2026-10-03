"""DD-BUG-023 (controller side): outcome ``signin_needed`` (Apple Music never connected on this PC)
gets its own connect copy on the knob, apart from ``signin_expired``.

Recent and Favourites keep their ``signin`` state (every gate that reads it is unchanged) and record
whether it was never connected; their frames, dims, Like and Play next read the matching copy.
Headless: the controller fixture only; no Tk, no ports, no network.
"""
import unittest

from cc5_support import Fixture, fail
from control_center.controller import COPY, _needs_login
from test_cc5_explorer import ExplorerCase


class NeedsLoginTests(unittest.TestCase):
    def test_a_never_connected_message_is_not_an_expired_sign_in(self):
        self.assertFalse(_needs_login("connect apple music in companion settings first."))
        self.assertTrue(_needs_login("apple music authorization expired or access was denied."))

    def test_copy(self):
        self.assertEqual(COPY["knob.title.signin_needed"], "Connect Apple Music")
        self.assertEqual(COPY["knob.sub.signin_needed"], "Sign in on your PC")
        self.assertEqual(COPY["knob.meta.signin_needed"], "Not signed in")
        self.assertEqual(COPY["knob.meta.like.signin_needed"], "Not signed in")
        self.assertEqual(COPY["toast.like.signin_needed"], "Apple Music not connected · open Settings")
        for key in ("knob.meta.signin_needed", "knob.meta.like.signin_needed"):
            self.assertNotIn("expired", COPY[key].lower())
            self.assertLessEqual(len(COPY[key]), len(COPY["knob.meta.signin_expired"]))


class RecentSigninNeededTests(Fixture):
    def open_recent(self, outcome, status=None):
        self.c.screen.mode = "home"
        self.press(1)
        self.complete("recent", error=fail("Connect Apple Music in companion settings first.",
                                           outcome=outcome, status=status))

    def test_never_connected_shows_the_connect_prompt(self):
        self.open_recent("signin_needed")
        self.assertEqual(self.c.recent.state, "signin")
        frame = self.frame()
        self.assertEqual((frame["title"], frame["subtitle"], frame["meta"], frame["activity"]),
                         ("Connect Apple Music", "Sign in on your PC", "Windows still works", "error"))
        self.assertEqual([b["enabled"] for b in frame["buttons"]], [True, False, False, False])
        for slot in (1, 2, 3):
            with self.subTest(slot=slot):
                self.press(slot)
                self.assertEqual(self.c.transient.copy_id, "knob.meta.signin_needed")
                self.assertEqual(self.c.transient.tone, "error")
                self.assertEqual(self.c.feedback["kind"], "err")

    def test_expired_keeps_the_expired_copy(self):
        self.open_recent("signin_expired", status=401)
        frame = self.frame()
        self.assertEqual((frame["title"], frame["subtitle"]), ("Apple Music sign-in expired", "Renew on your PC"))
        self.press(3)
        self.assertEqual(self.c.transient.copy_id, "knob.meta.signin_expired")

    def test_a_later_expiry_replaces_the_connect_prompt(self):
        self.open_recent("signin_needed")
        self.c.screen.mode = "home"
        self.press(0)
        self.open_recent("signin_expired", status=401)
        self.assertEqual(self.frame()["title"], "Apple Music sign-in expired")


class FavouritesSigninNeededTests(ExplorerCase):
    def test_favourites_never_connected(self):
        self.open()
        self.c.complete(self.pending("favourite_playlists")["request"], None, fail("x", outcome="signin_needed"))
        self.assertEqual((self.c.favourites.state, self.c.favourites.signin_needed), ("signin", True))
        self.press(2)
        self.assertEqual(self.one("explorer_source")["state"], "signin")
        self.tick(0.2)
        self.assertFalse(self.frame()["buttons"][3]["enabled"])
        self.press(3)
        self.assertEqual(self.c.transient.copy_id, "knob.meta.signin_needed")
        frame = {}
        self.c._frame_list_favourites(frame, 0)
        self.assertEqual((frame["title"], frame["subtitle"]), ("Connect Apple Music", "Sign in on your PC"))

    def test_favourites_expired(self):
        self.open()
        self.c.complete(self.pending("favourite_playlists")["request"], None,
                        fail("x", outcome="signin_expired", status=401))
        self.assertFalse(self.c.favourites.signin_needed)
        frame = {}
        self.c._frame_list_favourites(frame, 0)
        self.assertEqual(frame["title"], "Apple Music sign-in expired")


class LikeSigninNeededTests(Fixture):
    def test_like_never_connected(self):
        self.upnext()
        self.ratings()
        self.turn_to(6)
        self.press(2)
        self.complete("like", error=fail("x", outcome="signin_needed"))
        self.assertEqual(self.transient(), "Not signed in")
        self.assertFalse(self.c.music_signin_expired, "never connected is not an expired sign-in")
        self.assertEqual(self.c.screen.upnext.armed_toast, "toast.like.signin_needed")

    def test_like_expired_unchanged(self):
        self.upnext()
        self.ratings()
        self.turn_to(6)
        self.press(2)
        self.complete("like", error=fail("x", outcome="signin_expired", status=401))
        self.assertEqual(self.transient(), "Sign-in expired")
        self.assertTrue(self.c.music_signin_expired)


class PlayNextSigninNeededTests(Fixture):
    def test_play_next_never_connected(self):
        self.browse()
        self.press(2)
        job = self.one("play_next")
        self.c.complete(job["request"], error=fail("x", outcome="signin_needed"))
        frame = self.frame()
        self.assertEqual((frame["meta"], frame["metaTone"]), ("Not signed in", "error"))


if __name__ == "__main__":
    unittest.main()
