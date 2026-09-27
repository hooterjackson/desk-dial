"""Runtime side of artwork2 (firmware/ARTWORK2.md section 9).

The real Runtime and Controller with fakes that have the DeviceBridge's artwork2
interface (``media_capability``, ``set_media_wanted(kind, items)``, the
``media-ready`` / ``media-error`` events): frame decoration (artKey = jpeg_key,
iconKey on the windows layout), wanted-list order and change-only hand-over,
the order of writes, page prefetch, the connection lifecycle (nothing before
the knob is ready, a disconnect or a cc5.2 reconnect falls back to v1),
status.json fields and the mirror inputs.
Without artwork2 the v1 path must be exactly as before. No network, no port,
no window.
"""
from collections import OrderedDict
from copy import deepcopy
import inspect
import json
from pathlib import Path
import random
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from control_center.artwork import (ICON_PAYLOAD_INFO, ArtworkResult, ArtworkService, _art_key, attach_icon_payload,
                                   icon_payload, prepare_artwork2)
from control_center.controller import Controller
from control_center.lcd_preview import render_lcd
from control_center.presentation import ARTWORK2_CAPABILITY, MEDIA_KINDS
from control_center.runtime import Runtime, by_distance
from control_center.simulation import SimulatedSonos, SimulatedWindows
import standalone
from test_cc_art_swap import COLORS, CoverApple, cover_url
from test_cc_artwork import Response, Session, png
from test_cc_controller import Clock, FakeDevice, ManualExecutor

NOW_PLAYING = "https://is1-ssl.mzstatic.com/image/thumb/now-playing/480x480bb.jpg"
PAGE2 = [(250, 120, 0), (0, 90, 200), (20, 220, 120), (220, 40, 90), (120, 120, 250),
         (80, 200, 200), (200, 200, 40), (160, 60, 20), (30, 30, 160), (240, 160, 200)]
SOURCES = {**{cover_url(i): png(color) for i, color in enumerate(COLORS)},
           **{cover_url(10 + i): png(color) for i, color in enumerate(PAGE2)},
           NOW_PLAYING: png((255, 255, 255))}
_PREPARED = {}


def prepared(url):
    if url not in _PREPARED:
        _PREPARED[url] = prepare_artwork2(SOURCES[url])
    return _PREPARED[url]


def jpeg_key(i):
    return prepared(cover_url(i) if isinstance(i, int) else i).jpeg_key


def rgba(seed):
    rng = random.Random(seed)
    return Image.frombytes("RGBA", (32, 32), bytes(rng.randrange(256) for _ in range(32 * 32 * 4)))


class FakeArtwork:
    """A synchronous ArtworkService: covers become ready only when a test says so."""

    def __init__(self):
        self.prepared = dict()
        self.ready, self.version = set(), 0
        self.requests, self.prefetches, self.results = [], [], []
        self.pending, self.closed = None, False

    def _prepared(self, url):
        return self.prepared.get(url) or prepared(url)

    def _result(self, url, token):
        p = self._prepared(url)
        return ArtworkResult(token, _art_key(p.raw), p.preview, p.raw, p.dominant, "", p.jpeg, p.jpeg_key)

    def cached(self, url, token=None, *, speaker_host=None):
        return self._result(url, token) if url in self.ready else None

    def cached_cover(self, url, *, speaker_host=None):
        p = self._prepared(url) if url in self.ready else None
        return (p.jpeg_key, p.jpeg) if p is not None and p.jpeg else None

    def request(self, url, token=None, *, speaker_host=None):
        self.requests.append(url)
        self.pending = (url, token)

    def finish(self):
        url, token = self.pending
        self.pending = None
        self.load(url)
        self.results.append(self._result(url, token))

    def load(self, *urls):
        self.ready.update(urls)
        self.version += 1

    def prefetch(self, urls, *, page=None, speaker_host=None):
        self.prefetches.append((list(urls), page))

    def clear(self):
        self.pending = None

    def poll(self):
        results, self.results = self.results, []
        return results

    def close(self):
        self.closed = True


class MediaDevice(FakeDevice):
    """FakeDevice plus the DeviceBridge's artwork2 interface; one log keeps the write order."""

    def __init__(self, capability):
        super().__init__()
        self.media_capability = deepcopy(capability) if capability is not None else None
        self.wanted, self.log = [], []

    def submit(self, *command):
        super().submit(*command)
        self.log.append(("submit", command[0]))

    def set_media_wanted(self, kind, items):
        self.wanted.append((kind, [(key, data) for key, data in items]))
        self.log.append(("wanted", kind))

    def last_wanted(self, kind):
        calls = [items for k, items in self.wanted if k == kind]
        return calls[-1] if calls else None


