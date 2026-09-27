"""End-to-end wire capture: a scripted knob session through the real companion stack (desktop v7).

The real v7 ``Controller`` and ``Runtime`` (the K3 section 16 simulator fakes with scripted
content and outcomes, a FakeStagePresenter, fake ArtworkService/AccentService/IconWorker with
deterministic results) drive a real ``DeviceBridge`` whose serial port is an in-memory fake
knob. Every line the bridge writes is recorded, byte for byte, as it reaches the knob:
``{"frame":…}`` and ``{"control":…}`` lines in full, art lines as their op, offset and size
(their base64 payload is not kept), inventory and diag queries and the release in full.

Four sessions run the same script, one per row of PRESENTATION_V5.md section 2.1 that a
desktop v7 host meets:

* ``p5`` against a cc5.4 knob (presentation 5, ``alive``, ``artwork2``, ``diag``): the full v5
  frames with the ALIVE and v5 latched fields, ``ks`` in ``ready``, ``kh`` holds, ``hid`` on the
  Win press and ``lim`` end-stop pushes; unpaced whole-line writes into the CDC receive-queue
  model with seeded COM stalls and the section 4.4 media store model;
* ``a2`` against a cc5.3 knob (presentation 4 + ``artwork2``): the section 2.2 downgrade on the
  same CDC and media models;
* ``p4`` against a cc5 knob (presentation 4, the v1 ``artwork`` capability): the downgrade with
  paced v1 art lines;
* ``p2`` against a cc4 knob (presentation 2, no artwork, ASCII): the host's legacy stripping.

The script covers startup (inventory, "Looking for Sonos…", the first Sonos read), Home
playing/paused/idle, volume turns (pending, confirmed, bounds, an external change), Tracks
(Prev/Next skips over multibyte, escaped and over-capacity titles, a failed skip, the queue
end, Previous unavailable), Seek (the lap ring and a jump, the end stop), Up next (rows, a Like,
the companion shuffle, Play), Recently Added (the flat list with its lookahead page, detents
across the 20-entry window, an unavailable item, Play next with its progress, Play, a failed
start and a blocked album), the Music explorer (both tabs, Play), Windows (24 windows incl.
closed ones, a snap pair, Switch failure and success, Back, an empty picker), a hold to Home
from Seek (its press a Back to Tracks that re-enters with the button down, then the ``kh``),
both LED styles, reduced motion, Sonos down, the list notices (sign-in expired, error, empty),
the once-a-minute diag (PRESENTATION_V5.md 12.3) and the final release.

Nothing here opens a port, touches the network or a real window, or reads user data: the
inventory backup goes to a temporary directory, the runtime's I/O lanes run synchronously
under script control, and one fake clock drives the controller, the runtime, the simulator and
the bridge, so a capture is deterministic.

Usage: .venv\\Scripts\\python.exe tests\\tools\\capture_session_frames.py [--out capture.jsonl]
Then:  .venv\\Scripts\\python.exe ..\\harness\\parse_tests.py --frames capture.jsonl
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter, OrderedDict, deque
from concurrent.futures import Future
from copy import deepcopy
import dataclasses
from functools import lru_cache
import hashlib
import io
import json
from pathlib import Path
import random
import re
import sys
import tempfile
from unittest.mock import patch
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center import presentation  # noqa: E402
from control_center.artwork import ArtworkResult  # noqa: E402
from control_center.controller import PROFILES, Controller  # noqa: E402
from control_center.device import DeviceBridge, PacedSerial  # noqa: E402
from control_center.runtime import Runtime  # noqa: E402
from control_center.simulation import (FakeStagePresenter, SimControls, SimulatedAppleMusic,  # noqa: E402
                                       SimulatedSonos, SimulatedToasts, SimulatedWindows)

DEFAULT_OUTPUT = ROOT.parent / "harness" / "build" / "session-capture" / "session.jsonl"
LINE_LIMIT = 4096  # bytes per line including the newline (DeviceBridge._write; firmware kLineCapacity + 1)

# Capability replies, as the firmware answers {"capabilities":"?"}.
ARTWORK = {"version": 1, "width": 120, "height": 120, "format": "RGB565_LE", "chunkBytes": 384,
           "cacheEntries": 8, "available": True, "composited": "scrim80"}
_COMMON = {"controlCenter": 1, "leaseMs": 2000, "hostFrame": 1, "runtimeProfileBounds": 1, "taggedInput": 1,
           "windowsHidKey": "F24", "buttonOrder": 1, "windowsHidControl": 1}
CC5_CAPABILITIES = {**_COMMON, "presentation": 4, "glyphs": "latin-ext-a", "artwork": ARTWORK, "diag": 1}
CC4_CAPABILITIES = {**_COMMON, "presentation": 2}
# cc5.3: the v1 artwork object unchanged plus the artwork2 sibling (ARTWORK2.md section 1).
CC53_CAPABILITIES = {**CC5_CAPABILITIES, "artwork2": deepcopy(presentation.ARTWORK2_CAPABILITY)}
# cc5.4 (PRESENTATION_V5.md section 1, CCP:174-203): presentation 5 and `alive`, every other key as cc5.3.
CC54_CAPABILITIES = {**_COMMON, "presentation": 5, "glyphs": "latin-ext-a",
                     "alive": {"version": presentation.ALIVE_VERSION, "fps": 60, "drive": 51},
                     "artwork": ARTWORK, "artwork2": deepcopy(presentation.ARTWORK2_CAPABILITY), "diag": 1}
SESSIONS = {"p5": CC54_CAPABILITIES, "a2": CC53_CAPABILITIES, "p4": CC5_CAPABILITIES, "p2": CC4_CAPABILITIES}
FIRMWARE = {"p5": "1.0.0-cc5.4", "a2": "1.0.0-cc5.3", "p4": "1.0.0-cc5", "p2": "1.0.0-cc4"}
# The artwork2 knobs' COM thread stalls for 30-100 ms every 0.2-0.8 s (seeded, deterministic).
A2_STALLS = {"gap": (0.2, 0.8), "duration": (0.030, 0.100), "seed": 53}

# The knob's installed profiles (every name the controller uses, plus others).
KNOB_PROFILES = {name: {"name": name, "desc": "installed", "keys": [{"pressed": []}] * 4,
                        "knob": [{"haptic": {"mode": 0, "startPos": 0, "endPos": 8, "detentCount": 8,
                                             "outputRamp": 10000}}]}
                 for name in sorted(set(PROFILES.values()) | {"NANO_D DEFAULT"})}


class CaptureError(RuntimeError):
    """The session broke: the bridge failed, the knob refused a line, or nothing settled."""


# ---------------------------------------------------------------------------
# Time and I/O lanes.

class Clock:
    """One fake monotonic clock for the controller, the runtime and the bridge."""

    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class RuntimeTime:
    """Stands in for the `time` module inside control_center.runtime."""

    def __init__(self, clock):
        self.clock = clock

    def monotonic(self):
        return self.clock()

    def sleep(self, seconds):
        self.clock.advance(max(0.0, seconds))


class Lane:
    """A single-worker I/O lane (runtime ThreadPoolExecutor stand-in) run by the script."""

    def __init__(self, **_options):
        self.jobs = []
        self.closed = False

    def submit(self, function, *args):
        future = Future()
        self.jobs.append((future, function, args))
        return future

    @staticmethod
    def kind(job):
        """The op of a library or lookahead job (the audio lane's kinds are Runtime.audio_lane's)."""
        _future, function, args = job
        name = getattr(function, "__name__", "job")
        if name == "_apple_op" and args and isinstance(args[0], dict):
            return args[0]["kind"]  # recent, like, favourite_playlists, ...
        if name == "_resolve":
            return "resolve"        # a start's or a Play next's library lookup
        return name                 # _drain: an AudioLane / LookaheadLane pass

    def head(self):
        return self.kind(self.jobs[0]) if self.jobs else None

    def run_next(self):
        future, function, args = self.jobs.pop(0)
        if not future.set_running_or_notify_cancel():
            return
        try:
            future.set_result(function(*args))
        except BaseException as exc:  # the runtime's done-callbacks report it
            future.set_exception(exc)

    def shutdown(self, wait=True, cancel_futures=False):
        self.closed = True
        if cancel_futures:
            for future, _function, _args in self.jobs:
                future.cancel()
            self.jobs.clear()


# ---------------------------------------------------------------------------
# Deterministic content and presentation services.

def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).digest()


def accent_for(text):
    """A stable 0xRRGGBB accent, or None ("no dominant colour", white) for about one in five."""
    digest = _digest(text)
    if digest[0] % 5 == 0:
        return None
    return int.from_bytes(digest[1:4], "big") | 0x101010


def cover_url(name):
    return f"https://is1-ssl.mzstatic.com/image/thumb/capture/{name}/600x600bb.jpg"


def cover_key(url):
    return "cap_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


@lru_cache(maxsize=64)
def cover_pixels(key):
    seed = _digest(key)
    return bytes((seed[i % 32] + i * 7) & 0xFF for i in range(120 * 120 * 2))


@lru_cache(maxsize=128)
def cover_jpeg(key):
    """A deterministic 240x240 baseline JPEG (the host encoder's settings) for cover `key`."""
    from PIL import Image, ImageDraw
    seed = _digest("jpeg:" + key)
    image = Image.new("RGB", (240, 240), tuple(seed[:3]))
    draw = ImageDraw.Draw(image)
    for i in range(6):
        x, y = seed[3 + i] % 200, seed[9 + i] % 200
        draw.rectangle((x, y, x + 20 + seed[15 + i] % 40, y + 20 + seed[21 + i] % 40),
                       fill=tuple(seed[3 * i:3 * i + 3]))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=85, subsampling=2, optimize=True, progressive=False)
    return output.getvalue()


def jpeg_key(jpeg):
    return hashlib.sha256(jpeg).hexdigest()[:presentation.COVER_KEY_CHARS]


_RESULT_FIELDS = ({field.name for field in dataclasses.fields(ArtworkResult)}
                  if dataclasses.is_dataclass(ArtworkResult) else set())


def artwork_result(token, key, url):
    """What ArtworkService delivers: the v1 payload, plus the artwork2 JPEG when it has one."""
    extra = {}
    if {"jpeg", "jpeg_key"} <= _RESULT_FIELDS:
        jpeg = cover_jpeg(key)
        extra = {"jpeg": jpeg, "jpeg_key": jpeg_key(jpeg)}
    return ArtworkResult(token, key, None, cover_pixels(key), accent_for(url), **extra)


class FakeArtwork:
    """ArtworkService stand-in: a cover arrives on the poll after its request (late
    arrival); a URL containing "broken" fails like an unreadable cover. Delivered
    covers stay in a memory cache (16 entries as in cc5.2, `cache_size` otherwise)
    that cached() answers synchronously, so a revisited cover swaps in on the same
    detent (contract section 6). artwork2: cached_cover() gives a cached cover's
    (jpeg_key, jpeg), and prefetch() jobs run one per poll, after the foreground
    request, into the same cache (`version` grows on every cache change)."""

    CACHE_SIZE = 16  # ArtworkService's cc5.2 default

    def __init__(self, cache_size=CACHE_SIZE):
        self.cache_size = cache_size
        self.requests, self.delivered, self.failed, self.hits = [], 0, 0, 0
        self.prefetches, self.prefetched = [], 0
        self._pending = None
        self._prefetch = deque()
        self._cache = OrderedDict()  # url -> key
        self.version = 0
        self.closed = False

    def cached(self, url, token=None, *, speaker_host=None):
        key = self._cache.get(url)
        if key is None:
            return None
        self._cache.move_to_end(url)
        self.hits += 1
        return artwork_result(token, key, url)

    def cached_cover(self, url, *, speaker_host=None):
        key = self._cache.get(url)
        if key is None:
            return None
        self._cache.move_to_end(url)
        jpeg = cover_jpeg(key)
        return jpeg_key(jpeg), jpeg

    def request(self, url, token=None, *, speaker_host=None):
        self.requests.append(url)
        self._pending = [url, token, 1]

    def prefetch(self, urls, *, page=None, speaker_host=None):
        urls = [url for url in urls if isinstance(url, str) and url]
        self.prefetches.append((urls, page))
        self._prefetch = deque(urls)  # a new page drops the jobs that have not started

    def clear(self):
        self._pending = None

    def pending(self):
        return self._pending is not None or bool(self._prefetch)

    def _store(self, url):
        key = cover_key(url)
        self._cache[url] = key
        self._cache.move_to_end(url)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        self.version += 1
        return key

    def poll(self):
        if self._pending is None:
            if self._prefetch:  # the foreground request always runs first
                url = self._prefetch.popleft()
                if "broken" not in url and url not in self._cache:
                    self._store(url)
                    self.prefetched += 1
            return []
        if self._pending[2] > 0:
            self._pending[2] -= 1
            return []
        url, token, _ = self._pending
        self._pending = None
        if "broken" in url:
            self.failed += 1
            return [ArtworkResult(token, error="Artwork could not be loaded.")]
        self.delivered += 1
        key = self._store(url)
        return [artwork_result(token, key, url)]

    def close(self):
        self.closed = True


