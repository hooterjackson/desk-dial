"""Validation for the generated knob fonts (cc5 Stage 6), without building LVGL.

Reads the generated ``firmware/src/fonts/cc_font_*.c`` and the
built-in ``lv_font_montserrat_<N>.c`` from the pinned LVGL 9.0.0 tree, and
decodes both with a line-by-line Python port of LVGL 9.0's
``get_glyph_dsc_id``, ``lv_font_get_glyph_dsc_fmt_txt`` (advance rounding) and
the 4 bpp branch of ``lv_font_get_bitmap_fmt_txt``.

Hybrid layout (the default since cc5 Stage 6): cc_font_12/14/16/22 hold only
the non-ASCII part of the advertised set (U+00A0-017F plus the punctuation);
ASCII resolves through the REQUIRED .fallback lv_font_montserrat_<N>, i.e. the
cc4 glyphs and kerning. cc_font_48 stays digits-only with an optional fallback
(NULL while LV_FONT_MONTSERRAT_48 is 0 in the firmware lv_conf.h).

(a) Every requested codepoint resolves through the cmaps to its glyph, and the
    decoded bitmap equals Pillow's mask for that character (rendered here
    through ``getmask2`` with ``set_variation_by_name('Medium')``, independent
    of the generator's ImageDraw path), quantised to 4 bpp, pixel for pixel
    and in the same place relative to the pen origin and baseline. Packing,
    cmap and descriptor invariants are checked too, and non-requested
    codepoints -- every ASCII character of a hybrid font -- must miss (so the
    .fallback font is consulted).
(b) Hybrid fonts: every ASCII character resolves in the built-in fallback;
    accented Latin letters are consistent with the built-in's base letter
    (advance within 1 px; for marks above, the same box bottom within 1 px);
    mixed runs resolve completely (no placeholder) and their widths are
    reported with LVGL's fallback lookup (built-in kerning between ASCII
    pairs only). cc_font_48 ('0-9%-'): against the built-in Montserrat 48:
    advance, box, mean absolute difference and IoU of the aligned bitmaps.
    Hinting/antialiasing differences are reported, not failed; a glyph fails
    only when it is structurally broken (see STRUCTURAL_*).
(c) line_height/base_line/underline equal to the built-ins, the fallback
    declaration (required + #error guard for hybrids, conditional for 48),
    own ink extents vs the line box, and the CSS line-box baselines of the
    design (Knob Face.dc.html pairs) vs LVGL's label baseline.
(d) Flash: an estimate from the table sizes (ESP32, 4-byte pointers,
    LV_FONT_FMT_TXT_LARGE 0) and, when the PlatformIO ESP32-S3 toolchain is
    present, the measured .rodata of each object compiled with the firmware's
    C flags; the same for the built-ins; plus which built-ins the last
    firmware link kept (firmware.map).
(e) Toolchain checks (optional): with the firmware lv_conf.h every C file
    compiles warning-free as C (gnu99, -Wall -Wextra -Wpedantic); hybrids
    reference their built-in, cc_font_48 references lv_font_montserrat_48 only
    when it is enabled; with the built-ins off a hybrid FAILS with its #error
    and cc_font_48 compiles with a NULL fallback; cc_fonts.h compiles as C++11
    and its declarations have C linkage (unmangled undefined symbols).
(f) The generator is deterministic (--check equivalent) and fails on a
    codepoint the font lacks, and on U+00AD with --strict; --with-ascii builds
    the standalone comparison layout and refuses to overwrite the firmware set.
(t) cc_font_48t (1.0.0-cc5.4, PRESENTATION_V5.md section 10; harness
    `seek_digits` at the font level): its cmap maps U+0030-0039 to the glyphs
    named zero.tf..nine.tf (read here with an independent post-table parser)
    and U+003A to the ordinary colon; (a) decodes against Pillow's mask of the
    remapped font; every digit has the same advance (0 px jitter: the digit
    cells of every m:ss with the same number of digits sit at identical x), ':'
    is drawn, line metrics equal cc_font_48's (baseline 116 at y 73), and the
    Seek widths at tracking -1 (0:00..9:59, 10:00..99:59, 999:59) fit the
    192 px chord of rows 81-116.
(g) Icons (PRESENTATION_V5.md section 9; harness `icons`): src/cc_icons.cpp
    holds exactly the 9.1 token/size table (22 x 20 px + 5 x 26 px + 3 x 16 px =
    12,948 B of A8: r2.1's 12,548 B plus the r2.2 internal heartfill), each mask
    equal to the desktop PNG of the same token and size; the snap masks carry
    their filled half; dotfill is a 6 px disc; heartfill-20 is the heart path
    filled (solid over the stroked heart's interior, nothing outside its
    outline); the CCIcon enum order matches; every wire token and heartfill
    has desktop PNGs at 16/20/26 and @2x/@3x; export_handoff_icons.cjs --check
    passes (byte identity and the r2.1 drift gate) and no longer reads the old
    knob-model.js (9.2 item 1); the ESP32-S3 .rodata of cc_icons.o is measured. (m) With
    MSVC present, cc_icons.cpp and every font compile with /W4 /WX (the harness
    compiler; skipped with --no-toolchain). The other
    lock-step tables (cc_frame_parse kIcons, cc_display ICON_NAMES,
    presentation.ICONS) are reported, not failed: other packages own them.

No LVGL build, no USB, no device, no network. Exit status 1 on any failure.
Usage: .venv python harness/font_tests.py [--json OUT.json] [--no-toolchain] [--no-node]
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

from PIL import Image, ImageFont

import gen_lvgl_font as gen

ROOT = Path(__file__).resolve().parent
FONT_DIR = gen.OUT_DIR
LVGL = gen.LVGL
PIO_CORE = Path(os.environ.get('NANOD_PIO_CORE') or os.environ.get('PLATFORMIO_CORE_DIR')
                or Path.home() / '.platformio')   # same order as cpp11_gate.py
TOOLCHAIN = PIO_CORE / 'packages' / 'toolchain-xtensa-esp32s3' / 'bin'
FIRMWARE_MAP = gen.FIRMWARE / '.pio' / 'build' / 'nanofoc_d' / 'firmware.map'

OPA4 = [0, 17, 34, 51, 68, 85, 102, 119, 136, 153, 170, 187, 204, 221, 238, 255]
CMAP_TYPES = {'LV_FONT_FMT_TXT_CMAP_FORMAT0_FULL': 0, 'LV_FONT_FMT_TXT_CMAP_SPARSE_FULL': 1,
              'LV_FONT_FMT_TXT_CMAP_FORMAT0_TINY': 2, 'LV_FONT_FMT_TXT_CMAP_SPARSE_TINY': 3}

# (b) Report thresholds ("large mismatch") and structural-failure thresholds.
# MAD = mean |a-b| over the union box in 0..255 units; IoU over pixels >= 50 %
# coverage; "best" = best of the nine +-1 px shifts (hinting moves 1 px strokes).
REPORT_BEST_MAD = 30.0
REPORT_BEST_IOU = 0.60
REPORT_SHIFT = 0.60        # ink centroid shift, px
REPORT_INK = 0.20          # |ink mass ratio - 1|
REPORT_LIST = 10           # worst glyphs printed per size (all are in --json)
# Structural = wrong glyph, size, weight or placement, not hinting. Pixel-exact
# decoding is (a)'s job; thin strokes (=, -, `) legitimately lose all IoU when
# hinting moves them a row, so IoU only counts for glyphs with enough ink.
STRUCTURAL_ADV_PX = 1      # LVGL-rounded advance may differ by at most 1 px
STRUCTURAL_BOX = 3         # box_w/box_h may differ by at most 3 px
STRUCTURAL_INK = 0.45      # ink mass ratio outside 1 +- this means a wrong weight/size
STRUCTURAL_SHIFT = 1.5     # ink centroid shift, px
STRUCTURAL_BEST_IOU = 0.40
STRUCTURAL_IOU_MIN_ON = 25 # on-pixels (>= 50 %) both glyphs need before IoU is judged

# Knob Face.dc.html (font-size px, line-height px) pairs.
CSS_PAIRS = [(12, 14), (14, 18), (16, 20), (16, 16), (22, 26), (48, 46)]

# Firmware C flags (framework-arduinoespressif32 platformio-build-esp32s3.py).
C_FLAGS = ['-std=gnu99', '-Os', '-mlongcalls', '-ffunction-sections', '-fdata-sections', '-fno-jump-tables',
           '-fstrict-volatile-bitfields', '-Wno-old-style-declaration']
CXX_FLAGS = ['-std=gnu++11', '-fexceptions', '-fno-rtti', '-Os', '-mlongcalls']
WARN_FLAGS = ['-Wall', '-Wextra', '-Wpedantic']

SAMPLE_RUNS = ['Living Room', 'Volume', 'AVATAR', 'Tokyo Drift', "It's All Right", 'Recently Added',
               '0123456789', '100%']
# Mixed ASCII + Latin-Ext-A runs for the hybrid fonts (fixture copy included).
MIXED_RUNS = ['Copper Sun Sessions', 'Linnéa Holm — Homogénic', 'Łódź · Kraków', 'Doesn’t play…',
              'RECENTLY ADDED · P2', 'Zoë Café', 'Dvořák: Symphony 9']
# cc_font_48t: the Seek time (PRESENTATION_V5 sections 8.5.1, 8.6.8, 10).
SEEK_TRACKING = -1             # label letter space, px
SEEK_CHORD = 192               # safe chord of rows 81-116 (r 104)
SEEK_SAMPLES = {3: ['0:00', '1:14', '4:47', '9:59'], 4: ['10:00', '47:11', '59:59', '99:59'], 5: ['100:00', '999:59']}

# Icons: PRESENTATION_V5 section 9.1 (token -> firmware mask sizes), CCIcon order, mask bytes.
ICON_ENUM = ('play', 'pause', 'list', 'win', 'tracks', 'back', 'home', 'more', 'prev', 'next', 'switch', 'cancel',
             'expand', 'clock', 'playlists', 'playnext', 'seek', 'shuffle', 'heart', 'snapleft', 'snapright',
             # presentation 6 (PRESENTATION_V5.md section 19.5): the r3 prototype icons, bulb also at 26 px
             'bulb', 'thermo', 'power', 'wand', 'house', 'album')
ICON_SIZES = {**{token: (20,) for token in ICON_ENUM}, 'bulb': (20, 26), 'house': (20, 26), 'album': (20, 26), 'play': (20, 26), 'pause': (20, 26), 'list': (20, 26),
              'win': (20, 26), 'tracks': (20, 26), 'prev': (16, 20), 'next': (16, 20), 'dotfill': (16,),
              'heartfill': (20,)}                # [r2.2] internal: tone `liked` (P5-R29), the heart filled
ICON_MASK_BYTES = 17376                          # 12,548 B (r2.1) + heartfill 400 + presentation 6 (6 x 400 + 676)
#                                                  + r3.1 house / album 26 px (2 x 676)
ICON_DESKTOP = ICON_ENUM + ('heartfill',)        # desktop copies at 16/20/26 and @2x/@3x (dotfill: 16 px only)
ICON_ASSETS = gen.WORKSPACE / 'app' / 'assets'
ICON_EXPORTER = ROOT / 'export_handoff_icons.cjs'

# Hybrid base-letter consistency: advance (px) and, for marks above, box bottom (px).
STRUCTURAL_BASE_ADV_PX = 1
STRUCTURAL_BASE_BOTTOM_PX = 1


class Report:
    def __init__(self):
        self.failures = []
        self.data = {}

    def fail(self, message):
        self.failures.append(message)
        print(f'FAIL {message}')

    def check(self, condition, message):
        if not condition:
            self.fail(message)
        return condition


# --------------------------------------------------------------------------
# C parsing (works for lv_font_conv built-ins and the generated files)
# --------------------------------------------------------------------------
def _array_body(text, name):
    m = re.search(r'\b' + re.escape(name) + r'\[\]\s*=\s*\{(.*?)\n\};', text, re.S)
    return m.group(1) if m else None


def parse_font_c(path: Path) -> dict:
    raw = path.read_text(encoding='utf-8', errors='replace')
    text = re.sub(r'/\*.*?\*/', '', raw, flags=re.S)
    text = re.sub(r'//[^\n]*', '', text)
    font = {'path': str(path)}
    font['bitmap'] = bytes(int(x, 16) for x in re.findall(r'0x[0-9a-fA-F]+', _array_body(text, 'glyph_bitmap')))
    font['glyph_dsc'] = [tuple(int(v) for v in m) for m in re.findall(
        r'\{\s*\.bitmap_index\s*=\s*(\d+),\s*\.adv_w\s*=\s*(\d+),\s*\.box_w\s*=\s*(\d+),\s*\.box_h\s*=\s*(\d+),'
        r'\s*\.ofs_x\s*=\s*(-?\d+),\s*\.ofs_y\s*=\s*(-?\d+)\s*\}', _array_body(text, 'glyph_dsc'))]
    lists = {name: [int(v, 0) for v in re.findall(r'0x[0-9a-fA-F]+|\d+', body)]
             for name, body in re.findall(r'static const uint16_t (unicode_list_\d+)\[\]\s*=\s*\{(.*?)\};', text, re.S)}
    font['cmaps'] = []
    for m in re.finditer(r'\.range_start\s*=\s*(\d+),\s*\.range_length\s*=\s*(\d+),\s*\.glyph_id_start\s*=\s*(\d+),'
                         r'\s*\.unicode_list\s*=\s*(\w+),\s*\.glyph_id_ofs_list\s*=\s*(\w+),'
                         r'\s*\.list_length\s*=\s*(\d+),\s*\.type\s*=\s*(\w+)', _array_body(text, 'cmaps')):
        font['cmaps'].append({'range_start': int(m[1]), 'range_length': int(m[2]), 'glyph_id_start': int(m[3]),
                              'unicode_list': None if m[4] == 'NULL' else lists[m[4]],
                              'glyph_id_ofs_list': m[5], 'list_length': int(m[6]), 'type': m[7]})

    def field_(name, pattern=r'(-?\d+)'):
        m = re.search(r'\.' + name + r'\s*=\s*' + pattern, text)
        return m.group(1) if m else None

    for name in ('kern_scale', 'cmap_num', 'bpp', 'kern_classes', 'bitmap_format', 'line_height', 'base_line',
                 'underline_position', 'underline_thickness'):
        value = field_(name)
        font[name] = int(value) if value is not None else None
    font['kern_dsc'] = field_('kern_dsc', r'([&\w]+)')
    m = re.search(r'#if\s+(LV_FONT_MONTSERRAT_\d+)\s*\.fallback\s*=\s*&(\w+),\s*#else\s*\.fallback\s*=\s*NULL,\s*#endif',
                  text)
    font['fallback_guard'] = (m.group(1), m.group(2)) if m else None
    # Hybrid fonts: an unconditional fallback plus an #error when the built-in is off.
    m = re.search(r'^\s*\.fallback\s*=\s*&(\w+),', text, re.M)
    required = m.group(1) if m and not font['fallback_guard'] else None
    m = re.search(r'#if\s+!\s*(LV_FONT_MONTSERRAT_\d+)\s*#error\s*"[^"]*"\s*#endif', text)
    font['fallback_required'] = (m.group(1), required) if m and required else None
    font['public_name'] = (re.search(r'\bconst lv_font_t (\w+)\s*=', text) or [None, None])[1]
    if font['kern_classes'] == 1 and _array_body(text, 'kern_class_values'):
        font['kern'] = {
            'left': [int(v) for v in re.findall(r'-?\d+', _array_body(text, 'kern_left_class_mapping'))],
            'right': [int(v) for v in re.findall(r'-?\d+', _array_body(text, 'kern_right_class_mapping'))],
            'values': [int(v) for v in re.findall(r'-?\d+', _array_body(text, 'kern_class_values'))],
            'right_cnt': int(field_('right_class_cnt')),
        }
    return font


# --------------------------------------------------------------------------
# LVGL 9.0 ports
# --------------------------------------------------------------------------
def lv_glyph_id(font: dict, letter: int) -> int:
    """Port of lv_font_fmt_txt.c get_glyph_dsc_id(): the FIRST cmap whose range holds the letter decides."""
    if letter == 0:
        return 0
    for cmap in font['cmaps']:
        rcp = (letter - cmap['range_start']) & 0xFFFFFFFF
        if rcp >= cmap['range_length']:
            continue
        kind = cmap['type']
        if kind == 'LV_FONT_FMT_TXT_CMAP_FORMAT0_TINY':
            return cmap['glyph_id_start'] + rcp
        if kind == 'LV_FONT_FMT_TXT_CMAP_SPARSE_TINY':
            key = rcp & 0xFFFF
            items = cmap['unicode_list'][:cmap['list_length']]
            lo, hi = 0, len(items) - 1
            while lo <= hi:
                mid = (lo + hi) // 2
                if items[mid] == key:
                    return cmap['glyph_id_start'] + mid
                if items[mid] < key:
                    lo = mid + 1
                else:
                    hi = mid - 1
            return 0
        raise ValueError(f'cmap type {kind} not handled by this port')
    return 0


def lv_adv_px(font: dict, gid: int, gid_next: int = 0) -> int:
    """lv_font_get_glyph_dsc_fmt_txt(): (adv_w + kern) rounded to px."""
    adv = font['glyph_dsc'][gid][1]
    kern = font.get('kern')
    if font.get('kern_dsc') not in (None, 'NULL') and kern and gid_next:
        left, right = kern['left'][gid], kern['right'][gid_next]
        if left > 0 and right > 0:
            value = kern['values'][(left - 1) * kern['right_cnt'] + (right - 1)]
            adv += (value * font['kern_scale']) >> 4
    return (adv + 8) >> 4


def lv_decode(font: dict, gid: int):
    """4 bpp branch of lv_font_get_bitmap_fmt_txt(): returns rows of A8 values."""
    index, _adv, w, h, _ox, _oy = font['glyph_dsc'][gid]
    data, p, i, rows = font['bitmap'], index, 0, []
    for _y in range(h):
        row = []
        for _x in range(w):
            i &= 1
            if i == 0:
                row.append(OPA4[data[p] >> 4])
            else:
                row.append(OPA4[data[p] & 0xF])
                p += 1
            i += 1
        rows.append(row)
    return rows


def placed_pixels(font: dict, gid: int) -> dict:
    """{(x, y): a8} relative to the pen origin on the baseline (y down), as lv_draw_label places it."""
    _index, _adv, w, h, ofs_x, ofs_y = font['glyph_dsc'][gid]
    top = -(ofs_y + h)
    return {(ofs_x + x, top + y): v for y, row in enumerate(lv_decode(font, gid)) for x, v in enumerate(row) if v}


# --------------------------------------------------------------------------
# Reference rendering (independent of the generator's ImageDraw path)
# --------------------------------------------------------------------------
def reference_face(size: int, data: bytes | None = None):
    """Pillow face at wght 'Medium'; `data` = the bytes of an in-memory font (the tabular remap)."""
    source = io.BytesIO(data) if data is not None else str(gen.FONT_PATH)
    face = ImageFont.truetype(source, size, layout_engine=ImageFont.Layout.BASIC)
    face.set_variation_by_name(gen.WEIGHT_NAME)
    return face


def quantize(a: int) -> int:
    q = (a * 15 + 127) // 255
    assert abs(17 * q - a) <= 8.5
    return q


def reference_pixels(face, char: str) -> dict:
    core, (ox, oy) = face.getmask2(char, mode='L', anchor='ls')
    im = Image.Image()._new(core)
    w, h = im.size
    data = im.tobytes()
    out = {}
    for y in range(h):
        for x in range(w):
            q = quantize(data[y * w + x])
            if q:
                out[(ox + x, oy + y)] = OPA4[q]
    return out


# --------------------------------------------------------------------------
# (a) exact decode
# --------------------------------------------------------------------------
def test_structure_and_decode(report: Report, size: int, font: dict, codepoints, font_cmap, name: str | None = None,
                              font_data: bytes | None = None) -> dict:
    name = name or f'cc_font_{size}'
    ok = report.check(font['bpp'] == 4 and font['bitmap_format'] == 0 and font['kern_dsc'] == 'NULL'
                      and font['kern_classes'] == 0 and font['cmap_num'] == len(font['cmaps']),
                      f'{name}: font_dsc must be bpp 4, plain, no kerning, cmap_num == len(cmaps)')
    dsc = font['glyph_dsc']
    ok &= report.check(dsc[0] == (0, 0, 0, 0, 0, 0), f'{name}: glyph id 0 must be the reserved all-zero entry')
    # Packing: byte-aligned starts, exactly ceil(w*h/2) bytes each, no gaps or overlaps.
    expected = 0
    for gid in range(1, len(dsc)):
        index, adv, w, h, ox, oy = dsc[gid]
        ok &= report.check(index == expected, f'{name}: glyph {gid} bitmap_index {index} != {expected}')
        ok &= report.check(index < 1 << 20 and adv < 1 << 12 and w < 256 and h < 256 and -128 <= ox < 128
                           and -128 <= oy < 128, f'{name}: glyph {gid} overflows glyph_dsc bitfields')
        ok &= report.check((w == 0) == (h == 0), f'{name}: glyph {gid} has a degenerate box {w}x{h}')
        expected = index + (w * h + 1) // 2
    # An all-empty font still emits one 0x00 byte (C forbids an empty initializer).
    ok &= report.check(len(font['bitmap']) == (expected or 1),
                       f'{name}: glyph_bitmap has {len(font["bitmap"])} B, descriptors use {expected} B')
    # cmaps: sorted, non-overlapping, sparse lists strictly ascending, ids contiguous.
    last_end, next_id = -1, 1
    for c in font['cmaps']:
        ok &= report.check(c['type'] in ('LV_FONT_FMT_TXT_CMAP_FORMAT0_TINY', 'LV_FONT_FMT_TXT_CMAP_SPARSE_TINY'),
                           f'{name}: unexpected cmap type {c["type"]}')
        ok &= report.check(c['range_start'] > last_end, f'{name}: cmap ranges overlap or are unsorted')
        ok &= report.check(c['glyph_id_start'] == next_id, f'{name}: cmap glyph ids are not contiguous')
        last_end = c['range_start'] + c['range_length'] - 1
        if c['type'].endswith('SPARSE_TINY'):
            lst = c['unicode_list']
            ok &= report.check(len(lst) == c['list_length'] and all(a < b for a, b in zip(lst, lst[1:]))
                               and lst[0] == 0 and lst[-1] == c['range_length'] - 1 and lst[-1] <= 0xFFFF,
                               f'{name}: sparse unicode_list is not a sorted uint16 offset list spanning the range')
            next_id += len(lst)
        else:
            next_id += c['range_length']
    ok &= report.check(next_id == len(dsc), f'{name}: cmaps map {next_id - 1} glyphs, glyph_dsc has {len(dsc) - 1}')
    sparse = [c for c in font['cmaps'] if c['type'].endswith('SPARSE_TINY')]
    want_sparse = sum(1 for c in gen.build_cmaps(codepoints) if c.type == gen.CMAP_SPARSE_TINY)
    ok &= report.check(len(sparse) == want_sparse,
                       f'{name}: expected {want_sparse} SPARSE_TINY cmap(s), found {len(sparse)}')

    # Lookup: every requested codepoint hits, ids ascend with codepoints, others miss.
    gids = [lv_glyph_id(font, cp) for cp in codepoints]
    ok &= report.check(all(gids) and gids == list(range(1, len(codepoints) + 1)),
                       f'{name}: requested codepoints do not map to glyph ids 1..{len(codepoints)} in order')
    wanted = set(codepoints)
    probes = [0, 0x09, 0x1F, 0x7F, 0x9F, 0x180, 0x2012, 0x2015, 0x2017, 0x201A, 0x201E, 0x2021,
              0x2023, 0x2025, 0x2027, 0x20AC, 0xF001, 0xFFFF, 0x10000, 0x1F600] + list(range(0x20, 0x180))
    stray = [cp for cp in probes if cp >= 0 and cp not in wanted and lv_glyph_id(font, cp)]
    ok &= report.check(not stray, f'{name}: non-requested codepoints resolve locally: {[hex(c) for c in stray]}')

    # Exact pixels vs Pillow.
    face = reference_face(size, font_data)
    mismatched, synthesized, levels_ok = [], [], True
    for cp, gid in zip(codepoints, gids):
        decoded = placed_pixels(font, gid)
        levels_ok &= all(v % 17 == 0 for v in decoded.values())
        if cp in gen.SYNTHESIZE_EMPTY and cp not in font_cmap:
            synthesized.append(cp)
            if decoded or dsc[gid][1] != 0:
                mismatched.append(f'U+{cp:04X} (synthesized glyph must be empty and zero-advance)')
            continue
        if decoded != reference_pixels(face, chr(cp)):
            mismatched.append(f'U+{cp:04X}')
    ok &= report.check(levels_ok, f'{name}: decoded values are not opa4 levels')
    ok &= report.check(not mismatched, f'{name}: {len(mismatched)} glyph(s) differ from the Pillow mask: '
                                       f'{", ".join(mismatched[:12])}')
    print(f'(a) {name}: {len(codepoints)} codepoints, {len(dsc) - 1} glyphs, {len(font["cmaps"])} cmaps; '
          f'decode == Pillow 4 bpp for {len(codepoints) - len(mismatched) - len(synthesized)}'
          f'{f" (+{len(synthesized)} synthesized empty: " + ", ".join(f"U+{c:04X}" for c in synthesized) + ")" if synthesized else ""}'
          f' -> {"PASS" if ok else "FAIL"}')
    return {'glyphs': len(dsc) - 1, 'cmaps': [(c['type'].rsplit('CMAP_', 1)[1], c['range_start'], c['range_length'])
                                              for c in font['cmaps']],
            'exact_decode': not mismatched, 'synthesized': [f'U+{c:04X}' for c in synthesized], 'pass': bool(ok)}


# --------------------------------------------------------------------------
# (b) vs built-in
# --------------------------------------------------------------------------
def _mad_iou(a: dict, b: dict):
    keys = set(a) | set(b)
    if not keys:
        return 0.0, 1.0
    xs = [k[0] for k in keys]
    ys = [k[1] for k in keys]
    area = (max(xs) - min(xs) + 1) * (max(ys) - min(ys) + 1)
    mad = sum(abs(a.get(k, 0) - b.get(k, 0)) for k in keys) / area
    on_a = {k for k, v in a.items() if v >= 128}
    on_b = {k for k, v in b.items() if v >= 128}
    union = on_a | on_b
    return mad, (len(on_a & on_b) / len(union) if union else 1.0)


def compare_glyph(ours: dict, gid_o: int, theirs: dict, gid_t: int) -> dict:
    """Aligned (same pen origin/baseline) and best +-1 px shift MAD/IoU, plus ink-centroid shift.

    Hinting differences often move a 1 px stroke by one row (an '=' bar), which
    zeroes the aligned IoU without the glyph being wrong; the best-shift numbers
    separate that from real shape differences.
    """
    a, b = placed_pixels(ours, gid_o), placed_pixels(theirs, gid_t)
    mad, iou = _mad_iou(a, b)
    best_mad, best_iou = mad, iou
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx or dy:
                m, i = _mad_iou({(x + dx, y + dy): v for (x, y), v in a.items()}, b)
                best_mad, best_iou = min(best_mad, m), max(best_iou, i)

    def centroid(p):
        total = sum(p.values()) or 1
        return (sum(k[0] * v for k, v in p.items()) / total, sum(k[1] * v for k, v in p.items()) / total)
    (ax, ay), (bx, by) = centroid(a), centroid(b)
    return {'mad': mad, 'iou': iou, 'best_mad': best_mad, 'best_iou': best_iou,
            'shift': math.hypot(ax - bx, ay - by) if a and b else 0.0,
            'ink': (sum(a.values()) / 255, sum(b.values()) / 255),
            'on': min(sum(1 for v in a.values() if v >= 128), sum(1 for v in b.values() if v >= 128))}


def run_width(font: dict, text: str, kerning: bool) -> int:
    ids = [lv_glyph_id(font, ord(c)) for c in text]
    return sum(lv_adv_px(font, g, ids[i + 1] if kerning and i + 1 < len(ids) else 0) for i, g in enumerate(ids))


def test_vs_builtin(report: Report, size: int, ours: dict, builtin: dict, codepoints) -> dict:
    name = f'cc_font_{size}'
    compare = [cp for cp in codepoints if 0x20 <= cp <= 0x7E]
    rows, large, structural = [], [], []
    adv16 = []
    for cp in compare:
        go, gt = lv_glyph_id(ours, cp), lv_glyph_id(builtin, cp)
        if not gt:
            structural.append(f'U+{cp:04X} missing from built-in')
            continue
        do, dt = ours['glyph_dsc'][go], builtin['glyph_dsc'][gt]
        metrics = compare_glyph(ours, go, builtin, gt)
        adv_diff16 = do[1] - dt[1]
        adv_px_diff = lv_adv_px(ours, go) - lv_adv_px(builtin, gt)
        adv16.append(adv_diff16)
        ink_a, ink_b = metrics.pop('ink')
        on_pixels = metrics.pop('on')
        ink_ratio = ink_a / ink_b if ink_b else (1.0 if not ink_a else float('inf'))
        row = {'cp': f'U+{cp:04X}', 'char': chr(cp), 'adv_w': [do[1], dt[1]], 'box': [do[2:4], dt[2:4]],
               'ofs': [do[4:6], dt[4:6]], 'ink_ratio': round(ink_ratio, 3), **{k: round(v, 3) for k, v in metrics.items()}}
        rows.append(row)
        text = (f'{row["cp"]} {chr(cp)!r}: mad {metrics["mad"]:.1f} (best {metrics["best_mad"]:.1f}) '
                f'iou {metrics["iou"]:.2f} (best {metrics["best_iou"]:.2f}) shift {metrics["shift"]:.2f}px '
                f'ink x{ink_ratio:.2f} box {do[2]}x{do[3]}@{do[4]},{do[5]} vs {dt[2]}x{dt[3]}@{dt[4]},{dt[5]} '
                f'adv {do[1]}/{dt[1]}')
        if (abs(adv_px_diff) > STRUCTURAL_ADV_PX or abs(do[2] - dt[2]) > STRUCTURAL_BOX
                or abs(do[3] - dt[3]) > STRUCTURAL_BOX or abs(ink_ratio - 1) > STRUCTURAL_INK
                or metrics['shift'] > STRUCTURAL_SHIFT
                or on_pixels >= STRUCTURAL_IOU_MIN_ON and metrics['best_iou'] < STRUCTURAL_BEST_IOU):
            structural.append(text)
        elif (metrics['best_mad'] > REPORT_BEST_MAD or metrics['best_iou'] < REPORT_BEST_IOU
              or metrics['shift'] > REPORT_SHIFT or abs(ink_ratio - 1) > REPORT_INK or adv_px_diff != 0
              or abs(do[2] - dt[2]) > 1 or abs(do[3] - dt[3]) > 1):
            large.append((metrics['best_mad'], text))
    large = [text for _mad, text in sorted(large, key=lambda item: -item[0])]
    inked = [r for r in rows if r['box'][0] != (0, 0) or r['box'][1] != (0, 0)]
    mean = lambda values: sum(values) / len(values) if values else 0.0  # noqa: E731
    summary = {
        'compared': len(rows),
        'mean_mad': round(mean([r['mad'] for r in inked]), 2),
        'max_mad': round(max((r['mad'] for r in inked), default=0), 2),
        'mean_best_shift_mad': round(mean([r['best_mad'] for r in inked]), 2),
        'mean_iou': round(mean([r['iou'] for r in inked]), 3),
        'min_iou': round(min((r['iou'] for r in inked), default=1), 3),
        'mean_best_shift_iou': round(mean([r['best_iou'] for r in inked]), 3),
        'mean_shift_px': round(mean([r['shift'] for r in inked]), 3),
        'mean_ink_ratio': round(mean([r['ink_ratio'] for r in inked]), 3),
        'adv_w_equal': sum(1 for d in adv16 if d == 0),
        'adv_w_diff_1_16px': sorted(set(adv16) - {0}),
        'adv_px_equal': sum(1 for r in rows if (r['adv_w'][0] + 8) >> 4 == (r['adv_w'][1] + 8) >> 4),
        'box_equal': sum(1 for r in rows if r['box'][0] == r['box'][1] and r['ofs'][0] == r['ofs'][1]),
        'taller_by_overshoot_row': sum(1 for r in rows if r['box'][0][1] == r['box'][1][1] + 1),
        'large_mismatch': large,
        'structural': structural,
        'runs_px': {text: {'cc': run_width(ours, text, False), 'builtin_kerned': run_width(builtin, text, True),
                           'builtin_unkerned': run_width(builtin, text, False)}
                    for text in SAMPLE_RUNS if all(lv_glyph_id(ours, ord(c)) for c in text)},
    }
    report.check(not structural, f'{name}: structurally broken vs lv_font_montserrat_{size}: {structural[:6]}')
    print(f'(b) {name} vs lv_font_montserrat_{size}: {len(rows)} glyphs; mean MAD {summary["mean_mad"]}/255 '
          f'aligned (max {summary["max_mad"]}), {summary["mean_best_shift_mad"]} best +-1px; mean IoU '
          f'{summary["mean_iou"]} aligned, {summary["mean_best_shift_iou"]} best; centroid shift '
          f'{summary["mean_shift_px"]} px; ink ratio {summary["mean_ink_ratio"]}; adv_w equal '
          f'{summary["adv_w_equal"]}/{len(rows)} (px equal {summary["adv_px_equal"]}); box+ofs equal '
          f'{summary["box_equal"]}/{len(rows)}, {summary["taller_by_overshoot_row"]} one row taller; '
          f'{len(large)} large mismatch(es)' + (f', worst {REPORT_LIST}:' if len(large) > REPORT_LIST else ''))
    for line in large[:REPORT_LIST]:
        print(f'      {line}')
    for text, w in summary['runs_px'].items():
        print(f'      run {text!r}: cc {w["cc"]} px, built-in {w["builtin_kerned"]} px kerned '
              f'({w["builtin_unkerned"]} unkerned)')
    return summary


def resolved_run_width(ours: dict, builtin: dict, text: str):
    """LVGL 9.0 lv_font_get_glyph_dsc() over the fallback chain ours -> built-in.

    ours has no kerning; the built-in receives letter_next and kerns only when
    the next letter is also one of its glyphs. None when a letter resolves
    nowhere (LVGL would draw a placeholder box).
    """
    total = 0
    for i, ch in enumerate(text):
        cp, nxt = ord(ch), ord(text[i + 1]) if i + 1 < len(text) else 0
        gid = lv_glyph_id(ours, cp)
        if gid:
            total += lv_adv_px(ours, gid)
            continue
        gid = lv_glyph_id(builtin, cp)
        if not gid:
            return None
        total += lv_adv_px(builtin, gid, lv_glyph_id(builtin, nxt) if nxt else 0)
    return total


def test_hybrid_vs_builtin(report: Report, size: int, ours: dict, builtin: dict, codepoints) -> dict:
    """(b) for a hybrid text font: ASCII via the fallback, accented letters consistent with it."""
    name = f'cc_font_{size}'
    ascii_missing = [cp for cp in gen.ASCII_SET if not lv_glyph_id(builtin, cp)]
    ascii_local = [cp for cp in gen.ASCII_SET if lv_glyph_id(ours, cp)]
    report.check(not ascii_missing, f'{name}: built-in lv_font_montserrat_{size} lacks ASCII {ascii_missing}')
    report.check(not ascii_local, f'{name}: hybrid font stores ASCII {ascii_local} (must come from the fallback)')
    rows, structural, large = [], [], []
    for cp in codepoints:
        decomposed = unicodedata.normalize('NFD', chr(cp))
        base = decomposed[0]
        if len(decomposed) < 2 or not ('A' <= base <= 'Z' or 'a' <= base <= 'z'):
            continue
        go, gb = lv_glyph_id(ours, cp), lv_glyph_id(builtin, ord(base))
        do, db = ours['glyph_dsc'][go], builtin['glyph_dsc'][gb]
        adv_diff = lv_adv_px(ours, go) - lv_adv_px(builtin, gb)
        above = all(unicodedata.combining(m) == 230 for m in decomposed[1:])
        bottom_diff = do[5] - db[5]
        row = {'cp': f'U+{cp:04X}', 'char': chr(cp), 'base': base, 'adv_px_diff': adv_diff,
               'mark_above': above, 'bottom_diff': bottom_diff, 'box': [do[2:4], db[2:4]]}
        rows.append(row)
        text = (f'{row["cp"]} {chr(cp)!r} vs {base!r}: adv {lv_adv_px(ours, go)}/{lv_adv_px(builtin, gb)} px, '
                f'box {do[2]}x{do[3]}@{do[4]},{do[5]} vs {db[2]}x{db[3]}@{db[4]},{db[5]}')
        if abs(adv_diff) > STRUCTURAL_BASE_ADV_PX or (above and abs(bottom_diff) > STRUCTURAL_BASE_BOTTOM_PX):
            structural.append(text)
        elif adv_diff or (above and bottom_diff) or abs(do[2] - db[2]) > 2:
            large.append(text)
    runs = {}
    for text in MIXED_RUNS + SAMPLE_RUNS:
        width = resolved_run_width(ours, builtin, text)
        report.check(width is not None, f'{name}: run {text!r} does not resolve through ours -> built-in')
        runs[text] = width
    report.check(not structural, f'{name}: accented letters inconsistent with the built-in base: {structural[:6]}')
    print(f'(b) {name} hybrid: ASCII {len(gen.ASCII_SET) - len(ascii_missing)}/{len(gen.ASCII_SET)} via '
          f'lv_font_montserrat_{size}, {len(ascii_local)} stored locally; {len(rows)} accented letters vs their '
          f'built-in base: {len(structural)} structural, {len(large)} reported (1 px advance / box-bottom drift):')
    for line in large[:REPORT_LIST]:
        print(f'      {line}')
    for text, width in runs.items():
        print(f'      run {text!r}: {width} px (ours + built-in fallback)')
    return {'hybrid': True, 'ascii_via_fallback': len(gen.ASCII_SET) - len(ascii_missing),
            'ascii_stored_locally': len(ascii_local), 'accented_compared': len(rows),
            'structural': structural, 'reported': large, 'runs_px': runs}


# --------------------------------------------------------------------------
# (c) metrics
# --------------------------------------------------------------------------
def test_metrics(report: Report, size: int, ours: dict, builtin: dict, sfnt: gen.Sfnt, hybrid: bool = False,
                 name: str | None = None) -> dict:
    name = name or f'cc_font_{size}'
    keys = ('line_height', 'base_line', 'underline_position', 'underline_thickness')
    same = all(ours[k] == builtin[k] for k in keys)
    report.check(same, f'{name}: metrics {[ours[k] for k in keys]} != built-in {[builtin[k] for k in keys]}')
    if hybrid:
        report.check(ours['fallback_required'] == (f'LV_FONT_MONTSERRAT_{size}', f'lv_font_montserrat_{size}')
                     and ours['fallback_guard'] is None,
                     f'{name}: hybrid fallback must be an unconditional &lv_font_montserrat_{size} with an '
                     f'#if !LV_FONT_MONTSERRAT_{size} #error guard')
    else:
        report.check(ours['fallback_guard'] == (f'LV_FONT_MONTSERRAT_{size}', f'lv_font_montserrat_{size}'),
                     f'{name}: fallback must be &lv_font_montserrat_{size} guarded by LV_FONT_MONTSERRAT_{size}')
    report.check(ours['public_name'] == name, f'{name}: public symbol is {ours["public_name"]}')
    ascent = ours['line_height'] - ours['base_line']
    top_limit, bottom_limit = ascent, -ours['base_line']
    over_top, below = [], []
    dsc = ours['glyph_dsc']
    cps = {}
    for c in ours['cmaps']:
        span = (range(c['range_length']) if c['unicode_list'] is None else c['unicode_list'])
        for i, off in enumerate(span):
            cps[c['glyph_id_start'] + i] = c['range_start'] + off
    for gid in range(1, len(dsc)):
        _i, _a, w, h, _ox, oy = dsc[gid]
        if not h:
            continue
        if oy + h > top_limit:
            over_top.append((oy + h - top_limit, cps[gid]))
        if oy < bottom_limit:
            below.append((bottom_limit - oy, cps[gid]))
    natural_top = max(d[5] + d[3] for d in dsc[1:] if d[3])
    natural_bottom = min(d[5] for d in dsc[1:] if d[3])
    ext = ours['line_height'] // 4   # lv_label LV_EVENT_REFR_EXT_DRAW_SIZE
    worst = max([p for p, _ in over_top] + [p for p, _ in below] + [0])
    report.check(worst <= ext, f'{name}: glyphs overflow the line box by {worst} px > label ext draw {ext} px')

    def listing(items):
        by_px = {}
        for px, cp in items:
            by_px.setdefault(px, []).append(cp)
        return {f'{px}px': describe(cps_) for px, cps_ in sorted(by_px.items(), reverse=True)}

    css = []
    asc_u = sfnt.typo_ascender if sfnt.fs_selection & 0x80 else sfnt.hhea_ascender
    desc_u = -(sfnt.typo_descender if sfnt.fs_selection & 0x80 else sfnt.hhea_descender)
    for font_size, line in CSS_PAIRS:
        if font_size != size:
            continue
        asc = round(asc_u * font_size / sfnt.units_per_em)
        desc = round(desc_u * font_size / sfnt.units_per_em)
        css_baseline = asc + math.floor((line - (asc + desc)) / 2)
        css.append({'css': f'{font_size}px/{line}px', 'css_baseline_from_top': css_baseline,
                    'lvgl_ascent': ascent, 'label_y_offset': css_baseline - ascent})
    result = {'line_height': ours['line_height'], 'base_line': ours['base_line'], 'hybrid': hybrid,
              'builtin': [builtin['line_height'], builtin['base_line']], 'equal_to_builtin': same,
              'ascent': ascent, 'ink_span': [natural_bottom, natural_top],
              'glyph_derived_line_height': natural_top - natural_bottom, 'glyph_derived_base_line': -natural_bottom,
              'over_top': listing(over_top), 'below_bottom': listing(below), 'label_ext_draw_px': ext, 'css': css}
    print(f'(c) {name}: line_height {ours["line_height"]}/base_line {ours["base_line"]} '
          f'{"==" if same else "!="} built-in {builtin["line_height"]}/{builtin["base_line"]}; ascent {ascent}; '
          f'own ink {natural_bottom}..+{natural_top} (lv_font_conv rule would give '
          f'{natural_top - natural_bottom}/{-natural_bottom}); overflow top {result["over_top"] or "none"}, '
          f'bottom {result["below_bottom"] or "none"} (ext draw {ext}px)')
    for row in css:
        print(f'      CSS {row["css"]}: baseline {row["css_baseline_from_top"]} px below the line-box top; '
              f'LVGL {row["lvgl_ascent"]} -> label y = CSS top {row["label_y_offset"]:+d}')
    return result


def describe(cps):
    return gen.describe_ranges(sorted(cps)) if cps else ''


# --------------------------------------------------------------------------
# (d) flash
# --------------------------------------------------------------------------
def estimate_flash(font: dict) -> dict:
    """ESP32 (ILP32) sizes with LV_FONT_FMT_TXT_LARGE 0."""
    align4 = lambda n: (n + 3) & ~3  # noqa: E731
    parts = {
        'glyph_bitmap': len(font['bitmap']),
        'glyph_dsc': 8 * len(font['glyph_dsc']),
        'cmaps': 20 * len(font['cmaps']),
        'unicode_lists': sum(2 * len(c['unicode_list']) for c in font['cmaps'] if c['unicode_list']),
        'font_dsc': 20,
        'lv_font_t': 36,
    }
    if font.get('kern'):
        k = font['kern']
        parts['kerning'] = len(k['left']) + len(k['right']) + len(k['values']) + 16
    parts['total'] = sum(align4(v) for v in parts.values())
    return parts


def toolchain():
    gcc, gxx = TOOLCHAIN / 'xtensa-esp32s3-elf-gcc.exe', TOOLCHAIN / 'xtensa-esp32s3-elf-g++.exe'
    size, nm = TOOLCHAIN / 'xtensa-esp32s3-elf-size.exe', TOOLCHAIN / 'xtensa-esp32s3-elf-nm.exe'
    if all(p.is_file() for p in (gcc, gxx, size, nm)):
        return {'gcc': gcc, 'gxx': gxx, 'size': size, 'nm': nm}
    return None


def run(command):
    result = subprocess.run([str(c) for c in command], capture_output=True, text=True, encoding='utf-8',
                            errors='replace')
    return result.returncode, (result.stdout + result.stderr).strip()


def c_command(tools, conf_dir: Path, source: Path, extra):
    return ([tools['gcc']] + C_FLAGS + WARN_FLAGS + ['-DLV_CONF_INCLUDE_SIMPLE', '-DLV_LVGL_H_INCLUDE_SIMPLE',
                                                     f'-I{conf_dir}', f'-I{gen.FIRMWARE / "src"}',
                                                     '-isystem', str(LVGL)] + extra + [str(source)])


def rodata_bytes(tools, obj: Path) -> int:
    code, output = run([tools['size'], '-A', obj])
    total = 0
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith(('.rodata', '.data', '.sdata')) and parts[1].isdigit():
            total += int(parts[1])
    return total


def firmware_builtins() -> dict:
    """{size: enabled} for LV_FONT_MONTSERRAT_<size> in the firmware lv_conf.h."""
    text = (gen.FIRMWARE / 'include' / 'lv_conf.h').read_text(encoding='utf-8', errors='replace')
    return {int(m[1]): m[2] == '1' for m in re.finditer(r'^#define\s+LV_FONT_MONTSERRAT_(\d+)\s+([01])\b', text, re.M)}


def test_toolchain(report: Report, specs) -> dict:
    """`specs`: gen.FontSpec list (cc_font_12 ... cc_font_48, cc_font_48t)."""
    sizes = sorted({spec.size for spec in specs})
    tools = toolchain()
    if tools is None:
        print(f'(e) toolchain not found under {TOOLCHAIN}: compile checks and measured sizes skipped')
        return {'skipped': True}
    enabled = firmware_builtins()
    out = {'measured_rodata': {}, 'builtin_rodata': {}, 'firmware_builtins': enabled, 'variants': {}}
    with tempfile.TemporaryDirectory(prefix='cc-fonts-') as temp:
        scratch = Path(temp)
        conf_fw = gen.FIRMWARE / 'include'
        base = (conf_fw / 'lv_conf.h').read_text(encoding='utf-8', errors='replace')

        def variant(name: str, sizes_on=None, all_off=False) -> Path:
            text = base
            if all_off:
                text, n_off = re.subn(r'^(#define\s+LV_FONT_MONTSERRAT_\d+\s+)1\b', r'\g<1>0', text, flags=re.M)
                text, n_default = re.subn(r'^(#define\s+LV_FONT_DEFAULT\s+).*$', r'\g<1>&cc_font_48', text, flags=re.M)
                text, n_custom = re.subn(r'^#define\s+LV_FONT_CUSTOM_DECLARE\b.*$',
                                         '#define LV_FONT_CUSTOM_DECLARE LV_FONT_DECLARE(cc_font_48)', text, flags=re.M)
                report.check(n_off >= 1 and n_default == 1 and n_custom == 1,
                             f'could not derive the no-built-in lv_conf.h variant ({n_off}, {n_default}, {n_custom})')
            for size in sizes_on or ():
                text, n = re.subn(rf'^(#define\s+LV_FONT_MONTSERRAT_{size}\s+)0\b', r'\g<1>1', text, flags=re.M)
            folder = scratch / name
            folder.mkdir()
            (folder / 'lv_conf.h').write_text(text, encoding='utf-8')
            return folder

        conf_off = variant('builtins_off', all_off=True)
        conf_on = variant('builtins_on', sizes_on=sizes)
        allowed = {'lv_font_get_glyph_dsc_fmt_txt', 'lv_font_get_bitmap_fmt_txt'}
        for spec in specs:
            size, fname = spec.size, spec.name
            source = FONT_DIR / f'{fname}.c'
            expect_fb = f'lv_font_montserrat_{size}'
            hybrid = parse_font_c(source)['fallback_required'] is not None
            cases = [('firmware', conf_fw, hybrid or enabled.get(size, False)), ('builtins_off', conf_off, False)]
            if not hybrid:
                cases.append(('builtin_on', conf_on, True))
            results = {}
            for name, conf, expect_ref in cases:
                obj = scratch / f'{fname}_{name}.o'
                code, output = run(c_command(tools, conf, source, ['-c', '-o', str(obj)]))
                if hybrid and name == 'builtins_off':
                    ok = report.check(code != 0 and f'draws ASCII through {expect_fb}' in output,
                                      f'{fname}.c (built-ins off): a hybrid must fail with its #error:\n{output}')
                    results[name] = 'errors as required' if ok else 'NOT rejected'
                    continue
                if not report.check(code == 0 and not output, f'{fname}.c ({name}): C compile failed or '
                                                              f'produced output:\n{output}'):
                    results[name] = 'FAIL'
                    continue
                _c, undefined = run([tools['nm'], '--undefined-only', obj])
                names = sorted(l.split()[-1] for l in undefined.splitlines() if l.strip())
                if name == 'firmware':
                    out['measured_rodata'][fname] = rodata_bytes(tools, obj)
                report.check((expect_fb in names) == expect_ref,
                             f'{fname}.o ({name}) {"must" if expect_ref else "must not"} reference {expect_fb}')
                report.check(set(names) <= allowed | {expect_fb},
                             f'{fname}.o has unexpected undefined symbols {names}')
                results[name] = f'ok, fallback {"-> " + expect_fb if expect_fb in names else "NULL"}'
            out['variants'][fname] = results
            if size in out['builtin_rodata']:
                continue
            builtin = LVGL / 'src' / 'font' / f'lv_font_montserrat_{size}.c'
            obj = scratch / f'builtin_{size}.o'
            code, output = run(c_command(tools, conf_on, builtin, ['-w', '-c', '-o', str(obj)]))
            if code == 0:
                out['builtin_rodata'][size] = rodata_bytes(tools, obj)
        # C++11: the header's declarations must have C linkage.
        probe = scratch / 'probe.cpp'
        probe.write_text('#include "fonts/cc_fonts.h"\n'
                         'static_assert(CC_FONT_48_ASCENT == CC_FONT_48_LINE_HEIGHT - CC_FONT_48_BASE_LINE, "");\n'
                         'static_assert(CC_FONT_48T_ASCENT == CC_FONT_48_ASCENT, "Seek time on the volume baseline");\n'
                         'const lv_font_t * const cc_probe_fonts[] = {'
                         + ', '.join(f'&{spec.name}' for spec in specs) + '};\n'
                         'int cc_probe_height(int i) { return lv_font_get_line_height(cc_probe_fonts[i]); }\n',
                         encoding='utf-8')
        obj = scratch / 'probe.o'
        code, output = run([tools['gxx']] + CXX_FLAGS + WARN_FLAGS + [
            '-DLV_CONF_INCLUDE_SIMPLE', '-DLV_LVGL_H_INCLUDE_SIMPLE', f'-I{gen.FIRMWARE / "include"}',
            f'-I{gen.FIRMWARE / "src"}', '-isystem', str(LVGL), '-c', str(probe), '-o', str(obj)])
        if report.check(code == 0 and 'cc_fonts.h' not in output, f'cc_fonts.h fails as C++11:\n{output}'):
            _c, undefined = run([tools['nm'], '--undefined-only', obj])
            names = {l.split()[-1] for l in undefined.splitlines() if l.strip()}
            report.check({spec.name for spec in specs} <= names,
                         f'cc_fonts.h declarations are not extern "C" (undefined: {sorted(names)})')
    total = sum(out['measured_rodata'].values())
    # Firmware text-font cost = our non-ASCII tables + the (required) built-in for each hybrid size.
    fw_builtins = sum(out['builtin_rodata'].get(s, 0) for s in sizes if enabled.get(s, False))
    print(f'(e) C (gnu99 -Wall -Wextra -Wpedantic, silent) with the firmware lv_conf.h, built-ins off (hybrids '
          f'must #error) and cc_font_48 with its built-in on; C++11 extern "C" header: '
          f'{"PASS" if not report.failures else "see failures"}')
    for fname, results in out['variants'].items():
        print(f'      {fname}: ' + '; '.join(f'{k}: {v}' for k, v in results.items()))
    print(f'      measured .rodata {out["measured_rodata"]} total {total} B; built-ins {out["builtin_rodata"]}; '
          f'firmware lv_conf.h built-ins {sorted(s for s, on in enabled.items() if on)} '
          f'(font total ours + enabled built-ins of these sizes: {total + fw_builtins} B)')
    out['measured_total'] = total
    out['firmware_font_total'] = total + fw_builtins
    return out


def linked_builtins(firmware_map: Path = FIRMWARE_MAP) -> dict:
    if not firmware_map.is_file():
        return {}
    lines = firmware_map.read_text(encoding='utf-8', errors='replace').splitlines()
    state = {}
    pattern = re.compile(r'^\s*(\S+)?\s+0x([0-9a-f]{8,16})\s+0x([0-9a-f]+)\s+\S*lv_font_montserrat_(\d+)\.c\.o\s*$')
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if not m:
            continue
        section = m.group(1) or (lines[i - 1].strip() if i else '')
        if not section.startswith('.rodata'):
            continue   # .debug_* sections carry non-zero offsets even when discarded
        size, address, length = int(m.group(4)), int(m.group(2), 16), int(m.group(3), 16)
        entry = state.setdefault(size, {'linked': False, 'rodata': 0})
        if address:
            entry['linked'] = True
            entry['rodata'] += length
    return {size: (f'linked ({e["rodata"]} B .rodata)' if e['linked'] else 'discarded by --gc-sections')
            for size, e in sorted(state.items())}


# --------------------------------------------------------------------------
# (f) generator behaviour
# --------------------------------------------------------------------------
def test_generator(report: Report) -> dict:
    files, fonts, sfnt = gen.generate(log=lambda *_: None)
    stale = [n for n, t in files.items() if not (FONT_DIR / n).is_file()
             or (FONT_DIR / n).read_text(encoding='ascii') != t]
    report.check(not stale, f'generated files are stale or hand-edited: {stale} (re-run gen_lvgl_font.py)')
    absent = next(cp for cp in (0x0378, 0x4E00, 0x2603) if cp not in sfnt.cmap)
    try:
        gen.build_font(sfnt, gen.FONT_PATH, 14, (0x41, absent), lvgl=None)
        report.fail(f'generator accepted U+{absent:04X}, which the font lacks')
        detected = False
    except gen.GenerationError:
        detected = True
    try:
        gen.build_font(sfnt, gen.FONT_PATH, 14, (0x41, 0xAD), strict=True, lvgl=None)
        report.fail('generator --strict accepted U+00AD')
        strict = False
    except gen.GenerationError:
        strict = True
    # Layouts: the shipped default is hybrid; --with-ascii is the standalone comparison layout.
    hybrid_ok = all(f.hybrid == (f.size in gen.HYBRID_SIZES) for f in fonts) and \
        all(not any(0x20 <= g.cp <= 0x7E for g in f.glyphs) for f in fonts if f.hybrid)
    report.check(hybrid_ok, 'default generation must produce hybrid 12/14/16/22 px fonts without ASCII')
    standalone = gen.build_font(sfnt, gen.FONT_PATH, 12, gen.sizes_for(True)[12], lvgl=None)
    report.check(not standalone.hybrid and len(standalone.glyphs) == len(gen.TEXT_SET)
                 and '#if LV_FONT_MONTSERRAT_12' in gen.emit_font_c(standalone, sfnt),
                 '--with-ascii must build the standalone layout (ASCII baked in, optional fallback)')
    with contextlib.redirect_stderr(io.StringIO()) as refusal:
        refused = gen.main(['--with-ascii']) == 2 and 'pass --out DIR' in refusal.getvalue()
    report.check(refused, '--with-ascii must refuse to overwrite the firmware font directory')
    # The tabular remap is deterministic and refuses a font without the .tf glyphs.
    remap_same = gen.tabular_font_bytes(sfnt) == gen.tabular_font_bytes(gen.Sfnt(gen.FONT_PATH))
    report.check(remap_same, 'tabular_font_bytes is not deterministic')
    saved = dict(gen.TABULAR_GLYPHS)
    try:
        gen.TABULAR_GLYPHS[0x30] = 'zero.nonexistent'
        gen.tabular_font_bytes(sfnt)
        report.fail('tabular_font_bytes accepted a missing .tf glyph')
        remap_refuses = False
    except gen.GenerationError:
        remap_refuses = True
    finally:
        gen.TABULAR_GLYPHS.clear()
        gen.TABULAR_GLYPHS.update(saved)
    print(f'(f) generator: files {"up to date" if not stale else "STALE"}; missing U+{absent:04X} '
          f'{"fails generation" if detected else "NOT detected"}; U+00AD under --strict '
          f'{"fails generation" if strict else "NOT detected"}; U+00AD in cmap: {0xAD in sfnt.cmap}; '
          f'default layout {"hybrid" if hybrid_ok else "NOT hybrid"}; --with-ascii standalone '
          f'{len(standalone.glyphs)} glyphs @12px, {"refuses" if refused else "DOES NOT refuse"} the firmware dir; '
          f'tabular remap {"deterministic" if remap_same else "NOT deterministic"}, '
          f'{"refuses" if remap_refuses else "ACCEPTS"} a missing .tf glyph')
    return {'up_to_date': not stale, 'missing_detected': detected, 'strict_soft_hyphen_fails': strict,
            'soft_hyphen_in_font_cmap': 0xAD in sfnt.cmap, 'default_hybrid': hybrid_ok,
            'with_ascii_glyphs_12': len(standalone.glyphs), 'with_ascii_refuses_firmware_dir': refused,
            'tabular_remap_deterministic': remap_same, 'tabular_remap_refuses_missing_glyph': remap_refuses}


# --------------------------------------------------------------------------
# (t) cc_font_48t: tabular digits for the Seek time
# --------------------------------------------------------------------------
def post_glyph_names(data: bytes) -> list:
    """Glyph names of a post 2.0 table, parsed here independently of the generator's reader."""
    count = int.from_bytes(data[4:6], 'big')
    tables = {data[12 + 16 * i:16 + 16 * i].decode('latin-1'):
              (int.from_bytes(data[20 + 16 * i:24 + 16 * i], 'big'), int.from_bytes(data[24 + 16 * i:28 + 16 * i], 'big'))
              for i in range(count)}
    offset, length = tables['post']
    post = data[offset:offset + length]
    assert post[:4] == b'\x00\x02\x00\x00', 'post table is not format 2.0'
    glyphs = int.from_bytes(post[32:34], 'big')
    index = [int.from_bytes(post[34 + 2 * i:36 + 2 * i], 'big') for i in range(glyphs)]
    names, at = [], 34 + 2 * glyphs
    while at < len(post):
        names.append(post[at + 1:at + 1 + post[at]].decode('latin-1'))
        at += 1 + post[at]
    return [names[i - 258] if i >= 258 else f'#mac{i}' for i in index]


