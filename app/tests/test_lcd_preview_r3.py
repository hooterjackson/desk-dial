"""Presentation 6 (Desk Dial r3 release 1) in the floating knob's LCD mirror (control_center.lcd_preview).

PRESENTATION_V5.md section 19: lights = the Home text drawing with `meta` on the 12 px line, lightsbig = the reveal
with the unit valueUnit ("%" | "K"), scenes = prev / current / next + meta; no art on any of them; the six r3 icons
have firmware masks; v6_parse reads the presentation-6 parser rules (its C++ parity is harness
parse_tests.py over fixtures/frames_v6.json, the pixel/string parity cc54_report.py mirror_parity).
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center import lcd_preview as lp  # noqa: E402

BUTTONS = [{'label': 'Home', 'enabled': True, 'icon': 'house'}, {'label': 'Scenes', 'enabled': True, 'icon': 'wand'},
           {'label': 'Temp', 'enabled': True, 'icon': 'thermo', 'lit': 'on'},
           {'label': 'All off', 'enabled': True, 'icon': 'power'}]


def frame(layout, **extra):
    out = {'mode': 'LIGHTS', 'target': '', 'value': '', 'detail': '', 'status': 'NOT DRAWN', 'layout': layout,
           'heading': 'LIGHTS', 'artKey': 'k-hall', 'buttons': [dict(b) for b in BUTTONS],
           'ring': {'style': 'bri', 'value': 62, 'index': 0, 'count': 0, 'kelvin': 3200}}
    out.update(extra)
    return out


def texts(scene):
    return {(item.role, item.text) for item in scene.items if hasattr(item, 'text')}


class ComposeTests(unittest.TestCase):
    def test_lights_text(self):
        scene = lp.compose(frame('lights', title='Focus', subtitle='62% · 3200 K', meta='Knob: temperature',
                                 metaTone='secondary'))
        got = texts(scene)
        self.assertIn(('title', 'Focus'), got)
        self.assertIn(('status', 'Knob: temperature'), got)
        self.assertNotIn(('status', 'NOT DRAWN'), got)
        self.assertFalse(scene.art)
        status = [i for i in scene.items if getattr(i, 'role', '') == 'status'][0]
        self.assertEqual(status.ink, (0xA6, 0xA6, 0xA6))
        self.assertEqual([i.name for i in scene.items if getattr(i, 'role', '') == 'footer'],
                         ['house', 'wand', 'thermo', 'power'])

    def test_lightsbig_units(self):
        k = texts(lp.compose(frame('lightsbig', volumeCaption='Colour temperature', value='3200', valueUnit='K')))
        self.assertIn(('digits', '3200'), k)
        self.assertIn(('percent', 'K'), k)
        self.assertIn(('caption', 'Colour temperature'), k)
        p = texts(lp.compose(frame('lightsbig', volumeCaption='Brightness', value='62')))
        self.assertIn(('percent', '%'), p)
        stripped = texts(lp.compose(frame('volume', value='54%', valueUnit='K')))
        self.assertIn(('percent', '%'), stripped)

    def test_scenes(self):
        scene = lp.compose(frame('scenes', title='Movie', prevTitle='Evening', nextTitle='Reading',
                                 meta='3 / 5 · 12% · 2200 K',
                                 ring={'style': 'clusters', 'value': 0, 'index': 2, 'count': 5}))
        got = texts(scene)
        for want in (('prev', 'Evening'), ('title', 'Movie'), ('next', 'Reading')):
            self.assertIn(want, got)
        prev = [i for i in scene.items if getattr(i, 'role', '') == 'prev'][0]
        self.assertEqual(prev.ink, (0x7C, 0x7C, 0x7C))
        self.assertFalse(scene.art)
        on_lights = texts(lp.compose(frame('lights', title='Focus', prevTitle='Evening')))
        self.assertNotIn(('prev', 'Evening'), on_lights)

    def test_render(self):
        image = lp.render_lcd(frame('scenes', title='Movie', prevTitle='Evening', nextTitle='Reading',
                                    ring={'style': 'clusters', 'value': 0, 'index': 2, 'count': 5}))
        self.assertEqual(image.size, (240, 240))

    def test_icon_masks(self):
        for name in lp.ICONS_V6:
            self.assertTrue(lp.knob_has_mask(name, 20), name)
            self.assertIsNotNone(lp.icon_mask(name, 20), name)
        self.assertTrue(lp.knob_has_mask('bulb', 26))
        self.assertFalse(lp.knob_has_mask('power', 26))


class V6ParseTests(unittest.TestCase):
    def test_valid(self):
        stored, invalid = lp.v6_parse(frame('lightsbig', valueUnit='K',
                                            ring={'style': 'ctemp', 'value': 23, 'index': 0, 'count': 0,
                                                  'kelvin': 3200}))
        self.assertEqual(invalid, [])
        self.assertEqual((stored['ringKelvin'], stored['valueUnit']), (3200, 'K'))

    def test_rejects(self):
        for bad in (frame('lights', ring={'style': 'bri', 'value': 1, 'index': 0, 'count': 0}),
                    frame('lights', ring={'style': 'bri', 'value': 1, 'index': 0, 'count': 0, 'kelvin': 7000}),
                    frame('scenes', ring={'style': 'clusters', 'value': 0, 'index': 0, 'count': 21}),
                    frame('lightsbig', valueUnit='k'), frame('scenes', prevTitle=3), frame('lamp')):
            self.assertTrue(lp.v6_parse(bad)[1], bad)

    def test_strips(self):
        stored, invalid = lp.v6_parse(frame('lights', valueUnit='K', prevTitle='x',
                                            ring={'style': 'level', 'value': 1, 'index': 0, 'count': 101,
                                                  'kelvin': 4000}))
        self.assertEqual(invalid, [])
        self.assertEqual((stored['valueUnit'], stored['prevTitle'], stored['ringKelvin']), ('%', '', 0))


class R31Tests(unittest.TestCase):
    """[r3.1] PRESENTATION_V5 19.10 in the mirror: the Tracks position row only on transport, the hold tick, the
    paused cover at 0.45, v6_parse of queue / holdMarker / the playlists crumb."""

    def tracks(self, style):
        ring = {'style': style, 'value': 0, 'index': 1, 'count': 3 if style == 'transport' else 24}
        return {'mode': 'TRACKS', 'target': '', 'value': '', 'detail': '', 'status': '', 'layout': 'tracks',
                'title': 'Song', 'buttons': [dict(b) for b in BUTTONS], 'ring': ring}

    def test_position_row_only_with_transport(self):
        self.assertEqual(len(lp.compose(self.tracks('transport')).icons('track-position')), 3)
        self.assertEqual(lp.compose(self.tracks('queue')).icons('track-position'), [])
        self.assertEqual(lp.compose(self.tracks('selection')).icons('track-position'), [])

    def test_hold_tick_with_the_footer_only(self):
        self.assertTrue(lp.compose(dict(self.tracks('queue'), holdMarker=True)).hold_tick)
        self.assertFalse(lp.compose(self.tracks('queue')).hold_tick)
        idle = frame('idle', holdMarker=True, ring={'style': 'level', 'value': 5, 'index': 0, 'count': 101},
                     mode='VOLUME')
        self.assertFalse(lp.compose(idle).hold_tick)

    def test_paused_cover(self):
        home = frame('nowPlaying', mode='VOLUME', ring={'style': 'level', 'value': 5, 'index': 0, 'count': 101})
        self.assertTrue(lp.compose(dict(home, playing=False)).art_paused)
        self.assertFalse(lp.compose(dict(home, playing=True)).art_paused)
        self.assertFalse(lp.compose(dict(self.tracks('queue'), playing=False)).art_paused)

    def test_v6_parse_r31(self):
        stored, invalid = lp.v6_parse(dict(self.tracks('queue'), holdMarker=True, crumb='playlists',
                                           ring={'style': 'queue', 'value': 0, 'index': 3, 'count': 5, 'now': 1}))
        self.assertEqual(invalid, [])
        self.assertEqual((stored['ringStyle'], stored['ringNow'], stored['holdMarker'], stored['crumb']),
                         ('queue', 1, True, 'playlists'))
        self.assertIn('queue', lp.v6_parse(dict(self.tracks('queue'),
                                                ring={'style': 'queue', 'value': 0, 'index': 5, 'count': 5}))[1])
        self.assertIn('holdMarker', lp.v6_parse(dict(self.tracks('queue'), holdMarker=1))[1])


    def test_music_idle_keeps_its_crumb(self):
        """2026-09-29 (r3.1 prototype arcOp): only Home idle hides the crumb (it is sent without one); Music
        idle keeps MUSIC."""
        ring = {'style': 'level', 'value': 5, 'index': 0, 'count': 101}
        self.assertEqual(lp.compose(frame('idle', mode='VOLUME', crumb='music', ring=ring)).crumb, 'music')
        self.assertEqual(lp.compose(frame('idle', mode='VOLUME', ring=ring)).crumb, '')

if __name__ == '__main__':
    unittest.main()
