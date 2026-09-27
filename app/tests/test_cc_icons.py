"""Windows application icons for targeted colour and the desktop mirror/picker.

Unit tests drive IconWorker and the fallback helpers with a fake API. The GDI
test uses real Win32 calls, but only on a hidden Tk window of this test process
and on this Python executable: no other application, device or network is used.
"""
from copy import deepcopy
from pathlib import Path
import ctypes as C
import gc
import sys
import threading
import time
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from control_center import windows as w
from control_center.artwork import dominant_rgb


def solid(color, size=48, alpha=255):
    return Image.new("RGBA", (size, size), tuple(color) + (alpha,))


def pixels(image):
    return [image.getpixel((x, y)) for y in range(image.height) for x in range(image.width)]


class FakeApi:
    """Records every call; handles map to prepared images."""

    def __init__(self, window=None, cls=None, files=None, images=None, gate=None):
        self.window, self.cls = dict(window or {}), dict(cls or {})
        self.files, self.images = dict(files or {}), dict(images or {})
        self.gate = gate
        self.calls, self.com = [], []

    def co_initialize(self):
        self.com.append(("init", threading.get_ident()))
        return True

    def co_uninitialize(self):
        self.com.append(("uninit", threading.get_ident()))

    def window_icon(self, hwnd, kind):
        self.calls.append(("window", hwnd, kind))
        if self.gate is not None:
            self.gate.wait(2)
        return self.window.get((hwnd, kind), 0)

    def class_icon(self, hwnd, index):
        self.calls.append(("class", hwnd, index))
        return self.cls.get((hwnd, index), 0)

    def file_icon(self, path):
        self.calls.append(("file", path))
        return self.files.get(path, 0)

    def icon_image(self, handle):
        self.calls.append(("image", handle))
        value = self.images.get(handle)
        if isinstance(value, Exception):
            raise value
        return value

    def destroy_icon(self, handle):
        self.calls.append(("destroy", handle))


class FallbackOrderTests(unittest.TestCase):
    H, EXE = 0x1234, r"C:\Apps\Example\example.exe"

    def test_full_order_ends_with_the_shell_icon_which_alone_is_destroyed(self):
        api = FakeApi(files={self.EXE: 900}, images={900: solid((0, 0, 255))})
        image = w.extract_icon(api, self.H, self.EXE)
        self.assertEqual(image.getpixel((0, 0)), (0, 0, 255, 255))
        self.assertEqual(api.calls, [
            ("window", self.H, w.ICON_BIG), ("window", self.H, w.ICON_SMALL2),
            ("class", self.H, w.GCLP_HICON), ("class", self.H, w.GCLP_HICONSM),
            ("file", self.EXE), ("image", 900), ("destroy", 900)])

    def test_window_icon_wins_and_is_never_destroyed(self):
        api = FakeApi(window={(self.H, w.ICON_SMALL2): 500}, images={500: solid((255, 0, 0))},
                      files={self.EXE: 900})
        self.assertIsNotNone(w.extract_icon(api, self.H, self.EXE))
        self.assertEqual(api.calls, [("window", self.H, w.ICON_BIG), ("window", self.H, w.ICON_SMALL2),
                                     ("image", 500)])

    def test_class_icons_are_never_destroyed(self):
        api = FakeApi(cls={(self.H, w.GCLP_HICONSM): 600}, images={600: solid((0, 255, 0))})
        self.assertIsNotNone(w.extract_icon(api, self.H, self.EXE))
        self.assertNotIn("destroy", [call[0] for call in api.calls])
        self.assertEqual(api.calls[-1], ("image", 600))

    def test_unconvertible_handles_fall_through_to_the_next_source(self):
        api = FakeApi(window={(self.H, w.ICON_BIG): 501}, cls={(self.H, w.GCLP_HICON): 601},
                      files={self.EXE: 901}, images={901: solid((9, 9, 200))})
        self.assertIsNotNone(w.extract_icon(api, self.H, self.EXE))
        self.assertEqual([c for c in api.calls if c[0] in ("image", "destroy")],
                         [("image", 501), ("image", 601), ("image", 901), ("destroy", 901)])

    def test_shell_icon_is_destroyed_even_when_conversion_fails(self):
        api = FakeApi(files={self.EXE: 902}, images={902: RuntimeError("bad icon")})
        with self.assertRaises(RuntimeError):
            w.fallback_icon_image(api, 0, self.EXE)
        self.assertEqual(api.calls[-1], ("destroy", 902))
        api = FakeApi(files={self.EXE: 903})  # converts to None
        self.assertIsNone(w.fallback_icon_image(api, 0, self.EXE))
        self.assertEqual(api.calls.count(("destroy", 903)), 1)

    def test_without_hwnd_only_the_shell_icon_is_tried(self):
        api = FakeApi()
        self.assertIsNone(w.extract_icon(api, 0, self.EXE))
        self.assertEqual(api.calls, [("file", self.EXE)])
        api = FakeApi()
        self.assertIsNone(w.extract_icon(api, 0, ""))
        self.assertEqual(api.calls, [])

    def test_uwp_frame_host_detection(self):
        self.assertTrue(w.is_uwp_host("ApplicationFrameHost"))
        self.assertTrue(w.is_uwp_host("x", r"C:\Windows\System32\ApplicationFrameHost.exe"))
        self.assertFalse(w.is_uwp_host("slack", r"C:\Apps\slack.exe"))
        self.assertFalse(w.is_uwp_host(None, None))