def seek_width(font: dict, text: str, tracking: int = SEEK_TRACKING) -> int:
    """lv_text_get_width of one line: advances plus letter space between glyphs (LVGL 9.0)."""
    ids = [lv_glyph_id(font, ord(c)) for c in text]
    return sum(lv_adv_px(font, g) for g in ids) + tracking * (len(ids) - 1)


def test_tabular(report: Report, ours: dict, proportional: dict, remapped: bytes) -> dict:
    name = 'cc_font_48t'
    original = gen.FONT_PATH.read_bytes()
    names = post_glyph_names(original)
    tf = gen.Sfnt(gen.FONT_PATH, remapped)
    wanted = {0x30 + i: f'{d}.tf' for i, d in enumerate(('zero', 'one', 'two', 'three', 'four', 'five', 'six',
                                                           'seven', 'eight', 'nine'))}
    mapped = {cp: names[tf.cmap[cp]] if cp in tf.cmap else None for cp in wanted}
    report.check(mapped == wanted, f'{name}: the remapped cmap does not point the digits at zero.tf..nine.tf: {mapped}')
    report.check(set(tf.cmap) == set(gen.TABULAR_SET) and tf.cmap.get(0x3A) == gen.Sfnt(gen.FONT_PATH).cmap[0x3A],
                 f'{name}: the remapped cmap must hold exactly 0-9 and the ordinary colon')
    digits = [lv_glyph_id(ours, cp) for cp in range(0x30, 0x3A)]
    colon = lv_glyph_id(ours, 0x3A)
    advances = {ours['glyph_dsc'][g][1] for g in digits}
    report.check(all(digits) and len(advances) == 1, f'{name}: digit advances differ ({sorted(advances)}): not tabular')
    report.check(colon and ours['glyph_dsc'][colon][3] > 0, f"{name}: ':' missing or not drawn")
    report.check(all(ours[k] == proportional[k] for k in ('line_height', 'base_line')),
                 f'{name}: line metrics differ from cc_font_48 (the Seek time must share baseline 116)')
    one = lv_glyph_id(proportional, 0x31)
    report.check(one and proportional['glyph_dsc'][one][1] != ours['glyph_dsc'][digits[1]][1],
                 f"{name}: '1' has the proportional advance: the .tf outlines were not used")
    widths = {n: sorted({seek_width(ours, s) for s in samples}) for n, samples in SEEK_SAMPLES.items()}
    report.check(all(len(w) == 1 for w in widths.values()),
                 f'{name}: m:ss widths vary within a digit count (jitter): {widths}')
    widest = max(w[-1] for w in widths.values())
    report.check(widest <= SEEK_CHORD, f'{name}: 999:59 is {widest} px > the {SEEK_CHORD} px chord')
    # Cell positions: the x of each glyph in every same-length string are identical (0 px jitter).
    cells = {}
    for n, samples in SEEK_SAMPLES.items():
        for text in samples:
            x, pens = 0, []
            for c in text:
                pens.append(x)
                x += lv_adv_px(ours, lv_glyph_id(ours, ord(c))) + SEEK_TRACKING
            cells.setdefault(n, set()).add(tuple(pens))
    report.check(all(len(v) == 1 for v in cells.values()), f'{name}: digit cells move between strings: {cells}')
    digit_px = lv_adv_px(ours, digits[0])
    print(f'(t) {name}: digits -> zero.tf..nine.tf, advance {advances.pop() / 16:.2f} px ({digit_px} px in LVGL) for '
          f"every digit, ':' {lv_adv_px(ours, colon)} px; m:ss at tracking {SEEK_TRACKING}: "
          + ', '.join(f'{SEEK_SAMPLES[n][0]}..{SEEK_SAMPLES[n][-1]} {w[0]} px' for n, w in widths.items())
          + f' (chord {SEEK_CHORD}); cells fixed: {"yes" if all(len(v) == 1 for v in cells.values()) else "NO"}')
    return {'digit_adv_px': digit_px, 'colon_adv_px': lv_adv_px(ours, colon), 'widths_px': widths,
            'glyph_names': {f'U+{cp:04X}': n for cp, n in mapped.items()}}


