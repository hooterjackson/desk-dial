"""Carousel window facts (control_center.window_facts) against CAROUSEL.md sections 6 and 7.

Default suite: no window is created or shown and no other process is touched. Win32
entry points are replaced by a fake ``api``; COM interfaces are fake objects laid out
exactly like real ones (an object whose first field points at a vtable of ctypes
thunks), so the module's real vtable calls, argument marshalling and Release
discipline run against them. Only in-process GDI objects (a DIB section) are real.

Live probes (NANOD_FACTS_LIVE_TESTS=1, Windows only) are read-only: they query the
user's existing windows, displays and audio sessions through the real API, assert
shapes only, and never print or assert on a title, profile, monitor name, AUMID or
path (failure messages are generic).
"""
from collections import Counter
from pathlib import Path
import ctypes as C
import os
import struct
import sys
import tempfile
import time
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from control_center import window_facts as wf  # noqa: E402

WINDOWS = sys.platform == "win32"
X64 = C.sizeof(C.c_void_p) == 8
LIVE = WINDOWS and os.environ.get("NANOD_FACTS_LIVE_TESTS") == "1"
E_FAIL = -2147467259            # 0x80004005
E_NOINTERFACE = -2147467262     # 0x80004002


# ------------------------------------------------------------------ fakes
class FakeCom:
    """A COM-shaped object in process memory. ``methods`` maps a vtable slot to
    (prototype, python function(this, *args)); slots 0-2 are IUnknown. ``refs`` starts
    at 1 (the reference handed to the code under test) and must end at 0."""

    def __init__(self, methods=None, slots=20, qi=None):
        self.refs = 1
        self.errors = []
        self.calls = Counter()
        self._keep = []
        table = [0] * slots

        def guard(name, fn):
            def run(*args):
                self.calls[name] += 1
                try:
                    return fn(*args)
                except Exception as exc:          # never unwind into ctypes
                    self.errors.append(exc)
                    return E_FAIL
            return run

        def query(this, riid, out):
            target = qi(bytes(riid.contents)) if qi else None
            if target is None:
                out[0] = None
                return E_NOINTERFACE
            target.refs += 1
            out[0] = target.ptr
            return 0

        def add_ref(this):
            self.refs += 1
            return self.refs

        def release(this):
            self.refs -= 1
            return max(self.refs, 0)

        entries = {0: (wf._QUERY_INTERFACE, query), 1: (wf._RELEASE, add_ref), 2: (wf._RELEASE, release)}
        entries.update(methods or {})
        for slot, (prototype, fn) in entries.items():
            thunk = prototype(guard(f"slot{slot}", fn))
            self._keep.append(thunk)
            table[slot] = C.cast(thunk, C.c_void_p).value
        self.vtable = (C.c_void_p * slots)(*table)
        self.object = (C.c_void_p * 1)(C.addressof(self.vtable))
        self.ptr = C.addressof(self.object)

    def keep(self, value):
        self._keep.append(value)
        return value


class FakeApi:
    """Stands in for FactsApi. Declared names that are not overridden come from
    ``real`` (a FactsApi, for in-process GDI calls) or are None."""

    def __init__(self, real=None, **overrides):
        self._real = real
        self.calls = Counter()
        self.freed = []
        for name, fn in overrides.items():
            setattr(self, name, self._counted(name, fn))

    def _counted(self, name, fn):
        def run(*args):
            self.calls[name] += 1
            return fn(*args)
        return run

    def CoInitializeEx(self, _reserved, flags):
        self.calls["CoInitializeEx"] += 1
        return 1                                   # S_FALSE: already initialised, still balanced

    def CoUninitialize(self):
        self.calls["CoUninitialize"] += 1

    def PropVariantClear(self, value):
        self.calls["PropVariantClear"] += 1
        value._obj.vt = 0
        return 0

    def CoTaskMemFree(self, pointer):
        self.calls["CoTaskMemFree"] += 1
        self.freed.append(pointer)

    def GetDriveTypeW(self, root):
        self.calls["GetDriveTypeW"] += 1
        return 3                                   # DRIVE_FIXED

    def __getattr__(self, name):
        if name in wf.DECLARED_NAMES:
            return getattr(self._real, name) if self._real is not None else None
        raise AttributeError(name)


def out(arg, value):
    """Write through a byref() argument the way the callee would."""
    arg._obj.value = value


class FactsTestCase(unittest.TestCase):
    def setUp(self):
        wf.clear_caches()

    def tearDown(self):
        wf.clear_caches()

    def assertComBalanced(self, api, *objects):
        self.assertEqual(api.calls["CoInitializeEx"], api.calls["CoUninitialize"])
        for obj in objects:
            self.assertEqual(obj.errors, [])
            self.assertEqual(obj.refs, 0, "every interface handed out is released exactly once")


# ------------------------------------------------------------------ declarations
class Declarations(unittest.TestCase):
    @unittest.skipUnless(X64, "x64 layout")
    def test_structure_sizes_x64(self):
        for structure, size in wf.STRUCTURE_SIZES_X64.items():
            self.assertEqual(C.sizeof(structure), size, structure.__name__)

    @unittest.skipUnless(WINDOWS, "Windows only")
    def test_every_export_resolves_without_calls(self):
        api = wf.FactsApi()
        missing = [name for name in wf.DECLARED_NAMES if getattr(api, name) is None]
        self.assertEqual(missing, [])

    def test_never_logs_prints_or_shares_ctypes_windll(self):
        import ast
        tree = ast.parse(Path(wf.__file__).read_text(encoding="utf-8"))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        modules = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertNotIn("print", names)
        self.assertNotIn("logging", modules)
        self.assertNotIn("windll", attributes)

    def test_guids(self):
        self.assertEqual(bytes(wf.IID_IPropertyStore).hex(), "eb8e6d88f28c46448d02cdba1dbdcf99")
        self.assertEqual(wf.PKEY_AppUserModel_ID.pid, 5)
        self.assertEqual(wf.PKEY_AppUserModel_RelaunchDisplayNameResource.pid, 4)
        self.assertEqual(wf.PKEY_AppUserModel_RelaunchIconResource.pid, 3)


# ------------------------------------------------------------------ version strings
def version_api(strings, translations, ui=0x0409, size=4096, drive=3):
    """A fake version.dll whose values live inside the caller's block (as real ones do)."""
    layout = {}

    def size_of(flags, path, handle):
        return size

    def read(flags, path, _handle, length, block):
        cursor = 0
        table = struct.pack(f"<{2 * len(translations)}H", *[w for pair in translations for w in pair])
        items = [("\\VarFileInfo\\Translation", table, len(table))]
        for sub, text in strings.items():
            data = (text + "\x00").encode("utf-16-le")
            items.append((sub, data, len(text) + 1))
        for sub, data, count in items:
            C.memmove(C.addressof(block) + cursor, data, len(data))
            layout[sub] = (C.addressof(block) + cursor, count)
            cursor += len(data) + (-len(data)) % 4
        return 1

    def query(block, sub, pointer, length):
        if sub not in layout:
            return 0
        out(pointer, layout[sub][0])
        out(length, layout[sub][1])
        return 1

    return FakeApi(GetFileVersionInfoSizeExW=size_of, GetFileVersionInfoExW=read, VerQueryValueW=query,
                   GetUserDefaultUILanguage=lambda: ui, GetDriveTypeW=lambda root: drive)


