"""Headless rigs for the picker's GPU chrome (DESKTOP_STAGE §4.8, §6.6 H4/H5/H7; CAROUSEL.md §12.4): the
carousel's real ``CarouselEngine`` driven inline on a recording backend (no window, no Win32 call), the
chrome on the stage's fake device (or the native one without a target), one fake clock seen by both
(the carousel's ``perf_counter`` seconds and the device's ticks), and a reference renderer that
draws the chrome's visual tree with its clips (``PickerReference``) for the parity goldens.

Nothing here shows a window, reads the screen or touches another process.
"""
from __future__ import annotations

import time

from .. import carousel as CA
from .. import carousel_render as R
from . import clock as CK
from . import fake as F
from .picker_chrome import PickerChrome

MONITORS = {"32:9": ((0, 0, 5120, 1440), (0, 0, 5120, 1392)), "16:9": ((0, 0, 2560, 1440), (0, 0, 2560, 1392))}


class SharedClock:
    """One fake clock: ``car()`` seconds for the carousel (its ``perf_counter``), ``dev()`` ticks for
    the fake device (a 240 Hz vblank grid), ``advance(seconds)``."""

    def __init__(self, t=100.0, freq=10_000_000, hz=240.0):
        self.t = float(t)
        self.freq = int(freq)
        self.hz = float(hz)
        outer = self

        class Dev:
            freq = outer.freq

            @property
            def hz(self):
                return outer.hz

            @property
            def period(self):
                return outer.freq / outer.hz

            def __call__(self):
                return int(round(outer.t * outer.freq))

            def perf(self):
                return outer.t
        self.dev = Dev()

    def car(self):
        return self.t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += float(seconds)
        return self.t


class RealClock(SharedClock):
    """Real time (``time.perf_counter``) for the benches: ``advance(seconds)`` waits until that much
    real time has passed since the previous frame's start, so frames come at the display's pace
    (240 Hz by default) and commits are spaced as in the app."""

    def __init__(self, freq=10_000_000, hz=240.0):
        super().__init__(time.perf_counter(), freq, hz)
        self._frame = time.perf_counter()

    @property
    def t(self):
        return time.perf_counter()

    @t.setter
    def t(self, value):
        pass

    def advance(self, seconds):
        target = self._frame + float(seconds)
        left = target - time.perf_counter()
        if left > 0.0015:
            time.sleep(left - 0.001)
        while time.perf_counter() < target:
            pass
        self._frame = max(target, time.perf_counter() - 0.001)
        return self.t


class KeepingDevice(F.FakeDevice):
    """The fake device keeping every surface's full bytes (the reference renderer draws them)."""

    def upload(self, surface, w, h, data, name=""):
        super().upload(surface, w, h, data, name)
        self.objects[surface]["pixels"] = bytes(data)
        self.objects[surface].pop("_sprite", None)


class FakeHalf:
    """The fake device's first half (``PickerChrome.warm_async``): what the worker makes."""

    def __init__(self, hmon):
        self.hmon = hmon
        self.released = False


def inline_spawn(fn):
    """Run a warm-up worker at once on the calling thread (deterministic tests)."""
    fn()


class HeldSpawn:
    """Keep warm-up workers until ``run_all()`` (a device half still being made)."""

    def __init__(self):
        self.pending = []

    def __call__(self, fn):
        self.pending.append(fn)

    def run_all(self):
        out, self.pending = self.pending, []
        for fn in out:
            fn()
        return len(out)


def fake_chrome(clock: SharedClock, keep_pixels=False, devices=None, spawn=None, prepare=None, **kw):
    """A PickerChrome on the fake device, on ``clock``, made in two halves at a knob touch
    (``prepare(hmon)`` on the worker, default a ``FakeHalf``; ``spawn`` default ``inline_spawn``)."""
    devices = devices if devices is not None else []
    halves = []

    def device_factory(hmon):
        d = (KeepingDevice if keep_pixels else F.FakeDevice)(clock.dev)
        devices.append(d)
        return d

    def prepare_half(hmon):
        half = prepare(hmon) if prepare is not None else FakeHalf(hmon)
        halves.append(half)
        return half

    def adopt(half):
        if half.released:
            raise RuntimeError("adopting a released half")
        half.released = True                     # the device owns it now
        return device_factory(half.hmon)

    def discard(half):
        half.released = True
    kw.setdefault("monitor_for", lambda rect: 1)
    chrome = PickerChrome(device_factory=device_factory,
                          clock_factory=lambda d: CK.StageClock(d.time_frequency, d.time_frequency, qpc=clock.dev,
                                                                perf=clock.car),
                          monotonic=clock.car, prepare_factory=prepare_half,
                          adopt_factory=adopt, discard_prepared=discard, spawn=spawn or inline_spawn, **kw)
    chrome.devices = devices
    chrome.halves = halves
    return chrome


