"""Window picker v2 presenter (desktop v7: DESKTOP_STAGE.md sections 9, 10, 5, 6; CAROUSEL.md 12).

The picker stays on the v6 window stack (K4 S5-2): WindowsAdapter builds this presenter through
the module-global factory ``windows.PickerOverlay`` and drives it through the PickerOverlay
protocol (constructor ``(root, native, on_cancel)``, ``hwnd``, ``show(snapshot)``,
``focus_local()``, ``highlight(index, bump=0)``, ``set_icons(dict)``, ``hide()``, ``close()``)
plus ``rect`` (the stage's card area, physical px, from the show() handshake to the end of the
exit: the UI's 'carousel' suppression), ``set_labels(dict)``, ``set_background('glass'|'none')``,
``set_reduced_motion(bool)``, ``take_events()`` and the exits ``play_switch_exit()`` /
``play_cancel_exit()`` / ``play_pair_exit()`` (no toast of its own in v7: K3 raises
``toast.switch``, ``toast.snap.pair`` and ``toast.snap.one_side`` through the toast service).

New in v7 (K4 sections 9.2-9.9, 10):
- ``snap(request)``: the snap flow of K4 9.5. The pre-checks and the one placement run on the
  ``NanoD-snap`` worker (SnapWorker), which reaches a target window only through
  ``ShowWindowAsync(SW_SHOWNOACTIVATE / SW_SHOWMINNOACTIVE)`` and ``SetWindowPos`` with
  ``SWP_ASYNCWINDOWPOS`` (never SW_RESTORE, SetWindowPlacement, ShowWindow or a synchronous
  SetWindowPos; K4 9.6, VOC-D01) and resolves every job by a hard deadline (t0 + 800 ms; 600 ms
  for ``complete_one_side``). This thread arms the same deadline as a backstop. Events back:
  ``('snap_result', (side, outcome))`` with ``accepted`` first, then ``ok`` / ``move_rejected`` /
  ``cant_fit``, or at once ``hung`` / ``move_rejected``.
- ``complete_one_side(origin, side, rect)`` (U12, answered by ``('complete_result', (job,
  completed))``) and ``raise_window(hwnd)`` (the pair close's posted raise), both on NanoD-snap.
- ``half_rect(side)``: the picker monitor's rcWork half (K3's ``target_rect``).
- The tray (hidden until the first snap or snap failure, its spring reveal, slot fills,
  borders, the one-side preview, captions and failure states), the fly (a second DWM thumbnail
  of the snapped window: translate + uniform scale of its live rect, then a fade), the chip and
  the ``Snapped left/right`` suffix.
- ``toast(text, exit=False)``: the toast service (K4 10), lifted out of the picker session.
- Pacing per K4 5 (P2-P5, G1-2) and FrameStats per K4 6.2 (``metrics()['frames']``).

Step 3, the chrome on the GPU (K4 9.9 and 22 Q2; lead ruling R-h; CAROUSEL.md 12.4): when a GPU
chrome is installed (``install_gpu_chrome(factory)``: the stage package's ``picker_chrome``, handed
over by the one wiring point, ``standalone.py``; this module never names that package), every
open on the layered host draws its chrome (shadows, frame, shade, badges, chips, placeholder faces,
the label, the dots and marker, the tray, the fly's shadow) as DirectComposition visuals whose
animations the compositor runs: the engine mirrors the machine's tweens into them at each event
(``ChromeView``, one Commit), and per frame only steps the DWM thumbnails (GIL-keeping
``DwmUpdateThumbnailProperties``, batched, unchanged ones skipped). The chrome's window is a
click-through ``WS_EX_NOREDIRECTIONBITMAP`` layered window owned by the host (0x082800A8), so the
focus contract, the NOACTIVATE rules and capture exclusion are unchanged. The CPU chrome (the band,
B1-B5) stays as the fallback: ``set_chrome_mode('cpu')`` or ``NANOD_PICKER_CHROME=cpu``, the plain
host, a device that cannot be created, and device loss mid-open (the open continues on the CPU
chrome at once).

Layers (CarouselMachine, ToastMachine: pure state on one clock; CarouselEngine: NanoD-carousel
thread logic with an injected backend; Win32CarouselBackend: the only Win32 user of this
thread; CaptureWorker: NanoD-capture, the frost and the toast glass; LabelWorker: B1 label
sprites off the frame path; SnapWorker + Win32SnapNative: NanoD-snap; CarouselPresenter: the Tk
facade that records into the lock-protected Mailbox and posts).

Windows (created hidden at thread start and reused), bottom to top by ownership: Dim (No
background only) -> Glass (the frost, rcMonitor) -> Host (WS_POPUP, TOPMOST | TOOLWINDOW |
NOREDIRECTIONBITMAP, activatable, now rcMonitor: the destination of every thumbnail, the fly and
the tray slots included; it eats clicks anywhere) -> Chrome (the band, K4 9.2) -> Label and Dots
(B2: their own layered windows, uploaded only on change). The Toast is layered and unowned.

Thread boundary (the cc4 crash rule, windows.py): nothing on the NanoD-carousel, NanoD-capture,
NanoD-label or NanoD-snap threads imports or calls tkinter or the controller. Host input (Esc,
Enter, arrows, the wheel, a click on the centre card) and the results above are queued for the
Tk side and drained by ``adapter.pump()`` through ``take_events()``.

Focus contract (CAROUSEL.md section 1, kept by K4 9.1): when show() returns, ``hwnd`` is a
visible, activatable (never WS_EX_NOACTIVATE), top-level window of this process; the adapter's
native.focus(hwnd) follows synchronously. Right after the handshake the carousel thread only
starts the machine and the frost capture, then reads its queue until the host's WM_ACTIVATE (or
ACTIVATION_WAIT_S) before the open's heavy setup. Switch, Back and the pair close keep the
v6 order: focus moves first (in the adapter), then the exit plays; the host never activates
again during it. A click never re-activates the host while the foreground belongs to another
process.

Titles, labels and profile names are personal: nothing here logs them.
"""
from __future__ import annotations

import bisect
import ctypes as C
import itertools
import logging
import math
import os
import sys
import threading
import time
from collections import OrderedDict, deque, namedtuple

from . import carousel_render as R

__all__ = [
    "CarouselPresenter", "CarouselEngine", "CarouselMachine", "ToastMachine", "Win32CarouselBackend",
    "CaptureWorker", "LabelWorker", "SnapWorker", "SnapJob", "Win32SnapNative", "CarouselApi", "LoopPacer",
    "LoopStats", "Tween", "CubicBezier", "EASE_OUT", "EASE_IN", "EASE", "SPRING", "Mailbox", "ItemInfo",
    "OpenRequest", "Dismiss", "CaptureJob", "CaptureResult", "uses_placeholder", "self_test",
    "EPISODE_KINDS", "hist_quantile", "hist_delta", "LabelJob", "ToastJob", "install_gpu_chrome",
    "gpu_chrome_factory", "ChromeView", "ChromeCardInfo", "ChromeSlotInfo", "CHROME_MODES",
]

_LOGGER = logging.getLogger(__name__)
_LOGGER.addHandler(logging.NullHandler())


# ================================================================= easing + tweens
class CubicBezier:
    """CSS cubic-bezier(x1, y1, x2, y2): y for x in [0, 1], from a sampled x(t) table with
    linear interpolation (error well below 1e-3; fast enough for every card on every frame).
    y may leave [0, 1] (the spring overshoots)."""

    def __init__(self, x1, y1, x2, y2, samples=2048):
        self.params = (x1, y1, x2, y2)
        xs, ys = [], []
        for i in range(samples + 1):
            t = i / samples
            u = 1 - t
            xs.append(3 * u * u * t * x1 + 3 * u * t * t * x2 + t ** 3)
            ys.append(3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** 3)
        self._xs, self._ys = xs, ys

    def __call__(self, x):
        if x <= 0.0:
            return 0.0
        if x >= 1.0:
            return 1.0
        xs = self._xs
        i = bisect.bisect_left(xs, x)
        x0, x1 = xs[i - 1], xs[i]
        y0, y1 = self._ys[i - 1], self._ys[i]
        return y0 if x1 <= x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)


# K4 0.4: OUT (the default), IN (exits: the toast), SPR (the tray, the toast scale), EASE (CSS
# ease, only where App A is silent and BS says ease: slot border, empty glyph, slot badge, the
# cards group's close fade).
EASE_OUT = CubicBezier(0.22, 1, 0.36, 1)
EASE_IN = CubicBezier(0.4, 0, 1, 1)
SPRING = CubicBezier(0.34, 1.45, 0.64, 1)
EASE = CubicBezier(0.25, 0.1, 0.25, 1)


class Tween:
    """One animated value with CSS transition semantics: ``retarget`` starts a new transition
    from the current value to the target over the full duration; a target equal to the current
    one changes nothing (no restart), so fast turns retarget mid-flight and never queue (K4
    0.5 rule 4). Motion is a function of time only (P1): any frame rate samples the same curve."""
    __slots__ = ("start", "target", "t0", "duration", "ease")

    def __init__(self, value=0.0):
        self.start = self.target = float(value)
        self.t0 = None
        self.duration = 0.0
        self.ease = EASE_OUT

    def value(self, now):
        if self.t0 is None or self.duration <= 0.0:
            return self.target
        p = (now - self.t0) / self.duration
        if p >= 1.0 - 1e-9:
            return self.target
        if p <= 0.0:
            return self.start
        return self.start + (self.target - self.start) * self.ease(p)

    def retarget(self, target, now, duration, ease=EASE_OUT):
        target = float(target)
        if target == self.target:
            return False
        self.start = self.value(now)
        self.target = target
        self.t0 = now
        self.duration = float(duration)
        self.ease = ease
        return True

    def jump(self, value):
        self.start = self.target = float(value)
        self.t0 = None

    def done(self, now):
        return self.t0 is None or now - self.t0 >= self.duration - TIME_EPSILON


# ================================================================== timing (K4 9.8, App A S01:498-511)
OPEN_ROOT_S = 0.280        # root (frost/dim and everything on it) 0 -> 1, OUT; the close reverses it
ENTER_S = 0.420            # card enter: rise +24 S -> 0, scale 0.92 -> 1 (x S), opacity 0 -> table (S5-5), OUT
ENTER_RISE, ENTER_SCALE = 24.0, 0.92
MOVE_S = 0.420             # turn: X, S
FADE_S = 0.300             # turn: card opacity
SHADE_S = 0.320            # turn: #111 shade (OUT, S5-5)
FRAME_S = 0.320            # the selection frame and the shadow crossfade
MARKER_S = 0.420
LABEL_FADE_S = 0.160       # the label swaps at the detent, then fades in
BUMP_S = 0.160             # end stop: 0 -> -12 dir over 160, then back over 160 (S5-8, S5-31)
BUMP_PX = 12.0
TRAY_SPRING_S = 0.460      # first snap: tray translateY -14 -> 0, scale 0.94 -> 1 (SPR)
TRAY_FADE_S = 0.260        # ... opacity 0 -> 1 (OUT)
TRAY_RISE, TRAY_SCALE0 = -14.0, 0.94
SHIFT_S = 0.460            # ... the cards group translateY -44 -> 0 (OUT)
SLOT_FILL_S = 0.260        # slot fill 0 -> 1 (OUT); the one-side preview too
SLOT_BORDER_S = 0.260      # border crossfades (EASE, S5-8)
SLOT_GLYPH_S = 0.200       # empty glyph (EASE)
SLOT_BADGE_S = 0.260       # slot badge (EASE)
FLY_S = 0.460              # the fly: translate + uniform scale (OUT)
FLY_FADE_AT, FLY_FADE_S = 0.380, 0.220   # opacity 1 -> 0 from 380 ms (OUT)
FLY_RELEASE_S = 0.600      # the fly thumbnail is unregistered at 600 ms
CLOSE_GROUP_S = 0.220      # close: the cards group 1 -> 0 (EASE); the root 280 OUT
RM_FADE_S = 0.200          # reduced motion: every card opacity change (K4 16)
FAILURE_S = 2.400          # a slot's failure state (K4 9.4; VOC fail_meta)
# An exit ends when everything visible has reached 0: the root (280 ms) and the cards group
# (220 ms). No Switch grow in v7 (S5-6).
EXIT_S = {"switch": OPEN_ROOT_S, "cancel": OPEN_ROOT_S, "pair": OPEN_ROOT_S}
# The toast (K4 10.2): in, translateY +8 -> 0 and opacity 0 -> 1 over 260 OUT, scale 0.96 -> 1
# over 420 SPR; out, opacity 1 -> 0 over 200 IN (no movement) 1800 ms after the show.
TOAST_IN_S = 0.260
TOAST_SCALE_S = 0.420
TOAST_HOLD_S = 1.8
TOAST_OUT_S = 0.200
TOAST_RISE = 8.0
TOAST_SCALE0 = 0.96
EXIT_TOAST_DELAY_S = 0.360  # an exit toast shows at max(t_close + 360 ms, t_request) (K4 10.3)
LABEL_CACHE = 10                  # B1: more than 6 label sprites kept (the selection and +-3 prefetched)
LABEL_PREFETCH = 3
SPRITE_CACHE = 48                 # icon sprites kept (badge, placeholder, slot badge per nearby card)
ACTIVATION_WAIT_S = 0.040         # after the handshake: read the queue until the host is activated
PLAIN_FALLBACK_ATTEMPTS = 3       # an open with at least this many registrations, all failed ...
PLAIN_FALLBACK_OPENS = 2          # ... this many opens in a row -> the plain host (CAR section 5)
PLAIN_RETRY_S = 1800.0            # the plain host tries the layered one again after this (doubling)
PLAIN_RETRY_MAX_S = 86400.0
CAPTURE_TIMEOUT_S = 0.500         # the frost: fall back to the tint without a capture
TOAST_CAPTURE_TIMEOUT_S = 0.150
SHOW_TIMEOUT_S = 0.150            # show()'s handshake bound (CAR section 1)
START_TIMEOUT_S = 2.0
CLOSE_TIMEOUT_S = 1.0
WHEEL_DELTA = 120
LOG_INTERVAL_S = 30.0
TIME_EPSILON = 1e-9
# The snap recipe (K4 9.6; VOC 10 timers).
SNAP_PLACE_S = 0.360              # the real window moves once at t0 + 360
SNAP_DEADLINE_S = 0.800           # SNAP_DEADLINE_MS: a snap job resolves by t0 + 800
ONE_SIDE_DEADLINE_S = 0.600       # ONE_SIDE_DEADLINE_MS: complete_one_side by its start + 600
RESTORE_POLL_S, RESTORE_LIMIT_S = 0.010, 0.150
VERIFY_POLL_S, VERIFY_S, VERIFY_UWP_S = 0.020, 0.200, 0.400
MATCH_PX = 2
T0_TRUST_S = 5.0                  # a t0 further than this from now is taken as now (a clock mix-up)
GPU_PREWARM_STEP_S = 0.002        # the GPU chrome's segment-table warm-up: one idle step's budget ...
GPU_PREWARM_GAP_S = 0.004         # ... and the idle wait between steps (an idle-path wait, P9)

# op: the effective opacity (root, cards group, closed factor); cover: the card's own opacity
# inside the group (closed factor included, group fades excluded), which decides how much of the
# farther cards shows through it (CSS applies the group's opacity to the composited row);
# y: the card's vertical offset in units (the cards group's shift plus the open's rise x S).
CardFrame = namedtuple("CardFrame", "index d x s op shade selw closed cover y")
SlotFrame = namedtuple("SlotFrame", "fill ghost glyph badge borders")
Frame = namedtuple("Frame", "cards root group glass dim bump shift tray_op tray_y tray_sc marker label_alpha "
                            "exit slots")


class _CardTweens:
    __slots__ = ("x", "s", "op", "shade", "selw", "rise", "escale")

    def __init__(self, d, wide=False):
        x, s, op, shade = R.table_state(d, wide)
        self.x, self.s, self.op, self.shade = Tween(x), Tween(s), Tween(op), Tween(shade)
        self.selw = Tween(1.0 if d == 0 else 0.0)
        self.rise, self.escale = Tween(0.0), Tween(1.0)

    def tweens(self):
        return (self.x, self.s, self.op, self.shade, self.selw, self.rise, self.escale)

    def retarget(self, d, now, wide=False, rm=False):
        x, s, op, shade = R.table_state(d, wide)
        if rm:
            self.x.jump(x)
            self.s.jump(s)
            self.op.retarget(op, now, RM_FADE_S)
        else:
            self.x.retarget(x, now, MOVE_S)
            self.s.retarget(s, now, MOVE_S)
            self.op.retarget(op, now, FADE_S)
        self.shade.retarget(shade, now, SHADE_S)
        self.selw.retarget(1.0 if d == 0 else 0.0, now, FRAME_S)


class _SlotTweens:
    """One tray slot's looks (K4 9.4): the fill fade, the one-side preview (0.35), the empty glyph,
    the badge and the three border looks (crossfaded)."""
    __slots__ = ("fill", "ghost", "glyph", "badge", "borders")

    def __init__(self):
        self.fill, self.ghost, self.glyph, self.badge = Tween(0.0), Tween(0.0), Tween(1.0), Tween(0.0)
        self.borders = {"empty": Tween(1.0), "filled": Tween(0.0), "failure": Tween(0.0)}

    def tweens(self):
        return (self.fill, self.ghost, self.glyph, self.badge) + tuple(self.borders.values())

    def set(self, filled, keep, failure, now):
        self.fill.retarget(1.0 if filled else 0.0, now, SLOT_FILL_S)
        self.ghost.retarget(R.KEEP_OPACITY if keep and not filled else 0.0, now, SLOT_FILL_S)
        self.glyph.retarget(0.0 if filled or keep else 1.0, now, SLOT_GLYPH_S, EASE)
        self.badge.retarget(1.0 if filled else 0.0, now, SLOT_BADGE_S, EASE)
        look = "failure" if failure else "filled" if filled else "empty"
        for kind, tween in self.borders.items():
            tween.retarget(1.0 if kind == look else 0.0, now, SLOT_BORDER_S, EASE)

    def values(self, now):
        return SlotFrame(self.fill.value(now), self.ghost.value(now), self.glyph.value(now), self.badge.value(now),
                         {kind: tween.value(now) for kind, tween in self.borders.items()})


class CarouselMachine:
    """Pure picker state (K4 9.3-9.8): the order's size, ``sel``, ``is_open``, the table
    (``wide``), reduced motion (``rm``, latched at open), the exit, the end bump, the tray and its
    slots, and per-card tweens: the open's enter (rise +24 S -> 0, scale 0.92 -> 1, opacity 0 ->
    table, 420 ms OUT), turns (X and S 420 ms, opacity 300 ms, shade 320 ms, frame and shadow
    crossfade 320 ms, OUT), the root (280 ms OUT), the cards group's shift (-44 -> 0 over 460 ms OUT
    at the first snap) and close fade (220 ms EASE), the marker (420 ms OUT) and the label fade
    (160 ms OUT). Cards live lazily around the selection; a card never touched rests in its table
    state. Reduced motion (K4 16): cards jump, opacities 200 ms OUT, no enter offsets, no bump,
    the tray fades only, the group shift and the marker jump."""

    def __init__(self):
        self.count = 0
        self.sel = 0
        self.is_open = False
        self.wide = False
        self.rm = False
        self.exit_kind = None
        self.exit_t0 = None
        self.exit_index = None
        self.closed = frozenset()
        self.glass_ready = False
        self.cards = {}
        self.root, self.group, self.glass = Tween(0.0), Tween(1.0), Tween(0.0)
        self.shift = Tween(R.GROUP_SHIFT)
        self.tray_on = False
        self.tray_op, self.tray_y, self.tray_sc = Tween(0.0), Tween(TRAY_RISE), Tween(TRAY_SCALE0)
        self.marker = Tween(0.0)
        self.label_alpha = Tween(0.0)
        self.bump_x = Tween(0.0)
        self._bump_back = None
        self.slots = {"left": _SlotTweens(), "right": _SlotTweens()}

    # ------------------------------------------------------------ state
    @property
    def a_max(self):
        return len(R.table_for(self.wide)) - 1

    @property
    def switching(self):
        return self.exit_kind == "switch"

    @property
    def cancelling(self):
        return self.exit_kind == "cancel"

    @property
    def bump(self):
        """-1, 0 or +1: the direction of a running end bump."""
        target = self.bump_x.target
        return 0 if self._bump_back is None and target == 0.0 else (1 if target < 0 else -1 if target > 0 else 0)

    def _card(self, index, sel=None):
        card = self.cards.get(index)
        if card is None:
            card = self.cards[index] = _CardTweens(index - (self.sel if sel is None else sel), self.wide)
        return card

    def marker_slot(self, sel=None):
        """The marker's dot slot for ``sel`` (the dots window, S5-9)."""
        sel = self.sel if sel is None else sel
        first = R.dots_window(self.count, sel)[0]
        return float(sel - first)

    def start(self, count, sel, now, closed=(), wide=False, rm=False):
        """Open: the root fades in over 280 ms; every card enters (unless ``rm``) with the rise, the
        enter scale and its opacity from 0 over 420 ms, with no stagger; the group sits 44 units
        up with the tray hidden; the frost waits for set_glass_ready()."""
        self.count = max(0, int(count))
        self.sel = max(0, min(int(sel), self.count - 1)) if self.count else 0
        self.wide, self.rm = bool(wide), bool(rm)
        self.is_open = True
        self.exit_kind = self.exit_t0 = self.exit_index = None
        self.closed = frozenset(int(i) for i in closed)
        self.glass_ready = False
        self.cards = {}
        reach = self.a_max + 1
        for i in range(max(0, self.sel - reach), min(self.count, self.sel + reach + 1)):
            card = self._card(i)
            target = card.op.target
            card.op.jump(0.0)
            if self.rm:
                card.op.retarget(target, now, RM_FADE_S)
            else:
                card.op.retarget(target, now, ENTER_S)
                card.rise.jump(ENTER_RISE)
                card.rise.retarget(0.0, now, ENTER_S)
                card.escale.jump(ENTER_SCALE)
                card.escale.retarget(1.0, now, ENTER_S)
        self.root.jump(0.0)
        self.root.retarget(1.0, now, OPEN_ROOT_S)
        self.group.jump(1.0)
        self.glass.jump(0.0)
        self.shift.jump(R.GROUP_SHIFT)
        self.tray_on = False
        self.tray_op.jump(0.0)
        self.tray_y.jump(TRAY_RISE)
        self.tray_sc.jump(TRAY_SCALE0)
        self.marker.jump(self.marker_slot())
        self.label_alpha.jump(0.0)
        self.bump_x.jump(0.0)
        self._bump_back = None
        self.slots = {"left": _SlotTweens(), "right": _SlotTweens()}

    def reset(self):
        self.__init__()

    def select(self, sel, now):
        """Retarget every card whose table state changes (mid-flight, never queued) and the
        marker. The label swap is the engine's (it waits for the sprite, S5-24)."""
        if not self.is_open or self.exit_kind or not self.count:
            return False
        sel = max(0, min(int(sel), self.count - 1))
        old = self.sel
        if sel == old:
            return False
        reach = self.a_max + 1
        for i in range(max(0, min(old, sel) - reach), min(self.count, max(old, sel) + reach + 1)):
            self._card(i, old).retarget(i - sel, now, self.wide, self.rm)
        self.sel = sel
        slot = self.marker_slot()
        if self.rm:
            self.marker.jump(slot)
        else:
            self.marker.retarget(slot, now, MARKER_S)
        return True

    def label_swap(self, now):
        """The label changed: opacity 0, then 0 -> 1 over 160 ms OUT (kept under reduced motion)."""
        self.label_alpha.jump(0.0)
        self.label_alpha.retarget(1.0, now, LABEL_FADE_S)

    def set_closed(self, indices):
        self.closed = frozenset(int(i) for i in indices)

    def can_switch(self):
        return self.is_open and not self.exit_kind and 0 <= self.sel < self.count and self.sel not in self.closed

    def at_end(self, direction):
        """True when a turn in ``direction`` would leave the list (no wrap)."""
        target = self.sel + (1 if direction > 0 else -1)
        return target < 0 or target >= self.count

    def bump_now(self, direction, now):
        """The end bump: the cards container nudges 12 units against the turn (0 -> -12 dir) over
        160 ms OUT, then back from +160 ms over 160 ms OUT (S5-8, S5-31); none under reduced
        motion. Keys, the wheel and the knob's ``lim`` (K3 ``bump``)."""
        if not self.is_open or self.exit_kind or self.rm:
            return False
        self.bump_x.retarget(-BUMP_PX * (1 if direction > 0 else -1), now, BUMP_S)
        self._bump_back = now + BUMP_S
        return True

    def reveal_tray(self, now):
        """The first snap or snap failure: the tray springs in (translateY -14 -> 0 and scale 0.94
        -> 1 over 460 ms SPR, opacity over 260 ms OUT) and the cards group moves -44 -> 0 over
        460 ms OUT. Reduced motion: the tray fades only and the group jumps. Once per open."""
        if self.tray_on or not self.is_open:
            return False
        self.tray_on = True
        self.tray_op.retarget(1.0, now, TRAY_FADE_S)
        if self.rm:
            self.tray_y.jump(0.0)
            self.tray_sc.jump(1.0)
            self.shift.jump(0.0)
        else:
            self.tray_y.retarget(0.0, now, TRAY_SPRING_S, SPRING)
            self.tray_sc.retarget(1.0, now, TRAY_SPRING_S, SPRING)
            self.shift.retarget(0.0, now, SHIFT_S)
        return True

    def set_slot(self, side, filled, keep, failure, now):
        self.slots[side].set(filled, keep, failure, now)

    def set_glass_ready(self, now):
        self.glass_ready = True
        if self.is_open and not self.exit_kind:
            self.glass.retarget(1.0, now, OPEN_ROOT_S)

    def start_exit(self, kind, now):
        """'switch', 'cancel' or 'pair': the root 1 -> 0 over 280 ms OUT (the frost too) and the
        cards group 1 -> 0 over 220 ms EASE; no card motion (no Switch grow, S5-6)."""
        if not self.is_open or self.exit_kind:
            return False
        self.exit_kind = kind if kind in EXIT_S else "cancel"
        self.exit_t0 = now
        self.exit_index = self.sel
        self.root.retarget(0.0, now, OPEN_ROOT_S)
        self.glass.retarget(0.0, now, OPEN_ROOT_S)
        self.group.retarget(0.0, now, CLOSE_GROUP_S, EASE)
        self._bump_back = None
        self.bump_x.retarget(0.0, now, BUMP_S)
        return True

    def exit_done(self, now):
        return self.exit_kind is not None and now - self.exit_t0 >= EXIT_S[self.exit_kind] - TIME_EPSILON

    # ------------------------------------------------------------ values
    def _step_bump(self, now):
        if self._bump_back is not None and now >= self._bump_back:
            self.bump_x.retarget(0.0, self._bump_back, BUMP_S)
            self._bump_back = None

    def values(self, now):
        """The Frame at ``now``. ``op`` includes the root, the cards group and the closed (35 %)
        factor; ``cover`` is the card's own opacity (without the group fades)."""
        self._step_bump(now)
        root = self.root.value(now)
        group = self.group.value(now)
        shift = self.shift.value(now)
        cards = []
        stale = []
        reach = self.a_max + 1
        for index in sorted(self.cards):
            card = self.cards[index]
            closed = index in self.closed
            own = card.op.value(now) * (R.CLOSED_OPACITY if closed else 1.0)
            eff = own * root * group
            d = index - self.sel
            s = card.s.value(now)
            if eff > 0.001:
                cards.append(CardFrame(index, d, card.x.value(now), s * card.escale.value(now), eff,
                                       card.shade.value(now), card.selw.value(now), closed, own,
                                       shift + card.rise.value(now) * s))
            elif abs(d) > reach and all(t.done(now) for t in card.tweens()):
                stale.append(index)
        for index in stale:
            del self.cards[index]
        slots = {side: slot.values(now) for side, slot in self.slots.items()}
        return Frame(cards, root, group, self.glass.value(now), root, self.bump_x.value(now), shift,
                     self.tray_op.value(now), self.tray_y.value(now), self.tray_sc.value(now),
                     self.marker.value(now), self.label_alpha.value(now), self.exit_kind, slots)

    def animating(self, now):
        if self._bump_back is not None:
            return True
        if self.exit_kind is not None and not self.exit_done(now):
            return True
        for tween in (self.root, self.group, self.glass, self.bump_x, self.shift, self.tray_op, self.tray_y,
                      self.tray_sc, self.marker, self.label_alpha):
            if not tween.done(now):
                return True
        for card in self.cards.values():
            for tween in card.tweens():
                if not tween.done(now):
                    return True
        for slot in self.slots.values():
            for tween in slot.tweens():
                if not tween.done(now):
                    return True
        return False


class ToastMachine:
    """The toast (K4 10.2): in, opacity 0 -> 1 and translateY +8 -> 0 over 260 ms OUT while the
    scale springs 0.96 -> 1 over 420 ms SPR; it holds, then fades out (opacity only) over 200 ms
    IN 1800 ms after the show: 2000 ms in all. ``replace`` swaps the text at once and restarts
    the 1800 ms hold with no new entry motion (BS:770-774). Reduced motion: no translate, no scale
    (opacity 260 OUT in, 200 IN out)."""

    def __init__(self):
        self.t0 = None
        self.out_at = None
        self.rm = False
        self.opacity = Tween(0.0)
        self.rise = Tween(0.0)
        self.scale = Tween(1.0)

    def start(self, now, rm=False):
        self.t0 = now
        self.rm = bool(rm)
        self.out_at = now + TOAST_HOLD_S
        self.opacity.jump(0.0)
        self.opacity.retarget(1.0, now, TOAST_IN_S)
        if self.rm:
            self.rise.jump(0.0)
            self.scale.jump(1.0)
        else:
            self.rise.jump(TOAST_RISE)
            self.rise.retarget(0.0, now, TOAST_IN_S)
            self.scale.jump(TOAST_SCALE0)
            self.scale.retarget(1.0, now, TOAST_SCALE_S, SPRING)

    def replace(self, now):
        """A new text while showing: the hold restarts; an exit fade under way turns back."""
        if self.t0 is None:
            self.start(now)
            return
        self._step(now)
        self.out_at = now + TOAST_HOLD_S
        if self.opacity.target < 1.0:
            self.opacity.retarget(1.0, now, TOAST_IN_S)

    @property
    def started(self):
        return self.t0 is not None

    def _step(self, now):
        if self.out_at is not None and now >= self.out_at and self.opacity.target > 0.0:
            self.opacity.retarget(0.0, self.out_at, TOAST_OUT_S, EASE_IN)

    def values(self, now):
        """(opacity 0..1, rise in design px (8 -> 0), scale)."""
        self._step(now)
        return self.opacity.value(now), self.rise.value(now), self.scale.value(now)

    def done(self, now):
        self._step(now)
        return (self.t0 is not None and self.opacity.target == 0.0 and now >= self.out_at + TOAST_OUT_S - TIME_EPSILON)

    def next_wait(self, now):
        if self.t0 is None:
            return None
        self._step(now)
        if not self.opacity.done(now) or not self.rise.done(now) or not self.scale.done(now):
            return 0.0
        if self.opacity.target > 0.0:
            return max(0.0, self.out_at - now)
        return max(0.0, self.out_at + TOAST_OUT_S - now)


# ================================================================== pacing (K4 5.1 P2-P5, G1-2)
def quantile(sorted_values, p):
    """Nearest-rank quantile (the G1 spike's method)."""
    n = len(sorted_values)
    return sorted_values[min(n - 1, max(0, int(math.ceil(p * n)) - 1))] if n else None


