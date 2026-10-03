"""The app engine (plan sections 3b, 4; S1 lane DD-B): one input grammar and action interpreter for every app profile.

Generalised from Desk Dial's tuned Onshape stack (onshape.py ``KeyTracker`` / ``OnshapeInjector``, onshape_app.py
``OnshapeApp``) and adapted, with his permission, from Karl Malota's (katbinaris) app engine:
katbinaris/NanoD_RatchetH1 ``feat/firmware-esp-idf-quadra`` ``NanoDepsidf/src/app_mode.c`` (the slots, the quick-press
tap, the command wheel and its ring jumps, macros, the command search, parameter mode with number fields and handles,
the axis / plane / uniform constraint taps, their timings). His engine runs on the knob and types over USB HID; here
it runs on the PC and types through SendInput, so the knob only draws.

The profile (``app_profiles.AppProfile``, DD-A's effective model) drives everything:

* **Slots** knob / f1..f4, each with a kind (drag / wheel / keys / tap / commands / none). A slot's physical button is
  ``Slot.button`` (logical 0-3). Hold a button + turn = that slot (the newest held one wins); the knob alone = the
  ``knob`` slot. A press released without a turn before the knob's hold matures fires the slot's ``tap`` (a chord) or
  ``tap_macro``. A ``tap`` kind slot fires its ``cw`` (or ``macro``) on the press itself (Karl's APP_ACT_TAP).
* **The wheel.** Holding the ``commands`` slot's button opens it (``ProfileApp``): turning walks the open ring's entries
  (12 per turn, soft walls at cancel and the last command), another slot's button jumps to the next ring bound to that
  slot, the release runs the entry (0 = cancel). A wheel key with a tap shows the wheel only after 250 ms or the
  first detent, so a quick press is the tap (Onshape's and Plasticity's Undo).
* **Commands:** keys (one chord), actions (the app's search: open chord, open wait, the phrase, result wait, Enter),
  macro (key / text / wait steps). A command disabled on Windows refuses.
* **Parameter mode** after a command with a ``param``: number-field profiles (``param_keys.field``, Onshape) scroll A /
  type B as Desk Dial always has; handle profiles (Plasticity) move the pointer ``px_per_step`` per free click, step
  exactly while F1 / F2 / F4 is held (typed in on confirm through ``param_keys.numeric``), and a tap on F1 / F2 / F4
  cycles the constraint axis X / Y / Z, then its plane (Shift + the axis key), then uniform.
* **Home:** all four buttons held 1.0 s, for every profile (``SlotTracker`` chords; the runtime fires it).

Keys are resolved at send time against the foreground thread's keyboard layout (``keymap.resolve_chord``; the backend's
``resolve_chord``). A chord that layout can't type refuses ("Not on this keyboard") and nothing of its command is sent;
``KEYEVENTF_EXTENDEDKEY`` goes with ``keymap.EXTENDED_VKS`` (and the numpad Enter). Typed text stays Unicode.

Safety (the same rules as Onshape mode, for every app): before every SendInput batch the input desktop must be the
user's (``desktop_ok``; a lock screen or UAC prompt sends nothing and releases everything, reason ``secure_desktop``);
the cursor gate (``target_ok``) and the keyboard-focus gate (``focus_ok``) are the backend's, for the active profile;
every held key and button goes up on every exit path (``release_all`` / ``deactivate``; a profile switch, an app change,
a mode set to Off, a profile reload or an upload failure are deactivations).

Threads: the serial reader only calls ``AppInjector.post`` (a queue put); the injector thread interprets and sends;
the Tk thread activates and reads ``status()`` / ``app_state()``. Nothing here logs a window title, a URL or a host:
logs carry profile ids and exception type names only.
"""
from __future__ import annotations

import logging
import math
import queue
import threading
import time

from . import keymap

_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())

# ------------------------------------------------------------------ tunables (Onshape's, now every app's)
DEFAULT_IDLE_MS = 800                    # settings.json `onshape_idle_ms` (drag idle deadline)
IDLE_MS_RANGE = (200, 5000)
PX_PER_TURN = 760                        # pointer travel per knob turn when a drag slot names none (Karl: ~750)
PX_PER_DETENT = 11                       # PX_PER_TURN / 67 (BINARIS BEER); re-derived per profile
DEFAULT_NOTCHES_PER_TURN = 24            # wheel notches per knob turn (Onshape's tuned zoom) when a slot names none
DEFAULT_STEPS_PER_TURN = 12              # a keys slot's chords per turn when it names no detents (Karl's 12)
DEFAULT_DETENTS_PER_TURN = 67            # BINARIS BEER
WHEEL_DELTA = 120
CHORD_KEYS = 3                           # this many buttons down at once = a chord: no tap, drag or turn
HOME_CHORD_SECONDS = 1.0                 # all four buttons held this long (from the 4th press) = Home
WHEEL_SHOW_S = 0.25                      # APP_WHEEL_SHOW_US
TAP_MAX_S = 0.4                          # APP_TAP_MAX_US
PARAM_CANCEL_S = 0.6                     # APP_PARAM_CANCEL_US
PARAM_AXIS_TAP_S = 0.35                  # APP_PARAM_AXIS_TAP_US
PARAM_TYPE_PAUSE_S = 0.35                # APP_PARAM_TYPE_PAUSE_US
PARAM_NUMERIC_WAIT_S = 0.05              # param_end: numeric entry key, then 5 ticks before the digits
PARAM_SELECT_WAIT_S = 0.02               # B: select-all, then 2 ticks before the digits
MACRO_QUEUE_MAX = 4                      # S3 review DD-8: taps pending behind a running macro, in all (one per slot)
TEXT_SETTLE_S = 0.06                     # S3 decision: browser apps, a chord to the first typed text after it, at least
WHEEL_ENTRIES_PER_TURN = 12
PARAM_STEPS_PER_TURN = 16                # APP_PARAM_STEP_DETENTS
PARAM_FINE_PER_TURN = 48                 # APP_PARAM_FINE_DETENTS
VALUE_MAX_MILLI = 99_999_999
TURN_KINDS = ("drag", "wheel", "keys")   # a held button of these kinds owns the knob's turn
AXIS_SLOTS = ("f1", "f2", "f4")          # parameter mode: X / Y / Z taps (Karl's AXIS_SLOT)

# Results the knob shows (the injector's events; the controller's copy).
REFUSED = "refused"                      # the cursor is not over the app
FOCUS_REFUSED = "focus_refused"          # DD-SEC-001: on the app, but the keyboard focus is elsewhere
KEYBOARD_REFUSED = "keyboard_refused"    # the foreground layout can't type a chord: "Not on this keyboard"
DISABLED_REFUSED = "disabled_refused"    # a command the sidecar turned off on Windows
UNDO = "undo"                            # the wheel key's tap went out (the knob's flash)
REFUSALS = (REFUSED, FOCUS_REFUSED, KEYBOARD_REFUSED, DISABLED_REFUSED)
LIFECYCLE = ("disconnected", "released", "error", "closed")

KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_EXTENDEDKEY = 0x0001
_MOD_VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B}
_NAMED_VK = {"ENTER": 0x0D, "ESCAPE": 0x1B}
MODIFIER_KEYS = (0x10, 0x11, 0x12, 0x5B, 0x5C)


def normal_idle_ms(value):
    if type(value) is not int:
        return DEFAULT_IDLE_MS
    return max(IDLE_MS_RANGE[0], min(IDLE_MS_RANGE[1], value))


def ordered_mods(mods):
    """Modifier names in the canonical press order (ctrl, shift, alt, win)."""
    return tuple(sorted(mods, key=lambda m: keymap.MOD_ORDER.get(m, 9)))


# ------------------------------------------------------------------ events (pure)
def chord_vk(key):
    """A legacy chord key as a virtual key: A-Z and 0-9 are their ASCII codes; ENTER / ESCAPE."""
    if key in _NAMED_VK:
        return _NAMED_VK[key]
    if isinstance(key, str) and len(key) == 1 and ("A" <= key <= "Z" or "0" <= key <= "9"):
        return ord(key)
    raise ValueError(f"no virtual key for {key!r}")


