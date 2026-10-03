"""K3 section 9.8 Apple Music client (WP6): the guarded write helper, Like on the favourites
POST with the ratings read-back (C5-62, C5-64), add-only for good (no DELETE of any kind,
[r2.2] C5-67), ratings, catalog_songs, the
favourite-playlists recipe, the flat Recently Added pager, resolve (own-params pager,
leniency, deadline, cache, join, pre-resolution) and playlist_meta.

Every request goes to an in-memory recording session on a fake clock; no network.
"""
from copy import deepcopy
from pathlib import Path
import json
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import apple_music as AM  # noqa: E402
from control_center.apple_music import (  # noqa: E402
    AppleMusicClient, AppleMusicError, LikeNotConfirmed, MusicUnavailable, NotCatalog, ResolveTimeout,
    UnlikeUnavailable, apple_outcome, art_keys,
)
from test_cc_music import FakeClock  # noqa: E402

API = AppleMusicClient.API
CREDENTIALS = {"developer_token": "dev", "music_user_token": "user"}
SONG = "1445981467"
FAVOURITE = f"/v1/me/favorites?ids[songs]={SONG}"


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self.body = status, body
        self.content = b"" if body is None else json.dumps(body).encode()

    def json(self):
        if self.body is None:
            raise ValueError("no body")
        return deepcopy(self.body)


class RecordingSession:
    """Routes ``(method, path)`` (writes: the path with its literal query) to a Resp, a 200 body,
    or a callable(params) returning either; records every request."""

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.calls = []

    def _handle(self, method, url, params, kwargs):
        path = url[len(API):] if url.startswith(API) else url
        self.calls.append({"method": method, "path": path, "params": dict(params or {}), **kwargs})
        route = self.routes.get((method, path))
        if route is None:
            return Resp(404, {"errors": [{"code": "40400"}]})
        value = route(dict(params or {})) if callable(route) else route
        return value if isinstance(value, Resp) else Resp(200, value)

    def get(self, url, params=None, **kwargs):
        return self._handle("GET", url, params, kwargs)

    def request(self, method, url, **kwargs):
        return self._handle(method, url, None, kwargs)


def client(routes=None, *, clock=None):
    session = RecordingSession(routes)
    clock = clock or FakeClock()
    return AppleMusicClient(CREDENTIALS, session=session, clock=clock.now, sleep=clock.sleep), session, clock


def rating_after(clock, start_offset, value=1):
    """A ratings route: no rating until ``start_offset`` s after the route was made, then ``value``."""
    ready = clock.now() + start_offset

    def route(params):
        if clock.now() >= ready and value is not None:
            return {"data": [{"id": params["ids"], "type": "ratings", "attributes": {"value": value}}]}
        return {"data": []}
    return route


# ---------------------------------------------------------------------------------- _send
class SendTests(unittest.TestCase):
    def test_headers_redirects_timeout_and_empty_202_204(self):
        for status in (202, 204):
            with self.subTest(status=status):
                apple, session, _ = client({("POST", FAVOURITE): Resp(status)})
                self.assertIsNone(apple._send("POST", FAVOURITE, expected=(200, 202, 204)))
                call, = session.calls
                self.assertEqual(call["headers"], {"Authorization": "Bearer dev", "Music-User-Token": "user",
                                                   "Accept": "application/json"})
                self.assertEqual((call["allow_redirects"], call["timeout"]), (False, 8.0))
                self.assertNotIn("json", call)
                self.assertNotIn("data", call)

    def test_errors_carry_the_status_for_get_and_send(self):
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                apple, _, _ = client({("GET", "/v1/me/storefront"): Resp(status),
                                      ("POST", FAVOURITE): Resp(status)})
                with self.assertRaises(AppleMusicError) as raised:
                    apple._get("/v1/me/storefront")
                self.assertEqual(raised.exception.status, status)
                with self.assertRaises(AppleMusicError) as raised:
                    apple._send("POST", FAVOURITE, expected=(202,))
                self.assertEqual(raised.exception.status, status)

    def test_the_write_helper_allows_only_the_favourites_post(self):
        apple, session, _ = client()
        refused = [("PUT", f"/v1/me/ratings/songs/{SONG}", None), ("DELETE", f"/v1/me/ratings/songs/{SONG}", None),
                   ("POST", f"/v1/me/ratings/songs/{SONG}", None), ("PATCH", FAVOURITE, None),
                   ("POST", f"/v1/me/favorites?ids[albums]={SONG}", None),
                   ("POST", f"/v1/me/favorites?ids[songs]={SONG},1", None),
                   ("POST", f"/v1/me/library?ids[songs]={SONG}", None),
                   ("POST", FAVOURITE, {"type": "rating", "attributes": {"value": -1}}),
                   # [r2.2] C5-67: the favourites DELETE is refused too, whatever is asked.
                   ("DELETE", FAVOURITE, None), ("delete", FAVOURITE, None),
                   ("DELETE", "/v1/me/favorites", None), ("DELETE", "/v1/me/ratings/songs", None)]
        for method, path, body in refused:
            with self.subTest(method=method, path=path):
                with self.assertRaises(AppleMusicError):
                    apple._send(method, path, json=body, expected=(200, 202, 204))
        self.assertEqual(session.calls, [], "refused before any request")

    def test_the_module_no_longer_says_read_only(self):
        self.assertNotIn("Read-only", AM.__doc__.splitlines()[0])


