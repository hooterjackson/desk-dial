"""Snapshot blur recipes per surface (DESKTOP_STAGE §12 = S01 App B; VOC §7.1 recipe ids).

Every recipe is **fixed per surface, taken from a snapshot at open (or at show), and never
animated** (R:112-115). Radii are CSS ``blur()`` standard deviations in units, so σ at the
reduced scale is ``radius × k / reduce`` (``carousel_render.glass_sigma``). Saturation uses the
Rec.709 matrix, then the tint is applied as a second matrix pass on the same small image
(``carousel_render._saturate_matrix`` / ``_tint_matrix``, the v6 order; the equality is a unit
test). The two passes are not folded into one matrix: CSS clamps the saturated colour before the
tint layer is composited over it, and a single matrix would not clamp in between.

| Recipe            | reduce | radius | saturate | tint (folded)          | extra                              |
|-------------------|--------|--------|----------|------------------------|------------------------------------|
| blur.explorer     | 8      | 36     | 1.3      | rgba(8,8,10,.50)       | ambient opacity .50                |
| blur.upnext       | 8      | 36     | 1.3      | rgba(8,8,10,.55)       | ambient opacity .45                |
| blur.picker_frost | 8      | 40     | 1.6      | rgba(10,10,12,.50)     | no dim, no sheen                   |
| blur.picker_none  | -      | -      | -        | flat rgba(0,0,0,.55)   | label shadow 0 1px 2px /.6         |
| blur.toast        | 4      | 24     | 1        | rgba(24,24,26,.62)     | 1 px rgba(255,255,255,.2) border;  |
|                   |        |        |          |                        | fallback tint alpha .88            |

The stage (explorer, Up next) builds the frost at 1/8 with **one reduced pixel of overdraw**
past every monitor edge (§4.4 "Full-width layers") and places it scaled ×8 at (−8, −8) px. With
no capture (timeout 500 ms, or a failure) the frost is the tint alone over an opaque ``#0E0E10``
base (S5-30), never a translucent tint over the live desktop.

The ambient layer (§12, §7.5): the focused cover's 64 px copy cover-fit into the 1/8 bleed box
(the monitor plus 160 units on every side), ``GaussianBlur`` σ = 90·k/8, saturate 1.5, placed at
(−160k, −160k) px scaled ×8; its opacity (0.50 / 0.45) is the visual's, animated for the
crossfade, never baked. All PIL work here runs on a worker thread (``NanoD-stage-capture`` or
the art workers): ``reduce``, ``resize``, ``GaussianBlur`` and ``tobytes`` release the GIL
(§4.7.3); the matrix ``convert`` passes work on the small reduced image only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

NO_CAPTURE_BASE = (0x0E, 0x0E, 0x10)          # S5-30
AMBIENT_BLEED_UNITS = 160
AMBIENT_REDUCE = 8
AMBIENT_RADIUS_UNITS = 90
AMBIENT_SATURATE = 1.5
OVERDRAW = 1                                   # reduced px past every monitor edge (§4.4)
CAPTURE_TIMEOUT_S = 0.500                      # CA:208
TOAST_CAPTURE_TIMEOUT_S = 0.150                # CA:209


@dataclass(frozen=True)
class Recipe:
    id: str
    reduce: int
    radius_units: float
    saturate: float
    tint_rgb: tuple
    tint_a: float
    ambient_opacity: float | None = None
    border: tuple | None = None                 # (r, g, b, a) 1 px border
    fallback_a: float | None = None             # tint alpha without a capture (toast)
    flat: bool = False                          # picker_none: a flat dim, no snapshot

    def sigma(self, k: float) -> float:
        """σ at the reduced scale: radius × k / reduce (e.g. 36·2/8 = 9 for the explorer)."""
        return max(0.1, self.radius_units * float(k) / self.reduce) if self.reduce else 0.0


RECIPES = {
    "blur.explorer": Recipe("blur.explorer", 8, 36, 1.3, (8, 8, 10), 0.50, ambient_opacity=0.50),
    "blur.upnext": Recipe("blur.upnext", 8, 36, 1.3, (8, 8, 10), 0.55, ambient_opacity=0.45),
    "blur.picker_frost": Recipe("blur.picker_frost", 8, 40, 1.6, (10, 10, 12), 0.50),
    "blur.picker_none": Recipe("blur.picker_none", 0, 0, 1.0, (0, 0, 0), 0.55, flat=True),
    "blur.toast": Recipe("blur.toast", 4, 24, 1.0, (24, 24, 26), 0.62, border=(255, 255, 255, 0.2),
                         fallback_a=0.88),
}
SURFACE_RECIPE = {"explorer": "blur.explorer", "upnext": "blur.upnext"}


def saturate_matrix(s: float):
    """CSS ``saturate(s)`` (Rec.709 luma), as a PIL RGB convert matrix."""
    return (0.213 + 0.787 * s, 0.715 - 0.715 * s, 0.072 - 0.072 * s, 0,
            0.213 - 0.213 * s, 0.715 + 0.285 * s, 0.072 - 0.072 * s, 0,
            0.213 - 0.213 * s, 0.715 - 0.715 * s, 0.072 + 0.928 * s, 0)


def tint_matrix(rgb, alpha: float, dim: float = 1.0):
    """``dst * dim * (1 - a) + rgb * a``: a tint layer folded into the pixels."""
    c = dim * (1 - alpha)
    return (c, 0, 0, rgb[0] * alpha, 0, c, 0, rgb[1] * alpha, 0, 0, c, rgb[2] * alpha)


def reduced_size(w: int, h: int, reduce: int):
    return int(math.ceil(w / reduce)), int(math.ceil(h / reduce))


def tint_only(recipe: Recipe, size):
    """S5-30: the tint over an opaque #0E0E10 base (no capture)."""
    from PIL import Image
    a = recipe.fallback_a if recipe.fallback_a is not None else recipe.tint_a
    col = tuple(int(round(b * (1 - a) + t * a)) for b, t in zip(NO_CAPTURE_BASE, recipe.tint_rgb))
    return Image.new("RGB", size, col)