class LoopPacer:
    """Pacing for the carousel's Python-stepped loop (the picker's thumbnails and chrome, the
    toast), in seconds of the one clock (QPC via ``time.perf_counter``).

    - P2 ``target(now)``: the predicted display time ``vblank + n P`` with n the smallest integer
      such that it is at least ``now`` + the work p95 over the last 0.5 s; under the 120 lock,
      every second vblank and at least 2 P ahead.
    - P3 ``wait()``: the compositor clock (``DCompositionWaitForCompositorClock`` with the thread's
      mailbox event among the handles), else DwmFlush, else one P on a high-resolution waitable
      timer. G1-2: any other return than a tick or a handle means "no clock": one P on the timer,
      never a loop on the call; with the display off it returns at once ("display_off").
    - P4 ``judge``: a wake is pacing when it returns at least 0.5 P after the previous one (the v6
      fast-flush heuristic is gone).
    - P5 ``frame_done``: lock to every second vblank when the work p95 exceeds 0.8 P; unlock after
      0.5 s below 0.6 P; ``switches`` counts the cadence changes. P1 of the 2026-09-26 frame-drop
      fixes (the on-screen tour W: one 13-16 ms setup frame locked every open at 120, about 1 s
      each, and the detent frames kept it): a ``oneoff`` frame (an open's setup, the frost's
      upload, the chrome's warm-up adoption) is not a loop frame and is recorded nowhere; a frame
      with ``p5=False`` (the GPU chrome's detent frames, whose own budget is 3.0 ms, §6.3) feeds
      P2's estimate only; and the lock engages only once the loop has run for ``LOCK_MIN_SPAN_S``
      (a quarter second at any rate) and at least ``LOCK_MIN_OVER`` frames of P5's window are
      over 0.8 P (with fewer than 20 frames the nearest-rank p95 is the worst frame, so one slow
      frame alone never locks). A pause of more than ``run_gap()`` between two loop frames (the
      loop idled) starts a new run and empties P5's window: frames from before the pause never
      lock the next run. (The first form of P1 counted 60 frames, which a 0.5 s window cannot
      hold at 60 Hz, nor at 240 Hz once the work is over 2 P: the lock could never engage exactly
      when it was meant to; CAROUSEL.md §12.5 E-P1.)

    ``timing()`` -> (qpcVBlank seconds, period seconds) or None; ``clock_wait(handles,
    timeout_ms)`` -> ("tick" | "handle" | "timeout" | "no_clock" | "display_off", index);
    ``timer_wait(handles, seconds)``; ``flush()``. All injectable (tests and other platforms)."""

    WINDOW_S = 0.5
    LOCK_AT, UNLOCK_BELOW = 0.8, 0.6
    LOCK_MIN_SPAN_S = 0.25             # P1: the loop has run this long before P5 may lock (any rate)
    LOCK_MIN_OVER = 2                  # P1: and this many frames of the window are over 0.8 P
    RUN_GAP_S = 0.1                    # P1: a longer pause between loop frames (at least 6 P) is idle
    DEFAULT_PERIOD = 1 / 60

    def __init__(self, clock=time.perf_counter, timing=None, clock_wait=None, timer_wait=None, flush=None,
                 display_on=None, handles=()):
        self.clock = clock
        self._timing = timing
        self._clock_wait = clock_wait
        self._timer_wait = timer_wait
        self._flush = flush
        self._display_on = display_on
        self.handles = tuple(handles)
        self.cadence = 1
        self.switches = 0
        self.work = deque()            # (t, work seconds): P2's estimate
        self.lock_work = deque()       # (t, work seconds): P5's window (P1: without the p5=False frames)
        self.oneoff_frames = 0
        self.run_start = None          # P1: the first frame of the current run (after idle)
        self.runs = 0
        self._last_frame = None
        self.below_since = None
        self.last_return = None
        self.late_wakes = 0
        self.counts = {"tick": 0, "handle": 0, "timeout": 0, "no_clock": 0, "display_off": 0, "flush": 0,
                       "timer": 0}
        self._period = None
        self._vblank = None
        self._idle = threading.Event()

    def refresh(self):
        """Re-read P (on WM_DISPLAYCHANGE, K4 0.6) and the last vblank."""
        info = None
        if self._timing is not None:
            try:
                info = self._timing()
            except Exception:
                info = None
        if info:
            self._vblank, period = info
            if period and period > 0:
                self._period = float(period)
        return self._period

    @property
    def period(self):
        return self._period or self.DEFAULT_PERIOD

    def _p95(self, window, now):
        cut = now - self.WINDOW_S
        while window and window[0][0] < cut:
            window.popleft()
        values = sorted(w for _, w in window)
        return quantile(values, 0.95) if values else 0.0

    def work_p95(self, now):
        return self._p95(self.work, now)

    def target(self, now):
        """P2 (see the class docstring); ``now`` when no timing is available."""
        self.refresh()
        if self._vblank is None:
            return now
        period = self.period
        need = now + self.work_p95(now)
        step = period * self.cadence
        vblank = float(self._vblank)
        n = math.ceil((need - vblank) / step) if need > vblank else 0
        t = vblank + n * step
        if self.cadence == 2 and t - now < 2 * period:
            t += step
        return t

    def judge(self, t_return):
        """P4: True when this wake is at least 0.5 P after the previous one."""
        ok = self.last_return is None or (t_return - self.last_return) >= 0.5 * self.period
        if not ok:
            self.late_wakes += 1
        self.last_return = t_return
        return ok

    def run_gap(self):
        """P1: the pause between two loop frames that ends a run (the loop idled): RUN_GAP_S, at
        least 6 P (longer than any paced interval, 3 P under the 120 lock with work over 2 P)."""
        return max(self.RUN_GAP_S, 6.0 * self.period)

    def lock_ready(self, t_wake):
        """P1: the loop has run for LOCK_MIN_SPAN_S and P5's window holds LOCK_MIN_OVER frames over
        0.8 P (the p95 of a short window is its worst frame)."""
        if self.run_start is None or t_wake - self.run_start < self.LOCK_MIN_SPAN_S - 1e-9:
            return False
        bar = self.LOCK_AT * self.period
        return sum(1 for _t, w in self.lock_work if w > bar) >= self.LOCK_MIN_OVER

    def frame_done(self, t_wake, work_s, *, oneoff=False, p5=True):
        """Record a frame's work and apply P5's hysteresis; returns the cadence for the next one.
        ``oneoff`` and ``p5``: P1 (the class docstring)."""
        if self._last_frame is None or t_wake - self._last_frame > self.run_gap():
            self.run_start = t_wake                 # P1: a new run (the first frame, or after idle)
            self.runs += 1
            self.lock_work.clear()                  # frames from before the pause never lock this run
        self._last_frame = t_wake
        if oneoff:
            self.oneoff_frames += 1
            return self.cadence
        self.work.append((t_wake, float(work_s)))
        if p5:
            self.lock_work.append((t_wake, float(work_s)))
        p95 = self._p95(self.lock_work, t_wake)
        period = self.period
        if self.cadence == 1 and p95 > self.LOCK_AT * period and self.lock_ready(t_wake):
            self.cadence = 2
            self.switches += 1
            self.below_since = None
        elif self.cadence == 2:
            if p95 < self.UNLOCK_BELOW * period:
                if self.below_since is None:
                    self.below_since = t_wake
                elif t_wake - self.below_since >= self.WINDOW_S:
                    self.cadence = 1
                    self.switches += 1
                    self.below_since = None
            else:
                self.below_since = None
        return self.cadence

    def _one_wait(self):
        display_on = self._display_on
        if display_on is not None:
            try:
                if not display_on():
                    self.counts["display_off"] += 1
                    return "display_off"
            except Exception:
                pass
        if self._clock_wait is not None:
            kind, _index = self._clock_wait(self.handles, max(1, int(math.ceil(self.period * 4000))))
            if kind in ("tick", "handle", "timeout"):
                self.counts[kind] += 1
                return kind
            # 0xC01E0006 while the display sleeps, WAIT_FAILED, anything else (G1-2)
            self.counts["no_clock"] += 1
            if display_on is not None:
                try:
                    if not display_on():
                        self.counts["display_off"] += 1
                        return "display_off"
                except Exception:
                    pass
        elif self._flush is not None:
            try:
                ok = self._flush() == 0
            except Exception:
                ok = False
            if ok:
                self.counts["flush"] += 1
                return "tick"
        if self._timer_wait is not None:
            self.counts["timer"] += 1
            self._timer_wait(self.handles, self.period)
            return "timer"
        self._idle.wait(self.period)   # the last resort without native waits (tests, other platforms)
        return "timer"

    def wait(self):
        """P3/P5: wait for the next vblank to present on (two under the 120 lock)."""
        kind = self._one_wait()
        if self.cadence == 2 and kind in ("tick", "timer"):
            kind = self._one_wait()
        self.judge(self.clock())
        return kind


EPISODE_KINDS = ("open", "turn", "switch", "shuffle", "play", "close", "snap", "slide", "ring", "toast")
HIST_BIN_MS = 0.1                        # the pooled per-frame histograms: 0.1 ms bins ...
HIST_TOP_MS = 100.0                      # ... up to 100 ms (the last bin holds everything above)


def _summary(values):
    """{p95, max} of a list of ms values (None when empty)."""
    if not values:
        return None
    values = sorted(values)
    return {"p95": round(quantile(values, 0.95), 3), "max": round(values[-1], 3)}


def hist_add(hist, value_ms):
    """Count ``value_ms`` in a sparse histogram {bin: count} of HIST_BIN_MS bins."""
    top = int(HIST_TOP_MS / HIST_BIN_MS)
    b = min(top, max(0, int(value_ms / HIST_BIN_MS)))
    hist[b] = hist.get(b, 0) + 1


def hist_quantile(hist, p):
    """The ``p`` quantile (nearest rank) of a sparse histogram, as the bin's upper edge in ms: an
    upper bound within HIST_BIN_MS. Keys may be ints or the strings JSON makes of them."""
    counts = sorted((int(b), int(n)) for b, n in (hist or {}).items() if int(n) > 0)
    total = sum(n for _, n in counts)
    if not total:
        return None
    rank = max(1, int(math.ceil(p * total)))
    seen = 0
    for b, n in counts:
        seen += n
        if seen >= rank:
            return round((b + 1) * HIST_BIN_MS, 3)
    return round((counts[-1][0] + 1) * HIST_BIN_MS, 3)


def hist_delta(after, before):
    """``after - before`` of two sparse histograms (a tour's own frames from two metrics() reads)."""
    base = {int(b): int(n) for b, n in (before or {}).items()}
    out = {}
    for b, n in (after or {}).items():
        d = int(n) - base.get(int(b), 0)
        if d > 0:
            out[int(b)] = d
    return out


class LoopStats:
    """FrameStats for the carousel loop (K4 5.2, 6.1-6.2: present cadence), measured on the
    carousel thread.

    Per frame: the present time (mapped to a vblank index ``round((t - qpcVBlank) / P)``),
    ``work_ms`` (the wake to the start of the present: the drain and the compose) and
    ``present_ms`` (the thumbnail updates, the chrome ULW and the B2 layers).

    Per episode (a motion's start to its settle; ``kind`` one of K4 6.2's EPISODE_KINDS):
    frames (distinct vblanks), vblanks, fps, interval_ms p50/p95/p99/max, missed (> 1.5 P),
    double_missed (> 2.5 P), work_ms, present_ms and ``compose_present_ms`` (the per-frame sum,
    K4 6.3's picker budget) as p95/max, ``cpu_pct_one_core`` (the frame thread's CPU time over
    the episode, from ``cpu_clock``: ``time.thread_time``, i.e. GetThreadTimes of the calling
    thread, which is NanoD-carousel), cadence_switches, rate_hz, ``boosted`` and ``rm``.

    ``metrics()`` keeps per surface ``last``, ``worst`` and ``totals`` per kind (episodes,
    frames, missed, double_missed, wall_s, cpu_s), and ``pooled``: every episode frame's
    compose + present and work in HIST_BIN_MS histograms, so a supervised check can take a
    tour's p95 as the difference of two reads (``hist_delta``, ``hist_quantile``).

    Step 3 (the GPU chrome, CAR 12.4): a frame also says whether it carried an event's chrome
    sync (``detent``) and which chrome drew it; the record adds ``chrome`` and the per-frame Python
    work (compose + present) split into ``normal_ms`` and ``detent_ms`` (K4 6.3's "Picker (W), step
    3" row: <= 1.5 ms p95 on normal frames, <= 3.0 ms on detent frames), with ``sync_ms`` (the sync's
    build and Commit); ``pooled`` adds the ``normal_ms`` and ``detent_ms`` histograms.

    Attribution (the 2026-09-26 review of the frame-drop fixes): a frame may also carry the P5
    cadence it was paced at and, when it re-registered the thumbnails, how long that took. The
    record adds ``locked_frames`` (presents under the 120 lock), ``paced_frames``, ``rereg_frames``
    and ``rereg_ms``; each ``recent`` entry is (kind, t0, t_end, chrome, loop) with ``loop`` =
    {presents, locked_frames, paced_frames, cadence_switches, rereg_at_ms (ms from t0),
    rereg_ms_max}, which ``picker_snap_checks`` sets against the compositor's gaps."""

    RECENT = 64                           # the last episodes' (kind, t0, t_end, chrome, loop) per surface: the
                                          # supervised checks match them with the compositor's displayed frames
    RECENT_REREG = 64                     # re-registration times kept per episode in ``recent``

    def __init__(self, cpu_clock=None):
        self.surfaces = {}
        self._open = {}
        self.lock = threading.Lock()
        self.cpu_clock = cpu_clock if cpu_clock is not None else getattr(time, "thread_time", None)

    def _cpu(self):
        try:
            return float(self.cpu_clock()) if self.cpu_clock is not None else None
        except Exception:
            return None

    def begin(self, surface, kind, now, switches=0, rm=False):
        if surface not in self._open:
            kind = kind if kind in EPISODE_KINDS else "turn"
            self._open[surface] = {"kind": kind, "t0": now, "presents": [], "work": [], "present": [],
                                   "switches0": switches, "rm": bool(rm), "cpu0": self._cpu(), "detent": [],
                                   "sync": [], "chrome": None, "locked": 0, "paced": 0, "rereg": []}

    def frame(self, surface, t_present, work_s, present_s=0.0, detent=False, chrome=None, sync_s=None,
              cadence=None, rereg_s=None):
        """One presented frame. ``cadence``: the P5 cadence it was paced at (2 = the 120 lock);
        ``rereg_s``: the time its thumbnail re-registration took, when it re-registered. Both are
        for the attribution of an episode's missed frames (the 2026-09-26 review: lock or
        registration), recorded per episode and in ``recent``."""
        episode = self._open.get(surface)
        if episode is not None:
            episode["presents"].append(t_present)
            episode["work"].append(work_s * 1000.0)
            episode["present"].append(present_s * 1000.0)
            episode["detent"].append(bool(detent))
            if sync_s is not None:
                episode["sync"].append(sync_s * 1000.0)
            if chrome is not None:
                episode["chrome"] = chrome
            if cadence is not None:
                episode["paced"] += 1
                if cadence >= 2:
                    episode["locked"] += 1
            if rereg_s is not None:              # when the present (which re-registers first) began
                begun = t_present - max(0.0, present_s)
                episode["rereg"].append((max(0.0, begun - episode["t0"]) * 1000.0, rereg_s * 1000.0))

    def active(self, surface):
        return surface in self._open

    def end(self, surface, now, period, vblank=None, switches=0, rate_hz=None, boosted=None):
        episode = self._open.pop(surface, None)
        if episode is None or not episode["presents"]:
            return None
        cpu1 = self._cpu()
        period = period or LoopPacer.DEFAULT_PERIOD
        origin = vblank if vblank is not None else episode["presents"][0]
        idx = [int(math.floor((t - origin) / period + 0.5)) for t in episode["presents"]]
        distinct = []
        times = []
        for i, t in zip(idx, episode["presents"]):
            if not distinct or i != distinct[-1]:
                distinct.append(i)
                times.append(t)
        intervals = sorted((b - a) * 1000.0 for a, b in zip(times, times[1:]))
        duration = max(1e-9, now - episode["t0"])
        both = [w + p for w, p in zip(episode["work"], episode["present"])]
        cpu_s = None
        if episode["cpu0"] is not None and cpu1 is not None:
            cpu_s = max(0.0, cpu1 - episode["cpu0"])
        p_ms = period * 1000.0
        record = {"surface": surface, "kind": episode["kind"], "method": "present_cadence",
                  "frames": len(distinct), "vblanks": round(duration / period, 1),
                  "fps": round(len(distinct) / duration, 2),
                  "interval_ms": {"p50": round(quantile(intervals, 0.5), 3), "p95": round(quantile(intervals, 0.95), 3),
                                  "p99": round(quantile(intervals, 0.99), 3), "max": round(intervals[-1], 3)}
                  if intervals else None,
                  "missed": sum(1 for x in intervals if x > 1.5 * p_ms),
                  "double_missed": sum(1 for x in intervals if x > 2.5 * p_ms),
                  "work_ms": _summary(episode["work"]), "present_ms": _summary(episode["present"]),
                  "compose_present_ms": _summary(both),
                  "cpu_pct_one_core": round(100.0 * cpu_s / duration, 1) if cpu_s is not None else None,
                  "cadence_switches": max(0, switches - episode["switches0"]), "rate_hz": rate_hz,
                  "boosted": None if boosted is None else bool(boosted), "rm": episode["rm"],
                  "duration_ms": round(duration * 1000.0, 1)}
        flags = episode["detent"] + [False] * (len(both) - len(episode["detent"]))
        normal = [v for v, d in zip(both, flags) if not d]
        detent = [v for v, d in zip(both, flags) if d]
        record.update({"chrome": episode["chrome"], "normal_ms": _summary(normal), "detent_ms": _summary(detent),
                       "detent_frames": len(detent), "sync_ms": _summary(episode["sync"])})
        # Attribution of the episode's misses (2026-09-26 review): how many presents ran under the
        # 120 lock (P5), and which frames re-registered the thumbnails (ms from t0) and how long it took.
        rereg = episode["rereg"]
        record.update({"locked_frames": episode["locked"], "paced_frames": episode["paced"],
                       "rereg_frames": len(rereg), "rereg_ms": _summary([ms for _at, ms in rereg])})
        loop = {"presents": len(episode["presents"]), "locked_frames": episode["locked"],
                "paced_frames": episode["paced"], "cadence_switches": record["cadence_switches"],
                "rereg_at_ms": [round(at, 1) for at, _ms in rereg[:self.RECENT_REREG]],
                "rereg_ms_max": round(max((ms for _at, ms in rereg), default=0.0), 3)}
        with self.lock:
            s = self.surfaces.setdefault(surface, {"last": None, "worst": None, "totals": {},
                                                   "pooled": {"frames": 0, "compose_present_ms": {}, "work_ms": {}}})
            for key in ("normal_ms", "detent_ms"):
                s["pooled"].setdefault(key, {})
            s.setdefault("recent", deque(maxlen=self.RECENT)).append(
                (record["kind"], round(episode["t0"], 6), round(now, 6), record["chrome"], loop))
            s["last"] = record
            if s["worst"] is None or self._badness(record) > self._badness(s["worst"]):
                s["worst"] = record
            totals = s["totals"].setdefault(record["kind"], {"episodes": 0, "frames": 0, "missed": 0,
                                                             "double_missed": 0, "wall_s": 0.0, "cpu_s": 0.0})
            totals["episodes"] += 1
            totals["frames"] += record["frames"]
            totals["missed"] += record["missed"]
            totals["double_missed"] += record["double_missed"]
            if cpu_s is not None:
                totals["wall_s"] = round(totals["wall_s"] + duration, 6)
                totals["cpu_s"] = round(totals["cpu_s"] + cpu_s, 6)
            pooled = s["pooled"]
            pooled["frames"] += len(both)
            for w, value, d in zip(episode["work"], both, flags):
                hist_add(pooled["compose_present_ms"], value)
                hist_add(pooled["work_ms"], w)
                hist_add(pooled["detent_ms" if d else "normal_ms"], value)
        return record

    @staticmethod
    def _badness(record):
        iv = record.get("interval_ms") or {}
        return (record.get("double_missed") or 0) * 10 + (record.get("missed") or 0), iv.get("max") or 0.0

    def metrics(self):
        with self.lock:
            return {k: {"last": dict(v["last"]) if v["last"] else None,
                        "worst": dict(v["worst"]) if v["worst"] else None,
                        "totals": {kind: dict(t) for kind, t in v["totals"].items()},
                        "pooled": {"frames": v["pooled"]["frames"],
                                   "compose_present_ms": dict(v["pooled"]["compose_present_ms"]),
                                   "work_ms": dict(v["pooled"]["work_ms"]),
                                   "normal_ms": dict(v["pooled"].get("normal_ms") or {}),
                                   "detent_ms": dict(v["pooled"].get("detent_ms") or {})},
                        "recent": [[{k: list(y) if isinstance(y, list) else y for k, y in x.items()}
                                    if isinstance(x, dict) else x for x in e] for e in v.get("recent") or ()]}
                    for k, v in self.surfaces.items()}


# ======================================================================= hand-off
ItemInfo = namedtuple("ItemInfo", "id hwnd minimized available app title pid class_name exstyle",
                      defaults=(0, "", 0))
OpenRequest = namedtuple("OpenRequest", "gen items index origin background exclude rm", defaults=((), False))
SelectRequest = namedtuple("SelectRequest", "gen index available bump", defaults=(0,))
Dismiss = namedtuple("Dismiss", "gen mode text")      # mode: 'hide' | 'switch' | 'cancel' | 'pair'
CaptureJob = namedtuple("CaptureJob", "gen kind rect k flush")
CaptureResult = namedtuple("CaptureResult", "gen kind image capture_ms build_ms error")
SnapRequest = namedtuple("SnapRequest", "gen job index side target t0 item")
ToastRequest = namedtuple("ToastRequest", "seq text exit rm t_request")
WorkRequest = namedtuple("WorkRequest", "kind job")          # 'complete' | 'raise' (NanoD-snap jobs)

# ----------------------------------------------------- the GPU chrome seam (K4 9.9 step 3; R-h; CAR 12.4)
# What the engine hands the GPU chrome at each event (the chrome reads the machine's tweens as they
# are: start, target, t0, duration, ease; it never changes them):
# - ``machine``: the CarouselMachine; ``sel``; ``closed``: the closed card indices;
# - ``cards``: ChromeCardInfo per card the machine holds (``tweens`` = its _CardTweens; ``d`` = index -
#   sel; ``badge`` = (Sprite, pad) at scale 1; ``chip`` = the chip Sprite when the window holds a side;
#   ``face`` = the placeholder's icon Sprite when no thumbnail shows, else None);
# - ``order``: those indices far -> near (the z-order, K4 4.4 / BS:1183);
# - ``tray_on``; ``slots``: side -> ChromeSlotInfo (the _SlotTweens, the slot badge, caption and glyph);
# - ``label`` (a LabelSprite or None) and ``label_key``; ``dots`` ((Sprite, x, y) or None), ``dots_key``,
#   ``dots_shown`` (the row's dot count) and the ``marker`` Sprite;
# - ``fly`` (the session's fly dict: start, target, t0) or None;
# - the motion constants the chrome needs: ``bump_back`` (the end bump's second leg, or None),
#   ``bump_leg_s``, ``fly_s``, ``fly_fade_at``, ``fly_fade_s``.
ChromeView = namedtuple("ChromeView", "machine sel closed cards order tray_on slots label label_key dots dots_key "
                                      "dots_shown marker fly bump_back bump_leg_s fly_s fly_fade_at fly_fade_s")
ChromeCardInfo = namedtuple("ChromeCardInfo", "index d tweens closed badge chip face")
ChromeSlotInfo = namedtuple("ChromeSlotInfo", "tweens badge caption glyph")
CHROME_MODES = ("auto", "cpu")                 # 'auto': the GPU chrome when installed and able; 'cpu': never
CHROME_ENV = "NANOD_PICKER_CHROME"             # 'cpu' forces the CPU chrome (a support switch; K3 has no setting)
THUMB_LEAD_ENV = "NANOD_PICKER_THUMB_LEAD"     # periods the thumbnails lead the chrome by (AR-12; S1 decides)
_GPU_CHROME = {"factory": None}


def install_gpu_chrome(factory):
    """Register the GPU chrome's factory (``factory(log=None)`` -> a PickerChrome). The wiring point
    (``standalone.py``) calls the stage package's ``picker_chrome.install()``, which calls this; every
    CarouselPresenter created afterwards uses it. ``None`` uninstalls."""
    _GPU_CHROME["factory"] = factory


def gpu_chrome_factory():
    return _GPU_CHROME["factory"]


def _env_chrome_mode(environ=None):
    value = str((os.environ if environ is None else environ).get(CHROME_ENV, "") or "").strip().lower()
    return "cpu" if value in ("cpu", "0", "off", "false") else "auto"


def _env_thumb_lead(environ=None):
    try:
        value = float((os.environ if environ is None else environ).get(THUMB_LEAD_ENV, "") or 0.0)
    except ValueError:
        return 0.0
    return max(0.0, min(2.0, value))

EV_OPEN, EV_SELECT, EV_DATA, EV_DISMISS = "open", "select", "data", "dismiss"
EV_STOP, EV_CAPTURED, EV_TIMER, EV_SUSPEND = "stop", "captured", "timer", "suspend"
EV_ACTIVATED, EV_DISPLAY = "activated", "display"     # the host became active; display/DWM/resume change
EV_SNAP, EV_TOAST, EV_WORK, EV_LABEL = "snap", "toast", "work", "label"
EV_WARM = "warm"                                      # a knob touch: warm the GPU chrome's device (K4 4.2)
IN_KEY, IN_WHEEL, IN_HWHEEL, IN_CLICK, IN_CLOSE = "key", "wheel", "hwheel", "click", "close"

WM_APP = 0x8000
WM_APP_OPEN, WM_APP_SELECT, WM_APP_DATA, WM_APP_DISMISS = WM_APP + 1, WM_APP + 2, WM_APP + 3, WM_APP + 4
WM_APP_STOP, WM_APP_CAPTURED, WM_APP_ACTIVATED = WM_APP + 5, WM_APP + 6, WM_APP + 7
WM_APP_SNAP, WM_APP_TOAST, WM_APP_WORK, WM_APP_LABEL = WM_APP + 8, WM_APP + 9, WM_APP + 10, WM_APP + 11
WM_APP_WARM = WM_APP + 12
POSTED_EVENTS = {WM_APP_OPEN: EV_OPEN, WM_APP_SELECT: EV_SELECT, WM_APP_DATA: EV_DATA,
                 WM_APP_DISMISS: EV_DISMISS, WM_APP_STOP: EV_STOP, WM_APP_CAPTURED: EV_CAPTURED,
                 WM_APP_ACTIVATED: EV_ACTIVATED, WM_APP_SNAP: EV_SNAP, WM_APP_TOAST: EV_TOAST,
                 WM_APP_WORK: EV_WORK, WM_APP_LABEL: EV_LABEL, WM_APP_WARM: EV_WARM}
POST_FLAGS = {WM_APP_OPEN: "open", WM_APP_SELECT: "select", WM_APP_DATA: "data", WM_APP_DISMISS: "dismiss",
              WM_APP_SNAP: "snap", WM_APP_TOAST: "toast", WM_APP_WORK: "work"}

VK_RETURN, VK_ESCAPE, VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN = 0x0D, 0x1B, 0x25, 0x26, 0x27, 0x28

HOST_LAYERED, HOST_PLAIN = "noredirection", "plain"
SIDES = ("left", "right")


def _other(side):
    return "right" if side == "left" else "left"


class Mailbox:
    """Tk thread <-> carousel thread hand-off; every field is guarded by ``lock``. The Tk side
    writes requests (newest wins, except snap and NanoD-snap work requests, which queue) and
    posts at most one WM_APP message per kind at a time; the carousel thread takes them and
    appends events for take_events()."""

    def __init__(self):
        self.lock = threading.Lock()
        self.open_req = None
        self.select = None
        self.dismiss = None
        self.dismissed_gen = 0          # the Tk side gave up on these opens (handshake timeout)
        self.icons = None
        self.labels = None
        self.data_seq = 0
        self.snaps = []
        self.work = []
        self.toast = None
        self.toast_end = False
        self.events = deque(maxlen=512)
        self.posted = {"open": False, "select": False, "data": False, "dismiss": False, "snap": False,
                       "toast": False, "work": False}
        self.closed = False

    def take_open(self):
        with self.lock:
            req, self.open_req = self.open_req, None
            self.posted["open"] = False
            return req

    def take_select(self):
        with self.lock:
            req, self.select = self.select, None
            self.posted["select"] = False
            return req

    def take_dismiss(self):
        with self.lock:
            req, self.dismiss = self.dismiss, None
            self.posted["dismiss"] = False
            return req

    def take_data(self):
        with self.lock:
            self.posted["data"] = False
            return self.icons, self.labels, self.data_seq

    def take_snaps(self):
        with self.lock:
            snaps, self.snaps = self.snaps, []
            self.posted["snap"] = False
            return snaps

    def take_work(self):
        with self.lock:
            work, self.work = self.work, []
            self.posted["work"] = False
            return work

    def take_toast(self):
        with self.lock:
            req, self.toast = self.toast, None
            end, self.toast_end = self.toast_end, False
            self.posted["toast"] = False
            return req, end

    def push_event(self, kind, payload=None):
        with self.lock:
            self.events.append((kind, payload))


class _Status:
    """Values the carousel thread publishes (single writer each; reads are atomic)."""

    def __init__(self):
        self.cond = threading.Condition()
        self.host_hwnd = 0
        self.host_mode = None
        self.rect = None
        self.layout = None              # the open (or last) picker's Layout: half_rect()
        self.opened_gen = 0
        self.open_failed_gen = 0
        self.disabled = False
        self.closed = False
        self.last_error = None
        self.awareness = None
        self.frames = 0
        self.compose_ms = None
        self.compose_ms_max = 0.0
        self.register_failures = 0
        self.registrations = 0
        self.glass_fallbacks = 0
        self.capture_ms = None
        self.glass_ms = None
        # The frost's upload on this thread (glass_upload: DIB, copy, UpdateLayeredWindow, show;
        # or the plain host's paint), which lands during the open's fade (CAR section 10).
        self.glass_upload_ms = None
        self.glass_upload_ms_max = 0.0
        self.toasts = 0
        self.toasts_dropped = 0
        self.post_failures = 0
        self.snaps = 0
        self.snap_backstops = 0
        self.label_swaps = 0
        self.label_late = 0
        # step 3 (CAR 12.4): which chrome drew the last open, and how often the GPU one fell back
        self.chrome = None
        self.gpu_sessions = 0
        self.gpu_fallbacks = 0


class _Log:
    """Rate-limited logging per failure kind; never raises. Messages never carry titles."""

    def __init__(self, target=None, interval=LOG_INTERVAL_S):
        self._target = target if target is not None else _LOGGER
        self._interval = interval
        self._last = {}
        self._lock = threading.Lock()

    def _emit(self, level, message, exc_info=False):
        try:
            method = getattr(self._target, level, None)
            if callable(method):
                method(message, exc_info=exc_info) if exc_info else method(message)
            elif callable(self._target):
                self._target(message)
        except Exception:
            pass

    def info(self, message):
        self._emit("info", message)

    def error(self, message, exc_info=False):
        self._emit("error", message, exc_info)

    def warn(self, key, message):
        now = time.monotonic()
        with self._lock:
            last = self._last.get(key)
            if last is not None and now - last < self._interval:
                return
            self._last[key] = now
        self._emit("warning", message)


def uses_placeholder(available, registered, failed, stub, rereg_pending):
    """Whether a card draws the icon placeholder instead of its DWM thumbnail (CAR section 2):
    closed windows, failed registrations, minimized caption stubs, and cards without a
    thumbnail that no pending re-registration will give one."""
    if not available or failed or stub:
        return True
    return not registered and not rereg_pending


def _usable_size(size):
    """Whether a DwmQueryThumbnailSourceSize result can drive cover_source (both sides > 0)."""
    try:
        return size is not None and int(size[0]) > 0 and int(size[1]) > 0
    except (TypeError, ValueError, IndexError):
        return False


def _master_icon(icon):
    """The biggest copy of an icon: its attached 128 px hi-res copy (windows.attach_hires_icon)
    when present."""
    info = getattr(icon, "info", None)
    hires = info.get("nanod.iconHires") if isinstance(info, dict) else None
    return hires if getattr(hires, "size", (0, 0))[0] > getattr(icon, "size", (0, 0))[0] else icon


def _same_identity(item, identity):
    """windows.same_identity: never retarget a stale entry by title, process name or slot."""
    if not identity or not item.get("available", True):
        return False
    if (item.get("hwnd"), item.get("pid")) != (identity.get("hwnd"), identity.get("pid")):
        return False
    return not item.get("id") or item["id"] == identity.get("id")


def _rect4(value):
    try:
        l, t, r, b = (int(round(float(v))) for v in value)
    except (TypeError, ValueError):
        return None
    return (l, t, r, b) if r > l and b > t else None


# ================================================================= capture worker
class CaptureWorker:
    """The NanoD-capture thread: one job at a time (newest wins), backend.capture(rect) (a
    BitBlt of what the screen shows there: our windows are excluded by display affinity or
    hidden), then for a ``"frost"`` job the PIL frost (R.frost_canvas: the whole reduced-scale
    pipeline and the upscale, laid out as the glass window's premultiplied DIB, so the carousel
    thread only copies it); the toast's small capture is returned raw. Results go to
    ``take_results`` and the carousel thread is woken with WM_APP_CAPTURED."""

    def __init__(self, backend, *, log=None, glass=R.frost_canvas):
        self._backend = backend
        self._glass = glass
        self._log = log if isinstance(log, _Log) else _Log(log)
        self._cond = threading.Condition()
        self._job = None
        self._results = []
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="NanoD-capture", daemon=True)
        self._thread.start()

    def submit(self, job):
        with self._cond:
            if self._closed:
                return False
            self._job = job
            self._cond.notify()
            return True

    def take_results(self):
        with self._cond:
            results, self._results = self._results, []
            return results

    def close(self, timeout=None):
        with self._cond:
            self._closed = True
            self._job = None
            self._results = []
            self._cond.notify()
        if timeout and self._thread is not threading.current_thread():
            self._thread.join(timeout)
        return not self._thread.is_alive()

    def _run(self):
        try:
            self._backend.prepare_capture_thread()
        except Exception as exc:
            self._log.warn("capture-dpi", f"carousel: capture thread DPI setup failed: {exc!r}")
        while True:
            with self._cond:
                while not self._closed and self._job is None:
                    self._cond.wait()
                if self._closed:
                    return
                job, self._job = self._job, None
            result = self._do(job)
            with self._cond:
                if self._closed:
                    return
                self._results.append(result)
            try:
                self._backend.post(WM_APP_CAPTURED)
            except Exception:
                pass

    def _do(self, job):
        image, error, capture_ms, build_ms = None, None, None, None
        try:
            if job.flush:
                self._backend.flush()
            started = time.perf_counter()
            raw = self._backend.capture(job.rect)
            capture_ms = round((time.perf_counter() - started) * 1000, 2)
            if raw is None:
                raise OSError("screen capture failed")
            if job.kind == "frost":
                started = time.perf_counter()
                image = self._glass(raw, job.k)
                raw = None                          # a full-monitor capture: freed before the hand-off
                build_ms = round((time.perf_counter() - started) * 1000, 2)
            else:
                image = raw
        except Exception as exc:
            error = repr(exc)
        return CaptureResult(job.gen, job.kind, image, capture_ms, build_ms, error)


