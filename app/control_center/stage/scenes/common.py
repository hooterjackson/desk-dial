"""What the explorer and Up next scenes share (DESKTOP_STAGE §4.4, §4.5, §7.5, §8.4, §12, §13.3, §14).

- ``Prepared``: the transient CPU cache of rendered sprite bytes (a job's output before it is
  uploaded). A scene's factory starts jobs at ``*_open`` t = 0 (``ambient_source`` is the
  engine's first call, before the capture), so the sprites the open needs are usually ready when
  ``build`` runs about 50 ms later and are uploaded synchronously there; later work goes through
  the upload queue. Entries are consumed when uploaded; 24 MB cap, oldest dropped.
- ``MusicLRU``: GPU residency (§4.5, §13.3, §14; WP8-R2). Covers (``("art", ...)``) live in the
  engine's LRU, every other scene sprite in a second LRU kept on the device object. Both are
  bounded **by bytes**: the second LRU at ``AUX_BYTES``, and the two together at
  ``SCENE_VRAM_BYTES`` (the §14 stage-VRAM guard of 256 MB less the solids, the frost and the
  host's own), oldest unpinned first. At scene close everything that is not a card or row
  surface or a static is released (``RELEASE_AT_CLOSE``: labels, loading tiles, ambient layers,
  the Up next column text, the exact-scale row sprites), §4.5, §4.9.
- ``SceneBase``: static sprites kept in the device's surface LRU under ``("static", name, k)``
  (re-used across opens while the device is warm), content binding through cached hot setters
  (``Visual.SetContent`` keeps the GIL, §4.7.1), the pin set, the art-service owner. A static
  that is missing **on the input path** is never created or uploaded there (§4.5 "an input
  commit never queues behind uploads", §4.7.1, G1-5; WP8-R10): ``static(..., sync=False)`` has
  the fast lane post it to the upload queue (its cached bytes, or rendered first), so nothing on
  the input path releases the GIL before the Commit, and the scene swaps it in when it lands. The
  statics' CPU bytes are rendered at a factory's t = 0 on the fast lane (``prepare_statics``),
  and build uploads the ones a detent can reach.
- ``AmbientPair``: layers A and B (§7.5, §12): 1/8 of the bleed box, scaled x 8 at
  (−160k, −160k), opacity 0.50 / 0.45 while showing; a focus change restarts the 200 ms debounce
  on a worker (the job's ``not_before``), the newest build lands and the layers crossfade over
  600 ms OUT; the first layer is set without a crossfade (BS:779-790). A layer's previous build
  (and every stale build) is released when it is replaced, so a scene holds two ambient layers.
  The restart is ``ArtService.debounce``: during a spin it wakes no worker (G1-5, R-k).
- ``program_legs`` and ``set_value`` (R-k, G1-4): a detent's plain legs programmed in one loop
  with ``Batch.to``'s exact arithmetic (same segments, twin and counters, less Python per leg),
  and a float set that is skipped when a finished animation already holds the value.
"""
from __future__ import annotations

import ctypes as C
import itertools
import threading
from collections import OrderedDict

from ... import render_music as RM
from ... import scene_music as SM
from .. import blur as B
from .. import clock as CK
from .. import com
from .. import curves as CV
from ..presenter import Scene
from ..surfaces import SurfaceLRU, box_shadow
from .art import Job, _PRIO_FOCUS, _PRIO_TICK

MB = 1024 * 1024
AUX_CAPACITY = 512                    # entries: a backstop only, the bytes decide
AUX_BYTES = 64 * MB                   # labels, rows, loading tiles, ambient layers, statics
SCENE_VRAM_BYTES = 200 * MB           # covers + the above (§14: <= 256 MB with solids, frost, host)
DEFAULT_BYTES = 1 * MB                # a surface whose size was not recorded
RELEASE_AT_CLOSE = frozenset({"label", "load", "ambient", "left", "rowsharp", "tick"})


def key_kind(key):
    return key[0] if isinstance(key, tuple) and key else None


