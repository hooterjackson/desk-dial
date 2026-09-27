"""Picker v2 pure logic (DESKTOP_STAGE.md sections 9.3-9.8, 10.2, 5, 6.6 H1/H8; CAROUSEL.md 12): layout
math, the two tables, the DWM opacity/shade formula, cover-fit rcSource, the fly target and the
halves, easing, tweens, the CarouselMachine and the ToastMachine on a fake clock, the loop pacer
(P2-P5, G1-2), the frame statistics, frame-rate independence and the placeholder rules. No
windows, no Tk."""
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center import carousel as c  # noqa: E402
from control_center import carousel_render as R  # noqa: E402

G93SC = (0, 0, 5120, 1440)
G93SC_WORK = (0, 0, 5120, 1392)


class TableTests(unittest.TestCase):
    def test_the_16_9_table(self):
        expected = {0: (0, 1.00, 1.00, 0.00), 1: (280, 0.56, 0.95, 0.22), 2: (400, 0.34, 0.60, 0.44),
                    3: (490, 0.26, 0.0, 0.55), 4: (540, 0.20, 0.0, 0.55), 9: (540, 0.20, 0.0, 0.55)}
        for a, (x, s, op, shade) in expected.items():
            for sign in (1, -1):
                with self.subTest(d=sign * a):
                    got = R.table_state(sign * a)
                    self.assertEqual(got[:3], (sign * x if a else 0, s, op))
                    self.assertAlmostEqual(got[3], shade)

    def test_the_32_9_table(self):
        expected = {0: (0, 1.00, 1.00, 0.00), 1: (280, 0.56, 0.95, 0.22), 2: (420, 0.42, 0.70, 0.44),
                    3: (545, 0.40, 0.45, 0.55), 4: (665, 0.40, 0.25, 0.55), 5: (780, 0.40, 0.0, 0.55),
                    8: (780, 0.40, 0.0, 0.55)}
        for a, (x, s, op, shade) in expected.items():
            for sign in (1, -1):
                with self.subTest(d=sign * a):
                    got = R.table_state(sign * a, wide=True)
                    self.assertEqual(got[:3], (sign * x if a else 0, s, op))
                    self.assertAlmostEqual(got[3], shade)

    def test_visible_slots_and_no_visible_card_below_040_on_32_9(self):
        self.assertTrue(all(R.table_state(d)[2] > 0 for d in range(-2, 3)))
        self.assertTrue(all(R.table_state(d)[2] == 0 for d in (-5, -4, -3, 3, 4, 5)))
        self.assertTrue(all(R.table_state(d, True)[2] > 0 for d in range(-4, 5)))
        self.assertTrue(all(R.table_state(d, True)[1] >= 0.40 for d in range(-4, 5)))   # K4 18
        self.assertEqual(R.table_state(5, True)[2], 0)


class OpacityShadeTests(unittest.TestCase):
    def test_spec_values(self):
        self.assertAlmostEqual(R.thumb_opacity(0.95, 0.22), 0.937, places=3)
        self.assertAlmostEqual(R.shade_alpha(0.95, 0.22), 0.209, places=3)
        # K4 9.3's example: a = 3 on 32:9 gives o = 0.269 under a 0.248 shade.
        self.assertAlmostEqual(R.thumb_opacity(0.45, 0.55), 0.269, delta=1e-3)
        self.assertAlmostEqual(R.shade_alpha(0.45, 0.55), 0.248, delta=1e-3)
        self.assertEqual(R.thumb_opacity(1.0, 0.0), 1.0)
        self.assertEqual(R.thumb_opacity(0.0, 0.3), 0.0)

    def test_thumbnail_plus_chrome_shade_equals_css_group_opacity(self):
        rng = random.Random(7)
        for _ in range(200):
            op, s = rng.random(), rng.random() * 0.9
            thumb, backdrop, shade = rng.random(), rng.random(), 0x11 / 255
            css = op * (s * shade + (1 - s) * thumb) + (1 - op) * backdrop
            o, a = R.thumb_opacity(op, s), R.shade_alpha(op, s)
            dwm = a * shade + (1 - a) * (o * thumb + (1 - o) * backdrop)
            self.assertAlmostEqual(css, dwm, places=9)


class CoverSourceTests(unittest.TestCase):
    def test_cover_fit_is_top_aligned_and_keeps_the_card_aspect(self):
        cases = {((1812, 1365), (800, 500)): (0, 0, 1812, 1132),
                 ((1416, 1392), (800, 500)): (0, 0, 1416, 885),
                 ((2396, 1364), (448, 280)): (107, 0, 2289, 1364)}
        for (source, dest), expected in cases.items():
            with self.subTest(source=source):
                rc = R.cover_source(source, dest)
                self.assertEqual(rc, expected)
                self.assertEqual(rc[1], 0)
                w, h = rc[2] - rc[0], rc[3] - rc[1]
                self.assertAlmostEqual(w / h, dest[0] / dest[1], delta=0.01)
                self.assertTrue(0 <= rc[0] and rc[2] <= source[0] and rc[3] <= source[1])

    def test_rect_or_size_and_degenerate_inputs(self):
        self.assertEqual(R.cover_source((1600, 1000), (10, 20, 810, 520)), R.cover_source((1600, 1000), (800, 500)))
        self.assertEqual(R.cover_source((0, 0), (800, 500)), (0, 0, 1, 1))
        self.assertEqual(R.cover_source((800, 600), (0, 0)), (0, 0, 800, 600))


