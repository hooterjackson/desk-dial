"""Gallery loops for the README: the LED moments, the LCD motion moments and the Onshape knob.

leds-moments.webp / .gif (4 x 3 tiles, 7.6 s at 30 fps): one ring per tile, drawn by knob_scenes.KnobDevice
(crop_ring, scale 0.6, the LCD left dark) from the LED twin (control_center.alive_lights.AliveLights, the
firmware's cc_alive engine), each tile driven by its own short timeline of frames and inputs. The frames are the
app's own wire frames taken from the true-to-app recordings (music-volume, music-lists, windows-knob: Home at a
volume, the Recently Added list, the window picker), with only `ring.value` / `ring.index` and a `feedback`
object changed. What triggers each moment in the twin (alive_lights.py, AliveLights._feedback / _feedback_effect
/ render / release):
  rest glow        no input for 5 s (SLEEP_MS): every class at its resting alpha, the song hand (set_progress)
  wake + arc       detents on Home: the `wake` effect, the volume arc at its awake alpha, ticks
  86 % / 95 %      the volume arc's AMBER (x >= 80, k >= 40) and RED (x >= 90, k >= 45) roles; RED drives the
                   near-max embers
  cover colours    detents on a `selection` ring with `colors` (ledStyle color): the items' own accents
  Like             feedback ok + moment like            -> `bloom` in PINK at the cursor
  Snap             feedback ok + moment snap, side, color -> `half` in sat(color)
  Shuffle          feedback ok + moment shuffle          -> `scatter`
  Queued           feedback ok + moment queued           -> `sweep` (the comet lap from 12 o'clock)
  wall             limit(+1) at 100 %                    -> `bound` + the r4 warm-white wall glow (cursor +-2)
  deny             feedback err + moment refused          -> the deny glow (segments 26..34, 480 ms), no shake
  hold ring        slot 0 held 600 ms on a crumb screen   -> the arc fills WARM, then the `home` flash
  PC away          release()                              -> `down` (the drain), then the offline waiting marks
Every tile starts and (but the PC-away one) ends in the same state, so the loop seam is quiet. A button press goes
with each button moment (press / key_up), as on the knob.

motion-gallery.webp / .gif (4 x 2 tiles, 6 s): the firmware LCD renderer (knob-anim) alone, 200 px round tiles,
each a knob-anim script built from recording frames (music-lists, music-playpause, music-volume), re-timed so the
motion happens twice or there and back: push (a screen change), glide (a detent in a list, forward then back),
wall stretch ({"wall": 1} steps on the 100 % screen), press squash ({"keys": n} then 0), landing pop (playing
flips: the Play / Pause icon pops), Play / Pause morph (the same moment with the key, cropped 2x on the icon),
hold fill ({"keys": 8} for 1000 ms on a holdMarker frame, landed by a new ok feedback), crumb crossfade (Recently Added <-> Playlists).
knob-anim's own stats line (pops, morphs, glides, holdFills, walls, presses) is logged per tile as a check.

onshape-knob.webp / .gif (9.8 s): onshape_scenes.frames(onshape_scenes.SCENES["onshape-knob"](), app-canvas-anim,
work) on knob_scenes.KnobDevice(scale=1.1) with the ring and the button lights all dark (the knob turns its LEDs
off in Onshape mode). The public media show the knob's real Onshape screen, logo included (the owner's
decision, 2026-10-03); a --no-logo build swaps the logo for a plain badge.

Registry contract: SCENES = {name: (source label, fn)}; fn(ctx) returns the Paths it wrote, each tagged with
ctx.produced(path, source). Imports stay inside the functions. No device, no window, no network.
"""
from __future__ import annotations

import json
import re
import subprocess
from copy import deepcopy
from pathlib import Path

LED = "LED twin (alive_lights.py)"
LCD = "firmware LCD renderer"
APP_CANVAS = "firmware app canvas"

FPS = 30
BG = (13, 14, 17)                  # knob_scenes.BG
CAPTION_H = 30
WEBP_CAP = 1_200_000


# ------------------------------------------------------------------ shared helpers
def _rec(ctx, name):
    import rec_scenes
    import recording
    return recording.load(rec_scenes.recording_path(ctx.work, name, ctx.log))


def _frames_of(rec):
    return [(e["t"], e["frame"]) for e in rec["events"] if e["kind"] == "frame"]


def _last_frame(rec, t, pred=lambda f: True):
    """The last frame at or before t (output clock) that satisfies pred."""
    best = None
    for tt, f in _frames_of(rec):
        if tt <= t and pred(f):
            best = f
    if best is None:
        raise ValueError(f"{rec['name']}: no frame before {t} ms matches")
    return deepcopy(best)


