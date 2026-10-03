"""Full-screen desktop animations for the README ("On your desktop"), 7-9 s each at 30 fps.

* desktop-explorer-16x9 / desktop-explorer-32x9: the Music explorer opens over the desktop, browses
  Recently Added, switches to Favourite playlists, browses, plays one (the centre card grows, the
  overlay holds 380 ms, then fades) and closes.
* desktop-upnext-16x9: Up next opens on a playlist queue, spins through it, likes a song, shuffles
  what is left (the rows fade out and re-enter in the new order) and plays a row.
* desktop-picker-16x9 / desktop-picker-32x9: the Windows picker opens, browses the carousel, snaps
  one window to the LEFT half and another to the RIGHT half (the pair close), and the two windows
  end up side by side; then a plain Switch to a third window. The windows are fixtures.WINDOWS
  (invented apps: Ledger, Draft, Canvas, Chatter, Notes, Shell, Files, Grid; letter tiles, no logos).

The explorer and Up next are the companion's own stage engine (control_center.stage) on its fake
device and fake clock, drawn by its PIL reference renderer and composited over a synthetic desktop
with the overlay's own alpha. The explorer's key hints are the app's own ``scene_music.EXPLORER_HINTS``
(1 Back - 2 Recently Added - 3 Playlists - 4 Play). The picker is the production CarouselPresenter
running inline on the app's golden-test fake backend, fake NanoD-snap and fake clock; its frames are
composited the way the windows stack (desktop, frosted glass, DWM thumbnails at the engine's own
rects and opacities, chrome band, label and dots layers), like tests/test_carousel_goldens.py does.
The knob inputs and the snap answers are scripted; every animation's timing is the engine's own.

Output: 16:9 clips 1120 x 630, 32:9 clips 1400 x 394 (rendered at 1280 x 720 / 2560 x 720 and
resampled); WebP <= 2.0 MB (quality stepped down), GIF fallback <= 2.9 MB (gates.CAPS). No window is
shown, the screen is never read, and all data is fictional (fixtures.py).

Registry contract: SCENES = {name: (source label, fn)}; fn(ctx) returns the Paths it wrote.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

import fixtures as fx
import desktop_scene as D
from companion import APP_DIR

TS, SIM = D.TS, D.SIM
FPS = 30
STAGE = "app stage renderer"
CAROUSEL = "app carousel"
WEBP_CAP = 2_000_000          # gates.CAPS["desktop"]
GIF_CAP = 2_900_000           # gates.CAPS["gif"]
SIZE_16x9 = (1120, 630)
# The README's 16:9 clips: a 2560 x 1440 monitor (the stage and the carousel lay out on a 1280 x 720 design grid
# and scale to the monitor, so this is the same layout at 2x) down to 1760 x 990, shown at 880; 24 fps keeps
# them under the desktop cap (size trial of 2026-10-03).
SIZE_2X = (1760, 990)
MON_2X = (0, 0, 2560, 1440)
FPS_2X = 24
SIZE_32x9 = (1400, 394)


# ------------------------------------------------------------------ encoding
def encode(frames, fps, stem, out_dir, webp_budget=WEBP_CAP, gif_budget=GIF_CAP):
    """Animated WebP (full size, every frame; quality lowered until it fits the budget) and a GIF
    fallback (global palette, no dither), thinned and shrunk until it fits its budget."""
    out_dir = Path(out_dir)
    dur = round(1000 / fps)
    webp = out_dir / f"{stem}.webp"
    for q in (84, 78, 72, 66, 60, 54, 48, 42):
        frames[0].save(webp, save_all=True, append_images=frames[1:], duration=dur, loop=0, quality=q, method=5)
        if webp.stat().st_size <= webp_budget:
            break
    gif = out_dir / f"{stem}.gif"
    w0 = frames[0].size[0]
    for width, step in ((min(w0, 960), 2), (min(w0, 800), 2), (min(w0, 720), 3), (640, 3), (560, 3), (480, 4),
                        (420, 4)):
        scale = width / w0
        size = (round(frames[0].size[0] * scale / 2) * 2, round(frames[0].size[1] * scale / 2) * 2)
        fr = [f if f.size == size else f.resize(size, Image.Resampling.LANCZOS) for f in frames[::step]]
        sample = [fr[k] for k in range(0, len(fr), max(1, len(fr) // 12))]
        sheet = Image.new("RGB", (size[0], size[1] * len(sample)))
        for k, f in enumerate(sample):
            sheet.paste(f, (0, size[1] * k))
        pal = sheet.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in fr]
        q[0].save(gif, save_all=True, append_images=q[1:], duration=round(1000 * step / fps), loop=0, disposal=1)
        if gif.stat().st_size <= gif_budget:
            break
    return webp, gif


# ------------------------------------------------------------------ stage (explorer, Up next)
def run_stage(monitor, plan, end_ms, out_size, fps=FPS):
    """Drive a stage rig on its fake clock: ``plan`` is [(ms, fn(rig))]; one frame every 1000/FPS ms."""
    rig = D.Rig(monitor)
    size = (monitor[2] - monitor[0], monitor[3] - monitor[1])
    desk = fx.desktop(size)
    out, k, pi, now_ms = [], 0, 0, 0.0
    step = 1000 / fps
    while now_ms < end_ms:
        while pi < len(plan) and plan[pi][0] <= now_ms:
            plan[pi][1](rig)
            rig.settle()
            pi += 1
        img = D.over_desktop(rig, desk) if rig.engine.root is not None else desk.copy()
        out.append(img if img.size == out_size else img.resize(out_size, Image.Resampling.LANCZOS))
        k += 1
        target = k * step
        rig.advance(target - now_ms, step_ms=target - now_ms)
        now_ms = target
    return out


def explorer_plan():
    """Open on Recently Added (item 2), three detents, Playlists, two detents, Play: ~7.5 s."""
    def hl(i):
        return lambda rig: rig.presenter.explorer_highlight({"index": i, "control_id": 1, "bump": 0})

    def open_(rig):
        rig.presenter.explorer_open(TS.explorer_payload(rig.now(), index=1, art="full"))

    def favourites(rig):
        fav = TS.explorer_payload(rig.now(), source="favourites", index=0, favs="many")
        sw = {k: fav[k] for k in ("t0", "source", "state", "index", "count", "items", "items_first")}
        sw["items_rev"] = 2
        rig.presenter.explorer_source(sw)

    def play(rig):
        rig.presenter.explorer_close({"t0": rig.now(), "reason": "play", "close_at_ms": 380})

    plan = [(400, open_)]
    t = 1400
    for i in (2, 3, 4):
        plan.append((t, hl(i)))
        t += 550
    t += 350
    plan.append((t, favourites))
    t += 1100
    for i in (1, 2):
        plan.append((t, hl(i)))
        t += 600
    t += 500
    plan.append((t, play))
    return plan, t + 1300


def upnext_plan():
    """Open on a playlist queue, spin ahead and back, like a song, shuffle the rest, play: ~8.5 s."""
    from stills import upnext_payload
    state = {}

    def open_(rig):
        p = upnext_payload(rig.now(), SIM, now=4, liked=(1,), rows=24)
        state["p"] = p
        rig.presenter.upnext_open(p)

    def hl(i):
        return lambda rig: rig.presenter.upnext_highlight({"index": i, "control_id": 1, "bump": 0})

    def like(rig):
        p = state["p"]
        rig.presenter.upnext_rows({"t0": rig.now(), "reason": "likes", "rows": [{"row": 7, "liked": True}],
                                   "now": 4, "focus": 6, "count": p["count"], "card": None, "shuffle": "off",
                                   "likes_known": True})

    def shuffle(rig):
        p = state["p"]
        rest = p["rows"][5:]
        order = rest[1::2] + rest[0::2]                       # a deterministic "shuffle" of what is left
        rows = [dict(r, row=j + 1) for j, r in enumerate(p["rows"][:5] + order)]
        for r in rows:
            if r["title"] == p["rows"][6]["title"] and r["artist"] == p["rows"][6]["artist"]:
                r["liked"] = True
        state["p"] = dict(p, rows=rows)
        rig.presenter.upnext_rows({"t0": rig.now(), "reason": "shuffle", "rows": rows, "now": 4, "focus": 5,
                                   "count": p["count"], "card": None, "shuffle": "companion", "likes_known": True})

    def play(rig):
        rig.presenter.upnext_close({"t0": rig.now(), "reason": "play", "close_at_ms": 380})

    plan = [(400, open_)]
    t = 1500
    for i in (5, 6, 7, 8):
        plan.append((t, hl(i)))
        t += 380
    t += 250
    for i in (7, 6):
        plan.append((t, hl(i)))
        t += 200
    t += 500
    plan.append((t, like))
    t += 1000
    plan.append((t, shuffle))
    t += 1200
    plan.append((t, hl(6)))
    t += 550
    t += 300
    plan.append((t, play))
    return plan, t + 1300


# ------------------------------------------------------------------ the Windows picker
DESK_WINDOWS = ((0, (0.06, 0.1, 0.42, 0.62)), (1, (0.46, 0.18, 0.9, 0.8)), (4, (0.2, 0.55, 0.55, 0.92)))


class Picker:
    """The production CarouselPresenter on the golden tests' fake backend, stepped on its clock.
    Items, labels, thumbnails and the desktop's windows all come from fixtures.WINDOWS."""

    def __init__(self, ratio):
        sys.path.insert(0, str(Path(APP_DIR) / "tests"))
        import test_carousel_goldens as G
        import test_carousel_presenter as T
        from control_center import carousel as c
        from control_center import carousel_render as R
        self.G, self.R = G, R
        G.desktop = lambda size: fx.desktop(size)          # what the frost blurs (and capture returns)
        G.TABLES.setdefault("16x9@2x", (MON_2X, (0, 0, 2560, 1344)))     # the golden 16:9 table at 2x
        monitor, work = G.TABLES[ratio]
        self.monitor, self.work = monitor, work
        self.size = (monitor[2] - monitor[0], monitor[3] - monitor[1])
        self.clock = T.Clock()
        self.backend = G.GoldenBackend(monitor=monitor, work=work)
        self.backend.clock = self.clock
        self.capture = G.GoldenCapture(self.backend)
        self.snapper = T.FakeSnap()
        self.snapper.backend = self.backend
        self.p = c.CarouselPresenter(None, None, lambda: None, backend=self.backend, capture=self.capture,
                                     snap=self.snapper, clock=self.clock, inline=True)
        self.p.set_background("glass")
        self.p.set_labels({f"w{i}": R.SimpleLabel(a, t, d) for i, (a, t, d, _c, _k) in enumerate(fx.WINDOWS)})
        # the desktop: wallpaper and windows in z-order (bottom first): (window index, rect px)
        w, h = self.size
        self.wall = fx.wallpaper(self.size)
        self.stack = [(k, (int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h))) for k, (x0, y0, x1, y1) in DESK_WINDOWS]
        self._thumbs = {}
        self.showing = False

    def items(self):
        return [{"id": f"w{i}", "hwnd": 100 + i, "pid": 20, "app": a, "title": t, "available": True,
                 "minimized": False} for i, (a, t, _d, _c, _k) in enumerate(fx.WINDOWS)]

    def thumb(self, k, size):
        full = self._thumbs.get(k)
        if full is None:
            k2 = max(1.0, self.size[1] / 720)        # 2 on the 2x monitor, so thumbnails are never upscaled
            full = self._thumbs[k] = fx.window_thumb(k, (round(1600 * k2), round(1000 * k2)))
        return full.resize(size, Image.Resampling.BILINEAR)

    def raise_(self, k, rect):
        self.stack = [(j, r) for j, r in self.stack if j != k] + [(k, rect)]

    def desktop(self):
        base = self.wall.copy()
        for k, (l, t, r, b) in self.stack:
            base.paste(self.thumb(k, (r - l, b - t)), (l, t))
        return base

    def open(self, index):
        self.p.show({"items": self.items(), "index": index, "origin": {"hwnd": 100 + self.stack[-1][0], "pid": 20}})
        self.backend.activate()
        self.step()
        if self.capture.jobs:
            self.capture.complete()
        self.showing = True

    def step(self, seconds=0.0, dt=1 / 120):
        end = self.clock.t + seconds
        self.p._step_inline()
        while self.clock.t < end - 1e-9:
            self.clock.t = min(end, self.clock.t + dt)
            self.p._step_inline()

    def snap(self, index, side):
        self.p.snap({"t0": self.clock.t, "index": index, "side": side, "target_rect": None, "place_at_ms": 360,
                     "item": {"id": f"w{index}", "hwnd": 100 + index, "pid": 20}})
        self.step()
        job = self.snapper.jobs[-1]
        self.snapper.answer(job, "precheck", "accepted")
        return job

    def land(self, job, index, side):
        """NanoD-snap's final answer: the real window now sits in that rcWork half."""
        self.snapper.answer(job, "final", "ok")
        self.raise_(index, tuple(int(v) for v in self.p.half_rect(side)))

    def image(self):
        G, R, backend = self.G, self.R, self.backend
        base = self.desktop()
        if not self.showing:
            return base
        w, h = self.size
        if backend.glass_image is not None:
            G._over(base, backend.glass_image, backend.glass_rect[:2], G._alpha(backend.glass_level))
        for handle in backend.order:
            if handle not in backend.props:
                continue
            dest, _source, opacity, visible = backend.props[handle]
            if not visible or opacity <= 0:
                continue
            l, t, r, b = dest
            if r <= l or b <= t:
                continue
            k = (backend.thumbs.get(handle, 0) - 100) % len(fx.WINDOWS)
            base.paste(self.thumb(k, (r - l, b - t)), (l, t), Image.new("L", (r - l, b - t), opacity))
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