class VersionStrings(FactsTestCase):
    def test_translation_order(self):
        pairs = [(0x0407, 0x04B0), (0x0409, 0x04B0), (0x0416, 0x04E4)]
        self.assertEqual(wf._translation_candidates(pairs, 0x0416), [
            (0x0416, 0x04E4), (0x0407, 0x04B0), (0x0409, 0x04B0), (0x0416, 0x04B0),
            (0x0409, 0x04E4), (0x0409, 0x0000), (0x0000, 0x04B0)])

    def test_same_primary_language_before_others(self):
        self.assertEqual(wf._translation_candidates([(0x0409, 0x04B0), (0x0816, 0x04B0)], 0x0416)[:2],
                         [(0x0816, 0x04B0), (0x0409, 0x04B0)])

    def test_no_translation_table(self):
        self.assertEqual(wf._translation_candidates([], 0)[:1], [(0x0409, 0x04B0)])

    def test_ui_language_first_each_key_independently(self):
        api = version_api({
            "\\StringFileInfo\\040704B0\\FileDescription": "Beschreibung",
            "\\StringFileInfo\\040704B0\\ProductName": "Produkt",
            "\\StringFileInfo\\040904B0\\FileDescription": "Description",
        }, [(0x0407, 0x04B0), (0x0409, 0x04B0)], ui=0x0409)
        self.assertEqual(wf.version_strings(r"C:\Apps\acme.exe", api=api),
                         {"FileDescription": "Description", "ProductName": "Produkt"})

    def test_fallback_translation_when_table_missing(self):
        api = version_api({"\\StringFileInfo\\040904E4\\FileDescription": "Acme"}, [], ui=0x0416)
        self.assertEqual(wf.version_strings(r"C:\Apps\acme.exe", api=api)["FileDescription"], "Acme")

    def test_cached_per_path_case_insensitive(self):
        api = version_api({"\\StringFileInfo\\040904B0\\FileDescription": "Acme"}, [(0x0409, 0x04B0)])
        first = wf.version_strings(r"C:\Apps\Acme.exe", api=api)
        first["FileDescription"] = "mutated by the caller"
        second = wf.version_strings(r"c:/apps/acme.EXE", api=api)
        self.assertEqual(second["FileDescription"], "Acme")
        self.assertEqual(api.calls["GetFileVersionInfoSizeExW"], 1)

    def test_network_and_relative_paths_never_read(self):
        api = version_api({}, [], drive=4)
        for path in (r"\\server\share\a.exe", r"\\?\UNC\server\share\a.exe", "relative.exe", r"Z:\a.exe",
                     "//server/share/a.exe", r"\\.\pipe\x"):
            self.assertEqual(wf.version_strings(path, api=api), {"FileDescription": "", "ProductName": ""})
        self.assertEqual(api.calls["GetFileVersionInfoSizeExW"], 0)

    def test_long_path_prefix_is_local(self):
        self.assertTrue(wf._readable_local_path(FakeApi(), r"\\?\C:\Apps\a.exe"))
        self.assertFalse(wf._readable_local_path(FakeApi(GetDriveTypeW=lambda root: 1), r"Q:\a.exe"))

    def test_value_outside_the_block_is_ignored(self):
        outside = C.create_unicode_buffer("Elsewhere")

        def query(block, sub, pointer, length):
            if sub.endswith("FileDescription"):
                out(pointer, C.addressof(outside))
                out(length, 10)
                return 1
            return 0

        api = FakeApi(GetFileVersionInfoSizeExW=lambda f, p, h: 64, GetFileVersionInfoExW=lambda *a: 1,
                      VerQueryValueW=query, GetUserDefaultUILanguage=lambda: 0x0409)
        self.assertEqual(wf.version_strings(r"C:\a.exe", api=api)["FileDescription"], "")

    def test_failures_never_raise(self):
        def boom(*args):
            raise OSError("version.dll failed")
        api = FakeApi(GetFileVersionInfoSizeExW=boom)
        self.assertEqual(wf.version_strings(r"C:\a.exe", api=api), {"FileDescription": "", "ProductName": ""})
        for path in (None, "", 5):
            self.assertEqual(wf.version_strings(path, api=api), {"FileDescription": "", "ProductName": ""})


# ------------------------------------------------------------------ property store
def property_store(values, fail=()):
    """values: {pid: (vt, text)} for PKEY_AppUserModel_* pids."""
    store = FakeCom()

    def get_value(this, key, variant):
        pid = key.contents.pid
        if pid in fail:
            return E_FAIL
        vt, text = values.get(pid, (0, None))
        variant.contents.vt = vt
        if text is not None:
            variant.contents.p = C.addressof(store.keep(C.create_unicode_buffer(text)))
        return 0

    store.__init__({wf.SLOT_PROPERTYSTORE_GETVALUE: (wf._PROPERTYSTORE_GETVALUE, get_value)})
    return store


def store_api(store, hr=0):
    def get_store(hwnd, riid, target):
        if hr == 0:
            assert bytes(riid._obj) == bytes(wf.IID_IPropertyStore)
            out(target, store.ptr)
        return hr
    return FakeApi(SHGetPropertyStoreForWindow=get_store)


class PropertyStore(FactsTestCase):
    def test_reads_the_three_keys_and_releases(self):
        store = property_store({5: (31, "Chrome.Profile7"), 4: (31, "Work - Chrome"),
                                3: (31, r"C:\Data\Profile\Google Profile.ico,0")})
        api = store_api(store)
        self.assertEqual(wf.window_property_store(0x10, api=api), {
            "aumid": "Chrome.Profile7", "relaunch_display_name": "Work - Chrome",
            "relaunch_icon": r"C:\Data\Profile\Google Profile.ico,0"})
        self.assertEqual(api.calls["PropVariantClear"], 3)
        self.assertEqual(store.calls[f"slot{wf.SLOT_PROPERTYSTORE_GETVALUE}"], 3)
        self.assertComBalanced(api, store)

    def test_strings_are_cleaned(self):
        store = property_store({4: (31, "Wo​rk‎  - \tChrome")})
        self.assertEqual(wf.window_property_store(0x10, api=store_api(store))["relaunch_display_name"],
                         "Work - Chrome")
        self.assertIsNone(wf._clean("​ ‎"))

    def test_indirect_display_name_dropped_and_bstr_read(self):
        store = property_store({5: (8, "App.Id"), 4: (31, "@{Package?ms-resource://x}")})
        result = wf.window_property_store(0x10, api=store_api(store))
        self.assertEqual((result["aumid"], result["relaunch_display_name"], result["relaunch_icon"]),
                         ("App.Id", None, None))
        self.assertEqual(store.refs, 0)

    def test_failed_and_non_string_values(self):
        store = property_store({5: (19, None), 3: (31, "x.ico")}, fail=(4,))
        api = store_api(store)
        result = wf.window_property_store(0x10, api=api)
        self.assertEqual(result, {"aumid": None, "relaunch_display_name": None, "relaunch_icon": "x.ico"})
        self.assertEqual(api.calls["PropVariantClear"], 2, "only successful GetValue calls are cleared")
        self.assertComBalanced(api, store)

    def test_store_unavailable(self):
        store = property_store({})
        api = store_api(store, hr=E_FAIL)
        self.assertEqual(wf.window_property_store(0x10, api=api),
                         {"aumid": None, "relaunch_display_name": None, "relaunch_icon": None})
        self.assertEqual(store.refs, 1, "nothing was handed out, nothing is released")
        self.assertEqual(api.calls["CoInitializeEx"], api.calls["CoUninitialize"])

    def test_no_window(self):
        api = store_api(property_store({}))
        wf.window_property_store(0, api=api)
        self.assertEqual(api.calls["SHGetPropertyStoreForWindow"], 0)


