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
IDLE_X = (51, 97, 143, 189)
IDLE_TOP, IDLE_ICON, IDLE_COLUMN = 100, 26, 60
TRACK_ICON_X = (72, 112, 152)          # left edges of the 16 px prev / dotfill / next boxes
TRACK_ICON_TOP, TRACK_ICON = 88, 16
TILE_BOX = (104, 42, 32)                # x, y, size
DIGIT_GAP = 2
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

    @property
    def top(self):
        return self.baseline - ASCENT[self.size]

    @property
    def pitch(self):
        return LINE_HEIGHT[self.size] + LINE_SPACE

    @property
    def centre(self):
        return self.x + self.width // 2

    def line_width(self, ink, row=0):
        """cc_display lineWidth: the box width clamped to the chord of the ink rows on this row."""
        if ink is None:
            half = CENTRE                    # nothing inked: the chord never binds
        else:
            baseline = self.baseline + row * self.pitch
            half = safe_half(baseline + ink[0], baseline + ink[1], self.radius)
        return min(max(0, 2 * (half - abs(self.centre - CENTRE))), self.width)


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


def fit_label(label, text):
    """showText: the drawn lines of a label and the width each line was fitted to."""
    ink = ink_rows(text, label.size)
    width1 = label.line_width(ink, 0)
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
STATUS = Label(40, 160, 145, 12)                                # top 134
VOLUME_CAPTION = Label(35, 170, 66, 14, shadow=True)            # top 52
DIGITS_BASELINE = 116                                           # top 76, 48/46; '%' shares it
IDLE_WORD_BASELINE = 145                                        # top 134 (icon 100..126, gap 8)
LIST_TITLE = Label(35, 170, 73, 22, lines=2, shadow=True)       # top 52
LIST_SUBTITLE = Label(35, 170, 120, 14, shadow=True)            # top 106
LIST_META = Label(35, 170, 138, 12)                             # top 127
TRACKS_TITLE = Label(35, 170, 75, 22, shadow=True)              # top 54, single line
TRACKS_SUBTITLE = Label(35, 170, 124, 14, shadow=True)          # top 110
TRACKS_META = Label(35, 170, 141, 12)                           # top 130
SEEK_CAPTION = Label(35, 170, 66, 14, shadow=True)              # top 52
SEEK_TIME = Label(0, 240, SEEK_TIME_BASELINE, SEEK_FONT, tracking=DIGIT_TRACKING, shadow=True)  # top 76, 48/46
SEEK_LINE = Label(35, 170, 142, 14)                             # top 128, 14/18
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
ICON_NAMES = frozenset(name for name in ICONS if name)   # every wire token (section 9.1)
LIKED_GLYPH = 'heartfill'                                # [r2.2] tone liked (section 5.2 row 4)
DOT_GLYPH = 'dotfill'                                    # the Tracks position-row centre
ART_LAYOUTS = ('nowPlaying', 'volume', 'recent', 'tracks', 'seek', 'explorer', 'upnext')   # section 8.4


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
    window_icon_box: tuple = ()  # (x, y, size, opacity) for a supplied app icon
    items: list = field(default_factory=list)

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
    out['artKey'] = _text(source.get('artKey'))
    icon = source.get('iconKey')
    # artwork2 section 6: a malformed iconKey is stripped (the letter tile shows).
    out['iconKey'] = icon if isinstance(icon, str) and _ICON_KEY.fullmatch(icon) else ''
    layout = source.get('layout')
    out['layout'] = layout if layout in LAYOUTS else LEGACY_LAYOUT.get(out['mode'], 'nowPlaying')
    rest = source.get('restLayout')
    out['restLayout'] = rest if rest in REST_LAYOUTS else 'nowPlaying'
    tone = source.get('titleTone')
    out['titleTone'] = tone if tone in TITLE_TONES else 'ink'
    for key in ('metaTone', 'statusTone'):
        tone = source.get(key)
        out[key] = tone if tone in LINE_TONES else 'meta'
    out['artDim'] = source.get('artDim') is True
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


def _run(scene, role, label, line, row, ink, limit, tracking=None):
    tracking = label.tracking if tracking is None else tracking
    pen = label.x + _c_half(label.width - text_width(line, label.size, tracking))
    scene.items.append(TextRun(role, line, pen, label.baseline + row * label.pitch, label.size, ink,
                               tracking, (label.x, label.width), limit, label.shadow))


def _label(scene, role, label, text, ink):
    """showText: fit the text to the label's per-line chord and centre each line in the box."""
    if not text:
        return
    lines, limits = fit_label(label, text)
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


def button_look(slot, button, layout):
    """Section 5.2: (tone, glyph name, ink RGB) of one button; glyph '' when none is drawn."""
    tone = button_tone_v5(slot, button['icon'], button['enabled'], button['lit'], layout)
    if tone == 'none':
        return tone, '', (0, 0, 0)
    ink = button_ink_v5(slot, button['icon'], button['enabled'], button['lit'], button['color'], layout)
    return tone, LIKED_GLYPH if tone == 'liked' else button['icon'], _rgb(ink)