# --------------------------------------------------------------------------
# (g) icons
# --------------------------------------------------------------------------
def parse_icons_cpp(path: Path) -> dict:
    text = path.read_text(encoding='utf-8')
    data = {(m[1], int(m[2])): bytes(int(v) for v in m[3].split(','))
            for m in re.finditer(r'const uint8_t (\w+?)_(\d+)_data\[\] = \{([0-9,]*)\};', text)}
    dsc = {(m[1], int(m[2])): tuple(int(m[k]) for k in (3, 4, 5, 6))
           for m in re.finditer(r'const lv_image_dsc_t (\w+?)_(\d+) = \{ \{LV_IMAGE_HEADER_MAGIC, LV_COLOR_FORMAT_A8, 0, '
                                r'(\d+), (\d+), (\d+), 0\}, (\d+), \1_\2_data \};', text)}
    tables = {int(m[1]): re.findall(r'\{"(\w+)", &(\w+?)_(\d+)\}', m[2])
              for m in re.finditer(r'const IconEntry kIcons(\d+)\[\] = \{(.*?)\};', text)}
    return {'data': data, 'dsc': dsc, 'tables': tables, 'text': text}


def png_alpha(path: Path):
    with Image.open(path) as image:
        return image.convert('RGBA').getchannel('A')


