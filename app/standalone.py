"""Independent Windows tray application; no external interpreter is needed when frozen.

Desktop v5 (FLOATING_KNOB.md section 6): the live app is a tray icon plus the floating
knob. The Tk root stays withdrawn; ControlCenterApp runs with chrome=False and a
KnobOverlay that slides in from the left edge when the physical knob is touched.
Tray menu: "Knob connected" / "Knob not found" and the device status (both disabled),
Show knob (default, left click: peek 2.5 s), Settings…, Disconnect/Connect knob, Quit.
A second launch or the Start-menu --show opens Settings; if the tray fails, Settings
opens with Connect/Disconnect and Quit. A controller.notice (a failed action) becomes
one tray balloon; the notice itself keeps its v4 lifetime, so the knob shows "Last
action failed" until the next action.

App and tray icons (APP_ICON.md): ui.apply_app_icon gives the Tk root the app photos and
every mapped Tk window (Settings) the .ico's own frames for its DPI; the tray shows the designer's .ico for the taskbar theme (dark/light)
and the knob's presence (connected/missing), always loaded from the .ico file at the
small-icon size, with the tooltip and the menu header switching together.

Desktop v7 (DESKTOP_STAGE K4; CONTROL_CENTER_V5 K3; WP10):
- **Process settings** (K4 4.7.2, with the refresh review's AR-1 / AR-2): ``timeBeginPeriod(1)``
  (``timeEndPeriod`` at exit), the Windows 11 power-throttling opt-out (execution speed and
  ignore-timer-resolution, i.e. HighQoS and "always honour timer resolution"),
  ``sys.setswitchinterval(0.001)`` (never below 1 ms), and a startup self-check of three 8 ms
  waits (each <= 9.5 ms, else "timer resolution not honoured" is logged): ``apply_process_settings``.
- **The stage** (``NanoD-stage``: the explorer and Up next) starts right after the floating knob,
  inside the same try / finally, and is closed with it (``start_stage`` / ``close_stage``; a stage
  that cannot start answers every open with ``refused(device)``).
- **The picker's GPU chrome** (CAROUSEL.md 12.4; lead ruling R-h, wired by the lead's decision of
  2026-09-26, closing WP7c-D11): ``main`` installs it once (``install_picker_chrome``) right before
  ControlCenterApp builds the WindowsAdapter, whose CarouselPresenter reads the installed factory
  when it is made. Any failure leaves the CPU chrome. The fast path warms its device at a knob
  touch together with the stage's (``ui.FastPath``, ``WindowsAdapter.note_touch``).
- **Tray**: the Settings item is ``Open Settings…`` (``tray.open_settings``, it opens on the status
  strip); the taskbar theme follows ``WM_SETTINGCHANGE`` "ImmersiveColorSet" on pystray's own
  window (it only queues ``theme``) with a 30 s poll as the backstop (K4 20.3).
- **status.json** gains ``frames`` (K4 6.2: ``frames.knob``, ``frames.picker``, ``frames.toast``,
  ``frames.explorer`` / ``frames.upnext``), ``stage`` and ``process``.
- ``--smoke-test --headless`` runs every check without Tk and without showing anything (a stand-in
  root drives the app; the native windows it checks are created hidden, as before).
"""
from pathlib import Path
import argparse
import collections
import ctypes
import datetime
import faulthandler
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import queue
import sys
import threading
import time


# ------------------------------------------------------------------ crash diagnostics
# The windowed (frozen) build has no stderr: a native abort (Py_FatalError,
# Tcl_Panic) or a hard fault used to leave nothing but a WER event. crash.log
# gets faulthandler's tracebacks and, through the C runtime's stderr, the
# "Fatal Python error" text itself; Python-level failures go to app.log.
CRASH_LOG_NAME = 'crash.log'
CRASH_LOG_LIMIT = 1_000_000          # bytes; rotated once to crash.log.1 at startup
CALLBACK_LOG_INTERVAL = 30.0         # seconds between reports of one repeating failure
REQUEST_POLL_MS = 100                # tray requests are handled on the Tk thread this often
# Tray (desktop v5). The app is Desk Dial (rename-desk-dial.md A1, A2); TRAY_NAME is pystray's internal
# icon and window-class name, never shown, and keeps the old slug like the other internal identifiers (H8).
TRAY_NAME = 'NanoDControlCenter'
TRAY_TIP_PREFIX = 'Desk Dial · '
TRAY_TIP_LIMIT = 127                 # NOTIFYICONDATAW.szTip: 128 UTF-16 units including the NUL
MENU_STATUS_LIMIT = 80               # the disabled status line at the top of the menu
BALLOON_TITLE = 'Desk Dial'
BALLOON_TEXT_LIMIT = 255             # NOTIFYICONDATAW.szInfo: 256 UTF-16 units including the NUL
NOTICE_INTERVAL = 10.0               # seconds between two notice balloons (the newest waits)
PEEK_SECONDS = 2.5                   # tray "Show knob"
WM_RBUTTONUP = 0x0205
ASFW_ANY = -1
# App and tray icons (APP_ICON.md), relative to the bundle (ui.APP_DIR).
APP_ICON_DIR = Path('assets') / 'app-icon'
APP_ICON_FILE = APP_ICON_DIR / 'ico' / 'nano-d-app.ico'
APP_ICON_PNGS = (APP_ICON_DIR / 'png' / 'nano-d-app-256.png', APP_ICON_DIR / 'png' / 'nano-d-app-32.png')
APP_ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 256)
TRAY_ICON_SIZES = (16, 20, 24, 32)
TRAY_THEMES = ('dark', 'light')
TRAY_HEADERS = {True: 'Knob connected', False: 'Knob not found'}
TRAY_OPEN_SETTINGS = 'Open Settings…'   # tray.open_settings (VOC 9.3; K3 14.1)
THEME_POLL_MS = 30000                # backstop: the taskbar theme is re-read this often (K4 20.3)
THEME_KEY = r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'
THEME_VALUE = 'SystemUsesLightTheme'
WM_SETTINGCHANGE = 0x001A
THEME_SETTING = 'ImmersiveColorSet'  # WM_SETTINGCHANGE's lParam when the colour mode changes
# Process settings (K4 4.7.2).
SWITCH_INTERVAL_S = 0.001            # never below 1 ms (AR-1)
PROCESS_POWER_THROTTLING = 4         # PROCESS_INFORMATION_CLASS ProcessPowerThrottling
POWER_THROTTLING_VERSION = 1
POWER_THROTTLING_EXECUTION_SPEED = 0x1
POWER_THROTTLING_IGNORE_TIMER_RESOLUTION = 0x4
TIMER_CHECK_WAIT_MS = 8
TIMER_CHECK_LIMIT_MS = 9.5
TIMER_CHECK_WAITS = 3
WM_TRAY_ICON_FILE = 0x0400 + 0x70    # WM_USER+112 to pystray's window: swap the .ico (pystray: +10, +11)
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
SM_CXSMICON = 49
GUI_BASELINE_SECONDS = 2.0           # smoke: how long GDI/USER counts may take to return
DIB_REBUILD_SETTLE_SECONDS = 0.5     # smoke: how long the counts may take to settle after a DIB rebuild
_crash_log = None                    # open for the process lifetime (faulthandler writes to its fd)
_crash_log_path = None
_log = logging.getLogger('nanod.crash')


def open_crash_log(logs):
    """logs/crash.log opened unbuffered for append, headed with time, pid and
    executable; None when it cannot be opened. Never raises."""
    path = Path(logs) / CRASH_LOG_NAME
    try:
        if path.stat().st_size > CRASH_LOG_LIMIT:
            os.replace(path, path.with_name(CRASH_LOG_NAME + '.1'))
    except OSError:
        pass
    try:
        stream = open(path, 'ab', buffering=0)
    except OSError:
        return None
    try:
        now = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
        header = (f'=== {now} pid={os.getpid()} frozen={bool(getattr(sys, "frozen", False))} '
                  f'python={sys.version.split()[0]} exe={sys.executable} argv={sys.argv[1:]} ===\n')
        stream.write(header.encode('utf-8', 'replace'))
    except OSError:
        pass
    return stream


def redirect_c_stderr(path, force=False):
    """Point the C runtime's stderr at ``path`` (append, unbuffered) when it has no
    usable descriptor, as in the windowed build, so Py_FatalError and Tcl_Panic
    text reaches the crash log (Py_FatalError writes only there, then disables
    faulthandler before abort()). ``force`` redirects even a working stderr.
    Returns True when redirected; never raises."""
    if os.name != 'nt':
        return False
    try:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        module = kernel.GetModuleHandleW
        module.restype, module.argtypes = ctypes.c_void_p, [ctypes.c_wchar_p]
        handle = module('ucrtbase.dll')      # the CRT python3x.dll already uses
        if not handle:
            return False
        crt = ctypes.CDLL('ucrtbase.dll', handle=handle)
        iob = getattr(crt, '__acrt_iob_func')
        iob.restype, iob.argtypes = ctypes.c_void_p, [ctypes.c_uint]
        crt._fileno.restype, crt._fileno.argtypes = ctypes.c_int, [ctypes.c_void_p]
        crt._wfreopen.restype = ctypes.c_void_p
        crt._wfreopen.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p]
        crt.setvbuf.restype = ctypes.c_int
        crt.setvbuf.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_size_t]
        stream = iob(2)
        if not stream or (not force and crt._fileno(stream) >= 0):
            return False
        if not crt._wfreopen(str(path), 'a', stream):
            return False
        crt.setvbuf(stream, None, 4, 0)      # _IONBF: nothing is lost in a buffer on abort()
        return True
    except Exception:
        return False


class RateLimiter:
    """Log a repeating failure at most once per interval per key, with a count
    of what was suppressed in between."""

    def __init__(self, interval=CALLBACK_LOG_INTERVAL, clock=time.monotonic, limit=256):
        self.interval, self.clock, self.limit = interval, clock, limit
        self._seen = {}

    def allow(self, key):
        """(log now?, occurrences since the last report, this one included)."""
        now = self.clock()
        last, count = self._seen.get(key, (None, 0))
        count += 1
        if last is None or now - last >= self.interval:
            if key not in self._seen and len(self._seen) >= self.limit:
                self._seen.clear()
            self._seen[key] = (now, 0)
            return True, count
        self._seen[key] = (last, count)
        return False, count


def _failure_key(exc_type, tb):
    """Where a failure happened: its type and innermost frame."""
    while tb is not None and tb.tb_next is not None:
        tb = tb.tb_next
    code = tb.tb_frame.f_code if tb is not None else None
    return (getattr(exc_type, '__name__', str(exc_type)),
            code.co_filename if code else '', tb.tb_lineno if tb is not None else 0)


class CallbackErrorReporter:
    """root.report_callback_exception: logs a failing Tk callback with its traceback,
    each distinct failure at most once per interval (with a repeat count), so a
    callback failing on every 25 ms tick cannot flood app.log. Never raises."""

    def __init__(self, logger=None, interval=CALLBACK_LOG_INTERVAL, clock=time.monotonic):
        self.logger = logger or logging.getLogger('nanod.ui')
        self.limiter = RateLimiter(interval, clock)

    def __call__(self, exc_type, exc, tb):
        try:
            allowed, count = self.limiter.allow(_failure_key(exc_type, tb))
            if allowed:
                self.logger.error('UI callback failed (%d occurrence(s) since the last report)',
                                  count, exc_info=(exc_type, exc, tb))
        except Exception:
            pass


def install_exception_hooks(logger=None):
    """Log uncaught exceptions of the main thread (sys.excepthook), of other threads
    (threading.excepthook) and "Exception ignored" ones (sys.unraisablehook, rate
    limited: e.g. a Tk object finalized off the Tk thread). The previous hooks
    still run after logging. Returns a function that restores them."""
    log = logger or _log
    previous = (sys.excepthook, threading.excepthook, sys.unraisablehook)
    limiter = RateLimiter()
    busy = threading.local()

    def guarded(action):
        if getattr(busy, 'active', False):
            return  # a failure while logging a failure: never recurse
        busy.active = True
        try:
            action()
        except Exception:
            pass
        finally:
            busy.active = False

    def main_hook(exc_type, exc, tb):
        guarded(lambda: log.critical('Uncaught exception', exc_info=(exc_type, exc, tb)))
        guarded(lambda: previous[0](exc_type, exc, tb))

    def thread_hook(args):
        if args.exc_type is not SystemExit:
            name = getattr(args.thread, 'name', '?')
            guarded(lambda: log.error('Uncaught exception in thread %s', name,
                                      exc_info=(args.exc_type, args.exc_value, args.exc_traceback)))
        guarded(lambda: previous[1](args))

    def unraisable_hook(unraisable):
        def report():
            allowed, count = limiter.allow(_failure_key(unraisable.exc_type, unraisable.exc_traceback))
            if allowed:
                where = unraisable.err_msg or 'Exception ignored'
                log.warning('%s: %s (%d occurrence(s) since the last report)',
                            where, _safe_repr(unraisable.object), count,
                            exc_info=(unraisable.exc_type, unraisable.exc_value, unraisable.exc_traceback))
        guarded(report)
        guarded(lambda: previous[2](unraisable))

    sys.excepthook, threading.excepthook, sys.unraisablehook = main_hook, thread_hook, unraisable_hook

    def restore():
        sys.excepthook, threading.excepthook, sys.unraisablehook = previous
    return restore


def _safe_repr(value):
    try:
        return repr(value)[:200]
    except Exception:
        return f'<{type(value).__name__}>'


