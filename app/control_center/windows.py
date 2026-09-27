"""Windows picker: stable identities, the carousel presenter, snap, the toast service, and opt-in F24.

All adapter methods and callbacks belong to the Tk UI thread. Importing this
module does not register keys, create windows, or change desktop focus. Native
focus changes happen only in show/activate/cancel/close_pair, never while
highlighting or snapping.

The picker's presentation is the window picker v2 (desktop v7: DESKTOP_STAGE.md
section 9, CAROUSEL.md section 12): WindowsAdapter builds it through the
module-global factory ``PickerOverlay`` (tests patch it) and drives it through
the PickerOverlay protocol (hwnd, show, focus_local, highlight, set_icons, hide,
close, rect) plus set_labels, set_background, set_reduced_motion, take_events,
the exit animations and the v7 calls (snap, complete_one_side, raise_window,
half_rect, toast, end_toast). The presenter runs on its own native threads: its
input (Esc, Enter, arrows, wheel, a centre-card click) and its results (snap
results, the one-side completion, a display close) are queued there and drained
by ``pump()`` on the Tk thread. Activation stays synchronous: focus(target) ->
verify -> the exit -> hide.

The runtime's view of this adapter (K3 section 9.9, K4 section 2.3): snapshot /
show / activate / highlight(index, bump) / hide as in v6; ``snap(effect)``,
``half_rect(side)``, ``close_pair(left, right, focus)``, ``cancel(origin,
complete=, reason=)``, ``foreground_hwnd()``, ``toast(text, exit=)`` and
``take_events()``, which returns the K4 events as dicts: ``opened`` /
``closed`` (surface ``picker``), ``snap_result(side, outcome)``,
``cancel_result(restored, completed)`` and ``system(lock | sleep)``.

IconWorker reads application icons (targeted-colour accents, mirror/picker
tiles) on its own COM apartment thread; it never touches focus or the hotkey.
Next to each 32 px icon it keeps a 128 px copy for the floating knob's LCD
(FLOATING_KNOB.md section 2), taken from the shell's jumbo image list. For the
carousel (``facts=True``) it also gathers each window's label facts and a 128 px
icon master (CAROUSEL.md sections 6 and 7) on a separate channel, poll_facts(),
so the (item_id, icon, accent) contract stays exactly as it was.

Native callbacks never call tkinter. The subclassed window procedure (F24) and
the WinEvent hooks are ctypes callbacks that Windows runs on the Tk thread from
inside Tcl's notifier (Tcl_DoOneEvent). A tkinter call made there leaves
_tkinter's per-thread Tcl thread state NULL (its LEAVE_TCL has no matching
LEAVE_PYTHON), and the next Tcl-invoked Python callback of that same
Tcl_DoOneEvent (typically an ``after`` timer) calls PyEval_RestoreThread(NULL):
Py_FatalError -> abort() -> 0xc0000409 fast-fail 7 in ucrtbase. Its crash dump
shows exactly that stack for the cc4 companion with the picker open; the
foreground hook's ``root.after`` was the call that could run there while the
picker sat open. So: WinEvents only queue the window handle for ``pump()``, and
F24 runs its handler through TclInvoker (inside _tkinter's own Python-command
bracket) only when the procedure was entered straight from tkinter's event
loop; anywhere else it is deferred to the next ``pump()``.

Win32 references:
https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-registerhotkey
https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-setforegroundwindow
https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-setwineventhook
https://learn.microsoft.com/windows/win32/winmsg/wm-geticon
https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-geticoninfo
https://learn.microsoft.com/windows/win32/api/shellapi/nf-shellapi-shgetfileinfow
https://learn.microsoft.com/windows/win32/api/shellapi/nf-shellapi-shgetimagelist
https://learn.microsoft.com/windows/win32/api/commoncontrols/nf-commoncontrols-iimagelist-geticon
"""
from __future__ import annotations

import ctypes as C
import logging
import os
import re
import sys
import threading
import time
from collections import OrderedDict, deque
from datetime import date
from pathlib import PureWindowsPath

_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())

DWORD = C.c_uint32
LONG = C.c_int32
BOOL = C.c_int32
UINT = C.c_uint32
HANDLE = C.c_void_p
LPARAM = C.c_ssize_t
WPARAM = C.c_size_t
WINFUNCTYPE = getattr(C, "WINFUNCTYPE", C.CFUNCTYPE)
WNDPROC = WINFUNCTYPE(LPARAM, HANDLE, UINT, WPARAM, LPARAM)
ENUMPROC = WINFUNCTYPE(BOOL, HANDLE, LPARAM)
EVENTPROC = WINFUNCTYPE(None, HANDLE, DWORD, HANDLE, LONG, LONG, DWORD, DWORD)

WS_EX_TOOLWINDOW = 0x80
WS_EX_APPWINDOW = 0x40000
WS_EX_NOACTIVATE = 0x08000000
WM_HOTKEY = 0x0312
HOTKEY_ID = 0x4E44
VK_F24 = 0x87
MOD_NOREPEAT = 0x4000
# Settings "Switcher background" (CAROUSEL.md sections 3 and 11): Frosted (default, the full-screen
# frost) / No background.
PICKER_BACKGROUNDS = ("glass", "none")
DEFAULT_PICKER_BACKGROUND = "glass"
HOST_PLAIN_MODE = "plain"   # carousel.HOST_PLAIN: the fallback host, where only "glass" is offered
LABEL_SEPARATOR = " · "   # the carousel's middle dot (the Switch toast: "{App} · {Title}")

# Icon extraction (IconWorker). Handles are pointer-sized; ULONG_PTR results.
ULONG_PTR = C.c_size_t
WM_GETICON = 0x007F
ICON_BIG, ICON_SMALL2 = 1, 2
SMTO_BLOCK, SMTO_ABORTIFHUNG = 0x0001, 0x0002
ICON_MESSAGE_TIMEOUT_MS = 50
GCLP_HICON, GCLP_HICONSM = -14, -34
SHGFI_ICON, SHGFI_LARGEICON = 0x100, 0x0
COINIT_APARTMENTTHREADED = 0x2
BI_RGB, DIB_RGB_COLORS = 0, 0
ICON_SIZE = 32
MAX_ICON_EDGE = 512
UWP_HOSTS = frozenset({"applicationframehost"})
# Hi-res app icons (floating knob): the shell's system image lists, by the exe's
# system icon index. The 128 px copy rides in the 32 px icon's ``info``.
SHGFI_SYSICONINDEX = 0x4000
SHIL_LARGE, SHIL_EXTRALARGE, SHIL_JUMBO = 0, 2, 4   # 32, 48, 256 px at 96 DPI
ILD_TRANSPARENT = 0x1
IIMAGELIST_RELEASE, IIMAGELIST_GET_ICON = 2, 10     # IImageList vtable slots
ICON_HIRES_SIZE = 128
ICON_HIRES_INFO = "nanod.iconHires"
HIRES_MATCH_TOLERANCE = 12.0   # mean |difference| per channel (0..255) at 32 px
SMALL_JUMBO_EDGE = 64          # jumbo content inside this corner box: the exe has no big icon
# The carousel's per-window icon master (CAROUSEL.md section 7) and label facts (section 6).
ICON_MASTER_SIZE = 128
# "Meet - <code>" titles are the only ones whose label needs the (lazy) Core Audio check.
MEET_TITLE = re.compile(r"\bMeet\s+[-–—]\s+\S")

# Native event bridge (see the module docstring).
FOCUS_SETTLE_SECONDS = 0.06   # an external foreground change is re-checked this much later
# NativeWindows.focus: activating a window of another thread completes only when that thread
# next reads its queue (the carousel host lives on NanoD-carousel, which composes its first
# frame right after the show() handshake: dim + chrome + first label + DwmFlush measure about
# 50-60 ms cold). The verify re-checks every FOCUS_POLL_SECONDS (a sleep, never a spin) for at
# most FOCUS_VERIFY_SECONDS; a window that is already the foreground returns at the first check.
# A Switch or Cancel target (a window of another process: its thread usually still has it as
# its active window, so the first check mostly succeeds, as v5's single check did) gets the
# shorter FOCUS_VERIFY_OTHER_SECONDS, so a hung target or one that activates an owned dialog
# blocks the Tk thread for at most that long.
FOCUS_VERIFY_SECONDS = 0.25
FOCUS_VERIFY_OTHER_SECONDS = 0.10
FOCUS_POLL_SECONDS = 0.004
FOREGROUND_EVENT_LIMIT = 256  # queued WinEvent window handles awaiting pump()
# K4 9.7: a one-side completion resolves by its start + 600 ms on NanoD-snap (and the carousel's
# backstop); this adapter-side bound only covers a presenter that never answers at all.
CANCEL_RESULT_BACKSTOP_SECONDS = 1.0
SIDES = ("left", "right")
LIFETIME_REASONS = ("back", "hold", "lock", "sleep", "idle")
# K3 closes an open overlay after 60 s without knob input (controller OVERLAY_IDLE) and K4 15 hides
# the picker at once for ``idle``. K3's windows_cancel payload carries no reason (WP7b-D6), so until
# the runtime passes one this adapter infers ``idle`` when a cancel with no reason comes this long
# after the last knob-driven call it saw (show, highlight, snap, activate). A cancel from a press
# always follows knob input by less, so an explicit Back or hold is never taken for idle.
IDLE_INFER_SECONDS = 59.5
DESKTOP_READOBJECTS, UOI_NAME = 0x0001, 2
TCL_OK, TCL_EVAL_GLOBAL = 0, 0x20000
# ctypes thunks Windows may still call (a queued WinEvent after UnhookWinEvent, a
# message racing the window-procedure restore) are never freed. They hold no
# reference to an adapter: closing clears the indirection they call through.
_RETIRED_CALLBACKS = []
_TK_EVENT_LOOP_CODES = None


def _tk_event_loop_codes():
    global _TK_EVENT_LOOP_CODES
    if _TK_EVENT_LOOP_CODES is None:
        import tkinter
        codes = {getattr(tkinter.Misc, name).__code__
                 for name in ("mainloop", "update", "wait_window", "wait_variable", "wait_visibility")}
        codes.add(tkinter.mainloop.__code__)
        _TK_EVENT_LOOP_CODES = frozenset(codes)
    return _TK_EVENT_LOOP_CODES


def called_from_tk_event_loop(frame) -> bool:
    """True when ``frame``, the Python frame directly below a native callback, is one
    of tkinter's event-loop entry points (mainloop, update, wait_*).

    Those frames make exactly one C call, into Tcl, bracketed by _tkinter's
    ENTER_TCL: a callback entered there runs inside Tcl with the thread state
    recorded, so TclInvoker may evaluate a Python command. Any other frame means
    the callback interrupted Python code (a Tcl-invoked Python callback that
    pumped messages through a ctypes call), where that must never happen.
    """
    try:
        return frame is not None and frame.f_code in _tk_event_loop_codes()
    except Exception:
        return False


def _loaded_tcl(widget):
    """(the Tcl DLL _tkinter already uses, its Tcl_Size ctype) or (None, None).

    Only a module that is already loaded is used (GetModuleHandleW), never a
    second copy found on the search path.
    """
    if sys.platform != "win32":
        return None, None
    major, minor = (int(part) for part in str(widget.tk.call("info", "patchlevel")).split(".")[:2])
    kernel = C.WinDLL("kernel32", use_last_error=True)
    module = kernel.GetModuleHandleW
    module.restype, module.argtypes = HANDLE, (C.c_wchar_p,)
    for name in (f"tcl{major}{minor}t.dll", f"tcl{major}{minor}.dll", f"tcl9tcl{major}{minor}.dll"):
        handle = module(name)
        if handle:
            # Tcl 9 widened lengths to Tcl_Size (ptrdiff_t); 8.x uses int.
            return C.CDLL(name, handle=handle), (C.c_int if major < 9 else C.c_ssize_t)
    return None, None


class TclInvoker:
    """Run a Python callable from a native callback on the Tk thread, through Tcl.

    ``widget.register(func)`` makes a Tcl command; calling the invoker evaluates
    it with Tcl_EvalEx through ctypes (not _tkinter), so _tkinter's PythonCmd
    brackets ``func`` with ENTER_PYTHON/LEAVE_PYTHON and restores the thread
    state it depends on. ``func``'s exceptions go to report_callback_exception.
    Use only when called_from_tk_event_loop() is True for the callback.
    """

    def __init__(self, widget, func):
        tcl, size = _loaded_tcl(widget)
        if tcl is None:
            raise OSError("The Tcl library used by tkinter is not loaded.")
        evaluate = tcl.Tcl_EvalEx
        evaluate.restype, evaluate.argtypes = C.c_int, (C.c_void_p, C.c_char_p, size, C.c_int)
        self._widget = widget
        self._interp = widget.tk.interpaddr()
        self._evaluate = evaluate
        self._name = widget.register(func)
        self._script = self._name.encode("ascii")

    def __call__(self):
        """True when Tcl ran the command (its Python errors are reported, not raised)."""
        if not self._name:
            return False
        return self._evaluate(self._interp, self._script, len(self._script), TCL_EVAL_GLOBAL) == TCL_OK

    def close(self):
        name, self._name = self._name, None
        if name:
            try:
                self._widget.deletecommand(name)
            except Exception:
                pass