class LayoutTests(unittest.TestCase):
    """H8: the tables, the band, the fly target, the halves (K4 9.2-9.6)."""

    def test_the_users_monitor(self):
        layout = R.layout_for(G93SC, G93SC_WORK)
        self.assertEqual(layout.k, 2.0)
        self.assertTrue(layout.wide)
        self.assertEqual((layout.a_vis, layout.register_distance), (4, 5))
        self.assertEqual(layout.pane, (1420, 184, 2280, 1120))
        self.assertEqual(layout.host, G93SC)
        # the band: +- 765 units (X[4] 665 + 200 x 0.40 + 20) x y 76-668 -> 3060 x 1184 px (14.5 MB)
        self.assertEqual(layout.band, (1030, 152, 3060, 1184))
        self.assertAlmostEqual(layout.band[2] * layout.band[3] * 4 / 1e6, 14.5, delta=0.1)
        self.assertEqual(layout.band_origin, (1030, 152))
        # the centre card: 400 x 250 units at (640, 370) -> 800 x 500 px at (2560, 740)
        self.assertEqual(R.card_rect(layout, 0, 1.0), (2160, 490, 2960, 990))
        self.assertEqual(R.card_rect(layout, 0, 1.0, R.GROUP_SHIFT), (2160, 402, 2960, 902))
        x, s, _op, _shade = R.table_state(3, True)
        self.assertEqual(R.card_rect(layout, x, s), (3490, 640, 3810, 840))     # centre +1090 px
        # the tray: slot 1 at x 457-633 units, slot 2 at 647-823, top 104 (208 px)
        self.assertEqual(R.slot_rect(layout, "left"), (2194, 208, 2546, 428))
        self.assertEqual(R.slot_rect(layout, "right"), (2574, 208, 2926, 428))

    def test_the_16_9_band(self):
        layout = R.layout_for((0, 0, 2560, 1440))
        self.assertFalse(layout.wide)
        self.assertEqual((layout.a_vis, layout.register_distance), (2, 3))
        half = (layout.band[2] / 2) / layout.k
        self.assertAlmostEqual(half, 488, delta=0.5)                             # K4 9.2: +- 488 units
        self.assertEqual(R.layout_for((0, 0, 1280, 720)).band, (152, 76, 976, 592))

    def test_wide_is_w_over_k_above_1281(self):
        self.assertFalse(R.layout_for((0, 0, 2562, 1440)).wide)                 # 1281 units
        self.assertTrue(R.layout_for((0, 0, 2564, 1440)).wide)
        self.assertTrue(R.layout_for((0, 0, 3440, 1440)).wide)
        self.assertFalse(R.layout_for((0, 0, 1920, 1200)).wide)                 # narrower: k fits the width

    def test_stage_scale_fits_the_monitor_and_centres_the_stage(self):
        for monitor, k in (((0, 0, 1920, 1080), 1.5), ((0, 0, 2560, 1440), 2.0), ((0, 0, 3840, 2160), 3.0),
                           ((-1920, 0, 0, 1200), 1.5), ((0, 0, 1280, 1024), 1.0), (G93SC, 2.0)):
            with self.subTest(monitor=monitor):
                layout = R.layout_for(monitor)
                self.assertAlmostEqual(layout.k, k)
                sx, sy, sw, sh = layout.stage
                self.assertAlmostEqual(sx - monitor[0], (monitor[2] - monitor[0] - sw) / 2, delta=1)
                self.assertAlmostEqual(sy - monitor[1], (monitor[3] - monitor[1] - sh) / 2, delta=1)
                for rect in (layout.pane, layout.band, layout.labels, layout.dots):
                    x, y, w, h = rect
                    self.assertTrue(monitor[0] <= x and x + w <= monitor[2] and monitor[1] <= y and y + h <= monitor[3])

    def test_every_visible_card_fits_the_band(self):
        for monitor in ((0, 0, 1280, 720), (0, 0, 2560, 1440), G93SC):
            layout = R.layout_for(monitor)
            ox, oy = layout.band_origin
            for d in range(-layout.a_vis, layout.a_vis + 1):
                for shift in (0.0, R.GROUP_SHIFT):
                    with self.subTest(monitor=monitor, d=d, shift=shift):
                        x, s, _op, _shade = R.table_state(d, layout.wide)
                        left, top, right, bottom = R.card_rect(layout, x, s, shift)
                        self.assertGreaterEqual(left - ox, 0)
                        self.assertLessEqual(right - ox, layout.band[2])
                        self.assertGreaterEqual(top - oy, 0)
                        self.assertLessEqual(bottom - oy, layout.band[3])

    def test_halves_of_the_work_area_the_right_takes_the_odd_pixel(self):
        self.assertEqual(R.work_half(G93SC_WORK, "left"), (0, 0, 2560, 1392))
        self.assertEqual(R.work_half(G93SC_WORK, "right"), (2560, 0, 5120, 1392))
        self.assertEqual(R.work_half((-1921, 0, 0, 1040), "left"), (-1921, 0, -961, 1040))
        self.assertEqual(R.work_half((-1921, 0, 0, 1040), "right"), (-961, 0, 0, 1040))
        self.assertEqual(R.layout_for(G93SC, G93SC_WORK).half("right"), (2560, 0, 5120, 1392))
        self.assertEqual(R.layout_for(G93SC).half("left"), (0, 0, 2560, 1440))     # no work area given: the monitor

    def test_the_fly_target_on_the_g93sc(self):
        layout = R.layout_for(G93SC, G93SC_WORK)
        # kf = min(2560 / 800, 1392 / 500) = 2.784: a 2227 x 1392 box at x 166 (left) or 2726 (right), y 0
        for side, x in (("left", 166), ("right", 2726)):
            l, t, r, b = R.fly_target(layout, side)
            self.assertEqual((round(l), round(t), round(r - l), round(b - t)), (x, 0, 2227, 1392))
        # WP7b-R1: a half given as a rect (a snap job's target) is that half, never "not left"
        self.assertEqual(R.fly_target(layout, (0, 0, 2560, 1392)), R.fly_target(layout, "left"))
        self.assertEqual(R.fly_target(layout, (2560, 0, 5120, 1392)), R.fly_target(layout, "right"))
        self.assertEqual(R.fly_target(layout, layout.half("left")), R.fly_target(layout, "left"))
        self.assertEqual(R.fly_target(layout, layout.half("right")), R.fly_target(layout, "right"))
        l, t, r, b = R.fly_target(layout, layout.half("left"))
        self.assertTrue(0 <= l and r <= 2560, "a left snap's fly ends inside the left rcWork half")

    def test_a_side_that_is_neither_left_nor_right_is_an_error(self):
        # WP7b-R1: work_half used to answer the right half for any value but "left"
        for bad in ("Left", "", None, (0, 0, 10, 10)):
            with self.assertRaises(ValueError):
                R.work_half(G93SC_WORK, bad)
        with self.assertRaises(ValueError):
            R.fly_target(R.layout_for(G93SC, G93SC_WORK), (0, 0, 10))

    def test_the_fly_is_translate_plus_uniform_scale(self):
        start, target = (2160, 402, 2960, 902), R.fly_target(R.layout_for(G93SC, G93SC_WORK), "right")
        self.assertEqual(R.fly_rect(start, target, 0.0), start)
        for got, want in zip(R.fly_rect(start, target, 1.0), target):
            self.assertLessEqual(abs(got - want), 1)
        for e in (0.25, 0.5, 0.75):
            l, t, r, b = R.fly_rect(start, target, e)
            self.assertAlmostEqual((r - l) / (b - t), 1.6, delta=0.01)               # uniform scale, no stretch
            self.assertAlmostEqual(l, start[0] + (target[0] - start[0]) * e, delta=1)

    def test_the_tray_spring_scales_about_its_centre(self):
        layout = R.layout_for(G93SC, G93SC_WORK)
        l, t, r, b = R.slot_rect(layout, "left", -14, 0.94)
        L, T, Rr, B = R.slot_rect(layout, "left")
        self.assertAlmostEqual((r - l) / (Rr - L), 0.94, delta=0.01)
        self.assertLess(t, T)