# ------------------------------------------------------------------ AUMIDs
def aumid_api(pids, aumids, classes=None, children=(), store=None, open_ok=True):
    """pids: hwnd -> pid; aumids: pid -> AUMID (or an int error); classes: hwnd -> class."""
    classes = classes or {}
    handles = {}

    def thread_pid(hwnd, pid):
        out(pid, pids.get(hwnd, 0))
        return 1

    def open_process(access, inherit, pid):
        assert access == wf.PROCESS_QUERY_LIMITED_INFORMATION
        if not open_ok:
            return None
        handles[1000 + pid] = pid
        return 1000 + pid

    def get_aumid(handle, length, buffer):
        value = aumids.get(handles[handle], 15703)            # APPMODEL_ERROR_NO_APPLICATION
        if isinstance(value, int):
            return value
        if len(value) + 1 > length._obj.value:
            length._obj.value = len(value) + 1
            return wf.ERROR_INSUFFICIENT_BUFFER
        buffer.value = value
        return 0

    def class_name(hwnd, buffer, size):
        buffer.value = classes.get(hwnd, "")
        return len(buffer.value)

    def enum_children(hwnd, callback, lparam):
        for child in children:
            if not callback(child, lparam):
                break
        return 1

    overrides = dict(GetWindowThreadProcessId=thread_pid, OpenProcess=open_process,
                     GetApplicationUserModelId=get_aumid, CloseHandle=lambda h: 1, GetClassNameW=class_name,
                     EnumChildWindows=enum_children)
    if store is not None:
        def get_store(hwnd, riid, target):
            out(target, store.ptr)
            return 0
        overrides["SHGetPropertyStoreForWindow"] = get_store
    return FakeApi(**overrides)


class Aumids(FactsTestCase):
    def test_packaged_process(self):
        api = aumid_api({0x10: 7}, {7: "OpenAI.Codex_x!App"})
        self.assertEqual(wf.process_aumid(0x10, api=api), "OpenAI.Codex_x!App")
        self.assertEqual(api.calls["OpenProcess"], api.calls["CloseHandle"])

    def test_long_aumid_retries_with_the_reported_length(self):
        long_id = "Family_" + "x" * 200 + "!App"
        api = aumid_api({0x10: 7}, {7: long_id})
        self.assertEqual(wf.process_aumid(0x10, api=api), long_id)
        self.assertEqual(api.calls["GetApplicationUserModelId"], 2)
        self.assertEqual(api.calls["CloseHandle"], 1)

    def test_unpackaged_window(self):
        api = aumid_api({0x10: 7}, {}, classes={0x10: "Chrome_WidgetWin_1"})
        self.assertIsNone(wf.process_aumid(0x10, api=api))
        self.assertEqual(api.calls["EnumChildWindows"], 0)

    def test_uwp_frame_uses_the_core_window_process(self):
        api = aumid_api({0x10: 7, 0x11: 7, 0x12: 9}, {9: "Microsoft.App_x!App"},
                        classes={0x10: "ApplicationFrameWindow", 0x11: "ApplicationFrameInputSinkWindow",
                                 0x12: "Windows.UI.Core.CoreWindow"}, children=(0x11, 0x12))
        self.assertEqual(wf.process_aumid(0x10, api=api), "Microsoft.App_x!App")
        self.assertEqual(api.calls["OpenProcess"], api.calls["CloseHandle"])

    def test_suspended_uwp_frame_uses_its_property_store(self):
        store = property_store({5: (31, "Microsoft.App_x!App")})
        api = aumid_api({0x10: 7}, {}, classes={0x10: "ApplicationFrameWindow"}, store=store)
        self.assertEqual(wf.process_aumid(0x10, api=api), "Microsoft.App_x!App")
        self.assertComBalanced(api, store)

    def test_frame_store_without_a_package_is_ignored(self):
        store = property_store({5: (31, "Chrome")})
        api = aumid_api({0x10: 7}, {}, classes={0x10: "ApplicationFrameWindow"}, store=store)
        self.assertIsNone(wf.process_aumid(0x10, api=api))

    def test_inaccessible_process(self):
        api = aumid_api({0x10: 7}, {7: "A_x!App"}, open_ok=False)
        self.assertIsNone(wf.process_aumid(0x10, api=api))
        self.assertIsNone(wf.process_aumid(0, api=api))


# ------------------------------------------------------------------ packaged apps
def shell_item_api(item, iid, hr=0, real=None, parsing=None):
    def create(name, bind, riid, target):
        if parsing is not None:
            parsing.append(name)
        assert bytes(riid._obj) == bytes(iid)
        if hr == 0:
            out(target, item.ptr)
        return hr
    return FakeApi(real=real, SHCreateItemFromParsingName=create)


def display_name_item(text, hr=0):
    item = FakeCom()
    holder = {}

    def get_display_name(this, sigdn, target):
        assert sigdn == wf.SIGDN_NORMALDISPLAY
        if hr:
            return hr
        holder["buffer"] = item.keep(C.create_unicode_buffer(text))
        target[0] = C.addressof(holder["buffer"])
        return 0

    item.__init__({wf.SLOT_SHELLITEM_GETDISPLAYNAME: (wf._SHELLITEM_GETDISPLAYNAME, get_display_name)})
    return item, holder