def lockstep_report() -> dict:
    """Which other lock-step icon tables (9.2 item 5) already list the 21 tokens, and which LCD drawers
    already name the internal masks (dotfill; the r2.2 heartfill of tone `liked`, P5-R29): reported, not
    failed (the LCD and mirror owners' packages)."""
    app = gen.WORKSPACE / 'app' / 'control_center'
    display, mirror = gen.FIRMWARE / 'src' / 'cc_display.cpp', app / 'lcd_preview.py'
    sources = {'cc_frame_parse.cpp kIcons': (gen.FIRMWARE / 'src' / 'cc_frame_parse.cpp', ICON_ENUM),
               'cc_display.cpp ICON_NAMES': (display, ICON_ENUM),
               'presentation.py ICONS': (app / 'presentation.py', ICON_ENUM),
               'cc_display.cpp heartfill': (display, ('heartfill',)),
               'lcd_preview.py dotfill': (mirror, ('dotfill',)),
               'lcd_preview.py heartfill': (mirror, ('heartfill',))}
    out = {}
    for what, (path, wanted) in sources.items():
        text = path.read_text(encoding='utf-8', errors='replace') if path.is_file() else ''
        missing = [token for token in wanted if f'"{token}"' not in text and f"'{token}'" not in text]
        out[what] = 'complete' if not missing else f'missing {", ".join(missing)}'
    return out


