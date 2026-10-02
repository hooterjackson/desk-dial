"""The stage rig shared by the desktop scenes (desktop_fullscreen.py, navigator_scene.py, stills.py).

* Rig: the companion's own stage engine (control_center.stage) on its fake device and fake clock,
  with the simulator's library replaced in place by the fictional one in fixtures.py.
* FictionalCovers: every simulated cover template resolves to one of fixtures' procedural sleeves
  (never a download); the Navigator's cover pipeline (navigator_scene.py) uses it too.
* DesktopCapture: the frost's desktop grab, answered with fixtures' synthetic desktop.
* over_desktop(rig, desk): the overlay at the rig's now, drawn by the app's PIL reference renderer
  (DESKTOP_STAGE section 4.8) and composited over ``desk`` with the overlay's own alpha.

The floating-knob and the small (720 px) explorer clips that used to live here are gone: the
README's desktop clips are the full-screen ones in desktop_fullscreen.py and the Navigator in
navigator_scene.py. Nothing reads the real screen, and no window is created.
"""
from __future__ import annotations

from PIL import Image, ImageChops

import fixtures as fx
import companion  # noqa: F401  (puts the app on sys.path)
from control_center import simulation as SIM

SIM.ALBUMS[:] = [(t, a, y, c) for t, a, y, c, _s in fx.ALBUMS]
SIM.TRACKS[:] = [list(t) for t in fx.TRACKS]
# The last field is the simulator's "auto" flag: True would subtitle the playlist with the real
# streaming service's name ("made by ..."), so every fictional playlist is a plain one.
SIM.PLAYLISTS[:] = [(fx.PLAYLISTS[0][0], fx.PLAYLISTS[0][1], fx.PLAYLISTS[0][2], fx.PLAYLISTS[0][3], None, False),
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
    """Every simulated template resolves to one of fixtures' procedural covers (never a download).
    Identities: ``al<N>`` (album N), ``pl-<digest>`` (a fixtures playlist: its first album),
    ``s<song id>`` and ``a<N>`` (the simulator's song / artist ids)."""

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
