"""ArtworkService page prefetch (firmware/ARTWORK2.md section 9).

The real service and its worker threads against an in-memory, gated HTTP session:
no network. Covers: 3 workers with one always kept free for the foreground,
foreground priority and debounce, same-page reordering without cancellation, a
new page or leaving Recent dropping unstarted jobs, one download per URL (also
across a superseded foreground request), the 64-entry LRU (clamp 128), and the
artwork2 JPEG carried by every result.
"""
from io import BytesIO
import hashlib
from pathlib import Path
import sys
import threading
import time
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.artwork import ARTWORK_CACHE_LIMIT, ArtworkService
from control_center.presentation import ARTWORK_CACHE_ENTRIES, ARTWORK_PREFETCH_WORKERS, COVER_KEY_CHARS

WAIT = 3.0


def url(name):
    return f"https://is1-ssl.mzstatic.com/image/thumb/{name}/480x480bb.jpg"


def png(seed):
    output = BytesIO()
    Image.new("RGB", (48, 48), ((seed * 37) % 256, (seed * 91) % 256, (seed * 53) % 256)).save(output, format="PNG")
    return output.getvalue()


class GatedResponse:
    def __init__(self, session, url, data, status):
        self.session, self.url, self.data, self.status_code = session, url, data, status
        self.headers = {"Content-Type": "image/png"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        with self.session.lock:
            self.session.active -= 1

    def iter_content(self, chunk_size):
        gate = self.session.gates.get(self.url)
        if gate is not None:
            gate.wait(WAIT)
        yield self.data


class GatedSession:
    """Thread-safe fake requests.Session: a download can be held open by a gate."""

    def __init__(self, names, *, status=None):
        self.images = {url(name): png(i) for i, name in enumerate(names)}
        self.status = status or {}
        self.lock = threading.Lock()
        self.calls, self.active, self.max_active = [], 0, 0
        self.gates, self.started = {}, {}

    def hold(self, *names):
        for name in names:
            self.gates[url(name)] = threading.Event()

    def release(self, *names):
        for name in names or [n.split("/")[-2] for n in self.gates]:
            self.gates[url(name)].set()

    def get(self, target, **kwargs):
        assert kwargs["allow_redirects"] is False and "auth" not in kwargs
        with self.lock:
            self.calls.append(target)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            event = self.started.setdefault(target, threading.Event())
        event.set()
        return GatedResponse(self, target, self.images.get(target, b""), self.status.get(target, 200))

    def wait_started(self, name):
        with self.lock:
            event = self.started.setdefault(url(name), threading.Event())
        return event.wait(WAIT)

    def names(self):
        with self.lock:
            return [call.split("/")[-2] for call in self.calls]


def until(predicate, timeout=WAIT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


class PrefetchCase(unittest.TestCase):
    NAMES = [f"p{i}" for i in range(10)] + ["fg", "np", "q0", "q1", "r0", "r1", "r2"]

    def service(self, workers=ARTWORK_PREFETCH_WORKERS, debounce=0.0, **kwargs):
        self.session = GatedSession(self.NAMES, **kwargs)
        service = ArtworkService(session=self.session, debounce=debounce, workers=workers)
        self.addCleanup(service.close)
        self.addCleanup(lambda: [gate.set() for gate in self.session.gates.values()])
        return service

    def cached_all(self, service, names):
        return until(lambda: all(service.cached_cover(url(n)) for n in names))

    def result(self, service):
        found = []
        until(lambda: found.extend(service.poll()) or found)
        self.assertTrue(found, "no foreground result")
        return found[0]


class WorkerPoolTests(PrefetchCase):
    def test_three_workers_and_the_lru_bounds(self):
        service = self.service()
        self.assertEqual(ARTWORK_PREFETCH_WORKERS, 3)
        self.assertEqual([t.name for t in service._threads], ["NanoD-artwork-0", "NanoD-artwork-1", "NanoD-artwork-2"])
        self.assertEqual((service.cache_size, ARTWORK_CACHE_ENTRIES), (64, 64))
        self.assertEqual(ARTWORK_CACHE_LIMIT, 128)
        for kwargs, attribute, expected in (({"cache_size": 500}, "cache_size", 128),
                                            ({"cache_size": 100}, "cache_size", 100),
                                            ({}, "debounce", 0.12)):    # the foreground debounce is kept
            other = ArtworkService(session=self.session, workers=1, **kwargs)
            self.addCleanup(other.close)
            self.assertEqual(getattr(other, attribute), expected)

    def test_a_page_is_loaded_in_priority_order_leaving_a_worker_free(self):
        service = self.service()
        names = [f"p{i}" for i in range(10)]
        self.session.hold(*names)
        service.prefetch([url(n) for n in names], page=("view", 0))
        self.assertTrue(until(lambda: self.session.active == 2))
        time.sleep(0.05)
        self.assertEqual(sorted(self.session.names()), ["p0", "p1"], "the two nearest first, one worker kept free")
        self.session.release(*names)
        self.assertTrue(self.cached_all(service, names))
        self.assertEqual(self.session.max_active, ARTWORK_PREFETCH_WORKERS - 1)
        self.assertEqual(sorted(self.session.names()), sorted(names), "each cover downloaded once")
        self.assertEqual(service.version, 10)
        self.assertEqual(service.poll(), [], "prefetch never produces a foreground result")
        key, jpeg = service.cached_cover(url("p4"))
        self.assertEqual(key, hashlib.sha256(jpeg).hexdigest()[:COVER_KEY_CHARS])
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))

    def test_invalid_duplicate_and_cached_urls_are_skipped(self):
        service = self.service()
        service.prefetch([url("p0")], page="a")
        self.assertTrue(self.cached_all(service, ["p0"]))
        service.prefetch([url("p0"), "https://evil.test/x.jpg", "", None, url("p1"), url("p1"),
                          "http://192.168.1.9:1400/getaa?u=1"], page="b")
        self.assertTrue(self.cached_all(service, ["p1"]))
        time.sleep(0.05)
        self.assertEqual(self.session.names(), ["p0", "p1"])

    def test_a_failed_prefetch_is_not_cached_and_a_request_tries_again(self):
        service = self.service(status={url("p0"): 404})
        service.prefetch([url("p0")], page="a")
        self.assertTrue(until(lambda: self.session.names() == ["p0"]))
        time.sleep(0.05)
        self.assertIsNone(service.cached_cover(url("p0")))
        self.assertEqual(service.version, 0)
        service.request(url("p0"), "t")
        self.assertTrue(self.result(service).error)
        self.assertEqual(self.session.names(), ["p0", "p0"])

    def test_close_stops_every_worker(self):
        service = self.service()
        service.close()
        for thread in service._threads:
            thread.join(1)
            self.assertFalse(thread.is_alive())