# ---------------------------------------------------------------------------------- like / unlike
class LikeTests(unittest.TestCase):
    def test_like_posts_the_favourite_then_reads_the_rating_every_250_ms_until_1(self):
        clock = FakeClock()
        apple, session, _ = client({("POST", FAVOURITE): Resp(202),
                                    ("GET", "/v1/me/ratings/songs"): rating_after(clock, 1.0)}, clock=clock)
        start = clock.now()
        self.assertEqual(apple.like(SONG), {"liked": True})
        post, *reads = session.calls
        self.assertEqual((post["method"], post["path"], post["params"]), ("POST", FAVOURITE, {}))
        self.assertEqual([(c["method"], c["path"], c["params"]) for c in reads],
                         [("GET", "/v1/me/ratings/songs", {"ids": SONG})] * 4)
        self.assertEqual(clock.sleeps, [0.25] * 4)
        self.assertAlmostEqual(clock.now() - start, 1.0)

    def test_a_read_back_that_never_shows_1_fails_at_4_s(self):
        clock = FakeClock()
        apple, session, _ = client({("POST", FAVOURITE): Resp(202),
                                    ("GET", "/v1/me/ratings/songs"): {"data": []}}, clock=clock)
        start = clock.now()
        with self.assertRaises(LikeNotConfirmed) as raised:
            apple.like(SONG)
        self.assertAlmostEqual(clock.now() - start, 4.0)
        self.assertEqual(len(session.calls), 1 + 16)
        self.assertEqual(apple_outcome(raised.exception, "like"), "failed")

    def test_like_errors(self):
        for status, error, outcome in ((404, NotCatalog, "not_catalog"), (401, AppleMusicError, "signin_expired"),
                                       (403, AppleMusicError, "signin_expired"), (429, AppleMusicError, "rate_limited"),
                                       (405, AppleMusicError, "failed"), (400, AppleMusicError, "failed")):
            with self.subTest(status=status):
                apple, session, _ = client({("POST", FAVOURITE): Resp(status)})
                with self.assertRaises(error) as raised:
                    apple.like(SONG)
                self.assertEqual(apple_outcome(raised.exception, "like"), outcome)
                self.assertEqual(len(session.calls), 1, "no read-back after a refused POST")
        apple, session, _ = client()
        with self.assertRaises(NotCatalog):
            apple.like("not-a-song")
        self.assertEqual(session.calls, [])

    def test_a_refused_favourites_post_is_logged_by_status_only(self):
        # K3 section 9.8.2: 400/405 on the POST → failed, "logged by status only".
        for status in (400, 405, 500):
            with self.subTest(status=status):
                apple, _, _ = client({("POST", FAVOURITE): Resp(status, {"errors": [{"code": "40012"}]})})
                with self.assertLogs(AM.__name__, level="WARNING") as logs:
                    with self.assertRaises(AppleMusicError):
                        apple.like(SONG)
                self.assertEqual(len(logs.records), 1)
                self.assertIn(str(status), logs.output[0])
                for secret in (SONG, "40012", "user", "dev", "favorites"):
                    self.assertNotIn(secret, logs.output[0])
        for status in (401, 404, 429):   # mapped outcomes of their own: nothing to log here
            with self.subTest(status=status):
                apple, _, _ = client({("POST", FAVOURITE): Resp(status)})
                with self.assertNoLogs(AM.__name__, level="WARNING"):
                    with self.assertRaises(AppleMusicError):
                        apple.like(SONG)

    def test_add_only_is_final_and_unlike_sends_nothing(self):
        # [r2.2] C5-67: the constant stays for the tests; the favorites_delete branch, the
        # settings.json override and unlike_unsupported are not built.
        self.assertEqual(AM.UNLIKE_STRATEGY, "add_only")
        for withdrawn in ("UNLIKE_STRATEGIES", "effective_unlike_strategy", "UnlikeUnsupported"):
            self.assertFalse(hasattr(AM, withdrawn), withdrawn)
        with self.assertRaises(TypeError, msg="no unlike_strategy parameter to wire from settings"):
            AppleMusicClient(CREDENTIALS, session=RecordingSession(), unlike_strategy="favorites_delete")
        clock = FakeClock()
        apple, session, _ = client({("DELETE", FAVOURITE): Resp(204),
                                    ("GET", "/v1/me/ratings/songs"): {"data": []}}, clock=clock)
        self.assertFalse(hasattr(apple, "unlike_strategy"))
        apple.unlike_strategy = "favorites_delete"   # even a stray attribute changes nothing
        with self.assertRaises(UnlikeUnavailable) as raised:
            apple.unlike(SONG)
        self.assertEqual(session.calls, [])
        self.assertEqual(clock.sleeps, [], "no read-back either")
        self.assertEqual(apple_outcome(raised.exception, "unlike"), "failed")

    def test_no_outcome_is_ever_unlike_unsupported(self):
        for status in (None, 400, 404, 405, 500):
            with self.subTest(status=status):
                for op in ("like", "unlike", "ratings"):
                    self.assertNotEqual(apple_outcome(AppleMusicError("x", status=status), op), "unlike_unsupported")
        self.assertEqual(apple_outcome(AppleMusicError("x", status=400), "like"), "failed")

    def test_a_recording_session_never_sees_a_delete_or_a_rating_write(self):
        # K3 section 17.2 / 9.10 [r2.2]: a recording session proves no DELETE of any kind is ever
        # sent, and no request ever PUTs or DELETEs /v1/me/ratings/... or carries value -1.
        clock = FakeClock()
        routes = {("POST", FAVOURITE): Resp(202), ("DELETE", FAVOURITE): Resp(204),
                  ("DELETE", f"/v1/me/ratings/songs/{SONG}"): Resp(204),
                  ("GET", "/v1/me/ratings/songs"): rating_after(clock, 0.5),
                  ("GET", "/v1/me/storefront"): {"data": [{"id": "ca"}]},
                  ("GET", "/v1/catalog/ca/songs"): {"data": []}}
        apple, session, _ = client(routes, clock=clock)
        self.assertEqual(apple.like(SONG), {"liked": True})
        for attempt in (lambda: apple.unlike(SONG),
                        lambda: apple._send("DELETE", FAVOURITE, expected=(200, 202, 204)),
                        lambda: apple._send("DELETE", f"/v1/me/ratings/songs/{SONG}", expected=(204,)),
                        lambda: apple._send("PUT", f"/v1/me/ratings/songs/{SONG}", expected=(200,))):
            with self.assertRaises(AppleMusicError):
                attempt()
        apple.ratings([SONG, "1"])
        apple.catalog_songs([SONG])
        calls = session.calls
        self.assertTrue(calls)
        self.assertEqual({call["method"] for call in calls}, {"GET", "POST"})
        for call in calls:
            if call["method"] != "GET":
                self.assertEqual(call["path"], FAVOURITE)
                self.assertNotIn("json", call)
                self.assertNotIn("data", call)
        self.assertFalse(any("-1" in json.dumps(call.get("params")) for call in calls))