class EasingTests(unittest.TestCase):
    @staticmethod
    def reference(x1, y1, x2, y2, x):
        lo, hi = 0.0, 1.0
        for _ in range(60):
            t = (lo + hi) / 2
            bx = 3 * (1 - t) ** 2 * t * x1 + 3 * (1 - t) * t * t * x2 + t ** 3
            lo, hi = (t, hi) if bx < x else (lo, t)
        t = (lo + hi) / 2
        return 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t * t * y2 + t ** 3

    def test_curves_match_css_cubic_bezier(self):
        self.assertEqual(c.EASE_OUT.params, (0.22, 1, 0.36, 1))
        self.assertEqual(c.EASE_IN.params, (0.4, 0, 1, 1))
        self.assertEqual(c.SPRING.params, (0.34, 1.45, 0.64, 1))
        self.assertEqual(c.EASE.params, (0.25, 0.1, 0.25, 1))
        for curve in (c.EASE_OUT, c.SPRING, c.EASE_IN, c.EASE):
            for i in range(1, 100):
                x = i / 100
                self.assertAlmostEqual(curve(x), self.reference(*curve.params, x), delta=1e-3)
            self.assertEqual((curve(0.0), curve(1.0), curve(-1), curve(2)), (0.0, 1.0, 0.0, 1.0))

    def test_ease_out_is_monotonic_and_the_spring_overshoots(self):
        values = [c.EASE_OUT(i / 200) for i in range(201)]
        self.assertEqual(values, sorted(values))
        self.assertGreater(max(c.SPRING(i / 200) for i in range(201)), 1.02)


class TweenTests(unittest.TestCase):
    def test_retarget_starts_from_the_current_value_over_the_full_duration(self):
        tween = c.Tween(0.0)
        tween.retarget(100.0, 0.0, 0.42)
        mid = tween.value(0.1)
        tween.retarget(-50.0, 0.1, 0.42)
        self.assertAlmostEqual(tween.value(0.1), mid, places=9)          # continuous, no jump
        self.assertNotEqual(tween.value(0.42), -50.0)                     # never queued behind the first
        self.assertEqual(tween.value(0.52), -50.0)
        self.assertTrue(tween.done(0.52))

    def test_same_target_does_not_restart(self):
        tween = c.Tween(0.0)
        self.assertTrue(tween.retarget(1.0, 0.0, 0.3))
        self.assertFalse(tween.retarget(1.0, 0.2, 0.3))
        self.assertEqual(tween.value(0.3), 1.0)