def _make_invoker(widget, func):
    """A TclInvoker, or None where the Tcl library cannot be reached (F24 is then
    always deferred to pump())."""
    try:
        return TclInvoker(widget, func)
    except Exception:
        return None


class FILETIME(C.Structure):
    _fields_ = [("low", DWORD), ("high", DWORD)]


class ICONINFO(C.Structure):
    _fields_ = [("fIcon", BOOL), ("xHotspot", DWORD), ("yHotspot", DWORD),
                ("hbmMask", HANDLE), ("hbmColor", HANDLE)]


class BITMAP(C.Structure):
    _fields_ = [("bmType", LONG), ("bmWidth", LONG), ("bmHeight", LONG), ("bmWidthBytes", LONG),
                ("bmPlanes", C.c_uint16), ("bmBitsPixel", C.c_uint16), ("bmBits", C.c_void_p)]


class BITMAPINFOHEADER(C.Structure):
    _fields_ = [("biSize", DWORD), ("biWidth", LONG), ("biHeight", LONG), ("biPlanes", C.c_uint16),
                ("biBitCount", C.c_uint16), ("biCompression", DWORD), ("biSizeImage", DWORD),
                ("biXPelsPerMeter", LONG), ("biYPelsPerMeter", LONG), ("biClrUsed", DWORD),
                ("biClrImportant", DWORD)]


class BITMAPINFO(C.Structure):
    # Room for a colour table even though 32bpp BI_RGB output does not use one.
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", DWORD * 256)]


class SHFILEINFOW(C.Structure):
    _fields_ = [("hIcon", HANDLE), ("iIcon", C.c_int), ("dwAttributes", DWORD),
                ("szDisplayName", C.c_wchar * 260), ("szTypeName", C.c_wchar * 80)]


class GUID(C.Structure):
    _fields_ = [("Data1", C.c_uint32), ("Data2", C.c_uint16), ("Data3", C.c_uint16),
                ("Data4", C.c_ubyte * 8)]


# IID_IImageList {46EB5926-582E-4017-9FDF-E8998DAA0950}
IID_IIMAGELIST = GUID(0x46EB5926, 0x582E, 0x4017,
                      (C.c_ubyte * 8)(0x9F, 0xDF, 0xE8, 0x99, 0x8D, 0xAA, 0x09, 0x50))
# HRESULT IImageList::GetIcon(int i, UINT flags, HICON *picon); ULONG Release()
_IMAGELIST_GET_ICON = WINFUNCTYPE(LONG, HANDLE, C.c_int, UINT, C.POINTER(HANDLE))
_COM_RELEASE = WINFUNCTYPE(C.c_uint32, HANDLE)


def is_uwp_host(app, path=None) -> bool:
    """Packaged (UWP) windows are framed by ApplicationFrameHost: no icon in cc5."""
    stem = PureWindowsPath(path).stem if isinstance(path, str) and path else ""
    return str(app or "").lower() in UWP_HOSTS or stem.lower() in UWP_HOSTS


def eligible(record: dict, own_pid: int) -> bool:
    """Switcher candidates; a minimized application remains eligible."""
    style = int(record.get("exstyle", 0))
    return bool(
        record.get("hwnd") and record.get("pid") != own_pid
        and record.get("visible", True) and not record.get("cloaked", False)
        and str(record.get("title", "")).strip()
        and not style & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        and (not record.get("owner") or style & WS_EX_APPWINDOW)
        and record.get("class_name", "") not in
        {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}
    )


def same_identity(item: dict, identity: dict | None) -> bool:
    """Never retarget a stale entry by title, process name, or enumeration slot."""
    if not identity or not item.get("available", True):
        return False
    if (item.get("hwnd"), item.get("pid")) != (identity.get("hwnd"), identity.get("pid")):
        return False
    # Origin records supplied by callers may only contain hwnd/pid.
    return not item.get("id") or item["id"] == identity.get("id")


def make_snapshot(records: list[dict], foreground: dict | None, mru: list[str], own_pid: int) -> dict:
    """Freeze eligible windows, current first, then actual observed MRU."""
    candidates = [dict(r, available=True) for r in records if eligible(r, own_pid)]
    ranks = {identity: rank for rank, identity in enumerate(mru)}
    enumeration = {r["id"]: index for index, r in enumerate(candidates)}
    current = next((r for r in candidates if same_identity(r, foreground)), None)
    candidates.sort(key=lambda r: (0 if current and r["id"] == current["id"] else 1,
                                   ranks.get(r["id"], len(ranks) + enumeration[r["id"]])))
    return {"items": candidates, "index": 1 if current and len(candidates) > 1 else 0,
            "origin": dict(foreground or {"hwnd": 0, "pid": 0})}


def _window_labels():
    """control_center.window_labels (pure, table-driven; CAROUSEL.md section 6). Tests patch this."""
    from . import window_labels
    return window_labels


def _window_facts():
    """control_center.window_facts (Win32/COM helpers for the IconWorker thread). Tests inject theirs."""
    from . import window_facts
    return window_facts


def window_exe(item) -> str:
    """The process base name of a snapshot item ("chrome.exe"): from its image path (never
    logged), else its exe stem. Only the name is used: labels, never paths."""
    path, app = item.get("path"), str(item.get("app") or "")
    if isinstance(path, str) and path:
        return PureWindowsPath(path).name
    return f"{app}.exe" if app else ""


def browser_profile(relaunch_display_name):
    """The browser profile a window's RelaunchDisplayNameResource names ("<profile> - Chrome"),
    or None (window_labels.profile_from_relaunch_name). The name is personal: it is shown on
    screen only (duplicate labels) and never logged."""
    try:
        return _window_labels().profile_from_relaunch_name(relaunch_display_name)
    except Exception:
        return None


def meet_call(item) -> bool:
    """Whether a snapshot item is a browser's Meet call ("Meet - <code>"): only those need the
    lazy Core Audio check (window_labels.meet_window decides; a quick title test first)."""
    title = str(item.get("title") or "")
    if not MEET_TITLE.search(title):
        return False
    try:
        labels = _window_labels()
        exe = window_exe(item)
        return bool(labels.meet_window(labels.WindowFacts(
            exe=exe, app=labels.app_display_name(exe), title=title, class_name=str(item.get("class_name") or ""))))
    except Exception:
        return True   # undecided: the check is harmless, the rules still decide the label


def picker_icons(window_icons, window_facts=None, hires_icon=None):
    """item id -> the carousel's icon for that window (CAROUSEL.md section 7): the IconWorker's
    128 px master from the facts channel (the section 7 ladder), else the floating knob's 128 px
    copy of the knob's icon (``hires_icon(item_id)``), else the 32 px icon, else None (the
    presenter draws a letter tile). The knob's own 32 px icons and payloads are not touched."""
    icons = dict(window_icons or {})
    facts = window_facts or {}
    result = {}
    for item_id in list(icons) + [key for key in facts if key not in icons]:
        entry = facts.get(item_id)
        master = entry.get("icon") if isinstance(entry, dict) else None
        if master is None and hires_icon is not None and icons.get(item_id) is not None:
            try:
                master = hires_icon(item_id)
            except Exception:
                master = None
        result[item_id] = master if master is not None else icons.get(item_id)
    return result

