"""Contract-exact cc5 LED model: PRESENTATION_V4.md section 5 in integer math.

This module is the Python mirror of firmware ``src/cc_lights.cpp``. Both sides
must produce bit-identical logical colours, so every formula below uses only
integer operations that C++11 reproduces exactly. Each one is written out in a
``C++:`` comment for the port to copy. Conventions:

* A colour is ``0xRRGGBB``. A ring cell is ``(rgb, level)``; off is ``(0, 0)``.
* Logical segment 0 is twelve o'clock, increasing clockwise. The physical
  reflection/orientation stays in firmware ``address()`` and is not modelled.
* ``put(i, c, l)`` OVERWRITES ``ring[i mod 60]`` (never max-combines). The
  draw order is marks, body, endpoint/cursor, pending override, flash.
* Drive colour per channel is ``(c * level + 127) / 255``, computed before the
  firmware's global FastLED brightness cap (51). ``i mod 60`` for a possibly
  negative ``i`` is ``((i % 60) + 60) % 60`` in C++ (Python ``%`` already is).
* Time is ``uint32`` milliseconds. Every elapsed time is ``(now - start)``
  modulo 2**32 (``& 0xFFFFFFFF`` here; plain ``uint32_t`` subtraction in C++),
  so ``millis()`` wrap is harmless.

Choices where section 5 is silent (the C++ port must make the same ones):

* Pulse onsets: "pending" = activity pending on a selection/transport ring
  (the only styles that pulse); "loading" = activity loading on a selection
  ring. Each onset is taken on the rising edge of its condition.
* Transport pending on Neutral (index 1) pulses segment 0; on Prev it pulses
  52/53 even when Prev is unavailable (the model does the same).
* A ring the parser would reject (selection index >= count, transport count
  != 3) draws nothing, cursor 0. An invalid present ``first`` is normalised
  like the host adapter (derived window, relative colours/mask dropped).
* The More double landmark is drawn whenever moreIndex >= 0.
* The press highlight is applied after the button fade, to enabled buttons
  with an icon (tones nav/go/stop): ``blend(shown, 0xFFFFFF, 36)``.
* A button icon outside ``presentation.ICONS`` (or a non-string) is ``""``
  (tone none), exactly as ``device._buttons`` normalises it before sending;
  the firmware parser never sees one (it would reject the frame).
* The flash expires on the first render with ``now - start >= duration``.
* The ring decay and the button fade each carry an "animating" flag that is
  cleared when they finish, so a 2**32 ms ``millis()`` wrap can never replay
  an old transition (elapsed time is only read while the flag is set).

Public API (kept for existing importers):

* ``ring_target(frame, pending_ms, loading_ms, flash)`` -> (60 cells, cursor)
* ``ring_pixels(frame, now_ms=0, flash=None)``: stateless drive colours; the
  pulse phases are anchored at 0, i.e. ``now_ms`` is the time since onset.
* ``button_ink`` / ``button_light`` / ``button_pixels(frame, pressed=0)``
* ``PreviewLights().render(frame, control_id, now_ms, pressed=0)`` -> (ring60, buttons4)
"""
from __future__ import annotations

from .presentation import (
    BUTTON_FADE_MS, DECAY_MS, EASE_LUT, FLASH_ERR_MS, FLASH_OK_MS, ICONS, L0, L1, L2, L3, L4,
    LED_AMBER, LED_GREEN, LED_RED, LED_VOLUME_RED, LED_WHITE, LEVEL_SHOULDER, LEVELS,
    LIST_PITCH, PENDING_HOLD_MS, PULSE_MS, RING_SEGMENTS, RING_WINDOW, TRACKS_NEUTRAL,
    TRACKS_NEXT, TRACKS_PREV, VOLUME_END, VOLUME_START, button_tone, window_first,
)

# Palette aliases kept for existing importers (ui.py, tests, work/*). WARM and
# COOL were cc4 warm/cool whites; in cc5 every white is the LED palette W.
WHITE = WARM = COOL = LED_WHITE
GREEN = LED_GREEN
RED = LED_RED
AMBER = LED_AMBER
VOLUME_RED = LED_VOLUME_RED
OFF = (0, 0)
UINT32 = 0xFFFFFFFF
PRESS_BLEND = 36          # cc4 press highlight: blend(drive, W, 36) while held
FASTLED_CAP = 51          # firmware global brightness ceiling (setBrightness)