def native_chrome(clock=None, **kw):
    """A PickerChrome on the native device without a target (benches, the self-test; Windows). With
    ``clock`` (a SharedClock) the carousel's fake seconds map onto real QPC ticks by one offset."""
    from . import win32 as W

    def clock_factory(dev):
        if clock is None:
            return CK.StageClock(dev.time_frequency, dev.qpf, qpc=W.qpc)
        return CK.StageClock(dev.time_frequency, dev.qpf, qpc=W.qpc, perf=clock.car)
    mon = W.primary_monitor()
    return PickerChrome(clock_factory=clock_factory, monitor_for=lambda rect: mon["hmonitor"] if mon else None,
                        headless=True, **kw)


class HeadlessBackend:
    """Every call the engine makes on its backend, answered without Win32 (a subset of the tests'
    recording FakeBackend, fast enough for benches): DWM thumbnails are counted, never made; the
    GPU chrome's window is a fake handle. ``calls`` counts per name."""

    def __init__(self, monitor=(0, 0, 5120, 1440), work=(0, 0, 5120, 1392), dwm=None):
        self.monitor, self.work = tuple(monitor), tuple(work)
        self.host_mode = CA.HOST_LAYERED
        self.hwnd_host = 0x5001
        self.queue = []
        self.on_event = self.on_input = None
        self.chrome = None
        self.layers = {}
        self.toast = None
        self.next_handle = 1000
        self.thumbs = {}
        self.calls = {}
        self.dwm = dwm                        # a DwmThumbs (real thumbnails of hidden windows) or None
        self.updates = 0

    def _n(self, name):
        self.calls[name] = self.calls.get(name, 0) + 1

    @property
    def host_hwnd(self):
        return self.hwnd_host

    def prepare_thread(self):
        return 2

    def create(self, on_event, on_input):
        self.on_event, self.on_input = on_event, on_input
        return self.hwnd_host

    def post(self, code):
        self.queue.append(code)
        return True

    def post_quit(self):
        return True

    def pump(self):
        while self.queue:
            code = self.queue.pop(0)
            if self.on_event is not None:
                self.on_event(CA.POSTED_EVENTS[code])
        return True

    def wait(self, timeout):
        return True

    def pace(self):
        return "tick"

    def monitor_info(self, origin):
        return self.monitor, self.work

    def system_reduced_motion(self):
        return False

    def notification_busy(self):
        return False

    def show_host(self, rect):
        return True

    def activate(self):
        return self.post(CA.WM_APP_ACTIVATED)

    def _noop(self, *args, **kwargs):
        self._n("noop")
        return True

    set_host_passive = refocus_host = host_paint = set_affinity = set_toast_affinity = _noop
    set_capture_exclusions = chrome_show = chrome_present = layer_present = layer_alpha = layer_show = _noop
    dim_upload = dim_show = dim_alpha = glass_alpha = toast_present = toast_show = toast_hide = _noop
    hide_layers = free_large = prepare_capture_thread = destroy_windows = unregister_classes = _noop
    gpu_show = gpu_hide = _noop

    def glass_upload(self, rect, image):
        self._n("glass_upload")

    def chrome_alloc(self, rect):
        self.chrome = R.Canvas.new(rect[2:])
        return self.chrome

    def chrome_canvas(self):
        return self.chrome

    def chrome_free(self):
        self.chrome = None

    def layer_alloc(self, role, rect):
        self.layers[role] = R.Canvas.new(rect[2:])
        return self.layers[role]

    def layer_canvas(self, role):
        return self.layers.get(role)

    def layer_free(self, role):
        self.layers.pop(role, None)

    def toast_alloc(self, rect):
        self.toast = R.Canvas.new(rect[2:])
        return self.toast

    def toast_canvas(self):
        return self.toast

    def toast_free(self):
        self.toast = None

    def use_plain_host(self):
        self.host_mode = CA.HOST_PLAIN

    def use_layered_host(self):
        self.host_mode = CA.HOST_LAYERED
        return True

    def register(self, hwnd):
        self.next_handle += 1
        self.thumbs[self.next_handle] = hwnd
        if self.dwm is not None:
            self.dwm.register(self.next_handle)
        return self.next_handle

    def source_size(self, handle):
        return (1600, 1000)

    def update_thumbnail(self, handle, dest, source, opacity, visible):
        self.updates += 1
        return True

    def update_thumbnails(self, updates):
        self.updates += len(updates)
        if self.dwm is not None:
            return self.dwm.update(updates)
        return True

    def unregister(self, handle):
        self.thumbs.pop(handle, None)
        if self.dwm is not None:
            self.dwm.unregister(handle)

    def flush(self):
        return 0

    def capture(self, rect):
        return None

    def destroy(self):
        pass

    def gui_resources(self):
        return (0, 0)

    has_gpu_window = True

    def gpu_window(self, rect):
        return 0x6001