class IconWindows(SimulatedWindows):
    """Real-adapter-shaped windows (no accent: the IconWorker is asked)."""

    def snapshot(self):
        return {"items": [{"id": f"w{i}", "hwnd": 100 + i, "pid": 200 + i, "title": f"Window {i}",
                           "app": app, "path": "", "available": True}
                          for i, app in enumerate(("chrome", "ApplicationFrameHost", "slack", "Terminal"))],
                "index": 1, "origin": {"hwnd": 100, "pid": 200}}


class FakeIcons:
    def __init__(self):
        self.requests, self.results, self.closed = [], [], False

    def request(self, items):
        self.requests.append([item.get("id") for item in items])

    def poll(self):
        results, self.results = self.results, []
        return results

    def close(self, timeout=None):
        self.closed = True


class MediaCase(unittest.TestCase):
    capability = ARTWORK2_CAPABILITY

    def setUp(self):
        executor = patch("control_center.runtime.ThreadPoolExecutor", ManualExecutor)
        executor.start()
        self.addCleanup(executor.stop)
        self.clock = Clock()
        self.c = Controller(clock=self.clock)
        self.sonos = SimulatedSonos()
        self.c.complete(self.c.request("state"), self.sonos.read_state())
        self.c.drain()
        self.c.last_poll = self.clock()
        self.artwork, self.icons = self.make_artwork(), FakeIcons()
        self.device = self.make_device()
        self.runtime = Runtime(self.c, self.sonos, CoverApple(), IconWindows(), self.device,
                               artwork=self.artwork, icons=self.icons)
        self.addCleanup(self.runtime.close)
        self.connect()

    def make_artwork(self):
        return FakeArtwork()

    def make_device(self):
        return MediaDevice(self.capability)

    def connect(self):
        self.runtime.device_connected = self.runtime.device_supported = True
        self.c.set_hardware(True)
        self.settle()

    def settle(self):
        self.runtime.dispatch()
        entries = [command[1] for command in self.device.commands if command[0] == "enter"]
        self.assertTrue(entries, "no device entry was dispatched")
        self.device.commands.clear()
        self.device.events.put({"kind": "ready", "id": entries[-1]["id"]})
        self.runtime.poll()
        self.assertTrue(self.c.ready)

    def load_recent(self):
        self.c.button(1)  # Browse
        self.settle()
        self.runtime.library.run_next()
        self.runtime.poll()
        self.settle()
        self.assertEqual((self.c.screen.mode, self.c.screen.loading), ("recent", False))

    def open_windows(self):
        while self.c.screen.mode != "home":   # the picker opens from Home only (K3 section 5.7.1)
            self.c.button(0, self.c.control_id)
            self.settle()
        self.c.button(3)                 # Home 4 (Win; no hotkey here)
        self.runtime.dispatch()
        self.settle()
        self.assertEqual(self.c.screen.mode, "windows")

    def turn_to(self, index):
        self.device.commands.clear()
        self.device.log.clear() if hasattr(self.device, "log") else None
        self.device.events.put({"kind": "position", "id": self.c.control_id, "position": index})
        self.runtime.poll()
        self.assertEqual(self.c.screen.index, index)
        return [command[1] for command in self.device.commands if command[0] == "frame"]

    def frames(self):
        return [command[1] for command in self.device.commands if command[0] == "frame"]

    def art_commands(self):
        return [command[1] for command in self.device.commands if command[0] == "artwork"]


class V1CompatibilityTests(MediaCase):
    capability = None

    def test_without_artwork2_frames_uploads_and_prefetch_are_as_before(self):
        self.load_recent()
        self.artwork.finish()
        self.runtime.poll()
        v1 = _art_key(prepared(cover_url(0)).raw)
        self.assertFalse(self.runtime.artwork2)
        self.assertEqual(self.runtime.frame()["artKey"], v1)
        self.assertEqual([a["key"] for a in self.art_commands()], [v1], "the v1 upload follows the frame")
        self.assertEqual(self.art_commands()[0]["data"], prepared(cover_url(0)).raw)
        self.assertEqual(self.device.wanted, [], "no wanted lists without artwork2")
        self.assertEqual(self.artwork.prefetches, [], "no page prefetch without artwork2")
        self.open_windows()
        self.icons.results = [("w0", rgba(0), 0x010203), ("w1", None, None)]
        self.c.position(0)
        self.runtime.poll()
        self.assertNotIn("iconKey", self.runtime.frame())
        self.assertNotIn("iconKey", json.dumps(self.device.commands, default=str))

    def test_a_cache_growth_leaves_the_v1_request_alone(self):
        self.load_recent()
        self.artwork.finish()
        self.turn_to(5)
        self.artwork.load(cover_url(5))
        self.runtime.poll()
        self.assertIsNone(self.runtime.artwork_result, "v1: only the request's own result is stored")
        self.assertEqual(self.artwork.pending[0], cover_url(5))
        self.artwork.finish()
        self.runtime.poll()
        self.assertEqual(self.runtime.frame()["artKey"], _art_key(prepared(cover_url(5)).raw))

    def test_a_device_without_the_attribute_is_v1(self):
        runtime = Runtime(Controller(clock=self.clock), self.sonos, CoverApple(), IconWindows(), FakeDevice(),
                          artwork=FakeArtwork())
        self.addCleanup(runtime.close)
        runtime.device_connected = True
        runtime.poll()
        self.assertFalse(runtime.artwork2)
        self.assertEqual(runtime.media_status()["cover"]["wanted"], 0)


