"""FW-BUG-026: the r3 Windows marker ring has no sub-floor rest segments ([user 2026-10-03]).

Like the Lights arcs and the queue ring (ALIVE.md 15.2, 15.9), only the white marker +-1 is drawn; every other arc
segment is off (no target, so no F-T floor: byte 0x000000 at drive 150). The design's rest class M (WARM 0.10,
#020100) is not drawn; CLASS_M stays in the class tables. The firmware's draw_marker (cc_alive.cpp) is pinned to the
same rule; byte parity of the two engines is alive_tests.py's (r3-refused-marker sequence).
"""
from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center import alive_lights as al  # noqa: E402

ARC = [(38 + k) % 60 for k in range(45)]
FIRMWARE = ROOT.parent / 'firmware' / 'src' / 'cc_alive.cpp'


def windows(count, index):
    buttons = [{'label': 'Home', 'enabled': True, 'icon': 'house'},
               {'label': 'Snap left', 'enabled': True, 'icon': 'snapleft'},
               {'label': 'Snap right', 'enabled': True, 'icon': 'snapright'},
               {'label': 'Switch', 'enabled': True, 'icon': 'switch'}]
    return {'id': 1, 'mode': 'WINDOWS', 'target': '', 'value': '', 'detail': '', 'status': '', 'activity': 'idle',
            'layout': 'windows', 'ledStyle': 'color', 'buttons': buttons, 'crumb': 'windows',
            'ring': {'style': 'marker', 'value': 0, 'index': index, 'count': count}}


def pos(count, index):
    span = max(1, count - 1)
    return (2 * index * 44 + span) // (2 * span)


class MarkerRestTests(unittest.TestCase):
    def check(self, count, index, asleep):
        t = al.alive_targets(windows(count, index), state_asleep=asleep)
        p = pos(count, index)
        for k, seg in enumerate(ARC):
            cell = t.ring[seg]
            if abs(k - p) > 1:
                self.assertIsNone(cell, (count, index, k))
            else:
                self.assertIsNotNone(cell, (count, index, k))
                self.assertEqual(cell.cls, 3)
                if not asleep:
                    self.assertEqual((cell.role, cell.rgb), (al.ROLE_ACCENT, al.MARKER_RGB))
        self.assertEqual(t.cursor, ARC[p])
        self.assertFalse(any(c is not None and c.cls == al.CLASS_M for c in t.ring))
        ring_lit, _ = al.lit_masks(t)
        e = [(0.0, 0.0, 0.0) if c is None else tuple(min(1.0, x / 255 * c.alpha) for x in c.rgb) for c in t.ring]
        out, _ = al.reference_output(e, [(0.0, 0.0, 0.0)] * al.BUTTON_SLOTS, drive=150, ring_lit=ring_lit,
                                     button_lit=[False] * al.BUTTON_SLOTS)
        for k, seg in enumerate(ARC):
            if abs(k - p) > 1:
                self.assertEqual(out[seg], 0, (count, index, k))

    def test_marker_rest_is_off(self):
        self.check(8, 3, asleep=False)

    def test_bounds_and_sizes(self):
        for count, index in ((8, 0), (8, 7), (1, 0), (2, 1), (24, 11), (67, 66)):
            self.check(count, index, asleep=False)
            self.check(count, index, asleep=True)

    def test_class_m_stays_in_the_tables(self):
        self.assertIn(al.CLASS_M, al.CLASSES)

    def test_firmware_draw_marker_has_no_rest_class(self):
        if not FIRMWARE.is_file():
            self.skipTest('firmware tree absent')
        src = FIRMWARE.read_text(encoding='utf-8')
        body = re.search(r'int draw_marker\(.*?\n}\n', src.replace('\r\n', '\n'), re.S)
        self.assertIsNotNone(body)
        self.assertNotIn('CC_ALIVE_CLASS_M', body.group(0))
        self.assertIn('CC_ALIVE_CLASS_3, markerRgb', body.group(0))


if __name__ == '__main__':
    unittest.main()