class NoLabels:
    """A label worker that never renders (benches that isolate the chrome from the label thread)."""

    def submit(self, jobs):
        return True

    def submit_toast(self, job):
        return True

    def take_results(self):
        return []

    def take_toast_results(self):
        return []

    def pending(self):
        return set()

    def close(self, timeout=None):
        return True


class NullCapture:
    """The frost capture that never comes back (the tint-only frost after the timeout): the benches
    measure the chrome, not the frost."""

    def submit(self, job):
        return True

    def take_results(self):
        return []

    def close(self, timeout=None):
        return True


class InlineSnap:
    """A NanoD-snap stand-in: every snap is accepted, then placed ``ok`` when ``finish`` is called."""

    def __init__(self, backend):
        self.backend = backend
        self.jobs = []
        self.results = []

    def submit(self, job):
        self.jobs.append(job)
        return True

    def take_results(self):
        out, self.results = self.results, []
        return out

    def answer(self, job, stage, outcome, info=None):
        if stage == "precheck" and outcome == "accepted":
            job.accepted = True
        elif not job.resolve(outcome, "worker"):
            return False
        self.results.append((job, stage, outcome, dict(info or {})))
        self.backend.post(CA.WM_APP_SNAP)
        return True

    def close(self, timeout=None):
        return True


def snapshot(count=14, index=3):
    items = [{"id": f"w{i}", "hwnd": 100 + i, "pid": 20, "app": f"App{i}", "title": f"Window {i}",
              "available": True, "minimized": False} for i in range(count)]
    return {"items": items, "index": index, "origin": {"hwnd": 100, "pid": 20}}


POOLED_CREATES = frozenset(("Device.CreateVisual", "Device.CreateAnimation", "Device.CreateRectangleClip",
                            "Device.CreateScaleTransform", "Device.CreateTransformGroup", "Device.CreateEffectGroup"))


def create_calls(dev):
    """How many pooled objects (visuals, animations, clips, transforms) the fake device was asked to
    create so far: a detent's sync must add none (K4 §4.7.1, §9.10; surfaces are the uploads' rule)."""
    return sum(1 for call in dev.calls if call[0] in POOLED_CREATES)