# ---------------------------------------------------------------------------------- ratings, catalog
class RatingsAndCatalogTests(unittest.TestCase):
    def test_ratings_batches_of_100_unrated_absent_and_404_none(self):
        pages = []

        def route(params):
            batch = params["ids"].split(",")
            pages.append(len(batch))
            return {"data": [{"id": i, "type": "ratings", "attributes": {"value": 1 if int(i) % 2 else -1}}
                             for i in batch[:3]]}
        apple, session, _ = client({("GET", "/v1/me/ratings/songs"): route})
        ids = [str(1000 + n) for n in range(150)]
        result = apple.ratings(ids)
        self.assertEqual(pages, [100, 50])
        self.assertEqual(result, {"1000": -1, "1001": 1, "1002": -1, "1100": -1, "1101": 1, "1102": -1})
        apple, _, _ = client({("GET", "/v1/me/ratings/songs"): Resp(404, {"errors": []})})
        self.assertEqual(apple.ratings(["1", "2"]), {})
        apple, _, _ = client({("GET", "/v1/me/ratings/songs"): {"data": []}})
        self.assertEqual(apple.ratings(["1"]), {})

    def test_liked_states_value_1_is_liked_every_other_answer_is_not(self):
        # [WP6-r22] The heart-state read (K3 section 9.7.2, C5-64): liked = (value == 1); an id
        # absent from the answer is False; a failed read raises (the caller leaves None).
        def route(params):
            values = {"11": 1, "12": -1, "13": 2}
            return {"data": [{"id": i, "type": "ratings", "attributes": {"value": values[i]}}
                             for i in params["ids"].split(",") if i in values]}
        apple, session, _ = client({("GET", "/v1/me/ratings/songs"): route})
        states = apple.liked_states(["11", "12", "13", "14", None, "", "l.abc", "11"])
        self.assertEqual(states, {"11": True, "12": False, "13": False, "14": False})
        self.assertEqual(session.calls[0]["params"], {"ids": "11,12,13,14"},
                         "rows without a catalog id are never sent (C5-43: not in Apple Music)")
        self.assertEqual(AM.liked_states(["1", "2"], {"1": 1}), {"1": True, "2": False})
        apple, session, _ = client()
        self.assertEqual(apple.liked_states([None, "x"]), {})
        self.assertEqual(session.calls, [], "nothing to ask")
        apple, _, _ = client({("GET", "/v1/me/ratings/songs"): Resp(404, {"errors": []})})
        self.assertEqual(apple.liked_states(["1"]), {"1": False}, "a 404 batch: none rated")
        for status, outcome in ((401, "signin_expired"), (429, "rate_limited"), (500, "failed")):
            with self.subTest(status=status):
                apple, _, _ = client({("GET", "/v1/me/ratings/songs"): Resp(status)})
                with self.assertRaises(AppleMusicError) as raised:
                    apple.liked_states(["1"])
                self.assertEqual(apple_outcome(raised.exception, "ratings"), outcome)

    def test_the_four_row_heart_states(self):
        # R22 CH §1 / K4 S5-34 precedence: not in Apple Music → not known yet → liked / not liked.
        self.assertEqual(AM.heart_state(catalog=True, liked=True), "liked")
        self.assertEqual(AM.heart_state(catalog=True, liked=False), "not_liked")
        self.assertEqual(AM.heart_state(catalog=True, liked=None), "unknown")
        for liked in (True, False, None):
            self.assertEqual(AM.heart_state(catalog=False, liked=liked), "not_catalog")
        self.assertEqual(AM.heart_state(catalog=None, liked=None), "unknown", "the catalog batch not landed")
        self.assertEqual(AM.heart_state(catalog=None, liked=True), "liked")

    def catalog_song(self, identifier, **attributes):
        base = {"name": f"Song {identifier}", "artistName": "Artist", "albumName": "Album", "trackNumber": 3,
                "discNumber": 1, "durationInMillis": 245000, "releaseDate": "1982-06-21",
                "url": f"https://music.apple.com/us/album/album/900?i={identifier}",
                "artwork": {"url": "https://is1-ssl.mzstatic.com/image/thumb/x/{w}x{h}bb.jpg", "width": 1400,
                            "height": 1200, "bgColor": "1d1d1f", "textColor1": "f2e9e1"}}
        base.update(attributes)
        return {"id": str(identifier), "type": "songs", "attributes": base}

    def test_catalog_songs_shape_missing_ids_and_no_in_favorites(self):
        apple, session, _ = client({("GET", "/v1/me/storefront"): {"data": [{"id": "us"}]},
                                    ("GET", "/v1/catalog/us/songs"): {"data": [self.catalog_song(11)]}})
        result = apple.catalog_songs(["11", "12"])
        row = result["11"]
        self.assertEqual({k: row[k] for k in ("catalog", "album", "track_number", "disc_number", "duration_ms",
                                              "duration_s", "art_template", "art_max", "art_bg", "art_ink",
                                              "accent", "release_year")},
                         {"catalog": True, "album": "Album", "track_number": 3, "disc_number": 1,
                          "duration_ms": 245000, "duration_s": 245,
                          "art_template": "https://is1-ssl.mzstatic.com/image/thumb/x/{w}x{h}bb.jpg",
                          "art_max": 1200, "art_bg": 0x1D1D1F, "art_ink": 0xF2E9E1, "accent": 0x1D1D1F,
                          "release_year": 1982})
        self.assertEqual(row["art"], {"template": row["art_template"], "width": 1400, "height": 1200,
                                      "bgColor": 0x1D1D1F, "textColor1": 0xF2E9E1})
        self.assertEqual(row["url"], "https://music.apple.com/us/album/album/900?i=11")
        self.assertEqual(result["12"], {"catalog": False})
        request = [c for c in session.calls if c["path"] == "/v1/catalog/us/songs"][0]
        self.assertEqual(request["params"], {"ids": "11,12"})
        self.assertFalse(any("extend" in c["params"] for c in session.calls), "no extend=inFavorites (C5-64)")
        apple.catalog_songs(["13"])
        self.assertEqual(sum(c["path"] == "/v1/me/storefront" for c in session.calls), 1, "storefront once")

    def test_catalog_songs_batches_of_catalog_batch_and_song_form_urls(self):
        # K3 section 1.2: 50 ids per request (the H5 parse bench; 300 ids held the GIL ~2.3 ms).
        batches = []

        def route(params):
            batches.append(len(params["ids"].split(",")))
            return {"data": [self.catalog_song(params["ids"].split(",")[0],
                                               url="https://music.apple.com/us/song/x/1")]}
        apple, _, _ = client({("GET", "/v1/me/storefront"): {"data": [{"id": "us"}]},
                              ("GET", "/v1/catalog/us/songs"): route})
        result = apple.catalog_songs([str(n) for n in range(1, 351)])
        self.assertEqual(AppleMusicClient.CATALOG_BATCH, 50)
        self.assertEqual(batches, [50] * 7)
        self.assertEqual(result["1"]["url"], "", "a song-form link is not a Sonos share link")

    def test_art_keys_reject_unknown_templates(self):
        self.assertEqual(art_keys({"url": "https://is1-ssl.mzstatic.com/a/{w}x{h}{c}.{f}"}),
                         {"art_template": "", "art_max": 0, "art_bg": 0, "art_ink": 0})
        self.assertEqual(art_keys(None)["art_template"], "")
        self.assertEqual(art_keys({"url": "https://is1-ssl.mzstatic.com/a/{w}x{h}bb.jpg"})["art_max"], 0)


