"""Stage tree and animation builder on the fake device (DESKTOP_STAGE §4.4, §4.6.4-§4.6.7; G1-4,
G1-7, G1-8). Headless: no window, no GPU."""
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center.stage import clock as CK  # noqa: E402
from control_center.stage import com  # noqa: E402
from control_center.stage import curves as CV  # noqa: E402
from control_center.stage import fake as F  # noqa: E402
from control_center.stage.engine import StageCore  # noqa: E402
from control_center.stage.tree import (LAYER, LINEAR, MULTIPLY, OPACITY_EFFECT_GROUP, SOFT, Tree)  # noqa: E402


def make(time_frequency=None, qpf=None):
    clk = F.FakeClock()
    dev = F.FakeDevice(clk, time_frequency=time_frequency)
    clock = CK.StageClock(dev.time_frequency, qpf or dev.time_frequency, qpc=clk, perf=clk.perf)
    return clk, dev, StageCore(dev, clock, monotonic=clk.perf)


class TreeTests(unittest.TestCase):
    def test_root_is_linear_soft_layer(self):
        _clk, dev, _core = make()
        tree = Tree(dev)
        root = tree.root()
        props = dev.obj(root.ptr)["props"]
        self.assertEqual((props["interp"], props["border"], props["opacity_mode"]), (LINEAR, SOFT, LAYER))
        self.assertEqual(tree.mode_calls, [("interp", LINEAR), ("border", SOFT), ("opacity", LAYER)])

    def test_nearest_and_hard_are_refused(self):
        _clk, dev, _core = make()
        tree = Tree(dev)
        v = tree.visual("v")
        with self.assertRaises(AssertionError):
            tree.set_interp(v, com.DCOMPOSITION_BITMAP_INTERPOLATION_MODE_NEAREST_NEIGHBOR)
        with self.assertRaises(AssertionError):
            tree.set_border(v, com.DCOMPOSITION_BORDER_MODE_HARD)
        self.assertEqual(dev.violations, [])

    def test_containers_layer_or_multiply(self):
        _clk, dev, _core = make()
        tree = Tree(dev)
        a = tree.container("cards", overlap=True)
        b = tree.container("rows", overlap=False)
        self.assertEqual(dev.obj(a.ptr)["props"]["opacity_mode"], LAYER)
        self.assertEqual(dev.obj(b.ptr)["props"]["opacity_mode"], MULTIPLY)

    def test_add_positions_and_reorder_minimal(self):
        _clk, dev, _core = make()
        tree = Tree(dev)
        parent = tree.visual("p")
        kids = [tree.visual(f"k{i}") for i in range(12)]
        for k in kids:
            tree.add(parent, k)
        self.assertEqual(dev.obj(parent.ptr)["children"], [k.ptr for k in kids])
        rnd = random.Random(3)
        for trial in range(40):
            order = list(parent.children)
            if trial % 2:
                i, j = rnd.randrange(12), rnd.randrange(12)       # a small change: few moves
                order[i], order[j] = order[j], order[i]
            else:
                rnd.shuffle(order)
            before = tree.calls
            n = tree.reorder(parent, order)
            self.assertEqual(n, tree.calls - before)
            self.assertEqual(dev.obj(parent.ptr)["children"], [v.ptr for v in order])
            self.assertEqual(parent.children, order)
            self.assertLessEqual(n, 13)
        self.assertEqual(tree.reorder(parent, list(parent.children)), 0)
        order = list(parent.children)
        order.insert(0, order.pop())                                  # one card moves: 2 calls
        self.assertEqual(tree.reorder(parent, order), 2)

    def test_add_above_below_back(self):
        _clk, dev, _core = make()
        tree = Tree(dev)
        p = tree.visual("p")
        a, b, c, d = (tree.visual(n) for n in "abcd")
        tree.add(p, a)
        tree.add(p, b, back=True)
        tree.add(p, c, above=b)
        tree.add(p, d, below=a)
        self.assertEqual(dev.obj(p.ptr)["children"], [b.ptr, c.ptr, d.ptr, a.ptr])
        self.assertEqual(p.children, [b, c, d, a])

    def test_rest_offsets_snap_to_pixels(self):
        _clk, dev, _core = make()
        tree = Tree(dev)
        v = tree.visual("v")
        tree.offset(v, 10.4, 20.6)
        props = dev.obj(v.ptr)["props"]
        self.assertEqual((props["offset_x"], props["offset_y"]), (10.0, 21.0))

    def test_scale_binds_x_and_y_to_one_animation(self):
        clk, dev, core = make()
        tree = Tree(dev)
        v = tree.visual("v")
        st = tree.scale_transform(v, 340, 340)
        s = tree.scale(st, 680, 1.0)
        b = core.batch()
        b.to(s, 0.6, 420)
        b.commit()
        ax = dev.prop_anim[(st, "scale_x")]
        ay = dev.prop_anim[(st, "scale_y")]
        self.assertEqual(ax, ay)
        self.assertIn(ax, s.pool)

    def test_effect_group_opacity_path(self):
        clk, dev, core = make()
        tree = Tree(dev, OPACITY_EFFECT_GROUP)
        v = tree.visual("v", opacity=True)
        o = tree.opacity(v, 0.0)
        self.assertTrue(v.effect)
        self.assertEqual(dev.obj(v.ptr)["props"]["effect"], v.effect)
        b = core.batch()
        b.to(o, 1.0, 340)
        b.commit()
        self.assertIn(dev.prop_anim[(v.effect, "opacity")], o.pool)

    def test_release_all_releases_every_object_once(self):
        _clk, dev, core = make()
        tree = Tree(dev)
        root = tree.root()
        tree.opacity(root)
        v = tree.visual("v")
        tree.scale_group(v, ((1, 1), (2, 2)))
        tree.offset_x(v)
        before = dev.alive()
        n = tree.release_all()
        self.assertGreater(n, 0)
        self.assertEqual(dev.alive(), before - n)
        self.assertEqual(dev.violations, [])


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.clk, self.dev, self.core = make()
        self.tree = Tree(self.dev)
        self.v = self.tree.visual("card", opacity=True)
        self.x = self.tree.offset_x(self.v, 100.0)
        self.o = self.tree.opacity(self.v, 0.0)

    def anim_of(self, prop, what="offset_x"):
        return self.dev.animation_of(self.v.ptr, what)

    def test_one_commit_per_batch_and_calls_counted(self):
        n0 = len(self.dev.calls)
        b = self.core.batch()
        b.to(self.x, 700.0, 420)
        b.to(self.o, 1.0, 300)
        b.commit()
        self.assertEqual(self.dev.commits, 1)
        hot = [c for c in self.dev.calls[n0:] if c[0] in com.SLOTS and com.SLOTS[c[0]][1] == com.PY]
        self.assertEqual(len(hot), b.calls)
        self.assertEqual(b.anims, 2)

    def test_begin_time_is_t1_and_segments_match_the_twin(self):
        b = self.core.batch()
        b.to(self.x, 700.0, 420)
        b.commit()
        a = self.anim_of(self.x)
        self.assertEqual(a["begin"], b.t1)
        segs, end = self.x.func.segments()
        self.assertEqual(len(a["segs"]), len(segs))
        for got, want in zip(a["segs"], segs):
            for g, w in zip(got, want):
                self.assertAlmostEqual(g, w, places=9)
        self.assertEqual(a["end"], end)
        self.assertGreaterEqual(b.t1 - self.clk.t, CK.T1_MARGIN_S * self.clk.freq)       # G1-6

    def test_equal_target_changes_nothing(self):
        b = self.core.batch()
        b.to(self.x, 700.0, 420)
        b.commit()
        self.clk.advance(0.05)
        b2 = self.core.batch()
        self.assertEqual(b2.to(self.x, 700.0, 420), 0)
        self.assertEqual(b2.skipped, 1)
        self.assertEqual(b2.calls, 0)

    def test_retarget_starts_from_the_twin_at_t1(self):
        """G1-7 / H7: the new animation's value at its begin equals the old twin at t1."""
        b = self.core.batch()
        b.to(self.x, 700.0, 420)
        b.commit()
        for i in range(30):
            self.clk.advance(0.05)
            old = self.x.func
            b = self.core.batch()
            b.to(self.x, 100.0 if i % 2 == 0 else 700.0, 420)
            b.commit()
            self.assertAlmostEqual(self.x.func.value(b.t1), old.value(b.t1), places=9)
            a = self.anim_of(self.x)
            first = a["segs"][0]
            self.assertAlmostEqual(first[1], old.value(b.t1), places=6)
        self.assertEqual(self.dev.violations, [])            # a bound animation was never modified

    def test_ping_pong_pool_alternates(self):
        seen = []
        for i in range(6):
            self.clk.advance(0.05)
            b = self.core.batch()
            b.to(self.x, 100.0 * (i + 2), 420)
            b.commit()
            seen.append(self.dev.prop_anim[(self.v.ptr, "offset_x")])
        self.assertEqual(seen, [self.x.pool[0], self.x.pool[1]] * 3)
        self.assertEqual(self.dev.violations, [])

    def test_anchored_future_start_is_a_leading_hold(self):
        t0 = self.clk.t
        b = self.core.batch()
        b.to(self.o, 1.0, 320, anchor=t0, delay_ms=190, v_from=0.0, force=True)
        b.commit()
        a = self.dev.animation_of(self.v.ptr, "opacity")
        self.assertEqual(a["begin"], b.t1)
        hold = a["segs"][0]
        self.assertEqual(hold[1:], (0.0, 0.0, 0.0, 0.0))
        self.assertAlmostEqual(a["segs"][1][0], (t0 + 0.19 * self.clk.freq - b.t1) / self.clk.freq, places=6)
        self.assertEqual(self.o.func.start_tick, t0 + int(0.19 * self.clk.freq))

    def test_anchored_passed_start_begins_partway(self):
        t0 = self.clk.t
        self.clk.advance(0.3)
        b = self.core.batch()
        b.to(self.o, 1.0, 320, anchor=t0, delay_ms=190, v_from=0.0, force=True)
        b.commit()
        a = self.dev.animation_of(self.v.ptr, "opacity")
        self.assertEqual(a["begin"], t0 + int(0.19 * self.clk.freq))        # in the past: DWM drops the start
        self.assertGreater(self.o.func.value(b.t1), 0.5)

    def test_finished_leg_jumps(self):
        t0 = self.clk.t
        self.clk.advance(2.0)
        b = self.core.batch()
        n = b.to(self.o, 1.0, 320, anchor=t0, v_from=0.0, force=True)
        self.assertEqual(n, 1)
        self.assertEqual(b.jumps, 1)
        self.assertEqual(self.dev.obj(self.v.ptr)["props"]["opacity"], 1.0)

    def test_jump_uses_float_setter_once(self):
        b = self.core.batch()
        self.assertEqual(b.jump(self.x, 321.0), 1)
        self.assertEqual(b.jump(self.x, 321.0), 0)
        self.assertEqual(self.dev.obj(self.v.ptr)["props"]["offset_x"], 321.0)
        self.assertIsInstance(self.x.func, CV.Const)

    def test_two_leg_end_bump(self):
        b = self.core.batch()
        b.legs(self.x, [(0, 72.0, 160, "OUT"), (160, 100.0, 160, "OUT")])
        b.commit()
        m = self.x.func
        self.assertEqual(len(m.legs), 2)
        self.assertAlmostEqual(m.value(b.t1 + int(0.16 * self.clk.freq)), 72.0, places=6)
        self.assertEqual(m.end_tick, b.t1 + int(0.32 * self.clk.freq))
        self.assertEqual(b.max_end, m.end_tick)

    # ------------------------------------------------------------------ WP7a-R3: delayed instant steps
    def test_delayed_instant_step_is_a_hold_then_end(self):
        """§7.6 "Dots and marker | instant | 190" (S5-10): one animation, a hold and End."""
        t0 = self.clk.t
        b = self.core.batch()
        n = b.to(self.x, 700.0, 0, anchor=t0, delay_ms=190)
        b.commit()
        start = t0 + int(0.19 * self.clk.freq)
        a = self.anim_of(self.x)
        self.assertEqual(a["begin"], b.t1)
        self.assertEqual(a["segs"], [(0.0, 100.0, 0.0, 0.0, 0.0)])
        self.assertAlmostEqual(a["end"][0], (start - b.t1) / self.clk.freq, places=9)
        self.assertEqual(a["end"][1], 700.0)
        self.assertEqual(n, 5)                                  # Reset, begin, one AddCubic, End, bind
        m = self.x.func
        self.assertEqual(m.value(start - 1), 100.0)                 # H7: the twin steps where DWM steps
        self.assertEqual(m.value(start), 700.0)
        self.assertEqual(m.end_tick, start)
        self.assertEqual(b.max_end, start)
        self.assertEqual(self.dev.violations, [])

    def test_delayed_step_without_anchor_and_delayed_jump(self):
        b = self.core.batch()
        b.to(self.o, 1.0, 0, delay_ms=190)
        b.jump(self.x, 321.0, delay_ms=200)
        b.commit()
        self.assertEqual(self.o.func.end_tick, b.t1 + int(0.19 * self.clk.freq))
        self.assertEqual(self.x.func.end_tick, b.t1 + int(0.2 * self.clk.freq))
        self.assertEqual(self.x.func.value(b.t1), 100.0)
        self.assertEqual(self.x.func.target, 321.0)
        self.assertEqual(b.jumps, 0)

    def test_step_already_reached_is_a_jump(self):
        t0 = self.clk.t
        self.clk.advance(0.3)
        b = self.core.batch()
        self.assertEqual(b.to(self.x, 700.0, 0, anchor=t0, delay_ms=190), 1)
        self.assertEqual(b.jumps, 1)
        self.assertEqual(self.dev.obj(self.v.ptr)["props"]["offset_x"], 700.0)
        b2 = self.core.batch()
        self.assertEqual(b2.to(self.o, 0.5, 0), 1)                  # no delay at all: a jump
        self.assertEqual(b2.jump(self.o, 0.5, anchor=t0), 0)        # already there

    def test_retarget_before_a_pending_step_starts_from_the_hold(self):
        """H7: a turn at +100 ms, before the +190 step, continues from the held value."""
        t0 = self.clk.t
        b = self.core.batch()
        b.to(self.x, 700.0, 0, anchor=t0, delay_ms=190)
        b.commit()
        self.clk.advance(0.1)
        old = self.x.func
        b2 = self.core.batch()
        b2.to(self.x, 400.0, 420)
        b2.commit()
        self.assertEqual(old.value(b2.t1), 100.0)
        self.assertAlmostEqual(self.x.func.value(b2.t1), old.value(b2.t1), places=9)
        self.assertEqual(self.dev.violations, [])

    def test_zero_length_legs_are_steps(self):
        """A fade, then an instant change at +190 in the same animation; and a step to 0 at +190
        immediately followed by a 160 ms fade in (the state block, S5-33)."""
        b = self.core.batch()
        b.legs(self.o, [(0, 0.5, 160, "OUT"), (190, 1.0, 0, "OUT")], v_from=0.0)
        b.commit()
        a = self.dev.animation_of(self.v.ptr, "opacity")
        offs = [s[0] for s in a["segs"]]
        self.assertEqual(offs, sorted(set(offs)))                   # strictly increasing begin offsets
        self.assertAlmostEqual(a["end"][0], 0.19, places=9)
        self.assertEqual(a["end"][1], 1.0)
        m = self.o.func
        self.assertAlmostEqual(m.value(b.t1 + int(0.189 * self.clk.freq)), 0.5, places=6)
        self.assertEqual(m.value(b.t1 + int(0.19 * self.clk.freq)), 1.0)
        self.clk.advance(1.0)
        b2 = self.core.batch()
        b2.legs(self.o, [(190, 0.0, 0, "OUT"), (190, 1.0, 160, "OUT")])
        b2.commit()
        a2 = self.dev.animation_of(self.v.ptr, "opacity")
        offs2 = [s[0] for s in a2["segs"]]
        self.assertEqual(offs2, sorted(set(offs2)))
        self.assertEqual(a2["segs"][0][1:], (1.0, 0.0, 0.0, 0.0))    # the hold at 1 until +190
        self.assertAlmostEqual(a2["segs"][1][0], 0.19, places=9)     # the fade in from 0 at +190
        self.assertEqual(a2["segs"][1][1], 0.0)
        m2 = self.o.func
        at = b2.t1 + int(0.19 * self.clk.freq)
        self.assertEqual(m2.value(at - 1), 1.0)
        self.assertAlmostEqual(m2.value(at), 0.0, places=9)
        self.assertEqual(m2.value(b2.t1 + int(0.4 * self.clk.freq)), 1.0)
        self.assertEqual(self.dev.violations, [])

    def test_failed_hresult_raises_device_lost(self):
        self.dev.fail_next("Commit", com.DXGI_ERROR_DEVICE_REMOVED)
        b = self.core.batch()
        b.to(self.x, 500.0, 420)
        with self.assertRaises(com.DeviceLost):
            b.commit()

    def test_episode_boost_and_record(self):
        b = self.core.batch()
        b.to(self.x, 700.0, 420)
        b.commit()
        self.assertTrue(self.core.finish(b, "turn"))
        self.assertEqual(self.dev.boosts, [True])
        self.clk.advance(0.2)
        b2 = self.core.batch()
        b2.to(self.x, 800.0, 420)
        b2.commit()
        self.assertFalse(self.core.finish(b2, "turn"))
        self.assertIsNone(self.core.tick())
        self.clk.advance(0.5)
        rec = self.core.tick()
        self.assertIsNotNone(rec)
        self.assertEqual(self.dev.boosts, [True, False])
        self.assertEqual(rec["kind"], "turn")
        self.assertEqual(rec["events"], 2)
        self.assertTrue(rec["boosted"])


