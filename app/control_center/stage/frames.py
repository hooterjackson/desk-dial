"""FrameStats and frame pacing (DESKTOP_STAGE §5, §6.1-§6.3 with G1-1, G1-2 and G1-3).

**Stage surfaces (explorer, Up next): compositor statistics (§6.1, AR-13).** DWM evaluates our
animations at every composed frame, so displayed frames during an episode are our motion
frames. ``CompositorHarvest`` walks the completed frame ids through
``DCompositionGetStatistics`` / ``DCompositionGetTargetStatistics`` for the monitor's target,
through **GIL-keeping** calls (G1-1), at a low-rate wake every 250 ms of an episode and once at
its end, and **only while the display is on** (G1-3). G1-3 also fixes how frames are counted:
- never from frame-id differences (ids race while the display sleeps and DWM keeps ~300);
- displayed frames are counted with the target's running ``presentCount`` and each one is put
  on the vblank grid from ``completedStats.time`` (R = 1.000 on screen; ``presentTime`` is not);
- lost ids are **unknown**, never missed; an episode above 0.5 % unknown is invalid;
- ``DwmGetCompositionTimingInfo(NULL).cRefresh`` is not a refresh counter.

**Python-stepped surfaces (§5; picker, toast, floating knob; wired by WP7b and WP10):**
``ClockWait`` paces on ``DCompositionWaitForCompositorClock`` with the thread's mailbox among
the handles (P3). G1-2: while the display sleeps the call returns ``0xC01E0006`` at once, so any
return that is neither a tick nor a handle is "no clock": wait one P on a high-resolution
waitable timer instead, and stop the loop when the display is off; never loop on the call
unguarded. ``Pacer`` implements P2 (sample at the predicted display time), P4 (judge pacing by
wake intervals) and P5 (the 120 lock with hysteresis: lock above 0.8 P work p95 over 0.5 s,
unlock after 0.5 s below 0.6 P).

``FrameStats`` keeps ``last``, ``worst`` and ``totals`` per surface and kind for
``stage.metrics()`` (§6.2 export), and logs one line per episode that misses §6.3, at most one
per 30 s per surface. The stage's episode record (``engine.StageCore.end_episode``) also carries
``cpu_pct_one_core``: ``GetThreadTimes`` of every stage thread (``NanoD-stage`` and
``NanoD-stage-capture``, ``win32.ThreadCpu``) over the episode's wall time, as a share of one
core (§6.2, the §6.3 CPU column); and ``NANOD_FPS_HUD=1`` shows the newest record as a small text
sprite on the stage, re-drawn 4 times a second, never per frame (§6.2 "HUD"; ``engine``).
"""
from __future__ import annotations

import copy
import math
import statistics
import threading

HARVEST_PERIOD_S = 0.250
UNKNOWN_MAX_SHARE = 0.005
LOG_EVERY_S = 30.0
MAX_WALK = 4000

# §6.3 thresholds, in periods P or fractions of the rate.
STAGE_THRESHOLDS = {"fps_ratio": 0.979, "p95_P": 1.1, "p99_P": 2.02, "max_P": 2.02, "work_p95_ms": 1.5}
LOOP_THRESHOLDS = {
    "picker": {"fps_ratio": 0.49, "p95_P": 2.02, "max_P": 3.0, "work_p95_ms": 5.6},
    "picker_gpu": {"fps_ratio": 0.979, "p95_P": 1.1, "p99_P": 2.02, "work_p95_ms": 1.5},
    "knob_slide": {"fps_ratio": 0.979, "p95_P": 1.1, "max_P": 2.02, "work_p95_ms": 0.2},
    "toast": {"fps_ratio": 0.979, "p95_P": 1.1, "work_p95_ms": 1.0},
}
RING_THRESHOLDS = {"on_target": 0.98, "late_2P": 0.005, "work_p95_ms": 2.5}


