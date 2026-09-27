"""Home warm-up (firmware/ARTWORK2.md section 11.4).

While the controller is on Home and the knob is connected, the runtime keeps a copy of
Recent page 1: fetched on the lookahead lane (never the UI thread) 10 s after startup
and then every 10 minutes, or taken from the controller when Recent is left (no extra
request). Its covers are prefetched and, with artwork2, named after Now Playing on the
Home cover list. It changes nothing on screen, entering Recent still loads page 1 fresh,
errors are silent, and it never runs without Apple Music credentials, while sign-in
expired, or with artwork off. AppleMusicClient.recent_preview is the read-only page-1
fetch it uses: the same request and parsing, and the browsing visit is left alone.
No network, no port, no window.
"""
from copy import deepcopy
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from control_center.apple_music import AppleMusicClient, AppleMusicError
from control_center.controller import Controller
from control_center.runtime import WARMUP_FIRST_SECONDS, WARMUP_INTERVAL_SECONDS, Runtime
from control_center.simulation import SimulatedSonos
from test_cc_art_swap import CoverApple, cover_url
from test_cc_controller import Clock, ManualExecutor
from test_cc_media_runtime import NOW_PLAYING, FakeArtwork, FakeIcons, IconWindows, MediaCase, MediaDevice, jpeg_key

EXPIRED = "Apple Music authorization expired or access was denied. Reconnect in settings."
OFFLINE = "Apple Music could not be reached. Check the connection and retry."


class FakeTime:
    """Stands in for the `time` module inside control_center.runtime."""

    def __init__(self, clock):
        self.clock = clock

    def monotonic(self):
        return self.clock()

    def sleep(self, seconds):
        self.clock.advance(max(0.0, seconds))


class WarmApple(CoverApple):
    """A library adapter with the live client's warm-up interface.

    ``authorized`` is what the credential store holds now; ``has_credentials()`` answers
    from the copy last read, which ``refresh_credentials()`` re-reads (as the client does).
    ``previews`` records the page-1 requests (threads), ``store_reads`` the store reads.
    """

    def __init__(self, authorized=True):
        super().__init__()
        self.authorized = self.known = authorized
        self.fail = None
        self.recents, self.previews, self.store_reads = [], [], []

    def has_credentials(self):
        return self.known

    def refresh_credentials(self):
        self.store_reads.append(threading.current_thread().name)
        self.known = self.authorized
        return self.known

    def recent_page(self, offset=0, **kwargs):
        # The v7 flat-list pager (K3 section 9.8.6); recorded like the v6 cursors (None = page 1).
        self.recents.append((None if not offset else str(offset), threading.current_thread().name))
        return super().recent_page(offset, **kwargs)

    def recent_preview(self, limit=10):
        if not self.authorized:  # like AppleMusicClient._get: refused before any request
            raise AppleMusicError("Connect Apple Music in companion settings first.")
        self.previews.append(threading.current_thread().name)
        if self.fail is not None:
            raise self.fail
        return {"items": deepcopy(CoverApple._library(self)[:limit]), "next": None}   # read-only: no visit, no pager call


class WarmupCase(MediaCase):
    authorized = True

    def setUp(self):
        executor = patch("control_center.runtime.ThreadPoolExecutor", ManualExecutor)
        executor.start()
        self.addCleanup(executor.stop)
        self.clock = Clock()
        timing = patch("control_center.runtime.time", FakeTime(self.clock))
        timing.start()
        self.addCleanup(timing.stop)
        self.started = self.clock()
        self.c = Controller(clock=self.clock)
        self.sonos = SimulatedSonos()
        self.c.complete(self.c.request("state"), self.sonos.read_state())
        self.c.drain()
        self.c.last_poll = self.clock()
        self.artwork, self.icons = FakeArtwork(), FakeIcons()
        self.device = self.make_device()
        self.apple = WarmApple(self.authorized)
        self.runtime = Runtime(self.c, self.sonos, self.apple, IconWindows(), self.device,
                               artwork=self.artwork, icons=self.icons)
        self.addCleanup(self.runtime.close)
        self.connect()

    def warmups(self):
        return [job for job in self.runtime.lookahead.jobs if job[1] == self.runtime._warmup_job]

    def at(self, seconds):
        """Poll at ``seconds`` after startup."""
        self.clock.now = self.started + seconds
        self.runtime.poll()

    def run_warmup(self):
        (job,) = self.warmups()
        self.runtime.lookahead.jobs.remove(job)
        self.runtime.lookahead.jobs.insert(0, job)
        self.runtime.lookahead.run_next()
        self.runtime.poll()

    def warm_tokens(self):
        return [(urls, page) for urls, page in self.artwork.prefetches if page and page[0] == "warmup"]


