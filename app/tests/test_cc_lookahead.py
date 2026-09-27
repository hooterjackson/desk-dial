"""Recently Added visits and the lookahead lane on desktop v7 (CONTROL_CENTER_V5.md section 5.2, U5;
C5-1, C5-2).

The v6 page lookahead (More, adoption, pages) is retired by the flat list; its list cases live in
test_cc5_recent_list.py. Kept here (K3 section 17.1): the visit bookkeeping, the knob-reconnect
cases in their K3 form (a reconnect lands on Home, C5-2: a load still out is never asked for
twice and its late result never navigates), and the live client's lanes: the lookahead lane's
own session, a stale background request that never delays a new visit, and the Home warm-up
that never shares a session with Browse. No network, no port, no window.
"""
from copy import deepcopy
from pathlib import Path
from queue import Queue
import sys
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from control_center.apple_music import AppleMusicClient, AppleMusicError
from control_center.controller import Controller
from control_center.runtime import Runtime
from control_center.simulation import SimulatedSonos, SimulatedWindows
from cc5_support import Clock, FakeDevice, fail, recent_page, state


def home_controller(clock):
    c = Controller(clock=clock)
    c.complete(c.request("state"), state())
    c.drain()
    c.last_poll = clock()
    return c


class ReconnectTests(unittest.TestCase):
    """A knob reconnect re-enters Home (C5-2), whatever the list was doing."""

    def setUp(self):
        self.clock = Clock()
        self.c = home_controller(self.clock)

    def recents(self):
        return [e for e in self.c.drain() if e["kind"] in ("recent", "recent_lookahead")]

    def test_a_first_page_load_is_not_asked_again_after_a_reconnect(self):
        self.c.button(1)
        (load,) = self.recents()
        self.c.set_hardware(True)
        self.assertEqual(self.c.screen.mode, "home")
        self.assertEqual(self.recents(), [], "no second request")
        self.c.complete(load["request"], recent_page(0, 30))
        self.assertEqual(self.c.screen.mode, "home", "a late page never navigates")
        self.assertEqual(len(self.c.recent.items), 25, "it lands in the visit's list")

    def test_a_reconnect_on_a_loaded_list_asks_nothing(self):
        self.c.button(1)
        (load,) = self.recents()
        self.c.complete(load["request"], recent_page(0, 30))
        self.c.set_hardware(True)
        self.assertEqual(self.recents(), [])

    def test_a_prefetch_still_out_lands_silently_after_a_reconnect(self):
        self.c.button(1)
        (load,) = self.recents()
        self.c.complete(load["request"], recent_page(0, 60))
        self.c.position(10)
        (prefetch,) = self.recents()
        self.assertEqual(prefetch["kind"], "recent_lookahead")
        self.c.disconnected()
        self.c.set_hardware(True)
        self.c.complete(prefetch["request"], recent_page(25, 60))
        self.assertEqual((self.c.screen.mode, len(self.c.recent.items)), ("home", 50))

    def test_the_next_browse_starts_a_new_visit(self):
        self.c.button(1)
        (load,) = self.recents()
        self.c.set_hardware(True)
        self.c.device_ready(self.c.control_id)
        self.c.button(1)
        (again,) = self.recents()
        self.assertEqual((again["offset"], again["visit"]), (0, None))
        self.c.complete(load["request"], recent_page(0, 30))
        self.assertEqual(self.c.recent.items, [], "the older visit never commits")

    def test_a_failed_state_poll_never_disturbs_a_page_load(self):
        self.c.button(1)
        (load,) = self.recents()
        self.c.complete(self.c.request("state"), error="Sonos could not be reached")
        self.c.complete(load["request"], recent_page(0, 30))
        self.assertEqual((self.c.screen.mode, self.c.recent.state), ("recent", "ready"))

    def test_the_runtime_discard_reports_nothing(self):
        self.c.button(1)
        (load,) = self.recents()
        self.c.complete(load["request"], error=fail("Obsolete library request discarded", outcome="discarded"))
        self.assertEqual(self.c.feedback, None)


# ------------------------------------------------- the live client on the lookahead lane

BASE = AppleMusicClient.RECENT
CREDENTIALS = {"developer_token": "dev", "music_user_token": "user"}


def recent_response(first, next_cursor):
    return {"data": [{"id": f"album-{i}", "type": "library-albums",
                      "attributes": {"name": f"Album {i}", "artistName": "Artist",
                                     "artwork": {"url": f"https://is1-ssl.mzstatic.com/image/thumb/a{i}/{{w}}x{{h}}bb.jpg"}}}
                     for i in range(first, first + 10)], "next": next_cursor}


RESPONSES = {BASE: recent_response(0, BASE + "?offset=10"),
             BASE + "?offset=10": recent_response(10, BASE + "?offset=20"),
             BASE + "?offset=20": recent_response(20, None)}


class JsonResponse:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def json(self):
        return deepcopy(self._body)