# ---------------------------------------------------------------------------------- favourites
def playlist(identifier, name, flag=None, **attributes):
    values = {"name": name, "canEdit": True, "hasCatalog": True, "lastModifiedDate": "2026-06-21T00:00:00Z",
              "artwork": {"url": "https://is1-ssl.mzstatic.com/p/{w}x{h}bb.jpg", "width": 1080, "height": 1080}}
    if name is None:
        values.pop("name")
    if flag is not None:
        values["inFavorites"] = flag
    values.update(attributes)
    return {"id": identifier, "type": "library-playlists", "attributes": values}


class FavouritePlaylistsTests(unittest.TestCase):
    PATH = AppleMusicClient.PLAYLISTS

    def test_the_fast_path_is_accepted_and_pages_with_our_own_params(self):
        def route(params):
            if params.get("filter[inFavorites]") == "true":
                if params.get("offset") is None:
                    return {"data": [playlist("p.2", "PAPER LANTERN Ep. 1", True, canEdit=False)],
                            "next": self.PATH + "?filter%5BinFavorites%5D=true&offset=1"}
                return {"data": [playlist("p.1", "Favorite Songs", True, canEdit=False, hasCatalog=False)]}
            raise AssertionError("no full scan when the fast path is accepted")
        apple, session, _ = client({("GET", self.PATH): route})
        items = apple.favourite_playlists()
        self.assertEqual([i["title"] for i in items], ["Favorite Songs", "PAPER LANTERN Ep. 1"])
        self.assertEqual([c["params"] for c in session.calls],
                         [{"limit": 100, "extend": "inFavorites", "filter[inFavorites]": "true"},
                          {"limit": 100, "extend": "inFavorites", "filter[inFavorites]": "true", "offset": 1}])
        favourite_songs = items[0]
        self.assertEqual((favourite_songs["auto"], favourite_songs["kind"], favourite_songs["resource_type"],
                          favourite_songs["can_edit"], favourite_songs["has_catalog"]),
                         (True, "playlist", "library-playlists", False, False))
        self.assertFalse(items[1]["auto"])
        self.assertEqual(items[1]["art_max"], 1080)

    def test_a_rejected_fast_path_runs_the_full_scan(self):
        for fast in ({"data": [playlist("p.2", "B", True), playlist("p.3", "C", False)]},   # filter ignored
                     {"data": [playlist("p.2", "B")]},                                      # extend ignored
                     {"data": []},                                                          # empty
                     Resp(400, {"errors": [{"code": "40000"}]})):                         # an error
            with self.subTest(fast=str(fast)[:40]):
                def route(params, fast=fast):
                    if "filter[inFavorites]" in params:
                        return fast
                    return {"data": [playlist("p.2", "B", True), playlist("p.3", "C", False),
                                     playlist("p.9", None, True)], "meta": {"total": 3}}
                apple, _, _ = client({("GET", self.PATH): route})
                items = apple.favourite_playlists()
                self.assertEqual([(i["id"], i["title"]) for i in items], [("p.2", "B"), ("p.9", "Untitled playlist")])

    def test_the_full_scan_concludes_none_only_with_every_flag_present(self):
        def route(params):
            if "filter[inFavorites]" in params:
                return {"data": []}
            return {"data": [playlist("p.2", "B", False)], "meta": {"total": 1}}
        apple, _, _ = client({("GET", self.PATH): route})
        self.assertEqual(apple.favourite_playlists(), [])

    def test_missing_flags_fall_back_to_the_ratings(self):
        def route(params):
            if "filter[inFavorites]" in params:
                return Resp(500)
            return {"data": [playlist("p.2", "Beta"), playlist("p.3", "alpha")], "meta": {"total": 2}}
        ratings = {"data": [{"id": "p.3", "type": "ratings", "attributes": {"value": 1}},
                            {"id": "p.2", "type": "ratings", "attributes": {"value": -1}}]}
        apple, session, _ = client({("GET", self.PATH): route,
                                    ("GET", "/v1/me/ratings/library-playlists"): ratings})
        self.assertEqual([i["title"] for i in apple.favourite_playlists()], ["alpha"])
        ratings_call = [c for c in session.calls if c["path"] == "/v1/me/ratings/library-playlists"][0]
        self.assertEqual(ratings_call["params"], {"ids": "p.2,p.3"})

    def test_a_total_mismatch_rescans_once(self):
        scans = []

        def route(params):
            if "filter[inFavorites]" in params:
                return {"data": []}
            scans.append(1)
            rows = [playlist("p.2", "B", True)] + ([playlist("p.3", "C", True)] if len(scans) > 1 else [])
            return {"data": rows, "meta": {"total": 2}}
        apple, _, _ = client({("GET", self.PATH): route})
        self.assertEqual([i["id"] for i in apple.favourite_playlists()], ["p.2", "p.3"])
        self.assertEqual(len(scans), 2)

    def test_signin_and_rate_limit_raise_without_a_full_scan(self):
        for status in (401, 403, 429):
            with self.subTest(status=status):
                apple, session, _ = client({("GET", self.PATH): Resp(status)})
                with self.assertRaises(AppleMusicError) as raised:
                    apple.favourite_playlists()
                self.assertEqual(raised.exception.status, status)
                self.assertEqual(len(session.calls), 1)

    def test_folders_are_walked_when_a_listing_holds_one(self):
        folder = {"id": "f.1", "type": "library-playlist-folders", "attributes": {"name": "Folder"}}

        def route(params):
            if "filter[inFavorites]" in params:
                return {"data": []}
            return {"data": [playlist("p.2", "B", False), folder], "meta": {"total": 2}}
        children = {"data": [playlist("p.7", "Inside", True)]}
        apple, session, _ = client({("GET", self.PATH): route,
                                    ("GET", "/v1/me/library/playlist-folders/f.1/children"): children})
        self.assertEqual([i["id"] for i in apple.favourite_playlists()], ["p.7"])
        walk = [c for c in session.calls if "children" in c["path"]][0]
        self.assertEqual(walk["params"], {"limit": 100, "extend": "inFavorites"})


