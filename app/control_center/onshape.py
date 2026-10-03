"""Onshape mode (A0, Desk Dial only; ONSHAPE.md): the knob as Onshape's default mouse.

The mapping is adapted from katbinaris/NanoD_RatchetH1 feat/firmware-esp-idf-quadra
(NanoDepsidf/src/app_profiles/onshape.c, Karl Malota), with permission: the knob zooms (the
wheel, up = zoom in), hold 2 + turn orbits (right-drag along x), hold 4 + turn pans (middle-drag), a tap on 3 is
Undo (Ctrl+Z on Windows), and ~750 px of pointer travel per turn. Desk Dial adds hold 1 + turn = TILT (right-drag
along y: Onshape's default right-drag rotates, vertical motion pitches the view; 7.2.2.0, replaces Karl's F1 ZOOM)
and Home: all four buttons held together for HOME_CHORD_SECONDS (``KeyTracker`` chord; the runtime fires it).

Threads (the plan's "FastPath only enqueues"):

* the serial reader (``ui.FastPath``) only calls ``OnshapeInjector.post`` (a queue put);
* ``NanoD-onshape`` (``OnshapeInjector``) interprets the knob's key and detent events, calls
  SendInput and runs the watchdog (idle-deadline release), so the bridge thread's heartbeat never
  waits on another application's mouse hooks;
* the Tk thread (``Runtime``) owns the controller's presentation, Auto (``OnshapeAuto``, fed by
  ``FocusWatcher``) and activates / deactivates the injector.

Nothing here logs a window title. The injector is passed in: tests and the simulator never make a
``Win32Backend`` (``NullBackend`` or no injector at all), so they never inject.
"""
from __future__ import annotations

import ctypes
import logging
import os
import queue
import re
import sys
import threading
import time
import weakref

from . import keymap
from .app_engine import (AppInjector, FOCUS_REFUSED, KEYEVENTF_EXTENDEDKEY, KEYEVENTF_UNICODE,  # noqa: F401
                         LIFECYCLE, NullBackend, ProfileApp, REFUSED, ShortSend, SlotTracker, UNDO, chord_events,
                         chord_vk, knob_label, normal_idle_ms, scroll_events, text_events, turn_buttons)
from .onshape_app import OnshapeApp, builtin_onshape_profile
from .window_labels import BROWSER_SUFFIXES, normalize_title, strip_suffix

_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())

# ------------------------------------------------------------------ settings and tunables
ONSHAPE_MODES = ("off", "manual", "auto")         # settings.json `onshape_mode`
DEFAULT_ONSHAPE_MODE = "off"
DEFAULT_IDLE_MS = 800                              # settings.json `onshape_idle_ms` (drag idle deadline)
IDLE_MS_RANGE = (200, 5000)
PX_PER_TURN = 760                                  # orbit / tilt / pan pointer travel per knob turn (Karl: ~750)
TILT_DRAG_SIGN = 1                                 # tilt: +1 = a clockwise turn drags down (screen y grows)
PX_PER_DETENT = 11                                 # PX_PER_TURN / 67 (BINARIS BEER); re-derived per profile
ZOOM_NOTCHES_PER_TURN = 24                         # wheel notches per knob turn, sent as fractional deltas
WHEEL_DELTA = 120
AUTO_EXIT_SECONDS = 0.5                            # Auto leaves this long after Onshape lost the foreground
HOME_CHORD_SECONDS = 1.0                           # all four buttons held this long (from the 4th press) = Home
CHORD_KEYS = 3                                     # this many buttons down at once = a chord: no tap, drag or turn
FOCUS_POLL_SECONDS = 0.25                          # the title poll behind the NAMECHANGE hook
# The knob profile of the mode: the finest detent profile in the knob's inventory, else Home's.
# 2026-09-30: SMOOTH / SHAVED OPERATOR (127 detents, 2.8 deg, output ramp 0-5) buzzed on the user's knob (the
# detent spring against the 12N14P motor's ~4.3 deg cogging, no ramp): BINARIS BEER (67, ramp 10000), Home's
# volume profile, is smooth.
PROFILE_CHOICES = ("BINARIS BEER",)
FALLBACK_PROFILE = "BINARIS BEER"
DEFAULT_DETENTS_PER_TURN = 67                      # BINARIS BEER: detentCount 67 per 2 pi (haptic.cpp)

# Strict Auto match: the browser's exe AND Onshape's title. Recorded on this PC (2026-09-30):
# chrome.exe top-level `Chrome_WidgetWin_1`, web content `Chrome_RenderWidgetHostHWND` (Edge is the
# same Chromium widget). Firefox is not listed: its content and frame share one class, so the tab
# strip could not be told apart (a middle-click there closes a tab).
BROWSER_EXES = frozenset({"chrome.exe", "msedge.exe"})
CONTENT_CLASSES = ("Chrome_RenderWidgetHostHWND",)  # settings.json `onshape_content_classes`
# Onshape's own title segment. The browser's suffix (" - Google Chrome", " - Microsoft Edge"), Edge's
# " and N more pages" and a trailing Edge profile are removed first; the LAST remaining " | " / " - "
# segment must then be exactly this (a search results page "Onshape - Google Search" is not
# Onshape). Adjust here if Onshape's tab titles read differently on this PC.
ONSHAPE_TITLE = "Onshape"
_SEGMENTS = re.compile(r"\s+[|\-]\s+")
_EDGE_PAGES = re.compile(r"\s+and\s+\d{1,3}\s+more\s+pages?(?=$|\s+-\s+)")

