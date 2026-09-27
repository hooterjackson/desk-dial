"""Pure, deterministic interaction controller for desktop v7 (CONTROL_CENTER_V5.md, K3). No I/O.

The controller owns the knob modes (``home``, ``recent``, ``explorer``, ``tracks``, ``seek``,
``upnext``, ``windows``), the button grammar with its dim reasons and the Head-shake-with-reason
rule (section 3), Back and the firmware hold (section 4), the re-entry helper and its input
blackouts (section 6), every timer of section 7 on the injected clock, the confirmation policy
(section 8), the transient copy slot (section 2.4), the toast service rules (section 12) and the
overlay lifetime (section 13). It talks to the runtime only: effects out (``drain()``), and
``complete``, ``progress``, device calls and presenter events in.

Effects carry ``kind``, ``request``, ``control_id`` and ``view_id`` (section 10.1). Service
effects (Sonos, Apple Music, windows_open / windows_activate) are ``pending`` until their
``complete``; presenter effects (explorer_*, upnext_*, windows_highlight / _snap / _cancel /
_close_pair / _hide, toast) are posted and never completed: the presenters answer with the
section 11.4 events, which all enter through ``presenter_event`` (VOC-R22). The narrow presenter
interface is therefore: effect dicts out (names VOC section 7.4, payloads section 11.1 with
``t0`` on this controller's clock, ``time.perf_counter`` in production), event dicts in::

    {"kind": "opened" | "closed" | "click_action" | "refused" | "system" | "snap_result"
             | "cancel_result",
     "surface": "explorer" | "upnext" | "picker", "reason": ..., "what": lock|sleep|display|motion,
     "side": "left" | "right", "outcome": ..., "restored": bool, "completed": bool}

Every host-driven move is a new control (``_enter``); presses and turns are honoured only for
the current control id and only after its ``ready``. The embedded frame is the post-ready
projection; its ``artKey`` follows the entry art rule of section 6.3 (the runtime's decorator
keeps the previous cover in an entry and sends the new one in the first frame after ``ready``).

alive (firmware/ALIVE.md revision 2): Home frames carry ``playing`` from the confirmed
transport only; it is omitted while a start is pending and on the frame that first carries a
``started`` moment (K2 M16), and held after a start until PLAYING is confirmed
(ALBUM_START_HOLD_SECONDS, every start kind).
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from itertools import count
import logging
import math
import random
import threading
import time

from .presentation import (EXTERNAL_SECONDS, LED_GREEN, LED_RED, LED_WHITE, RING_WINDOW, clean_text,
                           mmss, window_first_v5)
from .queue_context import QueueLedger

_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())  # the application configures the real handlers

# Kept for existing imports (the contract LED palette, not the LCD inks).
WHITE, GREEN, RED = LED_WHITE, LED_GREEN, LED_RED
TONE_COLORS = {"go": LED_GREEN, "stop": LED_RED}
# The retired v6 lookahead page marker (kept so old imports resolve; never set any more).
LOOKAHEAD_PAGE = "lookahead"

MODES = ("home", "recent", "explorer", "tracks", "seek", "upnext", "windows")
OVERLAY_MODES = ("explorer", "upnext", "windows")
PROFILES = {"home": "BINARIS BEER", "recent": "MIDI SKIPPER", "explorer": "MIDI SKIPPER",
            "tracks": "MIDI CLACK JONES", "seek": "BINARIS BEER", "upnext": "MIDI SKIPPER",
            "windows": "MIDI SKIPPER"}
# Legacy `mode` text (presentation < 4 knobs derive a layout from it; v4/v5 knobs ignore it).
MODE_TITLES = {"home": "VOLUME", "recent": "RECENTLY ADDED", "explorer": "RECENTLY ADDED",
               "tracks": "TRACKS", "seek": "TRACKS", "upnext": "TRACKS", "windows": "WINDOWS"}
KIND_LABELS = {"album": "Album", "library-albums": "Album", "song": "Song", "library-songs": "Song",
               "playlist": "Playlist", "library-playlists": "Playlist"}
SOURCES = ("queue", "airplay", "radio", "linein", "none")
SHUFFLE_PLAY_MODES = frozenset(("SHUFFLE", "SHUFFLE_NOREPEAT", "SHUFFLE_REPEAT_ONE"))

# ------------------------------------------------------------------ timers (section 7), seconds
SEEK_STEP_S = 5
SEEK_MARGIN_S = 3
SEEK_MAX_DURATION_S = 59999
SEEK_DEBOUNCE = 0.250
SEEK_IDLE = 3.0
SEEK_FAIL_LINE = 2.2
SEEK_LIMIT_LINE = 1.5
REASON_META = 2.0
SIGNIN_META = 2.2
LIKE_FAIL_META = 2.2
LIKE_LATE_CHECK = 5.0
PREFETCH_RESOLVE_REST = 0.4
FAIL_META = 2.4
QUEUED_META = 1.5
FEEDBACK_META = 1.5
PARTIAL_STATUS = 3.0
START_FAIL_STATUS = 2.6
OVERLAY_PLAY_CLOSE = 0.380
OVERLAY_PLAY_CLOSE_MS = 380
TAB_SWAP = 0.190
SHUFFLE_SWAP = 0.200
SNAP_PLACE_MS = 360
SNAP_ADVANCE = 0.420
SNAP_RESULT_TIMEOUT = 1.0
SNAP_PAIR_CLOSE = 0.820
PASSIVE_QUIET = 0.400
EXIT_TOAST_DELAY = 0.360
OVERLAY_IDLE = 60.0
VOLUME_REVEAL_SECONDS = 1.4
EXTERNAL_REVEAL_SECONDS = 2.6
PAUSED_IDLE_SECONDS = 4.0
STATE_POLL = 1.0
STATE_POLL_BUSY = 2.0
FAVOURITES_STALE = 600.0
FAVOURITES_BACKOFF = (30.0, 120.0)
RECENT_PAGE = 25
RECENT_AHEAD = 16            # >= 16 loaded items ahead (12 preload + 4 in the direction of travel)
RECENT_RETRY = 5.0           # a failed later page is asked again after this long
COMPANION_SHUFFLE_MAX = 60
UPNEXT_WINDOW = 21
UPNEXT_EDGE = 5
PLAY_NEXT_MAX = 100
# alive (ALIVE.md section 3, R4): after any start a non-PLAYING reading omits `playing` until
# PLAYING is confirmed, a Home Play/Pause is pressed, or this long has passed.
ALBUM_START_HOLD_SECONDS = 10.0
FEEDBACK_SEQ_MAX = 0x7FFFFFFF
SKIP_DIRECTIONS = {"previous": -1, "next": 1}
DISCONNECTED_STATUS = "Knob disconnected · reconnect to resume"
# Line limits in px (VOC section 9.1; Montserrat 500): (font size, limit).
LINE_META = (12, 170)
LINE_STATUS = (12, 160)
LINE_14 = (14, 170)
EXPLORER_PRELOAD_BEHIND = 12
EXPLORER_PRELOAD_AHEAD = 16  # +-12 plus 4 in the direction of travel

# ------------------------------------------------------------------ copy (VOC section 9; K3 section 15)
COPY = {
    "knob.heading.recent": "RECENTLY ADDED",
    "knob.heading.explorer_recent": "RECENT",
    "knob.heading.explorer_favourites": "FAVOURITES",
    "knob.heading.upnext": "UP NEXT",
    "knob.heading.tracks": "TRACKS",
    "knob.heading.seek": "SEEK",
    "knob.meta.position": "{i} / {n}",
    "knob.meta.position_end": "{n} / {n} · end",
    "knob.meta.playnext.progress": "Queueing… {k} of {n}",
    "knob.meta.playnext.resolving": "Finding songs…",
    "knob.meta.playnext.ok": "Queued next",
    "knob.meta.playnext.nothing": "Nothing added · retry",
    "knob.meta.playnext.partial": "Partly queued",
    "knob.meta.playnext.song_changed": "Song changed · retry",
    "knob.meta.playnext.airplay": "AirPlay · use Play",
    "knob.meta.playnext.radio": "Radio · use Play",
    "knob.meta.playnext.linein": "Line-in · use Play",
    "knob.meta.playnext.none": "Nothing playing · Play",
    "knob.meta.playnext.shuffle": "Shuffle on · turn it off",
    "knob.meta.loading": "Loading…",
    "knob.title.favourites_empty": "No favourites yet",
    "knob.sub.favourites_empty": "Star one in Music",
    "knob.sub.playlist_count": "{n} songs",
    "knob.meta.tracks.hint": "Press 4 to skip",
    "knob.meta.tracks.position_shuffle": "{i} / {n} · shuffle",
    "knob.meta.tracks.skipping": "Skipping…",
    "knob.meta.upnext.airplay": "Up next is in Music app",
    "knob.meta.upnext.radio": "Radio · no Up next",
    "knob.meta.upnext.linein": "Line-in · no Up next",
    "knob.meta.upnext.none": "Nothing playing",
    "knob.meta.seek.radio": "Can’t seek · radio",
    "knob.meta.seek.airplay": "Can’t seek · AirPlay",
    "knob.meta.seek.linein": "Can’t seek · line-in",
    "knob.meta.seek.none": "Nothing playing",
    "knob.meta.seek.no_length": "Can’t seek · no length",
    "knob.meta.upnext.position_playing": "{i} / {n} · playing",
    "knob.meta.upnext.loading": "Loading queue…",
    "knob.meta.like.on": "Liked",
    "knob.meta.like.unknown": "Checking likes…",
    "knob.meta.like.not_catalog": "Not an Apple Music song",
    "knob.meta.like.signin_expired": "Sign-in expired",
    "knob.meta.like.failed": "Didn’t save · try again",
    "knob.meta.like.unlike_in_music": "Unfavourite in Music app",
    "knob.meta.shuffle.on": "Shuffle on",
    "knob.meta.shuffle.off": "Shuffle off · in order",
    "knob.meta.shuffle.sonos": "Sonos is shuffling",
    "knob.meta.shuffle.queue_changed": "Queue changed",
    "knob.meta.shuffle.failed": "Didn’t shuffle · try again",
    "knob.meta.shuffle.nothing": "Nothing to shuffle",
    "knob.meta.snap.left_set": "Left: {App} · pick right",
    "knob.meta.snap.right_set": "Right: {App} · pick left",
    "knob.meta.snap.hung": "{App} not responding",
    "knob.meta.snap.move": "Couldn’t move {App}",
    "knob.meta.snap.fit": "{App} can’t fit half",
    "knob.meta.windows.switching": "Switching…",
    "knob.meta.windows.no_focus": "Didn’t come forward · retry",
    "knob.meta.windows.closed": "Closed · can’t switch",
    "knob.title.no_windows": "No eligible windows",
    "knob.line.tracks.now": "Now: {title}",
    "knob.line.tracks.next": "Next: {title}",
    "knob.line.tracks.prev": "Prev: {title}",
    "knob.line.tracks.end": "End of queue",
    "knob.line.tracks.start": "Start of queue",
    "knob.line.tracks.next_shuffle": "Next: shuffle pick",
    "knob.line.tracks.prev_shuffle": "Prev: last played",
    "knob.line.tracks.next_wrap": "Next: back to track 1",
    "knob.title.tracks.choose": "Turn to choose",
    "knob.title.tracks.prev": "Previous track",
    "knob.title.tracks.next": "Next track",
    "knob.meta.skip.end": "End of queue",
    "knob.meta.skip.start": "Start of queue",
    "knob.meta.skip.prev_unavailable": "Previous unavailable",
    "knob.meta.skip.next_unavailable": "Next unavailable",
    "knob.line.seek.length": "of {m:ss}",
    "knob.line.seek.jumping": "Jumping…",
    "knob.line.seek.failed": "Didn’t jump · try again",
    "knob.line.seek.limit": "Stops 3 s before end",
    "knob.status.starting": "Starting…",
    "knob.status.pausing": "Pausing…",
    "knob.status.partial": "Playing {k} of {n}",
    "knob.status.start_failed": "Didn’t start",
    "knob.status.album_blocked": "Album unavailable",
    "knob.status.paused": "Paused",
    "knob.status.setting": "Setting…",
    "knob.status.changed_elsewhere": "Changed on Sonos",
    "knob.status.minimum": "Minimum",
    "knob.status.maximum": "Maximum",
    "knob.status.nothing_playing": "Nothing playing",
    "knob.status.sonos_unavailable": "Sonos unavailable",
    "knob.status.group_changed": "Speaker group changed",
    "knob.status.connecting": "Connecting knob",
    "knob.caption.nothing_playing": "Nothing playing",
    "knob.caption.now_playing": "Now playing",
    "knob.caption.volume": "{title}",
    "knob.caption.volume_paused": "Paused · {title}",
    "knob.title.looking_for_sonos": "Looking for Sonos…",
    "knob.title.sonos_unavailable": "Sonos unavailable",
    "knob.sub.looking_for_sonos": "Looking for Sonos…",
    "knob.meta.windows_still_works": "Windows still works",
    "knob.title.recent_empty": "Nothing recently added",
    "knob.sub.recent_empty": "Apple Music library",
    "knob.title.signin_expired": "Apple Music sign-in expired",
    "knob.sub.signin_expired": "Renew on your PC",
    "knob.title.library_error": "Library not loaded",
    "knob.sub.library_error": "Home, then Browse",
    "knob.title.upnext_sonos_card": "Shuffled by Sonos",
    "knob.meta.busy.starting": "Starting…",
    "knob.meta.busy.pausing": "Pausing…",
    "knob.meta.busy.shuffling": "Shuffling…",
    "knob.meta.library_error": "Library not loaded",
    "knob.meta.signin_expired": "Sign-in expired",
    "knob.meta.sonos_unavailable": "Sonos unavailable",
    "knob.meta.item_unavailable": "Not available",
    "knob.meta.group_changed": "Speaker group changed",
    "knob.meta.stage_unavailable": "Couldn’t open on screen",
    "overlay.explorer.untitled": "Untitled playlist",
    "overlay.upnext.shuffle_on": "Shuffle on",
    "overlay.upnext.shuffle_off": "In order",
    "overlay.upnext.shuffle_sonos": "Shuffle on · Sonos picks the order",
    "toast.playnext.ok": "Queued next · {album}",
    "toast.playnext.not_queue": "Not playing from the queue · use Play",
    "toast.playnext.none": "Nothing playing · use Play",
    "toast.playnext.shuffle": "Shuffle is on · turn it off to play next",
    "toast.playnext.nothing": "Couldn’t queue {album} · nothing added",
    "toast.playnext.partial": "Partly queued · check the Sonos queue",
    "toast.playnext.song_changed": "Song changed · try again",
    "toast.start.ok": "Playing {name}",
    "toast.start.partial": "Playing {k} of {n} · {u} songs unavailable",
    "toast.start.partial_one": "Playing {k} of {n} · 1 song unavailable",
    "toast.start.album_blocked": "{album} can’t play · a song is unavailable",
    "toast.start.failed": "Couldn’t start {name}",
    "toast.skip.next": "Next · {title}",
    "toast.skip.prev": "Previous · {title}",
    "toast.switch": "{App} · {Title}",
    "toast.snap.pair": "Side by side · {A} and {B}",
    "toast.snap.one_side": "{A} left · {B} right",
    "toast.like.signin_expired": "Apple Music sign-in expired · open Settings",
}
# Home button labels (the idle-row words, VOC-D08; each <= 46 px at 12 px).
HOME_LABELS = ("Play", "Pause", "Browse", "Tracks", "Win")

_view_ids = count(1)


def copy_text(copy_id, **fields):
    """The text of ``copy_id`` with ``{name}`` placeholders filled (no fitting)."""
    text = COPY[copy_id]
    for name, value in fields.items():
        text = text.replace("{" + name + "}", str(value))
    return text


# ------------------------------------------------------------------ fitting (K3 section 15.1)
_measure_fn = None


def measure(text, size):
    """Width in knob px of ``text`` at ``size`` (the lcd_preview font metrics when available)."""
    global _measure_fn
    if _measure_fn is None:
        try:
            from .lcd_preview import text_width
            _measure_fn = text_width
        except Exception:  # pragma: no cover - the metrics module is optional here
            _measure_fn = False
    if _measure_fn:
        try:
            return _measure_fn(text, size)
        except Exception:
            pass
    return int(round(len(text) * size * 0.58))


_FIT_CACHE = OrderedDict()


def fit_copy(copy_id, line=LINE_META, **fields):
    """``copy_id`` filled and fitted to ``line`` = (size, limit px): placeholder values are
    ellipsized first (longest first, U+2026), measured with the knob's own font metrics."""
    key = (copy_id, line, tuple(sorted((k, str(v)) for k, v in fields.items())))
    hit = _FIT_CACHE.get(key)
    if hit is not None:
        _FIT_CACHE.move_to_end(key)
        return hit
    size, limit = line
    values = {name: clean_text(str(value)) for name, value in fields.items()}
    text = copy_text(copy_id, **values)
    shortened = dict(values)
    guard = 0
    while measure(text, size) > limit and guard < 400:
        guard += 1
        name = max(shortened, key=lambda k: len(shortened[k]), default=None)
        if name is None or not shortened[name].rstrip("…"):
            break
        base = shortened[name].rstrip("…")
        shortened[name] = base[:-1].rstrip() + "…"
        text = copy_text(copy_id, **shortened)
    _FIT_CACHE[key] = text
    if len(_FIT_CACHE) > 1024:
        _FIT_CACHE.popitem(last=False)
    return text


def _clean_frame(frame):
    """Remove control characters from every text field and button label (outside metadata may
    carry newlines or tabs, which the device contract rejects in required fields)."""
    for name, value in frame.items():
        if isinstance(value, str):
            frame[name] = clean_text(value)
    for button in frame.get("buttons") or ():
        if isinstance(button, dict) and isinstance(button.get("label"), str):
            button["label"] = clean_text(button["label"])
    return frame


def _needs_login(lower):
    """An Apple Music sign-in/authorization failure (lower-cased status text)."""
    return "authorization" in lower or "credentials" in lower or "connect apple music" in lower


def _clamp(value, low, high):
    return max(low, min(high, value))


def _int(value, default=0):
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _item_id(item):
    return str(item.get("id", "")) if isinstance(item, dict) else ""


def presenter_event_dict(event):
    """One section 11.4 presenter event as the dict the controller dispatches on, or None.

    K4's stage posts ``(kind, payload)`` tuples (``stage.presenter.Mailbox``); a ``system``
    payload names its own kind (``lock``, ``sleep``, ``display``, ``motion``), which becomes
    ``what`` and never replaces the event kind. The picker and the fakes post dicts, which pass
    through unchanged."""
    if isinstance(event, (tuple, list)) and len(event) == 2 and isinstance(event[0], str):
        kind, payload = event
        if isinstance(payload, dict):
            fields = dict(payload)
        else:
            fields = {} if payload is None else {"value": payload}
        inner = fields.pop("kind", None)
        if kind == "system" and "what" not in fields:
            fields["what"] = inner if inner is not None else fields.get("system", fields.get("value"))
        fields["kind"] = kind
        return fields
    return event if isinstance(event, dict) else None


def _descriptor(item):
    """An item as presenters receive it: the K4 section 13.2 art keys and the list fields; the
    raw Apple ``_resource`` never leaves the controller."""
    if not isinstance(item, dict):
        return None
    return {key: value for key, value in item.items() if not key.startswith("_")}


