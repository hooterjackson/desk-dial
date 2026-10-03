"""FW-DES-001 (mirror side): the list title's first line clears the crumb's ink, as cc_display crumbClearHalf.

The knob caps list.title line 1 at the shown crumb's clearance (both masks, alpha >= 32, 2 px gap, over the
line's ink rows); the desktop mirror (lcd_preview) must fit the same lines or cc54_report mirror_parity fails.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from control_center import crumb_arc  # noqa: E402
from control_center import lcd_preview as lp  # noqa: E402


def oracle_half(token, top, bottom):
    """Independent restatement of the spec: 2 px clear of every crumb px (alpha >= 32) on rows [top, bottom]."""
    half = 120
    for mask in crumb_arc.render(token):
        if mask is None:
            continue
        for j in range(mask.h):
            y = mask.y + j
            if not top <= y <= bottom:
                continue
            for i in range(mask.w):
                if mask.data[j * mask.w + i] < 32:
                    continue
                px = mask.x + i
                half = min(half, ((119 - px) if px < 120 else (px - 120)) - 2)
    return max(half, 0)


def ink_band(text, label=lp.LIST_TITLE, row=0):
    ink = lp.ink_rows(text, label.size)
    base = label.baseline + row * label.pitch
    return ink, base + ink[0], base + ink[1]


class CrumbClearTests(unittest.TestCase):
    def test_half_matches_the_spec_for_every_token(self):
        for token in crumb_arc.TOKENS:
            for text in ('Ásæla ljósbrot', 'Stay', 'gypsy'):
                _, top, bottom = ink_band(text)
                with self.subTest(token=token, text=text):
                    self.assertEqual(lp.crumb_clear_half(token, lp.LIST_TITLE.centre, top, bottom),
                                     oracle_half(token, top, bottom))

    def test_recent_crumb_wraps_the_title_the_knob_wraps(self):
        text = 'Ásæla ljósbrot'
        self.assertEqual(lp.fit_label(lp.LIST_TITLE, text)[0], [text])            # no crumb: one line
        lines, widths = lp.fit_label(lp.LIST_TITLE, text, 'recent')
        self.assertEqual(lines, ['Ásæla', 'ljósbrot'])
        ink, top, bottom = ink_band(text)
        self.assertEqual(widths[0], 2 * oracle_half('recent', top, bottom))
        self.assertLess(widths[0], lp.LIST_TITLE.line_width(ink, 0))
        self.assertEqual(widths[1], lp.LIST_TITLE.line_width(ink, 1))             # line 2 never clamped

    def test_line_one_ink_stays_clear_of_the_crumb(self):
        text = 'Stay Kingdom Come Again'
        for token in ('recent', 'onScreenRecent', 'upnext'):
            lines, widths = lp.fit_label(lp.LIST_TITLE, text, token)
            first = lp.text_width(lines[0], 22)
            self.assertLessEqual(first, widths[0])
            span = (lp.LIST_TITLE.centre - (first + 1) // 2, lp.LIST_TITLE.centre + (first + 1) // 2)
            _, top, bottom = ink_band(text)
            for mask in crumb_arc.render(token):
                if mask is None:
                    continue
                for j in range(mask.h):
                    if not top <= mask.y + j <= bottom:
                        continue
                    hits = [mask.x + i for i in range(mask.w)
                            if mask.data[j * mask.w + i] >= 32 and span[0] <= mask.x + i < span[1]]
                    self.assertEqual(hits, [], f'{token} row {mask.y + j}')

    def test_crumb_without_ink_on_the_rows_and_other_labels_unchanged(self):
        ink, top, bottom = ink_band('Ásæla ljósbrot')
        self.assertEqual(lp.LIST_TITLE.line_width(ink, 0, 'music'), lp.LIST_TITLE.line_width(ink, 0))
        self.assertEqual(lp.LIST_TITLE.line_width(ink, 0, ''), lp.LIST_TITLE.line_width(ink, 0))
        self.assertEqual(lp.LIST_TITLE.line_width(None, 0, 'recent'), 170)
        self.assertFalse(lp.TRACKS_TITLE.crumb_clear)
        tracks_ink = lp.ink_rows('Ásæla ljósbrot', lp.TRACKS_TITLE.size)
        self.assertEqual(lp.TRACKS_TITLE.line_width(tracks_ink, 0, 'recent'), lp.TRACKS_TITLE.line_width(tracks_ink, 0))

    def test_scene_label_uses_the_scene_crumb(self):
        scene = lp.Scene('recent')
        scene.crumb = 'recent'
        lp._label(scene, 'title', lp.LIST_TITLE, 'Ásæla ljósbrot', lp.INK_RGB)
        self.assertEqual([r.text for r in scene.texts('title')], ['Ásæla', 'ljósbrot'])
        plain = lp.Scene('recent')
        lp._label(plain, 'title', lp.LIST_TITLE, 'Ásæla ljósbrot', lp.INK_RGB)
        self.assertEqual([r.text for r in plain.texts('title')], ['Ásæla ljósbrot'])


if __name__ == '__main__':
    unittest.main()
