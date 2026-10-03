"""Display headlines for the README: big Archivo type rendered as images, one light and one dark file each.

GitHub gives a README no fonts and no sizes beyond its own headings, so the chapter headlines are drawn here
and placed with <picture> (a prefers-color-scheme dark source, the light file as the <img>). The alt text of
each image is exactly its headline (HEADLINES below is the one place the words live; the blocklist scans it).

Typesetting, without raqm or HarfBuzz (this Pillow has neither):
* a static instance of the app's variable Archivo (app/assets/fonts) at WEIGHT / WIDTH, made with fontTools;
* pair kerning read from that instance's GPOS 'kern' lookups (PairPos formats 1 and 2), plus a slight
  negative tracking for display sizes, so each glyph is placed by hand on the baseline;
* drawn at 2x the canvas and reduced with LANCZOS; the canvas is 2x the README's 880 px column.
Lines that do not fit are broken where the lines come out most even.

SCENES["headlines"] writes docs/media/head-<key>.png and head-<key>-dark.png for every entry.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

COLUMN = 880                  # README column, CSS px
SCALE = 2                     # canvas px per CSS px
SS = 2                        # supersampling on top of SCALE
MAX_TEXT = 800                # CSS px a line may use
WEIGHT, WIDTH = 700, 96       # Archivo wght / wdth for headlines
TRACKING = -0.018             # em
LINE = 1.06                   # line height, in font sizes

INK = {"light": (29, 29, 31), "dark": (245, 245, 247)}       # Apple-style near-black / near-white
QUIET = {"light": (110, 110, 115), "dark": (134, 134, 139)}  # secondary line

def _chapter(headline, subhead):
    """A chapter banner: the headline, then one grey subhead line in the same face (Apple's pattern)."""
    return dict(lines=[(headline, 72, WEIGHT, "ink"), (subhead, 34, 560, "quiet")], top=40, bottom=24, gap=18)


# key -> list of (text, CSS px size, weight, colour role); top/bottom padding in CSS px
HEADLINES = {
    "hero": dict(lines=[("Desk Dial", 112, 760, "ink"),
                        ("A haptic knob for music, lights, windows and CAD.", 40, 560, "quiet")],
                 top=8, bottom=12, gap=22),
    "music-volume": _chapter("Every percent, a click.",
                             "Sonos volume, 1 % per click, with a firm wall at each end."),
    "music-albums": _chapter("Your library, on the knob.",
                             "Recently Added and your playlists, with covers on the round screen."),
    "music-explorer": _chapter("Full screen when you want it.",
                               "Your albums and Up next on the monitor, without taking focus."),
    "lights": _chapter("Dim, warm or set a scene.",
                       "Brightness, warmth and scenes for your Home Assistant lights."),
    "windows": _chapter("Every open window, one turn away.",
                        "Live previews. Turn to choose, press to switch, or snap two side by side."),
    "onshape": _chapter("Zoom, orbit and pan in Onshape.",
                        "Turn to zoom. Hold a button and turn to tilt, orbit or pan."),
    "apps": _chapter("Figma, Plasticity, Blender and AutoCAD.",
                     "Karl Malota's app profiles give each program its own knob."),
    "navigator": _chapter("Always know what each button does.",
                          "A small glass card shows where you are and what the four buttons do."),
    "feel": _chapter("A different feel for each control.",
                     "Soft for volume, coarse for windows, smooth for scrubbing."),
    "ring": _chapter("The ring shows what the knob is doing.",
                     "Sixty LEDs show the volume, the album, and what just happened."),
    "settings": _chapter("Set the sound, the feel and the motion.",
                         "Turn the sounds down, soften the haptics, calm the motion."),
}


def alt(key: str) -> str:
    """The image's alt text: its words, lines joined with a space."""
    parts = [text for text, *_ in HEADLINES[key]["lines"]]
    return " ".join(t if t[-1:] in ".!?" or i == len(parts) - 1 else t + "." for i, t in enumerate(parts))


# ---------------------------------------------------------------- the font
class Face:
    """One static instance of Archivo: a Pillow font per size, advances and GPOS pair kerning in font units."""

    def __init__(self, source: Path, weight: float, width: float, work: Path):
        from fontTools.ttLib import TTFont
        from fontTools.varLib import instancer
        self.path = work / f"Archivo-{int(weight)}-{int(width)}.ttf"
        if not self.path.exists():
            font = instancer.instantiateVariableFont(TTFont(source), {"wght": weight, "wdth": width})
            font.save(self.path)
        tt = __import__("fontTools.ttLib", fromlist=["TTFont"]).TTFont(self.path)
        self.upem = tt["head"].unitsPerEm
        self.cmap = tt.getBestCmap()
        self.adv = {g: m[0] for g, m in tt["hmtx"].metrics.items()}
        self.kern = self._pairs(tt)
        self._pil = {}

    @staticmethod
    def _pairs(tt):
        if "GPOS" not in tt:
            return lambda a, b: 0
        g = tt["GPOS"].table
        idx = sorted({i for fr in g.FeatureList.FeatureRecord if fr.FeatureTag == "kern"
                      for i in fr.Feature.LookupListIndex})
        single, classed = {}, []
        for i in idx:
            lk = g.LookupList.Lookup[i]
            for st in lk.SubTable:
                if lk.LookupType == 9:
                    st = st.ExtSubTable
                if getattr(st, "LookupType", lk.LookupType) != 2:
                    continue
                cov = st.Coverage.glyphs
                if st.Format == 1:
                    for first, ps in zip(cov, st.PairSet):
                        for r in ps.PairValueRecord:
                            v = getattr(r.Value1, "XAdvance", 0) if r.Value1 else 0
                            single.setdefault((first, r.SecondGlyph), v)
                elif st.Format == 2:
                    classed.append((set(cov), st.ClassDef1.classDefs, st.ClassDef2.classDefs, st.Class1Record))

        def kern(a, b):
            if (a, b) in single:
                return single[(a, b)]
            for cov, c1, c2, rec in classed:
                if a in cov:
                    v = rec[c1.get(a, 0)].Class2Record[c2.get(b, 0)].Value1
                    x = getattr(v, "XAdvance", 0) if v else 0
                    if x:
                        return x       # (a zero here may be a split subtable's class 0: keep looking)
            return 0
        return kern

    def pil(self, px: int):
        if px not in self._pil:
            self._pil[px] = ImageFont.truetype(str(self.path), px, layout_engine=ImageFont.Layout.BASIC)
        return self._pil[px]

    def layout(self, text: str, px: float):
        """[(char, x)] in px from the line origin, and the line's advance width."""
        out, x, prev = [], 0.0, None
        track = TRACKING * px
        for ch in text:
            gid = self.cmap.get(ord(ch))
            if prev is not None and gid is not None:
                x += self.kern(prev, gid) * px / self.upem
            out.append((ch, x))
            x += self.adv.get(gid, self.upem // 2) * px / self.upem + (track if ch != " " else 0)
            prev = gid
        return out, x - (track if text and text[-1] != " " else 0)


def _balanced(face, text, px, limit):
    """Break ``text`` into the fewest lines under ``limit`` px, choosing the most even split."""
    words = text.split(" ")
    if face.layout(text, px)[1] <= limit or len(words) == 1:
        return [text]
    best = None
    for n in (2, 3):
        import itertools
        for cuts in itertools.combinations(range(1, len(words)), n - 1):
            parts = [" ".join(words[a:b]) for a, b in zip((0,) + cuts, cuts + (len(words),))]
            widths = [face.layout(p, px)[1] for p in parts]
            if max(widths) <= limit:
                score = max(widths) - min(widths)
                if best is None or score < best[0]:
                    best = (score, parts)
        if best:
            return best[1]
    return words


# ---------------------------------------------------------------- drawing
def render(key: str, theme: str, faces: dict) -> Image.Image:
    spec = HEADLINES[key]
    k = SCALE * SS
    W = COLUMN * k
    rows = []                                     # (chars, x0, size px, face, colour, ascent, descent)
    for text, size, weight, role in spec["lines"]:
        face = faces[weight]
        px = size * k
        for line in _balanced(face, text, px, MAX_TEXT * k):
            chars, width = face.layout(line, px)
            colour = (INK if role == "ink" else QUIET)[theme]
            rows.append((chars, (W - width) / 2, px, face, colour))
    top, bottom, gap = spec.get("top", 40) * k, spec.get("bottom", 20) * k, spec.get("gap", 0) * k
    H, ys, prev_px = top, [], None
    for i, (_c, _x, px, _f, _col) in enumerate(rows):
        if prev_px is None:
            H += px * 0.80                         # cap height-ish above the first baseline
        else:
            H += (px * LINE if px == prev_px else px * 0.95 + gap)
        ys.append(H)
        prev_px = px
    H += rows[-1][2] * 0.24 + bottom               # room for descenders
    img = Image.new("RGBA", (W, int(H)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for (chars, x0, px, face, colour), y in zip(rows, ys):
        font = face.pil(int(round(px)))
        for ch, x in chars:
            if ch != " ":
                d.text((x0 + x, y), ch, font=font, fill=colour + (255,), anchor="ls")
    return img.resize((W // SS, int(H) // SS), Image.LANCZOS)


def typeset(draw, app: Path, work: Path, text: str, px: float, weight: float, xy, fill, tracking=TRACKING):
    """Draw one kerned line with its left end at xy (x, baseline); for other images (social preview)."""
    global TRACKING
    face = Face(Path(app) / "assets" / "fonts" / "Archivo.ttf", weight, WIDTH, Path(work))
    saved, TRACKING = TRACKING, tracking
    try:
        chars, width = face.layout(text, px)
    finally:
        TRACKING = saved
    font = face.pil(int(round(px)))
    for ch, x in chars:
        if ch != " ":
            draw.text((xy[0] + x, xy[1]), ch, font=font, fill=fill, anchor="ls")
    return width


def render_all(app: Path, out: Path, work: Path, keys=None, log=print) -> list[Path]:
    work.mkdir(parents=True, exist_ok=True)
    src = Path(app) / "assets" / "fonts" / "Archivo.ttf"
    weights = sorted({w for spec in HEADLINES.values() for _t, _s, w, _r in spec["lines"]})
    faces = {w: Face(src, w, WIDTH, work) for w in weights}
    written = []
    for key in keys or HEADLINES:
        for theme in ("light", "dark"):
            img = render(key, theme, faces)
            path = out / (f"head-{key}.png" if theme == "light" else f"head-{key}-dark.png")
            # 256-colour palette with alpha: one ink colour and its antialiasing ramp, a third of the bytes
            img.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).save(path, optimize=True)
            written.append(path)
        log(f"head-{key}: {img.size} {written[-2].stat().st_size // 1024} KB / {written[-1].stat().st_size // 1024} KB")
    return written


def scene(ctx):
    return [ctx.produced(p, TYPE) for p in render_all(ctx.app, Path(ctx.out), Path(ctx.work) / "headlines", log=ctx.log)]


TYPE = "typography (Archivo, headlines.py)"
SCENES = {"headlines": (TYPE, scene)}


if __name__ == "__main__":
    # python headlines.py <app dir> <out dir> [key ...]
    a = sys.argv[1:]
    render_all(Path(a[0]), Path(a[1]), Path(a[1]) / "_work", a[2:] or None)