# DD-SEC-001: the cursor is on the model but the keyboard focus is elsewhere (the address bar, the find bar, docked
# DevTools). A distinct result so the knob can say "Click the model first" instead of "Point at the model".
COMMAND = "command"

# A2 (ONSHAPE.md section 11): the virtual keys of the wheel's Windows chords and parameter mode.
VK_RETURN, VK_ESCAPE = 0x0D, 0x1B
_MOD_VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12}
_NAMED_VK = {"ENTER": VK_RETURN, "ESCAPE": VK_ESCAPE}


VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN, VK_Z = 0x10, 0x11, 0x12, 0x5B, 0x5C, 0x5A
MODIFIER_KEYS = (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN)


def normal_mode(value):
    return value if value in ONSHAPE_MODES else DEFAULT_ONSHAPE_MODE


def normal_classes(value):
    """A list of window-class names (settings.json), else the recorded default."""
    if isinstance(value, (list, tuple)):
        names = tuple(str(name) for name in value if isinstance(name, str) and 0 < len(name) <= 128)
        if names:
            return names
    return CONTENT_CLASSES


_EDGE_PROFILE = re.compile(r"(?:Profile \d{1,3}|Personal|Work|Guest|Default|InPrivate|\[InPrivate\])", re.I)
_BROWSER_NAMES = frozenset(name.casefold() for name in BROWSER_SUFFIXES)


def title_is_onshape(title):
    """The strict title rule (never logged): see ONSHAPE_TITLE."""
    if not isinstance(title, str) or not title:
        return False
    core = strip_suffix(normalize_title(title), *BROWSER_SUFFIXES)
    core = _EDGE_PAGES.sub("", core)
    parts = [part.strip() for part in _SEGMENTS.split(core) if part.strip()]
    # A browser name still in the title ("<page> - Google Chrome - <profile>"): the page ends before it.
    for index in range(len(parts) - 1, -1, -1):
        if parts[index].casefold() in _BROWSER_NAMES:
            parts = parts[:index]
            break
    if not parts:
        return False
    if parts[-1] == ONSHAPE_TITLE:
        return True
    # Edge: "<page> - <profile>" once the pages count is gone; the profile follows Onshape's segment.
    return len(parts) >= 2 and parts[-2] == ONSHAPE_TITLE and _EDGE_PROFILE.fullmatch(parts[-1]) is not None


# Onshape's tab titles carry only the document and tab names ("Bracket | Part Studio 1"), so Auto also
# accepts a browser window whose address bar shows Onshape (control_center.browser_url; host only, never
# logged). Enterprise workspaces are <company>.onshape.com; the marketing / learning sites are not Onshape.
ONSHAPE_HOSTS = frozenset({"cad.onshape.com"})
ONSHAPE_HOST_SUFFIX = ".onshape.com"
NOT_ONSHAPE_HOSTS = frozenset({"www.onshape.com", "onshape.com", "learn.onshape.com", "forum.onshape.com",
                               "status.onshape.com", "partners.onshape.com", "appstore.onshape.com"})
ADDRESS_CACHE_SECONDS = 5.0
ADDRESS_UIA_TIMEOUT_MS = 1000      # DD-BUG-012: the address-bar worker's UI Automation connection / transaction bound
KEY_FOCUS_CACHE_SECONDS = 0.25     # the keyboard-focus answer is reused this long (a parameter turn's burst)


def host_is_onshape(host):
    host = str(host or "").lower()
    if host in ONSHAPE_HOSTS:
        return True
    return host.endswith(ONSHAPE_HOST_SUFFIX) and host not in NOT_ONSHAPE_HOSTS


def window_is_onshape(exe, title):
    """Auto's strict match: the browser exe (case-insensitive file name) and Onshape's title."""
    name = os.path.basename(str(exe or "")).lower()
    return name in BROWSER_EXES and title_is_onshape(title)


def choose_profile(profiles):
    """The Onshape mode's knob profile from the knob's inventory {name: profile}: the finest
    installed (PROFILE_CHOICES), else Home's (always installed). Returns (name, detents per turn)."""
    names = profiles if isinstance(profiles, dict) else {}
    for name in PROFILE_CHOICES:
        if name in names:
            return name, _detents(names.get(name))
    return FALLBACK_PROFILE, _detents(names.get(FALLBACK_PROFILE), 67)


def _detents(profile, default=DEFAULT_DETENTS_PER_TURN):
    try:
        count = profile["knob"][0]["haptic"]["detentCount"]
    except (KeyError, IndexError, TypeError):
        return default
    return count if type(count) is int and 1 <= count <= 1000 else default


# ------------------------------------------------------------------ the key grammar (pure)
class KeyTracker(SlotTracker):
    """Onshape's key grammar (app_engine.SlotTracker): hold 1 = tilt, 2 = orbit, 4 = pan; the knob alone zooms. A turn
    during a press drops that key's tap and its hold; 3+ buttons down together are the Home chord (no tap, drag or
    turn). Shared by the controller and the injector, so both read the same events the same way."""

    MODIFIERS = {0: "tilt", 1: "orbit", 3: "pan"}
    DEFAULT_ACTION = "zoom"

    def __init__(self):
        super().__init__()