class PackageNames(FactsTestCase):
    AUMID = "OpenAI.Codex_2p2nqsd0c76g0!App"

    def test_display_name_frees_and_releases(self):
        item, holder = display_name_item("ChatGPT")
        parsing = []
        api = shell_item_api(item, wf.IID_IShellItem, parsing=parsing)
        self.assertEqual(wf.package_display_name(self.AUMID, api=api), "ChatGPT")
        self.assertEqual(parsing, ["shell:AppsFolder\\" + self.AUMID])
        self.assertEqual(api.freed, [C.addressof(holder["buffer"])])
        self.assertComBalanced(api, item)

    def test_cached_and_cached_only(self):
        self.assertIsNone(wf.package_display_name(self.AUMID, api=FakeApi(), cached_only=True))
        item, _ = display_name_item("ChatGPT")
        api = shell_item_api(item, wf.IID_IShellItem)
        wf.package_display_name(self.AUMID, api=api)
        self.assertEqual(wf.package_display_name(self.AUMID, api=api, cached_only=True), "ChatGPT")
        self.assertEqual(wf.package_display_name(self.AUMID, api=api), "ChatGPT")
        self.assertEqual(api.calls["SHCreateItemFromParsingName"], 1)

    def test_failures_are_cached_then_retried(self):
        now = [1000.0]
        clock, wf._clock = wf._clock, lambda: now[0]
        try:
            failing = shell_item_api(display_name_item("x")[0], wf.IID_IShellItem, hr=E_FAIL)
            self.assertIsNone(wf.package_display_name(self.AUMID, api=failing))
            now[0] += wf.FAILURE_TTL_SECONDS - 1
            self.assertIsNone(wf.package_display_name(self.AUMID, api=failing))
            self.assertIsNone(wf.package_display_name(self.AUMID, api=failing, cached_only=True))
            self.assertEqual(failing.calls["SHCreateItemFromParsingName"], 1, "a fresh failure is not retried")
            now[0] += 2                                            # the failure has expired
            self.assertIsNone(wf.package_display_name(self.AUMID, api=FakeApi(), cached_only=True),
                              "cached_only never calls COM, even for an expired failure")
            item, _ = display_name_item("ChatGPT")
            working = shell_item_api(item, wf.IID_IShellItem)
            self.assertEqual(wf.package_display_name(self.AUMID, api=working), "ChatGPT")
            now[0] += 10 * wf.FAILURE_TTL_SECONDS                  # answers never expire
            self.assertEqual(wf.package_display_name(self.AUMID, api=working), "ChatGPT")
            self.assertEqual(working.calls["SHCreateItemFromParsingName"], 1)
            self.assertComBalanced(working, item)
        finally:
            wf._clock = clock

    def test_get_display_name_failure_releases(self):
        item, _ = display_name_item("x", hr=E_FAIL)
        api = shell_item_api(item, wf.IID_IShellItem)
        self.assertIsNone(wf.package_display_name(self.AUMID, api=api))
        self.assertEqual(api.freed, [])
        self.assertComBalanced(api, item)

    def test_echoed_parsing_name_rejected(self):
        item, _ = display_name_item(self.AUMID)
        self.assertIsNone(wf.package_display_name(self.AUMID, api=shell_item_api(item, wf.IID_IShellItem)))

    def test_invalid_aumids(self):
        api = FakeApi()
        for aumid in (None, "", "  ", "a\x00b", 5, "x" * 600):
            self.assertIsNone(wf.package_display_name(aumid, api=api))
        self.assertEqual(api.calls["SHCreateItemFromParsingName"], 0)


@unittest.skipUnless(WINDOWS, "in-process GDI objects")
class PackageLogos(FactsTestCase):
    AUMID = "Microsoft.App_x!App"

    def setUp(self):
        super().setUp()
        self.real = wf.FactsApi()
        gdi, user, kernel = (C.WinDLL(n, use_last_error=True) for n in ("gdi32", "user32", "kernel32"))
        self.create_dib = gdi.CreateDIBSection
        self.create_dib.restype = wf.HANDLE
        self.create_dib.argtypes = (wf.HANDLE, C.POINTER(wf.BITMAPINFO), wf.UINT, C.POINTER(C.c_void_p),
                                    wf.HANDLE, wf.DWORD)
        self.gui_resources = user.GetGuiResources
        self.gui_resources.restype, self.gui_resources.argtypes = wf.DWORD, (wf.HANDLE, wf.DWORD)
        kernel.GetCurrentProcess.restype = wf.HANDLE
        self.process = kernel.GetCurrentProcess()

    def gdi_objects(self):
        return self.gui_resources(self.process, 0)

    def dib(self, size, bgra):
        """A top-down 32bpp DIB section filled with one (B, G, R, A) pixel, as GetImage's
        icon-only bitmap carries it: straight (not premultiplied) alpha."""
        info = wf.BITMAPINFO()
        info.bmiHeader.biSize = C.sizeof(wf.BITMAPINFOHEADER)
        info.bmiHeader.biWidth, info.bmiHeader.biHeight = size, -size
        info.bmiHeader.biPlanes, info.bmiHeader.biBitCount = 1, 32
        bits = C.c_void_p()
        bitmap = self.create_dib(None, C.byref(info), 0, C.byref(bits), None, 0)
        self.assertTrue(bitmap)
        C.memmove(bits.value, bytes(bgra) * size * size, size * size * 4)
        return bitmap

    def factory(self, pixel, size=64, hr=0):
        item = FakeCom()
        seen = {}

        def get_image(this, requested, flags, target):
            seen["size"], seen["flags"] = (requested.cx, requested.cy), flags
            if hr:
                return hr
            target[0] = self.dib(size, pixel)
            return 0

        item.__init__({wf.SLOT_IMAGEFACTORY_GETIMAGE: (wf._IMAGEFACTORY_GETIMAGE, get_image)})
        return item, seen

    def test_logo_keeps_straight_alpha_and_is_freed(self):
        baseline = self.gdi_objects()
        # Colour channels above the alpha: only valid as straight alpha. An un-premultiply
        # would clip G to 255 (the bright fringe the shell logos showed).
        item, seen = self.factory((0, 200, 255, 128), size=128)   # B, G, R, A
        api = shell_item_api(item, wf.IID_IShellItemImageFactory, real=self.real)
        deleted = []
        api.DeleteObject = lambda h: (deleted.append(h), self.real.DeleteObject(h))[1]
        logo = wf.package_logo(self.AUMID, 128, api=api)
        self.assertEqual((logo.size, logo.mode), ((128, 128), "RGBA"))
        self.assertEqual(logo.getpixel((64, 64)), (255, 200, 0, 128))
        self.assertEqual(seen, {"size": (128, 128), "flags": wf.SIIGBF_ICONONLY | wf.SIIGBF_BIGGERSIZEOK})
        self.assertEqual(len(deleted), 1)
        self.assertEqual(self.gdi_objects(), baseline, "the HBITMAP and the DC are freed")
        self.assertComBalanced(api, item)

    def test_bigger_logo_is_resampled_without_brightening(self):
        item, _ = self.factory((40, 80, 120, 96), size=64)     # dark straight-alpha edge colour
        api = shell_item_api(item, wf.IID_IShellItemImageFactory, real=self.real)
        r, g, b, a = wf.package_logo(self.AUMID, 32, api=api).getpixel((16, 16))
        self.assertEqual(a, 96)
        for got, want in ((r, 120), (g, 80), (b, 40)):
            self.assertLessEqual(abs(got - want), 2, "LANCZOS keeps a flat straight-alpha colour")

    def test_logo_failures_expire(self):
        now = [50.0]
        clock, wf._clock = wf._clock, lambda: now[0]
        try:
            failed, _ = self.factory((0, 0, 0, 255), hr=E_FAIL)
            api = shell_item_api(failed, wf.IID_IShellItemImageFactory, real=self.real)
            self.assertIsNone(wf.package_logo(self.AUMID, 64, api=api))
            now[0] += wf.FAILURE_TTL_SECONDS / 2
            self.assertIsNone(wf.package_logo(self.AUMID, 64, api=api))
            self.assertEqual(api.calls["SHCreateItemFromParsingName"], 1)
            now[0] += wf.FAILURE_TTL_SECONDS
            item, _ = self.factory((0, 0, 200, 255))
            working = shell_item_api(item, wf.IID_IShellItemImageFactory, real=self.real)
            self.assertIsNotNone(wf.package_logo(self.AUMID, 64, api=working), "retried after the TTL")
            self.assertComBalanced(api, failed)
            self.assertComBalanced(working, item)
        finally:
            wf._clock = clock

    def test_logo_cached_as_copies(self):
        item, _ = self.factory((0, 0, 200, 255))
        api = shell_item_api(item, wf.IID_IShellItemImageFactory, real=self.real)
        first = wf.package_logo(self.AUMID, 32, api=api)
        first.putpixel((0, 0), (1, 2, 3, 4))
        second = wf.package_logo(self.AUMID, 32, api=api)
        self.assertNotEqual(second.getpixel((0, 0)), (1, 2, 3, 4))
        self.assertEqual(api.calls["SHCreateItemFromParsingName"], 1)

    def test_transparent_or_failed_logo_is_none(self):
        item, _ = self.factory((0, 0, 0, 0))
        api = shell_item_api(item, wf.IID_IShellItemImageFactory, real=self.real)
        self.assertIsNone(wf.package_logo(self.AUMID, 64, api=api))    # an all-zero bitmap is empty
        self.assertComBalanced(api, item)
        failed, _ = self.factory((0, 0, 0, 255), hr=E_FAIL)
        api = shell_item_api(failed, wf.IID_IShellItemImageFactory, real=self.real)
        self.assertIsNone(wf.package_logo("Other_x!App", 64, api=api))
        self.assertComBalanced(api, failed)


