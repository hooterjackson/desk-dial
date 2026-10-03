"""The r3 arc breadcrumbs (README r3 section 2.1, "Arc, pre-rendered"): one source for the knob and the mirror.

Each breadcrumb path is set on the arc ``M 26 120 A 94 94 0 0 1 214 120`` (centre 120,120, r 94, from 180
degrees clockwise over the top to 0 degrees) as SVG ``textPath`` does it: the glyph baselines on the circle,
each glyph rotated to the tangent at the middle of its advance, the whole run centred at the apex
(``startOffset 50 %``, ``text-anchor middle``). Type: Montserrat 500 (the variable font's wght 500, as the
knob's own fonts), 12 px, caps, letter-spacing 0.96 px (0.08 em) after every glyph. Ancestors are drawn in
#7C7C7C, each followed by `` › ``; the current level in #E6E6E6.

r4 layout rule (design_handoff_nano_d_r4 README 3.6; motion-lab.js fitCrumb): at most two named levels -- deeper
ancestors collapse to ``…`` (``… › TRACKS › UP NEXT``) -- and the run must take at most 190 px of arc (about +-58
degrees from 12 o'clock); a longer one shows ``‹ CURRENT`` instead (``display(token)``).

``render(token)`` gives two A8 alpha masks (ancestors, current), each cropped to its ink with its top-left
position on the 240 x 240 LCD: rendered 4x supersampled, glyphs rotated with bicubic filtering, then box-filtered
down, so the masks are the same whatever machine renders them (Pillow + the bundled font only).

``harness/make_crumbs.py`` writes these masks into the firmware (src/cc_crumbs.cpp: A8 images the
LCD recolours); ``lcd_preview`` composites the very same masks on the desktop mirror. No I/O at import.
"""
from __future__ import annotations

from functools import lru_cache
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONT_PATH = ROOT / 'assets' / 'fonts' / 'Montserrat.ttf'
FONT_WEIGHT = 500
SIZE = 12
TRACKING = 0.96
CENTRE = (120.0, 120.0)
RADIUS = 94.0
SEPARATOR = ' › '
SUPERSAMPLE = 4
ANCESTOR_INK = 0x7C7C7C
CURRENT_INK = 0xE6E6E6

# The presentation-6 `crumb` tokens (presentation.CRUMBS) and their paths (README 2.1; 1e, Arc).
PATHS = {
    'music': ('MUSIC',),
    'recent': ('MUSIC', 'RECENTLY ADDED'),
    'onScreenRecent': ('MUSIC', 'RECENT', 'ON SCREEN'),
    'onScreenPlaylists': ('MUSIC', 'PLAYLISTS', 'ON SCREEN'),
    'tracks': ('MUSIC', 'TRACKS'),
    'upnext': ('MUSIC', 'TRACKS', 'UP NEXT'),
    'windows': ('WINDOWS',),
    'lights': ('LIGHTS',),
    'scenes': ('LIGHTS', 'SCENES'),
    # Desk Dial r3.1 (appended): Recently Added's button 3 source toggle, the Favourite playlists list.
    'playlists': ('MUSIC', 'PLAYLISTS'),
}
TOKENS = tuple(PATHS)
MAX_ARC = 190.0          # r4 3.6: the pre-rendered crumb's arc length limit (px along the r 94 arc)
COLLAPSED = '\u2026'    # r4 3.6: ancestors above the parent collapse to an ellipsis level
BACK = '\u2039 '        # r4 3.6: a run over MAX_ARC shows only "‹ CURRENT"
# Screen depth of each path (README 4 "Depth": home 0; music, windows, lights 1; albums, tracks, scenes 2;
# explorer, upnext 3): the knob slides deeper screens in from the right.
DEPTH = {token: len(path) for token, path in PATHS.items()}


@lru_cache(maxsize=4)
def _font(size):
    from PIL import ImageFont
    face = ImageFont.truetype(str(FONT_PATH), size, layout_engine=ImageFont.Layout.BASIC)
    face.set_variation_by_axes([FONT_WEIGHT])
    return face


class Mask:
    """An A8 mask on the LCD: top-left (x, y), size (w, h), row-major alpha bytes."""
    __slots__ = ('x', 'y', 'w', 'h', 'data')

    def __init__(self, x, y, w, h, data):
        self.x, self.y, self.w, self.h, self.data = x, y, w, h, bytes(data)

    def __repr__(self):
        return f'Mask(x={self.x}, y={self.y}, w={self.w}, h={self.h})'


def _layout(text, face, scale):
    """(glyph, x offset of its advance start, advance) along the run, in supersampled px."""
    out, pen = [], 0.0
    for ch in text:
        advance = face.getlength(ch)
        out.append((ch, pen, advance))
        pen += advance + TRACKING * scale
    return out, pen