# ------------------------------------------------------------------ Auto (pure, Tk thread)
class OnshapeAuto:
    """Auto: enter when Onshape has the foreground, leave AUTO_EXIT_SECONDS after it lost it; a
    user exit (all four buttons held, the tray) suppresses Auto until Onshape loses the foreground and gains it
    again. ``pending``: Auto wants the mode and the controller can enter it now (Sonos volume
    ignores the knob meanwhile)."""

    def __init__(self, exit_seconds=AUTO_EXIT_SECONDS):
        self.exit_seconds = exit_seconds
        self.suppressed = False
        self.pending = False
        self._lost_at = None

    def suppress(self):
        self.suppressed = True

    def update(self, now, setting, focused, in_mode, can_enter):
        """'enter' | 'exit' | None."""
        if not focused:
            self.suppressed = False          # the loss half of "loses and regains"
        self.pending = False
        if setting != "auto":
            self._lost_at = None
            return None
        if focused:
            self._lost_at = None
            if not in_mode and not self.suppressed and can_enter:
                self.pending = True
                return "enter"
            return None
        if not in_mode:
            self._lost_at = None
            return None
        if self._lost_at is None:
            self._lost_at = now
        if now - self._lost_at >= self.exit_seconds:
            self._lost_at = None
            return "exit"
        return None


# ------------------------------------------------------------------ the injector (app_engine, Onshape's profile)
class OnshapeInjector(AppInjector):
    """The injector thread and its watchdog (app_engine.AppInjector) with Onshape's built-in profile
    (onshape_app.builtin_onshape_profile) and Onshape's A2 state machine (OnshapeApp). ``activate(..., profile=)``
    switches it to any other app profile (the runtime does, through the same injector the fast path posts to).
    Every public method is safe from any thread and only queues; ``step()`` (tests, ``start=False``) runs the queue
    and the watchdog synchronously."""

    tracker_class = KeyTracker
    thread_name = "NanoD-onshape"
    logger = _log

    def __init__(self, backend=None, *, clock=time.monotonic, idle_ms=DEFAULT_IDLE_MS, px_per_detent=None,
                 start=True, profile=None):
        super().__init__(backend, clock=clock, idle_ms=idle_ms, px_per_detent=px_per_detent, start=start,
                         profile=profile if profile is not None else builtin_onshape_profile())

    @property
    def app_class(self):
        """Onshape keeps its A2 action spelling (OnshapeApp); every other profile runs the generic machine."""
        return OnshapeApp if getattr(self.profile, "id", None) == "onshape" else ProfileApp

    def _make_tracker(self, profile):
        if profile is None or getattr(profile, "id", None) == "onshape":
            return KeyTracker()
        return SlotTracker(turn_buttons(profile), knob_label(profile))


# ------------------------------------------------------------------ Win32 (live only)
if sys.platform == "win32":
    from ctypes import wintypes as W

    _WINEVENTPROC = ctypes.WINFUNCTYPE(None, W.HANDLE, W.DWORD, W.HWND, W.LONG, W.LONG, W.DWORD, W.DWORD)
    _WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
else:  # pragma: no cover - the live classes are Windows only
    W = None
    _WINEVENTPROC = _WNDPROC = None

MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x0001, 0x8000, 0x4000
MOUSE_FLAGS = {("down", "left"): 0x0002, ("up", "left"): 0x0004, ("down", "right"): 0x0008,
               ("up", "right"): 0x0010, ("down", "middle"): 0x0020, ("up", "middle"): 0x0040}
SM_SWAPBUTTON, SM_CXDRAG = 23, 68
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79
GA_ROOT = 2
MAPVK_VK_TO_VSC = 0
EVENT_SYSTEM_FOREGROUND, EVENT_OBJECT_NAMECHANGE = 0x0003, 0x800C
WINEVENT_OUTOFCONTEXT, WINEVENT_SKIPOWNPROCESS = 0x0000, 0x0002
_RETIRED = []   # WinEvent thunks Windows may still call after an unhook are never freed


def _user32():
    user = ctypes.WinDLL("user32", use_last_error=True)
    for name, result, args in (
            ("GetCursorPos", W.BOOL, (ctypes.POINTER(W.POINT),)),
            ("WindowFromPoint", W.HWND, (W.POINT,)),
            ("GetAncestor", W.HWND, (W.HWND, W.UINT)),
            ("GetClassNameW", ctypes.c_int, (W.HWND, W.LPWSTR, ctypes.c_int)),
            ("GetForegroundWindow", W.HWND, ()),
            ("GetWindowTextW", ctypes.c_int, (W.HWND, W.LPWSTR, ctypes.c_int)),
            ("GetWindowThreadProcessId", W.DWORD, (W.HWND, ctypes.POINTER(W.DWORD))),
            ("GetSystemMetrics", ctypes.c_int, (ctypes.c_int,)),
            ("GetAsyncKeyState", ctypes.c_short, (ctypes.c_int,)),
            ("GetKeyboardLayout", W.HANDLE, (W.DWORD,)),
            ("MapVirtualKeyExW", W.UINT, (W.UINT, W.UINT, W.HANDLE)),
            ("SetWinEventHook", W.HANDLE, (W.DWORD, W.DWORD, W.HANDLE, _WINEVENTPROC, W.DWORD, W.DWORD, W.DWORD)),
            ("UnhookWinEvent", W.BOOL, (W.HANDLE,))):
        function = getattr(user, name)
        function.restype, function.argtypes = result, args
    return user