def quantile(sorted_xs, p):
    """Nearest-rank quantile (the spike's method for p95 / p99)."""
    n = len(sorted_xs)
    return sorted_xs[min(n - 1, max(0, int(math.ceil(p * n)) - 1))] if n else None


def summary(xs, nd=3):
    xs = [float(x) for x in xs if x is not None]
    if not xs:
        return None
    ys = sorted(xs)
    return {"n": len(ys), "p50": round(statistics.median(ys), nd), "p95": round(quantile(ys, 0.95), nd),
            "p99": round(quantile(ys, 0.99), nd), "max": round(ys[-1], nd)}


# =========================================================================== compositor harvest
class TargetFrame:
    """One composed frame on our target: id, presentTime, completedStats.time, the running
    counters, and the composition's own startTime / targetTime (for pickup classes, G1 §6 item 11)."""

    __slots__ = ("id", "present_time", "completed_time", "present_count", "refresh_count", "start_time",
                 "target_time")

    def __init__(self, fid, present_time, completed_time, present_count, refresh_count, start_time=0, target_time=0):
        self.id, self.present_time, self.completed_time = int(fid), int(present_time), int(completed_time)
        self.present_count, self.refresh_count = int(present_count), int(refresh_count)
        self.start_time, self.target_time = int(start_time), int(target_time)


class NativeStatsReader:
    """The compositor statistics through the GIL-keeping exports (G1-1). ``target_key`` is
    (adapter LUID key, VidPnSourceId) of the stage's monitor (``win32.adapter_for_display``)."""

    def __init__(self, target_key=None):
        import ctypes as C
        from . import com, win32
        self.C, self.com, self.W = C, com, win32
        self.target_key = tuple(target_key) if target_key else None
        self._fid = C.c_uint64()
        self._tids = (com.COMPOSITION_TARGET_ID * 8)()
        self._fst = com.COMPOSITION_FRAME_STATS()
        self._ts = com.COMPOSITION_TARGET_STATS()
        self._cnt = C.c_uint()
        self.available = bool(win32.DCompositionGetFrameId_py and win32.DCompositionGetStatistics_py
                              and win32.DCompositionGetTargetStatistics_py)

    def completed_id(self):
        if not self.available:
            return None
        if self.W.DCompositionGetFrameId_py(self.com.COMPOSITION_FRAME_ID_COMPLETED, self.C.byref(self._fid)) != 0:
            return None
        return int(self._fid.value)

    def frame(self, fid):
        """A TargetFrame for our target, False when the id's statistics are gone (unknown), or
        None when the frame did not touch our target."""
        C = self.C
        if self.W.DCompositionGetStatistics_py(fid, C.byref(self._fst), 8, self._tids, C.byref(self._cnt)) != 0:
            return False
        hit = None
        for i in range(min(self._cnt.value, 8)):
            t = self._tids[i]
            if self.target_key is None or (t.displayAdapterLuid.key(), t.vidPnSourceId) == self.target_key:
                hit = t
                break
        if hit is None:
            return None
        if self.W.DCompositionGetTargetStatistics_py(fid, C.byref(hit), C.byref(self._ts)) != 0:
            return False
        ts = self._ts
        return TargetFrame(fid, ts.presentTime, ts.completedStats.time, ts.presentedStats.presentCount,
                           ts.presentedStats.refreshCount, self._fst.startTime, self._fst.targetTime)


