"""S1 tour W and the S3 snap checks for the picker v2 (DESKTOP_STAGE §6.4 W, §6.5 S3; CAROUSEL.md §12).

WP7b WROTE THIS SCRIPT BUT NEVER RAN IT ON SCREEN. The on-screen run shows the picker full-screen on
the user's monitor for about a minute and MOVES WINDOWS (its own test windows, plus any real window
named with --real-hwnd): run it only from the main session, with the user's explicit go-ahead, the
user at the PC:

    cd app
    .venv\\Scripts\\python.exe -I ..\\..\\tools\\stage_checks\\picker_snap_checks.py --run --i-have-go-ahead [--stress] [--no-s3] [--chrome gpu|cpu|both] [--real-hwnd 0x1234 ...]

S3 needs two real windows the helper cannot make (K4 §6.5 S3 lists UWP and elevated): pass a UWP
window (class ``ApplicationFrameWindow``: Settings, Calculator) and an elevated one (an
administrator terminal) with ``--real-hwnd``. The script classifies every --real-hwnd by its class
and integrity level (``uwp``, ``elevated``, ``real``) and the S3 verdict names each required kind
that did not run as ``not covered``: a run without them is never reported as a complete S3.

``--dry-run`` (headless: no window, no Win32 window call) drives the same tour scripts through the
presenter on the tests' fake backend, fake capture and a fake NanoD-snap on a fake clock, and checks
the event flow (every snap resolved by t0 + 800, the pair close at 820, the one-side completion,
the latched Back on a stalled snap). ``--run`` first runs the dry run, then one on-screen child,
which is killed at 150 s whatever happens.

What runs on screen: the production presenter (``carousel.CarouselPresenter``: NanoD-carousel,
NanoD-capture, NanoD-label, NanoD-snap, the real frost) driven by a small stand-in of K3's snap
rules (auto-advance at t0 + 420 unless turned, the pair close at t0 + 820 focusing the side snapped
last, U12's one-side completion on Back, the latched Back while a snap is in flight) and the
adapter's close order (raise the first side, focus the last, then the exit). No Tk, no controller,
no knob, no serial port, no companion; the running companion is left alone (the foreground grant
uses its own hotkey, F23 or F22, never F24).

Test windows: a helper process of ours (``--child-targets``) makes 10 plain windows on the monitor
under the mouse: 6 normal (the first is the origin), 1 maximized, 1 minimized, 1 DPI-unaware (its
own thread, for the mixed-DPI path) and 1 **busy target** whose thread stops pumping for 2 s when the
check signals it right after the pre-check. They are closed at the end.

- **Tour W** (§6.4), once Frosted and once No background: 20 detents at 10/s and 20 at 20/s; snap
  left, the auto-advance, snap right (the pair close); reopen, one snap, then Back (the one-side
  completion). ``--stress`` adds §6.4's GIL burst thread (10 ms of pure Python every 25 ms).
- **S3** (§6.5): a normal, the maximized, the minimized and the DPI-unaware window (plus every
  --real-hwnd) are each snapped left and the origin completed right: the result, flush edges
  (DWMWA_EXTENDED_FRAME_BOUNDS within 2 px of the rcWork half), the foreground kept on the picker
  from the snap to its result. A UWP window takes the 400 ms verify path and must end ``ok`` and
  flush; an elevated window must be refused at the integrity pre-check (``move_rejected``, no
  ``accepted``, not moved, no completion of the origin). ``S3.coverage`` records each required kind
  (maximized, minimized, UWP, elevated, mixed DPI) as covered, failed or ``not covered``. The pair close of tour W is checked for both halves above the
  origin in z-order. The busy target: snap, stall it, keep turning, Back (latched): the snap must
  resolve ``move_rejected`` by t0 + 800 (observed <= 850 ms), the picker must close, frames must
  keep coming during the stall, and the busy window must never become the foreground.

Recorded in ``diagnostics\\picker-snap-checks-<stamp>.json``: ``presenter.metrics()`` before and
after each pass (FrameStats for the picker and toasts, the pacer), the verdicts of K4 §6.3's
"Picker (W), step 1" row (fps >= 118 under the 120 lock, >= 110 in the stress run, interval
p95 <= 2.02 P, max <= 3 P, no gap >= 16 ms; the per-frame **compose + present** p95 over the pass's
episode frames <= 5.6 ms on 16:9 / <= 7.0 ms on 32:9, §22 Q2, from the pooled histograms of the two
metrics reads; the carousel thread's CPU <= 70 % of one core, from GetThreadTimes over the pass's
episodes), and every S3 item.
Window titles are never read or recorded (our windows' names are ours; real windows by handle only).

**Step 3, the chrome on the GPU (lead ruling R-h; CAROUSEL.md §12.4; K4 §6.3 "Picker (W), step 3").**
``--chrome gpu`` (the default) runs the picker with its DirectComposition chrome (the stage package's
``picker_chrome``, as the wiring point installs it); ``--chrome cpu`` the step-1 chrome; ``--chrome both``
adds a CPU pass of tour W (Frosted) after the GPU ones, for a side-by-side record (add ``--no-s3`` to
stay inside the 120 s kill). For the GPU chrome each tour W pass also records:
- **Displayed frames on screen**: the compositor's target statistics for the picker's monitor,
  harvested every 250 ms on a thread of this process (GIL-keeping reads, G1-1; counted by the target's
  present counter and put on the vblank grid, G1-3), matched to the pass's picker episodes (the
  presenter's ``frames.picker.recent``): fps, interval p50/p95/p99/max, frames missed.
  ``displayed_episodes`` keeps **every** episode (T1 of the 2026-09-26 frame-drop diagnosis), each
  with its missed intervals placed (ms from its start to the frame after the gap, the gap in P), not
  only the worst; ``--dry-run`` checks that on synthetic frames. The pacer's ``oneoff_frames`` counts
  the frames P1 keeps out of P2 and P5 (an open's setup, the frost's upload).
  Each episode also carries its **attribution** (the review of the frame-drop fixes, 2026-09-26: the
  morning's worst displayed episodes were snaps at 2 P, pointing to the P5 120 lock rather than to
  the thumbnails' re-registration, which stays on animated frames until a re-run settles it): the
  presenter's ``recent`` entry says how many presents ran at cadence 2 and when the thumbnails were
  re-registered, and ``attribute_gaps`` names the lock, the re-registration or neither.
- **The chrome's pickup**: every chrome Commit's t1 against the first composition that started after
  it returned (``stage.proof.pickup_classes``): at t1, t1 + P, later, early.
- The step-3 row: displayed fps >= 235 (>= 228 in the stress run), interval p95 <= 1.1 P, p99 <=
  2.02 P (max <= 3 P under stress); the per-frame Python work <= 1.5 ms p95 on normal frames and
  <= 3.0 ms p95 on detent frames (the pooled ``normal_ms`` / ``detent_ms`` histograms, R-h's target
  and §6.3); the carousel thread's CPU <= 35 % of one core.
- **AR-12's alignment witness** (one extra pass: 12 detents at 4/s on the Frosted background): a
  1-px row through the middle of the cards is BitBlt-captured every ~2 ms (the picker's own windows
  only, after its frost capture; nothing else is recorded); in each row the selection frame's white
  sides (chrome, compositor-run) and the centre card's thumbnail edges (the solid colour of our test
  window) are found, and the offset between their centres is the misalignment. While the cards move,
  offset / (speed x P) is the thumbnails' lag in frames: the verdict passes with a median |lag| under
  half a frame and a p95 offset within 6 px; otherwise it recommends ``NANOD_PICKER_THUMB_LEAD`` (the
  thumbnails then sample that many periods ahead). ``--dry-run`` checks the analysis on synthetic
  rows.
- **A knob touch right before the press** (review finding WP7c-R6): the first open of each tour W pass
  posts ``note_touch()`` 2 ms before ``show()``. In the child's first pass the chrome's device is cold,
  so its worker makes the process's first D3D11 device (about 130 ms) while ``show()`` waits for its
  handshake. ``touch_then_show`` records each such open's ``show_ms`` and passes when every one is
  under the 150 ms bound with the GPU chrome drawing the pass.

Safety: a native thread-pool timer whose callback is ``TerminateProcess`` kills the child at 120 s
even with the GIL held; the runner kills it (and the helper) at 150 s; **Ctrl+Alt+F12** hides the
picker at once and ends the run. The script refuses to show anything while the display sleeps or
the session is locked. Real windows named with --real-hwnd are put back at the end with posted,
non-activating calls; a formerly maximized one is left restored (S5-32) and reported.
"""
from __future__ import annotations

import argparse
import ctypes as C
import ctypes.wintypes as WT
import datetime
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
RUNNER_KILL_S = 150.0
TARGETS_LIFETIME_S = 160.0
ABORT_ID, GRANT_ID = 0x5043, 0x5044
MOD_CONTROL, MOD_ALT, MOD_NOREPEAT = 0x2, 0x1, 0x4000
VK_F12, VK_F22, VK_F23 = 0x7B, 0x85, 0x86
WM_HOTKEY = 0x0312
MATCH_PX = 2
SNAP_DEADLINE_S = 0.800
PAIR_CLOSE_S = 0.820
ADVANCE_S = 0.420
BUSY_STALL_S = 2.0
PAIR_TEXT = "Side by side · {a} and {b}"          # VOC toast.snap.pair (A = left, B = right)
ONE_SIDE_TEXT = "{a} left · {b} right"               # VOC toast.snap.one_side (after a completed Back)
CPU_GATE_PCT = 70.0                                  # K4 §6.3 "Picker (W), step 1": carousel thread
STEP3 = {"fps": 235.0, "fps_stress": 228.0, "p95_P": 1.1, "p99_P": 2.02, "max_P_stress": 3.0,
         "normal_ms": 1.5, "detent_ms": 3.0, "cpu_pct": 35.0}  # K4 §6.3 "Picker (W), step 3"; R-h
HARVEST_S = 0.250
WITNESS_S = 0.002
TARGET_COLOURS = (0x3060C0, 0x40A040, 0xC06030, 0x8040A0, 0x20A0A0, 0xA0A020, 0x606060, 0x2040E0, 0xE04080,
                  0x40E0C0)                          # the helper's windows (COLORREF 0x00BBGGRR)
S3_REQUIRED = ("maximized", "minimized", "uwp", "elevated", "mixed_dpi")
UWP_FRAME_CLASS = "ApplicationFrameWindow"


