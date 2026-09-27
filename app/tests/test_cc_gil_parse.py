"""K3 section 1.2 / K4 section 4.7.3 parse caps (WP6-gil): the page and batch sizes the H5 parse
bench (tools/stage_checks/gil_parse_hold.py) set, that no request the service lanes send exceeds
them, that playlist_meta keeps the 100-track mosaic window with 50-row pages, that the Sonos
queue reads keep 100-row pages, and that the bench's fixtures still run through the real client
paths (so the bench stays runnable when the clients change). Review fixes: playlist_meta's
duration keeps its 10,000-track reach with 50-row pages (WP6GIL-1); a failed window page costs a
neighbour only what the single 100-row read would have given (WP6GIL-3); the queue-recovery copy
is encoded in parts, never with one json.dumps of the whole record (WP6GIL-4, [G1] G1-5).

Headless: in-memory sessions and the FakeSpeaker; no network, no Sonos, no Tk. The bench module
is imported for its fixtures only (its timing run and its network block are never started here).
The one file written (the recovery-store format test, Windows DPAPI) goes to a temporary folder.
"""
from pathlib import Path
import importlib.util
import json
import os
import random
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import sonos as S  # noqa: E402
from control_center.apple_music import AppleMusicClient, AppleMusicError, MusicUnavailable  # noqa: E402
from control_center.credentials import CredentialError, CredentialStore  # noqa: E402
from test_cc_apple_v7 import CREDENTIALS, Resp, client, library_song  # noqa: E402
from test_cc_music import MemoryStore  # noqa: E402
from test_cc_sonos_v7 import Rig, song  # noqa: E402

BENCH = Path(__file__).resolve().parents[2] / "tools" / "stage_checks" / "gil_parse_hold.py"


def paged(path, rows, meta=True):
    """A route serving ``rows`` in pages of the request's own ``limit`` from its ``offset``
    (``meta.total`` on every page unless ``meta`` is False)."""
    def route(params):
        offset, limit = int(params.get("offset", 0)), int(params["limit"])
        body = {"data": rows[offset:offset + limit]}
        if meta:
            body["meta"] = {"total": len(rows)}
        if offset + limit < len(rows):
            body["next"] = f"{path}?offset={offset + limit}"
        return body
    return route


def failing_at(route, offset, response):
    """``route``, except that the request for ``offset`` answers ``response``."""
    def wrapped(params):
        return response if int(params.get("offset", 0)) == offset else route(params)
    return wrapped


