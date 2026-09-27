from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.apple_music import AppleMusicClient, AppleMusicError, MusicUnavailable
from control_center.sonos import SonosAdapter, SonosError, GroupChanged, TrackChanged, QueueReplacementFailed


class FakeResponse:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status
    def json(self):
        return self.data


class FakeSession:
    """Responses keyed by path; a request carrying our own ``offset`` param is keyed
    ``path?offset=N`` (the own-params pager, K3 section 9.8.7)."""
    def __init__(self, responses):
        self.responses = dict(responses)
        self.calls = []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        path = url.removeprefix(AppleMusicClient.API)
        params = kwargs.get("params") or {}
        if "offset" in params:
            path += f"?offset={params['offset']}"
        value = self.responses[path]
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, FakeResponse) else FakeResponse(value)


def catalog(identifier):
    return {"id": str(identifier), "type": "songs", "attributes": {
        "name": "Track " + str(identifier), "artistName": "Artist", "playParams": {"id": str(identifier)},
        "url": f"https://music.apple.com/ca/album/album/900?i={identifier}"}}


def library_song(identifier, catalog_id):
    return {"id": identifier, "type": "library-songs", "relationships": {
        "catalog": {"data": [catalog(catalog_id)] if catalog_id else []}}}


class AppleMusicTests(unittest.TestCase):
    def test_authorization_saved_after_startup_is_used_without_restart(self):
        saved = {}
        session = FakeSession({AppleMusicClient.RECENT: {"data": []}})
        client = AppleMusicClient({}, session=session, credential_loader=lambda: dict(saved))
        with self.assertRaisesRegex(AppleMusicError, "Connect Apple Music"):
            client.recent()
        saved.update(developer_token="dev", music_user_token="new-user")
        self.assertEqual(client.recent()["items"], [])
        self.assertEqual(session.calls[-1][1]["headers"]["Music-User-Token"], "new-user")

    def client(self, responses):
        session = FakeSession(responses)
        return AppleMusicClient({"developer_token": "dev", "music_user_token": "user"}, session=session), session

    def test_recent_pagination_preserves_server_order_and_deduplicates_shift(self):
        a = {"id": "A", "type": "library-albums", "attributes": {"name": "Alpha"}}
        b = {"id": "B", "type": "library-playlists", "attributes": {"name": "Beta"}}
        client_path = AppleMusicClient.RECENT
        client_path_next = client_path + "?offset=10"
        client, session = self.client({
            client_path: {"data": [a], "next": client_path_next},
            client_path_next: {"data": [a, b]},
        })
        first = client.recent()
        second = client.recent(first["next"])
        self.assertEqual([i["id"] for i in first["items"] + second["items"]], ["A", "B"])
        self.assertIsNone(second["next"])
        self.assertEqual(session.calls[0][1]["timeout"], 8.0)
        self.assertFalse(session.calls[0][1]["allow_redirects"])

    def test_recent_follows_apple_pagination_beyond_ten_pages(self):
        responses = {}
        for index in range(12):
            path = AppleMusicClient.RECENT + (f"?offset={index}" if index else "")
            responses[path] = {"data": [], "next": AppleMusicClient.RECENT + f"?offset={index+1}"}
        client, _ = self.client(responses)
        cursor = None
        for _ in range(12):
            page = client.recent(cursor)
            cursor = page["next"]
        self.assertEqual(cursor, AppleMusicClient.RECENT + "?offset=12")
        self.assertFalse(page["truncated"])

    def test_recent_cursor_retry_is_cached_and_preserves_next_page(self):
        base = AppleMusicClient.RECENT
        cursor, next_cursor = base + "?offset=10", base + "?offset=20"
        resource = lambda identifier: {"id": identifier, "type": "library-albums", "attributes": {"name": identifier}}
        client, session = self.client({base: {"data": [resource("a")], "next": cursor},
                                       cursor: {"data": [resource("b")], "next": next_cursor},
                                       next_cursor: {"data": [resource("c")]}})
        client.recent()
        first = client.recent(cursor)
        first["items"][0]["title"] = "caller mutation"
        retry = client.recent(cursor)
        self.assertEqual(retry["items"][0]["title"], "b")
        self.assertEqual(retry["next"], next_cursor)
        self.assertEqual(client._recent_pages, 2)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(client.recent(next_cursor)["items"][0]["id"], "c")

    def test_invalid_page_does_not_consume_items_or_page_budget(self):
        base, cursor = AppleMusicClient.RECENT, AppleMusicClient.RECENT + "?offset=10"
        resource = {"id": "b", "type": "library-albums", "attributes": {"name": "b"}}
        client, session = self.client({base: {"data": [], "next": cursor},
                                      cursor: {"data": [resource, {"id": "malformed"}]}})
        client.recent()
        with self.assertRaises(AppleMusicError):
            client.recent(cursor)
        self.assertEqual(client._recent_pages, 1)
        self.assertEqual(client._recent_seen, set())
        self.assertEqual(client._recent_next, cursor)
        session.responses[cursor] = {"data": [resource], "next": "https://attacker.example/v1/x"}
        with self.assertRaises(AppleMusicError):
            client.recent(cursor)
        self.assertEqual(client._recent_pages, 1)
        self.assertEqual(client._recent_seen, set())
        session.responses[cursor] = {"data": [resource]}
        self.assertEqual(client.recent(cursor)["items"][0]["id"], "b")
        self.assertEqual(client._recent_pages, 2)

    def test_concurrent_reset_cannot_inherit_inflight_old_page(self):
        base, cursor = AppleMusicClient.RECENT, AppleMusicClient.RECENT + "?offset=10"
        resource = lambda identifier: {"id": identifier, "type": "library-albums", "attributes": {"name": identifier}}
        client, _ = self.client({base: {"data": [resource("old-a")], "next": cursor}})
        client.recent()
        fetch_started, release_fetch, reset_started = threading.Event(), threading.Event(), threading.Event()
        def get(path, **kwargs):
            if path == cursor:
                fetch_started.set()
                if not release_fetch.wait(2):
                    raise RuntimeError("test fetch timed out")
                return {"data": [resource("old-b")]}
            return {"data": [resource("new-a")]}
        client._get = get
        def reset():
            reset_started.set()
            return client.recent(None)
        with ThreadPoolExecutor(max_workers=2) as executor:
            old = executor.submit(client.recent, cursor)
            self.assertTrue(fetch_started.wait(1))
            fresh = executor.submit(reset)
            self.assertTrue(reset_started.wait(1))
            release_fetch.set()
            self.assertEqual(old.result(2)["items"][0]["id"], "old-b")
            self.assertEqual(fresh.result(2)["items"][0]["id"], "new-a")
        self.assertEqual(client._recent_pages, 1)
        self.assertEqual(client._recent_seen, {("library-albums", "new-a")})
        self.assertNotIn(cursor, client._recent_cache)

    def test_refuses_cross_origin_pagination_before_token_transmission(self):
        client, session = self.client({AppleMusicClient.RECENT: {"data": [], "next": "https://attacker.example/v1/x"}})
        with self.assertRaises(AppleMusicError):
            client.recent()
        self.assertEqual(len(session.calls), 1)

    def test_library_album_keeps_only_library_members_not_full_catalog_album(self):
        client, session = self.client({
            "/v1/me/library/albums/partial/tracks": {"data": [library_song("one", 1)], "next": "/v1/me/library/albums/partial/tracks?offset=1"},
            "/v1/me/library/albums/partial/tracks?offset=1": {"data": [library_song("three", 3)]},
        })
        result = client.resolve({"id": "partial", "kind": "album", "_resource": {"attributes": {"trackCount": 2}}})
        self.assertEqual([item["catalog_id"] for item in result["tracks"]], ["1", "3"])
        self.assertEqual((result["total"], result["unavailable"]), (2, 0))
        self.assertTrue(all("/me/library/albums/" in call[0] for call in session.calls))
        # Our own params on every page (Apple's next drops them), the offset taken from next.
        self.assertEqual([call[1]["params"] for call in session.calls],
                         [{"include": "catalog", "limit": 50}, {"include": "catalog", "limit": 50, "offset": 1}])

    def test_private_playlist_uses_library_tracks_and_preserves_duplicates(self):
        client, _ = self.client({"/v1/me/library/playlists/private/tracks": {
            "data": [library_song("two", 2), library_song("one", 1), library_song("two", 2)]}})
        result = client.resolve({"id": "private", "kind": "playlist"})
        self.assertEqual([item["catalog_id"] for item in result["tracks"]], ["2", "1", "2"])

    def test_unmapped_track_refuses_entire_item(self):
        client, _ = self.client({"/v1/me/library/albums/a/tracks": {
            "data": [library_song("one", 1), library_song("upload", None)]}})
        with self.assertRaises(MusicUnavailable):
            client.resolve({"id": "a", "kind": "album"})

    def test_library_catalog_relationship_is_used_without_title_search(self):
        client, session = self.client({"/v1/me/library/songs/private/catalog": {"data": [catalog(3)]}})
        result = client.resolve({"id": "private", "kind": "song", "_resource": {"id": "private", "type": "library-songs"}})
        self.assertEqual(result["tracks"][0]["catalog_id"], "3")
        self.assertEqual(len(session.calls), 1)

    def test_song_link_is_normalized_using_actual_related_album(self):
        song = catalog(3)
        song["attributes"]["url"] = "https://music.apple.com/ca/song/track/3"
        client, _ = self.client({
            "/v1/me/library/songs/private/catalog": {"data": [song]},
            "/v1/me/storefront": {"data": [{"id": "ca"}]},
            "/v1/catalog/ca/songs/3/albums": {"data": [{"id": "900", "type": "albums", "attributes": {"url": "https://music.apple.com/ca/album/actual/900"}}]},
        })
        result = client.resolve({"id": "private", "kind": "song", "_resource": {"id": "private", "type": "library-songs"}})
        self.assertEqual(result["tracks"][0]["url"], "https://music.apple.com/ca/album/actual/900?i=3")

    def test_network_errors_are_sanitized(self):
        client, _ = self.client({AppleMusicClient.RECENT: RuntimeError("secret user token")})
        with self.assertRaises(AppleMusicError) as error:
            client.recent()
        self.assertNotIn("secret", str(error.exception))