class CompositorHarvest:
    """Walks completed frame ids into ``frames`` (our target only) and ``unknown`` id ranges."""

    def __init__(self, reader, max_walk: int = MAX_WALK):
        self.reader = reader
        self.max_walk = max_walk
        self.last_id = None
        self.frames = []
        self.unknown = []
        self.skipped_display_off = 0
        self.harvests = 0

    def start(self):
        self.last_id = self.reader.completed_id()
        self.frames = []
        self.unknown = []

    def harvest(self, display_on: bool = True) -> int:
        """Read every completed id since the last harvest. With the display off nothing is read
        (G1-3): the ids of the gap are skipped and recorded as unknown."""
        cur = self.reader.completed_id()
        if cur is None:
            return 0
        if self.last_id is None:
            self.last_id = cur
            return 0
        start = self.last_id + 1
        if cur < start:
            return 0
        self.harvests += 1
        if not display_on:
            self.unknown.append((start, cur))
            self.skipped_display_off += cur - start + 1
            self.last_id = cur
            return 0
        if cur - start + 1 > self.max_walk:
            self.unknown.append((start, cur - self.max_walk))
            start = cur - self.max_walk + 1
        n = 0
        for fid in range(start, cur + 1):
            r = self.reader.frame(fid)
            if r is False:
                self.unknown.append((fid, fid))
            elif r is not None:
                self.frames.append(r)
                n += 1
        self.last_id = cur
        return n

    def take(self):
        frames, unknown = self.frames, self.unknown
        self.frames, self.unknown = [], []
        return frames, unknown


def _unknown_between(unknown, a, b):
    for lo, hi in unknown:
        if hi > a and lo < b:
            return True
    return False


class ChangeModel:
    """Where a stage episode's committed twins change the picture (S3 of the 2026-09-26 frame-drop
    fixes). §6.1 counts every vblank of an episode as a motion frame, but DWM composes nothing where
    nothing changes (a constant segment causes no recomposition, §4.6.1 MS-1): the heart pop's
    designed 40 ms hold (§4.6.4: "hold 1.5, then at +420 ms"), the switch's 170 -> 190 ms, a delayed
    step. Those vblanks are holds, not missed frames.

    ``batches``: an episode's ``(t1, plain_end, shaped)`` (``animation.Episodes.batches``): every
    committed batch is a change at its t1 (its Commit); its plain legs move from t1 to ``plain_end``;
    each shaped motion moves inside its legs (a step changes at its start). ``changed(t)``: does the
    frame sampled at ``t`` (stage ticks) differ from the one a period earlier? Conservative: a
    retargeted motion keeps its whole span (more motion, never a false hold)."""

    def __init__(self, batches, period):
        import bisect
        self._bisect = bisect
        self.P = float(period)
        spans, steps = [], []
        for t1, plain_end, shaped in batches or ():
            t1 = int(t1)
            steps.append(t1)
            if plain_end is not None and plain_end > t1:
                spans.append((t1, int(plain_end)))
            for f in shaped or ():
                begin, fq = f.begin, f.freq
                for leg in f.legs:
                    s = begin + int(round(leg.start * fq))
                    if leg.dur > 0.0:
                        spans.append((s, begin + int(round((leg.start + leg.dur) * fq))))
                    else:
                        steps.append(s)
        spans.sort()
        merged = []
        for s, e in spans:
            if merged and s <= merged[-1][1]:
                if e > merged[-1][1]:
                    merged[-1][1] = e
            else:
                merged.append([s, e])
        self.starts = [s for s, _e in merged]
        self.ends = [e for _s, e in merged]
        self.steps = sorted(steps)

    def changed(self, t) -> bool:
        lo = t - self.P
        steps = self.steps
        i = self._bisect.bisect_right(steps, lo)
        if i < len(steps) and steps[i] <= t:
            return True                                # a Commit or a step in (t - P, t]
        j = self._bisect.bisect_left(self.starts, t) - 1
        return j >= 0 and self.ends[j] > lo            # a motion inside (t - P, t]


HOLD_EVAL_MAX = 512           # vblanks a ChangeModel evaluates per episode (beyond: counted as motion)


def _sample_time(f):
    return f.target_time or f.completed_time