def chord_events(mods, key):
    """One atomic batch: modifiers down, the key down and up, modifiers up (reversed). `key` is a legacy key name
    ("S", "ENTER") or a resolved virtual key (an int); a 4th item True marks an extended key."""
    vks = [_MOD_VK[m] for m in mods]
    if isinstance(key, tuple):
        vk, extended = key
    else:
        vk, extended = chord_vk(key), False
    down, up = (("key", vk, False, True), ("key", vk, True, True)) if extended else (("key", vk, False),
                                                                                      ("key", vk, True))
    mod_down = [("key", m, False, True) if m in keymap.EXTENDED_VKS else ("key", m, False) for m in vks]
    mod_up = [("key", m, True, True) if m in keymap.EXTENDED_VKS else ("key", m, True) for m in reversed(vks)]
    return mod_down + [down, up] + mod_up


def text_events(text):
    """Characters typed as Unicode keystrokes (layout independent: KEYEVENTF_UNICODE)."""
    events = []
    for ch in text:
        events += [("char", ch, False), ("char", ch, True)]
    return events


def scroll_events(notches, mods):
    """A wheel notch batch with modifiers held around it (parameter mode A; a wheel slot with a modifier)."""
    vks = [_MOD_VK[m] for m in mods]
    return ([("key", m, False) for m in vks] + [("wheel", int(notches) * WHEEL_DELTA)]
            + [("key", m, True) for m in reversed(vks)])


_US_PUNCTUATION = {"-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC, ";": 0xBA, "'": 0xDE, "`": 0xC0,
                   ",": 0xBC, ".": 0xBE, "/": 0xBF}


def us_vk_key_scan(char, hkl):
    """VkKeyScanExW on a US layout (the default of a backend that can't read the foreground layout: tests)."""
    return _US_PUNCTUATION.get(char, -1)


# ------------------------------------------------------------------ backends
class ShortSend(OSError):
    """SendInput inserted fewer events than asked (UIPI, a blocked desktop)."""


class NullBackend:
    """No injection (tests, the simulator): records nothing, sends nothing, refuses every target."""
    injects = False

    def cursor(self):
        return (0, 0)

    def target_ok(self, point):
        return False

    def onshape_foreground(self):
        return False

    def swapped(self):
        return False

    def drag_threshold(self):
        return 4

    def modifiers_held(self):
        return False

    def focus_ok(self, point):
        return False

    def focus_fresh(self, point):
        return False

    def foreground(self):
        return None

    def send(self, events):
        return len(events)


# ------------------------------------------------------------------ profile helpers (pure)
def turn_buttons(profile):
    """{logical button: action label} of the slots a held button turns (drag / wheel / keys): the slot's label in
    lower case ("tilt", "orbit", "pan" for Onshape), else its name."""
    out = {}
    for name, slot in profile.slots.items():
        if slot.button is not None and slot.kind in TURN_KINDS:
            out[slot.button] = (slot.label or name).lower()
    return out


def knob_label(profile):
    """The knob-alone action label ("zoom" for Onshape)."""
    knob = profile.slots.get("knob") if profile is not None else None
    return (knob.label or "knob").lower() if knob is not None else "knob"


def slot_of_button(profile, button):
    for slot in profile.slots.values():
        if slot.button == button and slot.kind != "none":
            return slot
    return None


def wheel_button(profile):
    for slot in profile.slots.values():
        if slot.kind == "commands" and slot.button is not None:
            return slot.button
    return None


def px_per_turn(slot):
    """A drag slot's pointer travel per knob turn (whole pixels; Karl's px_per_rad x 2 pi)."""
    if slot is None or not slot.px_per_rad:
        return PX_PER_TURN
    return max(1, round(abs(slot.px_per_rad) * 2 * math.pi))


def _whole(ratio):
    """Whole steps in ``ratio`` toward zero, forgiving float error (DD-BUG-029)."""
    return int(ratio + (1e-9 if ratio > 0 else -1e-9))


def format_value(value, decimals):
    """A typed value: "25.00", "-4.20" (never "-0.00")."""
    text = f"{value:.{decimals}f}"
    return text[1:] if text.startswith("-") and float(text) == 0 else text


def _enter_chord():
    return keymap.Chord(frozenset(), keymap.from_text("enter"))


# ------------------------------------------------------------------ the key grammar (pure)
class SlotTracker:
    """Per logical button 0-3: down, turned while down, hold matured. A turn during a press drops that key's tap and
    its hold. Shared by the controller (what the knob shows, the all-four Home chord) and the injector (drags, taps),
    so both read the same events the same way.

    The chord: once CHORD_KEYS (3) buttons are down together, every button then down (and any pressed while the chord
    lasts) is *chorded* until its own release: no tap, no hold, no turn slot. ``modifiers`` maps the buttons whose
    slot owns the turn to a label (Onshape: tilt / orbit / pan)."""

    MODIFIERS = {}
    DEFAULT_ACTION = "knob"

    def __init__(self, modifiers=None, default=None):
        if modifiers is not None:
            self.MODIFIERS = dict(modifiers)
        if default is not None:
            self.DEFAULT_ACTION = default
        self.clear()

    def clear(self):
        self._down = {}           # slot -> press order
        self._turned = set()
        self._held = set()
        self._chorded = set()
        self._order = 0

    def down(self, slot):
        if slot not in range(4):
            return
        self._order += 1
        self._down[slot] = self._order
        self._turned.discard(slot)
        self._held.discard(slot)
        self._chorded.discard(slot)
        if len(self._down) >= CHORD_KEYS or self._chorded:
            self._chorded.update(self._down)
            self._turned.update(self._down)      # no tap and no hold for any of them

    @property
    def chording(self):
        return bool(self._chorded)

    @property
    def count(self):
        return len(self._down)

    def turn(self):
        self._turned.update(self._down)

    def up(self, slot):
        """'tap' when the press ends without a turn and without a matured hold, else None."""
        if slot not in self._down:
            return None
        del self._down[slot]
        tap = slot not in self._turned and slot not in self._held and slot not in self._chorded
        self._turned.discard(slot)
        self._held.discard(slot)
        self._chorded.discard(slot)
        return "tap" if tap else None

    def hold(self, slot):
        """'hold' for the firmware's `kh` of a press that was not turned (then no tap follows)."""
        if slot not in self._down or slot in self._turned or slot in self._held or slot in self._chorded:
            return None
        self._held.add(slot)
        return "hold"

    def seed(self, mask):
        """`ready.held` (logical mask): a lost release clears its slot (no tap); a press seen only through the mask
        counts as turned (its start is unknown: no tap, no hold)."""
        mask = mask if type(mask) is int else 0
        for slot in list(self._down):
            if not mask & (1 << slot):
                del self._down[slot]
                self._turned.discard(slot)
                self._held.discard(slot)
                self._chorded.discard(slot)
        for slot in range(4):
            if mask & (1 << slot) and slot not in self._down:
                self._order += 1
                self._down[slot] = self._order
                self._turned.add(slot)

    def is_down(self, slot):
        return slot in self._down

    @property
    def mask(self):
        return sum(1 << slot for slot in self._down)

    def modifier_slot(self):
        """The newest held turn button outside a chord, or None (the knob alone)."""
        held = [(order, slot) for slot, order in self._down.items()
                if slot in self.MODIFIERS and slot not in self._chorded]
        return max(held)[1] if held else None

    def action(self):
        slot = self.modifier_slot()
        return self.MODIFIERS[slot] if slot is not None else self.DEFAULT_ACTION