class FakeItem:
    def __init__(self, identifier, duration="0:03:30"):
        self.title = "Song " + str(identifier)
        self.resources = [SimpleNamespace(uri=f"x-sonos-http:song%3a{identifier}.mp4", duration=duration)]
        self.didl_metadata = "<test/>"
        self.creator, self.album = "Artist", "Album"
        self.album_art_uri = f"/getaa?s=1&u=x-sonos-http%3asong%253a{identifier}.mp4"


class FakeClock:
    """A fake monotonic clock: ``sleep`` advances it; the speaker advances it per SOAP call."""
    def __init__(self, start=100.0):
        self.now_s = start
        self.sleeps = []
    def now(self):
        return self.now_s
    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now_s += max(0.0, seconds)
    def advance(self, seconds):
        self.now_s += seconds


class UPnPError(Exception):
    def __init__(self, code):
        super().__init__(f"UPnP Error {code}")
        self.error_code = str(code)


class FakeQueue(list):
    def __init__(self, values, revision, total):
        super().__init__(values)
        self.update_id, self.total_matches = revision, total


class FakeSpeaker:
    def __init__(self):
        self.uid, self.player_name, self.ip_address = "ROOM", "Den", "192.168.1.50"
        self.is_satellite, self.is_bridge = False, False
        self.zone_group_state = SimpleNamespace(clear_cache=lambda: None)
        self.group = SimpleNamespace(uid="GROUP", coordinator=self, members={self}, volume=25)
        self.all_zones, self.visible_zones = {self}, {self}
        self.items = [FakeItem(90), FakeItem(91)]
        self.revision = 10
        self.play_mode = "NORMAL"
        self.available_actions = ["Next", "Previous", "Play", "SeekTrackNr"]
        self.played, self.skips, self.removals = [], [], []
        self.seeks = []
        self.avTransport = SimpleNamespace(RemoveTrackRangeFromQueue=self.remove_range,
                                           SetAVTransportURI=lambda *a, **k: None,
                                           Seek=self.seek_action, Play=self.play_action,
                                           Next=lambda *a, **k: self.next())
        self.track = {"uri": "song:90", "playlist_position": "1", "title": "Old song", "artist": "Artist"}
        self.fail_enqueue_at = None
        self.enqueue_count = 0
        self.external_after_append = False
        self.fail_start = False
        # K3 section 17.1: positional inserts, ReorderTracksInQueue, SetPlayMode, Previous, REL_TIME
        # seeks with a TRANSITIONING script, and a per-call latency on an optional fake clock.
        self.transport_state = "PLAYING"
        self.media_uri = "x-rincon-queue:ROOM#0"
        self.clock = None
        self.latency = 0.05
        self.calls = []
        self.on_call = None
        self.queue_reads = []
        self.inserts = []
        self.reorders = []
        self.play_modes = []
        self.previous_calls = 0
        self.rel_seeks = []
        self.seek_script = None       # {"transition_s": 2.65, "then": "PLAYING", "never": False}
        self._seek_until = None
        self.enqueue_error = None     # raised by add_share_link_to_queue (nothing inserted)
        self.reorder_error = None
        self.play_mode_error = None
        self.play_mode_sticks = True
        self.avTransport.ReorderTracksInQueue = self.reorder
        self.avTransport.SetPlayMode = self.set_play_mode
        self.avTransport.Previous = self.previous_action
    def tick(self, name):
        self.calls.append(name)
        if self.clock is not None:
            self.clock.advance(self.latency)
        if self.on_call is not None:
            self.on_call(len(self.calls), name)
    def get_current_track_info(self):
        self.tick("GetPositionInfo")
        return dict(self.track)
    def get_current_transport_info(self):
        self.tick("GetTransportInfo")
        if self._seek_until is not None:
            if self.clock is not None and self.clock.now() < self._seek_until:
                return {"current_transport_state": "TRANSITIONING"}
            self.transport_state, self._seek_until = self.seek_script.get("then", "PLAYING"), None
        return {"current_transport_state": self.transport_state}
    def get_current_media_info(self):
        self.tick("GetMediaInfo")
        return {"uri": self.media_uri}
    def get_queue(self, start=0, max_items=100):
        self.tick("Browse")
        self.queue_reads.append((start, max_items))
        return FakeQueue(self.items[start:start+max_items], self.revision, len(self.items))
    def reorder(self, args, **kwargs):
        self.tick("ReorderTracksInQueue")
        if self.reorder_error is not None:
            raise self.reorder_error
        values = dict(args)
        if values["UpdateID"] != self.revision:
            raise UPnPError(712)
        start, count, before = values["StartingIndex"], values["NumberOfTracks"], values["InsertBefore"]
        self.reorders.append((start, count, before))
        block = self.items[start - 1:start - 1 + count]
        del self.items[start - 1:start - 1 + count]
        if before > start:
            before -= count
        self.items[before - 1:before - 1] = block
        self.revision += 1
    def set_play_mode(self, args, **kwargs):
        self.tick("SetPlayMode")
        if self.play_mode_error is not None:
            raise self.play_mode_error
        mode = dict(args)["NewPlayMode"]
        self.play_modes.append(mode)
        if self.play_mode_sticks:
            self.play_mode = mode
    def previous_action(self, args, **kwargs):
        self.tick("Previous")
        self.previous_calls += 1
    def next(self):
        self.skips.append("next")
    def previous(self):
        self.skips.append("previous")
    def remove_range(self, args, **kwargs):
        values = dict(args)
        if values["UpdateID"] != self.revision:
            raise RuntimeError("stale update id")
        start = values["StartingIndex"] - 1
        self.removals.append((start, values["NumberOfTracks"]))
        del self.items[start:start+values["NumberOfTracks"]]
        self.revision += 1
    def play_from_queue(self, index):
        if self.fail_start:
            raise RuntimeError("secret service token")
        self.played.append(index)
    def seek_action(self, args, **kwargs):
        self.tick("Seek")
        values = dict(args)
        target = values["Target"]
        if values.get("Unit") == "REL_TIME":
            self.rel_seeks.append(target)
            self.track["position"] = target  # RelTime reads the target from the first read (LC W2)
            script = self.seek_script or {}
            if not script.get("never") and self.clock is not None:
                self._seek_until = self.clock.now() + script.get("transition_s", 0.5)
            return
        self.seeks.append(target)
        self.track["playlist_position"] = str(target)
    def play_action(self, args, **kwargs):
        self.play_from_queue(int(self.track["playlist_position"]) - 1)
    def add_share_link_to_queue(self, url, position=0, as_next=False, **kwargs):
        self.tick("AddURIToQueue")
        self.enqueue_count += 1
        if self.enqueue_count == self.fail_enqueue_at:
            raise RuntimeError("secret service token")
        if self.enqueue_error is not None:
            raise self.enqueue_error
        from urllib.parse import parse_qs, urlsplit
        identifier = parse_qs(urlsplit(url).query)["i"][0]
        self.inserts.append((position, identifier, as_next))
        if position:
            if not 1 <= position <= len(self.items) + 1:
                raise UPnPError(402)
            self.items.insert(position - 1, FakeItem(identifier))
            placed = position
        else:
            self.items.append(FakeItem(identifier))
            placed = len(self.items)
        self.revision += 1
        if self.external_after_append:
            self.items.insert(0, FakeItem(777))
            self.revision += 1
        return placed