class IconInfoCleanupTests(unittest.TestCase):
    """icon_image always deletes both ICONINFO bitmaps and never destroys the icon."""

    def api(self, color=11, mask=12, ok=True):
        api = object.__new__(w.IconApi)
        api.u, api.g = Mock(), Mock()

        def get_icon_info(handle, ref):
            ref._obj.hbmColor, ref._obj.hbmMask = color, mask
            return ok
        api.u.GetIconInfo.side_effect = get_icon_info
        return api

    def test_both_bitmaps_deleted_when_conversion_raises_or_fails(self):
        for outcome in (RuntimeError("decode"), None):
            api = self.api()
            api._compose = Mock(side_effect=outcome) if isinstance(outcome, Exception) else Mock(return_value=None)
            if isinstance(outcome, Exception):
                with self.assertRaises(RuntimeError):
                    api.icon_image(77)
            else:
                self.assertIsNone(api.icon_image(77))
            self.assertEqual(sorted(call.args[0] for call in api.g.DeleteObject.call_args_list), [11, 12])
            api.u.DestroyIcon.assert_not_called()

    def test_monochrome_icon_without_colour_bitmap_deletes_its_mask(self):
        api = self.api(color=None, mask=12)
        api._compose = Mock(return_value=solid((1, 2, 3)))
        api.icon_image(77)
        api.g.DeleteObject.assert_called_once_with(12)

    def test_failed_get_icon_info_touches_nothing(self):
        api = self.api(ok=False)
        self.assertIsNone(api.icon_image(77))
        api.g.DeleteObject.assert_not_called()
        self.assertIsNone(api.icon_image(0))

    def compose_api(self, sizes, bits):
        api = object.__new__(w.IconApi)
        api._bitmap_size = lambda handle: sizes.get(handle)
        api._bits = lambda handle, width, height: bits.get(handle)
        return api

    def test_zero_alpha_colour_takes_alpha_from_mask(self):
        colour = bytes([10, 20, 30, 0, 40, 50, 60, 0])            # BGRA, alpha all zero
        mask = bytes([0, 0, 0, 0, 255, 255, 255, 0])              # opaque, transparent
        api = self.compose_api({1: (2, 1), 2: (2, 1)}, {1: colour, 2: mask})
        image = api._compose(1, 2)
        self.assertEqual(pixels(image), [(30, 20, 10, 255), (60, 50, 40, 0)])

    def test_real_alpha_is_kept_and_missing_mask_means_opaque(self):
        colour = bytes([10, 20, 30, 200, 40, 50, 60, 0])
        api = self.compose_api({1: (2, 1)}, {1: colour})
        self.assertEqual(pixels(api._compose(1, None)), [(30, 20, 10, 200), (60, 50, 40, 0)])
        api = self.compose_api({1: (2, 1)}, {1: bytes(8)})
        self.assertEqual([p[3] for p in pixels(api._compose(1, None))], [255, 255])

    def test_monochrome_icon_uses_and_mask_over_xor_image(self):
        bits = bytes([0, 0, 0, 0, 255, 255, 255, 0,               # AND row: opaque, transparent
                      255, 255, 255, 0, 0, 0, 0, 0])              # XOR row: white, black
        api = self.compose_api({2: (2, 2)}, {2: bits})
        self.assertEqual(pixels(api._compose(None, 2)), [(255, 255, 255, 255), (0, 0, 0, 0)])

    def test_oversized_bitmaps_are_rejected(self):
        api = self.compose_api({1: (600, 600)}, {})
        self.assertIsNone(api._compose(1, None))


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class SignatureTests(unittest.TestCase):
    def test_new_apis_use_pointer_sized_types(self):
        api = w.IconApi()
        send = api.u.SendMessageTimeoutW
        self.assertIs(send.restype, w.LPARAM)
        self.assertEqual(send.argtypes[:4], (w.HANDLE, w.UINT, w.WPARAM, w.LPARAM))
        self.assertIs(send.argtypes[-1]._type_, C.c_size_t)
        self.assertIs(api.get_class_long.restype, C.c_size_t)
        self.assertIs(api.s.SHGetFileInfoW.restype, C.c_size_t)
        self.assertIs(api.u.GetIconInfo.argtypes[0], C.c_void_p)
        self.assertIs(api.g.DeleteObject.argtypes[0], C.c_void_p)
        self.assertIs(api.o.CoInitializeEx.restype, w.LONG)
        if C.sizeof(C.c_void_p) == 8:
            self.assertEqual(api.get_class_long.__name__, "GetClassLongPtrW")
            self.assertEqual((C.sizeof(w.ICONINFO), C.sizeof(w.BITMAP), C.sizeof(w.SHFILEINFOW)), (32, 32, 696))
        self.assertEqual(C.sizeof(w.BITMAPINFOHEADER), 40)