def _footer(scene, frame):
    for slot, button in enumerate(frame['buttons']):
        tone, name, ink = button_look(slot, button, frame['layout'])
        if knob_has_mask(name, FOOTER_ICON):
            scene.items.append(IconRun('footer', name, FOOTER_X[slot] - FOOTER_ICON // 2, FOOTER_TOP, FOOTER_ICON, ink))


def _idle_row(scene, frame):
    for slot, button in enumerate(frame['buttons']):
        tone, name, ink = button_look(slot, button, frame['layout'])
        if tone == 'none':
            continue
        centre = IDLE_X[slot]
        if knob_has_mask(name, IDLE_ICON):           # a token without a 26 px mask is hidden (9.1)
            scene.items.append(IconRun('idle-icon', name, centre - IDLE_ICON // 2, IDLE_TOP, IDLE_ICON, ink))
        _label(scene, 'idle-word', IDLE_WORDS[slot], button['label'], ink)


def _status(scene, frame):
    _label(scene, 'status', STATUS, frame['status'], _rgb(TONE_INK[frame['statusTone']]))


def _volume(scene, frame):
    _label(scene, 'caption', VOLUME_CAPTION, frame['volumeCaption'] or frame['title'], SECONDARY_RGB)
    digits = volume_digits(frame['value'])
    if not digits:
        return
    digits_width = text_width(digits, 48, DIGIT_TRACKING)
    percent_width = text_width('%', 22)
    left = CENTRE - (digits_width + DIGIT_GAP + percent_width + 1) // 2
    scene.items.append(TextRun('digits', digits, left, DIGITS_BASELINE, 48, INK_RGB, DIGIT_TRACKING, shadow=True))
    scene.items.append(TextRun('percent', '%', left + digits_width + DIGIT_GAP, DIGITS_BASELINE, 22,
                               SECONDARY_RGB, shadow=True))


def _list(scene, frame):
    _label(scene, 'title', LIST_TITLE, frame['title'], _rgb(TONE_INK[frame['titleTone']]))
    _label(scene, 'subtitle', LIST_SUBTITLE, frame['subtitle'], SECONDARY_RGB)
    _label(scene, 'meta', LIST_META, frame['meta'], _rgb(TONE_INK[frame['metaTone']]))


def _tracks(scene, frame):
    _label(scene, 'title', TRACKS_TITLE, frame['title'], _rgb(TONE_INK[frame['titleTone']]))
    ring = frame['ring']
    selected = ring['index'] if ring['index'] <= 2 else 1   # renderTracks: 0 Prev, 1 Neutral, 2 Next
    no_prev = bool(ring['unavailable'] & 1)
    for position, name in enumerate(('prev', DOT_GLYPH, 'next')):
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
    scene = Scene(layout, art_dim=f['artDim'])
    _heading(scene, f['heading'])           # the heading row is drawn on every layout when sent
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
    else:  # recent, explorer, upnext, notice
        scene.art = has_key and layout in ART_LAYOUTS
        _list(scene, f)
        _footer(scene, f)
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
        if scene.art_dim:
            cover = cover.point(lambda v: round(v * ART_DIM))
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
        if scene.art_dim:
            image = image.point(lambda v: round(v * ART_DIM))
    else:
        image = Image.new('RGB', (pixels, pixels), 'black')
    draw = ImageDraw.Draw(image)
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
eNrVfdvOJLmN5rv0dSQQEnWcV2k0DK/h2THW6wHG3ivD774hnqVQZP5/dTd2Fl1dlclgKiSKIimJn/TPn/70n3/9P//7b3//6d9S
P3769//82z+uj//8KcTx9x///qe//OWnf/v55xyPc/z3y/FzDgccHT/WfKTrv3x9DJAvIpFD6Ec9AhyvOL6VeIRTHkG8Pl1fX+H6
ls4j8u9LvkodP4H1S61HHv9hwfEquByj2JQunkSvqKMW0cgR31XaxTpKGa8KsR1Nqh0udqnqeZW4+ezYZx5Pz44/OXpTOlan2sfO
MsGGXDLSz/m4091r+yW0OP6gSEIKTqQp26uhWy9k9zl2V9Von1Nz/EXLKaNj6GMfUpTSfeOTldLAVccVE4qv51W35YG153QFu6oG
sM+XClozq5Ubw9XLyTW0uT4xAbjGJa9qXkmmJ17ZehlcrEkho7Y1VYHKlQoHVst0xh40e9D0wfXurHSIxETv9mVlrBV/HkPBatgm
riif43n9IEz1qtr3ba2vvtHeX/uRmA2bTh8vatYecO07qxVa/ZvPsjDp285TSy31epc0KdfRCukb/4S64zIXv/xy/PQ//vj3P//h
r3/5259/+jc4fvrTn9BilfOyVGaoLkIYhKDD7qJcVo37ZlSFaDBoNn4vShoUGJTGlIyUIvp0UcooG2tLSnyR6kUiTQlSdsP3kcJU
pPRByclKqqPadagCWsKLMKrdh+oV5qBaj/anYRouyqjzaS2t6VZq5jdneXMdNW4nGtOEhKrFcjPrqO41mI2lL4R2rg1qAUXjdOmi
RRZpNVE0kM6AgwiJi0IzTr/L9Lqkr9M6s2xaXWTTUMLDPAZpeus3Uj+FFJUUVBVEOzpWO41fXT8lLriT0p2U76RyJ1UjRSaN2scz
+Hph7aESF8olnlh9tOFc2PWbOyneSXAnjepf9j0ZJd8ohSjZKPXGg4LPXQ3xRSLdHpZWuALW3Kx9QGLYEeOOCDti2hEzK3MmV3pR
imMLwoZ9gK7Efto2tH6nxXNDC2o8pMkRGwLqxS4KtgLE6tAPRfuNK98o5UapN0q7UbpSyB38FIHUH8VVmRQmS4hqBmRnmpUFcKOk
GyXfKGgbkwRZF6GuhEaErIROBBBCOtd2JTM0QiGF17jgosCNkm6UfKOUG8VMIwZjF6U5HurC1Llbi/wsnzdKuFHijYKVJv8oIz4n
s6pKyxu+m5mJ+aYjud2Z+sqE3pMDSy2+BK9LTIuTgUJRkA+1gPWipA1XvnGVDVe9cbUNV1+56skGyVpZRWVGm3gskDOd7FYFZtP+
J3862c16U/Na7kz1xtTuTH1las6+i+jJr0qEx7S7hW+3EUp+FQN7lVaj+CV61Wllw1c3fG3D1+985GOVj2jB+EBo8eYlunSAdR15
2ambyMsCWDf1m5/qdTEs6GEnx9X7bIwAvasvBdC5TiyRWECbBuhaKTRXErvWaAVlYhKzCycpfHOuANC3hhMnIlrUqHbH+UEUNqx3
ZhJykXfFWZnRnN4ozQw714Mca0imSYBuFRutlMxMrmKhSIuMVJWNxRWaFnUypa886E1xAUEIgVmaUuLcmUCO1KsOxLR4BSA/SkxS
RfKkU5AK5EvnwtqtMKx3Ok0NgZzpXD7cg2CATUADsDoogLRjyze2smOrNzYMKANOaYXUMcbEaSP3PjnXdLreR++K0z7+GTlX4pFm
ontFJm0l+de5qExc2m3kX4OYN6x60smSMLUNU1+YyMEGbygBXSxNu6RS5GPnstDLTmVRJANTWVr1ETESqRgbNxA9LHGxepOHtdWK
i9Jl5kJzKyj36BHKGh0AOdeFC25cacOVb1zFuEC4qnJJ3UvbFLaGNlDn6qNoapjiWqJFU0CRF/lXWhmQ4tIaN0O9hzfALnZiI533
w5Z87Olr229M5GM9E3nYmSnemECcAxEazV5QkXDFcVDwVx1NotJGzXmNMhOlrhQ0gW5222g6MVOKeB7gksn+wBjfYxb5r+On//Xn
//obrgeE45z+o+9x+f7uv/Dh6SWEq3KvpKQXTq0iPhptezX8OGKpOObo+3KGnF7P7xrFv/yPXyQ2/BjxrdiqF/91ffVVivLPC9xP
0uZFgwcfDsZXRgrIG0c9inyJ2JyxUCH1CE/1f9W3QrxeM147JHkJa5JCpXZTi4LUC5v7CumpvIAFPr/0esuOXFQ1XumjXpy49ha+
wPed/z5I6q5+CXuBOzihoMbXsTabSWsii7Hw/6/QiEyEV8QyqDRRlMswja7HvwbbUF1Q5XWVDNRdwzXguxN1Unwv6BMHyKemkT55
TnpXZyXFIcP6zvUOj3INfRr3+/rwq15VRQX4S/xXVT8AFoU6wuq4+y+jcJ+f98W4BJI/FYtyld4INuZt6NKXjN1d+FuaVZd/H61r
pSRna9BwxPUlYbGAzGCmgXmKf5EWGLgBp7NIO5lrodPzYMXTo6df+4LMZhX8XsQoJdpQY2EFtZavfkSp62kDIIgeocmpXI1Aoyvf
dIjU3tlmU/24a2q4N0YtbnBtfT2p6is6iVKZMnxfwxzFtYLhLlnnI9bXLJ0lHgOVorC4Cqs3SimQzU6HFio/AfFSQ0Y4stCdsM1g
hWLZ4YjDstCVslpHdkBICFx/rV14M6CddEw3aNAQtdzZJ4N2bgvv28jgua/grc1ZR/apNsy0CdSmsZFjGW5f9dZvxdlasVFIalTu
4wxrocKL2hOv4uIHJ8mQVyWLqwsYvucFuFcx3tfIsoA0O1Ar0dxSc2Goxov+LlIWG+uwyFBsJlVRHN334jmvPC5cSu+6eepN7oGk
AVkiVR9/sg09safgIjLmgskGxKnY03kd+u29UjIWwVpRpOzgpBRuVsW1MOro8SZWTRRXjYM1GqVBwo1hD0a4gL/rVMkRUfj6nEJx
ShnJqUoLSfwuHiV1hW0MHb8bZ8FvHLht7e23fxzfaZmP3VfeV9zXwHtJmPSoiAFI6g9Ze148bIe+ZgnjuF8rh+nkCYOzC9GGzPgh
Ddmm5UnwpiHUi2cPiYx/kDErSpLIWET9CY8aHirJxWIhHOEeEQSswS2ELH6EZ202DbziPMepChwlyNLWmVvkh8A9kjSEE3UvMnvb
2N72K0xvPNoHy/tWSSdP8Qo3BXT9lsgOhwczCjh/kCgIm1ksKsVWogWgYCq5kH28rfovURt4HhTAsWkJpC70gzD1SDvm6SryJdG+
fLCeh8SvAW09c4E3uUkbXng2xZOQwK+oPL/nto6/85GnSbUaeSDBlWl2wloCUka28L3Iw+TkMNYONLCNVkDi8TlqFHUcg0WvKGsM
rai8QkR2wUlqITPsZprIbyjS5+WgyJmCuIBP6cU0L2JZU+CymX7gaFZbc2rJbBFuYejkh8rGvvnINRzxHr1WlLwWnT54iYLx7PsR
w2WDTnpCV38V/VSCAsXnCe4LF0Vj/fCuH/AesIzcL3qrV56WxmLmIrDb8xHNOT+H2/mD/HShZ/lwaki+THD7G+ntQzlvrswcsGDM
rmW10Lq+Je9TR0UWpKmBktfSDHIjdw1XzqklSZRfTC67meQDvjAVi2bSz7rINZsPfc2Ll1xiOH6vgCauweU8bYnzGt5Wrn4Jhs1F
8L35Crt47KXGWiJFEMvczVuMLCG0ZvmIvMKaHnURc4rUo8bhN5s4T2lpfY4PN33vejwUqVWzqAJ+NBb9/rva14PMeaIQcXEvylSO
Z15xHrVuTVlmbiGaywuuG3kK5szQ7yPN8EacL/m5KybY0lRmp0ArJqO2jdtSxbM2do0gQV10MW5QPwQWHJW38Za3QKfO/r7rAabl
n9nu6ZyZqxxsMSzNS2TPdrWs3eVf9gq3aW6zUEyWnnCpZozYgv+LtFVBKebx1t4tF7E1EC0qtozvdyzYzkS38Fvm9cQ4LUHrqmqR
kH4Mc5NH8ItixS8ou2ZHNxfxq6GfXaxFIPc4RynJhSk638GJzciC4F2kxvbpaZUnfKjML7Qz9oe//+mPf70Sha8x9tNIGf7Df/z5
L//zP/5xEfK1dzayHhzOoehvOd2DPrdmGIRcLZ2IE+5xBwYT4SlNn5/l5HIPf071AC4D0x5C4lzr4r70E5eLMqdYj4yNKJgLfkkb
kcq1HShkkNzsiqVginrqhLLAuoPmYXB6vH5p7ks+fbMmPmhWGqVFy5eU/BNXHNas2UfeTudGNQI44GdKsJ/ovl5XUuJolmaBXyn6
TsL1dO8nnIl8a9l/y6evdXRfKky/ilZg6ZZR7/MpNQ1D2g2uugHTZ3bFXanKvupl80gbCV6s3X8J7kut7kvu7sVXluERij2b6puy
r2Jyhcx66TVqekKJLsUhVgQaAQnzzbsqSuMKgG6yc/fag64PoOqD6+VF6TkTE73cl1WiJlsN8EZ2VWx7rgiITPL1aqoVfa2vvtHe
36PkdPjc+Z87HE7e0YqNWYvFRG99d0wLk74vVC2WskyS4iGi7x7f3BMXHuA9OKKcCzhCktUYwEDphZJO5tARKauSCDwiGwRH8BG5
uURLQkj4KjNCgjUmThAJVBwYmBqBSLTTtJRBEp3AC0VBEpRxUxgTIYm1mDX3jJJYCs78+uHAu+IkesIJYTacBJwGEMGEE0wBKczS
FwJlm0DCnIhmOAmvWIKTQPwWo+UYJ4H9MuEksKgRZypOohfcdM2Kk+A6F8VJTOLBNE60pqCNxzTOhYZpnGJ1T4+ViI3xHGBgiULm
DjxaYqGlDS1vaGVDq46WPGQC8lQ/1JhCHiyRkBg0QYYfPGhiJsU7Ce4kzOzsBEdyoImJUohSjFKJko2Cyt6cARbUBHkK8KgJdgpp
Qk2sxLgjwo6YdkRLGiseNcFscUJNkLtJE2piofU7jVATCy2YUQGPmnBOUWATOUx4C4NmGS1vaGVDqxta29C60ThvjpKurkoS0pBp
YTKXySAUUH15lPO50NKGljc0VKro0pcx53OmNKJYFjSmfE486bQ2BY+ncN5UABXoCLUGBKlYaGlDyxta2dDMmjYPrSAuRosxtmLG
2uQN/obwFQstbmiUd5tZCx3GggSQJozFwuctU/QgC5Env6PdLBjjLGb9okxQtWqkOJwKmrwykT82s+agFqp1wcAWK2PeMJYdY90w
th1jvzNSXigH2+BhFxlYEMwY76aPEkMzTEguxjKe9BaHvaCRIdKm1NDJSrOjngYQ5YbObP3O1pyzkC5hZGP1XdLu7qJthjf5bJ5a
pAmEkSfdIhDGylg3jG3H2O+MBMMwxmQ4DGLMEw5j8jvd9wd4IEbLNncRJIaE5Q6K4X1dr6tZIixGJwSDYTGI5/RgDFcOgTG8MWM0
RucZSVI0BjFlIbHPjlZSJqYoOdmnJNWbXjEaIxae/BgaY0wBi8qe4BgleTYFO3arGHltmo1Izchpg06DBI5BE0lwcAxqUfJwDACn
owTHoPmNll6NLTg8Bok5ejyGm7kyIKNVB4MhNw1ugsyYDN+rDMrwesSgDO9aGJVBXFJ5ctLEFoVW76W1e2kU8JGFCR6XIb/0uIwp
6GZchs24HS5DfVAwZMYcMTEyY3JpjM1YGeuGEWPXjJ0lAiV4BuDA7IJ7OLl5JgT01t3LnZw1MYlE0Vl37mgmpXtZmbiKlVUYs2pB
GqR5shYMpLHw9TsfAyG7rxu5auVLBtSYyyNXvZSXDCCm5WErgMdkMqwGsYHDahBX8FgNt5DCYA03gxe0xhS1MlpjAUpE44MJr0F8
okvkoZfy8qa8Ynx5wmwsOI62Ke8eMzFsQ/mSwTaULxlsg1eNwME2eM1CoRZpjdwZtzGFTIzbmNloPFRPIrNaHbSGfPPExUcOeC7y
zDNXvHMhWum0rmfshpwkAQbeuOYVo/JKK3JWAU2nGbwxUdBcos4oJdwohWqASSMOvJFx+H8XvRF/NXoj0Pa/348OlICIq0BjjQ8T
hXElvh/PoIIAx9vkrbQm92M2RJo2WT4DOOC7AA7azagewFE9gKNSIkj6sF35YXORc2EoVabPYui8q2YIjmSbKPVx0wR3bfrzG/sD
JONbCI7+eyA42je31wkLOyE4RlZS4L1s7knZ+qF8Kd49rLKRdUdwXKMX92jld7RLXu+VDJpnmnjncNpffJOIkb+A4KCMoUWRY9Tk
VVPW+HHnM35AcCQahtq+qlCgSP+q7mPVgXdin7foCwr3OVEnrCnokmB2h3DEe4ZLtqyvyvvObyEc8QbhcFCDL0A4wNsFZ3jqE4Rj
BiN8hHDAM9DgCxCOaRu48iiYIBzF9rMlaSQE2QR+hegwHNEnjHbJ6QyKX4M1p0Ve+1UMBzxvyy/52+dHEx0nDAfsMBzxlo/jRQvf
wHBUTgKsrOACVhxW22E48qyNnFDg9tAFw6FZ/pIYHILkJWbJriws43LHcMTvYTg05zHcoXJfxXAsIMX4EcSRPoE44g7EEZw6gUIj
xcmX51d9BnGkKV8mriAOuAMK50ziLDbHQBwO0Nf8ABYAywysG/4HjWlV3KaiOATDECWFhxNkMOnUZZBr7jY8oTgEFRTD/1sUByf+
afpP8eJ02KLTo6rEphiKYwLvTKPLZdE9oDii5NMvaUjwAcUBi+n2kApRB0yJCy7nXFQJM+XA1DmRqjnDUycYR9rBONIK40iKOqq/
BYwj/U5Zj694/N4wDvgOjCM+wTgo4n0p1lctTdYETMrP8rjGjn+C9jqtlYGlcQaXA544BU9KPH0cwoO8UqowpQUKmk9CiEQGQxWF
3qX+uWhBaA3CPds76qTCB53OstGoNECYjpalqFOi6+raFydVrQauWrAcrPDpwQT3X2GB/Uxnb4DfK9v3sBzpa1iOqhGDhKfYSsKz
delYD99o+gVElpJTmyxJLxKGa/D0Q/uq0nxvnrnixCiL/uHxmOjcC78mGUY0i4sBn+mdJcTNgk09HUK1McBbmlcJJuFHmUNcoODq
NE/xma6MUKxcn+oeVsNyhKAe14M5FMbdWfMcmIOHTnKAqqpxXGRYBb+paShmdj5KKBa4L4rEeAzEGhkkaA+yG+wUwKTVakXCjkS3
aFC/Aeaom/xSP2K2YI6Oog8Hx92fwBz1bSquyzonV0dVivEAD+aIev4ApyvCm2nwNbcOH172A04kfR/NEX2Azr64cxGVUFnRT1Sf
iukfBOhAaucczk5QhuyV+PMqwic4R/GhkbhPg4nP2L7g85Zp1HQ1UvJegziteI602FUxMuAjpGxYrFOwCvGIU7Gv6GZg2Xz0FsUZ
PYrw9wpt4A7JWSEBp0ej7STrl2TYZoTgBRu/hujgKJkPxWUzimvrmNpV8PRLXj9+WoRJbFQV1EE5d20yE+05XNwML5hAK2xK+9LG
H4pNf+Bl/du4jmy4Dhwq9QHXUcwAW9BPe+TRh5DueXEzm99Nng/WQh0nkD3jqncFdnD2fp6AHYKe7BLvdV6pUATkOiOiABhs/lQ/
RPqvGYTwZlryxo/EG0Bjit7ijE5Vuzet7jxb2HpboYA7sMNNUbvFZfHQRQvCCVVZsPZ4ipMDIG+zp7MKFD2pkWG77WSAQHgN2FFn
vEWcVqZfoNGWHUDVXJETsqPekB3RYpowH+fyJdwWLojlryA78vKzF050AkXGuMHU2UilZ+jar4N2lAHtKDO0oxu0o9OxnScfRT9i
wop5+Kclecnpoxh/yz0D9rNaXHoTnYhJhbTCWSgjMbtV9yWcdKBwZojGSP9AdEczdEcnAAwImdAdHROOuCJX7jMnTOGjrGkdsiUq
X4r7UoNv2cTHadvRZ+Tzl5KnR54Ra9fto93lYA2jz+W4093743hJMSG16sXck683p4/xD+mjtjD6ivtW9Ob4rhxcV0b1mgBBc86u
V00vzq7wK/3R1XAuL4bsa9+8/PCZ04ZWJuH26dvpf3jGSQjRv36knTQvBMdZihdQ8RVtqDZZUUemXi17lcVeIxASZf5FVsJMUI9g
SsM3Q9RJZ1J5euIABKMC1dpQp7tBajLR12DdVTFfQ+qZ28Rl3T0UX2+tqO5GkOIvLdGq8Tvnr2e2O1D8xTB4v4WgVKqTQXJlX3v+
rgZ4CvfEpW+xk40JBiZtqxgkWlflqXc63pXwHvbRV9hHd8cWM+yDrAVMsA8//AX3UbtLumLgR3MDkYEfVOnCgAWfYpom4IdTI0Z+
8FG1UhplsJx0jJKDfkRSTAf9QFWlw//30I+15MwVKFoByls5q3tZ1aIVMtL06PHq4B+DMs4SdfdkZEK1dMN/VE6JYRwHpXAVTp1x
+A8y/WD4j3zDf4z3ZalBk4pXqTglkXopEQKErW30CJCZRgiQQatGk4wbO5yVESCtctqbQ4AstLShZUfLHgGy8NUNH7WjTXUmEAUl
BJYJAVI559AhQGZSvJPgTkp69HFyCBBBYRkChJBrySFAZh46oDk4RSQEiPiR7CAg4k2yh4DciHFHBEcsHgJy48ys4JXMPENAHFtU
CIg4ouwxIDdi3xAxW+pGDKz+Bu9hHIj3mwIEqZKW7JEgGVzmHSNBFlrZ0OqG1ja0brQ0IUEyML7SQ0HUhDooCKOFYcKCrMS0I+Yd
ETVsrBeIbDDNtAaXU41JpjUcxSh95aEE07mxhAdx3lbwIGUWPAFCVmLaEfOOWHZEs7Ldg0KKekiHCqlTtfO5oYUNLW5olPULEuYn
g4VwBKDEvOO8GywGhsySpYzTyYgxMGTmo6RTjn/LBAxRRgcMYWuXJ2CI6qADhqyMecNYdox1w9h2jP3OWE8xdCacKj7QY9D4xPDJ
IvKJ4XlGkKSbVa67QUJOnPiyR4asfO1eXt/wNXEjvu8ZzqmcDh0yldh2A55cem+TEMmpc/CrrymOs0z4kJWz7crsG06+DIs4xw6O
IUSYswpndI4peYxITd5ZdXIshBmNHiOisbyBRMhBZgcSmYwVevfJZfbVfBFIxJdDIJGZJxKPDSUCiZD1rB4kQlzJgURwBtE9SKQl
n+JNIJGEaC0tyi6P0NRt9OwVeHaVDCTCs0uWPqNEMs6KlRaV1j1KJDv1IpQItTt7lAgxaVFF2mSkamzRoUSoLPAokYkpyjH6Juko
+eTW0wQTmfojwk2XGCfiXQ7hRIRNKks+nPiS0OqmvHYvjwJDNxFmpIj8VPoFnPsDoW1CK4aKzA6MsCJLvMVYkZWz7MqsO06Mrvz8
XtAiIxRyF8iQN+flhOTwIjRxld+SN2c2ES158zPzYQLZICNLefleXrErerQlyc30YEKNrIz9zphPx1gm3IgyOtzIUmKGTYkCJpxK
pLYUHqkOOpJP32by5WexczAEPeKXZxg+wnwK5PABb5kQJFMMQgiSJTJmCMnCmHYl5g1j2TFWY0weRHJ79T3GIhSJK9HBSKoPTBhG
wiqbPIyEFkFEYuTKp8ifcSRziMVAkoWRBss08smXAxholKEkM1s7b2zkyBe2eGcDuplDp8QCJuFFMQ8mue4GCmUBk9ASb3VgEk9h
q4rHRwgp3El8G6YsDQichJws9upnPAn8lngS2i/yO+KoXJnW3/BQ0cBH5+KaERxPeIGQ3yNK8u1w7axH3037LWC703mThSZbvPB0
urigTixV9AXBNo+zbOTgGUy44PTSejzulH7Y1uRtvuDOM11AO3yu1x1T8ghYoJ348G5DZ09vqiSvr2z8Uv/+1gmJ/fgerAQPj5Fu
zpJ9C3j57XBt9Ei2nSh1i/friPACLOOU6z0kPwCLF7GgBifVYVdLw5Vk3qebNtbeXdVRvwAsSZoz6IElmZUVHNoB3Gbd0+Gl55vj
MzkzMVsDm57TmelfHQKhypG/b3NTK4r3WUVCfACWZMuQhtumvyUAvbId6ts0d2U+djX69EVwpg2mfGHwRz/b0YVfAZa0+9mPK7AE
3hwOuRyQfweWwO3pLl12OktVzjHPZrGy3jHkgSXxAAGWJBsEbI74PEi9twOOk4uZz6Z9ZU00XM7BXIXyDCyBKQU8vj+8fgMskSGM
W9ywJv9sgCXgT99/DywBvYSGd92DNJWPhg4ggBAwxN+kjpS5iCOMN/E9skSzNPXQeD0wu0mCQuD0RslJdtcJPI9q6Wh3aGmSFMxw
B/HN2JK4TaTabNLHT5cNvN5bnnV4Ww6JaVTSnBI2dQ83SPmTeZ/zwtxjUOOdnwYbpZuCh1AVO0tcOtlEGc81tfmeHDicENrTZtns
iqiT5DGQU8wpH5Rze/o9D02s9oIu0csJAju9H4CX2MHF06HH8I0Tt7PCSwqZG05FBn+otF32tIeXuDwly5DMM7wEdpoH8xGs0wHw
e3gJ/BC8JJwOr/WKRzZIlLs6LirOzAFMmiBGpuQloDwhvRsILJFLACZZbld4n/z4/zPABD5mDsOCGV9Tr58AJmlCKvEdPYVixqgI
Xb31ItgNTpqurldDhWgglVDNSICNHUqZx3RAK3UBmTTKF5Mc+VM8DV8k8qJkoeRBJjqBeIFOCuhGoJAfQCZBc1zrYuMEZVKt+UES
X2EtS4dTcygT85V8prXkyGUN7II7Wzs/GONw/gpjPE1+9sb4zRHdlme9Ak3sVILsPr0FmlCOg940kyiCaHbtDG7lg0RZWY0iMHDE
fYnaRjrpUkwNnr1xVNHH4LoFl1TmOS3eZlScHjKWiaAuYHe9nMKWPLCmaOMbg1t4iiLp4QywCILhaATj8FNvDWtZeG2au/BtI0ka
XPjvU4KhYigYXYzQsBdM3RRwHoRk7iIwLj870FejyWAQ3yw3ltiFnWG6A4FrEbhDqh31gBLAm0jCKbGggE0oqrktUAAN7uiuWWkf
ACd+Pacd4fuAk0DOWREn+cPyUHubI+yy4sndkV+KWd0Yz1YNZhLiu5UTWuiG8uFtPw45yd+FnNRpNQ3kjqRG4DEwr/0cj8NRv3M9
qotyJ7RFsdAsfmF9IWyRmfmGi5Z7DN3SVHH5yfZCdV58q8ep5kpebEis9QyCvGJOioaGcGR/JD5xz5iT6jEnMJ95L/cy/nfBnJRl
agPzql/eitav1ojdAC/YuIvW9DIEjSOTmOkgbhQNbQA8HELwJ3RO8ONpP7jno/P7OLzpOIxibm//FkgiTbgatqbhXFr5W6FOPr/t
25Esquop/gMkQpN16D3wRCFRLNbNVVenTNjy95En3xXqAz7DuVG0azI74vWAoDeT0T0YQUBg/kaubJeHuRH/iD9JchrQebQPEwEz
TJ/xJ/l5Pruuxjn8CUiwpFFKddboA/6k2lrg4t5fcMefFMVcSrSmi5C4ypP4np/5dia766NOk/HlUB0H3sPO7DfgC1t2d7emzABk
PdKvj4bTTjjxd5P26UI6t6rW/Jr0tA77oxiUsruFeV06zQsmFiHUOA8KI8NfN6UCW638DLb7dSiU9q+RRDihUHpWFEofKb2jRXxf
wQiQO+ILcF+an1z5lHjcGmeJXxkzuLnKDxPu3OJlgyNTPKElx+sXwkihQcA0fyv2jZPQG2IL5ERehKucB80hsEoZwU9Z6EnvLRji
C4yKAcl5OPkegqKVO3EXUL8F/w2yb+PMSXnH+u10L7hSNzHJyHHqM6ykwBtOS/zRNgaEMfC3euwe+XpcO+6jmWMjDVlz85IvxVck
J9+cjtvk2tTimxOT/1aj/13zZYaTk5cI9BF4851eB/7lZ3fPYLyu7ou8ErD8s5y8ZMezhvfNo57l4h+SEuoLvdivPLpJEsG9Aq5C
o7UPJsWObZJS8G0P1WvvrHLjoSnzrMAMywKBbI1+HrISRTKgTiK1qpNybp/NkJ6YKLOKGKUfqCoJJzP8sDdKNBOQWbMqs4Irn77r
SqDA4MrVw2pFZ1QudfSvtq8jNa2uULUJFpZZ6h4aFXp1b4CRw3BOQKwbp7yO80FNRNU67xzRke/KuvbdFYkuAJY0A1jMaDKARUwn
o0uiHFSKeGhGtWDaiTcXjGC5MpCPoNmFhGC5MotNFxnBwhWPlBTFEBYWZZeXSDY/ahkYhqVFXx5hWBLdCtMNwyIX+BiIRY3TGxTL
UnbmKjS8acVQLIlu02mKYpGRkjyMJfM5uNVwLEQKDCORNF5ENYIiWVDhLEWPoCw4pFGD+X4TkL5KDItJXFrGY0gNy0K3PHA1WtHj
XVlcU8br6eAsbKNFGJjvutAw3RVp0WhBEpqiqRFlu2a0SvF0eJaVlja0vKEVo4Xu8CzCFxyeBcZJ5a6CqEUZewtn14pnYXcSTwdo
WWlxQwOjcWUI0zLcTDG2fCcVJnUjVSZVKwtHwnB84iIF10IeSH5KuBbyQzFMuJaVGHdE2BGTI54e1zJUflQcDNfCLrBPuBZyYVZg
2xH7hki4FiaeHteCYyFruyMpl/O4jGsRE9w8rkV8VfPAlhux7Ih1R2yOWD24RYjdo1uuhE20/ODRLWJfJWF8yo1tHt5yI6YdMTti
9fCWjoC16uAtiIlWSrvxdOUpDt4igWPz+JbJRTPABR2rZ4QdMe2IeUcsjlg9wEUMcCScFabFCmP2EJdVJ/K5I4YdMTpinWAu5LLF
nxHMhcMGI2bHKWYn3+0YwVxWjcrtZtwI57LqIyXH5iajOCvQxRWZFeni7KAhXZy/N6jLjTPvOMuOs+44246zbzgpQ5bifhnyVRWu
2gAjLz/bScqQTbRX1zzaZTHYdTdo0NuLtQ8O77IOudrubqH2DWM7pxKpJ1qY350V8LIU2XY2gBw/zXZUko1CL5hUEJ2/cEaPeLlx
tl2ZfcNJiFYrsyjiRThBOOPdZXXtHlNrigHmbqQYIFGUXh3ihTylFldXA4YBwOxOe1em4jAvXFJwoBdfEoFeBpMNX0K94GRE5AHq
+EFqRbCX3nQGzbgXnGmaKWHgS8dYzYprAgI/tSMI+jLmPd0Yg2Ink/YDMKiVdAiEGI2o+BQa9l3WnhX/grZfhMJ+n7j0HUVloG+o
xifiC009SXMImGmCLRAYqE7u5PFPN0lmCMzUO+TvJ+UiCMzslRgDw3zSBPL2zNiEWDcltk2JXfLSs9IIBcO/FWWB2UkyMd7jK4LB
LG6OYTDMGT0MZvGSDIOZAzmCwdw4MTweCwkmW3T5FzgAaeBhMLxuIcIgGIwAtQwGI2wiXb7lDGfNIlxy+Ut5mfm6lUdhWBdr6WAw
PFtsHgdz4+wbTnL4xpkNCMOc0jfk8JcyyeGvZRJ+BJdurEzDgo6ezQqFEcbTQ2Fo6aB5KMy0FiRQGOIrExRmDpwJCrNEL4yFmaNp
wsIsIQ2DYZgzejDMrcyy46yOs09wmLWem3iM8TDGmRUP4+qZFRCDymsDFN29rK5UB4iZpwwMiJnDNgLEMCM7CwLE8AKa/tjjdKtD
xCx8hIiZ+cjVL3xxw0c39QQbDAKKIdXDtWNBxVyaOlqhNMWyVDp7g2ExM4lMbSq4Ni60sKEVrknG01AUGsPu/YvQmPRbQmMKpVa4
hFBKrmEUJubN4JUzIzocvZmOx3MjY/D7MPtDQJfEUtvPnbaCprN/N5kQeTp7brs1aBlzsrXnNuSqNAKPU8Ulwypn2RIo5cfODcW9
p6SJNWmByCSfjHcE21nDvcbyuJ9IqT7w4dCzB8hCWnMz3ujD2AT7zUEy3zxrle6/CXrVDh0DjGlTjbLl6sGoKTqsPshfI2GFkk0D
5+ukQ47LDe7UzIjpk01/i7c1m1r7ChtgpriUdjvp+w2ABb4AmOl6YKfbeITMm7pJ0iL4JPHzHZAK0puD6vSmluBP+Y+S2g2J/rVh
EZNku71NT6dr6NJzU0PdgWaSbovbjUq2f2spJrxzjFklnC1TlaOuKUJJTv02s5emPOjkkx9tY97byuwvYHA7uCHcMxxW3Ez6ePtT
mp+H6azF9ekDbsaAGnw8K67Dqy2rnI3aVbQo5Xokgc50GxGhudM/QS704OuJwjntOQePYgphTfmYJeNuXslPpnlKmE+fMiCSy2ub
bqBJH8EzzpmkHbwCloQv1o0QlhOnOecZ/89SD0wMAE0Lw99SLmYElwTBp5e+xCC/giGXmlzB0eROB0qGkXRQBdH4Q7bTu1QjTY1O
E+QsbE59fsEORZP2A3mDoknvzqFOX8pQqvMNYyH4Y6ub3cv2nP/k8/7e3PRWpq9y6cDD4OPTqpO/FcpOYQezICbP2LzaZe3qvCRV
vmi9gOMAzivOllNPEKyokN1Mpi8z2MbyUOkalni/IIkHV5Cb89g1/gCiJvnz8M1upi8haqrizgQYnQTJ0r1o3QUMp8+gpJRmf0dC
nJB71SVkvspG3WSQZmuFHWrtcTvhdvWUGxhpA6nRO1SS5OmHJCOMeUS1QnZ50qFSTfnUd8lZC3ZEtFPUxBcMCBhSrxRIcvQvne+7
jci/mzb6Ksd/R1QNvFO2V57+mQbx/cK2uz/NUz4xI3xfjSJMuwtRoSEhCRZBL01JenYwR/0dtSEmRdppqqtkHxZmT1rwjKwhxDTu
lfN1GKf6ITERCfOfCH5i+cVJz9WPxWXmxnAD17D+a3YjrIZPUbeWj8mHW+t1GXFOXeMone1asdO97eSAaACxqmFgtGTo86gPhjqk
X2WowWfJ7e30B5RNfbhd7GU3briZVlm1ProjIqrkrWMNi9xmEeWCD2ouWgkKyuwewiRiPu2KEbCWngdHg4LO7QzbYefBCfBRsH0h
Hcs0mQ5cbaahnSdJqFIIluAE0+Zua8keZdRUGKTCSSY6VBu5BVBvC8TxQBnAYR6XDgRM9+LFaR7EiJ2i1zfwPKHZ7VhcGZtN0ppk
MQ7VxuYAcsCTvWrCaRRwVgPGEO4sRLn7AmgFgasU7Oq17M61T5ZwLP3FNyBRvBgDY3twaCZ5C8GUGn6+rYjwzV3RgZdCWPE48JSR
TmtlN4Ppw+XgcmM1ZMYGFio8O7ANvLuYM3xyFVyRYnMuyOoFE7nioHEhnvfweI0JrdCn/uF1P+CUikNGfAeTE+Z1vCTXMbIWBLFE
6UjP0+5XKkf42srL7hAVw+WdCuZ9B2TwYOywhSbV2YSwhMw0hlPvQbLVOIOIJL3gBpU9Tfj5mO6Hzfh7bYrD/ViL+Lybamnl7u5C
PiniENCBRhrBjvNo7mgE2MB7o0f+/F6BU95gSeMc2Xr51r18/frQS86AaF66cadrBn6SCIMn/7ytkySaxl3kcjRWX1oiPvkg6v0K
X2QjLDgS3lBoU+Qa4Dks3SiDRzFoDB+SC17SjwbBP/K2kL4e4Gr/6s2udCSVHYWR5vtaugH/q8yXEt/hnNwQV2wszwWrW6/5ncQa
2rNcxSeDzH0pdnZoHcTuNPQ3gS8oVayuuFyOu4O7p1njoDhdDxdk9hyf769x87nkx098NyN643PSAtU//aVY6XCVju72wzZDA5/N
sKxDlmUOM62h+llyyBbyhUPXQGldKRO8hIKY6OY1yUUR52TkqSOzm1T7oyPSEdwJGGyR+ApKd+iFXdQXNJAFfzRbsiDO4EoBnIii
X9kLwdaIJk1Obn6UplttPnnr7VlJYZlk1gUHRsD4kzbKMBmZ9850s+IRu9h/HYYnpmvfcGzc/9Pnp3fJT8eMhXKlKl/7vsBHKFJW
YMdJwKjtL1TAz3ls0Ts2yo7FngXKycZt/3Shc64ZgZDGbmeCjiT+Je7553FUU1A2cL8UtrGnnC5M0JUEr7RRt5S7f8PYO01Xir1n
q+tP/7XIJUeUyz+eBEMtvqRyRR9Ti5E2txhJc4uFNLWYS3MtRlKdW4y0NrdYaK7FS92wxetP5TjZOl6yF8Ig/fnf/8G7ypFvFR3j
v+DBZ50uAjHsCWZLCFooVMbcUP5cdBu+EbOhRtoA5qxdwrjqELHOo9ondn7kr+NCR5QpIL6+4POKf67mXBsT14i9AorLSuEZQrjm
d4UTlze8op02IvnrRNMrz/EiXtv04w8gPQvbdSDK1arr6fWhDs4reXP86ePvgqXjttUltf8i2XxRHqs0IgskkhCCRTYmDcC/8/y5
OKLSgQ4e2EpOBcanC6iw6M+J/zYW3XjSUIAR5Sl/X/JMyYQ0xFmG5Hh+1Ydo+y//+r8xuu+o
"""
