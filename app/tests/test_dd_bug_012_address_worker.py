"""DD-BUG-012 (onshape side): FocusWatcher.pause() drops the browser's name-change hook, and the address-bar read
(UI Automation) runs on one worker thread whose per-(window, title) verdict is_onshape consults without blocking.
Fakes only: no window, no UI Automation, no port, no network."""
from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from control_center import onshape as O  # noqa: E402


class FakeUser:
    def __init__(self, titles):
        self.titles = titles
        self.hooks, self.unhooked = [], []

    def GetWindowTextW(self, hwnd, buffer, size):
        buffer.value = self.titles[hwnd]

    def SetWinEventHook(self, *args):
        self.hooks.append(args)
        return len(self.hooks)

    def UnhookWinEvent(self, hook):
        self.unhooked.append(hook)
        return True


def windows_with(verdicts, titles):
    w = O.OnshapeWindows.__new__(O.OnshapeWindows)
    w._exes = {}
    w.exe = lambda pid: "chrome.exe"
    w.pid = lambda hwnd: 7
    w.u = FakeUser(titles)
    w._verdicts = verdicts
    w.foreground = lambda: 1
    return w


class GatedReader:
    """An address_host stand-in that blocks until released, recording the thread it ran on."""

    def __init__(self, host):
        self.host = host
        self.threads = []
        self.gate = threading.Event()
        self.done = threading.Event()

    def __call__(self, hwnd):
        self.threads.append(threading.get_ident())
        self.gate.wait(5)
        self.done.set()
        return self.host


def wait_until(predicate, timeout=5.0):
    event = threading.Event()
    for _ in range(int(timeout / 0.01)):
        if predicate():
            return True
        event.wait(0.01)
    return predicate()


class AddressWorkerTests(unittest.TestCase):
    def test_is_onshape_never_blocks_and_reads_off_the_calling_thread(self):
        reader = GatedReader("cad.onshape.com")
        verdicts = O.AddressVerdicts(reader=reader)
        w = windows_with(verdicts, {1: "Bracket | Part Studio 1 - Google Chrome"})
        # The read is held at the gate: the call still answers at once (not Onshape until it is known).
        self.assertFalse(w.is_onshape(1))
        self.assertFalse(w.is_onshape(1))
        reader.gate.set()
        self.assertTrue(reader.done.wait(5))
        self.assertTrue(wait_until(lambda: w.is_onshape(1)))
        self.assertEqual(len(reader.threads), 1, "one read per window and title, never queued twice")
        self.assertNotEqual(reader.threads[0], threading.get_ident())

    def test_unreadable_host_falls_back_to_the_strict_title_rule_on_the_caller(self):
        reader = GatedReader(None)
        reader.gate.set()
        verdicts = O.AddressVerdicts(reader=reader)
        titles = {1: "Bracket | Onshape - Google Chrome", 2: "Inbox - Gmail - Google Chrome"}
        w = windows_with(verdicts, titles)
        w.is_onshape(1), w.is_onshape(2)
        self.assertTrue(wait_until(lambda: w.is_onshape(1)))
        self.assertFalse(w.is_onshape(2))

    def test_marketing_host_is_not_onshape_whatever_the_title(self):
        reader = GatedReader("www.onshape.com")
        reader.gate.set()
        verdicts = O.AddressVerdicts(reader=reader)
        w = windows_with(verdicts, {1: "Pricing | Onshape - Google Chrome"})
        w.is_onshape(1)
        self.assertTrue(reader.done.wait(5))
        self.assertTrue(wait_until(lambda: not verdicts._pending))
        self.assertFalse(w.is_onshape(1))

    def test_expired_verdict_keeps_answering_while_it_is_read_again(self):
        now = [100.0]
        reader = GatedReader("cad.onshape.com")
        reader.gate.set()
        verdicts = O.AddressVerdicts(reader=reader, clock=lambda: now[0])
        w = windows_with(verdicts, {1: "Bracket | Part Studio 1 - Google Chrome"})
        w.is_onshape(1)
        self.assertTrue(wait_until(lambda: w.is_onshape(1)))
        reader.gate.clear()
        reader.done.clear()
        now[0] += O.ADDRESS_CACHE_SECONDS + 1
        self.assertTrue(w.is_onshape(1), "the last verdict stands while the window is read again")
        reader.gate.set()
        self.assertTrue(reader.done.wait(5))
        self.assertEqual(len(reader.threads), 2)

    def test_finished_read_marks_the_focus_watcher_stale(self):
        reader = GatedReader("cad.onshape.com")
        verdicts = O.AddressVerdicts(reader=reader)
        w = windows_with(verdicts, {1: "Bracket | Part Studio 1 - Google Chrome"})
        now = [10.0]
        watcher = O.FocusWatcher(w, clock=lambda: now[0], hook=False)
        self.assertFalse(watcher.focused())
        self.assertFalse(watcher._stale)
        reader.gate.set()
        self.assertTrue(wait_until(lambda: watcher._stale))
        self.assertTrue(watcher.focused(), "re-read at once, not after the next poll")


class PauseTests(unittest.TestCase):
    def test_pause_unhooks_names_and_forgets_the_foreground(self):
        verdicts = O.AddressVerdicts(reader=lambda hwnd: None)
        w = windows_with(verdicts, {1: "Inbox - Gmail - Google Chrome"})
        watcher = O.FocusWatcher(w, clock=lambda: 10.0, hook=False)
        watcher.focused()
        self.assertEqual(len(w.u.hooks), 1, "the browser's name-change hook")
        self.assertEqual(watcher._foreground, 1)
        watcher.pause()
        self.assertEqual(w.u.unhooked, [1])
        self.assertIsNone(watcher._name_hook)
        self.assertIsNone(watcher._foreground)
        self.assertTrue(watcher._stale)
        watcher.pause()                                  # twice is harmless
        self.assertEqual(w.u.unhooked, [1])
        watcher.focused()                                # back in a mode: hooked again
        self.assertEqual(len(w.u.hooks), 2)
        watcher.close()


if __name__ == "__main__":
    unittest.main()
