"""The README hero: hero.webp / hero.gif, rendered at RES x 720 x 440 (shown at 720), 8 s at the recording's 30 fps.

Left, the knob: recording.knob_frames on the true-to-app recording ``hero-knob.json`` (the
firmware's own LCD renderer for the screen, the app's LED engine twin for the ring and the
buttons), at KnobDevice scale 0.9. Right, the r3 Navigator card (navigator_scene.NavRig: the app's
HeadlessNavigator, navigator_model.build_content and its Visibility rule) following the same
recording: every recorded wire frame and key edge becomes the snapshot the controller would hand the
Navigator at that time (mode from ``rec["screens"]``; title, buttons, volume, cover, list position
from the frame; HOLD progress and the pressed key from the key edges). Both sit over a dark crop of
fixtures.desktop().

Window: output time -300 .. 7700 ms of the recording: the dial turns the volume (the card slides
in), 1 = Music, 2 = Recently Added and three detents through the covers, 4 = Play (the new song
starts). The card's monitor is 2560 x 1440 (k = 2) with its work area starting at x 720, so the card
lands right of the knob; the frame is that desktop's (0, 280)-(1440, 1160) at half size.

The knob's flat backdrop (knob_scenes.BG) is keyed out against the static device body (the body
opaque, its drop shadow as a darkening), so the knob sits on the same desktop as the card.

Data: the recording is fictional (fixtures' albums and songs; covers from its covers/ folder). The
Recently Added items are fixtures' albums in the recording's order. The knob's subtitle on that list
(``Album · <year>``) is replaced by the artist for the card, as navigator_render's design states do.

Registry contract: SCENES = {"hero": (LCD, fn)}.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance

LCD = "firmware LCD renderer"
RES = 2                                     # render scale: 2 = retina-sharp at the README's 720 px (trial 2026-10-03)
SIZE = (720 * RES, 440 * RES)
KNOB_SCALE = 0.9 * RES
T_START, T_END = -300, 7700
MONITOR = (0, 0, 2560, 1440)
WORK = (720, 0, 2560, 1440)                 # the card's host column starts at x 720
VIEW = (0, 280, 1440, 1160)                 # what the hero shows of that desktop (2 : 1 down to 720 x 440)
WEBP_CAP = 1_700_000                        # gates.CAPS["hero"]
GIF_CAP = 2_900_000
DEFAULT_RECORDING = "hero-knob.json"
KEEP = ("title", "subtitle", "status", "statusTone", "meta", "metaTone", "layout", "value", "valueUnit",
        "volumeCaption", "playing", "artKey", "heading")


def dark_desktop(size):
    import fixtures as fx
    return ImageEnhance.Brightness(fx.desktop(size)).enhance(0.42)


def knob_key(base, bg):
    """(body alpha, shadow alpha) of the static device body against its flat backdrop ``bg``."""
    L = base.convert("L")
    b = round(0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2])
    body = L.point(lambda v: max(0, min(255, (v - b - 1) * 60)))
    shadow = L.point(lambda v: max(0, min(255, round((b - v) * 255 / max(1, b)))))
    return body, shadow


class Replay:
    """The recording's state at an output time: the last wire frame, the screen, key edges, inputs."""

    def __init__(self, rec):
        self.ev = sorted((e for e in rec["events"] if e["kind"] in ("frame", "kd", "ku", "kh", "detent", "lim")),
                         key=lambda e: e["t"])
        self.screens = sorted(rec["screens"], key=lambda s: s["t"])
        self.i = 0
        self.frame = {}
        self.down = {}                     # slot -> kd time
        self.last_kd = (None, -1e9)        # (slot, time)
        self.progress = None               # (event time, pos ms, dur ms) of the playing song
        self.song = ("", "")
        self.inputs = []                   # input times not yet handed out

    def advance(self, t):
        while self.i < len(self.ev) and self.ev[self.i]["t"] <= t:
            e = self.ev[self.i]
            k = e["kind"]
            if k == "frame":
                f = e["frame"]
                self.frame = f
                if f.get("layout") in ("nowPlaying", "volume") and f.get("title"):
                    if (f.get("title"), f.get("subtitle")) != self.song:
                        self.song = (f.get("title"), f.get("subtitle") or "")
                        self.progress = None
                if isinstance(f.get("progress"), dict):
                    self.progress = (e["t"], f["progress"].get("pos", 0), f["progress"].get("dur", 0))
            elif k == "kd":
                self.down[e["slot"]] = e["t"]
                self.last_kd = (e["slot"], e["t"])
                self.inputs.append(e["t"])
            elif k == "ku":
                self.down.pop(e["slot"], None)
                self.inputs.append(e["t"])
            elif k in ("detent", "lim"):
                self.inputs.append(e["t"])
            self.i += 1

    def mode(self, t):
        m = "launcher"
        for s in self.screens:
            if s["t"] <= t:
                m = s["mode"]
        return m

    def snapshot(self, t, items):
        import navigator_scene as NS
        f = self.frame
        mode = self.mode(t)
        frame = {k: f.get(k) for k in KEEP if k in f}
        ring = f.get("ring") or {}
        snap = NS.snapshot(mode if mode in ("launcher", "home", "recent") else "launcher",
                           song=self.song, volume=int(f.get("confirmedVolume", ring.get("value", 0)) or 0),
                           items=items, index=int(ring.get("index", 0) or 0) if mode == "recent" else 0,
                           held={s: (t - t0) / 1000.0 for s, t0 in self.down.items()})
        snap["mode"] = mode
        if ring.get("style") == "level":
            snap["volume"] = int(ring.get("value", 0))
        pos, dur = 0, 0
        if self.progress is not None:
            t0, p, d = self.progress
            pos, dur = (p + (t - t0)) / 1000.0, d / 1000.0
        snap["state"].update(position_s=int(pos), duration_s=int(dur), title=self.song[0], artist=self.song[1],
                             volume=snap["volume"])
        snap["buttons"] = [dict(label=b.get("label", ""), enabled=bool(b.get("enabled", True)), lit=b.get("lit"),
                                icon=b.get("icon")) for b in (f.get("buttons") or ())][:4]
        if mode == "recent":
            idx = snap["index"]
            cur = items[idx] if 0 <= idx < len(items) else {}
            if frame.get("title"):
                frame["subtitle"] = cur.get("artist", "")
            snap["list_source"] = "recent"
            snap["recent"] = items if frame.get("title") else []
        snap["frame"] = frame
        return snap

    def pressed(self, t):
        slot, t0 = self.last_kd
        return slot if slot is not None and t - t0 < 220 else None      # navigator_model.PRESS_FLASH_S