class MachineTests(unittest.TestCase):
    def machine(self, count=8, sel=1, now=0.0, closed=(), wide=False, rm=False):
        m = c.CarouselMachine()
        m.start(count, sel, now, closed, wide=wide, rm=rm)
        return m

    def card(self, frame, index):
        return next((cf for cf in frame.cards if cf.index == index), None)

    def test_open_the_root_fades_and_every_card_enters_with_the_rise_and_scale(self):
        m = self.machine()
        f = m.values(0.0)
        self.assertEqual((f.root, f.cards), (0.0, []))                    # everything at root opacity 0
        self.assertEqual((f.shift, f.tray_op), (R.GROUP_SHIFT, 0.0))     # the tray hidden, the group 44 up
        m.values(0.0)
        card = m.cards[1]
        self.assertEqual((card.rise.value(0.0), card.escale.value(0.0), card.op.value(0.0)), (24.0, 0.92, 0.0))
        f = m.values(0.14)
        self.assertTrue(0 < f.root < 1)
        centre = self.card(f, 1)
        self.assertTrue(0.92 < centre.s < 1.0)                           # the enter scale multiplies S
        self.assertTrue(R.GROUP_SHIFT < centre.y < R.GROUP_SHIFT + 24)     # the rise, in S-scaled units
        side = self.card(f, 2)
        self.assertAlmostEqual(side.y - R.GROUP_SHIFT, m.cards[2].rise.value(0.14) * 0.56, places=9)
        self.assertEqual(m.values(0.28).root, 1.0)                       # the root 280 ms OUT
        f = m.values(0.42)                                                # the enter 420 ms OUT, no stagger
        self.assertEqual((self.card(f, 1).s, self.card(f, 1).y, self.card(f, 1).op), (1.0, R.GROUP_SHIFT, 1.0))
        self.assertAlmostEqual(self.card(f, 2).op, 0.95)
        self.assertEqual(m.values(1.0).glass, 0.0)                       # never before the capture
        m.set_glass_ready(1.0)
        self.assertTrue(0 < m.values(1.14).glass < 1)
        self.assertEqual(m.values(1.28).glass, 1.0)
        self.assertFalse(m.animating(1.28))

    def test_reduced_motion_open_fades_only(self):
        m = self.machine(rm=True)
        m.values(0.0)
        f = m.values(0.1)
        centre = self.card(f, 1)
        self.assertEqual((centre.s, centre.y), (1.0, R.GROUP_SHIFT))
        self.assertAlmostEqual(m.cards[1].op.value(0.2), 1.0)             # 200 ms OUT
        self.assertLess(m.cards[1].op.value(0.1), 1.0)

    def test_visible_cards_follow_the_table(self):
        for wide, visible in ((False, [2, 3, 4, 5, 6]), (True, [0, 1, 2, 3, 4, 5, 6, 7, 8])):
            m = self.machine(count=9, sel=4, wide=wide)
            f = m.values(1.0)
            self.assertEqual(sorted(cf.index for cf in f.cards), visible)
            for cf in f.cards:
                x, s, op, shade = R.table_state(cf.index - 4, wide)
                self.assertEqual((cf.d, cf.x, cf.s), (cf.index - 4, x, s))
                self.assertAlmostEqual(cf.shade, shade)
                self.assertAlmostEqual(cf.op, op)
                self.assertEqual(cf.selw, 1.0 if cf.index == 4 else 0.0)

    def test_a_turn_moves_over_420_ms_fades_over_300_and_shades_and_frames_over_320(self):
        m = self.machine(count=8, sel=1)
        self.assertTrue(m.select(2, 1.0))
        f = m.values(1.3)
        new = self.card(f, 2)
        self.assertAlmostEqual(new.op, 1.0)               # opacity done at 300 ms
        self.assertTrue(0 < new.x < 280 and 0.56 < new.s < 1.0)
        self.assertTrue(0 < new.shade < 0.22 and 0 < new.selw < 1)
        f = m.values(1.32)
        self.assertEqual((self.card(f, 2).shade, self.card(f, 2).selw), (0.0, 1.0))
        f = m.values(1.42)
        self.assertEqual((self.card(f, 2).x, self.card(f, 2).s), (0.0, 1.0))
        self.assertEqual((self.card(f, 1).x, self.card(f, 1).s), (-280.0, 0.56))
        self.assertIsNone(self.card(f, 5))                # d = 3 on 16:9: invisible
        self.assertFalse(m.animating(1.42))

    def test_reduced_motion_turns_jump_with_a_200_ms_opacity(self):
        m = self.machine(count=8, sel=1, rm=True)
        m.values(1.0)
        m.select(2, 1.0)
        f = m.values(1.0)
        self.assertEqual((self.card(f, 2).x, self.card(f, 2).s), (0.0, 1.0))    # jumps
        self.assertAlmostEqual(m.cards[2].op.value(1.2), 1.0)
        self.assertEqual(m.marker.value(1.0), 2.0)                            # the marker jumps
        self.assertFalse(m.bump_now(1, 2.0))                                  # no end bump

    def test_fast_turns_retarget_mid_flight_and_never_queue(self):
        m = self.machine(count=10, sel=1)
        m.select(2, 1.0)
        before = self.card(m.values(1.1 - 1e-6), 3)
        m.select(3, 1.1)
        after = self.card(m.values(1.1), 3)
        self.assertAlmostEqual(before.x, after.x, places=2)       # continuous
        self.assertAlmostEqual(before.s, after.s, places=4)
        self.assertNotEqual(self.card(m.values(1.42), 3).x, 0.0)  # the first 420 ms would end here
        f = m.values(1.52)
        self.assertEqual((self.card(f, 3).x, self.card(f, 3).s), (0.0, 1.0))
        self.assertEqual(m.sel, 3)

    def test_big_jumps_retarget_every_card_between(self):
        m = self.machine(count=30, sel=0)
        m.select(25, 1.0)
        f = m.values(2.0)
        self.assertEqual(sorted(cf.index for cf in f.cards), [23, 24, 25, 26, 27])

    def test_the_marker_translates_over_420_ms_and_the_label_fades_in_over_160(self):
        m = self.machine(count=6, sel=1)
        self.assertEqual(m.values(1.0).marker, 1.0)
        m.select(2, 1.0)
        self.assertTrue(1.0 < m.values(1.2).marker < 2.0)
        self.assertEqual(m.values(1.42).marker, 2.0)
        m.label_swap(2.0)
        self.assertEqual(m.values(2.0).label_alpha, 0.0)
        self.assertTrue(0 < m.values(2.08).label_alpha < 1)
        self.assertEqual(m.values(2.16).label_alpha, 1.0)

    def test_the_marker_uses_the_dots_window_on_long_lists(self):
        m = self.machine(count=200, sel=100)
        self.assertEqual(m.values(1.0).marker, 41.0)                     # first = 100 - 41
        m.select(101, 1.0)
        self.assertEqual(m.values(1.5).marker, 41.0)                     # the row moves, not the marker
        self.assertEqual(R.dots_window(200, 101)[0], 60)
        m.select(199, 2.0)
        self.assertEqual(m.values(3.0).marker, 81.0)

    def test_end_bump_is_local_and_springs_back(self):
        m = self.machine(count=4, sel=3)
        self.assertTrue(m.at_end(1))
        self.assertFalse(m.at_end(-1))
        self.assertTrue(m.bump_now(1, 1.0))
        self.assertEqual(m.bump, 1)
        self.assertLess(m.values(1.08).bump, 0)
        self.assertAlmostEqual(m.values(1.16).bump, -12.0)
        self.assertTrue(-12 < m.values(1.24).bump < 0)
        self.assertEqual(m.values(1.32).bump, 0.0)
        self.assertFalse(m.animating(1.32))
        m = self.machine(count=4, sel=0)
        self.assertTrue(m.at_end(-1))
        m.bump_now(-1, 0.0)
        self.assertAlmostEqual(m.values(0.16).bump, 12.0)

    def test_the_first_snap_reveals_the_tray_with_its_spring_and_moves_the_group(self):
        m = self.machine(count=6, sel=1)
        m.values(1.0)
        self.assertTrue(m.reveal_tray(1.0))
        self.assertFalse(m.reveal_tray(1.1))                              # once per open
        f = m.values(1.13)
        self.assertTrue(0 < f.tray_op < 1)
        self.assertTrue(-14 < f.tray_y and 0.94 < f.tray_sc)
        self.assertTrue(R.GROUP_SHIFT < f.shift < 0)
        spring = [m.values(1.0 + i / 200).tray_sc for i in range(1, 93)]
        self.assertGreater(max(spring), 1.0, "SPR overshoots")
        self.assertEqual(m.values(1.26).tray_op, 1.0)                     # 260 ms OUT
        f = m.values(1.46)
        self.assertEqual((f.tray_y, f.tray_sc, f.shift), (0.0, 1.0, 0.0))  # 460 ms
        m = self.machine(count=6, sel=1, rm=True)
        m.reveal_tray(1.0)
        f = m.values(1.0)
        self.assertEqual((f.tray_y, f.tray_sc, f.shift), (0.0, 1.0, 0.0))  # reduced motion: fades only
        self.assertLess(f.tray_op, 1.0)

    def test_slot_looks_fill_preview_glyph_badge_and_border_crossfades(self):
        m = self.machine()
        m.set_slot("left", True, False, False, 1.0)
        m.set_slot("right", False, True, False, 1.0)
        f = m.values(1.13)
        left, right = f.slots["left"], f.slots["right"]
        self.assertTrue(0 < left.fill < 1 and 0 < left.badge < 1)
        self.assertTrue(0 < left.borders["filled"] < 1 and 0 < left.borders["empty"] < 1)
        self.assertTrue(0 < right.ghost < R.KEEP_OPACITY)
        f = m.values(1.2)
        self.assertEqual((f.slots["left"].glyph, f.slots["right"].glyph), (0.0, 0.0))    # 200 ms EASE
        f = m.values(1.26)
        self.assertEqual((f.slots["left"].fill, f.slots["left"].badge, f.slots["left"].borders["filled"]),
                         (1.0, 1.0, 1.0))
        self.assertEqual(f.slots["right"].ghost, R.KEEP_OPACITY)
        m.set_slot("left", False, False, True, 2.0)                       # a failure after a move out
        f = m.values(2.26)
        self.assertEqual((f.slots["left"].borders["failure"], f.slots["left"].fill), (1.0, 0.0))

    def test_exits_fade_the_root_280_out_and_the_cards_group_220_ease_with_no_grow(self):
        for kind in ("switch", "cancel", "pair"):
            with self.subTest(kind=kind):
                m = self.machine(count=6, sel=2)
                m.set_glass_ready(0.5)
                self.assertTrue(m.start_exit(kind, 1.0))
                self.assertFalse(m.start_exit("cancel", 1.0))
                f = m.values(1.1)
                self.assertEqual(self.card(f, 2).s, 1.0)                  # S5-6: no 1.35 grow
                self.assertTrue(0 < f.root < 1 and 0 < f.group < 1)
                self.assertEqual(m.values(1.22).group, 0.0)
                self.assertGreater(m.values(1.22).root, 0.0)
                self.assertFalse(m.exit_done(1.27))
                self.assertTrue(m.exit_done(1.28))
                f = m.values(1.28)
                self.assertEqual((f.root, f.glass, f.dim, f.cards), (0.0, 0.0, 0.0, []))
                self.assertFalse(m.select(3, 1.1))                          # no turning during the exit
        self.assertEqual(c.EXIT_S, {"switch": 0.28, "cancel": 0.28, "pair": 0.28})
        self.assertLessEqual(max(c.EXIT_S.values()), 0.42 - 1 / 30)       # a frame of margin even at 30 Hz

    def test_closed_cards_stay_at_35_percent_and_cannot_switch(self):
        m = self.machine(count=5, sel=1, closed=[1])
        f = m.values(1.0)
        centre = self.card(f, 1)
        self.assertTrue(centre.closed)
        self.assertAlmostEqual(centre.op, 0.35)
        self.assertFalse(m.can_switch())
        m.select(2, 1.0)
        self.assertTrue(m.can_switch())
        m.set_closed([1, 2])
        self.assertFalse(m.can_switch())
        self.assertAlmostEqual(self.card(m.values(2.0), 1).op, 0.95 * 0.35)

    def test_cover_is_the_cards_own_opacity_without_the_group_fades(self):
        m = self.machine(count=5, sel=1, closed=[2])
        f = m.values(1.0)
        self.assertTrue(all(abs(cf.cover - cf.op) < 1e-12 for cf in f.cards))   # at rest: the same
        m.start_exit("switch", 1.0)
        f = m.values(1.1)
        centre, side = self.card(f, 1), self.card(f, 2)
        self.assertEqual(centre.cover, 1.0)
        self.assertAlmostEqual(centre.op, f.root * f.group)
        self.assertAlmostEqual(side.cover, 0.95 * 0.35)
        self.assertAlmostEqual(side.op, 0.95 * 0.35 * f.root * f.group)

    def test_far_cards_are_pruned_and_recreated_at_rest(self):
        for wide in (False, True):
            m = self.machine(count=40, sel=0, wide=wide)
            reach = m.a_max + 1
            m.select(1, 0.0)
            m.values(1.0)
            self.assertTrue(all(abs(i - m.sel) <= reach for i in m.cards))
            m.select(30, 1.0)
            m.values(3.0)
            self.assertTrue(all(abs(i - m.sel) <= reach for i in m.cards))

    def test_empty_and_single_lists(self):
        m = self.machine(count=0, sel=0)
        self.assertEqual(m.values(1.0).cards, [])
        self.assertFalse(m.can_switch())
        m = self.machine(count=1, sel=0)
        self.assertTrue(m.at_end(1) and m.at_end(-1))