# ------------------------------------------------------------------ relaunch icons
class RelaunchIcons(FactsTestCase):
    def test_parse_resource(self):
        parse = wf._parse_icon_resource
        self.assertEqual(parse(r"C:\a\Google Profile.ico,0"), (r"C:\a\Google Profile.ico", 0))
        self.assertEqual(parse(r'"C:\a b\app.exe", -101'), (r"C:\a b\app.exe", -101))
        self.assertEqual(parse(r"C:\a\x.ico"), (r"C:\a\x.ico", 0))
        self.assertEqual(parse(r"C:\a,b\x.dll,3"), (r"C:\a,b\x.dll", 3))
        self.assertEqual(parse(r"%WINDIR%\x.dll,2")[0], os.path.expandvars(r"%WINDIR%\x.dll"))
        for bad in (None, "", "   ", "@{Package?x}", 5, ",3"):
            self.assertIsNone(parse(bad))

    def write_ico(self, folder):
        colours = {16: (9, 9, 9), 32: (8, 8, 8), 64: (0, 255, 0), 128: (0, 0, 255), 256: (255, 0, 0)}
        frames = [Image.new("RGBA", (s, s), c + (255,)) for s, c in colours.items()]
        path = os.path.join(folder, "Profile Icon.ico")
        frames[-1].save(path, sizes=[(s, s) for s in colours], append_images=frames[:-1])
        return path

    def test_best_ico_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write_ico(folder)
            api = FakeApi()
            self.assertEqual(wf.relaunch_icon(path + ",0", 128, api=api).getpixel((64, 64))[:3], (0, 0, 255))
            self.assertEqual(wf.relaunch_icon(path, 100, api=api).getpixel((50, 50))[:3], (0, 0, 255))
            icon = wf.relaunch_icon(path, 200, api=api)
            self.assertEqual((icon.size, icon.getpixel((100, 100))[:3]), ((200, 200), (255, 0, 0)))

    def test_cache_follows_the_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write_ico(folder)
            reads = []
            original = wf._ico_image
            wf._ico_image = lambda p, px: (reads.append(px), original(p, px))[1]
            try:
                wf.relaunch_icon(path, 64, api=FakeApi())
                wf.relaunch_icon(path, 64, api=FakeApi())
                stamp = os.stat(path).st_mtime_ns + 5_000_000_000
                os.utime(path, ns=(stamp, stamp))
                wf.relaunch_icon(path, 64, api=FakeApi())
            finally:
                wf._ico_image = original
            self.assertEqual(reads, [64, 64])

    def test_refused_paths(self):
        api = FakeApi(GetDriveTypeW=lambda root: 4)
        for resource in (r"\\server\share\x.ico", r"Z:\x.ico", "x.ico", r"C:\definitely\missing\x.ico"):
            self.assertIsNone(wf.relaunch_icon(resource, api=api))

    def test_module_icons_are_destroyed(self):
        destroyed = []

        def extract(path, index, flags, large, small, sizes):
            self.assertEqual((index, sizes & 0xFFFF, sizes >> 16), (-7, 96, 16))
            out(large, 0x111)
            out(small, 0x222)
            return 0

        with tempfile.TemporaryDirectory() as folder:
            module = os.path.join(folder, "app.dll")
            with open(module, "wb") as handle:
                handle.write(b"MZ" + b"\0" * 64)
            api = FakeApi(SHDefExtractIconW=extract, DestroyIcon=lambda h: destroyed.append(h) or 1,
                          GetIconInfo=lambda h, info: 0)
            self.assertIsNone(wf.relaunch_icon(module + ",-7", 96, api=api))
        self.assertEqual(sorted(destroyed), [0x111, 0x222])


# ------------------------------------------------------------------ monitors
class MonitorNames(FactsTestCase):
    def test_unique_and_nameless(self):
        names = wf._name_monitors([("\\\\.\\DISPLAY1", "Model A", 10, (0, 0)),
                                   ("\\\\.\\display2", "", 0x80000000, (100, 0)),
                                   ("\\\\.\\DISPLAY3", " ", 5, (200, 0))])
        self.assertEqual(names, {"\\\\.\\DISPLAY1": "Model A", "\\\\.\\DISPLAY2": "Built-in display",
                                 "\\\\.\\DISPLAY3": "Display"})

    def test_shared_model_gets_positions(self):
        two = wf._name_monitors([("A", "Model B", 10, (1920, 0)), ("B", "Model B", 10, (0, 0))])
        self.assertEqual(two, {"A": "Model B (Right)", "B": "Model B (Left)"})
        three = wf._name_monitors([("A", "M", 10, (0, 0)), ("B", "M", 10, (-1920, 0)), ("C", "M", 10, (1920, 0))])
        self.assertEqual(three, {"A": "M (Middle)", "B": "M (Left)", "C": "M (Right)"})
        stacked = wf._name_monitors([("A", "M", 10, (0, 1080)), ("B", "M", 10, (0, 0))])
        self.assertEqual(stacked, {"A": "M (Bottom)", "B": "M (Top)"})
        four = wf._name_monitors([(k, "M", 10, (i * 10, 0)) for i, k in enumerate("DCBA")])
        self.assertEqual(four, {"D": "M (1)", "C": "M (2)", "B": "M (3)", "A": "M (4)"})

    def test_clone_mode_keeps_the_first_target(self):
        self.assertEqual(wf._name_monitors([("A", "First", 10, None), ("A", "Second", 10, None)]), {"A": "First"})

    def display_api(self, device="\\\\.\\DISPLAY2", insufficient_once=False):
        state = {"insufficient": insufficient_once}
        monitors = [("\\\\.\\DISPLAY1", "Model A", 10, (0, 0)), ("\\\\.\\DISPLAY2", "Model B", 10, (2560, 0))]

        def sizes(flags, paths, modes):
            self.assertEqual(flags, wf.QDC_ONLY_ACTIVE_PATHS)
            out(paths, len(monitors))
            out(modes, len(monitors))
            return 0

        def query(flags, count, paths, mode_count, modes, topology):
            if state["insufficient"]:
                state["insufficient"] = False
                return wf.ERROR_INSUFFICIENT_BUFFER
            for i, (_gdi, _name, _tech, (x, y)) in enumerate(monitors):
                paths[i].sourceInfo.id, paths[i].sourceInfo.modeInfoIdx = i, i
                paths[i].targetInfo.id = 100 + i
                modes[i].infoType = wf.DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE
                raw = struct.pack("<IIIii", 2560, 1440, 4, x, y)
                C.memmove(C.addressof(modes[i].mode), raw, len(raw))
            return 0

        def device_info(request):
            packet = request._obj
            if packet.header.type == wf.DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME:
                self.assertEqual(packet.header.size, C.sizeof(wf.DISPLAYCONFIG_SOURCE_DEVICE_NAME))
                packet.viewGdiDeviceName = monitors[packet.header.id][0]
            else:
                self.assertEqual(packet.header.size, C.sizeof(wf.DISPLAYCONFIG_TARGET_DEVICE_NAME))
                packet.monitorFriendlyDeviceName = monitors[packet.header.id - 100][1]
                packet.outputTechnology = monitors[packet.header.id - 100][2]
            return 0

        def monitor_info(monitor, info):
            self.assertEqual(info._obj.cbSize, C.sizeof(wf.MONITORINFOEXW))
            info._obj.szDevice = device
            return 1

        return FakeApi(GetDisplayConfigBufferSizes=sizes, QueryDisplayConfig=query,
                       DisplayConfigGetDeviceInfo=device_info, MonitorFromWindow=lambda h, f: 0x55,
                       GetMonitorInfoW=monitor_info)

    def test_friendly_name_through_display_config(self):
        api = self.display_api(insufficient_once=True)
        self.assertEqual(wf.monitor_friendly_name(0x10, api=api), "Model B")
        self.assertEqual(wf.monitor_friendly_name(0x11, api=api), "Model B")
        self.assertEqual(api.calls["QueryDisplayConfig"], 2, "one retry, then the 2 s cache")

    def test_unknown_device_and_no_window(self):
        api = self.display_api(device="\\\\.\\DISPLAY9")
        self.assertIsNone(wf.monitor_friendly_name(0x10, api=api))
        self.assertIsNone(wf.monitor_friendly_name(0, api=api))


