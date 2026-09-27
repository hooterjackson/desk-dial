"""The floating knob face (desktop v5, FLOATING_KNOB.md section 2): pure Pillow, no Tk.

``KnobFace(scale)`` composes, at physical pixels, what the overlay window shows:

1. a dark circular plate (#111111 at alpha 235, r154) over a soft drop shadow
   (black, alpha <= 90, CSS blur 10, offset 0,3) so the LEDs read on any wallpaper;
2. the 60 Knob Face ring segments (4 x 10 at r138, i * 6 deg from twelve
   o'clock), unlit #1f1f1f, lit in the existing colour model, with the Knob
   Face glow (box-shadow 0 0 (2 + 3l)px rgba(c, 0.7 * L)) clipped by the disc;
3. the r126 #0a0a0a disc with its 1 px #262626 inner edge;
4. the LCD (``lcd_preview.render_lcd(..., scale=k)`` at ``lcd_px``), centred.

Units: design px are Knob Face px. The ring's outer diameter (2 x 143 design px)
is ``ring_logical_px`` logical px, so ``scale_for(dpi)`` = physical px per
design px. Everything is anti-aliased at physical pixels: masks are drawn 4x
supersampled and LANCZOS-downscaled, once per scale (the sprite cache); a frame only
copies the cached base and alpha-composites cached sprites. Frames are straight
RGBA; ``premultiplied_bgra`` turns one into UpdateLayeredWindow bytes.

Centring: the LCD is pasted unresampled at whole pixels, so its centre is a pixel
corner when ``lcd_px`` is even and a pixel centre when it is odd (150 % and
175 % DPI). The plate, shadow, ring and disc are drawn about that same point,
``origin``; ``center`` is the integer pixel corner at or just above-left of it.

The ring colour model (Knob Face optical mapping of PreviewLights drives) lives
here too, moved from ui.py unchanged: ``optical_alpha``, ``led_source``,
``ring_display``, ``ring_palette`` (and ``strip_display``); ``ring_colors``
gives the 60 ``(r, g, b, level)`` a KnobFace draws. That is the look of a knob
without ``alive`` (cc5.3 and older, PreviewLights), unchanged in desktop v7.

Desktop v7 (``AliveFace``; ALIVE.md revision 2 section 10.3 item 3, DESKTOP_STAGE
section 11.3-11.4): a knob with ``alive`` draws the engine's tone-mapped ``e``
(floats 0..1 per channel) with the design's styling. Per segment, with ``mx =
max(e)``: the body is filled ``round(36 + 219 e)`` (unlit #242424); when ``mx >
0.01`` one of **six glow looks** is picked from the rendered level (``look_index``:
the nearest of ``GLL``, ties to the lower look), tinted ``round(e / mx * 255)``
and drawn at alpha ``0.95 * GLL[g]`` with sigma ``GLB[g] / 2 * S_glow``, where
``S_glow = ring outer diameter in physical px / 318`` (``glow_scale_for``: 1.1321
at 100 %, so the sigmas are 3.40 ... 10.19 px). The 360 look masks (60 pre-rotated
segments x 6 looks, alpha baked, clipped by the disc) are built once per scale and
only tinted and pasted per frame, never blurred. ``compose_into`` is the C2 compose
straight into a premultiplied canvas (a PIL 'RGBX' view of the layered window's DIB,
bands B, G, R, A): copy the cached plate and shadow, paste each glow colour through
its look mask, each body colour through its body mask, then the disc and LCD sprite
through its coverage; a masked paste of a straight colour into a premultiplied
canvas is an exact "over". No alpha_composite, no per-frame image. ``ring_key`` is
the frame key's ring part (AR-22): per segment the 8-bit fill, the look index and
the 8-bit tint. Geometry, plate, disc and LCD placement are KnobFace's.
"""
from __future__ import annotations

from collections import OrderedDict
import logging
import math
import time

from .presentation import (
    LED_AMBER, LED_GREEN, LED_RED, LED_VOLUME_RED, LED_WHITE, LEVELS, RING_SEGMENTS,
)
from .preview_lights import peak, scale

# Pillow is loaded on first KnobFace use (_load_pil), so the colour model (and
# ui.py, which re-exports it) imports without PIL, as the pre-v5 ui.py did: a
# broken renderer then only disables the face, never the app.
Image = ImageChops = ImageDraw = ImageFilter = None

