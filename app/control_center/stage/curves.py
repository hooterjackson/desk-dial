"""CSS cubic-bezier curves as piecewise cubics for IDCompositionAnimation, and the analytic twin.

DESKTOP_STAGE §4.6 (with [G1] G1-4 and G1-7). Pure Python: no ctypes, no Windows calls.

Evaluation model (§4.6.1, MS-2): an animation is a list of segments; ``AddCubic(beginOffset, d,
c, b, a)`` gives ``x(t) = a t^3 + b t^2 + c t + d`` with t in seconds from **that segment's own**
begin offset; ``End(endOffset, endValue)`` holds the final value. A constant segment causes no
recomposition (MS-1), so hold segments are free.

Fit (§4.6.2): cubic Hermite segments in time; at every breakpoint the value and the slope equal
the exact CSS curve (the bezier solved for its parameter), so the fit is C1 and exact at the
breakpoints. The worst segment is split until the error over a dense sample is within the
tolerance (at most 32 segments), each piece as long as the bound allows. Tolerances derive from §4.6.2's bounds: 0.5 physical px of
travel for offsets, 0.5 px of the element's size for scales, 0.002 for opacities, each with a
0.8 margin for the float32 coefficients DWM receives. Deviation WP7a-D1: the breakpoints are
placed greedily (each piece extended by a binary search while its error stays within the bound)
instead of §4.6.2's "start with 8 uniform segments and split", because G1-4 requires the builder
to cut COM calls: a small travel needs 1-3 AddCubic calls instead of 8, and a typical detent about
a quarter fewer than bisection. The bound, the 32-segment cap and the Hermite pieces (the spike's
proven fitter, G1-7) are unchanged; bisection remains as the fallback. Segment
tables are normalised (u and y in [0, 1]) and cached per (curve, tolerance level), so a
retarget only scales them (§4.6.2 last bullet).

Twin (§4.6.3): ``Motion`` holds the same fitted segments DWM runs and the absolute begin time,
so ``value(t)`` is what the compositor samples at t (to float32 rounding of the coefficients).
A retarget at t1 starts the new motion from ``old.value(t1)`` in float64 (G1-7): continuous by
construction. Multi-leg motions (§4.6.4: the end bump, the heart) are one Motion with
constant holds between legs; App A's duration is per leg (S5-31).
"""
from __future__ import annotations

import bisect
import math
import struct
import time

CURVES = {
    "OUT": (0.22, 1.0, 0.36, 1.0),     # §0.4 default
    "IN": (0.4, 0.0, 1.0, 1.0),        # exits
    "SPR": (0.34, 1.45, 0.64, 1.0),    # snap tray, toast scale, the heart (overshoots)
    "EASE": (0.25, 0.1, 0.25, 1.0),    # CSS `ease`, only where App A is silent
    "LINEAR": None,                    # probes and witnesses only
    # r4 (design_handoff_nano_d_r4 README 3.1): SPRING.snap, response 0.36 s, damping 0.72 (k 304.6, c 25.1), as the
    # r3.1 prototype's cssSpring(): the step response over its settle time (416 ms), the last point forced to 1.
    # Used by the Navigator's content swap (M14: M1 timing, in sync with the knob; firmware kSpringLut).
    "SNAP": ("spring", 0.36, 0.72),
}

OFFSET_BOUND_PX = 0.5
SCALE_BOUND_PX = 0.5
OPACITY_BOUND = 0.002
FIT_MARGIN = 0.9
MAX_SEGMENTS = 32
MIN_SEGMENTS = 1
SAMPLES_PER_SEGMENT = 48
LEVEL_MIN, LEVEL_MAX = -40, -4          # tolerance levels 2**level (bucketed down: never looser)

PROPERTY_KINDS = ("offset", "scale", "opacity")


def f32(x: float) -> float:
    """IEEE float32 rounding, as AddCubic's and End's float parameters receive them."""
    return struct.unpack("f", struct.pack("f", x))[0]


