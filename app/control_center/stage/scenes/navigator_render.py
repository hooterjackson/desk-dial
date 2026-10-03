"""Headless renders of the r3 Navigator (DESKTOP_STAGE section 24.8): the engine on the recording fake
device, a fake host, a synchronous backdrop capture of a synthetic desktop, and the PIL reference
renderer (``render_music.ReferenceRenderer`` plus the static rectangle clips the Navigator uses).
Nothing here touches a window, the GPU or the screen.

    .venv\\Scripts\\python.exe -I control_center\\stage\\scenes\\navigator_render.py [--out DIR] [--sheet PNG]

writes one PNG per design state (``design_states``) and the contact sheet (by default
``design-reference\\r3-navigator-sheet.png``), with the prototype's own rendering of each state beside
ours when ``design-reference\\r3-navigator-prototype`` holds them (made by that folder's
``make_prototype_reference.py``: the prototype's own Navigator markup (P L79-170) filled per state,
rendered offscreen by headless Chrome at device scale 2 over the same desktop).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    __package__ = "control_center.stage.scenes"

from PIL import Image, ImageDraw, ImageFilter

from ... import navigator_model as NM
from ... import render_music as RM
from .. import clock as CK
from .. import fake as F
from . import navigator as NS

MONITOR = (0, 0, 5120, 1440)
WORK = (0, 0, 5120, 1344)            # the prototype's 48-unit taskbar (96 px at k = 2) below the work area
ROOT = Path(__file__).resolve().parents[3]


class KeepingDevice(F.FakeDevice):
    """The fake device keeping every surface's BGRA bytes for the reference renderer."""

    def upload(self, surface, w, h, data, name=""):
        super().upload(surface, w, h, data, name)
        self.objects[surface]["pixels"] = bytes(data)
        self.objects[surface].pop("_sprite", None)


class NavReference(RM.ReferenceRenderer):
    """``ReferenceRenderer`` with static rectangle clips (``Visual.SetClip.rect``) in the visual's own
    space (after its offset), as DirectComposition applies them."""

    def _draw(self, v, parent, mult, target, t, mode):
        o = self.dev.objects[v]
        clip = o.get("props", {}).get("clip")
        if not (isinstance(clip, tuple) and clip and clip[0] == "rect"):
            return super()._draw(v, parent, mult, target, t, mode)
        layer = RM._Canvas(target.size, None)
        RM.ReferenceRenderer._draw(self, v, parent, mult, layer, t, mode)
        ox = float(self.value(v, "offset_x", t, 0.0))
        oy = float(self.value(v, "offset_y", t, 0.0))
        m = RM._mul(parent, (1.0, 0.0, 0.0, 1.0, ox, oy))
        l, tp, r, b = clip[1]
        x0, y0 = RM._apply(m, l, tp)
        x1, y1 = RM._apply(m, r, b)
        w, h = target.size
        box = (max(0, int(round(min(x0, x1)))), max(0, int(round(min(y0, y1)))),
               min(w, int(round(max(x0, x1)))), min(h, int(round(max(y0, y1)))))
        mask = Image.new("L", target.size, 0)
        if box[2] > box[0] and box[3] > box[1]:
            mask.paste(255, box)
        layer.a = Image.composite(layer.a, Image.new("L", target.size, 0), mask)
        layer.pm = Image.composite(layer.pm, Image.new("RGB", target.size, (0, 0, 0)), mask)
        RM._over(target, layer.pm, layer.a, (0, 0), 1.0)


# --------------------------------------------------------------------------- the synthetic desktop
def covers_dir():
    for d in (ROOT / "design-reference" / "design_handoff_nano_d_master_r2.2" / "prototypes" / "assets" / "covers",):
        if d.is_dir():
            return d
    return None


def cover(name):
    d = covers_dir()
    if d is None:
        return None
    for ext in (".png", ".jpg"):
        p = d / (name + ext)
        if p.exists():
            with Image.open(p) as im:
                return im.convert("RGB")
    return None


