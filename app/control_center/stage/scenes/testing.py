"""Headless rigs for the music scenes (DESKTOP_STAGE §4.8, §6.6 H1, H4, H7, H8): the stage engine on
the fake device (which here keeps every surface's pixels, for the PIL reference renderer), a fake
host, a synchronous capture, a synchronous art service on the same fake clock, and payloads built
from the simulator's library (``control_center.simulation``: the r2.2 BS state picker's data).

Nothing here touches a window, the GPU, the network or the screen.
"""
from __future__ import annotations

import time

from ... import render_music as RM
from ... import scene_music as SM
from .. import clock as CK
from .. import fake as F
from ..engine import StageEngine
from ..presenter import Mailbox, StagePresenter
from . import make_scenes
from .art import ArtService, SimulatedCovers

MONITORS = {"32:9": (0, 0, 5120, 1440), "16:9": (0, 0, 2560, 1440)}


class KeepingDevice(F.FakeDevice):
    """The fake device, keeping each surface's full BGRA bytes (``pixels``)."""

    def upload(self, surface, w, h, data, name=""):
        super().upload(surface, w, h, data, name)
        self.objects[surface]["pixels"] = bytes(data)
        self.objects[surface].pop("_sprite", None)


class SceneRig:
    """The engine with the music scenes on fakes. ``capture`` = "gradient" (a synthetic desktop)
    or None (the tint-only frost). ``art_sync``: the art jobs run when ``settle`` runs them."""

    def __init__(self, monitor="32:9", *, capture="gradient", keep_pixels=True, covers_dir=None, sim_covers=True):
        self.clk = F.FakeClock()
        self.devices = []
        self.mailbox = Mailbox()
        self.monitor = MONITORS.get(monitor, monitor)
        self.art = ArtService(sync=True, clock=self.clk.perf,
                              simulated=SimulatedCovers(covers_dir) if sim_covers else None)
        self.logs = []

        def device_factory():
            d = (KeepingDevice if keep_pixels else F.FakeDevice)(self.clk)
            self.devices.append(d)
            return d

        self.scenes = make_scenes(self.art, layout_for=None, lru_for=lambda: getattr(self.engine, "lru", None))
        self.engine = StageEngine(
            self.mailbox, self.scenes, device_factory=device_factory,
            host_factory=lambda h: F.FakeHost(h),
            clock_factory=lambda d: CK.StageClock(d.time_frequency, d.time_frequency, qpc=self.clk, perf=self.clk.perf),
            monitor_for=lambda hwnd: self.monitor,
            capture_factory=lambda cb: F.SyncCapture(cb, grab=capture),
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

    # ------------------------------------------------------------------ driving
    @property
    def dev(self):
        return self.devices[-1]

    @property
    def scene(self):
        return self.engine.scene

    def now(self):
        return self.clk.perf()

    def _upload_wake_ticks(self):
        """Ticks until the upload queue needs the stage thread (its ripening and paced upload
        wakes, ``surfaces.UploadQueue``), or None."""
        up = self.engine.uploads
        w = up.next_wake_s() if up is not None else None
        if w is None:
            return None
        return max(1, int(-(-w * self.clk.freq // 1)))

    def settle(self, rounds=8):
        """Run the engine, then the due art jobs, until nothing more happens now (fake time
        stands still: an upload waiting for its pacing or ripening waits for ``advance``)."""
        for _ in range(rounds):
            self.engine.process()
            n = self.art.run_pending()
            up = self.engine.uploads
            w = up.next_wake_s() if up is not None else None
            if not n and (w is None or w > 0.0):
                break
        self.engine.process()

    def land(self, max_ms=250.0):
        """Fake time passes until what was posted so far has landed (S1: the paced upload wake, its
        own Commit, the reveal a frame later): the stage thread's upload wakes only, at most
        ``max_ms``. Returns the ms that passed."""
        t0 = self.clk.t
        end = t0 + int(round(max_ms * self.clk.freq / 1000.0))
        self.settle()
        while self.clk.t < end:
            up = self.engine.uploads
            w = self._upload_wake_ticks()
            if up is None or w is None or not up.busy():
                break
            self.clk.t = min(end, self.clk.t + w)
            self.settle()
        return (self.clk.t - t0) * 1000.0 / self.clk.freq

    def advance(self, ms, step_ms=None):
        """Fake time passes (the art's debounces and ticks come due). Inside each step the stage
        thread also wakes when its upload queue asks (S1's paced upload wakes and the reveals a
        frame later), as ``StageThread`` does with the engine's next wake."""
        step = step_ms or ms
        left = int(round(ms * self.clk.freq / 1000.0))
        step_t = max(1, int(round(step * self.clk.freq / 1000.0)))
        while left > 0:
            end = self.clk.t + min(step_t, left)
            left -= min(step_t, left)
            while True:
                w = self._upload_wake_ticks()
                if w is None or self.clk.t + w >= end:
                    break
                self.clk.t += w
                self.settle()
            self.clk.t = end
            self.settle()

    def events(self):
        return [(k, {x: y for x, y in p.items() if x != "t0"}) for k, p in self.mailbox.take_events()]

    def render(self, at_ms=None, scale=1.0):
        """The PIL reference render of the host at now + ``at_ms`` (an RGB image)."""
        t = self.clk.t + int(round((at_ms or 0) * self.clk.freq / 1000.0))
        r = RM.ReferenceRenderer(self.dev, self.clk.freq)
        img = r.render(self.engine.root.ptr, (self.monitor[2] - self.monitor[0], self.monitor[3] - self.monitor[1]), t)
        if scale != 1.0:
            img = img.resize((int(img.size[0] * scale), int(img.size[1] * scale)), RM.Image.Resampling.BOX)
        return img


# --------------------------------------------------------------------------- payloads from the simulator
def sim_apple(**controls):
    from ...simulation import SimControls, SimulatedAppleMusic
    c = SimControls()
    for k, v in controls.items():
        setattr(c, k, v)
    return SimulatedAppleMusic(c, clock=lambda: 0.0, sleep=lambda s: None), c


def explorer_payload(t0, *, source="recent", index=0, art="full", favs="real", recent="normal", state=None,
                     count=None, items=None, control_id=1, reduced_motion=False, window=True):
    """An ``explorer_open`` payload with every K4 §2.3 field, from the simulator's library."""
    am, _c = sim_apple(art=art, favs=favs, recent=recent)
    if items is None:
        if source == "favourites":
            items = am.favourite_playlists()
            for it in items:
                try:
                    meta = am.playlist_meta(it["id"], duration=True)
                    it.update({k: meta[k] for k in ("count", "mosaic", "art_state", "first_art", "duration_ms")})
                except Exception:
                    pass
        else:
            try:
                items = am._library()
            except Exception:
                items = []
    items = [{k: v for k, v in it.items() if not k.startswith("_")} for it in items]
    n = len(items)
    if state is None:
        state = "ready" if n else "empty"
    first = 0
    shown = items
    if window and n:
        first = max(0, index - 12)
        shown = items[first:min(n, index + 17)]
    return {"t0": t0, "source": source, "state": state, "index": index,
            "count": (n if count is None else count) if state != "loading" else None,
            "items": shown if state not in SM.BLOCK_STATES + ("loading",) else [], "items_first": first,
            "items_rev": 1,
            "control_id": control_id, "control_min": 0, "reduced_motion": reduced_motion, "foreground_hwnd": 0,
            "sonos_available": True}


def upnext_payload(t0, *, kind="album", rows=24, now=4, focus=None, loaded=True, likes="known", foreign=False,
                   card=None, shuffle="off", art="full", control_id=1, reduced_motion=False, liked=()):
    """An ``upnext_open`` payload (K3 §11.1) from the simulator's library: an album queue
    (``kind="album"``: rows of one album with track numbers), a playlist (every row its own
    cover) or a foreign queue (every third row not in Apple Music)."""
    from ...simulation import ALBUMS, TRACKS, _song_id, art_keys, dur_of
    out = []
    count = rows
    for k in range(rows):
        if kind == "album":
            al = 4
            name = TRACKS[al][k % len(TRACKS[al])]
        else:
            al = [1, 6, 2, 3, 5, 8, 0, 7][k % 8]
            name = TRACKS[al][k % len(TRACKS[al])]
        title, artist, year, colour = ALBUMS[al]
        song = _song_id(al, TRACKS[al].index(name))
        nc = foreign and k % 3 == 2
        keys = art_keys(art, k, f"s{song}", colour) if not nc else {"art_template": "", "art_max": 0, "art_bg": 0,
                                                                      "art_ink": 0}
        r = {"row": k + 1, "title": name, "artist": artist, "album": title, "song_id": None if nc else song,
             "catalog": False if nc else True, "duration_s": dur_of(name), "track_number": (k % 12) + 1,
             "sonos_art": "", "segment": "base" if kind == "album" else ("foreign" if foreign else "base"),
             "liked": (None if likes != "known" else k in liked), **keys}
        if nc:
            r["sonos_art"] = ""
        out.append(r)
    if not loaded:
        out = [r for r in out if r["row"] - 1 == now]
    if kind == "album":
        ctx = {"kind": "album", "title": ALBUMS[4][0], "sub": f"{ALBUMS[4][1]} · {ALBUMS[4][2]}"}
    elif foreign:
        ctx = {"kind": "foreign", "title": "Sonos queue", "sub": f"Started in another app · {rows} songs"}
    else:
        ctx = {"kind": "playlist", "title": "Late Night Channel", "sub": "Favourite playlist · 48 songs · 3 h 12 min"}
    if card is not None:
        count = now + 2
        out = [r for r in out if r["row"] - 1 <= now]
    return {"t0": t0, "rows": out, "now": now, "focus": now if focus is None else focus, "count": count,
            "card": card, "context": ctx, "shuffle": shuffle, "likes_known": likes == "known",
            "loading": not loaded, "control_id": control_id, "control_min": 0, "reduced_motion": reduced_motion,
            "foreground_hwnd": 0}
