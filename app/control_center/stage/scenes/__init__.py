"""The music scenes on the stage (DESKTOP_STAGE §7, §8, §13; WP8).

- ``explorer.ExplorerScene`` and ``upnext.UpNextScene``: ``presenter.Scene`` implementations.
- ``art.ArtService``: the ``NanoD-art-1`` / ``-2`` workers (the art lane) and ``NanoD-art-fast`` (ticks and
  text, never network I/O), the C2 cache, the simulator's covers.
- ``SceneFactory``: what ``StageEngine`` gets per surface; ``ambient_source`` (the engine's first
  call at ``*_open`` t = 0, before the capture) also starts the open's sprites on the art workers
  (into ``common.Prepared``), so ``build`` finds them ~50 ms later.
- ``start_music_stage``: the ``NanoD-stage`` thread with both scenes, its ``StagePresenter`` and
  the art service. The shell wiring is WP10's (``music_overlay.MusicOverlay`` wraps the presenter).
"""
from __future__ import annotations

import os
from pathlib import Path

from ... import scene_music as SM
from .art import ArtService, SimulatedCovers
from .common import Prepared, PreparedQueue, prepare_statics
from .explorer import ExplorerScene, explorer_planner
from .upnext import UpNextScene, left_text_job, upnext_planner

__all__ = ("ExplorerScene", "UpNextScene", "ArtService", "SceneFactory", "make_scenes", "start_music_stage",
           "default_covers_dir")


def default_covers_dir():
    """The prototype's covers in a dev checkout (the simulator draws them); None when absent."""
    root = Path(__file__).resolve().parents[3]
    d = root / "design-reference" / "design_handoff_nano_d_master_r2.2" / "prototypes" / "assets" / "covers"
    return str(d) if d.is_dir() else None


class SceneFactory:
    """``factory(ctx, payload)`` builds the scene; ``ambient_source(payload)`` is the §4.9 hook."""

    def __init__(self, cls, art=None, prepared=None, *, layout_for=None, lru_for=None):
        self.cls = cls
        self.art = art
        self.prepared = prepared if prepared is not None else Prepared()
        self.layout_for = layout_for          # payload -> StageLayout (the monitor the open will use), or None
        self.lru_for = lru_for                # () -> the engine's SurfaceLRU (stage thread), or None
        self.last_layout = None
        self.prefetches = 0
        self._first_ambient = None           # (id(payload), what ambient_source returned at t = 0)

    def __call__(self, ctx, payload):
        self.last_layout = ctx.layout
        scene = self.cls(ctx, payload, self.art, self.prepared)
        fa = self._first_ambient
        if fa is not None and fa[0] == id(payload):
            scene.first_ambient_src = fa[1]  # the scene tells a 64 px copy from an art_bg layer (WP8-R4)
        self._first_ambient = None
        return scene

    def ambient_source(self, payload):
        try:
            self.prefetch(payload)
        except Exception:
            pass
        src = self.cls.ambient_source(payload, self.art)
        self._first_ambient = (id(payload), src)
        return src

    def _layout(self, payload):
        lay = None
        if self.layout_for is not None:
            try:
                lay = self.layout_for(payload)
            except Exception:
                lay = None
        return lay or self.last_layout

    def prefetch(self, payload):
        """The open's sprites at t = 0 on the art workers, kept as bytes (``Prepared``)."""
        if self.art is None:
            return
        lay = self._layout(payload)
        if lay is None:
            return
        resident = frozenset()
        if self.lru_for is not None:
            try:
                lru = self.lru_for()
                resident = frozenset(lru.items) if lru is not None else frozenset()
                dev = getattr(lru, "dev", None)
                aux = getattr(dev, "_music_aux_lru", None)
                if aux is not None:
                    resident = resident | frozenset(aux.items)
            except Exception:
                resident = frozenset()
        target = (PreparedQueue(self.prepared), None)
        self.prefetches += 1
        self.art.warm(lay.k)
        specs = getattr(self.cls, "static_specs", None)
        if specs is not None:
            prepare_statics(self.art, specs(lay, payload))      # CPU bytes on the fast lane (WP8-R10)
        if self.cls.surface == "explorer":
            snap = explorer_snapshot(payload, lay, resident, target)
            if snap is not None:
                self.art.plan(("prefetch", "explorer"), explorer_planner, snap)
        else:
            snap = upnext_snapshot(payload, lay, resident, target)
            if snap is not None:
                self.art.plan(("prefetch", "upnext"), upnext_planner, snap)
            job = left_text_job(payload, lay.k, target, owner=("prefetch", "upnext"))
            if job.key not in resident:
                self.art.add(job)