class CubicBezier:
    """CSS cubic-bezier(x1, y1, x2, y2) with P0 = (0, 0) and P3 = (1, 1)."""

    __slots__ = ("x1", "y1", "x2", "y2", "ax", "bx", "cx", "ay", "by", "cy")

    def __init__(self, x1: float, y1: float, x2: float, y2: float):
        if not (0.0 <= x1 <= 1.0 and 0.0 <= x2 <= 1.0):
            raise ValueError("CSS cubic-bezier needs x1, x2 in [0, 1]")
        self.x1, self.y1, self.x2, self.y2 = x1, y1, x2, y2
        self.cx = 3.0 * x1
        self.bx = 3.0 * (x2 - x1) - self.cx
        self.ax = 1.0 - self.cx - self.bx
        self.cy = 3.0 * y1
        self.by = 3.0 * (y2 - y1) - self.cy
        self.ay = 1.0 - self.cy - self.by

    def _x(self, s):
        return ((self.ax * s + self.bx) * s + self.cx) * s

    def _y(self, s):
        return ((self.ay * s + self.by) * s + self.cy) * s

    def _dx(self, s):
        return (3.0 * self.ax * s + 2.0 * self.bx) * s + self.cx

    def _dy(self, s):
        return (3.0 * self.ay * s + 2.0 * self.by) * s + self.cy

    def _ddx(self, s):
        return 6.0 * self.ax * s + 2.0 * self.bx

    def _ddy(self, s):
        return 6.0 * self.ay * s + 2.0 * self.by

    def solve(self, u: float) -> float:
        """The bezier parameter s with x(s) = u (x is monotonic for CSS curves)."""
        if u <= 0.0:
            return 0.0
        if u >= 1.0:
            return 1.0
        s = u
        for _ in range(10):
            e = self._x(s) - u
            if abs(e) < 1e-14:
                return s
            d = self._dx(s)
            if abs(d) < 1e-9:
                break
            s2 = s - e / d
            if not (0.0 <= s2 <= 1.0):
                break
            s = s2
        if abs(self._x(s) - u) < 1e-13 and 0.0 <= s <= 1.0:
            return s
        lo, hi = 0.0, 1.0
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if self._x(mid) < u:
                lo = mid
            else:
                hi = mid
            if hi - lo < 1e-16:
                break
        return 0.5 * (lo + hi)

    def value(self, u: float) -> float:
        return self._y(self.solve(u))

    def slope(self, u: float) -> float:
        """dy/du at u (analytic; the second-derivative ratio where x' = y' = 0)."""
        s = self.solve(u)
        dx = self._dx(s)
        if abs(dx) > 1e-7:
            return self._dy(s) / dx
        ddx = self._ddx(s)
        if abs(ddx) > 1e-12:
            return self._ddy(s) / ddx
        h = 1e-6  # pragma: no cover - degenerate curves only
        a, b = max(0.0, u - h), min(1.0, u + h)
        return (self.value(b) - self.value(a)) / (b - a)


class _Linear:
    def value(self, u):
        return min(1.0, max(0.0, u))

    def slope(self, u):
        return 1.0


class Spring:
    """A damped spring's step response x(u) on u in [0, 1] (the settle time), mass 1: k = (2 pi / r)^2,
    c = 4 pi z / r (make_motion.py's SPRINGS; the prototype's cssSpring). value(1) is 1 exactly (a continuous
    linear correction of the <= 0.4 % left at the settle time, so the piecewise fit converges)."""

    __slots__ = ("response", "damping", "w0", "z", "wd", "settle_ms")

    def __init__(self, response: float, damping: float):
        self.response, self.damping = response, damping
        k = (2 * math.pi / response) ** 2
        c = 4 * math.pi * damping / response
        self.w0 = math.sqrt(k)
        self.z = c / (2 * self.w0)
        self.wd = self.w0 * math.sqrt(1 - self.z * self.z) if self.z < 1 else 0.0
        self.settle_ms = self._settle()

    def f(self, ms: float) -> float:
        t = ms / 1000.0
        if t <= 0:
            return 0.0
        if self.z < 1:
            return 1 - math.exp(-self.z * self.w0 * t) * (math.cos(self.wd * t) + (self.z * self.w0 / self.wd) * math.sin(self.wd * t))
        return 1 - math.exp(-self.w0 * t) * (1 + self.w0 * t)

    def _settle(self) -> float:
        for ms in range(40, 1600, 8):
            if all(abs(1 - self.f(ms + j)) <= 0.004 for j in range(0, 121, 8)):
                return float(ms)
        return 1200.0

    def value(self, u: float) -> float:
        """f(u S) plus a linear correction that makes value(1) exactly 1 without a jump (|f(S) - 1| <= 0.004)."""
        u = max(0.0, min(1.0, u))
        return self.f(u * self.settle_ms) + (1.0 - self.f(self.settle_ms)) * u

    def slope(self, u: float) -> float:
        """dy/du (analytic: x'(t) = (w0^2 / wd) e^(-z w0 t) sin(wd t), times the settle time)."""
        t = max(0.0, min(1.0, u)) * self.settle_ms / 1000.0
        if self.z < 1:
            dxdt = (self.w0 * self.w0 / self.wd) * math.exp(-self.z * self.w0 * t) * math.sin(self.wd * t)
        else:
            dxdt = self.w0 * self.w0 * t * math.exp(-self.w0 * t)
        return dxdt * self.settle_ms / 1000.0 + (1.0 - self.f(self.settle_ms))


