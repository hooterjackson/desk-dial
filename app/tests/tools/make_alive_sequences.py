"""Write harness/alive_sequences.json: the ALIVE.md 11.3 twin replay (C++ vs Python engine).

Every case is a timeline of engine calls (ALIVE.md section 4 API) at integer-ms times:
``reset``/``claim``/``release``/``reveal`` (``startReveal``; unused since [M29]), ``detent`` (with
realistic HMI timing, so the spin velocity and the tick length are exercised), ``limit``,
``press``, ``clock`` and ``progress``, plus one ``render`` per step with a wire-valid v4 frame
(or none), the 6.3 local position and the section 9 drive / dither. Each case runs through ONE
``control_center.alive_lights.AliveLights`` (constructed = ``reset(0)``, like the C++ runner's
``CCAlive::reset(0)``); each step records what the Python engine produced:

* ``e``: the tone-mapped design-space e, 60 ring segments then 4 buttons, [r, g, b] each, as
  192 integers in units of 1/``eScale`` (1e-5);
* ``bytes``: on a subset of steps, the section 9 output with dither OFF (0xRRGGBB, 60 ring
  segments then 4 button slots) from ``reference_output`` below: an independent float64
  reference (exact sRGB EOTF, drive, the [D17] power limit over 60 + 8 LEDs, round half up and,
  [user 2026-09-26] the F-T brightness floor on the LEDs whose target is lit), kept in this tool
  only (section 9 is C++ only in the product);
* ``lit`` (with ``bytes``): the F-T mask of the render, the engine's ``lit_masks()`` as 16 hex
  digits, bit i = ring segment i (0..59), bit 60 + j = button slot j; the C++ runner compares its
  own ``cc_alive_lit(targets())`` with it;
* ``asleep`` (effectiveAsleep), ``cursor``, ``flash`` (0 none / 1 ok / 2 err) and ``fx``: the
  effect queue after the render, one row per effect ``[type, t0, kill|null, params...]`` with
  the parameters its recipe reads (``FX_PARAMS``);
* ``animating``: only where no float32 / float64 knife edge can decide it (the damping residue
  and the tint are more than ``ANIMATING_MARGIN`` away from the 1/1024 threshold).

Every frame is the host's wire frame: ``wire()`` passes the v4 part through ``device._frame``
(the companion's validator: v4 defaults, stripped false/empty optional fields) before the Python
engine renders it, so both engines see what the knob would receive.

harness/alive_tests.cpp (run by alive_tests.py, which regenerates this file first, as
light_tests.py does) parses every frame with the firmware's own ``cc_parse_frame``, replays each
case through one ``CCAlive`` and compares ``e`` within ``tolerance`` (2e-3), the bytes within
``byteTolerance`` (1) and the other fields exactly. The format is documented there.

Frames carry the ALIVE.md section 3 frame content: ``playing`` (Home only) and
``feedback.skip`` (ok only). The latched fields are ops (``clock``, ``progress``); ``drive``
(default 150) and ``dither`` (default false: the knob's default since the 2026-09-26 user ruling,
ALIVE.md 12.7) are per step. Frames are stored once in
``frames`` and referenced by index; empty ``ops``, a null ``frame``/``local`` and default
drive/dither are omitted.

[r2] Revision 2 (ALIVE.md 11.4). Frames with v5 content (the layouts seek / explorer / upnext,
the lap ring, ``ring.now`` / ``card``, ``buttons[j].lit`` / ``color``, the v5 icons,
``feedback.moment`` / ``side`` / ``color``) are the v7 host's: ``wire()`` passes them through
``device._frame`` with a presentation-5 + alive knob (``CAPS_V5``); every other frame keeps the
v6 host's v4 wire (``CAPS_V4``), so both compatibility rows are replayed. A ``Raw`` frame is fed
unvalidated (the Up next card with its ``unavailable`` bit set, 11.4): the Python engine renders
the dict, the C++ parser strips the bit (K1 P5-R24), and the engine ignores it either way; such
steps carry ``"raw": true``. New ops: ``rm`` (``set_reduced_motion``), ``tuning``
(``set_tuning``: ``pink``, ``volFull``), ``knob`` (one pass of the HMI's local-input sampler,
``CCAliveKnob`` / ``al.AliveKnob``: ``id``, ``pos``, ``pushing``, ``max``; its detent and limit go
to the engine, its limits are recorded in ``expect.lim``) and ``knobReset``. The ``fx`` rows of the
new effects: ``bloom`` at + colour, ``half`` at + side + colour, ``scatter`` at + seed (compared
within 1e-5, 11.4). The scatter PRNG's seeds are refused within ``SCATTER_MARGIN`` of an addG
bound (p +- 2.4 on an integer), the knife edge between float32 and float64.

[r2.2] ALIVE.md 11.4 adds two cases: ``liked-heart-rest`` (M32: the liked Button 3 at PINK 0.30 next to
a ``dim`` 0.14 and an ``off`` 0.30, then at rest WARM 0.26 like ``off``, [user 2026-09-26] 12.8) and ``seek-pending-two-jumps``
(M33: one Seek span of ``activity:"pending"`` across a jump, a turn that moves the frozen target and
the follow-up jump, with no idle frame in between, so the Working comet never stops). A sequence built
with ``pending=True`` records ``expect.pending`` (the 6.1 pending flag, the comet) at every step; the
C++ runner compares it with ``CCAlive::targets().pending``.

Native handover (8.1) is firmware integration, not engine state: while the native path owns
the LEDs the engine is not rendered (a gap in the timeline). [M29] It lasts until the next
claim (revision 1's 5000 ms return and its ``reveal`` op are withdrawn).

Knife edges. The tick length rounds a float: ``round(clamp((vel - 4)/14) * 7 + bias)`` [D19].
Integer-ms detent gaps make exact .5 ties routine (the second detent 90 ms after a rest:
vel = 450/90 = 5); both ports add the same 1e-4 bias (``al.TICK_TIE_BIAS``, firmware
``tickTieBias``), so exact ties round up in both despite float32 vs float64 error, and the
"tick-direction-velocity-edges" case replays such ties. What is left is a rounding edge 1e-4
below each tie, which only non-integer rational velocities can reach: the generator records the
pre-round value of every tick and refuses a timeline within ``TICK_TIE_MARGIN`` of that edge.

Usage (alive_tests.py calls ``build()``/``dumps()`` itself):
    .venv\\Scripts\\python.exe tests\\tools\\make_alive_sequences.py [--check]
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _path in (str(ROOT), str(HERE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from control_center import alive_lights as al  # noqa: E402
from control_center import device, presentation as P  # noqa: E402

OUTPUT = ROOT.parent / "harness" / "alive_sequences.json"
VERSION = 2
TOLERANCE = 0.002
BYTE_TOLERANCE = 1
E_SCALE = 100000
U32 = 2 ** 32
CAPS_V4 = {"presentation": 4, "glyphs": "latin-ext-a"}
CAPS_V5 = {"presentation": 5, "glyphs": "latin-ext-a", "alive": {"version": 1, "fps": 60, "drive": 150}}
V5_LAYOUTS = ("seek", "explorer", "upnext")
V5_ICONS = ("expand", "clock", "playlists", "playnext", "seek", "shuffle", "heart", "snapleft", "snapright")
FLASH_CODE = {None: 0, "ok": 1, "err": 2}
TICK_TIE_MARGIN = 5e-5          # |frac(x) - 0.5| of the tick length's biased pre-round value x
ANIMATING_MARGIN = 5e-5         # |residue - 1/1024| and |tint - 1/1024| where animating is recorded
SCATTER_MARGIN = 1e-4           # |frac(p +- 2.4)| of every scatter spark position (addG's floor/ceil)

# Section 9 reference (dither off, the default since the 2026-09-26 user ruling). Kept here only:
# the product's output stage is C++.
DEFAULT_DRIVE = 150
POWER_BUDGET = 16920.0          # [D17][R5] B = 68 * (255 + 132 + 36) * 150 / 255 = 16920 exactly
BUTTON_LEDS_PER_SLOT = 2


def eotf(e):
    """Section 9.1 [D3]: the sRGB EOTF, e clamped to 0..1 (float64, exact formula)."""
    e = 0.0 if e < 0 else 1.0 if e > 1 else e
    return e / 12.92 if e <= 0.04045 else ((e + 0.055) / 1.055) ** 2.4


def reference_output(ring_e, button_e, drive=DEFAULT_DRIVE, ring_lit=(), button_lit=()):
    """Section 9 with dither off: (60 ring 0xRRGGBB, 4 button 0xRRGGBB).

    [user 2026-09-26] Rule F-T (9 step 4, channel rule amended the same day, 12.7): an LED flagged
    in ``ring_lit`` / ``button_lit`` (its target is lit; the engine's ``lit_masks()``) that plain
    rounding leaves dark while its largest channel value top > 0 shows one count on every channel
    equal to top (the dominant one; a tie lights each tied channel), the rest 0. Unflagged LEDs (and
    missing flags) keep plain rounding."""
    ring = [[eotf(x) * drive for x in c] for c in ring_e]
    buttons = [[eotf(x) * drive for x in c] for c in button_e]
    total = sum(sum(c) for c in ring) + BUTTON_LEDS_PER_SLOT * sum(sum(c) for c in buttons)
    scale = POWER_BUDGET / total if total > POWER_BUDGET else 1.0

    def pixel(c, lit):
        v = [x * scale for x in c]
        q = [min(255, max(0, math.floor(x + 0.5))) for x in v]
        top = max(v)
        if lit and q == [0, 0, 0] and top > 0:
            q = [1 if x == top else 0 for x in v]
        return (q[0] << 16) | (q[1] << 8) | q[2]

    def flag(flags, k):
        return k < len(flags) and bool(flags[k])
    return ([pixel(c, flag(ring_lit, i)) for i, c in enumerate(ring)],
            [pixel(c, flag(button_lit, j)) for j, c in enumerate(buttons)])


def lit_hex(ring_lit, button_lit):
    """The F-T mask as 16 hex digits: bit i = ring segment i, bit 60 + j = button slot j."""
    bits = sum(1 << i for i, lit in enumerate(ring_lit) if lit)
    bits |= sum(1 << (60 + j) for j, lit in enumerate(button_lit) if lit)
    return f"{bits:016x}"


# ----------------------------------------------------------------- frames
def _buttons(*spec):
    return [{"label": label, "enabled": enabled, "icon": icon} for label, enabled, icon in spec]


HOME_BUTTONS = _buttons(("Pause", True, "pause"), ("Browse", True, "list"), ("Win", True, "win"),
                        ("Tracks", True, "tracks"))
PAUSED_BUTTONS = _buttons(("Play", True, "play"), ("Browse", True, "list"), ("Win", True, "win"),
                          ("Tracks", True, "tracks"))
PLAY_DISABLED = _buttons(("Play", False, "play"), ("Browse", True, "list"), ("Win", True, "win"),
                         ("Tracks", False, "tracks"))
RECENT_BUTTONS = _buttons(("Back", True, "back"), ("Home", True, "home"), ("Win", True, "win"),
                          ("Play", True, "play"))
WINDOWS_BUTTONS = _buttons(("Cancel", True, "cancel"), ("Home", True, "home"), ("Win", True, "win"),
                           ("Switch", True, "switch"))
TRACKS_BUTTONS = _buttons(("Back", True, "back"), ("Home", True, "home"), ("Win", True, "win"),
                          ("Next", True, "next"))


def _feedback(spec):
    """(kind, seq) or (kind, seq, skip) -> the frame's feedback object; a dict is used as is (v5)."""
    if isinstance(spec, dict):
        return dict(spec)
    out = {"kind": spec[0], "seq": spec[1]}
    if len(spec) > 2:
        out["skip"] = spec[2]
    return out


def moment(seq, name, color=None, side=None):
    """[r2] an ok feedback carrying a moment (PRESENTATION_V5 6.1)."""
    out = {"kind": "ok", "seq": seq, "moment": name}
    if side is not None:
        out["side"] = side
    if color is not None:
        out["color"] = color
    return out


def _base(control_id, mode, layout, activity, led, buttons, ring, feedback=None, **extra):
    frame = {"id": control_id, "mode": mode, "target": "Den", "value": "", "detail": "", "status": "",
             "activity": activity, "layout": layout, "ledStyle": led, "buttons": buttons, "ring": ring}
    frame.update(extra)
    if feedback:
        frame["feedback"] = _feedback(feedback)
    return frame


def home(v, c=None, led="color", external=False, activity="idle", layout="volume", buttons=HOME_BUTTONS,
         playing=None, feedback=None, control_id=1):
    """Home family, level ring. ``playing`` (ALIVE.md 3) only when given."""
    extra = {"value": f"{v}%", "confirmedVolume": v if c is None else c}
    if layout == "volume":
        extra["restLayout"] = "nowPlaying"
    frame = _base(control_id, "VOLUME", layout, activity, led, buttons,
                  {"style": "level", "value": v, "index": 0, "count": 101, "external": external},
                  feedback, **extra)
    if playing is not None:
        frame["playing"] = playing
    return frame


def notice(v, c, led="color", playing=None, feedback=None, external=False):
    """The Home Sonos-off notice [D15]: activity offline, the confirmed endpoint only."""
    return home(v, c, led=led, activity="offline", layout="notice", playing=playing, feedback=feedback,
                external=external)


def idle_home(led="color", playing=None):
    """Home idle layout (nothing playing): style off, dark ring, paused Play."""
    frame = _base(1, "VOLUME", "idle", "idle", led, PAUSED_BUTTONS,
                  {"style": "off", "value": 0, "index": 0, "count": 0})
    if playing is not None:
        frame["playing"] = playing
    return frame


def accent(j):
    """Distinct non-white accents; every 7th entry has none (0 -> white); entry 5 is grey
    (sat() falls back to WARM)."""
    if j % 7 == 3:
        return 0
    if j == 5:
        return 0x7A7A86
    return (0x30 + (j * 37) % 200) << 16 | (0x20 + (j * 53) % 210) << 8 | (0x40 + (j * 29) % 190)


def recent_closed(j):
    return j % 5 == 2


def windows_closed(j):
    return j % 4 == 1


def lst(count, index, led="color", windows=False, activity="idle", more=-1, first="auto", colors="auto",
        feedback=None, control_id=1):
    """Recent (default) or Windows list; colours/mask relative to the transmitted first.
    ``first=None`` omits it: the window derives, and relative data is sent only when it is 0."""
    closed = windows_closed if windows else recent_closed
    start = P.window_first(index, count) if first in ("auto", None) else first
    width = min(P.RING_WINDOW, count - start)
    relative = first is not None or start == 0
    ring = {"style": "selection", "value": 0, "index": index, "count": count}
    if first is not None:
        ring["first"] = start
    mask = sum(1 << k for k in range(width) if closed(start + k) and start + k != more)
    if mask and relative:
        ring["unavailable"] = mask
    if more >= 0:
        ring["moreIndex"] = more
    if colors == "auto" and led == "color" and relative:
        ring["colors"] = [accent(start + k) for k in range(width)]
    elif isinstance(colors, list):
        ring["colors"] = colors
    return _base(control_id, "WINDOWS" if windows else "RECENTLY ADDED", "windows" if windows else "recent",
                 activity, led, WINDOWS_BUTTONS if windows else RECENT_BUTTONS, ring, feedback,
                 title=f"Entry {index + 1}")


def tracks(index, no_prev=False, activity="idle", feedback=None, control_id=1):
    ring = {"style": "transport", "value": 0, "index": index, "count": 3}
    if no_prev:
        ring["unavailable"] = 1
    buttons = [dict(b) for b in TRACKS_BUTTONS]
    buttons[3] = {"label": ("Prev", "Skip", "Next")[index], "enabled": index != 1 and not (index == 0 and no_prev),
                  "icon": ("prev", "next", "next")[index]}
    return _base(control_id, "TRACKS", "tracks", activity, "color", buttons, ring, feedback)


_WIRE = {}


class Raw:
    """A frame fed to both engines unvalidated (11.4: the Up next card's unavailable bit)."""

    def __init__(self, frame):
        self.frame = frame


def has_v5(frame):
    """[r2] the frame carries v5 content (PRESENTATION_V5 3.1 gating): the v7 host's frame."""
    ring = frame.get("ring") or {}
    feedback = frame.get("feedback") or {}
    return (frame.get("layout") in V5_LAYOUTS or ring.get("style") == "lap" or "now" in ring or "card" in ring
            or any("lit" in b or b.get("icon") in V5_ICONS for b in frame.get("buttons") or ())
            or any(k in feedback for k in ("moment", "side", "color")))


def wire(frame):
    """The frame as the host sends it. A v5 frame: ``device._frame`` for a presentation-5 knob with
    ``alive`` (v5 fields, ``playing``, ``feedback.skip``, slimming). Any other: ``device._frame`` on the
    v4 part for the v6 host (v4 defaults), plus the ALIVE.md section 3 content (``playing``,
    ``feedback.skip``) as a v6 host with ``alive`` sends it (10.2)."""
    if isinstance(frame, Raw):
        return frame.frame
    key = json.dumps(frame, sort_keys=True)
    out = _WIRE.get(key)
    if out is None and has_v5(frame):
        out = _WIRE[key] = device._frame(frame, CAPS_V5)
    if out is None:
        plain = {k: v for k, v in frame.items() if k != "playing"}
        feedback = plain.get("feedback")
        skip = feedback.get("skip") if isinstance(feedback, dict) else None
        if skip is not None:
            plain["feedback"] = {k: v for k, v in feedback.items() if k != "skip"}
        out = device._frame(plain, CAPS_V4)
        if skip is not None:
            out["feedback"] = {**out["feedback"], "skip": skip}
        if "playing" in frame:
            out["playing"] = frame["playing"]
        _WIRE[key] = out
    return out


# ------------------------------------------------------------- recording
class _Probe(al.AliveLights):
    """AliveLights recording the pre-round tick length (the only js_round inside _events)."""

    def __init__(self, now=0):
        self.tick_values = []
        super().__init__(now)

    def _events(self, *args, **kwargs):
        original = al.js_round

        def spy(x):
            self.tick_values.append(x)
            return original(x)
        al.js_round = spy
        try:
            return super()._events(*args, **kwargs)
        finally:
            al.js_round = original


def _apply(seq, op, now, lims):
    lights = seq.lights
    t = op.get("t", now)
    kind = op["op"]
    if kind == "reset":
        lights.reset(t)
    elif kind == "claim":
        lights.claim(t)
    elif kind == "release":
        lights.release(t)
    elif kind == "reveal":
        lights.start_reveal(t)
    elif kind == "detent":
        lights.detent(t, op["delta"])
    elif kind == "limit":
        lights.limit(t, op["dir"])
    elif kind == "press":
        lights.press(t, op["slot"])
    elif kind == "clock":
        lights.set_clock(t, op["minute"])
    elif kind == "progress":
        lights.set_progress(t, op["pos"], op["dur"])
    elif kind == "rm":
        lights.set_reduced_motion(t, op["on"])
    elif kind == "tuning":
        lights.set_tuning(t, op["pink"], op["volFull"])
    elif kind == "knob":                                    # one HMI pass of the sampler [Q1]
        delta, limit = seq.knob.sample(t, op["id"], op["pos"], op["pushing"], op["max"])
        if delta:
            lights.detent(t, delta)
        if limit:
            lights.limit(t, limit)
            lims.append(limit)
    elif kind == "knobReset":
        seq.knob.reset()
    else:
        raise ValueError(f"unknown op {kind}")


FX_PARAMS = {"boot": ("at", "home"), "down": ("at",), "wake": ("at",), "tick": ("at", "dir", "len"),
             "bound": ("at", "dir", "c"), "bloom": ("at", "c"), "fail": ("at",), "sweep": ("at", "dir"),
             "fill": ("at", "n"), "drain": ("at", "n"), "shimmer": ("frm", "to"), "wash": ("at", "c"),
             "reveal": ("at",), "press": ("n",), "half": ("at", "side", "c"), "scatter": ("at", "seed")}


def fx_row(e):
    row = [e.type, e.t0, e.kill]
    for name in FX_PARAMS[e.type]:
        value = getattr(e, name)
        if name == "c":
            row.extend(round(x, 6) for x in value)
        elif name == "seed":
            row.append(round(value, 9))
        elif name == "home":
            row.append(1 if value else 0)
        else:
            row.append(value)
    return row


def _e(x):
    return math.floor(x * E_SCALE + 0.5)


def _animating(lights):
    """(animating, decidable): decidable unless a float32/float64 knife edge could flip it."""
    animator, tg = lights.animator, lights.targets
    if animator.effects:
        return True, True
    embers = tg.heat and any(c is not None and c.vol_red for c in tg.ring)
    paused = tg.paused_play and not tg.asleep and tg.family == "home"
    if tg.pending or tg.tint is not None or tg.asleep or tg.offline or embers or paused \
            or lights.song_prog is not None:
        return True, True
    tint = max(abs(x) for x in animator.tint)
    residue = animator.residue
    decidable = abs(residue - al.RESIDUE) > ANIMATING_MARGIN and abs(tint - al.RESIDUE) > ANIMATING_MARGIN
    return residue > al.RESIDUE or tint > al.RESIDUE, decidable


class Seq:
    """A timeline: ``op`` queues engine calls for the next step, ``step``/``run`` render."""

    def __init__(self, name, note, bytes_every=4, pending=False):
        self.name, self.note = name, note
        self.lights = _Probe(0)
        self.t = 0
        self.bytes_every = bytes_every
        self.record_pending = pending           # [r2.2] expect.pending at every step (M33)
        self.drive, self.dither = DEFAULT_DRIVE, False
        self.knob = al.AliveKnob()
        self._ops = []
        self.steps = []

    def at(self, t):
        """Jump the clock (no render in between: the engine is not called)."""
        self.t = t % U32
        return self

    def op(self, name, at=None, **params):
        """Queue an engine call for the next step; ``at`` = its time as an offset from the current
        time (default: the step's own ``now``)."""
        entry = {"op": name, **params}
        if at is not None:
            entry["t"] = (self.t + at) % U32
        self._ops.append(entry)
        return self

    def output(self, drive=None, dither=None, bytes_every=None):
        if drive is not None:
            self.drive = drive
        if dither is not None:
            self.dither = dither
        if bytes_every is not None:
            self.bytes_every = bytes_every
        return self

    def step(self, dt, frame=None, local=None, bytes_=None):
        self.t = (self.t + dt) % U32
        now = self.t
        raw = isinstance(frame, Raw)
        frame = wire(frame) if frame is not None else None
        lights = self.lights
        ticks_before = len(lights.tick_values)
        seeds_before = len(lights.seeds)
        lims = []
        for entry in self._ops:
            _apply(self, entry, now, lims)
        ring, buttons = lights.render(now, frame, *(local if local else (None, None)))
        for x in lights.tick_values[ticks_before:]:
            if abs(x - math.floor(x) - 0.5) < TICK_TIE_MARGIN:
                raise AssertionError(f"{self.name} step {len(self.steps)} (now {now}): tick length {x!r} is "
                                     "a float knife edge; change the detent timing")
        for seed in lights.seeds[seeds_before:]:
            for k in al.SCATTER_ORDER:
                p = math.fmod(seed + k * 60 / 9, 60)
                for edge in (p - 2.4, p + 2.4):
                    if abs(edge - round(edge)) < SCATTER_MARGIN:
                        raise AssertionError(f"{self.name}: scatter seed {seed!r} puts a spark bound on an integer")
        expect = {"e": [_e(x) for c in ring for x in c] + [_e(x) for c in buttons for x in c]}
        with_bytes = bytes_ if bytes_ is not None else (not self.dither and len(self.steps) % self.bytes_every == 0)
        if with_bytes:
            if self.dither:
                raise AssertionError("bytes are only recorded with dither off")
            ring_lit, button_lit = lights.lit_masks()            # [user 2026-09-26] F-T
            rb, bb = reference_output(ring, buttons, self.drive, ring_lit, button_lit)
            expect["bytes"] = rb + bb
            expect["lit"] = lit_hex(ring_lit, button_lit)
        expect["asleep"] = lights.asleep()
        expect["cursor"] = lights.cursor()
        expect["flash"] = FLASH_CODE[lights._flash]
        expect["fx"] = [fx_row(e) for e in lights.animator.effects]
        if lims:
            expect["lim"] = lims
        if self.record_pending:
            expect["pending"] = bool(lights.targets.pending)
        animating, decidable = _animating(lights)
        if decidable:
            expect["animating"] = animating
        record = {"now": now}
        if self._ops:
            record["ops"] = self._ops
        if frame is not None:
            record["frame"] = frame
            if raw:
                record["raw"] = True
        if local:
            record["local"] = list(local)
        if self.drive != DEFAULT_DRIVE:
            record["drive"] = self.drive
        if self.dither:
            record["dither"] = True
        record["expect"] = expect
        self.steps.append(record)
        self._ops = []
        return self

    def run(self, duration, frame=None, local=None, every=20):
        """Steps every ``every`` ms for ``duration`` ms (the first one ``every`` after now)."""
        for _ in range(duration // every):
            self.step(every, frame, local)
        return self

    def rest(self, duration, frame=None, local=None):
        """A steady stretch, rendered every 100 ms (the engine sees dt = min(50, gap))."""
        return self.run(duration, frame, local, every=100)

    def turn(self, frames, local_max, positions, gap, delta=None):
        """Detents ``gap`` ms apart (one per position change), each rendered 3 ms after the detent
        at the new local position; ``frames(pos)`` is the host frame shown at that moment."""
        prev = positions[0]
        for pos in positions[1:]:
            self.op("detent", at=gap - 3, delta=pos - prev if delta is None else delta)
            self.step(gap, frames(pos), (pos, local_max))
            prev = pos
        return self


# ------------------------------------------------------------- sequences
def offline_sequences():
    s = Seq("offline-reset-reveal", "power-up reveal and offline breath (2600 ms), unclaimed frames and inputs "
                                    "ignored, reset -> reveal with dt 0, drive / dither / power limit", bytes_every=2)
    s.step(0)                                                   # the constructor's reset(0): reveal at 0
    s.run(900, every=16)
    s.run(2000, home(54), every=40)                             # a frame while unclaimed changes nothing
    s.op("detent", delta=1).op("press", slot=2).op("limit", dir=1)
    s.step(16)                                                  # unclaimed inputs are ignored
    s.output(drive=255).run(300)
    s.output(drive=1).run(100)
    s.output(drive=60).run(100)
    s.output(drive=150, dither=True).run(200)                   # dithered, then off: residuals zeroed
    s.output(dither=False).run(100)
    s.op("reset", at=40)
    s.step(40)                                                  # reset: reveal again, first dt 0
    s.run(600, every=16)
    s.op("reset", at=5).step(9)                                 # reset 4 ms before the render
    s.rest(2700)
    return [s]


def claim_sequences():
    out = []
    s = Seq("claim-seed-boot-home", "claim: the first frame only seeds (seq, external, playing, family: no "
                                    "bloom/shimmer/fill/reveal); boot home; a repeated claim is a no-op; then "
                                    "a new seq blooms over the BLUE external override")
    s.run(200, every=50)
    s.op("claim")
    seeded = home(54, external=True, playing=True, feedback=("ok", 5))
    s.step(16, seeded)
    s.run(1400, seeded, every=17)
    s.op("claim")
    s.run(1600, seeded, every=25)                               # boot runs to 2800 ms
    s.run(200, home(54, external=True, playing=True, feedback=("ok", 5)))
    s.run(900, home(54, external=True, playing=True, feedback=("ok", 6)))
    s.run(400, home(54, external=False, playing=True, feedback=("ok", 6)), every=25)
    out.append(s)

    s = Seq("claim-no-frame-recent", "claimed without a frame draws nothing and waits for the boot; claim into "
                                     "Recent boots home=false; a flash window ends without frames; asleep "
                                     "while frameless; release before any frame")
    s.op("claim").step(10)
    s.run(480, every=40)                                        # claimed, no frame yet: dark, no boot
    s.run(1500, lst(12, 4), (4, 11), every=25)                  # boot (home false), seeds
    s.run(300, lst(12, 4, feedback=("ok", 3)), (4, 11))         # ok on Recent: bloom + flash
    s.run(1200, every=30)                                       # frameless: the flash window still ends
    s.rest(3400)                                                # the sleep deadline passes frameless
    s.run(600, lst(12, 4, feedback=("ok", 3)), (4, 11), every=30)   # the frame returns: asleep
    s.op("detent", at=5, delta=1)
    s.run(400, lst(12, 5, feedback=("ok", 3)), (5, 11), every=25)
    s.op("release").step(16)
    s.run(400, every=40)
    s.op("claim").step(16)
    s.op("release", at=8).step(16)                              # released before the first frame
    s.rest(2000)
    out.append(s)
    return out


def sleep_sequences():
    out = []
    s = Seq("sleep-wake-inputs", "asleep 5000 ms after the last input (exact edge), resting alphas "
                                 "(steady, no breath: user 2026-09-26, 12.8), wake on detent / press / limit / EXT / pending / flash; a "
                                 "flash or pending forces awake without clearing stateAsleep")
    v40 = home(40, playing=True)
    s.op("claim").step(0, v40)
    s.run(4960, v40, every=80)                                  # t = 4960
    s.step(39, v40).step(1, v40).step(1, v40)                   # 4999 / 5000 / 5001
    s.rest(5400, v40)
    s.op("detent", at=20, delta=1)
    s.step(23, home(40, playing=True), (41, 100))               # wake + tick (local ahead: pending)
    s.run(300, home(41, playing=True), (41, 100))
    s.rest(5000, home(41, playing=True))                        # asleep again at detent + 5000
    s.op("press", at=7, slot=3)
    s.run(400, home(41, playing=True))                          # wake + press
    s.rest(5000, home(41, playing=True))
    v0 = home(0, playing=True)
    s.op("limit", at=4, dir=-1)
    s.run(600, v0, (0, 100))                                    # wake + bound at the lower end stop
    s.rest(5000, v0, (0, 100))
    s.run(1600, home(20, c=0, playing=True), every=40)          # pending while asleep: awake, no deadline
    s.run(1600, v0, every=40)                                   # answered: back to rest, no wake
    s.run(900, home(0, playing=True, feedback=("ok", 2)), every=30)   # a flash forces awake (650 ms)
    s.run(600, home(0, playing=True, feedback=("err", 3)), every=30)  # err: 900 ms
    s.run(900, v0, every=30)
    s.run(3000, home(0, external=True, playing=True), every=40)  # EXT: wake, shimmer, 3200 ms
    s.run(900, home(0, external=True, playing=True), every=60)
    out.append(s)

    s = Seq("sleep-recheck-pending-flash", "the sleep deadline meets a pending volume or a running flash: "
                                           "re-check every 1000 ms; asleep at the first clear re-check; a stale "
                                           "request on the Sonos-off notice is not pending and rests [R1]")
    s.op("claim").step(0, home(50))
    s.run(4000, home(50), every=80)
    s.run(2600, home(62, c=50), every=40)                       # pending across the 5000 ms deadline
    s.run(700, home(62), every=35)                              # answered between re-checks
    s.run(1600, home(62), every=50)
    s.op("press", slot=0)
    s.rest(4600, home(62))                                      # deadline: press + 5000
    s.run(1500, home(62, feedback=("err", 9)), every=30)        # an err flash straddles the deadline
    s.run(1500, home(62, feedback=("err", 9)), every=50)
    s.run(2500, lst(9, 3, activity="pending"), every=50)        # a list pending keeps it awake
    s.run(1500, lst(9, 3), every=50)
    s.op("press", slot=1)
    s.run(600, notice(61, 41), every=30)                        # [R1] a stale request on the Sonos-off
    s.rest(5200, notice(61, 41))                                # notice [D15] is not pending: it rests
    s.run(600, home(61, c=41), every=30)                        # the same request with Sonos up: pending
    out.append(s)
    return out


def _vol_frame(lag):
    """The host's Home frame while the knob turns: it echoes one position late and confirms
    ``lag`` positions behind (negative: ahead, turning down)."""
    def frame(pos):
        c = max(0, min(100, pos - lag))
        return home(pos if lag == 0 else max(0, min(100, pos - 1)), c=c, playing=True)
    return frame


def turning_sequences():
    out = []
    s = Seq("turning-velocity-level", "detents with realistic HMI timing: slow (len 0), medium, fast (len 7), "
                                      "bursts per frame, more than 8 merging into the last, reversals, "
                                      "|delta| > 1; the local level position ahead of the host (pending comet); "
                                      "end stops bound RED (>= 90 %) and WARM (0), clamped local positions",
            bytes_every=3)
    s.op("claim").step(0, home(30, playing=True), (30, 100))
    s.run(600, home(30, playing=True), (30, 100), every=30)
    s.turn(_vol_frame(2), 100, list(range(30, 35)), 470)        # slow: the velocity resets (> 400 ms)
    s.turn(_vol_frame(1), 100, list(range(34, 44)), 70)         # medium
    s.turn(_vol_frame(3), 100, list(range(43, 63)), 17)         # fast: one per frame
    pos = 62
    for _ in range(6):                                          # three detents per rendered frame
        for k in range(3):
            s.op("detent", at=4 + 5 * k, delta=1)
        pos += 3
        s.step(17, home(pos - 4, c=pos - 6, playing=True), (pos, 100))
    s.run(200, home(pos, playing=True), (pos, 100))
    for k in range(11):                                         # 11 in one frame: 9..11 merge into 8
        s.op("detent", at=1 + k, delta=1)
    pos += 11
    s.step(16, home(pos - 11, playing=True), (pos, 100))
    s.run(160, home(pos, playing=True), (pos, 100))
    s.turn(_vol_frame(-2), 100, list(range(pos, pos - 12, -1)), 23)   # reverse, fast
    pos -= 11
    for d in (2, 3, -3, 2):                                     # multi-position detents
        pos += d
        s.op("detent", at=40, delta=d)
        s.step(43, home(pos, playing=True), (pos, 100))
    s.run(400, home(pos, playing=True), (pos, 100))
    s.turn(_vol_frame(2), 100, list(range(pos, 101)), 33)       # up to the end stop
    s.run(200, home(100, playing=True), (100, 100))
    s.op("limit", at=7, dir=1)
    s.run(400, home(100, playing=True), (100, 100))             # bound in RED (>= 90 %), no tick [D4]
    s.op("limit", at=3, dir=1).op("limit", at=5, dir=1)
    s.run(160, home(100, playing=True), (100, 100))             # a bound replaces the bound
    s.op("detent", at=2, delta=1)                               # past the end: the local clamps to max
    s.step(20, home(100, playing=True), (104, 100))
    s.run(300, home(100, playing=True), (100, 100))
    s.turn(lambda p: home(p, playing=True), 100, list(range(100, -1, -4)), 19)   # fast down by 4
    s.run(300, home(0, playing=True), (0, 100))
    s.op("limit", at=6, dir=-1)
    s.run(500, home(0, playing=True), (0, 100))                 # bound WARM at the lower stop
    s.op("detent", at=9, delta=-1)
    s.step(20, home(0, playing=True), (-2, 100))                # clamped at 0
    s.rest(5600, home(0, playing=True), (0, 100))               # falls asleep
    out.append(s)

    s = Seq("tick-direction-velocity-edges", "6.2: the tick direction follows the displayed cursor (sign of "
                                             "cd(new, old)), not the detent, when the host moves the cursor the "
                                             "other way (local vetoed), and sign(delta) when it stays; the 400 ms "
                                             "velocity gap edge (390 and 400 keep the velocity, 401 resets it)")
    s.op("claim").step(0, lst(12, 6, activity="pending"))
    s.run(600, lst(12, 6, activity="pending"), every=30)
    s.op("detent", at=5, delta=1)
    s.step(20, lst(12, 4, activity="pending"), (7, 11))         # vetoed (pending); host 6 -> 4: dir -1
    s.run(300, lst(12, 4, activity="pending"), every=30)
    s.op("detent", at=5, delta=-1)
    s.step(20, lst(12, 7, activity="pending"), (3, 11))         # host 4 -> 7 against a -1 detent: dir +1
    s.run(300, lst(12, 7), (7, 11), every=30)
    s.op("detent", at=5, delta=1)
    s.step(20, home(50, playing=True), (51, 99))                # level, vetoed by max 99: MODE + tick
    s.run(200, home(50, playing=True), (51, 99), every=40)
    s.op("detent", at=5, delta=1)
    s.step(20, home(44, playing=True), (52, 99))                # host 50 -> 44 while turning up: dir -1
    s.op("detent", at=5, delta=1)
    s.step(20, home(44, playing=True), (53, 99))                # cursor unchanged: sign(delta)
    s.run(300, home(44, playing=True), every=30)
    s.run(300, tracks(2, activity="pending"), every=30)
    s.op("detent", at=5, delta=1)
    s.step(20, tracks(0, activity="pending"), (2, 2))           # transport, vetoed: host Next -> Prev, dir -1
    s.run(400, tracks(0), (0, 2), every=30)
    s.run(600, home(20, playing=True), (20, 100), every=50)     # rest (> 400 ms)
    pos = 20
    for gaps, delta in (((13, 90), 1), ((13, 30), 1), ((13, 180), 2), ((13, 45, 300), 1)):
        for gap in gaps:                                        # exact ties: vel 5, 15, 5 and 10 -> 7
            pos += delta
            s.op("detent", at=gap - 3, delta=delta)
            s.step(gap, home(pos, playing=True), (pos, 100))
        s.run(500, home(pos, playing=True), (pos, 100), every=50)
    pos = 30
    for gap in (390, 400, 401):
        s.turn(lambda p: home(p, playing=True), 100, list(range(pos, pos + 12)), 17)   # fast: vel high
        pos += 11
        s.op("detent", at=gap - 3, delta=1)                   # exactly gap ms after the last detent
        s.step(gap, home(pos + 1, playing=True), (pos + 1, 100))
        s.op("detent", at=117, delta=1)
        s.step(120, home(pos + 2, playing=True), (pos + 2, 100))   # len depends on the kept velocity
        pos += 2
        s.run(300, home(pos, playing=True), (pos, 100), every=30)
    out.append(s)

    s = Seq("queue-pressure", "a fast spin with presses, flashes and a mode change keeps the queue at its 8 "
                              "cap: [D12] evictions in both ports, killed effects first; more than 8 presses "
                              "or 4 limits in one frame are dropped", bytes_every=5)
    s.op("claim").step(0, home(20, playing=True), (20, 100))
    s.run(3000, home(20, playing=True), (20, 100), every=60)
    pos = 20
    for k in range(40):
        for j in range(2):
            s.op("detent", at=3 + 6 * j, delta=1)
        if k % 5 == 0:
            s.op("press", at=2, slot=k % 4)
        pos += 2
        seq = 20 + k // 8
        kind = "ok" if (k // 8) % 2 else "err"
        s.step(16, home(pos - 2, c=pos - 4, playing=True, feedback=(kind, seq)), (pos, 100))
    s.run(300, home(pos, playing=True, feedback=("ok", 30)), (pos, 100))
    for k in range(10):
        s.op("press", at=1 + k, slot=k % 4)
    for k in range(6):
        s.op("limit", at=2 + k, dir=1)
    s.step(16, home(100, playing=True, feedback=("ok", 30)), (100, 100))
    s.run(400, home(100, playing=True, feedback=("ok", 30)), (100, 100))
    s.run(900, lst(11, 5), (5, 10), every=30)
    out.append(s)
    return out


def local_cursor_sequences():
    s = Seq("local-cursor-rules", "6.3 [D14] per ring style: level (max 100; vetoed by max != 100, the notice "
                                  "layout, activity offline), selection (max == count - 1; vetoed while "
                                  "pending/loading or on a count mismatch; leaving the window: the v4 defensive "
                                  "rule), transport (max 2; vetoed while pending); no local = the frame's")
    s.op("claim").step(0, home(40, playing=True))
    for frame, local in ((home(40, playing=True), (60, 100)),           # level: 60 replaces 40 (pending)
                         (home(40, playing=True), (60, 99)),            # max 99: vetoed
                         (home(40, playing=True), None),                # no local position
                         (notice(40, 40), (60, 100)),                   # notice: vetoed
                         (home(40, activity="offline"), (60, 100)),     # activity offline: vetoed
                         (home(40, led="white"), (95, 100)),            # white style
                         (lst(12, 4), (9, 11)),                         # selection: applied
                         (lst(12, 4), (9, 12)),                         # count mismatch: vetoed
                         (lst(12, 4, activity="pending"), (9, 11)),     # pending: vetoed
                         (lst(12, 4, activity="loading"), (9, 11)),     # loading: vetoed
                         (lst(12, 4, more=11), (11, 11)),               # the local index on More
                         (lst(45, 12), (12, 44)),
                         (lst(45, 12), (40, 44)),                       # leaves the window: defensive rule
                         (lst(45, 12, first=None), (13, 44)),           # absent first (derived != 0)
                         (lst(9, 2, windows=True), (5, 8)),             # Windows (closed entry 5: accent L2)
                         (lst(9, 2, windows=True, activity="pending"), (5, 8)),
                         (tracks(1), (0, 2)),                           # transport: applied
                         (tracks(1), (2, 2)),
                         (tracks(1, no_prev=True), (0, 2)),
                         (tracks(1), (2, 3)),                           # max 3: vetoed
                         (tracks(1, activity="pending"), (2, 2)),       # pending: vetoed
                         (tracks(2), None)):
        s.run(240, frame, local, every=24)
    return [s]


def feedback_sequences():
    out = []
    s = Seq("feedback-bloom-fail-sweep", "6.4.2: ok -> bloom, err -> fail at the new cursor (FG kill), a repeated "
                                         "seq is no event, a new seq restarts the window; Tracks ok with skip "
                                         "+1/-1 -> sweep [D9], plain ok -> bloom, err -> fail")
    s.op("claim").step(0, home(54, playing=True, feedback=("ok", 1)))
    s.run(3000, home(54, playing=True, feedback=("ok", 1)), every=60)
    s.run(1000, home(56, playing=True, feedback=("ok", 2)))
    s.run(300, home(56, playing=True, feedback=("err", 3)))
    s.run(300, home(58, playing=True, feedback=("ok", 4)))
    s.run(1100, home(58, playing=True, feedback=("ok", 4)), every=25)
    s.run(200, home(60, playing=True, feedback=("err", 5)))
    s.run(1000, home(60, playing=True, feedback=("err", 5)), every=25)
    s.run(400, tracks(1, feedback=("err", 5)))                  # mode change: reveal; same seq
    s.run(900, tracks(1, feedback=("ok", 6, 1)), every=25)      # skip +1: sweep clockwise
    s.run(900, tracks(1, feedback=("ok", 7, -1)), every=25)     # skip -1: sweep anticlockwise
    s.run(900, tracks(0, feedback=("ok", 8)), every=25)         # plain ok: bloom
    s.run(900, tracks(2, feedback=("err", 9)), every=25)
    s.run(300, tracks(1, no_prev=True, feedback=("ok", 10, 1)))
    s.run(200, tracks(1, no_prev=True, feedback=("ok", 11, -1)))    # a sweep kills the sweep
    s.run(900, tracks(1, no_prev=True, feedback=("ok", 11, -1)), every=25)
    out.append(s)

    s = Seq("wash-switched", "6.4.2 [D7]: ok after Recent/Windows with a non-WARM selected accent washes that "
                             "colour at the previous cursor (even under the pending pulse); no accent, More, a "
                             "closed Recent entry, a grey (sat -> WARM) accent, white LEDs or loading bloom")
    s.op("claim").step(0, home(54, playing=True))
    s.run(400, home(54, playing=True), every=40)
    seq = [10]

    def album(list_frame, local, pending=True):
        s.run(300, list_frame, local, every=30)
        if pending:
            s.run(300, dict(list_frame, activity="pending"), None, every=30)
        seq[0] += 1
        s.run(1100, home(54, playing=True, feedback=("ok", seq[0])), every=30)

    album(lst(12, 4), (4, 11))                                  # accent entry 4: wash (Recent album start)
    album(lst(12, 4, windows=True), (4, 11))                    # Windows switch: wash
    album(lst(12, 3), (3, 11))                                  # accent 0 (no accent): bloom
    album(lst(12, 5), (5, 11))                                  # grey: sat -> WARM: bloom
    album(lst(12, 11, more=11), (11, 11))                       # More: white: bloom
    album(lst(12, 7), (7, 11))                                  # closed Recent entry: white: bloom
    album(lst(12, 9, windows=True), (9, 11))                    # closed Windows entry keeps its accent: wash
    album(lst(12, 4, led="white"), (4, 11))                     # white LEDs: bloom
    album(lst(12, 8), (8, 11), pending=False)                   # no pending pulse: wash
    s.run(300, lst(12, 8, activity="loading"), None, every=30)  # loading: no selected entry: bloom
    seq[0] += 1
    s.run(1100, home(54, playing=True, feedback=("ok", seq[0])), every=30)
    out.append(s)
    return out


def play_sequences():
    s = Seq("play-pause-fill-drain", "6.4.3 [D8]: fill/drain only between two Home frames that both carry "
                                     "playing and differ; n = (displayed + 1) / 2 (local value); an absent "
                                     "playing breaks the pair; Recent -> Home never fills; paused Play breathes")
    s.op("claim").step(0, home(54, playing=True))
    s.run(1000, home(54, playing=True), every=50)
    s.run(1000, home(54, playing=False, buttons=PAUSED_BUTTONS), every=25)   # drain n 27
    s.run(1000, home(55, playing=True), every=25)               # fill n 28
    s.run(300, home(55), every=30)                              # absent: no event
    s.run(600, home(55, playing=False, buttons=PAUSED_BUTTONS), every=30)   # absent -> false: none
    s.run(900, home(60, playing=True), (70, 100), every=25)     # fill with the local value: n 35
    s.run(900, home(0, playing=False, buttons=PAUSED_BUTTONS), every=25)    # n 0
    s.output(drive=255, bytes_every=1)                          # bright scenes: the [D17] power limit
    s.run(900, home(100, playing=True), every=25)               # n 50
    s.run(600, lst(12, 4), (4, 11), every=30)
    s.run(900, home(100, playing=False, buttons=PAUSED_BUTTONS, feedback=("ok", 4)), every=30)   # wash, no drain
    s.output(drive=150, bytes_every=4)
    s.run(3000, home(100, playing=False, buttons=PAUSED_BUTTONS), every=50)  # paused Play breath (2600)
    s.run(400, home(100, playing=False, buttons=PLAY_DISABLED), every=40)   # disabled Play: dim
    s.rest(3000, home(33, playing=False, buttons=PAUSED_BUTTONS))           # rests: WARM
    s.run(900, idle_home(playing=False), every=30)              # idle layout: Home family, no ring
    s.run(900, idle_home(playing=True), every=30)               # fill with n 0

    t = Seq("album-start-confirmation", "6.4.3 as written after an album start from Recent: an ok frame "
                                        "carrying playing:false makes the true that follows a change, so fill "
                                        "(FG) cuts the wash (the engine rule; [R4] keeps the host from sending "
                                        "that false); an ok frame without playing (transport not confirmed, "
                                        "the [R4] host) lets the wash run its 1100 ms [D8]")
    t.op("claim").step(0, home(54, playing=False, buttons=PAUSED_BUTTONS))
    t.run(600, home(54, playing=False, buttons=PAUSED_BUTTONS), every=30)
    for seq, playing in ((2, False), (3, None)):
        t.run(600, lst(12, 4), (4, 11), every=30)
        t.run(300, dict(lst(12, 4), activity="pending"), every=30)
        t.run(300, home(54, playing=playing, buttons=PAUSED_BUTTONS, feedback=("ok", seq)), every=25)   # wash
        t.run(1200, home(54, playing=True, feedback=("ok", seq)), every=25)   # fill cuts it / nothing
    return [s, t]


def ext_sequences():
    s = Seq("ext-shimmer", "6.4.4: external false -> true on Home shimmers from the previous to the new cursor "
                           "and is an input with a 3200 ms sleep; no re-trigger while true; none on the seeding "
                           "frame or from Recent; BLUE only awake; the notice is Home")
    ext70 = home(70, external=True, playing=True)
    s.op("claim").step(0, home(40, external=True, playing=True))
    s.run(900, home(40, external=True, playing=True), every=30)     # seeded external: no shimmer
    s.run(600, home(40, playing=True), every=30)
    s.step(40, ext70)                                           # EXT: shimmer 55 -> 10, asleep in 3200
    s.run(3120, ext70, every=40)
    s.step(79, ext70)                                           # EXT + 3199: awake
    s.step(1, ext70)                                            # EXT + 3200: asleep
    s.step(1, ext70)
    s.rest(2000, ext70)
    s.run(600, home(70, playing=True), every=40)
    s.run(1500, home(12, external=True, playing=True), every=30)    # rising again while asleep: wake
    s.op("detent", at=10, delta=-1)
    s.run(300, home(12, external=True, playing=True), (11, 100))    # a turn while external
    s.run(200, lst(9, 3), None)
    s.run(900, home(20, external=True, playing=True), every=30)     # from Recent: no EXT (not both Home)
    s.run(300, home(20, playing=True), every=30)
    s.run(600, notice(20, 20), every=30)
    s.run(900, notice(20, 20, external=True), every=30)         # the notice is Home: EXT
    return [s]


def mode_sequences():
    s = Seq("mode-reveal-families", "6.4.1: a family change reveals (Home <-> Recent <-> Tracks <-> Windows); "
                                    "layouts inside Home (volume, nowPlaying, idle, notice) do not")
    s.op("claim").step(0, home(54, playing=True))
    s.run(3000, home(54, playing=True), every=60)
    for frame in (home(54, layout="nowPlaying", playing=True), idle_home(playing=True), notice(54, 54),
                  home(54, playing=True), lst(10, 2), tracks(1), lst(9, 3, windows=True), home(54, playing=True),
                  tracks(2), lst(21, 20, windows=True), lst(21, 20), home(54, led="white", playing=True)):
        s.run(540, frame, every=30)
    return [s]


def list_sequences():
    out = []
    s = Seq("windows-pending-accent", "[D13] the Windows pending cursor pulses in the app colour (260 ms "
                                      "phases, L1 hold after 3 s); Recent and Tracks pending stay WARM; white "
                                      "LEDs; a closed Windows entry keeps its accent; loading")
    s.op("claim").step(0, lst(9, 2, windows=True))
    s.run(600, lst(9, 2, windows=True), every=30)
    s.run(3400, lst(9, 2, windows=True, activity="pending"), every=26)
    s.run(400, lst(9, 2, windows=True), every=25)
    s.run(800, lst(9, 5, windows=True, activity="pending"), every=25)    # closed entry 5: accent kept
    s.run(800, lst(21, 13, windows=True, activity="pending"), every=25)
    s.run(800, lst(9, 2, windows=True, led="white", activity="pending"), every=25)
    s.run(800, lst(12, 4, activity="pending"), every=25)        # Recent pending: WARM
    s.run(800, tracks(2, activity="pending"), every=25)
    s.run(400, tracks(2), every=25)
    s.run(1200, lst(11, 10, more=10, activity="loading"), every=25)   # loading: segment 0
    out.append(s)

    s = Seq("list-tint", "5.4 ambient tint: glides in (220 ms) with the cursor accent on Recent/Windows, follows "
                         "detents, fades on Home / white LEDs / a flash / rest; the residue decays everywhere")
    s.op("claim").step(0, home(54, playing=True))
    s.run(300, home(54, playing=True))
    s.run(900, lst(20, 0), (0, 19), every=25)
    s.turn(lambda p: lst(20, max(0, p - 1)), 19, list(range(0, 12)), 95)
    s.run(600, lst(20, 11), (11, 19), every=25)
    s.run(600, lst(20, 11, led="white"), (11, 19), every=25)
    s.run(600, lst(20, 11), (11, 19), every=25)
    s.run(900, lst(20, 11, feedback=("err", 3)), (11, 19), every=25)   # a red flash: not an accent
    s.run(700, home(54, playing=True), every=25)                # the tint residue decays on Home
    s.run(600, lst(9, 6, windows=True), (6, 8), every=25)
    s.rest(5600, lst(9, 6, windows=True), (6, 8))               # rests: WARM, no tint
    s.op("press", slot=3)
    s.run(900, lst(9, 6, windows=True), (6, 8), every=25)
    out.append(s)
    return out


def heat_sequences():
    s = Seq("heat-embers", "near-max embers: Home awake >= 90 % on the RED segments (volRed) with the rounded "
                           "periods [D11]; 89 % (AMBER) none; white LEDs none; asleep none; an err flash at >= 90 %; "
                           "the [D17] power limit at drive 255", bytes_every=3)
    s.op("claim").step(0, home(95, playing=True))
    s.run(3500, home(95, playing=True), every=17)
    s.run(900, home(89, playing=True), every=30)
    s.turn(lambda p: home(p, c=p - 1, playing=True), 100, list(range(89, 101)), 45)
    s.run(1500, home(100, playing=True), (100, 100), every=17)
    s.run(900, home(100, led="white", playing=True), (100, 100), every=30)
    s.run(1200, home(92, playing=True, feedback=("err", 4)), every=17)
    s.output(drive=255).run(900, home(92, playing=True), every=17)
    s.output(drive=150).rest(5600, home(92, playing=True))      # rests: no heat
    return [s]


def clock_sequences():
    s = Seq("time-of-day-clock-wrap", "8.3: the latched clock scales the resting brightness continuously "
                                      "[D18] across midnight twice (50 h), a re-latch, and reset clearing it; "
                                      "floored at 0.80 at rest (user 2026-09-26, 12.8)")
    s.op("claim").op("clock", minute=23 * 60 + 40).op("progress", pos=0, dur=86400000)
    s.step(0, home(40, playing=True))
    s.rest(5200, home(40, playing=True))                        # asleep at 23:40 + 5 s
    for _ in range(150):                                        # 50 h in 20 min strides (dt capped at 50)
        s.step(1200000, home(40, playing=True))
        s.step(50, home(40, playing=True))
    s.op("clock", minute=12 * 60).step(50, home(40, playing=True))
    s.rest(400, home(40, playing=True))
    s.op("detent", delta=1)
    s.step(20, home(40, playing=True), (41, 100))               # awake: todB unused
    s.rest(5200, home(41, playing=True))
    for _ in range(40):                                         # 12:00 .. 18:40
        s.step(600000, home(41, playing=True))
    s.op("reset").step(16)                                      # reset clears the clock and progress
    s.op("claim").step(16, home(41, playing=True))
    s.rest(5600, home(41, playing=True))
    return [s]


def song_sequences():
    s = Seq("song-hand", "8.4 [R3]: the hand shows asleep on Home while the last Home frame says playing:true "
                         "and progress is latched; playing false / absent (not playing) freezes and hides it, "
                         "true resumes; a seek re-latches; dur 0 clears; outside Home hidden; clamps at 1; "
                         "survives release/claim; [user 2026-09-26] 12.8: the latch runs, but no hand is drawn at rest")
    s.op("progress", pos=30000, dur=200000)                     # latched before the claim
    s.step(0)
    s.op("claim").op("clock", minute=21 * 60 + 30)
    s.step(16, home(54, playing=True))
    s.rest(5300, home(54, playing=True))                        # asleep: the hand at night todB
    s.rest(3000, home(54, playing=True))
    s.run(1000, home(54, playing=False, buttons=PAUSED_BUTTONS), every=30)   # drain wakes; frozen
    s.rest(5200, home(54, playing=False, buttons=PAUSED_BUTTONS))            # asleep: no hand
    s.rest(1500, home(54))                                      # absent: still frozen
    s.run(1000, home(54, playing=True), every=30)               # fill; resumes from the frozen position
    s.rest(4000, home(54, playing=True))
    s.rest(3000, home(54))                                      # [R3] true -> absent: hidden, frozen
    s.rest(2000, home(54, playing=True))                        # resumes (no fill: absent breaks the pair)
    s.op("progress", pos=190000, dur=200000)                    # seek near the end
    s.rest(5000, home(54, playing=True))
    s.run(8000, home(54, playing=True), every=250)              # clamps at 1
    s.op("progress", pos=5000, dur=0)                           # dur 0 clears
    s.rest(1000, home(54, playing=True))
    s.op("progress", pos=250000, dur=240000)                    # pos > dur: clamped
    s.rest(1000, home(54, playing=True))
    s.op("progress", pos=1000, dur=240000)
    s.op("press", slot=1)
    s.run(1000, lst(12, 4), (4, 11), every=40)                  # Recent: hidden
    s.rest(6000, lst(12, 4), (4, 11))
    s.run(1000, home(54, playing=True), every=40)               # Home again (MODE wakes)
    s.rest(5000, home(54, playing=True))                        # asleep: the hand
    s.op("release").step(20)
    s.run(1000, every=50)
    s.op("claim").step(20, home(54, playing=True))
    s.rest(5300, home(54, playing=True))                        # the latch survived release/claim
    return [s]


def release_sequences():
    s = Seq("release-down-native", "release: down from the snapshot at the last cursor, offline marks and "
                                   "breath; a second release is a no-op; claim during down (boot kills it) "
                                   "and release during boot; native handover (8.1) [M29]: one native input "
                                   "hands the LEDs to the native path (no renders) until the next claim, 60 s "
                                   "without input bring back no reveal and no marks, and a claim from there "
                                   "plays boot", bytes_every=3)
    s.op("claim").step(0, home(62, playing=True, external=True))
    s.run(3000, home(62, playing=True, external=True), every=30)
    s.op("release", at=5)
    s.op("release", at=7)
    s.op("detent", at=8, delta=1)
    s.run(2400)                                                 # down (1800 ms), then the offline breath
    s.run(1600, every=40)
    s.op("claim").step(20, lst(12, 7, windows=True))            # boot (home false)
    s.run(1000, lst(12, 7, windows=True))
    s.op("release", at=3).run(900)                              # down kills the boot
    s.op("claim", at=11).run(700, home(20, playing=True))       # boot kills the down
    s.run(2400, home(20, playing=True), every=30)
    s.op("release").step(20)
    s.run(1200, every=30)                                       # drain, then the amber marks
    # [M29] Native handover: one native input at +100 hands the LEDs to the native path (the engine
    # is not rendered) until the next claim; 60 s without native input bring nothing back.
    s.at(s.t + 100 + 60000)
    s.op("claim").step(0, home(20, playing=True))               # a claim from the native path: boot
    s.run(3000, home(20, playing=True), every=30)
    return [s, _lease_flap()]


def _lease_flap():
    """Five downs live at once: each keeps its own snapshot (design play() e.snap per effect)."""
    s = Seq("lease-flap-downs", "release/claim flapping inside one 120 ms kill fade (section 7): every live "
                                "down draws the snapshot of its own release (the design keeps e.snap per "
                                "effect), including a claim + release between two renders; five downs and "
                                "three killed boots live at once, then the offline breath", bytes_every=2)
    s.op("claim").step(0, home(54, playing=True))
    s.run(2000, home(54, playing=True), every=20)
    s.op("release").step(16)                                    # down 1: the settled Home 54
    s.op("claim").step(16, home(20, playing=True))              # boot kills down 1 (it fades until +120)
    s.op("release").step(16)                                    # down 2 kills the boot
    s.op("claim").step(16, lst(12, 7, windows=True))            # boot kills down 2
    s.op("release").step(16)                                    # down 3: three downs live
    s.op("claim", at=3).op("release", at=9).step(16)            # claim + release between renders: down 4
    s.op("claim").step(16, home(95, playing=True))              # boot kills down 4
    s.op("release").step(16)                                    # down 5: five downs live
    s.run(400, every=8)
    s.run(2000, every=40)                                       # the last down ends; offline breath
    return s


def style_sequences():
    s = Seq("led-styles", "[D16] white = warm only: volume 80-90/>= 90 %, accents and the tint become WARM; "
                          "GREEN/RED buttons and flashes, BLUE external and AMBER offline marks stay",
            bytes_every=2)
    s.op("claim").step(0, home(85, playing=True))
    for led in ("color", "white", "color", "white"):
        s.run(400, home(85, led=led, playing=True), every=25)
        s.run(400, home(96, led=led, playing=True), every=25)
        s.run(400, home(96, led=led, external=True, playing=True), every=25)
        s.run(300, home(96, led=led, playing=True), every=25)
        s.run(400, lst(12, 4, led=led), (4, 11), every=25)
        s.run(400, lst(9, 6, windows=True, led=led), (6, 8), every=25)
    s.run(700, lst(9, 6, windows=True, led="white", feedback=("ok", 2)), every=25)
    s.run(900, lst(9, 6, windows=True, led="white", feedback=("err", 3)), every=25)
    s.op("release").run(2000, every=40)
    return [s]


def wrap_sequences():
    out = []
    base = U32 - 2000
    s = Seq("millis-wrap", "uint32 millis wrap: reset/claim just before 2^32; the sleep deadline, velocity, "
                           "flash window, effects, clock and progress extrapolation all cross 0")
    s.op("reset", at=base).at(base).step(0)
    s.op("claim").op("clock", minute=6 * 60 + 30).op("progress", pos=100000, dur=180000)
    s.step(16, home(47, playing=True))                          # sleep deadline base + 5016 (after 0)
    s.run(1480, home(47, playing=True), every=40)
    s.step(20, home(47, playing=True, feedback=("ok", 1)))      # bloom + flash window across 0
    s.run(80, home(47, playing=True, feedback=("ok", 1)))
    s.turn(lambda p: home(p - 1, c=p - 2, playing=True, feedback=("ok", 1)), 100, list(range(47, 64)), 29)
    s.run(900, lst(9, 3, activity="pending"), every=25)
    s.run(600, lst(9, 3), (3, 8), every=25)
    s.rest(5600, home(63, playing=True))                        # asleep after the wrap: hand + todB
    s.op("detent", at=30, delta=-1)
    s.run(600, home(63, playing=True), (62, 100), every=25)
    out.append(s)

    s = Seq("frame-gaps", "irregular render gaps: dt = min(50, now - last) with 1..700 ms gaps during a boot, "
                          "pending, a mode change and a bloom")
    s.op("claim").step(0, home(54, playing=True))
    gaps = [16, 16, 70, 5, 33, 120, 16, 16, 1, 49, 51, 700, 3, 17, 50, 2]
    frames = [home(54, playing=True), home(56, c=54, playing=True), lst(12, 4),
              home(54, playing=True, feedback=("ok", 7))]
    k = 0
    for _ in range(10):
        for gap in gaps:
            s.step(gap, frames[(k // 20) % len(frames)])
            k += 1
    for k in range(10):                                         # a stalled render: 10 detents 60 ms apart,
        s.op("detent", at=60 * (k + 1), delta=1)                # the 9th and 10th merge into the 8th
    s.step(650, home(54, playing=True))
    s.run(400, home(54, playing=True))
    out.append(s)
    return out


def golden_sequences():
    """The alive golden states (tests/fixtures/alive_golden.json, ALIVE.md 11.2) as one timeline."""
    import knob_adapter as ka       # tests/tools; needs tests/fixtures/alive_golden.json
    golden = ka.load_alive_golden()
    adapter = ka.Adapter(golden)
    frames = []
    for case in golden["cases"]:
        if case["group"] == "sweep":
            continue
        for led in ("color", "white"):
            for variant in case["variants"]:
                if variant["key"] not in ("base", "ext"):
                    continue
                st = ka.merge_state(case["st"], variant["patch"])
                frame = ka.alive_frame(adapter, st, {"lcd": variant["lcd"], "foot": variant["foot"]}, led,
                                       case_id=case["id"])
                if frame is not None:
                    frames.append(frame)
    s = Seq("golden-scenarios", "every non-sweep alive golden state (base and external variants, both LED "
                                "styles) through the engine, 2 renders each: MODE, feedback, EXT and PLAY/PAUSE "
                                "fire from the real frame sequence", bytes_every=3)
    s.op("claim").step(0, frames[0])
    for frame in frames:
        s.step(33, frame).step(50, frame)
    s.rest(5400, frames[-1])
    return [s]


# ------------------------------------------------------------- [r2] v5 frames (the v7 host)
def _v5_buttons(*spec):
    out = []
    for item in spec:
        label, enabled, icon = item[:3]
        button = {"label": label, "enabled": enabled, "icon": icon}
        if len(item) > 3:
            button.update(item[3])
        out.append(button)
    return out


def v5_first(count, index):
    """The v5 host window (PRESENTATION_V5 4.2, VOC-R03): clamp(index - 10, 0, count - 20)."""
    return 0 if count <= P.RING_WINDOW else max(0, min(index - 10, count - P.RING_WINDOW))


def _selection(count, index, colour, led="color", now=None, card=False):
    first = v5_first(count, index)
    width = min(P.RING_WINDOW, count - first)
    ring = {"style": "selection", "value": 0, "index": index, "count": count}
    if count > P.RING_WINDOW:
        ring["first"] = first                                   # always sent when count > 20 (P5-R9)
    if led == "color":
        ring["colors"] = [0 if card and first + k == count - 1 else colour(first + k) for k in range(width)]
    if now is not None:
        ring["now"] = now
    if card:
        ring["card"] = True
    return ring


def recent5(count, index, activity="idle", zero=(), feedback=None, led="color"):
    """Recently Added on the knob (v7): one flat list; ``zero``: entries not loaded yet (colour 0, M31)."""
    zero = set(zero)
    ring = _selection(count, index, lambda j: 0 if j in zero else accent(j), led)
    buttons = _v5_buttons(("Back", True, "back"), ("Open", True, "expand"), ("Play next", True, "playnext"),
                          ("Play", True, "play"))
    return _base(1, "RECENTLY ADDED", "recent", activity, led, buttons, ring, feedback, title=f"Album {index + 1}")


def loading5(layout="recent"):
    """K1 4.6: a whole list loading is style off + activity loading (M31)."""
    buttons = _v5_buttons(("Back", True, "back"), ("Open", False, "expand"), ("Play next", False, "playnext"),
                          ("Play", False, "play"))
    return _base(1, "RECENTLY ADDED", layout, "loading", "color", buttons,
                 {"style": "off", "value": 0, "index": 0, "count": 0}, meta="Loading…")


def explorer5(count, index, page=0, feedback=None, activity="idle"):
    """The music explorer mirror: tab ``page`` 0 Recently Added / 1 Favourite playlists (lit pair)."""
    ring = _selection(count, index, lambda j: accent(j + 7 * page))
    buttons = _v5_buttons(("Back", True, "back"), ("Recent", True, "clock", {"lit": "on" if page == 0 else "off"}),
                          ("Playlists", True, "playlists", {"lit": "on" if page == 1 else "off"}), ("Play", True, "play"))
    return _base(1, "RECENTLY ADDED", "explorer", activity, "color", buttons, ring, feedback, page=page)


def queue_colour(j):
    """Up next row colours (album colours; every 5th row warm: colour 0)."""
    return 0 if j % 5 == 3 else accent(j + 40)


def upnext5(count, index, now, card=False, liked=False, shuffle=False, feedback=None, activity="idle", led="color",
            colour=queue_colour):
    """The Up next mirror: ``now`` the playing row, ``card`` the Sonos-shuffle card (entry count - 1, K1 4.4)."""
    ring = _selection(count, index, colour, led, now=now, card=card)
    heart = {"lit": "on"} if liked else {}
    buttons = _v5_buttons(("Back", True, "back"), ("Shuffle", True, "shuffle", {"lit": "on" if shuffle or card else "off"}),
                          ("Like", not (card and index == count - 1), "heart", heart), ("Play", not card or index < count - 1, "play"))
    return _base(1, "RECENTLY ADDED", "upnext", activity, led, buttons, ring, feedback)


def seek5(t, d, activity="idle", feedback=None):
    """Seek: the lap ring, index = target s, count = D s (K1 4.3); Seek lit."""
    buttons = _v5_buttons(("Back", True, "back"), ("Up next", True, "expand"), ("Seek", True, "seek", {"lit": "on"}),
                          ("Skip", False, "tracks"))
    return _base(1, "TRACKS", "seek", activity, "color", buttons, {"style": "lap", "value": 0, "index": t, "count": d},
                 feedback)


def tracks5(index, activity="idle", feedback=None):
    buttons = _v5_buttons(("Back", True, "back"), ("Up next", True, "expand"), ("Seek", True, "seek"),
                          ("Skip", index != 1, ("prev", "tracks", "next")[index]))
    return _base(1, "TRACKS", "tracks", activity, "color", buttons,
                 {"style": "transport", "value": 0, "index": index, "count": 3}, feedback)


def win_colour(j):
    """Raw app colours of the Windows picker; every 4th app monochrome (0, M26)."""
    return 0 if j % 4 == 1 else accent(j + 17)


def windows5(count, index, left=None, right=None, feedback=None, led="color"):
    """The window picker: an assigned snap side is lit on with its raw app colour (VOC 2.4)."""
    ring = _selection(count, index, win_colour, led)

    def side(label, icon, app):
        if app is None:
            return (label, True, icon)
        extra = {"lit": "on"}
        if win_colour(app):
            extra["color"] = win_colour(app)
        return (label, True, icon, extra)
    buttons = _v5_buttons(("Back", True, "back"), side("Snap left", "snapleft", left), side("Snap right", "snapright", right),
                          ("Switch", True, "switch"))
    return _base(1, "WINDOWS", "windows", "idle", led, buttons, ring, feedback, title=f"Window {index + 1}")


def moment_sequences():
    s = Seq("moments-rows", "6.4 [r2] rows c-h: queued -> a sweep from 12 o'clock; shuffle on and off -> scatter with the "
                            "PRNG sequence; like -> the PINK bloom; unlike -> nothing; snap -> the half-wash left in the app "
                            "colour, right with colour 0 and under Warm only; started -> a wash in an accent, a green bloom for "
                            "colour 0 and a grey (sat fallback) colour, no fill in that render [M16]; no flash with a moment "
                            "[M7]; row i from Up next and the explorer", bytes_every=3)
    s.op("claim").step(0, recent5(24, 6))
    s.run(900, recent5(24, 6), (6, 23), every=30)
    s.run(700, recent5(24, 6, feedback=moment(2, "queued")), (6, 23), every=20)
    s.run(600, upnext5(12, 4, 4), (4, 11), every=25)
    s.run(800, upnext5(12, 4, 4, shuffle=True, feedback=moment(3, "shuffle")), (4, 11), every=20)
    s.run(800, upnext5(12, 4, 4, shuffle=False, feedback=moment(4, "shuffle")), (4, 11), every=20)
    s.run(1000, upnext5(12, 6, 4, liked=True, feedback=moment(5, "like")), (6, 11), every=20)
    s.run(500, upnext5(12, 6, 4, liked=False, feedback=moment(6, "unlike")), (6, 11), every=20)
    s.run(1200, upnext5(12, 6, 4, feedback={"kind": "ok", "seq": 7}), (6, 11), every=20)    # i: the Up next accent
    s.run(600, windows5(7, 2), (2, 6), every=25)
    s.run(1000, windows5(7, 2, left=2, feedback=moment(8, "snap", color=win_colour(2), side=-1)), (2, 6), every=20)
    s.run(1000, windows5(7, 3, left=2, right=3, feedback=moment(9, "snap", color=0, side=1)), (3, 6), every=20)
    s.run(1000, windows5(7, 4, left=4, led="white", feedback=moment(10, "snap", color=win_colour(4), side=-1)), every=20)
    s.run(600, home(54, activity="pending", buttons=PLAY_DISABLED), every=25)                # Starting…: no playing
    s.run(1300, home(54, playing=True, feedback=moment(11, "started", color=0x3070E0)), every=20)
    s.run(600, home(54, playing=True), every=30)
    s.run(600, recent5(24, 9), (9, 23), every=30)
    s.run(1000, home(60, playing=False, buttons=PAUSED_BUTTONS, feedback=moment(12, "started", color=0)), every=20)
    s.run(1000, home(60, playing=True, feedback=moment(13, "started", color=0x808890)), every=20)   # M16: no fill
    s.run(900, home(60, playing=True, feedback=("err", 14)), every=25)
    s.run(600, explorer5(24, 5), (5, 23), every=25)
    s.run(1200, home(60, playing=True, feedback=("ok", 15)), every=20)                       # i: the explorer accent
    return [s]


def mode_v5_sequences():
    s = Seq("mode-seek-explorer-upnext", "6.4 MODE [r2]: transport <-> lap reveals inside the Tracks family (Seek "
                                         "enter, exit, the idle exit); an explorer tab switch does not; families into "
                                         "and out of explorer and upnext; the lap follows host frames only [M11] and a "
                                         "detent ticks at the unmoved head; Jumping... is the comet only [M28]; bounds at "
                                         "0:00 and T_end")
    s.op("claim").step(0, home(54, playing=True))
    s.run(900, home(54, playing=True), every=60)
    s.run(600, tracks5(1), (1, 2), every=30)
    s.run(700, seek5(74, 300), every=30)
    s.op("detent", at=5, delta=1).step(20, seek5(79, 300), (5, 10))
    s.op("detent", at=5, delta=1).step(20, seek5(79, 300), (6, 10))
    s.run(300, seek5(84, 300), every=30)
    s.run(1500, seek5(84, 300, activity="pending"), every=25)
    s.op("limit", at=3, dir=1).run(500, seek5(297, 300), every=25)
    s.run(600, tracks5(1), (1, 2), every=30)
    s.run(500, seek5(0, 300), every=30)
    s.op("limit", at=3, dir=-1).run(400, seek5(0, 300), every=25)
    s.run(3300, seek5(0, 300), every=100)
    s.run(600, tracks5(1), every=30)
    s.run(600, upnext5(12, 4, 4), (4, 11), every=30)
    s.run(600, tracks5(1), every=30)
    s.run(600, explorer5(24, 3, page=0), (3, 23), every=30)
    s.run(600, explorer5(2, 0, page=1), (0, 1), every=30)
    s.run(600, explorer5(24, 3, page=0), (3, 23), every=30)
    s.run(600, recent5(24, 3), (3, 23), every=30)
    s.run(600, home(54, playing=True), every=30)
    return [s]


def reduced_motion_sequences():
    s = Seq("reduced-motion", "6.5 [M17]: with reducedMotion latched, wake / tick / sweep / scatter / reveal are dropped "
                              "(not queued, kill nothing) while the PRNG still draws; fail is stationary; boot, down, "
                              "bound, bloom (green and pink), fill, drain, wash, half, press and the continuous layers "
                              "stay; off again restores them")
    s.op("rm", on=True).op("claim").step(0, home(54, playing=True))
    s.run(3000, home(54, playing=True), every=60)
    s.turn(lambda p: home(p, c=p - 1, playing=True), 100, list(range(54, 60)), 60)
    s.run(600, recent5(24, 6), (6, 23), every=30)
    s.run(700, recent5(24, 6, feedback=moment(2, "queued")), (6, 23), every=25)
    s.run(800, upnext5(12, 4, 4, shuffle=True, feedback=moment(3, "shuffle")), (4, 11), every=25)
    s.run(1000, upnext5(12, 4, 4, shuffle=True, feedback=moment(4, "like")), (4, 11), every=20)
    s.run(900, upnext5(12, 4, 4, shuffle=True, feedback=("err", 5)), (4, 11), every=20)
    s.op("limit", at=4, dir=1).run(500, upnext5(12, 11, 4), (11, 11), every=25)
    s.run(1000, windows5(7, 2, left=2, feedback=moment(6, "snap", color=win_colour(2), side=-1)), (2, 6), every=20)
    s.op("press", at=3, slot=1).run(300, windows5(7, 2, left=2), (2, 6), every=25)
    s.rest(5600, windows5(7, 2, left=2), (2, 6))
    s.op("detent", at=5, delta=1).step(20, windows5(7, 3, left=2), (3, 6))
    s.run(600, windows5(7, 3, left=2), (3, 6), every=30)
    s.run(900, home(54, playing=False, buttons=PAUSED_BUTTONS), every=30)
    s.run(900, home(54, playing=True), every=30)
    s.op("rm", on=False).run(800, upnext5(12, 4, 4, feedback=moment(7, "shuffle")), (4, 11), every=20)
    s.op("detent", at=5, delta=1).step(20, upnext5(12, 5, 4), (5, 11))
    s.run(600, recent5(24, 6), (6, 23), every=30)
    s.op("release").run(2000, every=40)
    s.op("rm", on=True).op("claim").step(20, home(40, playing=True))
    s.run(1500, home(40, playing=True), every=40)
    s.op("release").run(2000, every=40)
    return [s]


def recentre_sequences():
    s = Seq("recentre-96", "5.1.1 [M9] and 6.3 [M15]: a 96-entry Recently Added list; the host re-centres its window "
                           "one round trip behind a fast local spin (0 -> 95 -> 0, past both window edges); entries the "
                           "host has not sent yet stay unlit; a jump more than 10 entries ahead shows a WARM class 3 "
                           "cursor", bytes_every=6)
    s.op("claim").step(0, recent5(96, 0))
    s.run(900, recent5(96, 0), (0, 95), every=30)
    pos = 0
    for _ in range(95):
        pos += 1
        s.op("detent", at=22, delta=1)
        s.step(25, recent5(96, max(0, pos - 2)), (pos, 95))
    s.run(400, recent5(96, 95), (95, 95), every=25)
    s.op("limit", at=5, dir=1).run(500, recent5(96, 95), (95, 95), every=25)
    for _ in range(95):
        pos -= 1
        s.op("detent", at=15, delta=-1)
        s.step(18, recent5(96, min(95, pos + 3)), (pos, 95))
    s.run(600, recent5(96, 0), (0, 95), every=25)
    s.op("detent", at=5, delta=15).step(20, recent5(96, 0), (15, 95))
    s.run(300, recent5(96, 15), (15, 95), every=25)
    return [s]


def hold_sequences():
    s = Seq("moment-hold-sleep", "6.1 [M22]: a feedback moment holds sleep for its effect's duration (like 900, shuffle "
                                 "700, queued 640, started wash 1100; unlike none) and wakes a resting knob; the sleep "
                                 "deadline meeting a hold re-checks every 1000 ms")
    q = upnext5(12, 4, 4)
    s.op("claim").step(0, q)
    s.run(4960, q, every=80)
    s.step(20, upnext5(12, 4, 4, feedback=moment(2, "like")))
    s.run(1000, upnext5(12, 4, 4, feedback=moment(2, "like")), every=20)
    s.rest(3000, upnext5(12, 4, 4, feedback=moment(2, "like")))
    s.run(1400, upnext5(12, 4, 4, feedback=moment(3, "unlike")), every=20)
    s.run(1400, upnext5(12, 4, 4, feedback=moment(4, "shuffle")), every=20)
    s.rest(5000, upnext5(12, 4, 4, feedback=moment(4, "shuffle")))
    s.run(1400, recent5(24, 6, feedback=moment(5, "queued")), every=20)
    s.rest(5000, recent5(24, 6, feedback=moment(5, "queued")))
    s.run(1500, home(54, playing=True, feedback=moment(6, "started", color=0x3070E0)), every=20)
    s.rest(6000, home(54, playing=True))
    return [s]


def tuning_sequences():
    s = Seq("tuning-pink-volfull", "3.2 [M24]: set_tuning: ledPink sets PINK to the OETF of the LED colour (the heart "
                                   "and the Like bloom), 0 restores the constant; ledVolFull puts the semantic volume "
                                   "body and half-step at 1.00; both survive release and claim; reset clears them",
            bytes_every=2)
    s.op("claim").step(0, upnext5(12, 6, 4, liked=True))
    s.run(900, upnext5(12, 6, 4, liked=True), (6, 11), every=30)
    s.op("tuning", pink=0xFF0C30, volFull=False).run(600, upnext5(12, 6, 4, liked=True), (6, 11), every=25)
    s.run(1000, upnext5(12, 6, 4, liked=True, feedback=moment(2, "like")), (6, 11), every=20)
    s.op("tuning", pink=0xFF0210, volFull=True).run(600, home(85, playing=True), every=25)
    s.run(600, home(95, playing=True), every=25)
    s.run(600, home(99, c=97, playing=True), every=25)
    s.op("release").run(1000, every=40)
    s.op("claim").step(20, home(85, playing=True))
    s.run(900, home(85, playing=True), every=25)
    s.op("tuning", pink=0, volFull=False).run(600, home(85, playing=True), every=25)
    s.op("tuning", pink=0x00FF00, volFull=True).run(300, upnext5(12, 6, 4, liked=True), (6, 11), every=25)
    s.op("reset").step(20)
    s.op("claim").step(20, upnext5(12, 6, 4, liked=True))
    s.run(900, upnext5(12, 6, 4, liked=True), (6, 11), every=30)
    return [s]


def _play_dim(frame):
    """The same frame with Button 4 (Play) disabled: a ``dim`` 0.14 next to the liked heart (11.9)."""
    frame = json.loads(json.dumps(frame))
    frame["buttons"][3]["enabled"] = False
    return frame


def liked_sequences():
    """[r2.2][M32] 11.4: the liked button at PINK 0.30 -> WARM 0.26 at rest ([user 2026-09-26] 12.8)."""
    s = Seq("liked-heart-rest", "5.3 row 4 [r2.2][M32]: Up next row 6 is not liked (heart nav 0.70); like -> the PINK "
                                "bloom and the row turns liked: Button 3 is tone liked, PINK 0.30 (not r2.1's 1.0), next "
                                "to Shuffle off (WARM 0.30) and a dim Play (WARM 0.14); at rest it is WARM 0.26 like off "
                                "[M18]; a turn wakes the knob onto an unliked row (nav) and back (PINK 0.30); ledPink "
                                "draws the liked heart in the tuned PINK at 0.30", bytes_every=3)
    s.op("claim").step(0, upnext5(12, 6, 4))
    s.run(900, upnext5(12, 6, 4), (6, 11), every=30)
    s.run(1000, upnext5(12, 6, 4, liked=True, feedback=moment(2, "like")), (6, 11), every=20)
    liked_dim = _play_dim(upnext5(12, 6, 4, liked=True, feedback=moment(2, "like")))
    s.run(1500, liked_dim, (6, 11), every=25)
    s.rest(6000, liked_dim, (6, 11))
    s.op("detent", at=5, delta=1).step(20, upnext5(12, 7, 4), (7, 11))
    s.run(600, upnext5(12, 7, 4), (7, 11), every=30)
    s.op("detent", at=5, delta=-1).step(20, upnext5(12, 6, 4, liked=True), (6, 11))
    s.run(1800, upnext5(12, 6, 4, liked=True), (6, 11), every=30)
    s.op("tuning", pink=0xFF0C30, volFull=False).run(1500, upnext5(12, 6, 4, liked=True), (6, 11), every=30)
    s.rest(6000, upnext5(12, 6, 4, liked=True), (6, 11))
    s.op("tuning", pink=0, volFull=False).step(20, upnext5(12, 6, 4, liked=True), (6, 11))
    return [s]


def seek_pending_sequences():
    """[r2.2][M33] 11.4: a Seek frame sequence that keeps activity pending across two jumps."""
    s = Seq("seek-pending-two-jumps", "6.1 [r2.2][M33]: Seek in flight is one pending span. Jump 1 to 1:24 (Jumping..., "
                                      "activity pending); a turn during the jump moves the frozen target to 1:29 (the "
                                      "head follows the frame; the tick plays at the head); when jump 1 lands (2.7 s) the "
                                      "follow-up jump is sent and is slow (5 s): the frames stay pending across both "
                                      "jumps with no idle frame, so the Working comet never stops and sleep is held off "
                                      "past the 5 s deadline (rechecks); playback resumes at 1:29 (idle): the comet ends "
                                      "and the knob rests", pending=True)
    s.op("claim").step(0, tracks5(1))
    s.run(600, tracks5(1), (1, 2), every=30)
    s.run(600, seek5(74, 300), every=30)
    s.op("detent", at=5, delta=1).step(20, seek5(79, 300), (5, 10))
    s.op("detent", at=5, delta=1).step(20, seek5(84, 300), (6, 10))
    s.run(250, seek5(84, 300), every=25)                                    # the 250 ms debounce, then jump 1
    s.run(1200, seek5(84, 300, activity="pending"), every=25)
    s.op("detent", at=5, delta=1).step(20, seek5(89, 300, activity="pending"), (7, 10))
    s.run(1480, seek5(89, 300, activity="pending"), every=25)               # jump 1 lands at 2.7 s
    s.run(5000, seek5(89, 300, activity="pending"), every=25)               # the follow-up jump (slow)
    s.run(1000, seek5(89, 300), every=25)                                   # playback resumed
    s.rest(3000, seek5(89, 300))
    return [s]


def _card_raw(index):
    """The card frame unparsed: the card's unavailable bit set and a non-zero card colour (11.4)."""
    frame = wire(upnext5(6, index, 4, card=True))
    ring = dict(frame["ring"])
    ring["unavailable"] = 1 << 5
    ring["colors"] = list(ring["colors"])
    ring["colors"][5] = 0x10E020
    return Raw(dict(frame, ring=ring))


def card_sequences():
    s = Seq("upnext-card", "5.1.4 [M14]: the Sonos-shuffle card (ring.card, entry count - 1): no landmark and no cursor "
                           "cell; an err with the focus on it shakes at slot(5); a local spin 3 -> 5 -> 3 across it; "
                           "the same frames fed unparsed with the card's unavailable bit set and a non-zero card colour; "
                           "a 31-row card list (now 29, the host at 20 with first 10) with the local cursor spun to the "
                           "untransmitted card (L 30, F' 11) draws no cell there")
    s.op("claim").step(0, upnext5(6, 4, 4, card=True))
    s.run(900, upnext5(6, 4, 4, card=True), (4, 5), every=30)
    s.turn(lambda p: upnext5(6, 4, 4, card=True), 5, [4, 5], 60)
    s.run(600, upnext5(6, 5, 4, card=True), (5, 5), every=25)
    s.run(1000, upnext5(6, 5, 4, card=True, feedback=("err", 2)), (5, 5), every=20)
    s.turn(lambda p: upnext5(6, p, 4, card=True), 5, [5, 4, 3, 4, 5, 4, 3], 90)
    s.run(600, _card_raw(5), (5, 5), every=25)
    s.run(600, _card_raw(3), (3, 5), every=25)
    s.run(600, upnext5(31, 20, 29, card=True), (20, 30), every=30)
    s.turn(lambda p: upnext5(31, 20, 29, card=True), 30, list(range(20, 31)), 25)
    s.run(600, upnext5(31, 20, 29, card=True), (30, 30), every=25)
    s.run(600, upnext5(31, 30, 29, card=True), (30, 30), every=25)
    return [s]


def loading_sequences():
    s = Seq("loading-vs-unloaded", "5.1.3 case 1 [M31]: a 96-entry Recently Added list loading (K1's style off + "
                                   "loading): no cells, the Working comet, the local cursor off; the same list idle with "
                                   "entries 40..47 at colour 0 (not loaded yet): warm landmarks, a WARM class 3 cursor on "
                                   "entry 42, the local cursor running over them")
    s.op("claim").step(0, home(54, playing=True))
    s.run(600, home(54, playing=True), every=40)
    s.run(1500, loading5(), (42, 95), every=25)
    s.run(900, recent5(96, 42, zero=range(40, 48)), (42, 95), every=25)
    s.turn(lambda p: recent5(96, max(42, p - 1), zero=range(40, 48)), 95, list(range(42, 51)), 70)
    s.run(900, recent5(96, 50), (50, 95), every=25)
    return [s]


def endstop_sequences():
    s = Seq("end-stop-per-push", "[Q1] 12.5 through the HMI sampler (knob ops, scripted pushing): a push, spring back "
                                 "100 ms, a push again -> two bounds and two lim; held 2 s -> one; the attractor chattering "
                                 "at 20 ms for 300 ms -> one; a push 60 ms after springing back -> none; the lower bound; a "
                                 "new control id, a release and a pass without a ready control only seed; the Seek bounds")
    state = {"pos": 96}

    def hmi(duration, pos, pushing, frame, control=1, top=100, every=10):
        for _ in range(duration // every):
            s.op("knob", id=control, pos=pos, pushing=pushing, max=top)
            s.step(every, frame, (pos, top) if control == frame["id"] else None)
        state["pos"] = pos

    def chatter(duration, pos, frame, every=20):
        for k in range(duration // every):
            s.op("knob", id=1, pos=pos, pushing=k % 2 == 0, max=100)
            s.step(every, frame, (pos, 100))
    s.op("claim").step(0, home(96, playing=True))
    hmi(300, 96, False, home(96, playing=True))
    for p in (97, 98, 99, 100):
        hmi(40, p, False, home(p, playing=True))
    top = home(100, playing=True)
    hmi(300, 100, True, top)                                    # push: one bound, one lim
    hmi(100, 100, False, top)                                   # spring back 100 ms
    hmi(300, 100, True, top)                                    # push again: the second
    hmi(2000, 100, True, top, every=20)                         # held 2 s: nothing more
    hmi(200, 100, False, top)
    chatter(300, 100, top)                                      # chatter during one push: one
    hmi(200, 100, False, top)
    hmi(200, 100, True, top)                                    # a push after 200 ms: one
    hmi(60, 100, False, top)
    hmi(300, 100, True, top)                                    # 60 ms after springing back: none
    hmi(300, 100, False, top)
    for p in range(96, -1, -4):
        hmi(30, p, False, home(p, playing=True))
    bottom = home(0, playing=True)
    hmi(200, 0, True, bottom)                                   # the lower bound: dir -1
    hmi(300, 0, False, bottom)
    reenter = home(0, playing=True, control_id=2)
    hmi(200, 0, True, reenter, control=2)                       # a new control id pushing: only seeds
    hmi(100, 0, False, reenter, control=2)
    hmi(100, 0, True, reenter, control=2)                       # then fires
    s.op("knobReset")                                           # a pass without a ready control
    hmi(100, 0, True, reenter, control=2)                       # seeds again
    hmi(200, 0, False, reenter, control=2)
    s.op("release").op("knobReset").step(20)
    s.op("claim").op("knobReset").step(20, reenter)
    hmi(200, 0, True, reenter, control=2)                       # after a release and claim: seeds
    seek_end = seek5(297, 300)
    hmi(300, 59, False, dict(seek_end, id=3), control=3, top=59)
    hmi(300, 59, True, dict(seek_end, id=3), control=3, top=59)   # at T_end: the bound at the head
    hmi(300, 59, False, dict(seek_end, id=3), control=3, top=59)
    seek_0 = dict(seek5(0, 300), id=3)
    hmi(200, 0, False, seek_0, control=3, top=59)
    hmi(300, 0, True, seek_0, control=3, top=59)                # at 0:00
    hmi(600, 0, False, seek_0, control=3, top=59)
    return [s]


def sequences():
    return (offline_sequences() + claim_sequences() + sleep_sequences() + turning_sequences()
            + local_cursor_sequences() + feedback_sequences() + play_sequences() + ext_sequences()
            + mode_sequences() + list_sequences() + heat_sequences() + clock_sequences() + song_sequences()
            + release_sequences() + style_sequences() + wrap_sequences() + golden_sequences()
            + moment_sequences() + mode_v5_sequences() + reduced_motion_sequences() + recentre_sequences()
            + hold_sequences() + tuning_sequences() + card_sequences() + loading_sequences() + endstop_sequences()
            + liked_sequences() + seek_pending_sequences())


# ---------------------------------------------------------------- output
def build():
    """{"version", ..., "frames", "cases"}: frames deduplicated and referenced by index."""
    frames, index = [], {}
    cases = {}
    for sequence in sequences():
        assert sequence.name not in cases, sequence.name
        steps = []
        for step in sequence.steps:
            if "frame" in step:
                key = json.dumps(step["frame"], sort_keys=True, separators=(",", ":"))
                if key not in index:
                    index[key] = len(frames)
                    frames.append(step["frame"])
                step = {**step, "frame": index[key]}
            steps.append(step)
        cases[sequence.name] = {"note": sequence.note, "steps": steps}
    return {"version": VERSION, "generator": "app/tests/tools/make_alive_sequences.py",
            "tolerance": TOLERANCE, "byteTolerance": BYTE_TOLERANCE, "eScale": E_SCALE, "frames": frames,
            "cases": cases}


def dumps(data):
    """Deterministic, line-oriented JSON: one frame / one step per line."""
    def one(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    head = ("version", "generator", "tolerance", "byteTolerance", "eScale")
    lines = ["{" + ",".join(f"{one(k)}:{one(data[k])}" for k in head) + ',"frames":[']
    lines.append(",\n".join(one(frame) for frame in data["frames"]) + "],")
    lines.append('"cases":{')
    blocks = []
    for name, case in data["cases"].items():
        body = ",\n".join(one(step) for step in case["steps"])
        blocks.append(f'{one(name)}:{{"note":{one(case["note"])},"steps":[\n{body}]}}')
    lines.append(",\n".join(blocks))
    lines.append("}}")
    return "\n".join(lines) + "\n"


def summary(data):
    steps = [s for case in data["cases"].values() for s in case["steps"]]
    with_bytes = sum(1 for s in steps if "bytes" in s["expect"])
    return (f"{len(data['cases'])} sequence(s), {len(steps)} step(s) ({with_bytes} with output bytes), "
            f"{len(data['frames'])} distinct frame(s)")


def main(argv):
    data = build()
    text = dumps(data)
    if "--check" in argv:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else ""
        if current != text:
            print(f"{OUTPUT} is out of date; run tests/tools/make_alive_sequences.py")
            return 1
        print(f"{OUTPUT} is up to date ({summary(data)})")
        return 0
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT} ({summary(data)}, {len(text.encode('utf-8'))} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