def navigator_column_frames(rec, times, items):
    """The desktop (dark) with the Navigator on it, cropped to VIEW and scaled to SIZE, at each output time."""
    import navigator_scene as NS
    desk = dark_desktop((MONITOR[2], MONITOR[3]))
    art = {}
    for key, path in rec["covers"].items():
        try:
            with Image.open(path) as im:
                art[key] = im.convert("RGB")
        except OSError:
            pass
    rig = NS.NavRig(desk, monitor=MONITOR, art=art, fps=rec["fps"])
    rig.nav = rig.NR.HeadlessNavigator(desk, work=WORK, monitor=MONITOR)
    rp = Replay(rec)
    t0 = times[0] - 1000.0                 # one second of warm-up (state replayed, nothing kept)
    warm = [t0 + k * rig.dt for k in range(int(1000.0 / rig.dt))]
    keep = set(range(len(warm), len(warm) + len(times)))
    steps = warm + list(times)
    size = SIZE
    out = []
    for j, t in enumerate(steps):
        rp.advance(t)
        for ti in rp.inputs:
            rig.now_ms = ti - t0
            rig.touch()
        rp.inputs.clear()
        rig.now_ms = t - t0
        rig.step(rp.snapshot(t, items), pressed=rp.pressed(t))
        if j in keep:
            view = rig.frame().crop(VIEW)
            out.append(view if view.size == size else view.resize(size, Image.Resampling.LANCZOS))
        if j + 1 < len(steps):
            rig.nav.advance(steps[j + 1] - t)
    return out


