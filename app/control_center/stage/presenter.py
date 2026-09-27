"""The stage presenter API on the Tk side, the mailbox, the events back, and the scene protocol
(DESKTOP_STAGE §2.3, §2.4, §5.3; K3 §11; VOC §7.4).

``StagePresenter`` is the facade the runtime's presenter adapters call on the Tk thread. Every
call validates the K4 §2.3 fields it must carry, posts to the stage's mailbox and returns at
once (it never waits on the stage thread). ``t0`` is the controller's ``time.perf_counter()`` at
the press; the stage anchors every scheduled leg to it (VOC-R25).

Mailbox rules: calls are handled in order; a ``*_highlight`` coalesces with a highlight of the
same surface still waiting at the tail (``merge_highlight``: newest wins; data fields the newer
one lacks, such as ``items``, are kept from the older one; the ``bump`` is the newest **non-zero**
one, because K3 always sends ``bump`` (0 on a plain turn, K3 §11.1) and a waiting end bump must
survive the turn back that follows it). The fast path (§5.3) keeps only the newest ``position``
per ``control_id``; positions of an older ``control_id`` are discarded by the stage. While an open
is still capturing, the stage buffers the calls and positions for that surface by the same rules
and applies them in the open's own batch (``engine.StageEngine``).

Events back (``take_events()``; the v6 ``(kind, payload)`` shape, drained by the adapter's
``pump()`` and handed one by one to K3's ``presenter_event``, VOC-R22):
``("opened", {"surface"})``, ``("closed", {"surface", "reason"})``, ``("click_action",
{"surface"})``, ``("refused", {"surface", "reason": "busy" | "device"})``, ``("system", {"kind":
"lock" | "sleep" | "display" | "motion"})``. There is no ``display_off`` kind. Every payload also
carries ``t0``: the QPC seconds (``time.perf_counter``) at which the stage observed the event.

``Scene`` is what WP8's explorer and Up next implement (see ``probe_scene`` for a working one).
"""
from __future__ import annotations

import threading
import time
from collections import deque

SURFACES = ("explorer", "upnext")
CALL_SURFACE = {"explorer_open": "explorer", "explorer_highlight": "explorer", "explorer_source": "explorer",
                "explorer_close": "explorer", "upnext_open": "upnext", "upnext_highlight": "upnext",
                "upnext_rows": "upnext", "upnext_close": "upnext"}
REQUIRED = {
    "explorer_open": ("t0", "source", "state", "index", "count", "items", "items_first", "items_rev", "control_id",
                      "control_min", "reduced_motion", "foreground_hwnd", "sonos_available"),
    "explorer_highlight": ("index", "control_id"),
    "explorer_source": ("t0", "source", "state", "index", "count", "items", "items_first", "items_rev"),
    "explorer_close": ("t0", "reason", "close_at_ms"),
    "upnext_open": ("t0", "rows", "now", "focus", "count", "card", "context", "shuffle", "likes_known", "loading",
                    "control_id", "control_min", "reduced_motion", "foreground_hwnd"),
    "upnext_highlight": ("index", "control_id"),
    "upnext_rows": ("t0", "reason", "rows", "now", "focus", "count", "card", "shuffle", "likes_known"),
    "upnext_close": ("t0", "reason", "close_at_ms"),
}
ROWS_REASONS = ("data", "likes", "shuffle", "queue_changed")
EXPLORER_STATES = ("loading", "ready", "empty", "signin", "error")
CLOSE_REASONS = ("back", "hold", "play", "switch", "pair", "lock", "sleep", "idle", "disconnect", "focus_lost",
                 "group", "foreground", "source", "display", "device")
ANIMATED_CLOSES = ("back", "hold", "play")          # S5-26: everything else is instant
REFUSE_BUSY, REFUSE_DEVICE = "busy", "device"
SYSTEM_KINDS = ("lock", "sleep", "display", "motion")


class PayloadError(ValueError):
    pass


def merge_highlight(older: dict, newer: dict) -> dict:
    """Two waiting ``*_highlight`` payloads of one surface as one (newest wins, data fields kept).
    The ``bump`` is the newest non-zero one: a ``lim`` end bump (±1) followed by a plain turn
    (bump 0) in the same wake still plays its bump (K3 §5.3.6, §5.6.9)."""
    merged = dict(older)
    merged.update(newer)
    nb, ob = newer.get("bump"), older.get("bump")
    if not nb and ob:
        merged["bump"] = ob
    return merged


def validate(call: str, payload: dict) -> dict:
    """K4 §2.3's must-carry fields (and the enum values the stage branches on)."""
    if call not in REQUIRED:
        raise PayloadError(f"unknown presenter call {call!r}")
    if not isinstance(payload, dict):
        raise PayloadError(f"{call}: payload must be a dict")
    missing = [f for f in REQUIRED[call] if f not in payload]
    if missing:
        raise PayloadError(f"{call}: missing {', '.join(missing)}")
    if call in ("explorer_open", "explorer_source") and payload["state"] not in EXPLORER_STATES:
        raise PayloadError(f"{call}: state {payload['state']!r}")
    if call == "upnext_rows" and payload["reason"] not in ROWS_REASONS:
        raise PayloadError(f"upnext_rows: reason {payload['reason']!r}")
    if call.endswith("_close") and payload["reason"] not in CLOSE_REASONS:
        raise PayloadError(f"{call}: reason {payload['reason']!r}")
    return payload


