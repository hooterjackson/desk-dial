"""Window picker v2 rendering (desktop v7): layout math, the frost, premultiplied chrome and text.

DESKTOP_STAGE.md (K4) sections 9 and 10 and CAROUSEL.md section 12 are normative; the v6 rules of
CAROUSEL.md sections 6-8 (labels, icons, text) stay. This module is pure PIL: no ctypes, no Win32
and no Tk. control_center/carousel.py uses it on its NanoD-carousel, NanoD-capture and label
worker threads.

The v7 picker (K4 sections 9.2-9.4):
- 400 x 250 cards at (640, 370) on two tables (16:9 ``TABLE_16``, 32:9 ``TABLE_32``, chosen by
  ``Layout.wide``), flat and square (no perspective, no Arc); shade min(0.55, 0.22 a);
- the cards group (cards, label, dots) sits 44 units higher until the first snap or snap failure
  (``GROUP_SHIFT``);
- a separate 2 px selection frame 8 units outside the centre card, and two fixed shadows per
  card (side and focus) that crossfade (``ShadowCache.paint``);
- the snap chip, the 30 x 30 badge, the label (top 512, 26/32 title) and the fixed dots with a
  translating marker;
- the snap tray (two 176 x 110 slots at top 104) with its borders, empty glyph, badges and
  captions;
- the Frosted background ``blur.picker_frost`` (sigma 40 k / 8, saturate 1.6, tint
  rgba(10,10,12,.50), no dim, no sheen) and No background's flat 55 % dim;
- the toast (``blur.toast``: blur 24, tint rgba(24,24,26,.62), top 588).

Coordinates:
- units: the 1280 x 720 reference stage;
- ``Layout.k`` = min(monW / 1280, monH / 720); the stage is centred on the picker's monitor;
- host-local px: relative to rcMonitor's top-left. The host window is rcMonitor-sized in v7
  (K4 section 9.2); every DWM thumbnail rect (cards, tray slots, the fly) is host-local;
- chrome-local px: host-local minus ``Layout.band_origin`` (the chrome window is a band, K4 9.2);
- label / dots layer px: relative to their layer windows (``Layout.labels``, ``Layout.dots``),
  which move with the cards group (B2, K4 section 9.9).

Premultiplied canvases (``Canvas``): a PIL image in mode "RGBX" whose bytes are the 32-bit DIB
layout, B, G, R, A with premultiplied colour. Drawing is either an overwrite (clear, ``fill``)
or an exact premultiplied "over": in mode RGBX ``Image.paste(colour_or_image, box, mask)``
blends all four bytes as ``dst * (1 - m) + ink * m``, so a straight colour with a 4th byte of
255 and the source alpha as the mask yields ``dst * (1 - a) + colour * a`` for B, G, R and
``a + dst_a * (1 - a)`` for alpha: premultiplied source-over. (Mode "RGBA" is not used: Pillow
switches a colour paste to straight-alpha semantics where the destination alpha is 0.)
Sprites keep their straight colour (B, G, R, 255) and their alpha as a separate mask for that
reason. GDI text, FillRect and raster ops never touch these buffers (they zero alpha).
K4 section 4.7.3: no ``Image.alpha_composite`` over 64 K px on any path that can run during an
episode: the label and the toast pill are built with masked pastes only (both are rendered on the
label worker, B1).

Text (CAROUSEL.md section 8): Archivo (the bundled variable font, ``set_variation_by_axes([wght,
100])``), one face per (px, wght) per TextEngine (one engine per thread), fractional advances
from a 1000 px face, tracking in em, per-glyph drawing with ``anchor='ls'`` at rounded pens, the
ellipsis fitted by binary search on the same width function, and per-glyph font fallback
(Segoe UI, Segoe UI Symbol, Segoe UI Emoji with embedded colour, Microsoft YaHei, Malgun
Gothic, Yu Gothic) from each font's cmap, parsed once. Titles are personal: nothing here logs.
"""
from __future__ import annotations

import bisect
import functools
import math
import os
import struct
import threading
import unicodedata
import zlib
from collections import OrderedDict, namedtuple
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

__all__ = [
    "Layout", "layout_for", "stage_scale", "table_state", "thumb_opacity", "shade_alpha", "work_half",
    "cover_source", "is_caption_stub", "card_rect", "frost", "frost_canvas", "frost_sigma", "glass", "glass_sigma",
    "solid_frost", "fly_target", "fly_rect", "slot_rect", "tray_transform",
    "opaque_pane_rgb", "build_dim", "Canvas", "Sprite", "ShadowCache", "TextEngine", "FontSpec",
    "cmap_ranges", "emoji_presentation", "render_label", "LabelSprite", "render_dots", "dots_window",
    "marker_sprite", "render_toast", "render_toast_canvas", "toast_size", "fit_toast_text", "toast_backdrop", "letter_tile",
    "stub_letter_tile", "tile_colour", "white_contrast", "badge_sprite", "icon_sprite", "placeholder_sprite",
    "placeholder_face", "chip_sprite", "shadow_reach", "compose_chrome", "ChromeCard", "ChromeScene",
    "TraySlot", "slot_glyph_sprite", "slot_border_sprite", "caption_sprite", "slot_badge_sprite",
    "premultiplied_bgra", "straight_image", "fallback_label", "SimpleLabel", "fade_lut",
    "CLOSED_DESC", "SNAP_BADGE", "SNAPPED_DESC",
]

# ------------------------------------------------------------------ design constants (K4 section 9.3)
STAGE_W, STAGE_H = 1280, 720
# presenter.rect: the stage's card area (CAROUSEL.md section 11, kept by K4 section 9.2).
PANE_X, PANE_Y, PANE_W, PANE_H = 70, 92, 1140, 560
CENTER_X, CENTER_Y = 640, 370
CARD_W, CARD_H = 400, 250
GROUP_SHIFT = -44.0                      # the cards group until the first snap (BS:81, :1399)
# a = min(|d|, a_max): (offset X, scale, opacity). Shade = min(0.55, 0.22 a) on both (BS:1150).
TABLE_16 = ((0.0, 1.00, 1.00), (280.0, 0.56, 0.95), (400.0, 0.34, 0.60), (490.0, 0.26, 0.00),
            (540.0, 0.20, 0.00))
TABLE_32 = ((0.0, 1.00, 1.00), (280.0, 0.56, 0.95), (420.0, 0.42, 0.70), (545.0, 0.40, 0.45),
            (665.0, 0.40, 0.25), (780.0, 0.40, 0.00))
A_VIS = {False: 2, True: 4}              # the last visible slot on each table
WIDE_UNITS = 1281                        # wide = W / k > 1281 (BS: wide = SW > 1280)
BAND_MIN_HALF = 470                      # K4 9.2: the chrome band's half width floor, units
BAND_SLACK = 20
BAND_TOP, BAND_BOTTOM = 76, 668
SHADE_RGB = (0x11, 0x11, 0x11)
CARD_BASE_RGB = (0x1B, 0x1B, 0x1D)       # the card face base (BS:84-99)
PLACEHOLDER_RGB = CARD_BASE_RGB
PLACEHOLDER_ICON = 96                    # design px, centred on the placeholder card (CAR section 2)
CLOSED_OPACITY = 0.35
STUB_MAX_HEIGHT, STUB_MAX_ASPECT = 80, 4.0
# The selection frame: a 2 px rgba(255,255,255,.9) square frame whose outer edge is 8 units
# outside the card (BS:87: left/top/right/bottom -8 with its 2 px border inside that box).
OUTLINE_WIDTH, OUTLINE_OFFSET, OUTLINE_ALPHA = 2, 6, 0.90
BADGE_SIZE, BADGE_INSET = 30, 12
BADGE_SHADOW = (2, 8, 0.45)              # offset y, blur, alpha
BADGE_STEPS = 64                         # B4: badge and chip scales quantised to 1/64
# The snap chip (K4 9.3): left 12 / top 12, padding 4 x 8, rgba(18,18,20,.72), a 16 px rect + HALF
# glyph (stroke 2), gap 6, then Left / Right at 12 px 600.
CHIP_INSET, CHIP_PAD_X, CHIP_PAD_Y, CHIP_ICON, CHIP_GAP, CHIP_PX = 12, 8, 4, 16, 6, 12
CHIP_RGB, CHIP_A = (18, 18, 20), 0.72
SNAP_BADGE = {"left": "Left", "right": "Right"}                                  # overlay.picker.badge
SNAPPED_DESC = {"left": " · Snapped left", "right": " · Snapped right"}  # overlay.picker.desc_snapped
# The label (K4 9.3; BS:102-109): a 900-unit column at left 190, top 512 (468 before the tray),
# centred, gap 6: app row (18 px icon + 15 px name at .92), title 26/32 600, description 15 at .86.
LABEL_LEFT, LABEL_TOP, LABEL_WIDTH = 190, 512, 900
LABEL_ROWS = ((0, 20, 15, 400, 0.92, 0.0), (26, 32, 26, 600, 1.00, 0.0), (64, 20, 15, 400, 0.86, 0.0))
LABEL_HEIGHT = 84
LABEL_ICON, LABEL_ICON_GAP = 18, 8
LABEL_TEXT_SHADOWS = ((1, 2, 0.60),)     # No background: 0 1px 2px rgba(0,0,0,.6) (App B S01:536)
# Dots (K4 7.4 / 9.3): fixed 6 x 6 white squares at 0.40, pitch 14, top 622 (578 before the tray),
# plus a solid 6 x 6 marker translating over 420 ms; at most DOTS_CAP dots (S5-9).
DOTS_TOP, DOT_SIZE, DOT_PITCH, DOT_OPACITY = 622, 6, 14, 0.40
DOTS_CAP = (STAGE_W - 128 + 8) // DOT_PITCH          # 82
DOTS_END_FADES = (0.10, 0.20, 0.30)                   # the outermost three when more lie beyond
# The label and dots layers (B2): stage units (x, y, w, h) at the resting (tray shown) position.
LABEL_LAYER = (0, LABEL_TOP - 8, STAGE_W, LABEL_HEIGHT + 16)
DOTS_LAYER = (0, DOTS_TOP - 4, STAGE_W, DOT_SIZE + 8)
# The snap tray (K4 9.4; BS:62-79): a full-width container at top 104, slots centred with gap 14.
TRAY_TOP, SLOT_W, SLOT_H, SLOT_GAP = 104, 176, 110, 14
SLOT_X = {"left": 457, "right": 647}
CAPTION_GAP, CAPTION_H, CAPTION_KEY, CAPTION_PX, CAPTION_KEY_PX, CAPTION_KEY_GAP = 6, 16, 16, 12, 10, 6
TRAY_H = SLOT_H + CAPTION_GAP + CAPTION_H
TRAY_CX, TRAY_CY = STAGE_W / 2, TRAY_TOP + TRAY_H / 2
SLOT_BG_A = 0.04
SLOT_BORDERS = {"empty": ((255, 255, 255), 0.40, True), "filled": ((255, 255, 255), 0.50, False),
                "failure": ((255, 132, 116), 0.90, False)}
SLOT_GLYPH, SLOT_GLYPH_A = 34, 0.80
SLOT_BADGE, SLOT_BADGE_INSET = 22, 8
SLOT_KEYS = {"left": "2", "right": "3"}
CAPTION_INKS = {"normal": ((255, 255, 255), 0.86), "keep": ((255, 255, 255), 0.70), "failure": ((255, 132, 116), 1.0)}
KEEP_OPACITY = 0.35
DASH, DASH_GAP = 3, 3                    # units: the 1 px dashed border's pattern
HALF_BOXES = {"left": (3, 5, 12, 19), "right": (12, 5, 21, 19)}   # BS HALF, in the icon's 24 viewBox
# The toast (K4 10.1): centred on the stage at top 588, padding 12 x 18, 15 px, 1 px border .2.
TOAST_TOP, TOAST_PAD_X, TOAST_PAD_Y, TOAST_PX = 588, 18, 12, 15
TOAST_TINT, TOAST_TINT_A, TOAST_BLUR, TOAST_BORDER_A = (24, 24, 26), 0.62, 24, 0.20
TOAST_FALLBACK_A = 0.88
TOAST_TEXT_MAX = 900                     # design px: the toast's text fits the label's column (S5-22)
# Card shadows (K4 9.3; BS:85-86): two fixed layers per card, the same on both backgrounds (S5-20).
CARD_SHADOWS = {"side": (12, 30, 0.30), "focus": (24, 60, 0.45)}  # offset y, blur, alpha (CSS blur = 2 sigma)
# The desktop dim: No background only (App B S01:536: flat rgba(0,0,0,0.55)).
DIM_ALPHA = {"glass": 0.0, "none": 0.55}
CLOSED_DESC = "Closed · can’t switch"
SEP = " · "

# The Frosted background (K4 9.2, blur.picker_frost, S5-21): capture -> reduce(8) ->
# GaussianBlur(40 k / 8) -> saturate(1.6) -> the tint rgba(10,10,12,.50) -> bilinear upscale, over
# the whole monitor. No dim, no sheen, no border, no inset lines, no pane shadow.
GLASS_REDUCE = 8
GLASS_BLUR = 40                          # CSS px: blur(40px), a standard deviation
FROST_SIGMA_DIVISOR = 1
GLASS_SATURATE = 1.6
GLASS_DIM = 1.0 - DIM_ALPHA["glass"]     # 1.0: blur.picker_frost has no dim
GLASS_TINT, GLASS_TINT_A = (10, 10, 12), 0.50
# Without a capture (it failed or timed out) the frost is the tint alone over the live desktop:
# desktop * (1 - 0.50) + tint * 0.50, i.e. alpha 0.50 (v6's fallback rule, CR:127; S5-30).
FROST_SOLID_A = 1.0 - GLASS_DIM * (1.0 - GLASS_TINT_A)
TOAST_REDUCE = 4

# Archivo metrics: OS/2 typo (USE_TYPO_METRICS) == hhea, in em.
ASCENT, DESCENT = 0.878, 0.210
LINE_NORMAL = ASCENT + DESCENT

FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
ARCHIVO_PATH = FONT_DIR / "Archivo.ttf"
SYSTEM_FONT_DIR = Path(os.environ.get("WINDIR") or r"C:\Windows") / "Fonts"
# Fallback order (section 8) per weight: Segoe UI, Segoe UI Symbol, Segoe UI Emoji (colour),
# Microsoft YaHei, Malgun Gothic, Yu Gothic.
FALLBACK_FILES = {
    400: ("segoeui.ttf", "seguisym.ttf", "seguiemj.ttf", "msyh.ttc", "malgun.ttf", "YuGothR.ttc"),
    600: ("seguisb.ttf", "seguisym.ttf", "seguiemj.ttf", "msyhbd.ttc", "malgunbd.ttf", "YuGothB.ttc"),
    700: ("segoeuib.ttf", "seguisym.ttf", "seguiemj.ttf", "msyhbd.ttc", "malgunbd.ttf", "YuGothB.ttc"),
}
COLOUR_FONTS = frozenset({"seguiemj.ttf"})
# BMP code points with Emoji_Presentation=Yes (Unicode emoji-data.txt): emoji by default, even
# without VS16 (every such code point at U+1F000 and above is covered by that range test).
EMOJI_PRESENTATION_BMP = (
    (0x231A, 0x231B), (0x23E9, 0x23EC), (0x23F0, 0x23F0), (0x23F3, 0x23F3), (0x25FD, 0x25FE),
    (0x2614, 0x2615), (0x2648, 0x2653), (0x267F, 0x267F), (0x2693, 0x2693), (0x26A1, 0x26A1),
    (0x26AA, 0x26AB), (0x26BD, 0x26BE), (0x26C4, 0x26C5), (0x26CE, 0x26CE), (0x26D4, 0x26D4),
    (0x26EA, 0x26EA), (0x26F2, 0x26F3), (0x26F5, 0x26F5), (0x26FA, 0x26FA), (0x26FD, 0x26FD),
    (0x2705, 0x2705), (0x270A, 0x270B), (0x2728, 0x2728), (0x274C, 0x274C), (0x274E, 0x274E),
    (0x2753, 0x2755), (0x2757, 0x2757), (0x2795, 0x2797), (0x27B0, 0x27B0), (0x27BF, 0x27BF),
    (0x2B1B, 0x2B1C), (0x2B50, 0x2B50), (0x2B55, 0x2B55),
)
_EMOJI_BMP_STARTS = tuple(start for start, _ in EMOJI_PRESENTATION_BMP)
VS15, VS16 = "︎", "️"


def emoji_presentation(text, i):
    """Whether ``text[i]`` is drawn as a (colour) emoji: followed by VS16, or not followed by
    VS15 and either at U+1F000 or above or a BMP code point with Emoji_Presentation=Yes
    (U+2705, U+2B50, U+26A1, ...)."""
    following = text[i + 1] if i + 1 < len(text) else ""
    if following == VS16:
        return True
    if following == VS15:
        return False
    cp = ord(text[i])
    if cp >= 0x1F000:
        return True
    j = bisect.bisect_right(_EMOJI_BMP_STARTS, cp) - 1
    return j >= 0 and cp <= EMOJI_PRESENTATION_BMP[j][1]

SimpleLabel = namedtuple("SimpleLabel", "app title desc")


# ============================================================ layout math (K4 sections 9.2-9.5)
def stage_scale(width, height):
    """k = min(monW / 1280, monH / 720) (2.0 on the user's 5120 x 1440 monitor)."""
    width, height = max(1, int(width)), max(1, int(height))
    return min(width / STAGE_W, height / STAGE_H)


def table_for(wide):
    return TABLE_32 if wide else TABLE_16


@dataclass(frozen=True)
class Layout:
    """The picker on one monitor (physical px; the process is per-monitor DPI aware).

    ``monitor`` / ``work`` are rcMonitor / rcWork (left, top, right, bottom). The host window
    covers rcMonitor (``host``); every thumbnail rect is host-local. ``pane`` is the stage's
    1140 x 560 card area (x, y, w, h): ``presenter.rect`` (CAROUSEL.md section 11). ``band`` is
    the chrome window (x, y, w, h): x = stage centre +- max(X[a_vis] + 200 S[a_vis] + 20, 470)
    units, y 76-668 units, clamped to the monitor (K4 9.2). ``labels`` / ``dots`` are the B2
    layer windows at the resting position (the cards group moves them by its shift). ``wide``
    selects the 32:9 table (W / k > 1281)."""
    k: float
    monitor: tuple
    stage_x: float
    stage_y: float
    pane: tuple
    band: tuple
    labels: tuple
    dots: tuple
    work: tuple
    wide: bool = False

    @property
    def table(self):
        return table_for(self.wide)

    @property
    def a_max(self):
        return len(self.table) - 1

    @property
    def a_vis(self):
        return A_VIS[bool(self.wide)]

    @property
    def register_distance(self):
        """Thumbnails are registered for |d| <= a_vis + 1 (K4 9.3)."""
        return self.a_vis + 1

    @property
    def monitor_rect(self):
        l, t, r, b = self.monitor
        return (l, t, r - l, b - t)

    @property
    def host(self):
        return self.monitor_rect

    @property
    def chrome(self):
        return self.band

    @property
    def band_origin(self):
        """The band's top-left in host-local px (chrome-local = host-local - this)."""
        return (self.band[0] - self.monitor[0], self.band[1] - self.monitor[1])

    @property
    def stage(self):
        return (round(self.stage_x), round(self.stage_y), round(STAGE_W * self.k), round(STAGE_H * self.k))

    def host_point(self, sx, sy):
        """Stage units -> host-local physical px (floats)."""
        return (self.stage_x - self.monitor[0] + sx * self.k, self.stage_y - self.monitor[1] + sy * self.k)

    def screen_point(self, sx, sy):
        return (self.stage_x + sx * self.k, self.stage_y + sy * self.k)

    def half(self, side):
        """The rcWork half (left, top, right, bottom) for ``side`` (K4 9.6 step 2)."""
        return work_half(self.work, side)


def work_half(work, side):
    """The left or right half of ``work`` (l, t, r, b); with an odd width the right half takes the
    extra pixel (K4 9.6 step 2). ``side`` must be 'left' or 'right': anything else raises
    ValueError (never a silent right half; WP7b-R1)."""
    if side not in ("left", "right"):
        raise ValueError(f"work_half: side must be 'left' or 'right', not {side!r}")
    l, t, r, b = (int(v) for v in work)
    middle = l + (r - l) // 2
    return (l, t, middle, b) if side == "left" else (middle, t, r, b)


def _clamped(x0, y0, x1, y1, monitor):
    ml, mt, mr, mb = monitor
    x0, y0 = max(ml, round(x0)), max(mt, round(y0))
    x1, y1 = min(mr, round(x1)), min(mb, round(y1))
    return (x0, y0, max(1, x1 - x0), max(1, y1 - y0))


def layout_for(monitor, work=None):
    """Layout for rcMonitor ``(left, top, right, bottom)`` (and rcWork, else the monitor)."""
    left, top, right, bottom = (int(v) for v in monitor)
    width, height = max(1, right - left), max(1, bottom - top)
    k = stage_scale(width, height)
    wide = width / k > WIDE_UNITS
    sx = left + (width - STAGE_W * k) / 2
    sy = top + (height - STAGE_H * k) / 2
    pane = (round(sx + PANE_X * k), round(sy + PANE_Y * k), round(PANE_W * k), round(PANE_H * k))
    x, s, _ = table_for(wide)[A_VIS[wide]]
    half = max(x + CARD_W / 2 * s + BAND_SLACK, BAND_MIN_HALF)
    cx = sx + CENTER_X * k
    band = _clamped(cx - half * k, sy + BAND_TOP * k, cx + half * k, sy + BAND_BOTTOM * k, (left, top, right, bottom))
    labels = _clamped(sx + LABEL_LAYER[0] * k, sy + LABEL_LAYER[1] * k, sx + (LABEL_LAYER[0] + LABEL_LAYER[2]) * k,
                      sy + (LABEL_LAYER[1] + LABEL_LAYER[3]) * k, (left, top, right, bottom))
    dots = _clamped(sx + DOTS_LAYER[0] * k, sy + DOTS_LAYER[1] * k, sx + (DOTS_LAYER[0] + DOTS_LAYER[2]) * k,
                    sy + (DOTS_LAYER[1] + DOTS_LAYER[3]) * k, (left, top, right, bottom))
    work = tuple(int(v) for v in work) if work else (left, top, right, bottom)
    return Layout(k, (left, top, right, bottom), sx, sy, pane, band, labels, dots, work, bool(wide))


def table_state(d, wide=False):
    """(signed offset X, scale, opacity, shade) of a card at distance ``d = i - sel``."""
    table = table_for(wide)
    a = min(abs(int(d)), len(table) - 1)
    x, s, op = table[a]
    shade = min(0.55, 0.22 * min(abs(int(d)), len(table) - 1))
    return ((1 if d > 0 else -1 if d < 0 else 0) * x, s, op, shade)


def thumb_opacity(op, shade):
    """DWM thumbnail opacity o = op (1 - s) / (1 - op s) under a chrome #111 shade at op s, so
    thumbnail + shade match CSS group opacity ``op`` over a shaded card (CAR section 2; K4 9.3)."""
    op, shade = max(0.0, min(1.0, op)), max(0.0, min(1.0, shade))
    den = 1.0 - op * shade
    return 0.0 if den <= 1e-9 else max(0.0, min(1.0, op * (1.0 - shade) / den))


def shade_alpha(op, shade):
    """The chrome's #111 shade alpha, op * s."""
    return max(0.0, min(1.0, op)) * max(0.0, min(1.0, shade))


def cover_source(source_size, dest):
    """rcSource for a cover-fit, top-aligned thumbnail: k' = max(W/sw, H/sh),
    ((sw - W/k')/2, 0, (sw + W/k')/2, H/k'). ``dest`` is (l, t, r, b) or (W, H)."""
    sw, sh = (int(v) for v in source_size)
    if len(dest) == 4:
        w, h = dest[2] - dest[0], dest[3] - dest[1]
    else:
        w, h = dest
    if sw <= 0 or sh <= 0 or w <= 0 or h <= 0:
        return (0, 0, max(1, sw), max(1, sh))
    scale = max(w / sw, h / sh)
    cw, ch = w / scale, h / scale
    return (round((sw - cw) / 2), 0, round((sw + cw) / 2), round(ch))


def is_caption_stub(source_size):
    """A minimized window that was never shown restored: DWM's source is its caption bar
    (height <= 80 px or aspect > 4). The card then uses the placeholder."""
    if not source_size:
        return True
    sw, sh = (int(v) for v in source_size)
    return sh <= STUB_MAX_HEIGHT or sw <= 0 or sw / max(1, sh) > STUB_MAX_ASPECT


def card_rect(layout, x, s, y=0.0):
    """Integer host-local rect (l, t, r, b) of a card at design offset ``x`` (bump included),
    scale ``s`` and vertical offset ``y`` units (the cards group shift and the open's rise):
    computed once per frame and shared by thumbnails and chrome."""
    k = layout.k
    cx, cy = layout.host_point(CENTER_X + x, CENTER_Y + y)
    w, h = max(0, round(CARD_W * k * s)), max(0, round(CARD_H * k * s))
    left, top = round(cx - w / 2), round(cy - h / 2)
    return (left, top, left + w, top + h)


def fly_target(layout, side, work=None):
    """The snap fly's end rect (l, t, r, b), host-local floats (K4 9.5; BS:1080-1081): the card's
    box scaled by kf = min(halfW / (400 k), workH / (250 k)) and centred in the rcWork half.

    ``side`` is 'left' / 'right' (that half of ``work``, else of rcWork) or the half itself as a
    screen-px rect (l, t, r, b), e.g. a snap job's own target, so the fly ends where the window
    is placed. (WP7b-R1: a rect used to be read as a side name and every left snap flew right.)"""
    if isinstance(side, str):
        l, t, r, b = work_half(work or layout.work, side)
    else:
        half = tuple(side)
        if len(half) != 4:
            raise ValueError(f"fly_target: a half rect is (l, t, r, b), not {side!r}")
        l, t, r, b = (float(v) for v in half)
    k = layout.k
    hw, hh = r - l, b - t
    kf = min(hw / (CARD_W * k), hh / (CARD_H * k))
    w, h = CARD_W * k * kf, CARD_H * k * kf
    x = l + (hw - w) / 2 - layout.monitor[0]
    y = t + (hh - h) / 2 - layout.monitor[1]
    return (x, y, x + w, y + h)


def fly_rect(start, target, e):
    """The fly at eased progress ``e``: translate + uniform scale about the top-left
    (``transform-origin: 0 0``, CSS interpolation of translate() scale()): the top-left moves
    linearly and the size scales by 1 + (kr - 1) e, kr = target width / start width. Integer
    (l, t, r, b)."""
    x0, y0, x1, y1 = start
    tx0, ty0, tx1, ty1 = target
    w0, h0 = x1 - x0, y1 - y0
    kr = (tx1 - tx0) / w0 if w0 > 0 else 1.0
    scale = 1.0 + (kr - 1.0) * e
    x, y = x0 + (tx0 - x0) * e, y0 + (ty0 - y0) * e
    left, top = round(x), round(y)
    return (left, top, left + max(0, round(w0 * scale)), top + max(0, round(h0 * scale)))


def tray_transform(ty, sc):
    """The tray's spring transform (translateY ``ty`` units, scale ``sc`` about the tray
    container's centre, K4 9.4): stage units -> stage units."""
    def apply(x, y):
        return (TRAY_CX + (x - TRAY_CX) * sc, TRAY_CY + (y - TRAY_CY) * sc + ty)
    return apply


def slot_rect(layout, side, ty=0.0, sc=1.0):
    """The slot's content box (l, t, r, b), host-local ints, under the tray transform."""
    apply = tray_transform(ty, sc)
    x0, y0 = apply(SLOT_X[side], TRAY_TOP)
    x1, y1 = apply(SLOT_X[side] + SLOT_W, TRAY_TOP + SLOT_H)
    (l, t), (r, b) = layout.host_point(x0, y0), layout.host_point(x1, y1)
    return (round(l), round(t), round(r), round(b))


# ============================================================ frost (K4 9.2 blur.picker_frost; section 12)
def glass_sigma(k, blur=GLASS_BLUR, reduce=GLASS_REDUCE):
    """GaussianBlur sigma at the reduced scale for a CSS ``blur(<blur>px)`` filter: the CSS
    value is the standard deviation, so blur * k / reduce (12 for the toast's blur(24px) at
    reduce 4 and k = 2). The box-shadow and text-shadow blurs elsewhere use blur / 2, which is
    correct for those. The frost uses frost_sigma."""
    return max(0.1, blur * float(k) / reduce)


def frost_sigma(k, reduce=GLASS_REDUCE):
    """The frost's GaussianBlur sigma at the reduced scale: 40 * k / 8, which is 10 at k = 2
    (blur.picker_frost's CSS blur(40px) as a standard deviation; K4 9.2)."""
    return max(0.1, glass_sigma(k, GLASS_BLUR, reduce) / FROST_SIGMA_DIVISOR)


def _saturate_matrix(s):
    return (0.213 + 0.787 * s, 0.715 - 0.715 * s, 0.072 - 0.072 * s, 0,
            0.213 - 0.213 * s, 0.715 + 0.285 * s, 0.072 - 0.072 * s, 0,
            0.213 - 0.213 * s, 0.715 - 0.715 * s, 0.072 + 0.928 * s, 0)