# Section 5.9: tone -> (colour, level). "none" is dark.
TONE_LIGHT = {"none": (0, L0), "dim": (WHITE, L1), "stop": (RED, L2),
              "go": (GREEN, L3), "nav": (WHITE, L2)}
PRESSABLE_TONES = ("nav", "go", "stop")


# --------------------------------------------------------------------- colour
def _ch(color, shift):
    return (color >> shift) & 255


def rgb(r, g, b):
    return (r << 16) | (g << 8) | b


def scale(color, amount):
    """Drive colour: per channel (c * amount + 127) / 255, amount clamped to 0..255.

    C++: ch = (uint32_t)(c * amount + 127) / 255   // c, amount <= 255: fits uint16
    """
    amount = min(255, max(0, int(amount)))
    return rgb(*((_ch(color, s) * amount + 127) // 255 for s in (16, 8, 0)))


def blend(a, b, amount):
    """cc4 blend, used only for the press highlight.

    C++: ch = (a * (255 - amount) + b * amount + 127) / 255
    """
    return rgb(*(((_ch(a, s) * (255 - amount) + _ch(b, s) * amount + 127) // 255)
                 for s in (16, 8, 0)))


def cell_drive(cell):
    """Drive colour of one (rgb, level) cell."""
    return scale(cell[0], cell[1])


def peak(color):
    """Peak channel, the damping comparison key (section 5.7)."""
    return max(_ch(color, 16), _ch(color, 8), _ch(color, 0))


def _cdiv(numerator, denominator):
    """C/C++ integer division: truncates toward zero (Python // floors)."""
    q = abs(numerator) // denominator
    return -q if numerator < 0 else q


def ease(elapsed, duration):
    """easeOutQuint LUT value 0..255 at elapsed/duration (section 5.7).

    t is split into 1/16 steps with linear interpolation between LUT entries:
    C++: if (elapsed >= duration) return 255;
         x = elapsed * 16; i = x / duration; r = x % duration;
         return LUT[i] + (LUT[i + 1] - LUT[i]) * r / duration;  // LUT non-decreasing
    """
    if elapsed >= duration:
        return 255
    x = elapsed * 16
    i, r = x // duration, x % duration
    return EASE_LUT[i] + (EASE_LUT[i + 1] - EASE_LUT[i]) * r // duration


def toward(frm, to, e):
    """Per channel ``from + (to - from) * e / 255`` with C integer division.

    C++: int d = (int)to_ch - (int)from_ch; ch = from_ch + d * (int)e / 255;
    (C++11 signed division truncates toward zero; e = 255 gives exactly ``to``.)
    """
    return rgb(*(_ch(frm, s) + _cdiv((_ch(to, s) - _ch(frm, s)) * e, 255) for s in (16, 8, 0)))


def post_cap(color, cap=FASTLED_CAP):
    """Approximate post-cap LED drive without dithering: per channel c * cap / 255 (floor).

    Diagnostic only (FastLED's setBrightness + scale8 is roughly this; its
    temporal dithering spreads the remainder across frames).
    """
    return rgb(*((_ch(color, s) * cap) // 255 for s in (16, 8, 0)))


# --------------------------------------------------------------------- pulses
def pending_level(elapsed_ms):
    """Section 5.6 pending pulse: L3 on even 260 ms phases, L1 on odd, L1 after 3 s.

    C++: if (elapsed >= 3000) return L1; return ((elapsed / 260) & 1) ? L1 : L3;
    """
    elapsed_ms &= UINT32
    if elapsed_ms >= PENDING_HOLD_MS:
        return L1
    return L1 if (elapsed_ms // PULSE_MS) & 1 else L3


def loading_level(elapsed_ms):
    """Section 5.6 loading pulse: L2 on even phases, L1 on odd, no hold.

    C++: return ((elapsed / 260) & 1) ? L1 : L2;
    """
    return L1 if ((elapsed_ms & UINT32) // PULSE_MS) & 1 else L2


# --------------------------------------------------------------- frame access
def _int(value, lo, hi, default):
    return value if type(value) is int and lo <= value <= hi else default


def _ring_window(ring, index, count):
    """(first, width, colors, mask) exactly as device._ring normalises them (section 4).

    width = min(20, count - first) is the number of transmitted entries.

    A present, valid ``first`` is used. Otherwise first = window_first(index, count)
    (= 0 when count <= 20, else clamp(index-9, 0, count-20)) and colours/mask are
    kept only when they were relative to that same first (an absent first whose
    derived value is 0, rules.absentFirst). A too-long colour list, an out-of-range
    colour or mask bits beyond the window drop that field (all white / all available).
    """
    derived = window_first(index, count)
    raw_first = ring.get("first")
    if "first" in ring and type(raw_first) is int and 0 <= raw_first <= index < raw_first + RING_WINDOW \
            and (count > RING_WINDOW or raw_first == 0):
        first, relative = raw_first, True
    else:
        first, relative = derived, "first" not in ring and derived == 0
    width = max(0, min(RING_WINDOW, count - first))
    colors = ring.get("colors") if relative else None
    if not (isinstance(colors, list) and len(colors) <= width
            and all(type(c) is int and 0 <= c <= 0xFFFFFF for c in colors)):
        colors = []
    mask = _int(ring.get("unavailable", 0), 0, (1 << width) - 1, 0) if relative else 0
    return first, width, colors, mask


# --------------------------------------------------------------- ring target
def ring_target(frame, pending_ms=0, loading_ms=0, flash=None):
    """Pure target builder: (60 cells of (rgb, level), cursor) for one frame.

    ``pending_ms``/``loading_ms`` are the elapsed times since the pending/loading
    onset (section 5.6); ``flash`` is None, "ok" or "err" (section 5.8, drawn last).
    """
    cells = [OFF] * RING_SEGMENTS

    def put(i, color, level):
        cells[i % RING_SEGMENTS] = (color, level)   # C++: ring[((i % 60) + 60) % 60]

    ring = frame.get("ring") if isinstance(frame.get("ring"), dict) else {}
    style, activity = ring.get("style"), frame.get("activity", "idle")
    color_mode = frame.get("ledStyle") == "color"
    cursor = 0
    if style == "level":
        cursor = _draw_volume(put, frame, ring, activity, color_mode)
    elif style == "selection":
        cursor = _draw_list(put, frame, ring, activity, color_mode, pending_ms, loading_ms)
    elif style == "transport":
        cursor = _draw_transport(put, ring, activity, pending_ms)
    # style "off" (or anything unknown): all dark, cursor 0 (section 5.5).
    if flash in ("ok", "err"):
        color, level = (GREEN, L4) if flash == "ok" else (RED, L3)
        for d in (-1, 0, 1):
            put(cursor + d, color, level)
    return cells, cursor


def volume_color(k, color_mode):
    """volc(k): W, or in colour mode VRED from k >= 45, AMBER from k >= 40 (section 5.2)."""
    if not color_mode:
        return WHITE
    return VOLUME_RED if k >= 45 else AMBER if k >= 40 else WHITE


def _draw_volume(put, frame, ring, activity, color_mode):
    """Section 5.2. n = (v+1)/2 is JS Math.round(v/2) for 0..100; vseg(x) = (35 + (x+1)/2) mod 60."""
    v = _int(ring.get("value"), 0, 100, 0)
    c = _int(frame.get("confirmedVolume", v), 0, 100, v)
    n, nc = (v + 1) // 2, (c + 1) // 2
    if activity == "offline":                       # Home offline: confirmed endpoint only.
        put(VOLUME_START + nc, WHITE, L1)
        return (VOLUME_START + nc) % RING_SEGMENTS
    put(VOLUME_START, WHITE, L1)                    # 1. bound marks (35 then 25)
    put(VOLUME_END, WHITE, L1)
    for k in range(n + 1):                          # 2. body; span above confirmed is L1
        put(VOLUME_START + k, volume_color(k, color_mode), L2 if k <= nc else L1)
    for k in range(n + 1, nc + 1):                  # 3. pending decrease span
        put(VOLUME_START + k, volume_color(k, color_mode), L1)
    if v & 1 and n >= 1:                            # 4. odd-v shoulder (deviation 1)
        put(VOLUME_START + n - 1, volume_color(n - 1, color_mode), LEVEL_SHOULDER)
    put(VOLUME_START + n, volume_color(n, color_mode),   # 5. endpoint
        L4 if ring.get("external") is True else L3)
    return (VOLUME_START + n) % RING_SEGMENTS


def _draw_list(put, frame, ring, activity, color_mode, pending_ms, loading_ms):
    """Section 5.3 (Recent and Windows)."""
    if activity == "loading":                       # only segment 0, nothing else
        put(0, WHITE, loading_level(loading_ms))
        return 0
    count = _int(ring.get("count"), 0, 65535, 0)
    index = _int(ring.get("index"), 0, 65535, 0)
    if not index < count:                           # parsers reject this; draw nothing
        return 0
    first, width, colors, mask = _ring_window(ring, index, count)
    more = _int(ring.get("moreIndex", -1), -1, count - 1, -1)
    c0 = (count - 1) // 2

    def slot(j):                                    # C++: (((j - c0) * 3) % 60 + 60) % 60
        return ((j - c0) * LIST_PITCH) % RING_SEGMENTS

    def accent(j):
        k = j - first
        if not color_mode or j == more or not 0 <= k < len(colors) or not colors[k]:
            return WHITE
        return colors[k]

    def unavailable(j):
        k = j - first
        return 0 <= k < width and (mask >> k) & 1

    for j in range(first, first + width):           # 1. landmarks; unavailable = gap
        if not unavailable(j):
            put(slot(j), accent(j), L1)
    if more >= 0:                                   # 2. More double landmark
        put(slot(more) + 1, WHITE, L1)
    cursor = slot(index)
    if index == more:
        put(cursor, WHITE, L3)
        put(cursor + 1, WHITE, L3)
    elif unavailable(index):
        windows = frame.get("mode") == "WINDOWS" or frame.get("layout") == "windows"
        put(cursor, accent(index) if windows else WHITE, L2)
    else:
        put(cursor, accent(index), L3)
    if activity == "pending":                       # white pulse (deviations 3, 4)
        put(cursor, WHITE, pending_level(pending_ms))
    return cursor


def _draw_transport(put, ring, activity, pending_ms):
    """Section 5.4 (always white). index 0 Prev, 1 Neutral, 2 Next; mask bit0 = no Prev."""
    if _int(ring.get("count"), 0, 65535, 0) != 3:
        return 0
    index = _int(ring.get("index"), 0, 2, -1)
    if index < 0:
        return 0
    no_prev = bool(_int(ring.get("unavailable", 0), 0, 7, 0) & 1)
    if not no_prev:
        for i in TRACKS_PREV:
            put(i, WHITE, L1)
    put(TRACKS_NEUTRAL, WHITE, L1)
    for i in TRACKS_NEXT:
        put(i, WHITE, L1)
    if index == 0:
        pair, cursor = TRACKS_PREV, TRACKS_PREV[0]
        if not no_prev:
            for i in pair:
                put(i, WHITE, L3)
    elif index == 2:
        pair, cursor = TRACKS_NEXT, TRACKS_NEXT[1]
        for i in pair:
            put(i, WHITE, L3)
    else:
        pair, cursor = (TRACKS_NEUTRAL,), TRACKS_NEUTRAL
        put(TRACKS_NEUTRAL, WHITE, L2)
    if activity == "pending":                       # the selected pair pulses
        level = pending_level(pending_ms)
        for i in pair:
            put(i, WHITE, level)
    return cursor


def ring_pixels(frame, now_ms=0, flash=None):
    """Stateless 60 drive colours; pulse phases anchored at 0 (``now_ms`` = time since onset)."""
    cells, _ = ring_target(frame, now_ms, now_ms, flash)
    return [cell_drive(cell) for cell in cells]


# -------------------------------------------------------------------- buttons
def _tone(frame, index):
    """Section 5.9 tone of button ``index``.

    The icon is normalised exactly like ``device._buttons`` does before a frame
    is sent: anything that is not a string in ``presentation.ICONS`` becomes
    ``""`` (tone none), so the preview never lights a button the knob leaves dark.
    C++: cc_button_tone(frame, slot) (the parser only stores ICONS tokens).
    """
    buttons = frame.get("buttons") or []
    if not 0 <= index < len(buttons) or not isinstance(buttons[index], dict):
        return "none"
    button = buttons[index]
    icon = button.get("icon")
    if not isinstance(icon, str) or icon not in ICONS:
        icon = ""
    return button_tone(index, icon, button.get("enabled") is True)


def button_light(frame, index):
    """(colour, level) of button ``index`` from the section 5.9 tone table."""
    return TONE_LIGHT[_tone(frame, index)]


def button_ink(frame, index):
    """LED colour of presentation.button_tone: go G, stop R, nav/dim W, none 0."""
    return button_light(frame, index)[0]


def button_targets(frame):
    """Four drive colours (colour x level, pre-cap), no press highlight."""
    return [cell_drive(button_light(frame, i)) for i in range(4)]


def _pressable(frame, index):
    return _tone(frame, index) in PRESSABLE_TONES


def _press(frame, pixels, pressed):
    """cc4 press highlight on enabled buttons: blend(shown, W, 36) while held."""
    return [blend(color, WHITE, PRESS_BLEND) if pressed & (1 << i) and _pressable(frame, i) else color
            for i, color in enumerate(pixels)]


def button_pixels(frame, pressed=0):
    """Four drive colours (pre-cap) with the cc4 press highlight."""
    return _press(frame, button_targets(frame), pressed)


# ------------------------------------------------------------------- stateful
class PreviewLights:
    """Section 5.6-5.8 state machine: onsets, damping, button fade and flash.

    One instance per renderer. ``reset()`` (also run by the constructor) is the
    firmware's renderer reset (the unclaimed->claimed transition): the next frame
    snaps every LED to its target and seeds lastSeq without flashing.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self._snap = True
        self._shown = [0] * RING_SEGMENTS      # last output (drive colours)
        self._from = [0] * RING_SEGMENTS
        self._to = [0] * RING_SEGMENTS
        self._start = [0] * RING_SEGMENTS
        self._decaying = [False] * RING_SEGMENTS
        self._button_shown = [0] * 4
        self._button_from = [0] * 4
        self._button_to = [0] * 4
        self._button_start = [0] * 4
        self._button_fading = [False] * 4
        self._seeded = False
        self.last_seq = 0                      # 0 = none (seq is 1..0x7FFFFFFF)
        self.flash = None                      # active flash kind
        self._flash_start = 0
        self._pending_on = self._loading_on = False
        self._pending_start = self._loading_start = 0
        self.cursor = 0

    def _feedback(self, frame, now):
        """Section 5.8: seq != lastSeq flashes regardless of control id or layout."""
        feedback = frame.get("feedback")
        valid = (isinstance(feedback, dict) and feedback.get("kind") in ("ok", "err")
                 and _int(feedback.get("seq"), 1, 0x7FFFFFFF, 0))
        if not self._seeded:                   # first frame after reset: seed, never flash
            self._seeded = True
            if valid:
                self.last_seq = feedback["seq"]
        elif valid and feedback["seq"] != self.last_seq:
            self.last_seq = feedback["seq"]
            self.flash, self._flash_start = feedback["kind"], now
        if self.flash is not None:
            duration = FLASH_OK_MS if self.flash == "ok" else FLASH_ERR_MS
            if (now - self._flash_start) & UINT32 >= duration:   # C++: now - start >= dur
                self.flash = None
        return self.flash

    def _onsets(self, frame, now):
        """Section 5.6: each onset resets when its condition starts (rising edge).

        pending = activity "pending" on a selection/transport ring (the only
        styles that pulse); loading = activity "loading" on a selection ring.
        """
        ring = frame.get("ring") if isinstance(frame.get("ring"), dict) else {}
        style, activity = ring.get("style"), frame.get("activity", "idle")
        pending = activity == "pending" and style in ("selection", "transport")
        loading = activity == "loading" and style == "selection"
        if pending and not self._pending_on:
            self._pending_start = now
        if loading and not self._loading_on:
            self._loading_start = now
        self._pending_on, self._loading_on = pending, loading
        return ((now - self._pending_start) & UINT32 if pending else 0,
                (now - self._loading_start) & UINT32 if loading else 0)

    def _damp(self, i, target, now):
        """Section 5.7 per segment: instant rise, 260 ms LUT decay from the shown colour.

        C++ (per segment, on every render):
          if (target != to[i]) {
            if (peak(target) >= peak(shown[i])) { from[i] = to[i] = shown[i] = target; decaying[i] = false; }
            else { from[i] = shown[i]; to[i] = target; start[i] = now; decaying[i] = true; }
          }
          if (decaying[i]) {
            uint32_t el = now - start[i];
            if (el >= 260) { shown[i] = to[i]; decaying[i] = false; }
            else shown[i] = toward(from[i], to[i], ease(el, 260));
          }
        """
        if target != self._to[i]:
            if peak(target) >= peak(self._shown[i]):
                self._from[i] = self._to[i] = self._shown[i] = target
                self._decaying[i] = False
            else:
                self._from[i], self._to[i], self._start[i] = self._shown[i], target, now
                self._decaying[i] = True
        if self._decaying[i]:
            elapsed = (now - self._start[i]) & UINT32
            if elapsed >= DECAY_MS:
                self._shown[i], self._decaying[i] = self._to[i], False
            else:
                self._shown[i] = toward(self._from[i], self._to[i], ease(elapsed, DECAY_MS))
        return self._shown[i]

    def _fade(self, i, target, now):
        """Section 5.7 buttons: fade from the shown colour to a new target over 220 ms.

        The ``fading`` flag makes this wrap safe: once a fade has finished, the
        elapsed time is never read again, so ``now`` coming back around 2**32 ms
        later cannot replay it.

        C++: if (target != to[i]) { from[i] = shown[i]; to[i] = target; start[i] = now; fading[i] = true; }
             if (fading[i]) {
               uint32_t el = now - start[i];
               if (el >= 220) { shown[i] = to[i]; fading[i] = false; }
               else shown[i] = toward(from[i], to[i], ease(el, 220));
             }
        """
        if target != self._button_to[i]:
            self._button_from[i], self._button_to[i], self._button_start[i] = self._button_shown[i], target, now
            self._button_fading[i] = True
        if self._button_fading[i]:
            elapsed = (now - self._button_start[i]) & UINT32
            if elapsed >= BUTTON_FADE_MS:
                self._button_shown[i], self._button_fading[i] = self._button_to[i], False
            else:
                self._button_shown[i] = toward(self._button_from[i], self._button_to[i],
                                               ease(elapsed, BUTTON_FADE_MS))
        return self._button_shown[i]

    def render(self, frame, control_id=None, now_ms=0, pressed=0):
        """Return (60 logical ring drive colours, 4 button drive colours), pre-cap.

        ``control_id`` is accepted for API compatibility; by contract nothing here
        depends on it (flashes trigger regardless of control id).
        """
        now = int(now_ms) & UINT32
        flash = self._feedback(frame, now)
        pending_ms, loading_ms = self._onsets(frame, now)
        cells, self.cursor = ring_target(frame, pending_ms, loading_ms, flash)
        targets = [cell_drive(cell) for cell in cells]
        buttons = button_targets(frame)
        if self._snap:                          # renderer reset: everything snaps
            self._snap = False
            self._shown, self._from, self._to = targets[:], targets[:], targets[:]
            self._decaying = [False] * RING_SEGMENTS
            self._button_shown, self._button_from, self._button_to = buttons[:], buttons[:], buttons[:]
            self._button_start = [now] * 4
            self._button_fading = [False] * 4
            ring = targets[:]
            shown_buttons = buttons[:]
        else:
            ring = [self._damp(i, t, now) for i, t in enumerate(targets)]
            shown_buttons = [self._fade(i, t, now) for i, t in enumerate(buttons)]
        return ring, _press(frame, shown_buttons, pressed)


__all__ = [
    "WHITE", "WARM", "COOL", "GREEN", "RED", "AMBER", "VOLUME_RED", "LEVELS", "TONE_LIGHT",
    "scale", "blend", "peak", "ease", "toward", "post_cap", "cell_drive",
    "pending_level", "loading_level", "volume_color", "ring_target", "ring_pixels",
    "button_light", "button_ink", "button_targets", "button_pixels", "PreviewLights",
]