# ---------------------------------------------------------------------------------- Recently Added
class RecentPagerTests(unittest.TestCase):
    def album(self, n, **attributes):
        values = {"name": f"Album {n}", "artistName": "Artist", "releaseDate": "2019-04-26", "trackCount": 8,
                  "artwork": {"url": f"https://is1-ssl.mzstatic.com/a{n}/{{w}}x{{h}}bb.jpg",
                              "width": 1200, "height": 1200, "bgColor": "101010", "textColor1": "fafafa"}}
        values.update(attributes)
        return {"id": f"l.{n}", "type": "library-albums", "attributes": values}

    def test_pages_of_25_with_our_own_params_total_and_complete(self):
        def route(params):
            offset = params["offset"]
            data = [self.album(offset + i) for i in range(25 if offset < 25 else 3)]
            body = {"data": data, "meta": {"total": 28}}
            if offset < 25:
                body["next"] = AppleMusicClient.RECENT + "?offset=25"
            return body
        apple, session, _ = client({("GET", AppleMusicClient.RECENT): route})
        first = apple.recent_page(0)
        second = apple.recent_page(25, visit=first["visit"])
        self.assertEqual([c["params"] for c in session.calls], [{"limit": 25, "offset": 0}, {"limit": 25, "offset": 25}])
        self.assertEqual((first["total"], first["complete"], len(first["items"])), (28, False, 25))
        self.assertEqual((second["total"], second["complete"], len(second["items"])), (28, True, 3))
        item = first["items"][0]
        self.assertEqual({k: item[k] for k in ("art_max", "art_bg", "art_ink", "year", "track_count", "kind")},
                         {"art_max": 1200, "art_bg": 0x101010, "art_ink": 0xFAFAFA, "year": 2019, "track_count": 8,
                          "kind": "album"})
        self.assertTrue(item["artwork_url"].endswith("/480x480bb.jpg"), "the knob URL is unchanged")

    def test_a_page_of_an_older_visit_never_commits(self):
        apple, _, _ = client({("GET", AppleMusicClient.RECENT): lambda p: {"data": [self.album(p["offset"])]}})
        first = apple.recent_page(0)
        apple.recent_page(0)   # a new visit
        with self.assertRaises(AppleMusicError):
            apple.recent_page(25, visit=first["visit"])

    def test_an_item_without_art_carries_empty_art_keys(self):
        apple, _, _ = client({("GET", AppleMusicClient.RECENT): {"data": [self.album(1, artwork=None)]}})
        item = apple.recent_page(0)["items"][0]
        self.assertEqual((item["art_template"], item["art_max"], item["art_bg"], item["art_ink"]), ("", 0, 0, 0))
        self.assertIsNone(apple.recent_page(0)["total"])