class ParseCapTests(unittest.TestCase):
    def test_the_caps_are_the_h5_bench_values(self):
        self.assertEqual((AppleMusicClient.TRACKS_PAGE_LIMIT, AppleMusicClient.CATALOG_BATCH,
                          AppleMusicClient.PLAYLISTS_PAGE_LIMIT, AppleMusicClient.RATINGS_BATCH,
                          AppleMusicClient.RECENT_PAGE, AppleMusicClient.MOSAIC_SCAN_TRACKS),
                         (50, 50, 100, 100, 25, 100))
        self.assertEqual(S.QUEUE_PAGE_ROWS, 100)

    def test_no_apple_request_asks_for_more_than_its_cap(self):
        ids = [str(1000 + n) for n in range(120)]
        tracks = [library_song(f"i.{n}", 5000 + n) for n in range(120)]
        path = "/v1/me/library/playlists/p.big/tracks"
        apple, session, _ = client({("GET", "/v1/me/storefront"): {"data": [{"id": "us"}]},
                                    ("GET", "/v1/catalog/us/songs"): {"data": []},
                                    ("GET", "/v1/me/ratings/songs"): {"data": []},
                                    ("GET", path): paged(path, tracks)})
        apple.catalog_songs(ids)
        apple.ratings(ids)
        result = apple.resolve({"id": "p.big", "kind": "playlist"})
        self.assertEqual(len(result["tracks"]), 120)
        sizes = {}
        for call in session.calls:
            params = call["params"]
            if "ids" in params:
                sizes.setdefault(call["path"], []).append(len(params["ids"].split(",")))
            elif "limit" in params:
                sizes.setdefault(call["path"], []).append(params["limit"])
        self.assertEqual(sizes["/v1/catalog/us/songs"], [50, 50, 20])
        self.assertEqual(sizes["/v1/me/ratings/songs"], [100, 20])
        self.assertEqual(sizes[path], [50, 50, 50])
        self.assertEqual([c["params"].get("offset") for c in session.calls if c["path"] == path], [None, 50, 100])

    def test_an_item_over_max_tracks_still_says_it_exceeds_the_limit(self):
        path = "/v1/me/library/albums/huge/tracks"
        tracks = [library_song(f"i.{n}", 7000 + n) for n in range(AppleMusicClient.MAX_TRACKS + 1)]
        apple, session, _ = client({("GET", path): paged(path, tracks)})
        with self.assertRaises(MusicUnavailable) as raised:
            apple.resolve({"id": "huge", "kind": "album"})
        self.assertIn("exceeds the supported track limit", str(raised.exception))
        self.assertEqual(len(session.calls), AppleMusicClient.MAX_TRACKS // AppleMusicClient.TRACKS_PAGE_LIMIT + 1)


class PlaylistRows:
    """Playlist tracks with one album each (``track``) served in pages of the request's limit."""
    PATH = "/v1/me/library/playlists/p.1/tracks"

    def track(self, album, duration=1000):
        attributes = {"name": "T", "albumName": album, "durationInMillis": duration,
                      "artwork": {"url": f"https://is1-ssl.mzstatic.com/{album}/{{w}}x{{h}}bb.jpg",
                                  "width": 600, "height": 600, "bgColor": "203040", "textColor1": "ffffff"}}
        return {"id": "i." + album, "type": "library-songs",
                "relationships": {"catalog": {"data": [{"id": "1", "type": "songs", "attributes": attributes}]}}}

    def meta(self, albums, total=True, **kwargs):
        apple, session, _ = client({("GET", self.PATH): paged(self.PATH, [self.track(a) for a in albums], total)})
        return apple.playlist_meta("p.1", **kwargs), session

    @staticmethod
    def names(meta):
        return [m["art_template"].split("/")[3] for m in meta["mosaic"]]


class MosaicWindowTests(PlaylistRows, unittest.TestCase):
    """playlist_meta reads 50-row pages but looks for its 4 albums in the first 100 tracks, as a
    100-row first page did; a second page is read only while fewer than 4 were found."""

    def test_one_page_when_it_holds_four_albums(self):
        meta, session = self.meta(["a", "b", "c", "d"] + ["e"] * 96)
        self.assertEqual((self.names(meta), meta["art_state"], meta["count"]), (["a", "b", "c", "d"], "mosaic", 100))
        self.assertEqual([c["params"] for c in session.calls], [{"limit": 50, "include": "catalog"}])

    def test_a_second_page_when_the_first_holds_fewer_than_four(self):
        meta, session = self.meta(["a"] * 50 + ["b", "c", "d"] + ["a"] * 47)
        self.assertEqual((self.names(meta), meta["art_state"]), (["a", "b", "c", "d"], "mosaic"))
        self.assertEqual(len(session.calls), 2)

    def test_never_past_the_first_100_tracks(self):
        meta, session = self.meta(["a"] * 60 + ["b"] * 40 + ["c", "d"] + ["a"] * 8)
        self.assertEqual((self.names(meta), meta["art_state"]), (["a"], "single"))
        self.assertEqual(len(session.calls), 2, "tracks 101+ are not read for the mosaic")

    def test_without_meta_total_the_count_is_known_within_the_first_100_tracks(self):
        meta, session = self.meta(["a", "b", "c", "d"] + ["e"] * 56, total=False)
        self.assertEqual((meta["count"], meta["art_state"], len(session.calls)), (60, "mosaic", 2))
        meta, session = self.meta(["a", "b", "c", "d"] + ["e"] * 116, total=False)
        self.assertEqual((meta["count"], len(session.calls)), (None, 2), "past 100 tracks: unknown, as before")

    def test_the_duration_counts_every_page_once(self):
        albums = ["a"] * 50 + ["b", "c", "d"] + ["e"] * 60
        meta, session = self.meta(albums, duration=True, last_modified="2026-09-26")
        self.assertEqual(meta["duration_ms"], 1000 * len(albums))
        self.assertEqual([c["params"].get("offset") for c in session.calls], [None, 50, 100])


class PlaylistMetaReachTests(PlaylistRows, unittest.TestCase):
    """WP6GIL-1: the duration's page bound follows the page size, so 50-row pages keep the reach
    100 pages of 100 had (``META_MAX_TRACKS`` = 10,000); a longer playlist keeps its count and
    mosaic with the duration unknown, and never re-reads what cannot be read."""
    FOUR = ["a", "b", "c", "d"]

    def big(self, total, meta=True, **kwargs):
        rows = [self.track(a) for a in self.FOUR] + [self.track("e")] * (total - 4)
        apple, session, _ = client({("GET", self.PATH): paged(self.PATH, rows, meta)})
        return apple, session

    def test_a_6000_track_playlist_gets_its_count_mosaic_and_duration(self):
        apple, session = self.big(6000)
        meta = apple.playlist_meta("p.1", duration=True, last_modified="2026-09-26")
        self.assertEqual((meta["count"], meta["art_state"], meta["duration_ms"]), (6000, "mosaic", 6_000_000))
        self.assertEqual(len(session.calls), 120, "every 50-row page once")

    def test_the_reach_is_10000_tracks_as_with_100_row_pages(self):
        self.assertEqual(AppleMusicClient.META_MAX_TRACKS, 10_000)
        apple, session = self.big(10_000)
        meta = apple.playlist_meta("p.1", duration=True, last_modified="x")
        self.assertEqual((meta["count"], meta["duration_ms"], len(session.calls)), (10_000, 10_000_000, 200))

    def test_past_the_reach_with_meta_total_no_page_is_read_for_the_duration(self):
        apple, session = self.big(10_001)
        meta = apple.playlist_meta("p.1", duration=True, last_modified="x")
        self.assertEqual((meta["count"], meta["art_state"], meta["duration_ms"]), (10_001, "mosaic", None))
        self.assertEqual(len(session.calls), 1, "the first page only")

    def test_past_the_reach_without_meta_total_the_none_is_cached(self):
        apple, session = self.big(10_001, meta=False)
        meta = apple.playlist_meta("p.1", duration=True, last_modified="x")
        self.assertEqual((meta["count"], meta["art_state"], meta["duration_ms"]), (None, "mosaic", None))
        self.assertEqual(len(session.calls), 200, "the page bound, then unknown (no raise)")
        session.calls.clear()
        again = apple.playlist_meta("p.1", duration=True, last_modified="x")
        self.assertEqual((again["duration_ms"], again["art_state"]), (None, "mosaic"))
        self.assertEqual(len(session.calls), 2, "a refocus reads the 100-track window only")


class PlaylistMetaFailureTests(PlaylistRows, unittest.TestCase):
    """WP6GIL-3: a window page that fails costs a neighbour only what the single 100-row read would
    have given; the focused playlist still raises (its duration needs every page); a failed
    duration page keeps the count and mosaic, with nothing cached."""

    def meta_failing(self, albums, offset, response, total=True, **kwargs):
        route = failing_at(paged(self.PATH, [self.track(a) for a in albums], total), offset, response)
        apple, session, _ = client({("GET", self.PATH): route})
        return apple, session

    def test_a_neighbour_keeps_page_one_when_page_two_fails(self):
        for status in (429, 500, 503):
            with self.subTest(status=status):
                apple, session = self.meta_failing(["a"] * 60 + ["b", "c", "d"] + ["a"] * 37, 50,
                                                   Resp(status, {"errors": [{"code": "50000"}]}))
                meta = apple.playlist_meta("p.1")
                self.assertEqual((meta["count"], self.names(meta), meta["art_state"], meta["empty"]),
                                 (100, ["a"], "single", False))
                self.assertEqual(len(session.calls), 2)

    def test_a_broken_next_link_ends_the_window_too(self):
        rows = [self.track("a")] * 100

        def route(params):
            return {"data": rows[:50], "meta": {"total": 100}, "next": "/v1/me/library/playlists/p.1/tracks?offset=x"}
        apple, session, _ = client({("GET", self.PATH): route})
        meta = apple.playlist_meta("p.1")
        self.assertEqual((meta["count"], meta["art_state"], len(session.calls)), (100, "single", 1))

    def test_without_meta_total_a_failed_window_leaves_the_count_unknown(self):
        apple, _ = self.meta_failing(["a", "b", "c", "d"] + ["e"] * 76, 50, Resp(500, {}), total=False)
        meta = apple.playlist_meta("p.1")
        self.assertEqual((meta["count"], meta["art_state"]), (None, "mosaic"), "not the 50 read so far")

    def test_sign_in_failures_still_raise(self):
        for status in (401, 403):
            with self.subTest(status=status):
                apple, _ = self.meta_failing(["a"] * 100, 50, Resp(status, {}))
                with self.assertRaises(AppleMusicError) as raised:
                    apple.playlist_meta("p.1")
                self.assertEqual(raised.exception.status, status)

    def test_the_focused_playlist_still_raises_on_a_window_failure(self):
        apple, session = self.meta_failing(["a"] * 100, 50, Resp(500, {}))
        with self.assertRaises(AppleMusicError):
            apple.playlist_meta("p.1", duration=True, last_modified="x")
        self.assertEqual(apple._duration_cache, {}, "nothing cached")

    def test_a_failed_duration_page_keeps_count_and_mosaic_and_caches_nothing(self):
        albums = ["a", "b", "c", "d"] + ["e"] * 146
        apple, session = self.meta_failing(albums, 100, Resp(500, {}))
        meta = apple.playlist_meta("p.1", duration=True, last_modified="x")
        self.assertEqual((meta["count"], meta["art_state"], meta["duration_ms"]), (150, "mosaic", None))
        self.assertEqual([c["params"].get("offset") for c in session.calls], [None, 50, 100])
        self.assertEqual(apple._duration_cache, {}, "a partial sum is never cached")
        healthy, _ = self.meta(albums, duration=True, last_modified="x")
        self.assertEqual(healthy["duration_ms"], 150_000)
        apple, _ = self.meta_failing(albums, 100, Resp(401, {}))
        with self.assertRaises(AppleMusicError) as raised:
            apple.playlist_meta("p.1", duration=True, last_modified="x")
        self.assertEqual(raised.exception.status, 401)


class RecoveryEncodingTests(unittest.TestCase):
    """WP6GIL-4 ([G1] G1-5): the queue-recovery copy is encoded one value and one queue row at a
    time, byte for byte what json.dumps gave, and written in the CredentialStore format."""
    RECORD = {"room_uid": "RINCON_1", "coordinator_uid": "RINCON_1", "group_revision": "g", "queue_revision": "187",
              "items": [{"title": "Björk – Jóga 夜に駆ける \"quoted\"", "uri": "x-sonos-http:song%3a1.mp4",
                         "metadata": "<DIDL-Lite>&amp;</DIDL-Lite>"}, {"title": "", "uri": "", "metadata": None}],
              "track": {"title": "x", "position": "0:01:02", "nested": [1, 2.5, True, None, {"k": []}]},
              "transport": {}, "play_mode": "NORMAL", "empty": [], "number": 3}

    def test_the_parts_join_to_json_dumps_byte_for_byte(self):
        for record in (self.RECORD, {}, {"items": []}, {"items": [{"a": 1}]}, {"x": "é"}):
            with self.subTest(record=record):
                parts = S._recovery_json_parts(record)
                self.assertEqual(b"".join(parts), json.dumps(record).encode("utf-8"))
        parts = S._recovery_json_parts(self.RECORD)
        self.assertLess(max(map(len, parts)), len(json.dumps(self.RECORD["items"])), "no part holds the item list")

    def test_a_start_never_encodes_the_whole_record_in_one_call(self):
        class EncodedStore(MemoryStore):
            def save_encoded(self, data):
                self.encoded = data
        rig = Rig(queue=tuple(range(1000, 1300)))
        rig.store = rig.adapter.recovery_store = EncodedStore()
        real, sizes = json.dumps, []

        def spy(value, *args, **kwargs):
            out = real(value, *args, **kwargs)
            sizes.append(len(out))
            return out
        with mock.patch.object(S.json, "dumps", spy):
            rig.adapter.play_items([song(1), song(2)], rig.state["group_revision"])
        whole = json.dumps(rig.adapter.last_recovery).encode("utf-8")
        self.assertEqual(rig.store.encoded, whole)
        self.assertIsNone(rig.store.saved, "the mapping path is only for stores without save_encoded")
        self.assertEqual(len(rig.adapter.last_recovery["items"]), 300)
        self.assertLess(max(sizes), 1_000, "every json.dumps during the start is one small value")
        self.assertGreater(len(whole), 20 * max(sizes))

    def test_stores_without_save_encoded_get_the_mapping(self):
        rig = Rig(queue=(90, 91))
        rig.adapter.play_items([song(1)], rig.state["group_revision"])
        self.assertEqual([item["title"] for item in rig.store.saved["items"]], ["Song 90", "Song 91"])

    def test_the_default_store_is_the_recovery_store_beside_the_credentials(self):
        made = []

        class Recording:
            def __init__(self, path):
                self.path, self.data = Path(path), None
                made.append(self)

            def save_encoded(self, data):
                self.data = data

        class Default:
            path = Path(tempfile.gettempdir()) / "wp6gil-never-written" / "credentials.bin"
        rig = Rig(queue=(90, 91))
        rig.adapter.recovery_store = None
        with mock.patch.object(S, "_RecoveryStore", Recording), mock.patch.object(S, "CredentialStore", Default):
            rig.adapter.play_items([song(1)], rig.state["group_revision"])
        self.assertEqual([store.path.name for store in made], ["queue-recovery.bin"])
        self.assertEqual(made[0].path.parent, Default.path.parent)
        self.assertEqual(made[0].data, json.dumps(rig.adapter.last_recovery).encode("utf-8"))
        self.assertTrue(issubclass(S._RecoveryStore, CredentialStore))

    @unittest.skipUnless(os.name == "nt", "DPAPI is Windows only")
    def test_save_encoded_writes_the_credential_store_format(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "queue-recovery.bin"
            store = S._RecoveryStore(path)
            store.save_encoded(b"".join(S._recovery_json_parts(self.RECORD)))
            self.assertTrue(path.read_bytes().startswith(CredentialStore.MAGIC))
            self.assertEqual(CredentialStore(path).load(), self.RECORD)
            self.assertEqual([p.name for p in Path(folder).iterdir()], ["queue-recovery.bin"], "no temporary left")
            for bad in ("{}", b"[1]", b""):
                with self.subTest(bad=bad), self.assertRaises(CredentialError):
                    store.save_encoded(bad)


class SonosQueuePageTests(unittest.TestCase):
    def test_full_reads_slices_and_windows_use_100_row_pages(self):
        rig = Rig(queue=tuple(range(1000, 1250)), position=1)
        rig.speaker.queue_reads.clear()
        snapshot = rig.adapter._queue(rig.speaker)
        self.assertEqual((len(snapshot.items), rig.speaker.queue_reads), (250, [(0, 100), (100, 100), (200, 100)]))
        rig.speaker.queue_reads.clear()
        self.assertEqual(len(rig.adapter._slice(rig.speaker, 10, 150).items), 150)
        self.assertEqual(rig.speaker.queue_reads, [(10, 100), (110, 50)])
        rig.speaker.queue_reads.clear()
        self.assertEqual(len(rig.adapter.queue_window(0, 100)["rows"]), 100)
        self.assertEqual(rig.speaker.queue_reads, [(0, 100)], "one Browse, not deferred, not split")
        with self.assertRaises(S.SonosError):
            rig.adapter.queue_window(0, S.QUEUE_PAGE_ROWS + 1)


@unittest.skipUnless(BENCH.is_file(), "tools/stage_checks/gil_parse_hold.py is not beside this project")
class BenchFixtureTests(unittest.TestCase):
    """The bench's synthetic responses still run through the clients' real code paths."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("gil_parse_hold_fixtures", BENCH)
        cls.G = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.G)

    def apple(self, response):
        G = self.G
        storefront = G._response(G.apple_page([{"id": "us", "type": "storefronts"}]), G.JSON_TYPE)
        return AppleMusicClient(CREDENTIALS, session=G._Session(
            lambda url, params: storefront if url.endswith("/storefront") else response))

    def test_the_catalog_fixture_fills_every_row(self):
        G = self.G
        body, ids = G.catalog_songs_body(20, random.Random(1))
        result = self.apple(G._response(body, G.JSON_TYPE)).catalog_songs(ids)
        self.assertEqual(len(result), 20)
        self.assertTrue(all(row["catalog"] and row["url"] and row["art_template"] for row in result.values()))

    def test_the_tracks_fixture_resolves_every_track(self):
        G = self.G
        body = G.tracks_page_body(20, random.Random(2))
        result = self.apple(G._response(body, G.JSON_TYPE)).resolve({"id": "p.X", "kind": "playlist"})
        self.assertEqual((len(result["tracks"]), result["unavailable"]), (20, 0))

    def test_the_other_apple_fixtures_parse(self):
        G = self.G
        rng = random.Random(3)
        for body, count in ((G.playlists_page_body(10, rng), 10), (G.recent_page_body(25, rng), 25),
                            (G.ratings_body(["1", "2"]), 2)):
            self.assertEqual(len(G._response(body, G.JSON_TYPE).json()["data"]), count)

    def test_the_browse_fixture_becomes_queue_rows(self):
        from soco.data_structures_entry import from_didl_string
        from soco.services import Service
        G = self.G
        body, _ = G.browse_body(21, random.Random(4))
        out = Service.unwrap_arguments(G._response(body, G.XML_TYPE).text)
        items = from_didl_string.__wrapped__(out["Result"])
        self.assertEqual((len(items), out["NumberReturned"]), (21, "21"))
        row = S.SonosAdapter("192.0.2.10")._row(items[0], 1, "192.0.2.10")
        self.assertEqual((row["service"], row["song_id"].isdigit(), isinstance(row["duration_s"], int)),
                         ("apple", True, True))

    def test_the_zone_group_fixture_normalises(self):
        from soco.zonegroupstate import ZoneGroupState
        G = self.G
        _, xml = G.zgs_body(6, random.Random(5))
        state = ZoneGroupState()
        state.process_payload(payload=xml, source="poll", source_ip="192.0.2.10")
        self.assertEqual((len(state.visible_zones), len(state.all_zones)), (6, 9))

    def test_the_caps_rule_takes_the_largest_size_within_its_bounds(self):
        """p50 within 0.5 ms (the margin for real bodies) and p95 within 1 ms (the tail)."""
        G = self.G

        def row(name, size, p50, p95, kind="call"):
            return {"name": name, "size": size, "kind": kind, "call_p50_ms": p50, "hold_p95_ms": p95,
                    "verdict": "py"}
        rows = [row("apple catalog_songs ids=300: x", 300, 1.8, 2.3), row("apple catalog_songs ids=50: x", 50, 0.27, 0.28),
                row("apple catalog_songs ids=100: x", 100, 0.55, 0.7), row("apple tracks page limit=50 x", 50, 0.45, 0.79),
                row("apple tracks page limit=100 x", 100, 0.94, 1.1), row("apple tracks page limit=25 x", 25, 0.2, 0.3),
                row("apple playlists page limit=100 x", 100, 0.2, 0.22), row("sonos Browse rows=100: x", 100, 0.26, 1.2),
                row("sonos Browse rows=60: x", 60, 0.16, 0.2), row("apple catalog_songs ids=300: path", 300, 7.8, None, "path"),
                row("recovery save rows=5000: join", 5000, 0.5, 0.55), row("recovery save rows=100: join", 100, 0.01, 0.02)]
        caps = G.caps(rows)
        self.assertEqual((caps["catalog_songs_ids"], caps["tracks_page_limit"], caps["playlists_page_limit"],
                          caps["browse_rows"], caps["bound_ms"]), (50, 50, 100, 60, 0.5))
        self.assertEqual(caps["recovery_save_largest_hold_ms"], 0.55)

    def test_the_recovery_fixture_encodes_in_parts_as_json_dumps(self):
        record = self.G.recovery_snapshot(random.Random(6), 20)
        self.assertEqual(b"".join(S._recovery_json_parts(record)), json.dumps(record).encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