def _draw_run(canvas, glyphs, start, face, scale):
    """Each glyph drawn with the middle of its advance on its baseline at the canvas centre, rotated
    about that point to the tangent, and pasted with that point on the circle."""
    from PIL import Image, ImageDraw
    radius = RADIUS * scale
    cx, cy = CENTRE[0] * scale, CENTRE[1] * scale
    ascent, _descent = face.getmetrics()
    for ch, offset, advance in glyphs:
        if ch == ' ':
            continue
        distance = start + offset + advance / 2.0
        theta = math.pi - distance / radius            # standard angle (y up) of the glyph's middle
        px, py = cx + radius * math.cos(theta), cy - radius * math.sin(theta)
        half = int(math.ceil(max(ascent, advance))) + 2 * scale
        side = 2 * half
        glyph = Image.new('L', (side, side), 0)
        ImageDraw.Draw(glyph).text((half - advance / 2.0, half - ascent), ch, fill=255, font=face)
        rotation = math.degrees(distance / radius) - 90.0       # clockwise on screen
        rotated = glyph.rotate(-rotation, resample=Image.BICUBIC, expand=False)
        canvas.paste(255, (int(round(px)) - half, int(round(py)) - half), rotated)


def _mask_of(canvas, scale):
    from PIL import Image
    small = canvas.resize((canvas.width // scale, canvas.height // scale), Image.BOX)
    box = small.getbbox()
    if box is None:
        return None
    x0, y0, x1, y1 = box
    crop = small.crop(box)
    return Mask(x0, y0, x1 - x0, y1 - y0, crop.tobytes())


def arc_width(text):
    """The run's length along the arc in LCD px (advances plus the 0.96 px tracking after every glyph)."""
    face = _font(SIZE * SUPERSAMPLE)
    return _layout(text, face, SUPERSAMPLE)[1] / SUPERSAMPLE


@lru_cache(maxsize=16)
def display(token):
    """(ancestors prefix as drawn, current) of a token after the r4 3.6 rule (motion-lab.js fitCrumb): more than
    one ancestor collapses to ``… › PARENT › ``; a run over MAX_ARC becomes ``‹ `` + current (else current only)."""
    parts = PATHS[token]
    ancestors, current = parts[:-1], parts[-1]
    if len(ancestors) > 1:
        prefix = COLLAPSED + SEPARATOR + ancestors[-1] + SEPARATOR
    else:
        prefix = ''.join(part + SEPARATOR for part in ancestors)
    if prefix and arc_width(prefix + current) > MAX_ARC:
        prefix = BACK if arc_width(BACK + current) <= MAX_ARC else ''
    return prefix, current


@lru_cache(maxsize=16)
def render(token):
    """(ancestors Mask or None, current Mask) of a crumb token (r4 3.6: as ``display`` lays it out)."""
    from PIL import Image
    scale = SUPERSAMPLE
    face = _font(SIZE * scale)
    prefix, current = display(token)
    glyphs, width = _layout(prefix + current, face, scale)
    length = math.pi * RADIUS * scale
    start = length / 2.0 - width / 2.0
    split = len(prefix)
    size = 240 * scale
    masks = []
    for chunk in (glyphs[:split], glyphs[split:]):
        canvas = Image.new('L', (size, size), 0)
        _draw_run(canvas, chunk, start, face, scale)
        masks.append(_mask_of(canvas, scale))
    return masks[0], masks[1]


def composite(image, token, alpha=1.0):
    """Paint `token`'s breadcrumb onto a 240 x 240 RGB PIL image (the desktop mirror)."""
    from PIL import Image
    ancestors, current = render(token)
    for mask, ink in ((ancestors, ANCESTOR_INK), (current, CURRENT_INK)):
        if mask is None:
            continue
        m = Image.frombytes('L', (mask.w, mask.h), mask.data)
        if alpha < 1.0:
            m = m.point(lambda v: int(round(v * alpha)))
        fill = Image.new('RGB', (mask.w, mask.h), ((ink >> 16) & 255, (ink >> 8) & 255, ink & 255))
        image.paste(fill, (mask.x, mask.y), m)
    return image


@lru_cache(maxsize=16)
def layer_rgba(token):
    """`token`'s breadcrumb as a 240 x 240 RGBA layer (ink per part, the masks as alpha): the scaled mirror."""
    from PIL import Image
    layer = Image.new('RGBA', (240, 240), (0, 0, 0, 0))
    for mask, ink in zip(render(token), (ANCESTOR_INK, CURRENT_INK)):
        if mask is None:
            continue
        part = Image.new('RGBA', (mask.w, mask.h), ((ink >> 16) & 255, (ink >> 8) & 255, ink & 255, 255))
        part.putalpha(Image.frombytes('L', (mask.w, mask.h), mask.data))
        layer.alpha_composite(part, (mask.x, mask.y))
    return layer