class DecorationTests(MediaCase):
    def test_frames_name_the_jpeg_and_no_v1_art_is_ever_sent(self):
        self.load_recent()
        self.assertTrue(self.runtime.artwork2)
        self.artwork.finish()
        self.runtime.poll()
        self.assertEqual(self.runtime.frame()["artKey"], jpeg_key(0))
        self.assertEqual(self.frames()[-1]["artKey"], jpeg_key(0))
        self.assertEqual(self.art_commands(), [], "art (v1) lines are never sent with artwork2")
        self.assertEqual(self.device.last_wanted("cover")[0], (jpeg_key(0), prepared(cover_url(0)).jpeg))
        for _ in range(3):
            self.runtime.poll()
        self.assertEqual(self.art_commands(), [])

    def test_no_fitting_ladder_quality_leaves_the_art_key_empty(self):
        self.artwork.prepared[cover_url(0)] = prepared(cover_url(0))._replace(jpeg=None, jpeg_key=None)
        self.load_recent()
        self.artwork.finish()
        self.runtime.poll()
        self.assertEqual(self.runtime.frame()["artKey"], "", "never the v1 key under artwork2")
        self.assertEqual(self.device.last_wanted("cover"), [])
        self.assertEqual(self.art_commands(), [])

    def test_a_connect_entry_frame_already_names_the_jpeg(self):
        """A (re)connect lands on Home (C5-2); its first entry already names the jpeg (the knob has
        no previous cover to keep, section 6.3)."""
        c = Controller(clock=self.clock)
        state = self.sonos.read_state()
        state["artwork_url"] = NOW_PLAYING
        c.complete(c.request("state"), state)
        c.drain()
        c.last_poll = self.clock()
        device = MediaDevice(ARTWORK2_CAPABILITY)
        self.artwork.load(NOW_PLAYING)
        runtime = Runtime(c, self.sonos, CoverApple(), IconWindows(), device, artwork=self.artwork)
        self.addCleanup(runtime.close)
        self.assertEqual(runtime.frame()["artKey"], _art_key(prepared(NOW_PLAYING).raw), "not connected: v1")
        device.events.put({"kind": "connected", "capabilities": {"controlCenter": 1, "presentation": 4}})
        runtime.poll()
        entries = [command[1] for command in device.commands if command[0] == "enter"]
        self.assertEqual(entries[-1]["frame"]["artKey"], jpeg_key(NOW_PLAYING))

    def test_icon_key_only_on_the_windows_layout(self):
        # ARTWORK2.md section 6: iconKey is meaningful only on layout "windows"; it never rides
        # on another layout, even in Windows mode and with the icon payloads cached.
        self.open_windows()
        icon = rgba(2)
        self.icons.results = [("w2", icon, 2)]
        self.runtime.poll()
        self.turn_to(2)
        key = icon_payload(icon)[0]
        self.assertEqual(self.frames()[-1]["iconKey"], key)
        base = {name: value for name, value in self.runtime.frame().items() if name != "iconKey"}
        self.assertEqual(self.runtime._decorate({**base, "layout": "windows"}).get("iconKey"), key)
        for layout in ("volume", "notice", "nowPlaying", "idle", "recent", "tracks"):
            with self.subTest(layout=layout):
                self.assertNotIn("iconKey", self.runtime._decorate({**base, "layout": layout}))
        self.c.button(0)   # Back: Home, then Recent
        self.runtime.dispatch()
        self.settle()
        self.assertNotEqual(self.c.screen.mode, "windows")
        self.assertNotIn("iconKey", self.runtime.frame())
        self.load_recent()
        self.artwork.finish()
        self.runtime.poll()
        self.assertNotIn("iconKey", self.runtime.frame())
        others = [frame for frame in self.frames() if frame.get("layout") != "windows"]
        self.assertTrue(others)
        self.assertEqual([frame for frame in others if "iconKey" in frame], [])

    def test_negotiation_follows_the_bridge(self):
        self.load_recent()
        self.artwork.finish()
        self.runtime.poll()
        calls = len(self.device.wanted)
        self.device.media_capability = None      # e.g. a reconnect to a cc5.2 knob
        self.device.commands.clear()
        self.runtime.poll()
        self.assertFalse(self.runtime.artwork2)
        self.assertEqual(self.frames()[-1]["artKey"], _art_key(prepared(cover_url(0)).raw))
        self.assertEqual(len(self.art_commands()), 1)
        self.device.media_capability = deepcopy(ARTWORK2_CAPABILITY)
        self.runtime.poll()
        self.assertTrue(self.runtime.artwork2)
        self.assertEqual(len(self.device.wanted), calls + 2, "both lists are handed over again")