class MusicLRU:
    """The scenes' view of GPU residency (see the module docstring): the covers in the engine's
    LRU (the §4.5 "64 cover-surface pairs"), the rest in a second LRU on the device object (it
    lives and dies with the device: a teardown releases every surface, §4.2, §4.3), and the bytes
    of every surface put through here (``sizes``, on the device too). Pinning and lookups route by
    key; ``items`` lists both."""

    def __init__(self, covers, dev, art=None, uploads=None):
        self.covers = covers
        self.dev = dev
        self.art = art
        self.uploads = uploads            # the upload queue: a key in flight counts as resident (``in``)
        aux = getattr(dev, "_music_aux_lru", None)
        if aux is None:
            aux = SurfaceLRU(dev, capacity=AUX_CAPACITY)
            try:
                dev._music_aux_lru = aux
            except Exception:
                pass
        sizes = getattr(dev, "_music_sizes", None)
        if sizes is None:
            sizes = {}
            try:
                dev._music_sizes = sizes
            except Exception:
                pass
        self.aux = aux
        self.sizes = sizes
        self.evicted_bytes = 0

    def _of(self, key):
        return self.covers if key_kind(key) == "art" else self.aux

    def get(self, key):
        return self._of(key).get(key)

    def put(self, key, surface, nbytes=None):
        """``surface`` for ``key``; ``nbytes`` from the caller, else the art service's record of
        the upload, else ``DEFAULT_BYTES``. Then the byte bounds are applied."""
        if not nbytes and self.art is not None:
            try:
                nbytes = self.art.upload_bytes(key)
            except Exception:
                nbytes = None
        self.sizes[key] = int(nbytes) if nbytes else DEFAULT_BYTES
        self._of(key).put(key, surface)
        self.trim()

    def pin(self, keys):
        cov = {key for key in keys if key_kind(key) == "art"}
        self.covers.pin(cov)
        self.aux.pin(set(keys) - cov)

    @property
    def items(self):
        return list(self.covers.items) + list(self.aux.items)

    def __contains__(self, key):
        """Resident, or on its way through the upload queue (S1: an upload waits for its paced wake
        and ripens a frame after its Commit; the art planners must not render it again meanwhile)."""
        if key in self._of(key).items:
            return True
        up = self.uploads
        in_flight = getattr(up, "in_flight", None) if up is not None else None
        return bool(in_flight is not None and in_flight(key))

    # ------------------------------------------------------------------ bytes
    def bytes_of(self, lru) -> int:
        sizes = self.sizes
        return sum(sizes.get(k, DEFAULT_BYTES) for k in lru.items)

    def total_bytes(self) -> int:
        return self.bytes_of(self.covers) + self.bytes_of(self.aux)

    def trim(self):
        """The byte bounds: the second LRU at ``AUX_BYTES``, both at ``SCENE_VRAM_BYTES`` (the
        covers first, then the rest), oldest unpinned first."""
        aux_b = self.bytes_of(self.aux)
        if aux_b > AUX_BYTES:
            aux_b -= self._evict(self.aux, aux_b - AUX_BYTES)
        cov_b = self.bytes_of(self.covers)
        over = cov_b + aux_b - SCENE_VRAM_BYTES
        if over > 0:
            over -= self._evict(self.covers, over)
        if over > 0:
            self._evict(self.aux, over)
        if len(self.sizes) > 2 * (len(self.aux.items) + len(self.covers.items)) + 256:
            live = set(self.aux.items) | set(self.covers.items)
            for k in [k for k in self.sizes if k not in live]:
                del self.sizes[k]

    def _evict(self, lru, need) -> int:
        freed = 0
        for key in list(lru.items):
            if freed >= need:
                break
            if key in lru.pinned:
                continue
            s = lru.items.pop(key)
            lru.dev.release(s)
            lru.evictions += 1
            freed += self.sizes.pop(key, DEFAULT_BYTES)
        self.evicted_bytes += freed
        return freed

    def drop(self, key) -> bool:
        """Release ``key``'s surface now (a replaced ambient layer, a closed scene's labels)."""
        lru = self._of(key)
        s = lru.items.pop(key, None)
        self.sizes.pop(key, None)
        if s is None:
            return False
        lru.dev.release(s)
        return True

    def release_kinds(self, kinds):
        """Release every unpinned surface of the second LRU whose key kind is in ``kinds``."""
        for key in list(self.aux.items):
            if key_kind(key) in kinds and key not in self.aux.pinned:
                self.drop(key)