def episode_from_frames(frames, unknown, t_start, t_end, period, freq, *, rate_hz=None, changes=None):
    """§6.2 frame fields of one stage episode from harvested frames (G1-3 counting).

    G1-3: lost ids are **unknown, never missed**. An interval between two displayed frames whose
    ids bracket an unknown id range is left out of ``interval_ms``, ``interval_P``, ``missed``,
    ``double_missed`` and ``step_max`` (nobody knows what happened inside it) and counted in
    ``unknown_gaps`` instead; the episode's validity (≤ 0.5 % unknown ids) is judged separately.

    With ``changes`` (a ``ChangeModel``; S3) the vblanks the compositor did not present are checked
    against the twins: one where nothing changed is a **hold**. ``holds`` counts them (the whole
    intervals that were holds, and the vblanks, the leading and trailing ones included), and the
    ``*_in_motion`` fields are the §6.3 figures without them: an interval shortened by its hold
    vblanks, ``fps_in_motion`` over the vblanks that had something to show. The raw fields keep
    §6.2's definitions."""
    sel = [f for f in frames if f.present_time and f.completed_time and t_start <= f.completed_time <= t_end]
    sel.sort(key=lambda f: f.id)
    dur_s = max(1e-9, (t_end - t_start) / freq)
    vblanks = (t_end - t_start) / period if period else None
    out = {"method": "dcomp_target_stats", "vblanks": round(vblanks, 1) if vblanks is not None else None,
           "duration_ms": round(dur_s * 1000, 2), "rate_hz": rate_hz}
    if not sel:
        out.update({"frames": 0, "fps": 0.0, "interval_ms": None, "missed": None, "double_missed": None,
                    "unknown": sum(hi - lo + 1 for lo, hi in unknown), "unknown_gaps": 0, "valid": False})
        return out
    origin = sel[0].completed_time
    idx = [int(math.floor((f.completed_time - origin) / period + 0.5)) for f in sel]
    steps, intervals = [], []
    motion = [] if changes is not None else None
    budget = [HOLD_EVAL_MAX]
    hold_intervals = hold_vblanks = 0

    def statics(t_from, n):
        """Hold vblanks among the n samples t_from + k P, k = 1..n (``changes``; a capped count)."""
        count = 0
        for k in range(1, n + 1):
            if budget[0] <= 0:
                break
            budget[0] -= 1
            if not changes.changed(t_from + k * period):
                count += 1
        return count
    gaps = 0
    for i in range(1, len(sel)):
        a, b = sel[i - 1], sel[i]
        if _unknown_between(unknown, a.id, b.id):
            gaps += 1                                  # G1-3: unknown, never missed
            continue
        dt = b.completed_time - a.completed_time
        intervals.append(dt * 1000.0 / freq)
        steps.append(idx[i] - idx[i - 1])
        if motion is not None:
            n = int(math.floor(dt / period + 0.5))
            held = statics(_sample_time(a), n - 1) if n >= 2 else 0
            if n >= 2 and held == n - 1:
                hold_intervals += 1
            hold_vblanks += held
            motion.append((dt - held * period) * 1000.0 / freq)
    if motion is not None:
        first, last = _sample_time(sel[0]), _sample_time(sel[-1])
        lead = int(math.floor((first - t_start) / period + 0.5))
        if lead > 0:                                   # before the first frame: t_start .. first - P
            hold_vblanks += statics(first - (lead + 1) * period, lead)
        tail = int(math.floor((t_end - last) / period + 0.5))
        if tail > 0:
            hold_vblanks += statics(last, tail)
    displayed = len(set(idx))
    counted = sel[-1].present_count - sel[0].present_count + 1 if sel[-1].present_count >= sel[0].present_count \
        else displayed
    ids = sel[-1].id - sel[0].id + 1
    unknown_ids = sum(max(0, min(hi, sel[-1].id) - max(lo, sel[0].id) + 1) for lo, hi in unknown
                      if hi >= sel[0].id and lo <= sel[-1].id)
    share = unknown_ids / max(1, ids)
    P_ms = period * 1000.0 / freq
    out.update({
        "frames": displayed, "frames_by_counter": counted, "fps": round(displayed / dur_s, 2),
        "interval_ms": summary(intervals), "interval_P": summary([x / P_ms for x in intervals], 4),
        "missed": sum(1 for x in intervals if x > 1.5 * P_ms),
        "double_missed": sum(1 for x in intervals if x > 2.5 * P_ms),
        "step_max": max(steps) if steps else None,
        "unknown": unknown_ids, "unknown_gaps": gaps, "unknown_share": round(share, 5),
        "valid": share <= UNKNOWN_MAX_SHARE})
    if motion is not None:
        in_motion_s = max(1e-9, dur_s - hold_vblanks * period / freq)
        out.update({
            "holds": {"intervals": hold_intervals, "vblanks": hold_vblanks,
                      "evaluated": HOLD_EVAL_MAX - budget[0], "capped": budget[0] <= 0},
            "fps_in_motion": round(displayed / in_motion_s, 2),
            "interval_P_in_motion": summary([x / P_ms for x in motion], 4),
            "missed_in_motion": sum(1 for x in motion if x > 1.5 * P_ms),
            "double_missed_in_motion": sum(1 for x in motion if x > 2.5 * P_ms)})
    return out


