"""Stills: the knob's screens from the firmware's own LCD renderer (knob-anim) as a captioned contact sheet
(knob-screens.png), and the desktop overlays (Music explorer, Up next, Windows picker) from the app's own
renderers, all from fictional data."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import fixtures as fx
import knob_scenes as K
from companion import APP_DIR

NEXT_ALBUM, NEXT_SONG = 5, "Level Nine"        # "Level Nine" by Velvet Circuit
UPNEXT_ALBUMS = fx.PLAYLISTS[1][1] + [2, 5, 7]


def B(label, icon, enabled=True, **kw):
    return dict(label=label, enabled=enabled, icon=icon, **kw)


def screens():
    F = K.Frames()
    out = [("Home", F.home(54)), ("Volume", F.home(62, reveal=True)), ("Recently Added", F.recent(4)),
           ("Music explorer mirror", F.explorer(4))]
    b = F._base
    out.append(("Tracks", (b("TRACKS", "tracks", heading="TRACKS", title="Next track", subtitle=f"Next: {NEXT_SONG}",
                             meta="Press to skip",
                             buttons=[B("Back", "back"), B("Up next", "expand"), B("Seek", "seek"), B("Skip", "next")],
                             ring={"style": "transport", "value": 0, "index": 2, "count": 3}), K.NOW_ALBUM)))
    out.append(("Seek", (b("TRACKS", "seek", heading="SEEK", title=K.NOW_SONG, meta="of 4:21",
                           buttons=[B("Back", "back"), B("Up next", "expand"), B("Seek", "seek", lit="on"),
                                    B("Skip", "next", enabled=False)],
                           ring={"style": "lap", "value": 0, "index": 97, "count": 261}), K.NOW_ALBUM)))
    out.append(("Up next", (b("TRACKS", "upnext", heading="UP NEXT", title=NEXT_SONG, subtitle=fx.ALBUMS[NEXT_ALBUM][1],
                              meta="6 / 24",
                              buttons=[B("Back", "back"), B("Shuffle", "shuffle", lit="off"), B("Like", "heart"),
                                       B("Play", "play")],
                              ring={"style": "selection", "value": 0, "index": 5, "count": 24, "now": 4, "first": 0,
                                    "colors": [fx.rgb_int(fx.ALBUMS[UPNEXT_ALBUMS[k % len(UPNEXT_ALBUMS)]][3])
                                               for k in range(20)]}), NEXT_ALBUM)))
    app, title, _d, _c, _k = fx.WINDOWS[2]
    out.append(("Windows", (b("WINDOWS", "windows", target="DESKTOP", title=title, subtitle=app, meta="",
                              buttons=[B("Back", "back"), B("Snap left", "snapleft"), B("Snap right", "snapright"),
                                       B("Switch", "switch")],
                              ring={"style": "selection", "value": 0, "index": 2, "count": len(fx.WINDOWS),
                                    "colors": [0 if c == (40, 40, 40) else fx.rgb_int(c)
                                               for _a, _t, _d2, c, _k2 in fx.WINDOWS]}), None)))
    return out


def render(knob_anim, work, out_dir):
    items = screens()
    tl = K.Timeline("stills", duration=len(items) * 1000, preroll=900, fps=1)
    for k, (_cap, fa) in enumerate(items):
        tl.frame(k * 1000 - 900, fa)
    lcds = K.render_lcd(tl, knob_anim, work)
    font = ImageFont.truetype(str(Path(APP_DIR) / "assets" / "fonts" / "Archivo.ttf"), 22)
    try:
        font.set_variation_by_name("Medium")
    except Exception:
        pass
    cell, lcd_px, cols = 300, 256, 4
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cell * cols, (cell + 20) * rows + 20), K.BG)
    d = ImageDraw.Draw(sheet)
    ss = 4
    mask = Image.new("L", (lcd_px * ss,) * 2, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, lcd_px * ss - 1, lcd_px * ss - 1), fill=255)
    mask = mask.resize((lcd_px,) * 2, Image.Resampling.LANCZOS)
    ring = Image.new("L", (lcd_px * ss + 8 * ss,) * 2, 0)
    ImageDraw.Draw(ring).ellipse((0, 0, ring.width - 1, ring.height - 1), outline=255, width=2 * ss)
    ring = ring.resize((lcd_px + 8,) * 2, Image.Resampling.LANCZOS)
    for k, ((cap, _fa), lcd) in enumerate(zip(items, lcds)):
        x = (k % cols) * cell + (cell - lcd_px) // 2
        y = (k // cols) * (cell + 20) + 20
        sheet.paste((44, 45, 50), (x - 4, y - 4), ring)
        sheet.paste(lcd.resize((lcd_px,) * 2, Image.Resampling.LANCZOS), (x, y), mask)
        w = d.textlength(cap, font=font)
        d.text(((k % cols) * cell + (cell - w) / 2, y + lcd_px + 8), cap, font=font, fill=(170, 174, 184))
    path = out_dir / "knob-screens.png"
    sheet.save(path, optimize=True)
    print(f"{path.name}: {sheet.size} {path.stat().st_size // 1024} KB", flush=True)
    (work / "stills.json").write_text(json.dumps([c for c, _ in items]), encoding="utf-8")


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