PREPARED_BYTES = 24 * 1024 * 1024
STATIC_CPU_BYTES = 32 * 1024 * 1024
_STATIC_CPU = OrderedDict()          # static key -> (w, h, bytes, opaque); any thread, under the lock
_STATIC_CPU_BYTES = [0]
_STATIC_SIZES = {}                   # static key -> (w, h); never trimmed (a few bytes per sprite)
_STATIC_LOCK = threading.Lock()
_OWNER_IDS = itertools.count(1)
_EPS = 1e-9                          # animation.EPS: an equal target changes nothing


# --------------------------------------------------------------------------- the detent's legs (R-k)
def _plain_legs_ok(batch) -> bool:
    """``program_legs`` needs the absolute begin mode (G1-8) and the builder's hot-path state."""
    return (getattr(batch, "mode", None) == CK.BEGIN_ABSOLUTE and hasattr(batch, "_fc")
            and hasattr(batch, "_hr") and hasattr(batch, "max_end"))


def program_legs(batch, legs, curve="OUT") -> int:
    """``batch.to(prop, target, ms, curve)`` for every ``(prop, target, ms)`` of ``legs``: the plain
    legs of a detent (from the twin at t1, the full duration, no anchor, delay, ``v_from`` or
    ``force``), programmed in one loop instead of one builder call each (R-k, G1-4 "the builder
    batches"). The arithmetic is ``Batch.to``'s, operation for operation (``lead`` is 0.0 and
    ``0.0 + x == x``), so the segments, the begin time, the twin (``prop.func``), ``max_end``, the
    counters and the HRESULT accumulation are exactly what the builder would have made; an equal
    target is skipped (G1-4). Outside the absolute begin mode it is ``batch.to`` per leg. Returns
    the calls made."""
    if not legs:
        return 0
    if not _plain_legs_ok(batch):
        n = 0
        for prop, target, ms in legs:
            n += batch.to(prop, target, ms, curve)
        return n
    t1 = batch.t1
    freq = batch.freq
    fr, fb, fc, fe = batch._fr, batch._fb, batch._fc, batch._fe
    table_for = CV.table_for
    tween = CV.Tween
    bad = 0
    calls = anims = skipped = jumped = 0
    max_end = batch.max_end
    plain_end = getattr(batch, "plain_end", None)       # every leg here starts at t1 (S3's plain span)
    durs = {}
    for prop, target, ms in legs:
        target = float(target)
        func = prop.func
        in_flight = type(func) is tween                 # the common case: Tween.target / .value inlined
        if abs(target - (func.v1 if in_flight else func.target)) <= _EPS:
            skipped += 1
            continue
        de = durs.get(ms)
        if de is None:
            dur = ms / 1000.0
            de = durs[ms] = (dur, t1 + int(round(dur * freq)))
        dur, end = de
        if end <= t1:                                   # never for a detent's durations; the builder's rule
            jumped += batch.jump(prop, target)          # (the jump counts its own calls)
            continue
        if in_flight:                                   # ``Tween.value(t1)``, the same expression
            x = (t1 - func.begin) / func.freq - func.start
            if x <= 0.0:
                v0 = func.v0
            elif x >= func.dur:
                v0 = func.v1
            else:
                v0 = func.v0 + func.d * func.tab.eval(x / func.dur)
        else:
            v0 = func.value(t1)
        tab = table_for(curve, prop.kind, target - v0, prop.size)
        a = prop.take_animation()
        hr = fr(a) | fb(a, t1)
        d = target - v0
        k1 = d / dur
        k2 = k1 / dur
        k3 = k2 / dur
        rows = tab.rows
        for u0, ca, cb, cc, ce in rows:
            hr |= fc(a, u0 * dur, v0 + d * ca, k1 * cb, k2 * cc, k3 * ce)
        hr |= fe(a, dur, target)
        binds = prop.fbind
        for fn, ptr in binds:
            hr |= fn(ptr, a)
        if hr < 0:
            bad |= hr
        prop.func = tween(t1, freq, 0.0, dur, v0, target, tab)
        if max_end is None or end > max_end:
            max_end = end
        if plain_end is None or end > plain_end:
            plain_end = end
        calls += 3 + len(rows) + len(binds)
        anims += 1
    if bad:
        batch._hr |= bad
    batch.max_end = max_end
    if anims:
        batch.plain_end = plain_end
    batch.calls += calls
    batch.anims += anims
    batch.skipped += skipped
    return calls + jumped


