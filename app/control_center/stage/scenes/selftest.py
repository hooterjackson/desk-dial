"""Headless self-test of the stage with the music scenes (DESKTOP_STAGE §6.6; [G1] G1-4, G1-5).

    cd app
    .venv\\Scripts\\python.exe -I control_center\\stage\\scenes\\selftest.py [--json PATH] [--quick]

(By path: under ``-I`` the working directory is not on ``sys.path``, so ``-m`` cannot find the
package; ``-m control_center.stage.scenes.selftest`` works without ``-I``, from the project folder.)

Runs WP7a's stage self-test (``stage.selftest``: environment, H2/H3/H6/H7, the device, hidden
hosts, the probe bench), then the scenes' own checks:

- static: no timers, forbidden modes, focus calls or Tk / serial imports in the scene modules;
  nothing outside the stage package imports the stage except WP10's wiring point
  (``standalone.py``, K4 §4.1);
- end to end on the real device: ``StageThread`` with both scenes, a host that is created hidden
  and refuses to show, and a capture that never reads the screen; each open runs its whole
  capture -> frost -> build -> commit, then ends in ``refused(device)`` at the show (nothing is
  ever shown) with no other error;
- the per-detent benches (H5; G1-4 gates the 32:9 table at 20 detents/s): the explorer and Up
  next on a device without a target, warm prepared-sprite cache gated, cold recorded;
- the GIL holds of every art-worker operation (G1-5; informational, the PC is shared).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

if __name__ == "__main__" and not __package__:          # run by path (see the usage above)
    import runpy
    _HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.curdir) != _HERE]
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(_HERE))))
    runpy.run_module("control_center.stage.scenes.selftest", run_name="__main__", alter_sys=True)
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
WIRING_POINTS = ("standalone.py",)      # WP10's sanctioned importer of the stage (K4 §4.1; WP8-R11)


def static_checks():
    from ..selftest import _strip_strings_and_comments, static_scan
    hits = []
    pkg = os.path.dirname(os.path.dirname(HERE))
    files = [os.path.join(HERE, n) for n in sorted(os.listdir(HERE)) if n.endswith(".py")]
    files += [os.path.join(pkg, n) for n in ("scene_music.py", "render_music.py", "music_overlay.py")]
    frame_paths = ("explorer.py", "upnext.py", "common.py", "__init__.py")
    bad = ["NEAREST" + "_NEIGHBOR", "BORDER_MODE" + "_HARD", "SetFore" + "groundWindow", "SW_" + "SHOW",
           "import " + "tkinter", "import " + "serial"]
    for path in files:
        name = os.path.basename(path)
        in_doc = False
        with open(path, encoding="utf-8") as fh:
            for ln, raw in enumerate(fh, 1):
                if raw.count('"""') % 2 == 1:
                    in_doc = not in_doc
                    continue
                if in_doc:
                    continue
                code = _strip_strings_and_comments(raw)
                for b in bad:
                    if b in code:
                        hits.append(f"{name}:{ln}: {b}")
                if name in frame_paths:
                    for pat in (r"\.after" + r"\(", r"\bSetTim" + r"er\(", r"\bsle" + r"ep\("):
                        if re.search(pat, code):
                            hits.append(f"{name}:{ln}: timer")
    return hits, [f for f in static_scan()["outside_importers"] if f not in WIRING_POINTS]


def end_to_end(timeout_s=6.0):
    """Both scenes on ``NanoD-stage`` with the real device, a never-shown host and no screen."""
    from PIL import Image
    from ..engine import StageThread
    from ..presenter import StagePresenter
    from . import make_scenes
    from .art import ArtService, SimulatedCovers
    from . import testing as T
    logs = []
    art = ArtService(simulated=SimulatedCovers(None), log=logs.append)

    def grab(rect):
        return Image.linear_gradient("L").resize((int(rect[2]), int(rect[3]))).convert("RGB")

    thread = StageThread(make_scenes(art), log=logs.append, host_hidden_only=True, capture_grab=grab)
    pres = StagePresenter(thread)
    out = {}
    try:
        for surface, payload in (("explorer", T.explorer_payload(time.perf_counter(), index=4)),
                                 ("upnext", T.upnext_payload(time.perf_counter(), kind="playlist", now=4))):
            getattr(pres, surface + "_open")(payload)
            ev = []
            t_end = time.perf_counter() + timeout_s
            while time.perf_counter() < t_end and not ev:
                ev = pres.take_events()
                if not ev:
                    time.sleep(0.02)
            out[surface] = [(k, {x: y for x, y in p.items() if x != "t0"}) for k, p in ev]
        m = thread.metrics()
        out["counters"] = m.get("counters")
        errors = [x for x in logs if "error" in x and "hidden" not in x and "refus" not in x.lower()
                  and "show" not in x]
        out["errors"] = errors[:5]
        out["log_tail"] = logs[-6:]
    finally:
        thread.close(2.0)
        art.close(1.0)
    return out


def run(quick=False, echo=True):
    from .. import selftest as core
    rep = core.run(quick=True, echo=echo)
    hits, outside = static_checks()
    rep.check("scenes.static_timers_modes_focus_imports", not hits, hits[:20])
    rep.check("scenes.no_importers_outside_the_stage (WP10's standalone.py is the one wiring point)", not outside,
              outside)
    e2e = end_to_end()
    rep.data["end_to_end"] = e2e
    ok = all(e2e.get(s) == [("refused", {"surface": s, "reason": "device"})] for s in ("explorer", "upnext"))
    rep.check("scenes.end_to_end_build_and_commit_on_the_device (hidden host refuses the show)",
              ok and not e2e.get("errors"), e2e)
    from . import bench
    for scene in ("explorer", "upnext"):
        b = bench.run(scene, "native", "32:9", 20.0, art_on=True, detents=10 if quick else 20)
        rep.data[f"bench_{scene}_32:9"] = b
        rep.check(f"scenes.bench_{scene}_32:9_warm_wake_to_commit_p95<=1.5ms (H5 gate, G1-4)", b["gate_1_5ms_p95"],
                  {"warm": b["wake_to_commit_ms"], "cold": b["cold"]["wake_to_commit_ms"],
                   "calls": b["calls_per_detent"], "commit_ms": b["commit_ms"]})
    if not quick:
        b = bench.run("explorer", "native", "16:9", 20.0, art_on=True)
        rep.data["bench_explorer_16:9"] = b
        rep.check("scenes.bench_explorer_16:9 (informational)", True, {"warm": b["wake_to_commit_ms"]}, gate=False)
        from . import gilbench
        g = gilbench.run(reps=6, echo=False)
        rep.data["gil"] = g
        rep.check("scenes.art_worker_gil_holds<=2ms (G1-5, informational: the PC is shared)", g["gate_2ms"],
                  {"worst_ms": g["worst_late_max_ms"], "baseline": g["baseline"]}, gate=False)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", default=None)
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args(argv)
    t0 = time.perf_counter()
    rep = run(quick=a.quick)
    gated = [c for c in rep.checks if c["gate"]]
    summary = {"pass": rep.passed, "gated": len(gated), "gated_passed": sum(1 for c in gated if c["ok"]),
               "informational": len(rep.checks) - len(gated), "seconds": round(time.perf_counter() - t0, 1)}
    print(json.dumps(summary))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump({"summary": summary, "checks": rep.checks, "data": rep.data}, fh, indent=1, default=str)
    return 0 if rep.passed else 1


if __name__ == "__main__":
    sys.exit(main())
