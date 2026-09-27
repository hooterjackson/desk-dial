"""Host window roles and the input contract (DESKTOP_STAGE §2.1, §3, §4.1). The message logic is
tested without Win32; the Win32 host is created **hidden** off-screen at 1 x 1 and never shown
(``hidden_only`` refuses to show it)."""
import ctypes as C
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center.stage import host as HO  # noqa: E402

RECT = (2220, 296, 2900, 976)


def rig(role=HO.ROLE_CLICK_EATING):
    events = []
    cursor = []
    h = HO.HostInput(role, events.append, cursor=lambda: cursor.append(1),
                     power_setting=lambda lp: {1: (True, 0), 2: (True, 1), 3: (True, 2), 4: (False, 0)}[lp])
    h.set_hit_rect(RECT)
    return h, events, cursor


class InputContractTests(unittest.TestCase):
    def test_click_eating_answers(self):
        h, events, cursor = rig()
        self.assertEqual(HO.EX_STYLES[HO.ROLE_CLICK_EATING], 0x08200088)
        self.assertEqual(h.handle(HO.WM_NCHITTEST, 0, 0), HO.HTCLIENT)
        self.assertEqual(h.handle(HO.WM_MOUSEACTIVATE, 0, 0), HO.MA_NOACTIVATE)
        self.assertEqual(h.handle(HO.WM_SETCURSOR, 0, 0), 1)
        self.assertEqual(cursor, [1])
        self.assertEqual(h.handle(HO.WM_CLOSE, 0, 0), 0)

    def test_click_through_answers(self):
        h, _e, _c = rig(HO.ROLE_CLICK_THROUGH)
        self.assertEqual(HO.EX_STYLES[HO.ROLE_CLICK_THROUGH], 0x082800A8)
        self.assertEqual(h.handle(HO.WM_NCHITTEST, 0, 0), HO.HTTRANSPARENT)
        self.assertEqual(h.handle(HO.WM_MOUSEACTIVATE, 0, 0), HO.MA_NOACTIVATE)

    def test_only_down_and_up_inside_the_rest_rect_act(self):
        h, events, _c = rig()
        inside = HO.make_lparam(2500, 600)
        edge_out = HO.make_lparam(2900, 600)                 # right edge is exclusive
        outside = HO.make_lparam(10, 10)
        for down, up, want in ((inside, inside, 1), (inside, outside, 0), (outside, inside, 0),
                               (inside, edge_out, 0), (outside, outside, 0)):
            events.clear()
            self.assertEqual(h.handle(HO.WM_LBUTTONDOWN, 1, down), 0)
            self.assertEqual(h.handle(HO.WM_LBUTTONUP, 0, up), 0)
            self.assertEqual(events.count("click_action"), want, (down, up))

    def test_no_rect_no_action(self):
        h, events, _c = rig()
        h.set_hit_rect(None)
        p = HO.make_lparam(2500, 600)
        h.handle(HO.WM_LBUTTONDOWN, 1, p)
        h.handle(HO.WM_LBUTTONUP, 0, p)
        self.assertEqual(events, [])

    def test_everything_else_is_eaten(self):
        h, events, _c = rig()
        p = HO.make_lparam(2500, 600)
        for msg in (HO.WM_RBUTTONDOWN, HO.WM_RBUTTONUP, HO.WM_MBUTTONDOWN, HO.WM_MBUTTONUP, HO.WM_LBUTTONDBLCLK,
                    HO.WM_CONTEXTMENU, HO.WM_MOUSEWHEEL, HO.WM_MOUSEHWHEEL):
            self.assertEqual(h.handle(msg, 0, p), 0, hex(msg))
        for msg in (HO.WM_XBUTTONDOWN, HO.WM_XBUTTONUP):
            self.assertEqual(h.handle(msg, 0, p), 1)              # TRUE: processed
        self.assertEqual(events, [])
        self.assertEqual(h.eaten["wheel"], 2)

    def test_signed_coordinates(self):
        self.assertEqual(HO.lparam_point(HO.make_lparam(-5, -7)), (-5, -7))
        self.assertEqual(HO.lparam_point(HO.make_lparam(5119, 1439)), (5119, 1439))