def picker_frames(ratio, out_size, fps=FPS):
    """Open on the window you are in (Ledger), snap Chatter left and Shell right, then switch to
    Canvas: ~9 s."""
    pk = Picker(ratio)
    frames = []

    def hold(seconds):
        for _ in range(round(seconds * fps)):
            img = pk.image()
            frames.append(img if img.size == out_size else img.resize(out_size, Image.Resampling.LANCZOS))
            pk.step(1 / fps)

    hold(0.3)
    pk.open(0)                              # opens on the window you are in (Ledger)
    hold(0.8)
    for i in (1, 2, 3):
        pk.p.highlight(i)
        hold(0.4)
    job = pk.snap(3, "left")                # Snap left: Chatter flies into the left half
    hold(0.45)
    pk.land(job, 3, "left")
    hold(0.6)
    for i in (4, 5):
        pk.p.highlight(i)
        hold(0.4)
    job = pk.snap(5, "right")               # Snap right: Shell takes the second half; the pair is complete
    hold(0.45)
    pk.land(job, 5, "right")
    hold(0.3)
    pk.p.play_pair_exit()                   # the adapter's pair close: focus, exit, hide
    pk.p.hide()
    hold(0.5)
    pk.showing = False
    hold(0.9)                               # the two windows side by side
    pk.open(0)                              # a plain Switch
    hold(0.6)
    for i in (1, 2):
        pk.p.highlight(i)
        hold(0.4)
    hold(0.2)
    target = 2                              # Canvas
    pk.p.play_switch_exit()
    pk.p.hide()
    w, h = pk.size
    pk.raise_(target, (int(0.18 * w), int(0.12 * h), int(0.82 * w), int(0.88 * h)))
    hold(0.5)
    pk.showing = False
    hold(0.6)
    pk.p.close()
    return frames


