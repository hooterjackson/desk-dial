"""DD-RES-008: the per-thread UI Automation instance is Released, and COM uninitialised on its own thread, when
the thread that made it ends. Fakes only: no COM call, no window, no browser."""
from pathlib import Path
import gc
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import browser_url  # noqa: E402


class UiaLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.lock = threading.Lock()
        self.calls = {"init": [], "create": 0, "release": [], "uninit": []}
        self.init_ok = lambda index: True
        self.next_ptr = 1000

        def co_initialize():
            with self.lock:
                ok = self.init_ok(len(self.calls["init"]))
                self.calls["init"].append((threading.get_ident(), ok))
                return ok

        def co_create():
            with self.lock:
                self.calls["create"] += 1
                self.next_ptr += 1
                return self.next_ptr

        def release(ptr):
            with self.lock:
                self.calls["release"].append(ptr)

        def co_uninitialize():
            with self.lock:
                self.calls["uninit"].append(threading.get_ident())

        for name, fake in (("_co_initialize", co_initialize), ("_co_create", co_create), ("_release", release),
                           ("_co_uninitialize", co_uninitialize)):
            patcher = patch.object(browser_url, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_threads(self, count, calls_each=3):
        seen = []

        def work():
            for _ in range(calls_each):
                seen.append(browser_url._automation())

        threads = [threading.Thread(target=work) for _ in range(count)]
        for thread in threads:
            thread.start()
            thread.join()
        gc.collect()
        return seen

    def test_uia_instance_released_when_thread_exits(self):
        seen = self.run_threads(5)
        self.assertEqual(self.calls["create"], 5, "one instance per thread, reused within it")
        self.assertEqual(len(set(seen)), 5)
        self.assertEqual(sorted(self.calls["release"]), sorted(set(seen)), "each instance Released once")
        initialised = [ident for ident, ok in self.calls["init"] if ok]
        self.assertEqual(len(self.calls["uninit"]), len(initialised))
        self.assertEqual(sorted(self.calls["uninit"]), sorted(initialised), "uninitialised on its own thread")

    def test_a_thread_whose_apartment_was_already_set_owes_no_uninitialise(self):
        self.init_ok = lambda index: index % 2 == 0          # RPC_E_CHANGED_MODE on every other thread
        self.run_threads(4)
        self.assertEqual(len(self.calls["release"]), 4)
        self.assertEqual(len(self.calls["uninit"]), 2)

    def test_a_holder_closed_from_another_thread_releases_but_never_uninitialises(self):
        holder = []
        thread = threading.Thread(target=lambda: holder.append(browser_url._Automation()))
        thread.start()
        thread.join()
        holder[0].close()                                    # here, not on its thread
        self.assertEqual(len(self.calls["release"]), 1)
        self.assertEqual(self.calls["uninit"], [])
        holder[0].close()
        self.assertEqual(len(self.calls["release"]), 1, "closed once")


if __name__ == "__main__":
    unittest.main()