class HoldModeTests(unittest.TestCase):
    """G1-8: timeFrequency != QPF -> no absolute begin times, leading holds from the predicted
    commit frame (§4.6.5 item 7)."""

    def test_no_absolute_begin_and_lead_from_commit_frame(self):
        clk, dev, core = make(time_frequency=10_000_000, qpf=24_000_000)
        self.assertEqual(core.clock.begin_mode, CK.BEGIN_HOLD)
        tree = Tree(dev)
        v = tree.visual("v")
        x = tree.offset_x(v, 0.0)
        b = core.batch()
        b.to(x, 600.0, 420)
        b.commit()
        self.assertEqual(dev.calls_named("Animation.SetAbsoluteBeginTime"), [])
        a = dev.animation_of(v.ptr, "offset_x")
        self.assertEqual(x.func.begin, b.f_commit)
        lead = (b.t1 - b.f_commit) / dev.freq
        if lead > 0:
            self.assertEqual(a["segs"][0][1:], (0.0, 0.0, 0.0, 0.0))

    def test_steps_in_hold_mode(self):
        """WP7a-R3: ``ms`` 0 raised ZeroDivisionError in hold mode, even with no delay."""
        clk, dev, core = make(time_frequency=10_000_000, qpf=24_000_000)
        tree = Tree(dev)
        v = tree.visual("v")
        x = tree.offset_x(v, 0.0)
        b = core.batch()
        self.assertEqual(b.to(x, 600.0, 0), 1)                         # no delay: a jump
        self.assertEqual(b.jumps, 1)
        t0 = b.t1                                               # (this rig's QPC and frame time bases differ)
        b.to(x, 900.0, 0, anchor=t0, delay_ms=190)
        b.commit()
        self.assertEqual(dev.calls_named("Animation.SetAbsoluteBeginTime"), [])
        a = dev.animation_of(v.ptr, "offset_x")
        start = t0 + int(0.19 * dev.freq)
        self.assertEqual(a["segs"], [(0.0, 600.0, 0.0, 0.0, 0.0)])
        self.assertAlmostEqual(a["end"][0], (start - b.f_commit) / dev.freq, places=9)
        self.assertEqual(x.func.value(start - 1), 600.0)
        self.assertEqual(x.func.value(start), 900.0)

    def test_passed_start_is_reexpanded(self):
        clk, dev, core = make(time_frequency=10_000_000, qpf=24_000_000)
        tree = Tree(dev)
        v = tree.visual("v")
        x = tree.offset_x(v, 0.0)
        t0 = core.clock.now()
        clk.advance(0.1)
        b = core.batch()
        b.to(x, 600.0, 420, anchor=t0, v_from=0.0, force=True)
        b.commit()
        a = dev.animation_of(v.ptr, "offset_x")
        first = a["segs"][0]
        self.assertEqual(first[0], 0.0)
        self.assertAlmostEqual(first[1], x.func.value(b.f_commit), places=5)


if __name__ == "__main__":
    unittest.main()
