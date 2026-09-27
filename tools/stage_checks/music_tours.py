"""S1 tours E and U for the Music explorer and Up next on the stage (DESKTOP_STAGE §6.3, §6.4, §6.5 S1).

WP8 WROTE THIS SCRIPT BUT NEVER RAN IT ON SCREEN. The on-screen run shows the explorer and Up next
full-screen on the user's monitor for about a minute: run it only from the main session, with the
user's explicit go-ahead, the user at the PC:

    cd app
    .venv\\Scripts\\python.exe -I ..\\tools\\stage_checks\\music_tours.py --run --i-have-go-ahead [--stress] [--no-capture]

``--run`` first runs, in child processes, the two headless checks below on the same source and
starts the on-screen child only when both passed:

- ``--dry-run``: the tour scripts through both scenes on the fake engine rig (fake device, fake
  host, fake clock; nothing is shown, no GPU): every payload is validated and each tour must
  open, run and end in Play's close without a device violation or a logged error;
- ``--hidden``: the on-screen child's own code path on the real ``NanoD-stage`` thread with a host
  that is created hidden and refuses to show (``host_hidden_only``), a synthetic desktop instead of
  the capture, no hotkey, waits scaled by 0.1: every open must end in ``refused(device)`` after its
  whole build and commit, and nothing else may fail.

What runs on screen (§6.4): the production path, ``stage.scenes.start_music_stage`` (the
``NanoD-stage`` thread, the click-eating host, both scenes, the art workers) fed through
``StagePresenter`` with K3-shaped payloads from the simulator's library. No Sonos, no Apple Music,
no knob, no serial port, no network: every cover is the prototype's or synthesised.

- **Tour E** (explorer): Recently Added with 100 items: 20 detents at 10/s, a 1 s pause, 20 at
  20/s, 10 reversals at 20/s, a source switch to Favourite playlists and back, 10 detents, then
  Play (the 1.12 grow and the close at 380 ms). Three times on the monitor's own table (32:9 on the
  G93SC), then once with a forced 16:9 layout (a 16:9 rect centred on the monitor).
- **Tour U** (Up next): a 60-row playlist queue: the same detent pattern, Shuffle on and off (rows
  out at t0, back at t0 + 200), a Like (the heart pop), Play.
- ``--stress``: the same with §6.4's stress thread (a pure-Python burst of 10 ms every 25 ms).

Recorded in ``diagnostics\\music-tours-<stamp>[-stress].json``: every FrameStats episode the stage
recorded (the engine's compositor-statistics harvest, G1-3, each with §6.3's verdict: fps >= 0.979 x
rate, p95 <= 1.1 P, p99 and max <= 2.02 P, wake -> Commit <= 1.5 ms p95), the engine metrics after
each tour (open latency, counters), the art service's stats, the presenter events, and whether the
foreground window handle is unchanged (the host never activates; no title is read). Pass = every
judged episode passed, every open was "opened" and every tour ended "closed" by Play, and every
tour's detents were picked up on time (below).

**T2 (the 2026-09-26 frame-drop diagnosis): each tour's ``record``** places a miss against the event
that caused it: every committed stage batch (kind, phase, t1, the tick its Commit returned, work and
Commit ms, calls, the uploads its Commit carried), every interval over 1.5 P between the compositor
frames harvested during the tour (the frame after it: completed and target ticks, the interval in
P, an unread id range inside or not) and every upload wake (QPC seconds, uploads, bytes, ms). The
stage's episode records now carry their ``t_start`` / ``t_end`` ticks and, with the change model, the
``holds`` and ``*_in_motion`` figures §6.3's judge reads (S3). ``--dry-run`` also checks S1 on the
fake device: only the open's Commit carries uploads and no Commit would wait for the upload-Commit
spacing.

**Per-detent pickup and work (R-k, the S1 judgement of the explorer's per-detent budget).** A probe
(instrumentation in this child only: ``StageCore.finish``, ``CompositorHarvest.take`` and the two
scenes' ``update`` / ``position`` wrapped, nothing else changed) records every committed stage
event: its t1, the tick ``Commit`` returned, wake -> ``Commit`` (``work_ms``), the ``Commit`` time,
the COM calls and animations, the tour and the phase of the §6.4 pattern (``10/s``, ``20/s``,
``rev20``, ``after_switch``), plus every compositor frame the engine harvested. A detent's phase
travels with its call: the driver records (call, index, phase) on its own thread before it posts,
and the stage thread's event is joined to the newest record of the call and index it applied, so a
detent the stage picks up after the driver has moved on keeps its own phase (never the next one).
Per detent (a ``turn``), the pickup class is ``stage.proof``'s: the first composition that started
after ``Commit`` returned, its target time relative to t1 in periods (0 = at t1, 1 = t1 + P:
continuous, §4.6.5 item 5; >= 2 later; < 0 early); a detent whose frames the harvest could not read
is unknown, never late (the spike's rule). Each tour gets ``detents``: the per-detent rows, the
classes and shares per phase and in all, the share of commits returned before t1, and ``work_ms``
/ ``commit_ms`` / ``calls`` summaries; its pickup passes when at least ``PICKUP_ON_TIME_MIN`` (98 %)
of the known detents were picked up at t1 or t1 + P and none early (a tour with no known pickup is
not judged). **The lead accepted that threshold with WP8-D10 (2026-09-26; K4 §21.5)**; the report
carries it with its status (``pickup_rule``), and R-k stays open until these tours pass under it
on screen. ``--dry-run`` checks the probe itself (every tour records its turns, each with its
calls; a driver whose calls are picked up late keeps every detent in its own phase,
``phase_self_check``) and the classifier on synthetic frames (``report_self_check``); ``--hidden``
records nothing (its opens are refused).

Safety: a native thread-pool timer whose callback is ``TerminateProcess`` kills the child at 120 s
even with the GIL held; a Python watchdog hard-exits it at 103 s; the runner kills it at 150 s;
**Ctrl+Alt+F12** closes the open scene at once (reason ``idle``: an instant close) and ends the run.
The script refuses to show anything while the display sleeps or the session is locked. The desktop
snapshot for the frost never leaves memory (``--no-capture``: the tint-only frost). Nothing of the
user's is moved or activated; no companion, no settings, no credentials, no registry write.
"""
from __future__ import annotations

