"""Prepared surfaces (DESKTOP_STAGE §0.7, §4.5, §7.3, §13.3; G1-9).

- **Bytes.** Surfaces are ``DXGI_FORMAT_B8G8R8A8_UNORM``: premultiplied for sprites with alpha,
  ``DXGI_ALPHA_MODE_IGNORE`` for opaque content (covers, frost, ambient). ``sprite_bytes`` is
  PIL ``tobytes("raw", "BGRa")`` of an RGBA image (Pillow's BGRa packer premultiplies); it runs
  on a worker (§13.4 step 5; ``tobytes`` releases the GIL, §4.7.3).
- **Upload budget.** ``UploadQueue.run`` spends at most **4 ms** per stage wake (§4.5); the rest
  waits for the next wake, so an input commit never queues behind uploads. The first item of a
  wake always goes, so progress never stalls.
- **Upload discipline** (the 2026-09-26 frame-drop fixes, S1; the measurements are in the
  ``device`` module docstring). An upload-carrying ``Commit`` blocks until about two frames after
  the previous one, and the old queue revealed what landed with a Commit in the same wake, every
  wake: on screen those reveal Commits took 4-8 ms (the per-event work tail), and an upload whose
  reveal made no call was carried by the next detent's Commit instead. Now one upload wake: at most
  4 ms **and** ``UPLOAD_BUDGET_BYTES`` (2.5 MB), each upload followed by the context's Flush, then
  **the wake's own upload Commit at once** (it carries surface content only), and upload wakes
  are paced ``gap_s`` apart (two frames and 1 ms: that Commit never waits), so no input Commit
  ever carries an upload. The surfaces then **ripen** ``READY_S`` (4 ms, a frame; the picker
  chrome's rule) after that Commit: only then does ``done`` put a surface in the LRU and its key
  reach the scene's reveal, so no batch binds a surface before it is a frame old and the reveal's
  Commit is a bind (about 0.01-0.2 ms). A tick (``put(..., tick=True)``) carries no surface: it
  lands at the next wake, as before.
- **Shared solids (G1-9).** One opaque surface per colour and size class (the proven shared
  shade: a 680 px card shade is one 1.8 MB surface for every card), not a stretched 1 x 1,
  until a pixel test shows the stretch is clean (G1 P5 decides by eye).
- **Fixed shadow layers (§0.7, §7.3, §8.2).** A CSS ``box-shadow`` around a rectangle is
  prepared once as a small premultiplied sprite at 1/4 resolution (σ = blur / 2, reach 3σ) and
  stretched ×4 by the compositor; shadows are crossfaded between fixed layers, never
  interpolated (CAR deviation 11 retired).
- **Residency (§4.5, §13.3).** ``SurfaceLRU`` keeps GPU surfaces by key with pinning for the
  preload window and releases on eviction (64 cover pairs by default).
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque

UPLOAD_BUDGET_S = 0.004
UPLOAD_BUDGET_BYTES = 2_621_440           # 2.5 MB per upload wake (with the 4 ms)
READY_S = 0.004                           # a surface is revealed this long after its upload Commit
UPLOAD_GAP_FRAMES = 2                     # upload Commits at least two frames ...
UPLOAD_GAP_MARGIN_S = 0.001               # ... and 1 ms apart (the native spacing, device docstring)
COVER_PAIRS = 64
SHADOW_REDUCE = 4


def sprite_bytes(img):
    """(w, h, premultiplied BGRA bytes) of a PIL image (any mode with or without alpha)."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    return img.size[0], img.size[1], img.tobytes("raw", "BGRa")