# ================================================================== label worker (B1)
LabelJob = namedtuple("LabelJob", "key label icon k background suffix")
# The toast pill (K4 10; WP7b-R6): key (toast gen, seq); backdrop None = the tint-only pill.
ToastJob = namedtuple("ToastJob", "key text k backdrop")


class LabelWorker:
    """B1 (K4 9.9; RF1 5.2): the centre label and its +-3 neighbours are rendered off the frame
    path, on ``NanoD-label`` at below-normal priority (P13), with R.render_label's masked pastes
    (K4 4.7.3). ``submit(jobs)`` replaces the queue (priority order: the selection first, then
    by distance; a key already rendered or rendering is skipped); results go to
    ``take_results()`` and wake the carousel thread (WM_APP_LABEL). ``threaded=False`` (tests,
    inline presenters) renders the queued jobs at ``take_results()`` on the calling thread.

    The toast pill has a slot of its own (WP7b-R6): ``submit_toast(job)`` (newest wins, taken
    before any label), R.render_toast_canvas (masked pastes, the blur.toast glass), results
    from ``take_toast_results()``. Its text fitting, blur and drawing never run on the carousel
    thread, so a toast replacement never stalls the toast's own frames."""

    def __init__(self, *, render=None, post=None, log=None, threaded=True, prepare=None, render_toast=None):
        self._render = render or self._default_render
        self._render_toast = render_toast or self._default_render_toast
        self._post = post
        self._log = log if isinstance(log, _Log) else _Log(log)
        self._prepare = prepare
        self._cond = threading.Condition()
        self._queue = []
        self._busy = None
        self._results = []
        self._toast_job = None
        self._toast_results = []
        self._closed = False
        self._engine = None
        self._threaded = bool(threaded)
        self._thread = None
        if self._threaded:
            self._thread = threading.Thread(target=self._run, name="NanoD-label", daemon=True)
            self._thread.start()

    def _text_engine(self):
        if self._engine is None:
            self._engine = R.TextEngine()              # one engine per thread (CAR section 8)
        return self._engine

    def _default_render(self, job):
        return R.render_label(job.label, job.icon, job.k, job.background, self._text_engine(), job.suffix)

    def _default_render_toast(self, job):
        return R.render_toast_canvas(job.text, job.k, job.backdrop, self._text_engine())

    def submit_toast(self, job):
        with self._cond:
            if self._closed:
                return False
            self._toast_job = job
            self._cond.notify()
            return True

    def take_toast_results(self):
        if not self._threaded:
            with self._cond:
                job, self._toast_job = self._toast_job, None
            if job is not None:
                self._toast_results.append((job.key, self._safe_toast(job)))
        with self._cond:
            results, self._toast_results = self._toast_results, []
            return results

    def _safe_toast(self, job):
        try:
            return self._render_toast(job)
        except Exception as exc:
            self._log.warn("toast", f"carousel: toast rendering failed: {exc!r}")
            return None

    def submit(self, jobs):
        with self._cond:
            if self._closed:
                return False
            busy = self._busy
            self._queue = [job for job in jobs if job.key != busy]
            self._cond.notify()
            return True

    def take_results(self):
        if not self._threaded:
            with self._cond:
                queue, self._queue = self._queue, []
            for job in queue:
                self._results.append((job.key, self._safe(job)))
        with self._cond:
            results, self._results = self._results, []
            return results

    def pending(self):
        with self._cond:
            return [job.key for job in self._queue] + ([self._busy] if self._busy is not None else [])

    def close(self, timeout=None):
        with self._cond:
            self._closed = True
            self._queue = []
            self._results = []
            self._toast_job = None
            self._toast_results = []
            self._cond.notify()
        thread = self._thread
        if thread is not None and timeout and thread is not threading.current_thread():
            thread.join(timeout)
        return thread is None or not thread.is_alive()

    def _safe(self, job):
        try:
            return self._render(job)
        except Exception as exc:
            self._log.warn("label", f"carousel: label rendering failed: {exc!r}")
            return None

    def _run(self):
        if self._prepare is not None:
            try:
                self._prepare()
            except Exception:
                pass
        while True:
            with self._cond:
                while not self._closed and not self._queue and self._toast_job is None:
                    self._cond.wait()
                if self._closed:
                    return
                toast, self._toast_job = self._toast_job, None
                job = None
                if toast is None:
                    job = self._queue.pop(0)
                    self._busy = job.key
            if toast is not None:
                pill = self._safe_toast(toast)
                with self._cond:
                    if self._closed:
                        return
                    self._toast_results.append((toast.key, pill))
            else:
                sprite = self._safe(job)
                with self._cond:
                    self._busy = None
                    if self._closed:
                        return
                    self._results.append((job.key, sprite))
            if self._post is not None:
                try:
                    self._post(WM_APP_LABEL)
                except Exception:
                    pass


# ======================================================================= NanoD-snap (K4 9.5-9.7)
SW_SHOWNOACTIVATE, SW_SHOWMINNOACTIVE = 4, 7
SWP_NOSIZE_, SWP_NOMOVE_, SWP_NOZORDER_, SWP_NOACTIVATE_ = 0x0001, 0x0002, 0x0004, 0x0010
SWP_NOOWNERZORDER_, SWP_ASYNCWINDOWPOS = 0x0200, 0x4000
SWP_ASYNC_PLACE = SWP_NOZORDER_ | SWP_NOACTIVATE_ | SWP_NOOWNERZORDER_ | SWP_ASYNCWINDOWPOS
SWP_ASYNC_RAISE = SWP_NOSIZE_ | SWP_NOMOVE_ | SWP_NOACTIVATE_ | SWP_ASYNCWINDOWPOS
assert SWP_ASYNC_PLACE == 0x4214 and SWP_ASYNC_RAISE == 0x4013
HWND_TOP_ = 0
WS_EX_TOOLWINDOW_ = 0x80
UWP_FRAME_CLASS = "ApplicationFrameWindow"


class SnapJob:
    """One NanoD-snap job: ``kind`` 'snap' (the pre-checks, then the one placement at
    ``place_at``), 'complete' (U12's complete_one_side) or 'raise' (the pair close's posted
    raise). ``resolve`` records the first outcome only: the worker's, or the carousel's backstop
    at the deadline (K4 9.6); a later one is dropped."""
    _ids = itertools.count(1)

    def __init__(self, kind, *, side=None, item=None, target=None, t0=0.0, place_at=None, deadline=None,
                 hwnd=None, work=None):
        self.id = next(SnapJob._ids)
        self.kind = kind
        self.side = side
        self.item = dict(item or {})
        self.target = _rect4(target) if target is not None else None
        self.t0 = float(t0)
        self.place_at = place_at
        self.deadline = deadline
        self.hwnd = int(hwnd or self.item.get("hwnd") or 0)
        self.work = work
        self.accepted = False
        self._lock = threading.Lock()
        self.outcome = None
        self.resolved_by = None

    def resolve(self, outcome, by):
        with self._lock:
            if self.outcome is not None:
                return False
            self.outcome, self.resolved_by = outcome, by
            return True

    @property
    def resolved(self):
        return self.outcome is not None


def compensate(target, window, frame):
    """K4 9.6 step 5: the window rect R that puts the visible frame E on the target V:
    (V.l - (E.l - W.l), V.t - (E.t - W.t), V.r + (W.r - E.r), V.b + (W.b - E.b))."""
    vl, vt, vr, vb = target
    wl, wt, wr, wb = window
    el, et, er, eb = frame
    return (vl - (el - wl), vt - (et - wt), vr + (wr - er), vb + (wb - eb))


def _within(frame, target, px=MATCH_PX):
    return frame is not None and all(abs(a - b) <= px for a, b in zip(frame, target))


class SnapWorker:
    """``NanoD-snap`` (K4 9.5-9.7; S5-14): real-window placement and verification, never on the
    Tk or carousel thread. It reaches a target window **only** through ``native.show_async``
    (ShowWindowAsync with SW_SHOWNOACTIVATE or SW_SHOWMINNOACTIVE) and ``native.set_pos_async``
    (SetWindowPos with SWP_ASYNCWINDOWPOS); everything else it calls never waits on the target
    (placement, rects, frame bounds, iconic / zoomed / hung, identity, integrity, the monitor of
    a window, the foreground). Every job resolves by its hard deadline: the worker never starts a
    wait that would end past it, and at the deadline an unfinished job resolves as
    ``move_rejected`` and puts the window back (step 7, posted calls only).

    Results: ``(job, stage, outcome, info)`` with stage 'precheck' (``accepted``, ``hung`` or
    ``move_rejected`` at t = 0), 'final' (``ok``, ``move_rejected`` or ``cant_fit``) or 'complete'
    (the U12 job), through ``take_results()`` and a wake (``post(WM_APP_SNAP)``). ``info`` carries
    the foreground window after the job (step 8) and whether anything was posted."""

    def __init__(self, native, *, clock=time.perf_counter, wait=None, post=None, log=None, threaded=True,
                 prepare=None):
        self.native = native
        self.clock = clock
        self._stop = threading.Event()
        self._wait = wait if wait is not None else self._stop.wait
        self._post = post
        self._prepare = prepare
        self._log = log if isinstance(log, _Log) else _Log(log)
        self._cond = threading.Condition()
        self._jobs = deque()
        self._results = []
        self._closed = False
        self._threaded = bool(threaded)
        self._thread = None
        self.calls = 0

    # ------------------------------------------------------------ plumbing
    def submit(self, job):
        with self._cond:
            if self._closed:
                return False
            self._jobs.append(job)
            self._cond.notify()
        if self._threaded and self._thread is None:
            self._thread = threading.Thread(target=self._run, name="NanoD-snap", daemon=True)
            self._thread.start()
        return True

    def take_results(self):
        with self._cond:
            results, self._results = self._results, []
            return results

    def run_pending(self):
        """Tests / inline presenters: run the queued jobs on the calling thread."""
        while True:
            with self._cond:
                if not self._jobs:
                    return
                job = self._jobs.popleft()
            self.run_job(job)

    def close(self, timeout=None):
        with self._cond:
            self._closed = True
            self._jobs.clear()
            self._cond.notify()
        self._stop.set()
        thread = self._thread
        if thread is not None and timeout and thread is not threading.current_thread():
            thread.join(timeout)
        return thread is None or not thread.is_alive()

    def _run(self):
        if self._prepare is not None:
            try:
                self._prepare()
            except Exception:
                pass
        while True:
            with self._cond:
                while not self._closed and not self._jobs:
                    self._cond.wait()
                if self._closed:
                    return
                job = self._jobs.popleft()
            try:
                self.run_job(job)
            except Exception as exc:
                self._log.warn("snap", f"carousel: a snap job failed: {exc!r}")
                if job.kind != "raise" and job.resolve("move_rejected", "worker"):
                    self._emit(job, "final" if job.kind == "snap" else "complete", "move_rejected", {})

    def _emit(self, job, stage, outcome, info=None):
        with self._cond:
            if self._closed:
                return
            self._results.append((job, stage, outcome, dict(info or {})))
        if self._post is not None:
            try:
                self._post(WM_APP_SNAP)
            except Exception:
                pass

    def _pause_until(self, job, end, step):
        """Wait ``step`` if that ends by ``end`` (never past the job's deadline); False when it
        would not, or the worker is closing, or the job was resolved meanwhile (the backstop)."""
        now = self.clock()
        if now + step > end + TIME_EPSILON:
            return False
        self._wait(step)
        return not self._stop.is_set() and not job.resolved

    # ------------------------------------------------------------ jobs
    def run_job(self, job):
        self.calls += 1
        if job.kind == "raise":
            try:
                self.native.set_pos_async(job.hwnd, HWND_TOP_, 0, 0, 0, 0, SWP_ASYNC_RAISE)
            except Exception as exc:
                self._log.warn("raise", f"carousel: the posted raise failed: {exc!r}")
            return
        if job.kind == "complete":
            self._run_complete(job)
            return
        self._run_snap(job)

    def precheck(self, job):
        """K4 9.5 t = 0 (<= 5 ms): the identity still matches, not hung, integrity level not
        above ours (a failed query carries on). None when the job may go on."""
        native, hwnd = self.native, job.hwnd
        try:
            if not hwnd or not native.is_window(hwnd):
                return "move_rejected"
            if not _same_identity(job.item, native.identity(hwnd)):
                return "move_rejected"
            if native.is_hung(hwnd):
                return "hung"
        except Exception:
            return "move_rejected"
        try:
            if native.integrity_above_ours(hwnd) is True:
                return "move_rejected"
        except Exception:
            pass
        return None

    def _run_snap(self, job):
        failure = self.precheck(job)
        if failure is not None:
            if job.resolve(failure, "worker"):
                self._emit(job, "precheck", failure, {"posted": False})
            return
        job.accepted = True
        self._emit(job, "precheck", "accepted", {})
        deadline = job.deadline
        delay = (job.place_at or self.clock()) - self.clock()
        if delay > 0:
            if deadline is not None and self.clock() + delay > deadline:
                if job.resolve("move_rejected", "worker"):
                    self._emit(job, "final", "move_rejected", {"posted": False})
                return
            self._wait(delay)
        if self._stop.is_set() or job.resolved:
            return                                    # nothing was posted to the target yet
        outcome, state = self.place(job, deadline)
        info = {"posted": bool(state.get("posted")), "foreground": self._foreground()}
        if job.resolve(outcome, "worker"):
            self._emit(job, "final", outcome, info)
        elif outcome == "ok":
            self.put_back(job, state)                 # the backstop answered first: step 7

    def _run_complete(self, job):
        """complete_one_side (U12; VOC 8.4): the origin takes the other half with the snap recipe,
        resolved by its start + 600 ms."""
        failure = self.precheck(job)
        if failure is not None:
            if job.resolve(failure, "worker"):
                self._emit(job, "complete", failure, {"posted": False})
            return
        outcome, state = self.place(job, job.deadline)
        info = {"posted": bool(state.get("posted")), "foreground": self._foreground()}
        if job.resolve(outcome, "worker"):
            self._emit(job, "complete", outcome, info)
        elif outcome == "ok":
            self.put_back(job, state)

    def _foreground(self):
        try:
            return int(self.native.foreground() or 0)
        except Exception:
            return 0

    def place(self, job, deadline):
        """K4 9.6 steps 1-7 on ``job.hwnd`` towards ``job.target``: (outcome, state)."""
        native, hwnd, target = self.native, job.hwnd, job.target
        state = {"posted": False}
        if target is None:
            return "move_rejected", state
        deadline = deadline if deadline is not None else self.clock() + SNAP_DEADLINE_S
        placement = native.placement(hwnd)                                  # step 1
        window0 = _rect4(native.window_rect(hwnd) or ())
        if placement is None or window0 is None:
            return "move_rejected", state
        state.update(placement=placement, window0=window0, was_min=bool(native.is_iconic(hwnd)),
                     was_max=bool(native.is_zoomed(hwnd)))
        if state["was_min"] or state["was_max"]:                            # step 3
            native.show_async(hwnd, SW_SHOWNOACTIVATE)
            state["posted"] = True
            end = min(self.clock() + RESTORE_LIMIT_S, deadline)
            reposted = False
            while True:
                iconic, zoomed = bool(native.is_iconic(hwnd)), bool(native.is_zoomed(hwnd))
                if not iconic and not zoomed:
                    break
                if zoomed and not iconic and state["was_min"] and not reposted:
                    native.show_async(hwnd, SW_SHOWNOACTIVATE)              # WPF_RESTORETOMAXIMIZED
                    reposted = True
                if not self._pause_until(job, end, RESTORE_POLL_S):
                    self.put_back(job, state)
                    return "move_rejected", state
        window = _rect4(native.window_rect(hwnd) or ())                      # step 4
        frame = _rect4(native.frame_bounds(hwnd) or ()) or window
        if window is None:
            self.put_back(job, state)
            return "move_rejected", state
        self._place_once(hwnd, target, window, frame)                        # step 5
        state["posted"] = True
        uwp = str(job.item.get("class_name") or "") == UWP_FRAME_CLASS
        end = min(self.clock() + (VERIFY_UWP_S if uwp else VERIFY_S), deadline)
        offsets = tuple(a - b for a, b in zip(frame, window))
        reapplied = False
        last = frame
        while True:                                                         # step 6
            current = _rect4(native.frame_bounds(hwnd) or ()) or _rect4(native.window_rect(hwnd) or ())
            if _within(current, target):
                return "ok", state
            if current is not None:
                last = current
                now_window = _rect4(native.window_rect(hwnd) or ())
                if not reapplied and now_window is not None:
                    now_offsets = tuple(a - b for a, b in zip(current, now_window))
                    if any(abs(a - b) > 1 for a, b in zip(now_offsets, offsets)):
                        # a DPI change on the way: re-apply steps 4-5 once after its resize
                        self._place_once(hwnd, target, now_window, current)
                        reapplied = True
            if not self._pause_until(job, end, VERIFY_POLL_S):
                break
        tl, tt, tr, tb = target
        fl, ft, fr, fb = last
        # cant_fit: the window took the half's origin but kept a larger size (its minimum size);
        # anything else, a move that never landed included, is move_rejected (K4 9.6 step 6).
        at_origin = abs(fl - tl) <= MATCH_PX and abs(ft - tt) <= MATCH_PX
        larger = (fr - fl) > (tr - tl) + MATCH_PX or (fb - ft) > (tb - tt) + MATCH_PX
        outcome = "cant_fit" if at_origin and larger else "move_rejected"
        self.put_back(job, state)                                            # step 7
        return outcome, state

    def _place_once(self, hwnd, target, window, frame):
        l, t, r, b = compensate(target, window, frame)
        self.native.set_pos_async(hwnd, None, l, t, r - l, b - t, SWP_ASYNC_PLACE)

    def put_back(self, job, state):
        """K4 9.6 step 7: without activating and without waiting, posted calls only; skipped when
        nothing was posted. A normal window goes back to its rect, a minimized one to its normal
        rect and then minimized (SW_SHOWMINNOACTIVE); a maximized one is left restored at its
        normal rect, never re-maximized (every maximize command activates, S5-32)."""
        if not state.get("posted"):
            return
        native, hwnd = self.native, job.hwnd
        try:
            if state.get("was_min") or state.get("was_max"):
                normal = _rect4(state["placement"][2])
                if normal is None:
                    return
                if not int(job.item.get("exstyle") or 0) & WS_EX_TOOLWINDOW_:
                    monitors = native.monitor_of(hwnd)
                    if monitors:
                        monitor, work = monitors
                        dx, dy = work[0] - monitor[0], work[1] - monitor[1]
                        normal = (normal[0] + dx, normal[1] + dy, normal[2] + dx, normal[3] + dy)
            else:
                normal = state["window0"]
            l, t, r, b = normal
            native.set_pos_async(hwnd, None, l, t, r - l, b - t, SWP_ASYNC_PLACE)
            if state.get("was_min"):
                native.show_async(hwnd, SW_SHOWMINNOACTIVE)
        except Exception as exc:
            self._log.warn("put-back", f"carousel: putting a window back failed: {exc!r}")


# ========================================================================= engine
class _Session:
    """One open picker (carousel thread). ``plain``: the plain-host fallback (it paints the frost
    over the whole monitor: the v7 host is rcMonitor). ``dim``: No background's 55 % dim window.
    ``frost_rect``: what the frost covers and its capture reads (rcMonitor)."""

    def __init__(self, req, layout, background, plain=False):
        self.gen = req.gen
        self.items = req.items
        self.origin = req.origin
        self.layout = layout
        self.background = background
        self.plain = bool(plain)
        self.rm = bool(getattr(req, "rm", False))
        self.dim = background == "none" and not self.plain
        self.frost_rect = tuple(layout.monitor_rect)
        self.available = [bool(item.available) for item in req.items]
        self.origin_index = next((i for i, item in enumerate(req.items) if req.origin and item.hwnd == req.origin), None)
        self.thumbs = {}              # card index -> DWM thumbnail handle
        self.sizes = {}               # card index -> source size
        self.failed = set()           # never retried within this open
        self.stubs = set()
        self.attempts = 0
        self.rereg = True
        self.rereg_s = None           # the last frame's re-registration time (FrameStats attribution)
        self.release = set()
        self.dirty = True
        self.exiting = None
        self.glass = "none" if background == "none" else "pending"
        self.capture_deadline = None
        self.setup_deadline = None    # the layers' setup waits for the host's activation until then
        self.affinity = False
        self.exclusions = ()          # other windows of this process kept out of the frost capture
        self.last_animating = False   # the last composed frame was mid-animation (BILINEAR, off target)
        self.layers_shown = False
        self.rects = {}
        self.plan = None
        self.dim_target = 0.0
        self.glass_target = 0.0
        self.dim_alpha = None
        self.glass_alpha = None
        # snap (K4 9.4-9.6)
        self.sides = {"left": None, "right": None}
        self.failures = {}            # side -> (reason, until, index)
        self.jobs = {}                # job id -> SnapJob (kind 'snap')
        self.fly = None
        self.extra = {}               # 'left' | 'right' | 'keep' | 'fly' -> (handle, hwnd)
        self.extra_sizes = {}         # hwnd -> source size
        self.extra_plan = {}
        # B2 layers and B5
        self.label_key = None
        self.label = None
        self.label_index = None       # the card the shown label belongs to (a new card fades in, WP7b-R4)
        self.label_dirty = False
        self.dots_key = None
        self.dots = None
        self.dots_dirty = False
        self.layer_sent = {}          # role -> (alpha, pos)
        self.chrome_box = None
        self.chrome_dirty = None
        self.frame_label = (0, (0, 0))
        self.frame_dots = (0, (0, 0))
        self.marker_px = None
        # step 3 (CAR 12.4): this open's chrome is the GPU chrome
        self.gpu = False
        self.gpu_shown = False
        self.gpu_synced = False       # the first sync committed (the chrome window may show)
        self.thumb_sent = {}          # handle -> the last (dest, source, opacity, visible) sent (GPU: skip repeats)
        self.detent = False           # this frame carried an event's chrome sync
        self.sync_s = None
        self.gpu_label_wait = False   # the selected label waits for its GPU surface
        self.gpu_prebuild = False     # a snap's sprites for the selected card are still being built


class _Toast:
    """One toast. The pill (``sprite``: a premultiplied R.Canvas) comes from NanoD-label
    (WP7b-R6): first the tint-only pill (``plain``, which also sizes the window and the glass
    capture), then the glass pill once the capture is back; a replacement's new text first
    arrives on the old glass, stretched, then on its own fresh glass (K4 10.2)."""

    def __init__(self, gen, text, layout, rect, window, rm=False):
        self.gen = gen
        self.text = text
        self.layout = layout
        self.rect = rect              # the pill at rest (x, y, w, h), screen px (None until sized)
        self.window = window          # the toast window (x, y, w, h): room for the rise and the spring
        self.rm = bool(rm)
        self.sprite = None            # the pill on screen (R.Canvas, premultiplied)
        self.plain = None             # the tint-only pill of this gen: the capture-timeout fallback
        self.backdrop = None          # the last glass capture (raw), stretched for a replacement
        self.seq = 0                  # render submissions; a result older than the applied one is dropped
        self.applied = 0
        self.machine = ToastMachine()
        self.deadline = None          # the glass capture's timeout
        self.shown = False
        self.dirty = True
        self.alpha = None
        self.prepared = False


