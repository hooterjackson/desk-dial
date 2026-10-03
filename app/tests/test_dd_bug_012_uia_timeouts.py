"""DD-BUG-012: the address-bar worker bounds its UI Automation calls (IUIAutomation2 connection / transaction
timeouts), so one FindFirst(TreeScope_Descendants) into a slow browser cannot block it indefinitely.

No windows, no ports, no network: the Windows test creates an in-process CUIAutomation8 on a fresh thread, sets
the timeouts and reads them back through the IUIAutomation2 getters (proving the vtable slots)."""
from __future__ import annotations

import ctypes
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from control_center import browser_url, onshape  # noqa: E402

_UIA2_GET_CONNECTION_TIMEOUT = 60
_UIA2_GET_TRANSACTION_TIMEOUT = 62


def _on_fresh_thread(func):
    box = {}

    def run():
        try:
            box["value"] = func()
        except BaseException as exc:          # surfaced on the test thread
            box["error"] = exc
        finally:
            holder = getattr(browser_url._local, "holder", None)
            if holder is not None:
                holder.close()
                del browser_url._local.holder

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(10)
    if "error" in box:
        raise box["error"]
    return box.get("value")


@unittest.skipUnless(sys.platform == "win32", "UI Automation is Windows only")
class RealTimeoutsTest(unittest.TestCase):
    def test_set_timeouts_bounds_this_threads_instance_and_reads_back(self):
        from ctypes import wintypes as W

        def probe():
            if not browser_url.set_timeouts(750):
                return None
            uia = browser_url._automation()
            second = ctypes.c_void_p()
            assert browser_url._method(uia, browser_url._QUERY_INTERFACE, ctypes.POINTER(browser_url.GUID),
                                       ctypes.POINTER(ctypes.c_void_p))(
                uia, ctypes.byref(browser_url._guid(browser_url.IID_IUIAutomation2)), ctypes.byref(second)) == 0
            try:
                conn, trans = W.DWORD(), W.DWORD()
                browser_url._method(second.value, _UIA2_GET_CONNECTION_TIMEOUT, ctypes.POINTER(W.DWORD))(
                    second.value, ctypes.byref(conn))
                browser_url._method(second.value, _UIA2_GET_TRANSACTION_TIMEOUT, ctypes.POINTER(W.DWORD))(
                    second.value, ctypes.byref(trans))
                return conn.value, trans.value
            finally:
                browser_url._release(second.value)

        result = _on_fresh_thread(probe)
        if result is None:
            self.skipTest("IUIAutomation2 unavailable on this Windows")
        self.assertEqual(result, (750, 750))

    def test_bounded_address_host_on_a_missing_window_answers_none(self):
        def probe():
            browser_url.set_timeouts(200)
            return browser_url.address_host(0), browser_url.address_host(0x7FFFFFF0)
        self.assertEqual(_on_fresh_thread(probe), (None, None))


class SetTimeoutsFailsSoftTest(unittest.TestCase):
    def test_no_automation_answers_false(self):
        with mock.patch.object(browser_url, "_automation", return_value=None):
            self.assertFalse(browser_url.set_timeouts(1000))


class WorkerBoundsItsReadsTest(unittest.TestCase):
    def test_live_worker_sets_the_timeout_before_its_first_read(self):
        order = []
        done = threading.Event()

        def fake_timeouts(ms):
            order.append(("timeouts", ms, threading.get_ident()))
            return True

        def fake_host(hwnd):
            order.append(("read", hwnd, threading.get_ident()))
            done.set()
            return "example.org"

        with mock.patch.object(browser_url, "set_timeouts", fake_timeouts), \
                mock.patch.object(browser_url, "address_host", fake_host):
            verdicts = onshape.AddressVerdicts(timeout_ms=onshape.ADDRESS_UIA_TIMEOUT_MS)
            self.assertEqual(verdicts.lookup(42, (42, 1)), (False, None))
            self.assertTrue(done.wait(5))
        self.assertEqual([step[0] for step in order], ["timeouts", "read"])
        self.assertEqual(order[0][1], onshape.ADDRESS_UIA_TIMEOUT_MS)
        self.assertEqual(order[0][2], order[1][2])                       # the same worker thread
        self.assertNotEqual(order[0][2], threading.get_ident())          # never the caller's
        self.assertLessEqual(onshape.ADDRESS_UIA_TIMEOUT_MS, 2000)       # short


if __name__ == "__main__":
    unittest.main()