# =========================================================================== K3's snap rules (stand-in)
class MiniRuntime:
    """The part of K3 §5.7 the tours need, on the driver's clock: sides assigned on ``accepted``,
    the auto-advance at t0 + 420 to the next unassigned window after the snapped one (wrapping)
    unless a detent arrived since t0, the pair close at t0 + 820 (raise the side snapped first,
    focus the side snapped last, the pair exit, the exit toast), Back latched while a snap is in
    flight, and U12: Back with exactly one side assigned completes the origin on the other half."""

    def __init__(self, driver, items, origin_index):
        self.d = driver
        self.items = items
        self.origin_index = origin_index
        self.index = 0
        self.sides = {"left": None, "right": None}
        self.order = []                    # sides in the order they were accepted
        self.busy = None                   # {"index", "side", "t0"}
        self.latched = None
        self.advance_due = None
        self.pair_due = None
        self.last_detent = -1.0
        self.open = False
        self.log = []                      # (t, what, detail) - no titles
        self.snaps = []                    # one record per snap
        self.cancel = None                 # the pending one-side completion
        self.closed_by = None

    # ---------------------------------------------------------- inputs
    def detent(self, index, bump=0):
        self.index = max(0, min(len(self.items) - 1, index))
        self.last_detent = self.d.now()
        self.d.highlight(self.index, bump)

    def snap(self, side, index=None):
        index = self.index if index is None else index
        if self.busy is not None or not self.open:
            self.log.append((self.d.now(), "snap_ignored", side))
            return None
        if self.sides[side] == index:
            return None                    # same side again: a no-op
        t0 = self.d.now()
        self.busy = {"index": index, "side": side, "t0": t0}
        record = {"side": side, "index": index, "kind": self.items[index].get("_kind"), "t0": t0,
                  "accepted_ms": None, "result": None, "result_ms": None}
        self.snaps.append(record)
        item = self.items[index]
        self.d.snap({"t0": t0, "index": index, "side": side, "target_rect": self.d.half_rect(side),
                     "place_at_ms": 360, "item": {k: item[k] for k in ("id", "hwnd", "pid", "class_name", "exstyle")
                                                  if k in item}})
        return record

    def back(self):
        if not self.open:
            return
        if self.busy is not None:
            self.latched = "back"
            self.log.append((self.d.now(), "latched", "back"))
            return
        self._close_back()

    # ---------------------------------------------------------- events and timers
    def on_event(self, kind, payload, now):
        if kind == "snap_result" and self.busy is not None:
            side, outcome = payload
            record = self.snaps[-1]
            if outcome == "accepted":
                record["accepted_ms"] = round((now - record["t0"]) * 1000, 1)
                index = self.busy["index"]
                other = "right" if side == "left" else "left"
                if self.sides[other] == index:
                    self.sides[other] = None
                    self.order = [s for s in self.order if s != other]
                self.sides[side] = index
                self.order = [s for s in self.order if s != side] + [side]
                if self.sides["left"] is not None and self.sides["right"] is not None:
                    self.pair_due = self.busy["t0"] + PAIR_CLOSE_S
                else:
                    self.advance_due = self.busy["t0"] + ADVANCE_S
                return
            record["result"] = outcome
            record["result_ms"] = round((now - record["t0"]) * 1000, 1)
            if outcome != "ok":
                if self.sides.get(side) == self.busy["index"]:
                    self.sides[side] = None
                    self.order = [s for s in self.order if s != side]
                self.pair_due = None
            self.busy = None
            if self.latched and self.pair_due is None:
                self.latched = None
                self._close_back()
        elif kind == "complete_result" and self.cancel is not None:
            _job, completed = payload
            self.cancel["completed"] = bool(completed)
            self.cancel["ms"] = round((now - self.cancel["t"]) * 1000, 1)
            self._finish_back(bool(completed))

    def tick(self, now):
        if self.advance_due is not None and now >= self.advance_due:
            t0 = self.advance_due - ADVANCE_S
            self.advance_due = None
            if self.last_detent < t0 and self.open:
                snapped = self.snaps[-1]["index"] if self.snaps else self.index
                n = len(self.items)
                for step in range(1, n + 1):
                    j = (snapped + step) % n
                    if j not in self.sides.values():
                        self.index = j
                        self.d.highlight(j, 0)
                        break
        if self.pair_due is not None and now >= self.pair_due and self.busy is None:
            self.pair_due = None
            self._close_pair()

    # ---------------------------------------------------------- closes (the adapter's order)
    def _close_pair(self):
        first, last = self.order[0], self.order[-1]
        a, b = self.items[self.sides["left"]], self.items[self.sides["right"]]
        self.d.raise_window(self.items[self.sides[first]]["hwnd"])
        self.d.focus(self.items[self.sides[last]]["hwnd"])
        self.d.exit("pair")
        self.open = False
        self.closed_by = "pair"
        self.d.toast(PAIR_TEXT.format(a=a["app"], b=b["app"]), exit=True)
        self.log.append((self.d.now(), "pair_close", {"first": first, "last": last}))

    def _close_back(self):
        assigned = [s for s, i in self.sides.items() if i is not None]
        origin = self.items[self.origin_index]
        if len(assigned) == 1 and self.sides[assigned[0]] != self.origin_index:
            side = "right" if assigned[0] == "left" else "left"
            job = self.d.complete_one_side(origin, side)
            self.cancel = {"job": job, "side": side, "t": self.d.now(), "completed": None, "ms": None}
            self.log.append((self.d.now(), "complete_one_side", side))
            return
        self._finish_back(False)

    def _finish_back(self, completed):
        origin = self.items[self.origin_index]
        self.d.focus(origin["hwnd"])
        self.d.exit("cancel")
        self.open = False
        self.closed_by = "back"
        if completed:
            # VOC toast.snap.one_side "{A} left · {B} right": the snapped window keeps its side and
            # the origin took the other one (K3 cancel_result, C5-53).
            snapped = "left" if self.sides["left"] is not None else "right"
            other = self.items[self.sides[snapped]]
            left, right = (other, origin) if snapped == "left" else (origin, other)
            self.d.toast(ONE_SIDE_TEXT.format(a=left["app"], b=right["app"]), exit=True)
        self.cancel = None


# =========================================================================== the tours
def detents(rt, count, rate):
    """``count`` detents at ``rate``/s, ping-ponging inside the list (one bump at each end)."""
    direction = 1
    for _ in range(count):
        rt.d.wait(1.0 / rate)
        nxt = rt.index + direction
        if nxt < 0 or nxt >= len(rt.items):
            rt.d.highlight(rt.index, direction)          # the end bump (K3's lim)
            rt.last_detent = rt.d.now()
            direction = -direction
            continue
        rt.detent(nxt)


def open_picker(d, items, origin_index, background, index=1, touch=False):
    rt = MiniRuntime(d, items, origin_index)
    d.runtime = rt
    snapshot = {"items": [{k: v for k, v in it.items() if not k.startswith("_")} for it in items],
                "index": index, "origin": {"hwnd": items[origin_index]["hwnd"], "pid": items[origin_index]["pid"]}}
    info = d.open(snapshot, background, items[origin_index]["hwnd"], touch=touch)
    rt.open = True
    rt.index = index
    return rt, info


def tour_w(d, items, background):
    """§6.4 W: 20 detents at 10/s and 20 at 20/s; snap left, snap right (pair close); reopen, one
    snap, then Back (the one-side completion)."""
    out = {"tour": "W", "background": background, "metrics_before": d.metrics()}
    rt, out["open"] = open_picker(d, items, 0, background, touch=True)     # WP7c-R6: a touch, then the press
    d.wait(0.8)
    detents(rt, 20, 10)
    detents(rt, 20, 20)
    d.wait(0.6)
    if rt.index == 0:
        rt.detent(1)
        d.wait(0.5)
    rt.snap("left")
    d.wait(1.0)                                  # accepted, placed, auto-advanced
    rt.snap("right")
    d.wait(1.6)                                  # the pair close at 820 and the exit
    out["pass1"] = {"snaps": list(rt.snaps), "closed_by": rt.closed_by, "sides": dict(rt.sides),
                    "order": list(rt.order)}
    out["pair"] = d.pair_check(items, rt, origin_hwnd=items[0]["hwnd"])
    out["metrics_after_pair"] = d.metrics()
    d.wait(0.6)
    # Reopen with the window snapped last as the origin (the foreground after the pair close).
    last = rt.sides[rt.order[-1]] if rt.order else 0
    rt, out["reopen"] = open_picker(d, items, last if last is not None else 0, background,
                                    index=1 if last != 1 else 2)
    d.wait(0.8)
    detents(rt, 3, 10)
    if rt.index == rt.origin_index:
        rt.detent((rt.index + 1) % len(items))
    d.wait(0.5)
    rt.snap("left")
    d.wait(1.0)
    rt.back()
    d.wait(1.4)
    out["pass2"] = {"snaps": list(rt.snaps), "closed_by": rt.closed_by, "cancel_log": rt.log[-3:]}
    out["one_side"] = d.flush_check(items[rt.origin_index]["hwnd"], "right")
    out["metrics"] = d.metrics()
    return out


def s3(d, items, busy_index):
    """§6.5 S3 on our own windows (and --real-hwnd ones): each kind snapped left, the origin
    completed right; then the busy target."""
    out = {"items": []}
    for index, item in enumerate(items):
        if index == 0 or item.get("_kind") not in S3_KINDS:
            continue
        d.focus_external(items[0]["hwnd"])
        d.wait(0.3)
        rt, info = open_picker(d, items, 0, "glass", index=index)
        d.wait(0.7)
        before = d.frame_rect(item["hwnd"])
        d.sample_foreground(True)
        record = rt.snap("left")
        d.wait(1.0)
        samples = d.sample_foreground(False)
        host = d.host_hwnd()
        entry = {"kind": item["_kind"], "hwnd": item["hwnd"], "open": info,
                 "class_name": item.get("class_name"), "integrity_above_ours": item.get("_elevated"),
                 "expected": expected_result(item),
                 "result": record and record["result"], "result_ms": record and record["result_ms"],
                 "accepted_ms": record and record["accepted_ms"],
                 "foreground_kept": bool(samples) and all(h == host for _t, h in samples) if host else None,
                 "flush": d.flush_check(item["hwnd"], "left")}
        if entry["expected"] == "move_rejected":
            after = d.frame_rect(item["hwnd"])
            entry["unmoved"] = None if before is None or after is None else list(before) == list(after)
        rt.back()
        d.wait(1.4)
        entry["completion"] = d.flush_check(items[0]["hwnd"], "right")
        entry["closed_by"] = rt.closed_by
        entry["ok"] = s3_entry_ok(entry)
        out["items"].append(entry)
    out["coverage"] = s3_coverage(out["items"])
    # The busy target.
    if busy_index is not None:
        d.focus_external(items[0]["hwnd"])
        d.wait(0.3)
        rt, info = open_picker(d, items, 0, "glass", index=busy_index)
        d.wait(0.7)
        frames0 = (d.metrics() or {}).get("frames_presented")
        d.sample_foreground(True)
        record = rt.snap("left")
        d.wait(0.03)
        d.stall(items[busy_index])                       # right after the pre-check
        for step in range(8):                            # keep turning under the stalled snap
            d.wait(0.1)
            rt.detent((busy_index + (1 if step % 2 == 0 else 0)) % len(items))
            if step == 1:
                rt.back()                                # latched until the snap resolves
        d.wait(0.4)
        frames1 = (d.metrics() or {}).get("frames_presented")
        d.wait(BUSY_STALL_S + 1.0)                       # the stall ends; the put-back lands
        samples = d.sample_foreground(False)
        out["busy"] = {"result": record and record["result"], "result_ms": record and record["result_ms"],
                       "accepted_ms": record and record["accepted_ms"], "closed_by": rt.closed_by,
                       "latched_ran": rt.closed_by == "back",
                       "frames_during_stall": (frames1 - frames0) if frames0 is not None and frames1 is not None
                       else None,
                       "busy_never_foreground": all(h != items[busy_index]["hwnd"] for _t, h in samples),
                       "final_rect": d.frame_rect(items[busy_index]["hwnd"]),
                       "original_rect": items[busy_index].get("_rect")}
    return out