class NativeWindows:
    """Small ctypes boundary; helpers above remain usable on other platforms."""

    def __init__(self):
        if sys.platform != "win32":
            raise OSError("The window picker requires Windows.")
        self.u = C.WinDLL("user32", use_last_error=True)
        self.k = C.WinDLL("kernel32", use_last_error=True)
        self.d = C.WinDLL("dwmapi", use_last_error=True)
        self.own_pid = os.getpid()
        self.generations = {}
        self._hooks = []
        self._event_callbacks = []
        self._wndproc = None
        self._old_proc = None
        self._hotkey_owner = 0
        self._hotkey_enabled = False
        # What the native thunks call through; cleared on close so a retired
        # thunk never keeps (or calls into) a closed adapter.
        self._hotkey_handler = self._hotkey_report = None
        self._on_foreground = self._on_destroy = None
        self.last_focus = None   # (granted, milliseconds, checks) of the last focus() (diagnostics)
        self._bind()

    @property
    def hotkey_enabled(self):
        return self._hotkey_enabled

    @staticmethod
    def _signature(dll, name, result, *args):
        function = getattr(dll, name)
        function.restype, function.argtypes = result, args
        return function

    def _bind(self):
        u, k, d, sig = self.u, self.k, self.d, self._signature
        for name, result, args in (
            ("EnumWindows", BOOL, (ENUMPROC, LPARAM)),
            ("IsWindow", BOOL, (HANDLE,)), ("IsWindowVisible", BOOL, (HANDLE,)),
            ("IsIconic", BOOL, (HANDLE,)), ("GetForegroundWindow", HANDLE, ()),
            ("GetWindowThreadProcessId", DWORD, (HANDLE, C.POINTER(DWORD))),
            ("GetWindowTextW", C.c_int, (HANDLE, C.c_wchar_p, C.c_int)),
            ("GetClassNameW", C.c_int, (HANDLE, C.c_wchar_p, C.c_int)),
            ("GetWindow", HANDLE, (HANDLE, UINT)), ("GetAncestor", HANDLE, (HANDLE, UINT)),
            ("SetForegroundWindow", BOOL, (HANDLE,)), ("ShowWindowAsync", BOOL, (HANDLE, C.c_int)),
            ("RegisterHotKey", BOOL, (HANDLE, C.c_int, UINT, UINT)),
            ("UnregisterHotKey", BOOL, (HANDLE, C.c_int)),
            ("CallWindowProcW", LPARAM, (HANDLE, HANDLE, UINT, WPARAM, LPARAM)),
            ("SetWinEventHook", HANDLE, (DWORD, DWORD, HANDLE, EVENTPROC, DWORD, DWORD, DWORD)),
            ("UnhookWinEvent", BOOL, (HANDLE,)),
            ("OpenInputDesktop", HANDLE, (DWORD, BOOL, DWORD)),
            ("GetUserObjectInformationW", BOOL, (HANDLE, C.c_int, C.c_void_p, DWORD, C.POINTER(DWORD))),
            ("CloseDesktop", BOOL, (HANDLE,)),
        ):
            sig(u, name, result, *args)
        long_name = "GetWindowLongPtrW" if C.sizeof(HANDLE) == 8 else "GetWindowLongW"
        set_name = "SetWindowLongPtrW" if C.sizeof(HANDLE) == 8 else "SetWindowLongW"
        self.get_long = sig(u, long_name, LPARAM, HANDLE, C.c_int)
        self.set_long = sig(u, set_name, LPARAM, HANDLE, C.c_int, LPARAM)
        sig(k, "OpenProcess", HANDLE, DWORD, BOOL, DWORD)
        sig(k, "CloseHandle", BOOL, HANDLE)
        sig(k, "GetProcessTimes", BOOL, HANDLE, C.POINTER(FILETIME), C.POINTER(FILETIME),
            C.POINTER(FILETIME), C.POINTER(FILETIME))
        sig(k, "QueryFullProcessImageNameW", BOOL, HANDLE, DWORD, C.c_wchar_p, C.POINTER(DWORD))
        # The picker's placement and DWM thumbnails belong to the carousel (control_center.carousel,
        # its own ctypes table on its own thread); only the cloaked check stays here.
        sig(d, "DwmGetWindowAttribute", LONG, HANDLE, DWORD, HANDLE, DWORD)

    def root_handle(self, hwnd):
        return int(self.u.GetAncestor(hwnd, 2) or hwnd)  # GA_ROOT, not owner chain

    def _pid(self, hwnd):
        pid = DWORD()
        self.u.GetWindowThreadProcessId(hwnd, C.byref(pid))
        return int(pid.value)

    def _process_info(self, pid):
        """(creation FILETIME, executable stem, full image path or "").

        The path exists only for local icon extraction; it is never logged,
        shown, or sent to the knob.
        """
        process = self.k.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not process:
            return 0, "Application", ""
        try:
            times = [FILETIME() for _ in range(4)]
            birth = 0
            if self.k.GetProcessTimes(process, *(C.byref(t) for t in times)):
                birth = (times[0].high << 32) | times[0].low
            name, size = C.create_unicode_buffer(32768), DWORD(32768)
            app, path = "Application", ""
            if self.k.QueryFullProcessImageNameW(process, 0, name, C.byref(size)):
                path = name.value
                app = PureWindowsPath(path).stem
            return birth, app, path
        finally:
            self.k.CloseHandle(process)

    def identity(self, hwnd):
        hwnd = int(hwnd or 0)
        if not hwnd or not self.u.IsWindow(hwnd):
            return None
        pid = self._pid(hwnd)
        if not pid:
            return None
        generation = self.generations.setdefault(hwnd, 0)
        birth, _, _ = self._process_info(pid)
        # Process creation time adds protection if an HWND and PID are reused.
        return {"hwnd": hwnd, "pid": pid, "id": f"{hwnd:x}:{pid}:{birth:x}:{generation}"}

    def foreground(self):
        hwnd = self.u.GetForegroundWindow()
        return self.identity(self.root_handle(hwnd)) if hwnd else None

    def records(self):
        result = []

        @ENUMPROC
        def collect(hwnd, _):
            try:
                pid = self._pid(hwnd)
                if pid == self.own_pid or not self.u.IsWindowVisible(hwnd):
                    return True
                title, class_name = C.create_unicode_buffer(1024), C.create_unicode_buffer(256)
                # GetWindowText reads the OS-maintained top-level caption for
                # other processes; never send WM_GETTEXT to a potentially hung app.
                self.u.GetWindowTextW(hwnd, title, len(title))
                self.u.GetClassNameW(hwnd, class_name, len(class_name))
                cloaked = DWORD()
                self.d.DwmGetWindowAttribute(hwnd, 14, C.byref(cloaked), C.sizeof(cloaked))
                identity = self.identity(hwnd)
                if identity:
                    _, app, path = self._process_info(pid)
                    # "path" feeds IconWorker only (never logged or sent). UWP
                    # frames belong to ApplicationFrameHost: no icon, white accent.
                    result.append(dict(identity, title=title.value, app=app,
                                       path=None if is_uwp_host(app, path) else (path or None),
                                       visible=True, cloaked=bool(cloaked.value),
                                       exstyle=int(self.get_long(hwnd, -20)),
                                       owner=int(self.u.GetWindow(hwnd, 4) or 0),
                                       class_name=class_name.value,
                                       minimized=bool(self.u.IsIconic(hwnd))))
            except Exception:
                # A window may disappear while EnumWindows is visiting it.
                pass
            return True

        self.u.EnumWindows(collect, 0)
        return result

    def watch(self, on_foreground, on_destroy):
        """Out-of-context WinEvent hooks. Windows runs them on this (Tk) thread from
        inside message retrieval, so the handlers must not call tkinter: they only
        record (see the module docstring)."""
        self._on_foreground, self._on_destroy = on_foreground, on_destroy

        @EVENTPROC
        def foreground_event(_hook, _event, hwnd, _obj, _child, _thread, _time):
            handler = self._on_foreground
            if hwnd and handler is not None:
                try:
                    handler(int(hwnd))
                except Exception:
                    pass  # never unwind into user32

        @EVENTPROC
        def destroyed_event(_hook, _event, hwnd, obj, child, _thread, _time):
            handler = self._on_destroy
            if hwnd and obj == 0 and child == 0 and handler is not None:  # OBJID_WINDOW / CHILDID_SELF
                try:
                    number = int(hwnd)
                    if number in self.generations:
                        self.generations[number] += 1
                        handler(number)
                except Exception:
                    pass

        self._event_callbacks = [foreground_event, destroyed_event]
        for event, callback in ((3, foreground_event), (0x8001, destroyed_event)):
            hook = self.u.SetWinEventHook(event, event, None, callback, 0, 0, 0)
            if not hook:
                self.stop_watching()
                raise OSError(C.get_last_error(), "Could not monitor Windows foreground changes.")
            self._hooks.append(hook)

    def stop_watching(self):
        for hook in self._hooks:
            self.u.UnhookWinEvent(hook)
        self._hooks.clear()
        self._on_foreground = self._on_destroy = None
        # An event queued before the unhook may still be delivered: keep the thunks.
        _RETIRED_CALLBACKS.extend(self._event_callbacks)
        self._event_callbacks = []

    def attach_hotkey(self, hwnd, callback, report_error):
        """Subclass ``hwnd`` for WM_HOTKEY.

        ``callback(event_loop=...)`` runs inside the window procedure, a ctypes
        callback on the Tk thread, while Windows still grants this process the
        foreground for the hotkey. ``event_loop`` is True only when the procedure
        was entered straight from tkinter's event loop (called_from_tk_event_loop):
        the callback must not call tkinter otherwise.
        """
        self._hotkey_owner = hwnd
        self._hotkey_handler, self._hotkey_report = callback, report_error

        @WNDPROC
        def procedure(window, message, wparam, lparam):
            if message == WM_HOTKEY and wparam == HOTKEY_ID:
                handler = self._hotkey_handler
                if self._hotkey_enabled and handler is not None:
                    try:
                        handler(event_loop=called_from_tk_event_loop(sys._getframe(1)))
                    except BaseException:
                        report = self._hotkey_report
                        if report is not None:
                            try:
                                report(*sys.exc_info())
                            except BaseException:
                                pass
                return 0
            return self.u.CallWindowProcW(self._old_proc, window, message, wparam, lparam)

        self._wndproc = procedure  # Never let ctypes callbacks be garbage-collected.
        C.set_last_error(0)
        previous = self.set_long(hwnd, -4, C.cast(procedure, HANDLE).value)
        if not previous and C.get_last_error():
            self._wndproc = None
            self._hotkey_handler = self._hotkey_report = None
            raise OSError(C.get_last_error(), "Could not attach the F24 message handler.")
        self._old_proc = previous

    def hotkey(self, enabled):
        enabled = bool(enabled)
        if enabled == self._hotkey_enabled:
            return
        if enabled:
            if not self.u.RegisterHotKey(self._hotkey_owner, HOTKEY_ID, MOD_NOREPEAT, VK_F24):
                raise OSError(C.get_last_error(), "F24 could not be registered. Another application may be using it.")
            self._hotkey_enabled = True
        else:
            self.u.UnregisterHotKey(self._hotkey_owner, HOTKEY_ID)
            self._hotkey_enabled = False

    def focus(self, hwnd, restore=False):
        """SetForegroundWindow(hwnd), then verify that ``hwnd`` is the foreground window.

        Called from another thread than the window's (the carousel host belongs to the
        NanoD-carousel thread; every switch target to another process), SetForegroundWindow
        makes that thread's queue the foreground at once but posts the activation itself, which
        completes when the thread next reads its queue: until then GetForegroundWindow() is
        NULL, or still the thread's previously active window. So the verify re-checks every
        FOCUS_POLL_SECONDS for at most FOCUS_VERIFY_SECONDS for a window of this process (the
        carousel host) and FOCUS_VERIFY_OTHER_SECONDS for another process's window (a Switch or
        Cancel target). The return value of SetForegroundWindow is not trusted either way.
        ``last_focus`` keeps (granted, ms, checks) for the adapter's log; no title or handle is
        kept.
        """
        started = time.perf_counter()
        own = self._is_own_window(hwnd)
        if restore and self.u.IsIconic(hwnd):
            self.u.ShowWindowAsync(hwnd, 9)  # SW_RESTORE; never wait for the other process.
        self.u.SetForegroundWindow(hwnd)
        deadline = started + (FOCUS_VERIFY_SECONDS if own else FOCUS_VERIFY_OTHER_SECONDS)
        checks = 0
        while True:
            checks += 1
            current = self.u.GetForegroundWindow()
            granted = bool(current and self.root_handle(current) == hwnd)
            if granted or time.perf_counter() >= deadline:
                break
            time.sleep(FOCUS_POLL_SECONDS)
        self.last_focus = (granted, round((time.perf_counter() - started) * 1000.0, 1), checks)
        return granted

    def input_desktop_is_default(self):
        """K4 15: on a lost foreground the picker closes as ``lock`` when the input desktop is not
        ``Default`` (the lock screen, a UAC prompt), else as ``focus_lost``. Any failure to open
        the input desktop reads as locked."""
        desktop = self.u.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
        if not desktop:
            return False
        try:
            name, needed = C.create_unicode_buffer(64), DWORD(0)
            if not self.u.GetUserObjectInformationW(desktop, UOI_NAME, name, C.sizeof(name), C.byref(needed)):
                return False
            return name.value.lower() == "default"
        finally:
            self.u.CloseDesktop(desktop)

    def _is_own_window(self, hwnd):
        """True for a window of this process (the carousel host; the long verify). Any failure
        reads as own, which only keeps the longer, still bounded verify."""
        try:
            pid = self._pid(hwnd)
            return not pid or pid == self.own_pid
        except Exception:
            return True

    def close(self):
        self._hotkey_handler = self._hotkey_report = None
        try:
            self.hotkey(False)
        finally:
            self.stop_watching()
            procedure, self._wndproc = self._wndproc, None
            if procedure is not None:
                owner = self._hotkey_owner
                # Unsubclass only while ours is still the window's procedure: a
                # later subclass (another adapter) chains to it and keeps working.
                if (self._old_proc and self.u.IsWindow(owner)
                        and self.get_long(owner, -4) == C.cast(procedure, HANDLE).value):
                    self.set_long(owner, -4, self._old_proc)
                # A racing or chained message still finds a live thunk, which now
                # only forwards to _old_proc (kept) and never reaches this adapter.
                _RETIRED_CALLBACKS.append(procedure)