class WantedListTests(MediaCase):
    def keys(self, kind):
        return [key for key, _ in self.device.last_wanted(kind)]

    def test_cover_order_current_then_page_by_distance_then_now_playing(self):
        self.load_recent()
        self.c.state["artwork_url"] = NOW_PLAYING
        self.artwork.load(*[cover_url(i) for i in range(10)], NOW_PLAYING)
        self.turn_to(3)
        expected = [jpeg_key(i) for i in (3, 4, 2, 5, 1, 6, 0, 7, 8, 9)] + [jpeg_key(NOW_PLAYING)]
        self.assertEqual(self.keys("cover"), expected)
        self.assertEqual(self.device.last_wanted("cover")[0][1], prepared(cover_url(3)).jpeg)
        self.assertEqual(self.runtime.media_wanted["cover"], self.device.last_wanted("cover"))
        self.turn_to(9)   # the list's end: the flat list by distance, Now Playing last
        self.assertEqual(self.keys("cover"), [jpeg_key(i) for i in range(9, -1, -1)] + [jpeg_key(NOW_PLAYING)])

    def test_only_prepared_covers_are_listed_and_duplicates_dropped(self):
        self.load_recent()
        self.artwork.load(cover_url(2), cover_url(5))
        self.c.state["artwork_url"] = cover_url(5)   # Now Playing is also on the page
        self.turn_to(1)
        self.assertEqual(self.keys("cover"), [jpeg_key(2), jpeg_key(5)])
        self.artwork.finish()   # item 1's own cover arrives: it becomes index 0
        self.runtime.poll()
        self.assertEqual(self.keys("cover"), [jpeg_key(1), jpeg_key(2), jpeg_key(5)])

    def test_lists_are_handed_over_only_when_they_change(self):
        self.load_recent()
        self.artwork.load(*[cover_url(i) for i in range(4)])
        self.runtime.poll()
        calls = len(self.device.wanted)
        self.assertEqual([k for k, _ in self.device.wanted].count("icon"), 1, "the (empty) icon list once")
        for _ in range(5):
            self.runtime.last_heartbeat = 0     # heartbeat frames change nothing
            self.runtime.poll()
        self.assertEqual(len(self.device.wanted), calls)
        self.artwork.load(cover_url(7))
        self.runtime.poll()
        self.assertEqual(self.device.wanted[calls:], [("cover", self.device.last_wanted("cover"))])
        self.assertIn(jpeg_key(7), self.keys("cover"))

    def test_the_frame_is_queued_before_the_lists_it_changes(self):
        self.load_recent()
        self.artwork.load(*[cover_url(i) for i in range(10)])
        self.runtime.poll()
        self.turn_to(4)
        self.assertEqual(self.device.log, [("submit", "frame"), ("wanted", "cover")])
        self.assertEqual(self.frames()[0]["artKey"], self.keys("cover")[0])

    def test_icons_selected_window_first_then_the_frozen_list_by_distance(self):
        self.open_windows()
        self.assertEqual(self.icons.requests, [["w0", "w1", "w2", "w3"]])
        icons = {"w0": rgba(0), "w2": rgba(2), "w3": rgba(3)}
        self.icons.results = [("w0", icons["w0"], 1), ("w1", None, None), ("w2", icons["w2"], 2),
                              ("w3", icons["w3"], 3)]
        self.runtime.poll()
        key = {item: icon_payload(image)[0] for item, image in icons.items()}
        self.assertEqual(self.c.screen.index, 1)
        self.assertNotIn("iconKey", self.runtime.frame(), "UWP / no icon: the letter tile")
        self.assertEqual(self.keys("icon"), [key["w2"], key["w0"], key["w3"]])   # by_distance(4, 1) = 1,2,0,3
        self.turn_to(2)
        self.assertEqual(self.frames()[-1]["iconKey"], key["w2"])
        self.assertEqual(self.keys("icon"), [key["w2"], key["w3"], key["w0"]])
        self.assertEqual(self.device.log.index(("submit", "frame")), 0)
        self.assertEqual(self.device.last_wanted("icon")[0][1], icon_payload(icons["w2"])[1])
        self.assertEqual(self.keys("cover"), [], "no page covers here (and no Now Playing cover in this test)")
        self.c.button(0)   # Back: the icon list empties (the knob keeps its cache)
        self.runtime.dispatch()
        self.settle()
        self.assertNotEqual(self.c.screen.mode, "windows")
        self.assertEqual(self.device.last_wanted("icon"), [])

    def test_icon_payloads_are_cached_by_window_and_icon_identity(self):
        self.open_windows()
        first = rgba(5)
        self.icons.results = [("w0", first, 1)]
        self.runtime.poll()
        payload = self.runtime.window_icon_payload("w0")
        self.assertIs(self.runtime.window_icon_payload("w0"), payload)
        self.assertEqual(payload, icon_payload(first))
        self.icons.results = [("w0", rgba(6), 1)]      # a new icon for the same window
        self.runtime.poll()
        self.assertEqual(self.runtime.window_icon_payload("w0"), icon_payload(rgba(6)))
        self.icons.results = [("w1", object(), None)]  # not an image: no payload, never an error
        self.runtime.poll()
        self.assertIsNone(self.runtime.window_icon_payload("w1"))
        self.assertIsNone(self.runtime.window_icon_payload("missing"))

    def test_the_icon_workers_payload_is_used_without_encoding_on_the_ui_thread(self):
        self.open_windows()
        image = attach_icon_payload(rgba(4))
        sentinel = ("0123456789abcdef", bytes(range(256)) * 8)
        image.info[ICON_PAYLOAD_INFO] = sentinel     # proves which payload is used
        self.icons.results = [("w1", image.copy(), 1)]
        with patch("control_center.artwork.icon_payload", side_effect=AssertionError("encoded on the UI thread")):
            self.runtime.poll()
            self.assertEqual(self.runtime.frame()["iconKey"], sentinel[0])
            self.assertEqual(self.device.last_wanted("icon"), [sentinel])
            self.assertEqual(self.runtime.lcd_media(self.runtime.frame(), self.c.presented())[1], sentinel[1])

    def test_by_distance_prefers_the_following_item_on_ties(self):
        self.assertEqual(by_distance(5, 2), [2, 3, 1, 4, 0])
        self.assertEqual(by_distance(4, 0), [0, 1, 2, 3])
        self.assertEqual(by_distance(3, 5), [2, 1, 0])
        self.assertEqual(by_distance(0, 0), [])


