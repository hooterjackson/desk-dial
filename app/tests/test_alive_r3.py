"""Presentation 6 / Desk Dial r3 release 1 in the alive twin (ALIVE.md section 15; control_center.alive_lights).

Written out from the contract text: the LIGHTS family, the r3 arc (45 segments from 38 clockwise through the top to
22), the bri / ctemp / clusters targets and their classes, the Kelvin colour as an ACCENT drawn as is (no sat(), no
WARM fallback, no amber / red, no embers), resting (L / F at 0.34, T / R / O dark), the local cursor (bri max 100,
clusters max count - 1, ctemp never), the active-mode button at 0.90, the power button nav (never red) and the
LIGHTS ok = the 700 ms green wash with no bloom. Byte parity with the firmware is alive_tests.py's (the r3
sequences of tests/tools/make_alive_sequences.py).
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center import alive_lights as al  # noqa: E402

LIGHTS_BUTTONS = [{'label': 'Home', 'enabled': True, 'icon': 'house'},
                  {'label': 'Scenes', 'enabled': True, 'icon': 'wand'},
                  {'label': 'Temp', 'enabled': True, 'icon': 'thermo'},
                  {'label': 'All off', 'enabled': True, 'icon': 'power'}]
ARC = [(38 + k) % 60 for k in range(45)]


def lights(ring, layout='lights', temp=False, feedback=None, led='color'):
    buttons = [dict(b) for b in LIGHTS_BUTTONS]
    if temp:
        buttons[2]['lit'] = 'on'
    frame = {'id': 7, 'mode': 'LIGHTS', 'target': '', 'value': '', 'detail': '', 'status': '', 'layout': layout,
             'ledStyle': led, 'buttons': buttons, 'ring': ring}
    if feedback:
        frame['feedback'] = feedback
    return frame


def bri(value, kelvin=3200):
    return {'style': 'bri', 'value': value, 'index': 0, 'count': 0, 'kelvin': kelvin}


def ctemp(value, kelvin):
    return {'style': 'ctemp', 'value': value, 'index': 0, 'count': 0, 'kelvin': kelvin}


def clusters(count, index):
    return {'style': 'clusters', 'value': 0, 'index': index, 'count': count}


class KelvinTests(unittest.TestCase):
    def test_formula_points(self):
        self.assertEqual(al.kelvin_rgb(2200), (255, 146, 39))
        self.assertEqual(al.kelvin_rgb(2700), (255, 167, 87))
        self.assertEqual(al.kelvin_rgb(3200), (255, 184, 123))
        self.assertEqual(al.kelvin_rgb(6500), (255, 254, 250))

    def test_clamped_and_monotonic(self):
        self.assertEqual(al.kelvin_rgb(1000), al.kelvin_rgb(2200))
        self.assertEqual(al.kelvin_rgb(9000), al.kelvin_rgb(6500))
        prev = al.kelvin_rgb(2200)
        for k in range(2300, 6600, 100):
            cur = al.kelvin_rgb(k)
            self.assertEqual(cur[0], 255)
            self.assertGreaterEqual(cur[1], prev[1])
            self.assertGreaterEqual(cur[2], prev[2])
            prev = cur

    def test_calibration_hook_is_identity(self):
        self.assertEqual(al.KELVIN_GAIN, (255, 255, 255))


class TargetTests(unittest.TestCase):
    def test_family(self):
        for layout in ('lights', 'lightsbig', 'scenes'):
            self.assertEqual(al.frame_family({'layout': layout}), 'lights')

    def test_bri_rest_and_turning(self):
        t = al.alive_targets(lights(bri(62)))
        n = (62 * 45 + 50) // 100
        self.assertEqual(n, 28)
        rgb = al.kelvin_rgb(3200)
        for k, seg in enumerate(ARC[:n]):
            cell = t.ring[seg]
            self.assertEqual(cell.role, al.ROLE_ACCENT)
            self.assertEqual(cell.rgb, rgb)                    # as is: never sat()
            if k >= n:
                self.assertIsNone(cell)                        # [user 2026-09-29] the unfilled arc is off
                continue
            self.assertEqual((cell.cls, cell.alpha), ('L', 0.34))
        for seg in range(23, 38):
            self.assertIsNone(t.ring[seg])                     # the bottom stays free
        self.assertEqual(t.cursor, ARC[n - 1])
        big = al.alive_targets(lights(bri(62), 'lightsbig'))
        self.assertEqual([big.ring[s].alpha for s in ARC[:n]], [1.0] * n)
        self.assertFalse(big.heat)

    def test_bri_full_and_zero(self):
        full = al.alive_targets(lights(bri(100, 6500), 'lightsbig'))
        self.assertTrue(all(full.ring[s].cls == 3 for s in ARC))
        self.assertEqual(full.cursor, 22)
        zero = al.alive_targets(lights(bri(0)))
        self.assertTrue(all(zero.ring[s] is None for s in ARC))      # [user 2026-09-29] nothing lit
        self.assertEqual(zero.cursor, 38)

    def test_white_kelvin_has_no_warm_fallback(self):
        t = al.alive_targets(lights(bri(50, 6500), led='white'))
        cell = t.ring[ARC[0]]
        self.assertEqual((cell.role, cell.rgb), (al.ROLE_ACCENT, (255, 254, 250)))

    def test_ctemp(self):
        m = (23 * 44 + 50) // 100
        t = al.alive_targets(lights(ctemp(23, 3200), temp=True))
        for k, seg in enumerate(ARC):
            cell = t.ring[seg]
            if k > m:
                self.assertIsNone(cell, k)                     # [user 2026-09-29] above the marker is off
                continue
            self.assertEqual((cell.cls, cell.alpha), (3, 1.0) if k == m else ('F', 0.5), k)
            self.assertEqual(cell.rgb, al.kelvin_rgb(3200))
        self.assertEqual(t.cursor, ARC[m])
        big = al.alive_targets(lights(ctemp(23, 3200), 'lightsbig', temp=True))
        self.assertTrue(all(big.ring[s].alpha == 1.0 for s in ARC[:m + 1]))

    def test_clusters(self):
        t = al.alive_targets(lights(clusters(5, 2), 'scenes'))
        centres = [(120 * c + 5) // 10 for c in range(5)]
        self.assertEqual(centres, [0, 12, 24, 36, 48])
        for c, centre in enumerate(centres):
            for k in (-1, 0, 1):
                cell = t.ring[(centre + k) % 60]
                self.assertEqual(cell.role, al.ROLE_WARM)
                self.assertEqual((cell.cls, cell.alpha), (3, 1.0) if c == 2 else ('O', 0.18))
        self.assertEqual(t.cursor, 24)
        self.assertEqual(sum(1 for c in t.ring if c), 15)
        full = al.alive_targets(lights(clusters(20, 19), 'scenes'))
        self.assertEqual(sum(1 for c in full.ring if c), 60)
        self.assertEqual(full.cursor, 57)

    def test_resting(self):
        t = al.alive_targets(lights(bri(62)), state_asleep=True)
        n = 28
        for k, seg in enumerate(ARC):
            cell = t.ring[seg]
            if k >= n:
                self.assertIsNone(cell)
                continue
            self.assertEqual((cell.role, cell.alpha), (al.ROLE_WARM, 0.34))
        s = al.alive_targets(lights(clusters(5, 1), 'scenes'), state_asleep=True)
        self.assertEqual(sorted(c.alpha for c in s.ring if c and c.alpha), [0.34] * 3)

    def test_local_cursor(self):
        t = al.alive_targets(lights(bri(62)), 70, 100)
        self.assertEqual(t.cursor, ARC[(70 * 45 + 50) // 100 - 1])
        self.assertEqual(al.alive_targets(lights(bri(62)), 70, 43).cursor, ARC[27])   # not the bri profile
        c = al.alive_targets(lights(clusters(5, 0), 'scenes'), 3, 4)
        self.assertEqual(c.cursor, 36)
        k = al.alive_targets(lights(ctemp(23, 3200), temp=True), 40, 43)
        self.assertEqual(k.cursor, ARC[(23 * 44 + 50) // 100])                   # ctemp: never local

    def test_buttons(self):
        t = al.alive_targets(lights(bri(62), temp=True))
        self.assertEqual((t.buttons[2].role, t.buttons[2].alpha), (al.ROLE_WARM, 0.90))
        self.assertEqual((t.buttons[3].role, t.buttons[3].alpha), (al.ROLE_WARM, 0.70))   # power: nav, never red
        home = al.alive_targets({'layout': 'explorer', 'ring': {'style': 'off', 'value': 0, 'index': 0, 'count': 0},
                                 'buttons': [{'label': 'R', 'enabled': True, 'icon': 'clock', 'lit': 'on'}] * 4})
        self.assertEqual(home.buttons[0].alpha, 1.0)                              # other families unchanged


class EngineTests(unittest.TestCase):
    def run_frames(self, lights_engine, frame, t0, t1, local=(None, None)):
        t = t0
        while t < t1:
            t += 20
            lights_engine.render(t, frame, *local)
        return t

    def test_ok_is_the_green_wash(self):
        e = al.AliveLights(0)
        e.claim(0)
        base = lights(clusters(5, 2), 'scenes')
        t = self.run_frames(e, base, 0, 3000)
        ran = dict(base, feedback={'kind': 'ok', 'seq': 5})
        e.render(t + 20, ran)
        self.assertEqual(e._flash, 'wash')
        self.assertFalse(any(fx.type == 'bloom' for fx in e.animator.effects))
        self.assertTrue(all(c.role == al.ROLE_GREEN and c.alpha == 0.68 for c in e.targets.ring))
        e.render(t + 700, ran)
        self.assertEqual(e._flash, 'wash')
        e.render(t + 740, ran)
        self.assertIsNone(e._flash)

    def test_err_keeps_the_fail(self):
        e = al.AliveLights(0)
        e.claim(0)
        base = lights(bri(40))
        t = self.run_frames(e, base, 0, 3000)
        e.render(t + 20, dict(base, feedback={'kind': 'err', 'seq': 5}))
        self.assertEqual(e._flash, 'err')
        self.assertTrue(any(fx.type == 'fail' for fx in e.animator.effects))

    def test_mode_reveal_on_entering_lights(self):
        e = al.AliveLights(0)
        e.claim(0)
        home = {'id': 1, 'layout': 'nowPlaying', 'ring': {'style': 'level', 'value': 40, 'index': 0, 'count': 101},
                'buttons': LIGHTS_BUTTONS}
        t = self.run_frames(e, home, 0, 3000)
        e.render(t + 20, lights(bri(40)))
        self.assertTrue(any(fx.type == 'reveal' for fx in e.animator.effects))


def queue(count, index, now=-1, colors=None):
    ring = {'style': 'queue', 'value': 0, 'index': index, 'count': count}
    if now >= 0:
        ring['now'] = now
    if colors:
        ring['colors'] = colors
    return {'id': 9, 'mode': 'TRACKS', 'target': '', 'value': '', 'detail': '', 'status': '', 'layout': 'tracks',
            'ledStyle': 'color', 'crumb': 'tracks', 'buttons': [dict(b) for b in LIGHTS_BUTTONS], 'ring': ring}


class R31Tests(unittest.TestCase):
    """[r3.1] ALIVE.md 15.8 (the button-4 hold ring and its landings) and 15.9 (the queue ring)."""

    def settle(self, frame, until=3000):
        e = al.AliveLights(0)
        e.claim(0)
        t = 0
        while t < until:
            t += 20
            e.render(t, frame)
        return e, t

    def test_queue_ring_focus_now_and_rest_off(self):
        g = al.alive_geometry(queue(24, 8, now=6, colors=[0x2050A0] * 20))
        lit = {i: cell for i, cell in enumerate(g.cells) if cell is not None}
        pos = lambda j: ARC[(2 * j * 44 + 23) // 46]
        self.assertEqual(set(lit), {pos(8) - 1, pos(8), pos(8) + 1, pos(6)})
        self.assertEqual(lit[pos(6)], (al.ROLE_ACCENT, al.CLASS_W, al.QUEUE_NOW_RGB))
        self.assertEqual(lit[pos(8)][:2], (al.ROLE_ACCENT, 3))
        self.assertEqual(g.cursor, pos(8))

    def test_queue_ring_warm_without_colour_and_local_focus(self):
        g = al.alive_geometry(queue(24, 8, now=6), 12, 23)
        self.assertEqual(g.cells[ARC[(2 * 12 * 44 + 23) // 46]][:2], (al.ROLE_WARM, 3))

    def test_hold4_needs_the_hold_marker(self):
        home = lights(bri(40), 'lights')
        e, t = self.settle(home)
        e.press(t, 3)
        for _ in range(40):
            t += 20
            e.render(t, home)
        self.assertIsNone(e._landing_at)
        self.assertFalse(e._hold4_matured)

    def test_hold4_ring_shows_from_15_percent_and_lands_with_the_sweep(self):
        home = dict(lights(bri(40, 3000)), holdMarker=True)
        e, t = self.settle(home)
        e.press(t, 3)
        start = t
        e.render(start + 140, home)
        self.assertTrue(all(c is None or c.alpha < 1.0 or c.role != al.ROLE_WARM for c in e.targets.ring))
        e.render(start + 600, home)
        filled = [i for i in ARC if e.targets.ring[i] is not None and e.targets.ring[i].role == al.ROLE_WARM
                  and e.targets.ring[i].alpha == 1.0]
        self.assertEqual(len(filled), 27)
        e.render(start + 1000, home)
        self.assertEqual(e._landing_at, start + 1000)
        landed = dict(home, feedback={'kind': 'ok', 'seq': 3})
        before = e.render(start + 1044, home)[0]
        e.render(start + 1060, landed)
        self.assertEqual(e._flash, 'land')
        # r4 M12 (ALIVE.md 16): no wash; the ring is the frame's own (the Kelvin arc) and each LED starts easing to it
        # i x 8.7 ms after the landing, clockwise from 12 o'clock.
        self.assertEqual(e._sweep_at, start + 1060)
        self.assertTrue(all(c is None or c.alpha != 0.68 for c in e.targets.ring))
        ring = e.render(start + 1060 + 100, landed)[0]
        self.assertEqual(ring[50], before[50])                        # 50 x 8.7 = 435 ms: not yet
        self.assertNotEqual(ring[0], before[0])
        e.render(start + 1060 + 800, landed)
        self.assertIsNone(e._flash)
        self.assertIsNone(e._sweep_at)

    def test_no_hold_rings_on_the_app_canvas(self):
        # 1.0.0-cc5.6 (A2): Onshape's app frames (1 ZOOM, 4 PAN; Home = all four held 1 s) never draw the hold-1 ring /
        # home flash or the hold-4 ring / landing, even with a crumb and holdMarker (cc_alive.cpp mirrors this).
        base = dict(queue(12, 3), layout='recent', crumb='recent', holdMarker=True)
        base['ring'] = {'style': 'selection', 'value': 0, 'index': 3, 'count': 12}
        app = dict(base, app={'id': 'onshape', 'slot': 'zoom'})
        e, t = self.settle(app)
        e.press(t, 0)
        e.press(t, 3)
        warm = lambda: [c for c in e.targets.ring if c is not None and c.role == al.ROLE_WARM and c.alpha == 1.0]
        for dt in range(20, 1300, 20):
            e.render(t + dt, app)
            self.assertLessEqual(len(warm()), 1, dt)   # the selection cursor only, never the hold fill
        self.assertNotEqual(e._flash, 'home')
        self.assertFalse(e._hold_matured or e._hold4_matured)
        self.assertIsNone(e._landing_at)
        e.key_up(t + 1300, 0)
        e.key_up(t + 1300, 3)
        e.press(t + 1400, 0)                     # the same frame without `app`: the hold-1 flash again
        e.render(t + 2020, base)
        self.assertEqual(e._flash, 'home')

    def test_queued_lands_green_and_late_feedback_is_usual(self):
        base = dict(queue(12, 3), layout='recent', crumb='recent', holdMarker=True)
        base['ring'] = {'style': 'selection', 'value': 0, 'index': 3, 'count': 12}
        e, t = self.settle(base)
        e.press(t, 3)
        e.render(t + 1000, base)
        e.render(t + 1100, dict(base, feedback={'kind': 'ok', 'seq': 4, 'moment': 'queued'}))
        self.assertEqual(e._flash, 'queue')
        self.assertFalse(any(fx.type == 'sweep' for fx in e.animator.effects))
        e.key_up(t + 1200, 3)
        e.press(t + 3000, 3)
        e.render(t + 4000, base)
        e.render(t + 5600, dict(base, feedback={'kind': 'ok', 'seq': 5, 'moment': 'queued'}))
        self.assertIsNone(e._flash)
        self.assertTrue(any(fx.type == 'sweep' for fx in e.animator.effects))


if __name__ == '__main__':
    unittest.main()
