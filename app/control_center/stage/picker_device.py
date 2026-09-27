"""The picker chrome's native device made in two halves, so a knob touch's warm-up never holds
``NanoD-carousel`` (review finding WP7c-R6; K4 §4.2; CAROUSEL.md §12.4 "The device").

``NativeDevice`` makes everything in one call on the calling thread. For the chrome that thread is
``NanoD-carousel``, which also answers ``show()``'s 150 ms handshake, and ``D3D11CreateDevice`` is the
slow part: measured headlessly on this PC, 129 ms for the process's first device and 14-28 ms for
the next ones, against about 1 ms for ``DCompositionCreateDevice3``. So the warm-up splits it:

- ``prepare(hmonitor)`` runs on a short-lived worker thread: the adapter that owns the monitor
  (never a cross-adapter device), then the default adapter, then WARP, and ``D3D11CreateDevice``.
  An ``ID3D11Device`` is free-threaded; its immediate context is used by one thread at a time, and
  after the hand-off only ``NanoD-carousel`` uses it.
- ``adopt(prepared)`` runs on ``NanoD-carousel``: ``IDXGIDevice``, the DirectComposition device (and
  its v1 interface for ``CheckDeviceState``) and the timeFrequency check (G1-8). The result is a
  ``NativeDevice`` in every respect (same protocol, same teardown in reverse creation order).
- ``discard(prepared)`` releases a half that is never adopted (the chrome closed, or the open went to
  another monitor).

The first half mirrors ``NativeDevice._create`` (device.py belongs to another package); the
self-test and ``tests/test_stage_picker.py`` make a device both ways on this PC.
"""
from __future__ import annotations

import ctypes as C
import threading
import time

from . import com
from .device import NativeDevice


class PreparedD3D:
    """The D3D11 half of a device (made on any thread). Owns ``d3d`` and ``ctx`` until ``take()``."""

    def __init__(self, hmonitor, d3d, ctx, info):
        self.hmonitor = hmonitor
        self.d3d = d3d
        self.ctx = ctx
        self.info = info
        self.thread = threading.current_thread().name
        self._lock = threading.Lock()

    def take(self):
        """(d3d, ctx), handing ownership to the caller; (None, None) once taken or released."""
        with self._lock:
            out = (self.d3d, self.ctx)
            self.d3d = self.ctx = None
        return out

    def release(self) -> int:
        d3d, ctx = self.take()
        n = 0
        for ptr in (ctx, d3d):
            if ptr:
                com.release(ptr)
                n += 1
        return n


def prepare(hmonitor=None, allow_warp: bool = True) -> PreparedD3D:
    """The slow half (see the module docstring). Raises when no device can be made."""
    from . import win32 as W
    info = {}
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
        if ctx.value:
            com.release(ctx.value)
        raise com.ComError("D3D11CreateDevice", -1)
    return PreparedD3D(hmonitor, dev.value, ctx.value, info)


class ChromeDevice(NativeDevice):
    """A ``NativeDevice`` whose D3D11 half was made by ``prepare`` (possibly on another thread)."""

    def __init__(self, prepared: PreparedD3D):
        self._prepared = prepared
        super().__init__(prepared.hmonitor)

    def _create(self, hmonitor, allow_warp):
        p, self._prepared = self._prepared, None
        W = self.W
        info = self.info
        info.update(p.info)
        info["prepared_on"] = p.thread
        d3d, ctx = p.take()
        if not d3d:
            if ctx:
                com.release(ctx)
            raise com.ComError("adopt: the prepared device was already released", -1)
        self.d3d = self._track(d3d, "ID3D11Device")
        self.ctx = self._track(ctx, "ID3D11DeviceContext")
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


def adopt(prepared: PreparedD3D) -> ChromeDevice:
    """The fast half on ``NanoD-carousel``. On failure every object is released (``NativeDevice``)."""
    return ChromeDevice(prepared)


def discard(prepared) -> int:
    """Release a prepared half that will never be adopted (any thread)."""
    return prepared.release() if prepared is not None else 0
