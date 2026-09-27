"""PIL sprites of the Music explorer and Up next, the art states, and the PIL reference renderer
(DESKTOP_STAGE K4 §4.8, §7.1-§7.5, §8.1-§8.4, §12, §13.5-§13.6; BS r2.2 markup).

No stage import, no Tk, no I/O beyond the bundled Archivo font. Everything here runs on the art
workers (``NanoD-art-*``) or, for the few static sprites, once per open; §4.7.3 applies: only
GIL-releasing PIL calls on large images (decode, ``reduce``, ``resize``, ``GaussianBlur``,
``transform``, masked ``paste``, ``tobytes``), text drawn one glyph at a time onto small masks,
and **no** ``alpha_composite`` (it is used by nothing here; the reference renderer composes with
``ImageChops`` on its own canvases and is a test tool).

Sprites with alpha are built **premultiplied** (``Sprite``: an RGB ``pm`` image and an ``L``
alpha): a masked paste of straight colour into a premultiplied canvas is an exact premultiplied
"over" (RF1 C2), and ``Sprite.bgra()`` hands DirectComposition its premultiplied BGRA bytes
(§0.7) without a second premultiplication. Opaque art (covers, sleeves, frost, ambient) is RGB.

Glyphs are the prototype's SVG paths (BS ``I``), rasterised here: a small path parser (M L H V C
A Z, absolute and relative), flattening, round-cap / round-join strokes, dashes and fills, drawn
at 4x and box-reduced.

The reference renderer (§4.8) draws what DirectComposition would compose from a recording fake
device (``stage.fake.FakeDevice`` semantics, with the full surface bytes kept): every visual's
offset, transform (matrix, scale transforms, transform groups), opacity (static or the recorded
animation evaluated at t), group opacity mode (LAYER composes the subtree first; MULTIPLY
multiplies down), content, LINEAR sampling and SOFT edges. It gives the golden images of H4.
"""
from __future__ import annotations

import math
import os
import re
import threading
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from . import scene_music as SM
from .carousel_render import (ASCENT, COLOUR_FONTS, FALLBACK_FILES, LINE_NORMAL, FontSpec, TextEngine,
                              baseline_in)

SUPERSAMPLE = 4
WHITE = (255, 255, 255)
GEN_PALETTE = ((0x2B3A55, 0x131A28, 0xF3F2F2), (0x5A2E24, 0x26130F, 0xF6EBE4), (0x2F4A3A, 0x15231B, 0xECF4EE),
               (0x4B3B63, 0x1F182C, 0xF1EEF6), (0x6B5A2A, 0x2C2410, 0xF7F1DF), (0x2A4F57, 0x112326, 0xE9F4F5),
               (0x5C2A3F, 0x28111B, 0xF6E9EF), (0x3D3D3D, 0x171717, 0xF3F2F2))     # BS:536 g0, g1, ink


def rgb_of(value):
    if isinstance(value, tuple):
        return tuple(int(v) & 255 for v in value[:3])
    v = int(value) & 0xFFFFFF
    return (v >> 16) & 255, (v >> 8) & 255, v & 255


def _alpha_lut(alpha: float):
    a = max(0.0, min(1.0, float(alpha)))
    return [int(v * a + 0.5) for v in range(256)]


# =========================================================================== premultiplied canvas
class Sprite:
    """A premultiplied sprite kept as two planes: ``pm`` (RGB, colour × alpha) and ``a`` (L).

    Pillow blends a masked paste linearly on RGB and L images (``src·m + dst·(1 − m)``), so a
    masked paste of a straight colour into ``pm`` and of 255 into ``a`` is the exact premultiplied
    "over" (RF1 C2), in GIL-releasing pastes. (Pillow composites RGBA / RGBa destinations with
    straight-alpha rules, so a single 4-band image cannot hold premultiplied colour.) ``bgra()``
    packs ``pm`` as BGRX (a GIL-releasing ``tobytes``) and writes the alpha into every fourth
    byte (one strided C copy): no merge, no split, no chops."""

    __slots__ = ("pm", "a")

    def __init__(self, pm, a):
        self.pm, self.a = pm, a

    @classmethod
    def new(cls, w, h):
        w, h = max(1, int(w)), max(1, int(h))
        return cls(Image.new("RGB", (w, h)), Image.new("L", (w, h)))

    @classmethod
    def from_rgba(cls, img):
        """A straight RGBA image (e.g. black shadows, where straight == premultiplied colour 0)."""
        img = img.convert("RGBA")
        spr = cls.new(*img.size)
        spr.pm.paste(img.convert("RGB"), (0, 0), img.getchannel("A"))
        spr.a.paste(img.getchannel("A"), (0, 0))
        return spr

    @property
    def size(self):
        return self.pm.size

    def fill(self, box, rgb, alpha=1.0):
        fill(self, box, rgb, alpha)

    def over_mask(self, mask, rgb, alpha=1.0, xy=(0, 0)):
        over_mask(self, mask, rgb, alpha, xy)

    def bgra(self) -> bytes:
        """Premultiplied BGRA bytes (DXGI_ALPHA_MODE_PREMULTIPLIED, §0.7)."""
        buf = bytearray(self.pm.tobytes("raw", "BGRX"))
        buf[3::4] = self.a.tobytes()
        return bytes(buf)

    def straight(self):
        """A straight RGBA image (debugging, previews, tests)."""
        buf = bytearray(self.pm.tobytes("raw", "RGBX"))
        buf[3::4] = self.a.tobytes()
        return Image.frombytes("RGBa", self.size, bytes(buf)).convert("RGBA")


def _paint(target, rgb, box, mask):
    """Straight colour through ``mask`` onto a premultiplied ``Sprite`` or an opaque RGB image."""
    if isinstance(target, Sprite):
        target.pm.paste(rgb_of(rgb), box, mask)
        target.a.paste(255, box, mask)
    else:
        target.paste(rgb_of(rgb), box, mask)