def _tint_matrix(dim, rgb, alpha):
    c = dim * (1 - alpha)
    return (c, 0, 0, rgb[0] * alpha, 0, c, 0, rgb[1] * alpha, 0, 0, c, rgb[2] * alpha)


_SATURATE = _saturate_matrix(GLASS_SATURATE)
_GLASS_TINT = _tint_matrix(GLASS_DIM, GLASS_TINT, GLASS_TINT_A)
_TOAST_TINT = _tint_matrix(1.0, TOAST_TINT, TOAST_TINT_A)


def _frost_small(image, k):
    """The frost at the reduced scale: (small RGB image, full size). Every per-pixel step runs
    on the reduced image: reduce(8) -> GaussianBlur(40 k / 8) -> CSS saturate(1.6) (Rec.709) ->
    the tint rgba(10,10,12,.50) (blur.picker_frost: no dim)."""
    source = image if image.mode == "RGB" else image.convert("RGB")      # an RGB capture is not copied
    w, h = source.size
    factor = GLASS_REDUCE if min(w, h) >= GLASS_REDUCE * 2 else 1
    small = source.reduce(factor) if factor > 1 else source.copy()
    small = small.filter(ImageFilter.GaussianBlur(frost_sigma(k, factor)))
    return small.convert("RGB", _SATURATE).convert("RGB", _GLASS_TINT), (w, h)


def frost(image, k):
    """The Frosted background from a capture of the whole monitor (K4 9.2): the reduced-scale
    pipeline (_frost_small), then a bilinear upscale. No sheen, no border, no inset lines. An
    opaque straight RGBA image of the capture's size (previews, the smoke test, tests)."""
    small, size = _frost_small(image, k)
    big = small.resize(size, Image.Resampling.BILINEAR) if small.size != size else small
    return big.convert("RGBA")


glass = frost      # the historical name: the setting is still "glass" and the frozen smoke test calls it


def frost_canvas(image, k):
    """``frost`` laid out as the 32-bit DIB wants it: an opaque premultiplied Canvas (B, G, R,
    255). The bands are swapped on the reduced image and the upscale runs in mode RGBX, so the
    capture thread makes one full-size image and the carousel thread only copies it into the
    glass window's DIB (no conversion and no second full-size copy there)."""
    small, size = _frost_small(image, k)
    r, g, b = small.split()
    bgrx = Image.merge("RGB", (b, g, r)).convert("RGBX")               # the 4th byte is 255
    big = bgrx.resize(size, Image.Resampling.BILINEAR) if bgrx.size != size else bgrx
    return Canvas(big)


def solid_frost(size):
    """The frost without a capture (it failed or timed out): the tint alone over the live
    desktop (translucent, FROST_SOLID_A = 0.50), as a premultiplied Canvas. One uniform fill:
    nothing per pixel is computed."""
    w, h = (max(1, int(v)) for v in size)
    ink = tuple(round(c * GLASS_TINT_A) for c in GLASS_TINT)             # premultiplied: tint * 0.50
    return Canvas(Image.new("RGBX", (w, h), (ink[2], ink[1], ink[0], round(255 * FROST_SOLID_A))))


OPAQUE_PANE_BASE = (8, 8, 9)


def opaque_pane_rgb():
    """The plain host's flat colour (the tint over a near-black base), which it fills in its
    WM_PAINT until the frost arrives, and keeps when there is no capture: nothing is built on
    the open's path."""
    return tuple(round(t * GLASS_TINT_A + b * (1.0 - GLASS_TINT_A)) for t, b in zip(GLASS_TINT, OPAQUE_PANE_BASE))


def toast_backdrop(image, k):
    """The toast's glass (blur.toast): blur(24) and the tint rgba(24,24,26,.62) (saturate 1, no dim)."""
    source = image.convert("RGB")
    w, h = source.size
    factor = TOAST_REDUCE if min(w, h) >= TOAST_REDUCE * 2 else 1
    small = source.reduce(factor) if factor > 1 else source.copy()
    small = small.filter(ImageFilter.GaussianBlur(glass_sigma(k, TOAST_BLUR, factor)))
    small = small.convert("RGB", _TOAST_TINT)
    return (small.resize((w, h), Image.Resampling.BILINEAR) if small.size != (w, h) else small).convert("RGBA")


# ============================================================== premultiplied helpers
def premultiplied_bgra(image):
    """Straight RGBA (or RGB) -> premultiplied BGRA bytes (the 32-bit DIB layout)."""
    if image.mode == "RGB":
        return image.convert("RGBA").tobytes("raw", "BGRA")
    image = image.convert("RGBA")
    if image.getchannel("A").getextrema() == (255, 255):
        return image.tobytes("raw", "BGRA")           # opaque: premultiplied == straight
    return image.convert("RGBa").tobytes("raw", "BGRa")


def straight_image(image_bgra_pm):
    """A premultiplied-BGRA canvas image (mode RGBX or RGBA) -> straight RGBA (previews, tests)."""
    return Image.frombuffer("RGBa", image_bgra_pm.size, image_bgra_pm.tobytes(), "raw", "BGRa", 0, 1).convert("RGBA")


def _lut(alpha):
    """A 256-entry scale table for an 'L' mask (cached per 8-bit level)."""
    return _lut_level(byte_level(alpha))


@functools.lru_cache(maxsize=258)
def _lut_level(level):
    alpha = level / 255
    return tuple(round(v * alpha) for v in range(256))


def _point(image, table):
    """``image.point(table)`` for an integer table, without Pillow's per-call Python rounding of
    the table (Image.point rounds every entry again: 1024 calls for an RGBX table, about 0.1 ms
    a call on the frame path)."""
    try:
        return image._new(image.im.point(table, None))
    except Exception:
        return image.point(list(table))


INK_VIEW_MAX = 4096 * 2048          # px: larger requests paste the colour directly
_INKS = {}                              # ink -> (bytes, w, h)
_INKS_LOCK = threading.Lock()