def curve(name: str):
    spec = CURVES[name]
    if spec is None:
        return _Linear()
    if spec[0] == "spring":
        return Spring(spec[1], spec[2])
    return CubicBezier(*spec)


def _hermite(p0, p1, m0, m1, h):
    """Coefficients of p(w) = A + B w + C w^2 + E w^3 on w in [0, h]."""
    c = (3.0 * (p1 - p0) / h - 2.0 * m0 - m1) / h
    e = (2.0 * (p0 - p1) / h + m0 + m1) / (h * h)
    return (p0, m0, c, e)


def _fit_steps(name: str, tol: float, method: str = "greedy"):
    """The ``SegTable`` fit as a generator: it yields after every trial piece (one Hermite piece
    checked on 48 samples, well under a millisecond) and returns ``(u0, rows, max_err)``.
    ``SegTable`` runs it to the end at once; ``Prewarmer`` resumes it across idle wakes."""
    c = curve(name)
    cache: dict = {}

    def vs(u):
        r = cache.get(u)
        if r is None:
            r = cache[u] = (c.value(u), c.slope(u))
        return r

    def build(a, b):
        (pa, ma), (pb, mb) = vs(a), vs(b)
        h = b - a
        co = _hermite(pa, pb, ma, mb, h)
        err = 0.0
        n = SAMPLES_PER_SEGMENT
        for i in range(1, n):
            w = h * i / n
            v = co[0] + w * (co[1] + w * (co[2] + w * co[3]))
            err = max(err, abs(v - c.value(a + w)))
        return co, err

    segs = {}
    if method == "greedy":
        # Each piece as long as the bound allows (a binary search on its end): about a
        # quarter fewer AddCubic calls than bisection for the same bound (G1-4).
        a = 0.0
        while a < 1.0 and len(segs) < MAX_SEGMENTS:
            co, err = build(a, 1.0)
            yield
            if err <= tol:
                segs[(a, 1.0)] = (co, err)
                break
            lo, hi, best = a, 1.0, None
            for _ in range(24):
                mid = 0.5 * (lo + hi)
                co, err = build(a, mid)
                yield
                if err <= tol:
                    lo, best = mid, (co, err)
                else:
                    hi = mid
            if best is None:
                best, lo = build(a, hi), hi
            segs[(a, lo)] = best
            a = lo
        if not any(k[1] == 1.0 for k in segs):
            segs = {}                                    # over the cap: fall back to bisection
    if not segs:
        edges = [i / MIN_SEGMENTS for i in range(MIN_SEGMENTS + 1)]
        for a, b in zip(edges, edges[1:]):
            segs[(a, b)] = build(a, b)
    while True:
        worst = max(segs, key=lambda k: segs[k][1])
        if segs[worst][1] <= tol or len(segs) >= MAX_SEGMENTS:
            break
        a, b = worst
        m = 0.5 * (a + b)
        del segs[worst]
        segs[(a, m)] = build(a, m)
        segs[(m, b)] = build(m, b)
        yield
    keys = sorted(segs)
    return ([k[0] for k in keys], tuple((k[0],) + tuple(segs[k][0]) for k in keys),
            max(segs[k][1] for k in keys))


def _run(gen):
    while True:
        try:
            next(gen)
        except StopIteration as stop:
            return stop.value