# ------------------------------------------------------------------ the wheel and parameter mode (pure)
class ProfileApp:
    """The wheel / parameter-mode state machine of one profile (one per injector; the injector calls it from its own
    thread and publishes ``snapshot()``). It never sends anything: it returns actions for the injector:
    ``("undo",)`` (the wheel key's tap), ``("chord", Chord)``, ``("text", str)``, ``("wait", seconds)``,
    ``("scroll", notches, mods)``, ``("hover", px)``, ``("refuse", result)``, ``("settle",)``, ``("recheck",)`` (a fresh
    keyboard-focus check before parameter digits; S3 decision). A command run (and
    parameter mode's OK / cancel) is a transaction ending in ``settle``; a refusal or a short send drops the rest and
    calls ``abort()``, which rolls back what was assumed sent."""

    def __init__(self, profile, detents_per_turn=127, clock=time.monotonic):
        self.clock = clock
        self.profile = profile
        self.detents = detents_per_turn if type(detents_per_turn) is int and detents_per_turn > 0 else 127
        self.rings = tuple(profile.rings)
        self.wheel_slot = wheel_button(profile)
        wheel = slot_of_button(profile, self.wheel_slot) if self.wheel_slot is not None else None
        self.wheel_tap = wheel is not None and (wheel.tap is not None or bool(wheel.tap_macro))
        self.ring_buttons = tuple(profile.slots[r.slot].button if r.slot in profile.slots else None
                                  for r in self.rings)
        self.field = bool(profile.param_keys.field)
        buttons = {name: profile.slots[name].button for name in ("f1", "f2", "f4") if name in profile.slots}
        self.step_buttons = (buttons.get("f1"), buttons.get("f2"), buttons.get("f4"))   # fine / mid / coarse
        self.axis_buttons = tuple(buttons.get(name) for name in AXIS_SLOTS)
        self.typed = False                    # B (type) instead of A (scroll); kept across commands
        self.echo_seq = 0
        self.echo = (0, 1)
        self.undo_seq = 0
        self.ring = 0
        self._ring_entry = [0] * len(self.rings)
        self._axis_memo = {}                  # visual -> (axis, plane, uniform): the last constraint per visual
        self._txns = []
        self.reset()

    @classmethod
    def for_profile(cls, profile, detents_per_turn, clock):
        return cls(profile, detents_per_turn, clock=clock)

    # -------------------------------------------------------------- the actions it emits (overridable)
    def _chord(self, chord):
        return ("chord", chord)

    def _scroll(self, steps, mods):
        return ("scroll", steps, mods)

    # -------------------------------------------------------------- state
    def reset(self):
        """Everything open closes (a new control, deactivation, a lost knob); nothing is sent."""
        self.wheel_open = False
        self.wheel_shown = False
        self.entry = 1
        self._open_at = 0.0
        self._engaged = False
        self._accum = 0
        self._down = {}
        self._turned = set()
        self._swallowed = set()
        self._chorded = set()
        self.param = None                      # (ring, index, Param) while parameter mode is on
        self.value = 0.0                       # field A: the change; B and handles: the value
        self.bump = 0
        self.exact = False                     # handles: a step was used (typed in on confirm)
        self.axis, self.plane, self.uniform = 0, False, False
        self._dirty = False
        self._step_at = 0.0
        self._f3_at = None
        self._px_accum = 0.0
        self._txns = []

    def settle(self):
        if not self._txns:
            return
        txn = self._txns.pop(0)
        if txn.get("echo") is not None:
            self._echo(*txn["echo"])

    def abort(self):
        """The injector dropped the pending actions: every pending transaction rolls back, newest first."""
        for txn in reversed(self._txns):
            if txn["kind"] == "retype":
                if self.param is not None:
                    self._dirty = True
                    self._step_at = self.clock()
            elif txn["kind"] == "run":
                ring, entry = txn["ring_entry"]
                if 0 <= ring < len(self._ring_entry):
                    self._ring_entry[ring] = entry
                if txn["param"] is not None and self.param == txn["param"]:
                    self.param = None
                    self.value = 0.0
                    self.bump = 0
                    self._dirty = False
                    self._accum = 0
                    self._f3_at = None
            else:
                self.param = txn["param"]
                self.value = txn["value"]
                self.bump = txn["bump"]
                self._dirty = txn["dirty"]
                self.exact = txn.get("exact", False)
                self._step_at = self.clock()
                self._accum = 0
                self._f3_at = None
        self._txns = []

    @property
    def busy(self):
        """The knob's turn belongs to the wheel or parameter mode (no zoom, no drag)."""
        return self.wheel_open or self.param is not None

    def swallowed(self, slot):
        return slot in self._swallowed or slot in self._chorded

    def chord(self, slot, now=None):
        """`slot` went down with the Home chord on: an open wheel closes unrun, every key now down is chorded."""
        now = self.clock() if now is None else now
        if slot in range(4):
            self._down[slot] = now
        self.wheel_open = self.wheel_shown = False
        self._engaged = False
        self._accum = 0
        self._chorded.update(self._down)
        return []

    def step(self):
        """Parameter mode's live step. Number fields: 0 with F1 held, 2 with F4 held, else 1. Handles: F4 > F2 > F1
        = 2 / 1 / 0, none = -1 (free)."""
        fine, mid, coarse = self.step_buttons
        if self.field:
            if coarse in self._down:
                return 2
            if fine in self._down:
                return 0
            return 1
        if coarse in self._down:
            return 2
        if mid in self._down:
            return 1
        if fine in self._down:
            return 0
        return -1

    def snapshot(self):
        """What the knob shows (the frame's app object minus id / slot / refused): plain data."""
        out = {"flash": self.undo_seq}
        if self.wheel_open and self.wheel_shown:
            out["wheel"] = {"ring": self.ring, "index": self.entry}
        if self.param is not None:
            ring, index, param = self.param
            milli = max(-VALUE_MAX_MILLI, min(VALUE_MAX_MILLI, int(round(self.value * 1000))))
            typed = self.typed if self.field else True
            step = self.step()
            out["param"] = {"ring": ring, "index": index, "mode": "B" if typed else "A", "value": milli,
                            "step": step if step >= 0 else 1}
            if self.bump:
                out["param"]["bump"] = self.bump
            if getattr(param, "axes", False):
                out["param"]["axis"] = 3 if self.uniform else self.axis
                out["param"]["plane"] = bool(self.plane)
        if self.echo_seq:
            out["echo"] = {"ring": self.echo[0], "index": self.echo[1], "seq": self.echo_seq}
        return out

    # -------------------------------------------------------------- events (each returns a list of actions)
    def down(self, slot, now=None):
        now = self.clock() if now is None else now
        if slot not in range(4):
            return []
        self._down[slot] = now
        self._turned.discard(slot)
        if self.param is not None:
            if slot == self.wheel_slot:
                self._f3_at = now
            else:
                self._swallowed.add(slot)          # a step / A-B / axis key; never a drag or Home
            return []
        if self.wheel_open:
            if slot != self.wheel_slot:
                self._swallowed.add(slot)
                self._jump_ring(slot)
            return []
        if slot == self.wheel_slot and self.wheel_slot is not None:
            if any(s in self._down for s in range(4) if s != slot):
                self._swallowed.add(slot)          # the wheel key while another slot is live: nothing
                return []
            if not self.rings:
                return []
            if self.ring >= len(self.rings):
                self.ring = 0
            self.wheel_open = True
            self.wheel_shown = not self.wheel_tap  # a key that also taps waits WHEEL_SHOW_S
            self._open_at = now
            self._engaged = False
            self._accum = 0
            self.entry = self._ring_entry[self.ring] or 1
        return []

    def up(self, slot, now=None):
        now = self.clock() if now is None else now
        pressed = self._down.pop(slot, None)
        turned = slot in self._turned
        self._turned.discard(slot)
        if slot in self._chorded:
            self._chorded.discard(slot)
            self._swallowed.discard(slot)
            if slot == self.wheel_slot:
                self._f3_at = None
            return []
        if slot in self._swallowed:
            self._swallowed.discard(slot)
            if self.param is not None and pressed is not None and not turned and now - pressed < PARAM_AXIS_TAP_S:
                return self._param_tap(slot)
            return []
        if self.param is not None and slot == self.wheel_slot:
            held = now - (self._f3_at if self._f3_at is not None else now)
            self._f3_at = None
            return self._param_end(ok=held < PARAM_CANCEL_S)
        if slot != self.wheel_slot or not self.wheel_open:
            return []
        self.wheel_open = False
        shown = self.wheel_shown
        self.wheel_shown = False
        if not shown:
            # Released before the wheel showed (a wheel key that also taps): a quick press that never turned is the
            # tap (Onshape's and Plasticity's Undo).
            tap = self.wheel_tap and pressed is not None and not turned and now - pressed < TAP_MAX_S + WHEEL_SHOW_S
            if tap:
                self.undo_seq += 1
                return [("undo",)]
            return []
        return self._run(now)

    def seed(self, mask, now=None):
        """`ready.held` after a re-entry: a key whose release was lost is simply up; nothing is sent."""
        mask = mask if type(mask) is int else 0
        for slot in list(self._down):
            if not mask & (1 << slot):
                del self._down[slot]
                self._turned.discard(slot)
                self._swallowed.discard(slot)
                self._chorded.discard(slot)
                if slot == self.wheel_slot:
                    self.wheel_open = self.wheel_shown = False
                    self._f3_at = None
        return []

    def turn(self, delta, now=None):
        """Detents turned. Returns (consumed, actions)."""
        now = self.clock() if now is None else now
        if type(delta) is not int or not delta:
            return self.busy, []
        self._turned.update(self._down)
        if self.param is not None:
            return True, self._param_turn(delta, now)
        if not self.wheel_open:
            return False, []
        if not self.wheel_shown:
            self.wheel_shown = True                # the first detent reveals the wheel; it doesn't move yet
            self._engaged = True
            return True, []
        self._engaged = True
        per = max(1.0, self.detents / WHEEL_ENTRIES_PER_TURN)
        self._accum += delta
        moves = _whole(self._accum / per)
        if moves:
            self._accum -= moves * per             # DD-BUG-029: the exact amount, so 12 a turn
            last = len(self.rings[self.ring].commands)
            entry = max(0, min(last, self.entry + moves))
            if entry != self.entry + moves:
                self._accum = 0                    # at a wall: reversing moves at once
            self.entry = entry
        return True, []

    def tick(self, now=None):
        now = self.clock() if now is None else now
        if self.wheel_open and not self.wheel_shown and now - self._open_at >= WHEEL_SHOW_S:
            self.wheel_shown = True
        if self.param is not None and self.field and self.typed and self._dirty \
                and now - self._step_at >= PARAM_TYPE_PAUSE_S:
            return self._retype()
        return []

    def next_deadline(self):
        times = []
        if self.wheel_open and not self.wheel_shown:
            times.append(self._open_at + WHEEL_SHOW_S)
        if self.param is not None and self.field and self.typed and self._dirty:
            times.append(self._step_at + PARAM_TYPE_PAUSE_S)
        return min(times) if times else None

    # -------------------------------------------------------------- internals
    def command(self, ring, index):
        if not (0 <= ring < len(self.rings)) or not (1 <= index <= len(self.rings[ring].commands)):
            return None
        return self.rings[ring].commands[index - 1]

    def _jump_ring(self, slot):
        """The next ring bound to `slot` after the current one (wrapping)."""
        n = len(self.rings)
        for offset in range(1, n + 1):
            i = (self.ring + offset) % n
            if self.ring_buttons[i] == slot:
                self.ring = i
                self.entry = self._ring_entry[i] or 1
                self._accum = 0
                self._engaged = True
                self.wheel_shown = True
                return

    def command_actions(self, cmd):
        """What running a command sends (the injector adds the gates)."""
        p = self.profile
        if cmd.kind == "actions":
            return [self._chord(p.search), ("wait", p.search_open_ms / 1000.0), ("text", cmd.phrase),
                    ("wait", p.search_result_ms / 1000.0), self._chord(_enter_chord())]
        if cmd.kind == "macro":
            return macro_actions(p, cmd.macro, self._chord)
        return [self._chord(cmd.chord)]

    def _run(self, now):
        cmd = self.command(self.ring, self.entry)
        if cmd is None:
            return []                              # cancel
        if cmd.disabled or (cmd.kind == "keys" and cmd.chord is None) or (cmd.kind == "actions" and
                                                                          self.profile.search is None):
            return [("refuse", DISABLED_REFUSED)]
        txn = {"kind": "run", "ring_entry": (self.ring, self._ring_entry[self.ring]), "param": None, "echo": None}
        self._ring_entry[self.ring] = self.entry
        actions = self.command_actions(cmd)
        if cmd.param is not None:
            self.param = txn["param"] = (self.ring, self.entry, cmd.param)
            self.value = (cmd.param.start if self.typed else 0.0) if self.field else cmd.param.start
            self._accum = 0
            self._dirty = False
            self._f3_at = None
            self.bump = 0
            self.exact = False
            self._px_accum = 0.0
            actions += self._param_start(cmd.param)
        else:
            txn["echo"] = (self.ring, self.entry)  # shown once the command went out (settle)
        self._txns.append(txn)
        return actions + [("settle",)]

    def _echo(self, ring, index):
        self.echo_seq = self.echo_seq % 0x7FFFFFFF + 1
        self.echo = (ring, index)

    def _param_start(self, param):
        """Karl's param_start: the param's enter key, then (axes) the constraint key."""
        out = []
        if param.enter is not None:
            out.append(self._chord(param.enter))
        if param.axes:
            memo = self._axis_memo.get(param.visual)
            if memo is not None:
                self.axis, self.plane, self.uniform = memo
            else:
                uniform = param.axis_default == 3
                self.axis, self.plane, self.uniform = (0 if uniform else param.axis_default), False, uniform
            key = self._constraint_chord()
            if key is not None:
                out.append(self._chord(key))
        return out

    def _constraint_chord(self):
        keys = self.profile.param_keys
        if self.uniform:
            return keys.uniform
        chord = keys.axis[self.axis] if self.axis < len(keys.axis) else None
        if chord is not None and self.plane:
            chord = keymap.Chord(chord.mods | {"shift"}, chord.key)
        return chord

    def _param_tap(self, slot):
        """A quick press of F1 / F2 / F4 in parameter mode: number fields toggle A / B on F2; handles cycle the
        constraint X / Y / Z, then the plane, then uniform."""
        _, _, param = self.param
        if self.field:
            if slot == self.step_buttons[1]:
                self.typed = not self.typed
                self._dirty = False
            return []
        if not param.axes or slot not in self.axis_buttons:
            return []
        axis = self.axis_buttons.index(slot)
        if self.uniform or self.axis != axis:
            self.axis, self.plane, self.uniform = axis, False, False
        elif not self.plane and param.planes:
            self.plane = True
        elif param.uniform:
            self.plane, self.uniform = False, True
        else:
            self.plane = False
        self._axis_memo[param.visual] = (self.axis, self.plane, self.uniform)
        key = self._constraint_chord()
        return [self._chord(key)] if key is not None else []

    def _param_turn(self, delta, now):
        step = self.step()
        fine = step == 0 if self.field else step < 0
        per = max(1.0, self.detents / (PARAM_FINE_PER_TURN if fine else PARAM_STEPS_PER_TURN))
        self._accum += delta
        steps = _whole(self._accum / per)
        if not steps:
            return []
        self._accum -= steps * per                 # DD-BUG-029: exact, so 16 (48 fine) steps a turn at any count
        _, _, param = self.param
        if self.field:
            size = param.steps[step]
            if not self.typed:
                self.value = round(self.value + steps * size, 3)
                keys = self.profile.param_keys
                mods = keys.step_mods[step] if step < len(keys.step_mods) else frozenset()
                return [self._scroll(steps * (keys.scroll_sign or 1), mods)]
            value = round(self.value + steps * size, 3)
            if value < param.min or value > param.max:
                value = max(param.min, min(param.max, value))
                self.bump += 1
                self._accum = 0
            if value != self.value:
                self.value = value
                self._dirty = True
                self._step_at = now
            return []
        if step < 0:                               # free: a fine click each, and the pointer follows the handle
            self._set(self.value + steps * param.free_step)
            self._px_accum += steps * param.px_per_step
            px = int(self._px_accum)
            if px:
                self._px_accum -= px
                return [("hover", px)]
            return []
        size = param.steps[step]
        self.exact = True
        value = self.value
        for _ in range(abs(steps)):
            value = round(round(value / size) * size + (1 if steps > 0 else -1) * size, 6) if size else value
        self._set(value)
        return []

    def _set(self, value):
        _, _, param = self.param
        if value < param.min or value > param.max:
            self.bump += 1
            self._accum = 0
        self.value = max(param.min, min(param.max, value))
        if abs(self.value) < 1e-6:
            self.value = 0.0

    def _retype(self):
        """B: select the field and type the value (a transaction: unsent, it is pending again)."""
        _, _, param = self.param
        self._dirty = False
        self._txns.append({"kind": "retype", "echo": None})
        text = format_value(self.value, param.decimals)
        if param.unit:
            text += " " + param.unit
        select = self.profile.param_keys.select_all
        return [self._chord(select), ("wait", PARAM_SELECT_WAIT_S), ("recheck",), ("text", text), ("settle",)]

    def _param_end(self, ok):
        ring, index, param = self.param
        keys = self.profile.param_keys
        dirty = self._dirty
        actions = []
        if ok and self.field and self.typed and dirty:
            actions += self._retype()              # its transaction first: settle() pops in action order
        if ok and not self.field and self.exact and keys.numeric is not None:
            actions += [self._chord(keys.numeric), ("wait", PARAM_NUMERIC_WAIT_S), ("recheck",),
                        ("text", format_value(self.value, param.decimals))]
        self._txns.append({"kind": "end", "param": self.param, "value": self.value, "bump": self.bump,
                           "dirty": dirty, "exact": self.exact, "echo": (ring, index) if ok else None})
        key = keys.confirm if ok else keys.cancel
        if key is not None:
            actions.append(self._chord(key))
        actions.append(("settle",))
        self.param = None
        self._dirty = False
        self._accum = 0
        self.exact = False
        return actions