def _ink_view(ink, w, h):
    """A w x h RGBX image of the solid ``ink`` (B, G, R, 255) as a zero-copy view of one cached
    buffer per ink (Image.frombuffer with the buffer's row stride), or None past INK_VIEW_MAX.
    Pasting it through a mask gives the same bytes as ``paste(ink, box, mask)`` (Pillow's
    paste_mask_L and fill_mask_L share the BLEND arithmetic) at about 0.4x the cost on Pillow 12
    (fill_mask compares the mode string per channel). The buffer only grows (P7: no large
    allocation per frame): to the largest shadow band, about 2.4 MB at k = 2."""
    w, h = int(w), int(h)
    if w <= 0 or h <= 0:
        return None
    entry = _INKS.get(ink)
    if entry is None or entry[1] < w or entry[2] < h:
        with _INKS_LOCK:
            entry = _INKS.get(ink)
            if entry is None or entry[1] < w or entry[2] < h:
                bw = max(w, entry[1] if entry else 0)
                bh = max(h, entry[2] if entry else 0)
                bw, bh = -(-bw // 64) * 64, -(-bh // 64) * 64
                if bw * bh > INK_VIEW_MAX:
                    return None
                entry = (bytes(bytearray(ink)) * (bw * bh), bw, bh)
                _INKS[ink] = entry
    data, bw, _bh = entry
    return Image.frombuffer("RGBX", (w, h), data, "raw", "RGBX", bw * 4, 1)


def _paste_ink(image, ink, box, mask):
    """``image.paste(ink, box, mask)`` through an ink view (see _ink_view)."""
    try:
        view = _ink_view(tuple(ink), box[2] - box[0], box[3] - box[1])
    except (TypeError, ValueError):                    # not four byte values: Pillow's own path
        view = None
    if view is None:
        image.paste(ink, box, mask)
    else:
        _core_paste(image, view, box, mask)


def _core_paste(image, source, box, mask=None):
    """``image.paste(source, box, mask)`` for a same-mode ``source`` image of exactly the box's
    size (or a colour tuple) and an 'L' mask: Pillow's own core call without the wrapper's
    checks (about 5 us a call, ~70 calls a frame on the 32:9 table). Falls back to
    Image.paste for anything else."""
    try:
        core = image.im
        box = (int(box[0]), int(box[1]), int(box[2]), int(box[3]))
        src = source if source.__class__ is tuple else source.im
        if mask is None:
            core.paste(src, box)
        else:
            core.paste(src, box, mask.im)
    except Exception:
        image.paste(source, box if source.__class__ is tuple else box[:2], mask)


def _core_resize(image, size, resample, box):
    """``image.resize(size, resample, box=box)`` for an 'L' image through the core call."""
    try:
        return image._new(image.im.resize(size, resample, box))
    except Exception:
        return image.resize(size, resample, box=box)


def _pm(rgb, alpha):
    """Premultiplied fill tuple in the B, G, R, A band order."""
    r, g, b = rgb
    a = max(0.0, min(1.0, alpha))
    return (round(b * a), round(g * a), round(r * a), round(255 * a))


FADE_EPSILON = 0.5 / 255


def byte_level(value):
    """A 0..1 value as the 8-bit level the canvas can store (0..255)."""
    return max(0, min(255, round(255 * float(value))))


def fade_lut(keep, rgb=(0, 0, 0), alpha=0.0):
    """A per-band point() table for a premultiplied canvas (bands B, G, R, A): every byte
    scaled by ``keep``, then the solid ``rgb`` at ``alpha`` source-over, v * keep * (1 - alpha)
    + c * alpha. ``keep`` and ``alpha`` count in 8-bit levels (what a byte can hold), so the
    tables are cached: animations reuse them frame after frame. With v = 0 it gives the same
    bytes as ``_pm(rgb, byte_level(alpha) / 255)``."""
    return _fade_table(byte_level(keep), byte_level(alpha), rgb if rgb.__class__ is tuple else tuple(rgb))


@functools.lru_cache(maxsize=512)
def _fade_table(keep_level, alpha_level, rgb):
    a = alpha_level / 255
    factor = keep_level / 255 * (1.0 - a)
    r, g, b = (int(c) for c in rgb)
    table = []
    for c in (b, g, r, 255):
        base = round(c * a)
        exact = c * a
        table.extend(base if v == 0 else min(255, int(v * factor + exact + 0.5)) for v in range(256))
    return tuple(table)


class Canvas:
    """A premultiplied-BGRA surface wrapped in a PIL 'RGBX' image (see the module docstring).
    ``image`` may share memory with a DIB (Image.frombuffer) or be a plain image (previews)."""

    def __init__(self, image):
        if image.mode != "RGBX":
            raise ValueError("a premultiplied canvas is an RGBX image")
        self.image = image
        self.size = image.size

    @classmethod
    def new(cls, size):
        return cls(Image.new("RGBX", (max(1, int(size[0])), max(1, int(size[1]))), (0, 0, 0, 0)))

    @classmethod
    def over_buffer(cls, buffer, size):
        """A canvas sharing ``buffer`` (a writable ctypes array or address-backed array of
        w * h * 4 bytes, e.g. a DIB section's bits)."""
        image = Image.frombuffer("RGBX", (int(size[0]), int(size[1])), buffer, "raw", "RGBX", 0, 1)
        image.readonly = 0
        return cls(image)

    @staticmethod
    def _clip(box, size):
        l, t, r, b = (int(v) for v in box)
        return max(0, l), max(0, t), min(size[0], r), min(size[1], b)

    def clear(self, box=None):
        if box is None:
            _core_paste(self.image, (0, 0, 0, 0), (0, 0) + tuple(self.size))
            return
        l, t, r, b = self._clip(box, self.size)
        if r > l and b > t:
            _core_paste(self.image, (0, 0, 0, 0), (l, t, r, b))

    def content(self, box):
        """What is already drawn inside ``box``: ((l, t, r, b), a copy of those pixels) for the
        bounding box of its non-zero pixels, or None when nothing is there."""
        l, t, r, b = self._clip(box, self.size)
        if r <= l or b <= t:
            return None
        part = self.image.crop((l, t, r, b))
        bbox = part.getbbox()                          # RGBX: any of the four bytes non-zero
        if bbox is None:
            return None
        if bbox != (0, 0, r - l, b - t):
            part = part.crop(bbox)
        return (l + bbox[0], t + bbox[1], l + bbox[2], t + bbox[3]), part

    def fade(self, box, keep):
        """Scale every premultiplied byte inside ``box`` by ``keep``: what lies under a card
        that covers it at 1 - keep. ``keep`` <= 0 clears; >= 1 changes nothing."""
        if keep <= FADE_EPSILON:
            self.clear(box)
            return
        if keep >= 1.0 - FADE_EPSILON:
            return
        below = self.content(box)
        if below is not None:
            (l, t, _r, _b), pixels = below
            self.image.paste(_point(pixels, fade_lut(keep)), (l, t))

    def fill(self, box, rgb, alpha):
        """Overwrite ``box`` with a premultiplied colour."""
        l, t, r, b = self._clip(box, self.size)
        if r > l and b > t:
            _core_paste(self.image, _pm(rgb, alpha), (l, t, r, b))

    def over(self, box, rgb, alpha):
        """Source-over of a solid colour at constant ``alpha``."""
        l, t, r, b = self._clip(box, self.size)
        if r <= l or b <= t or alpha <= 0.0:
            return
        if alpha >= 1.0:
            self.fill((l, t, r, b), rgb, 1.0)
            return
        mask = Image.new("L", (r - l, b - t), round(255 * alpha))
        self.image.paste((rgb[2], rgb[1], rgb[0], 255), (l, t, r, b), mask)

    def over_mask(self, rgb, mask, xy, exclude=None):
        """Source-over of a solid colour through an 'L' mask placed at ``xy``; ``exclude``
        (l, t, r, b) is skipped (a card's own rect, cleared right after its shadow)."""
        x, y = int(xy[0]), int(xy[1])
        mw, mh = mask.size
        ink = (rgb[2], rgb[1], rgb[0], 255)
        if exclude is None:
            self._paste_mask(ink, mask, x, y, (x, y, x + mw, y + mh))
            return
        el, et, er, eb = exclude
        top, bottom = max(y, et), min(y + mh, eb)
        for band in ((x, y, x + mw, min(et, y + mh)), (x, max(eb, y), x + mw, y + mh),
                     (x, top, min(el, x + mw), bottom), (max(er, x), top, x + mw, bottom)):
            self._paste_mask(ink, mask, x, y, band)

    def _paste_mask(self, ink, mask, x, y, band):
        l, t, r, b = self._clip(band, self.size)
        if r <= l or b <= t:
            return
        part = mask.crop((l - x, t - y, r - x, b - y))
        _paste_ink(self.image, ink, (l, t, r, b), part)

    def over_sprite(self, sprite, xy, alpha=1.0):
        """Source-over of a straight-colour sprite at global ``alpha``."""
        if sprite is None or alpha <= 0.0:
            return
        x, y = int(round(xy[0])), int(round(xy[1]))
        w, h = sprite.size
        l, t, r, b = self._clip((x, y, x + w, y + h), self.size)
        if r <= l or b <= t:
            return
        mask = sprite.mask if alpha >= 1.0 else _point(sprite.mask, _lut(alpha))
        box = (l - x, t - y, r - x, b - y)
        if (r - l, b - t) != (w, h):
            mask = mask.crop(box)
        if sprite.colour_image is None:
            _paste_ink(self.image, sprite.colour, (l, t, r, b), mask)
        else:
            colour = sprite.colour_image if (r - l, b - t) == (w, h) else sprite.colour_image.crop(box)
            _core_paste(self.image, colour, (l, t, r, b), mask)

    def paste_premultiplied(self, image, xy):
        """Overwrite with a premultiplied RGBX ``image`` at ``xy`` (clipped): what a sprite over a
        cleared canvas gives, without a mask (the toast frame)."""
        x, y = int(round(xy[0])), int(round(xy[1]))
        w, h = image.size
        l, t, r, b = self._clip((x, y, x + w, y + h), self.size)
        if r <= l or b <= t:
            return
        part = image if (r - l, b - t) == (w, h) else image.crop((l - x, t - y, r - x, b - y))
        _core_paste(self.image, part, (l, t, r, b))

    def rect_outline(self, rect, width, rgb, alpha):
        l, t, r, b = rect
        w = max(1, int(width))
        for band in ((l, t, r, t + w), (l, b - w, r, b), (l, t + w, l + w, b - w), (r - w, t + w, r, b - w)):
            self.over(band, rgb, alpha)

    def straight(self):
        return straight_image(self.image)


class Sprite:
    """Straight colour in B, G, R order with a 4th byte of 255 (``colour_image``, mode RGBX) or one solid
    ``colour`` tuple, plus the alpha ``mask`` ('L'); see Canvas for the paste arithmetic."""
    __slots__ = ("colour", "colour_image", "mask", "size")

    def __init__(self, mask, colour=(255, 255, 255, 255), colour_image=None):
        self.mask = mask
        self.colour = colour
        self.colour_image = colour_image
        self.size = mask.size

    @classmethod
    def from_image(cls, image):
        """From a straight RGBA PIL image."""
        image = image.convert("RGBA")
        r, g, b, a = image.split()
        opaque = Image.new("L", image.size, 255)
        return cls(a, colour_image=Image.merge("RGBX", (b, g, r, opaque)))

    @classmethod
    def solid(cls, mask, rgb):
        return cls(mask, colour=(rgb[2], rgb[1], rgb[0], 255))

    def resized(self, size, resample=Image.Resampling.BILINEAR):
        """A resampled copy. A solid sprite resizes its mask only. A coloured one is resized in
        premultiplied form (Pillow premultiplies an RGBA resize: RGBA -> RGBa -> resize -> RGBA),
        so the black colour of fully transparent pixels never bleeds into, and darkens, the
        edges of badges, placeholder icons and the toast pill."""
        size = (max(1, int(size[0])), max(1, int(size[1])))
        if size == self.size:
            return self
        if self.colour_image is None:
            return Sprite(self.mask.resize(size, resample), self.colour)
        b, g, r, _ = self.colour_image.split()
        b, g, r, a = Image.merge("RGBA", (b, g, r, self.mask)).resize(size, resample).split()
        return Sprite(a, colour_image=Image.merge("RGBX", (b, g, r, Image.new("L", size, 255))))

    def straight(self):
        """The straight RGBA image (tests, previews)."""
        if self.colour_image is not None:
            b, g, r, _ = self.colour_image.split()
            return Image.merge("RGBA", (r, g, b, self.mask))
        image = Image.new("RGBA", self.size, (self.colour[2], self.colour[1], self.colour[0], 255))
        image.putalpha(self.mask)
        return image


# ============================================================ shadows (box-shadow)
def _blurred_box(size, box, sigma, alpha, hole=None):
    """An 'L' mask: ``box`` filled with ``alpha`` then blurred by ``sigma``; ``hole`` cleared."""
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle(box, fill=round(255 * max(0.0, min(1.0, alpha))))
    if sigma > 0.05:
        mask = mask.filter(ImageFilter.GaussianBlur(sigma))
    if hole is not None:
        mask.paste(0, hole)
    return mask


def _phi(z):
    """The standard normal CDF."""
    return 0.5 * math.erfc(-z / math.sqrt(2.0))


def shadow_reach(alpha):
    """How far (in sigma) a Gaussian-blurred edge of peak ``alpha`` stays visible in 8 bits:
    the z where alpha * Phi(-z) drops below half a step (2.62 for .45, 2.72 for .6). Pixels
    beyond it round to 0, so the shadow's pad stops there instead of at 3 sigma."""
    target = 0.5 / (255.0 * max(1e-6, min(1.0, float(alpha))))
    if target >= 0.5:
        return 0.0
    low, high = 0.0, 10.0
    for _ in range(48):
        middle = (low + high) / 2
        if _phi(-middle) > target:
            low = middle
        else:
            high = middle
    return high


def _edge_profile(count, step, start, length, sigma):
    """Samples at pixel centres ((i + 0.5) * step) of a 1-D box [start, start + length]
    convolved with a Gaussian of ``sigma``: Phi((u - start)/sigma) - Phi((u - start - length)/sigma)."""
    out = []
    for i in range(count):
        u = (i + 0.5) * step
        out.append(max(0.0, min(1.0, _phi((u - start) / sigma) - _phi((u - start - length) / sigma))))
    return out


SHADOW_INK = (0, 0, 0, 255)             # black source-over (B, G, R, 255)


class ShadowCache:
    """Card box-shadows (K4 9.3; BS:85-86) for one k: two fixed layers per card, the side shadow
    ``0 12px 30px rgba(0,0,0,.30)`` and the focus shadow ``0 24px 60px rgba(0,0,0,.45)``, which
    crossfade over 320 ms OUT as a card enters or leaves the centre: the side layer at opacity
    1 - selw, the focus layer at selw (ChromeCard.selw, the frame's tween). The same layers on
    both backgrounds (S5-20; CAROUSEL.md deviation 11 retired). Each layer scales with its card
    and the card's opacity applies to it.

    A blurred box is separable (alpha * Gx(x) * Gy(y), each an erfc edge pair), so each base is
    built analytically for the scale-1 card at 1/4 resolution and stops where 8 bits round to 0
    (shadow_reach). ``paint`` resizes only the bands outside the card rect and inside the canvas
    (a source box: the same pixels as cropping a full resize), with the opacity quantised to
    1/64 and applied to the small base, and pastes them as black source-over, side first. B3a
    (K4 9.9): NEAREST band resizes while animating, BILINEAR at rest. Band sets are cached for
    rest frames only (animating frames never repeat). ``trim`` (on hide) drops the band sets.
    """
    DOWN = 4
    LEVELS = 64
    KINDS = ("side", "focus")

    def __init__(self, k, background="glass", limit=24):
        self.k = float(k)
        self.background = "none" if background == "none" else "glass"    # kept: the layers are the same
        self.params = dict(CARD_SHADOWS)
        self._bases = {}                        # kind -> (small, full, pad, oy)
        self._luts = {}
        self._cache = OrderedDict()             # rest frames: key -> [(box, mask)]
        self._limit = limit

    def shadow_params(self, kind):
        """(offset y, blur, alpha) in design px of the ``"side"`` or ``"focus"`` layer."""
        return self.params["focus" if kind in ("focus", 1, 1.0, True) else "side"]

    def _base(self, kind):
        """(small 'L' mask at full strength, (full w, full h), pad, offset y) for a layer; the
        mask's top-left is (-pad, -pad + offset y) from the scale-1 card's top-left."""
        hit = self._bases.get(kind)
        if hit is not None:
            return hit
        oy, blur, alpha = self.shadow_params(kind)
        k, d = self.k, self.DOWN
        sigma = max(0.25, blur / 2 * k)                  # a box-shadow blur radius is 2 sigma
        pad = math.ceil(shadow_reach(alpha) * sigma)
        w0, h0 = CARD_W * k, CARD_H * k
        full = (w0 + 2 * pad, h0 + 2 * pad)
        nx, ny = max(1, math.ceil(full[0] / d)), max(1, math.ceil(full[1] / d))
        gx = _edge_profile(nx, full[0] / nx, pad, w0, sigma)
        gy = _edge_profile(ny, full[1] / ny, pad, h0, sigma)
        row = Image.frombytes("L", (nx, 1), bytes(round(255 * v) for v in gx))
        column = Image.frombytes("L", (1, ny), bytes(round(255 * alpha * v) for v in gy))
        small = ImageChops.multiply(row.resize((nx, ny), Image.Resampling.NEAREST),
                                    column.resize((nx, ny), Image.Resampling.NEAREST))
        hit = (small, full, pad, oy * k)
        self._bases[kind] = hit
        return hit

    def _lut(self, level):
        lut = self._luts.get(level)
        if lut is None:
            lut = self._luts[level] = _lut(level / self.LEVELS)
        return lut

    def placement(self, rect, s, kind="side"):
        """(mask left, mask top, mask w, mask h) in the rect's px for the ``kind`` layer of a card
        at ``rect`` (l, t, ...) and scale ``s`` (tests, previews, footprints)."""
        _small, full, pad, oy = self._base(kind)
        s = max(0.01, float(s))
        size = (max(1, round(full[0] * s)), max(1, round(full[1] * s)))
        return (int(rect[0]) + round(-pad * s), int(rect[1]) + round((-pad + oy) * s)) + size

    def footprint(self, rect, s, selw=0.0):
        """The box (l, t, r, b) both layers may cover for a card (the union when crossfading)."""
        boxes = []
        for kind, weight in (("side", 1.0 - selw), ("focus", selw)):
            if weight > 1.0 / (2 * self.LEVELS):
                x, y, w, h = self.placement(rect, s, kind)
                boxes.append((x, y, x + w, y + h))
        if not boxes:
            return None
        return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))

    def paint(self, canvas, rect, s, op, selw=0.0, animating=True):
        """Draw the card's shadows at ``rect`` (canvas px) into ``canvas``: the side layer at
        op (1 - selw), then the focus layer at op selw, each black source-over outside the card's
        rect only (CSS clips an outer box-shadow under its box) and inside the canvas. Returns
        the number of pixels pasted."""
        l, t, r, b = (int(v) for v in rect)
        if r <= l or b <= t:
            return 0
        selw = max(0.0, min(1.0, float(selw)))
        pasted = 0
        for kind, weight in (("side", 1.0 - selw), ("focus", selw)):
            level = max(0, min(self.LEVELS, round(float(op) * weight * self.LEVELS)))
            if level:
                pasted += self._paint_layer(canvas, (l, t, r, b), s, kind, level, animating)
        return pasted

    def _paint_layer(self, canvas, rect, s, kind, level, animating):
        l, t, r, b = rect
        mx, my, mw, mh = self.placement((l, t), s, kind)
        cw, ch = canvas.size
        x0, y0, x1, y1 = max(mx, 0), max(my, 0), min(mx + mw, cw), min(my + mh, ch)
        if x1 <= x0 or y1 <= y0:
            return 0
        key = (kind, level, mw, mh, mx, my, l, t, r, b, cw, ch)
        bands = None if animating else self._cache.get(key)
        if bands is None:
            small = self._base(kind)[0]
            source = small if level == self.LEVELS else _point(small, self._lut(level))
            fx, fy = small.size[0] / mw, small.size[1] / mh
            resample = Image.Resampling.NEAREST if animating else Image.Resampling.BILINEAR   # B3a
            bands = []
            for bl, bt, br, bb in ((x0, y0, x1, min(t, y1)), (x0, max(b, y0), x1, y1),
                                   (x0, max(t, y0), min(l, x1), min(b, y1)), (max(r, x0), max(t, y0), x1, min(b, y1))):
                if br <= bl or bb <= bt:
                    continue
                box = ((bl - mx) * fx, (bt - my) * fy, (br - mx) * fx, (bb - my) * fy)
                bands.append(((bl, bt, br, bb), _core_resize(source, (br - bl, bb - bt), resample, box)))
            if not animating:
                self._cache[key] = bands
                while len(self._cache) > self._limit:
                    self._cache.popitem(last=False)
        else:
            self._cache.move_to_end(key)
        pasted = 0
        for box, mask in bands:
            _paste_ink(canvas.image, SHADOW_INK, box, mask)
            pasted += mask.size[0] * mask.size[1]
        return pasted

    def trim(self):
        """Drop the cached band sets (the two bases stay, about 170 KB at k = 2), e.g. on hide."""
        self._cache.clear()


# ======================================================================== fonts
FontSpec = namedtuple("FontSpec", "path index wght colour name")

_COVERAGE = {}
_COVERAGE_LOCK = threading.Lock()


def _read_at(f, offset, size):
    f.seek(offset)
    data = f.read(size)
    if len(data) != size:
        raise ValueError("truncated font")
    return data


def cmap_ranges(path, index=0):
    """Sorted, merged (start, end) code point ranges with a non-zero glyph, from the font's
    best Unicode cmap subtable (format 12, else format 4). TTC collections use ``index``."""
    with open(path, "rb") as f:
        head = _read_at(f, 0, 12)
        base = 0
        if head[:4] == b"ttcf":
            count = struct.unpack(">I", head[8:12])[0]
            index = max(0, min(int(index), count - 1))
            base = struct.unpack(">I", _read_at(f, 12 + 4 * index, 4))[0]
        num_tables = struct.unpack(">H", _read_at(f, base + 4, 2))[0]
        records = _read_at(f, base + 12, 16 * num_tables)
        cmap_offset = cmap_length = None
        for i in range(num_tables):
            tag, _check, offset, length = struct.unpack(">4sIII", records[16 * i:16 * i + 16])
            if tag == b"cmap":
                cmap_offset, cmap_length = offset, length
        if cmap_offset is None:
            return []
        data = _read_at(f, cmap_offset, cmap_length)
    count = struct.unpack(">H", data[2:4])[0]
    subtables = {}
    for i in range(count):
        platform, encoding, offset = struct.unpack(">HHI", data[4 + 8 * i:12 + 8 * i])
        fmt = struct.unpack(">H", data[offset:offset + 2])[0]
        subtables.setdefault((platform, encoding, fmt), offset)
    for key in ((3, 10, 12), (0, 6, 12), (0, 4, 12), (3, 1, 4), (0, 3, 4), (0, 1, 4), (3, 0, 4)):
        if key in subtables:
            offset = subtables[key]
            return _merge(_cmap12(data, offset) if key[2] == 12 else _cmap4(data, offset))
    return []


