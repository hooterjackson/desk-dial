"""Desktop animations.

* explorer: the Music explorer overlay opening, browsing Recently Added and closing, rendered by
  the companion's own stage engine on its fake device and fake clock and drawn by its PIL reference
  renderer (DESKTOP_STAGE section 4.8), composited over a synthetic desktop with the overlay's own
  alpha. The simulator's library is replaced in place by the fictional one in fixtures.py; covers
  are fixtures' procedural sleeves; the desktop behind the frost is fixtures' synthetic wallpaper
  and windows.
* floating: the floating knob (the app's AliveFace with the same LED engine, and the firmware's LCD
  renderer) sliding in at the left edge of the desktop when the knob is turned and out 2.5 s after
  the last touch (FLOATING_KNOB.md: 24 px from the work area's left edge, 220 ms ease-out cubic in,
  260 ms ease-in cubic out, fading with the slide).

Nothing reads the real screen, and no window is created.
"""
from __future__ import annotations

from PIL import Image, ImageChops, ImageDraw

import fixtures as fx
import companion  # noqa: F401  (puts the app on sys.path)
from control_center import simulation as SIM

SIM.ALBUMS[:] = [(t, a, y, c) for t, a, y, c, _s in fx.ALBUMS]
SIM.TRACKS[:] = [list(t) for t in fx.TRACKS]
SIM.PLAYLISTS[:] = [(fx.PLAYLISTS[0][0], fx.PLAYLISTS[0][1], fx.PLAYLISTS[0][2], fx.PLAYLISTS[0][3], None, True),
                    (fx.PLAYLISTS[1][0], fx.PLAYLISTS[1][1], fx.PLAYLISTS[1][2], fx.PLAYLISTS[1][3], None, False)]
SIM.MORE_PLAYLISTS[:] = [(t, al, c, n) for t, al, c, n in fx.PLAYLISTS[2:]]
SIM.WINDOWS[:] = [(a, t, c) for a, t, _d, c, _k in fx.WINDOWS]

from control_center import render_music as RM  # noqa: E402
from control_center.stage import clock as CK  # noqa: E402
from control_center.stage import fake as F  # noqa: E402
from control_center.stage.engine import StageEngine  # noqa: E402
from control_center.stage.presenter import Mailbox, StagePresenter  # noqa: E402
from control_center.stage.scenes import make_scenes  # noqa: E402
from control_center.stage.scenes import testing as TS  # noqa: E402
from control_center.stage.scenes.art import ArtService, SimulatedCovers  # noqa: E402

PLAYLIST_ALBUM = {"pl-" + SIM._digest(t)[:8]: al[0] for t, al, _c, _n in fx.PLAYLISTS}
_COVERS = {}


def album_cover(index, edge):
    key = (index, edge)
    if key not in _COVERS:
        src = _COVERS.get((index, 1200))
        if src is None:
            src = _COVERS[(index, 1200)] = fx.cover(index, 1200)
        _COVERS[key] = src if edge == 1200 else src.resize((edge, edge), Image.Resampling.LANCZOS)
    return _COVERS[key]


class FictionalCovers(SimulatedCovers):
    """Every simulated template resolves to one of fixtures' procedural covers (never a download)."""

    def draw(self, template, rung, art_max, item):
        edge = max(600, min(int(rung), int(art_max or rung)))
        ident = template.split("/")[3] if template.count("/") >= 3 else template
        album = None
        try:
            if ident.startswith("al"):
                album = int(ident[2:])
            elif ident.startswith("pl-"):
                album = PLAYLIST_ALBUM.get(ident)
            elif ident.startswith("s") and ident[1:].isdigit():
                album = (int(ident[1:]) - 1_400_000_000) // 1000
            elif ident.startswith("a") and ident[1:].isdigit():
                album = int(ident[1:]) % len(fx.ALBUMS)
        except ValueError:
            album = None
        if album is None:
            return super().draw(template, rung, art_max, item)
        return album_cover(album % len(fx.ALBUMS), edge).copy()


class DesktopCapture:
    """The frost's desktop grab, answered with fixtures' synthetic desktop (never the real screen)."""

    def __init__(self, on_result):
        from control_center.stage.capture import StageCaptureWorker
        self.on_result = on_result
        self.worker = StageCaptureWorker(on_result, grab=lambda rect: fx.desktop((int(rect[2]), int(rect[3]))),
                                         affinity=lambda hwnds, on: True, start=False)

    def submit(self, job):
        self.on_result(self.worker.run_job(job))
        return True

    def close(self, timeout=None):
        return True


class Rig(TS.SceneRig):
    def __init__(self, monitor):
        self.clk = F.FakeClock()
        self.devices = []
        self.mailbox = Mailbox()
        self.monitor = monitor
        self.art = ArtService(sync=True, clock=self.clk.perf, simulated=FictionalCovers(None))
        self.logs = []

        def device_factory():
            d = TS.KeepingDevice(self.clk)
            self.devices.append(d)
            return d

        self.scenes = make_scenes(self.art, layout_for=None, lru_for=lambda: getattr(self.engine, "lru", None))
        self.engine = StageEngine(
            self.mailbox, self.scenes, device_factory=device_factory,
            host_factory=lambda h: F.FakeHost(h),
            clock_factory=lambda d: CK.StageClock(d.time_frequency, d.time_frequency, qpc=self.clk, perf=self.clk.perf),
            monitor_for=lambda hwnd: self.monitor,
            capture_factory=lambda cb: DesktopCapture(cb),
            log=self.logs.append, monotonic=self.clk.perf)
        self.engine.start()
        eng = self.engine

        class Facade:
            mailbox = self.mailbox

            def metrics(self):
                return eng.metrics()

            def close(self, timeout):
                return True
        self.presenter = StagePresenter(Facade())