def set_value(batch, prop, value) -> int:
    """``batch.jump(prop, value)``, skipped when the property already shows ``value`` for good: a
    float set to it, or an animation that has ended on it before the first frame that can show
    this batch (the predicted commit frame, at or before t1; DWM holds ``End``'s value, §4.6.1).
    Nothing visible changes; the twin keeps the finished function (R-k: no call for an unchanged
    property)."""
    f = prop.func
    if f.kind != "const":
        end = f.end_tick
        if end is not None and abs(f.target - float(value)) <= _EPS:
            first = batch.t1
            fc = getattr(batch, "f_commit", None)
            if fc is not None and fc < first:
                first = fc
            if end <= first:
                batch.skipped += 1
                return 0
    return batch.jump(prop, value)


def static_key(name, k, extra=()):
    return ("static", name, round(float(k), 4)) + tuple(extra)


def static_cpu(key):
    with _STATIC_LOCK:
        v = _STATIC_CPU.get(key)
        if v is not None:
            _STATIC_CPU.move_to_end(key)
        return v


def render_static(key, make):
    """``make()`` (a ``render_music.Sprite`` or an RGB image) as upload bytes, kept in the
    process-wide CPU cache (32 MB, oldest dropped) so a device re-creation re-uploads without
    rendering. Any thread."""
    out = make()
    if isinstance(out, RM.Sprite):
        cpu = (out.size[0], out.size[1], out.bgra(), False)
    else:
        cpu = (out.size[0], out.size[1], RM.opaque_bgra(out), True)
    with _STATIC_LOCK:
        _STATIC_SIZES[key] = (cpu[0], cpu[1])
        old = _STATIC_CPU.pop(key, None)
        if old is not None:
            _STATIC_CPU_BYTES[0] -= len(old[2])
        _STATIC_CPU[key] = cpu
        _STATIC_CPU_BYTES[0] += len(cpu[2])
        while _STATIC_CPU_BYTES[0] > STATIC_CPU_BYTES and len(_STATIC_CPU) > 1:
            _k, v = _STATIC_CPU.popitem(last=False)
            _STATIC_CPU_BYTES[0] -= len(v[2])
    return cpu


def prepare_statics(art, specs):
    """A factory's t = 0: the CPU bytes of every static in ``specs`` (``[(key, make)]``) that is
    not cached yet, on the fast lane (never on the stage thread)."""
    if art is None:
        return 0
    n = 0
    for key, make in specs:
        if static_cpu(key) is not None:
            continue

        def run(key=key, make=make):
            if static_cpu(key) is None:
                render_static(key, make)
            return None
        art.add(Job(("staticprep",) + key, (3, 9), run))
        n += 1
    return n