def judge_stage(ep, rate_hz, work_ms=None, th=STAGE_THRESHOLDS):
    """§6.3's explorer / Up next row. ``ep`` from ``episode_from_frames``. With the hold model's
    fields (S3) the frame checks read the motion figures (§6.3: "displayed frames/s **in
    motion**"); ``basis`` says which were read."""
    if not ep.get("frames") or not rate_hz:
        return {"pass": None, "checks": {}}
    in_motion = ep.get("fps_in_motion") is not None and ep.get("interval_P_in_motion") is not None
    fps = ep["fps_in_motion"] if in_motion else ep["fps"]
    iv = (ep.get("interval_P_in_motion") if in_motion else ep.get("interval_P")) or {}
    checks = {"fps": fps >= th["fps_ratio"] * rate_hz,
              "p95": (iv.get("p95") or 99) <= th["p95_P"],
              "p99": (iv.get("p99") or 99) <= th["p99_P"],
              "max": (iv.get("max") or 99) <= th["max_P"]}
    if work_ms:
        w = summary(work_ms)
        checks["work_p95"] = w["p95"] <= th["work_p95_ms"]
    basis = "in_motion" if in_motion else "raw"
    if ep.get("valid") is False:
        return {"pass": None, "checks": checks, "note": "invalid: too many unknown frame ids", "basis": basis}
    return {"pass": all(checks.values()), "checks": checks, "basis": basis}


