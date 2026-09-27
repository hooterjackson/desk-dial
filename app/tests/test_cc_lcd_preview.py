"""lcd_preview: the static knob LCD mirror (PRESENTATION_V5.md section 8, final states).

The mirror must draw the same strings as the firmware renderer (cc_display.cpp). FirmwareParityTests
compare every harness case (cc5_frames.json drawn with the v5 geometry, every frames_v5.json input a
cc5.4 parser accepts, the harness-only v5 states, artwork2 and the offline screen) with the firmware
harness dump (harness/cc54-handoff/render-index.json, read only): strings, baselines, pens,
inks, icons and art decisions. FontMetricsTests check the embedded knob font tables (the tabular
cc_font_48t included) against the firmware font sources. Both skip when the firmware workspace is
not next to the companion.

Regenerate the embedded font tables (after a firmware font change):
    .venv\\Scripts\\python.exe tests\\test_cc_lcd_preview.py --print-font-metrics
"""
import base64
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import struct
import sys
import textwrap
import unittest
from unittest import mock
import zlib

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import lcd_preview as lp
from control_center.presentation import (FOOTER_INK, ICONS, INK, INK_META, INK_SECONDARY, TONE_INK, accent_ink,
                                         mmss, sat_rgb)
import render_previews

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads((ROOT / 'tests' / 'fixtures' / 'cc5_frames.json').read_text(encoding='utf-8'))
V5 = json.loads((ROOT / 'tests' / 'fixtures' / 'frames_v5.json').read_text(encoding='utf-8'))
CASES = {case['id']: case for case in FIXTURES['cases']}
V5_INPUTS = {case['name']: case['input'] for case in V5['cases'] if case['v5']['accept']}
ART = {key: (ROOT / path).read_bytes() for key, path in FIXTURES['artFixtures'].items()}
LIT = 32  # a pixel counts as lit when a channel reaches this level

WORK = ROOT.parent / 'tools'
FIRMWARE_INDEX = WORK.parent / 'harness' / 'cc54-handoff' / 'render-index.json'
FIRMWARE_FONTS = WORK.parent / 'firmware' / 'src' / 'fonts'
LVGL_FONTS = WORK.parent / 'firmware' / '.pio' / 'libdeps' / 'nanofoc_d' / 'lvgl' / 'src' / 'font'


def rgb(value):
    return (value >> 16) & 255, (value >> 8) & 255, value & 255


def frame(case_id, **changes):
    result = deepcopy(CASES[case_id]['frame'])
    result.update(changes)
    return result


def v5(name, **changes):
    result = deepcopy(V5_INPUTS[name])
    result.update(changes)
    return result


def pixels(image):
    data = image.load()
    for y in range(image.height):
        for x in range(image.width):
            yield x, y, data[x, y]


def lit_bbox(image, box):
    """Bounding box (x0, y0, x1, y1 exclusive) of lit pixels inside box."""
    crop = image.crop(box).convert('RGB').point(lambda v: 255 if v >= LIT else 0).convert('L')
    found = crop.getbbox()
    return None if found is None else (found[0] + box[0], found[1] + box[1], found[2] + box[0], found[3] + box[1])


def radius(x, y):
    return math.hypot(x + .5 - lp.CENTRE, y + .5 - lp.CENTRE)


def rgb_pixels(image):
    data = image.convert('RGB').tobytes()
    return [tuple(data[i:i + 3]) for i in range(0, len(data), 3)]


def has_colour(image, colour, box=(0, 0, 240, 240), tolerance=2):
    return any(all(abs(a - b) <= tolerance for a, b in zip(p, colour)) for p in rgb_pixels(image.crop(box)))


HEADING_ROWS = range(lp.HEADING.baseline - lp.CAP_HEIGHT[12] - 2, lp.HEADING.baseline + 5)


def outside_safe_circle(image):
    """Lit pixels past r104 (past r112 on the heading row: section 8.3)."""
    found = []
    for x, y, p in pixels(image):
        if p[3] and max(p[:3]) >= LIT:
            limit = lp.HEADING_RADIUS if y in HEADING_ROWS else lp.SAFE_RADIUS
            if radius(x, y) > limit:
                found.append((x, y, p))
    return found


def wire_strings(f):
    """Every string a renderer may draw for a frame (verbatim wire text, the firmware heading chain,
    the Seek time it formats and the tile initial)."""
    strings = [f.get(key, '') for key in ('heading', 'title', 'subtitle', 'meta', 'status', 'volumeCaption')]
    strings += [b.get('label', '') for b in f.get('buttons', [])]
    strings += [f.get('value', ''), '%', f.get('subtitle', '')[:1].upper(), f.get('subtitle', '')[:1]]
    ring = f.get('ring') or {}
    if ring.get('style') == 'lap':
        strings.append(mmss(ring.get('index', 0)))
    heading = f.get('heading', '')
    if heading.startswith(lp.RECENT_LONG):   # "RECENTLY ADDED · P{n}" -> "RECENT · P{n}"
        strings.append(lp.RECENT_SHORT + heading[len(lp.RECENT_LONG):])
    return [s for s in strings if s]


def ink(text, size=22):
    return lp.ink_rows(text, size)


# --------------------------------------------------------------------------
# Firmware harness dump (cc_display.cpp through LVGL 9.0, harness/main.cpp)
# --------------------------------------------------------------------------
FIRMWARE_ROLES = {
    'heading': 'heading', 'home.title': 'title', 'list.title': 'title', 'tracks.title': 'title',
    'windows.title': 'title', 'offline.title': 'title', 'home.artist': 'subtitle', 'list.subtitle': 'subtitle',
    'tracks.subtitle': 'subtitle', 'windows.app': 'subtitle', 'offline.subtitle': 'subtitle',
    'status': 'status', 'volume.caption': 'caption', 'volume.digits': 'digits', 'volume.percent': 'percent',
    'idle.word': 'idle-word', 'list.meta': 'meta', 'tracks.meta': 'meta', 'windows.meta': 'meta',
    'windows.letter': 'tile-initial', 'seek.caption': 'caption', 'seek.time': 'seek-time', 'seek.line': 'line',
}
ICON_ROLES = {'footer.icon': 'footer', 'idle.icon': 'idle-icon', 'tracks.position': 'track-position'}


def drawn(obj):
    return not obj['hidden'] and obj['opa_eff'] > 0


def firmware_lines(render):
    """{mirror role: [(text, baseline, x, ink)]} of every label line the knob shows (twins excluded)."""
    lines = {}
    for obj in render['layout']:
        if obj.get('type') != 'label' or not drawn(obj) or obj['role'].endswith('.twin'):
            continue
        for line in obj['lines']:
            if line['text']:
                lines.setdefault(FIRMWARE_ROLES[obj['role']], []).append(
                    (line['text'], line['baseline'] - obj['ty'], line['x1'], obj['color']))
    return lines


def firmware_icons(render):
    return sorted((ICON_ROLES[o['role']], o['icon'], o['recolor']) for o in render['layout']
                  if o.get('type') == 'image' and drawn(o) and o['opa_eff'] == 255 and '@' in o.get('icon', ''))


def mirror_lines(scene):
    lines = {}
    for run in scene.texts():
        lines.setdefault(run.role, []).append((run.text, run.baseline, run.x, '#%02X%02X%02X' % run.ink))
    return lines


def mirror_icons(scene):
    return sorted((i.role, f'{i.name}@{i.size}', '#%02X%02X%02X' % i.ink) for i in scene.icons())


# --------------------------------------------------------------------------
# Knob font tables from the firmware sources (the embedded _KNOB_FONT_METRICS)
# --------------------------------------------------------------------------
GLYPH_DSC = re.compile(r'\{\.bitmap_index = \d+, \.adv_w = (\d+), \.box_w = (\d+), \.box_h = (\d+), '
                       r'\.ofs_x = -?\d+, \.ofs_y = (-?\d+)\}(?:,?\s*/\* id = \d+ U\+([0-9A-F]+) \*/)?')
FONT_SIZES = (12, 14, 16, 22, 48, '48t')


def _c_array(text, name):
    body = re.search(r'\b' + name + r'\[\]\s*=\s*\{(.*?)\};', text, re.S).group(1)
    body = re.sub(r'/\*.*?\*/', '', body, flags=re.S)
    return [int(v, 0) for v in re.findall(r'-?(?:0x[0-9a-fA-F]+|\d+)', body)]


def _c_field(text, name):
    return int(re.search(r'\.' + name + r'\s*=\s*(-?\d+)', text).group(1))


def extract_font_metrics(fonts_dir=FIRMWARE_FONTS, lvgl_font_dir=LVGL_FONTS):
    """cc_font_<N>.c glyph boxes plus lv_font_montserrat_<N>.c ASCII glyphs and class kerning; cc_font_48
    and the tabular cc_font_48t have no fallback."""
    data = {'fonts': {}}
    for size in FONT_SIZES:
        cc = (Path(fonts_dir) / f'cc_font_{size}.c').read_text(encoding='utf-8')
        entry = {'line_height': _c_field(cc, 'line_height'), 'base_line': _c_field(cc, 'base_line'),
                 'cc': {str(int(cp, 16)): [int(a), int(w), int(h), int(y)]
                        for a, w, h, y, cp in GLYPH_DSC.findall(cc) if cp}}
        if size not in (48, '48t'):
            builtin = (Path(lvgl_font_dir) / f'lv_font_montserrat_{size}.c').read_text(encoding='utf-8')
            # ASCII is glyph ids 1..95; U+00B0 and U+2022 are ids 96, 97; the rest are symbols.
            assert re.search(r'\.range_start = 32, \.range_length = 95, \.glyph_id_start = 1', builtin)
            assert _c_array(builtin, 'unicode_list_1')[:2] == [0, 0x2022 - 0xB0]
            glyphs = [[int(a), int(w), int(h), int(y)] for a, w, h, y, _ in GLYPH_DSC.findall(builtin)]
            left = _c_array(builtin, 'kern_left_class_mapping')
            right = _c_array(builtin, 'kern_right_class_mapping')
            assert not any(right[98:]), 'a symbol glyph has a right kerning class'
            data['left'], data['right'] = left[1:96], right[1:98]
            data['columns'] = _c_field(builtin, 'right_class_cnt')
            entry.update(ascii=glyphs[1:96], kern=_c_array(builtin, 'kern_class_values'),
                         kern_scale=_c_field(builtin, 'kern_scale'))
            assert len(entry['kern']) == _c_field(builtin, 'left_class_cnt') * data['columns']
            assert (_c_field(builtin, 'line_height'), _c_field(builtin, 'base_line')) == \
                (entry['line_height'], entry['base_line'])
        data['fonts'][str(size)] = entry
    return data


def encode_font_metrics(data):
    raw = json.dumps(data, separators=(',', ':'), sort_keys=True).encode()
    return '\n'.join(textwrap.wrap(base64.b64encode(zlib.compress(raw, 9)).decode(), 100))