def heartfill_problems(heart: bytes, fill: bytes, size: int = 20) -> tuple:
    """[r2.2] heartfill-20 is the heart path filled (fill="white" stroke="none"): every interior pixel of
    the stroked heart (unlit, and joined to the border by no 4-connected unlit path) is >= 250 in heartfill,
    and every exterior pixel is <= 5. Returns (problems, interior pixel count)."""
    if len(heart) != size * size or len(fill) != size * size:
        return [f'heart-{size}/heartfill-{size} missing or not {size} x {size}'], 0
    outside, stack = set(), [(i, j) for i in range(size) for j in (0, size - 1)] + \
        [(j, i) for i in range(size) for j in (0, size - 1)]
    while stack:
        x, y = stack.pop()
        if not (0 <= x < size and 0 <= y < size) or (x, y) in outside or heart[y * size + x]:
            continue
        outside.add((x, y))
        stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    interior = [(x, y) for y in range(size) for x in range(size) if not heart[y * size + x] and (x, y) not in outside]
    problems = []
    if len(interior) < 20:
        problems.append(f'the stroked heart-{size} has only {len(interior)} interior pixels')
    hollow = [p for p in interior if fill[p[1] * size + p[0]] < 250]
    if hollow:
        problems.append(f'heartfill-{size} is not filled over the heart interior at {hollow[:5]}')
    spill = [p for p in sorted(outside) if fill[p[1] * size + p[0]] > 5]
    if spill:
        problems.append(f'heartfill-{size} is lit outside the heart outline at {spill[:5]}')
    if fill == heart:
        problems.append(f'heartfill-{size} equals the stroked heart')
    return problems, len(interior)


