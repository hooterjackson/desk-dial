"""Headless per-detent bench of the music scenes (DESKTOP_STAGE §6.3 "Python work: per detent, wake ->
Commit <= 1.5 ms p95", §6.6 H5; [G1] G1-4 "H5 gates it on the 32:9 table at 20 detents/s").

    cd app
    .venv\\Scripts\\python.exe -I control_center\\stage\\scenes\\bench.py [--scene explorer|upnext]
        [--device native|fake] [--table 32:9|16:9] [--rate 20] [--art on|off] [--hog none|burst]
        [--runs N] [--json PATH]

Run it by path: under ``-I`` neither the working directory nor the script's folder is on
``sys.path``, so ``-m control_center.stage.scenes.bench`` cannot find the package (``-m`` works
without ``-I``, from the project folder); run by path, the module puts the project root on
``sys.path`` itself and runs as part of its package. R-k reads the gate over ``--runs 5`` or more:
``summary.median_p95_ms`` is the median of the runs' warm p95 (the mean of the two middle ones
for an even count), next to each run's build p95 (wake -> the ``Commit`` call) and ``Commit``
p95.

The explorer (or Up next) is built on a **device without a target** (no window, nothing shown),
opened, then driven by the K3 highlight payloads a spin produces (the index, and the preload
window's descriptors whenever the window moves, from the simulator's 100-item library): 20
forward, 20 back, 20 reversals at ``--rate`` detents/s, with real time passing so every retarget
starts from a curve in flight; the script runs twice, cold then warm (§6.3 gates the warm
prepared-sprite cache and records the cold one). Each detent is measured as the stage measures it: wake ->
``GetFrameStatistics`` (t1) -> the scene's calls -> ``Commit`` returned. With ``--art on`` the
art workers (``NanoD-art-1/2``) run for real meanwhile (decode, sleeves, labels on worker
threads: the GIL contention the input path meets on the user's PC), and their uploads land in
their own batches between detents, as the engine runs them. ``--hog burst`` adds §6.4's stress
thread. A target-less device does not show DWM's side of ``Commit``. It does show
DirectComposition's periodic ``Commit`` (about every 256 ms while animations are in flight,
0.3-1.2 ms on the calling thread whatever the batch holds; WP7a's probe bench shows it too), which
lands on about 1 detent in 5 at 20 detents/s: ``build_ms`` (wake -> the ``Commit`` call),
``commit_ms`` and ``commits_over_0_25ms`` are reported apart.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time

if __name__ == "__main__" and not __package__:          # run by path (see the usage above)
    import os
    import runpy
    _HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.curdir) != _HERE]
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(_HERE))))
    runpy.run_module("control_center.stage.scenes.bench", run_name="__main__", alter_sys=True)
    sys.exit(0)

from .. import curves as CV
from .. import frames as FR
from ..bench import BurstHog, _Holder, make_device
from ..engine import SceneContext, StageCore
from ..layout import StageLayout
from ..tree import Tree
from . import SceneFactory, testing as TS
from .art import ArtService, SimulatedCovers
from .common import Prepared
from .explorer import ExplorerScene
from .upnext import UpNextScene

MONITORS = {"32:9": (0, 0, 5120, 1440), "16:9": (0, 0, 2560, 1440)}


def script(n_each=20):
    return [+1] * n_each + [-1] * n_each + [(+1 if i % 2 == 0 else -1) for i in range(n_each)]


def _explorer_items():
    am, _c = TS.sim_apple(art="mixed", recent="many")
    return [{k: v for k, v in it.items() if not k.startswith("_")} for it in am._library()]


def _highlight(items, index, sent_first):
    """K3's ``explorer_highlight`` for a detent (``_explorer_push_highlight``): the index, and the
    window's descriptors whenever ``first`` moved."""
    first = max(0, index - 12)
    p = {"index": index, "control_id": 1, "bump": 0}
    if first != sent_first:
        p.update(items=items[first:index + 17], items_first=first, items_rev=1)
    return p, first


