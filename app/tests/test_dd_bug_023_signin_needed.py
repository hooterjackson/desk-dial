"""DD-BUG-023: a user who never connected Apple Music must not be told the sign-in expired.

The client raises NotSignedIn (``signin_needed`` True) when no Music user token is stored, before
any request; a token Apple refuses (401/403) is a plain AppleMusicError. ``apple_outcome`` keeps
NotSignedIn at ``signin_expired`` unless asked to split it (``split_signin=True``), so until the
controller has connect-prompt copy for ``signin_needed`` every screen keeps the sign-in prompt
instead of falling through to a generic failure (review of DD-BUG-023).
Headless: an in-memory recording session and the controller fixture; no network, no Tk.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.apple_music import AppleMusicClient, AppleMusicError, NotSignedIn, apple_outcome  # noqa: E402
from control_center.runtime import failure  # noqa: E402
from cc5_support import Fixture  # noqa: E402
from test_cc_apple_v7 import CREDENTIALS, FAVOURITE, RecordingSession, Resp  # noqa: E402
from test_cc_music import FakeClock  # noqa: E402
from test_cc5_explorer import ExplorerCase  # noqa: E402

OPS = ("like", "ratings", "recent", "play_items", "play_next", "favourite_playlists")


def make(credentials, routes=None):
    session, clock = RecordingSession(routes), FakeClock()
    return AppleMusicClient(credentials, session=session, clock=clock.now, sleep=clock.sleep), session


def not_signed_in():
    apple, _ = make({})
    try:
        apple._get("/v1/me/storefront")
    except NotSignedIn as error:
        return error
    raise AssertionError("NotSignedIn expected")


class SigninNeededClientTests(unittest.TestCase):
    def test_never_authorised_is_told_apart_from_expired(self):
        for credentials in ({}, {"developer_token": "dev"}, {"developer_token": "dev", "music_user_token": ""}):
            with self.subTest(credentials=sorted(credentials)):
                apple, session = make(credentials)
                with self.assertRaises(NotSignedIn) as raised:
                    apple._get("/v1/me/storefront")
                self.assertIsInstance(raised.exception, AppleMusicError, "callers catching AppleMusicError still do")
                self.assertIsNone(raised.exception.status)
                self.assertTrue(raised.exception.signin_needed)
                for op in OPS:
                    self.assertEqual(apple_outcome(raised.exception, op, split_signin=True), "signin_needed", op)
                    self.assertEqual(apple_outcome(raised.exception, op), "signin_expired",
                                     f"{op}: unsplit callers keep the sign-in prompt")
                self.assertEqual(session.calls, [], "no request without a user token")

    def test_a_refused_token_is_signin_expired_split_or_not(self):
        for status in (401, 403):
            with self.subTest(status=status):
                apple, _ = make(CREDENTIALS, {("GET", "/v1/me/storefront"): Resp(status),
                                              ("POST", FAVOURITE): Resp(status)})
                with self.assertRaises(AppleMusicError) as raised:
                    apple._get("/v1/me/storefront")
                self.assertNotIsInstance(raised.exception, NotSignedIn)
                self.assertFalse(getattr(raised.exception, "signin_needed", False))
                self.assertEqual(apple_outcome(raised.exception, "like"), "signin_expired")
                self.assertEqual(apple_outcome(raised.exception, "like", split_signin=True), "signin_expired")

    def test_the_runtime_failure_splits_the_signin_outcome(self):
        # The controller has connect copy for signin_needed now, so the runtime asks for the split.
        error = not_signed_in()
        for op in OPS:
            self.assertEqual(failure(error, op=op).outcome, "signin_needed", op)


class SigninNeededControllerTests(ExplorerCase):
    """No regression on screens that read the outcome: a never-connected user still gets the
    sign-in state/copy, never the generic error branch."""

    def test_favourites_list_shows_the_signin_state(self):
        self.open()
        self.c.complete(self.pending("favourite_playlists")["request"], None,
                        failure(not_signed_in(), op="favourite_playlists"))
        self.press(2)
        self.assertEqual(self.one("explorer_source")["state"], "signin")
        self.assertEqual(self.c.favourites.state, "signin")


class SigninNeededLikeTests(Fixture):
    def test_like_shows_the_signin_copy_not_the_generic_failure(self):
        self.upnext()
        self.ratings()
        self.turn_to(6)
        self.press(2)
        self.complete("like", error=failure(not_signed_in(), op="like"))
        self.assertEqual(self.transient(), "Not signed in")
        self.assertFalse(self.c.music_signin_expired, "never connected is not an expired sign-in")


if __name__ == "__main__":
    unittest.main()