class ScheduleTests(WarmupCase):
    def test_ten_seconds_after_startup_then_every_ten_minutes(self):
        self.assertEqual((WARMUP_FIRST_SECONDS, WARMUP_INTERVAL_SECONDS), (10.0, 600.0))
        self.at(9.9)
        self.assertEqual(self.warmups(), [])
        self.at(10.0)
        self.assertEqual(len(self.warmups()), 1)
        self.assertEqual((self.apple.previews, self.apple.store_reads), ([], []), "the UI thread only queues it")
        self.run_warmup()
        self.assertEqual((len(self.apple.previews), len(self.apple.store_reads)), (1, 1))
        self.assertEqual([item["id"] for item in self.runtime.warmup_page["items"]], [str(i) for i in range(10)])
        self.assertEqual(self.warm_tokens(), [([cover_url(i) for i in range(10)], ("warmup", 1))],
                         "its covers are prefetched in index order")
        self.at(609.9)
        self.assertEqual(self.warmups(), [])
        self.at(610.0)
        self.assertEqual(len(self.warmups()), 1, "every 10 minutes")
        self.at(1900.0)
        self.assertEqual(len(self.warmups()), 1, "one at a time")
        self.run_warmup()
        self.assertEqual(len(self.apple.previews), 2)
        self.assertEqual(self.warm_tokens()[-1][1], ("warmup", 2))

    def test_it_changes_nothing_on_screen(self):
        self.at(10.0)
        before = (self.runtime.frame(), self.c.control_id, self.c.screen.status, self.c.notice, len(self.c.pending))
        self.run_warmup()
        self.assertEqual((self.runtime.frame(), self.c.control_id, self.c.screen.status, self.c.notice,
                          len(self.c.pending)), before)
        self.assertEqual([command for command in self.device.commands if command[0] == "enter"], [])
        self.assertEqual(self.c.screen.mode, "home")

    def test_errors_are_silent_and_wait_for_the_next_tick(self):
        self.apple.fail = RuntimeError(OFFLINE)
        self.at(10.0)
        before = (self.runtime.frame(), self.c.screen.status, self.c.notice)
        self.run_warmup()
        self.assertIsNone(self.runtime.warmup_page)
        self.assertEqual((self.runtime.frame(), self.c.screen.status, self.c.notice), before)
        self.assertFalse(self.runtime.music_signin_expired)
        self.at(300.0)
        self.assertEqual(self.warmups(), [], "no retry before the next tick")
        self.apple.fail = None
        self.at(610.0)
        self.run_warmup()
        self.assertIsNotNone(self.runtime.warmup_page)

    def test_a_job_that_runs_after_leaving_home_requests_nothing(self):
        self.at(10.0)
        self.assertEqual(len(self.warmups()), 1)
        self.c.button(1)                  # Browse before the lane runs it
        self.settle()
        self.run_warmup()
        self.assertEqual((self.apple.previews, self.apple.store_reads), ([], []))
        self.assertIsNone(self.runtime.warmup_page)
        self.assertFalse(self.runtime.music_signin_expired)
        self.assertEqual((self.c.screen.mode, self.c.screen.loading, self.c.notice), ("recent", True, ""))

    def test_only_on_home_with_the_knob_connected(self):
        self.c.button(2)                  # Tracks
        self.settle()
        self.at(10.0)
        self.assertEqual(self.warmups(), [])
        self.c.button(0, self.c.control_id)   # Back: Home
        self.settle()
        self.assertEqual(len(self.warmups()), 1, "due, so it runs once Home is back")
        self.run_warmup()
        self.device.events.put({"kind": "disconnected", "message": "Knob disconnected"})
        self.runtime.poll()
        self.at(700.0)
        self.assertEqual(self.warmups(), [])
        self.assertEqual(self.artwork.prefetches[-1], ([], None), "its unstarted covers are dropped")