class FixtureRenderTests(unittest.TestCase):
    def test_every_fixture_renders_with_and_without_art(self):
        for case in FIXTURES['cases']:
            with self.subTest(case=case['id']):
                for artwork in (None, ART.get(case.get('art'))):
                    image = lp.render_lcd(case['frame'], artwork)
                    self.assertEqual((image.mode, image.size), ('RGBA', (240, 240)))
                    self.assertEqual(image.getpixel((0, 0))[3], 0)       # outside the round glass
                    self.assertEqual(image.getpixel((120, 120))[3], 255)

    def test_every_v5_input_renders(self):
        for name, f in V5_INPUTS.items():
            with self.subTest(case=name):
                image = lp.render_lcd(f, ART['art-den-120'])
                self.assertEqual(image.size, (240, 240))
                self.assertEqual(outside_safe_circle(lp.render_lcd(f)), [])

    def test_sequence_frames_render(self):
        for sequence in FIXTURES['sequences']:
            for step in sequence['steps']:
                with self.subTest(sequence=sequence['id'], t=step['t']):
                    lp.render_lcd(step['frame'], ART.get(step.get('art')))

    def test_no_lit_pixel_outside_the_safe_circle(self):
        # Art excluded (no artwork). Text and icons stay inside r104; the heading row may reach r112.
        for case in FIXTURES['cases']:
            with self.subTest(case=case['id']):
                self.assertEqual(outside_safe_circle(lp.render_lcd(case['frame'])), [])

    def test_long_and_wide_text_stays_inside_the_safe_circle(self):
        wide = 'WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW ÉÉÉÉÉÉÉÉÉ gggggggg'
        cases = [frame('home', title=wide, subtitle=wide, status=wide),
                 frame('home-turn', volumeCaption=wide, status=wide),
                 frame('ra-item', title=wide, subtitle=wide, meta=wide),
                 frame('tr-neu', title=wide, subtitle=wide, meta=wide),
                 frame('wi-brw', title=wide, subtitle=wide, meta=wide),
                 v5('v5-seek-p5', title=wide, meta=wide),
                 v5('v5-upnext-p5', title=wide, subtitle=wide, meta=wide),
                 frame('home-pidle', buttons=[{'label': 'WWWWWWWWWWWWWWWW', 'enabled': True, 'icon': 'play'}] * 4)]
        for f in cases:
            with self.subTest(layout=f['layout']):
                self.assertEqual(outside_safe_circle(lp.render_lcd(f)), [])
        for heading in ('RECENTLY ADDED', 'FAVOURITES', 'RECENTLY ADDED · P12 · WWWWWWWW', 'WWWWWWWWWWWWWWWWWWWW'):
            self.assertEqual(outside_safe_circle(lp.render_lcd(frame('ra-load', heading=heading))), [])


@unittest.skipUnless(FIRMWARE_INDEX.is_file(), 'firmware harness dump not present')
class FirmwareParityTests(unittest.TestCase):
    """The mirror draws what the knob draws (section 15.3 `mirror_parity`), case by case."""

    @classmethod
    def setUpClass(cls):
        index = json.loads(FIRMWARE_INDEX.read_text(encoding='utf-8'))
        cls.cases = [c for c in index['cases'] if c['kind'] in ('frame', 'offline')]
        cls.renders = {c['id']: c['render'] for c in cls.cases}

    def compose(self, case):
        layout = case['render']['layout']
        app_icon = any(o['role'] == 'windows.icon' and drawn(o) for o in layout)
        if case['kind'] == 'offline':
            return lp.compose(None, native=case.get('native', False))
        wire = CASES[case['id']]['frame'] if case['id'] in CASES else case['wire']
        return lp.compose(wire, window_icon=app_icon, artwork2=True)

    def test_the_harness_covers_every_fixture_and_v5_input(self):
        ids = set(self.renders)
        self.assertTrue({c['id'] for c in FIXTURES['cases']} <= ids)
        self.assertTrue({f'v5.{name}' for name in V5_INPUTS} <= ids)
        self.assertGreater(len(self.cases), 250)

    def test_drawn_strings_baselines_pens_and_inks_match_the_firmware(self):
        for case in self.cases:
            with self.subTest(case=case['id']):
                knob = firmware_lines(case['render'])
                mirror = mirror_lines(self.compose(case))
                self.assertEqual({role: [line[0] for line in lines] for role, lines in mirror.items()},
                                 {role: [line[0] for line in lines] for role, lines in knob.items()})
                for role, lines in knob.items():
                    for (_, knob_baseline, knob_x, knob_ink), (text, baseline, x, ink_) in zip(lines, mirror[role]):
                        self.assertLessEqual(abs(baseline - knob_baseline), 1, (role, text))
                        self.assertLessEqual(abs(x - knob_x), 1, (role, text))
                        if role != 'tile-initial':      # the tile group's opacity dims the initial
                            self.assertEqual(ink_, knob_ink, (role, text))

    def test_icons_and_art_decisions_match_the_firmware(self):
        for case in self.cases:
            with self.subTest(case=case['id']):
                scene = self.compose(case)
                self.assertEqual(mirror_icons(scene), firmware_icons(case['render']))
                if case['kind'] == 'frame':
                    art = next(o for o in case['render']['layout'] if o['role'] == 'art')
                    self.assertEqual(scene.art and bool(case.get('art')), drawn(art))

    def test_the_twelve_twins_are_the_mirrors_shadowed_runs(self):
        for case in self.cases:
            twins = {FIRMWARE_ROLES[o['role'][:-len('.twin')]] for o in case['render']['layout']
                     if o['role'].endswith('.twin') and drawn(o) and o['text']}
            with self.subTest(case=case['id']):
                self.assertEqual({run.role for run in self.compose(case).texts() if run.shadow}, twins)

    def test_strings_the_old_full_box_clamp_truncated(self):
        # Lines the knob shows in full (the chord of each line's own ink rows).
        shown = {'tr-neu': ('title', ['Turn to choose']),
                 'ra-auth': ('title', ['Apple Music', 'sign-in expired']),
                 'ra-empty': ('title', ['Nothing', 'recently added']),
                 'disc': ('title', ['Waiting for PC'])}
        for case_id, (role, lines) in shown.items():
            with self.subTest(case=case_id):
                self.assertEqual([line[0] for line in firmware_lines(self.renders[case_id])[role]], lines)


class FontMetricsTests(unittest.TestCase):
    @unittest.skipUnless(FIRMWARE_FONTS.is_dir() and LVGL_FONTS.is_dir(), 'firmware font sources not present')
    def test_embedded_tables_match_the_firmware_fonts(self):
        self.assertEqual(lp.font_data(), extract_font_metrics())

    def test_line_metrics_match_the_label_constants(self):
        for size, entry in lp.font_data()['fonts'].items():
            size = lp._font_key(size)
            self.assertEqual((entry['line_height'], entry['line_height'] - entry['base_line']),
                             (lp.LINE_HEIGHT[size], lp.ASCENT[size]))

    def test_glyph_sets(self):
        for size in (12, 14, 16, 22):
            self.assertIsNotNone(lp.glyph(ord('A'), size))            # built-in fallback
            self.assertIsNotNone(lp.glyph(0x0151, size))              # Latin Extended-A (cc_font)
            self.assertIsNotNone(lp.glyph(0x2026, size))
            self.assertIsNone(lp.glyph(0x4E2D, size))                 # not in the knob fonts
        self.assertIsNotNone(lp.glyph(ord('7'), 48))
        self.assertIsNone(lp.glyph(ord('A'), 48))                     # cc_font_48 has no fallback
        # cc_font_48t: the tabular digits and ':' only (section 10).
        self.assertEqual({lp.glyph(ord(d), lp.SEEK_FONT)[0] for d in '0123456789'}, {538})   # 33.6 px each
        self.assertIsNotNone(lp.glyph(ord(':'), lp.SEEK_FONT))
        self.assertIsNone(lp.glyph(ord('%'), lp.SEEK_FONT))

    def test_measure_is_the_firmware_width(self):
        # K3 fits its placeholders with lcd_preview.measure (CONTROL_CENTER_V5.md 15.1).
        self.assertEqual(lp.measure('Browse', 12), lp.text_width('Browse', 12))
        self.assertEqual(lp.measure('RECENTLY ADDED', 12, 1), lp.text_width('RECENTLY ADDED', 12, 1))
        self.assertEqual(lp.measure('1:14', '48t', -1), 110)
        self.assertEqual(lp.measure(None, 12), 0)
        for text in ('Play', 'Pause', 'Browse', 'Tracks', 'Win'):   # every v7 Home label <= 46 px (VOC-D08)
            self.assertLessEqual(lp.measure(text, 12), 46, text)
        self.assertGreater(lp.measure('Play/Pause', 12), 46)


class SeekFontBuildTests(unittest.TestCase):
    """The tabular Seek face (cc_font_48t's shapes) is built lazily on the first Seek render, possibly
    on the Tk thread while an overlay takes input: no single C call may hold the GIL for long
    (DESKTOP_STAGE G1-5, 4.7.3). The build used to sum the whole 741 KB font in one struct.unpack and
    one sum (2-3 ms each)."""

    def test_the_checksum_is_chunked_and_exact(self):
        data = bytes(range(256)) * 700 + b'\x01\x02\x03'   # several chunks, not a multiple of 4
        padded = data + b'\0' * (-len(data) % 4)
        self.assertEqual(lp._checksum(data), sum(struct.unpack(f'>{len(padded) // 4}I', padded)) & 0xFFFFFFFF)
        self.assertEqual(lp._checksum(b''), 0)
        self.assertLessEqual(4 * lp._CHECKSUM_CHUNK_WORDS, 16 * 1024)

    def test_the_build_sums_only_small_buffers_and_stays_a_valid_font(self):
        seen, real = [], lp._checksum

        def spy(data):
            seen.append(len(data))
            return real(data)

        lp._tabular_font_bytes.cache_clear()
        lp.tabular_font.cache_clear()
        try:
            with mock.patch.object(lp, '_checksum', spy):
                font = lp._tabular_font_bytes()
        finally:
            lp._tabular_font_bytes.cache_clear()
            lp.tabular_font.cache_clear()
        # Only the rebuilt cmap, the edited head and the table directory are summed.
        self.assertTrue(seen)
        self.assertLess(max(seen), 8 * 1024)
        # The reused source checksums are exact: every directory entry is its table's checksum (head
        # with checkSumAdjustment zeroed) and the whole file sums to 0xB1B0AFBA.
        sums = {}
        tables = lp._sfnt_tables(font, sums)
        self.assertIn('cmap', tables)
        for tag, blob in tables.items():
            if tag == 'head':
                blob = blob[:8] + b'\0\0\0\0' + blob[12:]
            self.assertEqual(sums[tag], real(blob), tag)
        self.assertEqual(real(font), 0xB1B0AFBA)
        face = lp.tabular_font(48)
        self.assertEqual({face.getlength(d) for d in '0123456789'}, {face.getlength('0')})   # tabular digits