class LifecycleTests(MediaCase):
    def fresh_runtime(self, capability=ARTWORK2_CAPABILITY):
        c = Controller(clock=self.clock)
        c.complete(c.request("state"), self.sonos.read_state())
        c.drain()
        c.last_poll = self.clock()
        device = MediaDevice(capability)
        runtime = Runtime(c, self.sonos, CoverApple(), IconWindows(), device, artwork=self.artwork)
        self.addCleanup(runtime.close)
        return c, device, runtime

    def test_no_lists_are_handed_over_before_the_knob_is_ready(self):
        c, device, runtime = self.fresh_runtime()
        c.state["artwork_url"] = NOW_PLAYING
        self.artwork.load(NOW_PLAYING)
        device.events.put({"kind": "connected", "capabilities": {"controlCenter": 1, "presentation": 4}})
        for _ in range(3):
            runtime.last_heartbeat = 0
            runtime.poll()
        entries = [command[1] for command in device.commands if command[0] == "enter"]
        self.assertTrue(entries)
        self.assertTrue(runtime.artwork2)
        self.assertFalse(c.ready)
        self.assertEqual(device.wanted, [], "nothing before the knob acknowledged its entry")
        self.assertNotIn("frame", [command[0] for command in device.commands])
        device.log.clear()
        device.events.put({"kind": "ready", "id": entries[-1]["id"]})
        runtime.poll()
        self.assertTrue(c.ready)
        self.assertEqual(device.log[0], ("submit", "frame"), "the frame first, then the lists")
        self.assertEqual(device.last_wanted("cover"), [(jpeg_key(NOW_PLAYING), prepared(NOW_PLAYING).jpeg)])
        self.assertEqual(device.last_wanted("icon"), [])

    def list_token(self):
        return ("recent", self.c.screen.view_id, (self.c.recent.rev, self.c.favourites.rev))

    def test_a_disconnect_turns_artwork2_off_and_drops_the_page_jobs(self):
        self.load_recent()
        self.artwork.finish()
        self.runtime.poll()
        self.assertTrue(self.runtime.artwork2)
        self.assertEqual(self.artwork.prefetches, [([cover_url(i) for i in range(10)], self.list_token())])
        calls = len(self.device.wanted)
        self.device.events.put({"kind": "disconnected", "message": "Knob disconnected"})
        self.runtime.poll()
        self.assertFalse(self.runtime.artwork2)
        self.assertEqual(self.artwork.prefetches[-1], ([], None), "the unstarted page jobs are dropped")
        self.assertEqual(self.runtime.media_wanted, {"cover": [], "icon": []})
        for _ in range(3):
            self.runtime.poll()
        self.assertEqual(len(self.device.wanted), calls, "no lists while disconnected")
        self.assertEqual(len(self.artwork.prefetches), 2)
        # Reconnect to a cc5.2 knob (no artwork2): Home (C5-2), and the v1 path again.
        self.device.media_capability = None
        self.device.commands.clear()
        self.c.state["artwork_url"] = NOW_PLAYING
        self.artwork.load(NOW_PLAYING)
        self.device.events.put({"kind": "connected", "capabilities": {"controlCenter": 1, "presentation": 4}})
        self.runtime.poll()
        entries = [command[1] for command in self.device.commands if command[0] == "enter"]
        self.assertEqual(self.c.screen.mode, "home")
        self.assertEqual(entries[-1]["frame"]["artKey"], _art_key(prepared(NOW_PLAYING).raw))
        self.device.events.put({"kind": "ready", "id": entries[-1]["id"]})
        self.runtime.poll()
        self.assertEqual([a["key"] for a in self.art_commands()], [_art_key(prepared(NOW_PLAYING).raw)])
        self.assertEqual(len(self.device.wanted), calls)
        self.assertEqual(len(self.artwork.prefetches), 2, "no list prefetch without artwork2")

    def test_no_page_is_prefetched_while_it_loads(self):
        self.c.button(1)  # Browse
        self.settle()
        self.assertEqual((self.c.screen.mode, self.c.screen.loading), ("recent", True))
        for _ in range(3):
            self.runtime.poll()
        self.assertEqual(self.artwork.prefetches, [])
        self.runtime.library.run_next()
        self.runtime.poll()
        self.settle()
        self.assertEqual(self.artwork.prefetches, [([cover_url(i) for i in range(10)], self.list_token())])
        self.c.button(0)          # Home, then a new visit: loading again asks for nothing
        self.settle()
        self.c.button(1)
        self.settle()
        self.assertTrue(self.c.screen.loading)
        self.runtime.poll()
        self.assertEqual(self.artwork.prefetches[1:], [([], None)], "a loading list asks for nothing")
        self.runtime.library.run_next()
        self.runtime.poll()
        self.settle()
        self.assertEqual(self.artwork.prefetches[1:], [([], None), ([cover_url(i) for i in range(10)], self.list_token())])