def desktop_image(size=(1380, 1344)):
    """A deterministic desktop behind the card: a warm-to-teal wallpaper with two app windows and a
    cover poster, so the glass's blur, saturation and rim read the way they do on a real desktop."""
    w, h = size
    g = Image.linear_gradient("L").resize((w, h))
    top, bottom = Image.new("RGB", (w, h), (46, 72, 110)), Image.new("RGB", (w, h), (186, 104, 70))
    img = Image.composite(bottom, top, g)
    d = ImageDraw.Draw(img)
    d.ellipse((-200, 240, 700, 1100), fill=(214, 150, 70))
    d.rectangle((300, 120, 1320, 700), fill=(240, 240, 244))
    d.rectangle((300, 120, 1320, 170), fill=(34, 38, 48))
    for i in range(9):
        d.rectangle((340, 210 + i * 50, 1100 - i * 40, 236 + i * 50), fill=(120 + i * 10, 130, 160))
    d.rectangle((60, 820, 960, 1300), fill=(24, 26, 32))
    d.rectangle((60, 820, 960, 866), fill=(60, 64, 76))
    for i in range(8):
        d.rectangle((100, 900 + i * 46, 900 - (i % 3) * 120, 922 + i * 46), fill=(90, 200 - i * 12, 140))
    art = cover("moon-safari")
    if art is not None:
        img.paste(art.resize((360, 360)), (720, 760))
    return img.filter(ImageFilter.GaussianBlur(0.6))


# --------------------------------------------------------------------------- the engine on fakes
class HeadlessNavigator:
    """``navigator_engine.NavigatorEngine`` on the fake device, host and clock, with a
    synchronous capture of ``desktop``. ``post(content, visible=True, art=...)`` then ``advance(ms)``;
    ``render(at_ms)`` returns the host column (RGB over the desktop, or RGBA with ``transparent``)."""

    def __init__(self, desktop=None, *, work=WORK, monitor=MONITOR, reduced=False):
        from .navigator_engine import CaptureWorker, NavigatorEngine
        self.clk = F.FakeClock(hz=240.0)
        self.desktop = desktop if desktop is not None else desktop_image()
        self.devices = []
        self.reduced = reduced

        def device_factory(_mon):
            d = KeepingDevice(self.clk)
            self.devices.append(d)
            return d

        def grab(rect):
            x, y, w, h = rect
            return self.desktop.crop((x, y, x + w, y + h)).convert("RGB")

        self.engine = NavigatorEngine(
            device_factory=device_factory, host_factory=lambda handler: F.FakeHost(handler),
            clock_factory=lambda d: CK.StageClock(d.time_frequency, d.time_frequency, qpc=self.clk, perf=self.clk.perf),
            monitor_for=lambda: {"rect": monitor, "work": work},
            capture_factory=lambda cb: CaptureWorker(cb, grab=grab, affinity=lambda h, on: True, sync=True),
            monotonic=self.clk.perf)
        self.engine.start()

    @property
    def dev(self):
        return self.devices[-1]

    def post(self, content, *, visible=True, art=None, eligible=True):
        self.engine.post({"content": content, "visible": visible, "eligible": eligible, "reduced": self.reduced,
                          "art": art or {}})
        self.engine.process()

    def advance(self, ms):
        end = self.clk.t + int(round(ms * self.clk.freq / 1000.0))
        while self.clk.t < end:
            w = self.engine.process()
            step = int(round((w if w is not None else 1.0) * self.clk.freq)) if w else int(self.clk.freq / 240)
            self.clk.t = min(end, self.clk.t + max(1, step))
        self.engine.process()

    def render(self, at_ms=0.0, *, transparent=False):
        eng = self.engine
        t = self.clk.t + int(round(at_ms * self.clk.freq / 1000.0))
        x, y, w, h = eng.geometry.host
        r = NavReference(self.dev, self.clk.freq)
        canvas = RM._Canvas((w, h), None)
        r._draw(eng.root.ptr, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), 1.0, canvas, t, 0)
        if transparent:
            out = canvas.pm.convert("RGBA")
            out.putalpha(canvas.a)
            return out
        from PIL import ImageChops
        inv = canvas.a.point(lambda v: 255 - v)
        dst = ImageChops.multiply(self.desktop.crop((x, y, x + w, y + h)).convert("RGB"),
                                  Image.merge("RGB", (inv, inv, inv)))
        return ImageChops.add(dst, canvas.pm)               # premultiplied over the desktop

    def card_box(self):
        """The card's rest rect in host px (x0, y0, x1, y1), with a margin for the shadow."""
        c = self.engine.state["content"]
        g = self.engine.geometry
        geo = c.geometry() if hasattr(c, "geometry") else c.kind   # r3.1: the Lights card's area block
        x, y = g.card_xy(geo, c.hold_hint)
        return x, y, x + g.card_w(), y + g.card_h(geo, c.hold_hint)