_log = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Colour model (moved from ui.py; same behaviour)
# --------------------------------------------------------------------------
# Knob Face optical mapping: level L0..L4 -> alpha, mixed up from the unlit floor.
OPTICAL_ALPHA = (0.0, 0.12, 0.34, 0.68, 1.0)
LED_FLOOR = 31                  # rgb(31,31,31), an unlit segment
SEGMENT_OFF = "#1f1f1f"
BUTTON_FACE = 0x20              # strips are rgba(colour, max(a, .18)) over #202020
STRIP_OFF = "#262626"
STRIP_MIN_ALPHA = 0.18
LED_PALETTE = (LED_WHITE, LED_GREEN, LED_RED, LED_AMBER, LED_VOLUME_RED)
LED_MATCH_TOLERANCE = 2         # per channel, drive rounding and decay truncation


def _channels(color):
    return (color >> 16) & 255, (color >> 8) & 255, color & 255


def _pack(r, g, b):
    return (r << 16) | (g << 8) | b


def optical_alpha(level):
    """Knob Face alpha for a drive level on the 0..255 scale (exact at L0..L4, linear between)."""
    if level <= 0:
        return 0.0
    for k in range(1, len(LEVELS)):
        if level <= LEVELS[k]:
            low, high = LEVELS[k - 1], LEVELS[k]
            return OPTICAL_ALPHA[k - 1] + (OPTICAL_ALPHA[k] - OPTICAL_ALPHA[k - 1]) * (level - low) / (high - low)
    return 1.0


def led_source(drive, palette=LED_PALETTE):
    """(colour, level) behind a pre-cap drive colour from PreviewLights.

    Settled cells are ``scale(colour, level)`` of a palette or accent colour and
    match exactly; decays toward dark keep their hue and match within the
    tolerance. Anything else (a colour-to-colour decay, a press highlight) is
    shown with its hue normalised to a 255 peak at level = its peak.
    """
    if not drive:
        return 0, 0
    drive_peak = peak(drive)
    wanted = _channels(drive)
    best = None
    for colour in palette:
        colour_peak = peak(colour) if colour else 0
        if not colour_peak:
            continue
        level = min(255, round(drive_peak * 255 / colour_peak))
        error = max(abs(a - b) for a, b in zip(_channels(scale(colour, level)), wanted))
        if error <= LED_MATCH_TOLERANCE and (best is None or error < best[0]):
            best = (error, colour, level)
            if not error:
                break
    if best is not None:
        return best[1], best[2]
    return _pack(*(min(255, round(ch * 255 / drive_peak)) for ch in wanted)), drive_peak


def _mix(colour, alpha, base):
    return tuple(round(base + (ch - base) * alpha) for ch in _channels(colour))


def _mix_hex(colour, alpha, base):
    return "#" + "".join(f"{ch:02x}" for ch in _mix(colour, alpha, base))


def ring_display(drive, palette=LED_PALETTE):
    """Screen colour of one ring segment: off + (colour - off) * L[level] (Knob Face)."""
    if not drive:
        return SEGMENT_OFF
    colour, level = led_source(drive, palette)
    return _mix_hex(colour, optical_alpha(level), LED_FLOOR)


def strip_display(drive, palette=LED_PALETTE):
    """Screen colour of a button strip: rgba(colour, max(L[level], .18)) over the face."""
    if not drive:
        return STRIP_OFF
    colour, level = led_source(drive, palette)
    return _mix_hex(colour, max(optical_alpha(level), STRIP_MIN_ALPHA), BUTTON_FACE)


def ring_palette(frame):
    """LED palette plus the frame's own ring accents."""
    ring = frame.get("ring") if isinstance(frame.get("ring"), dict) else {}
    colors = ring.get("colors") if isinstance(ring.get("colors"), list) else []
    return LED_PALETTE + tuple(c for c in colors if type(c) is int and 0 < c <= 0xFFFFFF)


UNLIT = _channels(0x1F1F1F) + (0.0,)


def ring_colors(frame, drives):
    """The 60 ``(r, g, b, level)`` a KnobFace draws for PreviewLights ``drives``.

    ``(r, g, b)`` is exactly the colour ``ring_display`` gives the segment (the
    old mirror's colour); ``level`` (0..1) is its Knob Face optical alpha, which
    sets the body's brightness and the glow (alpha 0.7 * level). Unlit segments
    are ``(31, 31, 31, 0.0)``. Missing drives count as unlit; extra ones are ignored.
    """
    palette = ring_palette(frame if isinstance(frame, dict) else {})
    drives = list(drives or ())[:RING_SEGMENTS]
    drives += [0] * (RING_SEGMENTS - len(drives))
    out = []
    for drive in drives:
        if not drive:
            out.append(UNLIT)
            continue
        colour, level = led_source(drive, palette)
        alpha = optical_alpha(level)
        out.append(_mix(colour, alpha, LED_FLOOR) + (alpha,) if alpha > 0 else UNLIT)
    return tuple(out)