def frost(capture, recipe: Recipe, k: float, monitor_size, overdraw: int = OVERDRAW):
    """The frost at the reduced scale with ``overdraw`` reduced px on every side, as an opaque RGB
    image, and its source ('snapshot' | 'tint_only'). ``capture`` is an RGB image of the monitor
    (or None). The image goes on a visual scaled ``recipe.reduce`` at (−overdraw·reduce) px."""
    from PIL import Image, ImageFilter
    if recipe.flat:
        raise ValueError("blur.picker_none is a flat dim, not a snapshot recipe")
    W, H = int(monitor_size[0]), int(monitor_size[1])
    rw, rh = reduced_size(W, H, recipe.reduce)
    if capture is None:
        small, source = tint_only(recipe, (rw, rh)), "tint_only"
    else:
        src = capture if capture.mode == "RGB" else capture.convert("RGB")
        small = src.reduce(recipe.reduce)
        if small.size != (rw, rh):
            small = small.resize((rw, rh), Image.BILINEAR)
        small = small.filter(ImageFilter.GaussianBlur(recipe.sigma(k)))
        if recipe.saturate != 1.0:
            small = small.convert("RGB", saturate_matrix(recipe.saturate))           # clamped, as CSS
        small = small.convert("RGB", tint_matrix(recipe.tint_rgb, recipe.tint_a))
        source = "snapshot"
    if overdraw <= 0:
        return small, source
    o = int(overdraw)
    p = Image.new("RGB", (rw + 2 * o, rh + 2 * o))
    p.paste(small, (o, o))
    for i in range(o):                                        # replicate the edge rows and columns
        p.paste(small.crop((0, 0, rw, 1)), (o, i))
        p.paste(small.crop((0, rh - 1, rw, rh)), (o, rh + o + i))
    for i in range(o):
        p.paste(p.crop((o, 0, o + 1, rh + 2 * o)), (i, 0))
        p.paste(p.crop((rw + o - 1, 0, rw + o, rh + 2 * o)), (rw + o + i, 0))
    return p, source


def frost_placement(recipe: Recipe, overdraw: int = OVERDRAW):
    """(scale, dx, dy) of the frost visual's matrix: ×reduce at (−overdraw·reduce) px."""
    r = float(recipe.reduce)
    return r, -overdraw * r, -overdraw * r


def ambient_size(k: float, monitor_size):
    W, H = monitor_size
    bleed = 2 * AMBIENT_BLEED_UNITS * float(k)
    return int(round((W + bleed) / AMBIENT_REDUCE)), int(round((H + bleed) / AMBIENT_REDUCE))


def ambient(source, k: float, monitor_size):
    """The ambient layer at 1/8 of the bleed box (720 × 260 on the G93SC) from a square cover
    (any size; reduced to its 64 px copy first) or a solid ``0xRRGGBB`` (``art_bg``)."""
    from PIL import Image, ImageFilter
    bw, bh = ambient_size(k, monitor_size)
    if isinstance(source, int):
        rgb = ((source >> 16) & 255, (source >> 8) & 255, source & 255)
        return Image.new("RGB", (bw, bh), rgb)
    src = source if source.mode == "RGB" else source.convert("RGB")
    if src.size != (64, 64):
        src = src.resize((64, 64), Image.BILINEAR, reducing_gap=2.0)
    side = max(bw, bh)
    fit = src.resize((side, side), Image.BILINEAR)             # CSS center / cover of a square
    left, top = (side - bw) // 2, (side - bh) // 2
    img = fit.crop((left, top, left + bw, top + bh))
    img = img.filter(ImageFilter.GaussianBlur(AMBIENT_RADIUS_UNITS * float(k) / AMBIENT_REDUCE))
    return img.convert("RGB", saturate_matrix(AMBIENT_SATURATE))


def ambient_placement(k: float):
    """(scale, dx, dy): ×8 at (−160k, −160k) px."""
    return float(AMBIENT_REDUCE), -AMBIENT_BLEED_UNITS * float(k), -AMBIENT_BLEED_UNITS * float(k)