# ------------------------------------------------------------------ Core Audio
class AudioGraph:
    """enumerator -> endpoint collection -> devices -> session managers -> sessions."""

    def __init__(self, devices):
        self.objects, self.flows = [], []
        self.devices = [self.device(sessions) for sessions in devices]
        collection = self.com({
            wf.SLOT_COLLECTION_GETCOUNT: (wf._COLLECTION_GETCOUNT, self._count(len(self.devices))),
            wf.SLOT_COLLECTION_ITEM: (wf._COLLECTION_ITEM, self._hand_out(self.devices)),
        })

        def enum_endpoints(this, flow, mask, target):
            self.flows.append((flow, mask))
            target[0] = collection.ptr
            return 0

        self.enumerator = self.com({wf.SLOT_ENUMERATOR_ENUMAUDIOENDPOINTS: (wf._ENUMAUDIOENDPOINTS, enum_endpoints)})

    def com(self, methods=None, qi=None):
        obj = FakeCom(methods, qi=qi)
        self.objects.append(obj)
        return obj

    @staticmethod
    def _count(n):
        def count(this, target):
            target[0] = n
            return 0
        return count

    @staticmethod
    def _hand_out(objects):
        def item(this, index, target):
            target[0] = objects[index].ptr
            return 0
        return item

    def session(self, pid, state):
        holder = {}

        def get_state(this, target):
            target[0] = state
            return 0

        def get_pid(this, target):
            target[0] = pid
            return 0

        def qi(iid):
            return holder["self"] if iid == bytes(wf.IID_IAudioSessionControl2) else None

        obj = self.com({wf.SLOT_SESSIONCONTROL_GETSTATE: (wf._SESSIONCONTROL_GETSTATE, get_state),
                        wf.SLOT_SESSIONCONTROL2_GETPROCESSID: (wf._SESSIONCONTROL2_GETPROCESSID, get_pid)}, qi=qi)
        holder["self"] = obj
        return obj

    def device(self, sessions):
        controls = [self.session(pid, state) for pid, state in sessions]
        enumerator = self.com({
            wf.SLOT_SESSIONENUM_GETCOUNT: (wf._SESSIONENUM_GETCOUNT, self._count(len(controls))),
            wf.SLOT_SESSIONENUM_GETSESSION: (wf._SESSIONENUM_GETSESSION, self._hand_out(controls)),
        })

        def get_enumerator(this, target):
            target[0] = enumerator.ptr
            return 0

        manager = self.com({wf.SLOT_MANAGER2_GETSESSIONENUMERATOR: (wf._GETSESSIONENUMERATOR, get_enumerator)})

        def activate(this, iid, context, params, target):
            assert bytes(iid.contents) == bytes(wf.IID_IAudioSessionManager2)
            target[0] = manager.ptr
            return 0

        return self.com({wf.SLOT_DEVICE_ACTIVATE: (wf._DEVICE_ACTIVATE, activate)})


def audio_api(graph, processes, create_hr=0):
    snapshot = {"handle": 0x77, "closed": 0, "cursor": 0}

    def create(clsid, outer, context, iid, target):
        assert bytes(clsid._obj) == bytes(wf.CLSID_MMDeviceEnumerator)
        assert bytes(iid._obj) == bytes(wf.IID_IMMDeviceEnumerator)
        if create_hr:
            return create_hr
        out(target, graph.enumerator.ptr)
        return 0

    def fill(entry):
        if snapshot["cursor"] >= len(processes):
            return 0
        pid, parent, exe = processes[snapshot["cursor"]]
        snapshot["cursor"] += 1
        entry._obj.th32ProcessID, entry._obj.th32ParentProcessID, entry._obj.szExeFile = pid, parent, exe
        return 1

    def first(handle, entry):
        assert entry._obj.dwSize == C.sizeof(wf.PROCESSENTRY32W)
        snapshot["cursor"] = 0
        return fill(entry)

    def close(handle):
        snapshot["closed"] += 1
        return 1

    api = FakeApi(CoCreateInstance=create, CreateToolhelp32Snapshot=lambda flags, pid: snapshot["handle"],
                  Process32FirstW=first, Process32NextW=lambda h, e: fill(e), CloseHandle=close)
    return api, snapshot


class AudiblePids(FactsTestCase):
    PROCESSES = [(1, 0, "explorer.exe"), (5, 1, "chrome.exe"), (10, 5, "chrome.exe"), (11, 5, "chrome.exe"),
                 (40, 1, "Teams.exe"), (30, 1, "spotify.exe")]

    def test_active_sessions_on_every_endpoint_mapped_to_browser(self):
        graph = AudioGraph([[(10, 1), (30, 0)], [(40, 1), (0, 1)]])
        api, snapshot = audio_api(graph, self.PROCESSES)
        self.assertEqual(wf.audible_pids(api=api), {10, 5, 40})
        self.assertEqual(graph.flows, [(wf.E_DATAFLOW_ALL, wf.DEVICE_STATE_ACTIVE)])
        self.assertEqual(snapshot["closed"], 1)
        self.assertComBalanced(api, *graph.objects)

    def test_no_active_session_skips_toolhelp(self):
        graph = AudioGraph([[(10, 0)]])
        api, _ = audio_api(graph, self.PROCESSES)
        self.assertEqual(wf.audible_pids(api=api), set())
        self.assertEqual(api.calls["CreateToolhelp32Snapshot"], 0)
        self.assertComBalanced(api, *graph.objects)

    def test_enumerator_unavailable(self):
        graph = AudioGraph([])
        api, _ = audio_api(graph, [], create_hr=E_FAIL)
        self.assertEqual(wf.audible_pids(api=api), set())
        self.assertEqual(api.calls["CoInitializeEx"], api.calls["CoUninitialize"])

    def test_parent_walk(self):
        table = {1: (0, "explorer.exe"), 5: (1, "chrome.exe"), 10: (5, "chrome.exe"), 12: (10, "chrome.exe"),
                 7: (8, "a.exe"), 8: (7, "a.exe"), 20: (99, "b.exe")}
        walk = wf._with_same_exe_ancestors
        self.assertEqual(walk({12}, table), {12, 10, 5})
        self.assertEqual(walk({7}, table), {7, 8}, "a parent cycle stops")
        self.assertEqual(walk({20, 0, 55}, table), {20, 55}, "unknown parents and pid 0")