class HomeCoverTests(WarmupCase):
    def keys(self):
        return [key for key, _ in self.device.last_wanted("cover")]

    def test_its_covers_are_named_on_home_after_now_playing(self):
        self.c.state["artwork_url"] = NOW_PLAYING
        self.artwork.load(NOW_PLAYING, *[cover_url(i) for i in range(10)])
        self.runtime.poll()
        self.assertEqual(self.keys(), [jpeg_key(NOW_PLAYING)])
        self.at(10.0)
        self.run_warmup()
        self.assertEqual(self.runtime.frame()["artKey"], jpeg_key(NOW_PLAYING), "Home still shows Now Playing")
        self.assertEqual(self.keys(), [jpeg_key(NOW_PLAYING)] + [jpeg_key(i) for i in range(10)])

    def test_at_most_ten_covers_even_from_a_longer_reply(self):
        self.c.state["artwork_url"] = NOW_PLAYING
        self.artwork.load(NOW_PLAYING, *[cover_url(i) for i in range(12)])
        self.apple.count = 12
        longer = {"items": CoverApple._library(self.apple)[:12], "next": None}
        self.assertEqual(len(longer["items"]), 12)
        self.apple.recent_preview = lambda limit=10: deepcopy(longer)
        self.at(10.0)
        self.run_warmup()
        self.assertEqual(len(self.runtime.warmup_page["items"]), 10)
        self.assertEqual(self.warm_tokens(), [([cover_url(i) for i in range(10)], ("warmup", 1))])
        self.assertEqual(self.keys(), [jpeg_key(NOW_PLAYING)] + [jpeg_key(i) for i in range(10)])

    def test_only_prepared_covers_are_named(self):
        self.artwork.load(cover_url(2), cover_url(7))
        self.at(10.0)
        self.run_warmup()
        self.assertEqual(self.keys(), [jpeg_key(2), jpeg_key(7)])
        self.artwork.load(cover_url(0))   # the prefetch delivers another one
        self.runtime.poll()
        self.assertEqual(self.keys(), [jpeg_key(0), jpeg_key(2), jpeg_key(7)])

    def test_leaving_recent_uses_the_controllers_page_1(self):
        self.load_recent()
        self.assertEqual([cursor for cursor, _ in self.apple.recents], [None])
        self.c.button(0, self.c.control_id)   # Back: Home
        self.settle()
        self.assertEqual([item["id"] for item in self.runtime.warmup_page["items"]], [str(i) for i in range(10)])
        self.assertEqual(self.apple.previews, [], "no extra request")
        self.assertEqual(self.warm_tokens()[-1][0], [cover_url(i) for i in range(10)])
        self.at(10.0)
        self.assertEqual(self.warmups(), [], "the copy is fresh: the next fetch is 10 minutes away")
        self.artwork.load(cover_url(4))
        self.runtime.poll()
        self.assertIn(jpeg_key(4), self.keys())

    def test_entering_recent_still_loads_page_1_fresh(self):
        self.at(10.0)
        self.run_warmup()
        self.c.button(1)                  # Browse
        self.assertEqual((self.c.screen.mode, self.c.screen.loading, self.c.screen.pages),
                         ("recent", True, []))
        self.settle()
        self.assertEqual(self.runtime.frame()["activity"], "loading")
        self.runtime.library.run_next()
        self.runtime.poll()
        self.assertEqual([cursor for cursor, _ in self.apple.recents], [None], "a fresh page-1 request")
        self.assertEqual(self.c.screen.loading, False)

    def test_a_cc52_knob_gets_the_host_side_warmup_only(self):
        self.device.media_capability = None
        self.runtime.poll()
        self.assertFalse(self.runtime.artwork2)
        wanted = len(self.device.wanted)
        self.at(10.0)
        self.run_warmup()
        self.assertEqual(self.warm_tokens(), [([cover_url(i) for i in range(10)], ("warmup", 1))])
        self.assertEqual(len(self.device.wanted), wanted, "no knob lists without artwork2")