class Rig:
    """The production presenter inline on HeadlessBackend with a GPU chrome (fake or native)."""

    def __init__(self, ratio="32:9", chrome="fake", dwm=None, keep_pixels=False, labels="inline", clock=None):
        monitor, work = MONITORS.get(ratio, (ratio, None))
        self.clock = clock or SharedClock()
        self.backend = HeadlessBackend(monitor, work or monitor, dwm=dwm)
        self.devices = []
        if chrome == "fake":
            self.chrome = fake_chrome(self.clock, keep_pixels=keep_pixels, devices=self.devices)
        elif chrome == "native":
            self.chrome = native_chrome(self.clock)
        else:
            self.chrome = False
        self.snap = InlineSnap(self.backend)
        # the label worker on its own thread as in the app (benches), or inline (deterministic tests)
        if labels == "threaded":
            self.labels = CA.LabelWorker(post=self.backend.post, threaded=True)
        elif labels == "none":
            self.labels = NoLabels()
        else:
            self.labels = None
        labels = self.labels
        self.presenter = CA.CarouselPresenter(None, None, lambda: None, backend=self.backend, capture=NullCapture(),
                                              snap=self.snap, labels=labels, clock=self.clock, inline=True,
                                              gpu_chrome=self.chrome, environ={})
        self.engine = self.presenter._engine
        self.frames = []                     # (python work ms, detent) per stepped frame

    def step(self, seconds, dt=1 / 240.0, record=True):
        end = self.clock.t + seconds
        self._one(record)
        while self.clock.t < end - 1e-9:
            self.clock.advance(min(dt, end - self.clock.t))
            self._one(record)

    def _one(self, record):
        t = time.perf_counter()
        alive, wait = self.presenter._iterate()
        if alive and wait is not None and wait <= 0:
            self.engine.present()
            ms = (time.perf_counter() - t) * 1000.0
            detent, sync_s = self.engine.last_detent
            if record and self.engine.session is not None:
                self.frames.append((ms, bool(detent), sync_s))
        return alive, wait

    def open(self, count=14, index=3, settle=0.7):
        self.presenter.show(snapshot(count, index))
        self.backend.activate()
        self.step(CA.CAPTURE_TIMEOUT_S + settle)

    def snap_side(self, index, side, place=True):
        p = self.presenter
        p.snap({"t0": self.clock.t, "index": index, "side": side, "target_rect": None, "place_at_ms": 360,
                "item": {"id": f"w{index}", "hwnd": 100 + index, "pid": 20}})
        self.step(1 / 240.0)
        job = self.snap.jobs[-1]
        self.snap.answer(job, "precheck", "accepted")
        self.step(0.36)
        if place:
            self.snap.answer(job, "final", "ok", {"rect": job.target})

    def close(self):
        self.presenter.close()
        if self.labels is not None:
            self.labels.close(1.0)


# --------------------------------------------------------------------------- the reference renderer
def reference_renderer():
    """render_music.ReferenceRenderer with RectangleClip support (the chrome's clips; the stage's
    scenes set none): a visual whose ``clip`` prop names a ``rect_clip`` object has its subtree
    drawn into a layer and cut to the clip's rect in the visual's space (the chrome's clip holders
    have no offset or transform of their own). Built lazily: render_music pulls in the music art."""
    from .. import render_music as RM
    from PIL import Image

    class PickerReference(RM.ReferenceRenderer):
        def _clip_rect(self, v, t):
            o = self.dev.objects[v]
            clip = o.get("props", {}).get("clip")
            if not clip or clip not in self.dev.objects or self.dev.objects[clip].get("kind") != "rect_clip":
                return None
            return tuple(float(self.value(clip, "clip_" + side, t, d)) for side, d in
                         (("left", -1e9), ("top", -1e9), ("right", 1e9), ("bottom", 1e9)))

        def _draw(self, v, parent, mult, target, t, mode):
            rect = self._clip_rect(v, t)
            if rect is None:
                return super()._draw(v, parent, mult, target, t, mode)
            layer = RM._Canvas(target.size, None)
            self._draw_unclipped(v, parent, mult, layer, t, mode)
            l, tp, r, b = rect
            x0, y0 = RM._apply(parent, l, tp)
            x1, y1 = RM._apply(parent, r, b)
            w, h = target.size
            box = (max(0, int(round(min(x0, x1)))), max(0, int(round(min(y0, y1)))),
                   min(w, int(round(max(x0, x1)))), min(h, int(round(max(y0, y1)))))
            mask = Image.new("L", target.size, 0)
            if box[2] > box[0] and box[3] > box[1]:
                mask.paste(255, box)
            layer.a = Image.composite(layer.a, Image.new("L", target.size, 0), mask)
            layer.pm = Image.composite(layer.pm, Image.new("RGB", target.size, (0, 0, 0)), mask)
            RM._over(target, layer.pm, layer.a, (0, 0), 1.0)

        def _draw_unclipped(self, v, parent, mult, target, t, mode):
            return RM.ReferenceRenderer._draw(self, v, parent, mult, target, t, mode)

    return PickerReference


def render_chrome(chrome, size, t_ticks, background=None):
    """The chrome's tree at ``t_ticks`` as (premultiplied RGB, alpha) images of ``size`` (host px)."""
    from .. import render_music as RM
    cls = reference_renderer()
    r = cls(chrome.dev, chrome.clock.freq)
    canvas = RM._Canvas(size, background)
    r._draw(chrome.root.ptr, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), 1.0, canvas, t_ticks, 0)
    return canvas.pm, canvas.a
