"""Offline LVGL 9.0.0 font generator for the Nano_D++ knob (cc5 Stage 6).

Renders the variable ``Montserrat.ttf`` at wght 500 ("Medium") with Pillow's
FreeType binding and writes LVGL 9.0 ``lv_font_fmt_txt`` C sources:

    firmware/src/fonts/cc_font_12.c   hybrid text font, 4 bpp
    firmware/src/fonts/cc_font_14.c   hybrid text font, 4 bpp
    firmware/src/fonts/cc_font_16.c   hybrid text font, 4 bpp
    firmware/src/fonts/cc_font_22.c   hybrid text font, 4 bpp
    firmware/src/fonts/cc_font_48.c   '0123456789%-K' only, 4 bpp (K: presentation 6)
    firmware/src/fonts/cc_font_48t.c  '0123456789:' tabular (Seek time), 4 bpp
    firmware/src/fonts/cc_fonts.h     extern "C" declarations

cc_font_48t (1.0.0-cc5.4, PRESENTATION_V5.md section 10): the Seek time's face. U+0030-0039 are
rendered from Montserrat's tabular outlines ``zero.tf`` ... ``nine.tf`` (every digit the same
advance, so ``m:ss`` never jitters) plus U+003A ':' from its ordinary glyph. The remap is an
in-memory copy of the variable font whose cmap maps exactly those eleven codepoints
(``tabular_font_bytes``: the post table's glyph names find the .tf glyphs, a new format 4 cmap
replaces the old one, every other table is copied byte for byte), loaded by Pillow from memory.
fontTools is not needed (it is not in the companion's venv). Same line_height 52 / base_line 9 as
cc_font_48, so a label at y 73 puts the baseline at 116.

Hybrid text fonts (the default): each cc_font_<N> (12/14/16/22) holds ONLY the
non-ASCII part of the advertised ``glyphs:"latin-ext-a"`` set, U+00A0-017F plus
U+2013 U+2014 U+2018 U+2019 U+201C U+201D U+2022 U+2026 (U+00B7 is inside the
Latin-1 range), and ``.fallback = &lv_font_montserrat_<N>`` is REQUIRED: every
ASCII character (U+0020-007E) misses in cc_font_<N> and is drawn by the crisp,
hinted, kerned built-in exactly as in cc4. The generated file #errors when that
built-in is disabled in lv_conf.h. ``--with-ascii`` restores the previous
standalone layout (ASCII baked in as well, fallback optional); it exists only
for comparison and is not what the firmware ships.

cc_font_48 stays digits-only ('0123456789%-', plus 'K' since presentation 6); its fallback is optional and is
NULL while LV_FONT_MONTSERRAT_48 is 0 (the firmware setting).

Format, matched to LVGL 9.0.0 ``src/font/lv_font_fmt_txt.c``:

* ``bpp = 4``, ``bitmap_format = LV_FONT_FMT_TXT_PLAIN`` (0), no kerning
  (``kern_dsc = NULL``), no cache (9.0's ``lv_font_fmt_txt_dsc_t`` has none).
* Glyph id 0 is reserved (all zero). Glyph ids follow codepoint order.
* Bitmaps: each glyph starts on a byte boundary (``bitmap_index`` is a byte
  offset); inside a glyph the box_w*box_h pixels are packed *continuously*
  row-major, two pixels per byte, first pixel in the HIGH nibble. Rows are not
  byte-aligned: the 4 bpp decoder keeps its nibble counter ``i`` across rows.
  A trailing odd nibble is zero padded. Pixel level q (0..15) decodes to
  opa4_table[q] = 17*q.
* ``adv_w`` in 1/16 px from the *unhinted* advance (LVGL rounds
  ``(adv_w + 8) >> 4`` per glyph), ``box_w``/``box_h`` are the tight 4 bpp ink
  box, ``ofs_x`` is the box's left edge relative to the pen origin, and
  ``ofs_y`` is the box's BOTTOM edge relative to the baseline (up positive),
  because lv_draw_label places a glyph at
  ``y1 = line_top + (line_height - base_line) - box_h - ofs_y``.
* ``line_height``/``base_line``/underline copy the built-in
  ``lv_font_montserrat_<N>`` values so labels keep the same baseline and the
  ``.fallback`` built-in's glyphs line up. ``base_line`` is measured from the
  bottom of the line.
* cmaps: LV_FONT_FMT_TXT_CMAP_FORMAT0_TINY for each contiguous run of at least
  MIN_FORMAT0_RUN codepoints, and SPARSE_TINY (sorted uint16 offsets from
  range_start) for the remaining codepoints. Ranges never overlap: LVGL returns
  from the first cmap whose range contains the letter.
* Hybrid text fonts: ``.fallback = &lv_font_montserrat_<N>`` unconditionally,
  plus ``#if !LV_FONT_MONTSERRAT_<N> #error``. LVGL resolves a letter through
  the fallback chain and passes ``letter_next`` to the built-in, so ASCII pairs
  keep the built-in's kerning; a pair with a non-ASCII neighbour is unkerned.
  Line metrics are identical, so fallback glyphs sit on the same baseline.
* cc_font_48 (and ``--with-ascii`` fonts): ``.fallback`` guarded by
  ``#if LV_FONT_MONTSERRAT_<N>`` (NULL when that built-in is disabled).

Rendering note: Pillow exposes no hinting control, and for this variable font
its FreeType output is effectively unhinted vertically (a 22 px glyph matches an
8x-oversampled, box-filtered render). The lv_font_conv built-ins snap horizontal
stems to whole rows, so these glyphs are softer, often one overshoot row taller
and a few percent lighter at 12-16 px. They do match the host preview, which
renders the same way. font_tests.py reports the differences.

Missing glyphs fail generation. A codepoint is missing when the font's cmap
(parsed from the TTF) does not map it, or when its rendered 4 bpp mask and
advance are identical to .notdef's. The one exception is U+00AD SOFT HYPHEN, a
default-ignorable format character that this Montserrat build does not map: it
is emitted as an empty, zero-advance glyph (invisible, which is what a soft
hyphen at a non-break position must render as; LVGL never breaks at U+00AD).
``--strict`` turns that exception off, so U+00AD then fails generation too.

Offline only: no network, no device, no LVGL build. Output is deterministic
(no timestamps); ``--check`` regenerates in memory and fails if any file on
disk differs.

Usage (from the workspace):
    .venv python harness/gen_lvgl_font.py [--out DIR] [--check] [--strict] [--with-ascii]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import math
import re
import struct
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import PIL
from PIL import Image, ImageDraw, ImageFont, features

ROOT = Path(__file__).resolve().parent            # harness
WORK = ROOT.parent                                # work
WORKSPACE = WORK
FIRMWARE = WORK / 'firmware'
LVGL = FIRMWARE / '.pio' / 'libdeps' / 'nanofoc_d' / 'lvgl'
FONT_PATH = WORKSPACE / 'app' / 'assets' / 'fonts' / 'Montserrat.ttf'
OUT_DIR = FIRMWARE / 'src' / 'fonts'

WEIGHT = 500
WEIGHT_NAME = 'Medium'
BPP = 4

PUNCTUATION = (0x00B7, 0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2026)
ASCII_SET = tuple(range(0x20, 0x7F))
# Hybrid text fonts: the non-ASCII part of the advertised set only (ASCII comes
# from the lv_font_montserrat_<N> fallback).
NON_ASCII_SET = tuple(sorted(set(range(0xA0, 0x180)) | set(PUNCTUATION)))
# The full advertised set (--with-ascii, the pre-hybrid standalone layout).
TEXT_SET = tuple(sorted(set(ASCII_SET) | set(NON_ASCII_SET)))
# Presentation 6 (PRESENTATION_V5.md section 19.2): 'K' joins the 48 px set for the lightsbig unit "K" (Colour
# temperature 3200 K). The renderer draws the unit with the 22 px face like '%' (README r3 section 2.2), so this
# glyph is the 48 px fallback of the unit, never mixed into the digits.
DIGIT_SET = tuple(sorted(ord(c) for c in '0123456789%-K'))
# cc_font_48t: the Seek time m:ss (PRESENTATION_V5 section 10). Digits from the .tf outlines.
TABULAR_SET = tuple(range(0x30, 0x3B))                  # '0'..'9' and ':'
TABULAR_GLYPHS = {0x30 + i: f'{name}.tf' for i, name in enumerate(
    ('zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine'))}
HYBRID_SIZES = (12, 14, 16, 22)


def sizes_for(with_ascii: bool = False) -> dict:
    text = TEXT_SET if with_ascii else NON_ASCII_SET
    return {**{size: text for size in HYBRID_SIZES}, 48: DIGIT_SET}


SIZES = sizes_for(False)


@dataclass(frozen=True)
class FontSpec:
    """One generated face: its C name, pixel size, codepoints and whether the digits are tabular."""
    name: str
    size: int
    codepoints: tuple
    tabular: bool = False

    @property
    def tag(self) -> str:
        """The CC_FONT_<tag>_* macro stem: 12 ... 48, 48T."""
        return self.name[len('cc_font_'):].upper()


def specs_for(with_ascii: bool = False) -> list:
    """Every face in generation order: the SIZES faces, then cc_font_48t."""
    specs = [FontSpec(f'cc_font_{size}', size, cps) for size, cps in sizes_for(with_ascii).items()]
    return specs + [FontSpec('cc_font_48t', 48, TABULAR_SET, tabular=True)]


FONT_SPECS = specs_for(False)

# lv_font_montserrat_<N>.c in LVGL 9.0.0 (lv_font_conv, Montserrat-Medium +
# FontAwesome): (line_height, base_line, underline_position, underline_thickness).
# Cross-checked against the LVGL tree when it is present.
BUILTIN_METRICS = {
    12: (15, 3, -1, 1),
    14: (16, 3, -1, 1),
    16: (18, 3, -1, 1),
    22: (24, 4, -2, 1),
    48: (52, 9, -4, 2),
}

# Codepoints the font may lack that are emitted as empty zero-advance glyphs.
SYNTHESIZE_EMPTY = {0x00AD: 'SOFT HYPHEN is default-ignorable and not mapped by this Montserrat build; '
                            'emitted empty with zero advance (invisible, as at any non-break position)'}

MIN_FORMAT0_RUN = 8          # shorter runs go into a SPARSE_TINY list (2 B/cp vs a 20 B cmap entry)
ADVANCE_OVERSAMPLE = 16      # advances are measured at ppem = upem * 16 (integer px == 1/16 font unit)

# 8-bit coverage -> nearest 4-bit level (LVGL decodes level q as 17*q).
QUANT_LUT = [(a * 15 + 127) // 255 for a in range(256)]

CMAP_FORMAT0_TINY = 'LV_FONT_FMT_TXT_CMAP_FORMAT0_TINY'
CMAP_SPARSE_TINY = 'LV_FONT_FMT_TXT_CMAP_SPARSE_TINY'


class GenerationError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Minimal sfnt reader (cmap, head, hhea, OS/2, fvar) -- no fontTools needed.
# --------------------------------------------------------------------------
class Sfnt:
    def __init__(self, path: Path, data: bytes | None = None):
        """`path` names the font; `data`, when given, is its bytes (an in-memory derivative)."""
        self.path = Path(path)
        self.data = self.path.read_bytes() if data is None else bytes(data)
        self.sha256 = hashlib.sha256(self.data).hexdigest()
        b = self.data
        self.version = b[:4]
        count = struct.unpack('>H', b[4:6])[0]
        self.tables = {}
        for i in range(count):
            tag, _checksum, offset, length = struct.unpack('>4sIII', b[12 + 16 * i:28 + 16 * i])
            self.tables[tag.decode('latin-1')] = (offset, length)
        head = self.table('head')
        self.units_per_em = struct.unpack('>H', head[18:20])[0]
        hhea = self.table('hhea')
        self.hhea_ascender, self.hhea_descender, self.hhea_line_gap = struct.unpack('>hhh', hhea[4:10])
        os2 = self.table('OS/2')
        self.fs_selection = struct.unpack('>H', os2[62:64])[0]
        self.typo_ascender, self.typo_descender, self.typo_line_gap = struct.unpack('>hhh', os2[68:74])
        self.win_ascent, self.win_descent = struct.unpack('>HH', os2[74:78])
        self.cmap = self._read_cmap()
        self.axes, self.instances = self._read_fvar()

    def table(self, tag: str) -> bytes:
        if tag not in self.tables:
            raise GenerationError(f'{self.path.name}: missing {tag!r} table')
        offset, length = self.tables[tag]
        return self.data[offset:offset + length]

    def _read_cmap(self) -> dict:
        t = self.table('cmap')
        count = struct.unpack('>H', t[2:4])[0]
        subtables = {}
        for i in range(count):
            pid, eid, offset = struct.unpack('>HHI', t[4 + 8 * i:12 + 8 * i])
            fmt = struct.unpack('>H', t[offset:offset + 2])[0]
            subtables[(pid, eid)] = (fmt, offset)
        for key in ((3, 10), (0, 4), (0, 6), (3, 1), (0, 3), (0, 2), (0, 1), (0, 0)):
            if key in subtables:
                fmt, offset = subtables[key]
                if fmt == 12:
                    return self._cmap12(t, offset)
                if fmt == 4:
                    return self._cmap4(t, offset)
        raise GenerationError(f'{self.path.name}: no Unicode cmap subtable in format 4 or 12')

    @staticmethod
    def _cmap4(t: bytes, base: int) -> dict:
        seg_x2 = struct.unpack('>H', t[base + 6:base + 8])[0]
        seg = seg_x2 // 2
        ends = struct.unpack(f'>{seg}H', t[base + 14:base + 14 + seg_x2])
        starts = struct.unpack(f'>{seg}H', t[base + 16 + seg_x2:base + 16 + 2 * seg_x2])
        deltas = struct.unpack(f'>{seg}h', t[base + 16 + 2 * seg_x2:base + 16 + 3 * seg_x2])
        range_pos = base + 16 + 3 * seg_x2
        range_offsets = struct.unpack(f'>{seg}H', t[range_pos:range_pos + seg_x2])
        mapping = {}
        for i in range(seg):
            for cp in range(starts[i], ends[i] + 1):
                if cp == 0xFFFF:
                    continue
                if range_offsets[i] == 0:
                    gid = (cp + deltas[i]) & 0xFFFF
                else:
                    at = range_pos + 2 * i + range_offsets[i] + 2 * (cp - starts[i])
                    gid = struct.unpack('>H', t[at:at + 2])[0]
                    if gid:
                        gid = (gid + deltas[i]) & 0xFFFF
                if gid:
                    mapping[cp] = gid
        return mapping

    @staticmethod
    def _cmap12(t: bytes, base: int) -> dict:
        groups = struct.unpack('>I', t[base + 12:base + 16])[0]
        mapping = {}
        for i in range(groups):
            start, end, gid = struct.unpack('>III', t[base + 16 + 12 * i:base + 28 + 12 * i])
            for cp in range(start, end + 1):
                if gid + cp - start:
                    mapping[cp] = gid + cp - start
        return mapping

    def _read_fvar(self):
        if 'fvar' not in self.tables:
            return [], []
        t = self.table('fvar')
        axes_offset, _reserved, axis_count, axis_size, instance_count, instance_size = struct.unpack('>HHHHHH', t[4:16])
        axes = []
        for i in range(axis_count):
            at = axes_offset + i * axis_size
            tag, lo, default, hi = struct.unpack('>4siii', t[at:at + 16])
            axes.append((tag.decode('latin-1'), lo / 65536, default / 65536, hi / 65536))
        instances = []
        at = axes_offset + axis_count * axis_size
        for i in range(instance_count):
            rec = t[at + i * instance_size:at + (i + 1) * instance_size]
            coords = struct.unpack(f'>{axis_count}i', rec[4:4 + 4 * axis_count])
            instances.append(tuple(c / 65536 for c in coords))
        return axes, instances

    def glyph_names(self) -> list:
        """Glyph names from a format 2.0 'post' table (index = glyph id)."""
        post = self.table('post')
        if struct.unpack('>I', post[:4])[0] != 0x00020000:
            raise GenerationError(f'{self.path.name}: post table is not format 2.0 (no glyph names)')
        count = struct.unpack('>H', post[32:34])[0]
        index = struct.unpack(f'>{count}H', post[34:34 + 2 * count])
        extra, at = [], 34 + 2 * count
        while at < len(post):
            length = post[at]
            extra.append(post[at + 1:at + 1 + length].decode('latin-1'))
            at += 1 + length
        return [MAC_GLYPH_NAMES.get(i, f'.mac{i}') if i < 258 else extra[i - 258] for i in index]


# The standard Macintosh names a post 2.0 table indexes below 258 that this generator needs.
MAC_GLYPH_NAMES = {0: '.notdef', 3: 'space', 19: 'zero', 20: 'one', 21: 'two', 22: 'three', 23: 'four', 24: 'five',
                   25: 'six', 26: 'seven', 27: 'eight', 28: 'nine', 29: 'colon'}


def _checksum(data: bytes) -> int:
    padded = data + b'\0' * (-len(data) % 4)
    return sum(struct.unpack(f'>{len(padded) // 4}I', padded)) & 0xFFFFFFFF


def _cmap_format4(mapping: dict) -> bytes:
    """A (3,1)/(0,3) 'cmap' table with one format 4 subtable for `mapping` {codepoint: glyph id}."""
    segments = []                       # [start, end, first gid] runs with consecutive glyph ids
    for cp in sorted(mapping):
        if segments and cp == segments[-1][1] + 1 and mapping[cp] == segments[-1][2] + cp - segments[-1][0]:
            segments[-1][1] = cp
        else:
            segments.append([cp, cp, mapping[cp]])
    segments.append([0xFFFF, 0xFFFF, None])
    count = len(segments)
    search = 2 * (1 << (count.bit_length() - 1))
    ends = [s[1] for s in segments]
    starts = [s[0] for s in segments]
    deltas = [((s[2] - s[0]) & 0xFFFF) if s[2] is not None else 1 for s in segments]
    body = struct.pack(f'>{count}H', *ends) + b'\0\0' + struct.pack(f'>{count}H', *starts)
    body += struct.pack(f'>{count}H', *deltas) + struct.pack(f'>{count}H', *([0] * count))
    sub = struct.pack('>HHHHHHH', 4, 14 + len(body), 0, 2 * count, search, search.bit_length() - 2,
                      2 * count - search) + body
    return struct.pack('>HHHHIHHI', 0, 2, 0, 3, 20, 3, 1, 20) + sub


def tabular_font_bytes(sfnt: 'Sfnt') -> bytes:
    """The variable font with a cmap of exactly TABULAR_SET: '0'..'9' -> zero.tf..nine.tf, ':' -> colon.

    Every other table is copied byte for byte (glyf, gvar, HVAR, ... so wght 500 renders the same
    outlines); the table directory, checksums and head.checkSumAdjustment are rebuilt.
    """
    names = sfnt.glyph_names()
    gid_of = {name: gid for gid, name in enumerate(names)}
    mapping = {}
    for cp, name in TABULAR_GLYPHS.items():
        if name not in gid_of:
            raise GenerationError(f'{sfnt.path.name}: no glyph named {name!r} (tabular digits)')
        mapping[cp] = gid_of[name]
    if 0x3A not in sfnt.cmap:
        raise GenerationError(f'{sfnt.path.name}: U+003A is not mapped')
    mapping[0x3A] = sfnt.cmap[0x3A]
    tables = {tag: sfnt.table(tag) for tag in sfnt.tables}
    tables['cmap'] = _cmap_format4(mapping)
    head = bytearray(tables['head'])
    head[8:12] = b'\0\0\0\0'
    tables['head'] = bytes(head)
    tags = sorted(tables)
    count = len(tags)
    search = 16 * (1 << (count.bit_length() - 1))
    directory = sfnt.version + struct.pack('>HHHH', count, search, (search // 16).bit_length() - 1, 16 * count - search)
    offset = 12 + 16 * count
    records, blobs = b'', b''
    for tag in tags:
        data = tables[tag]
        records += struct.pack('>4sIII', tag.encode('latin-1'), _checksum(data), offset, len(data))
        padded = data + b'\0' * (-len(data) % 4)
        blobs += padded
        offset += len(padded)
    font = bytearray(directory + records + blobs)
    head_at = struct.unpack('>I', records[16 * tags.index('head') + 8:16 * tags.index('head') + 12])[0]
    font[head_at + 8:head_at + 12] = struct.pack('>I', (0xB1B0AFBA - _checksum(bytes(font))) & 0xFFFFFFFF)
    return bytes(font)


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------
def load_face(font_path, size: int) -> ImageFont.FreeTypeFont:
    """The face every glyph is rendered with: BASIC layout (no shaping), wght 500.

    `font_path` is a path, or the bytes of an in-memory font (tabular_font_bytes)."""
    source = io.BytesIO(font_path) if isinstance(font_path, (bytes, bytearray)) else str(font_path)
    face = ImageFont.truetype(source, size, layout_engine=ImageFont.Layout.BASIC)
    face.set_variation_by_axes([WEIGHT])
    return face


def verify_variation(sfnt: Sfnt, font_path: Path) -> str:
    """Prove that axis coordinate 500 is the 'Medium' named instance and is applied."""
    face = ImageFont.truetype(str(font_path), 22, layout_engine=ImageFont.Layout.BASIC)
    axes = face.get_variation_axes()
    if len(axes) != 1 or axes[0]['name'] != b'Weight' or not axes[0]['minimum'] <= WEIGHT <= axes[0]['maximum']:
        raise GenerationError(f'unexpected variation axes {axes}')
    if len(sfnt.axes) != 1 or sfnt.axes[0][0] != 'wght':
        raise GenerationError(f'fvar axes {sfnt.axes}: expected exactly one wght axis')
    names = face.get_variation_names()
    wanted = WEIGHT_NAME.encode()
    if wanted not in names:
        raise GenerationError(f'no named instance {WEIGHT_NAME!r} in {names}')
    index = names.index(wanted)
    if sfnt.instances[index] != (float(WEIGHT),):
        raise GenerationError(f'named instance {WEIGHT_NAME!r} is at {sfnt.instances[index]}, not wght={WEIGHT}')

    def probe(setter) -> bytes:
        f = ImageFont.truetype(str(font_path), 22, layout_engine=ImageFont.Layout.BASIC)
        setter(f)
        im = Image.new('L', (520, 60), 0)
        ImageDraw.Draw(im).text((4, 44), 'Hamburgefonstiv 0123456789%', font=f, fill=255, anchor='ls')
        return im.tobytes()

    by_axes = probe(lambda f: f.set_variation_by_axes([WEIGHT]))
    by_name = probe(lambda f: f.set_variation_by_name(WEIGHT_NAME))
    regular = probe(lambda f: f.set_variation_by_axes([400]))
    if by_axes != by_name:
        raise GenerationError('set_variation_by_axes([500]) and set_variation_by_name("Medium") render differently')
    if by_axes == regular:
        raise GenerationError('variation is not applied (wght 500 renders like wght 400)')
    lo, default, hi = sfnt.axes[0][1:]
    return f'wght axis {lo:g}..{hi:g} (default {default:g}); instance {WEIGHT_NAME!r} = wght {WEIGHT}; applied'


def render_levels(face: ImageFont.FreeTypeFont, char: str, size: int):
    """Render one character at the 'ls' anchor; return (box_w, box_h, ofs_x, ofs_y, levels).

    ``levels`` holds box_w*box_h 4-bit levels (0..15), row-major. The box is the
    tight box of non-zero *quantized* pixels. ofs_y is the box bottom relative
    to the baseline, up positive (LVGL convention).
    """
    width = height = 6 * size
    origin_x, origin_y = 2 * size, 4 * size
    im = Image.new('L', (width, height), 0)
    ImageDraw.Draw(im).text((origin_x, origin_y), char, font=face, fill=255, anchor='ls')
    raw = im.getbbox()
    if raw and (raw[0] == 0 or raw[1] == 0 or raw[2] == width or raw[3] == height):
        raise GenerationError(f'U+{ord(char):04X} at {size}px touches the render canvas edge')
    q = im.point(QUANT_LUT)
    box = q.getbbox()
    if box is None:
        return 0, 0, 0, 0, b''
    x0, y0, x1, y1 = box
    return x1 - x0, y1 - y0, x0 - origin_x, origin_y - y1, q.crop(box).tobytes()


def pack_4bpp(levels: bytes) -> bytes:
    """Continuous 4 bpp packing: first pixel in the high nibble, rows not aligned."""
    out = bytearray()
    for i in range(0, len(levels), 2):
        hi = levels[i]
        lo = levels[i + 1] if i + 1 < len(levels) else 0
        out.append((hi << 4) | lo)
    return bytes(out)


# --------------------------------------------------------------------------
# Font assembly
# --------------------------------------------------------------------------
@dataclass
class Glyph:
    cp: int
    adv_w: int
    box_w: int
    box_h: int
    ofs_x: int
    ofs_y: int
    levels: bytes
    bitmap_index: int = 0
    synthesized: str | None = None


@dataclass
class Cmap:
    range_start: int
    range_length: int
    glyph_id_start: int
    type: str
    unicode_list: list = field(default_factory=list)


@dataclass
class BuiltFont:
    size: int
    name: str
    glyphs: list
    cmaps: list
    bitmap: bytes
    line_height: int
    base_line: int
    underline_position: int
    underline_thickness: int
    natural_top: int
    natural_bottom: int
    synthesized: dict
    notdef_codepoint: int
    # True for a hybrid text font: no ASCII inside, the built-in fallback is required.
    hybrid: bool = False
    # True for cc_font_48t: digits from the .tf outlines (tabular_font_bytes).
    tabular: bool = False

    @property
    def tag(self) -> str:
        return self.name[len('cc_font_'):].upper()


def build_cmaps(codepoints) -> list:
    cps = sorted(set(codepoints))
    runs = []
    for cp in cps:
        if runs and cp == runs[-1][-1] + 1:
            runs[-1].append(cp)
        else:
            runs.append([cp])
    dense = [r for r in runs if len(r) >= MIN_FORMAT0_RUN]
    loose = sorted(cp for r in runs if len(r) < MIN_FORMAT0_RUN for cp in r)
    groups = []
    for cp in loose:
        if groups:
            first = groups[-1][0]
            crosses = any(first < r[0] and r[-1] < cp for r in dense)
            if not crosses and cp - first <= 0xFFFF:
                groups[-1].append(cp)
                continue
        groups.append([cp])
    entries = [(r[0], len(r), CMAP_FORMAT0_TINY, []) for r in dense]
    entries += [(g[0], g[-1] - g[0] + 1, CMAP_SPARSE_TINY, [cp - g[0] for cp in g]) for g in groups]
    entries.sort()
    cmaps, next_id, last_end = [], 1, -1
    for start, length, kind, offsets in entries:
        if start <= last_end:
            raise GenerationError('internal: overlapping cmap ranges')
        last_end = start + length - 1
        count = length if kind == CMAP_FORMAT0_TINY else len(offsets)
        cmaps.append(Cmap(start, length, next_id, kind, offsets))
        next_id += count
    return cmaps


def cmap_codepoints(cmap: Cmap) -> list:
    if cmap.type == CMAP_FORMAT0_TINY:
        return list(range(cmap.range_start, cmap.range_start + cmap.range_length))
    return [cmap.range_start + o for o in cmap.unicode_list]


def parse_builtin_metrics(lvgl: Path, size: int):
    path = lvgl / 'src' / 'font' / f'lv_font_montserrat_{size}.c'
    if not path.is_file():
        return None
    text = path.read_text(encoding='utf-8', errors='replace')
    values = []
    for key in ('line_height', 'base_line', 'underline_position', 'underline_thickness'):
        m = re.search(r'\.' + key + r'\s*=\s*(-?\d+)', text)
        values.append(int(m.group(1)) if m else None)
    return tuple(values)


def build_font(sfnt: Sfnt, font_path: Path, size: int, codepoints, strict: bool = False,
               lvgl: Path | None = LVGL, name: str | None = None, tabular: bool = False) -> BuiltFont:
    """Render one face. With `tabular`, `sfnt`/`font_path` are replaced by the tabular remap of
    `sfnt` (tabular_font_bytes) and the glyphs come from those outlines."""
    if tabular:
        data = tabular_font_bytes(sfnt)
        sfnt, font_path = Sfnt(sfnt.path, data), data
    face = load_face(font_path, size)
    big = load_face(font_path, sfnt.units_per_em * ADVANCE_OVERSAMPLE)

    # .notdef signature from a codepoint the font does not map.
    notdef_cp = next(cp for cp in range(0xE000, 0xF900) if cp not in sfnt.cmap)
    notdef_sig = (render_levels(face, chr(notdef_cp), size), face.getlength(chr(notdef_cp)))
    if notdef_sig[0][0] == 0:
        raise GenerationError('.notdef renders empty; mask comparison cannot detect missing glyphs')

    glyph_by_cp, missing, synthesized = {}, [], {}
    for cp in codepoints:
        ch = chr(cp)
        rendered = render_levels(face, ch, size)
        mapped = cp in sfnt.cmap
        looks_notdef = (rendered, face.getlength(ch)) == notdef_sig
        if not mapped or looks_notdef:
            if cp in SYNTHESIZE_EMPTY and not strict:
                synthesized[cp] = SYNTHESIZE_EMPTY[cp]
                glyph_by_cp[cp] = Glyph(cp, 0, 0, 0, 0, 0, b'', synthesized=SYNTHESIZE_EMPTY[cp])
                continue
            why = 'not in cmap' if not mapped else 'renders as .notdef'
            missing.append(f'U+{cp:04X} {unicodedata.name(ch, "?")} ({why})')
            continue
        units = big.getlength(ch) / ADVANCE_OVERSAMPLE
        adv_w = math.floor(units * size * 16 / sfnt.units_per_em + 0.5)
        box_w, box_h, ofs_x, ofs_y, levels = rendered
        glyph_by_cp[cp] = Glyph(cp, adv_w, box_w, box_h, ofs_x, ofs_y, levels)
    if missing:
        raise GenerationError(f'{len(missing)} requested codepoint(s) missing from {sfnt.path.name} at {size}px:\n  '
                              + '\n  '.join(missing))

    cmaps = build_cmaps(codepoints)
    glyphs = [glyph_by_cp[cp] for cmap in cmaps for cp in cmap_codepoints(cmap)]
    bitmap = bytearray()
    for g in glyphs:
        g.bitmap_index = len(bitmap)
        bitmap += pack_4bpp(g.levels)
        # lv_font_fmt_txt_glyph_dsc_t with LV_FONT_FMT_TXT_LARGE == 0
        if not (g.bitmap_index < (1 << 20) and 0 <= g.adv_w < (1 << 12) and g.box_w < 256 and g.box_h < 256
                and -128 <= g.ofs_x < 128 and -128 <= g.ofs_y < 128):
            raise GenerationError(f'U+{g.cp:04X} does not fit lv_font_fmt_txt_glyph_dsc_t (LV_FONT_FMT_TXT_LARGE 0)')

    metrics = BUILTIN_METRICS[size]
    if lvgl is not None:
        parsed = parse_builtin_metrics(lvgl, size)
        if parsed is not None and parsed != metrics:
            raise GenerationError(f'lv_font_montserrat_{size}.c metrics {parsed} != BUILTIN_METRICS {metrics}')
    inked = [g for g in glyphs if g.box_h]
    natural_top = max(g.ofs_y + g.box_h for g in inked)
    natural_bottom = min(g.ofs_y for g in inked)
    hybrid = size in HYBRID_SIZES and not set(ASCII_SET) & set(codepoints) and not tabular
    return BuiltFont(size, name or f'cc_font_{size}', glyphs, cmaps, bytes(bitmap), *metrics,
                     natural_top, natural_bottom, synthesized, notdef_cp, hybrid, tabular)


# --------------------------------------------------------------------------
# C emission
# --------------------------------------------------------------------------
def _cp_comment(cp: int) -> str:
    name = unicodedata.name(chr(cp), '')
    if not name:
        name = 'CONTROL' if unicodedata.category(chr(cp)) == 'Cc' else 'UNNAMED'
    return f'U+{cp:04X} {name}'


def _hex_lines(data: bytes, per_line: int = 16, indent: str = '    ') -> list:
    return [indent + ', '.join(f'0x{b:02x}' for b in data[i:i + per_line]) + ','
            for i in range(0, len(data), per_line)]


def describe_ranges(codepoints) -> str:
    cps = sorted(codepoints)
    parts, start, prev = [], cps[0], cps[0]
    for cp in cps[1:] + [None]:
        if cp is not None and cp == prev + 1:
            prev = cp
            continue
        parts.append(f'U+{start:04X}' if start == prev else f'U+{start:04X}-{prev:04X}')
        if cp is not None:
            start = prev = cp
    return ', '.join(parts)


def provenance(sfnt: Sfnt) -> list:
    return [
        f' * Source: {sfnt.path.name} (variable; wght {WEIGHT} = named instance "{WEIGHT_NAME}")',
        f' *         sha256 {sfnt.sha256[:16]}..., units_per_em {sfnt.units_per_em}',
        f' * Renderer: Pillow {PIL.__version__} / FreeType {features.version("freetype2")}, '
        f'BASIC layout, anchor "ls", Pillow\'s own load flags',
        ' * Generated by harness/gen_lvgl_font.py -- DO NOT EDIT; re-run the generator.',
    ]


def emit_font_c(font: BuiltFont, sfnt: Sfnt) -> str:
    n = font.size
    cps = [g.cp for g in font.glyphs]
    lines = [
        '/*******************************************************************************',
        f' * Size: {n} px',
        f' * Bpp: {BPP}',
        f' * Glyphs: {len(font.glyphs)} (+ reserved id 0): {describe_ranges(cps)}',
        *provenance(sfnt),
        ' * Format: LVGL 9.0 lv_font_fmt_txt, plain (uncompressed) bitmaps, no kerning.',
        ' *   4 bpp, byte-aligned glyph starts, continuous rows, first pixel in the high nibble.',
        ' *   adv_w in 1/16 px (unhinted advance); ofs_y = box bottom relative to the baseline.',
        f' * Metrics: line_height {font.line_height}, base_line {font.base_line} (from the bottom) -- copied from',
        f' *   lv_font_montserrat_{n}; own ink spans {font.natural_bottom}..+{font.natural_top} px around the baseline.',
    ]
    for cp, why in font.synthesized.items():
        lines.append(f' * Synthesized: U+{cp:04X} -- {why}.')
    if font.tabular:
        lines += [
            ' * Tabular: U+0030-0039 are the zero.tf..nine.tf outlines (one advance for every digit), U+003A',
            ' *   the ordinary colon: an in-memory cmap remap of the same font (tabular_font_bytes). Seek m:ss.',
        ]
    if font.hybrid:
        lines += [
            ' * Hybrid: no ASCII here. U+0020-007E miss in this font and are drawn by the',
            f' *   REQUIRED fallback lv_font_montserrat_{n} (hinted, kerned; same line metrics).',
        ]
    lines += [
        ' ******************************************************************************/',
        '',
        '#include "lvgl.h"',
        '',
        '#if LVGL_VERSION_MAJOR != 9',
        '#error "cc_font_*.c are generated for the LVGL 9 lv_font_fmt_txt layout"',
        '#endif',
        '',
    ]
    if font.hybrid:
        lines += [
            f'#if !LV_FONT_MONTSERRAT_{n}',
            f'#error "cc_font_{n} draws ASCII through lv_font_montserrat_{n}: set LV_FONT_MONTSERRAT_{n} 1 in lv_conf.h"',
            '#endif',
            '',
        ]
    lines += [
        '/*-----------------',
        ' *    BITMAPS',
        ' *----------------*/',
        '',
        '/*Store the image of the glyphs*/',
        'static LV_ATTRIBUTE_LARGE_CONST const uint8_t glyph_bitmap[] = {',
    ]
    first = True
    for g in font.glyphs:
        if not first:
            lines.append('')
        first = False
        lines.append(f'    /* {_cp_comment(g.cp)} */')
        lines += _hex_lines(pack_4bpp(g.levels))
    if not font.bitmap:
        lines.append('    0x00,')
    lines += [
        '};',
        '',
        '/*---------------------',
        ' *  GLYPH DESCRIPTION',
        ' *--------------------*/',
        '',
        'static const lv_font_fmt_txt_glyph_dsc_t glyph_dsc[] = {',
        '    {.bitmap_index = 0, .adv_w = 0, .box_w = 0, .box_h = 0, .ofs_x = 0, .ofs_y = 0} /* id = 0 reserved */,',
    ]
    for gid, g in enumerate(font.glyphs, start=1):
        lines.append(f'    {{.bitmap_index = {g.bitmap_index}, .adv_w = {g.adv_w}, .box_w = {g.box_w}, '
                     f'.box_h = {g.box_h}, .ofs_x = {g.ofs_x}, .ofs_y = {g.ofs_y}}}, /* id = {gid} U+{g.cp:04X} */')
    lines[-1] = lines[-1].replace('}, /* id', '} /* id', 1)
    lines += [
        '};',
        '',
        '/*---------------------',
        ' *  CHARACTER MAPPING',
        ' *--------------------*/',
        '',
    ]
    for index, cmap in enumerate(font.cmaps):
        if cmap.type == CMAP_SPARSE_TINY:
            lines.append(f'static const uint16_t unicode_list_{index}[] = {{')
            lines += ['    ' + ', '.join(f'0x{o:x}' for o in cmap.unicode_list[i:i + 8]) + ','
                      for i in range(0, len(cmap.unicode_list), 8)]
            lines += ['};', '']
    lines += ['/*Collect the unicode lists and glyph_id offsets*/',
              'static const lv_font_fmt_txt_cmap_t cmaps[] = {']
    for index, cmap in enumerate(font.cmaps):
        sparse = cmap.type == CMAP_SPARSE_TINY
        lines += [
            '    {',
            f'        .range_start = {cmap.range_start}, .range_length = {cmap.range_length}, '
            f'.glyph_id_start = {cmap.glyph_id_start},',
            f'        .unicode_list = {f"unicode_list_{index}" if sparse else "NULL"}, .glyph_id_ofs_list = NULL, '
            f'.list_length = {len(cmap.unicode_list) if sparse else 0}, .type = {cmap.type}',
            '    }' + (',' if index + 1 < len(font.cmaps) else ''),
        ]
    lines += [
        '};',
        '',
        '/*--------------------',
        ' *  ALL CUSTOM DATA',
        ' *--------------------*/',
        '',
        '/*Store all the custom data of the font*/',
        'static const lv_font_fmt_txt_dsc_t font_dsc = {',
        '    .glyph_bitmap = glyph_bitmap,',
        '    .glyph_dsc = glyph_dsc,',
        '    .cmaps = cmaps,',
        '    .kern_dsc = NULL,',
        '    .kern_scale = 0,',
        f'    .cmap_num = {len(font.cmaps)},',
        f'    .bpp = {BPP},',
        '    .kern_classes = 0,',
        '    .bitmap_format = 0, /*LV_FONT_FMT_TXT_PLAIN*/',
        '};',
        '',
        '/*-----------------',
        ' *  PUBLIC FONT',
        ' *----------------*/',
        '',
        '/*Initialize a public general font descriptor*/',
        f'const lv_font_t {font.name} = {{',
        '    .get_glyph_dsc = lv_font_get_glyph_dsc_fmt_txt,    /*Function pointer to get glyph\'s data*/',
        '    .get_glyph_bitmap = lv_font_get_bitmap_fmt_txt,    /*Function pointer to get glyph\'s bitmap*/',
        f'    .line_height = {font.line_height},          /*Same as lv_font_montserrat_{n}*/',
        f'    .base_line = {font.base_line},             /*Baseline measured from the bottom of the line*/',
        '    .subpx = LV_FONT_SUBPX_NONE,',
        f'    .underline_position = {font.underline_position},',
        f'    .underline_thickness = {font.underline_thickness},',
        '    .dsc = &font_dsc,          /*The custom font data. Will be accessed by `get_glyph_bitmap/dsc` */',
    ]
    if font.hybrid:
        lines.append(f'    .fallback = &lv_font_montserrat_{n},   /*Required: ASCII lives in the built-in*/')
    else:
        lines += [
            f'#if LV_FONT_MONTSERRAT_{n}',
            f'    .fallback = &lv_font_montserrat_{n},',
            '#else',
            '    .fallback = NULL,',
            '#endif',
        ]
    lines += [
        '    .user_data = NULL,',
        '};',
        '',
    ]
    return '\n'.join(lines)


def emit_header(fonts: list, sfnt: Sfnt) -> str:
    lines = [
        '/*******************************************************************************',
        ' * Nano_D++ knob fonts: Montserrat Medium, LVGL 9.0 lv_font_fmt_txt, 4 bpp.',
        *provenance(sfnt),
        ' *',
    ]
    for font in fonts:
        lines.append(f' * {font.name}: {len(font.glyphs)} glyphs, {describe_ranges([g.cp for g in font.glyphs])}'
                     + (f' (+ U+0020-007E via lv_font_montserrat_{font.size})' if font.hybrid else '')
                     + (' (tabular digits: zero.tf..nine.tf)' if font.tabular else ''))
    hybrids = [font for font in fonts if font.hybrid]
    lines.append(' *')
    if hybrids:
        lines += [
            ' * Hybrid text fonts (' + ', '.join(font.name for font in hybrids) + '): ASCII is NOT',
            ' * stored here; it resolves through the required .fallback lv_font_montserrat_<N>',
            ' * (the cc4 glyphs and kerning), so LV_FONT_MONTSERRAT_<N> must stay 1 for them.',
        ]
    lines += [
        ' * Other glyphs outside a font fall back to lv_font_montserrat_<N> only when that',
        ' * built-in is enabled in lv_conf.h. Each font keeps its built-in\'s line_height',
        ' * and base_line, so a label\'s baseline sits CC_FONT_<N>_ASCENT px below its top.',
        ' ******************************************************************************/',
        '',
        '#ifndef CC_FONTS_H',
        '#define CC_FONTS_H',
        '',
        '#include "lvgl.h"',
        '',
        '#ifdef __cplusplus',
        'extern "C" {',
        '#endif',
        '',
    ]
    lines += [f'LV_FONT_DECLARE({font.name})' for font in fonts]
    lines += ['', '/* line_height, base_line (from the bottom) and ascent = line_height - base_line */']
    for font in fonts:
        n = font.tag
        lines += [
            f'#define CC_FONT_{n}_LINE_HEIGHT {font.line_height}',
            f'#define CC_FONT_{n}_BASE_LINE {font.base_line}',
            f'#define CC_FONT_{n}_ASCENT {font.line_height - font.base_line}',
        ]
    lines += [
        '',
        '#ifdef __cplusplus',
        '} /*extern "C"*/',
        '#endif',
        '',
        '#endif /*CC_FONTS_H*/',
        '',
    ]
    return '\n'.join(lines)


def generate(font_path: Path = FONT_PATH, strict: bool = False, lvgl: Path | None = LVGL, log=print,
             with_ascii: bool = False):
    """Build every font; return ({filename: text}, [BuiltFont], Sfnt).

    Default: hybrid text fonts (non-ASCII only, built-in fallback required).
    with_ascii: the pre-hybrid standalone layout (comparison only).
    """
    sfnt = Sfnt(font_path)
    log(f'font: {font_path} ({verify_variation(sfnt, font_path)})')
    fonts = []
    for spec in specs_for(with_ascii):
        font = build_font(sfnt, font_path, spec.size, spec.codepoints, strict=strict, lvgl=lvgl, name=spec.name,
                          tabular=spec.tabular)
        fonts.append(font)
        kinds = ', '.join(f'{c.type.rsplit("_", 2)[-2]}_{c.type.rsplit("_", 1)[-1]} U+{c.range_start:04X}+{c.range_length}'
                          for c in font.cmaps)
        log(f'{font.name}: {len(font.glyphs)} glyphs, bitmap {len(font.bitmap)} B, cmaps [{kinds}], '
            f'line_height {font.line_height}/base_line {font.base_line}, ink {font.natural_bottom}..+{font.natural_top}')
        for cp, why in font.synthesized.items():
            log(f'  WARNING {font.name}: U+{cp:04X} synthesized: {why}')
    files = {f'{font.name}.c': emit_font_c(font, sfnt) for font in fonts}
    files['cc_fonts.h'] = emit_header(fonts, sfnt)
    return files, fonts, sfnt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', type=Path, default=OUT_DIR, help=f'output directory (default {OUT_DIR})')
    parser.add_argument('--font', type=Path, default=FONT_PATH, help='variable Montserrat.ttf')
    parser.add_argument('--lvgl', type=Path, default=LVGL, help='LVGL 9.0.0 tree for the built-in metrics cross-check')
    parser.add_argument('--strict', action='store_true', help='no synthesized glyphs: U+00AD fails generation too')
    parser.add_argument('--check', action='store_true', help='do not write; exit 1 if the files on disk differ')
    parser.add_argument('--with-ascii', action='store_true',
                        help='bake ASCII into the 12/14/16/22 px fonts too (the pre-hybrid standalone layout; '
                             'comparison only -- the firmware ships the hybrid default)')
    args = parser.parse_args(argv)
    if args.with_ascii and not args.check and args.out.resolve() == OUT_DIR.resolve():
        print(f'FAIL: --with-ascii writes the comparison layout; pass --out DIR (not {OUT_DIR})', file=sys.stderr)
        return 2
    try:
        files, _fonts, _sfnt = generate(args.font, strict=args.strict, lvgl=args.lvgl if args.lvgl.is_dir() else None,
                                        with_ascii=args.with_ascii)
    except GenerationError as error:
        print(f'FAIL: {error}', file=sys.stderr)
        return 1
    if args.check:
        stale = [name for name, text in files.items()
                 if not (args.out / name).is_file() or (args.out / name).read_text(encoding='ascii') != text]
        for name in stale:
            print(f'STALE {args.out / name}')
        print('check: ' + ('up to date' if not stale else f'{len(stale)} file(s) differ'))
        return 1 if stale else 0
    args.out.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        text.encode('ascii')  # generated C stays pure ASCII (no MSVC code-page surprises)
        (args.out / name).write_text(text, encoding='ascii', newline='\n')
        print(f'wrote {args.out / name} ({len(text)} chars)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
