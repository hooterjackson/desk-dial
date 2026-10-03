"""The stage's D3D11 + DirectComposition device, its loss handling and its lifetime (DESKTOP_STAGE
§4.2, §4.3, §4.5, §4.7.1; G1-8).

``DevicePolicy`` (pure) decides when the device is created, released and recreated:
- warm-up at the first knob touch of the session (``note_touch``, AR-19), or at an open;
- released after **600 s** with no open scene (§4.2, S5-25): every stage COM object, surfaces
  first; the encoded and prepared-sprite caches stay;
- on loss (§4.3): close any open scene with reason ``device``, release everything in reverse
  creation order, log ``GetDeviceRemovedReason`` once, recreate at most **twice, 1 s apart**;
  after a second failure stay cold; the next open tries again. Nothing is re-uploaded eagerly.

``NativeDevice`` (Windows) is the real backend with the protocol ``fake.FakeDevice`` models:
adapter by the monitor's HMONITOR (never a cross-adapter device), then the default adapter,
then WARP; ``DCompositionCreateDevice3`` on the ``IDXGIDevice``; ``IDCompositionDevice`` (v1)
for ``CheckDeviceState``; uploads through ``BeginDraw(IID_ID3D11Texture2D)`` +
``UpdateSubresource`` at the atlas offset + ``EndDraw`` (§4.5); ``timeFrequency`` checked
against QPF at creation (G1-8). Every created object is tracked and released in reverse order.
Everything runs on the ``NanoD-stage`` thread only.

**Upload Commits (the 2026-09-26 frame-drop fixes, S1/S2).** Measured headlessly on this PC
(``probe_throttle4``: a hidden-only host target and no target alike): a ``Commit`` that carries
surface uploads (``EndDraw`` since the previous Commit) returns no sooner than about **8.1-8.5 ms
(two frames at 240 Hz) after the previous upload-carrying Commit**; it blocks until then, whatever
the bytes (64 px or 680 px). A Commit without uploads (properties, binds of surfaces committed
earlier) never waits (0.01-0.03 ms, even 0.5 ms after an upload Commit). The very first
upload-carrying Commit of a new device costs about 10 ms. So the device counts the uploads not
committed yet (``uploads_pending``, ``upload_bytes_pending``) and remembers when the last
upload-carrying Commit returned (``last_upload_commit``, ``now()`` seconds), for the upload queue's
pacing and the open's t1; ``flush()`` (``ID3D11DeviceContext::Flush``) starts the copies at once;
``prime()`` pays the first-Commit cost at creation.
"""
from __future__ import annotations

import ctypes as C
import time

from . import com
from .fake import VisualRef

RELEASE_AFTER_S = 600.0
RECREATE_ATTEMPTS = 2
RECREATE_GAP_S = 1.0
CONTEXT_FLUSH_SLOT = 111       # ID3D11DeviceContext::Flush (d3d11.h; the picker chrome flushes the same slot)
PRIME_PX = 8                   # prime(): the first upload-carrying Commit's one-time cost, paid at creation

COLD, WARM, LOST = "cold", "warm", "lost"


