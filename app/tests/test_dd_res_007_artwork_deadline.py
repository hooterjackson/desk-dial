"""DD-RES-007: the 8 s artwork download deadline holds inside a 16 KB chunk.

A trickling source used to be checked only once per 16 KB iter_content chunk, so the
deadline slipped by seconds. The body is now read with raw.read1 (whatever one socket
read delivers) and each read's socket timeout is capped at the time left.
"""
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import artwork  # noqa: E402


URL = "https://is1-ssl.mzstatic.com/image/thumb/a/b/600x600bb.jpg"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Sock:
    def __init__(self):
        self.timeout = 3.0
        self.history = []

    def gettimeout(self):
        return self.timeout

    def settimeout(self, value):
        self.timeout = value
        self.history.append(value)


class TrickleRaw:
    """One byte per read, each read taking ``step`` seconds of the fake clock."""

    def __init__(self, clock, step, total=200_000):
        self.clock, self.step, self.left = clock, step, total
        self.connection = mock.Mock(sock=Sock())
        self.reads = 0

    def read1(self, amt, decode_content=True):
        self.reads += 1
        sock = self.connection.sock
        if sock.timeout is not None and self.step > sock.timeout:
            self.clock.now += sock.timeout
            raise TimeoutError("read timed out")
        self.clock.now += self.step
        if self.left <= 0:
            return b""
        self.left -= 1
        return b"\xff"


class Response:
    status_code = 200
    headers = {"Content-Type": "image/jpeg"}

    def __init__(self, raw=None, chunks=None):
        self.raw = raw
        self.chunks = chunks
        self.chunk_sizes = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, chunk_size):
        self.chunk_sizes.append(chunk_size)
        yield from self.chunks or []


class Session:
    def __init__(self, response):
        self.response = response

    def get(self, url, **kwargs):
        return self.response


def fetch(response):
    return artwork._fetch(Session(response), URL, (), lambda: False)


class DeadlineTests(unittest.TestCase):
    def test_fetch_total_deadline_enforced_within_a_chunk(self):
        clock = Clock()
        raw = TrickleRaw(clock, step=0.25)
        with mock.patch.object(artwork.time, "monotonic", clock):
            start = clock.now
            with self.assertRaises(artwork.ArtworkError) as caught:
                fetch(Response(raw))
        self.assertNotIsInstance(caught.exception, artwork.ArtworkCancelled)
        self.assertIn("too long", str(caught.exception))
        self.assertLessEqual(clock.now - start, 8.5)
        # Far fewer than 16 KB arrived: the old per-16 KB check would never have fired.
        self.assertLess(raw.reads, 16_384)

    def test_a_stall_near_the_deadline_is_cut_at_the_deadline(self):
        clock = Clock()

        class StallLate(TrickleRaw):
            def read1(self, amt, decode_content=True):
                # Trickle until 7 s, then stall (a 2.9 s gap, under the 3 s read timeout).
                self.step = 0.5 if self.clock.now - 1000.0 < 7.0 else 2.9
                return super().read1(amt, decode_content)

        raw = StallLate(clock, step=0.5)
        with mock.patch.object(artwork.time, "monotonic", clock):
            with self.assertRaises(artwork.ArtworkError) as caught:
                fetch(Response(raw))
        self.assertIn("too long", str(caught.exception))
        self.assertLessEqual(clock.now - 1000.0, 8.5)
        sock = raw.connection.sock
        self.assertTrue(all(value <= 3.0 for value in sock.history[:-1]))
        self.assertLess(min(sock.history[:-1]), 3.0)  # capped at the time left near the end
        self.assertEqual(sock.timeout, 3.0)           # original timeout restored

    def test_a_fast_body_downloads_whole_and_restores_the_timeout(self):
        clock = Clock()
        raw = TrickleRaw(clock, step=0.0, total=5)
        with mock.patch.object(artwork.time, "monotonic", clock):
            self.assertEqual(fetch(Response(raw)), b"\xff" * 5)
        self.assertEqual(raw.connection.sock.timeout, 3.0)

    def test_without_read1_the_fallback_reads_small_chunks(self):
        response = Response(raw=None, chunks=[b"ab", b"cd"])
        self.assertEqual(fetch(response), b"abcd")
        self.assertEqual(response.chunk_sizes, [2_048])

    def test_cancel_still_wins_over_the_deadline(self):
        clock = Clock()
        raw = TrickleRaw(clock, step=0.1)
        with mock.patch.object(artwork.time, "monotonic", clock):
            with self.assertRaises(artwork.ArtworkCancelled):
                artwork._fetch(Session(Response(raw)), URL, (), lambda: raw.reads > 3)


if __name__ == "__main__":
    unittest.main()