class IconApi:
    """ctypes boundary for application icons; every API is declared via sig().

    Handle ownership rules:
    * WM_GETICON and class icons belong to their window/class: never destroyed.
    * SHGetFileInfoW icons belong to the caller: destroy_icon() exactly once.
    * icon_image() always DeleteObject()s both bitmaps GetIconInfo created.
    Create and use an instance on one thread (IconWorker's), after co_initialize().
    """

    def __init__(self):
        if sys.platform != "win32":
            raise OSError("Application icons require Windows.")
        self.u = C.WinDLL("user32", use_last_error=True)
        self.g = C.WinDLL("gdi32", use_last_error=True)
        self.s = C.WinDLL("shell32", use_last_error=True)
        self.o = C.WinDLL("ole32", use_last_error=True)
        sig = NativeWindows._signature
        # LRESULT SendMessageTimeoutW(HWND, UINT, WPARAM, LPARAM, UINT, UINT, PDWORD_PTR)
        sig(self.u, "SendMessageTimeoutW", LPARAM, HANDLE, UINT, WPARAM, LPARAM, UINT, UINT,
            C.POINTER(ULONG_PTR))
        # ULONG_PTR GetClassLongPtrW(HWND, int); 32-bit user32 only exports GetClassLongW.
        class_long = "GetClassLongPtrW" if C.sizeof(HANDLE) == 8 else "GetClassLongW"
        self.get_class_long = sig(self.u, class_long, ULONG_PTR, HANDLE, C.c_int)
        sig(self.u, "GetIconInfo", BOOL, HANDLE, C.POINTER(ICONINFO))
        sig(self.u, "DestroyIcon", BOOL, HANDLE)
        sig(self.g, "GetObjectW", C.c_int, HANDLE, C.c_int, C.c_void_p)
        sig(self.g, "CreateCompatibleDC", HANDLE, HANDLE)
        sig(self.g, "DeleteDC", BOOL, HANDLE)
        sig(self.g, "GetDIBits", C.c_int, HANDLE, HANDLE, UINT, UINT, C.c_void_p,
            C.POINTER(BITMAPINFO), UINT)
        sig(self.g, "DeleteObject", BOOL, HANDLE)
        # DWORD_PTR SHGetFileInfoW(LPCWSTR, DWORD, SHFILEINFOW*, UINT, UINT)
        sig(self.s, "SHGetFileInfoW", ULONG_PTR, C.c_wchar_p, DWORD, C.POINTER(SHFILEINFOW), UINT, UINT)
        sig(self.o, "CoInitializeEx", LONG, C.c_void_p, DWORD)
        sig(self.o, "CoUninitialize", None)
        # HRESULT SHGetImageList(int, REFIID, void**). Optional: without it there are
        # only 32 px icons (the floating knob then upscales them).
        try:
            self.get_image_list = sig(self.s, "SHGetImageList", LONG, C.c_int, C.POINTER(GUID),
                                      C.POINTER(HANDLE))
        except AttributeError:
            self.get_image_list = None

    def co_initialize(self):
        """True when this thread must later call co_uninitialize (S_OK/S_FALSE)."""
        return self.o.CoInitializeEx(None, COINIT_APARTMENTTHREADED) in (0, 1)

    def co_uninitialize(self):
        self.o.CoUninitialize()

    def window_icon(self, hwnd, kind):
        """WM_GETICON without ever waiting on a hung window (window-owned handle)."""
        result = ULONG_PTR(0)
        if not self.u.SendMessageTimeoutW(hwnd, WM_GETICON, kind, 0, SMTO_ABORTIFHUNG | SMTO_BLOCK,
                                          ICON_MESSAGE_TIMEOUT_MS, C.byref(result)):
            return 0
        return int(result.value or 0)

    def class_icon(self, hwnd, index):
        """GCLP_HICON / GCLP_HICONSM (class-owned handle)."""
        return int(self.get_class_long(hwnd, index) or 0)

    def file_icon(self, path):
        """The executable's shell icon; the caller owns (and must destroy) it."""
        info = SHFILEINFOW()
        if not self.s.SHGetFileInfoW(path, 0, C.byref(info), C.sizeof(info), SHGFI_ICON | SHGFI_LARGEICON):
            return 0
        return int(info.hIcon or 0)

    def destroy_icon(self, hicon):
        self.u.DestroyIcon(hicon)

    def system_icon_index(self, path):
        """The exe's index in the shell's system image lists, or None (no handle is created)."""
        info = SHFILEINFOW()
        if not path or not self.s.SHGetFileInfoW(path, 0, C.byref(info), C.sizeof(info), SHGFI_SYSICONINDEX):
            return None
        return int(info.iIcon)

    def image_list_icon(self, index, kind):
        """System image list ``kind`` (SHIL_*) icon ``index`` as an RGBA image, or None.

        IImageList::GetIcon's HICON belongs to the caller: destroyed exactly once;
        the list interface is released on every path.
        """
        if self.get_image_list is None or index is None:
            return None
        image_list = HANDLE()
        if self.get_image_list(kind, C.byref(IID_IIMAGELIST), C.byref(image_list)) != 0 or not image_list.value:
            return None
        # The object's first field is its vtable pointer.
        slots = C.cast(C.cast(image_list.value, C.POINTER(C.c_void_p))[0], C.POINTER(C.c_void_p))
        try:
            hicon = HANDLE()
            if _IMAGELIST_GET_ICON(slots[IIMAGELIST_GET_ICON])(image_list.value, index, ILD_TRANSPARENT,
                                                                C.byref(hicon)) != 0 or not hicon.value:
                return None
            try:
                return self.icon_image(hicon.value)
            finally:
                self.destroy_icon(hicon.value)
        finally:
            _COM_RELEASE(slots[IIMAGELIST_RELEASE])(image_list.value)

    def hires_icon(self, path):
        """(big, reference) for an exe: its jumbo icon (256 px; the 48 px one when the exe
        has no big icon) and its 32 px shell icon from the same image lists, or None."""
        index = self.system_icon_index(path)
        if index is None:
            return None
        reference = self.image_list_icon(index, SHIL_LARGE)
        big = self.image_list_icon(index, SHIL_JUMBO)
        if big is None or small_jumbo(big):
            big = self.image_list_icon(index, SHIL_EXTRALARGE)
        if big is None or reference is None:
            return None
        return big, reference

    def icon_image(self, hicon):
        """HICON -> PIL RGBA image (straight alpha), or None."""
        info = ICONINFO()
        if not hicon or not self.u.GetIconInfo(hicon, C.byref(info)):
            return None
        try:
            return self._compose(info.hbmColor, info.hbmMask)
        finally:
            # GetIconInfo created both bitmaps for this caller.
            for bitmap in (info.hbmColor, info.hbmMask):
                if bitmap:
                    self.g.DeleteObject(bitmap)

    def _bitmap_size(self, hbitmap):
        bitmap = BITMAP()
        if not self.g.GetObjectW(hbitmap, C.sizeof(BITMAP), C.byref(bitmap)):
            return None
        width, height = int(bitmap.bmWidth), abs(int(bitmap.bmHeight))
        if not (0 < width <= MAX_ICON_EDGE and 0 < height <= 2 * MAX_ICON_EDGE):
            return None
        return width, height

    def _bits(self, hbitmap, width, height):
        """32bpp top-down BGRA rows of a DDB, or None."""
        header = BITMAPINFO()
        header.bmiHeader.biSize = C.sizeof(BITMAPINFOHEADER)
        header.bmiHeader.biWidth = width
        header.bmiHeader.biHeight = -height  # negative: top-down rows
        header.bmiHeader.biPlanes = 1
        header.bmiHeader.biBitCount = 32
        header.bmiHeader.biCompression = BI_RGB
        buffer = (C.c_ubyte * (width * height * 4))()
        dc = self.g.CreateCompatibleDC(None)
        if not dc:
            return None
        try:
            lines = self.g.GetDIBits(dc, hbitmap, 0, height, buffer, C.byref(header), DIB_RGB_COLORS)
        finally:
            self.g.DeleteDC(dc)
        return bytes(buffer) if lines == height else None

    def _mask_alpha(self, mask, width, height, first_row=0):
        """Alpha from an AND mask (0 = opaque, 1 = transparent), or None."""
        from PIL import Image
        if not mask:
            return None
        size = self._bitmap_size(mask)
        if not size or size[0] != width or size[1] < first_row + height:
            return None
        bits = self._bits(mask, width, size[1])
        if bits is None:
            return None
        start = first_row * width * 4
        blue = bits[start:start + width * height * 4:4]
        return Image.frombytes("L", (width, height), blue.translate(_INVERT))

    def _compose(self, color, mask):
        from PIL import Image
        if color:
            size = self._bitmap_size(color)
            if not size or size[1] > MAX_ICON_EDGE:
                return None
            width, height = size
            bgra = self._bits(color, width, height)
            if bgra is None:
                return None
            image = Image.frombytes("RGBA", (width, height), bgra, "raw", "BGRA")
            if not any(bgra[3::4]):  # no alpha channel: legacy icon, use its mask
                alpha = self._mask_alpha(mask, width, height)
                image.putalpha(alpha if alpha is not None else 255)
            return image
        # Monochrome icon: one bitmap, AND mask (top half) over XOR image (bottom).
        size = self._bitmap_size(mask) if mask else None
        if not size or size[1] % 2:
            return None
        width, height = size[0], size[1] // 2
        bits = self._bits(mask, width, 2 * height)
        if bits is None:
            return None
        half = width * height * 4
        image = Image.frombytes("RGB", (width, height), bits[half:], "raw", "BGRX").convert("RGBA")
        image.putalpha(Image.frombytes("L", (width, height), bits[0:half:4].translate(_INVERT)))
        return image


_INVERT = bytes(255 - value for value in range(256))


def window_icon_image(api, hwnd):
    """WM_GETICON big, then small2. Window-owned handles are never destroyed."""
    for kind in (ICON_BIG, ICON_SMALL2):
        handle = api.window_icon(hwnd, kind)
        if handle:
            image = api.icon_image(handle)
            if image is not None:
                return image
    return None


def fallback_icon_image(api, hwnd, path):
    """Class icon (GCLP_HICON, GCLP_HICONSM), then SHGetFileInfoW on the exe."""
    if hwnd:
        for index in (GCLP_HICON, GCLP_HICONSM):
            handle = api.class_icon(hwnd, index)
            if handle:
                image = api.icon_image(handle)  # class-owned: never destroyed
                if image is not None:
                    return image
    if path:
        handle = api.file_icon(path)
        if handle:
            try:
                image = api.icon_image(handle)
            finally:
                api.destroy_icon(handle)  # SHGetFileInfoW transferred ownership
            if image is not None:
                return image
    return None


def extract_icon(api, hwnd, path):
    """Full fallback order for one window; RGBA PIL image or None."""
    image = window_icon_image(api, hwnd) if hwnd else None
    return image if image is not None else fallback_icon_image(api, hwnd, path)


def icon_thumbnail(image, size=ICON_SIZE):
    """A size x size RGBA copy (aspect kept, transparent padding)."""
    from PIL import Image, ImageOps
    image = image.convert("RGBA")
    if image.size == (size, size):
        return image.copy()
    fitted = ImageOps.contain(image, (size, size), Image.Resampling.LANCZOS)
    if fitted.size == (size, size):
        return fitted
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tile.paste(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2))
    return tile


def small_jumbo(image):
    """True when a jumbo-list icon is only a small icon drawn in its top-left corner
    (an exe without a big icon), or empty."""
    box = image.getchannel("A").getbbox() if image.mode == "RGBA" else None
    return box is None or (image.width > SMALL_JUMBO_EDGE and box[2] <= SMALL_JUMBO_EDGE
                           and box[3] <= SMALL_JUMBO_EDGE)


def _over_black(image):
    from PIL import Image
    image = icon_thumbnail(image)
    base = Image.new("RGBA", image.size, (0, 0, 0, 255))
    return Image.alpha_composite(base, image).convert("RGB"), image.getchannel("A")


def icon_matches(source, reference, tolerance=HIRES_MATCH_TOLERANCE):
    """Whether two icons show the same picture at 32 px: the window's own icon and the
    exe's shell icon. A window that sets another icon (a profile badge, a document)
    gets no hi-res copy, so the desktop never shows a different icon than the knob."""
    from PIL import ImageChops, ImageStat
    if source is None or reference is None:
        return False
    colour_a, alpha_a = _over_black(source)
    colour_b, alpha_b = _over_black(reference)
    colour = ImageStat.Stat(ImageChops.difference(colour_a, colour_b)).mean
    alpha = ImageStat.Stat(ImageChops.difference(alpha_a, alpha_b)).mean[0]
    return (sum(colour) + alpha) / 4 <= tolerance


def attach_hires_icon(icon, hires):
    """Store the 128 px copy in the 32 px icon's ``info`` (worker thread). Returns ``icon``."""
    if icon is not None and hires is not None:
        icon.info[ICON_HIRES_INFO] = hires
    return icon


def attached_hires_icon(icon):
    """The 128 px RGBA copy attach_hires_icon() stored on this icon, or None."""
    info = getattr(icon, "info", None)
    value = info.get(ICON_HIRES_INFO) if isinstance(info, dict) else None
    if getattr(value, "size", None) == (ICON_HIRES_SIZE, ICON_HIRES_SIZE) and getattr(value, "mode", "") == "RGBA":
        return value
    return None


class HiresIcon(tuple):
    """A later IconWorker result, (item_id, icon, accent) like the first one: the same 32 px
    icon (same pixels and payload) and accent the item was already delivered with, now
    carrying its 128 px copy (attached_hires_icon). ``hires`` tells it apart; a consumer
    that ignores it may simply store the icon again."""
    __slots__ = ()
    hires = True

    def __new__(cls, item_id, icon, accent):
        return super().__new__(cls, (item_id, icon, accent))