class MemoryStore:
    def __init__(self):
        self.saved = None
        self.saves = 0
    def save(self, data):
        self.saved = data
        self.saves += 1
    def load(self):
        return dict(self.saved or {})


class DelayedVolumeGroup:
    def __init__(self, group, readbacks):
        self.uid, self.coordinator, self.members = group.uid, group.coordinator, group.members
        self.readbacks = list(readbacks)
        self.writes = []
        self.current = group.volume
        self.on_read = None
    @property
    def volume(self):
        if self.writes and self.readbacks:
            self.current = self.readbacks.pop(0)
        if self.on_read:
            self.on_read()
        return self.current
    @volume.setter
    def volume(self, value):
        self.writes.append(value)


class SonosTests(unittest.TestCase):
    def adapter(self):
        speaker, store = FakeSpeaker(), MemoryStore()
        adapter = SonosAdapter("192.168.1.50", soco_factory=lambda host: speaker,
                               share_link_factory=lambda value: value, recovery_store=store,
                               shuffle_store=MemoryStore())
        return adapter, speaker, store
    @staticmethod
    def songs():
        return [{"catalog_id": str(n), "title": "Song " + str(n),
                 "url": f"https://music.apple.com/ca/album/a/999?i={n}"} for n in (1, 2)]
    def test_read_state_and_group_guard_prevent_retargeted_volume(self):
        adapter, speaker, _ = self.adapter()
        state = adapter.read_state()
        self.assertTrue(state["online"])
        speaker.group.uid = "NEWGROUP"
        with self.assertRaises(GroupChanged):
            adapter.set_volume(60, state["group_revision"])
        self.assertEqual(speaker.group.volume, 25)
    def test_volume_waits_for_delayed_group_readback_without_repeating_write(self):
        adapter, speaker, _ = self.adapter()
        state = adapter.read_state()
        speaker.group = DelayedVolumeGroup(speaker.group, [25, 25, 60])
        now = [0.0]
        with patch("control_center.sonos.time.monotonic", side_effect=lambda: now[0]), \
             patch("control_center.sonos.time.sleep", side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds)):
            confirmed = adapter.set_volume(60, state["group_revision"])
        self.assertEqual(confirmed["volume"], 60)
        self.assertEqual(speaker.group.writes, [60])
        self.assertGreaterEqual(now[0], 0.1)
    def test_volume_unconfirmed_readback_times_out_without_false_success_or_replay(self):
        adapter, speaker, _ = self.adapter()
        state = adapter.read_state()
        speaker.group = DelayedVolumeGroup(speaker.group, [25])
        now = [0.0]
        with patch("control_center.sonos.time.monotonic", side_effect=lambda: now[0]), \
             patch("control_center.sonos.time.sleep", side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds)):
            with self.assertRaisesRegex(SonosError, "not confirmed"):
                adapter.set_volume(60, state["group_revision"])
        self.assertEqual(speaker.group.writes, [60])
        self.assertEqual(now[0], 2.0)
        self.assertEqual(adapter._last_state["volume"], 25)
    def test_volume_confirmation_aborts_if_group_changes_during_propagation(self):
        adapter, speaker, _ = self.adapter()
        state = adapter.read_state()
        speaker.group = DelayedVolumeGroup(speaker.group, [25, 60])
        speaker.group.on_read = lambda: setattr(speaker.group, "uid", "EXTERNAL_GROUP")
        with patch("control_center.sonos.time.sleep"):
            with self.assertRaises(GroupChanged):
                adapter.set_volume(60, state["group_revision"])
        self.assertEqual(speaker.group.writes, [60])
    def test_track_guard_blocks_stale_confirmation(self):
        adapter, speaker, _ = self.adapter()
        state = adapter.read_state()
        speaker.track["uri"] = "song:changed"
        with self.assertRaises(TrackChanged):
            adapter.transport("next", state["group_revision"], state["track_id"])
        self.assertEqual(speaker.skips, [])
    def test_previous_seeks_preceding_track_without_restart_even_mid_song(self):
        adapter, speaker, _ = self.adapter()
        speaker.track.update(playlist_position="2", position="0:02:30")
        state = adapter.read_state()
        self.assertTrue(state["can_previous"])
        adapter.transport("previous", state["group_revision"], state["track_id"])
        self.assertEqual(speaker.seeks, [1])
        self.assertEqual(speaker.skips, [])
    def test_previous_disabled_at_start_and_with_unknown_shuffle_history(self):
        adapter, speaker, _ = self.adapter()
        state = adapter.read_state()
        self.assertFalse(state["can_previous"])
        self.assertIn("no preceding", state["previous_reason"])
        speaker.track["playlist_position"] = "2"
        speaker.play_mode = "SHUFFLE"
        speaker.available_actions.remove("Previous")
        state = adapter.read_state()
        self.assertFalse(state["can_previous"])
        with self.assertRaises(SonosError):
            adapter.transport("previous", state["group_revision"], state["track_id"])
        self.assertEqual((speaker.seeks, speaker.previous_calls), ([], 0))

    def test_previous_under_sonos_shuffle_uses_the_previous_action_when_offered(self):
        # C5-19 (OQ-6 pending R3): Sonos picks the last played track itself; no TRACK_NR seek.
        adapter, speaker, _ = self.adapter()
        speaker.track["playlist_position"] = "2"
        speaker.play_mode = "SHUFFLE_NOREPEAT"
        state = adapter.read_state()
        self.assertTrue(state["can_previous"])
        self.assertEqual(state["previous_reason"], "")
        adapter.transport("previous", state["group_revision"], state["track_id"])
        self.assertEqual((speaker.seeks, speaker.previous_calls), ([], 1))
    def test_previous_repeat_all_wraps_to_last_queue_track(self):
        adapter, speaker, _ = self.adapter()
        speaker.play_mode = "REPEAT_ALL"
        state = adapter.read_state()
        self.assertTrue(state["can_previous"])
        adapter.transport("previous", state["group_revision"], state["track_id"])
        self.assertEqual(speaker.seeks, [2])
    def test_queue_staging_then_replacement_preserves_order(self):
        adapter, speaker, store = self.adapter()
        state = adapter.read_state()
        result = adapter.play_items(self.songs(), state["group_revision"])
        self.assertTrue(result["online"])
        self.assertEqual([item.title for item in speaker.items], ["Song 1", "Song 2"])
        self.assertEqual(speaker.removals, [(0, 2)])
        self.assertEqual(speaker.played, [0])
        self.assertEqual([item["title"] for item in store.saved["items"]], ["Song 90", "Song 91"])
    def test_failed_second_append_rolls_back_only_own_verified_tail(self):
        adapter, speaker, _ = self.adapter()
        state = adapter.read_state()
        speaker.fail_enqueue_at = 2
        with self.assertRaises(QueueReplacementFailed) as error:
            adapter.play_items(self.songs(), state["group_revision"])
        self.assertFalse(error.exception.partial)
        self.assertTrue(error.exception.recovery_saved)
        self.assertEqual([item.title for item in speaker.items], ["Song 90", "Song 91"])
        self.assertEqual(speaker.removals, [(2, 1)])
        self.assertEqual(speaker.played, [])
    def test_external_queue_change_is_not_overwritten(self):
        adapter, speaker, _ = self.adapter()
        state = adapter.read_state()
        speaker.external_after_append = True
        with self.assertRaises(QueueReplacementFailed) as error:
            adapter.play_items(self.songs(), state["group_revision"])
        self.assertTrue(error.exception.partial)
        self.assertEqual(speaker.removals, [])
        self.assertEqual(speaker.played, [])
        self.assertEqual(speaker.items[0].title, "Song 777")
    def test_play_failure_reports_partial_and_keeps_recovery(self):
        adapter, speaker, store = self.adapter()
        state = adapter.read_state()
        speaker.fail_start = True
        with self.assertRaises(QueueReplacementFailed) as error:
            adapter.play_items(self.songs(), state["group_revision"])
        self.assertTrue(error.exception.partial)
        self.assertIsNotNone(store.saved)
        self.assertNotIn("secret", str(error.exception))
    def test_non_song_url_is_rejected_before_queue_mutation(self):
        adapter, speaker, _ = self.adapter()
        state = adapter.read_state()
        with self.assertRaises(Exception):
            adapter.play_items([{"catalog_id": "1", "url": "https://music.apple.com/ca/album/a/99"}], state["group_revision"])
        self.assertEqual(speaker.enqueue_count, 0)


if __name__ == "__main__":
    unittest.main()
