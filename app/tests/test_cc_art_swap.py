"""Contract section 6 "Art swap": cached covers swap on the same detent.

The real Runtime and the real ArtworkService (its worker thread, memory cache and
debounce) against an in-memory HTTP session: no network, no device, no window.
A Recent detent onto a cover loaded before must carry that cover's artKey in the
very poll that handles the detent (never an empty key in between), only a miss
waits for the debounce, and a result for an item the knob has left never shows.
"""
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from control_center.artwork import ArtworkService
from control_center.controller import Controller
from control_center.runtime import Runtime
from control_center.simulation import SimulatedAppleMusic, SimulatedSonos, SimulatedWindows
from test_cc_artwork import Response, Session, png
from test_cc_controller import Clock, FakeDevice, ManualExecutor

COLORS = [(255, 0, 0), (0, 160, 255), (40, 200, 60), (250, 200, 0), (200, 0, 200),
          (0, 0, 255), (255, 128, 0), (0, 255, 255), (128, 0, 64), (90, 90, 255)]


def cover_url(item_id):
    return f"https://is1-ssl.mzstatic.com/image/thumb/cover{item_id}/480x480bb.jpg"


class CoverApple(SimulatedAppleMusic):
    """Library items shaped like the real adapter's: each has its own artwork_url (one flat
    Recently Added list of `count` items, ids "0".."count-1"; item 9 is unavailable)."""
    count = 10

    def _library(self):
        return [{"id": str(i), "title": f"Album {i}", "artist": "Sample library", "kind": "album",
                 "available": i != 9, "reason": "" if i != 9 else "No Sonos-compatible catalog match",
                 "artwork_url": cover_url(i), "accent_url": "", "art_template": "", "art_max": 0, "art_bg": 0,
                 "art_ink": 0, "year": None, "track_count": 10, "resource_type": "library-albums",
                 "_resource": {"id": str(i), "type": "library-albums"}}
                for i in range(self.count)]


class ArtSwapCase(unittest.TestCase):
    def setUp(self):
        executor = patch("control_center.runtime.ThreadPoolExecutor", ManualExecutor)
        executor.start()
        self.addCleanup(executor.stop)
        self.clock = Clock()
        self.c = Controller(clock=self.clock)
        self.sonos = SimulatedSonos()
        self.c.complete(self.c.request("state"), self.sonos.read_state())
        self.c.drain()
        self.c.last_poll = self.clock()  # the fake clock never advances: no background polls
        self.session = Session({cover_url(i): Response(png(color)) for i, color in enumerate(COLORS)})
        self.service = ArtworkService(session=self.session, debounce=0)
        self.device = FakeDevice()
        self.runtime = Runtime(self.c, self.sonos, CoverApple(), SimulatedWindows(), self.device,
                               artwork=self.service)
        self.addCleanup(self.runtime.close)  # closes the artwork service too
        self.runtime.device_connected = self.runtime.device_supported = True
        self.c.set_hardware(True)
        self.settle()

    def settle(self):
        """Dispatch the latest entry and acknowledge it (the knob is then ready)."""
        self.runtime.dispatch()
        entries = [command[1] for command in self.device.commands if command[0] == "enter"]
        self.assertTrue(entries, "no device entry was dispatched")
        self.assertEqual(entries[-1]["id"], self.c.control_id)
        self.device.commands.clear()
        self.device.events.put({"kind": "ready", "id": entries[-1]["id"]})
        self.runtime.poll()
        self.assertTrue(self.c.ready)

    def load_recent(self):
        self.c.button(1)  # Browse
        self.settle()
        self.runtime.library.run_next()  # the page request
        self.runtime.poll()
        self.settle()
        self.assertEqual((self.c.screen.mode, self.c.screen.loading), ("recent", False))

    def wait_art(self):
        """Poll until the presented item's cover is ready; return its key."""
        until = time.monotonic() + 3
        while time.monotonic() < until:
            self.runtime.poll()
            result = self.runtime.artwork_result
            if result is not None and result.token == self.runtime._art_identity():
                self.assertEqual(self.runtime.frame()["artKey"], result.key)
                return result.key
            time.sleep(0.005)
        self.fail("the cover never arrived")

    def turn_to(self, index):
        """One detent, handled by one poll: (frames sent, artwork keys submitted) in it."""
        self.device.commands.clear()
        self.device.events.put({"kind": "position", "id": self.c.control_id, "position": index})
        self.runtime.poll()
        self.assertEqual(self.c.screen.index, index)
        frames = [command[1] for command in self.device.commands if command[0] == "frame"]
        art = [command[1]["key"] for command in self.device.commands if command[0] == "artwork"]
        self.assertTrue(frames, "a detent always sends its frame")
        return frames, art


