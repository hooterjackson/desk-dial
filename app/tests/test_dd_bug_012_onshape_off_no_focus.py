"""DD-BUG-012: with Onshape mode Off the runtime never polls the foreground watcher, so no window title or
browser address bar is read (no UI Automation into the browser) and no name-change hook is installed.
Manual and Auto still poll it; leaving to Off pauses a watcher that can pause.
Uses test_onshape's RuntimeHarness (simulated device, ManualExecutor): no window, port or network.
"""
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from control_center import onshape  # noqa: E402
from test_onshape import RuntimeHarness  # noqa: E402


class CountingWindows:
    """A browser in front on some site; counts every read the watcher makes."""

    def __init__(self):
        self.hooks, self.reads, self.address_reads = [], 0, 0
        windows = self

        class User:
            def SetWinEventHook(self, *args):
                windows.hooks.append(args)
                return len(windows.hooks)

            def UnhookWinEvent(self, hook):
                return True

        self.u = User()

    def foreground(self):
        self.reads += 1
        return 0x1234

    def pid(self, hwnd):
        return 42

    def exe(self, pid):
        return "chrome.exe"

    def is_onshape(self, hwnd):
        self.address_reads += 1      # stands for the title / address-bar read
        return False


class OnshapeOffTests(unittest.TestCase):
    def make(self):
        windows = CountingWindows()
        watcher = onshape.FocusWatcher(windows, hook=False)
        h = RuntimeHarness(self, focus=watcher)
        self.addCleanup(watcher.close)
        return h, windows, watcher

    def tick_for(self, h, seconds, step=0.025):
        now = [1000.0]
        with mock.patch("control_center.runtime.time.monotonic", side_effect=lambda: now[0]):
            for _ in range(int(seconds / step)):
                now[0] += step
                h.runtime._poll_onshape(now[0])

    def test_mode_off_never_reads_the_address_bar(self):
        h, windows, _ = self.make()
        self.assertEqual(h.runtime.onshape_setting, "off")
        h.runtime.poll()
        self.tick_for(h, 60)
        self.assertEqual((windows.reads, windows.address_reads), (0, 0))
        names = [hook for hook in windows.hooks if hook[0] == onshape.EVENT_OBJECT_NAMECHANGE]
        self.assertEqual(names, [])
        self.assertFalse(h.runtime.onshape_focused)

    def test_auto_and_manual_still_watch(self):
        for mode in ("auto", "manual"):
            with self.subTest(mode=mode):
                h, windows, _ = self.make()
                h.runtime.set_onshape_mode(mode)
                self.tick_for(h, 1)
                self.assertGreater(windows.address_reads, 0)

    def test_turning_off_pauses_a_watcher_that_can(self):
        h, windows, _ = self.make()
        focus = mock.Mock()
        focus.focused.return_value = False
        h.runtime.onshape_focus = focus
        h.runtime.set_onshape_mode("auto")
        self.tick_for(h, 0.1)
        self.assertTrue(focus.focused.called)
        h.runtime.set_onshape_mode("off")
        focus.focused.reset_mock()
        self.tick_for(h, 5)
        focus.focused.assert_not_called()
        focus.pause.assert_called_once_with()

    def test_a_watcher_without_pause_is_fine(self):
        h, windows, watcher = self.make()
        h.runtime.set_onshape_mode("auto")
        self.tick_for(h, 0.1)
        reads = windows.address_reads
        h.runtime.set_onshape_mode("off")
        self.tick_for(h, 5)
        self.assertEqual(windows.address_reads, reads)


if __name__ == "__main__":
    unittest.main()
