"""Real hidden-window lifecycle of the window picker (CAROUSEL.md sections 5, 10 and 12).

SKIPPED unless NANOD_CAROUSEL_LIVE_TESTS=1 (Windows only). It creates the carousel's real
windows (dim, glass, the NOREDIRECTIONBITMAP host, chrome, the label and dots layers, toast) on a
dedicated thread,
exactly like the application, but NEVER shows them: no show(), no show_host(), no SetWindowPos
show path, no SetForegroundWindow. It registers one DWM thumbnail whose source is one of its
own hidden windows (no other application's window is touched), updates it as invisible,
composes a chrome frame into the real DIB and presents it with SourceConstantAlpha 0, uploads a
dim at alpha 0, checks every window stayed hidden, destroys everything in the strict order and
asserts the process's GDI and USER object counts return to baseline. It never captures the
screen. Another test starts and closes the full CarouselPresenter (both threads) without
opening it, and one checks that set_capture_exclusions (the floating knob's WDA_EXCLUDEFROMCAPTURE
during the glass capture) works from another thread on a hidden window of this process, once with
a carousel window and once with the real floating knob (KnobOverlay started hidden, never touched).
One more uploads content at alpha 0 into the hidden dim, glass and chrome (never shown) and checks
that hide_layers() leaves each a 1 x 1 surface (the retained UpdateLayeredWindow memory).

Run it only in the stages that allow hidden windows (Integrate / Package):
    set NANOD_CAROUSEL_LIVE_TESTS=1
    .venv\\Scripts\\python.exe <guard>\\run_no_tk.py test_carousel_live.py
"""
from pathlib import Path
import os
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center import carousel as c  # noqa: E402
from control_center import carousel_render as R  # noqa: E402

LIVE = sys.platform == "win32" and os.environ.get("NANOD_CAROUSEL_LIVE_TESTS") == "1"
SKIP_REASON = "set NANOD_CAROUSEL_LIVE_TESTS=1 (Windows) to create the carousel's hidden, never-shown windows"


def gui_counts(api):
    process = api.k.GetCurrentProcess()
    return (int(api.u.GetGuiResources(process, c.GR_GDIOBJECTS)),
            int(api.u.GetGuiResources(process, c.GR_USEROBJECTS)))


def settle_counts(api, baseline, timeout=1.0):
    deadline = time.monotonic() + timeout
    counts = gui_counts(api)
    while counts != baseline and time.monotonic() < deadline:
        time.sleep(0.02)
        counts = gui_counts(api)
    return counts


