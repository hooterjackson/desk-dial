"""Host window roles and the input contract (DESKTOP_STAGE §2.1, §2.5, §2.6, §3, §4.1).

Roles:
- ``click_eating`` (the stage host, §2.1): ``WS_POPUP``, ex ``WS_EX_TOPMOST | WS_EX_TOOLWINDOW |
  WS_EX_NOACTIVATE | WS_EX_NOREDIRECTIONBITMAP`` = **0x08200088**. Not layered, not transparent:
  ``WM_NCHITTEST`` -> ``HTCLIENT`` everywhere and ``WM_MOUSEACTIVATE`` -> ``MA_NOACTIVATE`` (3), so a
  click reaches the window and nothing activates. A left button **down and up both inside the
  rest rect** of the centre card (explorer) or the focus plate (Up next) is one
  ``click_action``; every other click, every right / middle / X button and every wheel turn is
  eaten with no action (S5-3, S5-23). Keys never arrive (the host never has focus, §22 Q4).
- ``click_through`` (§19.2's P1 fallback and the G1 spike's proven host): the same plus
  ``WS_EX_LAYERED | WS_EX_TRANSPARENT`` = **0x082800A8**, ``WM_NCHITTEST`` -> ``HTTRANSPARENT``.
  (The toast and floating knob use the ULW variant 0x080800A8 on their own threads, FK §4.)

Show / hide (§3, FK:127): shown only with ``SetWindowPos(HWND_TOPMOST, rcMonitor, SWP_NOACTIVATE |
SWP_NOOWNERZORDER | SWP_SHOWWINDOW)`` - never ``SW_SHOW*``, ``SetForegroundWindow``,
``SetActiveWindow`` or ``BringWindowToTop`` (a static test scans for them); hidden with
``ShowWindow(SW_HIDE)`` on the stage thread. Created hidden (never ``WS_VISIBLE``), class
``NanoD.Stage.Host`` with a module-level WNDPROC thunk that is never freed,
``ERROR_CLASS_ALREADY_EXISTS`` tolerated, DWM attributes set once (transitions off, excluded from
peek, square corners), ``WM_SETCURSOR`` -> the arrow. Handlers are wrapped in ``try/except
BaseException`` and fall back to ``DefWindowProcW``.

System notifications (§4.1; the host is the app's single observer for all three overlays):
session lock and console / remote disconnect -> ``lock``; ``PBT_APMSUSPEND`` or the console
display turning off (``GUID_CONSOLE_DISPLAY_STATE`` = 0) -> ``sleep`` (and ``display_off`` for the
harvest, G1-3); display on -> ``display_on``; ``WM_DISPLAYCHANGE``, ``WM_DPICHANGED``,
``WM_SETTINGCHANGE(SPI_SETWORKAREA)``, ``WM_DWMCOMPOSITIONCHANGED`` -> ``display``;
``WM_SETTINGCHANGE(SPI_SETCLIENTAREAANIMATION)`` -> ``motion``; ``WM_ENDSESSION`` -> ``endsession``.
All are unregistered at close.

``WM_DPICHANGED`` caused by the host's **own** show is not a display change (WP7a-R5): the hidden
host sits where it was last shown, and moving it onto a monitor of another DPI makes Windows send
it that message. It is ignored while ``own_move()`` is active (``show`` wraps its
``SetWindowPos``), and whenever the new DPI equals ``expected_dpi``, the DPI of the monitor the
open scene was laid out for (set by the engine; that covers a late delivery). Only a DPI that
differs from the scene's monitor is ``display`` (K4 §4.3, VOC-K4-01).

``HostInput`` is the pure message logic (tests drive it without Win32); ``HostWindow`` is the
Win32 window on the ``NanoD-stage`` thread; ``hidden_only=True`` (tests, the self-test) creates it
off-screen at 1 x 1, refuses to show it and does not register for the console display state (so a
headless run never depends on whether the PC's display is on; RN-R5).
"""
from __future__ import annotations