class CachedCoverSwapTests(ArtSwapCase):
    def test_turning_between_loaded_covers_never_blanks_the_art(self):
        self.load_recent()
        keys = {0: self.wait_art()}
        self.turn_to(1)
        keys[1] = self.wait_art()
        self.assertNotEqual(keys[0], keys[1])
        downloads = len(self.session.calls)
        # From here a miss would wait five seconds: every swap below is a cache hit.
        self.service.debounce = 5.0
        for index in (0, 1, 0, 1, 0, 1):
            with self.subTest(index=index):
                frames, art = self.turn_to(index)
                self.assertEqual([frame["artKey"] for frame in frames], [keys[index]],
                                 "the new cover's key in the same poll, never an empty key")
                self.assertEqual(art, [keys[index]], "its pixels follow the frame in the same poll")
                result = self.runtime.artwork_result
                self.assertEqual((result.key, result.token), (keys[index], self.runtime._art_identity()))
                self.assertEqual(result.preview.size, (240, 240), "the desktop mirror draws the same cover")
        self.assertEqual(len(self.session.calls), downloads, "cached covers never download again")

    def test_several_detents_between_polls_show_only_the_last_cover(self):
        self.load_recent()
        keys = {0: self.wait_art()}
        self.turn_to(1)
        keys[1] = self.wait_art()
        self.device.commands.clear()
        for index in (0, 1, 0):
            self.device.events.put({"kind": "position", "id": self.c.control_id, "position": index})
        self.runtime.poll()
        frames = [command[1] for command in self.device.commands if command[0] == "frame"]
        self.assertEqual([frame["artKey"] for frame in frames], [keys[0]])

    def test_the_first_frame_after_an_entry_carries_its_cached_cover(self):
        """K3 section 6.3: an entry keeps the previous frame's artKey; the cached cover goes out in
        the first frame after `ready`, never a blank frame in between."""
        self.load_recent()
        key = self.wait_art()
        self.c.button(0)  # Back: Home
        self.settle()
        self.assertEqual(self.runtime.frame()["artKey"], "", "the simulated track has no cover")
        self.c.button(1)  # Browse again: the first item's cover is still cached
        self.settle()
        self.runtime.library.run_next()
        self.runtime.poll()
        entries = [command[1] for command in self.device.commands if command[0] == "enter"]
        self.assertEqual(entries[-1]["frame"]["artKey"], "", "the entry keeps the previous frame's cover")
        self.device.commands.clear()
        self.device.events.put({"kind": "ready", "id": entries[-1]["id"]})
        self.runtime.poll()
        frames = [command[1] for command in self.device.commands if command[0] == "frame"]
        self.assertEqual(frames[0]["artKey"], key, "no blank frame before the cover")


