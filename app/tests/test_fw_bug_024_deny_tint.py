"""FW-BUG-024: the deny glow (flash "refused", ACCENT cells 26..34) never triggers the 5.4 ambient tint.

The tint rule reads ring[cursor] after the 5.2 overrides; a list cursor inside 26..34 used to pick up the deny glow's
ACCENT cell and tint the dark ring for the 480 ms window. cc_alive.cpp mirrors this (alive_tests.cpp targets checks).
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center import alive_lights as al  # noqa: E402

BUTTONS = [{'label': 'Back', 'enabled': True, 'icon': 'back'},
           {'label': 'Home', 'enabled': True, 'icon': 'house'},
           {'label': 'Windows', 'enabled': True, 'icon': 'win'},
           {'label': 'Play', 'enabled': True, 'icon': 'play'}]


def recent(count, index, colors=None):
    ring = {'style': 'selection', 'value': 0, 'index': index, 'count': count}
    if colors is not None:
        ring['colors'] = colors
    return {'id': 3, 'mode': 'RECENTLY ADDED', 'target': '', 'value': '', 'detail': '', 'status': '',
            'layout': 'recent', 'crumb': 'recent', 'ledStyle': 'color', 'buttons': [dict(b) for b in BUTTONS],
            'ring': ring}


class DenyGlowTintTests(unittest.TestCase):
    def test_targets_never_tint_under_the_deny_glow(self):
        inside = 0
        for count in (9, 19, 30):
            for index in range(count):
                for colors in (None, [0x2050A0] * min(count, 20)):
                    g = al.alive_geometry(recent(count, index, colors))
                    if g.family not in al.LIST_FAMILIES:
                        continue
                    if g.cursor in al.REFUSED_SEGMENTS:
                        inside += 1
                    tg = al.alive_finish(g, False, 'refused')
                    self.assertIsNone(tg.tint, (count, index, colors is not None, g.cursor))
        self.assertGreater(inside, 0, 'some cursor must land inside the deny glow')

    def test_landing_keeps_the_cursor_tint(self):
        g = al.alive_geometry(recent(9, 4, [0x2050A0] * 9))
        self.assertIsNotNone(al.alive_finish(g, False, None).tint)
        self.assertIsNotNone(al.alive_finish(g, False, 'land').tint)

    def test_deny_glow_never_tints_the_ring(self):
        frame = recent(19, 18)
        e = al.AliveLights(0)
        e.claim(0)
        t = 0
        while t < 3000:
            t += 20
            e.render(t, frame)
        refused = dict(frame, feedback={'kind': 'err', 'seq': 5, 'moment': 'refused'})
        start = t
        seen = False
        while t < start + 480:
            t += 20
            ring = e.render(t, refused)[0]
            if e._flash == 'refused':
                seen = True
            self.assertIsNone(e.targets.tint, t - start)
        self.assertTrue(seen, 'the refused press must start the deny glow')
        self.assertTrue(max(abs(c) for c in e.animator.tint) < 1e-3, e.animator.tint)
        del ring


if __name__ == '__main__':
    unittest.main()