class IconWorker:
    """Background icons for the targeted-colour ring, the desktop mirror and the picker.

    request(items) takes a frozen snapshot's items; it only reads id/hwnd/path/app (and,
    with ``facts``, pid/class_name and whether the title is a Meet call), never reorders
    or mutates the list, and supersedes any unfinished request.
    poll() is nonblocking and drains (item_id, icon, accent) in snapshot order:
    icon is a 32x32 RGBA PIL image or None (letter tile), carrying its artwork2
    payload in ``info`` (artwork.attached_icon_payload); accent is
    artwork.dominant_rgb() of the native-size icon as 0xRRGGBB, or None (white).
    UWP frames (ApplicationFrameHost) always report (item_id, None, None).

    Floating knob (``hires=True``, the installed app's chrome=False mode only; the
    default is cc5.3's worker, which never touches the jumbo image list): a 128 px RGBA
    copy from the exe's jumbo system image list (IconApi.hires_icon), only when the
    window's own icon matches the exe's shell icon (icon_matches). It never delays the knob: every (item_id, 32 px icon, accent) of a
    snapshot is delivered first, exactly as before; only then, while no newer request
    waits, each copy follows as a HiresIcon result (the same 32 px icon and accent,
    with the copy attached: attached_hires_icon). The accent and the 2048-byte
    payload stay computed from the current 32 px sources.

    Carousel (``facts=True``, both app modes; CAROUSEL.md sections 6 and 7): after every
    32 px icon (and hi-res copy) of the snapshot, one facts job per window, ordered by
    distance from the selection (index 1 at open; prioritize() re-orders), gathers the
    label facts (version strings, the packaged app's display name, the browser profile,
    the monitor's friendly name) and a 128 px icon master from the ladder: package logo,
    the window's RelaunchIconResource (icon_matches), the v5 hi-res copy (icon_matches),
    the window's own icon upscaled, a letter tile. A snapshot with a browser's Meet call
    (meet_call) then gets one lazy Core Audio check (audible). prewarm() (once, at start) lets the
    first picker name its apps: the label facts of the windows open then, without icons. Results
    go to their own channel,
    poll_facts() -> [(item_id, partial facts dict)], so poll()'s 3-tuple contract, the 32 px
    icon and its payload are untouched. The Win32/COM helpers are control_center.window_facts
    (``facts_api`` injects a stand-in); a missing helper only leaves its fact out.
    The knob first, also while a facts job runs: a facts or prewarm job checks between its
    helper calls (_give_way) and gives way when a newer request is waiting (a facts job of an
    older snapshot is dropped; a prewarm job, which yields to any snapshot work, is queued
    again), so a new snapshot's 32 px icons wait for at most the one helper call in flight
    (a hi-res copy or the Meet check is a single call).

    The worker thread owns an apartment-threaded COM initialisation for
    SHGetFileInfoW, SHGetImageList and the facts helpers. Results are cached by
    executable path (class and shell icons, hi-res copies), by AUMID (package names
    and logos, answers only: a failed lookup is asked again, and window_facts rate-limits
    it) and by hwnd for WM_GETICON results within one snapshot. Paths and
    handles never leave this object and nothing here logs.
    """

    def __init__(self, *, api_factory=None, cache_size=64, hires=False, facts=False, facts_api=None):
        self._api_factory = api_factory or IconApi
        self._cache_size = max(1, int(cache_size))
        self._want_hires = bool(hires)
        self._want_facts = bool(facts)
        self._facts_api = facts_api      # worker thread: a window_facts stand-in, the module, or False
        self._exe_cache = OrderedDict()  # worker thread only: path -> (icon, accent)
        self._hires_cache = OrderedDict()  # worker thread only: path -> (128 px, 32 px reference) or None
        # Worker thread only (facts): AUMID -> display name / 128 px logo, answers only (_cached never
        # keeps a None: window_facts retries a failed lookup after FAILURE_TTL_SECONDS, e.g. when
        # shell:AppsFolder was not ready at logon). Relaunch icons are not cached here: window_facts
        # caches them per file mtime, so a changed profile picture is picked up.
        self._package_names = OrderedDict()
        self._logos = OrderedDict()
        self._condition = threading.Condition()
        self._generation = 0
        self._jobs = deque()
        self._results = []
        self._facts_jobs = deque()       # (generation, job): the carousel's facts, after the icons
        self._facts_results = []
        self._audible_job = None         # (generation, [(item_id, pid)]) when a Meet title is open
        self._prewarm_jobs = deque()     # label-facts jobs (no icon) for windows before any snapshot
        self._prewarm_serial = 0         # bumped by prewarm(): a yielded job of an older list is not re-queued
        self._request_ids = frozenset()  # the current snapshot's item ids (prewarm skips them)
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="NanoD-icons", daemon=True)
        self._thread.start()

    @staticmethod
    def _job_fields(item):
        path = item.get("path")
        path = path if isinstance(path, str) else ""
        try:
            hwnd = int(item.get("hwnd") or 0)
        except (TypeError, ValueError):
            hwnd = 0
        return hwnd, path, is_uwp_host(item.get("app"), path)

    def request(self, items):
        jobs, facts_jobs = [], []
        for position, item in enumerate(items or ()):
            hwnd, path, skip = self._job_fields(item)
            jobs.append((item.get("id"), hwnd, path, skip))
            if self._want_facts:
                facts_jobs.append(_facts_job(item, position, hwnd, path, skip))
        with self._condition:
            if self._closed:
                return self._generation
            self._generation += 1
            generation = self._generation
            self._jobs = deque((generation,) + job for job in jobs)
            self._results = []
            if self._want_facts:
                # This snapshot's windows get full facts jobs: warming them again is redundant.
                self._request_ids = frozenset(job[0] for job in jobs)
                self._prewarm_jobs = deque(job for job in self._prewarm_jobs if job["id"] not in self._request_ids)
            # The carousel opens on index 1 (the previous window): its neighbours first.
            anchor = 1 if len(facts_jobs) > 1 else 0
            facts_jobs.sort(key=lambda job: (abs(job["index"] - anchor), job["index"]))
            self._facts_jobs = deque((generation, job) for job in facts_jobs)
            self._facts_results = []
            meet = [(job["id"], job["pid"]) for job in facts_jobs if job["meet"]]
            self._audible_job = (generation, meet) if meet else None
            self._condition.notify()
            return generation

    def prioritize(self, index):
        """Carousel: order the snapshot's remaining facts jobs by distance from ``index``
        (the current selection). Nonblocking; changes no result already delivered."""
        try:
            index = int(index)
        except (TypeError, ValueError):
            return
        with self._condition:
            if self._facts_jobs:
                self._facts_jobs = deque(sorted(
                    self._facts_jobs, key=lambda entry: (abs(entry[1]["index"] - index), entry[1]["index"])))

    def prewarm(self, items):
        """Carousel: while the worker has nothing else to do, gather these windows' label facts
        (version strings, the packaged app's name, profile, monitor; the AppsFolder lookup takes
        9-77 ms per app) and warm the package-logo cache, so the first picker already names its
        apps. Each window's facts are delivered on the facts channel (poll_facts) under its item
        id, without an icon (the icon ladder needs the snapshot's 32 px icon, so it is left to
        the snapshot's own facts jobs). A window of the current snapshot is skipped (its facts
        job covers it). A no-op without ``facts``."""
        if not self._want_facts:
            return
        jobs = []
        for position, item in enumerate(items or ()):
            hwnd, path, skip = self._job_fields(item)
            jobs.append(_facts_job(item, position, hwnd, path, skip))
        with self._condition:
            if not self._closed:
                self._prewarm_serial += 1
                self._prewarm_jobs = deque(job for job in jobs if job["id"] not in self._request_ids)
                self._condition.notify()

    def poll(self):
        with self._condition:
            results, self._results = self._results, []
            return results

    def poll_facts(self):
        """Carousel: the [(item_id, facts)] that arrived since the last call (nonblocking; [] without
        ``facts``). ``facts`` is a partial dict, merged per key by the consumer: file_description,
        product_name, package_name, profile, monitor, icon (the 128 px RGBA master or None) and
        icon_source; later, for Meet titles only, audible. A prewarm delivery (prewarm()) has the
        label facts only, no icon keys. Never a path or a handle; nothing in it is mutated after
        hand-off."""
        with self._condition:
            results, self._facts_results = self._facts_results, []
            return results

    def close(self, timeout=None):
        with self._condition:
            self._closed = True
            self._generation += 1
            self._jobs.clear()
            self._results = []
            self._facts_jobs.clear()
            self._facts_results = []
            self._audible_job = None
            self._prewarm_jobs.clear()
            self._condition.notify()
        if timeout and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    def _entry(self, image, hires=None):
        from .artwork import attach_icon_payload, dominant_rgb
        if image is None:
            return None, None
        try:
            accent = dominant_rgb(image)
        except Exception:
            accent = None
        # artwork2: the knob's 2048-byte icon is built here, off the Tk thread.
        return attach_hires_icon(attach_icon_payload(icon_thumbnail(image)), hires), accent

    def _hires(self, api, path, source):
        """The 128 px copy of ``source`` (the icon the knob gets, or its 32 px thumbnail:
        both compare the same), or None. Never raises."""
        getter = getattr(api, "hires_icon", None)
        if getter is None or source is None or not path:
            return None
        key = path.lower()
        if key in self._hires_cache:
            self._hires_cache.move_to_end(key)
            cached = self._hires_cache[key]
        else:
            try:
                pair = getter(path)
                cached = (icon_thumbnail(pair[0], ICON_HIRES_SIZE), pair[1]) if pair else None
            except Exception:
                cached = None
            self._hires_cache[key] = cached
            while len(self._hires_cache) > self._cache_size:
                self._hires_cache.popitem(last=False)
        try:
            return cached[0] if cached is not None and icon_matches(source, cached[1]) else None
        except Exception:
            return None

    def _lookup(self, api, hwnd, path, hwnd_cache):
        if hwnd and hwnd in hwnd_cache:
            return hwnd_cache[hwnd]
        image = window_icon_image(api, hwnd) if hwnd else None
        if image is not None:
            entry = self._entry(image)
        else:
            key = path.lower()
            if key and key in self._exe_cache:
                self._exe_cache.move_to_end(key)
                entry = self._exe_cache[key]
            else:
                source = fallback_icon_image(api, hwnd, path)
                entry = self._entry(source)
                if key:
                    self._exe_cache[key] = entry
                    while len(self._exe_cache) > self._cache_size:
                        self._exe_cache.popitem(last=False)
        if hwnd:
            hwnd_cache[hwnd] = entry
        return entry

    def _run(self):
        api, com = None, False
        try:
            try:
                api = self._api_factory()
                com = bool(api.co_initialize())
            except Exception:
                api = None  # Icons are optional: every item reports (id, None, None).
            hwnd_cache, cache_generation = {}, None
            icons = {}        # worker thread only: item id -> this snapshot's 32 px icon (facts ladder)
            wants_hires = self._want_hires and api is not None and getattr(api, "hires_icon", None) is not None
            later = deque()   # worker thread only: hi-res copies, after every 32 px icon
            while True:
                with self._condition:
                    while (not self._closed and not self._jobs and not later and not self._facts_jobs
                           and self._audible_job is None and not self._prewarm_jobs):
                        self._condition.wait()
                    if self._closed:
                        return
                    current = self._generation
                    # The knob first: its 32 px icons, then the floating knob's copies; then the
                    # carousel's facts, the Meet audio check, and cache warming last.
                    kind, job = "icon", None
                    if self._jobs:
                        job = self._jobs.popleft()
                    elif later:
                        kind, job = "hires", later.popleft()
                    elif self._facts_jobs:
                        kind, job = "facts", self._facts_jobs.popleft()
                    elif self._audible_job is not None:
                        kind, job, self._audible_job = "audible", self._audible_job, None
                    else:
                        kind, job = "prewarm", (self._prewarm_serial, self._prewarm_jobs.popleft())
                if kind == "hires":
                    self._deliver_hires(api, job, current)
                    continue
                if kind == "facts":
                    generation, entry = job
                    icon = icons.get(entry["id"]) if generation == cache_generation else None
                    self._deliver_facts(api, generation, entry, icon)
                    continue
                if kind == "audible":
                    self._deliver_audible(*job)
                    continue
                if kind == "prewarm":
                    self._deliver_prewarm(api, *job)
                    continue
                generation, item_id, hwnd, path, skip = job
                if generation != cache_generation:
                    hwnd_cache, cache_generation = {}, generation  # hwnds are per snapshot
                    icons = {}
                try:
                    icon, accent = (None, None) if skip or api is None else \
                        self._lookup(api, hwnd, path, hwnd_cache)
                except Exception:
                    icon, accent = None, None
                icons[item_id] = icon
                with self._condition:
                    if generation == self._generation and not self._closed:
                        self._results.append((item_id, icon.copy() if icon is not None else None, accent))
                if wants_hires and icon is not None and path:
                    later.append((generation, item_id, path, icon, accent))
        finally:
            if com:
                try:
                    api.co_uninitialize()
                except Exception:
                    pass

    def _deliver_hires(self, api, job, current):
        """One deferred hi-res copy: a HiresIcon result when the exe has a matching big
        icon. A superseded snapshot's copy is dropped unmade. The cached 32 px icon is
        never modified: the copy rides on a fresh copy of it."""
        generation, item_id, path, icon, accent = job
        if generation != current:
            return
        try:
            big = self._hires(api, path, icon)
            update = HiresIcon(item_id, attach_hires_icon(icon.copy(), big), accent) if big is not None else None
        except Exception:
            update = None
        if update is None:
            return
        with self._condition:
            if generation == self._generation and not self._closed:
                self._results.append(update)

    # ------------------------------------------------------------ carousel facts
    def _facts_module(self):
        """window_facts (or the injected stand-in), or None when it cannot be imported. Worker thread."""
        if self._facts_api is None:
            try:
                self._facts_api = _window_facts()
            except Exception:
                self._facts_api = False
        return self._facts_api or None

    def _cached(self, cache, key, make):
        """cache[key], else make(); an answer is kept (LRU), a None is not (asked again next time)."""
        if key in cache:
            cache.move_to_end(key)
            return cache[key]
        value = make()
        if value is None:
            return None
        cache[key] = value
        while len(cache) > self._cache_size:
            cache.popitem(last=False)
        return value

    def _give_way(self, generation=None):
        """Between two helper calls of a facts job (``generation``: its snapshot's) or of a prewarm
        job (None): raise _Superseded when the job must stop for newer work. A facts job stops
        when the worker closes or a newer request replaced its snapshot (its 32 px icons are
        waiting); a prewarm job, the lowest priority, also for any queued snapshot work (icons,
        facts, the Meet check). Worker thread; one uncontended lock, never a wait."""
        with self._condition:
            if self._closed:
                raise _Superseded
            if generation is None:
                if self._jobs or self._facts_jobs or self._audible_job is not None:
                    raise _Superseded
            elif generation != self._generation or self._jobs:
                raise _Superseded

    def _deliver_facts(self, api, generation, job, icon):
        """One window's facts; a superseded snapshot's job is dropped unmade, also midway (at the
        next _give_way). Never raises."""
        with self._condition:
            if generation != self._generation or self._closed:
                return
        try:
            facts = self._facts_for(api, job, icon, check=lambda: self._give_way(generation))
        except _Superseded:
            return
        except Exception:
            facts = {"icon": None, "icon_source": None}
        with self._condition:
            if generation == self._generation and not self._closed:
                self._facts_results.append((job["id"], facts))

    def _deliver_prewarm(self, api, serial, job):
        """One prewarm job: the window's label facts, delivered without an icon unless a snapshot
        has taken the window over meanwhile (its own facts job then answers). A job that gives way
        to snapshot work goes back to the front of the queue (unless a snapshot took its window
        over, or a newer prewarm() replaced the list); what it cached so far stays cached.
        Never raises."""
        try:
            facts = self._facts_for(api, job, None, ladder=False, check=self._give_way)
        except _Superseded:
            with self._condition:
                if (not self._closed and serial == self._prewarm_serial
                        and job["id"] not in self._request_ids):
                    self._prewarm_jobs.appendleft(job)
            return
        except Exception:
            return
        with self._condition:
            if facts and not self._closed and job["id"] not in self._request_ids:
                self._facts_results.append((job["id"], facts))

    def _facts_for(self, api, job, icon, ladder=True, check=None):
        """The label facts and the icon master of one window (CAROUSEL.md sections 6 and 7).
        ``ladder=False`` (prewarm): the label facts only, no icon keys; a packaged app's logo is
        still cached for the snapshot's ladder. ``check`` (_give_way) runs between the slow
        helper calls and may raise _Superseded."""
        check = check or _no_check
        fx = self._facts_module()
        path, hwnd = job["path"], job["hwnd"]
        facts = {}
        strings = _facts_call(fx, "version_strings", path) if path else None
        check()
        if isinstance(strings, dict):
            for key, name in (("file_description", "FileDescription"), ("product_name", "ProductName")):
                value = strings.get(name)
                if isinstance(value, str) and value.strip():
                    facts[key] = value.strip()
        store = _facts_call(fx, "window_property_store", hwnd) if hwnd else None
        store = store if isinstance(store, dict) else {}
        # The package's AUMID: the packaged process's own, or the package one ("<family>!<app>") a
        # UWP frame carries. A desktop app's explicit window AUMID (a browser profile's) names no
        # package, so it never selects a package name or logo.
        aumid = _facts_call(fx, "process_aumid", hwnd) if hwnd else None
        if isinstance(aumid, dict):
            aumid = aumid.get("aumid")
        if not aumid and job["uwp"] and "!" in str(store.get("aumid") or ""):
            aumid = store.get("aumid")
        aumid = aumid if isinstance(aumid, str) and aumid else None
        check()
        if aumid:
            name = self._cached(self._package_names, aumid,
                                lambda: _facts_call(fx, "package_display_name", aumid))
            if isinstance(name, str) and name.strip():
                facts["package_name"] = name.strip()
            check()
        profile = browser_profile(store.get("relaunch_display_name"))
        if profile:
            facts["profile"] = profile
        monitor = _facts_call(fx, "monitor_friendly_name", hwnd) if hwnd else None
        if isinstance(monitor, str) and monitor.strip():
            facts["monitor"] = monitor.strip()
        check()
        if not ladder:
            if aumid:
                self._cached(self._logos, aumid, lambda: _master(_facts_call(fx, "package_logo", aumid,
                                                                             ICON_MASTER_SIZE)))
            return facts
        facts["icon"], facts["icon_source"] = self._icon_master(api, fx, job, aumid, store.get("relaunch_icon"),
                                                                icon, facts, check)
        return facts

    def _icon_master(self, api, fx, job, aumid, relaunch, icon, facts, check=None):
        """(128 px RGBA master, ladder step) or (None, None). ``icon`` is the window's 32 px icon
        (the knob's): every source but the package logo must show the same picture. ``check``
        (_give_way) runs after each slow step that did not answer and may raise _Superseded."""
        check = check or _no_check
        size = ICON_MASTER_SIZE
        if aumid:
            logo = self._cached(self._logos, aumid, lambda: _master(_facts_call(fx, "package_logo", aumid, size)))
            if logo is not None:
                return logo, "package"
            check()
        if isinstance(relaunch, str) and relaunch and icon is not None:
            image = _master(_facts_call(fx, "relaunch_icon", relaunch, size))
            try:
                matches = image is not None and icon_matches(icon, image)
            except Exception:
                matches = False
            if matches:
                return image, "relaunch"
            check()
        if icon is not None and job["path"] and api is not None:
            big = self._hires(api, job["path"], icon)
            if big is not None:
                return big, "hires"
            check()
        if icon is not None:
            native = None
            if api is not None and job["hwnd"] and not job["uwp"]:
                try:
                    native = extract_icon(api, job["hwnd"], job["path"])
                except Exception:
                    native = None
                check()
            upscaled = _master(native if native is not None else icon)
            if upscaled is not None:
                return upscaled, "window"
        tile = _master(_facts_call(fx, "letter_tile", _display_name(job, facts), size))
        if tile is not None:
            return tile, "letter"
        return None, None

    def _deliver_audible(self, generation, members):
        """Meet titles: "In a call" only when Core Audio finds the browser's session active; an
        unanswered check delivers nothing (the label keeps "Meeting")."""
        with self._condition:
            if generation != self._generation or self._closed:
                return
        pids = _facts_call(self._facts_module(), "audible_pids")
        if pids is None:
            return
        try:
            pids = set(pids)
        except TypeError:
            return
        with self._condition:
            if generation == self._generation and not self._closed:
                self._facts_results.extend((item_id, {"audible": pid in pids}) for item_id, pid in members)