def _kernel32():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype, kernel.OpenProcess.argtypes = W.HANDLE, (W.DWORD, W.BOOL, W.DWORD)
    kernel.CloseHandle.restype, kernel.CloseHandle.argtypes = W.BOOL, (W.HANDLE,)
    kernel.QueryFullProcessImageNameW.restype = W.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = (W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD))
    return kernel


_DESKTOP = {}


def input_desktop_is_default():
    """App profiles (plan 3b): windows.NativeWindows.input_desktop_is_default (K4 15's check: the input desktop's name
    is Default) over this module's own user32, without the tray app's window adapter. Any failure reads False."""
    try:
        if "u" not in _DESKTOP:
            from . import windows as native
            user = ctypes.WinDLL("user32", use_last_error=True)
            for name, result, args in (
                    ("OpenInputDesktop", W.HANDLE, (W.DWORD, W.BOOL, W.DWORD)),
                    ("GetUserObjectInformationW", W.BOOL, (W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD,
                                                           ctypes.POINTER(W.DWORD))),
                    ("CloseDesktop", W.BOOL, (W.HANDLE,))):
                function = getattr(user, name)
                function.restype, function.argtypes = result, args

            class _Native:
                u = user

            _DESKTOP["u"] = _Native()
            _DESKTOP["check"] = native.NativeWindows.input_desktop_is_default
        return bool(_DESKTOP["check"](_DESKTOP["u"]))
    except Exception:
        return False


class AddressVerdicts:
    """DD-BUG-012: the address-bar reads, off the calling (Tk / injector) threads. One daemon worker reads a
    window's host (browser_url.address_host, its UI Automation bounded by ADDRESS_UIA_TIMEOUT_MS) and caches the
    host's verdict per (window, title hash) for ADDRESS_CACHE_SECONDS: True / False, or None when the host could
    not be read (the caller then applies the strict title rule itself; titles never reach the worker). ``lookup``
    never blocks: a key never read answers ``(False, None)`` and queues one read; an expired one keeps answering
    its last verdict while it is read again. Listeners (weakly held) are called on the worker after each read."""

    def __init__(self, reader=None, clock=time.monotonic, timeout_ms=ADDRESS_UIA_TIMEOUT_MS):
        self._reader = reader
        self._clock = clock
        self._timeout_ms = timeout_ms
        self._lock = threading.Lock()
        self._verdicts = {}
        self._pending = set()
        self._queue = queue.Queue()
        self._thread = None
        self._listeners = []

    def listen(self, method):
        with self._lock:
            self._listeners.append(weakref.WeakMethod(method))

    def lookup(self, hwnd, key):
        """(known, verdict) for the window ``hwnd`` under ``key`` (hwnd, title hash)."""
        now = self._clock()
        with self._lock:
            hit = self._verdicts.get(key)
            if hit is not None and now - hit[1] < ADDRESS_CACHE_SECONDS:
                return True, hit[0]
            if key not in self._pending:
                self._pending.add(key)
                self._queue.put((int(hwnd), key))
                if self._thread is None:
                    self._thread = threading.Thread(target=self._run, name="NanoD-onshape-address", daemon=True)
                    self._thread.start()
        return (True, hit[0]) if hit is not None else (False, None)

    def _read(self, hwnd):
        reader = self._reader
        if reader is None:
            from .browser_url import address_host as reader
        host = reader(hwnd)
        return host_is_onshape(host) if host is not None else None

    def _run(self):
        if self._reader is None:
            try:
                from .browser_url import set_timeouts
                set_timeouts(self._timeout_ms)
            except Exception:
                pass
        while True:
            hwnd, key = self._queue.get()
            try:
                verdict = self._read(hwnd)
            except Exception:
                verdict = None
            with self._lock:
                if len(self._verdicts) > 64:
                    self._verdicts.clear()
                self._verdicts[key] = (verdict, self._clock())
                self._pending.discard(key)
                listeners = [ref() for ref in self._listeners]
                self._listeners = [ref for ref in self._listeners if ref() is not None]
            for listener in listeners:
                if listener is not None:
                    try:
                        listener()
                    except Exception:
                        pass


_address_verdicts = None


def shared_address_verdicts():
    """The one AddressVerdicts of the live app: the focus watcher's and the injector's windows share it, so the
    injector's target check finds the verdict the watcher's poll already asked for."""
    global _address_verdicts
    if _address_verdicts is None:
        _address_verdicts = AddressVerdicts()
    return _address_verdicts


