"""Bounded Windows media-key and mouse-wheel output, disabled by default.

No external packages are required. Importing this module or constructing a
disabled instance never sends input. WindowsActions is intended to be called
from the application's UI thread.

Win32 layouts and return handling follow Microsoft's INPUT / SendInput docs:
https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-input
https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput
"""

from __future__ import annotations

import ctypes
import sys


# Fixed-width fields matter: Windows uses 32-bit LONG/DWORD even on 64-bit PCs.
DWORD = ctypes.c_uint32
LONG = ctypes.c_int32
WORD = ctypes.c_uint16
ULONG_PTR = ctypes.c_size_t

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120
MAX_STEPS = 8

VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PLAY_PAUSE = 0xB3


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", LONG),
        ("dy", LONG),
        ("mouseData", DWORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", WORD),
        ("wScan", WORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", DWORD), ("wParamL", WORD), ("wParamH", WORD)]


class _INPUT_UNION(ctypes.Union):
    # Keep all three members, even though this app does not use hardware input.
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", DWORD), ("data", _INPUT_UNION)]


def _load_send_input():
    if sys.platform != "win32":
        raise OSError("Windows desktop controls require Windows.")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    send_input = user32.SendInput
    send_input.argtypes = (ctypes.c_uint32, ctypes.POINTER(INPUT), ctypes.c_int)
    send_input.restype = ctypes.c_uint32
    return send_input


def _bounded_steps(delta: int) -> int:
    if type(delta) is not int:
        raise TypeError("delta must be an integer number of knob steps")
    return max(-MAX_STEPS, min(MAX_STEPS, delta))


class WindowsActions:
    """Opt-in desktop output; turn clockwise to raise volume or scroll down.

    Each volume step is one complete media-key press and release. Each scroll
    step is one wheel notch. Large deltas are capped at eight steps per call.
    These are relative changes, not a request for an absolute volume level.
    """

    def __init__(self, enabled: bool = False):
        self._enabled = False
        self._send_input = None
        self.set_enabled(enabled)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise TypeError("enabled must be True or False")
        if enabled and self._send_input is None:
            self._send_input = _load_send_input()
        self._enabled = enabled

    def _send(self, events: list[INPUT]) -> None:
        if not self._enabled or not events:
            return
        buffer = (INPUT * len(events))(*events)
        # Last-error state is meaningful only on Windows. The fallbacks permit
        # platform-independent tests using a fake SendInput implementation.
        getattr(ctypes, "set_last_error", lambda error: None)(0)
        try:
            sent = self._send_input(len(buffer), buffer, ctypes.sizeof(INPUT))
        except OSError:
            self._enabled = False
            raise
        if sent != len(buffer):
            error = getattr(ctypes, "get_last_error", lambda: 0)()
            self._enabled = False
            raise OSError(
                error,
                f"Windows SendInput inserted {sent} of {len(buffer)} events "
                f"(Windows error {error}). Desktop controls have been disabled. "
                "The target may be running as administrator or input may be blocked.",
            )

    def _press(self, virtual_key: int, count: int = 1) -> None:
        if not self._enabled:
            return
        events = []
        for _ in range(count):
            down = INPUT(type=INPUT_KEYBOARD)
            down.ki.wVk = virtual_key
            up = INPUT(type=INPUT_KEYBOARD)
            up.ki.wVk = virtual_key
            up.ki.dwFlags = KEYEVENTF_KEYUP
            events.extend((down, up))
        self._send(events)

    def volume_steps(self, delta: int) -> None:
        """Raise (positive) or lower (negative) volume by up to eight steps."""
        steps = _bounded_steps(delta)
        if steps:
            self._press(VK_VOLUME_UP if steps > 0 else VK_VOLUME_DOWN, abs(steps))

    def scroll_steps(self, delta: int) -> None:
        """Scroll down for positive steps, up for negative steps; cap at eight."""
        steps = _bounded_steps(delta)
        if not self._enabled or not steps:
            return
        events = []
        wheel = -WHEEL_DELTA if steps > 0 else WHEEL_DELTA
        for _ in range(abs(steps)):
            event = INPUT(type=INPUT_MOUSE)
            # mouseData is DWORD; negative wheel deltas use two's complement.
            event.mi.mouseData = wheel & 0xFFFFFFFF
            event.mi.dwFlags = MOUSEEVENTF_WHEEL
            events.append(event)
        self._send(events)

    def mute(self) -> None:
        """Toggle system mute."""
        self._press(VK_VOLUME_MUTE)

    def play_pause(self) -> None:
        """Send the system media play/pause key."""
        self._press(VK_MEDIA_PLAY_PAUSE)

    def next_track(self) -> None:
        """Send the system media next-track key."""
        self._press(VK_MEDIA_NEXT_TRACK)