def _cmap12(data, offset):
    groups = struct.unpack(">I", data[offset + 12:offset + 16])[0]
    out = []
    for i in range(groups):
        start, end, glyph = struct.unpack(">III", data[offset + 16 + 12 * i:offset + 28 + 12 * i])
        if glyph == 0:
            start += 1
        if end >= start:
            out.append((start, end))
    return out


def _cmap4(data, offset):
    seg_count = struct.unpack(">H", data[offset + 6:offset + 8])[0] // 2
    ends = struct.unpack(f">{seg_count}H", data[offset + 14:offset + 14 + 2 * seg_count])
    p = offset + 16 + 2 * seg_count
    starts = struct.unpack(f">{seg_count}H", data[p:p + 2 * seg_count])
    p += 2 * seg_count
    deltas = struct.unpack(f">{seg_count}h", data[p:p + 2 * seg_count])
    p += 2 * seg_count
    range_base = p
    offsets = struct.unpack(f">{seg_count}H", data[p:p + 2 * seg_count])
    out = []
    for i in range(seg_count):
        start, end, delta, ro = starts[i], ends[i], deltas[i], offsets[i]
        if start == 0xFFFF:
            continue
        if ro == 0:
            zero = (-delta) & 0xFFFF
            if start <= zero <= end:
                if zero > start:
                    out.append((start, zero - 1))
                if zero < end:
                    out.append((zero + 1, end))
            else:
                out.append((start, end))
            continue
        run_start = None
        for c in range(start, end + 1):
            at = range_base + 2 * i + ro + 2 * (c - start)
            glyph = struct.unpack(">H", data[at:at + 2])[0] if at + 2 <= len(data) else 0
            glyph = (glyph + delta) & 0xFFFF if glyph else 0
            if glyph and run_start is None:
                run_start = c
            elif not glyph and run_start is not None:
                out.append((run_start, c - 1))
                run_start = None
        if run_start is not None:
            out.append((run_start, end))
    return out


def _merge(ranges):
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


class _Coverage:
    __slots__ = ("starts", "ends")

    def __init__(self, ranges):
        self.starts = [r[0] for r in ranges]
        self.ends = [r[1] for r in ranges]

    def __contains__(self, cp):
        i = bisect.bisect_right(self.starts, cp) - 1
        return i >= 0 and cp <= self.ends[i]


def coverage(path, index=0):
    """The (cached, shared, immutable) cmap coverage of a font file."""
    key = (str(path), int(index))
    with _COVERAGE_LOCK:
        hit = _COVERAGE.get(key)
    if hit is None:
        try:
            hit = _Coverage(cmap_ranges(path, index))
        except Exception:
            hit = _Coverage([])
        with _COVERAGE_LOCK:
            _COVERAGE[key] = hit
    return hit


class TextEngine:
    """Per-thread text renderer (faces are not shared across threads)."""

    def __init__(self, archivo=None, fonts_dir=None):
        self.archivo = str(archivo or ARCHIVO_PATH)
        self.fonts_dir = Path(fonts_dir or SYSTEM_FONT_DIR)
        self._faces = {}
        self._chains = {}
        self._pick = {}
        self._advances = {}

    # ------------------------------------------------------------- fonts
    def chain(self, wght):
        wght = 600 if 500 <= wght < 650 else 700 if wght >= 650 else 400
        chain = self._chains.get(wght)
        if chain is None:
            chain = [FontSpec(self.archivo, 0, wght, False, "Archivo")] if os.path.exists(self.archivo) else []
            for name in FALLBACK_FILES[wght]:
                path = self.fonts_dir / name
                if path.exists():
                    chain.append(FontSpec(str(path), 0, None, name in COLOUR_FONTS, name))
            self._chains[wght] = chain
        return chain

    def font_for(self, ch, wght, emoji=False):
        """The first font of the chain whose cmap has ``ch``. Segoe UI Symbol has monochrome
        glyphs for many emoji, so an emoji (``emoji``, see emoji_presentation: VS16, U+1F000
        and above, or a BMP Emoji_Presentation code point, unless VS15 follows) tries Segoe UI
        Emoji first. That is the only change to section 8's order."""
        key = (ch, wght, bool(emoji))
        spec = self._pick.get(key)
        if spec is None:
            chain = self.chain(wght)
            if emoji:
                chain = [s for s in chain if s.colour] + [s for s in chain if not s.colour]
            cp = ord(ch)
            spec = next((s for s in chain if cp in coverage(s.path, s.index)), None)
            if spec is None:
                plain = [s for s in self.chain(wght) if not s.colour]
                spec = plain[1] if len(plain) > 1 else (plain[0] if plain else None)
            self._pick[key] = spec
        return spec

    def glyphs(self, text, wght):
        """(ch, FontSpec) for every drawn character of ``text``."""
        out = []
        for i, ch in enumerate(text):
            if not self._drawn(ch):
                continue
            out.append((ch, self.font_for(ch, wght, emoji_presentation(text, i))))
        return out

    def face(self, spec, px):
        key = (spec, round(float(px), 3))
        face = self._faces.get(key)
        if face is None:
            if spec is None:
                face = ImageFont.load_default(size=max(1.0, float(px)))
            else:
                face = ImageFont.truetype(spec.path, max(1.0, float(px)), index=spec.index,
                                          layout_engine=ImageFont.Layout.BASIC)
                if spec.wght is not None:
                    try:
                        face.set_variation_by_axes([spec.wght, 100])
                    except Exception:
                        pass
            self._faces[key] = face
        return face

    def advance(self, ch, spec):
        """Fractional advance in em (from a 1000 px face: effectively unhinted)."""
        key = (ch, spec)
        value = self._advances.get(key)
        if value is None:
            try:
                value = self.face(spec, 1000).getlength(ch) / 1000.0
            except Exception:
                value = 0.5
            self._advances[key] = value
        return value

    # ------------------------------------------------------------- layout
    @staticmethod
    def _drawn(ch):
        """False for invisible format characters (ZWJ, bidi marks: 'Cf') and variation
        selectors (VS1-16, VS17-256), which would otherwise draw as tofu."""
        cp = ord(ch)
        return not (0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF) and unicodedata.category(ch) != "Cf"

    def width(self, text, px, wght, track=0.0):
        return sum(self.advance(ch, spec) * px + track * px for ch, spec in self.glyphs(text, wght))

    def fit(self, text, px, wght, track, limit):
        """One line: ``text`` if it fits in ``limit`` px, else the longest prefix + an ellipsis
        (binary search on the same width function), or '' when not even the ellipsis fits."""
        text = " ".join(str(text or "").split())
        if self.width(text, px, wght, track) <= limit:
            return text
        ellipsis = "\u2026"
        if self.width(ellipsis, px, wght, track) > limit:
            return ""
        low, high = 0, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if self.width(text[:middle].rstrip() + ellipsis, px, wght, track) <= limit:
                low = middle
            else:
                high = middle - 1
        return text[:low].rstrip() + ellipsis

    def draw(self, text, x, baseline, px, wght, track, mask, colour=None, fill=255):
        """Per-glyph drawing at rounded pens (anchor 'ls'): monochrome glyphs into the 'L'
        ``mask`` at ``fill`` (coverage x fill / 255), colour glyphs (emoji) into the premultiplied
        RGBA ``colour`` layer (into the mask, monochrome, when there is none). Returns the pen's
        end x."""
        pen = float(x)
        draw_mask = ImageDraw.Draw(mask)
        draw_colour = None
        base = round(baseline)
        for ch, spec in self.glyphs(text, wght):
            face = self.face(spec, px)
            if spec is not None and spec.colour and colour is not None:
                if draw_colour is None:
                    draw_colour = ImageDraw.Draw(colour)
                draw_colour.text((round(pen), base), ch, font=face, fill=(255, 255, 255, 255),
                                 anchor="ls", embedded_color=True)
            else:
                draw_mask.text((round(pen), base), ch, font=face, fill=fill, anchor="ls")
            pen += self.advance(ch, spec) * px + track * px
        return pen


def baseline_in(top, line_height, px):
    """CSS line-box baseline for Archivo: top + (lh - (asc + desc) px) / 2 + asc px."""
    return top + (line_height - LINE_NORMAL * px) / 2 + ASCENT * px


# ================================================================== letter tiles
BRAND_TILES = {"bambu studio": (0x00, 0xAE, 0x42), "file explorer": (0xE8, 0xB6, 0x4A), "steam": (0x1B, 0x28, 0x38)}
TILE_PALETTE = ((0x3C, 0x6E, 0xD8), (0x8E, 0x44, 0xAD), (0xC0, 0x39, 0x2B), (0x16, 0xA0, 0x85),
                (0xD3, 0x54, 0x00), (0x2C, 0x3E, 0x50), (0x7D, 0x5B, 0xA6), (0x1E, 0x88, 0x7E),
                (0xB0, 0x3A, 0x6B), (0x5D, 0x6D, 0x7E), (0x2E, 0x7D, 0x32), (0x6D, 0x4C, 0x41))
MIN_TILE_CONTRAST = 3.0


def _luminance(rgb):
    out = []
    for v in rgb:
        v = v / 255
        out.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def white_contrast(rgb):
    return 1.05 / (_luminance(rgb) + 0.05)


def tile_colour(name):
    key = " ".join(str(name or "").split()).lower()
    rgb = BRAND_TILES.get(key) or TILE_PALETTE[zlib.crc32(key.encode("utf-8")) % len(TILE_PALETTE)]
    while white_contrast(rgb) < MIN_TILE_CONTRAST:
        rgb = tuple(int(c * 0.92) for c in rgb)
    return tuple(rgb)


def stub_letter_tile(name, px, engine=None):
    """The section 7 letter tile, used when control_center.window_facts is unavailable: the
    first letter of the display name, upper-cased, white Archivo 700 at 17/32 of the tile,
    centred on its advance, on tile_colour(name); square corners."""
    px = max(1, int(round(px)))
    tile = Image.new("RGBA", (px, px), tile_colour(name) + (255,))
    text = " ".join(str(name or "").split())
    letter = next((c for c in text if c.isalnum()), text[:1] if text else "")
    letter = letter.upper()[:1] if letter else ""
    if not letter:
        return tile
    engine = engine or TextEngine()
    fs = px * 17 / 32
    width = engine.width(letter, fs, 700)
    mask = Image.new("L", (px, px), 0)
    colour = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    engine.draw(letter, (px - width) / 2, baseline_in(0, px, fs), fs, 700, 0.0, mask, colour)
    tile.paste((255, 255, 255, 255), (0, 0, px, px), mask)
    return tile


def letter_tile(name, px, engine=None):
    """window_facts.letter_tile (labels track) when importable, else the stub."""
    try:
        from .window_facts import letter_tile as facts_tile
    except Exception:
        facts_tile = None
    if facts_tile is not None:
        try:
            image = facts_tile(name, int(round(px)))
            if image is not None and image.size == (int(round(px)),) * 2:
                return image.convert("RGBA")
        except Exception:
            pass
    return stub_letter_tile(name, px, engine)