def enable_crash_diagnostics(logs, capture_c_stderr=None):
    """Startup crash diagnostics; every step is optional and none can stop the app.

    faulthandler (all threads) appends to logs/crash.log, kept open for the
    process lifetime; the C runtime's stderr joins it when it has none
    (``capture_c_stderr`` None = only in the windowed build); uncaught Python
    exceptions are logged. Returns what was enabled.
    """
    global _crash_log, _crash_log_path
    state = {'crashLog': None, 'faulthandler': False, 'cStderr': False, 'hooks': False}
    if getattr(sys, 'frozen', False):
        logging.raiseExceptions = False  # a failing log handler never prints or raises
    try:
        stream = open_crash_log(logs)
        if stream is not None:
            _crash_log, _crash_log_path = stream, Path(stream.name)
            state['crashLog'] = str(_crash_log_path)
            faulthandler.enable(file=stream, all_threads=True)
            state['faulthandler'] = True
            if capture_c_stderr is None:
                capture_c_stderr = sys.stderr is None
            if capture_c_stderr:
                state['cStderr'] = redirect_c_stderr(_crash_log_path)
    except Exception:
        pass
    try:
        install_exception_hooks()
        state['hooks'] = True
    except Exception:
        pass
    return state


class RetryPolicy:
    def __init__(self):
        self.enabled = True
        self.attempts = 0
        self.due = 0
        self.inflight = False

    def failed(self, now):
        self.inflight = False
        self.attempts += 1
        self.due = now + min(30, 2 ** min(self.attempts, 5))

    def ready(self):
        self.inflight = False
        self.attempts = 0

    def can_attempt(self, now):
        return self.enabled and not self.inflight and now >= self.due


def matching_port(ports):
    matches = [p.device for p in ports if (p.vid, p.pid) == (0x239A, 0x8010)
               and (p.serial_number or '').upper() == 'NANO_D']
    return matches[0] if len(matches) == 1 else None


def fresh_controller(previous, runtime=None):
    """A clean controller that continues the previous one's ids and presentation.

    With `runtime`, the controller is attached before its first entry, so that
    entry is decorated from the new controller's own state (art identity), not
    from the controller being replaced.
    """
    from control_center.controller import Controller
    current = Controller()
    current.serial = previous.serial
    current.control_id = previous.control_id
    # Presentation carries over before the first entry, so that entry's frame
    # is decorated and a later flash never reuses an earlier sequence number.
    current.decorate = previous.decorate
    current.feedback_seq = previous.feedback_seq
    current.effects.clear()
    if runtime is not None:
        runtime.attach(current)
    current._enter()
    return current


def credential_file_info(directory):
    """Identify encrypted store differences without exposing credential values."""
    path = directory / 'credentials.bin'
    try:
        encrypted = path.read_bytes()
        return {'exists': True, 'bytes': len(encrypted), 'sha256': hashlib.sha256(encrypted).hexdigest()}
    except FileNotFoundError:
        return {'exists': False}
    except OSError as exc:
        return {'error': type(exc).__name__}


def firmware_summary(capabilities):
    """Presentation-relevant firmware capabilities, or None when no knob reported any."""
    if not isinstance(capabilities, dict) or not capabilities:
        return None
    from control_center.device import presentation_level
    artwork = capabilities.get('artwork')
    glyphs = capabilities.get('glyphs')
    return {'presentation': presentation_level(capabilities),
            'controlCenter': capabilities.get('controlCenter'),
            'glyphs': glyphs if isinstance(glyphs, str) else None,
            'artwork': (artwork.get('composited') or bool(artwork.get('version')))
                       if isinstance(artwork, dict) else None}


def media_status(runtime):
    """status.json "media" (ARTWORK2.md section 9): per kind wanted, present, uploads,
    hits, errors, failedKeys and lastError; None when the runtime has no artwork2 support."""
    source = getattr(runtime, 'media_status', None)
    if not callable(source):
        return None
    try:
        status = source()
    except Exception:
        return None
    return status if isinstance(status, dict) else None


# ------------------------------------------------------------------ tray (desktop v5)
def utf16_cut(text, limit):
    """``text`` cut to at most ``limit`` UTF-16 code units, with an ellipsis when cut."""
    text = str(text)
    if len(text.encode('utf-16-le')) // 2 <= limit:
        return text
    text = text[:limit]              # every character is at least one UTF-16 unit
    while text and len((text + '…').encode('utf-16-le')) // 2 > limit:
        text = text[:-1]
    return text.rstrip() + '…'


def _one_line(text):
    return ' '.join(str(text or '').split())


def tray_header(present):
    """The tray's knob state (APP_ICON.md section 5): the menu header and the tooltip's text."""
    return TRAY_HEADERS[bool(present)]


def tray_tooltip(present):
    """The tray icon's tooltip (APP_ICON.md section 5, which supersedes FLOATING_KNOB.md
    section 6's device-status tooltip): 'Desk Dial · Knob connected' or 'Desk Dial · Knob
    not found', at most 127 UTF-16 units. The detailed status is the menu's second line."""
    return utf16_cut(TRAY_TIP_PREFIX + tray_header(present), TRAY_TIP_LIMIT)


def tray_icon_file(theme, present, app_dir=None):
    """The tray .ico for the taskbar ``theme`` ('dark' or 'light') and the knob's presence:
    assets/app-icon/ico/nano-d-tray-{theme}-{connected|missing}.ico (under ``app_dir``)."""
    theme = theme if theme in TRAY_THEMES else 'dark'
    path = APP_ICON_DIR / 'ico' / f'nano-d-tray-{theme}-{"connected" if present else "missing"}.ico'
    return Path(app_dir) / path if app_dir is not None else path


def tray_png(theme, present, app_dir=None, size=32):
    """The same glyph as a PNG: the small PIL image pystray's Icon still needs (the Win32
    handle always comes from the .ico, see make_tray_icon)."""
    theme = theme if theme in TRAY_THEMES else 'dark'
    path = APP_ICON_DIR / 'png' / f'nano-d-tray-{theme}-{"connected" if present else "missing"}-{size}.png'
    return Path(app_dir) / path if app_dir is not None else path


def knob_present(runtime):
    """APP_ICON.md section 5: 'connected' while the knob is connected (connecting-ready, or
    claimed and ready); 'missing' with no knob, while reconnecting, with the bridge closed or
    after a deliberate Disconnect. Runtime.device_connected is exactly that."""
    return bool(getattr(runtime, 'device_connected', False))


def taskbar_theme(winreg_module=None):
    """The taskbar's theme (APP_ICON.md section 6): HKCU ...\\Themes\\Personalize
    SystemUsesLightTheme 1 -> 'light', 0 -> 'dark'; missing or unreadable -> 'dark'. Read only;
    never raises."""
    try:
        if winreg_module is None:
            import winreg as winreg_module
        with winreg_module.OpenKey(winreg_module.HKEY_CURRENT_USER, THEME_KEY) as key:
            value, kind = winreg_module.QueryValueEx(key, THEME_VALUE)
        if kind == winreg_module.REG_DWORD and value == 1:
            return 'light'
    except Exception:
        pass
    return 'dark'


def connect_label(connected):
    """The dynamic tray item: Disconnect while connected or connecting, else Connect."""
    return 'Disconnect knob' if connected else 'Connect knob'


def tray_menu_model(status, connected, present=False):
    """The tray menu, top to bottom: (text, request or None, enabled, default).

    The request strings are queued for the Tk thread (handle_requests). The header
    ('Knob connected' / 'Knob not found', APP_ICON.md section 5) and the detailed device
    status are disabled lines; Show knob is the default item (a left click)."""
    return ((tray_header(present), None, False, False),
            (utf16_cut(_one_line(status) or 'Knob disconnected', MENU_STATUS_LIMIT), None, False, False),
            ('Show knob', 'peek', True, True),
            (TRAY_OPEN_SETTINGS, 'settings', True, False),
            (connect_label(connected), 'connect', True, False),
            ('Quit', 'quit', True, False))


class TrayState:
    """What the tray thread reads when pystray (re)builds the menu: plain values the Tk
    thread sets (never tkinter or the app from the tray thread)."""

    def __init__(self, status='Knob disconnected', connected=False, present=False):
        self.status, self.connected, self.present = status, connected, bool(present)

    def model(self):
        return tray_menu_model(self.status, self.connected, self.present)


def build_tray_menu(pystray, state, put):
    """A pystray.Menu over ``state``: every text is read when the menu is built (after each
    menu action, and before the menu opens); every action only calls ``put(request)``."""
    def entry(index):
        _text, request, enabled, default = tray_menu_model('', False)[index]
        action = (lambda *_: put(request)) if request else None
        return pystray.MenuItem(lambda _item: state.model()[index][0], action,
                                enabled=enabled, default=default)
    return pystray.Menu(*(entry(index) for index in range(len(tray_menu_model('', False)))))


class TrayIconApi:
    """The Win32 calls behind the tray icon, declared on private user32/shell32 WinDLL
    instances with x64-correct prototypes (pystray declares its own on ctypes.windll.user32;
    separate instances keep both sets of argtypes intact). ``small_icon_size`` is
    GetSystemMetricsForDpi(SM_CXSMICON, GetDpiForSystem()), else GetSystemMetrics."""

    def __init__(self):
        self._user32 = self._shell32 = None

    def _u(self):
        if self._user32 is None:
            u = ctypes.WinDLL('user32', use_last_error=True)
            u.LoadImageW.restype = ctypes.c_void_p
            u.LoadImageW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_uint)
            u.DestroyIcon.restype, u.DestroyIcon.argtypes = ctypes.c_int, (ctypes.c_void_p,)
            u.GetSystemMetrics.restype, u.GetSystemMetrics.argtypes = ctypes.c_int, (ctypes.c_int,)
            u.PostMessageW.restype = ctypes.c_int
            u.PostMessageW.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)
            try:
                u.GetSystemMetricsForDpi.restype = ctypes.c_int
                u.GetSystemMetricsForDpi.argtypes = (ctypes.c_int, ctypes.c_uint)
                u.GetDpiForSystem.restype, u.GetDpiForSystem.argtypes = ctypes.c_uint, ()
            except AttributeError:
                pass                     # before Windows 10 1607: GetSystemMetrics only
            self._user32 = u
        return self._user32

    def small_icon_size(self):
        u = self._u()
        size = 0
        try:
            size = int(u.GetSystemMetricsForDpi(SM_CXSMICON, u.GetDpiForSystem()))
        except (AttributeError, OSError):
            size = 0
        if size <= 0:
            size = int(u.GetSystemMetrics(SM_CXSMICON))
        return size if size > 0 else 16

    def load(self, path, size):
        """LoadImageW(NULL, path, IMAGE_ICON, size, size, LR_LOADFROMFILE): Windows picks the
        .ico frame drawn for that size. An HICON (int) or None."""
        return self._u().LoadImageW(None, str(path), IMAGE_ICON, int(size), int(size), LR_LOADFROMFILE) or None

    def destroy(self, handle):
        return bool(self._u().DestroyIcon(handle))

    def post(self, hwnd, message):
        return bool(self._u().PostMessageW(hwnd, message, 0, 0))

    def icon_count(self, path):
        """The icons a PE file embeds: ExtractIconExW(path, -1, NULL, NULL, 0); none are loaded."""
        if self._shell32 is None:
            shell = ctypes.WinDLL('shell32', use_last_error=True)
            shell.ExtractIconExW.restype = ctypes.c_uint
            shell.ExtractIconExW.argtypes = (ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                                             ctypes.c_uint)
            self._shell32 = shell
        return int(self._shell32.ExtractIconExW(str(path), -1, None, None, 0))


def theme_change_handler(on_theme, read=None):
    """pystray's handler for WM_SETTINGCHANGE (tray thread): when lParam names
    "ImmersiveColorSet" (the taskbar's colour mode changed) it only calls ``on_theme()`` (which
    queues 'theme' for the Tk thread); anything else is ignored. Returns 0; never raises."""
    read = read or (lambda address: ctypes.wstring_at(address, len(THEME_SETTING) + 1))

    def handler(wparam, lparam):
        try:
            if lparam and read(lparam).split('\0', 1)[0] == THEME_SETTING:
                on_theme()
        except Exception:
            pass
        return 0
    return handler