# ---------------------------------------------------------------------------------- resolve
def library_song(identifier, catalog_id, **catalog_attributes):
    related = []
    if catalog_id:
        attributes = {"name": f"Track {catalog_id}", "artistName": "Artist", "playParams": {"id": str(catalog_id)},
                      "albumName": "Album", "trackNumber": 1, "durationInMillis": 200000,
                      "url": f"https://music.apple.com/ca/album/album/900?i={catalog_id}",
                      "artwork": {"url": "https://is1-ssl.mzstatic.com/x/{w}x{h}bb.jpg"}}
        attributes.update(catalog_attributes)
        related = [{"id": str(catalog_id), "type": "songs", "attributes": attributes}]
    return {"id": identifier, "type": "library-songs", "relationships": {"catalog": {"data": related}}}


class ResolveTests(unittest.TestCase):
    def tracks_route(self, pages):
        """pages: list of track lists; our own params plus Apple's offset."""
        def route(params):
            index = params.get("offset", 0) // 2
            body = {"data": pages[index], "meta": {"total": sum(len(p) for p in pages)}}
            if index + 1 < len(pages):
                body["next"] = "PATH?offset=%d" % ((index + 1) * 2)
            return body
        return route

    def routes(self, kind, identifier, pages):
        path = f"/v1/me/library/{kind}s/{identifier}/tracks"
        route = self.tracks_route(pages)

        def fixed(params):
            body = route(params)
            if "next" in body:
                body["next"] = body["next"].replace("PATH", path)
            return body
        return {("GET", path): fixed}

    def test_include_catalog_and_the_page_limit_on_every_page_for_albums_and_playlists(self):
        # limit = TRACKS_PAGE_LIMIT (50, the K3 section 1.2 parse cap; 100 until the H5 bench).
        for kind in ("album", "playlist"):
            with self.subTest(kind=kind):
                pages = [[library_song("a", 1), library_song("b", 2)], [library_song("c", 3)]]
                apple, session, _ = client(self.routes(kind, "x", pages))
                result = apple.resolve({"id": "x", "kind": kind})
                self.assertEqual([t["catalog_id"] for t in result["tracks"]], ["1", "2", "3"])
                self.assertEqual([c["params"] for c in session.calls],
                                 [{"include": "catalog", "limit": 50},
                                  {"include": "catalog", "limit": 50, "offset": 2}])
                track = result["tracks"][0]
                self.assertEqual((track["album"], track["track_number"], track["duration_ms"], track["art_template"]),
                                 ("Album", 1, 200000, "https://is1-ssl.mzstatic.com/x/{w}x{h}bb.jpg"))

    def test_playlists_are_lenient_albums_strict(self):
        pages = [[library_song("a", 1), library_song("upload", None), library_song("c", 3)]]
        apple, _, _ = client(self.routes("playlist", "p", pages))
        result = apple.resolve({"id": "p", "kind": "playlist"})
        self.assertEqual((len(result["tracks"]), result["total"], result["unavailable"]), (2, 3, 1))
        apple, _, _ = client(self.routes("album", "a", pages))
        with self.assertRaises(MusicUnavailable) as raised:
            apple.resolve({"id": "a", "kind": "album"})
        self.assertEqual(apple_outcome(raised.exception, "play_items", kind="album"), "album_blocked")
        self.assertEqual(apple_outcome(raised.exception, "play_next"), "nothing_added")
        apple, _, _ = client(self.routes("playlist", "z", [[library_song("u", None)]]))
        with self.assertRaises(MusicUnavailable):
            apple.resolve({"id": "z", "kind": "playlist"})

    def test_the_20_s_deadline_covers_the_whole_resolve(self):
        clock = FakeClock()
        pages = [[library_song("a", 1)], [library_song("b", 2)]]
        routes = self.routes("album", "slow", pages)
        (key, route), = routes.items()

        def slow(params):
            clock.advance(12.0)
            return route(params)
        apple, _, _ = client({key: slow}, clock=clock)
        with self.assertRaises(ResolveTimeout) as raised:
            apple.resolve({"id": "slow", "kind": "album"})
        self.assertEqual(apple_outcome(raised.exception, "play_items", kind="album"), "start_failed")
        self.assertEqual(apple_outcome(raised.exception, "play_next"), "nothing_added")

    def test_the_cache_is_read_first_expires_and_can_be_evicted(self):
        clock = FakeClock()
        apple, session, _ = client(self.routes("album", "c", [[library_song("a", 1)]]), clock=clock)
        item = {"id": "c", "kind": "album"}
        first = apple.resolve(item)
        self.assertEqual(apple.resolve(item), first)
        self.assertEqual((len(session.calls), apple.resolve_lookups), (1, 1))
        self.assertEqual(apple.resolve_cached(item), first)
        clock.advance(AM.RESOLVE_CACHE_TTL_S + 1)
        self.assertIsNone(apple.resolve_cached(item))
        apple.resolve(item)
        apple.evict_resolved(item)
        self.assertIsNone(apple.resolve_cached(item))
        self.assertEqual(apple.resolve_lookups, 2)

    def test_a_running_resolve_of_the_same_item_is_joined(self):
        started, release = threading.Event(), threading.Event()
        routes = self.routes("album", "j", [[library_song("a", 1)]])
        (key, route), = routes.items()

        def held(params):
            started.set()
            release.wait(5)
            return route(params)
        session = RecordingSession({key: held})
        apple = AppleMusicClient(CREDENTIALS, session=RecordingSession(), background_session=session)
        item = {"id": "j", "kind": "album", "track_count": 1}
        outcome = {}
        worker = threading.Thread(target=lambda: outcome.setdefault("pre", apple.preresolve(item, focused=True)))
        worker.start()
        self.assertTrue(started.wait(3))
        self.assertTrue(apple.resolve_running(item))
        joiner = threading.Thread(target=lambda: outcome.setdefault("job", apple.resolve(item)))
        joiner.start()
        joiner.join(0.2)
        self.assertTrue(joiner.is_alive(), "waits for the running pre-resolution")
        release.set()
        worker.join(3)
        joiner.join(3)
        self.assertEqual(outcome["job"], outcome["pre"])
        self.assertEqual((apple.resolve_lookups, len(session.calls)), (1, 1))

    def test_preresolution_skips_cached_unavailable_large_and_unknown_playlists(self):
        apple, session, _ = client(self.routes("album", "k", [[library_song("a", 1)]]))
        self.assertIsNone(apple.preresolve({"id": "k", "kind": "album", "available": False}))
        self.assertIsNone(apple.preresolve({"id": "k", "kind": "album", "track_count": 101}))
        self.assertIsNone(apple.preresolve({"id": "p", "kind": "playlist"}), "unknown size, not focused")
        self.assertEqual(session.calls, [])
        self.assertIsNotNone(apple.preresolve({"id": "k", "kind": "album", "track_count": 1}))
        self.assertIsNone(apple.preresolve({"id": "k", "kind": "album", "track_count": 1}), "cached")
        self.assertEqual(apple.resolve_lookups, 1)


