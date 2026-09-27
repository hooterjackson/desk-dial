"""The per-event animation builder (DESKTOP_STAGE §4.6.4-§4.6.7 with G1-4, G1-6, G1-7, G1-8).

One ``Batch`` per event (a detent, an open, a data patch): every property change of the event
goes into **one** ``Commit`` (§4.6.5 item 5). The batch is opened at the event's wake with
``t1`` (``Stage.t1()``: ``nextEstimatedFrameTime`` plus P while under 1.5 ms away, G1-6) and:

- ``to(prop, target, ms, curve)`` is a CSS transition: it retargets from the twin's value at t1
  (float64, from the same fitted segments DWM runs, G1-7), over the full duration, beginning at
  t1. A target equal to the current target changes nothing (0 calls, G1-4).
- ``to(..., anchor=t0_ticks, delay_ms=190)`` anchors a leg to K3's ``t0`` (§2.3, VOC-R25): a
  future start becomes a leading hold (a constant segment, free for DWM, §4.6.4); a start
  already passed begins at t1 at the value the curve has there.
- ``to(..., ms=0)`` is a **step** (§7.6 "Dots and marker | instant | 190", the state change's
  "instant | 190", §8.5 "hints | instant | 200"): with a future start it is one animation of a
  leading hold at the current value and ``End(start, target)`` (2 segments, no curve); a start
  already reached is a ``jump``.
- ``legs(prop, spec)`` is a multi-leg motion in one animation (§4.6.4: the end bump, the heart);
  a leg with ``dur_ms`` 0 is a step inside it.
- ``jump(prop, v)`` sets a value with the float setter (1 call per bound setter): for elements
  that are invisible or under reduced motion, instead of a 10-call animation (G1-4).
  ``jump(prop, v, anchor=t0, delay_ms=190)`` is the same step scheduled for later.
- Pooled objects only (``tree.Prop`` owns two animation objects, used alternately, so a bound
  animation is never modified: §4.6.5 item 4, G1-7).

Begin mode (G1-8): ``absolute`` sets ``SetAbsoluteBeginTime`` in timeFrequency ticks; ``hold``
(timeFrequency != QPF) sets none and gives the animation a leading hold measured from the
predicted commit frame (§4.6.5 item 7), re-expanding the curve when the start has passed.

Every hot call keeps the GIL (PYFUNCTYPE setters, G1-5); ``commit()`` is the batch's first
GIL-releasing call. HRESULTs are OR-accumulated per program and checked once: a failure raises
``com.ComError`` (or ``DeviceLost``) and the engine checks the device state (§4.3).

For the episode's hold model (S3 of the 2026-09-26 frame-drop fixes, ``frames.ChangeModel``) a
batch also keeps where its motions change the picture, at no cost to the detent's plain legs:
``plain_end`` is the latest end of the legs that start at their batch's t1 (one span from t1), and
``shaped`` lists the motions with a leading hold, several legs or a step (their exact spans).
``carried``: the uploads its Commit carried (the engine's count; S1 keeps it 0 for input batches).
"""
from __future__ import annotations

import time

from . import clock as CK
from . import com
from . import curves as CV

EPS = 1e-9
COMMIT_LOG_MS = 2.0       # a Commit over 2 ms is logged, rate-limited (§4.6.7, AR-16)


