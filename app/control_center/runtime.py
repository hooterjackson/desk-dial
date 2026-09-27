"""Main-thread effect dispatcher with bounded background I/O lanes (CONTROL_CENTER_V5.md sections 1, 10).

Lanes (section 1): ``audio`` (``nanod-sonos``, one worker running the section 1.1 step scheduler:
short jobs ``state``, ``volume``, ``transport``, ``seek``, ``queue_window`` run between the steps of
the exclusive queue jobs ``play_items`` (Sonos phase), ``play_next`` (Sonos phase),
``shuffle_reorder``, ``set_shuffle``, ``jump``, ``move_next``; a seek's confirmation polls run the
queued short jobs except another seek), ``library`` (``nanod-library``: the foreground Apple session:
the page the user waits for, start / Play next resolves, ``like``, a favourites load without a cache)
and ``lookahead`` (``nanod-lookahead``: prefetched pages, ``catalog_songs``, ``ratings``,
``playlist_meta``, a favourites refresh, the Home warm-up and, always last and one at a time, the
pre-resolutions of section 9.8.7). A job reads its intent when it starts (volume, seek).

Progress (section 10.3): jobs post ``("progress", request, payload)`` on the results queue; ``poll()``
hands it to ``controller.progress`` in queue order, before the job's completion.

Presenters (section 11; K4 section 2.3): the stage presenter (explorer_* / upnext_*) receives each
effect through its K4 method of the same name (``StagePresenter.explorer_open(payload)`` ...), or
``post(effect)`` when it has one (the test fakes); ``toast(text, exit=)`` on the toast service, the v6 windows
adapter (``snapshot``/``show``/``activate``/``cancel``/``highlight``/``hide``, plus ``snap``,
``close_pair`` and ``cancel(origin, complete=, reason=)`` when the v7 picker provides them), and
``take_events()`` on any of them for the section 11.4 events (K4's ``(kind, payload)`` tuples or dicts,
normalised by ``presenter_event_dict``), every one of which goes to ``controller.presenter_event``
(VOC-R22). Without a v7 picker a snap is answered ``move_rejected``
and a v6 ``cancel`` return value becomes ``cancel_result``; without a stage presenter the explorer
and Up next run on the knob alone.

Knob art (section 6.3, section 10.4): per mode the art identity is the focused item (explorer:
the focused item, a playlist's first mosaic cover; Up next: the focused row; Tracks / Seek / Home:
now playing). An entry frame keeps the previous frame's ``artKey``; the new cover goes out in the
first frame after ``ready``. Accents come from the AccentService / icon worker caches; items
without art use the Generated-sleeve accent (index 7 and monochrome apps are sent as 0, K2 M26).

alive (ALIVE.md revision 2): ``SongProgress`` posts the knob's song position; settings.json's
``led_drive`` / ``led_dither`` and (presentation 5 + alive) ``led_pink`` / ``led_vol_full`` go to
``device.set_led_tuning``; the effective Motion setting to ``device.set_reduced_motion``,
``controller.set_reduced_motion`` and the picker's ``set_reduced_motion``; the picker also gets the
overlay registry (``set_overlay_registry(overlay_surfaces)``, K4 2.4) when the runtime is built.
"""
from collections import OrderedDict, deque
from concurrent.futures import Future, ThreadPoolExecutor
import inspect
from io import BytesIO
import logging
from queue import Queue, Empty
import re
import threading
import time

from .controller import _needs_login, presenter_event_dict
from .presentation import (ALIVE_LED_DRIVE_MAX, ALIVE_LED_DRIVE_MIN, ALIVE_PROGRESS_MAX_MS,
                           MEDIA_KEY_PATTERN, MEDIA_KINDS, RING_WINDOW)
from .queue_context import QueueLedger, Segment

ART_RETRY_SECONDS = 1.0
ART_TRANSIENT_REASONS = ("timeout", "parse")
# The layouts that may carry art (never windows or notice). Idle keeps its artKey: the firmware
# fades the cover out.
ART_LAYOUTS = ("nowPlaying", "volume", "idle", "recent", "tracks", "seek", "explorer", "upnext")
ACCENT_CACHE_LIMIT = 2048  # (kind, item id) -> accent; bounded for long sessions
_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())  # the application configures the real handlers
ART_STATUS_MESSAGES = {
    "ready": "Album artwork shown on the knob.",
    "unsupported": "This firmware cannot display album artwork.",
    "size": "Album artwork does not match the knob's format.",
    "invalid": "Album artwork request was invalid.",
    "timeout": "Album artwork transfer timed out.",
    "parse": "The knob could not read an album artwork packet.",
    "rejected": "The knob could not receive this album artwork.",
    "error": "Album artwork could not be shown.",
}
_ART_KEY = re.compile(r"[A-Za-z0-9_-]{1,64}")
_MEDIA_KEY = re.compile(MEDIA_KEY_PATTERN)
MEDIA_STALE_ERROR = "Stale media control"
MEDIA_STATUS_FAILED_KEYS = 24
MEDIA_ERROR_TEXT = 80
WARMUP_FIRST_SECONDS = 10.0
WARMUP_INTERVAL_SECONDS = 600.0
WARMUP_COVERS = 10
PAGE_ITEMS = 10                 # the Home warm-up's page-1 copy
LIST_COVERS = 24                # covers of a list prefetched / named around the focus
HIRES_COVER_CACHE = 4
MOTION_RECHECK_SECONDS = 5.0    # the Motion backstop (section 14.3)
DIAG_LOG_SECONDS = 60.0         # section 6.5: the knob's enterMsLast / enterMsMax, once per minute
AUDIO_RAN_KEEP = 256            # AudioLane.ran is a bounded diagnostic (the tray process runs for weeks)
PROGRESS_REFRESH_SECONDS = 30.0
PROGRESS_SEEK_MS = 2000
_SONOS_TIME = re.compile(r"([0-9]{1,5}):([0-9]{1,2}):([0-9]{1,2})(?:\.([0-9]{1,9})(?:/([0-9]{1,9}))?)?")
_SONOS_TRANSPORTS = {"PLAYING": "playing", "PAUSED_PLAYBACK": "paused", "STOPPED": "stopped"}

# Section 1 lanes.
SHORT_OPS = frozenset(("state", "volume", "transport", "seek", "queue_window"))
EXCLUSIVE_OPS = frozenset(("shuffle_reorder", "set_shuffle", "jump", "move_next"))
LOOKAHEAD_OPS = frozenset(("recent_lookahead", "catalog_songs", "ratings", "playlist_meta"))
APPLE_OPS = frozenset(("recent", "recent_lookahead", "favourite_playlists", "playlist_meta", "catalog_songs",
                       "ratings", "like", "play_items", "play_next"))
# Section 10.2: unsent write effects dropped by invalidate_actions() (never replayed).
WRITE_OPS = frozenset(("volume", "transport", "play_items", "play_next", "seek", "shuffle_reorder",
                       "set_shuffle", "jump", "move_next", "like"))
STAGE_EFFECTS = frozenset(("explorer_open", "explorer_source", "explorer_highlight", "explorer_close",
                           "upnext_open", "upnext_highlight", "upnext_rows", "upnext_close"))
SURFACE_OF = {"explorer_open": "explorer", "upnext_open": "upnext"}


def sonos_time_ms(value):
    """A Sonos `position`/`duration` ("H:MM:SS", UPnP REL_TIME) in whole ms, or None (unknown)."""
    if not isinstance(value, str):
        return None
    match = _SONOS_TIME.fullmatch(value.strip())
    if match is None:
        return None
    hours, minutes, seconds = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if minutes > 59 or seconds > 59:
        return None
    fraction = 0
    if match.group(4) is not None:
        numerator = int(match.group(4))
        if match.group(5) is not None:
            denominator = int(match.group(5))
            if denominator == 0 or numerator >= denominator:
                return None
            fraction = numerator * 1000 // denominator
        else:
            fraction = numerator * 1000 // 10 ** len(match.group(4))
    total = (hours * 3600 + minutes * 60 + seconds) * 1000 + fraction
    return total if total <= ALIVE_PROGRESS_MAX_MS else None


def led_tuning(settings):
    """(drive, dither) from settings.json's optional `led_drive` / `led_dither` (ALIVE.md 3).

    `led_drive` is an int 1..255 and `led_dither` a bool; each is None when absent or
    invalid (an invalid one is logged by key name only, never by value). Never raises.
    """
    if not isinstance(settings, dict):
        return None, None
    drive, dither = settings.get("led_drive"), settings.get("led_dither")
    if drive is not None and not (type(drive) is int and ALIVE_LED_DRIVE_MIN <= drive <= ALIVE_LED_DRIVE_MAX):
        _log.warning("Settings led_drive ignored: not an integer %d..%d", ALIVE_LED_DRIVE_MIN, ALIVE_LED_DRIVE_MAX)
        drive = None
    if dither is not None and type(dither) is not bool:
        _log.warning("Settings led_dither ignored: not true or false")
        dither = None
    return drive, dither


def led_tuning_v5(settings):
    """(pink, vol_full) from settings.json's optional `led_pink` / `led_vol_full` (K3 section 14.4).

    `led_pink` is an int 0..0xFFFFFF or a "#RRGGBB" string (converted; 0 = the built-in PINK),
    `led_vol_full` a bool; None when absent or invalid (logged by key name only). Never raises."""
    if not isinstance(settings, dict):
        return None, None
    pink, vol_full = settings.get("led_pink"), settings.get("led_vol_full")
    if pink is not None:
        from .device import led_pink_value
        value = led_pink_value(pink)
        if value is None:
            _log.warning("Settings led_pink ignored: not an integer 0..0xFFFFFF or #RRGGBB")
        pink = value
    if vol_full is not None and type(vol_full) is not bool:
        _log.warning("Settings led_vol_full ignored: not true or false")
        vol_full = None
    return pink, vol_full