def opaque_bytes(img):
    """(w, h, BGRA bytes with alpha 255) for an opaque surface (DXGI_ALPHA_MODE_IGNORE). Pillow's
    BGRX packer pads with 0, so the alpha byte is set explicitly rather than trusting IGNORE."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    rgba = img.convert("RGBA")
    return img.size[0], img.size[1], rgba.tobytes("raw", "BGRA")


class Upload:
    __slots__ = ("key", "w", "h", "data", "opaque", "done", "priority", "seq", "tick")

    def __init__(self, key, w, h, data, opaque, done, priority, seq, tick=False):
        self.key, self.w, self.h, self.data, self.opaque = key, int(w), int(h), data, bool(opaque)
        self.done, self.priority, self.seq, self.tick = done, priority, seq, bool(tick)


def _order(u):
    return u.priority, u.seq


class UploadQueue:
    """Pending uploads for the stage thread, newest wins per key, lowest priority first. ``put``
    may be called from any thread (the art workers post prepared bytes, §13.4 step 5; ``wake``
    then signals the stage thread); everything else runs on the stage thread only.

    The upload discipline is the module docstring's: ``ripen()`` hands over the ticks and the
    surfaces whose upload Commit is ``ready_s`` old (``done`` runs then; their keys are
    ``landed``); ``upload()`` is one upload wake (budgets, a Flush after each, then ``commit()``,
    the wake's own upload Commit); ``due()`` says whether the pacing (``gap_s`` after the device's
    last upload-carrying Commit) allows one now; ``next_wake_s()`` is when the stage thread must
    wake for the queue. ``run()`` is ``ripen()`` then, when due, ``upload()``.

    ``clock`` defaults to the device's ``now()`` (the clock of ``last_upload_commit``); ``gap_s``
    is seconds or a callable (the engine: two frames of the current P plus 1 ms), None for no
    pacing; ``commit`` is the upload Commit (the engine's ``StageCore.commit``), else the device's."""

    def __init__(self, device, budget_s: float = UPLOAD_BUDGET_S, clock=None, wake=None, *,
                 ready_s: float = READY_S, budget_bytes: int = UPLOAD_BUDGET_BYTES, gap_s=None, commit=None):
        self.dev = device
        self.budget_s = budget_s
        self.budget_bytes = int(budget_bytes)
        self.clock = clock or getattr(device, "now", None) or time.perf_counter
        self.wake = wake
        self.ready_s = float(ready_s)
        self.gap_s = gap_s
        self.commit = commit
        self.lock = threading.Lock()
        self.items = {}
        self.seq = 0
        self.landed = []
        self.aging = deque()              # (ripe at, key, surface, done), in upload-Commit order
        self._aging_keys = {}             # key -> entries in ``aging`` (``in_flight``)
        self._uploading = {}              # key -> items between ``items`` and ``aging`` (``in_flight``)
        self.stats = {"uploads": 0, "bytes": 0, "wakes": 0, "deferred": 0, "ms_max": 0.0, "commits": 0,
                      "ticks": 0, "ripened": 0, "bytes_max": 0, "paced": 0}

    def put(self, key, w, h, data, *, opaque=False, done=None, priority=0, tick=False):
        """Queue (or replace) the upload for ``key``; ``done(surface, key)`` runs on the stage
        thread once it is ready (``ripen``). ``tick``: no content (a scene's wake-up, §5.1 P9): it
        lands at the next wake without a surface (``done(None, key)``)."""
        with self.lock:
            self.seq += 1
            self.items[key] = Upload(key, w, h, data, opaque, done, priority, self.seq, tick)
        if self.wake is not None:
            try:
                self.wake()
            except Exception:
                pass

    def cancel(self, key):
        with self.lock:
            self.items.pop(key, None)

    def __len__(self):
        """Items still waiting for their upload (the aging ones are ``aging``)."""
        return len(self.items)

    def busy(self) -> bool:
        return bool(self.items) or bool(self.aging)

    def in_flight(self, key) -> bool:
        """``key``'s content is on its way (waiting for its upload, being uploaded and committed, or
        ripening): the scenes' art planners count it as resident, so no worker renders it again
        meanwhile. Any thread (three dict reads, in the order an item moves through them: an item
        is counted in the next dict before it leaves the previous one, so a reader on another
        thread never sees a gap)."""
        return key in self.items or self._uploading.get(key, 0) > 0 or self._aging_keys.get(key, 0) > 0

    def _count(self, table, key, step):
        left = table.get(key, 0) + step
        if left > 0:
            table[key] = left
        else:
            table.pop(key, None)

    # ------------------------------------------------------------------ pacing
    def _gap(self) -> float:
        g = self.gap_s
        if g is None:
            return 0.0
        return float(g()) if callable(g) else float(g)

    def gap_left(self, now=None) -> float:
        """Seconds until an upload Commit would not wait for the previous one (<= 0: now)."""
        last = getattr(self.dev, "last_upload_commit", None)
        if last is None or self.gap_s is None:
            return 0.0
        return last + self._gap() - (self.clock() if now is None else now)

    def due(self, now=None) -> bool:
        """Content waits and an upload wake may run now."""
        with self.lock:
            content = any(not u.tick for u in self.items.values())
        return content and self.gap_left(now) <= 1e-6

    def next_wake_s(self, now=None):
        """Seconds until the queue needs the stage thread (0: at once), or None."""
        now = self.clock() if now is None else now
        waits = []
        with self.lock:
            ticks = any(u.tick for u in self.items.values())
            content = any(not u.tick for u in self.items.values())
        if ticks:
            waits.append(0.0)
        if self.aging:
            waits.append(self.aging[0][0] - now)
        if content:
            waits.append(self.gap_left(now))
        return max(0.0, min(waits)) if waits else None

    # ------------------------------------------------------------------ the stage thread
    def ripen(self, now=None) -> list:
        """The ticks, then every surface whose upload Commit is ``ready_s`` old: ``done`` runs now
        (into the LRU), and the keys are returned (and kept in ``landed``) for the scene's reveal."""
        now = self.clock() if now is None else now
        out = []
        with self.lock:
            ticks = [u for u in self.items.values() if u.tick]
            for u in ticks:
                del self.items[u.key]
        for u in sorted(ticks, key=_order):
            if u.done is not None:
                u.done(None, u.key)
            out.append(u.key)
            self.stats["ticks"] += 1
        aging, keys = self.aging, self._aging_keys
        while aging and aging[0][0] <= now + 1e-6:
            _at, key, surf, done = aging.popleft()
            if done is not None:
                done(surf, key)                                # into the LRU first, then out of flight
            left = keys.get(key, 1) - 1
            if left > 0:
                keys[key] = left
            else:
                keys.pop(key, None)
            out.append(key)
            self.stats["ripened"] += 1
        self.landed = out
        return out

    def upload(self, budget_s: float | None = None, budget_bytes: int | None = None) -> int:
        """One upload wake: in priority order until 4 ms or 2.5 MB is spent (the first item always
        goes), each upload flushed at once, then the wake's own upload Commit. Returns the uploads
        made; their surfaces ripen ``ready_s`` after that Commit."""
        with self.lock:
            order = sorted((u for u in self.items.values() if not u.tick), key=_order)
        if not order:
            return 0
        budget = self.budget_s if budget_s is None else budget_s
        cap = self.budget_bytes if budget_bytes is None else int(budget_bytes)
        t0 = self.clock()
        n = nbytes = 0
        made = []
        taken = []                                             # keys counted in ``_uploading``
        self.stats["wakes"] += 1
        flush = getattr(self.dev, "flush", None)
        err = None
        try:
            try:
                for item in order:
                    if n and (self.clock() - t0 >= budget or nbytes + len(item.data) > cap):
                        self.stats["deferred"] += len(self.items)
                        break
                    with self.lock:
                        if self.items.get(item.key) is not item:
                            continue                           # replaced or cancelled meanwhile
                        # in flight before it leaves ``items`` (review nit S1: a planner on an art
                        # worker must never see it as neither waiting nor ripening)
                        self._count(self._uploading, item.key, +1)
                        taken.append(item.key)
                        self.items.pop(item.key)
                    surf = self.dev.create_surface(item.w, item.h, item.opaque, str(item.key))
                    try:
                        self.dev.upload(surf, item.w, item.h, item.data, str(item.key))
                    except BaseException:
                        self.dev.release(surf)
                        raise
                    if flush is not None:
                        flush()                                # the copy starts now
                    made.append((item.key, surf, item.done))
                    n += 1
                    nbytes += len(item.data)
                    self.stats["uploads"] += 1
                    self.stats["bytes"] += len(item.data)
            except BaseException as exc:                       # what was uploaded is still committed
                err = exc
            if made:
                try:
                    (self.commit or self.dev.commit)()         # the wake's upload Commit (content only)
                except BaseException:
                    if err is None:
                        raise
                self.stats["commits"] += 1
                ripe = self.clock() + self.ready_s
                for key, surf, done in made:
                    self.aging.append((ripe, key, surf, done))
                    self._count(self._aging_keys, key, +1)     # ripening before it stops uploading
        finally:
            for key in taken:
                self._count(self._uploading, key, -1)
        if err is not None:
            raise err
        self.stats["bytes_max"] = max(self.stats["bytes_max"], nbytes)
        self.stats["ms_max"] = max(self.stats["ms_max"], (self.clock() - t0) * 1000.0)
        return n

    def run(self, budget_s: float | None = None) -> int:
        """``ripen()`` (the keys in ``landed``), then one ``upload()`` when due. Returns the uploads."""
        self.ripen()
        if not self.due():
            with self.lock:
                if any(not u.tick for u in self.items.values()):
                    self.stats["paced"] += 1
            return 0
        return self.upload(budget_s)


class SolidCache:
    """G1-9: one shared opaque surface per (colour, size class); ``get`` creates on first use."""

    def __init__(self, device):
        self.dev = device
        self.surfaces = {}

    def get(self, rgb, w, h):
        key = (tuple(int(c) for c in rgb[:3]), int(w), int(h))
        s = self.surfaces.get(key)
        if s is None:
            w, h = key[1], key[2]
            b, g, r = key[0][2], key[0][1], key[0][0]
            data = bytes((b, g, r, 255)) * (w * h)
            s = self.dev.create_surface(w, h, True, f"solid{key}")
            self.dev.upload(s, w, h, data, "solid")
            self.surfaces[key] = s
        return s

    def release(self):
        for s in self.surfaces.values():
            self.dev.release(s)
        self.surfaces.clear()


class SurfaceLRU:
    """GPU surfaces by key: an LRU with pinning (the preload window) that releases on eviction."""

    def __init__(self, device, capacity: int = 2 * COVER_PAIRS):
        self.dev = device
        self.capacity = int(capacity)
        self.items = OrderedDict()
        self.pinned = set()
        self.evictions = 0

    def get(self, key):
        s = self.items.get(key)
        if s is not None:
            self.items.move_to_end(key)
        return s

    def put(self, key, surface):
        old = self.items.pop(key, None)
        if old is not None and old != surface:
            self.dev.release(old)
        self.items[key] = surface
        self._evict()

    def pin(self, keys):
        self.pinned = set(keys)
        self._evict()

    def _evict(self):
        over = len(self.items) - self.capacity
        if over <= 0:
            return
        for key in list(self.items):
            if over <= 0:
                break
            if key in self.pinned:
                continue
            self.dev.release(self.items.pop(key))
            self.evictions += 1
            over -= 1

    def release(self):
        for s in self.items.values():
            self.dev.release(s)
        self.items.clear()
        self.pinned.clear()


class ShadowSprite:
    """A fixed shadow layer: ``image`` (premultiplied-ready RGBA at 1/reduce) plus where it goes,
    in the element's own physical px at scale 1: ``offset`` of the stretched sprite's top-left,
    and ``scale`` (= reduce) for its transform."""

    __slots__ = ("image", "offset", "scale", "sigma_px", "reach_px")

    def __init__(self, image, offset, scale, sigma_px, reach_px):
        self.image, self.offset, self.scale = image, offset, scale
        self.sigma_px, self.reach_px = sigma_px, reach_px


def box_shadow(w_px: float, h_px: float, blur_px: float, alpha: float, *, offset_x_px: float = 0.0,
               offset_y_px: float = 0.0, rgb=(0, 0, 0), reduce: int = SHADOW_REDUCE) -> ShadowSprite:
    """CSS ``box-shadow: X Y BLUR rgba(rgb, alpha)`` around a ``w_px`` x ``h_px`` rectangle, in
    physical px (units x k). σ = BLUR / 2; the sprite reaches 3σ past the rectangle. Built at
    1/``reduce`` with PIL (GaussianBlur releases the GIL, §4.7.3); stretched by the compositor
    under LINEAR sampling, which a blur of this size tolerates (§12 "Why 1/8 is enough")."""
    from PIL import Image, ImageFilter
    sigma = blur_px / 2.0
    reach = 3.0 * sigma
    r = float(reduce)
    m = int(round(reach / r)) + 1
    rw, rh = max(1, int(round(w_px / r))), max(1, int(round(h_px / r)))
    mask = Image.new("L", (rw + 2 * m, rh + 2 * m), 0)
    mask.paste(255, (m, m, m + rw, m + rh))
    if sigma > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(sigma / r))
    a = int(round(max(0.0, min(1.0, alpha)) * 255))
    mask = mask.point(lambda v: v * a // 255)
    img = Image.new("RGBA", mask.size, tuple(int(c) for c in rgb[:3]) + (0,))
    img.putalpha(mask)
    return ShadowSprite(img, (offset_x_px - m * r, offset_y_px - m * r), r, sigma, reach)
