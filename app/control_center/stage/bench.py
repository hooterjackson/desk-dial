"""Headless per-detent build bench (DESKTOP_STAGE §6.6 H5, [G1] G1-4): reported, not gated.

    .venv\\Scripts\\python.exe -I control_center\\stage\\bench.py [--device native|fake] [--table 32:9|16:9]
        [--items 25] [--rate 20] [--hog none|burst] [--json PATH]

Run it by path from the project folder: under ``-I`` neither the working directory nor the script's
folder is on ``sys.path``, so ``-m control_center.stage.bench`` cannot find the package (``-m`` works
without ``-I``); run by path, the module puts the project root on ``sys.path`` itself and runs as part
of its package.

It builds the probe scene (the explorer's tree shape, ``probe_scene``) on a **device without a
target** (no window is created; nothing is shown), opens it, then replays a detent script at
``--rate`` detents/s with real time passing between detents, so every retarget starts from a
curve in flight: 20 forward, 20 back, 20 reversals. Each detent is measured as the stage
measures it: wake -> ``GetFrameStatistics`` (t1) -> the builder's calls -> ``Commit`` returned
(§6.2 ``work_ms``). ``--hog burst`` adds §6.4's stress thread (pure Python, 10 ms every 25 ms).
The §6.3 gate is 1.5 ms p95 on screen at 20 detents/s on the 32:9 table; a target-less device
does not show DWM's side of ``Commit``, so this is the Python + COM build cost.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time

if __name__ == "__main__" and not __package__:          # run by path (see the usage above)
    import os
    import runpy
    _HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.curdir) != _HERE]
    sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))
    runpy.run_module("control_center.stage.bench", run_name="__main__", alter_sys=True)
    sys.exit(0)

from . import clock as CK
from . import curves as CV
from . import frames as FR
from .engine import SceneContext, StageCore
from .layout import StageLayout
from .probe_scene import ProbeScene, probe_payload
from .surfaces import SolidCache, SurfaceLRU, UploadQueue
from .tree import Tree

MONITORS = {"32:9": (0, 0, 5120, 1440), "16:9": (0, 0, 2560, 1440)}


class _Holder:
    """The bits of the engine a SceneContext reads (uploads and caches)."""

    def __init__(self, dev):
        self.uploads = UploadQueue(dev)
        self.solids = SolidCache(dev)
        self.lru = SurfaceLRU(dev)


class BurstHog(threading.Thread):
    """§6.4 stress: a pure-Python burst of 10 ms every 25 ms (bench only)."""

    def __init__(self):
        super().__init__(name="stage-bench-hog", daemon=True)
        self.stop = False

    def run(self):
        nxt = time.perf_counter()
        while not self.stop:
            end = time.perf_counter() + 0.010
            while time.perf_counter() < end:
                pass
            nxt += 0.025
            d = nxt - time.perf_counter()
            if d > 0:
                time.sleep(d)
            else:
                nxt = time.perf_counter()


def make_device(kind):
    if kind == "fake":
        from .fake import FakeClock, FakeDevice
        clk = FakeClock()
        dev = FakeDevice(clk)
        return dev, CK.StageClock(dev.time_frequency, dev.time_frequency, qpc=lambda: int(time.perf_counter() * 1e7)), \
            lambda: None
    from . import win32 as W
    from .device import NativeDevice
    mon = W.primary_monitor()
    dev = NativeDevice(mon["hmonitor"] if mon else None)
    return dev, CK.StageClock(dev.time_frequency, dev.qpf, qpc=W.qpc), dev.teardown


def script(n_each=20):
    return [+1] * n_each + [-1] * n_each + [(+1 if i % 2 == 0 else -1) for i in range(n_each)]


def run(device="native", table="32:9", items=25, rate=20.0, hog="none", detents=20, sleep=time.sleep):
    CV.prewarm()
    dev, clock, teardown = make_device(device)
    out = {"device": device, "table": table, "items": items, "rate_per_s": rate, "hog": hog,
           "device_info": {k: v for k, v in (getattr(dev, "info", {}) or {}).items() if k != "adapters"}}
    hog_t = None
    try:
        core = StageCore(dev, clock)
        layout = StageLayout(MONITORS[table])
        tree = Tree(dev)
        root = tree.root()
        root_op = tree.opacity(root, 0.0)
        container = tree.visual("scene")
        tree.add(root, container)
        payload = probe_payload(count=items, index=items // 2 - detents // 2)
        ctx = SceneContext(_Holder(dev), core, tree, layout, "explorer", payload)
        t0 = time.perf_counter()
        scene = ProbeScene(ctx, payload)
        scene.build(payload, container)
        b = core.batch()
        b.to(root_op, 1.0, 340, "OUT", v_from=0.0, force=True)
        scene.open(b, payload)
        b.commit()
        out["build_open_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        out["open_calls"] = b.calls
        out["objects"] = dev.alive()
        sleep(0.5)
        if hog == "burst":
            hog_t = BurstHog()
            hog_t.start()
            sleep(0.05)
        rows = []
        period = 1.0 / rate
        nxt = time.perf_counter()
        for step in script(detents):
            nxt += period
            d = nxt - time.perf_counter()
            if d > 0:
                sleep(d)
            t_wake = time.perf_counter()
            batch = core.batch(t_wake)
            t_stats = time.perf_counter()
            scene.turn(batch, scene.focus + step)
            batch.commit()
            rows.append({"wake_to_commit_ms": batch.work_ms, "stats_ms": (t_stats - t_wake) * 1000.0,
                         "build_ms": (batch.t_built - t_stats) * 1000.0, "commit_ms": batch.commit_ms,
                         "calls": batch.calls, "anims": batch.anims, "jumps": batch.jumps,
                         "skipped": batch.skipped})
        w = [r["wake_to_commit_ms"] for r in rows]
        calls = sum(r["calls"] for r in rows)
        build = sum(r["build_ms"] for r in rows)
        out.update({
            "detents": len(rows),
            "wake_to_commit_ms": FR.summary(w),
            "build_ms": FR.summary([r["build_ms"] for r in rows]),
            "commit_ms": FR.summary([r["commit_ms"] for r in rows]),
            "stats_ms": FR.summary([r["stats_ms"] for r in rows], 4),
            "calls_per_detent": FR.summary([r["calls"] for r in rows], 1),
            "anims_per_detent": FR.summary([r["anims"] for r in rows], 1),
            "us_per_call": round(build * 1000.0 / max(1, calls), 3),
            "over_1_5ms": sum(1 for x in w if x > 1.5),
            "gate_1_5ms_p95": FR.summary(w)["p95"] <= 1.5,
        })
        tree.release_all()
        scene.release()
        return out
    finally:
        if hog_t is not None:
            hog_t.stop = True
            hog_t.join(1.0)
        teardown()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--device", choices=["native", "fake"], default="native")
    ap.add_argument("--table", choices=list(MONITORS), default="32:9")
    ap.add_argument("--items", type=int, default=25)
    ap.add_argument("--rate", type=float, default=20.0)
    ap.add_argument("--hog", choices=["none", "burst"], default="none")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    sys.setswitchinterval(0.001)                    # §4.7.2 item 3 (the app sets it at startup)
    res = run(a.device, a.table, a.items, a.rate, a.hog)
    text = json.dumps(res, indent=1)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