class OnshapeWindows:
    """The foreground and target checks (Windows): exe names are cached per process id; window
    titles are read, matched and dropped (never kept or logged)."""

    def __init__(self, classes=CONTENT_CLASSES, verdicts=None):
        self.u, self.k = _user32(), _kernel32()
        self.classes = normal_classes(classes)
        self._exes = {}
        self._verdicts = verdicts if verdicts is not None else shared_address_verdicts()

    def pid(self, hwnd):
        pid = W.DWORD()
        self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)

    def exe(self, pid):
        if pid in self._exes:
            return self._exes[pid]
        name = ""
        process = self.k.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if process:
            try:
                buffer, size = ctypes.create_unicode_buffer(1024), W.DWORD(1024)
                if self.k.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                    name = os.path.basename(buffer.value).lower()
            finally:
                self.k.CloseHandle(process)
        if len(self._exes) > 256:
            self._exes.clear()
        self._exes[pid] = name
        return name

    def class_name(self, hwnd):
        buffer = ctypes.create_unicode_buffer(256)
        self.u.GetClassNameW(hwnd, buffer, 256)
        return buffer.value

    def is_onshape(self, hwnd):
        """A Chrome / Edge window showing Onshape. DD-SEC-002: the host in its address bar (UI Automation, cached
        per (window, title) for ADDRESS_CACHE_SECONDS) decides: the marketing / learning sites (NOT_ONSHAPE_HOSTS)
        and any other site are not Onshape whatever their title says. Only when the host can't be read at all is
        the strict title rule (title_is_onshape) the fallback. DD-BUG-012: with the live AddressVerdicts the read
        happens on its worker and this never blocks: a window and title not read yet is not Onshape until it is
        (a window built without it, as in tests, reads in place)."""
        if not hwnd:
            return False
        exe = self.exe(self.pid(hwnd))
        if exe not in BROWSER_EXES:
            return False
        buffer = ctypes.create_unicode_buffer(1024)
        self.u.GetWindowTextW(hwnd, buffer, 1024)
        title = buffer.value
        key = (int(hwnd), hash(title))                   # the title itself is never kept
        verdicts = getattr(self, "_verdicts", None)
        if verdicts is not None:
            known, verdict = verdicts.lookup(hwnd, key)
            if not known:
                return False
            return verdict if verdict is not None else title_is_onshape(title)
        now = time.monotonic()
        cache = getattr(self, "_address_cache", None)
        if cache is None:
            cache = self._address_cache = {}
        hit = cache.get(key)
        if hit is not None and now - hit[1] < ADDRESS_CACHE_SECONDS:
            return hit[0]
        reader = getattr(self, "address_host", None)
        if reader is None:
            from .browser_url import address_host as reader
        host = reader(hwnd)
        answer = host_is_onshape(host) if host is not None else title_is_onshape(title)
        if len(cache) > 64:
            cache.clear()
        cache[key] = (answer, now)
        return answer

    def foreground(self):
        return self.u.GetForegroundWindow()

    def onshape_foreground(self):
        return self.is_onshape(self.foreground())

    def target_ok(self, point):
        """The window under ``point`` is the browser's content widget and its root is the
        Onshape window in the foreground (never the tab strip, toolbar or bookmarks bar)."""
        hwnd = self.u.WindowFromPoint(W.POINT(int(point[0]), int(point[1])))
        if not hwnd or self.class_name(hwnd) not in self.classes:
            return False
        root = self.u.GetAncestor(hwnd, GA_ROOT)
        foreground = self.foreground()
        if not root or root != foreground or not self.is_onshape(root):
            return False
        # DD-SEC-003: is_onshape may read the address bar (UI Automation, slow): the foreground must still be the
        # same window afterwards, or the chord / text / drag that follows would land in the new one.
        return self.foreground() == root

    def keyboard_ok(self, point):
        """The keyboard focus is inside the page under ``point`` (UI Automation: the focused element lies in the
        outermost web Document there), so a keystroke reaches Onshape and never the address bar, the find bar or
        docked DevTools. Cached KEY_FOCUS_CACHE_SECONDS. UI Automation unable to tell (None) keeps the cursor
        gate alone, as before."""
        now = time.monotonic()
        hit = getattr(self, "_key_focus", None)
        if hit is not None and now - hit[1] < KEY_FOCUS_CACHE_SECONDS:
            return hit[0]
        reader = getattr(self, "focus_in_page", None)
        if reader is None:
            from .browser_url import focus_in_page as reader
        answer = reader(point) is not False
        self._key_focus = (answer, now)
        return answer

    def keyboard_ok_fresh(self, point):
        """S3 decision (typed text after a chord): UI Automation read now, never the cache, and only the page's own
        document focus passes (can't tell does not: the chord may just have moved the focus to the address bar). The
        answer refreshes the cache."""
        reader = getattr(self, "focus_in_page", None)
        if reader is None:
            from .browser_url import focus_in_page as reader
        answer = reader(point) is True
        self._key_focus = (answer, time.monotonic())
        return answer