class FrameRateIndependenceTests(unittest.TestCase):
    """H1: the machine sampled at 60, 120, 144, 240 and 360 Hz gives the same value at the same t;
    a skip of 1-3 vblanks resumes on the curve with no catch-up burst."""

    def run_at(self, hz, skip=()):
        m = c.CarouselMachine()
        m.start(12, 3, 0.0, wide=True)
        events = {0.05: ("select", 4), 0.12: ("select", 5), 0.2: ("tray", None), 0.31: ("bump", 1), 0.4: ("exit", None)}
        samples = {}
        pending = sorted(events.items())
        n = 0
        t = 0.0
        while t <= 0.8:
            while pending and pending[0][0] <= t + 1e-12:
                at, (kind, arg) = pending.pop(0)
                if kind == "select":
                    m.select(arg, at)
                elif kind == "tray":
                    m.reveal_tray(at)
                elif kind == "bump":
                    m.bump_now(arg, at)
                else:
                    m.start_exit("cancel", at)
            if n not in skip:
                m.values(t)
            n += 1
            t = n / hz
        for probe in (0.1, 0.25, 0.3, 0.5, 0.6):
            f = m.values(probe)
            samples[probe] = (round(f.root, 9), round(f.shift, 9), round(f.tray_sc, 9),
                              tuple(sorted((cf.index, round(cf.x, 6), round(cf.s, 9)) for cf in f.cards)))
        return samples

    def test_same_values_at_every_refresh_rate_and_after_skips(self):
        reference = self.run_at(240)
        for hz in (60, 120, 144, 360):
            with self.subTest(hz=hz):
                self.assertEqual(self.run_at(hz), reference)
        self.assertEqual(self.run_at(240, skip={20, 21, 22, 50}), reference)


class ToastMachineTests(unittest.TestCase):
    def test_in_hold_and_out(self):
        t = c.ToastMachine()
        t.start(10.0)
        self.assertEqual(t.next_wait(10.1), 0.0)
        self.assertAlmostEqual(t.next_wait(10.9), 0.9, places=6)          # holding: until 1.8 s
        self.assertEqual(t.values(10.0), (0.0, 8.0, 0.96))
        opacity, rise, scale = t.values(10.26)
        self.assertEqual((opacity, rise), (1.0, 0.0))                     # 260 ms OUT
        self.assertAlmostEqual(t.values(10.42)[2], 1.0)                   # 420 ms SPR
        self.assertTrue(any(t.values(10.0 + i / 100)[2] > 1.0 for i in range(1, 42)))   # the spring overshoots
        self.assertEqual(t.values(11.79)[0], 1.0)
        self.assertFalse(t.done(11.9))
        opacity, rise, scale = t.values(11.9)
        self.assertTrue(0 < opacity < 1)
        self.assertEqual((rise, scale), (0.0, 1.0), "the exit is opacity only (S5-5)")
        self.assertTrue(t.done(12.0))                                     # 2000 ms in all

    def test_a_replacement_restarts_the_hold_without_a_new_entry(self):
        t = c.ToastMachine()
        t.start(10.0)
        t.replace(11.0)
        self.assertEqual(t.t0, 10.0)
        self.assertEqual(t.values(12.7)[0], 1.0)
        self.assertTrue(t.done(13.0))
        t = c.ToastMachine()
        t.start(10.0)
        t.values(11.85)                                                   # fading out
        t.replace(11.85)
        self.assertEqual(t.values(12.2)[0], 1.0)                          # back in

    def test_reduced_motion_is_opacity_only(self):
        t = c.ToastMachine()
        t.start(0.0, rm=True)
        self.assertEqual(t.values(0.1)[1:], (0.0, 1.0))
        self.assertTrue(0 < t.values(0.1)[0] < 1)


