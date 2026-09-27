"""Knob animations for the README: the LCD from the firmware's own renderer (knob-anim, lcd/), the
LEDs from the "Warm · alive" engine's Python twin (control_center.alive_lights, the same engine as
the firmware), composited onto a knob drawn after the Knob Face design (60-LED ring, round LCD,
four backlit buttons) with the desktop app's own floating-knob face (control_center.knob_face).

Every scene is a timeline of what happens at the knob -- detents, presses -- and the frames the
companion sends in reply, built with the companion's own frame adapter (device._frame) from the
fictional library in fixtures.py. Nothing talks to a knob, a speaker or the network.
"""
from __future__ import annotations

import json
import math
import subprocess
from copy import deepcopy
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import fixtures as fx
from companion import dev, kf, AliveLights, prepare_artwork2

CAPS = {"controlCenter": 1, "presentation": 5, "glyphs": "latin-ext-a",
        "artwork": {"version": 1, "width": 120, "height": 120, "format": "RGB565_LE", "chunkBytes": 384,
                    "cacheEntries": 8, "available": True, "composited": "scrim80"},
        "artwork2": {"version": 1, "available": True, "composited": "scrim80", "paced": False, "rxBytes": 8192,
                     "chunkBytes": 2048, "haveKeys": 24,
                     "cover": {"width": 240, "height": 240, "format": "JPEG", "maxBytes": 32768, "entries": 24},
                     "icon": {"width": 32, "height": 32, "format": "RGB565_LE", "bytes": 2048, "entries": 48,
                              "background": "black"}},
        "alive": {"version": 1, "fps": 60, "drive": 150}}

# ------------------------------------------------------------------ fictional content (consistent)
NOW_ALBUM, NOW_SONG = 2, "Clearing"            # "Clearing" by North of June, album "Glass Weather"
HOME_BUTTONS = [dict(label="Pause", enabled=True, icon="pause"), dict(label="Browse", enabled=True, icon="list"),
                dict(label="Tracks", enabled=True, icon="tracks"), dict(label="Win", enabled=True, icon="win")]
RECENT_BUTTONS = [dict(label="Back", enabled=True, icon="back"), dict(label="Open", enabled=True, icon="expand"),
                  dict(label="Play next", enabled=True, icon="playnext"), dict(label="Play", enabled=True, icon="play")]
RECENT_TOTAL = 26


def library_colours(count=RECENT_TOTAL):
    """Ring colours in Recently Added order (album accents; items 13 and 26 are playlists)."""
    out = []
    for index in range(count):
        if index % 13 == 12:
            out.append(fx.rgb_int(fx.PLAYLISTS[1 if index == 12 else 0][2]))
        else:
            out.append(fx.rgb_int(fx.ALBUMS[index % len(fx.ALBUMS)][3]))
    return out


_PREPARED = {}


def prepared(album):
    if album not in _PREPARED:
        buf = BytesIO()
        fx.cover(album, 1200).save(buf, "PNG")
        _PREPARED[album] = prepare_artwork2(buf.getvalue())
    return _PREPARED[album]


class Frames:
    """Host frames with increasing ids (the shapes of CONTROL_CENTER_V5 section 5)."""

    def __init__(self):
        self.fid = 0
        self.seq = 0

    def _base(self, mode, layout, **kw):
        self.fid += 1
        f = {"id": self.fid, "mode": mode, "target": fx.ROOM, "value": "", "detail": "", "status": "",
             "layout": layout, "ledStyle": "color"}
        f.update(kw)
        return f

    def home(self, vol, reveal=False, album=NOW_ALBUM, song=NOW_SONG, feedback=None):
        f = self._base("HOME", "volume" if reveal else "nowPlaying", value=f"{vol}%", title=song,
                       subtitle=fx.ALBUMS[album][1], confirmedVolume=vol, restLayout="nowPlaying",
                       volumeCaption=song, volumeVisible=reveal, playing=True, buttons=deepcopy(HOME_BUTTONS),
                       ring={"style": "level", "value": vol, "index": 0, "count": 101})
        if feedback:
            self.seq += 1
            f["feedback"] = dict(feedback, seq=self.seq)
        return f, album

    def recent(self, index):
        a = index % len(fx.ALBUMS)
        first = max(0, min(index - 10, RECENT_TOTAL - 20))
        f = self._base("RECENTLY ADDED", "recent", heading="RECENTLY ADDED", title=fx.ALBUMS[a][0],
                       subtitle=fx.ALBUMS[a][1], meta=f"{index + 1} / {RECENT_TOTAL}",
                       buttons=deepcopy(RECENT_BUTTONS),
                       ring={"style": "selection", "value": 0, "index": index, "count": RECENT_TOTAL, "first": first,
                             "colors": library_colours()[first:first + 20]})
        return f, a

    def explorer(self, index):
        a = index % len(fx.ALBUMS)
        first = max(0, min(index - 10, RECENT_TOTAL - 20))
        f = self._base("RECENTLY ADDED", "explorer", heading="RECENT", page=0, title=fx.ALBUMS[a][0],
                       subtitle=fx.ALBUMS[a][1], meta=f"{index + 1} / {RECENT_TOTAL}",
                       buttons=[dict(label="Back", enabled=True, icon="back"),
                                dict(label="Recent", enabled=True, icon="clock", lit="on"),
                                dict(label="Playlists", enabled=True, icon="playlists", lit="off"),
                                dict(label="Play", enabled=True, icon="play")],
                       ring={"style": "selection", "value": 0, "index": index, "count": RECENT_TOTAL, "first": first,
                             "colors": library_colours()[first:first + 20]})
        return f, a