class ForegroundPriorityTests(PrefetchCase):
    def test_the_foreground_request_runs_before_queued_prefetch_jobs(self):
        service = self.service(workers=1)
        self.session.hold("p0")
        service.prefetch([url(f"p{i}") for i in range(4)], page="page")
        self.assertTrue(self.session.wait_started("p0"))
        service.request(url("fg"), "fg")
        self.session.release("p0")
        result = self.result(service)
        self.assertEqual((result.token, result.error), ("fg", ""))
        self.assertTrue(self.cached_all(service, ["p1", "p2", "p3"]))
        self.assertEqual(self.session.names(), ["p0", "fg", "p1", "p2", "p3"])

    def test_a_debouncing_foreground_keeps_a_worker_free(self):
        service = self.service(debounce=0.3)
        names = [f"p{i}" for i in range(6)]
        self.session.hold(*names)
        service.request(url("fg"), "fg")
        service.prefetch([url(n) for n in names], page="page")
        self.assertTrue(until(lambda: self.session.active == 2))
        time.sleep(0.1)
        self.assertEqual(sorted(self.session.names()), ["p0", "p1"], "two prefetches while the foreground debounces")
        result = self.result(service)
        self.assertEqual((result.token, result.error), ("fg", ""))
        self.assertEqual(self.session.names()[2], "fg", "the free worker takes the foreground when it is due")
        self.session.release(*names)
        self.assertTrue(self.cached_all(service, names))

    def test_a_foreground_miss_never_waits_behind_page_downloads(self):
        # A page is presented with the selected cover cached (no request pending),
        # its downloads stall; the user turns to an uncached item.
        service = self.service(debounce=0.12)
        names = [f"p{i}" for i in range(10)]
        self.session.hold(*names)
        service.prefetch([url(n) for n in names], page=("view", 0))
        self.assertTrue(until(lambda: self.session.active == 2))
        started = time.monotonic()
        service.request(url("fg"), "fg")
        result = self.result(service)       # the gates are still closed
        self.assertEqual((result.token, result.error), ("fg", ""))
        self.assertLess(time.monotonic() - started, 1.5, "never behind a stalled prefetch download")
        self.assertEqual(sorted(self.session.names()), ["fg", "p0", "p1"])
        self.assertEqual(self.session.max_active, 3)
        self.session.release(*names)
        self.assertTrue(self.cached_all(service, names))

    def test_a_superseded_waiter_gives_its_worker_back(self):
        # A Recent page opens with an uncached selection: in one poll the runtime requests p0
        # and prefetches the page. Two workers download p0 and p1 (both stall); after the
        # debounce the third waits for the p0 download. The user turns to p5 before either
        # finishes: the p0 waiter gives its worker back, so p5 starts at once.
        service = self.service(debounce=0.12)
        names = [f"p{i}" for i in range(10)]
        self.session.hold(*names)
        service.request(url("p0"), "p0")
        service.prefetch([url(n) for n in names], page=("view", 0))
        self.assertTrue(until(lambda: self.session.active == 2))
        self.assertTrue(until(lambda: service._busy == 3), "the p0 foreground waits on the p0 download")
        started = time.monotonic()
        service.request(url("p5"), "p5")
        self.assertTrue(self.session.wait_started("p5"))
        # Well before the held gates give up (WAIT): p0 and p1 are still stalled.
        self.assertLess(time.monotonic() - started, WAIT / 2, "p5 starts while p0 and p1 still stall")
        self.assertEqual(sorted(self.session.names()), ["p0", "p1", "p5"], "each URL downloaded once")
        self.session.release("p5")
        result = self.result(service)       # p0 and p1 are still held
        self.assertEqual((result.token, result.error), ("p5", ""))
        self.session.release(*names)
        self.assertTrue(self.cached_all(service, names))
        self.assertEqual(service.poll(), [], "the superseded p0 request never answers")

    def test_a_url_being_prefetched_is_downloaded_once(self):
        service = self.service()
        self.session.hold("p0")
        service.prefetch([url("p0")], page="page")
        self.assertTrue(self.session.wait_started("p0"))
        service.request(url("p0"), "fg")
        time.sleep(0.05)
        self.assertEqual(service.poll(), [], "the foreground waits for the running download")
        self.session.release("p0")
        result = self.result(service)
        self.assertEqual((result.token, result.error), ("fg", ""))
        self.assertEqual(self.session.names(), ["p0"])
        self.assertEqual((result.jpeg_key, result.jpeg), service.cached_cover(url("p0")))

    def test_a_superseded_download_of_the_page_still_fills_the_cache(self):
        service = self.service()
        self.session.hold("p0")
        service.request(url("p0"), "old")
        self.assertTrue(self.session.wait_started("p0"))
        service.prefetch([url("p0"), url("p1")], page="page")
        service.request(url("p1"), "new")   # supersedes the running p0 download
        self.session.release("p0")
        result = self.result(service)
        self.assertEqual(result.token, "new")
        self.assertTrue(self.cached_all(service, ["p0", "p1"]), "p0 was still wanted by the page")
        self.assertEqual(sorted(self.session.names()), ["p0", "p1"])

    def test_a_request_back_to_a_superseded_download_waits_for_it(self):
        # A -> B -> A before A's download ends: the new request waits for the
        # running download (never cancelled, never started twice).
        service = self.service()
        self.session.hold("p0")
        service.request(url("p0"), "a1")
        self.assertTrue(self.session.wait_started("p0"))
        service.request(url("p1"), "b")
        self.assertTrue(self.session.wait_started("p1"))
        service.request(url("p0"), "a2")
        time.sleep(0.05)
        self.assertEqual(service.poll(), [], "a2 waits for the running download; b is superseded")
        self.session.release("p0")
        result = self.result(service)
        self.assertEqual((result.token, result.error), ("a2", ""))
        self.assertEqual((result.jpeg_key, result.jpeg), service.cached_cover(url("p0")))
        self.assertEqual(self.session.names().count("p0"), 1)
        time.sleep(0.05)
        self.assertEqual(service.poll(), [], "one result: the newest request's")

    def test_a_superseded_download_nobody_wants_is_cancelled(self):
        service = self.service()
        self.session.hold("p0")
        service.request(url("p0"), "old")
        self.assertTrue(self.session.wait_started("p0"))
        service.request(url("p1"), "new")
        result = self.result(service)
        self.assertEqual((result.token, result.error), ("new", ""))
        self.session.release("p0")
        time.sleep(0.1)
        self.assertIsNone(service.cached_cover(url("p0")), "cancelled, never cached")
        self.assertEqual(service.poll(), [])
        service.request(url("p0"), "again")          # asked for later: a fresh download
        self.assertEqual(self.result(service).token, "again")
        self.assertEqual(self.session.names().count("p0"), 2)

    def test_results_carry_the_artwork2_cover(self):
        service = self.service()
        service.request(url("fg"), "t")
        result = self.result(service)
        self.assertEqual(result.jpeg_key, hashlib.sha256(result.jpeg).hexdigest()[:COVER_KEY_CHARS])
        self.assertEqual(len(result.rgb565), 120 * 120 * 2, "the v1 payload stays")
        hit = service.cached(url("fg"), "again")
        self.assertEqual((hit.jpeg, hit.jpeg_key, hit.key), (result.jpeg, result.jpeg_key, result.key))
        self.assertIsNone(service.cached_cover("https://evil.test/a.jpg"))
        self.assertIsNone(service.cached_cover(url("p9")))