class PacerTests(unittest.TestCase):
    """K4 5.1: P2 (the predicted display time), P3 with G1-2 (the compositor clock, else DwmFlush,
    else the timer; no clock -> one P on the timer; never a loop on the call), P4 (wake intervals)
    and P5 (the 120 lock with hysteresis)."""

    def test_p2_samples_the_next_vblank_after_the_work_estimate(self):
        period = 1 / 240
        pacer = c.LoopPacer(clock=lambda: 0.0, timing=lambda: (10.0, period))
        self.assertAlmostEqual(pacer.target(10.001), 10.0 + period)       # no work history: the next vblank
        for i in range(20):
            pacer.frame_done(10.0 + i * period, 0.006)                     # 6 ms of work
        t = pacer.target(10.0 + 20 * period)
        self.assertGreaterEqual(t, 10.0 + 20 * period + 0.006 - 1e-9)
        self.assertAlmostEqual((t - 10.0) / period, round((t - 10.0) / period), places=6)   # on the grid
        self.assertEqual(c.LoopPacer(clock=lambda: 0.0).target(5.0), 5.0)  # no timing: now

    def test_p5_locks_to_every_second_vblank_and_unlocks_after_half_a_second(self):
        period = 1 / 240
        pacer = c.LoopPacer(timing=lambda: (0.0, period))
        pacer.refresh()
        t = 0.0
        while t < pacer.LOCK_MIN_SPAN_S - period:                         # P1: not in the run's first 0.25 s
            pacer.frame_done(t, 0.8 * period + 0.0005)
            t += period
        self.assertEqual(pacer.cadence, 1)
        for _ in range(10):
            pacer.frame_done(t, 0.8 * period + 0.0005)
            t += period
        self.assertEqual(pacer.cadence, 2)
        self.assertEqual(pacer.switches, 1)
        target = pacer.target(t)
        self.assertGreaterEqual(target - t, 2 * period - 1e-9)             # sampled 2 P ahead
        for _ in range(60):                                                # 0.5 s below 0.6 P
            pacer.frame_done(t, 0.3 * period)
            t += 2 * period
        self.assertEqual(pacer.cadence, 2, "the window still holds the slow frames")
        for _ in range(200):
            pacer.frame_done(t, 0.3 * period)
            t += 2 * period
        self.assertEqual(pacer.cadence, 1)
        self.assertEqual(pacer.switches, 2)

    def test_p1_one_off_frames_and_a_lone_heavy_frame_never_lock(self):
        """P1 of the 2026-09-26 frame-drop fixes (tour W on screen: every open locked at 120 for
        about 1 s by its 13-16 ms setup frame; 0 -> 2 -> 4 -> 6 -> 8 switches over four opens): the
        pacer fed an open shaped like W's (``p5_lock_sim``: a 14 ms setup frame, the 12.8 ms frost
        upload 90 ms later, normal frames about 0.8 ms) and a turn at 10 and 20 detents/s (detent
        frames 1.8-2.8 ms, the re-registration after each 1.2-2.2 ms)."""
        import random
        period = 1 / 240

        def run(flag_oneoffs, gpu_detents=True):
            rnd = random.Random(7)
            pacer = c.LoopPacer(timing=lambda: (0.0, period))
            pacer.refresh()
            n, t_end, frames = 240, 1.0 + 0.55 + 0.33 + 3.34, []
            detents = sorted([1.88 + 0.1 * i for i in range(20)] + [3.88 + 0.05 * i for i in range(20)])
            rereg = False
            while n * period < t_end:
                t = n * period
                in_open, in_turn = 1.0 <= t < 1.55, 1.88 <= t < t_end
                if not (in_open or in_turn):
                    n += 1
                    continue
                kind = "normal"
                if abs(t - 1.0) < period / 2:
                    kind, work = "setup", 0.014
                elif abs(t - 1.09) < period / 2:
                    kind, work = "glass", 0.0128
                elif detents and detents[0] <= t:
                    detents.pop(0)
                    kind, work, rereg = "detent", rnd.uniform(0.0018, 0.0028), True
                elif rereg:
                    work, rereg = rnd.uniform(0.0012, 0.0022), False
                else:
                    work = rnd.uniform(0.0004, 0.0011)
                oneoff = flag_oneoffs and kind in ("setup", "glass")
                p5 = not (gpu_detents and kind == "detent")
                frames.append((t, "open" if in_open else "turn"))
                n += pacer.frame_done(t, work, oneoff=oneoff, p5=p5) if flag_oneoffs else pacer.frame_done(t, work)
            out = {}
            for k in ("open", "turn"):
                ts = [f[0] for f in frames if f[1] == k]
                out[k] = (len(ts), sum(1 for a, b in zip(ts, ts[1:]) if round((b - a) / period) >= 2))
            return out, pacer.switches
        fixed, switches = run(True)
        self.assertEqual(fixed["open"][1], 0)                                 # every open frame at 240
        self.assertEqual(fixed["turn"][1], 0)
        self.assertEqual(switches, 0)
        # without the flags the setup frame alone is still no lock (LOCK_MIN_SPAN_S, LOCK_MIN_OVER) ...
        plain, switches = run(False)
        self.assertEqual(plain["open"][1], 0)
        # ... and a heavy frame among 60 light ones is under the p95
        pacer = c.LoopPacer(timing=lambda: (0.0, period))
        pacer.refresh()
        for i in range(80):
            pacer.frame_done(i * period, 0.020 if i == 70 else 0.0008)
        self.assertEqual(pacer.cadence, 1)
        pacer.frame_done(81 * period, 0.050, oneoff=True)
        self.assertEqual((pacer.cadence, pacer.oneoff_frames), (1, 1))
        self.assertLess(pacer.work_p95(81 * period), 0.8 * period)            # P2's estimate untouched too

    def test_p1_the_gpu_chromes_detent_frames_do_not_hold_the_lock(self):
        period = 1 / 240
        pacer = c.LoopPacer(timing=lambda: (0.0, period))
        pacer.refresh()
        pacer.cadence = 2                                                     # locked (a slow stretch)
        t = 0.0
        for i in range(240):                                                  # 1 s at 120, a detent each 10th
            detent = i % 10 == 0
            pacer.frame_done(t, 0.0027 if detent else 0.0008, p5=not detent)
            t += 2 * period
        self.assertEqual(pacer.cadence, 1)
        self.assertGreater(pacer.work_p95(t), 0.6 * period)                  # P2 still sees the detent frames

    @staticmethod
    def _drive(pacer, hz, work_of, seconds, t0=0.0):
        """The loop on a ``hz`` display: a frame on each vblank it wakes on; the next wake is the
        first vblank the frame's work and the cadence allow (work over P spans ceil(work / P)
        vblanks; the 120 lock presents on every second one). Returns [(t, work, cadence after)]."""
        import math
        period = 1.0 / hz
        n = int(round(t0 / period))
        frames = []
        while n * period < t0 + seconds - 1e-12:
            t = n * period
            work = work_of(len(frames), t)
            cadence = pacer.frame_done(t, work)
            frames.append((t, work, cadence))
            n += max(cadence, int(math.ceil(work / period - 1e-9)))
        return frames

    def test_p1_the_lock_engages_at_every_rate_once_the_loop_ran_a_quarter_second(self):
        """Review finding (2026-09-26): P1's first form needed 60 frames in P5's 0.5 s window, which
        a 60 Hz loop never holds (at most 31), nor a 240 Hz loop whose work is over 2 P (40), so the
        lock never engaged where it is meant to. The minimum is now a time span, the same at every
        rate: a loop whose work stays over 0.8 P locks once it has run LOCK_MIN_SPAN_S (and never
        before), at 60, 120, 144 and 240 Hz, with work under P, over P and over 2 P."""
        cases = ((60, 14.0), (60, 20.0), (60, 35.0), (120, 7.0), (120, 9.0), (120, 18.0), (144, 6.5),
                 (240, 4.0), (240, 9.0), (240, 12.0))
        for hz, work_ms in cases:
            with self.subTest(hz=hz, work_ms=work_ms):
                period = 1.0 / hz
                pacer = c.LoopPacer(timing=lambda period=period: (0.0, period))
                pacer.refresh()
                frames = self._drive(pacer, hz, lambda i, t: work_ms / 1000.0, 1.0)
                locked = [t for t, _w, cadence in frames if cadence == 2]
                self.assertTrue(locked, "never locked at %d Hz with %.1f ms of work" % (hz, work_ms))
                self.assertGreaterEqual(locked[0], pacer.LOCK_MIN_SPAN_S - 1e-9)
                self.assertLess(locked[0], pacer.LOCK_MIN_SPAN_S + 3 * period + 1e-9)
                self.assertEqual(pacer.switches, 1)                               # and it stays locked
                self.assertEqual(pacer.runs, 1)

    def test_p1_a_120_hz_loop_that_misses_vblanks_still_locks(self):
        """The review's 120 Hz case: with the lock minimum a frame count, a 120 Hz loop locked only if
        it missed no vblank at all. Work of 7 ms with every fifth frame at 12 ms (one vblank missed
        each time) locks after a quarter second."""
        pacer = c.LoopPacer(timing=lambda: (0.0, 1 / 120))
        pacer.refresh()
        frames = self._drive(pacer, 120, lambda i, t: 0.012 if i % 5 == 4 else 0.007, 1.0)
        locked = [t for t, _w, cadence in frames if cadence == 2]
        self.assertTrue(locked)
        self.assertLess(locked[0], pacer.LOCK_MIN_SPAN_S + 3 / 120)

    def test_p1_one_slow_frame_never_locks_at_any_rate(self):
        """A lone slow frame (3 P: a first upload, a GC pause) at a run's start or later: with fewer
        than 20 frames in the window the nearest-rank p95 is that frame, so LOCK_MIN_OVER (two frames
        over 0.8 P) keeps the rate. At 60 Hz the 0.25 s window holds only about 15 frames."""
        for hz in (60, 120, 144, 240):
            for slow_at in (0.0, 0.3):
                with self.subTest(hz=hz, slow_at=slow_at):
                    period = 1.0 / hz
                    pacer = c.LoopPacer(timing=lambda period=period: (0.0, period))
                    pacer.refresh()
                    self._drive(pacer, hz, lambda i, t, p=period, at=slow_at: 3 * p if abs(t - at) < p / 2
                                else 0.2 * p, 1.0)
                    self.assertEqual((pacer.cadence, pacer.switches), (1, 0))

    def test_p1_two_slow_frames_in_a_short_window_do_lock_at_60_hz(self):
        """The other side of LOCK_MIN_OVER: two frames over 0.8 P within P5's window at 60 Hz (about
        30 frames, whose nearest-rank p95 is the second-worst frame) are P5's own rule, and lock."""
        pacer = c.LoopPacer(timing=lambda: (0.0, 1 / 60))
        pacer.refresh()
        frames = self._drive(pacer, 60, lambda i, t: 0.015 if i in (20, 24) else 0.004, 1.0)
        self.assertEqual(pacer.switches, 1)
        self.assertEqual([round(t * 60) for t, _w, cadence in frames if cadence == 2][0], 24)

    def test_p1_a_pause_starts_a_new_run_whose_first_quarter_second_never_locks(self):
        """Frames from before an idle pause (longer than ``run_gap()``) neither lock the next run nor
        count toward its span: 0.2 s of heavy frames, 0.15 s idle, 0.2 s of heavy frames stay at the
        full rate; the second run locks once it has itself run 0.25 s."""
        period = 1 / 240
        pacer = c.LoopPacer(timing=lambda: (0.0, period))
        pacer.refresh()
        heavy = lambda i, t: 0.8 * period + 0.0005  # noqa: E731
        self._drive(pacer, 240, heavy, 0.2)
        self.assertGreater(0.15, pacer.run_gap())
        second = self._drive(pacer, 240, heavy, 0.2, t0=0.35)
        self.assertEqual((pacer.cadence, pacer.switches, pacer.runs), (1, 0, 2))
        third = self._drive(pacer, 240, heavy, 0.2, t0=second[-1][0] + period)
        self.assertEqual(pacer.runs, 2)                                        # no pause: the same run
        locked = [t for t, _w, cadence in third if cadence == 2]
        self.assertTrue(locked)
        self.assertGreaterEqual(locked[0], 0.35 + pacer.LOCK_MIN_SPAN_S - 1e-9)
        slow = c.LoopPacer(timing=lambda: (0.0, 1 / 60))
        slow.refresh()
        self.assertGreater(slow.run_gap(), 5 / 60)             # a locked 60 Hz loop with work over 3 P is no pause

    def test_p4_judges_pacing_by_the_interval_between_wakes(self):
        pacer = c.LoopPacer(timing=lambda: (0.0, 1 / 240))
        pacer.refresh()
        self.assertTrue(pacer.judge(1.0))
        self.assertFalse(pacer.judge(1.001))                               # < 0.5 P after the last one
        self.assertTrue(pacer.judge(1.001 + 1 / 240))
        self.assertEqual(pacer.late_wakes, 1)

    def test_p3_the_compositor_clock_and_g1_2_no_clock_waits_one_period_on_the_timer(self):
        timer = []
        results = [("tick", None), ("no_clock", 0xC01E0006), ("handle", 0)]
        pacer = c.LoopPacer(timing=lambda: (0.0, 1 / 240), clock_wait=lambda handles, ms: results.pop(0),
                            timer_wait=lambda handles, seconds: timer.append(seconds), handles=(7,))
        pacer.refresh()
        self.assertEqual(pacer.wait(), "tick")
        self.assertEqual(timer, [])
        self.assertEqual(pacer.wait(), "timer")                             # never a loop on the call
        self.assertAlmostEqual(timer[0], 1 / 240)
        self.assertEqual(pacer.wait(), "handle")
        self.assertEqual(pacer.counts["no_clock"], 1)

    def test_display_off_stops_the_wait_and_flush_is_the_fallback(self):
        pacer = c.LoopPacer(display_on=lambda: False, clock_wait=lambda h, ms: ("tick", None))
        self.assertEqual(pacer.wait(), "display_off")
        flushes = []
        pacer = c.LoopPacer(flush=lambda: flushes.append(1) or 0)
        self.assertEqual(pacer.wait(), "tick")
        self.assertEqual(flushes, [1])

    def test_the_120_lock_waits_two_ticks(self):
        ticks = []
        pacer = c.LoopPacer(clock_wait=lambda h, ms: ticks.append(1) or ("tick", None))
        pacer.cadence = 2
        pacer.wait()
        self.assertEqual(len(ticks), 2)