class SegTable:
    """A normalised fit of one curve: y(u) on u in [0, 1], y(0) = 0, y(1) = 1. ``rows`` are
    (u0, a, b, c, e): the piece starting at u0 is a + b w + c w^2 + e w^3 with w = u - u0.
    ``fit`` is a finished ``_fit_steps`` result (the prewarm's resumable build)."""

    __slots__ = ("name", "tol", "u0", "rows", "max_err", "converged", "method")

    def __init__(self, name: str, tol: float, method: str = "greedy", fit=None):
        self.name = name
        self.tol = tol
        self.method = method
        if CURVES[name] is None:
            self.u0 = [0.0]
            self.rows = ((0.0, 0.0, 1.0, 0.0, 0.0),)
            self.max_err = 0.0
            self.converged = True
            return
        if fit is None:
            fit = _run(_fit_steps(name, tol, method))
        self.u0, self.rows, self.max_err = fit
        self.converged = self.max_err <= tol

    def eval(self, u: float) -> float:
        i = bisect.bisect_right(self.u0, u) - 1
        if i < 0:
            i = 0
        u0, a, b, c, e = self.rows[i]
        w = u - u0
        return a + w * (b + w * (c + w * e))

    def __len__(self):
        return len(self.rows)


_TABLES: dict = {}


def level_for(tol_unit: float) -> int:
    tol_unit = max(float(tol_unit), 1e-12)
    return max(LEVEL_MIN, min(LEVEL_MAX, math.floor(math.log2(tol_unit))))


def table(name: str, tol_unit: float) -> SegTable:
    """Cached fit whose error in unit terms is <= tol_unit (bucketed down to a power of two)."""
    key = (name, level_for(tol_unit))
    t = _TABLES.get(key)
    if t is None:
        t = _TABLES[key] = SegTable(name, 2.0 ** key[1])
    return t


PREWARM_NAMES = ("OUT", "IN", "SPR", "EASE", "SNAP")
PREWARM_LEVELS = range(-17, LEVEL_MAX + 1)


def prewarm(names=PREWARM_NAMES, levels=PREWARM_LEVELS) -> int:
    """Build the tables a scene will need before the first detent, all at once (benches, the
    supervised check). About 0.27 s of pure Python for the default set: never on the hot path,
    and never inside a device creation or an open (the stage thread uses ``Prewarmer``)."""
    p = Prewarmer(names, levels)
    while p.step(budget_s=None):
        pass
    return p.built


class Prewarmer:
    """The same warm-up in small steps, for the ``NanoD-stage`` thread's idle wakes from app
    start (WP7a-R4). One table can take up to about 20 ms of pure Python, so the fit itself is
    resumable (``_fit_steps``): ``step`` advances it one trial piece at a time until ``budget_s``
    has passed (at least one piece per call, so it always progresses) and returns True while
    any work is left. Tables already built, e.g. lazily by ``table_for`` between two steps, are
    skipped (or kept) for free. ``budget_s=None`` finishes everything in one call."""

    def __init__(self, names=PREWARM_NAMES, levels=PREWARM_LEVELS, clock=None):
        self.todo = [(name, lv) for name in names for lv in levels]
        self.todo.reverse()
        self.built = 0
        self.steps = 0
        self.clock = clock or time.perf_counter
        self._job = None                 # (key, the running _fit_steps generator)

    @property
    def done(self) -> bool:
        return not self.todo and self._job is None

    def step(self, budget_s: float | None = 0.002) -> bool:
        if self.done:
            return False
        self.steps += 1
        t_end = None if budget_s is None else self.clock() + budget_s
        while True:
            if self._job is None:
                if not self.todo:
                    break
                key = self.todo.pop()
                if key in _TABLES:
                    continue
                if CURVES[key[0]] is None:                       # LINEAR: nothing to fit
                    _TABLES[key] = SegTable(key[0], 2.0 ** key[1])
                    self.built += 1
                    continue
                self._job = (key, _fit_steps(key[0], 2.0 ** key[1]))
            key, gen = self._job
            try:
                next(gen)
            except StopIteration as stop:
                self._job = None
                if key not in _TABLES:
                    _TABLES[key] = SegTable(key[0], 2.0 ** key[1], fit=stop.value)
                    self.built += 1
            if t_end is not None and self.clock() >= t_end:
                break
        return not self.done


_KIND_BOUND = {"offset": OFFSET_BOUND_PX * FIT_MARGIN, "opacity": OPACITY_BOUND * FIT_MARGIN}