class GateTests(WarmupCase):
    def test_never_without_credentials(self):
        self.apple.authorized = self.apple.known = False
        self.at(10.0)
        self.assertEqual(self.apple.store_reads, [], "the UI thread never reads the store")
        self.run_warmup()                 # the lane asks the store: no token, so no request
        self.at(700.0)
        self.run_warmup()
        self.assertEqual((len(self.apple.store_reads), self.apple.previews), (2, []))
        self.assertIsNone(self.runtime.warmup_page)
        self.assertFalse(self.runtime.music_signin_expired, "not signed in yet is not an expired sign-in")
        self.assertEqual((self.warm_tokens(), self.c.screen.status, self.c.notice), ([], "", ""))
        self.load_recent()
        self.c.button(0, self.c.control_id)   # leaving Recent: the controller's page is not used either
        self.settle()
        self.assertEqual(self.warm_tokens(), [])
        self.assertEqual(self.device.last_wanted("cover"), [])

    def test_an_authorization_saved_after_startup_is_found_at_the_next_tick(self):
        self.apple.authorized = self.apple.known = False
        self.at(10.0)
        self.run_warmup()
        self.assertIsNone(self.runtime.warmup_page)
        self.apple.authorized = True      # authorized in the app: only the store has the token
        self.assertFalse(self.apple.has_credentials())
        self.at(300.0)
        self.assertEqual(self.warmups(), [], "the next tick, not before")
        self.at(610.0)
        self.run_warmup()
        self.assertEqual(len(self.apple.previews), 1)
        self.assertTrue(self.apple.has_credentials())
        self.assertEqual(self.warm_tokens(), [([cover_url(i) for i in range(10)], ("warmup", 1))])
        self.artwork.load(cover_url(3))
        self.runtime.poll()
        self.assertEqual([key for key, _ in self.device.last_wanted("cover")], [jpeg_key(3)])

    def test_never_with_artwork_off(self):
        self.runtime.artwork_enabled = False
        self.at(10.0)
        self.at(700.0)
        self.assertEqual((self.warmups(), self.apple.previews, self.warm_tokens()), ([], [], []))

    def test_never_while_sign_in_expired(self):
        self.apple.expired = True
        self.c.button(1)                  # Browse: the foreground load fails for authorization
        self.settle()
        self.runtime.library.run_next()
        self.runtime.poll()
        self.assertEqual(self.runtime.frame()["title"], "Apple Music sign-in expired")
        self.assertTrue(self.runtime.music_signin_expired)
        self.c.button(0, self.c.control_id)   # Back: Home
        self.settle()
        self.at(10.0)
        self.at(700.0)
        self.assertEqual(self.warmups(), [])
        self.apple.expired = False
        self.load_recent()                # a successful load ends it
        self.assertFalse(self.runtime.music_signin_expired)
        self.c.button(0, self.c.control_id)
        self.settle()
        self.assertEqual(len(self.warm_tokens()), 1)

    def test_a_warmup_that_finds_sign_in_expired_stops(self):
        self.apple.fail = RuntimeError(EXPIRED)
        self.at(10.0)
        self.run_warmup()
        self.assertTrue(self.runtime.music_signin_expired)
        self.assertEqual((self.c.screen.status, self.c.notice), ("", ""), "silent")
        self.at(700.0)
        self.at(1400.0)
        self.assertEqual(self.warmups(), [])

    def test_a_simulated_library_never_warms_up(self):
        self.runtime.apple = CoverApple()  # no has_credentials / recent_preview
        self.at(10.0)
        self.at(700.0)
        self.assertEqual(self.warmups(), [])