# ------------------------------------------------------------------ letter tiles
class LetterTiles(FactsTestCase):
    def test_every_colour_passes_contrast(self):
        names = list(wf.BRAND_TILE_COLOURS) + [f"App {i}" for i in range(40)]
        for name in names:
            self.assertGreaterEqual(wf.white_contrast(wf.tile_colour(name)), wf.MIN_TILE_CONTRAST, name)

    def test_brand_colours_darkened_only_when_needed(self):
        self.assertEqual(wf.tile_colour("Steam"), (0x1B, 0x28, 0x38))
        self.assertNotEqual(wf.tile_colour("File Explorer"), (0xE8, 0xB6, 0x4A))
        self.assertLess(wf.white_contrast((0xE8, 0xB6, 0x4A)), 3.0)

    def test_crc32_palette_is_deterministic(self):
        expected = wf.TILE_PALETTE[zlib.crc32(b"acme notes") % len(wf.TILE_PALETTE)]
        rgb = ((expected >> 16) & 255, (expected >> 8) & 255, expected & 255)
        while wf.white_contrast(rgb) < 3.0:
            rgb = tuple(int(c * 0.92) for c in rgb)
        self.assertEqual(wf.tile_colour("Acme Notes"), rgb)
        self.assertEqual(wf.tile_colour("  ACME   NOTES\u2122 "), rgb)

    def test_letter_choice(self):
        cases = {"7-Zip": "7", "(beta) Tool": "B", " \u00e9lan": "\u00c9", "\u00df": "S", "": "",
                 "\u2026": "", "\U0001F3B5 Music": "M", "\u5fae\u4fe1": "\u5fae", None: ""}
        for name, letter in cases.items():
            self.assertEqual(wf.tile_letter(name), letter, repr(name))

    def white_box(self, tile):
        """Bounding box of the near-white (letter) pixels: all three channels bright."""
        from PIL import ImageChops
        red, green, blue = tile.convert("RGB").split()
        darkest = ImageChops.darker(ImageChops.darker(red, green), blue)
        return darkest.point(lambda v: 255 if v > 200 else 0).getbbox()

    def test_tile_shape_colour_and_centred_letter(self):
        tile = wf.letter_tile("Hub", 128)
        self.assertEqual((tile.size, tile.mode), ((128, 128), "RGBA"))
        self.assertEqual(tile.getpixel((0, 0)), wf.tile_colour("Hub") + (255,), "square corners by default")
        box = self.white_box(tile)
        self.assertIsNotNone(box)
        self.assertLessEqual(abs((box[0] + box[2]) / 2 - 64), 2)
        self.assertLessEqual(abs((box[1] + box[3]) / 2 - 64), 4)
        size = 128 * 17 / 32
        self.assertTrue(0.6 * size <= box[3] - box[1] <= 0.8 * size, "a cap height of a 17/32 font")

    @staticmethod
    def white_pixels(image):
        """Near-white (letter) pixels: all three channels above 200."""
        return sum(1 for r, g, b in image.convert("RGB").getdata() if min(r, g, b) > 200)

    def archivo_reference(self, letter, weight, px=128):
        """The letter drawn independently of window_facts: Archivo at [weight, 100]."""
        from PIL import Image, ImageDraw, ImageFont
        font = ImageFont.truetype(str(wf.ARCHIVO), px * 17 / 32, layout_engine=ImageFont.Layout.BASIC)
        font.set_variation_by_axes([weight, 100])
        image = Image.new("RGB", (px, px), wf.tile_colour("Hub"))
        ImageDraw.Draw(image).text((px / 2, px / 2), letter, font=font, fill=(255, 255, 255), anchor="mm")
        return self.white_pixels(image)

    def test_letter_is_archivo_wght_700(self):
        """Section 7: Archivo wght 700. Weight changes ink, not the box or cap height, so
        compare the letter's ink with Archivo 'H' drawn at 700 and at 400."""
        tile = self.white_pixels(wf.letter_tile("Hub", 128))
        bold, regular = self.archivo_reference("H", 700), self.archivo_reference("H", 400)
        self.assertGreater(bold - regular, 0.2 * bold, "the reference weights are distinguishable")
        self.assertLessEqual(abs(tile - bold), 0.05 * bold, (tile, bold, regular))
        self.assertGreater(tile, (bold + regular) / 2, (tile, bold, regular))

    def test_radius(self):
        tile = wf.letter_tile("Hub", 64, radius=16)
        self.assertEqual(tile.getpixel((0, 0))[3], 0)
        self.assertEqual(tile.getpixel((32, 2))[3], 255)

    def test_cached_copies(self):
        first = wf.letter_tile("Acme", 32)
        first.putpixel((0, 0), (1, 2, 3, 4))
        self.assertNotEqual(wf.letter_tile("Acme", 32).getpixel((0, 0)), (1, 2, 3, 4))

    def test_font_coverage(self):
        self.assertTrue(wf.font_covers(wf.ARCHIVO, "A"))
        self.assertFalse(wf.font_covers(wf.ARCHIVO, 0x1F600))
        self.assertFalse(wf.font_covers(Path("missing.ttf"), "A"))

    @unittest.skipUnless((wf.SYSTEM_FONT_DIR / "segoeuib.ttf").is_file(), "Segoe UI Bold")
    def test_letters_archivo_lacks_use_a_fallback(self):
        self.assertFalse(wf.font_covers(wf.ARCHIVO, "\u0422"))
        self.assertTrue(wf.font_covers(wf.SYSTEM_FONT_DIR / "segoeuib.ttf", "\u0422"))
        self.assertIsNotNone(self.white_box(wf.letter_tile("\u0422\u0435\u043b\u0435\u0433\u0440\u0430\u043c", 64)))

    @unittest.skipUnless((wf.SYSTEM_FONT_DIR / "segoeuib.ttf").is_file(), "Segoe UI Bold")
    def test_fallback_letter_keeps_archivos_baseline(self):
        latin = self.white_box(wf.letter_tile("Hub", 128))
        cyrillic = self.white_box(wf.letter_tile("Нора", 128))   # Cyrillic En
        self.assertLessEqual(abs(latin[3] - cyrillic[3]), 1)

    @unittest.skipUnless((wf.SYSTEM_FONT_DIR / "msyhbd.ttc").is_file(), "Microsoft YaHei Bold")
    def test_cjk_letter_from_a_collection(self):
        self.assertTrue(wf.font_covers(wf.SYSTEM_FONT_DIR / "msyhbd.ttc", "\u5fae"))
        self.assertIsNotNone(self.white_box(wf.letter_tile("\u5fae\u4fe1", 64)))

    def test_never_raises(self):
        for name, px, radius in ((None, 32, 0), ("x", "bad", 0), ("x", 0, 0), ("x", 10_000, 0), ("x", 32, "r"),
                                 ("x", 32, float("nan")), ("x", 32, float("inf"))):
            tile = wf.letter_tile(name, px, radius)
            self.assertEqual(tile.mode, "RGBA")
        for px in (float("nan"), float("inf"), float("-inf"), True):      # non-finite sizes: the 32 px default
            self.assertEqual(wf.letter_tile("x", px).size, (32, 32), repr(px))
        for px in (float("nan"), float("inf"), "x", None, False):   # package_logo / relaunch_icon sizes
            self.assertEqual(wf._px(px), 128, repr(px))
        self.assertEqual((wf._px(0), wf._px(31.6), wf._px(10_000)), (1, 32, wf.MAX_PX))
        self.assertEqual(wf.letter_tile("x", 10_000).size, (wf.MAX_PX, wf.MAX_PX))
        self.assertEqual(wf.letter_tile("", 16).getpixel((8, 8))[3], 255, "no letter: a plain tile")