# =========================================================================== verdicts
S3_KINDS = ("normal2", "maximized", "minimized", "unaware", "uwp", "elevated", "real")


def expected_result(item):
    """An elevated target is refused at the integrity pre-check (K4 §9.5 t = 0); every other kind
    ends ``ok`` (a UWP frame after the 400 ms verify path)."""
    return "move_rejected" if item.get("_kind") == "elevated" else "ok"


def s3_entry_ok(entry):
    """An elevated target: ``move_rejected``, not moved, closed by Back (``refused_at_precheck``
    records whether the integrity pre-check answered; K4 §9.5 lets the job carry on when the
    token query fails, and the async move is then refused by UIPI). Every other kind: ``ok``,
    closed by Back, and on screen flush in the left half with the origin completed right."""
    if entry["expected"] == "move_rejected":
        entry["refused_at_precheck"] = entry["accepted_ms"] is None
        return (entry["result"] == "move_rejected" and entry.get("unmoved") is not False
                and entry["closed_by"] == "back")
    flush_ok = all(check is None or bool(check.get("ok")) for check in (entry.get("flush"), entry.get("completion")))
    return entry["result"] == "ok" and entry["closed_by"] == "back" and flush_ok


def s3_coverage(entries):
    """K4 §6.5 S3's required target kinds: ``covered`` when an entry of that kind ran and passed,
    ``failed`` when it ran and did not, else ``not covered`` (S3 is then incomplete)."""
    kinds = {"maximized": ("maximized",), "minimized": ("minimized",), "uwp": ("uwp",),
             "elevated": ("elevated",), "mixed_dpi": ("unaware",)}
    out = {}
    for need, have in kinds.items():
        ran = [e for e in entries if e["kind"] in have]
        out[need] = "not covered" if not ran else ("covered" if all(e.get("ok") for e in ran) else "failed")
    out["complete"] = all(out[k] == "covered" for k in S3_REQUIRED)
    return out


def _pooled(metrics):
    return (((metrics or {}).get("frames") or {}).get("picker") or {}).get("pooled") or {}


def _cpu_totals(metrics):
    totals = (((metrics or {}).get("frames") or {}).get("picker") or {}).get("totals") or {}
    return (sum(float(t.get("cpu_s") or 0.0) for t in totals.values()),
            sum(float(t.get("wall_s") or 0.0) for t in totals.values()))


def frame_verdicts(metrics, wide, before=None, stress=False):
    """K4 §6.3 "Picker (W), step 1" for one pass (``before``: the metrics read at its start):
    - fps, interval p95 and max on the worst picker episode (``worst`` by missed frames);
    - the budget: the p95 of the per-frame **compose + present** over every picker episode frame of
      the pass (the pooled histograms after minus before), <= 5.6 ms on 16:9, <= 7.0 ms on 32:9
      (§22 Q2); never the compose alone;
    - the carousel thread's CPU over the pass's episodes (GetThreadTimes) <= 70 % of one core."""
    if not metrics:
        return {"ok": False, "why": "no metrics"}
    from control_center import carousel as CR
    pacer = metrics.get("pacer") or {}
    period = (pacer.get("period_ms") or 1000 / 60) / 1000.0
    worst = ((metrics.get("frames") or {}).get("picker") or {}).get("worst") or {}
    iv = worst.get("interval_ms") or {}
    rate = 1.0 / period
    need_fps = (110.0 if stress else 118.0) if rate > 200 else 0.49 * rate
    gate = 7.0 if wide else 5.6
    after_pool, before_pool = _pooled(metrics), _pooled(before)
    frames = int(after_pool.get("frames") or 0) - int(before_pool.get("frames") or 0)
    both = CR.hist_delta(after_pool.get("compose_present_ms"), before_pool.get("compose_present_ms"))
    work = CR.hist_delta(after_pool.get("work_ms"), before_pool.get("work_ms"))
    cpu1, wall1 = _cpu_totals(metrics)
    cpu0, wall0 = _cpu_totals(before)
    wall = wall1 - wall0
    cpu_pct = round(100.0 * (cpu1 - cpu0) / wall, 1) if wall > 0 else None
    out = {"rate_hz": round(rate, 2), "fps": worst.get("fps"), "need_fps": need_fps,
           "p95_ms": iv.get("p95"), "max_ms": iv.get("max"), "episode_frames": frames,
           "compose_present_p95_ms": CR.hist_quantile(both, 0.95), "compose_p95_ms": CR.hist_quantile(work, 0.95),
           "budget_gate_ms": gate, "worst_episode_compose_present_ms": worst.get("compose_present_ms"),
           "cpu_pct_one_core": cpu_pct, "cpu_gate_pct": CPU_GATE_PCT,
           "worst_episode_cpu_pct": worst.get("cpu_pct_one_core"), "compose_ms_max": metrics.get("compose_ms_max")}
    out["fps_ok"] = worst.get("fps") is not None and worst["fps"] >= need_fps
    out["p95_ok"] = iv.get("p95") is not None and iv["p95"] <= 2.02 * period * 1000
    out["max_ok"] = iv.get("max") is not None and iv["max"] <= 3 * period * 1000 and iv["max"] < 16.0
    out["budget_ok"] = out["compose_present_p95_ms"] is not None and out["compose_present_p95_ms"] <= gate
    out["cpu_ok"] = cpu_pct is not None and cpu_pct <= CPU_GATE_PCT
    out["ok"] = all(out[k] for k in ("fps_ok", "p95_ok", "max_ok", "budget_ok", "cpu_ok"))
    return out


def step3_verdicts(metrics, before=None, stress=False, displayed=None):
    """K4 §6.3 "Picker (W), step 3" (the GPU chrome) for one pass: the displayed frames (from the
    compositor statistics, ``displayed``; the loop's present cadence when those are missing), the
    per-frame Python work on normal and detent frames (the pooled histograms after minus before), the
    carousel thread's CPU."""
    if not metrics:
        return {"ok": False, "why": "no metrics"}
    from control_center import carousel as CR
    pacer = metrics.get("pacer") or {}
    period = (pacer.get("period_ms") or 1000 / 60) / 1000.0
    P_ms = period * 1000.0
    after_pool, before_pool = _pooled(metrics), _pooled(before)
    normal = CR.hist_delta(after_pool.get("normal_ms"), before_pool.get("normal_ms"))
    detent = CR.hist_delta(after_pool.get("detent_ms"), before_pool.get("detent_ms"))
    cpu1, wall1 = _cpu_totals(metrics)
    cpu0, wall0 = _cpu_totals(before)
    wall = wall1 - wall0
    cpu_pct = round(100.0 * (cpu1 - cpu0) / wall, 1) if wall > 0 else None
    worst = ((metrics.get("frames") or {}).get("picker") or {}).get("worst") or {}
    shown = displayed or {}
    fps = shown.get("fps_worst") if shown.get("fps_worst") is not None else worst.get("fps")
    iv = shown.get("interval_ms") or worst.get("interval_ms") or {}
    need = STEP3["fps_stress"] if stress else STEP3["fps"]
    out = {"rate_hz": round(1.0 / period, 2), "method": "dcomp_target_stats" if shown.get("fps_worst") is not None
           else "present_cadence", "fps": fps, "need_fps": need, "interval_ms": iv,
           "normal_p95_ms": CR.hist_quantile(normal, 0.95), "detent_p95_ms": CR.hist_quantile(detent, 0.95),
           "normal_frames": sum(normal.values()), "detent_frames": sum(detent.values()), "cpu_pct_one_core": cpu_pct,
           "chrome": (worst or {}).get("chrome"), "gpu_fallbacks": metrics.get("gpu_fallbacks")}
    rate_ok = (1.0 / period) > 200
    out["fps_ok"] = fps is not None and (fps >= need if rate_ok else fps >= 0.979 / period)
    out["p95_ok"] = iv.get("p95") is not None and iv["p95"] <= STEP3["p95_P"] * P_ms
    out["p99_ok"] = iv.get("p99") is None or iv["p99"] <= STEP3["p99_P"] * P_ms
    out["max_ok"] = (not stress) or (iv.get("max") is not None and iv["max"] <= STEP3["max_P_stress"] * P_ms)
    out["normal_ok"] = out["normal_p95_ms"] is not None and out["normal_p95_ms"] <= STEP3["normal_ms"]
    out["detent_ok"] = out["detent_p95_ms"] is None or out["detent_p95_ms"] <= STEP3["detent_ms"]
    out["cpu_ok"] = cpu_pct is not None and cpu_pct <= STEP3["cpu_pct"]
    out["gpu_ok"] = out["chrome"] == "gpu" and not metrics.get("gpu_fallbacks")
    out["ok"] = all(out[k] for k in ("fps_ok", "p95_ok", "p99_ok", "max_ok", "normal_ok", "detent_ok", "cpu_ok",
                                     "gpu_ok"))
    return out


