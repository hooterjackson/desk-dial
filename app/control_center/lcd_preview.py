"""Static 240 px mirror of the Nano_D++ knob LCD (presentation 5, PRESENTATION_V5.md section 8).

``render_lcd(frame, artwork=None, window_icon=None, overlay=False, *, artwork2=False)`` draws the
settled (final) state the knob shows for one wire frame. There is no animation: every layer is
drawn at the end state of its section 8.8 transition (the floating knob's LCD is change-driven,
DESKTOP_STAGE.md 11.5).

Sources: ``firmware/PRESENTATION_V5.md`` section 8 ("K1"), the firmware renderer
``src/cc_display.cpp`` (the reference for what text is drawn where; the LVGL harness in
``harness`` dumps it and ``tests/test_cc_lcd_preview.py`` FirmwareParityTests compares).
A presentation-4 frame (a v6 host, or a cc5.3 fixture) is drawn with the same v5 geometry and
inks, as cc5.4 draws it (section 2.3).

* The mirror draws the SAME strings the knob draws. Text is measured with the knob's own font
  metrics (``_KNOB_FONT_METRICS`` below, extracted from the firmware fonts): ASCII from LVGL 9.0's
  hinted ``lv_font_montserrat_<N>`` (advances plus class kerning), every other glyph from the
  generated ``cc_font_<N>`` (unhinted advances, 4 bpp ink boxes; U+00AD is an empty, zero-advance
  glyph), the volume digits from ``cc_font_48`` and the Seek time from the tabular ``cc_font_48t``
  (key ``'48t'``: digits from Montserrat's ``zero.tf`` .. ``nine.tf``, section 10). A glyph outside
  those fonts is LVGL's placeholder (a frame ``line_height / 2 + 2`` wide). Widths are
  ``lv_text_get_width``'s: whole-pixel kerned advances, letter spacing only after glyphs with a
  width, the last one trimmed. ``measure(text, size)`` exposes them (K3 fits its placeholders
  with it).
* Fitting is ``cc_display.cpp``'s. Each line of a label may use the label width clamped to the
  r104 chord (r112 for the heading, section 8.5.2) of the rows its ink occupies on that line. One-
  line labels ellipsize at a code point. Two-line titles take the balanced space split whose lines
  both fit (ties keep the longer first line), else a balanced break inside an over-wide word
  (preferably after - _ / \\ .), else a full first line and a second line clamped at a word, so
  U+2026 appears only when the text cannot be shown whole. A heading drops its 1 px tracking,
  then shortens "RECENTLY ADDED · P{n}" to "RECENT · P{n}", then ellipsizes.
* Text is anchored on its baseline, the firmware label's ``y + ascent``. Lines are centred in the
  label box as ``LV_TEXT_ALIGN_CENTER`` does it (C integer division). The twelve labels with a
  text-shadow twin (section 8.5.3) get a black copy at 80 % one pixel lower, painted first with a
  masked paste. Glyph shapes are Pillow's unhinted Montserrat Medium, so an ASCII glyph can differ
  from the knob's hinted bitmap by a pixel; strings, line breaks, pen positions and baselines are
  the knob's.
* Inks and glyphs follow section 5.2 (``presentation.button_tone_v5`` / ``button_ink_v5``): the
  paused Home Play is green, ``lit`` on/off draw #FFFFFF / #7A7A7A, an assigned snap side its
  ``accent_ink``, and [r2.2] a liked heart the filled ``heartfill`` in #A3244A. The Windows letter
  tile takes ``sat()`` of the selected entry's accent with a #FFFFFF initial (section 5.3).
* Wire text is drawn verbatim. A pre-wire frame (the Tk mirror renders ``controller.frame()``)
  first gets the host's own adaptation, as ``device._frame`` sends it to a latin-ext-a knob: glyphs
  outside the knob fonts transliterated (or "?") and the text cut at the contract's UTF-8
  capacities. The renderer never invents copy, except the knob's own: the Seek time ``m:ss`` from
  ``ring.index``, the tile initial, and ``frame=None``, the firmware-local offline screen
  "Waiting for PC" (section 8.10; ``native=True`` after native input).

Desktop floating knob (``FLOATING_KNOB.md`` section 3): ``render_lcd(..., scale=k)`` paints the
same scene at ``round(240 * k)`` px. Layout, text fitting and line breaking stay in knob pixels
(``compose`` / ``fit_*``); only painting multiplies by k: fonts at ``size * k``, pens and baselines
times k, icon masks from the ``@2x``/``@3x`` exports in ``assets/lcd-icons``, tile rectangles
times k, shadows one knob pixel (k device pixels) lower, and an anti-aliased glass. Every
composite at scale k is a masked paste over the run's own box (never ``alpha_composite``,
DESKTOP_STAGE.md 11.5). ``hires_cover`` / ``hires_icon`` are used only at k != 1.

Presentation 6 (PRESENTATION_V5.md section 19, Desk Dial r3 release 1), as ``cc_display.cpp`` draws it:
``lights`` is the Home text drawing (title 22/26 two lines, sub-line 14, the 12 px line = ``meta`` in its
``metaTone``, never ``status``), ``lightsbig`` the Home reveal (caption = ``volumeCaption``, 48 px digits of
``value`` and the 22 px unit ``valueUnit`` "%" | "K"), ``scenes`` the scenes list (``prevTitle`` 14 px #7C7C7C,
``title`` 22 px one line, ``nextTitle`` 14 px #7C7C7C, ``meta`` 12 px); none of them draws art. The six icons
bulb thermo power wand house album come from the same handoff-icons export. ``v6_parse`` is the Python
reading of the presentation-6 parser rules (parity with ``cc_frame_parse.cpp``: harness parse_tests.py).
"""
from __future__ import annotations

import base64
from io import BytesIO
import json
import math
import re
import struct
import zlib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from control_center.artwork import ArtworkError, cover_key, icon_key, icon_payload, rgb565le_rounded
from control_center.device import _device_text
from control_center.presentation import (
    BUTTON_LABEL_CAPACITY, COVER_MAX_BYTES, COVER_SIZE, ICON_BYTES, ICON_KEY_PATTERN, ICON_SIZE, ICONS,
    INK, INK_DISABLED_GLYPH, INK_META, INK_SECONDARY, LAYOUTS, LEGACY_LAYOUT, LINE_TONES, PRESENTATION_VERSION,
    REST_LAYOUTS, RING_WINDOW, TEXT_CAPACITY, TILE, TILE_INITIAL, TITLE_TONES, TONE_INK,
    button_ink_v5, button_tone_v5, mmss, sat_rgb, window_first,
)

ASSETS = Path(__file__).resolve().parents[1] / 'assets'
FONT_PATH = ASSETS / 'fonts' / 'Montserrat.ttf'
ICON_DIR = ASSETS / 'handoff-icons'
# Hi-res masks of the same icon paths (floating knob, scale > 1 only):
# {name}-{size}@{factor}x.png, written by harness/export_handoff_icons.cjs --png-only.
HIRES_ICON_DIR = ASSETS / 'lcd-icons'
HIRES_ICON_FACTORS = (2, 3)
FONT_WEIGHT = 500          # the knob fonts are the variable font's "Medium" instance

SIZE = 240
CENTRE = 120
SAFE_RADIUS = 104
HEADING_RADIUS = 112       # section 8.3: headings may reach r112 (the bezel hides r112..120)
ELLIPSIS = '…'
ART_SIZE = 120             # v1 wire artwork: 120 x 120 RGB565 LE, pre-composited
ART_BYTES = ART_SIZE * ART_SIZE * 2
ART_DIM = 0.4375           # artDim: image_opa 112 = 0.35 / 0.8 of the composited cover
ART_PAUSED = 1.0           # [r3.1] a paused Home / Music cover: image_opa 255 (cc_art_image_opa; user ruling 2026-09-29)
CLOSED_OPACITY = 0.35      # Windows tile of a closed (unavailable) entry
SHADOW_OPACITY = 204       # text-shadow twins: 0 1px 0 black at 80 % (section 8.5.3)
_ICON_KEY = re.compile(ICON_KEY_PATTERN)

SEEK_FONT = '48t'          # cc_font_48t, the tabular Seek time (section 10)
# LVGL metrics of the cc_font_<N> fonts (src/fonts/cc_fonts.h).
LINE_HEIGHT = {12: 15, 14: 16, 16: 18, 22: 24, 48: 52, SEEK_FONT: 52}
ASCENT = {12: 12, 14: 13, 16: 15, 22: 20, 48: 43, SEEK_FONT: 43}
CAP_HEIGHT = {12: 9, 14: 10, 16: 12, 22: 16, 48: 34, SEEK_FONT: 34}
PX = {12: 12, 14: 14, 16: 16, 22: 22, 48: 48, SEEK_FONT: 48}   # painted pixel size of each font key
LINE_SPACE = 2             # two-line labels: line pitch = LINE_HEIGHT + 2 (26 / 20 / 18)

FOOTER_X = (56, 99, 141, 184)
FOOTER_TOP, FOOTER_ICON = 154, 20
# [r3.1] (section 19.10; r3.1 prototype L349) the hold tick: 16 x 2 px, radius 1, #A6A6A6 at (176, 180) under the
# button-4 footer icon, drawn with holdMarker outside the idle icon view.
HOLD_TICK = (176, 180, 16, 2)
HOLD_TICK_RGB = (0xA6, 0xA6, 0xA6)
IDLE_X = (51, 97, 143, 189)
IDLE_TOP, IDLE_ICON, IDLE_COLUMN = 100, 26, 60
TRACK_ICON_X = (72, 112, 152)          # left edges of the 16 px prev / dotfill / next boxes
TRACK_ICON_TOP, TRACK_ICON = 88, 16
TILE_BOX = (104, 42, 32)                # x, y, size
DIGIT_GAP = 4                           # r4 README 3.6: number | 4 px | unit around a computed centre
DIGIT_CHARS = '0123456789-'
DIGIT_LIMIT = 7                         # cc_display.cpp: char number[8]
DIGIT_TRACKING = -1                     # -0.02em at 48 px (volume digits and the Seek time)
SEEK_TIME_BASELINE = 116                # SEEK_TIME {0, 73, 240, 52}: top 73 + ascent 43


def _rgb(value):
    return (value >> 16) & 255, (value >> 8) & 255, value & 255


INK_RGB = _rgb(INK)
SECONDARY_RGB = _rgb(INK_SECONDARY)
META_RGB = _rgb(INK_META)
DISABLED_GLYPH_RGB = _rgb(INK_DISABLED_GLYPH)
TILE_RGB = _rgb(TILE)