# ------------------------------------------------------------------ live (read-only)
@unittest.skipUnless(LIVE, "set NANOD_FACTS_LIVE_TESTS=1 (Windows) for read-only probes of the real desktop")
class LiveProbes(unittest.TestCase):
    """Read-only: no window is created, shown, focused or messaged beyond GetWindowText-
    level reads. Assertions check shapes only; messages never contain a value."""

    SETTINGS = "windows.immersivecontrolpanel_cw5n1h2txyewy!microsoft.windows.immersivecontrolpanel"

    @classmethod
    def setUpClass(cls):
        from control_center.windows import NativeWindows, eligible
        wf.clear_caches()
        records = NativeWindows().records()
        cls.hwnds = [r["hwnd"] for r in records if eligible(r, os.getpid())][:40]
        user, kernel = C.WinDLL("user32", use_last_error=True), C.WinDLL("kernel32", use_last_error=True)
        user.GetGuiResources.restype, user.GetGuiResources.argtypes = wf.DWORD, (wf.HANDLE, wf.DWORD)
        kernel.GetCurrentProcess.restype = wf.HANDLE
        cls.resources = staticmethod(lambda: (user.GetGuiResources(kernel.GetCurrentProcess(), 0),
                                              user.GetGuiResources(kernel.GetCurrentProcess(), 1)))

    def probe_all(self):
        facts = []
        for hwnd in self.hwnds:
            store = wf.window_property_store(hwnd)
            self.assertTrue(set(store) == {"aumid", "relaunch_display_name", "relaunch_icon"}, "store keys")
            self.assertTrue(all(v is None or isinstance(v, str) for v in store.values()), "store value types")
            aumid = wf.process_aumid(hwnd)
            self.assertTrue(aumid is None or isinstance(aumid, str), "aumid type")
            monitor = wf.monitor_friendly_name(hwnd)
            self.assertTrue(monitor is None or (isinstance(monitor, str) and monitor), "monitor type")
            facts.append((store, aumid))
        for aumid in {a for _s, a in facts if a} | {self.SETTINGS}:
            name = wf.package_display_name(aumid)
            self.assertTrue(name is None or (isinstance(name, str) and name), "package name type")
            logo = wf.package_logo(aumid, 128)
            self.assertTrue(logo is None or (logo.size == (128, 128) and logo.mode == "RGBA"), "logo shape")
        for store, _aumid in facts:
            if store["relaunch_icon"]:
                icon = wf.relaunch_icon(store["relaunch_icon"], 128)
                self.assertTrue(icon is None or icon.size == (128, 128), "relaunch icon shape")
        module = wf.relaunch_icon(r"%SystemRoot%\System32\shell32.dll,3", 128)
        self.assertTrue(module is not None and module.getchannel("A").getbbox() is not None, "module icon")
        self.assertTrue(all(isinstance(p, int) for p in wf.audible_pids()), "audible pid types")
        return facts

    def test_every_helper_on_the_real_desktop_and_no_leaks(self):
        started = time.perf_counter()
        self.probe_all()
        first = time.perf_counter() - started
        self.assertLess(first, 20.0, "probe time")
        wf.clear_caches()
        before = self.resources()
        self.probe_all()                                  # the same work again, caches cold
        wf.clear_caches()
        after = self.resources()
        self.assertTrue(after[0] <= before[0] and after[1] <= before[1], "GDI/USER objects returned to baseline")

    def test_settings_app_resolves(self):
        name = wf.package_display_name(self.SETTINGS)
        self.assertTrue(isinstance(name, str) and name, "the Settings app has an AppsFolder name")
        logo = wf.package_logo(self.SETTINGS, 128)
        self.assertTrue(logo is not None and logo.getchannel("A").getbbox() is not None, "Settings logo")

    def test_settings_logo_edges_are_not_brightened(self):
        """The decoded logo's semi-transparent pixels keep the raw bitmap's colours: the
        shell's icon-only bitmap is straight alpha, so nothing is un-premultiplied."""
        api, seen, original = wf.FactsApi(), {}, wf._hbitmap_image

        def spy(api_, bitmap, *args, **kwargs):     # the same HBITMAP, read raw and decoded
            size = wf._bitmap_size(api_, bitmap)
            seen["bits"] = wf._bitmap_bits(api_, bitmap, *size) if size else None
            seen["image"] = original(api_, bitmap, *args, **kwargs)
            return seen["image"]

        wf._hbitmap_image = spy
        try:
            with wf._com(api):
                wf._shell_logo(api, self.SETTINGS, 128)
        finally:
            wf._hbitmap_image = original
        bits, image = seen.get("bits"), seen.get("image")
        self.assertTrue(bits is not None and image is not None, "the Settings logo decodes")
        semi = brightened = straight = 0
        for index, (r, g, b, a) in enumerate(image.getdata()):
            raw_b, raw_g, raw_r, raw_a = bits[index * 4:index * 4 + 4]
            if 0 < raw_a < 255:
                semi += 1
                brightened += (r > raw_r) or (g > raw_g) or (b > raw_b) or a != raw_a
                straight += max(raw_r, raw_g, raw_b) > raw_a     # impossible for premultiplied data
        self.assertTrue(semi > 0, "the logo has anti-aliased edges")
        self.assertEqual(brightened, 0, "no semi-transparent pixel is brightened")
        # The premise of the decode: this Windows build's icon-only bitmap is straight
        # alpha. If a build ever returns premultiplied data, this fails (and the decode
        # must un-premultiply again).
        self.assertGreater(straight, 0, "the shell bitmap carries straight alpha")

    def test_version_strings_of_real_files(self):
        python = wf.version_strings(sys.executable)
        self.assertTrue(python["FileDescription"] or python["ProductName"], "python.exe has version strings")
        explorer = wf.version_strings(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "explorer.exe"))
        self.assertTrue(explorer["FileDescription"], "explorer.exe has a FileDescription")
        started = time.perf_counter()
        wf.version_strings(sys.executable)
        self.assertLess(time.perf_counter() - started, 0.005, "cached read")

    def test_audible_pids_is_quick(self):
        started = time.perf_counter()
        pids = wf.audible_pids()
        self.assertLess(time.perf_counter() - started, 1.0, "Core Audio enumeration time")
        self.assertTrue(isinstance(pids, set), "a set")


if __name__ == "__main__":
    unittest.main(verbosity=1)