def make_tray_icon(pystray, image, state, put, icon_file=None, icon_api=None, on_theme=None):
    """The tray icon. Its menu is also rebuilt on the tray thread right before it opens
    (a right click), so the status lines and Connect/Disconnect are current; the menu is
    never rebuilt from the Tk thread (that would race TrackPopupMenuEx).

    With ``icon_file`` (APP_ICON.md item 4) the Win32 handle always comes from that .ico
    (LoadImageW at the small-icon size, so the hand-tuned 16-24 px frames are used), never
    from pystray re-serializing ``image`` (which drops them); ``image`` is still given
    because pystray needs one. ``set_icon_file(path)`` (Tk thread) only records the path and
    posts WM_TRAY_ICON_FILE; the tray thread then swaps the handle through pystray's
    ``_update_icon`` (so the old handle is destroyed as before)."""
    base = pystray.Icon
    hook_menu = callable(getattr(base, '_on_notify', None))
    hook_icon = icon_file is not None and callable(getattr(base, '_assert_icon_handle', None))
    cls = base
    if hook_menu or hook_icon:
        class TrayIcon(base):
            if hook_menu:
                def _on_notify(self, wparam, lparam):
                    if lparam == WM_RBUTTONUP:
                        try:
                            self.update_menu()
                        except Exception:
                            pass
                    return super()._on_notify(wparam, lparam)

            if hook_icon:
                # pystray's setup thread (show), the tray thread (swaps) and the Tk thread (tooltip)
                # all reach the handle and the notify icon; they take this lock.
                _icon_lock = threading.RLock()
                _icon_api = None
                _icon_file = None                  # the .ico whose handle is loaded
                _wanted_icon_file = None           # the .ico the Tk thread asked for
                _nim_added = False                 # NIM_ADD done (pystray sets visible only after it)

                def _assert_icon_handle(self):
                    """A no-op while a handle exists; else LoadImageW of the wanted .ico at the
                    small-icon size. Never serializes the PIL image."""
                    with self._icon_lock:
                        if getattr(self, '_icon_handle', None):
                            return
                        path = self._wanted_icon_file
                        handle = None
                        try:
                            handle = self._icon_api.load(path, self._icon_api.small_icon_size())
                        except Exception:
                            logging.getLogger('nanod.tray').warning('Tray icon %s could not be loaded', path,
                                                                    exc_info=True)
                        if not handle:
                            logging.getLogger('nanod.tray').warning('Tray icon %s did not load', path)
                        self._icon_handle = handle or None
                        self._icon_file = path

                def _update_icon(self):
                    with self._icon_lock:
                        return super()._update_icon()

                def _release_icon(self):
                    with self._icon_lock:
                        return super()._release_icon()

                def _show(self):
                    """NIM_ADD under the lock, so the handle it passes is never destroyed or swapped
                    half way. A tooltip the Tk thread set meanwhile is sent right after it."""
                    with self._icon_lock:
                        shown_title = getattr(self, '_title', None)
                        result = super()._show()
                        self._nim_added = True
                        if getattr(self, '_title', None) != shown_title:
                            self._update_title()
                        return result

                def _hide(self):
                    with self._icon_lock:
                        self._nim_added = False
                        return super()._hide()

                @property
                def title(self):
                    return getattr(self, '_title', None)

                @title.setter
                def title(self, value):
                    """Tk thread; never waits for the lock (NIM_ADD can be slow at sign-in). pystray
                    updates a tooltip only while ``visible``, which it sets after NIM_ADD returns,
                    so one set in between was lost: here the title is stored first and NIM_ADD's
                    flag read second, and _show does the reverse, so either this NIM_MODIFY or
                    _show's sends it (at worst both)."""
                    if value != getattr(self, '_title', None):
                        self._title = value
                        if self._nim_added:
                            self._update_title()

                def set_icon_file(self, path):
                    """Tk thread: show another .ico (theme or knob state changed). True when it
                    changed; the swap itself happens on the tray thread."""
                    path = str(path)
                    if path == self._wanted_icon_file:
                        return False
                    self._wanted_icon_file = path
                    hwnd = getattr(self, '_hwnd', None)
                    if hwnd:
                        try:
                            if not self._icon_api.post(hwnd, WM_TRAY_ICON_FILE):
                                logging.getLogger('nanod.tray').warning('Tray icon change could not be posted')
                        except Exception:
                            logging.getLogger('nanod.tray').warning('Tray icon change could not be posted',
                                                                    exc_info=True)
                    return True

                def _on_icon_file(self, wparam, lparam):
                    """Tray thread (WM_TRAY_ICON_FILE): load the wanted .ico, destroying the old
                    handle. Keyed on the loaded handle and NIM_ADD, not on ``visible`` (pystray sets
                    it only after NIM_ADD): with a handle, or once added, _update_icon swaps it and
                    sends NIM_MODIFY (a no-op before NIM_ADD; the locked _show then adds the new
                    handle); with neither, the next show loads the wanted file."""
                    with self._icon_lock:
                        if self._wanted_icon_file != self._icon_file and (
                                getattr(self, '_icon_handle', None) or self._nim_added):
                            self._update_icon()
                    return 0
        cls = TrayIcon
    icon = cls(TRAY_NAME, image, tray_tooltip(getattr(state, 'present', False)),
               menu=build_tray_menu(pystray, state, put))
    handlers = getattr(icon, '_message_handlers', None)
    if hook_icon:
        icon._icon_api = icon_api if icon_api is not None else TrayIconApi()
        icon._wanted_icon_file = str(icon_file)
        if isinstance(handlers, dict):
            handlers[WM_TRAY_ICON_FILE] = icon._on_icon_file
    if on_theme is not None and isinstance(handlers, dict):
        # K4 20.3: pystray's window is a top-level popup, so it receives the broadcast.
        handlers[WM_SETTINGCHANGE] = theme_change_handler(on_theme)
    return icon


def route_request(command, handlers):
    """Run one queued tray request on the Tk thread. True when it was 'quit'."""
    handler = handlers.get(command)
    if handler is not None:
        handler()
    return command == 'quit'


class NoticeBalloons:
    """controller.notice errors and app messages become tray balloons: at most one per
    ``interval`` seconds. A newer notice replaces a notice still waiting. App messages (the
    Apple Music authorization outcome, FLOATING_KNOB.md section 9.13) wait in their own queue,
    oldest first and ahead of a waiting notice; a notice never replaces one."""

    MESSAGE_LIMIT = 8                    # app messages kept while no balloon can be shown

    def __init__(self, interval=NOTICE_INTERVAL, clock=time.monotonic):
        self.interval, self.clock = interval, clock
        self.pending = None
        self.messages = collections.deque(maxlen=self.MESSAGE_LIMIT)
        self.last = None

    def offer(self, notice):
        text = _one_line(notice)
        if text:
            self.pending = text

    def offer_message(self, message):
        text = _one_line(message)
        if text:
            self.messages.append(text)

    def due(self):
        """The balloon text to show now, or None."""
        if self.pending is None and not self.messages:
            return None
        now = self.clock()
        if self.last is not None and now - self.last < self.interval:
            return None
        if self.messages:
            text = self.messages.popleft()
        else:
            text, self.pending = self.pending, None
        self.last = now
        return utf16_cut(text, BALLOON_TEXT_LIMIT)


class TrayPresenter:
    """The Tk thread's side of the tray: the menu state, the knob-state trio (tooltip, .ico
    and menu header, switched together and only when the knob's presence or the taskbar
    theme changes; APP_ICON.md section 5) and notice balloons (rate limited; only while the
    icon is shown).

    controller.notice is only read, never cleared: it keeps its v4 lifetime (until the
    next action clears it), so the knob's "Last action failed" line stays as long as
    before. Each notice becomes one balloon: the presenter remembers the notice it last
    saw and offers only a new one (an empty notice in between makes the same text new
    again). ``messages`` (the app's take_tray_messages(), e.g. an Apple Music authorization
    outcome) are each one balloon, in order, and never replaced by a notice."""

    def __init__(self, icon, state, balloons=None, log=None, theme='dark', app_dir=None):
        self.icon, self.state = icon, state
        self.balloons = balloons if balloons is not None else NoticeBalloons()
        self.log = log or logging.getLogger('nanod.tray')
        self.tip = getattr(icon, 'title', None)
        self.seen_notice = ''
        self.theme = theme if theme in TRAY_THEMES else 'dark'
        self.app_dir = app_dir
        self.icon_file = getattr(icon, '_wanted_icon_file', None)

    def _apply_knob_state(self):
        """Tooltip and .ico for state.present and the theme (the header is read from the state
        when the menu is built). Each is set only when it changes."""
        present = bool(getattr(self.state, 'present', False))
        tip = tray_tooltip(present)
        if tip != self.tip:
            try:
                self.icon.title = tip
                self.tip = tip
            except Exception:
                self.log.warning('Tray tooltip could not be updated', exc_info=True)
        setter = getattr(self.icon, 'set_icon_file', None)
        if callable(setter):
            path = str(tray_icon_file(self.theme, present, self.app_dir))
            if path != self.icon_file:
                try:
                    setter(path)
                    self.icon_file = path
                except Exception:
                    self.log.warning('Tray icon could not be switched', exc_info=True)

    def set_theme(self, theme):
        """The taskbar theme ('dark'/'light', polled every THEME_POLL_MS): swap the .ico live."""
        theme = theme if theme in TRAY_THEMES else 'dark'
        if theme == self.theme:
            return False
        self.theme = theme
        self._apply_knob_state()
        return True

    def update(self, status, connected, notice='', present=None, messages=()):
        """Publish the status (and, when given, the knob's presence), and offer a new
        ``notice`` and every ``messages`` text as balloons. True when a new notice was
        offered (it is shown now or, rate limited, later)."""
        self.state.status, self.state.connected = status, bool(connected)
        if present is not None:
            self.state.present = bool(present)
        self._apply_knob_state()
        for message in messages or ():
            self.balloons.offer_message(message)
        if not getattr(self.icon, 'visible', False):
            return False   # no tray (yet): a notice still pending is offered once it shows
        text = _one_line(notice)
        fresh = bool(text) and text != self.seen_notice
        self.seen_notice = text
        if fresh:
            self.balloons.offer(text)
        due = self.balloons.due()
        if due:
            try:
                self.icon.notify(due, BALLOON_TITLE)
            except Exception:
                self.log.warning('Tray notification failed', exc_info=True)
        return fresh


class NoTray:
    """Stands in for a tray icon that could not be created: never shown, nothing to stop."""
    visible = False
    title = None

    def stop(self):
        pass

    def notify(self, message, title=None):
        pass


def run_tray(icon, stopping, put, log=None):
    """The tray thread's body: icon.run(). When it raises, or returns although nobody asked
    it to stop (``stopping`` not set: Quit and shutdown set it first), 'fallback' is queued
    for the Tk thread, which opens Settings with Connect/Disconnect and Quit. Returns the
    request queued, or None."""
    log = log or logging.getLogger('nanod.tray')
    try:
        icon.run()
    except Exception:
        log.exception('Tray unavailable; opening Settings with Connect and Quit')
        put('fallback')
        return 'fallback'
    if not stopping.is_set():
        log.warning('Tray stopped unexpectedly; opening Settings with Connect and Quit')
        put('fallback')
        return 'fallback'
    return None


def start_tray(make_icon, stopping, put, log=None, thread_factory=threading.Thread):
    """Create the tray icon and run it (run_tray) on the 'NanoD-tray' thread. An icon that
    cannot even be created queues 'fallback' at once and a NoTray stands in. Returns the
    icon."""
    log = log or logging.getLogger('nanod.tray')
    try:
        icon = make_icon()
    except Exception:
        log.exception('Tray icon could not be created; opening Settings with Connect and Quit')
        put('fallback')
        return NoTray()
    thread_factory(target=run_tray, args=(icon, stopping, put, log), daemon=True, name='NanoD-tray').start()
    return icon


def stop_tray(icon, stopping):
    """Quit and shutdown: mark the stop as asked for (so run_tray does not fall back), then
    stop the icon. Never raises: a tray that failed must not block Quit."""
    stopping.set()
    try:
        icon.stop()
    except Exception:
        logging.getLogger('nanod.tray').warning('Tray icon did not stop cleanly', exc_info=True)


def tray_fallback(app, connect, quit_app, connected):
    """The tray failed (Tk thread): Settings gains Connect/Disconnect (labelled from
    ``connected()``) and Quit, so the app is never invisible and unquittable."""
    app.setup_actions = {'connect': connect, 'quit': quit_app,
                         'label': lambda: connect_label(connected())}
    app.setup()


def start_overlay(factory=None, log=None):
    """The floating knob (a started KnobOverlay), or None when it cannot be built.

    A failed start leaves the overlay disabled (its metrics say why); the app and the
    tray keep running either way."""
    log = log or logging.getLogger('nanod.overlay')
    try:
        if factory is None:
            from control_center.overlay import KnobOverlay as factory
        overlay = factory(log=log)
    except Exception:
        log.exception('Floating knob unavailable')
        return None
    try:
        if not overlay.start():
            log.warning('Floating knob disabled: %s', _safe_metrics(overlay).get('last_error'))
    except Exception:
        log.exception('Floating knob could not start')
    return overlay


def close_overlay(overlay):
    """overlay.close(), never raising (it is idempotent)."""
    if overlay is None:
        return
    try:
        overlay.close()
    except Exception:
        logging.getLogger('nanod.overlay').exception('Floating knob did not close cleanly')


def _safe_metrics(overlay):
    try:
        value = overlay.metrics()
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


# ------------------------------------------------------------------ desktop v7: the stage
def start_stage(speaker_hosts=None, log=None, factory=None):
    """The explorer / Up next presenter (K4 4.1): ``stage.scenes.start_music_stage`` (the
    ``NanoD-stage`` thread with both scenes and the art workers) wrapped as the runtime's
    ``MusicOverlay``. Started after the floating knob; never raises. A stage whose thread could not
    start answers every open with ``refused(device)`` (K3 13.5); an import or build failure gives a
    ``MusicOverlay`` without a presenter, which refuses the same way."""
    log = log or logging.getLogger('nanod.stage')
    from control_center.music_overlay import MusicOverlay

    def stage_log(message):
        try:
            log.info('%s', message)
        except Exception:
            pass
    try:
        if factory is None:
            from control_center.stage.scenes import start_music_stage as factory
        thread, presenter, art = factory(log=stage_log, speaker_hosts=speaker_hosts, covers_dir=None, fetch=True)
    except Exception:
        log.exception('Stage unavailable: the explorer and Up next run on the knob alone')
        return MusicOverlay(None)
    disabled = getattr(thread, 'disabled', None)
    if disabled:
        log.warning('Stage disabled: %s', disabled)
    return MusicOverlay(presenter, art=art, thread=thread)


def close_stage(stage):
    """stage.close() (the stage thread and the art workers), never raising; idempotent."""
    if stage is None:
        return
    try:
        stage.close()
    except Exception:
        logging.getLogger('nanod.stage').exception('Stage did not close cleanly')


