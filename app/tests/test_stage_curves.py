"""Stage curves, twin and clock (DESKTOP_STAGE §4.6, §0.6; H1, H3, H7; G1-6, G1-7, G1-8). Headless."""
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center.stage import clock as CK  # noqa: E402
from control_center.stage import curves as CV  # noqa: E402
from control_center.stage import motion_table as MT  # noqa: E402

FREQ = 10_000_000


class CurveFitTests(unittest.TestCase):
    def test_h3_every_app_a_tuple_within_bound(self):
        """H3: every §7-§10 / §16 tuple at its kind's worst travel, float32 as DWM gets it."""
        bounds = {"offset": CV.OFFSET_BOUND_PX, "scale": CV.SCALE_BOUND_PX, "opacity": CV.OPACITY_BOUND}
        worst = {}
        for row in MT.APP_A:
            surface, element, kind, name, _legs = row
            ext = MT.H3_EXTREMES[kind]
            for _start, dur in MT.legs_of(row):
                r = CV.validate(name, dur / 1000.0, 1.0, 1.0 + ext["travel"], kind, ext["size"], samples=3000)
                err = r["max_err"] * (ext["size"] if kind == "scale" else 1.0)
                worst[kind] = max(worst.get(kind, 0.0), err)
                self.assertLessEqual(err, bounds[kind], f"{surface}.{element} {name} {dur} ms: {r}")
                self.assertLessEqual(r["segments"], CV.MAX_SEGMENTS)
        self.assertEqual(set(worst), {"offset", "scale", "opacity"})

    def test_small_travel_uses_few_segments(self):
        """G1-4: a small travel needs a looser fit, so fewer AddCubic calls."""
        small = CV.tween(0, FREQ, 0.92, 0.84, 0.3, "OUT", kind="opacity")
        large = CV.tween(0, FREQ, 0.0, 5960.0, 0.42, "OUT", kind="offset")
        self.assertLessEqual(len(small.legs[0].tab), 4)
        self.assertGreater(len(large.legs[0].tab), len(small.legs[0].tab))

    def test_tables_are_cached_and_bucketed_down(self):
        a = CV.table("OUT", 1e-4)
        b = CV.table("OUT", 1.2e-4)
        self.assertIs(a, b)
        self.assertLessEqual(a.tol, 1e-4)
        self.assertTrue(a.converged)

    def test_linear_is_exact(self):
        m = CV.tween(0, FREQ, 10.0, 490.0, 1.0, "LINEAR", kind="offset")
        segs, end = m.segments()
        self.assertEqual(len(segs), 1)
        for t in (0.0, 0.25, 0.5, 0.999):
            self.assertAlmostEqual(CV.eval_segments(segs, end, t, False), 10.0 + 480.0 * t, places=9)

    def test_h3_steps_emit_exactly_the_twin(self):
        """WP7a-R3 (H3 for the "instant" rows of §7.6 / §8.5): a step, alone or between legs, is
        emitted as holds and End with strictly increasing offsets, and DWM's evaluation of the
        emitted pieces equals the twin everywhere (a step has no fit error)."""
        cases = [CV.step(0, FREQ, 0.19, 0.0, 700.0),
                 CV.Motion(0, FREQ, [CV.Leg(0.0, 0.16, 1.0, 0.0, CV.table_for("OUT", "opacity", -1.0)),
                                     CV.Leg(0.19, 0.0, 0.0, 1.0, None)]),
                 CV.Motion(0, FREQ, [CV.Leg(0.19, 0.0, 1.0, 0.0, None),
                                     CV.Leg(0.19, 0.16, 0.0, 1.0, CV.table_for("OUT", "opacity", 1.0))]),
                 CV.Motion(0, FREQ, [CV.Leg(0.0, 0.2, 0.0, 50.0, CV.table_for("OUT", "offset", 50.0)),
                                     CV.Leg(0.2, 0.0, 50.0, 80.0, None),
                                     CV.Leg(0.3, 0.2, 80.0, 0.0, CV.table_for("IN", "offset", -80.0))])]
        for m in cases:
            segs, end = m.segments()
            offs = [s[0] for s in segs]
            self.assertEqual(offs, sorted(set(offs)), m)
            self.assertTrue(all(o < end[0] for o in offs))
            for k in range(0, 801):
                t = 0.8 * k / 800
                if any(abs(t - leg.start) < 1e-9 for leg in m.legs if leg.dur == 0.0):
                    continue                                     # the step instant itself
                want = m.value(int(round(t * FREQ)))
                got = CV.eval_segments(segs, end, t, emulate_f32=False)
                self.assertAlmostEqual(got, want, delta=1e-6)
        s = CV.step(0, FREQ, 0.19, 0.0, 700.0)
        self.assertEqual(s.segments(), ([(0.0, 0.0, 0.0, 0.0, 0.0)], (0.19, 700.0)))
        self.assertEqual((s.value(1_899_999), s.value(1_900_000)), (0.0, 700.0))
        self.assertFalse(s.moving(1_000_000))
        with self.assertRaises(ValueError):
            CV.Leg(0.0, -0.1, 0.0, 1.0, None)
        with self.assertRaises(ValueError):
            CV.Leg(0.0, 0.1, 0.0, 1.0, None)                     # a curve leg needs its table

    def test_prewarmer_builds_in_small_steps(self):
        """WP7a-R4: the warm-up runs in idle chunks (at least one table per step), not at once."""
        keys = [("SPR", lv) for lv in (-12, -11, -10)]
        saved = {k: CV._TABLES.pop(k) for k in keys if k in CV._TABLES}
        try:
            ticks = iter(range(100000))
            p = CV.Prewarmer(names=("SPR",), levels=(-12, -11, -10), clock=lambda: next(ticks))
            self.assertFalse(p.done)
            self.assertTrue(p.step(budget_s=0.0))                # one trial piece, then yield
            self.assertEqual(p.built, 0)
            while p.step(budget_s=0.0):
                pass
            self.assertTrue(p.done)
            self.assertEqual(p.built, 3)
            self.assertGreater(p.steps, 30)                      # a table is many small steps, not one
            self.assertFalse(p.step())
            for k in keys:                                       # the same fit as a direct build
                direct = CV.SegTable(k[0], 2.0 ** k[1])
                self.assertEqual(CV._TABLES[k].rows, direct.rows)
                self.assertEqual(CV._TABLES[k].max_err, direct.max_err)
                self.assertTrue(CV._TABLES[k].converged)
            again = CV.Prewarmer(names=("SPR",), levels=(-12, -11, -10))
            self.assertFalse(again.step())                       # already built: free
            self.assertEqual(again.built, 0)
            self.assertEqual(CV.prewarm(names=("SPR",), levels=(-12, -11, -10)), 0)
            lazy = CV.Prewarmer(names=("SPR",), levels=(-12,), clock=lambda: next(ticks))
            CV._TABLES.pop(keys[0])
            lazy.step(budget_s=0.0)                              # a fit in progress ...
            t = CV.table_for("SPR", "opacity", 0.0018 * 0.9 / 2.0 ** -12)   # ... while the hot path builds it
            while lazy.step(budget_s=0.0):
                pass
            self.assertIs(CV._TABLES[keys[0]], t)                # the lazy table is kept
            self.assertEqual(lazy.built, 0)
        finally:
            for k, t in saved.items():
                CV._TABLES[k] = t

    def test_segments_match_twin(self):
        m = CV.tween(1000, FREQ, 100.0, 700.0, 0.42, "OUT", delay=0.09)
        segs, end = m.segments()
        self.assertEqual(segs[0], (0.0, 100.0, 0.0, 0.0, 0.0))     # the leading hold (§4.6.4)
        for k in range(0, 60):
            t = 0.51 * k / 59
            twin = m.value(1000 + int(round(t * FREQ)))
            dwm = CV.eval_segments(segs, end, round(t * FREQ) / FREQ, False)
            self.assertAlmostEqual(twin, dwm, places=6)