def _facts_job(item, position, hwnd, path, uwp):
    """What a facts job reads of a snapshot item. The title only decides the Meet check."""
    try:
        pid = int(item.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    return {"id": item.get("id"), "index": position, "hwnd": hwnd, "pid": pid, "path": path,
            "app": str(item.get("app") or ""), "class_name": str(item.get("class_name") or ""),
            "uwp": bool(uwp), "meet": meet_call(item)}


class _Superseded(Exception):
    """IconWorker: a facts or prewarm job gives way to newer work (IconWorker._give_way)."""


def _no_check():
    """The default ``check`` of IconWorker._facts_for: never gives way."""


def _facts_call(module, name, *args):
    """module.name(*args), or None when the helper is missing or fails (a fact is optional)."""
    function = getattr(module, name, None) if module else None
    if function is None:
        return None
    try:
        return function(*args)
    except Exception:
        return None


def _master(image, size=ICON_MASTER_SIZE):
    """A size x size RGBA copy of a PIL image (LANCZOS, aspect kept), or None."""
    if image is None or not hasattr(image, "convert"):
        return None
    try:
        return icon_thumbnail(image, size)
    except Exception:
        return None


def _display_name(job, facts):
    """The app's display name for a letter tile (window_labels.app_display_name)."""
    try:
        return _window_labels().app_display_name(
            window_exe(job), package_name=facts.get("package_name") or "",
            file_description=facts.get("file_description") or "", product_name=facts.get("product_name") or "")
    except Exception:
        return str(job.get("app") or "") or "Application"


def PickerOverlay(root, native, on_cancel):  # noqa: N802 - the module-global presenter factory
    """The Windows picker's presenter: the carousel (control_center.carousel.CarouselPresenter).

    WindowsAdapter builds it here, where it built the Tk grid overlay before desktop v6, and
    tests patch this name (CAROUSEL.md section 1). The protocol: hwnd, show(snapshot),
    focus_local(), highlight(index[, bump]), set_icons(dict), hide(), close() and ``rect`` (its
    stage's card area while open: the UI's 'carousel' suppression, section 11); plus
    set_labels(dict), set_background(value), set_reduced_motion(on), take_events(),
    play_switch_exit(), play_cancel_exit(), play_pair_exit() and the v7 calls snap(effect),
    complete_one_side(origin, side, rect), raise_window(hwnd), half_rect(side), toast(text,
    exit=) and end_toast(). The adapter treats every one of the additions as optional."""
    from .carousel import CarouselPresenter
    return CarouselPresenter(root, native, on_cancel)


class WindowsAdapter:
    """UI-thread adapter. F24 is disabled until explicitly enabled.

    on_focus_lost means the user chose another application: the overlay has
    already hidden and the controller must not restore origin focus.
    on_closed (optional) notifies that snapshot entries became unavailable.
    on_switch / on_turn (optional): the presenter's own input, drained by pump():
    Enter or a click on the centre card is Switch (the knob's green button path,
    controller.button(3)); Esc is Cancel (on_cancel, the red button's path); arrows and
    the wheel are turns, forwarded only to on_turn (a test/simulator path: a host-side
    turn would desync the knob's absolute detent, CAROUSEL.md section 9).

    Native events (see the module docstring): foreground changes are queued by
    the WinEvent hook and handled by pump(), which the UI tick calls (and _poll
    as a backstop); an external foreground change while the picker is open is
    re-checked FOCUS_SETTLE_SECONDS later and dismisses it. F24 runs on_hotkey
    synchronously through TclInvoker when that is safe, else on the next pump().

    Carousel labels (CAROUSEL.md section 6) are computed here, on the Tk thread, from
    the snapshot and the facts the IconWorker delivered (set_window_facts), with
    duplicates disambiguated per snapshot and closed windows marked; they reach the
    presenter through set_labels. On open that is after focus, never inside it: show()
    pushes the first labels once native.focus() has returned (still within the WM_HOTKEY
    handler), from the facts known so far minus the last snapshot's Meet answers.
    """

    def __init__(self, rootTk, on_hotkey, on_cancel, on_focus_lost, on_closed=None, *,
                 on_switch=None, on_turn=None):
        self.root = rootTk
        self._thread = threading.get_ident()
        self._closed = False
        self._visible = False
        self._changing_focus = False
        self._snapshot = None
        self._mru = deque(maxlen=512)
        self._last_external = None
        self._poll_id = None
        self._foreground_events = deque(maxlen=FOREGROUND_EVENT_LIMIT)
        self._focus_due = None       # monotonic time of the pending focus-loss check
        self._hotkey_pending = False
        self._invoker = None
        # Carousel presentation state (Tk thread).
        self._facts = {}             # window item id -> facts (IconWorker.poll_facts, merged)
        self._labels = {}            # window item id -> the label last handed to the presenter
        self._app_names = {}         # exe stem -> display name, until a window's own facts arrive
        self._background = DEFAULT_PICKER_BACKGROUND
        self._labels_failed = False
        self._today = date.today
        # v7 (K4 sections 2.3, 9, 10): the K4 events for the runtime, the overlay registry the
        # toast service reads, the pending one-side completion and the lifetime close reason.
        self._events = []
        self._registry = None
        self._registry_busy = False
        self._reduced_motion = None
        self._cancel_job = None
        self._closing = False
        self._lifetime_reason = None
        self._last_input = None      # monotonic time of the last knob-driven call (idle inference)
        self.on_hotkey, self.on_cancel = on_hotkey, on_cancel
        self.on_focus_lost, self.on_closed = on_focus_lost, on_closed
        self.on_switch, self.on_turn = on_switch, on_turn
        self.native = NativeWindows()
        self.overlay = None
        try:
            self.root.update_idletasks()
            self._owner = self.native.root_handle(self.root.winfo_id())
            self.overlay = PickerOverlay(self.root, self.native, lambda: self._call(self.on_cancel))
            self._invoker = _make_invoker(self.root, self._run_hotkey)
            self.native.attach_hotkey(self._owner, self._hotkey_message,
                                      self.root.report_callback_exception)
            self.native.watch(self._foreground_event, self._destroy_event)
            current = self.native.foreground()
            if current:
                self._remember(current)
            self._poll_id = self.root.after(350, self._poll)
        except Exception:
            if self._invoker is not None:
                self._invoker.close()
            if self.overlay:
                self.overlay.close()
            self.native.close()
            raise

    def _check_thread(self):
        if threading.get_ident() != self._thread:
            raise RuntimeError("WindowsAdapter must be called on its Tk UI thread.")
        if self._closed:
            raise RuntimeError("WindowsAdapter is closed.")

    def _call(self, callback):
        if callback and not self._closed:
            try:
                callback()
            except BaseException:
                self.root.report_callback_exception(*sys.exc_info())

    def _remember(self, identity):
        if identity and identity["pid"] != self.native.own_pid:
            self._last_external = dict(identity)
            if identity["id"] in self._mru:
                self._mru.remove(identity["id"])
            self._mru.appendleft(identity["id"])

    # -------------------------------------------------- native callbacks
    # These two run inside ctypes callbacks. They record and return: no tkinter,
    # no adapter state beyond plain Python attributes.
    def _hotkey_message(self, event_loop=False):
        """WM_HOTKEY (F24) from the subclassed window procedure."""
        if self._closed:
            return
        if event_loop and self._invoker is not None and self._invoker():
            return  # ran synchronously, under the hotkey's foreground grant
        self._hotkey_pending = True

    def _foreground_event(self, hwnd):
        """EVENT_SYSTEM_FOREGROUND: queued for pump()."""
        if not self._closed:
            self._foreground_events.append(hwnd)

    def _destroy_event(self, _hwnd):
        # Availability polling intentionally leaves the order and labels frozen.
        pass

    # ------------------------------------------------------- Tk thread
    def _run_hotkey(self):
        """The F24 action (a Tcl command when run by TclInvoker)."""
        self._hotkey_pending = False
        self._call(self.on_hotkey)

    def pump(self):
        """Handle what the native callbacks and the presenter recorded. Tk thread only (the UI tick)."""
        if self._closed or threading.get_ident() != self._thread:
            return
        self._drain_foreground()
        if self._hotkey_pending:
            self._hotkey_pending = False
            if getattr(self.native, "hotkey_enabled", True):
                self._call(self.on_hotkey)
        self._drain_presenter()
        if self._focus_due is not None and time.monotonic() >= self._focus_due:
            self._check_focus_lost()
        pending = self._cancel_job
        if pending is not None and time.monotonic() - pending["started"] >= CANCEL_RESULT_BACKSTOP_SECONDS:
            _log.warning("No one-side completion result: the picker closes without it")
            self._finish_cancel(False)
        # K4 10.4: an overlay that opens ends a showing toast at once.
        busy = bool(self._open_overlays() - {"picker"})
        if busy and not self._registry_busy:
            end = getattr(self.overlay, "end_toast", None)
            if callable(end):
                try:
                    end()
                except Exception:
                    pass
        self._registry_busy = busy

    def _drain_foreground(self):
        while self._foreground_events and not self._closed:
            hwnd = self._foreground_events.popleft()
            try:
                identity = self.native.identity(self.native.root_handle(hwnd))
            except Exception:
                continue  # the window vanished while queued
            self._remember(identity)
            foreign = identity is None or identity["pid"] != self.native.own_pid
            if self._visible and not self._changing_focus and foreign and self._focus_due is None:
                # (identity None: a window we cannot identify, e.g. the lock screen's)
                self._focus_due = time.monotonic() + FOCUS_SETTLE_SECONDS

    def _take_presenter_events(self):
        """The presenter's queued input (its native thread records it), or [] (never raises)."""
        take = getattr(self.overlay, "take_events", None) if self.overlay is not None else None
        if take is None:
            return []
        try:
            return list(take() or ())
        except Exception:
            return []

    def _drain_presenter(self):
        """Presenter input and results, on the Tk thread (the _hotkey_pending pattern): Switch
        runs the green button's path (on_switch), Cancel the red button's (on_cancel), a turn
        goes to on_turn only; input of a dismissed (or closing) picker is dropped. Results become
        K4 events for the runtime (take_events): snap results, the one-side completion (which
        finishes a pending cancel), a display close and a suspend."""
        for event in self._take_presenter_events():
            if self._closed:
                return
            try:
                kind, payload = event
            except (TypeError, ValueError):
                continue
            if self._result_event(kind, payload):
                continue
            if not self._visible or self._closing:
                continue
            if kind == "switch":
                # A centre-card click names the card it hit: stale if the knob moved meanwhile.
                if type(payload) is int and self._snapshot and payload != self._snapshot.get("index"):
                    continue
                self._call(self.on_switch)
            elif kind == "cancel":
                self._call(self.on_cancel)
            elif kind == "turn":
                if self.on_turn is not None and type(payload) is int and payload:
                    self._call(lambda delta=payload: self.on_turn(delta))

    def _result_event(self, kind, payload):
        """A presenter result (not input): True when handled."""
        if kind == "snap_result":
            try:
                side, outcome = payload
            except (TypeError, ValueError):
                return True
            self._events.append({"kind": "snap_result", "side": side, "outcome": outcome})
            return True
        if kind == "complete_result":
            try:
                job, completed = payload
            except (TypeError, ValueError):
                return True
            pending = self._cancel_job
            if pending is not None and pending["job"] == job:
                self._finish_cancel(bool(completed))
            return True
        if kind == "closed":
            if self._visible and payload == "display":
                self._visible = False
                self._focus_due = None
                self._events.append({"kind": "closed", "surface": "picker", "reason": "display"})
            return True
        if kind == "system":
            if payload in ("sleep", "lock"):
                self._lifetime_reason = payload
                if self._visible:
                    self._visible = False
                    self._focus_due = None
                    self._events.append({"kind": "closed", "surface": "picker", "reason": payload})
                self._events.append({"kind": "system", "what": payload})
            return True
        return False

    def _input_desktop_default(self):
        check = getattr(self.native, "input_desktop_is_default", None)
        if check is None:
            return True
        try:
            return bool(check())
        except Exception:
            return True

    def _check_focus_lost(self):
        self._focus_due = None
        if self._closed or not self._visible or self._changing_focus or self._closing:
            return
        if not self._input_desktop_default():
            # K4 15: the session was locked (or a secure desktop took the input): the close is
            # ``lock``, instant; the controller then asks for the U12 completion without a focus
            # restore (cancel(), reason lock).
            self._lifetime_reason = "lock"
            self.hide(reason="lock")
            self._events.append({"kind": "system", "what": "lock"})
            return
        foreground = self.native.foreground()
        if foreground and foreground["pid"] != self.native.own_pid:
            self.hide(reason="focus_lost")
            self._call(self.on_focus_lost)

    def _refresh_availability(self):
        changed = False
        if self._snapshot:
            for item in self._snapshot["items"]:
                if item["available"] and not same_identity(item, self.native.identity(item["hwnd"])):
                    item["available"] = False
                    changed = True
        return changed

    def _poll(self):
        self._poll_id = None
        if self._closed:
            return
        try:
            self.pump()  # backstop when the UI tick is not pumping
            if self._visible:
                if self._refresh_availability():
                    self.overlay.highlight(self._snapshot["index"])
                    self._push_labels()
                    self._call(self.on_closed)
                self._check_focus_lost()
        finally:
            if not self._closed:
                self._poll_id = self.root.after(350, self._poll)

    def snapshot(self):
        self._check_thread()
        self._drain_foreground()  # the MRU order includes every change seen so far
        foreground = self.native.foreground()
        if foreground and foreground["pid"] == self.native.own_pid:
            foreground = self._last_external
        self._remember(foreground)
        return make_snapshot(self.native.records(), foreground, list(self._mru), self.native.own_pid)

    def show(self, snapshotdict):
        """Open the picker on ``snapshotdict`` (usually inside the WM_HOTKEY grant). Bounded,
        worst case: the presenter's show() handshake (at most 150 ms) plus native.focus()'s
        verify (at most FOCUS_VERIFY_SECONDS), then the first labels. When focus is not
        granted the picker hides and OSError propagates; the origin is not re-focused here
        (SetForegroundWindow may already have handed the foreground to the carousel thread,
        and Windows activates another window when the hidden host gives it up)."""
        self._check_thread()
        self._note_input()
        if self._visible:
            return  # Opening Windows again never overwrites the saved origin.
        self._snapshot = snapshotdict
        count = len(snapshotdict["items"])
        snapshotdict["index"] = max(0, min(int(snapshotdict.get("index", 0)), count - 1))
        self._refresh_availability()
        self._take_presenter_events()  # input left over from an earlier picker is stale
        self._changing_focus = True
        try:
            try:
                self.overlay.show(snapshotdict)
            except Exception:
                # A presenter that could not come up in time (its bounded handshake) is
                # dismissed like one that was denied focus.
                try:
                    self.overlay.hide()
                except Exception:
                    pass
                raise
            granted = self.native.focus(self.overlay.hwnd)
            self._log_focus("open", granted)
            if not granted:
                self.overlay.hide()
                raise OSError("Windows did not grant focus to the picker. Open it with the registered F24 key.")
            self.overlay.focus_local()
            self._visible = True
            self._closing = False
            self._lifetime_reason = None
            self._events.append({"kind": "opened", "surface": "picker"})
        finally:
            self._changing_focus = False
        # A Meet window's "audible" answer belongs to the snapshot that asked: this one reads
        # "Meeting" until its own Core Audio check answers (CAROUSEL.md section 6). The runtime
        # forgets its copy only on its next tick, after these first labels.
        self._facts = {key: {name: value for name, value in facts.items() if name != "audible"}
                       for key, facts in self._facts.items() if isinstance(facts, dict)}
        # After focus, never inside it: the labels from the snapshot and the facts known so far.
        self._push_labels()

    def highlight(self, index, bump=0):
        """``windows_highlight{index, control_id, bump}``: a new highlight, and the end bump when
        K3 sends ``bump`` (the knob's ``lim`` at an end, K4 9.8)."""
        self._check_thread()
        self._note_input()
        if not self._snapshot:
            return
        count = len(self._snapshot["items"])
        index = max(0, min(int(index), count - 1))
        self._snapshot["index"] = index
        changed = self._refresh_availability()
        if self._visible and not self._closing:
            bump = 1 if (bump or 0) > 0 else -1 if (bump or 0) < 0 else 0
            if bump:
                try:
                    self.overlay.highlight(index, bump=bump)
                except TypeError:
                    self.overlay.highlight(index)
            else:
                self.overlay.highlight(index)
            if changed:
                self._push_labels()

    def activate(self, item):
        self._check_thread()
        self._note_input()
        foreground = self.native.foreground()
        if self._visible and foreground and foreground["pid"] != self.native.own_pid:
            # The user may have left the picker before the next event/poll ran.
            self.hide()
            self._call(self.on_focus_lost)
            return False
        if not same_identity(item, self.native.identity(item.get("hwnd", 0))):
            item["available"] = False
            if self._visible:
                self.overlay.highlight(self._snapshot["index"])
                self._push_labels()
            return False
        shown = self._visible   # only a picker on screen plays an exit (never a stale toast)
        self._changing_focus = True
        try:
            granted = self.native.focus(item["hwnd"], restore=True)
            self._log_focus("switch", granted)
            success = granted and same_identity(item, self.native.foreground())
            if success:
                # Focus has moved and is verified: the Switch visual is an exit animation. v7: the
                # picker raises no toast of its own; K3 sends toast.switch through toast() at +360.
                if shown:
                    self._play_exit("play_switch_exit", self._toast_text(item))
                self.hide(reason="switch")
            return success
        finally:
            self._changing_focus = False

    def cancel(self, origin, complete=None, reason=None):
        """``windows_cancel{origin, home, complete}`` (K3 5.7.4; K4 9.7): Back, hold and the
        lifetime closes lock, sleep and idle. ``reason`` (when the runtime passes it; else the
        lifetime reason this adapter saw, else ``back``): lock and sleep never restore focus;
        lock, sleep and idle hide at once; back and hold play the exit. With ``complete`` (a
        side), the origin first takes that half with the non-activating recipe on NanoD-snap
        (complete_one_side, <= 600 ms); the answer is the event ``cancel_result(restored,
        completed)`` (take_events), never a toast of the picker's own. Returns ``restored`` for
        the v6 callers (None while a completion is still running).

        Without a ``reason`` (K3's payload has none, WP7b-D6): the lifetime reason this adapter
        saw itself (lock, sleep), else ``idle`` when IDLE_INFER_SECONDS have passed since the
        last knob-driven call (K3's 60 s idle close; K4 9.7 and 15: instant), else ``back``."""
        self._check_thread()
        if reason not in LIFETIME_REASONS:
            reason = self._lifetime_reason or ("idle" if self._idle_elapsed() else "back")
        self._lifetime_reason = None
        if not self._input_desktop_default():
            reason = "lock"
        foreground = self.native.foreground()
        if (reason in ("back", "hold") and self._visible and foreground
                and foreground["pid"] != self.native.own_pid):
            self.hide(reason="focus_lost")
            self._events.append({"kind": "cancel_result", "restored": False, "completed": False})
            return False  # Never overwrite a user-chosen app in the focus-loss race.
        origin = origin if isinstance(origin, dict) else {}
        valid = bool(origin) and same_identity(origin, self.native.identity(origin.get("hwnd", 0)))
        shown = self._visible
        start = getattr(self.overlay, "complete_one_side", None)
        if complete in SIDES and valid and callable(start):
            identity = dict(origin)
            for item in (self._snapshot or {}).get("items", ()):
                if item.get("hwnd") == origin.get("hwnd"):
                    identity.setdefault("class_name", item.get("class_name"))
                    identity.setdefault("exstyle", item.get("exstyle"))
            restore = reason not in ("lock", "sleep")
            if reason == "idle" and restore:
                self._restore_focus(origin)            # while this process still owns the foreground
                restore = False
            if reason in ("lock", "sleep", "idle") or not shown:
                self.hide(reason=reason)               # instant (K4 15); the completion follows
                shown = False
            else:
                self._closing = True                   # the picker stays up, passive, under the moves
            job = start(identity, complete, self.half_rect(complete))
            self._cancel_job = {"job": job, "origin": origin, "reason": reason, "shown": shown,
                                "restore": restore, "started": time.monotonic()}
            return None
        restored = False
        if valid and reason not in ("lock", "sleep"):
            restored = self._restore_focus(origin)
        if shown and reason in ("back", "hold"):
            self._play_exit("play_cancel_exit")        # no toast in v7 (R:152)
        self.hide(reason=reason)
        self._events.append({"kind": "cancel_result", "restored": bool(restored), "completed": False})
        return restored

    def _note_input(self):
        self._last_input = time.monotonic()

    def _idle_elapsed(self):
        """True when no knob-driven call came for IDLE_INFER_SECONDS (see cancel())."""
        return self._last_input is not None and time.monotonic() - self._last_input >= IDLE_INFER_SECONDS

    def _restore_focus(self, origin):
        self._changing_focus = True
        try:
            granted = self.native.focus(origin["hwnd"], restore=True)
            self._log_focus("cancel", granted)
            return bool(granted and same_identity(origin, self.native.foreground()))
        finally:
            self._changing_focus = False

    def _finish_cancel(self, completed):
        """The one-side completion answered (or its bound passed): focus the origin (back / hold),
        the exit, then ``cancel_result(restored, completed)``."""
        pending, self._cancel_job = self._cancel_job, None
        if pending is None:
            return
        restored = False
        origin = pending["origin"]
        if pending["restore"] and same_identity(origin, self.native.identity(origin.get("hwnd", 0))):
            restored = self._restore_focus(origin)
        elif pending["reason"] == "idle":
            restored = same_identity(origin, self.native.foreground())
        if pending["shown"] and self._visible:
            self._play_exit("play_cancel_exit")
            self.hide(reason=pending["reason"])
        self._closing = False
        self._events.append({"kind": "cancel_result", "restored": bool(restored), "completed": bool(completed)})

    # ------------------------------------------------------------- snap (K4 9.5-9.7)
    def snap(self, effect):
        """``windows_snap{t0, index, side, target_rect, place_at_ms, item}``: posted to the
        presenter (its pre-checks and placement run on NanoD-snap); the answers are
        ``snap_result`` events. Never blocks. A presenter without snap answers move_rejected."""
        self._check_thread()
        self._note_input()
        effect = dict(effect or {})
        snap = getattr(self.overlay, "snap", None)
        if not callable(snap) or not self._visible or self._closing:
            self._events.append({"kind": "snap_result", "side": effect.get("side"), "outcome": "move_rejected"})
            return False
        index = effect.get("index")
        items = (self._snapshot or {}).get("items") or []
        if isinstance(index, int) and 0 <= index < len(items):
            item = dict(items[index])
            if isinstance(effect.get("item"), dict):
                item.update({k: v for k, v in effect["item"].items() if k in ("id", "hwnd", "pid")})
            effect["item"] = {key: item.get(key) for key in ("id", "hwnd", "pid", "class_name", "exstyle", "available")}
        if effect.get("target_rect") is None:
            effect["target_rect"] = self.half_rect(effect.get("side"))
        try:
            snap(effect)
        except Exception as exc:
            _log.warning("Snap not posted (%s)", type(exc).__name__)
            self._events.append({"kind": "snap_result", "side": effect.get("side"), "outcome": "move_rejected"})
            return False
        return True

    def half_rect(self, side):
        """The picker monitor's rcWork half for ``side`` (K3's ``target_rect``), or None."""
        getter = getattr(self.overlay, "half_rect", None)
        if not callable(getter) or side not in SIDES:
            return None
        try:
            return getter(side)
        except Exception:
            return None

    def close_pair(self, left, right, focus):
        """``windows_close_pair{left, right, focus}`` at 820 ms (K4 9.7): the side snapped first
        is raised with a posted SetWindowPos(HWND_TOP) on NanoD-snap, the side snapped last
        (``focus``) takes the foreground through the v6 focus path, then the exit. Nothing waits
        on either window beyond the bounded focus verify."""
        self._check_thread()
        items = {item.get("id"): item for item in (self._snapshot or {}).get("items", ())}
        last_id, first_id = (left, right) if focus == "left" else (right, left)
        first, last = items.get(first_id), items.get(last_id)
        raise_window = getattr(self.overlay, "raise_window", None)
        if first is not None and callable(raise_window):
            try:
                raise_window(first.get("hwnd"))
            except Exception:
                pass
        granted = False
        shown = self._visible
        if last is not None and same_identity(last, self.native.identity(last.get("hwnd", 0))):
            self._changing_focus = True
            try:
                granted = self.native.focus(last["hwnd"])
                self._log_focus("pair", granted)
            finally:
                self._changing_focus = False
        if shown:
            self._play_exit("play_pair_exit")
        self.hide(reason="pair")
        return bool(granted)

    def foreground_hwnd(self):
        """The foreground window at the press (the stage's monitor choice, K4 0.3), or None."""
        if self._closed:
            return None
        try:
            foreground = self.native.foreground()
        except Exception:
            return None
        return int(foreground["hwnd"]) if foreground else None

    def take_events(self):
        """The K4 events for the runtime (dicts, oldest first). Tk thread."""
        events, self._events = self._events, []
        return events

    # ------------------------------------------------------------- the toast service (K4 10)
    def set_overlay_registry(self, provider):
        """``provider()`` -> the open overlay surfaces (the runtime's ``open_surfaces``, K4 2.4):
        toasts read it, and an overlay that opens ends a showing toast."""
        self._registry = provider if callable(provider) else None

    def _open_overlays(self):
        surfaces = set()
        if self._registry is not None:
            try:
                surfaces = set(self._registry() or ())
            except Exception:
                surfaces = set()
        if self._visible or self._closing:
            surfaces.add("picker")
        return surfaces

    def toast(self, text, exit=False):
        """K4 10.3 / K3 12.1: ``exit=False`` toasts are dropped while any overlay is open; an exit
        toast only when another overlay than the picker is open (the picker's own exit toast
        waits for the end of its exit on the presenter). Never blocks."""
        if self._closed:
            return False
        show = getattr(self.overlay, "toast", None)
        if not callable(show):
            return False
        surfaces = self._open_overlays()
        if (surfaces - {"picker"}) if exit else surfaces:
            return False
        try:
            return bool(show(text, exit=bool(exit)))
        except Exception as exc:
            _log.warning("Toast not shown (%s)", type(exc).__name__)
            return False

    def set_reduced_motion(self, on):
        """The effective Motion setting (K3 14.3): latched by the picker at its next open."""
        self._reduced_motion = None if on is None else bool(on)
        setter = getattr(self.overlay, "set_reduced_motion", None)
        if callable(setter):
            try:
                setter(self._reduced_motion)
            except Exception:
                pass

    def note_touch(self):
        """A knob touch (K4 4.2, AR-19; CAROUSEL.md 12.4): the picker's GPU chrome creates its device
        while nothing is open, so an open never waits for it. Posted to the carousel thread, whose
        worker makes the slow half (a show() right after answers its handshake at once); never
        blocks and never raises; False without a GPU chrome."""
        if self._closed:
            return False
        warm = getattr(self.overlay, "note_touch", None)
        if not callable(warm):
            return False
        try:
            return bool(warm())
        except Exception:
            return False

    def set_chrome_mode(self, mode):
        """'auto' (the GPU chrome when it is installed and able) or 'cpu' (the step-1 chrome), from the
        next open (CAROUSEL.md 12.4; a support switch: Settings has no such choice)."""
        setter = getattr(self.overlay, "set_chrome_mode", None)
        if not callable(setter):
            return None
        try:
            return setter(mode)
        except Exception:
            return None

    def _log_focus(self, what, granted):
        """One line per picker focus change (open, switch, cancel) with its timing, so the
        supervised check can confirm the cross-thread activation settles. Never a title or a
        handle; a native layer without ``last_focus`` (test stand-ins) logs nothing."""
        stats = getattr(self.native, "last_focus", None)
        try:
            _, ms, checks = stats
            _log.info("Picker %s focus %s after %.1f ms (%d checks)", what,
                      "granted" if granted else "NOT granted", float(ms), int(checks))
        except Exception:
            pass

    def hide(self, reason=None):
        """Dismiss without any focus action (instant unless an exit was just requested).
        Idempotent, also after close(). Posts ``closed(picker, reason)`` when it was open."""
        if self._closed:
            return
        self._check_thread()
        was = self._visible
        self._visible = False
        self._focus_due = None
        self.overlay.hide()
        if was:
            self._events.append({"kind": "closed", "surface": "picker", "reason": reason or "hide"})

    def set_hotkey_enabled(self, enabled):
        self._check_thread()
        self.native.hotkey(bool(enabled))

    # ------------------------------------------------- carousel presentation
    def set_picker_background(self, value):
        """Settings "Switcher background": "glass" (Frosted, the default) or "none" (No
        background); anything else is "glass". Applied to the presenter at once. Tk thread."""
        if self._closed:
            return
        self._check_thread()
        self._background = value if value in PICKER_BACKGROUNDS else DEFAULT_PICKER_BACKGROUND
        setter = getattr(self.overlay, "set_background", None)
        if setter is not None:
            try:
                setter(self._background)
            except Exception:
                pass  # presentation only: the next open keeps the previous look

    @property
    def picker_background(self):
        return self._background

    @property
    def picker_backgrounds(self):
        """The Switcher background values the picker can show right now: ("glass", "none"), or
        only ("glass",) while the carousel runs on its plain-host fallback, where "No background"
        is disabled and the picker is forced to glass (CAROUSEL.md section 5). Read from the
        presenter's ``host_mode`` (or its metrics()); never raises. Tk thread (Settings)."""
        overlay = self.overlay
        mode = None
        try:
            mode = getattr(overlay, "host_mode", None)
            if mode is None:
                metrics = getattr(overlay, "metrics", None)
                mode = metrics().get("host_mode") if callable(metrics) else None
        except Exception:
            mode = None
        return ("glass",) if mode == HOST_PLAIN_MODE else PICKER_BACKGROUNDS

    def set_window_facts(self, facts):
        """The facts per window item id (the runtime merges IconWorker.poll_facts); an open
        picker's labels follow at once. Tk thread."""
        if self._closed:
            return
        self._check_thread()
        self._facts = dict(facts or {})
        if self._visible:
            self._push_labels()

    def prewarm_items(self):
        """The eligible windows right now, as IconWorker.prewarm reads them (id, hwnd, pid,
        path, app, class_name): read-only, no snapshot, MRU or focus change. Tk thread."""
        self._check_thread()
        try:
            records = self.native.records()
        except Exception:
            return []
        return [{key: record.get(key) for key in ("id", "hwnd", "pid", "path", "app", "class_name")}
                for record in records if eligible(record, self.native.own_pid)]

    def _play_exit(self, name, *args):
        """The presenter's exit animation (after focus moved). Presentation only: a failure
        never changes the outcome of the switch or the cancel."""
        play = getattr(self.overlay, name, None)
        if play is None:
            return
        try:
            play(*args)
        except Exception:
            pass

    def _toast_text(self, item):
        """The Switch toast, "{App} · {Title}", from the label the picker showed for ``item``."""
        label = self._labels.get(item.get("id"))
        app = getattr(label, "app", "") or str(item.get("app") or "")
        title = getattr(label, "title", "") or str(item.get("title") or "")
        return app + LABEL_SEPARATOR + title if app and title else (app or title)

    def _push_labels(self):
        """Compute the snapshot's labels and hand them to the presenter (never raises). Each
        snapshot item also carries its display app name as ``label_app`` (K3 5.7.2: the knob's
        subtitle and the toasts' ``{App}``), since the controller copies the items after show()."""
        setter = getattr(self.overlay, "set_labels", None) if self.overlay is not None else None
        if setter is None or self._closed or not self._snapshot:
            return
        try:
            labels = self._compute_labels(self._snapshot["items"])
            self._labels = labels
            for item in self._snapshot["items"]:
                label = labels.get(item.get("id"))
                app = getattr(label, "app", "")
                if app:
                    item["label_app"] = app
            setter(dict(labels))
        except Exception as exc:
            if not self._labels_failed:
                self._labels_failed = True
                _log.warning("Picker labels unavailable (%s)", type(exc).__name__)

    def _compute_labels(self, items):
        """item id -> Label for the whole snapshot: label_for per window, duplicates
        disambiguated, closed windows marked "Closed · can't switch"."""
        labels_module = _window_labels()
        today = self._today()
        answers = [self._app_name(labels_module, item) for item in items]   # learns every answered exe first
        facts_list = [self._label_facts(labels_module, item, answer) for item, answer in zip(items, answers)]
        labels = []
        for facts in facts_list:
            try:
                labels.append(labels_module.label_for(facts, today))
            except Exception:
                labels.append(labels_module.Label(facts.app, facts.title or facts.app, facts.app))
        try:
            labels = list(labels_module.disambiguate(facts_list, labels))
        except Exception:
            pass
        result = {}
        for item, label in zip(items, labels):
            if not item.get("available", True):
                try:
                    label = labels_module.closed_label(label)
                except Exception:
                    pass
            result[item.get("id")] = label
        return result

    def _item_facts(self, item):
        facts = self._facts.get(item.get("id"))
        return facts if isinstance(facts, dict) else {}

    def _app_name(self, labels_module, item):
        """(display name, final) of one item: app_display_name of its delivered facts; ``final``
        is False while its facts are still out, when an exe another window already answered for
        lends its name instead (never for UWP frames, which host many apps)."""
        facts = self._item_facts(item)
        exe = window_exe(item)
        stem = PureWindowsPath(exe).stem.lower()
        path = item.get("path")
        uwp = is_uwp_host(item.get("app"), path if isinstance(path, str) else None)
        name = labels_module.app_display_name(
            exe, package_name=facts.get("package_name") or "", file_description=facts.get("file_description") or "",
            product_name=facts.get("product_name") or "")
        answered = any(facts.get(key) for key in ("package_name", "file_description", "product_name"))
        if answered and not uwp and stem:
            if len(self._app_names) >= 256:
                self._app_names.clear()
            self._app_names[stem] = name
        return name, bool(facts) or uwp or not stem

    def _label_facts(self, labels_module, item, answer):
        """window_labels.WindowFacts for one snapshot item, its delivered facts and its
        _app_name() answer."""
        facts = self._item_facts(item)
        name, final = answer
        if not final:
            stem = PureWindowsPath(window_exe(item)).stem.lower()
            name = self._app_names.get(stem, name)   # another window of the same exe answered already
        return labels_module.WindowFacts(
            exe=window_exe(item), app=name, title=str(item.get("title") or ""),
            class_name=str(item.get("class_name") or ""), minimized=bool(item.get("minimized")),
            audible=facts.get("audible"), profile=facts.get("profile"), monitor=facts.get("monitor"))

    def close(self):
        if self._closed:
            return
        self._check_thread()
        self.hide(reason="close")
        self._closed = True
        self._cancel_job = None
        self._hotkey_pending = False
        self._foreground_events.clear()
        try:
            if self._poll_id is not None:
                self.root.after_cancel(self._poll_id)
                self._poll_id = None
            if self._invoker is not None:
                self._invoker.close()
            # Native first: no hotkey or WinEvent reaches the adapter once the
            # picker window is gone.
            self.native.close()
        finally:
            self.overlay.close()
