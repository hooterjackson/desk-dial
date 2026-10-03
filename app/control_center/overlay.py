"""Floating knob overlay (desktop v5): the knob face slides in from the left edge.

FLOATING_KNOB.md section 4 is normative. The overlay is a click-through,
never-activated, per-pixel-alpha layered popup. It is presented with
UpdateLayeredWindow from a premultiplied BGRA DIB twice the window's width. The
content sits in the left half, and the slide moves ``ptSrc.x`` from W (hidden)
to 0 (shown) while SourceConstantAlpha fades 0..255. The window rectangle stays
fixed inside the primary monitor's work area, so it never appears on a monitor
to the left and never straddles monitors.

Placement (section 9.11): the window box starts at the work area's left edge and
is the knob face plus the 24 logical px inset wide; the face is drawn ``inset``
px into the box (window_rect). The shown knob sits exactly where section 4 puts
it, and while it slides it emerges from the screen edge instead of from a cut
line 24 px inside it.

Thread boundary (the rule behind the crash documented in windows.py:10-22):
- The ``NanoD-overlay`` thread is the only thread that touches the overlay's
  HWND, memory DC and DIB. It never imports or calls tkinter.
- The Tk thread only posts (PostMessageW) and hands data over through the
  lock-protected Mailbox, where the newest scene wins. Nothing SendMessages the
  overlay, and nothing but its own thread calls SetWindowPos or ShowWindow on it.

Layers, so that the state machine and scheduling run without Win32:
- SlideMachine: the pure hidden -> in -> shown -> out -> hidden machine, with easing.
- OverlayEngine: overlay-thread logic (touches, suppression, scene hand-off,
  geometry, compose, present), driven by a backend and an injected clock.
- Win32Backend: the only code that calls user32/gdi32/dwmapi/shcore/shell32.
- KnobOverlay: the Tk-thread facade. It only posts and coalesces, and it owns
  the thread.

Clock: the default ``time.monotonic`` is QueryPerformanceCounter on Windows
(Python >= 3.13, resolution 100 ns), the same source as ``time.perf_counter``.
The one injected clock therefore drives the touch deadlines and the vsync-paced
animation steps, which is what makes the fake-clock tests possible.

Recorded refinements of section 4 (intentional; the spec's letter is otherwise followed):
- First frame: a slide-in from ``hidden`` is armed until a scene submitted at or
  after the touch arrives, for at most FIRST_FRAME_WAIT_SECONDS (100 ms), so the
  frame presented while hidden is the current face, not a stale one. ui.py submits
  before touch() on the touch tick, so this adds ~0 ms to a touch and at most one
  25 ms UI tick to a tray peek().
- Suppression travels to the overlay thread as its own posted WM_APP+4
  (WM_APP+1 frame, +2 touch, +3 stop). The overlay thread also re-reads the
  reasons on every wake-up, so a release whose post was lost cannot stick.
- ``wants_frames`` turns true as soon as touch()/peek() is accepted, one step
  before the overlay thread leaves ``hidden``, so the Tk side renders the first
  frame on its next tick; it falls back to "state is not hidden" once the overlay
  thread has taken the touch (a touch it ignores, e.g. full screen, clears it).

Desktop v7 (DESKTOP_STAGE K4 section 11, section 5; ALIVE.md K2 revision 2 section 10.3):
for a knob with ``alive`` (``set_alive(True)``) the ring is drawn by the ``AliveLights``
engine **on this thread** (``AliveMirror``), with the six glow looks of
``knob_face.AliveFace``. Inputs:
- the serial reader's **fast path** (``post_input``: ``position`` (p, delta) as a detent,
  ``limit``, ``press``), each stamped with its QPC read time (any thread; PostMessageW
  WM_APP+5); every one is also a touch, so a ``lim`` summons the knob like a turn;
- the decorated frames, the claim state, the control's maximum and the latched clock,
  progress, reduced-motion and tuning values from the Tk thread (``post_frame``,
  ``set_latched``: WM_APP+6), newest frame wins; the LCD still comes as a scene.
While the overlay is visible the engine renders **at every vblank**, sampled at the
predicted display time (P2), paced on the compositor clock (P3, with the G1-2 timer
fallback; ``KnobPacer`` P4/P5), and the face is composed straight into the DIB
(``AliveFace.compose_into`` through ``Win32Backend.canvas``) only when its quantised
content changed (AR-22); while hidden there is **no loop and no timer**: one engine
render per posted message at that message's stamp, after the catch-up of K2 M27
(``AliveMirror.catch_up``: steps of 50 ms, at most 60, a gap over 3 s first rendered once
at now - 3 s), never a compose or a present. "Hidden" lasts until the first visible frame:
a summoning input and a frame posted during the slide-in's arm wait take the same path, so
the launch's catch-up spans only the time since the last of them. Reduced motion: no slide, a 200 ms fade in
place. ``metrics()["frames"]["knob"]`` is K4 6.2's FrameStats (``slide`` and ``ring``
episodes, changed-frame lateness) and ``looks_build_ms`` the look sprites' build time.
Knobs without ``alive`` keep the v5 path above (PreviewLights scenes, KnobFace, DwmFlush).
"""
from __future__ import annotations

import ctypes as C
import logging
import math
import sys
import threading
import time
from collections import deque, namedtuple

__all__ = [
    "OverlayScene", "KnobOverlay", "OverlayEngine", "SlideMachine", "Win32Backend", "OverlayApi",
    "OverlayError", "Geometry", "Mailbox", "ease_in_cubic", "ease_out_cubic", "window_rect",
    "AliveMirror", "KnobPacer", "KnobFrameStats",
]

_LOGGER = logging.getLogger(__name__)
_LOGGER.addHandler(logging.NullHandler())  # the application configures the real handlers

# ------------------------------------------------------------------ public data
OverlayScene = namedtuple("OverlayScene", "lcd_key lcd ring")
"""One frame's content: ``lcd_key`` (hashable; identical key + ring = identical
scene), ``lcd`` (a PIL RGBA image at the overlay's ``lcd_px``, or None; never
mutated after hand-off) and ``ring`` (60 ``(r, g, b, level)``)."""

Geometry = namedtuple("Geometry", "work dpi")
"""Primary monitor work area ``(left, top, right, bottom)`` in physical px, and its effective DPI."""

HIDDEN, IN, SHOWN, OUT, DISABLED = "hidden", "in", "shown", "out", "disabled"
STATES = (HIDDEN, IN, SHOWN, OUT, DISABLED)

# -------------------------------------------------------------------- behaviour
THREAD_NAME = "NanoD-overlay"
CLASS_NAME = "NanoD.KnobOverlay"
WINDOW_TITLE = "Desk Dial knob"       # rename-desk-dial.md A12; CLASS_NAME stays (H8)
HIDE_SECONDS = 2.5
SLIDE_IN_SECONDS = 0.220          # ease-out cubic
SLIDE_OUT_SECONDS = 0.260         # ease-in cubic
START_TIMEOUT_SECONDS = 2.0       # the Tk side waits at most this long for the window
CLOSE_TIMEOUT_SECONDS = 1.0       # close() joins the thread at most this long
FIRST_FRAME_WAIT_SECONDS = 0.1    # a slide-in from hidden waits this long for a fresh scene
FRESH_SCENE_SLACK_SECONDS = 0.03  # a scene submitted within one UI tick before the touch is fresh
PRESENT_RETRY_SECONDS = 0.25      # a failed UpdateLayeredWindow (lock screen, secure desktop) is retried
PACE_FALLBACK_MS = 8              # MsgWaitForMultipleObjectsEx pacing when DwmFlush fails
FAST_FLUSH_SECONDS = 0.0005       # a DwmFlush this fast twice in a row is treated as not pacing
LOG_INTERVAL_SECONDS = 30.0       # rate limit per failure kind
TIME_EPSILON = 1e-9               # float sums of clock steps may land a hair short of an end time
TIMER_ID = 1
USER_TIMER_MINIMUM_MS = 10
DESIGN_RING_OUTER = 143           # design px, outer end of a ring segment (knob_face.DESIGN_RING_OUTER)
LCD_DESIGN_PX = 240
RING_LOGICAL_PX = 360
INSET_LOGICAL_PX = 24
UNLIT_SEGMENT = (0x1F, 0x1F, 0x1F, 0.0)
BLANK_RING = (UNLIT_SEGMENT,) * 60
FULLSCREEN_NOTIFICATION_STATES = frozenset({3, 4})  # QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE
SUPPRESS_NAVIGATOR = "navigator"   # r3: held while the Navigator replaces the floating knob (presentation >= 6)

# Engine events (backend -> engine). The Win32 backend maps window messages to these.
EV_FRAME, EV_TOUCH, EV_STOP, EV_SUPPRESS = "frame", "touch", "stop", "suppress"
EV_DIRTY, EV_HIDE, EV_TIMER = "dirty", "hide", "timer"
EV_INPUT, EV_ALIVE = "input", "alive"         # desktop v7: fast-path inputs, Tk alive frames

# Desktop v7 (K4 11.2, K2 M27; P12).
UINT32 = 0xFFFFFFFF
CATCHUP_STEP_SECONDS = 0.050                  # the engine's dt clamp (AL section 4)
CATCHUP_MAX_STEPS = 60
CATCHUP_SPAN_SECONDS = 3.0                    # a longer gap first renders once at now - 3 s
REDUCED_FADE_SECONDS = 0.200                  # reduced motion: a fade in place (S5-16)
INPUT_QUEUE_LIMIT = 256                       # fast-path inputs kept while the overlay thread is busy
INPUT_KINDS = ("position", "limit", "press")
DEFAULT_PERIOD_SECONDS = 1 / 60               # before the first DwmGetCompositionTimingInfo
FRAME_RECORDS = 4096                          # per-frame records kept for the running episode
THREAD_PRIORITY_ABOVE_NORMAL = 1              # P13

# SlideMachine.touch results
ARM, REVERSE, EXTEND = "arm", "reverse", "extend"

ANIMATING = 0.0


class OverlayError(RuntimeError):
    """The overlay window could not be created or used; the overlay disables itself."""


def window_rect(work, dpi, face_size, inset_logical_px=INSET_LOGICAL_PX):
    """The overlay window for a knob face of ``face_size`` (W, H) physical px on the
    primary monitor's work area ``work`` (left, top, right, bottom) at ``dpi``:
    ``(x, y, width, height, inset)`` in physical px (FLOATING_KNOB.md section 9.11).

    The box starts at the work area's left edge and is ``W + inset`` wide, where
    ``inset`` is the 24 logical px of section 4 at this DPI; the face is drawn
    ``inset`` px into it, vertically centred. The shown face therefore sits exactly
    ``inset`` px from the edge, and a slide (ptSrc.x from ``width`` to 0) moves it
    out from the screen edge itself, never from a cut line inside it."""
    left, top, _right, bottom = (int(v) for v in work)
    face_width, face_height = (int(v) for v in face_size)
    inset = max(0, int(round(inset_logical_px * int(dpi or 96) / 96)))
    return left, top + (bottom - top - face_height) // 2, face_width + inset, face_height, inset


# ------------------------------------------------------------- Win32: types
# Same conventions as control_center/windows.py (pointer-sized handles,
# LPARAM/LRESULT = ssize_t, WPARAM = size_t); verified by overlay_proto.py on x64.
DWORD = C.c_uint32
LONG = C.c_int32
BOOL = C.c_int32
UINT = C.c_uint32
BYTE = C.c_ubyte
WORD = C.c_uint16
ATOM = C.c_uint16
HANDLE = C.c_void_p           # HWND, HDC, HBITMAP, HGDIOBJ, HMONITOR, HINSTANCE, HCURSOR ...
LPARAM = C.c_ssize_t          # also LRESULT
WPARAM = C.c_size_t
UINT_PTR = C.c_size_t
DPI_CONTEXT = C.c_void_p      # DPI_AWARENESS_CONTEXT is a pseudo-handle
WINFUNCTYPE = getattr(C, "WINFUNCTYPE", C.CFUNCTYPE)
WNDPROC = WINFUNCTYPE(LPARAM, HANDLE, UINT, WPARAM, LPARAM)


class POINT(C.Structure):
    _fields_ = [("x", LONG), ("y", LONG)]


class SIZE(C.Structure):
    _fields_ = [("cx", LONG), ("cy", LONG)]


class RECT(C.Structure):
    _fields_ = [("left", LONG), ("top", LONG), ("right", LONG), ("bottom", LONG)]