class MultiLegTests(unittest.TestCase):
    def test_end_bump_two_legs(self):
        m = CV.legs_motion(0, FREQ, 0.0, [(0.0, -28.0, 0.16, "OUT"), (0.16, 0.0, 0.16, "OUT")])
        self.assertAlmostEqual(m.value(int(0.16 * FREQ)), -28.0, places=9)
        self.assertAlmostEqual(m.value(int(0.32 * FREQ)), 0.0, places=9)
        self.assertEqual(m.end_tick, int(0.32 * FREQ))
        self.assertLess(m.value(int(0.08 * FREQ)), -20.0)

    def test_heart_holds_between_legs(self):
        m = CV.legs_motion(0, FREQ, 0.4, [(0.0, 1.5, 0.38, "SPR"), (0.42, 1.0, 0.38, "SPR")], kind="scale", size=40)
        self.assertAlmostEqual(m.value(int(0.40 * FREQ)), 1.5, places=9)       # held 380 -> 420 ms
        segs, end = m.segments()
        holds = [s for s in segs if s[2:] == (0.0, 0.0, 0.0)]
        self.assertTrue(any(abs(s[0] - 0.38) < 1e-12 and abs(s[1] - 1.5) < 1e-12 for s in holds))
        self.assertEqual(end, (0.80, 1.0))
        self.assertGreater(max(m.value(int(t * FREQ / 1000)) for t in range(0, 380)), 1.5)   # SPR overshoots

    def test_overlapping_legs_rejected(self):
        with self.assertRaises(ValueError):
            CV.legs_motion(0, FREQ, 0.0, [(0.0, 1.0, 0.2, "OUT"), (0.1, 0.0, 0.2, "OUT")])