class StatsHarvester(threading.Thread):
    """The compositor's target statistics for the picker's monitor, harvested every 250 ms while a
    pass runs (GIL-keeping reads, G1-1; only while the display is on, G1-3)."""

    def __init__(self, monitor_rect=None):
        super().__init__(name="picker-checks-harvest", daemon=True)
        from control_center.stage import frames as FR
        from control_center.stage import win32 as SW
        from control_center.stage import com as SC
        key = None
        try:
            if monitor_rect is not None:                   # (l, t, r, b): the picker's monitor's target
                l, t, r, b = monitor_rect
                hmon = SW.MonitorFromPoint(SC.POINT((l + r) // 2, (t + b) // 2), SW.MONITOR_DEFAULTTONEAREST)
                info = SW.monitor_info(hmon) or {}
                key = SW.adapter_for_display(info["device"]) if info.get("device") else None
        except Exception:
            key = None
        self.harvest = FR.CompositorHarvest(FR.NativeStatsReader(key))
        self.stop_ev = threading.Event()
        self.error = None

    def run(self):
        try:
            self.harvest.start()
            while not self.stop_ev.wait(HARVEST_S):
                self.harvest.harvest(True)
            self.harvest.harvest(True)
        except BaseException as exc:
            self.error = repr(exc)

    def stop(self):
        self.stop_ev.set()
        self.join(2.0)
        return self.harvest.frames, self.harvest.unknown


def displayed_frames(frames, unknown, metrics, t_from, qpf=None):
    """The picker episodes of a pass (``frames.picker.recent`` with start >= ``t_from``, perf seconds)
    matched with the harvested frames: per episode ``episode_from_frames``; the worst by missed."""
    from control_center.stage import frames as FR
    from control_center.stage import win32 as SW
    qpf = qpf or SW.qpf()
    recent = ((((metrics or {}).get("frames") or {}).get("picker") or {}).get("recent")) or []
    pacer = (metrics or {}).get("pacer") or {}
    period_s = (pacer.get("period_ms") or 1000 / 60) / 1000.0
    eps = []
    period_t = period_s * qpf
    for entry in recent:
        kind, t0, t1, chrome = entry[:4]
        loop = entry[4] if len(entry) > 4 and isinstance(entry[4], dict) else None
        if t0 < t_from or t1 - t0 < 0.05:
            continue
        ep = FR.episode_from_frames(frames, unknown, int(t0 * qpf), int(t1 * qpf), period_t, qpf,
                                    rate_hz=round(1.0 / period_s, 2))
        ep["kind"], ep["chrome"] = kind, chrome
        ep["t0"], ep["t1"] = round(t0, 6), round(t1, 6)
        # T1 of the 2026-09-26 diagnosis: where in the episode each missed interval lies (ms from its
        # start to the frame after the gap), so a snap's misses can be placed against its phases
        sel = sorted((f for f in frames if f.present_time and int(t0 * qpf) <= f.completed_time <= int(t1 * qpf)),
                     key=lambda f: f.id)
        ep["gaps"] = [[round((b.completed_time - t0 * qpf) * 1000.0 / qpf, 2),
                       round((b.completed_time - a.completed_time) / period_t, 2)]
                      for a, b in zip(sel, sel[1:]) if b.completed_time - a.completed_time > 1.5 * period_t][:80]
        ep["loop"] = loop
        ep["attribution"] = attribute_gaps(ep, loop, period_s * 1000.0)
        eps.append(ep)
    if not eps:
        return {"episodes": 0}
    counted = [e for e in eps if e.get("frames")]
    worst = max(counted, key=lambda e: ((e.get("missed") or 0), -(e.get("fps") or 0.0))) if counted else eps[0]
    keep = ("kind", "chrome", "t0", "t1", "frames", "vblanks", "fps", "missed", "double_missed", "interval_P",
            "duration_ms", "valid", "gaps", "attribution")
    return {"episodes": len(eps), "fps_worst": min((e["fps"] for e in counted), default=None),
            "interval_ms": worst.get("interval_ms"), "missed": sum(e.get("missed") or 0 for e in counted),
            "double_missed": sum(e.get("double_missed") or 0 for e in counted),
            "invalid": sum(1 for e in eps if not e.get("valid")), "worst": worst,
            "all": [{k: e.get(k) for k in keep} for e in eps]}              # every displayed episode (T1)


LOCK_SHARE_MIN = 0.5            # attribution: at least half the presents paced at cadence 2 ...
LOCK_INTERVAL_P50 = 1.9         # ... and displayed frames typically 2 P apart: the P5 120 lock


def attribute_gaps(ep, loop, period_ms):
    """Which cause an episode's missed intervals point to (the 2026-09-26 review of the frame-drop
    fixes asked the re-run to settle it before the re-registration item is closed):

    - **the P5 120 lock**: the loop paced most of its presents at cadence 2 (``loop.locked_frames``)
      and the displayed interval p50 is about 2 P (the snap episodes of the morning's run: p50
      exactly 8.332 ms, max 3 P);
    - **thumbnail re-registration**: at least half of the gaps begin within 1.5 P of a frame that
      re-registered the thumbnails (``loop.rereg_at_ms``, ms from the episode's start);
    - else unattributed (with the numbers). ``loop`` None: a presenter without the attribution
      fields (before the review fix)."""
    gaps = ep.get("gaps") or []
    out = {"gaps": len(gaps)}
    if loop is None:
        out["cause"] = "no loop record (a presenter from before the attribution fields)"
        return out
    paced = loop.get("paced_frames") or 0
    share = (loop.get("locked_frames") or 0) / paced if paced else None
    rereg = [float(x) for x in loop.get("rereg_at_ms") or ()]
    near = 0
    for end_ms, length_p in gaps:
        start = end_ms - length_p * period_ms
        if any(start - 1.5 * period_ms <= r <= end_ms for r in rereg):
            near += 1
    p50 = (ep.get("interval_P") or {}).get("p50")
    out.update(locked_share=None if share is None else round(share, 3), rereg_frames=len(rereg),
               gaps_near_rereg=near, interval_P_p50=p50, cadence_switches=loop.get("cadence_switches"))
    if not gaps:
        out["cause"] = "no gaps"
    elif share is not None and share >= LOCK_SHARE_MIN and (p50 or 0) >= LOCK_INTERVAL_P50:
        out["cause"] = ("the P5 120 lock: %d of %d presents paced at cadence 2, displayed interval p50 %.2f P"
                        % (loop.get("locked_frames") or 0, paced, p50))
    elif near and near * 2 >= len(gaps):
        out["cause"] = ("thumbnail re-registration: %d of %d gaps begin within 1.5 P of a re-registering frame"
                        % (near, len(gaps)))
    else:
        out["cause"] = ("unattributed: %s of the presents locked, %d of %d gaps near a re-registration"
                        % ("n/a" if share is None else "%.0f %%" % (100 * share), near, len(gaps)))
    return out


def displayed_frames_self_check():
    """--dry-run: ``displayed_frames`` keeps every episode and places each missed interval (T1 of the
    2026-09-26 diagnosis), on synthetic frames: 2 s at 240 Hz, one 3 P gap 112.5 ms into the second
    episode right after a re-registering frame, and a third episode presented every second vblank
    under the 120 lock; ``attribute_gaps`` names each cause (the review of the fixes)."""
    from control_center.stage.frames import TargetFrame
    qpf = 10_000_000
    P = qpf / 240.0
    base = 1_000_000_000
    frames, fid = [], 0
    for i in range(480):
        if i in (145, 146) or (240 <= i < 360 and i % 2):
            continue
        t = int(base + i * P)
        fid += 1
        frames.append(TargetFrame(fid, t, t, fid, fid, target_time=t))
    t0 = base / qpf
    loop_open = {"presents": 120, "locked_frames": 0, "paced_frames": 120, "cadence_switches": 0,
                 "rereg_at_ms": [], "rereg_ms_max": 0.0}
    loop_snap = dict(loop_open, rereg_at_ms=[40.2, 101.3], rereg_ms_max=2.1)
    loop_locked = dict(loop_open, presents=60, locked_frames=58, paced_frames=60, cadence_switches=1)
    metrics = {"pacer": {"period_ms": 1000 / 240.0},
               "frames": {"picker": {"recent": [("open", t0, t0 + 0.5, "gpu", loop_open),
                                                ("snap", t0 + 0.5, t0 + 1.0, "gpu", loop_snap),
                                                ("snap", t0 + 1.0, t0 + 1.5, "gpu", loop_locked),
                                                ("close", t0 + 1.5, t0 + 1.9, "gpu")]}}}   # an old 4-field entry
    shown = displayed_frames(frames, [], metrics, t0 - 1.0, qpf=qpf)
    eps = shown.get("all") or []
    gaps = eps[1]["gaps"] if len(eps) > 1 else None
    causes = [(e.get("attribution") or {}).get("cause") or "" for e in eps]
    ok = shown.get("episodes") == 4 and len(eps) == 4 and not eps[0]["gaps"] and bool(gaps) \
        and abs(gaps[0][1] - 3.0) < 0.01 and abs(gaps[0][0] - 112.5) < 0.5 \
        and causes[0] == "no gaps" and causes[1].startswith("thumbnail re-registration") \
        and causes[2].startswith("the P5 120 lock") and causes[3].startswith("no loop record")
    return {"ok": ok, "episodes": shown.get("episodes"), "gaps": gaps, "causes": causes}


def chrome_pickup(events, frames, period_ticks):
    """The chrome's Commits (t1, done) against the compositions (``stage.proof.pickup_classes``)."""
    from control_center.stage import proof as PF
    ks, classes = PF.pickup_classes(frames, list(events), period_ticks)
    known = classes.get("known") or 0
    classes["ok"] = bool(known) and classes.get("early", 0) == 0 and classes.get("later", 0) <= 0.05 * known
    return classes


class RowGrabber:
    """BitBlt of a 1-px screen row into a 32-bit DIB: (B, G, R, X) bytes (our picker's row only)."""

    def __init__(self, x, y, w):
        from control_center.stage import win32 as SW
        self.W = SW
        self.x, self.y, self.w = int(x), int(y), int(w)
        self.screen = SW.GetDC(None)
        self.mdc = SW.CreateCompatibleDC(self.screen)
        bmi = SW.BITMAPINFOHEADER(C.sizeof(SW.BITMAPINFOHEADER), self.w, -1, 1, 32, 0, 0, 0, 0, 0, 0)
        self.bits = C.c_void_p()
        self.dib = SW.CreateDIBSection(self.screen, C.byref(bmi), 0, C.byref(self.bits), None, 0)
        self.old = SW.SelectObject(self.mdc, self.dib)

    def grab(self):
        SW = self.W
        if not SW.BitBlt(self.mdc, 0, 0, self.w, 1, self.screen, self.x, self.y, SW.SRCCOPY | SW.CAPTUREBLT):
            return None
        SW.GdiFlush()
        return bytes((C.c_ubyte * (self.w * 4)).from_address(self.bits.value))

    def close(self):
        SW = self.W
        if self.old:
            SW.SelectObject(self.mdc, self.old)
        if self.dib:
            SW.DeleteObject(self.dib)
        if self.mdc:
            SW.DeleteDC(self.mdc)
        SW.ReleaseDC(None, self.screen)


class AlignWitness(threading.Thread):
    """AR-12's witness: rows through the middle of the cards every WITNESS_S (see the docstring)."""

    def __init__(self, x, y, w, max_samples=20000):
        super().__init__(name="picker-checks-witness", daemon=True)
        self.args = (x, y, w)
        self.samples = []
        self.stop_ev = threading.Event()
        self.max_samples = max_samples
        self.error = None

    def run(self):
        g = None
        try:
            g = RowGrabber(*self.args)
            while not self.stop_ev.wait(WITNESS_S) and len(self.samples) < self.max_samples:
                ta = time.perf_counter()
                row = g.grab()
                tb = time.perf_counter()
                if row is not None:
                    self.samples.append(((ta + tb) / 2.0, row))
        except BaseException as exc:
            self.error = repr(exc)
        finally:
            if g is not None:
                g.close()

    def stop(self):
        self.stop_ev.set()
        self.join(2.0)
        return self.samples


def _runs(values, test):
    out, start = [], None
    for i, v in enumerate(list(values) + [None]):
        if v is not None and test(v):
            if start is None:
                start = i
        elif start is not None:
            out.append((start, i))
            start = None
    return out


def align_row(row, k):
    """(ring centre, thumbnail centre, ring outer width) of one BGRX row, or None: the selection
    frame's two white sides (the brightest narrow runs) and, inside them past the gap, the first
    and last pixels that differ from the gap's colour (the centre card's thumbnail edges)."""
    n = len(row) // 4
    px = [(row[4 * i + 2], row[4 * i + 1], row[4 * i]) for i in range(n)]
    lum = [(r + g + b) / 3.0 for r, g, b in px]
    side_max = max(3, int(round(2 * k)) + 2)
    sides = [(a, b) for a, b in _runs(lum, lambda v: v >= 185) if 1 <= b - a <= side_max]
    ring_unit = (400 + 2 * 8) * k                   # the frame's outer width at scale 1 (K4 9.3)
    best = None
    for i in range(len(sides)):
        for j in range(i + 1, len(sides)):
            a, b = sides[i], sides[j]
            width = b[1] - a[0]
            if not 0.45 * ring_unit <= width <= 1.03 * ring_unit:
                continue
            score = sum(lum[a[0]:a[1]]) + sum(lum[b[0]:b[1]])
            if best is None or score > best[0]:
                best = (score, a, b)
    if best is None:
        return None
    _score, a, b = best
    width = b[1] - a[0]
    scale = width / ring_unit
    gap = max(2, int(round(6 * k * scale)))
    # The thumbnail's colour, read at the frame's centre (our test window is one solid colour at the
    # card's mid-height); its edges are where that colour starts and ends inside the frame.
    card = px[(a[0] + b[1]) // 2]

    def like(x):
        return sum(abs(c - d) for c, d in zip(px[x], card)) < 45
    tl = tr = None
    for x in range(a[1], min(b[0], a[1] + 4 * gap + 40)):
        if like(x) and like(min(n - 1, x + 1)):
            tl = x
            break
    for x in range(b[0] - 1, max(a[1], b[0] - 1 - 4 * gap - 40), -1):
        if like(x) and like(max(0, x - 1)):
            tr = x + 1
            break
    if tl is None or tr is None:
        return None
    expected = width * 400.0 / 416.0
    if abs((tr - tl) - expected) > 8:
        return None
    return ((a[0] + b[1]) / 2.0, (tl + tr) / 2.0, width)


def analyse_alignment(samples, k, period_s):
    """AR-12's verdict from the witness rows: offsets (thumbnail centre - frame centre), and while the
    cards move, the thumbnails' lag in frames (offset against the frame's own speed x P)."""
    rows = []
    for t, row in samples:
        r = align_row(row, k)
        if r is not None:
            rows.append((t, r[0], r[1]))
    out = {"samples": len(samples), "valid": len(rows)}
    if len(rows) < 3:
        out.update({"ok": None, "why": "too few rows with the frame and the thumbnail"})
        return out
    offsets = [ct - cr for _t, cr, ct in rows]
    lags = []
    moving = []
    for (t0, c0, _), (t1, c1, ct1) in zip(rows, rows[1:]):
        dt = t1 - t0
        if not 0.0005 <= dt <= 0.02:
            continue
        v = (c1 - c0) / dt                           # px/s of the chrome (compositor-run: on time)
        if abs(v) < 800.0:
            continue
        off = ct1 - c1
        moving.append(abs(off))
        lags.append(-off / (v * period_s))           # > 0: the thumbnail trails the chrome
    ab = sorted(abs(o) for o in offsets)
    out.update({"offset_px": {"p50": round(ab[len(ab) // 2], 2), "p95": round(ab[int(0.95 * (len(ab) - 1))], 2),
                              "max": round(ab[-1], 2)},
                "moving_rows": len(moving)})
    if lags:
        lags.sort()
        moving.sort()
        med = lags[len(lags) // 2]
        out.update({"lag_frames_median": round(med, 3), "moving_offset_p95_px": round(moving[int(0.95 * (len(moving) - 1))], 2),
                    "ok": abs(med) < 0.5 and moving[int(0.95 * (len(moving) - 1))] <= 6.0,
                    "recommend_thumb_lead": max(0, int(round(med))) if abs(med) >= 0.5 else 0})
    else:
        out.update({"ok": None, "why": "no rows while the cards moved"})
    return out


def synthetic_alignment_check(k=2.0, period_s=1 / 240.0):
    """--dry-run: the analysis recovers a known lag from synthetic rows (a white frame and a coloured
    card moving at a known speed; the card drawn 0 and then 1 frame behind)."""
    results = {}
    for lag in (0, 1):
        samples = []
        width_px = 2560
        for i in range(200):
            t = i * 0.002
            speed = 3000.0                                        # px/s
            centre = 1280 + speed * t
            s_scale = 1.0
            ring_half = (400 + 16) * k * s_scale / 2
            card_half = 400 * k * s_scale / 2
            card_centre = centre - speed * lag * period_s
            row = bytearray(b"\x20\x18\x18\x00" * width_px)
            for x in range(width_px):
                if abs(x + 0.5 - card_centre) < card_half:
                    row[4 * x:4 * x + 3] = bytes((0xC0, 0x60, 0x30))
            for edge in (int(round(centre - ring_half)), int(round(centre + ring_half)) - int(2 * k)):
                for x in range(edge, edge + int(2 * k)):
                    if 0 <= x < width_px:
                        row[4 * x:4 * x + 3] = b"\xf0\xf0\xf0"
            samples.append((t, bytes(row)))
        results[lag] = analyse_alignment(samples, k, period_s)
    ok = (results[0].get("ok") is True and results[1].get("ok") is False
          and abs(results[1].get("lag_frames_median", 0) - 1.0) < 0.25 and results[1].get("recommend_thumb_lead") == 1)
    return {"ok": ok, "aligned": {k2: results[0].get(k2) for k2 in ("valid", "lag_frames_median", "ok")},
            "one_frame_late": {k2: results[1].get(k2) for k2 in ("valid", "lag_frames_median", "ok",
                                                                 "recommend_thumb_lead")}}


def alignment_pass(d, items, background="glass"):
    """AR-12's witness pass (GPU chrome): open, 12 detents at 4/s while rows are captured."""
    out = {"background": background}
    rt, out["open"] = open_picker(d, items, 0, background, index=2)
    d.wait(0.9)                                  # the frost was captured; our windows are capturable again
    layout = d.layout()
    if layout is None:
        out["error"] = "no layout"
        return out
    from control_center import carousel_render as R
    y = int(round(layout.stage_y + (R.CENTER_Y + R.GROUP_SHIFT) * layout.k))     # before the first snap
    witness = d.witness(int(round(layout.stage_x)), y, int(round(R.STAGE_W * layout.k)))
    try:
        direction = 1
        for _ in range(12):
            d.wait(0.25)
            nxt = rt.index + direction
            if nxt < 1 or nxt >= len(items) - 1:
                direction = -direction
                nxt = rt.index + direction
            rt.detent(nxt)
        d.wait(0.6)
    finally:
        samples = witness.stop() if witness is not None else []
    period = ((d.metrics().get("pacer") or {}).get("period_ms") or 1000 / 60) / 1000.0
    out["analysis"] = analyse_alignment(samples, layout.k, period)
    out["witness_error"] = getattr(witness, "error", None)
    rt.back()
    d.wait(0.8)
    return out


# =========================================================================== drivers
class DryDriver:
    """The presenter inline on the tests' fake backend, fake capture and a fake NanoD-snap that
    answers at once (accepted) and at t0 + 400 (ok), except for a stalled window (no answer: the
    carousel's backstop resolves it at t0 + 800). Fake time advances in 1/240 s steps."""

    def __init__(self, chrome="gpu"):
        tests = os.path.join(ND, "tests")
        if tests not in sys.path:
            sys.path.insert(0, tests)
        import test_carousel_presenter as T
        from control_center import carousel as CR
        from control_center.stage import picker_testing as PT
        self.T, self.CR = T, CR

        class GpuFakeBackend(T.FakeBackend):
            has_gpu_window = True                  # the engine asks whether the window exists (WP7c-R7)

            def gpu_window(self, rect):
                self.log("gpu_window", tuple(rect))
                return 0x6001

            def gpu_show(self):
                self.visible.add("gpu")

            def gpu_hide(self):
                self.visible.discard("gpu")
        self.clock = PT.SharedClock()
        self.backend = GpuFakeBackend(monitor=(0, 0, 5120, 1440), work=(0, 0, 5120, 1392))
        self.backend.clock = self.clock
        self.capture = T.FakeCapture(self.backend)
        self.snapper = T.FakeSnap()
        self.snapper.backend = self.backend
        self.gpu = None
        if chrome != "cpu":
            self.gpu = PT.fake_chrome(self.clock)
            self.gpu.prewarm_step(None)
        self.p = CR.CarouselPresenter(None, None, lambda: None, backend=self.backend, capture=self.capture,
                                      snap=self.snapper, clock=self.clock, inline=True,
                                      gpu_chrome=self.gpu if self.gpu is not None else False, environ={})
        self.runtime = None
        self.stalled = set()
        self.elevated = set()
        self.answered = {}
        self.events = []
        self.toasts = []
        self.toast_texts = []
        self.sampling = None

    def now(self):
        return self.clock.t

    def open(self, snapshot, background, origin_hwnd, touch=False):
        self.p.set_background(background)
        if touch:
            self.p.note_touch()
        self.p.show(snapshot)
        self.backend.activate()
        self._step()
        if self.capture.jobs:
            self.capture.complete()
        return {"ok": True}

    def highlight(self, index, bump=0):
        self.p.highlight(index, bump)

    def snap(self, request):
        self.p.snap(request)

    def half_rect(self, side):
        return self.p.half_rect(side)

    def complete_one_side(self, origin, side):
        return self.p.complete_one_side(origin, side, self.p.half_rect(side))

    def raise_window(self, hwnd):
        self.p.raise_window(hwnd)

    def focus(self, hwnd):
        return True

    def focus_external(self, hwnd):
        return True

    def exit(self, kind):
        {"pair": self.p.play_pair_exit, "cancel": self.p.play_cancel_exit,
         "switch": self.p.play_switch_exit}[kind]()
        self.p.hide()

    def toast(self, text, exit=False):
        self.toast_texts.append(text)
        self.toasts.append(bool(self.p.toast(text, exit=exit)))

    def stall(self, item):
        self.stalled.add(item["hwnd"])

    def host_hwnd(self):
        return None

    def sample_foreground(self, on):
        return []

    def flush_check(self, hwnd, side):
        return None

    def frame_rect(self, hwnd):
        return None

    def pair_check(self, items, rt, origin_hwnd):
        return None

    def metrics(self):
        return self.p.metrics()

    def layout(self):
        return getattr(getattr(self.p, "_status", None), "layout", None)

    def witness(self, x, y, w):
        return None

    def _answer(self):
        for job in list(self.snapper.jobs):
            state = self.answered.setdefault(job.id, set())
            if job.kind == "snap" and job.hwnd in self.elevated:
                if "pre" not in state:                   # the integrity pre-check refuses it
                    state.add("pre")
                    self.snapper.answer(job, "precheck", "move_rejected")
            elif job.kind == "snap" and job.hwnd not in self.stalled:
                if "pre" not in state:
                    state.add("pre")
                    self.snapper.answer(job, "precheck", "accepted")
                elif "final" not in state and self.clock.t >= job.t0 + 0.4:
                    state.add("final")
                    self.snapper.answer(job, "final", "ok", {"rect": job.target})
            elif job.kind == "complete" and "done" not in state and self.clock.t >= job.t0 + 0.3:
                state.add("done")
                self.snapper.answer(job, "complete", "ok")

    def _step(self):
        self._answer()
        self.p._step_inline()
        for kind, payload in self.p.take_events():
            self.events.append((round(self.clock.t, 4), kind, payload))
            if self.runtime is not None:
                self.runtime.on_event(kind, payload, self.clock.t)
        if self.runtime is not None:
            self.runtime.tick(self.clock.t)

    def wait(self, s):
        end = self.clock.t + s
        while self.clock.t < end - 1e-9:
            self.clock.t = min(end, self.clock.t + 1 / 240)
            self._step()

    def close(self):
        self.p.close()


class ScreenDriver:
    """The production presenter on screen. The main thread plays the Tk thread: it pumps its
    queue (the abort hotkey and the grant hotkey), drains the presenter's events into the
    runtime, samples the foreground when asked."""

    def __init__(self, presenter, native, targets):
        self.p = presenter
        self.native = native
        self.targets = targets
        self.u32 = C.windll.user32
        self.dwm = C.windll.dwmapi
        self.runtime = None
        self.events = []
        self.aborted = None
        self.sampling = None
        self.grant_vk = None
        self.opens = []

    # ------------------------------------------------------------ foreground grant
    def arm_grant(self):
        for vk in (VK_F23, VK_F22):
            if self.u32.RegisterHotKey(None, GRANT_ID, MOD_NOREPEAT, vk):
                self.grant_vk = vk
                return True
        return False

    def grant(self):
        """Inject our own hotkey: WM_HOTKEY gives this thread the foreground right, the way the
        knob's F24 does for the companion."""
        if self.grant_vk is None:
            return False

        class KEYBDINPUT(C.Structure):
            _fields_ = [("wVk", WT.WORD), ("wScan", WT.WORD), ("dwFlags", WT.DWORD), ("time", WT.DWORD),
                        ("dwExtraInfo", C.c_size_t)]

        class INPUT(C.Structure):
            class _U(C.Union):
                _fields_ = [("ki", KEYBDINPUT), ("pad", C.c_byte * 32)]
            _anonymous_ = ("u",)
            _fields_ = [("type", WT.DWORD), ("u", _U)]
        seq = (INPUT * 2)()
        for i, flags in enumerate((0, 0x0002)):
            seq[i].type = 1
            seq[i].ki = KEYBDINPUT(self.grant_vk, 0, flags, 0, 0)
        self.u32.SendInput(2, seq, C.sizeof(INPUT))
        deadline = time.perf_counter() + 1.0
        msg = WT.MSG()
        while time.perf_counter() < deadline:
            while self.u32.PeekMessageW(C.byref(msg), None, 0, 0, 1):
                if msg.message == WM_HOTKEY and msg.wParam == GRANT_ID:
                    return True
                if msg.message == WM_HOTKEY and msg.wParam == ABORT_ID:
                    self.aborted = "hotkey"
            time.sleep(0.002)
        return False

    # ------------------------------------------------------------ the presenter
    def now(self):
        return time.perf_counter()

    def open(self, snapshot, background, origin_hwnd, touch=False):
        self.focus_external(origin_hwnd)
        self.wait(0.15)
        granted = self.grant()
        self.p.set_background(background)
        warm_before = None
        if touch:                                   # WP7c-R6: the chrome's device is made off the handshake
            warm_before = bool(((self.p.metrics().get("gpu") or {}).get("warm")))
            self.p.note_touch()
            time.sleep(0.002)
        t = time.perf_counter()
        self.p.show(snapshot)
        shown = time.perf_counter()
        focused = self.native.focus(self.p.hwnd)
        info = {"grant": granted, "show_ms": round((shown - t) * 1000, 1),
                "focus_ms": round((time.perf_counter() - shown) * 1000, 1), "focused": bool(focused)}
        if touch:
            info.update(touched=True, device_warm_before_touch=warm_before)
        self.opens.append(info)
        return info

    def highlight(self, index, bump=0):
        self.p.highlight(index, bump)

    def snap(self, request):
        self.p.snap(request)

    def half_rect(self, side):
        return self.p.half_rect(side)

    def complete_one_side(self, origin, side):
        return self.p.complete_one_side({k: origin[k] for k in ("id", "hwnd", "pid", "class_name", "exstyle")
                                         if k in origin}, side, self.p.half_rect(side))

    def raise_window(self, hwnd):
        self.p.raise_window(hwnd)

    def focus(self, hwnd):
        return self.native.focus(hwnd)

    def focus_external(self, hwnd):
        if self.grant():
            return self.native.focus(hwnd)
        return False

    def exit(self, kind):
        {"pair": self.p.play_pair_exit, "cancel": self.p.play_cancel_exit,
         "switch": self.p.play_switch_exit}[kind]()
        self.p.hide()

    def toast(self, text, exit=False):
        self.p.toast(text, exit=exit)

    def stall(self, item):
        self.targets.stall()

    def host_hwnd(self):
        return self.p.hwnd

    def sample_foreground(self, on):
        if on:
            self.sampling = []
            return []
        samples, self.sampling = self.sampling or [], None
        return samples

    def frame_rect(self, hwnd):
        rect = WT.RECT()
        if self.dwm.DwmGetWindowAttribute(WT.HWND(hwnd), 9, C.byref(rect), C.sizeof(rect)) != 0:
            if not self.u32.GetWindowRect(WT.HWND(hwnd), C.byref(rect)):
                return None
        return [rect.left, rect.top, rect.right, rect.bottom]

    def flush_check(self, hwnd, side):
        half = self.p.half_rect(side)
        rect = self.frame_rect(hwnd)
        if half is None or rect is None:
            return {"ok": False, "half": half, "rect": rect}
        diff = [abs(a - b) for a, b in zip(rect, half)]
        return {"ok": max(diff) <= MATCH_PX, "half": list(half), "rect": rect, "max_diff_px": max(diff)}

    def z_order(self):
        order = []
        h = self.u32.GetTopWindow(None)
        while h and len(order) < 4096:
            order.append(h)
            h = self.u32.GetWindow(h, 2)                 # GW_HWNDNEXT
        return order

    def pair_check(self, items, rt, origin_hwnd):
        """S3: after the pair close both halves lie above the origin (the posted raise, §9.7)."""
        self.wait(0.5)
        order = self.z_order()
        pos = {h: i for i, h in enumerate(order)}
        left = items[rt.sides["left"]]["hwnd"] if rt.sides["left"] is not None else None
        right = items[rt.sides["right"]]["hwnd"] if rt.sides["right"] is not None else None
        o = pos.get(origin_hwnd)
        above = {side: (pos.get(h) is not None and o is not None and pos[h] < o) for side, h in
                 (("left", left), ("right", right)) if h}
        fg = self.u32.GetForegroundWindow()
        return {"both_above_origin": bool(above) and all(above.values()) if origin_hwnd not in (left, right)
                else None, "above": above, "foreground_is_last": fg == (items[rt.sides[rt.order[-1]]]["hwnd"]
                                                                       if rt.order else None),
                "flush_left": self.flush_check(left, "left") if left else None,
                "flush_right": self.flush_check(right, "right") if right else None}

    def metrics(self):
        try:
            return self.p.metrics()
        except Exception as exc:
            return {"error": repr(exc)}

    def layout(self):
        return getattr(getattr(self.p, "_status", None), "layout", None)

    def witness(self, x, y, w):
        wit = AlignWitness(x, y, w)
        wit.start()
        return wit

    def wait(self, s):
        end = time.perf_counter() + s
        msg = WT.MSG()
        while True:
            while self.u32.PeekMessageW(C.byref(msg), None, 0, 0, 1):
                if msg.message == WM_HOTKEY and msg.wParam == ABORT_ID:
                    self.aborted = "hotkey"
            if self.aborted:
                try:
                    self.p.hide()
                finally:
                    raise KeyboardInterrupt(self.aborted)
            now = time.perf_counter()
            for kind, payload in self.p.take_events():
                self.events.append((round(now, 4), kind, payload))
                if self.runtime is not None:
                    self.runtime.on_event(kind, payload, now)
            if self.runtime is not None:
                self.runtime.tick(now)
            if self.sampling is not None:
                self.sampling.append((now, self.u32.GetForegroundWindow()))
            left = end - time.perf_counter()
            if left <= 0:
                return
            time.sleep(min(0.004, left))


# =========================================================================== the test windows
class Targets:
    """The helper process (``--child-targets``) and its windows."""

    def __init__(self):
        self.proc = subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), "--child-targets"],
                                     cwd=ND, stdout=subprocess.PIPE, text=True)
        line = self.proc.stdout.readline()
        self.info = json.loads(line)
        self.k32 = C.windll.kernel32

    def _event(self, name):
        h = self.k32.OpenEventW(0x0002, False, name)             # EVENT_MODIFY_STATE
        if h:
            self.k32.SetEvent(h)
            self.k32.CloseHandle(h)
        return bool(h)

    def stall(self):
        return self._event(self.info["busy_event"])

    def close(self):
        self._event(self.info["quit_event"])
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def run_targets():
    """``--child-targets``: our 10 test windows (see the module docstring); prints their handles
    as one JSON line, then pumps until the quit event or TARGETS_LIFETIME_S."""
    u32 = C.WinDLL("user32", use_last_error=True)
    k32 = C.WinDLL("kernel32", use_last_error=True)
    gdi = C.WinDLL("gdi32", use_last_error=True)
    LRESULT = C.c_ssize_t
    WNDPROC = C.WINFUNCTYPE(LRESULT, WT.HWND, WT.UINT, WT.WPARAM, WT.LPARAM)
    u32.DefWindowProcW.argtypes = (WT.HWND, WT.UINT, WT.WPARAM, WT.LPARAM)
    u32.DefWindowProcW.restype = LRESULT
    u32.CreateWindowExW.argtypes = (WT.DWORD, WT.LPCWSTR, WT.LPCWSTR, WT.DWORD, C.c_int, C.c_int, C.c_int, C.c_int,
                                    WT.HWND, WT.HMENU, WT.HINSTANCE, WT.LPVOID)
    u32.CreateWindowExW.restype = WT.HWND
    u32.FillRect.argtypes = (WT.HDC, C.POINTER(WT.RECT), WT.HBRUSH)
    u32.MsgWaitForMultipleObjects.argtypes = (WT.DWORD, C.POINTER(WT.HANDLE), WT.BOOL, WT.DWORD, WT.DWORD)
    k32.CreateEventW.restype = WT.HANDLE
    k32.CreateEventW.argtypes = (WT.LPVOID, WT.BOOL, WT.BOOL, WT.LPCWSTR)
    gdi.CreateSolidBrush.restype = WT.HBRUSH
    brushes = {}

    @WNDPROC
    def proc(hwnd, msg, wp, lp):
        if msg == 0x0014:                                        # WM_ERASEBKGND
            rect = WT.RECT()
            u32.GetClientRect(hwnd, C.byref(rect))
            u32.FillRect(WT.HDC(wp), C.byref(rect), brushes.get(hwnd) or gdi.GetStockObject(0))
            return 1
        if msg == 0x0010:                                        # WM_CLOSE: only the quit event ends us
            return 0
        return u32.DefWindowProcW(hwnd, msg, wp, lp)

    class WNDCLASSW(C.Structure):
        _fields_ = [("style", WT.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", C.c_int), ("cbWndExtra", C.c_int),
                    ("hInstance", WT.HINSTANCE), ("hIcon", WT.HICON), ("hCursor", WT.HANDLE),
                    ("hbrBackground", WT.HBRUSH), ("lpszMenuName", WT.LPCWSTR), ("lpszClassName", WT.LPCWSTR)]
    hinst = k32.GetModuleHandleW(None)
    wc = WNDCLASSW(0x3, proc, 0, 0, hinst, None, u32.LoadCursorW(None, 32512), None, None, "NanoDS3Target")
    u32.RegisterClassW(C.byref(wc))
    pid = os.getpid()
    busy_name, quit_name = f"Local\\NanoD-S3-busy-{pid}", f"Local\\NanoD-S3-quit-{pid}"
    busy_event = k32.CreateEventW(None, False, False, busy_name)
    quit_event = k32.CreateEventW(None, True, False, quit_name)

    class MONITORINFO(C.Structure):
        _fields_ = [("cbSize", WT.DWORD), ("rcMonitor", WT.RECT), ("rcWork", WT.RECT), ("dwFlags", WT.DWORD)]
    pt = WT.POINT()
    u32.GetCursorPos(C.byref(pt))
    mon = u32.MonitorFromPoint(pt, 2)
    mi = MONITORINFO()
    mi.cbSize = C.sizeof(mi)
    u32.GetMonitorInfoW(mon, C.byref(mi))
    wl, wt_, wr, wb = mi.rcWork.left, mi.rcWork.top, mi.rcWork.right, mi.rcWork.bottom
    colours = (0x3060C0, 0x40A040, 0xC06030, 0x8040A0, 0x20A0A0, 0xA0A020, 0x606060, 0x2040E0, 0xE04080, 0x40E0C0)
    made = []
    lock = threading.Lock()

    def make(n, kind):
        w, h = 900, 600
        x = wl + 120 + 90 * n
        y = wt_ + 80 + 40 * n
        hwnd = u32.CreateWindowExW(0, "NanoDS3Target", f"NanoD S3 test window {n} ({kind})", 0x10CF0000,
                                   x, y, w, h, None, None, hinst, None)
        brushes[hwnd] = gdi.CreateSolidBrush(colours[n % len(colours)])
        cmd = {"maximized": 3, "minimized": 7}.get(kind, 4)            # SW_MAXIMIZE / SHOWMINNOACTIVE / SHOWNOACTIVATE
        u32.ShowWindow(hwnd, cmd)
        rect = WT.RECT()
        u32.GetWindowRect(hwnd, C.byref(rect))
        with lock:
            made.append({"n": n, "kind": kind, "hwnd": hwnd, "tid": k32.GetCurrentThreadId(),
                         "rect": [rect.left, rect.top, rect.right, rect.bottom]})
        return hwnd

    def pump_until(stop_handle, busy=None):
        msg = WT.MSG()
        handles = (WT.HANDLE * 2)(stop_handle, busy or stop_handle)
        end = time.monotonic() + TARGETS_LIFETIME_S
        while time.monotonic() < end:
            r = u32.MsgWaitForMultipleObjects(2 if busy else 1, handles, False, 50, 0x04FF)
            if r == 0:
                return
            if busy and r == 1:
                time.sleep(BUSY_STALL_S)                          # stop pumping: the busy target
            while u32.PeekMessageW(C.byref(msg), None, 0, 0, 1):
                u32.TranslateMessage(C.byref(msg))
                u32.DispatchMessageW(C.byref(msg))

    def side_thread(n, kind, busy=None, unaware=False):
        if unaware:
            try:
                u32.SetThreadDpiAwarenessContext(WT.HANDLE(-1))      # DPI_AWARENESS_CONTEXT_UNAWARE
            except Exception:
                pass
        make(n, kind)
        pump_until(quit_event, busy)

    try:
        u32.SetThreadDpiAwarenessContext(WT.HANDLE(-4))              # per-monitor v2 for the others
    except Exception:
        pass
    kinds = ["origin", "normal1", "normal2", "normal3", "normal4", "normal5", "maximized", "minimized"]
    for n, kind in enumerate(kinds):
        make(n, kind)
    threads = [threading.Thread(target=side_thread, args=(8, "unaware"), kwargs={"unaware": True}, daemon=True),
               threading.Thread(target=side_thread, args=(9, "busy"), kwargs={"busy": busy_event}, daemon=True)]
    for t in threads:
        t.start()
    deadline = time.monotonic() + 3.0
    while len(made) < 10 and time.monotonic() < deadline:
        time.sleep(0.01)
    print(json.dumps({"pid": pid, "busy_event": busy_name, "quit_event": quit_name,
                      "windows": sorted(made, key=lambda m: m["n"])}), flush=True)
    pump_until(quit_event)
    return 0


def _class_and_exstyle(hwnd):
    """The window class (not a title) and GWL_EXSTYLE: the snap worker's UWP rule reads them."""
    u32 = C.windll.user32
    buf = C.create_unicode_buffer(256)
    u32.GetClassNameW(WT.HWND(hwnd), buf, 256)
    get = getattr(u32, "GetWindowLongPtrW", None) or u32.GetWindowLongW
    get.restype = C.c_ssize_t
    get.argtypes = (WT.HWND, C.c_int)
    return buf.value, int(get(WT.HWND(hwnd), -20)) & 0xFFFFFFFF


def screen_items(targets, real_hwnds):
    """The snapshot items, with the native identity ids the snap pre-check compares."""
    from control_center import windows as W
    native = W.NativeWindows()
    items = []
    for w in targets.info["windows"]:
        ident = native.identity(w["hwnd"]) or {}
        cls, ex = _class_and_exstyle(w["hwnd"])
        items.append({"id": ident.get("id", f"s3-{w['n']}"), "hwnd": w["hwnd"],
                      "pid": ident.get("pid", targets.info["pid"]), "app": "NanoD S3", "title": f"Test window {w['n']}",
                      "available": True, "minimized": w["kind"] == "minimized", "class_name": cls, "exstyle": ex,
                      "_kind": w["kind"], "_rect": w["rect"]})
    from control_center import carousel as CR
    try:
        snap_native = CR.Win32SnapNative()
    except Exception:
        snap_native = None
    for i, hwnd in enumerate(real_hwnds):
        ident = native.identity(hwnd)
        if not ident:
            continue
        cls, ex = _class_and_exstyle(hwnd)
        elevated = None
        if snap_native is not None:
            try:
                elevated = snap_native.integrity_above_ours(hwnd)
            except Exception:
                elevated = None
        items.append({"id": ident["id"], "hwnd": hwnd, "pid": ident["pid"], "app": f"Real {i}",
                      "title": f"Real window {i}", "available": True, "minimized": bool(C.windll.user32.IsIconic(hwnd)),
                      "class_name": cls, "exstyle": ex, "_kind": classify_real(cls, elevated),
                      "_elevated": elevated})
    return native, items


def classify_real(class_name, elevated):
    """A --real-hwnd's S3 kind: ``elevated`` (integrity above ours), ``uwp`` (an
    ApplicationFrameWindow frame), else ``real``."""
    if elevated:
        return "elevated"
    if class_name == UWP_FRAME_CLASS:
        return "uwp"
    return "real"


def dry_items():
    """The helper's windows plus a stand-in UWP frame and an elevated window (the on-screen run
    takes those two from --real-hwnd)."""
    kinds = ["origin", "normal1", "normal2", "normal3", "normal4", "normal5", "maximized", "minimized", "unaware",
             "uwp", "elevated", "busy"]
    return [{"id": f"s3-{n}", "hwnd": 0x7000 + n, "pid": 4242, "app": f"App {n}", "title": f"Test window {n}",
             "available": True, "minimized": kind == "minimized",
             "class_name": UWP_FRAME_CLASS if kind == "uwp" else "NanoDS3Target", "exstyle": 0,
             "_kind": kind, "_elevated": kind == "elevated"} for n, kind in enumerate(kinds)]


# =========================================================================== remember and put back real windows
class WINDOWPLACEMENT(C.Structure):
    _fields_ = [("length", WT.UINT), ("flags", WT.UINT), ("showCmd", WT.UINT), ("ptMinPosition", WT.POINT),
                ("ptMaxPosition", WT.POINT), ("rcNormalPosition", WT.RECT)]


def remember(hwnds):
    u32 = C.windll.user32
    out = {}
    for hwnd in hwnds:
        wp = WINDOWPLACEMENT()
        wp.length = C.sizeof(wp)
        rect = WT.RECT()
        u32.GetWindowRect(WT.HWND(hwnd), C.byref(rect))
        u32.GetWindowPlacement(WT.HWND(hwnd), C.byref(wp))
        out[hwnd] = {"rect": [rect.left, rect.top, rect.right, rect.bottom], "iconic": bool(u32.IsIconic(hwnd)),
                     "zoomed": bool(u32.IsZoomed(hwnd))}
    return out


def put_back(saved):
    """Posted, non-activating: the saved window rect, then minimized again when it was."""
    u32 = C.windll.user32
    report = {}
    for hwnd, s in saved.items():
        l, t, r, b = s["rect"]
        if not s["iconic"] and not s["zoomed"]:
            u32.SetWindowPos(WT.HWND(hwnd), None, l, t, r - l, b - t, 0x4214)
        if s["iconic"]:
            u32.ShowWindowAsync(WT.HWND(hwnd), 7)                  # SW_SHOWMINNOACTIVE
        report[hex(hwnd)] = "left restored (was maximized; S5-32)" if s["zoomed"] else "put back"
    return report


# =========================================================================== runs
class Hog(threading.Thread):
    def __init__(self):
        super().__init__(name="picker-checks-hog", daemon=True)
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


def run_dry(args):
    """Headless: tour W twice and the S3 flow on the fakes. Checks: every snap resolved by
    t0 + 800 (the stalled one by the backstop as move_rejected), the pair close, the one-side
    completion, the latched Back."""
    chrome = getattr(args, "chrome", "gpu") or "gpu"
    d = DryDriver("cpu" if chrome == "cpu" else "gpu")
    out = {"mode": "dry", "chrome": chrome}
    problems = []
    try:
        wit = synthetic_alignment_check()
        out["alignment_analysis_selfcheck"] = wit
        if not wit["ok"]:
            problems.append(f"AR-12 witness analysis: {wit}")
        shown = displayed_frames_self_check()
        out["displayed_episodes_selfcheck"] = shown
        if not shown["ok"]:
            problems.append(f"displayed episodes (T1): {shown}")
        items = dry_items()
        d.elevated = {it["hwnd"] for it in items if it["_kind"] == "elevated"}
        for background in ("glass", "none"):
            w = tour_w(d, items, background)
            out[f"W_{background}"] = {"pass1": w["pass1"]["closed_by"], "pass2": w["pass2"]["closed_by"],
                                      "snaps": [(s["side"], s["result"], s["result_ms"]) for s in
                                                w["pass1"]["snaps"] + w["pass2"]["snaps"]]}
            # the verdict's plumbing on fake time (the numbers themselves only mean something on screen)
            verdict = frame_verdicts(w.get("metrics"), True, w.get("metrics_before"))
            out[f"W_{background}"]["verdict_plumbing"] = {k: verdict.get(k) for k in (
                "episode_frames", "compose_present_p95_ms", "compose_p95_ms", "budget_gate_ms")}
            if not verdict.get("episode_frames") or verdict.get("compose_present_p95_ms") is None \
                    or verdict.get("cpu_pct_one_core") is None:
                problems.append(f"W {background}: the verdict cannot read compose + present or the CPU")
            if chrome != "cpu":
                v3 = step3_verdicts(w.get("metrics"), w.get("metrics_before"))
                out[f"W_{background}"]["step3_plumbing"] = {k: v3.get(k) for k in (
                    "chrome", "normal_frames", "detent_frames", "normal_p95_ms", "detent_p95_ms", "gpu_fallbacks")}
                recent = (((w.get("metrics") or {}).get("frames") or {}).get("picker") or {}).get("recent")
                if v3.get("chrome") != "gpu" or not v3.get("normal_frames") or not v3.get("detent_frames") \
                        or not recent:
                    problems.append(f"W {background}: the GPU chrome did not draw the pass or its frames are missing")
            if w["pass1"]["closed_by"] != "pair":
                problems.append(f"W {background}: no pair close")
            if w["pass2"]["closed_by"] != "back":
                problems.append(f"W {background}: no Back close")
            for s in w["pass1"]["snaps"] + w["pass2"]["snaps"]:
                if s["result"] != "ok" or (s["result_ms"] or 1e9) > SNAP_DEADLINE_S * 1000 + 5:
                    problems.append(f"W {background}: snap {s['side']} -> {s['result']} at {s['result_ms']} ms")
        busy_index = next(i for i, it in enumerate(items) if it["_kind"] == "busy")
        s = s3(d, items, busy_index)
        out["S3"] = {"items": [(e["kind"], e["result"], e["closed_by"]) for e in s["items"]], "busy": s.get("busy"),
                     "coverage": s.get("coverage")}
        for e in s["items"]:
            if not e["ok"]:
                problems.append(f"S3 {e['kind']}: {e['result']} / {e['closed_by']} (expected {e['expected']})")
        if not (s.get("coverage") or {}).get("complete"):
            problems.append(f"S3 coverage: {s.get('coverage')}")
        # the pair closes raise toast.snap.pair; every completed Back raises toast.snap.one_side
        pairs = [t for t in d.toast_texts if t.startswith("Side by side · ")]
        one_side = [t for t in d.toast_texts if " left · " in t and t.endswith(" right")
                    and not t.startswith("Side by side")]
        if len(pairs) != 2 or len(one_side) != len(d.toast_texts) - len(pairs) or not one_side:
            problems.append(f"toast copy is not VOC toast.snap.pair / toast.snap.one_side: {d.toast_texts}")
        b = s.get("busy") or {}
        if b.get("result") != "move_rejected" or (b.get("result_ms") or 1e9) > SNAP_DEADLINE_S * 1000 + 5:
            problems.append(f"busy: {b.get('result')} at {b.get('result_ms')} ms")
        if not b.get("latched_ran"):
            problems.append("busy: the latched Back did not close the picker")
        out["toasts_accepted"] = d.toasts
        out["events"] = len(d.events)
    finally:
        d.close()
    out["problems"] = problems
    out["pass"] = not problems
    return (0 if not problems else 2), out


def run_onscreen(args):
    """The on-screen child (see the module docstring)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("stage_pacing_check", os.path.join(HERE, "stage_pacing_check.py"))
    pc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pc)
    disp = pc.display_usable()
    if not disp.get("usable"):
        print(json.dumps({"refused": "display asleep or session locked", "display": disp}))
        return 3, {"refused": disp}
    wd = pc.arm_native_watchdog(int(NATIVE_KILL_S * 1000))
    u32 = C.windll.user32
    u32.RegisterHotKey(None, ABORT_ID, MOD_CONTROL | MOD_ALT, VK_F12)
    C.windll.winmm.timeBeginPeriod(1)
    real = [int(h, 0) for h in args.real_hwnd or ()]
    saved = remember(real)
    out = {"mode": "onscreen", "stress": bool(args.stress), "started": datetime.datetime.now().isoformat()}
    code = 0
    presenter = targets = None
    hog = Hog() if args.stress else None
    fg_before = u32.GetForegroundWindow()
    try:
        targets = Targets()
        out["targets"] = [{k: w[k] for k in ("n", "kind", "rect")} for w in targets.info["windows"]]
        from control_center import carousel as CR
        native, items = screen_items(targets, real)
        chrome = args.chrome or "gpu"
        gpu = None
        if chrome != "cpu":
            from control_center.stage import picker_chrome as PCH
            gpu = PCH.factory()
            gpu.record_events = True                     # every chrome Commit's (t1, done): the pickup
        presenter = CR.CarouselPresenter(None, native, lambda: None, gpu_chrome=gpu if gpu is not None else False)
        if presenter.disabled:
            raise RuntimeError(f"the picker is unavailable: {presenter.last_error}")
        d = ScreenDriver(presenter, native, targets)
        if not d.arm_grant():
            raise RuntimeError("no free grant hotkey (F23, F22)")
        if hog:
            hog.start()
        layout_wide = None
        passes = [("glass", chrome != "cpu"), ("none", chrome != "cpu")]
        if chrome == "both":
            passes.append(("glass", False))
        for background, on_gpu in passes:
            presenter.set_chrome_mode("auto" if on_gpu else "cpu")
            key = f"W_{background}" + ("" if on_gpu or chrome == "cpu" else "_cpu")
            harvester = None
            t_from = time.perf_counter()
            if on_gpu:
                harvester = StatsHarvester()
                harvester.start()
                if gpu is not None:
                    gpu.events.clear()
            w = tour_w(d, items, background)
            layout = getattr(getattr(presenter, "_status", None), "layout", None)
            layout_wide = bool(getattr(layout, "wide", False)) if layout is not None else None
            if on_gpu:
                frames, unknown = harvester.stop()
                shown = displayed_frames(frames, unknown, w.get("metrics"), t_from)
                w["displayed"] = {k: v for k, v in shown.items() if k not in ("worst", "all")}
                w["displayed_worst_episode"] = shown.get("worst")
                w["displayed_episodes"] = shown.get("all")          # T1: all of them, with their gaps
                w["harvest"] = {"frames": len(frames), "unknown_ranges": len(unknown), "error": harvester.error}
                w["verdict"] = step3_verdicts(w.get("metrics"), w.get("metrics_before"), bool(args.stress), shown)
                if gpu is not None:
                    from control_center.stage import win32 as SW
                    pacer = (w.get("metrics") or {}).get("pacer") or {}
                    period_ticks = (pacer.get("period_ms") or 1000 / 60) / 1000.0 * SW.qpf()
                    w["chrome_pickup"] = chrome_pickup(list(gpu.events), frames, period_ticks)
            else:
                w["verdict"] = frame_verdicts(w.get("metrics"), layout_wide, w.get("metrics_before"),
                                              bool(args.stress))
            out[key] = w
        if hog:
            hog.stop = True
        if chrome != "cpu":
            presenter.set_chrome_mode("auto")
            out["AR12_alignment"] = alignment_pass(d, items, "glass")
        if not args.no_s3:
            busy_index = next((i for i, it in enumerate(items) if it["_kind"] == "busy"), None)
            out["S3"] = s3(d, items, busy_index)
        out["opens"] = d.opens
        touched = [o for o in d.opens if o.get("touched")]
        out["touch_then_show"] = {"opens": touched, "chrome": presenter.chrome if presenter is not None else None,
                                  "ok": bool(touched) and all((o.get("show_ms") or 1e9) < 150.0 for o in touched)}
        out["wide"] = layout_wide
        out["metrics"] = d.metrics()
        out["events"] = [(t, k, p) for t, k, p in d.events if k in ("snap_result", "complete_result", "closed",
                                                                    "system")]
    except KeyboardInterrupt as exc:
        out["aborted"] = str(exc)
        code = 5
    except Exception as exc:
        out["error"] = repr(exc)
        code = 6
    finally:
        if hog:
            hog.stop = True
        try:
            if presenter is not None:
                presenter.hide()
                presenter.close()
        finally:
            if targets is not None:
                targets.close()
            out["real_windows"] = put_back(saved)
            out["foreground_before_is_back"] = u32.GetForegroundWindow() == fg_before
            u32.UnregisterHotKey(None, ABORT_ID)
            u32.UnregisterHotKey(None, GRANT_ID)
            C.windll.winmm.timeEndPeriod(1)
            pc.disarm_native_watchdog(wd)
    return code, out


def run_runner(args):
    code, dry = run_dry(args)
    print(json.dumps({"dry_pass": dry["pass"], "problems": dry["problems"][:5]}), flush=True)
    if code != 0:
        print("dry run failed: nothing shown")
        return code, {"dry": dry}
    cmd = [sys.executable, "-I", os.path.abspath(__file__), "--child-onscreen", "--i-have-go-ahead",
           "--chrome", args.chrome or "gpu"]
    if args.stress:
        cmd.append("--stress")
    if args.no_s3:
        cmd.append("--no-s3")
    for h in args.real_hwnd or ():
        cmd += ["--real-hwnd", h]
    p = subprocess.Popen(cmd, cwd=ND)
    try:
        p.wait(timeout=RUNNER_KILL_S)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
    return p.returncode, {"dry": dry, "child_exit": p.returncode}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="headless: the fakes, nothing shown")
    g.add_argument("--run", action="store_true", help="the dry run, then one on-screen child")
    g.add_argument("--child-onscreen", action="store_true", help=argparse.SUPPRESS)
    g.add_argument("--child-targets", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--i-have-go-ahead", action="store_true")
    ap.add_argument("--stress", action="store_true")
    ap.add_argument("--no-s3", action="store_true", help="tour W only (moves only our own test windows)")
    ap.add_argument("--chrome", default="gpu", choices=("gpu", "cpu", "both"),
                    help="the picker's chrome: the GPU one (step 3, the default), the CPU one, or both")
    ap.add_argument("--real-hwnd", action="append", help="a real window to include in S3 (hex or decimal)")
    a = ap.parse_args(argv)
    if a.child_targets:
        return run_targets()
    if (a.run or a.child_onscreen) and not a.i_have_go_ahead:
        print("refusing: the on-screen checks need --i-have-go-ahead (the user's explicit OK, given in chat)")
        return 4
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    if a.dry_run:
        code, out = run_dry(a)
        print(json.dumps(out, default=str))
        return code
    if a.run:
        code, _out = run_runner(a)
        return code
    code, out = run_onscreen(a)
    os.makedirs(DIAG, exist_ok=True)
    path = os.path.join(DIAG, f"picker-snap-checks-{stamp}{'-stress' if a.stress else ''}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(path)
    return code


if __name__ == "__main__":
    sys.exit(main())