class MONITORINFO(C.Structure):
    _fields_ = [("cbSize", DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", DWORD)]


class BLENDFUNCTION(C.Structure):
    _fields_ = [("BlendOp", BYTE), ("BlendFlags", BYTE),
                ("SourceConstantAlpha", BYTE), ("AlphaFormat", BYTE)]


class BITMAPINFOHEADER(C.Structure):
    _fields_ = [("biSize", DWORD), ("biWidth", LONG), ("biHeight", LONG), ("biPlanes", WORD),
                ("biBitCount", WORD), ("biCompression", DWORD), ("biSizeImage", DWORD),
                ("biXPelsPerMeter", LONG), ("biYPelsPerMeter", LONG), ("biClrUsed", DWORD),
                ("biClrImportant", DWORD)]


class BITMAPINFO(C.Structure):
    # 32bpp BI_RGB has no colour table; one RGBQUAD keeps the C layout.
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", DWORD * 1)]


class WNDCLASSEXW(C.Structure):
    _fields_ = [("cbSize", UINT), ("style", UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", C.c_int), ("cbWndExtra", C.c_int), ("hInstance", HANDLE),
                ("hIcon", HANDLE), ("hCursor", HANDLE), ("hbrBackground", HANDLE),
                ("lpszMenuName", C.c_wchar_p), ("lpszClassName", C.c_wchar_p), ("hIconSm", HANDLE)]


class MSG(C.Structure):
    _fields_ = [("hwnd", HANDLE), ("message", UINT), ("wParam", WPARAM), ("lParam", LPARAM),
                ("time", DWORD), ("pt", POINT), ("lPrivate", DWORD)]


# ---------------------------------------------------------- Win32: constants
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x00000008, 0x00000020, 0x00000080
WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x00080000, 0x08000000
OVERLAY_EX_STYLE = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT
OVERLAY_STYLE = WS_POPUP      # never WS_VISIBLE at creation
SW_HIDE, SW_SHOWNA = 0, 8
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
SWP_SHOWWINDOW, SWP_NOOWNERZORDER = 0x0040, 0x0200
SHOW_FLAGS = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_SHOWWINDOW
ULW_ALPHA = 0x2
AC_SRC_OVER, AC_SRC_ALPHA = 0x00, 0x01
BI_RGB, DIB_RGB_COLORS = 0, 0
PM_NOREMOVE, PM_REMOVE = 0x0000, 0x0001
WM_USER = 0x0400
WM_DESTROY, WM_CLOSE, WM_QUIT, WM_TIMER = 0x0002, 0x0010, 0x0012, 0x0113
WM_MOUSEACTIVATE, MA_NOACTIVATE = 0x0021, 3
WM_NCHITTEST, HTTRANSPARENT = 0x0084, -1
WM_DISPLAYCHANGE, WM_SETTINGCHANGE, WM_DPICHANGED = 0x007E, 0x001A, 0x02E0
WM_DWMCOMPOSITIONCHANGED = 0x031E
WM_POWERBROADCAST, PBT_APMSUSPEND = 0x0218, 0x0004
PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC = 0x0007, 0x0012
WM_ENDSESSION = 0x0016
SPI_SETWORKAREA = 0x002F
WM_APP = 0x8000
WM_APP_FRAME, WM_APP_TOUCH, WM_APP_STOP, WM_APP_SUPPRESS = WM_APP + 1, WM_APP + 2, WM_APP + 3, WM_APP + 4
WM_APP_INPUT, WM_APP_ALIVE = WM_APP + 5, WM_APP + 6
MONITOR_DEFAULTTOPRIMARY = 1
MDT_EFFECTIVE_DPI = 0
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
DPI_AWARENESS_PER_MONITOR_AWARE = 2
GR_GDIOBJECTS, GR_USEROBJECTS = 0, 1
QS_ALLINPUT = 0x04FF
MWMO_INPUTAVAILABLE = 0x0004
ERROR_CLASS_ALREADY_EXISTS = 1410

# Posted message -> engine event (the Win32 backend and the test fakes share it).
POSTED_EVENTS = {WM_APP_FRAME: EV_FRAME, WM_APP_TOUCH: EV_TOUCH,
                 WM_APP_STOP: EV_STOP, WM_APP_SUPPRESS: EV_SUPPRESS,
                 WM_APP_INPUT: EV_INPUT, WM_APP_ALIVE: EV_ALIVE}

# (dll attribute, export, restype, argtypes). Private WinDLL instances only, never
# ctypes.windll, so no declaration is shared with pystray or other modules.
DECLARATIONS = (
    # class + window lifetime (overlay thread only)
    ("u", "RegisterClassExW", ATOM, (C.POINTER(WNDCLASSEXW),)),
    ("u", "UnregisterClassW", BOOL, (C.c_wchar_p, HANDLE)),
    ("u", "CreateWindowExW", HANDLE, (DWORD, C.c_wchar_p, C.c_wchar_p, DWORD, C.c_int, C.c_int,
                                      C.c_int, C.c_int, HANDLE, HANDLE, HANDLE, C.c_void_p)),
    ("u", "DestroyWindow", BOOL, (HANDLE,)),
    ("u", "DefWindowProcW", LPARAM, (HANDLE, UINT, WPARAM, LPARAM)),        # LRESULT, 64-bit
    ("u", "IsWindowVisible", BOOL, (HANDLE,)),
    # message loop
    ("u", "GetMessageW", BOOL, (C.POINTER(MSG), HANDLE, UINT, UINT)),
    ("u", "PeekMessageW", BOOL, (C.POINTER(MSG), HANDLE, UINT, UINT, UINT)),
    ("u", "TranslateMessage", BOOL, (C.POINTER(MSG),)),
    ("u", "DispatchMessageW", LPARAM, (C.POINTER(MSG),)),
    ("u", "PostMessageW", BOOL, (HANDLE, UINT, WPARAM, LPARAM)),           # the only cross-thread call
    ("u", "PostThreadMessageW", BOOL, (DWORD, UINT, WPARAM, LPARAM)),     # close() fallback (WM_QUIT)
    ("u", "PostQuitMessage", None, (C.c_int,)),
    ("u", "MsgWaitForMultipleObjectsEx", DWORD, (DWORD, C.c_void_p, DWORD, DWORD, DWORD)),
    ("u", "SetTimer", UINT_PTR, (HANDLE, UINT_PTR, UINT, C.c_void_p)),
    ("u", "KillTimer", BOOL, (HANDLE, UINT_PTR)),
    # presentation
    ("u", "UpdateLayeredWindow", BOOL, (HANDLE, HANDLE, C.POINTER(POINT), C.POINTER(SIZE), HANDLE,
                                        C.POINTER(POINT), DWORD, C.POINTER(BLENDFUNCTION), DWORD)),
    ("u", "ShowWindow", BOOL, (HANDLE, C.c_int)),
    ("u", "SetWindowPos", BOOL, (HANDLE, HANDLE, C.c_int, C.c_int, C.c_int, C.c_int, UINT)),
    # monitors + DPI
    ("u", "MonitorFromPoint", HANDLE, (POINT, DWORD)),                     # POINT by value
    ("u", "GetMonitorInfoW", BOOL, (HANDLE, C.POINTER(MONITORINFO))),
    ("u", "SetThreadDpiAwarenessContext", DPI_CONTEXT, (DPI_CONTEXT,)),
    ("u", "GetThreadDpiAwarenessContext", DPI_CONTEXT, ()),
    ("u", "GetAwarenessFromDpiAwarenessContext", C.c_int, (DPI_CONTEXT,)),
    ("u", "GetGuiResources", DWORD, (HANDLE, DWORD)),
    # GDI
    ("g", "CreateCompatibleDC", HANDLE, (HANDLE,)),
    ("g", "DeleteDC", BOOL, (HANDLE,)),
    ("g", "CreateDIBSection", HANDLE, (HANDLE, C.POINTER(BITMAPINFO), UINT,
                                       C.POINTER(C.c_void_p), HANDLE, DWORD)),
    ("g", "SelectObject", HANDLE, (HANDLE, HANDLE)),
    ("g", "DeleteObject", BOOL, (HANDLE,)),
    ("g", "GdiFlush", BOOL, ()),
    # process / thread
    ("k", "GetModuleHandleW", HANDLE, (C.c_wchar_p,)),
    ("k", "GetCurrentThreadId", DWORD, ()),
    ("k", "GetCurrentProcess", HANDLE, ()),
    ("k", "GetCurrentThread", HANDLE, ()),
    ("k", "SetThreadPriority", BOOL, (HANDLE, C.c_int)),                    # P13
    ("d", "DwmFlush", LONG, ()),                                             # HRESULT
    ("s", "GetDpiForMonitor", LONG, (HANDLE, C.c_int, C.POINTER(UINT), C.POINTER(UINT))),
    ("sh", "SHQueryUserNotificationState", LONG, (C.POINTER(C.c_int),)),
)
DLLS = (("u", "user32"), ("g", "gdi32"), ("k", "kernel32"), ("d", "dwmapi"), ("s", "shcore"),
        ("sh", "shell32"))
STRUCTURE_SIZES_X64 = {POINT: 8, SIZE: 8, RECT: 16, MONITORINFO: 40, BLENDFUNCTION: 4,
                       BITMAPINFOHEADER: 40, BITMAPINFO: 44, WNDCLASSEXW: 80, MSG: 48}


class OverlayApi:
    """Win32 declarations only; constructing it resolves exports and calls nothing."""

    def __init__(self):
        if sys.platform != "win32":
            raise OverlayError("the floating knob needs Windows")
        for attribute, name in DLLS:
            setattr(self, attribute, C.WinDLL(name, use_last_error=True))
        for attribute, name, result, args in DECLARATIONS:
            function = getattr(getattr(self, attribute), name)
            function.restype, function.argtypes = result, args

    @staticmethod
    def last_error():
        return C.get_last_error()


# -------------------------------------------------- Win32: window procedure
# One module-level thunk for the class, never freed: Windows may still call it for
# a message racing DestroyWindow, and a freed ctypes thunk is an access violation.
_WINDOW_HANDLERS = {}        # hwnd -> backend._on_message (overlay thread only)
_DEF_WINDOW_PROC = None      # DefWindowProcW from a private user32 (LRESULT restype)
_CALLBACK_FAILURES = {"count": 0, "logged_at": None}


def _note_callback_failure():
    try:
        _CALLBACK_FAILURES["count"] += 1
        now = time.monotonic()
        last = _CALLBACK_FAILURES["logged_at"]
        if last is None or now - last >= LOG_INTERVAL_SECONDS:
            _CALLBACK_FAILURES["logged_at"] = now
            _LOGGER.warning("overlay window procedure failed (%d so far)", _CALLBACK_FAILURES["count"],
                            exc_info=True)
    except BaseException:
        pass


def _window_procedure(hwnd, message, wparam, lparam):
    """The class WNDPROC. Nothing may escape into user32: any exception falls back
    to DefWindowProcW, and a failing DefWindowProcW returns 0."""
    try:
        handler = _WINDOW_HANDLERS.get(hwnd)
        if handler is not None:
            result = handler(message, wparam, lparam)
            if result is not None:
                return int(result)
    except BaseException:
        _note_callback_failure()
    try:
        default = _DEF_WINDOW_PROC
        return default(hwnd, message, wparam, lparam) if default is not None else 0
    except BaseException:
        return 0


_WNDPROC_THUNK = WNDPROC(_window_procedure)
_KEPT_ALIVE = (_WNDPROC_THUNK,)   # the class keeps pointing at it for the process lifetime


# ---------------------------------------------------------------- helpers
def ease_out_cubic(u):
    u = min(1.0, max(0.0, u))
    return 1.0 - (1.0 - u) ** 3


def ease_in_cubic(u):
    u = min(1.0, max(0.0, u))
    return u ** 3


def _initial_lcd_px(ring_logical_px):
    """``lcd_px`` before start() publishes the real one: the 96 DPI value,
    round(240 * knob_face.scale_for(96, ring_logical_px)), without importing knob_face."""
    return round(LCD_DESIGN_PX * ring_logical_px / (2 * DESIGN_RING_OUTER))


def _face_support(face_factory):
    """(face_factory, to_bgra, scale_for) from control_center.knob_face, the single
    source of the face, the premultiplication and the DPI scale; ``face_factory``
    None means knob_face.KnobFace.

    knob_face is imported here, at start(), so this module stays importable (ui.py
    and standalone.py import it) when knob_face cannot be; start() then disables
    the overlay with the real cause in ``last_error`` and the log.
    """
    try:
        from . import knob_face
    except Exception as exc:
        raise OverlayError(f"control_center.knob_face is unavailable: {exc!r}") from exc
    if face_factory is None:
        face_factory = knob_face.KnobFace
    return face_factory, knob_face.premultiplied_bgra, knob_face.scale_for


def _alive_support():
    """(AliveFace, glow_scale_for, ring_key) from knob_face, or None when it cannot be imported
    (the v5 path then keeps working; a knob with ``alive`` is drawn with it)."""
    try:
        from . import knob_face
        return knob_face.AliveFace, knob_face.glow_scale_for, knob_face.ring_key
    except Exception:
        return None


def _default_lights(now_ms):
    """A fresh ``AliveLights`` engine (reset at ``now_ms``): the Python twin of the knob's."""
    from .alive_lights import AliveLights
    return AliveLights(now_ms)


def _frozen_ring(ring):
    """An immutable copy of the ring (the Tk side may reuse its lists)."""
    return tuple(colour if isinstance(colour, (tuple, int)) else tuple(colour) for colour in ring)


def _same_scene(a, b):
    if a is None or b is None:
        return a is b
    if a.lcd_key != b.lcd_key:
        return False
    if a.lcd_key is None and a.lcd is not b.lcd:
        return False
    return a.ring == b.ring


class _Log:
    """Wraps a logging.Logger-like object (or a callable taking one string).
    ``warn(key, ...)`` is rate-limited per key. Logging never raises."""

    def __init__(self, target=None, interval=LOG_INTERVAL_SECONDS):
        self._target = target if target is not None else _LOGGER
        self._interval = interval
        self._last = {}
        self._skipped = {}
        self._lock = threading.Lock()

    def _emit(self, level, message, exc_info=False):
        try:
            method = getattr(self._target, level, None)
            if callable(method):
                method(message, exc_info=exc_info) if exc_info else method(message)
            elif callable(self._target):
                self._target(message)
        except Exception:
            pass

    def info(self, message):
        self._emit("info", message)

    def error(self, message, exc_info=False):
        self._emit("error", message, exc_info)

    def warn(self, key, message):
        now = time.monotonic()
        with self._lock:
            last = self._last.get(key)
            if last is not None and now - last < self._interval:
                self._skipped[key] = self._skipped.get(key, 0) + 1
                return
            skipped = self._skipped.pop(key, 0)
            self._last[key] = now
        self._emit("warning", f"{message} (+{skipped} similar)" if skipped else message)


# ============================================================ state machine
class SlideMachine:
    """hidden -> in -> shown -> out -> hidden, platform-neutral.

    ``visible(now)`` is the eased visible fraction v (0 = hidden, 1 = shown).
    Slide-in is ease-out cubic over SLIDE_IN_SECONDS; slide-out is ease-in cubic
    over SLIDE_OUT_SECONDS. A reversal keeps v continuous: with these two curves
    the linear parameter of the new phase is exactly ``1 - u`` of the old one.
    A slide-in from hidden starts *pending* (armed, v = 0) until ``launch(now)``,
    so the first frame can be presented while the window is still hidden.
    Every touch sets ``deadline = now + seconds`` (FLOATING_KNOB.md section 4),
    where ``now`` is the time of the touch() call; the newest touch wins, even
    over a longer peek.
    """

    def __init__(self, in_seconds=SLIDE_IN_SECONDS, out_seconds=SLIDE_OUT_SECONDS):
        self.in_seconds = float(in_seconds)
        self.out_seconds = float(out_seconds)
        self.state = HIDDEN
        self.deadline = None
        self.suppressed = False
        self._u0 = 0.0
        self._t0 = None

    @property
    def pending(self):
        """True while a slide-in from hidden is armed but not launched."""
        return self.state == IN and self._t0 is None

    @property
    def animating(self):
        return self.state in (IN, OUT) and self._t0 is not None

    def progress(self, now):
        """Linear progress u (0..1) of the current slide."""
        if self._t0 is None:
            return self._u0
        span = self.in_seconds if self.state == IN else self.out_seconds
        if span <= 0:
            return 1.0
        u = self._u0 + (now - self._t0) / span
        return 1.0 if u >= 1.0 - TIME_EPSILON else max(0.0, u)

    def visible(self, now):
        if self.state == SHOWN:
            return 1.0
        if self.state == IN:
            return 0.0 if self._t0 is None else ease_out_cubic(self.progress(now))
        if self.state == OUT:
            return 1.0 - ease_in_cubic(self.progress(now))
        return 0.0

    def touch(self, now, deadline):
        """Apply a touch whose visibility deadline is ``deadline``.

        Returns ARM (hidden -> in, pending), REVERSE (out -> in from the current
        progress), EXTEND (in/shown: deadline only), or None (ignored while suppressed).
        """
        if self.suppressed or deadline is None:
            return None
        self.deadline = deadline
        if self.state == HIDDEN:
            self.state, self._u0, self._t0 = IN, 0.0, None
            return ARM
        if self.state == OUT:
            u = self.progress(now)
            self.state, self._u0, self._t0 = IN, 1.0 - u, now
            return REVERSE
        return EXTEND

    def launch(self, now):
        """Start the armed slide-in clock (after the hidden present and the show)."""
        if self.pending:
            self._t0 = now
            return True
        return False

    def step(self, now):
        """Advance to ``now``; returns the states entered, in order."""
        entered = []
        if self.state == IN and self._t0 is not None and self.progress(now) >= 1.0:
            self.state, self._u0, self._t0 = SHOWN, 0.0, None
            entered.append(SHOWN)
        if self.state == SHOWN and (self.deadline is None or now >= self.deadline - TIME_EPSILON):
            self._begin_out(now, 0.0)
            entered.append(OUT)
        if self.state == OUT and self.progress(now) >= 1.0:
            self._to_hidden()
            entered.append(HIDDEN)
        return entered

    def set_suppressed(self, on, now):
        """Hold or release suppression. Turning it on slides out at once
        (returns OUT), or cancels a pending slide-in (returns HIDDEN)."""
        self.suppressed = bool(on)
        if not self.suppressed:
            return None
        if self.pending:
            self._to_hidden()
            return HIDDEN
        if self.state == IN:
            self._begin_out(now, 1.0 - self.progress(now))
            return OUT
        if self.state == SHOWN:
            self._begin_out(now, 0.0)
            return OUT
        return None

    def hide_now(self):
        """Jump to hidden with no animation (suspend, end of session, stop)."""
        was_visible = self.state != HIDDEN
        self._to_hidden()
        return was_visible

    def next_wait(self, now):
        """0.0 while animating, seconds until the deadline while shown, None when idle."""
        if self.state == HIDDEN or self.pending:
            return None
        if self.state in (IN, OUT):
            return ANIMATING
        if self.deadline is None:
            return ANIMATING
        return max(0.0, self.deadline - now)

    def _begin_out(self, now, u0):
        self.state, self._u0, self._t0 = OUT, u0, now

    def _to_hidden(self):
        self.state, self._u0, self._t0 = HIDDEN, 0.0, None
        self.deadline = None


# ================================================================ hand-off
class Mailbox:
    """Tk thread -> overlay thread hand-off. Every field is guarded by ``lock``.

    Each message kind has a pending-post flag, so at most one WM_APP message of a
    kind is queued at a time (a 25 ms tick plus touch pulses can never flood the
    10,000-message queue). The overlay thread clears the flag when it takes the
    data; the Tk side clears it when its PostMessageW fails.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.scene = None
        self.scene_seq = 0
        self.scene_time = None
        self.frame_posted = False
        self.touch_deadline = None
        self.touch_time = None
        self.touch_posted = False
        self.reasons = frozenset()
        self.suppress_posted = False
        self.closed = False
        # Desktop v7 (alive): the Tk side's mode and newest frame, the latched values, and the
        # serial reader's fast-path inputs (kept in arrival order, each with its QPC stamp).
        self.alive_on = False
        self.alive_msg = None          # (frame, claimed, local_max, t) newest wins
        self.alive_seq = 0
        self.latched = {}              # name -> (value, t)
        self.alive_posted = False
        self.inputs = deque(maxlen=INPUT_QUEUE_LIMIT)
        self.inputs_dropped = 0
        self.input_posted = False

    def take_alive(self):
        """(alive_on, newest frame message or None, latched {name: (value, t)})."""
        with self.lock:
            message, latched = self.alive_msg, self.latched
            self.alive_msg, self.latched = None, {}
            self.alive_posted = False
            return self.alive_on, message, latched

    def take_inputs(self):
        """Every fast-path input posted since the last take, oldest first."""
        with self.lock:
            inputs = list(self.inputs)
            self.inputs.clear()
            self.input_posted = False
            return inputs

    def take_scene(self):
        with self.lock:
            scene, seq, when = self.scene, self.scene_seq, self.scene_time
            self.scene = None
            self.frame_posted = False
            return scene, seq, when

    def take_touch(self):
        with self.lock:
            deadline, when = self.touch_deadline, self.touch_time
            self.touch_deadline = self.touch_time = None
            self.touch_posted = False
            return deadline, when

    def take_reasons(self):
        with self.lock:
            self.suppress_posted = False
            return self.reasons

    def current_reasons(self):
        """The Tk side's reasons now, without taking the pending post."""
        with self.lock:
            return self.reasons


class _Status:
    """Values the overlay thread publishes for the Tk thread (plain attributes;
    each is written by one thread only, and single reads are atomic)."""

    def __init__(self, lcd_px):
        self.machine_state = HIDDEN
        self.wants_frames = False
        self.disabled = False
        self.closed = False
        self.last_error = None
        self.rect = None
        self.dpi = None
        self.scale = None
        self.window_px = None
        self.face_px = None           # the knob face's own (W, H); the window adds the inset
        self.inset_px = None          # face offset from the window box's left edge (section 9.11)
        self.lcd_px = lcd_px
        self.awareness = None
        self.notification_state = None
        self.fullscreen_blocked = False
        self.suppressed = ()
        self.frames_presented = 0
        self.frames_composed = 0
        self.ulw_failures = 0
        self.compose_failures = 0
        self.face_builds = 0
        self.compose_ms = None
        self.lcd_resizes = 0          # LCDs not at lcd_px that _compose had to fit (section 2)
        self.face_lcd_resizes = None  # the current face's own count (KnobFace.lcd_resizes)
        self.scenes_submitted = 0     # Tk thread
        self.post_failures = 0        # Tk thread
        # Desktop v7 (alive).
        self.alive = False            # the engine draws the ring (a knob with `alive`)
        self.looks_build_ms = None
        self.engine_renders = 0       # AliveLights renders (visible frames, hidden messages, catch-up)
        self.hidden_renders = 0       # renders for a posted message while hidden or armed (K2 M27)
        self.catchup_renders = 0
        self.frames_skipped = 0       # visible frames whose quantised face did not change (AR-22)
        self.alive_failures = 0
        self.inputs_posted = 0        # any thread
        self.reduced_motion = False
        self.frame_stats = None       # KnobFrameStats (overlay thread writes, metrics() reads under its lock)
        self.pacing = None


# ============================================================ desktop v7 (alive)
def qpc_ms(t_seconds):
    """P12: an AliveLights ``now``: int(t_qpc_seconds * 1000) as uint32."""
    return int(t_seconds * 1000.0) & UINT32


BLANK_E = ((0.0, 0.0, 0.0),) * 60


class AliveMirror:
    """The floating knob's ``AliveLights`` on the overlay thread (K2 10.3 items 1-2; K4 11.2).
    Pure: no Win32, no slide. Times are QPC seconds (floats); the engine gets P12's uint32 ms.

    Messages are applied in stamp order and never move time backwards: a message stamped before
    the last render is applied at the last render's time. ``message(t, apply)`` is the hidden
    path (one render per posted message after the catch-up); ``apply_*`` queue into the engine
    and ``render(t)`` is the visible path (one render per vblank). ``catch_up(t)`` is K2 M27:
    render at last + 50 ms, + 100 ms, ... below ``t`` with the previous frame and no new input,
    at most 60 steps; a gap over 3 s first renders once at t - 3 s."""

    def __init__(self, lights_factory=_default_lights, start=0.0):
        self.lights = lights_factory(qpc_ms(start))
        self.frame = None
        self.claimed = False
        self.local_max = None
        self.local = None                 # (control id, position) from the fast path
        self.last = float(start)          # QPC seconds of the last render
        self.ring = BLANK_E
        self.renders = self.catchups = 0

    # ------------------------------------------------------------- inputs
    def _stamp(self, t):
        return self.last if t is None or t < self.last else float(t)

    def apply_frame(self, frame, claimed, local_max, t):
        """A Tk frame: the claim edge (claim / release at its stamp), then the frame itself."""
        now = qpc_ms(self._stamp(t))
        claimed = bool(claimed)
        if claimed and not self.claimed:
            self.lights.claim(now)
        elif self.claimed and not claimed:
            self.lights.release(now)
        self.claimed = claimed
        self.frame = frame if isinstance(frame, dict) else None
        self.local_max = local_max if type(local_max) is int and local_max >= 0 else None

    def _frame_id(self):
        return self.frame.get("id") if isinstance(self.frame, dict) else None

    def apply_input(self, kind, value, control_id, t):
        """A fast-path input (K2 6.2): a position of the frame's control is the local cursor and,
        with a delta, a detent; a limit of that control a bound; a press (physical slot)."""
        now = qpc_ms(self._stamp(t))
        if kind == "position":
            try:
                position, delta = value
            except (TypeError, ValueError):
                return
            if type(position) is int:
                self.local = (control_id, position)
            if self.claimed and control_id is not None and control_id == self._frame_id() \
                    and type(delta) is int and delta:
                self.lights.detent(now, delta)
        elif kind == "limit":
            if self.claimed and control_id is not None and control_id == self._frame_id() and value in (-1, 1):
                self.lights.limit(now, value)
        elif kind == "press":
            if self.claimed and type(value) is int and 0 <= value < 4:
                self.lights.press(now, value)

    def apply_latched(self, name, value, t):
        """Clock, progress, reduced motion and tuning come straight from the runtime (K2 10.3 item 1)."""
        now = qpc_ms(self._stamp(t))
        lights = self.lights
        if name == "clock":
            lights.set_clock(now, value)
        elif name == "progress":
            try:
                position, duration = value
            except (TypeError, ValueError):
                return
            lights.set_progress(now, position, duration)
        elif name == "reduced_motion":
            lights.set_reduced_motion(now, bool(value))
        elif name == "tuning":
            try:
                pink, vol_full = value
            except (TypeError, ValueError):
                return
            lights.set_tuning(now, pink if type(pink) is int else 0, bool(vol_full))

    # ------------------------------------------------------------- renders
    def _local(self):
        local = self.local
        if local is None or self.frame is None or local[0] != self._frame_id() or self.local_max is None:
            return None, None
        return local[1], self.local_max

    def _render(self, t):
        position, maximum = self._local()
        frame = self.frame if self.claimed else None
        ring, _buttons = self.lights.render(qpc_ms(t), frame, position, maximum)
        self.ring = tuple(ring)
        self.last = t
        self.renders += 1
        return self.ring

    def catch_up(self, t):
        """K2 M27 (see the class docstring). Returns the number of catch-up renders."""
        t = float(t)
        gap = t - self.last
        if gap <= CATCHUP_STEP_SECONDS:
            return 0
        steps = 0
        if gap > CATCHUP_SPAN_SECONDS:
            self._render(t - CATCHUP_SPAN_SECONDS)
            steps += 1
        start = self.last
        k = 1
        while steps < CATCHUP_MAX_STEPS:
            at = start + CATCHUP_STEP_SECONDS * k
            if at >= t - 1e-9:
                break
            self._render(at)
            steps += 1
            k += 1
        self.catchups += steps
        return steps

    def render(self, t):
        """One render at ``t`` (never before the last one): the visible path's per-vblank render."""
        return self._render(self._stamp(t))

    def message(self, t, apply=None):
        """The hidden path: catch up to the message's stamp, apply it, render once at the stamp."""
        t = self._stamp(t)
        steps = self.catch_up(t)
        if apply is not None:
            apply()
        self._render(t)
        return steps


class KnobPacer:
    """P2, P4 and P5 for the floating knob's loop, in QPC seconds (K4 5.1; the rules of the
    stage's ``frames.Pacer``). ``target`` samples at the predicted display time; ``frame_done``
    keeps the 0.5 s work window and the 240 <-> 120 lock with hysteresis."""

    WINDOW_S = 0.5
    LOCK_AT, UNLOCK_BELOW = 0.8, 0.6

    def __init__(self):
        self.cadence = 1
        self.switches = 0
        self.work = deque()               # (t, work seconds)
        self.below_since = None
        self.last_return = None
        self.late_wakes = 0

    def work_p95(self, now):
        cut = now - self.WINDOW_S
        while self.work and self.work[0][0] < cut:
            self.work.popleft()
        if not self.work:
            return 0.0
        values = sorted(w for _t, w in self.work)
        return values[min(len(values) - 1, max(0, math.ceil(0.95 * len(values)) - 1))]

    def target(self, now, vblank, period):
        """P2: t_target = vblank + n P >= now + the work p95 of the last 0.5 s; under the P5 lock
        every second vblank and at least 2 P ahead."""
        if not period or period <= 0:
            return now
        need = now + self.work_p95(now)
        step = period * self.cadence
        n = math.ceil((need - vblank) / step) if need > vblank else 0
        t = vblank + n * step
        if self.cadence == 2 and t - now < 2 * period:
            t += step
        return t

    def judge_wake(self, t_return, period):
        """P4: a wait that returns at least 0.5 P after the previous return is pacing."""
        ok = self.last_return is None or (t_return - self.last_return) >= 0.5 * period
        if not ok:
            self.late_wakes += 1
        self.last_return = t_return
        return ok

    def frame_done(self, t_wake, work, period):
        """Record a frame's work and apply P5's hysteresis; returns the next cadence (1 or 2)."""
        self.work.append((t_wake, float(work)))
        p95 = self.work_p95(t_wake)
        if self.cadence == 1 and p95 > self.LOCK_AT * period:
            self.cadence, self.below_since = 2, None
            self.switches += 1
        elif self.cadence == 2:
            if p95 < self.UNLOCK_BELOW * period:
                if self.below_since is None:
                    self.below_since = t_wake
                elif t_wake - self.below_since >= self.WINDOW_S:
                    self.cadence, self.below_since = 1, None
                    self.switches += 1
            else:
                self.below_since = None
        return self.cadence


def _quantile(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, max(0, math.ceil(p * len(values)) - 1))] if values else None


def _summary_ms(values):
    values = [float(v) for v in values if v is not None]
    if not values:
        return None
    ordered = sorted(values)
    return {"n": len(ordered), "p50": round(ordered[(len(ordered) - 1) // 2], 3),
            "p95": round(_quantile(ordered, 0.95), 3), "p99": round(_quantile(ordered, 0.99), 3),
            "max": round(ordered[-1], 3)}


class KnobFrameStats:
    """K4 6.2's FrameStats for ``frames.knob``: per frame (t_wake, t_target, work, present,
    changed, cadence, presented), one record per episode (``slide`` while sliding, ``ring`` for a
    visible spell) with ``last``, ``worst`` and ``totals`` per kind. Methods: ``present_cadence``
    for the slide (a present on a new vblank is a displayed frame) and ``ring_changed`` for the
    ring (only changed frames count; late = presented after its t_target vblank, AR-22).
    The overlay thread records; ``metrics()`` (any thread) returns copies under the lock."""

    def __init__(self):
        self.lock = threading.Lock()
        self.kinds = {}
        self._frames = {"slide": [], "ring": []}
        self._start = {"slide": None, "ring": None}

    def begin(self, kind, t, *, rate_hz=None, rm=False, boosted=False):
        if self._start.get(kind) is None:
            self._start[kind] = (t, rate_hz, bool(rm), bool(boosted))
            self._frames[kind] = []

    def frame(self, kind, record):
        if self._start.get(kind) is None:
            return
        frames = self._frames[kind]
        if len(frames) < FRAME_RECORDS:
            frames.append(record)

    def end(self, kind, t, period, *, cadence_switches=0):
        started = self._start.get(kind)
        if started is None:
            return None
        self._start[kind] = None
        frames, self._frames[kind] = self._frames[kind], []
        t0, rate_hz, rm, boosted = started
        episode = self._episode(kind, frames, t0, t, period, rate_hz, rm, boosted, cadence_switches)
        with self.lock:
            entry = self.kinds.setdefault(kind, {"last": None, "worst": None,
                                                 "totals": {"episodes": 0, "frames": 0, "late_changed": 0}})
            entry["last"] = episode
            if episode["frames"] and (entry["worst"] is None or self._badness(episode) > self._badness(entry["worst"])):
                entry["worst"] = episode
            totals = entry["totals"]
            totals["episodes"] += 1
            totals["frames"] += episode["frames"]
            totals["late_changed"] += episode.get("late_changed") or 0
        return episode

    @staticmethod
    def _badness(episode):
        return (episode.get("late_2P") or 0, episode.get("late_changed") or 0,
                (episode.get("interval_ms") or {}).get("max") or 0.0)

    @staticmethod
    def _episode(kind, frames, t0, t1, period, rate_hz, rm, boosted, switches):
        period = period or DEFAULT_PERIOD_SECONDS
        duration = max(1e-9, t1 - t0)
        presented = [f for f in frames if f.get("presented")]
        if kind == "ring":
            shown = [f for f in presented if f.get("changed")]
            method = "ring_changed"
        else:
            shown = presented
            method = "present_cadence"
        vblanks = sorted({round((f["t_present"] - t0) / period) for f in shown})
        times = [f["t_present"] for f in shown]
        intervals = [(b - a) * 1000.0 for a, b in zip(times, times[1:])]
        late = [f for f in shown if f["t_present"] > f["t_target"] + 1e-4]
        late_2p = [f for f in shown if f["t_present"] > f["t_target"] + period + 1e-4]
        episode = {"kind": kind, "method": method, "frames": len(vblanks), "vblanks": round(duration / period),
                   "fps": round(len(vblanks) / duration, 1), "interval_ms": _summary_ms(intervals),
                   "missed": sum(1 for i in intervals if i > 1.5 * period * 1000.0),
                   "double_missed": sum(1 for i in intervals if i > 2.5 * period * 1000.0),
                   "work_ms": _summary_ms(f.get("work_ms") for f in frames),
                   "present_ms": _summary_ms(f.get("present_ms") for f in presented),
                   "cadence_switches": switches, "rate_hz": rate_hz, "boosted": boosted, "rm": rm,
                   "duration_ms": round(duration * 1000.0, 1)}
        if kind == "ring":
            episode.update(changed=len(shown), late_changed=len(late), late_2P=len(late_2p),
                           on_target=round(1.0 - len(late) / len(shown), 4) if shown else None)
        return episode

    def metrics(self):
        with self.lock:
            import copy
            return copy.deepcopy(self.kinds)


# ================================================================== engine
class OverlayEngine:
    """Overlay-thread logic, platform-neutral. Everything here runs on the
    overlay thread: ``on_event`` from the window procedure, ``advance`` from the
    loop. ``advance`` returns ANIMATING (0.0: pace to vsync and step again), a
    wait in seconds, or None (block until a message)."""

    def __init__(self, *, backend, mailbox, status, face_factory, to_bgra, scale_for, clock,
                 ring_logical_px=RING_LOGICAL_PX, inset_logical_px=INSET_LOGICAL_PX, log=None,
                 alive_support=None, lights_factory=None):
        self.backend = backend
        self.mail = mailbox
        self.status = status
        self.face_factory = face_factory
        self.to_bgra = to_bgra
        self.scale_for = scale_for
        self.clock = clock
        self.ring_logical_px = ring_logical_px
        self.inset_logical_px = inset_logical_px
        self.log = log if isinstance(log, _Log) else _Log(log)
        # Desktop v7 (alive): (AliveFace, glow_scale_for, ring_key) and the engine factory.
        self.alive_support = alive_support
        self.lights_factory = lights_factory or _default_lights
        self.alive_on = False
        self.mirror = None
        self.pacer = KnobPacer()
        self.stats = KnobFrameStats()
        status.frame_stats = self.stats
        self._alive_pending = self._input_pending = False
        self._leaving_hidden = True
        self._alive_composed = None   # (face, ring key, LCD identity) drawn in the current frame
        self._alive_params = None     # (src_x, alpha) of the last successful alive present
        self._timing = None           # (vblank, period, rate) of the last frame
        self._reduced = False
        self._boosted = False
        self.machine = SlideMachine()
        self.face = None
        self._face_key = None
        self.geometry = None          # (x, y, W, H) physical px of the window box (window_rect)
        self.inset = 0                # px from the box's left edge to the face (section 9.11)
        self.created = False
        self.stopped = False
        self._latest = None           # newest scene received
        self._latest_time = None
        self._composed_scene = None
        self._composed_face = None
        self._frame = None            # premultiplied BGRA bytes of the current face size
        self._presented = None        # (frame, v) last presented successfully
        self._window_visible = False
        self._geometry_dirty = False
        self._frame_pending = self._touch_pending = False
        self._suppress_pending = self._stop_pending = False
        self._arm_until = None
        self._arm_touch_time = None
        self._retry_at = None
        self._applied_reasons = None  # suppression reasons the machine last applied

    # ---------------------------------------------------------- lifecycle
    def initialize(self):
        """Before the window exists: geometry, face and any suppression set before start."""
        self._layout(initial=True)
        self._apply_suppression(self.clock())
        self._publish()
        return self.geometry

    def mark_created(self):
        self.created = True

    def finish(self):
        """The loop has ended (after close() or abnormally); nothing is shown any more."""
        self.stopped = True
        self.machine.hide_now()
        self._window_visible = False
        self.status.machine_state = HIDDEN
        self.status.wants_frames = False

    @property
    def vsync_alive(self):
        """True while the loop paces on the compositor clock (a visible alive knob, K4 5.1 P3)."""
        return self.alive_on and self.mirror is not None and self.machine.state != HIDDEN

    def frame_period(self):
        timing = self._timing
        return timing[1] if timing else DEFAULT_PERIOD_SECONDS

    # ------------------------------------------------------------- events
    def on_event(self, kind):
        """Window-procedure side: record, never compose. Hide requests act at once."""
        if kind == EV_FRAME:
            self._frame_pending = True
        elif kind == EV_TOUCH:
            self._touch_pending = True
        elif kind == EV_SUPPRESS:
            self._suppress_pending = True
        elif kind == EV_DIRTY:
            self._geometry_dirty = True
        elif kind == EV_STOP:
            self._stop_pending = True
        elif kind == EV_HIDE:
            self.hide_now()
        elif kind == EV_INPUT:
            self._input_pending = True
        elif kind == EV_ALIVE:
            self._alive_pending = True

    def hide_now(self):
        self.machine.hide_now()
        self._hide_window()
        self._end_visible(self.clock())
        self._publish()

    # ----------------------------------------------------------- stepping
    def advance(self):
        if self.stopped:
            return None
        now = self.clock()
        if self._stop_pending or self.mail.closed:
            self._stop()
            return None
        # Posted WM_APP+4, or a change whose post failed (a lost release would
        # otherwise hold the machine suppressed while the Tk side accepts touches).
        if self._suppress_pending or self.mail.current_reasons() != self._applied_reasons:
            self._suppress_pending = False
            self._apply_suppression(now)
        if self._touch_pending:
            self._touch_pending = False
            self._apply_touch(now)
        if self._frame_pending:
            self._frame_pending = False
            self._take_scene()
        self._alive_messages(now)
        if self._drawing_alive():
            return self._advance_alive(now)
        machine = self.machine
        if machine.pending:
            if not self._fresh_scene() and now < self._arm_until:
                self._publish()
                return self._arm_until - now
            self._launch()
            now = self.clock()
        entered = machine.step(now)
        if HIDDEN in entered:
            self._hide_window()
        elif machine.state != HIDDEN:
            if self._geometry_dirty:
                self._layout()
            self._render(now)
        if machine.state == HIDDEN and self._geometry_dirty:
            # A DPI or work-area change while hidden (FLOATING_KNOB.md section 9.17): lay out now,
            # so the published rect (which Settings keeps clear of) and lcd_px are current before
            # the next slide-in, which lays out again anyway. Nothing is shown or presented.
            self._layout()
        self._publish()
        wait = machine.next_wait(now)
        if self._retry_at is not None and machine.state != HIDDEN:
            retry = max(0.0, self._retry_at - now)
            wait = retry if wait is None else min(wait, retry)
        return wait

    # ------------------------------------------------------------ touches
    def _apply_touch(self, now):
        deadline, touch_time = self.mail.take_touch()
        machine = self.machine
        if deadline is None or machine.suppressed:
            return
        if machine.state in (HIDDEN, OUT) and not self._slide_in_allowed():
            return
        result = machine.touch(now, deadline)
        if result == ARM:
            self._arm_until = now + FIRST_FRAME_WAIT_SECONDS
            self._arm_touch_time = touch_time if touch_time is not None else now
        elif result == REVERSE:
            self._layout()                 # geometry is recomputed on every slide-in
            self._show_window()            # and HWND_TOPMOST re-asserted

    def _slide_in_allowed(self):
        """SHQueryUserNotificationState, checked at each slide-in: no slide-in
        over D3D full-screen (3) or presentation mode (4)."""
        try:
            state = self.backend.notification_state()
        except Exception as exc:
            self.log.warn("quns", f"overlay: notification state unavailable: {exc!r}")
            state = None
        self.status.notification_state = state
        blocked = state in FULLSCREEN_NOTIFICATION_STATES
        if blocked and not self.status.fullscreen_blocked:
            self.log.info(f"overlay: slide-in suppressed (notification state {state})")
        self.status.fullscreen_blocked = blocked
        return not blocked

    def _apply_suppression(self, now):
        reasons = self.mail.take_reasons()
        self._applied_reasons = reasons
        self.status.suppressed = tuple(sorted(reasons))
        if self.machine.set_suppressed(bool(reasons), now) == HIDDEN:
            self._hide_window()

    # ------------------------------------------------------------- scenes
    def _take_scene(self):
        scene, _seq, when = self.mail.take_scene()
        if scene is not None:
            self._latest, self._latest_time = scene, when

    def _fresh_scene(self):
        self._take_scene()      # newest wins, even if its WM_APP+1 is still queued
        return (self._latest_time is not None and self._arm_touch_time is not None
                and self._latest_time >= self._arm_touch_time - FRESH_SCENE_SLACK_SECONDS)

    def _launch(self):
        """Slide-in from hidden: geometry, first frame presented while hidden, then show."""
        self._layout()
        self._compose_if_needed()
        self._present(0.0, self.clock())
        self._show_window()
        self.machine.launch(self.clock())

    # --------------------------------------------------- desktop v7: alive
    def _drawing_alive(self):
        return self.alive_on and self.mirror is not None and self.alive_support is not None

    def _set_alive(self, on, now):
        """The Tk side switched the knob's model: a fresh engine (reset: offline + reveal) for a
        knob with ``alive``, or back to the v5 scenes. The face is rebuilt on this thread (while
        hidden when possible: the geometry is marked dirty)."""
        on = bool(on) and self.alive_support is not None
        if on == self.alive_on:
            return
        self.alive_on = on
        self.status.alive = on
        self._end_visible(now)
        try:
            self.mirror = AliveMirror(self.lights_factory, now) if on else None
        except Exception as exc:
            self.mirror, self.alive_on, self.status.alive = None, False, False
            self.status.alive_failures += 1
            self.status.last_error = f"alive: {exc!r}"
            self.log.warn("alive", f"overlay: the LED engine could not start: {exc!r}")
        self._leaving_hidden = True
        self._alive_composed = self._alive_params = None
        self._frame = None
        self._presented = None
        self._geometry_dirty = True
        if self.machine.state != HIDDEN:
            self._layout()

    def _apply_reduced(self, on):
        on = bool(on)
        if on == self._reduced:
            return
        self._reduced = on
        self.status.reduced_motion = on
        # K4 11.6 / S5-16: no slide; a 200 ms constant-alpha fade in place.
        self.machine.in_seconds = REDUCED_FADE_SECONDS if on else SLIDE_IN_SECONDS
        self.machine.out_seconds = REDUCED_FADE_SECONDS if on else SLIDE_OUT_SECONDS

    def _alive_messages(self, now):
        """Take the Tk side's alive state and the fast-path inputs. While hidden each frame or input
        is one engine render at its own stamp (after the M27 catch-up); while visible they only
        queue, for the next vblank's render.

        "Hidden" here is every state before the first visible render (``_leaving_hidden``): hidden,
        and also armed (pending) during the slide-in's wait for a fresh scene. A summoning input
        (``post_input`` posts the input, then its touch, so one pump carries both and the touch
        ARMs first) and a Tk frame posted during the arm wait therefore render at their own
        stamps too, and the launch's catch-up only spans the time since (K4 11.2 / K2 M27: the new
        frame and inputs go only into the final render at their ``now``, never into catch-up
        steps seconds in the past)."""
        on, message, latched = self.mail.take_alive()
        inputs = self.mail.take_inputs()
        self._alive_pending = self._input_pending = False
        if on != self.alive_on:
            self._set_alive(on, now)
        if "reduced_motion" in latched:
            self._apply_reduced(latched["reduced_motion"][0])
        mirror = self.mirror
        if not self.alive_on or mirror is None:
            return
        events = [(t if t is not None else now, 0, ("latched", name, value)) for name, (value, t) in latched.items()]
        if message is not None:
            frame, claimed, local_max, t = message
            events.append((t if t is not None else now, 1, ("frame", frame, claimed, local_max)))
        for kind, value, control_id, t in inputs:
            events.append((t if t is not None else now, 2, ("input", kind, value, control_id)))
        if not events:
            return
        events.sort(key=lambda event: (event[0], event[1]))
        machine = self.machine
        hidden = self._leaving_hidden or machine.state == HIDDEN or machine.pending
        status = self.status
        for t, _order, item in events:
            def apply(item=item, t=t):
                if item[0] == "latched":
                    mirror.apply_latched(item[1], item[2], t)
                elif item[0] == "frame":
                    mirror.apply_frame(item[1], item[2], item[3], t)
                else:
                    mirror.apply_input(item[1], item[2], item[3], t)
            try:
                if hidden and item[0] != "latched":
                    status.catchup_renders += mirror.message(t, apply)     # K2 M27: one render per message
                    status.hidden_renders += 1
                    status.engine_renders += 1
                else:
                    apply()
            except Exception as exc:
                status.alive_failures += 1
                status.last_error = f"alive: {exc!r}"
                self.log.warn("alive", f"overlay: an engine message failed: {exc!r}")

    def _frame_timing(self):
        """(vblank, period, rate_hz) from the backend (DwmGetCompositionTimingInfo), else the last
        one or 60 Hz starting now (a fake backend)."""
        timing = None
        getter = getattr(self.backend, "vblank_timing", None)
        if callable(getter):
            try:
                timing = getter()
            except Exception as exc:
                self.log.warn("timing", f"overlay: composition timing unavailable: {exc!r}")
        if timing and timing[1] and timing[1] > 0:
            self._timing = tuple(timing)
        elif self._timing is None:
            self._timing = (self.clock(), DEFAULT_PERIOD_SECONDS, None)
        return self._timing

    def _advance_alive(self, now):
        machine = self.machine
        if machine.pending:
            if not self._fresh_scene() and now < self._arm_until:
                self._publish()
                return self._arm_until - now
            self._launch_alive()
        if machine.state == HIDDEN:
            if self._geometry_dirty:
                self._layout()
            self._publish()
            return None
        t_wake = self.clock()
        vblank, period, _rate = self._frame_timing()
        self.pacer.judge_wake(t_wake, period)            # P4: counted as late_wakes in the pacing metrics
        t_target = self.pacer.target(t_wake, vblank, period)
        entered = machine.step(t_target)                 # P2: the slide is sampled at the display time too
        if HIDDEN in entered:
            self._hide_window()
            self._end_visible(t_target)
            self._publish()
            return None
        if self._geometry_dirty:
            self._layout()
        self._alive_frame(t_wake, t_target, period)
        self._publish()
        return ANIMATING

    def _launch_alive(self):
        """Slide-in from hidden: geometry, the M27 catch-up, the first frame (at its display time)
        presented while hidden, then show and start the slide clock."""
        self._layout()
        t_wake = self.clock()
        vblank, period, rate = self._frame_timing()
        t_target = self.pacer.target(t_wake, vblank, period)
        self._begin_visible(t_target, rate)
        self._alive_frame(t_wake, t_target, period, launching=True)
        self._show_window()
        self.machine.launch(self.clock())

    def _begin_visible(self, t, rate):
        stats = self.stats
        stats.begin("ring", t, rate_hz=rate, rm=self._reduced, boosted=True)
        stats.begin("slide", t, rate_hz=rate, rm=self._reduced, boosted=True)
        if not self._boosted:
            self._boost(True)

    def _end_visible(self, t):
        """The knob is hidden again: close the episodes, stop boosting, re-arm the M27 catch-up."""
        period = self.frame_period()
        self.stats.end("slide", t, period, cadence_switches=self.pacer.switches)
        self.stats.end("ring", t, period, cadence_switches=self.pacer.switches)
        if self._boosted:
            self._boost(False)
        self._leaving_hidden = True

    def _boost(self, on):
        """P11: DCompositionBoostCompositorClock for the visible spell (harmless without DRR)."""
        self._boosted = bool(on)
        boost = getattr(self.backend, "boost", None)
        if callable(boost):
            try:
                boost(bool(on))
            except Exception:
                pass

    def _alive_frame(self, t_wake, t_target, period, launching=False):
        """One vblank: render the engine at t_target (after the catch-up when leaving hidden),
        compose when the quantised face changed, present when the face or the slide changed."""
        mirror = self.mirror
        status = self.status
        if self._leaving_hidden:
            status.catchup_renders += mirror.catch_up(t_target)
            self._leaving_hidden = False
        try:
            ring = mirror.render(t_target)
            status.engine_renders += 1
        except Exception as exc:
            ring = mirror.ring
            status.alive_failures += 1
            self.log.warn("alive", f"overlay: an engine render failed: {exc!r}")
        machine = self.machine
        if machine.state in (IN, OUT) and not launching:
            self.stats.begin("slide", t_target, rate_hz=None, rm=self._reduced, boosted=self._boosted)
        changed = self._compose_alive(ring)
        v = 0.0 if launching else machine.visible(t_target)
        t_presented = None
        presented = self._present_alive(v, changed, t_wake)
        work_end = self.clock()
        if presented:
            t_presented = work_end
        if not changed:
            status.frames_skipped += 1
        self.pacer.frame_done(t_wake, work_end - t_wake, period)
        record = {"t_wake": t_wake, "t_target": t_target, "work_ms": (work_end - t_wake) * 1000.0,
                  "present_ms": self._present_ms, "changed": changed, "cadence": self.pacer.cadence,
                  "presented": bool(presented), "t_present": t_presented or work_end}
        self.stats.frame("ring", record)
        self.stats.frame("slide", record)
        if machine.state == SHOWN:
            self.stats.end("slide", t_target, period, cadence_switches=self.pacer.switches)

    _present_ms = None

    def _compose_alive(self, ring):
        """C2 (K4 11.4): draw the face into the DIB (or a new canvas for a backend without one)
        only when the frame key (ring key + LCD identity + face) changed. True when drawn."""
        face = self.face
        if face is None or self.geometry is None:
            return False
        scene = self._latest
        lcd = scene.lcd if scene is not None else None
        lcd_key = (scene.lcd_key if scene is not None and scene.lcd_key is not None else id(lcd))
        try:
            looks = self.alive_support[2](ring)
        except Exception as exc:
            self.status.alive_failures += 1
            self.log.warn("alive-key", f"overlay: ring key failed: {exc!r}")
            return False
        key = (id(face), looks, lcd_key)
        if self._alive_composed == key and self._frame is not None:
            return False
        try:
            started = time.perf_counter()
            width, height = self.geometry[2:]
            if lcd is not None and lcd.mode != "RGBA":
                lcd = lcd.convert("RGBA")
            canvas_of = getattr(self.backend, "canvas", None)
            canvas = canvas_of() if callable(canvas_of) else None
            if canvas is not None:
                face.compose_into(canvas, (self.inset, 0), lcd, looks)
                self._frame = canvas
            else:
                from PIL import Image
                canvas = Image.new("RGBX", (width, height), (0, 0, 0, 0))
                face.compose_into(canvas, (self.inset, 0), lcd, looks)
                self._frame = canvas.tobytes()
            self.status.face_lcd_resizes = getattr(face, "lcd_resizes", None)
        except Exception as exc:
            self.status.compose_failures += 1
            self.status.last_error = f"compose: {exc!r}"
            self.log.warn("compose", f"overlay: compose failed: {exc!r}")
            self._alive_composed = key            # do not retry the same frame
            return False
        self._alive_composed = key
        self._alive_params = None
        self.status.frames_composed += 1
        self.status.compose_ms = round((time.perf_counter() - started) * 1000, 3)
        return True

    def _present_alive(self, v, changed, now):
        """ULW with ptSrc.x and the constant alpha of the slide (reduced motion: a fade in place)."""
        if self._frame is None or self.geometry is None:
            return False
        x, y, width, height = self.geometry
        v = min(1.0, max(0.0, v))
        src_x = 0 if self._reduced else min(width, max(0, round(width * (1.0 - v))))
        alpha = min(255, max(0, round(255 * v)))
        params = (src_x, alpha)
        if not changed and params == self._alive_params:
            self._present_ms = None
            return False
        started = time.perf_counter()
        try:
            if isinstance(self._frame, (bytes, bytearray)):
                ok = bool(self.backend.present(bytes(self._frame), (width, height), (x, y), src_x, alpha))
            else:
                ok = bool(self.backend.present_canvas((width, height), (x, y), src_x, alpha))
        except Exception as exc:
            self.status.last_error = f"present: {exc!r}"
            ok = False
        self._present_ms = (time.perf_counter() - started) * 1000.0
        if ok:
            self.status.frames_presented += 1
            self._alive_params = params
            self._retry_at = None
        else:
            self.status.ulw_failures += 1
            self._alive_params = None
            self._retry_at = now + PRESENT_RETRY_SECONDS
            self.log.warn("present", f"overlay: UpdateLayeredWindow failed ({self.status.ulw_failures} so far)")
        return ok

    # ------------------------------------------------------------ geometry
    def _layout(self, initial=False):
        """Primary monitor rcWork + effective DPI -> window rect (window_rect: the box
        starts at the work area's left edge, the face ``inset`` px into it); rebuild the
        face (sprites) when the physical scale changes and the DIB when the size does."""
        try:
            work, dpi = self.backend.geometry()
            dpi = int(dpi) if dpi else 96
            alive = self._drawing_alive()
            key = (dpi, self.ring_logical_px) if not alive else (dpi, self.ring_logical_px, "alive")
            if self.face is None or key != self._face_key:
                scale = self.scale_for(dpi, self.ring_logical_px)
                if alive:
                    face_class, glow_scale_for, _ring_key = self.alive_support
                    self.face = face_class(scale, glow_scale_for(dpi, self.ring_logical_px))
                    self.status.looks_build_ms = round(float(getattr(self.face, "looks_build_ms", 0.0) or 0.0), 1)
                else:
                    self.face = self.face_factory(scale)
                self._face_key = key
                self._frame = None
                self._alive_composed = None
                self.status.face_builds += 1
                self.status.scale = scale
            x, y, width, height, inset = window_rect(work, dpi, self.face.size, self.inset_logical_px)
        except Exception as exc:
            if initial or self.face is None:
                raise
            self.log.warn("layout", f"overlay: geometry update failed: {exc!r}")
            self._geometry_dirty = False
            return
        resized = self.geometry is None or self.geometry[2:] != (width, height)
        moved = self.geometry is not None and self.geometry[:2] != (x, y)
        self.geometry = (x, y, width, height)
        if inset != self.inset:
            self._frame = None            # the face moves inside the box: compose again
        self.inset = inset
        self._geometry_dirty = False
        if resized and self.created:
            self.backend.resize((width, height))
            self._alive_composed = None   # a new DIB holds no frame
        if resized or moved:
            self._presented = None
            self._alive_params = None
        status = self.status
        status.dpi, status.window_px, status.rect = dpi, (width, height), self.geometry
        status.face_px, status.inset_px = tuple(int(v) for v in self.face.size), inset
        status.lcd_px = int(self.face.lcd_px)

    # ------------------------------------------------------ compose + present
    def _compose_if_needed(self):
        if self.face is None:
            return
        scene = self._latest
        if (self._frame is not None and self._composed_face is self.face
                and _same_scene(scene, self._composed_scene)):
            return
        self._compose(scene)

    def _compose(self, scene):
        face = self.face
        try:
            started = time.perf_counter()
            lcd = scene.lcd if scene is not None else None
            ring = scene.ring if scene is not None else BLANK_RING
            if lcd is not None:
                side = int(face.lcd_px)
                if lcd.mode != "RGBA":
                    lcd = lcd.convert("RGBA")
                if lcd.size != (side, side):
                    # Only for the tick after a DPI change, before the Tk side renders at the new lcd_px.
                    # Counted (metrics lcd_resizes) so a steady 240 -> lcd_px upscale stays visible.
                    self.status.lcd_resizes += 1
                    self.log.warn("lcd-resize", f"overlay: LCD {lcd.size[0]}x{lcd.size[1]} fitted to "
                                                f"lcd_px {side} (expected only right after a DPI change)")
                    from PIL import Image
                    lcd = lcd.resize((side, side), Image.Resampling.LANCZOS)
            image = face.compose(lcd, ring)
            self.status.face_lcd_resizes = getattr(face, "lcd_resizes", None)
            width, height = self.geometry[2:]
            inset = self.inset
            if image.size != (width - inset, height):
                raise OverlayError(f"face composed {image.size}, window is {(width, height)} with inset {inset}")
            if inset:
                # The face sits ``inset`` px into the window box (section 9.11); the strip at the
                # screen edge stays transparent. A plain paste copies the pixels (no blending).
                from PIL import Image
                box = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                box.paste(image, (inset, 0))
                image = box
            frame = self.to_bgra(image)
            if not isinstance(frame, bytes):
                frame = bytes(frame)
            if len(frame) != width * height * 4:
                raise OverlayError(f"frame of {len(frame)} bytes, window is {(width, height)}")
        except Exception as exc:
            self.status.compose_failures += 1
            self.status.last_error = f"compose: {exc!r}"
            self.log.warn("compose", f"overlay: compose failed: {exc!r}")
            self._composed_scene, self._composed_face = scene, face   # do not retry the same scene
            return
        self._frame = frame
        self._composed_scene, self._composed_face = scene, face
        self.status.frames_composed += 1
        self.status.compose_ms = round((time.perf_counter() - started) * 1000, 3)

    def _render(self, now):
        self._compose_if_needed()
        v = self.machine.visible(now)
        presented = self._presented
        if presented is not None and presented[0] is self._frame and presented[1] == v:
            return
        self._present(v, now)

    def _present(self, v, now):
        if self._frame is None or self.geometry is None:
            return False
        x, y, width, height = self.geometry
        v = min(1.0, max(0.0, v))
        src_x = min(width, max(0, round(width * (1.0 - v))))
        alpha = min(255, max(0, round(255 * v)))
        try:
            ok = bool(self.backend.present(self._frame, (width, height), (x, y), src_x, alpha))
        except Exception as exc:
            self.status.last_error = f"present: {exc!r}"
            ok = False
        if ok:
            self.status.frames_presented += 1
            self._presented = (self._frame, v)
            self._retry_at = None
        else:
            self.status.ulw_failures += 1
            self._presented = None
            self._retry_at = now + PRESENT_RETRY_SECONDS
            self.log.warn("present", f"overlay: UpdateLayeredWindow failed ({self.status.ulw_failures} so far)")
        return ok

    def _show_window(self):
        try:
            ok = bool(self.backend.show())
        except Exception as exc:
            self.status.last_error = f"show: {exc!r}"
            ok = False
        if not ok:
            self.log.warn("show", "overlay: showing the window failed")
        self._window_visible = True

    def _hide_window(self):
        if self._window_visible:
            try:
                self.backend.hide()
            except Exception as exc:
                self.status.last_error = f"hide: {exc!r}"
                self.log.warn("hide", f"overlay: hiding the window failed: {exc!r}")
            self._window_visible = False
        self._presented = None
        self._alive_params = None
        self._retry_at = None

    def _stop(self):
        """Posted WM_APP+3 (or the closed flag): strict cleanup on this thread;
        DestroyWindow's WM_DESTROY posts the WM_QUIT that ends the loop."""
        self.stopped = True
        self.machine.hide_now()
        self._window_visible = False
        self.status.machine_state = HIDDEN
        self.status.wants_frames = False
        self.backend.destroy_window()

    def _publish(self):
        status = self.status
        state = self.machine.state
        status.machine_state = state
        with self.mail.lock:   # keep the Tk side's anticipation while its touch is still queued
            status.wants_frames = state != HIDDEN or self.mail.touch_posted


# ================================================= Win32: the frame clock (v7)
class _UnsignedRatio(C.Structure):
    _pack_ = 1
    _fields_ = [("num", C.c_uint32), ("den", C.c_uint32)]


class DWM_TIMING_INFO(C.Structure):            # dwmapi.h is #pragma pack(1)
    _pack_ = 1
    _fields_ = [("cbSize", C.c_uint32), ("rateRefresh", _UnsignedRatio), ("qpcRefreshPeriod", C.c_uint64),
                ("rateCompose", _UnsignedRatio), ("qpcVBlank", C.c_uint64), ("cRefresh", C.c_uint64),
                ("cDXRefresh", C.c_uint32), ("qpcCompose", C.c_uint64), ("cFrame", C.c_uint64),
                ("cDXPresent", C.c_uint32), ("cRefreshFrame", C.c_uint64), ("cFrameSubmitted", C.c_uint64),
                ("cDXPresentSubmitted", C.c_uint32), ("cFrameConfirmed", C.c_uint64),
                ("cDXPresentConfirmed", C.c_uint32), ("cRefreshConfirmed", C.c_uint64),
                ("cDXRefreshConfirmed", C.c_uint32), ("cFramesLate", C.c_uint64), ("cFramesOutstanding", C.c_uint32),
                ("cFrameDisplayed", C.c_uint64), ("qpcFrameDisplayed", C.c_uint64),
                ("cRefreshFrameDisplayed", C.c_uint64), ("cFrameComplete", C.c_uint64),
                ("qpcFrameComplete", C.c_uint64), ("cFramePending", C.c_uint64), ("qpcFramePending", C.c_uint64),
                ("cFramesDisplayed", C.c_uint64), ("cFramesComplete", C.c_uint64), ("cFramesPending", C.c_uint64),
                ("cFramesAvailable", C.c_uint64), ("cFramesDropped", C.c_uint64), ("cFramesMissed", C.c_uint64),
                ("cRefreshNextDisplayed", C.c_uint64), ("cRefreshNextPresented", C.c_uint64),
                ("cRefreshesDisplayed", C.c_uint64), ("cRefreshesPresented", C.c_uint64),
                ("cRefreshStarted", C.c_uint64), ("cPixelsReceived", C.c_uint64), ("cPixelsDrawn", C.c_uint64),
                ("cBuffersEmpty", C.c_uint64)]


WAIT_TIMEOUT = 0x102
CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS = 0x2, 0x1F0003


class FrameClock:
    """The overlay thread's frame clock (K4 5.1 P3 with G1-2): ``timing()`` from
    DwmGetCompositionTimingInfo in ``time.perf_counter`` seconds, ``wait(period, ticks)`` on
    DCompositionWaitForCompositorClock (Windows 11), where any return other than a tick or a
    timeout means "no clock" (0xC01E0006 while the display sleeps) and waits one period on a
    high-resolution waitable timer; without the export, DwmFlush, then the timer. Every call
    here releases the GIL (WinDLL). Resolved on first use, on the overlay thread; nothing is
    declared in ``DECLARATIONS`` (the v5 declaration tests are unchanged)."""

    def __init__(self):
        k = C.WinDLL("kernel32", use_last_error=True)
        u = C.WinDLL("user32", use_last_error=True)
        dwm = C.WinDLL("dwmapi")
        self._timing = dwm.DwmGetCompositionTimingInfo
        self._timing.restype, self._timing.argtypes = LONG, (HANDLE, C.POINTER(DWM_TIMING_INFO))
        self._flush = dwm.DwmFlush
        self._flush.restype, self._flush.argtypes = LONG, ()
        self._clock_wait = self._boost = None
        try:
            dcomp = C.WinDLL("dcomp")
            wait = dcomp.DCompositionWaitForCompositorClock
            wait.restype, wait.argtypes = DWORD, (UINT, C.POINTER(HANDLE), DWORD)
            self._clock_wait = wait
            boost = dcomp.DCompositionBoostCompositorClock
            boost.restype, boost.argtypes = LONG, (BOOL,)
            self._boost = boost
        except (OSError, AttributeError):
            pass
        self._create_timer = k.CreateWaitableTimerExW
        self._create_timer.restype = HANDLE
        self._create_timer.argtypes = (C.c_void_p, C.c_wchar_p, DWORD, DWORD)
        self._set_timer = k.SetWaitableTimer
        self._set_timer.restype = BOOL
        self._set_timer.argtypes = (HANDLE, C.POINTER(C.c_int64), C.c_long, C.c_void_p, C.c_void_p, BOOL)
        self._close = k.CloseHandle
        self._close.restype, self._close.argtypes = BOOL, (HANDLE,)
        self._msg_wait = u.MsgWaitForMultipleObjectsEx
        self._msg_wait.restype = DWORD
        self._msg_wait.argtypes = (DWORD, C.POINTER(HANDLE), DWORD, DWORD, DWORD)
        frequency, counter = C.c_int64(), C.c_int64()
        k.QueryPerformanceFrequency(C.byref(frequency))
        self.qpf = int(frequency.value) or 10_000_000
        before = time.perf_counter()
        k.QueryPerformanceCounter(C.byref(counter))
        after = time.perf_counter()
        self._offset = (before + after) / 2 - counter.value / self.qpf   # QPC ticks -> perf_counter seconds
        self._timer = None
        self._info = DWM_TIMING_INFO()
        self.counts = {"tick": 0, "timeout": 0, "no_clock": 0, "flush": 0, "timer": 0}
        self.has_clock = self._clock_wait is not None

    def timing(self):
        """(vblank, period, rate_hz) in perf_counter seconds, or None."""
        info = self._info
        info.cbSize = C.sizeof(DWM_TIMING_INFO)
        if self._timing(None, C.byref(info)) != 0 or not info.qpcRefreshPeriod:
            return None
        rate = info.rateRefresh.num / info.rateRefresh.den if info.rateRefresh.den else None
        return info.qpcVBlank / self.qpf + self._offset, info.qpcRefreshPeriod / self.qpf, rate

    def _timer_wait(self, seconds):
        if self._timer is None:
            self._timer = (self._create_timer(None, None, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS)
                           or self._create_timer(None, None, 0, TIMER_ALL_ACCESS))
        timer = self._timer
        milliseconds = max(1, int(math.ceil(seconds * 1000)))
        if not timer:
            self._msg_wait(0, None, milliseconds, QS_ALLINPUT, MWMO_INPUTAVAILABLE)
            return
        due = C.c_int64(-max(1, int(seconds * 1e7)))
        self._set_timer(timer, C.byref(due), 0, None, None, False)
        handles = (HANDLE * 1)(timer)
        self._msg_wait(1, handles, milliseconds * 4, QS_ALLINPUT, MWMO_INPUTAVAILABLE)
        self.counts["timer"] += 1

    def wait(self, period, ticks=1):
        """Wait ``ticks`` compositor frames (2 under the P5 lock). Returns the last kind."""
        kind = "tick"
        for _ in range(max(1, int(ticks))):
            if self._clock_wait is not None:
                code = self._clock_wait(0, None, max(1, int(period * 4000))) & 0xFFFFFFFF
                if code == 0:
                    self.counts["tick"] += 1
                    kind = "tick"
                    continue
                if code == WAIT_TIMEOUT:
                    self.counts["timeout"] += 1
                    kind = "timeout"
                    continue
                self.counts["no_clock"] += 1          # G1-2: never loop on the call unguarded
                self._timer_wait(period)
                kind = "no_clock"
                continue
            started = time.perf_counter()
            if self._flush() == 0 and time.perf_counter() - started >= 0.5 * period:
                self.counts["flush"] += 1
                kind = "flush"
                continue
            self._timer_wait(period)
            kind = "timer"
        return kind

    def boost(self, on):
        if self._boost is not None:
            self._boost(1 if on else 0)

    def close(self):
        if self._timer:
            self._close(self._timer)
            self._timer = None


# =========================================================== Win32 backend
class Win32Backend:
    """The overlay's only Win32 user. Except ``post``/``post_quit`` (PostMessageW /
    PostThreadMessageW, any thread) and ``gui_resources`` (a process counter
    query), every method runs on the overlay thread that called ``create``."""

    def __init__(self, *, api=None, log=None):
        global _DEF_WINDOW_PROC
        self.api = api or OverlayApi()
        self.log = log if isinstance(log, _Log) else _Log(log)
        if isinstance(self.api, OverlayApi):
            # Without it the thunk would answer WM_NCCREATE with 0 and creation would fail.
            _DEF_WINDOW_PROC = self.api.u.DefWindowProcW
        self.hwnd = None
        self.hdc = None
        self.dib = None
        self.bits = None
        self.old_bitmap = None
        self.size = None              # (W, H) of the content; the DIB is 2W x H
        self.hinstance = None
        self.registered = False
        self.thread_id = None
        self.awareness = None
        self._handler = None
        self._uploaded = None
        self._timer = False
        self._fast_flushes = 0
        self._msg = MSG()
        # Desktop v7 (alive): the frame clock and a PIL view of the DIB's left half.
        self._frame_clock = None
        self._frame_clock_failed = False
        self._canvas = None
        self._canvas_dib = None
        self.priority = None

    # -------------------------------------------------------------- start
    def prepare_thread(self):
        """Per-thread PMv2 DPI awareness (verified) and the thread's message queue."""
        u = self.api.u
        previous = u.SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        self.awareness = u.GetAwarenessFromDpiAwarenessContext(u.GetThreadDpiAwarenessContext())
        if not previous or self.awareness != DPI_AWARENESS_PER_MONITOR_AWARE:
            self.log.warn("dpi", f"overlay: thread DPI awareness is {self.awareness}, not per-monitor "
                                 f"(set returned {previous!r}); the knob may be misplaced or blurry")
        self.thread_id = self.api.k.GetCurrentThreadId()
        u.PeekMessageW(C.byref(self._msg), None, WM_USER, WM_USER, PM_NOREMOVE)
        try:   # P13: the frame thread above our own workers and other processes' normal threads
            self.priority = bool(self.api.k.SetThreadPriority(self.api.k.GetCurrentThread(),
                                                              THREAD_PRIORITY_ABOVE_NORMAL))
        except Exception:
            self.priority = False
        return self.awareness

    def create(self, handler, position, size):
        """Register the class (1410 tolerated), create the hidden window, the memory DC and the DIB."""
        api = self.api
        self.hinstance = api.k.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = C.sizeof(WNDCLASSEXW)
        wc.style = 0
        wc.lpfnWndProc = _WNDPROC_THUNK
        wc.hInstance = self.hinstance
        wc.lpszClassName = CLASS_NAME
        if not api.u.RegisterClassExW(C.byref(wc)):
            error = api.last_error()
            if error != ERROR_CLASS_ALREADY_EXISTS:
                raise OverlayError(f"RegisterClassExW failed (error {error})")
        self.registered = True
        x, y = position
        width, height = size
        hwnd = api.u.CreateWindowExW(OVERLAY_EX_STYLE, CLASS_NAME, WINDOW_TITLE, OVERLAY_STYLE,
                                     int(x), int(y), int(width), int(height), None, None, self.hinstance, None)
        if not hwnd:
            raise OverlayError(f"CreateWindowExW failed (error {api.last_error()})")
        self.hwnd = hwnd
        self._handler = handler
        _WINDOW_HANDLERS[hwnd] = self._on_message
        hdc = api.g.CreateCompatibleDC(None)
        if not hdc:
            raise OverlayError(f"CreateCompatibleDC failed (error {api.last_error()})")
        self.hdc = hdc
        self.resize(size)

    def resize(self, size):
        """(Re)create the 2W x H top-down 32-bit DIB; at most one DIB is ever alive."""
        width, height = (int(v) for v in size)
        if self.dib and self.size == (width, height):
            return
        if width <= 0 or height <= 0:
            raise OverlayError(f"invalid overlay size {(width, height)}")
        self._release_dib()
        api = self.api
        bmi = BITMAPINFO()
        header = bmi.bmiHeader
        header.biSize = C.sizeof(BITMAPINFOHEADER)
        header.biWidth = 2 * width
        header.biHeight = -height          # top-down
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = BI_RGB
        bits = C.c_void_p()
        dib = api.g.CreateDIBSection(self.hdc, C.byref(bmi), DIB_RGB_COLORS, C.byref(bits), None, 0)
        if not dib or not bits.value:
            if dib:
                api.g.DeleteObject(dib)
            raise OverlayError(f"CreateDIBSection failed (error {api.last_error()})")
        self.dib, self.bits = dib, bits.value
        C.memset(self.bits, 0, 2 * width * 4 * height)      # the right half stays transparent
        old = api.g.SelectObject(self.hdc, dib)
        if not old:
            raise OverlayError(f"SelectObject(DIB) failed (error {api.last_error()})")
        self.old_bitmap = old
        self.size = (width, height)
        self._uploaded = None

    # ---------------------------------------------------------- messages
    def _on_message(self, message, wparam, lparam):
        """Window procedure body (overlay thread). None -> DefWindowProcW."""
        handler = self._handler
        event = POSTED_EVENTS.get(message)
        if event is not None:
            if handler is not None:
                handler(event)
            return 0
        if message == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE
        if message == WM_NCHITTEST:
            return HTTRANSPARENT
        if message == WM_TIMER:
            if wparam == TIMER_ID:
                if handler is not None:
                    handler(EV_TIMER)
                return 0
            return None
        if message in (WM_DISPLAYCHANGE, WM_DPICHANGED, WM_DWMCOMPOSITIONCHANGED):
            if handler is not None:
                handler(EV_DIRTY)
            return 0                       # WM_DPICHANGED: the suggested rect is ignored
        if message == WM_SETTINGCHANGE:
            if wparam == SPI_SETWORKAREA and handler is not None:
                handler(EV_DIRTY)
            return None
        if message == WM_POWERBROADCAST:
            if handler is not None:
                if wparam == PBT_APMSUSPEND:
                    handler(EV_HIDE)
                elif wparam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
                    handler(EV_DIRTY)
            return 1
        if message == WM_ENDSESSION:
            if wparam and handler is not None:
                handler(EV_HIDE)
            return 0
        if message == WM_CLOSE:
            return 0                       # teardown only through WM_APP+3 -> DestroyWindow
        if message == WM_DESTROY:
            self.api.u.PostQuitMessage(0)
            return 0
        return None

    def post(self, code):
        """Any thread: PostMessageW only (never SendMessage)."""
        hwnd = self.hwnd
        if not hwnd:
            return False
        return bool(self.api.u.PostMessageW(hwnd, code, 0, 0))

    def post_quit(self):
        """Any thread: WM_QUIT to the overlay thread (close() fallback when WM_APP+3 cannot be posted)."""
        thread_id = self.thread_id
        if not thread_id:
            return False
        return bool(self.api.u.PostThreadMessageW(thread_id, WM_QUIT, 0, 0))

    def pump(self):
        """Dispatch every queued message without blocking; False once WM_QUIT arrives."""
        u, msg = self.api.u, self._msg
        while u.PeekMessageW(C.byref(msg), None, 0, 0, PM_REMOVE):
            if msg.message == WM_QUIT:
                return False
            u.TranslateMessage(C.byref(msg))
            u.DispatchMessageW(C.byref(msg))
        return True

    def wait(self, timeout):
        """Block in GetMessageW for one message; a timeout arms the WM_TIMER that wakes it."""
        u, msg = self.api.u, self._msg
        if timeout is None:
            self._kill_timer()
        else:
            milliseconds = max(USER_TIMER_MINIMUM_MS, min(0x7FFFFFFF, int(math.ceil(timeout * 1000 - 1e-6))))
            if self.hwnd and u.SetTimer(self.hwnd, TIMER_ID, milliseconds, None):
                self._timer = True
            else:
                self.log.warn("timer", f"overlay: SetTimer failed (error {self.api.last_error()})")
                u.MsgWaitForMultipleObjectsEx(0, None, milliseconds, QS_ALLINPUT, MWMO_INPUTAVAILABLE)
                return True
        result = u.GetMessageW(C.byref(msg), None, 0, 0)
        if result == 0:
            return False                   # WM_QUIT
        if result == -1:
            self.log.warn("getmessage", f"overlay: GetMessageW failed (error {self.api.last_error()})")
            return False
        u.TranslateMessage(C.byref(msg))
        u.DispatchMessageW(C.byref(msg))
        return True

    def pace(self):
        """Vsync pacing with DwmFlush; MsgWaitForMultipleObjectsEx(8 ms) when it fails
        (display off, no composition) or stops waiting, so the loop never busy-spins."""
        self._kill_timer()
        started = time.perf_counter()
        result = self.api.d.DwmFlush()
        if result == 0 and time.perf_counter() - started >= FAST_FLUSH_SECONDS:
            self._fast_flushes = 0
            return
        if result == 0:
            self._fast_flushes += 1
            if self._fast_flushes < 2:
                return
        self.api.u.MsgWaitForMultipleObjectsEx(0, None, PACE_FALLBACK_MS, QS_ALLINPUT, MWMO_INPUTAVAILABLE)

    # -------------------------------------------------------- presentation
    def present(self, frame, size, position, src_x, alpha):
        """Copy a W x H premultiplied BGRA frame into the DIB's left half (only when
        it changed) and UpdateLayeredWindow with ptSrc.x = src_x and the constant alpha."""
        if not self.hwnd or not self.dib:
            return False
        width, height = (int(v) for v in size)
        if (width, height) != self.size:
            self.log.warn("present-size", f"overlay: frame size {(width, height)} != DIB {self.size}")
            return False
        api = self.api
        if frame is not self._uploaded:
            if not isinstance(frame, bytes) or len(frame) != width * height * 4:
                self.log.warn("present-bytes", "overlay: frame has the wrong length; not uploaded")
                return False
            api.g.GdiFlush()
            row, stride = width * 4, width * 8
            source = C.c_char_p(frame)                # no copy; keeps ``frame`` referenced
            base = C.cast(source, C.c_void_p).value
            bits = self.bits
            for y in range(height):
                C.memmove(bits + y * stride, base + y * row, row)
            self._uploaded = frame
        destination = POINT(int(position[0]), int(position[1]))
        extent = SIZE(width, height)
        source_origin = POINT(min(width, max(0, int(src_x))), 0)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, min(255, max(0, int(alpha))), AC_SRC_ALPHA)
        ok = api.u.UpdateLayeredWindow(self.hwnd, None, C.byref(destination), C.byref(extent), self.hdc,
                                       C.byref(source_origin), 0, C.byref(blend), ULW_ALPHA)
        if not ok:
            self.log.warn("ulw", f"overlay: UpdateLayeredWindow failed (error {api.last_error()})")
            return False
        return True

    # --------------------------------------------- desktop v7: frame clock
    def _clock(self):
        if self._frame_clock is None and not self._frame_clock_failed:
            try:
                self._frame_clock = FrameClock()
            except Exception as exc:
                self._frame_clock_failed = True
                self.log.warn("frameclock", f"overlay: no frame clock ({exc!r}); pacing with DwmFlush")
        return self._frame_clock

    def vblank_timing(self):
        """(vblank, period, rate_hz) in perf_counter seconds (DwmGetCompositionTimingInfo), or None."""
        clock = self._clock()
        return clock.timing() if clock is not None else None

    def wait_vblank(self, period, ticks=1):
        """P3: wait for the compositor clock (``ticks`` frames: 2 under the P5 lock); G1-2's timer
        when there is no clock; the v5 pace() when the frame clock is unavailable."""
        self._kill_timer()
        clock = self._clock()
        if clock is None:
            self.pace()
            return "pace"
        return clock.wait(period, ticks)

    def boost(self, on):
        clock = self._clock()
        if clock is not None:
            clock.boost(on)

    def clock_counts(self):
        clock = self._frame_clock
        return dict(clock.counts, compositor_clock=clock.has_clock) if clock is not None else None

    def canvas(self):
        """A PIL 'RGBX' image sharing the DIB's left half (row stride 2W x 4 bytes): the alive
        face is composed straight into it (K4 11.4 C2; no copy, no per-frame image). GDI's
        batch is flushed first; the v5 upload cache is invalidated (the DIB changes under it)."""
        if not self.dib or not self.bits or not self.size:
            return None
        width, height = self.size
        if self._canvas is None or self._canvas_dib != self.dib:
            from PIL import Image
            buffer = (C.c_ubyte * (2 * width * 4 * height)).from_address(self.bits)
            image = Image.frombuffer("RGBX", (width, height), buffer, "raw", "RGBX", 2 * width * 4, 1)
            image.readonly = 0
            self._canvas, self._canvas_dib = image, self.dib
        self.api.g.GdiFlush()
        self._uploaded = None
        return self._canvas

    def present_canvas(self, size, position, src_x, alpha):
        """UpdateLayeredWindow of what the canvas holds (ptSrc.x = src_x, the constant alpha)."""
        if not self.hwnd or not self.dib:
            return False
        width, height = (int(v) for v in size)
        if (width, height) != self.size:
            self.log.warn("present-size", f"overlay: frame size {(width, height)} != DIB {self.size}")
            return False
        api = self.api
        destination = POINT(int(position[0]), int(position[1]))
        extent = SIZE(width, height)
        source_origin = POINT(min(width, max(0, int(src_x))), 0)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, min(255, max(0, int(alpha))), AC_SRC_ALPHA)
        ok = api.u.UpdateLayeredWindow(self.hwnd, None, C.byref(destination), C.byref(extent), self.hdc,
                                       C.byref(source_origin), 0, C.byref(blend), ULW_ALPHA)
        if not ok:
            self.log.warn("ulw", f"overlay: UpdateLayeredWindow failed (error {api.last_error()})")
            return False
        return True

    def show(self):
        """Show without activating and re-assert HWND_TOPMOST."""
        if not self.hwnd:
            return False
        u = self.api.u
        if u.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SHOW_FLAGS):
            return True
        self.log.warn("setwindowpos", f"overlay: SetWindowPos failed (error {self.api.last_error()})")
        u.ShowWindow(self.hwnd, SW_SHOWNA)
        return False

    def hide(self):
        if self.hwnd:
            self.api.u.ShowWindow(self.hwnd, SW_HIDE)   # returns the previous visibility, not success
        return True

    def is_visible(self):
        return bool(self.hwnd) and bool(self.api.u.IsWindowVisible(self.hwnd))

    # ------------------------------------------------------------ queries
    def geometry(self):
        u = self.api.u
        monitor = u.MonitorFromPoint(POINT(0, 0), MONITOR_DEFAULTTOPRIMARY)
        info = MONITORINFO()
        info.cbSize = C.sizeof(MONITORINFO)
        if not monitor or not u.GetMonitorInfoW(monitor, C.byref(info)):
            raise OverlayError(f"GetMonitorInfoW failed (error {self.api.last_error()})")
        dpi_x, dpi_y = UINT(), UINT()
        result = self.api.s.GetDpiForMonitor(monitor, MDT_EFFECTIVE_DPI, C.byref(dpi_x), C.byref(dpi_y))
        dpi = dpi_x.value if result == 0 and dpi_x.value else 96
        if result != 0:
            self.log.warn("dpi-monitor", f"overlay: GetDpiForMonitor failed (0x{result & 0xFFFFFFFF:08X}); using 96")
        work = info.rcWork
        return Geometry((work.left, work.top, work.right, work.bottom), dpi)

    def notification_state(self):
        state = C.c_int()
        result = self.api.sh.SHQueryUserNotificationState(C.byref(state))
        return state.value if result == 0 else None

    def gui_resources(self):
        """(GDI objects, USER objects) of this process; a process-wide counter query."""
        api = self.api
        process = api.k.GetCurrentProcess()
        return (int(api.u.GetGuiResources(process, GR_GDIOBJECTS)),
                int(api.u.GetGuiResources(process, GR_USEROBJECTS)))

    # ----------------------------------------------------------- teardown
    def _kill_timer(self):
        if self._timer and self.hwnd:
            if not self.api.u.KillTimer(self.hwnd, TIMER_ID):
                self.log.warn("killtimer", f"overlay: KillTimer failed (error {self.api.last_error()})")
        self._timer = False

    def _release_dib(self):
        api = self.api
        self._canvas = self._canvas_dib = None     # never draw into a freed DIB
        if self.dib:
            api.g.GdiFlush()
            if self.old_bitmap and self.hdc:
                if not api.g.SelectObject(self.hdc, self.old_bitmap):
                    self.log.warn("selectobject", "overlay: restoring the DC bitmap failed")
            self.old_bitmap = None
            if not api.g.DeleteObject(self.dib):
                self.log.warn("deleteobject", "overlay: DeleteObject(DIB) failed")
        # the bits pointer is invalid from here on: never memmove again
        self.dib = self.bits = None
        self.size = None
        self._uploaded = None

    def destroy_window(self):
        """Cleanup steps 1-5, in order: KillTimer, SelectObject(old), DeleteObject(DIB),
        DeleteDC, DestroyWindow (whose WM_DESTROY posts the loop's WM_QUIT). Idempotent."""
        api = self.api
        self._kill_timer()
        self._release_dib()
        if self.hdc:
            if not api.g.DeleteDC(self.hdc):
                self.log.warn("deletedc", "overlay: DeleteDC failed")
            self.hdc = None
        hwnd = self.hwnd
        if hwnd:
            self.hwnd = None               # posts from the Tk side stop here
            if not api.u.DestroyWindow(hwnd):
                self.log.warn("destroywindow", f"overlay: DestroyWindow failed (error {api.last_error()})")
            _WINDOW_HANDLERS.pop(hwnd, None)
        self._handler = None

    def unregister(self):
        """Cleanup step 6, after the loop: UnregisterClassW (the thunk is never freed)."""
        if self.registered:
            if not self.api.u.UnregisterClassW(CLASS_NAME, self.hinstance):
                self.log.warn("unregister", f"overlay: UnregisterClassW failed (error {self.api.last_error()})")
            self.registered = False

    def destroy(self):
        """Full ordered cleanup (safety net for failures and abnormal loop exits). Idempotent."""
        self.destroy_window()
        self.unregister()
        clock, self._frame_clock = self._frame_clock, None
        if clock is not None:
            try:
                clock.close()
            except Exception:
                pass


# ============================================================ Tk-side facade
class KnobOverlay:
    """The floating knob, driven from the Tk thread.

    Every public method may be called from the Tk thread; each one only records
    data under a lock and posts (coalesced) to the ``NanoD-overlay`` thread,
    which does all Win32 work. ``state``, ``wants_frames``, ``lcd_px`` and
    ``rect`` are plain values published by the overlay thread.
    """

    START_TIMEOUT_SECONDS = START_TIMEOUT_SECONDS
    CLOSE_TIMEOUT_SECONDS = CLOSE_TIMEOUT_SECONDS

    def __init__(self, *, face_factory=None, backend=None, clock=time.perf_counter, hide_seconds=HIDE_SECONDS,
                 ring_logical_px=RING_LOGICAL_PX, inset_logical_px=INSET_LOGICAL_PX, log=None,
                 alive_support=None, lights_factory=None):
        # face_factory=None means control_center.knob_face.KnobFace (imported at start()).
        # alive_support=None means knob_face's (AliveFace, glow_scale_for, ring_key) (desktop v7).
        # The clock is QPC seconds (time.perf_counter): the fast path's read stamps and the Tk side's
        # frame stamps share it, and AliveLights gets int(t * 1000) (K4 P12).
        self._face_factory = face_factory
        self._alive_support = alive_support
        self._lights_factory = lights_factory
        self._backend = backend
        self._clock = clock
        self.hide_seconds = float(hide_seconds)
        self.ring_logical_px = ring_logical_px
        self.inset_logical_px = inset_logical_px
        self._log = log if isinstance(log, _Log) else _Log(log)
        self._mail = Mailbox()
        self._status = _Status(lcd_px=_initial_lcd_px(ring_logical_px))
        self._engine = None
        self._thread = None
        self._ready = threading.Event()
        self._running = False

    # ------------------------------------------------------------ properties
    @property
    def state(self):
        status = self._status
        if status.disabled or status.closed:
            return DISABLED
        return status.machine_state

    @property
    def wants_frames(self):
        status = self._status
        return bool(status.wants_frames) and not status.disabled and not status.closed

    @property
    def lcd_px(self):
        return int(self._status.lcd_px)

    @property
    def rect(self):
        return self._status.rect

    @property
    def hwnd(self):
        """The knob window's handle (created by the NanoD-overlay thread), or 0 before it
        exists, after teardown and while the overlay is disabled. Read-only. Other code of this
        process may pass it only to process-wide calls: the carousel sets WDA_EXCLUDEFROMCAPTURE
        on it while it captures its glass (CAROUSEL.md sections 3 and 5). Drawing, showing,
        hiding and destroying stay on the overlay thread. Never raises."""
        if not self._live():
            return 0
        try:
            return int(getattr(self._backend, "hwnd", 0) or 0)
        except (TypeError, ValueError):
            return 0

    # --------------------------------------------------------------- start
    def start(self):
        """Create the overlay thread and its hidden window; waits at most 2 s.
        False (state 'disabled', reason logged) when anything fails."""
        if self._thread is not None or self._engine is not None or self._status.closed:
            return self._running
        try:
            self._prepare()
        except Exception as exc:
            self._disable(f"overlay unavailable: {exc!r}")
            return False
        self._thread = threading.Thread(target=self._run, name=THREAD_NAME, daemon=True)
        self._thread.start()
        if not self._ready.wait(self.START_TIMEOUT_SECONDS):
            with self._mail.lock:
                self._mail.closed = True     # the thread tears down whatever it creates
            self._disable(f"overlay thread did not start within {self.START_TIMEOUT_SECONDS:g} s")
            return False
        if self._status.disabled:
            self._thread.join(self.CLOSE_TIMEOUT_SECONDS)
            return False
        self._running = True
        return True

    def _prepare(self):
        face_factory, to_bgra, scaler = _face_support(self._face_factory)
        alive_support = self._alive_support if self._alive_support is not None else _alive_support()
        if self._backend is None:
            self._backend = Win32Backend(log=self._log)
        self._engine = OverlayEngine(
            backend=self._backend, mailbox=self._mail, status=self._status, face_factory=face_factory,
            to_bgra=to_bgra, scale_for=scaler, clock=self._clock, ring_logical_px=self.ring_logical_px,
            inset_logical_px=self.inset_logical_px, log=self._log, alive_support=alive_support,
            lights_factory=self._lights_factory)

    def _start_inline(self):
        """Test hook: create on the calling thread without a loop thread; drive it
        with ``_iterate()`` and an injected clock. Never used by the application."""
        self._prepare()
        self._create()
        self._running = True

    def _create(self):
        """Thread start steps 1-3: DPI awareness + queue, geometry + face, class + window + DC + DIB."""
        engine, backend = self._engine, self._backend
        self._status.awareness = backend.prepare_thread()
        x, y, width, height = engine.initialize()
        backend.create(engine.on_event, (x, y), (width, height))
        engine.mark_created()

    def _run(self):
        backend, engine = self._backend, self._engine
        try:
            created = False
            try:
                self._create()
                created = True
            except BaseException as exc:
                self._disable(f"overlay window creation failed: {exc!r}")
            finally:
                self._ready.set()            # step 4: the Tk side stops waiting
            if created:
                self._loop()
                with self._mail.lock:
                    closing = self._mail.closed
                if not closing:
                    # WM_QUIT or a GetMessageW error without close(): the window is gone,
                    # so the overlay is failed, not "shown" with every post failing.
                    self._disable("overlay message loop ended unexpectedly")
        except BaseException as exc:
            self._disable(f"overlay thread failed: {exc!r}", exc_info=True)
        finally:
            try:
                backend.destroy()
            except BaseException as exc:
                self._log.error(f"overlay cleanup failed: {exc!r}")
            engine.finish()

    def _iterate(self):
        """One loop turn: drain messages, then step. (alive, wait)."""
        if not self._backend.pump():
            return False, None
        return True, self._engine.advance()

    def _loop(self):
        backend, engine = self._backend, self._engine
        while True:
            alive, wait = self._iterate()
            if not alive:
                return
            if engine.stopped:
                backend.pump()               # consume WM_DESTROY's WM_QUIT; never block after teardown
                return
            if wait is not None and wait <= 0:
                wait_vblank = getattr(backend, "wait_vblank", None)
                if engine.vsync_alive and callable(wait_vblank):
                    # v7: the compositor clock (P3, G1-2); every second vblank under the P5 lock
                    wait_vblank(engine.frame_period(), engine.pacer.cadence)
                else:
                    backend.pace()           # animating (v5 scenes): DwmFlush vsync pacing
            elif not backend.wait(wait):     # idle: blocks in GetMessageW
                return

    def _disable(self, reason, exc_info=False):
        status = self._status
        status.disabled = True
        status.wants_frames = False
        status.last_error = reason
        self._running = False
        self._log.error(reason, exc_info=exc_info)

    # ----------------------------------------------------------- Tk side
    def _post(self, code, flag):
        try:
            ok = bool(self._backend.post(code))
        except Exception:
            ok = False
        if not ok:
            with self._mail.lock:
                setattr(self._mail, flag, False)   # a failed post never blocks later posts
            self._status.post_failures += 1
            self._log.warn("post", f"overlay: PostMessageW(0x{code:04X}) failed")
        return ok

    def _live(self):
        return self._running and not self._status.disabled and not self._status.closed

    def touch(self):
        """A physical knob touch: slide in (or reverse a slide-out) and keep the
        knob visible until ``hide_seconds`` after the last touch."""
        return self._touch(self.hide_seconds)

    def peek(self, seconds=HIDE_SECONDS):
        """Show the knob for ``seconds`` (tray "Show knob"); a touch with its own duration."""
        return self._touch(float(seconds))

    def _touch(self, seconds):
        if not self._live():
            return False
        now = self._clock()
        mail = self._mail
        with mail.lock:
            if mail.closed or mail.reasons:
                return False                 # ignored while suppressed
            mail.touch_deadline = now + seconds   # the newest touch wins (coalesced while posted)
            post = not mail.touch_posted
            if post:
                mail.touch_time = now
            mail.touch_posted = True
            self._status.wants_frames = True  # the Tk side renders from its next tick
        if post:
            return self._post(WM_APP_TOUCH, "touch_posted")
        return True

    def submit(self, scene):
        """Hand over the newest scene (lcd_key, lcd RGBA at lcd_px or None, 60
        (r, g, b, level)). Posts WM_APP+1 only when none is pending."""
        if not self._live():
            return False
        lcd_key, lcd, ring = scene
        scene = OverlayScene(lcd_key, lcd, _frozen_ring(ring))
        now = self._clock()
        mail = self._mail
        with mail.lock:
            if mail.closed:
                return False
            mail.scene = scene
            mail.scene_seq += 1
            mail.scene_time = now
            post = not mail.frame_posted
            mail.frame_posted = True
        self._status.scenes_submitted += 1
        if post:
            return self._post(WM_APP_FRAME, "frame_posted")
        return True

    def set_suppressed(self, reason, on):
        """Hold (on=True) or release one suppression reason: e.g. 'picker' (the
        Windows picker overlaps ``rect``) or 'disconnected'. While any reason
        holds, the knob slides out at once and touches are ignored. r3: the
        reason 'navigator' (``SUPPRESS_NAVIGATOR``) is held for as long as the
        Navigator stands in for the floating knob (a presentation-6 knob;
        ``ui.ControlCenterApp._render_navigator``, DESKTOP_STAGE 24)."""
        reason = str(reason)
        mail = self._mail
        with mail.lock:
            reasons = set(mail.reasons)
            if on:
                reasons.add(reason)
            else:
                reasons.discard(reason)
            reasons = frozenset(reasons)
            if reasons == mail.reasons:
                return False
            mail.reasons = reasons
            if on:
                self._status.wants_frames = self._status.machine_state != HIDDEN
            post = self._live() and not mail.suppress_posted
            if post:
                mail.suppress_posted = True
        if post:
            self._post(WM_APP_SUPPRESS, "suppress_posted")
        return True

    # ------------------------------------------------ desktop v7 (alive)
    @property
    def alive(self):
        """True while the overlay thread draws the ring with AliveLights (the Tk side asked for it)."""
        return bool(self._status.alive)

    def set_alive(self, on):
        """Tk thread: draw the ring with the alive engine (a knob with ``alive``) or with the v5
        scenes (PreviewLights). A change builds a fresh engine on the overlay thread."""
        on = bool(on)
        mail = self._mail
        with mail.lock:
            if mail.closed or mail.alive_on == on:
                return False
            mail.alive_on = on
            post = self._live() and not mail.alive_posted
            if post:
                mail.alive_posted = True
        if post:
            self._post(WM_APP_ALIVE, "alive_posted")
        return True

    def post_frame(self, frame, *, claimed, local_max=None, t=None):
        """Tk thread: the decorated frame the knob was sent (``{"id": control id, ...}``), whether
        the knob is claimed (the engine's claim / release), and the control's maximum (the local
        cursor's bound, K2 6.3). Newest wins; ``t`` defaults to now (the post time, P12)."""
        if not self._live():
            return False
        t = self._clock() if t is None else float(t)
        mail = self._mail
        with mail.lock:
            if mail.closed or not mail.alive_on:
                return False
            mail.alive_msg = (frame, bool(claimed), local_max, t)
            mail.alive_seq += 1
            post = not mail.alive_posted
            mail.alive_posted = True
        if post:
            return self._post(WM_APP_ALIVE, "alive_posted")
        return True

    def set_latched(self, *, t=None, **values):
        """Tk thread: latched engine inputs straight from the runtime (K2 10.3 item 1): ``clock``
        (local minutes), ``progress`` ((pos ms, dur ms)), ``reduced_motion`` (the effective Motion
        setting) and ``tuning`` ((ledPink int, ledVolFull bool)). Newest wins per name."""
        known = {name: value for name, value in values.items()
                 if name in ("clock", "progress", "reduced_motion", "tuning")}
        if not known or not self._live():
            return False
        t = self._clock() if t is None else float(t)
        mail = self._mail
        with mail.lock:
            if mail.closed:
                return False
            for name, value in known.items():
                mail.latched[name] = (value, t)
            post = not mail.alive_posted
            mail.alive_posted = True
        if post:
            return self._post(WM_APP_ALIVE, "alive_posted")
        return True

    def post_input(self, kind, value, control_id=None, t=None):
        """Any thread (the serial reader's fast path, K4 5.3): ``position`` ((p, delta)), ``limit``
        (-1 | 1) or ``press`` (physical slot), stamped with its QPC read time ``t``. Only while the
        engine draws the ring. Each is also a knob touch (a ``lim`` summons like a turn, K4 11.6)."""
        if kind not in INPUT_KINDS or not self._live():
            return False
        t = self._clock() if t is None else float(t)
        mail = self._mail
        with mail.lock:
            if mail.closed or not mail.alive_on:
                return False
            if len(mail.inputs) == mail.inputs.maxlen:
                mail.inputs_dropped += 1
            mail.inputs.append((kind, value, control_id, t))
            post = not mail.input_posted
            mail.input_posted = True
        self._status.inputs_posted += 1
        if post:
            self._post(WM_APP_INPUT, "input_posted")
        self._touch(self.hide_seconds)
        return True

    def close(self):
        """Post WM_APP+3 and join the thread for at most 1 s. Idempotent."""
        mail = self._mail
        with mail.lock:
            already = mail.closed
            mail.closed = True
        status = self._status
        status.closed = True
        status.wants_frames = False
        self._running = False
        thread = self._thread
        if already and (thread is None or not thread.is_alive()):
            return True
        if thread is None or thread is threading.current_thread():
            return True
        if thread.is_alive():
            backend = self._backend
            posted = False
            try:
                posted = bool(backend.post(WM_APP_STOP))
                if not posted:
                    posted = bool(backend.post_quit())
            except Exception as exc:
                self._log.warn("close", f"overlay: posting the stop failed: {exc!r}")
            thread.join(self.CLOSE_TIMEOUT_SECONDS)
            if thread.is_alive():
                self._log.warn("close", f"overlay thread did not stop within {self.CLOSE_TIMEOUT_SECONDS:g} s"
                                        f" (stop posted: {posted})")
                return False
        return True

    # ---------------------------------------------------------- diagnostics
    def metrics(self):
        """Diagnostics for status.json (plain JSON types)."""
        status = self._status
        gdi = user = None
        backend = self._backend
        if backend is not None:
            try:
                gdi, user = backend.gui_resources()
            except Exception:
                pass
        with self._mail.lock:
            suppressed = sorted(self._mail.reasons)
            inputs_dropped = self._mail.inputs_dropped
        engine = self._engine
        pacer = engine.pacer if engine is not None else None
        clock_counts = None
        counts = getattr(backend, "clock_counts", None)
        if callable(counts):
            try:
                clock_counts = counts()
            except Exception:
                clock_counts = None
        frames = status.frame_stats.metrics() if status.frame_stats is not None else {}
        return {
            "alive": bool(status.alive),
            "looks_build_ms": status.looks_build_ms,
            "engine_renders": status.engine_renders,
            "hidden_renders": status.hidden_renders,
            "catchup_renders": status.catchup_renders,
            "frames_skipped": status.frames_skipped,
            "alive_failures": status.alive_failures,
            "inputs_posted": status.inputs_posted,
            "inputs_dropped": inputs_dropped,
            "reduced_motion": bool(status.reduced_motion),
            "frames": {"knob": frames},
            "pacing": None if pacer is None else {
                "cadence": pacer.cadence, "cadence_switches": pacer.switches, "late_wakes": pacer.late_wakes,
                "period_ms": round(engine.frame_period() * 1000.0, 4), "waits": clock_counts,
                "priority_above_normal": getattr(backend, "priority", None)},
            "state": self.state,
            "wants_frames": self.wants_frames,
            "dpi": status.dpi,
            "scale": round(status.scale, 4) if status.scale else None,
            "window_px": list(status.window_px) if status.window_px else None,
            "face_px": list(status.face_px) if status.face_px else None,
            "inset_px": status.inset_px,
            "rect": list(status.rect) if status.rect else None,
            "lcd_px": status.lcd_px,
            "frames_presented": status.frames_presented,
            "frames_composed": status.frames_composed,
            "ulw_failures": status.ulw_failures,
            "compose_failures": status.compose_failures,
            "post_failures": status.post_failures,
            "scenes_submitted": status.scenes_submitted,
            "face_builds": status.face_builds,
            "compose_ms": status.compose_ms,
            "lcd_resizes": status.lcd_resizes,
            "face_lcd_resizes": status.face_lcd_resizes,
            "suppressed": suppressed,
            "fullscreen_blocked": status.fullscreen_blocked,
            "notification_state": status.notification_state,
            "dpi_awareness": status.awareness,
            "last_error": status.last_error,
            "gdi_objects": gdi,
            "user_objects": user,
        }