def explorer_snapshot(payload, lay, resident, target):
    """The planner snapshot of an ``explorer_open`` / ``explorer_source`` payload (the focus ± 3
    of the preload window: what the open shows first)."""
    from .explorer import LABEL_PREFETCH
    state = payload.get("state")
    if state in SM.BLOCK_STATES:
        return None
    first = int(payload.get("items_first") or 0)
    items = {first + j: d for j, d in enumerate(payload.get("items") or ()) if isinstance(d, dict)}
    focus = int(payload.get("index") or 0)
    source = payload.get("source")
    n = payload.get("count") if isinstance(payload.get("count"), int) else None
    lo, hi = SM.preload_window(focus, n, lay.wide, 0)
    order = [i for i in SM.build_order(focus, lo, hi, 0) if i in items]
    plans = {i: SM.explorer_plan(items[i], source) for i in order}
    l0set = frozenset(SM.l0_indices(focus, n, 0))
    labels = [(i, SM.explorer_label(items[i], source)) for i in range(focus - LABEL_PREFETCH, focus + LABEL_PREFETCH + 1)
              if i in items] if state != "loading" else []
    return (focus, 0, order, plans, l0set, labels, resident,
            (SM.upx(lay, SM.L1_UNITS), SM.card_size(lay), lay.k), target, SM.CARD_UNITS)


def upnext_snapshot(payload, lay, resident, target):
    from .upnext import ROW_WINDOW, row_spec
    rows = SM.rows_by_index(payload.get("rows"))
    count = int(payload.get("count") or 0)
    if count <= 0:
        return None
    focus = max(0, min(count - 1, int(payload.get("focus") or 0)))
    now = int(payload.get("now") or 0)
    ctx = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    card = payload.get("card")
    likes = bool(payload.get("likes_known"))
    lo, hi = max(0, focus - ROW_WINDOW), min(count - 1, focus + ROW_WINDOW)
    order = sorted(range(lo, hi + 1), key=lambda i: (abs(i - focus), i))
    specs = [(i, row_spec(i, rows, now, count, card, ctx, likes)) for i in order]
    row = SM.big_cover_row(rows, focus, now, ctx)
    covers = [SM.big_cover_plan(row)]
    return (focus, specs, covers, resident, (lay.k, SM.upx(lay, SM.U_LEAD_ART), SM.upx(lay, SM.U_COVER)), target)


def make_scenes(art=None, *, layout_for=None, lru_for=None):
    """The ``scenes`` dict for ``StageEngine`` / ``StageThread``."""
    prepared = Prepared()
    return {"explorer": SceneFactory(ExplorerScene, art, prepared, layout_for=layout_for, lru_for=lru_for),
            "upnext": SceneFactory(UpNextScene, art, prepared, layout_for=layout_for, lru_for=lru_for)}


def start_music_stage(*, log=None, cover_store=None, speaker_hosts=None, covers_dir=None, fetch=True, **thread_kw):
    """Start ``NanoD-stage`` with the explorer and Up next (Windows): returns (StageThread,
    StagePresenter, ArtService). ``cover_store`` defaults to a new WP6 ``artwork.CoverStore``
    (C1) when ``fetch``; ``speaker_hosts`` is a callable returning the Sonos hosts whose
    ``/getaa`` covers may be fetched; ``covers_dir`` feeds the simulator's covers."""
    from ..engine import StageThread
    from ..presenter import StagePresenter
    if cover_store is None and fetch:
        from ...artwork import CoverStore
        cover_store = CoverStore()
    art = ArtService(cover_store=cover_store, speaker_hosts=speaker_hosts,
                     simulated=SimulatedCovers(covers_dir if covers_dir is not None else default_covers_dir()),
                     log=log)
    holder = {}

    def layout_for(payload):
        from ..engine import _default_monitor_for
        from ..layout import StageLayout
        mon = _default_monitor_for(payload.get("foreground_hwnd"))
        if not mon:
            return None
        rect = mon["rect"] if isinstance(mon, dict) else mon
        return StageLayout(rect)

    def lru_for():
        th = holder.get("thread")
        eng = getattr(th, "engine", None)
        return getattr(eng, "lru", None)

    scenes = make_scenes(art, layout_for=layout_for, lru_for=lru_for)
    thread = StageThread(scenes, log=log, **thread_kw)
    holder["thread"] = thread
    return thread, StagePresenter(thread), art
