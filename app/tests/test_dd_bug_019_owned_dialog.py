"""DD-BUG-019: switching to (or back to) an app whose modal dialog is open is a success: Windows hands the
activation to the owned dialog, which is in front instead of the app's own window. Fakes only: no window,
no focus change, no hotkey."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_cc_windows  # noqa: E402
from test_cc_windows import AdapterHarness, FakeNative, record  # noqa: E402

from control_center import windows as w  # noqa: E402

TARGET, DIALOG, NESTED, STRANGER = 10, 50, 60, 70


def native_with(foreground, owners):
    """A bare NativeWindows over a fake user32: top-level windows only (GA_ROOT is the window itself)."""
    native = object.__new__(w.NativeWindows)
    native.u = Mock()
    native.u.GetForegroundWindow.return_value = foreground
    native.u.GetAncestor.side_effect = lambda hwnd, flag: hwnd
    native.u.GetWindow.side_effect = lambda hwnd, flag: owners.get(hwnd, 0) if flag == w.GW_OWNER else 0
    native.u.IsIconic.return_value = False
    native._is_own_window = lambda hwnd: False
    native.identity = lambda hwnd: {"hwnd": hwnd, "pid": 20, "id": f"{hwnd:x}"}
    return native


class NativeFocusTests(unittest.TestCase):
    def test_an_owned_dialog_in_front_grants_the_switch_without_polling(self):
        native = native_with(DIALOG, {DIALOG: TARGET})
        with patch.object(w.time, "sleep") as sleep:
            self.assertTrue(native.focus(TARGET, restore=True))
        sleep.assert_not_called()
        self.assertEqual(native.last_focus[0::2], (True, 1), "granted at the first check")

    def test_a_dialog_owned_through_two_levels_counts(self):
        native = native_with(NESTED, {NESTED: DIALOG, DIALOG: TARGET})
        self.assertTrue(native.owned_by(NESTED, TARGET))
        self.assertEqual(native.foreground_for(TARGET)["hwnd"], TARGET)

    def test_an_unrelated_window_is_still_refused(self):
        native = native_with(STRANGER, {DIALOG: TARGET})
        with patch.object(w.time, "sleep"):
            self.assertFalse(native.focus(TARGET))
        self.assertEqual(native.foreground_for(TARGET)["hwnd"], STRANGER)

    def test_an_owner_cycle_ends(self):
        native = native_with(DIALOG, {DIALOG: NESTED, NESTED: DIALOG})
        self.assertFalse(native.owned_by(DIALOG, TARGET))


class DialogNative(FakeNative):
    """Focusing a window with an open modal dialog brings the dialog to the front."""
    dialogs = {}

    def __init__(self):
        super().__init__()
        self.windows[DIALOG] = record(DIALOG)

    def focus(self, hwnd, restore=False):
        self.focus_calls.append((hwnd, restore))
        self.foreground_hwnd = self.dialogs.get(hwnd, hwnd)
        return True

    def foreground_for(self, target):
        if self.dialogs.get(target) == self.foreground_hwnd:
            return self.identity(target)
        return self.foreground()


class AdapterDialogTests(AdapterHarness):
    def setUp(self):
        DialogNative.dialogs = {}
        with patch.object(test_cc_windows, "FakeNative", DialogNative):
            super().setUp()
        self.assertIsInstance(self.adapter.native, DialogNative)

    def test_switch_to_window_whose_owned_dialog_takes_foreground_is_success(self):
        snapshot = self.open_picker()
        item = snapshot["items"][1]
        DialogNative.dialogs = {item["hwnd"]: DIALOG}
        self.assertTrue(self.adapter.activate(item))
        self.assertFalse(self.adapter.overlay.visible, "the picker closed as a switch")
        self.assertEqual(self.events, [])

    def test_cancel_to_an_origin_whose_dialog_takes_foreground_is_restored(self):
        snapshot = self.open_picker()
        DialogNative.dialogs = {snapshot["origin"]["hwnd"]: DIALOG}
        self.assertTrue(self.adapter.cancel(snapshot["origin"]))
        self.assertEqual(self.adapter.take_events()[-1], {"kind": "cancel_result", "restored": True,
                                                          "completed": False})


if __name__ == "__main__":
    unittest.main()