# --------------------------------------------------------------------------
# Knob font metrics
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def font_data():
    """The embedded knob font tables, as extracted (JSON types, string keys)."""
    return json.loads(zlib.decompress(base64.b64decode(''.join(_KNOB_FONT_METRICS.split()))))


def _font_key(size):
    return int(size) if str(size).isdigit() else size


@lru_cache(maxsize=1)
def _fonts():
    data = font_data()
    fonts = {}
    for size, entry in data['fonts'].items():
        fonts[_font_key(size)] = {'cc': {int(cp): tuple(g) for cp, g in entry['cc'].items()},
                                  'ascii': [tuple(g) for g in entry.get('ascii', ())],
                                  'kern': entry.get('kern', ()), 'kern_scale': entry.get('kern_scale', 0)}
    return fonts, data['left'], data['right'], data['columns']


def is_marker(cp):
    """LVGL 9.0 ``_lv_text_is_marker``: zero width and never drawn."""
    return (cp < 0x20 or cp in (0x061C, 0x115F, 0x1160, 0xFEFF, 0xF8FF) or 0x180B <= cp <= 0x180E
            or 0x200B <= cp <= 0x200F or 0x2028 <= cp <= 0x202F or 0x205F <= cp <= 0x206F)


def glyph(cp, size):
    """(adv_w in 1/16 px, box_w, box_h, ofs_y) of the glyph the knob resolves cp to, or None.

    cc_font_<N> first, then its lv_font_montserrat_<N> fallback (ASCII only); cc_font_48 and
    cc_font_48t have no fallback. None is LVGL's placeholder (glyph not found).
    """
    fonts = _fonts()[0]
    table = fonts.get(size)
    if table is None:
        return None
    found = table['cc'].get(cp)
    if found is None and table['ascii'] and 0x20 <= cp <= 0x7E:
        found = table['ascii'][cp - 0x20]
    return found


def _kern(cp, next_cp, size):
    """Class kerning of the built-in (1/16 px) for an ASCII glyph before next_cp."""
    fonts, left, right, columns = _fonts()
    if not 0x20 <= cp <= 0x7E or cp in fonts[size]['cc'] or not fonts[size]['kern']:
        return 0
    if 0x20 <= next_cp <= 0x7E:
        right_class = right[next_cp - 0x20]
    elif next_cp in (0xB0, 0x2022):      # the built-in's only other text glyphs
        right_class = right[95 if next_cp == 0xB0 else 96]
    else:
        return 0
    left_class = left[cp - 0x20]
    if not left_class or not right_class:
        return 0
    table = fonts[size]
    return (table['kern'][(left_class - 1) * columns + right_class - 1] * table['kern_scale']) >> 4


@lru_cache(maxsize=16384)
def advance(char, size, next_char=''):
    """lv_font_get_glyph_width: whole-pixel advance, kerned with the next letter."""
    cp = ord(char)
    if is_marker(cp):
        return 0
    found = glyph(cp, size)
    if found is None:
        return LINE_HEIGHT[size] // 2 + 2   # LV_USE_FONT_PLACEHOLDER
    adv_w = found[0] + (_kern(cp, ord(next_char), size) if next_char else 0)
    return (adv_w + 8) >> 4


def text_width(text, size, tracking=0):
    """lv_text_get_width: spacing follows every glyph with a width; the last one is trimmed."""
    width = 0
    for i, char in enumerate(text):
        step = advance(char, size, text[i + 1] if i + 1 < len(text) else '')
        if step > 0:
            width += step + tracking
    return width - tracking if width > 0 else width


def measure(text, size, tracking=0):
    """Width in knob pixels of ``text`` at knob font ``size`` (12, 14, 16, 22, 48 or '48t'), as the
    firmware measures it (lv_text_get_width with the knob fonts). K3 fits its placeholders with it
    (CONTROL_CENTER_V5.md 15.1)."""
    return text_width(text if isinstance(text, str) else '', _font_key(size), tracking)


def ink_rows(text, size):
    """(first, last) ink row of the text relative to the baseline, or None (cc_display inkRows)."""
    top = bottom = None
    for char in text:
        found = glyph(ord(char), size)
        if found is None or not found[1] or not found[2]:
            continue
        _, _, box_h, ofs_y = found
        first, last = -box_h - ofs_y, -ofs_y - 1
        top = first if top is None else min(top, first)
        bottom = last if bottom is None else max(bottom, last)
    return None if top is None else (top, bottom)


def safe_half(top, bottom, radius=SAFE_RADIUS):
    """Half-width of the radius chord over pixel rows top..bottom (cc_display safeHalf)."""
    half = CENTRE
    for y in range(top, bottom + 1):
        d = CENTRE - y if y < CENTRE else y + 1 - CENTRE
        half = min(half, 0 if d >= radius else math.isqrt(radius * radius - d * d))
    return half


def _c_half(value):
    """C ``value / 2`` (truncates toward zero)."""
    return value // 2 if value >= 0 else -(-value // 2)


# --------------------------------------------------------------------------
# Labels and fitting (cc_display.cpp)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Label:
    """One LVGL label: box x and width, baseline of line 1, font, lines, tracking, fitting radius,
    and whether it has a text-shadow twin (section 8.5.3)."""
    x: int
    width: int
    baseline: int
    size: object
    lines: int = 1
    tracking: int = 0
    radius: int = SAFE_RADIUS
    shadow: bool = False
    crumb_clear: bool = False            # FW-DES-001: line 1 also clears the crumb's ink (the list title)

    @property
    def top(self):
        return self.baseline - ASCENT[self.size]

    @property
    def pitch(self):
        return LINE_HEIGHT[self.size] + LINE_SPACE

    @property
    def centre(self):
        return self.x + self.width // 2

    def line_width(self, ink, row=0, crumb=''):
        """cc_display lineWidth: the box width clamped to the chord of the ink rows on this row; with
        ``crumb_clear`` and a crumb shown, line 1 is also clamped to that crumb's clearance (FW-DES-001)."""
        if ink is None:
            half = CENTRE                    # nothing inked: the chord never binds
        else:
            baseline = self.baseline + row * self.pitch
            half = safe_half(baseline + ink[0], baseline + ink[1], self.radius)
        width = 2 * (half - abs(self.centre - CENTRE))
        if row == 0 and self.crumb_clear and crumb and ink is not None:
            baseline = self.baseline
            width = min(width, 2 * crumb_clear_half(crumb, self.centre, baseline + ink[0], baseline + ink[1]))
        return min(max(0, width), self.width)


CRUMB_INK_ALPHA, CRUMB_GAP = 32, 2       # cc_display.cpp CRUMB_INK_ALPHA / CRUMB_GAP (FW-DES-001)


def crumb_clear_half(crumb, centre, top, bottom):
    """cc_display crumbClearHalf: the half-width around ``centre`` clear of ``crumb``'s ink (both masks,
    alpha >= CRUMB_INK_ALPHA, plus CRUMB_GAP px) over pixel rows [top, bottom]; CENTRE when the crumb has
    no ink there. A centred line 2 * half wide then shares no pixel with the crumb."""
    from control_center import crumb_arc
    half = CENTRE
    try:
        masks = crumb_arc.render(crumb)
    except KeyError:                     # an unknown token draws no crumb
        return half
    for mask in masks:
        if mask is None or not mask.w:
            continue
        for y in range(max(top, mask.y), min(bottom, mask.y + mask.h - 1) + 1):
            row = mask.data[(y - mask.y) * mask.w:(y - mask.y + 1) * mask.w]
            for x, alpha in enumerate(row):
                if alpha < CRUMB_INK_ALPHA:
                    continue
                px = mask.x + x
                room = (centre - px - 1 if px < centre else px - centre) - CRUMB_GAP
                half = min(half, room)
    return max(half, 0)


def fit_line(text, width, size, tracking=0, force=False):
    """appendLine: the text when it fits, else the longest code-point prefix (trailing spaces
    trimmed) that fits with an ellipsis. ``force`` always ends in the ellipsis."""
    if not force and text_width(text, size, tracking) <= width:
        return text
    lo, hi, keep = 0, len(text), 0          # the firmware's binary search, kept verbatim
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if text_width(text[:mid].rstrip(' ') + ELLIPSIS, size, tracking) <= width:
            keep = lo = mid
        else:
            hi = mid - 1
    return text[:keep].rstrip(' ') + ELLIPSIS


def _fitting_prefix(text, width, size, tracking):
    end = 0
    for cut in range(1, len(text) + 1):
        if text_width(text[:cut], size, tracking) > width:
            break
        end = cut
    return end


def last_line(text, width, size, tracking=0):
    """appendLastLine: the whole text when it fits; else the whole words that fit together
    with U+2026 (-webkit-line-clamp), cutting characters only when no whole word fits."""
    if text_width(text, size, tracking) <= width:
        return text
    words = 0
    for i in range(1, len(text)):
        if text[i] != ' ':
            continue
        end = len(text[:i].rstrip(' '))
        if end == 0:
            continue
        if text_width(text[:end] + ELLIPSIS, size, tracking) > width:
            break
        words = end
    return fit_line(text[:words] if words else text, width, size, tracking, force=True)


WORD_SEPARATORS = '-_/\\.'   # preferred breaks inside an over-wide word (file names, paths)


def _consider(best, end1, start2, w1, w2):
    """Keep the split with the narrower wider line; ties keep the longer first line."""
    score = max(w1, w2)
    return (end1, start2, score) if best is None or score <= best[2] else best


