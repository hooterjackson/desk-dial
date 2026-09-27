"""The ``NanoD-stage-capture`` worker (DESKTOP_STAGE §2.2, §2.6, §4.9, §12).

One job at a time, newest wins: exclude our other visible windows from capture
(``WDA_EXCLUDEFROMCAPTURE``, only windows of this process; the stage host itself is still hidden
at open, so it needs none), ``BitBlt`` the monitor from the screen DC, drop the exclusions
(``WDA_NONE``), then build the recipe's frost at 1/8 and, when asked, the first ambient layer.
The full-monitor capture (29.5 MB at 5120 × 1440) is freed right after ``reduce`` (§14). The
result is posted back through ``on_result`` (the engine signals its own thread); this thread
makes no other HWND call than the affinity and the screen DC (§2.2), and never touches Tk.

The stage thread applies the 500 ms timeout (``CAPTURE_TIMEOUT_S``): a late result is dropped
by generation and the frost falls back to the tint alone (S5-30).
"""
from __future__ import annotations

import threading
import time

from . import blur as B


class CaptureJob:
    __slots__ = ("gen", "rect", "recipe", "k", "exclude", "ambient_source")

    def __init__(self, gen, rect, recipe, k, exclude=(), ambient_source=None):
        self.gen, self.rect, self.recipe, self.k = gen, tuple(rect), recipe, k
        self.exclude = tuple(int(h) for h in exclude if h)
        self.ambient_source = ambient_source


class CaptureResult:
    __slots__ = ("gen", "frost", "source", "ambient", "capture_ms", "build_ms", "error")

    def __init__(self, gen, frost=None, source=None, ambient=None, capture_ms=None, build_ms=None, error=None):
        self.gen, self.frost, self.source, self.ambient = gen, frost, source, ambient
        self.capture_ms, self.build_ms, self.error = capture_ms, build_ms, error


def screen_grab(rect):
    """BitBlt(SRCCOPY | CAPTUREBLT) of the screen DC -> PIL RGB, or None (Windows). The image is
    decoded straight from the DIB's memory before the DIB is freed (no second 29.5 MB copy)."""
    import ctypes as C
    from PIL import Image
    from . import win32 as W
    x, y, w, h = (int(v) for v in rect)
    if w <= 0 or h <= 0:
        return None
    screen = W.GetDC(None)
    if not screen:
        return None
    mdc = dib = old = None
    try:
        mdc = W.CreateCompatibleDC(screen)
        bmi = W.BITMAPINFOHEADER(C.sizeof(W.BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = C.c_void_p()
        dib = W.CreateDIBSection(screen, C.byref(bmi), 0, C.byref(bits), None, 0)
        if not mdc or not dib or not bits.value:
            return None
        old = W.SelectObject(mdc, dib)
        ok = W.BitBlt(mdc, 0, 0, w, h, screen, x, y, W.SRCCOPY | W.CAPTUREBLT)
        W.GdiFlush()
        if not ok:
            return None
        view = (C.c_ubyte * (w * h * 4)).from_address(bits.value)
        image = Image.frombuffer("RGB", (w, h), view, "raw", "BGRX", 0, 1)
        view = None
        return image
    finally:
        if old and mdc:
            W.SelectObject(mdc, old)
        if dib:
            W.DeleteObject(dib)
        if mdc:
            W.DeleteDC(mdc)
        W.ReleaseDC(None, screen)


def set_affinity(hwnds, exclude: bool) -> bool:
    """WDA_EXCLUDEFROMCAPTURE / WDA_NONE on windows of this process (best effort)."""
    import ctypes as C
    import ctypes.wintypes as WT
    from . import win32 as W
    own = int(W.GetCurrentProcessId())
    ok = True
    value = W.WDA_EXCLUDEFROMCAPTURE if exclude else W.WDA_NONE
    for hwnd in hwnds or ():
        if not hwnd or not W.IsWindow(hwnd):
            continue
        pid = WT.DWORD(0)
        W.GetWindowThreadProcessId(hwnd, C.byref(pid))
        if int(pid.value) != own:
            continue
        if not W.SetWindowDisplayAffinity(hwnd, value):
            ok = False
    return ok


class StageCaptureWorker:
    """The capture thread. ``grab(rect)`` and ``affinity(hwnds, on)`` are injectable (tests pass
    fakes and never read the screen)."""

    def __init__(self, on_result, *, grab=None, affinity=None, name="NanoD-stage-capture", start=True):
        self._on_result = on_result
        self._grab = grab or screen_grab
        self._affinity = affinity or set_affinity
        self._cond = threading.Condition()
        self._job = None
        self._closed = False
        self.jobs_done = 0
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        if start:
            self._thread.start()

    @property
    def native_id(self):
        """The OS thread id of ``NanoD-stage-capture`` (for the stage's CPU share, §6.2), or None."""
        return self._thread.native_id if self._thread.is_alive() else None

    def submit(self, job: CaptureJob) -> bool:
        with self._cond:
            if self._closed:
                return False
            self._job = job
            self._cond.notify()
            return True

    def close(self, timeout: float | None = 1.0) -> bool:
        with self._cond:
            self._closed = True
            self._job = None
            self._cond.notify()
        if timeout and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout)
        return not self._thread.is_alive()

    def _run(self):
        try:
            from . import win32 as W
            W.SetThreadDpiAwarenessContext(W.DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        except Exception:
            pass
        while True:
            with self._cond:
                while not self._closed and self._job is None:
                    self._cond.wait()
                if self._closed:
                    return
                job, self._job = self._job, None
            result = self.run_job(job)
            with self._cond:
                if self._closed:
                    return
            self.jobs_done += 1
            try:
                self._on_result(result)
            except Exception:
                pass

    def run_job(self, job: CaptureJob) -> CaptureResult:
        """One job, synchronously (the thread's body; also used directly by tests and benches)."""
        capture_ms = build_ms = None
        raw = None
        error = None
        try:
            if job.exclude:
                self._affinity(job.exclude, True)
            t0 = time.perf_counter()
            try:
                raw = self._grab(job.rect)
            finally:
                if job.exclude:
                    self._affinity(job.exclude, False)
            capture_ms = round((time.perf_counter() - t0) * 1000, 2)
        except Exception as exc:
            error = repr(exc)
            raw = None
        t0 = time.perf_counter()
        try:
            size = (job.rect[2], job.rect[3])
            frost_img, source = B.frost(raw, job.recipe, job.k, size)
            raw = None                                        # freed right after the reduce (§14)
            amb = None
            if job.ambient_source is not None:
                amb = B.ambient(job.ambient_source, job.k, size)
            build_ms = round((time.perf_counter() - t0) * 1000, 2)
            return CaptureResult(job.gen, frost_img, source, amb, capture_ms, build_ms, error)
        except Exception as exc:
            return CaptureResult(job.gen, None, None, None, capture_ms, None, repr(exc))