# --------------------------------------------------------------------------- the design states
def _buttons(labels, disabled=(), lit=None):
    return [{"label": l, "enabled": i not in disabled, "lit": ("on" if lit == i else None), "icon": ""}
            for i, l in enumerate(labels)]


def _playing(**extra):
    st = {"title": "Harbour Lights", "artist": "Air", "playback": "PLAYING", "position_s": 64,
          "duration_s": 252, "volume": 38, "online": True, "playlist_position": 1, "queue_length": 10}
    st.update(extra)
    return st


MOON = ["Harbour Lights", "Long Range", "Afterburn", "Kelly Watch the Stars", "Talisman", "Remember",
        "You Make It Easy", "Ce matin-là", "Blue Hour Signal", "Le voyage de Maré"]
RECENT = [("Neon Littoral", "Lumen Park", 1991, 0x2A4F7A), ("Glass Weather", "Lumen Park", 2010, 0x6B5A2A),
          ("Paper Lanterns", "Mira Vale", 1985, 0x5C2A3F), ("Midnight Arcade", "Air", 1998, 0x8AA7C4),
          ("Tidal Glass", "Oskar Lind Trio", 1959, 0x2B3A55), ("Promises", "Harbour Signals", 2021, 0x4B3B63),
          ("Night Channel", "Velvet Circuit", 2007, 0x3D3D3D), ("Copper Sun", "Various", 1968, 0x6B5A2A),
          ("Lua & Mar", "Lua Serena", 1974, 0x2F4A3A)]
RECENT_ART = ["blue-lines", "glass weather-album-", "hounds-of-love", "moon-safari", "kind-of-blue",
              "promises-floating-points-pharoah-sanders", "night-drive-velvet circuit-album-",
              "tropic-lia-ou-panis-et-circencis", "elis-tom"]
SCENES = [{"id": "scene.focus", "label": "Focus", "running": False}, {"id": "scene.evening", "label": "Evening"},
          {"id": "scene.movie", "label": "Movie"}, {"id": "scene.reading", "label": "Reading"},
          {"id": "scene.daylight", "label": "Daylight"}]


def _lights(on=True, bri=62, kelvin=3200, mode="bri", scene="Focus", adjusted=False):
    return {"online": True, "on": on, "bri": bri if on else 0, "kelvin": kelvin, "supports_ct": True,
            "scene_label": scene, "scene_id": "scene.focus", "adjusted": adjusted, "name": "Demo",
            "scenes": [dict(s) for s in SCENES], "mode": mode}


def recent_items():
    """The Recently Added sample items, shaped like the controller's list items: each carries an
    artwork template the art pipeline resolves (``simulation://art/...``: the simulator's covers,
    drawn by ``art.SimulatedCovers`` from the prototype's files by title)."""
    return [{"id": f"alb-{i}", "title": t, "artist": a, "year": y, "accent": c, "kind": "album",
             "art_template": f"simulation://art/alb-{i}/{{w}}x{{h}}bb.jpg", "art_max": 1400, "art_bg": c}
            for i, (t, a, y, c) in enumerate(RECENT)]