class Mailbox:
    """Tk thread -> stage thread hand-off (every field guarded by ``lock``); ``wake`` is called
    after each post (the engine's auto-reset event or a posted message)."""

    def __init__(self, wake=None):
        self.lock = threading.Lock()
        self.items = deque()
        self.positions = {}              # control_id -> (p, t_read)
        self.touch = False
        self.exclusions = ()
        self.events = deque(maxlen=512)
        self.wake = wake
        self.closed = False
        self.posts = 0
        self.coalesced = 0

    def _wake(self):
        w = self.wake
        if w is not None:
            try:
                w()
            except Exception:
                pass

    def post(self, call: str, payload: dict) -> bool:
        with self.lock:
            if self.closed:
                return False
            self.posts += 1
            if call.endswith("_highlight") and self.items:
                tail = self.items[-1]
                if tail[0] == call:
                    self.items[-1] = (call, merge_highlight(tail[1], payload), time.perf_counter())
                    self.coalesced += 1
                    self._wake()
                    return True
            self.items.append((call, dict(payload), time.perf_counter()))
        self._wake()
        return True

    def post_position(self, control_id, p, t_read) -> bool:
        with self.lock:
            if self.closed:
                return False
            self.positions[control_id] = (int(p), float(t_read))
        self._wake()
        return True

    def post_touch(self):
        with self.lock:
            self.touch = True
        self._wake()

    def set_exclusions(self, hwnds):
        with self.lock:
            self.exclusions = tuple(int(h) for h in hwnds or () if h)

    def take(self):
        """(calls, positions, touch) for the stage thread."""
        with self.lock:
            items = list(self.items)
            self.items.clear()
            positions, self.positions = self.positions, {}
            touch, self.touch = self.touch, False
            return items, positions, touch

    def push_event(self, kind: str, payload: dict):
        with self.lock:
            self.events.append((kind, dict(payload)))

    def take_events(self):
        with self.lock:
            out = list(self.events)
            self.events.clear()
            return out


class Scene:
    """The protocol a stage scene implements (WP8's explorer and Up next; ``probe_scene``).

    The engine owns the scene root (its opacity is the open / close fade, 340 ms OUT), the frost
    and the host; the scene owns everything above the frost. Every method that receives a
    ``batch`` adds its property changes to that one event's Commit (never commits itself).
    ``ctx`` is an ``engine.SceneContext``.
    """

    surface = "explorer"

    def __init__(self, ctx, payload):
        self.ctx = ctx

    @classmethod
    def ambient_source(cls, payload):
        """The first ambient layer's source for the capture worker: a PIL image (the focused
        item's cover) or an int ``0xRRGGBB`` (``art_bg``), or None."""
        return None

    def build(self, payload, container):
        """Create the scene's visuals in their hidden pose under ``container``."""

    def open(self, batch, payload):
        """The entry motions, committed with the root fade at t1."""

    def update(self, batch, call, payload):
        """``*_highlight``, ``explorer_source`` or ``upnext_rows``."""

    def position(self, batch, index):
        """The fast path's index for the current control (§5.3)."""

    def close(self, batch, payload):
        """An animated close's scene motions (Play: the grow and the others' fade). The engine
        fades the root: 1 -> 0 at t1 (back, hold) or at t0 + close_at_ms (play)."""

    def hit_rect(self):
        """The click-action rest rect in host client px, or None."""
        return None

    def swapping(self, now_tick) -> bool:
        """True while a switch or shuffle holds fast-path positions back (§5.3)."""
        return False

    def release(self):
        """Release the scene's own objects (the engine releases the tree it gave the scene)."""


class StagePresenter:
    """The Tk-thread facade (see the module docstring). ``engine`` is a started
    ``engine.StageThread`` or anything with ``mailbox``, ``metrics()`` and ``close()``."""

    def __init__(self, engine):
        self.engine = engine
        self.mailbox = engine.mailbox

    def _post(self, call, payload):
        return self.mailbox.post(call, validate(call, payload))

    # VOC §7.4 presenter effects, one-to-one
    def explorer_open(self, payload):
        return self._post("explorer_open", payload)

    def explorer_highlight(self, payload):
        return self._post("explorer_highlight", payload)

    def explorer_source(self, payload):
        return self._post("explorer_source", payload)

    def explorer_close(self, payload):
        return self._post("explorer_close", payload)

    def upnext_open(self, payload):
        return self._post("upnext_open", payload)

    def upnext_highlight(self, payload):
        return self._post("upnext_highlight", payload)

    def upnext_rows(self, payload):
        return self._post("upnext_rows", payload)

    def upnext_close(self, payload):
        return self._post("upnext_close", payload)

    def note_touch(self):
        """The first knob touch warms the stage device (§2.3 row ``note_touch``, §4.2)."""
        self.mailbox.post_touch()

    def position(self, control_id, p, t_read=None):
        """The input fast path (§5.3): the serial reader's position, stamped at the read."""
        return self.mailbox.post_position(control_id, p, time.perf_counter() if t_read is None else t_read)

    def set_capture_exclusions(self, hwnds):
        """Our other windows kept out of the frost's capture (§2.6; UI ``_sync_capture_exclusions``)."""
        self.mailbox.set_exclusions(hwnds)

    def take_events(self):
        return self.mailbox.take_events()

    def pump(self, sink) -> int:
        """Hand every pending event to ``sink(event)`` (K3's ``presenter_event``)."""
        n = 0
        for ev in self.take_events():
            try:
                sink(ev)
            except Exception:
                pass
            n += 1
        return n

    def metrics(self):
        return self.engine.metrics()

    def close(self, timeout: float = 2.0):
        return self.engine.close(timeout)