# ------------------------------------------------------------------ desktop v7: the picker's GPU chrome
def install_picker_chrome(install=None, log=None):
    """The window picker's GPU chrome (CAROUSEL.md 12.4, K4 9.10; lead ruling R-h; WP7c-D11, wired by
    the lead's decision of 2026-09-26): ``picker_chrome.install()`` (the stage package; this file is
    its one sanctioned wiring point, K4 4.1) registers the chrome's factory with the carousel, and
    every CarouselPresenter made afterwards draws its chrome as DirectComposition visuals
    (``NANOD_PICKER_CHROME=cpu`` still keeps the CPU chrome). Nothing is created here: the device is
    made on the carousel's threads at the first open or a knob touch.

    Called once, by ``main``, right before ControlCenterApp builds the WindowsAdapter. Never raises:
    any failure (an import error, an ``install()`` that raises or answers False) is logged once and
    leaves the CPU chrome, with the factory uninstalled in case the install failed half-way. True
    when installed. ``install`` (tests) replaces ``picker_chrome.install``."""
    log = log or logging.getLogger('nanod.picker')
    try:
        if install is None:
            from control_center.stage import picker_chrome
            install = picker_chrome.install
        if install() is False:
            raise RuntimeError('install() answered False')
    except Exception as exc:
        try:
            log.warning('Picker GPU chrome not installed (%r): the picker keeps the CPU chrome', exc)
        except Exception:
            pass
        try:
            from control_center import carousel
            carousel.install_gpu_chrome(None)
        except Exception:
            pass
        return False
    try:
        log.info('Picker GPU chrome installed (CAROUSEL.md 12.4)')
    except Exception:
        pass
    return True


# ------------------------------------------------------------------ desktop v7: process settings
class _PowerThrottlingState(ctypes.Structure):
    _fields_ = [('Version', ctypes.c_ulong), ('ControlMask', ctypes.c_ulong), ('StateMask', ctypes.c_ulong)]


def timer_self_check(wait=None, clock=time.perf_counter, waits=TIMER_CHECK_WAITS):
    """K4 4.7.2 item 4: three 8 ms MsgWaitForMultipleObjectsEx waits, each measured; the result is
    honoured when every one took <= 9.5 ms (about 8.25 ms with 1 ms timers, about 16 ms without).
    ``wait(ms)`` defaults to the native call. Returns {"waitsMs": [...], "honoured": bool}."""
    if wait is None:
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        native = user32.MsgWaitForMultipleObjectsEx
        native.restype = ctypes.c_uint32
        native.argtypes = (ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32)
        wait = lambda ms: native(0, None, ms, 0, 0)   # noqa: E731  (no handles, no input: the timeout)
    measured = []
    for _ in range(waits):
        started = clock()
        wait(TIMER_CHECK_WAIT_MS)
        measured.append(round((clock() - started) * 1000.0, 3))
    return {'waitsMs': measured, 'honoured': all(ms <= TIMER_CHECK_LIMIT_MS for ms in measured)}


def apply_process_settings(log=None, check=True):
    """K4 4.7.2 at startup (the running instance only): timeBeginPeriod(1), the power-throttling
    opt-out (EXECUTION_SPEED | IGNORE_TIMER_RESOLUTION with StateMask 0: HighQoS and "always honour
    timer resolution" for a process whose windows are hidden or never focused), the 1 ms switch
    interval, then the self-check (logged once). Returns the record for status.json; never raises.
    ``restore_process_settings(record)`` undoes the timer period at exit."""
    log = log or logging.getLogger('nanod.process')
    record = {'timerPeriod1': False, 'powerThrottlingOptOut': False, 'switchInterval': None, 'selfCheck': None}
    try:
        sys.setswitchinterval(SWITCH_INTERVAL_S)
        record['switchInterval'] = sys.getswitchinterval()
    except Exception:
        pass
    if os.name != 'nt':
        return record
    try:
        winmm = ctypes.WinDLL('winmm')
        winmm.timeBeginPeriod.restype = ctypes.c_uint
        winmm.timeBeginPeriod.argtypes = (ctypes.c_uint,)
        record['timerPeriod1'] = winmm.timeBeginPeriod(1) == 0      # TIMERR_NOERROR
    except Exception:
        pass
    try:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.SetProcessInformation.restype = ctypes.c_int
        kernel.SetProcessInformation.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)
        state = _PowerThrottlingState(POWER_THROTTLING_VERSION,
                                      POWER_THROTTLING_EXECUTION_SPEED | POWER_THROTTLING_IGNORE_TIMER_RESOLUTION, 0)
        record['powerThrottlingOptOut'] = bool(kernel.SetProcessInformation(
            kernel.GetCurrentProcess(), PROCESS_POWER_THROTTLING, ctypes.byref(state), ctypes.sizeof(state)))
    except Exception:
        pass
    if check:
        try:
            record['selfCheck'] = timer_self_check()
        except Exception:
            record['selfCheck'] = None
    check_result = record['selfCheck'] or {}
    if check and not check_result.get('honoured'):
        log.warning('timer resolution not honoured (%s)', check_result.get('waitsMs'))
    log.info('Process settings: timeBeginPeriod(1) %s, power throttling opt-out %s, switch interval %s s, '
             'self-check %s', record['timerPeriod1'], record['powerThrottlingOptOut'], record['switchInterval'],
             check_result.get('waitsMs'))
    return record


def restore_process_settings(record):
    """timeEndPeriod(1) when apply_process_settings raised the resolution. Never raises."""
    if not record or not record.get('timerPeriod1') or os.name != 'nt':
        return False
    try:
        winmm = ctypes.WinDLL('winmm')
        winmm.timeEndPeriod.restype = ctypes.c_uint
        winmm.timeEndPeriod.argtypes = (ctypes.c_uint,)
        record['timerPeriod1'] = False
        return winmm.timeEndPeriod(1) == 0
    except Exception:
        return False


def allow_foreground():
    """A second launch lets the running instance bring Settings forward. Never raises."""
    if os.name != 'nt':
        return False
    try:
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.AllowSetForegroundWindow.restype = ctypes.c_int
        user32.AllowSetForegroundWindow.argtypes = (ctypes.c_uint32,)
        return bool(user32.AllowSetForegroundWindow(ctypes.c_uint32(ASFW_ANY).value))
    except Exception:
        return False


def overlay_status(app):
    """status.json "overlay": the floating knob's metrics (state, DPI, sizes, frames,
    ULW failures, last error, GDI/USER counts) plus the scenes the UI handed over."""
    overlay = getattr(app, 'overlay', None)
    metrics = getattr(overlay, 'metrics', None)
    if not callable(metrics):
        return None
    try:
        value = metrics()
        value = json.loads(json.dumps(value if isinstance(value, dict) else {}, default=str))
    except Exception as exc:
        value = {'error': type(exc).__name__}
    value['scenesSubmitted'] = getattr(app, 'overlay_submits', 0)
    return value


def _json_ready(value):
    try:
        return json.loads(json.dumps(value, default=str))
    except Exception as exc:
        return {'error': type(exc).__name__}


def frames_status(app):
    """K4 6.2 export: every surface's FrameStats (``last``, ``worst``, ``totals`` per episode kind)
    under ``frames.<surface>``: ``knob`` from the floating knob, ``picker`` and ``toast`` from the
    picker presenter, ``explorer`` and ``upnext`` from the stage. Never raises."""
    frames = {}
    sources = [getattr(app, 'overlay', None),
               getattr(getattr(getattr(app, 'runtime', None), 'windows', None), 'overlay', None)]
    for source in sources:
        metrics = _safe_metrics(source) if source is not None and callable(getattr(source, 'metrics', None)) else {}
        value = metrics.get('frames')
        if isinstance(value, dict):
            frames.update(value)
    stage = getattr(app, 'stage', None)
    if stage is not None and callable(getattr(stage, 'metrics', None)):
        value = (_safe_metrics(stage).get('stage') or {}).get('frames')
        if isinstance(value, dict):
            frames.update(value)
    return _json_ready(frames)


def stage_status(app):
    """status.json "stage": the MusicOverlay's counters, the stage's state and its art service
    (no frames: those are under ``frames``), or None without a stage."""
    stage = getattr(app, 'stage', None)
    if stage is None or not callable(getattr(stage, 'metrics', None)):
        return None
    metrics = dict(_safe_metrics(stage))
    inner = metrics.get('stage')
    if isinstance(inner, dict):
        metrics['stage'] = {key: value for key, value in inner.items() if key != 'frames'}
    return _json_ready(metrics)


def status_payload(app, policy, startup_credentials, capabilities=None, data_dir=None):
    """The status.json document (read-only view of the running app)."""
    runtime, controller = app.runtime, app.controller
    firmware = firmware_summary(capabilities) if runtime.device_connected else None
    credentials = getattr(runtime.apple, 'credentials', None)
    return {'pid': os.getpid(), 'frozen': bool(getattr(sys, 'frozen', False)),
            'live': app.live, 'connected': runtime.device_connected,
            'ready': controller.ready, 'mode': controller.screen.mode,
            'screenStatus': controller.screen.status,
            'loading': controller.screen.loading,
            'selection': controller.screen.index,
            'pageCount': len(controller.screen.pages),
            'dataDir': str(data_dir) if data_dir is not None else None,
            'musicAuthorized': bool(credentials.get('music_user_token')) if hasattr(credentials, 'get') else False,
            'startupCredentialFile': startup_credentials,
            'executable': sys.executable,
            'sonosOnline': controller.state.get('online'),
            'volume': controller.state.get('volume'), 'autoConnect': policy.enabled,
            'deviceStatus': runtime.device_status,
            'ledStyle': runtime.led_style,
            'artwork': runtime.artwork_enabled,
            'artworkStatus': runtime.artwork_status,
            'artwork2': bool(getattr(runtime, 'artwork2', False)),
            'media': media_status(runtime),
            'firmwarePresentation': firmware['presentation'] if firmware else None,
            'firmware': firmware,
            'overlay': overlay_status(app),
            'frames': frames_status(app),
            'stage': stage_status(app),
            'openSurfaces': sorted(getattr(runtime, 'open_surfaces', None) or ()),
            'reducedMotion': bool(getattr(runtime, 'reduced_motion', False)),
            'process': getattr(app, 'process_settings', None),
            'time': time.time()}


# --smoke-test: a bundled-asset and UI check that opens no port, no network and
# no desktop action, and never contacts a running instance.
SMOKE_ART = Path('assets') / 'fixtures' / 'art-den-120.rgb565'  # relative to the bundle (ui.APP_DIR)
SMOKE_ICON_SIZES = (16, 20, 26)
SMOKE_FRAME = {
    'mode': 'VOLUME', 'target': 'Den', 'value': '54%', 'detail': '', 'status': '',
    'layout': 'nowPlaying', 'heading': 'DEN', 'title': 'Smoke test', 'subtitle': 'Desk Dial',
    'activity': 'idle', 'ledStyle': 'color', 'artKey': 'smoke-test',
    'buttons': [{'label': 'Pause', 'enabled': True, 'icon': 'pause'},
                {'label': 'Browse', 'enabled': True, 'icon': 'list'},
                {'label': 'Win', 'enabled': True, 'icon': 'win'},
                {'label': 'Tracks', 'enabled': True, 'icon': 'tracks'}],
    'ring': {'style': 'level', 'value': 54, 'index': 0, 'count': 101}}


SMOKE_WINDOWS_FRAME = {
    'mode': 'WINDOWS', 'target': '', 'value': '', 'detail': '', 'status': '',
    'layout': 'windows', 'title': 'Smoke test window', 'subtitle': 'nano', 'activity': 'idle',
    'ledStyle': 'color',
    'buttons': [{'label': 'Cancel', 'enabled': True, 'icon': 'cancel'},
                {'label': '', 'enabled': False, 'icon': ''},
                {'label': '', 'enabled': False, 'icon': ''},
                {'label': 'Switch', 'enabled': True, 'icon': 'switch'}],
    'ring': {'style': 'selection', 'value': 0, 'index': 0, 'count': 2}}


def smoke_artwork2():
    """The artwork2 payloads end to end, without a knob (the frozen build's proof that
    Pillow's JPEG plugin and codec are bundled). Raises on the first failure.

    A synthetic cover goes through prepare_artwork2 (one pass: the v1 transfer and
    the baseline 240 px JPEG), the JPEG is decoded again, a synthetic RGBA icon
    becomes its 2048-byte payload, and the artwork2 mirror draws both.
    """
    from io import BytesIO
    from PIL import Image
    from control_center.artwork import cover_key, icon_key, icon_payload, prepare_artwork2
    from control_center.lcd_preview import render_lcd
    from control_center.presentation import COVER_KEY_CHARS, COVER_MAX_BYTES, COVER_SIZE, ICON_BYTES, ICON_KEY_CHARS
    gradient = Image.linear_gradient('L')
    source = Image.merge('RGB', (gradient, gradient.rotate(90), gradient.transpose(Image.Transpose.FLIP_TOP_BOTTOM)))
    encoded = BytesIO()
    source.save(encoded, format='PNG')
    prepared = prepare_artwork2(encoded.getvalue())
    jpeg, key = prepared.jpeg, prepared.jpeg_key
    if not isinstance(jpeg, bytes) or not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
        raise RuntimeError('no artwork2 JPEG was encoded')
    if len(jpeg) > COVER_MAX_BYTES or key != cover_key(jpeg) or len(key) != COVER_KEY_CHARS:
        raise RuntimeError(f'unexpected artwork2 cover ({len(jpeg)} bytes)')
    with Image.open(BytesIO(jpeg)) as decoded:
        if (decoded.format, decoded.size, decoded.mode) != ('JPEG', (COVER_SIZE, COVER_SIZE), 'RGB') or \
                decoded.info.get('progressive'):
            raise RuntimeError(f'unexpected JPEG decode {decoded.format} {decoded.mode} {decoded.size}')
        decoded.load()
    alpha = gradient.resize((32, 32))
    rgba = Image.merge('RGBA', (alpha, alpha.rotate(90), alpha.transpose(Image.Transpose.FLIP_TOP_BOTTOM), alpha))
    payload_key, payload = icon_payload(rgba)
    if len(payload) != ICON_BYTES or payload_key != icon_key(payload) or len(payload_key) != ICON_KEY_CHARS:
        raise RuntimeError(f'unexpected icon payload ({len(payload)} bytes)')
    cover_frame = dict(SMOKE_FRAME, artKey=key)
    with_cover = render_lcd(cover_frame, jpeg, artwork2=True)
    if with_cover.tobytes() == render_lcd(dict(SMOKE_FRAME, artKey=''), None, artwork2=True).tobytes():
        raise RuntimeError('the artwork2 cover was not drawn')
    window_frame = dict(SMOKE_WINDOWS_FRAME, iconKey=payload_key)
    if render_lcd(window_frame, None, payload, artwork2=True).tobytes() == \
            render_lcd(SMOKE_WINDOWS_FRAME, None, None, artwork2=True).tobytes():
        raise RuntimeError('the artwork2 icon was not drawn')
    return {'jpegBytes': len(jpeg), 'rgb565Bytes': len(prepared.raw), 'iconBytes': len(payload)}