def fit_two_lines(text, width1, width2, size, tracking=0):
    """fitTwoLines (CSS text-wrap: balance + line-clamp 2); U+2026 only when the text cannot
    be shown whole in the two lines:

    1. a split at a space where both lines fit, minimising the wider line;
    2. otherwise a split inside a word wider than a line (overflow-wrap), again
       balanced, preferring a break after - _ / \\ . over any code point;
    3. otherwise a full first line (the words that fit, or the first word cut by
       characters) and a clamped second line.
    """
    if text_width(text, size, tracking) <= width1:
        return [text]
    length = len(text)
    best = greedy = None
    for i in range(1, length):
        if text[i] != ' ':
            continue
        end1 = len(text[:i].rstrip(' '))
        start2 = i
        while start2 < length and text[start2] == ' ':
            start2 += 1
        if end1 == 0 or start2 == length:
            continue
        w1 = text_width(text[:end1], size, tracking)
        if w1 > width1:
            break                           # later splits only widen line 1
        greedy = end1, start2
        w2 = text_width(text[start2:], size, tracking)
        if w2 <= width2:
            best = _consider(best, end1, start2, w1, w2)
    if best is None:
        narrow, separated, start, stop = min(width1, width2), None, 0, False
        while start < length and not stop:
            while start < length and text[start] == ' ':
                start += 1
            end = start
            while end < length and text[end] != ' ':
                end += 1
            if end > start and text_width(text[start:end], size, tracking) > narrow:
                for cut in range(start + 1, end):
                    w1 = text_width(text[:cut], size, tracking)
                    if w1 > width1:
                        stop = True
                        break
                    w2 = text_width(text[cut:], size, tracking)
                    if w2 <= width2:
                        best = _consider(best, cut, cut, w1, w2)
                        if text[cut - 1] in WORD_SEPARATORS:
                            separated = _consider(separated, cut, cut, w1, w2)
            start = end
        if separated is not None:
            best = separated
    if best is not None:
        end1, start2 = best[:2]
    elif greedy is not None:
        end1, start2 = greedy
    else:                                   # the first word alone is wider than line 1
        end1 = _fitting_prefix(text, width1, size, tracking) or 1
        start2 = end1
        while start2 < length and text[start2] == ' ':
            start2 += 1
    rest = text[start2:]
    return [text[:end1], last_line(rest, width2, size, tracking)] if rest else [text[:end1]]


def fit_label(label, text, crumb=''):
    """showText: the drawn lines of a label and the width each line was fitted to (``crumb``: the crumb
    on screen, which a ``crumb_clear`` label's first line keeps clear of, FW-DES-001)."""
    ink = ink_rows(text, label.size)
    width1 = label.line_width(ink, 0, crumb)
    if label.lines > 1:
        width2 = label.line_width(ink, 1)
        return fit_two_lines(text, width1, width2, label.size, label.tracking), [width1, width2]
    return [fit_line(text, width1, label.size, label.tracking)], [width1]


RECENT_LONG, RECENT_SHORT = 'RECENTLY ADDED · P', 'RECENT · P'


def fit_heading(text):
    """showHeading (section 8.5.2): (drawn text, tracking, fitted width) of the heading row.
    Every v5 heading fits at 1 px; a legacy one drops the tracking, then "RECENTLY ADDED · P{n}"
    becomes "RECENT · P{n}", then it is ellipsized at tracking 0."""
    tracking = HEADING.tracking
    if not text:
        return '', tracking, 0
    width = HEADING.line_width(ink_rows(text, HEADING.size))
    size = HEADING.size
    if text_width(text, size, tracking) <= width:
        return text, tracking, width
    if text_width(text, size, 0) <= width:
        return text, 0, width
    if text.startswith(RECENT_LONG):
        shorter = RECENT_SHORT + text[len(RECENT_LONG):]
        if text_width(shorter, size, tracking) > width:
            return fit_line(shorter, width, size, 0), 0, width
        return shorter, tracking, width
    return fit_line(text, width, size, 0), 0, width


def volume_digits(value):
    """The 48 px number: digits and '-' before the first '%', at most seven."""
    number = ''
    for char in value:
        if char == '%' or len(number) >= DIGIT_LIMIT:
            break
        if char in DIGIT_CHARS:
            number += char
    return number