def wire(frame, album):
    f = deepcopy(frame)
    if album is not None:
        f["artKey"] = prepared(album).jpeg_key
    return dev._frame(f, CAPS)


# ------------------------------------------------------------------ timelines
@dataclass
class Timeline:
    name: str
    duration: int                  # ms of output
    preroll: int = 3000            # ms simulated before the first output frame (LEDs settle, covers decode)
    fps: int = 30
    events: list = field(default_factory=list)   # (t, kind, payload); t relative to the output start

    def frame(self, t, fa):
        self.events.append((t, "frame", fa))

    def detent(self, t, delta=1):
        self.events.append((t, "detent", delta))

    def press(self, t, slot):
        self.events.append((t, "press", slot))

    def sorted(self):
        order = {"detent": 0, "press": 0, "frame": 1}
        return sorted(self.events, key=lambda e: (e[0], order[e[1]]))


def turn(tl, frames, t0, start, stop, every=70, make=None, lag=30):
    """Detents from ``start`` to ``stop`` (inclusive of stop), one every ``every`` ms; the companion's
    frame for each lands ``lag`` ms later. Returns the time after the last detent."""
    step = 1 if stop >= start else -1
    t = t0
    for v in range(start + step, stop + step, step):
        tl.detent(t, step)
        tl.frame(t + lag, make(v))
        t += every
    return t


def scene_hero(F):
    tl = Timeline("hero", duration=9600)
    tl.frame(-2800, F.home(48))
    t = turn(tl, F, 500, 48, 62, every=75, make=lambda v: F.home(v, reveal=True))
    tl.frame(t + 1200, F.home(62))
    t += 1700
    tl.press(t, 1)
    tl.frame(t + 40, F.recent(0))
    t += 900
    for i in (1, 2, 3):
        tl.detent(t, 1)
        tl.frame(t + 30, F.recent(i))
        t += 650
    t += 350
    tl.press(t, 0)
    tl.frame(t + 40, F.home(62))
    t += 900
    t = turn(tl, F, t, 62, 48, every=75, make=lambda v: F.home(v, reveal=True))
    tl.frame(t + 900, F.home(48))
    return tl


def scene_volume(F):
    tl = Timeline("volume", duration=7400)
    tl.frame(-2800, F.home(66))
    t = turn(tl, F, 300, 66, 97, every=85, make=lambda v: F.home(v, reveal=True))
    t += 1300
    t = turn(tl, F, t, 97, 66, every=45, make=lambda v: F.home(v, reveal=True))
    tl.frame(t + 900, F.home(66))
    return tl


def scene_browse(F):
    tl = Timeline("browse", duration=9000)
    tl.frame(-2800, F.recent(0))
    t = 600
    for i in range(1, 7):
        tl.detent(t, 1)
        tl.frame(t + 30, F.recent(i))
        t += 700
    t += 300
    tl.press(t, 3)              # Play: the album starts on Sonos, the ring flashes its colour
    album = 6 % len(fx.ALBUMS)
    tl.frame(t + 60, F.home(48, album=album, song=fx.TRACKS[album][0],
                            feedback={"kind": "ok", "moment": "started", "color": fx.rgb_int(fx.ALBUMS[album][3])}))
    t += 2000
    tl.press(t, 1)
    tl.frame(t + 40, F.recent(6))
    t += 500
    t = turn(tl, F, t, 6, 0, every=110, make=F.recent)
    return tl


def scene_wake(F):
    """Resting (steady dim warm white) -> a touch wakes it (brighter warm white, the volume arc and
    the volume reveal) -> 5 s without input: back to the steady warm rest."""
    tl = Timeline("wake", duration=9400, preroll=7000, fps=30)
    tl.frame(-7000, F.home(48))
    t = turn(tl, F, 1200, 48, 53, every=140, make=lambda v: F.home(v, reveal=True))
    tl.frame(t + 1100, F.home(53))
    return tl