class CarouselEngine:
    """Carousel-thread logic, platform-neutral. ``on_event`` / ``on_input`` run from the window
    procedure (record, or queue input); ``advance`` handles what was recorded and prepares a
    frame (compose into the chrome DIB) sampled at the predicted display time (P2), returning
    0.0 (``present``, then pace on the compositor clock), a wait in seconds, or None (block until a
    message)."""

    def __init__(self, *, backend, mailbox, status, capture, clock, log=None, text_engine=None, snap=None,
                 labels=None, stats=None, gpu=None, chrome_mode="auto", thumb_lead=0.0):
        self.gpu = gpu                  # the GPU chrome (CAR 12.4) or None: the CPU chrome only
        self.chrome_mode = chrome_mode if chrome_mode in CHROME_MODES else "auto"
        self.thumb_lead = max(0.0, float(thumb_lead or 0.0))   # periods (AR-12's lead, 0 unless S1 says)
        self.backend = backend
        self.mail = mailbox
        self.status = status
        self.capture = capture
        self.snapper = snap
        self.labeler = labels
        self.clock = clock
        self.log = log if isinstance(log, _Log) else _Log(log)
        self.text = text_engine
        self.stats = stats if stats is not None else LoopStats()
        self.machine = CarouselMachine()
        self.session = None
        self.toast = None
        self.stopped = False
        self._pending = set()
        self._icons = {}
        self._labels = {}
        self._data_seq = -1
        self._sprites = OrderedDict()  # (kind, item id) -> (key, value); LRU, SPRITE_CACHE, cleared on hide
        self._label_cache = OrderedDict()
        self._captions = OrderedDict()
        self._chips = {}
        self._glyphs = {}
        self._marker = None
        self._shadows = None
        self._scaler = R._SpriteScaler()
        self._last_gen = 0
        self._last_layout = None
        self._toast_gen = 0
        self._toast_seq = 0
        self._deferred_toast = None
        self._local_toasts = []        # pills rendered inline when there is no label worker
        self._work_jobs = {}
        self._wheel = 0
        self._prepared = False
        self._frame_t = None
        self._t_wake = None
        self._oneoff = False
        self._episode = "open"
        self.last_detent = (False, None)   # the last presented frame: (it carried a chrome sync, the sync's s)
        self._boosted = False
        self._rm_default = False
        # The CAR section 5 fallback: see _note_registrations, _switch_to_plain and _switch_to_layered.
        self._plain_pending = False
        self._layered_pending = False
        self._failed_opens = 0
        self._plain_since = None
        self._plain_retry_s = PLAIN_RETRY_S
        self._timed_retry = False

    # --------------------------------------------------------------- inputs
    def _text(self):
        if self.text is None:
            self.text = R.TextEngine()
        return self.text

    def on_event(self, kind):
        """Window-procedure side: record; the loop's advance() acts on it."""
        self._pending.add(kind)

    def on_input(self, kind, a=0, b=0):
        """Host input (carousel thread): queued for the Tk side as ('switch'|'cancel'|'turn',
        payload); a turn past either end bumps locally and queues nothing. Ignored unless an
        open picker is interactive."""
        s = self.session
        if s is None or s.exiting or not self.machine.is_open:
            return
        if kind == IN_KEY:
            vk, repeat = int(a), bool(b)
            if vk == VK_ESCAPE and not repeat:
                self.mail.push_event("cancel", None)
            elif vk == VK_RETURN and not repeat:
                self._request_switch()
            elif vk in (VK_LEFT, VK_UP):
                self._turn(-1)
            elif vk in (VK_RIGHT, VK_DOWN):
                self._turn(1)
        elif kind in (IN_WHEEL, IN_HWHEEL):
            delta = int(a)
            if (self._wheel > 0 > delta) or (self._wheel < 0 < delta):
                self._wheel = 0                 # a direction change starts over
            self._wheel += delta
            while abs(self._wheel) >= WHEEL_DELTA:
                step = 1 if self._wheel > 0 else -1
                self._wheel -= step * WHEEL_DELTA
                # wheel down (negative delta) turns forward, like the prototype's deltaY; tilt right too
                self._turn(-step if kind == IN_WHEEL else step)
        elif kind == IN_CLICK:
            # The host is rcMonitor-sized (K4 9.2): client coordinates are host-local.
            rect = s.rects.get(self.machine.sel)
            x, y = int(a), int(b)
            if rect is not None and rect[0] <= x < rect[2] and rect[1] <= y < rect[3]:
                self._request_switch()          # side cards and the rest of the monitor: nothing (CAR dev 5)
        elif kind == IN_CLOSE:
            self.mail.push_event("cancel", None)

    def _request_switch(self):
        if self.machine.can_switch():
            self.mail.push_event("switch", self.machine.sel)

    def _turn(self, direction):
        if self.machine.at_end(direction):
            if self.machine.bump_now(direction, self.clock()) and self.session is not None:
                self._episode = "turn"          # the end bump is a turn at an end (K4 6.2's kinds)
                self.session.dirty = True
            return
        self.mail.push_event("turn", direction)

    # ------------------------------------------------------------- stepping
    def advance(self):
        if self.stopped:
            return None
        now = self.clock()
        self._t_wake = now
        self._oneoff = False               # P1: this wake ran a one-off step (setup, frost upload, warm-up)
        pending, self._pending = self._pending, set()
        with self.mail.lock:
            closing = self.mail.closed
        if EV_STOP in pending or closing:
            self._stop()
            return None
        if EV_SUSPEND in pending and self.session is not None:
            self._teardown(self.session)
            self.mail.push_event("system", "sleep")
        if EV_DISPLAY in pending:
            self._display_changed()
            s = self.session
            if s is not None and not s.exiting:
                self._teardown(s)                              # K4 15: instant, no U12
                self.mail.push_event("closed", "display")
        if EV_OPEN in pending:
            self._open(now)
        if EV_DISMISS in pending:
            self._dismiss(now)
        if EV_SELECT in pending:
            self._select(now)
        if EV_DATA in pending:
            self._data()
        if EV_CAPTURED in pending:
            self._captured(now)
        if EV_WARM in pending:
            self._oneoff = True
            self._gpu_warm()
        self._label_results(now)
        self._toast_results(now)
        self._snap_requests(now)
        self._work_requests(now)
        self._snap_results(now)
        if EV_TOAST in pending:
            self._toast_request(now)
        self._timeouts(now)
        self._toast_results(now)          # an inline worker renders at take time; a threaded one posts
        s = self.session
        if s is not None and s.setup_deadline is not None and (
                EV_ACTIVATED in pending or s.exiting or now >= s.setup_deadline):
            self._setup_layers(s)
        if s is not None and s.exiting and self.machine.exit_done(now):
            self._finish_exit(now)
            s = None
        if self.toast is not None and self.toast.machine.started and self.toast.machine.done(now):
            self._end_toast()
        self._prepared = False
        picker_work = toast_work = False
        frame_t = None
        # s.last_animating: once the motion is over, one more frame is composed at the exact
        # targets with animating=False (LANCZOS sprites, cached shadows, BILINEAR bands).
        # The GPU chrome's want_sync: a sprite a sync needed was not ready (uploaded then, shown a
        # frame later); the loop stays awake until the next sync shows it, at rest too (WP7c-R3).
        if s is not None and s.setup_deadline is None and (
                self.machine.animating(now) or s.dirty or s.rereg or s.release or s.last_animating
                or s.label_dirty or s.dots_dirty or s.gpu_label_wait or s.gpu_prebuild
                or (s.gpu and self.gpu is not None and self.gpu.want_sync)):
            frame_t = self._frame_time(now)
            self._prepare(s, frame_t)
            picker_work = True
        if self.toast is not None and self.toast.sprite is not None:
            wait = self.toast.machine.next_wait(now)
            if not self.toast.shown or self.toast.dirty or wait == 0.0:
                self._prepare_toast(frame_t if frame_t is not None else self._frame_time(now))
                toast_work = True
        self._episode_bookkeeping(now, picker_work, toast_work)
        work = picker_work or toast_work
        if work:
            self._prepared = True
            return 0.0
        self._prefetch()
        self._gpu_idle()
        return self._next_wait(now)

    def _frame_time(self, now):
        """P2: the predicted display time of the frame composed now (``now`` without a pacer)."""
        target = getattr(self.backend, "frame_target", None)
        if target is None:
            return now
        try:
            t = float(target(now))
        except Exception:
            return now
        t = t if now - 1e-3 <= t <= now + 0.1 else now
        s = self.session
        if s is not None and s.gpu and self.thumb_lead > 0.0:
            # AR-12: the thumbnails may lead the compositor-run chrome by whole periods if S1 shows
            # their DwmUpdateThumbnailProperties landing a frame late (0 unless measured).
            pacer = getattr(self.backend, "pacer", None)
            t += self.thumb_lead * float(getattr(pacer, "period", 0.0) or 0.0)
        return t

    def _episode_bookkeeping(self, now, picker_work, toast_work):
        """FrameStats episodes (K4 6.2) and the compositor-clock boost per episode (P11)."""
        animating = picker_work or toast_work
        for surface, active in (("picker", picker_work), ("toast", toast_work)):
            if active and not self.stats.active(surface):
                if surface == "picker":
                    rm = bool(self.session.rm) if self.session is not None else False
                else:
                    rm = bool(self.toast.rm) if self.toast is not None else False
                self.stats.begin(surface, self._episode if surface == "picker" else "toast", now,
                                 self._pacer_switches(), rm=rm)
            elif not active and self.stats.active(surface):
                period, vblank, rate = self._timing()
                self.stats.end(surface, now, period, vblank, self._pacer_switches(), rate, boosted=self._boosted)
        boost = getattr(self.backend, "boost", None)
        want = bool(animating)
        if boost is not None and want != self._boosted:
            try:
                boost(want)
            except Exception:
                pass
            self._boosted = want

    def _pacer_switches(self):
        pacer = getattr(self.backend, "pacer", None)
        return int(getattr(pacer, "switches", 0) or 0)

    def _timing(self):
        pacer = getattr(self.backend, "pacer", None)
        if pacer is None or not hasattr(pacer, "period"):
            return None, None, None
        period = pacer.period
        return period, getattr(pacer, "_vblank", None), round(1.0 / period, 2) if period else None

    def present(self):
        """Right after the compose: re-registration (tray and preview, cards far -> near, then the
        fly), every thumbnail's properties and the chrome ULW back-to-back, the B2 layers, the
        layers' constant alphas; then the toast. The loop paces after it (P3)."""
        if not self._prepared:
            return
        self._prepared = False
        started = self.clock()
        compose = max(0.0, started - (self._t_wake or started))     # K4 5.2 work_ms: wake -> present
        s = self.session
        p5 = True                                                  # P1: this frame counts in P5's window
        if s is not None and s.plan is not None:
            try:
                self._present_session(s)
            except Exception as exc:
                self.status.last_error = f"present: {exc!r}"
                self.log.warn("present", f"carousel: presenting a frame failed: {exc!r}")
            done = self.clock()
            pacer = getattr(self.backend, "pacer", None)
            cadence = getattr(pacer, "cadence", None)     # the cadence this frame was paced at (P5)
            self.stats.frame("picker", done, compose, done - started, detent=s.detent,     # present_ms: the ULWs
                             chrome="gpu" if s.gpu else "cpu", sync_s=s.sync_s,
                             cadence=cadence if isinstance(cadence, int) else None, rereg_s=s.rereg_s)
            s.rereg_s = None
            self.last_detent = (s.detent, s.sync_s)
            p5 = not (s.gpu and s.detent)          # the GPU chrome's detent frames: their own 3.0 ms budget
            s.detent, s.sync_s = False, None
        else:
            self.last_detent = (False, None)
        t = self.toast
        if t is not None and t.prepared:
            t.prepared = False
            begun = self.clock()
            try:
                self.backend.toast_present(t.alpha)
                if not t.shown:
                    self.backend.toast_show()
                    t.shown = True
            except Exception as exc:
                self.log.warn("toast", f"carousel: toast present failed: {exc!r}")
            done = self.clock()
            self.stats.frame("toast", done, compose, done - begun)
        frame_done = getattr(self.backend, "frame_done", None)
        if frame_done is not None and self._t_wake is not None:
            work = self.clock() - self._t_wake
            try:
                frame_done(self._t_wake, work, oneoff=self._oneoff, p5=p5)
            except TypeError:                                      # a backend without P1's flags
                try:
                    frame_done(self._t_wake, work)
                except Exception:
                    pass
            except Exception:
                pass

    def _next_wait(self, now):
        waits = []
        s = self.session
        if s is not None and s.setup_deadline is not None:
            waits.append(max(0.0, s.setup_deadline - now))
        if s is not None and s.glass == "pending" and s.capture_deadline is not None:
            waits.append(max(0.0, s.capture_deadline - now))
        if s is not None:
            # idle-path waits (the P9 allowlist): the snap backstops, failure expiries, the fly's release
            for job in s.jobs.values():
                if job.deadline is not None:
                    waits.append(max(0.0, job.deadline - now))
            for _reason, until, _index in s.failures.values():
                waits.append(max(0.0, until - now))
        for job in self._work_jobs.values():
            if job.deadline is not None:
                waits.append(max(0.0, job.deadline - now))
        if self.gpu is not None and s is None:
            try:
                due = self.gpu.next_wake()          # the idle release of the chrome's device (600 s, K4 4.2)
                if self.chrome_mode == "auto" and getattr(self.gpu, "prewarming", False):
                    due = GPU_PREWARM_GAP_S if due is None else min(due, GPU_PREWARM_GAP_S)
            except Exception:
                due = None
            if due is not None:
                waits.append(max(0.001, due))
        t = self.toast
        if t is not None:
            if t.sprite is None and t.deadline is not None:
                waits.append(max(0.0, t.deadline - now))
            elif t.sprite is not None:
                wait = t.machine.next_wait(now)
                if wait is not None:
                    waits.append(wait)
        return min(waits) if waits else None

    def finish(self):
        """The loop ended (close() or abnormally)."""
        self.stopped = True
        self.session = None
        self.toast = None
        self.status.rect = None

    # ---------------------------------------------------------------- open
    def _publish_open(self, gen, ok, reason=None):
        status = self.status
        with status.cond:
            if ok:
                status.opened_gen = max(status.opened_gen, gen)
            else:
                status.open_failed_gen = max(status.open_failed_gen, gen)
                status.last_error = reason
            status.cond.notify_all()

    def _monitor(self, origin):
        """(rcMonitor, rcWork) of the monitor holding ``origin`` (None: the foreground window)."""
        info = getattr(self.backend, "monitor_info", None)
        if info is not None:
            monitor, work = info(origin)
            return tuple(monitor), (tuple(work) if work else None)
        return tuple(self.backend.monitor_rect(origin)), None

    def _open(self, now):
        req = self.mail.take_open()
        if req is None:
            return
        # Opening an overlay ends any visible toast at once (K4 10.4); its window is excluded from
        # capture first, and the frost capture below waits for a DWM frame (flush).
        toast_ended = self._end_toast()
        self._deferred_toast = None
        if self.session is not None:
            self._teardown(self.session)
        with self.mail.lock:
            given_up = req.gen <= self.mail.dismissed_gen
        if given_up:
            return                                   # the Tk side timed out: never show it late
        backend = self.backend
        if self._plain_pending:
            self._switch_to_plain(now)
        elif backend.host_mode == HOST_PLAIN:
            if self._plain_since is None:
                self._plain_since = now              # plain since creation (NOREDIRECTIONBITMAP failed)
            if self._layered_pending or now - self._plain_since >= self._plain_retry_s:
                self._switch_to_layered(now, timed=not self._layered_pending)
        try:
            monitor, work = self._monitor(req.origin)
            layout = R.layout_for(monitor, work)
            plain = backend.host_mode != HOST_LAYERED
            background = "glass" if plain else req.background
            s = _Session(req, layout, background, plain)
            self.session = s
            self.machine.reset()
            if background == "glass":
                backend.set_affinity(True)       # from show until the frost capture is taken
                s.affinity = True
            # Only what the handshake needs runs before it: our own layers' affinity and
            # SetWindowPos (the host is rcMonitor in v7, K4 9.2).
            shown = bool(backend.show_host(layout.monitor_rect))
        except Exception as exc:
            shown = False
            self.status.last_error = f"open: {exc!r}"
            self.log.warn("open", f"carousel: opening failed: {exc!r}")
        with self.mail.lock:
            given_up = req.gen <= self.mail.dismissed_gen
        if not shown or given_up:
            if self.session is not None:
                self._teardown(self.session)
            self._publish_open(req.gen, False, "the picker window could not be shown" if not shown else
                               "the picker window came up too late")
            return
        self.status.rect = tuple(layout.pane)
        self.status.layout = layout
        self._publish_open(req.gen, True)            # the handshake: the Tk side focuses the host now
        # ------ not on the handshake path from here on (CAR section 1): the machine, the capture job;
        # the heavy setup waits in the loop until the host was activated or ACTIVATION_WAIT_S passed.
        closed = [i for i, ok in enumerate(s.available) if not ok]
        self.machine.start(len(s.items), req.index, now, closed, wide=layout.wide, rm=s.rm)
        self._episode = "open"
        if background == "glass":
            self._set_exclusions(s, tuple(getattr(req, "exclude", ()) or ()))
            s.capture_deadline = now + CAPTURE_TIMEOUT_S
            if not self.capture.submit(CaptureJob(s.gen, "frost", s.frost_rect, layout.k, bool(toast_ended))):
                self._glass_ready(s, None, now)
        self._wheel = 0
        s.setup_deadline = now + ACTIVATION_WAIT_S
        s.dirty = s.rereg = True

    def _setup_layers(self, s):
        """The open's heavy setup, once the host is active (or ACTIVATION_WAIT_S passed, or an
        exit started): the chrome band's DIB, the B2 label and dots layers, the dim's content (No
        background only), the shadows, and the first labels on the worker."""
        s.setup_deadline = None
        self._oneoff = True                  # P1: this frame's work is the setup's, not the loop's
        layout, background = s.layout, s.background
        s.gpu = self._gpu_begin(s)
        try:
            if not s.gpu:
                self._cpu_layers(s)
            if s.dim:
                self.backend.dim_upload(layout, background)
        except Exception as exc:
            self.status.last_error = f"layers: {exc!r}"
            self.log.warn("layers", f"carousel: preparing the layers failed: {exc!r}")
        s.dirty = True
        self._request_labels(s)

    def _cpu_layers(self, s):
        """The CPU chrome's setup (step 1): the band's DIB, the B2 label and dots layers, the shadows."""
        layout = s.layout
        self.backend.chrome_alloc(layout.band)
        self.backend.layer_alloc("label", layout.labels)
        self.backend.layer_alloc("dots", layout.dots)
        if self._shadows is None or self._shadows[0] != layout.k:
            self._shadows = (layout.k, R.ShadowCache(layout.k, s.background))

    # ------------------------------------------------------------ the GPU chrome (CAR 12.4)
    def _gpu_usable(self):
        """The GPU chrome can draw an open: installed, 'auto', the layered host, and the chrome's window
        exists (``has_gpu_window``: the window, not the method that places it; WP7c-R7). Otherwise the
        CPU chrome draws, with no fallback counted and no device warmed."""
        if self.gpu is None or self.chrome_mode != "auto" or self.backend.host_mode != HOST_LAYERED:
            return False
        has = getattr(self.backend, "has_gpu_window", None)
        try:
            return bool(has() if callable(has) else has)
        except Exception:
            return False

    def _gpu_begin(self, s):
        """This open on the GPU chrome: the chrome window placed (hidden) on rcMonitor, the device
        warm, the target, the tree. False: the CPU chrome for this open."""
        if not self._gpu_usable():
            self.status.chrome = "cpu"
            return False
        try:
            hwnd = self.backend.gpu_window(s.layout.monitor_rect)
            ok = bool(hwnd) and bool(self.gpu.begin(hwnd, s.layout, s.background, count=len(s.items)))
        except Exception as exc:
            ok = False
            self.log.warn("gpu", f"carousel: the GPU chrome could not start: {exc!r}")
        if not ok:
            self.status.gpu_fallbacks += 1
            self.status.chrome = "cpu"
            self.log.warn("gpu", "carousel: the GPU chrome is unavailable for this open; the CPU chrome draws it")
            return False
        self.status.gpu_sessions += 1
        self.status.chrome = "gpu"
        return True

    def _gpu_fallback(self, s, why):
        """R-h: the CPU chrome takes over the open picker at once (device loss, a failed sync or a
        failed upload in a quiet frame)."""
        s.gpu = False
        s.gpu_label_wait = s.gpu_prebuild = False       # the CPU label swaps as soon as its sprite exists
        self.status.gpu_fallbacks += 1
        self.status.chrome = "cpu"
        self.log.warn("gpu", f"carousel: the GPU chrome stopped ({why}); the CPU chrome draws this open")
        try:
            self.gpu.end()
        except Exception:
            pass
        try:
            self.backend.gpu_hide()
        except Exception:
            pass
        s.gpu_shown = s.gpu_synced = False
        try:
            self._cpu_layers(s)
        except Exception as exc:
            self.log.warn("layers", f"carousel: preparing the layers failed: {exc!r}")
        s.layers_shown = False
        s.label_key = None                   # the label and the dots are composed again on the CPU
        s.dots_key = None
        s.marker_px = None
        s.chrome_box = None
        s.dirty = s.label_dirty = s.dots_dirty = True

    def _gpu_warm(self):
        """A knob touch (``note_touch``): start the GPU chrome's device while nothing is open, never
        on this thread's handshake path (WP7c-R6): the chrome makes the slow half on a worker, whose
        end posts WM_APP_WARM again, and this thread adopts it (about 1 ms). An open that arrives
        first answers its handshake at once and waits for the half in its setup."""
        if not self._gpu_usable() or self.session is not None:
            return
        try:
            monitor, _work = self._monitor(None)
            l, t, r, b = monitor
            rect = (l, t, r - l, b - t)
            start = getattr(self.gpu, "warm_async", None)
            if start is None:
                self.gpu.warm(rect)
            else:
                start(rect, notify=self._warm_done)
        except Exception as exc:
            self.log.warn("gpu-warm", f"carousel: warming the GPU chrome failed: {exc!r}")

    def _warm_done(self):
        """The warm-up worker finished (called on that worker): wake this thread to adopt it."""
        self.backend.post(WM_APP_WARM)

    def _gpu_idle(self):
        """The idle path: the device's 600 s release, and the segment tables' warm-up in 2 ms steps
        (so no detent ever fits a table; shared with the stage thread's own warm-up)."""
        if self.gpu is not None and self.session is None:
            try:
                self.gpu.idle()
                if self.chrome_mode == "auto" and getattr(self.gpu, "prewarming", False):
                    self.gpu.prewarm_step(GPU_PREWARM_STEP_S)
            except Exception:
                pass

    # -------------------------------------------------------------- updates
    def _select(self, now):
        req = self.mail.take_select()
        s = self.session
        if req is None or s is None or req.gen != s.gen or s.exiting:
            return
        if req.available is not None and len(req.available) == len(s.available):
            for i, ok in enumerate(req.available):
                if s.available[i] and not ok:
                    s.available[i] = False       # closed windows never come back
                    if i in s.thumbs:
                        s.release.add(i)
                    s.dirty = True
            self.machine.set_closed(i for i, ok in enumerate(s.available) if not ok)
        if self.machine.select(req.index, now):
            self._episode = "turn"
            s.rereg = True
            s.dirty = True
            self._request_labels(s)
        bump = int(getattr(req, "bump", 0) or 0)
        if bump and self.machine.bump_now(bump, now):
            self._episode = "turn"              # the end bump is a turn at an end (K4 6.2's kinds)
            s.dirty = True

    def _data(self):
        icons, labels, seq = self.mail.take_data()
        if seq == self._data_seq:
            return
        self._data_seq = seq
        self._icons = dict(icons or {})
        self._labels = dict(labels or {})
        if self.session is not None:
            self.session.dirty = True
            self._request_labels(self.session)

    def _dismiss(self, now):
        d = self.mail.take_dismiss()
        if d is None:
            return
        s = self.session
        if s is None or d.gen != s.gen:
            return
        if s.exiting:
            return                                # hide() never cuts an exit short (close() does)
        if d.mode == "hide":
            self._teardown(s)                     # focus loss, lock, display, any plain dismissal: instant
            return
        s.exiting = d.mode
        s.rereg = False                           # nothing registers after dismissal
        try:
            self.backend.set_host_passive(True)  # topmost, never activating during the exit
        except Exception:
            pass
        self.machine.start_exit(d.mode, now)
        self._episode = "close"
        s.dirty = True

    def _finish_exit(self, now):
        s = self.session
        self._teardown(s)
        deferred, self._deferred_toast = self._deferred_toast, None
        if deferred is not None:
            self._show_toast(deferred, now)

    def _timeouts(self, now):
        s = self.session
        if s is not None and s.glass == "pending" and s.capture_deadline is not None and now >= s.capture_deadline:
            self.log.warn("capture-timeout", "carousel: the frost capture timed out; using the plain tint")
            self._glass_ready(s, None, now)
        if s is not None:
            for job in list(s.jobs.values()):
                if job.deadline is not None and now >= job.deadline - TIME_EPSILON:
                    self._backstop(s, job, now)
            expired = [side for side, (_r, until, _i) in s.failures.items() if now >= until - TIME_EPSILON]
            for side in expired:
                del s.failures[side]
            if expired:
                self._update_slots(s, now)
            if s.fly is not None and now - s.fly["t0"] >= FLY_RELEASE_S - TIME_EPSILON:
                s.fly = None
                self._release_extra(s, "fly")
                s.dirty = True
        for job_id, job in list(self._work_jobs.items()):
            if job.deadline is not None and now >= job.deadline - TIME_EPSILON:
                del self._work_jobs[job_id]
                if job.resolve("move_rejected", "carousel"):
                    self.status.snap_backstops += 1
                    self.mail.push_event("complete_result", (job.id, False))
        t = self.toast
        if t is not None and t.sprite is None and t.deadline is not None and now >= t.deadline:
            t.deadline = None                      # no glass in time: the tint-only pill, already rendered
            if t.plain is not None:
                self._toast_show(t, t.plain, now)
        elif t is not None and t.deadline is not None and t.sprite is not None and now >= t.deadline:
            t.deadline = None                      # a replacement's fresh capture never came: keep the old glass
            try:
                self.backend.set_toast_affinity(False)
            except Exception:
                pass

    def _captured(self, now):
        for result in self.capture.take_results():
            if result.kind == "frost":
                s = self.session
                if s is None or result.gen != s.gen or s.glass != "pending":
                    continue
                self.status.capture_ms, self.status.glass_ms = result.capture_ms, result.build_ms
                if result.error:
                    self.log.warn("capture", f"carousel: frost capture failed: {result.error}")
                self._glass_ready(s, result.image, now)
            elif result.kind == "toast":
                t = self.toast
                if t is None or result.gen != t.gen:
                    continue
                if result.image is not None:
                    t.backdrop = result.image
                    self._render_toast(t, t.backdrop, "glass")   # the glass pill, on NanoD-label
                elif t.sprite is None and t.plain is not None:
                    t.deadline = None
                    self._toast_show(t, t.plain, now)            # the capture failed: the tint alone

    def _glass_ready(self, s, image, now):
        """The frost arrived (a premultiplied Canvas from frost_canvas, or a straight image), or its
        capture failed or timed out (None). The layered host uploads it into the monitor-sized
        glass window at constant alpha 0 (the machine then fades it in); the plain host paints
        it itself, and without a capture keeps its flat colour."""
        if image is None:
            self.status.glass_fallbacks += 1
            image = None if s.plain else R.solid_frost(s.frost_rect[2:])
        self._oneoff = True                  # P1: the frost's upload (about 13 ms at 32:9) is no loop work
        started = time.perf_counter()
        uploaded = False
        try:
            if s.plain:
                if image is not None and self.backend.host_mode == HOST_PLAIN:
                    uploaded = True
                    self.backend.host_paint(image)
            elif not s.exiting:
                uploaded = True
                self.backend.glass_upload(s.frost_rect, image)
        except Exception as exc:
            self.log.warn("glass", f"carousel: frost upload failed: {exc!r}")
        if uploaded:
            ms = round((time.perf_counter() - started) * 1000, 3)
            self.status.glass_upload_ms = ms
            self.status.glass_upload_ms_max = max(self.status.glass_upload_ms_max, ms)
        s.glass = "ready"
        if s.affinity:
            try:
                self.backend.set_affinity(False)   # screenshots and sharing see the picker again
            except Exception:
                pass
            s.affinity = False
        self._set_exclusions(s, ())
        self.machine.set_glass_ready(now)
        s.dirty = True

    def _set_exclusions(self, s, hwnds):
        """Other windows of this process named by the Tk side (set_capture_exclusions: the
        floating knob) get WDA_EXCLUDEFROMCAPTURE with our own layers while the frost capture
        runs, so they are never blurred into it; ``()`` clears the ones set. Best effort."""
        hwnds = tuple(int(h) for h in hwnds if h)
        previous, s.exclusions = s.exclusions, hwnds
        change = hwnds or previous
        setter = getattr(self.backend, "set_capture_exclusions", None)
        if not change or setter is None:
            return
        try:
            setter(hwnds or previous, bool(hwnds))
        except Exception as exc:
            self.log.warn("exclusions", f"carousel: capture exclusions failed: {exc!r}")

    # ---------------------------------------------------------------- snap (K4 9.4-9.7)
    def _snap_requests(self, now):
        snaps = self.mail.take_snaps()
        for req in snaps:
            s = self.session
            side = req.side if req.side in SIDES else None
            if (s is None or req.gen != s.gen or s.exiting or side is None or self.snapper is None
                    or not 0 <= int(req.index) < len(s.items)):
                self.mail.push_event("snap_result", (side, "move_rejected"))
                continue
            index = int(req.index)
            info = s.items[index]
            item = {"hwnd": info.hwnd, "pid": info.pid, "id": info.id, "class_name": info.class_name,
                    "exstyle": info.exstyle, "available": s.available[index]}
            for key in ("hwnd", "pid", "id", "class_name", "exstyle", "available"):
                if isinstance(req.item, dict) and req.item.get(key) is not None:
                    item[key] = req.item[key]
            target = _rect4(req.target) if req.target is not None else None
            target = target or s.layout.half(side)
            t0 = float(req.t0) if req.t0 is not None and abs(float(req.t0) - now) <= T0_TRUST_S else now
            job = SnapJob("snap", side=side, item=item, target=target, t0=t0, place_at=t0 + SNAP_PLACE_S,
                          deadline=t0 + SNAP_DEADLINE_S)
            job.index = index
            s.jobs[job.id] = job
            self.status.snaps += 1
            if not self.snapper.submit(job):
                self._backstop(s, job, now)

    def _backstop(self, s, job, now):
        """K4 9.6: no result by the deadline (the worker died or hangs): ``move_rejected`` from
        here; the first result for a job wins and the worker's late one is dropped."""
        s.jobs.pop(job.id, None)
        if job.resolve("move_rejected", "carousel"):
            self.status.snap_backstops += 1
            self.mail.push_event("snap_result", (job.side, "move_rejected"))
            self._snap_failed(s, job, "move_rejected", now)

    def _work_requests(self, now):
        for req in self.mail.take_work():
            job = req.job
            if self.snapper is None:
                if job.kind == "complete":
                    self.mail.push_event("complete_result", (job.id, False))
                continue
            if job.kind == "complete":
                self._work_jobs[job.id] = job
            if not self.snapper.submit(job) and job.kind == "complete":
                self._work_jobs.pop(job.id, None)
                self.mail.push_event("complete_result", (job.id, False))

    def _snap_results(self, now):
        if self.snapper is None:
            return
        for job, stage, outcome, info in self.snapper.take_results():
            if job.kind == "complete":
                self._work_jobs.pop(job.id, None)
                self.mail.push_event("complete_result", (job.id, outcome == "ok"))
                continue
            s = self.session
            live = s is not None and job.id in s.jobs
            if stage == "precheck" and outcome == "accepted":
                if not live or job.resolved_by == "carousel":
                    continue
                self.mail.push_event("snap_result", (job.side, "accepted"))
                self._accept(s, job, now)
                continue
            if not live:
                continue
            del s.jobs[job.id]
            self.mail.push_event("snap_result", (job.side, outcome))
            if outcome == "ok":
                self._placed(s, job, info, now)
            else:
                self._snap_failed(s, job, outcome, now)

    def _accept(self, s, job, now):
        """``accepted`` (K4 9.5 t = 0): the side is assigned (a move clears the other side if the
        same window held it, BS:1078), the slot fills, the chip and the suffix appear, the first
        snap reveals the tray, and the fly starts (no fly under reduced motion)."""
        side, index = job.side, job.index
        other = _other(side)
        if s.sides[other] == index:
            s.sides[other] = None
            self._release_extra(s, other)
        if s.sides[side] is not None and s.sides[side] != index:
            self._release_extra(s, side)
        s.sides[side] = index
        s.failures.pop(side, None)
        self.machine.reveal_tray(now)
        self._episode = "snap"
        if not s.rm:
            start = s.rects.get(index)
            if start is None:
                frame = self.machine.values(now)
                for cf in frame.cards:
                    if cf.index == index:
                        start = R.card_rect(s.layout, cf.x + frame.bump, cf.s, cf.y)
            if start is not None:
                if s.fly is not None:
                    self._release_extra(s, "fly")
                s.fly = {"index": index, "hwnd": s.items[index].hwnd, "start": tuple(start),
                         "target": R.fly_target(s.layout, job.target), "t0": now}
        s.rereg = True                  # the slot's thumbnail goes below the cards, the fly on top
        self._update_slots(s, now)
        s.dirty = True
        self._request_labels(s)

    def _placed(self, s, job, info, now):
        """``ok``: the source changed shape; rcSource is recomputed for the card, the slot and
        the fly from a re-queried size. Step 8: the picker host must still own the foreground."""
        hwnd = s.items[job.index].hwnd
        handle = s.thumbs.get(job.index)
        if handle is not None:
            size = self.backend.source_size(handle)
            if _usable_size(size):
                s.sizes[job.index] = size
        for key, (handle, source) in list(s.extra.items()):
            if source == hwnd:
                size = self.backend.source_size(handle)
                if _usable_size(size):
                    s.extra_sizes[hwnd] = size
        refocus = getattr(self.backend, "refocus_host", None)
        if refocus is not None and not s.exiting:
            try:
                refocus()
            except Exception:
                pass
        s.dirty = True

    def _snap_failed(self, s, job, outcome, now):
        side, index = job.side, getattr(job, "index", None)
        if job.accepted and index is not None and s.sides.get(side) == index:
            s.sides[side] = None
            self._release_extra(s, side)
        s.failures[side] = (outcome, now + FAILURE_S, index)
        self.machine.reveal_tray(now)
        self._episode = "snap"
        self._update_slots(s, now)
        s.dirty = True
        self._request_labels(s)

    def _keep_side(self, s):
        """The one-side preview (U12; BS:1160): the empty side while exactly one side is filled and
        the origin window (the foreground window at open) holds neither side; else None."""
        filled = [side for side in SIDES if s.sides[side] is not None]
        if len(filled) != 1 or s.origin_index is None or s.origin_index in s.sides.values():
            return None
        if not s.available[s.origin_index]:
            return None
        return _other(filled[0])

    def _update_slots(self, s, now):
        keep = self._keep_side(s)
        for side in SIDES:
            failure = side in s.failures and now < s.failures[side][1]
            self.machine.set_slot(side, s.sides[side] is not None, keep == side, failure, now)
        if keep is None and "keep" in s.extra:
            self._release_extra(s, "keep")
        elif keep is not None and "keep" not in s.extra:
            s.rereg = True
        s.dirty = True

    def _release_extra(self, s, key):
        entry = s.extra.pop(key, None)
        if entry is not None:
            self._unregister(entry[0])

    def _side_of(self, s, index):
        for side in SIDES:
            if s.sides[side] == index:
                return side
        return None

    # ---------------------------------------------------------------- labels (B1)
    def _label_for(self, item):
        label = self._labels.get(item.id)
        if label is None or not hasattr(label, "title"):
            label = R.fallback_label({"app": item.app, "title": item.title, "minimized": item.minimized})
        return label

    def _closed_label(self, label):
        try:
            from .window_labels import closed_label
            return closed_label(label)
        except Exception:
            return R.SimpleLabel(getattr(label, "app", ""), getattr(label, "title", ""), R.CLOSED_DESC)

    def _label_job(self, s, index):
        if not 0 <= index < len(s.items):
            return None
        item = s.items[index]
        label = self._label_for(item)
        if not s.available[index]:
            label = self._closed_label(label)
        side = self._side_of(s, index)
        suffix = R.SNAPPED_DESC[side] if side else ""
        icon = self._icons.get(item.id)
        key = (item.id, getattr(label, "app", ""), getattr(label, "title", ""), getattr(label, "desc", ""), suffix,
               id(icon), s.layout.k, s.background)
        return LabelJob(key, label, _master_icon(icon) if icon is not None else None, s.layout.k, s.background, suffix)

    def _request_labels(self, s):
        """B1: the centre label first, then +-3 by distance; cached ones are skipped."""
        if self.labeler is None or s.setup_deadline is not None:
            return
        sel = self.machine.exit_index if self.machine.exit_kind else self.machine.sel
        order = [sel] + [i for d in range(1, LABEL_PREFETCH + 1) for i in (sel + d, sel - d)]
        jobs = []
        for index in order:
            job = self._label_job(s, index)
            if job is not None and job.key not in self._label_cache:
                jobs.append(job)
        self.labeler.submit(jobs)

    def _label_results(self, now):
        if self.labeler is None:
            return
        results = self.labeler.take_results()
        for key, sprite in results:
            self._label_cache[key] = sprite
            self._label_cache.move_to_end(key)
            while len(self._label_cache) > LABEL_CACHE:
                self._label_cache.popitem(last=False)
        if results and self.session is not None:
            self.session.dirty = True

    def _prefetch(self):
        """Idle: nothing to render here any more (B1 renders on the worker); kept for the loop."""
        return None

    def _update_label(self, s, now):
        """S5-24: the label swaps once the new sprite exists (the previous one stays until then).
        K4 9.3 / 9.8 "swap at the detent, then fade in over 160 ms": only a label for another
        card (the selection moved, or the first label of an open) fades in. A new sprite for the
        same card (the snapped suffix appearing or going, set_labels / set_icons data, a card
        that closed) replaces the sprite at the current opacity, with no blink (BS:1340's
        ``_labKey`` leaves the suffix and the data out; WP7b-R4)."""
        index = self.machine.exit_index if self.machine.exit_kind else self.machine.sel
        job = self._label_job(s, index)
        if job is None or job.key == s.label_key:
            return
        hit = self._label_cache.get(job.key, False)
        if hit is False:
            self.status.label_late += 1 if s.label_key is not None else 0
            if self.labeler is not None and job.key not in self.labeler.pending():
                self._request_labels(s)
            return
        if s.gpu and not self._gpu_label_ready(hit):
            s.gpu_label_wait = True                 # uploaded by the next event-free frame, shown a frame later
            return
        moved = s.label_index != index
        s.gpu_label_wait = False
        s.label_key, s.label, s.label_index = job.key, hit, index
        s.label_dirty = True
        self.status.label_swaps += 1
        if moved and not self.machine.exit_kind:
            self.machine.label_swap(now)

    # --------------------------------------------------------------- frames
    def _sprite(self, kind, item, build):
        """A card's badge / placeholder / slot badge sprite, cached per (kind, item id) in a small
        LRU that hide clears: item ids are per window instance, so nothing may accumulate over a
        24/7 run (CAR section 5 memory)."""
        icon = self._icons.get(item.id)
        label = self._label_for(item)
        key = (id(icon), icon, label.app, self.session.layout.k if self.session else None)
        slot = (kind, item.id)
        hit = self._sprites.get(slot)
        if hit is not None and hit[0][0] == key[0] and hit[0][1] is key[1] and hit[0][2:] == key[2:]:
            self._sprites.move_to_end(slot)
            return hit[1]
        try:
            value = build(_master_icon(icon) if icon is not None else None, label.app or item.app)
        except Exception as exc:
            self.log.warn("sprite", f"carousel: icon sprite failed: {exc!r}")
            value = None
        self._sprites[slot] = (key, value)
        self._sprites.move_to_end(slot)
        while len(self._sprites) > SPRITE_CACHE:
            self._sprites.popitem(last=False)
        return value

    def _chip(self, side, k):
        key = (side, k)
        chip = self._chips.get(key)
        if chip is None:
            try:
                chip = self._chips[key] = R.chip_sprite(side, k, self._text())
            except Exception as exc:
                self.log.warn("chip", f"carousel: chip failed: {exc!r}")
                return None
        return chip

    def _glyph(self, side, k):
        key = (side, k)
        glyph = self._glyphs.get(key)
        if glyph is None:
            glyph = self._glyphs[key] = R.slot_glyph_sprite(side, k)
        return glyph

    def _caption(self, s, side, now):
        """The slot caption (K4 9.4; VOC overlay.picker.slot_*): failure > filled > keep > empty."""
        name = R.SNAP_BADGE[side]
        failure = s.failures.get(side)
        if failure is not None and now < failure[1]:
            index = failure[2]
            app = self._label_for(s.items[index]).app if index is not None and 0 <= index < len(s.items) else ""
            text = {"hung": f"{app} isn’t responding", "cant_fit": f"{app} can’t fit half"}.get(
                failure[0], f"Couldn’t move {app}")
            ink = "failure"
        elif s.sides[side] is not None:
            text, ink = f"{name}{R.SEP}{self._label_for(s.items[s.sides[side]]).app}", "normal"
        elif self._keep_side(s) == side:
            text, ink = f"{name}{R.SEP}keeps {self._label_for(s.items[s.origin_index]).app}", "keep"
        else:
            text, ink = f"Snap {side}", "normal"
        key = (side, text, ink, s.layout.k)
        sprite = self._captions.get(key)
        if sprite is None:
            try:
                sprite = R.caption_sprite(R.SLOT_KEYS[side], text, R.CAPTION_INKS[ink], s.layout.k, self._text())
            except Exception as exc:
                self.log.warn("caption", f"carousel: caption failed: {exc!r}")
                sprite = None
            self._captions[key] = sprite
            while len(self._captions) > 8:
                self._captions.popitem(last=False)
        return sprite

    def _wanted(self, s, now_ops):
        """Indices to register at a re-registration: |d| <= a_vis + 1 (K4 9.3), plus cards beyond it
        that are still visibly fading out (CAR dev 10); present() releases them at the first frame
        that no longer draws them. Never closed, failed or stub cards. Far -> near (z-order is
        registration order)."""
        sel = self.machine.sel
        reach = s.layout.register_distance
        wanted = []
        for i in range(len(s.items)):
            if not s.available[i] or i in s.failed or i in s.stubs:
                continue
            if abs(i - sel) <= reach or now_ops.get(i, 0.0) > 0.004:
                wanted.append(i)
        wanted.sort(key=lambda i: -abs(i - sel))
        return wanted

    def _prepare(self, s, now):
        """Frame values -> integer card rects (once) -> the thumbnails plan -> chrome compose (B5
        dirty rect) -> the B2 layers' state. On the GPU chrome: the thumbnails plan only, and the
        chrome's sync when an event changed something (``_prepare_gpu``)."""
        if s.gpu:
            return self._prepare_gpu(s, now)
        started = time.perf_counter()
        self._update_label(s, now)
        frame = self.machine.values(now)
        layout = s.layout
        rects = {}
        ops = {}
        for cf in frame.cards:
            rects[cf.index] = R.card_rect(layout, cf.x + frame.bump, cf.s, cf.y)
            ops[cf.index] = cf.op
        s.rects = rects
        wanted = self._wanted(s, ops) if s.rereg else None
        plan = {}
        cards = []
        ordered = sorted(frame.cards, key=lambda cf: (-abs(cf.d), cf.index))
        for cf in ordered:
            item = s.items[cf.index]
            registered = cf.index in s.thumbs and cf.index not in s.release
            pending = wanted is not None and cf.index in wanted
            placeholder = uses_placeholder(s.available[cf.index], registered, cf.index in s.failed,
                                           cf.index in s.stubs, pending)
            if not placeholder:
                plan[cf.index] = (rects[cf.index], R.thumb_opacity(cf.op, cf.shade))
            badge = self._sprite("badge", item, lambda icon, name: R.badge_sprite(icon, name, layout.k, self._text()))
            holder = (self._sprite("placeholder", item,
                                   lambda icon, name: R.placeholder_sprite(icon, name, layout.k, self._text()))
                      if placeholder else None)
            side = self._side_of(s, cf.index)
            cards.append(R.ChromeCard(rects[cf.index], cf.s, cf.op, cf.shade, cf.selw, badge, holder, cf.index,
                                      cf.cover, self._chip(side, layout.k) if side else None))
        tray = []
        extra_plan = {}
        if self.machine.tray_on:
            keep = self._keep_side(s)
            opacity = frame.tray_op * frame.root
            for side in SIDES:
                values = frame.slots[side]
                rect = R.slot_rect(layout, side, frame.tray_y, frame.tray_sc)
                index = s.sides[side]
                badge = (self._sprite("slot", s.items[index],
                                      lambda icon, name: R.slot_badge_sprite(icon, name, layout.k, self._text()))
                         if index is not None else None)
                tray.append(R.TraySlot(side, rect, frame.tray_sc, opacity, values.fill, dict(values.borders),
                                       values.glyph, badge, values.badge, self._caption(s, side, now),
                                       self._glyph(side, layout.k)))
                if index is not None and s.available[index]:
                    extra_plan[side] = (s.items[index].hwnd, rect, values.fill * opacity)
                elif keep == side and s.origin_index is not None:
                    extra_plan["keep"] = (s.items[s.origin_index].hwnd, rect, values.ghost * opacity)
        if s.fly is not None:
            elapsed = now - s.fly["t0"]
            e = EASE_OUT(min(1.0, max(0.0, elapsed / FLY_S)))
            fade = 0.0 if elapsed <= FLY_FADE_AT else EASE_OUT(min(1.0, (elapsed - FLY_FADE_AT) / FLY_FADE_S))
            extra_plan["fly"] = (s.fly["hwnd"], R.fly_rect(s.fly["start"], s.fly["target"], e), 1.0 - fade)
        s.extra_plan = extra_plan
        s.plan = (plan, wanted)
        animating = self.machine.animating(now) or s.fly is not None
        s.last_animating = animating
        scene = R.ChromeScene(layout.k, layout.band_origin, s.background, cards, tray, animating)
        canvas = self.backend.chrome_canvas()
        if canvas is not None:
            try:
                current = R.scene_footprint(scene, self._shadows[1])
                dirty = R._union(s.chrome_box, current)
                scene.clear = dirty if s.chrome_box is not None else None
                drawn = R.compose_chrome(canvas, scene, self._shadows[1], self._scaler)
                s.chrome_box = drawn if drawn is not None else (0, 0, 1, 1)
                s.chrome_dirty = scene.clear
            except Exception as exc:
                self.status.last_error = f"compose: {exc!r}"
                self.log.warn("compose", f"carousel: chrome compose failed: {exc!r}")
        self._prepare_layers(s, frame)
        s.dim_target = frame.dim
        s.glass_target = frame.glass
        s.dirty = False
        ms = round((time.perf_counter() - started) * 1000, 3)
        self.status.compose_ms = ms
        self.status.compose_ms_max = max(self.status.compose_ms_max, ms)

    def _prepare_layers(self, s, frame):
        """B2: the label and dots layers. Their content is composed only when it changes (a
        label swap; the dots row or the marker moved); the group's fades are constant alphas and
        its shift a window move."""
        layout = s.layout
        k = layout.k
        dy = round(frame.shift * k)
        stage_x, stage_y = layout.stage_x, layout.stage_y
        visible = frame.root * frame.group
        # the label
        alpha = round(255 * max(0.0, min(1.0, visible * frame.label_alpha))) if s.label is not None else 0
        s.frame_label = (alpha, (layout.labels[0], layout.labels[1] + dy))
        if s.label_dirty:
            canvas = self.backend.layer_canvas("label")
            if canvas is not None:
                ox, oy = layout.labels[0] - stage_x, layout.labels[1] - stage_y
                sprites = []
                label = s.label
                if label is not None and label.sprite is not None:
                    if label.shadow is not None:
                        sprites.append((label.shadow, (label.x - ox, label.y - oy), 1.0))
                    sprites.append((label.sprite, (label.x - ox, label.y - oy), 1.0))
                R.compose_layer(canvas, sprites)
        # the dots
        first, shown, opacities = R.dots_window(len(s.items), self.machine.sel)
        key = (opacities, k)
        if key != s.dots_key:
            s.dots_key = key
            s.dots = R.render_dots(opacities, k) if shown else None
            s.dots_dirty = True
        marker_px = round(R.marker_x(shown, frame.marker) * k) if shown else None
        if marker_px != s.marker_px:
            s.marker_px = marker_px
            s.dots_dirty = True
        s.frame_dots = (round(255 * max(0.0, min(1.0, visible))) if shown else 0, (layout.dots[0], layout.dots[1] + dy))
        if s.dots_dirty:
            canvas = self.backend.layer_canvas("dots")
            if canvas is not None:
                ox, oy = layout.dots[0] - stage_x, layout.dots[1] - stage_y
                sprites = []
                if s.dots is not None:
                    sprite, x, y = s.dots
                    sprites.append((sprite, (x - ox, y - oy), 1.0))
                    if self._marker is None or self._marker[0] != k:
                        self._marker = (k, R.marker_sprite(k))
                    sprites.append((self._marker[1], (marker_px - ox, round(R.DOTS_TOP * k) - oy), 1.0))
                R.compose_layer(canvas, sprites)

    # ------------------------------------------------------------ the GPU chrome's frames (CAR 12.4)
    def _prepare_gpu(self, s, now):
        """Step 3's frame: the thumbnails' rects and opacities at the predicted display time (the
        same maths as the CPU path: card_rect, thumb_opacity, slot_rect, fly_rect), and, only when an
        event changed something (``s.dirty``, a label swap, the dots), one sync of the chrome (its
        compositor-run animations then need nothing per frame). A chrome that stopped outside a sync
        (a failed upload in a quiet frame: device loss surfaces in CreateSurface or UpdateSubresource,
        K4 4.3) hands this open to the CPU chrome at once, in this frame (R-h; WP7c-R2)."""
        if not self.gpu.active:
            self._gpu_fallback(s, "the chrome's device failed")
            return self._prepare(s, now)
        started = time.perf_counter()
        self._update_label(s, now)
        frame = self.machine.values(now)
        layout = s.layout
        rects = {}
        ops = {}
        for cf in frame.cards:
            rects[cf.index] = R.card_rect(layout, cf.x + frame.bump, cf.s, cf.y)
            ops[cf.index] = cf.op
        s.rects = rects
        wanted = self._wanted(s, ops) if s.rereg else None
        plan = {}
        for cf in frame.cards:
            registered = cf.index in s.thumbs and cf.index not in s.release
            pending = wanted is not None and cf.index in wanted
            if not uses_placeholder(s.available[cf.index], registered, cf.index in s.failed, cf.index in s.stubs,
                                    pending):
                plan[cf.index] = (rects[cf.index], R.thumb_opacity(cf.op, cf.shade))
        extra_plan = {}
        if self.machine.tray_on:
            keep = self._keep_side(s)
            opacity = frame.tray_op * frame.root
            for side in SIDES:
                values = frame.slots[side]
                rect = R.slot_rect(layout, side, frame.tray_y, frame.tray_sc)
                index = s.sides[side]
                if index is not None and s.available[index]:
                    extra_plan[side] = (s.items[index].hwnd, rect, values.fill * opacity)
                elif keep == side and s.origin_index is not None:
                    extra_plan["keep"] = (s.items[s.origin_index].hwnd, rect, values.ghost * opacity)
        if s.fly is not None:
            elapsed = now - s.fly["t0"]
            e = EASE_OUT(min(1.0, max(0.0, elapsed / FLY_S)))
            fade = 0.0 if elapsed <= FLY_FADE_AT else EASE_OUT(min(1.0, (elapsed - FLY_FADE_AT) / FLY_FADE_S))
            extra_plan["fly"] = (s.fly["hwnd"], R.fly_rect(s.fly["start"], s.fly["target"], e), 1.0 - fade)
        s.extra_plan = extra_plan
        s.plan = (plan, wanted)
        s.last_animating = self.machine.animating(now) or s.fly is not None
        s.detent, s.sync_s = False, None
        if s.dirty or s.label_dirty or s.dots_dirty or not s.gpu_synced or self.gpu.want_sync:
            self._gpu_dots(s)
            stats = self._gpu_sync(s, now, wanted)
            if stats is None:
                self._gpu_fallback(s, "the chrome's device failed")
                return self._prepare(s, now)
            s.detent, s.sync_s = True, stats["ms"] / 1000.0
            s.gpu_synced = True
            s.label_dirty = s.dots_dirty = False
        elif not s.rereg:
            self._gpu_prefetch(s)                   # never in the frame that re-registers (the detent's next)
            if not self.gpu.active:                 # an upload failed: the CPU chrome draws this very frame
                self._gpu_fallback(s, "the chrome's device failed")
                return self._prepare(s, now)
        s.dim_target = frame.dim
        s.glass_target = frame.glass
        s.dirty = False
        ms = round((time.perf_counter() - started) * 1000, 3)
        self.status.compose_ms = ms
        self.status.compose_ms_max = max(self.status.compose_ms_max, ms)

    def _sprite_cached(self, kind, item):
        """The cached sprite of ``_sprite`` (kind, item), or False when it would have to be built."""
        hit = self._sprites.get((kind, item.id))
        if hit is None:
            return False
        icon = self._icons.get(item.id)
        label = self._label_for(item)
        key = (id(icon), icon, label.app, self.session.layout.k if self.session else None)
        if hit[0][0] == key[0] and hit[0][1] is key[1] and hit[0][2:] == key[2:]:
            return hit[1]
        return False

    def _gpu_prefetch(self, s):
        """A frame without an event (CAR 12.4): upload the selected label if it waits, else grow the
        chrome's card pool by one slot while few are free (K4 4.7.1: no object is made in a detent's
        batch; WP7c-R4), else build at most one missing badge of a card the machine holds (nearest
        first) and upload one sprite the next detents will show (the badge at the level its card
        will use, a chip, the tray's glyphs). The next event's Commit carries these a frame or more
        later, when that costs about 0.1 ms instead of about 3 ms, so a detent's batch never
        builds, creates or uploads."""
        m = self.machine
        k = s.layout.k
        uploads = 0
        index = self.machine.exit_index if self.machine.exit_kind else self.machine.sel
        job = self._label_job(s, index)
        label = self._label_cache.get(job.key) if job is not None else None
        if label is not None and getattr(label, "sprite", None) is not None:
            uploads += self.gpu.prepare(label.sprite, "label")
            if getattr(label, "shadow", None) is not None:
                uploads += self.gpu.prepare(label.shadow, "label.shadow")
        if uploads or not self.gpu.active:
            return
        grow = getattr(self.gpu, "grow_pool", None)
        if grow is not None and grow(len(s.items)):
            return
        built = False
        for index in sorted(m.cards, key=lambda i: (abs(i - m.sel), i)):
            if not 0 <= index < len(s.items):
                continue
            item = s.items[index]
            badge = self._sprite_cached("badge", item)
            if badge is False:
                if built:
                    break
                built = True
                badge = self._sprite("badge", item, lambda icon, name: R.badge_sprite(icon, name, k, self._text()))
            if badge is None:
                continue
            d = abs(index - m.sel)
            levels = ("full", "half") if d == 1 else ("full",) if d == 0 else ("half",)
            if self.gpu.prepare(badge[0], "badge", levels):
                return                              # at most one sprite's uploads per frame
        for side in SIDES:
            if s.sides[side] is not None and self.gpu.prepare(self._chip(side, k), "chip", ("full", "half")):
                return
        if built:
            return
        for side in SIDES:                          # the tray's glyphs, before the first snap reveals it
            if self.gpu.prepare(self._glyph(side, k), "slot.glyph"):
                return
        self._gpu_prebuild_snap(s)

    def _gpu_snap_sprites(self, s):
        """[(what, build)] a snap of the selected card would show at once and is not built yet: the
        chips, the card's slot badge, the slot captions of either outcome (CAR 12.4)."""
        m = self.machine
        if m.exit_kind or not 0 <= m.sel < len(s.items):
            return []
        k = s.layout.k
        item = s.items[m.sel]
        out = []
        for side in SIDES:
            if (side, k) not in self._chips:
                out.append(lambda side=side: self._chip(side, k))
        if self._sprite_cached("slot", item) is False:
            out.append(lambda: self._sprite("slot", item, lambda icon, name: R.slot_badge_sprite(icon, name, k,
                                                                                                 self._text())))
        app = self._label_for(item).app
        for side in SIDES:
            for text in (f"{R.SNAP_BADGE[side]}{R.SEP}{app}", f"Snap {side}"):
                key = (side, text, "normal", k)
                if key not in self._captions:
                    out.append(lambda key=key, side=side, text=text: self._prebuilt_caption(key, side, text, k))
        return out

    def _prebuilt_caption(self, key, side, text, k):
        try:
            self._captions[key] = R.caption_sprite(R.SLOT_KEYS[side], text, R.CAPTION_INKS["normal"], k, self._text())
        except Exception:
            self._captions[key] = None
        while len(self._captions) > 8:
            self._captions.popitem(last=False)

    def _gpu_prebuild_snap(self, s):
        """Once the cards rest, build one of ``_gpu_snap_sprites`` per frame, so the acceptance frame
        (the fly's first) renders no text; the loop stays awake until they exist (``s.gpu_prebuild``)."""
        if self.machine.animating(self.clock()):
            s.gpu_prebuild = True                   # after the motion (normal frames stay light)
            return
        todo = self._gpu_snap_sprites(s)
        if todo:
            todo[0]()
        s.gpu_prebuild = len(todo) > 1

    def _gpu_label_ready(self, label):
        """The GPU chrome shows a label once its surfaces are ready (uploaded a frame earlier: an upload's
        Commit in the same frame costs about 3 ms, CAR 12.4); S5-24's 'the previous label stays'."""
        sprite = getattr(label, "sprite", None)
        if sprite is None:
            return True
        shadow = getattr(label, "shadow", None)
        return self.gpu.ready(sprite) and (shadow is None or self.gpu.ready(shadow))

    def _gpu_dots(self, s):
        """The dots row's sprite (S5-9's window), re-rendered only when its opacities change."""
        k = s.layout.k
        _first, shown, opacities = R.dots_window(len(s.items), self.machine.sel)
        key = (opacities, k)
        if key != s.dots_key:
            s.dots_key = key
            s.dots = R.render_dots(opacities, k) if shown else None

    def _gpu_view(self, s, now, wanted):
        """The ChromeView of this event (see its definition): sprites only for cards that show."""
        m = self.machine
        layout = s.layout
        k = layout.k
        cards = []
        for index in sorted(m.cards):
            if not 0 <= index < len(s.items):
                continue
            tweens = m.cards[index]
            closed = index in m.closed
            f = R.CLOSED_OPACITY if closed else 1.0
            shows = tweens.op.start * f > 0.001 or tweens.op.target * f > 0.001
            badge = chip = face = None
            if shows:
                item = s.items[index]
                registered = index in s.thumbs and index not in s.release
                pending = wanted is not None and index in wanted
                badge = self._sprite("badge", item, lambda icon, name: R.badge_sprite(icon, name, k, self._text()))
                near = abs(index - m.sel) <= layout.register_distance     # beyond it a card is at opacity 0
                if (uses_placeholder(s.available[index], registered, index in s.failed, index in s.stubs, pending)
                        and (near or not s.available[index] or index in s.failed or index in s.stubs)):
                    face = self._sprite("placeholder", item,
                                        lambda icon, name: R.placeholder_sprite(icon, name, k, self._text()))
                side = self._side_of(s, index)
                chip = self._chip(side, k) if side else None
            cards.append(ChromeCardInfo(index, index - m.sel, tweens, closed, badge, chip, face))
        order = [c.index for c in sorted(cards, key=lambda c: (-abs(c.d), c.index))]
        slots = {}
        if m.tray_on:
            for side in SIDES:
                index = s.sides[side]
                badge = (self._sprite("slot", s.items[index],
                                      lambda icon, name: R.slot_badge_sprite(icon, name, k, self._text()))
                         if index is not None else None)
                slots[side] = ChromeSlotInfo(m.slots[side], badge, self._caption(s, side, now), self._glyph(side, k))
        label = s.label if s.label is not None and getattr(s.label, "sprite", None) is not None else None
        dots_shown = R.dots_window(len(s.items), m.sel)[1]
        if self._marker is None or self._marker[0] != k:
            self._marker = (k, R.marker_sprite(k))
        return ChromeView(m, m.sel, frozenset(m.closed), tuple(cards), tuple(order), m.tray_on, slots, label,
                          s.label_key if label is not None else None, s.dots, s.dots_key, dots_shown,
                          self._marker[1], s.fly, m._bump_back, BUMP_S, FLY_S, FLY_FADE_AT, FLY_FADE_S)

    def _gpu_sync(self, s, now, wanted):
        """One event's chrome sync (one Commit); None when the chrome's device failed."""
        try:
            view = self._gpu_view(s, now, wanted)
            return self.gpu.sync(view, self._t_wake)
        except Exception as exc:
            self.log.warn("gpu-sync", f"carousel: the GPU chrome sync failed: {exc!r}")
            return None

    def _update_thumbnails(self, s, updates):
        """Every thumbnail update of the frame back to back: one GIL-keeping call each on the
        Win32 backend (G1-1, batched); on the GPU chrome an unchanged thumbnail is not sent again."""
        if s.gpu:
            sent = s.thumb_sent
            fresh = []
            for u in updates:
                if sent.get(u[0]) != u[1:]:
                    sent[u[0]] = u[1:]
                    fresh.append(u)
            updates = fresh
        batch = getattr(self.backend, "update_thumbnails", None)
        if batch is not None:
            batch(updates)
            return
        for handle, dest, source, opacity, visible in updates:
            self.backend.update_thumbnail(handle, dest, source, opacity, visible)

    def _present_session(self, s):
        backend = self.backend
        plan, wanted = s.plan
        s.plan = None
        for i in list(s.release):
            handle = s.thumbs.pop(i, None)
            if handle is not None:
                self._unregister(handle)
        s.release.clear()
        # The GPU chrome's detent frame carries the chrome's Commit; its re-registration (about 1 ms of
        # DWM calls) goes to the next frame, a 4 ms late z-order change for the thumbnails (CAR 12.4).
        s.rereg_s = None
        if wanted is not None and s.rereg and not s.exiting and not (s.gpu and s.detent):
            rereg_t0 = time.perf_counter()          # FrameStats: which frames re-registered, and how long
            for handle in s.thumbs.values():
                self._unregister(handle)
            s.thumbs.clear()
            for key in list(s.extra):
                self._release_extra(s, key)
            # Z-order is registration order: the tray slots and the one-side preview first (the
            # cards group lies over the tray), then the cards far -> near, then the fly on top.
            for key in ("left", "right", "keep"):
                if key in s.extra_plan:
                    self._register_extra(s, key, s.extra_plan[key][0])
            for i in wanted:
                item = s.items[i]
                s.attempts += 1
                self.status.registrations += 1
                handle = backend.register(item.hwnd)
                if not handle:
                    s.failed.add(i)
                    s.dirty = True
                    self.status.register_failures += 1
                    continue
                size = backend.source_size(handle)
                if item.minimized and R.is_caption_stub(size):
                    self._unregister(handle)
                    s.stubs.add(i)
                    s.dirty = True
                    continue
                if not _usable_size(size):
                    # DwmQueryThumbnailSourceSize failed: never stretch one source pixel over the
                    # card; like a failed registration, the placeholder, never retried this open.
                    self._unregister(handle)
                    s.failed.add(i)
                    s.dirty = True
                    self.status.register_failures += 1
                    continue
                s.thumbs[i] = handle
                s.sizes[i] = size
            if "fly" in s.extra_plan:
                self._register_extra(s, "fly", s.extra_plan["fly"][0])
            s.rereg = False
            s.rereg_s = time.perf_counter() - rereg_t0
        elif not s.exiting:
            # A slot filled or a preview appeared without a re-registration pending: its own thumbnail
            # would land above the cards; so it waits for the next re-registration (s.rereg).
            for key in ("left", "right", "keep"):
                if key in s.extra_plan and key not in s.extra:
                    s.rereg = True
            if "fly" in s.extra_plan and "fly" not in s.extra:
                self._register_extra(s, "fly", s.extra_plan["fly"][0])
        sel = self.machine.sel
        reach = s.layout.register_distance
        updates = []
        gone = []
        for i, handle in list(s.thumbs.items()):
            spec = plan.get(i)
            size = s.sizes.get(i)
            if spec is None or not _usable_size(size):
                updates.append((handle, (0, 0, 0, 0), (0, 0, 1, 1), 0, False))
                if abs(i - sel) > reach:
                    gone.append(i)
                continue
            rect, opacity = spec
            source = R.cover_source(size, rect)
            visible = opacity > 0.001 and rect[2] > rect[0] and rect[3] > rect[1]
            updates.append((handle, rect, source, max(0, min(255, round(255 * opacity))), visible))
        for key, (handle, hwnd) in list(s.extra.items()):
            spec = s.extra_plan.get(key)
            size = s.extra_sizes.get(hwnd)
            if spec is None or not _usable_size(size):
                updates.append((handle, (0, 0, 0, 0), (0, 0, 1, 1), 0, False))
                continue
            _hwnd, rect, opacity = spec
            source = R.cover_source(size, rect)
            visible = opacity > 0.001 and rect[2] > rect[0] and rect[3] > rect[1]
            updates.append((handle, rect, source, max(0, min(255, round(255 * opacity))), visible))
        self._update_thumbnails(s, updates)
        for i in gone:
            handle = s.thumbs.pop(i, None)
            if handle is not None:
                s.thumb_sent.pop(handle, None)
                self._unregister(handle)
        if s.gpu:
            self._present_gpu(s)
            return
        backend.chrome_present(s.chrome_dirty)
        self._present_layers(s)
        if not s.layers_shown:
            backend.chrome_show()
            backend.layer_show("label")
            backend.layer_show("dots")
            if s.dim:
                backend.dim_show()
            s.layers_shown = True
            if s.affinity:
                # WDA_EXCLUDEFROMCAPTURE on shown windows: re-assert it now that chrome (and the dim)
                # are up, while the frost capture may still be running.
                backend.set_affinity(True)
        if s.dim:
            dim = round(255 * max(0.0, min(1.0, s.dim_target)))
            if dim != s.dim_alpha:
                backend.dim_alpha(dim)
                s.dim_alpha = dim
        # Frosted: the glass window's constant alpha is the open's and the exit's backdrop fade,
        # from 0, once the frost was uploaded.
        if s.glass == "ready" and not s.plain and backend.host_mode == HOST_LAYERED:
            glass = round(255 * max(0.0, min(1.0, s.glass_target)))
            if glass != s.glass_alpha:
                backend.glass_alpha(glass)
                s.glass_alpha = glass
        self.status.frames += 1

    def _present_layers(self, s):
        backend = self.backend
        for role, state, dirty_attr in (("label", s.frame_label, "label_dirty"), ("dots", s.frame_dots, "dots_dirty")):
            alpha, pos = state
            if getattr(s, dirty_attr):
                backend.layer_present(role, alpha, pos)
                setattr(s, dirty_attr, False)
                s.layer_sent[role] = (alpha, pos)
            elif s.layer_sent.get(role) != (alpha, pos):
                backend.layer_alpha(role, alpha, pos)
                s.layer_sent[role] = (alpha, pos)

    def _register_extra(self, s, key, hwnd):
        handle = self.backend.register(hwnd)
        if not handle:
            return None
        size = self.backend.source_size(handle)
        if not _usable_size(size):
            self._unregister(handle)
            return None
        s.extra[key] = (handle, hwnd)
        s.extra_sizes[hwnd] = size
        return handle

    def _unregister(self, handle):
        s = self.session
        if s is not None:
            s.thumb_sent.pop(handle, None)          # a later registration may reuse the handle value
        try:
            self.backend.unregister(handle)
        except Exception as exc:
            self.log.warn("unregister", f"carousel: DwmUnregisterThumbnail failed: {exc!r}")

    def _present_gpu(self, s):
        """The GPU chrome's present: its window shows once the first sync committed (with the dim on
        No background); the dim's and the frost's constant alphas as on the CPU path. Nothing of
        the chrome is sent per frame: the compositor runs it."""
        backend = self.backend
        if s.gpu_synced and not s.gpu_shown:
            backend.gpu_show()
            if s.dim and not s.layers_shown:
                backend.dim_show()
            s.gpu_shown = s.layers_shown = True
            if s.affinity:
                backend.set_affinity(True)          # WDA_EXCLUDEFROMCAPTURE on the shown chrome too
        if s.dim:
            dim = round(255 * max(0.0, min(1.0, s.dim_target)))
            if dim != s.dim_alpha:
                backend.dim_alpha(dim)
                s.dim_alpha = dim
        if s.glass == "ready" and not s.plain and backend.host_mode == HOST_LAYERED:
            glass = round(255 * max(0.0, min(1.0, s.glass_target)))
            if glass != s.glass_alpha:
                backend.glass_alpha(glass)
                s.glass_alpha = glass
        self.status.frames += 1

    # -------------------------------------------------------------- teardown
    def _teardown(self, s):
        """Hide cleanup (CAR section 5): thumbnails before the host (the tray, the preview and the
        fly included); chrome -> layers -> host -> glass -> dim; the large DIBs; the display
        affinity; pending snap jobs resolve as ``move_rejected`` (nothing moves once the picker is
        gone); then every per-open cache."""
        backend = self.backend
        self._note_registrations(s)
        for handle in list(s.thumbs.values()):
            self._unregister(handle)
        s.thumbs.clear()
        for key in list(s.extra):
            self._release_extra(s, key)
        s.plan = None
        if s.gpu and self.gpu is not None:
            try:
                self.gpu.end()                  # the root at 0, the session's label surfaces released
            except Exception as exc:
                self.log.warn("gpu", f"carousel: ending the GPU chrome failed: {exc!r}")
            s.gpu = False
        for step in (backend.hide_layers, backend.chrome_free, backend.free_large):
            try:
                step()
            except Exception as exc:
                self.log.warn("teardown", f"carousel: hide step failed: {exc!r}")
        for role in ("label", "dots"):
            try:
                backend.layer_free(role)
            except Exception:
                pass
        if s.affinity:
            try:
                backend.set_affinity(False)
            except Exception:
                pass
            s.affinity = False
        self._set_exclusions(s, ())
        try:
            backend.set_host_passive(False)
        except Exception:
            pass
        for job in list(s.jobs.values()):
            s.jobs.pop(job.id, None)
            if job.resolve("move_rejected", "carousel"):
                self.mail.push_event("snap_result", (job.side, "move_rejected"))
        self.status.rect = None
        self._last_gen, self._last_layout = s.gen, s.layout
        if self.session is s:
            self.session = None
        self.machine.reset()
        self._prepared = False
        # Memory (CAR section 5): besides the DIBs, drop every per-open cache.
        self._label_cache.clear()
        self._sprites.clear()
        self._captions.clear()
        self._scaler.trim()
        if self._shadows is not None:
            self._shadows[1].trim()
        if self.labeler is not None:
            self.labeler.submit([])

    # ------------------------------------------------ the plain-host fallback (CAR section 5)
    def _note_registrations(self, s):
        """At the end of an open on the layered host: an open whose registrations (at least
        PLAIN_FALLBACK_ATTEMPTS) all failed counts; PLAIN_FALLBACK_OPENS of them in a row switch
        to the plain host at the next open. An open with a successful registration starts over."""
        if self.backend.host_mode != HOST_LAYERED or not s.attempts:
            return
        if s.attempts >= PLAIN_FALLBACK_ATTEMPTS and len(s.failed) >= s.attempts:
            self._failed_opens += 1
            if self._failed_opens >= PLAIN_FALLBACK_OPENS:
                self._plain_pending = True
        elif len(s.failed) < s.attempts:
            self._failed_opens = 0
            self._timed_retry = False                # the layered host works: no backoff pending
            self._plain_retry_s = PLAIN_RETRY_S
        s.attempts = 0                    # counted once, even if torn down twice

    def _display_changed(self):
        """WM_DISPLAYCHANGE, WM_DWMCOMPOSITIONCHANGED or a resume: the plain host tries the layered
        one again at the next open, the failure count starts over, and P is re-read (K4 0.6)."""
        self._failed_opens = 0
        self._plain_pending = False
        if self.backend.host_mode == HOST_PLAIN:
            self._layered_pending = True
        refresh = getattr(getattr(self.backend, "pacer", None), "refresh", None)
        if refresh is not None:
            try:
                refresh()
            except Exception:
                pass

    def _publish_host(self):
        self.status.host_hwnd = int(self.backend.host_hwnd or 0)
        self.status.host_mode = self.backend.host_mode

    def _switch_to_plain(self, now):
        """CAR section 5 fallback: the plain host that paints the frost itself; 'none' is forced to
        glass while it lasts. Not permanent (see _display_changed and PLAIN_RETRY_S)."""
        self._plain_pending = False
        self._failed_opens = 0
        self._back_off()
        try:
            self.backend.use_plain_host()
            self.log.warn("plain-host", "carousel: thumbnails failed on the layered host; using the plain host")
        except Exception as exc:
            self.log.warn("plain-host", f"carousel: switching to the plain host failed: {exc!r}")
        self._publish_host()
        self._plain_since = now

    def _back_off(self):
        """A timed retry of the layered host that failed again doubles the next wait."""
        if self._timed_retry:
            self._plain_retry_s = min(PLAIN_RETRY_MAX_S, self._plain_retry_s * 2)
        self._timed_retry = False

    def _switch_to_layered(self, now, timed):
        self._layered_pending = False
        try:
            ok = bool(self.backend.use_layered_host())
        except Exception as exc:
            ok = False
            self.log.warn("layered-host", f"carousel: recreating the layered host failed: {exc!r}")
        self._publish_host()
        self._timed_retry = bool(timed)
        if ok and self.backend.host_mode == HOST_LAYERED:
            self._plain_since = None
            self.log.info("carousel: trying the layered host again")
        else:
            self._back_off()
            self._plain_since = now

    def _stop(self):
        """close(): release at once (thumbnails first), then the windows, on this thread."""
        self.stopped = True
        if self.session is not None:
            self._teardown(self.session)
        if self.gpu is not None:
            try:
                self.gpu.close()                # every chrome COM object, on this thread (K4 4.3 step 2)
            except Exception as exc:
                self.log.warn("gpu", f"carousel: closing the GPU chrome failed: {exc!r}")
        self._end_toast()
        self.status.rect = None
        boost = getattr(self.backend, "boost", None)
        if boost is not None and self._boosted:
            try:
                boost(False)
            except Exception:
                pass
            self._boosted = False
        try:
            self.backend.destroy_windows()
        except Exception as exc:
            self.log.warn("destroy", f"carousel: destroying the windows failed: {exc!r}")

    # ------------------------------------------------------------ the toast service (K4 10)
    def _toast_request(self, now):
        req, end = self.mail.take_toast()
        if end:
            self._end_toast()
            self._deferred_toast = None
        if req is None:
            return
        s = self.session
        if s is not None:
            if s.exiting and req.exit:
                self._deferred_toast = req                # the picker's own exit toast: after its exit
            else:
                self.status.toasts_dropped += 1           # never over an open overlay (K4 10.4)
            return
        self._show_toast(req, now)

    def _show_toast(self, req, now):
        busy = getattr(self.backend, "notification_busy", None)
        try:
            if busy is not None and busy():
                self.status.toasts_dropped += 1           # a full-screen D3D app or presentation mode (S5-17)
                return
        except Exception:
            pass
        t = self.toast
        if t is not None and t.sprite is not None and not t.machine.done(now):
            self._replace_toast(t, req, now)
        else:
            self._start_toast(req.text, None, now, rm=req.rm)

    def _toast_layout(self):
        try:
            monitor, work = self._monitor(None)          # the foreground window's monitor at show time
            return R.layout_for(monitor, work)
        except Exception:
            return self._last_layout

    @staticmethod
    def _toast_geometry(size, layout):
        """(rect, window) for a pill of ``size`` px: the resting rect and the window with room for
        the rise and the spring."""
        rect = R.toast_rect(layout, size)
        margin = math.ceil(TOAST_RISE * layout.k) + max(2, math.ceil(0.03 * size[0]))
        window = (rect[0] - margin, rect[1] - margin, rect[2] + 2 * margin, rect[3] + 2 * margin)
        return rect, window

    def _start_toast(self, text, layout, now, rm=False):
        """K4 10: the tint-only pill is rendered first on NanoD-label (it sizes the window and
        the glass capture, and is the capture-timeout fallback); the toast shows with its glass
        pill, or with the plain one after TOAST_CAPTURE_TIMEOUT_S."""
        text = " ".join(str(text or "").split())
        layout = layout or self._toast_layout()
        if not text or layout is None or self.stopped:
            return
        self._end_toast()
        self._toast_gen += 1
        t = _Toast(self._toast_gen, text, layout, None, None, rm)
        self.toast = t
        self._render_toast(t, None, "plain")

    def _replace_toast(self, t, req, now):
        """K4 10.2: the text swaps at once (as soon as NanoD-label has the new pill on the old
        glass, stretched) and the 1800 ms hold restarts now, with no new entry motion; the new
        width then takes a fresh glass capture."""
        text = " ".join(str(req.text or "").split())
        if not text:
            return
        self._toast_gen += 1
        t.gen = self._toast_gen                   # the old capture's answer is dropped
        t.text = text
        t.plain = None
        t.deadline = None
        t.machine.replace(now)
        self.status.toasts += 1
        self._render_toast(t, t.backdrop, "stretch")

    def _render_toast(self, t, backdrop, stage):
        """Hand a pill to NanoD-label (inline only without a worker: tests, a bare engine)."""
        t.seq += 1
        job = ToastJob((t.gen, t.seq, stage), t.text, t.layout.k, backdrop)
        submit = getattr(self.labeler, "submit_toast", None)
        if submit is not None and submit(job):
            return
        try:
            pill = R.render_toast_canvas(job.text, job.k, job.backdrop, self._text())
        except Exception as exc:
            self.log.warn("toast", f"carousel: toast rendering failed: {exc!r}")
            pill = None
        self._local_toasts.append((job.key, pill))

    def _toast_results(self, now):
        results, self._local_toasts = self._local_toasts, []
        take = getattr(self.labeler, "take_toast_results", None)
        if take is not None:
            results = results + take()
        for key, pill in results:
            t = self.toast
            gen, seq, stage = key
            if t is None or gen != t.gen or seq <= t.applied:
                continue
            if pill is None:
                if stage == "plain":
                    self._end_toast()                 # nothing to show at all
                continue
            t.applied = seq
            if stage == "plain":
                t.plain = pill
                self._toast_capture(t, pill, now)
            elif stage == "stretch":
                self._toast_capture(t, pill, now)
                self._toast_show(t, pill, now)
            else:
                t.deadline = None
                self._toast_show(t, pill, now)

    def _toast_capture(self, t, pill, now):
        """Size the window for ``pill`` and ask for the glass behind its resting rect (the toast
        window excluded from the capture while it runs)."""
        try:
            rect, window = self._toast_geometry(pill.size, t.layout)
            if rect != t.rect or window != t.window:
                t.rect, t.window = rect, window
                self.backend.toast_alloc(window)
                t.shown = False
                t.dirty = True
            self.backend.set_toast_affinity(True)
            t.deadline = now + TOAST_CAPTURE_TIMEOUT_S
            if not self.capture.submit(CaptureJob(t.gen, "toast", rect, t.layout.k, True)):
                t.deadline = now                      # no capture: the timeout path shows the tint
        except Exception as exc:
            self.log.warn("toast", f"carousel: toast failed: {exc!r}")
            self._end_toast()

    def _toast_show(self, t, pill, now):
        t.sprite = pill
        t.dirty = True
        if t.deadline is None:
            try:
                self.backend.set_toast_affinity(False)
            except Exception:
                pass
        if not t.machine.started:
            t.machine.start(now, t.rm)
            self.status.toasts += 1

    def _prepare_toast(self, now):
        t = self.toast
        canvas = self.backend.toast_canvas()
        if canvas is None:
            return
        opacity, rise, scale = t.machine.values(now)
        w, h = t.sprite.size
        size = (max(1, round(w * scale)), max(1, round(h * scale)))
        # premultiplied: a resize of the pill is exact and it is pasted over the cleared window
        pill = t.sprite.image if size == (w, h) else t.sprite.image.resize(size, R.Image.Resampling.BILINEAR)
        cx = t.rect[0] + t.rect[2] / 2 - t.window[0]
        cy = t.rect[1] + t.rect[3] / 2 - t.window[1] + rise * t.layout.k
        canvas.clear()
        canvas.paste_premultiplied(pill, (cx - size[0] / 2, cy - size[1] / 2))
        t.alpha = max(0, min(255, round(255 * opacity)))
        t.prepared = True
        t.dirty = False

    def _end_toast(self):
        """Hide and free the toast; True when one was up. Its window is excluded from capture
        FIRST and stays excluded while hidden (the next toast clears that before it shows): a
        hidden window can linger in the DWM frame a capture reads."""
        t, self.toast = self.toast, None
        if t is None:
            return False
        for step in (lambda: self.backend.set_toast_affinity(True), self.backend.toast_hide, self.backend.toast_free):
            try:
                step()
            except Exception:
                pass
        return True