class ThreadTests(unittest.TestCase):
    """Real lanes: no Apple Music call ever runs on the UI (test) thread."""

    def setUp(self):
        self.c = Controller()
        sonos = SimulatedSonos()
        self.c.complete(self.c.request("state"), sonos.read_state())
        self.c.drain()
        self.c.last_poll = time.perf_counter() + 3600  # no Sonos polls meanwhile
        self.device = MediaDevice(None)
        self.apple = WarmApple()
        self.artwork = FakeArtwork()
        self.runtime = Runtime(self.c, sonos, self.apple, IconWindows(), self.device, artwork=self.artwork)
        self.addCleanup(self.runtime.close)
        self.runtime.device_connected = self.runtime.device_supported = True

    def until(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.runtime.poll()
            if predicate():
                return True
            time.sleep(0.005)
        return predicate()

    def test_no_ui_thread_network(self):
        ui = threading.current_thread().name
        self.runtime._warmup_due = 0.0   # due now instead of 10 s after startup
        self.assertTrue(self.until(lambda: self.runtime.warmup_page is not None))
        self.c.button(1)                  # Browse: the list's first page on the library lane
        self.assertTrue(self.until(lambda: self.c.recent.state == "ready"))
        self.assertEqual(len(self.apple.previews), 1)
        self.assertTrue(all(name.startswith("nanod-lookahead") for name in self.apple.previews), self.apple.previews)
        self.assertTrue(self.apple.store_reads and all(name.startswith("nanod-lookahead")
                                                       for name in self.apple.store_reads), self.apple.store_reads)
        cursors = dict(self.apple.recents)
        self.assertTrue(cursors[None].startswith("nanod-library"), cursors)
        self.assertNotIn(ui, self.apple.previews + [name for _, name in self.apple.recents])


class RecentPreviewTests(unittest.TestCase):
    """AppleMusicClient.recent_preview: read-only page 1 through the same request and parsing."""

    BASE = AppleMusicClient.RECENT

    def responses(self):
        def response(first, next_cursor):
            return {"data": [{"id": f"album-{i}", "type": "library-albums",
                              "attributes": {"name": f"Album {i}", "artistName": "Artist",
                                             "artwork": {"url": f"https://is1-ssl.mzstatic.com/image/thumb/a{i}/{{w}}x{{h}}bb.jpg"}}}
                             for i in range(first, first + 10)], "next": next_cursor}
        return {self.BASE: response(0, self.BASE + "?offset=10"),
                self.BASE + "?offset=10": response(10, self.BASE + "?offset=20"),
                self.BASE + "?offset=20": response(20, None)}

    def client(self):
        client = AppleMusicClient({}, session=object())
        responses, calls = self.responses(), []

        def get(path, *, params=None, **kwargs):
            calls.append((path, params))
            return deepcopy(responses[path])
        client._get = get
        return client, calls

    def visit_state(self, client):
        return (client._recent_pages, set(client._recent_seen), client._recent_next, deepcopy(client._recent_cache))

    def test_the_preview_is_page_1_and_leaves_the_visit_alone(self):
        client, calls = self.client()
        first = client.recent(None)
        client.recent(self.BASE + "?offset=10")
        state = self.visit_state(client)
        preview = client.recent_preview()
        self.assertEqual(preview, first, "the same item shape and next link as recent(None)")
        self.assertEqual(calls[-1], (self.BASE, {"limit": 10}), "the same request and bounds")
        self.assertEqual(self.visit_state(client), state, "no reset, no commit")
        third = client.recent(self.BASE + "?offset=20")       # More still continues the visit
        self.assertEqual(third["items"][0]["id"], "album-20")
        preview["items"].clear()
        self.assertEqual(len(client.recent(None)["items"]), 10, "the preview is the caller's own copy")

    def test_the_preview_validates_like_recent(self):
        client, _calls = self.client()
        client._get = lambda path, **kwargs: {"data": [{"id": "", "type": "library-albums"}]}
        with self.assertRaises(AppleMusicError):
            client.recent_preview()
        client._get = lambda path, **kwargs: {"data": [], "next": self.BASE}
        with self.assertRaises(AppleMusicError):
            client.recent_preview()

    def test_no_request_without_a_music_user_token(self):
        class Session:
            calls = []

            def get(self, *args, **kwargs):
                self.calls.append(args)
                raise AssertionError("no request without credentials")

        for loader in (None, lambda: {}):
            with self.subTest(loader=loader):
                client = AppleMusicClient({}, session=Session(), credential_loader=loader)
                self.assertFalse(client.has_credentials())
                with self.assertRaises(AppleMusicError) as raised:
                    client.recent_preview()
                self.assertIn("Connect Apple Music", str(raised.exception))
        self.assertEqual(Session.calls, [])

    def test_has_credentials_reads_no_store(self):
        def loader():
            raise AssertionError("has_credentials must not read the store")
        self.assertTrue(AppleMusicClient({"music_user_token": "x"}, session=object(),
                                         credential_loader=loader).has_credentials())
        for value in ("", None, 5):
            self.assertFalse(AppleMusicClient({"music_user_token": value}, session=object()).has_credentials())

    def test_refresh_credentials_rereads_the_store_without_a_request(self):
        saved = {}
        client = AppleMusicClient({}, session=object(), credential_loader=lambda: dict(saved))
        self.assertFalse(client.refresh_credentials())
        saved.update(developer_token="dev", music_user_token="user")
        self.assertFalse(client.has_credentials(), "has_credentials reads no store")
        self.assertTrue(client.refresh_credentials())
        self.assertTrue(client.has_credentials())
        self.assertTrue(AppleMusicClient({"music_user_token": "x"}, session=object()).refresh_credentials())

    def test_the_runtime_warms_up_a_real_client_once_its_store_has_a_token(self):
        body = self.responses()[self.BASE]

        class Session:
            def __init__(self):
                self.calls = []

            def get(self, url, **kwargs):
                self.calls.append(url)
                return SimpleNamespace(status_code=200, json=lambda: deepcopy(body))

        saved, foreground, background = {}, Session(), Session()
        client = AppleMusicClient({}, session=foreground, background_session=background,
                                  credential_loader=lambda: dict(saved))
        with patch("control_center.runtime.ThreadPoolExecutor", ManualExecutor):
            runtime = Runtime(Controller(), SimulatedSonos(), client, IconWindows(), MediaDevice(None),
                              artwork=FakeArtwork())
        self.addCleanup(runtime.close)
        runtime.device_connected = runtime.device_supported = True

        def tick():
            runtime._warmup_due = 0.0     # the next 10-minute tick, now
            runtime.poll()
            (job,) = [job for job in runtime.lookahead.jobs if job[1] == runtime._warmup_job]
            runtime.lookahead.jobs.remove(job)
            runtime.lookahead.jobs.insert(0, job)
            runtime.lookahead.run_next()
            runtime.poll()
        tick()                            # no token in the store: nothing is requested
        self.assertEqual((foreground.calls, background.calls, runtime.warmup_page), ([], [], None))
        self.assertFalse(runtime.music_signin_expired)
        saved.update(developer_token="dev", music_user_token="user")   # authorized after startup
        tick()
        self.assertEqual((foreground.calls, background.calls), ([], [AppleMusicClient.API + self.BASE]))
        self.assertEqual([item["id"] for item in runtime.warmup_page["items"]], [f"album-{i}" for i in range(10)])


if __name__ == "__main__":
    unittest.main()