class Batch:
    """One event's changes. ``stage`` supplies ``device``, ``clock``, ``period`` and an episode
    tracker (``note_motion``); see ``engine.StageCore``."""

    __slots__ = ("stage", "dev", "t1", "freq", "mode", "f_commit", "calls", "anims", "jumps", "skipped",
                 "max_end", "t_wake", "t_built", "t_done", "committed", "_hr", "_fr", "_fb", "_fc", "_fe",
                 "commit_ms", "plain_end", "shaped", "carried")

    def __init__(self, stage, t1: int, *, t_wake: float | None = None, predicted_commit: int | None = None):
        self.stage = stage
        self.dev = stage.device
        self.t1 = int(t1)
        self.freq = stage.clock.freq
        self.mode = stage.clock.begin_mode
        self.f_commit = int(predicted_commit if predicted_commit is not None else t1)
        self.calls = 0
        self.anims = 0
        self.jumps = 0
        self.skipped = 0
        self.max_end = None
        self.t_wake = time.perf_counter() if t_wake is None else t_wake
        self.t_built = self.t_done = None
        self.committed = False
        self.commit_ms = None
        self.plain_end = None
        self.shaped = None
        self.carried = 0
        self._hr = 0
        fns = stage.animation_fns()
        self._fr, self._fb, self._fc, self._fe = fns

    # ------------------------------------------------------------------ changes
    def to(self, prop, target: float, ms: float, curve: str = "OUT", *, delay_ms: float = 0.0,
           anchor: int | None = None, v_from: float | None = None, force: bool = False) -> int:
        target = float(target)
        func = prop.func
        if not force and v_from is None and abs(target - func.target) <= EPS:
            self.skipped += 1
            return 0
        t1 = self.t1
        freq = self.freq
        start = t1 if anchor is None else int(anchor)
        if delay_ms:
            start += int(round(delay_ms * freq / 1000.0))
        v0 = func.value(t1) if v_from is None else float(v_from)
        if ms <= 0.0:
            return self._step(prop, start, v0, target)
        dur = ms / 1000.0
        tab = CV.table_for(curve, prop.kind, target - v0, prop.size)
        if self.mode != CK.BEGIN_ABSOLUTE:
            begin, lead, skip = self._place(start)
            return self._program(prop, CV.Tween(begin, freq, lead, dur, v0, target, tab), skip)
        # the hot path: absolute begin times, one leg, segments emitted straight into AddCubic
        if start >= t1:
            begin, lead = t1, (start - t1) / freq
        else:
            begin, lead = start, 0.0
        motion = CV.Tween(begin, freq, lead, dur, v0, target, tab)
        end = begin + int(round((lead + dur) * freq))
        if end <= t1:
            return self.jump(prop, target)
        a = prop.take_animation()
        fc = self._fc
        hr = self._fr(a) | self._fb(a, begin)
        n = 3
        if lead > 0.0:
            hr |= fc(a, 0.0, v0, 0.0, 0.0, 0.0)
            n += 1
        d = target - v0
        k1 = d / dur
        k2 = k1 / dur
        k3 = k2 / dur
        rows = tab.rows
        for u0, ca, cb, cc, ce in rows:
            hr |= fc(a, lead + u0 * dur, v0 + d * ca, k1 * cb, k2 * cc, k3 * ce)
        hr |= self._fe(a, lead + dur, target)
        for fn, ptr in prop.fbind:
            hr |= fn(ptr, a)
        n += len(rows) + len(prop.fbind)
        if hr < 0:
            self._hr |= hr
        prop.func = motion
        if self.max_end is None or end > self.max_end:
            self.max_end = end
        if lead > 0.0:                                  # a leading hold: its exact span (S3)
            if self.shaped is None:
                self.shaped = [motion]
            else:
                self.shaped.append(motion)
        elif self.plain_end is None or end > self.plain_end:
            self.plain_end = end
        self.calls += n
        self.anims += 1
        return n

    def legs(self, prop, spec, *, anchor: int | None = None, v_from: float | None = None) -> int:
        """``spec`` = [(start_ms, v_to, dur_ms, curve), ...] relative to the anchor (default t1);
        each leg starts from the previous leg's end value, the first from ``v_from`` or the
        twin's value at t1."""
        start = self.t1 if anchor is None else int(anchor)
        v = prop.func.value(self.t1) if v_from is None else float(v_from)
        first = start + int(round(spec[0][0] * self.freq / 1000.0))
        begin, lead, skip = self._place(first)
        base = spec[0][0]
        legs = []
        for st, v_to, dur, name in spec:
            dur = max(0.0, float(dur))
            tab = CV.table_for(name, prop.kind, v_to - v, prop.size) if dur > 0.0 else None
            legs.append(CV.Leg(lead + (st - base) / 1000.0, dur / 1000.0, v, v_to, tab))
            v = float(v_to)
        return self._program(prop, CV.Motion(begin, self.freq, legs), skip)

    def _step(self, prop, start: int, v0: float, target: float) -> int:
        """A delayed instant change: hold ``v0`` from the batch's begin, ``target`` from
        ``start``. A start at or before t1 (the first frame that can show this batch) is a jump:
        the float setter lands with the Commit, in either begin mode."""
        if start <= self.t1:
            return self.jump(prop, target)
        begin, lead, skip = self._place(start)
        return self._program(prop, CV.step(begin, self.freq, lead, v0, target), skip)

    def jump(self, prop, value: float, *, anchor: int | None = None, delay_ms: float = 0.0) -> int:
        """Set ``value`` now with the float setter; with ``anchor`` / ``delay_ms`` the same
        instant change is scheduled for ``anchor + delay_ms`` (a step, see ``to``)."""
        if anchor is not None or delay_ms:
            return self.to(prop, value, 0.0, anchor=anchor, delay_ms=delay_ms)
        value = float(value)
        f = prop.func
        if f.kind == "const" and abs(f.v - value) <= EPS:
            self.skipped += 1
            return 0
        hr = 0
        for fn, ptr in prop.fset:
            hr |= fn(ptr, value)
        if hr < 0:
            self._hr |= hr
        prop.func = CV.Const(value)
        self.calls += len(prop.fset)
        self.jumps += 1
        return len(prop.fset)

    def call(self, fn, ptr, *args) -> int:
        """Any other hot setter in this batch (content swap, reorder helpers)."""
        hr = fn(ptr, *args)
        if hr is not None and hr < 0:
            self._hr |= hr
        self.calls += 1
        return 1

    # ------------------------------------------------------------------ internals
    def _place(self, start: int):
        """(motion begin tick, leading hold s, skip s) for a start tick, per begin mode."""
        if self.mode == CK.BEGIN_ABSOLUTE:
            ref = self.t1
            if start >= ref:
                return ref, (start - ref) / self.freq, 0.0
            return start, 0.0, 0.0
        ref = self.f_commit
        if start >= ref:
            return ref, (start - ref) / self.freq, 0.0
        return start, 0.0, (ref - start) / self.freq

    def _program(self, prop, motion, skip: float) -> int:
        ref = self.t1 if self.mode == CK.BEGIN_ABSOLUTE else self.f_commit
        if motion.end_tick <= ref:
            return self.jump(prop, motion.v_end)            # already finished when DWM first samples it
        a = prop.take_animation()
        segs, (eo, ev) = motion.segments(skip)
        hr = self._fr(a)
        n = 1
        if self.mode == CK.BEGIN_ABSOLUTE:
            hr |= self._fb(a, motion.begin)
            n += 1
        fc = self._fc
        for off, c0, c1, c2, c3 in segs:
            hr |= fc(a, off, c0, c1, c2, c3)
        hr |= self._fe(a, eo, ev)
        n += len(segs) + 1
        for fn, ptr in prop.fbind:
            hr |= fn(ptr, a)
        n += len(prop.fbind)
        if hr < 0:
            self._hr |= hr
        prop.func = motion
        end = motion.end_tick
        if self.max_end is None or end > self.max_end:
            self.max_end = end
        if self.shaped is None:                         # legs, steps, the hold fallback: exact spans (S3)
            self.shaped = [motion]
        else:
            self.shaped.append(motion)
        self.calls += n
        self.anims += 1
        return n

    # ------------------------------------------------------------------ commit
    def commit(self) -> None:
        """Check the accumulated HRESULTs, then the batch's one Commit (GIL-releasing)."""
        self.t_built = time.perf_counter()
        if self._hr < 0:
            com.check(self._hr, "batch")
        self.stage.commit(self)
        self.t_done = time.perf_counter()
        self.commit_ms = (self.t_done - self.t_built) * 1000.0
        self.committed = True

    @property
    def work_ms(self) -> float | None:
        """Wake -> Commit returned (§6.2 ``work_ms`` for the stage; under GIL contention a
        timestamp taken after the GIL returns overstates it, G1-5)."""
        return None if self.t_done is None else (self.t_done - self.t_wake) * 1000.0


