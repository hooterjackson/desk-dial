"""The window picker's chrome on DirectComposition: step 3 (DESKTOP_STAGE §9.9, §22 Q2; lead ruling
R-h; CAROUSEL.md §12.4).

What moves here: every piece of the picker that is not a live window, as **prepared surfaces with
compositor-run animations**: the two card shadows (side and focus, crossfading), the selection frame,
the #111 shade, the badge, the snap chip, the placeholder face, the label, the dots and the marker,
the snap tray (slots, borders, glyphs, badges, captions) and the fly's shadow (S5-4 returns with the
GPU chrome). The live DWM thumbnails stay DWM thumbnails, stepped per frame by ``NanoD-carousel``
(``carousel.CarouselEngine``); nothing here touches them.

**Mirror, not re-animation.** The carousel's ``CarouselMachine`` stays the single source of motion.
At every event that retargets it (open, turn, end bump, tray reveal, slot looks, exit, label swap,
snap) the engine calls ``sync(view)``, and each chrome property becomes the machine's own tween:
the same start, target, duration, curve and **the same begin time** (the machine's ``t0``, a
``time.perf_counter`` value, converted to compositor ticks), fitted by the stage builder within
§4.6.2's bounds (``animation.Batch.to`` with ``anchor`` and ``v_from``). A begin time already past
when DWM first samples the commit drops the start of the curve (MS-3), so the chrome shows exactly
the value the thumbnails sample at every displayed frame (the thumbnails at the predicted display
time, K4 §5 P2). A property whose tween did not change since the last sync costs nothing (G1-4,
R-k: unchanged or invisible properties are not animated; pooled objects only; one Commit per event).

Each chrome property is linear in exactly one machine tween, by construction of the tree:

    root (opacity = root)                              LINEAR + SOFT, LAYER group opacity
      tray (opacity = tray_op) > tray.pos (OffsetY = tray_y) > tray.sc (scale = tray_sc) > slots
      group (opacity = group, OffsetY = shift)
        cards (OffsetX = bump, two legs)
          card.wrap (clip: the nearer card's far edge)   one per visible card, far -> near
            card.pos (OffsetX = x, opacity = own op x closed factor)
              card.sc (scale = s) > card.rise (OffsetY = rise) > card.es (scale = enter scale)
                side shadow (1 - selw), focus shadow (selw), face, badge, chip, shade (shade), frame (0.9 selw)
        label (opacity = label_alpha) > label shadow, label text
        dots > row, marker (OffsetX = marker)
      fly (OffsetX, OffsetY, opacity) > fly.sc (scale) > fly shadow

**Occlusion (AR-12's "catch").** Every chrome visual lies above every thumbnail (the chrome window
is above the host), so a farther card's chrome must not darken the nearer card's thumbnail. Each
card's chrome is clipped to the half-plane beyond its nearer neighbour's far edge (an animated
``IDCompositionRectangleClip`` edge); CSS hides it there (deviation WP7c-D3: compose_chrome keeps
``1 - cover`` of it under a translucent nearer card; the clip keeps none, except under a closed
card, which is not clipped). The edge is one machine tween whenever the neighbour's X and scale
retarget together (every turn from rest) or only its enter scale runs (the open). In the mixed cases
(fast turns on the 32:9 table, where a far card's scale target stays 0.40 while its previous scale
motion still runs; a turn during the open's enter) it is one curve anchored at the latest retarget,
from the edge's exact value there to its exact target (``metrics()['clip_approx']``; within 2.3 px of
the exact edge in the tests, on far, dim cards).

**Uploads never ride a detent's Commit.** A Commit that follows a surface upload at once waits for the
copy (about 3 ms here); a frame later it costs about 0.1-0.2 ms (``Surfaces``). So sprites are
uploaded ahead, in frames without an event (the engine's prefetch: the selected label, the badges
of the cards the machine holds at the level each will use, the chips, the tray's glyphs), each
followed by the D3D11 context's Flush, and a surface is shown only once it is a frame old; a sprite
that was not ready is left out of the batch (the card keeps what it showed) and the next frame syncs
it in (``want_sync``, which keeps the engine's loop awake until then).

**Pooled objects are made in quiet frames** (K4 §4.7.1, §9.10): the tree and 14 card slots at the
first open; then ``grow_pool`` adds one slot per event-free frame while fewer than ``SLOT_SPARE`` are
free and the open's windows could use more, so a detent's sync reuses a slot. A burst that still
finds no free slot grows one inside the sync (``slots_grown_in_sync``, 0 in the benches).

**Device.** The chrome has its own D3D11 + DirectComposition device on ``NanoD-carousel`` (the thread
that owns the picker's windows), created at the first open or by a knob touch (``warm_async``), kept
while the picker is used and released after 600 s without one (``device.DevicePolicy``, §4.2).
Measured headlessly on this PC: a second device next to a warm stage device costs about 16 MB
private and 17-28 ms (WP7c-D1). A knob touch never holds ``NanoD-carousel`` (the thread that answers
``show()``'s handshake): the slow half, ``D3D11CreateDevice``, runs on a short-lived worker
(``picker_device.prepare``) and the carousel thread adopts it (the DirectComposition device, about
1 ms); an open that arrives meanwhile waits for it after its handshake. Every release keeps the
policy in step (a monitor change, a failed call, the idle release, close), so the next open or touch
makes a device again. Device loss (§4.3): the engine closes nothing; it switches the open picker to
the CPU chrome at once (R-h) and the next open tries the GPU again.

Hosted in the stage package so the static rule holds (K4 §4.1): ``control_center.carousel`` never
names this package. ``install()`` (called from the one wiring point, ``standalone.py``) hands
``factory`` to ``carousel.install_gpu_chrome``. ``NANOD_PICKER_CHROME=cpu`` keeps the CPU chrome.
"""
from __future__ import annotations

import ctypes as C
import threading
import time
from collections import OrderedDict, deque

from . import animation as AN
from . import clock as CK
from . import com
from . import curves as CV
from .device import DevicePolicy
from .tree import OPACITY_VISUAL3, Prop, Tree

BIG = 1.0e6                    # an unbounded clip edge, px
READY_S = 0.004                # a surface is shown this long after its upload (see Surfaces)
POOL = 14                      # card slots built at the first open (then grown in quiet frames, grow_pool)
SLOT_SPARE = 6                 # grow_pool keeps this many slots free (six detents without a quiet frame)
WARM_JOIN_S = 1.0              # an open waits at most this long for a knob touch's device half
SURFACES = 160                 # prepared sprite surfaces kept per device (LRU)
EPS = 1e-9
LEVEL_SPLIT = 0.75             # a card whose scale stays below this shows the half-resolution badge / chip
CURVE_NAMES = {(0.22, 1.0, 0.36, 1.0): "OUT", (0.4, 0.0, 1.0, 1.0): "IN", (0.34, 1.45, 0.64, 1.0): "SPR",
               (0.25, 0.1, 0.25, 1.0): "EASE"}

# IDCompositionRectangleClip (dcomp.h declares each value overload before its animation overload;
# MSVC puts the later one first, RF2 §2.3): SetLeft(anim) 3, SetLeft(float) 4, SetTop 5/6, SetRight
# 7/8, SetBottom 9/10. Kept here (not in com.SLOTS) so no other module's slot table changes; the
# picker self-test proves each S_OK on a device without a target, and the NULL discriminator.
CLIP_SLOTS = {"Clip.SetLeft.anim": 3, "Clip.SetLeft": 4, "Clip.SetTop.anim": 5, "Clip.SetTop": 6,
              "Clip.SetRight.anim": 7, "Clip.SetRight": 8, "Clip.SetBottom.anim": 9, "Clip.SetBottom": 10}
_CLIP_PROTOS = {}
CONTEXT_FLUSH_SLOT = 111       # ID3D11DeviceContext::Flush (d3d11.h; Map 14, Unmap 15, UpdateSubresource 48)


def curve_name(ease) -> str:
    """The stage curve (§0.4) of a carousel ``CubicBezier`` (its ``params``)."""
    params = tuple(round(float(v), 6) for v in getattr(ease, "params", (0.22, 1.0, 0.36, 1.0)))
    return CURVE_NAMES.get(params, "OUT")


def clip_fn(dev, name, clip):
    """A callable ``f(clip, value_or_animation) -> HRESULT`` for a RectangleClip slot: GIL-keeping
    (PYFUNCTYPE, §4.7.1: a pure setter) on the native device; a recording model on the fake one."""
    if getattr(dev, "kind", "") == "fake":
        return _fake_clip_fn(dev, name)
    if not clip:
        raise ValueError(f"{name}: null clip")
    slot = CLIP_SLOTS[name]
    arg = com.VP if name.endswith(".anim") else C.c_float
    proto = _CLIP_PROTOS.get(arg)
    if proto is None:
        proto = _CLIP_PROTOS[arg] = C.PYFUNCTYPE(com.HRESULT, C.c_void_p, arg)
    vtbl = C.c_void_p.from_address(clip).value
    return proto(C.c_void_p.from_address(vtbl + 8 * slot).value)