# ------------------------------------------------------------------ state objects
@dataclass
class RecentList:
    """The flat Recently Added list of one visit (section 5.2.2; shared by recent and the explorer)."""
    visit: int = 0
    apple_visit: int | None = None
    items: list = field(default_factory=list)
    total: int | None = None
    complete: bool = False
    next_offset: int = 0
    inflight: int | None = None
    inflight_lane: str = ""
    state: str = "loading"          # loading | ready | empty | signin | error
    retry_at: float = 0.0
    rev: int = 0

    def count(self):
        if self.state in ("loading", "empty", "signin", "error"):
            return 0
        if self.total is not None and not self.complete:
            return max(self.total, len(self.items))
        return len(self.items)

    def item(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None


@dataclass
class FavouritesList:
    """Favourite playlists (section 9.8.5): session cache, refreshed after 600 s."""
    items: list = field(default_factory=list)
    state: str = "none"             # none | loading | ready | empty | signin | error
    loaded_at: float | None = None
    focus_id: str | None = None
    inflight: int | None = None
    retry_at: float = 0.0
    backoff: int = 0
    meta: dict = field(default_factory=dict)      # playlist id -> playlist_meta result
    meta_inflight: dict = field(default_factory=dict)   # playlist id -> request
    rev: int = 0

    def count(self):
        return len(self.items) if self.state == "ready" else 0


@dataclass
class ExplorerState:
    source: str = "recent"
    index_by_source: dict = field(default_factory=dict)
    swap_until: float = 0.0
    swap_to: str | None = None
    play_until: float = 0.0
    sent: dict = field(default_factory=dict)      # what the last push carried (items window, state, count)


@dataclass
class SeekState:
    D: int = 1
    p0: int = 0
    n0: int = 0
    max: int = 0
    target_s: int = 0
    due: float | None = None
    inflight: int | None = None
    acked_s: int | None = None      # the target of the last jump sent: the one its job read at start
    landed_s: int | None = None     # the target of the jump that last landed in this burst
    fail_until: float = 0.0
    limit_until: float = 0.0
    idle_due: float = 0.0
    track_id: str | None = None
    left: bool = False              # Seek was left; results apply silently (C5-16)
    dropped: bool = False           # a track / group change or a disconnect dropped the target (C5-47)

    def t(self, n):
        return _clamp(self.p0 + SEEK_STEP_S * (n - self.n0), 0, max(0, self.D - SEEK_MARGIN_S))

    @property
    def busy(self):
        return self.inflight is not None or (self.landed_s is not None and self.target_s != self.landed_s)


@dataclass
class UpNextState:
    P: int = 1
    T: int = 0
    card: bool = False
    regime: str = "companion"
    rows: dict = field(default_factory=dict)      # 1-based row -> row dict
    loading: bool = True
    reads: list = field(default_factory=list)     # queued (start, count, purpose)
    read_inflight: int | None = None
    revision: str = ""
    enriched: set = field(default_factory=set)    # song ids asked for (catalog + ratings)
    ratings_failed: set = field(default_factory=set)
    context: dict | None = None
    sent_context: dict | None = None
    swap_until: float = 0.0
    play_until: float = 0.0
    armed_toast: str | None = None
    identity: tuple | None = None                 # focus identity kept across a re-read
    pending_regime: str | None = None             # a Sonos-shuffle regime change waiting for its window


@dataclass
class SnapJob:
    item_id: str
    side: str
    t0: float
    accepted: bool = False
    turned: bool = False


@dataclass
class WindowsState:
    items: list = field(default_factory=list)
    origin: dict | None = None
    left: str | None = None
    right: str | None = None
    desk_open: str | None = None
    snap_busy: SnapJob | None = None
    last_side: str | None = None
    latched_close: str | None = None
    failure: dict | None = None
    switch_request: int | None = None


@dataclass
class StartPending:
    request: int
    kind: str
    name: str
    accent: int
    source: str
    closed_at: float
    item_id: str = ""


@dataclass
class PlayNextJob:
    request: int
    item: dict
    name: str
    accent: int
    k: int = 0
    n: int | None = None
    phase: str = "resolving"


@dataclass
class ShuffleJob:
    request: int
    on: bool
    regime: str
    plan: list = field(default_factory=list)
    playnext_offsets: list = field(default_factory=list)
    accepted: bool = False
    t0: float = 0.0
    record_order: list = None        # [P3] on (companion): the base rows' signatures the record will hold


@dataclass
class TransientCopy:
    copy_id: str
    text: str
    tone: str
    until: float


@dataclass
class Screen:
    """One per mode entry (a new view_id per Screen).

    Compat for v6-era callers (release tooling, previews): ``pages=[page dicts]`` seeds the flat
    Recently Added list when the Screen is assigned to a controller, ``windows=<snapshot dict>``
    becomes a WindowsState and the old mode name ``volume`` means ``home``."""
    mode: str = "home"
    index: int = 0
    parent_index: int | None = None
    status: str = ""
    view_id: int = field(default_factory=lambda: next(_view_ids))
    explorer: ExplorerState | None = None
    seek: SeekState | None = None
    upnext: UpNextState | None = None
    windows: WindowsState | None = None
    recent: RecentList | None = None
    pages: list = field(default_factory=list)

    def __post_init__(self):
        if self.mode == "volume":
            self.mode = "home"
        if isinstance(self.windows, dict):
            snapshot = self.windows
            self.windows = WindowsState(items=[dict(item) for item in snapshot.get("items") or ()],
                                        origin=snapshot.get("origin"))
        self._legacy_pages = list(self.pages) if self.pages else None
        self.pages = []

    @property
    def loading(self):
        """Compat (status.json): the knob list waits for its first page."""
        return bool(self.mode in ("recent", "explorer") and self.recent is not None
                    and self.recent.state == "loading")

    @property
    def page(self):
        return 0


# ------------------------------------------------------------------ the controller
class Controller:
    def __init__(self, clock=time.perf_counter, rng=None):
        self.clock = clock
        self.rng = rng if rng is not None else random.Random()
        self.screen = Screen()
        self.control_id = 0
        self.ready = True
        self.hardware = False
        self.effects = []
        self.pending = {}
        self.serial = 0
        self.state = {"online": False, "volume": 0, "group_label": "Den",
                      "group_revision": "", "title": "", "artist": "",
                      "can_next": False, "can_previous": False,
                      "can_play": False, "can_pause": False, "playback": "UNKNOWN"}
        self.state_known = False
        self._state_at = 0.0
        self._intent_lock = threading.Lock()
        self._volume_intent = (None, "")
        self._seek_lock = threading.Lock()
        self._seek_targets = {}          # seek request -> latest target (read at job start)
        self._seek_read = {}             # seek request -> the target its job read when it started
        self.volume_request = None
        self.volume_due = 0.0
        self.last_volume_write = -10.0
        self._volume_reveal_until = 0.0
        self._volume_reveal_source = ""
        self._external_until = 0.0
        self._paused_since = None
        self._paused_idle_cancelled = False
        self._album_start_until = 0.0
        self.last_poll = -10.0
        self.command_request = None      # the Home play/pause or the Tracks skip that is out
        self.button_order = [0, 1, 2, 3]
        self.windows_hid_enabled = True
        self.notice = ""
        self.decorate = None
        self.accent_lookup = None        # runtime hook: (kind, item) -> 0xRRGGBB (section 10.4)
        self.feedback = None
        self.feedback_seq = 0
        self._started_seq = None         # the `started` feedback whose first frame omits playing
        self._decorate_failed = False
        self.reduced_motion = False
        self.music_signin_expired = False
        self.upnext_button3 = "like"     # settings.json `upnext_button3` (no UI)
        self.ledger = QueueLedger(autosave=False)
        # Controller-wide state (section 2.2).
        self.recent = RecentList()
        self.favourites = FavouritesList()
        self.start = None
        self.play_next_job = None
        self.shuffle_job = None
        # [P3] The companion-shuffle restore record's base rows (signature digests, their order at
        # Shuffle on) when known: from this controller's own accepted Shuffle on, or the record the
        # runtime loaded at start (`shuffle_record`). The Shuffle-off preview ranks by it (K3 9.5.3).
        self.shuffle_record_order = None
        self.move_next_request = None
        self.like_inflight = set()
        self.transient = None
        self.due = []                    # (at, cause, view_id, fn)
        self.last_knob_input = self.clock()
        self._last_detent = -10.0
        self._detent_dir = 1
        self._passive = None             # (cause, view_id): a passive re-entry waiting for quiet
        self._preresolve_due = None
        self._preresolve_batch = 0
        self._preresolve_sent = set()    # (kind, id) asked for pre-resolution and maybe still queued
        self._toasts = []                # (at, text): exit toasts due
        self._seek_bg = None             # SeekState still landing after Seek was left
        self._neighbours = {}            # Tracks neighbour titles per (queue_revision, P)
        self._neighbours_request = None
        self._cancel_pending = None      # the picker close waiting for cancel_result
        self.last_reentry_cause = ""
        self.origin = None               # compat: v6 Windows origin (never a resumable Screen)
        self._enter("startup")

    # ------------------------------------------------------------------ the current Screen
    @property
    def screen(self):
        return self._screen

    @screen.setter
    def screen(self, screen):
        """Every Screen goes through here: list modes share the controller-wide lists."""
        legacy = getattr(screen, "_legacy_pages", None)
        if legacy is not None and screen.mode in ("recent", "explorer"):
            items = [dict(item) for page in legacy if isinstance(page, dict)
                     for item in page.get("items") or () if isinstance(item, dict)]
            complete = not (legacy and isinstance(legacy[-1], dict) and legacy[-1].get("next"))
            previous = getattr(self, "recent", None)
            self.recent = RecentList(visit=(previous.visit + 1) if previous else 1, items=items, total=None,
                                     complete=complete, state="ready" if items else "empty",
                                     next_offset=len(items))
            screen._legacy_pages = None
        if screen.mode in ("recent", "explorer") and hasattr(self, "recent"):
            screen.recent = self.recent
        if screen.mode == "explorer" and screen.explorer is None:
            screen.explorer = ExplorerState(index_by_source={"recent": screen.index})
        if screen.mode == "windows" and screen.windows is None:
            screen.windows = WindowsState()
        if screen.mode == "upnext" and screen.upnext is None:
            P, T = self._position() if hasattr(self, "state") else (1, 0)
            screen.upnext = UpNextState(P=max(1, P), T=T, loading=True)
        if screen.mode == "seek" and screen.seek is None:
            screen.seek = SeekState()
        self._screen = screen

    # ------------------------------------------------------------------ effects
    def request(self, kind, **payload):
        """A service effect: pending until complete()."""
        self.serial += 1
        effect = {"kind": kind, "request": self.serial,
                  "control_id": self.control_id, "view_id": self.screen.view_id, **payload}
        self.pending[self.serial] = effect
        self.effects.append(effect)
        return self.serial

    def _present(self, kind, **payload):
        """A presenter effect (posted, never completed; section 11.1)."""
        self.serial += 1
        effect = {"kind": kind, "request": self.serial,
                  "control_id": self.control_id, "view_id": self.screen.view_id, **payload}
        self.effects.append(effect)
        return effect

    def drain(self):
        effects, self.effects = self.effects, []
        return effects

    def forget(self, effect):
        """An unsent write effect the runtime dropped (section 10.2): never replayed, and every
        job reference to it is released (busy dims, pending spans, in-flight guards)."""
        request = effect.get("request")
        self.pending.pop(request, None)
        if self.volume_request == request:
            self.volume_request = None
        if self.command_request == request:
            self.command_request = None
        if self.start is not None and self.start.request == request:
            self.start = None
        if self.play_next_job is not None and self.play_next_job.request == request:
            self.play_next_job = None
        if self.shuffle_job is not None and self.shuffle_job.request == request:
            self.shuffle_job = None
        if self.move_next_request == request:
            self.move_next_request = None
        if effect.get("kind") == "like":
            self.like_inflight.discard(str(effect.get("song_id")))
        for seek in (self.screen.seek, self._seek_bg):
            if seek is not None and seek.inflight == request:
                seek.inflight = None
                seek.acked_s = None
        if effect.get("kind") == "seek":
            with self._seek_lock:
                self._seek_targets.pop(request, None)
                self._seek_read.pop(request, None)
        if self.screen.windows is not None and self.screen.windows.switch_request == request:
            self.screen.windows.switch_request = None

    # ------------------------------------------------------------------ intents (lane handoffs)
    @property
    def display_volume(self):
        return int(self.desired_volume if self.desired_volume is not None else self.state["volume"])

    @property
    def desired_volume(self):
        with self._intent_lock:
            return self._volume_intent[0]

    @desired_volume.setter
    def desired_volume(self, value):
        with self._intent_lock:
            self._volume_intent = (value, self.state.get("group_revision", ""))

    def volume_intent(self):
        """Atomic worker handoff: current target and the group it belongs to."""
        with self._intent_lock:
            return self._volume_intent

    def seek_target(self, effect):
        """The newest target of a `seek` job, read when the job starts (the volume pattern). The
        value read is remembered: it is the target that jump lands on (section 5.5.4)."""
        request = effect.get("request")
        with self._seek_lock:
            target = self._seek_targets.get(request, effect.get("target_s"))
            if request is not None:
                self._seek_read[request] = target
            return target

    @property
    def windows_button(self):
        """The raw button mapped to slot 3 (VOC section 2.5): never the literal 3."""
        return self.button_order[3]

    @windows_button.setter
    def windows_button(self, _value):
        pass  # derived from button_order (K3 section 3.1 notes)

    # ------------------------------------------------------------------ state queries
    def source(self):
        source = self.state.get("source")
        if source in SOURCES:
            return source
        # A state without the section 9.1 class (an older adapter or fake): the queue only when
        # its rows are known, a stream otherwise.
        if not self.has_media():
            return "none"
        return "queue" if self.state.get("queue_length") else "radio"

    def has_media(self):
        """Streams can play with an empty queue and without a supplied title."""
        return bool(self.state.get("playback") in ("PLAYING", "PAUSED_PLAYBACK")
                    or any(self.state.get(name) for name in
                           ("can_play", "can_pause", "can_next", "can_previous"))
                    or self.state.get("queue_length", 0))

    def _position(self):
        """(P, T): the 1-based playing row and the queue length."""
        total = _int(self.state.get("queue_length"), 0)
        position = _int(self.state.get("playlist_position"), 0)
        if position <= 0 and total:
            position = 1
        return position, total

    def shuffle_active(self):
        return bool(self.state.get("companion_shuffle") or self.state.get("shuffle")
                    or self.state.get("play_mode") in SHUFFLE_PLAY_MODES)

    def sonos_shuffle(self):
        return bool(self.state.get("shuffle") or self.state.get("play_mode") in SHUFFLE_PLAY_MODES)

    def playback_action(self):
        """Choose an absolute action from confirmed state, never a blind toggle."""
        playback = self.state.get("playback")
        direction = "pause" if playback == "PLAYING" else "play"
        stable = playback in ("PLAYING", "PAUSED_PLAYBACK", "STOPPED")
        enabled = bool(self.state["online"] and stable and not self.command_request
                       and self.state.get("can_" + direction))
        return direction, enabled

    def confirmed_playing(self):
        """A Home frame's `playing` (ALIVE.md section 3, R3/R4), or None to omit it."""
        if not self.state_known or not self.state.get("online"):
            return None
        if self.start is not None:
            return None   # K2 M16: omitted while a start is pending
        playback = self.state.get("playback")
        if playback == "PLAYING":
            return True
        if playback not in ("PAUSED_PLAYBACK", "STOPPED"):
            return None
        if self._album_start_until and self.clock() < self._album_start_until:
            return None
        return False

    def _home_command(self):
        command = self.pending.get(self.command_request)
        if command and command.get("kind") == "transport" and command.get("direction") in ("play", "pause"):
            return command
        return None

    def _skip_command(self):
        command = self.pending.get(self.command_request)
        if command and command.get("kind") == "transport" and command.get("direction") in ("previous", "next"):
            return command
        return None

    def _busy_code(self):
        """The running exclusive queue action's busy code (section 2.3), or None."""
        if self.start is not None:
            return "starting"
        if self.play_next_job is not None or self.move_next_request is not None:
            return "queueing"
        if self.shuffle_job is not None:
            return "shuffling"
        return None

    def _overlay_open(self):
        return self.screen.mode in ("explorer", "upnext", "windows") or any(
            effect.get("kind") == "windows_open" for effect in self.pending.values())

    def _accent(self, kind, item):
        """0xRRGGBB accent of an entry; 0 (warm) when unknown."""
        if not isinstance(item, dict):
            return 0
        lookup = self.accent_lookup
        if lookup is not None:
            try:
                value = lookup(kind, item)
                if type(value) is int and 0 <= value <= 0xFFFFFF:
                    return value
            except Exception:  # presentation is never fatal
                pass
        value = item.get("accent")
        return value if type(value) is int and 0 <= value <= 0xFFFFFF else 0

    # ------------------------------------------------------------------ entering (section 6)
    def _enter(self, cause=""):
        self.control_id += 1
        self.ready = not self.hardware
        self.last_reentry_cause = cause
        self._passive = None
        self.effects.append({"kind": "device_enter", "control": self.control()})

    def _reenter(self, cause, index=None):
        """One control for one host-driven move; `index` clamped into the new bounds."""
        if index is not None:
            self.screen.index = index
        low, high, _ = self.bounds()
        if self.screen.mode not in ("home",):
            self.screen.index = _clamp(self.screen.index, low, high)
        self._enter(cause)

    def _schedule(self, at, cause, fn, *, any_screen=False):
        """Run fn in tick() at `at` if the Screen that scheduled it is still current."""
        self.due.append((at, cause, None if any_screen else self.screen.view_id, fn))

    def _cancel_due(self, view_id):
        self.due = [entry for entry in self.due if entry[2] != view_id]

    def _run_due(self, now):
        ready = [entry for entry in self.due if entry[0] <= now]
        if not ready:
            return
        self.due = [entry for entry in self.due if entry[0] > now]
        for at, cause, view_id, fn in sorted(ready, key=lambda entry: entry[0]):
            if view_id is not None and view_id != self.screen.view_id:
                continue
            try:
                fn()
            except Exception:  # a presentation timer is never fatal
                _log.exception("Controller timer %s failed", cause)

    def _request_passive(self, cause, *, now_if_waiting=False):
        """Section 6.4: a re-entry the user did not cause waits 400 ms after the last detent."""
        if now_if_waiting or self.clock() - self._last_detent >= PASSIVE_QUIET:
            self._reenter(cause)
        else:
            self._passive = (cause, self.screen.view_id)

    def _run_passive(self, now):
        if self._passive is None:
            return
        cause, view_id = self._passive
        if view_id != self.screen.view_id:
            self._passive = None
            return
        if now - self._last_detent >= PASSIVE_QUIET:
            self._passive = None
            self._reenter(cause)

    def _new_screen(self, mode, index=0, cause="", **fields):
        self._cancel_due(self.screen.view_id)
        self.screen = Screen(mode=mode, index=index, **fields)
        if mode in ("recent", "explorer"):
            self.screen.recent = self.recent
        if mode in OVERLAY_MODES:
            # Every overlay entry re-arms the 60 s lifetime idle (section 13.1): the press that
            # opened it (a knob button, or the Win button's F24) is the overlay's first input.
            self.last_knob_input = self.clock()
        self._enter(cause or mode)

    def _go_home(self, cause="home"):
        if self.screen.mode == "seek":
            self._leave_seek(flush=True)
        self._new_screen("home", self.display_volume, cause)

    # ------------------------------------------------------------------ bounds and control
    def _list_count(self):
        mode = self.screen.mode
        if mode == "recent":
            return self.recent.count()
        if mode == "explorer":
            return self._source_count(self.screen.explorer.source)
        if mode == "upnext":
            return self._upnext_count()
        if mode == "windows":
            return len(self.screen.windows.items) if self.screen.windows else 0
        return 0

    def bounds(self):
        mode = self.screen.mode
        if mode == "home":
            return 0, 100, self.display_volume
        if mode == "tracks":
            return 0, 2, _clamp(self.screen.index, 0, 2)
        if mode == "seek":
            seek = self.screen.seek
            return 0, seek.max, _clamp(self.screen.index, 0, seek.max)
        high = max(0, self._list_count() - 1)
        return 0, high, _clamp(self.screen.index, 0, high)

    def control(self):
        low, high, position = self.bounds()
        return {"id": self.control_id, "profile": PROFILES[self.screen.mode],
                "min": low, "max": high, "position": position,
                "windowsButton": self.button_order[3], "buttonOrder": self.button_order[:],
                "windowsHidEnabled": bool(self.windows_hid_enabled and self.screen.mode == "home"),
                "frame": self.frame(assume_ready=True)}

    # ------------------------------------------------------------------ transient copy (section 2.4)
    def _set_transient(self, copy_id, *, tone="meta", ms=REASON_META, text=None, **fields):
        """Show copy on the current screen's copy line; the id's twin follows the line."""
        home = self.screen.mode == "home"
        if home and copy_id.startswith("knob.meta.") and copy_id.replace("knob.meta.", "knob.status.") in COPY:
            copy_id = copy_id.replace("knob.meta.", "knob.status.")
        elif not home and copy_id.startswith("knob.status.") and copy_id.replace("knob.status.", "knob.meta.") in COPY:
            copy_id = copy_id.replace("knob.status.", "knob.meta.")
        line = LINE_STATUS if copy_id.startswith("knob.status.") else LINE_META
        if text is None:
            text = fit_copy(copy_id, line, **fields)
        self.transient = TransientCopy(copy_id, text, tone, self.clock() + ms)

    def _transient(self):
        transient = self.transient
        if transient is None:
            return None
        if self.clock() >= transient.until:
            self.transient = None
            return None
        return transient

    def _feedback(self, kind, skip=0, *, moment=None, side=None, color=None):
        """Arm a moment: a new seq plays exactly once (VOC section 4)."""
        self.feedback_seq = self.feedback_seq % FEEDBACK_SEQ_MAX + 1
        self.feedback = {"kind": kind, "seq": self.feedback_seq}
        if kind == "ok" and skip in (-1, 1):
            self.feedback["skip"] = skip
        elif kind == "ok" and moment:
            self.feedback["moment"] = moment
            if moment == "snap" and side in (-1, 1):
                self.feedback["side"] = side
            if moment in ("snap", "started") and type(color) is int and color:
                self.feedback["color"] = color
            if moment == "started":
                self._started_seq = self.feedback_seq

    # ------------------------------------------------------------------ toasts (section 12)
    def _toast(self, copy_id, **fields):
        """A toast now: dropped while an overlay is open (rule 1)."""
        if self._overlay_open():
            return
        self._present("toast", text=copy_text(copy_id, **fields), exit=False)

    def _exit_toast(self, copy_id, close_at, **fields):
        """An overlay's exit toast: at max(close + 360 ms, now) (rules 2 and 7)."""
        now = self.clock()
        at = max(close_at + EXIT_TOAST_DELAY, now)
        text = copy_text(copy_id, **fields)
        if at <= now:
            if not self._overlay_open():
                self._present("toast", text=text, exit=True)
            return
        self._toasts.append((at, text))

    def _run_toasts(self, now):
        if not self._toasts:
            return
        due = [entry for entry in self._toasts if entry[0] <= now]
        self._toasts = [entry for entry in self._toasts if entry[0] > now]
        for _at, text in due:
            if self._overlay_open():
                continue  # another overlay is open at that moment: dropped
            self._present("toast", text=text, exit=True)

    # ------------------------------------------------------------------ public input API (section 2.5)
    def _accepts(self, control_id):
        return self.ready and (control_id is None or control_id == self.control_id)

    def _play_window(self, now):
        explorer, upnext = self.screen.explorer, self.screen.upnext
        return bool((explorer and now < explorer.play_until) or (upnext and now < upnext.play_until))

    def position(self, position, control_id=None):
        if not self._accepts(control_id) or type(position) is not int:
            return
        low, high, current = self.bounds()
        if not low <= position <= high or position == current:
            return
        now = self.clock()
        mode = self.screen.mode
        if self._play_window(now):
            return
        if mode == "explorer" and now < self.screen.explorer.swap_until:
            return  # positions of the old source's control are discarded (section 5.3.3)
        if mode == "upnext" and now < self.screen.upnext.swap_until:
            return
        self.last_knob_input = now
        self._detent_dir = 1 if position > current else -1
        self._last_detent = now
        if mode == "home":
            if not self.state["online"]:
                return
            self.desired_volume = position
            self._reveal_volume(VOLUME_REVEAL_SECONDS, "local")
            self._external_until = 0.0
            self.volume_due = max(now, self.last_volume_write + 0.1)
            return
        self.screen.index = position
        if mode == "recent":
            self._recent_moved()
        elif mode == "explorer":
            self._explorer_moved()
        elif mode == "tracks":
            pass
        elif mode == "seek":
            seek = self.screen.seek
            seek.target_s = seek.t(position)
            seek.due = now + SEEK_DEBOUNCE
            seek.idle_due = now + SEEK_IDLE
            # A turn during a jump only moves the frozen target (C5-68). A job still queued on
            # the audio lane reads this newest target when it starts (the volume pattern).
            if seek.inflight is not None:
                with self._seek_lock:
                    self._seek_targets[seek.inflight] = seek.target_s
        elif mode == "upnext":
            self._present("upnext_highlight", index=position, control_id=self.control_id, bump=0)
            self._upnext_refill()
        elif mode == "windows":
            windows = self.screen.windows
            if windows.snap_busy is not None:
                windows.snap_busy.turned = True
            if windows.switch_request is None:
                self._present("windows_highlight", index=position, control_id=self.control_id, bump=0)

    def turn(self, delta):
        """A host-side turn (simulator, picker keys without a knob session)."""
        low, high, current = self.bounds()
        self.position(_clamp(current + delta, low, high))

    def button(self, logical, control_id=None, hid=False):
        if not self._accepts(control_id) or logical not in (0, 1, 2, 3):
            return
        if logical == 3 and hid:
            return  # the F24 path already acted (VOC section 2.5)
        now = self.clock()
        if self._play_window(now):
            return  # every button and hold (C5-9)
        self.last_knob_input = now
        mode = self.screen.mode
        if self._silent_guard(mode, logical, now):
            return
        spec = self._buttons()[logical]
        code = spec["code"]
        if code is not None:
            self._refuse(logical, code)
            return
        getattr(self, "_press_" + mode)(logical, now)

    def hold(self, logical, control_id=None):
        """The firmware's 600 ms hold (`kh`), logical 0 only, once per event (section 4.2)."""
        if logical != 0 or not self._accepts(control_id):
            return
        now = self.clock()
        if self._play_window(now):
            return
        self.last_knob_input = now
        mode = self.screen.mode
        if mode == "home":
            return
        if mode in ("recent", "tracks"):
            self._go_home("hold")
        elif mode == "seek":
            self._leave_seek(flush=True)
            self._new_screen("home", self.display_volume, "hold")
        elif mode == "explorer":
            self._close_explorer("hold")
        elif mode == "upnext":
            self._close_upnext("hold")
        elif mode == "windows":
            windows = self.screen.windows
            if windows.snap_busy is not None:
                windows.latched_close = "hold"
            else:
                self._close_windows("hold")

    def limit(self, direction, control_id=None):
        """An end-stop push (`lim`): Seek limit line and idle re-arm, overlay end bumps, lifetime."""
        if direction not in (-1, 1) or not self._accepts(control_id):
            return
        now = self.clock()
        self.last_knob_input = now
        mode = self.screen.mode
        if mode == "seek":
            seek = self.screen.seek
            seek.idle_due = now + SEEK_IDLE
            if direction == 1 and self.screen.index >= seek.max:
                seek.limit_until = now + SEEK_LIMIT_LINE
        elif mode == "explorer":
            self._present("explorer_highlight", index=self.screen.index, control_id=self.control_id, bump=direction)
        elif mode == "upnext":
            self._present("upnext_highlight", index=self.screen.index, control_id=self.control_id, bump=direction)
        elif mode == "windows":
            self._present("windows_highlight", index=self.screen.index, control_id=self.control_id, bump=direction)

    def device_ready(self, control_id):
        if control_id == self.control_id:
            self.ready = True

    def set_hardware(self, enabled):
        """A knob (re)connect: fresh state read and Home (C5-2)."""
        self.hardware = enabled
        if enabled:
            self.last_poll = -10.0
            if self.screen.mode != "home":
                self._cancel_due(self.screen.view_id)
                self.screen = Screen(mode="home", index=self.display_volume)
            self._enter("reconnect")
        else:
            self._enter("hardware off")

    def disconnected(self):
        """Section 13.4: close every overlay (`disconnect`), exit Seek dropping its target, clear
        the transient; a pending start finishes honestly; the Screen becomes Home."""
        mode = self.screen.mode
        if mode in ("explorer", "upnext", "windows"):
            self._close_overlay_now("disconnect")
        if self.screen.mode == "seek":
            self._leave_seek(flush=False, drop=True)   # an exit the user did not make (C5-47)
        self.hardware = False
        self.ready = False
        self.desired_volume = None
        self._volume_reveal_until = 0.0
        self._volume_reveal_source = ""
        self._external_until = 0.0
        self.transient = None
        self._toasts = []
        self._passive = None
        if self.screen.mode != "home":
            self._cancel_due(self.screen.view_id)
            self.screen = Screen(mode="home", index=self.display_volume)

    def set_reduced_motion(self, on):
        self.reduced_motion = bool(on)

    def open_windows(self):
        """F24 (or serial logical 3 without a hotkey) on Home only (section 5.7.1). The Win press
        is the knob's own button (its `kd` is dropped as `hid`), so it counts as knob input for
        the lifetime idle (section 13.1)."""
        self.last_knob_input = self.clock()
        if self.screen.mode != "home" or any(e.get("kind") == "windows_open" for e in self.pending.values()):
            return
        self.request("windows_open")

    def dismiss_windows(self):
        """External focus won (`focus_lost`): hide without focus restore, no U12, Home."""
        if self.screen.mode == "windows":
            self._close_overlay_now("focus_lost")

    def home(self):
        """Compat: Back to Home from anywhere (the picker closes with `back`)."""
        if self.screen.mode == "windows":
            self._close_windows("back")
        elif self.screen.mode == "explorer":
            self._close_explorer("hold")
        elif self.screen.mode == "upnext":
            self._close_upnext("hold")
        elif self.screen.mode != "home":
            self._go_home("home")

    def close_overlay(self, reason):
        """Lifetime closes (section 13.1): lock, sleep, idle, group, foreground, source, disconnect.

        Never latched behind an in-flight snap (WP5R-2): only Back and hold wait for the snap to
        resolve (C5-12, 5.7.3); lock, sleep and idle close the picker at once (5.7.4; K4 15 "instant",
        hidden in the same presenter wake), and a latched Back or hold gives way to them. A
        `snap_result` that arrives after the close is dropped (the picker is no longer the Screen)."""
        mode = self.screen.mode
        if mode in ("explorer", "upnext", "windows"):
            self._close_overlay_now(reason)

    # ------------------------------------------------------------------ presenter events (section 11.4)
    def presenter_event(self, event):
        """The one entry point for every presenter event (VOC-R22): K4's ``(kind, payload)``
        tuples and the picker's dicts alike (``presenter_event_dict``)."""
        event = presenter_event_dict(event)
        if event is None:
            return
        kind = event.get("kind")
        surface = event.get("surface")
        control = event.get("control_id")
        if control is not None and control != self.control_id and kind in ("click_action",):
            _log.debug("Presenter event %s for an old control dropped", kind)
            return
        if kind in ("opened",):
            return
        if kind == "closed":
            reason = event.get("reason")
            if reason in ("display", "device"):
                self.presenter_closed(surface, reason)
            return
        if kind == "refused":
            self.presenter_refused(surface, event.get("reason"))
            return
        if kind == "click_action":
            if self._surface_mode(surface) == self.screen.mode:
                self.button(3, self.control_id)
            return
        if kind == "system":
            what = event.get("what", event.get("system", event.get("value")))
            if what in ("lock", "sleep"):
                self.close_overlay(what)
            elif what == "motion":
                on = event.get("reduced", event.get("on"))
                if type(on) is bool:
                    self.set_reduced_motion(on)
            elif what == "foreground":
                if self.screen.mode in ("explorer", "upnext"):
                    self.close_overlay("foreground")
            return
        if kind == "snap_result":
            self.snap_result(event.get("side"), event.get("outcome"))
            return
        if kind == "cancel_result":
            self.cancel_result(bool(event.get("restored")), bool(event.get("completed")))

    @staticmethod
    def _surface_mode(surface):
        return {"explorer": "explorer", "upnext": "upnext", "picker": "windows"}.get(surface)

    def presenter_closed(self, surface, reason):
        """A close the presenter started (`display`, `device`): parent mode, no toast, no U12."""
        mode = self._surface_mode(surface)
        if mode is None or mode != self.screen.mode:
            return
        self._close_overlay_now(reason, emit=False)

    def presenter_refused(self, surface, reason):
        """Section 13.5: the knob leaves the mode it entered at the press for the parent."""
        mode = self._surface_mode(surface)
        if mode is None or mode != self.screen.mode:
            return
        if reason == "busy":
            _log.warning("The %s overlay was refused as busy (one-overlay guard)", surface)
        self._close_overlay_now("refused", emit=False)
        self._feedback("err")
        self._set_transient("knob.meta.stage_unavailable", tone="error", ms=FAIL_META)
        self.notice = "The screen overlay could not open."

    # ------------------------------------------------------------------ closes (section 13)
    def _close_overlay_now(self, reason, emit=True):
        mode = self.screen.mode
        if mode == "explorer":
            self._close_explorer(reason, emit=emit)
        elif mode == "upnext":
            self._close_upnext(reason, emit=emit)
        elif mode == "windows":
            self._close_windows(reason, emit=emit)

    def _close_explorer(self, reason, emit=True):
        now = self.clock()
        explorer = self.screen.explorer
        index = explorer.index_by_source.get("recent", 0)
        if emit:
            self._present("explorer_close", t0=now, reason=reason, close_at_ms=0)
        if reason in ("hold", "disconnect"):
            if reason == "disconnect":
                self._cancel_due(self.screen.view_id)
                self.screen = Screen(mode="home", index=self.display_volume)
                return
            self._new_screen("home", self.display_volume, "hold")
            return
        self._new_screen("recent", index, reason)
        self._recent_moved(schedule_preresolve=False)

    def _close_upnext(self, reason, emit=True):
        now = self.clock()
        upnext = self.screen.upnext
        parent = self.screen.parent_index if self.screen.parent_index is not None else 1
        armed = upnext.armed_toast if upnext else None
        if emit:
            self._present("upnext_close", t0=now, reason=reason, close_at_ms=0)
        if reason == "back" and armed:
            self._exit_toast(armed, now)
        if reason == "disconnect":
            self._cancel_due(self.screen.view_id)
            self.screen = Screen(mode="home", index=self.display_volume)
            return
        if reason == "hold":
            self._new_screen("home", self.display_volume, "hold")
            return
        self._enter_tracks(parent, reason)

    def _close_windows(self, reason, emit=True):
        """Picker closes: back/hold/lock/sleep/idle apply U12 and go through `windows_cancel`, which
        carries the close `reason` (K3 5.7.4, C5-78, phase-2b review item R8; the picker's own
        inference is only the fallback for a payload without one, WP7b-D6); back/hold/idle restore focus, lock and sleep
        never do (K4 15); disconnect, focus_lost and display hide without either (VOC-R15)."""
        now = self.clock()
        windows = self.screen.windows
        if emit:
            if reason in ("back", "hold", "lock", "sleep", "idle"):
                complete = None
                assigned = [side for side in ("left", "right") if getattr(windows, side)]
                if len(assigned) == 1:
                    snapped = getattr(windows, assigned[0])
                    if windows.desk_open is not None and windows.desk_open != snapped:
                        complete = "right" if assigned[0] == "left" else "left"
                self._present("windows_cancel", origin=windows.origin, home=True, complete=complete, reason=reason)
                self._cancel_pending = {"reason": reason, "closed_at": now, "complete": complete,
                                        "left": self._window_app(windows.left),
                                        "right": self._window_app(windows.right),
                                        "origin": self._window_app(windows.desk_open)}
            else:
                self._present("windows_hide")
                self._cancel_pending = None
        if reason == "disconnect":
            self._cancel_due(self.screen.view_id)
            self.screen = Screen(mode="home", index=self.display_volume)
            return
        self._new_screen("home", self.display_volume, reason)

    def _window_app(self, item_id):
        if item_id is None:
            return ""
        for item in (self.screen.windows.items if self.screen.windows else ()):
            if item.get("id") == item_id:
                return item.get("label_app") or item.get("app", "")
        return ""

    def cancel_result(self, restored, completed):
        """`windows_cancel` answered (C5-53): `toast.snap.one_side` only after a completed back close."""
        pending, self._cancel_pending = self._cancel_pending, None
        if not pending:
            return
        if not restored and pending["reason"] not in ("lock", "sleep"):
            # K4 15: a lock or sleep close never restores focus, so `restored` false is expected there.
            self.notice = "Original window no longer available"
        if pending["reason"] == "back" and completed and pending["complete"]:
            left, right = pending["left"], pending["right"]
            if pending["complete"] == "left":
                left = pending["origin"]
            else:
                right = pending["origin"]
            self._exit_toast("toast.snap.one_side", pending["closed_at"], A=left, B=right)

    # ------------------------------------------------------------------ silent guards (section 3.4)
    def _silent_guard(self, mode, logical, now):
        if mode == "explorer":
            explorer = self.screen.explorer
            if logical in (1, 2) and now < explorer.swap_until:
                return True
        elif mode == "upnext":
            upnext = self.screen.upnext
            if logical == 1 and now < upnext.swap_until:
                return True
            if logical == 2:
                row = self._upnext_focus_row()
                if row and row.get("song_id") in self.like_inflight:
                    return True
        elif mode == "windows":
            windows = self.screen.windows
            if windows.switch_request is not None:
                return True
            if windows.snap_busy is not None:
                if logical == 0:
                    windows.latched_close = "back"
                return True
        return False

    # ------------------------------------------------------------------ refusals (section 3.3)
    def _reason(self, code, slot):
        """(copy_id, tone, seconds, toast_id) or None when the press is ignored (C5-59)."""
        mode = self.screen.mode
        if code in ("loading", "empty", "neutral", "seeking", "sonos_card"):
            return None
        if code == "starting":
            if mode == "home" and slot == 0:
                return None
            return "knob.meta.busy.starting", "meta", REASON_META, None
        if code == "queueing":
            if mode == "recent":
                return None
            job = self.play_next_job
            if job is not None and job.k >= 1 and job.n:
                return "knob.meta.playnext.progress", "meta", REASON_META, None
            return "knob.meta.playnext.resolving", "meta", REASON_META, None
        if code == "shuffling":
            if mode == "upnext":
                return None
            return "knob.meta.busy.shuffling", "meta", REASON_META, None
        if code == "transport_pending":
            if mode == "home":
                return None
            if self._skip_command() is not None:
                return None
            command = self._home_command() or {}
            copy_id = "knob.meta.busy.pausing" if command.get("direction") == "pause" else "knob.meta.busy.starting"
            return copy_id, "meta", REASON_META, None
        if code == "nothing_next":
            P, T = self._position()
            if T - P < 2:
                return None
            return "knob.meta.shuffle.nothing", "meta", REASON_META, None
        if code == "sonos_unavailable":
            return ("knob.status.sonos_unavailable" if mode == "home" else "knob.meta.sonos_unavailable"), \
                "meta", REASON_META, None
        if code == "nothing_playing":
            return "knob.status.nothing_playing", "meta", REASON_META, None
        if code == "signin_expired":
            return "knob.meta.signin_expired", "error", SIGNIN_META, None
        if code == "list_error":
            return "knob.meta.library_error", "meta", REASON_META, None
        if code == "item_unavailable":
            return "knob.meta.item_unavailable", "meta", REASON_META, None
        if code.startswith("src_"):
            cls = code[4:]
            if mode == "recent":
                toast = "toast.playnext.none" if cls == "none" else "toast.playnext.not_queue"
                return "knob.meta.playnext." + cls, "meta", REASON_META, toast
            if slot == 2 and mode == "tracks":
                return "knob.meta.seek." + cls, "meta", REASON_META, None
            return "knob.meta.upnext." + cls, "meta", REASON_META, None
        if code == "sonos_shuffle":
            return "knob.meta.playnext.shuffle", "meta", REASON_META, "toast.playnext.shuffle"
        if code == "no_length":
            return "knob.meta.seek.no_length", "meta", REASON_META, None
        if code == "skip_unavailable":
            copy_id = "knob.meta.skip.prev_unavailable" if self.screen.index == 0 else "knob.meta.skip.next_unavailable"
            return copy_id, "meta", REASON_META, None
        if code == "likes_unknown":
            return "knob.meta.like.unknown", "meta", REASON_META, None
        if code == "not_catalog":
            return "knob.meta.like.not_catalog", "meta", REASON_META, None
        if code == "closed":
            return "knob.meta.windows.closed", "meta", REASON_META, None
        if code == "unlike_unavailable":
            return "knob.meta.like.unlike_in_music", "meta", LIKE_FAIL_META, None
        return None

    def _refuse(self, slot, code):
        """A press never acts on a dimmed button: reason copy + Head shake, unless ignored."""
        reason = self._reason(code, slot)
        if reason is None:
            return
        copy_id, tone, seconds, toast = reason
        fields = {}
        if copy_id == "knob.meta.playnext.progress":
            job = self.play_next_job
            fields = {"k": job.k, "n": job.n}
        self._set_transient(copy_id, tone=tone, ms=seconds, **fields)
        self._feedback("err")
        if toast and self.screen.mode == "recent" and slot == 2:
            self._toast(toast)

    # ------------------------------------------------------------------ the button grammar (section 3.1)
    @staticmethod
    def _btn(icon, label, code=None, lit=None, color=0):
        return {"icon": icon, "label": label, "code": code, "lit": lit, "color": color}

    def _buttons(self):
        return getattr(self, "_buttons_" + self.screen.mode)()

    def _src_code(self):
        source = self.source()
        return None if source == "queue" else "src_" + source

    def _buttons_home(self):
        online = self.state["online"]
        playing = online and self.state.get("playback") == "PLAYING"
        token = "pause" if playing else "play"
        command = self._home_command()
        code = None
        if not online:
            code = "sonos_unavailable"
        elif self.start is not None:
            code = "starting"
        elif command is not None:
            code = "transport_pending"
            token = "pause" if command.get("direction") == "play" else "play"
        elif not self.has_media():
            code = "nothing_playing"
        tracks_code = "sonos_unavailable" if not online else ("nothing_playing" if not self.has_media() else None)
        return [self._btn(token, "Pause" if token == "pause" else "Play", code),
                self._btn("list", "Browse"),
                self._btn("tracks", "Tracks", tracks_code),
                self._btn("win", "Win")]

    def _list_codes(self, lst_state, item, focused_loaded):
        """The shared first dims of Recent 3/4 and Explorer 4 (loading ... item_unavailable)."""
        if lst_state == "loading" or not focused_loaded:
            if lst_state not in ("empty", "signin", "error"):
                return "loading"
        if lst_state == "empty":
            return "empty"
        if lst_state == "signin":
            return "signin_expired"
        if lst_state == "error":
            return "list_error"
        busy = self._busy_code()
        if busy:
            return busy
        if not self.state["online"]:
            return "sonos_unavailable"
        if item is not None and item.get("available") is False:
            return "item_unavailable"
        return None

    def _buttons_recent(self):
        lst = self.recent
        item = lst.item(self.screen.index)
        loaded = item is not None
        open_code = "signin_expired" if lst.state == "signin" else ("list_error" if lst.state == "error" else None)
        play_code = self._list_codes(lst.state, item, loaded)
        next_code = play_code
        if next_code is None:
            next_code = self._src_code() or ("sonos_shuffle" if self.sonos_shuffle() else None)
        return [self._btn("back", "Back"), self._btn("expand", "Open", open_code),
                self._btn("playnext", "Play next", next_code), self._btn("play", "Play", play_code)]

    def _buttons_explorer(self):
        explorer = self.screen.explorer
        source = explorer.source
        item = self._source_item(source, self.screen.index)
        state = self._source_state(source)
        code = self._list_codes(state, item, item is not None)
        if code is None and source == "favourites" and item is not None:
            meta = self.favourites.meta.get(_item_id(item)) or {}
            if meta.get("empty"):
                code = "item_unavailable"
        recent_on = source == "recent"
        return [self._btn("back", "Back"),
                self._btn("clock", "Recent", lit="on" if recent_on else "off"),
                self._btn("playlists", "Playlists", lit="off" if recent_on else "on"),
                self._btn("play", "Play", code)]

    def _tracks_upnext_code(self):
        if not self.state["online"]:
            return "sonos_unavailable"
        return self._src_code()

    def _queue_end(self, index):
        """Tracks 4 at a queue end: 'end' / 'start' (the press is refused), or None."""
        if self.source() != "queue" or self.state.get("repeat") == "all" or self.sonos_shuffle():
            return None
        P, T = self._position()
        if index == 2 and T and P >= T:
            return "end"
        if index == 0 and P <= 1 and T:
            return "start"
        return None

    def _buttons_tracks(self):
        online = self.state["online"]
        index = _clamp(self.screen.index, 0, 2)
        upnext_code = self._tracks_upnext_code()
        seek_code = upnext_code
        if seek_code is None and not self._can_seek():
            seek_code = "no_length"
        if seek_code is None and self.start is not None:
            seek_code = "starting"
        skip_code = None
        if index == 1:
            skip_code = "neutral"
        elif not online:
            skip_code = "sonos_unavailable"
        else:
            busy = self._busy_code()
            if busy:
                skip_code = busy
            elif self.command_request is not None:
                skip_code = "transport_pending"
            elif self._queue_end(index) is None:
                offered = self.state.get("can_previous") if index == 0 else self.state.get("can_next")
                if not offered:
                    skip_code = "skip_unavailable"
        return [self._btn("back", "Back"), self._btn("expand", "Up next", upnext_code),
                self._btn("seek", "Seek", seek_code),
                self._btn("prev" if index == 0 else "next", "Skip", skip_code)]

    def _can_seek(self):
        if "can_seek" not in self.state:
            return False
        duration = self.state.get("duration_s")
        if isinstance(duration, int) and duration > SEEK_MAX_DURATION_S:
            return False
        return bool(self.state.get("can_seek"))

    def _buttons_seek(self):
        return [self._btn("back", "Back"), self._btn("expand", "Up next", self._tracks_upnext_code()),
                self._btn("seek", "Seek", lit="on"), self._btn("next", "Skip", "seeking")]

    def _buttons_upnext(self):
        upnext = self.screen.upnext
        online = self.state["online"]
        active = self.shuffle_active()
        busy = self._busy_code()
        focus_row = self._upnext_focus_row()
        on_card = self._upnext_on_card()
        loading_focus = upnext.loading or (focus_row is None and not on_card)
        # Button 2 (shuffle)
        shuffle_code = None
        P, T = self._position()
        U = max(0, T - P)
        if upnext.loading or (not active and U <= COMPANION_SHUFFLE_MAX and not self._upcoming_loaded()):
            shuffle_code = "loading"
        elif busy:
            shuffle_code = busy
        elif not online:
            shuffle_code = "sonos_unavailable"
        elif not active and U <= COMPANION_SHUFFLE_MAX and U - len(self._playnext_offsets()) < 2:
            shuffle_code = "nothing_next"
        # Button 3 (like, or the Play next fallback)
        liked = bool(focus_row and focus_row.get("liked") is True)
        if self.upnext_button3 == "playnext":
            like = self._btn("playnext", "Play next")
            if loading_focus:
                like["code"] = "loading"
            elif on_card:
                like["code"] = "sonos_card"
            elif busy:
                like["code"] = busy
        else:
            like = self._btn("heart", "Liked" if liked else "Like", lit="on" if liked else None)
            if loading_focus:
                like["code"] = "loading"
            elif on_card:
                like["code"] = "sonos_card"
            elif focus_row.get("catalog") is False or not focus_row.get("song_id"):
                like["code"] = "not_catalog"
            elif focus_row.get("liked") is None:
                like["code"] = "likes_unknown"
        # Button 4 (play)
        play_code = None
        if loading_focus:
            play_code = "loading"
        elif on_card:
            play_code = "sonos_card"
        elif busy:
            play_code = busy
        elif not online:
            play_code = "sonos_unavailable"
        return [self._btn("back", "Back"), self._btn("shuffle", "Shuffle", shuffle_code, lit="on" if active else "off"),
                like, self._btn("play", "Play", play_code)]

    def _buttons_windows(self):
        windows = self.screen.windows
        item = self._window_item(self.screen.index)
        code = "empty" if not windows.items else ("closed" if item is not None and not item.get("available") else None)
        left = self._window_item_by_id(windows.left)
        right = self._window_item_by_id(windows.right)
        left_btn = self._btn("snapleft", "Snap left", code)
        right_btn = self._btn("snapright", "Snap right", code)
        if left is not None:
            left_btn.update(lit="on", color=self._accent("window", left))
        if right is not None:
            right_btn.update(lit="on", color=self._accent("window", right))
        return [self._btn("back", "Back"), left_btn, right_btn, self._btn("switch", "Switch", code)]

    # ------------------------------------------------------------------ Home (section 5.1)
    def _press_home(self, logical, now):
        if logical == 0:
            direction, enabled = self.playback_action()
            playback = self.state.get("playback")
            if playback not in ("PLAYING", "PAUSED_PLAYBACK", "STOPPED") or not self.state.get("can_" + direction):
                return  # an unstable transport: silently ignored (no blind toggle)
            self.notice = ""
            self._paused_since = None
            self._paused_idle_cancelled = True
            self._album_start_until = 0.0
            self.command_request = self.request("transport", direction=direction,
                                                expected_group_revision=self.state["group_revision"],
                                                expected_track_id=self.state.get("track_id"))
        elif logical == 1:
            self._browse()
        elif logical == 2:
            self._enter_tracks(1, "tracks")
        elif logical == 3:
            self.open_windows()

    def _reveal_volume(self, seconds, source):
        self._volume_reveal_until = self.clock() + seconds
        self._volume_reveal_source = source

    def _home_layout(self, ready=None, reveal=True):
        ready = self.ready if ready is None else ready
        if not self.state["online"]:
            return "notice"
        if not ready:
            return "nowPlaying"
        now = self.clock()
        if reveal and self._volume_reveal_until and (now < self._volume_reveal_until
                                                     or self.desired_volume is not None or self.volume_request is not None):
            return "volume"
        if self._home_command() or self.start is not None:
            return "nowPlaying"
        if not self.has_media():
            return "idle"
        if (self.state.get("playback") == "PAUSED_PLAYBACK" and self._paused_since is not None
                and now - self._paused_since >= PAUSED_IDLE_SECONDS):
            return "idle"
        if self.state.get("playback") == "STOPPED":
            return "idle"
        return "nowPlaying"

    # ------------------------------------------------------------------ Recently Added (section 5.2)
    def _browse(self):
        """Home 2: a new visit at item 1 (C5-1)."""
        self.recent = RecentList(visit=self.recent.visit + 1)
        self._new_screen("recent", 0, "browse")
        self._request_recent_page(lane="library")

    def _request_recent_page(self, lane):
        lst = self.recent
        if lst.inflight is not None:
            return
        kind = "recent" if lane == "library" else "recent_lookahead"
        lst.inflight = self.request(kind, visit=lst.apple_visit, offset=lst.next_offset, limit=RECENT_PAGE,
                                    list_visit=lst.visit)
        lst.inflight_lane = lane

    def _recent_index(self):
        """max(recent index, explorer recent index): what the prefetch keeps ahead of."""
        mode = self.screen.mode
        if mode == "recent":
            return self.screen.index
        if mode == "explorer":
            return self.screen.explorer.index_by_source.get("recent", 0)
        return None

    def _recent_prefetch(self):
        lst = self.recent
        index = self._recent_index()
        if index is None:
            return
        if lst.state == "loading" and not lst.items and lst.inflight is None and self.clock() >= lst.retry_at:
            self._request_recent_page("library")   # the first page, asked again (a held list)
            return
        if lst.state in ("loading", "empty", "signin", "error") or lst.complete:
            return
        focused_unloaded = index >= len(lst.items)
        if lst.inflight is not None:
            # Section 5.2.2: a fast spin outran the prefetch. The page the user now waits for moves
            # to the library lane (the lookahead one may sit behind a pre-resolution for seconds);
            # whichever copy lands first is kept, the other is dropped by its offset.
            if focused_unloaded and lst.inflight_lane == "lookahead":
                lst.inflight = None
                self._request_recent_page("library")
            return
        if self.clock() < lst.retry_at:
            return
        if len(lst.items) - 1 - index >= RECENT_AHEAD:
            return
        self._request_recent_page("library" if focused_unloaded else "lookahead")

    def _recent_moved(self, schedule_preresolve=True):
        self._recent_prefetch()
        if schedule_preresolve:
            self._preresolve_due = self.clock() + PREFETCH_RESOLVE_REST
            self._drop_stale_preresolve()

    @staticmethod
    def _preresolve_key(item):
        return (item.get("kind"), str(item.get("id")))

    def _drop_stale_preresolve(self):
        """Section 5.2.2 / 9.8.7: a new focus drops the queued (unsent) pre-resolutions that are
        no longer the focus or a neighbour, at the detent (not at the next rest). The runtime
        keeps only `keep` in the lookahead lane's queue; the one running finishes into the cache."""
        if not self._preresolve_sent:
            return
        index = self._recent_index()
        keep = []
        if index is not None:
            for target in (index, index + self._detent_dir, index - self._detent_dir):
                item = self.recent.item(target)
                if item is not None and self._preresolve_key(item) not in keep:
                    keep.append(self._preresolve_key(item))
        if not self._preresolve_sent - set(keep):
            return
        self._preresolve_sent.intersection_update(keep)
        self._present("resolve_drop", keep=[{"kind": kind, "id": ident} for kind, ident in keep])

    def _recent_result(self, effect, result, error):
        lst = self.recent
        if effect.get("list_visit") != lst.visit:
            return  # a page of an older visit never commits
        if lst.inflight == effect["request"]:
            lst.inflight = None
        offset = effect.get("offset")
        if type(offset) is int and offset != lst.next_offset:
            return  # the other copy of this page (moved to the library lane, section 5.2.2) landed first
        twin = lst.inflight is not None and (self.pending.get(lst.inflight) or {}).get("offset") == offset
        if error is not None:
            if twin:
                return  # the library copy of this page is still out: it answers for the page
            if self._discarded(error):
                lst.retry_at = self.clock() + RECENT_RETRY   # the list keeps its state; asked again
                return
            outcome = getattr(error, "outcome", None)
            signin = outcome == "signin_expired" or getattr(error, "status", None) in (401, 403) or \
                _needs_login(str(error).lower())
            if not lst.items:
                lst.state = "signin" if signin else "error"
                lst.rev += 1
                self._list_state_changed()
            else:
                lst.retry_at = self.clock() + RECENT_RETRY
            return
        if not isinstance(result, dict) or not isinstance(result.get("items"), list):
            return
        if twin:
            lst.inflight = None   # this copy won; the other one is dropped by its offset when it lands
        was_count = lst.count()
        was_loaded_end = self._recent_index() is not None and self._recent_index() >= len(lst.items) - 1
        if lst.apple_visit is None:
            lst.apple_visit = result.get("visit")
        lst.items.extend(deepcopy(result["items"]))
        total = result.get("total")
        lst.total = total if isinstance(total, int) and not isinstance(total, bool) and total >= 0 else lst.total
        lst.complete = bool(result.get("complete"))
        lst.next_offset = _int(result.get("offset"), lst.next_offset) + RECENT_PAGE
        if lst.complete and lst.total is not None and lst.total != len(lst.items):
            lst.total = len(lst.items)
        lst.state = "ready" if lst.items else ("empty" if lst.complete else "ready")
        if not lst.items and not lst.complete:
            lst.state = "loading"
            self._request_recent_page("library")
        lst.rev += 1
        if self.screen.mode in ("recent", "explorer"):
            count_now = lst.count()
            if count_now != was_count:
                if self.screen.mode == "recent" or self.screen.explorer.source == "recent":
                    if was_count == 0:
                        self._reenter("recent loaded")
                    else:
                        self._request_passive("recent growth", now_if_waiting=was_loaded_end)
            self._list_state_changed()
            self._recent_prefetch()
            if was_count == 0 and self.screen.mode in ("recent", "explorer"):
                self._preresolve_due = self.clock() + PREFETCH_RESOLVE_REST

    def _list_state_changed(self):
        if self.screen.mode == "explorer":
            self._explorer_push_highlight(data=True)

    def _preresolve(self, now):
        """C5-66: 400 ms after the last detent on a loaded Recently Added item, the focused item,
        then its neighbour in the direction of travel, then the other neighbour."""
        if self._preresolve_due is None or now < self._preresolve_due:
            return
        self._preresolve_due = None
        index = self._recent_index()
        if index is None or self.screen.mode == "explorer" and self.screen.explorer.source != "recent":
            return
        lst = self.recent
        focus = lst.item(index)
        if focus is None:
            return
        order = [index, index + self._detent_dir, index - self._detent_dir]
        self._preresolve_batch += 1
        for position, target in enumerate(order):
            item = lst.item(target)
            if item is None or item.get("available") is False:
                continue
            self._preresolve_sent.add(self._preresolve_key(item))
            self._present("resolve", item=_descriptor_resource(item), direction=self._detent_dir,
                          focused=position == 0, batch=self._preresolve_batch)

    # ------------------------------------------------------------------ explorer (section 5.3)
    def _source_count(self, source):
        return self.recent.count() if source == "recent" else self.favourites.count()

    def _source_state(self, source):
        if source == "recent":
            return self.recent.state
        state = self.favourites.state
        if state in ("none", "loading"):
            return "loading"
        if state == "error":
            return "loading"   # C5-42: without a cache the tab shows loading while retries run
        return state

    def _source_item(self, source, index):
        if source == "recent":
            return self.recent.item(index)
        return self.favourites.items[index] if 0 <= index < len(self.favourites.items) else None

    def _favourites_index(self):
        focus = self.favourites.focus_id
        for index, item in enumerate(self.favourites.items):
            if _item_id(item) == focus:
                return index
        return 0

    def _open_explorer(self, now):
        index = self.screen.index
        explorer = ExplorerState(source="recent", index_by_source={"recent": index})
        self._new_screen("explorer", index, "explorer open", explorer=explorer)
        self._favourites_ensure(now)
        self._present("explorer_open", t0=now, **self._explorer_payload("recent", index),
                      control_id=self.control_id, control_min=0, reduced_motion=self.reduced_motion,
                      foreground_hwnd=None, sonos_available=bool(self.state["online"]))
        explorer.sent = self._explorer_sent_marker("recent", index)

    def _favourites_ensure(self, now, force=False):
        fav = self.favourites
        if fav.inflight is not None or now < fav.retry_at:
            return
        if fav.state == "ready" or fav.state == "empty":
            if fav.loaded_at is not None and now - fav.loaded_at <= FAVOURITES_STALE and not force:
                return
            fav.inflight = self.request("favourite_playlists", force=False, lane="lookahead")
            return
        if fav.state in ("none", "error", "signin", "loading"):
            fav.state = "loading" if fav.state in ("none", "error") else fav.state
            fav.inflight = self.request("favourite_playlists", force=True, lane="library")

    def _favourites_result(self, effect, result, error):
        fav = self.favourites
        if fav.inflight == effect["request"]:
            fav.inflight = None
        now = self.clock()
        if error is not None:
            outcome = getattr(error, "outcome", None)
            status = getattr(error, "status", None)
            if outcome == "signin_expired" or status in (401, 403):
                if not fav.items:
                    fav.state = "signin"
                fav.loaded_at = None  # stale
                fav.retry_at = now + FAVOURITES_BACKOFF[0]
            elif outcome == "rate_limited" or status == 429:
                fav.retry_at = now + FAVOURITES_BACKOFF[min(fav.backoff, len(FAVOURITES_BACKOFF) - 1)]
                fav.backoff += 1
                if not fav.items:
                    fav.state = "error"
            else:
                fav.retry_at = now + FAVOURITES_BACKOFF[min(fav.backoff, len(FAVOURITES_BACKOFF) - 1)]
                fav.backoff += 1
                if not fav.items:
                    fav.state = "error"
            fav.rev += 1
            self._favourites_changed()
            return
        if not isinstance(result, list):
            return
        fav.backoff = 0
        fav.items = [dict(item) for item in result if isinstance(item, dict)]
        fav.state = "ready" if fav.items else "empty"
        fav.loaded_at = now
        fav.rev += 1
        self._favourites_changed()

    def _favourites_changed(self):
        if self.screen.mode != "explorer":
            return
        explorer = self.screen.explorer
        if explorer.source == "favourites":
            focus = self._favourites_index()
            explorer.index_by_source["favourites"] = focus
            if focus != self.screen.index or self._list_count() - 1 != self.bounds()[1]:
                self._request_passive("favourites refresh")
            self._request_playlist_meta()
        self._explorer_push_highlight(data=True)

    def _request_playlist_meta(self):
        """Count, mosaic and accent of the playlists near the focus (lookahead lane)."""
        fav = self.favourites
        if self.screen.mode != "explorer" or self.screen.explorer.source != "favourites":
            return
        index = self.screen.index
        for position in range(max(0, index - 2), min(len(fav.items), index + 3)):
            item = fav.items[position]
            playlist = _item_id(item)
            focused = position == index
            known = fav.meta.get(playlist)
            if playlist in fav.meta_inflight or (known is not None and (not focused or known.get("duration_ms") is not None)):
                continue
            fav.meta_inflight[playlist] = self.request("playlist_meta", playlist_id=playlist, duration=focused,
                                                       last_modified=item.get("last_modified"))

    def _meta_result(self, effect, result, error):
        fav = self.favourites
        playlist = effect.get("playlist_id")
        if fav.meta_inflight.get(playlist) == effect["request"]:
            del fav.meta_inflight[playlist]
        if error is not None or not isinstance(result, dict):
            return
        merged = dict(fav.meta.get(playlist) or {})
        merged.update({key: value for key, value in result.items() if value is not None or key not in merged})
        fav.meta[playlist] = merged
        fav.rev += 1
        if self.screen.mode == "explorer":
            self._explorer_push_highlight(data=True)

    def _explorer_window(self, source, index):
        """Descriptors for the preload window (+-12 + 4 ahead): (items, items_first)."""
        total = self._source_count(source)
        first = max(0, index - EXPLORER_PRELOAD_BEHIND)
        last = min(total, index + EXPLORER_PRELOAD_AHEAD + 1)
        items = []
        for position in range(first, last):
            item = self._source_item(source, position)
            descriptor = _descriptor(item)
            if descriptor is not None and source == "favourites":
                meta = self.favourites.meta.get(_item_id(item))
                if meta:
                    descriptor.update({key: meta[key] for key in ("count", "mosaic", "art_state", "first_art",
                                                                  "duration_ms", "empty") if key in meta})
                    descriptor["accent"] = self._accent("playlist", item)
            elif descriptor is not None:
                descriptor["accent"] = self._accent("recent", item)
            items.append(descriptor)
        return items, first

    def _explorer_payload(self, source, index):
        items, first = self._explorer_window(source, index)
        state = self._source_state(source)
        total = self._source_count(source)
        return {"source": source, "index": index, "count": total if state != "loading" else None,
                "items": items, "items_first": first, "items_rev": self._source_rev(source), "state": state}

    def _source_rev(self, source):
        return self.recent.rev if source == "recent" else self.favourites.rev

    def _explorer_sent_marker(self, source, index):
        _items, first = self._explorer_window(source, index)
        state = self._source_state(source)
        return {"first": first, "rev": self._source_rev(source), "state": state,
                "count": self._source_count(source) if state != "loading" else None}

    def _explorer_push_highlight(self, bump=0, data=False):
        explorer = self.screen.explorer
        source = explorer.source
        index = self.screen.index
        marker = self._explorer_sent_marker(source, index)
        payload = {"index": index, "control_id": self.control_id, "bump": bump}
        sent = explorer.sent
        if marker["first"] != sent.get("first") or marker["rev"] != sent.get("rev"):
            items, first = self._explorer_window(source, index)
            payload.update(items=items, items_first=first, items_rev=marker["rev"])
        if marker["state"] != sent.get("state") or marker["count"] != sent.get("count"):
            payload.update(state=marker["state"], count=marker["count"])
        if data and len(payload) == 3:
            return  # nothing new to push
        explorer.sent = marker
        self._present("explorer_highlight", **payload)

    def _explorer_moved(self):
        explorer = self.screen.explorer
        explorer.index_by_source[explorer.source] = self.screen.index
        if explorer.source == "recent":
            self._recent_moved()
        else:
            item = self._source_item("favourites", self.screen.index)
            if item is not None:
                self.favourites.focus_id = _item_id(item)
            self._request_playlist_meta()
        self._explorer_push_highlight()

    def _press_explorer(self, logical, now):
        explorer = self.screen.explorer
        if logical == 0:
            self._close_explorer("back")
        elif logical in (1, 2):
            target = "recent" if logical == 1 else "favourites"
            if target == explorer.source:
                return  # the active tab: ignored silently
            self._tab_switch(target, now)
        elif logical == 3:
            item = self._source_item(explorer.source, self.screen.index)
            if item is None:
                return
            kind = "playlist" if explorer.source == "favourites" else self._item_kind(item)
            accent = self._accent("playlist" if explorer.source == "favourites" else "recent", item)
            self._dispatch_start(item, kind, accent, "explorer", now)
            explorer.play_until = now + OVERLAY_PLAY_CLOSE
            self._present("explorer_close", t0=now, reason="play", close_at_ms=OVERLAY_PLAY_CLOSE_MS)
            self._schedule(now + OVERLAY_PLAY_CLOSE, "overlay play",
                           lambda at=now + OVERLAY_PLAY_CLOSE: self._overlay_play_home(at))

    def _tab_switch(self, target, now):
        explorer = self.screen.explorer
        explorer.index_by_source[explorer.source] = self.screen.index
        if target == "favourites":
            index = self._favourites_index()
            self._favourites_ensure(now)
        else:
            index = explorer.index_by_source.get("recent", 0)
        explorer.index_by_source[target] = index
        explorer.swap_until = now + TAB_SWAP
        explorer.swap_to = target
        self._present("explorer_source", t0=now, **self._explorer_payload(target, index))
        explorer.sent = self._explorer_sent_marker(target, index)

        def switch():
            explorer.source = target
            explorer.swap_to = None
            self._reenter("tab switch", index=index)
            if target == "favourites":
                self._request_playlist_meta()
            else:
                self._recent_moved()
        self._schedule(now + TAB_SWAP, "tab switch", switch)

    def _overlay_play_home(self, closed_at=None):
        """t0 + 380: the overlay has closed; the knob goes Home with `Starting…` (section 5.3.5)."""
        if self.start is not None:
            self.start.closed_at = self.clock() if closed_at is None else closed_at
        self._new_screen("home", self.display_volume, "overlay play")

    # ------------------------------------------------------------------ starts (sections 8, 9.2)
    @staticmethod
    def _item_kind(item):
        kind = item.get("kind", "")
        return {"library-albums": "album", "library-playlists": "playlist",
                "library-songs": "song"}.get(kind, kind or "album")

    def _drop_seek_follow_up(self):
        """K3 C5-77: a start drops a Seek follow-up still waiting after Seek was left, as a track
        change drops a pending target (C5-47): never sent; the in-flight jump still resolves first."""
        seek = self._seek_bg
        if seek is None:
            return
        seek.due = None
        seek.dropped = True
        seek.target_s = seek.acked_s if seek.acked_s is not None else seek.target_s
        if seek.inflight is not None:
            with self._seek_lock:        # a job still queued reads no newer target
                self._seek_targets[seek.inflight] = seek.target_s

    def _dispatch_start(self, item, kind, accent, source, now):
        name = item.get("title", "")
        self._drop_seek_follow_up()
        request = self.request("play_items", item=deepcopy(_descriptor_resource(item)), name=name, accent=accent,
                               source=source, lenient=kind == "playlist", item_kind=kind,
                               expected_group_revision=self.state["group_revision"])
        self.start = StartPending(request, kind, name, accent, source, self._start_closed_at(source, now),
                                  _item_id(item))
        self.notice = ""
        return request

    @staticmethod
    def _start_closed_at(source, now):
        """StartPending.closed_at: an overlay start closes its overlay at t0 + 380 (section 5.3.5
        step 4), so its exit toast is due at max(t0 + 380 + 360, result) even when the result
        lands first (section 12.3); a Recent start has no overlay (the press time)."""
        return now + OVERLAY_PLAY_CLOSE if source in ("explorer", "upnext") else now

    def _press_recent(self, logical, now):
        if logical == 0:
            self._go_home("back")
        elif logical == 1:
            self._open_explorer(now)
        elif logical == 2:
            item = self.recent.item(self.screen.index)
            self._dispatch_play_next(item)
        elif logical == 3:
            item = self.recent.item(self.screen.index)
            self._dispatch_start(item, self._item_kind(item), self._accent("recent", item), "recent", now)
            self._new_screen("home", self.display_volume, "start")

    def _start_result(self, effect, result, error):
        start = self.start
        if start is None or start.request != effect["request"]:
            return self._apply_result_state(effect, result, error)
        self.start = None
        now = self.clock()
        overlay = start.source in ("explorer", "upnext")
        if error is not None:
            outcome = getattr(error, "outcome", None) or "start_failed"
            if self._discarded(error):
                return
            if outcome == "group_changed":
                self._feedback("err")
                self._group_changed_copy()
                return
            blocked = outcome == "album_blocked"
            self._feedback("err")
            self._set_transient("knob.status.album_blocked" if blocked else "knob.status.start_failed",
                                tone="error", ms=START_FAIL_STATUS)
            if getattr(error, "unavailable", False) and start.source == "recent":
                for item in self.recent.items:
                    if _item_id(item) == start.item_id:
                        item["available"], item["reason"] = False, str(error)
                        self.recent.rev += 1
            toast = "toast.start.album_blocked" if blocked else "toast.start.failed"
            fields = {"album": start.name} if blocked else {"name": start.name}
            if overlay:
                self._exit_toast(toast, start.closed_at, **fields)
            else:
                self._toast(toast, **fields)
            if getattr(error, "partial", False):
                self.notice = str(error)
            return
        result = dict(result or {})
        info = result.pop("_start", None) or {}
        result.pop("_final_song_ids", None)
        self._state(result, enter=False)
        if self.confirmed_playing() is not True:
            self._album_start_until = now + ALBUM_START_HOLD_SECONDS
        self._feedback("ok", moment="started", color=start.accent)
        k, n, u = _int(info.get("k"), 0), _int(info.get("n"), 0), _int(info.get("u"), 0)
        if start.kind == "playlist" and u > 0 and n:
            self._set_transient("knob.status.partial", ms=PARTIAL_STATUS, k=k, n=n)
            toast, fields = ("toast.start.partial_one" if u == 1 else "toast.start.partial"), {"k": k, "n": n, "u": u}
        else:
            toast, fields = "toast.start.ok", {"name": start.name}
        if overlay:
            self._exit_toast(toast, start.closed_at, **fields)
        else:
            self._toast(toast, **fields)

    # ------------------------------------------------------------------ Play next (section 9.3)
    def _dispatch_play_next(self, item):
        request = self.request("play_next", item=deepcopy(_descriptor_resource(item)), name=item.get("title", ""),
                               accent=self._accent("recent", item), item_kind=self._item_kind(item),
                               expected_group_revision=self.state["group_revision"],
                               expected_track_id=self.state.get("track_id"))
        self.play_next_job = PlayNextJob(request, dict(item), item.get("title", ""), self._accent("recent", item))
        self.notice = ""

    def progress(self, request, payload):
        """Section 10.3: progress of a running job (a stale request is ignored)."""
        if request not in self.pending or not isinstance(payload, dict):
            return
        job = self.play_next_job
        if job is not None and job.request == request:
            phase = payload.get("phase")
            if phase in ("resolving", "inserting"):
                job.phase = phase
            if type(payload.get("n")) is int:
                job.n = payload["n"]
            if type(payload.get("k")) is int:
                job.k = payload["k"]
            return
        shuffle = self.shuffle_job
        if shuffle is not None and shuffle.request == request and payload.get("phase") == "accepted":
            if not shuffle.accepted:
                shuffle.accepted = True
                self._note_shuffle_record(shuffle)
                self._feedback("ok", moment="shuffle")
                self._set_transient("knob.meta.shuffle.on" if shuffle.on else "knob.meta.shuffle.off",
                                    ms=FEEDBACK_META)

    def _playnext_result(self, effect, result, error):
        job = self.play_next_job
        mine = job is not None and job.request == effect["request"]
        if effect["kind"] == "move_next":
            if self.move_next_request == effect["request"]:
                self.move_next_request = None
            mine = True
        if not mine:
            return self._apply_result_state(effect, result, error)
        name = job.name if job is not None else ""
        self.play_next_job = None if effect["kind"] == "play_next" else self.play_next_job
        overlay = self._overlay_open()
        if error is not None:
            if self._discarded(error):
                return
            outcome = getattr(error, "outcome", None) or "nothing_added"
            self._feedback("err")
            meta = {"partial": "knob.meta.playnext.partial", "song_changed": "knob.meta.playnext.song_changed",
                    "sonos_shuffle_on": "knob.meta.playnext.shuffle",
                    "group_changed": "knob.meta.group_changed",
                    "sonos_unavailable": "knob.meta.sonos_unavailable",
                    "signin_expired": "knob.meta.signin_expired"}.get(outcome, "knob.meta.playnext.nothing")
            toast = {"partial": "toast.playnext.partial", "song_changed": "toast.playnext.song_changed",
                     "sonos_shuffle_on": "toast.playnext.shuffle"}.get(outcome, "toast.playnext.nothing")
            if outcome == "not_queue_source":
                cls = getattr(error, "source", None) or self.source()
                cls = cls if cls in ("airplay", "radio", "linein", "none") else "none"
                meta = "knob.meta.playnext." + cls
                toast = "toast.playnext.none" if cls == "none" else "toast.playnext.not_queue"
            self._set_transient(meta, tone="error", ms=FAIL_META)
            if effect["kind"] == "play_next" and not overlay:
                self._toast(toast, album=name)
            return
        result = dict(result or {})
        result.pop("_inserted", None)
        self._apply_state_result(result)
        self._feedback("ok", moment="queued")
        self._set_transient("knob.meta.playnext.ok", ms=QUEUED_META)
        if effect["kind"] == "play_next" and not overlay:
            self._toast("toast.playnext.ok", album=name)
        self._our_queue_changed()

    # ------------------------------------------------------------------ Tracks (section 5.4)
    def _enter_tracks(self, index, cause):
        self._new_screen("tracks", index, cause)
        self._neighbours_read()

    def _neighbours_read(self):
        if self.screen.mode not in ("tracks",) or self.source() != "queue":
            return
        P, T = self._position()
        key = (self.state.get("queue_revision"), P)
        if key in self._neighbours or self._neighbours_request in self.pending:
            return
        self._neighbours_request = self.request("queue_window", start=max(0, P - 2), count=3, purpose="tracks",
                                                key=list(key))
        if P <= 1 and self.state.get("repeat") == "all" and T > 3:
            self.request("queue_window", start=T - 1, count=1, purpose="tracks_last", key=list(key))

    def _neighbours_result(self, effect, result, error):
        if error is not None or not isinstance(result, dict):
            return
        key = tuple(effect.get("key") or ())
        entry = self._neighbours.setdefault(key, {})
        for row in result.get("rows") or ():
            if isinstance(row, dict) and type(row.get("row")) is int:
                entry[row["row"]] = row.get("title", "")
        if len(self._neighbours) > 8:
            for old in list(self._neighbours)[:-8]:
                del self._neighbours[old]

    def _press_tracks(self, logical, now):
        if logical == 0:
            self._go_home("back")
        elif logical == 1:
            self._open_upnext(now)
        elif logical == 2:
            self._enter_seek(now)
        elif logical == 3:
            index = self.screen.index
            end = self._queue_end(index)
            if end is not None:
                self._set_transient("knob.meta.skip." + end, ms=FEEDBACK_META)
                self._feedback("err")
                return
            direction = {0: "previous", 2: "next"}[index]
            self.notice = ""
            self.command_request = self.request("transport", direction=direction,
                                                expected_group_revision=self.state["group_revision"],
                                                expected_track_id=self.state.get("track_id"), index=index)

    def _transport_result(self, effect, result, error):
        if self.command_request == effect["request"]:
            self.command_request = None
        home_command = effect.get("direction") in ("play", "pause")
        if error is not None:
            if self._discarded(error):
                return
            self.notice = str(error)
            self._feedback("err")
            if home_command:
                self._paused_since = None
            return
        result = dict(result or {})
        if self._obsolete_group(effect, result):
            return
        reenter = self._state(result, enter=False)
        if home_command:
            if self.state["online"] and self.state.get("playback") == "PAUSED_PLAYBACK":
                self._paused_since = self.clock()
                self._paused_idle_cancelled = False
            if reenter and self.screen.mode == "home":
                self._enter("volume")
            return
        skip = SKIP_DIRECTIONS.get(effect.get("direction"), 0)
        self._feedback("ok", skip)
        self._toast("toast.skip.next" if skip == 1 else "toast.skip.prev", title=self.state.get("title", ""))
        if self.screen.mode == "tracks" and effect.get("view_id") == self.screen.view_id:
            self.screen.index = 1
            self._reenter("skip ok", index=1)
        elif reenter and self.screen.mode == "home":
            self._enter("volume")

    # ------------------------------------------------------------------ Seek (section 5.5)
    def _enter_seek(self, now):
        duration = _int(self.state.get("duration_s"), 0) or 1
        position = _int(self.state.get("position_s"), 0)
        if self.state.get("playback") == "PLAYING":
            position += int(max(0.0, now - self._state_at))
        p = min(position, duration)
        end = max(0, duration - SEEK_MARGIN_S)
        p1 = min(p, end)
        n0 = math.ceil(p1 / SEEK_STEP_S)
        maximum = n0 + math.ceil((end - p1) / SEEK_STEP_S)
        seek = SeekState(D=duration, p0=p1, n0=n0, max=maximum, target_s=p1, idle_due=now + SEEK_IDLE,
                         track_id=self.state.get("track_id"), acked_s=p1)
        self._new_screen("seek", n0, "seek", seek=seek, parent_index=1)

    def _seek_busy(self):
        seek = self.screen.seek if self.screen.mode == "seek" else None
        return bool(seek and seek.busy)

    def _seek_tick(self, now):
        for seek in (self.screen.seek if self.screen.mode == "seek" else None, self._seek_bg):
            if seek is None:
                continue
            if seek.due is not None and now >= seek.due and seek.inflight is None:
                if seek.target_s != seek.acked_s and not seek.dropped:
                    self._send_seek(seek)
                else:
                    # Nothing waits: the last jump sent is the target (or it was dropped), so the
                    # burst is over and `seek_busy` ends with it (C5-68).
                    seek.due = None
                    seek.landed_s = None
        seek = self.screen.seek if self.screen.mode == "seek" else None
        if seek is not None and not seek.busy and seek.due is None and now >= seek.idle_due:
            self._leave_seek(flush=False, drop=False)
            self._enter_tracks(1, "seek idle")
        if self._seek_bg is not None and self._seek_bg.inflight is None and (
                self._seek_bg.due is None or self._seek_bg.target_s == self._seek_bg.acked_s):
            self._seek_bg = None

    def _send_seek(self, seek):
        seek.due = None
        seek.acked_s = seek.target_s
        request = self.request("seek", target_s=seek.target_s, expected_group_revision=self.state["group_revision"],
                               expected_track_id=seek.track_id)
        seek.inflight = request
        with self._seek_lock:
            self._seek_targets[request] = seek.target_s

    def _leave_seek(self, flush=True, drop=False):
        """Explicit exits flush a debouncing target (C5-68: while a jump is in flight the one
        follow-up target is kept for when it lands); unmade exits drop it (C5-47)."""
        seek = self.screen.seek
        if seek is None:
            return
        seek.left = True
        if drop:
            seek.due = None
            seek.dropped = True
            seek.target_s = seek.acked_s if seek.acked_s is not None else seek.target_s
            if seek.inflight is not None:
                with self._seek_lock:   # a job still queued reads no newer target
                    self._seek_targets[seek.inflight] = seek.target_s
        elif flush and seek.target_s != seek.acked_s:
            if seek.inflight is None:
                self._send_seek(seek)
            else:
                seek.due = self.clock()
        if seek.inflight is not None or (seek.due is not None and seek.target_s != seek.acked_s):
            self._seek_bg = seek

    def _press_seek(self, logical, now):
        if logical in (0, 2):
            self._leave_seek(flush=True)
            self._enter_tracks(1, "seek off")
        elif logical == 1:
            self._leave_seek(flush=True)
            self._enter_tracks(1, "seek off")
            if self._tracks_upnext_code() is None:
                self._open_upnext(now)

    def _seek_result(self, effect, result, error):
        seek = None
        for candidate in (self.screen.seek if self.screen.mode == "seek" else None, self._seek_bg):
            if candidate is not None and candidate.inflight == effect["request"]:
                seek = candidate
        with self._seek_lock:
            self._seek_targets.pop(effect["request"], None)
            read = self._seek_read.pop(effect["request"], None)
        now = self.clock()
        if seek is None:
            if error is not None and not self._discarded(error) and getattr(error, "outcome", None) == "not_confirmed":
                self._feedback("err")
            if error is None:
                self._apply_state_result(result)
            return
        seek.inflight = None
        if error is not None:
            if self._discarded(error):
                seek.landed_s = None
                return
            outcome = getattr(error, "outcome", None) or "not_confirmed"
            seek.landed_s = None
            seek.due = None
            seek.acked_s = seek.target_s  # a pending follow-up target is dropped with the failure
            if outcome == "song_changed":
                if not seek.left:
                    self._leave_seek(flush=False, drop=True)
                    self._enter_tracks(1, "seek song changed")
                return
            self._feedback("err")
            if not seek.left:
                seek.fail_until = now + SEEK_FAIL_LINE
                seek.idle_due = now + SEEK_IDLE
            return
        result = dict(result or {})
        applied = result.pop("_applied_seek", effect.get("target_s"))
        result.pop("_seek_kept_state", None)
        # The landed target is the one this job read when it started (a job still queued picks up
        # the newest turn), not the one at send time: a later turn back to the sent value must
        # still be sent (section 5.5.4, C5-68). The adapter's clamp of it (`_applied_seek`) is
        # only the fallback when the read is unknown.
        if type(read) is int:
            landed = read
        elif type(applied) is int:
            landed = applied
        else:
            landed = seek.acked_s
        seek.acked_s = landed
        seek.landed_s = landed
        if seek.dropped:
            seek.target_s = landed   # a dropped target is never sent afterwards (C5-47)
        self._apply_state_result(result)
        if seek.target_s == seek.landed_s:
            seek.landed_s = None
            seek.due = None
        elif seek.due is None:
            seek.due = now   # the one follow-up jump, still 250 ms after the last detent
        if not seek.left:
            seek.idle_due = now + SEEK_IDLE

    # ------------------------------------------------------------------ Up next (section 5.6)
    def _upnext_count(self):
        upnext = self.screen.upnext
        if upnext is None:
            return 0
        if upnext.card:
            return upnext.P + 1
        return upnext.T

    def _upnext_on_card(self):
        upnext = self.screen.upnext
        return bool(upnext and upnext.card and self.screen.index == upnext.P)

    def _upnext_focus_row(self):
        upnext = self.screen.upnext
        if upnext is None or self._upnext_on_card():
            return None
        return upnext.rows.get(self.screen.index + 1)

    def _upcoming_loaded(self):
        upnext = self.screen.upnext
        if upnext is None:
            return False
        return all(row in upnext.rows for row in range(upnext.P + 1, upnext.T + 1))

    def _playnext_offsets(self):
        """0-based offsets (from P+1) of the upcoming rows the ledger attributes to Play next."""
        upnext = self.screen.upnext
        if upnext is None:
            return []
        return [row - upnext.P - 1 for row in range(upnext.P + 1, upnext.T + 1)
                if upnext.rows.get(row, {}).get("segment") == "playnext"]

    def _open_upnext(self, now):
        P, T = self._position()
        card = self.sonos_shuffle()
        upnext = UpNextState(P=P, T=T, card=card, regime="sonos" if card or T - P > COMPANION_SHUFFLE_MAX else "companion",
                             revision=str(self.state.get("queue_revision", "")))
        parent = _clamp(self.screen.index, 0, 2) if self.screen.mode == "tracks" else 1
        self._new_screen("upnext", max(0, P - 1), "upnext open", upnext=upnext, parent_index=parent)
        upnext.reads.append((max(0, P - 1 - 10), UPNEXT_WINDOW, "upnext"))
        shuffle_read = self._upcoming_read(max(0, P - 1 - 10))
        if shuffle_read is not None:
            upnext.reads.append(shuffle_read)
        self._present("upnext_open", t0=now, **self._upnext_payload(), control_id=self.control_id, control_min=0,
                      reduced_motion=self.reduced_motion, foreground_hwnd=None)
        self._upnext_next_read()

    def _upnext_payload(self, rows=None):
        upnext = self.screen.upnext
        return {"rows": self._upnext_rows_payload(rows), "now": upnext.P - 1, "focus": self.screen.index,
                "count": self._upnext_count(), "card": {"n": max(0, upnext.T - upnext.P)} if upnext.card else None,
                "context": self._upnext_context(), "shuffle": self._shuffle_token(),
                "likes_known": self._likes_known(), "loading": upnext.loading}

    def _shuffle_token(self):
        if self.sonos_shuffle():
            return "sonos"
        if self.state.get("companion_shuffle"):
            return "companion"
        return "off"

    def _likes_known(self):
        upnext = self.screen.upnext
        rows = [row for row in upnext.rows.values() if row.get("song_id") and row.get("catalog") is not False]
        return bool(rows) and all(row.get("liked") is not None for row in rows)

    def _row_role(self, number):
        P = self.screen.upnext.P
        if number < P:
            return "played"
        if number == P:
            return "now"
        if number == P + 1:
            return "next"
        return "upcoming"

    def _upnext_rows_payload(self, rows=None):
        upnext = self.screen.upnext
        numbers = sorted(upnext.rows) if rows is None else rows
        out = []
        for number in numbers:
            row = upnext.rows.get(number)
            if row is None:
                continue
            entry = _descriptor(row)
            entry["role"] = self._row_role(number)
            entry["accent"] = self._accent("row", row)
            out.append(entry)
        return out

    def _upnext_context(self):
        upnext = self.screen.upnext
        rows = [upnext.rows[number] for number in sorted(upnext.rows)]
        try:
            context = self.ledger.classify(rows, total=upnext.T)
        except Exception:
            _log.exception("Queue ledger classification failed")
            return {"kind": "foreign", "title": "Sonos queue", "sub": ""}
        for number, role in zip(sorted(upnext.rows), context.roles):
            upnext.rows[number]["segment"] = role
        upnext.context = context.presenter()
        return upnext.context

    def _upnext_next_read(self):
        upnext = self.screen.upnext
        if upnext is None or upnext.read_inflight is not None or not upnext.reads:
            return
        start, size, purpose = upnext.reads.pop(0)
        upnext.read_inflight = self.request("queue_window", start=start, count=min(100, max(1, size)),
                                            purpose=purpose)

    def _upnext_refill(self):
        upnext = self.screen.upnext
        if upnext is None or upnext.loading or not upnext.rows:
            return
        focus_row = self.screen.index + 1
        if focus_row > upnext.T:
            return
        low, high = min(upnext.rows), max(upnext.rows)
        near_low = focus_row - low < UPNEXT_EDGE and low > 1
        near_high = high - focus_row < UPNEXT_EDGE and high < upnext.T
        missing = focus_row not in upnext.rows
        if not (near_low or near_high or missing):
            return
        start = max(0, self.screen.index - 10)
        spec = (start, UPNEXT_WINDOW, "upnext")
        upnext.reads = [read for read in upnext.reads if read[2] != "upnext"] + [spec]  # newest need wins
        self._upnext_next_read()

    def _window_result(self, effect, result, error):
        purpose = effect.get("purpose")
        if purpose in ("tracks", "tracks_last"):
            if self._neighbours_request == effect["request"]:
                self._neighbours_request = None
            return self._neighbours_result(effect, result, error)
        upnext = self.screen.upnext if self.screen.mode == "upnext" else None
        if upnext is None or effect.get("view_id") != self.screen.view_id:
            return
        if upnext.read_inflight == effect["request"]:
            upnext.read_inflight = None
        if error is not None or not isinstance(result, dict):
            if upnext.loading:
                # The whole queue is still loading: ask again in a second (the 60 s idle close
                # bounds it); the frame keeps `Loading queue…` with the Working comet.
                spec = (effect.get("start", 0), effect.get("count", UPNEXT_WINDOW), effect.get("purpose", "upnext"))

                def retry(spec=spec, upnext=upnext):
                    upnext.reads.insert(0, spec)
                    self._upnext_next_read()
                self._schedule(self.clock() + 1.0, "upnext retry", retry)
            self._upnext_next_read()
            return
        first_window = upnext.loading
        upnext.loading = False
        total = _int(result.get("total"), upnext.T)
        new_rows = []
        for row in result.get("rows") or ():
            if not isinstance(row, dict) or type(row.get("row")) is not int:
                continue
            number = row["row"]
            existing = upnext.rows.get(number) or {}
            merged = dict(row)
            for key in ("catalog", "liked", "album", "track_number", "art_template", "art_max", "art_bg",
                        "art_ink", "accent", "url", "release_year", "disc_number"):
                if key in existing and existing.get("signature") == row.get("signature"):
                    merged.setdefault(key, existing[key])
            merged.setdefault("liked", None)
            if not merged.get("song_id"):
                merged["catalog"] = False
            else:
                merged.setdefault("catalog", None)
            upnext.rows[number] = merged
            new_rows.append(number)
        if total != upnext.T and not upnext.card:
            upnext.T = total
        upnext.revision = str(result.get("update_id", upnext.revision))
        self._upnext_enrich(new_rows)
        now = self.clock()
        if upnext.identity is not None:
            self._upnext_restore_identity()
        if upnext.pending_regime is not None:
            regime, upnext.pending_regime = upnext.pending_regime, None
            self._present("upnext_rows", t0=now, reason="shuffle", **self._upnext_payload())
            upnext.swap_until = now + SHUFFLE_SWAP
            self._schedule(now + SHUFFLE_SWAP, "sonos shuffle off", lambda: self._reenter("sonos shuffle off"))
        else:
            reason = "data" if first_window or effect.get("purpose") != "requeue" else "queue_changed"
            self._present("upnext_rows", t0=now, reason=reason, **{**self._upnext_payload(new_rows)})
        self._upnext_next_read()

    def _upnext_enrich(self, numbers):
        upnext = self.screen.upnext
        ids = []
        for number in numbers:
            song = upnext.rows[number].get("song_id")
            if song and song not in upnext.enriched and song not in ids:
                ids.append(str(song))
        if not ids:
            return
        upnext.enriched.update(ids)
        self.request("catalog_songs", ids=ids[:300])
        self.request("ratings", ids=ids[:100], purpose="rows")

    def _enrich_result(self, effect, result, error):
        upnext = self.screen.upnext if self.screen.mode == "upnext" else None
        if effect["kind"] == "ratings" and effect.get("purpose") == "late_check":
            return self._late_check_result(effect, result, error)
        if upnext is None:
            return
        ids = [str(v) for v in effect.get("ids") or ()]
        if error is not None or not isinstance(result, dict):
            if effect["kind"] == "ratings" and ids:
                if not set(ids) <= upnext.ratings_failed:
                    upnext.ratings_failed.update(ids)
                    upnext.enriched.difference_update(ids)  # retried once with the next window read
            return
        changed = []
        for number, row in upnext.rows.items():
            song = str(row.get("song_id") or "")
            if song not in ids:
                continue
            if effect["kind"] == "catalog_songs":
                found = result.get(song) or {}
                if found.get("catalog"):
                    for key in ("album", "track_number", "disc_number", "duration_s", "art_template", "art_max",
                                "art_bg", "art_ink", "url", "release_year"):
                        if found.get(key) is not None:
                            row[key] = found[key]
                    row["accent"] = found.get("accent", row.get("accent", 0))
                    row["catalog"] = True
                else:
                    row["catalog"] = False
            else:
                row["liked"] = result.get(song) == 1
            changed.append(number)
        if changed:
            self._present("upnext_rows", t0=self.clock(), reason="data", **self._upnext_payload(sorted(changed)))

    def _upnext_changes(self, before_revision, before_position):
        """Section 5.6.8: a song ended (roles live) or the queue changed (re-read around the focus)."""
        upnext = self.screen.upnext
        P, T = self._position()
        revision = str(self.state.get("queue_revision", ""))
        if self.source() != "queue":
            self.close_overlay("source")
            return
        position_changed = P != upnext.P
        revision_changed = revision != before_revision and revision != upnext.revision
        if self._exclusive_running() and revision_changed:
            revision_changed = False  # our own job's edits wait for its completion (section 1.1)
        if position_changed:
            upnext.P = P
            self._present("upnext_rows", t0=self.clock(), reason="data", **self._upnext_payload([]))
        if revision_changed:
            self._upnext_requeue(T)

    def _upnext_requeue(self, T=None):
        upnext = self.screen.upnext
        focus_row = upnext.rows.get(self.screen.index + 1)
        if focus_row is not None:
            signature = focus_row.get("signature")
            occurrence = sum(1 for number in sorted(upnext.rows) if number <= self.screen.index + 1
                             and upnext.rows[number].get("signature") == signature)
            upnext.identity = (signature, occurrence)
        if T is None:
            T = self._position()[1]
        upnext.T = T
        upnext.card = self.sonos_shuffle()
        upnext.rows = {}
        upnext.revision = str(self.state.get("queue_revision", ""))
        start = max(0, self.screen.index - 10)
        upnext.reads = [(start, UPNEXT_WINDOW, "requeue")]
        shuffle_read = self._upcoming_read(start)
        if shuffle_read is not None:
            upnext.reads.append(shuffle_read)
        upnext.read_inflight = None
        self._upnext_next_read()

    def _upcoming_read(self, window_start):
        """The rows P+1..T read (section 5.6.1, section 9.7.1) that the companion shuffle plan
        needs (section 9.5.2), when U <= 60 and the 21-row window from `window_start` (0-based)
        does not cover them; else None. On open and after every re-read, so Shuffle never stays
        dimmed `loading` once the rows were dropped."""
        upnext = self.screen.upnext
        P, T = upnext.P, upnext.T
        U = T - P
        if upnext.card or not 0 < U <= COMPANION_SHUFFLE_MAX:
            return None
        if window_start <= P and window_start + UPNEXT_WINDOW >= T:
            return None
        return (P, U, "shuffle")

    def _upnext_restore_identity(self):
        upnext = self.screen.upnext
        signature, occurrence = upnext.identity
        seen = 0
        target = None
        for number in sorted(upnext.rows):
            if upnext.rows[number].get("signature") == signature:
                seen += 1
                if seen == occurrence:
                    target = number - 1
                    break
        upnext.identity = None
        count_now = self._upnext_count()
        if target is None:
            target = _clamp(self.screen.index, 0, max(0, count_now - 1))
        if target != self.screen.index or self.bounds()[1] != max(0, count_now - 1):
            self.screen.index = target
            self._request_passive("upnext queue changed")

    def _exclusive_running(self):
        return self._busy_code() is not None

    def _our_queue_changed(self):
        """A Play next / shuffle / jump / move_next of ours completed: as a revision change."""
        if self.screen.mode == "upnext":
            self._upnext_requeue()

    def _press_upnext(self, logical, now):
        upnext = self.screen.upnext
        if logical == 0:
            self._close_upnext("back")
        elif logical == 1:
            self._shuffle_press(now)
        elif logical == 2:
            row = self._upnext_focus_row()
            if self.upnext_button3 == "playnext":
                self.move_next_request = self.request("move_next", row=row["row"],
                                                      expected_group_revision=self.state["group_revision"],
                                                      expected_update_id=upnext.revision, item=_descriptor(row))
                return
            self._like_press(row)
        elif logical == 3:
            row = self._upnext_focus_row()
            accent = self._accent("row", row)
            self._drop_seek_follow_up()
            self.request("jump", row=row["row"], name=row.get("title", ""), accent=accent,
                         expected_group_revision=self.state["group_revision"],
                         expected_track_id=self.state.get("track_id"), expected_update_id=upnext.revision)
            request = self.serial
            self.start = StartPending(request, "track", row.get("title", ""), accent, "upnext",
                                      self._start_closed_at("upnext", now), str(row.get("song_id") or ""))
            upnext.play_until = now + OVERLAY_PLAY_CLOSE
            self._present("upnext_close", t0=now, reason="play", close_at_ms=OVERLAY_PLAY_CLOSE_MS)
            self._schedule(now + OVERLAY_PLAY_CLOSE, "overlay play",
                           lambda at=now + OVERLAY_PLAY_CLOSE: self._overlay_play_home(at))

    def _like_press(self, row):
        upnext = self.screen.upnext
        if row.get("liked") is True:
            self._refuse(2, "unlike_unavailable")  # [r2.2] add-only, final (C5-67): no request
            return
        if self.music_signin_expired:
            self._set_transient("knob.meta.like.signin_expired", tone="error", ms=SIGNIN_META)
            self._feedback("err")
            upnext.armed_toast = "toast.like.signin_expired"
            return
        song = str(row.get("song_id"))
        self.like_inflight.add(song)
        self.request("like", song_id=song, row=row["row"])

    def _like_result(self, effect, result, error):
        song = str(effect.get("song_id"))
        self.like_inflight.discard(song)
        upnext = self.screen.upnext if self.screen.mode == "upnext" else None
        if error is not None:
            if self._discarded(error):
                return
            outcome = getattr(error, "outcome", None) or "failed"
            self._feedback("err")
            if outcome == "not_catalog":
                self._set_transient("knob.meta.like.not_catalog", ms=REASON_META)
                if upnext is not None:
                    changed = [n for n, row in upnext.rows.items() if str(row.get("song_id")) == song]
                    for number in changed:
                        upnext.rows[number]["catalog"] = False
                    if changed:
                        self._present("upnext_rows", t0=self.clock(), reason="data",
                                      **self._upnext_payload(sorted(changed)))
            elif outcome == "signin_expired":
                self.music_signin_expired = True
                self._set_transient("knob.meta.like.signin_expired", tone="error", ms=SIGNIN_META)
                if upnext is not None:
                    upnext.armed_toast = "toast.like.signin_expired"
            else:
                self._set_transient("knob.meta.like.failed", tone="error", ms=LIKE_FAIL_META)
                if getattr(error, "late_check", False) or getattr(error, "confirm_timeout", False):
                    self._schedule(self.clock() + LIKE_LATE_CHECK, "like late check",
                                   lambda s=song: self.request("ratings", ids=[s], purpose="late_check"),
                                   any_screen=True)
            return
        if not (isinstance(result, dict) and result.get("liked") is True):
            return
        self._feedback("ok", moment="like")
        self._set_transient("knob.meta.like.on", ms=FEEDBACK_META)
        self.favourites.loaded_at = None  # Favorite Songs changed: the Favourites cache is stale (CF:15)
        if upnext is not None:
            changed = [n for n, row in upnext.rows.items() if str(row.get("song_id")) == song]
            for number in changed:
                upnext.rows[number]["liked"] = True
            if changed:
                self._present("upnext_rows", t0=self.clock(), reason="likes",
                              **{**self._upnext_payload([]), "rows": [{"row": n, "liked": True} for n in sorted(changed)]})

    def _late_check_result(self, effect, result, error):
        if error is not None or not isinstance(result, dict):
            return
        upnext = self.screen.upnext if self.screen.mode == "upnext" else None
        if upnext is None:
            return
        ids = [str(v) for v in effect.get("ids") or ()]
        changed = []
        for number, row in upnext.rows.items():
            song = str(row.get("song_id") or "")
            if song in ids and result.get(song) == 1 and row.get("liked") is not True:
                row["liked"] = True
                changed.append(number)
        if changed:
            self._present("upnext_rows", t0=self.clock(), reason="data", **self._upnext_payload(sorted(changed)))

    def _shuffle_press(self, now):
        upnext = self.screen.upnext
        P, T = self._position()
        U = max(0, T - P)
        active = self.shuffle_active()
        rev, track = self.state["group_revision"], self.state.get("track_id")
        if not active and U <= COMPANION_SHUFFLE_MAX:
            pn = self._playnext_offsets()
            rest = [offset for offset in range(U) if offset not in pn]
            self.rng.shuffle(rest)
            plan = pn + rest
            expected = [upnext.rows[P + 1 + offset].get("signature") for offset in range(U)]
            request = self.request("shuffle_reorder", on=True, plan=plan, playnext_offsets=pn, expected_rows=expected,
                                   expected_update_id=upnext.revision, expected_group_revision=rev,
                                   expected_track_id=track)
            # The record the adapter persists at acceptance: the base rows (every upcoming row but the
            # Play-next block) in their order now (K3 9.5.2 step 3).
            record = [expected[offset] for offset in range(U) if offset not in pn]
            self.shuffle_job = ShuffleJob(request, True, "companion", plan, pn, t0=now,
                                          record_order=record if all(isinstance(s, str) for s in record) else None)
            order = list(range(1, P + 1)) + [P + 1 + offset for offset in plan]
            self._present_reordered(now, order, "companion")
            upnext.swap_until = now + SHUFFLE_SWAP
            self._schedule(now + SHUFFLE_SWAP, "shuffle", lambda: self._reenter("shuffle", index=min(
                self._upnext_count() - 1, P)))
            return
        if not active:
            request = self.request("set_shuffle", on=True, expected_group_revision=rev)
            self.shuffle_job = ShuffleJob(request, True, "sonos", t0=now)
            return
        if self.sonos_shuffle():
            request = self.request("set_shuffle", on=False, expected_group_revision=rev)
            self.shuffle_job = ShuffleJob(request, False, "sonos", t0=now)
            return
        request = self.request("shuffle_reorder", on=False, playnext_song_ids=self.ledger.playnext_units(),
                               expected_update_id=upnext.revision, expected_group_revision=rev, expected_track_id=track)
        self.shuffle_job = ShuffleJob(request, False, "companion", t0=now)
        order = self._restore_order()
        self._present_reordered(now, order, "off")
        upnext.swap_until = now + SHUFFLE_SWAP
        self._schedule(now + SHUFFLE_SWAP, "shuffle", lambda: self._reenter("shuffle", index=min(
            self._upnext_count() - 1, P)))

    def _note_shuffle_record(self, job):
        """[P3] A companion Shuffle on was accepted: the adapter persisted its restore record."""
        if job.on and job.regime == "companion" and job.record_order:
            self.shuffle_record_order = list(job.record_order)

    def shuffle_record(self, order):
        """[P3] The runtime's read of the persisted restore record at start (K3 9.5.3, 9.5.5): the
        base rows' signature digests in the record's order, or None / [] when there is none. It lets
        the Shuffle-off preview match the restore after a companion restart."""
        if isinstance(order, (list, tuple)) and order and all(isinstance(s, str) and s for s in order):
            self.shuffle_record_order = list(order)
        else:
            self.shuffle_record_order = None

    def _restore_order(self):
        """The shuffle-off target order: Play-next rows first (current order), then the base rows in
        the order they had at Shuffle on, then anything else as it stands.

        [P3] (K3 9.5.3; the phase-2a review's recommended fix) When the restore record is known
        (`shuffle_record_order`, while the state reports `companion_shuffle`), the base rows are
        ranked by it, per signature in queue order as the adapter attributes them (sonos.py
        `_attribute_restore`, step 3), so the preview is the realised order also after a reorder
        without a ledger entry or on a queue the companion did not start (limitations 2 and 3).
        Otherwise by the ledger's start order (the P2a rule)."""
        upnext = self.screen.upnext
        P, T = upnext.P, upnext.T
        upcoming = [n for n in range(P + 1, T + 1) if n in upnext.rows]
        pn = [n for n in upcoming if upnext.rows[n].get("segment") == "playnext"]
        record = self.shuffle_record_order if self.state.get("companion_shuffle") else None
        if record:
            key, pool = "signature", list(record)
        else:
            key, pool = "song_id", list(self.ledger.base.song_ids) if self.ledger.base else []
        size = len(pool)
        ranked = []
        for n in upcoming:
            if n in pn:
                continue
            value = str(upnext.rows[n].get(key) or "")
            if value in pool:
                rank = pool.index(value)
                pool[rank] = None  # each entry once
            else:
                rank = size + n
            ranked.append((rank, n))
        return list(range(1, P + 1)) + pn + [n for _, n in sorted(ranked)]

    def _present_reordered(self, now, order, token):
        upnext = self.screen.upnext
        reordered = {}
        for position, number in enumerate(order, start=1):
            if number in upnext.rows:
                reordered[position] = dict(upnext.rows[number], row=position)
        rows = []
        for position in sorted(reordered):
            entry = _descriptor(reordered[position])
            entry["role"] = self._row_role(position)
            entry["accent"] = self._accent("row", reordered[position])
            rows.append(entry)
        payload = self._upnext_payload([])
        payload.update(rows=rows, focus=min(self._upnext_count() - 1, upnext.P), shuffle=token)
        self._present("upnext_rows", t0=now, reason="shuffle", **payload)

    def _shuffle_result(self, effect, result, error):
        job = self.shuffle_job
        if job is None or job.request != effect["request"]:
            return self._apply_result_state(effect, result, error)
        self.shuffle_job = None
        now = self.clock()
        if error is not None:
            if self._discarded(error):
                return
            outcome = getattr(error, "outcome", None) or "failed"
            self._feedback("err")
            copy_id = "knob.meta.shuffle.queue_changed" if outcome == "queue_changed" else "knob.meta.shuffle.failed"
            self._set_transient(copy_id, tone="error", ms=FAIL_META)
            if self.screen.mode == "upnext":
                self._upnext_requeue()
            return
        self._apply_state_result(dict(result or {}))
        if job.regime == "companion":
            if job.on:
                self._note_shuffle_record(job)
            else:
                self.shuffle_record_order = None      # restored: the adapter deleted the record
            if not job.accepted:
                self._feedback("ok", moment="shuffle")
                self._set_transient("knob.meta.shuffle.on" if job.on else "knob.meta.shuffle.off", ms=FEEDBACK_META)
            self._our_queue_changed()
            return
        # Sonos native regime: confirmed on the verified completion (t1).
        self._feedback("ok", moment="shuffle")
        self._set_transient("knob.meta.shuffle.sonos" if job.on else "knob.meta.shuffle.off", ms=FEEDBACK_META)
        if self.screen.mode != "upnext":
            return
        upnext = self.screen.upnext
        if job.on:
            upnext.card = True
            upnext.regime = "sonos"
            upnext.rows = {n: row for n, row in upnext.rows.items() if n <= upnext.P}
            self._present("upnext_rows", t0=now, reason="shuffle", **self._upnext_payload())
            upnext.swap_until = now + SHUFFLE_SWAP
            self._schedule(now + SHUFFLE_SWAP, "sonos shuffle on",
                           lambda: self._reenter("sonos shuffle on", index=self.screen.upnext.P))
        else:
            upnext.card = False
            upnext.regime = "companion" if upnext.T - upnext.P <= COMPANION_SHUFFLE_MAX else "sonos"
            upnext.pending_regime = "off"
            self._upnext_requeue()

    # ------------------------------------------------------------------ Windows (section 5.7)
    def _window_item(self, index):
        windows = self.screen.windows
        return windows.items[index] if windows and 0 <= index < len(windows.items) else None

    def _window_item_by_id(self, item_id):
        if item_id is None or self.screen.windows is None:
            return None
        for item in self.screen.windows.items:
            if item.get("id") == item_id:
                return item
        return None

    def _windows_open_result(self, effect, result, error):
        if error is not None or not isinstance(result, dict):
            if error is not None and not self._discarded(error):
                self._feedback("err")
                if not self._overlay_open():
                    self.notice = str(error)
            return
        if self.screen.mode != "home":
            self._present("windows_hide")
            return
        items = [dict(item) for item in result.get("items") or () if isinstance(item, dict)]
        origin = result.get("origin")
        desk_open = None
        if isinstance(origin, dict):
            for item in items:
                if item.get("hwnd") == origin.get("hwnd"):
                    desk_open = item.get("id")
        windows = WindowsState(items=items, origin=origin, desk_open=desk_open)
        index = _clamp(_int(result.get("index"), 0), 0, max(0, len(items) - 1))
        self._new_screen("windows", index, "windows open", windows=windows)

    def _press_windows(self, logical, now):
        windows = self.screen.windows
        if logical == 0:
            self._close_windows("back")
            return
        item = self._window_item(self.screen.index)
        if logical in (1, 2):
            side = "left" if logical == 1 else "right"
            item_id = item.get("id")
            if getattr(windows, side) == item_id:
                return  # C5-11: already holds this side
            windows.snap_busy = SnapJob(item_id, side, now)
            windows.failure = None
            self._present("windows_snap", t0=now, index=self.screen.index, side=side, target_rect=None,
                          place_at_ms=SNAP_PLACE_MS, item=dict(item))
            self._schedule(now + SNAP_RESULT_TIMEOUT, "snap timeout",
                           lambda job=windows.snap_busy: self._snap_timeout(job))
            return
        if logical == 3:
            windows.switch_request = self.request("windows_activate", item=deepcopy(item), index=self.screen.index)

    def _snap_timeout(self, job):
        windows = self.screen.windows if self.screen.mode == "windows" else None
        if windows is None or windows.snap_busy is not job:
            return
        _log.warning("No snap result within %d ms: treated as move_rejected", int(SNAP_RESULT_TIMEOUT * 1000))
        self.snap_result(job.side, "move_rejected")

    def snap_result(self, side, outcome):
        """Section 5.7.3: `accepted` assigns the side (half-wash); `ok` resolves; a failure unassigns."""
        if side in (-1, 1):
            side = "left" if side == -1 else "right"
        windows = self.screen.windows if self.screen.mode == "windows" else None
        if windows is None or windows.snap_busy is None or windows.snap_busy.side != side:
            return
        job = windows.snap_busy
        now = self.clock()
        item = self._window_item_by_id(job.item_id) or {}
        app = item.get("label_app") or item.get("app", "")
        if outcome == "accepted":
            if job.accepted:
                return
            job.accepted = True
            other = "right" if side == "left" else "left"
            if getattr(windows, other) == job.item_id:
                setattr(windows, other, None)
            setattr(windows, side, job.item_id)
            windows.last_side = side
            self._feedback("ok", moment="snap", side=-1 if side == "left" else 1, color=self._accent("window", item))
            if windows.left and windows.right:
                self._schedule(job.t0 + SNAP_PAIR_CLOSE, "snap pair close", self._close_pair)
            elif self._last_detent < job.t0:
                self._schedule(job.t0 + SNAP_ADVANCE, "snap advance", lambda j=job: self._snap_advance(j))
            return
        if outcome == "ok":
            windows.snap_busy = None
            self._run_latched()
            return
        # a failure: a pre-check (`hung`, `move_rejected`) or the placement (`move_rejected`, `cant_fit`)
        if job.accepted and getattr(windows, side) == job.item_id:
            setattr(windows, side, None)
            self.due = [entry for entry in self.due if entry[1] not in ("snap pair close", "snap advance")]
        windows.snap_busy = None
        windows.failure = {"side": side, "reason": outcome, "until": now + FAIL_META}
        self._feedback("err")
        copy_id = {"hung": "knob.meta.snap.hung", "cant_fit": "knob.meta.snap.fit"}.get(outcome, "knob.meta.snap.move")
        self._set_transient(copy_id, tone="error", ms=FAIL_META, App=app)
        self._run_latched()

    def _run_latched(self):
        windows = self.screen.windows if self.screen.mode == "windows" else None
        if windows is not None and windows.latched_close and windows.snap_busy is None:
            reason, windows.latched_close = windows.latched_close, None
            self._close_windows(reason)

    def _snap_advance(self, job):
        windows = self.screen.windows
        if self.screen.mode != "windows" or self._last_detent >= job.t0:
            return  # C5-10: a detent since t0 cancels the advance
        items = windows.items
        start = next((i for i, item in enumerate(items) if item.get("id") == job.item_id), None)
        if start is None:
            return
        for step in range(1, len(items)):
            candidate = items[(start + step) % len(items)]
            if candidate.get("id") in (windows.left, windows.right) or not candidate.get("available", True):
                continue
            index = (start + step) % len(items)
            self._reenter("snap advance", index=index)
            self._present("windows_highlight", index=index, control_id=self.control_id, bump=0)
            return

    def _close_pair(self):
        windows = self.screen.windows
        if self.screen.mode != "windows" or not (windows.left and windows.right):
            return
        now = self.clock()
        left, right = windows.left, windows.right
        a, b = self._window_app(left), self._window_app(right)
        self._present("windows_close_pair", left=left, right=right, focus=windows.last_side)
        self._cancel_pending = None
        self._new_screen("home", self.display_volume, "snap pair")
        self._exit_toast("toast.snap.pair", now, A=a, B=b)

    def _activate_result(self, effect, result, error):
        windows = self.screen.windows if self.screen.mode == "windows" else None
        if windows is not None and windows.switch_request == effect["request"]:
            windows.switch_request = None
        if windows is None:
            return
        if error is None and result:
            item = effect.get("item") or {}
            now = self.clock()
            self._feedback("ok")
            self._new_screen("home", self.display_volume, "switch")
            self._exit_toast("toast.switch", now, App=item.get("label_app") or item.get("app", ""),
                             Title=item.get("title", ""))
            return
        if error is not None and self._discarded(error):
            return
        self._feedback("err")
        self._set_transient("knob.meta.windows.no_focus", tone="error", ms=FAIL_META)
        if effect.get("index") is not None and effect["index"] != self.screen.index:
            self._present("windows_highlight", index=self.screen.index, control_id=self.control_id, bump=0)

    # ------------------------------------------------------------------ tick (section 7)
    def tick(self):
        now = self.clock()
        self._run_due(now)
        self._run_toasts(now)
        if self.state["online"] and self.desired_volume is not None and self.volume_request is None and now >= self.volume_due:
            self.volume_request = self.request("volume", value=self.desired_volume,
                                               expected_group_revision=self.state["group_revision"])
            self.last_volume_write = now
        interval = STATE_POLL_BUSY if self._exclusive_running() else STATE_POLL
        if (now - self.last_poll >= interval and not self.command_request and not self.volume_request
                and not any(e["kind"] == "state" for e in self.pending.values())):
            self.last_poll = now
            self.request("state")
        self._seek_tick(now)
        self._preresolve(now)
        self._run_passive(now)
        if self.screen.mode in ("recent", "explorer"):
            self._recent_prefetch()
        if self.screen.mode == "explorer":
            self._favourites_ensure(now)
        if self.screen.mode in ("explorer", "upnext", "windows") and now - self.last_knob_input >= OVERLAY_IDLE:
            self.close_overlay("idle")

    # ------------------------------------------------------------------ state (section 9.1)
    def _state(self, state, previous_position=None, volume_response=False, enter=True):
        """Apply a Sonos state. Returns whether Home needs a fresh entry (new bounds)."""
        old_group = self.state.get("group_revision")
        group_changed = bool(old_group and state.get("group_revision") and state.get("group_revision") != old_group)
        previous = self.display_volume if previous_position is None else previous_position
        was_online = self.state["online"]
        was_playback = self.state.get("playback")
        was_track = self.state.get("track_id")
        was_revision = str(self.state.get("queue_revision", ""))
        was_position = self.state.get("playlist_position")
        confirmed_before = self.state["volume"]
        self.state.update(state)
        if "companion_shuffle" in state and not state["companion_shuffle"]:
            self.shuffle_record_order = None   # [P3] the adapter reports no restore record any more
        self.state_known = True
        self._state_at = self.clock()
        if self.state["online"] and self.state.get("playback") == "PAUSED_PLAYBACK":
            fresh = group_changed or (was_online and was_playback != "PAUSED_PLAYBACK")
            if fresh or (self._paused_since is None and not self._paused_idle_cancelled):
                self._paused_since = self.clock()
                self._paused_idle_cancelled = False
        elif self.state["online"]:
            self._paused_since = None
            self._paused_idle_cancelled = False
        if self.state["online"] and self.state.get("playback") == "PLAYING":
            self._album_start_until = 0.0
        if group_changed or not self.state["online"]:
            self._volume_reveal_until = 0.0
            self._volume_reveal_source = ""
            self._external_until = 0.0
        elif (was_online and not volume_response and self.desired_volume is None
              and self.volume_request is None and confirmed_before != self.state["volume"]):
            self._reveal_volume(EXTERNAL_REVEAL_SECONDS, "external")
            self._external_until = self.clock() + EXTERNAL_SECONDS
        if group_changed:
            self.desired_volume = None
        reenter = self.screen.mode == "home" and (
            group_changed or (self.desired_volume is None and previous != self.display_volume))
        if not self.state["online"]:
            self.desired_volume = None
        # K3 section 5: lifetime and mode consequences of the new state.
        mode = self.screen.mode
        if group_changed and mode in ("explorer", "upnext"):
            self.close_overlay("group")
            reenter = False
        elif mode == "seek" and (group_changed or (was_track and self.state.get("track_id") != was_track)):
            self._leave_seek(flush=False, drop=True)
            self._enter_tracks(1, "seek track changed")
            reenter = False
        elif mode == "upnext" and self.state["online"]:
            self._upnext_changes(was_revision, was_position)
        elif mode == "tracks":
            self._neighbours_read()
        if group_changed and self.state["online"]:
            self._group_changed_copy()
        if reenter and enter:
            self._enter("volume")
        return reenter

    def _group_changed_copy(self):
        """The `Group changed` Home condition (section 15.2; r2.2 `Speaker group changed`), on the
        current copy line (Home `status`, else its `meta` twin, C5-56), for `group_changed_ms`
        (C5-76) in the `error` tone (lead ruling R-j, K3 E-j: was `meta`)."""
        self._set_transient("knob.status.group_changed", tone="error", ms=START_FAIL_STATUS)

    def _apply_state_result(self, result):
        result = dict(result or {})
        for key in [k for k in result if k.startswith("_")]:
            result.pop(key)
        if result:
            self._state(result)

    def _apply_result_state(self, effect, result, error):
        if error is None and isinstance(result, dict):
            self._apply_state_result(result)

    @staticmethod
    def _discarded(error):
        return getattr(error, "outcome", None) == "discarded" or "discarded" in str(error).lower()

    def _obsolete_group(self, effect, result):
        expected = effect.get("expected_group_revision")
        return bool(expected is not None and expected != self.state.get("group_revision")
                    and isinstance(result, dict) and result.get("group_revision") == expected)

    # ------------------------------------------------------------------ completions (sections 8, 9)
    def complete(self, request, result=None, error=None):
        effect = self.pending.pop(request, None)
        if not effect:
            return
        kind = effect["kind"]
        if kind == "state":
            if error is not None:
                self.state["online"] = False
                self.state_known = True
                self.desired_volume = None
                self._external_until = 0.0
                return
            self._state(dict(result or {}))
            return
        if kind == "volume":
            return self._volume_result(effect, result, error)
        if kind == "transport":
            return self._transport_result(effect, result, error)
        if kind in ("play_items", "jump"):
            return self._start_result(effect, result, error)
        if kind in ("play_next", "move_next"):
            return self._playnext_result(effect, result, error)
        if kind == "seek":
            return self._seek_result(effect, result, error)
        if kind in ("shuffle_reorder", "set_shuffle"):
            return self._shuffle_result(effect, result, error)
        if kind == "queue_window":
            return self._window_result(effect, result, error)
        if kind in ("catalog_songs", "ratings"):
            return self._enrich_result(effect, result, error)
        if kind == "like":
            return self._like_result(effect, result, error)
        if kind in ("recent", "recent_lookahead"):
            return self._recent_result(effect, result, error)
        if kind == "favourite_playlists":
            return self._favourites_result(effect, result, error)
        if kind == "playlist_meta":
            return self._meta_result(effect, result, error)
        if kind == "windows_open":
            return self._windows_open_result(effect, result, error)
        if kind == "windows_activate":
            return self._activate_result(effect, result, error)

    def _volume_result(self, effect, result, error):
        self.volume_request = None
        obsolete_group = effect.get("expected_group_revision") != self.state.get("group_revision")
        if error is not None:
            if self._discarded(error):
                return
            self.last_poll = -10
            if obsolete_group:
                return  # a write to the old group finishes quietly (CT:813-814, section 10.2)
            self.desired_volume = None
            self._feedback("err")
            if getattr(error, "outcome", None) == "group_changed":
                self._group_changed_copy()
            if not self._overlay_open():
                self.notice = str(error)
            if self.screen.mode == "home":
                self._enter("volume")
            return
        result = dict(result or {})
        if obsolete_group and result.get("group_revision") == effect.get("expected_group_revision"):
            return
        previous_position = self.display_volume
        applied = result.pop("_applied_volume", effect.get("value"))
        if self.desired_volume == applied:
            self.desired_volume = None
        reenter = self._state(result, previous_position=previous_position, volume_response=True, enter=False)
        if reenter:
            self._enter("volume")

    # ------------------------------------------------------------------ frames
    def frame(self, assume_ready=False):
        """Presentation projection, decorated by the injected presentation hook. assume_ready=True
        is the post-ready projection embedded in control()."""
        frame = self._frame(assume_ready)
        if not assume_ready and self._started_seq is not None:
            # K2 M16: only the first frame carrying the `started` moment omits `playing`.
            self._started_seq = None
        decorate = self.decorate
        if decorate is None:
            return frame
        try:
            if assume_ready:
                frame["_entry"] = True
            decorated = decorate(deepcopy(frame))
            if not isinstance(decorated, dict):
                raise TypeError("Presentation decorator must return a frame")
            decorated.pop("_entry", None)
            return _clean_frame(decorated)
        except Exception:
            if not self._decorate_failed:
                self._decorate_failed = True
                _log.exception("Presentation decorator failed; using the undecorated frame")
            frame.pop("_entry", None)
            return frame

    def _frame(self, assume_ready=False):
        ready = self.ready or assume_ready
        mode = self.screen.mode
        specs = self._buttons()
        buttons = []
        for spec in specs:
            button = {"label": spec["label"], "enabled": spec["code"] is None, "icon": spec["icon"]}
            if spec["lit"]:
                button["lit"] = spec["lit"]
                if spec["lit"] == "on" and spec["color"]:
                    button["color"] = spec["color"]
            buttons.append(button)
        frame = {"mode": MODE_TITLES[mode], "target": self._target(), "value": "", "detail": "",
                 "status": "", "title": "", "subtitle": "", "counter": "", "activity": "idle",
                 "buttons": buttons, "ring": {"style": "off", "value": 0, "index": 0, "count": 0},
                 "layout": mode, "heading": "", "meta": "", "titleTone": "ink", "metaTone": "meta",
                 "statusTone": "meta"}
        getattr(self, "_frame_" + mode)(frame, ready)
        if not ready and self.hardware and mode == "home":
            frame["status"], frame["activity"] = COPY["knob.status.connecting"], "loading"
        frame["value"] = frame["value"] or frame["title"]
        frame["detail"] = frame["detail"] or frame["subtitle"]
        frame["reducedMotion"] = self.reduced_motion
        if self.feedback:
            frame["feedback"] = dict(self.feedback)
        return _clean_frame(frame)

    def _target(self):
        if self.screen.mode == "windows":
            return "DESKTOP"
        room_count = self.state.get("group_room_count", 1)
        if isinstance(room_count, int) and room_count > 1:
            return f"{self.state.get('room_label', 'Den')} + {room_count - 1} room{'s' if room_count > 2 else ''}"
        return self.state.get("group_label", "Den")

    def _selection_ring(self, index, count, entries, kind, unavailable=None):
        """A v5 selection ring: `first` by VOC-R03, colours of the window, the unavailable mask."""
        if count <= 0:
            return {"style": "off", "value": 0, "index": 0, "count": 0}
        index = _clamp(index, 0, count - 1)
        first = window_first_v5(index, count)
        window = min(RING_WINDOW, count - first)
        colors, mask = [], 0
        for k in range(window):
            entry = entries(first + k)
            colors.append(self._accent(kind, entry) if entry is not None else 0)
            if unavailable is not None and entry is not None and unavailable(entry):
                mask |= 1 << k
        ring = {"style": "selection", "value": 0, "index": index, "count": count, "first": first, "colors": colors}
        if mask:
            ring["unavailable"] = mask
        return ring

    # Home ------------------------------------------------------------------------------------------------
    def _frame_home(self, frame, ready):
        now = self.clock()
        online = self.state["online"]
        layout = self._home_layout(ready)
        title = self.state.get("title") or ""
        frame["title"] = title or COPY["knob.caption.nothing_playing"]
        frame["subtitle"] = self.state.get("artist", "") if title else ""
        frame["value"] = f"{self.display_volume}%" if online else "--"
        frame["detail"] = self.state.get("title") or "Nothing playing"
        status, tone = self._home_status(layout, now)
        activity = "idle"
        if (self.start is not None or self.desired_volume is not None or self._home_command() is not None
                or self.play_next_job is not None or self.shuffle_job is not None or self.move_next_request is not None):
            activity = "pending"
        if layout == "notice":
            if not self.state_known:
                frame.update(title=COPY["knob.title.looking_for_sonos"], subtitle="", status="", activity="idle")
                frame["ring"] = {"style": "off", "value": self.display_volume, "index": 0, "count": 101}
            else:
                frame.update(title=COPY["knob.title.sonos_unavailable"], subtitle=COPY["knob.sub.looking_for_sonos"],
                             meta=COPY["knob.meta.windows_still_works"], status=COPY["knob.status.sonos_unavailable"],
                             activity="offline")
                frame["ring"] = {"style": "level", "value": self.display_volume, "index": 0, "count": 101}
            frame["layout"] = "notice"
        else:
            frame.update(status=status, statusTone=tone, activity=activity, layout=layout)
            frame["ring"] = {"style": "level", "value": self.display_volume, "index": 0, "count": 101,
                             "external": now < self._external_until}
        rest = self._home_layout(ready, reveal=False)
        frame["restLayout"] = "idle" if rest == "idle" else "nowPlaying"
        frame["volumeVisible"] = frame["layout"] == "volume"
        caption = self.state.get("title") or (COPY["knob.caption.now_playing"] if self.has_media()
                                              else COPY["knob.caption.nothing_playing"])
        command = self._home_command() or {}
        if self.state.get("playback") == "PAUSED_PLAYBACK" and command.get("direction") != "play":
            caption = copy_text("knob.caption.volume_paused", title=caption)
        frame["volumeCaption"] = caption
        frame["confirmedVolume"] = self.state["volume"]
        playing = self.confirmed_playing()
        started_frame = (self._started_seq is not None and self.feedback is not None
                         and self.feedback.get("seq") == self._started_seq)
        if playing is not None and not started_frame:
            frame["playing"] = playing

    def _home_status(self, layout, now):
        """Section 2.4 Home precedence: Starting… > transient > reveal > transport pending > Paused."""
        if self.start is not None:
            return COPY["knob.status.starting"], "meta"
        transient = self._transient()
        if transient is not None:
            return transient.text, transient.tone if transient.tone in ("meta", "secondary", "error") else "meta"
        if layout == "volume":
            volume = self.display_volume
            if self.desired_volume is not None:
                return COPY["knob.status.setting"], "meta"
            if self._volume_reveal_source == "external":
                return COPY["knob.status.changed_elsewhere"], "secondary"
            if volume == 0:
                return COPY["knob.status.minimum"], "secondary" if self.state.get("playback") != "PLAYING" else "meta"
            if volume == 100:
                return COPY["knob.status.maximum"], "secondary" if self.state.get("playback") != "PLAYING" else "meta"
            return "", "meta"
        command = self._home_command()
        if command is not None:
            return (COPY["knob.status.starting"] if command.get("direction") == "play" else COPY["knob.status.pausing"]), "meta"
        if layout == "idle":
            return "", "meta"
        if self.state.get("playback") == "PAUSED_PLAYBACK":
            return COPY["knob.status.paused"], "secondary"
        return "", "meta"

    # Recent ----------------------------------------------------------------------------------------------
    def _list_meta(self, lst_count, index, complete):
        if complete and lst_count and index == lst_count - 1:
            return copy_text("knob.meta.position_end", n=lst_count)
        return copy_text("knob.meta.position", i=index + 1, n=lst_count)

    def _playnext_meta(self):
        job = self.play_next_job
        if job is None:
            return None
        if job.phase == "resolving" or job.k < 1 or not job.n:
            return COPY["knob.meta.playnext.resolving"]
        return copy_text("knob.meta.playnext.progress", k=job.k, n=job.n)

    def _frame_list_recent(self, frame, index, *, explorer=False):
        lst = self.recent
        frame["page"] = 0
        frame["heading"] = COPY["knob.heading.explorer_recent" if explorer else "knob.heading.recent"]
        if lst.state == "loading":
            frame.update(meta=COPY["knob.meta.loading"], activity="loading")
            return
        if lst.state == "empty":
            frame.update(title=COPY["knob.title.recent_empty"], subtitle=COPY["knob.sub.recent_empty"])
            return
        if lst.state in ("signin", "error"):
            signin = lst.state == "signin"
            frame.update(title=COPY["knob.title.signin_expired" if signin else "knob.title.library_error"],
                         subtitle=COPY["knob.sub.signin_expired" if signin else "knob.sub.library_error"],
                         meta=COPY["knob.meta.windows_still_works"], metaTone="secondary", activity="error")
            return
        total = lst.count()
        index = _clamp(index, 0, max(0, total - 1))
        item = lst.item(index)
        pending = self.play_next_job is not None
        frame["activity"] = "pending" if pending else "idle"
        progress = None if explorer else self._playnext_meta()
        transient = self._transient()
        if item is None:
            frame["meta"] = COPY["knob.meta.loading"]
        else:
            frame["title"] = item.get("title", "")
            frame["subtitle"] = item.get("artist") or KIND_LABELS.get(item.get("kind"), "")
            if item.get("available") is False:
                frame["titleTone"] = "muted"
                frame["artDim"] = True
            frame["meta"] = self._list_meta(total, index, lst.complete)
        if transient is not None:
            frame["meta"], frame["metaTone"] = transient.text, transient.tone
        if progress is not None:
            frame["meta"], frame["metaTone"] = progress, "meta"
        frame["ring"] = self._selection_ring(index, total, lst.item, "recent",
                                             unavailable=lambda entry: entry.get("available") is False)

    def _frame_recent(self, frame, ready):
        self._frame_list_recent(frame, self.screen.index)

    # Explorer --------------------------------------------------------------------------------------------
    def _frame_explorer(self, frame, ready):
        explorer = self.screen.explorer
        source = explorer.source
        frame["layout"] = "explorer"
        if source == "recent":
            self._frame_list_recent(frame, self.screen.index, explorer=True)
            frame["page"] = 0
            return
        frame["page"] = 1
        frame["heading"] = COPY["knob.heading.explorer_favourites"]
        fav = self.favourites
        state = self._source_state("favourites")
        if state == "loading":
            frame.update(meta=COPY["knob.meta.loading"], activity="loading")
            return
        if state == "empty":
            frame.update(title=COPY["knob.title.favourites_empty"], subtitle=COPY["knob.sub.favourites_empty"])
            return
        if state == "signin":
            frame.update(title=COPY["knob.title.signin_expired"], subtitle=COPY["knob.sub.signin_expired"])
            return
        total = fav.count()
        index = _clamp(self.screen.index, 0, max(0, total - 1))
        item = fav.items[index] if index < len(fav.items) else None
        if item is None:
            frame["meta"] = COPY["knob.meta.loading"]
        else:
            meta = fav.meta.get(_item_id(item)) or {}
            frame["title"] = item.get("title") or COPY["overlay.explorer.untitled"]
            count = meta.get("count")
            if isinstance(count, int):
                frame["subtitle"] = "1 song" if count == 1 else copy_text("knob.sub.playlist_count", n=count)
            if meta.get("empty"):
                frame["titleTone"] = "muted"
                frame["artDim"] = True
            frame["meta"] = copy_text("knob.meta.position", i=index + 1, n=total)
        transient = self._transient()
        if transient is not None:
            frame["meta"], frame["metaTone"] = transient.text, transient.tone
        frame["activity"] = "pending" if self.play_next_job is not None else "idle"
        frame["ring"] = self._selection_ring(index, total, lambda j: fav.items[j] if j < len(fav.items) else None,
                                             "playlist",
                                             unavailable=lambda entry: bool((fav.meta.get(_item_id(entry)) or {}).get("empty")))

    # Tracks ----------------------------------------------------------------------------------------------
    def _neighbour(self, row):
        P, _ = self._position()
        entry = self._neighbours.get((self.state.get("queue_revision"), P)) or {}
        return entry.get(row)

    def _frame_tracks(self, frame, ready):
        index = _clamp(self.screen.index, 0, 2)
        frame["heading"] = COPY["knob.heading.tracks"]
        title = self.state.get("title") or ""
        queue = self.source() == "queue"
        P, T = self._position()
        now_line = fit_copy("knob.line.tracks.now", LINE_14, title=title) if title else COPY["knob.caption.nothing_playing"]
        skip = self._skip_command()
        transient = self._transient()
        if index == 1:
            frame["title"] = COPY["knob.title.tracks.choose"]
            frame["subtitle"] = now_line
            if queue and T:
                meta = copy_text("knob.meta.tracks.position_shuffle" if self.shuffle_active() else "knob.meta.position",
                                 i=P, n=T)
            else:
                meta = ""
        else:
            frame["title"] = COPY["knob.title.tracks.next" if index == 2 else "knob.title.tracks.prev"]
            meta = COPY["knob.meta.tracks.hint"]
            if not queue:
                frame["subtitle"] = now_line
            elif self.sonos_shuffle():
                frame["subtitle"] = COPY["knob.line.tracks.next_shuffle" if index == 2 else "knob.line.tracks.prev_shuffle"]
            elif index == 2:
                if P < T:
                    neighbour = self._neighbour(P + 1)
                    frame["subtitle"] = fit_copy("knob.line.tracks.next", LINE_14, title=neighbour) if neighbour \
                        else COPY["knob.title.tracks.next"]
                elif self.state.get("repeat") == "all":
                    frame["subtitle"] = COPY["knob.line.tracks.next_wrap"]
                else:
                    frame["subtitle"] = COPY["knob.line.tracks.end"]
            else:
                if P > 1:
                    neighbour = self._neighbour(P - 1)
                    frame["subtitle"] = fit_copy("knob.line.tracks.prev", LINE_14, title=neighbour) if neighbour \
                        else COPY["knob.title.tracks.prev"]
                elif self.state.get("repeat") == "all" and T:
                    neighbour = self._neighbour(T)
                    frame["subtitle"] = fit_copy("knob.line.tracks.prev", LINE_14, title=neighbour) if neighbour \
                        else COPY["knob.title.tracks.prev"]
                else:
                    frame["subtitle"] = COPY["knob.line.tracks.start"]
        if skip is not None:
            meta = COPY["knob.meta.tracks.skipping"]
        if transient is not None:
            frame["meta"], frame["metaTone"] = transient.text, transient.tone
        else:
            frame["meta"] = meta
        frame["activity"] = "pending" if skip is not None else "idle"
        can_previous, can_next = bool(self.state.get("can_previous")), bool(self.state.get("can_next"))
        frame["ring"] = {"style": "transport", "value": 0, "index": index, "count": 3,
                         "unavailable": (0 if can_previous else 1) | (0 if can_next else 4)}
        frame["value"] = ("Previous", "Neutral", "Next")[index]

    # Seek ------------------------------------------------------------------------------------------------
    def _frame_seek(self, frame, ready):
        seek = self.screen.seek
        now = self.clock()
        frame["heading"] = COPY["knob.heading.seek"]
        frame["title"] = self.state.get("title") or ""
        target = _clamp(seek.target_s, 0, max(0, seek.D - 1))
        frame["ring"] = {"style": "lap", "value": 0, "index": target, "count": _clamp(seek.D, 1, SEEK_MAX_DURATION_S)}
        transient = self._transient()
        if seek.busy:
            frame["meta"] = COPY["knob.line.seek.jumping"]
        elif now < seek.fail_until:
            frame["meta"], frame["metaTone"] = COPY["knob.line.seek.failed"], "error"
        elif transient is not None:
            frame["meta"], frame["metaTone"] = transient.text, transient.tone
        elif now < seek.limit_until:
            frame["meta"] = COPY["knob.line.seek.limit"]
        else:
            frame["meta"] = copy_text("knob.line.seek.length", **{"m:ss": mmss(seek.D)})
        frame["activity"] = "pending" if seek.busy else "idle"
        frame["value"] = mmss(target)

    # Up next ---------------------------------------------------------------------------------------------
    def _frame_upnext(self, frame, ready):
        upnext = self.screen.upnext
        frame["heading"] = COPY["knob.heading.upnext"]
        count_all = self._upnext_count()
        index = _clamp(self.screen.index, 0, max(0, count_all - 1))
        pending = self.shuffle_job is not None or bool(self.like_inflight)
        if upnext.loading:
            frame.update(meta=COPY["knob.meta.upnext.loading"], activity="loading")
            frame["ring"] = {"style": "off", "value": 0, "index": 0, "count": 0}
            return
        frame["activity"] = "pending" if pending else "idle"
        transient = self._transient()
        if upnext.card and index == upnext.P:
            frame["title"] = COPY["knob.title.upnext_sonos_card"]
            frame["meta"] = copy_text("knob.meta.position", i=index + 1, n=count_all)
        else:
            row = upnext.rows.get(index + 1)
            if row is None:
                frame["meta"] = copy_text("knob.meta.position", i=index + 1, n=count_all)
            else:
                frame["title"] = row.get("title", "")
                frame["subtitle"] = row.get("artist", "")
                if index + 1 == upnext.P:
                    frame["meta"] = copy_text("knob.meta.upnext.position_playing", i=index + 1, n=count_all)
                else:
                    frame["meta"] = copy_text("knob.meta.position", i=index + 1, n=count_all)
        if transient is not None:
            frame["meta"], frame["metaTone"] = transient.text, transient.tone
        ring = self._selection_ring(index, count_all,
                                    lambda j: None if (upnext.card and j == upnext.P) else upnext.rows.get(j + 1),
                                    "row")
        ring.pop("unavailable", None)   # Up next frames never set `unavailable` (C5-61)
        ring["now"] = upnext.P - 1
        if upnext.card:
            ring["card"] = True
        frame["ring"] = ring

    # Windows ---------------------------------------------------------------------------------------------
    def _frame_windows(self, frame, ready):
        windows = self.screen.windows
        items = windows.items
        frame["layout"] = "windows"
        if not items:
            frame["title"] = COPY["knob.title.no_windows"]
            return
        index = _clamp(self.screen.index, 0, len(items) - 1)
        item = items[index]
        frame["title"] = item.get("title", "")
        app = item.get("label_app") or item.get("app", "")
        frame["subtitle"] = app
        transient = self._transient()
        if transient is not None:
            frame["meta"], frame["metaTone"] = transient.text, transient.tone
        elif windows.left and not windows.right:
            frame["meta"] = fit_copy("knob.meta.snap.left_set", LINE_META, App=self._window_app(windows.left))
        elif windows.right and not windows.left:
            frame["meta"] = fit_copy("knob.meta.snap.right_set", LINE_META, App=self._window_app(windows.right))
        elif windows.switch_request is not None:
            frame["meta"] = COPY["knob.meta.windows.switching"]
        elif not item.get("available", True):
            frame["meta"] = COPY["knob.meta.windows.closed"]
        if not item.get("available", True):
            frame["titleTone"] = "muted"
        frame["activity"] = "pending" if windows.switch_request is not None else "idle"
        frame["ring"] = self._selection_ring(index, len(items), lambda j: items[j] if j < len(items) else None,
                                             "window", unavailable=lambda entry: not entry.get("available", True))

    # ------------------------------------------------------------------ compat and view models (section 11.2)
    def items(self):
        mode = self.screen.mode
        if mode == "windows":
            return list(self.screen.windows.items) if self.screen.windows else []
        if mode == "recent" or (mode == "explorer" and self.screen.explorer.source == "recent"):
            return list(self.recent.items)
        if mode == "explorer":
            return list(self.favourites.items)
        if mode == "upnext":
            upnext = self.screen.upnext
            return [upnext.rows.get(n) for n in range(1, self._upnext_count() + 1)]
        return []

    def selected(self):
        items = self.items()
        index = self.screen.index
        return items[index] if 0 <= index < len(items) else None

    def presented_index(self):
        return self.screen.index

    def presented(self):
        return self.selected()

    def lookahead_page(self):
        return None  # the v6 page lookahead is retired (flat list, U5)

    def lookahead_live(self, request):
        return False

    def recent_wanted(self, list_visit, offset=None):
        """Whether a page for the Recently Added visit `list_visit` (at `offset`) is still wanted
        (lane check, any thread): a copy of a page that already landed is not (section 5.2.2)."""
        lst = self.recent
        return list_visit == lst.visit and (type(offset) is not int or offset >= lst.next_offset)

    def art_item(self):
        """(kind, item) whose cover the knob shows (section 10.4 art identity), or (kind, None)."""
        mode = self.screen.mode
        if mode == "recent":
            return "recent", self.recent.item(self.screen.index) if self.recent.state == "ready" else None
        if mode == "explorer":
            source = self.screen.explorer.source
            if source == "recent":
                return "recent", self.recent.item(self.screen.index) if self.recent.state == "ready" else None
            item = self._source_item("favourites", self.screen.index) if self.favourites.state == "ready" else None
            if item is not None:
                meta = self.favourites.meta.get(_item_id(item)) or {}
                item = dict(item, **{key: meta[key] for key in ("mosaic", "first_art") if key in meta})
            return "playlist", item
        if mode == "upnext":
            return "row", self._upnext_focus_row()
        if mode in ("home", "tracks", "seek"):
            return "playing", None
        return mode, None

    def explorer_view(self):
        explorer = self.screen.explorer if self.screen.mode == "explorer" else None
        index = self.screen.index if explorer else 0
        recent_index = explorer.index_by_source.get("recent", 0) if explorer else self.screen.index
        recent_items, recent_first = self._explorer_window("recent", recent_index)
        fav_items, _ = self._explorer_window("favourites", explorer.index_by_source.get("favourites", 0)
                                             if explorer else 0)
        return {"source": explorer.source if explorer else "recent", "index": index,
                "recent": {"items": recent_items, "first": recent_first, "total": self.recent.total,
                           "state": self.recent.state, "complete": self.recent.complete, "rev": self.recent.rev},
                "favourites": {"items": fav_items, "state": self._source_state("favourites"), "rev": self.favourites.rev},
                "sonos_available": bool(self.state["online"]), "reduced_motion": self.reduced_motion}

    def upnext_view(self):
        upnext = self.screen.upnext if self.screen.mode == "upnext" else None
        if upnext is None:
            return None
        active = self.shuffle_active()
        row = self._upnext_focus_row()
        liked = bool(row and row.get("liked") is True)
        token = self._shuffle_token()
        line = {"sonos": "overlay.upnext.shuffle_sonos", "companion": "overlay.upnext.shuffle_on"}.get(
            token, "overlay.upnext.shuffle_off")
        return {"focus": self.screen.index, "now": upnext.P - 1, "T": upnext.T,
                "rows": self._upnext_rows_payload(), "regime": upnext.regime,
                "card": {"n": max(0, upnext.T - upnext.P)} if upnext.card else None,
                "context": self._upnext_context(), "shuffle": token, "likes_known": self._likes_known(),
                "loading": upnext.loading, "shuffle_line": COPY[line],
                "hints": ["Back", "Shuffle off" if active else "Shuffle", "Liked" if liked else "Like", "Play"],
                "reduced_motion": self.reduced_motion}

    def windows_view(self):
        windows = self.screen.windows if self.screen.mode == "windows" else None
        if windows is None:
            return None
        keep = None
        assigned = [side for side in ("left", "right") if getattr(windows, side)]
        if len(assigned) == 1 and windows.desk_open and windows.desk_open != getattr(windows, assigned[0]):
            keep = self._window_item_by_id(windows.desk_open)
        failure = windows.failure if windows.failure and self.clock() < windows.failure["until"] else None
        return {"items": windows.items, "index": self.screen.index, "left": windows.left, "right": windows.right,
                "keep": keep, "failure": failure}


def _descriptor_resource(item):
    """An item for a service effect: every field, the Apple `_resource` included (resolve needs it)."""
    return dict(item) if isinstance(item, dict) else {}