def recent_covers_source():
    """``navigator_covers.NavigatorCovers`` over a synchronous ``ArtService`` with the simulator's
    covers: the same path the app takes (the explorer's art identity, ``fetch_decoded``)."""
    from .navigator_covers import NavigatorCovers
    from .art import ArtService, SimulatedCovers
    d = covers_dir()
    service = ArtService(sync=True, simulated=SimulatedCovers(str(d) if d else None))
    return NavigatorCovers(service, k=2.0), service


def with_recent_covers(content, snap, source=None, *, land=True):
    """What ``Navigator._with_covers`` does on the Tk tick: the covers' art keys and the images
    that landed. Returns (content, {key: image})."""
    import dataclasses
    covers, service = source or recent_covers_source()
    items = snap.get("recent") or []
    focus = snap.get("index", 0)
    keys = covers.want(items, focus)
    if land:
        service.run_pending()
    art = {}
    out = []
    for cv in content.covers:
        key = keys.get(focus + cv.offset, "")
        out.append(dataclasses.replace(cv, art_key=key))
        img = covers.get(key)
        if img is not None:
            art[key] = img
    return dataclasses.replace(content, covers=tuple(out)), art


def design_states():
    """(name, snapshot, pressed, art key) for every state of the checklist (NV-14 ... NV-24)."""
    home_b = _buttons(["Music", "Win", "Lights", "Pause"])
    music_b = _buttons(["Home", "Recent", "Tracks", "Pause"])
    art = "art:moon-safari"
    states = [
        ("home", {"mode": "launcher", "frame": {"artKey": art}, "state": _playing(), "volume": 38,
                  "buttons": home_b}, None),
        ("home-volume-turning", {"mode": "launcher", "frame": {"artKey": art, "layout": "volume"}, "state": _playing(),
                                 "volume": 44, "buttons": home_b}, None),
        ("home-key4-pressed", {"mode": "launcher", "frame": {"artKey": art}, "state": _playing(), "volume": 38,
                               "buttons": home_b}, 3),
        ("music", {"mode": "home", "frame": {"artKey": art}, "state": _playing(), "volume": 38,
                   "buttons": music_b}, None),
        ("music-paused", {"mode": "home", "frame": {"artKey": art}, "state": _playing(playback="PAUSED_PLAYBACK"),
                          "volume": 38, "buttons": _buttons(["Home", "Recent", "Tracks", "Play"])}, None),
        ("lights-brightness", {"mode": "lights", "frame": {}, "state": {}, "lights": _lights(),
                               "buttons": _buttons(["Home", "Scenes", "Temp", "All off"])}, None),
        ("lights-temperature", {"mode": "lights", "frame": {}, "state": {}, "lights": _lights(mode="temp", kelvin=4100,
                                                                                            adjusted=True),
                                "buttons": _buttons(["Home", "Scenes", "Temp", "All off"], lit=2)}, None),
        ("lights-off", {"mode": "lights", "frame": {}, "state": {}, "lights": _lights(on=False),
                        "buttons": _buttons(["Home", "Scenes", "Temp", "Turn on"])}, None),
        ("recently-added", {"mode": "recent", "index": 3, "frame": {"artKey": "art:moon-safari", "title": "Midnight Arcade",
                                                                     "subtitle": "Air", "meta": "4 / 9"},
                            "recent": recent_items(),
                            "buttons": _buttons(["Back", "Open", "Play next", "Play"])}, None),
        ("tracks", {"mode": "tracks", "index": 1, "frame": {"meta": "1 / 10"}, "state": _playing(),
                    "neighbours": {n + 1: MOON[n] for n in range(10)},
                    "buttons": _buttons(["Back", "Up next", "Seek", "Skip"], disabled=(3,))}, None),
        ("tracks-next", {"mode": "tracks", "index": 2, "frame": {"meta": "Press 4 to skip"}, "state": _playing(),
                         "neighbours": {n + 1: MOON[n] for n in range(10)},
                         "buttons": _buttons(["Back", "Up next", "Seek", "Skip"])}, None),
        ("seek", {"mode": "seek", "frame": {"artKey": art, "title": "Harbour Lights"}, "state": _playing(),
                  "seek": {"target": 131, "D": 252}, "buttons": _buttons(["Back", "Up next", "Seek", "Skip"])}, None),
        ("scenes", {"mode": "scenes", "index": 1, "frame": {}, "state": {},
                    "lights": dict(_lights(), scenes=[dict(s, running=(i == 0)) for i, s in enumerate(SCENES)]),
                    "buttons": _buttons(["Back", "", "", "Run"], disabled=(1, 2))}, None),
        ("recent-message", {"mode": "recent", "index": 0, "frame": {"artKey": "", "title": "Neon Littoral",
                                                                     "subtitle": "Lumen Park",
                                                                     "meta": "Shuffle on · turn it off",
                                                                     "metaTone": "error"},
                            "recent": recent_items(),
                            "buttons": _buttons(["Back", "Open", "Play next", "Play"], disabled=(2,))}, None),
    ]
    out = []
    for name, snap, pressed in states:
        snap.setdefault("spaces", True)
        out.append((name, snap, pressed))
    return out