def fill(target, box, rgb, alpha=1.0):
    """A straight colour rectangle "over" (``target``: a ``Sprite`` or an RGB image)."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    if x1 <= x0 or y1 <= y0:
        return
    level = int(round(max(0.0, min(1.0, alpha)) * 255))
    _paint(target, rgb, (x0, y0, x1, y1), Image.new("L", (x1 - x0, y1 - y0), level))


def over_mask(target, mask, rgb, alpha=1.0, xy=(0, 0)):
    """Straight colour ``rgb`` through coverage ``mask`` × ``alpha``, "over"."""
    if alpha < 1.0:
        mask = mask.point(_alpha_lut(alpha))
    x, y = int(xy[0]), int(xy[1])
    _paint(target, rgb, (x, y, x + mask.size[0], y + mask.size[1]), mask)


def over_colour(target, rgba_straight, alpha=1.0, xy=(0, 0)):
    """A straight RGBA layer (colour glyphs, rare) "over"."""
    r, g, b, a = rgba_straight.split()
    if alpha < 1.0:
        a = a.point(_alpha_lut(alpha))
    x, y = int(xy[0]), int(xy[1])
    box = (x, y, x + a.size[0], y + a.size[1])
    colour = Image.merge("RGB", (r, g, b))
    if isinstance(target, Sprite):
        target.pm.paste(colour, box, a)
        target.a.paste(255, box, a)
    else:
        target.paste(colour, box, a)


def opaque_bgra(img) -> bytes:
    """BGRA bytes with alpha 255 for an opaque surface (DXGI_ALPHA_MODE_IGNORE)."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img.convert("RGBA").tobytes("raw", "BGRA")


# =========================================================================== SVG glyphs
_TOKEN = re.compile(r"[MmLlHhVvCcSsAaZz]|[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
_ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "A": 7, "Z": 0}


def _arc_points(x1, y1, rx, ry, phi_deg, large, sweep, x2, y2, steps_per_rad=6.0):
    """SVG elliptical arc (endpoint parameterisation, SVG 1.1 F.6.5) as points after (x1, y1)."""
    if rx == 0 or ry == 0:
        return [(x2, y2)]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(phi_deg % 360.0)
    cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p, y1p = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1.0:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if bool(large) == bool(sweep):
        co = -co
    cxp, cyp = co * rx * y1p / ry, -co * ry * x1p / rx
    cx = cp * cxp - sp * cyp + (x1 + x2) / 2.0
    cy = sp * cxp + cp * cyp + (y1 + y2) / 2.0

    def ang(ux, uy, vx, vy):
        d = math.hypot(ux, uy) * math.hypot(vx, vy)
        a = math.acos(max(-1.0, min(1.0, (ux * vx + uy * vy) / d))) if d else 0.0
        return -a if ux * vy - uy * vx < 0 else a

    t1 = ang(1.0, 0.0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dt = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    n = max(4, int(abs(dt) * steps_per_rad * max(1.0, max(rx, ry) / 3.0)))
    pts = []
    for i in range(1, n + 1):
        t = t1 + dt * i / n
        ex, ey = rx * math.cos(t), ry * math.sin(t)
        pts.append((cp * ex - sp * ey + cx, sp * ex + cp * ey + cy))
    pts[-1] = (x2, y2)
    return pts


def _cubic_points(p0, p1, p2, p3, n=16):
    out = []
    for i in range(1, n + 1):
        t = i / n
        mt = 1 - t
        a, b, c, d = mt * mt * mt, 3 * mt * mt * t, 3 * mt * t * t, t * t * t
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


def parse_path(d: str):
    """SVG path data -> [(points, closed)] in the path's own units (M L H V C S A Z, both cases)."""
    tokens = _TOKEN.findall(d)
    subpaths = []
    pts = []
    closed = False
    x = y = 0.0
    sx = sy = 0.0
    last_c2 = None
    cmd = None
    i = 0

    def flush():
        nonlocal pts, closed
        if len(pts) > 1:
            subpaths.append((pts, closed))
        pts, closed = [], False

    while i < len(tokens):
        tok = tokens[i]
        if tok.isalpha():
            cmd = tok
            i += 1
            if cmd in "Zz":
                closed = True
                if pts:
                    pts.append((sx, sy))
                x, y = sx, sy
                flush()
                last_c2 = None
                continue
        up = cmd.upper()
        n = _ARGS[up]
        args = [float(t) for t in tokens[i:i + n]]
        i += n
        rel = cmd.islower()
        if up == "M":
            flush()
            x, y = (x + args[0], y + args[1]) if rel else (args[0], args[1])
            sx, sy = x, y
            pts = [(x, y)]
            cmd = "l" if rel else "L"               # implicit lineto after a moveto
            last_c2 = None
        elif up == "L":
            x, y = (x + args[0], y + args[1]) if rel else (args[0], args[1])
            pts.append((x, y))
            last_c2 = None
        elif up == "H":
            x = x + args[0] if rel else args[0]
            pts.append((x, y))
            last_c2 = None
        elif up == "V":
            y = y + args[0] if rel else args[0]
            pts.append((x, y))
            last_c2 = None
        elif up in "CS":
            if up == "C":
                c1 = (x + args[0], y + args[1]) if rel else (args[0], args[1])
                c2 = (x + args[2], y + args[3]) if rel else (args[2], args[3])
                e = (x + args[4], y + args[5]) if rel else (args[4], args[5])
            else:
                c1 = (2 * x - last_c2[0], 2 * y - last_c2[1]) if last_c2 else (x, y)
                c2 = (x + args[0], y + args[1]) if rel else (args[0], args[1])
                e = (x + args[2], y + args[3]) if rel else (args[2], args[3])
            pts.extend(_cubic_points((x, y), c1, c2, e))
            x, y = e
            last_c2 = c2
        elif up == "A":
            ex, ey = (x + args[5], y + args[6]) if rel else (args[5], args[6])
            pts.extend(_arc_points(x, y, args[0], args[1], args[2], args[3], args[4], ex, ey))
            x, y = ex, ey
            last_c2 = None
    flush()
    return subpaths


_GLYPH_CACHE = {}
_GLYPH_LOCK = threading.Lock()


def _point_at(pts, cum, s):
    """The point at arc length ``s`` along the polyline (``cum`` = cumulative lengths)."""
    import bisect
    i = max(1, min(len(pts) - 1, bisect.bisect_left(cum, s)))
    a, b = cum[i - 1], cum[i]
    f = 0.0 if b <= a else (s - a) / (b - a)
    (x0, y0), (x1, y1) = pts[i - 1], pts[i]
    return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f


def _dash_segments(pts, on, off):
    """Split a polyline into dash pieces (``on`` drawn, ``off`` skipped), in path units: each
    dash [n·period, n·period + on) is cut out by arc length (SVG ``stroke-dasharray``)."""
    import bisect
    cum = [0.0]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot(x1 - x0, y1 - y0))
    total = cum[-1]
    period = on + off
    out = []
    if total <= 0 or period <= 0:
        return out
    start = 0.0
    while start < total:
        end = min(total, start + on)
        piece = [_point_at(pts, cum, start)]
        i = bisect.bisect_right(cum, start)
        while i < len(cum) and cum[i] < end:
            piece.append(pts[i])
            i += 1
        piece.append(_point_at(pts, cum, end))
        out.append(piece)
        start += period
    return out