import contextlib
import ctypes as C

ROLE_CLICK_EATING, ROLE_CLICK_THROUGH = "click_eating", "click_through"
EX_CLICK_EATING = 0x08200088
EX_CLICK_THROUGH = 0x082800A8
EX_STYLES = {ROLE_CLICK_EATING: EX_CLICK_EATING, ROLE_CLICK_THROUGH: EX_CLICK_THROUGH}
CLASS_NAME = "NanoD.Stage.Host"

WM_CLOSE, WM_ERASEBKGND, WM_ENDSESSION, WM_SETTINGCHANGE = 0x0010, 0x0014, 0x0016, 0x001A
WM_SETCURSOR, WM_MOUSEACTIVATE, WM_CONTEXTMENU, WM_DISPLAYCHANGE = 0x0020, 0x0021, 0x007B, 0x007E
WM_NCHITTEST = 0x0084
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK = 0x0200, 0x0201, 0x0202, 0x0203
WM_RBUTTONDOWN, WM_RBUTTONUP, WM_RBUTTONDBLCLK = 0x0204, 0x0205, 0x0206
WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MBUTTONDBLCLK = 0x0207, 0x0208, 0x0209
WM_MOUSEWHEEL, WM_XBUTTONDOWN, WM_XBUTTONUP, WM_XBUTTONDBLCLK, WM_MOUSEHWHEEL = 0x020A, 0x020B, 0x020C, 0x020D, 0x020E
WM_POWERBROADCAST, WM_WTSSESSION_CHANGE, WM_DPICHANGED, WM_DWMCOMPOSITIONCHANGED = 0x0218, 0x02B1, 0x02E0, 0x031E
WM_APP = 0x8000
WM_APP_WAKE = WM_APP + 0x31          # the presenter's post (any thread -> the stage thread)

MA_NOACTIVATE = 3
HTCLIENT, HTTRANSPARENT = 1, -1
PBT_APMSUSPEND, PBT_POWERSETTINGCHANGE = 0x4, 0x8013
WTS_CONSOLE_DISCONNECT, WTS_REMOTE_DISCONNECT, WTS_SESSION_LOCK = 2, 4, 7
SPI_SETWORKAREA, SPI_SETCLIENTAREAANIMATION = 0x002F, 0x1043
SHOW_FLAGS = 0x10 | 0x200 | 0x40      # SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_SHOWWINDOW

EATEN_BUTTONS = {WM_RBUTTONDOWN, WM_RBUTTONUP, WM_RBUTTONDBLCLK, WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MBUTTONDBLCLK,
                 WM_LBUTTONDBLCLK, WM_CONTEXTMENU, WM_MOUSEMOVE}
X_BUTTONS = {WM_XBUTTONDOWN, WM_XBUTTONUP, WM_XBUTTONDBLCLK}
WHEELS = {WM_MOUSEWHEEL, WM_MOUSEHWHEEL}


def lparam_point(lp):
    """Signed client coordinates of a mouse message (GET_X_LPARAM / GET_Y_LPARAM)."""
    lp = int(lp) & 0xFFFFFFFF
    x, y = lp & 0xFFFF, (lp >> 16) & 0xFFFF
    return (x - 0x10000 if x & 0x8000 else x), (y - 0x10000 if y & 0x8000 else y)


def make_lparam(x, y):
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


