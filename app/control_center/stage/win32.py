"""Flat Win32 / DWM / DXGI / D3D11 / DirectComposition exports for the stage (Windows only).

Private ``WinDLL`` instances only (never ``ctypes.windll``), so no declaration is shared with
pystray or the other presenters (the overlay.py convention). Importing this module loads the
DLLs and declares prototypes; it calls nothing.

GIL (DESKTOP_STAGE §4.7.1 as amended by G1-1): every window, DWM and wait call releases the GIL
(``WinDLL`` functions do). The three compositor statistics reads exist twice: ``*_py`` through
``PYFUNCTYPE`` (keep the GIL; the harvest and the input path use these, G1-1) and the plain
GIL-releasing export (kept for the H5 bench's comparison only).
"""
from __future__ import annotations

import ctypes as C
import ctypes.wintypes as W
import sys

from . import com

if sys.platform != "win32":   # pragma: no cover - the stage is Windows-only
    raise ImportError("control_center.stage.win32 needs Windows")

assert C.sizeof(C.c_void_p) == 8, "x64 only (PYFUNCTYPE on COM relies on the single x64 ABI)"

VP = C.c_void_p
HRESULT = com.HRESULT
LRESULT = C.c_ssize_t

kernel32 = C.WinDLL("kernel32", use_last_error=True)
user32 = C.WinDLL("user32", use_last_error=True)
gdi32 = C.WinDLL("gdi32")
dwmapi = C.WinDLL("dwmapi")
dcomp = C.WinDLL("dcomp")
d3d11 = C.WinDLL("d3d11")
dxgi = C.WinDLL("dxgi")
wtsapi32 = C.WinDLL("wtsapi32")


def _decl(dll, name, restype, *argtypes):
    f = getattr(dll, name)
    f.restype = restype
    f.argtypes = list(argtypes)
    return f


def _optional(dll, name, restype, *argtypes):
    """GetProcAddress-style resolve for Windows 11-only exports; None when missing (§5.1 P3)."""
    try:
        return _decl(dll, name, restype, *argtypes)
    except AttributeError:
        return None


def _py_export(dll, name, restype, *argtypes):
    """The same export through a GIL-keeping prototype (non-blocking reads, G1-1)."""
    try:
        getattr(dll, name)
    except AttributeError:
        return None
    return C.PYFUNCTYPE(restype, *argtypes)((name, dll))


# --------------------------------------------------------------------------- structs
class MONITORINFOEXW(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("rcMonitor", com.RECT), ("rcWork", com.RECT), ("dwFlags", W.DWORD),
                ("szDevice", C.c_wchar * 32)]


WNDPROC = C.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)