@unittest.skipUnless(LIVE, SKIP_REASON)
class HiddenCarouselLifecycle(unittest.TestCase):
    def setUp(self):
        self.api = c.CarouselApi()

    def run_on_thread(self, body, timeout=10.0):
        outcome = {}

        def target():
            try:
                outcome["value"] = body()
            except BaseException as exc:
                outcome["error"] = exc

        thread = threading.Thread(target=target, name="NanoD-carousel-live-test", daemon=True)
        thread.start()
        thread.join(timeout)
        self.assertFalse(thread.is_alive(), "the window thread did not finish")
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("value")

    def test_backend_create_register_compose_destroy_returns_to_baseline(self):
        api = self.api
        baseline = gui_counts(api)

        def body():
            result = {}
            backend = c.Win32CarouselBackend(api=api)
            events, inputs = [], []
            try:
                result["awareness"] = backend.prepare_thread()
                backend.create(events.append, lambda *args: inputs.append(args))
                result["host_mode"] = backend.host_mode
                windows = dict(backend.windows)
                result["created"] = sorted(windows)
                result["visible_after_create"] = [role for role, hwnd in windows.items()
                                                  if api.u.IsWindowVisible(hwnd)]
                handle = backend.register(windows["dim"])          # our own hidden window as the source
                result["registered"] = bool(handle)
                if handle:
                    result["source_size"] = backend.source_size(handle)
                    result["update_ok"] = backend.update_thumbnail(handle, (0, 0, 96, 60), (0, 0, 1, 1), 0, False)
                    # step 3 (CAR 12.4): the frame's thumbnails back to back, GIL-keeping (G1-1)
                    result["batch_ok"] = backend.update_thumbnails([(handle, (0, 0, 96, 60), (0, 0, 1, 1), 0, False),
                                                                    (handle, (1, 1, 97, 61), (0, 0, 1, 1), 0, False)])
                    backend.unregister(handle)
                result["gpu_window"] = backend.gpu_window((0, 0, 64, 64))   # placed, never shown
                result["has_gpu_window"] = backend.has_gpu_window
                layout = R.layout_for((0, 0, 1280, 720))
                canvas = backend.chrome_alloc(layout.band)
                x, s, op, shade = R.table_state(0)
                card = R.ChromeCard(R.card_rect(layout, x, s), s, op, shade, 1.0, None, None, 0)
                scene = R.ChromeScene(layout.k, layout.band_origin, "glass", [card])
                R.compose_chrome(canvas, scene, R.ShadowCache(layout.k))
                result["chrome_ulw"] = backend._ulw("chrome", 0)    # constant alpha 0: invisible anyway
                backend.layer_alloc("label", layout.labels)
                result["label_ulw"] = backend._ulw("label", 0)
                backend.layer_free("label")
                backend.dim_upload(layout, "none")                  # uploads at alpha 0, frees the DIB
                result["counts_open"] = gui_counts(api)
                backend.chrome_free()
                backend.free_large()
                result["visible_before_destroy"] = [role for role, hwnd in windows.items()
                                                    if api.u.IsWindowVisible(hwnd)]
            finally:
                backend.destroy_windows()
                backend.pump()                                      # WM_DESTROY's WM_QUIT
                backend.unregister_classes()
            result["events"] = list(events)
            return result

        result = self.run_on_thread(body)
        self.assertEqual(result["created"], ["chrome", "dim", "dots", "glass", "gpu", "host", "label", "toast"])
        self.assertTrue(result["gpu_window"])
        self.assertTrue(result["has_gpu_window"])
        self.assertTrue(result["batch_ok"])
        self.assertEqual(result["visible_after_create"], [])
        self.assertEqual(result["visible_before_destroy"], [])
        self.assertEqual(result["awareness"], c.DPI_AWARENESS_PER_MONITOR_AWARE)
        self.assertIn(result["host_mode"], (c.HOST_LAYERED, c.HOST_PLAIN))
        self.assertTrue(result["registered"])
        self.assertTrue(result["update_ok"])
        self.assertTrue(result["chrome_ulw"] and result["label_ulw"])
        self.assertEqual(settle_counts(api, baseline), baseline)

    def test_hidden_layers_give_back_their_retained_surfaces(self):
        """After hide, each layered window used to keep its last UpdateLayeredWindow surface
        (about 50 MB at 5120 x 1440 for dim, glass and chrome). On the real, never-shown windows:
        content uploaded at alpha 0 (the glass through its surface directly, since glass_upload
        would show it: the section 11 frost over the whole monitor, rcMonitor), then hide_layers()
        leaves each of them a 1 x 1 surface; nothing shows and GDI/USER return to baseline. The
        real frost window is click-through (layered, WS_EX_TRANSPARENT, never activating)."""
        import ctypes
        from ctypes import wintypes
        api = self.api
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        get_rect = user32.GetWindowRect
        get_rect.restype, get_rect.argtypes = wintypes.BOOL, (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        get_long = user32.GetWindowLongPtrW
        get_long.restype, get_long.argtypes = ctypes.c_ssize_t, (wintypes.HWND, ctypes.c_int)
        GWL_EXSTYLE = -20

        def size(hwnd):
            rect = wintypes.RECT()
            return (rect.right - rect.left, rect.bottom - rect.top) if get_rect(hwnd, ctypes.byref(rect)) else None

        layout = R.layout_for((0, 0, 1280, 720))
        monitor = layout.monitor_rect
        baseline = gui_counts(api)

        def body():
            result = {}
            backend = c.Win32CarouselBackend(api=api)
            try:
                backend.prepare_thread()
                backend.create(lambda *_: None, lambda *_: None)
                windows = dict(backend.windows)
                result["glass_ex"] = int(get_long(windows["glass"], GWL_EXSTYLE)) & 0xFFFFFFFF
                backend.dim_upload(layout, "none")                   # alpha 0, frees its DIB
                backend.chrome_alloc(layout.band)
                result["chrome_ulw"] = backend._ulw("chrome", 0)
                surface = backend._alloc_surface("glass", monitor)   # glass_upload's path minus its show
                surface.canvas.image.paste(R.solid_frost(monitor[2:]).image, (0, 0))
                result["glass_ulw"] = backend._ulw("glass", 0)
                backend._free_surface("glass")
                backend.chrome_free()
                result["before"] = {role: size(windows[role]) for role in c.RETAINED_ULW_ROLES}
                backend.hide_layers()
                result["after"] = {role: size(windows[role]) for role in c.RETAINED_ULW_ROLES}
                result["again"] = backend.release_retained()        # nothing is held any more
                result["visible"] = [role for role, hwnd in windows.items() if api.u.IsWindowVisible(hwnd)]
            finally:
                backend.destroy_windows()
                backend.pump()
                backend.unregister_classes()
            return result

        result = self.run_on_thread(body)
        self.assertTrue(result["chrome_ulw"] and result["glass_ulw"])
        for flag in (c.WS_EX_LAYERED, c.WS_EX_TRANSPARENT, c.WS_EX_NOACTIVATE, c.WS_EX_TOPMOST):
            self.assertTrue(result["glass_ex"] & flag, hex(flag))
        self.assertEqual(result["before"], {"chrome": tuple(layout.band[2:]), "label": (1, 1), "dots": (1, 1),
                                            "glass": tuple(monitor[2:]), "dim": (1280, 720)})
        self.assertEqual(result["after"], {role: (1, 1) for role in c.RETAINED_ULW_ROLES})
        self.assertEqual(result["again"], 0)
        self.assertEqual(result["visible"], [])
        self.assertEqual(settle_counts(api, baseline), baseline)

    def test_host_fallback_round_trip_stays_hidden_and_returns_to_baseline(self):
        """The section 5 fallback and its way back (use_plain_host / use_layered_host) on the
        real, hidden windows: the ownership chain is rebuilt and nothing leaks or shows."""
        api = self.api
        baseline = gui_counts(api)

        def body():
            result = {}
            backend = c.Win32CarouselBackend(api=api)
            try:
                backend.prepare_thread()
                backend.create(lambda *_: None, lambda *_: None)
                result["first"] = backend.host_mode
                backend.use_plain_host()
                result["plain"] = backend.host_mode
                result["layered_back"] = backend.use_layered_host()
                result["mode_back"] = backend.host_mode
                handle = backend.register(backend.windows["dim"])
                result["registered"] = bool(handle)
                if handle:
                    backend.unregister(handle)
                result["visible"] = [role for role, hwnd in backend.windows.items() if api.u.IsWindowVisible(hwnd)]
                result["roles"] = sorted(backend.windows)
            finally:
                backend.destroy_windows()
                backend.pump()
                backend.unregister_classes()
            return result

        result = self.run_on_thread(body)
        self.assertEqual(result["plain"], c.HOST_PLAIN)
        self.assertEqual(result["mode_back"], result["first"])            # layered wherever it was possible
        self.assertEqual(result["layered_back"], result["first"] == c.HOST_LAYERED)
        self.assertTrue(result["registered"])
        self.assertEqual(result["visible"], [])
        self.assertEqual(result["roles"], ["chrome", "dim", "dots", "glass", "gpu", "host", "label", "toast"])
        self.assertEqual(settle_counts(api, baseline), baseline)

    def test_capture_exclusion_works_on_a_hidden_window_of_another_thread(self):
        """set_capture_exclusions runs on the carousel thread, while the floating knob's window
        belongs to another thread of this process: SetWindowDisplayAffinity must work across
        threads (it is checked per process). A hidden toast window of a backend on a helper
        thread stands in for the knob; this thread excludes it and clears it again."""
        import ctypes
        from ctypes import wintypes
        api = self.api
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        get_affinity = user32.GetWindowDisplayAffinity
        get_affinity.restype, get_affinity.argtypes = wintypes.BOOL, (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))

        def read(hwnd):
            value = wintypes.DWORD(0xFFFF)
            return int(value.value) if get_affinity(hwnd, ctypes.byref(value)) else None

        created, finished = threading.Event(), threading.Event()
        shared = {}

        def owner():
            backend = c.Win32CarouselBackend(api=api)
            try:
                backend.prepare_thread()
                backend.create(lambda *_: None, lambda *_: None)
                shared["hwnd"] = backend.windows["toast"]
                created.set()
                deadline = time.monotonic() + 5.0
                while not finished.is_set() and time.monotonic() < deadline:
                    backend.pump()                                   # in case the call needs the owner's queue
                    time.sleep(0.005)
                shared["visible"] = bool(api.u.IsWindowVisible(shared["hwnd"]))
            finally:
                backend.destroy_windows()
                backend.pump()
                backend.unregister_classes()

        thread = threading.Thread(target=owner, name="NanoD-knob-stand-in", daemon=True)
        thread.start()
        try:
            self.assertTrue(created.wait(5.0))
            hwnd = shared["hwnd"]
            caller = c.Win32CarouselBackend(api=api)                  # no windows: only the call
            before = read(hwnd)
            excluded_ok = caller.set_capture_exclusions((hwnd,), True)
            excluded = read(hwnd)
            cleared_ok = caller.set_capture_exclusions((hwnd,), False)
            cleared = read(hwnd)
        finally:
            finished.set()
            thread.join(5.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(before, c.WDA_NONE)
        self.assertTrue(excluded_ok)
        self.assertEqual(excluded, c.WDA_EXCLUDEFROMCAPTURE)
        self.assertTrue(cleared_ok)
        self.assertEqual(cleared, c.WDA_NONE)
        self.assertFalse(shared["visible"])

    def test_the_real_floating_knob_window_can_be_excluded_from_capture(self):
        """End to end with the real floating knob: KnobOverlay.start() creates its hidden window on
        the NanoD-overlay thread; its ``hwnd`` goes to set_capture_exclusions on this thread, the
        affinity reads WDA_EXCLUDEFROMCAPTURE, then WDA_NONE again. The knob is never touched or
        peeked, so it stays hidden; GDI/USER return to baseline after close."""
        import ctypes
        from ctypes import wintypes
        from control_center import overlay as ov
        api = self.api
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        get_affinity = user32.GetWindowDisplayAffinity
        get_affinity.restype, get_affinity.argtypes = wintypes.BOOL, (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))

        def read(hwnd):
            value = wintypes.DWORD(0xFFFF)
            return int(value.value) if get_affinity(hwnd, ctypes.byref(value)) else None

        baseline = gui_counts(api)
        knob = ov.KnobOverlay()
        try:
            self.assertTrue(knob.start(), knob.metrics()["last_error"])
            hwnd = knob.hwnd
            self.assertTrue(hwnd)
            self.assertFalse(api.u.IsWindowVisible(hwnd))
            caller = c.Win32CarouselBackend(api=api)
            before = read(hwnd)
            excluded_ok = caller.set_capture_exclusions((hwnd,), True)
            excluded = read(hwnd)
            cleared_ok = caller.set_capture_exclusions((hwnd,), False)
            cleared = read(hwnd)
            self.assertFalse(api.u.IsWindowVisible(hwnd))
        finally:
            self.assertTrue(knob.close())
        self.assertEqual(knob.hwnd, 0)
        self.assertEqual((before, excluded, cleared), (c.WDA_NONE, c.WDA_EXCLUDEFROMCAPTURE, c.WDA_NONE))
        self.assertTrue(excluded_ok)
        self.assertTrue(cleared_ok)
        self.assertEqual(settle_counts(api, baseline), baseline)

    def test_presenter_start_and_close_never_show_and_return_to_baseline(self):
        api = self.api
        baseline = gui_counts(api)
        presenter = c.CarouselPresenter(None, None, None)
        try:
            self.assertFalse(presenter.disabled, presenter.last_error)
            self.assertTrue(presenter.hwnd)
            self.assertFalse(api.u.IsWindowVisible(presenter.hwnd))
            self.assertIsNone(presenter.rect)
            presenter.set_background("none")
            presenter.set_icons({})
            presenter.set_labels({})
            presenter.hide()                   # nothing open: nothing happens
            time.sleep(0.1)
            self.assertFalse(api.u.IsWindowVisible(presenter.hwnd))
        finally:
            started = time.perf_counter()
            self.assertTrue(presenter.close())
            self.assertLess(time.perf_counter() - started, 1.5)
        self.assertEqual(settle_counts(api, baseline), baseline)

    def test_self_test_with_hidden_windows(self):
        """The frozen smoke report's carousel step (carousel.self_test), live half included."""
        report = c.self_test(hidden_windows=True)
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["windows"]["hidden"])
        self.assertTrue(report["windows"]["baseline"])


if __name__ == "__main__":
    unittest.main()
