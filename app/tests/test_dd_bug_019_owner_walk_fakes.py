"""DD-BUG-019 review: the owner walk must not break callers whose user32 stand-in answers GetWindow with a
non-number (a bare Mock), and a direct match must not read any owner at all. Fakes only: no window."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import windows as w  # noqa: E402

TARGET, OTHER = 10, 70


def bare_native(foreground):
    """A NativeWindows over a bare Mock user32: GetWindow returns a Mock, not a handle."""
    native = object.__new__(w.NativeWindows)
    native.u = Mock()
    native.u.GetForegroundWindow.return_value = foreground
    native.u.GetAncestor.side_effect = lambda hwnd, flag: hwnd
    native.u.IsIconic.return_value = False
    native._is_own_window = lambda hwnd: False
    native.identity = lambda hwnd: {"hwnd": hwnd, "pid": 20, "id": f"{hwnd:x}"}
    return native


class OwnerWalkTests(unittest.TestCase):
    def test_a_direct_match_reads_no_owner(self):
        native = bare_native(TARGET)
        self.assertTrue(native.owned_by(TARGET, TARGET))
        native.u.GetWindow.assert_not_called()

    def test_a_non_number_owner_ends_the_walk(self):
        native = bare_native(OTHER)
        self.assertFalse(native.owned_by(OTHER, TARGET))
        self.assertEqual(native.foreground_for(TARGET)["hwnd"], OTHER)

    def test_focus_over_a_bare_mock_is_refused_not_raised(self):
        native = bare_native(OTHER)
        with patch.object(w.time, "sleep"):
            self.assertFalse(native.focus(TARGET))

    def test_handle_or_zero(self):
        self.assertEqual(w._handle_or_zero(None), 0)
        self.assertEqual(w._handle_or_zero(0x5001), 0x5001)
        self.assertEqual(w._handle_or_zero(Mock()), 0)
        self.assertEqual(w._handle_or_zero("x"), 0)


if __name__ == "__main__":
    unittest.main()