def with_text_rechecks(actions, settle):
    """S3 decision: typed text (a macro's text step, a search phrase, parameter digits) that follows a chord within the
    same action gets a fresh keyboard-focus check (``("recheck",)``) right before it: the chord may have moved the
    focus (a browser's address bar, a dialog). ``settle`` (browser apps): the waits from that chord to the text add
    up to at least TEXT_SETTLE_S first (a longer wait of the profile's own stays as it is).

    Parameter digits (B's retype, the numeric entry) carry their own ``("recheck",)`` from ProfileApp and keep their
    tuned waits (20 / 50 ms): settling them would move Onshape's param_mode_b golden by 40 ms, which is the owner's
    call. Such a text keeps the given recheck and gets no settle. Pure."""
    out, chord_seen, gap = [], False, 0.0
    for action in actions:
        kind = action[0]
        if kind == "chord":
            chord_seen, gap = True, 0.0
        elif kind == "wait":
            gap += float(action[1])
        elif kind == "text" and chord_seen and out and out[-1] == ("recheck",):
            pass                                            # rechecked by its producer (parameter digits)
        elif kind == "text" and chord_seen:
            if settle and gap < TEXT_SETTLE_S - 1e-9:
                extra = TEXT_SETTLE_S - gap
                if out and out[-1][0] == "wait":            # one wait, not two (one wake-up)
                    extra += float(out.pop()[1])
                out.append(("wait", round(extra, 6)))
                gap = TEXT_SETTLE_S
            out.append(("recheck",))
        out.append(action)
    return out