def table_for(name: str, kind: str, delta: float, size: float = 1.0) -> SegTable:
    """``table(name, tolerance(kind, delta, size))`` fused for the hot path (one frexp, one dict
    lookup; frexp gives floor(log2(tol)) exactly)."""
    ad = abs(delta)
    if ad < 1e-12:
        ad = 1e-12
    if kind == "scale":
        tol = SCALE_BOUND_PX * FIT_MARGIN / (size if size > 1e-9 else 1e-9) / ad
    else:
        tol = _KIND_BOUND[kind] / ad
    lv = math.frexp(tol)[1] - 1
    if lv < LEVEL_MIN:
        lv = LEVEL_MIN
    elif lv > LEVEL_MAX:
        lv = LEVEL_MAX
    t = _TABLES.get((name, lv))
    if t is None:
        t = _TABLES[(name, lv)] = SegTable(name, 2.0 ** lv)
    return t


def tolerance(kind: str, delta: float, size: float = 1.0) -> float:
    """§4.6.2's bound for a property kind, as a tolerance on the normalised curve."""
    d = max(abs(float(delta)), 1e-12)
    if kind == "offset":
        return OFFSET_BOUND_PX * FIT_MARGIN / d
    if kind == "scale":
        return SCALE_BOUND_PX * FIT_MARGIN / max(float(size), 1e-9) / d
    if kind == "opacity":
        return OPACITY_BOUND * FIT_MARGIN / d
    raise ValueError(f"unknown property kind {kind!r}")


# --------------------------------------------------------------------------- the twin
class Const:
    """A property set with its float setter (no animation bound)."""

    __slots__ = ("v",)
    kind = "const"

    def __init__(self, v: float):
        self.v = float(v)

    def value(self, t_tick) -> float:
        return self.v

    def moving(self, t_tick) -> bool:
        return False

    @property
    def target(self) -> float:
        return self.v

    @property
    def end_tick(self):
        return None


class Leg:
    """One curve leg of a Motion: from ``v0`` to ``v1`` over ``dur`` s, starting ``start`` s
    after the motion's begin. ``dur == 0`` is a **step** (§7.6 / §8.5 "instant" at +190 or +200):
    the value is ``v0`` before ``start`` and ``v1`` from ``start`` on; it needs no table."""

    __slots__ = ("start", "dur", "v0", "v1", "d", "tab")

    def __init__(self, start: float, dur: float, v0: float, v1: float, tab: SegTable | None):
        if dur < 0.0:
            raise ValueError("a leg needs a non-negative duration")
        if dur > 0.0 and tab is None:
            raise ValueError("a curve leg needs a segment table")
        self.start, self.dur = float(start), float(dur)
        self.v0, self.v1 = float(v0), float(v1)
        self.d = self.v1 - self.v0
        self.tab = tab

    @property
    def end(self) -> float:
        return self.start + self.dur


