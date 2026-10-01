"""Synthetic, fictional data for the Desk Dial README media.

Every title, artist, playlist and window below is invented for these images. Every cover is drawn
procedurally here (no real album art, no real screenshots)."""
from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw, ImageFilter

# (album, artist, year, accent rgb, cover style)
ALBUMS = [
    ("Slow Orbit", "Mira Vale", 2024, (120, 150, 255), "orbit"),
    ("Neon Littoral", "Lumen Park", 2023, (255, 60, 140), "waves"),
    ("Glass Weather", "North of June", 2022, (60, 200, 230), "grid"),
    ("Copper Sun Sessions", "Ana Ribeira", 2021, (255, 150, 50), "sun"),
    ("Paper Lanterns", "The Quiet Harbour", 2020, (255, 200, 90), "lanterns"),
    ("Midnight Arcade", "Velvet Circuit", 2019, (170, 90, 255), "stripes"),
    ("Field Notes No. 3", "Oskar Lind Trio", 2018, (80, 210, 150), "blobs"),
    ("Salt & Static", "The Low Hours", 2025, (240, 90, 70), "rings"),
    ("Tidal Glass", "Kaori Sands", 2017, (70, 140, 255), "dunes"),
]
TRACKS = [
    ["First Light", "Perihelion", "Slow Orbit", "Weightless Hour", "Blue Shift", "Satellite Hearts",
     "Night Side", "Return Window", "Afterburn"],
    ["Low Tide Neon", "Harbour Signals", "Palm Static", "Sodium Coast", "Low Harbour", "Glass Pier"],
    ["Pressure Front", "Glass Weather", "Rain on Aluminium", "Fog Index", "Clearing", "Barometer",
     "Soft Front", "Isobars", "Blue Hour", "Long Range"],
    ["Copper Sun", "Varanda", "Maré Alta", "Cidade Lenta", "Laranja", "Samba de Sal", "Poente",
     "Beira-Mar"],
    ["Lantern Light", "Harbour Song", "Paper Boats", "Evening Ferry", "Rope & Anchor", "Low Lamps",
     "The Long Pier", "Dockside Waltz", "Lanterns Out", "Harbour Mist", "Salt Wind", "Home Port"],
    ["Insert Coin", "High Score", "Pixel Rain", "Arcade Lights", "Continue?", "Level Nine",
     "Game Over Waltz", "Last Credit"],
    ["Birch", "Notebook", "Early Frost", "Field Recording", "Meadow Line", "Kettle", "Lantern",
     "Evening Notes"],
    ["Salt & Static", "Radio Silence", "Long Wave", "Sea Crackle", "Tuning Fork", "Night Channel"],
    ["Tidal Glass", "Sand Script", "Shore Break", "Moonpull", "Drift", "Estuary", "Glass Floats"],
]
PLAYLISTS = [  # (title, album indexes, colour, length)
    ("Favourite Songs", [4, 1, 2, 3], (255, 70, 90), 42),
    ("Evening Wind-Down", [4, 6, 8, 0], (255, 170, 80), 36),
    ("Deep Work", [0, 2, 6, 8], (90, 150, 255), 27),
    ("Sunday Kitchen", [3, 4, 6, 1], (255, 190, 90), 52),
    ("Road Trip Mix", [1, 5, 7, 3], (255, 60, 110), 61),
    ("Rainy Day Jazz", [6, 2, 8, 0], (80, 200, 170), 22),
]
# (app, title, description, accent rgb, thumbnail kind). Every app name is invented (no real product
# names, no real logos: the picker draws a letter tile or a synthetic icon); titles are generic.
WINDOWS = [
    ("Ledger", "dial_ui.py · Desk Dial", "Editor", (0, 122, 204), "code"),
    ("Draft", "Weather · 7-day forecast", "Browser tab", (255, 200, 40), "web"),
    ("Canvas", "Dial faceplate · v4", "Design file", (162, 89, 255), "design"),
    ("Chatter", "#hardware", "Channel", (230, 50, 200), "chat"),
    ("Notes", "Release checklist", "Workspace page", (230, 230, 230), "doc"),
    ("Shell", "Session 1", "Terminal", (40, 40, 40), "term"),
    ("Files", "Downloads", "Folder", (255, 190, 60), "files"),
    ("Grid", "Budget 2026", "Workbook", (30, 160, 90), "sheet"),
]
ROOM = "Living Room"


