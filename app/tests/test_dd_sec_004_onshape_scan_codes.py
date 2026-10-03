"""DD-SEC-004: injected keys carry the scan code of the receiving keyboard layout (Chromium's KeyboardEvent.code
comes from it). Builds INPUT structures only; never calls SendInput."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from control_center import onshape  # noqa: E402

try:
    import windows_actions as wa  # noqa: E402
except Exception:  # pragma: no cover - Windows only
    wa = None


class FakeUser:
    def __init__(self, scans):
        self.scans = scans
        self.layouts = []

    def GetForegroundWindow(self):
        return 0x1234

    def GetWindowThreadProcessId(self, hwnd, pid):
        return 77

    def GetKeyboardLayout(self, thread):
        self.layouts.append(thread)
        return 0x040C040C                      # a non-US layout handle

    def MapVirtualKeyExW(self, vk, kind, layout):
        assert kind == onshape.MAPVK_VK_TO_VSC and layout == 0x040C040C
        return self.scans.get(vk, 0)


@unittest.skipIf(wa is None, "windows_actions (Windows) unavailable")
class ScanCodeTests(unittest.TestCase):
    def backend(self, scans):
        b = onshape.Win32Backend.__new__(onshape.Win32Backend)
        b._INPUT, b._INPUT_KEYBOARD, b._INPUT_MOUSE = wa.INPUT, wa.INPUT_KEYBOARD, wa.INPUT_MOUSE
        b._KEYUP, b._WHEEL = wa.KEYEVENTF_KEYUP, wa.MOUSEEVENTF_WHEEL
        b.u = FakeUser(scans)
        return b

    def test_key_events_carry_a_scan_code(self):
        b = self.backend({0x5A: 0x2C})
        item = b._input(("key", 0x5A, False))
        self.assertEqual(item.ki.wVk, 0x5A)
        self.assertEqual(item.ki.wScan, 0x2C)
        self.assertEqual(item.ki.dwFlags, 0)
        up = b._input(("key", 0x5A, True))
        self.assertEqual(up.ki.wScan, 0x2C)
        self.assertEqual(up.ki.dwFlags, wa.KEYEVENTF_KEYUP)

    def test_the_layout_is_the_foreground_threads_read_once_per_batch(self):
        b = self.backend({0x11: 0x1D, 0x5A: 0x2C})
        b._send_input = lambda n, buffer, size: n
        events = [("key", 0x11, False), ("key", 0x5A, False), ("key", 0x5A, True), ("key", 0x11, True)]
        self.assertEqual(b.send(events), 4)
        self.assertEqual(b.u.layouts, [77], "one layout read for the batch, from the foreground thread")

    def test_unicode_chars_are_unchanged(self):
        b = self.backend({})
        item = b._input(("char", "e", False))
        self.assertEqual(item.ki.wVk, 0)
        self.assertEqual(item.ki.wScan, ord("e"))
        self.assertEqual(item.ki.dwFlags, onshape.KEYEVENTF_UNICODE)


if __name__ == "__main__":
    unittest.main()