MONITOR = (0, 0, 1920, 1080)


def over_desktop(rig, desk):
    """The overlay at the rig's now, composited over ``desk`` with its own (premultiplied) alpha."""
    r = RM.ReferenceRenderer(rig.dev, rig.clk.freq)
    canvas = RM._Canvas(desk.size, None)
    r._draw(rig.engine.root.ptr, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), 1.0, canvas, rig.clk.t, 0)
    inv = ImageChops.invert(canvas.a)
    return ImageChops.add(ImageChops.multiply(desk, Image.merge("RGB", (inv, inv, inv))), canvas.pm)


def explorer_frames(fps=30, width=720):
    """Open on item 3, browse right to 8, back to 3, close; the desktop around it."""
    rig = Rig(MONITOR)
    desk_full = fx.desktop((1920, 1080))
    size = (width, round(1080 * width / 1920))
    desk = desk_full.resize(size, Image.Resampling.LANCZOS)
    plan = []                                   # (ms, action)
    t = 500
    plan.append((t, ("open", 2)))
    t += 1300
    for i in range(3, 8):
        plan.append((t, ("hl", i)))
        t += 650
    t += 200
    for i in range(6, 1, -1):
        plan.append((t, ("hl", i)))
        t += 170
    t += 900
    plan.append((t, ("close", None)))
    end = t + 1100
    out = []
    step = 1000 / fps
    k = 0
    pi = 0
    now_ms = 0.0
    while now_ms < end:
        while pi < len(plan) and plan[pi][0] <= now_ms:
            kind, arg = plan[pi][1]
            if kind == "open":
                rig.presenter.explorer_open(TS.explorer_payload(rig.now(), index=arg, art="full"))
            elif kind == "hl":
                rig.presenter.explorer_highlight({"index": arg, "control_id": 1, "bump": 0})
            elif kind == "close":
                rig.presenter.explorer_close({"t0": rig.now(), "reason": "back", "close_at_ms": 0})
            rig.settle()
            pi += 1
        if rig.engine.root is not None:
            out.append(over_desktop(rig, desk_full).resize(size, Image.Resampling.LANCZOS))
        else:
            out.append(desk.copy())
        k += 1
        target = k * step
        rig.advance(target - now_ms, step_ms=target - now_ms)
        now_ms = target
    return out, fps


def _ease_out(p):
    return 1 - (1 - p) ** 3


def _ease_in(p):
    return p ** 3


def floating_frames(knob_anim, work, width=720):
    """The left half of a 1920 x 1080 desktop (960 x 540 around its middle), the floating knob at 96 DPI."""
    import knob_scenes as K
    from companion import kf
    F = K.Frames()
    tl = K.Timeline("floating", duration=6600, preroll=3000)
    tl.frame(-2800, F.home(48))
    first_touch = 700
    t = K.turn(tl, F, first_touch, 48, 58, every=90, make=lambda v: F.home(v, reveal=True))
    last_touch = t - 90
    tl.frame(t + 1100, F.home(58))
    lcd = K.render_lcd(tl, knob_anim, work)
    leds = K.render_leds(tl)
    k_out = width / 960
    rects = [(0.30, 0.20, 0.62, 0.70, 0), (0.42, 0.42, 0.80, 0.92, 1)]
    desk = fx.desktop((1920, 1080), rects).crop((0, 270, 960, 810)).resize((width, round(540 * k_out)),
                                                                          Image.Resampling.LANCZOS)
    face = kf.AliveFace(kf.scale_for(96) * k_out, kf.glow_scale_for(96) * k_out)
    ss = 4
    m = Image.new("L", (face.lcd_px * ss,) * 2, 0)
    ImageDraw.Draw(m).ellipse((0, 0, face.lcd_px * ss - 1, face.lcd_px * ss - 1), fill=255)
    lcd_mask = m.resize((face.lcd_px,) * 2, Image.Resampling.LANCZOS)
    W, H = face.size
    wx = round(24 * k_out)
    wy = round((540 - 270) * k_out - H / 2)
    out = []
    for k, c in enumerate(K.capture_times(tl)):
        if c < first_touch:
            p = 0.0
        elif c < last_touch + 2500:
            p = _ease_out(min(1.0, (c - first_touch) / 220))
        else:
            p = 1 - _ease_in(min(1.0, (c - last_touch - 2500) / 260))
        img = desk.copy()
        if p > 0:
            lcd_k = lcd[k].resize((face.lcd_px,) * 2, Image.Resampling.LANCZOS).convert("RGBA")
            lcd_k.putalpha(lcd_mask)
            fimg = face.compose(lcd_k, leds[k][0])
            dx = round(W * (1 - p))
            part = fimg.crop((dx, 0, W, H))
            alpha = part.getchannel("A").point(lambda v, p=p: int(v * p))
            img.paste(part.convert("RGB"), (wx, wy), alpha)
        out.append(img)
    return out, tl.fps


def render(knob_anim, work, out_dir, which="explorer"):
    import knob_scenes as K
    if which == "explorer":
        imgs, fps = explorer_frames()
        stem = "desktop-explorer"
    else:
        imgs, fps = floating_frames(knob_anim, work)
        stem = "desktop-floating-knob"
    imgs[len(imgs) // 3].save(work / f"{stem}-peek.png")
    return K.save_animation(imgs, fps, stem, out_dir)