class HostInput:
    """Pure message logic of a host role. ``notify(kind)`` receives 'click_action', 'lock',
    'sleep', 'display_off', 'display_on', 'display', 'motion' and 'endsession'. ``cursor()``
    sets the arrow; ``power_setting(lp)`` returns (is_console_display_state, value) for a
    ``PBT_POWERSETTINGCHANGE`` lParam."""

    def __init__(self, role, notify, *, cursor=None, power_setting=None):
        if role not in EX_STYLES:
            raise ValueError(role)
        self.role = role
        self.notify = notify
        self.cursor = cursor
        self.power_setting = power_setting
        self.hit_rect = None
        self.pending = False
        self.eaten = {"left": 0, "other_buttons": 0, "wheel": 0}
        self.clicks = 0
        self.expected_dpi = None           # the open scene's monitor DPI (engine), or None
        self.moving = 0                    # > 0 inside our own SetWindowPos (``own_move``)
        self.dpi_ignored = 0

    @contextlib.contextmanager
    def own_move(self):
        """Around the host's own ``SetWindowPos``: a ``WM_DPICHANGED`` it causes is ignored."""
        self.moving += 1
        try:
            yield
        finally:
            self.moving -= 1

    def set_hit_rect(self, rect):
        """The rest rect (client px: left, top, right, bottom) that acts as Button 4, or None
        (no scene, a block state, a switch or Play in progress)."""
        self.hit_rect = tuple(int(v) for v in rect) if rect else None
        self.pending = False

    def _inside(self, lp):
        if not self.hit_rect:
            return False
        x, y = lparam_point(lp)
        l, t, r, b = self.hit_rect
        return l <= x < r and t <= y < b

    def handle(self, msg, wp, lp):
        """The window procedure's answer, or None for DefWindowProcW."""
        if msg == WM_NCHITTEST:
            return HTCLIENT if self.role == ROLE_CLICK_EATING else HTTRANSPARENT
        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE
        if msg == WM_SETCURSOR:
            if self.cursor is not None:
                self.cursor()
            return 1
        if msg == WM_LBUTTONDOWN:
            self.pending = self._inside(lp)
            self.eaten["left"] += 1
            return 0
        if msg == WM_LBUTTONUP:
            hit = self.pending and self._inside(lp)
            self.pending = False
            if hit:
                self.clicks += 1
                self.notify("click_action")
            return 0
        if msg in WHEELS:
            self.eaten["wheel"] += 1
            return 0
        if msg in X_BUTTONS:
            self.eaten["other_buttons"] += 1
            return 1                               # TRUE: processed (WM_XBUTTON* contract)
        if msg in EATEN_BUTTONS:
            if msg != WM_MOUSEMOVE:
                self.eaten["other_buttons"] += 1
            return 0
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_CLOSE:
            return 0                               # the engine destroys the host, nobody else
        if msg == WM_WTSSESSION_CHANGE:
            if int(wp) in (WTS_SESSION_LOCK, WTS_CONSOLE_DISCONNECT, WTS_REMOTE_DISCONNECT):
                self.notify("lock")
            return 0
        if msg == WM_POWERBROADCAST:
            if int(wp) == PBT_APMSUSPEND:
                self.notify("sleep")
            elif int(wp) == PBT_POWERSETTINGCHANGE and self.power_setting is not None:
                is_display, value = self.power_setting(lp)
                if is_display:
                    if value == 0:
                        self.notify("display_off")
                        self.notify("sleep")
                    elif value == 1:
                        self.notify("display_on")
            return 1
        if msg == WM_DPICHANGED:
            dpi = int(wp) & 0xFFFF
            if self.moving or (self.expected_dpi and dpi == self.expected_dpi):
                self.dpi_ignored += 1              # our own move onto the scene's monitor (R5)
            else:
                self.notify("display")
            return 0                               # handled: we position the host ourselves
        if msg in (WM_DISPLAYCHANGE, WM_DWMCOMPOSITIONCHANGED):
            self.notify("display")
            return None
        if msg == WM_SETTINGCHANGE:
            if int(wp) == SPI_SETWORKAREA:
                self.notify("display")
            elif int(wp) == SPI_SETCLIENTAREAANIMATION:
                self.notify("motion")
            return None
        if msg == WM_ENDSESSION:
            if wp:
                self.notify("endsession")
            return 0
        if msg == WM_APP_WAKE:
            return 0
        return None