def glyph_mask(name_or_path: str, px: float, *, stroke=2.0, fill=False, dash=None, caps="round",
               viewbox=24.0):
    """An ``L`` coverage mask of a 24-unit SVG glyph drawn at ``px`` square: stroked (width in
    glyph units; round caps and joins as BS ``I``), dashed (``dash`` = (on, off), butt caps, R22
    BS:255) or filled. Cached per argument set."""
    d = SM.GLYPHS.get(name_or_path, name_or_path)
    key = (d, round(float(px), 3), stroke, fill, dash, caps, viewbox)
    with _GLYPH_LOCK:
        hit = _GLYPH_CACHE.get(key)
    if hit is not None:
        return hit
    size = max(1, int(round(px)))
    S = SUPERSAMPLE
    big = Image.new("L", (size * S, size * S), 0)
    draw = ImageDraw.Draw(big)
    scale = size * S / viewbox
    subs = parse_path(d)
    if fill:
        for pts, _closed in subs:
            draw.polygon([(x * scale, y * scale) for x, y in pts], fill=255)
    else:
        w = max(1.0, stroke * scale)
        r = w / 2.0
        pieces = []
        for pts, closed in subs:
            if dash:
                pieces.extend((p, False) for p in _dash_segments(pts, dash[0], dash[1]))
            else:
                pieces.append((pts, closed))
        for pts, _closed in pieces:
            sp = [(x * scale, y * scale) for x, y in pts]
            for a, b in zip(sp, sp[1:]):
                draw.line([a, b], fill=255, width=max(1, int(round(w))))
            if caps == "round" and not dash:
                for (x, y) in sp:
                    draw.ellipse((x - r, y - r, x + r, y + r), fill=255)
    mask = big.reduce(S)
    with _GLYPH_LOCK:
        if len(_GLYPH_CACHE) > 256:
            _GLYPH_CACHE.clear()
        _GLYPH_CACHE[key] = mask
    return mask


# =========================================================================== text
class MusicText(TextEngine):
    """``TextEngine`` with the exact Archivo weight on the variable axis (500, 600, 700, 800);
    the fallback families stay per nearest weight class. Per thread (faces are not shared)."""

    def chain(self, wght):
        key = int(wght)
        chain = self._chains.get(key)
        if chain is None:
            family = 600 if 500 <= key < 650 else 700 if key >= 650 else 400
            chain = [FontSpec(self.archivo, 0, key, False, "Archivo")] if os.path.exists(self.archivo) else []
            for name in FALLBACK_FILES[family]:
                path = self.fonts_dir / name
                if path.exists():
                    chain.append(FontSpec(str(path), 0, None, name in COLOUR_FONTS, name))
            self._chains[key] = chain
        return chain


_TLS = threading.local()


def text_engine() -> MusicText:
    eng = getattr(_TLS, "engine", None)
    if eng is None:
        eng = _TLS.engine = MusicText()
    return eng


def draw_text(target, text: str, x: float, top: float, px: float, lh: float, *, wght=400, track=0.0,
              rgb=WHITE, alpha=1.0, max_w=None, align="left", eng=None):
    """One line: fitted with an ellipsis at ``max_w``; ``x`` is the left edge (``align`` left),
    the centre (``center``) or the right edge (``right``). Returns the drawn width."""
    eng = eng or text_engine()
    text = " ".join(str(text or "").split())
    if max_w is not None:
        text = eng.fit(text, px, wght, track, max_w)
    if not text:
        return 0.0
    width = eng.width(text, px, wght, track)
    left = x - width / 2.0 if align == "center" else x - width if align == "right" else x
    # A mask the size of the line only (the glyphs are drawn at rounded pens, anchor 'ls').
    pad = int(math.ceil(px * 0.6)) + 2
    x0 = int(math.floor(left)) - pad
    y0 = int(math.floor(top)) - pad
    mw = int(math.ceil(width)) + 2 * pad + 2
    mh = int(math.ceil(max(lh, LINE_NORMAL * px))) + 2 * pad + 2
    mask = Image.new("L", (mw, mh), 0)
    colour = Image.new("RGBA", (mw, mh), (0, 0, 0, 0))
    eng.draw(text, left - x0, baseline_in(top, lh, px) - y0, px, wght, track, mask, colour)
    over_mask(target, mask, rgb, alpha, (x0, y0))
    if colour.getbbox():
        over_colour(target, colour, alpha, (x0, y0))
    return width


def text_width(text, px, wght=400, track=0.0, eng=None) -> float:
    eng = eng or text_engine()
    return eng.width(" ".join(str(text or "").split()), px, wght, track)


def wrap(text, px, wght, width, *, track=0.0, eng=None):
    eng = eng or text_engine()
    words = str(text or "").split()
    lines, cur = [], ""
    for w in words:
        trial = w if not cur else cur + " " + w
        if cur and eng.width(trial, px, wght, track) > width:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def wrap_balanced(text, px, wght, width, *, track=0.0, eng=None):
    """CSS ``text-wrap: balance``: the narrowest width that keeps the greedy line count."""
    eng = eng or text_engine()
    lines = wrap(text, px, wght, width, track=track, eng=eng)
    if len(lines) <= 1:
        return lines
    lo = max(eng.width(w, px, wght, track) for w in str(text).split())
    hi = float(width)
    for _ in range(18):
        mid = (lo + hi) / 2.0
        if len(wrap(text, px, wght, mid, track=track, eng=eng)) <= len(lines):
            hi = mid
        else:
            lo = mid
    return wrap(text, px, wght, hi + 0.01, track=track, eng=eng)


