"""DD-BUG-026: the session watcher's window class is shared per process, and a session change goes to the
watcher that owns the window it arrived on (a second watcher, built before the first is closed, used to get
the first watcher's procedure). Headless: no window is created; the dispatch is driven with fake handles."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from control_center import onshape  # noqa: E402


def fake_watcher(hwnd, calls, tag):
    watcher = onshape.SessionWatcher.__new__(onshape.SessionWatcher)
    watcher.hwnd = hwnd
    watcher.on_change = lambda code: calls.append((tag, code))
    return watcher


class SessionDispatchTests(unittest.TestCase):
    def setUp(self):
        self._saved = dict(onshape._session_watchers)
        onshape._session_watchers.clear()

    def tearDown(self):
        onshape._session_watchers.clear()
        onshape._session_watchers.update(self._saved)

    def test_second_session_watcher_gets_its_own_session_change(self):
        calls = []
        first, second = fake_watcher(0x101, calls, "first"), fake_watcher(0x202, calls, "second")
        onshape._session_watchers[0x101] = first
        onshape._session_watchers[0x202] = second
        self.assertTrue(onshape._session_message(0x202, onshape.WM_WTSSESSION_CHANGE, 7))   # WTS_SESSION_LOCK
        self.assertEqual(calls, [("second", 7)])
        self.assertTrue(onshape._session_message(0x101, onshape.WM_WTSSESSION_CHANGE, 3))
        self.assertEqual(calls, [("second", 7), ("first", 3)])

    def test_other_messages_and_unknown_windows_reach_no_watcher(self):
        calls = []
        onshape._session_watchers[0x101] = fake_watcher(0x101, calls, "first")
        self.assertFalse(onshape._session_message(0x101, onshape.WM_CLOSE, 0))
        self.assertTrue(onshape._session_message(0x999, onshape.WM_WTSSESSION_CHANGE, 7))
        self.assertEqual(calls, [])

    def test_a_failing_on_change_never_escapes_the_procedure(self):
        watcher = fake_watcher(0x101, [], "x")
        watcher.on_change = Mock(side_effect=RuntimeError("closed"))
        onshape._session_watchers[0x101] = watcher
        self.assertTrue(onshape._session_message(0x101, onshape.WM_WTSSESSION_CHANGE, 7))

    def test_destroy_forgets_the_window(self):
        onshape._session_watchers[0x101] = fake_watcher(0x101, [], "first")
        user = Mock()
        with patch.dict(onshape._session_class, {"user": user}):
            self.assertEqual(onshape._session_procedure(0x101, onshape.WM_DESTROY, 0, 0), 0)
        self.assertNotIn(0x101, onshape._session_watchers)
        user.PostQuitMessage.assert_called_once_with(0)

    def test_the_class_is_registered_once_per_process(self):
        source = Path(onshape.__file__).read_text(encoding="utf-8")
        body = source[source.index("class SessionWatcher"):source.index("def live_service(")]
        self.assertNotIn("RegisterClassW", body, "no per-watcher class registration")
        self.assertNotIn("def procedure", body, "no per-watcher window procedure")


if __name__ == "__main__":
    unittest.main()
