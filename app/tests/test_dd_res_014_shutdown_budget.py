"""DD-RES-014: the stage's shutdown is bounded. The art workers share one close deadline (three
workers stuck mid-download cost one timeout, not three), and a second close of the art service or
the stage thread (main's ``finally`` after ``app.close``) never waits again. Headless: no window,
no network (the stuck jobs block on an event)."""
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.stage.engine import StageThread  # noqa: E402
from control_center.stage.scenes import art as A  # noqa: E402


class ArtCloseBudget(unittest.TestCase):
    def setUp(self):
        self.release = threading.Event()
        self.started = []
        self.lock = threading.Lock()

    def tearDown(self):
        self.release.set()

    def stuck(self, n):
        def fn():
            with self.lock:
                self.started.append(n)
            self.release.wait(10.0)            # a download that ignores the cancel flag
            return None
        return fn

    def test_close_with_stuck_workers_is_bounded(self):
        svc = A.ArtService(workers=3, fast_worker=False)
        for n in range(3):
            svc.add(A.Job(("stuck", n), (5,), self.stuck(n), owner="t", lane=A.LANE_ART))
        t_end = time.monotonic() + 5.0
        while len(self.started) < 3 and time.monotonic() < t_end:
            time.sleep(0.01)
        self.assertEqual(len(self.started), 3, "three workers run a stuck job")
        t0 = time.monotonic()
        joined = svc.close(0.5)
        first = time.monotonic() - t0
        self.assertFalse(joined)
        self.assertLess(first, 1.2, f"one shared deadline, not one per worker ({first:.2f} s)")
        self.assertGreaterEqual(first, 0.4)
        t0 = time.monotonic()
        svc.close(0.5)
        self.assertLess(time.monotonic() - t0, 0.1, "a second close does not wait again")
        self.release.set()
        t_end = time.monotonic() + 5.0
        while any(t.is_alive() for t in svc._threads) and time.monotonic() < t_end:
            time.sleep(0.01)
        self.assertTrue(svc.close(0.5))

    def test_idle_close_returns_at_once_and_reports_joined(self):
        svc = A.ArtService(workers=3)
        t0 = time.monotonic()
        self.assertTrue(svc.close(1.0))
        self.assertLess(time.monotonic() - t0, 0.5)


class StageThreadCloseOnce(unittest.TestCase):
    def test_second_close_does_not_wait_again(self):
        st = StageThread({}, start=False)
        gate = threading.Event()
        st._thread = threading.Thread(target=lambda: gate.wait(10.0), daemon=True)    # a busy stage thread
        st._thread.start()
        try:
            t0 = time.monotonic()
            self.assertFalse(st.close(0.3))
            self.assertGreaterEqual(time.monotonic() - t0, 0.25)
            self.assertTrue(st.mailbox.closed)
            t0 = time.monotonic()
            self.assertFalse(st.close(2.0))
            self.assertLess(time.monotonic() - t0, 0.1, "a second close only reports")
        finally:
            gate.set()
        st._thread.join(2.0)
        self.assertTrue(st.close(2.0))


if __name__ == "__main__":
    unittest.main()