class RetargetTests(unittest.TestCase):
    def test_h7_continuity_every_kind(self):
        """H7: just before and just after a retarget at t1 agree to 1e-6, for every kind."""
        for kind, v0, step, size in (("offset", 0.0, 600.0, 1.0), ("scale", 0.4, 0.2, 680.0),
                                     ("opacity", 0.0, 0.3, 1.0)):
            m = CV.tween(0, FREQ, v0, v0 + step, 0.42, "OUT", kind=kind, size=size)
            target = v0 + step
            t = 0
            for i in range(40):
                t += int(0.05 * FREQ)
                before = m.value(t)
                target += step if i % 3 else -step
                new = CV.tween(t, FREQ, before, target, 0.42, "OUT", kind=kind, size=size)
                self.assertLessEqual(abs(new.value(t) - before), 1e-6, kind)
                self.assertLessEqual(abs(new.value(t + 1) - m.value(t + 1)), abs(step) * 1e-4 + 1e-6, kind)
                segs, end = new.segments()
                self.assertLessEqual(abs(CV.eval_segments(segs, end, 0.0, True) - before),
                                     max(1e-6, abs(before) * 1.2e-7), kind)
                m = new

    def test_h1_frame_rate_independence(self):
        """H1: sampling at 60, 120, 144, 240 and 360 Hz gives the same value at the same t, and a
        skipped vblank resumes on the curve (the twin is a function of time only)."""
        m = CV.legs_motion(0, FREQ, 0.0, [(0.0, 900.0, 0.42, "OUT"), (0.5, 100.0, 0.3, "IN")])
        shared = [int(k * FREQ / 60) for k in range(0, 60)]
        ref = [m.value(t) for t in shared]
        for hz in (120, 144, 240, 360):
            seen = {int(k * FREQ / hz): m.value(int(k * FREQ / hz)) for k in range(0, hz)}
            for t, v in zip(shared, ref):
                if t in seen:
                    self.assertEqual(seen[t], v)
        skipped = [m.value(int(k * FREQ / 240)) for k in (10, 13)]      # 2 vblanks skipped
        self.assertEqual(skipped[1], m.value(int(13 * FREQ / 240)))

    def test_skip_reexpands_the_passed_part(self):
        """§4.6.5 item 7 fallback: shifting the time origin keeps the curve."""
        m = CV.tween(0, FREQ, 0.0, 800.0, 0.44, "OUT", delay=0.045)
        for skip in (0.01, 0.045, 0.1, 0.3):
            segs, end = m.segments(skip)
            self.assertEqual(segs[0][0], 0.0)
            for w in (0.0, 0.02, 0.1, 0.2):
                if skip + w >= m.end_s:
                    continue
                want = m.value(int(round((skip + w) * FREQ)))
                self.assertAlmostEqual(CV.eval_segments(segs, end, w, False), want, delta=1e-3)
        segs, end = m.segments(1.0)
        self.assertEqual(end[1], 800.0)