# --------------------------------------------------------------------------
# Geometry (design px)
# --------------------------------------------------------------------------
DESIGN_RING_OUTER = 143                   # outer segment ends: RING_RADIUS + SEGMENT_HEIGHT / 2
RING_LOGICAL_PX = 360                     # the ring's outer diameter in logical px (user decision)
RING_RADIUS = 138
SEGMENT_WIDTH, SEGMENT_HEIGHT = 4, 10
SEGMENT_UNLIT_RGB = (0x1F, 0x1F, 0x1F)
PLATE_RADIUS = 154
PLATE_RGB, PLATE_ALPHA = (0x11, 0x11, 0x11), 235
SHADOW_ALPHA, SHADOW_BLUR, SHADOW_OFFSET = 90, 10, (0, 3)   # CSS blur radius; sigma = blur / 2
DISC_RADIUS = 126
DISC_RGB, DISC_EDGE_RGB, DISC_EDGE_WIDTH = (0x0A, 0x0A, 0x0A), (0x26, 0x26, 0x26), 1
LCD_DESIGN = 240
GLASS_RGB = (0, 0, 0)                     # the LCD glass when no LCD image is given
GLOW_ALPHA = 0.7
GLOW_BLUR = {1: 5, 2: 8, 3: 11, 4: 14}    # 2 + 3l design px (CSS blur radius; sigma = radius / 2)
SIGMAS = 3                                # Gaussian support kept around a shape
# Half the window box: the plate, its shadow offset and 3 sigma of shadow (the glow ends earlier).
FACE_EXTENT = max(PLATE_RADIUS + SHADOW_OFFSET[1] + SIGMAS * SHADOW_BLUR / 2,
                  DESIGN_RING_OUTER + SIGMAS * GLOW_BLUR[4] / 2)
SUPERSAMPLE = 4
GLOW_STEPS = 64                           # glow alpha quantisation (cache key)
# point() tables scaling a glow mask by step / GLOW_STEPS, built once (a cache miss only looks one up).
GLOW_LUTS = tuple([round(v * (step / GLOW_STEPS)) for v in range(256)] for step in range(GLOW_STEPS + 1))
GLOW_MASK_CACHE = 512
BODY_SPRITE_CACHE = 2048


def scale_for(dpi, ring_logical_px=RING_LOGICAL_PX):
    """Physical px per design px: ring_logical_px / 286 * dpi / 96."""
    if isinstance(dpi, bool) or not isinstance(dpi, (int, float)) or not dpi > 0:
        raise ValueError("dpi must be a positive number")
    return ring_logical_px / (2 * DESIGN_RING_OUTER) * dpi / 96


def _load_pil():
    """Bind Pillow's Image, ImageChops, ImageDraw and ImageFilter (static imports, so PyInstaller finds them)."""
    global Image, ImageChops, ImageDraw, ImageFilter
    if ImageFilter is None:
        from PIL import Image as image, ImageChops as chops, ImageDraw as draw, ImageFilter as filters
        Image, ImageChops, ImageDraw, ImageFilter = image, chops, draw, filters


def premultiplied_bgra(image):
    """Premultiplied BGRA bytes of a straight-alpha RGBA image (what UpdateLayeredWindow reads)."""
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    return image.tobytes("raw", "BGRa")


def _level_index(level):
    """The Knob Face level (1..4) whose optical alpha is nearest ``level`` (the glow radius)."""
    return min(range(1, len(OPTICAL_ALPHA)), key=lambda k: abs(OPTICAL_ALPHA[k] - level))


def _glow_rgb(rgb, level):
    """The glow colour c behind a displayed body colour off + (c - off) * level."""
    return tuple(max(0, min(255, round(LED_FLOOR + (ch - LED_FLOOR) / level))) for ch in rgb)


def _clamp8(value):
    return max(0, min(255, int(round(value))))


def _downscale(mask, size):
    """A 4x supersampled mask brought to ``size`` (LANCZOS, FLOATING_KNOB.md section 2)."""
    return mask.resize(size, Image.Resampling.LANCZOS)