def wrap_pretty(text, px, wght, width, *, track=0.0, eng=None):
    """CSS ``text-wrap: pretty`` as K4 §7.4 reads it: no one-word last line when it can be avoided."""
    eng = eng or text_engine()
    lines = wrap(text, px, wght, width, track=track, eng=eng)
    if len(lines) >= 2 and len(lines[-1].split()) == 1:
        prev = lines[-2].split()
        if len(prev) >= 2:
            moved = prev[-1] + " " + lines[-1]
            if eng.width(moved, px, wght, track) <= width:
                lines[-2:] = [" ".join(prev[:-1]), moved]
    return lines


def clamp_lines(lines, n, px, wght, width, *, track=0.0, eng=None):
    """``-webkit-line-clamp``: at most ``n`` lines, the last ellipsised when text was cut."""
    eng = eng or text_engine()
    if len(lines) <= n:
        return lines
    head = lines[:n]
    head[-1] = eng.fit(head[-1] + " " + " ".join(lines[n:]), px, wght, track, width)
    return head


def line_normal(px) -> float:
    return LINE_NORMAL * px


# =========================================================================== gradients and art states
def linear_gradient_160(size, g0, g1):
    """``linear-gradient(160deg, g0 0%, g1 100%)`` on a square (BS ``artFor`` 'none')."""
    size = max(1, int(size))
    ramp = Image.linear_gradient("L")                     # 256 x 256, value = row
    ang = math.radians(160.0)
    dx, dy = math.sin(ang), -math.cos(ang)
    L = size * (abs(dx) + abs(dy))
    # input row = 255 * (0.5 + ((x - s/2) dx + (y - s/2) dy) / L)
    k = 255.0 / L
    c = 255.0 * 0.5 - k * (size / 2.0) * (dx + dy)
    t = ramp.transform((size, size), Image.Transform.AFFINE, (0, 0, 128, k * dx, k * dy, c),
                       resample=Image.Resampling.BILINEAR)
    return _ramp_colour(t, [(0.0, rgb_of(g0)), (1.0, rgb_of(g1))])


def _ramp_colour(t_img, stops):
    """Colour an ``L`` ramp by piecewise-linear stops through a palette: ``putpalette`` makes it
    a ``P`` image and ``convert("RGB")`` expands it (GIL-releasing; no merge)."""
    pal = bytearray()
    for v in range(256):
        tt = v / 255.0
        col = stops[-1][1]
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if tt <= t1:
                f = 0.0 if t1 == t0 else max(0.0, min(1.0, (tt - t0) / (t1 - t0)))
                col = [c0[j] + (c1[j] - c0[j]) * f for j in range(3)]
                break
        pal.extend(int(round(c)) for c in col)
    t_img.putpalette(bytes(pal))
    return t_img.convert("RGB")


def _shade(c, k):
    return tuple(int(math.floor(v * k + 0.5)) for v in c)


def radial_ground(size, colour):
    """``radial-gradient(120% 120% at 50% 38%, shade(c,.95) 0%, shade(c,.5) 52%, shade(c,.2) 100%)``
    (BS ``extGrad``; K4 §13.6), with c = the cover's dominant colour."""
    size = max(1, int(size))
    c = rgb_of(colour)
    rad = Image.radial_gradient("L")      # value = 255 × distance from (128, 128) ÷ 128·√2 (measured)
    R = 1.2 * size
    s = 128.0 * math.sqrt(2.0) / R
    cx, cy = 0.5 * size, 0.38 * size
    t = rad.transform((size, size), Image.Transform.AFFINE, (s, 0, 128 - s * cx, 0, s, 128 - s * cy),
                      resample=Image.Resampling.BILINEAR)
    return _ramp_colour(t, [(0.0, _shade(c, .95)), (0.52, _shade(c, .5)), (1.0, _shade(c, .2))])