def _smoke_sources():
    """A synthetic 480 px cover, its 240 px preview, and a 32 px icon with its 128 px copy."""
    from PIL import Image
    gradient = Image.linear_gradient('L')
    cover = Image.merge('RGB', (gradient, gradient.rotate(90), gradient.transpose(Image.Transpose.FLIP_TOP_BOTTOM)))
    cover = cover.resize((480, 480), Image.Resampling.LANCZOS)
    alpha = gradient.resize((128, 128))
    big_icon = Image.merge('RGBA', (alpha.rotate(90), alpha, alpha.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
                                    Image.new('L', (128, 128), 255)))
    return (cover, cover.resize((240, 240), Image.Resampling.LANCZOS), big_icon.resize((32, 32), Image.Resampling.LANCZOS),
            big_icon)


def smoke_hires_glyphs():
    """Every button glyph's hi-res masks (assets/lcd-icons, @2x and @3x of each smoke size)
    load at their exact size: render_lcd above 240 px would otherwise upscale the 1x mask
    without a sign. Raises on the first missing one; returns how many were checked."""
    from control_center import lcd_preview
    from control_center.presentation import ICONS
    checked = 0
    for name in ICONS:
        if not name:
            continue
        for size in SMOKE_ICON_SIZES:
            for factor in lcd_preview.HIRES_ICON_FACTORS:
                if lcd_preview._hires_mask_source(name, size, factor) is None:
                    raise RuntimeError(f'hi-res LCD glyph {name}-{size}@{factor}x is missing or the wrong size')
                checked += 1
    return checked


def smoke_overlay():
    """The floating knob's renderers, to PIL only (no window): KnobFace at 100 % and 200 %
    DPI with a composed LCD and a lit ring, premultiplied BGRA of the right size, and
    render_lcd above 240 px drawing the hi-res cover and icon, with every button glyph's
    hi-res masks present (smoke_hires_glyphs). Raises on the first failure."""
    from control_center import knob_face
    from control_center.lcd_preview import render_lcd
    from control_center.preview_lights import PreviewLights
    hires_glyphs = smoke_hires_glyphs()
    cover, preview, icon, big_icon = _smoke_sources()
    drives, _buttons = PreviewLights().render(SMOKE_FRAME, 0, 0)
    ring = tuple(knob_face.ring_colors(SMOKE_FRAME, drives))
    if len(ring) != 60 or not all(len(color) == 4 for color in ring):
        raise RuntimeError('ring_colors did not return 60 (r, g, b, level) entries')
    if not any(color[3] > 0 for color in ring):
        raise RuntimeError('the smoke frame lit no ring segment')
    detail = {}
    for name, dpi in (('dpi100', 96), ('dpi200', 192)):
        face = knob_face.KnobFace(knob_face.scale_for(dpi))
        pixels = face.lcd_px
        scale = pixels / 240
        lcd = render_lcd(SMOKE_FRAME, preview, scale=scale, hires_cover=cover)
        if lcd.size != (pixels, pixels):
            raise RuntimeError(f'render_lcd at scale {scale:.3f} drew {lcd.size}, not {pixels} px')
        drawn = lcd.tobytes()
        if drawn in (render_lcd(dict(SMOKE_FRAME, artKey=''), None, scale=scale).tobytes(),
                     render_lcd(SMOKE_FRAME, preview, scale=scale).tobytes()):
            raise RuntimeError('the hi-res cover was not drawn')
        windows = render_lcd(SMOKE_WINDOWS_FRAME, None, icon, scale=scale, hires_icon=big_icon).tobytes()
        if windows in (render_lcd(SMOKE_WINDOWS_FRAME, None, None, scale=scale).tobytes(),
                       render_lcd(SMOKE_WINDOWS_FRAME, None, icon, scale=scale).tobytes()):
            raise RuntimeError('the hi-res app icon was not drawn')
        started = time.perf_counter()
        image = face.compose(lcd.convert('RGBA'), ring)
        compose_ms = (time.perf_counter() - started) * 1000
        width, height = face.size
        if image.mode != 'RGBA' or image.size != (width, height) or width % 2 or height % 2:
            raise RuntimeError(f'unexpected knob face {image.mode} {image.size}')
        if image.getpixel((0, 0))[3] != 0 or image.getpixel(face.center)[3] == 0:
            raise RuntimeError('the knob face is not transparent outside and opaque inside')
        data = knob_face.premultiplied_bgra(image)
        if len(data) != width * height * 4:
            raise RuntimeError('premultiplied BGRA has the wrong size')
        detail[name] = {'window': [width, height], 'lcd': pixels, 'composeMs': round(compose_ms, 2)}
    detail['hiresGlyphs'] = hires_glyphs
    return detail


SMOKE_STAGE_SCALE = 2.0   # the carousel's stage scale on the user's 5120 x 1440 monitor
# A centre label with glyphs Archivo lacks (Cyrillic, Greek, CJK, Hangul, emoji) and a
# Latin tail long enough for the ellipsis: every one must come from a fallback face.
SMOKE_LABEL = ('Smoke test',
               'Смоук · Σύνοψη · '
               '煙のテスト · 연기 · \U0001F642 · '
               'a synthetic window title long enough to need an ellipsis at the carousel width',
               'Fallback fonts · smoke')


def contrast_ratio(first, second):
    """WCAG contrast ratio of two sRGB colours (r, g, b[, a]) (1.0 to 21.0)."""
    def luminance(rgb):
        def channel(value):
            value /= 255
            return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        red, green, blue = (channel(value) for value in rgb[:3])
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _label_image(result):
    """The straight RGBA image of a render_label() result (a LabelSprite, a Sprite or an image)."""
    sprite = getattr(result, 'sprite', result)
    straight = getattr(sprite, 'straight', None)
    return straight() if callable(straight) else sprite


def _label_fonts(carousel_render, text, weight=600):
    """(fonts used, characters no font covers) for ``text`` through the carousel's own text
    engine (TextEngine.glyphs + the fonts' cmap coverage), or (None, None) without one."""
    missing = getattr(carousel_render, 'missing_glyphs', None)
    if callable(missing):
        return None, str(missing(text) or '')
    engine_class = getattr(carousel_render, 'TextEngine', None)
    covers = getattr(carousel_render, 'coverage', None)
    if engine_class is None or not callable(covers):
        return None, None
    glyphs = engine_class().glyphs(text, weight)
    gaps = ''.join(ch for ch, spec in glyphs if spec is None or ord(ch) not in covers(spec.path, spec.index))
    return sorted({spec.name for _ch, spec in glyphs if spec is not None}), gaps


def smoke_carousel_render():
    """The Windows carousel's PIL work (CAROUSEL.md sections 3, 7, 8, 10 and 11), no window:
    the Frosted background's pipeline (glass(), the full-screen frost) on a synthetic
    stage-sized backdrop at the user's stage scale, the centre label with glyphs Archivo lacks
    (per-glyph font fallback) for both backgrounds, and a letter tile (128 px, square and
    opaque, a white letter at >= 3:1). Every title glyph must come from a font whose cmap has
    it (no tofu), and at least one from a fallback face. Raises on the first failure."""
    from PIL import Image
    from control_center import carousel_render, window_facts, window_labels
    k = SMOKE_STAGE_SCALE
    size = (round(1280 * k), round(720 * k))      # section 11: the frost covers the monitor, not a pane
    ramp = Image.linear_gradient('L').resize(size)
    backdrop = Image.merge('RGB', (ramp, ramp.transpose(Image.Transpose.FLIP_LEFT_RIGHT), ramp.rotate(180)))
    started = time.perf_counter()
    glass = carousel_render.glass(backdrop, k)
    glass_ms = (time.perf_counter() - started) * 1000
    if getattr(glass, 'mode', None) != 'RGBA' or getattr(glass, 'size', None) != size:
        raise RuntimeError(f'glass() returned {getattr(glass, "mode", type(glass).__name__)} '
                           f'{getattr(glass, "size", None)}, not RGBA {size}')
    if glass.convert('RGB').tobytes() == backdrop.tobytes():
        raise RuntimeError('glass() left the backdrop unchanged')
    tile = window_facts.letter_tile('Nano', 128)
    if getattr(tile, 'mode', None) != 'RGBA' or getattr(tile, 'size', None) != (128, 128):
        raise RuntimeError(f'letter_tile() returned {getattr(tile, "mode", type(tile).__name__)} '
                           f'{getattr(tile, "size", None)}, not RGBA 128 px')
    corner = tile.getpixel((0, 0))
    if corner[3] != 255 or tile.getpixel((127, 127))[3] != 255:
        raise RuntimeError('the letter tile is not square and opaque')
    if tile.convert('L').point(lambda value: 255 if value >= 235 else 0).getbbox() is None:
        raise RuntimeError('the letter tile has no white letter')
    ratio = contrast_ratio((255, 255, 255), corner)
    if ratio < 3.0:
        raise RuntimeError(f'the letter tile colour gives white text {ratio:.2f}:1, below 3:1')
    label = window_labels.Label(*SMOKE_LABEL)
    rendered = {}
    for background in ('glass', 'none'):
        started = time.perf_counter()
        result = carousel_render.render_label(label, tile, k, background)
        elapsed = (time.perf_counter() - started) * 1000
        image = _label_image(result)
        if getattr(image, 'mode', None) != 'RGBA':
            raise RuntimeError(f'render_label() returned {type(result).__name__}, not a label image ({background})')
        if image.getchannel('A').getbbox() is None:
            raise RuntimeError(f'render_label() drew nothing ({background})')
        rendered[background] = {'size': list(image.size), 'ms': round(elapsed, 2)}
    fonts, gaps = _label_fonts(carousel_render, label.title)
    if gaps:
        raise RuntimeError(f'{len(gaps)} label glyph(s) have no font (tofu)')
    if fonts is not None and len(fonts) < 2:
        raise RuntimeError(f'the label used {fonts}: no fallback face for the glyphs Archivo lacks')
    return {'stageScale': k, 'glass': {'size': list(size), 'ms': round(glass_ms, 2)}, 'label': rendered,
            'fallbackCoverage': None if gaps is None else True, 'labelFonts': fonts,
            'letterTile': {'contrast': round(ratio, 2)}}


class SmokeOverlay:
    """The KnobOverlay interface for the smoke test's UI check, without a window: every
    scene the app submits is composed with KnobFace (the overlay thread's work)."""
    wants_frames = True
    state = 'shown'
    rect = None

    def __init__(self, dpi=192):
        from control_center import knob_face
        self._face_module = knob_face
        self.face = knob_face.KnobFace(knob_face.scale_for(dpi))
        self.lcd_px = self.face.lcd_px
        self.scenes = self.touches = 0
        self.errors = []

    def submit(self, scene):
        try:
            if scene.lcd is not None and (scene.lcd.mode, scene.lcd.size) != ('RGBA', (self.lcd_px, self.lcd_px)):
                raise RuntimeError(f'LCD {scene.lcd.mode} {scene.lcd.size}, expected {self.lcd_px} px RGBA')
            if len(scene.ring) != 60:
                raise RuntimeError(f'{len(scene.ring)} ring colours')
            image = self.face.compose(scene.lcd, scene.ring)
            if len(self._face_module.premultiplied_bgra(image)) != image.width * image.height * 4:
                raise RuntimeError('premultiplied BGRA has the wrong size')
            self.scenes += 1
        except Exception as exc:
            self.errors.append(f'{type(exc).__name__}: {exc}'[:200])

    def touch(self):
        self.touches += 1

    def peek(self, seconds=PEEK_SECONDS):
        self.touches += 1

    def set_suppressed(self, reason, on):
        pass

    def metrics(self):
        return {'state': self.state, 'scenes': self.scenes, 'lcdPx': self.lcd_px}

    def close(self):
        pass


def smoke_alive():
    """Desktop v7's floating-knob look without a window (K2 10.3 item 3; K4 11.3-11.4): AliveFace at
    100 % and 200 % DPI (the 360 look masks, the sigmas GLB/2 x S_glow), AliveLights rendering a
    claimed Home frame, the C2 compose into a premultiplied canvas, and the frame key. Raises on the
    first failure."""
    from PIL import Image
    from control_center import knob_face
    from control_center.alive_lights import AliveLights
    expected = {96: (3.40, 10.19), 192: (6.79, 20.38)}
    detail = {}
    for dpi, (first, last) in expected.items():
        face = knob_face.AliveFace(knob_face.scale_for(dpi), knob_face.glow_scale_for(dpi))
        if abs(face.sigmas[0] - first) > 0.01 or abs(face.sigmas[-1] - last) > 0.01:
            raise RuntimeError(f'look sigmas {face.sigmas} at {dpi} DPI')
        lights = AliveLights(0)
        lights.claim(0)
        frame = dict(SMOKE_FRAME, id=7, playing=True)
        ring = None
        for step in range(60):
            ring, _buttons = lights.render(step * 16, frame, None, None)
        looks = knob_face.ring_key(ring)
        if not any(look >= 0 for _fill, look, _tint in looks):
            raise RuntimeError('the alive engine lit no ring segment')
        lcd = Image.new('RGBA', (face.lcd_px, face.lcd_px), (20, 40, 60, 255))
        canvas = Image.new('RGBX', face.size, (0, 0, 0, 0))
        started = time.perf_counter()
        face.compose_into(canvas, (0, 0), lcd, looks)
        compose_ms = (time.perf_counter() - started) * 1000
        image = face.compose(lcd, ring)
        if image.getpixel((0, 0))[3] != 0 or image.getpixel(face.center)[3] != 255:
            raise RuntimeError('the alive face is not transparent outside and opaque inside')
        detail[f'dpi{dpi}'] = {'window': list(face.size), 'buildMs': round(face.build_ms, 1),
                               'looksBuildMs': round(face.looks_build_ms, 1), 'composeMs': round(compose_ms, 3)}
    return detail