class WNDCLASSEXW(C.Structure):
    _fields_ = [("cbSize", W.UINT), ("style", W.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", C.c_int),
                ("cbWndExtra", C.c_int), ("hInstance", W.HINSTANCE), ("hIcon", W.HICON), ("hCursor", W.HANDLE),
                ("hbrBackground", W.HBRUSH), ("lpszMenuName", W.LPCWSTR), ("lpszClassName", W.LPCWSTR),
                ("hIconSm", W.HICON)]


class UNSIGNED_RATIO(C.Structure):
    _pack_ = 1
    _fields_ = [("num", C.c_uint32), ("den", C.c_uint32)]


_u64 = C.c_uint64


class DWM_TIMING_INFO(C.Structure):   # dwmapi.h is #pragma pack(1)
    _pack_ = 1
    _fields_ = [("cbSize", C.c_uint32), ("rateRefresh", UNSIGNED_RATIO), ("qpcRefreshPeriod", _u64),
                ("rateCompose", UNSIGNED_RATIO), ("qpcVBlank", _u64), ("cRefresh", _u64), ("cDXRefresh", C.c_uint32),
                ("qpcCompose", _u64), ("cFrame", _u64), ("cDXPresent", C.c_uint32), ("cRefreshFrame", _u64),
                ("cFrameSubmitted", _u64), ("cDXPresentSubmitted", C.c_uint32), ("cFrameConfirmed", _u64),
                ("cDXPresentConfirmed", C.c_uint32), ("cRefreshConfirmed", _u64), ("cDXRefreshConfirmed", C.c_uint32),
                ("cFramesLate", _u64), ("cFramesOutstanding", C.c_uint32), ("cFrameDisplayed", _u64),
                ("qpcFrameDisplayed", _u64), ("cRefreshFrameDisplayed", _u64), ("cFrameComplete", _u64),
                ("qpcFrameComplete", _u64), ("cFramePending", _u64), ("qpcFramePending", _u64),
                ("cFramesDisplayed", _u64), ("cFramesComplete", _u64), ("cFramesPending", _u64),
                ("cFramesAvailable", _u64), ("cFramesDropped", _u64), ("cFramesMissed", _u64),
                ("cRefreshNextDisplayed", _u64), ("cRefreshNextPresented", _u64), ("cRefreshesDisplayed", _u64),
                ("cRefreshesPresented", _u64), ("cRefreshStarted", _u64), ("cPixelsReceived", _u64),
                ("cPixelsDrawn", _u64), ("cBuffersEmpty", _u64)]


class D3DKMT_OPENADAPTERFROMGDIDISPLAYNAME(C.Structure):
    _fields_ = [("DeviceName", C.c_wchar * 32), ("hAdapter", C.c_uint), ("AdapterLuid", com.LUID),
                ("VidPnSourceId", C.c_uint)]


class D3DKMT_CLOSEADAPTER(C.Structure):
    _fields_ = [("hAdapter", C.c_uint)]


class BITMAPINFOHEADER(C.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", C.c_long), ("biHeight", C.c_long), ("biPlanes", W.WORD),
                ("biBitCount", W.WORD), ("biCompression", W.DWORD), ("biSizeImage", W.DWORD),
                ("biXPelsPerMeter", C.c_long), ("biYPelsPerMeter", C.c_long), ("biClrUsed", W.DWORD),
                ("biClrImportant", W.DWORD)]


class FILETIME(C.Structure):
    _fields_ = [("lo", W.DWORD), ("hi", W.DWORD)]

    def seconds(self) -> float:
        return ((self.hi << 32) | self.lo) / 1e7


class POWERBROADCAST_SETTING(C.Structure):
    _fields_ = [("PowerSetting", com.GUID), ("DataLength", W.DWORD), ("Data", C.c_ubyte * 1)]


# --------------------------------------------------------------------------- kernel32
GetModuleHandleW = _decl(kernel32, "GetModuleHandleW", VP, W.LPCWSTR)
GetCurrentProcess = _decl(kernel32, "GetCurrentProcess", VP)
GetCurrentThread = _decl(kernel32, "GetCurrentThread", VP)
GetCurrentThreadId = _decl(kernel32, "GetCurrentThreadId", W.DWORD)
GetCurrentProcessId = _decl(kernel32, "GetCurrentProcessId", W.DWORD)
QueryPerformanceFrequency = _decl(kernel32, "QueryPerformanceFrequency", W.BOOL, C.POINTER(C.c_int64))
CreateEventW = _decl(kernel32, "CreateEventW", VP, VP, W.BOOL, W.BOOL, W.LPCWSTR)
SetEvent = _decl(kernel32, "SetEvent", W.BOOL, VP)
CloseHandle = _decl(kernel32, "CloseHandle", W.BOOL, VP)
CreateWaitableTimerExW = _decl(kernel32, "CreateWaitableTimerExW", VP, VP, W.LPCWSTR, W.DWORD, W.DWORD)
SetWaitableTimer = _decl(kernel32, "SetWaitableTimer", W.BOOL, VP, C.POINTER(C.c_int64), C.c_long, VP, VP, W.BOOL)
SetThreadPriority = _decl(kernel32, "SetThreadPriority", W.BOOL, VP, C.c_int)
GetThreadTimes = _decl(kernel32, "GetThreadTimes", W.BOOL, VP, *(C.POINTER(FILETIME),) * 4)
QueryThreadCycleTime = _decl(kernel32, "QueryThreadCycleTime", W.BOOL, VP, C.POINTER(C.c_uint64))
OpenThread = _decl(kernel32, "OpenThread", VP, W.DWORD, W.BOOL, W.DWORD)
THREAD_QUERY_LIMITED_INFORMATION = 0x0800

_qpc_py = C.PYFUNCTYPE(W.BOOL, C.POINTER(C.c_int64))(("QueryPerformanceCounter", kernel32))
_qpc_buf = C.c_int64()


def qpc() -> int:
    """QueryPerformanceCounter without dropping the GIL."""
    _qpc_py(C.byref(_qpc_buf))
    return _qpc_buf.value


def qpf() -> int:
    v = C.c_int64()
    QueryPerformanceFrequency(C.byref(v))
    return v.value


# --------------------------------------------------------------------------- user32
RegisterClassExW = _decl(user32, "RegisterClassExW", W.ATOM, C.POINTER(WNDCLASSEXW))
UnregisterClassW = _decl(user32, "UnregisterClassW", W.BOOL, W.LPCWSTR, VP)
CreateWindowExW = _decl(user32, "CreateWindowExW", W.HWND, W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int,
                        C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, VP, VP)
DestroyWindow = _decl(user32, "DestroyWindow", W.BOOL, W.HWND)
DefWindowProcW = _decl(user32, "DefWindowProcW", LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
SetWindowPos = _decl(user32, "SetWindowPos", W.BOOL, W.HWND, VP, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT)
ShowWindow = _decl(user32, "ShowWindow", W.BOOL, W.HWND, C.c_int)
IsWindowVisible = _decl(user32, "IsWindowVisible", W.BOOL, W.HWND)
IsWindow = _decl(user32, "IsWindow", W.BOOL, W.HWND)
GetWindowLongPtrW = _decl(user32, "GetWindowLongPtrW", C.c_ssize_t, W.HWND, C.c_int)
SetWindowDisplayAffinity = _decl(user32, "SetWindowDisplayAffinity", W.BOOL, W.HWND, W.DWORD)
PeekMessageW = _decl(user32, "PeekMessageW", W.BOOL, C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT)
TranslateMessage = _decl(user32, "TranslateMessage", W.BOOL, C.POINTER(W.MSG))
DispatchMessageW = _decl(user32, "DispatchMessageW", LRESULT, C.POINTER(W.MSG))
PostMessageW = _decl(user32, "PostMessageW", W.BOOL, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
MsgWaitForMultipleObjectsEx = _decl(user32, "MsgWaitForMultipleObjectsEx", W.DWORD, W.DWORD, C.POINTER(VP),
                                    W.DWORD, W.DWORD, W.DWORD)
MonitorFromWindow = _decl(user32, "MonitorFromWindow", VP, W.HWND, W.DWORD)
MonitorFromPoint = _decl(user32, "MonitorFromPoint", VP, com.POINT, W.DWORD)
GetMonitorInfoW = _decl(user32, "GetMonitorInfoW", W.BOOL, VP, C.POINTER(MONITORINFOEXW))
GetForegroundWindow = _decl(user32, "GetForegroundWindow", W.HWND)
GetWindowThreadProcessId = _decl(user32, "GetWindowThreadProcessId", W.DWORD, W.HWND, C.POINTER(W.DWORD))
LoadCursorW = _decl(user32, "LoadCursorW", VP, VP, VP)
SetCursor = _decl(user32, "SetCursor", VP, VP)
SetThreadDpiAwarenessContext = _decl(user32, "SetThreadDpiAwarenessContext", VP, VP)
RegisterPowerSettingNotification = _decl(user32, "RegisterPowerSettingNotification", VP, VP,
                                         C.POINTER(com.GUID), W.DWORD)
UnregisterPowerSettingNotification = _decl(user32, "UnregisterPowerSettingNotification", W.BOOL, VP)
GetDC = _decl(user32, "GetDC", VP, W.HWND)
ReleaseDC = _decl(user32, "ReleaseDC", C.c_int, W.HWND, VP)

# --------------------------------------------------------------------------- gdi32
CreateCompatibleDC = _decl(gdi32, "CreateCompatibleDC", VP, VP)
DeleteDC = _decl(gdi32, "DeleteDC", W.BOOL, VP)
CreateDIBSection = _decl(gdi32, "CreateDIBSection", VP, VP, C.POINTER(BITMAPINFOHEADER), W.UINT,
                         C.POINTER(VP), VP, W.DWORD)
SelectObject = _decl(gdi32, "SelectObject", VP, VP, VP)
DeleteObject = _decl(gdi32, "DeleteObject", W.BOOL, VP)
BitBlt = _decl(gdi32, "BitBlt", W.BOOL, VP, C.c_int, C.c_int, C.c_int, C.c_int, VP, C.c_int, C.c_int, W.DWORD)
GdiFlush = _decl(gdi32, "GdiFlush", W.BOOL)
D3DKMTOpenAdapterFromGdiDisplayName = _decl(gdi32, "D3DKMTOpenAdapterFromGdiDisplayName", C.c_long,
                                            C.POINTER(D3DKMT_OPENADAPTERFROMGDIDISPLAYNAME))
D3DKMTCloseAdapter = _decl(gdi32, "D3DKMTCloseAdapter", C.c_long, C.POINTER(D3DKMT_CLOSEADAPTER))

# --------------------------------------------------------------------------- dwmapi / wtsapi32
DwmGetCompositionTimingInfo = _decl(dwmapi, "DwmGetCompositionTimingInfo", HRESULT, W.HWND,
                                    C.POINTER(DWM_TIMING_INFO))
DwmSetWindowAttribute = _decl(dwmapi, "DwmSetWindowAttribute", HRESULT, W.HWND, W.DWORD, VP, W.DWORD)
DwmFlush = _decl(dwmapi, "DwmFlush", HRESULT)
WTSRegisterSessionNotification = _decl(wtsapi32, "WTSRegisterSessionNotification", W.BOOL, W.HWND, W.DWORD)
WTSUnRegisterSessionNotification = _decl(wtsapi32, "WTSUnRegisterSessionNotification", W.BOOL, W.HWND)
try:
    shcore = C.WinDLL("shcore")
    GetDpiForMonitor = _optional(shcore, "GetDpiForMonitor", HRESULT, VP, C.c_int, C.POINTER(W.UINT), C.POINTER(W.UINT))
except OSError:                  # pragma: no cover - shcore ships with Windows 8.1 and later
    shcore = GetDpiForMonitor = None
MDT_EFFECTIVE_DPI = 0

# --------------------------------------------------------------------------- DXGI / D3D11 / DirectComposition
CreateDXGIFactory1 = _decl(dxgi, "CreateDXGIFactory1", HRESULT, C.POINTER(com.GUID), C.POINTER(VP))
D3D11CreateDevice = _decl(d3d11, "D3D11CreateDevice", HRESULT, VP, C.c_int, VP, C.c_uint, C.POINTER(C.c_uint),
                          C.c_uint, C.c_uint, C.POINTER(VP), C.POINTER(C.c_uint), C.POINTER(VP))
DCompositionCreateDevice3 = _decl(dcomp, "DCompositionCreateDevice3", HRESULT, VP, C.POINTER(com.GUID),
                                  C.POINTER(VP))

_STATS_ARGS = (C.c_uint64, C.POINTER(com.COMPOSITION_FRAME_STATS), C.c_uint, C.POINTER(com.COMPOSITION_TARGET_ID),
               C.POINTER(C.c_uint))
_TSTATS_ARGS = (C.c_uint64, C.POINTER(com.COMPOSITION_TARGET_ID), C.POINTER(com.COMPOSITION_TARGET_STATS))
# G1-1: the statistics reads keep the GIL.
DCompositionGetFrameId_py = _py_export(dcomp, "DCompositionGetFrameId", HRESULT, C.c_int, C.POINTER(C.c_uint64))
DCompositionGetStatistics_py = _py_export(dcomp, "DCompositionGetStatistics", HRESULT, *_STATS_ARGS)
DCompositionGetTargetStatistics_py = _py_export(dcomp, "DCompositionGetTargetStatistics", HRESULT, *_TSTATS_ARGS)
# GIL-releasing twins, for the H5 bench's comparison only.
DCompositionGetFrameId_wf = _optional(dcomp, "DCompositionGetFrameId", HRESULT, C.c_int, C.POINTER(C.c_uint64))
DCompositionGetStatistics_wf = _optional(dcomp, "DCompositionGetStatistics", HRESULT, *_STATS_ARGS)
DCompositionGetTargetStatistics_wf = _optional(dcomp, "DCompositionGetTargetStatistics", HRESULT, *_TSTATS_ARGS)
DCompositionBoostCompositorClock = _optional(dcomp, "DCompositionBoostCompositorClock", HRESULT, W.BOOL)
DCompositionWaitForCompositorClock = _optional(dcomp, "DCompositionWaitForCompositorClock", W.DWORD, C.c_uint,
                                               C.POINTER(VP), W.DWORD)

FLAT_EXPORTS = {"DCompositionGetFrameId": DCompositionGetFrameId_py,
                "DCompositionGetStatistics": DCompositionGetStatistics_py,
                "DCompositionGetTargetStatistics": DCompositionGetTargetStatistics_py,
                "DCompositionBoostCompositorClock": DCompositionBoostCompositorClock,
                "DCompositionWaitForCompositorClock": DCompositionWaitForCompositorClock}

# --------------------------------------------------------------------------- constants
WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOREDIRECTIONBITMAP = 0x00200000
WS_EX_NOACTIVATE = 0x08000000
GWL_EXSTYLE = -20
HWND_TOPMOST = C.c_void_p(-1)
SWP_NOACTIVATE, SWP_SHOWWINDOW, SWP_NOOWNERZORDER = 0x10, 0x40, 0x200
SW_HIDE = 0
PM_REMOVE = 0x1
QS_ALLINPUT = 0x04FF
MWMO_INPUTAVAILABLE = 0x4
WAIT_OBJECT_0, WAIT_TIMEOUT, WAIT_FAILED = 0x0, 0x102, 0xFFFFFFFF
INFINITE = 0xFFFFFFFF
MONITOR_DEFAULTTOPRIMARY = 1
MONITOR_DEFAULTTONEAREST = 2
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = C.c_void_p(-4)
CREATE_WAITABLE_TIMER_HIGH_RESOLUTION = 0x2
TIMER_ALL_ACCESS = 0x1F0003
THREAD_PRIORITY_BELOW_NORMAL, THREAD_PRIORITY_NORMAL, THREAD_PRIORITY_ABOVE_NORMAL = -1, 0, 1
WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x0, 0x11
DWMWA_TRANSITIONS_FORCEDISABLED, DWMWA_EXCLUDED_FROM_PEEK = 3, 12
DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_DONOTROUND = 33, 1
NOTIFY_FOR_THIS_SESSION = 0
DEVICE_NOTIFY_WINDOW_HANDLE = 0
IDC_ARROW = 32512
ERROR_CLASS_ALREADY_EXISTS = 1410
SRCCOPY, CAPTUREBLT = 0x00CC0020, 0x40000000
WM_QUIT = 0x0012


def monitor_info(hmonitor) -> dict | None:
    mi = MONITORINFOEXW()
    mi.cbSize = C.sizeof(MONITORINFOEXW)
    if not hmonitor or not GetMonitorInfoW(hmonitor, C.byref(mi)):
        return None
    r, w = mi.rcMonitor, mi.rcWork
    return {"hmonitor": hmonitor, "device": mi.szDevice, "rect": (r.left, r.top, r.right, r.bottom),
            "work": (w.left, w.top, w.right, w.bottom), "primary": bool(mi.dwFlags & 1),
            "dpi": monitor_dpi(hmonitor)}


def monitor_dpi(hmonitor) -> int | None:
    """The monitor's effective DPI (what a PMv2 window on it gets in ``WM_DPICHANGED``), or None."""
    if not hmonitor or GetDpiForMonitor is None:
        return None
    x, y = W.UINT(0), W.UINT(0)
    if GetDpiForMonitor(hmonitor, MDT_EFFECTIVE_DPI, C.byref(x), C.byref(y)) != 0:
        return None
    return int(x.value) or None


def primary_monitor() -> dict | None:
    return monitor_info(MonitorFromPoint(com.POINT(0, 0), MONITOR_DEFAULTTOPRIMARY))


def foreground_monitor() -> dict | None:
    """§0.3: the monitor holding the foreground window (primary when there is none)."""
    return monitor_info(MonitorFromWindow(GetForegroundWindow(), MONITOR_DEFAULTTOPRIMARY))


def adapter_for_display(device_name: str):
    """(adapter LUID key, VidPnSourceId) of a GDI display name: the compositor target key."""
    q = D3DKMT_OPENADAPTERFROMGDIDISPLAYNAME()
    q.DeviceName = device_name
    if D3DKMTOpenAdapterFromGdiDisplayName(C.byref(q)) != 0:
        return None
    D3DKMTCloseAdapter(C.byref(D3DKMT_CLOSEADAPTER(q.hAdapter)))
    return q.AdapterLuid.key(), q.VidPnSourceId


def dwm_timing():
    """(qpcRefreshPeriod, qpcVBlank, rate_hz) or None: P is re-read on WM_DISPLAYCHANGE (§0.6)."""
    ti = DWM_TIMING_INFO()
    ti.cbSize = C.sizeof(DWM_TIMING_INFO)
    if DwmGetCompositionTimingInfo(None, C.byref(ti)) != 0:
        return None
    rate = ti.rateRefresh.num / ti.rateRefresh.den if ti.rateRefresh.den else None
    return ti.qpcRefreshPeriod, ti.qpcVBlank, rate


def thread_cpu_seconds() -> float:
    a, b, k, u = FILETIME(), FILETIME(), FILETIME(), FILETIME()
    GetThreadTimes(GetCurrentThread(), C.byref(a), C.byref(b), C.byref(k), C.byref(u))
    return k.seconds() + u.seconds()


class ThreadCpu:
    """Kernel + user time (``GetThreadTimes``) summed over some threads of this process, by their
    native ids (``threading.Thread.native_id``): the §6.2 ``cpu_pct_one_core`` source for the
    stage (``NanoD-stage`` and ``NanoD-stage-capture``). Callable from any thread. The times
    advance in scheduler ticks, so a short episode's share is coarse (about ±15.6 ms of CPU)."""

    def __init__(self, native_ids):
        self.handles = []
        for tid in native_ids:
            if tid:
                h = OpenThread(THREAD_QUERY_LIMITED_INFORMATION, False, int(tid))
                if h:
                    self.handles.append(h)
        self._ft = (FILETIME(), FILETIME(), FILETIME(), FILETIME())

    def seconds(self) -> float:
        a, b, k, u = self._ft
        total = 0.0
        for h in self.handles:
            if GetThreadTimes(h, C.byref(a), C.byref(b), C.byref(k), C.byref(u)):
                total += k.seconds() + u.seconds()
        return total

    def close(self):
        for h in self.handles:
            CloseHandle(h)
        self.handles = []


def thread_cycles() -> int:
    v = C.c_uint64()
    QueryThreadCycleTime(GetCurrentThread(), C.byref(v))
    return v.value