# ================================================================== Win32: types
DWORD = C.c_uint32
LONG = C.c_int32
BOOL = C.c_int32
UINT = C.c_uint32
BYTE = C.c_ubyte
WORD = C.c_uint16
ATOM = C.c_uint16
HANDLE = C.c_void_p
LPARAM = C.c_ssize_t
WPARAM = C.c_size_t
UINT_PTR = C.c_size_t
HRESULT = C.c_int32
DPI_CONTEXT = C.c_void_p
WINFUNCTYPE = getattr(C, "WINFUNCTYPE", C.CFUNCTYPE)
WNDPROC = WINFUNCTYPE(LPARAM, HANDLE, UINT, WPARAM, LPARAM)


class POINT(C.Structure):
    _fields_ = [("x", LONG), ("y", LONG)]


class SIZE(C.Structure):
    _fields_ = [("cx", LONG), ("cy", LONG)]


class RECT(C.Structure):
    _fields_ = [("left", LONG), ("top", LONG), ("right", LONG), ("bottom", LONG)]


class MONITORINFO(C.Structure):
    _fields_ = [("cbSize", DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", DWORD)]


class BLENDFUNCTION(C.Structure):
    _fields_ = [("BlendOp", BYTE), ("BlendFlags", BYTE), ("SourceConstantAlpha", BYTE), ("AlphaFormat", BYTE)]


class BITMAPINFOHEADER(C.Structure):
    _fields_ = [("biSize", DWORD), ("biWidth", LONG), ("biHeight", LONG), ("biPlanes", WORD),
                ("biBitCount", WORD), ("biCompression", DWORD), ("biSizeImage", DWORD),
                ("biXPelsPerMeter", LONG), ("biYPelsPerMeter", LONG), ("biClrUsed", DWORD),
                ("biClrImportant", DWORD)]


class BITMAPINFO(C.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", DWORD * 1)]


class WNDCLASSEXW(C.Structure):
    _fields_ = [("cbSize", UINT), ("style", UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", C.c_int), ("cbWndExtra", C.c_int), ("hInstance", HANDLE),
                ("hIcon", HANDLE), ("hCursor", HANDLE), ("hbrBackground", HANDLE),
                ("lpszMenuName", C.c_wchar_p), ("lpszClassName", C.c_wchar_p), ("hIconSm", HANDLE)]


class MSG(C.Structure):
    _fields_ = [("hwnd", HANDLE), ("message", UINT), ("wParam", WPARAM), ("lParam", LPARAM),
                ("time", DWORD), ("pt", POINT), ("lPrivate", DWORD)]


class PAINTSTRUCT(C.Structure):
    _fields_ = [("hdc", HANDLE), ("fErase", BOOL), ("rcPaint", RECT), ("fRestore", BOOL),
                ("fIncUpdate", BOOL), ("rgbReserved", BYTE * 32)]


class THUMBNAIL_PROPERTIES(C.Structure):
    _fields_ = [("flags", DWORD), ("destination", RECT), ("source", RECT),
                ("opacity", BYTE), ("visible", BOOL), ("source_client_only", BOOL)]


class UPDATELAYEREDWINDOWINFO(C.Structure):
    _fields_ = [("cbSize", DWORD), ("hdcDst", HANDLE), ("pptDst", C.POINTER(POINT)), ("psize", C.POINTER(SIZE)),
                ("hdcSrc", HANDLE), ("pptSrc", C.POINTER(POINT)), ("crKey", DWORD),
                ("pblend", C.POINTER(BLENDFUNCTION)), ("dwFlags", DWORD), ("prcDirty", C.POINTER(RECT))]


class UNSIGNED_RATIO(C.Structure):
    _pack_ = 1
    _fields_ = [("num", C.c_uint32), ("den", C.c_uint32)]


_U64 = C.c_uint64


class DWM_TIMING_INFO(C.Structure):   # dwmapi.h is #pragma pack(1)
    _pack_ = 1
    _fields_ = [("cbSize", C.c_uint32), ("rateRefresh", UNSIGNED_RATIO), ("qpcRefreshPeriod", _U64),
                ("rateCompose", UNSIGNED_RATIO), ("qpcVBlank", _U64), ("cRefresh", _U64), ("cDXRefresh", C.c_uint32),
                ("qpcCompose", _U64), ("cFrame", _U64), ("cDXPresent", C.c_uint32), ("cRefreshFrame", _U64),
                ("cFrameSubmitted", _U64), ("cDXPresentSubmitted", C.c_uint32), ("cFrameConfirmed", _U64),
                ("cDXPresentConfirmed", C.c_uint32), ("cRefreshConfirmed", _U64), ("cDXRefreshConfirmed", C.c_uint32),
                ("cFramesLate", _U64), ("cFramesOutstanding", C.c_uint32), ("cFrameDisplayed", _U64),
                ("qpcFrameDisplayed", _U64), ("cRefreshFrameDisplayed", _U64), ("cFrameComplete", _U64),
                ("qpcFrameComplete", _U64), ("cFramePending", _U64), ("qpcFramePending", _U64),
                ("cFramesDisplayed", _U64), ("cFramesComplete", _U64), ("cFramesPending", _U64),
                ("cFramesAvailable", _U64), ("cFramesDropped", _U64), ("cFramesMissed", _U64),
                ("cRefreshNextDisplayed", _U64), ("cRefreshNextPresented", _U64), ("cRefreshesDisplayed", _U64),
                ("cRefreshesPresented", _U64), ("cRefreshStarted", _U64), ("cPixelsReceived", _U64),
                ("cPixelsDrawn", _U64), ("cBuffersEmpty", _U64)]


class WINDOWPLACEMENT(C.Structure):
    _fields_ = [("length", UINT), ("flags", UINT), ("showCmd", UINT), ("ptMinPosition", POINT),
                ("ptMaxPosition", POINT), ("rcNormalPosition", RECT)]


class SID_AND_ATTRIBUTES(C.Structure):
    _fields_ = [("Sid", C.c_void_p), ("Attributes", DWORD)]


class TOKEN_MANDATORY_LABEL(C.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]


STRUCTURE_SIZES_X64 = {POINT: 8, SIZE: 8, RECT: 16, MONITORINFO: 40, BLENDFUNCTION: 4, BITMAPINFOHEADER: 40,
                       BITMAPINFO: 44, WNDCLASSEXW: 80, MSG: 48, PAINTSTRUCT: 72, THUMBNAIL_PROPERTIES: 48,
                       UPDATELAYEREDWINDOWINFO: 80, WINDOWPLACEMENT: 44, DWM_TIMING_INFO: 292}

# ============================================================== Win32: constants
WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x00000008, 0x00000020, 0x00000080
WS_EX_LAYERED, WS_EX_NOACTIVATE, WS_EX_NOREDIRECTIONBITMAP = 0x00080000, 0x08000000, 0x00200000
LAYER_EX_STYLE = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
assert LAYER_EX_STYLE == 0x080800A8
HOST_EX_STYLE = WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOREDIRECTIONBITMAP    # activatable
# The GPU chrome's window (step 3, CAR 12.4): the layers' click-through, non-activating styles plus
# NOREDIRECTIONBITMAP (a DirectComposition target, no redirection surface): K4 3's chrome row.
GPU_EX_STYLE = LAYER_EX_STYLE | WS_EX_NOREDIRECTIONBITMAP
assert GPU_EX_STYLE == 0x082800A8
LWA_ALPHA = 0x2
PLAIN_HOST_EX_STYLE = WS_EX_TOPMOST | WS_EX_TOOLWINDOW
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0004, 0x0010
SWP_SHOWWINDOW = 0x0040
SHOW_FLAGS = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
SW_HIDE = 0
ULW_ALPHA = 0x2
AC_SRC_OVER, AC_SRC_ALPHA = 0x00, 0x01
BI_RGB, DIB_RGB_COLORS = 0, 0
SRCCOPY, CAPTUREBLT = 0x00CC0020, 0x40000000
PM_NOREMOVE, PM_REMOVE = 0x0000, 0x0001
WM_USER = 0x0400
WM_DESTROY, WM_ACTIVATE, WA_INACTIVE = 0x0002, 0x0006, 0
WM_PAINT, WM_CLOSE, WM_QUIT, WM_ERASEBKGND = 0x000F, 0x0010, 0x0012, 0x0014
WM_MOUSEACTIVATE, WM_DISPLAYCHANGE, WM_NCHITTEST, WM_KEYDOWN, WM_TIMER = 0x0021, 0x007E, 0x0084, 0x0100, 0x0113
WM_LBUTTONUP, WM_MOUSEWHEEL, WM_MOUSEHWHEEL = 0x0202, 0x020A, 0x020E
WM_DWMCOMPOSITIONCHANGED = 0x031E
WM_POWERBROADCAST, PBT_APMSUSPEND, PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC = 0x0218, 0x0004, 0x0007, 0x0012
HTTRANSPARENT, HTCLIENT, MA_NOACTIVATE, MA_NOACTIVATEANDEAT = -1, 1, 3, 4
MONITOR_DEFAULTTOPRIMARY, MONITOR_DEFAULTTONEAREST = 1, 2
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
DPI_AWARENESS_PER_MONITOR_AWARE = 2
DWMWA_TRANSITIONS_FORCEDISABLED, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_DONOTROUND = 3, 33, 1
DWMWA_EXTENDED_FRAME_BOUNDS = 9
WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x00, 0x11
DWM_TNP_ALL = 0x1F        # RECTDESTINATION | RECTSOURCE | OPACITY | VISIBLE | SOURCECLIENTAREAONLY
QS_ALLINPUT, MWMO_INPUTAVAILABLE = 0x04FF, 0x0004
INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0, WAIT_TIMEOUT = 0x0, 0x102
GR_GDIOBJECTS, GR_USEROBJECTS = 0, 1
ERROR_CLASS_ALREADY_EXISTS = 1410
IDC_ARROW = 32512
THREAD_PRIORITY_ABOVE_NORMAL, THREAD_PRIORITY_BELOW_NORMAL = 1, -1
CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS = 0x2, 0x1F0003
SPI_GETCLIENTAREAANIMATION = 0x1042
QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE = 3, 4
CLASS_NAMES = {"dim": "NanoD.Carousel.Dim", "glass": "NanoD.Carousel.Glass", "host": "NanoD.Carousel.Host",
               "chrome": "NanoD.Carousel.Chrome", "label": "NanoD.Carousel.Label", "dots": "NanoD.Carousel.Dots",
               "toast": "NanoD.Carousel.Toast", "gpu": "NanoD.Carousel.Gpu"}
HOST_TITLE = "Desk Dial · Windows"                   # the host window's name (rename A13: Desk Dial)
LARGE_DIB_BYTES = 1 << 20
DC_BRUSH = 18
PLAIN_PANE_COLORREF = (lambda r, g, b: r | (g << 8) | (b << 16))(*R.opaque_pane_rgb())
# After hide, each layered window's last UpdateLayeredWindow surface stays committed by the
# system (the constant-alpha fades reuse it): at 5120 x 1440 about 29.5 MB for the monitor-sized
# frost or dim, 14.5 MB for the chrome band (32:9) and 2 MB for the label layer. hide_layers()
# shrinks each to 1 x 1 transparent.
RETAINED_ULW_ROLES = ("chrome", "label", "dots", "glass", "dim")
LAYER_ROLES = ("label", "dots")

# (dll attribute, export, restype, argtypes); private WinDLL instances only.
DECLARATIONS = (
    ("u", "RegisterClassExW", ATOM, (C.POINTER(WNDCLASSEXW),)),
    ("u", "UnregisterClassW", BOOL, (C.c_wchar_p, HANDLE)),
    ("u", "CreateWindowExW", HANDLE, (DWORD, C.c_wchar_p, C.c_wchar_p, DWORD, C.c_int, C.c_int, C.c_int, C.c_int,
                                      HANDLE, HANDLE, HANDLE, C.c_void_p)),
    ("u", "DestroyWindow", BOOL, (HANDLE,)),
    ("u", "DefWindowProcW", LPARAM, (HANDLE, UINT, WPARAM, LPARAM)),
    ("u", "IsWindow", BOOL, (HANDLE,)),
    ("u", "IsWindowVisible", BOOL, (HANDLE,)),
    ("u", "ShowWindow", BOOL, (HANDLE, C.c_int)),
    ("u", "SetWindowPos", BOOL, (HANDLE, HANDLE, C.c_int, C.c_int, C.c_int, C.c_int, UINT)),
    ("u", "UpdateLayeredWindow", BOOL, (HANDLE, HANDLE, C.POINTER(POINT), C.POINTER(SIZE), HANDLE,
                                        C.POINTER(POINT), DWORD, C.POINTER(BLENDFUNCTION), DWORD)),
    ("u", "UpdateLayeredWindowIndirect", BOOL, (HANDLE, C.POINTER(UPDATELAYEREDWINDOWINFO))),
    ("u", "GetMessageW", BOOL, (C.POINTER(MSG), HANDLE, UINT, UINT)),
    ("u", "PeekMessageW", BOOL, (C.POINTER(MSG), HANDLE, UINT, UINT, UINT)),
    ("u", "TranslateMessage", BOOL, (C.POINTER(MSG),)),
    ("u", "DispatchMessageW", LPARAM, (C.POINTER(MSG),)),
    ("u", "PostMessageW", BOOL, (HANDLE, UINT, WPARAM, LPARAM)),
    ("u", "PostThreadMessageW", BOOL, (DWORD, UINT, WPARAM, LPARAM)),
    ("u", "PostQuitMessage", None, (C.c_int,)),
    ("u", "MsgWaitForMultipleObjectsEx", DWORD, (DWORD, C.c_void_p, DWORD, DWORD, DWORD)),
    ("u", "BeginPaint", HANDLE, (HANDLE, C.POINTER(PAINTSTRUCT))),
    ("u", "EndPaint", BOOL, (HANDLE, C.POINTER(PAINTSTRUCT))),
    ("u", "InvalidateRect", BOOL, (HANDLE, C.c_void_p, BOOL)),
    ("u", "LoadCursorW", HANDLE, (HANDLE, C.c_void_p)),
    ("u", "GetDC", HANDLE, (HANDLE,)),
    ("u", "ReleaseDC", C.c_int, (HANDLE, HANDLE)),
    ("u", "GetForegroundWindow", HANDLE, ()),
    ("u", "SetForegroundWindow", BOOL, (HANDLE,)),
    ("u", "MonitorFromWindow", HANDLE, (HANDLE, DWORD)),
    ("u", "MonitorFromPoint", HANDLE, (POINT, DWORD)),
    ("u", "GetMonitorInfoW", BOOL, (HANDLE, C.POINTER(MONITORINFO))),
    ("u", "SetThreadDpiAwarenessContext", DPI_CONTEXT, (DPI_CONTEXT,)),
    ("u", "GetThreadDpiAwarenessContext", DPI_CONTEXT, ()),
    ("u", "GetAwarenessFromDpiAwarenessContext", C.c_int, (DPI_CONTEXT,)),
    ("u", "SetWindowDisplayAffinity", BOOL, (HANDLE, DWORD)),
    ("u", "GetWindowThreadProcessId", DWORD, (HANDLE, C.POINTER(DWORD))),
    ("u", "GetGuiResources", DWORD, (HANDLE, DWORD)),
    ("u", "FillRect", C.c_int, (HANDLE, C.POINTER(RECT), HANDLE)),
    ("u", "SystemParametersInfoW", BOOL, (UINT, UINT, C.c_void_p, UINT)),
    ("u", "SetLayeredWindowAttributes", BOOL, (HANDLE, DWORD, BYTE, DWORD)),
    ("g", "GetStockObject", HANDLE, (C.c_int,)),
    ("g", "SetDCBrushColor", DWORD, (HANDLE, DWORD)),
    ("g", "CreateCompatibleDC", HANDLE, (HANDLE,)),
    ("g", "DeleteDC", BOOL, (HANDLE,)),
    ("g", "CreateDIBSection", HANDLE, (HANDLE, C.POINTER(BITMAPINFO), UINT, C.POINTER(C.c_void_p), HANDLE, DWORD)),
    ("g", "SelectObject", HANDLE, (HANDLE, HANDLE)),
    ("g", "DeleteObject", BOOL, (HANDLE,)),
    ("g", "GdiFlush", BOOL, ()),
    ("g", "BitBlt", BOOL, (HANDLE, C.c_int, C.c_int, C.c_int, C.c_int, HANDLE, C.c_int, C.c_int, DWORD)),
    ("g", "SetDIBitsToDevice", C.c_int, (HANDLE, C.c_int, C.c_int, DWORD, DWORD, C.c_int, C.c_int, UINT, UINT,
                                         C.c_void_p, C.POINTER(BITMAPINFO), UINT)),
    ("k", "GetModuleHandleW", HANDLE, (C.c_wchar_p,)),
    ("k", "GetCurrentThreadId", DWORD, ()),
    ("k", "GetCurrentThread", HANDLE, ()),
    ("k", "GetCurrentProcess", HANDLE, ()),
    ("k", "GetCurrentProcessId", DWORD, ()),
    ("k", "SetThreadPriority", BOOL, (HANDLE, C.c_int)),
    ("k", "CreateEventW", HANDLE, (C.c_void_p, BOOL, BOOL, C.c_wchar_p)),
    ("k", "SetEvent", BOOL, (HANDLE,)),
    ("k", "CloseHandle", BOOL, (HANDLE,)),
    ("k", "CreateWaitableTimerExW", HANDLE, (C.c_void_p, C.c_wchar_p, DWORD, DWORD)),
    ("k", "SetWaitableTimer", BOOL, (HANDLE, C.POINTER(C.c_int64), LONG, C.c_void_p, C.c_void_p, BOOL)),
    ("d", "DwmRegisterThumbnail", HRESULT, (HANDLE, HANDLE, C.POINTER(HANDLE))),
    ("d", "DwmUnregisterThumbnail", HRESULT, (HANDLE,)),
    ("d", "DwmQueryThumbnailSourceSize", HRESULT, (HANDLE, C.POINTER(SIZE))),
    ("d", "DwmUpdateThumbnailProperties", HRESULT, (HANDLE, C.POINTER(THUMBNAIL_PROPERTIES))),
    ("d", "DwmSetWindowAttribute", HRESULT, (HANDLE, DWORD, C.c_void_p, DWORD)),
    ("d", "DwmFlush", HRESULT, ()),
    ("d", "DwmGetCompositionTimingInfo", HRESULT, (HANDLE, C.POINTER(DWM_TIMING_INFO))),
    ("sh", "SHQueryUserNotificationState", HRESULT, (C.POINTER(C.c_int),)),
)
DLLS = (("u", "user32"), ("g", "gdi32"), ("k", "kernel32"), ("d", "dwmapi"), ("sh", "shell32"))
# Windows 11 (22000+) compositor clock; absent before: DwmFlush, then the waitable timer (P3).
OPTIONAL = (("dc", "dcomp", "DCompositionWaitForCompositorClock", DWORD, (UINT, C.c_void_p, DWORD)),
            ("dc", "dcomp", "DCompositionBoostCompositorClock", HRESULT, (BOOL,)))


class CarouselApi:
    """Win32 declarations only; constructing it resolves the exports and calls nothing."""

    def __init__(self):
        if sys.platform != "win32":
            raise OSError("the window carousel needs Windows")
        for attribute, name in DLLS:
            setattr(self, attribute, C.WinDLL(name, use_last_error=True))
        for attribute, name, result, args in DECLARATIONS:
            function = getattr(getattr(self, attribute), name)
            function.restype, function.argtypes = result, args
        self.optional = {}
        for attribute, dll, name, result, args in OPTIONAL:
            try:
                library = getattr(self, attribute, None) or C.WinDLL(dll, use_last_error=True)
                setattr(self, attribute, library)
                function = getattr(library, name)
                function.restype, function.argtypes = result, args
                self.optional[name] = function
            except (OSError, AttributeError):
                self.optional[name] = None
        # G1-1 (as the lead applies it to the thumbnails, R-h): DwmUpdateThumbnailProperties only
        # records the properties for DWM's next composition, so it is called GIL-keeping, back to
        # back for every thumbnail of a frame (update_thumbnails).
        self.dwm_update_py = C.PYFUNCTYPE(HRESULT, HANDLE, C.POINTER(THUMBNAIL_PROPERTIES))(
            ("DwmUpdateThumbnailProperties", self.d))

    @staticmethod
    def last_error():
        return C.get_last_error()


# ------------------------------------------------ Win32: the one window procedure
# One module-level thunk for every carousel class, never freed: Windows may still call it
# for a message racing DestroyWindow, and a freed ctypes thunk is an access violation.
_WINDOW_HANDLERS = {}         # hwnd -> handler(message, wparam, lparam) (carousel thread only)
_DEF_WINDOW_PROC = None
_CALLBACK_FAILURES = {"count": 0, "logged_at": None}


def _note_callback_failure():
    try:
        _CALLBACK_FAILURES["count"] += 1
        now = time.monotonic()
        last = _CALLBACK_FAILURES["logged_at"]
        if last is None or now - last >= LOG_INTERVAL_S:
            _CALLBACK_FAILURES["logged_at"] = now
            _LOGGER.warning("carousel window procedure failed (%d so far)", _CALLBACK_FAILURES["count"],
                            exc_info=True)
    except BaseException:
        pass


def _window_procedure(hwnd, message, wparam, lparam):
    """Nothing escapes into user32: an exception falls back to DefWindowProcW."""
    try:
        handler = _WINDOW_HANDLERS.get(hwnd)
        if handler is not None:
            result = handler(message, wparam, lparam)
            if result is not None:
                return int(result)
    except BaseException:
        _note_callback_failure()
    try:
        default = _DEF_WINDOW_PROC
        return default(hwnd, message, wparam, lparam) if default is not None else 0
    except BaseException:
        return 0


_WNDPROC_THUNK = WNDPROC(_window_procedure)
_KEPT_ALIVE = (_WNDPROC_THUNK,)


def _signed_word(value):
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


class _Surface:
    """A layered window's DIB section selected into a memory DC (carousel thread)."""
    __slots__ = ("hwnd", "rect", "mdc", "dib", "old", "bits", "canvas", "nbytes")

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.rect = None
        self.mdc = self.dib = self.old = self.bits = self.canvas = None
        self.nbytes = 0


class Win32CarouselBackend:
    """The carousel's only Win32 user. ``post``/``post_quit`` (any thread), ``capture`` /
    ``flush`` / ``prepare_capture_thread`` / ``prepare_worker_thread`` (worker threads) and
    ``gui_resources`` aside, every method runs on the NanoD-carousel thread that called
    ``create``."""

    def __init__(self, *, api=None, log=None):
        global _DEF_WINDOW_PROC
        self.api = api or CarouselApi()
        self.log = log if isinstance(log, _Log) else _Log(log)
        if isinstance(self.api, CarouselApi):
            _DEF_WINDOW_PROC = self.api.u.DefWindowProcW   # WM_NCCREATE needs a real default
        self.hinstance = None
        self.windows = {}
        self.surfaces = {}
        self.registered = []
        self.host_mode = None
        self.thread_id = None
        self.awareness = None
        self.event = None             # auto-reset: post() signals it (the compositor-clock wait's handle, P3)
        self._timer = None            # the high-resolution waitable timer (P3 fallback 2)
        self._on_event = self._on_input = None
        self._host_passive = False
        self._host_paint = None       # (bytes, BITMAPINFO) for the plain host
        self._retained = {}           # role -> the system holds its last ULW surface (RETAINED_ULW_ROLES)
        self._msg = MSG()
        self._thumb_props = THUMBNAIL_PROPERTIES()
        self._thumb_props.flags = DWM_TNP_ALL
        optional = getattr(self.api, "optional", {}) or {}
        self._clock_export = optional.get("DCompositionWaitForCompositorClock")
        self._boost_export = optional.get("DCompositionBoostCompositorClock")
        self.pacer = LoopPacer(timing=self._timing, clock_wait=self._clock_wait if self._clock_export else None,
                               timer_wait=self._timer_wait, flush=self._dwm_flush)

    @property
    def host_hwnd(self):
        return self.windows.get("host")

    # ----------------------------------------------------------------- start
    def prepare_thread(self):
        u, k = self.api.u, self.api.k
        previous = u.SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        self.awareness = u.GetAwarenessFromDpiAwarenessContext(u.GetThreadDpiAwarenessContext())
        if not previous or self.awareness != DPI_AWARENESS_PER_MONITOR_AWARE:
            self.log.warn("dpi", f"carousel: thread DPI awareness is {self.awareness}, not per-monitor")
        self.thread_id = k.GetCurrentThreadId()
        k.SetThreadPriority(k.GetCurrentThread(), THREAD_PRIORITY_ABOVE_NORMAL)       # P13
        self.event = k.CreateEventW(None, False, False, None)
        self.pacer.handles = (self.event,) if self.event else ()
        u.PeekMessageW(C.byref(self._msg), None, WM_USER, WM_USER, PM_NOREMOVE)   # the message queue
        return self.awareness

    def prepare_worker_thread(self):
        """NanoD-label / NanoD-snap: per-monitor DPI awareness and below-normal priority (P13)."""
        u, k = self.api.u, self.api.k
        u.SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        k.SetThreadPriority(k.GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL)

    def _register_class(self, role):
        api = self.api
        wc = WNDCLASSEXW()
        wc.cbSize = C.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = _WNDPROC_THUNK
        wc.hInstance = self.hinstance
        wc.lpszClassName = CLASS_NAMES[role]
        if role == "host":
            wc.hCursor = api.u.LoadCursorW(None, C.c_void_p(IDC_ARROW))
        if not api.u.RegisterClassExW(C.byref(wc)):
            error = api.last_error()
            if error != ERROR_CLASS_ALREADY_EXISTS:
                raise OSError(error, f"RegisterClassExW {CLASS_NAMES[role]}")
        self.registered.append(CLASS_NAMES[role])

    def _create_window(self, role, ex_style, owner=None, title=""):
        api = self.api
        hwnd = api.u.CreateWindowExW(ex_style, CLASS_NAMES[role], title, WS_POPUP, 0, 0, 1, 1,
                                     owner, None, self.hinstance, None)
        if not hwnd:
            raise OSError(api.last_error(), f"CreateWindowExW {role}")
        _WINDOW_HANDLERS[hwnd] = self._handler(role)
        self.windows[role] = hwnd
        on = BOOL(1)
        api.d.DwmSetWindowAttribute(hwnd, DWMWA_TRANSITIONS_FORCEDISABLED, C.byref(on), C.sizeof(on))
        if role in ("dim", "glass", "chrome", "toast") + LAYER_ROLES:
            self.surfaces[role] = _Surface(hwnd)
        return hwnd

    def create(self, on_event, on_input):
        """Register the classes and create every window hidden (dim -> glass -> host -> chrome ->
        label / dots ownership, toast unowned). The host is NOREDIRECTIONBITMAP unless that fails."""
        self._on_event, self._on_input = on_event, on_input
        self.hinstance = self.api.k.GetModuleHandleW(None)
        for role in CLASS_NAMES:
            self._register_class(role)
        dim = self._create_window("dim", LAYER_EX_STYLE)
        glass = self._create_window("glass", LAYER_EX_STYLE, dim)
        try:
            self._create_host(HOST_EX_STYLE, glass)
            self.host_mode = HOST_LAYERED
        except OSError as exc:
            self.log.warn("noredirection", f"carousel: NOREDIRECTIONBITMAP host unavailable ({exc!r}); plain host")
            self._create_host(PLAIN_HOST_EX_STYLE, dim)
            self.host_mode = HOST_PLAIN
        self._create_chrome_and_layers()
        self._create_window("toast", LAYER_EX_STYLE)
        return self.windows["host"]

    def _create_chrome_and_layers(self):
        chrome = self._create_window("chrome", LAYER_EX_STYLE, self.windows["host"])
        for role in LAYER_ROLES:
            self._create_window(role, LAYER_EX_STYLE, chrome)
        self._create_gpu_window()

    def _create_gpu_window(self):
        """The GPU chrome's window (CAR 12.4): owned by the host (always above it and its thumbnails),
        click-through and never activating like the layers, NOREDIRECTIONBITMAP for its
        DirectComposition target; a layered window needs its attributes set once to show anything.
        Best effort: without it the picker keeps the CPU chrome."""
        hwnd = None
        try:
            hwnd = self._create_window("gpu", GPU_EX_STYLE, self.windows["host"])
            if not self.api.u.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA):
                raise OSError(self.api.last_error(), "SetLayeredWindowAttributes gpu")
        except Exception as exc:
            self.windows.pop("gpu", None)
            if hwnd:
                _WINDOW_HANDLERS.pop(hwnd, None)
                try:
                    self.api.u.DestroyWindow(hwnd)
                except Exception:
                    pass
            self.log.warn("gpu-window", f"carousel: the GPU chrome's window is unavailable ({exc!r})")

    def _create_host(self, ex_style, owner):
        hwnd = self._create_window("host", ex_style, owner, HOST_TITLE)
        value = C.c_int(DWMWCP_DONOTROUND)
        self.api.d.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, C.byref(value), C.sizeof(value))
        return hwnd

    def _destroy_host_and_chrome(self):
        for role in ("gpu",) + LAYER_ROLES + ("chrome", "host"):
            self._free_surface(role)
            hwnd = self.windows.pop(role, None)
            if hwnd:
                self.api.u.DestroyWindow(hwnd)
                _WINDOW_HANDLERS.pop(hwnd, None)
            self.surfaces.pop(role, None)
            self._retained.pop(role, None)
        self._host_paint = None
        self._host_passive = False

    def use_plain_host(self):
        """CAR section 5 fallback: recreate the host (a plain popup owned by the dim), the chrome
        and the layers."""
        self._destroy_host_and_chrome()
        self._create_host(PLAIN_HOST_EX_STYLE, self.windows["dim"])
        self.host_mode = HOST_PLAIN
        self._create_chrome_and_layers()

    def use_layered_host(self):
        """Leave the fallback: recreate the NOREDIRECTIONBITMAP host (owned by the glass), the chrome
        and the layers; if that host cannot be created, a plain one again. True when layered."""
        self._destroy_host_and_chrome()
        try:
            self._create_host(HOST_EX_STYLE, self.windows["glass"])
            self.host_mode = HOST_LAYERED
        except OSError as exc:
            self.log.warn("noredirection", f"carousel: NOREDIRECTIONBITMAP host unavailable ({exc!r}); plain host")
            self._create_host(PLAIN_HOST_EX_STYLE, self.windows["dim"])
            self.host_mode = HOST_PLAIN
        self._create_chrome_and_layers()
        return self.host_mode == HOST_LAYERED

    # -------------------------------------------------------------- messages
    def _handler(self, role):
        def layer(message, wparam, lparam):
            if message == WM_NCHITTEST:
                return HTTRANSPARENT
            if message == WM_MOUSEACTIVATE:
                return MA_NOACTIVATE
            if role == "dim":
                event = POSTED_EVENTS.get(message)
                if event is not None:
                    if self._on_event is not None:
                        self._on_event(event)
                    return 0
                if message == WM_POWERBROADCAST:
                    if self._on_event is not None:
                        if wparam == PBT_APMSUSPEND:
                            self._on_event(EV_SUSPEND)
                        elif wparam in (PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC):
                            self._on_event(EV_DISPLAY)
                    return 1
                if message in (WM_DISPLAYCHANGE, WM_DWMCOMPOSITIONCHANGED):
                    # Broadcast to top-level windows, the hidden dim included: an open picker closes
                    # as 'display' (K4 15), the plain-host fallback may try the layered host again.
                    if self._on_event is not None:
                        self._on_event(EV_DISPLAY)
                    return None
                if message == WM_DESTROY:
                    self.api.u.PostQuitMessage(0)
                    return 0
            if message == WM_CLOSE:
                return 0
            return None

        def host(message, wparam, lparam):
            if message == WM_NCHITTEST:
                # rcMonitor-sized in v7: it eats clicks anywhere on the monitor (K4 3); during an exit
                # the clicks are swallowed too (never passed to the hidden desktop).
                return HTCLIENT
            if message == WM_MOUSEACTIVATE and (self._host_passive or self._foreground_is_foreign()):
                # A click never takes the foreground back from another application: the Tk
                # thread may already have given it to the Switch/Back target (other processes
                # only) before this thread has the exit's Dismiss.
                return MA_NOACTIVATEANDEAT
            if message == WM_ERASEBKGND:
                return 1
            if message == WM_PAINT:
                self._paint_host()
                return 0
            if message == WM_ACTIVATE:
                # The adapter's native.focus(host) completed here: wake the loop, which defers
                # the open's heavy setup until now (CarouselEngine._open).
                if (int(wparam) & 0xFFFF) != WA_INACTIVE and not self._host_passive:
                    self.post(WM_APP_ACTIVATED)
                return None
            report = self._on_input
            if message == WM_KEYDOWN:
                if report is not None and not self._host_passive:
                    report(IN_KEY, int(wparam), (int(lparam) >> 30) & 1)
                return 0 if int(wparam) in (VK_RETURN, VK_ESCAPE, VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN) else None
            if message in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
                if report is not None and not self._host_passive:
                    report(IN_WHEEL if message == WM_MOUSEWHEEL else IN_HWHEEL, _signed_word(int(wparam) >> 16))
                return 0
            if message == WM_LBUTTONUP:
                if report is not None and not self._host_passive:
                    report(IN_CLICK, _signed_word(int(lparam)), _signed_word(int(lparam) >> 16))
                return 0
            if message == WM_CLOSE:
                if report is not None and not self._host_passive:
                    report(IN_CLOSE)
                return 0
            return None

        return host if role == "host" else layer

    def _paint_host(self):
        api = self.api
        hwnd = self.windows.get("host")
        ps = PAINTSTRUCT()
        hdc = api.u.BeginPaint(hwnd, C.byref(ps))
        try:
            paint = self._host_paint
            if hdc and self.host_mode == HOST_PLAIN:
                if paint is not None:
                    data, bmi, w, h = paint
                    api.g.SetDIBitsToDevice(hdc, 0, 0, w, h, 0, 0, 0, h, data, C.byref(bmi), DIB_RGB_COLORS)
                else:
                    # Until the frost (or the tint) arrives: a flat colour, so the open builds no
                    # bitmap before its handshake (an ordinary redirected window: GDI is fine here).
                    api.g.SetDCBrushColor(hdc, PLAIN_PANE_COLORREF)
                    api.u.FillRect(hdc, C.byref(ps.rcPaint), api.g.GetStockObject(DC_BRUSH))
        finally:
            api.u.EndPaint(hwnd, C.byref(ps))

    def post(self, code):
        """Any thread: PostMessageW to the dim window (the carousel's message target), and the
        mailbox event for a loop waiting on the compositor clock (P3)."""
        hwnd = self.windows.get("dim")
        ok = bool(hwnd) and bool(self.api.u.PostMessageW(hwnd, code, 0, 0))
        if ok and self.event:
            self.api.k.SetEvent(self.event)
        return ok

    def post_quit(self):
        return bool(self.thread_id) and bool(self.api.u.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0))

    def pump(self):
        u, msg = self.api.u, self._msg
        while u.PeekMessageW(C.byref(msg), None, 0, 0, PM_REMOVE):
            if msg.message == WM_QUIT:
                return False
            u.TranslateMessage(C.byref(msg))
            u.DispatchMessageW(C.byref(msg))
        return True

    def wait(self, timeout):
        """P8: block until a message, the mailbox event or ``timeout`` (idle-path waits only: the
        capture, activation, snap-backstop and toast deadlines). The loop's pump() then reads
        the queue."""
        ms = INFINITE if timeout is None else max(1, min(0x7FFFFFFE, int(math.ceil(timeout * 1000 - 1e-6))))
        handles = (HANDLE * 1)(self.event) if self.event else None
        self.api.u.MsgWaitForMultipleObjectsEx(1 if self.event else 0, handles, ms, QS_ALLINPUT, MWMO_INPUTAVAILABLE)
        return True

    # ---------------------------------------------------------------- pacing (K4 5)
    def _timing(self):
        info = DWM_TIMING_INFO()
        info.cbSize = C.sizeof(DWM_TIMING_INFO)
        if self.api.d.DwmGetCompositionTimingInfo(None, C.byref(info)) != 0:
            return None
        qpf = _qpc_frequency()
        if not qpf or not info.qpcRefreshPeriod:
            return None
        return info.qpcVBlank / qpf, info.qpcRefreshPeriod / qpf

    def _clock_wait(self, handles, timeout_ms):
        count = len(handles)
        array = (HANDLE * max(1, count))(*handles) if count else None
        code = int(self._clock_export(count, array, int(timeout_ms))) & 0xFFFFFFFF
        if code == WAIT_OBJECT_0 + count:
            return "tick", None
        if WAIT_OBJECT_0 <= code < WAIT_OBJECT_0 + count:
            return "handle", code - WAIT_OBJECT_0
        if code == WAIT_TIMEOUT:
            return "timeout", None
        return "no_clock", code

    def _timer_wait(self, handles, seconds):
        k = self.api.k
        if self._timer is None:
            self._timer = (k.CreateWaitableTimerExW(None, None, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS)
                           or k.CreateWaitableTimerExW(None, None, 0, TIMER_ALL_ACCESS) or 0)
        items = list(handles)
        if self._timer:
            due = C.c_int64(-max(1, int(seconds * 1e7)))
            k.SetWaitableTimer(self._timer, C.byref(due), 0, None, None, False)
            items.append(self._timer)
        array = (HANDLE * max(1, len(items)))(*items) if items else None
        self.api.u.MsgWaitForMultipleObjectsEx(len(items), array, max(1, int(seconds * 4000)), 0, 0)

    def _dwm_flush(self):
        return self.api.d.DwmFlush()

    def pace(self):
        """P3/P5: wait for the next vblank to present on."""
        return self.pacer.wait()

    def frame_target(self, now):
        return self.pacer.target(now)

    def frame_done(self, t_wake, work_s, *, oneoff=False, p5=True):
        return self.pacer.frame_done(t_wake, work_s, oneoff=oneoff, p5=p5)

    def boost(self, on):
        """P11: DCompositionBoostCompositorClock for each episode (Windows 11)."""
        if self._boost_export is not None:
            self._boost_export(bool(on))

    # -------------------------------------------------------------- geometry
    def monitor_info(self, origin_hwnd):
        """(rcMonitor, rcWork), physical px, of the monitor holding ``origin`` (else the foreground
        window's; K4 0.3)."""
        u = self.api.u
        hwnd = origin_hwnd or u.GetForegroundWindow()
        monitor = u.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST) if hwnd else None
        if not monitor:
            monitor = u.MonitorFromPoint(POINT(0, 0), MONITOR_DEFAULTTOPRIMARY)
        info = MONITORINFO()
        info.cbSize = C.sizeof(MONITORINFO)
        if not monitor or not u.GetMonitorInfoW(monitor, C.byref(info)):
            raise OSError(self.api.last_error(), "GetMonitorInfoW")
        m, w = info.rcMonitor, info.rcWork
        return (m.left, m.top, m.right, m.bottom), (w.left, w.top, w.right, w.bottom)

    def monitor_rect(self, origin_hwnd):
        return self.monitor_info(origin_hwnd)[0]

    def system_reduced_motion(self):
        """Windows *Animation effects* off (SPI_GETCLIENTAREAANIMATION), when the Tk side gave no
        Motion setting (K4 16)."""
        value = BOOL(1)
        if not self.api.u.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, C.byref(value), 0):
            return False
        return not bool(value.value)

    def notification_busy(self):
        """K4 10.4: a full-screen D3D app (3) or presentation mode (4): toasts are dropped."""
        state = C.c_int(0)
        if self.api.sh.SHQueryUserNotificationState(C.byref(state)) != 0:
            return False
        return state.value in (QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE)

    # ------------------------------------------------------------------ host
    def show_host(self, rect):
        """Place the host on ``rect`` (rcMonitor, K4 9.2) and show it without activating (the
        adapter's native.focus makes it the foreground right after the handshake)."""
        hwnd = self.windows.get("host")
        if not hwnd:
            return False
        x, y, w, h = (int(v) for v in rect)
        self._host_passive = False
        self.api.u.SetWindowPos(hwnd, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW)
        return bool(self.api.u.IsWindowVisible(hwnd))

    def set_host_passive(self, passive):
        """During an exit: the host never activates on a click (MA_NOACTIVATEANDEAT) and ignores
        keys and the wheel; clicks are still eaten."""
        self._host_passive = bool(passive)

    def _foreground_is_foreign(self):
        """True when there is no foreground window or it belongs to another process."""
        u = self.api.u
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return True
        owner = DWORD(0)
        u.GetWindowThreadProcessId(hwnd, C.byref(owner))
        return int(owner.value) != int(self.api.k.GetCurrentProcessId())

    def refocus_host(self):
        """K4 9.6 step 8: after a placement the picker host must still own the foreground; if it
        does not, ask once (it works only while this process still holds the grant). The adapter's
        focus-loss path closes the picker as focus_lost otherwise."""
        hwnd = self.windows.get("host")
        if hwnd and self._foreground_is_foreign():
            return bool(self.api.u.SetForegroundWindow(hwnd))
        return True

    def host_paint(self, image):
        """Plain host only: the frost it paints itself in WM_PAINT (the degraded fallback): an
        opaque premultiplied Canvas (frost_canvas) or a straight image (over black)."""
        if self.host_mode != HOST_PLAIN:
            return
        if isinstance(image, R.Canvas):
            data = image.image.tobytes()
        else:
            image = image.convert("RGBA")
            backdrop = R.Image.new("RGBA", image.size, (0, 0, 0, 255))
            data = R.Image.alpha_composite(backdrop, image).tobytes("raw", "BGRA")
        w, h = image.size
        self._host_paint = (data, self._bmi(w, h), w, h)
        hwnd = self.windows.get("host")
        if hwnd:
            self.api.u.InvalidateRect(hwnd, None, False)

    # -------------------------------------------------------------- affinity
    def _affinity(self, roles, exclude):
        value = WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE
        ok = True
        for role in roles:
            hwnd = self.windows.get(role)
            if hwnd and not self.api.u.SetWindowDisplayAffinity(hwnd, value):
                ok = False
        if not ok:
            self.log.warn("affinity", f"carousel: SetWindowDisplayAffinity failed (error {self.api.last_error()})")
        return ok

    def set_affinity(self, exclude):
        return self._affinity(("dim", "glass", "host", "chrome") + LAYER_ROLES + ("gpu",), exclude)

    def set_toast_affinity(self, exclude):
        return self._affinity(("toast",), exclude)

    def set_capture_exclusions(self, hwnds, exclude):
        """WDA_EXCLUDEFROMCAPTURE (or WDA_NONE) on other windows of this process (the floating
        knob) while the frost capture runs. A window of another process, or one that is gone, is
        skipped: SetWindowDisplayAffinity only works on the caller's own windows."""
        value = WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE
        u = self.api.u
        pid = int(self.api.k.GetCurrentProcessId())
        ok = True
        for hwnd in hwnds or ():
            if not hwnd or not u.IsWindow(hwnd):
                continue
            owner = DWORD(0)
            u.GetWindowThreadProcessId(hwnd, C.byref(owner))
            if int(owner.value) != pid:
                continue
            if not u.SetWindowDisplayAffinity(hwnd, value):
                ok = False
        if not ok:
            self.log.warn("affinity-extra", "carousel: SetWindowDisplayAffinity on an excluded window failed "
                                            f"(error {self.api.last_error()})")
        return ok

    # ---------------------------------------------------------------- layers
    @staticmethod
    def _bmi(w, h):
        bmi = BITMAPINFO()
        header = bmi.bmiHeader
        header.biSize = C.sizeof(BITMAPINFOHEADER)
        header.biWidth, header.biHeight = int(w), -int(h)       # top-down
        header.biPlanes, header.biBitCount, header.biCompression = 1, 32, BI_RGB
        return bmi

    def _alloc_surface(self, role, rect):
        surface = self.surfaces[role]
        x, y, w, h = (int(v) for v in rect)
        if surface.dib and surface.rect is not None and surface.rect[2:] == (w, h):
            surface.rect = (x, y, w, h)
            return surface
        self._free_surface(role)
        api = self.api
        mdc = api.g.CreateCompatibleDC(None)
        if not mdc:
            raise OSError(api.last_error(), "CreateCompatibleDC")
        bits = C.c_void_p()
        dib = api.g.CreateDIBSection(mdc, C.byref(self._bmi(w, h)), DIB_RGB_COLORS, C.byref(bits), None, 0)
        if not dib or not bits.value:
            if dib:
                api.g.DeleteObject(dib)
            api.g.DeleteDC(mdc)
            raise OSError(api.last_error(), "CreateDIBSection")
        surface.mdc, surface.dib, surface.bits = mdc, dib, bits.value
        surface.old = api.g.SelectObject(mdc, dib)
        surface.nbytes = w * h * 4
        C.memset(surface.bits, 0, surface.nbytes)
        buffer = (C.c_ubyte * surface.nbytes).from_address(surface.bits)
        surface.canvas = R.Canvas.over_buffer(buffer, (w, h))
        surface.rect = (x, y, w, h)
        return surface

    def _free_surface(self, role):
        surface = self.surfaces.get(role)
        if surface is None or not surface.dib:
            return
        api = self.api
        surface.canvas = None         # no view of the bits may outlive them
        api.g.GdiFlush()
        if surface.old and surface.mdc:
            api.g.SelectObject(surface.mdc, surface.old)
        api.g.DeleteObject(surface.dib)
        if surface.mdc:
            api.g.DeleteDC(surface.mdc)
        surface.mdc = surface.dib = surface.old = surface.bits = None
        surface.nbytes = 0

    def _ulw(self, role, alpha, content=True, pos=None, dirty=None):
        surface = self.surfaces[role]
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, max(0, min(255, int(alpha))), AC_SRC_ALPHA)
        u = self.api.u
        if content:
            if not surface.dib:
                return False
            x, y, w, h = surface.rect
            if pos is not None:
                x, y = int(pos[0]), int(pos[1])
                surface.rect = (x, y, w, h)
            if dirty is not None:
                # B5: UpdateLayeredWindowIndirect with prcDirty (the union of the last and this
                # frame's footprints); the rest of the window keeps its last content.
                l, t, r, b = (int(v) for v in dirty)
                info = UPDATELAYEREDWINDOWINFO()
                info.cbSize = C.sizeof(UPDATELAYEREDWINDOWINFO)
                point, size, src = POINT(x, y), SIZE(w, h), POINT(0, 0)
                rect = RECT(max(0, l), max(0, t), min(w, r), min(h, b))
                info.pptDst, info.psize, info.hdcSrc, info.pptSrc = C.pointer(point), C.pointer(size), surface.mdc, C.pointer(src)
                info.pblend, info.dwFlags, info.prcDirty = C.pointer(blend), ULW_ALPHA, C.pointer(rect)
                ok = u.UpdateLayeredWindowIndirect(surface.hwnd, C.byref(info))
            else:
                ok = u.UpdateLayeredWindow(surface.hwnd, None, C.byref(POINT(x, y)), C.byref(SIZE(w, h)),
                                           surface.mdc, C.byref(POINT(0, 0)), 0, C.byref(blend), ULW_ALPHA)
            if ok:
                self._retained[role] = True           # the system keeps it until release_retained
        else:
            # Constant alpha (and a move) only: the window keeps the content of its last update.
            point = C.byref(POINT(int(pos[0]), int(pos[1]))) if pos is not None else None
            ok = u.UpdateLayeredWindow(surface.hwnd, None, point, None, None, None, 0, C.byref(blend), ULW_ALPHA)
        if not ok:
            self.log.warn(f"ulw-{role}", f"carousel: UpdateLayeredWindow({role}) failed (error {self.api.last_error()})")
        return bool(ok)

    def _show(self, role):
        hwnd = self.windows.get(role)
        if hwnd:
            self.api.u.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SHOW_FLAGS)

    def _hide(self, role):
        hwnd = self.windows.get(role)
        if hwnd:
            self.api.u.ShowWindow(hwnd, SW_HIDE)

    def chrome_alloc(self, rect):
        return self._alloc_surface("chrome", rect).canvas

    def chrome_canvas(self):
        surface = self.surfaces.get("chrome")
        return surface.canvas if surface is not None and surface.dib else None

    def chrome_present(self, dirty=None):
        self.api.g.GdiFlush()
        return self._ulw("chrome", 255, dirty=dirty)

    def chrome_show(self):
        self._show("chrome")

    def chrome_free(self):
        self._free_surface("chrome")

    def layer_alloc(self, role, rect):
        """B2: the label or dots layer's DIB (its window is placed on each present)."""
        return self._alloc_surface(role, rect).canvas

    def layer_canvas(self, role):
        surface = self.surfaces.get(role)
        return surface.canvas if surface is not None and surface.dib else None

    def layer_present(self, role, alpha, pos=None):
        self.api.g.GdiFlush()
        return self._ulw(role, alpha, pos=pos)

    def layer_alpha(self, role, alpha, pos=None):
        return self._ulw(role, alpha, content=False, pos=pos)

    def layer_show(self, role):
        self._show(role)

    def layer_free(self, role):
        self._free_surface(role)

    def dim_upload(self, layout, background):
        """Build No background's flat dim (black at 55 %), upload it at constant alpha 0 and free
        its DIB at once: fades only change SourceConstantAlpha."""
        surface = self._alloc_surface("dim", layout.monitor_rect)
        try:
            R.build_dim(surface.canvas, layout, background)
            self.api.g.GdiFlush()
            self._ulw("dim", 0)
        finally:
            self._free_surface("dim")

    def dim_show(self):
        self._show("dim")

    def dim_alpha(self, alpha):
        return self._ulw("dim", alpha, content=False)

    def glass_upload(self, rect, image):
        """The frost over the whole monitor (``rect`` is rcMonitor) at constant alpha 0, shown
        (click-through); DIB freed. ``image`` is a premultiplied Canvas (copied as is) or a
        straight image (premultiplied here)."""
        surface = self._alloc_surface("glass", rect)
        try:
            if isinstance(image, R.Canvas):
                if tuple(image.size) != tuple(surface.rect[2:]):
                    raise OSError("glass size mismatch")
                surface.canvas.image.paste(image.image, (0, 0))
            else:
                data = R.premultiplied_bgra(image)
                if len(data) != surface.nbytes:
                    raise OSError("glass size mismatch")
                C.memmove(surface.bits, data, surface.nbytes)
            self.api.g.GdiFlush()
            self._ulw("glass", 0)
        finally:
            self._free_surface("glass")
        self._show("glass")

    def glass_alpha(self, alpha):
        return self._ulw("glass", alpha, content=False)

    def toast_alloc(self, rect):
        return self._alloc_surface("toast", rect).canvas

    def toast_canvas(self):
        surface = self.surfaces.get("toast")
        return surface.canvas if surface is not None and surface.dib else None

    def toast_present(self, alpha):
        self.api.g.GdiFlush()
        return self._ulw("toast", alpha)

    def toast_show(self):
        self._show("toast")

    def toast_hide(self):
        self._hide("toast")

    def toast_free(self):
        self._free_surface("toast")

    def hide_layers(self):
        """chrome -> label / dots -> host -> glass -> dim (thumbnails are already unregistered); then
        the hidden layered windows give back their retained surfaces (release_retained)."""
        for role in ("gpu", "chrome") + LAYER_ROLES + ("host", "glass", "dim"):
            self._hide(role)
        self._host_passive = False
        self.release_retained()

    def release_retained(self):
        """UpdateLayeredWindow's last surface stays committed by the system after hide; once the
        layers are hidden each is replaced by one transparent pixel. Every open uploads full
        content again before a fade. Best effort; our 1 x 1 DIB is freed at once."""
        roles = [role for role in RETAINED_ULW_ROLES if self._retained.get(role) and self.windows.get(role)]
        if not roles:
            return 0
        api = self.api
        mdc = api.g.CreateCompatibleDC(None)
        if not mdc:
            return 0
        bits = C.c_void_p()
        dib = api.g.CreateDIBSection(mdc, C.byref(self._bmi(1, 1)), DIB_RGB_COLORS, C.byref(bits), None, 0)
        released = 0
        try:
            if not dib or not bits.value:
                return 0
            old = api.g.SelectObject(mdc, dib)
            C.memset(bits.value, 0, 4)
            api.g.GdiFlush()
            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 0, AC_SRC_ALPHA)
            for role in roles:
                if api.u.UpdateLayeredWindow(self.windows[role], None, None, C.byref(SIZE(1, 1)), mdc,
                                             C.byref(POINT(0, 0)), 0, C.byref(blend), ULW_ALPHA):
                    self._retained[role] = False
                    released += 1
                else:
                    self.log.warn(f"release-{role}", f"carousel: releasing the {role} surface failed "
                                                     f"(error {api.last_error()})")
            if old:
                api.g.SelectObject(mdc, old)
        finally:
            if dib:
                api.g.DeleteObject(dib)
            api.g.DeleteDC(mdc)
        return released

    def free_large(self):
        """Free the DIBs larger than 1 MB (chrome, label, and the plain host's frost)."""
        for role, surface in self.surfaces.items():
            if surface.dib and surface.nbytes > LARGE_DIB_BYTES and role != "toast":
                self._free_surface(role)
        self._host_paint = None

    # ------------------------------------------------------------ thumbnails
    def register(self, source_hwnd):
        host = self.windows.get("host")
        handle = HANDLE()
        if not host or not source_hwnd:
            return None
        if self.api.d.DwmRegisterThumbnail(host, source_hwnd, C.byref(handle)) != 0:
            return None
        return handle.value

    def source_size(self, handle):
        size = SIZE()
        if self.api.d.DwmQueryThumbnailSourceSize(handle, C.byref(size)) != 0:
            return None
        return (int(size.cx), int(size.cy))

    def update_thumbnail(self, handle, dest, source, opacity, visible):
        """All five property flags on every update (CAR section 2)."""
        props = THUMBNAIL_PROPERTIES()
        props.flags = DWM_TNP_ALL
        props.destination = RECT(*(int(v) for v in dest))
        props.source = RECT(*(int(v) for v in source))
        props.opacity = max(0, min(255, int(opacity)))
        props.visible = bool(visible)
        props.source_client_only = False
        return self.api.d.DwmUpdateThumbnailProperties(handle, C.byref(props)) == 0

    def update_thumbnails(self, updates):
        """Every thumbnail update of one frame, back to back, through the GIL-keeping export (G1-1,
        batched: no GIL hand-off between the calls): [(handle, dest, source, opacity, visible)]."""
        fn = getattr(self.api, "dwm_update_py", None)
        if fn is None:
            return all([self.update_thumbnail(*u) for u in updates])
        props = self._thumb_props
        dst, src = props.destination, props.source
        ok = True
        for handle, dest, source, opacity, visible in updates:
            dst.left, dst.top, dst.right, dst.bottom = (int(v) for v in dest)
            src.left, src.top, src.right, src.bottom = (int(v) for v in source)
            props.opacity = max(0, min(255, int(opacity)))
            props.visible = 1 if visible else 0
            if fn(handle, C.byref(props)) != 0:
                ok = False
        return ok

    def unregister(self, handle):
        if handle:
            self.api.d.DwmUnregisterThumbnail(handle)

    # ------------------------------------------------------------ the GPU chrome's window (CAR 12.4)
    @property
    def has_gpu_window(self):
        """True while the GPU chrome's window exists (``_create_gpu_window`` is best effort); the
        engine's ``_gpu_usable`` reads this, never the ``gpu_window`` method (WP7c-R7)."""
        return bool(self.windows.get("gpu"))

    def gpu_window(self, rect):
        """Place the GPU chrome's window on ``rect`` (rcMonitor: the thumbnails' host-local px are its
        client px) without showing or activating it; its hwnd (the DirectComposition target), or
        None when the window does not exist."""
        hwnd = self.windows.get("gpu")
        if not hwnd:
            return None
        x, y, w, h = (int(v) for v in rect)
        self.api.u.SetWindowPos(hwnd, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE)
        return hwnd

    def gpu_show(self):
        self._show("gpu")

    def gpu_hide(self):
        self._hide("gpu")

    # --------------------------------------------------------------- capture
    def prepare_capture_thread(self):
        self.api.u.SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        self.api.k.SetThreadPriority(self.api.k.GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL)

    def flush(self):
        return self.api.d.DwmFlush()

    def capture(self, rect):
        """Any thread: BitBlt(SRCCOPY | CAPTUREBLT) of the screen DC -> PIL RGB, or None, decoded
        straight from the DIB's memory before the DIB is freed."""
        api = self.api
        x, y, w, h = (int(v) for v in rect)
        if w <= 0 or h <= 0:
            return None
        screen = api.u.GetDC(None)
        if not screen:
            return None
        mdc = dib = old = None
        try:
            mdc = api.g.CreateCompatibleDC(screen)
            bits = C.c_void_p()
            dib = api.g.CreateDIBSection(screen, C.byref(self._bmi(w, h)), DIB_RGB_COLORS, C.byref(bits), None, 0)
            if not mdc or not dib or not bits.value:
                return None
            old = api.g.SelectObject(mdc, dib)
            ok = api.g.BitBlt(mdc, 0, 0, w, h, screen, x, y, SRCCOPY | CAPTUREBLT)
            api.g.GdiFlush()
            if not ok:
                return None
            view = (C.c_ubyte * (w * h * 4)).from_address(bits.value)
            image = R.Image.frombuffer("RGB", (w, h), view, "raw", "BGRX", 0, 1)
            view = None
        finally:
            if old and mdc:
                api.g.SelectObject(mdc, old)
            if dib:
                api.g.DeleteObject(dib)
            if mdc:
                api.g.DeleteDC(mdc)
            api.u.ReleaseDC(None, screen)
        return image

    # -------------------------------------------------------------- teardown
    def destroy_windows(self):
        """DIBs and DCs, then DestroyWindow toast, layers, chrome, host, glass, dim (whose
        WM_DESTROY posts the loop's WM_QUIT); the event and the timer. Idempotent."""
        for role in list(self.surfaces):
            self._free_surface(role)
        self._host_paint = None
        self._retained.clear()                     # DestroyWindow frees them
        for role in ("toast", "gpu") + LAYER_ROLES + ("chrome", "host", "glass", "dim"):
            hwnd = self.windows.pop(role, None)
            if hwnd:
                if not self.api.u.DestroyWindow(hwnd):
                    self.log.warn("destroy", f"carousel: DestroyWindow({role}) failed (error {self.api.last_error()})")
                _WINDOW_HANDLERS.pop(hwnd, None)
        self.surfaces.clear()
        self._on_event = self._on_input = None
        for attribute in ("event", "_timer"):
            handle = getattr(self, attribute)
            if handle:
                self.api.k.CloseHandle(handle)
            setattr(self, attribute, None)
        self.pacer.handles = ()

    def unregister_classes(self):
        for name in self.registered:
            self.api.u.UnregisterClassW(name, self.hinstance)
        self.registered = []

    def destroy(self):
        self.destroy_windows()
        self.unregister_classes()

    def gui_resources(self):
        api = self.api
        process = api.k.GetCurrentProcess()
        return int(api.u.GetGuiResources(process, GR_GDIOBJECTS)), int(api.u.GetGuiResources(process, GR_USEROBJECTS))


