"""DD-BUG-032 (review): quitting stops only the lane kinds that have a safe stop (play_items and
play_next roll back their staging, seek and jump only drop confirmation polls). The companion
shuffle has no rollback, so a quit lets it run all its moves instead of leaving the upcoming
queue partly reordered."""
import threading
import time
import unittest
from concurrent.futures import Future

from cc5_support import Clock
from control_center.controller import Controller
from control_center.runtime import STOP_AT_STEP_KINDS, LaneStopped, Runtime
from control_center.simulation import SimulatedAppleMusic, SimulatedSonos, SimulatedWindows


class ShuffleFinishesOnQuitTests(unittest.TestCase):
    MOVES = 60          # the companion shuffle's bound
    STEP_S = 0.005

    def make_runtime(self):
        runtime = Runtime(Controller(clock=Clock()), SimulatedSonos(), SimulatedAppleMusic(), SimulatedWindows())
        self.addCleanup(lambda: runtime.shutdown() if not runtime.closed else None)
        return runtime

    def submit_moves(self, runtime, kind, moves):
        record = {"moved": 0, "error": None}
        started = threading.Event()

        def job(between_steps):
            try:
                for _ in range(moves):
                    time.sleep(self.STEP_S)
                    record["moved"] += 1
                    started.set()
                    between_steps()
            except Exception as exc:
                record["error"] = exc
                raise
            return "done"
        future = runtime.audio_lane.submit(kind, job)
        self.assertTrue(started.wait(2.0))
        return future, record

    def test_shuffle_reorder_is_not_a_stop_at_step_kind(self):
        self.assertNotIn("shuffle_reorder", STOP_AT_STEP_KINDS)
        self.assertEqual(STOP_AT_STEP_KINDS, frozenset(("play_items", "play_next", "seek", "jump")))

    def test_close_lets_a_running_shuffle_finish_every_move(self):
        runtime = self.make_runtime()
        future, record = self.submit_moves(runtime, "shuffle_reorder", self.MOVES)
        queued = runtime.audio_lane.submit("volume", lambda step: "never")
        runtime.close()
        self.assertEqual(future.result(timeout=2.0), "done")
        self.assertIsNone(record["error"])
        self.assertEqual(record["moved"], self.MOVES, "no partly reordered queue")
        self.assertTrue(queued.cancelled(), "queued jobs are still dropped")

    def test_shuffle_steps_after_stop_run_no_queued_job(self):
        lane = self.make_runtime().audio_lane
        ran, steps = [], []
        lane._jobs.append(("volume", lambda step: ran.append("volume"), Future()))
        gate = threading.Event()

        def running(between_steps):
            gate.wait(2.0)          # the shuffle is already running when the quit arrives
            between_steps()
            steps.append(1)
            return "done"
        future = Future()
        thread = threading.Thread(target=lane._run, args=("shuffle_reorder", running, future))
        thread.start()
        lane.stopping = True
        gate.set()
        thread.join(2.0)
        self.assertEqual(future.result(timeout=0), "done")
        self.assertEqual(steps, [1])
        self.assertEqual(ran, [], "a step after stop runs no queued job")

    def test_stop_at_step_kinds_still_stop(self):
        for kind in sorted(STOP_AT_STEP_KINDS):
            with self.subTest(kind=kind):
                runtime = self.make_runtime()
                future, record = self.submit_moves(runtime, kind, 400)
                runtime.close()
                self.assertIsInstance(future.exception(timeout=1.0), LaneStopped)
                self.assertLess(record["moved"], 400)


if __name__ == "__main__":
    unittest.main()