class GateSession:
    """An in-memory requests.Session. Records each GET (path, thread), can hold the next GET
    of a path until released, and records the most GETs that were ever out at once. The
    v7 pager's `offset` param picks the page; the v6 cursor pages keep their paths."""

    def __init__(self):
        self.calls, self.held = [], {}
        self.lock = threading.Lock()
        self.active = self.max_active = 0

    def hold(self, path):
        started, release = threading.Event(), threading.Event()
        self.held[path] = (started, release)
        return started, release

    def release_all(self):
        for _started, release in list(self.held.values()):
            release.set()

    def get(self, url, params=None, headers=None, timeout=None, allow_redirects=None):
        path = url[len(AppleMusicClient.API):]
        offset = (params or {}).get("offset")
        if offset:
            path = f"{path}?offset={offset}"
        with self.lock:
            self.calls.append((path, threading.current_thread().name))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            held = self.held.pop(path, None)
        try:
            if held is not None:
                held[0].set()
                held[1].wait(10)
            return JsonResponse(RESPONSES.get(path) or RESPONSES[urlsplit(path).path + "?offset=20"])
        finally:
            with self.lock:
                self.active -= 1

    def paths(self):
        return [path for path, _ in self.calls]


class LookaheadClientTests(unittest.TestCase):
    """AppleMusicClient.recent_lookahead and the lookahead lane's own session."""

    def setUp(self):
        self.foreground, self.background = GateSession(), GateSession()
        self.client = AppleMusicClient(CREDENTIALS, session=self.foreground, background_session=self.background)
        self.addCleanup(self.foreground.release_all)
        self.addCleanup(self.background.release_all)

    def visit(self):
        c = self.client
        return c._recent_pages, c._recent_next, sorted(c._recent_cache), len(c._recent_seen)

    def in_thread(self, function, *args, **kwargs):
        outcome = {}

        def run():
            try:
                outcome["result"] = function(*args, **kwargs)
            except Exception as exc:
                outcome["error"] = exc
        worker = threading.Thread(target=run)
        worker.start()
        self.addCleanup(worker.join, 5)
        return worker, outcome

    def test_it_commits_exactly_like_recent_on_its_own_session(self):
        first = self.client.recent(None)
        second = self.client.recent_lookahead(first["next"])
        reference = AppleMusicClient(CREDENTIALS, session=GateSession())
        reference.recent(None)
        self.assertEqual(second, reference.recent(first["next"]))
        self.assertEqual(self.visit(), (2, BASE + "?offset=20", [BASE, BASE + "?offset=10"], 20))
        self.assertEqual((self.foreground.paths(), self.background.paths()), ([BASE], [BASE + "?offset=10"]))
        self.assertEqual(self.client.recent(first["next"]), second, "the foreground finds it cached")
        self.assertEqual(len(self.foreground.calls), 1)

    def test_a_cached_or_unwanted_page_requests_nothing(self):
        first = self.client.recent(None)
        self.client.recent(first["next"])
        self.assertEqual(self.client.recent_lookahead(first["next"])["items"][0]["id"], "album-10")
        with self.assertRaises(AppleMusicError):
            self.client.recent_lookahead(BASE + "?offset=20", wanted=lambda: False)
        self.assertEqual(self.background.calls, [])
        with self.assertRaises(AppleMusicError):
            self.client.recent_lookahead(BASE + "?offset=30")   # not the visit's next page
        self.assertEqual(self.background.calls, [])

    def test_a_new_visit_is_never_delayed_by_it_and_obsoletes_it(self):
        first = self.client.recent(None)
        started, release = self.background.hold(first["next"])
        worker, outcome = self.in_thread(self.client.recent_lookahead, first["next"])
        self.assertTrue(started.wait(3), "the lookahead request is out")
        began = time.monotonic()
        fresh = self.in_thread(self.client.recent, None)
        fresh[0].join(3)
        self.assertFalse(fresh[0].is_alive(), "page 1 of a new visit never waits for a lookahead request")
        self.assertLess(time.monotonic() - began, 2.0)
        self.assertEqual(fresh[1]["result"]["items"][0]["id"], "album-0")
        release.set()
        worker.join(3)
        self.assertIsInstance(outcome.get("error"), AppleMusicError, "its response is obsolete")
        self.assertEqual(self.visit(), (1, BASE + "?offset=10", [BASE], 10), "and commits nothing")
        self.assertEqual(self.client.recent_lookahead(first["next"])["items"][0]["id"], "album-10")
        self.assertEqual(self.visit()[0], 2)

    def test_a_page_the_foreground_committed_meanwhile_is_returned_once(self):
        first = self.client.recent(None)
        started, release = self.background.hold(first["next"])
        worker, outcome = self.in_thread(self.client.recent_lookahead, first["next"])
        self.assertTrue(started.wait(3))
        foreground = self.client.recent(first["next"])
        release.set()
        worker.join(3)
        self.assertEqual(outcome["result"], foreground)
        self.assertEqual(self.visit(), (2, BASE + "?offset=20", [BASE, BASE + "?offset=10"], 20), "one commit")

    def test_the_lookahead_lane_gets_its_own_session_by_default(self):
        made = []

        class Session(GateSession):
            def __init__(self):
                super().__init__()
                made.append(self)
        with patch("requests.Session", Session):
            client = AppleMusicClient(CREDENTIALS)
            self.assertEqual(len(made), 1)
            client.recent(None)
            client.recent_preview()
            client.recent_lookahead(BASE + "?offset=10")
        self.assertEqual(len(made), 2, "created on first background use")
        self.assertEqual(made[0].paths(), [BASE])
        self.assertEqual(made[1].paths(), [BASE, BASE + "?offset=10"])

    def test_an_injected_session_alone_is_shared_one_thread_at_a_time(self):
        session = GateSession()
        client = AppleMusicClient(CREDENTIALS, session=session)
        self.addCleanup(session.release_all)
        started, release = session.hold(BASE)
        preview, _ = self.in_thread(client.recent_preview)       # the warm-up, background
        self.assertTrue(started.wait(3))
        browse, outcome = self.in_thread(client.recent, None)    # Browse, foreground
        browse.join(0.3)
        self.assertTrue(browse.is_alive(), "waits for the session")
        self.assertEqual(len(session.calls), 1)
        release.set()
        for worker in (preview, browse):
            worker.join(3)
        self.assertEqual((session.max_active, len(session.calls)), (1, 2))
        self.assertEqual(outcome["result"]["items"][0]["id"], "album-0")