class DevicePolicy:
    """Pure lifetime rules on an injected monotonic clock (seconds)."""

    def __init__(self, release_after_s: float = RELEASE_AFTER_S):
        self.state = COLD
        self.release_after_s = release_after_s
        self.scene_open = False
        self.idle_since = None
        self.attempts = 0
        self.attempts_at_create = 0      # the attempt count ``created`` reset (a loss in warm-up keeps it)
        self.next_try = None
        self.removed_reason_logged = False
        self.history = []

    def _log(self, what, now):
        self.history.append((round(now, 3), what))

    def want_warm(self, now: float) -> bool:
        """A touch or an open asks for the device: True when it should be created now."""
        if self.state == WARM:
            return False
        if self.state == LOST and self.next_try is not None and now < self.next_try:
            return False
        return True

    def created(self, now: float):
        self.attempts_at_create = self.attempts if self.state == LOST else 0
        self.state = WARM
        self.attempts = 0
        self.next_try = None
        if not self.scene_open:
            self.idle_since = now
        self._log("created", now)

    def create_failed(self, now: float):
        self.attempts += 1
        if self.state == LOST and self.attempts < RECREATE_ATTEMPTS:
            self.next_try = now + RECREATE_GAP_S
        else:
            self.state = COLD                    # stay cold; the next open tries again
            self.next_try = None
        self._log("create_failed", now)

    def scene_opened(self, now: float):
        self.scene_open = True
        self.idle_since = None

    def scene_closed(self, now: float):
        self.scene_open = False
        self.idle_since = now

    def release_due(self, now: float) -> bool:
        return (self.state == WARM and not self.scene_open and self.idle_since is not None
                and now - self.idle_since >= self.release_after_s)

    def released(self, now: float):
        self.state = COLD
        self.idle_since = None
        self._log("released", now)

    def lost(self, now: float):
        """§4.3: the caller has closed the scene (reason ``device``) and released everything."""
        self.state = LOST
        self.attempts = 0
        self.next_try = now
        self.scene_open = False
        self.idle_since = None
        self._log("lost", now)

    def lost_while_creating(self, now: float):
        """The device was lost inside its own creation warm-up (e.g. mid-TDR): count it as a failed
        attempt, keeping the count ``created`` reset, so the recreate cap (at most twice 1 s apart)
        holds instead of a fresh ``lost`` restarting the attempts at once every turn."""
        self.scene_open = False
        self.idle_since = None
        self.state = LOST
        self.attempts = self.attempts_at_create
        self.create_failed(now)

    def recreate_due(self, now: float) -> bool:
        return self.state == LOST and self.attempts < RECREATE_ATTEMPTS and self.next_try is not None \
            and now >= self.next_try

    def next_wake(self):
        """Seconds (monotonic) of the next policy wake, or None."""
        if self.state == LOST and self.next_try is not None:
            return self.next_try
        if self.state == WARM and not self.scene_open and self.idle_since is not None:
            return self.idle_since + self.release_after_s
        return None


