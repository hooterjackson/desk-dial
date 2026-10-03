"""App detection and the per-app window gates (plan sections 3a / 3b; S1 lane DD-B). Generalised from Onshape mode's
``FocusWatcher`` / ``OnshapeWindows`` (onshape.py).

**Matching** (``match_app``, pure): the foreground window's program name first; when it is a Chromium browser (chrome,
msedge, brave, vivaldi, opera) the host in its address bar too (``browser_url.address_host`` on a worker, cached per
(window, title hash) for 5 s). A host rule beats a program rule; a tie goes to the earlier profile in ``app_order``.
``exclude_host`` is honoured (``Detect.matches_host``). The owner's rules (settings.json ``app_rules``) merge in
(``with_rules``). Onshape keeps its strict title rule for a browser whose address bar can't be read at all (DD-SEC-002).

**Detection** (``AppDetector``, the Tk thread): ``detect(now, profiles)`` answers ``(id, matched_by)`` for the apps it is
given (the runtime gives the ones not Off, Manual included, plus the active one; only Auto ones enter by themselves);
with none it reads nothing at all (no
foreground, no title, no UI Automation: DD-BUG-012 generalised). EVENT_SYSTEM_FOREGROUND and the browser's
EVENT_OBJECT_NAMECHANGE mark the answer stale; it is re-read then and at least every 250 ms.

**Gates** (``AppWindows``, the injector thread): ``target_ok`` - the window under the cursor has the foreground window
as its root and that window is the active app: for a browser app its content widget (``content_class``) and the host;
for a desktop app the program (and the sidecar's optional ``content_class``); the foreground is checked again after a
slow read (DD-SEC-003). ``keyboard_ok`` - browser apps: UI Automation's document focus (DD-SEC-001); desktop apps:
``GetGUIThreadInfo``'s focus window belongs to the app's process.

**Privacy:** titles and URLs are never stored or logged: a title is hashed into a cache key and dropped, a host lives
only in the worker's 5 s cache. Logs carry profile ids, ``matched_by`` and exception type names only.
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
from dataclasses import replace

from .app_profiles import BROWSER_EXES as CHROMIUM_EXES, Detect, host_matches, is_shell_exe
from .onshape import (ADDRESS_CACHE_SECONDS, AddressVerdicts, CONTENT_CLASSES, EVENT_OBJECT_NAMECHANGE,
                      EVENT_SYSTEM_FOREGROUND, FOCUS_POLL_SECONDS, GA_ROOT, OnshapeWindows, WINEVENT_OUTOFCONTEXT,
                      WINEVENT_SKIPOWNPROCESS, _RETIRED, _WINEVENTPROC, title_is_onshape)

_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())

BROWSERS = frozenset(name.lower() for name in CHROMIUM_EXES)
ONSHAPE_BROWSERS = frozenset({"chrome.exe", "msedge.exe"})       # the strict title rule's browsers (onshape.py)
MATCHED_BY = ("exe", "host")
DETECT_POLL_SECONDS = FOCUS_POLL_SECONDS          # 250 ms
HOST_CACHE_SECONDS = ADDRESS_CACHE_SECONDS        # 5 s per (window, title hash)


# ------------------------------------------------------------------ pure
def is_browser(exe):
    return os.path.basename(str(exe or "")).lower() in BROWSERS


def with_rules(profile, rules):
    """``profile`` with the owner's extra programs and hosts (settings.json ``app_rules[id]``) merged into its
    detection (no duplicates; the bundled exclusions stay)."""
    extra = (rules or {}).get(profile.id) if isinstance(rules, dict) else None
    if not isinstance(extra, dict):
        return profile
    d = profile.detect
    exe = tuple(dict.fromkeys((*d.exe, *(v for v in extra.get("exe") or () if isinstance(v, str)))))
    host = tuple(dict.fromkeys((*d.host, *(v for v in extra.get("host") or () if isinstance(v, str)))))
    if exe == d.exe and host == d.host:
        return profile
    return replace(profile, detect=Detect(exe=exe, host=host, exclude_host=d.exclude_host,
                                          content_class=d.content_class))


def match_app(profiles, exe, host):
    """(profile id, 'exe' | 'host') for the foreground program ``exe`` and its address bar ``host`` (None when it is
    not a browser or can't be read), or (None, None). ``profiles`` in Settings order (``app_order``): a host rule beats a
    program rule, then the earlier profile wins."""
    best = None
    for index, profile in enumerate(profiles):
        d = profile.detect
        hit = None
        if host and is_browser(exe) and d.matches_host(host):
            hit = (0, index, profile.id, "host")
        elif d.matches_exe(exe):
            hit = (1, index, profile.id, "exe")
        if hit is not None and (best is None or hit < best):
            best = hit
    return (best[2], best[3]) if best is not None else (None, None)


def ordered(profiles, order):
    """Profiles in the owner's ``app_order`` (ids missing from it keep the library's order, after)."""
    order = [pid for pid in (order or ()) if isinstance(pid, str)]
    rank = {pid: i for i, pid in enumerate(order)}
    return sorted(profiles, key=lambda p: (rank.get(p.id, len(rank)), ))


def detect_summary(profile, rules=None):
    """A short line for Settings: the programs and hosts that switch the app on (never a title or URL)."""
    d = with_rules(profile, rules).detect
    parts = []
    if d.exe:
        parts.append(", ".join(d.exe))
    if d.host:
        parts.append(", ".join(d.host) + " in Chrome, Edge, Brave, Vivaldi or Opera")
    return " · ".join(parts) if parts else "Manual only"


# ------------------------------------------------------------------ the host worker
class AddressHosts(AddressVerdicts):
    """DD-BUG-012's address-bar worker, keeping the host (lower case) instead of Onshape's verdict, so every profile
    matches against one read. ``lookup(hwnd, key)`` -> (known, host or None); never blocks."""

    def _read(self, hwnd):
        reader = self._reader
        if reader is None:
            from .browser_url import address_host as reader
        host = reader(hwnd)
        return str(host).lower().rstrip(".") if host else None


_shared_hosts = None


def shared_address_hosts():
    """The one host worker of the live app: the detector's poll and the injector's gate share its cache."""
    global _shared_hosts
    if _shared_hosts is None:
        _shared_hosts = AddressHosts()
    return _shared_hosts


# ------------------------------------------------------------------ Win32 (live only)
if sys.platform == "win32":
    from ctypes import wintypes as W

    class GUITHREADINFO(ctypes.Structure):
        _fields_ = [("cbSize", W.DWORD), ("flags", W.DWORD), ("hwndActive", W.HWND), ("hwndFocus", W.HWND),
                    ("hwndCapture", W.HWND), ("hwndMenuOwner", W.HWND), ("hwndMoveSize", W.HWND),
                    ("hwndCaret", W.HWND), ("rcCaret", W.RECT)]
else:  # pragma: no cover
    W = None
    GUITHREADINFO = None


class AppWindows(OnshapeWindows):
    """The foreground reads and the gates for the active app profile (Windows). Exe names are cached per process id;
    titles are read, hashed into a cache key and dropped. ``set_profile`` is called on the injector thread."""

    def __init__(self, classes=CONTENT_CLASSES, verdicts=None, hosts=None):
        super().__init__(classes, verdicts)
        self.hosts = hosts if hosts is not None else shared_address_hosts()
        self.profile = None
        user = self.u
        user.GetGUIThreadInfo.restype, user.GetGUIThreadInfo.argtypes = W.BOOL, (W.DWORD, ctypes.POINTER(GUITHREADINFO))

    def set_profile(self, profile):
        self.profile = profile

    # -- primitives (tests override these)
    def window_from_point(self, point):
        return self.u.WindowFromPoint(W.POINT(int(point[0]), int(point[1])))

    def root(self, hwnd):
        return self.u.GetAncestor(hwnd, GA_ROOT)

    def title_key(self, hwnd):
        buffer = ctypes.create_unicode_buffer(1024)
        self.u.GetWindowTextW(hwnd, buffer, 1024)
        return (int(hwnd), hash(buffer.value))           # the title itself is never kept

    def onshape_title(self, hwnd):
        """Onshape's strict title rule (the fallback when the address bar can't be read). Never logged or kept."""
        buffer = ctypes.create_unicode_buffer(1024)
        self.u.GetWindowTextW(hwnd, buffer, 1024)
        return title_is_onshape(buffer.value)

    def host(self, hwnd):
        """(known, host) of a browser window's address bar, from the shared worker (never blocks)."""
        return self.hosts.lookup(hwnd, self.title_key(hwnd))

    def focus_pid(self):
        """The process of the foreground thread's focus window (or its active window), or 0."""
        hwnd = self.foreground()
        if not hwnd:
            return 0
        thread = self.u.GetWindowThreadProcessId(hwnd, None)
        info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
        if not thread or not self.u.GetGUIThreadInfo(thread, ctypes.byref(info)):
            return 0
        window = info.hwndFocus or info.hwndActive
        return self.pid(window) if window else 0

    # -- the gates
    def target_ok(self, point):
        if self.profile is None:
            return super().target_ok(point)
        return gate_target(self, self.profile, point)

    def keyboard_ok(self, point):
        profile = self.profile
        if profile is None:
            return super().keyboard_ok(point)
        root = self.foreground()
        exe = self.exe(self.pid(root)) if root else ""
        if is_browser(exe):
            return super().keyboard_ok(point)            # DD-SEC-001: UI Automation's document focus
        pid = self.pid(root) if root else 0
        return bool(pid) and self.focus_pid() == pid

    def keyboard_ok_fresh(self, point):
        """S3 decision (typed text after a chord): browser apps read UI Automation's document focus now (never the
        cache); desktop apps read GetGUIThreadInfo now (keyboard_ok never caches it)."""
        profile = self.profile
        root = self.foreground()
        exe = self.exe(self.pid(root)) if root else ""
        if profile is None or is_browser(exe):
            return super().keyboard_ok_fresh(point)
        return self.keyboard_ok(point)