def _fake_clip_fn(dev, name):
    prop = "clip_" + name.split(".")[1][3:].lower()          # clip_left | clip_top | clip_right | clip_bottom
    anim = name.endswith(".anim")

    def call(p, value):
        dev.calls.append((name, p, (value,)))
        dev._batch_calls += 1
        o = dev.objects.get(p)
        if o is None:
            dev.violations.append(("unknown object", name, p))
            return C.c_long(0x80070057).value
        dev._unbind(p, prop)
        if anim:
            dev.prop_anim[(p, prop)] = value
            dev.bound_by.setdefault(value, set()).add((p, prop))
            o["props"][prop] = ("anim", value)
        else:
            o["props"][prop] = float(value)
        return 0
    return call


def create_clip(dev, name):
    """``CreateRectangleClip`` (WF: creation releases the GIL)."""
    if getattr(dev, "kind", "") == "fake":
        dev.calls.append(("Device.CreateRectangleClip", None, (name,)))
        return dev._new("rect_clip", name, props={})
    return dev.create_rect_clip(name)


# --------------------------------------------------------------------------- the device's core
class ChromeCore:
    """What ``animation.Batch`` needs from a stage (``StageCore`` without its episodes and harvest:
    the carousel owns the picker's episodes, its boost and its FrameStats): the device, the clock, P
    and t1 (G1-6), the animation slot functions and the one Commit per event (§4.6.7)."""

    def __init__(self, device, clock):
        self.device = device
        self.clock = clock
        self.period = clock.freq / 60.0
        self._fns = None
        self.last_commit_ms = None
        self.slow_commits = 0

    def animation_fns(self):
        if self._fns is None:
            self._fns = self.device.animation_fns()
        return self._fns

    def batch(self, t_wake=None):
        fs = self.device.frame_statistics()                       # GIL-keeping read (G1-1, G1-5)
        if fs.rateNum and fs.rateDen:
            self.period = CK.period_ticks(fs.rateNum, fs.rateDen, self.clock.freq)
        now = self.clock.now()
        t1 = CK.t1_for(fs.nextEstimatedFrameTime, now, self.period, CK.T1_MARGIN_S * self.clock.freq)
        return AN.Batch(self, t1, t_wake=t_wake, predicted_commit=CK.next_frame_after(fs.lastFrameTime, now,
                                                                                      self.period))

    def commit(self, batch):
        t = time.perf_counter()
        self.device.commit()                                      # the batch's first GIL-releasing call
        self.last_commit_ms = (time.perf_counter() - t) * 1000.0
        if self.last_commit_ms > AN.COMMIT_LOG_MS:
            self.slow_commits += 1


# --------------------------------------------------------------------------- surfaces
class Surfaces:
    """Prepared sprite surfaces by the source sprite's identity (the engine's sprite caches keep each
    Sprite while it is in use), plus surfaces derived from one (its half-resolution copy, a
    placeholder face) under a tag: an LRU that releases on eviction. The per-k statics (shade,
    shadows, frame, slot rings) by key.

    **Upload, then commit a frame later.** Measured headlessly on this PC: a Commit that follows a
    surface upload at once costs about 3 ms (it waits for the copy), one that comes a frame later
    about 0.1-0.2 ms, and a property-only Commit about 0.02-0.1 ms. So every upload is followed by
    ``ID3D11DeviceContext::Flush`` (the copy starts now) and remembers its time: a surface is
    **ready** once ``ready_s`` has passed, and the chrome shows only ready surfaces (a detent's
    batch never waits on a copy)."""

    def __init__(self, dev, capacity=SURFACES, now=time.monotonic, ready_s=0.004):
        self.dev = dev
        self.capacity = int(capacity)
        self.now = now
        self.ready_s = float(ready_s)
        self.items = OrderedDict()            # (id(sprite), tag) -> (sprite, surface, size, extra, t_upload)
        self.statics = {}                      # key -> (surface, size, extra)
        self.uploads = 0
        self.bytes = 0
        self.upload_ms = 0.0
        self._ctx_flush = _ctx_flush_fn(dev)

    def _upload(self, w, h, data, opaque, name):
        t = time.perf_counter()
        s = self.dev.create_surface(w, h, opaque, name)
        try:
            self.dev.upload(s, w, h, data, name)
            if self._ctx_flush is not None:
                self._ctx_flush()                              # the copy starts now (WF: releases the GIL)
        except BaseException:
            self.dev.release(s)
            raise
        self.uploads += 1
        self.bytes += len(data)
        self.upload_ms += (time.perf_counter() - t) * 1000.0
        return s

    def get(self, sprite, tag=None):
        """(surface, size, extra) when uploaded, else None."""
        hit = self.items.get((id(sprite), tag)) if sprite is not None else None
        if hit is not None and hit[0] is sprite:
            self.items.move_to_end((id(sprite), tag))
            return hit[1], hit[2], hit[3]
        return None

    def ready(self, sprite, tag=None):
        """True once the sprite's surface was uploaded at least ``ready_s`` ago."""
        hit = self.items.get((id(sprite), tag)) if sprite is not None else None
        return hit is not None and hit[0] is sprite and self.now() - hit[4] >= self.ready_s - 1e-9

    def derived(self, sprite, tag, build, opaque=False, name="sprite"):
        """(surface, size, extra) of ``build()`` -> (w, h, bytes, extra), keyed by ``sprite`` and ``tag``."""
        hit = self.get(sprite, tag)
        if hit is not None:
            return hit
        key = (id(sprite), tag)
        old = self.items.pop(key, None)
        w, h, data, extra = build()
        s = self._upload(w, h, data, opaque, name)
        if old is not None:
            self.dev.release(old[1])
        self.items[key] = (sprite, s, (w, h), extra, self.now())
        self._evict()
        return s, (w, h), extra

    def sprite(self, sprite, name="sprite"):
        """(surface, (w, h)) of a carousel_render Sprite, uploaded on first use."""
        if sprite is None:
            return None, (0, 0)

        def build():
            from .. import carousel_render as R
            return R.sprite_bgra(sprite) + (None,)
        s, size, _extra = self.derived(sprite, None, build, False, name)
        return s, size

    def half(self, sprite, name="sprite.l1"):
        """(surface, (sx, sy)) of the sprite's half-resolution copy (the side cards' level, S5-28's rule)."""
        def build():
            from .. import carousel_render as R
            small, scale = R.half_sprite(sprite)
            return R.sprite_bgra(small) + (scale,)
        s, _size, scale = self.derived(sprite, "half", build, False, name)
        return s, scale

    def has(self, sprite, tag=None):
        return self.get(sprite, tag) is not None

    def age_all(self):
        """Every surface counts as ready (tests; nothing waits on its copy any more)."""
        for key, entry in list(self.items.items()):
            self.items[key] = entry[:4] + (entry[4] - self.ready_s,)

    def static(self, key, build, opaque=False, name="static"):
        """(surface, size, extra) built once per key: ``build()`` -> (w, h, bytes, extra)."""
        hit = self.statics.get(key)
        if hit is None:
            w, h, data, extra = build()
            hit = self.statics[key] = (self._upload(w, h, data, opaque, name), (w, h), extra)
        return hit

    def _evict(self):
        while len(self.items) > self.capacity:
            _key, entry = self.items.popitem(last=False)
            self.dev.release(entry[1])

    def forget(self, sprites):
        """Release every surface made from these sprites (personal text: the labels, at a session's end)."""
        ids = {id(sp) for sp in sprites if sp is not None}
        for key in [k for k, v in self.items.items() if k[0] in ids and v[0] is not None]:
            entry = self.items.pop(key)
            self.dev.release(entry[1])

    def release(self):
        for entry in self.items.values():
            self.dev.release(entry[1])
        self.items.clear()
        for s, _size, _extra in self.statics.values():
            self.dev.release(s)
        self.statics.clear()


# --------------------------------------------------------------------------- one card's visuals
class CardSlot:
    """A pooled card: its visuals, properties and what is programmed on them."""

    __slots__ = ("n", "wrap", "clip", "pos", "sc", "rise", "es", "side", "focus", "face", "badge", "chip", "shade",
                 "frame", "p_x", "p_op", "p_s", "p_rise", "p_e", "p_side", "p_focus", "p_shade", "p_frame",
                 "p_clip_l", "p_clip_r", "index", "contents", "clip_sig", "placed", "owner")

    def __init__(self, n):
        self.n = n
        self.index = None
        self.contents = {}                    # visual name -> (surface, placement key)
        self.clip_sig = None                  # (side, nearer index, its tweens) the clip was programmed for
        self.placed = None
        self.owner = None                     # the card whose sprites ``contents`` shows (None: none yet)


