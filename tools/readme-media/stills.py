"""Stills from the true-to-app recordings and the desktop overlays.

* knob-screens.png: the twelve knob screens of `stills.json` (capture.py's `stills` scene: Home, Music, Recently
  Added, Playlists, Tracks, Seek, Up next, Windows, Lights, Colour temperature, Scenes, Onshape), each drawn by the
  firmware's own LCD renderer (knob-anim) from the recorded wire frame, as a captioned 4-column contact sheet.
* button-maps/<screen>.png: per screen, the knob's own footer strip (the four button glyphs, cropped from the same
  LCD frame) over a text row "1 word · 2 word · 3 word · 4 word" and the hold action of `button-maps.json`.
* The desktop overlays (Music explorer, Up next, Windows picker) from the app's own renderers (unchanged).

`render(knob_anim, work, out_dir, stills_json=None)` keeps scenes_registry.scene_stills' 3-argument call working:
without `stills_json` the recording is looked up (and captured on demand) through rec_scenes.recording_path.
All data is fictional (fiction.py / fixtures.py); nothing here opens a device, a window or the network.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import fixtures as fx
import knob_scenes as K
from companion import APP_DIR

CAPTIONS = ["Home", "Music", "Recently Added", "Playlists", "Tracks", "Seek", "Up next", "Windows",
            "Lights", "Colour temperature", "Scenes", "Onshape"]
STILL_CAP = 300_000          # gates.CAPS["still"]
FOOTER_BAND = (0.70, 0.90)   # the button glyph row of the 240 px LCD, as fractions of its height
HOLD_SECONDS = {"0": 0.6, "3": 1.0}   # slot -> hold time the firmware sends (kh of button 1 at 0.6 s, of button 4 at 1.0 s)


# ------------------------------------------------------------------ fonts
def font(name: str, size: int, variation: str | None = None) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(Path(APP_DIR) / "assets" / "fonts" / f"{name}.ttf"), size)
    if variation:
        try:
            f.set_variation_by_name(variation)
        except Exception:
            pass
    return f


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# ------------------------------------------------------------------ the recorded stills through the firmware renderer
def load_stills(stills_json) -> dict:
    """The `stills` recording as a recording.py-shaped dict: one frame event per still, 1 fps, 900 ms settle."""
    import recording
    rec = recording.load(stills_json)
    items = rec["stills"]
    rec.update(fps=1, duration_ms=len(items) * 1000, preroll_ms=900,
               events=[{"t": k * 1000 - 900, "kind": "frame", "frame": s["frame"]} for k, s in enumerate(items)])
    return rec


def render_lcds(knob_anim, work, stills_json) -> tuple[list[dict], list[Image.Image]]:
    """([still records], [240 x 240 RGB LCD images]) in stills.json order."""
    import recording
    rec = load_stills(stills_json)
    lcds = recording.lcd_frames(rec, knob_anim, Path(work), tag="-stills")
    items = rec["stills"]
    if len(lcds) < len(items):
        raise RuntimeError(f"knob-anim returned {len(lcds)} frames for {len(items)} stills")
    return items, lcds[:len(items)]


def lcd_disc(lcd: Image.Image, px: int, bezel=(44, 45, 50), bezel_w=4) -> Image.Image:
    """The LCD as a round tile with a thin bezel, RGBA, (px + 2 * bezel_w) square."""
    ss = 4
    size = px + 2 * bezel_w
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ring = Image.new("L", (size * ss,) * 2, 0)
    ImageDraw.Draw(ring).ellipse((0, 0, size * ss - 1, size * ss - 1), fill=255)
    ring = ring.resize((size,) * 2, Image.Resampling.LANCZOS)
    out.paste(bezel, (0, 0), ring)
    mask = Image.new("L", (px * ss,) * 2, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, px * ss - 1, px * ss - 1), fill=255)
    mask = mask.resize((px,) * 2, Image.Resampling.LANCZOS)
    out.paste(lcd.resize((px,) * 2, Image.Resampling.LANCZOS), (bezel_w, bezel_w), mask)
    return out


def save_png(img: Image.Image, path: Path, cap=STILL_CAP) -> Path:
    """PNG under the still cap: optimized RGB first, then a 256-colour palette, then 192 / 128 colours."""
    path = Path(path)
    img.save(path, optimize=True)
    for colors in (256, 192, 128):
        if path.stat().st_size <= cap:
            break
        q = img.convert("RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
        q.save(path, optimize=True)
    return path


def render(knob_anim, work, out_dir, stills_json=None) -> list[Path]:
    """knob-screens.png: 12 tiles, 4 columns, captions under each. Returns [path]."""
    work, out_dir = Path(work), Path(out_dir)
    if stills_json is None:
        import rec_scenes
        stills_json = rec_scenes.recording_path(work, "stills")
    items, lcds = render_lcds(knob_anim, work, stills_json)
    cap_font = font("Archivo", 20, "Medium")
    px, cols, pad, cap_h = 200, 4, 16, 34
    cell = px + 2 * pad
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cell * cols, (cell + cap_h) * rows + pad), K.BG)
    d = ImageDraw.Draw(sheet)
    for k, (s, lcd) in enumerate(zip(items, lcds)):
        tile = lcd_disc(lcd, px)
        x = (k % cols) * cell + pad - 4
        y = (k // cols) * (cell + cap_h) + pad
        sheet.paste(tile, (x, y), tile)
        cap = s["name"]
        w = d.textlength(cap, font=cap_font)
        d.text(((k % cols) * cell + (cell - w) / 2, y + px + 10), cap, font=cap_font, fill=(170, 174, 184))
    path = save_png(sheet, out_dir / "knob-screens.png")
    print(f"{path.name}: {sheet.size} {path.stat().st_size // 1024} KB", flush=True)
    (work / "stills.json").write_text(json.dumps([s["name"] for s in items]), encoding="utf-8")
    return [path]


# ------------------------------------------------------------------ button maps
def load_button_maps(button_maps_json) -> dict[str, dict]:
    """name -> {"buttons": [(label, icon, enabled, lit) x4], "holdAction", "feel", "profile"}."""
    data = json.loads(Path(button_maps_json).read_text(encoding="utf-8"))
    out = {}
    for s in data["screens"]:
        out[s["name"]] = {"buttons": [(b[1], b[0], b[2], b[3]) for b in s["buttons"]],
                          "holdAction": s.get("holdAction") or "", "feel": s.get("feel", ""),
                          "profile": s.get("profile", "")}
    return out


def button_row(buttons, sep=" · ", dash="—") -> str:
    return sep.join(f"{k + 1} {label or dash}" for k, (label, _icon, _en, _lit) in enumerate(buttons))


def hold_line(name: str, hold_action: str) -> str:
    """The hold the screen offers: hold 4 (1.0 s) where the map has one; hold 1 (0.6 s) = Home on the music and lights
    screens (not on Home, Windows or Onshape, where button 1 is not a Back)."""
    parts = []
    if hold_action:
        parts.append(f"hold 4 ({HOLD_SECONDS['3']:.1f} s) = {hold_action}")
    if name not in ("Home", "Windows", "Onshape"):
        parts.append(f"hold 1 ({HOLD_SECONDS['0']:.1f} s) = Home")
    return "   ".join(parts)


def glyph_band(lcd: Image.Image, margin=3, below=4, threshold=70, faint=30) -> tuple[int, int]:
    """(y0, y1) of the button glyph row, cut tight so no line of the meta text above it leaks in.

    From the lowest lit row of the LCD's middle (the glyphs, or the lit button's underline under them, sit at the
    bottom of every layout at a height that varies with it) walk up: a short run (<= 5 rows) followed by a gap is the
    underline; the next run is the glyphs (about 20 rows). The crop keeps at most `margin` blank rows over the glyphs
    (never reaching the text line above) and `below` rows under the lowest lit row."""
    h, w = lcd.height, lcd.width
    lum = lcd.convert("L")
    x0, x1 = round(w * 0.12), round(w * 0.88)
    peak = [lum.crop((x0, y, x1, y + 1)).getextrema()[1] for y in range(h)]
    bottom = next((y for y in range(round(h * FOOTER_BAND[1]), h // 2, -1) if peak[y] > threshold), None)
    if bottom is None:
        return round(h * 0.62), round(h * 0.80)

    def run_top(y):           # first row of the lit run ending at y
        while y - 1 > h // 2 and peak[y - 1] > faint:
            y -= 1
        return y

    top = run_top(bottom)
    if bottom - top + 1 <= 5:                     # the underline: skip the gap to the glyphs
        y = top - 1
        while y > h // 2 and peak[y] <= faint and top - y <= 10:
            y -= 1
        if peak[y] > faint:
            top = run_top(y)
    gap = 0
    while top - gap - 1 > 0 and peak[top - gap - 1] <= faint and gap < margin:
        gap += 1
    if gap < margin:                              # text sits right over the glyphs: keep one blank row at most
        gap = max(0, gap - 1)
    return top - gap, min(h, bottom + below + 1)


def footer_strip(lcd: Image.Image, width: int) -> Image.Image:
    """The glyph row of the LCD, cropped and scaled to `width`."""
    y0, y1 = glyph_band(lcd)
    band = lcd.crop((0, y0, lcd.width, y1))
    return band.resize((width, round((y1 - y0) * width / lcd.width)), Image.Resampling.LANCZOS)


def button_maps(knob_anim, work, out_dir, stills_json=None, button_maps_json=None) -> list[Path]:
    """button-maps/<screen>.png for every still: the knob's footer strip + the labelled row + the hold."""
    work, out_dir = Path(work), Path(out_dir)
    if stills_json is None:
        import rec_scenes
        stills_json = rec_scenes.recording_path(work, "stills")
    if button_maps_json is None:
        button_maps_json = Path(stills_json).parent / "button-maps.json"
    items, lcds = render_lcds(knob_anim, work, stills_json)
    maps = load_button_maps(button_maps_json)
    row_font, hold_font, name_font = font("Archivo", 22, "Medium"), font("Archivo", 18, "Regular"), font("Montserrat", 16, "SemiBold")
    width, pad = 420, 14
    folder = out_dir / "button-maps"
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for s, lcd in zip(items, lcds):
        m = maps.get(s["name"]) or {"buttons": [(b["label"], b["icon"], b["enabled"], b.get("lit")) for b in s["frame"]["buttons"]],
                                   "holdAction": s.get("holdAction", "")}
        strip = footer_strip(lcd, width)
        hold = hold_line(s["name"], m["holdAction"])
        h = pad + 22 + 6 + strip.height + 10 + 28 + (26 if hold else 0) + pad
        img = Image.new("RGB", (width + 2 * pad, h), K.BG)
        d = ImageDraw.Draw(img)
        y = pad
        d.text((pad, y), s["name"].upper(), font=name_font, fill=(150, 154, 164))
        y += 22 + 6
        img.paste(strip, (pad, y))
        y += strip.height + 10
        row, f = button_row(m["buttons"]), row_font
        for size in (21, 20, 19, 18, 17, 16):      # long rows (Windows: Snap left / Snap right) shrink to fit
            if d.textlength(row, font=f) <= width:
                break
            f = font("Archivo", size, "Medium")
        d.text((pad, y), row, font=f, fill=(236, 238, 242))
        y += 28
        if hold:
            d.text((pad, y), hold, font=hold_font, fill=(214, 160, 86))
        p = save_png(img, folder / f"{slug(s['name'])}.png")
        paths.append(p)
    print(f"button-maps/: {len(paths)} PNG, {sum(p.stat().st_size for p in paths) // 1024} KB", flush=True)
    return paths


