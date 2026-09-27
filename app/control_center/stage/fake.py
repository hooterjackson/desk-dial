"""The stage's fake device: a recording, semantic model of the COM surface every test uses
(DESKTOP_STAGE §4.8: "The DirectComposition backend ... sits behind an interface with a fake that
every test uses"). Pure Python.

It implements the same protocol as ``device.NativeDevice``:
``fn(slot_name, ptr)`` returns a callable ``f(ptr, *args) -> HRESULT`` for any slot of
``com.SLOTS`` (the hot-path setters); ``create_*``, ``upload``, ``commit``, ``frame_statistics``,
``check_device_state``, ``boost``, ``release`` and ``teardown`` are the rest.

The model enforces the contract so tests fail loudly:
- a NEAREST_NEIGHBOR interpolation or HARD border is an error (H6, AR-8);
- modifying an animation object while it is bound to a property is a violation (§4.6.5 item 4,
  G1-7): the ping-pong pool must hand the builder the unbound object;
- uploads must carry exactly w * h * 4 bytes;
- ``fail_next(op, hr)`` injects a failed HRESULT (device loss, §4.3).

It also models the **upload-Commit spacing** the native device shows (``device`` module docstring;
the 2026-09-26 frame-drop fixes): a Commit that carries uploads within ``THROTTLE_FRAMES`` frames
of the previous upload-carrying Commit would block on the native device until then. Every
Commit is logged (``commit_log``: its time, the uploads it carried and that predicted wait) and
the waits land in ``throttled``, so a test can count them (the fake itself never blocks).
"""
from __future__ import annotations

from . import com

P240 = 240


class FakeClock:
    """A settable QPC-like clock in ticks (default 10 MHz) with a 240 Hz vblank grid."""

    def __init__(self, freq: int = 10_000_000, hz: float = 240.0, start: int = 1_000_000_000):
        self.freq = int(freq)
        self.hz = float(hz)
        self.t = int(start)

    @property
    def period(self) -> float:
        return self.freq / self.hz

    def __call__(self) -> int:
        return self.t

    def advance(self, seconds: float) -> int:
        self.t += int(round(seconds * self.freq))
        return self.t

    def perf(self) -> float:
        return self.t / self.freq


class VisualRef:
    """A visual: its IDCompositionVisual2 pointer and, when opacity is animated, Visual3."""

    __slots__ = ("ptr", "v3", "name")

    def __init__(self, ptr, v3, name=""):
        self.ptr, self.v3, self.name = ptr, v3, name

    def __repr__(self):
        return f"<Visual {self.name or self.ptr}>"


class FakeFrameStats:
    __slots__ = ("lastFrameTime", "rateNum", "rateDen", "currentTime", "timeFrequency", "nextEstimatedFrameTime")


_OBJ_PROPS = {
    "Visual.SetOffsetX": "offset_x", "Visual.SetOffsetX.anim": "offset_x",
    "Visual.SetOffsetY": "offset_y", "Visual.SetOffsetY.anim": "offset_y",
    "Visual3.SetOpacity": "opacity", "Visual3.SetOpacity.anim": "opacity",
    "EffectGroup.SetOpacity": "opacity", "EffectGroup.SetOpacity.anim": "opacity",
    "Scale.SetScaleX": "scale_x", "Scale.SetScaleX.anim": "scale_x",
    "Scale.SetScaleY": "scale_y", "Scale.SetScaleY.anim": "scale_y",
    "Scale.SetCenterX": "center_x", "Scale.SetCenterY": "center_y",
    "Visual2.SetOpacityMode": "opacity_mode", "Visual.SetBitmapInterpolationMode": "interp",
    "Visual.SetBorderMode": "border", "Visual.SetContent": "content", "Visual.SetEffect": "effect",
    "Visual.SetTransform.object": "transform", "Visual.SetTransform.matrix": "transform",
    "Visual.SetClip.object": "clip", "Visual.SetClip.rect": "clip",
}