class MissAndStaleTests(ArtSwapCase):
    def test_a_miss_still_debounces_and_shows_no_previous_cover(self):
        self.load_recent()
        previous = self.wait_art()
        self.service.debounce = 1.0
        frames, art = self.turn_to(2)
        self.assertEqual(([frame["artKey"] for frame in frames], art), ([""], []),
                         "item 2's cover is not loaded: no art, never item 0's")
        time.sleep(0.05)
        self.runtime.poll()
        self.assertNotIn(cover_url(2), [url for url, _ in self.session.calls], "still debouncing")
        self.assertEqual(self.runtime.frame()["artKey"], "")
        key = self.wait_art()
        self.assertNotEqual(key, previous)
        self.assertEqual(self.session.calls[-1][0], cover_url(2))

    def test_a_result_for_a_left_item_never_leaks(self):
        self.load_recent()
        key = self.wait_art()
        started, proceed = threading.Event(), threading.Event()

        def slow():
            started.set()
            proceed.wait(2)
            return Response(png(COLORS[3]))
        self.session.responses[cover_url(3)] = slow
        self.addCleanup(proceed.set)
        frames, _ = self.turn_to(3)
        self.assertEqual([frame["artKey"] for frame in frames], [""])
        self.assertTrue(started.wait(2), "item 3's download is in flight")
        frames, art = self.turn_to(0)
        self.assertEqual(([frame["artKey"] for frame in frames], art), ([key], [key]))
        proceed.set()
        until = time.monotonic() + 0.3
        while time.monotonic() < until:
            self.device.commands.clear()
            self.runtime.poll()
            sent = [command[1]["artKey"] for command in self.device.commands if command[0] == "frame"]
            self.assertEqual(set(sent) - {key}, set(), "item 3's late cover never replaces item 0's")
            time.sleep(0.01)
        self.assertEqual((self.runtime.artwork_result.key, self.runtime.frame()["artKey"]), (key, key))
        self.assertEqual(self.runtime.artwork_result.token, self.runtime._art_identity())

    def test_a_stored_cover_never_stands_in_for_an_uncached_item(self):
        self.load_recent()
        key = self.wait_art()
        self.c.position(4)  # not yet polled: the stored result still belongs to item 0
        self.assertEqual(self.runtime.artwork_result.key, key)
        self.assertEqual(self.runtime.frame()["artKey"], "")
        self.runtime.artwork_enabled = False
        self.c.position(0)
        self.assertEqual(self.runtime.frame()["artKey"], "", "disabled art shows no cached cover either")


class Artwork2SwapTests(ArtSwapCase):
    """The same swaps with artwork2 negotiated (ARTWORK2.md section 9): frames name the JPEG
    cover, the knob gets wanted lists instead of v1 uploads, and the page is prefetched."""

    def setUp(self):
        super().setUp()
        from control_center.presentation import ARTWORK2_CAPABILITY
        self.wanted, self.order = [], []
        self.device.media_capability = dict(ARTWORK2_CAPABILITY)
        self.device.set_media_wanted = lambda kind, items: (self.wanted.append((kind, list(items))),
                                                              self.order.append(("wanted", kind)))
        submit = self.device.submit
        self.device.submit = lambda *command: (submit(*command), self.order.append(("submit", command[0])))

    def wait_covers(self, count):
        until = time.monotonic() + 3
        while time.monotonic() < until:
            self.runtime.poll()
            if len(self.runtime.media_wanted["cover"]) >= count:
                return
            time.sleep(0.005)
        self.fail("the page was not prefetched")

    def test_cached_swaps_name_the_jpeg_in_the_same_poll(self):
        self.load_recent()
        self.assertTrue(self.runtime.artwork2)
        self.wait_covers(10)
        keys = {}
        for index in (1, 2, 1, 0, 1):
            with self.subTest(index=index):
                self.order.clear()
                frames, art = self.turn_to(index)
                result = self.runtime.artwork_result
                self.assertEqual((result.token, frames[-1]["artKey"]), (self.runtime._art_identity(), result.jpeg_key))
                keys.setdefault(index, result.jpeg_key)
                self.assertEqual(frames[-1]["artKey"], keys[index])
                self.assertEqual(art, [], "no v1 upload with artwork2")
                cover = [items for kind, items in self.wanted if kind == "cover"][-1]
                self.assertEqual(cover[0][0], result.jpeg_key, "index 0 is what the knob shows")
                self.assertEqual(self.order[:2], [("submit", "frame"), ("wanted", "cover")])
        self.assertEqual(len({url for url, _ in self.session.calls}), len(self.session.calls), "one download per cover")
        self.assertEqual(len(self.session.calls), 10, "the whole page, prefetched once")


if __name__ == "__main__":
    unittest.main()