# ---------------------------------------------------------------------------------- playlist_meta
class PlaylistMetaTests(unittest.TestCase):
    PATH = "/v1/me/library/playlists/p.1/tracks"

    def track(self, album, art=True, duration=100000):
        attributes = {"name": "T", "albumName": album, "durationInMillis": duration}
        if art:
            attributes["artwork"] = {"url": f"https://is1-ssl.mzstatic.com/{album}/{{w}}x{{h}}bb.jpg",
                                     "width": 600, "height": 600, "bgColor": "203040", "textColor1": "ffffff"}
        return {"id": "i." + album, "type": "library-songs",
                "relationships": {"catalog": {"data": [{"id": "1", "type": "songs", "attributes": attributes}]}}}

    def test_the_mosaic_takes_the_first_4_distinct_albums_with_art(self):
        tracks = [self.track("a"), self.track("a"), self.track("noart", art=False), self.track("b"),
                  self.track("c"), self.track("d"), self.track("e")]
        apple, session, _ = client({("GET", self.PATH): {"data": tracks, "meta": {"total": 34}}})
        meta = apple.playlist_meta("p.1")
        self.assertEqual(meta["count"], 34)
        self.assertEqual([m["art_template"].split("/")[3] for m in meta["mosaic"]], ["a", "b", "c", "d"])
        self.assertEqual((meta["art_state"], meta["accent"], meta["duration_ms"]), ("mosaic", 0x203040, None))
        self.assertEqual(session.calls[0]["params"], {"limit": 50, "include": "catalog"})

    def test_fewer_than_4_is_the_first_one_and_none_is_generated(self):
        apple, _, _ = client({("GET", self.PATH): {"data": [self.track("noart", art=False), self.track("a"),
                                                              self.track("b")], "meta": {"total": 3}}})
        meta = apple.playlist_meta("p.1")
        self.assertEqual((meta["art_state"], len(meta["mosaic"])), ("single", 1))
        apple, _, _ = client({("GET", self.PATH): {"data": [self.track("x", art=False)], "meta": {"total": 1}}})
        meta = apple.playlist_meta("p.1")
        self.assertEqual((meta["art_state"], meta["mosaic"], meta["first_art"]), ("generated", [], None))

    def test_an_empty_playlist_and_the_duration_of_every_page(self):
        apple, _, _ = client({("GET", self.PATH): Resp(404, {"errors": [{"code": "40403"}]})})
        self.assertTrue(apple.playlist_meta("p.1")["empty"])
        apple, _, _ = client({("GET", self.PATH): Resp(404, {"errors": [{"code": "40400"}]})})
        with self.assertRaises(AppleMusicError):
            apple.playlist_meta("p.1")

        # The first page already holds the mosaic's 4 albums, so only the duration reads page 2
        # (with fewer, the mosaic would read on into the first 100 tracks, test_cc_gil_parse.py).
        def route(params):
            if params.get("offset"):
                return {"data": [self.track("e", duration=30000)], "meta": {"total": 5}}
            return {"data": [self.track("a"), self.track("b"), self.track("c"), self.track("d")],
                    "meta": {"total": 5}, "next": self.PATH + "?offset=4"}
        apple, session, _ = client({("GET", self.PATH): route})
        meta = apple.playlist_meta("p.1", duration=True, last_modified="2026-06-21")
        self.assertEqual(meta["duration_ms"], 430000)
        apple.playlist_meta("p.1", duration=True, last_modified="2026-06-21")
        self.assertEqual(len(session.calls), 3, "the duration is cached by (id, last_modified)")


if __name__ == "__main__":
    unittest.main()