# --------------------------------------------------------------------------- Win32
_HANDLERS = {}                   # hwnd -> HostInput.handle (stage thread only)
_THUNK = None
_DEF = None
_FAILURES = {"count": 0}


def _wndproc(hwnd, msg, wp, lp):
    try:
        h = _HANDLERS.get(hwnd)
        if h is not None:
            r = h(msg, wp, lp)
            if r is not None:
                return int(r)
    except BaseException:
        _FAILURES["count"] += 1
    try:
        return _DEF(hwnd, msg, wp, lp) if _DEF is not None else 0
    except BaseException:
        return 0


def _thunk():
    """The class WNDPROC, created once per process and never freed (a message racing
    DestroyWindow may still call it)."""
    global _THUNK, _DEF
    if _THUNK is None:
        from . import win32 as W
        _DEF = W.DefWindowProcW
        _THUNK = W.WNDPROC(_wndproc)
    return _THUNK


def read_power_setting(lp):
    """(is GUID_CONSOLE_DISPLAY_STATE, DWORD value) of a POWERBROADCAST_SETTING* lParam."""
    from . import com, win32 as W
    if not lp:
        return False, None
    ps = W.POWERBROADCAST_SETTING.from_address(int(lp))
    same = bytes(ps.PowerSetting) == bytes(com.GUID_CONSOLE_DISPLAY_STATE)
    if not same or ps.DataLength < 1:
        return same, None
    return True, C.c_uint32.from_address(int(lp) + W.POWERBROADCAST_SETTING.Data.offset).value \
        if ps.DataLength >= 4 else ps.Data[0]