def _clean(frame):
    f = deepcopy(frame)
    f.pop("feedback", None)
    f.pop("haptic", None)
    return f


def _caption(img, text, theme_text=(230, 237, 243)):
    import panels as P
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    w, h = img.size
    d.text((w / 2, h - CAPTION_H / 2), text, font=P.font(13), fill=theme_text, anchor="mm")
    return img


def _grid(tile_frames, captions, cols, gap=6, pad=10):
    """tile_frames: list (per tile) of equal-length frame lists of equal-size images. Returns the composited frames,
    each tile with its caption under it, on BG."""
    from PIL import Image
    n = min(len(t) for t in tile_frames)
    tw, th = tile_frames[0][0].size
    rows = (len(tile_frames) + cols - 1) // cols
    W = pad * 2 + cols * tw + (cols - 1) * gap
    H = pad * 2 + rows * (th + CAPTION_H) + (rows - 1) * gap
    base = Image.new("RGB", (W, H), BG)
    for j, cap in enumerate(captions):
        x = pad + (j % cols) * (tw + gap)
        y = pad + (j // cols) * (th + CAPTION_H + gap)
        band = Image.new("RGB", (tw, CAPTION_H), BG)
        _caption(band, cap)
        base.paste(band, (x, y + th))
    out = []
    for k in range(n):
        img = base.copy()
        for j, tf in enumerate(tile_frames):
            x = pad + (j % cols) * (tw + gap)
            y = pad + (j // cols) * (th + CAPTION_H + gap)
            img.paste(tf[k], (x, y))
        out.append(img)
    return out


def _save(frames, stem, ctx):
    import panel_scenes
    gif, webp, q = panel_scenes.save_loop_capped(frames, FPS, stem, ctx.out, cap=WEBP_CAP)
    if q is not None:
        ctx.log(f"{stem}.webp re-encoded at quality {q} to fit {WEBP_CAP} B")
    ctx.log(f"{len(frames)} frames {frames[0].size[0]}x{frames[0].size[1]}: webp {webp.stat().st_size} B, "
            f"gif {gif.stat().st_size} B")
    frames[len(frames) // 2].save(Path(ctx.work) / f"{stem}-peek.png")
    return gif, webp


# ------------------------------------------------------------------ LED moments
LED_LOOP_MS = 7600
LED_PRE_MS = 8000                  # claimed this long before the loop: boot done, asleep at t = 0
LED_SCALE = 0.6
MOMENT_AT = 600                    # the button moments: press at 600, feedback 80 ms later


class LedTile:
    """One tile's timeline on the loop clock: (t, kind, payload), kind frame / detent / kd / ku / lim / release."""

    def __init__(self, caption, first_frame):
        self.caption = caption
        self.events = [(-LED_PRE_MS + 10, "frame", first_frame)]
        self.seq = 0

    def at(self, t, kind, payload=None):
        self.events.append((t, kind, payload))
        return self

    def feedback(self, t, base, **fb):
        self.seq += 1
        f = deepcopy(base)
        f["feedback"] = dict(fb, seq=self.seq)
        return self.at(t, "frame", f)


def _home(base, v, reveal=False):
    f = _clean(base)
    f["ring"] = dict(f["ring"], value=v)
    f["value"] = f"{v}%"
    f["confirmedVolume"] = v
    f["layout"] = "volume" if reveal else "nowPlaying"
    f["volumeVisible"] = bool(reveal)
    f["activity"] = "idle"
    return f


def _list(base, i):
    f = _clean(base)
    f["ring"] = dict(f["ring"], index=i)
    return f


def _turn(tile, t0, v0, v1, every, make):
    step = 1 if v1 >= v0 else -1
    t = t0
    for v in range(v0 + step, v1 + step, step):
        tile.at(t, "detent", step)
        tile.at(t + 30, "frame", make(v))
        t += every
    return t


def led_tiles(ctx):
    vol = _rec(ctx, "music-volume")
    lists = _rec(ctx, "music-lists")
    win = _rec(ctx, "windows-knob")
    home0 = _clean(_last_frame(vol, -2000, lambda f: f.get("layout") == "nowPlaying"))
    lst0 = _clean(_last_frame(lists, 1300, lambda f: (f.get("ring") or {}).get("style") == "selection"))
    win0 = _clean(_last_frame(win, 2500, lambda f: (f.get("ring") or {}).get("style") == "marker"))
    H = lambda v, r=False: _home(home0, v, r)   # noqa: E731
    tiles = []

    tiles.append(LedTile("Resting glow", H(62)))

    t = LedTile("Wake: the volume arc", H(48))
    end = _turn(t, 300, 48, 54, 120, lambda v: H(v, True))
    _turn(t, end + 250, 54, 48, 120, lambda v: H(v, True))
    tiles.append(t)

    t = LedTile("86 % amber, 95 % red embers", H(80, True))
    t.at(-300, "detent", 1).at(-270, "frame", H(80, True))          # awake at both ends of the loop
    end = _turn(t, 500, 80, 95, 90, lambda v: H(v, True))
    _turn(t, 4600, 95, 80, 90, lambda v: H(v, True))
    tiles.append(t)

    t = LedTile("Cover colours in a list", _list(lst0, 0))
    t.at(-300, "detent", -1).at(-270, "frame", _list(lst0, 0))
    for k, i in enumerate((1, 2, 3, 4)):
        t.at(500 + 650 * k, "detent", 1).at(530 + 650 * k, "frame", _list(lst0, i))
    for k, i in enumerate((3, 2, 1, 0)):
        t.at(3900 + 650 * k, "detent", -1).at(3930 + 650 * k, "frame", _list(lst0, i))
    tiles.append(t)

    def button_moment(caption, base, slot, **fb):
        tile = LedTile(caption, base)
        tile.at(MOMENT_AT, "kd", slot).at(MOMENT_AT + 90, "ku", slot)
        tile.feedback(MOMENT_AT + 80, base, **fb)
        return tile

    tiles.append(button_moment("Like: pink bloom", H(62), 2, kind="ok", moment="like"))
    snap = win0.get("buttons", [{}, {}])[1].get("color") or 0x1FB895
    tiles.append(button_moment("Snap: half wash", win0, 1, kind="ok", moment="snap", side=-1, color=snap))
    tiles.append(button_moment("Shuffle: scatter", H(30), 2, kind="ok", moment="shuffle"))   # sparks land on dark LEDs
    tiles.append(button_moment("Queued: comet lap", _list(lst0, 0), 2, kind="ok", moment="queued"))

    t = LedTile("Wall: the push glows", H(100))
    t.at(MOMENT_AT, "lim", 1).at(MOMENT_AT + 260, "lim", 1)
    tiles.append(t)

    tiles.append(button_moment("Refused: deny glow", H(62), 3, kind="err", moment="refused"))

    t = LedTile("Hold 1: the ring fills", _list(lst0, 0))
    t.at(MOMENT_AT, "kd", 0).at(MOMENT_AT + 760, "ku", 0)
    tiles.append(t)

    t = LedTile("PC away: drain, then waiting", H(62))
    t.at(-300, "detent", 1).at(-270, "frame", H(62))
    t.at(300, "detent", 1).at(330, "frame", H(62))
    t.at(1000, "release")
    tiles.append(t)
    return tiles, home0


def run_led_tile(tile, tuning):
    """(ring, buttons) per output frame of the loop: the twin at 60 Hz plus every capture tick (recording.led_frames)."""
    import math
    from companion import AliveLights
    pre = LED_PRE_MS
    lights = AliveLights(0)
    lights.claim(0)
    pink, vol_full, progress = tuning
    lights.set_tuning(0, pink, vol_full)
    if progress:
        lights.set_progress(0, int(progress.get("pos", 0)), int(progress.get("dur", 0)))
    ev = sorted(((t + pre, k, p) for t, k, p in tile.events), key=lambda e: (e[0], 0 if e[1] != "frame" else 1))
    caps = [pre + math.ceil(k * 1000 / FPS) for k in range(math.ceil(LED_LOOP_MS * FPS / 1000))]
    ticks = sorted(set([round(j * 1000 / 60) for j in range(int((caps[-1] + 1) * 60 / 1000) + 2)] + caps))
    capset, out, frame, ei = set(caps), {}, None, 0
    for now in ticks:
        while ei < len(ev) and ev[ei][0] <= now:
            t, k, p = ev[ei]
            if k == "frame":
                frame = p
            elif k == "detent":
                lights.detent(t, p)
            elif k == "kd":
                lights.press(t, p)
            elif k == "ku":
                lights.key_up(t, p)
            elif k == "lim":
                lights.limit(t, p)
            elif k == "release":
                lights.release(t)
            ei += 1
        ring, buttons = lights.render(now, frame)
        if now in capset:
            out[now] = (list(ring), list(buttons))
    return [out[c] for c in caps]


def scene_leds_moments(ctx) -> list[Path]:
    import knob_scenes as K
    from PIL import Image
    tiles, home0 = led_tiles(ctx)
    tuning = (int(home0.get("ledPink", 0) or 0), bool(home0.get("ledVolFull", False)), home0.get("progress"))
    dev = K.KnobDevice(scale=LED_SCALE, crop_ring=True)
    dark = Image.new("RGB", (240, 240), (0, 0, 0))
    per_tile = []
    for tile in tiles:
        leds = run_led_tile(tile, tuning)
        per_tile.append([dev.compose(dark, ring, buttons) for ring, buttons in leds])
    frames = _grid(per_tile, [t.caption for t in tiles], cols=4)
    gif, webp = _save(frames, "leds-moments", ctx)
    return [ctx.produced(webp, LED), ctx.produced(gif, LED)]


# ------------------------------------------------------------------ LCD motion moments
MOTION_MS = 6000
MOTION_PRE = 1500                  # knob-anim settles (covers decode) before the first output frame
MOTION_TILE = 200


class Script:
    def __init__(self, rec, first):
        self.rec = rec
        self.steps = [{"at": 0, "frame": first}]

    def frame(self, t, f):
        self.steps.append({"at": MOTION_PRE + t, "frame": f})
        return self

    def keys(self, t, mask):
        self.steps.append({"at": MOTION_PRE + t, "keys": mask})
        return self

    def wall(self, t, d):
        self.steps.append({"at": MOTION_PRE + t, "wall": d})
        return self

    def segment(self, a, b, at, keys=True):
        """The recording's frames (and key edges) in [a, b) of its output clock, moved so a lands at `at`."""
        mask = 0
        for e in self.rec["events"]:
            if not a <= e["t"] < b:
                continue
            t = at + e["t"] - a
            if e["kind"] == "frame":
                self.frame(t, e["frame"])
            elif keys and e["kind"] == "kd":
                mask |= 1 << e["slot"]
                self.keys(t, mask)
            elif keys and e["kind"] == "ku":
                mask &= ~(1 << e["slot"])
                self.keys(t, mask)
        return self

    def dict(self, name):
        steps = sorted(self.steps, key=lambda s: s["at"])
        return {"name": name, "fps": FPS, "duration_ms": MOTION_MS, "start_ms": MOTION_PRE,
                "covers": self.rec["covers"], "icons": self.rec["icons"], "steps": steps}


def motion_scripts(ctx):
    lists = _rec(ctx, "music-lists")
    pp = _rec(ctx, "music-playpause")
    vol = _rec(ctx, "music-volume")
    out = []
    # push: Music -> 2 = Recently Added (926), then 1 = Back to Music (11527)
    s = Script(lists, _last_frame(lists, 800))
    s.segment(900, 1500, 900).segment(11400, 12100, 3500)
    out.append(("Push: a screen change", "push", s, None))
    # glide: the list one detent at a time, forward then back (the recording's own frames per index)
    by_index = {}
    for t, f in _frames_of(lists):
        r = f.get("ring") or {}
        if 1200 < t < 4700 and r.get("style") == "selection" and f.get("crumb") == "recent":
            by_index[r.get("index")] = f
    s = Script(lists, by_index[0])
    for k, i in enumerate((1, 2, 3, 2, 1, 0)):
        s.frame(500 + 900 * k, by_index[i])
    out.append(("Glide: a detent in a list", "glide", s, None))
    # wall stretch: the 100 % screen, two pushes, twice
    top = _last_frame(vol, 5100, lambda f: (f.get("ring") or {}).get("value") == 100 and f.get("activity") == "idle"
                      and f.get("layout") == "volume")     # "Maximum", not the pending "Setting…"
    s = Script(vol, top)
    for t in (800, 1050, 3400, 3650):
        s.wall(t, 1)
    out.append(("Wall stretch at 100 %", "wall", s, None))
    # press squash: Home, a tap on 1 then on 3 (slot masks 1, 4)
    home = _last_frame(vol, -2000, lambda f: f.get("layout") == "nowPlaying")
    s = Script(vol, home)
    s.keys(900, 1).keys(1010, 0).keys(3300, 4).keys(3410, 0)
    out.append(("Press squash", "press", s, None))
    # landing pop: playing flips (Pause 117 / Play 2212 of music-playpause), the frames only
    s = Script(pp, _last_frame(pp, 0))
    s.segment(100, 1900, 600, keys=False).segment(2200, 4000, 3300, keys=False)
    out.append(("Landing pop: playing flips", "pop", s, None))
    # Play / Pause morph: the same moments with the key edges, cropped 2x on the button-4 icon
    s = Script(pp, _last_frame(pp, 0))
    s.segment(0, 1900, 500).segment(2100, 4000, 3200)
    out.append(("Play / Pause morph (2x)", "morph", s, "icon4"))
    # hold fill: button 4 held 1000 ms on a holdMarker frame, twice
    # ... and the host's answer lands it (a new ok feedback within 1.5 s: holdFillEnd + the icon pop), as the app
    # does after the Queue / Play next it ran; without it the matured icon stays lit and the loop seam jumps.
    s = Script(vol, home)
    for k, t in enumerate((700, 3400)):
        landed = deepcopy(home)
        landed["feedback"] = {"kind": "ok", "seq": 101 + k}
        s.keys(t, 8).frame(t + 1080, landed).keys(t + 1100, 0)
    out.append(("Hold fill: button 4, 1 s", "hold", s, None))
    # crumb crossfade: Recently Added -> 3 = Playlists (5185), 3 again = Recent (10527)
    s = Script(lists, _last_frame(lists, 11300))          # starts where it ends: Recently Added, Slow Orbit
    s.segment(5050, 5900, 800).segment(10400, 11300, 3500)
    out.append(("Crumb crossfade", "crumb", s, None))
    return out


def _knob_anim(ctx, script, work):
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    sp = work / f"motion-{script['name']}.script.json"
    sp.write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    raw = work / f"motion-{script['name']}.rgb"
    r = subprocess.run([str(ctx.knob_anim), str(sp), str(raw)], check=True, capture_output=True, text=True)
    stats = re.search(r"stats (.*)", r.stdout)
    data = raw.read_bytes()
    n = len(data) // 172800
    return [Image.frombytes("RGB", (240, 240), data[k * 172800:(k + 1) * 172800]) for k in range(n)], \
        (stats.group(1).strip() if stats else "")


ICON4_BOX = (150, 125, 230, 205)   # the button-4 icon on the 240 px LCD (2x crop for the morph tile)


def _round_tile(img, size, mask_cache={}):
    from PIL import Image, ImageDraw
    if size not in mask_cache:
        ss = 4
        m = Image.new("L", (size * ss, size * ss), 0)
        ImageDraw.Draw(m).ellipse((0, 0, size * ss - 1, size * ss - 1), fill=255)
        mask_cache[size] = m.resize((size, size), Image.Resampling.LANCZOS)
    tile = Image.new("RGB", (size, size), BG)
    tile.paste(img.resize((size, size), Image.Resampling.LANCZOS), (0, 0), mask_cache[size])
    return tile


def scene_motion_gallery(ctx) -> list[Path]:
    work = Path(ctx.work) / "motion"
    per_tile, captions = [], []
    for caption, name, s, crop in motion_scripts(ctx):
        lcd, stats = _knob_anim(ctx, s.dict(name), work)
        ctx.log(f"{name}: {len(lcd)} frames; {stats}")
        if crop == "icon4":
            lcd = [f.crop(ICON4_BOX) for f in lcd]
        per_tile.append([_round_tile(f, MOTION_TILE) for f in lcd])
        captions.append(caption)
    frames = _grid(per_tile, captions, cols=4)
    gif, webp = _save(frames, "motion-gallery", ctx)
    return [ctx.produced(webp, LCD), ctx.produced(gif, LCD)]


# ------------------------------------------------------------------ Onshape
ONSHAPE_SCALE = 1.1


def scene_onshape_knob(ctx) -> list[Path]:
    import knob_scenes as K
    import onshape_scenes as O
    if ctx.no_logo:
        ctx.log("note: a --no-logo build: the Onshape logo is replaced by a plain badge")
    lcd = O.frames(O.SCENES["onshape-knob"](), ctx.exe("app-canvas-anim"), Path(ctx.work) / "onshape")
    dev = K.KnobDevice(scale=ONSHAPE_SCALE)
    dark_ring, dark_buttons = [(0.0, 0.0, 0.0)] * 60, [(0.0, 0.0, 0.0)] * 4
    frames = [dev.compose(f, dark_ring, dark_buttons) for f in lcd]
    gif, webp = _save(frames, "onshape-knob", ctx)
    return [ctx.produced(webp, APP_CANVAS), ctx.produced(gif, APP_CANVAS)]


SCENES = {
    "leds-moments": (LED, scene_leds_moments),
    "motion-gallery": (LCD, scene_motion_gallery),
    "onshape-knob": (APP_CANVAS, scene_onshape_knob),
}