def recent_items_for(rec):
    """Recently Added in the recording's order: fixtures' albums cycled to the list's length."""
    import navigator_scene as NS
    count = max([int((e["frame"].get("ring") or {}).get("count", 0) or 0) for e in rec["events"]
                 if e["kind"] == "frame" and e["frame"].get("layout") == "recent"] or [NS.RECENT_COUNT])
    return NS.recent_items(count)


def hero_frames(rec, knob_anim, work):
    import recording as R
    import knob_scenes as K
    knob = R.knob_frames(rec, knob_anim, work, scale=KNOB_SCALE, t_start=T_START, t_end=T_END, tag="-hero")
    times = [T_START + c for c in R.capture_times({"fps": rec["fps"], "duration_ms": T_END - T_START})]
    n = min(len(knob), len(times))
    nav = navigator_column_frames(rec, times[:n], recent_items_for(rec))
    dev = K.KnobDevice(scale=KNOB_SCALE)
    body, shadow = knob_key(dev.base, K.BG)
    kw, kh = dev.size
    kx, ky = (SIZE[0] // 2 - kw) // 2, (SIZE[1] - kh) // 2
    frames = []
    for k in range(n):
        img = nav[k].copy()
        region = img.crop((kx, ky, kx + kw, ky + kh))
        inv = ImageChops.invert(shadow)
        region = ImageChops.multiply(region, Image.merge("RGB", (inv, inv, inv)))
        region.paste(knob[k], (0, 0), body)
        img.paste(region, (kx, ky))
        frames.append(img)
    return frames


def scene_hero(ctx) -> list[Path]:
    import recording as R
    import rec_scenes
    rec = R.load(rec_scenes.recording_path(ctx.work, DEFAULT_RECORDING[:-5], ctx.log))
    frames = hero_frames(rec, ctx.knob_anim, ctx.work)
    for k in (0, len(frames) // 3, 2 * len(frames) // 3):
        frames[k].save(Path(ctx.work) / f"hero-peek-{k}.png")
    gif, webp = R.save_loop(frames, rec["fps"], "hero", ctx.out, webp_cap=WEBP_CAP, gif_cap=GIF_CAP)
    ctx.log(f"hero: {len(frames)} frames at {rec['fps']} fps, webp {webp.stat().st_size} B, gif {gif.stat().st_size} B")
    cards = navigator_cards(frames, ctx.out)
    return [ctx.produced(webp, LCD), ctx.produced(gif, LCD)] + [ctx.produced(p, LCD) for p in cards]


def navigator_cards(frames, out_dir):
    """navigator-cards.webp / .png: the hero's Navigator card twice, side by side at the hero's resolution:
    browsing Recently Added (70 % through the clip) and the song playing (the last frames)."""
    out_dir = Path(out_dir)
    n = len(frames)
    x0, x1 = round(750 * RES / 2), round(1270 * RES / 2)          # the card column of the 2x hero
    crops = [frames[k].crop((x0, 5 * RES, x1, SIZE[1] - 5 * RES)) for k in (int(n * 0.7), n - 2)]
    gap = 20 * RES
    img = Image.new("RGB", (sum(c.width for c in crops) + gap, crops[0].height), (13, 14, 17))
    for i, c in enumerate(crops):
        img.paste(c, (i * (c.width + gap), 0))
    webp, png = out_dir / "navigator-cards.webp", out_dir / "navigator-cards.png"
    img.save(webp, quality=86, method=6)
    img.save(png, optimize=True)
    return [webp, png]


SCENES = {"hero": (LCD, scene_hero)}
