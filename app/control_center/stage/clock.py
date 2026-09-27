"""The stage's one clock (DESKTOP_STAGE §0.6) with G1-6 and G1-8 applied.

- **Unit.** Stage ticks are the compositor's ``timeFrequency`` (``GetFrameStatistics``): begin
  times, the twin and the frame statistics all use it. G1-8: always convert through
  ``timeFrequency`` and never hard-code 10 MHz; at device creation ``timeFrequency`` must equal
  ``QueryPerformanceFrequency``, else the begin mode is ``"hold"`` (§4.6.5 item 7: no absolute
  begin time, a leading hold from the predicted commit frame instead).
- **t0.** K3's ``t0`` is ``time.perf_counter()`` seconds. It is converted with an offset
  calibrated once against QPC (CPython reads QPC for perf_counter on Windows; the calibration
  keeps the conversion right even if a runtime adds a reference point), never to the time a
  post arrives (VOC-R25).
- **t1** (§4.6.5 item 1, G1-6): ``nextEstimatedFrameTime``, plus whole periods P while it is
  less than 1.5 ms away. The margin is fixed: no EWMA of wake -> Commit (under GIL holds the
  spike's grew to 14-17 ms). An adaptive margin may use only build CPU time and never exceeds P.
"""
from __future__ import annotations

import math
import time

T1_MARGIN_S = 0.0015
BEGIN_ABSOLUTE, BEGIN_HOLD = "absolute", "hold"


def period_ticks(rate_num: int, rate_den: int, freq: int, fallback_hz: float = 60.0) -> float:
    """P in ticks from a rate (``DCOMPOSITION_FRAME_STATISTICS.rateNum / rateDen``)."""
    if rate_num and rate_den:
        return freq * float(rate_den) / float(rate_num)
    return freq / fallback_hz


def t1_for(next_estimated: int, now: int, period: float, margin_ticks: float) -> int:
    """G1-6: the next estimated frame, pushed by whole periods while it is closer than the
    margin (also when the estimate is stale and already in the past)."""
    t1 = float(next_estimated)
    need = float(now) + margin_ticks
    if period <= 0.0:
        return int(round(max(t1, need)))
    if t1 < need:
        t1 += math.ceil((need - t1) / period) * period
    return int(round(t1))


def adaptive_margin(build_cpu_s: float, period_s: float) -> float:
    """G1-6's only allowed adaptive margin: build CPU time (GIL waits excluded), at least the
    fixed 1.5 ms and never more than one period."""
    return min(max(T1_MARGIN_S, float(build_cpu_s)), max(T1_MARGIN_S, float(period_s)))


def next_frame_after(last_frame: int, now: int, period: float) -> int:
    """The first frame boundary strictly after ``now`` on the grid of ``last_frame`` (the
    predicted commit frame for the hold fallback, §4.6.5 item 7)."""
    if period <= 0.0:
        return int(now)
    k = math.floor((now - last_frame) / period) + 1
    return int(round(last_frame + k * period))


class StageClock:
    """Ticks in the compositor's unit, plus conversions from QPC and from perf_counter."""

    def __init__(self, time_frequency: int, qpf: int, qpc=None, perf=time.perf_counter):
        self.qpf = int(qpf)
        tf = int(time_frequency or 0)
        self.time_frequency = tf
        self.freq = tf if tf > 0 else self.qpf
        self.begin_mode = BEGIN_ABSOLUTE if tf == self.qpf else BEGIN_HOLD      # G1-8
        self._qpc = qpc if qpc is not None else (lambda: int(perf() * self.qpf))
        self._perf = perf
        self.perf_offset_s = self._calibrate()

    def _calibrate(self) -> float:
        best = None
        for _ in range(5):
            a = self._perf()
            q = self._qpc()
            b = self._perf()
            span = b - a
            off = q / self.qpf - 0.5 * (a + b)
            if best is None or span < best[0]:
                best = (span, off)
        off = best[1]
        return 0.0 if abs(off) < 1e-4 else off

    def now(self) -> int:
        q = self._qpc()
        return q if self.freq == self.qpf else int(q * self.freq // self.qpf)

    def ticks(self, seconds: float) -> int:
        return int(round(seconds * self.freq))

    def seconds(self, ticks) -> float:
        return ticks / self.freq

    def from_perf(self, t_perf: float) -> int:
        """Stage ticks of a ``time.perf_counter()`` value (K3's t0)."""
        return int(round((float(t_perf) + self.perf_offset_s) * self.freq))

    def to_perf(self, ticks: int) -> float:
        return ticks / self.freq - self.perf_offset_s

    def ms(self, ticks: float) -> float:
        return ticks * 1000.0 / self.freq

    def uint32_ms(self, ticks: int) -> int:
        """P12: ``int(t_qpc_seconds * 1000) & 0xFFFFFFFF`` for AliveLights."""
        return int(ticks * 1000 // self.freq) & 0xFFFFFFFF