class PrefetchWiringTests(MediaCase):
    def list_token(self):
        return ("recent", self.c.screen.view_id, (self.c.recent.rev, self.c.favourites.rev))

    def test_a_presented_list_is_prefetched_once_by_distance(self):
        self.load_recent()
        self.assertEqual(self.artwork.prefetches, [([cover_url(i) for i in range(10)], self.list_token())])
        self.turn_to(4)
        self.turn_to(5)
        self.assertEqual(len(self.artwork.prefetches), 1, "a selection change asks nothing")
        self.c.button(0)          # Home: leaving Recent drops the unstarted jobs
        self.settle()
        self.assertEqual(self.artwork.prefetches[-1], ([], None))

    def test_prefetch_starts_from_the_presented_selection(self):
        self.load_recent()
        self.turn_to(7)
        self.c.button(1)          # Open: the explorer (the same list, a new presentation)
        self.settle()
        self.c.button(0)          # Back: Recently Added at the explorer's index
        self.settle()
        self.assertEqual((self.c.screen.mode, self.c.screen.index), ("recent", 7))
        self.assertEqual(self.artwork.prefetches[-1], ([cover_url(i) for i in by_distance(10, 7)], self.list_token()))
        self.assertEqual(self.artwork.prefetches[-1][0][:2], [cover_url(7), cover_url(8)])

    def test_a_prefetched_cover_swaps_in_before_the_debounced_request(self):
        self.load_recent()
        self.artwork.finish()
        frames = self.turn_to(5)
        self.assertEqual(frames[-1]["artKey"], "", "a miss shows no art yet")
        self.assertEqual(self.artwork.pending[0], cover_url(5))
        self.artwork.load(cover_url(5))            # the page prefetch cached it meanwhile
        self.runtime.poll()
        self.assertEqual(self.runtime.frame()["artKey"], jpeg_key(5))
        self.assertIsNone(self.artwork.pending, "the debounced request is obsolete")
        self.assertEqual(self.device.last_wanted("cover")[0][0], jpeg_key(5))

    def test_disabled_artwork_prefetches_and_lists_nothing(self):
        self.runtime.artwork_enabled = False
        self.load_recent()
        self.artwork.load(*[cover_url(i) for i in range(10)])
        self.runtime.poll()
        self.assertEqual(self.artwork.prefetches, [])
        self.assertEqual(self.device.last_wanted("cover"), [])
        self.assertEqual(self.runtime.frame()["artKey"], "")


