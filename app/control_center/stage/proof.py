"""Measurement helpers for supervised proofs on the stage (DESKTOP_STAGE §6.1, §19; G1 report §6
item 11: "reuse the spike's measurement": pickup classes per event, a quiet-baseline gate, and
the pixel witness). Pure functions, unit-tested headlessly; the supervised G1-10 check
(``tools\\stage_checks\\stage_pacing_check.py``) uses them on screen.

- **Pickup** (per event): the first composition that *started* after ``Commit`` returned, and
  its target time relative to t1 in periods: 0 = picked up at t1 (as planned), 1 = at t1 + P
  (continuous, invisible, §4.6.5 item 5), >= 2 = later (a small step at a reversal), < 0 =
  early (the property holds ``old(t1)`` until t1: the G1-6 failure mode).
- **Quiet baseline**: frame statistics are display-wide, so a proof is valid only when the
  static windows (nothing of ours moving) show at most 5 % presents per vblank.
- **Witness**: a 16 px square moving on a known curve is strip-captured; every sample inside a
  judged window must sit within the twin's range over the grab's own time bracket widened by one
  period on each side (± 0.5 px), and at least 95 % must be visible.
"""
from __future__ import annotations

import bisect
import math

QUIET_MAX_RATIO = 0.05
WITNESS_VISIBLE_MIN = 0.95


def pickup_classes(frames, events, period):
    """``frames``: TargetFrames with start/target times; ``events``: dicts with ``t1`` and
    ``done`` (the tick Commit returned). Returns per-event k values (None when unknown) and a
    class count."""
    by_start = sorted((f for f in frames if f.start_time), key=lambda f: f.start_time)
    starts = [f.start_time for f in by_start]
    ks = []
    for ev in events:
        i = bisect.bisect_right(starts, ev["done"])
        if i >= len(by_start):
            ks.append(None)
            continue
        ks.append(int(round((by_start[i].target_time - ev["t1"]) / period)))
    known = [k for k in ks if k is not None]
    return ks, {"events": len(ks), "known": len(known), "early": sum(1 for k in known if k < 0),
                "at_t1": sum(1 for k in known if k == 0), "t1_plus_P": sum(1 for k in known if k == 1),
                "later": sum(1 for k in known if k >= 2)}


def quiet_ratio(frames, windows, period):
    """Presents per vblank over the static ``windows`` [(t0, t1), ...] (ticks)."""
    pres = sorted(f.present_time for f in frames if f.present_time)
    dur = sum(b - a for a, b in windows)
    n = sum(bisect.bisect_right(pres, b) - bisect.bisect_left(pres, a) for a, b in windows)
    vb = dur / period if period else 0.0
    ratio = n / vb if vb else None
    return {"vblanks": round(vb, 1), "presents": n, "ratio": None if ratio is None else round(ratio, 4),
            "quiet": None if ratio is None else ratio <= QUIET_MAX_RATIO}


def run_centroid(row, threshold=200, lo_len=12, hi_len=20):
    """The centre x of the one bright run (a 16 px witness) in a grayscale row, or None."""
    best = None
    start = None
    for x, v in enumerate(list(row) + [0]):
        if v > threshold:
            if start is None:
                start = x
        elif start is not None:
            n = x - start
            if lo_len <= n <= hi_len and (best is None or n > best[1]):
                best = (start, n)
            start = None
    return None if best is None else best[0] + (best[1] - 1) / 2.0


def witness_judge(samples, twin_range, period, tol_px=0.5, windows=None):
    """``samples``: (t_mid, half_span, x_left or None) in ticks and px; ``twin_range(a, b)`` gives
    the twin's (min, max) over [a, b]. Returns counts and the pass flag."""
    n = visible = outside = 0
    worst = 0.0
    for t_mid, half, x in samples:
        if windows is not None and not any(a <= t_mid <= b for a, b in windows):
            continue
        n += 1
        if x is None:
            continue
        visible += 1
        lo, hi = twin_range(t_mid - half - period, t_mid + half + period)
        if x < lo - tol_px or x > hi + tol_px:
            outside += 1
            worst = max(worst, lo - x if x < lo else x - hi)
    share = visible / n if n else None
    return {"samples": n, "visible": visible, "visible_share": None if share is None else round(share, 4),
            "outside": outside, "worst_px": round(worst, 2),
            "pass": bool(n) and share >= WITNESS_VISIBLE_MIN and outside == 0}


def twin_range_fn(history):
    """(min, max) of a property's twin over [a, b] from its history [(from_tick, func), ...]:
    the function in force at t is the last one set at or before t, exact at every change."""
    starts = [h[0] for h in history]
    funcs = [h[1] for h in history]

    def at(t):
        i = bisect.bisect_right(starts, t) - 1
        return funcs[max(0, i)].value(t)

    def rng(a, b, n=9):
        pts = [a + (b - a) * k / (n - 1) for k in range(n)]
        i, j = bisect.bisect_left(starts, a), bisect.bisect_right(starts, b)
        pts += starts[i:j]
        vals = [at(t) for t in pts]
        return min(vals), max(vals)
    return rng


def history_probe(completed_id, frame, delays_ids):
    """P9: for each (label, id) pair, whether the statistics of that frame id are still answered
    (``frame(id)`` is not False). ``completed_id`` is the id read when the probe runs."""
    out = {}
    for label, fid in delays_ids:
        out[label] = {"age_ids": completed_id - fid, "answered": frame(fid) is not False}
    return out


def vblank_steps(frames, t0, t1, period):
    """Vblank-index steps between consecutive displayed frames in [t0, t1] (completedStats.time
    on the grid, G1-3)."""
    sel = sorted((f for f in frames if f.present_time and t0 <= f.completed_time <= t1), key=lambda f: f.id)
    if not sel:
        return []
    o = sel[0].completed_time
    idx = [int(math.floor((f.completed_time - o) / period + 0.5)) for f in sel]
    return [b - a for a, b in zip(idx, idx[1:])]