class Win32Backend:
    """SendInput with windows_actions' INPUT layout and short-return rule (absolute moves on the
    virtual desktop; the process is per-monitor DPI aware)."""
    injects = True

    def __init__(self, windows=None):
        from windows_actions import INPUT, INPUT_KEYBOARD, INPUT_MOUSE, KEYEVENTF_KEYUP, MOUSEEVENTF_WHEEL, _load_send_input
        self._INPUT, self._INPUT_MOUSE, self._INPUT_KEYBOARD = INPUT, INPUT_MOUSE, INPUT_KEYBOARD
        self._KEYUP, self._WHEEL = KEYEVENTF_KEYUP, MOUSEEVENTF_WHEEL
        self._send_input = _load_send_input()
        self.windows = windows or OnshapeWindows()
        self.u = self.windows.u

    def cursor(self):
        point = W.POINT()
        if not self.u.GetCursorPos(ctypes.byref(point)):
            raise OSError(ctypes.get_last_error(), "GetCursorPos failed")
        return (point.x, point.y)

    def target_ok(self, point):
        return self.windows.target_ok(point)

    def onshape_foreground(self):
        return self.windows.onshape_foreground()

    def focus_ok(self, point):
        return self.windows.keyboard_ok(point)

    def focus_fresh(self, point):
        """S3 decision: the keyboard focus read now (typed text after a chord). A windows object without the check
        fails closed."""
        check = getattr(self.windows, "keyboard_ok_fresh", None)
        return bool(check(point)) if callable(check) else False

    def set_profile(self, profile):
        """App profiles: the gates follow the active profile (the injector thread calls it on activation)."""
        setter = getattr(self.windows, "set_profile", None)
        if callable(setter):
            setter(profile)

    def desktop_ok(self):
        """App profiles (plan 3b): the input desktop is the user's Default one. A lock screen or a UAC prompt (the
        secure desktop) reads False, and so does any failure: nothing is sent then."""
        return input_desktop_is_default()

    def resolve_chord(self, chord):
        """App profiles (plan 4a): (vk, mods) for a keymap.Chord on the foreground thread's layout, or None ("Not on
        this keyboard"). The layout read here is the one the next batch's scan codes use (DD-SEC-004's read)."""
        layout = self._keyboard_layout()
        self._batch_layout = layout
        return keymap.resolve_chord(chord, layout)

    def foreground(self):
        return self.windows.foreground()

    def swapped(self):
        return bool(self.u.GetSystemMetrics(SM_SWAPBUTTON))

    def drag_threshold(self):
        return max(1, int(self.u.GetSystemMetrics(SM_CXDRAG) or 4))

    def modifiers_held(self):
        return any(self.u.GetAsyncKeyState(vk) & 0x8000 for vk in MODIFIER_KEYS)

    def _absolute(self, x, y):
        left, top = self.u.GetSystemMetrics(SM_XVIRTUALSCREEN), self.u.GetSystemMetrics(SM_YVIRTUALSCREEN)
        width = max(2, self.u.GetSystemMetrics(SM_CXVIRTUALSCREEN))
        height = max(2, self.u.GetSystemMetrics(SM_CYVIRTUALSCREEN))
        x = max(left, min(left + width - 1, int(x)))
        y = max(top, min(top + height - 1, int(y)))
        return (round((x - left) * 65535 / (width - 1)), round((y - top) * 65535 / (height - 1)))

    def _keyboard_layout(self):
        """The keyboard layout of the foreground window's thread (the one that receives the keys), or None."""
        try:
            hwnd = self.u.GetForegroundWindow()
            thread = self.u.GetWindowThreadProcessId(hwnd, None) if hwnd else 0
            return self.u.GetKeyboardLayout(thread)
        except Exception:
            return None

    def _scan(self, vk):
        """DD-SEC-004: the scan code of ``vk`` in the receiving layout (Chromium derives KeyboardEvent.code from
        it; 0 left the page an empty code). 0 when Windows has none."""
        layout = self._layout if getattr(self, "_layout", None) is not None else self._keyboard_layout()
        try:
            return int(self.u.MapVirtualKeyExW(int(vk), MAPVK_VK_TO_VSC, layout)) & 0xFFFF
        except Exception:
            return 0

    def _input(self, event):
        kind = event[0]
        if kind == "key":
            item = self._INPUT(type=self._INPUT_KEYBOARD)
            item.ki.wVk = event[1]
            item.ki.wScan = self._scan(event[1])
            item.ki.dwFlags = self._KEYUP if event[2] else 0
            if (len(event) > 3 and event[3]) or event[1] in keymap.EXTENDED_VKS:
                item.ki.dwFlags |= KEYEVENTF_EXTENDEDKEY       # app profiles: arrows, Insert / Delete, Home / End...
            return item
        if kind == "char":                              # A2: typed text (tool search phrases, parameter values)
            item = self._INPUT(type=self._INPUT_KEYBOARD)
            item.ki.wVk = 0
            item.ki.wScan = ord(event[1])
            item.ki.dwFlags = KEYEVENTF_UNICODE | (self._KEYUP if event[2] else 0)
            return item
        item = self._INPUT(type=self._INPUT_MOUSE)
        if kind == "move":
            item.mi.dx, item.mi.dy = self._absolute(event[1], event[2])
            item.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        elif kind == "wheel":
            item.mi.mouseData = int(event[1]) & 0xFFFFFFFF    # fractional notches: |n| < 120 is fine
            item.mi.dwFlags = self._WHEEL
        else:
            item.mi.dwFlags = MOUSE_FLAGS[(kind, event[1])]
        return item

    def send(self, events):
        batch, self._batch_layout = getattr(self, "_batch_layout", None), None
        if any(event[0] == "key" for event in events):
            self._layout = batch if batch is not None else self._keyboard_layout()
        else:
            self._layout = None
        try:
            items = [self._input(event) for event in events]
        finally:
            self._layout = None
        buffer = (self._INPUT * len(items))(*items)
        ctypes.set_last_error(0)
        return int(self._send_input(len(buffer), buffer, ctypes.sizeof(self._INPUT)))


