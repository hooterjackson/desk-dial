"""Onshape command wheel and parameter mode (A2; ONSHAPE.md sections 10-13): the pure state machine.

Adapted from katbinaris/NanoD_RatchetH1 feat/firmware-esp-idf-quadra (Karl Malota), with permission:
NanoDepsidf/src/app_mode.c (the wheel, parameter mode and their timings) and app_profiles/onshape.c (the rings,
commands, parameter steps). His macOS shortcuts are translated for Windows: Ctrl for Cmd, Alt for Option; the
tool search is Alt+C (Onshape's "Keyboard shortcuts" page). Desk Dial drives the input; the knob only draws
(the frame's `app` object, device.app_parse / firmware cc_frame_parse.cpp).

Buttons are the logical slots 0-3 (buttons 1-4, left to right):

* **Wheel.** Pressing 3 opens it (hidden; not while 1, 2 or 4 is held: tilting, orbiting, panning). It shows after 250 ms (``WHEEL_SHOW_S``) or at the first detent
  (which only reveals it). Turning moves one entry per ``DETENTS_PER_ENTRY_TURN`` of a turn (12 entries per turn,
  as Karl's 12-detent wheel), clamped at cancel (entry 0) and the last command: soft walls, no wrap. While it is
  open, 1 steps MODEL <-> MODIFY, 2 opens SKETCH, 4 VIEW (those keys then do nothing else until released).
  Releasing 3 runs the entry (0 = close). Released before the wheel showed (and never turned) it is a tap: Undo.
  The wheel reopens on the entry last run in that ring, so hold-and-release repeats it (Karl's design).
* **Parameter mode.** After EXTRUDE, FILLET, CHAMFER, SHELL, TRANSFORM or MOVE FACE the knob sets the dialog's
  number: one step per 1/16 turn (1/48 turn for the fine step) - 0.01 with 1 held, 0.1 alone, 1.0 with 4 held.
  A (scroll, the default): each step is one wheel notch over the field under the cursor, Ctrl / none / Shift
  held (Onshape's numeric-field increments); the knob shows the change. B (type): the value is held here (from
  the command's start value, clamped to its range) and typed over the field (Ctrl+A, the digits) once the knob
  rests 350 ms; the knob shows the value. A tap on 2 switches A <-> B (remembered). Tap 3 = OK (Enter, after a
  pending retype), 3 held 600 ms or more then released = cancel (Esc).
* **Echo.** A command that ran (or a parameter confirmed) bumps ``echo_seq``; the knob replays its card 1.1 s.
* **The Home chord.** Three or more buttons down together (Desk Dial's Home is all four held 1.0 s): ``chord()``
  closes an open wheel without running it; every key down then does nothing until its own release (no ring
  switch, step, A/B tap, OK or cancel). Parameter mode itself stays open.

``OnshapeApp`` never sends anything: it returns actions for the injector (``control_center.onshape``), which
checks the target and calls SendInput:
``("undo",)``, ``("chord", mods, key)``, ``("text", str)``, ``("wait", seconds)``, ``("scroll", notches, mods)``,
``("settle",)``. A command run (and parameter mode's OK / cancel) is a transaction: its list ends in ``settle``,
which the injector reaches only when every action before it went out (``settle()``: the echo shows). A refusal, a
chord skipped for a held real modifier or a short send drops the rest of the list and calls ``abort()``: parameter
mode, the ring's remembered entry and the echo go back to what they were, so nothing later types into the wrong
place.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from . import keymap
from .app_engine import ProfileApp, format_value, ordered_mods, _whole  # noqa: F401  (re-exported for the tests)

WHEEL_SHOW_S = 0.25            # APP_WHEEL_SHOW_US: a wheel key that also taps shows the wheel after this
TAP_MAX_S = 0.4                # APP_TAP_MAX_US: released within this without a turn = a tap
PARAM_CANCEL_S = 0.6           # APP_PARAM_CANCEL_US: button 3 held this long in parameter mode = cancel
PARAM_AXIS_TAP_S = 0.35        # APP_PARAM_AXIS_TAP_US: button 2 released within this = the A/B tap
PARAM_TYPE_PAUSE_S = 0.35      # APP_PARAM_TYPE_PAUSE_US: B retypes once the knob rests this long
WHEEL_ENTRIES_PER_TURN = 12    # Karl's wheel slot: 12 detents per turn, one entry each
PARAM_STEPS_PER_TURN = 16      # APP_PARAM_STEP_DETENTS
PARAM_FINE_PER_TURN = 48       # APP_PARAM_FINE_DETENTS (the 0.01 step)
SEARCH_OPEN_S = 0.25           # onshape.c search {Opt+C, 25, 40}: 10 ms ticks
SEARCH_RESULT_S = 0.40
VALUE_MAX_MILLI = 99_999_999   # the frame's param.value bound (thousandths)

CTRL, SHIFT, ALT = "ctrl", "shift", "alt"
SEARCH_CHORD = ((ALT,), "C")   # Onshape tool search on Windows (Option+C on macOS)
UNDO_CHORD = ((CTRL,), "Z")
SELECT_ALL = ((CTRL,), "A")
STEP_MODIFIERS = ((CTRL,), (), (SHIFT,))   # A: the notch modifier of step 0 / 1 / 2 (0.01 / 0.1 / 1.0)
STEP_SIZES = (0.01, 0.10, 1.00)


@dataclass(frozen=True)
class Param:
    label: str
    start: float
    minimum: float
    maximum: float
    decimals: int = 2
    steps: tuple = STEP_SIZES
    unit: str = "mm"               # B types it after the number, so an inch document still gets the metric value

    # app_profiles.Param's names (the engine reads either).
    @property
    def min(self):
        return self.minimum

    @property
    def max(self):
        return self.maximum


@dataclass(frozen=True)
class Command:
    name: str
    mods: tuple = ()               # the Windows chord's modifiers
    key: str | None = None         # its key; None = tool search with `phrase`
    phrase: str | None = None
    param: Param | None = None

    @property
    def search(self):
        return self.key is None

    def display_chord(self):
        """The chord as cc_app_onshape.c spells it after the name and the search flag (tests)."""
        if self.search:
            return "0, NULL"
        mods = {SHIFT: "SHIFT", CTRL: "APP_MOD_CTRL", ALT: "APP_MOD_ALT"}
        spelled = " | ".join(mods[m] for m in self.mods) if self.mods else "0"
        return f'{spelled}, "{self.key}"'

    def actions(self):
        """What running it sends (the injector adds the target check)."""
        if self.search:
            mods, key = SEARCH_CHORD
            return [("chord", mods, key), ("wait", SEARCH_OPEN_S), ("text", self.phrase), ("wait", SEARCH_RESULT_S),
                    ("chord", (), "ENTER")]
        return [("chord", self.mods, self.key)]


@dataclass(frozen=True)
class Ring:
    name: str
    slot: int                      # the logical slot that jumps here while the wheel is open
    commands: tuple = field(default_factory=tuple)


# Onshape's rings (Karl's onshape.c), Windows chords. Parameter starts and ranges are his, in millimetres: B types
# the unit with the value ("25.10 mm"), so a document set to inches still gets 25.1 mm, not 25.1 in.
_P_EXTRUDE = Param("DEPTH", 25.0, 0.0, 1000.0)
_P_FILLET = Param("RADIUS", 1.0, 0.0, 100.0)
_P_CHAMFER = Param("DISTANCE", 1.0, 0.0, 100.0)
_P_SHELL = Param("THICKNESS", 1.0, 0.01, 100.0)
_P_MOVE_FACE = Param("DISTANCE", 0.0, -1000.0, 1000.0)
_P_TRANSFORM = Param("DISTANCE", 0.0, -1000.0, 1000.0)
RINGS = (
    Ring("MODEL", 0, (Command("SKETCH", (SHIFT,), "S"), Command("EXTRUDE", (SHIFT,), "E", param=_P_EXTRUDE),
                      Command("REVOLVE", (SHIFT,), "W"), Command("FILLET", (SHIFT,), "F", param=_P_FILLET),
                      Command("CHAMFER", phrase="chamfer", param=_P_CHAMFER),
                      Command("SHELL", phrase="shell", param=_P_SHELL))),
    Ring("MODIFY", 0, (Command("BOOLEAN", phrase="boolean"), Command("SPLIT", phrase="split"),
                       Command("TRANSFORM", phrase="transform", param=_P_TRANSFORM),
                       Command("PATTERN", phrase="linear pattern"), Command("MIRROR", phrase="mirror"),
                       Command("MOVE FACE", phrase="move face", param=_P_MOVE_FACE))),
    Ring("SKETCH", 1, (Command("LINE", (), "L"), Command("RECTANGLE", (), "G"), Command("CIRCLE", (), "C"),
                       Command("ARC", (), "A"), Command("DIMENSION", (), "D"), Command("TRIM", (), "M"),
                       Command("CONSTRUCTION", (), "Q"))),
    Ring("VIEW", 3, (Command("FRONT", (SHIFT,), "1"), Command("RIGHT", (SHIFT,), "4"), Command("TOP", (SHIFT,), "5"),
                     Command("ISOMETRIC", (SHIFT,), "7"), Command("NORMAL TO", (), "N"),
                     Command("ZOOM TO FIT", (), "F"), Command("SECTION", (SHIFT,), "X"))),
)
WHEEL_SLOT = 2                     # button 3


def command(ring, index):
    """Entry `index` (1..count) of ring `ring`, or None (cancel / out of range)."""
    if not (0 <= ring < len(RINGS)) or not (1 <= index <= len(RINGS[ring].commands)):
        return None
    return RINGS[ring].commands[index - 1]


class OnshapeApp(ProfileApp):
    """The wheel / parameter-mode state machine with Onshape's built-in profile (app_engine.ProfileApp; one per
    injector). Its actions keep the A2 spelling the tests and the goldens were written against: ``("chord", mods,
    key)`` with Onshape's key names ("S", "ENTER", "ESCAPE") and ``("scroll", notches, mods)`` with a mods tuple."""

    def __init__(self, detents_per_turn=127, clock=time.monotonic, profile=None):
        super().__init__(profile if profile is not None else builtin_onshape_profile(), detents_per_turn, clock=clock)

    @classmethod
    def for_profile(cls, profile, detents_per_turn, clock):
        return cls(detents_per_turn, clock=clock, profile=profile)

    def _chord(self, chord):
        label = chord.key.label
        return ("chord", ordered_mods(chord.mods), {"ESC": "ESCAPE"}.get(label, label))

    def _scroll(self, steps, mods):
        return ("scroll", steps, ordered_mods(mods))