class _Warm:
    """A knob touch's device half being made on the worker (``warm_async``). The worker only fills
    this object; everything else stays on ``NanoD-carousel``."""

    __slots__ = ("hmon", "t0", "done", "result", "error", "cancelled", "lock")

    def __init__(self, hmon):
        self.hmon = hmon
        self.t0 = time.perf_counter()
        self.done = threading.Event()
        self.result = None
        self.error = None
        self.cancelled = False
        self.lock = threading.Lock()

    def finish(self, result, error, discard):
        """The worker's end: keep the half, or release it when the chrome no longer wants it."""
        with self.lock:
            drop = self.cancelled
            self.result = None if drop else result
            self.error = error
            self.done.set()
        if drop and result is not None:
            _quiet(discard, result)

    def cancel(self, discard):
        with self.lock:
            self.cancelled = True
            result, self.result = self.result, None
        if result is not None:
            _quiet(discard, result)

    def take(self):
        with self.lock:
            result, self.result = self.result, None
            return result, self.error


class _Mirror:
    """What each property runs: its signature (the machine tween's start, target, t0, duration, curve
    and the linear map), so an unchanged tween costs nothing (G1-4)."""

    __slots__ = ("sig",)

    def __init__(self):
        self.sig = {}


# --------------------------------------------------------------------------- the chrome
class PickerChrome:
    """See the module docstring. Every method runs on ``NanoD-carousel``.

    ``device_factory(hmonitor)`` -> a device (``device.NativeDevice`` or ``fake.FakeDevice``);
    ``clock_factory(device)`` -> ``clock.StageClock`` whose ``from_perf`` converts the carousel clock
    (``time.perf_counter`` in the app) to the device's ticks; ``monitor_for(rect)`` -> the HMONITOR of
    the picker's monitor (the device is created on the adapter that owns it, §4.2).

    A knob touch's device is made in two halves (``warm_async``): ``prepare_factory(hmonitor)`` -> a
    half made on any thread, ``adopt_factory(half)`` -> the device (on this thread),
    ``discard_prepared(half)`` releases a half never adopted; ``spawn(fn)`` runs ``fn`` on a worker
    thread. The native device has all three (``picker_device``); without them a touch makes the
    device at once (``warm``)."""

    def __init__(self, *, device_factory=None, clock_factory=None, monitor_for=None, log=None,
                 monotonic=time.monotonic, policy=None, opacity_path=OPACITY_VISUAL3, headless=False,
                 prepare_factory=None, adopt_factory=None, discard_prepared=None, spawn=None):
        native = device_factory is None
        self.device_factory = device_factory or _native_device
        self.prepare_factory = prepare_factory or (_native_prepare if native else None)
        self.adopt_factory = adopt_factory or (_native_adopt if native else None)
        self.discard_prepared = discard_prepared or (_native_discard if native else None)
        self.spawn = spawn or _spawn_thread
        self.clock_factory = clock_factory or _native_clock
        self.monitor_for = monitor_for or _monitor_for_rect
        self.log = log
        self.monotonic = monotonic
        self.policy = policy or DevicePolicy()
        self.opacity_path = opacity_path
        self.dev = self.clock = self.core = None
        self.hmonitor = None
        self.target = None
        self.hwnd = None
        self.tree = None
        self.surfaces = None
        self.slots = []
        self.by_index = {}
        self.k = None
        self.layout = None
        self.background = None
        self.active = False
        self.mirror = _Mirror()
        self.label_sprites = []                # uploaded this session (released at end: personal text)
        self.headless = bool(headless)         # benches and the self-test: no target, nothing composed
        self.prewarmer = None                  # curves.Prewarmer: the segment tables, in idle steps
        self.want_sync = False                 # a sprite this sync needed was not ready: sync again later
        self.record_events = False             # the supervised checks: every Commit's (t1, done) ticks
        self.events = deque(maxlen=4096)
        self.count = None                      # the open's windows (grow_pool's ceiling)
        self._warming = None                   # _Warm: a knob touch's device half on the worker
        self.counters = {"device_creates": 0, "device_create_ms": None, "device_releases": 0, "device_lost": 0,
                         "last_release": None, "warm_starts": 0, "warm_adopted": 0, "warm_ms": None,
                         "sessions": 0, "syncs": 0, "sync_ms_max": 0.0, "last_sync_ms": None, "last_calls": 0,
                         "last_anims": 0, "commit_ms_max": 0.0, "clip_approx": 0, "failures": 0, "last_error": None,
                         "slots": 0, "slots_grown_ahead": 0, "slots_grown_in_sync": 0, "late_uploads": 0}
        self._statics_k = None

    # ------------------------------------------------------------------ lifecycle (§4.2, §4.3)
    @property
    def warm_device(self) -> bool:
        return self.dev is not None

    @property
    def warming(self) -> bool:
        """A knob touch's device half is being made (or waits to be adopted)."""
        return self._warming is not None

    def _hmon(self, rect):
        if rect is None:
            return None
        try:
            return self.monitor_for(rect)
        except Exception:
            return None

    def _check_monitor(self, hmon):
        """Never a cross-adapter device (§4.2): a device made for another monitor is released."""
        if self.dev is not None and hmon is not None and self.hmonitor is not None and hmon != self.hmonitor:
            self._release_device("monitor")

    def warm(self, rect=None) -> bool:
        """Create the device if it is cold (the open's setup, after its handshake): a half a knob touch
        started is waited for (at most ``WARM_JOIN_S``) and adopted. False when it can't."""
        hmon = self._hmon(rect)
        self._check_monitor(hmon)
        if self.dev is not None:
            return True
        w = self._warming
        if w is not None:
            if hmon is not None and w.hmon is not None and w.hmon != hmon:
                self._drop_warming()                      # made for another monitor
            else:
                if w.done.wait(WARM_JOIN_S):
                    return self._adopt_ready()
                self._drop_warming()
                self._note_error("device: the knob touch's warm-up did not finish in time")
                return False
        now = self.monotonic()
        if not self.policy.want_warm(now):
            return False
        t = time.perf_counter()
        dev = None
        try:
            dev = self.device_factory(hmon)
            clock = self.clock_factory(dev)
        except Exception as exc:
            if dev is not None:
                _quiet(dev.teardown)
            self.policy.create_failed(now)
            self._note_error(f"device: {exc!r}")
            return False
        self._install_device(dev, clock, hmon, now, (time.perf_counter() - t) * 1000.0)
        return True

    def warm_async(self, rect=None, notify=None):
        """A knob touch (K4 §4.2, AR-19) on ``NanoD-carousel``: start the device without holding this
        thread, which answers ``show()``'s handshake (WP7c-R6). The slow half runs on a worker
        (``spawn``); ``notify()`` (called on the worker) wakes this thread, whose next ``warm_async``,
        ``idle`` or ``warm`` adopts it. Returns 'warm', 'started', 'pending' or False."""
        self._adopt_ready()
        hmon = self._hmon(rect)
        self._check_monitor(hmon)
        if self.dev is not None:
            return "warm"
        w = self._warming
        if w is not None:
            if hmon is None or w.hmon is None or w.hmon == hmon:
                return "pending"
            self._drop_warming()
        if self.prepare_factory is None or self.adopt_factory is None:
            return "warm" if self.warm(rect) else False       # a device without halves: at once
        if not self.policy.want_warm(self.monotonic()):
            return False
        w = self._warming = _Warm(hmon)
        prepare, discard = self.prepare_factory, self.discard_prepared

        def run():
            result = error = None
            try:
                result = prepare(hmon)
            except BaseException as exc:                  # handed to NanoD-carousel, never raised here
                error = exc
            w.finish(result, error, discard)
            if notify is not None:
                _quiet(notify)
        try:
            self.spawn(run)
        except Exception as exc:
            self._warming = None
            self._note_error(f"warm-up worker: {exc!r}")
            return False
        self.counters["warm_starts"] += 1
        return "started"

    def _adopt_ready(self) -> bool:
        """Adopt a finished half (on this thread): True when the device is warm now."""
        w = self._warming
        if w is None or not w.done.is_set():
            return False
        self._warming = None
        result, error = w.take()
        now = self.monotonic()
        if self.dev is not None:
            _quiet(self.discard_prepared, result)
            return True
        if result is None:
            self.policy.create_failed(now)
            self._note_error(f"device: {error!r}")
            return False
        t = time.perf_counter()
        dev = None
        try:
            dev = self.adopt_factory(result)
            clock = self.clock_factory(dev)
        except Exception as exc:
            if dev is not None:
                _quiet(dev.teardown)
            _quiet(self.discard_prepared, result)          # a no-op once the adopt took it
            self.policy.create_failed(now)
            self._note_error(f"device: {exc!r}")
            return False
        self._install_device(dev, clock, w.hmon, now, (time.perf_counter() - t) * 1000.0)
        self.counters["warm_adopted"] += 1
        self.counters["warm_ms"] = round((time.perf_counter() - w.t0) * 1000.0, 2)
        return True

    def _drop_warming(self):
        w, self._warming = self._warming, None
        if w is not None:
            w.cancel(self.discard_prepared)

    def _install_device(self, dev, clock, hmon, now, ms):
        self.dev, self.clock = dev, clock
        self.hmonitor = hmon
        self.core = ChromeCore(dev, clock)
        self.surfaces = Surfaces(dev, now=self.monotonic, ready_s=READY_S)
        self.policy.created(now)
        self.counters["device_creates"] += 1
        self.counters["device_create_ms"] = round(ms, 2)       # this thread's share of the creation

    def begin(self, hwnd, layout, background, count=None) -> bool:
        """A picker opens on the GPU chrome: device, target on ``hwnd`` (the carousel's click-through
        chrome window, rcMonitor), the tree (pooled per device) and the per-k statics. The root
        starts at opacity 0 (the machine's root fades it in at the first sync). ``count``: the open's
        windows (the ceiling of ``grow_pool``). False: use the CPU chrome for this open."""
        if self.active:
            self.end()
        self.count = int(count) if count else None
        if not self.warm(layout.monitor_rect):
            return False
        try:
            if not self.dev.check_device_state():
                raise com.DeviceLost("CheckDeviceState", com.DXGI_ERROR_DEVICE_REMOVED)
            if not self.headless and (self.target is None or hwnd != self.hwnd):
                if self.target is not None:
                    self.dev.release(self.target)
                self.target = self.dev.create_target(hwnd)
                self.hwnd = hwnd
                if self.tree is not None:
                    self.dev.set_root(self.target, self.root.ptr)
            if self.tree is None:
                self._build_tree()
                if self.target is not None:
                    self.dev.set_root(self.target, self.root.ptr)
            self.layout = layout
            self.background = background
            self.k = float(layout.k)
            self._statics()
            self._place_static(layout)
            for slot in self.slots:
                self._free_slot(slot, batch=None)
            self.mirror = _Mirror()
            self.p_root.set_now(0.0)
            self.dev.commit()
        except Exception as exc:
            self._failed(exc)
            return False
        self.active = True
        self.policy.scene_opened(self.monotonic())
        self.counters["sessions"] += 1
        return True

    def end(self):
        """The picker closed: the root at 0 and, in the same batch, the label visuals and every
        placeholder face unbound (a visual holds its own reference to its content: personal text
        must not stay bound, WP7c-R5); after the Commit the session's label surfaces are released.
        The tree is kept for the next open (§4.2: surfaces of the LRU stay while the device is warm)."""
        if not self.active:
            return
        self.active = False
        self.policy.scene_closed(self.monotonic())
        try:
            self.p_root.set_now(0.0)
            t = self.tree
            t.content(self.label_text, None)
            t.content(self.label_shadow, None)
            self.label_content = None
            for slot in self.slots:
                if slot.contents.get("face", (None,))[0]:
                    t.content(slot.face, None)
                slot.contents["face"] = (None, None)
                slot.index = slot.owner = None
            self.by_index.clear()
            self.dev.commit()
            if self.surfaces is not None:
                self.surfaces.forget(self.label_sprites)
            self.label_sprites = []
        except Exception as exc:
            self._failed(exc)

    def idle(self):
        """The idle path: adopt a knob touch's finished device half; release the device after 600 s
        without a picker (§4.2, S5-25)."""
        self._adopt_ready()
        if self.dev is not None and not self.active and self.policy.release_due(self.monotonic()):
            self._release_device("idle")

    def prewarm_step(self, budget_s=0.002):
        """One idle step of the segment tables' warm-up (``curves.Prewarmer``; the tables are shared
        with the stage thread, which warms the same ones from app start): a detent never fits a
        table. True while work is left."""
        if self.prewarmer is None:
            self.prewarmer = CV.Prewarmer()
        return self.prewarmer.step(budget_s)

    @property
    def prewarming(self):
        return self.prewarmer is None or not self.prewarmer.done

    def next_wake(self):
        """Seconds until ``idle`` has work, or None."""
        due = self.policy.next_wake() if self.dev is not None else None
        return None if due is None else max(0.0, due - self.monotonic())

    def close(self):
        self.active = False
        self._drop_warming()
        self._release_device("close")

    def _release_device(self, why):
        """Release every chrome object and keep ``DevicePolicy`` in step with it (WP7c-R1): a loss
        goes through ``lost`` (recreate at most twice, 1 s apart); every other release (a monitor
        change, a failed call, the idle release, close) closes the policy's scene and marks it cold,
        so the next touch or open makes a device again."""
        dev = self.dev
        self.want_sync = False
        if dev is None:
            return
        try:
            if self.surfaces is not None:
                self.surfaces.release()
            if self.tree is not None:
                self.tree.release_all()
            if self.target is not None:
                dev.release(self.target)
        except Exception:
            pass
        try:
            dev.teardown()
        except Exception:
            pass
        self.dev = self.clock = self.core = self.surfaces = self.tree = self.target = None
        self.hwnd = None
        self.slots = []
        self.by_index = {}
        self._statics_k = None
        self.label_sprites = []
        self.counters["device_releases"] += 1
        self.counters["last_release"] = why
        now = self.monotonic()
        policy = self.policy
        if why == "lost":
            policy.lost(now)
        else:
            if policy.scene_open:
                policy.scene_closed(now)
            policy.released(now)

    def _note_error(self, text):
        self.counters["failures"] += 1
        self.counters["last_error"] = text[:200]
        if self.log is not None:
            try:
                self.log(f"picker chrome: {text[:200]}")
            except Exception:
                pass

    def _failed(self, exc):
        """A failed call (§4.3): device loss releases everything (the policy recreates at the next
        open, at most twice 1 s apart); any other COM error releases too (deterministic), and the
        next open tries the GPU again (``_release_device`` keeps the policy in step)."""
        lost = isinstance(exc, com.DeviceLost) or (self.dev is not None and not _safe_state(self.dev))
        if lost:
            self.counters["device_lost"] += 1
            try:
                reason = self.dev.removed_reason() if self.dev is not None else 0
                self._note_error(f"device lost ({com.hx(reason)}): {exc!r}")
            except Exception:
                self._note_error(f"device lost: {exc!r}")
        else:
            self._note_error(repr(exc))
        self.active = False
        self._release_device("lost" if lost else "error")

    # ------------------------------------------------------------------ the tree (pooled per device)
    def _build_tree(self):
        dev = self.dev
        t = self.tree = Tree(dev, self.opacity_path)
        self.root = t.root("picker.root")
        self.p_root = t.opacity(self.root, 0.0)
        # the tray (under the cards group: BS markup order)
        self.tray = t.container("picker.tray")
        self.p_tray_op = t.opacity(self.tray, 0.0)
        self.tray_pos = t.visual("picker.tray.pos")
        self.p_tray_y = t.offset_y(self.tray_pos, 0.0)
        self.tray_sc = t.visual("picker.tray.sc")
        st = t.scale_transform(self.tray_sc, 0.0, 0.0)
        self.p_tray_sc = t.scale(st, 400.0, 1.0, "picker.tray.scale")
        t.add(self.root, self.tray)
        t.add(self.tray, self.tray_pos)
        t.add(self.tray_pos, self.tray_sc)
        self.tray_slots = {}
        for side in ("left", "right"):
            box = t.visual(f"picker.slot.{side}")
            v = {"box": box}
            for name in ("bg", "empty", "filled", "failure", "glyph", "badge", "caption"):
                v[name] = t.visual(f"picker.slot.{side}.{name}", opacity=name != "caption")
                t.add(box, v[name])
            p = {name: t.opacity(v[name], 0.0) for name in ("bg", "empty", "filled", "failure", "glyph", "badge")}
            v["p"] = p
            v["contents"] = {}
            t.add(self.tray_sc, box)
            self.tray_slots[side] = v
        # the cards group: cards, label, dots
        self.group = t.container("picker.group")
        self.p_group = t.opacity(self.group, 1.0)
        self.p_shift = t.offset_y(self.group, 0.0)
        t.add(self.root, self.group)
        self.cards = t.visual("picker.cards")
        self.p_bump = t.offset_x(self.cards, 0.0)
        t.add(self.group, self.cards)
        self.label = t.container("picker.label")
        self.p_label = t.opacity(self.label, 0.0)
        self.label_shadow = t.visual("picker.label.shadow")
        self.label_text = t.visual("picker.label.text")
        t.add(self.label, self.label_shadow)
        t.add(self.label, self.label_text)
        t.add(self.group, self.label)
        self.label_content = None
        self.dots = t.visual("picker.dots")
        self.dots_row = t.visual("picker.dots.row")
        self.marker = t.visual("picker.dots.marker")
        self.p_marker = t.offset_x(self.marker, 0.0)
        t.add(self.dots, self.dots_row)
        t.add(self.dots, self.marker)
        t.add(self.group, self.dots)
        self.dots_content = None
        # the fly's shadow, above everything (the fly thumbnail is registered last, K4 9.5)
        self.fly = t.container("picker.fly")
        self.p_fly_op = t.opacity(self.fly, 0.0)
        self.p_fly_x = t.offset_x(self.fly, 0.0)
        self.p_fly_y = t.offset_y(self.fly, 0.0)
        self.fly_sc = t.visual("picker.fly.sc")
        st = t.scale_transform(self.fly_sc, 0.0, 0.0)
        self.p_fly_s = t.scale(st, 800.0, 1.0, "picker.fly.scale")
        self.fly_shadow = t.visual("picker.fly.shadow")
        t.add(self.fly, self.fly_sc)
        t.add(self.fly_sc, self.fly_shadow)
        t.add(self.root, self.fly)
        self.fly_sig = None
        self.slots = []
        self.by_index = {}
        for _ in range(POOL):
            self._new_slot()

    def _new_slot(self):
        dev, t = self.dev, self.tree
        n = len(self.slots)
        c = CardSlot(n)
        c.wrap = t.visual(f"picker.card{n}.wrap")
        c.clip = create_clip(dev, f"picker.card{n}.clip")
        t.others.append(c.clip)
        t._call("Visual.SetClip.object", c.wrap.ptr, c.clip)
        fl, fr = clip_fn(dev, "Clip.SetLeft", c.clip), clip_fn(dev, "Clip.SetRight", c.clip)
        al, ar = clip_fn(dev, "Clip.SetLeft.anim", c.clip), clip_fn(dev, "Clip.SetRight.anim", c.clip)
        c.p_clip_l = Prop(dev, f"picker.card{n}.clip.l", "offset", ((fl, c.clip),), ((al, c.clip),), 1.0, -BIG)
        c.p_clip_r = Prop(dev, f"picker.card{n}.clip.r", "offset", ((fr, c.clip),), ((ar, c.clip),), 1.0, BIG)
        t.props.extend((c.p_clip_l, c.p_clip_r))
        for p in (c.p_clip_l, c.p_clip_r):
            t.calls += p.set_now(p.func.v)
        for name in ("Clip.SetTop", "Clip.SetBottom"):
            hr = clip_fn(dev, name, c.clip)(c.clip, -BIG if name.endswith("Top") else BIG)
            if hr is not None and hr < 0:
                com.check(hr, name)
        c.pos = t.container(f"picker.card{n}.pos")
        c.p_x = t.offset_x(c.pos, 0.0)
        c.p_op = t.opacity(c.pos, 0.0)
        c.sc = t.visual(f"picker.card{n}.sc")
        c.p_s = t.scale(t.scale_transform(c.sc, 0.0, 0.0), 800.0, 1.0, f"picker.card{n}.s")
        c.rise = t.visual(f"picker.card{n}.rise")
        c.p_rise = t.offset_y(c.rise, 0.0)
        c.es = t.visual(f"picker.card{n}.es")
        c.p_e = t.scale(t.scale_transform(c.es, 0.0, 0.0), 800.0, 1.0, f"picker.card{n}.e")
        c.side = t.visual(f"picker.card{n}.side", opacity=True)
        c.p_side = t.opacity(c.side, 0.0)
        c.focus = t.visual(f"picker.card{n}.focus", opacity=True)
        c.p_focus = t.opacity(c.focus, 0.0)
        c.face = t.visual(f"picker.card{n}.face")
        c.badge = t.visual(f"picker.card{n}.badge")
        c.chip = t.visual(f"picker.card{n}.chip")
        c.shade = t.visual(f"picker.card{n}.shade", opacity=True)
        c.p_shade = t.opacity(c.shade, 0.0)
        c.frame = t.visual(f"picker.card{n}.frame", opacity=True)
        c.p_frame = t.opacity(c.frame, 0.0)
        t.add(c.wrap, c.pos)
        t.add(c.pos, c.sc)
        t.add(c.sc, c.rise)
        t.add(c.rise, c.es)
        for v in (c.side, c.focus, c.face, c.badge, c.chip, c.shade, c.frame):
            t.add(c.es, v)
        self.slots.append(c)
        self.counters["slots"] = len(self.slots)
        return c

    # ------------------------------------------------------------------ per k and per layout
    def _statics(self):
        """The per-k surfaces: the shade (one opaque #111 surface at the card's size, G1-9), the two
        shadow layers, the frame ring, the fly shadow, the slot background, and their placement in
        each card slot (so a turn only moves and fades)."""
        from .. import carousel_render as R
        k = self.k
        if self._statics_k == k:
            return
        S = self.surfaces
        w0, h0 = R.card_box_px(k)

        def sprite_static(sprite_and_xy):
            sprite, xy = sprite_and_xy
            w, h, data = R.sprite_bgra(sprite)
            return w, h, data, xy
        self.s_shade = S.static(("shade", k), lambda: R.solid_bgra(R.SHADE_RGB, w0, h0) + (None,), True, "shade")
        self.s_side = S.static(("side", k), lambda: sprite_static(R.gpu_shadow_sprite("side", k)), False, "shadow.side")
        self.s_focus = S.static(("focus", k), lambda: sprite_static(R.gpu_shadow_sprite("focus", k)), False,
                                "shadow.focus")
        self.s_frame = S.static(("frame", k), lambda: sprite_static(R.frame_ring_sprite(k)), False, "frame")
        self.s_fly = S.static(("fly", k), lambda: sprite_static(R.gpu_shadow_sprite("fly", k)), False, "shadow.fly")
        sw, sh = max(1, round(R.SLOT_W * k)), max(1, round(R.SLOT_H * k))
        self.s_slot_bg = S.static(("slot_bg", k), lambda: R.solid_bgra((255, 255, 255), sw, sh) + (None,), True,
                                  "slot.bg")
        width = max(1, round(k))
        self.s_borders = {kind: S.static(("border", kind, k), lambda kind=kind: sprite_static(
            (R.slot_border_colour_sprite(kind, (sw, sh), width), (-width, -width))), False, "slot.border")
            for kind in ("empty", "filled", "failure")}
        self._statics_k = k
        for c in self.slots:
            self._place_slot_statics(c)
        for side, v in self.tray_slots.items():
            t = self.tree
            t.content(v["bg"], self.s_slot_bg[0])
            t.offset(v["bg"], 0, 0)
            for kind in ("empty", "filled", "failure"):
                s, _size, (dx, dy) = self.s_borders[kind]
                t.content(v[kind], s)
                t.offset(v[kind], dx, dy)
        t = self.tree
        s, _size, (dx, dy) = self.s_fly
        t.content(self.fly_shadow, s)
        t.offset(self.fly_shadow, dx, dy)

    def _place_slot_statics(self, c):
        from .. import carousel_render as R
        t = self.tree
        w0, h0 = R.card_box_px(self.k)
        x0, y0 = -w0 / 2.0, -h0 / 2.0
        t.content(c.shade, self.s_shade[0])
        t.offset(c.shade, x0, y0, snap=False)
        for v, st in ((c.side, self.s_side), (c.focus, self.s_focus), (c.frame, self.s_frame)):
            s, _size, (dx, dy) = st
            t.content(v, s)
            t.offset(v, x0 + dx, y0 + dy, snap=False)
        t.offset(c.face, x0, y0, snap=False)
        c.placed = self.k

    def _place_static(self, layout):
        """The layout's static offsets: card rows, tray and slots, dots row origin."""
        from .. import carousel_render as R
        t = self.tree
        k = layout.k
        self.hx0 = layout.stage_x - layout.monitor[0]
        self.hy0 = layout.stage_y - layout.monitor[1]
        for c in self.slots:
            t._call("Visual.SetOffsetY", c.pos.ptr, float(self.hy0 + R.CENTER_Y * k))
        t._call("Visual.SetOffsetX", self.tray_pos.ptr, float(self.hx0 + R.TRAY_CX * k))
        for side, v in self.tray_slots.items():
            t.offset(v["box"], (R.SLOT_X[side] - R.TRAY_CX) * k, (R.TRAY_TOP - R.TRAY_CY) * k, snap=False)
            v["contents"] = {}
        t._call("Visual.SetOffsetY", self.marker.ptr, float(round(self.hy0 + round(R.DOTS_TOP * k))))
        self.label_content = self.dots_content = None
        t.content(self.label_text, None)
        t.content(self.label_shadow, None)
        t.content(self.dots_row, None)
        t.content(self.marker, None)
        self.fly_sig = None
        self.p_fly_op.set_now(0.0)

    # ------------------------------------------------------------------ slots of cards
    def _free_slot(self, c, batch):
        """Hide a pooled card (opacity 0 with the float setter) and forget what it ran."""
        if c.index is not None:
            self.by_index.pop(c.index, None)
        c.index = c.owner = None
        for p in (c.p_x, c.p_op, c.p_s, c.p_rise, c.p_e, c.p_side, c.p_focus, c.p_shade, c.p_frame):
            self.mirror.sig.pop(id(p), None)
        c.clip_sig = None
        if batch is None:
            c.p_op.set_now(0.0)
        else:
            batch.jump(c.p_op, 0.0)

    def _add_slot(self):
        """A new pooled card, placed for the current k and layout (not in the tree until used)."""
        from .. import carousel_render as R
        c = self._new_slot()
        self._place_slot_statics(c)
        self.tree._call("Visual.SetOffsetY", c.pos.ptr, float(self.hy0 + R.CENTER_Y * self.k))
        return c

    def grow_pool(self, count=None) -> bool:
        """A quiet frame's pool step (K4 §4.7.1 and §9.10: visuals, clips and animation objects come
        from pools, never from a detent's batch; WP7c-R4): one card slot when fewer than
        ``SLOT_SPARE`` are free and the open's ``count`` windows could use more. Its property calls
        ride the next Commit. True when a slot was made (the frame's heavy step)."""
        if not self.active or self.tree is None or self.dev is None:
            return False
        count = self.count if count is None else count
        total = len(self.slots)
        if count is not None and total >= count:
            return False
        if total - len(self.by_index) >= SLOT_SPARE:
            return False
        try:
            self._add_slot()
        except Exception as exc:
            self._failed(exc)
            return False
        self.counters["slots_grown_ahead"] += 1
        return True

    def _slot_for(self, index, batch):
        c = self.by_index.get(index)
        if c is not None:
            return c, False
        for c in self.slots:
            if c.index is None:
                break
        else:
            c = self._add_slot()                        # a burst beyond SLOT_SPARE: never expected (bench: 0)
            self.counters["slots_grown_in_sync"] += 1
        c.index = index
        self.by_index[index] = c
        for p in (c.p_x, c.p_op, c.p_s, c.p_rise, c.p_e, c.p_side, c.p_focus, c.p_shade, c.p_frame):
            self.mirror.sig.pop(id(p), None)
        c.clip_sig = None
        return c, True

    # ------------------------------------------------------------------ mirroring
    def _mirror(self, b, prop, tween, a=0.0, s=1.0, *, t1p, force=False):
        """Program ``prop`` = a + s * tween (the machine's tween, with its own t0). Returns calls."""
        sig = (tween.t0, tween.start, tween.target, tween.duration, id(tween.ease), a, s)
        key = id(prop)
        if not force and self.mirror.sig.get(key) == sig:
            b.skipped += 1
            return 0
        self.mirror.sig[key] = sig
        target = a + s * tween.target
        if tween.t0 is None or tween.duration <= 0.0 or t1p >= tween.t0 + tween.duration - EPS:
            return b.jump(prop, target)
        return b.to(prop, target, tween.duration * 1000.0, curve_name(tween.ease), anchor=self.clock.from_perf(tween.t0),
                    v_from=a + s * tween.start, force=True)

    def _constant(self, b, prop, value, key_extra=None):
        sig = ("const", float(value), key_extra)
        key = id(prop)
        if self.mirror.sig.get(key) == sig:
            b.skipped += 1
            return 0
        self.mirror.sig[key] = sig
        return b.jump(prop, value)

    def _content(self, b, holder, name, visual, surface, place=None):
        """SetContent (and a static placement) only when it changed: in the batch that reveals it
        (§4.4 last row)."""
        want = (surface, place)
        if holder.get(name) == want:
            return 0
        holder[name] = want
        n = b.call(self.dev.fn("Visual.SetContent", visual.ptr), visual.ptr, surface or None)
        if place is not None and surface:
            # One static matrix places every swapped content (never an offset as well: a level change
            # from the half-resolution copy back to the full sprite must not keep the old scale).
            if place[0] == "offset":
                sx = sy = 1.0
                dx, dy = place[1], place[2]
            else:
                _k, sx, sy, dx, dy = place
            m = com.D2D_MATRIX_3X2_F(sx, 0.0, 0.0, sy, dx, dy)
            n += b.call(self.dev.fn("Visual.SetTransform.matrix", visual.ptr), visual.ptr, C.byref(m))
        return n

    # ------------------------------------------------------------------ the one entry point per event
    def sync(self, view, t_wake=None):
        """Program the chrome for the machine's current tweens and the engine's sprites: one batch,
        one Commit (§4.6.5 item 5). Returns a stats dict, or None when the device failed (the
        engine switches this open to the CPU chrome)."""
        if not self.active or self.dev is None:
            return None
        t0 = time.perf_counter()
        self.want_sync = False
        try:
            b = self.core.batch(t_wake if t_wake is not None else t0)
            t1p = self.clock.to_perf(b.t1)
            m = view.machine
            k = self.k
            self._mirror(b, self.p_root, m.root, t1p=t1p)
            self._mirror(b, self.p_group, m.group, t1p=t1p)
            self._mirror(b, self.p_shift, m.shift, 0.0, k, t1p=t1p)
            self._bump(b, view, t1p)
            self._tray(b, view, t1p)
            self._cards(b, view, t1p)
            self._label(b, view, t1p)
            self._dots(b, view, t1p)
            self._fly(b, view, t1p)
            if b.calls:
                b.commit()                          # nothing changed: no Commit at all
                if self.record_events:
                    self.events.append({"t1": b.t1, "done": self.clock.now(), "calls": b.calls})
        except Exception as exc:
            self._failed(exc)
            return None
        ms = (time.perf_counter() - t0) * 1000.0
        c = self.counters
        c["syncs"] += 1
        c["last_sync_ms"] = round(ms, 3)
        c["sync_ms_max"] = max(c["sync_ms_max"], round(ms, 3))
        c["last_calls"], c["last_anims"] = b.calls, b.anims
        if self.core.last_commit_ms is not None:
            c["commit_ms_max"] = max(c["commit_ms_max"], round(self.core.last_commit_ms, 3))
        return {"ms": ms, "calls": b.calls, "anims": b.anims, "jumps": b.jumps, "skipped": b.skipped,
                "commit_ms": self.core.last_commit_ms}

    # ------------------------------------------------------------------ pieces
    def _bump(self, b, view, t1p):
        """The end bump: two legs in one animation (§4.6.4, S5-31), or the machine's single tween."""
        m, k = view.machine, self.k
        tw, back = m.bump_x, view.bump_back
        key = id(self.p_bump)
        if back is not None and tw.t0 is not None and tw.target != 0.0:
            sig = ("legs", tw.t0, tw.start, tw.target, tw.duration, back)
            if self.mirror.sig.get(key) == sig:
                b.skipped += 1
                return
            self.mirror.sig[key] = sig
            leg = view.bump_leg_s * 1000.0
            spec = [(0.0, tw.target * k, tw.duration * 1000.0, curve_name(tw.ease)),
                    ((back - tw.t0) * 1000.0, 0.0, leg, curve_name(tw.ease))]
            b.legs(self.p_bump, spec, anchor=self.clock.from_perf(tw.t0), v_from=tw.start * k)
            return
        old = self.mirror.sig.get(key)
        if old and old[0] == "legs" and tw.t0 is not None and abs(tw.t0 - old[5]) <= 1e-9 and tw.target == 0.0:
            b.skipped += 1                       # the machine reached leg 2: the programmed legs already run it
            return
        self._mirror(b, self.p_bump, tw, 0.0, k, t1p=t1p)

    def _tray(self, b, view, t1p):
        from .. import carousel_render as R
        m, k, t = view.machine, self.k, self.tree
        self._mirror(b, self.p_tray_op, m.tray_op, t1p=t1p)
        if not view.tray_on and m.tray_op.target <= 0.0 and m.tray_op.start <= 0.0:
            return                                   # hidden until the first snap (trayOn, BS:1155)
        self._mirror(b, self.p_tray_y, m.tray_y, self.hy0 + R.TRAY_CY * k, k, t1p=t1p)
        self._mirror(b, self.p_tray_sc, m.tray_sc, t1p=t1p)
        sw, sh = self.s_slot_bg[1]
        width = max(1, round(k))
        for side, info in view.slots.items():
            v = self.tray_slots[side]
            p = v["p"]
            tw = info.tweens
            self._mirror(b, p["bg"], tw.fill, R.SLOT_BG_A, -R.SLOT_BG_A, t1p=t1p)
            for kind in ("empty", "filled", "failure"):
                self._mirror(b, p[kind], tw.borders[kind], 0.0, R.SLOT_BORDERS[kind][1], t1p=t1p)
            self._mirror(b, p["glyph"], tw.glyph, 0.0, R.SLOT_GLYPH_A, t1p=t1p)
            self._mirror(b, p["badge"], tw.badge, t1p=t1p)
            contents = v["contents"]
            if info.glyph is not None:
                s, (gw, gh) = self._sprite_ready(info.glyph, "slot.glyph")
                if s:
                    self._content(b, contents, "glyph", v["glyph"], s, ("offset", (sw - gw) / 2.0, (sh - gh) / 2.0))
            if info.badge is not None:
                s, (bw, bh) = self._sprite_ready(info.badge, "slot.badge")
                inset = R.SLOT_BADGE_INSET * k
                if s:
                    self._content(b, contents, "badge", v["badge"], s, ("offset", inset, sh - inset - bh))
            if info.caption is not None:
                s, _size = self._sprite_ready(info.caption, "slot.caption")
                if s:                               # the previous caption stays until the new one is ready
                    self._content(b, contents, "caption", v["caption"], s,
                                  ("offset", -width, sh + width + R.CAPTION_GAP * k))
            else:
                self._content(b, contents, "caption", v["caption"], None)

    def _cards(self, b, view, t1p):
        """Slots for the visible cards, far -> near order, contents, the mirrored tweens and clips."""
        from .. import carousel_render as R
        k = self.k
        ax = self.hx0 + R.CENTER_X * k
        by_index = {}
        for info in view.cards:
            op = info.tweens.op
            f = R.CLOSED_OPACITY if info.closed else 1.0
            visible = op.start * f > 0.001 or op.target * f > 0.001
            if visible or info.index in self.by_index:
                by_index[info.index] = info
        # release slots whose card is gone or finished fading out
        for index in list(self.by_index):
            info = by_index.get(index)
            op = info.tweens.op if info is not None else None
            if info is None or (op.target <= 0.001 and (op.t0 is None or t1p >= op.t0 + op.duration)):
                self._free_slot(self.by_index[index], b)
                by_index.pop(index, None)
        order = [i for i in view.order if i in by_index]
        fresh = set()
        for index in order:
            _c, new = self._slot_for(index, b)
            if new:
                fresh.add(index)
        wanted = [self.by_index[i].wrap for i in order]
        present = [v for v in self.cards.children if v not in wanted]
        for v in present:
            self.tree.remove(self.cards, v)
        for v in wanted:
            if v.parent is not self.cards:
                self.tree.add(self.cards, v)
        b.calls += self.tree.reorder(self.cards, wanted)
        tw_of = {i: by_index[i].tweens for i in order}
        for index in order:
            info = by_index[index]
            c = self.by_index[index]
            tw = info.tweens
            f = R.CLOSED_OPACITY if info.closed else 1.0
            self._mirror(b, c.p_op, tw.op, 0.0, f, t1p=t1p)
            self._mirror(b, c.p_x, tw.x, ax, k, t1p=t1p)
            self._mirror(b, c.p_s, tw.s, t1p=t1p)
            self._mirror(b, c.p_rise, tw.rise, 0.0, k, t1p=t1p)
            self._mirror(b, c.p_e, tw.escale, t1p=t1p)
            self._mirror(b, c.p_side, tw.selw, 1.0, -1.0, t1p=t1p)
            self._mirror(b, c.p_focus, tw.selw, t1p=t1p)
            self._mirror(b, c.p_frame, tw.selw, 0.0, R.OUTLINE_ALPHA, t1p=t1p)
            self._mirror(b, c.p_shade, tw.shade, t1p=t1p)
            self._card_contents(b, c, info)
            self._clip(b, c, info, view, tw_of, ax, t1p)

    def _card_contents(self, b, c, info):
        from .. import carousel_render as R
        k = self.k
        w0, h0 = R.card_box_px(k)
        x0, y0 = -w0 / 2.0, -h0 / 2.0
        s = info.tweens.s
        small = max(s.start, s.target) < LEVEL_SPLIT
        contents = c.contents
        # A sprite that is not ready yet: a slot that already shows this card keeps what it shows
        # (the previous badge, chip or face, as the tray keeps its caption) and the next frame syncs
        # the new one in (``want_sync``); a slot just given to this card shows nothing of another's.
        keep = c.owner == info.index
        c.owner = info.index
        # the placeholder face (closed, failed, caption-stub cards: no thumbnail below)
        if info.face is not None:
            tag = ("face", k)
            face = self._ready(info.face, tag, lambda: self.surfaces.derived(
                info.face, tag, lambda: R.placeholder_face_bgra(info.face, k) + (None,), True, "face"))
            if face or not keep:
                self._content(b, contents, "face", c.face, face[0] if face else None)
        else:
            self._content(b, contents, "face", c.face, None)
        # the badge at left 12 / bottom 12 (K4 9.3), half resolution on side cards
        if info.badge is not None:
            sprite, pad = info.badge
            bx, by = x0 + R.BADGE_INSET * k - pad, y0 + h0 - R.BADGE_INSET * k - R.BADGE_SIZE * k - pad
            surface, place = self._leveled(sprite, small, bx, by, "badge")
            if surface or not keep:
                self._content(b, contents, "badge", c.badge, surface, place)
        else:
            self._content(b, contents, "badge", c.badge, None)
        if info.chip is not None:
            cx, cy = x0 + R.CHIP_INSET * k, y0 + R.CHIP_INSET * k
            surface, place = self._leveled(info.chip, small, cx, cy, "chip")
            if surface or not keep:
                self._content(b, contents, "chip", c.chip, surface, place)
        else:
            self._content(b, contents, "chip", c.chip, None)

    def _ready(self, sprite, tag, upload):
        """The sprite's (surface, size, extra) when ready; else None: it is uploaded now (``upload()``)
        if missing, and the chrome asks for another sync once it is ready (``want_sync``; a miss is
        counted in ``late_uploads``)."""
        if self.surfaces.ready(sprite, tag):
            return self.surfaces.get(sprite, tag)
        if not self.surfaces.has(sprite, tag):
            upload()
            self.counters["late_uploads"] += 1
        self.want_sync = True
        return None

    def _leveled(self, sprite, small, x, y, name):
        """(surface, placement): the full sprite at (x, y), or its half-resolution copy scaled back;
        (None, None) until it is ready (``_ready``)."""
        if not small:
            hit = self._ready(sprite, None, lambda: self.surfaces.sprite(sprite, name))
            return (hit[0], ("offset", x, y)) if hit else (None, None)
        hit = self._ready(sprite, "half", lambda: self.surfaces.half(sprite, name + ".l1"))
        if not hit:
            return None, None
        sx, sy = hit[2]
        return hit[0], ("matrix", sx, sy, x, y)

    def _sprite_ready(self, sprite, name):
        """(surface, (w, h)) of a plain sprite when ready, else (None, (0, 0)) (``_ready``)."""
        hit = self._ready(sprite, None, lambda: self.surfaces.sprite(sprite, name))
        return (hit[0], hit[1]) if hit else (None, (0, 0))

    def _clip(self, b, c, info, view, tw_of, ax, t1p):
        """The half-plane beyond the nearer card's far edge (see the module docstring)."""
        from .. import carousel_render as R
        d = info.d
        sgn = 1 if d > 0 else -1 if d < 0 else 0
        near = info.index - sgn if sgn else None
        ntw = tw_of.get(near) if near is not None else None
        closed_near = near is not None and near in view.closed
        if not sgn or ntw is None or closed_near:
            sig = ("none",)
            if c.clip_sig != sig:
                c.clip_sig = sig
                self._constant(b, c.p_clip_l, -BIG)
                self._constant(b, c.p_clip_r, BIG)
            return
        half = R.CARD_W * self.k / 2.0 * sgn
        x, s, e = ntw.x, ntw.s, ntw.escale
        sig = (sgn, near, _tsig(x), _tsig(s), _tsig(e))
        if c.clip_sig == sig:
            b.skipped += 1
            return
        c.clip_sig = sig
        edge, other = (c.p_clip_l, c.p_clip_r) if sgn > 0 else (c.p_clip_r, c.p_clip_l)
        self._constant(b, other, BIG * sgn)

        def value(xv, sv, ev):
            return ax + xv * self.k + half * sv * ev

        running = [tw for tw in (x, s, e) if tw.t0 is not None and tw.duration > 0.0 and t1p < tw.t0 + tw.duration - EPS]
        target = value(x.target, s.target, e.target)
        key = id(edge)
        self.mirror.sig.pop(key, None)
        if not running:
            self.mirror.sig[key] = ("const", target)
            b.jump(edge, target)
            return
        lead = running[0]
        same = all(tw.t0 == lead.t0 and tw.duration == lead.duration and tw.ease is lead.ease for tw in running)
        product = e in running and s in running
        if same and not product:
            if len(running) == 1:
                start = value(x.start if x is lead else x.target, s.start if s is lead else s.target,
                              e.start if e is lead else e.target)
            else:
                start = value(x.start, s.start, e.target)
            b.to(edge, target, lead.duration * 1000.0, curve_name(lead.ease), anchor=self.clock.from_perf(lead.t0),
                 v_from=start, force=True)
            return
        # mixed motions: one curve anchored at the latest retarget, from the edge's exact value there to
        # its exact target, ending with the last motion (WP7c-D3)
        self.counters["clip_approx"] += 1
        latest = max(running, key=lambda tw: tw.t0)
        t_a = latest.t0
        end = max(tw.t0 + tw.duration for tw in running)
        v_a = value(x.value(t_a), s.value(t_a), e.value(t_a))
        b.to(edge, target, max(0.001, end - t_a) * 1000.0, curve_name(latest.ease), anchor=self.clock.from_perf(t_a),
             v_from=v_a, force=True)

    def _label(self, b, view, t1p):
        m = view.machine
        self._mirror(b, self.p_label, m.label_alpha, t1p=t1p)
        label = view.label
        key = view.label_key
        if key == self.label_content:
            return
        self.label_content = key
        holder = {}
        if label is None or label.sprite is None:
            self._content(b, holder, "text", self.label_text, None)
            self._content(b, holder, "shadow", self.label_shadow, None)
            return
        x, y = self.hx0 + label.x, self.hy0 + label.y
        s, _size = self._sprite_ready(label.sprite, "label")
        s2 = None
        if label.shadow is not None:
            s2, _size = self._sprite_ready(label.shadow, "label.shadow")
        self.label_sprites.extend(sp for sp in (label.sprite, label.shadow) if sp is not None)
        if s is None or (label.shadow is not None and s2 is None):
            self.label_content = None                    # not ready: the previous label stays (S5-24)
            return
        self._content(b, holder, "text", self.label_text, s, ("offset", round(x), round(y)))
        if s2 is not None:
            self._content(b, holder, "shadow", self.label_shadow, s2, ("offset", round(x), round(y)))
        else:
            self._content(b, holder, "shadow", self.label_shadow, None)

    def _dots(self, b, view, t1p):
        from .. import carousel_render as R
        k = self.k
        if view.dots_key != self.dots_content:
            self.dots_content = view.dots_key
            holder = {}
            if view.dots is None:
                self._content(b, holder, "row", self.dots_row, None)
                self._content(b, holder, "marker", self.marker, None)
            else:
                sprite, x, y = view.dots
                s, _size = self._sprite_ready(sprite, "dots")
                ms, _size = self._sprite_ready(view.marker, "marker")
                if s is None or ms is None:
                    self.dots_content = None             # the row shows once its surface is ready
                else:
                    self._content(b, holder, "row", self.dots_row, s,
                                  ("offset", round(self.hx0 + x), round(self.hy0 + y)))
                    b.call(self.dev.fn("Visual.SetContent", self.marker.ptr), self.marker.ptr, ms)
            self.mirror.sig.pop(id(self.p_marker), None)
        if view.dots is not None:
            a = self.hx0 + (R.CENTER_X - R.dots_width(view.dots_shown) / 2.0) * k
            self._mirror(b, self.p_marker, view.machine.marker, a, R.DOT_PITCH * k, t1p=t1p)

    def _fly(self, b, view, t1p):
        """The fly's shadow (S5-4 returns with the GPU chrome): the fly's rect moves by translate and
        uniform scale on OUT over FLY_S, its opacity 1 -> 0 from FLY_FADE_AT over FLY_FADE_S."""
        fly = view.fly
        if fly is None:
            if self.fly_sig is not None:
                self.fly_sig = None
                self._constant(b, self.p_fly_op, 0.0)
            return
        sig = (fly["t0"], tuple(fly["start"]), tuple(fly["target"]))
        if sig == self.fly_sig:
            b.skipped += 1
            return
        self.fly_sig = sig
        (x0, y0, x1, y1), (tx0, ty0, tx1, ty1) = fly["start"], fly["target"]
        w0 = max(1.0, float(x1 - x0))
        h0 = max(1.0, float(y1 - y0))
        kr = (tx1 - tx0) / w0
        anchor = self.clock.from_perf(fly["t0"])
        dur = view.fly_s * 1000.0
        for key in (id(self.p_fly_x), id(self.p_fly_y), id(self.p_fly_s), id(self.p_fly_op)):
            self.mirror.sig.pop(key, None)
        b.to(self.p_fly_x, tx0, dur, "OUT", anchor=anchor, v_from=x0, force=True)
        b.to(self.p_fly_y, ty0, dur, "OUT", anchor=anchor, v_from=y0, force=True)
        b.to(self.p_fly_s, kr, dur, "OUT", anchor=anchor, v_from=1.0, force=True)
        b.legs(self.p_fly_op, [(0.0, 1.0, 0.0, "OUT"), (view.fly_fade_at * 1000.0, 0.0, view.fly_fade_s * 1000.0, "OUT")],
               anchor=anchor, v_from=1.0)
        # the shadow sprite is built for the card at scale 1; a start rect of another size scales it
        from .. import carousel_render as R
        cw, ch = R.card_box_px(self.k)
        s, _size, (dx, dy) = self.s_fly
        sx, sy = w0 / cw, h0 / ch
        m = com.D2D_MATRIX_3X2_F(sx, 0.0, 0.0, sy, dx * sx, dy * sy)
        b.call(self.dev.fn("Visual.SetOffsetX", self.fly_shadow.ptr), self.fly_shadow.ptr, 0.0)
        b.call(self.dev.fn("Visual.SetOffsetY", self.fly_shadow.ptr), self.fly_shadow.ptr, 0.0)
        b.call(self.dev.fn("Visual.SetTransform.matrix", self.fly_shadow.ptr), self.fly_shadow.ptr, C.byref(m))

    # ------------------------------------------------------------------ uploads ahead of use
    def prepare(self, sprite, name="label", levels=("full",)):
        """Upload a sprite before it is needed (a prefetched label, B1; a badge or chip of a card that
        will show), so a detent's batch never uploads: a Commit carrying uploads costs milliseconds
        where a property-only Commit costs about 0.1 ms. ``levels``: "full" and/or "half". Label
        surfaces are released at the session's end. Returns the uploads made."""
        if not self.active or self.dev is None or sprite is None:
            return 0
        n = 0
        try:
            if "full" in levels and not self.surfaces.has(sprite):
                self.surfaces.sprite(sprite, name)
                n += 1
                if name.startswith("label"):
                    self.label_sprites.append(sprite)
            if "half" in levels and not self.surfaces.has(sprite, "half"):
                self.surfaces.half(sprite, name + ".l1")
                n += 1
        except Exception as exc:
            self._failed(exc)
            return 0
        return n

    def ready(self, sprite, levels=("full",)):
        """True when every requested level of the sprite is uploaded and its copy done (``Surfaces``)."""
        if not self.active or self.surfaces is None or sprite is None:
            return False
        return all(self.surfaces.ready(sprite, None if lv == "full" else "half") for lv in levels)

    def metrics(self):
        out = dict(self.counters)
        out["warm"] = self.dev is not None
        out["warming"] = self._warming is not None
        out["active"] = self.active
        out["policy"] = self.policy.state
        if self.surfaces is not None:
            out["surfaces"] = {"sprites": len(self.surfaces.items), "statics": len(self.surfaces.statics),
                               "uploads": self.surfaces.uploads, "upload_ms": round(self.surfaces.upload_ms, 2)}
        if self.dev is not None:
            out["device"] = {k: v for k, v in (getattr(self.dev, "info", {}) or {}).items()
                             if k in ("d3d11", "timeFrequency_equals_qpf", "kind")}
        return out