class NotificationTests(unittest.TestCase):
    def test_session_power_display_settings(self):
        h, events, _c = rig()
        h.handle(HO.WM_WTSSESSION_CHANGE, HO.WTS_SESSION_LOCK, 0)
        h.handle(HO.WM_WTSSESSION_CHANGE, HO.WTS_CONSOLE_DISCONNECT, 0)
        h.handle(HO.WM_WTSSESSION_CHANGE, HO.WTS_REMOTE_DISCONNECT, 0)
        h.handle(HO.WM_WTSSESSION_CHANGE, 8, 0)                  # WTS_SESSION_UNLOCK: nothing
        self.assertEqual(events, ["lock"] * 3)
        events.clear()
        self.assertEqual(h.handle(HO.WM_POWERBROADCAST, HO.PBT_APMSUSPEND, 0), 1)
        h.handle(HO.WM_POWERBROADCAST, HO.PBT_POWERSETTINGCHANGE, 1)   # display off
        h.handle(HO.WM_POWERBROADCAST, HO.PBT_POWERSETTINGCHANGE, 2)   # display on
        h.handle(HO.WM_POWERBROADCAST, HO.PBT_POWERSETTINGCHANGE, 3)   # dimmed: nothing
        h.handle(HO.WM_POWERBROADCAST, HO.PBT_POWERSETTINGCHANGE, 4)   # another setting: nothing
        self.assertEqual(events, ["sleep", "display_off", "sleep", "display_on"])
        events.clear()
        self.assertIsNone(h.handle(HO.WM_DISPLAYCHANGE, 32, 0))
        self.assertEqual(h.handle(HO.WM_DPICHANGED, 0, 0), 0)
        h.handle(HO.WM_DWMCOMPOSITIONCHANGED, 0, 0)
        h.handle(HO.WM_SETTINGCHANGE, HO.SPI_SETWORKAREA, 0)
        h.handle(HO.WM_SETTINGCHANGE, HO.SPI_SETCLIENTAREAANIMATION, 0)
        h.handle(HO.WM_SETTINGCHANGE, 0x0072, 0)                 # something else: nothing
        self.assertEqual(events, ["display"] * 4 + ["motion"])
        events.clear()
        h.handle(HO.WM_ENDSESSION, 0, 0)
        h.handle(HO.WM_ENDSESSION, 1, 0)
        self.assertEqual(events, ["endsession"])

    def test_dpi_change_from_our_own_move_is_not_a_display_change(self):
        """WP7a-R5: SetWindowPos onto a monitor of another DPI sends WM_DPICHANGED to the host."""
        h, events, _c = rig()
        with h.own_move():
            self.assertEqual(h.handle(HO.WM_DPICHANGED, (144 << 16) | 144, 0), 0)
            with h.own_move():                                      # nesting is fine
                h.handle(HO.WM_DPICHANGED, (120 << 16) | 120, 0)
            h.handle(HO.WM_DPICHANGED, (96 << 16) | 96, 0)
        self.assertEqual(events, [])
        self.assertEqual(h.dpi_ignored, 3)
        h.expected_dpi = 144                                         # the open scene's monitor
        h.handle(HO.WM_DPICHANGED, (144 << 16) | 144, 0)            # a late delivery of our move
        self.assertEqual(events, [])
        h.handle(HO.WM_DPICHANGED, (168 << 16) | 168, 0)            # that monitor's scale changed
        self.assertEqual(events, ["display"])
        h.expected_dpi = None
        h.handle(HO.WM_DPICHANGED, (144 << 16) | 144, 0)            # nothing open: as before
        self.assertEqual(events, ["display", "display"])

    def test_show_wraps_its_setwindowpos_in_own_move(self):
        """``HostWindow.show`` without any window: a stub stands in for user32 (nothing shown)."""
        h, events, _c = rig()
        seen = []

        class StubW:
            HWND_TOPMOST = -1

            @staticmethod
            def SetWindowPos(hwnd, after, x, y, w, hh, flags):
                seen.append((h.moving, flags))
                h.handle(HO.WM_DPICHANGED, (144 << 16) | 144, 0)    # sent from inside the move
                return 1

        hw = HO.HostWindow.__new__(HO.HostWindow)
        hw.hidden_only, hw.handler, hw.hwnd, hw.W, hw.shown = False, h, 0x1234, StubW, False
        self.assertTrue(hw.show((0, 0, 5120, 1440)))
        self.assertEqual(seen, [(1, HO.SHOW_FLAGS)])
        self.assertEqual(h.moving, 0)
        self.assertEqual(events, [])

    def test_unknown_messages_go_to_defwindowproc(self):
        h, _e, _c = rig()
        self.assertIsNone(h.handle(0x000F, 0, 0))                # WM_PAINT

    def test_only_a_showable_host_registers_for_the_display_state(self):
        """RN-R5 (the stage owner's fix): Windows answers a GUID_CONSOLE_DISPLAY_STATE registration at
        once with the current state, so a hidden-only host (tests, the self-tests) never registers
        and a headless run cannot see display_off + sleep from a sleeping display. The real host
        still registers both. A stub stands in for user32 / wtsapi32 (nothing is created)."""
        calls = []

        class StubW:
            NOTIFY_FOR_THIS_SESSION, DEVICE_NOTIFY_WINDOW_HANDLE = 0, 0

            @staticmethod
            def WTSRegisterSessionNotification(hwnd, flags):
                calls.append("wts")
                return 1

            @staticmethod
            def RegisterPowerSettingNotification(hwnd, guid, flags):
                calls.append("power")
                return 0xB0B

        for hidden, want_power in ((True, None), (False, 0xB0B)):
            calls.clear()
            hw = HO.HostWindow.__new__(HO.HostWindow)
            hw.hidden_only, hw.hwnd, hw.W, hw.info = hidden, 0x1234, StubW, {}
            hw.notifications = {"wts": False, "power": None}
            got = hw.register_notifications()
            self.assertEqual(got, {"wts": True, "power": want_power}, hidden)
            self.assertEqual(calls, ["wts"] if hidden else ["wts", "power"], hidden)
            if hidden:
                self.assertIn("hidden-only", hw.info["power_notification"])


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class HiddenWin32HostTests(unittest.TestCase):
    """The real window, created hidden at (-32000, -32000) 1 x 1 and never shown."""

    def test_styles_hidden_and_refuses_to_show(self):
        for role, style in ((HO.ROLE_CLICK_EATING, 0x08200088), (HO.ROLE_CLICK_THROUGH, 0x082800A8)):
            events = []
            h = HO.HostWindow(HO.HostInput(role, events.append), hidden_only=True)
            try:
                self.assertEqual(h.ex_style(), style)
                self.assertFalse(h.info["visible_after_create"])
                self.assertFalse(h.visible())
                with self.assertRaises(RuntimeError):
                    h.show((0, 0, 100, 100))
                self.assertFalse(h.visible())
                registered = h.register_notifications()
                self.assertTrue(registered["wts"])
                self.assertIsNone(registered["power"], "a hidden-only host skips the display state (RN-R5)")
                h.unregister_notifications()
                # the class procedure answers through the registered handler
                want = HO.HTCLIENT if role == HO.ROLE_CLICK_EATING else HO.HTTRANSPARENT
                self.assertEqual(HO._wndproc(h.hwnd, HO.WM_NCHITTEST, 0, 0), want)
                self.assertEqual(HO._wndproc(h.hwnd, HO.WM_MOUSEACTIVATE, 0, 0), HO.MA_NOACTIVATE)
            finally:
                h.destroy()
            self.assertIsNone(h.hwnd)

    def test_power_setting_reader(self):
        from control_center.stage import com, win32 as W
        buf = (C.c_ubyte * (C.sizeof(W.POWERBROADCAST_SETTING) + 4))()
        ps = W.POWERBROADCAST_SETTING.from_buffer(buf)
        C.memmove(C.addressof(ps.PowerSetting), C.byref(com.GUID_CONSOLE_DISPLAY_STATE), 16)
        ps.DataLength = 4
        C.c_uint32.from_address(C.addressof(buf) + W.POWERBROADCAST_SETTING.Data.offset).value = 0
        self.assertEqual(HO.read_power_setting(C.addressof(buf)), (True, 0))
        C.c_uint32.from_address(C.addressof(buf) + W.POWERBROADCAST_SETTING.Data.offset).value = 1
        self.assertEqual(HO.read_power_setting(C.addressof(buf)), (True, 1))
        self.assertEqual(HO.read_power_setting(0), (False, None))


if __name__ == "__main__":
    unittest.main()