def macro_actions(profile, name, chord=lambda c: ("chord", c)):
    """A profile macro as actions: key -> a chord, text -> Unicode text, wait -> a wait."""
    out = []
    for step in profile.macros.get(name, ()) if name else ():
        if step.kind == "key":
            if step.chord is not None:
                out.append(chord(step.chord))
        elif step.kind == "text":
            out.append(("text", step.text or ""))
        else:
            out.append(("wait", step.ms / 1000.0))
    return out


# ------------------------------------------------------------------ the injector
class _Drag:
    __slots__ = ("slot", "button", "buttons", "mods", "origin", "last_at", "root", "vertical", "sign", "px")

    def __init__(self, slot, buttons, mods, origin, last_at, root=None, vertical=False, sign=1, px=1):
        self.slot, self.buttons, self.mods, self.origin, self.last_at = slot, buttons, mods, origin, last_at
        self.button = buttons[0] if buttons else None
        self.root = root               # DD-SEC-003: the foreground window the drag started in
        self.vertical, self.sign, self.px = vertical, sign, px


class AppInjector:
    """The injector thread and its watchdog for one profile at a time. Every public method is safe from any thread and
    only queues; ``step()`` (tests, ``start=False``) runs the queue and the watchdog synchronously."""

    app_class = ProfileApp
    tracker_class = SlotTracker
    thread_name = "NanoD-app"
    logger = _log

    def __init__(self, backend=None, *, clock=time.monotonic, idle_ms=DEFAULT_IDLE_MS, px_per_detent=None,
                 start=True, profile=None):
        self.backend = backend if backend is not None else NullBackend()
        self.clock = clock
        self.idle = normal_idle_ms(idle_ms) / 1000.0
        self._px_auto = px_per_detent is None
        self.px = PX_PER_DETENT if px_per_detent is None else px_per_detent
        self.profile = profile
        self.keys = self._make_tracker(profile)
        self._queue = queue.Queue()
        self._events = queue.Queue()
        self._lock = threading.Lock()
        self._active = None
        self._order = [0, 1, 2, 3]
        self._detents = DEFAULT_DETENTS_PER_TURN
        self._wheel_per_detent = WHEEL_DELTA * DEFAULT_NOTCHES_PER_TURN / DEFAULT_DETENTS_PER_TURN
        self._carry = 0.0
        self._key_accum = 0.0
        self._key_spec = None
        self._drag = None
        self._buttons_down = []
        self._keys_down = []
        self._last_input = None
        self._burst_refused = False
        self._closing = False
        self._exception_logged = False
        self.counts = {"wheel": 0, "drags": 0, "moves": 0, "undo": 0, "undoSkipped": 0, "refusals": 0,
                       "short": 0, "errors": 0, "commands": 0, "commandsSkipped": 0, "scrolls": 0, "typed": 0,
                       "focusRefused": 0}
        # App profiles (DD-B): counters the Onshape-only injector never had (status()["app"]).
        self.app_counts = {"keyboardRefused": 0, "disabledRefused": 0, "secureDesktop": 0, "taps": 0, "keySteps": 0,
                           "macros": 0, "hover": 0, "focusRecheckRefused": 0, "macrosDropped": 0}
        self.app = None
        self._app_state = None
        self._macro = []
        self.releases = {}
        self._thread = None
        if start:
            self._thread = threading.Thread(target=self._run, name=self.thread_name, daemon=True)
            self._thread.start()

    def _make_tracker(self, profile):
        if profile is None:
            return self.tracker_class()
        return self.tracker_class(turn_buttons(profile), knob_label(profile))

    # -------------------------------------------------------------- any thread (enqueue only)
    def post(self, kind, values=None):
        """A knob event from the serial reader (FastPath): queued, never acted on here."""
        self._queue.put(("input", kind, dict(values or {})))

    def activate(self, control_id, button_order=None, detents_per_turn=None, app=False, profile=None):
        """Act for `control_id` with `profile` (None keeps the current one). `app`: the wheel and parameter mode run
        (Onshape: only for a knob that draws the canvas; every other profile always)."""
        self._queue.put(("activate", control_id, list(button_order or (0, 1, 2, 3)), detents_per_turn, bool(app),
                         profile))

    def app_state(self):
        with self._lock:
            return dict(self._app_state) if self._app_state is not None else None

    def deactivate(self, reason="mode"):
        self._queue.put(("deactivate", reason))

    def release_all(self, reason):
        self._queue.put(("release", reason))

    def set_idle_ms(self, value):
        self._queue.put(("idle", normal_idle_ms(value)))

    def take_events(self):
        out = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                return out

    def status(self):
        with self._lock:
            return {"active": self._active is not None, "action": self.keys.action() if self._active else "",
                    "dragging": self._drag is not None, "injects": bool(getattr(self.backend, "injects", True)),
                    "idleMs": int(round(self.idle * 1000)), **self.counts,
                    "releases": dict(self.releases)}

    def app_status(self):
        """status.json `app.injector`: the Onshape counters plus the app-profile ones and the profile id."""
        out = self.status()
        with self._lock:
            out.update(self.app_counts)
            out["profile"] = getattr(self.profile, "id", None) if self._active is not None else None
        return out

    def close(self, timeout=1.0):
        self._queue.put(("close",))
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        elif thread is None:
            self.step()

    # -------------------------------------------------------------- the injector thread
    def _run(self):
        while not self._closing:
            drag = self._drag
            timeout = 0.1 if drag is None else max(0.0, min(0.1, drag.last_at + self.idle - self.clock()))
            due = self._next_due()
            if due is not None:
                timeout = max(0.0, min(timeout, due - self.clock()))
            try:
                item = self._queue.get(timeout=timeout)
            except queue.Empty:
                item = None
            self._guarded(item)

    def step(self):
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            self._guarded(item)
        self._guarded(None)

    def _guarded(self, item):
        try:
            if item is not None:
                self._handle(item)
            self._watchdog(self.clock())
        except Exception as exc:
            with self._lock:
                self.counts["errors"] += 1
            if not self._exception_logged:
                self._exception_logged = True
                # The exception's type and the profile id only (never its text: no title or address reaches a log).
                self.logger.error("App injector failed (%s, profile %s); every held input released",
                                  type(exc).__name__, getattr(self.profile, "id", None))
            try:
                self._release_everything("exception")
            except Exception:
                pass

    def _watchdog(self, now):
        drag = self._drag
        if drag is not None and now - drag.last_at >= self.idle:
            self._end_drag("idle")
        if self._active is not None:
            if self.app is not None:
                self._app_run(self.app.tick(now), now)
            self._macro_step(now)
            if self.app is not None:
                self._publish_app()

    def _handle(self, item):
        kind = item[0]
        if kind == "input":
            self._input(item[1], item[2])
        elif kind == "activate":
            _, control_id, order, detents, app, profile = item
            switched = profile is not None and profile is not self.profile
            if switched and self.profile is not None:
                # A profile switch: everything held goes up and the old profile's state is gone.
                self._release_everything("profile")
                self.app = None
                self._macro = []
            new_session = self._active is None or switched
            if self._active is not None and control_id != self._active and not switched:
                self._end_drag("control")
            with self._lock:
                if switched:
                    self.profile = profile
                    self.keys = self._make_tracker(profile)
                self._active = control_id
                self._order = order if sorted(order) == [0, 1, 2, 3] else [0, 1, 2, 3]
            setter = getattr(self.backend, "set_profile", None)
            if callable(setter):
                setter(self.profile)
            if type(detents) is int and detents > 0:
                self._detents = detents
                self._wheel_per_detent = WHEEL_DELTA * self._notches(self._knob_slot()) / detents
                if self._px_auto:
                    self.px = max(1, round(PX_PER_TURN / detents))
            if app and self.profile is not None:
                if self.app is None:
                    count = detents if type(detents) is int and detents > 0 else DEFAULT_DETENTS_PER_TURN
                    self.app = self.app_class.for_profile(self.profile, count, self.clock)
                else:
                    if new_session:
                        self.app.reset()
                    if type(detents) is int and detents > 0:
                        self.app.detents = detents
                if new_session:
                    self._macro = []
            else:
                self.app = None
            self._publish_app()
        elif kind == "deactivate":
            self._release_everything(item[1])
            with self._lock:
                self._active = None
                self.keys.clear()
            self._app_reset()
        elif kind == "release":
            self._release_everything(item[1])
        elif kind == "idle":
            self.idle = item[1] / 1000.0
        elif kind == "close":
            self._release_everything("shutdown")
            with self._lock:
                self._active = None
            self._closing = True

    # -------------------------------------------------------------- the profile's slots
    def _knob_slot(self):
        return self.profile.slots.get("knob") if self.profile is not None else None

    def _slot(self, button):
        return slot_of_button(self.profile, button) if self.profile is not None else None

    def _turn_button(self, slot):
        return self.keys.MODIFIERS.get(slot) is not None

    @staticmethod
    def _notches(slot):
        if slot is None:
            return DEFAULT_NOTCHES_PER_TURN
        if slot.notches_per_turn:
            return slot.notches_per_turn
        return slot.detents or DEFAULT_NOTCHES_PER_TURN

    def _slot_px(self, slot):
        if not self._px_auto:
            return self.px
        return max(1, round(px_per_turn(slot) / self._detents))

    def _logical(self, raw):
        try:
            return self._order.index(raw)
        except ValueError:
            return None

    def _input(self, kind, values):
        if kind in LIFECYCLE:
            self._release_everything(kind)
            with self._lock:
                self._active = None
                self.keys.clear()
            self._app_reset()
            return
        if self._active is None or values.get("id") != self._active:
            return
        now = self.clock()
        if kind == "ready":
            with self._lock:
                self.keys.seed(values.get("held"))
            if self.app is not None:
                self.app.seed(values.get("held"), now)
                self._publish_app()
            drag = self._drag
            if drag is not None and not self.keys.is_down(drag.slot):
                self._end_drag("ready")
            return
        if kind in ("button", "release", "position"):
            if self._last_input is None or now - self._last_input >= self.idle:
                self._burst_refused = False
            self._last_input = now
        if kind == "button":
            slot = self._logical(values.get("button", values.get("index")))
            if slot is None:
                return
            with self._lock:
                self.keys.down(slot)
            if self.keys.chording:
                if self._drag is not None:
                    self._end_drag("chord")
                if self.app is not None:
                    self.app.chord(slot, now)
                    self._publish_app()
                return
            if self.app is not None:
                self._app_run(self.app.down(slot, now), now)
                self._publish_app()
                if self.app.busy or self.app.swallowed(slot):
                    return
            drag = self._drag
            if drag is not None and self._turn_button(slot) and slot != drag.slot:
                self._end_drag("switch")
            spec = self._slot(slot)
            if spec is not None and spec.kind == "tap":
                self._fire_press(spec, now)
        elif kind == "release":
            slot = self._logical(values.get("button", values.get("index")))
            if slot is None:
                return
            with self._lock:
                tap = self.keys.up(slot)
            drag = self._drag
            if drag is not None and drag.slot == slot:
                self._end_drag("ku")
            spec = self._slot(slot)
            if self.app is not None:
                swallowed = self.app.swallowed(slot)
                self._app_run(self.app.up(slot, now), now)
                self._publish_app()
                if tap and not swallowed and spec is not None and spec.kind not in ("commands", "tap"):
                    self._fire_tap(spec, now)
            elif tap and spec is not None and spec.kind != "tap":
                if spec.kind == "commands":
                    self._undo()
                else:
                    self._fire_tap(spec, now)
        elif kind == "hold":
            slot = values.get("button")
            if type(slot) is int:
                with self._lock:
                    self.keys.hold(slot)
        elif kind == "position":
            delta = values.get("delta")
            if type(delta) is not int or not delta:
                return
            with self._lock:
                self.keys.turn()
            if self.keys.chording:
                self._carry = 0.0
                return
            if self.app is not None:
                consumed, actions = self.app.turn(delta, now)
                if consumed:
                    if self._drag is not None:
                        self._end_drag("wheel")
                    self._app_run(actions, now)
                    self._publish_app()
                    return
            slot = self.keys.modifier_slot()
            if slot is not None and self.app is not None and self.app.swallowed(slot):
                return
            spec = self._knob_slot() if slot is None else self._slot(slot)
            key = "knob" if slot is None else slot
            if self._drag is not None and self._drag.slot != key:
                self._end_drag("modifier" if slot is None else "switch")
            if spec is None:
                return
            if spec.kind == "drag":
                self._drag_turn(key, spec, delta, now)
            elif spec.kind == "wheel":
                self._wheel_turn(spec, delta)
            elif spec.kind == "keys":
                self._keys_turn(spec, delta, now)

    # -------------------------------------------------------------- actions
    def _refuse(self, result=REFUSED):
        """One refusal per burst (the knob says why)."""
        if self._burst_refused:
            return
        self._burst_refused = True
        with self._lock:
            self.counts["refusals"] += 1
            if result == KEYBOARD_REFUSED:
                self.app_counts["keyboardRefused"] += 1
            elif result == DISABLED_REFUSED:
                self.app_counts["disabledRefused"] += 1
        self._events.put(result)

    def _desktop_ok(self):
        """The input desktop is the user's (never a lock screen or a UAC prompt). A backend without the check (test
        fakes) is always on it; a check that fails reads as not."""
        check = getattr(self.backend, "desktop_ok", None)
        if check is None:
            return True
        try:
            return bool(check())
        except Exception:
            return False

    def _send(self, events):
        """One atomic SendInput batch; a short return releases everything this injector holds. Nothing goes out on
        a secure desktop (and everything held goes up)."""
        if not events:
            return True
        if not self._desktop_ok():
            with self._lock:
                self.app_counts["secureDesktop"] += 1
            # What this batch would have pressed was never down: only what earlier batches hold goes up.
            for event in events:
                if event[0] == "down" and event[1] in self._buttons_down:
                    self._buttons_down.remove(event[1])
                elif event[0] == "key" and not event[2] and event[1] in self._keys_down:
                    self._keys_down.remove(event[1])
            if self._drag is not None and any(event[0] == "down" for event in events):
                self._drag = None                      # a drag that never started
            self._release_everything("secure_desktop")
            return False
        try:
            sent = self.backend.send(events)
        except ShortSend:
            sent = -1
        if sent != len(events):
            with self._lock:
                self.counts["short"] += 1
            self._release_everything("short")
            return False
        return True

    def _keys_ok(self):
        """Keystrokes need the cursor over the app AND the keyboard focus inside it (DD-SEC-001)."""
        point = self.backend.cursor()
        if not self.backend.target_ok(point):
            self._refuse()
            return False
        check = getattr(self.backend, "focus_ok", None)
        if check is not None and not check(point):
            with self._lock:
                self.counts["focusRefused"] += 1
            self._refuse(FOCUS_REFUSED)
            return False
        return True

    def _resolve(self, chord):
        """(vk, mods) for a Chord on the foreground layout, or None ("Not on this keyboard")."""
        resolver = getattr(self.backend, "resolve_chord", None)
        try:
            if callable(resolver):
                return resolver(chord)
            return keymap.resolve_chord(chord, None, vk_key_scan=us_vk_key_scan)
        except Exception:
            return None

    def _chord_batch(self, action):
        """The events of a chord action, or None when the layout can't type it."""
        if len(action) == 3:                                        # legacy ("chord", mods, "S")
            return chord_events(action[1], action[2])
        chord = action[1]
        hit = self._resolve(chord)
        if hit is None:
            return None
        vk, mods = hit
        extended = chord.key.extended or vk in keymap.EXTENDED_VKS
        return chord_events(ordered_mods(mods), (vk, extended))

    def _wheel_turn(self, spec, delta):
        """The wheel slot (Onshape's zoom): fractional notches per detent, the rest carried; modifiers around it."""
        if not self.backend.target_ok(self.backend.cursor()):
            self._carry = 0.0
            self._refuse()
            return
        per = self._wheel_per_detent if spec is self._knob_slot() else \
            WHEEL_DELTA * self._notches(spec) / self._detents
        self._carry += delta * per * (spec.sign or 1)
        notch = int(self._carry)
        if not notch:
            return
        self._carry -= notch
        mods = ordered_mods(spec.wheel_mods)
        if mods and self.backend.modifiers_held():
            with self._lock:
                self.counts["commandsSkipped"] += 1
            return
        events = [("wheel", notch)] if not mods else (
            [("key", _MOD_VK[m], False) for m in mods] + [("wheel", notch)]
            + [("key", _MOD_VK[m], True) for m in reversed(mods)])
        if mods:
            self._keys_down = [_MOD_VK[m] for m in mods]
        if self._send(events):
            self._keys_down = []
            with self._lock:
                self.counts["wheel"] += 1

    def _keys_turn(self, spec, delta, now):
        """A keys slot: its cw / ccw chord per step (spec.detents steps per turn, Karl's 12 by default)."""
        steps_per_turn = spec.detents or DEFAULT_STEPS_PER_TURN
        per = max(1.0, self._detents / steps_per_turn)
        if spec is not self._key_spec:
            self._key_spec, self._key_accum = spec, 0.0     # another keys slot: its own count
        self._key_accum += delta
        steps = _whole(self._key_accum / per)
        if not steps:
            return
        self._key_accum -= steps * per
        chord = spec.cw if steps > 0 else spec.ccw
        if chord is None:
            return
        actions = [("chord", chord)] * abs(steps)
        if self._perform_checked(actions, now, tag=("slot", id(spec))):
            with self._lock:
                self.app_counts["keySteps"] += abs(steps)

    def _fire_press(self, spec, now):
        """A `tap` kind slot fires its cw (or macro) on the press (Karl's APP_ACT_TAP)."""
        if spec.macro:
            actions = macro_actions(self.profile, spec.macro)
        elif spec.cw is not None:
            actions = [("chord", spec.cw)]
        else:
            return
        if self._perform_checked(actions, now, tag=("slot", id(spec))):
            with self._lock:
                self.app_counts["taps"] += 1

    def _fire_tap(self, spec, now):
        """A slot's quick press (released without a turn before its hold): its tap chord or tap macro."""
        if spec.tap_macro:
            actions = macro_actions(self.profile, spec.tap_macro)
        elif spec.tap is not None:
            actions = [("chord", spec.tap)]
        else:
            return
        if self._perform_checked(actions, now, tag=("slot", id(spec))):
            with self._lock:
                self.app_counts["taps"] += 1

    def _perform_checked(self, actions, now, tag=("slot", None)):
        """Runs actions through the same gates as a command (queued behind a running macro). True when it started.
        DD-8: behind a running macro at most one entry per ``tag`` (a slot) waits, and MACRO_QUEUE_MAX in all; an extra
        one is dropped and counted (``macrosDropped``)."""
        if not actions:
            return False
        actions = self._rechecked(actions)
        if self._macro:
            pending = [entry[2] for entry in self._macro if entry[2] is not None]
            if tag in pending or len(pending) >= MACRO_QUEUE_MAX:
                with self._lock:
                    self.app_counts["macrosDropped"] += 1
                return False
            self._macro.append((self._macro[-1][0], list(actions), tag))
            return True
        if not self._preflight(actions):
            return False
        self._perform(list(actions), now)
        return True

    def _physical(self, button):
        if button in ("left", "right") and self.backend.swapped():
            return "left" if button == "right" else "right"
        return button

    def _foreground(self):
        read = getattr(self.backend, "foreground", None)
        return read() if read is not None else None

    def _drag_turn(self, key, spec, delta, now):
        drag = self._drag
        if drag is not None and drag.slot != key:
            self._end_drag("switch")
            drag = None
        if drag is not None and drag.root is not None and self._foreground() != drag.root:
            self._end_drag("foreground")          # DD-SEC-003: no relative move ever lands in another window
            return
        if drag is None:
            origin = self.backend.cursor()
            if not self.backend.target_ok(origin):
                self._refuse()
                return
            buttons = [self._physical(b) for b in ("left", "right", "middle") if b in spec.drag_buttons]
            mods = ordered_mods(spec.drag_mods)
            step = max(1, int(self.backend.drag_threshold())) + 1
            x, y = origin
            vertical = bool(spec.axis_y)
            # Pressed on the first detent; the out-and-back step clears the drag threshold with no net movement, so
            # the app sees a drag (never a click: no context menu, no tab close).
            mod_vks = [_MOD_VK[m] for m in mods]
            self._buttons_down.extend(buttons)            # before the send: a short return releases them (and mods)
            drag = self._drag = _Drag(key, buttons, mod_vks, origin, now, self._foreground(), vertical,
                                      spec.sign or 1, self._slot_px(spec))
            out = ("move", x, y + step) if vertical else ("move", x + step, y)
            events = [("key", vk, False) for vk in mod_vks] + [("down", b) for b in buttons] + [out, ("move", x, y)]
            if not self._send(events):
                return
            with self._lock:
                self.counts["drags"] += 1
        x, y = self.backend.cursor()
        travel = delta * drag.px * drag.sign
        move = ("move", x, y + travel) if drag.vertical else ("move", x + travel, y)
        if self._send([move]):
            drag.last_at = now
            with self._lock:
                self.counts["moves"] += 1

    def _end_drag(self, reason):
        drag = self._drag
        if drag is None:
            return
        self._drag = None
        held = [b for b in drag.buttons if b in self._buttons_down]
        events = [("up", b) for b in held]
        events += [("key", vk, True) for vk in reversed(drag.mods)]
        events.append(("move",) + tuple(drag.origin))     # the cursor goes back once the button is up
        try:
            sent = self.backend.send(events)
        except ShortSend:
            sent = -1
        if sent == len(events):
            for b in held:
                self._buttons_down.remove(b)
        else:
            with self._lock:
                self.counts["short"] += 1
            self._release_everything("short")
        self._count_release(reason)

    def _undo(self):
        """The wheel key's tap (Onshape's and Plasticity's Undo): its tap chord, or its tap macro."""
        spec = self._slot(wheel_button(self.profile)) if self.profile is not None else None
        if spec is not None and spec.tap_macro:
            if self._perform_checked(macro_actions(self.profile, spec.tap_macro), self.clock(),
                                     tag=("slot", id(spec))):
                with self._lock:
                    self.counts["undo"] += 1
                self._events.put(UNDO)
            return
        chord = spec.tap if spec is not None else None
        if chord is None:
            return
        if self._blocked(chord):
            self._refuse(DISABLED_REFUSED)
            return
        if not self._keys_ok():
            return
        if self.backend.modifiers_held():
            with self._lock:
                self.counts["undoSkipped"] += 1   # Ctrl+Z with a real Shift / Alt / Win held is another shortcut
            return
        events = self._chord_batch(("chord", chord))
        if events is None:
            self._refuse(KEYBOARD_REFUSED)
            return
        self._keys_down = [e[1] for e in events if not e[2]]
        if self._send(events):
            self._keys_down = []
            with self._lock:
                self.counts["undo"] += 1
            self._events.put(UNDO)

    # -------------------------------------------------------------- the wheel, parameter mode and macros
    def _app_reset(self):
        if self.app is not None:
            self.app.reset()
        self._macro = []
        self._publish_app()

    def _publish_app(self):
        app = self.app
        state = None
        if app is not None and self._active is not None:
            state = app.snapshot()
            state["flash"] = self.counts["undo"]
        with self._lock:
            self._app_state = state

    def _next_due(self):
        times = [entry[0] for entry in self._macro[:1]]
        app = self.app
        if app is not None:
            deadline = app.next_deadline()
            if deadline is not None:
                times.append(deadline)
        return min(times) if times else None

    def _app_run(self, actions, now):
        """The app's actions: queued behind a pending macro (tool search waits), else run now."""
        if not actions:
            return
        actions = self._rechecked(actions)
        if self._macro:
            # The app's own runs (wheel commands, parameter mode) are transactions: queued, never dropped.
            self._macro.append((self._macro[-1][0], list(actions), "app"))
            return
        if not self._preflight(actions):
            self._drop()
            return
        self._perform(list(actions), now)

    def _preflight(self, actions):
        """Every chord of a command resolves on the foreground layout before anything of it is sent: one that
        doesn't refuses the whole command ("Not on this keyboard"). A chord that leaves the app (``_blocked``)
        refuses it too ("Not on Windows")."""
        for action in actions:
            if action[0] == "chord" and len(action) == 2 and self._blocked(action[1]):
                self._refuse(DISABLED_REFUSED)
                return False
            if action[0] == "chord" and len(action) == 2 and self._resolve(action[1]) is None:
                self._refuse(KEYBOARD_REFUSED)
                return False
        return True

    def _browser(self):
        """The active profile has website rules (a browser app)."""
        return bool(getattr(getattr(self.profile, "detect", None), "host", ()))

    def _rechecked(self, actions):
        return with_text_rechecks(actions, settle=self._browser())

    def _focus_fresh(self):
        """S3 decision: the keyboard focus, read now (never the 0.25 s cache): a browser app's page document must hold
        it (not the address bar), a desktop app's process must own the focus window. A backend without the fresh
        check (test fakes) answers with its focus_ok; any failure reads as not."""
        check = getattr(self.backend, "focus_fresh", None) or getattr(self.backend, "focus_ok", None)
        if check is None:
            return True
        try:
            return bool(check(self.backend.cursor()))
        except Exception:
            return False

    def _blocked(self, chord):
        """S3 review DD-1: ``keymap.blocked`` (a website profile also keeps the browser's tab keys out). The loader
        already refuses such a profile; this keeps a chord that reached the engine anyway from going out."""
        detect = getattr(self.profile, "detect", None)
        try:
            return keymap.blocked(chord, browser=bool(getattr(detect, "host", ()))) is not None
        except Exception:
            return True

    def _macro_step(self, now):
        while self._macro and self._macro[0][0] <= now:
            actions = self._macro.pop(0)[1]
            self._perform(actions, now)
            if self._macro and self._macro[0][0] > now:
                break

    def _drop(self):
        self._macro = []
        if self.app is not None:
            self.app.abort()

    def _perform(self, actions, now):
        """Runs actions until a wait, which schedules the rest. Keys need the cursor over the app and the keyboard
        focus in it; a refusal drops the rest of the list and rolls the app back (``_drop``)."""
        while actions:
            action = actions.pop(0)
            kind = action[0]
            if kind == "wait":
                later = now + float(action[1])
                self._macro.insert(0, (later, actions, None))     # running (no longer pending)
                return
            if kind == "settle":
                if self.app is not None:
                    self.app.settle()
                continue
            if kind == "undo":
                self._undo()
                continue
            if kind == "refuse":
                self._refuse(action[1])
                self._drop()
                return
            if kind == "recheck":
                if not self._focus_fresh():
                    # The chord before this text moved the focus: refuse ("Click the app first"), send nothing more.
                    with self._lock:
                        self.counts["focusRefused"] += 1
                        self.app_counts["focusRecheckRefused"] += 1
                    self._refuse(FOCUS_REFUSED)
                    self._drop()
                    self._release_everything("focus_recheck")
                    return
                continue
            keyed = kind in ("chord", "text") or (kind == "scroll" and bool(action[2]))
            if not (self._keys_ok() if keyed else self.backend.target_ok(self.backend.cursor())):
                if not keyed:
                    self._refuse()
                self._drop()
                return
            if kind in ("chord", "text", "scroll") and self.backend.modifiers_held():
                # A real Ctrl / Shift / Alt / Win held would make another shortcut of a chord, Ctrl+wheel zoom the
                # page of a plain notch and shortcuts of typed text: nothing goes out.
                with self._lock:
                    self.counts["commandsSkipped"] += 1
                self._drop()
                return
            if kind == "chord":
                if len(action) == 2 and self._blocked(action[1]):
                    self._refuse(DISABLED_REFUSED)
                    self._drop()
                    return
                events = self._chord_batch(action)
                if events is None:
                    self._refuse(KEYBOARD_REFUSED)
                    self._drop()
                    return
                self._keys_down = [e[1] for e in events if not e[2]]
                if not self._send(events):
                    self._drop()
                    return
                self._keys_down = []
                with self._lock:
                    self.counts["commands"] += 1
            elif kind == "text":
                if not self._send(text_events(action[1])):
                    self._drop()
                    return
                with self._lock:
                    self.counts["typed"] += 1
            elif kind == "scroll":
                events = scroll_events(action[1], ordered_mods(action[2]) if not isinstance(action[2], tuple)
                                       else action[2])
                self._keys_down = [e[1] for e in events if e[0] == "key" and not e[2]]
                if not self._send(events):
                    self._drop()
                    return
                self._keys_down = []
                with self._lock:
                    self.counts["scrolls"] += 1
            elif kind == "hover":
                x, y = self.backend.cursor()
                if not self._send([("move", x + int(action[1]), y)]):
                    self._drop()
                    return
                with self._lock:
                    self.app_counts["hover"] += 1

    def _release_everything(self, reason):
        """Every button and key this injector holds goes up (best effort), the drag's cursor comes back, the carries
        are dropped."""
        drag, self._drag = self._drag, None
        events = [("up", button) for button in self._buttons_down]
        events += [("key", vk, True) for vk in reversed(self._keys_down)]
        if drag is not None:
            events += [("key", vk, True) for vk in reversed(drag.mods)]
            events.append(("move",) + tuple(drag.origin))
        self._buttons_down = []
        self._keys_down = []
        self._carry = 0.0
        self._key_accum = 0.0
        if events:
            try:
                self.backend.send(events)
            except Exception:
                pass
            self._count_release(reason)

    def _count_release(self, reason):
        with self._lock:
            self.releases[reason] = self.releases.get(reason, 0) + 1