# ================================================================ icon sprites
def _icon_square(icon, px, resample=Image.Resampling.LANCZOS):
    """``icon`` fitted (contain) into a px x px transparent square."""
    px = max(1, int(round(px)))
    icon = icon.convert("RGBA")
    if icon.size == (px, px):
        return icon
    w, h = icon.size
    scale = min(px / max(1, w), px / max(1, h))
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    fitted = icon.resize(size, resample)
    if size == (px, px):
        return fitted
    square = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    square.paste(fitted, ((px - size[0]) // 2, (px - size[1]) // 2))
    return square


def icon_sprite(icon, name, px, engine=None):
    """The app icon (or the letter tile) at px, as a Sprite."""
    image = _icon_square(icon, px) if icon is not None else letter_tile(name, px, engine)
    return Sprite.from_image(image)


def badge_sprite(icon, name, k, engine=None):
    """(Sprite, pad): the 30 design px badge with its box-shadow 0 2 8 rgba(0,0,0,.45) (outside
    the box only, as CSS clips outer shadows), at scale 1 (K4 9.3). The badge's box starts
    ``pad`` px into the sprite. Small (under 64 K px), so alpha_composite is allowed here."""
    size = max(1, round(BADGE_SIZE * k))
    oy, blur, alpha = BADGE_SHADOW
    sigma = blur / 2 * k
    pad = math.ceil(3 * sigma) + math.ceil(oy * k)
    full = size + 2 * pad
    shadow = _blurred_box((full, full), (pad, pad + oy * k, pad + size - 1, pad + oy * k + size - 1), sigma, alpha,
                          hole=(pad, pad, pad + size, pad + size))
    image = Image.new("RGBA", (full, full), (0, 0, 0, 0))
    image.putalpha(shadow)
    face = _icon_square(icon, size) if icon is not None else letter_tile(name, size, engine)
    image.alpha_composite(face, (pad, pad))
    return Sprite.from_image(image), pad


def placeholder_sprite(icon, name, k, engine=None):
    """The placeholder card's centred icon (96 design px), at scale 1."""
    return icon_sprite(icon, name, PLACEHOLDER_ICON * k, engine)


def _half_glyph_mask(px, side, stroke_units):
    """An 'L' mask of BS's snap glyph at ``px``: the 24-unit viewBox rect (3, 5, 18 x 14) stroked
    ``stroke_units`` wide, with the ``side`` half (BS ``HALF``) filled. Drawn 4x and reduced."""
    ss = 4
    size = max(1, int(round(px)))
    big = Image.new("L", (size * ss, size * ss), 0)
    draw = ImageDraw.Draw(big)
    unit = size * ss / 24.0
    half_w = stroke_units * unit / 2
    x0, y0, x1, y1 = 3 * unit, 5 * unit, 21 * unit, 19 * unit
    for band in ((x0 - half_w, y0 - half_w, x1 + half_w, y0 + half_w), (x0 - half_w, y1 - half_w, x1 + half_w, y1 + half_w),
                 (x0 - half_w, y0 - half_w, x0 + half_w, y1 + half_w), (x1 - half_w, y0 - half_w, x1 + half_w, y1 + half_w)):
        draw.rectangle(tuple(round(v) for v in band), fill=255)
    if side in HALF_BOXES:
        hx0, hy0, hx1, hy1 = HALF_BOXES[side]
        draw.rectangle((round(hx0 * unit), round(hy0 * unit), round(hx1 * unit) - 1, round(hy1 * unit) - 1), fill=255)
    return big.reduce(ss)


def chip_sprite(side, k, engine=None):
    """The snap chip on a card that holds a side (K4 9.3; BS wCards): padding 4 x 8 units,
    rgba(18,18,20,.72), a 16 px rect + HALF glyph (stroke 2), gap 6, then ``overlay.picker.badge``
    (Left / Right) at 12 px 600, white. A Sprite at scale 1 (straight colour, masked pastes)."""
    engine = engine or TextEngine()
    k = float(k)
    text = SNAP_BADGE.get(side, "")
    px = CHIP_PX * k
    text_w = engine.width(text, px, 600)
    w = math.ceil(CHIP_PAD_X * k * 2 + CHIP_ICON * k + CHIP_GAP * k + text_w)
    h = math.ceil(CHIP_PAD_Y * k * 2 + CHIP_ICON * k)
    mask = Image.new("L", (w, h), round(255 * CHIP_A))
    colour = Image.new("RGBX", (w, h), (CHIP_RGB[2], CHIP_RGB[1], CHIP_RGB[0], 255))
    white = (255, 255, 255, 255)
    icon = _half_glyph_mask(CHIP_ICON * k, side, 2.0)
    ix, iy = round(CHIP_PAD_X * k), round((h - icon.size[1]) / 2)
    colour.paste(white, (ix, iy, ix + icon.size[0], iy + icon.size[1]), icon)
    mask.paste(255, (ix, iy, ix + icon.size[0], iy + icon.size[1]), icon)
    glyphs = Image.new("L", (w, h), 0)
    tx = CHIP_PAD_X * k + CHIP_ICON * k + CHIP_GAP * k
    engine.draw(text, tx, baseline_in(0, h, px), px, 600, 0.0, glyphs)
    colour.paste(white, (0, 0, w, h), glyphs)
    mask.paste(255, (0, 0, w, h), glyphs)
    return Sprite(mask, colour_image=colour)


def slot_glyph_sprite(side, k):
    """The empty slot's 34 px rect + HALF glyph (stroke 1.8), white (its 0.80 is applied at
    paste time; K4 9.4)."""
    return Sprite.solid(_half_glyph_mask(SLOT_GLYPH * k, side, 1.8), (255, 255, 255))


def slot_border_sprite(kind, size, width):
    """The slot's 1-unit border (``width`` px) around a content box of ``size`` (w, h) px, drawn
    outside it: solid, or dashed (DASH on, DASH_GAP off, in units of ``width``) for the empty
    look. A white Sprite whose mask is the ring; colour and alpha are applied at paste time."""
    w, h = (max(1, int(v)) for v in size)
    width = max(1, int(width))
    full = (w + 2 * width, h + 2 * width)
    mask = Image.new("L", full, 0)
    draw = ImageDraw.Draw(mask)
    fw, fh = full
    if not SLOT_BORDERS.get(kind, SLOT_BORDERS["filled"])[2]:
        for band in ((0, 0, fw - 1, width - 1), (0, fh - width, fw - 1, fh - 1),
                     (0, width, width - 1, fh - width - 1), (fw - width, width, fw - 1, fh - width - 1)):
            draw.rectangle(band, fill=255)
    else:
        on, off = DASH * width, DASH_GAP * width
        step = on + off
        for x in range(0, fw, step):
            draw.rectangle((x, 0, min(fw, x + on) - 1, width - 1), fill=255)
            draw.rectangle((x, fh - width, min(fw, x + on) - 1, fh - 1), fill=255)
        for y in range(0, fh, step):
            draw.rectangle((0, y, width - 1, min(fh, y + on) - 1), fill=255)
            draw.rectangle((fw - width, y, fw - 1, min(fh, y + on) - 1), fill=255)
    return Sprite.solid(mask, (255, 255, 255))


def caption_sprite(key, text, ink, k, engine=None):
    """A slot caption (K4 9.4; BS:75-78): the key box 16 x 16 (1 px border at .6, the digit
    10 px 700), gap 6, then ``text`` at 12 px in ``ink`` = (rgb, alpha) (CAPTION_INKS). A Sprite
    at scale 1 with straight colour."""
    engine = engine or TextEngine()
    k = float(k)
    rgb, alpha = ink
    px, key_px = CAPTION_PX * k, CAPTION_KEY_PX * k
    box = max(1, round(CAPTION_KEY * k))
    border = max(1, round(k))
    text_w = engine.width(text, px, 400) if text else 0.0
    w = math.ceil(box + (CAPTION_KEY_GAP * k + text_w if text else 0)) + 1
    h = max(box, math.ceil(LINE_NORMAL * px))
    mask = Image.new("L", (w, h), 0)
    colour = Image.new("RGBX", (w, h), (255, 255, 255, 255))
    top = (h - box) // 2
    ring = Image.new("L", (box, box), round(255 * 0.6))
    ring.paste(0, (border, border, box - border, box - border))
    mask.paste(ring, (0, top))
    digit = Image.new("L", (w, h), 0)
    dw = engine.width(key, key_px, 700)
    engine.draw(key, (box - dw) / 2, baseline_in(top, box, key_px), key_px, 700, 0.0, digit)
    mask.paste(255, (0, 0, w, h), digit)
    if text:
        words = Image.new("L", (w, h), 0)
        engine.draw(text, box + CAPTION_KEY_GAP * k, baseline_in(0, h, px), px, 400, 0.0, words)
        colour.paste((rgb[2], rgb[1], rgb[0], 255), (0, 0, w, h), words)
        mask.paste(round(255 * alpha), (0, 0, w, h), words)
    return Sprite(mask, colour_image=colour)


def slot_badge_sprite(icon, name, k, engine=None):
    """The filled slot's 22 x 22 app badge (BS:71; no shadow), at scale 1."""
    return icon_sprite(icon, name, SLOT_BADGE * k, engine)


# ======================================================================== label
LabelSprite = namedtuple("LabelSprite", "sprite x y shadow", defaults=(None,))


def fallback_label(item):
    """The label before set_labels delivered one: the exe stem and the raw title."""
    app = str((item or {}).get("app") or "Application")
    title = str((item or {}).get("title") or app)
    desc = "Minimized" if (item or {}).get("minimized") else ""
    return SimpleLabel(app, title, desc)


def _text_shadow(alpha_mask, k):
    """No background's text shadow 0 1px 2px rgba(0,0,0,.6) (App B S01:536; S5-20) as an 'L' mask
    of the glyph coverage (a text-shadow ignores the text colour's own alpha)."""
    w, h = alpha_mask.size
    out = Image.new("L", (w, h), 0)
    for oy, blur, alpha in reversed(LABEL_TEXT_SHADOWS):
        sigma = blur / 2 * k
        shifted = Image.new("L", (w, h), 0)
        shifted.paste(alpha_mask, (0, round(oy * k)))
        blurred = shifted.filter(ImageFilter.GaussianBlur(sigma))
        out = _l_over(out, blurred.point(_lut(alpha)))
    return out


def _l_over(bottom, top):
    """Alpha of ``top`` over ``bottom`` (both 'L'): t + b (1 - t)."""
    return ImageChops.add(top, ImageChops.multiply(bottom, ImageChops.invert(top)))


def render_label(label, icon, k, background="glass", engine=None, suffix=""):
    """The centre card's label (K4 9.3; BS:102-109) as a LabelSprite whose (x, y) is the sprite's
    top-left in stage px (relative to the stage's top-left, at the tray-shown position; the
    engine adds the cards group's shift): a 900-unit column centred at left 190, top 512, gap 6.
    Row 1: 18 px icon + 8 px gap + app name 15 px at 92 % white; row 2: title 26/32, weight 600,
    one line with an ellipsis; row 3: description 15 px at 86 % white, plus ``suffix``
    (``overlay.picker.desc_snapped``). No background adds the text shadow 0 1px 2px /.6 as a
    separate solid sprite (``shadow``), drawn under the text.

    Built with masked pastes only (K4 4.7.3: no alpha_composite over 64 K px; it runs on the
    label worker, B1): the text coverage goes into one 'L' mask at each row's alpha, colour
    glyphs and the icon go into a straight-colour RGBX image through their own alpha."""
    engine = engine or TextEngine()
    k = float(k)
    width = round(LABEL_WIDTH * k)
    shadowed = background == "none"
    pad = math.ceil(4 * k) + 2 if shadowed else 2
    height = round(LABEL_HEIGHT * k)
    size = (width + 2 * pad, height + 2 * pad)
    mask = Image.new("L", size, 0)
    coverage = Image.new("L", size, 0) if shadowed else None
    colour = None                                           # RGBX, only for emoji and the icon
    texts = (str(getattr(label, "app", "") or ""), str(getattr(label, "title", "") or ""),
             (str(getattr(label, "desc", "") or "") + str(suffix or "")).strip())
    icon_box = None
    for row, (top, line_h, fs, wght, alpha, track) in enumerate(LABEL_ROWS):
        px = fs * k
        text = texts[row]
        limit = width
        icon_w = 0.0
        if row == 0:
            icon_w = round(LABEL_ICON * k)
            limit = max(0.0, width - icon_w - LABEL_ICON_GAP * k)
        text = engine.fit(text, px, wght, track, limit) if text else ""
        text_w = engine.width(text, px, wght, track) if text else 0.0
        group = text_w + ((icon_w + LABEL_ICON_GAP * k) if row == 0 else 0.0)
        x0 = pad + (width - group) / 2
        row_top = pad + top * k
        if row == 0:
            icon_box = (round(x0), round(row_top + (line_h * k - icon_w) / 2), int(icon_w))
            x0 += icon_w + LABEL_ICON_GAP * k
        if not text:
            continue
        baseline = baseline_in(row_top, line_h * k, px)
        glyphs = engine.glyphs(text, wght)
        emoji = any(spec is not None and spec.colour for _, spec in glyphs)
        layer = Image.new("RGBA", size, (0, 0, 0, 0)) if emoji else None
        if layer is None and coverage is None:
            engine.draw(text, x0, baseline, px, wght, track, mask, None, fill=round(255 * alpha))
            continue
        row_mask = Image.new("L", size, 0)
        engine.draw(text, x0, baseline, px, wght, track, row_mask, layer)
        if True:
            if coverage is not None:
                coverage.paste(255, (0, 0) + size, row_mask)
            mask.paste(round(255 * alpha), (0, 0) + size, row_mask)
        if layer is not None:
            # colour glyphs were drawn premultiplied onto transparent: un-premultiply, then paste
            # their colour through their alpha (a masked paste) and add their alpha at the row's.
            straight = Image.frombuffer("RGBa", size, layer.tobytes(), "raw", "RGBa", 0, 1).convert("RGBA")
            r, g, b, a = straight.split()
            if colour is None:
                colour = Image.new("RGBX", size, (255, 255, 255, 255))
            colour.paste(Image.merge("RGBX", (b, g, r, Image.new("L", size, 255))), (0, 0), a)
            if coverage is not None:
                coverage.paste(255, (0, 0) + size, a)
            mask.paste(round(255 * alpha), (0, 0) + size, a)
    if icon_box is not None:
        x, y, px = icon_box
        face = _icon_square(icon, px) if icon is not None else letter_tile(texts[0] or "?", px, engine)
        if face.size != (px, px):
            face = face.resize((px, px), Image.Resampling.LANCZOS)
        r, g, b, a = face.convert("RGBA").split()
        if colour is None:
            colour = Image.new("RGBX", size, (255, 255, 255, 255))
        colour.paste(Image.merge("RGBX", (b, g, r, Image.new("L", (px, px), 255))), (x, y), a)
        mask.paste(255, (x, y, x + px, y + px), a)
    shadow = _text_shadow(coverage, k) if coverage is not None else None
    box = mask.getbbox()
    if shadow is not None:
        sbox = shadow.getbbox()
        if sbox is not None:
            box = sbox if box is None else (min(box[0], sbox[0]), min(box[1], sbox[1]),
                                            max(box[2], sbox[2]), max(box[3], sbox[3]))
    lx, ly = LABEL_LEFT * k - pad, LABEL_TOP * k - pad
    if box is None:
        return LabelSprite(None, round(lx), round(ly), None)
    sprite = Sprite(mask.crop(box), colour_image=colour.crop(box) if colour is not None else None)
    shade = Sprite.solid(shadow.crop(box), (0, 0, 0)) if shadow is not None and shadow.getbbox() else None
    return LabelSprite(sprite, round(lx) + box[0], round(ly) + box[1], shade)


# ========================================================================= dots
def dots_window(count, index):
    """(first, shown, opacities) of the dots row (K4 7.4; S5-9): all dots at 0.40 when the list
    fits DOTS_CAP; otherwise a DOTS_CAP window starting at clamp(i - 41, 0, n - 82) whose three
    end dots on a side with more items beyond are 0.30 / 0.20 / 0.10."""
    count, index = max(0, int(count)), int(index)
    if count <= DOTS_CAP:
        return 0, count, tuple([DOT_OPACITY] * count)
    first = max(0, min(index - DOTS_CAP // 2, count - DOTS_CAP))
    values = [DOT_OPACITY] * DOTS_CAP
    if first > 0:
        values[:3] = DOTS_END_FADES
    if first + DOTS_CAP < count:
        values[-3:] = DOTS_END_FADES[::-1]
    return first, DOTS_CAP, tuple(values)


def dots_width(count):
    """Row width in design units for ``count`` dots (pitch 14, 6 px squares)."""
    return max(0, int(count) * DOT_PITCH - (DOT_PITCH - DOT_SIZE))


def render_dots(opacities, k):
    """(Sprite, x, y) of the fixed dots row (K4 7.4 / 9.3): 6 x 6 white squares at each
    opacity, pitch 14, centred at stage x 640, top 622 (stage px of the row's top-left, at the
    tray-shown position). No shadow (BS:190-195)."""
    count = len(opacities)
    if not count:
        return None
    k = float(k)
    left = CENTER_X - dots_width(count) / 2
    x0 = math.floor(left * k)
    w = math.ceil((left + dots_width(count)) * k) - x0
    h = max(1, round(DOT_SIZE * k))
    mask = Image.new("L", (max(1, w), h), 0)
    for j, opacity in enumerate(opacities):
        dx = round((left + j * DOT_PITCH) * k) - x0
        mask.paste(round(255 * max(0.0, min(1.0, opacity))), (dx, 0, dx + h, h))
    return Sprite.solid(mask, (255, 255, 255)), x0, round(DOTS_TOP * k)


def marker_x(count, slot):
    """The marker's left edge in stage units for dot ``slot`` of a ``count``-dot row."""
    return CENTER_X - dots_width(count) / 2 + slot * DOT_PITCH


def marker_sprite(k):
    """The solid 6 x 6 white marker."""
    h = max(1, round(DOT_SIZE * float(k)))
    return Sprite.solid(Image.new("L", (h, h), 255), (255, 255, 255))


# ======================================================================== toast
def fit_toast_text(text, k, engine=None, limit=None):
    """The toast's one line fitted to ``limit`` px (default TOAST_TEXT_MAX * k, the label's
    900-unit column, so the pill always stays inside the stage and the monitor): a
    '{App} · {Title}' text keeps its app prefix and ellipsizes the title; without the
    separator, or when the prefix would leave the title less than a quarter of the line, the
    whole text is ellipsized. Idempotent (a fitted text fits). S5-22."""
    engine = engine or TextEngine()
    text = " ".join(str(text or "").split())
    px = TOAST_PX * k
    limit = TOAST_TEXT_MAX * k if limit is None else float(limit)
    if not text or engine.width(text, px, 400) <= limit:
        return text
    app, sep, title = text.partition(SEP)
    if sep and title:
        prefix = app + SEP
        room = limit - engine.width(prefix, px, 400)
        if room >= limit / 4:
            fitted = engine.fit(title, px, 400, 0.0, room)
            if fitted:
                return prefix + fitted
    return engine.fit(text, px, 400, 0.0, limit)


def toast_size(text, k, engine=None):
    """(w, h) physical px of the toast pill for the fitted text (fit_toast_text): padding
    12/18, 1 px border, 15 px text."""
    engine = engine or TextEngine()
    px = TOAST_PX * k
    text_w = engine.width(fit_toast_text(text, k, engine), px, 400)
    w = math.ceil(text_w + 2 * TOAST_PAD_X * k + 2 * max(1, round(k)))
    h = math.ceil(LINE_NORMAL * px + 2 * TOAST_PAD_Y * k + 2 * max(1, round(k)))
    return max(1, w), max(1, h)


def render_toast_canvas(text, k, backdrop=None, engine=None):
    """The toast pill as a premultiplied Canvas (the toast window's DIB layout): glass (blur.toast:
    blur 24 + tint rgba(24,24,26,.62), from ``backdrop``, a capture of the screen behind it,
    stretched to the pill when its size differs) or, without one, the tint at 88 %; a 1 px border
    rgba(255,255,255,.2); white 15 px text fitted to one line (fit_toast_text); colour glyphs.
    Square corners.

    K4 4.7.3 (WP7b-R6): a fitted pill reaches about 160 K px at k = 2, so it is built only with
    fills and masked pastes of straight colour into the premultiplied canvas (exact
    premultiplied "over"), never ``Image.alpha_composite``. The carousel renders it on its label
    worker (NanoD-label), off the frame path."""
    engine = engine or TextEngine()
    text = fit_toast_text(text, k, engine)
    w, h = toast_size(text, k, engine)
    canvas = Canvas.new((w, h))
    if backdrop is not None:
        glass = toast_backdrop(backdrop.resize((w, h)) if backdrop.size != (w, h) else backdrop, k)
        r, g, b = glass.convert("RGB").split()
        # the glass is opaque: premultiplied == straight, in the B, G, R, A band order
        _core_paste(canvas.image, Image.merge("RGBX", (b, g, r, Image.new("L", (w, h), 255))), (0, 0, w, h))
    else:
        canvas.fill((0, 0, w, h), TOAST_TINT, TOAST_FALLBACK_A)
    border = max(1, round(k))
    canvas.rect_outline((0, 0, w, h), border, (255, 255, 255), TOAST_BORDER_A)
    px = TOAST_PX * k
    mask = Image.new("L", (w, h), 0)
    colour = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    x0 = border + TOAST_PAD_X * k
    engine.draw(text, x0, baseline_in(border + TOAST_PAD_Y * k, LINE_NORMAL * px, px), px, 400, 0.0, mask, colour)
    canvas.over_mask((255, 255, 255), mask, (0, 0))
    if colour.getbbox():
        colour = Image.frombuffer("RGBa", (w, h), colour.tobytes(), "raw", "RGBa", 0, 1).convert("RGBA")
        canvas.over_sprite(Sprite.from_image(colour), (0, 0))
    return canvas


def render_toast(text, k, backdrop=None, engine=None):
    """The toast pill as straight RGBA (tests and previews): ``render_toast_canvas`` unpremultiplied."""
    return render_toast_canvas(text, k, backdrop, engine).straight()


def toast_rect(layout, size):
    """The toast's resting rect (x, y, w, h), physical screen px: centred on the stage, top 588."""
    w, h = size
    cx, top = layout.screen_point(CENTER_X, TOAST_TOP)
    return (round(cx - w / 2), round(top), int(w), int(h))


# ==================================================================== dim layer
def build_dim(canvas, layout, background="none"):
    """Fill a monitor-sized premultiplied canvas with No background's flat black at 55 %
    (blur.picker_none). Frosted shows no dim (blur.picker_frost has none, K4 9.2)."""
    a_dim = DIM_ALPHA["none" if background == "none" else "glass"]
    canvas.image.paste((0, 0, 0, round(255 * a_dim)), (0, 0) + canvas.size)
    return canvas


# ================================================================ chrome compose
@dataclass
class ChromeCard:
    """One card's chrome, host-local ``rect`` (l, t, r, b). ``op`` is the card's effective
    opacity (the root, the cards group and the closed factor included), ``shade`` its #111
    overlay, ``selw`` the 0..1 weight of the selected look (the frame and the focus shadow).
    ``badge`` = (Sprite, pad) at scale 1; ``placeholder`` = the centred icon Sprite at scale 1 when
    no thumbnail shows; ``chip`` = the snap chip Sprite at scale 1 when the window holds a side.
    ``cover`` is how much the card hides the farther cards under it inside the group (its own
    opacity, closed factor included, without the group fades; CSS applies the group's opacity to
    the composited row); None means ``op``."""
    rect: tuple
    s: float
    op: float
    shade: float = 0.0
    selw: float = 0.0
    badge: tuple = None
    placeholder: Sprite = None
    index: int = -1
    cover: float = None
    chip: Sprite = None


@dataclass
class TraySlot:
    """One tray slot's chrome (K4 9.4). ``rect`` is the host-local content box (l, t, r, b) under
    the tray's transform (scale ``scale``); ``opacity`` the tray's own (its reveal fade x the
    root); ``fill`` the filled look's weight (the slot fill fade: the 4 % background shows only
    where the thumbnail does not); ``borders`` kind -> weight ("empty", "filled", "failure"; the
    260 ms EASE crossfades); ``glyph`` the empty glyph's opacity; ``badge`` the 22 px badge Sprite
    and ``badge_alpha``; ``caption`` its Sprite at scale 1 (drawn under the slot, gap 6);
    ``glyph_sprite`` the side's empty glyph at scale 1."""
    side: str
    rect: tuple
    scale: float = 1.0
    opacity: float = 1.0
    fill: float = 0.0
    borders: dict = field(default_factory=dict)
    glyph: float = 1.0
    badge: Sprite = None
    badge_alpha: float = 0.0
    caption: Sprite = None
    glyph_sprite: Sprite = None


@dataclass
class ChromeScene:
    """One chrome frame: ``origin`` is the band's top-left in host-local px (canvas px = host-local
    - origin); ``cards`` far -> near; ``tray`` the TraySlots (drawn first: the cards group lies
    over the tray, BS markup order); ``clear`` the canvas box to clear first (None: all; B5's
    dirty rect is the union of the last frame's and this frame's footprints)."""
    k: float
    origin: tuple = (0, 0)
    background: str = "glass"
    cards: list = field(default_factory=list)      # far -> near
    tray: list = field(default_factory=list)
    animating: bool = False
    clear: tuple = None


class _SpriteScaler:
    """Per-card sprite resizing: BILINEAR while animating, LANCZOS at rest (CAR section 5); the
    scales are quantised by the caller (B4)."""
    FACES = 4

    def __init__(self, limit=64):
        self._cache = OrderedDict()
        self._faces = OrderedDict()
        self._borders = OrderedDict()
        self._limit = limit

    def get(self, sprite, size, animating):
        size = (max(1, int(size[0])), max(1, int(size[1])))
        if size == sprite.size:
            return sprite
        key = (id(sprite), size, animating)
        hit = self._cache.get(key)
        if hit is None or hit[0] is not sprite:
            resample = Image.Resampling.BILINEAR if animating else Image.Resampling.LANCZOS
            hit = (sprite, sprite.resized(size, resample))
            self._cache[key] = hit
            while len(self._cache) > self._limit:
                self._cache.popitem(last=False)
        else:
            self._cache.move_to_end(key)
        return hit[1]

    def __len__(self):
        return len(self._cache)

    def face(self, key, refs, build, animating):
        """A placeholder card face, cached for rest frames only (at most FACES of them: a centre
        face is 1.6 MB at k = 2). ``refs`` are the sprites it was built from, compared by
        identity, so a recycled id() never returns a stale face."""
        if animating:
            return build()
        key = tuple(key)
        hit = self._faces.get(key)
        if hit is not None and len(hit[0]) == len(refs) and all(a is b for a, b in zip(hit[0], refs)):
            self._faces.move_to_end(key)
            return hit[1]
        value = build()
        self._faces[key] = (tuple(refs), value)
        while len(self._faces) > self.FACES:
            self._faces.popitem(last=False)
        return value

    def border(self, kind, size, width):
        """A tray slot's border ring (slot_border_sprite) in its colour, cached by (kind, size,
        width): the spring changes the size on every frame of the reveal only."""
        key = (kind, int(size[0]), int(size[1]), int(width))
        hit = self._borders.get(key)
        if hit is None:
            ring = slot_border_sprite(kind, size, width)
            hit = self._borders[key] = Sprite.solid(ring.mask, SLOT_BORDERS[kind][0])
            while len(self._borders) > 12:
                self._borders.popitem(last=False)
        else:
            self._borders.move_to_end(key)
        return hit

    def trim(self):
        """Drop every resized sprite, face and border (and the source sprites the keys hold), e.g.
        on hide."""
        self._cache.clear()
        self._faces.clear()
        self._borders.clear()


def quantised(s, steps=BADGE_STEPS):
    """B4: a sprite scale quantised to 1/64, so badge and chip copies repeat across frames."""
    return max(1.0 / steps, round(float(s) * steps) / steps)


def placeholder_face(size, icon, badge=None, badge_xy=(0, 0), shade=0.0, chip=None, chip_xy=(0, 0)):
    """One placeholder card as an opaque premultiplied RGBX image: the #1B1B1D card, the centred
    icon, the badge (with its shadow) at ``badge_xy``, the chip at ``chip_xy`` and the #111 shade
    at ``shade``, all at full strength. The chrome pastes it once at the card's group opacity,
    as CSS applies ``opacity`` to the whole card (fill, icon, badge, chip, shade) at once."""
    w, h = max(1, int(size[0])), max(1, int(size[1]))
    face = Canvas.new((w, h))
    face.fill((0, 0, w, h), PLACEHOLDER_RGB, 1.0)
    if icon is not None:
        face.over_sprite(icon, ((w - icon.size[0]) / 2, (h - icon.size[1]) / 2))
    if badge is not None:
        face.over_sprite(badge, badge_xy)
    if chip is not None:
        face.over_sprite(chip, chip_xy)
    if shade > 0.001:
        face.over((0, 0, w, h), SHADE_RGB, shade)
    return face.image


def _shaded_sprite(sprite, alpha, rgb=SHADE_RGB):
    """``sprite`` with the solid ``rgb`` at ``alpha`` over its colour (its mask unchanged): a
    shade over a sprite, drawn as one sprite."""
    alpha = max(0.0, min(1.0, float(alpha)))
    ink = (rgb[2], rgb[1], rgb[0], 255)                       # B, G, R like the sprites
    if sprite.colour_image is None:
        colour = tuple(round(c * (1.0 - alpha) + i * alpha) for c, i in zip(sprite.colour[:3], ink)) + (255,)
        return Sprite(sprite.mask, colour)
    solid = Image.new("RGBX", sprite.colour_image.size, ink)
    return Sprite(sprite.mask, colour_image=Image.blend(sprite.colour_image, solid, alpha))


def _under_keep(cover, drawn):
    """The factor for what farther cards left inside a card's rect before the card draws its
    chrome at alpha ``drawn`` over it: CSS shows them through the card at 1 - cover, and the
    card's own chrome already lets (1 - drawn) of them through, so keep = (1 - cover) / (1 - drawn).
    Without a group fade (cover == op) that is 1 - o for a thumbnail card (drawn = op * s: the
    same ratio thumb_opacity solves) and 1 for a placeholder face (drawn = op: plain over)."""
    drawn = max(0.0, min(1.0, drawn))
    if drawn >= 1.0 - FADE_EPSILON:
        return 0.0
    return max(0.0, min(1.0, (1.0 - max(0.0, min(1.0, cover))) / (1.0 - drawn)))


def _intersect(a, b):
    l, t, r, bottom = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return (l, t, r, bottom) if r > l and bottom > t else None


def _union(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _disjoint(boxes):
    """Merge overlapping boxes into their bounding boxes until none overlap."""
    boxes = [tuple(box) for box in boxes]
    changed = True
    while changed:
        changed = False
        out = []
        for box in boxes:
            for i, other in enumerate(out):
                if _intersect(box, other) is not None:
                    out[i] = (min(box[0], other[0]), min(box[1], other[1]), max(box[2], other[2]), max(box[3], other[3]))
                    changed = True
                    break
            else:
                out.append(box)
        boxes = out
    return boxes


def _under(canvas, rect, drawn):
    """What the farther cards left inside ``rect``: [(box, pixels)] for the non-empty parts,
    looked for only where their footprints (``drawn``: rect, shadow and frame boxes) meet the
    rect, so a centre card over two side cards reads two narrow strips, not its whole rect."""
    found = []
    for box in _disjoint(filter(None, (_intersect(rect, footprint) for footprint in drawn))):
        hit = canvas.content(box)
        if hit is not None:
            found.append(hit)
    return found


def _frame_reach(card, k):
    return round(OUTLINE_OFFSET * k * card.s) + max(1, round(OUTLINE_WIDTH * k * card.s))


def card_footprint(rect, card, shadows, k):
    """Everything a card may draw (canvas px): its rect (face, shade, badge, chip), its shadows'
    box and its frame ring, with a 2 px margin for rounding."""
    l, t, r, b = rect
    box = shadows.footprint(rect, card.s, card.selw) if card.op > 0.001 else None
    if box is not None:
        l, t, r, b = min(l, box[0]), min(t, box[1]), max(r, box[2]), max(b, box[3])
    if card.selw > 0.004:
        reach = _frame_reach(card, k)
        l, t, r, b = min(l, rect[0] - reach), min(t, rect[1] - reach), max(r, rect[2] + reach), max(b, rect[3] + reach)
    return (l - 2, t - 2, r + 2, b + 2)


def slot_footprint(rect, slot, k):
    """A tray slot's drawn box (canvas px): the content box, its border, and the caption row."""
    l, t, r, b = rect
    width = max(1, round(k * slot.scale))
    right = r + width
    if slot.caption is not None:
        right = max(right, l + round(slot.caption.size[0] * slot.scale))
    bottom = b + width + round((CAPTION_GAP + CAPTION_H) * k * slot.scale) + 2
    return (l - width - 2, t - width - 2, right + 2, bottom)


def scene_footprint(scene, shadows):
    """The union (canvas px) of everything the scene draws, or None (B5's dirty rect)."""
    ox, oy = scene.origin
    box = None
    for card in scene.cards:
        l, t, r, b = card.rect
        if card.op <= 0.001 or r <= l or b <= t:
            continue
        box = _union(box, card_footprint((l - ox, t - oy, r - ox, b - oy), card, shadows, scene.k))
    for slot in scene.tray:
        if slot.opacity <= 0.001:
            continue
        l, t, r, b = slot.rect
        box = _union(box, slot_footprint((l - ox, t - oy, r - ox, b - oy), slot, scene.k))
    return box


def _draw_tray(canvas, scene, scaler):
    ox, oy = scene.origin
    k = scene.k
    for slot in scene.tray:
        a = max(0.0, min(1.0, slot.opacity))
        if a <= 0.001:
            continue
        l, t, r, b = slot.rect
        rect = (l - ox, t - oy, r - ox, b - oy)
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        if w <= 0 or h <= 0:
            continue
        bg = SLOT_BG_A * (1.0 - max(0.0, min(1.0, slot.fill))) * a
        if bg > 0.001:
            canvas.over(rect, (255, 255, 255), bg)
        width = max(1, round(k * slot.scale))
        for kind, weight in slot.borders.items():
            alpha = weight * a * SLOT_BORDERS[kind][1]
            if alpha <= 0.002:
                continue
            canvas.over_sprite(scaler.border(kind, (w, h), width), (rect[0] - width, rect[1] - width), alpha)
        if slot.glyph_sprite is not None and slot.glyph > 0.002:
            sprite = slot.glyph_sprite
            size = (sprite.size[0] * slot.scale, sprite.size[1] * slot.scale)
            glyph = scaler.get(sprite, size, scene.animating)
            canvas.over_sprite(glyph, (rect[0] + (w - glyph.size[0]) / 2, rect[1] + (h - glyph.size[1]) / 2),
                               slot.glyph * SLOT_GLYPH_A * a)
        if slot.badge is not None and slot.badge_alpha > 0.002:
            badge = scaler.get(slot.badge, (slot.badge.size[0] * slot.scale, slot.badge.size[1] * slot.scale),
                               scene.animating)
            inset = SLOT_BADGE_INSET * k * slot.scale
            canvas.over_sprite(badge, (rect[0] + inset, rect[3] - inset - badge.size[1]), slot.badge_alpha * a)
        if slot.caption is not None:
            caption = scaler.get(slot.caption, (slot.caption.size[0] * slot.scale, slot.caption.size[1] * slot.scale),
                                 scene.animating)
            top = rect[3] + width + CAPTION_GAP * k * slot.scale
            canvas.over_sprite(caption, (rect[0] - width, top), a)


def compose_chrome(canvas, scene, shadows, scaler=None):
    """Compose one chrome frame into the premultiplied ``canvas`` (chrome-local px) and return
    the box drawn (canvas px) or None. The tray first (the cards group lies over it); then the
    cards far -> near: shadows (side, then focus: ShadowCache.paint, outside the card only);
    then what the farther cards left inside the card's rect keeps the share CSS shows through
    the card (1 - cover, see _under_keep; an opaque card clears it); then either the placeholder
    face at the effective opacity op, or (over a DWM thumbnail shown at o) the badge and chip at
    o and the #111 shade at op * s over the card, its badge and chip, and what shows through; the
    selection frame on the centre card. B5: only ``scene.clear`` (the dirty rect) is cleared."""
    scaler = scaler if scaler is not None else _SpriteScaler()      # an empty scaler is falsy
    if scene.clear is None:
        canvas.clear()
    else:
        canvas.clear(scene.clear)
    ox, oy = scene.origin
    k = scene.k
    drawn_box = None
    if scene.tray:
        _draw_tray(canvas, scene, scaler)
        for slot in scene.tray:
            if slot.opacity > 0.001:
                l, t, r, b = slot.rect
                drawn_box = _union(drawn_box, slot_footprint((l - ox, t - oy, r - ox, b - oy), slot, k))
    drawn = []                                   # footprints of the cards drawn so far
    for card in scene.cards:
        l, t, r, b = card.rect
        rect = (l - ox, t - oy, r - ox, b - oy)
        if card.op <= 0.001 or r <= l or b <= t:
            continue
        shadows.paint(canvas, rect, card.s, card.op, card.selw, scene.animating)
        footprint = card_footprint(rect, card, shadows, k)
        cover = card.op if card.cover is None else card.cover
        # The thumbnail shows at o under the chrome; the badge and chip use o too, and the #111
        # shade at op * s lies over them (thumb_opacity).
        o = thumb_opacity(card.op, card.shade)
        s_alpha = shade_alpha(card.op, card.shade)
        q = quantised(card.s)                                           # B4
        badge = chip = None
        if card.badge is not None:
            sprite, pad = card.badge
            badge = scaler.get(sprite, (sprite.size[0] * q, sprite.size[1] * q), scene.animating)
            bx = rect[0] + BADGE_INSET * k * card.s - pad * q
            by = rect[3] - BADGE_INSET * k * card.s - BADGE_SIZE * k * q - pad * q
        if card.chip is not None:
            chip = scaler.get(card.chip, (card.chip.size[0] * q, card.chip.size[1] * q), scene.animating)
            cx, cy = rect[0] + CHIP_INSET * k * card.s, rect[1] + CHIP_INSET * k * card.s
        if card.placeholder is not None:
            # No thumbnail below: the whole card is chrome, one opaque face pasted once at op.
            w, h = rect[2] - rect[0], rect[3] - rect[1]
            icon = scaler.get(card.placeholder, (card.placeholder.size[0] * card.s,
                                                 card.placeholder.size[1] * card.s), scene.animating)
            badge_xy = (round(bx) - rect[0], round(by) - rect[1]) if badge is not None else (0, 0)
            chip_xy = (round(cx) - rect[0], round(cy) - rect[1]) if chip is not None else (0, 0)
            shade = max(0.0, min(1.0, card.shade))
            face = scaler.face((w, h, badge_xy, chip_xy, round(shade * 255)), (icon, badge, chip),
                               lambda: placeholder_face((w, h), icon, badge, badge_xy, shade, chip, chip_xy),
                               scene.animating)
            level = max(0, min(255, round(255 * max(0.0, min(1.0, card.op)))))
            if level >= 255:
                canvas.image.paste(face, rect[:2])
            else:
                # An opaque face pasted over at op is exact CSS: a closed centre card (35 %) keeps
                # the side card under it, badge and shade, at 65 %. Inside a fading group the
                # farther cards are first reduced to what CSS shows through (1 - cover).
                keep = _under_keep(cover, card.op)
                if keep <= FADE_EPSILON:
                    canvas.clear(rect)
                elif keep < 1.0 - FADE_EPSILON:
                    table = fade_lut(keep)
                    for box, pixels in _under(canvas, rect, drawn):
                        canvas.image.paste(_point(pixels, table), box[:2])
                if level > 0:
                    canvas.image.paste(face, rect[:2], Image.new("L", face.size, level))
        else:
            keep = _under_keep(cover, s_alpha)
            below = _under(canvas, rect, drawn) if keep > FADE_EPSILON else ()
            shade = byte_level(s_alpha) / 255 if s_alpha > 0.001 else 0.0     # the fill and the table agree
            if shade:
                canvas.fill(rect, SHADE_RGB, shade)         # the fast overwrite where nothing shows through
            else:
                canvas.clear(rect)
            if below:
                # The farther cards' chrome (their shade, badge and shadows) at keep, then this
                # card's shade over it, in one table pass over where they drew only.
                table = fade_lut(keep, SHADE_RGB, shade)
                for box, pixels in below:
                    canvas.image.paste(_point(pixels, table), box[:2])
            # The exact order is shade over (sprite at o over what shows through). The rect
            # already holds S = shade over what shows through, and for a sprite pixel B with
            # coverage m that order equals S * (1 - o m) + o m * (shade over B): so the sprite,
            # its colour shaded, goes over S at o (_shaded_sprite; one paste, no re-fill).
            if badge is not None:
                canvas.over_sprite(_shaded_sprite(badge, shade) if shade else badge, (bx, by), o)
            if chip is not None:
                canvas.over_sprite(_shaded_sprite(chip, shade) if shade else chip, (cx, cy), o)
        if card.selw > 0.004:
            width = max(1, round(OUTLINE_WIDTH * k * card.s))
            offset = round(OUTLINE_OFFSET * k * card.s)
            outer = (rect[0] - offset - width, rect[1] - offset - width, rect[2] + offset + width, rect[3] + offset + width)
            canvas.rect_outline(outer, width, (255, 255, 255), OUTLINE_ALPHA * card.selw * card.op)
        drawn.append(footprint)
        drawn_box = _union(drawn_box, footprint)
    return drawn_box


def compose_layer(canvas, sprites, clear=True):
    """A B2 layer (label or dots): ``sprites`` = [(Sprite, (x, y), alpha)] in canvas px, drawn in
    order with masked pastes. Returns the canvas."""
    if clear:
        canvas.clear()
    for sprite, xy, alpha in sprites:
        if sprite is not None and alpha > 0.002:
            canvas.over_sprite(sprite, xy, alpha)
    return canvas


# ================================================== the GPU chrome's sprites (K4 9, step 3; lead ruling R-h)
# control_center/stage/picker_chrome.py prepares these once (per k) as DirectComposition surfaces and
# lets the compositor move, scale and fade them (CAROUSEL.md 12.4). Every helper is pure PIL and
# returns a straight-colour Sprite at scale 1 (with where it sits relative to the card's top-left)
# or (w, h, premultiplied BGRA bytes), the bytes a surface takes (K4 0.7).
GPU_SHADOWS = {"side": CARD_SHADOWS["side"], "focus": CARD_SHADOWS["focus"],
               "fly": (30, 70, 0.45)}                       # the fly: 0 30px 70px rgba(0,0,0,.45) (BS:120)


def sprite_bgra(sprite):
    """(w, h, premultiplied BGRA bytes) of a Sprite (Pillow's BGRa packer premultiplies)."""
    w, h = sprite.size
    if sprite.colour_image is None:
        b, g, r = sprite.colour[:3]
        image = Image.new("RGBA", (w, h), (r, g, b, 0))
        image.putalpha(sprite.mask)
    else:
        cb, cg, cr, _ = sprite.colour_image.split()
        image = Image.merge("RGBA", (cr, cg, cb, sprite.mask))
    return w, h, image.tobytes("raw", "BGRa")


def solid_bgra(rgb, w, h):
    """(w, h, opaque BGRA bytes) of a solid colour (a shared surface per colour and size, G1-9)."""
    w, h = max(1, int(w)), max(1, int(h))
    return w, h, bytes((int(rgb[2]), int(rgb[1]), int(rgb[0]), 255)) * (w * h)


def card_box_px(k):
    """The card's box at scale 1 in whole physical px (the GPU chrome's card-local frame)."""
    return max(1, round(CARD_W * k)), max(1, round(CARD_H * k))


def gpu_shadow_sprite(kind, k, size=None):
    """(Sprite, (dx, dy)): one fixed box-shadow layer (``"side"`` 0 12 30 /.30, ``"focus"`` 0 24 60
    /.45, ``"fly"`` 0 30 70 /.45) around a box of ``size`` px (default the card at scale 1), at full
    resolution, black with the shadow's alpha, and **the box itself cleared** (CSS clips an outer
    box-shadow under its box), so the layer can lie above the element's own DWM thumbnail. The
    same separable erfc profile as ShadowCache, stopped where 8 bits round to 0 (shadow_reach).
    (dx, dy) is the sprite's top-left relative to the box's top-left."""
    oy, blur, alpha = GPU_SHADOWS[kind]
    w0, h0 = size if size is not None else card_box_px(k)
    w0, h0 = max(1, round(w0)), max(1, round(h0))
    sigma = max(0.25, blur / 2 * k)
    pad = math.ceil(shadow_reach(alpha) * sigma)
    oy_px = round(oy * k)
    fw, fh = w0 + 2 * pad, h0 + 2 * pad
    gx = _edge_profile(fw, 1.0, pad, w0, sigma)
    gy = _edge_profile(fh, 1.0, pad, h0, sigma)
    row = Image.frombytes("L", (fw, 1), bytes(round(255 * v) for v in gx))
    column = Image.frombytes("L", (1, fh), bytes(round(255 * alpha * v) for v in gy))
    mask = ImageChops.multiply(row.resize((fw, fh), Image.Resampling.NEAREST),
                               column.resize((fw, fh), Image.Resampling.NEAREST))
    top = pad - oy_px                                  # the box, in the mask (the shadow sits oy lower)
    mask.paste(0, (pad, max(0, top), pad + w0, max(0, top + h0)))
    return Sprite.solid(mask, (0, 0, 0)), (-pad, -pad + oy_px)


def frame_ring_sprite(k):
    """(Sprite, (dx, dy)): the selection frame at scale 1 (K4 9.3): a white ring OUTLINE_WIDTH k wide
    whose outer edge is (OUTLINE_OFFSET + OUTLINE_WIDTH) k outside the card, as compose_chrome draws
    it at s = 1; its 0.90 x selw is the visual's opacity."""
    width = max(1, round(OUTLINE_WIDTH * k))
    off = round(OUTLINE_OFFSET * k)
    w0, h0 = card_box_px(k)
    fw, fh = w0 + 2 * (off + width), h0 + 2 * (off + width)
    mask = Image.new("L", (fw, fh), 255)
    mask.paste(0, (width, width, fw - width, fh - width))
    return Sprite.solid(mask, (255, 255, 255)), (-(off + width), -(off + width))


def placeholder_face_bgra(icon, k):
    """(w, h, opaque BGRA bytes): a placeholder card's face at scale 1 (the #1B1B1D card with the
    centred icon Sprite at scale 1, ``placeholder_sprite``); badge, chip and shade are separate
    visuals of the GPU chrome, so none is baked in."""
    w0, h0 = card_box_px(k)
    return w0, h0, placeholder_face((w0, h0), icon).tobytes()


def slot_border_colour_sprite(kind, size, width):
    """A tray slot's border ring (slot_border_sprite) in its own colour (its alpha is the visual's)."""
    ring = slot_border_sprite(kind, size, width)
    return Sprite.solid(ring.mask, SLOT_BORDERS[kind][0])


def half_sprite(sprite):
    """((Sprite at half resolution), (sx, sy)): the minified copy the GPU chrome shows on side cards
    (a card at s <= 0.56 samples a full-size sprite 2x apart under LINEAR, which aliases; the covers'
    two-level rule, S5-28). (sx, sy) scale it back to the full sprite's footprint exactly."""
    w, h = sprite.size
    hw, hh = max(1, (w + 1) // 2), max(1, (h + 1) // 2)
    small = sprite.resized((hw, hh), Image.Resampling.LANCZOS)
    return small, (w / hw, h / hh)