class FakeDevice:
    """Recording model of the stage device (see the module docstring)."""

    kind = "fake"
    THROTTLE_FRAMES = 2              # the native upload-Commit spacing (device module docstring)

    def __init__(self, clock: FakeClock | None = None, time_frequency: int | None = None):
        self.clock = clock or FakeClock()
        self.time_frequency = int(time_frequency or self.clock.freq)
        self.freq = self.time_frequency
        self.objects = {}                 # id -> dict
        self.order = []                   # creation order (ids)
        self.next_id = 0x1000
        self.calls = []                   # (name, ptr, args) of every call
        self.commits = 0
        self.commit_calls = []            # number of calls in each committed batch
        self._batch_calls = 0
        self.violations = []
        self.bound_by = {}                # anim id -> set((obj, prop))
        self.prop_anim = {}               # (obj, prop) -> anim id
        self.failures = {}                # op name -> hr to return once
        self.boosts = []
        self.valid = True
        self.targets = {}
        self.info = {"kind": "fake", "timeFrequency": self.time_frequency}
        self.lost = False
        self.uploads_pending = 0          # uploads not committed yet (device.NativeDevice's counters)
        self.upload_bytes_pending = 0
        self.last_upload_t = None
        self.last_upload_commit = None
        self.upload_commits = 0
        self.flushes = 0
        self.commit_log = []              # per Commit: {"t", "uploads", "bytes", "wait_s"}
        self.throttled = []               # the upload-carrying Commits the native device would block

    def now(self) -> float:
        """The fake clock in seconds (the native device's perf seconds)."""
        return self.clock.perf()

    def flush(self):
        self.flushes += 1

    # ------------------------------------------------------------------ helpers
    def _new(self, kind, name, **extra):
        oid = self.next_id
        self.next_id += 0x10
        self.objects[oid] = {"kind": kind, "name": name, "children": [], "released": False, **extra}
        self.order.append(oid)
        return oid

    def _fail(self, op):
        hr = self.failures.pop(op, None)
        if hr is not None:
            self.calls.append((op, None, ("FAILED", hr)))
            if com.is_device_lost(hr):
                self.lost = True
                self.valid = False
        return hr

    def fail_next(self, op: str, hr: int):
        self.failures[op] = hr

    def obj(self, oid):
        return self.objects[oid]

    def alive(self) -> int:
        return sum(1 for o in self.objects.values() if not o["released"])

    def calls_named(self, name):
        return [c for c in self.calls if c[0] == name]

    # ------------------------------------------------------------------ creation
    def create_visual(self, name="", v3=False) -> VisualRef:
        hr = self._fail("CreateVisual")
        if hr is not None:
            com.check(hr, "CreateVisual")
        oid = self._new("visual", name, props={})
        self.calls.append(("Device.CreateVisual", None, (name,)))
        return VisualRef(oid, oid if v3 else 0, name)

    def create_scale(self, name=""):
        self.calls.append(("Device.CreateScaleTransform", None, (name,)))
        return self._new("scale", name, props={})

    def create_transform_group(self, transforms, name=""):
        self.calls.append(("Device.CreateTransformGroup", None, (tuple(transforms),)))
        return self._new("transform_group", name, members=tuple(transforms), props={})

    def create_effect_group(self, name=""):
        self.calls.append(("Device.CreateEffectGroup", None, (name,)))
        return self._new("effect_group", name, props={})

    def create_animation(self, name=""):
        self.calls.append(("Device.CreateAnimation", None, (name,)))
        return self._new("animation", name, begin=None, segs=[], end=None, resets=0)

    def create_surface(self, w, h, opaque, name=""):
        hr = self._fail("CreateSurface")
        if hr is not None:
            com.check(hr, "CreateSurface")
        self.calls.append(("Device.CreateSurface", None, (w, h, opaque)))
        return self._new("surface", name, size=(int(w), int(h)), opaque=bool(opaque), uploads=0, data=None)

    def create_target(self, hwnd):
        self.calls.append(("Device.CreateTargetForHwnd", None, (hwnd,)))
        oid = self._new("target", f"target:{hwnd}", root=None)
        self.targets[oid] = hwnd
        return oid

    def upload(self, surface, w, h, data, name=""):
        hr = self._fail("Upload")
        if hr is not None:
            com.check(hr, "Upload")
        o = self.objects[surface]
        if (int(w), int(h)) != o["size"]:
            raise ValueError(f"upload {w}x{h} into a {o['size']} surface")
        if len(data) != int(w) * int(h) * 4:
            raise ValueError(f"upload of {len(data)} bytes for {w}x{h}")
        o["uploads"] += 1
        o["data"] = bytes(data[:16])
        self.calls.append(("Upload", surface, (w, h)))
        self._batch_calls += 3
        self.uploads_pending += 1
        self.upload_bytes_pending += len(data)
        self.last_upload_t = self.now()

    def set_root(self, target, visual):
        self.calls.append(("Target.SetRoot", target, (visual,)))
        self.objects[target]["root"] = visual
        return 0

    def release(self, oid):
        if not oid or oid not in self.objects:
            return 0
        o = self.objects[oid]
        if o["released"]:
            self.violations.append(("double release", oid))
            return 0
        o["released"] = True
        self.calls.append(("Unknown.Release", oid, ()))
        return 0

    def teardown(self) -> int:
        n = 0
        for oid in reversed(self.order):
            if not self.objects[oid]["released"]:
                self.objects[oid]["released"] = True
                n += 1
        self.calls.append(("teardown", None, (n,)))
        return n

    # ------------------------------------------------------------------ device
    def commit(self):
        hr = self._fail("Commit")
        self.calls.append(("Device.Commit", None, ()))
        if hr is not None:
            com.check(hr, "Commit")
        self.commits += 1
        self.commit_calls.append(self._batch_calls)
        self._batch_calls = 0
        now = self.now()
        wait = 0.0
        if self.uploads_pending:
            if self.last_upload_commit is not None:
                wait = max(0.0, self.last_upload_commit + self.THROTTLE_FRAMES / self.clock.hz - now)
            if wait > 0.0:
                self.throttled.append({"t": now, "wait_s": wait, "uploads": self.uploads_pending})
            self.last_upload_commit = now + wait          # the native Commit returns then
            self.upload_commits += 1
        self.commit_log.append({"t": now, "uploads": self.uploads_pending, "bytes": self.upload_bytes_pending,
                                "wait_s": wait})
        self.uploads_pending = self.upload_bytes_pending = 0
        return 0

    def wait_commit(self):
        self.calls.append(("Device.WaitForCommitCompletion", None, ()))
        return 0

    def frame_statistics(self):
        hr = self._fail("GetFrameStatistics")
        if hr is not None:
            com.check(hr, "GetFrameStatistics")
        now = self.clock()
        P = self.clock.period
        last = int((now // P) * P)
        fs = FakeFrameStats()
        fs.lastFrameTime = last
        fs.rateNum, fs.rateDen = int(round(self.clock.hz)), 1
        fs.currentTime = now
        fs.timeFrequency = self.time_frequency
        fs.nextEstimatedFrameTime = int(round(last + P))
        return fs

    def check_device_state(self) -> bool:
        hr = self._fail("CheckDeviceState")
        if hr is not None:
            self.valid = False
        return self.valid

    def removed_reason(self) -> int:
        return com.DXGI_ERROR_DEVICE_REMOVED if self.lost else 0

    def boost(self, on: bool):
        self.boosts.append(bool(on))
        return 0

    def animation_fns(self):
        """(Reset, SetAbsoluteBeginTime, AddCubic, End) callables, resolved once (one vtable)."""
        probe = getattr(self, "_fns_probe", None)
        if probe is None:
            probe = self._fns_probe = self._new("animation", "fns-probe", begin=None, segs=[], end=None, resets=0)
        return (self.fn("Animation.Reset", probe), self.fn("Animation.SetAbsoluteBeginTime", probe),
                self.fn("Animation.AddCubic", probe), self.fn("Animation.End", probe))

    # ------------------------------------------------------------------ hot-path callables
    def fn(self, name: str, ptr):
        if name not in com.SLOTS:
            raise KeyError(name)
        if not ptr:
            raise ValueError(f"{name}: null pointer")
        dev = self

        def call(p, *args):
            dev.calls.append((name, p, args))
            dev._batch_calls += 1
            return dev._apply(name, p, args)
        return call

    def _unbind(self, obj, prop):
        a = self.prop_anim.pop((obj, prop), None)
        if a is not None:
            s = self.bound_by.get(a)
            if s:
                s.discard((obj, prop))

    def _apply(self, name, p, args):
        o = self.objects.get(p)
        if o is None:
            self.violations.append(("unknown object", name, p))
            return com.C.c_long(0x80070057).value
        if o["released"]:
            self.violations.append(("call on a released object", name, p))
        prop = _OBJ_PROPS.get(name)
        if name.startswith("Animation."):
            if self.bound_by.get(p):
                self.violations.append(("modified a bound animation", name, p))
            if name == "Animation.Reset":
                o.update(begin=None, segs=[], end=None)
                o["resets"] += 1
            elif name == "Animation.SetAbsoluteBeginTime":
                o["begin"] = args[0]
            elif name == "Animation.AddCubic":
                o["segs"].append(tuple(args))
            elif name == "Animation.End":
                o["end"] = tuple(args)
            return 0
        if name == "Visual.SetBitmapInterpolationMode" and args[0] == com.FORBIDDEN_INTERPOLATION:
            self.violations.append(("NEAREST_NEIGHBOR", p))
        if name == "Visual.SetBorderMode" and args[0] == com.FORBIDDEN_BORDER:
            self.violations.append(("HARD border", p))
        if name == "Visual.AddVisual":
            child, above, ref = args
            kids = o["children"]
            if child in kids:
                self.violations.append(("AddVisual of a present child", child))
                return com.C.c_long(0x80070057).value
            if ref:
                i = kids.index(ref)
                kids.insert(i + 1 if above else i, child)
            elif above:
                kids.insert(0, child)          # NULL + insertAbove=TRUE: behind all siblings
            else:
                kids.append(child)             # NULL + insertAbove=FALSE: in front of all siblings
            return 0
        if name == "Visual.RemoveVisual":
            if args[0] in o["children"]:
                o["children"].remove(args[0])
            return 0
        if name == "Visual.RemoveAllVisuals":
            o["children"].clear()
            return 0
        if prop is not None:
            val = args[0] if args else None
            if name.endswith(".anim"):
                self._unbind(p, prop)
                self.prop_anim[(p, prop)] = val
                self.bound_by.setdefault(val, set()).add((p, prop))
                o["props"][prop] = ("anim", val)
            else:
                if prop in ("offset_x", "offset_y", "opacity", "scale_x", "scale_y"):
                    self._unbind(p, prop)
                if name == "Visual.SetTransform.matrix":
                    m = args[0]
                    m = getattr(m, "_obj", m)
                    val = ("matrix", tuple(round(float(getattr(m, f)), 4) for f in ("_11", "_12", "_21", "_22",
                                                                                     "_31", "_32")))
                elif name == "Visual.SetClip.rect":
                    r = getattr(args[0], "_obj", args[0])
                    val = None if r is None else ("rect", (r.left, r.top, r.right, r.bottom))
                o.setdefault("props", {})[prop] = val
            return 0
        return 0

    # ------------------------------------------------------------------ inspection
    def animation_of(self, obj, prop):
        a = self.prop_anim.get((obj, prop))
        return None if a is None else self.objects[a]

    def value_now(self, obj, prop):
        """The property's static value, or ('anim', id) while an animation is bound."""
        return self.objects[obj]["props"].get(prop)


class FakeHost:
    """A host window stand-in: records show / hide / exclusion calls, never touches Win32.
    ``dpi_on_show`` models a show onto a monitor of another DPI: like ``HostWindow.show``'s
    ``SetWindowPos``, it delivers ``WM_DPICHANGED`` (that DPI) from inside the move."""

    def __init__(self, handler, hwnd=0xBEEF, dpi_on_show=None):
        self.input = handler
        self.role = handler.role
        self.hwnd = hwnd
        self.shown = False
        self.log = []
        self.registered = False
        self.destroyed = False
        self.dpi_on_show = dpi_on_show

    def register_notifications(self):
        self.registered = True
        return {"wts": True, "power": 1}

    def unregister_notifications(self):
        self.registered = False

    def show(self, rect):
        with self.input.own_move():
            if self.dpi_on_show:
                from .host import WM_DPICHANGED
                d = int(self.dpi_on_show)
                self.input.handle(WM_DPICHANGED, (d << 16) | d, 0)
            self.shown = True
        self.log.append(("show", tuple(rect)))
        return True

    def hide(self):
        self.shown = False
        self.log.append(("hide",))

    def exclude_from_capture(self, on):
        self.log.append(("exclude", bool(on)))
        return True

    def destroy(self):
        self.destroyed = True
        self.log.append(("destroy",))


class SyncCapture:
    """A capture worker that runs each job at once on the calling thread with a synthetic grab
    (a gradient) or none (``grab=None`` -> the capture failed: the tint-only frost)."""

    def __init__(self, on_result, grab="gradient", defer=False):
        from .capture import StageCaptureWorker
        self.on_result = on_result
        self.defer = defer
        self.pending = []
        self.jobs = []
        self.affinity_calls = []

        def fake_grab(rect):
            if grab is None:
                return None
            from PIL import Image
            w, h = int(rect[2]), int(rect[3])
            return Image.linear_gradient("L").resize((w, h)).convert("RGB")
        self.worker = StageCaptureWorker(on_result, grab=fake_grab,
                                         affinity=lambda hwnds, on: self.affinity_calls.append((hwnds, on)) or True,
                                         start=False)

    def submit(self, job):
        self.jobs.append(job)
        if self.defer:
            self.pending.append(job)
            return True
        self.on_result(self.worker.run_job(job))
        return True

    def release_pending(self):
        jobs, self.pending = self.pending, []
        for job in jobs:
            self.on_result(self.worker.run_job(job))

    def close(self, timeout=None):
        return True