# Label geometry (section 8.5.1): cc_display.cpp boxes; baseline = LVGL y + ascent, the rounded
# CSS baseline (comments give the CSS top). shadow = one of the twelve twins (section 8.5.3).
HEADING = Label(51, 138, 43, 12, tracking=1, radius=HEADING_RADIUS, shadow=True)   # top 32, y 31
HOME_TITLE = Label(35, 170, 81, 22, lines=2, shadow=True)       # top 60
HOME_ARTIST = Label(35, 170, 128, 14, shadow=True)              # top 114
STATUS = Label(30, 180, 145, 12)                                # top 134; r3 x 30 w 180 (L-6)
# Presentation 6 scenes list (section 19.4; README r3 2.2): prev top 56, current top 78 (x 30..210), next top
# 108, meta top 134 (x 30..210).
SCENE_PREV = Label(68, 104, 70, 14)                             # y 57; r4 3.6 previous <= 104
SCENE_TITLE = Label(40, 160, 99, 22, shadow=True)               # y 79, one line; r4 3.6 current <= 160
SCENE_NEXT = Label(45, 150, 122, 14)                            # y 109; r4 3.6 next <= 150
SCENE_META = Label(32, 176, 145, 12)                            # y 133; r4 3.6 meta <= 176
VOLUME_CAPTION = Label(35, 170, 66, 14, shadow=True)            # top 52
DIGITS_BASELINE = 116                                           # top 76, 48/46; '%' shares it
IDLE_WORD_BASELINE = 145                                        # top 134 (icon 100..126, gap 8)
LIST_TITLE = Label(35, 170, 73, 22, lines=2, shadow=True, crumb_clear=True)       # top 52
LIST_SUBTITLE = Label(35, 170, 120, 14, shadow=True)            # top 106
LIST_META = Label(35, 170, 138, 12)                             # top 127
TRACKS_TITLE = Label(35, 170, 75, 22, shadow=True)              # top 54, single line
TRACKS_SUBTITLE = Label(35, 170, 124, 14, shadow=True)          # top 110
TRACKS_META = Label(32, 176, 141, 12)                           # top 130; r3 x 30 w 180 (L-6); r4 3.6 meta <= 176
SEEK_CAPTION = Label(35, 170, 66, 14, shadow=True)              # top 52
SEEK_TIME = Label(0, 240, SEEK_TIME_BASELINE, SEEK_FONT, tracking=DIGIT_TRACKING, shadow=True)  # top 76, 48/46
SEEK_LINE = Label(25, 190, 142, 14)                             # top 128, 14/18; r3 x 25 w 190
WINDOWS_APP = Label(35, 170, 94, 14)                            # top 80
WINDOWS_TITLE = Label(35, 170, 114, 16, lines=2)                # top 98, 16/20
WINDOWS_META = Label(35, 170, 151, 12)                          # top 140
TILE_INITIAL_LABEL = Label(104, 32, 64, 16)                     # CSS 16/16 line centred in the tile: y 49
OFFLINE_TITLE_LABEL = Label(35, 170, 91, 22)                    # top 70, one line
OFFLINE_SUB_LABEL = Label(35, 170, 118, 14, lines=2)            # top 104, 14/18, two balanced lines
# K1 8.10 erratum (lead ruling R-c; cc_display.cpp showOfflineSub, OFFLINE_NATIVE_TRACKING): the native
# sub-line "Knob controls still work" is 171 px with the knob font against the 170 px line, so when it
# does not fit at 0 tracking it is drawn at -1 px (148 px) and stays on one line with the approved words.
OFFLINE_NATIVE_LABEL = Label(35, 170, 118, 14, lines=2, tracking=-1)
IDLE_WORDS = tuple(Label(x - IDLE_COLUMN // 2, IDLE_COLUMN, IDLE_WORD_BASELINE, 12) for x in IDLE_X)

# Firmware-local offline screen (section 8.10; VOC knob.title.offline, knob.sub.offline(_native)).
# The sub keeps "Desk Dial" together with a no-break space (U+00A0, as cc_display.cpp OFFLINE_SUB):
# fit_two_lines breaks only at ASCII spaces, so it renders 'Open Desk Dial' / 'on your PC', never
# 'Open Desk' / 'Dial on your PC' (rename-desk-dial.md 5.2 and 11.5).
OFFLINE = {'title': 'Waiting for PC', 'subtitle': 'Open Desk\u00a0Dial on your PC',
           'native': 'Knob controls still work'}

# Legacy frames without "icon": the firmware's cc_legacy_icon() label table.
LEGACY_ICON = {'Play': 'play', 'Pause': 'pause', 'Browse': 'list', 'Win': 'win', 'Tracks': 'tracks',
               'Back': 'back', 'Home': 'home', 'More': 'more', 'Prev': 'prev', 'Next': 'next',
               'Skip': 'next', 'Switch': 'switch', 'Cancel': 'cancel'}
ICON_NAMES = frozenset(name for name in tuple(ICONS) + ('bulb', 'thermo', 'power', 'wand', 'house', 'album') if name)   # 9.1, 19.5 (ICONS_V6)
LIKED_GLYPH = 'heartfill'                                # [r2.2] tone liked (section 5.2 row 4)
DOT_GLYPH = 'dotfill'                                    # the Tracks position-row centre
ART_LAYOUTS = ('nowPlaying', 'volume', 'recent', 'tracks', 'seek', 'explorer', 'upnext')   # section 8.4
# Presentation 6 (section 19): tokens appended to the presentation-5 ones (whatever presentation.py has yet).
LAYOUTS_V6 = ('lights', 'lightsbig', 'scenes')
RING_STYLES_V6 = ('bri', 'ctemp', 'clusters', 'marker',   # marker: section 19.9 (r3 navigation)
                  'queue')                                 # [r3.1] section 19.10: the whole-queue ring
ICONS_V6 = ('bulb', 'thermo', 'power', 'wand', 'house', 'album')
VALUE_UNITS = ('%', 'K')
KELVIN_MIN, KELVIN_MAX = 2200, 6500
CLUSTERS_MAX = 20
TITLE_V6_CAPACITY = 64                          # prevTitle / nextTitle (char[65])
# Section 19.9 (the r3 navigation): the crumb tokens, the `warm` line tone and feedback.moment `refused`.
CRUMBS_V6 = ('music', 'recent', 'onScreenRecent', 'onScreenPlaylists', 'tracks', 'upnext', 'windows', 'lights',
             'scenes', 'playlists')                      # r3.1 appends `playlists` (MUSIC › PLAYLISTS)
LINE_TONES_V6 = tuple(LINE_TONES) + ('warm',)
MOMENTS_V6 = ('queued', 'shuffle', 'like', 'unlike', 'snap', 'started', 'refused')
ALL_LAYOUTS = tuple(dict.fromkeys(tuple(LAYOUTS) + LAYOUTS_V6))
ALL_RING_STYLES = tuple(dict.fromkeys(('off', 'level', 'selection', 'transport', 'lap') + RING_STYLES_V6))
ALL_ICONS = tuple(dict.fromkeys(tuple(ICONS) + ICONS_V6))


@lru_cache(maxsize=64)
def font(size):
    """Montserrat at wght 500 with BASIC layout (no shaping): the glyph shapes the mirror paints.

    ``size`` is a pixel size (the knob size, or ``size * k`` when painting at scale k)."""
    face = ImageFont.truetype(str(FONT_PATH), size, layout_engine=ImageFont.Layout.BASIC)
    face.set_variation_by_axes([FONT_WEIGHT])
    return face


# The tabular Seek face: the same variable font with '0'..'9' mapped to zero.tf..nine.tf (section
# 10; the in-memory remap of harness/gen_lvgl_font.py tabular_font_bytes, ported here
# without fontTools so the companion needs nothing beyond Pillow).
_TABULAR_NAMES = ('zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine')
_MAC_NAMES = {0: '.notdef', 3: 'space', 19: 'zero', 20: 'one', 21: 'two', 22: 'three', 23: 'four', 24: 'five',
              25: 'six', 26: 'seven', 27: 'eight', 28: 'nine', 29: 'colon'}


def _sfnt_tables(data, checksums=None):
    """tag -> table bytes; ``checksums`` (a dict), when given, receives each table's directory
    checksum."""
    count = struct.unpack('>H', data[4:6])[0]
    tables = {}
    for i in range(count):
        tag, checksum, offset, length = struct.unpack('>4sIII', data[12 + 16 * i:28 + 16 * i])
        tables[tag.decode('latin-1')] = data[offset:offset + length]
        if checksums is not None:
            checksums[tag.decode('latin-1')] = checksum
    return tables


def _cmap_glyph(cmap, cp):
    """Glyph id of cp from the font's first format 4 Unicode subtable (BMP)."""
    for i in range(struct.unpack('>H', cmap[2:4])[0]):
        pid, eid, offset = struct.unpack('>HHI', cmap[4 + 8 * i:12 + 8 * i])
        if (pid, eid) not in ((3, 1), (0, 3), (0, 4)) or struct.unpack('>H', cmap[offset:offset + 2])[0] != 4:
            continue
        seg = struct.unpack('>H', cmap[offset + 6:offset + 8])[0] // 2
        ends = struct.unpack(f'>{seg}H', cmap[offset + 14:offset + 14 + 2 * seg])
        starts = struct.unpack(f'>{seg}H', cmap[offset + 16 + 2 * seg:offset + 16 + 4 * seg])
        deltas = struct.unpack(f'>{seg}h', cmap[offset + 16 + 4 * seg:offset + 16 + 6 * seg])
        range_at = offset + 16 + 6 * seg
        ranges = struct.unpack(f'>{seg}H', cmap[range_at:range_at + 2 * seg])
        for k in range(seg):
            if starts[k] <= cp <= ends[k]:
                if ranges[k] == 0:
                    return (cp + deltas[k]) & 0xFFFF
                at = range_at + 2 * k + ranges[k] + 2 * (cp - starts[k])
                gid = struct.unpack('>H', cmap[at:at + 2])[0]
                return (gid + deltas[k]) & 0xFFFF if gid else 0
    return 0


# Words per struct.unpack_from / sum call of _checksum: 4,096 words (16 KB) take well under 0.1 ms,
# so no single C call of the Seek font build holds the GIL anywhere near DESKTOP_STAGE G1-5's
# ~2 ms limit (the whole 741 KB font in one call held it 2-3 ms, twice).
_CHECKSUM_CHUNK_WORDS = 4096


def _checksum(data):
    """The sfnt checksum (sum of the big-endian uint32 words, zero padded) in bounded chunks."""
    padded = data + b'\0' * (-len(data) % 4)
    view = memoryview(padded)
    total = 0
    for at in range(0, len(padded), 4 * _CHECKSUM_CHUNK_WORDS):
        words = min(_CHECKSUM_CHUNK_WORDS, (len(padded) - at) // 4)
        total += sum(struct.unpack_from(f'>{words}I', view, at))
    return total & 0xFFFFFFFF


@lru_cache(maxsize=1)
def _tabular_font_bytes():
    """Montserrat with a cmap of '0'..'9' -> zero.tf..nine.tf and ':' -> colon.

    Built lazily on the first Seek render, possibly on the Tk thread while an overlay takes input,
    so it avoids large single C calls (G1-5): the checksums of the tables it copies unchanged are
    the source's own directory entries (verified by tests), only the new cmap and the edited head
    are summed, and the whole-file checkSumAdjustment is derived from the table checksums (the
    file's word sum is the header's plus every padded table's) instead of a pass over the file."""
    data = FONT_PATH.read_bytes()
    source_sums = {}
    tables = _sfnt_tables(data, source_sums)
    post = tables['post']
    count = struct.unpack('>H', post[32:34])[0]
    index = struct.unpack(f'>{count}H', post[34:34 + 2 * count])
    extra, at = [], 34 + 2 * count
    while at < len(post):
        extra.append(post[at + 1:at + 1 + post[at]].decode('latin-1'))
        at += 1 + post[at]
    names = [_MAC_NAMES.get(i, f'.mac{i}') if i < 258 else extra[i - 258] for i in index]
    gid_of = {name: gid for gid, name in enumerate(names)}
    mapping = {0x30 + i: gid_of[f'{name}.tf'] for i, name in enumerate(_TABULAR_NAMES)}
    mapping[0x3A] = _cmap_glyph(tables['cmap'], 0x3A)
    # One format 4 subtable: a segment per code point plus the 0xFFFF terminator.
    segments = sorted(mapping.items()) + [(0xFFFF, None)]
    seg = len(segments)
    search = 2 * (1 << (seg.bit_length() - 1))
    ends = [cp for cp, _ in segments]
    deltas = [((gid - cp) & 0xFFFF) if gid is not None else 1 for cp, gid in segments]
    body = struct.pack(f'>{seg}H', *ends) + b'\0\0' + struct.pack(f'>{seg}H', *ends)
    body += struct.pack(f'>{seg}H', *deltas) + struct.pack(f'>{seg}H', *([0] * seg))
    sub = struct.pack('>HHHHHHH', 4, 14 + len(body), 0, 2 * seg, search, search.bit_length() - 2, 2 * seg - search) + body
    tables['cmap'] = struct.pack('>HHHHIHHI', 0, 2, 0, 3, 20, 3, 1, 20) + sub
    head = bytearray(tables['head'])
    head[8:12] = b'\0\0\0\0'
    tables['head'] = bytes(head)
    rebuilt = {'cmap', 'head'}   # the only tables whose bytes change here
    tags = sorted(tables)
    n = len(tags)
    search = 16 * (1 << (n.bit_length() - 1))
    out = data[:4] + struct.pack('>HHHH', n, search, (search // 16).bit_length() - 1, 16 * n - search)
    offset = 12 + 16 * n
    records, blobs, sums = [], [], 0
    for tag in tags:
        blob = tables[tag]
        checksum = _checksum(blob) if tag in rebuilt else source_sums[tag]
        records.append(struct.pack('>4sIII', tag.encode('latin-1'), checksum, offset, len(blob)))
        blobs.append(blob + b'\0' * (-len(blob) % 4))
        offset += len(blobs[-1])
        sums += checksum
    directory = out + b''.join(records)
    head_at = struct.unpack('>I', records[tags.index('head')][8:12])[0]
    whole = (_checksum(directory) + sums) & 0xFFFFFFFF   # == _checksum of the finished file
    font_bytes = bytearray(directory + b''.join(blobs))
    font_bytes[head_at + 8:head_at + 12] = struct.pack('>I', (0xB1B0AFBA - whole) & 0xFFFFFFFF)
    return bytes(font_bytes)


@lru_cache(maxsize=16)
def tabular_font(size):
    """The tabular Seek face at pixel size ``size`` (wght 500, BASIC layout)."""
    face = ImageFont.truetype(BytesIO(_tabular_font_bytes()), size, layout_engine=ImageFont.Layout.BASIC)
    face.set_variation_by_axes([FONT_WEIGHT])
    return face


def _face(size_key, k=1.0):
    px = PX[size_key] * k
    return tabular_font(px) if size_key == SEEK_FONT else font(px)


# --------------------------------------------------------------------------
# Scene (what is drawn where); render_lcd paints it
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TextRun:
    role: str
    text: str           # the drawn (fitted) text of one line
    x: int              # pen start of the first glyph
    baseline: int
    size: object
    ink: tuple
    tracking: int = 0
    box: tuple = ()     # (x, width) of the label box
    limit: int = 0      # the width this line was fitted to (safe chord)
    shadow: bool = False  # a text-shadow twin is painted first (section 8.5.3)

    @property
    def width(self):
        return text_width(self.text, self.size, self.tracking)


@dataclass(frozen=True)
class IconRun:
    role: str
    name: str
    x: int              # left of the icon box
    y: int              # top of the icon box
    size: int
    ink: tuple
    opacity: float = 1.0


@dataclass(frozen=True)
class BoxRun:
    role: str
    x: int
    y: int
    size: int
    fill: tuple
    opacity: float = 1.0


@dataclass
class Scene:
    layout: str
    art: bool = False           # draw the cover (if pixels were supplied)
    art_dim: bool = False
    art_paused: bool = False    # [r3.1] a paused Home / Music cover (playing false): drawn at ART_PAUSED
    hold_tick: bool = False     # [r3.1] the hold tick under the button-4 icon (holdMarker, not the idle view)
    window_icon_box: tuple = ()  # (x, y, size, opacity) for a supplied app icon
    items: list = field(default_factory=list)
    crumb: str = ''             # presentation 6 (19.9): the arc breadcrumb token (crumb_arc), '' = none

    def texts(self, role=None):
        return [item for item in self.items if isinstance(item, TextRun) and role in (None, item.role)]

    def icons(self, role=None):
        return [item for item in self.items if isinstance(item, IconRun) and role in (None, item.role)]


# The cc5.4 knob advertises these; the host adapts frame text to them before sending.
KNOB_CAPABILITIES = {'presentation': PRESENTATION_VERSION, 'glyphs': 'latin-ext-a'}


def _text(value, capacity=None):
    """Wire text as the knob receives it: glyphs outside its fonts transliterated (or "?")
    and cut at the UTF-8 capacity, exactly as device._frame does it (idempotent on wire frames)."""
    if not isinstance(value, str):
        return ''
    return _device_text(value, KNOB_CAPABILITIES, capacity) if capacity else value


def _icon(raw, label):
    icon = raw['icon'] if 'icon' in raw else LEGACY_ICON.get(label, '')
    return icon if isinstance(icon, str) and icon in ICON_NAMES else ''


def _int(value, default=0):
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def normalize(frame):
    """Apply the contract's defaults to a (possibly slimmed or legacy) wire frame."""
    source = frame if isinstance(frame, dict) else {}
    out = {key: _text(source.get(key), TEXT_CAPACITY.get(key)) for key in (
        'mode', 'value', 'status', 'title', 'subtitle', 'heading', 'meta', 'volumeCaption')}
    # Presentation 6 (section 19.2): kept on lightsbig / scenes only, like cc_parse_frame.
    for key in ('prevTitle', 'nextTitle'):
        out[key] = _text(source.get(key), TITLE_V6_CAPACITY) if source.get('layout') == 'scenes' else ''
    unit = source.get('valueUnit')
    out['valueUnit'] = unit if unit in VALUE_UNITS and source.get('layout') == 'lightsbig' else '%'
    out['artKey'] = _text(source.get('artKey'))
    icon = source.get('iconKey')
    # artwork2 section 6: a malformed iconKey is stripped (the letter tile shows).
    out['iconKey'] = icon if isinstance(icon, str) and _ICON_KEY.fullmatch(icon) else ''
    layout = source.get('layout')
    out['layout'] = layout if layout in ALL_LAYOUTS else LEGACY_LAYOUT.get(out['mode'], 'nowPlaying')
    rest = source.get('restLayout')
    out['restLayout'] = rest if rest in REST_LAYOUTS else 'nowPlaying'
    tone = source.get('titleTone')
    out['titleTone'] = tone if tone in TITLE_TONES else 'ink'
    for key in ('metaTone', 'statusTone'):
        tone = source.get(key)
        out[key] = tone if tone in LINE_TONES_V6 else 'meta'
    crumb = source.get('crumb')
    out['crumb'] = crumb if crumb in CRUMBS_V6 else ''
    out['artDim'] = source.get('artDim') is True
    out['holdMarker'] = source.get('holdMarker') is True     # [r3.1] section 19.10
    out['paused'] = source.get('playing') is False           # [r3.1] a paused Home cover (cc_art_image_opa)
    buttons = []
    raw_buttons = source.get('buttons') if isinstance(source.get('buttons'), list) else []
    for slot in range(4):
        raw = raw_buttons[slot] if slot < len(raw_buttons) and isinstance(raw_buttons[slot], dict) else {}
        label = _text(raw.get('label'), BUTTON_LABEL_CAPACITY)
        lit = raw.get('lit') if raw.get('lit') in ('on', 'off') else None
        color = _int(raw.get('color'))
        buttons.append({'label': label, 'enabled': raw.get('enabled') is True, 'icon': _icon(raw, label),
                        'lit': lit, 'color': color if 0 <= color <= 0xFFFFFF else 0})
    out['buttons'] = buttons
    ring = source.get('ring') if isinstance(source.get('ring'), dict) else {}
    index, count = _int(ring.get('index')), _int(ring.get('count'))
    first_sent = 'first' in ring
    first = _int(ring.get('first')) if first_sent else window_first(index, count)
    relative = first_sent or not first   # section 4: colours and mask relative to an implicit 0 only
    unavailable = _int(ring.get('unavailable')) if relative else 0
    colors = ring.get('colors') if relative and isinstance(ring.get('colors'), list) else []
    if out['layout'] == 'upnext':
        unavailable = 0                  # section 4.4 (P5-R24): stripped on upnext
    out['ring'] = {'style': ring.get('style', 'off'), 'index': index, 'count': count, 'first': first,
                   'unavailable': unavailable, 'colors': [_int(c) for c in colors]}
    return out


def _v6_text(value, capacity):
    """cc_json_text: a str without control characters, cut at the last whole code point within capacity
    bytes; None when invalid (a non-string, or a character below U+0020, or a lone surrogate)."""
    if not isinstance(value, str) or any(ord(c) < 0x20 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        return None
    out, used = [], 0
    for char in value:
        size = len(char.encode('utf-8'))
        if used + size > capacity:
            break
        out.append(char)
        used += size
    return ''.join(out)


def _wire_int(value, lo, hi):
    return value if type(value) is int and lo <= value <= hi else None


def v6_parse(frame):
    """Presentation 6 (PRESENTATION_V5.md section 19) as ``cc_parse_frame`` reads it: (stored, invalid).

    ``stored``: layout, ringStyle, ringKelvin (0 unless bri / ctemp), valueUnit ('%' unless lightsbig),
    prevTitle / nextTitle ('' unless scenes) and the four button icons. ``invalid``: the presentation-6 reasons
    the knob rejects the frame for (an unknown layout / style / icon / unit token, a clusters ring outside
    1 <= count <= 20 or index >= count, a missing ring.kelvin on bri / ctemp, a ring.kelvin that is not an int
    2200..6500 on any style, a prevTitle / nextTitle that is not valid text). Every other field follows the
    presentation-5 rules (device.v5_parse); this reads only what presentation 6 adds."""
    invalid = []
    source = frame if isinstance(frame, dict) else {}
    layout = source.get('layout', LEGACY_LAYOUT.get(source.get('mode'), 'nowPlaying'))
    if layout not in ALL_LAYOUTS:
        invalid.append('layout')
    ring = source.get('ring') if isinstance(source.get('ring'), dict) else {}
    style = ring.get('style')
    if style not in ALL_RING_STYLES:
        invalid.append('ring.style')
    index, count = _wire_int(ring.get('index'), 0, 65535), _wire_int(ring.get('count'), 0, 65535)
    if style == 'clusters' and (count is None or index is None or not 1 <= count <= CLUSTERS_MAX or index >= count):
        invalid.append('clusters')
    if style == 'marker' and (count is None or index is None or count < 1 or index >= count):
        invalid.append('marker')   # section 19.9
    if style == 'queue' and (count is None or index is None or count < 1 or index >= count):
        invalid.append('queue')    # [r3.1] section 19.10
    ring_now = -1                  # [r3.1] ring.now: kept on the queue ring (the v5 Up next mirror keeps its own)
    if style == 'queue' and 'now' in ring:
        now = ring['now']
        if type(now) is int and count is not None and -1 <= now <= count - 1:
            ring_now = now
        else:
            invalid.append('ring.now')
    kelvin = 0
    if 'kelvin' in ring:
        value = _wire_int(ring['kelvin'], KELVIN_MIN, KELVIN_MAX)
        if value is None:
            invalid.append('ring.kelvin')
        elif style in ('bri', 'ctemp'):
            kelvin = value
    elif style in ('bri', 'ctemp'):
        invalid.append('ring.kelvin missing')
    unit = '%'
    if 'valueUnit' in source:
        if source['valueUnit'] not in VALUE_UNITS:
            invalid.append('valueUnit')
        elif layout == 'lightsbig':
            unit = source['valueUnit']
    titles = {}
    for key in ('prevTitle', 'nextTitle'):
        text = ''
        if key in source:
            text = _v6_text(source[key], TITLE_V6_CAPACITY)
            if text is None:
                invalid.append(key)
                text = ''
        titles[key] = text if layout == 'scenes' else ''
    crumb = ''
    if 'crumb' in source:
        if source['crumb'] in CRUMBS_V6:
            crumb = source['crumb']
        else:
            invalid.append('crumb')   # section 19.9: a token, invalid rejects
    hold_marker = False            # [r3.1] section 19.10: a bool, every layout
    if 'holdMarker' in source:
        if type(source['holdMarker']) is bool:
            hold_marker = source['holdMarker']
        else:
            invalid.append('holdMarker')
    for key in ('metaTone', 'statusTone'):
        if key in source and source[key] not in LINE_TONES_V6:
            invalid.append(key)
    feedback = source.get('feedback') if isinstance(source.get('feedback'), dict) else {}
    if 'moment' in feedback and feedback['moment'] not in MOMENTS_V6:
        invalid.append('feedback.moment')
    icons = []
    buttons = source.get('buttons') if isinstance(source.get('buttons'), list) else []
    for raw in buttons[:4]:
        icon = raw.get('icon', '') if isinstance(raw, dict) else ''
        if icon not in ALL_ICONS:
            invalid.append('icon')
        icons.append(icon)
    stored = {'layout': layout, 'ringStyle': style, 'ringKelvin': kelvin, 'valueUnit': unit, **titles,
              'icons': icons, 'crumb': crumb, 'holdMarker': hold_marker, 'ringNow': ring_now}
    return stored, invalid


def _run(scene, role, label, line, row, ink, limit, tracking=None):
    tracking = label.tracking if tracking is None else tracking
    pen = label.x + _c_half(label.width - text_width(line, label.size, tracking))
    scene.items.append(TextRun(role, line, pen, label.baseline + row * label.pitch, label.size, ink,
                               tracking, (label.x, label.width), limit, label.shadow))


def _label(scene, role, label, text, ink):
    """showText: fit the text to the label's per-line chord and centre each line in the box."""
    if not text:
        return
    lines, limits = fit_label(label, text, scene.crumb)
    for row, line in enumerate(lines):
        _run(scene, role, label, line, row, ink, limits[row])


def _heading(scene, text):
    drawn, tracking, limit = fit_heading(text)
    if drawn:
        _run(scene, 'heading', HEADING, drawn, 0, SECONDARY_RGB, limit, tracking)


@lru_cache(maxsize=1)
def firmware_sizes():
    """Section 9.1: token -> the sizes the knob has a mask for (icons.json ``firmwareSizes``, written
    together with src/cc_icons.cpp by export_handoff_icons.cjs). A token without a mask at a size is
    hidden there (cc_icon() returns nullptr), e.g. every token but play/pause/list/win/tracks at 26 px."""
    try:
        data = json.loads((ICON_DIR / 'icons.json').read_text(encoding='utf-8'))
        return {name: frozenset(sizes) for name, sizes in data['firmwareSizes'].items()}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def knob_has_mask(name, size):
    return bool(name) and size in firmware_sizes().get(name, ())


def button_look(slot, button, layout, crumb=''):
    """Section 5.2: (tone, glyph name, ink RGB) of one button; glyph '' when none is drawn."""
    tone = button_tone_v5(slot, button['icon'], button['enabled'], button['lit'], layout)
    if tone == 'none':
        return tone, '', (0, 0, 0)
    ink = button_ink_v5(slot, button['icon'], button['enabled'], button['lit'], button['color'], layout, crumb)
    return tone, LIKED_GLYPH if tone == 'liked' else button['icon'], _rgb(ink)


def _footer(scene, frame):
    scene.hold_tick = frame.get('holdMarker') is True     # [r3.1] the hold tick shows with the footer
    for slot, button in enumerate(frame['buttons']):
        tone, name, ink = button_look(slot, button, frame['layout'], frame.get('crumb', ''))
        if knob_has_mask(name, FOOTER_ICON):
            scene.items.append(IconRun('footer', name, FOOTER_X[slot] - FOOTER_ICON // 2, FOOTER_TOP, FOOTER_ICON, ink))


def _idle_row(scene, frame):
    for slot, button in enumerate(frame['buttons']):
        tone, name, ink = button_look(slot, button, frame['layout'], frame.get('crumb', ''))
        if tone == 'none':
            continue
        centre = IDLE_X[slot]
        if knob_has_mask(name, IDLE_ICON):           # a token without a 26 px mask is hidden (9.1)
            scene.items.append(IconRun('idle-icon', name, centre - IDLE_ICON // 2, IDLE_TOP, IDLE_ICON, ink))
        _label(scene, 'idle-word', IDLE_WORDS[slot], button['label'], ink)


def _status(scene, frame):
    _label(scene, 'status', STATUS, frame['status'], _rgb(TONE_INK[frame['statusTone']]))


def _volume(scene, frame, unit='%'):
    """The reveal: caption, 48 px digits and the 22 px unit ('%'; presentation 6 lightsbig: valueUnit)."""
    _label(scene, 'caption', VOLUME_CAPTION, frame['volumeCaption'] or frame['title'], SECONDARY_RGB)
    digits = volume_digits(frame['value'])
    if not digits:
        return
    digits_width = text_width(digits, 48, DIGIT_TRACKING)
    percent_width = text_width(unit, 22)
    left = CENTRE - (digits_width + DIGIT_GAP + percent_width + 1) // 2
    scene.items.append(TextRun('digits', digits, left, DIGITS_BASELINE, 48, INK_RGB, DIGIT_TRACKING, shadow=True))
    scene.items.append(TextRun('percent', unit, left + digits_width + DIGIT_GAP, DIGITS_BASELINE, 22,
                               SECONDARY_RGB, shadow=True))


def _lights_line(scene, frame):
    """Presentation 6: the 12 px line of lights / lightsbig is ``meta`` in its metaTone (the STATUS label)."""
    _label(scene, 'status', STATUS, frame['meta'], _rgb(TONE_INK[frame['metaTone']]))


def _scenes(scene, frame):
    """Presentation 6 (section 19.4): prev / current / next and the meta line."""
    _label(scene, 'prev', SCENE_PREV, frame['prevTitle'], META_RGB)
    _label(scene, 'title', SCENE_TITLE, frame['title'], _rgb(TONE_INK[frame['titleTone']]))
    _label(scene, 'next', SCENE_NEXT, frame['nextTitle'], META_RGB)
    _label(scene, 'meta', SCENE_META, frame['meta'], _rgb(TONE_INK[frame['metaTone']]))


def _list(scene, frame):
    _label(scene, 'title', LIST_TITLE, frame['title'], _rgb(TONE_INK[frame['titleTone']]))
    _label(scene, 'subtitle', LIST_SUBTITLE, frame['subtitle'], SECONDARY_RGB)
    _label(scene, 'meta', LIST_META, frame['meta'], _rgb(TONE_INK[frame['metaTone']]))


def _tracks(scene, frame):
    _label(scene, 'title', TRACKS_TITLE, frame['title'], _rgb(TONE_INK[frame['titleTone']]))
    ring = frame['ring']
    selected = ring['index'] if ring['index'] <= 2 else 1   # renderTracks: 0 Prev, 1 Neutral, 2 Next
    no_prev = bool(ring['unavailable'] & 1)
    # Desk Dial r3.1: the prev / dot / next row belongs to the 3-position transport ring only; any other ring
    # (the whole-queue Tracks sends a selection ring) hides it, as renderTracks does.
    positions = ('prev', DOT_GLYPH, 'next') if ring['style'] == 'transport' else ()
    for position, name in enumerate(positions):
        ink = INK_RGB if position == selected else META_RGB
        if position == 0 and no_prev:
            ink = DISABLED_GLYPH_RGB
        scene.items.append(IconRun('track-position', name, TRACK_ICON_X[position], TRACK_ICON_TOP, TRACK_ICON, ink))
    _label(scene, 'subtitle', TRACKS_SUBTITLE, frame['subtitle'], SECONDARY_RGB)
    _label(scene, 'meta', TRACKS_META, frame['meta'], _rgb(TONE_INK[frame['metaTone']]))


def seek_time(frame):
    """Section 4.3: mmss(ring.index) of a lap ring on the Seek layout, else '' (no time)."""
    ring = frame['ring']
    return mmss(ring['index']) if ring['style'] == 'lap' else ''


def _seek(scene, frame):
    """Section 8.6.8: the 14 px caption is the song (title), the 48 px tabular time comes from the
    ring, the 14 px line is the meta (#A6A6A6 for tone meta, P5-R2)."""
    _label(scene, 'caption', SEEK_CAPTION, frame['title'], SECONDARY_RGB)
    time = seek_time(frame)
    if time:
        _label(scene, 'seek-time', SEEK_TIME, time, INK_RGB)
    tone = frame['metaTone']
    _label(scene, 'line', SEEK_LINE, frame['meta'], SECONDARY_RGB if tone == 'meta' else _rgb(TONE_INK[tone]))


def selected_closed(frame):
    """True when the selected ring entry carries the unavailable (closed) bit."""
    ring = frame['ring']
    bit = ring['index'] - ring['first']
    return 0 <= bit < RING_WINDOW and bool(ring['unavailable'] >> bit & 1)


def tile_colours(frame):
    """Section 5.3: (tile RGB, initial RGB) of the Windows letter tile: sat() of the selected entry's
    accent with a #FFFFFF initial when it has one that sat() does not reduce to WARM, else V4's
    #444 tile with a #F2F2F2 initial."""
    ring = frame['ring']
    k = ring['index'] - ring['first']
    accent = ring['colors'][k] if 0 <= k < len(ring['colors']) else 0
    s = sat_rgb(accent) if accent else None
    return (_rgb(s), (255, 255, 255)) if s is not None else (TILE_RGB, _rgb(TILE_INITIAL))


def tile_initial(subtitle, artwork2=True):
    """The letter tile's initial: the first code point, ASCII a-z upper-cased (cc5.3 and later).

    ``artwork2=False`` keeps the pre-cc5.3 as-is initial (a cc5.2 knob)."""
    initial = subtitle[:1]
    return initial.upper() if artwork2 and 'a' <= initial <= 'z' else initial


def _windows(scene, frame, window_icon, artwork2=True):
    opacity = CLOSED_OPACITY if selected_closed(frame) else 1.0
    x, y, size = TILE_BOX
    if window_icon:
        scene.window_icon_box = (x, y, size, opacity)
    elif frame['subtitle']:                 # renderWindows: no subtitle, no tile
        fill, initial_ink = tile_colours(frame)
        scene.items.append(BoxRun('tile', x, y, size, fill, opacity))
        # The tile and its letter fade together over black (group opacity).
        ink = tuple(round(c * opacity) for c in initial_ink)
        _run(scene, 'tile-initial', TILE_INITIAL_LABEL, tile_initial(frame['subtitle'], artwork2), 0, ink,
             TILE_INITIAL_LABEL.width)
    _label(scene, 'subtitle', WINDOWS_APP, frame['subtitle'], SECONDARY_RGB)
    _label(scene, 'title', WINDOWS_TITLE, frame['title'], _rgb(TONE_INK[frame['titleTone']]))
    _label(scene, 'meta', WINDOWS_META, frame['meta'], _rgb(TONE_INK[frame['metaTone']]))


def compose(frame, *, window_icon=False, artwork2=True, native=False):
    """The settled scene for a wire frame, or the offline screen for ``None`` (section 8.10;
    ``native``: after the first native input, "Knob controls still work").

    ``window_icon``: an app icon replaces the Windows letter tile. ``artwork2=False``: the pre-cc5.3
    letter tile (initial as-is)."""
    if frame is None:
        scene = Scene('offline')
        _label(scene, 'title', OFFLINE_TITLE_LABEL, OFFLINE['title'], INK_RGB)
        text, label = OFFLINE['native' if native else 'subtitle'], OFFLINE_SUB_LABEL
        if native and text_width(text, _font_key(label.size), 0) > label.line_width(ink_rows(text, label.size), 0):
            label = OFFLINE_NATIVE_LABEL        # K1 8.10 erratum R-c: one line at -1 px tracking
        _label(scene, 'subtitle', label, text, SECONDARY_RGB)
        return scene
    f = normalize(frame)
    layout, has_key = f['layout'], bool(f['artKey'])
    scene = Scene(layout, art_dim=f['artDim'],
                  art_paused=f['paused'] and layout in ('nowPlaying', 'volume', 'idle', 'notice'))
    # Presentation 6 (section 19.9): a crumb replaces the flat heading. r3.1 (2026-09-29): the crumb shows in
    # the idle icon view too (Music idle keeps MUSIC; Home idle is sent without one), as the r3.1 prototype.
    if f['crumb']:
        scene.crumb = f['crumb']
    else:
        _heading(scene, f['heading'])       # the heading row is drawn on every layout when sent
    if layout == 'nowPlaying':
        scene.art = has_key
        _label(scene, 'title', HOME_TITLE, f['title'], INK_RGB)
        _label(scene, 'subtitle', HOME_ARTIST, f['subtitle'], SECONDARY_RGB)
        _status(scene, f)
        _footer(scene, f)
    elif layout == 'volume':
        over_idle = f['restLayout'] == 'idle'
        scene.art = has_key and not over_idle
        _volume(scene, f)
        _status(scene, f)
        if not over_idle:
            _footer(scene, f)
    elif layout == 'idle':
        _idle_row(scene, f)
    elif layout == 'tracks':
        scene.art = has_key
        _tracks(scene, f)
        _footer(scene, f)
    elif layout == 'seek':
        scene.art = has_key
        _seek(scene, f)
        _footer(scene, f)
    elif layout == 'windows':
        _windows(scene, f, window_icon, artwork2)
        _footer(scene, f)
    elif layout == 'lights':                # presentation 6: the Home text drawing, no art
        _label(scene, 'title', HOME_TITLE, f['title'], INK_RGB)
        _label(scene, 'subtitle', HOME_ARTIST, f['subtitle'], SECONDARY_RGB)
        _lights_line(scene, f)
        _footer(scene, f)
    elif layout == 'lightsbig':             # presentation 6: the reveal with valueUnit, no art
        _volume(scene, f, 'K' if f['valueUnit'] == 'K' else '%')
        _lights_line(scene, f)
        _footer(scene, f)
    elif layout == 'scenes':                # presentation 6: the scenes list, no art
        _scenes(scene, f)
        _footer(scene, f)
    else:  # recent, explorer, upnext, notice
        scene.art = has_key and layout in ART_LAYOUTS
        _list(scene, f)
        _footer(scene, f)
    # r4 render speed (cc_display.cpp, MOTION.md 4): the knob hides these twins while no cover is shown; a black
    # shadow over black draws nothing, so the mirror keeps them (identical pixels).
    return scene


# --------------------------------------------------------------------------
# Painting
# --------------------------------------------------------------------------
@lru_cache(maxsize=128)
def icon_mask(name, size):
    """A8 mask of a handoff icon, or None for an empty or unknown name."""
    path = ICON_DIR / f'{name}-{size}.png'
    if not name or not path.is_file():
        return None
    with Image.open(path) as source:
        return source.convert('RGBA').getchannel('A')


def artwork_image(artwork):
    """The 240 px cover: wire RGB565 bytes or a 120 px image doubled once, like the knob."""
    if artwork is None:
        return None
    if isinstance(artwork, (bytes, bytearray, memoryview)):
        if len(artwork) != ART_BYTES:
            return None  # a size mismatch is never fatal (contract section 7)
        artwork = Image.frombytes('RGB', (ART_SIZE, ART_SIZE), bytes(artwork), 'raw', 'BGR;16')
    image = artwork.convert('RGB')
    if image.size == (ART_SIZE, ART_SIZE):
        return image.resize((SIZE, SIZE), Image.Resampling.NEAREST)
    if image.size != (SIZE, SIZE):
        return image.resize((SIZE, SIZE), Image.Resampling.BILINEAR)
    return image


@lru_cache(maxsize=8)
def _decoded_cover(jpeg):
    try:
        with Image.open(BytesIO(jpeg)) as source:
            # cc_jpeg_validate: a baseline JPEG of exactly 240 x 240, else no art.
            if (source.format != 'JPEG' or source.size != (COVER_SIZE, COVER_SIZE)
                    or source.info.get('progressive') or source.info.get('progression')):
                return None
            rgb = source.convert('RGB')
    except Exception:
        return None
    return Image.frombytes('RGB', rgb.size, rgb565le_rounded(rgb.tobytes()), 'raw', 'BGR;16')


def cover_image(jpeg):
    """The artwork2 cover as the knob shows it: the JPEG decoded (Pillow), quantised to
    RGB565 with rounding (as cc_jpeg converts TJpgDec's RGB888) and drawn at 240 px
    without any upscale. None for anything the knob would refuse to decode."""
    if not isinstance(jpeg, (bytes, bytearray, memoryview)) or not 0 < len(jpeg) <= COVER_MAX_BYTES:
        return None
    image = _decoded_cover(bytes(jpeg))
    return image.copy() if image is not None else None  # the cached decode is never handed out


def icon_image(payload):
    """A 2048-byte RGB565 LE artwork2 icon decoded to 32 x 32 RGB, or None."""
    if not isinstance(payload, (bytes, bytearray, memoryview)) or len(payload) != ICON_BYTES:
        return None
    return Image.frombytes('RGB', (ICON_SIZE, ICON_SIZE), bytes(payload), 'raw', 'BGR;16')


def _frame_key(frame, name, pattern=None):
    value = frame.get(name) if isinstance(frame, dict) else None
    if not isinstance(value, str) or not value or (pattern is not None and not pattern.fullmatch(value)):
        return ''
    return value


def _artwork2_icon(frame, window_icon):
    """The tile icon the knob draws: the payload the frame's iconKey names, else None.

    ``window_icon`` is the 2048-byte payload (or IconWorker's RGBA image, which is turned into that
    payload). A payload whose key is not the frame's iconKey is never drawn: the knob shows the
    letter tile then."""
    key = _frame_key(frame, 'iconKey', _ICON_KEY)
    if not key or window_icon is None:
        return None
    if isinstance(window_icon, Image.Image):
        try:
            payload_key, payload = icon_payload(window_icon)
        except ArtworkError:
            return None
    elif isinstance(window_icon, (bytes, bytearray, memoryview)):
        payload = bytes(window_icon)
        payload_key = icon_key(payload)
    else:
        return None
    return icon_image(payload) if payload_key == key else None


def _artwork2_cover(frame, artwork):
    """artwork2 cover: JPEG bytes whose key is the frame's artKey (a stale cover is never
    shown); an image (a v1-store cover) as the v1 mirror does."""
    if isinstance(artwork, (bytes, bytearray, memoryview)):
        data = bytes(artwork)
        return cover_image(data) if data and cover_key(data) == _frame_key(frame, 'artKey') else None
    return artwork_image(artwork)


def _scaled(mask, opacity):
    return mask if opacity >= 1 else mask.point(lambda a: round(a * opacity))


def _walk(run, k, draw_glyph, draw_placeholder):
    """lv_draw_label's pen walk at scale k: glyphs with a box are drawn, an unknown one as a frame."""
    pen, text = run.x, run.text
    top = run.baseline - ASCENT[run.size]
    for i, char in enumerate(text):
        step = advance(char, run.size, text[i + 1] if i + 1 < len(text) else '')
        cp = ord(char)
        if not is_marker(cp):
            found = glyph(cp, run.size)
            if found is None:
                draw_placeholder(pen, top, step)
            elif found[1] and found[2]:
                draw_glyph(pen, char)
        if step > 0:
            pen += step + run.tracking


def _run_box(run, k, dy=0):
    """Device-pixel box (x0, y0, x1, y1) that holds a run's glyphs painted at scale k."""
    px = PX[run.size]
    x0 = math.floor((run.x - px) * k)
    x1 = math.ceil((run.x + run.width + 2 * px) * k)
    y0 = math.floor((run.baseline - LINE_HEIGHT[run.size] - px // 2 + dy) * k)
    y1 = math.ceil((run.baseline + px + dy) * k)
    return x0, y0, x1, y1


def _paint_shadow(image, run, k):
    """The run's text-shadow twin: black at 204/255, one knob pixel lower, as a masked paste over the
    run's own box (never alpha_composite)."""
    x0, y0, x1, y1 = _run_box(run, k, 1)
    mask = Image.new('L', (x1 - x0, y1 - y0), 0)
    draw = ImageDraw.Draw(mask)
    face = _face(run.size, k)

    def glyph_(pen, char):
        draw.text((pen * k - x0, (run.baseline + 1) * k - y0), char, font=face, fill=255, anchor='ls')

    def placeholder(pen, top, step):
        (gx, gw), (gy, gh) = _span(pen, step, k), _span(top + 1, LINE_HEIGHT[run.size], k)
        draw.rectangle((gx - x0, gy - y0, gx - x0 + gw - 1, gy - y0 + gh - 1), outline=255, width=max(1, round(k)))
    _walk(run, k, glyph_, placeholder)
    image.paste((0, 0, 0), (x0, y0), mask.point(lambda v: (v * SHADOW_OPACITY + 127) // 255))


def _paint_text(draw, run):
    """lv_draw_label's pen walk: glyphs with a box are drawn, an unknown one as a 1 px frame."""
    face = _face(run.size)

    def glyph_(pen, char):
        draw.text((pen, run.baseline), char, font=face, fill=run.ink, anchor='ls')

    def placeholder(pen, top, step):
        draw.rectangle((pen, top, pen + step - 1, top + LINE_HEIGHT[run.size] - 1), outline=run.ink)
    _walk(run, 1, glyph_, placeholder)


def _overlay(image):
    layer = Image.new('RGBA', image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.ellipse((CENTRE - 120, CENTRE - 120, CENTRE + 120, CENTRE + 120), outline=(255, 60, 40, 97), width=8)
    guide = (53, 208, 192, 255)
    for step in range(0, 360, 4):  # dashed r104 circle
        draw.arc((CENTRE - SAFE_RADIUS, CENTRE - SAFE_RADIUS, CENTRE + SAFE_RADIUS, CENTRE + SAFE_RADIUS),
                 step, step + 2, fill=guide)
    for x in FOOTER_X:
        for y in range(146, 182, 4):
            draw.line((x, y, x, y + 1), fill=guide)
    draw.line((0, CENTRE, SIZE, CENTRE), fill=(53, 208, 192, 64))
    draw.line((CENTRE, 0, CENTRE, SIZE), fill=(53, 208, 192, 64))
    return Image.alpha_composite(image.convert('RGBA'), layer).convert('RGB')


def render_lcd(frame, artwork=None, window_icon=None, overlay=False, *, artwork2=False,
               scale=1.0, hires_cover=None, hires_icon=None, native=False):
    """240 px RGBA mirror of the knob LCD (alpha = the round glass).

    Without ``artwork2`` (a v1-only knob, or no knob): ``artwork`` is the pre-composited cover for
    ``frame['artKey']``: the 28,800 byte RGB565 LE wire image, its 120 px decode, or the 240 px
    preview; it is drawn only where the knob draws art. ``window_icon`` (an RGBA image) replaces
    the Windows letter tile.

    With ``artwork2`` (ARTWORK2.md section 7): ``artwork`` is the cover JPEG the frame's artKey
    names (decoded, RGB565-rounded, 240 px, never upscaled) and ``window_icon`` the 2048-byte icon
    payload the frame's iconKey names (an RGBA image is turned into that payload); it fills the
    tile at the tile's open or closed opacity. No usable icon: the letter tile. A key that does not
    match draws nothing, as on the knob.

    ``frame=None`` draws the firmware's offline screen (``native``: after native input).

    ``scale`` (floating knob, FLOATING_KNOB.md section 3): the image is ``lcd_pixels(scale)``
    square, painted directly at that size (never upscaled from 240). At any scale other than 1:

    * ``hires_cover``: the hi-res composited cover for the same artKey (an image, or the
      ``ArtworkResult.hires_jpeg`` bytes). It replaces the cover only where the knob would draw
      one; without it the 240 cover is resampled.
    * ``hires_icon``: the app's hi-res RGBA icon. It fills the Windows tile, also where the knob
      shows its letter tile; without it the tile uses the RGBA ``window_icon`` or the payload.
    * the debug ``overlay`` is not drawn.
    """
    k = _scale_factor(scale)
    hires_icon = hires_icon if k != 1 and isinstance(hires_icon, Image.Image) else None
    if artwork2:
        icon_pixels = _artwork2_icon(frame, window_icon)
        scene = compose(frame, window_icon=icon_pixels is not None or hires_icon is not None, artwork2=True,
                        native=native)
        cover = _artwork2_cover(frame, artwork) if scene.art else None
    else:
        icon_pixels = None
        scene = compose(frame, window_icon=window_icon is not None or hires_icon is not None, artwork2=False,
                        native=native)
        cover = artwork_image(artwork) if scene.art else None
    if k != 1:
        tile_icon = hires_icon
        if tile_icon is None and scene.window_icon_box:
            tile_icon = window_icon if isinstance(window_icon, Image.Image) else icon_pixels
        return _paint_scaled(scene, cover, tile_icon, k, hires_cover)
    if cover is not None:
        if scene.art_dim or scene.art_paused:
            factor = ART_DIM if scene.art_dim else ART_PAUSED
            cover = cover.point(lambda v: round(v * factor))
        image = cover.copy()
    else:
        image = Image.new('RGB', (SIZE, SIZE), 'black')
    draw = ImageDraw.Draw(image)
    if scene.window_icon_box:
        x, y, size, opacity = scene.window_icon_box
        if icon_pixels is not None:
            # The payload is already composited onto black (the tile's transparent background over
            # the black LCD); the tile group fades it as a whole.
            image.paste(icon_pixels if opacity >= 1 else icon_pixels.point(lambda v: round(v * opacity)), (x, y))
        else:
            icon = window_icon.convert('RGBA').resize((size, size), Image.Resampling.LANCZOS)
            image.paste(icon.convert('RGB'), (x, y), _scaled(icon.getchannel('A'), opacity))
    if scene.crumb:
        from control_center import crumb_arc
        crumb_arc.composite(image, scene.crumb)
    for item in scene.items:
        if isinstance(item, TextRun):
            if item.shadow:
                _paint_shadow(image, item, 1)
            _paint_text(draw, item)
        elif isinstance(item, IconRun):
            mask = icon_mask(item.name, item.size)
            if mask is not None:
                image.paste(item.ink, (item.x, item.y), _scaled(mask, item.opacity))
        elif isinstance(item, BoxRun):
            fill = tuple(round(c * item.opacity) for c in item.fill)
            draw.rectangle((item.x, item.y, item.x + item.size - 1, item.y + item.size - 1), fill=fill)
    if scene.hold_tick:                                   # [r3.1] section 19.10
        x, y, w, h = HOLD_TICK
        draw.rectangle((x, y, x + w - 1, y + h - 1), fill=HOLD_TICK_RGB)
    if overlay:
        image = _overlay(image)
    result = image.convert('RGBA')
    mask = Image.new('L', (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, SIZE - 1, SIZE - 1), fill=255)
    result.putalpha(mask)
    return result


# --------------------------------------------------------------------------
# Painting at scale k (floating knob; never used at k == 1)
# --------------------------------------------------------------------------
GLASS_SUPERSAMPLE = 4


def _scale_factor(scale):
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0:
        raise ValueError('scale must be a positive finite number')
    return scale


def lcd_pixels(scale=1.0):
    """Edge in device pixels of ``render_lcd(..., scale=scale)``: 240 at scale 1, else round(240 * scale)."""
    k = _scale_factor(scale)
    return SIZE if k == 1 else max(1, round(SIZE * k))


def _span(start, length, k):
    """Device pixels (first, count) of the knob span [start, start + length) at scale k."""
    first = round(start * k)
    return first, max(1, round((start + length) * k) - first)


@lru_cache(maxsize=256)
def _hires_mask_source(name, size, factor):
    path = HIRES_ICON_DIR / f'{name}-{size}@{factor}x.png'
    if not path.is_file():
        return None
    with Image.open(path) as source:
        mask = source.convert('RGBA').getchannel('A')
    return mask if mask.size == (size * factor, size * factor) else None


@lru_cache(maxsize=256)
def scaled_icon_mask(name, size, pixels):
    """A8 mask of icon ``name`` (knob size ``size``) at ``pixels`` square, or None.

    The source is the nearest export at or above the target (the shipped 1x mask, then the @2x and
    @3x exports), downsampled with LANCZOS when the scale is fractional; above @3x the @3x export is
    resampled up.
    """
    base = icon_mask(name, size)
    if base is None or pixels <= 0:
        return None
    candidates = [(1, base)] + [(factor, _hires_mask_source(name, size, factor)) for factor in HIRES_ICON_FACTORS]
    candidates = [(factor, mask) for factor, mask in candidates if mask is not None]
    source = next((mask for factor, mask in candidates if size * factor >= pixels), candidates[-1][1])
    return source if source.width == pixels else source.resize((pixels, pixels), Image.Resampling.LANCZOS)


@lru_cache(maxsize=8)
def _glass_mask(pixels):
    """Anti-aliased round glass (4x supersampled ellipse, box-reduced)."""
    big = pixels * GLASS_SUPERSAMPLE
    mask = Image.new('L', (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    return mask.reduce(GLASS_SUPERSAMPLE)


@lru_cache(maxsize=4)
def _decoded_hires_cover(data):
    try:
        with Image.open(BytesIO(data)) as source:
            return source.convert('RGB')
    except Exception:
        return None


def hires_cover_image(value):
    """An RGB image of a hi-res cover given as an image or as encoded (JPEG) bytes, or None."""
    if isinstance(value, Image.Image):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)) and 0 < len(value) <= 4 * 1024 * 1024:
        return _decoded_hires_cover(bytes(value))
    return None


def _fit_square(icon, pixels):
    """An RGBA icon fitted into a pixels-square box (aspect kept, centred, LANCZOS)."""
    icon = icon.convert('RGBA')
    if icon.size == (pixels, pixels):
        return icon
    if icon.width == icon.height:
        return icon.resize((pixels, pixels), Image.Resampling.LANCZOS)
    fitted = ImageOps.contain(icon, (pixels, pixels), Image.Resampling.LANCZOS)
    tile = Image.new('RGBA', (pixels, pixels), (0, 0, 0, 0))
    tile.paste(fitted, ((pixels - fitted.width) // 2, (pixels - fitted.height) // 2))
    return tile


def _paint_text_scaled(draw, run, k):
    """_paint_text at scale k: the knob's pen walk, painted at pen * k with the font at size * k."""
    face = _face(run.size, k)

    def glyph_(pen, char):
        draw.text((pen * k, run.baseline * k), char, font=face, fill=run.ink, anchor='ls')

    def placeholder(pen, top, step):
        x0, width = _span(pen, step, k)
        y0, height = _span(top, LINE_HEIGHT[run.size], k)
        draw.rectangle((x0, y0, x0 + width - 1, y0 + height - 1), outline=run.ink, width=max(1, round(k)))
    _walk(run, k, glyph_, placeholder)


def _paint_scaled(scene, cover, tile_icon, k, hires_cover):
    """The scene painted at round(240 * k) px (k != 1)."""
    pixels = lcd_pixels(k)
    if cover is not None:
        source = hires_cover_image(hires_cover) or cover
        image = source.convert('RGB')
        if image.size != (pixels, pixels):
            image = image.resize((pixels, pixels), Image.Resampling.LANCZOS)
        if scene.art_dim or scene.art_paused:
            factor = ART_DIM if scene.art_dim else ART_PAUSED
            image = image.point(lambda v: round(v * factor))
    else:
        image = Image.new('RGB', (pixels, pixels), 'black')
    draw = ImageDraw.Draw(image)
    if scene.crumb:
        from control_center import crumb_arc
        layer = crumb_arc.layer_rgba(scene.crumb).resize((pixels, pixels), Image.Resampling.LANCZOS)
        image.paste(layer.convert('RGB'), (0, 0), layer.getchannel('A'))
    if scene.window_icon_box and tile_icon is not None:
        x, y, size, opacity = scene.window_icon_box
        (x0, box), (y0, _) = _span(x, size, k), _span(y, size, k)
        icon = _fit_square(tile_icon, box)
        # Over the black LCD: the same c * a * opacity the knob's payload (composited onto black,
        # faded as a group) and the v1 RGBA paste both produce.
        image.paste(icon.convert('RGB'), (x0, y0), _scaled(icon.getchannel('A'), opacity))
    for item in scene.items:
        if isinstance(item, TextRun):
            if item.shadow:
                _paint_shadow(image, item, k)
            _paint_text_scaled(draw, item, k)
        elif isinstance(item, IconRun):
            mask = scaled_icon_mask(item.name, item.size, max(1, round(item.size * k)))
            if mask is not None:
                image.paste(item.ink, (round(item.x * k), round(item.y * k)), _scaled(mask, item.opacity))
        elif isinstance(item, BoxRun):
            fill = tuple(round(c * item.opacity) for c in item.fill)
            (x0, width), (y0, height) = _span(item.x, item.size, k), _span(item.y, item.size, k)
            draw.rectangle((x0, y0, x0 + width - 1, y0 + height - 1), fill=fill)
    if scene.hold_tick:                                   # [r3.1] section 19.10
        x, y, w, h = HOLD_TICK
        (x0, width), (y0, height) = _span(x, w, k), _span(y, h, k)
        draw.rectangle((x0, y0, x0 + width - 1, y0 + max(1, height) - 1), fill=HOLD_TICK_RGB)
    result = image.convert('RGBA')
    result.putalpha(_glass_mask(pixels))
    return result


# --------------------------------------------------------------------------
# Knob font tables (generated; do not edit by hand)
# --------------------------------------------------------------------------
# base64(zlib(JSON)) of the metrics the firmware measures text with, extracted from
# firmware/src/fonts/cc_font_{12,14,16,22,48,48t}.c (gen_lvgl_font.py) and LVGL 9.0.0
# src/font/lv_font_montserrat_{12,14,16,22}.c:
#   fonts[N].cc[cp] / fonts[N].ascii[cp - 0x20] = [adv_w (1/16 px), box_w, box_h, ofs_y]
#   fonts[N].kern = the built-in's class-pair values (row = left class - 1, `columns` wide),
#   kern_scale; left[cp - 0x20] / right[...] = kern classes of U+0020-007E (right also
#   U+00B0, U+2022, the built-in's other text glyphs); line_height / base_line.
#   fonts["48t"] is cc_font_48t, the tabular Seek time (no fallback, no kerning).
# Regenerate: python tests/test_cc_lcd_preview.py --print-font-metrics
# (tests/test_cc_lcd_preview.py checks it against the firmware sources when present).
_KNOB_FONT_METRICS = """
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
"""