class StatusTests(MediaCase):
    def test_events_feed_the_media_status(self):
        put = self.device.events.put
        put({"kind": "media-ready", "media": "cover", "key": "c1"})
        put({"kind": "media-ready", "media": "cover", "key": "c2", "hit": True})
        put({"kind": "media-error", "media": "cover", "key": "c3", "error": "Media decode failed"})
        put({"kind": "media-error", "media": "cover", "key": "c3", "error": "Media decode failed"})
        put({"kind": "media-error", "media": "icon", "key": "i1", "error": "Stale media control"})
        put({"kind": "media-error", "media": "icon", "key": "i1", "error": "Stale media control"})
        put({"kind": "media-error", "mediaKind": "icon", "key": "i2", "error": "timeout", "failed": True})
        put({"kind": "media-ready", "media": "poster", "key": "x"})   # unknown kind: ignored
        self.runtime.poll()
        status = self.runtime.media_status()
        self.assertEqual(set(status), set(MEDIA_KINDS))
        self.assertEqual(status["cover"], {"wanted": 0, "present": 2, "uploads": 1, "hits": 1, "errors": 2,
                                           "failedKeys": ["c3"], "lastError": "Media decode failed"})
        self.assertEqual((status["icon"]["errors"], status["icon"]["failedKeys"], status["icon"]["lastError"]),
                         (3, ["i2"], "timeout"), "a stale control is not a failure")
        self.device.events.put({"kind": "connected", "capabilities": {"controlCenter": 1}})
        self.runtime.poll()
        again = self.runtime.media_status()["cover"]
        self.assertEqual((again["present"], again["failedKeys"], again["uploads"]), (0, [], 1),
                         "a reconnect clears the mirror, not the counters")

    def test_the_bridge_figures_win_and_status_json_carries_both_fields(self):
        self.load_recent()
        self.artwork.load(*[cover_url(i) for i in range(3)])
        self.runtime.poll()
        app = SimpleNamespace(runtime=self.runtime, controller=self.c, live=True)
        caps = {"controlCenter": 1, "presentation": 4, "glyphs": "latin-ext-a", "artwork2": ARTWORK2_CAPABILITY}
        status = standalone.status_payload(app, standalone.RetryPolicy(), {"exists": False}, caps, Path("data"))
        self.assertEqual(status["media"]["cover"]["wanted"], 3, "without bridge figures: this runtime's list")
        self.device.media_status = lambda: {"cover": {"wanted": 2, "present": 7, "uploads": 9, "hits": 4,
                                                      "errors": 1, "failedKeys": ["abc", "bad key!"],
                                                      "lastError": "x" * 200, "dropped": 1}}
        status = standalone.status_payload(app, standalone.RetryPolicy(), {"exists": False}, caps, Path("data"))
        self.assertIs(status["artwork2"], True)
        cover = status["media"]["cover"]
        self.assertEqual((cover["wanted"], cover["present"], cover["uploads"], cover["hits"], cover["errors"],
                          cover["dropped"]), (2, 7, 9, 4, 1, 1))
        self.assertEqual(cover["failedKeys"], ["abc"])
        self.assertEqual(len(cover["lastError"]), 80)
        self.assertEqual(status["media"]["icon"]["wanted"], 0)
        json.dumps(status)
        self.device.media_status = lambda: 1 / 0          # never breaks status.json
        self.assertEqual(standalone.media_status(self.runtime)["cover"]["wanted"], 3)
        self.assertIsNone(standalone.media_status(SimpleNamespace()))
        bare = standalone.status_payload(SimpleNamespace(runtime=SimpleNamespace(
            device_connected=False, device_status="", led_style="white", artwork_enabled=True, artwork_status=None,
            apple=None), controller=self.c, live=False), standalone.RetryPolicy(), {"exists": False})
        self.assertEqual((bare["artwork2"], bare["media"]), (False, None))


class MirrorInputTests(MediaCase):
    def test_lcd_media_gives_the_knob_payloads_with_artwork2(self):
        self.load_recent()
        self.artwork.finish()
        self.runtime.poll()
        frame = self.runtime.frame()
        art, icon, artwork2, identity = self.runtime.lcd_media(frame)
        self.assertEqual((art, icon, artwork2), (prepared(cover_url(0)).jpeg, None, True))
        with_art = render_lcd(frame, art, icon, artwork2=artwork2)
        self.assertNotEqual(with_art.tobytes(), render_lcd(frame, None, None, artwork2=True).tobytes())
        self.open_windows()
        image = rgba(9)
        self.icons.results = [("w1", image, 1)]
        self.runtime.poll()
        frame = self.runtime.frame()
        item = self.c.presented()
        art, icon, artwork2, identity2 = self.runtime.lcd_media(frame, item)
        self.assertEqual((art, icon), (None, icon_payload(image)[1]))
        self.assertEqual(frame["iconKey"], icon_payload(image)[0])
        self.assertNotEqual(identity, identity2)
        drawn = render_lcd(frame, art, icon, artwork2=True).convert("RGB")
        self.assertNotEqual(drawn.crop((104, 42, 136, 74)).tobytes(),
                            render_lcd(frame, None, None, artwork2=True).convert("RGB").crop((104, 42, 136, 74)).tobytes())

    def test_lcd_media_is_the_v1_inputs_without_artwork2(self):
        self.device.media_capability = None
        self.load_recent()
        self.artwork.finish()
        self.runtime.poll()
        frame = self.runtime.frame()
        art, icon, artwork2, _ = self.runtime.lcd_media(frame)
        self.assertFalse(artwork2)
        self.assertEqual(art.tobytes(), prepared(cover_url(0)).preview.tobytes())
        self.open_windows()
        image = rgba(1)
        self.icons.results = [("w1", image, 1)]
        self.runtime.poll()
        _, icon, _, identity = self.runtime.lcd_media(self.runtime.frame(), self.c.presented())
        self.assertIs(icon, image)
        self.assertEqual(identity, ("", ("w1", id(image)), False))


