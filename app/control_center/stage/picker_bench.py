"""The picker's headless benches for step 3 (DESKTOP_STAGE §6.3 "Picker (W), step 3", §6.6 H5; lead
ruling R-h; CAROUSEL.md §12.4). Nothing is shown and the screen is never read.

    .venv\\Scripts\\python.exe -I control_center\\stage\\picker_bench.py [--ratio 32:9|16:9|both]
        [--chrome native|fake] [--dwm] [--reps N] [--count N] [--json PATH]

Run it by path from the project folder: under ``-I`` neither the working directory nor the script's
folder is on ``sys.path``, so ``-m control_center.stage.picker_bench`` cannot find the package (``-m``
works without ``-I``); run by path, the module puts the project root on ``sys.path`` itself and runs
as part of its package.

The production ``CarouselEngine`` runs inline (``picker_testing.Rig``) at k = 2 on the 16:9 (2560 x 1440)
and 32:9 (5120 x 1440) tables, with its GPU chrome on the native device without a target (``native``,
the default: the COM calls are real) or the fake one, and the label worker on its own thread as in
the app. ``--dwm`` also makes every thumbnail call real: DWM thumbnails of the carousel's own hidden
windows onto its hidden host (``Win32CarouselBackend`` created on this thread, never shown), updated
through the GIL-keeping ``DwmUpdateThumbnailProperties``.

The session (``--count`` windows, 14 by default; 30 or more makes the card pool grow, which it must
do in quiet frames only: ``slots_grown_in_sync`` stays 0, K4 §4.7.1): open, 14 turns at about 7/s, 20
at 20/s, a left snap (the tray's reveal and the fly), 6 turns, a right snap, then the exit, in real time: one engine step per 240 Hz frame (``RealClock``; with
``--fast`` a fake clock steps as fast as it can, which queues DirectComposition commits behind each
other). The timings are ``perf_counter`` time of each frame's Python work (the engine's drain, frame
values, thumbnail plan and present, and on an event's frame the chrome's sync: its build and its
Commit).

Reported (median of the repetitions): the **per-frame Python work** p50 / p95 / max over normal frames
(the gate: <= 1.5 ms p95 at 32:9, R-h), over detent frames (<= 3.0 ms p95, §6.3), and the **per-detent
build cost** (the sync: build + Commit) p50 / p95 / max, with the COM calls and animations per sync.
The PC is shared, so the numbers are recorded, not gated, except as the self-test's H5 line.
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
    sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))
    runpy.run_module("control_center.stage.picker_bench", run_name="__main__", alter_sys=True)
    sys.exit(0)

from .. import carousel as CA
from . import picker_testing as PT


LABELS = ["threaded"]                    # the label worker as in the app ("inline": on the frame thread)


def quantile(values, p):
    values = sorted(values)
    if not values:
        return None
    return values[min(len(values) - 1, max(0, int(round(p * (len(values) - 1)))))]


def summary(values, nd=3):
    if not values:
        return None
    return {"n": len(values), "p50": round(quantile(values, 0.5), nd), "p95": round(quantile(values, 0.95), nd),
            "max": round(max(values), nd)}


class DwmThumbs:
    """Real DWM thumbnails between hidden windows of this thread (never shown): the per-call cost of
    DwmRegisterThumbnail / DwmUpdateThumbnailProperties / DwmUnregisterThumbnail, nothing on screen."""

    def __init__(self):
        self.backend = CA.Win32CarouselBackend()
        self.backend.prepare_thread()
        self.backend.create(lambda *a: None, lambda *a: None)
        self.sources = [h for role, h in self.backend.windows.items() if role != "host"]
        self.handles = {}
        self.n = 0
        self.fail = 0

    def register(self, fake_handle):
        src = self.sources[self.n % len(self.sources)]
        self.n += 1
        real = self.backend.register(src)
        if real:
            self.handles[fake_handle] = real
        else:
            self.fail += 1

    def update(self, updates):
        real = [(self.handles[h], d, s, o, False) for h, d, s, o, _v in updates if h in self.handles]
        return self.backend.update_thumbnails(real)

    def unregister(self, fake_handle):
        real = self.handles.pop(fake_handle, None)
        if real:
            self.backend.unregister(real)

    def close(self):
        for real in list(self.handles.values()):
            self.backend.unregister(real)
        self.handles.clear()
        self.backend.destroy()
        self.backend.pump()


def session(rig, count=14):
    """The scripted session (see the module docstring); returns the phase marks."""
    marks = {}
    rig.open(count=count, index=3)
    marks["open"] = len(rig.frames)
    index = 3
    for _ in range(14):                       # ~7 detents/s
        index = min(count - 1, index + 1)
        rig.presenter.highlight(index)
        rig.step(0.14)
    for i in range(20):                       # 20 detents/s, back and forth
        index = max(0, min(count - 1, index + (-1 if i < 10 else 1)))
        rig.presenter.highlight(index)
        rig.step(0.05)
    rig.step(0.5)
    marks["turns"] = len(rig.frames)
    rig.snap_side(index, "left")
    rig.step(0.6)
    for _ in range(6):
        index = max(0, index - 1)
        rig.presenter.highlight(index)
        rig.step(0.14)
    rig.step(0.5)
    rig.snap_side(index, "right")
    rig.step(0.6)
    marks["snaps"] = len(rig.frames)
    rig.presenter.play_cancel_exit()
    rig.step(0.4)
    marks["end"] = len(rig.frames)
    return marks


def run_one(ratio="32:9", chrome="native", dwm=False, count=14, realtime=True):
    dwm_thumbs = DwmThumbs() if dwm else None
    rig = PT.Rig(ratio, chrome, dwm=dwm_thumbs, labels=LABELS[0], clock=PT.RealClock() if realtime else None)
    try:
        rig.chrome.prewarm_step(None)                     # the tables, as the idle warm-up leaves them
        marks = session(rig, count)
        frames = rig.frames[marks["open"]:]
        normal = [ms for ms, detent, _s in frames if not detent]
        detent = [ms for ms, detent, _s in frames if detent]
        syncs = [s * 1000.0 for _ms, detent, s in frames if detent and s is not None]
        gm = rig.chrome.metrics()
        out = {"ratio": ratio, "chrome": chrome, "dwm": bool(dwm), "frames": len(frames),
               "normal_ms": summary(normal), "detent_ms": summary(detent), "sync_ms": summary(syncs),
               "open_frames_ms": summary([ms for ms, _d, _s in rig.frames[:marks["open"]]]),
               "last_calls": gm.get("last_calls"), "sync_ms_max": gm.get("sync_ms_max"),
               "clip_approx": gm.get("clip_approx"), "failures": gm.get("failures"),
               "slots": gm.get("slots"), "slots_grown_ahead": gm.get("slots_grown_ahead"),
               "slots_grown_in_sync": gm.get("slots_grown_in_sync"), "count": count,
               "chrome_used": rig.presenter.chrome, "updates": rig.backend.updates}
        if dwm_thumbs is not None:
            out["dwm_register_failures"] = dwm_thumbs.fail
        return out
    finally:
        rig.close()
        if dwm_thumbs is not None:
            dwm_thumbs.close()


def run(ratio="32:9", chrome="native", dwm=False, reps=3, echo=True, realtime=True, count=14):
    reps_out = [run_one(ratio, chrome, dwm, count=count, realtime=realtime) for _ in range(max(1, reps))]

    def med(key, stat):
        vals = [r[key][stat] for r in reps_out if r.get(key)]
        return round(statistics.median(vals), 3) if vals else None

    result = {"ratio": ratio, "chrome": chrome, "dwm": dwm, "reps": len(reps_out),
              "normal_ms": {s: med("normal_ms", s) for s in ("p50", "p95", "max")},
              "detent_ms": {s: med("detent_ms", s) for s in ("p50", "p95", "max")},
              "sync_ms": {s: med("sync_ms", s) for s in ("p50", "p95", "max")},
              "normal_p95_range": [min(r["normal_ms"]["p95"] for r in reps_out),
                                   max(r["normal_ms"]["p95"] for r in reps_out)],
              "detent_p95_range": [min(r["detent_ms"]["p95"] for r in reps_out),
                                   max(r["detent_ms"]["p95"] for r in reps_out)],
              "frames": reps_out[0]["frames"], "detents": reps_out[0]["detent_ms"]["n"],
              "clip_approx": reps_out[0]["clip_approx"], "failures": sum(r["failures"] or 0 for r in reps_out),
              "count": count, "slots": max(r["slots"] or 0 for r in reps_out),
              "slots_grown_in_sync": sum(r["slots_grown_in_sync"] or 0 for r in reps_out),
              "chrome_used": reps_out[0]["chrome_used"], "runs": reps_out}
    result["gate_normal_1_5ms_p95"] = result["normal_ms"]["p95"] is not None and result["normal_ms"]["p95"] <= 1.5
    result["gate_detent_3ms_p95"] = result["detent_ms"]["p95"] is not None and result["detent_ms"]["p95"] <= 3.0
    if echo:
        print(f"== {ratio} k=2 chrome={chrome} dwm={dwm} windows={count} frames/rep={result['frames']} detent "
              f"frames/rep={result['detents']} reps={result['reps']} (chrome used: {result['chrome_used']})")
        for key in ("normal_ms", "detent_ms", "sync_ms"):
            v = result[key]
            print(f"  {key:10s} p50={v['p50']} p95={v['p95']} max={v['max']}  (median of reps)")
        print(f"  normal p95 over reps {result['normal_p95_range']}; detent p95 over reps {result['detent_p95_range']}; "
              f"clip approximations {result['clip_approx']}; failures {result['failures']}; card slots "
              f"{result['slots']} (grown inside a sync: {result['slots_grown_in_sync']})")
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ratio", default="both", choices=("32:9", "16:9", "both"))
    ap.add_argument("--chrome", default="native", choices=("native", "fake"))
    ap.add_argument("--dwm", action="store_true")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--count", type=int, default=14, help="windows in the session (30+: the pool grows)")
    ap.add_argument("--json", default=None)
    ap.add_argument("--fast", action="store_true", help="a fake clock instead of real 240 Hz frames (commits "
                                                          "come faster than the app's and queue behind each other)")
    a = ap.parse_args(argv)
    sys.setswitchinterval(0.001)                          # K4 4.7.2 item 3, as the app sets it
    out = {}
    t0 = time.perf_counter()
    for ratio in (("16:9", "32:9") if a.ratio == "both" else (a.ratio,)):
        out[ratio] = run(ratio, a.chrome, a.dwm, a.reps, realtime=not a.fast, count=max(2, a.count))
    out["seconds"] = round(time.perf_counter() - t0, 1)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