def _area_lights(members, *, mode="bri", block=None, online=True, scene="Focus", adjusted=False):
    """An r3.1.1 area snapshot (the shape ``navigator_model.snapshot`` builds from the controller's
    ``lights_area`` / ``lights_block``) over neutral sample members: (name, on, bri, kelvin, available)."""
    ms = [{"name": n, "on": on, "bri": b, "kelvin": k, "available": av} for n, on, b, k, av in members]
    ok = [m for m in ms if m["available"]]
    lit = [m for m in ok if m["on"]]
    levels, kelvins = [m["bri"] for m in lit], [m["kelvin"] for m in lit]
    mixed = bool(lit) and (len(lit) < len(ok) or max(levels) - min(levels) > 2 or max(kelvins) - min(kelvins) > 50)
    bri = round(sum(levels) / len(levels)) if lit else 0
    kelvin = round(sum(kelvins) / len(kelvins)) if lit else 3200
    out = dict(_lights(on=bool(lit), bri=bri or 62, kelvin=kelvin, mode=mode, scene=scene, adjusted=adjusted),
               online=online, name="Office", block=block)
    out["bri"] = bri
    out["area"] = {"count": len(ms), "ok": len(ok), "on": len(lit), "mixed": mixed, "members": ms,
                   "bad": [m["name"] for m in ms if not m["available"]]}
    return out


def lights_states():
    """The r3.1.1 compact Lights card (Home's hold-4 domain and the Lights screen) over an area:
    uniform, mixed, temperature, all off, one unavailable, not connected. Same shape as
    ``design_states``."""
    keys = _buttons(["Home", "Scenes", "Temp", "All off"])
    three = [("Lamp 1", True, 62, 3200, True), ("Lamp 2", True, 62, 3200, True), ("Lamp 3", True, 62, 3200, True)]
    states = [
        ("lights-area-uniform", {"mode": "lights", "frame": {}, "state": {}, "lights": _area_lights(three),
                                 "buttons": keys}, None),
        ("lights-area-mixed", {"mode": "lights", "frame": {}, "state": {},
                               "lights": _area_lights([("Lamp 1", True, 80, 2700, True),
                                                       ("Lamp 2", True, 40, 4000, True),
                                                       ("Lamp 3", False, 0, 3200, True)], adjusted=True),
                               "buttons": keys}, None),
        ("lights-area-temperature", {"mode": "lights", "frame": {}, "state": {},
                                     "lights": _area_lights([(n, on, b, 4100, av) for n, on, b, _k, av in three],
                                                            mode="temp"),
                                     "buttons": _buttons(["Home", "Scenes", "Temp", "All off"], lit=2)}, None),
        ("lights-area-off", {"mode": "lights", "frame": {}, "state": {},
                             "lights": _area_lights([(n, False, 0, k, av) for n, _on, _b, k, av in three]),
                             "buttons": _buttons(["Home", "Scenes", "Temp", "Turn on"])}, None),
        ("lights-area-unavailable", {"mode": "lights", "frame": {}, "state": {},
                                     "lights": _area_lights(three[:2] + [("Lamp 3", False, 0, 3200, False)]),
                                     "buttons": keys}, None),
        ("lights-area-not-connected", {"mode": "lights", "frame": {}, "state": {},
                                       "lights": _area_lights(three, block="nc", online=False),
                                       "buttons": keys}, None),
        ("home-lights", {"mode": "launcher", "home_domain": "lights", "frame": {}, "state": _playing(),
                         "volume": 38, "lights": _area_lights(three),
                         "buttons": _buttons(["Music", "Win", "Lights", "Pause"])}, None),
    ]
    for _name, snap, _pressed in states:
        snap.setdefault("spaces", True)
    return states