class GeometryTests(unittest.TestCase):
    def test_safe_half_is_the_chord_over_the_pixel_rows(self):
        self.assertEqual(lp.safe_half(53, 102), math.isqrt(104 ** 2 - 67 ** 2))       # 79
        self.assertEqual(lp.safe_half(130, 140), math.isqrt(104 ** 2 - 21 ** 2))      # row 140 ends at 141
        self.assertEqual(lp.safe_half(10, 5), lp.CENTRE)                               # no rows
        self.assertEqual(lp.safe_half(10, 16), 0)                                      # d >= 104
        self.assertEqual(lp.safe_half(34, 42, 112), math.isqrt(112 ** 2 - 86 ** 2))   # the heading's r112

    def test_line_width_uses_each_lines_own_ink_rows(self):
        # A single-line title: its cap/ascender rows 58..74, not the 24 px line box.
        self.assertEqual(ink('Turn to choose'), (-17, -1))
        self.assertEqual(lp.TRACKS_TITLE.line_width(ink('Turn to choose')), 166)
        self.assertEqual(lp.text_width('Turn to choose', 22), 166)
        # Two lines: the same ink rows, one pitch lower for line 2 (nearer the centre).
        rows = ink('Apple Music sign-in expired')
        self.assertEqual([lp.LIST_TITLE.line_width(rows, row) for row in (0, 1)], [162, 170])
        self.assertEqual(lp.LIST_TITLE.line_width(None), 170)   # nothing inked: the box width
        # The heading: min(138, the r112 chord of its ink rows) = 138 (section 8.5.2).
        self.assertEqual(lp.HEADING.line_width(ink('RECENTLY ADDED', 12)), 138)
        self.assertEqual((lp.HEADING.x, lp.HEADING.width, lp.HEADING.radius), (51, 138, 112))
        # The Seek time: the 192 px chord of its rows (section 8.5.1) inside the 240 px box.
        self.assertEqual(lp.SEEK_TIME.line_width(ink('999:59', lp.SEEK_FONT)), 192)
        # An off-centre idle column loses twice its offset from the centre.
        self.assertEqual([label.line_width(ink('Browse', 12)) for label in lp.IDLE_WORDS], [60] * 4)
        column = lp.Label(10, 60, 145, 12)                      # centre 40, 80 px off-centre
        self.assertEqual(column.line_width(ink('Browse', 12)), 2 * (100 - 80))

    def test_baselines_match_the_css_line_boxes(self):
        # round(CSS top + (line height - 1.219 em) / 2 + 0.968 em) == LVGL y + ascent (section 8.5.1).
        def css(top, size, lh):
            return round(top + (lh - 1.219 * size) / 2 + 0.968 * size)
        expected = {'HEADING': (32, 14), 'HOME_TITLE': (60, 26), 'HOME_ARTIST': (114, 18), 'STATUS': (134, 14),
                    'VOLUME_CAPTION': (52, 18), 'LIST_TITLE': (52, 26), 'LIST_SUBTITLE': (106, 18),
                    'LIST_META': (127, 14), 'TRACKS_TITLE': (54, 26), 'TRACKS_SUBTITLE': (110, 18),
                    'TRACKS_META': (130, 14), 'SEEK_CAPTION': (52, 18), 'SEEK_LINE': (128, 18),
                    'WINDOWS_APP': (80, 18), 'WINDOWS_TITLE': (98, 20), 'WINDOWS_META': (140, 14),
                    'OFFLINE_TITLE_LABEL': (70, 26), 'OFFLINE_SUB_LABEL': (104, 18)}
        for name, (top, lh) in expected.items():
            label = getattr(lp, name)
            self.assertEqual(label.baseline, css(top, label.size, lh), name)
        self.assertEqual(lp.DIGITS_BASELINE, css(76, 48, 46))
        self.assertEqual(lp.SEEK_TIME.baseline, css(76, 48, 46))
        self.assertEqual(lp.IDLE_WORD_BASELINE, css(134, 12, 14))
        self.assertEqual(lp.TILE_INITIAL_LABEL.baseline, 42 + 7 + lp.ASCENT[16])   # LVGL y 49 in the tile
        self.assertEqual((lp.HOME_TITLE.pitch, lp.WINDOWS_TITLE.pitch, lp.OFFLINE_SUB_LABEL.pitch), (26, 20, 18))

    def test_scene_baselines_per_layout(self):
        def baselines(scene, role):
            return [run.baseline for run in scene.texts(role)]
        home = lp.compose(frame('home-paused', title='Cloudbusting and a long second line here'))
        self.assertEqual(baselines(home, 'title'), [81, 107])
        self.assertEqual((baselines(home, 'subtitle'), baselines(home, 'status')), ([128], [145]))
        volume = lp.compose(frame('home-pend'))
        self.assertEqual((baselines(volume, 'caption'), baselines(volume, 'digits'),
                          baselines(volume, 'percent')), ([66], [116], [116]))
        recent = lp.compose(frame('ra-na'))
        self.assertEqual((baselines(recent, 'heading'), baselines(recent, 'title'),
                          baselines(recent, 'subtitle'), baselines(recent, 'meta')),
                         ([43], [73, 99], [120], [138]))
        tracks = lp.compose(frame('tr-neu'))
        self.assertEqual((baselines(tracks, 'title'), baselines(tracks, 'subtitle'), baselines(tracks, 'meta')),
                         ([75], [124], [141]))
        seek = lp.compose(v5('v5-seek-p5'))
        self.assertEqual((baselines(seek, 'heading'), baselines(seek, 'caption'), baselines(seek, 'seek-time'),
                          baselines(seek, 'line')), ([43], [66], [116], [142]))
        windows = lp.compose(frame('wi-brw', meta='Switching…'))
        self.assertEqual((baselines(windows, 'subtitle'), baselines(windows, 'title'),
                          baselines(windows, 'meta'), baselines(windows, 'tile-initial')),
                         ([94], [114, 134], [151], [64]))
        idle = lp.compose(frame('home-pidle'))
        self.assertEqual(baselines(idle, 'idle-word'), [145] * 4)
        offline = lp.compose(None)
        self.assertEqual((baselines(offline, 'title'), baselines(offline, 'subtitle')), ([91], [118, 136]))

    def test_lines_are_centred_in_the_label_box(self):
        for f in (CASES['ra-auth']['frame'], v5('v5-seek-p5'), None):
            scene = lp.compose(f)
            for run in scene.texts():
                with self.subTest(role=run.role, text=run.text):
                    x, width = run.box
                    self.assertEqual(run.x, x + (width - run.width) // 2)
                    self.assertLessEqual(run.width, run.limit)

    def test_digits_and_percent_share_a_baseline_with_a_2px_gap(self):
        for case_id in ('home-turn', 'stress-0', 'stress-100', 'vol-1-ext', 'home-none-vol'):
            with self.subTest(case=case_id):
                f = CASES[case_id]['frame']
                scene = lp.compose(f)
                digits, percent = scene.texts('digits')[0], scene.texts('percent')[0]
                self.assertEqual(digits.text, f['value'].rstrip('%'))
                self.assertEqual((digits.size, digits.tracking, digits.ink), (48, -1, rgb(INK)))
                self.assertEqual((percent.size, percent.ink), (22, rgb(INK_SECONDARY)))
                self.assertEqual(percent.x - (digits.x + digits.width), lp.DIGIT_GAP)
                left, right = digits.x, percent.x + percent.width
                self.assertLessEqual(abs((240 - right) - left), 1)  # pair centred
                image = lp.render_lcd(f)
                digit_ink = lit_bbox(image, (digits.x, 60, percent.x - 1, 130))
                percent_ink = lit_bbox(image, (percent.x, 60, right + 2, 130))
                self.assertLessEqual(abs(digit_ink[3] - percent_ink[3]), 1)
                self.assertLessEqual(abs(digit_ink[3] - lp.DIGITS_BASELINE), 1)

    def test_volume_number_is_the_firmwares(self):
        self.assertEqual(lp.volume_digits('54%'), '54')
        self.assertEqual(lp.volume_digits('Muted'), '')
        self.assertEqual(lp.volume_digits('5 4 %9'), '54')
        self.assertEqual(lp.volume_digits('-12345678%'), '-123456')
        muted = lp.compose(frame('home-turn', value='Muted'))
        self.assertEqual((muted.texts('digits'), muted.texts('percent')), ([], []))

    def test_footer_icons_sit_on_their_slot_centres(self):
        image = lp.render_lcd(CASES['home']['frame'])
        for slot, button in enumerate(CASES['home']['frame']['buttons']):
            centre = lp.FOOTER_X[slot]
            with Image.open(lp.ICON_DIR / f"{button['icon']}-20.png") as png:
                x0, y0, x1, y1 = png.getchannel('A').point(lambda a: 255 if a >= LIT else 0).getbbox()
            left = centre - 10
            self.assertEqual(lit_bbox(image, (centre - 21, 146, centre + 21, 182)),
                             (left + x0, 154 + y0, left + x1, 154 + y1))

    def test_empty_footer_slot_keeps_the_other_positions(self):
        f = frame('home')
        f['buttons'][1] = {'label': '', 'enabled': False, 'icon': ''}
        scene = lp.compose(f)
        self.assertEqual([(i.name, i.x + 10) for i in scene.icons('footer')],
                         [('pause', 56), ('win', 141), ('tracks', 184)])
        image = lp.render_lcd(f)
        self.assertIsNone(lit_bbox(image, (80, 146, 118, 182)))

    def test_idle_row_centres(self):
        f = CASES['home-pidle']['frame']
        scene, image = lp.compose(f), lp.render_lcd(f)
        icons, words = scene.icons('idle-icon'), scene.texts('idle-word')
        self.assertEqual([(i.x + 13, i.y, i.size) for i in icons], [(x, 100, 26) for x in lp.IDLE_X])
        for icon in icons:
            with Image.open(lp.ICON_DIR / f'{icon.name}-26.png') as png:
                x0, y0, x1, y1 = png.getchannel('A').point(lambda a: 255 if a >= LIT else 0).getbbox()
            self.assertEqual(lit_bbox(image, (icon.x - 4, 96, icon.x + 30, 128)),
                             (icon.x + x0, 100 + y0, icon.x + x1, 100 + y1))
        for word, centre in zip(words, lp.IDLE_X):
            self.assertLessEqual(abs(word.x + word.width / 2 - centre), 1)
            self.assertEqual(word.box, (centre - 30, 60))
        self.assertEqual([w.text for w in words], [b['label'] for b in f['buttons']])

    def test_a_token_without_a_knob_mask_is_hidden(self):
        # Section 9.1: the 26 px set is play/pause/list/win/tracks; cc_icon() returns nullptr otherwise.
        self.assertEqual(lp.firmware_sizes()['play'], frozenset({20, 26}))
        self.assertEqual(lp.firmware_sizes()['heartfill'], frozenset({20}))
        self.assertFalse(lp.knob_has_mask('back', 26))
        f = frame('home-pidle', buttons=[{'label': 'Back', 'enabled': True, 'icon': 'back'},
                                         {'label': 'Browse', 'enabled': True, 'icon': 'list'},
                                         {'label': 'Win', 'enabled': True, 'icon': 'win'},
                                         {'label': 'Tracks', 'enabled': True, 'icon': 'tracks'}])
        scene = lp.compose(f)
        self.assertEqual([i.name for i in scene.icons('idle-icon')], ['list', 'win', 'tracks'])
        self.assertEqual(scene.texts('idle-word')[0].text, 'Back')          # the word stays


class InkTests(unittest.TestCase):
    def test_footer_and_idle_inks_follow_the_v5_tone(self):
        checks = [('home', 'nav', (40, 146, 200, 182)),
                  ('home-none', 'dim', (30, 98, 212, 150)),
                  ('home-none', 'nav', (30, 98, 212, 150)),
                  ('home-paused', 'go', (40, 146, 72, 182)),        # section 5.2 row 9: paused Home Play
                  ('home-pidle', 'go', (30, 98, 80, 150)),
                  ('ra-item', 'go', (170, 146, 200, 182)),
                  ('wi-brw', 'stop', (40, 146, 72, 182)),
                  ('wi-closed', 'dim', (170, 146, 200, 182))]
        for case_id, tone, box in checks:
            with self.subTest(case=case_id, tone=tone):
                self.assertTrue(has_colour(lp.render_lcd(CASES[case_id]['frame']), rgb(FOOTER_INK[tone]), box))
        self.assertEqual(FOOTER_INK['dim'], 0x5A5A5A)

    def test_lit_liked_and_accent_inks(self):
        # Explorer tabs: lit on #FFFFFF, lit off #7A7A7A (rows 6 and 7).
        explorer = lp.compose(v5('v5-explorer-tab0-p5'))
        self.assertEqual([(i.name, i.ink) for i in explorer.icons('footer')][1:3],
                         [('clock', (255, 255, 255)), ('playlists', (0x7A, 0x7A, 0x7A))])
        # [r2.2] A liked row: the filled heart in #A3244A (row 4), never the stroked heart or dim.
        liked = lp.compose(v5('heart-lit-on-no-colour')).icons('footer')[2]
        self.assertEqual((liked.name, liked.ink), ('heartfill', (0xA3, 0x24, 0x4A)))
        plain = lp.compose(v5('v5-upnext-p5')).icons('footer')[2]
        self.assertEqual((plain.name, plain.ink), ('heart', rgb(FOOTER_INK['nav'])))
        # Snap side lit on with an app colour: accent_ink (row 5); navy lifts to #4040FF.
        snap = v5('v5-windows-snap-p5')
        snap['buttons'][1] = {'label': 'Left', 'enabled': True, 'icon': 'snapleft', 'lit': 'on', 'color': 0x000080}
        self.assertEqual(lp.compose(snap).icons('footer')[1].ink, (0x40, 0x40, 0xFF))
        self.assertEqual(accent_ink(0x000080), 0x4040FF)
        snap['buttons'][1]['color'] = 0
        self.assertEqual(lp.compose(snap).icons('footer')[1].ink, (255, 255, 255))   # P5-6: monochrome -> #FFFFFF
        image = lp.render_lcd(v5('heart-lit-on-no-colour'))
        self.assertTrue(has_colour(image, (0xA3, 0x24, 0x4A), (131, 154, 151, 174), tolerance=4))

    def test_line_tones(self):
        checks = [('ra-part', 'meta', 'error'), ('wi-fail', 'meta', 'error'), ('tr-done', 'meta', 'success'),
                  ('ra-pend', 'meta', 'secondary'), ('ra-item', 'meta', 'meta'), ('home-ext', 'status', 'secondary'),
                  ('home-pend', 'status', 'meta')]
        self.assertEqual(TONE_INK['error'], 0xFF8474)
        for case_id, role, tone in checks:
            with self.subTest(case=case_id):
                f = CASES[case_id]['frame']
                run = lp.compose(f).texts(role)[0]
                self.assertEqual(run.ink, rgb(TONE_INK[tone]))
                image = lp.render_lcd(f)
                box = (run.box[0], run.baseline - 12, run.box[0] + run.box[1], run.baseline + 4)
                self.assertTrue(has_colour(image, rgb(TONE_INK[tone]), box, tolerance=24))

    def test_seek_line_ink(self):
        # P5-R2: #A6A6A6 for tone meta, else the tone's ink.
        self.assertEqual(lp.compose(v5('v5-seek-p5')).texts('line')[0].ink, rgb(INK_SECONDARY))
        error = lp.compose(v5('v5-seek-p5', meta='Didn’t jump · try again', metaTone='error'))
        self.assertEqual(error.texts('line')[0].ink, rgb(TONE_INK['error']))

    def test_title_tone_and_fixed_inks(self):
        self.assertEqual(lp.compose(CASES['ra-na']['frame']).texts('title')[0].ink, rgb(INK_META))
        self.assertEqual(lp.compose(CASES['wi-closed']['frame']).texts('title')[0].ink, rgb(INK_META))
        self.assertEqual(lp.compose(CASES['ra-item']['frame']).texts('title')[0].ink, rgb(INK))
        home = lp.compose(frame('home', titleTone='muted'))
        self.assertEqual(home.texts('title')[0].ink, rgb(INK))  # Home title is always ink
        self.assertEqual(lp.compose(CASES['ra-item']['frame']).texts('heading')[0].ink, rgb(INK_SECONDARY))
        self.assertEqual(lp.compose(CASES['home']['frame']).texts('subtitle')[0].ink, rgb(INK_SECONDARY))

    def test_tracks_position_row(self):
        def inks(case_id, **changes):
            scene = lp.compose(frame(case_id, **changes))
            return [(i.name, i.x, i.y, i.ink) for i in scene.icons('track-position')]
        T1, T3, TD = rgb(INK), rgb(INK_META), (0x55, 0x55, 0x55)
        self.assertEqual(inks('tr-neu'), [('prev', 72, 88, T3), ('dotfill', 112, 88, T1), ('next', 152, 88, T3)])
        self.assertEqual([i[3] for i in inks('tr-next')], [T3, T3, T1])
        self.assertEqual([i[3] for i in inks('tr-prev')], [T1, T3, T3])
        self.assertEqual([i[3] for i in inks('tr-noprev')], [TD, T3, T3])
        self.assertEqual([i[3] for i in inks('tr-noprev-next')], [TD, T3, T1])
        self.assertEqual([i[3] for i in inks('tr-neu', ring={'style': 'transport', 'value': 0, 'index': 7,
                                                              'count': 3})], [T3, T1, T3])
        image = lp.render_lcd(CASES['tr-noprev']['frame'])
        self.assertTrue(has_colour(image, TD, (72, 88, 88, 104)))
        self.assertFalse(has_colour(image, T1, (72, 88, 88, 104), tolerance=40))


class ArtTests(unittest.TestCase):
    ART_ROWS = (70, 12, 170, 30)  # above the heading: art only

    def test_art_is_doubled_once_with_nearest_pixels(self):
        f = CASES['home']['frame']
        image = lp.render_lcd(f, ART['art-den-120']).convert('RGB')
        source = Image.frombytes('RGB', (120, 120), ART['art-den-120'], 'raw', 'BGR;16')
        for x in range(40, 80):
            for y in range(6, 15):
                expected = source.getpixel((x, y))
                for dx in (0, 1):
                    for dy in (0, 1):
                        self.assertEqual(image.getpixel((2 * x + dx, 2 * y + dy)), expected)

    def test_art_accepts_wire_bytes_and_images(self):
        f = CASES['home']['frame']
        from_bytes = lp.render_lcd(f, ART['art-den-120'])
        source = Image.frombytes('RGB', (120, 120), ART['art-den-120'], 'raw', 'BGR;16')
        self.assertEqual(lp.render_lcd(f, source).tobytes(), from_bytes.tobytes())
        doubled = source.resize((240, 240), Image.Resampling.NEAREST)
        self.assertEqual(lp.render_lcd(f, doubled).tobytes(), from_bytes.tobytes())
        broken = lp.render_lcd(f, ART['art-den-120'][:-2])  # size mismatch: no art, no error
        self.assertEqual(broken.tobytes(), lp.render_lcd(f).tobytes())

    def test_unavailable_art_is_dimmed_to_0_4375(self):
        dimmed = lp.render_lcd(CASES['ra-na']['frame'], ART['art-bright-120']).convert('RGB')
        full = lp.render_lcd(frame('ra-na', artDim=False), ART['art-bright-120']).convert('RGB')
        total_full = total_dim = 0
        for a, b in zip(rgb_pixels(full.crop(self.ART_ROWS)), rgb_pixels(dimmed.crop(self.ART_ROWS))):
            for v, d in zip(a, b):
                self.assertLessEqual(abs(d - v * lp.ART_DIM), 1)
                total_full, total_dim = total_full + v, total_dim + d
        self.assertGreater(total_full, 0)
        self.assertAlmostEqual(total_dim / total_full, 0.4375, delta=0.01)

    def test_where_art_is_drawn(self):
        # Section 8.4: nowPlaying, volume (not over idle), recent, tracks, seek, explorer, upnext.
        art = ART['art-bright-120']
        shown = [frame('home'), frame('home-turn'), frame('ra-item'), frame('tr-neu'), v5('v5-seek-p5'),
                 v5('v5-explorer-tab1-p5'), v5('v5-upnext-p5')]
        hidden = [frame('home-pidle'), frame('home-none-vol', artKey='k'), frame('home-off', artKey='k'),
                  frame('wi-brw', artKey='k'), frame('home', artKey=''), frame('ra-load')]
        for f in shown:
            with self.subTest(shown=f['layout']):
                self.assertIsNotNone(lit_bbox(lp.render_lcd(f, art), self.ART_ROWS))
        for f in hidden:
            with self.subTest(hidden=f['layout'], key=f.get('artKey')):
                self.assertIsNone(lit_bbox(lp.render_lcd(f, art), self.ART_ROWS))

    def test_art_never_depends_on_activity(self):
        for activity in ('error', 'offline', 'unavailable', 'pending', 'loading'):
            image = lp.render_lcd(frame('home', activity=activity), ART['art-bright-120'])
            self.assertIsNotNone(lit_bbox(image, self.ART_ROWS))


class LayoutTests(unittest.TestCase):
    def test_idle_hides_title_artist_status_and_footer(self):
        scene = lp.compose(frame('home-pidle', status='Paused', statusTone='secondary'))
        self.assertEqual([r.role for r in scene.texts()], ['idle-word'] * 4)
        self.assertEqual(scene.icons('footer'), [])
        self.assertFalse(scene.art)

    def test_volume_over_idle_hides_art_and_footer(self):
        f = frame('home-pidle-vol', artKey='art-bright-120')
        self.assertEqual(f['restLayout'], 'idle')
        scene = lp.compose(f)
        self.assertFalse(scene.art)
        self.assertEqual(scene.icons('footer'), [])
        self.assertEqual({r.role for r in scene.texts()}, {'caption', 'digits', 'percent'})
        image = lp.render_lcd(f, ART['art-bright-120'])
        self.assertIsNone(lit_bbox(image, (30, 146, 210, 182)))
        over_track = lp.compose(frame('home-turn'))
        self.assertTrue(over_track.art)
        self.assertEqual(len(over_track.icons('footer')), 4)
        self.assertEqual(over_track.texts('title'), [])  # the track layer is out

    def test_list_layouts_draw_meta_not_status(self):
        for f in (frame('ra-item', status='Legacy status'), frame('home-off', status='Legacy status'),
                  v5('v5-upnext-p5', status='Legacy status'), v5('v5-explorer-tab0-p5', status='Legacy status')):
            scene = lp.compose(f)
            self.assertEqual(scene.texts('status'), [])
            self.assertTrue(scene.texts('meta'))

    def test_notice_uses_list_geometry_without_art(self):
        scene = lp.compose(frame('home-off', artKey='art-bright-120'))
        self.assertFalse(scene.art)
        self.assertEqual([(r.text, r.baseline) for r in scene.texts('title')], [('Sonos', 73), ('unavailable', 99)])
        self.assertEqual(scene.texts('meta')[0].text, 'Windows still works')
        self.assertEqual(len(scene.icons('footer')), 4)

    def test_tracks_title_is_a_single_line(self):
        long = 'A very long previous track title that cannot fit'
        runs = lp.compose(frame('tr-next', title=long)).texts('title')
        self.assertEqual(len(runs), 1)
        self.assertTrue(runs[0].text.endswith(lp.ELLIPSIS))
        self.assertEqual(runs[0].box, (35, 170))
        self.assertEqual(runs[0].limit, lp.TRACKS_TITLE.line_width(ink(long)))
        self.assertLessEqual(runs[0].width, runs[0].limit)

    def test_seek_draws_caption_tabular_time_and_line(self):
        # Section 8.6.8: title -> 14 px caption, mmss(ring.index) in cc_font_48t, meta -> 14 px line.
        scene = lp.compose(v5('v5-seek-p5'))
        self.assertEqual([(r.role, r.text) for r in scene.texts()],
                         [('heading', 'SEEK'), ('caption', 'Hunter'), ('seek-time', '1:14'), ('line', 'of 3:30')])
        time = scene.texts('seek-time')[0]
        self.assertEqual((time.size, time.tracking, time.ink, time.box), (lp.SEEK_FONT, -1, rgb(INK), (0, 240)))
        self.assertEqual([r.text for r in lp.compose(v5('v5-seek-p5', subtitle='x', status='y', value='9%')).texts()],
                         ['SEEK', 'Hunter', '1:14', 'of 3:30'])      # subtitle, status, value ignored
        no_lap = lp.compose(v5('v5-seek-p5', ring={'style': 'transport', 'value': 0, 'index': 1, 'count': 3}))
        self.assertEqual(no_lap.texts('seek-time'), [])
        self.assertEqual(lp.compose(v5('v5-seek-p5')).icons('track-position'), [])

    def test_seek_time_has_no_jitter(self):
        # 0 px jitter: every m:ss of the same length has the same pens (sections 8.6.8, 10).
        for texts in (('0:00', '1:14', '5:55', '9:59'), ('10:00', '47:11', '59:59'), ('100:00', '999:59')):
            runs = [lp.compose(v5('v5-seek-p5', ring={'style': 'lap', 'value': 0, 'index': s, 'count': 59999}))
                    .texts('seek-time')[0] for s in [int(t.split(':')[0]) * 60 + int(t.split(':')[1]) for t in texts]]
            self.assertEqual([r.text for r in runs], list(texts))
            self.assertEqual({(r.x, r.width) for r in runs}, {(runs[0].x, runs[0].width)})
        self.assertEqual([lp.measure(t, lp.SEEK_FONT, -1) for t in ('0:00', '10:00', '999:59')], [110, 143, 176])

    def test_windows_tile_initial_accent_and_closed_opacity(self):
        # Section 5.3: sat() of the selected entry's accent with a #FFFFFF initial.
        scene = lp.compose(CASES['wi-brw']['frame'])
        tile, initial = [i for i in scene.items if isinstance(i, lp.BoxRun)][0], scene.texts('tile-initial')[0]
        accent = lp.normalize(CASES['wi-brw']['frame'])['ring']['colors'][1]
        self.assertEqual((tile.x, tile.y, tile.size, tile.opacity, tile.fill), (104, 42, 32, 1.0, rgb(sat_rgb(accent))))
        self.assertEqual((initial.text, initial.size, initial.baseline, initial.ink), ('C', 16, 64, (255, 255, 255)))
        self.assertLessEqual(abs(initial.x + initial.width / 2 - 120), 1)
        image = lp.render_lcd(CASES['wi-brw']['frame'])
        self.assertEqual(image.getpixel((106, 44))[:3], rgb(sat_rgb(accent)))
        # No accent (entry 0 of the fixture's colours is 0): V4's #444 tile with a #F2F2F2 initial.
        plain = lp.compose(CASES['pend-wi-codex']['frame'])
        self.assertEqual(([i.fill for i in plain.items if isinstance(i, lp.BoxRun)], plain.texts('tile-initial')[0].ink),
                         ([(0x44, 0x44, 0x44)], rgb(INK)))
        closed = lp.render_lcd(CASES['wi-closed']['frame'])
        fill = [i.fill for i in lp.compose(CASES['wi-closed']['frame']).items if isinstance(i, lp.BoxRun)][0]
        self.assertEqual(closed.getpixel((106, 44))[:3], tuple(round(c * 0.35) for c in fill))
        self.assertTrue(lp.selected_closed(lp.normalize(CASES['wi-closed-claude']['frame'])))
        self.assertFalse(lp.selected_closed(lp.normalize(CASES['wi-n45-i30-closed']['frame'])))
        bare = lp.compose(frame('wi-brw', subtitle=''))
        self.assertEqual(([i for i in bare.items if isinstance(i, lp.BoxRun)], bare.texts('tile-initial')), ([], []))

    def test_windows_icon_replaces_the_tile(self):
        icon = Image.new('RGBA', (16, 16), (255, 0, 0, 255))
        image = lp.render_lcd(CASES['wi-brw']['frame'], window_icon=icon)
        self.assertEqual(image.getpixel((110, 50))[:3], (255, 0, 0))
        closed = lp.render_lcd(CASES['wi-closed']['frame'], window_icon=icon)
        self.assertEqual(closed.getpixel((110, 50))[:3], (89, 0, 0))
        self.assertEqual(lp.compose(CASES['wi-brw']['frame'], window_icon=True).texts('tile-initial'), [])

    def test_heading_row_is_drawn_on_every_layout(self):
        # cc_display draws frame.heading on every layout; the host sends none on Windows.
        self.assertEqual(lp.compose(CASES['wi-brw']['frame']).texts('heading'), [])
        self.assertEqual([r.text for r in lp.compose(frame('wi-brw', heading='WINDOWS')).texts('heading')],
                         ['WINDOWS'])
        for name, heading in (('v5-explorer-tab0-p5', 'RECENT'), ('v5-explorer-tab1-p5', 'FAVOURITES'),
                              ('v5-upnext-p5', 'UP NEXT'), ('v5-seek-p5', 'SEEK'), ('v5-tracks-p5', 'TRACKS')):
            self.assertEqual([(r.text, r.tracking) for r in lp.compose(v5(name)).texts('heading')], [(heading, 1)])

    def test_offline_screen(self):
        # Section 8.10: no heading, footer or art; the sub-line in two balanced lines at 0 tracking;
        # after native input "Knob controls still work" on ONE line. It is 171 px with the knob font
        # against the 170 px line, so K1's erratum of lead ruling R-c (8.10, P5-14) draws it at -1 px
        # tracking (148 px) with the approved words, as cc_display.cpp showOfflineSub does.
        self.assertEqual(lp.measure('Knob controls still work', 14), 171)
        self.assertEqual(lp.measure('Knob controls still work', 14, -1), 148)
        scene = lp.compose(None)
        self.assertEqual([(r.role, r.text, r.tracking) for r in scene.texts()],
                         [('title', 'Waiting for PC', 0), ('subtitle', 'Open Desk\u00a0Dial', 0),
                          ('subtitle', 'on your PC', 0)])
        # Desk Dial (VOC-R32, K1 16.8 E-r): a no-break space holds the name together, as the firmware's
        # OFFLINE_SUB; fit_two_lines breaks only at ASCII spaces, so the name is never split.
        self.assertEqual(lp.OFFLINE['subtitle'], 'Open Desk\u00a0Dial on your PC')
        self.assertEqual((lp.measure('Open Desk\u00a0Dial', 14), lp.measure('on your PC', 14)), (114, 80))
        self.assertEqual(lp.fit_two_lines(lp.OFFLINE['subtitle'], 170, 170, 14), ['Open Desk\u00a0Dial', 'on your PC'])
        self.assertEqual(lp.fit_two_lines('Open Desk Dial on your PC', 170, 170, 14), ['Open Desk', 'Dial on your PC'],
                         'with a plain space the balanced split would part the name')
        self.assertEqual((scene.icons(), scene.art), ([], False))
        native = lp.compose(None, native=True)
        self.assertEqual([(r.text, r.tracking) for r in native.texts('subtitle')],
                         [('Knob controls still work', -1)])
        self.assertEqual([(r.role, r.text, r.tracking) for r in native.texts('title')],
                         [('title', 'Waiting for PC', 0)])
        self.assertFalse(any(r.text.endswith(lp.ELLIPSIS) for r in native.texts()))
        image = lp.render_lcd(None)
        self.assertIsNone(lit_bbox(image, (40, 146, 200, 182)))      # no footer
        self.assertIsNotNone(lit_bbox(lp.render_lcd(None, native=True), (35, 104, 205, 140)))

    def test_text_shadow_twins(self):
        # Section 8.5.3: the twelve labels with a twin; none on meta, status, the Seek line, idle words,
        # Windows or the offline screen.
        roles = {run.role for f in (frame('home'), frame('home-turn'), frame('ra-item'), frame('tr-neu'),
                                    v5('v5-seek-p5')) for run in lp.compose(f).texts() if run.shadow}
        self.assertEqual(roles, {'heading', 'title', 'subtitle', 'caption', 'digits', 'percent', 'seek-time'})
        unshadowed = [run.role for f in (frame('wi-brw', meta='x'), frame('home-pidle'), None, frame('ra-item'),
                                         frame('home', status='Paused'), v5('v5-seek-p5'))
                      for run in lp.compose(f).texts() if not run.shadow]
        self.assertEqual(set(unshadowed), {'tile-initial', 'subtitle', 'title', 'meta', 'idle-word', 'status', 'line'})
        # The shadow is black at 80 % one pixel below the glyphs: over a light cover the baseline row
        # (under the last ink row of every capital) goes dark, and nothing darkens without a twin.
        grey = Image.new('RGB', (240, 240), (200, 200, 200))
        for f, role, shadowed in ((frame('home', artKey='k'), 'title', True), (frame('ra-item', artKey='k'), 'meta', False)):
            with self.subTest(role=role):
                image = lp.render_lcd(f, grey).convert('RGB')
                run = lp.compose(f).texts(role)[0]
                row = [image.getpixel((x, run.baseline)) for x in range(run.x, run.x + run.width)]
                self.assertEqual(any(max(p) < 120 for p in row), shadowed)
                self.assertEqual(min(min(p) for p in row) >= 60, not shadowed)

    def test_overlay_draws_the_safe_circle_guide(self):
        plain = lp.render_lcd(CASES['home']['frame'])
        guided = lp.render_lcd(CASES['home']['frame'], overlay=True)
        self.assertNotEqual(plain.tobytes(), guided.tobytes())
        self.assertTrue(has_colour(guided, (53, 208, 192), (16, 110, 24, 130), tolerance=4))
        self.assertTrue(has_colour(guided, (53, 208, 192), (54, 146, 58, 182), tolerance=4))


class CopyTests(unittest.TestCase):
    def test_no_invented_copy_in_any_fixture(self):
        frames = [(case['id'], case['frame']) for case in FIXTURES['cases'] if case['frame'] is not None]
        frames += [(name, f) for name, f in V5_INPUTS.items()]
        for case_id, f in frames:
            allowed = wire_strings(f)
            for run in lp.compose(f).texts():
                text = run.text[:-1] if run.text.endswith(lp.ELLIPSIS) else run.text
                with self.subTest(case=case_id, role=run.role, text=run.text):
                    self.assertTrue(any(text in s for s in allowed))

    def test_heading_is_verbatim_or_the_firmware_chain(self):
        self.assertEqual([(r.text, r.tracking) for r in lp.compose(CASES['ra-item']['frame']).texts('heading')],
                         [('RECENTLY ADDED', 1)])
        self.assertEqual(lp.compose(CASES['tr-neu']['frame']).texts('heading')[0].text, 'TRACKS')
        self.assertEqual(lp.compose(frame('ra-item', heading='Recent · P2')).texts('heading')[0].text,
                         'Recent · P2')
        # Legacy page headings: "RECENTLY ADDED · P{n}" -> "RECENT · P{n}" (tracking kept when it fits);
        # longer: tracking dropped, then an ellipsis at min(138, the r112 chord).
        self.assertEqual(lp.fit_heading('RECENTLY ADDED · P2')[:2], ('RECENT · P2', 1))
        text, tracking, width = lp.fit_heading('RECENTLY ADDED · P12 · WWWWWWWW')
        self.assertEqual((text[:len('RECENT · P12')], text[-1], tracking), ('RECENT · P12', lp.ELLIPSIS, 0))
        self.assertLessEqual(lp.text_width(text, 12, 0), width)
        slim = frame('ra-item')
        del slim['heading']
        self.assertEqual(lp.compose(slim).texts('heading'), [])

    def test_tracks_text_is_verbatim(self):
        scene = lp.compose(frame('tr-neu', subtitle='Cloudbusting', title='', meta=''))
        self.assertEqual([r.text for r in scene.texts('subtitle')], ['Cloudbusting'])  # no "Now: "
        self.assertEqual(scene.texts('title'), [])   # no ring-index title
        self.assertEqual(scene.texts('meta'), [])    # no default meta
        self.assertEqual(lp.compose(CASES['tr-noprev']['frame']).texts('title')[0].text, 'Previous track')

    def test_no_default_meta_or_initial_and_the_firmware_caption_fallback(self):
        slim = frame('ra-item')
        del slim['meta']
        self.assertEqual(lp.compose(slim).texts('meta'), [])
        self.assertEqual(lp.compose(frame('wi-brw', subtitle='')).texts('tile-initial'), [])
        self.assertEqual([r.text for r in lp.compose(frame('home-turn', volumeCaption='')).texts('caption')],
                         ['Cloudbusting'])
        self.assertEqual(lp.compose(frame('home-turn', volumeCaption='', title='')).texts('caption'), [])

    def test_r22_copy_fits_whole(self):
        # [r2.2] approved strings (section 8.6.11) are drawn whole in their elements.
        for text, f, role in (('Speaker group changed', frame('home', status='Speaker group changed'), 'status'),
                              ('Couldn’t open on screen', frame('ra-item', meta='Couldn’t open on screen'), 'meta'),
                              ('Unfavourite in Music app', v5('v5-upnext-p5', meta='Unfavourite in Music app'), 'meta'),
                              ('Finding songs…', frame('ra-item', meta='Finding songs…'), 'meta')):
            with self.subTest(text=text):
                self.assertEqual([r.text for r in lp.compose(f).texts(role)], [text])


class FrameInputTests(unittest.TestCase):
    def test_slimmed_and_legacy_frames_render(self):
        legacy = {'id': 1, 'mode': 'VOLUME', 'target': 'Den', 'value': '54%', 'detail': '', 'status': '',
                  'title': 'Cloudbusting', 'subtitle': 'Kate Bush',
                  'buttons': [{'label': 'Pause', 'enabled': True}, {'label': 'Browse', 'enabled': True},
                              {'label': 'Win', 'enabled': True}, {'label': 'Tracks', 'enabled': True}],
                  'ring': {'style': 'level', 'value': 54, 'index': 0, 'count': 101}}
        scene = lp.compose(legacy)
        self.assertEqual(scene.layout, 'nowPlaying')
        self.assertEqual([i.name for i in scene.icons('footer')], ['pause', 'list', 'win', 'tracks'])
        lp.render_lcd(legacy)
        self.assertEqual(lp.compose(dict(legacy, mode='RECENTLY ADDED')).layout, 'recent')
        minimal = {'id': 2, 'mode': 'X', 'target': '', 'value': '', 'detail': '', 'status': ''}
        lp.render_lcd(minimal)
        self.assertEqual(lp.compose(minimal).layout, 'nowPlaying')

    def test_empty_and_unknown_icons_are_skipped(self):
        f = frame('home')
        f['buttons'] = [{'label': '', 'enabled': True, 'icon': ''},
                        {'label': 'X', 'enabled': True, 'icon': 'bogus'},
                        {'label': 'Win', 'enabled': True, 'icon': 'win'},
                        {'label': '', 'enabled': False, 'icon': ''}]
        self.assertEqual([i.name for i in lp.compose(f).icons()], ['win'])
        lp.render_lcd(f)
        lp.render_lcd(dict(f, layout='idle'))
        self.assertIsNone(lp.icon_mask('', 20))
        self.assertIsNone(lp.icon_mask('missing', 20))

    def test_unhashable_or_non_string_icons_do_not_crash(self):
        f = frame('home')
        f['buttons'] = [{'label': 'Pause', 'enabled': True, 'icon': ['pause'], 'lit': ['on'], 'color': 'red'},
                        {'label': 'Browse', 'enabled': True, 'icon': {'name': 'list'}, 'lit': 5},
                        {'label': 'Win', 'enabled': True, 'icon': None, 'color': -1},
                        {'label': 'Tracks', 'enabled': True, 'icon': 5}]
        self.assertEqual([b['icon'] for b in lp.normalize(f)['buttons']], [''] * 4)
        self.assertEqual([(b['lit'], b['color']) for b in lp.normalize(f)['buttons']], [(None, 0)] * 4)
        self.assertEqual(lp.compose(f).icons(), [])
        lp.render_lcd(f)
        lp.render_lcd(dict(f, layout='idle'))
        lp.normalize(dict(f, layout=['volume'], restLayout={}, titleTone=[], metaTone={}, ring={'style': []}))

    def test_text_is_cut_at_the_wire_capacity(self):
        title = 'é' * 60
        self.assertEqual(lp.normalize(frame('ra-item', title=title))['title'], 'é' * 48)
        label = lp.normalize(frame('home', buttons=[{'label': 'x' * 20, 'enabled': True, 'icon': 'play'}]))
        self.assertEqual(label['buttons'][0]['label'], 'x' * 16)

    def test_absent_first_with_a_nonzero_derived_window_ignores_the_mask_and_colours(self):
        f = frame('wi-n45-i30-closed')
        f['ring'] = {'style': 'selection', 'value': 0, 'index': 30, 'count': 45, 'unavailable': 1 << 9,
                     'colors': [0xFF0000] * 20}
        self.assertFalse(lp.selected_closed(lp.normalize(f)))
        self.assertEqual(lp.normalize(f)['ring']['colors'], [])
        f['ring']['first'] = 21
        self.assertTrue(lp.selected_closed(lp.normalize(f)))
        self.assertEqual(len(lp.normalize(f)['ring']['colors']), 20)

    def test_upnext_strips_the_unavailable_mask(self):
        # Section 4.4 (P5-R24): no Up next row reads as unavailable.
        self.assertEqual(lp.normalize(v5('unavailable-upnext-stripped'))['ring']['unavailable'], 0)


class TextTests(unittest.TestCase):
    def test_text_width_uses_kerned_whole_pixel_advances_and_trims_the_last_spacing(self):
        self.assertEqual(lp.text_width('', 12, 1), 0)
        for char in 'AW%5':
            self.assertIsInstance(lp.advance(char, 22), int)
        self.assertLess(lp.advance('T', 22, 'o'), lp.advance('T', 22))
        self.assertEqual(lp.text_width('To', 22), lp.advance('T', 22, 'o') + lp.advance('o', 22))
        self.assertEqual(lp.text_width('AB', 12, 1), lp.advance('A', 12, 'B') + lp.advance('B', 12) + 1)
        self.assertEqual(lp.advance('T', 22, 'ő'), lp.advance('T', 22))

    def test_soft_hyphen_has_no_advance_and_draws_nothing(self):
        for size in (12, 14, 16, 22):
            self.assertEqual(lp.advance('\xad', size), 0)
            self.assertIsNone(lp.ink_rows('\xad', size))
        self.assertEqual(lp.text_width('A\xad', 12, 1), lp.text_width('A', 12, 1))
        self.assertEqual(lp.text_width('Cloud\xadbusting', 22),
                         lp.text_width('Cloud', 22) + lp.text_width('busting', 22))
        with_shy = lp.render_lcd(frame('ra-item', title='Night\xad'))
        without = lp.render_lcd(frame('ra-item', title='Night'))
        self.assertEqual(with_shy.tobytes(), without.tobytes())
        self.assertEqual([r.text for r in lp.compose(frame('ra-item', title='Cloud\xadbusting')).texts('title')],
                         ['Cloud\xadbusting'])
        alone = lp.render_lcd(frame('ra-item', title='\xad', subtitle='', meta='', heading=''))
        self.assertIsNone(lit_bbox(alone, (20, 50, 220, 146)))

    def test_unknown_glyphs_are_lvgl_placeholders(self):
        self.assertEqual(lp.advance('中', 22), lp.LINE_HEIGHT[22] // 2 + 2)
        self.assertEqual(lp.advance('​', 22), 0)              # a marker: no width
        scene = lp.Scene('recent')
        lp._label(scene, 'title', lp.LIST_TITLE, '中', lp.INK_RGB)
        image = Image.new('RGB', (240, 240))
        lp._paint_text(ImageDraw.Draw(image), scene.texts()[0])
        self.assertEqual(lit_bbox(image, (0, 0, 240, 240)), (113, 53, 127, 77))  # a 14 x 24 frame

    def test_pre_wire_text_gets_the_hosts_glyph_fold(self):
        f = frame('wi-brw', title='中文 🎵 Ω notes — “draft”', subtitle='Écrit')
        runs = lp.compose(f).texts()
        self.assertEqual([r.text for r in runs if r.role == 'title'], ['?? ? ? notes', '— “draft”'])
        self.assertEqual([r.text for r in runs if r.role == 'subtitle'], ['Écrit'])
        wire = lp.compose(frame('wi-brw', title='?? ? ? notes — “draft”', subtitle='Écrit')).texts()
        self.assertEqual([(r.text, r.x, r.baseline) for r in runs], [(r.text, r.x, r.baseline) for r in wire])

    def test_fit_line(self):
        self.assertEqual(lp.fit_line('Kate Bush', 170, 14), 'Kate Bush')
        clipped = lp.fit_line('Caetano Veloso, Gilberto Gil, Os Mutantes & Gal Costa', 166, 14)
        self.assertEqual(clipped, 'Caetano Veloso, Gilbe…')
        self.assertLessEqual(lp.text_width(clipped, 14), 166)
        self.assertEqual(lp.fit_line('ab  cd', 1, 14), lp.ELLIPSIS)
        self.assertEqual(lp.fit_line('Kate Bush', 170, 14, force=True), 'Kate Bush…')

    def test_fit_two_lines(self):
        self.assertEqual(lp.fit_two_lines('Short', 162, 170, 22), ['Short'])
        self.assertEqual(lp.fit_two_lines('Apple Music sign-in expired', 162, 170, 22),
                         ['Apple Music', 'sign-in expired'])
        width = lp.text_width('aa aa', 22)
        self.assertEqual(lp.fit_two_lines('aa aa aa', width, width, 22), ['aa aa', 'aa'])
        self.assertEqual(lp.fit_two_lines('Tropicália ou Panis et Circencis', 162, 170, 22),
                         ['Tropicália ou', 'Panis et…'])
        self.assertEqual(lp.last_line('Panis et Circencis', 170, 22), 'Panis et…')
        self.assertEqual(lp.last_line('Panis et', 170, 22), 'Panis et')
        width = lp.text_width('Panis et' + lp.ELLIPSIS, 22)
        self.assertEqual(lp.last_line('Panis et Circencis', width - 1, 22), 'Panis…')
        self.assertEqual(lp.fit_two_lines('CLAUDE_CODE_HANDOFF.md', 170, 170, 16), ['CLAUDE_CODE_', 'HANDOFF.md'])
        self.assertEqual(lp.fit_two_lines('cc5-stage6-lcd-preview-handoff', 170, 170, 16),
                         ['cc5-stage6-lcd-', 'preview-handoff'])
        lines = lp.fit_two_lines('Pneumonoultramicroscopic', 162, 170, 22)
        self.assertEqual(''.join(lines), 'Pneumonoultramicroscopic')
        self.assertTrue(all(lp.text_width(line, 22) <= width for line, width in zip(lines, (162, 170))))
        for text in ('Supercalifragilisticexpialidocious', 'Supercalifragilisticexpialidocious and more'):
            lines = lp.fit_two_lines(text, 162, 170, 22)
            self.assertEqual((len(lines), lines[1][-1]), (2, lp.ELLIPSIS))
            self.assertTrue(all(lp.text_width(line, 22) <= width for line, width in zip(lines, (162, 170))))


class Artwork2MirrorTests(unittest.TestCase):
    """ARTWORK2.md section 7 as the mirror draws it (only with artwork2 negotiated)."""
    ART_ROWS = (70, 12, 170, 30)  # above the heading: art only

    @classmethod
    def setUpClass(cls):
        from control_center.artwork import prepare_artwork2
        source = ROOT / 'design-reference' / 'design_handoff_nano_d_artwork_color' / 'assets' / 'covers'
        cls.cover = prepare_artwork2((source / 'night-drive-chromatics-album-.jpg').read_bytes())

    def expected_cover(self):
        """Pillow decode, RGB565 with rounding, decoded back: what the knob's panel shows."""
        from io import BytesIO
        with Image.open(BytesIO(self.cover.jpeg)) as decoded:
            data = decoded.convert('RGB').tobytes()
        packed = b''.join((((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5
                           | ((b * 31 + 127) // 255)).to_bytes(2, 'little')
                          for r, g, b in zip(data[0::3], data[1::3], data[2::3]))
        return Image.frombytes('RGB', (240, 240), packed, 'raw', 'BGR;16')

    def home(self, **changes):
        return frame('home', **{'artKey': self.cover.jpeg_key, **changes})

    def test_the_cover_is_the_decoded_jpeg_at_240_without_upscale(self):
        image = lp.render_lcd(self.home(), self.cover.jpeg, artwork2=True).convert('RGB')
        expected = self.expected_cover()
        self.assertEqual(image.crop(self.ART_ROWS).tobytes(), expected.crop(self.ART_ROWS).tobytes())
        region = image.crop((60, 12, 180, 30)).tobytes()
        pairs = [(region[i:i + 3], region[i + 3:i + 6]) for i in range(0, len(region) - 6, 6)]
        self.assertGreater(sum(a != b for a, b in pairs), len(pairs) // 4)
        self.assertEqual(lp.cover_image(self.cover.jpeg).tobytes(), expected.tobytes())

    def test_a_stale_or_undecodable_cover_is_never_drawn(self):
        blank = lp.render_lcd(self.home(artKey=''), None, artwork2=True).tobytes()
        self.assertEqual(lp.render_lcd(self.home(artKey='0' * 24), self.cover.jpeg, artwork2=True).tobytes(),
                         lp.render_lcd(self.home(artKey='0' * 24), None, artwork2=True).tobytes(), 'key mismatch')
        from io import BytesIO
        from control_center.artwork import cover_key
        small, progressive = BytesIO(), BytesIO()
        Image.new('RGB', (120, 120), (200, 10, 10)).save(small, format='JPEG')
        self.cover.preview.save(progressive, format='JPEG', progressive=True)
        for data in (b'\xff\xd8garbage', small.getvalue(), progressive.getvalue(), bytes(40000)):
            with self.subTest(size=len(data)):
                image = lp.render_lcd(self.home(artKey=cover_key(data)), data, artwork2=True)
                self.assertIsNone(lit_bbox(image, self.ART_ROWS))
        self.assertIsNotNone(lit_bbox(lp.render_lcd(self.home(), self.cover.jpeg, artwork2=True), self.ART_ROWS))
        self.assertIsNone(lit_bbox(lp.render_lcd(frame('wi-brw', artKey=self.cover.jpeg_key), self.cover.jpeg,
                                                 artwork2=True), self.ART_ROWS), 'never on windows')
        self.assertNotEqual(blank, lp.render_lcd(self.home(), self.cover.jpeg, artwork2=True).tobytes())

    def test_art_dim_applies_to_the_jpeg_cover(self):
        f = frame('ra-na', artKey=self.cover.jpeg_key)
        dimmed = lp.render_lcd(f, self.cover.jpeg, artwork2=True).convert('RGB').crop(self.ART_ROWS)
        full = self.expected_cover().crop(self.ART_ROWS)
        for a, b in zip(rgb_pixels(full), rgb_pixels(dimmed)):
            self.assertEqual(b, tuple(round(v * lp.ART_DIM) for v in a))

    def icon(self, colour=(255, 0, 0, 255)):
        from control_center.artwork import icon_payload
        return icon_payload(Image.new('RGBA', (32, 32), colour))

    def test_the_icon_fills_the_tile_open_and_closed(self):
        key, payload = self.icon()
        opened = lp.render_lcd(frame('wi-brw', iconKey=key), None, payload, artwork2=True)
        self.assertEqual({opened.getpixel((x, y))[:3] for x in range(104, 136) for y in range(42, 74)}, {(255, 0, 0)})
        closed = lp.render_lcd(frame('wi-closed', iconKey=key), None, payload, artwork2=True)
        self.assertEqual({closed.getpixel((x, y))[:3] for x in range(104, 136) for y in range(42, 74)}, {(89, 0, 0)})
        self.assertEqual(lp.compose(frame('wi-brw', iconKey=key), window_icon=True, artwork2=True)
                         .texts('tile-initial'), [])
        key, payload = self.icon((200, 100, 40, 128))
        half = lp.render_lcd(frame('wi-brw', iconKey=key), None, payload, artwork2=True)
        self.assertEqual(half.getpixel((110, 50))[:3], lp.icon_image(payload).getpixel((0, 0)))

    def test_an_rgba_icon_is_drawn_through_its_payload(self):
        from control_center.artwork import icon_payload
        rng = __import__('random').Random(4)
        image = Image.frombytes('RGBA', (32, 32), bytes(rng.randrange(256) for _ in range(4096)))
        key, payload = icon_payload(image)
        f = frame('wi-brw', iconKey=key)
        self.assertEqual(lp.render_lcd(f, None, image, artwork2=True).tobytes(),
                         lp.render_lcd(f, None, payload, artwork2=True).tobytes())

    def test_the_letter_tile_shows_without_a_matching_icon(self):
        key, payload = self.icon()
        letter = lp.render_lcd(frame('wi-brw'), None, None, artwork2=True)
        accent = rgb(sat_rgb(lp.normalize(frame('wi-brw'))['ring']['colors'][1]))
        self.assertEqual(letter.getpixel((106, 44))[:3], accent)
        for f, icon in ((frame('wi-brw'), payload),                        # no iconKey: letter tile
                        (frame('wi-brw', iconKey='f' * 16), payload),        # another icon's key
                        (frame('wi-brw', iconKey='bad key!'), payload),      # malformed: stripped
                        (frame('wi-brw', iconKey=key), payload[:-2]),        # not 2048 bytes
                        (frame('wi-brw', iconKey=key), object())):
            with self.subTest(iconKey=f.get('iconKey')):
                self.assertEqual(lp.render_lcd(f, None, icon, artwork2=True).tobytes(), letter.tobytes())
        self.assertEqual(lp.normalize(frame('wi-brw', iconKey='x' * 25))['iconKey'], '')
        self.assertEqual(lp.normalize(frame('wi-brw', iconKey=key))['iconKey'], key)
        self.assertEqual(lp.normalize(frame('wi-brw'))['iconKey'], '')

    def test_the_initial_is_upper_cased_with_artwork2(self):
        for subtitle, cc53, cc52 in (('chrome', 'C', 'c'), ('Claude', 'C', 'C'), ('élan', 'é', 'é'),
                                     ('1Password', '1', '1'), ('zed', 'Z', 'z')):
            with self.subTest(subtitle=subtitle):
                f = frame('wi-brw', subtitle=subtitle)
                self.assertEqual(lp.compose(f, artwork2=True).texts('tile-initial')[0].text, cc53)
                self.assertEqual(lp.compose(f, artwork2=False).texts('tile-initial')[0].text, cc52)
                self.assertEqual(lp.tile_initial(subtitle, True), cc53)
        self.assertEqual(lp.compose(frame('wi-brw', subtitle=''), artwork2=True).texts('tile-initial'), [])

    def test_artwork2_changes_nothing_else(self):
        for case in FIXTURES['cases']:
            f = case['frame']
            if f is None or (f.get('layout') == 'windows' and (f.get('subtitle') or '')[:1].islower()):
                continue
            with self.subTest(case=case['id']):
                self.assertEqual(lp.render_lcd(f, None, artwork2=True).tobytes(), lp.render_lcd(f).tobytes())


class PreviewExportTests(unittest.TestCase):
    def test_preview_lights_match_the_fixture_leds_and_show_flashes(self):
        for case in FIXTURES['cases']:
            f = case['frame']
            with self.subTest(case=case['id']):
                ring, buttons = render_previews.lights(f)
                if f is None:
                    self.assertEqual((set(ring), set(buttons)), ({0}, {0}))
                    continue
                self.assertEqual((ring, buttons), (case['leds']['ring'], case['leds']['buttons']))
                if render_previews.flash_kind(f):
                    unflashed, _ = render_previews.lights({k: v for k, v in f.items() if k != 'feedback'})
                    self.assertNotEqual(ring, unflashed)


# --------------------------------------------------------------------------
# Floating knob: render_lcd(..., scale=k) (FLOATING_KNOB.md section 3)
# --------------------------------------------------------------------------
SCALES = (360 / 286, 1.5, 2.0, 720 / 286, 3.6)      # 100 % and 200 % DPI are 360/286 and 720/286


def ink_fraction_midtones(image, box):
    """Share of inked pixels (grey > 24) that are mid-tones (< 200): blur raises it."""
    grey = image.convert('L').crop(box).tobytes()
    ink_ = [v for v in grey if v > 24]
    return sum(v < 200 for v in ink_) / max(1, len(ink_))


def edge_energy(image, box):
    from PIL import ImageFilter
    edges = image.convert('L').crop(box).filter(ImageFilter.FIND_EDGES).tobytes()
    return sum(v * v for v in edges) / len(edges)


def scaled_box(box, k):
    return tuple(round(v * k) for v in box)


class ScaledRenderTests(unittest.TestCase):
    """At scale k the same layout is painted at round(240 * k) px, never upscaled from 240."""

    @classmethod
    def setUpClass(cls):
        from control_center.artwork import icon_payload, prepare_artwork2
        source = ROOT / 'design-reference' / 'design_handoff_nano_d_artwork_color' / 'assets' / 'covers'
        cls.cover = prepare_artwork2((source / 'night-drive-chromatics-album-.jpg').read_bytes())
        cls.icon_rgba = Image.new('RGBA', (32, 32), (200, 100, 41, 255))
        cls.icon_key, cls.payload = icon_payload(cls.icon_rgba)

    def test_size_mode_and_anti_aliased_glass(self):
        for k in SCALES:
            with self.subTest(k=k):
                image = lp.render_lcd(frame('home'), scale=k)
                px = round(240 * k)
                self.assertEqual((image.mode, image.size, lp.lcd_pixels(k)), ('RGBA', (px, px), px))
                alpha = image.getchannel('A')
                self.assertEqual((alpha.getpixel((0, 0)), alpha.getpixel((px // 2, px // 2))), (0, 255))
                self.assertTrue(any(0 < v < 255 for v in alpha.tobytes()), 'anti-aliased rim')
        self.assertEqual(set(lp.render_lcd(frame('home')).getchannel('A').tobytes()), {0, 255})
        self.assertEqual(lp.lcd_pixels(1), 240)

    def test_invalid_scales_are_refused(self):
        for bad in (0, -1, float('nan'), float('inf'), True, '2', None):
            with self.subTest(scale=bad), self.assertRaises(ValueError):
                lp.render_lcd(frame('home'), scale=bad)

    def test_scale_1_is_the_native_render_and_ignores_hires_sources(self):
        f = frame('wi-brw', iconKey=self.icon_key)
        native = lp.render_lcd(f, None, self.payload, artwork2=True).tobytes()
        for k in (1, 1.0):
            self.assertEqual(lp.render_lcd(f, None, self.payload, artwork2=True, scale=k,
                                           hires_icon=Image.new('RGBA', (128, 128), 'lime')).tobytes(), native)

    def test_same_layout_as_the_knob(self):
        """Lit regions of every fixture case match the 240 render scaled, within about one knob pixel."""
        cases = [(c['id'], c['frame']) for c in FIXTURES['cases']] + [(n, V5_INPUTS[n]) for n in (
            'v5-seek-p5', 'v5-explorer-tab1-p5', 'v5-upnext-p5', 'heart-lit-on-no-colour', 'v5-windows-snap-p5')]
        for case_id, f in cases:
            for k in (720 / 286, 1.5):
                with self.subTest(case=case_id, k=k):
                    px = round(240 * k)
                    native = lit_bbox(lp.render_lcd(f), (0, 0, 240, 240))
                    scaled = lit_bbox(lp.render_lcd(f, scale=k), (0, 0, px, px))
                    if native is None:
                        self.assertIsNone(scaled)
                        continue
                    for a, b in zip(native, scaled):
                        self.assertLessEqual(abs(a * k - b), 1.5 * k + 1)

    def test_text_is_crisper_than_the_upscaled_240(self):
        from PIL import Image as PILImage
        for case_id in ('home', 'ra-item', 'wi-brw', 'home-turn', 'tr-neu'):
            f = frame(case_id)
            for k in (360 / 286, 720 / 286):
                px = round(240 * k)
                direct = lp.render_lcd(f, scale=k)
                upscaled = lp.render_lcd(f).resize((px, px), PILImage.Resampling.LANCZOS)
                box = scaled_box((40, 30, 200, 150), k)
                with self.subTest(case=case_id, k=k):
                    self.assertLess(ink_fraction_midtones(direct, box), ink_fraction_midtones(upscaled, box))
                    if k > 2:
                        self.assertGreater(edge_energy(direct, box), 1.3 * edge_energy(upscaled, box))

    def test_the_hires_cover_replaces_the_240_cover(self):
        k = 720 / 286
        f = frame('home', artKey=self.cover.jpeg_key)
        box = scaled_box(Artwork2MirrorTests.ART_ROWS, k)
        magenta = Image.new('RGB', (480, 480), (255, 0, 255))
        with_hires = lp.render_lcd(f, self.cover.jpeg, artwork2=True, scale=k, hires_cover=magenta)
        self.assertEqual(set(rgb_pixels(with_hires.crop(box))), {(255, 0, 255)})
        without = lp.render_lcd(f, self.cover.jpeg, artwork2=True, scale=k)
        self.assertNotIn((255, 0, 255), rgb_pixels(without.crop(box)))
        self.assertIsNotNone(lit_bbox(without, box))
        from io import BytesIO
        decoded = Image.open(BytesIO(self.cover.hires_jpeg)).convert('RGB').resize((round(240 * k),) * 2,
                                                                                     Image.Resampling.LANCZOS)
        drawn_ = lp.render_lcd(f, self.cover.jpeg, artwork2=True, scale=k, hires_cover=self.cover.hires_jpeg)
        self.assertEqual(drawn_.convert('RGB').crop(box).tobytes(), decoded.crop(box).tobytes())
        dimmed = lp.render_lcd(frame('ra-na', artKey=self.cover.jpeg_key), self.cover.jpeg, artwork2=True,
                               scale=k, hires_cover=magenta)
        self.assertEqual(set(rgb_pixels(dimmed.crop(box))), {(round(255 * lp.ART_DIM), 0, round(255 * lp.ART_DIM))})
        for g, art in ((frame('home', artKey='0' * 24), self.cover.jpeg),
                       (frame('wi-brw', artKey=self.cover.jpeg_key), self.cover.jpeg),
                       (frame('home', artKey=self.cover.jpeg_key), None)):
            with self.subTest(layout=g['layout'], artKey=g['artKey'][:4]):
                image = lp.render_lcd(g, art, artwork2=True, scale=k, hires_cover=magenta)
                self.assertNotIn((255, 0, 255), rgb_pixels(image))
        v1 = lp.render_lcd(frame('home'), ART['art-den-120'], scale=k, hires_cover=magenta)
        self.assertEqual(set(rgb_pixels(v1.crop(box))), {(255, 0, 255)})

    def tile(self, image, k):
        x0, y0 = round(104 * k), round(42 * k)
        x1, y1 = round(136 * k), round(74 * k)
        return set(rgb_pixels(image.crop((x0 + 2, y0 + 2, x1 - 2, y1 - 2))))

    def test_the_hires_icon_fills_the_tile(self):
        k = 720 / 286
        lime = Image.new('RGBA', (128, 128), (0, 255, 0, 255))
        opened = lp.render_lcd(frame('wi-brw', iconKey=self.icon_key), None, self.payload, artwork2=True,
                               scale=k, hires_icon=lime)
        self.assertEqual(self.tile(opened, k), {(0, 255, 0)})
        closed = lp.render_lcd(frame('wi-closed', iconKey=self.icon_key), None, self.payload, artwork2=True,
                               scale=k, hires_icon=lime)
        self.assertEqual(self.tile(closed, k), {(0, round(255 * lp.CLOSED_OPACITY), 0)})
        rgba = lp.render_lcd(frame('wi-brw', iconKey=self.icon_key), None, self.icon_rgba, artwork2=True, scale=k)
        self.assertEqual(self.tile(rgba, k), {(200, 100, 41)})
        payload = lp.render_lcd(frame('wi-brw', iconKey=self.icon_key), None, self.payload, artwork2=True, scale=k)
        self.assertEqual(self.tile(payload, k), {lp.icon_image(self.payload).getpixel((0, 0))})
        # No payload: the knob's letter tile (here the app accent, section 5.3); the desktop may show
        # the hi-res icon (a UWP app).
        letter = lp.render_lcd(frame('wi-brw'), None, None, artwork2=True, scale=k)
        self.assertIn(rgb(sat_rgb(lp.normalize(frame('wi-brw'))['ring']['colors'][1])), self.tile(letter, k))
        uwp = lp.render_lcd(frame('wi-brw'), None, None, artwork2=True, scale=k, hires_icon=lime)
        self.assertEqual(self.tile(uwp, k), {(0, 255, 0)})
        self.assertEqual(lp.render_lcd(frame('wi-brw'), None, None, artwork2=True, hires_icon=lime).tobytes(),
                         lp.render_lcd(frame('wi-brw'), None, None, artwork2=True).tobytes(), 'scale 1: ignored')
        wide = Image.new('RGBA', (128, 64), (0, 255, 0, 255))
        fitted = lp.render_lcd(frame('wi-brw', iconKey=self.icon_key), None, self.payload, artwork2=True,
                               scale=k, hires_icon=wide)
        self.assertEqual(fitted.getpixel((round(120 * k), round(46 * k)))[:3], (0, 0, 0))
        self.assertEqual(fitted.getpixel((round(120 * k), round(58 * k)))[:3], (0, 255, 0))

    def test_icons_use_the_hires_masks(self):
        self.assertIs(lp.scaled_icon_mask('play', 20, 20), lp.icon_mask('play', 20))
        with Image.open(lp.HIRES_ICON_DIR / 'play-20@2x.png') as source:
            self.assertEqual(lp.scaled_icon_mask('play', 20, 40).tobytes(),
                             source.convert('RGBA').getchannel('A').tobytes())
        for size, pixels, factor in ((20, 25, 2), (20, 50, 3), (26, 33, 2), (16, 48, 3), (20, 72, 3)):
            with self.subTest(size=size, pixels=pixels):
                with Image.open(lp.HIRES_ICON_DIR / f'play-{size}@{factor}x.png') as source:
                    expected = source.convert('RGBA').getchannel('A')
                if expected.size != (pixels, pixels):
                    expected = expected.resize((pixels, pixels), Image.Resampling.LANCZOS)
                self.assertEqual(lp.scaled_icon_mask('play', size, pixels).tobytes(), expected.tobytes())
        self.assertIsNone(lp.scaled_icon_mask('', 20, 40))
        self.assertIsNone(lp.scaled_icon_mask('nope', 20, 40))
        image = lp.render_lcd(frame('home'), scale=2).convert('RGB')
        run = lp.compose(frame('home')).icons('footer')[0]
        box = (run.x * 2, run.y * 2, run.x * 2 + 40, run.y * 2 + 40)
        mask = lp.scaled_icon_mask(run.name, 20, 40)
        drawn_ = image.crop(box).getchannel('R').tobytes()
        expected = bytes(round(v * run.ink[0] / 255) for v in mask.tobytes())
        self.assertLessEqual(max(abs(a - b) for a, b in zip(drawn_, expected)), 1)

    def test_debug_overlay_only_at_scale_1(self):
        k = 1.5
        self.assertEqual(lp.render_lcd(frame('home'), overlay=True, scale=k).tobytes(),
                         lp.render_lcd(frame('home'), scale=k).tobytes())

    def test_placeholder_glyphs_the_offline_screen_and_seek_render_at_scale(self):
        k = 720 / 286
        image = lp.render_lcd(frame('home', title='A中文 B'), scale=k)
        self.assertIsNotNone(lit_bbox(image, (0, 0) + image.size))
        self.assertIsNotNone(lit_bbox(lp.render_lcd(None, scale=k), (0, 0) + image.size))
        seek = lp.render_lcd(v5('v5-seek-p5'), scale=k)
        self.assertIsNotNone(lit_bbox(seek, scaled_box((60, 80, 180, 118), k)))

    def test_shadows_at_scale_are_masked_pastes_over_the_run_box(self):
        # DESKTOP_STAGE.md 11.5: no alpha_composite at scale > 1; a shadow darkens one knob pixel below.
        import unittest.mock as mock
        with mock.patch.object(lp.Image, 'alpha_composite', side_effect=AssertionError('alpha_composite')):
            lp.render_lcd(frame('home', artKey='k'), Image.new('RGB', (240, 240), (200, 200, 200)), scale=720 / 286)


class HiresIconAssetTests(unittest.TestCase):
    """assets/lcd-icons/{name}-{size}@2x/@3x.png: the shipped icon paths exported larger (PNG only)."""

    def test_every_icon_has_2x_and_3x_masks_of_the_same_paths(self):
        names = sorted((set(ICONS) - {''}) | {'heartfill'})
        self.assertEqual(len(names), 22)
        sizes = {name: (16, 20, 26) for name in names}
        sizes['dotfill'] = (16,)
        for name, name_sizes in sizes.items():
            for size in name_sizes:
                base = lp.icon_mask(name, size)
                self.assertIsNotNone(base, (name, size))
                for factor in lp.HIRES_ICON_FACTORS:
                    with self.subTest(name=name, size=size, factor=factor):
                        path = lp.HIRES_ICON_DIR / f'{name}-{size}@{factor}x.png'
                        with Image.open(path) as source:
                            image = source.convert('RGBA')
                        self.assertEqual(image.size, (size * factor, size * factor))
                        inked = image.tobytes()
                        self.assertEqual({inked[i] & inked[i + 1] & inked[i + 2] for i in range(0, len(inked), 4)
                                          if inked[i + 3]}, {255})                    # white + alpha
                        alpha = image.getchannel('A')
                        reduced = alpha.reduce(factor).tobytes()
                        diff = sum(abs(a - b) for a, b in zip(reduced, base.tobytes())) / len(reduced)
                        self.assertLess(diff, 12)                                      # the same strokes
                        ink_ = sum(alpha.tobytes()) / sum(base.tobytes())
                        self.assertAlmostEqual(ink_, factor * factor, delta=0.25 * factor * factor)

    def test_no_stale_hires_masks_of_dropped_tokens(self):
        # PRESENTATION_V5.md 9.1: ok, dot, warn and usb were dropped; their @2x/@3x exports are gone.
        stale = sorted(p.name for p in lp.HIRES_ICON_DIR.glob('*@*x.png')
                       if p.name.split('-')[0] in ('ok', 'dot', 'warn', 'usb'))
        self.assertEqual(stale, [])

    def test_the_exporter_png_only_mode_never_writes_firmware(self):
        exporter = ROOT.parent / 'harness' / 'export_handoff_icons.cjs'
        if not exporter.is_file():
            self.skipTest('firmware workspace not present')
        text = exporter.read_text(encoding='utf-8')
        png_only = text[text.index('async function pngOnly'):text.index('if (PNG_ONLY)')]
        self.assertNotIn('cc_icons', png_only)
        self.assertIn('fidelity gate', png_only)
        self.assertIn("else if (ARGS.length)", text)          # any other argument is refused


if __name__ == '__main__':
    if '--print-font-metrics' in sys.argv:
        print(encode_font_metrics(extract_font_metrics()))
    else:
        unittest.main()
