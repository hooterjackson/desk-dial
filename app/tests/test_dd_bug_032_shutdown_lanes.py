"""DD-BUG-032: quitting stops the running Sonos lane job at its next step (its own rollback runs)
and close() joins the lane workers within one bounded deadline, so the process that releases the
single-instance mutex no longer changes the queue."""
import threading
import time
import unittest

from cc5_support import Clock
from control_center.controller import Controller
from control_center.runtime import LaneStopped, Runtime, _join_executors
from control_center.simulation import SimulatedAppleMusic, SimulatedSonos, SimulatedWindows


class ShutdownStopsRunningJobTests(unittest.TestCase):
    STEPS = 100
    STEP_S = 0.02

    def make_runtime(self):
        runtime = Runtime(Controller(clock=Clock()), SimulatedSonos(), SimulatedAppleMusic(), SimulatedWindows())
        self.addCleanup(lambda: runtime.shutdown() if not runtime.closed else None)
        return runtime

    def submit_staging(self, runtime):
        """An exclusive job with STEPS staged inserts, each followed by between_steps(); an error
        takes the rollback path (like play_items' staging rollback)."""
        record = {"inserted": 0, "rolled_back": None, "error": None}
        started = threading.Event()

        def job(between_steps):
            try:
                for _ in range(self.STEPS):
                    time.sleep(self.STEP_S)
                    record["inserted"] += 1
                    started.set()
                    between_steps()
            except Exception as exc:
                record["error"] = exc
                record["rolled_back"] = record["inserted"]
                record["inserted"] = 0
                raise
            return "done"
        future = runtime.audio_lane.submit("play_items", job)
        self.assertTrue(started.wait(2.0))
        return future, record

    def lane_threads(self, runtime):
        return [t for t in threading.enumerate() if t.name.startswith("nanod-sonos") and t.is_alive()]

    def test_shutdown_stops_running_exclusive_job_at_next_step(self):
        runtime = self.make_runtime()
        future, record = self.submit_staging(runtime)
        queued = runtime.audio_lane.submit("play_next", lambda step: "never")
        at_stop = record["inserted"]
        begin = time.monotonic()
        runtime.close()
        self.assertLess(time.monotonic() - begin, 1.0, "close() waits only for the step in progress")
        self.assertIsInstance(future.exception(timeout=1.0), LaneStopped)
        self.assertIn("discarded", str(future.exception()))
        self.assertLessEqual(record["rolled_back"], at_stop + 1, "stopped within one step")
        self.assertEqual(record["inserted"], 0, "the job's own rollback ran")
        self.assertTrue(queued.cancelled())
        deadline = time.monotonic() + 0.5
        while self.lane_threads(runtime) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.lane_threads(runtime), [], "the lane worker is gone 0.5 s after close")

    def test_mode_switch_shutdown_does_not_block_but_still_stops_the_job(self):
        runtime = self.make_runtime()
        future, record = self.submit_staging(runtime)
        begin = time.monotonic()
        runtime.shutdown(close_device=False)
        self.assertLess(time.monotonic() - begin, 0.5, "no join on the Tk thread")
        self.assertIsInstance(future.exception(timeout=1.0), LaneStopped)
        self.assertLess(record["rolled_back"], self.STEPS)

    def test_a_job_submitted_after_stop_never_runs(self):
        runtime = self.make_runtime()
        runtime.audio_lane.stopping = True
        ran = []
        future = runtime.audio_lane.submit("state", lambda step: ran.append(1))
        runtime.audio_lane._drain()
        self.assertTrue(future.cancelled())
        self.assertEqual(ran, [])

    def test_bounded_join_reports_stragglers(self):
        runtime = self.make_runtime()
        release = threading.Event()
        runtime.library.submit(release.wait, 5.0)   # a job that never takes a step
        try:
            with self.assertLogs("control_center.runtime", level="WARNING") as logs:
                begin = time.monotonic()
                runtime.shutdown(join_timeout=0.2)
                self.assertLess(time.monotonic() - begin, 1.0, "one shared deadline")
            self.assertTrue(any("nanod-library" in line for line in logs.output))
        finally:
            release.set()

    def test_join_executors_skips_the_calling_thread_and_tolerates_fakes(self):
        class Fake:
            pass
        self.assertEqual(_join_executors([Fake()], 0.1), [])


if __name__ == "__main__":
    unittest.main()