SCENES = {"hero": scene_hero, "volume": scene_volume, "browse": scene_browse, "wake": scene_wake}


# ------------------------------------------------------------------ LCD: the firmware renderer
def render_lcd(tl, knob_anim, work):
    covers = {}
    steps = []
    for t, kind, payload in tl.sorted():
        if kind != "frame":
            continue
        frame, album = payload
        w = wire(frame, album)
        if album is not None:
            p = prepared(album)
            path = work / "covers" / f"{p.jpeg_key}.jpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(p.jpeg)
            covers[p.jpeg_key] = str(path)
        steps.append({"at": t + tl.preroll, "frame": w})
    script = {"fps": tl.fps, "duration_ms": tl.duration, "start_ms": tl.preroll, "covers": covers, "icons": {},
              "steps": steps}
    sp = work / f"{tl.name}.script.json"
    sp.write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    raw = work / f"{tl.name}.rgb"
    subprocess.run([str(knob_anim), str(sp), str(raw)], check=True)
    data = raw.read_bytes()
    n = len(data) // (240 * 240 * 3)
    return [Image.frombytes("RGB", (240, 240), data[k * 172800:(k + 1) * 172800]) for k in range(n)]


def capture_times(tl):
    """Output frame k is captured at the first whole ms at or after k * 1000 / fps (as knob-anim)."""
    return [math.ceil(k * 1000 / tl.fps) for k in range(math.ceil(tl.duration * tl.fps / 1000))]


# ------------------------------------------------------------------ LEDs: the alive engine
def render_leds(tl):
    """(ring e x60, buttons e x4) per output frame; the engine runs at 60 Hz like the knob's."""
    lights = AliveLights(0)
    lights.claim(0)
    events = [(t + tl.preroll, k, p) for t, k, p in tl.sorted()]
    caps = [tl.preroll + c for c in capture_times(tl)]
    ticks = sorted(set([round(j * 1000 / 60) for j in range(int((caps[-1] + 1) * 60 / 1000) + 2)] + caps))
    frame = None
    ei = 0
    out = {}
    capset = set(caps)
    for now in ticks:
        while ei < len(events) and events[ei][0] <= now:
            t, kind, payload = events[ei]
            if kind == "frame":
                frame = wire(*payload)
            elif kind == "detent":
                lights.detent(t, payload)
            elif kind == "press":
                lights.press(t, payload)
            ei += 1
        ring, buttons = lights.render(now, frame)
        if now in capset:
            out[now] = (list(ring), list(buttons))
    return [out[c] for c in caps]


# ------------------------------------------------------------------ composition
BG = (13, 14, 17)
BODY_TOP, BODY_BOTTOM = (30, 31, 34), (20, 21, 23)