class Prepared:
    """Rendered sprite bytes waiting for an upload (see the module docstring)."""

    def __init__(self, budget=PREPARED_BYTES):
        self.budget = budget
        self._lock = threading.Lock()
        self._items = OrderedDict()
        self._bytes = 0

    def put(self, key, w, h, data, opaque):
        with self._lock:
            old = self._items.pop(key, None)
            if old is not None:
                self._bytes -= len(old[2])
            self._items[key] = (int(w), int(h), data, bool(opaque))
            self._bytes += len(data)
            while self._bytes > self.budget and len(self._items) > 1:
                _k, v = self._items.popitem(last=False)
                self._bytes -= len(v[2])

    def take(self, key):
        with self._lock:
            v = self._items.pop(key, None)
            if v is not None:
                self._bytes -= len(v[2])
            return v

    def __contains__(self, key):
        with self._lock:
            return key in self._items

    def __len__(self):
        return len(self._items)


class PreparedQueue:
    """An upload target that only keeps the bytes (a factory's t = 0 jobs, before the device and
    the scene exist). Same ``put`` signature as ``surfaces.UploadQueue``."""

    def __init__(self, prepared: Prepared):
        self.prepared = prepared

    def put(self, key, w, h, data, *, opaque=False, done=None, priority=0, tick=False):
        if not tick:
            self.prepared.put(key, w, h, data, opaque)