def golden_states():
    """Every state the Navigator goldens pin (tests/goldens/navigator): the design states and the
    r3.1.1 Lights states, plus key 1's pressed fill (key 4 no longer fills, r3.1 design)."""
    states = design_states()
    home = next(snap for name, snap, _p in states if name == "home")
    return states + lights_states() + [("home-key1-pressed", dict(home), 0)]


def state_art(name, snap):
    """The cover images a state's Tk side would hand over (the prototype's covers when present)."""
    key = (snap.get("frame") or {}).get("artKey")
    art = {}
    if key:
        img = cover(key.split(":", 1)[1])
        if img is not None:
            art[key] = img
    return art


def render_state(name, snap, pressed=None, *, desktop=None, settle_ms=900):
    """Our render of one state at rest: the host column over the desktop (RGB)."""
    rig = HeadlessNavigator(desktop)
    content = NM.build_content(snap, pressed=pressed)
    art = state_art(name, snap)
    if content.kind == "covers":
        # every cover through the app's path: NavigatorCovers -> the art pipeline (fetch_decoded)
        content, covers_art = with_recent_covers(content, snap)
        art.update(covers_art)
    rig.post(content, art=art)
    rig.advance(settle_ms)
    return rig.render(), rig


def crop_card(img, rig, margin=40):
    x0, y0, x1, y1 = rig.card_box()
    return img.crop((max(0, x0 - margin), max(0, y0 - margin), min(img.size[0], x1 + margin + 40),
                     min(img.size[1], y1 + margin + 60)))


def _motion_crop(rig, img):
    x0, y0, x1, y1 = rig.card_box()
    return img.crop((0, max(0, y0 - 40), min(img.size[0], x1 + 80), min(img.size[1], y1 + 100)))


def motion_frames(desktop=None):
    """The show slide, a content swap, the hide (MO-7, MO-8) and Recently Added covers landing
    over their accent tiles (the 240 ms fade), sampled mid-motion, each cropped to its card."""
    frames = []
    states = {n: (s, p) for n, s, p in design_states()}
    rig = HeadlessNavigator(desktop)
    home = NM.build_content(states["home"][0])
    rig.post(home, art=state_art("home", states["home"][0]))
    for ms in (60, 140, 420):
        frames.append((f"show +{ms} ms", _motion_crop(rig, rig.render(ms))))
    rig.advance(900)
    music = NM.build_content(states["music"][0])
    rig.post(music, art=state_art("music", states["music"][0]))
    for ms in (40, 120):
        frames.append((f"swap Home>Music +{ms} ms", _motion_crop(rig, rig.render(ms))))
    rig.advance(900)
    rig.post(music, visible=False)
    frames.append(("hide +140 ms", _motion_crop(rig, rig.render(140))))
    # Recently Added: shown before any cover is in (accent tiles), then the art pipeline lands them
    rig = HeadlessNavigator(desktop)
    snap = states["recently-added"][0]
    source = recent_covers_source()
    content, _art = with_recent_covers(NM.build_content(snap), snap, source, land=False)
    rig.post(content)
    rig.advance(900)
    frames.append(("covers loading (tiles)", _motion_crop(rig, rig.render())))
    content, art = with_recent_covers(NM.build_content(snap), snap, source, land=True)
    rig.post(content, art=art)
    for ms in (100, 300):
        frames.append((f"covers land +{ms} ms", _motion_crop(rig, rig.render(ms))))
    return frames, rig