# =========================================================================== FrameStats store
class FrameStats:
    """``last``, ``worst`` and ``totals`` per surface and episode kind (§6.2 export).

    ``record`` runs on the frame thread (the stage thread for the stage); ``metrics`` runs on the
    Tk thread for status.json. Both take ``lock``, and ``metrics`` returns deep copies, so the
    exported snapshot is consistent and never shares a dict the frame thread mutates."""

    def __init__(self, log=None, clock=None):
        self.surfaces = {}
        self._log = log
        self._clock = clock
        self._logged = {}
        self.lock = threading.Lock()

    def record(self, surface, kind, ep: dict, verdict: dict | None = None, now_s: float | None = None):
        ep = dict(ep)
        ep["surface"], ep["kind"] = surface, kind
        if verdict is not None:
            ep["pass"] = verdict.get("pass")
            ep["checks"] = verdict.get("checks")
        with self.lock:
            s = self.surfaces.setdefault(surface, {"last": None, "worst": None, "totals": {}})
            s["last"] = ep
            if ep.get("frames") and (s["worst"] is None or self._badness(ep) > self._badness(s["worst"])):
                s["worst"] = ep
            t = s["totals"].setdefault(kind, {"episodes": 0, "frames": 0, "missed": 0, "double_missed": 0,
                                              "failed": 0, "invalid": 0, "missed_in_motion": 0, "hold_vblanks": 0})
            t["episodes"] += 1
            t["frames"] += ep.get("frames") or 0
            t["missed"] += ep.get("missed") or 0
            t["double_missed"] += ep.get("double_missed") or 0
            t["missed_in_motion"] += ep.get("missed_in_motion", ep.get("missed")) or 0
            t["hold_vblanks"] += (ep.get("holds") or {}).get("vblanks") or 0
            if ep.get("pass") is False:
                t["failed"] += 1
            if ep.get("valid") is False:
                t["invalid"] += 1
        if ep.get("pass") is False:
            self._maybe_log(surface, ep, now_s)                 # outside the lock: logging may block
        return ep

    @staticmethod
    def _badness(ep):
        if ep.get("interval_P_in_motion") is not None:            # S3: holds are not missed frames
            iv = ep.get("interval_P_in_motion") or {}
            return ((ep.get("double_missed_in_motion") or 0) * 10 + (ep.get("missed_in_motion") or 0),
                    iv.get("max") or 0.0)
        iv = ep.get("interval_P") or {}
        return ((ep.get("double_missed") or 0) * 10 + (ep.get("missed") or 0), iv.get("max") or 0.0)

    def _maybe_log(self, surface, ep, now_s):
        if self._log is None:
            return
        if now_s is None and self._clock is not None:
            now_s = self._clock()
        last = self._logged.get(surface)
        if now_s is not None and last is not None and now_s - last < LOG_EVERY_S:
            return
        self._logged[surface] = now_s
        try:
            self._log(f"stage: {surface} {ep.get('kind')} missed §6.3: fps {ep.get('fps')}, "
                      f"interval_P {ep.get('interval_P')}, checks {ep.get('checks')}")
        except Exception:
            pass

    def metrics(self):
        """A deep copy of every surface's ``last``, ``worst`` and ``totals`` (any thread)."""
        with self.lock:
            return copy.deepcopy({k: {"last": v["last"], "worst": v["worst"], "totals": v["totals"]}
                                  for k, v in self.surfaces.items()})


# =========================================================================== compositor-clock wait
TICK, HANDLE, TIMEOUT, NO_CLOCK, DISPLAY_OFF = "tick", "handle", "timeout", "no_clock", "display_off"


class ClockWait:
    """P3 with G1-2. ``clock_wait(count, handles, timeout_ms) -> DWORD`` is
    ``DCompositionWaitForCompositorClock`` (or None where the export is missing, Windows < 11);
    ``timer_wait(handles, seconds) -> index | None`` waits one period on a high-resolution
    waitable timer (None = the timer fired, an index = that handle was signalled);
    ``flush()`` is ``DwmFlush`` (fallback 1); ``display_on()`` reports the display state."""

    WAIT_OBJECT_0, WAIT_TIMEOUT = 0x0, 0x102

    def __init__(self, clock_wait, timer_wait, *, flush=None, display_on=lambda: True, period_s=lambda: 1 / 60):
        self.clock_wait = clock_wait
        self.timer_wait = timer_wait
        self.flush = flush
        self.display_on = display_on
        self.period_s = period_s
        self.counts = {TICK: 0, HANDLE: 0, TIMEOUT: 0, NO_CLOCK: 0, DISPLAY_OFF: 0, "fallback_timer": 0,
                       "fallback_flush": 0}
        self.last_code = None

    def wait(self, handles=(), timeout_ms: int = 100):
        """(kind, index): ``(TICK, None)``, ``(HANDLE, i)``, ``(TIMEOUT, None)``,
        ``(NO_CLOCK, None | i)`` after the one-period timer fallback, ``(DISPLAY_OFF, None)``."""
        if not self.display_on():
            self.counts[DISPLAY_OFF] += 1
            return DISPLAY_OFF, None
        n = len(handles)
        if self.clock_wait is not None:
            code = self.clock_wait(n, handles, int(timeout_ms)) & 0xFFFFFFFF
            self.last_code = code
            if code == self.WAIT_OBJECT_0 + n:
                self.counts[TICK] += 1
                return TICK, None
            if self.WAIT_OBJECT_0 <= code < self.WAIT_OBJECT_0 + n:
                self.counts[HANDLE] += 1
                return HANDLE, code - self.WAIT_OBJECT_0
            if code == self.WAIT_TIMEOUT:
                self.counts[TIMEOUT] += 1
                return TIMEOUT, None
            # 0xC01E0006 while the display sleeps, WAIT_FAILED, anything else: no clock (G1-2)
            self.counts[NO_CLOCK] += 1
            if not self.display_on():
                self.counts[DISPLAY_OFF] += 1
                return DISPLAY_OFF, None
            idx = self.timer_wait(handles, self.period_s())
            self.counts["fallback_timer"] += 1
            return NO_CLOCK, idx
        if self.flush is not None:
            self.counts["fallback_flush"] += 1
            hr = self.flush()
            if hr == 0:
                return TICK, None
        self.counts["fallback_timer"] += 1
        idx = self.timer_wait(handles, self.period_s())
        return (TICK, None) if idx is None else (HANDLE, idx)