class Episodes:
    """The episode tracker (§6.2 "per episode"; §4.6.7): an episode runs from a motion's start
    to the twin's end. It boosts the compositor clock at the start and unboosts after the last
    animation ends (the engine wakes at ``end`` + P for that, a clean-up wake)."""

    def __init__(self):
        self.active = False
        self.kind = None
        self.start = None
        self.end = None
        self.events = 0
        self.work_ms = []
        self.calls = []
        self.batches = []             # (t1, plain_end, shaped) per committed batch: frames.ChangeModel (S3)
        self.boosted = False

    def note(self, batch: Batch, kind: str) -> bool:
        """Record a committed batch; True when it starts a new episode."""
        started = False
        if batch.max_end is not None:
            if not self.active:
                self.active, self.kind, self.start, self.end = True, kind, batch.t1, batch.max_end
                self.events, self.work_ms, self.calls, self.batches = 0, [], [], []
                started = True
            else:
                self.end = max(self.end, batch.max_end)
        if self.active:
            self.events += 1
            if batch.work_ms is not None:
                self.work_ms.append(batch.work_ms)
            self.calls.append(batch.calls)
            self.batches.append((batch.t1, getattr(batch, "plain_end", batch.max_end), getattr(batch, "shaped", None)))
        return started

    def due_end(self, now: int, period: float) -> bool:
        return self.active and now >= self.end + period

    def finish(self):
        rec = {"kind": self.kind, "start": self.start, "end": self.end, "events": self.events,
               "work_ms": list(self.work_ms), "calls": list(self.calls), "boosted": self.boosted,
               "batches": self.batches}
        self.active = False
        self.kind = self.start = self.end = None
        self.batches = []
        return rec