class FakeAccents:
    """AccentService stand-in: each URL's accent arrives on the poll after the request."""

    def __init__(self):
        self.requests, self._pending, self._ready = [], [], []
        self.closed = False

    def request_many(self, urls, token=None, *, speaker_host=None):
        self.requests.append((list(urls), token))
        self._pending = [(token, url, accent_for(url)) for url in urls]
        return len(self.requests)

    def pending(self):
        return bool(self._pending or self._ready)

    def poll(self):
        results, self._ready, self._pending = self._ready, self._pending, []
        return results

    def clear(self):
        self._pending, self._ready = [], []

    def close(self):
        self.closed = True


def window_icon(app):
    """A deterministic 32x32 RGBA app icon (partly transparent), or None for about one app in four."""
    digest = _digest("icon:" + app)
    if digest[0] % 4 == 0:
        return None  # no icon: the letter tile
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((2, 2, 29, 29), fill=(digest[1], digest[2], digest[3], 255))
    draw.rectangle((10, 10, 21, 21), fill=(digest[4], digest[5], digest[6], 160))
    return image


class FakeIcons:
    """IconWorker stand-in: (item id, icon, accent) per window on the poll after the request.
    Icons are None (letter tile) unless `images` (then window_icon()); accents are stable
    per app, some None (white)."""

    def __init__(self, images=False):
        self.images = images
        self.requests, self._pending, self._ready = [], [], []
        self.closed = False

    def request(self, items):
        items = list(items)
        self.requests.append([item.get("id") for item in items])
        self._pending = [(item.get("id"), window_icon(str(item.get("app", ""))) if self.images else None,
                          accent_for("app:" + str(item.get("app", "")))) for item in items]
        return len(self.requests)

    def pending(self):
        return bool(self._pending or self._ready)

    def poll(self):
        results, self._ready, self._pending = self._ready, self._pending, []
        return results

    def close(self, timeout=None):
        self.closed = True


# Track and library text: multibyte (latin-ext-a and beyond), JSON escapes, control
# characters, combining marks, compatibility forms and over-capacity titles.
TRACKS = [  # The Sonos queue's first rows; the script skips across all of them.
    ("Colombina", "Mari Froes"),
    ('Say "Hello" \\ Goodbye', "The Backslashes"),
    ("Straße 🎵 Mix\tfor\nNight", "DJ Ørsted"),
    ("Cafe\u0301 ﬁnale – ½ time €", "Ensemble Übung"),
    ("Déjà Vu", "Beyoncé"),
    ("Łódź “Nocturne” (Live)", "Zbigniew Preisner"),
    ("x" * 91 + "éééé and more", "Überlänge " * 12),  # both over 96 bytes, cut inside "é"
]
QUEUE_ROWS = 12            # TRACKS, then plain rows (the Up next windows and the queue end)

ALBUMS = [  # (title, artist, kind, available): the Recently Added list, in Apple order
    ("Colombina", "Mari Froes", "album", True), ("Déjà Vu", "Beyoncé", "song", True),
    ("Ænima", "Tool", "album", True), ("Sigur Rós · Ágætis byrjun", "Sigur Rós", "album", True),
    ("Łódź Sessions", "Zbigniew Preisner", "playlist", True), ("Unavailable library upload", "", "song", False),
    ("Motörhead — Overkill", "Motörhead", "album", True), ("Café Tacvba", "Café Tacvba", "album", True),
    ("A very long album title that keeps its readable type size on the knob’s round screen, really",
     "Various Artists", "album", True),
    ('Quotes "and" \\backslashes\\', "Escape Artists", "playlist", True),
    ("Straße nach Süden", "Die Ärzte", "album", True), ("Ïn Cölör", "Jamie xx", "album", True),
    ("Moon Safari", "Air", "album", True), ("Private upload (no match)", "", "album", False),
    ("Selected Ambient Works 85–92", "Aphex Twin", "album", True), ("Ōkami Original Soundtrack", "Various", "album", True),
    ("Kind of Blue", "Miles Davis", "album", True), ("Rhythm & Ñ", "Ñu", "song", True),
    ("日本語タイトル", "アーティスト", "album", True), ("Evening Research", "Sample", "playlist", True),
    ("Signals", "Rush", "album", True), ("Ça plane pour moi", "Plastic Bertrand", "song", True),
    ("Žužemberk", "Šoštanj", "album", True), ("Ğüzel", "Şebnem", "album", True),
    ("Last one", "Finale", "album", True),
] + [(f"Capture album {n}", "Page two", "album", True) for n in range(26, 45)]   # the lookahead page

WINDOWS = [  # (app, title, open)
    ("Codex", "Nano_D++ control center", True), ("Claude", "Model training review", True),
    ("Chrome", "Apple Music documentation — Google Chrome", True), ("Slack", "Engineering · #firmware", False),
    ("Microsoft Edge", "Déjà vu: a “quoted” page", True), ("Discord", "Friends", True),
    ("Visual Studio Code", "cc_frame_parse.cpp — NanoD_RatchetH1", True), ("Spotify", "Motörhead — Overkill", True),
    ("Outlook", "Inbox – marcelo@example.invalid", True), ("File Explorer", "C:\\Users\\Public\\Music", True),
    ("Teams", "Weekly sync\twith tabs\nand newlines", True), ("Notepad++", "Łódź notes.txt", False),
    ("WhatsApp", "Família 👨‍👩‍👧", True), ("Figma", "Knob Face · design", True),
    ("Obsidian", "Straße — Übersicht", True), ("Calculator", "Calculator", True),
    ("Terminal", "PowerShell 7 (x64)", True), ("Photos", "IMG_2041.HEIC", False),
    ("Word", "A very long document title that is far longer than the knob can ever show on one line.docx", True),
    ("Excel", "Budget 2026 ½ € ﬁnal.xlsx", True), ("OBS Studio", "Scene: Desk", True),
    ("Steam", "Library", True), ("Zoom", "Zoom Meeting", True), ("Notion", "Ideas · Ästhetik", True),
]
_RESOURCES = {"album": "library-albums", "playlist": "library-playlists", "song": "library-songs"}


def _colour(text):
    digest = _digest("colour:" + text)
    return (digest[0], digest[1], digest[2])


class ScriptedSonos(SimulatedSonos):
    """SimulatedSonos (K3 section 16) with a queue of the TRACKS titles, a cover per row (row 5's
    cover never loads) and a scripted skip failure."""

    def __init__(self, controls, clock):
        super().__init__(controls, clock=clock, sleep=clock.advance)
        self.fail_transport = None      # message for the next skip
        self.state.update(group_room_count=2)
        self.load_capture_queue(position=3)

    def load_capture_queue(self, position=1):
        tracks = []
        for n in range(QUEUE_ROWS):
            title, artist = TRACKS[n] if n < len(TRACKS) else (f"Queue song {n + 1}", "Capture Artists")
            song = str(1_400_900_000 + n)
            tracks.append({"title": title, "artist": artist, "album": "Capture", "catalog_id": song,
                           "url": f"simulation://song/{song}", "track_number": n + 1})
        with self._lock:
            self.queue = [self._row(track) for track in tracks]
            self.P = position
            self.update_id += 1
            self._sync()

    def read_state(self):
        state = super().read_state()
        state["artwork_url"] = cover_url(f"track-{self.P}" + ("-broken" if self.P == 5 else ""))
        return state

    def transport(self, direction, expected_group_revision, expected_track_id=None):
        if self.fail_transport and direction not in ("play", "pause"):
            message, self.fail_transport = self.fail_transport, None
            raise RuntimeError(message)
        return super().transport(direction, expected_group_revision, expected_track_id)


class ScriptedAppleMusic(SimulatedAppleMusic):
    """The flat Recently Added list (pages of 25 with meta.total, K3 9.8.6) built from ALBUMS: two
    library uploads without a catalog match, songs and playlists, one cover that never loads, a few
    items without art (the Generated sleeve) and, for most items, the accent left to the
    AccentService (the item carries no `accent`)."""

    def _library(self):
        count = {"empty": 0}.get(self.controls.recent, len(ALBUMS))
        items = []
        for index, (title, artist, kind, available) in enumerate(ALBUMS[:count]):
            item = self._item(f"al-{index}", title, artist, kind, _colour(title), 10, available=available,
                              resource=_RESOURCES[kind], index=index, art="missing" if index % 7 == 6 else "full")
            if index == 4:
                item["art_template"] = "simulation://art/al-4-broken/{w}x{h}bb.jpg"
            if not available:
                item["reason"] = "No Sonos-compatible catalog match"
            if item["art_template"] and index % 6 != 3:
                del item["accent"]           # the AccentService supplies it (runtime section 10.4)
            items.append(item)
        return items


class ScriptedWindows(SimulatedWindows):
    """A live-like picker: 24 windows (some closed), private exe paths and no accents (the icon
    worker supplies them); the F24 hotkey owns Windows entry. Snaps follow SimControls.snap."""
    supports_hotkey = True

    def __init__(self, controls):
        super().__init__(controls)
        self.activate_result = True
        self.empty_next = False
        self.calls = Counter()

    def snapshot(self):
        self.calls["snapshot"] += 1
        if self.empty_next:
            self.empty_next = False
            return {"items": [], "index": 0, "origin": {"hwnd": 0x1000, "pid": 4000}}
        items = [{"id": f"w{i}", "hwnd": 0x1000 + i, "pid": 4000 + i, "title": title, "app": app,
                  "path": f"C:\\Program Files\\{app}\\{app.replace(' ', '')}.exe", "available": is_open}
                 for i, (app, title, is_open) in enumerate(WINDOWS)]
        return {"items": items, "index": 1, "origin": {"hwnd": 0x1000, "pid": 4000}}

    def show(self, snapshot):
        self.calls["show"] += 1
        super().show(snapshot)

    def highlight(self, index, *args, **kwargs):
        self.calls["highlight"] += 1

    def activate(self, item):
        self.calls["activate"] += 1
        super().activate(item)
        return bool(item["available"] and self.activate_result)

    def cancel(self, origin, complete=None):
        self.calls["cancel"] += 1
        return super().cancel(origin, complete)

    def hide(self):
        self.calls["hide"] += 1
        super().hide()

    def close(self):
        self.calls["close"] += 1

    def set_hotkey_enabled(self, enabled):
        self.calls["hotkey-on" if enabled else "hotkey-off"] += 1


# ---------------------------------------------------------------------------
# The knob and the recorder.

class Recorder:
    """Every line the bridge writes, in order, with the session step that caused it."""

    def __init__(self, clock):
        self.clock = clock
        self.records = []
        self.session = ""
        self.presentation = 0
        self.step = ""

    def record(self, raw, message):
        kind = classify(message)
        record = {"n": len(self.records) + 1, "session": self.session, "presentation": self.presentation,
                  "step": self.step, "t": round(self.clock() - 1000.0, 3), "kind": kind, "bytes": len(raw)}
        if kind == "art":
            art = message["art"]
            record.update(op=art.get("op"), id=art.get("id"), key=art.get("key"))
            if "offset" in art:
                record["offset"] = art["offset"]
            if art.get("op") != "data":
                record["line"] = raw[:-1].decode("utf-8")
        elif kind == "media":
            media = message["media"] if isinstance(message["media"], dict) else {}
            record.update(op=media.get("op"), id=media.get("id"), media=media.get("kind"), key=media.get("key"))
            if "offset" in media:
                record["offset"] = media["offset"]
            if media.get("op") != "data":
                record["line"] = raw[:-1].decode("utf-8")
        else:
            record["line"] = raw[:-1].decode("utf-8", errors="replace")
        self.records.append(record)
        return record


def classify(message):
    for kind in ("frame", "control", "art", "media", "release"):
        if kind in message:
            return kind
    return "query"


# ---------------------------------------------------------------------------
# artwork2 on the knob: the media store (ARTWORK2.md section 4.4) and the CDC path.

