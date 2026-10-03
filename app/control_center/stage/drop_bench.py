"""Headless bench of the 2026-09-26 on-screen frame-drop classes (reported, not gated). Nothing is
shown: the fake engine rig, and (``--native``) a D3D11 + DirectComposition device **without a
target** (no window).

    cd app
    .venv\\Scripts\\python.exe -I control_center\\stage\\drop_bench.py [--root PATH] [--native] [--json PATH]

``--root`` imports ``control_center`` from another checkout (the code before the fixes), so the
same measurements give before / after numbers. Sections:

- ``tours``: tours E (32:9, 16:9) and U (32:9) of ``tools/stage_checks/music_tours.py`` on the fake rig
  (its ``DryDriver``), with the fake device instrumented here (works on either checkout): every
  Commit with the uploads it carried and the wait the native upload-Commit spacing predicts (an
  upload-carrying Commit sooner than two frames after the previous one blocks until then; the
  ``device`` module docstring), by batch kind. The drop class S1: reveal (``art``) Commits
  carrying uploads and waiting; detent (``turn``) Commits carrying uploads.
- ``holds`` (S3): the heart pop's episode (§4.6.4), frames where the twins change: the raw §6.2
  figures and, where the checkout has it, the change model's in-motion figures.
- ``picker`` (P1): the checkout's ``carousel.LoopPacer`` fed tour W's frame work (a 14 ms setup
  frame, the 12.8 ms frost upload, detent and re-registration frames at 10 and 20 detents/s):
  frames and misses in the open and the turn, cadence switches; and ``lock_by_rate``: when a
  loop whose work stays over 0.8 P locks at 60, 120, 144 and 240 Hz (a quarter second into the
  run since the review fix; never, with the reviewed 60-frame minimum), and that one slow frame
  does not.
- ``episode_eval``: the cost of the change model and the episode record at an episode's end
  (100 detents with gaps; pure Python on the stage thread, preemptible every 1 ms).
- ``native`` (``--native``): Commit costs on a real device for the old reveal pattern (upload
  wakes back to back, each revealed by a Commit in the same wake) and the new one (a paced upload
  Commit, a bind-only reveal a frame later), and the first upload Commit of a new device with and
  without ``prime``.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
TOURS = os.path.normpath(os.path.join(PROJECT, "..", "..", "work", "stage_checks", "music_tours.py"))


def _summary(xs):
    xs = sorted(float(x) for x in xs)
    if not xs:
        return None
    return {"n": len(xs), "p50": round(statistics.median(xs), 3), "p95": round(xs[min(len(xs) - 1, int(0.95 * len(xs)))], 3),
            "max": round(xs[-1], 3)}


# =========================================================================== tours (S1)
class CommitLog:
    """Instruments ``FakeDevice.upload`` / ``commit`` and ``StageCore.finish`` of the checkout."""

    def __init__(self):
        self.rows = []

    def install(self):
        from control_center.stage import engine as EN
        from control_center.stage import fake as F
        log = self
        self._saved = [(F.FakeDevice, "upload", F.FakeDevice.upload), (F.FakeDevice, "commit", F.FakeDevice.commit),
                       (EN.StageCore, "finish", EN.StageCore.finish)]
        orig_upload, orig_commit, orig_finish = (s[2] for s in self._saved)

        def upload(dev, surface, w, h, data, name=""):
            r = orig_upload(dev, surface, w, h, data, name)
            st = dev.__dict__.setdefault("_bench", {"pending": 0, "bytes": 0, "last": None})
            st["pending"] += 1
            st["bytes"] += len(data)
            return r

        def commit(dev):
            r = orig_commit(dev)
            st = dev.__dict__.setdefault("_bench", {"pending": 0, "bytes": 0, "last": None})
            now = dev.clock.perf()
            wait = 0.0
            if st["pending"]:
                if st["last"] is not None:
                    wait = max(0.0, st["last"] + 2.0 / dev.clock.hz - now)
                st["last"] = now + wait
            log.rows.append({"dev": id(dev), "t": now, "uploads": st["pending"], "bytes": st["bytes"],
                             "wait_ms": wait * 1000.0, "kind": None})
            st["pending"] = st["bytes"] = 0
            return r

        def finish(core, batch, kind):
            rows = log.rows
            if rows and rows[-1]["kind"] is None and rows[-1]["dev"] == id(core.device):
                rows[-1]["kind"] = kind
            return orig_finish(core, batch, kind)
        F.FakeDevice.upload, F.FakeDevice.commit, EN.StageCore.finish = upload, commit, finish
        return self

    def uninstall(self):
        for owner, name, fn in self._saved:
            setattr(owner, name, fn)

    def report(self):
        kinds = {}
        for r in self.rows:
            kind = r["kind"] or ("upload" if r["uploads"] else "other")
            k = kinds.setdefault(kind, {"commits": 0, "with_uploads": 0, "waits": 0, "wait_ms_sum": 0.0,
                                        "wait_ms_max": 0.0, "upload_bytes_max": 0})
            k["commits"] += 1
            if r["uploads"]:
                k["with_uploads"] += 1
                k["upload_bytes_max"] = max(k["upload_bytes_max"], r["bytes"])
            if r["wait_ms"] > 0.0:
                k["waits"] += 1
                k["wait_ms_sum"] += r["wait_ms"]
                k["wait_ms_max"] = max(k["wait_ms_max"], r["wait_ms"])
        for k in kinds.values():
            k["wait_ms_sum"] = round(k["wait_ms_sum"], 2)
            k["wait_ms_max"] = round(k["wait_ms_max"], 2)
        waits = [r for r in self.rows if r["wait_ms"] > 0.0]
        return {"by_kind": kinds, "commits": len(self.rows),
                "commits_with_uploads": sum(1 for r in self.rows if r["uploads"]),
                "waits": len(waits), "wait_ms_sum": round(sum(r["wait_ms"] for r in waits), 1),
                "reveal_waits_over_2ms": sum(1 for r in waits if r["kind"] == "art" and r["wait_ms"] > 2.0),
                "turns_with_uploads": kinds.get("turn", {}).get("with_uploads", 0)}


def _music_tours():
    if not os.path.isfile(TOURS):
        return None
    if PROJECT not in sys.path:
        sys.path.append(PROJECT)                          # music_tours adds it only when absent
    spec = importlib.util.spec_from_file_location("music_tours_bench", TOURS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_tours():
    MT = _music_tours()
    if MT is None:
        return {"skipped": "music_tours.py not found"}
    out = {}
    for tour, monitor in ((MT.explorer_tour, "32:9"), (MT.explorer_tour, "16:9"), (MT.upnext_tour, "32:9")):
        log = CommitLog().install()
        try:
            t = time.perf_counter()
            d = MT.DryDriver(monitor)
            tour(d, monitor)
            d.wait(1.0)
            rep = log.report()
            rep["events"] = [k for k, _p in d.events]
            rep["seconds"] = round(time.perf_counter() - t, 1)
            eng = d.rig.engine
            rep["upload_queue"] = dict(eng.metrics().get("uploads") or {}) if hasattr(eng, "metrics") else None
        finally:
            log.uninstall()
        out[f"{tour.__name__}@{monitor}"] = rep
    return out


# =========================================================================== holds (S3)
def run_holds():
    from control_center.stage import clock as CK
    from control_center.stage import fake as F
    from control_center.stage import frames as FR
    from control_center.stage.engine import StageCore
    from control_center.stage.tree import Tree
    clk = F.FakeClock()
    dev = F.FakeDevice(clk)
    core = StageCore(dev, CK.StageClock(dev.time_frequency, dev.time_frequency, qpc=clk, perf=clk.perf))
    core.read_stats()
    tree = Tree(dev)
    root = tree.root("root")
    box = tree.visual("heart", opacity=True)
    tree.add(root, box)
    fill_o = tree.opacity(box, 0.0)
    fill_s = tree.scale(tree.scale_transform(box, 16.0, 16.0), 32.0, 0.4, name="heart")
    b = core.batch()
    b.to(fill_o, 1.0, 200, "OUT", v_from=0.0, force=True)
    b.legs(fill_s, [(0, 1.5, 380, "SPR"), (420, 1.0, 380, "SPR")], v_from=0.4)
    b.commit()
    core.finish(b, "turn")
    ep = core.episodes.finish()
    P, t1 = core.period, b.t1
    funcs = (fill_o.func, fill_s.func)
    frames, n, fid = [], 0, 0
    while t1 + n * P <= ep["end"] + 1:
        t = int(round(t1 + n * P))
        if n == 0 or any(abs(f.value(t) - f.value(t - P)) > 1e-7 for f in funcs):
            fid += 1
            frames.append(FR.TargetFrame(fid, t, t, fid, fid, start_time=t - int(P / 2), target_time=t))
        n += 1
    raw = FR.episode_from_frames(frames, [], ep["start"], ep["end"], P, core.clock.freq, rate_hz=240.0)
    keep = ("frames", "vblanks", "fps", "missed", "double_missed", "step_max")
    out = {"raw": {k: raw.get(k) for k in keep}, "raw_pass": FR.judge_stage(raw, 240.0).get("pass")}
    model = getattr(FR, "ChangeModel", None)
    if model is not None and "batches" in ep:
        got = FR.episode_from_frames(frames, [], ep["start"], ep["end"], P, core.clock.freq, rate_hz=240.0,
                                     changes=model(ep["batches"], P))
        out["in_motion"] = {k: got.get(k) for k in ("fps_in_motion", "missed_in_motion", "double_missed_in_motion",
                                                    "holds")}
        out["in_motion"]["max_P"] = (got.get("interval_P_in_motion") or {}).get("max")
        out["pass"] = FR.judge_stage(got, 240.0).get("pass")
    else:
        out["in_motion"] = "no change model in this checkout"
        out["pass"] = out["raw_pass"]
    return out


# =========================================================================== picker (P1)
def run_picker(seed=1):
    import inspect
    import random
    from control_center import carousel as c
    period = 1 / 240.0
    flags = "oneoff" in inspect.signature(c.LoopPacer.frame_done).parameters

    def run(setup_ms, glass_ms, detent_ms, rereg_ms, gpu=True):
        rnd = random.Random(seed)
        pacer = c.LoopPacer(timing=lambda: (0.0, period))
        pacer.refresh()
        open_t0, open_end = 1.0, 1.55
        turn_t0 = open_end + 0.33
        turn_end = turn_t0 + 3.34
        detents = sorted([turn_t0 + 0.1 * i for i in range(20)] + [turn_t0 + 2.0 + 0.05 * i for i in range(20)])
        frames, n, rereg = [], int(round(open_t0 / period)), False
        while n * period < turn_end:
            t = n * period
            in_open, in_turn = open_t0 <= t < open_end, turn_t0 <= t < turn_end
            if not (in_open or in_turn):
                n += 1
                continue
            kind = "normal"
            if abs(t - open_t0) < period / 2:
                kind, work = "setup", setup_ms / 1000.0
            elif abs(t - (open_t0 + 0.09)) < period / 2:
                kind, work = "glass", glass_ms / 1000.0
            elif detents and detents[0] <= t:
                detents.pop(0)
                kind, work, rereg = "detent", rnd.uniform(*detent_ms) / 1000.0, True
            elif rereg:
                work, rereg = rnd.uniform(*rereg_ms) / 1000.0, False
            else:
                work = rnd.uniform(0.4, 1.1) / 1000.0
            frames.append((t, "open" if in_open else "turn"))
            if flags:
                cad = pacer.frame_done(t, work, oneoff=kind in ("setup", "glass"), p5=not (gpu and kind == "detent"))
            else:
                cad = pacer.frame_done(t, work)
            n += cad
        out = {}
        for k in ("open", "turn"):
            ts = [f[0] for f in frames if f[1] == k]
            out[k] = {"frames": len(ts), "missed": sum(1 for a, b in zip(ts, ts[1:]) if round((b - a) / period) >= 2)}
        out["switches"] = pacer.switches
        return out
    return {"flags": flags,
            "warm_open_W_like": run(14.0, 12.8, (1.8, 2.8), (1.2, 2.2)),
            "cold_open_110ms_setup": run(110.0, 12.8, (1.8, 2.8), (1.2, 2.2)),
            "no_one_off_frames": run(0.9, 0.9, (1.8, 2.8), (1.2, 2.2)),
            "lock_by_rate": run_lock_by_rate()}


def run_lock_by_rate():
    """P1's lock minimum at other rates (the 2026-09-26 review): a loop whose every frame is over
    0.8 P should lock once the loop has run a quarter second, at 60, 120, 144 and 240 Hz, with
    work under P, over P and over 2 P; a lone slow frame (3 P) among light ones never should.
    ``locked_at_s`` None: never locked in 1 s (the reviewed checkout's 60-frame minimum)."""
    import math
    from control_center import carousel as c

    def drive(hz, work_of):
        period = 1.0 / hz
        pacer = c.LoopPacer(timing=lambda: (0.0, period))
        pacer.refresh()
        n, i, locked = 0, 0, None
        while n * period < 1.0:
            t = n * period
            work = work_of(i, t, period)
            cadence = pacer.frame_done(t, work)
            if cadence == 2 and locked is None:
                locked = round(t, 4)
            n += max(cadence, int(math.ceil(work / period - 1e-9)))
            i += 1
        return {"locked_at_s": locked, "switches": pacer.switches}
    out = {}
    for hz, work_ms in ((60, 14.0), (60, 20.0), (60, 35.0), (120, 7.0), (120, 9.0), (144, 6.5), (240, 4.0),
                        (240, 9.0), (240, 12.0)):
        out["%d Hz, %.1f ms" % (hz, work_ms)] = drive(hz, lambda i, t, p, w=work_ms: w / 1000.0)
    for hz in (60, 120, 240):
        out["%d Hz, one 3 P frame" % hz] = drive(hz, lambda i, t, p: 3 * p if i == 0 else 0.2 * p)
    return out


# =========================================================================== the episode record's cost
def run_episode_eval():
    from control_center.stage import frames as FR
    from control_center.stage.scenes import testing as T
    model = getattr(FR, "ChangeModel", None)
    if model is None:
        return "no change model in this checkout"
    rig = T.SceneRig("32:9", keep_pixels=False)
    items = T.explorer_payload(0.0, recent="many", art="mixed", window=False)["items"]
    rig.presenter.explorer_open(T.explorer_payload(rig.now(), index=10, recent="many", art="mixed"))
    rig.settle()
    rig.advance(1500, 50)
    eps = []
    from control_center.stage import animation as AN
    orig = AN.Episodes.finish

    def finish(e):
        r = orig(e)
        eps.append(r)
        return r
    AN.Episodes.finish = finish
    try:
        index, first = 10, 0
        for i in range(100):
            index += 1 if i % 20 < 15 else -1
            p = {"index": index, "control_id": 1, "bump": 0}
            f = max(0, index - 12)
            if f != first:
                first = f
                p.update(items=items[f:index + 17], items_first=f, items_rev=1)
            rig.presenter.explorer_highlight(p)
            rig.settle()
            rig.advance(50, 50)
        rig.advance(1500, 100)
    finally:
        AN.Episodes.finish = orig
    ep = max(eps, key=lambda e: e["events"])
    P = rig.engine.core.period
    frames, n, fid = [], 0, 0
    while ep["start"] + n * P <= ep["end"]:
        t = int(round(ep["start"] + n * P))
        if n % 97 not in (13, 14):                     # a gap of 2-3 P now and then
            fid += 1
            frames.append(FR.TargetFrame(fid, t, t, fid, fid, start_time=t, target_time=t))
        n += 1
    ts = []
    for _ in range(5):
        t0 = time.perf_counter()
        m = model(ep["batches"], P)
        rec = FR.episode_from_frames(frames, [], ep["start"], ep["end"], P, rig.clk.freq, rate_hz=240.0, changes=m)
        ts.append((time.perf_counter() - t0) * 1000.0)
    return {"events": ep["events"], "batches": len(ep["batches"]), "vblanks": rec.get("vblanks"),
            "gaps": rec.get("missed"), "ms": _summary(ts)}


# =========================================================================== native (optional)
def run_native():
    from control_center.stage import device as SD
    from control_center.stage import picker_chrome as PC

    def flush_of(dev):
        f = getattr(dev, "flush", None)
        return f if f is not None else PC._ctx_flush_fn(dev)

    def spin(s):
        end = time.perf_counter() + s
        while time.perf_counter() < end:
            pass

    out = {}
    # the first upload Commit of a new device, with and without the prime
    for label, prime in (("first_commit_no_prime_ms", False), ("first_commit_after_prime_ms", True)):
        dev = SD.NativeDevice(None)
        try:
            flush = flush_of(dev)
            if prime:
                s = dev.create_surface(8, 8, True, "prime")
                dev.upload(s, 8, 8, bytes(256), "prime")
                flush()
                dev.commit()
                dev.release(s)
                time.sleep(0.02)
            v = dev.create_visual("v")
            s = dev.create_surface(680, 680, True, "c")
            dev.upload(s, 680, 680, b"\x40" * (680 * 680 * 4), "c")
            dev.fn("Visual.SetContent", v.ptr)(v.ptr, s)
            t = time.perf_counter()
            dev.commit()
            out[label] = round((time.perf_counter() - t) * 1000.0, 3)
        finally:
            dev.teardown()
    dev = SD.NativeDevice(None)
    try:
        flush = flush_of(dev)
        root = dev.create_visual("root")
        kids = [dev.create_visual(f"k{i}") for i in range(4)]
        for k in kids:
            dev.fn("Visual.AddVisual", root.ptr)(root.ptr, k.ptr, 0, None)
        setc = [dev.fn("Visual.SetContent", k.ptr) for k in kids]
        data = b"\x40" * (680 * 680 * 4)
        made = []

        def tidy():
            while len(made) > 12:
                dev.release(made.pop(0))
        # the old pattern: upload wakes back to back (about 1 ms apart), each revealed in its own wake
        old = []
        for i in range(30):
            s1 = dev.create_surface(680, 680, True, "x")
            dev.upload(s1, 680, 680, data, "x")
            setc[i % 4](kids[i % 4].ptr, s1)
            t = time.perf_counter()
            dev.commit()
            old.append((time.perf_counter() - t) * 1000.0)
            made.append(s1)
            tidy()
            spin(0.001)
        time.sleep(0.05)
        # the new pattern: a paced upload wake (flush, its own Commit), the bind a frame later
        gap = 2 / 240.0 + 0.001
        up_ms, bind_ms = [], []
        for i in range(30):
            s1 = dev.create_surface(680, 680, True, "x")
            dev.upload(s1, 680, 680, data, "x")
            flush()
            t = time.perf_counter()
            dev.commit()
            up_ms.append((time.perf_counter() - t) * 1000.0)
            spin(0.004)
            setc[i % 4](kids[i % 4].ptr, s1)
            t = time.perf_counter()
            dev.commit()
            bind_ms.append((time.perf_counter() - t) * 1000.0)
            made.append(s1)
            tidy()
            spin(gap - 0.004)
        out["old_reveal_commit_ms"] = _summary(old[2:])
        out["new_upload_commit_ms"] = _summary(up_ms[2:])
        out["new_bind_commit_ms"] = _summary(bind_ms[2:])
    finally:
        dev.teardown()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=None, help="import control_center from this checkout instead")
    ap.add_argument("--native", action="store_true", help="also the Commit microbench on a device without a target")
    ap.add_argument("--json", default=None)
    ap.add_argument("--skip-tours", action="store_true")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root) if a.root else PROJECT
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.curdir) not in (HERE, os.path.dirname(HERE))]
    sys.path.insert(0, root)
    sys.setswitchinterval(0.001)
    import control_center
    out = {"root": root, "control_center": os.path.dirname(control_center.__file__)}
    if not a.skip_tours:
        out["tours"] = run_tours()
    out["holds"] = run_holds()
    out["picker"] = run_picker()
    out["episode_eval"] = run_episode_eval()
    if a.native:
        out["native"] = run_native()
    text = json.dumps(out, indent=1, default=str)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