_BUILTIN = {}


def builtin_onshape_profile():
    """Onshape's tuned layout (ONSHAPE.md sections 1, 5, 13, 15, 16) as an app_profiles.AppProfile built from this
    module's constants: the knob zooms (24 notches a turn on BINARIS BEER), hold 1 / 2 / 4 + turn tilt / orbit / pan
    (760 px a turn), tap 3 is Ctrl+Z, hold 3 the wheel of RINGS, the tool search Alt+C. It equals the bundled
    profiles/onshape.json + onshape.windows.json on everything the engine reads (tests/test_app_engine.py), so the
    injector works without the profile files. Built once per RINGS table (a test may patch it)."""
    if id(RINGS) in _BUILTIN:
        return _BUILTIN[id(RINGS)][1]
    from . import app_profiles as ap
    from .onshape import CONTENT_CLASSES, NOT_ONSHAPE_HOSTS, ZOOM_NOTCHES_PER_TURN, PX_PER_TURN, TILT_DRAG_SIGN

    def chord(mods, key):
        return keymap.Chord(frozenset(mods), keymap.from_text({"ENTER": "enter", "ESCAPE": "esc"}.get(key, key)))

    px_per_rad = PX_PER_TURN / (2 * math.pi)

    def slot(name, kind, label, button, **extra):
        base = dict(name=name, kind=kind, label=label, button=button, drag_buttons=frozenset(), drag_mods=frozenset(),
                    axis_y=False, px_per_rad=0.0, sign=1, wheel_mods=frozenset(), notches_per_turn=None, cw=None,
                    ccw=None, tap=None, macro=None, tap_macro=None, fx="none", feel=None, detents=None, haptic="saw")
        base.update(extra)
        return ap.Slot(**base)

    slots = {
        "knob": slot("knob", "wheel", "ZOOM", None, notches_per_turn=float(ZOOM_NOTCHES_PER_TURN), fx="zoom",
                     feel="BINARIS BEER", detents=67),
        "f1": slot("f1", "drag", "TILT", 0, drag_buttons=frozenset({"right"}), axis_y=True, px_per_rad=px_per_rad,
                   sign=TILT_DRAG_SIGN, fx="orbit", haptic="viscose"),
        "f2": slot("f2", "drag", "ORBIT", 1, drag_buttons=frozenset({"right"}), px_per_rad=px_per_rad, fx="orbit",
                   haptic="viscose"),
        "f3": slot("f3", "commands", "UNDO", WHEEL_SLOT, tap=chord(*UNDO_CHORD), fx="flash", sign=0),
        "f4": slot("f4", "drag", "PAN", 3, drag_buttons=frozenset({"middle"}), px_per_rad=px_per_rad, fx="pan",
                   haptic="viscose"),
    }
    names = {0: "f1", 1: "f2", 3: "f4"}
    rings = []
    for ring in RINGS:
        commands = []
        for cmd in ring.commands:
            param = None
            if cmd.param is not None:
                p = cmd.param
                param = ap.Param(label=p.label, label_neg=None, steps=tuple(p.steps), free_step=0.0, px_per_step=0.0,
                                 start=p.start, min=p.minimum, max=p.maximum, decimals=p.decimals, deg=False,
                                 axes=False, planes=False, uniform=False, visual="none", modes=0, enter=None,
                                 axis_default=0, unit=p.unit)
            commands.append(ap.Command(cmd.name, "actions" if cmd.search else "keys",
                                       None if cmd.search else chord(cmd.mods, cmd.key), cmd.phrase, None, None, param,
                                       False, None))
        rings.append(ap.Ring(ring.name, ring.name, names[ring.slot], tuple(commands)))
    keys = ap.ParamKeys(numeric=None, confirm=chord((), "ENTER"), cancel=chord((), "ESCAPE"), axis=(None, None, None),
                        uniform=None, field=True, step_mods=tuple(frozenset(m) for m in STEP_MODIFIERS), scroll_sign=1,
                        select_all=chord(*SELECT_ALL))
    profile = ap.AppProfile(
        id="onshape", name="ONSHAPE", status="tested", source="bundled", karl_sha256="",
        detect=ap.Detect(host=("cad.onshape.com", "*.onshape.com"), exclude_host=tuple(sorted(NOT_ONSHAPE_HOSTS)),
                         content_class=tuple(CONTENT_CLASSES)),
        slots=slots, rings=tuple(rings), macros={}, search=chord(*SEARCH_CHORD),
        search_open_ms=round(SEARCH_OPEN_S * 1000), search_result_ms=round(SEARCH_RESULT_S * 1000),
        param_keys=keys, home_chord=True, raw_karl={}, raw_overlay={}, legend=("TILT", "ORBIT", "WHEEL", "PAN"))
    _BUILTIN[id(RINGS)] = (RINGS, profile)        # the table is kept, so its id is never reused
    return profile