class HeadlessOverlayBackend:
    """A Win32Backend stand-in for the headless smoke check: no window, no DIB, nothing shown. Posts
    are delivered at the next pump (the overlay runs inline on the calling thread)."""
    hwnd = 0

    def __init__(self, work=(0, 0, 1920, 1040), dpi=96):
        self.work, self.dpi = work, dpi
        self.handler = None
        self.size = None
        self.pending = []
        self.presents = 0
        self.shown = False

    def prepare_thread(self):
        return 2

    def create(self, handler, position, size):
        self.handler, self.size = handler, tuple(size)

    def resize(self, size):
        self.size = tuple(size)

    def geometry(self):
        return self.work, self.dpi

    def post(self, code):
        self.pending.append(code)
        return True

    def post_quit(self):
        return True

    def pump(self):
        from control_center.overlay import POSTED_EVENTS
        pending, self.pending = self.pending, []
        for code in pending:
            if self.handler is not None and code in POSTED_EVENTS:
                self.handler(POSTED_EVENTS[code])
        return True

    def wait(self, timeout):
        return True

    def pace(self):
        pass

    def present(self, frame, size, position, src_x, alpha):
        if not isinstance(frame, bytes) or len(frame) != size[0] * size[1] * 4 or tuple(size) != self.size:
            return False
        self.presents += 1
        return True

    def show(self):
        self.shown = True
        return True

    def hide(self):
        self.shown = False
        return True

    def is_visible(self):
        return self.shown

    def notification_state(self):
        return 5                          # QUNS_ACCEPTS_NOTIFICATIONS

    def gui_resources(self):
        return 0, 0

    def destroy_window(self):
        self.handler = None

    def unregister(self):
        pass

    def destroy(self):
        self.destroy_window()


class HeadlessRoot:
    """The part of a Tk root that ControlCenterApp(chrome=False) uses, without Tk: timers are
    recorded and never run (the check drives the ticks itself); nothing is ever shown."""

    def __init__(self):
        self.timers = {}
        self._next = 0
        self.destroyed = False

    def title(self, *args):
        pass

    def configure(self, **kwargs):
        pass

    def protocol(self, *args):
        pass

    def state(self):
        return 'withdrawn'

    def after(self, ms, callback):
        self._next += 1
        self.timers[self._next] = (ms, callback)
        return self._next

    def after_cancel(self, ident):
        self.timers.pop(ident, None)

    def destroy(self):
        self.destroyed = True


def headless_ui_check(ticks=40):
    """The installed app's mode without Tk (``--smoke-test --headless``): ControlCenterApp(chrome=False)
    on a stand-in root, first with the v5 floating knob (SmokeOverlay: every scene composed with
    KnobFace), then with the simulated knob of the state picker (presentation 5 + alive) and a real
    KnobOverlay run inline over a headless backend: the frames reach AliveLights on the overlay's
    engine, it renders per message while hidden, and after a touch it slides in and composes the six
    looks with AliveFace. No window, port, network or desktop action. Raises on failure."""
    from control_center import ui as ui_module
    from control_center.overlay import KnobOverlay
    detail = {}
    overlay = SmokeOverlay()
    app = ui_module.ControlCenterApp(HeadlessRoot(), smoke=True, live=False, chrome=False, overlay=overlay)
    try:
        for _ in range(ticks):
            app._poll_once()
        stages = {stage: count for stage, count in getattr(app, 'failure_counts', {}).items() if count}
        if app.mirror_failures or not app.lcd_renders or not overlay.scenes or overlay.errors or stages:
            raise RuntimeError(f'v5 knob: LCD renders={app.lcd_renders} scenes={overlay.scenes} '
                               f'failures={app.mirror_failures} scene errors={overlay.errors[:3]} stages={stages}')
        detail['v5'] = {'lcdRenders': app.lcd_renders, 'scenes': overlay.scenes, 'lcdPixels': overlay.lcd_px}
    finally:
        app.close()
    backend = HeadlessOverlayBackend()
    knob = KnobOverlay(backend=backend)
    knob._start_inline()
    app = ui_module.ControlCenterApp(HeadlessRoot(), smoke=True, live=False, chrome=False, overlay=knob)
    try:
        if not app.set_sim_connection('connected'):
            raise RuntimeError('the simulated knob could not be selected')
        for _ in range(ticks):
            app._poll_once()
            knob._iterate()
        if not app.runtime.alive or not knob.alive:
            raise RuntimeError(f'the simulated knob is not alive (runtime {app.runtime.alive}, overlay {knob.alive})')
        hidden = knob.metrics()
        if not hidden['hidden_renders'] or hidden['frames_composed']:
            raise RuntimeError(f'hidden: renders {hidden["hidden_renders"]}, composes {hidden["frames_composed"]}')
        knob.touch()
        started = time.perf_counter()
        while time.perf_counter() - started < 0.6:
            app._poll_once()
            knob._iterate()
        shown = knob.metrics()
        if knob.state not in ('in', 'shown') or not shown['frames_composed'] or not backend.presents:
            raise RuntimeError(f'shown: state {knob.state}, composes {shown["frames_composed"]}, '
                               f'presents {backend.presents}')
        stages = {stage: count for stage, count in getattr(app, 'failure_counts', {}).items() if count}
        if stages or shown['alive_failures'] or shown['compose_failures']:
            raise RuntimeError(f'alive: stages {stages}, engine failures {shown["alive_failures"]}, '
                               f'compose failures {shown["compose_failures"]}')
        detail['alive'] = {key: shown[key] for key in ('engine_renders', 'hidden_renders', 'catchup_renders',
                                                        'frames_composed', 'frames_presented', 'frames_skipped',
                                                        'looks_build_ms', 'compose_ms')}
    finally:
        app.close()
        knob.close()
    return json.loads(json.dumps(detail, default=str))


def smoke_stage(start=None):
    """The stage's native lifecycle, never shown (K4 4.1): the explorer and Up next thread started
    with its host created hidden (``host_hidden_only``: it refuses to show) and no art fetching,
    wrapped as the runtime's MusicOverlay, then closed; the GDI/USER counts return to their
    baseline. Raises on failure."""
    if start is None:
        from control_center.stage.scenes import start_music_stage as start
    from control_center.music_overlay import MusicOverlay

    def cycle():
        thread, presenter, art = start(log=None, fetch=False, covers_dir=None, host_hidden_only=True)
        overlay = MusicOverlay(presenter, art=art, thread=thread)
        try:
            disabled = getattr(thread, 'disabled', None)
            if disabled:
                raise RuntimeError(f'the stage did not start: {disabled}')
            metrics = overlay.metrics()
        finally:
            closed = overlay.close(2.0)
        if not closed:
            raise RuntimeError('the stage thread did not stop within 2 s')
        return metrics
    # The first cycles load what a process keeps once (measured: two USER objects over the first two
    # cycles, then none); a leak grows on every cycle. So cycles run until one leaves the counts
    # where the previous one did, at most four.
    counts = [gui_resources()]
    metrics = {}
    for _ in range(4):
        metrics = cycle()
        counts.append(_back_to_baseline(counts[-1], DIB_REBUILD_SETTLE_SECONDS))
        if len(counts) >= 3 and counts[-1][0] <= counts[-2][0] and counts[-1][1] <= counts[-2][1]:
            break
    else:
        raise RuntimeError(f'GDI/USER objects grew on every stage cycle: {counts}')
    stage = metrics.get('stage') if isinstance(metrics.get('stage'), dict) else {}
    return json.loads(json.dumps({'state': stage.get('state'), 'cycles': len(counts) - 1,
                                  'objects': [list(c) for c in counts]}, default=str))


def smoke_process_settings():
    """K4 4.7.2's calls in the frozen build: timeBeginPeriod(1), the three-wait self-check, then
    timeEndPeriod(1) (the smoke process leaves nothing changed). The self-check is recorded."""
    if os.name != 'nt':
        return {'skipped': 'not Windows'}
    winmm = ctypes.WinDLL('winmm')
    winmm.timeBeginPeriod.restype = winmm.timeEndPeriod.restype = ctypes.c_uint
    winmm.timeBeginPeriod.argtypes = winmm.timeEndPeriod.argtypes = (ctypes.c_uint,)
    if winmm.timeBeginPeriod(1) != 0:
        raise RuntimeError('timeBeginPeriod(1) failed')
    try:
        check = timer_self_check()
    finally:
        winmm.timeEndPeriod(1)
    return {'timerPeriod1': True, 'selfCheck': check}


_gui_api = None


def gui_resources():
    """(GDI objects, USER objects) of this process (GetGuiResources)."""
    global _gui_api
    if os.name != 'nt':
        return 0, 0
    if _gui_api is None:
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        user32.GetGuiResources.restype = ctypes.c_uint32
        user32.GetGuiResources.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.GetCurrentProcess.argtypes = ()
        _gui_api = (user32.GetGuiResources, kernel32.GetCurrentProcess)
    counts, process = _gui_api
    handle = process()
    return int(counts(handle, 0)), int(counts(handle, 1))


def _back_to_baseline(before, timeout=None):
    """GDI/USER counts once they are back at or below ``before`` (or the last seen)."""
    deadline = time.monotonic() + (GUI_BASELINE_SECONDS if timeout is None else timeout)
    while True:
        after = gui_resources()
        if (after[0] <= before[0] and after[1] <= before[1]) or time.monotonic() >= deadline:
            return after
        time.sleep(0.02)