class WorkerTests(unittest.TestCase):
    EXE, OTHER = r"C:\Apps\Example\example.exe", r"C:\Apps\Other\other.exe"

    def worker(self, api):
        worker = w.IconWorker(api_factory=lambda: api)
        self.addCleanup(worker.close, 2)
        return worker

    def collect(self, worker, count, timeout=3):
        found, until = [], time.monotonic() + timeout
        while len(found) < count and time.monotonic() < until:
            found.extend(worker.poll())
            time.sleep(.005)
        return found

    def test_results_follow_snapshot_order_with_32px_icons_and_accents(self):
        api = FakeApi(window={(1, w.ICON_BIG): 101}, files={self.EXE: 900},
                      images={101: solid((255, 0, 0), 48), 900: solid((0, 0, 200), 16)})
        items = [{"id": "a", "hwnd": 1, "pid": 10, "path": self.EXE, "app": "example", "title": "A"},
                 {"id": "b", "hwnd": 2, "pid": 11, "path": self.EXE, "app": "example", "title": "B"},
                 {"id": "u", "hwnd": 3, "pid": 12, "path": None, "app": "ApplicationFrameHost", "title": "U"},
                 {"id": "c", "hwnd": 4, "pid": 13, "path": None, "app": "Application", "title": "C"}]
        frozen = deepcopy(items)
        worker = self.worker(api)
        worker.request(items)
        results = self.collect(worker, 4)
        self.assertEqual(items, frozen)  # the snapshot is never reordered or mutated
        self.assertEqual([(i, a) for i, _, a in results], [("a", 0xFF0000), ("b", 0x0000FF), ("u", None), ("c", None)])
        for _, icon, _ in results[:2]:
            self.assertEqual((icon.size, icon.mode), ((32, 32), "RGBA"))
        self.assertIsNone(results[2][1])
        self.assertNotIn(3, [call[1] for call in api.calls if call[0] in ("window", "class")])  # UWP untouched

    def test_com_is_initialised_and_released_on_the_worker_thread(self):
        api = FakeApi()
        worker = w.IconWorker(api_factory=lambda: api)
        worker.request([{"id": "x", "hwnd": 0, "path": ""}])
        self.collect(worker, 1)
        worker.close(2)
        self.assertFalse(worker._thread.is_alive())
        self.assertEqual([kind for kind, _ in api.com], ["init", "uninit"])
        self.assertEqual(api.com[0][1], api.com[1][1])
        self.assertNotEqual(api.com[0][1], threading.get_ident())

    def test_exe_path_cache_persists_and_hwnd_cache_is_per_snapshot(self):
        api = FakeApi(window={(7, w.ICON_BIG): 700}, files={self.EXE: 900},
                      images={700: solid((0, 255, 0)), 900: solid((255, 0, 0))})
        worker = self.worker(api)
        worker.request([{"id": "1", "hwnd": 1, "path": self.EXE}, {"id": "2", "hwnd": 2, "path": self.EXE.upper()}])
        self.assertEqual([a for _, _, a in self.collect(worker, 2)], [0xFF0000, 0xFF0000])
        worker.request([{"id": "3", "hwnd": 3, "path": self.EXE}])
        self.assertEqual([a for _, _, a in self.collect(worker, 1)], [0xFF0000])
        self.assertEqual(api.calls.count(("file", self.EXE)), 1)
        worker.request([{"id": "g1", "hwnd": 7, "path": self.OTHER}, {"id": "g2", "hwnd": 7, "path": self.OTHER}])
        self.assertEqual([a for _, _, a in self.collect(worker, 2)], [0x00FF00, 0x00FF00])
        self.assertEqual(api.calls.count(("window", 7, w.ICON_BIG)), 1)
        worker.request([{"id": "g3", "hwnd": 7, "path": self.OTHER}])  # new snapshot: ask the window again
        self.collect(worker, 1)
        self.assertEqual(api.calls.count(("window", 7, w.ICON_BIG)), 2)

    def test_new_request_supersedes_unfinished_work(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        api = FakeApi(window={(1, w.ICON_BIG): 101, (9, w.ICON_BIG): 109},
                      images={101: solid((255, 0, 0)), 109: solid((0, 0, 255))}, gate=gate)
        worker = self.worker(api)
        worker.request([{"id": "old-1", "hwnd": 1}, {"id": "old-2", "hwnd": 2}])
        until = time.monotonic() + 2
        while not api.calls and time.monotonic() < until:
            time.sleep(.005)
        worker.request([{"id": "new", "hwnd": 9}])
        gate.set()
        self.assertEqual([(i, a) for i, _, a in self.collect(worker, 1)], [("new", 0x0000FF)])
        time.sleep(.05)
        self.assertEqual(worker.poll(), [])
        self.assertNotIn(("window", 2, w.ICON_BIG), api.calls)

    def test_api_failures_degrade_to_letter_tiles(self):
        def broken():
            raise OSError("no user32")
        worker = w.IconWorker(api_factory=broken)
        self.addCleanup(worker.close, 2)
        worker.request([{"id": "a", "hwnd": 1, "path": self.EXE}])
        self.assertEqual(self.collect(worker, 1), [("a", None, None)])
        api = FakeApi(window={(1, w.ICON_BIG): 5}, images={5: RuntimeError("GDI")})
        worker = self.worker(api)
        worker.request([{"id": "b", "hwnd": 1, "path": ""}])
        self.assertEqual(self.collect(worker, 1), [("b", None, None)])

    def test_close_is_final(self):
        api = FakeApi()
        worker = w.IconWorker(api_factory=lambda: api)
        worker.close(2)
        worker.request([{"id": "late", "hwnd": 1}])
        self.assertEqual(worker.poll(), [])
        self.assertFalse(worker._thread.is_alive())

    def test_icon_thumbnail_pads_non_square_icons(self):
        thumb = w.icon_thumbnail(Image.new("RGBA", (64, 32), (255, 0, 0, 255)))
        self.assertEqual(thumb.size, (32, 32))
        self.assertEqual(thumb.getpixel((0, 0))[3], 0)
        self.assertEqual(thumb.getpixel((16, 16)), (255, 0, 0, 255))


class ProcessPathTests(unittest.TestCase):
    """Both _process_info call sites: identity() and records()."""

    PATHS = {501: r"C:\Program Files\Slack\slack.exe", 502: r"C:\Windows\System32\ApplicationFrameHost.exe"}

    def native(self):
        native = object.__new__(w.NativeWindows)
        native.own_pid, native.generations = 1, {}
        native.u, native.k, native.d = Mock(), Mock(), Mock()
        native.get_long = Mock(return_value=0)
        pids = {11: 501, 12: 502, 13: 503}

        def pid_of(hwnd, ref):
            ref._obj.value = pids[int(hwnd)]
            return 1

        def image_name(process, flags, buffer, size):
            if process not in self.PATHS:
                return 0
            buffer.value = self.PATHS[process]
            return 1

        def text(hwnd, buffer, length):
            buffer.value = f"Window {hwnd}"
            return len(buffer.value)

        native.u.GetWindowThreadProcessId.side_effect = pid_of
        native.u.IsWindow.return_value = native.u.IsWindowVisible.return_value = True
        native.u.IsIconic.return_value = False
        native.u.GetWindow.return_value = 0
        native.u.GetWindowTextW.side_effect = text
        native.u.GetClassNameW.return_value = 0
        native.u.EnumWindows.side_effect = lambda proc, _: [proc(h, 0) for h in (11, 12, 13)] and 1
        native.d.DwmGetWindowAttribute.return_value = 0
        native.k.OpenProcess.side_effect = lambda access, inherit, pid: pid if pid != 503 else 0
        native.k.GetProcessTimes.return_value = 0
        native.k.QueryFullProcessImageNameW.side_effect = image_name
        return native

    def test_process_info_returns_the_full_image_path(self):
        native = self.native()
        self.assertEqual(native._process_info(501), (0, "slack", self.PATHS[501]))
        self.assertEqual(native._process_info(503), (0, "Application", ""))

    def test_records_keep_existing_fields_and_add_path(self):
        native = self.native()
        records = native.records()
        self.assertEqual([r["app"] for r in records], ["slack", "ApplicationFrameHost", "Application"])
        self.assertEqual([r["path"] for r in records], [self.PATHS[501], None, None])
        for record in records:
            for field in ("hwnd", "pid", "id", "title", "app", "visible", "cloaked", "exstyle",
                          "owner", "class_name", "minimized"):
                self.assertIn(field, record)
        self.assertEqual(native.identity(11)["id"], records[0]["id"])


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class GdiStabilityTests(unittest.TestCase):
    """Real extraction on a hidden window of this process must not leak handles."""

    @classmethod
    def setUpClass(cls):
        cls.user32 = C.WinDLL("user32", use_last_error=True)
        cls.kernel32 = C.WinDLL("kernel32", use_last_error=True)
        cls.user32.GetGuiResources.restype, cls.user32.GetGuiResources.argtypes = C.c_uint32, (C.c_void_p, C.c_uint32)
        cls.user32.GetDesktopWindow.restype, cls.user32.GetDesktopWindow.argtypes = C.c_void_p, ()
        cls.kernel32.GetCurrentProcess.restype, cls.kernel32.GetCurrentProcess.argtypes = C.c_void_p, ()
        cls.root, cls.photo = None, None
        try:
            import tkinter as tk
            cls.root = tk.Tk()
            cls.root.withdraw()
            cls.photo = tk.PhotoImage(master=cls.root, width=16, height=16)
            cls.photo.put("#5865F2", to=(0, 0, 16, 16))
            cls.root.iconphoto(False, cls.photo)  # WM_SETICON: a window-owned icon
            cls.root.update_idletasks()
            cls.hwnd = int(cls.root.wm_frame(), 16)
        except Exception:
            if cls.root is not None:
                cls.root.destroy()
            cls.root = None
            cls.hwnd = int(cls.user32.GetDesktopWindow() or 0)
        if not cls.hwnd:
            raise unittest.SkipTest("no top-level window available")

    @classmethod
    def tearDownClass(cls):
        if cls.root is not None:
            cls.root.destroy()

    def counts(self):
        process = self.kernel32.GetCurrentProcess()
        return self.user32.GetGuiResources(process, 0), self.user32.GetGuiResources(process, 1)  # GDI, USER

    def test_100_extractions_keep_gdi_and_user_object_counts_stable(self):
        api = w.IconApi()
        com = api.co_initialize()
        try:
            window_handle = api.window_icon(self.hwnd, w.ICON_BIG) if self.root is not None else 0
            for _ in range(3):  # warm shell caches and image lists before measuring
                w.extract_icon(api, self.hwnd, sys.executable)
                w.fallback_icon_image(api, 0, sys.executable)
            gc.collect()
            before = self.counts()
            for _ in range(100):
                image = w.extract_icon(api, self.hwnd, sys.executable)
                self.assertIsNotNone(image)
                shell = w.fallback_icon_image(api, 0, sys.executable)
                self.assertEqual(shell.mode, "RGBA")
            gc.collect()
            after = self.counts()
            if window_handle:
                # The window still owns a live icon: WM_GETICON results were never destroyed.
                self.assertEqual(api.window_icon(self.hwnd, w.ICON_BIG), window_handle)
                self.assertIsNotNone(api.icon_image(window_handle))
        finally:
            if com:
                api.co_uninitialize()
        self.assertLessEqual(after[0] - before[0], 4, f"GDI objects {before[0]} -> {after[0]}")
        self.assertLessEqual(after[1] - before[1], 4, f"USER objects {before[1]} -> {after[1]}")

    def test_worker_extracts_this_window_while_the_ui_thread_pumps(self):
        if self.root is None:
            self.skipTest("Tk is unavailable")
        worker = w.IconWorker()
        try:
            worker.request([{"id": "tk", "hwnd": self.hwnd, "path": sys.executable, "app": "python"}])
            found, until = [], time.monotonic() + 5
            while not found and time.monotonic() < until:
                self.root.update()  # answer the worker's cross-thread WM_GETICON
                found = worker.poll()
                time.sleep(.005)
        finally:
            worker.close(2)
        self.assertEqual(len(found), 1)
        item_id, icon, accent = found[0]
        self.assertEqual(item_id, "tk")
        self.assertEqual((icon.size, icon.mode), ((32, 32), "RGBA"))
        # The solid #5865F2 icon set through WM_SETICON, normalised to max channel 255.
        self.assertEqual(accent, dominant_rgb(Image.new("RGB", (16, 16), (0x58, 0x65, 0xF2))))
        self.assertEqual(accent, 0x5D6AFF)


if __name__ == "__main__":
    unittest.main()