# ------------------------------------------------------------------ desktop overlays (stills)
def upnext_payload(t0, SIM, now=4, liked=(1, 4), rows=24):
    """An ``upnext_open`` payload for a fictional favourite playlist."""
    albums = fx.PLAYLISTS[1][1] + [2, 5, 7]
    out = []
    for k in range(rows):
        al = albums[k % len(albums)]
        names = SIM.TRACKS[al]
        name = names[(k // len(albums) + k) % len(names)]
        title, artist, _year, colour = SIM.ALBUMS[al]
        song = SIM._song_id(al, names.index(name))
        keys = SIM.art_keys("full", k, f"s{song}", colour)
        out.append({"row": k + 1, "title": name, "artist": artist, "album": title, "song_id": song, "catalog": True,
                    "duration_s": SIM.dur_of(name), "track_number": None, "sonos_art": "", "segment": "base",
                    "liked": k in liked, **keys})
    pl = fx.PLAYLISTS[1]
    ctx = {"kind": "playlist", "title": pl[0], "sub": f"Favourite playlist · {pl[3]} songs · 2 h 24 min"}
    return {"t0": t0, "rows": out, "now": now, "focus": now + 1, "count": rows, "card": None, "context": ctx,
            "shuffle": "off", "likes_known": True, "loading": False, "control_id": 1, "control_min": 0,
            "reduced_motion": False, "foreground_hwnd": 0}


def overlay_stills(out_dir):
    """Music explorer (both tabs) and Up next, 16:9, from the stage engine's reference renderer."""
    import desktop_scene as D
    TS, SIM = D.TS, D.SIM
    shots = [("music-explorer-16x9", "explorer", lambda t0: TS.explorer_payload(t0, index=4, art="full")),
             ("music-explorer-playlists-16x9", "explorer",
              lambda t0: TS.explorer_payload(t0, source="favourites", index=1, favs="many")),
             ("up-next-16x9", "upnext", lambda t0: upnext_payload(t0, SIM))]
    desk = fx.desktop((1920, 1080))
    for name, surface, build in shots:
        rig = D.Rig(D.MONITOR)
        getattr(rig.presenter, surface + "_open")(build(rig.now()))
        rig.settle()
        rig.advance(1600, 100)
        img = D.over_desktop(rig, desk)
        path = out_dir / f"{name}.png"
        img.save(path, optimize=True)
        print(f"{path.name}: {img.size} {path.stat().st_size // 1024} KB", flush=True)


def picker_stills(out_dir):
    """The Windows picker and Snap left: the production carousel on the app's golden-test fake
    backend (tests/test_carousel_goldens.py), with fictional apps, titles and window thumbnails."""
    import sys
    sys.path.insert(0, str(Path(APP_DIR) / "tests"))
    import test_carousel_goldens as G
    from control_center import carousel_render as R
    n = len(fx.WINDOWS)
    G.APPS = tuple(w[0] for w in fx.WINDOWS)
    G.TITLES = tuple(w[1] for w in fx.WINDOWS)
    G.DESCS = tuple(w[2] for w in fx.WINDOWS)
    G.CLOSED, G.STUB = 99, 99
    G.desktop = fx.desktop
    G.TABLES["16x9"] = ((0, 0, 1920, 1080), (0, 0, 1920, 1032))

    def composite(backend, background):
        w, h = backend.monitor[2] - backend.monitor[0], backend.monitor[3] - backend.monitor[1]
        base = fx.desktop((w, h))
        if background == "glass" and backend.glass_image is not None:
            G._over(base, backend.glass_image, backend.glass_rect[:2], G._alpha(backend.glass_level))
        elif background == "none":
            G._over(base, R.Canvas(Image.new("RGBX", (w, h), R._pm((0, 0, 0), 0.55))), (0, 0),
                    G._alpha(backend.dim_level))
        for handle in backend.order:
            if handle not in backend.props:
                continue
            dest, _source, opacity, visible = backend.props[handle]
            if not visible or opacity <= 0:
                continue
            l, t, r, b = dest
            if r <= l or b <= t:
                continue
            hwnd = backend.thumbs.get(handle, 0)
            tile = fx.window_thumb((hwnd - 100) % n, (r - l, b - t))
            base.paste(tile, (l, t), Image.new("L", tile.size, opacity))
        layout = R.layout_for(backend.monitor, backend.work)
        if "chrome" in backend.visible:
            G._over(base, backend.chrome, layout.band[:2])
        for role, rest in (("label", layout.labels), ("dots", layout.dots)):
            canvas = backend.layers.get(role)
            if canvas is None or role not in backend.visible:
                continue
            alpha, pos = backend.layer_state.get(role, (0, None))
            G._over(base, canvas, pos if pos is not None else rest[:2], G._alpha(alpha))
        return base

    G.composite = composite
    s = G.Scene("16x9", "glass")
    try:
        s.p.highlight(2)
        s.step(0.8)
        s.image().save(out_dir / "window-picker-16x9.png", optimize=True)
        job = s.snap(2, "left")
        s.step(0.1)
        s.snapper.answer(job, "final", "ok")
        s.step(1.0)
        s.image().save(out_dir / "window-picker-snap-16x9.png", optimize=True)
        print("window-picker-16x9.png, window-picker-snap-16x9.png", flush=True)
    finally:
        s.close()