_QPF = []


def _qpc_frequency():
    if not _QPF:
        value = C.c_int64(0)
        try:
            C.windll.kernel32.QueryPerformanceFrequency(C.byref(value))
        except Exception:
            pass
        _QPF.append(int(value.value) or 0)
    return _QPF[0]


# ================================================================ Win32: NanoD-snap's native layer
TOKEN_QUERY, PROCESS_QUERY_LIMITED_INFORMATION, TOKEN_INTEGRITY_LEVEL = 0x0008, 0x1000, 25
SNAP_DECLARATIONS = (
    ("u", "IsWindow", BOOL, (HANDLE,)),
    ("u", "IsIconic", BOOL, (HANDLE,)),
    ("u", "IsZoomed", BOOL, (HANDLE,)),
    ("u", "IsHungAppWindow", BOOL, (HANDLE,)),
    ("u", "GetWindowPlacement", BOOL, (HANDLE, C.POINTER(WINDOWPLACEMENT))),
    ("u", "GetWindowRect", BOOL, (HANDLE, C.POINTER(RECT))),
    ("u", "ShowWindowAsync", BOOL, (HANDLE, C.c_int)),
    ("u", "SetWindowPos", BOOL, (HANDLE, HANDLE, C.c_int, C.c_int, C.c_int, C.c_int, UINT)),
    ("u", "GetForegroundWindow", HANDLE, ()),
    ("u", "MonitorFromWindow", HANDLE, (HANDLE, DWORD)),
    ("u", "GetMonitorInfoW", BOOL, (HANDLE, C.POINTER(MONITORINFO))),
    ("u", "GetWindowThreadProcessId", DWORD, (HANDLE, C.POINTER(DWORD))),
    ("d", "DwmGetWindowAttribute", HRESULT, (HANDLE, DWORD, C.c_void_p, DWORD)),
    ("k", "OpenProcess", HANDLE, (DWORD, BOOL, DWORD)),
    ("k", "CloseHandle", BOOL, (HANDLE,)),
    ("k", "GetCurrentProcess", HANDLE, ()),
    ("a", "OpenProcessToken", BOOL, (HANDLE, DWORD, C.POINTER(HANDLE))),
    ("a", "GetTokenInformation", BOOL, (HANDLE, C.c_int, C.c_void_p, DWORD, C.POINTER(DWORD))),
    ("a", "GetSidSubAuthorityCount", C.POINTER(C.c_ubyte), (C.c_void_p,)),
    ("a", "GetSidSubAuthority", C.POINTER(DWORD), (C.c_void_p, DWORD)),
)