class NativeDevice:
    """The real device (Windows). See the module docstring. Construct on ``NanoD-stage``."""

    kind = "native"

    def __init__(self, hmonitor=None, *, allow_warp: bool = True):
        from . import win32
        self.W = win32
        self.objs = {}              # ptr -> name, creation order (dict keeps it)
        self.info = {}
        self.d3d = self.ctx = self.dxgi = self.dev = self.dev1 = None
        self._fns = None
        self._flush = None
        self.torn_down = False
        self.uploads_pending = 0            # surface uploads (EndDraw) not committed yet
        self.upload_bytes_pending = 0
        self.last_upload_t = None           # now() of the newest upload
        self.last_upload_commit = None      # now() when the last upload-carrying Commit returned
        self.upload_commits = 0
        try:
            self._create(hmonitor, allow_warp)
        except BaseException:
            self.teardown()
            raise

    # ------------------------------------------------------------------ creation
    def _track(self, ptr, name):
        if ptr:
            self.objs[ptr] = name
        return ptr

    def _create(self, hmonitor, allow_warp):
        W = self.W
        info = self.info
        fac = C.c_void_p()
        com.check(W.CreateDXGIFactory1(C.byref(com.IID_IDXGIFactory1), C.byref(fac)), "CreateDXGIFactory1")
        chosen = None
        adapters = []
        try:
            i = 0
            while True:
                ad = C.c_void_p()
                if com.vfn(fac.value, "Factory1.EnumAdapters1")(fac.value, i, C.byref(ad)) != 0:
                    break
                desc = com.DXGI_ADAPTER_DESC1()
                com.vfn(ad.value, "Adapter1.GetDesc1")(ad.value, C.byref(desc))
                owns = False
                j = 0
                while True:
                    o = C.c_void_p()
                    if com.vfn(ad.value, "Adapter.EnumOutputs")(ad.value, j, C.byref(o)) != 0:
                        break
                    od = com.DXGI_OUTPUT_DESC()
                    com.vfn(o.value, "Output.GetDesc")(o.value, C.byref(od))
                    if hmonitor and od.Monitor == hmonitor:
                        owns = True
                    com.release(o.value)
                    j += 1
                adapters.append({"index": i, "name": desc.Description, "software": bool(desc.Flags & 2),
                                 "owns_monitor": owns})
                if owns and chosen is None:
                    chosen = ad.value
                else:
                    com.release(ad.value)
                i += 1
        finally:
            com.release(fac.value)
        info["adapters"] = adapters
        levels = (C.c_uint * len(com.FEATURE_LEVELS))(*com.FEATURE_LEVELS)
        attempts = []
        if chosen:
            attempts.append(("monitor_adapter", chosen, com.D3D_DRIVER_TYPE_UNKNOWN))
        attempts.append(("default_hardware", None, com.D3D_DRIVER_TYPE_HARDWARE))
        if allow_warp:
            attempts.append(("warp", None, com.D3D_DRIVER_TYPE_WARP))
        dev, ctx, fl = C.c_void_p(), C.c_void_p(), C.c_uint()
        tried = []
        try:
            for label, adp, drv in attempts:
                t0 = time.perf_counter()
                hr = W.D3D11CreateDevice(adp, drv, None, com.D3D11_CREATE_DEVICE_BGRA_SUPPORT, levels, len(levels),
                                         com.D3D11_SDK_VERSION, C.byref(dev), C.byref(fl), C.byref(ctx))
                tried.append({"path": label, "hr": com.hx(hr), "ms": round((time.perf_counter() - t0) * 1000, 1)})
                if hr == 0:
                    info["d3d11"] = {"path": label, "feature_level": hex(fl.value)}
                    break
        finally:
            if chosen:
                com.release(chosen)
        info["d3d11_attempts"] = tried
        if not dev.value:
            raise com.ComError("D3D11CreateDevice", -1)
        self.d3d = self._track(dev.value, "ID3D11Device")
        self.ctx = self._track(ctx.value, "ID3D11DeviceContext")
        hr, dx = com.qi(self.d3d, com.IID_IDXGIDevice)
        com.check(hr, "QI IDXGIDevice")
        self.dxgi = self._track(dx, "IDXGIDevice")
        dc = C.c_void_p()
        t0 = time.perf_counter()
        com.check(W.DCompositionCreateDevice3(self.dxgi, C.byref(com.IID_IDCompositionDesktopDevice), C.byref(dc)),
                  "DCompositionCreateDevice3")
        info["dcomp_create_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        self.dev = self._track(dc.value, "IDCompositionDesktopDevice")
        hr, d1 = com.qi(self.dev, com.IID_IDCompositionDevice)
        if hr == 0:
            self.dev1 = self._track(d1, "IDCompositionDevice")
        self._commit = com.vfn(self.dev, "Device.Commit")
        self._stats = com.vfn(self.dev, "Device.GetFrameStatistics")
        fs = self.frame_statistics()
        self.time_frequency = int(fs.timeFrequency)
        self.qpf = W.qpf()
        info["timeFrequency"] = self.time_frequency
        info["qpf"] = self.qpf
        info["timeFrequency_equals_qpf"] = self.time_frequency == self.qpf      # G1-8
        self.freq = self.time_frequency if self.time_frequency > 0 else self.qpf

    # ------------------------------------------------------------------ protocol
    @staticmethod
    def now() -> float:
        """The clock of ``last_upload_t`` / ``last_upload_commit`` (perf seconds, QPC)."""
        return time.perf_counter()

    def fn(self, name, ptr):
        return com.vfn(ptr, name)

    def flush(self):
        """``ID3D11DeviceContext::Flush`` (WF: it may wait on the driver): the queued surface copies
        start now instead of at the next Commit."""
        f = self._flush
        if f is None:
            if not self.ctx:
                return
            vtbl = C.c_void_p.from_address(self.ctx).value
            f = self._flush = C.WINFUNCTYPE(None, C.c_void_p)(C.c_void_p.from_address(vtbl + 8 * CONTEXT_FLUSH_SLOT).value)
        f(self.ctx)

    def prime(self):
        """Pay the device's first upload-carrying Commit (about 10 ms here, headless) at creation (a
        knob touch's warm-up, or a cold open in parallel with its capture), not in an open's batch:
        one tiny surface uploaded, flushed, committed and released."""
        s = self.create_surface(PRIME_PX, PRIME_PX, True, "prime")
        try:
            self.upload(s, PRIME_PX, PRIME_PX, bytes(PRIME_PX * PRIME_PX * 4), "prime")
            self.flush()
            self.commit()
        finally:
            self.release(s)

    def animation_fns(self):
        if self._fns is None:
            probe = self.create_animation("fns-probe")
            self._fns = (com.vfn(probe, "Animation.Reset"), com.vfn(probe, "Animation.SetAbsoluteBeginTime"),
                         com.vfn(probe, "Animation.AddCubic"), com.vfn(probe, "Animation.End"))
        return self._fns

    def _create_out(self, slot, name, *args):
        out = C.c_void_p()
        com.call(self.dev, slot, *args, C.byref(out))
        return self._track(out.value, name)

    def create_visual(self, name="", v3=False) -> VisualRef:
        p = self._create_out("Device.CreateVisual", name or "visual")
        p3 = 0
        if v3:
            hr, p3 = com.qi(p, com.IID_IDCompositionVisual3)
            com.check(hr, "QI IDCompositionVisual3")
            self._track(p3, (name or "visual") + ".v3")
        return VisualRef(p, p3, name)

    def create_scale(self, name=""):
        return self._create_out("Device.CreateScaleTransform", name or "scale")

    def create_transform_group(self, transforms, name=""):
        arr = (C.c_void_p * len(transforms))(*transforms)
        out = C.c_void_p()
        com.call(self.dev, "Device.CreateTransformGroup", arr, len(transforms), C.byref(out))
        return self._track(out.value, name or "transform_group")

    def create_effect_group(self, name=""):
        return self._create_out("Device.CreateEffectGroup", name or "effect_group")

    def create_rect_clip(self, name=""):
        return self._create_out("Device.CreateRectangleClip", name or "clip")

    def create_animation(self, name=""):
        return self._create_out("Device.CreateAnimation", name or "animation")

    def create_surface(self, w, h, opaque, name=""):
        return self._create_out("Device.CreateSurface", name or "surface", int(w), int(h),
                                com.DXGI_FORMAT_B8G8R8A8_UNORM,
                                com.DXGI_ALPHA_MODE_IGNORE if opaque else com.DXGI_ALPHA_MODE_PREMULTIPLIED)

    def create_target(self, hwnd):
        return self._create_out("Device.CreateTargetForHwnd", "IDCompositionTarget", C.c_void_p(hwnd), 1)

    def set_root(self, target, visual):
        return com.call(target, "Target.SetRoot", visual)

    def upload(self, surface, w, h, data, name="", verify=False):
        """§4.5: BeginDraw(ID3D11Texture2D) -> UpdateSubresource at the atlas offset -> EndDraw.
        ``data`` is premultiplied BGRA, ``w * 4`` bytes per row. With ``verify`` the region is
        read back through a staging texture before EndDraw (self-test only); returns the match."""
        w, h = int(w), int(h)
        if len(data) != w * h * 4:
            raise ValueError(f"{name}: {len(data)} bytes for {w}x{h}")
        tex, off = C.c_void_p(), com.POINT()
        com.call(surface, "Surface.BeginDraw", None, C.byref(com.IID_ID3D11Texture2D), C.byref(tex), C.byref(off))
        ok = None
        try:
            box = com.D3D11_BOX(off.x, off.y, 0, off.x + w, off.y + h, 1)
            src = C.c_char_p(bytes(data)) if not isinstance(data, bytes) else C.c_char_p(data)
            com.vfn(self.ctx, "Context.UpdateSubresource")(self.ctx, tex.value, 0, C.byref(box),
                                                             C.cast(src, C.c_void_p), w * 4, 0)
            if verify:
                ok = self._readback(tex.value, box, w, h) == bytes(data)
        finally:
            hr = com.vfn(surface, "Surface.EndDraw")(surface)
            if tex.value:
                com.release(tex.value)
        com.check(hr, f"EndDraw {name}")
        self.uploads_pending += 1
        self.upload_bytes_pending += w * h * 4
        self.last_upload_t = time.perf_counter()
        return ok

    def _readback(self, tex, box, w, h) -> bytes:
        sd = com.D3D11_TEXTURE2D_DESC(w, h, 1, 1, com.DXGI_FORMAT_B8G8R8A8_UNORM, com.DXGI_SAMPLE_DESC(1, 0),
                                      com.D3D11_USAGE_STAGING, 0, com.D3D11_CPU_ACCESS_READ, 0)
        stg = C.c_void_p()
        com.call(self.d3d, "D3D11.CreateTexture2D", C.byref(sd), None, C.byref(stg))
        try:
            com.vfn(self.ctx, "Context.CopySubresourceRegion")(self.ctx, stg.value, 0, 0, 0, 0, tex, 0, C.byref(box))
            mp = com.D3D11_MAPPED_SUBRESOURCE()
            com.call(self.ctx, "Context.Map", stg.value, 0, com.D3D11_MAP_READ, 0, C.byref(mp))
            try:
                return b"".join(C.string_at(mp.pData + y * mp.RowPitch, w * 4) for y in range(h))
            finally:
                com.vfn(self.ctx, "Context.Unmap")(self.ctx, stg.value, 0)
        finally:
            com.release(stg.value)

    def commit(self):
        hr = self._commit(self.dev)
        if self.uploads_pending and hr >= 0:
            self.last_upload_commit = time.perf_counter()
            self.upload_commits += 1
            self.uploads_pending = self.upload_bytes_pending = 0
        return com.check(hr, "Commit")

    def wait_commit(self):
        return com.call(self.dev, "Device.WaitForCommitCompletion")

    def frame_statistics(self):
        fs = com.DCOMPOSITION_FRAME_STATISTICS()
        com.check(self._stats(self.dev, C.byref(fs)), "GetFrameStatistics")
        return fs

    def check_device_state(self) -> bool:
        if not self.dev1:
            return True
        v = C.c_int(0)
        hr = com.vfn(self.dev1, "Device1.CheckDeviceState")(self.dev1, C.byref(v))
        return hr == 0 and bool(v.value)

    def removed_reason(self) -> int:
        return com.vfn(self.d3d, "D3D11.GetDeviceRemovedReason")(self.d3d) if self.d3d else 0

    def boost(self, on: bool):
        f = self.W.DCompositionBoostCompositorClock
        return f(bool(on)) if f else None

    def release(self, ptr):
        if ptr and ptr in self.objs:
            del self.objs[ptr]
            com.release(ptr)

    def alive(self) -> int:
        return len(self.objs)

    def teardown(self) -> int:
        """Release every tracked object in reverse creation order (§4.3 step 2)."""
        if self.torn_down:
            return 0
        self.torn_down = True
        n = 0
        for ptr in reversed(list(self.objs)):
            try:
                com.release(ptr)
                n += 1
            except Exception:
                pass
        self.objs.clear()
        self.d3d = self.ctx = self.dxgi = self.dev = self.dev1 = None
        return n