class _Artwork:
    """Just enough of ArtworkService for the warm-up to be permitted (no I/O)."""
    version = 0

    def cached(self, *args, **kwargs): return None
    def cached_cover(self, *args, **kwargs): return None
    def request(self, *args, **kwargs): pass
    def prefetch(self, *args, **kwargs): pass
    def clear(self): pass
    def poll(self): return []
    def close(self): pass


class LiveClientLaneTests(unittest.TestCase):
    """Real lanes and the real AppleMusicClient over in-memory sessions (no network)."""

    def setUp(self):
        self.c = Controller()
        sonos = SimulatedSonos()
        self.c.complete(self.c.request("state"), sonos.read_state())
        self.c.drain()
        self.c.last_poll = time.perf_counter() + 3600  # no Sonos polls meanwhile
        self.foreground, self.background = GateSession(), GateSession()
        client = AppleMusicClient(CREDENTIALS, session=self.foreground, background_session=self.background)
        self.runtime = Runtime(self.c, sonos, client, SimulatedWindows(), FakeDevice(), artwork=_Artwork())
        self.addCleanup(self.runtime.close)
        self.addCleanup(self.foreground.release_all)
        self.addCleanup(self.background.release_all)
        self.runtime.device_connected = self.runtime.device_supported = True
        self.runtime._warmup_due = float("inf")

    def until(self, predicate, seconds=5.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.runtime.poll()
            if predicate():
                return True
            time.sleep(0.005)
        self.runtime.poll()
        return predicate()

    def page_1_loaded(self):
        return self.c.screen.mode == "recent" and self.c.recent.state == "ready"

    def assert_lanes(self):
        self.assertEqual((self.foreground.max_active, self.background.max_active), (1, 1),
                         "a session is never used by two threads at once")
        self.assertTrue(all(name.startswith("nanod-library") for _, name in self.foreground.calls), self.foreground.calls)
        self.assertTrue(all(name.startswith("nanod-lookahead") for _, name in self.background.calls), self.background.calls)

    def test_a_stale_prefetch_still_out_never_delays_the_next_visit(self):
        started, release = self.background.hold(BASE + "?offset=25")
        self.c.button(1)                  # Browse
        self.assertTrue(self.until(self.page_1_loaded))
        self.assertTrue(started.wait(3), "the next-page prefetch is out")
        self.c.button(0)                  # Home
        self.c.button(1)                  # Browse: a new visit while the old prefetch waits for Apple
        began = time.monotonic()
        self.assertTrue(self.until(self.page_1_loaded, 2.0), "page 1 never waits for the stale prefetch")
        self.assertLess(time.monotonic() - began, 2.0)
        self.assertEqual(len(self.c.recent.items), 10)
        release.set()
        self.assertTrue(self.until(lambda: len(self.c.recent.items) == 20), "the new visit's own next page")
        self.assertEqual(self.c.recent.items[10]["id"], "album-20")
        self.assertEqual(self.foreground.paths(), [BASE, BASE])
        self.assert_lanes()

    def test_a_warmup_still_out_never_shares_a_session_with_browse(self):
        started, release = self.background.hold(BASE)
        self.runtime._warmup_due = 0.0   # due now instead of 10 s after startup
        self.runtime.poll()
        self.assertTrue(started.wait(3), "the warm-up page-1 request is out")
        self.c.button(1)                  # Browse meanwhile
        self.assertTrue(self.until(self.page_1_loaded, 2.0), "Browse never waits for the warm-up")
        release.set()
        self.assertTrue(self.until(lambda: self.runtime.warmup_page is not None))
        self.assert_lanes()


if __name__ == "__main__":
    unittest.main()