class Win32SnapNative:
    """The calls NanoD-snap may make (K4 9.6). Only ``show_async`` (ShowWindowAsync) and
    ``set_pos_async`` (SetWindowPos with SWP_ASYNCWINDOWPOS, asserted) reach a target window;
    every other call reads state that never waits on the target's thread. ``identity`` is the
    adapter's NativeWindows.identity (the snapshot's identity ids)."""

    def __init__(self, identity=None):
        if sys.platform != "win32":
            raise OSError("the snap worker needs Windows")
        self.u = C.WinDLL("user32", use_last_error=True)
        self.d = C.WinDLL("dwmapi", use_last_error=True)
        self.k = C.WinDLL("kernel32", use_last_error=True)
        self.a = C.WinDLL("advapi32", use_last_error=True)
        for attribute, name, result, args in SNAP_DECLARATIONS:
            function = getattr(getattr(self, attribute), name)
            function.restype, function.argtypes = result, args
        self._identity = identity
        self._own_level = None

    def identity(self, hwnd):
        if self._identity is None:
            return None
        return self._identity(hwnd)

    def is_window(self, hwnd):
        return bool(self.u.IsWindow(hwnd))

    def is_iconic(self, hwnd):
        return bool(self.u.IsIconic(hwnd))

    def is_zoomed(self, hwnd):
        return bool(self.u.IsZoomed(hwnd))

    def is_hung(self, hwnd):
        return bool(self.u.IsHungAppWindow(hwnd))

    def placement(self, hwnd):
        wp = WINDOWPLACEMENT()
        wp.length = C.sizeof(WINDOWPLACEMENT)
        if not self.u.GetWindowPlacement(hwnd, C.byref(wp)):
            return None
        r = wp.rcNormalPosition
        return int(wp.flags), int(wp.showCmd), (r.left, r.top, r.right, r.bottom)

    def window_rect(self, hwnd):
        r = RECT()
        if not self.u.GetWindowRect(hwnd, C.byref(r)):
            return None
        return (r.left, r.top, r.right, r.bottom)

    def frame_bounds(self, hwnd):
        r = RECT()
        if self.d.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, C.byref(r), C.sizeof(r)) != 0:
            return None
        return (r.left, r.top, r.right, r.bottom)

    def monitor_of(self, hwnd):
        monitor = self.u.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        info = MONITORINFO()
        info.cbSize = C.sizeof(MONITORINFO)
        if not monitor or not self.u.GetMonitorInfoW(monitor, C.byref(info)):
            return None
        m, w = info.rcMonitor, info.rcWork
        return (m.left, m.top, m.right, m.bottom), (w.left, w.top, w.right, w.bottom)

    def foreground(self):
        return int(self.u.GetForegroundWindow() or 0)

    def show_async(self, hwnd, command):
        if command not in (SW_SHOWNOACTIVATE, SW_SHOWMINNOACTIVE):
            raise ValueError("only the non-activating show commands reach a snap target (VOC-D01)")
        return bool(self.u.ShowWindowAsync(hwnd, command))

    def set_pos_async(self, hwnd, insert_after, x, y, w, h, flags):
        if not int(flags) & SWP_ASYNCWINDOWPOS or not int(flags) & SWP_NOACTIVATE_:
            raise ValueError("SetWindowPos reaches a snap target only posted and non-activating (K4 9.6)")
        return bool(self.u.SetWindowPos(hwnd, insert_after, int(x), int(y), int(w), int(h), int(flags)))

    def _level(self, process):
        token = HANDLE()
        if not self.a.OpenProcessToken(process, TOKEN_QUERY, C.byref(token)):
            return None
        try:
            needed = DWORD(0)
            self.a.GetTokenInformation(token, TOKEN_INTEGRITY_LEVEL, None, 0, C.byref(needed))
            if not needed.value:
                return None
            buffer = C.create_string_buffer(needed.value)
            if not self.a.GetTokenInformation(token, TOKEN_INTEGRITY_LEVEL, buffer, needed, C.byref(needed)):
                return None
            label = C.cast(buffer, C.POINTER(TOKEN_MANDATORY_LABEL)).contents
            count = self.a.GetSidSubAuthorityCount(label.Label.Sid).contents.value
            return int(self.a.GetSidSubAuthority(label.Label.Sid, count - 1).contents.value)
        finally:
            self.k.CloseHandle(token)

    def integrity_above_ours(self, hwnd):
        """True when the window's process runs at a higher integrity level (UIPI refuses our posted
        moves); None when either query fails ("carry on", K4 9.5)."""
        pid = DWORD(0)
        self.u.GetWindowThreadProcessId(hwnd, C.byref(pid))
        if not pid.value:
            return None
        if self._own_level is None:
            self._own_level = self._level(self.k.GetCurrentProcess())
        process = self.k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not process:
            return None
        try:
            level = self._level(process)
        finally:
            self.k.CloseHandle(process)
        if level is None or self._own_level is None:
            return None
        return level > self._own_level