def gate_target(windows, profile, point):
    """The cursor gate for ``profile`` over a windows object's primitives (pure apart from them)."""
    hwnd = windows.window_from_point(point)
    if not hwnd:
        return False
    root = windows.root(hwnd)
    if not root or root != windows.foreground():
        return False
    exe = windows.exe(windows.pid(root))
    if is_shell_exe(exe):
        return False                                      # S3 review DD-2: never a shell, terminal or Windows itself
    d = profile.detect
    if is_browser(exe):
        if not d.host:
            return False
        classes = d.content_class or CONTENT_CLASSES
        if profile.id == "onshape":
            classes = getattr(windows, "classes", classes) or classes    # settings.json onshape_content_classes
        if windows.class_name(hwnd) not in classes:
            return False                                  # never the tab strip, toolbar or bookmarks bar
        known, host = windows.host(root)
        if not known:
            return False
        if host is None:
            ok = profile.id == "onshape" and exe in ONSHAPE_BROWSERS and windows.onshape_title(root)
        else:
            ok = d.matches_host(host)
    else:
        ok = d.matches_exe(exe) and (not d.content_class or windows.class_name(hwnd) in d.content_class)
    # DD-SEC-003: a host read may be slow: the foreground must still be that window afterwards.
    return bool(ok) and windows.foreground() == root


