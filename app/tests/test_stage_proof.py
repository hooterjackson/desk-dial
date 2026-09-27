"""Supervised-proof measurement helpers on synthetic data (DESKTOP_STAGE §6.1, §19; G1 report §6
item 11). Headless."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center.stage import curves as CV  # noqa: E402
from control_center.stage import frames as FR  # noqa: E402
from control_center.stage import proof as PF  # noqa: E402

FREQ = 10_000_000
P = FREQ / 240.0


def comps(n, t0=1_000_000_000):
    """n compositions, one per vblank: start 0.6 P before the vblank, target = the vblank."""
    out = []
    for i in range(n):
        vb = int(round(t0 + i * P))
        out.append(FR.TargetFrame(100 + i, vb + 700, vb, i, i, vb - int(0.6 * P), vb))
    return out


class PickupTests(unittest.TestCase):
    def test_classes(self):
        fr = comps(100)
        t0 = fr[0].target_time
        vb = lambda i: int(round(t0 + i * P))          # noqa: E731
        events = [{"t1": vb(10), "done": vb(8)},                    # next start after done targets vb 9: early
                  {"t1": vb(20), "done": vb(19) - int(0.7 * P)},    # the composition for vb 19 starts later: early
                  {"t1": vb(30), "done": vb(29) - int(0.5 * P)},    # picks up the vb 30 composition: at t1
                  {"t1": vb(40), "done": vb(40) - int(0.5 * P)},    # misses it: t1 + P
                  {"t1": vb(50), "done": vb(52)},                   # later
                  {"t1": vb(99), "done": vb(99) + 10}]              # nothing after: unknown
        ks, cls = PF.pickup_classes(fr, events, P)
        self.assertEqual(ks, [-1, -1, 0, 1, 3, None])
        self.assertEqual((cls["early"], cls["at_t1"], cls["t1_plus_P"], cls["later"], cls["known"]), (2, 1, 1, 1, 5))


class QuietTests(unittest.TestCase):
    def test_quiet_ratio(self):
        fr = comps(240)
        a, b = fr[0].completed_time, fr[-1].completed_time
        busy = PF.quiet_ratio(fr, [(a, b)], P)
        self.assertFalse(busy["quiet"])
        sparse = [f for i, f in enumerate(fr) if i % 40 == 0]
        self.assertTrue(PF.quiet_ratio(sparse, [(a, b)], P)["quiet"])
        self.assertIsNone(PF.quiet_ratio(fr, [], P)["quiet"])


class WitnessTests(unittest.TestCase):
    def test_run_centroid(self):
        row = [16] * 100
        for x in range(40, 56):
            row[x] = 250
        self.assertEqual(PF.run_centroid(row), 47.5)
        self.assertIsNone(PF.run_centroid([16] * 100))
        row2 = [16] * 100
        for x in range(10, 14):                                     # too short: not the witness
            row2[x] = 250
        self.assertIsNone(PF.run_centroid(row2))

    def test_judge_against_the_twin(self):
        m = CV.tween(0, FREQ, 700.0, 700.0 + 560.0 * 4, 4.0, "LINEAR")
        rng = PF.twin_range_fn([(0, m)])
        good = [(int(t * FREQ / 100), int(0.004 * FREQ), m.value(int(t * FREQ / 100))) for t in range(1, 300)]
        res = PF.witness_judge(good, rng, P)
        self.assertTrue(res["pass"], res)
        bad = good[:-1] + [(good[-1][0], good[-1][1], good[-1][2] + 20.0)]
        self.assertFalse(PF.witness_judge(bad, rng, P)["pass"])
        hidden = [(s[0], s[1], None) for s in good[:20]] + good[20:]
        self.assertFalse(PF.witness_judge(hidden, rng, P)["pass"])            # under 95 % visible
        windowed = PF.witness_judge(bad, rng, P, windows=[(0, good[100][0])])
        self.assertTrue(windowed["pass"])
        self.assertEqual(windowed["samples"], 101)

    def test_twin_range_uses_the_function_in_force(self):
        a = CV.Const(10.0)
        b = CV.tween(1000, FREQ, 10.0, 90.0, 0.1, "LINEAR")
        rng = PF.twin_range_fn([(0, a), (1000, b)])
        self.assertEqual(rng(0, 900), (10.0, 10.0))
        lo, hi = rng(0, 1000 + FREQ)
        self.assertEqual((lo, hi), (10.0, 90.0))


class MiscTests(unittest.TestCase):
    def test_history_probe_and_steps(self):
        fr = comps(50)
        gone = {100, 101}
        out = PF.history_probe(149, lambda fid: False if fid in gone else True, [("250ms", 100), ("100ms", 130)])
        self.assertEqual(out["250ms"], {"age_ids": 49, "answered": False})
        self.assertTrue(out["100ms"]["answered"])
        steps = PF.vblank_steps([f for i, f in enumerate(fr) if i != 7], fr[0].completed_time, fr[-1].completed_time, P)
        self.assertEqual(max(steps), 2)
        self.assertEqual(len(steps), 48)


if __name__ == "__main__":
    unittest.main()