class SongProgress:
    """When to post the knob's song position (ALIVE.md section 3 `progress`, ruling R3). Pure.

    observe() is fed the controller's confirmed Sonos state and the monotonic time of its
    latest reading on every poll; update(now) answers the (pos_ms, dur_ms) to post now,
    or None. A post goes out at the first opportunity after reset(), on a track change
    and on a play/pause change, when the transport becomes PLAYING (R3), when the knob's
    Home `playing` becomes true, on a seek (a new reading more than PROGRESS_SEEK_MS off the
    posted extrapolation) and every PROGRESS_REFRESH_SECONDS while PLAYING. Nothing playing
    posts dur 0 once; an unknown transport posts nothing.
    """

    def __init__(self):
        self._snapshot = None
        self._reading = None
        self._fresh = False
        self._transport = None
        self._rising = False
        self._home = None
        self._home_rising = False
        self._sent = None
        self.reset()

    def reset(self):
        self._sent = None
        self._rising = False
        self._home = None
        self._home_rising = False

    def home(self, playing):
        playing = playing if isinstance(playing, bool) else None
        if playing is True and self._home is not True:
            self._home_rising = True
        self._home = playing

    def observe(self, state, at):
        state = state if isinstance(state, dict) else {}
        snapshot = (bool(state.get("online")), state.get("playback"), state.get("track_id"),
                    state.get("position"), state.get("duration"))
        if snapshot == self._snapshot:
            return
        self._snapshot = snapshot
        transport = _SONOS_TRANSPORTS.get(snapshot[1], "unknown") if snapshot[0] else "unknown"
        if transport == "playing" and self._transport != "playing":
            self._rising = True
        self._transport = transport
        self._reading = (transport, snapshot[2], sonos_time_ms(snapshot[3]), sonos_time_ms(snapshot[4]), at)
        self._fresh = True

    @staticmethod
    def _at(pos, dur, playing, since, now):
        value = pos + int(round((now - since) * 1000)) if playing else pos
        return max(0, min(dur, value))

    def update(self, now):
        reading = self._reading
        if reading is None:
            return None
        fresh, self._fresh = self._fresh, False
        rising, self._rising = self._rising, False
        home_rising, self._home_rising = self._home_rising, False
        transport, track, pos, dur, at = reading
        if transport == "unknown":
            return None
        if transport == "stopped" or pos is None or not dur:
            if self._sent is not None and self._sent[2] == 0:
                return None
            self._sent = (None, 0, 0, False, now)
            return 0, 0
        playing = transport == "playing"
        sent = self._sent
        due = (sent is None or not sent[2] or track != sent[0] or dur != sent[2]
               or playing != sent[3] or rising or (home_rising and playing))
        if not due and fresh:
            expected = self._at(sent[1], sent[2], sent[3], sent[4], at)
            due = abs(min(pos, dur) - expected) > PROGRESS_SEEK_MS
        if not due:
            due = playing and now - sent[4] >= PROGRESS_REFRESH_SECONDS
        if not due:
            return None
        value = self._at(pos, dur, playing, at, now)
        self._sent = (track, value, dur, playing, now)
        return value, dur


def by_distance(count, index):
    """Indices 0..count-1 ordered by distance from ``index``; ties: the following item first."""
    return sorted(range(count), key=lambda i: (abs(i - index), i < index))


def _media_counters():
    return {"uploads": 0, "hits": 0, "errors": 0, "lastError": "",
            "present": set(), "failed": set(), "failures": {}}


def _bounded_add(keys, key, limit=256):
    if key not in keys and len(keys) >= limit:
        keys.pop()
    keys.add(key)


def _unique(items):
    seen, unique = set(), []
    for key, data in items:
        if key not in seen:
            seen.add(key)
            unique.append((key, data))
    return unique


def _cover_urls(items):
    return [item["artwork_url"] for item in items
            if isinstance(item, dict) and isinstance(item.get("artwork_url"), str) and item["artwork_url"]]


def _page_copy(items):
    """The warm-up's own copy of Recently Added page 1 (at most PAGE_ITEMS items), or None."""
    if not isinstance(items, list):
        return None
    return {"items": [{k: v for k, v in item.items() if not k.startswith("_")}
                      for item in items[:PAGE_ITEMS] if isinstance(item, dict)]}


class OperationFailure(str):
    """Sanitised failure text with the section 9.10 outcome and the fields the controller reads."""

    def __new__(cls, message, unavailable=False, outcome=None, status=None, partial=False, source=None,
                late_check=False):
        value = super().__new__(cls, message)
        value.unavailable = unavailable
        value.outcome = outcome
        value.status = status
        value.partial = partial
        value.source = source
        value.late_check = late_check
        return value


def failure(error, fallback="Operation failed", op=None, kind=None):
    """An OperationFailure for ``error`` from op ``op`` (the effect kind), with its K3 outcome."""
    from .apple_music import AppleMusicError, LikeNotConfirmed, MusicUnavailable, apple_outcome
    from .sonos import SonosError, sonos_outcome
    message = str(error) if isinstance(error, RuntimeError) else f"{fallback} ({type(error).__name__})"
    outcome = None
    if "discarded" in message.lower():
        outcome = "discarded"
    elif op is not None and isinstance(error, SonosError):
        outcome = sonos_outcome(error, op)
    elif op is not None and isinstance(error, AppleMusicError):
        outcome = apple_outcome(error, op, kind=kind)
    elif op is not None and _needs_login(message.lower()):
        outcome = "signin_expired"
    return OperationFailure(message, unavailable=isinstance(error, MusicUnavailable), outcome=outcome,
                            status=getattr(error, "status", None), partial=bool(getattr(error, "partial", False)),
                            source=getattr(error, "source", None),
                            late_check=isinstance(error, LikeNotConfirmed))


_SIGNATURES = {}


def _call(function, *args, **kwargs):
    """Call ``function`` with the keyword arguments it accepts (older adapters and fakes)."""
    try:
        key = getattr(function, "__func__", function)
        accepted = _SIGNATURES.get(key)
        if accepted is None:
            parameters = inspect.signature(function).parameters.values()
            if any(p.kind == p.VAR_KEYWORD for p in parameters):
                accepted = True
            else:
                accepted = frozenset(p.name for p in parameters)
            _SIGNATURES[key] = accepted
    except (TypeError, ValueError):
        accepted = True
    if accepted is not True:
        kwargs = {name: value for name, value in kwargs.items() if name in accepted}
    return function(*args, **kwargs)


def shuffle_record_order(record):
    """The restore record's base-row signature digests in its order (K3 9.5.2 step 3), or None."""
    rows = record.get("base_rows") if isinstance(record, dict) else None
    if not isinstance(rows, list):
        return None
    order = [entry[0] for entry in rows if isinstance(entry, (list, tuple)) and entry and isinstance(entry[0], str)]
    return order if order and len(order) == len(rows) else None


def _system_animations_off():
    """Windows *Animation effects* off (SPI_GETCLIENTAREAANIMATION = 0x1042 is FALSE): a read only."""
    try:
        import ctypes
        value = ctypes.c_int(1)
        if not ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(value), 0):
            return False
        return not bool(value.value)
    except Exception:
        return False


# ------------------------------------------------------------------ lanes (section 1)
class AudioLane:
    """``nanod-sonos``: one worker, two queues (section 1.1, C5-48).

    Idle jobs run in arrival order. An exclusive job receives ``between_steps`` and calls it
    after every step with the adapter lock released: it runs every queued short job (FIFO;
    volume and seek read their newest intent at start). A seek's own ``between_steps`` runs the
    queued short jobs except another seek (a newer target waits for this one, latest wins)."""

    def __init__(self, executor):
        self.executor = executor
        self._lock = threading.Lock()
        self._jobs = deque()
        self.ran = deque(maxlen=AUDIO_RAN_KEEP)   # the latest kinds, in the order they ran (diagnostics)

    def submit(self, kind, function):
        future = Future()
        with self._lock:
            self._jobs.append((kind, function, future))
        self.executor.submit(self._drain)
        return future

    def queued(self):
        with self._lock:
            return [kind for kind, _function, _future in self._jobs]

    def _take(self, short_only=False, skip_seek=False):
        with self._lock:
            for index, (kind, function, future) in enumerate(self._jobs):
                if short_only and kind not in SHORT_OPS:
                    continue
                if skip_seek and kind == "seek":
                    continue
                del self._jobs[index]
                return kind, function, future
        return None

    def _drain(self):
        job = self._take()
        if job is not None:
            self._run(*job)

    def _run(self, kind, function, future):
        if not future.set_running_or_notify_cancel():
            return
        seek = kind == "seek"

        def between_steps():
            while True:
                job = self._take(short_only=True, skip_seek=seek)
                if job is None:
                    return
                self._run(*job)
        self.ran.append(kind)
        try:
            future.set_result(function(between_steps))
        except BaseException as exc:
            future.set_exception(exc)

    def cancel(self):
        with self._lock:
            jobs, self._jobs = list(self._jobs), deque()
        for _kind, _function, future in jobs:
            future.cancel()


class LookaheadLane:
    """``nanod-lookahead``: background Apple work; the pre-resolutions (C5-66) always run last,
    one at a time, and a new focus drops the queued ones that are no longer wanted."""

    def __init__(self, executor):
        self.executor = executor
        self._lock = threading.Lock()
        self._jobs = deque()
        self._preresolve = deque()     # (key, function)
        self.running_preresolve = None

    def submit(self, function):
        future = Future()
        with self._lock:
            self._jobs.append((function, future))
        self.executor.submit(self._drain)
        return future

    def preresolve(self, jobs):
        """Replace the queued pre-resolutions by ``jobs`` [(key, function)], keeping queued ones
        still wanted; the one running finishes into the cache."""
        with self._lock:
            keys = [key for key, _function in jobs]
            self._preresolve = deque(entry for entry in self._preresolve if entry[0] in keys)
            known = {entry[0] for entry in self._preresolve}
            if self.running_preresolve is not None:
                known.add(self.running_preresolve)
            added = [(key, function) for key, function in jobs if key not in known]
            self._preresolve.extend(added)
        for _ in added:
            self.executor.submit(self._drain)

    def drop_preresolve(self, key):
        with self._lock:
            self._preresolve = deque(entry for entry in self._preresolve if entry[0] != key)

    def keep_preresolve(self, keys):
        """A focus change (section 9.8.7): the queued pre-resolutions not in ``keys`` (the new
        focus and its neighbours) are dropped; the one running finishes into the cache."""
        with self._lock:
            self._preresolve = deque(entry for entry in self._preresolve if entry[0] in keys)

    def queued_preresolve(self):
        with self._lock:
            return [key for key, _function in self._preresolve]

    def _drain(self):
        with self._lock:
            if self._jobs:
                function, future = self._jobs.popleft()
                key = None
            elif self._preresolve and self.running_preresolve is None:
                key, function = self._preresolve.popleft()
                future = None
                self.running_preresolve = key
            else:
                return
        if future is not None:
            if not future.set_running_or_notify_cancel():
                return
            try:
                future.set_result(function())
            except BaseException as exc:
                future.set_exception(exc)
            return
        try:
            function()
        except Exception:
            pass  # a pre-resolution fails silently (the job resolves itself later)
        finally:
            with self._lock:
                self.running_preresolve = None