class AppDetector:
    """Which app has the foreground (the Tk thread): ``detect(now, profiles)`` -> (id, matched_by). The hooks only mark
    the answer stale; a read happens then and at least every DETECT_POLL_SECONDS. ``focused()`` keeps Onshape mode's
    FocusWatcher contract (Onshape in front). Titles are never kept."""

    def __init__(self, windows=None, clock=time.monotonic, hook=True):
        self.windows = windows if windows is not None else AppWindows()
        self.u = getattr(self.windows, "u", None)
        self.clock = clock
        self._stale = True
        self._checked = -1e9
        self._value = (None, None)
        self._ids = None
        self._foreground = None
        self._name_hook = None
        self._name_pid = None
        self._hooks = []
        self._callbacks = ()
        hosts = getattr(self.windows, "hosts", None)
        listen = getattr(hosts, "listen", None)
        if callable(listen):
            listen(self._read_done)                      # a finished address read re-checks
        if not hook or _WINEVENTPROC is None or self.u is None:
            return

        @_WINEVENTPROC
        def on_foreground(_hook, _event, hwnd, _obj, _child, _thread, _time):
            self._stale = True

        @_WINEVENTPROC
        def on_name(_hook, _event, hwnd, obj, _child, _thread, _time):
            if obj == 0 and hwnd and hwnd == self._foreground:
                self._stale = True

        self._callbacks = (on_foreground, on_name)
        handle = self.u.SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, None, on_foreground, 0, 0,
                                        WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
        if handle:
            self._hooks.append(handle)

    def _read_done(self):
        self._stale = True

    def _hook_names(self, pid):
        if pid == self._name_pid:
            return
        if self._name_hook and self.u is not None:
            self.u.UnhookWinEvent(self._name_hook)
            self._name_hook = None
        self._name_pid = pid
        if pid and self.u is not None and len(self._callbacks) > 1:
            self._name_hook = self.u.SetWinEventHook(EVENT_OBJECT_NAMECHANGE, EVENT_OBJECT_NAMECHANGE, None,
                                                     self._callbacks[1], pid, 0, WINEVENT_OUTOFCONTEXT) or None

    def pause(self):
        """No app is watched (every mode Off): drop the browser's name hook and the foreground; nothing is read until
        ``detect`` is called with profiles again."""
        self._hook_names(0)
        self._foreground = None
        self._stale = True
        self._value = (None, None)
        self._ids = None

    def detect(self, now, profiles):
        """(id, 'exe' | 'host') of the app in front among ``profiles`` (already in Settings order, rules merged), or
        (None, None). With no profiles nothing is read."""
        profiles = list(profiles or ())
        if not profiles:
            self.pause()
            return None, None
        ids = tuple((p.id, p.detect) for p in profiles)
        now = self.clock() if now is None else now
        if not self._stale and ids == self._ids and now - self._checked < DETECT_POLL_SECONDS:
            return self._value
        self._stale = False
        self._checked = now
        self._ids = ids
        w = self.windows
        hwnd = w.foreground()
        self._foreground = hwnd
        pid = w.pid(hwnd) if hwnd else 0
        exe = w.exe(pid) if pid else ""
        browser = bool(pid) and is_browser(exe)
        self._hook_names(pid if browser else 0)
        host = None
        if browser and any(p.detect.host for p in profiles):
            known, host = w.host(hwnd)
            if known and host is None and any(p.id == "onshape" for p in profiles) \
                    and exe in ("chrome.exe", "msedge.exe") and w.onshape_title(hwnd):
                self._value = ("onshape", "host")        # DD-SEC-002: the strict title rule, unreadable address only
                return self._value
        self._value = match_app(profiles, exe, host)
        return self._value

    def focused(self, now=None, profiles=None):
        """FocusWatcher's contract: Onshape (the built-in profile) has the foreground."""
        if profiles is None:
            from .onshape_app import builtin_onshape_profile
            profiles = [builtin_onshape_profile()]
        return self.detect(now, profiles)[0] == "onshape"

    def close(self):
        self._hook_names(0)
        if self.u is not None:
            for handle in self._hooks:
                self.u.UnhookWinEvent(handle)
        self._hooks = []
        _RETIRED.extend(self._callbacks)


__all__ = ["AddressHosts", "AppDetector", "AppWindows", "BROWSERS", "detect_summary", "gate_target", "host_matches",
           "is_browser", "match_app", "ordered", "with_rules"]