def contact_sheet(out_png, out_dir=None, prototype_dir=None, scale=0.5):
    """Every design state (ours, with the prototype's rendering beside it when available) and the
    motion samples, on one sheet."""
    from ...carousel_render import FONT_DIR  # noqa: F401  (the bundled Archivo is what we draw with)
    desktop = desktop_image()
    tiles = []
    for name, snap, pressed in golden_states():
        img, rig = render_state(name, snap, pressed, desktop=desktop)
        card = crop_card(img, rig)
        if out_dir:
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            card.save(Path(out_dir) / f"nav-{name}.png")
        proto = None
        if prototype_dir:
            p = Path(prototype_dir) / f"{name}.png"
            if p.exists():
                with Image.open(p) as im:
                    proto = im.convert("RGB")
        tiles.append((name, card, proto))
    motion, _rig = motion_frames(desktop)
    return _sheet(out_png, tiles, motion, scale)


def _sheet(out_png, tiles, motion, scale):
    from ...render_music import draw_text
    pad, label_h = 24, 44
    cells = []
    for name, card, proto in tiles:
        imgs = [card] if proto is None else [proto, card]
        cells.append((name, [im.resize((int(im.size[0] * scale), int(im.size[1] * scale)), Image.Resampling.LANCZOS)
                             for im in imgs], proto is not None))
    for name, im in motion:
        cells.append((name, [im.resize((int(im.size[0] * scale), int(im.size[1] * scale)), Image.Resampling.LANCZOS)],
                      False))
    cols = 4
    cw = max(sum(i.size[0] for i in imgs) + pad * (len(imgs) - 1) for _n, imgs, _p in cells) + pad
    rows = [cells[i:i + cols] for i in range(0, len(cells), cols)]
    rh = [max(max(i.size[1] for i in imgs) for _n, imgs, _p in row) + label_h + pad for row in rows]
    W, H = cols * cw + pad, sum(rh) + pad + 60
    sheet = Image.new("RGB", (W, H), (22, 22, 26))
    title = RM.Sprite.new(W, 60)
    draw_text(title, "r3 Navigator · headless reference renders (ours" +
              (": prototype left, ours right)" if any(p for _n, _i, p in cells) else ")") +
              " · k = 2, 5120 x 1440 · shown at 50 %", pad, 16, 22, 28, wght=600)
    sheet.paste(title.pm, (0, 0), title.a)
    y = 60
    for row, h in zip(rows, rh):
        x = pad
        for name, imgs, has_proto in row:
            lab = RM.Sprite.new(cw, label_h)
            draw_text(lab, name, 0, 10, 18, 24, wght=600, rgb=(230, 230, 230))
            sheet.paste(lab.pm, (x, y), lab.a)
            xx = x
            for im in imgs:
                sheet.paste(im, (xx, y + label_h))
                xx += im.size[0] + pad
            x += cw
        y += h
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_png)
    return out_png


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(ROOT / "design-reference" / "r3-navigator"))
    ap.add_argument("--sheet", default=str(ROOT / "design-reference" / "r3-navigator-sheet.png"))
    ap.add_argument("--prototype", default=str(ROOT / "design-reference" / "r3-navigator-prototype"))
    a = ap.parse_args(argv)
    proto = a.prototype if os.path.isdir(a.prototype) else None
    print(contact_sheet(a.sheet, a.out, proto))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