class FocusWatcher:
    """Whether Onshape has the foreground (Tk thread). EVENT_SYSTEM_FOREGROUND and, for the
    foreground browser's process, EVENT_OBJECT_NAMECHANGE (a tab switch in one window) only mark
    the answer stale; ``focused()`` re-reads it then, and at least every FOCUS_POLL_SECONDS (the
    fallback). The hooks are out of context on the installing (Tk) thread; the callbacks only set a
    flag. Titles are never kept."""

    def __init__(self, windows=None, clock=time.monotonic, hook=True):
        self.windows = windows or OnshapeWindows()
        self.u = self.windows.u
        self.clock = clock
        self._stale = True
        self._checked = -1e9
        self._value = False
        self._foreground = None
        self._name_hook = None
        self._name_pid = None
        self._hooks = []

        @_WINEVENTPROC
        def on_foreground(_hook, _event, hwnd, _obj, _child, _thread, _time):
            self._stale = True

        @_WINEVENTPROC
        def on_name(_hook, _event, hwnd, obj, _child, _thread, _time):
            if obj == 0 and hwnd and hwnd == self._foreground:   # OBJID_WINDOW of the foreground window
                self._stale = True

        self._callbacks = (on_foreground, on_name)
        listen = getattr(getattr(self.windows, "_verdicts", None), "listen", None)
        if callable(listen):
            listen(self._verdict_read)                   # DD-BUG-012: a finished address read re-checks
        if not hook:
            return
        hook = self.u.SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, None, on_foreground, 0, 0,
                                      WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
        if hook:
            self._hooks.append(hook)

    def _hook_names(self, pid):
        if pid == self._name_pid:
            return
        if self._name_hook:
            self.u.UnhookWinEvent(self._name_hook)
            self._name_hook = None
        self._name_pid = pid
        if pid:
            self._name_hook = self.u.SetWinEventHook(EVENT_OBJECT_NAMECHANGE, EVENT_OBJECT_NAMECHANGE, None,
                                                     self._callbacks[1], pid, 0, WINEVENT_OUTOFCONTEXT) or None

    def _verdict_read(self):
        self._stale = True

    def pause(self):
        """DD-BUG-012: Onshape mode is Off: drop the browser's name-change hook and the foreground window; the
        next ``focused()`` reads everything again."""
        self._hook_names(0)
        self._foreground = None
        self._stale = True

    def focused(self, now=None):
        now = self.clock() if now is None else now
        if not self._stale and now - self._checked < FOCUS_POLL_SECONDS:
            return self._value
        self._stale = False
        self._checked = now
        hwnd = self.windows.foreground()
        self._foreground = hwnd
        pid = self.windows.pid(hwnd) if hwnd else 0
        browser = bool(pid) and self.windows.exe(pid) in BROWSER_EXES
        self._hook_names(pid if browser else 0)
        self._value = bool(browser and self.windows.is_onshape(hwnd))
        return self._value

    def close(self):
        self._hook_names(0)
        for hook in self._hooks:
            self.u.UnhookWinEvent(hook)
        self._hooks = []
        _RETIRED.extend(self._callbacks)


WM_WTSSESSION_CHANGE, WM_CLOSE, WM_DESTROY = 0x02B1, 0x0010, 0x0002
NOTIFY_FOR_THIS_SESSION = 0
HWND_MESSAGE = -3
SESSION_CLASS = "NanoDOnshapeSession"

# DD-BUG-026: the window class is registered once per process with ONE window procedure that hands each message
# to the watcher owning that window (a live -> simulator -> live toggle builds a second watcher before the first
# is closed; a class registered per watcher kept the first watcher's procedure, so the new injector never got
# "session"). hwnd -> SessionWatcher; entries leave on WM_DESTROY.
_session_lock = threading.Lock()
_session_watchers = {}
_session_class = {}          # "user" (its own user32 with the procedure's argtypes), "procedure" (kept forever)


def _session_message(hwnd, message, wparam):
    """WM_WTSSESSION_CHANGE for ``hwnd``: that window's watcher's ``on_change`` only (none: nothing). True when
    the message is a session change (handled), else False."""
    if message != WM_WTSSESSION_CHANGE:
        return False
    with _session_lock:
        watcher = _session_watchers.get(int(hwnd or 0))
    if watcher is not None:
        try:
            watcher.on_change(int(wparam))
        except Exception:
            pass
    return True


def _session_procedure(hwnd, message, wparam, lparam):
    user = _session_class["user"]
    if _session_message(hwnd, message, wparam):
        return 0
    if message == WM_CLOSE:
        user.DestroyWindow(hwnd)
        return 0
    if message == WM_DESTROY:
        with _session_lock:
            _session_watchers.pop(int(hwnd or 0), None)
        user.PostQuitMessage(0)
        return 0
    return user.DefWindowProcW(hwnd, message, wparam, lparam)


