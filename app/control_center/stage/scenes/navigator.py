"""The r3 Navigator scene: the compact liquid-glass card on the monitor's left edge (r3 README section 5,
section 4 motion; DESKTOP_STAGE section 24).

Units are the prototype's px (its 2560 x 720 monitor stage); ``k`` = physical px per unit (2 on the
5120 x 1440 G93SC, ``StageLayout.k``). Every rest position is a whole physical px.

The card (section 5): left 20, vertically centred in the work area, width 250, height = content,
padding 16, gap 14, radius 26. Liquid glass, bottom to top:

- ``shadow``  ``0 18px 50px rgba(0,0,0,.35)`` around the rounded card, built at 1/4 and stretched;
- ``glass``   one opaque sprite per card height: the backdrop (the desktop behind the card, captured
              with the Navigator excluded, ``blur(14px) saturate(1.8) brightness(1.06)``), the fill
              (``rgba(18,18,22,.30)`` then the 160deg white gradient .18 / .05 at 42 % / .09), the
              specular (radial white .22, 220 x 160 at (-40, -60)) and the four inset rim lines, cut
              to the 26-unit radius; a refreshed backdrop crossfades in over a second glass visual;
- the ``path`` row, the ``content`` container (the per-kind visuals, the content swap moves it),
  the ``keys`` grid and the HOLD row (r3.1: key chips `1 Home`, `4 Queue` ... filling with the hold). Text carries ``0 1px 2px rgba(0,0,0,.35)``.

Motion (section 4), all compositor-run through ``animation.Batch``: show / hide = root opacity 280 ms
and root X -24 -> 0 u 420 ms, OUT; content swap (r4 M14: the knob's M1 timing, in sync with it) = the content
container from +/-28 u and opacity 0, 240 ms opacity E.out / SPRING.snap transform (416 ms; curves "SNAP")
(deeper = from the right, as the knob's content layer); r4 reduced motion: a 160 ms opacity crossfade; list
rows and covers 380 ms transform / 280 ms opacity (EASE); the Tracks plate 320 ms; bar fills and the
temperature marker 120 ms LINEAR; the 60 % / 100 % row opacities 200 ms EASE; a pressed key's fill
120 ms EASE. Reduced motion (r4 section 7): only opacity moves; show / hide is a 160 ms fade, and the
offsets, the bar fills' scale and the temperature marker jump (DD-DES-005).

Pure Python + PIL: no Win32 here. The tree is built through ``tree.Tree`` on a ``NativeDevice`` (the
``NanoD-navigator`` thread, ``control_center.navigator``) or a ``FakeDevice`` (tests, the reference
renders: ``render_states``).
"""
from __future__ import annotations

import math
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from ... import render_music as RM
from ...carousel_render import ASCENT, LINE_NORMAL, baseline_in
from ...navigator_model import NavContent, kelvin_rgb
from ..surfaces import opaque_bytes

# --------------------------------------------------------------------------- geometry (units)
LEFT, WIDTH, PAD, GAP, RADIUS = 20, 250, 16, 14, 26
INNER = WIDTH - 2 * PAD
SLIDE_U = 24
SWAP_U = 28                         # r4 M14 = M1: the content enters from 28 units (the knob's 28 px)
ROW_H = 38
LIST_H = 190
COVERS_H = 196
COVER_U = 120
COVER_OFFS = (0, 86, 132, 170)
COVER_SCALES = (1.0, 0.55, 0.38, 0.30)
COVER_OPS = (1.0, 0.55, 0.25, 0.0)
SHADOW = (0, 18, 50, 0.35)          # x, y, blur, alpha
SHADOW_REACH_U = 75                 # 3 sigma of the 50-unit blur
HOST_W_U = LEFT + WIDTH + SHADOW_REACH_U
KEYS_H = 1 + 12 + 16 + 8 + 16
HOLD_H = 16                         # r3.1: the HOLD row of 16-unit key chips (was the 14-unit line)
HOLD_OVERLAP = 6                    # the row sits this far into the gap (r3: 4 for the 14-unit line): 24 u in all
AREA_GAP = 12                       # r3.1 Lights card: the area block under the Scene row
AREA_LINE_H = 14
LIGHT_ROW_H = 16
LIGHT_ROW_GAP = 4                   # r3.1.1: the per-light rows, gap 4 under the summary line
L_VALUE_H = 18                      # r3.1.1 compact Lights card: the caps label + 16/18 tabular value line
L_BAR_Y = L_VALUE_H + 5             # its 4-unit bar, 5 below
L_ROW_H = L_BAR_Y + 4
L_GAP = 10                          # the card's content gap
L_SUMMARY_H = 15                    # the 12/15 summary line
LN = LINE_NORMAL
CAPS = 11 * LN                      # a caps label row (11 px, line-height normal)

# motion (ms)
SHOW_OP_MS, SHOW_X_MS = 280, 420
SWAP_OP_MS = 240                    # r4 M14 = M1: opacity 0 -> 1 in 240 ms E.out
SWAP_CURVE = "SNAP"                 # r4 M14 = M1: SPRING.snap over its settle time
SWAP_X_MS = 416
LIST_MS, LIST_OP_MS, PLATE_MS = 380, 280, 320
BAR_MS, DIM_MS, KEY_MS, FROST_MS = 120, 200, 120, 250
ART_FADE_MS = 240                   # a Recently Added cover landing over its accent tile
ART_KEEP = 24                       # cover images the scene keeps (the Tk side's LRU holds the rest)
REDUCED_SWAP_MS = 160               # r4 section 7: every animation a 160 ms opacity crossfade
REDUCED_FADE_MS = REDUCED_SWAP_MS   # DD-DES-005: show / hide too (r4 section 7)

WHITE = (255, 255, 255)
TEXT_SHADOW = (0, 1, 2, 0.35)      # x, y, blur, alpha (units)
FALLBACK_BACKDROP = (58, 60, 68)   # no capture: a neutral mid-dark ground under the fill
TRACK_A = 0.20
TRACK_A_BRI = 0.18
RADIAL_EDGE = 181.0                # Image.radial_gradient: the value at the closest side (128 px)


def area_block_height(rows: int) -> float:
    """r3.1.1 Lights card: ``rows`` per-light rows (gap 4 each) under the summary line."""
    return rows * (LIGHT_ROW_GAP + LIGHT_ROW_H)


def content_height(kind: str) -> float:
    if kind.startswith("lights+"):            # r3.1.1 compact card (NavContent.geometry: lights+N rows)
        return 2 * L_ROW_H + 2 * L_GAP + L_SUMMARY_H + area_block_height(int(kind.split("+", 1)[1] or 0))
    if kind == "now":
        return 64 + 12 + (CAPS + 6 + 4)
    if kind == "lights":
        return content_height("lights+0")
    if kind == "covers":
        return COVERS_H + 10 + (19 + 2 + 16 + 2 + 15)
    if kind in ("rows", "scenes"):
        return LIST_H + 10 + 15
    if kind == "seek":
        return 44 + 10 + 40 + 10 + 4
    return 0.0


def card_height(kind: str, hold: bool) -> float:
    h = PAD + CAPS + GAP + content_height(kind) + GAP + KEYS_H + PAD
    if hold:
        h += GAP - HOLD_OVERLAP + HOLD_H
    return h


def content_top() -> float:
    return PAD + CAPS + GAP


def keys_top(kind: str) -> float:
    return content_top() + content_height(kind) + GAP


class NavGeometry:
    """Where the host and the card go on a monitor: ``work`` = rcWork (left, top, right, bottom),
    physical px. The host is a column at the monitor's left edge over the work area's height."""

    def __init__(self, work, k: float):
        l, t, r, b = (int(v) for v in work)
        self.work = (l, t, r, b)
        self.k = float(k)
        self.host = (l, t, int(round(HOST_W_U * k)), b - t)       # x, y, w, h (SetWindowPos)

    def px(self, u: float) -> int:
        return int(round(u * self.k))

    def card_w(self) -> int:
        return self.px(WIDTH)

    def card_h(self, kind, hold) -> int:
        return self.px(card_height(kind, hold))

    def card_xy(self, kind, hold):
        """The card's rest top-left in host client px: left 20, centred in the work area."""
        return self.px(LEFT), int(round((self.host[3] - self.card_h(kind, hold)) / 2.0))

    def card_rect_screen(self, kind, hold):
        x, y = self.card_xy(kind, hold)
        return (self.host[0] + x, self.host[1] + y, self.card_w(), self.card_h(kind, hold))