def test_icons(report: Report, run_node: bool = True, tools=None) -> dict:
    path = gen.FIRMWARE / 'src' / 'cc_icons.cpp'
    if not report.check(path.is_file(), f'{path} missing (run export_handoff_icons.cjs)'):
        return {}
    icons = parse_icons_cpp(path)
    expected = {(token, size) for token, sizes in ICON_SIZES.items() for size in sizes}
    report.check(set(icons['data']) == expected,
                 f'cc_icons.cpp masks != section 9.1: extra {sorted(set(icons["data"]) - expected)}, '
                 f'missing {sorted(expected - set(icons["data"]))}')
    total = sum(len(v) for v in icons['data'].values())
    report.check(total == ICON_MASK_BYTES, f'cc_icons.cpp masks total {total} B, section 9.1 says {ICON_MASK_BYTES} B')
    bad = [f'{t}-{s}' for (t, s), v in icons['data'].items()
           if len(v) != s * s or icons['dsc'].get((t, s)) != (s, s, s, s * s)]
    report.check(not bad, f'cc_icons.cpp descriptors/data sizes wrong: {bad}')
    table_pairs = {(entry, int(size)) for size_key, rows in icons['tables'].items()
                   for entry, sym, size in rows if sym == entry and int(size) == size_key}
    report.check(table_pairs == expected and sum(len(r) for r in icons['tables'].values()) == len(expected),
                 'cc_icons.cpp per-size tables do not list exactly the masks, each under its own name and size')
    # Desktop parity: each firmware mask is the alpha of the shipped PNG of the same token and size.
    handoff, hires = ICON_ASSETS / 'handoff-icons', ICON_ASSETS / 'lcd-icons'
    differ = [f'{t}-{s}' for (t, s), v in icons['data'].items()
              if not (handoff / f'{t}-{s}.png').is_file() or png_alpha(handoff / f'{t}-{s}.png').tobytes() != v]
    report.check(not differ, f'firmware masks differ from assets/handoff-icons: {differ}')
    missing = [f'{t}-{s}{k}' for t in ICON_DESKTOP for s in (16, 20, 26) for k in ('.png', '.svg', '@2x.png', '@3x.png')
               if not ((hires if '@' in k else handoff) / f'{t}-{s}{k}').is_file()]
    report.check(not missing, f'desktop icon files missing: {missing[:12]}')
    # Snap masks carry their filled half (20 px, rows 8-12: the filled interior vs the other half's interior).
    snaps = {}
    for token, filled, empty in (('snapleft', range(4, 9), range(11, 16)), ('snapright', range(12, 17), range(4, 9))):
        mask = icons['data'].get((token, 20), b'')
        if len(mask) == 400:
            inside = [mask[y * 20 + x] for y in range(8, 13) for x in filled]
            other = [mask[y * 20 + x] for y in range(8, 13) for x in empty]
            snaps[token] = (min(inside), max(other))
            report.check(min(inside) >= 250 and max(other) <= 5, f'{token}-20: the filled half is not filled '
                                                                  f'(min {min(inside)} inside, max {max(other)} outside)')
    dot = icons['data'].get(('dotfill', 16), b'')
    on = [(i % 16, i // 16) for i, v in enumerate(dot) if v >= 128]
    box = (min(x for x, _ in on), min(y for _, y in on), max(x for x, _ in on), max(y for _, y in on)) if on else None
    report.check(box == (5, 5, 10, 10), f'dotfill-16 is not the 6 px disc centred in the 16 px cell (ink box {box})')
    heart_problems, heart_interior = heartfill_problems(icons['data'].get(('heart', 20), b''),
                                                        icons['data'].get(('heartfill', 20), b''))
    for problem in heart_problems:
        report.fail(f'[r2.2] {problem}')
    stroked = icons['data'].get(('heart', 20), b'')         # negative control: the stroked heart is not a heartfill
    report.check(len(stroked) != 400 or heartfill_problems(stroked, stroked)[0],
                 'heartfill check accepts the stroked heart as heartfill')
    # 9.2 item 1: the exporter no longer reads the old design table (legacy masks are pinned by --check).
    exporter = ICON_EXPORTER.read_text(encoding='utf-8')
    report.check('knob-model' not in exporter, 'export_handoff_icons.cjs still names the old knob-model.js '
                                               '(9.2 item 1: it no longer reads it)')
    # CCIcon enum order (cc_presentation.h, append only) = the table order.
    header = (gen.FIRMWARE / 'src' / 'cc_presentation.h').read_text(encoding='utf-8')
    enum = re.search(r'enum CCIcon : uint8_t \{(.*?)\};', header, re.S)
    names = re.findall(r'CC_ICON_(\w+)', re.sub(r'//[^\n]*', '', enum.group(1))) if enum else []
    report.check(names == ['NONE'] + [t.upper() for t in ICON_ENUM], f'CCIcon order {names} != section 9.1')
    manifest = json.loads((handoff / 'icons.json').read_text(encoding='utf-8')) if (handoff / 'icons.json').is_file() else {}
    report.check({k: tuple(v) for k, v in manifest.get('firmwareSizes', {}).items()} ==
                 {k: tuple(sorted(v)) for k, v in ICON_SIZES.items()}, 'icons.json firmwareSizes != section 9.1')
    node = shutil.which('node')
    check = 'skipped'
    if run_node and node:
        code, output = run([node, ICON_EXPORTER, '--check'])
        check = output.splitlines()[-1] if output else f'exit {code}'
        report.check(code == 0, f'export_handoff_icons.cjs --check failed:\n{output[-2000:]}')
    measured = None
    if tools is not None:
        with tempfile.TemporaryDirectory(prefix='cc-icons-') as temp:
            obj = Path(temp) / 'cc_icons.o'
            code, output = run([tools['gxx']] + CXX_FLAGS + WARN_FLAGS + [
                '-ffunction-sections', '-fdata-sections', '-DLV_CONF_INCLUDE_SIMPLE', '-DLV_LVGL_H_INCLUDE_SIMPLE',
                f'-I{gen.FIRMWARE / "include"}', f'-I{gen.FIRMWARE / "src"}', '-isystem', str(LVGL), '-c', str(path),
                '-o', str(obj)])
            if report.check(code == 0 and not output, f'cc_icons.cpp (xtensa g++ -std=gnu++11): {output}'):
                sizes = {}
                for line in run([tools['size'], '-A', obj])[1].splitlines():
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].isdigit() and parts[0].startswith(('.rodata', '.text', '.data',
                                                                                         '.bss', '.literal')):
                        key = parts[0].split('.')[1]
                        sizes[key] = sizes.get(key, 0) + int(parts[1])
                measured = sizes
                report.check(not sizes.get('data') and not sizes.get('bss'), f'cc_icons.o uses RAM: {sizes}')
    lockstep = lockstep_report()
    print(f'(g) icons: {len(icons["data"])} firmware masks ({total} B A8; 20 px {sum(1 for _, s in expected if s == 20)}, '
          f'26 px {sum(1 for _, s in expected if s == 26)}, 16 px {sum(1 for _, s in expected if s == 16)}) == section 9.1; '
          f'desktop PNG parity {"ok" if not differ else "FAIL"}; snap halves {snaps}; dotfill box {box}; '
          f'heartfill {"filled" if not heart_problems else "FAIL"} ({heart_interior} interior px of heart-20); '
          f'CCIcon order {"ok" if names[1:] == [t.upper() for t in ICON_ENUM] else "FAIL"}')
    print(f'      exporter --check: {check}')
    if measured is not None:
        print(f'      ESP32-S3 cc_icons.o (-Os, per-section): {measured} B (no .data/.bss: masks live in flash)')
    print(f'      lock-step tables (other packages): {lockstep}')
    return {'masks': len(icons['data']), 'mask_bytes': total, 'measured': measured, 'exporter_check': check,
            'snap': snaps, 'dotfill_box': box, 'heartfill': {'interior': heart_interior, 'problems': heart_problems},
            'lockstep': lockstep}


MSVC = Path('C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Tools/MSVC/14.44.35207')
WINDOWS_SDK = Path('C:/Program Files (x86)/Windows Kits/10')


def test_msvc(report: Report, specs) -> dict:
    """(m) The harness compiler: cc_icons.cpp (C++14) and every cc_font_*.c (C) compile with MSVC /W4 /WX
    against the harness lv_conf.h (harness), LVGL's own headers as external (not ours)."""
    cl = MSVC / 'bin' / 'Hostx64' / 'x64' / 'cl.exe'
    if not cl.is_file() or not (WINDOWS_SDK / 'Include').is_dir():
        print(f'(m) MSVC not found at {cl}: skipped')
        return {'skipped': True}
    include = sorted((WINDOWS_SDK / 'Include').iterdir(), key=lambda p: p.name)[-1]
    env = {key.upper(): value for key, value in os.environ.items()}
    env['INCLUDE'] = ';'.join(str(p) for p in (MSVC / 'include', include / 'ucrt', include / 'shared', include / 'um'))
    sources = [gen.FIRMWARE / 'src' / 'cc_icons.cpp'] + [FONT_DIR / f'{spec.name}.c' for spec in specs]
    results = {}
    with tempfile.TemporaryDirectory(prefix='cc-msvc-') as temp:
        for source in sources:
            flags = ['/std:c++14', '/EHsc'] if source.suffix == '.cpp' else ['/TC']
            result = subprocess.run([str(cl), '/nologo', '/c', *flags, '/W4', '/WX', '/DLV_CONF_INCLUDE_SIMPLE',
                                     '/DLV_LVGL_H_INCLUDE_SIMPLE', f'/I{ROOT}', f'/I{gen.FIRMWARE / "src"}',
                                     f'/external:I{LVGL}', f'/external:I{LVGL / "src"}', '/external:W0', str(source),
                                     f'/Fo{temp}\\'], cwd=temp, env=env, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace')
            ok = report.check(result.returncode == 0, f'{source.name}: MSVC /W4 /WX failed:\n'
                                                      f'{(result.stdout + result.stderr)[-2000:]}')
            results[source.name] = 'ok' if ok else 'FAIL'
    print(f'(m) MSVC /W4 /WX (harness lv_conf.h): {results}')
    return results


def main(argv=None) -> int:
    # The report prints Latin Extended samples; a cp1252 console or a redirected stdout must not turn that into a
    # UnicodeEncodeError that looks like a font failure.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    parser = argparse.ArgumentParser(description='Validate the generated cc_font_*.c files and cc_icons.cpp.')
    parser.add_argument('--json', type=Path, help='also write the full report as JSON')
    parser.add_argument('--no-toolchain', action='store_true', help='skip the ESP32-S3 compile checks')
    parser.add_argument('--no-node', action='store_true', help='skip export_handoff_icons.cjs --check')
    parser.add_argument('--firmware-map', type=Path, default=FIRMWARE_MAP,
                        help=f'firmware.map of the last link to inspect (default {FIRMWARE_MAP})')
    args = parser.parse_args(argv)
    report = Report()
    sfnt = gen.Sfnt(gen.FONT_PATH)
    results = {'sizes': {}}
    parsed = {}
    for spec in gen.FONT_SPECS:
        size, codepoints, name = spec.size, spec.codepoints, spec.name
        path = FONT_DIR / f'{name}.c'
        if not report.check(path.is_file(), f'{path} missing (run gen_lvgl_font.py)'):
            continue
        ours = parsed[name] = parse_font_c(path)
        builtin = parse_font_c(LVGL / 'src' / 'font' / f'lv_font_montserrat_{size}.c')
        hybrid = size in gen.HYBRID_SIZES and not any(0x20 <= cp <= 0x7E for cp in codepoints)
        if spec.tabular:
            remapped = gen.tabular_font_bytes(sfnt)
            entry = {'a': test_structure_and_decode(report, size, ours, codepoints, gen.Sfnt(gen.FONT_PATH, remapped).cmap,
                                                    name=name, font_data=remapped),
                     't': (test_tabular(report, ours, parsed['cc_font_48'], remapped) if 'cc_font_48' in parsed
                           else report.fail(f'{name}: cc_font_48 missing, tabular checks not run'))}
        else:
            entry = {'a': test_structure_and_decode(report, size, ours, codepoints, sfnt.cmap, name=name),
                     'b': (test_hybrid_vs_builtin(report, size, ours, builtin, codepoints) if hybrid
                           else test_vs_builtin(report, size, ours, builtin, codepoints))}
        entry.update(c=test_metrics(report, size, ours, builtin, sfnt, hybrid=hybrid, name=name),
                     d={'estimate': estimate_flash(ours), 'builtin_estimate': estimate_flash(builtin)})
        results['sizes'][name] = entry
    total = sum(e['d']['estimate']['total'] for e in results['sizes'].values())
    print('(d) flash estimate (B): ' + ', '.join(
        f'{s} {e["d"]["estimate"]["total"]} (bitmap {e["d"]["estimate"]["glyph_bitmap"]}, glyph_dsc '
        f'{e["d"]["estimate"]["glyph_dsc"]})' for s, e in results['sizes'].items()) + f'; total {total}')
    print('    built-in estimate (B): ' + ', '.join(
        f'{s} {e["d"]["builtin_estimate"]["total"]}' for s, e in results['sizes'].items() if not s.endswith('t')))
    results['flash_estimate_total'] = total
    results['firmware_map_builtins'] = linked_builtins(args.firmware_map)
    if results['firmware_map_builtins']:
        print(f'    last firmware link ({args.firmware_map}): {results["firmware_map_builtins"]}')
    results['toolchain'] = {'skipped': True} if args.no_toolchain else test_toolchain(report, list(gen.FONT_SPECS))
    results['generator'] = test_generator(report)
    results['icons'] = test_icons(report, run_node=not args.no_node, tools=None if args.no_toolchain else toolchain())
    results['msvc'] = {'skipped': True} if args.no_toolchain else test_msvc(report, list(gen.FONT_SPECS))
    results['failures'] = report.failures
    if args.json:
        args.json.write_text(json.dumps(results, indent=2, ensure_ascii=True, default=str), encoding='utf-8')
    print(f'font_tests: {"PASS" if not report.failures else f"FAIL ({len(report.failures)})"}')
    return 1 if report.failures else 0


if __name__ == '__main__':
    sys.exit(main())