if W is not None:
    class _WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", W.UINT), ("lpfnWndProc", _WNDPROC), ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int), ("hInstance", W.HINSTANCE), ("hIcon", W.HANDLE),
                    ("hCursor", W.HANDLE), ("hbrBackground", W.HANDLE), ("lpszMenuName", W.LPCWSTR),
                    ("lpszClassName", W.LPCWSTR)]


def _session_register_class(instance):
    """Registers SESSION_CLASS once per process (later calls reuse it). Returns its user32."""
    with _session_lock:
        if "user" in _session_class:
            return _session_class["user"]
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.DefWindowProcW.restype = ctypes.c_ssize_t
        user.DefWindowProcW.argtypes = (W.HWND, W.UINT, W.WPARAM, W.LPARAM)
        user.RegisterClassW.restype, user.RegisterClassW.argtypes = W.ATOM, (ctypes.POINTER(_WNDCLASSW),)
        user.DestroyWindow.argtypes = (W.HWND,)
        user.PostQuitMessage.argtypes = (ctypes.c_int,)
        procedure = _WNDPROC(_session_procedure)
        wc = _WNDCLASSW(lpfnWndProc=procedure, hInstance=instance, lpszClassName=SESSION_CLASS)
        if not user.RegisterClassW(ctypes.byref(wc)) and ctypes.get_last_error() != 1410:  # CLASS_ALREADY_EXISTS
            raise OSError(ctypes.get_last_error(), "RegisterClassW failed")
        _session_class["procedure"] = procedure        # never freed: the class keeps calling it
        _session_class["user"] = user
        return user


class SessionWatcher:
    """WM_WTSSESSION_CHANGE (lock screen, a console / remote disconnect, logoff) on a message-only
    window of its own thread (``NanoD-onshape-session``): ``on_change(code)`` there (it only
    queues: the injector's release_all). Each watcher gets its own window's messages only (the
    shared class dispatches by window: DD-BUG-026). Never raises from the constructor."""

    def __init__(self, on_change):
        self.on_change = on_change
        self.hwnd = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="NanoD-onshape-session", daemon=True)
        self._thread.start()
        self._ready.wait(2.0)

    def _run(self):
        user = ctypes.WinDLL("user32", use_last_error=True)
        wts = ctypes.WinDLL("wtsapi32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        user.CreateWindowExW.restype = W.HWND
        user.CreateWindowExW.argtypes = (W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, ctypes.c_int, ctypes.c_int,
                                         ctypes.c_int, ctypes.c_int, W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID)
        user.GetMessageW.restype, user.GetMessageW.argtypes = W.BOOL, (ctypes.POINTER(W.MSG), W.HWND, W.UINT, W.UINT)
        user.DispatchMessageW.argtypes = (ctypes.POINTER(W.MSG),)
        wts.WTSRegisterSessionNotification.restype = W.BOOL
        wts.WTSRegisterSessionNotification.argtypes = (W.HWND, W.DWORD)
        wts.WTSUnRegisterSessionNotification.argtypes = (W.HWND,)
        kernel.GetModuleHandleW.restype, kernel.GetModuleHandleW.argtypes = W.HMODULE, (W.LPCWSTR,)

        try:
            instance = kernel.GetModuleHandleW(None)
            _session_register_class(instance)
            self.hwnd = user.CreateWindowExW(0, SESSION_CLASS, SESSION_CLASS, 0, 0, 0, 0, 0, W.HWND(HWND_MESSAGE),
                                             None, instance, None)
            if self.hwnd:
                with _session_lock:
                    _session_watchers[int(self.hwnd)] = self
                wts.WTSRegisterSessionNotification(self.hwnd, NOTIFY_FOR_THIS_SESSION)
        except Exception:
            _log.warning("Onshape session watcher unavailable", exc_info=True)
            self.hwnd = None
        finally:
            self._ready.set()
        if not self.hwnd:
            return
        message = W.MSG()
        while user.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user.DispatchMessageW(ctypes.byref(message))
        try:
            wts.WTSUnRegisterSessionNotification(self.hwnd)
        except Exception:
            pass
        with _session_lock:
            if _session_watchers.get(int(self.hwnd)) is self:
                del _session_watchers[int(self.hwnd)]

    def close(self, timeout=1.0):
        if self.hwnd:
            user = ctypes.WinDLL("user32", use_last_error=True)
            user.PostMessageW.argtypes = (W.HWND, W.UINT, W.WPARAM, W.LPARAM)
            user.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        self._thread.join(timeout)


def live_service(idle_ms=DEFAULT_IDLE_MS, classes=CONTENT_CLASSES):
    """The live app-mode pieces for the tray app: (injector, detector, session watcher). App profiles (DD-B): the one
    injector serves every profile (its gates follow the active one: app_detect.AppWindows) and the detector is
    app_detect.AppDetector (``detect(now, profiles)``; ``focused()`` keeps FocusWatcher's Onshape contract). Any
    failure leaves the app mode without injection (None, None, None) and is logged once (the exception type only)."""
    try:
        from .app_detect import AppDetector, AppWindows
        injector = OnshapeInjector(Win32Backend(AppWindows(classes)), idle_ms=idle_ms)
        focus = AppDetector(AppWindows(classes))
        session = SessionWatcher(lambda code: injector.release_all("session"))
        return injector, focus, session
    except Exception as exc:
        _log.warning("App mode injection unavailable (%s)", type(exc).__name__)
        return None, None, None
