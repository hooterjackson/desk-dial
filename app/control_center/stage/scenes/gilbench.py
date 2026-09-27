"""GIL holds of every art-worker operation of the music scenes (DESKTOP_STAGE §4.7.3, §6.6 H5 "gil_pil_hold
for every worker operation"; [G1] G1-5: no thread holds the GIL over ~2 ms while an overlay can take
input, 1 ms per C call during episodes is the design target).

    cd app
    .venv\\Scripts\\python.exe -I control_center\\stage\\scenes\\gilbench.py [--reps 12] [--json PATH]

(By path: under ``-I`` the working directory is not on ``sys.path``, so ``-m`` cannot find the
package; ``-m control_center.stage.scenes.gilbench`` works without ``-I``, from the project folder.)

Each operation runs in a loop on a worker thread while a probe thread sleeps 0.5 ms at a time
and records how late it gets the GIL back after each wake (``timeBeginPeriod(1)`` and a 1 ms
switch interval, as the app sets them, §4.7.2). A pure-Python stretch costs the probe at most
about one switch interval; anything longer is one C call holding the GIL. Reported per
operation: its duration, the probe's p99 and max lateness above the idle baseline. Nothing is
shown, fetched or written.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import threading
import time

if __name__ == "__main__" and not __package__:          # run by path (see the usage above)
    import os
    import runpy
    _HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.curdir) != _HERE]
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(_HERE))))
    runpy.run_module("control_center.stage.scenes.gilbench", run_name="__main__", alter_sys=True)
    sys.exit(0)

from PIL import Image

from ... import render_music as RM
from ... import scene_music as SM
from .. import blur as B

PROBE_SLEEP_S = 0.0005


def _time_begin_period(on: bool):
    try:
        import ctypes
        w = ctypes.windll.winmm
        (w.timeBeginPeriod if on else w.timeEndPeriod)(1)
    except Exception:
        pass


def probe(op, reps=12, warm=1):
    """(op ms p50, probe lateness p99 ms, max ms) while ``op`` runs ``reps`` times on a worker.
    The worker runs ``op`` ``warm`` times first (its thread-local font faces load then, as a
    long-lived art worker's do once, see ``ArtService.warm``), and only then is it measured."""
    started = threading.Event()
    done = threading.Event()
    durs = []

    def work():
        for _ in range(warm):
            op()
        started.set()
        for _ in range(reps):
            t = time.perf_counter()
            op()
            durs.append((time.perf_counter() - t) * 1000.0)
        done.set()

    late = []
    th = threading.Thread(target=work, name="gilbench-worker")
    th.start()
    started.wait()
    while not done.is_set():
        t = time.perf_counter()
        time.sleep(PROBE_SLEEP_S)
        late.append(max(0.0, (time.perf_counter() - t - PROBE_SLEEP_S) * 1000.0))
    th.join()
    late.sort()
    durs.sort()
    p99 = late[min(len(late) - 1, int(0.99 * len(late)))] if late else 0.0
    return {"op_ms": round(durs[len(durs) // 2], 3), "late_p99_ms": round(p99, 3),
            "late_max_ms": round(late[-1] if late else 0.0, 3), "samples": len(late)}


def baseline(duration_s=0.3):
    late = []
    t_end = time.perf_counter() + duration_s
    while time.perf_counter() < t_end:
        t = time.perf_counter()
        time.sleep(PROBE_SLEEP_S)
        late.append(max(0.0, (time.perf_counter() - t - PROBE_SLEEP_S) * 1000.0))
    late.sort()
    return {"late_p99_ms": round(late[int(0.99 * len(late))], 3), "late_max_ms": round(late[-1], 3)}


def operations(k=2.0):
    """Every worker operation, at the G93SC's k (the largest sizes the app draws)."""
    from .art import ArtService, SimulatedCovers
    art = ArtService(sync=True, simulated=SimulatedCovers(None))
    l0, l1 = SM.upx(_K(k), SM.L0_UNITS), SM.upx(_K(k), SM.L1_UNITS)
    big = SM.upx(_K(k), SM.U_COVER)
    src1200 = RM.linear_gradient_160(1200, 0x5A2E24, 0x2F4A3A)
    buf = io.BytesIO()
    src1200.save(buf, "JPEG", quality=90)
    jpeg1200 = buf.getvalue()
    src400 = src1200.resize((400, 400))
    plan_gen = SM.cover_plan({"title": "Hounds of Love", "artist": "Kate Bush"})
    plan_load = SM.cover_plan({"title": "Heligoland", "artist": "Massive Attack", "art_bg": 0xFF781E,
                               "art_ink": 0xF2F2F2, "art_template": "simulation://art/x/{w}x{h}bb.jpg", "art_max": 1200})
    card_img = RM.art_generated("Hounds of Love", "Kate Bush", l0)
    c2buf = io.BytesIO()
    card_img.save(c2buf, "JPEG", quality=92)
    c2 = c2buf.getvalue()
    label = RM.label_sprite("Hounds of Love", "Kate Bush", "1985 · 12 tracks", k)
    frost_src = Image.linear_gradient("L").resize((1280 * int(k), 720 * int(k))).convert("RGB")

    def decode_full():
        img = Image.open(io.BytesIO(jpeg1200))
        img.draft("RGB", (l0, l0))
        img.load()
        return RM.fit_square(img.convert("RGB"), l0)

    def c2_decode():
        img = Image.open(io.BytesIO(c2))
        img.load()
        return RM.opaque_bgra(img.convert("RGB"))

    ops = {
        "decode 1200 JPEG -> L0 (draft, reduce, LANCZOS)": decode_full,
        "L0 -> L1 reduce(2)": lambda: card_img.reduce(2),
        "C2 decode + opaque bytes (L0)": c2_decode,
        "C2 encode JPEG q92 (L0)": lambda: card_img.save(io.BytesIO(), "JPEG", quality=92),
        "art.generated L0": lambda: RM.art_generated("Tropicália ou Panis et Circencis", "Various artists", l0),
        "art.generated big cover": lambda: RM.art_generated("Moon Safari", "Air", big, variant="cover"),
        "art.extended L0 (400 px source)": lambda: RM.art_extended(src400, l0, (200, 100, 50), 0.88, l0 / 340.0),
        "art.loading L0": lambda: RM.art_loading("Heligoland", "Massive Attack", l0, 0xFF781E, 0xF2F2F2),
        "art.loading L1": lambda: RM.art_loading("Heligoland", "Massive Attack", l1, 0xFF781E, 0xF2F2F2),
        "art.mosaic L0": lambda: RM.art_mosaic([src400] * 4, l0),
        "simulated cover 1200": lambda: art.simulated.draw("simulation://art/a1/{w}x{h}bb.jpg", 1200, 1200,
                                                           {"art_bg": 0xFF2850}),
        "label sprite + bgra": lambda: RM.label_sprite("Hounds of Love", "Kate Bush", "1985 · 12 tracks", k).bgra(),
        "label bgra only": lambda: label.bgra(),
        "row sprite + bgra": lambda: RM.row_sprite(k, lead="number", number="04", title="Running Up That Hill",
                                                   sub="Kate Bush", tag=("overlay.upnext.tag_now", SM.U_TAG_NOW_RGB,
                                                                         1.0)).bgra(),
        "row placeholder sprite": lambda: RM.row_sprite(k, lead="placeholder", placeholder_k=3).bgra(),
        "left text sprite": lambda: RM.left_text_sprite("Hounds of Love", "Kate Bush · 1985", k)[0].bgra(),
        "ambient build (64 px source)": lambda: B.ambient(RM.thumb64(src400), k, (5120, 1440)),
        "ambient build (art_bg)": lambda: B.ambient(0xFF781E, k, (5120, 1440)),
        "thumb64 + dominant": lambda: _thumb_dom(src1200),
        "element() generated (full path, C2 miss)": lambda: _element_fresh(art, plan_gen, l0),
        "element() cover via simulated source": lambda: _element_fresh(art, plan_load, l0),
        "frost at open (reduce 8, blur, matrices)": lambda: B.frost(frost_src, B.RECIPES["blur.explorer"], k,
                                                                   frost_src.size),
        "heart sprites": lambda: RM.heart_sprites(k),
        "state block sprite": lambda: RM.state_block_sprite("queue", SM.COPY["overlay.explorer.empty_title"],
                                                            SM.COPY["overlay.explorer.empty_help"], k).bgra(),
    }
    return ops


class _K:
    def __init__(self, k):
        self.k = k


def _thumb_dom(img):
    from ...artwork import dominant_rgb, sleeve_colour
    th = RM.thumb64(img)
    return sleeve_colour(img, dominant_rgb(img)), th


def _element_fresh(art, plan, px):
    art._c2.clear()
    art._c2_bytes = 0
    return art.element(plan, px, units=SM.CARD_UNITS, need0=px)


def run(reps=12, k=2.0, echo=True):
    sys.setswitchinterval(0.001)
    _time_begin_period(True)
    try:
        out = {"baseline": baseline(), "ops": {}}
        for name, op in operations(k).items():
            r = probe(op, reps)
            out["ops"][name] = r
            if echo:
                flag = "OK " if r["late_max_ms"] <= 2.0 else "HOLD"
                print(f"[{flag}] {name:48s} op {r['op_ms']:7.2f} ms  late p99 {r['late_p99_ms']:5.2f}  "
                      f"max {r['late_max_ms']:5.2f} ms", flush=True)
        worst = max(v["late_max_ms"] for v in out["ops"].values())
        out["worst_late_max_ms"] = worst
        out["gate_2ms"] = worst <= 2.0
        return out
    finally:
        _time_begin_period(False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--reps", type=int, default=12)
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    res = run(a.reps)
    print(json.dumps({"baseline": res["baseline"], "worst_late_max_ms": res["worst_late_max_ms"],
                      "gate_2ms": res["gate_2ms"]}))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