MEDIA_OPS = ("begin", "data", "commit", "have")
_MEDIA_KEY_RE = re.compile(presentation.MEDIA_KEY_PATTERN)
_ART_KEY_RE = re.compile(presentation.ART_KEY_PATTERN)
_ICON_KEY_RE = re.compile(presentation.ICON_KEY_PATTERN)
UINT32 = 0xFFFFFFFF
SCAN_BYTES = 192  # the firmware's bounded raw-prefix scan (kArtScanBytes)
_JSON_FIRST_VALUE = json.JSONDecoder()  # raw_decode: the first value of a line, as ArduinoJson reads it


def _uint32(value):
    """An integer the firmware reads as uint32 (never a bool, a float or out of range)."""
    return type(value) is int and 0 <= value <= UINT32


def _json_int(value):
    """A JSON integer as the firmware's ArduinoJson stores one: within -2**63..2**64-1 (a
    longer number parses as a float there); never a bool, a float or a string."""
    return type(value) is int and -2 ** 63 <= value <= 2 ** 64 - 1


_B64 = {c: i for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")}


def decode_chunk(text, capacity):
    """A `data` field: standard base64 with padding, 1..capacity bytes decoded, else None.

    Exactly the firmware decoder (cc_media_base64_decode): a non-empty multiple of four
    characters, '=' only as the last one or two, unused low bits of the last character
    ignored (as Python's b64decode(validate=True) does).
    """
    if not isinstance(text, str) or not text or len(text) % 4:
        return None
    pad = (2 if text[-2] == "=" else 1) if text[-1] == "=" else 0
    size = len(text) // 4 * 3 - pad
    if not size or size > capacity:
        return None
    out = bytearray()
    for start in range(0, len(text), 4):
        word = 0
        for j, char in enumerate(text[start:start + 4]):
            final_pad = char == "=" and start + 4 == len(text) and j >= 4 - pad
            value = 0 if final_pad else _B64.get(char, -1)
            if value < 0:
                return None
            word = (word << 6) | value
        out += bytes(((word >> 16) & 0xFF, (word >> 8) & 0xFF, word & 0xFF))
    return bytes(out[:size])


# cc_jpeg.cpp over the ESP32-S3 ROM TJpgDec R0.01b: the decoder's stream buffer (JD_SZBUF)
# and the static work area it prepares in (kWorkWords * 4 bytes).
JD_SZBUF = 512
JPEG_WORK_BYTES = 4096
# SOF types other than SOF0 (progressive, extended, lossless, arithmetic) and EOI: refused
# before SOS by cc_jpeg.cpp prescan() and by jd_prepare alike.
_JPEG_REFUSED = frozenset((0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF, 0xD9))


def jpeg_prescan(data):
    """cc_jpeg.cpp prescan(), step for step: SOI first and EOI as the last two bytes; every
    segment up to SOS is 0xFF, a marker and a length > 2 inside the data (no fill bytes); one
    SOF0 (length >= 8, 8-bit samples, three components) before SOS; another SOF type or EOI
    before SOS rejects. Other segments are left to the decoder."""
    size = len(data)
    if size < 4 or data[0] != 0xFF or data[1] != 0xD8 or data[-2] != 0xFF or data[-1] != 0xD9:
        return False
    sof0, at = False, 2
    while True:
        if size - at < 4 or data[at] != 0xFF:
            return False
        marker, length = data[at + 1], data[at + 2] << 8 | data[at + 3]
        if length <= 2 or length > size - at - 2:
            return False
        if marker == 0xC0:
            segment = data[at + 4:at + 2 + length]
            if sof0 or length < 2 + 6 or segment[0] != 8 or segment[5] != 3:
                return False
            sof0 = True
        elif marker == 0xDA:
            return sof0
        elif marker in _JPEG_REFUSED:
            return False
        at += 2 + length


def _tjpgd_huffman(seg, ndata, alloc, loaded):
    """R0.01b create_huffman_tbl over the loaded segment: True when every table is built."""
    at = 0
    while ndata:
        if ndata < 17:
            return False                        # JDR_FMT1: wrong data size
        ndata -= 17
        d = seg[at]
        at += 1
        if d & 0xEE:
            return False                        # JDR_FMT1: class/number beyond 0/1
        cls, num = d >> 4, d & 0x0F
        if not alloc(16):
            return False                        # JDR_MEM1
        count = sum(seg[at:at + 16])
        at += 16
        loaded.add((num, cls))
        if not alloc(count * 2):
            return False
        if ndata < count:
            return False
        ndata -= count
        if not alloc(count):
            return False
        values = seg[at:at + count]
        at += count
        if not cls and any(value > 11 for value in values):
            return False                        # a DC category beyond 11
    return True


def _tjpgd_quant(seg, ndata, alloc, loaded):
    """R0.01b create_qt_tbl over the loaded segment: True when every table is built."""
    at = 0
    while ndata:
        if ndata < 65:
            return False                        # JDR_FMT1: table size is unaligned
        ndata -= 65
        d = seg[at]
        at += 65
        if d & 0xF0:
            return False                        # JDR_FMT1: not 8-bit
        if not alloc(64 * 4):
            return False                        # JDR_MEM1
        loaded.add(d & 3)
    return True


def tjpgd_prepare(data, inbuf):
    """jd_prepare of the ROM TJpgDec R0.01b as cc_jpeg.cpp calls it: (width, height), or None
    for any error. Never decodes the scan.

    `inbuf` (a bytearray of JD_SZBUF) is the decoder's stream buffer: the first 512 bytes
    of cc_jpeg.cpp's static COM work area, zero at boot and never cleared, so a short SOF0
    or SOS segment reads what an earlier segment or validation left there, as the ROM
    does. The rest of the 4 KB area is allocated as the decoder does (4-byte aligned):
    the tables, then the IDCT/RGB and MCU buffers at SOS; running out is an error.
    """
    pool = [JPEG_WORK_BYTES]
    position = [0]

    def alloc(size):
        size = (size + 3) & ~3
        if pool[0] < size:
            return False
        pool[0] -= size
        return True

    def infunc(count, into=None):
        count = min(count, len(data) - position[0])
        if into is not None and count:
            inbuf[into:into + count] = data[position[0]:position[0] + count]
        position[0] += count
        return count

    if not alloc(JD_SZBUF):
        return None
    if infunc(2, 0) != 2 or inbuf[0] != 0xFF or inbuf[1] != 0xD8:
        return None
    ofs, width, height, msx, msy = 2, 0, 0, 0, 0
    qtid, huffman, quant = [0, 0, 0], set(), set()
    while True:
        if infunc(4, 0) != 4:
            return None
        marker, length = inbuf[0] << 8 | inbuf[1], inbuf[2] << 8 | inbuf[3]
        if length <= 2 or marker >> 8 != 0xFF:
            return None
        length -= 2
        ofs += 4 + length
        kind = marker & 0xFF
        if kind in (0xC0, 0xDD, 0xC4, 0xDB, 0xDA):
            if length > JD_SZBUF or infunc(length, 0) != length:
                return None                     # JDR_MEM2 / JDR_INP
        if kind == 0xC0:
            width, height = inbuf[3] << 8 | inbuf[4], inbuf[1] << 8 | inbuf[2]
            if inbuf[5] != 3:
                return None
            for component in range(3):
                factor = inbuf[7 + 3 * component]
                if component == 0:
                    if factor not in (0x11, 0x22, 0x21):
                        return None
                    msx, msy = factor >> 4, factor & 15
                elif factor != 0x11:
                    return None
                if inbuf[8 + 3 * component] > 3:
                    return None
                qtid[component] = inbuf[8 + 3 * component]
        elif kind == 0xDD:
            pass                                # DRI: the restart interval only
        elif kind == 0xC4:
            if not _tjpgd_huffman(inbuf, length, alloc, huffman):
                return None
        elif kind == 0xDB:
            if not _tjpgd_quant(inbuf, length, alloc, quant):
                return None
        elif kind == 0xDA:
            if not width or not height or inbuf[0] != 3:
                return None
            for component in range(3):
                if inbuf[2 + 2 * component] not in (0x00, 0x11):
                    return None
                table = 1 if component else 0   # by component: Y table 0, chroma table 1
                if (table, 0) not in huffman or (table, 1) not in huffman or qtid[component] not in quant:
                    return None
            blocks = msx * msy
            if not blocks or not alloc(max(blocks * 64 * 2 + 64, 256)) or not alloc((blocks + 2) * 64):
                return None
            ofs %= JD_SZBUF
            if ofs:
                infunc(JD_SZBUF - ofs, ofs)     # the bit stream pre-load (kept in the buffer)
            return width, height
        elif kind in _JPEG_REFUSED:
            return None                         # JDR_FMT3
        elif infunc(length) != length:
            return None                         # a skipped segment cut short


def jpeg_baseline_240(data, inbuf=None):
    """The knob's cover check (cc_jpeg_validate, ARTWORK2.md sections 4.3 and 5), step for step.

    1..32768 bytes, jpeg_prescan(), then tjpgd_prepare() (the ROM decoder's own checks:
    three components, luma 1x1/2x1/2x2 and chroma 1x1, table ids, 8-bit quantisation tables
    and Huffman tables of classes and numbers 0/1 loaded for every component, all within
    the 4 KB work area), and the prepared size exactly 240x240. The scan itself is not
    decoded, as on the knob: a cover whose entropy-coded data is damaged passes here and
    fails later on the LCD. `inbuf` is the COM decoder's persistent stream buffer (a fresh,
    zeroed one when None: the first validation after boot).
    """
    data = bytes(data)
    if not 1 <= len(data) <= presentation.COVER_MAX_BYTES or not jpeg_prescan(data):
        return False
    size = tjpgd_prepare(data, inbuf if inbuf is not None else bytearray(JD_SZBUF))
    return size == (presentation.COVER_SIZE, presentation.COVER_SIZE)


class MediaSlot:
    __slots__ = ("valid", "key", "bytes", "crc", "stamp", "data")

    def __init__(self, slot_bytes):
        self.valid, self.key, self.bytes, self.crc, self.stamp = False, "", 0, 0, 0
        self.data = bytearray(slot_bytes)


class MediaKindStore:
    """One kind's store: entries + 1 slots, its clock, `displayed` and `frameKey`."""

    def __init__(self, entries, slot_bytes, available=True):
        self.available = available
        self.slots = [MediaSlot(slot_bytes) for _ in range(entries + 1)] if available else []
        self.clock = 0
        self.displayed = -1
        self.frame_key = ""

    def touch(self, index):
        self.clock = (self.clock + 1) & UINT32
        self.slots[index].stamp = self.clock

    def find(self, key):
        for index, slot in enumerate(self.slots):
            if slot.valid and slot.key == key:
                return index
        return -1

    def pinned(self):
        """`displayed` and the valid slot holding `frameKey`: never victims."""
        pins = {self.displayed} if self.displayed >= 0 else set()
        if self.frame_key:
            index = self.find(self.frame_key)
            if index >= 0:
                pins.add(index)
        return pins

    def victim(self):
        """The lowest-index invalid slot, else the least recently touched valid one (ties:
        lowest index); pinned slots never. -1 when every slot is pinned."""
        pins = self.pinned()
        for index, slot in enumerate(self.slots):
            if not slot.valid and index not in pins:
                return index
        best = -1
        for index, slot in enumerate(self.slots):
            if slot.valid and index not in pins and (best < 0 or slot.stamp < self.slots[best].stamp):
                best = index
        return best

    def adopt(self, key):
        """The LCD draws `key` (or no media of this kind when it is not held)."""
        index = self.find(key) if key else -1
        if index < 0:
            self.displayed = -1
        elif index != self.displayed:
            self.displayed = index
            self.touch(index)

    def table(self):
        return [[slot.valid, slot.key, slot.stamp] for slot in self.slots]


class MediaUpload:
    """The one global upload context (both kinds)."""
    __slots__ = ("kind", "key", "bytes", "crc", "slot", "received", "hit", "last_offset", "last_length", "running")

    def __init__(self, kind, key, size, crc, slot, received, hit):
        self.kind, self.key, self.bytes, self.crc, self.slot = kind, key, size, crc, slot
        self.received, self.hit = received, hit
        self.last_offset = self.last_length = 0
        self.running = 0  # zlib.crc32 of the bytes received so far


class MediaStoreModel:
    """ARTWORK2.md section 4.4, step for step: the Python reference for the firmware store.

    media(request) takes the parsed `media` object and returns the `mediaAck`
    object (validation order and error strings of section 4.3). An error reply
    echoes the id (an integer 1..0x7FFFFFFF), op, kind and key (never on `have`)
    that parsed validly and, except on `have`, carries `offset`: the matched
    upload's received count, else 0. control(id)/release() change the active
    control (both cancel the upload), frame(artKey, iconKey) sets each store's
    frameKey (a key that cannot name a media slot pins nothing) and adopts it, and
    a successful miss commit of a store's frameKey adopts it. snapshot() is what a
    trace `check` step compares.

    Integers follow 4.3 literally, as JSON integers the firmware's ArduinoJson
    stores (_json_int): a begin `bytes` or `crc32` that is missing, not an integer or
    outside 0..0xFFFFFFFF is "Media size and CRC required" (the lead ruling of
    2026-09-24: negative and huge sizes included), and a `bytes` in that range but
    outside the kind's range is "Invalid media size"; a `data` offset past the
    upload's bytes is "Media chunk bounds", and any other offset that is neither the
    received count nor an identical retry (a negative one included) is "Media offset
    mismatch". Where the contract is silent this follows src/cc_media_store.h (the
    shared traces pin it): a `data` offset that is absent or not an integer fails the
    bounds check after the data check; a begin size must also fit the slot; a request
    that is not an object has no valid field; a `have` error reply carries no
    `offset` (4.2 reads "otherwise offset is 0").
    """

    def __init__(self, *, cover_entries, cover_slot_bytes, cover_max_bytes, icon_entries, icon_slot_bytes,
                 icon_bytes, chunk_bytes, have_keys, validate_jpeg=False, available=None):
        available = available or {}
        self.stores = {"cover": MediaKindStore(cover_entries, cover_slot_bytes, available.get("cover", True)),
                       "icon": MediaKindStore(icon_entries, icon_slot_bytes, available.get("icon", True))}
        self.slot_bytes = {"cover": cover_slot_bytes, "icon": icon_slot_bytes}
        self.cover_max_bytes, self.icon_bytes = cover_max_bytes, icon_bytes
        self.chunk_bytes, self.have_keys, self.validate_jpeg = chunk_bytes, have_keys, validate_jpeg
        self.active_id = None
        self.upload = None
        self.media_version = 0
        self.commits = self.errors = self.evictions = 0
        self.jpeg_inbuf = bytearray(JD_SZBUF)  # the COM decoder's stream buffer (static: kept per boot)

    @classmethod
    def from_config(cls, config):
        """A trace case's config (harness/media_store_traces.json)."""
        cover, icon = config["cover"], config["icon"]
        return cls(cover_entries=cover["entries"], cover_slot_bytes=cover["slotBytes"],
                   cover_max_bytes=cover["maxBytes"], icon_entries=icon["entries"],
                   icon_slot_bytes=icon["slotBytes"], icon_bytes=icon["bytes"], chunk_bytes=config["chunkBytes"],
                   have_keys=config["haveKeys"], validate_jpeg=bool(config.get("validateJpeg", False)),
                   available={"cover": cover.get("available", True), "icon": icon.get("available", True)})

    @classmethod
    def from_capability(cls, capability, *, validate_jpeg=False):
        """The knob that advertises `capability` (the artwork2 object)."""
        cover, icon = capability["cover"], capability["icon"]
        available = capability.get("available") is True
        return cls(cover_entries=cover["entries"], cover_slot_bytes=cover["maxBytes"],
                   cover_max_bytes=cover["maxBytes"], icon_entries=icon["entries"], icon_slot_bytes=icon["bytes"],
                   icon_bytes=icon["bytes"], chunk_bytes=capability["chunkBytes"],
                   have_keys=capability["haveKeys"], validate_jpeg=validate_jpeg,
                   available={"cover": available, "icon": available})

    # session and LCD side
    def control(self, ident):
        self.active_id = ident
        self.upload = None

    def release(self):
        self.active_id = None
        self.upload = None

    def frame(self, art_key="", icon_key="", *, adopt=True):
        for kind, key in (("cover", art_key), ("icon", icon_key)):
            valid = isinstance(key, str) and _MEDIA_KEY_RE.fullmatch(key) is not None
            self.stores[kind].frame_key = key if valid else ""
        if adopt:
            for store in self.stores.values():
                store.adopt(store.frame_key)

    def adopt(self, kind, key):
        self.stores[kind].adopt(key or "")

    def receiving(self):
        return self.upload is not None and not self.upload.hit

    def snapshot(self):
        return {"slots": {kind: store.table() for kind, store in self.stores.items()},
                "displayed": {kind: store.displayed for kind, store in self.stores.items()},
                "clock": {kind: store.clock for kind, store in self.stores.items()}}

    # the `media` command
    def media(self, request):
        request = request if isinstance(request, dict) else {}
        ident, op, kind, key = (request.get(name) for name in ("id", "op", "kind", "key"))
        id_ok = type(ident) is int and 1 <= ident <= 0x7FFFFFFF
        op_ok = isinstance(op, str) and op in MEDIA_OPS
        kind_ok = isinstance(kind, str) and kind in presentation.MEDIA_KINDS
        key_ok = isinstance(key, str) and _MEDIA_KEY_RE.fullmatch(key) is not None

        def reply(error=None, offset=0, **fields):
            out = {}
            if id_ok:
                out["id"] = ident
            if op_ok:
                out["op"] = op
            if kind_ok:
                out["kind"] = kind
            if key_ok and op != "have":
                out["key"] = key
            if op != "have":
                out["offset"] = offset
            out.update(fields)
            if error is not None:
                out["error"] = error
                self.errors += 1
            return out

        if not op_ok:
            return reply("Unknown media operation")
        if not kind_ok:
            return reply("Unknown media kind")
        store = self.stores[kind]
        if not store.available:
            return reply("Media unavailable")
        if self.active_id is None or not id_ok or ident != self.active_id:
            return reply("Stale media control")
        if op == "have":
            keys = request.get("keys")
            if (not isinstance(keys, list) or not 1 <= len(keys) <= self.have_keys
                    or not all(isinstance(k, str) and _MEDIA_KEY_RE.fullmatch(k) for k in keys)):
                return reply("Invalid media keys")
            answers = []
            for wanted in keys:
                index = store.find(wanted)
                answers.append(index >= 0)
                if index >= 0:
                    store.touch(index)
            return reply(have=answers)
        if not key_ok:
            return reply("Invalid media key")
        if op == "begin":
            return self._begin(store, kind, key, request, reply)
        if op == "data":
            return self._data(store, kind, key, request, reply)
        return self._commit(store, kind, key, reply)

    def _begin(self, store, kind, key, request, reply):
        size, crc = request.get("bytes"), request.get("crc32")
        if not (_uint32(size) and _uint32(crc)):
            return reply("Media size and CRC required")
        if (not (1 <= size <= self.cover_max_bytes if kind == "cover" else size == self.icon_bytes)
                or size > self.slot_bytes[kind]):
            return reply("Invalid media size")
        index = store.find(key)
        if index >= 0 and store.slots[index].bytes == size and store.slots[index].crc == crc:
            self.upload = MediaUpload(kind, key, size, crc, index, size, True)  # hit: cancels any other
            store.touch(index)
            return reply(offset=size)
        self.upload = None  # a miss cancels any upload too
        victim = store.victim()
        if victim < 0:
            return reply("Media unavailable")
        if store.slots[victim].valid:
            self.evictions += 1
        store.slots[victim].valid = False  # eviction happens at begin
        self.upload = MediaUpload(kind, key, size, crc, victim, 0, False)
        return reply(offset=0)

    def _data(self, store, kind, key, request, reply):
        upload = self.upload
        if upload is None or upload.hit or upload.kind != kind or upload.key != key:
            return reply("No matching media upload")
        chunk = decode_chunk(request.get("data"), self.chunk_bytes)
        if chunk is None:
            return reply("Invalid media data", upload.received)
        offset = request.get("offset")
        if not _json_int(offset) or offset + len(chunk) > upload.bytes:
            return reply("Media chunk bounds", upload.received)
        slot = store.slots[upload.slot]
        if offset == upload.received:
            slot.data[offset:offset + len(chunk)] = chunk
            upload.running = zlib.crc32(chunk, upload.running)
            upload.received += len(chunk)
            upload.last_offset, upload.last_length = offset, len(chunk)
        elif not (offset >= 0 and upload.last_length and offset == upload.last_offset
                  and offset + len(chunk) == upload.received
                  and bytes(slot.data[offset:offset + len(chunk)]) == chunk):
            return reply("Media offset mismatch", upload.received)  # a negative offset too
        return reply(offset=upload.received)  # an identical retry changes nothing

    def _commit(self, store, kind, key, reply):
        upload = self.upload
        if upload is None or upload.kind != kind or upload.key != key:
            return reply("No matching media upload")
        if upload.hit:
            self.upload = None
            self.commits += 1
            return reply(offset=upload.bytes)
        if upload.received != upload.bytes:
            return reply("Media upload incomplete", upload.received)
        slot = store.slots[upload.slot]
        if upload.running & UINT32 != upload.crc:
            self.upload = None
            return reply("Media checksum mismatch", upload.received)
        if (kind == "cover" and self.validate_jpeg
                and not jpeg_baseline_240(slot.data[:upload.bytes], self.jpeg_inbuf)):
            self.upload = None
            return reply("Media decode failed", upload.received)
        for index, other in enumerate(store.slots):
            if index != upload.slot and other.valid and other.key == key:
                other.valid = False
        slot.valid, slot.key, slot.bytes, slot.crc = True, key, upload.bytes, upload.crc
        store.touch(upload.slot)
        self.media_version += 1
        self.commits += 1
        self.upload = None
        if key == store.frame_key:
            store.adopt(key)  # the frame named it before it arrived
        return reply(offset=upload.bytes)


def run_media_trace(case):
    """Replay one media_store_traces.json case through MediaStoreModel (the reference runner).

    Yields (step index, step, actual) for every `media` step (actual: the mediaAck
    object) and `check` step (actual: the snapshot parts the step names: slots,
    displayed and clock per kind, and `receiving`, whether an upload that is not a
    begin hit is in progress).
    """
    model = MediaStoreModel.from_config(case["config"])
    for index, step in enumerate(case["steps"]):
        action = step["do"]
        if action == "control":
            model.control(step["id"])
        elif action == "release":
            model.release()
        elif action == "frame":
            model.frame(step.get("artKey", ""), step.get("iconKey", ""), adopt=not step.get("noAdopt", False))
        elif action == "adopt":
            model.adopt(step["kind"], step["key"])
        elif action == "media":
            yield index, step, model.media(deepcopy(step["req"]))
        elif action == "check":
            snapshot = model.snapshot()
            actual = {}
            for part in ("slots", "displayed", "clock"):
                if part in step:
                    actual[part] = {kind: snapshot[part][kind] for kind in step[part]}
            if "receiving" in step:
                actual["receiving"] = model.receiving()
            yield index, step, actual
        else:
            raise ValueError(f"unknown trace step {action!r}")


_SCAN_KEY_CHARS = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")


def scan_member(line, limit, name):
    """cc_media_scan_member (and com_thread.cpp scan_member): the position just after the first
    `"name"` followed by optional spaces and ':' (then optional spaces) within `limit`, else 0."""
    size = len(name)
    i = 0
    while i + size + 2 < limit:
        if line[i] != 0x22 or line[i + 1:i + 1 + size] != name or line[i + size + 1] != 0x22:
            i += 1
            continue
        j = i + size + 2
        while j < limit and line[j] == 0x20:
            j += 1
        if j >= limit or line[j] != 0x3A:
            i += 1
            continue
        j += 1
        while j < limit and line[j] == 0x20:
            j += 1
        return j if j < limit else 0
    return 0


def prefix_scan(raw, key_chars):
    """The firmware's parse-reply scan (cc_media_parse_ack; art_parse_reply with 64 key chars).

    Only the first 192 bytes, and only the first `"id":` and the first `"key":` member: each
    is reported when that member is intact (id a delimited integer 1..0x7FFFFFFF of at most
    ten digits with no leading zero; key 1..key_chars key characters with its closing
    quote), and omitted otherwise, never taken from a later member.
    """
    raw = bytes(raw)
    limit = min(len(raw), SCAN_BYTES)
    found = {}
    at = scan_member(raw, limit, b"id")
    if at:
        digits = 0
        while at + digits < limit and digits < 11 and 0x30 <= raw[at + digits] <= 0x39:
            digits += 1
        following = raw[at + digits] if at + digits < limit else 0
        if digits and digits <= 10 and following in b",} " and raw[at] != 0x30:
            value = int(raw[at:at + digits])
            if 1 <= value <= 0x7FFFFFFF:
                found["id"] = value
    at = scan_member(raw, limit, b"key")
    if at and raw[at] == 0x22:
        n = 0
        while at + 1 + n < limit and n <= key_chars and raw[at + 1 + n] in _SCAN_KEY_CHARS:
            n += 1
        if 1 <= n <= key_chars and at + 1 + n < limit and raw[at + 1 + n] == 0x22:
            found["key"] = raw[at + 1:at + 1 + n].decode("ascii")
    return found


def _command_prefix(raw, name):
    return raw.lstrip(b" \t\r").startswith(b'{"' + name + b'"')


class CdcModel:
    """Byte-level model of the knob's CDC receive path and COM thread (ARTWORK2.md sections 3 and 10).

    Host writes land in the receive queue (`capacity` bytes: cc5.3's 8192); bytes
    that do not fit are dropped, as USBCDC's receive callback drops them, so their
    line reaches the parser damaged (a JSON parse error, or two lines glued). The
    COM thread wakes on FreeRTOS ticks: a pass drains up to `drain_budget` bytes
    (kDrainBudget), handles every complete line, then sleeps `active_ticks` while a
    partial line is pending, bytes are queued, a media upload is receiving or a
    line was handled less than 20 ms ago, else `idle_ticks`. No pass runs during a
    stall (stall(), or seeded random ones: {"gap": (s, s), "duration": (s, s),
    "seed": n}). The line buffer holds 4096 bytes before the newline: a longer line
    gets one oversize reply and is discarded through its newline. A partial line
    idle for 2000 ms is dropped.
    """

    def __init__(self, *, capacity=8192, tick=0.001, active_ticks=1, idle_ticks=10, drain_budget=2 * (4096 + 1),
                 line_capacity=4096, recent=0.020, abandon=2.0, random_stalls=None):
        self.capacity, self.tick = capacity, tick
        self.active_ticks, self.idle_ticks = active_ticks, idle_ticks
        self.drain_budget, self.line_capacity = drain_budget, line_capacity
        self.recent, self.abandon = recent, abandon
        self.queue = bytearray()
        self.line = bytearray()
        self.oversize = False
        self.last_byte = self.last_line = self.next_wake = None
        self.dropped_bytes = self.damaged_writes = self.high_water = 0
        self.passes = self.lines = 0
        self.stalls = []          # [(start, end)] still to come
        self.stall_log = []       # every stall that delayed a pass: (start, end)
        self._random = random.Random(random_stalls["seed"]) if random_stalls else None
        self._random_spec = random_stalls
        self._random_from = None

    def stall(self, start, duration):
        self.stalls.append((start, start + duration))
        self.stalls.sort()

    def pending(self):
        return bool(self.queue) or bool(self.line) or self.oversize

    def _stall_end(self, t):
        if self._random is not None:
            if self._random_from is None:
                self._random_from = t
            while self._random_from <= t + 1.0:
                start = self._random_from + self._random.uniform(*self._random_spec["gap"])
                end = start + self._random.uniform(*self._random_spec["duration"])
                self.stalls.append((start, end))
                self._random_from = end
            self.stalls.sort()
        while self.stalls and self.stalls[0][1] <= t:
            self.stalls.pop(0)
        for start, end in self.stalls:
            if start > t:
                break
            if start <= t < end:
                if not self.stall_log or self.stall_log[-1] != (start, end):
                    self.stall_log.append((start, end))
                return end
        return None

    def receive(self, data, now):
        if self.next_wake is None:
            self.next_wake = now
        take = min(self.capacity - len(self.queue), len(data))
        self.queue += data[:take]
        if take < len(data):
            self.dropped_bytes += len(data) - take
            self.damaged_writes += 1
        self.high_water = max(self.high_water, len(self.queue))

    def run(self, now, knob):
        """Every COM pass due up to `now`."""
        if self.next_wake is None:
            self.next_wake = now
        while self.next_wake <= now:
            t = self.next_wake
            end = self._stall_end(t)
            if end is not None:
                self.next_wake = end
                continue
            self._pass(t, knob)

    def _pass(self, t, knob):
        self.passes += 1
        if self.queue:
            take = min(self.drain_budget, len(self.queue))
            data = bytes(self.queue[:take])
            del self.queue[:take]
            self.last_byte = t
            start = 0
            while start < len(data):
                newline = data.find(b"\n", start)
                end = newline if newline >= 0 else len(data)
                if not self.oversize:
                    room = self.line_capacity - len(self.line)
                    if end - start > room:
                        self.line += data[start:start + room]
                        knob.cdc_oversize(bytes(self.line), t)  # exactly one reply
                        self.oversize = True
                    else:
                        self.line += data[start:end]
                if newline < 0:
                    break
                if self.oversize:
                    self.oversize = False
                else:
                    self.lines += 1
                    self.last_line = t
                    knob.cdc_line(bytes(self.line), t)
                self.line.clear()
                start = newline + 1
        if (self.line or self.oversize) and t - self.last_byte >= self.abandon:
            self.line.clear()
            self.oversize = False
        knob.cdc_idle(t)
        busy = (bool(self.line) or self.oversize or bool(self.queue) or knob.media_receiving()
                or (self.last_line is not None and t - self.last_line < self.recent))
        self.next_wake = t + (self.active_ticks if busy else self.idle_ticks) * self.tick


class FakeKnob:
    """In-memory serial port of a Nano_D++ knob (cc5.4, cc5.3, cc5 or cc4 capabilities).

    Assembles lines like the firmware COM thread, records each through the
    Recorder, answers inventory/capabilities/control/release/art/media like the
    firmware, and refuses what the firmware would refuse: a stale frame id, a
    control id that does not advance, a line over the 4096-byte buffer, or a
    line that does not start with a JSON object. Like the firmware's
    deserializeJson, only a line's first JSON value is read: whatever follows it
    (a glued next line whose newline was lost) is dropped without a reply.
    Refusals are error replies (the bridge disconnects on them) and are kept in
    `refusals`.

    With `artwork2` in the capabilities the knob keeps the section 4.4 media store
    (`media`, a MediaStoreModel; covers must pass jpeg_baseline_240 when
    `validate_jpeg`). With `cdc` (a CdcModel) every written byte goes through the
    receive-queue model and lines are handled on COM passes as time advances;
    otherwise (the cc5/cc4 sessions) each line is handled as it is written.
    `lease` models the 2000 ms lease (renewed by accepted controls and frames).

    Presentation 5 (cc5.4, PRESENTATION_V5.md section 11): `ready` carries `ks`, the raw mask of the
    buttons physically down when the ready line is built (11.1, 11.3: `held`, which press(), down()
    and up() keep; a Back taken by a held press re-enters with that button still down); a press of
    the control's `windowsButton` that also sends F24 (the 11.4 icon gate: HID enabled, that slot
    enabled with icon `win`) carries `hid:1`; long_press() sends the 600 ms long press of a raw
    button that is still down as `kh` between its `kd` and `ku` (11.2). limit() sends an end-stop
    push (`lim`, ALIVE.md 3). With the `diag` capability the knob answers `{"diag":"?"}` read-only
    at any time (12.3); the v5 fields only on presentation 5. Knob input sent is counted in `sent`;
    every presentation-5 `ready` sent with a button down is kept in `ready_ks` as (step, ks).
    """
    timeout = 0.05

    def __init__(self, clock, capabilities, recorder, firmware, *, cdc=None, validate_jpeg=False, lease=False):
        self.clock, self.capabilities, self.recorder, self.firmware = clock, capabilities, recorder, firmware
        self.buffer = bytearray()
        self.partial = b""
        self.control_id = 0
        self.position = 0
        self.claimed = False
        self.art_total = 0
        self.art_cache = OrderedDict()  # key -> True, cacheEntries LRU (cc_art_store)
        self.refusals = []
        self.idle_reads = 0
        self.closed = False
        self.media = None
        artwork2 = capabilities.get("artwork2")
        if isinstance(artwork2, dict):
            try:
                self.media = MediaStoreModel.from_capability(artwork2, validate_jpeg=validate_jpeg)
            except (KeyError, TypeError):
                self.media = None  # a malformed capability: this knob has no media command
        self.media_acks = Counter()   # replies per op
        self.media_errors = []        # every mediaAck error: {"ack", "step"}
        self.cdc = cdc
        self.processed = []           # cdc: (time, kind, bytes) of every handled line
        self.lease = lease
        self.renewed_at = None
        self.lease_expiries = 0
        self.write_calls = self.whole_line_writes = self.max_write_bytes = 0
        self._host_partial = False
        self._now = None
        level = capabilities.get("presentation", 0)
        self.presentation = level if type(level) is int else 0
        self.control = None           # the last accepted control, and the frame on screen (the F24 gate)
        self.frame = None
        self.control_max = 0
        self.sent = Counter()         # knob input sent: kd, ku, kh, hid, lim, ready, diag
        self.held = 0                 # raw mask of the buttons physically down (HMI keyState): every `ks`
        self.ready_ks = []            # presentation 5: (step, ks) of each ready sent with a button down

    # pyserial surface used by DeviceBridge / PacedSerial
    @property
    def in_waiting(self):
        if self.cdc is not None:
            self._cdc_run()
        return len(self.buffer)

    def read(self, size):
        if self.cdc is not None:
            return self._cdc_read(size)
        if not self.buffer:
            self.idle_reads += 1
            if self.idle_reads > 20:
                self.clock.advance(self.timeout)  # a silent knob: the port timeout elapses
            return b""
        self.idle_reads = 0
        data = bytes(self.buffer[:size])
        del self.buffer[:size]
        return data

    def write(self, data):
        data = bytes(data)
        self.write_calls += 1
        self.max_write_bytes = max(self.max_write_bytes, len(data))
        if data.endswith(b"\n") and data.count(b"\n") == 1 and not self._host_partial:
            self.whole_line_writes += 1
        self._host_partial = not data.endswith(b"\n")
        self.idle_reads = 0
        if self.cdc is not None:
            self._cdc_run()
            self.cdc.receive(data, self.clock())
            return len(data)
        self.partial += data
        while b"\n" in self.partial:
            line, self.partial = self.partial.split(b"\n", 1)
            self._line(line + b"\n")
        self._lease_check(self.clock())
        return len(data)

    def close(self):
        self.closed = True

    # the CDC model's hooks
    def _cdc_run(self):
        self.cdc.run(self.clock(), self)

    def _cdc_read(self, size):
        """A blocking read(size): returns once bytes are there, or after the port timeout."""
        self._cdc_run()
        if not self.buffer:
            deadline = self.clock() + self.timeout
            while not self.buffer and self.cdc.pending() and self.cdc.next_wake <= deadline:
                self.clock.advance(max(0.0, self.cdc.next_wake - self.clock()))
                self._cdc_run()
            if not self.buffer and self.cdc.pending():
                self.clock.advance(max(0.0, deadline - self.clock()))  # stalled: the read times out
                self._cdc_run()
        if not self.buffer:
            self.idle_reads += 1
            if self.idle_reads > 20:
                self.clock.advance(self.timeout)  # nothing is coming: the port timeout elapses
                self._cdc_run()
            if not self.buffer:
                return b""
        self.idle_reads = 0
        data = bytes(self.buffer[:size])
        del self.buffer[:size]
        return data

    def cdc_line(self, raw, t):
        self._now = t
        try:
            self._line(raw + b"\n")
        finally:
            self._now = None

    def cdc_oversize(self, prefix, t):
        self._now = t
        try:
            self.processed.append((t, "oversize", len(prefix)))
            if not self._parse_reply(prefix):
                self.refuse("Command too large")
        finally:
            self._now = None

    def cdc_idle(self, t):
        self._lease_check(t)

    def media_receiving(self):
        return self.media is not None and self.media.receiving()

    def _time(self):
        return self._now if self._now is not None else self.clock()

    # knob side
    def inject(self, message):
        self.buffer.extend((json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8"))

    def refuse(self, why, record=None):
        self.refusals.append({"why": why, "n": record and record["n"], "step": self.recorder.step})
        self.inject({"error": why})

    def turn_to(self, position):
        # The motor holds the knob inside the control's bounds (min is always 0 from this host).
        self.position = max(0, min(position, self.control_max)) if self.control is not None else position
        self.inject({"id": self.control_id, "p": self.position})

    def _f24(self, raw):
        """PRESENTATION_V5.md 11.4: this press also sends F24 (the icon gate of cc5.4)."""
        control = self.control or {}
        if not control.get("windowsHidEnabled", True) or raw != control.get("windowsButton"):
            return False
        order = control.get("buttonOrder", [0, 1, 2, 3])
        buttons = (self.frame or {}).get("buttons") or []
        slot = order.index(raw) if raw in order else -1
        button = buttons[slot] if 0 <= slot < len(buttons) else {}
        return bool(button.get("enabled")) and button.get("icon") == "win"

    def press(self, raw):
        """A short press: its down and up edges together (nothing is ready in between)."""
        down = {"id": self.control_id, "kd": raw, "ks": self.held | 1 << raw}
        if self.presentation >= presentation.PRESENTATION_V5 and self._f24(raw):
            down["hid"] = 1
            self.sent["hid"] += 1
        self.inject(down)
        self.inject({"id": self.control_id, "ku": raw, "ks": self.held & ~(1 << raw)})
        self.held &= ~(1 << raw)
        self.sent["kd"] += 1
        self.sent["ku"] += 1

    def down(self, raw):
        """The down edge of a press that is held (Session.hold()): the button stays down until up()."""
        self.held |= 1 << raw
        self.inject({"id": self.control_id, "kd": raw, "ks": self.held})
        self.sent["kd"] += 1

    def long_press(self, raw):
        """K1 11.2: the 600 ms long press of the raw button still down, tagged with the control that is
        ready now; when the press re-entered the knob, this is the `kh` sent right after the new
        `ready` (step 5: only while that raw's bit is still set in keyState). Presentation 5 only."""
        if self.presentation >= presentation.PRESENTATION_V5 and self.held & (1 << raw):
            self.inject({"id": self.control_id, "ks": self.held, "kh": raw})
            self.sent["kh"] += 1

    def up(self, raw):
        self.held &= ~(1 << raw)
        self.inject({"id": self.control_id, "ku": raw, "ks": self.held})
        self.sent["ku"] += 1

    def limit(self, direction):
        """An end-stop push of the ready control (ALIVE.md 3): alive knobs only."""
        if isinstance(self.capabilities.get("alive"), dict):
            self.inject({"id": self.control_id, "lim": direction})
            self.sent["lim"] += 1

    def diag(self):
        """The `{"diag":{...}}` object (control_center.cpp; P4 section 1, PRESENTATION_V5.md 12.3)."""
        diag = {"lvglFree": 38000, "lvglMinFree": 31000, "heapMinFree": 79000, "heapFree": 90000,
                "stackLcd": 6700, "stackCom": 3100, "stackHmi": 2900, "lcdAgeMs": 4,
                "sessionPhase": "ready" if self.claimed else "idle"}
        if self.media is not None:
            diag.update(jpegDecodes=self.media.commits, jpegDecodeErrors=0, jpegDecodeMsMax=151, jpegDecodeMsLast=88)
        if self.presentation >= presentation.PRESENTATION_V5:
            diag.update(enterMsLast=84, enterMsMax=131, holdEvents=self.sent["kh"], holdDeferred=0,
                        lcdFps=60, lcdFpsAnimMin=57, lcdDma=True, lcdPeriodMs=16, artAsync=True, stackArtDec=2500,
                        ledFps=60, ledRenderUsMax=1450, ledRenderUsAvg=610, ledMode="alive")
        return diag

    def _lease_check(self, t):
        if (self.lease and self.claimed and self.renewed_at is not None
                and t - self.renewed_at > self.capabilities.get("leaseMs", 2000) / 1000.0):
            self.claimed = False
            self.lease_expiries += 1
            if self.media is not None:
                self.media.release()
            self.inject({"released": True, "reason": "lease-expired"})

    def _parse_reply(self, raw):
        """The art/media `parse` reply for a damaged or oversize art/media line (else False).

        Since cc5.3 an art-capable knob (the p4/cc5 session too) answers a damaged or
        oversize `art` line with the artAck parse reply, as the cc5.2 and cc5.3 firmware
        does (com_thread.cpp: contract section 7); before, this FakeKnob refused it with a
        bare JSON parse error / Command too large. An intentional v1 fidelity fix: no v1
        capture or test sends such a line, and a knob without `artwork` still refuses it.
        """
        if self.media is not None and _command_prefix(raw, b"media"):
            # cc_media_parse_ack's key order (ARTWORK2.md 4.3 step 1): op, error, then id and key.
            ack = {"op": "parse", "error": "parse", **prefix_scan(raw, 24)}
            self.media_acks["parse"] += 1
            self.media_errors.append({"ack": ack, "step": self.recorder.step})
            self.inject({"mediaAck": ack})
            return True
        if "artwork" in self.capabilities and _command_prefix(raw, b"art"):
            self.inject({"artAck": {**prefix_scan(raw, 64), "op": "parse", "error": "parse"}})
            return True
        return False

    def _frame_keys(self, frame):
        """A frame (or a control's frame) was accepted: the stores' frameKey, then adoption.

        As cc_parse_frame: iconKey counts only on the windows layout (the frame's `layout`, or
        the one its `mode` implies when `layout` is absent, nowPlaying by default); on any
        other layout the icon frame key is "" whatever the frame carries.
        """
        if self.media is None or not isinstance(frame, dict):
            return
        art, icon = frame.get("artKey", ""), frame.get("iconKey", "")
        art = art if isinstance(art, str) and _ART_KEY_RE.fullmatch(art) else ""
        layout = (frame["layout"] if "layout" in frame
                  else presentation.LEGACY_LAYOUT.get(frame.get("mode"), "nowPlaying"))
        icon = icon if layout == "windows" and isinstance(icon, str) and _ICON_KEY_RE.fullmatch(icon) else ""
        self.media.frame(art, icon)

    def _line(self, raw):
        now = self._time()
        try:
            # ArduinoJson 7's deserializeJson (com_thread.cpp handleLine): leading whitespace, then
            # the first JSON value; anything after it on the line is ignored, not an error. So a
            # line glued to the next one (its newline lost) is handled as its first command alone.
            text = raw.decode("utf-8")
            message, _end = _JSON_FIRST_VALUE.raw_decode(text, len(text) - len(text.lstrip(" \t\r\n")))
        except (UnicodeDecodeError, ValueError):
            self.recorder.record(raw, {})
            if self.cdc is not None:
                self.processed.append((now, "unparsed", len(raw)))
            if not self._parse_reply(raw[:-1]):
                self.refuse("JSON parse error")
            return
        if not isinstance(message, dict):
            self.recorder.record(raw, {})
            self.refuse("JSON parse error")
            return
        record = self.recorder.record(raw, message)
        if self.cdc is not None:
            self.processed.append((now, record["kind"], len(raw)))
        if len(raw) > LINE_LIMIT:
            if not self._parse_reply(raw[:-1]):
                self.refuse("Command too large", record)
            return
        if message == {"profiles": "#all"}:
            self.inject({"profiles": list(KNOB_PROFILES), "current": next(iter(KNOB_PROFILES))})
        elif isinstance(message.get("profile"), str):
            self.inject({"profile": KNOB_PROFILES[message["profile"]]})
        elif message == {"settings": "?"}:
            self.inject({"settings": {"serialNumber": "CAPTURE", "firmwareVersion": self.firmware,
                                      "deviceName": "Nano_D++", "deviceOrientation": 0, "ledMaxBrightness": 51}})
        elif message == {"capabilities": "?"}:
            self.inject({"capabilities": deepcopy(self.capabilities)})
        elif "control" in message:
            control = message["control"]
            if self.claimed and control["id"] <= self.control_id:
                self.refuse("Control ID must advance; wait for release before reconnecting", record)
                return
            self.control_id, self.position, self.claimed = control["id"], control["position"], True
            self.control, self.frame, self.control_max = control, control.get("frame"), control.get("max", 0)
            self.renewed_at = now
            if self.media is not None:
                self.media.control(control["id"])
                self._frame_keys(control.get("frame"))
            ready = {"ready": control["id"], "p": control["position"]}
            if self.presentation >= presentation.PRESENTATION_V5:
                ready["ks"] = self.held            # 11.1/11.3: the buttons down as the ready line is built
                if self.held:
                    self.ready_ks.append((self.recorder.step, self.held))
            self.inject(ready)
            self.sent["ready"] += 1
        elif "frame" in message:
            if not self.claimed or message["frame"].get("id") != self.control_id:
                self.refuse("Stale control frame", record)
                return
            self.renewed_at = now
            self.frame = message["frame"]
            self._frame_keys(message["frame"])
        elif message == {"diag": "?"} and self.capabilities.get("diag") == 1:
            self.sent["diag"] += 1                 # read-only: never renews the lease (12.3)
            self.inject({"diag": self.diag()})
        elif message.get("release") is True:
            self.claimed = False
            self.control = None
            if self.media is not None:
                self.media.release()
            self.inject({"released": True})
        elif "art" in message:
            self._art(message["art"], record)
        elif "media" in message:
            self._media(message["media"], record)
        else:
            self.refuse("Unknown command", record)

    def _art(self, art, record):
        if "artwork" not in self.capabilities:
            self.refuse("JSON parse error", record)  # cc4 has no art store
            return
        ack = {"id": art["id"], "key": art["key"], "op": art["op"]}
        if art["op"] == "begin":
            self.art_total = art["bytes"]
            cached = art["key"] in self.art_cache
            if cached:
                self.art_cache.move_to_end(art["key"])
            ack["offset"] = self.art_total if cached else 0
        elif art["op"] == "data":
            ack["offset"] = art["offset"] + len(base64.b64decode(art["data"]))
        else:
            self.art_cache[art["key"]] = True
            self.art_cache.move_to_end(art["key"])
            while len(self.art_cache) > self.capabilities["artwork"]["cacheEntries"]:
                self.art_cache.popitem(last=False)
            ack["offset"] = self.art_total
        self.inject({"artAck": ack})

    def _media(self, value, record):
        if self.media is None:
            self.refuse("Unknown command", record)  # cc5.2/cc4: the host must never send one
            return
        ack = self.media.media(value)
        self.media_acks[ack.get("op", "?")] += 1
        if "error" in ack:
            self.media_errors.append({"ack": ack, "step": self.recorder.step})
        self.inject({"mediaAck": ack})


class RecordingBridge(DeviceBridge):
    """The real DeviceBridge; only observes the events it emits."""

    def __init__(self, *args, **kwargs):
        self.emitted = []
        super().__init__(*args, **kwargs)

    def _emit(self, kind, **values):
        self.emitted.append({"kind": kind, **{k: v for k, v in values.items()
                                              if k in ("reason", "error", "message", "media", "hit", "failed",
                                                       "held")}})
        super()._emit(kind, **values)



# ---------------------------------------------------------------------------
# One session.

class Session:
    def __init__(self, name, capabilities, recorder, backup_dir):
        self.name, self.capabilities = name, capabilities
        self.recorder = recorder
        self.clock = recorder.clock
        self.recorder.session = name
        self.recorder.presentation = capabilities.get("presentation", 0)
        self.v5 = self.recorder.presentation >= presentation.PRESENTATION_V5
        self.alive = isinstance(capabilities.get("alive"), dict)
        # artwork2 (cc5.3, cc5.4): the CDC receive-queue model with seeded COM stalls, JPEG-checked
        # covers, the 64-entry artwork cache and real app icons.
        self.artwork2 = isinstance(capabilities.get("artwork2"), dict)
        self.knob = FakeKnob(self.clock, capabilities, recorder, FIRMWARE[name],
                             cdc=CdcModel(random_stalls=A2_STALLS) if self.artwork2 else None,
                             validate_jpeg=self.artwork2)
        self.paced = PacedSerial(self.knob, sleep=lambda _seconds: None)
        self.bridge = RecordingBridge(backup_dir, lambda port: self.paced, request_timeout=1.5,
                                      autostart=False, clock=self.clock, local_minute=lambda: 21 * 60 + 26)
        self.controls = SimControls()
        self.sonos = ScriptedSonos(self.controls, self.clock)
        self.apple = ScriptedAppleMusic(self.controls, clock=self.clock, sleep=self.clock.advance)
        self.windows = ScriptedWindows(self.controls)
        self.stage = FakeStagePresenter(self.controls)
        self.toasts = SimulatedToasts()
        self.artwork = FakeArtwork(presentation.ARTWORK_CACHE_ENTRIES if self.artwork2 else FakeArtwork.CACHE_SIZE)
        self.accents, self.icons = FakeAccents(), FakeIcons(images=self.artwork2)
        self.controller = Controller(clock=self.clock, rng=random.Random(54))
        self.runtime = Runtime(self.controller, self.sonos, self.apple, self.windows, self.bridge,
                               artwork=self.artwork, accents=self.accents, icons=self.icons, stage=self.stage,
                               toasts=self.toasts, motion_probe=lambda: False)
        # What ui._make_runtime applies from settings.json (defaults: targeted colour, artwork on)
        # plus the LED tuning keys (ALIVE.md 3; PRESENTATION_V5.md 7.3): only an alive knob gets them.
        self.runtime.button_order = [0, 1, 2, 3]
        self.runtime.led_style = "color"
        self.runtime.artwork_enabled = True
        self.runtime.set_motion("system")
        self.runtime.apply_led_tuning({"led_drive": 120, "led_dither": True, "led_pink": "#FF285A",
                                       "led_vol_full": True})
        self.bridge_errors = []
        self.holds = []

    # -- bridge worker: one pass of DeviceBridge._run per command, synchronously
    def _bridge_pass(self, command, value):
        b = self.bridge
        try:
            b._dispatch(command, value)
            b._service()
        except Exception as exc:  # as DeviceBridge._run: report, then recover
            self.bridge_errors.append({"step": self.recorder.step, "command": command,
                                       "error": type(exc).__name__, "message": str(exc)})
            b._emit("error", message=str(exc), error=type(exc).__name__)
            if isinstance(exc, (OSError, TimeoutError)) and b.serial is not None:
                try:
                    b._disconnect()
                except Exception:
                    pass

    def pump(self):
        """Run the bridge until it has no command, transfer or unread reply left."""
        b, moved = self.bridge, False
        for _ in range(20000):
            has_command = b._deferred_command is not None or not b.commands.empty()
            knob_busy = bool(self.knob.buffer) or (self.knob.cdc is not None and self.knob.cdc.pending())
            busy = has_command or b._busy() or (b.serial is not None and (knob_busy or b._diag_due()))
            if not busy:
                if b.serial is not None:
                    before = len(self.recorder.records)
                    self._bridge_pass(None, None)  # heartbeat
                    moved = moved or len(self.recorder.records) != before
                return moved
            command, value = b._next_command() if has_command else (None, None)
            self._bridge_pass(command, value)
            moved = True
        raise CaptureError(f"{self.recorder.step}: the bridge never went idle")

    def settle(self):
        for _ in range(400):
            self.runtime.poll()
            moved = self.pump()
            if not (moved or not self.bridge.events.empty() or self.controller.effects
                    or self.artwork.pending() or self.accents.pending() or self.icons.pending()
                    or self.stage.events or self.windows.events):
                return
        raise CaptureError(f"{self.recorder.step}: the session did not settle")

    # -- the lanes (runtime ThreadPoolExecutor stand-ins, run by the script)
    def queued(self, lane):
        """The kinds queued on `lane`, in the order they will run."""
        if lane == "audio":
            return self.runtime.audio_lane.queued()   # section 1.1: one worker, FIFO for idle jobs
        return [Lane.kind(job) for job in getattr(self.runtime, lane).jobs]

    def run(self, lane, kind, patience=3.0, optional=False):
        """Run `lane` in order up to and including the first job of `kind`, letting time pass
        first when that job is not queued yet (a debounce, a timed re-entry). `optional`: no job
        of that kind within the patience is not an error."""
        executor = getattr(self.runtime, lane)
        waited = 0.0
        while kind not in self.queued(lane):
            if waited >= patience:
                if optional:
                    return False
                raise CaptureError(f"{self.recorder.step}: no {kind} job queued ({self.queued(lane)})")
            self.clock.advance(0.05)
            waited += 0.05
            self.settle()
        while executor.jobs:
            done = self.queued(lane)[:1] == [kind]
            executor.run_next()
            self.settle()
            if done:
                return True
        raise CaptureError(f"{self.recorder.step}: the {kind} job never ran")

    def drain(self, lane, limit=200):
        """Run every job queued on `lane` (the lookahead lane's pages, meta and pre-resolutions)."""
        executor = getattr(self.runtime, lane)
        for _ in range(limit):
            if not executor.jobs:
                return
            executor.run_next()
            self.settle()
        raise CaptureError(f"{self.recorder.step}: the {lane} lane never emptied")

    def wait(self, seconds, tick=0.25):
        """Let time pass; the Sonos reads due meanwhile (state polls, queue windows) complete as they would."""
        end = self.clock() + seconds
        while self.clock() < end:
            self.clock.advance(min(tick, end - self.clock()))
            self.settle()
            self.flush_audio()

    # -- script vocabulary
    def step(self, label):
        self.recorder.step = label

    def turn_to(self, position):
        self.knob.turn_to(position)
        self.settle()

    def press(self, raw):
        self.knob.press(raw)
        self.settle()

    def hold(self, parent):
        """Button 1 held for 600 ms (K1 11.2): its press acts first, a Back to `parent` that re-enters
        the knob with the button still down (the new `ready` carries it in `ks`, 11.3), then the
        firmware's `kh` for that ready control, which goes Home (K3 4.2), then the release. Older knobs
        send no `kh`: the press alone is the Back. Each hold is kept in `holds` as the mode the `kh`
        met and the mode after it."""
        self.knob.down(0)
        self.settle()
        self.expect(parent)
        self.knob.long_press(0)
        self.settle()
        self.holds.append({"step": self.recorder.step, "held": parent, "after": self.controller.screen.mode})
        if self.v5:
            self.expect("home")
        self.knob.up(0)
        self.settle()

    def expect(self, mode):
        """The script's own check: the controller reached `mode` (else the script drifted)."""
        if self.controller.screen.mode != mode:
            raise CaptureError(f"{self.recorder.step}: in {self.controller.screen.mode}, expected {mode}")

    def flush_audio(self, kinds=("queue_window", "state")):
        """Run the queued audio reads (queue windows, state polls) while one is at the head."""
        while self.queued("audio")[:1] and self.queued("audio")[0] in kinds and self.runtime.audio.jobs:
            self.runtime.audio.run_next()
            self.settle()

    def limit(self, direction):
        """An end-stop push (ALIVE.md 3 `lim`): alive knobs only."""
        if self.alive:
            self.knob.limit(direction)
            self.settle()

    def win(self):
        """Button 4 on Home: the knob sends F24 (the WM_HOTKEY path that opens the picker) and the
        serial `kd`, which the host drops (`hid:1` on presentation 5; logical 3 on Home otherwise)."""
        self.knob.press(3)
        self.runtime.hotkey()
        self.settle()

    def media_summary(self):
        """Knob-side media and transport figures (the bridge resets its own at release)."""
        knob, cdc = self.knob, self.knob.cdc
        store = knob.media
        return {"acks": dict(knob.media_acks), "errors": [e["ack"].get("error") for e in knob.media_errors],
                "commits": store.commits if store else 0, "evictions": store.evictions if store else 0,
                "cdc": None if cdc is None else {"droppedBytes": cdc.dropped_bytes, "damagedWrites": cdc.damaged_writes,
                                                 "highWater": cdc.high_water, "stalls": len(cdc.stall_log),
                                                 "lines": cdc.lines},
                "writes": {"calls": knob.write_calls, "wholeLines": knob.whole_line_writes,
                           "maxBytes": knob.max_write_bytes}}

    def close(self):
        self.step("shutdown")
        try:
            self.runtime.close()
        finally:
            self.pump()


def script(s):
    """The scripted knob session (identical for every capability set; K3 sections 3-5)."""
    # Startup: inventory, first entry before any Sonos read, then the first read.
    s.step("startup/connect")
    s.bridge.submit("connect", "COM-CAPTURE")
    s.settle()
    s.step("startup/first-sonos-read")
    s.run("audio", "state")
    s.step("home/art-arrival")
    s.settle()
    # Home titles from Sonos: JSON escapes, a combining mark with compatibility forms, over-capacity
    # title and artist (cut at whole code points), then back to row 3 (control characters, an emoji).
    for row in (2, 4, 7, 3):
        s.step(f"home/title-row-{row}")
        with s.sonos._lock:
            s.sonos.P = row
            s.sonos._sync()
        s.wait(1.2)

    # Home volume: pending increase, confirmation, pending decrease, bounds, an external change.
    s.step("home/volume-up-pending")
    for position in (29, 31, 33):
        s.turn_to(position)
    s.step("home/volume-up-confirmed")
    s.run("audio", "volume")
    s.step("home/volume-down-pending")
    for position in (30, 27):
        s.turn_to(position)
    s.run("audio", "volume")
    for label, position in (("amber", 84), ("red", 95), ("maximum", 100), ("minimum", 0), ("odd", 35)):
        s.step(f"home/volume-{label}")
        s.turn_to(position)
        s.run("audio", "volume")
    s.step("home/volume-reveal-ends")
    s.wait(1.6)
    s.step("home/external-volume")
    s.sonos.state["volume"] = 61
    s.wait(1.2)
    s.step("home/external-reveal-ends")
    s.wait(3.0)

    # Home paused -> idle -> playing.
    s.step("home/pause-pending")
    s.press(0)
    s.step("home/paused")
    s.run("audio", "transport")
    s.step("home/paused-idle")
    s.wait(4.2)
    s.step("home/play-pending")
    s.press(0)
    s.step("home/playing")
    s.run("audio", "transport")

    # Tracks (Home 3): neighbour titles, skips over every TRACKS title, a failure, the ends.
    s.step("tracks/enter")
    s.press(2)
    s.run("audio", "queue_window", optional=True)
    s.step("tracks/previous")
    s.turn_to(0)
    s.step("tracks/previous-skip-pending")
    s.press(3)
    s.step("tracks/previous-skip-ok")
    s.run("audio", "transport")
    s.run("audio", "queue_window", optional=True)
    s.step("tracks/next-skip-failed")
    s.turn_to(2)
    s.sonos.fail_transport = "Sonos did not skip"
    s.press(3)
    s.run("audio", "transport")
    for _ in range(6):  # rows 2..8: escaped, control-character, combining-mark, over-capacity titles
        s.step("tracks/next-skip-ok")
        s.turn_to(2)
        s.press(3)
        s.run("audio", "transport")
        s.run("audio", "queue_window", optional=True)
    s.step("tracks/queue-end")
    with s.sonos._lock:
        s.sonos.P = QUEUE_ROWS
        s.sonos._sync()
    s.wait(1.2)
    s.run("audio", "queue_window", optional=True)
    s.turn_to(2)
    s.press(3)  # End of queue: refused, nothing is sent
    s.step("tracks/previous-unavailable")
    with s.sonos._lock:
        s.sonos.P = 6
        s.sonos._sync()
        s.sonos.state["can_previous"] = False
    s.wait(1.2)
    s.run("audio", "queue_window", optional=True)
    s.turn_to(0)
    s.press(3)  # dimmed: its reason and the Head shake
    with s.sonos._lock:
        s.sonos._sync()
    s.wait(1.2)

    # Seek (Tracks 3): the lap ring, a jump, the end stop, the idle exit.
    s.step("seek/enter")
    s.turn_to(1)
    s.press(2)
    s.step("seek/jump")
    s.turn_to(s.knob.position + 6)
    s.run("audio", "seek")
    s.step("seek/end-stop")
    s.turn_to(s.knob.control_max)
    s.run("audio", "seek")
    s.limit(1)
    s.step("seek/idle-exit")
    s.wait(3.2)

    # Up next (Tracks 2): rows, a Like, a refused press on the liked row, the shuffle, Play.
    s.step("upnext/open")
    s.press(1)
    s.expect("upnext")
    s.flush_audio()
    s.drain("lookahead")
    s.drain("library")
    s.step("upnext/rows")
    for _ in range(3):
        s.turn_to(s.knob.position + 1)
    s.drain("lookahead")
    s.step("upnext/like")
    s.press(2)
    s.run("library", "like")
    s.wait(1.0)
    s.step("upnext/liked-refused")
    s.press(2)  # add-only: Unfavourite in Music app
    s.step("upnext/shuffle")
    s.press(1)
    s.run("audio", "shuffle_reorder")
    s.wait(0.3)
    s.flush_audio()
    s.drain("lookahead")
    s.step("upnext/play")
    s.turn_to(s.knob.position + 1)
    s.press(3)
    s.run("audio", "jump")
    s.wait(0.6)
    s.expect("home")
    s.wait(1.6)            # the Shuffle transient runs out (K3 2.4: one global copy slot)

    # A hold goes Home from any mode (K3 4.2; K1 11.2), held in Seek so that it is not a Back to Home:
    # the press is Seek's Back to Tracks (K3 4.1), which re-enters the knob with Button 1 still down
    # (that ready's `ks`, K1 11.3), then the `kh` goes Home. Older knobs send no `kh`: the press alone
    # is the Back, and one more Back reaches Home.
    s.step("hold/seek-home")
    s.press(2)
    s.expect("tracks")
    s.press(2)
    s.expect("seek")
    s.hold("tracks")
    if not s.v5:
        s.press(0)
    s.expect("home")

    # Recently Added (Home 2): the flat list, detents across the 20-entry window, the lookahead
    # page, an unavailable item, Play next with its progress, Play (Home at once).
    s.step("recent/loading")
    s.press(1)
    s.step("recent/page-1")
    s.run("library", "recent")
    s.step("recent/detents")
    for position in (1, 2, 3, 4, 6, 8, 9, 12, 16, 21, 24):
        s.turn_to(position)
    s.step("recent/lookahead-page")
    s.drain("lookahead")
    for position in (26, 30, 33, 43, 11):
        s.turn_to(position)
    s.step("recent/unavailable")
    s.turn_to(5)
    s.press(3)  # dimmed: Not available
    s.step("recent/play-next")
    s.turn_to(2)
    s.press(2)
    s.run("library", "resolve", optional=True)
    s.run("audio", "play_next")
    s.wait(1.6)
    s.step("recent/play")
    s.turn_to(3)
    s.press(3)
    s.run("library", "resolve", optional=True)
    s.run("audio", "play_items")
    s.wait(0.5)

    # Starts that fail: a staging failure, then a blocked album (K3 9.10).
    for label, outcome in (("recent/play-failed", "fail"), ("recent/album-blocked", "blocked")):
        s.step(label)
        s.controls.start = outcome
        s.press(1)
        s.run("library", "recent")
        s.turn_to(7)
        s.press(3)
        s.run("library", "resolve", optional=True)
        s.run("audio", "play_items", optional=True)
        s.wait(0.5)
        s.controls.start = "ok"
        s.wait(2.6)

    # The Music explorer (Recent 2): the recent tab, the Favourite playlists tab, Play at 380 ms.
    s.step("explorer/open")
    s.press(1)
    s.run("library", "recent")
    s.turn_to(2)
    s.press(1)
    s.drain("lookahead")
    s.step("explorer/favourites")
    s.press(2)
    s.wait(0.25)
    s.run("library", "favourite_playlists", optional=True)
    s.drain("lookahead")
    s.turn_to(1)
    s.step("explorer/recent-tab")
    s.press(1)
    s.wait(0.25)
    s.step("explorer/play")
    s.press(3)
    s.wait(0.4)
    s.run("library", "resolve", optional=True)
    s.run("audio", "play_items", optional=True)
    s.wait(0.5)

    # Windows (Home 4, F24): 24 windows (some closed), detents across the 20-entry window, a snap
    # pair, a refused and a failed Switch, Back with one side (U12), Switch, an empty picker.
    s.step("windows/open")
    s.win()
    s.step("windows/detents")
    for position in (2, 3, 9, 10, 12, 17, 22, 23, 11):
        s.turn_to(position)
    s.step("windows/switch-closed")
    s.turn_to(3)
    s.press(3)  # closed: its reason, nothing is sent
    s.step("windows/switch-failed")
    s.turn_to(5)
    s.windows.activate_result = False
    s.press(3)
    s.windows.activate_result = True
    s.wait(0.3)
    s.step("windows/snap-pair")
    s.turn_to(1)
    s.wait(0.2)            # a detent since the press would cancel the advance (C5-10)
    s.press(1)
    s.wait(0.5)            # the highlight advances at 420 ms
    s.press(2)
    s.wait(1.0)            # the pair closes at 820 ms
    s.expect("home")
    s.step("windows/back-one-side")
    s.win()
    s.expect("windows")
    s.turn_to(4)
    s.wait(0.2)
    s.press(1)
    s.wait(0.5)
    s.press(0)             # Back with one side assigned: the origin completes the pair (U12)
    s.wait(0.5)
    s.expect("home")
    s.step("windows/switch-ok")
    s.win()
    s.turn_to(12)
    s.press(3)
    s.wait(0.5)
    s.expect("home")
    s.step("windows/empty")
    s.windows.empty_next = True
    s.win()
    s.expect("windows")
    s.press(0)
    s.expect("home")

    # White LED style: the same screens without accents.
    s.step("white/home")
    s.runtime.led_style = "white"
    s.settle()
    s.turn_to(40)
    s.run("audio", "volume")
    s.step("white/recent")
    s.press(1)
    s.run("library", "recent")
    for position in (3, 5, 10):
        s.turn_to(position)
    s.press(0)
    s.step("white/windows")
    s.win()
    for position in (15, 3):
        s.turn_to(position)
    s.press(0)
    s.runtime.led_style = "color"
    s.settle()

    # Reduced motion (VOC-R09): the latched field of presentation 5.
    s.step("motion/reduced")
    s.runtime.set_motion("reduced")
    s.settle()
    s.press(2)
    s.press(0)
    s.runtime.set_motion("system")
    s.settle()

    # Recently Added notices: sign-in expired, a library error, an empty library.
    for label, change in (("recent/sign-in-expired", "expired"), ("recent/error", "error"),
                          ("recent/empty", "empty")):
        s.step(label)
        if change == "expired":
            s.apple.expired = True
        else:
            s.controls.recent = change
        s.press(1)
        s.run("library", "recent")
        s.press(3)  # dimmed or ignored
        s.press(0)
        s.apple.expired = False
        s.controls.recent = "normal"

    # Home with Sonos down (notice), then back.
    s.step("home/sonos-down")
    s.sonos.fail = True
    s.wait(1.2)
    s.sonos.fail = False
    s.step("home/sonos-back")
    s.wait(1.2)

    # The runtime's once-a-minute diag (K3 6.5; PRESENTATION_V5.md 12.3): read-only.
    s.step("diag/once-a-minute")
    s.clock.advance(61.0)
    s.settle()
    s.wait(0.5)

    # Release the knob.
    s.step("release")
    s.bridge.submit("disconnect")
    s.settle()


# ---------------------------------------------------------------------------

def _frame_of(record):
    message = json.loads(record["line"])
    return message["frame"] if record["kind"] == "frame" else message["control"]["frame"]


def summarize(records, sessions):
    """Counts and coverage per session (what the test asserts and the CLI prints)."""
    summary = {}
    for name, info in sessions.items():
        mine = [r for r in records if r["session"] == name]
        frames = [r for r in mine if r["kind"] in ("frame", "control")]
        decoded = [_frame_of(r) for r in frames]
        rings = [f["ring"] for f in decoded]
        buttons = [b for f in decoded for b in f["buttons"]]
        feedback = [f["feedback"] for f in decoded if "feedback" in f]
        summary[name] = {
            "presentation": info["capabilities"].get("presentation"),
            "lines": len(mine),
            "kinds": dict(Counter(r["kind"] for r in mine)),
            "maxLineBytes": max((r["bytes"] for r in mine), default=0),
            "maxFrameLineBytes": max((r["bytes"] for r in mine if r["kind"] == "frame"), default=0),
            "maxControlLineBytes": max((r["bytes"] for r in mine if r["kind"] == "control"), default=0),
            "artOps": dict(Counter(r["op"] for r in mine if r["kind"] == "art")),
            "mediaOps": dict(Counter(r["op"] for r in mine if r["kind"] == "media")),
            "iconKeys": len({f["iconKey"] for f in decoded if f.get("iconKey")}),
            "steps": len({r["step"] for r in mine}),
            "layouts": sorted({f.get("layout", "") for f in decoded}),
            "activities": sorted({f.get("activity", "idle") for f in decoded}),
            "ringStyles": sorted({ring["style"] for ring in rings}),
            "ledStyles": sorted({f.get("ledStyle", "") for f in decoded}),
            "feedback": sorted({fb["kind"] for fb in feedback}),
            "moments": sorted({fb["moment"] for fb in feedback if "moment" in fb}),
            "skips": sorted({fb["skip"] for fb in feedback if "skip" in fb}),
            "icons": sorted({b.get("icon", "") for b in buttons}),
            "lit": sorted({b["lit"] for b in buttons if "lit" in b}),
            "buttonColors": sum(1 for b in buttons if "color" in b and "lit" in b),
            "artKeys": len({f["artKey"] for f in decoded if f.get("artKey")}),
            "artDim": sum(1 for f in decoded if f.get("artDim")),
            "restIdle": sum(1 for f in decoded if f.get("restLayout") == "idle"),
            "pages": sorted({f.get("page", 0) for f in decoded}),
            "withColors": sum(1 for ring in rings if ring.get("colors")),
            "maxColors": max((len(ring.get("colors", ())) for ring in rings), default=0),
            "maxCount": max((ring["count"] for ring in rings), default=0),
            "windowFirst": sorted({ring.get("first", 0) for ring in rings if ring["count"] > 20}),
            "unavailableMasks": sum(1 for ring in rings if ring.get("unavailable")),
            "now": sum(1 for ring in rings if "now" in ring),
            "external": sum(1 for ring in rings if ring.get("external")),
            "latched": sorted({k for f in decoded for k in ("clock", "progress", "ledDrive", "ledDither",
                                                             "reducedMotion", "ledPink", "ledVolFull") if k in f}),
            "reducedMotion": sum(1 for f in decoded if f.get("reducedMotion") is True),
            "playing": sum(1 for f in decoded if "playing" in f),
            "nonAscii": sum(1 for r in frames if any(ord(c) > 0x7E for c in r["line"])),
            "controls": sum(1 for r in frames if r["kind"] == "control"),
            "frames": sum(1 for r in frames if r["kind"] == "frame"),
            "diagLines": sum(1 for r in mine if r["kind"] == "query" and r.get("line") == '{"diag":"?"}'),
            "refusals": info["refusals"],
            "bridgeErrors": info["bridgeErrors"],
            "events": info["events"],
            "knobInput": info["knobInput"],
            "holds": info["holds"],
            "readyKs": info["readyKs"],
            "readyHeld": info["readyHeld"],
            "toasts": info["toasts"],
            "artwork": info["artwork"],
            "media": info["media"],
        }
    return summary


def capture(out_path=None, sessions=tuple(SESSIONS)):
    """Run the scripted session against each capability set; return (records, summary).

    With `out_path`, the records are written there as JSONL (one per line, UTF-8).
    """
    records, info = [], {}
    clock = Clock()
    recorder = Recorder(clock)
    with tempfile.TemporaryDirectory(prefix="nanod-capture-") as backups, \
            patch("control_center.runtime.ThreadPoolExecutor", Lane), \
            patch("control_center.runtime.time", RuntimeTime(clock)):
        for name in sessions:
            session = Session(name, SESSIONS[name], recorder, Path(backups) / name)
            try:
                script(session)
            finally:
                session.close()
            info[name] = {"capabilities": SESSIONS[name], "refusals": session.knob.refusals,
                          "bridgeErrors": session.bridge_errors,
                          "events": dict(Counter(e["kind"] for e in session.bridge.emitted)),
                          "knobInput": dict(session.knob.sent),
                          # K1 11.2/11.3: each hold (the mode its `kh` met, the mode after), each ready
                          # the knob sent with a button down, and the host's `held` mask of those readies.
                          "holds": session.holds,
                          "readyKs": [list(entry) for entry in session.knob.ready_ks],
                          "readyHeld": [e["held"] for e in session.bridge.emitted
                                        if e["kind"] == "ready" and e.get("held")],
                          "toasts": len(session.toasts.shown),
                          "artwork": {"requested": len(session.artwork.requests),
                                      "delivered": session.artwork.delivered, "failed": session.artwork.failed,
                                      "hostHits": session.artwork.hits,
                                      "knobCache": len(session.knob.art_cache),
                                      "prefetched": session.artwork.prefetched},
                          "media": session.media_summary()}
            clock.advance(10.0)
    records = recorder.records
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return records, summarize(records, info)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT, help=f"JSONL output (default {DEFAULT_OUTPUT})")
    args = parser.parse_args()
    records, summary = capture(args.out)
    print(f"{len(records)} line(s) -> {args.out}")
    for name, counts in summary.items():
        print(f"[{name}] " + json.dumps(counts, ensure_ascii=False))
    broken = any(counts["refusals"] or counts["bridgeErrors"] for counts in summary.values())
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