class SceneBase(Scene):
    """Common plumbing (see the module docstring)."""

    def __init__(self, ctx, payload, art=None, prepared=None):
        super().__init__(ctx, payload)
        self.art = art
        self.prepared = prepared if prepared is not None else Prepared()
        self.k = ctx.layout.k
        self.owner = f"{self.surface}#{next(_OWNER_IDS)}"
        self.dev = ctx.device
        self.tree = ctx.tree
        self.lru = MusicLRU(ctx.lru, ctx.device, art, ctx.uploads)
        self.uploads = ctx.uploads
        self._fn_content = {}
        self._fn_matrix = {}
        self.pins = set()
        self._pinned = None
        self.static_keys = set()
        self._static_waiting = set()
        self.closed = False
        self.surfaces = []                      # scene-owned surfaces released at close
        self.counters = {"sync_uploads": 0, "landed": 0, "binds": 0, "recycled": 0, "grown": 0,
                         "static_async": 0}

    # ------------------------------------------------------------------ surfaces
    def done(self, surface, key):
        """An upload landed (stage thread): into the surface LRU; after the scene closed, what
        ``RELEASE_AT_CLOSE`` names is released at once instead."""
        if self.closed and key_kind(key) in RELEASE_AT_CLOSE:
            self.dev.release(surface)
            return
        self.lru.put(key, surface)

    def static_key(self, name, extra=()):
        return static_key(name, self.k, extra)

    def static(self, name, make, extra=(), *, sync=True):
        """A static sprite's surface: the LRU's; else, with ``sync`` (build, open, an upload
        landing), rendered once per (name, k) (or taken from the CPU cache) and uploaded now;
        without ``sync`` (the input path), None: the sprite is posted to the upload queue and
        lands in ``uploads_ready`` under its key (see the module docstring). ``make()`` returns
        a ``render_music.Sprite`` or an RGB image."""
        key = self.static_key(name, extra)
        s = self.lru.get(key)
        if s is not None:
            self.static_keys.add(key)
            return s
        if not sync:
            self._static_async(key, make)
            return None
        cpu = static_cpu(key) or render_static(key, make)
        w, h, data, opaque = cpu
        s = self.dev.create_surface(w, h, opaque, str(key))
        self.dev.upload(s, w, h, data, str(key))
        self.lru.put(key, s, w * h * 4)
        self.static_keys.add(key)
        return s

    def _static_async(self, key, make):
        self.static_keys.add(key)                          # pinned once it lands
        if key in self._static_waiting:
            return
        self._static_waiting.add(key)
        self.counters["static_async"] += 1
        uploads, done = self.uploads, self._static_done

        def run():
            w, h, data, opaque = static_cpu(key) or render_static(key, make)
            uploads.put(key, w, h, data, opaque=opaque, done=done, priority=0)
            return None
        if self.art is not None:
            # posted from the fast lane, never from here: ``UploadQueue.put`` wakes the stage with
            # ``SetEvent``, a GIL-releasing call that must not come before the input's Commit (G1-5)
            self.art.add(Job(("staticjob",) + key, (_PRIO_FOCUS, 0), run, owner=self.owner))
        else:
            run()                                          # no workers (a bench without art)

    def _static_done(self, surface, key):
        self._static_waiting.discard(key)
        wh = _STATIC_SIZES.get(key)
        self.lru.put(key, surface, (wh[0] * wh[1] * 4) if wh else None)

    def upload_statics(self, names):
        """Build: upload the statics whose CPU bytes are already cached (the factory's t = 0
        render), so the input path finds them resident; the rest go the input path's way."""
        n = 0
        for name, extra in names:
            key = self.static_key(name, extra)
            if self.lru.get(key) is not None:
                self.static_keys.add(key)
                continue
            cpu = static_cpu(key)
            if cpu is None:
                continue
            w, h, data, opaque = cpu
            s = self.dev.create_surface(w, h, opaque, str(key))
            self.dev.upload(s, w, h, data, str(key))
            self.lru.put(key, s, w * h * 4)
            self.static_keys.add(key)
            n += 1
        return n

    def static_size(self, name, extra=()):
        with _STATIC_LOCK:
            return _STATIC_SIZES.get(self.static_key(name, extra))

    def own_surface(self, img_or_sprite, name):
        """A scene-owned surface from an image (released at close)."""
        if isinstance(img_or_sprite, RM.Sprite):
            w, h = img_or_sprite.size
            data, opaque = img_or_sprite.bgra(), False
        else:
            w, h = img_or_sprite.size
            data, opaque = RM.opaque_bgra(img_or_sprite), True
        s = self.dev.create_surface(w, h, opaque, name)
        self.dev.upload(s, w, h, data, name)
        self.surfaces.append(s)
        return s

    def release_own(self, surface):
        """Release a scene-owned surface before close (it is no longer shown)."""
        if surface in self.surfaces:
            self.surfaces.remove(surface)
            self.dev.release(surface)

    def surface_for(self, key, *, sync=False):
        """The GPU surface of an upload key: the LRU's; with ``sync``, a prepared sprite is
        uploaded now (build only, never on a detent)."""
        s = self.lru.get(key)
        if s is not None or not sync:
            return s
        v = self.prepared.take(key)
        if v is None:
            return None
        w, h, data, opaque = v
        s = self.dev.create_surface(w, h, opaque, str(key))
        self.dev.upload(s, w, h, data, str(key))
        self.lru.put(key, s, w * h * 4)
        self.counters["sync_uploads"] += 1
        return s

    def job(self, key, prio, fn, **kw):
        """A job whose output lands in the LRU (and wakes this scene's ``uploads_ready``)."""
        return Job(key, prio, fn, uploads=self.uploads, done=self.done, **kw)

    # ------------------------------------------------------------------ hot setters
    def content_now(self, visual, surface):
        """Outside a batch (build)."""
        self.tree.content(visual, surface)

    def set_content(self, batch, visual, surface):
        fn = self._fn_content.get(visual.ptr)
        if fn is None:
            fn = self._fn_content[visual.ptr] = self.dev.fn("Visual.SetContent", visual.ptr)
        return batch.call(fn, visual.ptr, surface or None)

    def set_matrix(self, batch, visual, sx, sy, dx, dy):
        fn = self._fn_matrix.get(visual.ptr)
        if fn is None:
            fn = self._fn_matrix[visual.ptr] = self.dev.fn("Visual.SetTransform.matrix", visual.ptr)
        m = com.D2D_MATRIX_3X2_F(float(sx), 0.0, 0.0, float(sy), float(dx), float(dy))
        return batch.call(fn, visual.ptr, C.byref(m))

    def sprite_visual(self, parent, name, surface, x, y, *, opacity=None, above=None):
        v = self.tree.visual(name, opacity=opacity is not None, content=surface)
        self.tree.offset(v, x, y)
        if above is None:
            self.tree.add(parent, v)
        else:
            self.tree.add(parent, v, above=above)
        prop = self.tree.opacity(v, opacity) if opacity is not None else None
        return v, prop

    def tick_job(self, tag, at_s, *, replace=None):
        """Wake this scene at ``at_s`` (perf seconds): a 1 x 1 upload on the fast lane (never
        behind a fetch, WP8-R1) whose landing reaches ``uploads_ready`` as ``("tick", owner, n)``;
        the surface is released at once. The stage thread keeps no timer (§5.1 P8, P9)."""
        self._ticks = getattr(self, "_ticks", 0) + 1
        key = ("tick", self.owner, self._ticks)
        self.tick_tags = getattr(self, "tick_tags", {})
        self.tick_tags[key] = tag
        dev = self.dev

        def released(surface, _key):
            dev.release(surface)
        if self.art is not None:
            job = Job(key, _PRIO_TICK, lambda: RM.Sprite.new(1, 1), uploads=self.uploads, done=released,
                      owner=self.owner, not_before=at_s)
            if replace is None:
                self.art.add(job)
            elif self.art.debounce(job, replace=replace):       # a restart wakes no worker (R-k)
                self.tick_tags.pop(replace, None)
        return key

    def repin(self, keys):
        """Pin exactly ``keys`` plus the statics (only when the set changed)."""
        if self.closed:
            return
        want = frozenset(keys) | frozenset(self.static_keys)
        if want != self._pinned:
            self._pinned = want
            self.lru.pin(want)

    def release(self):
        """Close (§4.5, §4.9): the art jobs of this scene stop, its own surfaces go, the statics
        stay pinned, and every ``RELEASE_AT_CLOSE`` surface is released (card and row surfaces
        stay in the LRU)."""
        self.closed = True
        if self.art is not None:
            try:
                self.art.forget(self.owner)
            except Exception:
                pass
        for s in self.surfaces:
            try:
                self.dev.release(s)
            except Exception:
                pass
        self.surfaces = []
        try:
            self._pinned = frozenset(self.static_keys)
            self.lru.pin(self._pinned)
            self.lru.release_kinds(RELEASE_AT_CLOSE)
        except Exception:
            pass


