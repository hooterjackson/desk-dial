"""FrameStats, the compositor harvest, the compositor-clock wait and the pacer (DESKTOP_STAGE §5,
§6.1-§6.3; G1-1, G1-2, G1-3) on synthetic data. Headless."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center.stage import frames as FR  # noqa: E402

FREQ = 10_000_000
P = FREQ / 240.0


def stream(n, drop=(), fid0=1000, t0=5_000_000_000, id_step=1, pc0=100):
    """n vblanks; one composed frame per vblank on our target (completedStats.time on the grid,
    presentTime a little after it), except the vblanks in ``drop``."""
    out = []
    pc = pc0
    for i in range(n):
        if i in drop:
            continue
        pc += 1
        t = int(round(t0 + i * P))
        out.append(FR.TargetFrame(fid0 + i * id_step, t + int(0.17 * P), t, pc, pc))
    return out


class EpisodeTests(unittest.TestCase):
    def test_perfect_240(self):
        fr = stream(240)
        ep = FR.episode_from_frames(fr, [], fr[0].completed_time, fr[-1].completed_time, P, FREQ, rate_hz=240.0)
        self.assertEqual(ep["frames"], 240)
        self.assertEqual(ep["frames_by_counter"], 240)
        self.assertEqual(ep["missed"], 0)
        self.assertEqual(ep["step_max"], 1)
        self.assertAlmostEqual(ep["interval_P"]["p95"], 1.0, places=3)
        self.assertTrue(FR.judge_stage(ep, 240.0, [0.9, 1.1])["pass"])

    def test_missed_frames_counted(self):
        fr = stream(240, drop={50, 51, 120})
        ep = FR.episode_from_frames(fr, [], fr[0].completed_time, fr[-1].completed_time, P, FREQ, rate_hz=240.0)
        self.assertEqual(ep["missed"], 2)
        self.assertEqual(ep["double_missed"], 1)
        self.assertEqual(ep["step_max"], 3)
        self.assertFalse(FR.judge_stage(ep, 240.0)["pass"])

    def test_lost_ids_are_unknown_not_missed(self):
        """G1-3 (WP7a-R2): an interval that spans a lost id is unknown: never missed, never in
        the interval statistics."""
        fr = stream(1000, drop={500})
        ep = FR.episode_from_frames(fr, [(1500, 1500)], fr[0].completed_time, fr[-1].completed_time, P, FREQ,
                                    rate_hz=240.0)
        self.assertEqual(ep["unknown"], 1)
        self.assertEqual(ep["unknown_gaps"], 1)
        self.assertTrue(ep["valid"])
        self.assertEqual(ep["missed"], 0)
        self.assertEqual(ep["double_missed"], 0)
        self.assertLessEqual(ep["interval_P"]["max"], 1.0 + 1e-3)
        self.assertEqual(ep["step_max"], 1)
        self.assertEqual(ep["interval_ms"]["n"], 997)                 # 998 pairs, one of them unknown
        self.assertTrue(FR.judge_stage(ep, 240.0)["pass"])
        many = [(1100 + i, 1100 + i) for i in range(0, 40)]
        ep2 = FR.episode_from_frames(fr, many, fr[0].completed_time, fr[-1].completed_time, P, FREQ, rate_hz=240.0)
        self.assertFalse(ep2["valid"])                                 # > 0.5 % unknown
        self.assertIsNone(FR.judge_stage(ep2, 240.0)["pass"])

    def test_adjacent_lost_ids_keep_a_valid_episode_passing(self):
        """Two adjacent lost ids (0.2 %, valid): before the fix this was missed 1, double 1,
        max 3.0 P and a false §6.3 failure."""
        fr = stream(1000, drop={500, 501})
        ep = FR.episode_from_frames(fr, [(1500, 1501)], fr[0].completed_time, fr[-1].completed_time, P, FREQ,
                                    rate_hz=240.0)
        self.assertTrue(ep["valid"])
        self.assertEqual((ep["missed"], ep["double_missed"], ep["unknown"], ep["unknown_gaps"]), (0, 0, 2, 1))
        self.assertLessEqual(ep["interval_P"]["max"], 1.0 + 1e-3)
        v = FR.judge_stage(ep, 240.0, [0.5] * 20)
        self.assertTrue(v["pass"], v)

    def test_isolated_lost_ids_are_not_missed(self):
        drop = {100 + 250 * i for i in range(12)}                      # 12 in 3000 (0.4 %, valid)
        fr = stream(3000, drop=drop)
        unknown = [(1000 + d, 1000 + d) for d in sorted(drop)]
        ep = FR.episode_from_frames(fr, unknown, fr[0].completed_time, fr[-1].completed_time, P, FREQ, rate_hz=240.0)
        self.assertTrue(ep["valid"])
        self.assertEqual((ep["missed"], ep["unknown_gaps"]), (0, 12))

    def test_a_real_miss_next_to_a_lost_id_still_counts(self):
        fr = stream(1000, drop={200, 500})                             # 200 dropped (missed), 500 lost (unknown)
        ep = FR.episode_from_frames(fr, [(1500, 1500)], fr[0].completed_time, fr[-1].completed_time, P, FREQ,
                                    rate_hz=240.0)
        self.assertEqual((ep["missed"], ep["unknown_gaps"]), (1, 1))
        self.assertEqual(ep["step_max"], 2)

    def test_counts_by_counter_not_ids(self):
        """G1-3: ids can race (display asleep); frames come from the running counters."""
        fr = stream(240, id_step=19)
        ep = FR.episode_from_frames(fr, [], fr[0].completed_time, fr[-1].completed_time, P, FREQ, rate_hz=240.0)
        self.assertEqual(ep["frames_by_counter"], 240)
        self.assertEqual(ep["frames"], 240)

    def test_work_budget_in_the_verdict(self):
        fr = stream(240)
        ep = FR.episode_from_frames(fr, [], fr[0].completed_time, fr[-1].completed_time, P, FREQ, rate_hz=240.0)
        v = FR.judge_stage(ep, 240.0, [1.0] * 19 + [2.0] * 2)
        self.assertFalse(v["checks"]["work_p95"])


class FakeReader:
    def __init__(self, frames):
        self.frames = {f.id: f for f in frames}
        self.cur = None
        self.gone = set()
        self.other = set()

    def completed_id(self):
        return self.cur

    def frame(self, fid):
        if fid in self.gone:
            return False
        if fid in self.other:
            return None
        return self.frames.get(fid)


class HarvestTests(unittest.TestCase):
    def test_walks_ids_and_marks_unknown(self):
        fr = stream(100)
        rd = FakeReader(fr)
        rd.cur = 999
        h = FR.CompositorHarvest(rd)
        h.start()
        rd.cur = 1049
        rd.gone = {1010, 1011}
        rd.other = {1020}
        self.assertEqual(h.harvest(), 47)
        self.assertEqual(h.unknown, [(1010, 1010), (1011, 1011)])
        rd.cur = 1099
        h.harvest()
        frames, unknown = h.take()
        self.assertEqual(len(frames), 97)
        self.assertEqual(h.frames, [])

    def test_display_off_skips_the_walk(self):
        rd = FakeReader(stream(10))
        rd.cur = 999
        h = FR.CompositorHarvest(rd)
        h.start()
        rd.cur = 5999
        self.assertEqual(h.harvest(display_on=False), 0)
        self.assertEqual(h.unknown, [(1000, 5999)])
        self.assertEqual(h.skipped_display_off, 5000)

    def test_max_walk(self):
        rd = FakeReader(stream(10))
        rd.cur = 0
        h = FR.CompositorHarvest(rd, max_walk=100)
        h.start()
        rd.cur = 1000
        h.harvest()
        self.assertEqual(h.unknown[0], (1, 900))


class FrameStatsTests(unittest.TestCase):
    def test_last_worst_totals_and_rate_limited_log(self):
        logs = []
        fs = FR.FrameStats(log=logs.append)
        good = {"frames": 240, "missed": 0, "double_missed": 0, "interval_P": {"max": 1.0}}
        bad = {"frames": 200, "missed": 5, "double_missed": 1, "interval_P": {"max": 3.1}}
        fs.record("explorer", "turn", good, {"pass": True, "checks": {}}, now_s=0.0)
        fs.record("explorer", "turn", bad, {"pass": False, "checks": {"fps": False}}, now_s=1.0)
        fs.record("explorer", "turn", bad, {"pass": False, "checks": {"fps": False}}, now_s=10.0)
        fs.record("explorer", "turn", good, {"pass": True, "checks": {}}, now_s=40.0)
        fs.record("explorer", "open", bad, {"pass": False, "checks": {}}, now_s=41.5)
        m = fs.metrics()["explorer"]
        self.assertEqual(m["last"]["kind"], "open")
        self.assertEqual(m["worst"]["missed"], 5)
        self.assertEqual(m["totals"]["turn"]["episodes"], 4)
        self.assertEqual(m["totals"]["turn"]["failed"], 2)
        self.assertEqual(len(logs), 2)                   # at most one per 30 s per surface

    def test_metrics_are_detached_copies(self):
        """WP7a-R9: the Tk thread gets a snapshot, never the dicts the stage thread mutates."""
        fs = FR.FrameStats()
        fs.record("explorer", "turn", {"frames": 240, "missed": 0, "interval_P": {"max": 1.0}}, {"pass": True})
        snap = fs.metrics()
        snap["explorer"]["totals"]["turn"]["episodes"] = 99
        snap["explorer"]["last"]["interval_P"]["max"] = 9.0
        fs.record("explorer", "open", {"frames": 10})
        fs.record("upnext", "turn", {"frames": 10})
        m = fs.metrics()
        self.assertEqual(m["explorer"]["totals"]["turn"]["episodes"], 1)
        self.assertEqual(m["explorer"]["worst"]["interval_P"]["max"], 1.0)
        self.assertNotIn("open", snap["explorer"]["totals"])            # the snapshot did not change
        self.assertNotIn("upnext", snap)

    def test_metrics_while_another_thread_records(self):
        import json
        import threading
        fs = FR.FrameStats()
        stop = threading.Event()
        errors = []

        def writer():
            i = 0
            while not stop.is_set() and i < 20000:
                fs.record(f"s{i % 50}", f"k{i % 7}", {"frames": 1, "missed": 0})
                i += 1

        th = threading.Thread(target=writer)
        th.start()
        try:
            for _ in range(300):
                try:
                    json.dumps(fs.metrics(), indent=2)
                except RuntimeError as exc:                             # dictionary changed size
                    errors.append(exc)
        finally:
            stop.set()
            th.join(10)
        self.assertEqual(errors, [])


class ClockWaitTests(unittest.TestCase):
    def test_tick_handle_timeout(self):
        codes = [2, 0, 0x102]
        cw = FR.ClockWait(lambda n, h, t: codes.pop(0), lambda h, s: None)
        self.assertEqual(cw.wait((1, 2)), (FR.TICK, None))
        self.assertEqual(cw.wait((1, 2)), (FR.HANDLE, 0))
        self.assertEqual(cw.wait((1, 2)), (FR.TIMEOUT, None))

    def test_sleeping_display_falls_back_to_one_period_timer(self):
        """G1-2: 0xC01E0006 returns at once; the loop must wait one P on the timer, not spin."""
        timer = []
        cw = FR.ClockWait(lambda n, h, t: 0xC01E0006, lambda h, s: timer.append(s) or None,
                          period_s=lambda: 1 / 240)
        for _ in range(5):
            self.assertEqual(cw.wait(()), (FR.NO_CLOCK, None))
        self.assertEqual(len(timer), 5)
        self.assertAlmostEqual(timer[0], 1 / 240)
        self.assertEqual(cw.counts["no_clock"], 5)

    def test_display_off_stops_without_calling_the_clock(self):
        called = []
        cw = FR.ClockWait(lambda n, h, t: called.append(1) or 0, lambda h, s: None, display_on=lambda: False)
        self.assertEqual(cw.wait(()), (FR.DISPLAY_OFF, None))
        self.assertEqual(called, [])

    def test_missing_export_uses_flush_then_timer(self):
        cw = FR.ClockWait(None, lambda h, s: 0, flush=lambda: 0)
        self.assertEqual(cw.wait((5,)), (FR.TICK, None))
        cw2 = FR.ClockWait(None, lambda h, s: 0, flush=lambda: -1)
        self.assertEqual(cw2.wait((5,)), (FR.HANDLE, 0))


class PacerTests(unittest.TestCase):
    def test_predicted_display_time(self):
        pc = FR.Pacer(FREQ)
        vb = 1_000_000_000
        t = pc.target(vb + 100, vb, P)
        self.assertEqual(t, int(round(vb + P)))
        for i in range(50):
            pc.frame_done(vb + i * int(P), 0, 0.6 * P, P)
        self.assertEqual(pc.cadence, 1)
        t2 = pc.target(vb + 100, vb, P)
        self.assertGreaterEqual(t2 - (vb + 100), 0.6 * P - 1)

    def test_lock_and_unlock_with_hysteresis(self):
        pc = FR.Pacer(FREQ)
        t = 0
        for _ in range(30):
            t += int(P)
            pc.frame_done(t, 0, 0.9 * P, P)
        self.assertEqual(pc.cadence, 2)
        self.assertEqual(pc.switches, 1)
        for _ in range(60):                               # 0.25 s below 0.6 P: still locked (window keeps old)
            t += int(2 * P)
            pc.frame_done(t, 0, 0.3 * P, P)
        self.assertEqual(pc.cadence, 2)
        for _ in range(200):
            t += int(2 * P)
            pc.frame_done(t, 0, 0.3 * P, P)
        self.assertEqual(pc.cadence, 1)
        self.assertEqual(pc.switches, 2)
        t_target = pc.target(t, t, P)                     # work p95 0.3 P: the next vblank, cadence 1
        self.assertEqual(t_target, int(round(t + P)))

    def test_locked_target_is_two_periods_ahead(self):
        pc = FR.Pacer(FREQ)
        pc.cadence = 2
        vb = 10 * int(P)
        self.assertGreaterEqual(pc.target(vb + 1, vb, P) - (vb + 1), 2 * P - 2)

    def test_judge_wake(self):
        pc = FR.Pacer(FREQ)
        self.assertTrue(pc.judge_wake(0, P))
        self.assertFalse(pc.judge_wake(int(0.2 * P), P))
        self.assertTrue(pc.judge_wake(int(1.2 * P), P))
        self.assertEqual(pc.late_wakes, 1)


if __name__ == "__main__":
    unittest.main()