# =========================================================================== pacer (P2, P4, P5)
class Pacer:
    """Pacing rules for a Python-stepped loop, in ticks of one clock (``freq``)."""

    WINDOW_S = 0.5
    LOCK_AT, UNLOCK_BELOW = 0.8, 0.6

    def __init__(self, freq: int):
        self.freq = int(freq)
        self.cadence = 1
        self.switches = 0
        self.work = []                 # (t, work_ticks)
        self.below_since = None
        self.last_return = None
        self.late_wakes = 0
        self.records = []

    def work_p95(self, now):
        cut = now - self.WINDOW_S * self.freq
        self.work = [w for w in self.work if w[0] >= cut]
        ys = sorted(w[1] for w in self.work)
        return quantile(ys, 0.95) if ys else 0.0

    def target(self, now: int, vblank: int, period: float) -> int:
        """P2: t_target = vblank + n·P ≥ now + work p95 (0.5 s window); under the P5 lock, every
        second vblank and 2 P ahead."""
        est = self.work_p95(now)
        need = now + est
        step = period * self.cadence
        n = math.ceil((need - vblank) / step) if need > vblank else 0
        t = vblank + n * step
        if self.cadence == 2 and t - now < 2 * period:
            t += step
        return int(round(t))

    def judge_wake(self, t_return: int, period: float) -> bool:
        """P4: a wait that returns at least 0.5 P after the previous return is pacing."""
        ok = self.last_return is None or (t_return - self.last_return) >= 0.5 * period
        if not ok:
            self.late_wakes += 1
        self.last_return = t_return
        return ok

    def frame_done(self, t_wake: int, t_target: int, work_ticks: float, period: float, *, present_ticks=0.0,
                   changed=True, keep=False):
        """Record a frame and apply P5's hysteresis. Returns the cadence for the next frame."""
        self.work.append((t_wake, float(work_ticks)))
        p95 = self.work_p95(t_wake)
        if self.cadence == 1 and p95 > self.LOCK_AT * period:
            self.cadence = 2
            self.switches += 1
            self.below_since = None
        elif self.cadence == 2:
            if p95 < self.UNLOCK_BELOW * period:
                if self.below_since is None:
                    self.below_since = t_wake
                elif t_wake - self.below_since >= self.WINDOW_S * self.freq:
                    self.cadence = 1
                    self.switches += 1
                    self.below_since = None
            else:
                self.below_since = None
        if keep:
            self.records.append({"t_wake": t_wake, "t_target": t_target,
                                 "work_ms": work_ticks * 1000.0 / self.freq,
                                 "present_ms": present_ticks * 1000.0 / self.freq,
                                 "changed": bool(changed), "cadence": self.cadence})
        return self.cadence
