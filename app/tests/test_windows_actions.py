"""The backend is always mocked: these tests never send desktop input."""

import ctypes
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import windows_actions as wa


class FakeSendInput:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    def __call__(self, count, events, item_size):
        # Copy records while the temporary ctypes array is alive.
        copied = [wa.INPUT.from_buffer_copy(bytes(events[i])) for i in range(count)]
        self.calls.append((count, copied, item_size))
        return count if self.result is None else self.result


class WindowsActionsTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeSendInput()
        self.loader = patch.object(wa, "_load_send_input", return_value=self.fake)
        self.mock_loader = self.loader.start()
        self.addCleanup(self.loader.stop)

    def test_default_and_disabled_instances_cannot_send_input(self):
        actions = wa.WindowsActions()
        for method, args in (
            (actions.volume_steps, (5,)),
            (actions.scroll_steps, (-5,)),
            (actions.mute, ()),
            (actions.play_pause, ()),
            (actions.next_track, ()),
        ):
            method(*args)
        self.assertFalse(actions.enabled)
        self.mock_loader.assert_not_called()
        self.assertEqual(self.fake.calls, [])
        actions.set_enabled(True)
        actions.set_enabled(False)
        actions.mute()
        self.assertEqual(self.fake.calls, [])

    def test_volume_direction_and_complete_key_pairs(self):
        actions = wa.WindowsActions(enabled=True)
        for delta, key in ((3, wa.VK_VOLUME_UP), (-2, wa.VK_VOLUME_DOWN)):
            actions.volume_steps(delta)
            count, events, size = self.fake.calls[-1]
            self.assertEqual(count, abs(delta) * 2)
            self.assertEqual(size, ctypes.sizeof(wa.INPUT))
            self.assertEqual([e.type for e in events], [wa.INPUT_KEYBOARD] * count)
            self.assertEqual([e.ki.wVk for e in events], [key] * count)
            self.assertEqual([e.ki.dwFlags for e in events], [0, wa.KEYEVENTF_KEYUP] * abs(delta))
            self.assertTrue(all(e.ki.wScan == 0 for e in events))

    def test_scroll_direction_notches_and_no_pointer_movement(self):
        actions = wa.WindowsActions(enabled=True)
        for delta, expected_wheel in ((2, -120), (-3, 120)):
            actions.scroll_steps(delta)
            count, events, _ = self.fake.calls[-1]
            self.assertEqual(count, abs(delta))
            for event in events:
                self.assertEqual(event.type, wa.INPUT_MOUSE)
                self.assertEqual(event.mi.dwFlags, wa.MOUSEEVENTF_WHEEL)
                self.assertEqual(ctypes.c_int32(event.mi.mouseData).value, expected_wheel)
                self.assertEqual((event.mi.dx, event.mi.dy), (0, 0))

    def test_limits_and_zero_steps(self):
        actions = wa.WindowsActions(enabled=True)
        actions.volume_steps(1000000)
        self.assertEqual(self.fake.calls[-1][0], 16)
        actions.scroll_steps(-1000000)
        self.assertEqual(self.fake.calls[-1][0], 8)
        actions.volume_steps(0)
        actions.scroll_steps(0)
        self.assertEqual(len(self.fake.calls), 2)

    def test_invalid_values_never_send_input(self):
        actions = wa.WindowsActions(enabled=True)
        for value in (True, False, 1.5, "2", None):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    actions.volume_steps(value)
                with self.assertRaises(TypeError):
                    actions.scroll_steps(value)
        with self.assertRaises(TypeError):
            actions.set_enabled("false")
        self.assertEqual(self.fake.calls, [])

    def test_media_buttons_have_press_and_release(self):
        actions = wa.WindowsActions(enabled=True)
        for method, key in (
            (actions.mute, wa.VK_VOLUME_MUTE),
            (actions.play_pause, wa.VK_MEDIA_PLAY_PAUSE),
            (actions.next_track, wa.VK_MEDIA_NEXT_TRACK),
        ):
            method()
            count, events, _ = self.fake.calls[-1]
            self.assertEqual(count, 2)
            self.assertEqual([e.ki.wVk for e in events], [key, key])
            self.assertEqual([e.ki.dwFlags for e in events], [0, wa.KEYEVENTF_KEYUP])

    def test_zero_and_partial_returns_raise_and_disable_output(self):
        for result in (0, 1):
            with self.subTest(result=result):
                self.fake.result = result
                actions = wa.WindowsActions(enabled=True)
                with self.assertRaisesRegex(OSError, f"inserted {result} of 2 events"):
                    actions.mute()
                self.assertFalse(actions.enabled)
                call_count = len(self.fake.calls)
                actions.next_track()
                self.assertEqual(len(self.fake.calls), call_count)

    def test_ctypes_oserror_disables_output(self):
        def failed_send_input(*args):
            raise OSError("fake operating-system failure")
        self.mock_loader.return_value = failed_send_input
        actions = wa.WindowsActions(enabled=True)
        with self.assertRaisesRegex(OSError, "fake operating-system failure"):
            actions.mute()
        self.assertFalse(actions.enabled)

    def test_non_windows_can_preview_but_cannot_enable(self):
        # Stop the fake loader here; the platform guard precedes DLL loading.
        self.loader.stop()
        with patch.object(wa.sys, "platform", "linux"):
            actions = wa.WindowsActions()
            actions.volume_steps(1)
            with self.assertRaisesRegex(OSError, "require Windows"):
                actions.set_enabled(True)
            self.assertFalse(actions.enabled)

    def test_win32_structures_have_full_union_and_pointer_alignment(self):
        pointer_size = ctypes.sizeof(ctypes.c_void_p)
        self.assertIn(pointer_size, (4, 8))
        self.assertEqual(ctypes.sizeof(wa.DWORD), 4)
        self.assertEqual(ctypes.sizeof(wa.LONG), 4)
        self.assertEqual(ctypes.sizeof(wa.ULONG_PTR), pointer_size)
        self.assertEqual(ctypes.sizeof(wa.HARDWAREINPUT), 8)
        self.assertEqual(ctypes.sizeof(wa.MOUSEINPUT), 32 if pointer_size == 8 else 24)
        self.assertEqual(ctypes.sizeof(wa.KEYBDINPUT), 24 if pointer_size == 8 else 16)
        self.assertEqual(ctypes.sizeof(wa.INPUT), 40 if pointer_size == 8 else 28)
        self.assertEqual(wa.INPUT.data.offset, 8 if pointer_size == 8 else 4)
        self.assertEqual(wa.KEYBDINPUT.dwExtraInfo.offset, 16 if pointer_size == 8 else 12)
        self.assertEqual(wa.MOUSEINPUT.dwExtraInfo.offset, 24 if pointer_size == 8 else 20)
        self.assertEqual({name for name, _ in wa._INPUT_UNION._fields_}, {"mi", "ki", "hi"})


if __name__ == "__main__":
    unittest.main()