# ================================================================ Tk-side facade
class CarouselPresenter:
    """The Windows picker's presenter (the PickerOverlay protocol and the v7 additions, see the
    module docstring).

    Every method belongs to the Tk thread and only records into the Mailbox and posts; show()
    also waits (<= 150 ms) until the carousel thread has shown the host. If the carousel thread
    or its windows cannot be created, the presenter is ``disabled`` (``last_error`` says why)
    and show() raises OSError; construction itself never raises for that."""

    SHOW_TIMEOUT_SECONDS = SHOW_TIMEOUT_S
    START_TIMEOUT_SECONDS = START_TIMEOUT_S
    CLOSE_TIMEOUT_SECONDS = CLOSE_TIMEOUT_S

    def __init__(self, root, native, on_cancel, *, backend=None, capture=None, snap=None, labels=None,
                 clock=time.perf_counter, log=None, inline=False, gpu_chrome=None, environ=None):
        self.root = root
        self.native = native
        self.on_cancel = on_cancel      # the adapter maps a queued 'cancel' to it (take_events)
        self._log = log if isinstance(log, _Log) else _Log(log)
        self._clock = clock
        self._mail = Mailbox()
        self._status = _Status()
        self._stats = LoopStats()
        self._closed = False
        self._visible = False
        self._focused = False
        self._gen = 0
        self._items = ()
        self._background = "glass"
        self._rm = None
        self._toast_seq = 0
        self._exclusions = ()
        self._icons = {}
        self._labels = {}
        self._thread = None
        self._ready = threading.Event()
        self._inline = bool(inline)
        self._backend = backend
        self._capture = capture
        self._snapper = snap
        self._labeler = labels
        self._engine = None
        self._gpu = None
        try:
            if self._backend is None:
                self._backend = Win32CarouselBackend(log=self._log)
            if self._capture is None:
                self._capture = CaptureWorker(self._backend, log=self._log)
            prepare = getattr(self._backend, "prepare_worker_thread", None)
            if self._labeler is None:
                self._labeler = LabelWorker(post=self._backend.post, log=self._log, threaded=not self._inline,
                                            prepare=prepare)
            if self._snapper is None and not self._inline:
                try:
                    self._snapper = SnapWorker(Win32SnapNative(identity=getattr(native, "identity", None)),
                                               post=self._backend.post, log=self._log, prepare=prepare)
                except Exception as exc:
                    self._log.warn("snap", f"carousel: the snap worker is unavailable: {exc!r}")
                    self._snapper = None
            self._gpu = self._make_gpu(gpu_chrome)
            self._engine = CarouselEngine(backend=self._backend, mailbox=self._mail, status=self._status,
                                          capture=self._capture, clock=clock, log=self._log, snap=self._snapper,
                                          labels=self._labeler, stats=self._stats, gpu=self._gpu,
                                          chrome_mode=_env_chrome_mode(environ), thumb_lead=_env_thumb_lead(environ))
        except Exception as exc:
            self._disable(f"carousel unavailable: {exc!r}")
            return
        if self._inline:
            try:
                self._create()
            except Exception as exc:
                self._disable(f"carousel window creation failed: {exc!r}")
            return
        self._thread = threading.Thread(target=self._run, name="NanoD-carousel", daemon=True)
        self._thread.start()
        if not self._ready.wait(self.START_TIMEOUT_SECONDS):
            with self._mail.lock:
                self._mail.closed = True
            self._disable(f"carousel thread did not start within {self.START_TIMEOUT_SECONDS:g} s")

    def _make_gpu(self, gpu_chrome):
        """The GPU chrome (CAR 12.4): ``gpu_chrome`` = an object, a factory, False (none), or None for
        the one installed by the wiring point (``install_gpu_chrome``). Never raises: the CPU chrome
        is the fallback."""
        if gpu_chrome is False:
            return None
        chrome = gpu_chrome if gpu_chrome is not None else gpu_chrome_factory()
        if chrome is None:
            return None
        if hasattr(chrome, "sync") and hasattr(chrome, "begin"):
            return chrome
        try:
            return chrome(log=self._log.info)
        except Exception as exc:
            self._log.warn("gpu", f"carousel: the GPU chrome could not be created: {exc!r}")
            return None

    # ------------------------------------------------------------ properties
    @property
    def hwnd(self):
        return int(self._status.host_hwnd or 0)

    @property
    def chrome(self):
        """'gpu' or 'cpu': which chrome drew the last (or the open) picker, None before the first."""
        return self._status.chrome

    @property
    def rect(self):
        """(x, y, w, h) of the stage's card area in physical px, from the show() handshake until the
        teardown at the end of the exit, else None. The UI suppresses the floating knob while it
        is set (reason 'carousel', CAROUSEL.md section 11; K4 17.1)."""
        return self._status.rect

    @property
    def disabled(self):
        return bool(self._status.disabled)

    @property
    def last_error(self):
        return self._status.last_error

    @property
    def visible(self):
        return self._visible

    @property
    def background(self):
        return self._background

    @property
    def host_mode(self):
        return self._status.host_mode

    # ---------------------------------------------------------------- thread
    def _create(self):
        backend, engine = self._backend, self._engine
        self._status.awareness = backend.prepare_thread()
        hwnd = backend.create(engine.on_event, engine.on_input)
        self._status.host_hwnd = int(hwnd or 0)
        self._status.host_mode = backend.host_mode

    def _run(self):
        backend, engine = self._backend, self._engine
        try:
            created = False
            try:
                self._create()
                created = True
            except BaseException as exc:
                self._disable(f"carousel window creation failed: {exc!r}")
            finally:
                self._ready.set()
            if created:
                self._loop()
        except BaseException as exc:
            self._disable(f"carousel thread failed: {exc!r}", exc_info=True)
        finally:
            try:
                if not engine.stopped:
                    engine._stop()
            except BaseException:
                pass
            try:
                backend.destroy()
            except BaseException as exc:
                self._log.error(f"carousel cleanup failed: {exc!r}")
            engine.finish()
            with self._status.cond:
                self._status.cond.notify_all()

    def _iterate(self):
        """One loop turn: messages, then a step; (alive, wait)."""
        if not self._backend.pump():
            return False, None
        return True, self._engine.advance()

    def _loop(self):
        """K4 5.2: drain the queue; while something moves, compose for the predicted display time,
        present, then wait on the compositor clock (or the mailbox event); idle, block."""
        backend, engine = self._backend, self._engine
        while True:
            alive, wait = self._iterate()
            if not alive:
                return
            if engine.stopped:
                backend.pump()
                return
            if wait is not None and wait <= 0:
                engine.present()
                backend.pace()
            elif not backend.wait(wait):
                return

    def _step_inline(self, pace=True):
        """Test hook (inline mode): one loop turn on the calling thread."""
        alive, wait = self._iterate()
        if alive and wait is not None and wait <= 0:
            self._engine.present()
            if pace:
                self._backend.pace()
        if self._snapper is not None and hasattr(self._snapper, "run_inline"):
            self._snapper.run_inline()
        return alive, wait

    def _disable(self, reason, exc_info=False):
        status = self._status
        status.disabled = True
        status.last_error = reason
        self._log.error(reason, exc_info=exc_info)
        with status.cond:
            status.cond.notify_all()

    def _post(self, code):
        flag = POST_FLAGS.get(code)
        try:
            ok = bool(self._backend.post(code))
        except Exception:
            ok = False
        if not ok:
            if flag:
                with self._mail.lock:
                    self._mail.posted[flag] = False
            self._status.post_failures += 1
            self._log.warn("post", f"carousel: PostMessageW(0x{code:04X}) failed")
        return ok

    def _request(self, code, write):
        """Record under the lock, then post unless one of this kind is still queued."""
        flag = POST_FLAGS[code]
        with self._mail.lock:
            if self._mail.closed:
                return False
            write(self._mail)
            post = not self._mail.posted[flag]
            self._mail.posted[flag] = True
        return self._post(code) if post else True

    def _event_now(self, kind, payload):
        """An answer produced on the Tk side (a request the carousel thread will never see)."""
        self._mail.push_event(kind, payload)

    # ------------------------------------------------------------- protocol
    def show(self, snapshot):
        """Open on ``snapshot`` (items, index, origin); returns once the host is visible and
        activatable (<= 150 ms), else raises OSError."""
        if self._closed:
            raise RuntimeError("The window picker is closed.")
        if self._status.disabled:
            raise OSError(f"The window picker is unavailable: {self._status.last_error}")
        items = list((snapshot or {}).get("items") or [])
        infos = tuple(ItemInfo(str(item.get("id")), int(item.get("hwnd") or 0), bool(item.get("minimized")),
                               bool(item.get("available", True)), str(item.get("app") or ""),
                               str(item.get("title") or ""), int(item.get("pid") or 0),
                               str(item.get("class_name") or ""), int(item.get("exstyle") or 0)) for item in items)
        index = max(0, min(int((snapshot or {}).get("index", 0) or 0), max(0, len(items) - 1)))
        origin = int(((snapshot or {}).get("origin") or {}).get("hwnd") or 0)
        self._gen += 1
        gen = self._gen
        self._items = items          # the adapter's list: highlight() re-reads its availability
        self._focused = False
        background = self._background
        exclusions = self._exclusions
        rm = self._rm

        def write(mail):
            mail.open_req = OpenRequest(gen, infos, index, origin, background, exclusions, rm)
            mail.select = None
            mail.dismiss = None
        self._request(WM_APP_OPEN, write)
        if not self._wait_open(gen):
            with self._mail.lock:
                self._mail.dismissed_gen = max(self._mail.dismissed_gen, gen)
            self._request(WM_APP_DISMISS, lambda mail: setattr(mail, "dismiss", Dismiss(gen, "hide", None)))
            reason = self._status.last_error if self._status.open_failed_gen >= gen else None
            raise OSError(f"The window picker did not open{': ' + reason if reason else ' in time'}.")
        self._visible = True

    def _wait_open(self, gen):
        status = self._status

        def done():
            return status.opened_gen >= gen or status.open_failed_gen >= gen or status.disabled

        if self._inline:
            for _ in range(8):
                if done():
                    break
                self._step_inline()
        else:
            with status.cond:
                status.cond.wait_for(done, self.SHOW_TIMEOUT_SECONDS)
        return status.opened_gen >= gen and status.open_failed_gen < gen

    def focus_local(self):
        """Native focus succeeded (the adapter's contract). Nothing to draw here: icons and
        labels are the carousel thread's work, never in the focus path."""
        if self._closed or not self._visible:
            return
        self._focused = True

    def highlight(self, index, bump=0):
        """Post the new target (and the items' availability) and an end bump (``bump`` = the
        direction of a turn past an end: K3's ``lim``); never redraws on the Tk thread."""
        if self._closed or not self._visible:
            return
        count = len(self._items)
        index = max(0, min(int(index), max(0, count - 1)))
        available = tuple(bool(item.get("available", True)) for item in self._items)
        gen = self._gen
        bump = 1 if (bump or 0) > 0 else -1 if (bump or 0) < 0 else 0
        self._request(WM_APP_SELECT, lambda mail: setattr(mail, "select", SelectRequest(gen, index, available, bump)))

    def set_icons(self, icons):
        """item id -> PIL image (a 128 px master, or a 32 px icon with its hi-res copy attached)
        or None (letter tile). Stored and posted only: all resizing is the carousel thread's."""
        if self._closed:
            return
        self._icons = dict(icons or {})
        self._post_data()

    def set_labels(self, labels):
        """item id -> Label(app, title, desc) for the centre card."""
        if self._closed:
            return
        self._labels = dict(labels or {})
        self._post_data()

    def _post_data(self):
        icons, labels = self._icons, self._labels

        def write(mail):
            mail.icons, mail.labels = icons, labels
            mail.data_seq += 1
        self._request(WM_APP_DATA, write)

    def set_background(self, background):
        """'glass' (Frosted, the default) or 'none' (No background); from the next open."""
        self._background = "none" if background == "none" else "glass"

    def set_chrome_mode(self, mode):
        """'auto' (the GPU chrome when installed and able, CAR 12.4) or 'cpu' (the step-1 chrome
        always); from the next open. Returns the mode in force."""
        mode = mode if mode in CHROME_MODES else "auto"
        if self._engine is not None:
            self._engine.chrome_mode = mode
        return mode

    def note_touch(self):
        """A knob touch (K4 4.2, AR-19): warm the GPU chrome's device while nothing is open, so the
        next open has no device creation on its path. Posted; never blocks, and the carousel thread
        makes no slow part of the device itself (a worker does; WP7c-R6), so a show() right after a
        touch answers its handshake at once."""
        if self._closed or self._status.disabled or self._gpu is None:
            return False
        return self._post(WM_APP_WARM)

    def set_reduced_motion(self, on):
        """The effective Motion setting (K4 16; K3 14.3), latched at the next open and used for
        toasts at their show. None: the Windows setting, read on the carousel thread."""
        self._rm = None if on is None else bool(on)

    def set_capture_exclusions(self, hwnds):
        """Other top-level windows of THIS process that must never be blurred into the frost (the
        floating knob): from the next open they get WDA_EXCLUDEFROMCAPTURE with the picker's
        layers while the frost capture runs, and WDA_NONE right after it. Tk thread."""
        out = []
        for hwnd in hwnds or ():
            try:
                value = int(hwnd or 0)
            except (TypeError, ValueError):
                continue
            if value and value not in out:
                out.append(value)
        self._exclusions = tuple(out)

    def take_events(self):
        """Everything queued for the Tk side, oldest first: host input ('switch', index),
        ('cancel', None), ('turn', +1 | -1); ('snap_result', (side, outcome)),
        ('complete_result', (job id, completed)), ('closed', 'display') and ('system', 'sleep')."""
        with self._mail.lock:
            events = list(self._mail.events)
            self._mail.events.clear()
        return events

    # ------------------------------------------------------------- snap (K4 9.5-9.7)
    def snap(self, request):
        """``windows_snap`` (K3 9.9): ``{t0, index, side, target_rect, place_at_ms, item}``. The
        results come back as ('snap_result', (side, outcome)) events. Never blocks."""
        request = dict(request or {})
        side = request.get("side")
        index = request.get("index")
        if (self._closed or self._status.disabled or not self._visible or side not in SIDES
                or not isinstance(index, int)):
            self._event_now("snap_result", (side if side in SIDES else None, "move_rejected"))
            return False
        gen = self._gen
        req = SnapRequest(gen, None, int(index), side, request.get("target_rect"), request.get("t0"),
                          request.get("item") if isinstance(request.get("item"), dict) else None)
        if not self._request(WM_APP_SNAP, lambda mail: mail.snaps.append(req)):
            self._event_now("snap_result", (side, "move_rejected"))
            return False
        return True

    def complete_one_side(self, origin, side, rect=None):
        """U12 (K4 9.7; VOC 8.4 complete_one_side): move ``origin`` (an identity dict: hwnd, pid,
        id, class_name, exstyle) to ``side``'s half without activating it, on NanoD-snap, within
        600 ms. Returns the job id; the answer is ('complete_result', (job id, completed))."""
        now = self._clock()
        rect = rect if rect is not None else self.half_rect(side)
        job = SnapJob("complete", side=side, item=origin, target=rect, t0=now, deadline=now + ONE_SIDE_DEADLINE_S)
        if (self._closed or self._status.disabled or side not in SIDES or job.target is None
                or not isinstance(origin, dict) or not origin.get("hwnd")):
            self._event_now("complete_result", (job.id, False))
            return job.id
        if not self._request(WM_APP_WORK, lambda mail: mail.work.append(WorkRequest("complete", job))):
            self._event_now("complete_result", (job.id, False))
        return job.id

    def raise_window(self, hwnd):
        """The pair close's posted raise (K4 9.7): SetWindowPos(HWND_TOP, 0x4013) on NanoD-snap,
        fire and forget."""
        if self._closed or self._status.disabled or not hwnd:
            return False
        job = SnapJob("raise", hwnd=int(hwnd))
        return self._request(WM_APP_WORK, lambda mail: mail.work.append(WorkRequest("raise", job)))

    def half_rect(self, side):
        """The picker monitor's rcWork half (l, t, r, b) for ``side`` (K3's ``target_rect``), or
        None before the first open."""
        layout = self._status.layout
        if layout is None or side not in SIDES:
            return None
        return layout.half(side)

    # ------------------------------------------------------------- exits
    def play_switch_exit(self, toast_text=""):
        """After the adapter activated the target: the root fades 280 ms OUT and the cards group
        220 ms EASE; thumbnails go at the end. No grow (S5-6) and no toast of the picker's own:
        K3 raises ``toast.switch`` through the toast service. Idempotent per open."""
        self._exit("switch")

    def play_cancel_exit(self):
        """After the adapter restored the origin: the same exit; no toast (R:152)."""
        self._exit("cancel")

    def play_pair_exit(self):
        """After the pair close's focus: the same exit (``toast.snap.pair`` is K3's)."""
        self._exit("pair")

    def _exit(self, mode):
        if self._closed or not self._gen:
            return
        gen = self._gen
        self._visible = False
        self._focused = False
        self._request(WM_APP_DISMISS, lambda mail: setattr(mail, "dismiss", Dismiss(gen, mode, None)))

    def hide(self):
        """Idempotent; never raises. Instant (thumbnails go before the windows do, on the carousel
        thread). A running (or just requested) exit animation is not cut short."""
        if self._closed:
            return
        self._visible = False
        self._focused = False
        if not self._gen:
            return
        gen = self._gen

        def write(mail):
            pending = mail.dismiss
            if pending is None or pending.gen != gen or pending.mode == "hide":
                mail.dismiss = Dismiss(gen, "hide", None)
        self._request(WM_APP_DISMISS, write)

    # ------------------------------------------------------------- the toast service (K4 10)
    def toast(self, text, exit=False):
        """K4 10.3: ``toast(text, exit=False)`` from the Tk thread. The Tk side (the adapter) has
        already applied the overlay-registry rule; here the carousel thread drops it over the
        open picker (an exit toast asked for during the picker's own exit waits for its end) and
        while SHQueryUserNotificationState is 3 or 4, replaces a showing toast, and places a new
        one on the stage of the foreground window's monitor, top 588."""
        if self._closed or self._status.disabled:
            return False
        text = " ".join(str(text or "").split())
        if not text:
            return False
        self._toast_seq += 1
        req = ToastRequest(self._toast_seq, text, bool(exit), bool(self._rm), self._clock())
        return self._request(WM_APP_TOAST, lambda mail: setattr(mail, "toast", req))

    def end_toast(self):
        """Opening an overlay ends any visible toast at once (K4 10.4)."""
        if self._closed or self._status.disabled:
            return False

        def write(mail):
            mail.toast = None
            mail.toast_end = True
        return self._request(WM_APP_TOAST, write)

    def close(self):
        """Release at once and destroy everything on the carousel thread; join the threads within
        1 s. Idempotent; show() raises afterwards."""
        if self._closed:
            return True
        self._closed = True
        self._visible = False
        with self._mail.lock:
            self._mail.closed = True
        self._status.closed = True
        joined = True
        started = time.monotonic()
        if self._inline:
            try:
                if self._engine is not None and not self._engine.stopped:
                    self._engine._stop()
                self._backend.destroy()
                self._engine.finish()
            except Exception as exc:
                self._log.warn("close", f"carousel: close failed: {exc!r}")
        elif self._thread is not None and self._thread.is_alive() and self._thread is not threading.current_thread():
            posted = False
            try:
                posted = bool(self._backend.post(WM_APP_STOP)) or bool(self._backend.post_quit())
            except Exception:
                pass
            self._thread.join(self.CLOSE_TIMEOUT_SECONDS)
            if self._thread.is_alive():
                joined = False
                self._log.warn("close", f"carousel thread did not stop within 1 s (stop posted: {posted})")
        for worker in (self._capture, self._labeler, self._snapper):
            if worker is None:
                continue
            remaining = max(0.05, self.CLOSE_TIMEOUT_SECONDS - (time.monotonic() - started))
            try:
                joined = bool(worker.close(remaining)) and joined
            except Exception:
                pass
        self._icons = self._labels = {}
        return joined

    # ---------------------------------------------------------------- diagnostics
    def metrics(self):
        """Diagnostics (plain JSON types; no titles). ``frames``: FrameStats per surface
        (``picker``, ``toast``; K4 6.2); ``pacer``: the loop's cadence and wait counts."""
        status = self._status
        gdi = user = None
        try:
            gdi, user = self._backend.gui_resources()
        except Exception:
            pass
        pacer = getattr(self._backend, "pacer", None)
        pacing = None
        if pacer is not None and hasattr(pacer, "counts"):
            pacing = {"cadence": pacer.cadence, "cadence_switches": pacer.switches, "late_wakes": pacer.late_wakes,
                      "period_ms": round(pacer.period * 1000.0, 4), "waits": dict(pacer.counts),
                      "oneoff_frames": getattr(pacer, "oneoff_frames", 0),         # P1: left out of P2 / P5
                      "runs": getattr(pacer, "runs", 0)}                           # P1: loop runs (after idle)
        return {
            "disabled": status.disabled, "last_error": status.last_error, "host_mode": status.host_mode,
            "rect": list(status.rect) if status.rect else None, "frames_presented": status.frames,
            "compose_ms": status.compose_ms, "compose_ms_max": status.compose_ms_max,
            "registrations": status.registrations, "register_failures": status.register_failures,
            "glass_fallbacks": status.glass_fallbacks, "capture_ms": status.capture_ms, "glass_ms": status.glass_ms,
            "glass_upload_ms": status.glass_upload_ms, "glass_upload_ms_max": status.glass_upload_ms_max,
            "toasts": status.toasts, "toasts_dropped": status.toasts_dropped, "post_failures": status.post_failures,
            "snaps": status.snaps, "snap_backstops": status.snap_backstops, "label_swaps": status.label_swaps,
            "label_late": status.label_late, "dpi_awareness": status.awareness, "gdi_objects": gdi,
            "user_objects": user, "frames": self._stats.metrics(), "pacer": pacing,
            "chrome": status.chrome, "gpu_sessions": status.gpu_sessions, "gpu_fallbacks": status.gpu_fallbacks,
            "gpu": self._gpu_metrics(),
        }

    def _gpu_metrics(self):
        gpu = getattr(self, "_gpu", None)
        if gpu is None:
            return None
        try:
            return dict(gpu.metrics())
        except Exception:
            return None


# ==================================================================== self test
def self_test(hidden_windows=False, k=2.0):
    """A smoke check for the frozen build (CAR section 10), JSON-friendly and title-free: the frost
    pipeline on a synthetic stage-sized image, a label with fallback fonts (Cyrillic, Greek,
    CJK, Hangul, emoji) and its glyph coverage, the letter tile, and with ``hidden_windows`` the
    carousel's real windows created hidden on their own thread, one thumbnail registered from one
    of its own windows, a chrome frame composed and presented at alpha 0, everything destroyed and
    the GDI/USER counts back to baseline. Nothing is ever shown and the screen is never read."""
    report = {"ok": False}
    try:
        started = time.perf_counter()
        stage = (round(R.STAGE_W * k), round(R.STAGE_H * k))      # the frost covers the monitor
        source = R.Image.linear_gradient("L").resize(stage).convert("RGB")
        frost = R.frost_canvas(source, k)
        report["glass_ms"] = round((time.perf_counter() - started) * 1000, 1)
        report["glass_ok"] = frost.size == stage and frost.image.getextrema()[3] == (255, 255)
        engine = R.TextEngine()
        title = ("Title Встреча Λίστα "
                 "会议 회의 \U0001F680")
        started = time.perf_counter()
        label = R.render_label(R.SimpleLabel("App", title, "Description"), None, k, "glass", engine)
        report["label_ms"] = round((time.perf_counter() - started) * 1000, 1)
        glyphs = engine.glyphs(title, 600)
        report["label_fonts"] = sorted({spec.name for _, spec in glyphs if spec is not None})
        report["label_ok"] = label.sprite is not None and all(
            spec is not None and ord(ch) in R.coverage(spec.path, spec.index) for ch, spec in glyphs)
        tile = R.letter_tile("Bambu Studio", round(30 * k), engine)
        report["tile_ok"] = tile.size == (round(30 * k),) * 2 and R.white_contrast(tile.getpixel((1, 1))[:3]) >= 3.0
        report["ok"] = bool(report["glass_ok"] and report["label_ok"] and report["tile_ok"])
        if hidden_windows:
            report["windows"] = _hidden_window_check(k)
            report["ok"] = report["ok"] and bool(report["windows"].get("ok"))
    except Exception as exc:
        report["error"] = repr(exc)
    return report


def _hidden_window_check(k):
    """The live half of self_test on its own thread (it owns the windows it destroys)."""
    outcome = {}

    def body():
        api = CarouselApi()
        process = api.k.GetCurrentProcess()

        def counts():
            return (int(api.u.GetGuiResources(process, GR_GDIOBJECTS)),
                    int(api.u.GetGuiResources(process, GR_USEROBJECTS)))

        baseline = counts()
        backend = Win32CarouselBackend(api=api)
        try:
            backend.prepare_thread()
            backend.create(lambda *_: None, lambda *_: None)
            outcome["host_mode"] = backend.host_mode
            windows = dict(backend.windows)
            handle = backend.register(windows["dim"])
            outcome["thumbnail"] = bool(handle)
            if handle:
                backend.update_thumbnail(handle, (0, 0, 8, 8), (0, 0, 1, 1), 0, False)
                backend.unregister(handle)
            layout = R.layout_for((0, 0, round(R.STAGE_W * k), round(R.STAGE_H * k)))
            canvas = backend.chrome_alloc(layout.band)
            x, s, op, shade = R.table_state(0)
            card = R.ChromeCard(R.card_rect(layout, x, s), s, op, shade, 1.0)
            R.compose_chrome(canvas, R.ChromeScene(layout.k, layout.band_origin, "glass", [card]),
                             R.ShadowCache(layout.k))
            outcome["ulw"] = backend._ulw("chrome", 0)          # constant alpha 0
            outcome["hidden"] = not any(api.u.IsWindowVisible(hwnd) for hwnd in windows.values())
            backend.chrome_free()
        finally:
            backend.destroy_windows()
            backend.pump()
            backend.unregister_classes()
        deadline = time.monotonic() + 1.0
        after = counts()
        pause = threading.Event()
        while after != baseline and time.monotonic() < deadline:
            pause.wait(0.02)
            after = counts()
        outcome["baseline"] = after == baseline
        outcome["ok"] = bool(outcome.get("thumbnail") and outcome.get("ulw") and outcome.get("hidden")
                             and outcome["baseline"])

    def run():
        try:
            body()
        except Exception as exc:
            outcome["error"] = repr(exc)

    thread = threading.Thread(target=run, name="NanoD-carousel-selftest", daemon=True)
    thread.start()
    thread.join(10.0)
    if thread.is_alive():
        outcome["error"] = "the self-test thread did not finish"
    return outcome