class PageTests(PrefetchCase):
    def test_a_selection_change_reorders_but_never_cancels(self):
        service = self.service(workers=1)
        names = [f"p{i}" for i in range(5)]
        self.session.hold("p0")
        service.prefetch([url(n) for n in names], page=("view", 0))
        self.assertTrue(self.session.wait_started("p0"))
        # The selection moved to item 3: same page, nearest first; a partial list drops nothing.
        service.prefetch([url(n) for n in ("p3", "p4", "p2")], page=("view", 0))
        self.session.release("p0")
        self.assertTrue(self.cached_all(service, names))
        self.assertEqual(self.session.names(), ["p0", "p3", "p4", "p2", "p1"])

    def test_a_new_page_drops_the_unstarted_jobs(self):
        service = self.service(workers=1)
        self.session.hold("p0")
        service.prefetch([url(f"p{i}") for i in range(5)], page=("view", 0))
        self.assertTrue(self.session.wait_started("p0"))
        service.prefetch([url("q0"), url("q1")], page=("view", 1))
        self.session.release("p0")
        self.assertTrue(self.cached_all(service, ["p0", "q0", "q1"]), "a started download finishes")
        time.sleep(0.05)
        self.assertEqual(self.session.names(), ["p0", "q0", "q1"])

    def test_leaving_recent_drops_the_unstarted_jobs(self):
        service = self.service(workers=1)
        self.session.hold("r0")
        service.prefetch([url("r0"), url("r1"), url("r2")], page=("view", 2))
        self.assertTrue(self.session.wait_started("r0"))
        service.prefetch([], page=None)
        self.session.release("r0")
        self.assertTrue(self.cached_all(service, ["r0"]))
        time.sleep(0.05)
        self.assertEqual(self.session.names(), ["r0"])

    def test_the_lru_evicts_the_oldest_cover(self):
        self.session = GatedSession(self.NAMES)
        service = ArtworkService(session=self.session, debounce=0, cache_size=3, workers=1)  # completion order fixed
        self.addCleanup(service.close)
        service.prefetch([url(f"p{i}") for i in range(3)], page="a")
        self.assertTrue(self.cached_all(service, ["p0", "p1", "p2"]))
        self.assertTrue(service.cached_cover(url("p0")))  # refreshes p0
        service.prefetch([url("p3")], page="b")
        self.assertTrue(self.cached_all(service, ["p3"]))
        self.assertIsNone(service.cached_cover(url("p1")))
        self.assertTrue(service.cached_cover(url("p0")) and service.cached_cover(url("p2")))


if __name__ == "__main__":
    unittest.main()