class Motion:
    """What DWM runs for one bound animation: ``v_init`` until the first leg, the legs in order
    with constant holds between them, then the last leg's end value. ``begin`` is an absolute
    tick of the compositor clock (``freq`` = timeFrequency, G1-8)."""

    __slots__ = ("begin", "freq", "legs", "v_init", "v_end", "end_s")
    kind = "motion"

    def __init__(self, begin: int, freq: int, legs):
        if not legs:
            raise ValueError("a motion needs at least one leg")
        prev_end = 0.0
        for leg in legs:
            if leg.start < prev_end - 1e-12:
                raise ValueError("legs overlap")
            prev_end = leg.end
        self.begin = int(begin)
        self.freq = int(freq)
        self.legs = tuple(legs)
        self.v_init = self.legs[0].v0
        self.v_end = self.legs[-1].v1
        self.end_s = self.legs[-1].end

    @property
    def target(self) -> float:
        return self.v_end

    @property
    def start_tick(self) -> int:
        return self.begin + int(round(self.legs[0].start * self.freq))

    @property
    def end_tick(self) -> int:
        return self.begin + int(round(self.end_s * self.freq))

    def value(self, t_tick) -> float:
        tau = (t_tick - self.begin) / self.freq
        legs = self.legs
        if len(legs) == 1:
            leg = legs[0]
            x = tau - leg.start
            if x >= leg.dur and (x > 0.0 or leg.dur == 0.0):      # a step (dur 0) holds v1 from its start
                return leg.v1
            if x <= 0.0:
                return leg.v0
            return leg.v0 + leg.d * leg.tab.eval(x / leg.dur)
        v = self.v_init
        for leg in legs:
            x = tau - leg.start
            if x < 0.0 or (x == 0.0 and leg.dur > 0.0):
                return v
            if x < leg.dur:
                return leg.v0 + leg.d * leg.tab.eval(x / leg.dur)
            v = leg.v1
        return v

    def moving(self, t_tick) -> bool:
        tau = (t_tick - self.begin) / self.freq
        return self.legs[0].start <= tau < self.end_s

    def segments(self, skip: float = 0.0):
        """(segments, end): segments are (beginOffset_s, c0, c1, c2, c3) in AddCubic order
        (constant, linear, quadratic, cubic), end is End's (offset_s, value). With ``skip`` > 0
        the time origin moves ``skip`` s later (the §4.6.5 item 7 fallback for a leg whose
        start has passed): the piece containing it is re-expanded around the new origin.

        A step leg (``dur == 0``) is a constant segment of its end value at its start; a step that
        ends the motion is ``End`` itself. Begin offsets are strictly increasing: a piece that
        starts where the next one starts is dropped (the later one holds from there)."""
        out = []
        first = self.legs[0]
        if first.start > 0.0:
            out.append((0.0, first.v0, 0.0, 0.0, 0.0))
        prev_end = None
        for leg in self.legs:
            if prev_end is not None and leg.start > prev_end + 1e-12:
                out.append((prev_end, leg.v0, 0.0, 0.0, 0.0))
            D, d, v0, st = leg.dur, leg.d, leg.v0, leg.start
            if D <= 0.0:
                out.append((st, leg.v1, 0.0, 0.0, 0.0))
            else:
                k1, k2, k3 = d / D, d / (D * D), d / (D * D * D)
                for (u0, a, b, c, e) in leg.tab.rows:
                    out.append((st + u0 * D, v0 + d * a, k1 * b, k2 * c, k3 * e))
            prev_end = leg.end
        return _shift(_strict(out, self.end_s), self.end_s, self.v_end, skip)


def _strict(out, end_s):
    """Pieces with strictly increasing begin offsets below ``end_s``: a piece that starts where a
    later one starts is superseded by it, and one that starts at ``end_s`` is ``End``'s job."""
    res = []
    for seg in out:
        if seg[0] >= end_s - 1e-12:
            continue
        while res and res[-1][0] >= seg[0] - 1e-12:
            res.pop()
        res.append(seg)
    return res


def step(begin: int, freq: int, at_s: float, v0: float, v1: float) -> Motion:
    """A delayed instant change: ``v0`` until ``at_s`` s after ``begin``, then ``v1`` (a leading
    hold and ``End``; §7.6 "instant | 190", §8.5 "instant | 200")."""
    return Motion(begin, freq, [Leg(at_s, 0.0, v0, v1, None)])


def _shift(out, end_s, v_end, skip):
    """Move the time origin ``skip`` s later: drop the pieces before it and re-expand the one
    containing it around the new origin (a Taylor shift of the cubic)."""
    if skip <= 0.0:
        return out, (end_s, v_end)
    if skip >= end_s:
        return [(0.0, v_end, 0.0, 0.0, 0.0)], (0.0, v_end)
    offs = [s[0] for s in out]
    i = max(0, bisect.bisect_right(offs, skip) - 1)
    o, c0, c1, c2, c3 = out[i]
    s = skip - o
    shifted = [(0.0, c0 + s * (c1 + s * (c2 + s * c3)), c1 + s * (2.0 * c2 + 3.0 * c3 * s), c2 + 3.0 * c3 * s, c3)]
    for seg in out[i + 1:]:
        shifted.append((seg[0] - skip,) + tuple(seg[1:]))
    return shifted, (end_s - skip, v_end)