# --------------------------------------------------------------------------- PIL helpers
def _corner(r: int, ss: int = 4):
    """An antialiased quarter disc (top-left corner) of radius ``r`` px as an L image."""
    big = Image.new("L", (r * ss, r * ss), 0)
    ImageDraw.Draw(big).pieslice((0, 0, 2 * r * ss - 1, 2 * r * ss - 1), 180, 270, fill=255)
    return big.reduce(ss)


@lru_cache(maxsize=64)
def rounded_mask(w: int, h: int, r: int):
    """An antialiased rounded rectangle (L) of ``w`` x ``h`` px, corner radius ``r`` px."""
    w, h, r = max(1, int(w)), max(1, int(h)), max(0, min(int(r), int(w) // 2, int(h) // 2))
    m = Image.new("L", (w, h), 255)
    if r <= 0:
        return m
    c = _corner(r)
    m.paste(0, (0, 0, r, r))
    m.paste(0, (w - r, 0, w, r))
    m.paste(0, (0, h - r, r, h))
    m.paste(0, (w - r, h - r, w, h))
    m.paste(c, (0, 0))
    m.paste(c.transpose(Image.Transpose.FLIP_LEFT_RIGHT), (w - r, 0))
    m.paste(c.transpose(Image.Transpose.FLIP_TOP_BOTTOM), (0, h - r))
    m.paste(c.transpose(Image.Transpose.ROTATE_180), (w - r, h - r))
    return m


def _shifted(mask, dx: int, dy: int):
    out = Image.new("L", mask.size, 0)
    out.paste(mask, (dx, dy))
    return out


def _scaled_mask(mask, a: float):
    lvl = max(0.0, min(1.0, a))
    return mask.point([int(v * lvl + 0.5) for v in range(256)])


def _gradient_160(w: int, h: int, stops):
    """CSS ``linear-gradient(160deg, ...)`` of alphas (0..1 at positions 0..1) as an L image."""
    ramp = Image.linear_gradient("L")                          # value = row
    ang = math.radians(160.0)
    dx, dy = math.sin(ang), -math.cos(ang)
    L = abs(w * dx) + abs(h * dy)
    k = 255.0 / L
    c = 127.5 - k * (w / 2.0 * dx + h / 2.0 * dy)
    t = ramp.transform((w, h), Image.Transform.AFFINE, (0, 0, 128, k * dx, k * dy, c),
                       resample=Image.Resampling.BILINEAR)
    lut = []
    for v in range(256):
        p = v / 255.0
        a = stops[-1][1]
        for (p0, a0), (p1, a1) in zip(stops, stops[1:]):
            if p0 <= p <= p1:
                a = a0 + (a1 - a0) * ((p - p0) / (p1 - p0) if p1 > p0 else 0.0)
                break
        lut.append(int(round(a * 255)))
    return t.point(lut)


def _specular(w: int, h: int, k: float):
    """``radial-gradient(closest-side, rgba(255,255,255,.22), transparent)`` in a 220 x 160 box at
    (-40, -60) units, clipped to the card, as an L alpha image."""
    bw, bh = max(2, int(round(220 * k))), max(2, int(round(160 * k)))
    rad = Image.radial_gradient("L").resize((bw, bh), Image.Resampling.BILINEAR)   # 0 centre, 181 at the side
    alpha = rad.point([int(round(max(0.0, 1.0 - v / RADIAL_EDGE) * 0.22 * 255)) for v in range(256)])
    out = Image.new("L", (w, h), 0)
    out.paste(alpha, (int(round(-40 * k)), int(round(-60 * k))))
    return out


def build_frost(capture, k: float, reduce: int = 4):
    """The backdrop at 1/``reduce`` from a capture (RGB) of the host column: ``blur(14px)
    saturate(1.8) brightness(1.06)`` (section 5). None without a capture."""
    from ..blur import saturate_matrix
    if capture is None:
        return None
    src = capture if capture.mode == "RGB" else capture.convert("RGB")
    small = src.reduce(reduce)
    small = small.filter(ImageFilter.GaussianBlur(max(0.1, 14.0 * k / reduce)))
    small = small.convert("RGB", saturate_matrix(1.8))
    b = 1.06
    return small.convert("RGB", (b, 0, 0, 0, 0, b, 0, 0, 0, 0, b, 0))


def glass_sprite(w: int, h: int, k: float, frost=None, frost_box=None, reduce: int = 4):
    """The opaque glass (section 5 recipe) as a premultiplied ``RM.Sprite`` of ``w`` x ``h`` px.
    ``frost``: ``build_frost`` of the host column; ``frost_box``: the card's (x, y) in host px."""
    r = int(round(RADIUS * k))
    if frost is not None and frost_box is not None:
        x, y = frost_box
        box = (x / reduce, y / reduce, (x + w) / reduce, (y + h) / reduce)
        base = frost.resize((w, h), Image.Resampling.BILINEAR, box=box)
    else:
        base = Image.new("RGB", (w, h), FALLBACK_BACKDROP)
    base = Image.blend(base, Image.new("RGB", (w, h), (18, 18, 22)), 0.30)
    base.paste(WHITE, (0, 0), _gradient_160(w, h, ((0.0, 0.18), (0.42, 0.05), (1.0, 0.09))))
    base.paste(WHITE, (0, 0), _specular(w, h, k))
    mask = rounded_mask(w, h, r)
    s = max(1, int(round(k)))
    for (dx, dy), a in (((0, s), 0.60), ((0, -s), 0.14), ((s, 0), 0.22), ((-s, 0), 0.10)):
        band = ImageChops.subtract(mask, _shifted(mask, dx, dy))
        base.paste(WHITE, (0, 0), _scaled_mask(band, a))
    spr = RM.Sprite.new(w, h)
    spr.pm.paste(base, (0, 0), mask)
    spr.a.paste(255, (0, 0), mask)
    return spr


def shadow_sprite(w: int, h: int, k: float, reduce: int = 4):
    """``0 18px 50px rgba(0,0,0,.35)`` of the rounded card: (Sprite, (dx, dy) in card px, scale)."""
    _x, oy, blur, alpha = SHADOW
    sigma = blur / 2.0 * k
    m = int(math.ceil(3 * sigma / reduce)) + 1
    rw, rh = max(1, int(round(w / reduce))), max(1, int(round(h / reduce)))
    mask = Image.new("L", (rw + 2 * m, rh + 2 * m), 0)
    mask.paste(rounded_mask(rw, rh, max(1, int(round(RADIUS * k / reduce)))), (m, m))
    mask = mask.filter(ImageFilter.GaussianBlur(sigma / reduce))
    mask = _scaled_mask(mask, alpha)
    spr = RM.Sprite.new(*mask.size)
    spr.a.paste(mask, (0, 0))
    return spr, (-m * reduce, oy * k - m * reduce), float(reduce)


_DIGIT_CELL = {}   # (size px, wght, track) -> the widest digit's advance (tabular figures)


class Painter:
    """Text and shapes on a premultiplied sprite, at ``k`` px per unit, every text with the card's
    ``0 1px 2px rgba(0,0,0,.35)`` text-shadow (``shadow=False`` for the key digits). ``tabular``:
    every digit takes the widest digit's advance (centred in it), so a changing number keeps its width
    and a right-aligned value does not shift (user 2026-09-29: ``100% · 4400 K`` -> ``4500 K`` moved)."""

    def __init__(self, w_u: float, h_u: float, k: float):
        self.k = float(k)
        self.w, self.h = max(1, int(round(w_u * k))), max(1, int(round(h_u * k)))
        self.spr = RM.Sprite.new(self.w, self.h)
        self.eng = RM.text_engine()

    def _pieces(self, text, size, wght, track, tabular):
        """[(piece, x offset px)] and the line width in px (per character with tabular digits)."""
        eng = self.eng
        if not tabular or not any(ch.isdigit() for ch in text):
            return [(text, 0.0)], eng.width(text, size, wght, track)
        key = (round(size, 3), wght, track)
        cell = _DIGIT_CELL.get(key)
        if cell is None:
            cell = _DIGIT_CELL[key] = max(eng.width(d, size, wght, track) for d in "0123456789")
        pieces, pen = [], 0.0
        for ch in text:
            w = eng.width(ch, size, wght, track)
            if ch.isdigit():
                pieces.append((ch, pen + (cell - w) / 2.0))
                pen += cell
            else:
                if not ch.isspace():
                    pieces.append((ch, pen))
                pen += w
        return pieces, pen

    def text(self, text, x, top, px, lh, *, wght=400, track=0.0, rgb=WHITE, alpha=1.0, max_w=None, align="left",
             caps=False, shadow=True, tabular=False):
        """One line at unit coordinates; returns its width in units."""
        k, eng = self.k, self.eng
        text = " ".join(str(text or "").split())
        if caps:
            text = text.upper()
        size = px * k
        if max_w is not None:
            text = eng.fit(text, size, wght, track, max_w * k)
        if not text:
            return 0.0
        pieces, width = self._pieces(text, size, wght, track, tabular)
        left = x * k - (width / 2.0 if align == "center" else width if align == "right" else 0.0)
        pad = int(math.ceil(size * 0.6)) + 4
        x0, y0 = int(math.floor(left)) - pad, int(math.floor(top * k)) - pad
        mw = int(math.ceil(width)) + 2 * pad + 2
        mh = int(math.ceil(max(lh * k, LN * size))) + 2 * pad + 2
        mask = Image.new("L", (mw, mh), 0)
        colour = Image.new("RGBA", (mw, mh), (0, 0, 0, 0))
        base = baseline_in(top * k, lh * k, size) - y0
        for piece, offset in pieces:
            eng.draw(piece, left - x0 + offset, base, size, wght, track, mask, colour)
        if shadow:
            sx, sy, blur, sa = TEXT_SHADOW
            sh = mask.filter(ImageFilter.GaussianBlur(max(0.1, blur / 2.0 * k)))
            RM.over_mask(self.spr, sh, (0, 0, 0), sa, (x0 + int(round(sx * k)), y0 + int(round(sy * k))))
        RM.over_mask(self.spr, mask, rgb, alpha, (x0, y0))
        if colour.getbbox():
            RM.over_colour(self.spr, colour, alpha, (x0, y0))
        return width / k

    def width(self, text, px, *, wght=400, track=0.0, caps=False, tabular=False) -> float:
        text = " ".join(str(text or "").split())
        return self._pieces(text.upper() if caps else text, px * self.k, wght, track, tabular)[1] / self.k

    def caps(self, text, x, top, *, rgb=WHITE, alpha=0.75, align="left", max_w=None, tabular=False):
        return self.text(text, x, top, 11, CAPS, wght=600, track=0.12, rgb=rgb, alpha=alpha, align=align,
                         caps=True, max_w=max_w, tabular=tabular)

    def rect(self, x, y, w, h, rgb=WHITE, alpha=1.0, radius=0.0):
        k = self.k
        x0, y0 = int(round(x * k)), int(round(y * k))
        pw, ph = max(1, int(round(w * k))), max(1, int(round(h * k)))
        m = rounded_mask(pw, ph, int(round(radius * k))) if radius else Image.new("L", (pw, ph), 255)
        RM.over_mask(self.spr, m, rgb, alpha, (x0, y0))

    def hline(self, x, y, w, alpha):
        k = self.k
        RM.over_mask(self.spr, Image.new("L", (max(1, int(round(w * k))), max(1, int(round(k)))), 255), WHITE,
                     alpha, (int(round(x * k)), int(round(y * k))))

    def frame(self, x, y, size, radius, lw_u, alpha):
        k = self.k
        s = int(round(size * k))
        outer = rounded_mask(s, s, int(round(radius * k)))
        lw = max(1, int(round(lw_u * k)))
        inner = Image.new("L", (s, s), 0)
        inner.paste(rounded_mask(s - 2 * lw, s - 2 * lw, max(0, int(round(radius * k)) - lw)), (lw, lw))
        RM.over_mask(self.spr, ImageChops.subtract(outer, inner), WHITE, alpha, (int(round(x * k)), int(round(y * k))))


# --------------------------------------------------------------------------- sprites (pure)
def path_sprite(path: str, k: float):
    p = Painter(INNER, CAPS, k)
    p.caps(path, 0, 0, max_w=INNER)
    return p.spr


def now_text_sprite(c: NavContent, k: float):
    w = INNER - 64 - 12
    p = Painter(w, 54, k)
    p.text(c.title, 0, 0, 15, 19, wght=600, max_w=w)
    p.text(c.artist, 0, 21, 12, 16, alpha=0.85, max_w=w)
    p.text(c.status, 0, 39, 11, 15, rgb=c.status_rgb, alpha=c.status_a, max_w=w)
    return p.spr


def label_row_sprite(label: str, value: str, k: float):
    p = Painter(INNER, CAPS, k)
    p.caps(label, 0, 0)
    p.caps(value, INNER, 0, align="right", tabular=True)
    return p.spr


def bar_sprite(w_u: float, rgb, alpha: float, k: float, *, left_round=True, right_round=True):
    """A 4-unit bar (radius 2) as a sprite: the track, or a fill (left end rounded, as the CSS fill
    clipped by its rounded track)."""
    k = float(k)
    w, h = max(1, int(round(w_u * k))), max(1, int(round(4 * k)))
    r = int(round(2 * k))
    m = rounded_mask(w, h, r)
    if not right_round:
        m = m.copy()
        m.paste(255, (max(0, w - r), 0, w, h))
    if not left_round:
        m = m.copy()
        m.paste(255, (0, 0, min(w, r), h))
    spr = RM.Sprite.new(w, h)
    RM.over_mask(spr, m, rgb, alpha, (0, 0))
    return spr


def gradient_bar_sprite(k: float):
    """The temperature track: linear-gradient(90deg, 2200 K, 3400 K, 6500 K), radius 2."""
    w, h = max(2, int(round(INNER * k))), max(1, int(round(4 * k)))
    stops = (kelvin_rgb(2200), kelvin_rgb(3400), kelvin_rgb(6500))
    row = Image.new("RGB", (w, 1))
    px = row.load()
    for x in range(w):
        t = x / (w - 1) * 2.0
        i = min(1, int(t))
        f = t - i
        a, b = stops[i], stops[i + 1]
        px[x, 0] = tuple(int(round(a[j] + (b[j] - a[j]) * f)) for j in range(3))
    img = row.resize((w, h))
    spr = RM.Sprite.new(w, h)
    m = rounded_mask(w, h, int(round(2 * k)))
    spr.pm.paste(img, (0, 0), m)
    spr.a.paste(255, (0, 0), m)
    return spr


def marker_sprite(k: float):
    """The white 4 x 12 temperature marker with its 1 px dark ring (box-shadow 0 0 0 1px rgba(0,0,0,.4))."""
    ring = max(1, int(round(k)))
    w, h = int(round(4 * k)), int(round(12 * k))
    spr = RM.Sprite.new(w + 2 * ring, h + 2 * ring)
    RM.over_mask(spr, rounded_mask(w + 2 * ring, h + 2 * ring, int(round(2 * k)) + ring), (0, 0, 0), 0.4, (0, 0))
    RM.over_mask(spr, rounded_mask(w, h, int(round(2 * k))), WHITE, 1.0, (ring, ring))
    return spr, ring


def _baseline(top, lh, px):
    """The CSS line-box baseline of a ``px`` line in a ``lh`` box at ``top`` (units)."""
    return top + (lh - LN * px) / 2.0 + ASCENT * px


def _top_for_baseline(base, px):
    """The ``top`` of a normal-height ``px`` line whose baseline is ``base`` (units)."""
    return base - ASCENT * px


def status_sprite(text: str, rgb, alpha: float, k: float, w_u: float = INNER, lh: float = 15):
    p = Painter(w_u, lh, k)
    p.text(text, 0, 0, 11, lh, rgb=rgb, alpha=alpha, max_w=w_u)
    return p.spr


def covers_text_sprite(c: NavContent, k: float):
    p = Painter(INNER, 54, k)
    p.text(c.title, 0, 0, 15, 19, wght=600, max_w=INNER)
    p.text(c.artist, 0, 21, 12, 16, alpha=0.85, max_w=INNER)
    p.text(c.status, 0, 39, 11, 15, rgb=c.status_rgb, alpha=c.status_a, max_w=INNER)
    return p.spr


def row_sprite(row, k: float):
    """One list row (218 x 38): number (16 wide, 11 px, 70 %), title 13/17 600, tag 10 px 600 caps."""
    p = Painter(INNER, ROW_H, k)
    p.text(row.number, 10, (ROW_H - 11 * LN) / 2, 11, 11 * LN, alpha=0.7)
    tag_w = 0.0
    if row.tag:
        tag_w = p.width(row.tag, 10, wght=600, track=0.08, caps=True)
        p.text(row.tag, INNER - 10, (ROW_H - 10 * LN) / 2, 10, 10 * LN, wght=600, track=0.08, caps=True,
               rgb=row.tag_rgb, alpha=row.tag_a, align="right")
    x = 10 + 16 + 10
    right = INNER - 10 - (tag_w + 10 if row.tag else 0)
    p.text(row.title, x, (ROW_H - 17) / 2, 13, 17, wght=600, rgb=row.title_rgb, max_w=max(10, right - x))
    return p.spr


def plate_sprite(k: float):
    w, h = int(round(INNER * k)), int(round(ROW_H * k))
    m = rounded_mask(w, h, int(round(10 * k)))
    spr = RM.Sprite.new(w, h)
    RM.over_mask(spr, m, WHITE, 0.16, (0, 0))
    s = max(1, int(round(k)))
    RM.over_mask(spr, ImageChops.subtract(m, _shifted(m, 0, s)), WHITE, 0.35, (0, 0))
    return spr


def _art_tile(size_px: int, art, accent: int):
    if art is not None:
        try:
            return RM.fit_square(art.convert("RGB") if art.mode != "RGB" else art, size_px)
        except Exception:
            pass
    rgb = RM.rgb_of(accent)
    top = tuple(min(255, int(v * 1.25 + 18)) for v in rgb)
    bottom = tuple(int(v * 0.55) for v in rgb)
    grad = Image.linear_gradient("L").resize((size_px, size_px))
    return Image.composite(Image.new("RGB", (size_px, size_px), bottom), Image.new("RGB", (size_px, size_px), top),
                           grad)


def cover_sprite(size_u: float, radius_u: float, k: float, art=None, accent=0x2A2A30, *, shadow=None, ring=0.2):
    """A cover: art (or an accent tile), rounded, the inset 1 px white ring, and its drop shadow
    baked in (``shadow`` = (y, blur, alpha) units). Returns (Sprite, margin px)."""
    s = int(round(size_u * k))
    margin = 0
    if shadow is not None:
        oy, blur, a = shadow
        margin = int(math.ceil(1.5 * blur * k + oy * k)) + 2
    spr = RM.Sprite.new(s + 2 * margin, s + 2 * margin)
    mask = rounded_mask(s, s, int(round(radius_u * k)))
    if shadow is not None:
        oy, blur, a = shadow
        sh = Image.new("L", spr.size, 0)
        sh.paste(mask, (margin, margin + int(round(oy * k))))
        sh = sh.filter(ImageFilter.GaussianBlur(blur / 2.0 * k))
        RM.over_mask(spr, sh, (0, 0, 0), a, (0, 0))
    tile = _art_tile(s, art, accent)
    spr.pm.paste(tile, (margin, margin), mask)
    spr.a.paste(255, (margin, margin), mask)
    if ring:
        lw = max(1, int(round(k)))
        inner = Image.new("L", (s, s), 0)
        inner.paste(rounded_mask(s - 2 * lw, s - 2 * lw, max(0, int(round(radius_u * k)) - lw)), (lw, lw))
        RM.over_mask(spr, ImageChops.subtract(mask, inner), WHITE, ring, (margin, margin))
    return spr, margin


def seek_head_sprite(c: NavContent, k: float):
    w = INNER - 44 - 12
    p = Painter(w, 44, k)
    p.text(c.title, 0, (44 - 18) / 2, 14, 18, wght=600, max_w=w)
    return p.spr


def seek_big_sprite(c: NavContent, k: float):
    """The 36 px m:ss (40 line, 600, -0.02 em) and ``of 4:12`` (12 px, 80 %), baseline-aligned, gap 6."""
    p = Painter(INNER, 40, k)
    w = p.text(c.big, 0, 0, 36, 40, wght=600, track=-0.02, tabular=True)
    p.text(c.unit, w + 6, _top_for_baseline(_baseline(0, 40, 36), 12), 12, 12 * LN, alpha=0.8)
    return p.spr


def keys_label_sprite(keys, k: float):
    """The four labels (11 px, white 90 %) at their grid places; the key boxes are their own visuals."""
    col = (INNER - 10) / 2.0
    p = Painter(INNER, 16 + 8 + 16, k)
    for i, key in enumerate(keys[:4]):
        x, y = (i % 2) * (col + 10), (i // 2) * (16 + 8)
        p.text(key.label, x + 16 + 6, y + (16 - CAPS) / 2, 11, CAPS, alpha=0.9 * (1.0 if key.enabled else 0.4),
               max_w=col - 22)
    return p.spr


def key_box_sprite(digit: str, pressed: bool, enabled: bool, k: float):
    p = Painter(16, 16, k)
    a = 1.0 if enabled else 0.4
    if pressed:
        p.rect(0, 0, 16, 16, WHITE, a, radius=4)
        p.text(digit, 8, (16 - 10 * LN) / 2, 10, 10 * LN, wght=700, rgb=(0, 0, 0), alpha=a, align="center",
               shadow=False)
    else:
        p.frame(0, 0, 16, 4, 1, 0.55 * a)
        p.text(digit, 8, (16 - 10 * LN) / 2, 10, 10 * LN, wght=700, alpha=a, align="center", shadow=False)
    return p.spr


def hold_sprite(k: float, holds=()):
    """r3.1 design HOLD row: the caps label ``Hold`` (10 px, 60 %) and one chip per hold (a 16-unit
    key box that fills bottom-up in white with the hold's progress, its digit turning black above
    55 %, then the label, 11 px 90 %), 10 apart. A plain string draws the r3 line instead."""
    p = Painter(INNER, HOLD_H, k)
    if isinstance(holds, str):
        p.text(holds, 0, 1, 11, 14, alpha=0.7, max_w=INNER)
        return p.spr
    x = p.text("Hold", 0, (HOLD_H - 10 * LN) / 2, 10, 10 * LN, wght=600, track=0.12, caps=True, alpha=0.6) + 10
    for digit, label, progress in holds:
        if x >= INNER - 16:
            break
        p.frame(x, 0, 16, 4, 1, 0.55)
        q = max(0.0, min(1.0, float(progress or 0.0)))
        if q > 0.04:
            h = 16 * q
            p.rect(x + 1, 16 - h, 14, max(0.5, h - (1 if q < 1 else 1)), WHITE, 1.0, radius=3 if q >= 0.99 else 0.0)
        ink = (0, 0, 0) if q > 0.55 else WHITE
        p.text(digit, x + 8, (16 - 10 * LN) / 2, 10, 10 * LN, wght=700, rgb=ink, align="center", shadow=False)
        x += 16 + 6
        x += p.text(label, x, (HOLD_H - 11 * LN) / 2, 11, 11 * LN, alpha=0.9, max_w=max(10, INNER - x)) + 10
    return p.spr


def value_row_sprite(label: str, value: str, k: float):
    """r3.1.1: the caps label left and the 16/18 px 600 tabular value right, baseline-aligned."""
    p = Painter(INNER, L_VALUE_H, k)
    base = _baseline(0, L_VALUE_H, 16)
    p.caps(label, 0, _top_for_baseline(base, 11), max_w=INNER - 70)
    p.text(value, INNER, 0, 16, L_VALUE_H, wght=600, align="right", tabular=True)
    return p.spr


def summary_sprite(c: NavContent, k: float):
    """r3.1.1: ``**{scene}** · {n} lights · {on} on`` (12/15, one line, ellipsis); red when a light is
    unavailable or Home Assistant is not connected."""
    p = Painter(INNER, L_SUMMARY_H, k)
    w = p.text(c.summary_bold, 0, 0, 12, L_SUMMARY_H, wght=600, rgb=c.summary_rgb, max_w=INNER)
    if c.summary_rest and w < INNER - 20:
        space = p.width("x x", 12) - p.width("xx", 12)
        p.text("· " + c.summary_rest, w + space, 0, 12, L_SUMMARY_H, rgb=c.summary_rgb, alpha=c.summary_rest_a,
               max_w=INNER - w - space, tabular=True)
    return p.spr


def area_sprite(c: NavContent, k: float):
    """r3.1.1 Lights card: one row per light (a 6-unit dot in the light's colour, the name 12 px, the
    value 11 px tabular right-aligned), gap 4, only when the area is mixed or a light is unavailable."""
    rows = c.lights_rows
    p = Painter(INNER, max(1.0, area_block_height(len(rows))), k)
    y = 0.0
    for row in rows:
        y += LIGHT_ROW_GAP
        p.rect(0, y + (LIGHT_ROW_H - 6) / 2, 6, 6, row.dot_rgb, row.dot_a, radius=3)
        vw = p.text(row.value, INNER, y + (LIGHT_ROW_H - 11 * LN) / 2, 11, 11 * LN, rgb=row.value_rgb,
                    alpha=row.value_a, align="right", tabular=True)
        p.text(row.name, 14, y + (LIGHT_ROW_H - 12 * LN) / 2, 12, 12 * LN, max_w=max(10, INNER - 14 - vw - 8))
        y += LIGHT_ROW_H
    return p.spr


def line_sprite(w_u, k, alpha=0.18):
    p = Painter(w_u, 1, k)
    p.hline(0, 0, w_u, alpha)
    return p.spr


# --------------------------------------------------------------------------- the scene
class _Slot:
    """One visual that shows a sprite: its surface, the key of what it shows, optional props."""
    __slots__ = ("v", "surface", "key", "op", "x", "y", "margin")

    def __init__(self, v):
        self.v, self.surface, self.key, self.op, self.x, self.y, self.margin = v, None, None, None, None, None, 0


class _Item:
    """A list row or a cover that moves: its own ``Tree`` (released when it leaves), a container
    with the opacity / Y / scale props and the sprite visual."""
    __slots__ = ("key", "tree", "box", "v", "surface", "skey", "y", "op", "scale", "offset", "gone", "base_x",
                 "base_y", "art_v", "art_op", "art_surface", "art_key", "fresh_art")


class NavigatorScene:
    """The Navigator's visual tree and its motion (see the module docstring).

    ``dev``: a NativeDevice / FakeDevice; ``tree``: the skeleton's ``Tree``; ``geometry``: a
    ``NavGeometry``. ``build(root)`` makes the skeleton, hidden (card opacity 0, X at -24 u);
    ``apply(batch, content, art=, direction=)`` swaps or updates the content; ``show(batch, on)``
    slides the card in or out; ``set_frost(batch, frost)`` crossfades a fresh backdrop in. Each
    content kind lives in its own ``Tree`` and each moving row / cover in another, released when
    they go, so a long session never accumulates COM objects."""

    def __init__(self, dev, tree, geometry: NavGeometry, *, reduced_motion=False):
        from ..tree import Tree
        self._Tree = Tree
        self.dev, self.tree, self.g = dev, tree, geometry
        self.k = geometry.k
        self.reduced = bool(reduced_motion)
        self.content = None
        self.visible = False
        self.art = {}
        self.frost = None
        self.frost_gen = 0
        self.items = {}
        self.ktree = None
        self.list_box = None
        self.kind_top = []            # the kind's visuals directly under ``body``
        self.kind_slots = []          # every kind slot (their surfaces are released at a swap)
        self.stats = {"sprites": 0, "swaps": 0, "updates": 0, "glass_builds": 0, "released_trees": 0}
        self._glass_cache = {}

    # ------------------------------------------------------------------ surfaces
    def _surface(self, spr, name):
        w, h = spr.size
        s = self.dev.create_surface(w, h, False, name)
        self.dev.upload(s, w, h, spr.bgra(), name)
        self.stats["sprites"] += 1
        return s

    def _release(self, s):
        if s is not None:
            try:
                self.dev.release(s)
            except Exception:
                pass

    def _content(self, batch, v, s):
        if batch is not None:
            batch.call(self.dev.fn("Visual.SetContent", v.ptr), v.ptr, s)
        else:
            self.tree.content(v, s)

    def _set(self, batch, slot: _Slot, key, make, name):
        """Show ``make()``'s sprite on ``slot`` unless it already shows ``key``."""
        if slot.key == key and slot.surface is not None:
            return False
        spr = make()
        s = self._surface(spr, name)
        self._content(batch, slot.v, s)
        old, slot.surface, slot.key = slot.surface, s, key
        self._release(old)
        return True

    def _slot(self, tree, parent, name, x_u=0.0, y_u=0.0, *, opacity=None):
        v = tree.visual(name, opacity=opacity is not None)
        slot = _Slot(v)
        tree.offset(v, x_u * self.k, y_u * self.k)
        if opacity is not None:
            slot.op = tree.opacity(v, opacity)
        tree.add(parent, v)
        return slot

    # ------------------------------------------------------------------ build
    def build(self, root):
        """The static skeleton under ``root`` (hidden)."""
        t, k = self.tree, self.k
        self.root = root
        self.card = t.container("nav.card", opacity=True)
        t.add(root, self.card)
        self.card_op = t.opacity(self.card, 0.0)
        self.card_x = t.offset_x(self.card, float(self.g.px(LEFT - (0 if self.reduced else SLIDE_U))))
        self.card_y = t.offset_y(self.card, 0.0)
        self.shadow = _Slot(t.visual("nav.shadow"))
        t.add(self.card, self.shadow.v)
        self.glass = []
        for i in range(2):
            g = _Slot(t.visual(f"nav.glass{i}", opacity=True))
            t.add(self.card, g.v)
            g.op = t.opacity(g.v, 1.0 if i == 0 else 0.0)
            self.glass.append(g)
        self.glass_front = 0
        self.path = self._slot(t, self.card, "nav.path", PAD, PAD)
        self.body = t.container("nav.content", opacity=True)
        t.add(self.card, self.body)
        t.offset(self.body, self.g.px(PAD), self.g.px(content_top()))
        self.body_op = t.opacity(self.body, 1.0)
        self.body_x = t.offset_x(self.body, float(self.g.px(PAD)))
        self.keys = t.visual("nav.keys")
        t.add(self.card, self.keys)
        self.keys_line = self._slot(t, self.keys, "nav.keys.line", 0, 0)
        self.keys_labels = self._slot(t, self.keys, "nav.keys.labels", 0, 13)
        col = (INNER - 10) / 2.0
        self.key_boxes = []
        for i in range(4):
            x, y = (i % 2) * (col + 10), 13 + (i // 2) * 24
            normal = self._slot(t, self.keys, f"nav.key{i}", x, y)
            filled = self._slot(t, self.keys, f"nav.key{i}.pressed", x, y, opacity=0.0)
            self.key_boxes.append((normal, filled))
        self.hold = self._slot(t, self.card, "nav.hold", PAD, 0, opacity=0.0)
        self._set(None, self.hold, ("hold", ()), lambda: hold_sprite(k), "hold")
        self._set(None, self.keys_line, "line", lambda: line_sprite(INNER, k), "keys.line")

    # ------------------------------------------------------------------ glass
    def _glass(self, batch, kind, hold, crossfade):
        w, h = self.g.card_w(), self.g.card_h(kind, hold)
        x, y = self.g.card_xy(kind, hold)
        key = (w, h, self.frost_gen)
        spr = self._glass_cache.get(key)
        if spr is None:
            spr = glass_sprite(w, h, self.k, self.frost, (x, y))
            self._glass_cache = {kk: vv for kk, vv in self._glass_cache.items() if kk[2] == self.frost_gen}
            self._glass_cache[key] = spr
            self.stats["glass_builds"] += 1
        if crossfade and batch is not None and self.visible and not self.reduced:
            back = 1 - self.glass_front
            gb, gf = self.glass[back], self.glass[self.glass_front]
            self._set(batch, gb, key, lambda: spr, "glass")
            kids = list(self.card.children)                          # the new glass just above the old
            ia, ib = kids.index(gf.v), kids.index(gb.v)
            if ib < ia:
                kids[ia], kids[ib] = gb.v, gf.v
                self.tree.reorder(self.card, kids)
            batch.to(gb.op, 1.0, FROST_MS, "EASE", v_from=0.0, force=True)
            batch.to(gf.op, 0.0, 0.0, delay_ms=FROST_MS)
            self.glass_front = back
        else:
            gf = self.glass[self.glass_front]
            self._set(batch, gf, key, lambda: spr, "glass")
            if batch is not None:
                batch.jump(gf.op, 1.0)
                batch.jump(self.glass[1 - self.glass_front].op, 0.0)
        if self.shadow.key != (w, h):
            sh, (dx, dy), sc = shadow_sprite(w, h, self.k)
            self._set(batch, self.shadow, (w, h), lambda: sh, "shadow")
            self.tree.matrix(self.shadow.v, sc, sc, dx, dy)

    def set_frost(self, batch, frost):
        """A fresh backdrop (``build_frost``): the glass is rebuilt and crossfaded in."""
        self.frost = frost
        self.frost_gen += 1
        if self.content is not None:
            self._glass(batch, self.content.geometry(), self.content.hold_hint, crossfade=True)

    # ------------------------------------------------------------------ show / hide
    def show(self, batch, on: bool):
        on = bool(on)
        if on == self.visible:
            return False
        self.visible = on
        rest_x, off_x = float(self.g.px(LEFT)), float(self.g.px(LEFT - SLIDE_U))
        if self.reduced:
            batch.jump(self.card_x, rest_x)
            batch.to(self.card_op, 1.0 if on else 0.0, REDUCED_FADE_MS, "OUT")
        else:
            batch.to(self.card_op, 1.0 if on else 0.0, SHOW_OP_MS, "OUT")
            batch.to(self.card_x, rest_x if on else off_x, SHOW_X_MS, "OUT")
        return True

    def _bar_to(self, batch, prop, value):
        """A bar fill's scale or the temperature marker's X: 120 ms LINEAR; reduced motion jumps
        (r4 section 7: nothing translates or scales, DD-DES-005)."""
        if self.reduced:
            batch.jump(prop, value)
        else:
            batch.to(prop, value, BAR_MS, "LINEAR")

    def settle_end(self):
        """The tick at which the last show / hide motion ends (the host hides after it)."""
        ends = [getattr(p.func, "end_tick", None) for p in (self.card_op, self.card_x)]
        ends = [e for e in ends if e is not None]
        return max(ends) if ends else None

    # ------------------------------------------------------------------ content
    def apply(self, batch, content: NavContent, *, art=None, direction=0):
        """Show ``content`` (in ``batch``): a new mode is a content swap (section 4 "Screen change":
        the content slides 20 u in ``direction`` and fades in, when visible), the same mode animates
        in place."""
        if art:
            for key, image in art.items():
                self.art.pop(key, None)
                self.art[key] = image
            self._prune_art(content)
        prev = self.content
        self.content = content
        k = self.k
        self._set(batch, self.path, ("path", content.path), lambda: path_sprite(content.path, k), "path")
        holds = tuple(getattr(content, "holds", ()) or ())
        self._set(batch, self.hold, ("hold", holds), lambda: hold_sprite(k, holds), "hold")
        if prev is None or prev.mode != content.mode or prev.layout_key() != content.layout_key():
            self.stats["swaps"] += 1
            self._swap(batch, prev, content, direction)
        else:
            self.stats["updates"] += 1
            getattr(self, "_update_" + ("rows" if content.kind == "scenes" else content.kind))(batch, prev, content)
        self._keys(batch, content)

    def _prune_art(self, content):
        """At most ART_KEEP images, keeping every one the content shows (oldest others go first)."""
        if len(self.art) <= ART_KEEP:
            return
        used = {content.art_key} | {cv.art_key for cv in content.covers}
        for key in list(self.art):
            if len(self.art) <= ART_KEEP:
                break
            if key not in used:
                del self.art[key]

    def _swap(self, batch, prev, c, direction):
        t = self.tree
        geo = c.geometry()
        if prev is None or prev.geometry() != geo or prev.hold_hint != c.hold_hint:
            self._glass(batch, geo, c.hold_hint, crossfade=False)
            _x, y = self.g.card_xy(geo, c.hold_hint)
            batch.jump(self.card_y, float(y))
            t.offset(self.keys, self.g.px(PAD), self.g.px(keys_top(geo)))
            t.offset(self.hold.v, self.g.px(PAD), self.g.px(keys_top(geo) + KEYS_H + GAP - HOLD_OVERLAP))
        batch.jump(self.hold.op, 1.0 if c.hold_hint else 0.0)
        self._clear_kind()
        self.ktree = self._Tree(self.dev, self.tree.opacity_path)
        getattr(self, "_build_" + ("rows" if c.kind == "scenes" else c.kind))(batch, c)
        if direction and not self.reduced and self.visible:
            batch.to(self.body_op, 1.0, SWAP_OP_MS, "OUT", v_from=0.0, force=True)
            batch.to(self.body_x, float(self.g.px(PAD)), SWAP_X_MS, SWAP_CURVE,
                     v_from=float(self.g.px(PAD) + direction * self.g.px(SWAP_U)), force=True)
        elif direction and self.visible:
            batch.to(self.body_op, 1.0, REDUCED_SWAP_MS, "OUT", v_from=0.0, force=True)   # r4 7: fade only
            batch.jump(self.body_x, float(self.g.px(PAD)))
        else:
            batch.jump(self.body_op, 1.0)
            batch.jump(self.body_x, float(self.g.px(PAD)))

    def _clear_kind(self):
        for v in self.kind_top:
            if v.parent is not None:
                self.tree.remove(v.parent, v)
        for slot in self.kind_slots:
            self._release(slot.surface)
            slot.surface = None
        for it in list(self.items.values()):
            self._drop_item(it, detach=False)
        self.items = {}
        if self.ktree is not None:
            self.ktree.release_all()
            self.stats["released_trees"] += 1
        self.ktree = None
        self.list_box = None
        self.kind_top, self.kind_slots = [], []

    def _kslot(self, name, x_u, y_u, *, opacity=None, parent=None):
        slot = self._slot(self.ktree, parent if parent is not None else self.body, name, x_u, y_u, opacity=opacity)
        if parent is None:
            self.kind_top.append(slot.v)
        self.kind_slots.append(slot)
        return slot

    def _kbox(self, name, x_u, y_u, *, opacity=None, clip=None):
        t = self.ktree
        v = t.container(name, opacity=True) if opacity is not None else t.visual(name)
        t.offset(v, x_u * self.k, y_u * self.k)
        t.add(self.body, v)
        if clip is not None:
            t.clip(v, tuple(c * self.k for c in clip))
        slot = _Slot(v)
        if opacity is not None:
            slot.op = t.opacity(v, opacity)
        self.kind_top.append(v)
        return slot

    # ---- bars
    def _bar(self, box, name, y_u, track_a, fill_rgb, frac, *, fill_key):
        k, t = self.k, self.ktree
        track = self._kslot(name + ".track", 0, y_u, parent=box.v)
        self._set(None, track, ("track", track_a), lambda: bar_sprite(INNER, WHITE, track_a, k), name + ".track")
        fill = self._kslot(name + ".fill", 0, y_u, parent=box.v)
        self._set(None, fill, fill_key, lambda: bar_sprite(INNER, fill_rgb, 1.0, k, right_round=False), name + ".fill")
        st = t.scale_transform(fill.v, 0.0, 0.0, name + ".sx")
        fill.x = t.scale_x(st, INNER * k, max(0.0, min(1.0, frac)), name + ".scale")
        return fill

    def _cover(self, batch, slot, c, size_u, radius_u, shadow=None):
        art = self.art.get(c.art_key) if c.art_key else None
        key = ("cover", size_u, c.art_key if art is not None else "", c.accent)
        if slot.key == key:
            return
        spr, margin = cover_sprite(size_u, radius_u, self.k, art, c.accent, shadow=shadow)
        self._set(batch, slot, key, lambda: spr, "cover")
        if margin != slot.margin:
            slot.margin = margin
            self.ktree.offset(slot.v, -margin, -margin)

    # ---- now (Home / Music)
    def _now_text_key(self, c):
        return ("t", c.title, c.artist, c.status, c.status_rgb, c.status_a)

    def _build_now(self, batch, c):
        k = self.k
        self.now_cover = self._kslot("nav.now.cover", 0, 0)
        self._cover(batch, self.now_cover, c, 64, 8, shadow=(8, 20, 0.35))
        self.now_text = self._kslot("nav.now.text", 64 + 12, (64 - 54) / 2)
        self._set(batch, self.now_text, self._now_text_key(c), lambda: now_text_sprite(c, k), "now.text")
        self.vol = self._kbox("nav.now.vol", 0, 64 + 12, opacity=1.0 if c.volume_active else 0.6)
        self.vol_label = self._kslot("nav.now.vol.label", 0, 0, parent=self.vol.v)
        self._set(batch, self.vol_label, ("v", c.volume), lambda: label_row_sprite("Volume", f"{c.volume}%", k), "vol")
        self.vol_fill = self._bar(self.vol, "nav.now.vol", CAPS + 6, TRACK_A, WHITE, c.volume / 100.0, fill_key="white")

    def _update_now(self, batch, p, c):
        k = self.k
        self._cover(batch, self.now_cover, c, 64, 8, shadow=(8, 20, 0.35))
        self._set(batch, self.now_text, self._now_text_key(c), lambda: now_text_sprite(c, k), "now.text")
        self._set(batch, self.vol_label, ("v", c.volume), lambda: label_row_sprite("Volume", f"{c.volume}%", k), "vol")
        self._bar_to(batch, self.vol_fill.x, c.volume / 100.0)
        batch.to(self.vol.op, 1.0 if c.volume_active else 0.6, DIM_MS, "EASE")

    # ---- lights
    def _build_lights(self, batch, c):
        """r3.1.1 compact Lights card: Brightness row, Temperature row (label + 16/18 value, 4-unit bar
        5 below), the summary line and, when mixed / unavailable, the per-light rows (gap 10 between)."""
        k = self.k
        y = 0.0
        self.l_bri = self._kbox("nav.lights.bri", 0, y, opacity=c.bri_a)
        self.l_bri_label = self._kslot("nav.lights.bri.label", 0, 0, parent=self.l_bri.v)
        self._set(batch, self.l_bri_label, self._bri_key(c), lambda: value_row_sprite(c.bri_caption, c.bri_text, k),
                  "bri.label")
        self.l_bri_fill = self._bar(self.l_bri, "nav.lights.bri", L_BAR_Y, TRACK_A_BRI, c.kelvin_rgb, c.bri_frac,
                                    fill_key=("k", c.kelvin_rgb))
        y += L_ROW_H + L_GAP
        self.l_temp = self._kbox("nav.lights.temp", 0, y, opacity=c.temp_a)
        self.l_temp_label = self._kslot("nav.lights.temp.label", 0, 0, parent=self.l_temp.v)
        self._set(batch, self.l_temp_label, ("t", c.temp_text),
                  lambda: value_row_sprite("Temperature", c.temp_text, k), "temp.label")
        grad = self._kslot("nav.lights.temp.grad", 0, L_BAR_Y, parent=self.l_temp.v)
        self._set(batch, grad, "grad", lambda: gradient_bar_sprite(k), "temp.grad")
        mk, ring = marker_sprite(k)
        self.l_marker = self._kslot("nav.lights.temp.marker", 0, 0, parent=self.l_temp.v)
        self._set(batch, self.l_marker, "marker", lambda: mk, "temp.marker")
        self.l_marker_base = -ring - 2 * k
        self.ktree.offset(self.l_marker.v, 0, (L_BAR_Y - 4) * k - ring)
        self.l_marker.x = self.ktree.offset_x(self.l_marker.v, self.l_marker_base + c.temp_frac * INNER * k)
        y += L_ROW_H + L_GAP
        self.l_summary = self._kslot("nav.lights.summary", 0, y)
        self._set(batch, self.l_summary, self._summary_key(c), lambda: summary_sprite(c, k), "lights.summary")
        y += L_SUMMARY_H
        self.l_area = None
        if c.lights_rows:
            self.l_area = self._kslot("nav.lights.area", 0, y)
            self._set(batch, self.l_area, self._area_key(c), lambda: area_sprite(c, k), "lights.area")

    @staticmethod
    def _bri_key(c):
        return ("b", c.bri_caption, c.bri_text)

    @staticmethod
    def _summary_key(c):
        return ("s", c.summary_bold, c.summary_rest, c.summary_rgb, c.summary_rest_a)

    @staticmethod
    def _area_key(c):
        return ("a", c.lights_rows)

    def _update_lights(self, batch, p, c):
        k = self.k
        self._set(batch, self.l_bri_label, self._bri_key(c), lambda: value_row_sprite(c.bri_caption, c.bri_text, k),
                  "bri.label")
        self._set(batch, self.l_bri_fill, ("k", c.kelvin_rgb),
                  lambda: bar_sprite(INNER, c.kelvin_rgb, 1.0, k, right_round=False), "bri.fill")
        self._bar_to(batch, self.l_bri_fill.x, c.bri_frac)
        self._set(batch, self.l_temp_label, ("t", c.temp_text),
                  lambda: value_row_sprite("Temperature", c.temp_text, k), "temp.label")
        self._bar_to(batch, self.l_marker.x, self.l_marker_base + c.temp_frac * INNER * k)
        batch.to(self.l_bri.op, c.bri_a, DIM_MS, "EASE")
        batch.to(self.l_temp.op, c.temp_a, DIM_MS, "EASE")
        self._set(batch, self.l_summary, self._summary_key(c), lambda: summary_sprite(c, k), "lights.summary")
        if getattr(self, "l_area", None) is not None and c.lights_rows:
            self._set(batch, self.l_area, self._area_key(c), lambda: area_sprite(c, k), "lights.area")

    # ---- covers (Recently Added)
    def _covers_text_key(self, c):
        return ("t", c.title, c.artist, c.status, c.status_rgb, c.status_a)

    def _build_covers(self, batch, c):
        k = self.k
        self.list_box = self._kbox("nav.covers", 0, 0, clip=(0, 0, INNER, COVERS_H))
        self.cv_text = self._kslot("nav.covers.text", 0, COVERS_H + 10)
        self._set(batch, self.cv_text, self._covers_text_key(c), lambda: covers_text_sprite(c, k), "covers.text")
        self._list_items(batch, c.covers, cover=True, fresh=True)

    def _update_covers(self, batch, p, c):
        k = self.k
        self._set(batch, self.cv_text, self._covers_text_key(c), lambda: covers_text_sprite(c, k), "covers.text")
        self._list_items(batch, c.covers, cover=True, fresh=False)

    # ---- rows (Tracks) and scenes
    def _build_rows(self, batch, c):
        k = self.k
        self.list_box = self._kbox("nav.rows", 0, 0, clip=(0, 0, INNER, LIST_H))
        self.plate = self._kslot("nav.rows.plate", 0, 0, parent=self.list_box.v)
        self._set(batch, self.plate, "plate", lambda: plate_sprite(k), "plate")
        self.plate.y = self.ktree.offset_y(self.plate.v, (76 + c.plate * ROW_H) * k)
        self.rw_status = self._kslot("nav.rows.status", 0, LIST_H + 10)
        self._set(batch, self.rw_status, ("s", c.status, c.status_rgb, c.status_a),
                  lambda: status_sprite(c.status, c.status_rgb, c.status_a, k), "rows.status")
        self._list_items(batch, c.rows, cover=False, fresh=True)

    def _update_rows(self, batch, p, c):
        k = self.k
        self._set(batch, self.rw_status, ("s", c.status, c.status_rgb, c.status_a),
                  lambda: status_sprite(c.status, c.status_rgb, c.status_a, k), "rows.status")
        if self.reduced or not self.visible:
            batch.jump(self.plate.y, (76 + c.plate * ROW_H) * k)
        else:
            batch.to(self.plate.y, (76 + c.plate * ROW_H) * k, PLATE_MS, "OUT")
        self._list_items(batch, c.rows, cover=False, fresh=False)

    # ---- seek
    def _build_seek(self, batch, c):
        k = self.k
        self.sk_cover = self._kslot("nav.seek.cover", 0, 0)
        self._cover(batch, self.sk_cover, c, 44, 6, shadow=None)
        self.sk_title = self._kslot("nav.seek.title", 44 + 12, 0)
        self._set(batch, self.sk_title, ("t", c.title), lambda: seek_head_sprite(c, k), "seek.title")
        self.sk_big = self._kslot("nav.seek.big", 0, 44 + 10)
        self._set(batch, self.sk_big, ("b", c.big, c.unit), lambda: seek_big_sprite(c, k), "seek.big")
        holder = self._kbox("nav.seek.bar", 0, 44 + 10 + 40 + 10)
        self.sk_fill = self._bar(holder, "nav.seek", 0, TRACK_A, (0xFF, 0xBE, 0x69), c.seek_frac, fill_key="warm")

    def _update_seek(self, batch, p, c):
        k = self.k
        self._cover(batch, self.sk_cover, c, 44, 6, shadow=None)
        self._set(batch, self.sk_title, ("t", c.title), lambda: seek_head_sprite(c, k), "seek.title")
        self._set(batch, self.sk_big, ("b", c.big, c.unit), lambda: seek_big_sprite(c, k), "seek.big")
        self._bar_to(batch, self.sk_fill.x, c.seek_frac)

    # ---- list items (rows and covers) that move
    def _item_pose(self, offset, cover):
        a = min(3, abs(offset))
        sg = (offset > 0) - (offset < 0)
        if cover:
            return sg * COVER_OFFS[a] * self.k, COVER_OPS[a], COVER_SCALES[a]
        op = 0.0 if a > 2 else 1.0 if a == 0 else 0.8 - a * 0.15
        return offset * ROW_H * self.k, op, 1.0

    def _list_items(self, batch, entries, *, cover, fresh):
        seen = set()
        for e in entries:
            seen.add(e.key)
            it = self.items.get(e.key)
            y, op, sc = self._item_pose(e.offset, cover)
            if it is not None and it.gone:
                self._drop_item(it)
                it = None
            if it is None:
                it = self._new_item(e, cover)
                it.fresh_art = bool(cover and e.art_key and e.art_key in self.art)
                if fresh or not self.visible:
                    self._pose_now(it, y, op, sc)
                else:                              # enters from one step further out, faded
                    sg = (e.offset > 0) - (e.offset < 0) or 1
                    y0, _o, sc0 = self._item_pose(e.offset + sg, cover)
                    self._pose_now(it, y0, 0.0, sc0)
                self.items[e.key] = it
            self._item_content(batch, it, e, cover)
            it.fresh_art = False
            it.offset = e.offset
            self._pose_to(batch, it, y, op, sc)
        for key, it in list(self.items.items()):
            if key in seen or it.gone:
                continue
            sg = (it.offset > 0) - (it.offset < 0) or 1          # leaves one step further out, fading
            it.offset += sg
            y, _o, sc = self._item_pose(it.offset, cover)
            it.gone = True
            self._pose_to(batch, it, y, 0.0, sc)
        if cover:                                                # z = 10 - a, changed at the detent
            order = sorted(self.items.values(), key=lambda it: (-9 if it.gone else -min(3, abs(it.offset)), it.key))
            self.tree.reorder(self.list_box.v, [it.box for it in order])
        gone = [it for it in self.items.values() if it.gone]
        for it in gone[:-4]:                                     # at most 4 leaving items are kept
            self._drop_item(it)

    def _new_item(self, e, cover):
        k = self.k
        t = self._Tree(self.dev, self.tree.opacity_path)
        it = _Item()
        it.key, it.tree, it.surface, it.skey, it.gone, it.offset = e.key, t, None, None, False, e.offset
        it.box = t.container(f"nav.item.{e.key}", opacity=True)
        it.v = t.visual(f"nav.item.{e.key}.sprite")
        t.add(it.box, it.v)
        it.op = t.opacity(it.box, 0.0)
        it.art_v = it.art_op = it.art_surface = it.art_key = None
        it.fresh_art = False
        if cover:                              # the real cover fades in over the accent tile (ART_FADE_MS)
            it.art_v = t.visual(f"nav.item.{e.key}.art", opacity=True)
            t.add(it.box, it.art_v)
            it.art_op = t.opacity(it.art_v, 0.0)
        if cover:
            s = int(round(COVER_U * k))
            it.base_x, it.base_y = (INNER * k - s) / 2.0, (COVERS_H * k - s) / 2.0
            st = t.scale_transform(it.box, it.base_x + s / 2.0, it.base_y + s / 2.0, f"nav.item.{e.key}.s")
            it.scale = t.scale(st, s, 1.0, name=f"nav.item.{e.key}.scale")
            it.y = t.offset_y(it.box, 0.0)
        else:
            it.base_x, it.base_y = 0.0, 76 * k
            it.scale = None
            it.y = t.offset_y(it.box, it.base_y)
        self.tree.add(self.list_box.v, it.box)
        return it

    def _item_content(self, batch, it, e, cover):
        k = self.k
        if cover:
            skey = ("tile", e.accent)
            if it.skey != skey:                 # the accent tile (with the cover's shadow) under the art
                spr, margin = cover_sprite(COVER_U, 8, k, None, e.accent, shadow=(10, 24, 0.40))
                s = self._surface(spr, "cover.tile")
                self._content(batch, it.v, s)
                it.tree.offset(it.v, it.base_x - margin, it.base_y - margin)
                self._release(it.surface)
                it.surface, it.skey = s, skey
            art = self.art.get(e.art_key) if e.art_key else None
            if art is not None and it.art_key != e.art_key:
                spr, margin = cover_sprite(COVER_U, 8, k, art, e.accent, shadow=None)
                s = self._surface(spr, "cover.art")
                self._content(batch, it.art_v, s)
                it.tree.offset(it.art_v, it.base_x - margin, it.base_y - margin)
                self._release(it.art_surface)
                fresh = it.art_key is None
                it.art_surface, it.art_key = s, e.art_key
                if batch is None or not self.visible or self.reduced or not fresh or it.fresh_art:
                    batch.jump(it.art_op, 1.0) if batch is not None else it.art_op.set_now(1.0)
                else:
                    batch.to(it.art_op, 1.0, ART_FADE_MS, "EASE", v_from=0.0, force=True)
            elif art is None and it.art_key is not None and it.art_key != e.art_key:
                it.art_key = None
                if batch is not None:
                    batch.jump(it.art_op, 0.0)
        else:
            skey = ("row", e.number, e.title, e.title_rgb, e.tag, e.tag_rgb, e.tag_a)
            if it.skey != skey:
                s = self._surface(row_sprite(e, k), "row")
                self._content(batch, it.v, s)
                self._release(it.surface)
                it.surface, it.skey = s, skey

    def _pose_now(self, it, y, op, sc):
        it.y.set_now(it.base_y + y if it.scale is None else y)
        it.op.set_now(op)
        if it.scale is not None:
            it.scale.set_now(sc)

    def _pose_to(self, batch, it, y, op, sc):
        yv = it.base_y + y if it.scale is None else y
        if self.reduced or not self.visible:
            batch.jump(it.y, yv)
            if it.scale is not None:
                batch.jump(it.scale, sc)
            if self.visible:
                batch.to(it.op, op, LIST_OP_MS, "EASE")
            else:
                batch.jump(it.op, op)
            return
        batch.to(it.y, yv, LIST_MS, "OUT")
        if it.scale is not None:
            batch.to(it.scale, sc, LIST_MS, "OUT")
        batch.to(it.op, op, LIST_OP_MS, "EASE")

    def _drop_item(self, it, detach=True):
        if detach and it.box.parent is not None:
            self.tree.remove(it.box.parent, it.box)
        self._release(it.surface)
        self._release(it.art_surface)
        it.surface = it.art_surface = None
        it.tree.release_all()
        self.stats["released_trees"] += 1
        self.items.pop(it.key, None)

    # ---- keys
    def _keys(self, batch, c):
        k = self.k
        self._set(batch, self.keys_labels, ("labels", tuple((key.label, key.enabled) for key in c.keys)),
                  lambda: keys_label_sprite(c.keys, k), "keys.labels")
        for i, key in enumerate(c.keys[:4]):
            normal, filled = self.key_boxes[i]
            self._set(batch, normal, ("n", key.digit, key.enabled),
                      lambda: key_box_sprite(key.digit, False, key.enabled, k), "key")
            self._set(batch, filled, ("p", key.digit, key.enabled),
                      lambda: key_box_sprite(key.digit, True, key.enabled, k), "key.pressed")
            if not self.visible or self.reduced:
                batch.jump(filled.op, 1.0 if key.pressed else 0.0)
            else:
                batch.to(filled.op, 1.0 if key.pressed else 0.0, KEY_MS, "EASE")

    def release(self):
        """Every surface this scene made and the kind / item trees (the engine releases the
        skeleton's tree itself)."""
        self._clear_kind()
        for slot in [self.shadow, self.path, self.keys_line, self.keys_labels, self.hold] + list(self.glass):
            self._release(slot.surface)
            slot.surface = None
        for n, f in self.key_boxes:
            self._release(n.surface)
            self._release(f.surface)
            n.surface = f.surface = None