def run(scene="explorer", device="native", table="32:9", rate=20.0, art_on=True, hog="none", detents=20,
        sleep=time.sleep, keep=False):
    CV.prewarm()
    dev, clock, teardown = make_device(device)
    out = {"scene": scene, "device": device, "table": table, "rate_per_s": rate, "art": art_on, "hog": hog,
           "device_info": {k: v for k, v in (getattr(dev, "info", {}) or {}).items() if k != "adapters"}}
    hog_t = None
    art = ArtService(simulated=SimulatedCovers(None)) if art_on else None
    try:
        core = StageCore(dev, clock)
        layout = StageLayout(MONITORS[table])
        tree = Tree(dev)
        root = tree.root()
        root_op = tree.opacity(root, 0.0)
        container = tree.visual("scene")
        tree.add(root, container)
        holder = _Holder(dev)
        holder.uploads.gap_s = core.upload_gap_s                  # the engine's upload discipline (S1)
        holder.uploads.commit = lambda: core.commit(None)
        if scene == "explorer":
            items = _explorer_items()
            start = 40
            payload = TS.explorer_payload(time.perf_counter(), index=start, items=items)
            cls = ExplorerScene
        else:
            payload = TS.upnext_payload(time.perf_counter(), kind="playlist", rows=90, now=40)
            cls = UpNextScene
            items = None
        ctx = SceneContext(holder, core, tree, layout, scene, payload)
        ctx.ambient_image = None
        factory = SceneFactory(cls, art, Prepared())
        t0 = time.perf_counter()
        sc = factory(ctx, payload)
        sc.build(payload, container)
        b = core.batch()
        b.to(root_op, 1.0, 340, "OUT", v_from=0.0, force=True)
        sc.open(b, payload)
        b.commit()
        out["build_open_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        out["open_calls"] = b.calls
        out["objects"] = dev.alive() if hasattr(dev, "alive") else None

        upload_commit_ms = []

        def land():
            """The engine's upload wake (``StageEngine._run_uploads``, S1): the reveal of what
            ripened (a bind-only batch), then, when the pacing allows, one upload wake (4 ms,
            2.5 MB) with its own upload Commit."""
            up = holder.uploads
            landed = up.ripen()
            n, ms = 0, 0.0
            if landed:
                bb = core.batch()
                sc.uploads_ready(bb, list(landed))
                if bb.calls:
                    bb.commit()
                n, ms = len(landed), (bb.t_done - bb.t_wake) * 1000.0 if bb.t_done else 0.0
            if up.due():
                t = time.perf_counter()
                if up.upload():
                    upload_commit_ms.append((time.perf_counter() - t) * 1000.0)
            return n, ms

        t_end = time.perf_counter() + 0.5
        while time.perf_counter() < t_end:
            land()
            sleep(0.01)
        if hog == "burst":
            hog_t = BurstHog()
            hog_t.start()
            sleep(0.05)
        passes = {}
        for label in ("cold", "warm"):
            rows, land_rows = [], []
            period = 1.0 / rate
            nxt = time.perf_counter()
            focus = sc.focus
            sent_first = max(0, focus - 12)
            for step in script(detents):
                nxt += period
                while True:
                    d = nxt - time.perf_counter()
                    if d <= 0:
                        break
                    n, ms = land()
                    if n:
                        land_rows.append(ms)
                    d = nxt - time.perf_counter()
                    if d > 0:
                        sleep(min(d, 0.004))
                focus = focus + step
                t_wake = time.perf_counter()
                batch = core.batch(t_wake)
                t_stats = time.perf_counter()
                if scene == "explorer":
                    p, sent_first = _highlight(items, focus, sent_first)
                    sc.update(batch, "explorer_highlight", p)
                else:
                    sc.update(batch, "upnext_highlight", {"index": focus, "control_id": 1, "bump": 0})
                batch.commit()
                rows.append({"wake_to_commit_ms": batch.work_ms, "stats_ms": (t_stats - t_wake) * 1000.0,
                             "build_ms": (batch.t_built - t_stats) * 1000.0, "commit_ms": batch.commit_ms,
                             "calls": batch.calls, "anims": batch.anims, "carried": batch.carried})
            t_end = time.perf_counter() + 0.6                  # the art catches up between the passes
            while time.perf_counter() < t_end:
                land()
                sleep(0.01)
            w = [r["wake_to_commit_ms"] for r in rows]
            passes[label] = {
                "detents": len(rows),
                "wake_to_commit_ms": FR.summary(w),
                "build_ms": FR.summary([r["build_ms"] for r in rows]),
                "commit_ms": FR.summary([r["commit_ms"] for r in rows]),
                "calls_per_detent": FR.summary([r["calls"] for r in rows], 1),
                "anims_per_detent": FR.summary([r["anims"] for r in rows], 1),
                "upload_batches_ms": FR.summary(land_rows) if land_rows else None,
                "detents_carrying_uploads": sum(1 for r in rows if r["carried"]),      # S1: 0
                "over_1_5ms": sum(1 for x in w if x > 1.5),
                # DirectComposition's periodic Commit (about every 256 ms while animations run,
                # 0.3-1 ms, whatever the batch holds): at 20 detents/s it lands on about 1 detent in 5
                "commits_over_0_25ms": sum(1 for r in rows if r["commit_ms"] is not None and r["commit_ms"] > 0.25),
                "gate_1_5ms_p95": FR.summary(w)["p95"] <= 1.5,
            }
        # §6.3: the gate is taken with a warm prepared-sprite cache; a cold cache is recorded.
        out.update(passes["warm"])
        out["cold"] = passes["cold"]
        out["upload_wakes_ms"] = FR.summary(upload_commit_ms) if upload_commit_ms else None   # uploads + Commit
        out["upload_stats"] = dict(holder.uploads.stats)
        out.update({"scene_counters": dict(sc.counters), "art": dict(art.stats) if art is not None else None})
        sc.release()
        tree.release_all()
        return out
    finally:
        if hog_t is not None:
            hog_t.stop = True
            hog_t.join(1.0)
        if art is not None:
            art.close(1.0)
        teardown()


def _p95_of(r, key):
    s = r.get(key)
    return s.get("p95") if isinstance(s, dict) else None


def runs_summary(results):
    """R-k's reading of the gate over several runs: each run's warm p95, their median (the mean of
    the two middle values for an even count, ``statistics.median``) and worst, the runs at or
    under 1.5 ms, each run's build p95 (wake -> the ``Commit`` call) and ``Commit`` p95 apart, and
    the COM calls and animations per detent."""
    p95 = [r["wake_to_commit_ms"]["p95"] for r in results]
    return {"runs": len(results), "warm_p95_ms": p95, "median_p95_ms": round(statistics.median(p95), 3),
            "worst_p95_ms": max(p95),
            "runs_at_or_under_1_5ms": sum(1 for r in results if r["gate_1_5ms_p95"]),
            "warm_p50_ms": [r["wake_to_commit_ms"]["p50"] for r in results],
            "build_p95_ms": [_p95_of(r, "build_ms") for r in results],
            "commit_p95_ms": [_p95_of(r, "commit_ms") for r in results],
            "commits_over_0_25ms": [r.get("commits_over_0_25ms") for r in results],
            "calls_per_detent_p50": [r["calls_per_detent"]["p50"] for r in results],
            "anims_per_detent_p50": [r["anims_per_detent"]["p50"] for r in results]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--scene", choices=["explorer", "upnext"], default="explorer")
    ap.add_argument("--device", choices=["native", "fake"], default="native")
    ap.add_argument("--table", choices=list(MONITORS), default="32:9")
    ap.add_argument("--rate", type=float, default=20.0)
    ap.add_argument("--art", choices=["on", "off"], default="on")
    ap.add_argument("--hog", choices=["none", "burst"], default="none")
    ap.add_argument("--runs", type=int, default=1, help="repeat the bench (R-k: the gate is read over >= 5 runs)")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    sys.setswitchinterval(0.001)                    # §4.7.2 item 3 (the app sets it at startup)
    if a.runs > 1:
        results = [run(a.scene, a.device, a.table, a.rate, a.art == "on", a.hog) for _ in range(a.runs)]
        res = {"summary": runs_summary(results), "results": results}
    else:
        res = run(a.scene, a.device, a.table, a.rate, a.art == "on", a.hog)
    text = json.dumps(res, indent=1, default=str)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