def shadow_sprite(w_px, h_px, blur_units, alpha, offset_units, k):
    """A fixed shadow layer (§7.3, §8.2): ``0 {offset}px {blur}px rgba(0,0,0,alpha)`` of a
    ``w_px`` x ``h_px`` rectangle, at 1/4 resolution (``surfaces.box_shadow``)."""
    return box_shadow(w_px, h_px, blur_units * k, alpha, offset_y_px=offset_units * k)


class AmbientPair:
    """Ambient layers A and B (see the module docstring)."""

    def __init__(self, scene: SceneBase, parent, opacity: float):
        self.scene = scene
        self.opacity = float(opacity)
        tree, lay = scene.tree, scene.ctx.layout
        sc, dx, dy = B.ambient_placement(lay.k)
        self.size = B.ambient_size(lay.k, (lay.W, lay.H))
        self.layers = []
        for name in ("ambient.a", "ambient.b"):
            v = tree.visual(name, opacity=True)
            tree.matrix(v, sc, sc, dx, dy)
            tree.add(parent, v)
            self.layers.append([v, tree.opacity(v, 0.0), None])      # visual, opacity, key
        self.front = 0
        self.gen = 0
        self.want = None                    # the art key the newest request is for
        self.pending_job = None
        self.shown = None                   # the art key the front layer shows ("" = nothing)
        self.first_surface = None           # the open's layer (scene-owned) while layer A shows it
        self.first_src = None               # what the engine built that layer from at t = 0

    def first(self, image, art_key, src=None):
        """The first layer at open, without a crossfade (§4.9): the capture worker's build of
        ``src`` (the factory's t = 0 ``ambient_source``). Without an image (a capture timeout)
        nothing shows and the first request builds the layer."""
        self.first_src = src
        if image is None:
            self.shown = ""
            self.want = "" if not art_key else None
            return
        s = self.scene.own_surface(image, "ambient.first")
        v, op, _ = self.layers[0]
        self.scene.content_now(v, s)
        op.set_now(self.opacity)
        self.shown = art_key
        self.want = art_key
        self.first_surface = s

    def refresh_if_first_stale(self, plan, now_s) -> bool:
        """At open, when ``plan``'s art exists already (its sprites came from the t = 0 prefetch)
        but the first layer was built before it, from ``art_bg``: build again from the 64 px copy
        (§7.5, §12; WP8-R4)."""
        art = self.scene.art
        if art is None or plan is None or plan.kind not in ("cover", "mosaic", "single"):
            return False
        th = art.thumb(plan.key)
        if th is None or self.first_src is th:
            return False
        self.refresh(plan, now_s)
        return True

    def request(self, plan, now_s, debounce_ms=SM.AMBIENT_DEBOUNCE_MS):
        """Restart the debounce for ``plan`` (None = no focused item: fade to nothing)."""
        key = plan.key if plan is not None else ""
        if key == self.want:
            return
        self.want = key
        self.gen += 1
        gen = self.gen
        scene = self.scene
        if scene.art is None:
            return
        lay = scene.ctx.layout
        art = scene.art
        size = (lay.W, lay.H)
        k = lay.k

        def build(plan=plan):
            if plan is None:
                return RM.Sprite.new(1, 1)                  # a tick: fade to nothing
            src = art.thumb(plan.key)
            if src is None:
                if plan.kind == "generated":
                    g0, g1, _ink = RM.GEN_PALETTE[SM.gen_index(plan.title, plan.artist)]
                    src = RM.linear_gradient_160(64, g0, g1)
                else:
                    src = int(plan.bg) or SM.LOADING_EMPTY_BG
            return B.ambient(src, k, size)

        old, self.pending_job = self.pending_job, ("ambient", scene.owner, gen)
        job = scene.job(self.pending_job, _PRIO_TICK, build, owner=scene.owner,
                        not_before=now_s + debounce_ms / 1000.0, tag=("ambient", key))
        scene.art.debounce(job, replace=old)                # the debounce restarts: newest wins (§7.5)

    def refresh(self, plan, now_s):
        """The art of the item the ambient shows became ready (its 64 px copy exists now): build
        again with the debounce (§7.5 "a change of the source"; §12: ``art_bg`` only while nothing
        is cached)."""
        self.want = None
        self.request(plan, now_s)

    def landed(self, batch, key) -> bool:
        """An ambient build landed: crossfade if it is the newest (else it is dropped). The layer
        it replaces loses its previous build at once (it is never shown again, WP8-R2)."""
        if not (isinstance(key, tuple) and key and key[0] == "ambient" and key[1] == self.scene.owner):
            return False
        gen = key[2]
        lru = self.scene.lru
        surface = lru.get(key)
        if gen != self.gen or surface is None:
            lru.drop(key)                                   # a stale build: never shown
            return True
        back = 1 - self.front
        v, op, old = self.layers[back]
        fv, fop, _ = self.layers[self.front]
        if self.want == "":
            batch.to(fop, 0.0, SM.AMBIENT_MS, "OUT")
            batch.to(op, 0.0, SM.AMBIENT_MS, "OUT")
            self.shown = ""
            lru.drop(key)                                   # the 1 x 1 "nothing"
            return True
        self.scene.set_content(batch, v, surface)
        batch.to(op, self.opacity, SM.AMBIENT_MS, "OUT", v_from=0.0, force=True)
        batch.to(fop, 0.0, SM.AMBIENT_MS, "OUT")
        self.layers[back][2] = key
        if old is not None and old != key:
            lru.drop(old)
        if back == 0 and self.first_surface is not None:
            self.scene.release_own(self.first_surface)
            self.first_surface = None
        self.front = back
        self.shown = self.want
        return True

    def keys(self):
        return [layer[2] for layer in self.layers if layer[2] is not None]