import argparse
import ctypes as C
import ctypes.wintypes as WT
import datetime
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ND = os.path.normpath(os.path.join(HERE, "..", "..", "app"))
if ND not in sys.path:
    sys.path.insert(0, ND)
DIAG = os.path.join(ND, "diagnostics")

NATIVE_KILL_S = 120.0
PY_WATCHDOG_S = 100.0
RUNNER_KILL_S = 150.0
HIDDEN_KILL_S = 60.0
HOTKEY_ID = 0x4D54
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, VK_F12 = 0x1, 0x2, 0x4000, 0x7B
WM_HOTKEY = 0x0312
CREATE_NO_WINDOW = 0x08000000
EXIT_OK, EXIT_FAILED, EXIT_REFUSED, EXIT_NO_GO, EXIT_ABORTED = 0, 2, 3, 4, 5
PICKUP_ON_TIME_MIN = 0.98             # R-k: detents picked up at t1 or t1 + P (known ones), per tour
PICKUP_RULE_STATUS = ("accepted (WP8-D10; lead, 2026-09-26; K4 21.5): R-k stays open until tours E and U "
                      "pass on screen")


def pacing_helpers():
    """WP7a's supervised-check helpers (watchdogs, display state), loaded from its script."""
    spec = importlib.util.spec_from_file_location("stage_pacing_check", os.path.join(HERE, "stage_pacing_check.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# =========================================================================== the tour scripts
def detent_pattern():
    """§6.4: (delay_s before the step, step, phase): 20 at 10/s, a 1 s pause, 20 at 20/s, 10
    reversals at 20/s."""
    out = [(0.1, +1, "10/s")] * 20
    out += [(1.0, 0, "pause")]
    out += [(0.05, +1, "20/s")] * 20
    out += [(0.05, +1 if i % 2 == 0 else -1, "rev20") for i in range(10)]
    return out


def _source_payload(p, t0, cid, rev):
    out = {k: p[k] for k in ("source", "state", "index", "count", "items", "items_first")}
    out.update(t0=t0, items_rev=rev, control_id=cid)
    return out


def explorer_tour(driver, label):
    """Tour E (see the module docstring). K3 re-sends the item window whenever its first index
    moves (``_explorer_push_highlight``) and gives each source its own control."""
    from control_center.stage.scenes import testing as T
    items = T.explorer_payload(0.0, recent="many", art="mixed", window=False)["items"]
    n = len(items)
    index, cid, rev = 30, 1, 1
    driver.call("explorer_open", T.explorer_payload(driver.now(), index=index, recent="many", art="mixed",
                                                    control_id=cid))
    driver.wait(1.2)
    first = max(0, index - 12)
    for delay, step, phase in detent_pattern():
        driver.mark(phase)
        driver.wait(delay)
        if not step:
            continue
        index = max(0, min(n - 1, index + step))
        p = {"index": index, "control_id": cid, "bump": 0}
        f = max(0, index - 12)
        if f != first:
            first = f
            p.update(items=items[f:index + 17], items_first=f, items_rev=rev)
        driver.call("explorer_highlight", p, phase=phase)
    driver.wait(0.6)
    driver.mark("switch")
    cid, rev = cid + 1, rev + 1
    fav = T.explorer_payload(driver.now(), source="favourites", index=3, favs="many")
    driver.call("explorer_source", _source_payload(fav, driver.now(), cid, rev))
    driver.wait(0.8)
    cid, rev = cid + 1, rev + 1
    back = T.explorer_payload(driver.now(), index=index, recent="many", art="mixed")
    driver.call("explorer_source", _source_payload(back, driver.now(), cid, rev))
    driver.wait(0.8)
    first = back["items_first"]
    driver.mark("after_switch")
    for _ in range(10):
        driver.wait(0.1)
        index = min(n - 1, index + 1)
        p = {"index": index, "control_id": cid, "bump": 0}
        f = max(0, index - 12)
        if f != first:
            first = f
            p.update(items=items[f:index + 17], items_first=f, items_rev=rev)
        driver.call("explorer_highlight", p, phase="after_switch")
    driver.wait(0.8)
    driver.mark("play")
    driver.call("explorer_close", {"t0": driver.now(), "reason": "play", "close_at_ms": 380})
    driver.wait(1.4)
    return {"tour": "E", "layout": label, "detents": 60, "items": n}


def upnext_tour(driver, label):
    """Tour U (see the module docstring)."""
    from control_center.stage.scenes import testing as T
    now, cid = 20, 1
    p = T.upnext_payload(driver.now(), kind="playlist", rows=60, now=now, art="mixed", liked=(3, 9), control_id=cid)
    count = p["count"]
    driver.call("upnext_open", p)
    driver.wait(1.2)
    focus = now
    for delay, step, phase in detent_pattern():
        driver.mark(phase)
        driver.wait(delay)
        if step:
            focus = max(0, min(count - 1, focus + step))
            driver.call("upnext_highlight", {"index": focus, "control_id": cid, "bump": 0}, phase=phase)
    driver.wait(0.8)
    driver.mark("shuffle")
    rows = p["rows"]
    shuffled = [dict(r, row=j + 1) for j, r in enumerate(rows[:now + 1] + list(reversed(rows[now + 1:])))]
    base = {"now": now, "count": count, "card": None, "likes_known": True}
    for new_rows, mode in ((shuffled, "companion"), (rows, "off")):
        cid += 1
        driver.call("upnext_rows", dict(base, t0=driver.now(), reason="shuffle", rows=new_rows, focus=now + 1,
                                        shuffle=mode, control_id=cid))
        driver.wait(1.0)
    driver.call("upnext_rows", dict(base, t0=driver.now(), reason="likes", rows=[{"row": now + 2, "liked": True}],
                                    focus=now + 1, shuffle="off"))
    driver.wait(1.2)
    driver.call("upnext_close", {"t0": driver.now(), "reason": "play", "close_at_ms": 380})
    driver.wait(1.4)
    return {"tour": "U", "layout": label, "detents": 50, "rows": count}


# =========================================================================== the per-detent probe (R-k)
_MISSING = object()


class DetentProbe:
    """Records every committed stage event and every harvested compositor frame (see the module
    docstring). ``install`` wraps ``StageCore.finish`` (called on the stage thread right after an
    event's ``Commit``), ``CompositorHarvest.take`` (the engine's episode-end harvest) and the two
    scenes' ``update`` / ``position`` (the call and index the stage thread applies) in this
    process; ``uninstall`` restores them.

    ``tour`` and ``phase`` are set by the driver thread (``mark``) and label the events that are no
    detents (open, switch, shuffle, Play). A detent's own tour and phase are recorded with its call
    (``posted``, on the driver thread, before the post) and joined in ``note`` to the newest record
    of the call and index the stage thread applied: the stage picks a call up later, after the
    driver has already marked the next phase (WP8T-3)."""

    def __init__(self):
        self.rows = []
        self.frames = []
        self.frame_tours = []             # the tour each harvested frame was taken in (T2)
        self.unknown = []
        self.upload_wakes = []            # T2: every upload wake (its uploads, bytes, the upload Commit's ms)
        self.tour = None
        self.phase = None
        self.posts = []                   # (call, index, tour, phase) per posted call, driver thread
        self._applying = None             # (call, index) the stage thread is applying, read by ``note``
        self._saved = []

    def install(self):
        from control_center.stage import engine as EN
        from control_center.stage import frames as FR
        from control_center.stage import surfaces as SU
        from control_center.stage.scenes.explorer import ExplorerScene
        from control_center.stage.scenes.upnext import UpNextScene
        probe = self
        orig_finish, orig_take = EN.StageCore.finish, FR.CompositorHarvest.take

        def finish(core, batch, kind):
            try:
                probe.note(core, batch, kind)
            except Exception:
                pass
            return orig_finish(core, batch, kind)

        def take(harvest):
            frames, unknown = orig_take(harvest)
            probe.frames.extend(frames)
            probe.frame_tours.extend([probe.tour] * len(frames))
            probe.unknown.extend(unknown)
            return frames, unknown
        self._saved = [(EN.StageCore, "finish", EN.StageCore.__dict__.get("finish", _MISSING)),
                       (FR.CompositorHarvest, "take", FR.CompositorHarvest.__dict__.get("take", _MISSING))]
        EN.StageCore.finish = finish
        FR.CompositorHarvest.take = take
        orig_upload = SU.UploadQueue.__dict__.get("upload")
        if orig_upload is not None:                     # the upload wakes (S1 of the 2026-09-26 fixes)
            def upload(queue, *a, _orig=orig_upload, **k):
                b0, t0 = queue.stats.get("bytes", 0), time.perf_counter()
                n = _orig(queue, *a, **k)
                if n:
                    try:
                        probe.upload_wakes.append({"tour": probe.tour, "t_perf": round(t0, 6), "uploads": n,
                                                   "bytes": queue.stats.get("bytes", 0) - b0,
                                                   "ms": round((time.perf_counter() - t0) * 1000.0, 3)})
                    except Exception:
                        pass
                return n
            self._saved.append((SU.UploadQueue, "upload", orig_upload))
            SU.UploadQueue.upload = upload
        for cls in (ExplorerScene, UpNextScene):
            orig_update, orig_position = cls.update, cls.position

            def update(scene, batch, call, payload, _orig=orig_update):
                probe._applying = (call, payload.get("index") if isinstance(payload, dict) else None)
                return _orig(scene, batch, call, payload)

            def position(scene, batch, index, _orig=orig_position):
                probe._applying = ("position", index)
                return _orig(scene, batch, index)
            self._saved += [(cls, "update", cls.__dict__.get("update", _MISSING)),
                            (cls, "position", cls.__dict__.get("position", _MISSING))]
            cls.update, cls.position = update, position
        return self

    def uninstall(self):
        for owner, name, fn in reversed(self._saved):
            if fn is _MISSING:
                try:
                    delattr(owner, name)
                except AttributeError:
                    pass
            else:
                setattr(owner, name, fn)
        self._saved = []

    def posted(self, call, payload, phase):
        """The driver is about to post ``call``: its index, tour and phase (driver thread)."""
        index = payload.get("index") if isinstance(payload, dict) else None
        self.posts.append((call, index, self.tour, phase))

    def origin(self, call, index):
        """(tour, phase) of the newest posted ``call`` with ``index``, or None."""
        posts = self.posts
        for j in range(len(posts) - 1, -1, -1):
            c, i, tour, phase = posts[j]
            if c == call and i == index:
                return tour, phase
        return None

    def note(self, core, batch, kind):
        applying, self._applying = self._applying, None
        tour, phase = self.tour, self.phase
        if kind == "turn" and applying is not None:
            found = self.origin(*applying)
            if found is not None and found[1] is not None:
                tour, phase = found
        clock = core.clock
        done = clock.from_perf(batch.t_done) if batch.t_done is not None else None
        self.rows.append({"tour": tour, "phase": phase, "surface": core.surface, "kind": kind,
                          "t1": int(batch.t1), "done": done, "period": float(core.period), "freq": int(clock.freq),
                          "work_ms": batch.work_ms, "commit_ms": batch.commit_ms, "calls": batch.calls,
                          "anims": batch.anims, "carried": getattr(batch, "carried", None)})

    def report(self, tour):
        """The ``detents`` block of one tour (see the module docstring)."""
        return detent_report([r for r in self.rows if r["tour"] == tour], self.frames, self.unknown)

    def record(self, tour):
        """T2 of the 2026-09-26 diagnosis: what places a miss against the event that caused it. Every
        committed batch of the tour (kind, phase, t1, the tick its Commit returned, work, Commit, calls,
        the uploads it carried), every interval over 1.5 P between the compositor frames harvested in
        it (the frame after the gap: its completed and target ticks, the interval in P, whether an
        unread id range lies inside), and every upload wake (QPC seconds, uploads, bytes, ms)."""
        rows = [{k: (round(v, 3) if isinstance(v, float) and k.endswith("_ms") else v) for k, v in r.items()
                 if k not in ("tour", "freq", "period")} for r in self.rows if r["tour"] == tour]
        mine = sorted((f for f, t in zip(self.frames, self.frame_tours) if t == tour), key=lambda f: f.id)
        period = next((r["period"] for r in self.rows if r["tour"] == tour), None)
        gaps = []
        if period:
            for a, b in zip(mine, mine[1:]):
                dt = (b.completed_time - a.completed_time) / period
                if dt > 1.5:
                    gaps.append({"completed": int(b.completed_time), "target": int(b.target_time),
                                 "dt_P": round(dt, 3),
                                 "unknown": any(hi > a.id and lo < b.id for lo, hi in self.unknown)})
        return {"batches": rows, "frame_gaps": gaps, "frames": len(mine),
                "first_frame": int(mine[0].completed_time) if mine else None,
                "last_frame": int(mine[-1].completed_time) if mine else None,
                "upload_wakes": [{k: v for k, v in w.items() if k != "tour"} for w in self.upload_wakes
                                 if w["tour"] == tour]}


def _share(n, d):
    return None if not d else round(n / d, 4)


def _classes(ks):
    known = [k for k in ks if k is not None]
    n = len(known)
    return {"detents": len(ks), "known": n, "at_t1": sum(1 for k in known if k == 0),
            "t1_plus_P": sum(1 for k in known if k == 1), "later": sum(1 for k in known if k >= 2),
            "early": sum(1 for k in known if k < 0),
            "at_t1_share": _share(sum(1 for k in known if k == 0), n),
            "on_time_share": _share(sum(1 for k in known if k in (0, 1)), n)}


def pickup_ks(frames, unknown, events, period):
    """``stage.proof.pickup_classes``'s k per event (the first composition that started after
    ``Commit`` returned, its target relative to t1 in periods), None when no such frame was
    harvested or an id range the harvest could not read lies between it and the frame before (the
    spike's rule: unknown, never late)."""
    import bisect
    by_start = sorted((f for f in frames if f.start_time), key=lambda f: f.start_time)
    starts = [f.start_time for f in by_start]
    ks = []
    for ev in events:
        i = bisect.bisect_right(starts, ev["done"])
        if i >= len(by_start) or i == 0:
            ks.append(None)
            continue
        fa, fb = by_start[i], by_start[i - 1]
        lo, hi = min(fa.id, fb.id), max(fa.id, fb.id)
        if any(b > lo and a < hi for a, b in unknown):
            ks.append(None)
            continue
        ks.append(int(round((fa.target_time - ev["t1"]) / period)))
    return ks


def detent_report(rows, frames, unknown=()):
    """Per-detent pickup (``pickup_ks``) and work for the ``turn`` events of ``rows``; the
    verdict is None when no pickup is known (the fake rig, the hidden host)."""
    from control_center.stage import frames as FR
    turns = [r for r in rows if r["kind"] == "turn" and r["done"] is not None]
    if not turns:
        return {"detents": 0, "pickup": _classes([]), "pickup_pass": None, "pickup_rule": pickup_rule(),
                "per_detent": []}
    period = sorted(r["period"] for r in turns)[len(turns) // 2]
    freq = turns[0]["freq"]
    ks = pickup_ks(frames, unknown, [{"t1": r["t1"], "done": r["done"]} for r in turns], period)
    per = []
    for j, (r, k) in enumerate(zip(turns, ks)):
        per.append({"i": j, "phase": r["phase"], "surface": r["surface"], "k": k,
                    "lead_ms": round((r["t1"] - r["done"]) * 1000.0 / freq, 3),
                    "work_ms": None if r["work_ms"] is None else round(r["work_ms"], 3),
                    "commit_ms": None if r["commit_ms"] is None else round(r["commit_ms"], 3),
                    "calls": r["calls"], "anims": r["anims"]})
    phases = {}
    for row in per:
        phases.setdefault(row["phase"], []).append(row)
    by_phase = {ph: dict(_classes([x["k"] for x in xs]),
                         work_ms=FR.summary([x["work_ms"] for x in xs if x["work_ms"] is not None]),
                         commit_ms=FR.summary([x["commit_ms"] for x in xs if x["commit_ms"] is not None]),
                         commit_before_t1_share=_share(sum(1 for x in xs if x["lead_ms"] > 0), len(xs)))
                for ph, xs in phases.items()}
    cls = _classes(ks)
    verdict = None
    if cls["known"]:
        verdict = (cls["on_time_share"] or 0.0) >= PICKUP_ON_TIME_MIN and cls["early"] == 0
    work = [x["work_ms"] for x in per if x["work_ms"] is not None]
    commit = [x["commit_ms"] for x in per if x["commit_ms"] is not None]
    return {"detents": len(per), "pickup": cls, "pickup_pass": verdict, "pickup_rule": pickup_rule(),
            "commit_before_t1_share": _share(sum(1 for x in per if x["lead_ms"] > 0), len(per)),
            "work_ms": FR.summary(work) if work else None, "commit_ms": FR.summary(commit) if commit else None,
            "calls": FR.summary([x["calls"] for x in per], 1),
            "anims": FR.summary([x["anims"] for x in per], 1), "by_phase": by_phase,
            "frames_harvested": len(frames), "per_detent": per}


def pickup_rule():
    """The pickup verdict's rule and its status: accepted with WP8-D10 (lead, 2026-09-26)."""
    return {"on_time_min": PICKUP_ON_TIME_MIN, "early_max": 0, "status": PICKUP_RULE_STATUS}


def report_self_check():
    """``detent_report`` on synthetic frames (240 Hz, 10 MHz): commits returned before t1, one frame
    late, two late and one early are classed 0, 1, 2 and -1; the verdict follows the shares."""
    from control_center.stage.frames import TargetFrame
    freq, P = 10_000_000, 10_000_000 / 240.0
    frames = [TargetFrame(i, int(1_000_000 + i * P + P), int(1_000_000 + i * P + P), i, i,
                          start_time=int(1_000_000 + i * P - P / 2), target_time=int(1_000_000 + i * P))
              for i in range(200)]
    base = {"tour": 0, "phase": "20/s", "surface": "explorer", "kind": "turn", "period": P, "freq": freq,
            "work_ms": 1.0, "commit_ms": 0.1, "calls": 490, "anims": 63}

    def row(frame_i, done_offset):
        t1 = frames[frame_i].target_time
        return dict(base, t1=t1, done=int(t1 + done_offset))
    # a frame starts P/2 before its target: done in (t1 - 1.5P, t1 - 0.5P) is picked up at t1 (k 0),
    # [t1 - 0.5P, t1 + 0.5P) at t1 + P, [t1 + 0.5P, t1 + 1.5P) two late, [t1 - 2.5P, t1 - 1.5P) early
    rows = [row(10, -0.6 * P), row(20, -1.0 * P), row(30, 0.25 * P), row(40, 1.25 * P), row(50, -1.75 * P)]
    rep = detent_report(rows, frames)
    ks = [x["k"] for x in rep["per_detent"]]
    ok = ks == [0, 0, 1, 2, -1] and rep["pickup"]["early"] == 1 and rep["pickup_pass"] is False
    good = detent_report(rows[:3] * 40, frames)
    ok = ok and good["pickup_pass"] is True and good["pickup"]["on_time_share"] == 1.0
    gap = detent_report(rows[:2], [f for f in frames if f.id != 10], [(10, 10)])   # frame 10 unread
    ok = ok and [x["k"] for x in gap["per_detent"]] == [None, 0] and gap["pickup"]["known"] == 1
    return ok, ks


def phase_self_check():
    """Tour E on the fake rig with every call picked up late (``LaggingDryDriver``): each detent
    keeps its own phase (20 at ``10/s``, 20 at ``20/s``, 10 ``rev20``, 10 ``after_switch``; none in
    the pause), with the probe's own join (WP8T-3). Returns (ok, the turns per phase)."""
    probe = DetentProbe().install()
    try:
        d = LaggingDryDriver("32:9", probe)
        probe.tour, probe.phase = 0, None
        explorer_tour(d, "32:9")
        rep = probe.report(0)
    finally:
        probe.uninstall()
    split = {}
    for x in rep["per_detent"]:
        split[x["phase"]] = split.get(x["phase"], 0) + 1
    return split == {"10/s": 20, "20/s": 20, "rev20": 10, "after_switch": 10}, split


def _detent_line(label, rep):
    pk = rep["pickup"]
    w = rep.get("work_ms") or {}
    c = rep.get("commit_ms") or {}
    return (f"{label}: {rep['detents']} detents, pickup at t1 {pk.get('at_t1')}, t1+P {pk.get('t1_plus_P')}, "
            f"later {pk.get('later')}, early {pk.get('early')} (known {pk.get('known')}; on time "
            f"{pk.get('on_time_share')}), commit before t1 {rep.get('commit_before_t1_share')}, work p50 "
            f"{w.get('p50')} / p95 {w.get('p95')} ms (Commit p95 {c.get('p95')} ms), calls p50 "
            f"{(rep.get('calls') or {}).get('p50')}; pickup rule: {PICKUP_RULE_STATUS}")


# =========================================================================== drivers
class DryDriver:
    """The fake engine rig: every call validated and processed, fake time advanced by the waits."""

    def __init__(self, monitor="32:9", probe=None):
        from control_center.stage.scenes import testing as T
        self.rig = T.SceneRig(monitor, keep_pixels=False)
        self.calls = 0
        self.events = []
        self.probe = probe

    def mark(self, phase):
        if self.probe is not None:
            self.probe.phase = phase

    def now(self):
        return self.rig.now()

    def call(self, name, payload, phase=None):
        """Post one call; a detent's ``phase`` is recorded with it before the post (WP8T-3)."""
        if self.probe is not None:
            self.probe.posted(name, payload, phase)
        self._post(name, payload)
        self.calls += 1

    def _post(self, name, payload):
        getattr(self.rig.presenter, name)(payload)
        self.rig.settle()

    def wait(self, s):
        if s > 0:
            self.rig.advance(s * 1000.0, 50)
        self.events.extend(self.rig.events())


class LaggingDryDriver(DryDriver):
    """The fake rig with the stage picking every call up late: a call is processed only at the
    driver's next ``wait``, after the tour has moved on (and marked the next phase), as the
    ``NanoD-stage`` thread does on screen (``phase_self_check``)."""

    def __init__(self, monitor="32:9", probe=None):
        super().__init__(monitor, probe)
        self.queue = []

    def _post(self, name, payload):
        self.queue.append((name, payload))

    def wait(self, s):
        queue, self.queue = self.queue, []
        for name, payload in queue:
            DryDriver._post(self, name, payload)
        super().wait(s)


class ScreenDriver:
    """The production stage (``start_music_stage``). The waits pump this thread's message queue
    for the abort hotkey (registered to this thread) and collect every FrameStats episode."""

    def __init__(self, stage, presenter, scale=1.0, probe=None):
        self.stage = stage
        self.presenter = presenter
        self.scale = scale
        self.aborted = None
        self.events = []
        self.calls = 0
        self.episodes = []
        self._seen = set()
        self._next_harvest = 0.0
        self.probe = probe

    def mark(self, phase):
        if self.probe is not None:
            self.probe.phase = phase

    def now(self):
        return time.perf_counter()

    def call(self, name, payload, phase=None):
        """Post one call (it returns at once; the stage thread applies it later); a detent's
        ``phase`` is recorded with it before the post (WP8T-3)."""
        if self.aborted:
            raise KeyboardInterrupt(self.aborted)
        if self.probe is not None:
            self.probe.posted(name, payload, phase)
        getattr(self.presenter, name)(payload)
        self.calls += 1

    def abort(self, why):
        self.aborted = self.aborted or why

    def harvest(self):
        try:
            frames = (self.stage.metrics() or {}).get("frames") or {}
        except Exception:
            return
        for surface, rec in frames.items():
            for which in ("last", "worst"):
                ep = rec.get(which)
                if not ep:
                    continue
                key = json.dumps(ep, sort_keys=True, default=str)
                if key not in self._seen:
                    self._seen.add(key)
                    self.episodes.append({"surface": surface, "slot": which, "episode": ep})

    def wait(self, s):
        t_end = time.perf_counter() + s * self.scale
        msg = WT.MSG()
        u32 = C.windll.user32
        while True:
            while u32.PeekMessageW(C.byref(msg), None, 0, 0, 1):
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self.abort("hotkey")
            self.events.extend(self.presenter.take_events())
            t = time.perf_counter()
            if t >= self._next_harvest:
                self._next_harvest = t + 0.25
                self.harvest()
            if self.aborted:
                for surface in ("explorer", "upnext"):
                    try:
                        getattr(self.presenter, surface + "_close")({"t0": time.perf_counter(), "reason": "idle",
                                                                     "close_at_ms": 0})
                    except Exception:
                        pass
                raise KeyboardInterrupt(self.aborted)
            left = t_end - time.perf_counter()
            if left <= 0:
                return
            time.sleep(min(0.004, left))


class Hog(threading.Thread):
    """§6.4's stress thread: pure Python, 10 ms of work every 25 ms."""

    def __init__(self):
        super().__init__(name="music-tours-hog", daemon=True)
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


# =========================================================================== runs
def run_dry():
    """Headless: the tours through the scenes on the fake rig."""
    out = {"mode": "dry", "tours": []}
    ok, ks = report_self_check()
    out["pickup_report_self_check"] = {"ok": ok, "k": ks}
    print(json.dumps({"pickup_report_self_check": ok, "k": ks}), flush=True)
    pok, split = phase_self_check()
    out["phase_self_check"] = {"ok": pok, "turns_per_phase": split}
    print(json.dumps({"phase_self_check": pok, "turns_per_phase": split}), flush=True)
    ok = ok and pok
    probe = DetentProbe().install()
    try:
        runs = [(n, tour, monitor) for n, (tour, monitor) in
                enumerate(((explorer_tour, "32:9"), (explorer_tour, "16:9"), (upnext_tour, "32:9")))]
        for n, tour, monitor in runs:
            t = time.perf_counter()
            d = DryDriver(monitor, probe)
            probe.tour, probe.phase = n, None
            info = tour(d, monitor)
            kinds = [k for k, _p in d.events]
            det = probe.report(n)
            info.update(calls=d.calls, events=kinds, violations=d.rig.dev.violations[:3],
                        errors=[x for x in d.rig.logs if "error" in x.lower()][:3],
                        seconds=round(time.perf_counter() - t, 1),
                        detents={k: det[k] for k in ("detents", "calls", "pickup_pass")})
            probe_ok = det["detents"] >= 20 and all(x["calls"] > 0 for x in det["per_detent"]) \
                and {x["phase"] for x in det["per_detent"]} >= {"10/s", "20/s", "rev20"}
            # S1 of the 2026-09-26 frame-drop fixes, on the fake device's model: only the open's Commit
            # carries uploads (every other upload has its own paced upload Commit), and no Commit of
            # the tour would wait for the native upload-Commit spacing (``FakeDevice.throttled``)
            rec = probe.record(n)
            carrying = sorted({r["kind"] for r in rec["batches"] if r.get("carried")})
            throttled = getattr(d.rig.dev, "throttled", [])
            info["s1"] = {"batches": len(rec["batches"]), "upload_wakes": len(rec["upload_wakes"]),
                          "kinds_carrying_uploads": carrying, "commits_that_would_wait": len(throttled)}
            s1_ok = set(carrying) <= {"open"} and not throttled
            good = kinds == ["opened", "closed"] and not info["violations"] and not info["errors"] and probe_ok \
                and s1_ok
            info["ok"] = good
            ok = ok and good
            out["tours"].append(info)
            print(json.dumps({k: info[k] for k in ("tour", "layout", "calls", "events", "ok", "seconds", "errors",
                                                   "detents", "s1")}, default=str), flush=True)
    finally:
        probe.uninstall()
    out["pass"] = ok
    return (EXIT_OK if ok else EXIT_FAILED), out


def _forced_16x9(mon):
    rect = mon["rect"] if isinstance(mon, dict) else mon
    l, t, r, b = rect
    w = min(r - l, int(round((b - t) * 16 / 9)))
    x = l + (r - l - w) // 2
    forced = (x, t, x + w, b)
    return dict(mon, rect=forced) if isinstance(mon, dict) else forced


def run_child(args):
    """The on-screen child, or (``--hidden``) its headless twin (see the module docstring)."""
    pc = pacing_helpers()
    hidden = bool(args.hidden)
    if not hidden:
        disp = pc.display_usable()
        if not disp.get("usable"):
            print(json.dumps({"refused": "display asleep or session locked", "display": disp}), flush=True)
            return EXIT_REFUSED, {"refused": disp}
    wd = pc.arm_native_watchdog(int((HIDDEN_KILL_S if hidden else NATIVE_KILL_S) * 1000))
    pywd = pc.PyWatchdog((HIDDEN_KILL_S - 8.0) if hidden else PY_WATCHDOG_S, lambda: 0)
    pywd.start()
    u32 = C.windll.user32
    hotkey = False
    if not hidden:
        hotkey = bool(u32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_F12))
    C.windll.winmm.timeBeginPeriod(1)
    sys.setswitchinterval(0.001)
    fg_before = u32.GetForegroundWindow()
    from control_center.stage.scenes import default_covers_dir, start_music_stage
    kw = {}
    if hidden:
        from PIL import Image

        def grab(rect):
            return Image.linear_gradient("L").resize((max(1, int(rect[2])), max(1, int(rect[3])))).convert("RGB")
        kw = {"host_hidden_only": True, "capture_grab": grab}
    elif args.no_capture:
        kw = {"capture_grab": lambda rect: None}
    logs = []
    probe = DetentProbe().install()
    stage, presenter, art = start_music_stage(log=logs.append, covers_dir=default_covers_dir(), fetch=False, **kw)
    driver = ScreenDriver(stage, presenter, scale=0.1 if hidden else 1.0, probe=probe)
    hog = Hog() if args.stress else None
    if hog:
        hog.start()
    out = {"mode": "hidden" if hidden else "onscreen", "stress": bool(args.stress), "hotkey": hotkey,
           "tours": [], "started": datetime.datetime.now().isoformat(timespec="seconds")}
    code = EXIT_OK
    try:
        plan = [(explorer_tour, "monitor"), (explorer_tour, "monitor"), (explorer_tour, "monitor"),
                (upnext_tour, "monitor"), (explorer_tour, "16:9 forced")]
        for n, (tour, label) in enumerate(plan):
            probe.tour, probe.phase = n, None
            if label == "16:9 forced":
                eng = stage.engine
                if eng is not None:
                    mon = eng.monitor_for(0)
                    if mon:
                        forced = _forced_16x9(mon)
                        eng.monitor_for = lambda hwnd, forced=forced: forced
            n_events = len(driver.events)
            info = tour(driver, label)
            driver.harvest()
            info["events"] = [k for k, _p in driver.events[n_events:]]
            m = stage.metrics() or {}
            info["metrics"] = {k: v for k, v in m.items() if k != "frames"}
            out["tours"].append(info)
    except KeyboardInterrupt as exc:
        out["aborted"] = str(exc)
        code = EXIT_ABORTED
    except Exception as exc:                                  # recorded, the stage still closed below
        out["exception"] = f"{type(exc).__name__}: {exc}"
        code = EXIT_FAILED
    finally:
        if hog:
            hog.stop = True
        try:
            driver.wait(0.5)
        except KeyboardInterrupt:
            pass
        driver.harvest()
        out["foreground_unchanged"] = u32.GetForegroundWindow() == fg_before
        out["art"] = dict(getattr(art, "stats", {}) or {})
        try:
            stage.close(2.0)
            art.close(1.0)
        finally:
            if hotkey:
                u32.UnregisterHotKey(None, HOTKEY_ID)
            C.windll.winmm.timeEndPeriod(1)
            pywd.done.set()
            pc.disarm_native_watchdog(wd)
            probe.uninstall()
    for n, info in enumerate(out["tours"]):
        info["detents"] = probe.report(n)
        info["record"] = probe.record(n)                          # T2: batches, frame gaps, upload wakes
    out["episodes"] = driver.episodes
    out["errors"] = [x for x in logs if "error" in x.lower() and "refus" not in x.lower()
                     and "hidden-only" not in x][:10]            # the hidden host's own refusal of the show
    kinds = [k for info in out["tours"] for k in info["events"]]
    if hidden:
        good = (len(out["tours"]) == 5 and all(info["events"] and set(info["events"]) == {"refused"}
                                                for info in out["tours"])
                and not out["errors"] and "exception" not in out)
    else:
        judged = [e["episode"].get("pass") for e in driver.episodes if e["episode"].get("pass") is not None]
        pickups = [info["detents"]["pickup_pass"] for info in out["tours"]
                   if info["detents"]["pickup_pass"] is not None]
        good = (len(out["tours"]) == 5 and all(info["events"] == ["opened", "closed"] for info in out["tours"])
                and all(judged) and bool(judged) and out["foreground_unchanged"] and "exception" not in out
                and all(pickups) and bool(pickups))
        out["judged_episodes"] = len(judged)
        out["judged_pickups"] = len(pickups)
        for n, info in enumerate(out["tours"]):
            print(_detent_line(f"{info.get('tour')}#{n} {info.get('layout')}", info["detents"]), flush=True)
    out["pass"] = bool(good) and code == EXIT_OK
    if code == EXIT_OK and not out["pass"]:
        code = EXIT_FAILED
    print(json.dumps({"mode": out["mode"], "pass": out["pass"], "events": kinds[:12],
                      "episodes": len(driver.episodes), "errors": out["errors"][:3],
                      "exception": out.get("exception")}, default=str), flush=True)
    return code, out


def _child(flags, timeout):
    cmd = [sys.executable, "-I", os.path.abspath(__file__)] + flags
    p = subprocess.Popen(cmd, cwd=ND, creationflags=CREATE_NO_WINDOW)
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
    return p.returncode


def run_runner(args):
    for flags, timeout in ((["--dry-run"], 600.0), (["--hidden"], HIDDEN_KILL_S + 10.0)):
        rc = _child(flags, timeout)
        print(json.dumps({"precheck": flags[0], "exit": rc}), flush=True)
        if rc != EXIT_OK:
            print("a headless precheck failed: nothing shown", flush=True)
            return EXIT_FAILED
    flags = ["--child-onscreen", "--i-have-go-ahead"] + (["--stress"] if args.stress else []) + \
        (["--no-capture"] if args.no_capture else [])
    rc = _child(flags, RUNNER_KILL_S)
    print(json.dumps({"onscreen_exit": rc}), flush=True)
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="headless: the fake engine rig, nothing shown")
    g.add_argument("--hidden", action="store_true", help="headless: the real stage thread, a host that never shows")
    g.add_argument("--run", action="store_true", help="both headless checks, then one on-screen child")
    g.add_argument("--child-onscreen", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--i-have-go-ahead", action="store_true")
    ap.add_argument("--stress", action="store_true")
    ap.add_argument("--no-capture", action="store_true")
    a = ap.parse_args(argv)
    if (a.run or a.child_onscreen) and not a.i_have_go_ahead:
        print("refusing: the on-screen tours need --i-have-go-ahead (the user's explicit OK, given in chat)")
        return EXIT_NO_GO
    if a.dry_run:
        code, out = run_dry()
        print(json.dumps({"pass": out["pass"]}))
        return code
    if a.run:
        return run_runner(a)
    code, out = run_child(a)
    if not a.hidden:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(DIAG, f"music-tours-{stamp}{'-stress' if a.stress else ''}.json")
        pacing_helpers().write_json(path, out)
        print(path, flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