class Tween:
    """One leg: the common case, a CSS transition (the same protocol as ``Motion``; a Tween is
    its own single leg). Lean on purpose: the builder makes one per retarget (G1-4)."""

    __slots__ = ("begin", "freq", "start", "dur", "v0", "v1", "d", "tab")
    kind = "motion"

    def __init__(self, begin: int, freq: int, start: float, dur: float, v0: float, v1: float, tab: SegTable):
        self.begin = begin
        self.freq = freq
        self.start = start
        self.dur = dur
        self.v0 = v0
        self.v1 = v1
        self.d = v1 - v0
        self.tab = tab

    @property
    def legs(self):
        return (self,)

    @property
    def end(self) -> float:
        return self.start + self.dur

    @property
    def end_s(self) -> float:
        return self.start + self.dur

    @property
    def v_init(self) -> float:
        return self.v0

    @property
    def v_end(self) -> float:
        return self.v1

    @property
    def target(self) -> float:
        return self.v1

    @property
    def start_tick(self) -> int:
        return self.begin + int(round(self.start * self.freq))

    @property
    def end_tick(self) -> int:
        return self.begin + int(round((self.start + self.dur) * self.freq))

    def value(self, t_tick) -> float:
        x = (t_tick - self.begin) / self.freq - self.start
        if x <= 0.0:
            return self.v0
        if x >= self.dur:
            return self.v1
        return self.v0 + self.d * self.tab.eval(x / self.dur)

    def moving(self, t_tick) -> bool:
        x = (t_tick - self.begin) / self.freq - self.start
        return 0.0 <= x < self.dur

    def segments(self, skip: float = 0.0):
        D, d, v0, st = self.dur, self.d, self.v0, self.start
        out = [(0.0, v0, 0.0, 0.0, 0.0)] if st > 0.0 else []
        k1, k2, k3 = d / D, d / (D * D), d / (D * D * D)
        for (u0, a, b, c, e) in self.tab.rows:
            out.append((st + u0 * D, v0 + d * a, k1 * b, k2 * c, k3 * e))
        return _shift(out, st + D, self.v1, skip)


def tween(begin: int, freq: int, v0: float, v1: float, dur: float, curve_name: str = "OUT", delay: float = 0.0,
          kind: str = "offset", size: float = 1.0, tol: float | None = None) -> Tween:
    """One leg from v0 to v1 after ``delay`` s: the common case (a CSS transition)."""
    if dur <= 0.0:
        raise ValueError("a leg needs a positive duration")
    t = tolerance(kind, v1 - v0, size) if tol is None else tol
    return Tween(int(begin), int(freq), float(delay), float(dur), float(v0), float(v1), table(curve_name, t))


def legs_motion(begin: int, freq: int, v0: float, spec, kind: str = "offset", size: float = 1.0) -> Motion:
    """A multi-leg motion from ``spec`` = [(start_s, v_to, dur_s, curve_name), ...], each leg
    starting from the previous leg's end value (the first from ``v0``)."""
    legs = []
    v = float(v0)
    for start, v_to, dur, name in spec:
        legs.append(Leg(start, dur, v, v_to, table(name, tolerance(kind, v_to - v, size))))
        v = float(v_to)
    return Motion(begin, freq, legs)


def eval_segments(segs, end, t: float, emulate_f32: bool = True) -> float:
    """Evaluate emitted segments the way DWM does (coefficients rounded to float32)."""
    end_off, end_val = end
    if t >= end_off:
        return f32(end_val) if emulate_f32 else end_val
    offs = [s[0] for s in segs]
    i = max(0, bisect.bisect_right(offs, t) - 1)
    off, c0, c1, c2, c3 = segs[i]
    if emulate_f32:
        c0, c1, c2, c3 = f32(c0), f32(c1), f32(c2), f32(c3)
    tau = t - off
    return c0 + tau * (c1 + tau * (c2 + tau * c3))


def validate(curve_name: str, dur: float, v0: float, v1: float, kind: str = "offset", size: float = 1.0,
             samples: int = 12000) -> dict:
    """Max |emitted (float32) - exact CSS| over a whole tuple, in value units (H3)."""
    m = tween(0, 10_000_000, v0, v1, dur, curve_name, 0.0, kind, size)
    segs, end = m.segments()
    c = curve(curve_name)
    worst, worst_t = 0.0, 0.0
    for i in range(samples + 1):
        t = dur * i / samples
        exact = v0 + (v1 - v0) * c.value(t / dur)
        err = abs(eval_segments(segs, end, t, True) - exact)
        if err > worst:
            worst, worst_t = err, t
    return {"curve": curve_name, "ms": round(dur * 1000, 3), "kind": kind, "travel": v1 - v0,
            "segments": len(m.legs[0].tab), "max_err": worst, "at_ms": round(worst_t * 1000, 3)}
