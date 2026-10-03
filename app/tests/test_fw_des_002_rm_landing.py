"""FW-DES-002: under reduced motion the r4 M12 domain-swap landing is a blend, not a sweep (r4 section 7, MOTION.md
M12): no LED waits for its i x 8.7 ms turn. Default motion still sweeps. cc_alive.cpp mirrors this (alive_tests.cpp
r4Checks section 5).
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center import alive_lights as al  # noqa: E402

BUTTONS = [{'label': 'Home', 'enabled': True, 'icon': 'house'},
           {'label': 'Scenes', 'enabled': True, 'icon': 'wand'},
           {'label': 'Temp', 'enabled': True, 'icon': 'thermo'},
           {'label': 'All off', 'enabled': True, 'icon': 'power'}]


def home():
    return {'id': 7, 'mode': 'LIGHTS', 'target': '', 'value': '', 'detail': '', 'status': '', 'layout': 'lights',
            'ledStyle': 'color', 'buttons': [dict(b) for b in BUTTONS], 'holdMarker': True,
            'ring': {'style': 'bri', 'value': 40, 'index': 0, 'count': 0, 'kelvin': 3000}}


def land(reduced):
    """Settle, hold button 4 to maturity, land a plain ok; returns (engine, ring before, first frame, frame +480)."""
    e = al.AliveLights(0)
    e.claim(0)
    frame = home()
    t = 0
    while t < 3000:
        t += 20
        e.render(t, frame)
    if reduced:
        e.set_reduced_motion(t, True)
    e.press(t, 3)
    start = t
    while t < start + 1000:
        t += 20
        e.render(t, frame)
    before = e.render(t + 20, frame)[0]
    landed = dict(frame, feedback={'kind': 'ok', 'seq': 3})
    first = e.render(t + 40, landed)[0]
    assert e._flash == 'land', e._flash
    later = None
    for dt in range(60, 540, 20):
        later = e.render(t + dt, landed)[0]
    return e, before, first, later, t


class ReducedMotionLandingTests(unittest.TestCase):
    def held(self, before, first, later):
        return [i for i in range(al.SEGMENTS) if first[i] == before[i] and later[i] != before[i]]

    def test_default_motion_still_sweeps(self):
        e, before, first, later, _ = land(False)
        self.assertGreater(len(self.held(before, first, later)), 0)

    def test_reduced_motion_landing_is_a_blend(self):
        e, before, first, later, t = land(True)
        self.assertTrue(e.reduced_motion)
        self.assertIsNone(e._sweep_at)
        moved = [i for i in range(al.SEGMENTS) if later[i] != before[i]]
        self.assertGreater(len(moved), 0)
        self.assertEqual(self.held(before, first, later), [])


if __name__ == '__main__':
    unittest.main()