def rgb_int(c):
    return (c[0] << 16) | (c[1] << 8) | c[2]


def _mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _vgrad(size, top, bottom, angle=0):
    w, h = size
    g = Image.linear_gradient("L").resize((max(w, h) * 2, max(w, h) * 2))
    if angle:
        g = g.rotate(angle, resample=Image.Resampling.BICUBIC)
    g = g.crop(((g.width - w) // 2, (g.height - h) // 2, (g.width - w) // 2 + w, (g.height - h) // 2 + h))
    return Image.composite(Image.new("RGB", size, bottom), Image.new("RGB", size, top), g)


def _dark(c, f):
    return tuple(max(0, min(255, round(v * f))) for v in c)


def _light(c, f):
    return tuple(max(0, min(255, round(v + (255 - v) * f))) for v in c)


def cover(index, size=1200):
    """A procedural, text-free abstract cover for fictional album ``index``."""
    title, artist, _year, accent, style = ALBUMS[index]
    rnd = random.Random(title)
    ss = 2
    S = size * ss
    deep = _dark(accent, 0.22)
    mid = _dark(accent, 0.6)
    img = _vgrad((S, S), _light(mid, 0.1), deep, angle=rnd.choice((0, 20, -20, 160)))
    d = ImageDraw.Draw(img, "RGBA")
    if style == "orbit":
        cx, cy = S * 0.5, S * 0.56
        for k in range(9, 0, -1):
            r = S * 0.06 * k
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=_light(accent, 0.3) + (40 + 12 * (9 - k),), width=max(2, S // 300))
        r = S * 0.13
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=_light(accent, 0.55) + (255,))
        a = math.radians(-35)
        px, py = cx + math.cos(a) * S * 0.36, cy + math.sin(a) * S * 0.36
        r = S * 0.035
        d.ellipse((px - r, py - r, px + r, py + r), fill=(255, 255, 255, 235))
    elif style == "waves":
        img = _vgrad((S, S), (18, 10, 40), (60, 12, 60))
        d = ImageDraw.Draw(img, "RGBA")
        for k in range(14):
            y0 = S * (0.30 + k * 0.05)
            col = _mix(accent, (80, 220, 255), k / 13) + (200,)
            pts = [(x, y0 + math.sin(x / S * 2 * math.pi * 1.5 + k * 0.5) * S * 0.035) for x in range(0, S + 8, 8)]
            d.line(pts, fill=col, width=max(3, S // 160))
        r = S * 0.11
        d.ellipse((S * 0.68 - r, S * 0.2 - r, S * 0.68 + r, S * 0.2 + r), fill=_light(accent, 0.2) + (255,))
    elif style == "grid":
        img = _vgrad((S, S), (220, 236, 240), (150, 190, 205))
        d = ImageDraw.Draw(img, "RGBA")
        n = 6
        cell = S / n
        for i in range(n):
            for j in range(n):
                v = rnd.random()
                x0, y0 = i * cell + cell * 0.1, j * cell + cell * 0.1
                x1, y1 = x0 + cell * 0.8, y0 + cell * 0.8
                if v < 0.35:
                    d.rounded_rectangle((x0, y0, x1, y1), radius=cell * 0.18, fill=accent + (int(90 + 150 * rnd.random()),))
                elif v < 0.6:
                    d.ellipse((x0, y0, x1, y1), fill=(30, 60, 80, int(60 + 120 * rnd.random())))
                else:
                    d.rounded_rectangle((x0, y0, x1, y1), radius=cell * 0.18, outline=(30, 60, 80, 90), width=max(2, S // 400))
    elif style == "sun":
        img = _vgrad((S, S), (255, 196, 90), (170, 40, 60))
        d = ImageDraw.Draw(img, "RGBA")
        r = S * 0.24
        cx, cy = S * 0.5, S * 0.58
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 236, 170, 255))
        for k in range(7):
            y = cy + r * (0.1 + k * 0.14)
            d.rectangle((0, y, S, y + S * (0.008 + k * 0.004)), fill=(190, 60, 60, 255))
        d.rectangle((0, S * 0.8, S, S), fill=(120, 30, 55, 255))
    elif style == "lanterns":
        img = _vgrad((S, S), (30, 26, 60), (10, 8, 22))
        d = ImageDraw.Draw(img, "RGBA")
        for k in range(11):
            x = S * (0.1 + 0.8 * rnd.random())
            y = S * (0.15 + 0.7 * rnd.random())
            r = S * (0.03 + 0.05 * rnd.random())
            glow = Image.new("L", (S, S), 0)
            ImageDraw.Draw(glow).ellipse((x - r * 2.2, y - r * 2.2, x + r * 2.2, y + r * 2.2), fill=120)
            glow = glow.filter(ImageFilter.GaussianBlur(r * 0.9))
            img.paste(Image.new("RGB", (S, S), (255, 170, 70)), (0, 0), glow)
            d = ImageDraw.Draw(img, "RGBA")
            d.rounded_rectangle((x - r * 0.7, y - r, x + r * 0.7, y + r), radius=r * 0.5, fill=(255, 214, 130, 255))
    elif style == "stripes":
        img = _vgrad((S, S), (40, 16, 80), (10, 6, 28))
        d = ImageDraw.Draw(img, "RGBA")
        cols = [(255, 60, 160), (170, 90, 255), (60, 200, 255), (255, 200, 60)]
        for k in range(4):
            off = S * (0.1 + k * 0.1)
            d.polygon([(off, S), (off + S * 0.07, S), (S, off + S * 0.07 - S * 0.0), (S, off)], fill=cols[k] + (230,))
        for k in range(18):
            y = S * 0.08 + k * S * 0.03
            d.line((S * 0.08, y, S * 0.08 + S * 0.25 * (0.3 + 0.7 * rnd.random()), y), fill=(255, 255, 255, 60), width=max(2, S // 300))
    elif style == "blobs":
        img = Image.new("RGB", (S, S), (232, 238, 226))
        for col, (x, y, r) in zip([(80, 210, 150), (250, 200, 90), (70, 140, 200), (240, 120, 90)],
                                  [(0.3, 0.35, 0.28), (0.7, 0.3, 0.22), (0.6, 0.72, 0.3), (0.25, 0.78, 0.18)]):
            m = Image.new("L", (S, S), 0)
            ImageDraw.Draw(m).ellipse(((x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S), fill=200)
            m = m.filter(ImageFilter.GaussianBlur(S * 0.02))
            img.paste(Image.new("RGB", (S, S), col), (0, 0), m)
        d = ImageDraw.Draw(img, "RGBA")
        for k in range(5):
            y = S * (0.12 + k * 0.035)
            d.line((S * 0.62, y, S * 0.9, y), fill=(30, 40, 30, 120), width=max(2, S // 350))
    elif style == "rings":
        img = _vgrad((S, S), (30, 30, 34), (12, 12, 14))
        d = ImageDraw.Draw(img, "RGBA")
        cx, cy = S * 0.5, S * 0.5
        for k in range(22):
            r = S * (0.04 + k * 0.02)
            a0 = rnd.randrange(0, 360)
            d.arc((cx - r, cy - r, cx + r, cy + r), a0, a0 + rnd.randrange(60, 300),
                  fill=_mix(accent, (240, 240, 240), k / 22) + (220,), width=max(3, S // 220))
    elif style == "dunes":
        img = _vgrad((S, S), (180, 215, 255), (240, 220, 200))
        d = ImageDraw.Draw(img, "RGBA")
        for k in range(6):
            base = S * (0.45 + k * 0.1)
            col = _mix((70, 140, 255), (20, 40, 90), k / 5) + (255,)
            pts = [(0, S)] + [(x, base + math.sin(x / S * math.pi * (1.2 + k * 0.3) + k) * S * 0.05)
                              for x in range(0, S + 8, 8)] + [(S, S)]
            d.polygon(pts, fill=col)
        r = S * 0.07
        d.ellipse((S * 0.25 - r, S * 0.22 - r, S * 0.25 + r, S * 0.22 + r), fill=(255, 250, 235, 255))
    img = img.filter(ImageFilter.GaussianBlur(ss * 0.6))
    noise = Image.effect_noise((S // 4, S // 4), 18).resize((S, S)).convert("RGB")
    img = Image.blend(img, noise, 0.035)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def wallpaper(size, seed=3):
    """A synthetic desktop wallpaper (soft colour fields), no real content."""
    w, h = size
    img = _vgrad((w, h), (22, 30, 58), (58, 30, 70), angle=15)
    for col, (x, y, r) in [((230, 110, 70), (0.18, 0.25, 0.35)), ((60, 140, 255), (0.8, 0.7, 0.45)),
                           ((180, 80, 220), (0.55, 0.1, 0.3)), ((40, 200, 180), (0.35, 0.95, 0.3))]:
        m = Image.new("L", (w // 8, h // 8), 0)
        ImageDraw.Draw(m).ellipse(((x - r) * w / 8, (y - r) * w / 8, (x + r) * w / 8, (y + r) * w / 8), fill=150)
        m = m.filter(ImageFilter.GaussianBlur(w / 8 * 0.08)).resize((w, h), Image.Resampling.BILINEAR)
        img.paste(Image.new("RGB", (w, h), col), (0, 0), m)
    return img


DESKTOP_WINDOWS = [(0.06, 0.1, 0.42, 0.62, 0), (0.46, 0.18, 0.9, 0.8, 1), (0.2, 0.55, 0.55, 0.92, 4)]


def desktop(size, rects=DESKTOP_WINDOWS):
    """Wallpaper plus a few synthetic application windows (what a frost would blur)."""
    img = wallpaper(size)
    w, h = size
    for x0, y0, x1, y1, k in rects:
        box = (int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h))
        thumb = window_thumb(k, (box[2] - box[0], box[3] - box[1]))
        img.paste(thumb, box[:2])
    return img


def window_thumb(index, size):
    """A synthetic application window (title bar plus placeholder UI blocks, no real content)."""
    app, title, _desc, accent, kind = WINDOWS[index % len(WINDOWS)]
    w, h = max(8, int(size[0])), max(8, int(size[1]))
    dark = kind in ("code", "term", "chat")
    bg = (30, 32, 38) if dark else (246, 247, 250)
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    bar = max(3, h // 14)
    d.rectangle((0, 0, w, bar), fill=(44, 46, 54) if dark else (226, 229, 236))
    ink = (200, 204, 214) if dark else (60, 64, 76)
    g = max(1, bar // 4)                     # Windows caption buttons: minimise, maximise, close
    lw = max(1, bar // 14)
    for k in range(3):
        cx, cy = w - bar * (0.9 + k * 1.5), bar / 2
        if k == 0:
            d.line((cx - g, cy - g, cx + g, cy + g), fill=ink, width=lw)
            d.line((cx - g, cy + g, cx + g, cy - g), fill=ink, width=lw)
        elif k == 1:
            d.rectangle((cx - g, cy - g, cx + g, cy + g), outline=ink, width=lw)
        else:
            d.line((cx - g, cy, cx + g, cy), fill=ink, width=lw)
    faint = (90, 96, 110) if dark else (200, 204, 214)
    rnd = random.Random(title)
    lh = max(2, h // 26)
    if kind == "code":
        d.rectangle((0, bar, w // 6, h), fill=(37, 39, 46))
        for i in range(24):
            y = bar + lh * 1.2 + i * lh * 1.5
            if y > h - lh:
                break
            indent = w // 6 + lh * 2 + (rnd.randrange(0, 4) * lh * 1.5)
            cols = [(86, 156, 214), (206, 145, 120), (78, 201, 176), (220, 220, 170), (156, 220, 254)]
            x = indent
            for _ in range(rnd.randrange(1, 4)):
                ln = rnd.randrange(lh * 2, lh * 8)
                d.rectangle((x, y, x + ln, y + lh * 0.7), fill=rnd.choice(cols))
                x += ln + lh
    elif kind == "term":
        for i in range(18):
            y = bar + lh + i * lh * 1.5
            if y > h - lh:
                break
            d.rectangle((lh, y, lh + rnd.randrange(lh * 4, int(w * 0.7)), y + lh * 0.7),
                        fill=(120, 220, 140) if i % 5 == 0 else (190, 190, 190))
    elif kind in ("web", "doc", "design", "files", "sheet"):
        if kind == "web":
            d.rectangle((0, bar, w, bar + lh * 2), fill=(236, 238, 242))
            d.rounded_rectangle((w * 0.2, bar + lh * 0.4, w * 0.8, bar + lh * 1.6), radius=lh, fill=(255, 255, 255))
            top = bar + lh * 3
            d.rectangle((w * 0.08, top, w * 0.92, top + h * 0.28), fill=(90, 150, 230))
            for i in range(7):
                x0 = w * 0.08 + i * w * 0.12
                d.rounded_rectangle((x0, top + h * 0.32, x0 + w * 0.1, top + h * 0.5), radius=lh // 2,
                                    fill=(255, 210, 90) if i % 3 else (120, 170, 240))
        elif kind == "design":
            d.rectangle((0, bar, w * 0.16, h), fill=(236, 236, 240))
            d.rectangle((w * 0.84, bar, w, h), fill=(236, 236, 240))
            cx, cy, r = w * 0.5, (h + bar) / 2, min(w * 0.26, h * 0.34)
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(20, 20, 22))
            r2 = r * 0.82
            d.ellipse((cx - r2, cy - r2, cx + r2, cy + r2), fill=(8, 8, 10))
            for k in range(60):
                a = math.radians(k * 6 - 90)
                x, y = cx + math.cos(a) * r * 0.91, cy + math.sin(a) * r * 0.91
                d.ellipse((x - 1.5, y - 1.5, x + 1.5, y + 1.5), fill=(255, 132, 36) if k < 32 else (60, 60, 60))
        elif kind == "sheet":
            cw, ch = max(4, w // 10), max(3, lh * 1.4)
            for i in range(11):
                d.line((i * cw, bar + lh, i * cw, h), fill=(210, 214, 220))
            for j in range(40):
                y = bar + lh + j * ch
                if y > h:
                    break
                d.line((0, y, w, y), fill=(210, 214, 220))
            d.rectangle((0, bar, w, bar + lh), fill=(30, 160, 90))
        else:
            for i in range(20):
                y = bar + lh * 2 + i * lh * 1.6
                if y > h - lh:
                    break
                d.rectangle((w * 0.1, y, w * 0.1 + rnd.randrange(int(w * 0.3), int(w * 0.8)), y + lh * 0.7), fill=faint)
    elif kind == "chat":
        d.rectangle((0, bar, w * 0.22, h), fill=(63, 14, 64))
        for i in range(10):
            y = bar + lh * 2 + i * lh * 2.6
            if y > h - lh * 2:
                break
            d.rounded_rectangle((w * 0.26, y, w * 0.26 + lh * 1.6, y + lh * 1.6), radius=lh // 2, fill=rnd.choice(
                [(230, 110, 70), (60, 140, 255), (40, 200, 180)]))
            d.rectangle((w * 0.26 + lh * 2.4, y + lh * 0.2, w * 0.26 + lh * 2.4 + rnd.randrange(int(w * 0.2), int(w * 0.6)),
                         y + lh * 0.8), fill=ink)
    return img