class ClockTests(unittest.TestCase):
    def test_t1_rule_fixed_margin(self):
        P = FREQ / 240.0
        margin = CK.T1_MARGIN_S * FREQ
        now = 1_000_000
        self.assertEqual(CK.t1_for(now + 30_000, now, P, margin), now + 30_000)          # 3 ms away: kept
        self.assertEqual(CK.t1_for(now + 10_000, now, P, margin), now + 10_000 + int(round(P)))   # 1 ms: + P
        stale = CK.t1_for(now - 5 * FREQ, now, P, margin)                                # stale estimate
        self.assertGreaterEqual(stale - now, margin)
        self.assertLess(stale - now, margin + P + 1)

    def test_adaptive_margin_capped_at_one_period(self):
        self.assertEqual(CK.adaptive_margin(0.0002, 0.0041667), CK.T1_MARGIN_S)
        self.assertAlmostEqual(CK.adaptive_margin(0.015, 0.0041667), 0.0041667)

    def test_begin_mode_follows_time_frequency(self):
        """G1-8: absolute begin times only when timeFrequency == QPF."""
        fake = [0]
        c = CK.StageClock(10_000_000, 10_000_000, qpc=lambda: fake[0], perf=lambda: fake[0] / 1e7)
        self.assertEqual(c.begin_mode, CK.BEGIN_ABSOLUTE)
        c2 = CK.StageClock(10_000_000, 24_000_000, qpc=lambda: fake[0], perf=lambda: fake[0] / 2.4e7)
        self.assertEqual(c2.begin_mode, CK.BEGIN_HOLD)
        fake[0] = 48_000_000
        self.assertEqual(c2.now(), 20_000_000)                     # converted into timeFrequency ticks

    def test_t0_conversion_uses_calibrated_offset(self):
        state = {"q": 123_456_789}
        offset_s = 7.25
        c = CK.StageClock(10_000_000, 10_000_000, qpc=lambda: state["q"], perf=lambda: state["q"] / 1e7 - offset_s)
        self.assertAlmostEqual(c.perf_offset_s, offset_s, places=6)
        t_perf = state["q"] / 1e7 - offset_s
        self.assertEqual(c.from_perf(t_perf), state["q"])
        self.assertEqual(c.uint32_ms(12_345_678), 1234)

    def test_real_perf_counter_is_qpc(self):
        """On this platform perf_counter reads QPC: the calibrated offset is ~0."""
        try:
            from control_center.stage import win32
        except ImportError:
            self.skipTest("Windows only")
        c = CK.StageClock(win32.qpf(), win32.qpf(), qpc=win32.qpc)
        self.assertEqual(c.begin_mode, CK.BEGIN_ABSOLUTE)
        import time
        t = time.perf_counter()
        self.assertLess(abs(c.from_perf(t) - c.now()), c.freq * 0.005)

    def test_next_frame_after(self):
        P = FREQ / 240.0
        self.assertEqual(CK.next_frame_after(0, 1, P), int(round(P)))
        self.assertEqual(CK.next_frame_after(0, int(P) + 1, P), int(round(2 * P)))
        self.assertTrue(math.isclose(CK.period_ticks(240, 1, FREQ), P))


if __name__ == "__main__":
    unittest.main()