class LoopStatsTests(unittest.TestCase):
    def test_an_episode_counts_distinct_vblanks_and_missed_frames(self):
        period = 1 / 240
        stats = c.LoopStats()
        stats.begin("picker", "turn", 0.0)
        t = 0.0
        for i in range(96):
            t += period * (3 if i == 50 else 1)                          # one double miss
            stats.frame("picker", t, 0.002)
        record = stats.end("picker", t, period, 0.0, rate_hz=240.0)
        self.assertEqual(record["frames"], 96)
        self.assertEqual(record["missed"], 1)
        self.assertEqual(record["double_missed"], 1)
        self.assertAlmostEqual(record["interval_ms"]["p50"], period * 1000, places=3)
        self.assertEqual(record["method"], "present_cadence")
        metrics = stats.metrics()
        self.assertEqual(metrics["picker"]["totals"]["turn"]["episodes"], 1)
        self.assertEqual(metrics["picker"]["worst"]["missed"], 1)

    def test_compose_plus_present_cpu_boost_and_rm_are_recorded(self):
        """WP7b-R2 (K4 5.2, 6.2, 6.3): present_ms and the per-frame compose + present sum (the
        picker budget), cpu_pct_one_core from the thread clock, boosted and rm per episode."""
        period = 1 / 240
        cpu = [5.0]
        stats = c.LoopStats(cpu_clock=lambda: cpu[0])
        stats.begin("picker", "turn", 0.0, rm=True)
        t = 0.0
        for i in range(100):
            t += period
            # compose alone stays at 3 ms; with the present every 10th frame is 7 ms
            stats.frame("picker", t, 0.003, 0.004 if i % 10 == 0 else 0.001)
        cpu[0] += 0.25 * t                                                # a quarter of one core
        record = stats.end("picker", t, period, 0.0, rate_hz=240.0, boosted=True)
        self.assertEqual(record["work_ms"], {"p95": 3.0, "max": 3.0})
        self.assertEqual(record["present_ms"], {"p95": 4.0, "max": 4.0})
        self.assertEqual(record["compose_present_ms"], {"p95": 7.0, "max": 7.0},
                         "a compose-only gate would pass this run; compose + present fails 5.6 ms")
        self.assertAlmostEqual(record["cpu_pct_one_core"], 25.0, places=1)
        self.assertIs(record["boosted"], True)
        self.assertIs(record["rm"], True)
        pooled = stats.metrics()["picker"]["pooled"]
        self.assertEqual(pooled["frames"], 100)
        self.assertAlmostEqual(c.hist_quantile(pooled["compose_present_ms"], 0.95), 7.1, places=3)   # bin edge
        self.assertAlmostEqual(c.hist_quantile(pooled["compose_present_ms"], 0.5), 4.1, places=3)
        totals = stats.metrics()["picker"]["totals"]["turn"]
        self.assertAlmostEqual(totals["cpu_s"] / totals["wall_s"], 0.25, places=3)

    def test_the_lock_and_the_re_registrations_are_attributed_per_episode(self):
        """The 2026-09-26 review: an episode says how many presents ran under the 120 lock and when the
        thumbnails re-registered (ms from its start, from the present's begin), in the record and in
        ``recent`` (kind, t0, t_end, chrome, loop); frames without the facts count in neither."""
        period = 1 / 240
        stats = c.LoopStats(cpu_clock=lambda: 0.0)
        stats.begin("picker", "snap", 10.0, switches=3)
        t = 10.0
        for i in range(40):
            t += period * (2 if i >= 10 else 1)
            stats.frame("picker", t, 0.001, 0.0005, cadence=2 if i >= 10 else 1,
                        rereg_s=0.0015 if i in (3, 20) else None)
        stats.frame("picker", t + period, 0.001)                             # an old caller: no facts
        record = stats.end("picker", t + 2 * period, period, 10.0, switches=4)
        self.assertEqual((record["locked_frames"], record["paced_frames"], record["rereg_frames"]), (30, 40, 2))
        self.assertEqual(record["rereg_ms"], {"p95": 1.5, "max": 1.5})
        kind, t0, t_end, chrome, loop = stats.metrics()["picker"]["recent"][-1]
        self.assertEqual((kind, t0), ("snap", 10.0))
        self.assertEqual(loop["presents"], 41)
        self.assertEqual(loop["cadence_switches"], 1)
        first = (4 * period - 0.0005) * 1000.0                             # frame 3's present began 0.5 ms early
        self.assertAlmostEqual(loop["rereg_at_ms"][0], round(first, 1), places=6)
        self.assertEqual(len(loop["rereg_at_ms"]), 2)
        self.assertEqual(loop["rereg_ms_max"], 1.5)
        stats.metrics()["picker"]["recent"][-1][4]["rereg_at_ms"].append(99.0)   # a copy, not the record
        self.assertEqual(len(stats.metrics()["picker"]["recent"][-1][4]["rereg_at_ms"]), 2)

    def test_episode_kinds_are_k4s_and_pooled_histograms_subtract(self):
        stats = c.LoopStats(cpu_clock=lambda: 0.0)
        stats.begin("picker", "bump", 0.0)                                 # not a K4 6.2 kind: a turn
        stats.frame("picker", 0.004, 0.001, 0.001)
        self.assertEqual(stats.end("picker", 0.01, 1 / 240)["kind"], "turn")
        before = stats.metrics()["picker"]["pooled"]["compose_present_ms"]
        stats.begin("picker", "snap", 1.0)
        for i in range(10):
            stats.frame("picker", 1.0 + i / 240, 0.004, 0.002)
        stats.end("picker", 1.1, 1 / 240)
        after = stats.metrics()["picker"]["pooled"]["compose_present_ms"]
        delta = c.hist_delta({str(k): v for k, v in after.items()}, before)   # as JSON gives them back
        self.assertEqual(sum(delta.values()), 10)
        self.assertAlmostEqual(c.hist_quantile(delta, 0.95), 6.1, places=3)
        self.assertIsNone(c.hist_quantile({}, 0.95))
        self.assertTrue(set(c.EPISODE_KINDS) >= {"open", "turn", "close", "snap", "toast"})


class PlaceholderTests(unittest.TestCase):
    def test_caption_stubs(self):
        for size in ((200, 54), (1200, 80), (1000, 200), None, (0, 0)):
            self.assertTrue(R.is_caption_stub(size), size)
        for size in ((1157, 856), (2396, 1364), (400, 101)):
            self.assertFalse(R.is_caption_stub(size), size)

    def test_placeholder_rules(self):
        self.assertTrue(c.uses_placeholder(False, True, False, False, False))    # closed
        self.assertTrue(c.uses_placeholder(True, False, True, False, True))      # failed: never retried
        self.assertTrue(c.uses_placeholder(True, False, False, True, True))      # minimized stub
        self.assertTrue(c.uses_placeholder(True, False, False, False, False))    # no thumbnail coming
        self.assertFalse(c.uses_placeholder(True, True, False, False, False))
        self.assertFalse(c.uses_placeholder(True, False, False, False, True))    # registered right after the flush


if __name__ == "__main__":
    unittest.main()