def fit_square(img, px):
    """Centre-crop to a square and LANCZOS to ``px`` (``art.full``; §13.4 step 3)."""
    px = max(1, int(px))
    img = img.convert("RGB") if img.mode != "RGB" else img
    w, h = img.size
    if w != h:
        e = min(w, h)
        img = img.crop(((w - e) // 2, (h - e) // 2, (w - e) // 2 + e, (h - e) // 2 + e))
    if img.size[0] >= 2 * px:
        img = img.reduce(max(1, img.size[0] // (2 * px)))
    return img if img.size == (px, px) else img.resize((px, px), Image.Resampling.LANCZOS)


def _frame_mask(size, width, level):
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    w, h = size
    for i in range(int(width)):
        d.rectangle((i, i, w - 1 - i, h - 1 - i), outline=level)
    return m


def art_extended(src, px, colour, frac, unit_px):
    """``art.extended`` (K4 §13.6): the radial ground of the cover's colour; the cover sharp at
    ``frac`` of the element (1.5 × native), centred; its fixed shadow ``0 18px 40px /.4`` and a
    1 px inset at 14 % white. No blur of the cover."""
    px = max(1, int(px))
    ground = radial_ground(px, colour)
    drawn = max(1, min(px, int(round(frac * px))))
    off = (px - drawn) // 2
    shadow = Image.new("L", (px, px), 0)
    oy = int(round(18 * unit_px))
    shadow.paste(int(round(0.4 * 255)), (off, off + oy, off + drawn, off + oy + drawn))
    sigma = 20.0 * unit_px                                  # blur 40 -> sigma 20 units
    if sigma > 0.3:
        shadow = shadow.filter(ImageFilter.GaussianBlur(sigma))
    ground.paste((0, 0, 0), (0, 0, px, px), shadow)
    ground.paste(fit_square(src, drawn), (off, off))
    inset = max(1, int(round(unit_px)))
    ground.paste(WHITE, (off, off, off + drawn, off + drawn), _frame_mask((drawn, drawn), inset, int(round(0.14 * 255))))
    return ground


def _gen_colours(title, artist):
    g0, g1, ink = GEN_PALETTE[SM.gen_index(title, artist)]
    return g0, g1, rgb_of(ink)


def art_generated(title, artist, px, *, variant="card", unit_px=None):
    """``art.generated`` (K4 §13.6; BS:155-164 card, :218-224 Up next cover): the 160° GEN
    gradient; the title in Archivo 800 (card 34/37 at left/right 26, top 24; cover 38/41 at 28 /
    26), −0.02 em, balanced, at most 4 lines; the artist 16/20 (cover 17/22) 500 at 0.80; the card
    adds a 2 px rule at 0.50 and a 28 px two-note glyph at 0.70 at bottom 26; the cover a rule at
    bottom 28. All in the palette's ink, drawn straight onto the opaque image (masked pastes)."""
    px = max(1, int(px))
    units = SM.CARD_UNITS if variant == "card" else SM.U_COVER
    u = (px / units) if unit_px is None else unit_px
    g0, g1, ink = _gen_colours(title, artist)
    img = linear_gradient_160(px, g0, g1)
    eng = text_engine()
    if variant == "card":
        side, top, tpx, tlh, apx, alh = 26, 24, 34, 37, 16, 20
    else:
        side, top, tpx, tlh, apx, alh = 28, 26, 38, 41, 17, 22
    width = (units - 2 * side) * u
    lines = wrap_balanced(title or "", tpx * u, 800, width, track=-0.02, eng=eng)
    lines = clamp_lines(lines, 4, tpx * u, 800, width, track=-0.02, eng=eng)
    y = top * u
    for ln in lines:
        draw_text(img, ln, side * u, y, tpx * u, tlh * u, wght=800, track=-0.02, rgb=ink, eng=eng)
        y += tlh * u
    if lines:
        y += 8 * u
    if artist:
        draw_text(img, artist, side * u, y, apx * u, alh * u, wght=500, rgb=ink, alpha=0.8, max_w=width, eng=eng)
    if variant == "card":
        g = 28 * u
        gx, gy = (units - side) * u - g, (units - 26) * u - g
        rule_right = gx - 12 * u
        fill(img, (side * u, gy + g - 2 * u, rule_right, gy + g), ink, 0.5)
        over_mask(img, glyph_mask("note", g, stroke=2.0), ink, 0.7, (int(round(gx)), int(round(gy))))
    else:
        fill(img, (side * u, (units - 28) * u - 2 * u, (units - side) * u, (units - 28) * u), ink, 0.5)
    return img


def art_loading(title, artist, px, bg, ink, *, units=SM.CARD_UNITS, unit_px=None):
    """``art.loading`` (K4 §13.6; BS:165-170): a solid ``art_bg``; the title 17/21 600 and the
    artist 13/17 500 at 0.75 in ``art_ink``, at left/right 22 and bottom 20, gap 4."""
    px = max(1, int(px))
    u = (px / units) if unit_px is None else unit_px
    img = Image.new("RGB", (px, px), rgb_of(bg))
    if not title and not artist:
        return img
    width = (units - 44) * u
    bottom = (units - 20) * u
    y_artist = bottom - 17 * u if artist else bottom
    y_title = y_artist - (4 * u if artist else 0) - 21 * u
    draw_text(img, title, 22 * u, y_title, 17 * u, 21 * u, wght=600, rgb=rgb_of(ink), max_w=width)
    if artist:
        draw_text(img, artist, 22 * u, y_artist, 13 * u, 17 * u, wght=500, rgb=rgb_of(ink), alpha=0.75, max_w=width)
    return img


def art_mosaic(tiles, px):
    """``art.mosaic``: TL, TR, BL, BR of the first 4 distinct albums, each half the element."""
    px = max(2, int(px))
    img = Image.new("RGB", (px, px), (0x22, 0x22, 0x22))
    h = px // 2
    for j, t in enumerate(tiles[:4]):
        x0 = 0 if j % 2 == 0 else h
        y0 = 0 if j < 2 else h
        w = h if j % 2 == 0 else px - h
        hh = h if j < 2 else px - h
        img.paste(fit_square(t, max(w, hh)).crop((0, 0, w, hh)), (x0, y0))
    return img


def frame_sprite(px, width, alpha):
    """A shared inset line: ``inset 0 0 0 1px rgba(255,255,255,alpha)`` of a square (§7.3)."""
    px = max(1, int(px))
    spr = Sprite.new(px, px)
    spr.over_mask(_frame_mask((px, px), max(1, int(width)), 255), WHITE, alpha)
    return spr


def frame_sprite_rect(w, h, width, alpha, fill_alpha=0.0):
    w, h = max(1, int(w)), max(1, int(h))
    spr = Sprite.new(w, h)
    if fill_alpha > 0:
        spr.fill((0, 0, w, h), WHITE, fill_alpha)
    spr.over_mask(_frame_mask((w, h), max(1, int(width)), 255), WHITE, alpha)
    return spr


def thumb64(img):
    """The 64 px copy the ambient is built from (§12; RA §4.1)."""
    return fit_square(img, 64)


# =========================================================================== explorer sprites (k-scaled)
def key_box(spr: Sprite, x, y, size, digit, dpx, *, border_alpha=1.0, text_alpha=1.0, unit_px=1.0):
    """A key box (1 px border, the digit centred, 700)."""
    s = int(round(size))
    lw = max(1, int(round(unit_px)))
    spr.over_mask(_frame_mask((s, s), lw, 255), WHITE, border_alpha, (int(round(x)), int(round(y))))
    draw_text(spr, digit, x + size / 2.0, y + (size - line_normal(dpx)) / 2.0, dpx, line_normal(dpx), wght=700,
              alpha=text_alpha, align="center")


def tab_sprite(source: str, k: float):
    """One tab's line 1 (BS:130-141): key box 18 (digit 11/700), gap 8, 18 px glyph (stroke 2),
    gap 8, the label 17/600; white. Returns (Sprite, column width px, line height px)."""
    eng = text_engine()
    label = SM.TAB_LABEL[source]
    lw = text_width(label, 17 * k, 600, eng=eng)
    width = (18 + 8 + 18 + 8) * k + lw
    lh = max(18 * k, line_normal(17 * k))
    W, H = int(math.ceil(width)) + 1, int(math.ceil(lh))
    spr = Sprite.new(W, H)
    y_box = (lh - 18 * k) / 2.0
    key_box(spr, 0, y_box, 18 * k, SM.TAB_KEY[source], 11 * k, unit_px=k)
    spr.over_mask(glyph_mask(SM.TAB_GLYPH[source], 18 * k), WHITE, 1.0, (int(round(26 * k)), int(round(y_box))))
    draw_text(spr, label, 52 * k, 0, 17 * k, lh, wght=600, eng=eng)
    return spr, width, lh


def hints_sprite(hints, k: float):
    """The hint row (BS:196-203): 13 px at 0.80, 28 apart; key boxes 16 (border 0.60, digit
    10/700), gap 6. Returns (Sprite, width px); centred on the stage by the caller."""
    eng = text_engine()
    parts = []
    total = 0.0
    for key, label in hints:
        w = (16 + 6) * k + text_width(label, 13 * k, 400, eng=eng)
        parts.append((key, label, w))
        total += w
    total += 28 * k * (len(parts) - 1)
    H = int(math.ceil(16 * k))
    spr = Sprite.new(int(math.ceil(total)) + 1, H)
    x = 0.0
    for key, label, w in parts:
        key_box(spr, x, 0, 16 * k, key, 10 * k, border_alpha=0.6, text_alpha=0.8, unit_px=k)
        draw_text(spr, label, x + 22 * k, 0, 13 * k, 16 * k, alpha=0.8, eng=eng)
        x += w + 28 * k
    return spr, total


def label_sprite(title, sub, meta, k: float):
    """The explorer label (BS:178-182): 900 wide, centred; title 30/36 600 −0.01 em, one line,
    ellipsis; sub 17/22 at 0.90; meta 14/18 at 0.72; gap 6."""
    W, H = int(round(SM.LABEL_W * k)), int(round(SM.LABEL_H * k))
    spr = Sprite.new(W, H)
    cx = W / 2.0
    draw_text(spr, title, cx, 0, 30 * k, 36 * k, wght=600, track=-0.01, max_w=W, align="center")
    draw_text(spr, sub, cx, 42 * k, 17 * k, 22 * k, alpha=0.9, max_w=W, align="center")
    draw_text(spr, meta, cx, 70 * k, 14 * k, 18 * k, alpha=0.72, max_w=W, align="center")
    return spr


def dots_sprite(dots: SM.Dots, k: float):
    """The dot row (BS:190-195): 6 x 6 dots at pitch 14; 0.40, fading ends (S5-9)."""
    n = dots.count
    W = max(1, int(round((n * SM.DOT_PITCH - 8) * k)))
    H = max(1, int(round(SM.DOT_UNITS * k)))
    spr = Sprite.new(W, H)
    for j, op in enumerate(SM.dot_opacities(dots)):
        x0 = int(round(j * SM.DOT_PITCH * k))
        spr.fill((x0, 0, x0 + H, H), WHITE, op)
    return spr


def state_block_sprite(glyph, title, help_text, k: float):
    """The state block (BS:183-189; S5-33): 600 wide, centred, gap 12: a 56 px glyph (stroke
    1.6, 0.60), the title 28/34 600, the help 16/22 at 0.80 wrapped (``text-wrap: pretty``)."""
    eng = text_engine()
    W = int(round(SM.BLOCK_W * k))
    lines = wrap_pretty(help_text, 16 * k, 400, W, eng=eng)
    H = int(round((56 + 12 + 34 + 12 + 22 * max(1, len(lines))) * k))
    spr = Sprite.new(W, H)
    g = 56 * k
    spr.over_mask(glyph_mask(glyph, g, stroke=1.6), WHITE, 0.6, (int(round((W - g) / 2.0)), 0))
    draw_text(spr, title, W / 2.0, 68 * k, 28 * k, 34 * k, wght=600, align="center", max_w=W, eng=eng)
    y = 114 * k
    for ln in lines:
        draw_text(spr, ln, W / 2.0, y, 16 * k, 22 * k, alpha=0.8, align="center", eng=eng)
        y += 22 * k
    return spr


# =========================================================================== Up next sprites
def left_text_sprite(title, sub, k: float):
    """The column text under the big cover (BS:229-234): caption ``UP NEXT`` 13 px 600 0.12 em
    at 0.72; title 24/30 600, ellipsis at 380; sub 15 px at 0.86, ellipsis. The shuffle line is
    its own pair of sprites (``shuffle_sprite``). Returns (Sprite, height px)."""
    W = int(round(SM.U_COVER * k))
    cap_lh = line_normal(13 * k)
    sub_lh = line_normal(15 * k)
    H = int(math.ceil(cap_lh + 6 * k + 30 * k + 6 * k + sub_lh))
    spr = Sprite.new(W, H)
    draw_text(spr, SM.COPY["overlay.upnext.header"].upper(), 0, 0, 13 * k, cap_lh, wght=600, track=0.12,
              alpha=0.72, max_w=W)
    draw_text(spr, title, 0, cap_lh + 6 * k, 24 * k, 30 * k, wght=600, max_w=W)
    draw_text(spr, sub, 0, cap_lh + 42 * k, 15 * k, sub_lh, alpha=0.86, max_w=W)
    return spr, cap_lh + 6 * k + 30 * k + 6 * k + sub_lh


def shuffle_sprite(text, on: bool, k: float):
    """The shuffle line (BS:235-238): a 16 px glyph (stroke 2), gap 6, 13 px text; white when on,
    0.60 when off."""
    alpha = 1.0 if on else 0.6
    lh = max(16 * k, line_normal(13 * k))
    W = int(math.ceil(22 * k + text_width(text, 13 * k, 400))) + 1
    spr = Sprite.new(W, int(math.ceil(lh)))
    spr.over_mask(glyph_mask("shuffle", 16 * k), WHITE, alpha, (0, int(round((lh - 16 * k) / 2.0))))
    draw_text(spr, text, 22 * k, 0, 13 * k, lh, alpha=alpha)
    return spr


def row_geometry(lead: str, tag_w_px: float, k: float):
    """(text left, text right, tag right) in row px (BS:245-256): padding 0 20, gap 18; the
    right group is the tag, gap 12, the 20 px heart."""
    x = SM.U_ROW_PAD * k
    if lead in ("art", "placeholder"):
        x += (SM.U_LEAD_ART + SM.U_ROW_GAP) * k
    elif lead == "number":
        x += (SM.U_LEAD_NUM + SM.U_ROW_GAP) * k
    right_group = tag_w_px + (SM.U_RIGHT_GAP + SM.U_HEART) * k
    tag_right = (SM.U_ROW_W - SM.U_ROW_PAD - SM.U_HEART - SM.U_RIGHT_GAP) * k
    text_right = (SM.U_ROW_W - SM.U_ROW_PAD) * k - right_group - SM.U_ROW_GAP * k
    return x, text_right, tag_right


def row_sprite(k: float, *, lead="art", number="", title="", sub="", tag=None, placeholder_k=None):
    """A row's text sprite at scale 1 (the focus size), the whole 560 x 88 row: the number
    (20 px 500 at 0.72, tabular cells), title 22/26 600, sub 14/18 at 0.82 (both ellipsised),
    the tag 12 px 600 0.08 em uppercase (``#6ED996`` now, else 0.70). The cover lead and the
    hearts are their own visuals. A placeholder row draws its 56 px block at 10 % and the two
    bars (BS:249)."""
    eng = text_engine()
    W, H = int(round(SM.U_ROW_W * k)), int(round(SM.U_ROW_H * k))
    spr = Sprite.new(W, H)
    tag_text = ""
    tag_rgb, tag_alpha = WHITE, 0.7
    if tag is not None:
        tag_id, tag_rgb, tag_alpha = tag
        tag_text = SM.COPY[tag_id].upper()
    tag_w = text_width(tag_text, 12 * k, 600, 0.08, eng=eng) if tag_text else 0.0
    x, text_right, tag_right = row_geometry(lead, tag_w, k)
    if placeholder_k is not None:
        lx = SM.U_ROW_PAD * k
        spr.fill((lx, 16 * k, lx + 56 * k, 72 * k), WHITE, 0.10)
        cw = max(0.0, text_right - x)
        spr.fill((x, 22 * k, x + cw * SM.placeholder_bar_width(placeholder_k), 38 * k), WHITE, 0.14)
        spr.fill((x, 48 * k, x + cw * 0.34, 58 * k), WHITE, 0.10)
        return spr
    if lead == "number" and number:
        cell = max(eng.width(d, 20 * k, 500) for d in "0123456789")
        nx = SM.U_ROW_PAD * k
        for ch in number:
            draw_text(spr, ch, nx + cell / 2.0, 0, 20 * k, 88 * k, wght=500, alpha=0.72, align="center", eng=eng)
            nx += cell
    cw = max(1.0, text_right - x)
    draw_text(spr, title, x, 20 * k, 22 * k, 26 * k, wght=600, max_w=cw, eng=eng)
    draw_text(spr, sub, x, 50 * k, 14 * k, 18 * k, alpha=0.82, max_w=cw, eng=eng)
    if tag_text:
        draw_text(spr, tag_text, tag_right, 0, 12 * k, 88 * k, wght=600, track=0.08, rgb=tag_rgb, alpha=tag_alpha,
                  align="right", eng=eng)
    return spr


HEART_DASH = (2.2, 2.4)


def heart_sprites(k: float, filled_oversample=1.5):
    """The three [r2.2] heart forms (BS:255, R22): outline (white, stroke 1.8), dashed outline
    (dash 2.2 / gap 2.4 in the 24-unit glyph space) and filled ``#FF285A``; opacities are the
    visuals'. The filled form is drawn at ``filled_oversample`` × so the pop to 1.5 stays sharp."""
    px = SM.U_HEART * k
    out = Sprite.new(int(round(px)), int(round(px)))
    out.over_mask(glyph_mask("heart", px, stroke=1.8, caps="butt"), WHITE)
    dash = Sprite.new(int(round(px)), int(round(px)))
    dash.over_mask(glyph_mask("heart", px, stroke=1.8, dash=HEART_DASH, caps="butt"), WHITE)
    fpx = px * filled_oversample
    fill = Sprite.new(int(round(fpx)), int(round(fpx)))
    fill.over_mask(glyph_mask("heart", fpx, fill=True), SM.U_HEART_RGB)
    return out, dash, fill


def plate_sprite(k: float):
    """The focus plate's fill and inset (BS:241): 560 x 88, ``rgba(255,255,255,.14)`` with a 1 px
    inset at 0.28 (its shadow is a fixed 1/4-resolution layer under it)."""
    return frame_sprite_rect(SM.U_PLATE[2] * k, SM.U_PLATE[3] * k, max(1, int(round(k))), 0.28, fill_alpha=0.14)


# =========================================================================== the reference renderer (§4.8)
class ReferenceRenderer:
    """Draws a recording fake device's visual tree at a time ``t`` (ticks of ``freq``).

    ``device.objects`` follows ``stage.fake.FakeDevice``: visuals with ``children`` and
    ``props`` (``offset_x``, ``offset_y``, ``opacity``, ``opacity_mode``, ``transform``,
    ``content``, ``interp``, ``border``), scale transforms, transform groups, animations
    (``begin``, ``segs``, ``end``) and surfaces with ``pixels`` (the full BGRA bytes, which the
    scenes' recording device keeps). The visual's transform is applied in its own space, then its
    offset (the scenes never set both on one visual). Sampling is bilinear with transparent
    borders (LINEAR + SOFT); LAYER opacity composes the subtree before blending it."""

    def __init__(self, device, freq: int):
        self.dev = device
        self.freq = int(freq)
        self.visited = 0

    # ------------------------------------------------------------------ values
    def _anim(self, oid, t):
        a = self.dev.objects[oid]
        segs = a.get("segs") or []
        begin = a.get("begin")
        tau = 0.0 if begin is None else (t - begin) / self.freq
        end = a.get("end")
        if end is not None and tau >= end[0]:
            return float(end[1])
        if not segs:
            return float(end[1]) if end else 0.0
        seg = segs[0]
        for s in segs:
            if s[0] <= tau:
                seg = s
            else:
                break
        w = max(0.0, tau - seg[0])
        return seg[1] + w * (seg[2] + w * (seg[3] + w * seg[4]))

    def value(self, oid, prop, t, default):
        v = self.dev.objects[oid].get("props", {}).get(prop)
        if v is None:
            return default
        if isinstance(v, tuple) and v and v[0] == "anim":
            return self._anim(v[1], t)
        return v

    def _transform(self, v, t):
        tr = self.dev.objects[v].get("props", {}).get("transform")
        if tr is None:
            return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        if isinstance(tr, tuple) and tr[0] == "matrix":
            m11, m12, m21, m22, dx, dy = tr[1]
            return (m11, m12, m21, m22, dx, dy)
        return self._object_matrix(tr, t)

    def _object_matrix(self, oid, t):
        o = self.dev.objects[oid]
        if o["kind"] == "transform_group":
            m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
            for member in o["members"]:
                m = _mul(m, self._object_matrix(member, t))      # members apply in order
            return m
        if o["kind"] == "scale":
            sx = self.value(oid, "scale_x", t, 1.0)
            sy = self.value(oid, "scale_y", t, 1.0)
            cx = self.value(oid, "center_x", t, 0.0)
            cy = self.value(oid, "center_y", t, 0.0)
            return (sx, 0.0, 0.0, sy, cx - sx * cx, cy - sy * cy)
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    # ------------------------------------------------------------------ drawing
    def surface_sprite(self, sid):
        """(premultiplied RGB, alpha) of a surface from its kept BGRA bytes (released handles
        included: a visual keeps its own reference to its content)."""
        o = self.dev.objects.get(sid)
        if not o or o.get("kind") != "surface" or o.get("pixels") is None:
            return None
        cache = o.get("_sprite")
        if cache is not None:
            return cache
        w, h = o["size"]
        raw = Image.frombytes("RGBA", (w, h), o["pixels"], "raw", "BGRA")
        pm = raw.convert("RGB")
        a = Image.new("L", (w, h), 255) if o["opaque"] else raw.getchannel("A")
        o["_sprite"] = (pm, a)
        return pm, a

    def render(self, root, size, t, background=(0, 0, 0)):
        canvas = _Canvas(size, background)
        self._draw(root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), 1.0, canvas, t, 0)
        return canvas.pm

    def _draw(self, v, parent, mult, target, t, mode):
        o = self.dev.objects[v]
        if o.get("released"):
            return
        self.visited += 1
        props = o.get("props", {})
        if props.get("interp") == 0 or props.get("border") == 1:
            raise AssertionError(f"forbidden NEAREST / HARD mode on {o['name']}")
        op = float(self.value(v, "opacity", t, 1.0))
        own_mode = props.get("opacity_mode")
        mode = mode if own_mode is None or own_mode == 0xFFFFFFFF else own_mode
        ox = float(self.value(v, "offset_x", t, 0.0))
        oy = float(self.value(v, "offset_y", t, 0.0))
        m = _mul(_mul(parent, (1.0, 0.0, 0.0, 1.0, ox, oy)), self._transform(v, t))
        if op <= 0.0 or mult <= 0.0:
            return
        content = props.get("content")
        kids = o.get("children") or []
        if mode == 0 and op < 0.999 and (kids or content):
            layer = _Canvas(target.size, None)
            if content:
                self._blit(content, m, 1.0, layer)
            for c in kids:
                self._draw(c, m, 1.0, layer, t, mode)
            _over(target, layer.pm, layer.a, (0, 0), op * mult)
            return
        a = op * mult
        if content:
            self._blit(content, m, a, target)
        for c in kids:
            self._draw(c, m, a, target, t, mode)

    def _blit(self, sid, m, alpha, target):
        spr = self.surface_sprite(sid)
        if spr is None:
            return
        pm_src, a_src = spr
        w, h = pm_src.size
        corners = [_apply(m, x, y) for x, y in ((0, 0), (w, 0), (0, h), (w, h))]
        x0 = max(0, int(math.floor(min(c[0] for c in corners))) - 1)
        y0 = max(0, int(math.floor(min(c[1] for c in corners))) - 1)
        x1 = min(target.size[0], int(math.ceil(max(c[0] for c in corners))) + 1)
        y1 = min(target.size[1], int(math.ceil(max(c[1] for c in corners))) + 1)
        if x1 <= x0 or y1 <= y0:
            return
        inv = _invert(m)
        # output pixel (x, y) of the bbox -> input: the inverse applied to (x + x0, y + y0)
        a_, b_, c_, d_, e_, f_ = inv[0], inv[2], inv[4], inv[1], inv[3], inv[5]
        coeffs = (a_, b_, a_ * x0 + b_ * y0 + c_, d_, e_, d_ * x0 + e_ * y0 + f_)
        size = (x1 - x0, y1 - y0)
        pm = pm_src.transform(size, Image.Transform.AFFINE, coeffs, resample=Image.Resampling.BILINEAR)
        al = a_src.transform(size, Image.Transform.AFFINE, coeffs, resample=Image.Resampling.BILINEAR)
        _over(target, pm, al, (x0, y0), alpha)


class _Canvas:
    """The reference renderer's premultiplied canvas (colour and alpha kept apart)."""

    __slots__ = ("pm", "a")

    def __init__(self, size, background):
        self.pm = Image.new("RGB", size, rgb_of(background) if background is not None else (0, 0, 0))
        self.a = Image.new("L", size, 255 if background is not None else 0)

    @property
    def size(self):
        return self.pm.size


def _mul(p, q):
    """Matrix product p ∘ q for (m11, m12, m21, m22, dx, dy) row-vector matrices: q first."""
    a1, b1, c1, d1, e1, f1 = q
    a2, b2, c2, d2, e2, f2 = p
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2, c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def _apply(m, x, y):
    return (x * m[0] + y * m[2] + m[4], x * m[1] + y * m[3] + m[5])


def _invert(m):
    a, b, c, d, e, f = m
    det = a * d - b * c
    if abs(det) < 1e-12:
        return (0.0, 0.0, 0.0, 0.0, -1e9, -1e9)
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    return (ia, ib, ic, id_, -(e * ia + f * ic), -(e * ib + f * id_))


def _over(target, pm, a, xy, alpha):
    """Premultiplied over of (``pm``, ``a``) scaled by ``alpha`` (the reference renderer only: a
    test tool; ``ImageChops`` holds the GIL and never runs in the app)."""
    x, y = int(xy[0]), int(xy[1])
    w, h = pm.size
    if alpha < 0.999:
        lut = _alpha_lut(alpha)
        pm = pm.point(lut * 3)
        a = a.point(lut)
    box = (x, y, x + w, y + h)
    d_pm = target.pm.crop(box)
    d_a = target.a.crop(box)
    inv = ImageChops.invert(a)
    d_pm = ImageChops.add(ImageChops.multiply(d_pm, Image.merge("RGB", (inv, inv, inv))), pm)
    d_a = ImageChops.add(ImageChops.multiply(d_a, inv), a)
    target.pm.paste(d_pm, (x, y))
    target.a.paste(d_a, (x, y))