def _hidden_window_cycle(overlay_module, timeout=5.0):
    """On a thread of its own (the overlay's rule: one thread owns the window): the
    overlay's Win32Backend creates the window hidden with its DC and 2W x H DIB (the
    app's geometry: overlay.window_rect), presents a composed face with
    UpdateLayeredWindow (ptSrc.x = W, alpha 0) while the window stays hidden, rebuilds
    the DIB twice as a DPI change does (the GDI/USER counts must not move), then
    destroys the window and unregisters the class."""
    from PIL import Image
    from control_center import knob_face
    from control_center.overlay import window_rect
    outcome = {}

    def cycle():
        try:
            backend = overlay_module.Win32Backend()
        except BaseException as exc:
            outcome['error'] = f'{type(exc).__name__}: {exc}'[:200]
            return
        try:
            outcome['awareness'] = backend.prepare_thread()
            work, dpi = backend.geometry()
            face = knob_face.KnobFace(knob_face.scale_for(dpi or 96))
            x, y, width, height, inset = window_rect(work, dpi or 96, face.size)
            position = (x, y)
            backend.create(lambda _event: None, position, (width, height))
            box = Image.new('RGBA', (width, height), (0, 0, 0, 0))
            box.paste(face.compose(None, ()), (inset, 0))
            frame = knob_face.premultiplied_bgra(box)
            outcome['ulw'] = bool(backend.present(frame, (width, height), position, width, 0))
            outcome['visible'] = bool(backend.is_visible())
            outcome.update(dpi=dpi, window=[width, height], insetPx=inset)
            # A DPI change rebuilds the DIB (old bitmap selected back, old DIB deleted, new one
            # created): at most one DIB is ever alive, so the object counts stay where they are.
            during = gui_resources()
            rebuilds = []
            for grow in (2, 0):
                size = (width + grow, height + grow)
                backend.resize(size)
                ok = backend.present(bytes(size[0] * size[1] * 4), size, position, size[0], 0)
                # Process-wide counters: another thread's short-lived object may be counted for a
                # moment, so wait (briefly) for them to settle; a leaked DIB never does.
                objects = _back_to_baseline(during, DIB_REBUILD_SETTLE_SECONDS)
                rebuilds.append({'size': list(size), 'ulw': bool(ok), 'objects': list(objects)})
            outcome.update(objects=list(during), dibRebuilds=rebuilds,
                           visibleAfterRebuilds=bool(backend.is_visible()))
        except BaseException as exc:
            outcome['error'] = f'{type(exc).__name__}: {exc}'[:200]
        finally:
            try:
                backend.destroy_window()
                backend.pump()          # WM_DESTROY's WM_QUIT
                backend.unregister()
                outcome['destroyed'] = backend.hwnd is None and not backend.registered
            except BaseException as exc:
                outcome.setdefault('error', f'cleanup {type(exc).__name__}: {exc}'[:200])

    thread = threading.Thread(target=cycle, name='NanoD-overlay-smoke', daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise RuntimeError('the hidden overlay window cycle did not finish')
    if outcome.get('error'):
        raise RuntimeError(outcome['error'])
    if not outcome.get('ulw') or outcome.get('visible') or not outcome.get('destroyed'):
        raise RuntimeError(f'hidden window cycle: {outcome}')
    rebuilds = outcome.get('dibRebuilds') or []
    during = outcome.get('objects') or [0, 0]
    if (len(rebuilds) != 2 or outcome.get('visibleAfterRebuilds')
            or not all(step['ulw'] and step['objects'][0] <= during[0] and step['objects'][1] <= during[1]
                       for step in rebuilds)):
        raise RuntimeError(f'hidden window DIB rebuilds: {outcome}')
    return outcome


def smoke_overlay_window(overlay_module=None):
    """The overlay window's native lifecycle, never shown: create it hidden, build the DIB,
    UpdateLayeredWindow on the hidden window, destroy it and unregister the class; then a
    KnobOverlay start()/close() on its NanoD-overlay thread (created hidden, stopped by
    WM_APP+3). GDI and USER object counts must return to their baseline. Uses
    overlay.smoke_check() instead when the module provides one."""
    if overlay_module is None:
        from control_center import overlay as overlay_module
    before = gui_resources()
    check = getattr(overlay_module, 'smoke_check', None)
    if callable(check):
        detail = dict(check() or {})
    else:
        detail = {'window': _hidden_window_cycle(overlay_module)}
        knob = overlay_module.KnobOverlay()
        try:
            if not knob.start():
                raise RuntimeError(f'the overlay thread did not start: {_safe_metrics(knob).get("last_error")}')
            if knob.state != 'hidden' or knob.wants_frames:
                raise RuntimeError(f'the overlay started {knob.state}, not hidden')
            metrics = _safe_metrics(knob)
            detail['overlay'] = {key: metrics.get(key) for key in ('dpi', 'window_px', 'lcd_px', 'dpi_awareness')}
        finally:
            stopped = knob.close()
        if not stopped:
            raise RuntimeError('the overlay thread did not stop within its timeout')
    after = _back_to_baseline(before)
    if after[0] > before[0] or after[1] > before[1]:
        raise RuntimeError(f'GDI/USER objects {before} -> {after}: the window leaked')
    detail.update(gdi=[before[0], after[0]], user=[before[1], after[1]])
    return json.loads(json.dumps(detail, default=str))


def _window_visible(hwnd):
    if os.name != 'nt' or not hwnd:
        return False
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.IsWindowVisible.restype, user32.IsWindowVisible.argtypes = ctypes.c_int, (ctypes.c_void_p,)
    return bool(user32.IsWindowVisible(hwnd))


def _carousel_presenter_cycle(carousel_module):
    """The presenter's own lifecycle without show(): its thread creates every window hidden,
    then close() destroys them, unregisters the classes and joins its threads (<= 1 s)."""
    presenter = carousel_module.CarouselPresenter(None, None, lambda: None)
    try:
        if getattr(presenter, 'disabled', False) or not presenter.hwnd:
            raise RuntimeError(f'the carousel did not start: {getattr(presenter, "last_error", None)}')
        if presenter.rect is not None or _window_visible(presenter.hwnd):
            raise RuntimeError('the carousel host is shown before show()')
        metrics = presenter.metrics() if callable(getattr(presenter, 'metrics', None)) else {}
        detail = {'hostMode': metrics.get('host_mode'), 'dpiAwareness': metrics.get('dpi_awareness')}
    finally:
        joined = presenter.close()
    if joined is False:
        raise RuntimeError('the carousel threads did not stop within their timeout')
    return detail


def _carousel_self_test(self_test):
    """carousel.self_test(hidden_windows=True) at the smoke's stage scale: the glass pipeline on a
    synthetic image, a label with fallback fonts, the letter tile, and the real windows created
    hidden on their own thread with one DWM thumbnail registered from one of them, one chrome
    frame composed into its premultiplied DIB and UpdateLayeredWindow'd at alpha 0, everything
    destroyed and the GDI/USER counts back to baseline. Raises unless it reports ok."""
    report = self_test(hidden_windows=True, k=SMOKE_STAGE_SCALE)
    report = dict(report) if isinstance(report, dict) else {'ok': False, 'error': 'no report'}
    if report.get('ok') is not True:
        raise RuntimeError(f'the carousel self-test failed: {json.dumps(report, default=str)}')
    return report


def smoke_carousel_window(carousel_module=None):
    """The Windows carousel's native lifecycle, never shown (CAROUSEL.md section 10):
    carousel.smoke_check() when the module has one; else carousel.self_test(hidden_windows=True)
    (hidden windows, one DWM thumbnail, one composed chrome frame presented through the
    premultiplied DIB path, then everything destroyed) and the presenter's own lifecycle
    without show() (its windows are created hidden on the NanoD-carousel thread and destroyed
    by close()), each when the module provides it. The GDI and USER object counts must return
    to their baseline."""
    if carousel_module is None:
        from control_center import carousel as carousel_module
    check = getattr(carousel_module, 'smoke_check', None)
    self_test = getattr(carousel_module, 'self_test', None)
    presenter = getattr(carousel_module, 'CarouselPresenter', None)
    if not callable(check) and not callable(self_test) and presenter is None:
        raise RuntimeError('control_center.carousel provides neither smoke_check(), self_test() '
                           'nor CarouselPresenter')
    before = gui_resources()
    if callable(check):
        detail = dict(check() or {})
    else:
        detail = {}
        if callable(self_test):
            detail['selfTest'] = _carousel_self_test(self_test)
        if presenter is not None:
            detail.update(_carousel_presenter_cycle(carousel_module))
    after = _back_to_baseline(before)
    if after[0] > before[0] or after[1] > before[1]:
        raise RuntimeError(f'GDI/USER objects {before} -> {after}: the carousel leaked')
    detail.update(gdi=[before[0], after[0]], user=[before[1], after[1]])
    return json.loads(json.dumps(detail, default=str))


def smoke_app_icons(app_dir=None, api=None, frozen=None, executable=None):
    """APP_ICON.md item 7: every app and tray .ico and the two app PNGs are in the bundle;
    each .ico has exactly the frames of the table (Pillow info['sizes']); LoadImageW gives an
    HICON at the small-icon size for every tray .ico and for the app .ico (each destroyed again
    at once); and the running
    frozen exe embeds at least one icon (ExtractIconExW count; nothing is loaded). Opens no
    window. Raises on the first failure."""
    from PIL import Image
    if app_dir is None:
        from control_center.ui import APP_DIR as app_dir
    app_dir = Path(app_dir)
    api = api if api is not None else TrayIconApi()
    icos = {APP_ICON_FILE: APP_ICON_SIZES}
    for theme in TRAY_THEMES:
        for present in (True, False):
            icos[tray_icon_file(theme, present)] = TRAY_ICON_SIZES
    missing = [str(path) for path in list(icos) + list(APP_ICON_PNGS) if not (app_dir / path).is_file()]
    if missing:
        raise RuntimeError('missing icon files: ' + ', '.join(missing))
    frames = {}
    for path, sizes in icos.items():
        with Image.open(app_dir / path) as image:
            found = sorted(tuple(size) for size in image.info.get('sizes', ()))
        if found != [(size, size) for size in sizes]:
            raise RuntimeError(f'{path.name} has frames {found}, expected {list(sizes)}')
        frames[path.name] = [width for width, _height in found]
    size = api.small_icon_size()
    loaded = 0
    for path, sizes in icos.items():
        if sizes is not TRAY_ICON_SIZES:
            continue
        handle = api.load(app_dir / path, size)
        if not handle:
            raise RuntimeError(f'LoadImageW returned no icon for {path.name} at {size} px')
        api.destroy(handle)
        loaded += 1
    # The app .ico as well: every Tk window gets its frames through LoadImageW (Tk 8.6 cannot
    # read them; ui.AppWindowIcons, APP_ICON.md item 3).
    handle = api.load(app_dir / APP_ICON_FILE, size)
    if not handle:
        raise RuntimeError(f'LoadImageW returned no icon for {APP_ICON_FILE.name} at {size} px')
    api.destroy(handle)
    frozen = bool(getattr(sys, 'frozen', False)) if frozen is None else frozen
    exe = {'checked': False}
    if frozen:
        executable = executable or sys.executable
        count = api.icon_count(executable)
        if count < 1:
            raise RuntimeError(f'{Path(executable).name} embeds no icon')
        exe = {'checked': True, 'icons': count}
    return {'frames': frames, 'smallIconSize': size, 'trayIconsLoaded': loaded, 'appIconLoaded': True, 'exeIcon': exe}


def decode_rgb565(data, size=120):
    """A size x size RGB565 little-endian wire image as a PIL RGB image."""
    from PIL import Image
    if len(data) != size * size * 2:
        raise ValueError(f'expected {size * size * 2} bytes, got {len(data)}')
    pixels = bytearray(size * size * 3)
    for i in range(size * size):
        value = data[2 * i] | data[2 * i + 1] << 8
        r, g, b = value >> 11 & 31, value >> 5 & 63, value & 31
        pixels[3 * i:3 * i + 3] = bytes(((r * 527 + 23) >> 6, (g * 259 + 33) >> 6, (b * 527 + 23) >> 6))
    return Image.frombytes('RGB', (size, size), bytes(pixels))


class _NoTk(Exception):
    """--smoke-test --headless: the Tk part of the smoke test is skipped (no root is created)."""


def _smoke_check(results, name, check):
    try:
        detail = check()
        results[name] = {'passed': True, 'detail': detail}
    except Exception as exc:
        results[name] = {'passed': False, 'error': f'{type(exc).__name__}: {exc}'[:300]}


def run_smoke_test(out_dir, *, art_path=None, ui=True, ui_ms=500, headless=False):
    """Run every smoke check, write out_dir/smoke-test.json, return the exit code (0 = all passed).

    Desktop v7 adds: ``alive`` (smoke_alive: the six glow looks and the C2 compose), ``processSettings``
    (the timer calls and self-check, undone), and with ``ui`` the stage's hidden lifecycle
    (``stageWindow``). ``headless`` (``--smoke-test --headless``) creates no Tk root at all: the
    Tk-only checks (fontsTk, imageTk, the Tk UI run) are replaced by ``uiHeadless`` (headless_ui_check:
    the app on a stand-in root, with the v5 knob and with the simulated alive knob on a real
    KnobOverlay run inline over a headless backend). Nothing is ever shown in either mode.

    Checks: the art fixture decodes; render_lcd draws a frame with it; every
    handoff icon exists at 16/20/26; Montserrat and Archivo load in PIL and are
    visible to Tk after private registration; the artwork2 payloads encode and
    draw (smoke_artwork2: Pillow's JPEG plugin is bundled); the floating knob's
    renderers (smoke_overlay: KnobFace at 100 % and 200 %, render_lcd above 240 px
    with hi-res sources); the app and tray icons (smoke_app_icons: files, ICO frames,
    LoadImageW of each tray .ico, the frozen exe's embedded icon); the Windows
    carousel's PIL work (smoke_carousel_render: the frost pipeline on a synthetic stage-sized image,
    the label with fallback fonts, the letter tile); PIL.ImageTk works;
    and (``ui``) the overlay window's hidden lifecycle, DIB rebuilds included, with a
    GDI/USER baseline (smoke_overlay_window, never shown), the carousel's hidden
    lifecycle with the same baseline (smoke_carousel_window, never shown: carousel.self_test
    registers one DWM thumbnail and presents one composed chrome frame, then the presenter
    starts and closes its thread),
    and the simulator in the floating-knob mode (chrome=False) for ``ui_ms``,
    whose scenes are composed with KnobFace. Opens no port, no network
    connection and no desktop action, and never shows a window.
    """
    import datetime
    results = {}
    state = {}

    def art():
        path = art_path
        if path is None:
            from control_center.ui import APP_DIR
            path = APP_DIR / SMOKE_ART
        path = Path(path)
        state['art'] = decode_rgb565(path.read_bytes())
        return {'size': list(state['art'].size), 'bytes': path.stat().st_size}

    def lcd():
        from control_center.lcd_preview import render_lcd
        if 'art' not in state:
            raise RuntimeError('art fixture unavailable')
        with_art = render_lcd(SMOKE_FRAME, state['art'])
        without_art = render_lcd(SMOKE_FRAME, None)
        if with_art.size != (240, 240) or with_art.mode != 'RGBA':
            raise RuntimeError(f'unexpected LCD image {with_art.mode} {with_art.size}')
        if with_art.tobytes() == without_art.tobytes():
            raise RuntimeError('artwork was not drawn')
        if without_art.convert('L').getbbox() is None:
            raise RuntimeError('no text or icons were drawn')
        return {'size': list(with_art.size)}

    def icons():
        from control_center.lcd_preview import icon_mask
        from control_center.presentation import ICONS
        checked = 0
        for name in ICONS:
            if not name:
                continue
            for size in SMOKE_ICON_SIZES:
                mask = icon_mask(name, size)
                if mask is None or mask.size != (size, size) or mask.getbbox() is None:
                    raise RuntimeError(f'icon {name}-{size} is missing or empty')
                checked += 1
        return {'icons': checked}

    def fonts_pil():
        from PIL import ImageFont
        from control_center.ui import FONT_DIR
        names = {}
        for family in ('Montserrat', 'Archivo'):
            face = ImageFont.truetype(str(FONT_DIR / f'{family}.ttf'), 20)
            names[family] = face.getname()[0]
            if names[family] != family:
                raise RuntimeError(f'{family}.ttf reports family {names[family]!r}')
        return names

    for name, check in (('art', art), ('lcd', lcd), ('icons', icons), ('fontsPil', fonts_pil),
                        ('artwork2', smoke_artwork2), ('overlay', smoke_overlay), ('appIcons', smoke_app_icons),
                        ('carouselRender', smoke_carousel_render), ('alive', smoke_alive),
                        ('processSettings', smoke_process_settings)):
        _smoke_check(results, name, check)
    if ui:
        # Before Tk exists, so each GDI/USER baseline is that window's alone.
        _smoke_check(results, 'overlayWindow', smoke_overlay_window)
        _smoke_check(results, 'carouselWindow', smoke_carousel_window)
        _smoke_check(results, 'stageWindow', smoke_stage)
        if headless:
            _smoke_check(results, 'uiHeadless', headless_ui_check)

    root = None
    try:
        if headless:
            raise _NoTk()
        import tkinter as tk
        from tkinter import font
        from control_center.ui import register_fonts
        registered = register_fonts()  # before the Tk root and any Tk font
        root = tk.Tk()
        root.withdraw()

        def fonts_tk():
            families = set(font.families(root))
            missing = [name for name in ('Montserrat', 'Archivo') if name not in families]
            if missing:
                raise RuntimeError('Tk cannot see ' + ', '.join(missing))
            return {'registered': registered}

        def imagetk():
            from PIL import Image, ImageTk
            image = Image.new('RGB', (240, 240), (20, 40, 60))
            photo = ImageTk.PhotoImage('RGB', image.size, master=root)
            photo.paste(image)
            if (photo.width(), photo.height()) != image.size:
                raise RuntimeError('PhotoImage size mismatch')
            return {'size': [photo.width(), photo.height()]}

        def ui_check():
            from control_center import ui as ui_module
            callback_errors = []
            # Anything escaping a Tk callback fails the check too (not only stderr).
            root.report_callback_exception = lambda kind, value, tb: callback_errors.append(
                f'{kind.__name__}: {value}'[:200])
            # The installed app's mode: no window, the floating knob fed every tick.
            overlay = SmokeOverlay()
            app = ui_module.ControlCenterApp(root, smoke=True, live=False, chrome=False, overlay=overlay)
            root.after(ui_ms, app.close)
            root.mainloop()
            # _poll_once isolates and counts each stage's failures (runtime,
            # claim, auth, picker-icons, render, mirror): any of them fails.
            stages = {stage: count for stage, count in getattr(app, 'failure_counts', {}).items() if count}
            if (app.mirror_failures or not app.lcd_renders or not overlay.scenes or overlay.errors
                    or stages or callback_errors):
                raise RuntimeError(f'overlay LCD renders={app.lcd_renders} scenes={overlay.scenes} '
                                   f'failures={app.mirror_failures} scene errors={overlay.errors[:3]} '
                                   f'stage failures={stages} callback errors={callback_errors[:3]}')
            return {'lcdRenders': app.lcd_renders, 'scenes': overlay.scenes, 'lcdPixels': overlay.lcd_px,
                    'uiFont': ui_module.UI_FAMILY}

        _smoke_check(results, 'fontsTk', fonts_tk)
        _smoke_check(results, 'imageTk', imagetk)
        if ui:
            _smoke_check(results, 'ui', ui_check)
    except _NoTk:
        pass                                  # --headless: no Tk root is ever created
    except Exception as exc:
        results['tk'] = {'passed': False, 'error': f'{type(exc).__name__}: {exc}'[:300]}
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass  # already destroyed by the UI check's close()
    passed = bool(results) and all(check['passed'] for check in results.values())
    now = time.time()
    report = {'passed': passed, 'pid': os.getpid(), 'executable': sys.executable,
              'frozen': bool(getattr(sys, 'frozen', False)), 'headless': bool(headless), 'timestamp': now,
              'time': datetime.datetime.fromtimestamp(now, datetime.timezone.utc).isoformat(),
              'checks': results}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'smoke-test.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--background', action='store_true')
    parser.add_argument('--show', action='store_true')
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--headless', action='store_true',
                        help='With --smoke-test: no Tk root at all (nothing is created on screen)')
    parser.add_argument('--check-music', action='store_true', help='Read-only packaged MusicKit diagnostic')
    args = parser.parse_args()
    # %LOCALAPPDATA%\DeskDial\logs (control_center.paths). Install-Desktop.ps1 reads the smoke report
    # from the same folder (rename-desk-dial.md 11.9: the two move together, else the install refuses).
    from control_center import paths
    logs = paths.logs_dir()
    logs.mkdir(parents=True, exist_ok=True)
    if args.check_music:
        from control_center.credentials import CredentialStore, CredentialError
        from control_center.apple_music import AppleMusicClient, AppleMusicError
        try:
            import tkinter as tk
            from control_center.ui import ControlCenterApp, DATA_DIR
            check_root = tk.Tk()
            check_root.withdraw()
            check_app = ControlCenterApp(check_root, live=True)
            page = check_app.runtime.apple.recent()
            result = {'passed': True, 'items': len(page['items']), 'hasNext': bool(page.get('next')),
                      'dataDir': str(DATA_DIR), 'credentialFile': credential_file_info(DATA_DIR)}
            check_app.runtime.close()
            check_root.destroy()
        except (CredentialError, AppleMusicError) as exc:
            result = {'passed': False, 'error': str(exc)}
        except Exception as exc:
            result = {'passed': False, 'error': type(exc).__name__}
        (logs / 'music-check.json').write_text(json.dumps(result), encoding='utf-8')
        return
    if args.smoke_test:
        # Before the single-instance mutex and the shared app.log: a smoke test
        # never signals or disturbs a running companion.
        raise SystemExit(run_smoke_test(logs, headless=args.headless))
    handler = RotatingFileHandler(logs / 'app.log', maxBytes=1_000_000, backupCount=3)
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format='%(asctime)s %(levelname)s %(message)s', force=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateEventW.restype = ctypes.c_void_p
    kernel.SetEvent.argtypes = [ctypes.c_void_p]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    mutex = kernel.CreateMutexW(None, False, 'Local\\NanoDControlCenter.App')
    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())
    duplicate = ctypes.get_last_error() == 183
    show_event = kernel.CreateEventW(None, False, False, 'Local\\NanoDControlCenter.Show')
    if duplicate:
        if not args.background:
            # The running instance opens Settings: let it come to the foreground.
            allow_foreground()
            kernel.SetEvent(show_event)
        kernel.CloseHandle(show_event)
        kernel.CloseHandle(mutex)
        return
    # Only the running instance writes crash.log (a duplicate launch just signals).
    diagnostics = enable_crash_diagnostics(logs)
    logging.info('Crash diagnostics: %s', diagnostics)
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass
    # K4 4.7.2: 1 ms timers, the power-throttling opt-out and the 1 ms switch interval, before any
    # thread of ours starts; the self-check is logged once. Undone at exit.
    process_settings = apply_process_settings()
    import tkinter as tk
    from control_center.ui import ControlCenterApp, APP_DIR, DATA_DIR, apply_app_icon, register_fonts
    from serial.tools.list_ports import comports
    register_fonts()  # process-private Archivo/Montserrat before any Tk font exists
    root = tk.Tk()
    # For the whole process: the root owns F24, Settings and the timers (the Windows picker is
    # the carousel's own native windows, never a Tk child of the root).
    root.withdraw()
    root.report_callback_exception = CallbackErrorReporter()
    apply_app_icon(root)   # APP_ICON.md item 3: before any Toplevel (Settings) exists
    overlay = start_overlay()
    icon = None            # the tray icon, once start_tray made it
    stage = None           # the explorer / Up next presenter (K4 4.1)
    tray_stopping = threading.Event()
    # Everything after start_overlay() runs inside this try: a startup failure (the app, the
    # tray, Settings) still closes the overlay thread's window (FLOATING_KNOB.md section 4),
    # stops a started tray and destroys the root before the interpreter finalizes.
    try:
        holder = {}
        # K4 4.1: NanoD-stage starts with the app, after the floating knob, inside this try. Its art
        # workers may fetch Sonos covers only from the configured speaker (read when they ask).
        stage = start_stage(speaker_hosts=lambda: tuple(
            host for host in (getattr(holder.get('app'), 'config', {}).get('speaker_ip'),) if host))
        # CAROUSEL.md 12.4 (WP7c-D11): the picker's GPU chrome is installed once, here, before
        # ControlCenterApp builds the WindowsAdapter, whose CarouselPresenter takes the factory when it is
        # made (a later install would leave the CPU chrome for the session). It never raises.
        install_picker_chrome()
        app = ControlCenterApp(root, live=True, chrome=False, overlay=overlay, stage=stage)
        holder['app'] = app
        app.process_settings = process_settings
        startup_credentials = credential_file_info(DATA_DIR)
        import pystray
        from PIL import Image
        requests = queue.Queue()
        lifecycle = queue.Queue()
        policy = RetryPolicy()
        preparing = None
        emit = app.device._emit
        def device_event(kind, **values):
            if kind in ('connected','ready','released','disconnected','closed','error'):
                lifecycle.put(kind)
                logging.info('Device %s: %s', kind, values.get('message', values.get('reason','')))
            emit(kind, **values)
        app.device._emit = device_event

        def open_settings():
            app.setup()

        def quit_app():
            policy.enabled = False
            stop_tray(icon, tray_stopping)
            app.close()

        def manual_connect():
            if app.runtime.device_connected or policy.inflight:
                policy.enabled = False
                app.device.submit('disconnect')
            else:
                policy.enabled = True
                policy.inflight = False
                policy.due = 0

        def connected_or_connecting():
            return bool(app.runtime.device_connected or policy.inflight)

        # pystray runs the menu on its own thread: items only queue a request. Never call
        # tkinter (or the app) from there; handle_requests runs them on the Tk thread.
        theme = taskbar_theme()
        present = knob_present(app.runtime)
        tray_state = TrayState(app.runtime.device_status, connected_or_connecting(), present)
        icon = start_tray(lambda: make_tray_icon(pystray, Image.open(tray_png(theme, present, APP_DIR)),
                                                 tray_state, requests.put,
                                                 icon_file=tray_icon_file(theme, present, APP_DIR),
                                                 on_theme=lambda: requests.put('theme')),
                          tray_stopping, requests.put)
        presenter = TrayPresenter(icon, tray_state, theme=theme, app_dir=APP_DIR)
        root.protocol('WM_DELETE_WINDOW', root.withdraw)
        connect_button = getattr(app, 'connect_button', None)   # only with the main window (chrome)
        if connect_button is not None:
            connect_button.configure(command=manual_connect)
        if not args.background: open_settings()
        logging.info('Standalone started pid=%s frozen=%s overlay=%s', os.getpid(), bool(getattr(sys,'frozen',False)),
                     getattr(overlay, 'state', None))
        handlers = {'peek': lambda: app.peek(PEEK_SECONDS), 'settings': open_settings,
                    'connect': manual_connect, 'quit': quit_app,
                    'theme': lambda: presenter.set_theme(taskbar_theme()),   # WM_SETTINGCHANGE (K4 20.3)
                    'fallback': lambda: tray_fallback(app, manual_connect, quit_app, connected_or_connecting)}

        def handle_requests():
            """Tray requests, the second-launch Show event, and the tray's status, knob state
            (tooltip, icon, header), notice and message balloons, on the Tk thread."""
            if app.closing: return
            try:
                if kernel.WaitForSingleObject(show_event, 0) == 0: open_settings()
                while True:
                    try:
                        command = requests.get_nowait()
                    except queue.Empty:
                        break
                    if route_request(command, handlers): return
                # The notice is only read: the knob keeps "Last action failed" until the next action.
                presenter.update(app.runtime.device_status, connected_or_connecting(), app.controller.notice,
                                 present=knob_present(app.runtime), messages=app.take_tray_messages())
            finally:
                if not app.closing:
                    root.after(REQUEST_POLL_MS, handle_requests)

        def poll_theme():
            # APP_ICON.md section 6 / K4 20.3: the backstop for WM_SETTINGCHANGE, every 30 s.
            try:
                presenter.set_theme(taskbar_theme())
            finally:
                if not app.closing:
                    root.after(THEME_POLL_MS, poll_theme)

        def maintain():
            # Rescheduled even when a step fails (e.g. status.json is locked):
            # auto-reconnect and the status file must never stop for good.
            try:
                maintain_once()
            finally:
                if not app.closing:
                    root.after(1000, maintain)

        def maintain_once():
            nonlocal preparing
            if app.closing: return
            now = time.monotonic()
            while not lifecycle.empty():
                kind = lifecycle.get_nowait()
                if kind == 'ready': policy.ready()
                elif kind in ('error','released','disconnected'):
                    preparing = None
                    policy.failed(now)
                    if kind in ('error','released') and app.device.serial is not None:
                        app.device.submit('disconnect')
            if policy.inflight and now > policy.due:
                app.device.submit('disconnect')
                policy.failed(now)
                preparing = None
            if preparing is not None:
                # A new controller requests current Sonos state; old completions and
                # gestures cannot target this controller or a remembered screen.
                if not policy.enabled:
                    preparing = None
                elif app.controller.state.get('online') or now >= preparing[1]:
                    app.config['port'] = preparing[0]
                    app.runtime.button_order = app.config['button_order'][:]
                    app.device.submit('connect', preparing[0])
                    preparing = None
                    policy.due = now + 40
            elif (not app.runtime.device_connected and app.device.serial is None
                  and policy.can_attempt(now)):
                port = matching_port(comports())
                if port:
                    policy.inflight = True
                    policy.due = now + 45
                    app.runtime.invalidate_actions()
                    app.runtime.windows.hide()
                    app.runtime.windows.set_hotkey_enabled(False)
                    app.controller = fresh_controller(app.controller, app.runtime)
                    app.runtime.attach(app.controller)  # idempotent; keeps the rebuild explicit
                    app.runtime.last_frame = None
                    preparing = (port, now + 5)
                else:
                    policy.due = now + 3
            status = status_payload(app, policy, startup_credentials,
                                    getattr(app.device, 'capabilities', None), DATA_DIR)
            (logs/'status.json').write_text(json.dumps(status, indent=2))
        root.after(REQUEST_POLL_MS, handle_requests)
        root.after(THEME_POLL_MS, poll_theme)
        root.after(500, maintain)
        root.mainloop()
    finally:
        # Every exit path, a failed startup included. The overlay thread owns its window: close
        # it (idempotent; app.close did it on a normal quit) before the root and the interpreter
        # go away; then the stage (its thread owns its host window), the tray (if it was started)
        # and the root.
        close_overlay(overlay)
        close_stage(stage)
        if icon is not None:
            stop_tray(icon, tray_stopping)
        try:
            root.destroy()
        except Exception:
            pass   # normally already destroyed by app.close()
        restore_process_settings(process_settings)
        kernel.CloseHandle(show_event)
        kernel.CloseHandle(mutex)

if __name__ == '__main__':
    try:
        main()
    except Exception:
        logging.exception('Application failed')
        raise