class KnobDevice:
    """The knob drawn after the Knob Face design (340 x 400 design px: ring centre 170,170, four
    44 px buttons at y 336), with the desktop app's AliveFace for the ring, glow and LCD."""

    def __init__(self, scale=1.5, margin=20, buttons=True, crop_ring=False):
        self.s = s = scale
        self.face = kf.AliveFace(s)
        self.buttons = buttons
        self.crop_ring = crop_ring
        if crop_ring:
            half = 180
            self.size = (round(2 * half * s), round(2 * half * s))
            self.centre = (self.size[0] / 2, self.size[1] / 2)
        else:
            self.size = (round((340 + 2 * margin) * s), round((400 + 2 * margin) * s))
            self.centre = ((170 + margin) * s, (170 + margin) * s)
        self.margin = margin
        self.base = self._base()
        self.lcd_px = self.face.lcd_px
        ss = 4
        m = Image.new("L", (self.lcd_px * ss,) * 2, 0)
        ImageDraw.Draw(m).ellipse((0, 0, self.lcd_px * ss - 1, self.lcd_px * ss - 1), fill=255)
        self.lcd_mask = m.resize((self.lcd_px,) * 2, Image.Resampling.LANCZOS)
        self._btn = self._button_sprites() if buttons and not crop_ring else None

    def _base(self):
        s = self.s
        img = Image.new("RGB", self.size, BG)
        if self.crop_ring:
            return img
        W, H = self.size
        m = self.margin * s
        ss = 3
        body = Image.linear_gradient("L").resize((W, H))
        body = Image.composite(Image.new("RGB", (W, H), BODY_BOTTOM), Image.new("RGB", (W, H), BODY_TOP), body)
        mask = Image.new("L", (W * ss, H * ss), 0)
        ImageDraw.Draw(mask).rounded_rectangle((m * ss, m * ss, (W - m) * ss, (H - m) * ss), radius=34 * s * ss, fill=255)
        mask = mask.resize((W, H), Image.Resampling.LANCZOS)
        sh = mask.filter(ImageFilter.GaussianBlur(8 * s)).point(lambda v: v * 150 // 255)
        img.paste((0, 0, 0), (0, round(5 * s)), sh)
        img.paste(body, (0, 0), mask)
        edge = Image.new("L", (W * ss, H * ss), 0)
        d = ImageDraw.Draw(edge)
        d.rounded_rectangle((m * ss, m * ss, (W - m) * ss, (H - m) * ss), radius=34 * s * ss, outline=70, width=int(1.2 * s * ss))
        edge = edge.resize((W, H), Image.Resampling.LANCZOS)
        img.paste((120, 122, 128), (0, 0), edge)
        return img

    def _button_rects(self):
        s, m = self.s, self.margin
        return [((m + 49 + k * 66) * s, (m + 336) * s, (m + 49 + k * 66 + 44) * s, (m + 336 + 44) * s) for k in range(4)]

    def _button_sprites(self):
        s = self.s
        W, H = self.size
        rects = self._button_rects()
        ss = 3
        caps = Image.new("L", (W * ss, H * ss), 0)
        d = ImageDraw.Draw(caps)
        for x0, y0, x1, y1 in rects:
            d.rounded_rectangle((x0 * ss, y0 * ss, x1 * ss, y1 * ss), radius=5 * s * ss, fill=255)
        caps = caps.resize((W, H), Image.Resampling.LANCZOS)
        strips, glows = [], []
        for x0, y0, x1, y1 in rects:
            st = Image.new("L", (W * ss, H * ss), 0)
            ImageDraw.Draw(st).rounded_rectangle((x0 * ss, (y1 - 3.2 * s) * ss, x1 * ss, y1 * ss), radius=1.5 * s * ss, fill=255)
            st = st.resize((W, H), Image.Resampling.LANCZOS)
            box = (int(x0 - 24 * s), int(y0 - 10 * s), int(x1 + 24 * s), int(y1 + 24 * s))
            strips.append((box, st.crop(box)))
            glows.append((box, st.crop(box).filter(ImageFilter.GaussianBlur(5 * s))))
        return caps, strips, glows

    def compose(self, lcd_rgb, ring, buttons):
        img = self.base.copy()
        lcd = lcd_rgb.resize((self.lcd_px,) * 2, Image.Resampling.LANCZOS).convert("RGBA")
        lcd.putalpha(self.lcd_mask)
        face = self.face.compose(lcd, ring)
        cx, cy = self.centre
        fx0, fy0 = round(cx - self.face.origin[0]), round(cy - self.face.origin[1])
        img.paste(face, (fx0, fy0), face)
        if self._btn:
            caps, strips, glows = self._btn
            img.paste((34, 35, 38), (0, 0), caps)
            for j, e in enumerate(buttons[:4]):
                fill, look, tint = kf.segment_look(e)
                (box, st), (_b, gl) = strips[j], glows[j]
                region = img.crop(box)
                if look >= 0:
                    a = min(1.0, 1.25 * max(e))
                    region.paste(tint, (0, 0), gl.point(lambda v, a=a: int(v * a)))
                region.paste(fill, (0, 0), st)
                img.paste(region, box[:2])
        return img


# ------------------------------------------------------------------ encoding
GIF_BUDGET = 2_900_000


def _gif(frames, fps, path, scale, step, colors):
    if scale != 1.0:
        w, h = frames[0].size
        size = (round(w * scale / 2) * 2, round(h * scale / 2) * 2)
        frames = [f.resize(size, Image.Resampling.LANCZOS) for f in frames]
    frames = frames[::step]
    sample = [frames[k] for k in range(0, len(frames), max(1, len(frames) // 12))]
    w, h = frames[0].size
    sheet = Image.new("RGB", (w, h * len(sample)))
    for k, f in enumerate(sample):
        sheet.paste(f, (0, h * k))
    pal = sheet.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    q[0].save(path, save_all=True, append_images=q[1:], duration=round(1000 * step / fps), loop=0,
              optimize=False, disposal=1)
    return path.stat().st_size


def save_animation(frames, fps, stem, out_dir, colors=192):
    """Animated WebP at full size and frame rate (what the README shows), plus a GIF fallback
    (global adaptive palette, no dither: stable frames, small deltas) shrunk until it fits
    GIF_BUDGET: first fewer frames per second, then smaller."""
    dur = round(1000 / fps)
    webp = out_dir / f"{stem}.webp"
    frames[0].save(webp, save_all=True, append_images=frames[1:], duration=dur, loop=0, quality=82, method=5)
    gif = out_dir / f"{stem}.gif"
    for scale, step in ((1.0, 1), (1.0, 2), (0.85, 2), (0.75, 2), (0.66, 2), (0.6, 3), (0.5, 3)):
        if _gif(frames, fps, gif, scale, step, colors) <= GIF_BUDGET:
            break
    return gif, webp