class Runtime:
    def __init__(self, controller, sonos, apple, windows, device=None, artwork=None,
                 accents=None, icons=None, *, stage=None, toasts=None, ledger=None, motion_probe=None):
        """`accents` is an artwork.AccentService and `icons` a windows.IconWorker (both optional);
        `stage` the explorer / Up next presenter and `toasts` the toast service (K4)."""
        self._controller = None
        self.sonos, self.apple, self.windows, self.device = sonos, apple, windows, device
        self.stage, self.toasts = stage, toasts
        self.audio = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nanod-sonos")
        self.library = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nanod-library")
        self.lookahead = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nanod-lookahead")
        self.audio_lane = AudioLane(self.audio)
        self.lookahead_lane = LookaheadLane(self.lookahead)
        self.results = Queue()
        self.closed = False
        self.device_connected = False
        self.device_supported = False
        self.presentation_level = 0
        self.button_order = [0, 1, 2, 3]
        self.held = set()
        self.last_hotkey = -10.0
        self.touch_seq = 0
        self.last_touch = None
        self.last_touch_kind = ""
        self.limit_seq = 0
        self.last_limit_dir = 0
        self.song_progress = SongProgress()
        self._progress_failed = False
        self.last_progress = None
        self.progress_seq = 0
        self.led_tuning = (None, None)
        self.led_tuning_v5 = (None, None)
        self._hires_covers = OrderedDict()
        self.last_frame = None
        self.last_heartbeat = 0
        self.device_status = "Knob disconnected"
        self.on_button_probe = None
        self._action_lock = threading.Lock()
        self._action_epoch = 0
        self._latest_volume = None
        self._last_volume_complete = -10.0
        self.artwork = artwork
        self.artwork_result = None
        self.artwork_status = None
        self._art_token = None
        self._art_sent = None
        self._art_retried = set()
        self._art_retry = None
        self._art_version = None
        self._knob_art_key = None        # the artKey the knob has (section 6.3 entry art rule)
        self.artwork_enabled = True
        self.led_style = "color"
        self.accents = {}
        self.accent_service = accents
        self.icons = icons
        self.window_icons = {}
        self.window_hires = {}
        self.window_facts = {}
        self.window_facts_revision = 0
        self._facts_failed = False
        self._accent_items = {}          # accent URL -> keys ((kind, id)) that use it
        self._accent_token = None
        self._icon_token = None
        self._accents_failed = False
        self._pump_failed = False
        self._stage_failed = False
        self.artwork2 = False
        self.icon_payloads = {}
        self.media_wanted = {kind: [] for kind in MEDIA_KINDS}
        self._media_sent = {}
        self._media_inputs = None
        self._icons_revision = 0
        self._prefetch_token = None
        self._media_counters = {kind: _media_counters() for kind in MEDIA_KINDS}
        self._media_failed = False
        self.music_signin_expired = False
        self.warmup_page = None
        self._warmup_version = 0
        self._warmup_due = time.monotonic() + WARMUP_FIRST_SECONDS
        self._warmup_serial = 0
        self._warmup_inflight = None
        self._warmup_results = Queue()
        self._held_page1 = None
        self._warmup_failed = False
        # Presenter events synthesized here (a v6 picker's cancel result, a missing snap), and the
        # K4 section 2.4 registry of what is open.
        self._events = []
        self.open_surfaces = set()
        self._snap_missing_logged = False
        # Motion (section 14.3): None = not configured yet (reduced motion off).
        self.motion_setting = None
        self.motion_probe = motion_probe or _system_animations_off
        self.reduced_motion = False
        self._motion_checked = -1e9
        # Section 6.5: the knob's re-entry timings (diag), requested and logged once per minute.
        self.last_diag = None            # (enterMsLast, enterMsMax, cause of the last re-entry)
        self._diag_requested = -1e9
        self._diag_logged = -1e9
        self.ledger = ledger if ledger is not None else self._default_ledger(sonos)
        self._shuffle_record_loaded = False
        self.attach(controller)
        self._wire_picker()

    @staticmethod
    def _default_ledger(sonos):
        """The persisted ledger of the pinned room for a live adapter; in memory for fakes."""
        try:
            from .sonos import SonosAdapter
            if isinstance(sonos, SonosAdapter):
                return QueueLedger(getattr(sonos, "room_uid", None) or "")
        except Exception:
            pass
        return QueueLedger(autosave=False)

    @property
    def controller(self):
        return self._controller

    @controller.setter
    def controller(self, controller):
        self.attach(controller)

    def attach(self, controller):
        """Install this runtime's presentation on a (replacement) controller."""
        replaced = controller is not self._controller
        self._controller = controller
        if controller is None:
            return
        controller.decorate = self._decorate
        controller.accent_lookup = self.accent_of
        controller.ledger = self.ledger
        controller.music_signin_expired = self.music_signin_expired
        controller.button_order = self.button_order[:]
        controller.set_reduced_motion(self.reduced_motion)
        if replaced:
            self.last_frame = None
            self._accent_token = self._icon_token = None
            self._prefetch_token = self._media_inputs = None
            self._held_page1 = None
        effects = []
        for effect in controller.effects:
            if effect.get("kind") == "device_enter":
                if effect.get("control", {}).get("id") != controller.control_id:
                    continue
                effect = {**effect, "control": controller.control()}
            effects.append(effect)
        controller.effects = effects

    # ------------------------------------------------------------------ art identity (section 10.4)
    @staticmethod
    def _template_url(template, size=None):
        from .artwork import ARTWORK_SIZE, apple_artwork_url
        if not isinstance(template, str) or not template:
            return ""
        return apple_artwork_url({"url": template}, size or ARTWORK_SIZE)

    def _item_art_url(self, kind, item):
        if not isinstance(item, dict):
            return ""
        url = item.get("artwork_url")
        if isinstance(url, str) and url:
            return url
        if kind == "playlist":
            first = item.get("first_art") or {}
            return self._template_url(first.get("art_template") if isinstance(first, dict) else "")
        if kind == "row":
            return self._template_url(item.get("art_template")) or (item.get("sonos_art") or "")
        return self._template_url(item.get("art_template"))

    @staticmethod
    def _item_key(kind, item):
        if not isinstance(item, dict):
            return None
        if kind == "row":
            return item.get("song_id") or item.get("signature")
        return item.get("id")

    def _art_identity(self):
        c = self.controller
        kind, item = c.art_item() if hasattr(c, "art_item") else ("playing", None)
        if kind == "playing":
            return ("playing", c.state.get("track_id"), c.state.get("artwork_url", ""))
        if item is None:
            return (kind, None, "")
        return (kind, self._item_key(kind, item), self._item_art_url(kind, item))

    def _cached_art(self, identity):
        url = identity[-1] if identity else ""
        lookup = getattr(self.artwork, "cached", None)
        if not url or lookup is None:
            return None
        try:
            result = lookup(url, token=identity, speaker_host=self.controller.state.get("artwork_host"))
        except Exception:
            return None
        if (result is None or getattr(result, "error", "") or not getattr(result, "key", "")
                or getattr(result, "token", None) != identity):
            return None
        return result

    def _poll_artwork(self):
        if not self.artwork:
            return
        token = self._art_identity()
        if not self.artwork_enabled:
            token = ("disabled", None, "")
        if token != self._art_token:
            self._art_token = token
            self._art_sent = None
            self.artwork_result = self._cached_art(token)
            self._art_version = getattr(self.artwork, "version", None)
            if self.artwork_result is not None or not token[-1]:
                self.artwork.clear()
            else:
                self.artwork.request(token[-1], token=token, speaker_host=self.controller.state.get("artwork_host"))
        elif self.artwork2 and self.artwork_result is None and token[-1]:
            version = getattr(self.artwork, "version", None)
            if version is not None and version != self._art_version:
                self._art_version = version
                self.artwork_result = self._cached_art(token)
                if self.artwork_result is not None:
                    self._art_sent = None
                    self.artwork.clear()
        for result in self.artwork.poll():
            if result.token == self._art_token and not result.error:
                self.artwork_result = result
                self._art_sent = None

    def _art_allowed(self, frame):
        c = self.controller
        layout = frame.get("layout")
        if layout not in ART_LAYOUTS or (not c.ready and not c.hardware):
            return False
        if layout in ("recent", "explorer", "upnext"):
            kind, item = c.art_item() if hasattr(c, "art_item") else (None, None)
            return item is not None
        return True

    def _decorate(self, frame):
        """Controller.decorate: pure presentation from cached state; no I/O."""
        entry = bool(frame.pop("_entry", False))
        frame["ledStyle"] = self.led_style
        key = ""
        if self.artwork_enabled and self._art_allowed(frame):
            identity = self._art_identity()
            result = self.artwork_result
            if (result is None or getattr(result, "error", "") or not getattr(result, "key", "")
                    or result.token != identity):
                result = self._cached_art(identity) if self.artwork else None
            if result is not None:
                key = (getattr(result, "jpeg_key", None) or "") if self.artwork2 else result.key
        if entry and self._knob_art_key is not None:
            key = self._knob_art_key  # section 6.3: the entry keeps the previous frame's cover
        frame["artKey"] = key
        if self.artwork2:
            icon_key = self._frame_icon_key(frame)
            if icon_key:
                frame["iconKey"] = icon_key
        ring = frame.get("ring")
        if isinstance(ring, dict) and self.led_style != "color":
            ring.pop("colors", None)
        return frame

    def _presented_index(self):
        c = self.controller
        index = c.presented_index() if hasattr(c, "presented_index") else c.screen.index
        return index if isinstance(index, int) else 0

    def _presented_window(self):
        c = self.controller
        if c.screen.mode != "windows":
            return None
        item = c.presented() if hasattr(c, "presented") else c.selected()
        return item if isinstance(item, dict) else None

    def _frame_icon_key(self, frame):
        if frame.get("layout") != "windows":
            return ""
        item = self._presented_window()
        payload = self.window_icon_payload(item.get("id")) if item is not None else None
        return payload[0] if payload else ""

    def window_icon_payload(self, item_id):
        icon = self.window_icons.get(item_id)
        if icon is None:
            return None
        entry = self.icon_payloads.get(item_id)
        if entry is not None and entry[0] is icon:
            return entry[1]
        from .artwork import attached_icon_payload, icon_payload
        try:
            payload = attached_icon_payload(icon) or icon_payload(icon)
        except Exception:
            payload = None
        self.icon_payloads[item_id] = (icon, payload)
        return payload

    # ------------------------------------------------------------------ accents (section 10.4)
    def accent_of(self, kind, item):
        """The controller's accent hook: 0xRRGGBB, 0 = warm. Items without art get the Generated
        sleeve's accent (GEN index 7 and monochrome apps are sent as 0, K2 M26)."""
        if not isinstance(item, dict):
            return 0
        if kind == "window":
            value = item["accent"] if "accent" in item else self.accents.get(("window", item.get("id")))
            return value if type(value) is int and 0 <= value <= 0xFFFFFF else 0
        value = item.get("accent")
        if kind == "row":
            cached = self.accents.get(("row", self._item_key("row", item)))
        else:
            cached = self.accents.get((kind if kind == "playlist" else "recent", item.get("id")))
        if type(cached) is int and 0 <= cached <= 0xFFFFFF:
            return cached
        if type(value) is int and 0 < value <= 0xFFFFFF:
            return value
        if not self._item_art_url(kind, item) and not (kind == "row" and item.get("sonos_art")):
            from .artwork import gen_sleeve
            return gen_sleeve(item.get("title", ""), item.get("artist", ""))["ring_accent"]
        return 0

    def _store_accent(self, key, color):
        if len(self.accents) >= ACCENT_CACHE_LIMIT and key not in self.accents:
            for old in list(self.accents)[:ACCENT_CACHE_LIMIT // 2]:
                del self.accents[old]
        self.accents[key] = color if type(color) is int and 0 <= color <= 0xFFFFFF else None

    def _accent_requests(self):
        """(token, [(key, url)]) for the list the knob shows now."""
        from .artwork import ACCENT_SIZE
        c = self.controller
        mode = c.screen.mode
        if not hasattr(c, "recent"):
            return None, []
        pairs = []
        if mode == "recent" or (mode == "explorer" and c.screen.explorer.source == "recent"):
            token = ("recent", c.recent.visit, c.recent.rev)
            for item in c.recent.items:
                url = item.get("accent_url") or self._template_url(item.get("art_template"), ACCENT_SIZE)
                if "accent" not in item and url:
                    pairs.append((("recent", item.get("id")), url))
            return token, pairs
        if mode == "explorer":
            token = ("playlist", c.favourites.rev)
            for item in c.favourites.items:
                meta = c.favourites.meta.get(str(item.get("id"))) or {}
                first = meta.get("first_art") or {}
                url = self._template_url(first.get("art_template"), ACCENT_SIZE) if isinstance(first, dict) else ""
                url = url or item.get("accent_url") or ""
                if "accent" not in item and url:
                    pairs.append((("playlist", item.get("id")), url))
            return token, pairs
        if mode == "upnext" and c.screen.upnext is not None:
            upnext = c.screen.upnext
            token = ("row", c.screen.view_id, len(upnext.rows), upnext.revision)
            for row in upnext.rows.values():
                url = self._template_url(row.get("art_template"), ACCENT_SIZE) or row.get("sonos_art") or ""
                if url:
                    pairs.append((("row", self._item_key("row", row)), url))
            return token, pairs
        return None, []

    def _poll_accents(self):
        c = self.controller
        screen = c.screen
        token, pairs = self._accent_requests()
        if token != self._accent_token:
            self._accent_token = token
            if token is not None and self.accent_service is not None and pairs:
                urls = []
                for key, url in pairs:
                    self._accent_items.setdefault(url, set()).add(key)
                    urls.append(url)
                if len(self._accent_items) > ACCENT_CACHE_LIMIT:
                    keep = set(urls)
                    self._accent_items = {u: keys for u, keys in self._accent_items.items() if u in keep}
                self.accent_service.request_many(urls, token=token, speaker_host=c.state.get("artwork_host"))
        if self.accent_service is not None:
            for _token, url, color in self.accent_service.poll():
                for key in self._accent_items.get(url, ()):
                    self._store_accent(key, color)
        windows = screen.windows if screen.mode == "windows" else None
        items = list(getattr(windows, "items", None) or ()) if windows is not None else None
        icon_token = screen.view_id if items is not None else None
        if icon_token != self._icon_token:
            self._icon_token = icon_token
            if items is not None and self.icons is not None:
                wanted = [i for i in items if "accent" not in i]
                if wanted:
                    live = {i.get("id") for i in items}
                    self.window_icons = {k: v for k, v in self.window_icons.items() if k in live}
                    self.icon_payloads = {k: v for k, v in self.icon_payloads.items() if k in live}
                    self.window_hires = {k: v for k, v in self.window_hires.items() if k in live}
                    if any(k not in live or "audible" in v for k, v in self.window_facts.items()):
                        self.window_facts = {k: {key: value for key, value in v.items() if key != "audible"}
                                             for k, v in self.window_facts.items() if k in live}
                        self.window_facts_revision += 1
                    self._icons_revision += 1
                    self.icons.request(wanted)
        if self.icons is not None:
            for result in self.icons.poll():
                item_id, icon, accent = result
                if getattr(result, "hires", False) and self._keep_hires(item_id, icon):
                    continue
                self._store_accent(("window", item_id), accent)
                self.window_icons[item_id] = icon
                self._icons_revision += 1

    def _poll_facts(self):
        poll = getattr(self.icons, "poll_facts", None) if self.icons is not None else None
        if poll is None:
            return
        for item_id, facts in poll() or ():
            if not isinstance(facts, dict):
                continue
            merged = dict(self.window_facts.get(item_id) or {})
            merged.update(facts)
            self.window_facts[item_id] = merged
            self.window_facts_revision += 1

    def _keep_hires(self, item_id, icon):
        from .windows import attached_hires_icon
        current = self.window_icons.get(item_id)
        big = attached_hires_icon(icon)
        try:
            same = (current is not None and big is not None and current.size == icon.size
                    and current.mode == icon.mode and current.tobytes() == icon.tobytes())
        except Exception:
            same = False
        if same:
            self.window_hires[item_id] = (current, big)
        return same

    def window_hires_icon(self, item_id):
        icon = self.window_icons.get(item_id)
        if icon is None:
            return None
        entry = self.window_hires.get(item_id)
        if entry is not None and entry[0] is icon:
            return entry[1]
        from .windows import attached_hires_icon
        return attached_hires_icon(icon)

    # ------------------------------------------------------------------ artwork2
    def _refresh_media(self):
        capability = getattr(self.device, "media_capability", None) if self.device_connected else None
        negotiated = isinstance(capability, dict) and bool(capability)
        if negotiated != self.artwork2:
            self.artwork2 = negotiated
            self._art_sent = None
            self._media_sent = {}
            self._media_inputs = None
            self.media_wanted = {kind: [] for kind in MEDIA_KINDS}

    def _list_cover_items(self):
        """(kind, [items by distance from the focus]) of the list the knob shows, or (None, [])."""
        c = self.controller
        mode = c.screen.mode
        if not hasattr(c, "recent"):
            return None, []
        if mode == "recent" or (mode == "explorer" and c.screen.explorer.source == "recent"):
            items = c.recent.items
            kind = "recent"
        elif mode == "explorer":
            items = c.favourites.items
            kind = "playlist"
        elif mode == "upnext" and c.screen.upnext is not None:
            upnext = c.screen.upnext
            items = [upnext.rows.get(n) for n in range(1, (max(upnext.rows) if upnext.rows else 0) + 1)]
            kind = "row"
        else:
            return None, []
        index = self._presented_index()
        ordered = [items[i] for i in by_distance(len(items), index)][:LIST_COVERS]
        return kind, [item for item in ordered if isinstance(item, dict)]

    def _poll_prefetch(self):
        """ArtworkService.prefetch for what the knob may show next: with artwork2, the focused
        list's covers by distance (asked when the list or its data change); on Home with the
        warm-up active, its page 1 copy's covers."""
        c = self.controller
        screen = c.screen
        signature = None
        kind, items = self._list_cover_items()
        if self.artwork_enabled and self.artwork2 and kind is not None and items:
            # artwork2 only: a v1 knob loads the focused cover on demand (ARTWORK2.md section 9).
            revision = (getattr(c.recent, "rev", 0), getattr(c.favourites, "rev", 0))
            signature = ((screen.mode, screen.view_id, revision), True, False)
        elif screen.mode == "home" and self.warmup_page is not None and self._warmup_active():
            signature = (("warmup", self._warmup_version), False, False)
        if signature == self._prefetch_token:
            return
        self._prefetch_token = signature
        prefetch = getattr(self.artwork, "prefetch", None)
        if prefetch is None:
            return
        token, urls = None, []
        if signature is not None:
            token = signature[0]
            if token[0] == "warmup":
                urls = _cover_urls(self.warmup_page.get("items", ()))[:WARMUP_COVERS]
            else:
                urls = [url for url in (self._item_art_url(kind, item) for item in items) if url]
        prefetch(urls, page=token, speaker_host=c.state.get("artwork_host"))

    def _current_cover(self, key):
        if not key:
            return None
        result = self.artwork_result
        if getattr(result, "jpeg_key", None) != key:
            result = self._cached_art(self._art_identity()) if self.artwork else None
        jpeg = getattr(result, "jpeg", None)
        if getattr(result, "jpeg_key", None) == key and isinstance(jpeg, bytes) and jpeg:
            return key, jpeg
        return None

    def _cached_cover(self, url):
        lookup = getattr(self.artwork, "cached_cover", None)
        if lookup is None or not isinstance(url, str) or not url:
            return None
        hit = lookup(url, speaker_host=self.controller.state.get("artwork_host"))
        if (isinstance(hit, tuple) and len(hit) == 2 and isinstance(hit[0], str)
                and _MEDIA_KEY.fullmatch(hit[0]) and isinstance(hit[1], bytes) and hit[1]):
            return hit
        return None

    def _wanted_covers(self, frame):
        """What the knob shows now, then the focused list by distance (VOC section 7.1 knob art),
        then Now Playing; on Home with the warm-up active, the Recent page 1 copy's covers."""
        if not self.artwork_enabled or self.artwork is None:
            return []
        c = self.controller
        wanted = []
        current = self._current_cover(frame.get("artKey") or "")
        if current:
            wanted.append(current)
        kind, items = self._list_cover_items()
        for item in items:
            hit = self._cached_cover(self._item_art_url(kind, item))
            if hit:
                wanted.append(hit)
        hit = self._cached_cover(c.state.get("artwork_url"))
        if hit:
            wanted.append(hit)
        if c.screen.mode == "home" and self.warmup_page is not None and self._warmup_active():
            for url in _cover_urls(self.warmup_page.get("items", ()))[:WARMUP_COVERS]:
                hit = self._cached_cover(url)
                if hit:
                    wanted.append(hit)
        return _unique(wanted)

    def _wanted_icons(self):
        c = self.controller
        windows = c.screen.windows if c.screen.mode == "windows" else None
        if windows is None:
            return []
        items = [i for i in getattr(windows, "items", ()) if isinstance(i, dict)]
        wanted = []
        for index in by_distance(len(items), self._presented_index()):
            payload = self.window_icon_payload(items[index].get("id"))
            if payload:
                wanted.append(payload)
        return _unique(wanted)

    def _media_signature(self, frame):
        c = self.controller
        screen = c.screen
        return (self.artwork_enabled, frame.get("artKey") or "", frame.get("iconKey") or "",
                screen.mode, screen.view_id, self._presented_index(),
                getattr(getattr(c, "recent", None), "rev", 0), getattr(getattr(c, "favourites", None), "rev", 0),
                len(screen.upnext.rows) if getattr(screen, "upnext", None) else 0,
                c.state.get("artwork_url"), c.state.get("artwork_host"),
                getattr(self.artwork, "version", None), self._icons_revision,
                self._warmup_version if screen.mode == "home" and self._warmup_active() else None)

    def _push_media(self, frame):
        signature = self._media_signature(frame)
        if signature != self._media_inputs:
            self._media_inputs = signature
            self.media_wanted = {"cover": self._wanted_covers(frame), "icon": self._wanted_icons()}
        setter = getattr(self.device, "set_media_wanted", None)
        if setter is None:
            return
        for kind in MEDIA_KINDS:
            items = self.media_wanted.get(kind, [])
            keys = tuple(key for key, _ in items)
            if self._media_sent.get(kind) == keys:
                continue
            setter(kind, list(items))
            self._media_sent[kind] = keys

    def _media_event(self, event):
        kind = event.get("media", event.get("mediaKind"))
        if kind not in MEDIA_KINDS:
            return
        key = event.get("key")
        key = key if isinstance(key, str) and _MEDIA_KEY.fullmatch(key) else ""
        counters = self._media_counters[kind]
        if event.get("kind") == "media-ready":
            counters["hits" if event.get("hit") is True else "uploads"] += 1
            if key:
                _bounded_add(counters["present"], key)
                counters["failed"].discard(key)
                counters["failures"].pop(key, None)
            return
        error = event.get("error")
        error = error[:MEDIA_ERROR_TEXT] if isinstance(error, str) else "error"
        counters["errors"] += 1
        counters["lastError"] = error
        if key:
            counters["present"].discard(key)
            if error != MEDIA_STALE_ERROR:
                count = counters["failures"].get(key, 0) + 1
                if len(counters["failures"]) >= 4 * MEDIA_STATUS_FAILED_KEYS and key not in counters["failures"]:
                    counters["failures"].clear()
                counters["failures"][key] = count
                if count >= 2 or event.get("failed") is True:
                    _bounded_add(counters["failed"], key)

    def _media_connection_reset(self):
        self._media_sent = {}
        self._media_inputs = None
        for counters in self._media_counters.values():
            counters["present"].clear()
            counters["failed"].clear()
            counters["failures"].clear()

    def media_status(self):
        bridge = None
        source = getattr(self.device, "media_status", None)
        if callable(source) and self.artwork2:
            try:
                bridge = source()
            except Exception:
                bridge = None
        status = {}
        for kind in MEDIA_KINDS:
            counters = self._media_counters[kind]
            entry = {"wanted": len(self.media_wanted.get(kind, ())), "present": len(counters["present"]),
                     "uploads": counters["uploads"], "hits": counters["hits"], "errors": counters["errors"],
                     "failedKeys": sorted(counters["failed"])[:MEDIA_STATUS_FAILED_KEYS],
                     "lastError": counters["lastError"]}
            reported = bridge.get(kind) if isinstance(bridge, dict) else None
            if isinstance(reported, dict):
                for name in ("wanted", "present", "uploads", "hits", "errors", "dropped"):
                    if type(reported.get(name)) is int:
                        entry[name] = reported[name]
                failed = reported.get("failedKeys")
                if isinstance(failed, (list, tuple, set)):
                    entry["failedKeys"] = sorted(k for k in failed if isinstance(k, str)
                                                 and _MEDIA_KEY.fullmatch(k))[:MEDIA_STATUS_FAILED_KEYS]
                if isinstance(reported.get("lastError"), str):
                    entry["lastError"] = reported["lastError"][:MEDIA_ERROR_TEXT]
            status[kind] = entry
        return status

    def lcd_media(self, frame, item=None, *, hires=False):
        """What lcd_preview.render_lcd draws for ``frame``: (artwork, window_icon, artwork2, identity)
        (with ``hires``: plus the hi-res cover and icon)."""
        art_key = frame.get("artKey") or ""
        result = self.artwork_result
        art = icon = None
        icon_identity = None
        if self.artwork2:
            if art_key and result is not None and getattr(result, "jpeg_key", None) == art_key:
                art = getattr(result, "jpeg", None)
            if frame.get("layout") == "windows" and isinstance(item, dict):
                payload = self.window_icon_payload(item.get("id"))
                if payload:
                    icon, icon_identity = payload[1], payload[0]
        else:
            if art_key and result is not None and getattr(result, "key", None) == art_key:
                art = result.preview
            if frame.get("layout") == "windows" and isinstance(item, dict):
                icon = self.window_icons.get(item.get("id"))
                if icon is not None:
                    icon_identity = (item.get("id"), id(icon))
        identity = (art_key if art is not None else "", icon_identity, self.artwork2)
        if not hires:
            return art, icon, self.artwork2, identity
        cover = self._hires_cover(result) if art is not None else None
        big_icon = None
        if icon is not None and isinstance(item, dict):
            big_icon = self.window_hires_icon(item.get("id"))
        identity += ("hires" if cover is not None else "", id(big_icon) if big_icon is not None else None)
        return art, icon, self.artwork2, identity, cover, big_icon

    def _hires_cover(self, result):
        data = getattr(result, "hires_jpeg", None)
        if not isinstance(data, bytes) or not data:
            return None
        key = (getattr(result, "key", ""), getattr(result, "jpeg_key", None))
        hit = self._hires_covers.get(key)
        if hit is not None and hit[0] == data:
            self._hires_covers.move_to_end(key)
            return hit[1]
        try:
            from PIL import Image
            with Image.open(BytesIO(data)) as decoded:
                image = decoded.convert("RGB")
        except Exception:
            image = None
        self._hires_covers[key] = (data, image)
        self._hires_covers.move_to_end(key)
        while len(self._hires_covers) > HIRES_COVER_CACHE:
            self._hires_covers.popitem(last=False)
        return image

    # ------------------------------------------------------------------ Home warm-up (ARTWORK2.md 11.4)
    def _note_library(self, effect, error):
        """Section 10.4: every Apple result feeds the sign-in state (cleared by any success)."""
        if not isinstance(effect, dict) or effect.get("kind") not in APPLE_OPS:
            return
        if error is None:
            self.music_signin_expired = False
        elif getattr(error, "outcome", None) == "signin_expired" or getattr(error, "status", None) in (401, 403) \
                or _needs_login(str(error).lower()):
            self.music_signin_expired = True
        self.controller.music_signin_expired = self.music_signin_expired

    def _warmup_supported(self):
        return (callable(getattr(self.apple, "has_credentials", None))
                and callable(getattr(self.apple, "recent_preview", None)))

    def _music_credentials(self):
        if not self._warmup_supported():
            return False
        try:
            return bool(self.apple.has_credentials())
        except Exception:
            return False

    def _lane_credentials(self):
        refresh = getattr(self.apple, "refresh_credentials", None)
        return bool(refresh() if callable(refresh) else self.apple.has_credentials())

    def _warmup_permitted(self, credentials=True):
        if (self.closed or self.artwork is None or not self.artwork_enabled
                or self.music_signin_expired or not self._warmup_supported()):
            return False
        return not credentials or self._music_credentials()

    def _warmup_home(self):
        return (self.device_connected and self.device_supported
                and self.controller.screen.mode == "home")

    def _warmup_active(self):
        return self._warmup_home() and self._warmup_permitted()

    def _set_warmup_page(self, page):
        self.warmup_page = page
        self._warmup_version += 1

    def _poll_warmup(self):
        now = time.monotonic()
        for _ in range(8):
            try:
                serial, result, error = self._warmup_results.get_nowait()
            except Empty:
                break
            if serial != self._warmup_inflight:
                continue
            self._warmup_inflight = None
            if error is not None:
                if _needs_login(str(error).lower()):
                    self.music_signin_expired = True
                continue
            page = _page_copy(result.get("items") if isinstance(result, dict) else None)
            if page is not None:
                self.music_signin_expired = False
                self._set_warmup_page(page)
        c = self.controller
        if c.screen.mode in ("recent", "explorer"):
            items = getattr(c.recent, "items", None)
            if items:
                self._held_page1 = list(items[:PAGE_ITEMS])
        elif self._held_page1 is not None:
            held, self._held_page1 = self._held_page1, None
            page = _page_copy(held)
            if page is not None and self._warmup_permitted():
                self._set_warmup_page(page)
                self._warmup_due = now + WARMUP_INTERVAL_SECONDS
        if (self._warmup_inflight is not None or now < self._warmup_due or not self._warmup_home()
                or not self._warmup_permitted(credentials=False)):
            return
        self._warmup_serial += 1
        self._warmup_inflight = self._warmup_serial
        self._warmup_due = now + WARMUP_INTERVAL_SECONDS
        # Straight onto the lookahead worker (FIFO with the lane's own drains): a normal-priority
        # job, never behind the pre-resolutions.
        self.lookahead.submit(self._warmup_job, self._warmup_serial)

    def _warmup_job(self, serial):
        result = error = None
        try:
            if self.closed or self.controller.screen.mode != "home":
                raise RuntimeError("Obsolete library request discarded")
            if self._lane_credentials():
                result = self.apple.recent_preview(limit=PAGE_ITEMS)
        except Exception as exc:
            result, error = None, failure(exc)
        self._warmup_results.put((serial, result, error))

    def frame(self):
        return self.controller.frame()

    # ------------------------------------------------------------------ alive
    @property
    def alive(self):
        if self.device is None or not (self.device_connected and self.device_supported):
            return False
        try:
            return getattr(self.device, "alive", False) is True
        except Exception:
            return False

    def _poll_progress(self, now):
        progress = self.song_progress
        progress.observe(self.controller.state, now)
        if not self.alive:
            progress.reset()
            return False
        controller = self.controller
        if controller.screen.mode == "home":
            progress.home(controller.confirmed_playing())
        post = progress.update(now)
        if post is None:
            return False
        self.device.post_progress(*post)
        self.last_progress = (post[0], post[1], now)
        self.progress_seq += 1
        return True

    def apply_led_tuning(self, settings):
        """settings.json `led_drive` / `led_dither` (ALIVE.md 3) and `led_pink` / `led_vol_full`
        (K3 section 14.4, presentation 5 + alive) to the bridge. No UI; values are never logged.
        Returns the (drive, dither) applied."""
        tuning = led_tuning(settings)
        extra = led_tuning_v5(settings)
        self.led_tuning, self.led_tuning_v5 = tuning, extra
        setter = getattr(self.device, "set_led_tuning", None) if self.device is not None else None
        if callable(setter):
            try:
                if extra == (None, None):
                    setter(*tuning)
                else:
                    _call(setter, *tuning, pink=extra[0], vol_full=extra[1])
            except Exception as exc:
                _log.warning("LED tuning not applied (%s)", type(exc).__name__)
        return tuning

    # ------------------------------------------------------------------ Motion (section 14.3)
    def set_motion(self, setting):
        """Settings `motion` ∈ {system, full, reduced}; re-evaluated at once."""
        self.motion_setting = setting if setting in ("system", "full", "reduced") else "system"
        self._refresh_motion(force=True)

    def _refresh_motion(self, force=False):
        setting = self.motion_setting
        if setting is None:
            return
        now = time.monotonic()
        if not force and now - self._motion_checked < MOTION_RECHECK_SECONDS:
            return
        self._motion_checked = now
        if setting == "full":
            on = False
        elif setting == "reduced":
            on = True
        else:
            try:
                on = bool(self.motion_probe())
            except Exception:
                on = False
        if on != self.reduced_motion or force:
            self.reduced_motion = on
            self.controller.set_reduced_motion(on)
            setter = getattr(self.device, "set_reduced_motion", None) if self.device is not None else None
            if callable(setter):
                try:
                    setter(on)
                except Exception as exc:
                    _log.warning("Motion setting not applied (%s)", type(exc).__name__)
            self._picker_motion(on)

    def _picker_motion(self, on):
        """The effective Motion setting to the picker (K3 14.3; K4 16: latched at its next open).
        The Tk shell also hands it over per tick when it changes; doing it here as well keeps the
        picker of a replacement runtime (simulator / live switch) in step from its first open."""
        setter = getattr(self.windows, "set_reduced_motion", None) if self.windows is not None else None
        if callable(setter):
            try:
                setter(bool(on))
            except Exception as exc:
                _log.warning("Motion setting not applied to the picker (%s)", type(exc).__name__)

    def overlay_surfaces(self):
        """K4 2.4: the open overlay surfaces (a copy of ``open_surfaces``), for the picker's toast
        service and its end-the-toast-on-open rule (K4 10.4)."""
        return set(self.open_surfaces)

    def _wire_picker(self):
        """Hand the picker this runtime's overlay registry and the current Motion setting, when it
        takes them (the v7 WindowsAdapter: ``set_overlay_registry``, ``set_reduced_motion``)."""
        registry = getattr(self.windows, "set_overlay_registry", None) if self.windows is not None else None
        if callable(registry):
            try:
                registry(self.overlay_surfaces)
            except Exception as exc:
                _log.warning("Overlay registry not given to the picker (%s)", type(exc).__name__)
        self._picker_motion(self.reduced_motion)

    def note_touch(self, kind):
        """Record a physical knob touch ("turn", "button", "hotkey", "limit"; "sim"). Only records."""
        self.touch_seq += 1
        self.last_touch = time.monotonic()
        self.last_touch_kind = kind

    def hotkey(self):
        """F24 (WM_HOTKEY): the picker opens on Home only (section 4.3), synchronously."""
        if self.closed or not self.device_connected or not self.device_supported or self.on_button_probe:
            return
        self.note_touch("hotkey")
        self.last_hotkey = time.monotonic()
        self.controller.open_windows()
        self.dispatch()

    # ------------------------------------------------------------------ services
    def _check_epoch(self, epoch):
        with self._action_lock:
            if self.closed or epoch != self._action_epoch:
                raise RuntimeError("Pending action discarded after connection changed")

    def _post_progress(self, request, payload):
        self.results.put(("progress", request, payload))

    def _audio_op(self, effect, epoch, between_steps):
        """One audio-lane op (a short job, or an exclusive job's Sonos phase)."""
        kind = effect["kind"]
        sonos = self.sonos
        if kind == "state":
            return sonos.read_state()
        if kind == "volume":
            delay = self._last_volume_complete + 0.1 - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            with self._action_lock:
                target, group = self.controller.volume_intent()
                if epoch != self._action_epoch or target is None or group != effect["expected_group_revision"]:
                    raise RuntimeError("Pending volume discarded after connection changed")
            try:
                state = sonos.set_volume(target, effect["expected_group_revision"])
            finally:
                self._last_volume_complete = time.monotonic()
            return {**state, "_applied_volume": target}
        self._check_epoch(epoch)
        rev = effect.get("expected_group_revision")
        if kind == "transport":
            return sonos.transport(effect["direction"], rev, effect.get("expected_track_id"))
        if kind == "seek":
            target = self.controller.seek_target(effect)
            return _call(sonos.seek, target, rev, effect.get("expected_track_id"), between_steps=between_steps)
        if kind == "queue_window":
            return sonos.queue_window(effect["start"], effect["count"])
        if kind == "set_shuffle":
            return sonos.set_shuffle(effect["on"], rev)
        if kind == "shuffle_reorder":
            return _call(sonos.shuffle_reorder, effect["on"], rev, effect.get("expected_track_id"),
                         plan=effect.get("plan"), playnext_offsets=effect.get("playnext_offsets") or (),
                         expected_rows=effect.get("expected_rows"),
                         playnext_song_ids=effect.get("playnext_song_ids") or (),
                         expected_update_id=effect.get("expected_update_id"),
                         progress=lambda payload, r=effect["request"]: self._post_progress(r, payload),
                         between_steps=between_steps)
        if kind == "jump":
            return _call(sonos.jump, effect["row"], rev, effect.get("expected_track_id"),
                         effect.get("expected_update_id"), name=effect.get("name"), between_steps=between_steps)
        if kind == "move_next":
            return _call(sonos.move_next, effect["row"], rev, effect.get("expected_update_id"), item=effect.get("item"))
        raise ValueError("Unknown operation")

    def _recent_page(self, effect, background):
        apple = self.apple
        list_visit = effect.get("list_visit")
        offset = effect.get("offset")
        controller = self.controller

        def wanted():
            return not self.closed and self.controller is controller and _call(controller.recent_wanted, list_visit,
                                                                                    offset=offset)
        if not wanted():
            raise RuntimeError("Obsolete library request discarded")
        page = getattr(apple, "recent_page", None)
        if callable(page):
            return _call(page, effect.get("offset", 0), visit=effect.get("visit"), limit=effect.get("limit", 25),
                         background=background, wanted=wanted)
        offset = effect.get("offset", 0)
        legacy = apple.recent(None if offset == 0 else str(offset), limit=effect.get("limit", 25))
        return {"items": legacy.get("items", []), "offset": offset, "total": None,
                "complete": not legacy.get("next"), "visit": None}

    def _apple_op(self, effect, background):
        kind = effect["kind"]
        apple = self.apple
        if kind in ("recent", "recent_lookahead"):
            return self._recent_page(effect, background)
        if kind == "like":
            return apple.like(effect["song_id"])
        if kind == "ratings":
            return _call(apple.ratings, effect.get("ids") or [], background=background)
        if kind == "catalog_songs":
            return _call(apple.catalog_songs, effect.get("ids") or [], background=background)
        if kind == "favourite_playlists":
            return _call(apple.favourite_playlists, background=background)
        if kind == "playlist_meta":
            return _call(apple.playlist_meta, effect["playlist_id"], duration=bool(effect.get("duration")),
                         last_modified=effect.get("last_modified"), background=background)
        raise ValueError("Unknown operation")

    def _submit_audio(self, effect, epoch):
        future = self.audio_lane.submit(effect["kind"], lambda steps, e=effect, ep=epoch: self._audio_op(e, ep, steps))
        future.add_done_callback(lambda f, e=effect: self._done(e, f))

    def _resolve(self, item, lenient, background=False):
        apple = self.apple
        return _call(apple.resolve, item, lenient=lenient, background=background)

    def _dispatch_start(self, effect, epoch):
        """play_items: the library-lane resolve (cache first, joining a running pre-resolution),
        then the audio lane's exclusive Sonos phase (section 9.2)."""
        item = effect.get("item") or {}
        self.lookahead_lane.drop_preresolve(self._preresolve_key(item))
        future = self.library.submit(self._resolve, item, effect.get("lenient"))
        future.add_done_callback(lambda f, e=effect, ep=epoch: self._resolved_start(e, ep, f))

    def _resolved_start(self, effect, epoch, future):
        try:
            resolved = future.result()
            self._check_epoch(epoch)
        except Exception as exc:
            self._evict(effect)
            self.results.put((effect["request"], None, failure(exc, "Library resolution failed", op="play_items",
                                                               kind=effect.get("item_kind"))))
            return
        rev = effect["expected_group_revision"]

        def play(between_steps):
            self._check_epoch(epoch)
            return _call(self.sonos.play_items, resolved, rev, between_steps=between_steps, name=effect.get("name"))
        played = self.audio_lane.submit("play_items", play)
        played.add_done_callback(lambda f, e=effect, r=resolved: self._done(e, f, resolved=r))

    def _dispatch_play_next(self, effect, epoch):
        """play_next: the resolve cache first (a hit inserts at once), else the library lane
        (joining a running pre-resolution; a queued one is dropped), then the inserts."""
        item = effect.get("item") or {}
        request = effect["request"]
        self.lookahead_lane.drop_preresolve(self._preresolve_key(item))
        lenient = item.get("kind") == "playlist"
        cached = None
        lookup = getattr(self.apple, "resolve_cached", None)
        if callable(lookup):
            try:
                cached = _call(lookup, item, lenient=lenient)
            except Exception:
                cached = None
        if cached is not None:
            count = len(cached.get("tracks") or []) if isinstance(cached, dict) else len(cached or [])
            self._post_progress(request, {"phase": "inserting", "k": 0, "n": min(count, 100)})
            self._insert_play_next(effect, epoch, cached)
            return
        known = item.get("track_count")
        self._post_progress(request, {"phase": "resolving", "n": known if isinstance(known, int) else None})
        future = self.library.submit(self._resolve, item, lenient)
        future.add_done_callback(lambda f, e=effect, ep=epoch: self._resolved_play_next(e, ep, f))

    def _resolved_play_next(self, effect, epoch, future):
        try:
            resolved = future.result()
            self._check_epoch(epoch)
        except Exception as exc:
            self._evict(effect)
            self.results.put((effect["request"], None, failure(exc, "Library resolution failed", op="play_next")))
            return
        self._insert_play_next(effect, epoch, resolved)

    def _insert_play_next(self, effect, epoch, resolved):
        request = effect["request"]

        def insert(between_steps):
            self._check_epoch(epoch)
            return _call(self.sonos.play_next, resolved, effect["expected_group_revision"],
                         effect.get("expected_track_id"),
                         progress=lambda payload: self._post_progress(request, payload),
                         between_steps=between_steps)
        future = self.audio_lane.submit("play_next", insert)
        future.add_done_callback(lambda f, e=effect, r=resolved: self._done(e, f, resolved=r))

    @staticmethod
    def _preresolve_key(item):
        return (item.get("kind"), str(item.get("id"))) if isinstance(item, dict) else None

    def _evict(self, effect):
        evict = getattr(self.apple, "evict_resolved", None)
        if callable(evict):
            try:
                evict(effect.get("item") or {})
            except Exception:
                pass

    def _preresolve(self, effects):
        """The controller's pre-resolution batch (C5-66): lookahead lane, lowest priority."""
        preresolve = getattr(self.apple, "preresolve", None)
        if not callable(preresolve):
            return
        jobs = []
        for effect in effects:
            item = effect.get("item") or {}
            key = self._preresolve_key(item)
            if key is None:
                continue
            jobs.append((key, lambda i=item, focused=bool(effect.get("focused")):
                         self._run_preresolve(preresolve, i, focused)))
        self.lookahead_lane.preresolve(jobs)

    def _run_preresolve(self, preresolve, item, focused):
        if self.closed:
            return None
        return _call(preresolve, item, focused=focused)

    def invalidate_actions(self):
        """Section 10.2: drop unsent write effects; already-dispatched work finishes honestly."""
        with self._action_lock:
            self._action_epoch += 1
            self._latest_volume = None
        retained = []
        controller = self.controller
        for effect in controller.effects:
            if effect.get("kind") in WRITE_OPS:
                forget = getattr(controller, "forget", None)
                if callable(forget):
                    forget(effect)
                else:
                    controller.pending.pop(effect.get("request"), None)
            else:
                retained.append(effect)
        controller.effects = retained

    def _done(self, effect, future, resolved=None):
        request = effect["request"] if isinstance(effect, dict) else effect
        kind = effect.get("kind") if isinstance(effect, dict) else None
        try:
            result = future.result()
        except Exception as exc:
            if isinstance(effect, dict) and kind in ("play_items", "play_next"):
                self._evict(effect)
            item_kind = effect.get("item_kind") if isinstance(effect, dict) else None
            self.results.put((request, None, failure(exc, op=kind, kind=item_kind)))
            return
        if isinstance(effect, dict):
            try:
                self._record_ledger(effect, result, resolved)
            except Exception as exc:  # the ledger is presentation: never fatal
                _log.warning("Queue ledger not updated (%s)", type(exc).__name__)
        self.results.put((request, result, None))

    def _record_ledger(self, effect, result, resolved):
        """Section 10.4: the base segment from `_final_song_ids`, a Play-next block from `_inserted`."""
        if not isinstance(result, dict):
            return
        kind = effect.get("kind")
        item = effect.get("item") or {}
        tracks = resolved.get("tracks") if isinstance(resolved, dict) else (resolved if isinstance(resolved, list) else [])
        if kind == "play_items" and result.get("_final_song_ids") is not None:
            start = result.get("_start") or {}
            item_kind = {"library-albums": "album", "library-playlists": "playlist",
                         "library-songs": "song"}.get(item.get("kind"), item.get("kind") or "album")
            segment = Segment(kind=item_kind if item_kind in ("album", "playlist", "song") else "album",
                              name=effect.get("name") or item.get("title", ""), artist=item.get("artist", ""),
                              year=item.get("year") if isinstance(item.get("year"), int) else None,
                              library_id=str(item.get("id", "")), art_template=item.get("art_template", "") or "",
                              accent=effect.get("accent") or 0, favourite=bool(item.get("favourite")),
                              auto=bool(item.get("auto")), count=start.get("n") if isinstance(start.get("n"), int) else None,
                              duration_ms=item.get("duration_ms") if isinstance(item.get("duration_ms"), int) else None,
                              album=(tracks[0].get("album", "") if tracks and isinstance(tracks[0], dict) else ""))
            self.ledger.record_start(segment, result["_final_song_ids"])
        elif kind in ("play_next", "move_next") and isinstance(result.get("_inserted"), dict):
            inserted = result["_inserted"]
            context = Segment(kind="playnext", name=effect.get("name") or item.get("title", ""),
                              artist=item.get("artist", ""), library_id=str(item.get("id", "")),
                              art_template=item.get("art_template", "") or "", accent=effect.get("accent") or 0)
            self.ledger.append_playnext(inserted.get("start_row"), inserted.get("song_ids") or [], context)

    # ------------------------------------------------------------------ dispatch
    def dispatch(self):
        preresolve = []
        for effect in self.controller.drain():
            kind = effect["kind"]
            if kind == "device_enter":
                if self.device_connected and self.device_supported and effect["control"]["id"] == self.controller.control_id:
                    self.held.clear()
                    self.device.submit("enter", effect["control"])
                continue
            if kind == "resolve":
                preresolve.append(effect)
                continue
            if kind == "resolve_drop":
                if preresolve:   # keep the order: an earlier batch first, then the drop
                    self._preresolve(preresolve)
                    preresolve = []
                self.lookahead_lane.keep_preresolve(
                    {self._preresolve_key(item) for item in effect.get("keep") or () if isinstance(item, dict)})
                continue
            if kind.startswith("windows_"):
                self._windows_effect(effect)
                continue
            if kind in STAGE_EFFECTS:
                self._stage_effect(effect)
                continue
            if kind == "toast":
                self._toast(effect)
                continue
            with self._action_lock:
                epoch = self._action_epoch
                self._latest_volume = self.controller.desired_volume
            if kind in SHORT_OPS or kind in EXCLUSIVE_OPS:
                self._submit_audio(effect, epoch)
            elif kind == "play_items":
                self._dispatch_start(effect, epoch)
            elif kind == "play_next":
                self._dispatch_play_next(effect, epoch)
            elif kind in ("recent", "like") or (kind == "favourite_playlists" and effect.get("lane") != "lookahead"):
                future = self.library.submit(self._apple_op, effect, False)
                future.add_done_callback(lambda f, e=effect: self._done(e, f))
            elif kind in LOOKAHEAD_OPS or kind == "favourite_playlists":
                future = self.lookahead_lane.submit(lambda e=effect: self._apple_op(e, True))
                future.add_done_callback(lambda f, e=effect: self._done(e, f))
            else:
                _log.warning("Unknown effect %s dropped", kind)
                self.controller.pending.pop(effect.get("request"), None)
        if preresolve:
            self._preresolve(preresolve)

    def _foreground_hwnd(self):
        getter = getattr(self.windows, "foreground_hwnd", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                return None
        return None

    def _stage_effect(self, effect):
        if effect["kind"].endswith("_open"):
            effect["foreground_hwnd"] = self._foreground_hwnd()
        stage = self.stage
        if stage is None:
            return  # no stage presenter: the explorer / Up next run on the knob alone
        try:
            post = getattr(stage, "post", None)
            if callable(post):
                posted = post(effect)
            else:
                # K4 section 2.3: StagePresenter's methods are the presenter effects one-to-one.
                posted = getattr(stage, effect["kind"])(effect)
            if posted is False and effect["kind"] in SURFACE_OF:
                raise RuntimeError("stage mailbox closed")
        except Exception as exc:
            if not self._stage_failed:
                self._stage_failed = True
                _log.warning("Stage presenter failed (%s)", type(exc).__name__)
            surface = SURFACE_OF.get(effect["kind"])
            if surface is not None:
                self._events.append({"kind": "refused", "surface": surface, "reason": "device"})

    def _toast(self, effect):
        target = self.toasts if self.toasts is not None else self.windows
        toast = getattr(target, "toast", None)
        if not callable(toast):
            return
        try:
            _call(toast, effect.get("text", ""), exit=bool(effect.get("exit")))
        except Exception as exc:
            _log.warning("Toast not shown (%s)", type(exc).__name__)

    def _windows_effect(self, effect):
        kind = effect["kind"]
        windows = self.windows
        try:
            if kind == "windows_open":
                result = windows.snapshot()
                windows.show(result)
                self.controller.complete(effect["request"], result)
            elif kind == "windows_activate":
                self.controller.complete(effect["request"], windows.activate(effect["item"]))
            elif kind == "windows_highlight":
                # K3 11.1: `bump` (the knob's end push) drives the picker's end bump (K4 9.8);
                # an adapter without the parameter still gets the plain highlight.
                bump = effect.get("bump") or 0
                if bump:
                    try:
                        windows.highlight(effect["index"], bump=bump)
                    except TypeError:
                        windows.highlight(effect["index"])
                else:
                    windows.highlight(effect["index"])
            elif kind == "windows_hide":
                windows.hide()
            elif kind == "windows_cancel":
                # K3 5.7.4 / 9.9 (C5-78, review item R8): the close `reason` goes to the picker, which
                # hides at once for lock/sleep/idle and never restores focus for lock/sleep (K4 15).
                # `_call` passes only what the adapter takes: a v6 adapter gets `cancel(origin)`, and a
                # picker given no reason (an older controller) keeps inferring it (WP7b-D6).
                result = _call(windows.cancel, effect.get("origin"), complete=effect.get("complete"),
                               reason=effect.get("reason"))
                if not callable(getattr(windows, "take_events", None)):
                    self._events.append({"kind": "cancel_result", "restored": bool(result), "completed": False})
            elif kind == "windows_snap":
                snap = getattr(windows, "snap", None)
                rect = getattr(windows, "half_rect", None)
                if callable(rect) and effect.get("target_rect") is None:
                    try:
                        effect["target_rect"] = rect(effect.get("side"))
                    except Exception:
                        effect["target_rect"] = None
                if callable(snap):
                    snap(effect)
                else:
                    if not self._snap_missing_logged:
                        self._snap_missing_logged = True
                        _log.warning("The picker has no snap; a snap is answered move_rejected")
                    self._events.append({"kind": "snap_result", "side": effect.get("side"),
                                         "outcome": "move_rejected"})
            elif kind == "windows_close_pair":
                close_pair = getattr(windows, "close_pair", None)
                if callable(close_pair):
                    close_pair(effect.get("left"), effect.get("right"), effect.get("focus"))
                else:
                    windows.hide()
        except Exception as exc:
            if kind in ("windows_open", "windows_activate"):
                self.controller.complete(effect.get("request"), error=f"Windows control failed ({type(exc).__name__})")
            else:
                _log.warning("Picker call %s failed (%s)", kind, type(exc).__name__)
                if kind == "windows_cancel":
                    self._events.append({"kind": "cancel_result", "restored": False, "completed": False})

    def _pump_windows(self):
        pump = getattr(self.windows, "pump", None)
        if pump is None:
            return
        try:
            pump()
        except Exception as exc:
            if not self._pump_failed:
                self._pump_failed = True
                _log.warning("Windows picker events could not be handled (%s)", type(exc).__name__)

    def _presenter_events(self):
        """Every section 11.4 event, from every presenter, to the controller's one entry point."""
        events, self._events = self._events, []
        for source in (self.stage, self.windows, self.toasts):
            take = getattr(source, "take_events", None) if source is not None else None
            if callable(take):
                try:
                    events.extend(take() or ())
                except Exception as exc:
                    _log.warning("Presenter events lost (%s)", type(exc).__name__)
        for event in events:
            # K4's stage posts (kind, payload) tuples, the picker and the fakes dicts: one shape here.
            event = presenter_event_dict(event)
            if event is None:
                continue
            kind = event.get("kind")
            surface = event.get("surface")
            if kind == "opened" and surface:
                self.open_surfaces.add(surface)
            elif kind == "closed" and surface:
                self.open_surfaces.discard(surface)
            if kind == "system" and event.get("what", event.get("system")) == "motion":
                self._refresh_motion(force=True)
                event = dict(event, on=self.reduced_motion)
            self.controller.presenter_event(event)

    def poll(self):
        if self.closed:
            return
        self._pump_windows()
        with self._action_lock:
            self._latest_volume = self.controller.desired_volume
        self._presenter_events()
        for _ in range(400):   # a 100-song Play next posts 100 progress entries before its result
            try:
                item = self.results.get_nowait()
            except Empty:
                break
            if len(item) == 3 and item[0] == "progress":
                self.controller.progress(item[1], item[2])
                continue
            if len(item) == 2 and item[0] == "shuffle_record":
                setter = getattr(self.controller, "shuffle_record", None)
                if callable(setter):
                    setter(item[1])
                continue
            request, result, error = item
            pending = getattr(self.controller, "pending", None)
            self._note_library(pending.get(request) if isinstance(pending, dict) else None, error)
            self.controller.complete(request, result, error)
        self._device_events()
        self._poll_diag(time.monotonic())
        self._refresh_media()
        self._refresh_motion()
        self.controller.tick()
        self.dispatch()
        if not self._shuffle_record_loaded:
            self._load_shuffle_record()
        try:
            self._poll_warmup()
        except Exception as exc:
            if not self._warmup_failed:
                self._warmup_failed = True
                _log.warning("Home warm-up unavailable (%s)", type(exc).__name__)
        self._poll_artwork()
        try:
            self._poll_accents()
        except Exception as exc:
            if not self._accents_failed:
                self._accents_failed = True
                _log.warning("Ring accents unavailable (%s)", type(exc).__name__)
        try:
            self._poll_facts()
        except Exception as exc:
            if not self._facts_failed:
                self._facts_failed = True
                _log.warning("Picker facts unavailable (%s)", type(exc).__name__)
        try:
            self._poll_prefetch()
        except Exception as exc:
            self._media_failure(exc)
        now = time.monotonic()
        posted = False
        try:
            posted = self._poll_progress(now)
        except Exception as exc:
            if not self._progress_failed:
                self._progress_failed = True
                _log.warning("Song position unavailable (%s)", type(exc).__name__)
        if self.device_connected and self.device_supported and self.controller.ready:
            frame = {"id": self.controller.control_id, **self.frame()}
            if frame != self.last_frame or now - self.last_heartbeat >= 0.5 or posted:
                self.device.submit("frame", frame)
                self.last_frame, self.last_heartbeat = frame, now
                self._knob_art_key = frame.get("artKey") or ""
            if self.artwork2:
                self._art_sent = None
                try:
                    self._push_media(frame)
                except Exception as exc:
                    self._media_failure(exc)
                return
            key = frame.get("artKey") or ""
            if not key:
                self._art_sent = None
                return
            if self._art_retry and now >= self._art_retry[0]:
                if self._art_sent == self._art_retry[1]:
                    self._art_sent = None
                self._art_retry = None
            result = self.artwork_result
            identity = (self.controller.control_id, key)
            if result and getattr(result, "key", "") == key and identity != self._art_sent:
                self.device.submit("artwork", {"id": identity[0], "key": result.key, "data": result.rgb565})
                self._art_sent = identity

    def _load_shuffle_record(self):
        """Read the live adapter's companion-shuffle restore record once, on the audio lane (store
        I/O, section 9.5.5); afterwards its read_state() reports `companion_shuffle`."""
        self._shuffle_record_loaded = True
        try:
            from .sonos import SonosAdapter
        except Exception:
            return
        if isinstance(self.sonos, SonosAdapter):
            self.audio_lane.submit("state", self._read_shuffle_record)

    def _read_shuffle_record(self, _steps=None):
        """Audio lane: load the record, then hand the controller its base-row order (signature
        digests only, K3 9.5.3 [P3]) through the results queue, so the Shuffle-off preview matches
        the restore after a restart. Nothing of it is logged."""
        record = self.sonos.load_shuffle_record()
        self.results.put(("shuffle_record", shuffle_record_order(record)))
        return record

    def _media_failure(self, exc):
        if not self._media_failed:
            self._media_failed = True
            _log.warning("Knob artwork lists unavailable (%s)", type(exc).__name__)

    def _artwork_event(self, event):
        ident, key = event.get("id"), event.get("key")
        key = key if isinstance(key, str) and _ART_KEY.fullmatch(key) else ""
        if event.get("kind") == "artwork-ready":
            self.artwork_status = {"state": "ready", "key": key, "reason": "",
                                   "message": ART_STATUS_MESSAGES["ready"]}
            return
        reason = event.get("reason")
        reason = reason if reason in ART_STATUS_MESSAGES and reason != "ready" else "error"
        self.artwork_status = {"state": "error", "key": key, "reason": reason,
                               "message": ART_STATUS_MESSAGES[reason]}
        identity = (ident, key)
        if (reason in ART_TRANSIENT_REASONS and event.get("transient", True) is not False
                and not event.get("retrying") and identity == self._art_sent
                and identity not in self._art_retried):
            self._art_retried = {i for i in self._art_retried if i[0] == ident}
            self._art_retried.add(identity)
            self._art_retry = (time.monotonic() + ART_RETRY_SECONDS, identity)

    def _hotkey_registered(self):
        return bool(getattr(self.windows, "supports_hotkey", True))

    # ------------------------------------------------------------------ diagnostics (section 6.5)
    def _poll_diag(self, now):
        """Once a minute while a v5 knob is claimed, ask the bridge for `diag` (VOC section 6.1:
        the knob answers `{"diag":"?"}` only). The bridge posts the reply as a `diag` event."""
        if not (self.device_connected and self.device_supported):
            return
        if now - self._diag_requested < DIAG_LOG_SECONDS:
            return
        self._diag_requested = now
        request = getattr(self.device, "request_diag", None) if self.device is not None else None
        if callable(request):
            try:
                request()
            except Exception as exc:
                _log.debug("Knob diag not requested (%s)", type(exc).__name__)

    @staticmethod
    def _diag_ms(value):
        return value if type(value) is int and 0 <= value <= 600000 else None

    def _diag_event(self, event, now=None):
        """A `diag` reply: log enterMsLast / enterMsMax with the cause of the last re-entry, at
        debug level, at most once per minute (gate H3 reads them). Numbers and the cause only."""
        payload = event.get("diag") if isinstance(event.get("diag"), dict) else event
        last, peak = self._diag_ms(payload.get("enterMsLast")), self._diag_ms(payload.get("enterMsMax"))
        if last is None and peak is None:
            return
        cause = str(getattr(self.controller, "last_reentry_cause", "") or "")[:40]
        self.last_diag = (last, peak, cause)
        now = time.monotonic() if now is None else now
        if now - self._diag_logged < DIAG_LOG_SECONDS:
            return
        self._diag_logged = now
        _log.debug("Knob re-entry timing: enterMsLast %s ms, enterMsMax %s ms (last re-entry: %s)",
                   "?" if last is None else last, "?" if peak is None else peak, cause or "?")

    def _lost(self):
        """disconnected / closed / error / released: section 13.4."""
        self.invalidate_actions()
        self.held.clear()
        self.controller.disconnected()
        self.dispatch()  # the overlay closes (disconnect) go out now
        self.windows.set_hotkey_enabled(False)

    def _device_events(self):
        if not self.device:
            return
        for _ in range(200):
            try:
                event = self.device.events.get_nowait()
            except Empty:
                break
            kind = event.get("kind")
            if kind == "connected":
                self._art_sent = None
                self._knob_art_key = None
                self.device_connected = True
                self.song_progress.reset()
                self._media_connection_reset()
                self._refresh_media()
                capabilities = event.get("capabilities", {}) or {}
                self.device_supported = bool(capabilities.get("controlCenter"))
                level = capabilities.get("presentation", 0)
                self.presentation_level = level if type(level) is int else 0
                self._diag_requested = time.monotonic()   # the first diag a minute after the claim
                self.device_status = ("Connected · verifying control interface" if self.device_supported
                                      else "Stock firmware · display/control extension required")
                if self.device_supported:
                    try:
                        self.windows.set_hotkey_enabled(True)
                        self.controller.button_order = self.button_order[:]
                        self.controller.windows_hid_enabled = self._hotkey_registered()
                        self.controller.set_hardware(True)
                    except OSError:
                        self.device_supported = False
                        self.device_status = "F24 is unavailable · close the conflicting hotkey app"
            elif kind == "ready":
                self.controller.device_ready(event.get("id"))
                self.device_status = "Knob ready · installed profiles active"
            elif kind == "position":
                self.note_touch("turn")
                if not self.on_button_probe:
                    self.controller.position(event.get("position", event.get("p")), event.get("id"))
            elif kind == "limit":
                # A knob touch (summons the floating knob) and a controller input (section 10.4:
                # the Seek limit line and idle re-arm, overlay end bumps, the lifetime clock).
                self.note_touch("limit")
                direction = event.get("dir")
                if type(direction) is int and direction in (-1, 1):
                    self.limit_seq += 1
                    self.last_limit_dir = direction
                    if not self.on_button_probe:
                        self.controller.limit(direction, event.get("id"))
            elif kind == "hold":
                if not self.on_button_probe:
                    self.controller.hold(event.get("button"), event.get("id"))
            elif kind == "button":
                raw = event.get("button", event.get("kd"))
                edge = event.get("edge", "down")
                if edge in ("up", "release") or "ku" in event:
                    self.held.discard(event.get("button", event.get("ku")))
                    continue
                if raw not in range(4):
                    continue
                self.note_touch("button")
                if self.on_button_probe:
                    self.on_button_probe(raw)
                    continue
                logical = self.button_order.index(raw)
                hid = event.get("hid") is True
                if logical == 3:
                    if hid:
                        continue  # the F24 path already acted (VOC section 2.5)
                    if (self.presentation_level < 5 and self._hotkey_registered()
                            and self.controller.screen.mode == "home"):
                        continue  # presentation 4: the hotkey owns Home's Win button
                self.controller.button(logical, event.get("id"), hid)
            elif kind in ("disconnected", "closed"):
                self.device_connected = self.device_supported = False
                self._refresh_media()
                self._lost()
                self.windows.hide()
                self.device_status = event.get("message", "Knob disconnected")
            elif kind == "error":
                self.device_status = event.get("message", "Device error")
                self.device_supported = False
                self._lost()
                self.controller.ready = False
            elif kind == "diag":
                self._diag_event(event)
            elif kind in ("artwork-ready", "artwork-error"):
                self._artwork_event(event)
            elif kind in ("media-ready", "media-error"):
                self._media_event(event)
            elif kind == "released":
                self.device_supported = False
                self._lost()
                self.controller.ready = False
                self.device_status = "Host control released · disconnect and reconnect"

    def shutdown(self, close_device=False):
        """Stop this runtime: unsent actions, the picker, presentation services, lanes."""
        first_error = None

        def step(action):
            nonlocal first_error
            try:
                action()
            except Exception as exc:
                if first_error is None:
                    first_error = exc

        step(self.invalidate_actions)
        self.closed = True
        step(self.windows.close)
        for service in (self.artwork, self.accent_service, self.icons):
            if service is not None:
                step(service.close)
        if close_device and self.device:
            step(lambda: self.device.submit("close"))
        step(self.audio_lane.cancel)
        self.audio.shutdown(wait=False, cancel_futures=True)
        self.library.shutdown(wait=False, cancel_futures=True)
        self.lookahead.shutdown(wait=False, cancel_futures=True)
        if first_error is not None:
            raise first_error

    def close(self):
        self.shutdown(close_device=True)