def _ctx_flush_fn(dev):
    """``ID3D11DeviceContext::Flush`` (slot 111; WF: it may wait on the driver) of a native device, or
    None (the fake device)."""
    ctx = getattr(dev, "ctx", None)
    if not ctx or getattr(dev, "kind", "") != "native":
        return None
    vtbl = C.c_void_p.from_address(ctx).value
    fn = C.WINFUNCTYPE(None, C.c_void_p)(C.c_void_p.from_address(vtbl + 8 * CONTEXT_FLUSH_SLOT).value)
    return lambda: fn(ctx)


def _tsig(tw):
    return (tw.t0, tw.start, tw.target, tw.duration, id(tw.ease))


def _safe_state(dev):
    try:
        return bool(dev.check_device_state())
    except Exception:
        return False


def _quiet(fn, *args):
    """Call ``fn`` (a release or a wake-up) and swallow its failure."""
    if fn is None:
        return None
    try:
        return fn(*args)
    except Exception:
        return None


def _spawn_thread(fn):
    """The knob touch's warm-up worker: a short-lived daemon thread (one D3D11CreateDevice)."""
    t = threading.Thread(target=fn, name="NanoD-chrome-warm", daemon=True)
    t.start()
    return t


# --------------------------------------------------------------------------- native wiring
def _native_device(hmonitor):
    from .device import NativeDevice
    return NativeDevice(hmonitor)


def _native_prepare(hmonitor):
    from . import picker_device
    return picker_device.prepare(hmonitor)


def _native_adopt(prepared):
    from . import picker_device
    return picker_device.adopt(prepared)


def _native_discard(prepared):
    from . import picker_device
    return picker_device.discard(prepared)


def _native_clock(dev):
    from . import win32 as W
    return CK.StageClock(dev.time_frequency, dev.qpf, qpc=W.qpc)


def _monitor_for_rect(rect):
    """The HMONITOR holding the centre of ``rect`` (x, y, w, h)."""
    from . import win32 as W
    x, y, w, h = (int(v) for v in rect)
    return W.MonitorFromPoint(com.POINT(x + w // 2, y + h // 2), W.MONITOR_DEFAULTTONEAREST)


def factory(log=None):
    """A new ``PickerChrome`` on the native device (what ``carousel.install_gpu_chrome`` takes)."""
    return PickerChrome(log=log)


def install():
    """Register ``factory`` with the carousel (called once from the wiring point, ``standalone.py``):
    every picker created afterwards uses the GPU chrome unless ``NANOD_PICKER_CHROME=cpu``."""
    from .. import carousel
    carousel.install_gpu_chrome(factory)
    return True