def _ui_mirror_follows_artwork2():
    """True once ui.py takes the lcd_media inputs (the pending cross-track change)."""
    try:
        from control_center import ui
        return "artwork2" in inspect.signature(ui.compose_lcd).parameters
    except Exception:
        return False


@unittest.skipUnless(_ui_mirror_follows_artwork2(), "ui.py artwork2 mirror change pending (cross-track request)")
class DesktopMirrorTests(MediaCase):
    """ui.ControlCenterApp._draw_lcd fed by Runtime.lcd_media, with a stand-in ``self`` (no Tk window)."""

    def app(self, runtime):
        from control_center import ui
        self.pasted = []
        return SimpleNamespace(runtime=runtime, _lcd_key=None, _lcd_cache=OrderedDict(), lcd_renders=0,
                               lcd_photo=SimpleNamespace(paste=self.pasted.append),
                               _presented_window=lambda: self.c.presented())

    def draw(self, app, frame):
        from control_center import ui
        ui.ControlCenterApp._draw_lcd(app, frame, True)
        return self.pasted[-1].tobytes()

    def test_the_desktop_mirror_draws_the_knobs_cover_and_icon(self):
        from control_center import ui
        self.load_recent()
        self.artwork.finish()
        self.runtime.poll()
        app = self.app(self.runtime)
        frame = self.runtime.frame()
        self.assertEqual(frame["artKey"], jpeg_key(0))
        drawn = self.draw(app, frame)
        self.assertEqual(drawn, ui.compose_lcd(frame, prepared(cover_url(0)).jpeg, None, True).tobytes())
        self.assertNotEqual(drawn, ui.compose_lcd(frame, None, None, True).tobytes(), "the cover is shown")
        self.assertEqual(app._lcd_key[1:], (jpeg_key(0), None, True))
        self.open_windows()
        image = rgba(9)
        self.icons.results = [("w1", image, 1)]
        self.runtime.poll()
        frame = self.runtime.frame()
        drawn = self.draw(app, frame)
        self.assertEqual(drawn, ui.compose_lcd(frame, None, icon_payload(image)[1], True).tobytes())
        self.assertEqual(app._lcd_key[1:], ("", icon_payload(image)[0], True))

    def test_without_lcd_media_or_artwork2_the_mirror_is_as_before(self):
        from control_center import ui
        self.device.media_capability = None
        self.load_recent()
        self.artwork.finish()
        self.runtime.poll()
        frame = self.runtime.frame()
        preview = self.runtime.artwork_result.preview
        expected = ui.compose_lcd(frame, preview, None).tobytes()
        self.assertEqual(self.draw(self.app(self.runtime), frame), expected)
        legacy = SimpleNamespace(artwork_result=self.runtime.artwork_result, window_icons={})
        app = self.app(legacy)
        self.assertEqual(self.draw(app, frame), expected)
        self.assertEqual(app._lcd_key[1:], (frame["artKey"], None))


class RealServiceTests(MediaCase):
    """The real ArtworkService (worker threads, in-memory HTTP): prefetch fills the wanted list."""

    def make_artwork(self):
        self.session = Session({url: Response(data) for url, data in SOURCES.items()})
        service = ArtworkService(session=self.session, debounce=0)
        self.addCleanup(service.close)
        return service

    def test_a_presented_page_reaches_the_cover_list_by_distance(self):
        self.load_recent()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and len(self.runtime.media_wanted["cover"]) < 10:
            self.runtime.poll()
            time.sleep(0.01)
        keys = [key for key, _ in self.device.last_wanted("cover")]
        self.assertEqual(keys, [jpeg_key(i) for i in range(10)])
        self.assertEqual(self.runtime.frame()["artKey"], jpeg_key(0))
        downloaded = [url for url, _ in self.session.calls]
        self.assertEqual(sorted(downloaded), sorted(cover_url(i) for i in range(10)), "each cover once")
        self.assertEqual(self.art_commands(), [])


if __name__ == "__main__":
    unittest.main()