class HostWindow:
    """The Win32 host of one role (create, show, hide and destroy on the owning thread)."""

    def __init__(self, handler: HostInput, *, hidden_only: bool = False):
        from . import win32 as W
        self.W = W
        self.handler = handler
        self.role = handler.role
        self.hidden_only = hidden_only
        self.hwnd = None
        self.notifications = {"wts": False, "power": None}
        self.shown = False
        self.info = {}
        hinst = W.GetModuleHandleW(None)
        wc = W.WNDCLASSEXW()
        wc.cbSize = C.sizeof(W.WNDCLASSEXW)
        wc.lpfnWndProc = _thunk()
        wc.hInstance = hinst
        wc.hCursor = W.LoadCursorW(None, C.c_void_p(W.IDC_ARROW))
        wc.lpszClassName = CLASS_NAME
        if not W.RegisterClassExW(C.byref(wc)):
            err = C.get_last_error()
            if err != W.ERROR_CLASS_ALREADY_EXISTS:
                raise C.WinError(err)
        x, y, w, h = (-32000, -32000, 1, 1)
        hwnd = W.CreateWindowExW(EX_STYLES[self.role], CLASS_NAME, "", W.WS_POPUP, x, y, w, h, None, None, hinst,
                                 None)
        if not hwnd:
            raise C.WinError(C.get_last_error())
        self.hwnd = hwnd
        _HANDLERS[hwnd] = handler.handle
        one, corner = C.c_int(1), C.c_int(W.DWMWCP_DONOTROUND)
        self.info["dwm"] = [W.DwmSetWindowAttribute(hwnd, W.DWMWA_TRANSITIONS_FORCEDISABLED, C.byref(one), 4),
                            W.DwmSetWindowAttribute(hwnd, W.DWMWA_EXCLUDED_FROM_PEEK, C.byref(one), 4),
                            W.DwmSetWindowAttribute(hwnd, W.DWMWA_WINDOW_CORNER_PREFERENCE, C.byref(corner), 4)]
        self.info["ex_style"] = self.ex_style()
        self.info["visible_after_create"] = self.visible()
        self._arrow = wc.hCursor
        if handler.cursor is None:
            handler.cursor = lambda: W.SetCursor(self._arrow)
        if handler.power_setting is None:
            handler.power_setting = read_power_setting

    def ex_style(self) -> int:
        return int(self.W.GetWindowLongPtrW(self.hwnd, self.W.GWL_EXSTYLE)) & 0xFFFFFFFF if self.hwnd else 0

    def visible(self) -> bool:
        return bool(self.hwnd and self.W.IsWindowVisible(self.hwnd))

    def register_notifications(self):
        """Session changes always; the console display state only on a host that can be shown.

        A hidden-only host (tests, the self-tests) never registers for ``GUID_CONSOLE_DISPLAY_STATE``:
        Windows answers that registration at once with the current state, so with the PC's display
        off a headless run would get ``display_off`` + ``sleep``, an event it never caused (review
        finding RN-R5; the stage owner's fix, lead decision 2026-09-26). ``PBT_APMSUSPEND`` needs no
        registration and still arrives."""
        from . import com
        W = self.W
        if not self.notifications["wts"]:
            self.notifications["wts"] = bool(W.WTSRegisterSessionNotification(self.hwnd, W.NOTIFY_FOR_THIS_SESSION))
        if self.hidden_only:
            self.info["power_notification"] = "skipped: hidden-only host"
        elif not self.notifications["power"]:
            self.notifications["power"] = W.RegisterPowerSettingNotification(
                self.hwnd, C.byref(com.GUID_CONSOLE_DISPLAY_STATE), W.DEVICE_NOTIFY_WINDOW_HANDLE) or None
        return dict(self.notifications)

    def unregister_notifications(self):
        W = self.W
        if self.notifications["wts"]:
            W.WTSUnRegisterSessionNotification(self.hwnd)
            self.notifications["wts"] = False
        if self.notifications["power"]:
            W.UnregisterPowerSettingNotification(self.notifications["power"])
            self.notifications["power"] = None

    def show(self, rect):
        """§3: topmost over ``rect`` (x, y, w, h = rcMonitor) without activating."""
        if self.hidden_only:
            raise RuntimeError("this host is hidden-only (tests and the self-test never show it)")
        x, y, w, h = (int(v) for v in rect)
        with self.handler.own_move():                  # a WM_DPICHANGED sent from inside is ours (R5)
            ok = bool(self.W.SetWindowPos(self.hwnd, self.W.HWND_TOPMOST, x, y, w, h, SHOW_FLAGS))
        self.shown = ok
        return ok

    def hide(self):
        if self.hwnd and self.W.IsWindow(self.hwnd):
            self.W.ShowWindow(self.hwnd, self.W.SW_HIDE)
        self.shown = False

    def exclude_from_capture(self, on: bool) -> bool:
        return bool(self.W.SetWindowDisplayAffinity(self.hwnd, self.W.WDA_EXCLUDEFROMCAPTURE if on
                                                    else self.W.WDA_NONE))

    def post_wake(self) -> bool:
        return bool(self.hwnd and self.W.PostMessageW(self.hwnd, WM_APP_WAKE, 0, 0))

    def destroy(self):
        if not self.hwnd:
            return
        try:
            self.unregister_notifications()
        finally:
            self.W.ShowWindow(self.hwnd, self.W.SW_HIDE)
            _HANDLERS.pop(self.hwnd, None)
            self.W.DestroyWindow(self.hwnd)
            self.hwnd = None


def pump_messages(W=None) -> int:
    """Drain this thread's queue with PeekMessageW (the top of every loop turn). -1 on WM_QUIT."""
    import ctypes.wintypes as WT
    if W is None:
        from . import win32 as W
    msg = WT.MSG()
    n = 0
    while W.PeekMessageW(C.byref(msg), None, 0, 0, W.PM_REMOVE):
        n += 1
        if msg.message == W.WM_QUIT:
            return -1
        W.TranslateMessage(C.byref(msg))
        W.DispatchMessageW(C.byref(msg))
    return n