class KnobFace:
    """The floating knob face at ``scale`` physical px per design px (see ``scale_for``).

    ``size`` (W, H): the window box, even ints; ``center`` (cx, cy): the
    integer pixel corner W/2, H/2; ``origin``: the exact knob centre every
    layer is drawn about, ``center`` + 0.5 px when ``lcd_px`` is odd (so the
    whole-pixel LCD is centred on the disc and ring); ``lcd_px``: the LCD edge
    render_lcd must paint at (``round(240 * scale)``). ``compose(lcd, ring)``
    returns a straight-alpha RGBA frame of ``size``. Sprites are built once per
    instance (one scale); make a new KnobFace when the DPI changes. Not
    thread-safe: use one instance from one thread (the overlay thread).

    ``lcd_resizes`` counts LCD images that were not ``lcd_px`` square and had to
    be LANCZOS-fitted (a caller bug: section 2 says the LCD is never upscaled
    from 240); the first one per instance is also logged as a warning.
    """

    def __init__(self, scale, *, supersample=SUPERSAMPLE):
        if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0:
            raise ValueError("scale must be a positive finite number")
        _load_pil()
        started = time.perf_counter()
        self.scale = float(scale)
        self.supersample = int(supersample)
        self.lcd_px = max(1, round(LCD_DESIGN * self.scale))
        offset = 0.5 * (self.lcd_px % 2)          # an odd LCD is centred on a pixel centre
        half = math.ceil(FACE_EXTENT * self.scale + offset)   # the full margin on the far side too
        self.size = (2 * half, 2 * half)
        self.center = (half, half)
        self.origin = (half + offset, half + offset)
        self.lcd_resizes = 0
        self._disc_coverage = self._disc_mask(DISC_RADIUS)
        self._base = self._build_base()
        self._inner_box, self._inner = self._build_inner()
        self._segments = [self._build_segment(index) for index in range(RING_SEGMENTS)]
        self._lcd_bases = OrderedDict()        # id(lcd) -> (lcd, base with the LCD)
        self._glow_masks = OrderedDict()       # (index, level, step) -> L mask
        self._bodies = OrderedDict()           # (index, rgb) -> RGBA sprite, least recently used first
        self.frames = 0
        self.build_ms = (time.perf_counter() - started) * 1000

    # ------------------------------------------------------------- building
    def _disc_mask(self, radius, centre=None):
        """Anti-aliased coverage (L, frame size) of a circle of ``radius`` design px.

        Drawn 4x supersampled over the circle's box (plus the LANCZOS support) only.
        Pillow truncates float coordinates and fills both bbox ends, so the box is
        rounded to the supersample grid: it fills [round(a), round(b)) there, which
        is symmetric about ``centre`` (a multiple of 1/supersample px) instead of
        sitting 1/8 px up and left.
        """
        ss = self.supersample
        cx, cy = centre or self.origin
        r = radius * self.scale
        x0, y0 = max(0, math.floor(cx - r) - 4), max(0, math.floor(cy - r) - 4)
        x1, y1 = min(self.size[0], math.ceil(cx + r) + 4), min(self.size[1], math.ceil(cy + r) + 4)
        big = Image.new("L", ((x1 - x0) * ss, (y1 - y0) * ss), 0)
        ImageDraw.Draw(big).ellipse((round((cx - r - x0) * ss), round((cy - r - y0) * ss),
                                     round((cx + r - x0) * ss) - 1, round((cy + r - y0) * ss) - 1), fill=255)
        mask = Image.new("L", self.size, 0)
        mask.paste(_downscale(big, (x1 - x0, y1 - y0)), (x0, y0))
        return mask

    def _solid(self, rgb, alpha_mask):
        """Straight RGBA of one colour with ``alpha_mask`` as alpha (never a colour paste on RGBA)."""
        layer = Image.new("RGBA", alpha_mask.size, tuple(rgb) + (0,))
        layer.putalpha(alpha_mask)
        return layer

    def _build_base(self):
        """Shadow and plate (straight RGBA), the static bottom of every frame."""
        s = self.scale
        cx, cy = self.origin
        dx, dy = SHADOW_OFFSET
        shadow = self._disc_mask(PLATE_RADIUS, (cx + dx * s, cy + dy * s))
        shadow = shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR / 2 * s))
        shadow = shadow.point([round(v * SHADOW_ALPHA / 255) for v in range(256)])
        plate = self._disc_mask(PLATE_RADIUS).point([round(v * PLATE_ALPHA / 255) for v in range(256)])
        base = self._solid((0, 0, 0), shadow)
        base.alpha_composite(self._solid(PLATE_RGB, plate))
        return base

    def _build_inner(self):
        """The disc with its inner edge (straight RGBA), cropped to the disc's box."""
        coverage = self._disc_coverage
        box = coverage.getbbox()
        inside = self._disc_mask(DISC_RADIUS - DISC_EDGE_WIDTH)
        # RGB first (opaque), then alpha: pixels outside the inner circle are edge colour,
        # the band between the circles mixes both by the inner coverage.
        colour = Image.new("RGB", self.size, DISC_EDGE_RGB)
        colour.paste(DISC_RGB, (0, 0), inside)
        inner = colour.convert("RGBA")
        inner.putalpha(coverage)
        return box, inner.crop(box)

    def _segment_corners(self, index):
        theta = math.radians(index * 360 / RING_SEGMENTS)
        cos, sin = math.cos(theta), math.sin(theta)
        cx, cy = self.origin
        s = self.scale
        half_w, half_h = SEGMENT_WIDTH / 2, SEGMENT_HEIGHT / 2
        return [(cx + (lx * cos - ly * sin) * s, cy + (lx * sin + ly * cos) * s)
                for lx, ly in ((-half_w, -RING_RADIUS - half_h), (half_w, -RING_RADIUS - half_h),
                               (half_w, -RING_RADIUS + half_h), (-half_w, -RING_RADIUS + half_h))]

    def _build_segment(self, index):
        """(body origin, body mask, {level: (glow origin, glow mask clipped by the disc)})."""
        s, ss = self.scale, self.supersample
        corners = self._segment_corners(index)
        # The body is drawn 4x over its own box (plus the LANCZOS support), then padded
        # by the widest glow's Gaussian support for the blurs.
        tx0, ty0 = math.floor(min(x for x, _ in corners)) - 4, math.floor(min(y for _, y in corners)) - 4
        tx1, ty1 = math.ceil(max(x for x, _ in corners)) + 4, math.ceil(max(y for _, y in corners)) + 4
        big = Image.new("L", ((tx1 - tx0) * ss, (ty1 - ty0) * ss), 0)
        ImageDraw.Draw(big).polygon([((x - tx0) * ss, (y - ty0) * ss) for x, y in corners], fill=255)
        pad = math.ceil(SIGMAS * GLOW_BLUR[4] / 2 * s) + 2
        x0, y0, x1, y1 = tx0 - pad, ty0 - pad, tx1 + pad, ty1 + pad
        body = Image.new("L", (x1 - x0, y1 - y0), 0)
        body.paste(_downscale(big, (tx1 - tx0, ty1 - ty0)), (pad, pad))
        outside = ImageChops.invert(self._disc_coverage.crop((x0, y0, x1, y1)))
        glows = {}
        for level, radius in GLOW_BLUR.items():
            glow = ImageChops.multiply(body.filter(ImageFilter.GaussianBlur(radius / 2 * s)), outside)
            box = glow.getbbox()
            if box:
                glows[level] = ((x0 + box[0], y0 + box[1]), glow.crop(box))
        box = body.getbbox()
        return (x0 + box[0], y0 + box[1]), body.crop(box), glows

    def _base_for(self, lcd):
        """The static layers with this LCD (cached by identity; the LCD is never mutated)."""
        key = id(lcd)
        hit = self._lcd_bases.get(key)
        if hit is not None and hit[0] is lcd:
            self._lcd_bases.move_to_end(key)
            return hit[1]
        inner = self._inner.copy()
        box = self._inner_box
        cx, cy = self.center
        px = self.lcd_px
        # [cx - px//2, cx - px//2 + px): centred on cx (even px) or cx + 0.5 (odd px), i.e. on origin.
        at = (cx - px // 2 - box[0], cy - px // 2 - box[1])
        if lcd is None:
            glass = Image.new("L", (px * self.supersample,) * 2, 0)
            ImageDraw.Draw(glass).ellipse((0, 0, px * self.supersample - 1, px * self.supersample - 1), fill=255)
            inner.alpha_composite(self._solid(GLASS_RGB, _downscale(glass, (px, px))), at)
        else:
            image = lcd if lcd.mode == "RGBA" else lcd.convert("RGBA")
            if image.size != (px, px):
                # A caller bug (render_lcd must paint at lcd_px): fit it so the app keeps
                # running, but make it visible (lcd_resizes, one warning per face).
                self.lcd_resizes += 1
                if self.lcd_resizes == 1:
                    _log.warning("knob face: LCD image %sx%s resampled to lcd_px %s; render_lcd at the "
                                 "overlay's scale instead (FLOATING_KNOB.md section 2)", *image.size, px)
                image = image.resize((px, px), Image.Resampling.LANCZOS)
            inner.alpha_composite(image, at)
        base = self._base.copy()
        base.alpha_composite(inner, box[:2])
        self._lcd_bases[key] = (lcd, base)
        while len(self._lcd_bases) > 2:
            self._lcd_bases.popitem(last=False)
        return base

    def _glow_mask(self, index, level, alpha):
        step = round(alpha * GLOW_STEPS)
        key = (index, level, step)
        hit = self._glow_masks.get(key)
        if hit is None:
            glow = self._segments[index][2].get(level)
            if glow is None or step <= 0:
                return None
            at, mask = glow
            hit = self._glow_masks[key] = (at, mask.point(GLOW_LUTS[min(step, GLOW_STEPS)]))
            while len(self._glow_masks) > GLOW_MASK_CACHE:
                self._glow_masks.popitem(last=False)
        else:
            self._glow_masks.move_to_end(key)
        return hit

    def _body(self, index, rgb):
        key = (index, rgb)
        sprite = self._bodies.get(key)
        if sprite is None:
            sprite = self._bodies[key] = self._solid(rgb, self._segments[index][1])
            while len(self._bodies) > BODY_SPRITE_CACHE:   # LRU: no 2048-sprite clear() on one frame
                self._bodies.popitem(last=False)
        else:
            self._bodies.move_to_end(key)
        return sprite

    # ------------------------------------------------------------- per frame
    def compose(self, lcd, ring):
        """One frame: straight RGBA of ``size``.

        ``lcd``: an RGBA image of ``lcd_px`` (render_lcd at this scale; alpha is
        the round glass) or None for a blank glass. ``ring``: 60
        ``(r, g, b, level)`` (``ring_colors``; ``(0xRRGGBB, level)`` pairs are
        accepted too); a short sequence leaves the rest unlit.
        """
        frame = self._base_for(lcd).copy()
        ring = tuple(ring or ())
        bodies = []
        for index in range(RING_SEGMENTS):
            entry = ring[index] if index < len(ring) else UNLIT
            if len(entry) == 2:
                (r, g, b), level = _channels(int(entry[0]) & 0xFFFFFF), entry[1]
            else:
                r, g, b, level = entry
            rgb = (_clamp8(r), _clamp8(g), _clamp8(b))
            level = min(1.0, max(0.0, float(level)))
            if level > 0:
                glow = self._glow_mask(index, _level_index(level), GLOW_ALPHA * level)
                if glow is not None:
                    at, mask = glow
                    frame.alpha_composite(self._solid(_glow_rgb(rgb, level), mask), at)
            bodies.append((self._segments[index][0], self._body(index, rgb)))
        for at, sprite in bodies:          # bodies over every glow
            frame.alpha_composite(sprite, at)
        self.frames += 1
        return frame


# --------------------------------------------------------------------------
# Desktop v7: the alive look (ALIVE.md 10.3 item 3; DESKTOP_STAGE 11.3-11.4)
# --------------------------------------------------------------------------
GLL = (0.14, 0.30, 0.45, 0.62, 0.81, 1.00)   # the six look levels (S02 r2; BS:479-481)
GLB = (6, 8, 10, 12, 15, 18)                 # their shadowBlur in BS canvas px (sigma = GLB / 2)
LOOK_ALPHA = 0.95                            # glow alpha = 0.95 * GLL[g] (BS:677)
LOOK_MIN = 0.01                              # no glow at or below this mx
BS_RING_DIAMETER = 318                       # BS's ring: segment ends at 152 + 7, at 1x (BS:671, :679)
ALIVE_BODY_BASE, ALIVE_BODY_SPAN = 36, 219   # body fill round(36 + 219 e): unlit #242424 (S5-19)
ALIVE_UNLIT_RGB = (ALIVE_BODY_BASE,) * 3
LOOKS = len(GLL)


def glow_scale_for(dpi, ring_logical_px=RING_LOGICAL_PX):
    """S_glow: physical px per BS px = the ring's outer diameter in physical px / 318 (K2 10.3
    item 3; K4 11.3). 1.1321 at 96 DPI with the 360 logical px ring."""
    if isinstance(dpi, bool) or not isinstance(dpi, (int, float)) or not dpi > 0:
        raise ValueError("dpi must be a positive number")
    return ring_logical_px * dpi / 96 / BS_RING_DIAMETER


def look_sigmas(glow_scale):
    """The six Gaussian sigmas in physical px: GLB[g] / 2 * S_glow."""
    return tuple(blur / 2 * float(glow_scale) for blur in GLB)


def _half_up(value):
    """JS Math.round for the non-negative values drawn here (Python's round() is banker's)."""
    return int(math.floor(value + 0.5))


def look_index(mx):
    """The look for a rendered level ``mx``: the nearest GLL, ties to the lower look (BS's strict <)."""
    best = 0
    for j in range(1, LOOKS):
        if abs(GLL[j] - mx) < abs(GLL[best] - mx):
            best = j
    return best


def segment_look(e):
    """(fill (r, g, b) 0..255, look index or -1, tint (r, g, b) 0..255) for one segment's ``e``.

    The fill is round(36 + 219 e) per channel; with mx = max(e) > 0.01 the look is
    look_index(mx) and the tint round(e / mx * 255) (the normalised colour); else no glow."""
    r, g, b = (min(1.0, max(0.0, float(c))) for c in e)
    fill = (_half_up(ALIVE_BODY_BASE + ALIVE_BODY_SPAN * r), _half_up(ALIVE_BODY_BASE + ALIVE_BODY_SPAN * g),
            _half_up(ALIVE_BODY_BASE + ALIVE_BODY_SPAN * b))
    mx = max(r, g, b)
    if mx <= LOOK_MIN:
        return fill, -1, (0, 0, 0)
    return fill, look_index(mx), (_half_up(r / mx * 255), _half_up(g / mx * 255), _half_up(b / mx * 255))


def ring_key(ring):
    """The ring part of the floating knob's frame key (AR-22; K4 11.4): per segment the 8-bit
    fill, the look index and the 8-bit tint. Missing segments count as unlit."""
    ring = tuple(ring or ())
    return tuple(segment_look(ring[i]) if i < len(ring) else (ALIVE_UNLIT_RGB, -1, (0, 0, 0))
                 for i in range(RING_SEGMENTS))


def alive_fill_hex(e):
    """'#rrggbb' of one segment's body fill (the simulator's Tk mirror of an alive knob)."""
    return "#{:02x}{:02x}{:02x}".format(*segment_look(e)[0])


class AliveFace(KnobFace):
    """The floating knob face for a knob with ``alive`` (see the module docstring).

    ``scale`` is KnobFace's (segment, plate and disc masks: ``scale_for``); ``glow_scale`` is
    S_glow (``glow_scale_for``), used only for the six glow looks. Built on the overlay thread
    while hidden (at start and on a DPI change); ``looks_build_ms`` is recorded for metrics.
    ``compose_into(canvas, origin, lcd, looks)`` draws one frame into a premultiplied 'RGBX'
    canvas at ``origin``; ``compose(lcd, ring)`` returns it as a straight RGBA image (tests and the
    smoke check). ``looks`` is ``ring_key(ring)`` (the per-segment fill, look and tint)."""

    def __init__(self, scale, glow_scale=None, *, supersample=SUPERSAMPLE):
        if glow_scale is None:
            glow_scale = float(scale) * (2 * DESIGN_RING_OUTER) / BS_RING_DIAMETER
        if isinstance(glow_scale, bool) or not isinstance(glow_scale, (int, float)) or not glow_scale > 0:
            raise ValueError("glow_scale must be a positive number")
        self.glow_scale = float(glow_scale)
        self.sigmas = look_sigmas(self.glow_scale)
        self.looks_build_ms = None
        super().__init__(scale, supersample=supersample)
        started = time.perf_counter()
        # Premultiplied plate + shadow (bands B, G, R, A in an 'RGBX' image): copied first each frame.
        self._under = Image.frombytes("RGBX", self.size, premultiplied_bgra(self._base))
        inner = self._inner                         # straight RGBA disc with its edge, cropped to _inner_box
        red, green, blue, alpha = inner.split()
        self._opaque = Image.new("L", inner.size, 255)
        self._disc_colour = Image.merge("RGBX", (blue, green, red, self._opaque))
        self._disc_mask = alpha
        self._disc_sprites = OrderedDict()          # id(lcd) -> (lcd, colour)
        self._body_boxes = tuple((at[0], at[1], at[0] + mask.width, at[1] + mask.height, mask.im)
                                 for at, mask, _looks in self._segments)
        self._look_boxes = tuple(tuple(None if look is None else
                                       (look[0][0], look[0][1], look[0][0] + look[1].width,
                                        look[0][1] + look[1].height, look[1].im)
                                       for look in looks)
                                 for _at, _mask, looks in self._segments)
        self.build_ms += (time.perf_counter() - started) * 1000

    # ------------------------------------------------------------- building
    def _build_segment(self, index):
        """(body origin, body mask, six (origin, look mask) with 0.95 * GLL[g] baked, clipped by
        the disc) for segment ``index``."""
        if self.looks_build_ms is None:
            self.looks_build_ms = 0.0
        started = time.perf_counter()
        s, ss = self.scale, self.supersample
        corners = self._segment_corners(index)
        tx0, ty0 = math.floor(min(x for x, _ in corners)) - 4, math.floor(min(y for _, y in corners)) - 4
        tx1, ty1 = math.ceil(max(x for x, _ in corners)) + 4, math.ceil(max(y for _, y in corners)) + 4
        big = Image.new("L", ((tx1 - tx0) * ss, (ty1 - ty0) * ss), 0)
        ImageDraw.Draw(big).polygon([((x - tx0) * ss, (y - ty0) * ss) for x, y in corners], fill=255)
        pad = math.ceil(SIGMAS * self.sigmas[-1]) + 2
        x0, y0, x1, y1 = tx0 - pad, ty0 - pad, tx1 + pad, ty1 + pad
        body = Image.new("L", (x1 - x0, y1 - y0), 0)
        body.paste(_downscale(big, (tx1 - tx0, ty1 - ty0)), (pad, pad))
        outside = ImageChops.invert(self._disc_coverage.crop((x0, y0, x1, y1)))
        looks = []
        for g, sigma in enumerate(self.sigmas):
            glow = ImageChops.multiply(body.filter(ImageFilter.GaussianBlur(sigma)), outside)
            alpha = LOOK_ALPHA * GLL[g]
            glow = glow.point([_half_up(v * alpha) for v in range(256)])
            box = glow.getbbox()
            looks.append(((x0 + box[0], y0 + box[1]), glow.crop(box)) if box else None)
        box = body.getbbox()
        self.looks_build_ms += (time.perf_counter() - started) * 1000
        return (x0 + box[0], y0 + box[1]), body.crop(box), tuple(looks)

    def _disc_sprite(self, lcd):
        """The disc with this LCD as a straight 'RGBX' colour image (B, G, R, 255) over the disc's
        box; its mask is the disc coverage (the LCD lies inside the opaque disc). Masked pastes
        only; cached by identity (the LCD is never mutated)."""
        key = id(lcd)
        hit = self._disc_sprites.get(key)
        if hit is not None and hit[0] is lcd:
            self._disc_sprites.move_to_end(key)
            return hit[1]
        colour = self._disc_colour.copy()
        box = self._inner_box
        cx, cy = self.center
        px = self.lcd_px
        at = (cx - px // 2 - box[0], cy - px // 2 - box[1])
        if lcd is None:
            glass = Image.new("L", (px * self.supersample,) * 2, 0)
            ImageDraw.Draw(glass).ellipse((0, 0, px * self.supersample - 1, px * self.supersample - 1), fill=255)
            colour.paste((GLASS_RGB[2], GLASS_RGB[1], GLASS_RGB[0], 255), at + (at[0] + px, at[1] + px),
                         _downscale(glass, (px, px)))
        else:
            image = lcd if lcd.mode == "RGBA" else lcd.convert("RGBA")
            if image.size != (px, px):
                self.lcd_resizes += 1
                if self.lcd_resizes == 1:
                    _log.warning("knob face: LCD image %sx%s resampled to lcd_px %s; render_lcd at the "
                                 "overlay's scale instead (FLOATING_KNOB.md section 2)", *image.size, px)
                image = image.resize((px, px), Image.Resampling.LANCZOS)
            red, green, blue, alpha = image.split()
            colour.paste(Image.merge("RGBX", (blue, green, red, Image.new("L", (px, px), 255))), at, alpha)
        self._disc_sprites[key] = (lcd, colour)
        while len(self._disc_sprites) > 2:
            self._disc_sprites.popitem(last=False)
        return colour

    # ------------------------------------------------------------- per frame
    def compose_into(self, canvas, origin, lcd, looks):
        """Draw one frame into ``canvas`` (a premultiplied 'RGBX' image, bands B, G, R, A, e.g. the
        DIB's left half) with the face's top-left at ``origin``. ``looks``: ``ring_key(ring)``."""
        ox, oy = int(origin[0]), int(origin[1])
        core = canvas.im
        width, height = self.size
        core.paste(self._under.im, (ox, oy, ox + width, oy + height))       # plate + shadow (a copy)
        look_boxes = self._look_boxes
        for index, (_fill, look, tint) in enumerate(looks):
            if look >= 0:
                entry = look_boxes[index][look]
                if entry is not None:
                    x0, y0, x1, y1, mask = entry
                    core.paste((tint[2], tint[1], tint[0], 255), (ox + x0, oy + y0, ox + x1, oy + y1), mask)
        for index, (fill, _look, _tint) in enumerate(looks):                # bodies over every glow
            x0, y0, x1, y1, mask = self._body_boxes[index]
            core.paste((fill[2], fill[1], fill[0], 255), (ox + x0, oy + y0, ox + x1, oy + y1), mask)
        colour = self._disc_sprite(lcd)
        bx0, by0, bx1, by1 = self._inner_box
        core.paste(colour.im, (ox + bx0, oy + by0, ox + bx1, oy + by1), self._disc_mask.im)
        self.frames += 1

    def frame_canvas(self, lcd, ring):
        """A new premultiplied 'RGBX' canvas of ``size`` with one frame drawn (the fake-backend path)."""
        canvas = Image.new("RGBX", self.size, (0, 0, 0, 0))
        self.compose_into(canvas, (0, 0), lcd, ring_key(ring))
        return canvas

    def compose(self, lcd, ring):
        """One frame as a straight RGBA image of ``size`` (``ring``: 60 ``e`` triples)."""
        canvas = self.frame_canvas(lcd, ring)
        return Image.frombytes("RGBA", self.size, canvas.tobytes(), "raw", "BGRa")