# ------------------------------------------------------------------ entry
JOBS = {
    "explorer-16x9": lambda: (run_stage(MON_2X, *explorer_plan(), SIZE_2X, fps=FPS_2X), FPS_2X),
    "explorer-32x9": lambda: (run_stage((0, 0, 2560, 720), *explorer_plan(), SIZE_32x9), FPS),
    "upnext-16x9": lambda: (run_stage((0, 0, 1280, 720), *upnext_plan(), SIZE_16x9), FPS),
    "picker-16x9": lambda: (picker_frames("16x9@2x", SIZE_2X, fps=FPS_2X), FPS_2X),
    "picker-32x9": lambda: (picker_frames("32x9", SIZE_32x9), FPS),
}


def render(out_dir, work, which):
    """[(name, frame count, webp, gif)] for every name of ``which`` (keys of JOBS)."""
    out_dir, work = Path(out_dir), Path(work)
    results = []
    for name in which:
        frames, fps = JOBS[name]()
        for k in (len(frames) // 5, len(frames) // 2, 4 * len(frames) // 5):
            frames[k].save(work / f"fs-{name}-{k}.png")
        results.append((name, len(frames), fps) + encode(frames, fps, f"desktop-{name}", out_dir))
    return results


def _scene(which, source):
    def run(ctx) -> list[Path]:
        out = []
        for stem, n, fps, webp, gif in render(ctx.out, ctx.work, [which]):
            ctx.log(f"{stem}: {n} frames at {fps} fps ({n / fps:.1f} s), webp {webp.stat().st_size} B, "
                    f"gif {gif.stat().st_size} B")
            out += [ctx.produced(webp, source), ctx.produced(gif, source)]
        return out
    return run


SCENES = {
    "desktop-explorer-16x9": (STAGE, _scene("explorer-16x9", STAGE)),
    "desktop-explorer-32x9": (STAGE, _scene("explorer-32x9", STAGE)),
    "desktop-upnext-16x9": (STAGE, _scene("upnext-16x9", STAGE)),
    "desktop-picker-16x9": (CAROUSEL, _scene("picker-16x9", CAROUSEL)),
    "desktop-picker-32x9": (CAROUSEL, _scene("picker-32x9", CAROUSEL)),
}
