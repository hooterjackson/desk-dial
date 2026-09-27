"""alive: the "Warm · alive" LED engine (ALIVE.md revision 2), Python twin of firmware src/cc_alive.h/.cpp.

Contract: firmware/ALIVE.md revision 2 (K2; it wins over the designs). Design references:
design-reference/design_handoff_led_choreography/ (RC: ``draw()``/``detect()``/``play()`` in
"Ring Choreography v2.dc.html", ``finishAlive()`` in knob-model.js) and the r2.1 master
design_handoff_nano_d_master_r2.1/prototypes/"Browse and Snap.dc.html" (BS: ``draw()`` BS:597-695,
``play()`` BS:578-586, the ring and button targets of ``renderVals()`` BS:1232-1333).

Three layers, each testable on its own (section 4):

1. **Targets** ``alive_targets(frame, local_pos, local_max, ...)``: pure. Revision 2 draws the alive
   geometry directly (5.1: the volume arc with the M13 half-step and the M2 value gate, the
   re-centred 20-entry window M9 / M15, lists with only their items' colours M3, Up next M14, the
   Seek lap, Tracks), the alpha table (5.2, classes P / 1 / Q / 2 / N / S / 3 / 4), the External /
   Flash / Offline overrides, the button tones (5.3, M18) and the flags (5.4).
   ``alive_geometry`` + ``alive_finish`` are its two halves (the engine needs ``pending`` before it
   knows whether the knob rests).
2. **Animator** ``AliveAnimator``: damping, effect queue (cap 8, D12), continuous layers and
   composition; a verbatim port of RC ``draw()`` plus BS ``draw()``'s new and changed recipes (the
   colour ``bloom``, ``half``, ``scatter``, the stationary ``fail``) and BS ``play()``'s reduced-motion
   drop (6.5). ``run_oracle_case`` replays both oracles (tests/fixtures/alive_oracle.json, RC,
   11.1; tests/fixtures/alive_oracle_bs.json, BS, 11.2).
3. **Output** (transfer, drive, power limit, quantisation) is C++ only; ``srgb_eotf`` and the
   dither-off ``reference_output`` are here for tests (the twin replay's and the oracles' byte
   checks). [user 2026-09-26] Dither is off by default (``DEFAULT_DITHER``), and dither off applies
   the F-T brightness floor to the LEDs whose target is lit (``lit_masks``; section 9 step 4, 12.7).
   The desktop still draws ``e`` (10.3): the floor is the knob's output stage only.

``AliveLights`` owns the layers and the event detection (section 6), with the section 4 API in
snake_case. Float64 throughout; times are uint32 ms and every elapsed time is
``(now - start) & 0xFFFFFFFF``. Periodic phases use integer modulo (D11).

Readings where the contract is silent, identical to firmware ``CCAlive`` (cc_alive.cpp):

* ``claim``/``release`` act immediately: ``release`` plays ``down`` at its own ``now`` with the
  snapshot of the last rendered state, at the last claimed cursor. ``detent``/``limit``/``press``
  queue while claimed (8 / 4 / 8 per render; a ninth detent merges into the eighth).
* ``render`` first applies the state changes: the pending onset, geometry, feedback (the flash of
  rows a, b, i, j or the moment hold of rows c-h, 6.4), the EXT edge, the song latch, the flash and
  hold expiry (also without a frame: both windows are time-based); then each queued input's
  deadline (its own ``now`` + 5000; presses, then detents, then limits), EXT (render ``now`` +
  3200), and the sleep timer; then ``effectiveAsleep`` and the targets; then effects at the
  render's ``now`` in the order boot, presses, wake, ticks, bounds, MODE, feedback, PLAY/PAUSE,
  EXT.
* A new feedback seq replaces the running flash and moment hold: a flash row starts its flash
  (and ends a running hold), a moment row starts its hold and ends a running flash (M7: "no flash
  for a feedback that carries a moment"), ``unlike`` ends both.
* Velocity is computed per detent in queue order at its own time; the first detent after
  ``reset``/``claim`` has no previous rotation (velocity 0). Every detent of one render ticks at the
  render's cursor; ``dir`` compares it with the previous rendered cursor (``sign(delta)`` on the
  first frame after claim or when the cursor did not move). Tick length [D19].
* The queue evicts (section 7 order) right before appending, after the reduced-motion drop, the FG
  kill and the same-type replacement.
* ``volRed`` is set for every target whose final role is RED.
* ``tint`` uses the cursor target after the overrides and needs its role to be ACCENT [R2].
* Song hand [R3]: a Home frame's ``playing`` is the latch; a missing ``playing`` counts as not
  playing. ``clock``/``progress``/``reducedMotion``/tuning survive release/claim (``reset`` clears
  them; K1 resets ``reducedMotion`` at the claim through the latch, not the engine).
* ``render`` while claimed without a frame draws nothing (no events; boot waits for a frame).
* On layout ``upnext`` the engine ignores ``ring.unavailable`` (both parsers strip it there, K1
  §4.4 / P5-R24; 5.1.4): every Up next entry is available, whatever an unparsed frame says.
* Palette [R5]: the section 2 float constants, identical to the firmware's ``CCAliveSpec``; accents
  stay 8-bit (sat() is integer by definition). PINK follows ``set_tuning`` (section 2).
"""
from __future__ import annotations

import math

from .presentation import (
    FLASH_ERR_MS, FLASH_OK_MS, ICONS, LEGACY_LAYOUT, PENDING_HOLD_MS, PULSE_MS, RING_SEGMENTS,
    RING_WINDOW,
)

UINT32 = 0xFFFFFFFF
TAU = math.pi * 2
SEGMENTS = RING_SEGMENTS
BUTTON_SLOTS = 4

# --------------------------------------------------------------- palette (section 2, R5)
# Design space, 0..1 per channel, before the section 9 transfer. WARM and AMBER are the sRGB OETF
# (the exact inverse of the section 9 EOTF) of the LED colours the user picked on the hardware on
# 2026-09-25, c = LED/255: c <= 0.0031308 ? 12.92 c : 1.055 c^(1/2.4) - 0.055. Stored as floats
# (>= 6 significant digits, the firmware's CCAliveSpec values), never as rounded 8-bit ints and
# never re-derived at run time. At drive 255 with dither off, section 9 maps WARM to #FF8424 and
# AMBER to #FF3A0A exactly.
WARM = (1.0, 0.746862, 0.411645)        # [user][D1] fixed all day: LED #FF8424
HOT = (1.0, 0.746862, 0.411645)         # [user 2026-09-26] == WARM (was mix(WARM, white, 0.5))
GREEN = (0.0, 1.0, 98 / 255)            # confirm
RED = (1.0, 0.0, 0.0)                   # [user][D2] volume >= 90 %, Cancel, Fail: #FF0000
AMBER = (1.0, 0.514232, 0.218649)       # [user][D2] volume 80-90 %, offline marks: #FF3A0A
BLUE = (40 / 255, 140 / 255, 1.0)       # changed elsewhere
# [r2][M25] PINK: the liked heart and the Like bloom; its own role, never sat() (R:100; S01:106; the
# candidate 255,40,90, section 14 Q2). LED output at full ~ #FF051A.
PINK = (1.0, 40 / 255, 90 / 255)
WHITE_F = (1.0, 1.0, 1.0)

ROLE_WARM, ROLE_ACCENT = "warm", "accent"
ROLE_GREEN, ROLE_RED, ROLE_AMBER, ROLE_BLUE = "green", "red", "amber", "blue"
ROLE_PINK = "pink"                      # [r2] CCAliveRole 7
# The palette roles' colours (floats); an ACCENT carries its own sat() colour (8-bit ints). WARM and
# PINK are drawn from the animator's palette (the oracle injects the design's WARM; set_tuning
# changes the engine's PINK).
ROLE_COLOUR = {ROLE_WARM: WARM, ROLE_GREEN: GREEN, ROLE_RED: RED, ROLE_AMBER: AMBER, ROLE_BLUE: BLUE,
               ROLE_PINK: PINK}

# ----------------------------------------------------------------- levels (section 5.2)
CLASS_S = "S"                               # odd-volume half-step [D10][M13]
CLASS_P, CLASS_N, CLASS_Q = "P", "N", "Q"   # [r2] Up next played / now playing / upcoming and the
                                            # unavailable list cursor (CCAliveClass 6, 7, 8)
CLASSES = (CLASS_P, 1, CLASS_Q, 2, CLASS_N, CLASS_S, 3, 4)
ALPHA_AWAKE_WARM = {CLASS_P: 0.14, 1: 0.30, CLASS_Q: 0.45, 2: 0.62, CLASS_N: 0.70, CLASS_S: 0.81, 3: 1.0, 4: 1.0}
# [r2][M1] the semantic body 0.62 and half-step 0.81 like warm (AL: 1.00); ledVolFull restores 1.00.
ALPHA_AWAKE_SEMANTIC = {CLASS_P: 0.14, 1: 0.45, CLASS_Q: 0.45, 2: 0.62, CLASS_N: 0.70, CLASS_S: 0.81, 3: 1.0,
                        4: 1.0}
ALPHA_VOL_FULL = {2: 1.0, CLASS_S: 1.0}     # [M24] semantic class 2 / S with ledVolFull
# Resting = BS's thresholds (>= 0.99 -> 0.16, >= 0.5 -> 0.10, else 0.05), but S keeps D10's 0.13.
# [user 2026-09-26] resting = one steady dim warm white at 0.34 (0.05-0.16 was too dim to show the hue).
ALPHA_REST = {CLASS_P: 0.34, 1: 0.34, CLASS_Q: 0.34, 2: 0.34, CLASS_N: 0.34, CLASS_S: 0.34, 3: 0.34, 4: 0.34}
REST_TOD_MIN = 0.80   # time of day dims resting, never below this
EXTERNAL_ALPHA = 1.0
FLASH_ALPHA_NEAR, FLASH_ALPHA_FAR = 1.0, 0.5     # |k| <= 1, |k| == 2
OFFLINE_ALPHA = 0.12
OFFLINE_PITCH = 5                                # amber marks at 0, 5, ... 55
FLASH_MS = {"ok": FLASH_OK_MS, "err": FLASH_ERR_MS}
# [r2][M18] resting buttons: 0.12 when the awake alpha >= 0.5, else 0.04 (BS:620).
BUTTON_REST_HIGH, BUTTON_REST_LOW, BUTTON_REST_SPLIT = 0.34, 0.26, 0.5   # [user 2026-09-26]
# 5.3 tones -> (role, class, awake alpha). The class is the design light level (RC finishAlive:
# nav 2, dim 1, go 3, stop 2); the [r2] tones use 3 for the lit 1.0 tones and 1 for off.
# [r2.2][M32] ``liked`` (VOC CCButtonTone 7, the liked heart, 5.3 row 4): PINK 0.30, class 1 like
# ``off``; below the M18 split, so it rests at WARM 0.04.
BUTTON_TONES = {
    "dim": (ROLE_WARM, 1, 0.14), "stop": (ROLE_RED, 2, 1.0), "liked": (ROLE_PINK, 1, 0.30),
    "on": (ROLE_WARM, 3, 1.0), "off": (ROLE_WARM, 1, 0.30), "go": (ROLE_GREEN, 3, 1.0),
    "paused": (ROLE_GREEN, 3, 1.0), "nav": (ROLE_WARM, 2, 0.70),
}
# v5 icon tokens (PRESENTATION_V5 9.1): the engine reads them whether or not presentation.ICONS has
# them yet.
ICONS_V5 = tuple(dict.fromkeys(ICONS + ("expand", "clock", "playlists", "playnext", "seek", "shuffle",
                                        "heart", "snapleft", "snapright")))

HOME_LAYOUTS = ("nowPlaying", "volume", "idle", "notice")
# [r2] 5.4: every layout mapped explicitly (VOC 1.1); seek is Tracks family.
LAYOUT_FAMILY = {"nowPlaying": "home", "volume": "home", "idle": "home", "notice": "home",
                 "recent": "recent", "explorer": "explorer", "tracks": "tracks", "seek": "tracks",
                 "upnext": "upnext", "windows": "windows"}
FAMILIES = ("home", "recent", "tracks", "windows", "explorer", "upnext")
LIST_FAMILIES = ("recent", "explorer", "upnext", "windows")     # tint, D7 wash (M10)
FAMILY_OFFLINE = "offline"

VOLUME_START, VOLUME_END = 35, 25
TRACKS_PREV, TRACKS_NEUTRAL, TRACKS_NEXT = (52, 53), 0, (7, 8)
LIST_PITCH = 3
LAP_TICK = 5

# ----------------------------------------------------------------- timing (sections 6-8)
SLEEP_MS = 5000
SLEEP_EXTERNAL_MS = 3200
SLEEP_RECHECK_MS = 1000
MAX_DT_MS = 50
VEL_GAP_MS = 400
VEL_MIN_DT_MS = 16
VEL_KEEP, VEL_NEW = 0.55, 0.45
TICK_VEL0, TICK_VEL_SPAN, TICK_LEN_MAX = 4, 14, 7
# [D19] len = round(x + TICK_TIE_BIAS), x = clamp((vel - 4)/14) * 7 (see the firmware's tickTieBias).
TICK_TIE_BIAS = 1e-4

TAU_RING_REST_UP, TAU_RING_REST_DOWN = 400, 700
TAU_RING_CURSOR_UP, TAU_RING_UP, TAU_RING_DOWN = 10, 55, 140
RING_CURSOR_TARGET = 0.9
TAU_BUTTON_REST_UP, TAU_BUTTON_REST_DOWN = 400, 700
TAU_BUTTON_UP, TAU_BUTTON_DOWN = 40, 160
TAU_COLOUR, TAU_COLOUR_SNAP, COLOUR_SNAP_ALPHA = 70, 1, 0.02
TAU_TINT = 220
TINT_ALPHA = 0.06

BREATH_REST_MS = 5200
BREATH_OFFLINE_MS = 2600
PAUSED_PLAY_MS = 2600
WORKING_LAP_MS = 1400
# Near-max embers [D11]: P_i = round(2*pi*(380 + (i*97 mod 260))) ms.
HEAT_PERIODS = tuple(math.floor(TAU * (380 + (i * 97) % 260) + 0.5) for i in range(SEGMENTS))

SONG_HAND_W, SONG_HAND_ALPHA = 0.75, 0.26
TONE_KNEE, TONE_SPAN = 0.78, 0.22
RESIDUE = 1.0 / 1024

# ------------------------------------------------------------------ effects (section 7)
DUR = {"boot": 2800, "down": 1800, "wake": 520, "tick": 180, "bound": 460, "bloom": 900,
       "fail": 700, "sweep": 640, "fill": 760, "drain": 860, "shimmer": 1000, "wash": 1100,
       "reveal": 450, "press": 220, "pending": 2800, "half": 900, "scatter": 700}
FG = frozenset(("boot", "down", "bloom", "fail", "sweep", "fill", "drain", "shimmer", "wash", "half",
                "scatter"))
REPLACING = frozenset(("wake", "reveal", "bound"))
# [r2][M17] 6.5: play() drops these under reduced motion before anything else (BS:579).
REDUCED_MOTION_DROP = frozenset(("wake", "tick", "sweep", "scatter", "reveal"))
QUEUE_CAP = 8
KILL_FADE_MS = 120
DUCK_DEPTH = 0.35
# [r2][M5] scatter: r2.1's spread (BS:657); the sparks start 55 ms apart and bump for 260 ms.
SCATTER_ORDER = (0, 4, 8, 3, 7, 2, 6, 1, 5)
SCATTER_STEP_MS, SCATTER_BUMP_MS = 55, 260
# [r2][M23] half: segment k (1..29) lights when 20|k - 15| <= min(ms, 300) + 10.
HALF_GROW_MS, HALF_HOLD_MS, HALF_FADE_MS = 300, 380, 520
# [r2][M22] a feedback moment holds sleep for its effect's nominal duration (rows c-h of 6.4).
MOMENT_HOLD_MS = {"queued": 640, "shuffle": 700, "like": 900, "snap": 900, "wash": 1100, "bloom": 900}
FEEDBACK_MOMENTS = ("queued", "shuffle", "like", "unlike", "snap", "started")
# [r2][M5] the scatter PRNG: one xorshift32 per engine, seeded in reset().
RNG_SEED = 0x2545F491

# Time of day (8.3): (hour, resting brightness factor); WARM never changes [user].
TOD_KEYFRAMES = ((0, 0.55), (5, 0.60), (8, 0.95), (13, 1.00), (17, 1.00), (20, 0.85),
                 (22.5, 0.65), (24, 0.55))
MINUTES_PER_DAY = 1440


# ================================================================== design helpers
def js_round(x):
    """JS ``Math.round``: nearest integer, halves toward +infinity (exact: x - floor(x) is exact)."""
    f = math.floor(x)
    return f + 1 if x - f >= 0.5 else f


def md(i):
    """Design ``md(i) = ((Math.round(i) % 60) + 60) % 60``."""
    if type(i) is not int:
        i = js_round(i)
    return i % SEGMENTS     # Python % of an int equals ((r % 60) + 60) % 60 with the JS remainder


def cd(i, j):
    """Design ``cd(i, j) = ((((i - j) % 60) + 90) % 60) - 30`` with the JS remainder."""
    x = i - j
    if type(x) is int:
        return (x + 30) % SEGMENTS - 30
    return math.fmod(math.fmod(x, 60) + 90, 60) - 30


def cl(x):
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def eo(u):
    return 1 - (1 - cl(u)) ** 3


def eio(u):
    u = cl(u)
    return 4 * u * u * u if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2


def gs(x, w):
    return math.exp(-x * x / (2 * w * w))


def bump(ms, a, b):
    return 0 if ms < a or ms > b else math.sin(math.pi * (ms - a) / (b - a))


def mix(a, b, k):
    return (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k)


def phase(now, period):
    """Integer-modulo phase in [0, 1) [D11]."""
    return (now % period) / period


def sign(x):
    return (x > 0) - (x < 0)


def sat(c):
    """Re-saturate an app/album colour (design knob-model.js:499, section 2).

    ``c`` is (r, g, b) ints 0..255. Returns ints, or None when max - min < 30: the WARM
    fallback (a sat() that fell back to WARM counts as WARM). Rounds half away from zero.
    """
    mx, mn = max(c), min(c)
    if mx - mn < 30:
        return None
    d = mx - mn * 0.75
    return tuple(math.floor(max(0, x - mn * 0.75) / d * 255 + 0.5) for x in c)


def rgb_tuple(color):
    """0xRRGGBB -> (r, g, b)."""
    return ((color >> 16) & 255, (color >> 8) & 255, color & 255)


def tone(r, g, b):
    """Soft-knee tone map (8.5): above 0.78 scale by (0.78 + 0.22(1 - e^-(mx-0.78)/0.22))/mx."""
    mx = max(r, g, b)
    if mx <= TONE_KNEE:
        return (r, g, b)
    k = (TONE_KNEE + TONE_SPAN * (1 - math.exp(-(mx - TONE_KNEE) / TONE_SPAN))) / mx
    return (r * k, g * k, b * k)


def srgb_eotf(e):
    """Section 9 transfer [D3]: sRGB EOTF per channel, e clamped to 0..1."""
    e = 0.0 if e < 0 else 1.0 if e > 1 else e
    return e / 12.92 if e <= 0.04045 else ((e + 0.055) / 1.055) ** 2.4


def srgb_oetf(c):
    """The inverse of ``srgb_eotf`` (section 2 derivation; the PINK tuning at run time)."""
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


transfer = srgb_eotf

# Section 9 output (C++ only in the product; this is the dither-off reference for tests).
DEFAULT_DRIVE = 150
# [user 2026-09-26] (9 step 4, 12.7) the knob's temporal dither is off unless a latched
# ledDither:true turns it on (firmware CCAliveSpec::defaultDither).
DEFAULT_DITHER = False
BUTTON_LEDS_PER_SLOT = 2
# [D17][R5] B = 68 * (255 + 132 + 36) * 150 / 255 = 16920 exactly: the warmth test's proven load.
POWER_BUDGET = 16920.0


def effective_drive(led_drive=None, led_max_brightness=255):
    """Drive: the latched ledDrive, else 150, clamped to ledMaxBrightness."""
    return min(DEFAULT_DRIVE if led_drive is None else led_drive, led_max_brightness)


def floor_pixel(v):
    """[user 2026-09-26] Section 9 step 4, rule F-T, on one target-lit LED whose plain rounding is
    dark: ``v`` = the three drive- and power-limited channel values, all rounding to 0. With
    m = max(v) > 0 the LED shows one count on its dominant channel: q_c = 1 where v_c == m (a tie
    lights every tied channel), the rest 0. m = 0 stays dark. Returns (r, g, b).

    The channel rule was amended the same day (12.7): the first reading, round(v_c / m), also lit a
    channel >= m / 2, which plain rounding leaves dark just above m = 0.5, so a breathing mark turned a
    second channel on at its dim point and off again on both sides. This rule is the byte plain
    rounding shows just above 0.5: a breath passes through the floor without a jump."""
    m = max(v)
    if not m > 0:
        return (0, 0, 0)
    return tuple(1 if x >= m else 0 for x in v)


def reference_output(ring_e, button_e, drive=DEFAULT_DRIVE, ring_lit=None, button_lit=None):
    """Section 9 with dither off, float64: transfer, drive, power limit over 60 ring + 8 button
    LEDs, round half up and clamp; [user 2026-09-26] then the F-T floor (``floor_pixel``) on every
    LED whose flag in ``ring_lit`` (60) / ``button_lit`` (4) is true (the target is lit,
    ``lit_masks``) and whose plain rounding is dark. None = no floor on that strip (the plain
    output). Returns (60 ring 0xRRGGBB, 4 button 0xRRGGBB).

    The load is summed left to right in explicit loops (``sum()`` of floats is compensated since
    Python 3.12), so tests/js/alive_oracle.cjs ``referenceOutput`` reproduces every byte."""
    lin_ring = [[srgb_eotf(x) for x in e] for e in ring_e]
    lin_buttons = [[srgb_eotf(x) for x in e] for e in button_e]
    total = 0.0
    for c in lin_ring:
        total += (c[0] + c[1] + c[2]) * drive
    for c in lin_buttons:
        total += BUTTON_LEDS_PER_SLOT * (c[0] + c[1] + c[2]) * drive
    scale = drive * (POWER_BUDGET / total) if total > POWER_BUDGET else drive

    def pixel(c, lit):
        v = [x * scale for x in c]
        q = [min(255, max(0, math.floor(x + 0.5))) for x in v]
        if lit and not any(q):
            q = floor_pixel(v)
        return (q[0] << 16) | (q[1] << 8) | q[2]
    ring_lit = list(ring_lit) if ring_lit is not None else [False] * len(lin_ring)
    button_lit = list(button_lit) if button_lit is not None else [False] * len(lin_buttons)
    if len(ring_lit) != len(lin_ring) or len(button_lit) != len(lin_buttons):
        raise ValueError("reference_output: one lit flag per ring segment and per button slot")
    return ([pixel(c, bool(lit)) for c, lit in zip(lin_ring, ring_lit)],
            [pixel(c, bool(lit)) for c, lit in zip(lin_buttons, button_lit)])


def lit_masks(targets):
    """[user 2026-09-26] The F-T masks of an ``AliveTargets`` (section 9 step 4): per ring segment and
    per button slot, whether its target is lit (a cell with alpha > 0). Firmware ``cc_alive_lit``."""
    def lit(cell):
        return cell is not None and cell.alpha > 0
    return [lit(c) for c in targets.ring], [lit(c) for c in targets.buttons]


def tod_brightness(hour):
    """Resting brightness factor at ``hour`` (design warmAt(h).b over TOD_KEYFRAMES)."""
    keys = TOD_KEYFRAMES
    i = 0
    while i < len(keys) - 2 and hour > keys[i + 1][0]:
        i += 1
    (h0, b0), (h1, b1) = keys[i], keys[i + 1]
    k = cl((hour - h0) / (h1 - h0))
    return b0 + (b1 - b0) * k


def clock_hour(minute, elapsed_ms):
    """h = ((minute + elapsed/60000) mod 1440) / 60 (8.3, no half-hour rounding [D18])."""
    return math.fmod(minute + elapsed_ms / 60000, MINUTES_PER_DAY) / 60


def pink_from_led(led):
    """[r2][M24] PINK for a ``ledPink`` value: 0 = the built-in PINK, else the OETF of the LED colour."""
    if not led:
        return PINK
    return tuple(srgb_oetf(ch / 255) for ch in rgb_tuple(led))


def xorshift32(state):
    """[M5] one xorshift32 step (uint32): x ^= x << 13; x ^= x >> 17; x ^= x << 5."""
    state ^= (state << 13) & UINT32
    state ^= state >> 17
    state ^= (state << 5) & UINT32
    return state


def scatter_seed(state):
    """[M5] seed = 60 (rng >> 8) / 2^24 in [0, 60) (float64 here; the firmware's float32 is the
    correctly rounded value, within 4e-6)."""
    return 60 * (state >> 8) / 16777216


# ==================================================================== palettes
class Palette:
    """Colours the animator uses (floats 0..1). WARM/HOT are parameters so the oracles can inject
    the design's; the effect colours are GREEN (bloom), RED (fail), BLUE (shimmer), PINK (heart)."""

    __slots__ = ("warm", "hot", "green", "red", "blue", "amber", "pink")

    def __init__(self, warm, hot=None, green=None, red=None, blue=None, amber=None, pink=None):
        self.warm = tuple(float(x) for x in warm)
        self.hot = tuple(float(x) for x in hot) if hot is not None else mix(self.warm, WHITE_F, 0.5)
        self.green = tuple(green) if green is not None else GREEN
        self.red = tuple(red) if red is not None else RED
        self.blue = tuple(blue) if blue is not None else BLUE
        self.amber = tuple(amber) if amber is not None else AMBER
        self.pink = tuple(pink) if pink is not None else PINK

    def with_pink(self, pink):
        return Palette(self.warm, self.hot, self.green, self.red, self.blue, self.amber, pink)

    def role(self, role):
        """The colour of a palette role (the cells' ``col`` for the rest)."""
        return {ROLE_WARM: self.warm, ROLE_PINK: self.pink, ROLE_GREEN: self.green, ROLE_RED: self.red,
                ROLE_AMBER: self.amber, ROLE_BLUE: self.blue}.get(role)


def _f(rgb):
    """8-bit design-space ints (an ACCENT / sat() colour) -> floats 0..1."""
    return (rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)


# The section 2 constants as stored (HOT too: never re-derived), like firmware cc_alive_palette().
ENGINE_PALETTE = Palette(WARM, HOT, GREEN, RED, BLUE, AMBER, PINK)
# The RC design's effect constants (Ring Choreography v2 line 98), for the RC oracle only.
DESIGN_GREEN = (0.0, 1.0, 0.384)
DESIGN_RED = (1.0, 0.094, 0.0)
DESIGN_BLUE = (0.157, 0.549, 1.0)


def design_palette(warm, hot):
    """The RC oracle's palette: the case's WARM/HOT and the design's effect colours."""
    return Palette(warm, hot, DESIGN_GREEN, DESIGN_RED, DESIGN_BLUE)


def bs_palette(constants):
    """The BS oracle's palette (section 2, 11.2): BS's WARM/HOT/GREEN/RED/AMBER/PINK constants."""
    return Palette(constants["WARM"], constants["HOT"], constants["GREEN"], constants["RED"],
                   constants.get("BLUE", BLUE), constants["AMBER"], constants["PINK"])


# ===================================================================== targets
class Cell:
    """A lit target: ring segment or button.

    ``rgb``: an ACCENT's sat() colour (design-space 8-bit ints, also the oracle's explicit
    colours); for a palette role its section 2 float constant. ``col``: the colour the animator
    draws, floats 0..1: None for WARM and PINK (the animator's palette: the oracle injects the
    design's WARM, ``set_tuning`` changes PINK), the float constant for the other palette roles,
    rgb/255 otherwise. ``role`` ROLE_*; ``cls`` a CLASSES entry (ring) or the button tone's class;
    ``alpha``; ``vol_red`` feeds the near-max embers.
    """

    __slots__ = ("rgb", "col", "role", "cls", "alpha", "vol_red")

    def __init__(self, rgb, role, cls, alpha, col=None, vol_red=None):
        palette = ROLE_COLOUR.get(role)
        self.rgb = tuple(rgb) if rgb is not None else palette
        self.role = role
        self.cls = cls
        self.alpha = alpha
        if col is None and role not in (ROLE_WARM, ROLE_PINK):
            col = palette if palette is not None else _f(self.rgb)
        self.col = col
        self.vol_red = (role == ROLE_RED) if vol_red is None else bool(vol_red)

    def __eq__(self, other):
        return (isinstance(other, Cell) and self.rgb == other.rgb and self.role == other.role
                and self.cls == other.cls and self.alpha == other.alpha and self.vol_red == other.vol_red)

    def __repr__(self):
        return f"Cell({self.rgb}, {self.role}, {self.cls!r}, {self.alpha})"


def _role_cell(role, rgb, cls, alpha):
    return Cell(rgb if role == ROLE_ACCENT else ROLE_COLOUR[role], role, cls, alpha)


class AliveTargets:
    """Section 5.4 hand-off: per-segment/button targets plus the animator's flags."""

    __slots__ = ("ring", "buttons", "cursor", "family", "style", "asleep", "offline", "pending", "heat",
                 "paused_play", "tint", "value", "external", "playing", "accent", "flash", "reduced_motion")

    def __init__(self, ring=None, buttons=None, cursor=0, family=FAMILY_OFFLINE, style=None, asleep=False,
                 offline=False, pending=False, heat=False, paused_play=False, tint=None, value=0,
                 external=False, playing=None, accent=None, flash=None, reduced_motion=False):
        self.ring = ring if ring is not None else [None] * SEGMENTS
        self.buttons = buttons if buttons is not None else [None] * BUTTON_SLOTS
        self.cursor = cursor
        self.family = family
        self.style = style              # [r2] the ring style (MODE on transport <-> lap)
        self.asleep = asleep            # effectiveAsleep
        self.offline = offline
        self.pending = pending
        self.heat = heat
        self.paused_play = paused_play  # Home, slot 0 PLAY enabled (the animator adds awake)
        self.tint = tint                # floats 0..1 or None
        self.value = value              # displayed volume (level ring), else the ring value
        self.external = external
        self.playing = playing          # Home frame's playing (bool) or None
        self.accent = accent            # selected entry's accent after sat (ints) or None (WARM)
        self.flash = flash
        self.reduced_motion = reduced_motion


def offline_targets():
    """Section 5.2 Offline override (unclaimed): 12 AMBER marks at 0.12, buttons off."""
    ring = [None] * SEGMENTS
    for i in range(0, SEGMENTS, OFFLINE_PITCH):
        ring[i] = Cell(AMBER, ROLE_AMBER, 1, OFFLINE_ALPHA)
    return AliveTargets(ring=ring, family=FAMILY_OFFLINE, offline=True)


def _int(value, lo, hi, default):
    return value if type(value) is int and lo <= value <= hi else default


def frame_layout(frame):
    return frame.get("layout") or LEGACY_LAYOUT.get(frame.get("mode"), "nowPlaying")


def frame_family(frame):
    """[r2] 5.4: home (nowPlaying/volume/idle/notice), recent, explorer, tracks (tracks, seek), upnext,
    windows. The parsers reject every other layout token; a legacy frame derives it from ``mode``."""
    return LAYOUT_FAMILY.get(frame_layout(frame), "home")


def window_first_v4(index, count):
    """V4's derivation of an absent ``first`` (P4 section 4 rules.absentFirst): clamp(index - 9, ...)."""
    if count <= RING_WINDOW:
        return 0
    return max(0, min(index - 9, count - RING_WINDOW))


def _window_first(ring, index, count):
    """(first, relative): a present valid first, else V4's derived window (relative only when the
    first was absent and derives to 0, rules.absentFirst)."""
    raw_first = ring.get("first")
    if "first" in ring and type(raw_first) is int and 0 <= raw_first <= index < raw_first + RING_WINDOW \
            and (count > RING_WINDOW or raw_first == 0):
        return raw_first, True
    derived = window_first_v4(index, count)
    return derived, "first" not in ring and derived == 0


def ring_window(ring, index, count):
    """(first, width, colors, mask): the transmitted window the parser keeps (section 4)."""
    first, relative = _window_first(ring, index, count)
    width = max(0, min(RING_WINDOW, count - first))
    colors = ring.get("colors") if relative else None
    if not (isinstance(colors, list) and len(colors) <= width
            and all(type(c) is int and 0 <= c <= 0xFFFFFF for c in colors)):
        colors = []
    mask = _int(ring.get("unavailable", 0), 0, (1 << width) - 1, 0) if relative else 0
    return first, width, colors, mask


def pulse_class(pending_ms):
    """5.1.8 pending pulse: class 3 on even 260 ms phases, 1 on odd, 1 from 3000 ms."""
    pending_ms &= UINT32
    if pending_ms >= PENDING_HOLD_MS:
        return 1
    return 1 if (pending_ms // PULSE_MS) & 1 else 3


def _local(frame, local_pos, local_max):
    """Section 6.3 local cursor [D14]: (frame for the geometry, applied, local selection index).

    The level and transport rings get the local value/index; a selection ring keeps the frame
    (its transmitted window, colours, mask and ``now``) and returns the local index separately,
    for the [M15] re-centring. The lap ring never takes the local position [M11].
    """
    if local_pos is None or local_max is None or type(local_pos) is not int or type(local_max) is not int \
            or local_max < 0:
        return frame, False, None
    ring = frame.get("ring")
    if not isinstance(ring, dict):
        return frame, False, None
    local_pos = min(max(local_pos, 0), local_max)          # clamped like the firmware
    style, activity = ring.get("style"), frame.get("activity", "idle")
    if style == "level":
        if local_max != 100 or frame_layout(frame) == "notice" or activity == "offline":
            return frame, False, None
        value = _int(ring.get("value"), 0, 100, 0)
        confirmed = _int(frame.get("confirmedVolume", value), 0, 100, value)
        out = dict(frame)
        out["ring"] = dict(ring, value=local_pos)
        out["confirmedVolume"] = confirmed          # always the frame's
        return out, True, None
    if style == "selection":
        count = _int(ring.get("count"), 0, 65535, 0)
        if count < 1 or local_max != count - 1 or activity in ("pending", "loading"):
            return frame, False, None
        return frame, True, local_pos
    if style == "transport":
        if local_max != 2 or activity == "pending":
            return frame, False, None
        out = dict(frame)
        out["ring"] = dict(ring, index=local_pos)
        return out, True, None
    return frame, False, None


def apply_local(frame, local_pos, local_max):
    """Section 6.3: (frame with the local value/index, applied). A selection frame gets the local
    index in ``ring.index`` (the geometry re-centres from the original frame, M15)."""
    out, applied, index = _local(frame, local_pos, local_max)
    if index is not None:
        out = dict(out)
        out["ring"] = dict(out["ring"], index=index)
    return out, applied


class _Ring:
    """The ring cells being built: (role, class, accent rgb or None) per segment; put() overwrites."""

    __slots__ = ("cells",)

    def __init__(self):
        self.cells = [None] * SEGMENTS

    def put(self, i, role, cls, rgb=None):
        self.cells[i % SEGMENTS] = (role, cls, rgb)


def _volume_role(k, x, color_mode):
    """[M2] col(k, x): RED if x >= 90 and k >= 45; AMBER if x >= 80 and k >= 40; else WARM."""
    if not color_mode:
        return ROLE_WARM
    if x >= 90 and k >= 45:
        return ROLE_RED
    if x >= 80 and k >= 40:
        return ROLE_AMBER
    return ROLE_WARM


def _draw_volume(out, ring, frame, activity, color_mode):
    """5.1.2 [M1, M2, M13]. Returns the cursor."""
    v = _int(ring.get("value"), 0, 100, 0)
    c = _int(frame.get("confirmedVolume", v), 0, 100, v)

    def seg(k):
        return (VOLUME_START + k) % SEGMENTS
    if activity == "offline":                       # [D15] the confirmed endpoint only (M13 placement)
        out.put(seg(c // 2), ROLE_WARM, 1)
        return seg(c // 2)
    e, n, nc = v // 2, (v + 1) // 2, (c + 1) // 2
    out.put(seg(0), ROLE_WARM, 1)                   # 1. bounds
    out.put(seg(50), ROLE_WARM, 1)
    for k in range(n + 1):                          # 2. body; the span above confirmed is class 1
        out.put(seg(k), _volume_role(k, v, color_mode), 2 if k <= nc else 1)
    for k in range(n + 1, nc + 1):                  # 3. pending decrease on the confirmed value
        out.put(seg(k), _volume_role(k, c, color_mode), 1)
    if v & 1:                                       # 4. [M13] the half-step lights the NEXT segment
        out.put(seg(e + 1), _volume_role(e + 1, v, color_mode), CLASS_S)
    out.put(seg(e), _volume_role(e, v, color_mode),  # 5. endpoint
            4 if ring.get("external") is True else 3)
    return seg(e)


def _accent_of(color_mode, colors, first, more, j):
    """5.1.1 acc(j): (role, sat rgb or None). WARM without colour mode, on More, for colour 0 or a
    sat() fallback."""
    k = j - first
    if not color_mode or j == more or not 0 <= k < len(colors) or not colors[k]:
        return ROLE_WARM, None
    s = sat(rgb_tuple(colors[k]))
    return (ROLE_ACCENT, s) if s is not None else (ROLE_WARM, None)


def _draw_selection(out, ring, activity, color_mode, pending_ms, local_index, upnext):
    """5.1.1, 5.1.3 (lists) and 5.1.4 (Up next). Returns (cursor, selected accent rgb or None)."""
    count = _int(ring.get("count"), 0, 65535, 0)
    if activity == "loading" or count == 0:         # [M31] a whole list loading: the comet only
        return 0, None
    frame_index = _int(ring.get("index"), 0, 65535, 0)
    if not frame_index < count:                     # the parsers reject this; draw nothing
        return 0, None
    index = frame_index if local_index is None else local_index
    first, width, colors, mask = ring_window(ring, frame_index, count)
    more = -1 if upnext else _int(ring.get("moreIndex", -1), -1, count - 1, -1)
    if upnext:
        mask = 0                                    # K1 strips ring.unavailable on upnext (P5-R24)
        now = _int(ring.get("now", -1), -1, count - 1, -1)
        card = ring.get("card") is True and count >= 2
    else:
        now, card = -1, False
    if local_index is not None and count > RING_WINDOW:     # [M15] re-centre on the local index
        win_first, win_width = max(0, min(local_index - 10, count - RING_WINDOW)), RING_WINDOW
    else:
        win_first, win_width = first, width
    c0 = win_first + (win_width - 1) // 2           # [M9]

    def slot(j):
        return ((j - c0) * LIST_PITCH) % SEGMENTS

    def transmitted(j):
        return first <= j < first + width

    def available(j):
        k = j - first
        return not (0 <= k < width and (mask >> k) & 1)

    def is_card(j):
        return card and j == count - 1
    for j in range(win_first, win_first + win_width):   # landmarks; unavailable = a gap
        if not transmitted(j) or is_card(j) or not available(j):
            continue
        role, rgb = _accent_of(color_mode, colors, first, more, j)
        cls = (CLASS_P if j < now else CLASS_N if j == now else CLASS_Q) if upnext else 1
        out.put(slot(j), role, cls, rgb)
    cursor = slot(index)
    selected = None
    if is_card(index):                              # [M14] the card: no cursor cell
        return cursor, None
    if not transmitted(index):                      # [M15] not transmitted yet: WARM class 3
        role, rgb, cls = ROLE_WARM, None, 3
    else:
        role, rgb = _accent_of(color_mode, colors, first, more, index)
        selected = rgb
        cls = 3 if index == more or available(index) else CLASS_Q
    if activity == "pending":                       # 5.1.8: the cursor pulses in its colour [M3][D13]
        cls = pulse_class(pending_ms)
    out.put(cursor, role, cls, rgb)
    return cursor, selected


def _draw_transport(out, ring, activity, pending_ms):
    """5.1.5 (P4 5.4, always WARM). index 0 Prev, 1 Neutral, 2 Next; mask bit0 = no Prev."""
    if _int(ring.get("count"), 0, 65535, 0) != 3:
        return 0
    index = _int(ring.get("index"), 0, 2, -1)
    if index < 0:
        return 0
    no_prev = bool(_int(ring.get("unavailable", 0), 0, 7, 0) & 1)
    if not no_prev:
        for i in TRACKS_PREV:
            out.put(i, ROLE_WARM, 1)
    out.put(TRACKS_NEUTRAL, ROLE_WARM, 1)
    for i in TRACKS_NEXT:
        out.put(i, ROLE_WARM, 1)
    if index == 0:
        pair, cursor = TRACKS_PREV, TRACKS_PREV[0]  # [M4] Prev cursor 52
        if not no_prev:
            for i in pair:
                out.put(i, ROLE_WARM, 3)
    elif index == 2:
        pair, cursor = TRACKS_NEXT, TRACKS_NEXT[1]
        for i in pair:
            out.put(i, ROLE_WARM, 3)
    else:
        pair, cursor = (TRACKS_NEUTRAL,), TRACKS_NEUTRAL
        out.put(TRACKS_NEUTRAL, ROLE_WARM, 2)
    if activity == "pending":                       # the selected cells pulse
        cls = pulse_class(pending_ms)
        for i in pair:
            out.put(i, ROLE_WARM, cls)
    return cursor


def _draw_lap(out, ring):
    """5.1.6 [r2]: the song as one lap from 12 o'clock, all WARM; no pulse. Returns the head."""
    t = _int(ring.get("index"), 0, 65535, 0)
    d = max(1, _int(ring.get("count"), 0, 65535, 0))
    head = min(59, t * 60 // d)
    for k in range(SEGMENTS):
        if k < head:
            out.put(k, ROLE_WARM, 2)
        elif k > head and k % LAP_TICK == 0:
            out.put(k, ROLE_WARM, 1)
    out.put(head, ROLE_WARM, 3)
    return head


def button_tone_v5(frame, slot, family):
    """5.3 [r2][M18]: (tone, sat rgb or None) of button ``slot``, first match wins."""
    buttons = frame.get("buttons") or []
    if not 0 <= slot < len(buttons) or not isinstance(buttons[slot], dict):
        return "none", None
    b = buttons[slot]
    icon = b.get("icon")
    if not isinstance(icon, str) or icon not in ICONS_V5:
        icon = ""
    if not icon:
        return "none", None
    if b.get("enabled") is not True:
        return "dim", None
    if slot == 0 and icon == "cancel":
        return "stop", None
    lit = b.get("lit")
    if lit == "on":
        if icon == "heart":
            return "liked", None                    # [r2.2][M32] PINK 0.30; [M25] never sat(), kept under Warm only
        color = _int(b.get("color", 0), 0, 0xFFFFFF, 0)
        if color and frame.get("ledStyle") == "color":
            s = sat(rgb_tuple(color))
            if s is not None:
                return "accent", s                  # VOC-D02: the snap side in sat(app colour)
        return "on", None
    if lit == "off":
        return "off", None
    if slot == 3 and icon in ("play", "prev", "next", "switch"):
        return "go", None
    if family == "home" and slot == 0 and icon == "play":
        return "paused", None                       # [M8] paused Play: green + the breath
    return "nav", None


class AliveGeometry:
    """First half of the targets: the alive cells (awake roles and classes) and the frame facts."""

    __slots__ = ("frame", "local", "cells", "cursor", "family", "layout", "style", "activity",
                 "color_mode", "value", "confirmed", "pending", "external", "playing",
                 "accent", "buttons")


def alive_geometry(frame, local_pos=None, local_max=None, pending_ms=0, loading_ms=0):
    """5.1 cells on the frame with the local cursor applied (6.3), plus the frame facts.
    ``loading_ms`` is accepted for callers of revision 1; revision 2 draws no loading pulse."""
    del loading_ms
    g = AliveGeometry()
    resolved, g.local, local_index = _local(frame, local_pos, local_max)
    g.frame = resolved
    ring = resolved.get("ring") if isinstance(resolved.get("ring"), dict) else {}
    g.style, g.activity = ring.get("style"), resolved.get("activity", "idle")
    g.layout, g.family = frame_layout(resolved), frame_family(resolved)
    g.color_mode = resolved.get("ledStyle") == "color"
    g.value = _int(ring.get("value"), 0, 100, 0)
    g.confirmed = _int(resolved.get("confirmedVolume", g.value), 0, 100, g.value)
    # 6.1 [R1]: activity offline (the Sonos-off notice [D15]) is never pending.
    g.pending = g.activity in ("pending", "loading") or (
        g.family == "home" and g.style == "level" and g.activity != "offline" and g.value != g.confirmed)
    g.external = ring.get("external") is True
    playing = resolved.get("playing")
    g.playing = playing if g.family == "home" and type(playing) is bool else None
    out = _Ring()
    g.accent = None
    if g.style == "level":
        g.cursor = _draw_volume(out, ring, resolved, g.activity, g.color_mode)
    elif g.style == "selection":
        g.cursor, g.accent = _draw_selection(out, ring, g.activity, g.color_mode, pending_ms, local_index,
                                             g.layout == "upnext")
    elif g.style == "transport":
        g.cursor = _draw_transport(out, ring, g.activity, pending_ms)
    elif g.style == "lap":
        g.cursor = _draw_lap(out, ring)
    else:                                           # 5.1.7 off (or unknown): dark, cursor 0
        g.cursor = 0
    g.cells = out.cells
    g.buttons = [button_tone_v5(resolved, j, g.family) for j in range(BUTTON_SLOTS)]
    return g


def ring_alpha(role, cls, asleep, vol_full=False):
    """5.2: the alpha of a (role, class) target."""
    if asleep:
        return ALPHA_REST[cls]
    if role == ROLE_WARM:
        return ALPHA_AWAKE_WARM[cls]
    if vol_full and cls in ALPHA_VOL_FULL:
        return ALPHA_VOL_FULL[cls]
    return ALPHA_AWAKE_SEMANTIC[cls]


def alive_finish(g, asleep, flash=None, vol_full=False, reduced_motion=False):
    """Second half: alphas, overrides (5.2), buttons (5.3), flags (5.4).

    ``asleep`` is effectiveAsleep; ``flash`` the active flash kind ("ok"/"err") or None;
    ``vol_full`` the latched ledVolFull [M24].
    """
    ring = [None] * SEGMENTS
    for i, cell in enumerate(g.cells):
        if cell is None:
            continue
        role, cls, rgb = cell
        if asleep:
            ring[i] = Cell(WARM, ROLE_WARM, cls, ALPHA_REST[cls])
        else:
            ring[i] = _role_cell(role, rgb, cls, ring_alpha(role, cls, False, vol_full))
    cursor = g.cursor
    if not asleep and g.family == "home" and g.external:
        for k in (-1, 0, 1):
            ring[(cursor + k) % SEGMENTS] = Cell(BLUE, ROLE_BLUE, 4, EXTERNAL_ALPHA)
    if flash in FLASH_MS:
        role = ROLE_GREEN if flash == "ok" else ROLE_RED
        for k in (-2, -1, 0, 1, 2):
            ring[(cursor + k) % SEGMENTS] = _role_cell(
                role, None, 4, FLASH_ALPHA_NEAR if abs(k) <= 1 else FLASH_ALPHA_FAR)
    buttons = [None] * BUTTON_SLOTS
    paused = False
    for j, (tone_name, rgb) in enumerate(g.buttons):
        if tone_name == "none":
            continue
        if tone_name == "accent":
            role, cls, alpha = ROLE_ACCENT, 3, 1.0
        else:
            role, cls, alpha = BUTTON_TONES[tone_name]
        if tone_name == "paused":
            paused = True
        if asleep:                                  # [M18]
            buttons[j] = Cell(WARM, ROLE_WARM, cls, BUTTON_REST_HIGH if alpha >= BUTTON_REST_SPLIT else BUTTON_REST_LOW)
        else:
            buttons[j] = _role_cell(role, rgb, cls, alpha)
    tint = None
    if g.family in LIST_FAMILIES and not asleep:    # 5.4 [R2]: an ACCENT cursor only
        target = ring[cursor]
        if target is not None and target.role == ROLE_ACCENT:
            tint = target.col
    return AliveTargets(
        ring=ring, buttons=buttons, cursor=cursor, family=g.family, style=g.style, asleep=asleep,
        offline=False, pending=g.pending,
        heat=g.family == "home" and not asleep and g.style == "level" and g.value >= 90,
        paused_play=paused and not asleep, tint=tint, value=g.value, external=g.external,
        playing=g.playing, accent=g.accent, flash=flash if flash in FLASH_MS else None,
        reduced_motion=reduced_motion)


def alive_targets(frame, local_pos=None, local_max=None, *, state_asleep=False, flash=None, hold=False,
                  pending_ms=0, loading_ms=0, claimed=True, vol_full=False):
    """Pure targets (section 5, 6.3) for one frame dict.

    ``state_asleep`` is the engine's stateAsleep; effectiveAsleep = state_asleep and not pending
    and not holdActive (a flash, or ``hold``: a moment hold [M22]) and claimed.
    ``pending_ms`` is the pending onset's elapsed time. Unclaimed (or no frame): the offline targets.
    """
    del loading_ms
    if not claimed or frame is None:
        return offline_targets()
    g = alive_geometry(frame, local_pos, local_max, pending_ms)
    active = flash if flash in FLASH_MS else None
    return alive_finish(g, bool(state_asleep) and not g.pending and active is None and not hold, active,
                        vol_full)


# ===================================================================== animator
class Effect:
    """One queued moment. ``c`` floats 0..1 (bound, wash, bloom, half); ``frm``/``to`` shimmer; ``n``
    press slot or fill/drain arc length; ``side`` half (-1 left, +1 right); ``seed`` scatter
    (0 <= seed < 60); ``snap``/``bsnap`` the down snapshot."""

    __slots__ = ("type", "t0", "dur", "at", "dir", "c", "n", "len", "frm", "to", "home",
                 "snap", "bsnap", "kill", "side", "seed")

    def __init__(self, type, t0, at=0, dir=1, c=None, n=0, len=0, frm=0, to=0, home=True,
                 snap=None, bsnap=None, side=0, seed=0.0):
        self.type = type
        self.t0 = t0
        self.dur = DUR[type]
        self.at = at
        self.dir = dir
        self.c = c
        self.n = n
        self.len = len
        self.frm = frm
        self.to = to
        self.home = home
        self.snap = snap
        self.bsnap = bsnap
        self.kill = None
        self.side = side
        self.seed = seed

    def __repr__(self):
        return f"Effect({self.type}, t0={self.t0}, at={self.at}, kill={self.kill})"


def _initial_cells(count):
    return [[1.0, 0.64, 0.33, 0.0] for _ in range(count)]     # design cur/bcur init


class AliveAnimator:
    """Damping, effect queue, continuous layers and composition (sections 7-8): design draw()."""

    def __init__(self, cap=QUEUE_CAP):
        self.cap = cap                # None = uncapped (the designs; oracle shadow)
        self.reduced_motion = False   # [r2] 6.5: play() drops, fail is stationary (read at draw time)
        self.reset()

    def reset(self):
        self.ring = _initial_cells(SEGMENTS)       # [r, g, b, a] per segment
        self.buttons = _initial_cells(BUTTON_SLOTS)
        self.tint = [0.0, 0.0, 0.0]
        self.effects = []
        self.evictions = 0
        self.residue = 0.0
        self.continuous = False

    # ------------------------------------------------------------ queue
    def snapshot(self):
        """``down``'s snap/bsnap: cur*a per channel (design line 231)."""
        return ([(c[0] * c[3], c[1] * c[3], c[2] * c[3]) for c in self.ring],
                [(c[0] * c[3], c[1] * c[3], c[2] * c[3]) for c in self.buttons])

    def play(self, effect):
        """Design play(): [r2] under reduced motion wake/tick/sweep/scatter/reveal are dropped first
        (not queued, kill nothing; BS:579); an FG effect kills running FG (kill = t0); wake/reveal/
        bound replace their type; then the section 7 eviction when the queue is full [D12]; then
        append. Returns the effect, or None when dropped."""
        if self.reduced_motion and effect.type in REDUCED_MOTION_DROP:
            return None
        fx = self.effects
        if effect.type in FG:
            for f in fx:
                if f.type in FG and f.kill is None:
                    f.kill = effect.t0
        elif effect.type in REPLACING:
            fx[:] = [f for f in fx if f.type != effect.type]
        if self.cap is not None:
            while len(fx) >= self.cap:
                self._evict()
        fx.append(effect)
        return effect

    def _evict(self):
        fx = self.effects
        for test in (lambda f: f.kill is not None, lambda f: f.type == "tick",
                     lambda f: f.type == "press", lambda f: True):
            for i, f in enumerate(fx):
                if test(f):
                    del fx[i]
                    self.evictions += 1
                    return

    def animating(self):
        return bool(self.effects) or self.residue > RESIDUE or self.continuous

    # ------------------------------------------------------------ draw
    def step(self, now, dt, tg, song_prog=None, tod_b=1.0, palette=None):
        """One frame at ``now`` (uint32 ms) with gap ``dt`` (ms): returns (ring e x60, buttons e x4)."""
        pal = palette or ENGINE_PALETTE
        exp, sin = math.exp, math.sin
        WARM_, HOT_, PINK_ = pal.warm, pal.hot, pal.pink
        asleep, off = tg.asleep, tg.offline
        rest_k = max(tod_b, REST_TOD_MIN) if asleep else 1   # [user 2026-09-26] steady rest, no breath
        if off:
            br = 0.6 + 0.4 * sin(TAU * phase(now, BREATH_OFFLINE_MS))
        else:
            br = 1
        heat = tg.heat
        if dt:
            k_rest_up, k_rest_down = 1 - exp(-dt / TAU_RING_REST_UP), 1 - exp(-dt / TAU_RING_REST_DOWN)
            k_cur, k_up, k_down = (1 - exp(-dt / TAU_RING_CURSOR_UP), 1 - exp(-dt / TAU_RING_UP),
                                   1 - exp(-dt / TAU_RING_DOWN))
            kb_rest_up, kb_rest_down = (1 - exp(-dt / TAU_BUTTON_REST_UP),
                                        1 - exp(-dt / TAU_BUTTON_REST_DOWN))
            kb_up, kb_down = 1 - exp(-dt / TAU_BUTTON_UP), 1 - exp(-dt / TAU_BUTTON_DOWN)
            k_col, k_snap = 1 - exp(-dt / TAU_COLOUR), 1 - exp(-dt / TAU_COLOUR_SNAP)
            k_tint = 1 - exp(-dt / TAU_TINT)
        else:
            k_rest_up = k_rest_down = k_cur = k_up = k_down = kb_rest_up = kb_rest_down = 0.0
            kb_up = kb_down = k_col = k_snap = k_tint = 0.0
        residue = 0.0
        embers = False

        def colour(cell):
            role = cell.role
            if role == ROLE_WARM:
                return WARM_
            if role == ROLE_PINK:
                return PINK_
            return cell.col or WARM_

        # -- ring damping (design 274-286)
        cur = self.ring
        targets = tg.ring
        for i in range(SEGMENTS):
            r = targets[i]
            c = cur[i]
            a = c[3]
            if r is not None:
                tc = colour(r)
                ta = r.alpha * br * rest_k
                if heat and r.vol_red:
                    embers = True
                    p = HEAT_PERIODS[i]
                    ta *= 0.72 + 0.28 * (0.5 + 0.5 * sin(TAU * ((now % p) / p) + 1.9 * i))
            else:
                tc = None
                ta = 0
            if asleep:
                k = k_rest_up if ta > a else k_rest_down
            elif ta > a:
                k = k_cur if ta >= RING_CURSOR_TARGET else k_up
            else:
                k = k_down
            a += (ta - a) * k
            c[3] = a
            d = ta - a
            if d > residue or -d > residue:
                residue = abs(d)
            if tc is not None:
                kc = k_snap if a < COLOUR_SNAP_ALPHA else k_col
                c[0] += (tc[0] - c[0]) * kc
                c[1] += (tc[1] - c[1]) * kc
                c[2] += (tc[2] - c[2]) * kc
                d = a * max(abs(tc[0] - c[0]), abs(tc[1] - c[1]), abs(tc[2] - c[2]))
                if d > residue:
                    residue = d

        # -- buttons (design 287-296)
        paused = tg.paused_play and not asleep and tg.family == "home"
        bcur = self.buttons
        for j in range(BUTTON_SLOTS):
            b = tg.buttons[j]
            c = bcur[j]
            a = c[3]
            ta = b.alpha * rest_k if b is not None else 0
            if asleep:
                ta *= br
            if j == 0 and paused:
                ta *= 0.55 + 0.45 * (0.5 + 0.5 * math.cos(TAU * phase(now, PAUSED_PLAY_MS)))
            if asleep:
                k = kb_rest_up if ta > a else kb_rest_down
            else:
                k = kb_up if ta > a else kb_down
            a += (ta - a) * k
            c[3] = a
            d = ta - a
            if d > residue or -d > residue:
                residue = abs(d)
            if b is not None:
                tc = colour(b)
                c[0] += (tc[0] - c[0]) * k_col
                c[1] += (tc[1] - c[1]) * k_col
                c[2] += (tc[2] - c[2]) * k_col
                d = a * max(abs(tc[0] - c[0]), abs(tc[1] - c[1]), abs(tc[2] - c[2]))
                if d > residue:
                    residue = d

        # -- masks and overlays (design 298-305)
        m = [1.0] * SEGMENTS
        bm = [1.0] * BUTTON_SLOTS
        o_r = [0.0] * SEGMENTS
        o_g = [0.0] * SEGMENTS
        o_b = [0.0] * SEGMENTS
        ob = [[0.0, 0.0, 0.0] for _ in range(BUTTON_SLOTS)]
        floor, ceil = math.floor, math.ceil

        def add(i, c, a):
            if a <= 0.001:
                return
            if type(i) is not int:
                i = js_round(i)
            i %= SEGMENTS
            o_r[i] += c[0] * a
            o_g[i] += c[1] * a
            o_b[i] += c[2] * a

        def add_g(pos, w, c, a):
            ww = 2 * w * w
            for k in range(floor(pos - 3 * w), ceil(pos + 3 * w) + 1):
                x = k - pos
                add(k, c, a * exp(-x * x / ww))

        def add_b(j, c, a):
            o = ob[j]
            o[0] += c[0] * a
            o[1] += c[1] * a
            o[2] += c[2] * a

        def comet(head, direction, length, c0, c1, a):
            for k in range(length + 1):
                add_g(head - direction * k, 0.7, c1 if k else c0, a * (1 - k / (length + 1)) ** 1.7)

        # -- continuous layers (8.4)
        if tg.pending:
            comet(60 * phase(now, WORKING_LAP_MS), 1, 8, HOT_, WARM_, 0.5)
        tt = tg.tint or (0.0, 0.0, 0.0)
        tint = self.tint
        for q in range(3):
            tint[q] += (tt[q] - tint[q]) * k_tint
        tint_live = tg.tint is not None or max(abs(tint[0]), abs(tint[1]), abs(tint[2])) > RESIDUE
        for i in range(SEGMENTS):
            if targets[i] is None:
                add(i, tint, TINT_ALPHA)
        if song_prog is not None and not asleep:   # [user 2026-09-26] no song hand at rest
            add_g(song_prog * 60, SONG_HAND_W, HOT_, SONG_HAND_ALPHA * tod_b)

        # -- effects (design 318-360; BS 640-660 for the r2 recipes)
        duck = 0.0
        keep = []
        pi = math.pi
        rm = self.reduced_motion
        for e in self.effects:
            ms = (now - e.t0) & UINT32
            u = ms / e.dur
            if u > 1:
                continue
            amp = 1
            if e.kill is not None:
                amp = 1 - ((now - e.kill) & UINT32) / KILL_FADE_MS
                if amp <= 0:
                    continue
            keep.append(e)
            kind, at = e.type, e.at
            if kind in FG and kind != "boot" and kind != "down":
                duck = max(duck, DUCK_DEPTH * sin(pi * u) * amp)
            if kind == "tick":
                add(at, HOT_, 0.45 * (1 - u) ** 2 * amp)
                ln, dr = e.len, e.dir
                for k in range(1, ln + 1):
                    add(at - dr * k, WARM_, 0.38 * (1 - k / (ln + 1)) ** 1.5 * (1 - u) * amp)
            elif kind == "press":
                add_b(e.n, HOT_, 0.6 * (1 - u) ** 2)
            elif kind == "wake":
                d = eo(u) * 30
                for i in range(SEGMENTS):
                    x = abs(cd(i, at)) - d
                    add(i, HOT_, 0.32 * (1 - u) * exp(-x * x / 18) * amp)
            elif kind == "bound":
                c = e.c
                add(at, c, 0.8 * (1 - u) ** 2 * amp)
                for k in range(1, 5):
                    add(at - e.dir * k, c, 0.5 * (1 - k / 5) * bump(ms, (4 - k) * 30, (4 - k) * 30 + 260) * amp)
            elif kind == "reveal":
                for i in range(SEGMENTS):
                    m[i] *= cl((ms - abs(cd(i, 0)) * 8) / 130)
            elif kind == "bloom":                   # RC:349 / BS:656: the colour is a parameter
                c = e.c if e.c is not None else pal.green
                d = eo(u / 0.8) * 30
                front = 0.9 * (1 - u * 0.5)
                trail = 0.16 * (1 - u) ** 1.5
                for i in range(SEGMENTS):
                    x = abs(cd(i, at))
                    y = x - d
                    add(i, c, front * exp(-y * y / 4.5) * amp)
                    if x < d:
                        add(i, c, trail * amp)
                add_g(at + 30, 1, mix(c, WHITE_F, 0.3), 0.8 * bump(ms, 560, 900) * amp)
            elif kind == "half":                    # BS:655 [M23]
                c = e.c
                fade = 1 if ms < HALF_HOLD_MS else 1 - eo((ms - HALF_HOLD_MS) / HALF_FADE_MS)
                reach = min(ms, HALF_GROW_MS) + 10
                for k in range(1, 30):
                    if 20 * abs(k - 15) <= reach:
                        add(60 - k if e.side < 0 else k, c, 0.75 * fade * amp)
                add_b(1 if e.side < 0 else 2, c, 0.6 * fade)
            elif kind == "scatter":                 # BS:657 [M5]
                for k in range(9):
                    p = math.fmod(e.seed + SCATTER_ORDER[k] * 60 / 9, 60)
                    st = k * SCATTER_STEP_MS
                    add_g(p, 0.8, HOT_, 0.8 * bump(ms, st, st + SCATTER_BUMP_MS) * amp)
            elif kind == "fail":                    # RC:350 / BS:658 (stationary under reduced motion)
                pos = at if rm else at + 1.6 * sin(ms / 1000 * TAU * 3.2) * (1 - eo(u))
                add_g(pos, 0.9, pal.red, 0.95 * (1 - u ** 2) * amp)
                dim = 1 - 0.6 * sin(pi * u)
                for k in range(-3, 4):
                    m[md(at + k)] *= dim
            elif kind == "sweep":
                comet(at + e.dir * 60 * eo(u), e.dir, 10, HOT_, WARM_, 0.85 * (1 - u ** 3) * amp)
            elif kind == "fill":
                n = e.n
                f = u * 1.15 * (n + 1)
                for k in range(n + 1):
                    m[(35 + k) % SEGMENTS] *= cl((f - k) / 2.5)
                add_g(35 + min(n, f), 0.9, HOT_, 0.75 * (1 - cl((u - 0.85) / 0.15)) * amp)
            elif kind == "drain":
                n = e.n
                pos = n - eio(u) * (n + 6)
                for k in range(n + 1):
                    x = k - pos
                    m[(35 + k) % SEGMENTS] *= 1 - 0.8 * exp(-x * x / 24.5) * amp
            elif kind == "shimmer":
                dl = cd(e.to, e.frm)
                pos = e.frm + dl * eio(u / 0.7)
                blue = pal.blue
                add_g(pos, 1.2, blue, 0.9 * (1 if u < 0.7 else 1 - (u - 0.7) / 0.3) * amp)
                add_g(e.to, 1.4, blue, 0.5 * bump(ms, 600, 1000) * amp)
            elif kind == "wash":
                c = e.c
                d = eo(ms / 420) * 31
                fade = 1 if ms < 520 else 1 - eo((ms - 520) / 580)
                edge = 0.45 * (1 - cl(ms / 420))
                dim = 1 - 0.55 * fade * amp
                for i in range(SEGMENTS):
                    x = abs(cd(i, at))
                    if x <= d:
                        add(i, c, 0.65 * fade * amp)
                    y = x - d
                    add(i, c, edge * exp(-y * y / 4.5) * amp)
                    m[i] *= dim
                add_b(3, c, 0.55 * fade * amp)
            elif kind == "boot":
                if ms < 1000:
                    comet(60 * eio(ms / 900), 1, 14, HOT_, WARM_,
                          0.95 * (1 if ms < 900 else 1 - (ms - 900) / 100) * amp)
                b = bump(ms, 850, 1450)
                if b:
                    for i in range(SEGMENTS):
                        add(i, WARM_, 0.22 * b * amp)
                home = e.home
                for i in range(SEGMENTS):
                    o = (i - 35) % SEGMENTS if home else abs(cd(i, 0)) * 2
                    m[i] *= cl((ms - 1250 - o * 11) / 160)
                for j in range(BUTTON_SLOTS):
                    s0 = 1850 + j * 100
                    bm[j] *= cl((ms - s0) / 200)
                    add_b(j, HOT_, 0.45 * bump(ms, s0, s0 + 240))
            elif kind == "down":                    # [M19] RC's recipe (S02 section 7)
                snap = e.snap
                for i in range(SEGMENTS):
                    o = md(i - at)
                    st = 80 + (60 - o) * 10
                    sn = snap[i]
                    m[i] *= 0 if i == at else cl((ms - 1250 - abs(cd(i, 0)) * 12) / 200)
                    if o == 0:
                        add(i, sn, (1 - cl((ms - 700) / 500)) * amp)
                        add(i, WARM_, 0.35 * bump(ms, 500, 1250) * amp)
                    else:
                        add(i, sn, (1 - cl((ms - st) / 110)) * amp)
                for j in range(BUTTON_SLOTS):
                    bm[j] = 0
                    add_b(j, e.bsnap[j], 1 - cl((ms - 120 - (3 - j) * 80) / 160))
            elif kind == "pending":        # RC design-only moment, kept for the verbatim port
                comet(ms / 1400 * 60 + at, 1, 8, HOT_, WARM_, 0.5 * min(1, ms / 200, (e.dur - ms) / 200))
        self.effects = keep
        self.residue = residue
        self.continuous = bool(tg.pending or tint_live or asleep or off or embers or paused
                               or song_prog is not None)

        # -- compose (design 370-395)
        bk = 1 - duck
        ring_e = []
        for i in range(SEGMENTS):
            c = cur[i]
            k = c[3] * m[i] * bk
            ring_e.append(tone(c[0] * k + o_r[i], c[1] * k + o_g[i], c[2] * k + o_b[i]))
        button_e = []
        for j in range(BUTTON_SLOTS):
            c = bcur[j]
            o = ob[j]
            k = c[3] * bm[j]
            button_e.append(tone(c[0] * k + o[0], c[1] * k + o[1], c[2] * k + o[2]))
        return ring_e, button_e


# ------------------------------------------------------------------ oracle entry
def oracle_targets(view):
    """Oracle view (tests/fixtures/alive_oracle.json, alive_oracle_bs.json) -> AliveTargets.

    ``warm:true`` entries use the palette WARM (case.warm); others c/255. Flags verbatim.
    """
    ring = []
    for entry in view["ring"]:
        if entry is None:
            ring.append(None)
            continue
        warm = bool(entry.get("warm"))
        rgb = tuple(entry["c"])
        ring.append(Cell(rgb, ROLE_WARM if warm else "oracle", None, float(entry["a"]),
                         col=None if warm else _f(rgb), vol_red=bool(entry.get("volRed"))))
    buttons = []
    for entry in view["buttons"]:
        if entry is None:
            buttons.append(None)
            continue
        warm = bool(entry.get("warm"))
        rgb = tuple(entry["c"])
        buttons.append(Cell(rgb, ROLE_WARM if warm else "oracle", None, float(entry["a"]),
                            col=None if warm else _f(rgb), vol_red=False))
    tint = view.get("tint")
    return AliveTargets(
        ring=ring, buttons=buttons, cursor=view.get("cursor", 0), family=view.get("family", "home"),
        asleep=bool(view.get("asleep")), offline=bool(view.get("offline")), pending=bool(view.get("pending")),
        heat=bool(view.get("heat")), paused_play=bool(view.get("pausedPlay")),
        tint=tuple(tint) if tint else None, value=view.get("vol", 0), playing=view.get("playing"),
        reduced_motion=bool(view.get("rm")))


def oracle_effect(spec, animator, palette=None):
    """Oracle effect push -> Effect; params verbatim, 'down' snapshots ``animator`` now. A bloom
    without ``c`` is the palette's GREEN (RC's GRN)."""
    kind = spec["type"]
    c = spec.get("c")
    if c is None and kind == "bloom":
        c = (palette or ENGINE_PALETTE).green
    e = Effect(kind, spec["t0"], at=spec.get("at", 0), dir=spec.get("dir", 1),
               c=tuple(c) if c is not None else None, n=spec.get("n", 0), len=spec.get("len", 0),
               frm=spec.get("from", 0), to=spec.get("to", 0), home=bool(spec.get("home", True)),
               side=spec.get("side", 0), seed=spec.get("seed", 0.0))
    if kind == "down":
        e.snap, e.bsnap = animator.snapshot()
    return e


def run_oracle_case(case, cap=QUEUE_CAP, palette=None):
    """Replay one oracle case; yields (step, ring e, buttons e, animator) per step.

    Persistent inputs: a step's ``view`` replaces them (and the reduced-motion flag ``rm``, BS).
    Effects are pushed in order before the step's draw with their own t0; then ``step(t, dt)``
    with the case's WARM/HOT/todB (RC) or ``palette`` (BS: the fixture's designConstants).
    """
    animator = AliveAnimator(cap)
    if palette is None:
        palette = design_palette(case["warm"], case["hot"])
    tod_b = case["todB"]
    targets = None
    song = None
    for step in case["steps"]:
        view = step.get("view")
        if view is not None:
            targets = oracle_targets(view)
            song = view.get("songProg")
            animator.reduced_motion = bool(view.get("rm"))
        for spec in step.get("effects", ()):
            animator.play(oracle_effect(spec, animator, palette))
        ring, buttons = animator.step(step["t"], step["dt"], targets, song, tod_b, palette)
        yield step, ring, buttons, animator


# ======================================================================= engine
DAY_MS = MINUTES_PER_DAY * 60000
MAX_DETENTS, MAX_LIMITS, MAX_PRESSES = 8, 4, 8     # queued per render (firmware arrays)


def _elapsed(now, start):
    return (now - start) & UINT32


def _reached(now, deadline):
    """now >= deadline on the uint32 clock (signed difference, wrap safe)."""
    return ((now - deadline) & UINT32) < 0x80000000


class Feedback:
    """One new feedback seq, classified (6.4 rows a-j need the previous frame, so the row is picked
    in ``_events``): kind, skip, moment, side, colour (raw 0xRRGGBB)."""

    __slots__ = ("kind", "skip", "moment", "side", "color")

    def __init__(self, kind, skip=0, moment=None, side=0, color=0):
        self.kind, self.skip, self.moment, self.side, self.color = kind, skip, moment, side, color


def started_colour(color, color_mode):
    """Row h [M16]: the ``started`` wash colour (sat rgb) or None for the green bloom."""
    if not color or not color_mode:
        return None
    return sat(rgb_tuple(color))


def moment_hold_ms(fb, color_mode):
    """[M22] the hold of a moment row (c-h), 0 for unlike and the flash rows."""
    if fb.kind != "ok" or fb.skip or fb.moment is None or fb.moment == "unlike":
        return 0
    if fb.moment == "started":
        return MOMENT_HOLD_MS["wash" if started_colour(fb.color, color_mode) is not None else "bloom"]
    return MOMENT_HOLD_MS[fb.moment]


class AliveLights:
    """The alive engine (section 4 API): owns targets, animator and event detection (section 6).

    Mirrors firmware ``CCAlive`` step for step (the twin replay compares both).
    """

    def __init__(self, now=0):
        self.animator = AliveAnimator()
        self.reset(now)

    # ------------------------------------------------------------ API
    def reset(self, now):
        """Power-up: offline state (8.1) with a reveal; clears every latch; next dt is 0."""
        now &= UINT32
        self.animator.reset()
        self.animator.reduced_motion = False
        self._presses, self._detents, self._limits = [], [], []
        self._claimed = self._boot_pending = self._seeding = False
        self._state_asleep = self._prev_asleep = False
        self._first_render = True
        self._last_render = now
        self._sleep_at = now
        self._flash = None
        self._flash_start = 0
        self._hold_ms = 0                            # [M22] the running moment hold (0 none)
        self._hold_start = 0
        self._last_seq = 0
        self._pending_on = False
        self._pending_start = 0
        self._prev_family = FAMILY_OFFLINE           # 6.4 memory of the last rendered claimed frame
        self._prev_style = None
        self._prev_cursor = 0
        self._prev_accent = None
        self._prev_external = False
        self._prev_playing = None
        self._vel = 0.0
        self._last_rot = 0
        self._has_rot = False
        self._clock = None                           # (minute, latched at)
        self._prog_pos = self._prog_dur = self._prog_at = 0
        self._home_playing = None                    # the last Home frame's playing (None absent)
        self._rng = RNG_SEED                         # [M5]
        self._pink_led = 0                           # [M24] latched ledPink (0 = the built-in PINK)
        self._vol_full = False                       # [M24] latched ledVolFull
        self.palette = ENGINE_PALETTE
        self.seeds = []                              # every scatter seed drawn (tests, twin replay)
        self.targets = offline_targets()
        self.song_prog = None
        self.tod_b = 1.0
        self.animator.play(Effect("reveal", now))

    def claim(self, now):
        """unclaimed -> claimed (ONLINE); counts as an input; boot on the first rendered frame."""
        if self._claimed:
            return
        now &= UINT32
        self._claimed = True
        self._boot_pending = self._seeding = True
        self._state_asleep = False
        self._sleep_at = (now + SLEEP_MS) & UINT32
        self._flash = None
        self._hold_ms = 0
        self._last_seq = 0
        self._pending_on = False
        self._presses, self._detents, self._limits = [], [], []
        self._vel = 0.0
        self._has_rot = False

    def release(self, now):
        """claimed -> unclaimed (OFFLINE): 'down' at the last claimed cursor, snapshot now."""
        if not self._claimed:
            return
        now &= UINT32
        self._claimed = False
        self._boot_pending = self._seeding = False
        self._state_asleep = False
        self._flash = None
        self._hold_ms = 0
        self._presses, self._detents, self._limits = [], [], []
        snap, bsnap = self.animator.snapshot()
        self.animator.play(Effect("down", now, at=self._prev_cursor, snap=snap, bsnap=bsnap))

    def detent(self, now, delta):
        if not self._claimed or type(delta) is not int or not delta:
            return
        now &= UINT32
        if len(self._detents) < MAX_DETENTS:
            self._detents.append([now, delta])
        else:
            last = self._detents[-1]
            last[0] = now
            last[1] += delta

    def limit(self, now, direction):
        if not self._claimed or not direction or len(self._limits) >= MAX_LIMITS:
            return
        self._limits.append([now & UINT32, 1 if direction > 0 else -1])

    def press(self, now, slot):
        if not self._claimed or type(slot) is not int or not 0 <= slot < BUTTON_SLOTS \
                or len(self._presses) >= MAX_PRESSES:
            return
        self._presses.append([now & UINT32, slot])

    def start_reveal(self, now):
        """Firmware ``startReveal`` (a reveal of whatever the engine draws). [M29] revision 2 has no
        5 s return from the native handover, so the integration no longer calls it; kept for the API."""
        self.animator.play(Effect("reveal", now & UINT32, at=0))

    def set_clock(self, now, minute):
        """Latched local minutes since midnight (int 0..1439; anything else is ignored)."""
        if type(minute) is int and 0 <= minute < MINUTES_PER_DAY:
            self._clock = (minute, now & UINT32)

    def set_progress(self, now, pos, dur):
        """Latched song progress in ms; dur 0 clears; pos is clamped to dur."""
        if type(pos) is not int or type(dur) is not int or pos < 0 or dur < 0:
            return
        if dur == 0:
            self._prog_pos = self._prog_dur = 0
            return
        self._prog_pos = min(pos, dur)
        self._prog_dur = dur
        self._prog_at = now & UINT32

    def set_reduced_motion(self, now, on):
        """[r2][M17] the latched ``reducedMotion`` (6.5): read by play() and by fail at draw time."""
        del now
        self.animator.reduced_motion = bool(on)

    def set_tuning(self, now, pink_led, vol_full):
        """[r2][M24] the latched ``ledPink`` (0 = the built-in PINK; else the LED colour at full, its
        OETF becomes PINK) and ``ledVolFull`` (semantic body / half-step at 1.00)."""
        del now
        pink_led = pink_led if type(pink_led) is int and 0 <= pink_led <= 0xFFFFFF else 0
        self._pink_led = pink_led
        self._vol_full = bool(vol_full)
        self.palette = ENGINE_PALETTE.with_pink(pink_from_led(pink_led))

    @property
    def reduced_motion(self):
        return self.animator.reduced_motion

    def asleep(self):
        return self.targets.asleep

    def cursor(self):
        return self.targets.cursor

    def lit_masks(self):
        """[user 2026-09-26] The F-T masks of the last render (section 9 step 4): (60 ring, 4 button)
        flags, true where the target is lit. Firmware ``CCAlive::output`` builds the same from its
        targets (``cc_alive_lit``). Test-only here: the desktop draws ``e``."""
        return lit_masks(self.targets)

    def animating(self):
        return self.animator.animating()

    def claimed(self):
        return self._claimed

    def hold_active(self, now):
        """[M22] holdActive: the flash window or a moment hold."""
        return self._flash is not None or (self._hold_ms and _elapsed(now & UINT32, self._hold_start) < self._hold_ms)

    def tod_brightness(self, now):
        """8.3 resting factor at ``now`` (1 without a latched clock), integer-ms clock."""
        if self._clock is None:
            return 1.0
        minute, at = self._clock
        ms = (minute * 60000 + _elapsed(now & UINT32, at) % DAY_MS) % DAY_MS
        return tod_brightness(ms / 3600000)

    # --------------------------------------------------------- render
    def render(self, now, frame=None, local_pos=None, local_max=None):
        """One frame: returns (ring e x60, buttons e x4) as (r, g, b) floats 0..1 (tone-mapped).

        ``frame`` is the last accepted host frame while claimed (ignored when unclaimed; None while
        claimed draws nothing). ``local_pos``/``local_max``: the knob position of the frame's control
        when it is ready (6.3), else None.
        """
        now &= UINT32
        dt = 0 if self._first_render else min(MAX_DT_MS, _elapsed(now, self._last_render))
        self._first_render = False
        self._last_render = now
        live = self._claimed and frame is not None
        family, pending, ext, playing, event, g = FAMILY_OFFLINE, False, False, None, None, None
        if live:
            pending_ms = self._onsets(frame, now)
            g = alive_geometry(frame, local_pos, local_max, pending_ms)
            family, pending, playing = g.family, g.pending, g.playing
            event = self._feedback(g, now)
            ext = (not self._seeding and self._prev_family == "home" and family == "home"
                   and not self._prev_external and g.external)
            if family == "home":
                self._song(now, playing)
        # The flash window (ok 650 ms, err 900 ms) and the moment hold are time-based: they also
        # end on a claimed render without a frame.
        if self._flash is not None and _elapsed(now, self._flash_start) >= FLASH_MS[self._flash]:
            self._flash = None
        if self._hold_ms and _elapsed(now, self._hold_start) >= self._hold_ms:
            self._hold_ms = 0
        holding = self._flash is not None or self._hold_ms != 0
        if self._claimed:                                  # 6.1: inputs, then the sleep timer
            for t, _ in self._presses:
                self._wake_input((t + SLEEP_MS) & UINT32)
            for t, _ in self._detents:
                self._wake_input((t + SLEEP_MS) & UINT32)
            for t, _ in self._limits:
                self._wake_input((t + SLEEP_MS) & UINT32)
            if ext:
                self._wake_input((now + SLEEP_EXTERNAL_MS) & UINT32)
            if not self._state_asleep and _reached(now, self._sleep_at):
                if pending or holding:
                    self._sleep_at = (now + SLEEP_RECHECK_MS) & UINT32
                else:
                    self._state_asleep = True
        sleeping = self._claimed and self._state_asleep and not pending and not holding
        if not self._claimed:
            targets = offline_targets()
        elif not live:
            targets = AliveTargets(family=FAMILY_OFFLINE)
        else:
            targets = alive_finish(g, sleeping, self._flash, self._vol_full, self.animator.reduced_motion)
        self.targets = targets
        self.tod_b = self.tod_brightness(now)
        self.song_prog = None
        # 8.4 [R3]: the hand needs the last Home frame's playing == true (absent is not playing).
        if live and sleeping and family == "home" and self._home_playing is True and self._prog_dur > 0:
            pos = (self._prog_pos + _elapsed(now, self._prog_at)) & UINT32
            self.song_prog = 1.0 if pos < self._prog_pos else cl(pos / self._prog_dur)
        if live:
            self._events(now, g, targets, sleeping, event, ext)
        self._presses, self._detents, self._limits = [], [], []
        self._prev_asleep = sleeping
        return self.animator.step(now, dt, targets, self.song_prog, self.tod_b, self.palette)

    # ------------------------------------------------------- internals
    def _wake_input(self, sleep_at):
        self._state_asleep = False
        self._sleep_at = sleep_at

    def _onsets(self, frame, now):
        """5.1.8: the pending onset of a selection / transport ring (revision 2 has no loading pulse)."""
        ring = frame.get("ring") if isinstance(frame.get("ring"), dict) else {}
        style, activity = ring.get("style"), frame.get("activity", "idle")
        pending = activity == "pending" and style in ("selection", "transport")
        if pending and not self._pending_on:
            self._pending_start = now
        self._pending_on = pending
        return _elapsed(now, self._pending_start) if pending else 0

    def _feedback(self, g, now):
        """v4 seq rules: a new valid seq is one event; the first frame after claim only seeds. It
        starts the flash (rows a, b, i, j) or the moment hold (rows c-h), which ``render`` expires."""
        feedback = g.frame.get("feedback")
        valid = (isinstance(feedback, dict) and feedback.get("kind") in FLASH_MS
                 and _int(feedback.get("seq"), 1, 0x7FFFFFFF, 0))
        if self._seeding:
            if valid:
                self._last_seq = feedback["seq"]
            return None
        if not valid or feedback["seq"] == self._last_seq:
            return None
        self._last_seq = feedback["seq"]
        kind = feedback["kind"]
        fb = Feedback(kind)
        if kind == "ok":
            skip = feedback.get("skip")
            fb.skip = skip if type(skip) is int and skip in (-1, 1) else 0
            moment = feedback.get("moment")
            fb.moment = moment if moment in FEEDBACK_MOMENTS else None
            if fb.moment == "snap":
                fb.side = -1 if feedback.get("side") == -1 else 1
            if fb.moment in ("snap", "started"):
                fb.color = _int(feedback.get("color", 0), 0, 0xFFFFFF, 0)
        hold = moment_hold_ms(fb, g.color_mode)
        if kind == "err" or fb.skip or fb.moment is None:
            self._flash, self._flash_start = kind, now       # rows a, b, i, j: the flash
            self._hold_ms = 0
        else:
            self._flash = None                               # rows c-h: no flash [M7]
            self._hold_ms, self._hold_start = hold, now      # [M22] (unlike: none)
        return fb

    def _song(self, now, playing):
        """8.4 latch on a Home frame [R3]: progress runs while it says playing:true and freezes
        otherwise; a missing ``playing`` (None) counts as not playing, exactly like false."""
        was_running, running = self._home_playing is True, playing is True
        if was_running and not running and self._prog_dur > 0:
            pos = (self._prog_pos + _elapsed(now, self._prog_at)) & UINT32
            self._prog_pos = self._prog_dur if pos < self._prog_pos or pos > self._prog_dur else pos
            self._prog_at = now
        if not was_running and running:
            self._prog_at = now
        self._home_playing = playing

    def _draw_seed(self):
        """[M5] one PRNG draw (also when reduced motion drops the scatter)."""
        self._rng = xorshift32(self._rng)
        seed = scatter_seed(self._rng)
        self.seeds.append(seed)
        return seed

    def _feedback_effect(self, now, g, cursor, fb):
        """6.4 row a-j (first match). Returns True when the row was h (started)."""
        play = self.animator.play
        if fb.kind == "err":                                               # a
            play(Effect("fail", now, at=cursor))
        elif fb.skip:                                                      # b [M21]
            play(Effect("sweep", now, at=self._prev_cursor, dir=fb.skip))
        elif fb.moment == "queued":                                        # c
            play(Effect("sweep", now, at=0, dir=1))
        elif fb.moment == "shuffle":                                       # d
            play(Effect("scatter", now, at=cursor, seed=self._draw_seed()))
        elif fb.moment == "like":                                          # e
            play(Effect("bloom", now, at=cursor, c=self.palette.pink))
        elif fb.moment == "unlike":                                        # f
            pass
        elif fb.moment == "snap":                                          # g
            s = sat(rgb_tuple(fb.color)) if fb.color and g.color_mode else None
            colour = _f(s) if s is not None else self.palette.warm
            play(Effect("half", now, at=cursor, c=colour, side=fb.side))
        elif fb.moment == "started":                                       # h [M16]
            s = started_colour(fb.color, g.color_mode)
            if s is not None:
                play(Effect("wash", now, at=cursor, c=_f(s)))
            else:
                play(Effect("bloom", now, at=cursor, c=self.palette.green))
            return True
        elif self._prev_family in LIST_FAMILIES and self._prev_accent is not None:   # i [D7][M10]
            play(Effect("wash", now, at=self._prev_cursor, c=_f(self._prev_accent)))
        else:                                                              # j
            play(Effect("bloom", now, at=cursor, c=self.palette.green))
        return False

    def _events(self, now, g, targets, sleeping, event, ext):
        play = self.animator.play
        cursor = targets.cursor
        family = g.family
        if self._boot_pending:                             # 6.4.5: boot, home = this frame's family
            play(Effect("boot", now, at=cursor, home=family == "home"))
            self._boot_pending = False
        for _, slot in self._presses:                      # 1. presses
            play(Effect("press", now, at=cursor, n=slot))
        if self._prev_asleep and not sleeping:             # 2. wake
            play(Effect("wake", now, at=cursor))
        for t, delta in self._detents:                     # 3. ticks (6.2)
            dtr = _elapsed(t, self._last_rot) if self._has_rot else VEL_GAP_MS + 1
            dtr = max(VEL_MIN_DT_MS, dtr)
            self._last_rot, self._has_rot = t, True
            self._vel = 0.0 if dtr > VEL_GAP_MS else self._vel * VEL_KEEP + VEL_NEW * (1000 * abs(delta) / dtr)
            direction = 0 if self._seeding else sign(cd(cursor, self._prev_cursor))
            direction = direction or (1 if delta > 0 else -1)
            length = js_round(cl((self._vel - TICK_VEL0) / TICK_VEL_SPAN) * TICK_LEN_MAX + TICK_TIE_BIAS)   # [D19]
            play(Effect("tick", now, at=cursor, dir=direction, len=length))
        for _, direction in self._limits:                  # 3. bounds, no tick [D4]
            target = targets.ring[cursor]
            if target is None or target.role == ROLE_WARM:
                colour = self.palette.warm
            elif target.role == ROLE_PINK:
                colour = self.palette.pink
            else:
                colour = target.col
            play(Effect("bound", now, at=cursor, dir=direction, c=colour))
        if not self._seeding:                              # 4. frame-derived events (6.4)
            style = g.style
            if family != self._prev_family or (
                    family == "tracks" and style != self._prev_style
                    and {style, self._prev_style} == {"transport", "lap"}):
                play(Effect("reveal", now, at=cursor))     # MODE [r2] incl. Seek enter / exit
            started = False
            if event is not None:
                started = self._feedback_effect(now, g, cursor, event)
            if not started and self._prev_family == "home" and family == "home" \
                    and self._prev_playing is not None and g.playing is not None \
                    and g.playing != self._prev_playing:   # PLAY/PAUSE [D8] (not with started, M16)
                play(Effect("fill" if g.playing else "drain", now, at=cursor, n=(g.value + 1) // 2))
            if ext:                                                            # EXT
                play(Effect("shimmer", now, at=cursor, frm=self._prev_cursor, to=cursor))
        self._prev_family, self._prev_style, self._prev_cursor = family, g.style, cursor
        self._prev_accent, self._prev_external, self._prev_playing = g.accent, g.external, g.playing
        self._seeding = False


# ================================================================ local input (HMI)
LIM_REARM_MS = 75           # [Q1] ALIVE.md 12.5 lim_rearm_ms (tuned in the turning test, 40-150 ms)
LIM_GAP_MS = 150            # lim_gap_ms: the ring's bound and the wire lim stay one-to-one


class AliveKnob:
    """Twin of the firmware HMI's local-input sampler ``CCAliveKnob`` (ALIVE.md 6.2, [F1/W2], [Q1]).

    A detent is a position change of the same ready control between two samples of one ready
    interval; the first sample of a control, and every sample after ``reset()``, only seeds. A limit
    fires when ``pushing`` (the FOC at the limit AND its attractor moved past the bound) rises from
    false, provided it has been false for >= 75 ms since the last sample that saw it true (the first
    push after arriving fires at once) and >= 150 ms passed since the previous fire; dir -1 at 0,
    +1 at max. The desktop engine gets limits from the wire ``lim`` instead; this twin exists for
    the 11.4 twin replay of the push detector.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.id = 0
        self.pos = self.max = 0
        self.valid = False
        self._pushing = self._push_seen = self._fired = False
        self._push_at = self._fire_at = 0

    def sample(self, now, control_id, pos, pushing, maximum):
        """One pass: returns (delta, limit)."""
        now &= UINT32
        if not control_id:
            self.reset()
            return 0, 0
        delta = limit = 0
        if control_id == self.id:
            delta = pos - self.pos
            if pushing and not self._pushing:
                rearmed = not self._push_seen or _elapsed(now, self._push_at) >= LIM_REARM_MS
                spaced = not self._fired or _elapsed(now, self._fire_at) >= LIM_GAP_MS
                direction = -1 if pos == 0 else (1 if pos >= maximum else 0)
                if rearmed and spaced and direction:
                    limit = direction
                    self._fired, self._fire_at = True, now
        else:
            self._push_seen = self._fired = False
        if pushing:
            self._push_seen, self._push_at = True, now
        self.id, self.pos, self.max = control_id, pos, maximum
        self._pushing = bool(pushing)
        self.valid = True
        return delta, limit


__all__ = [
    "LIM_REARM_MS", "LIM_GAP_MS", "AliveKnob",
    "WARM", "HOT", "GREEN", "RED", "AMBER", "BLUE", "PINK", "ROLE_COLOUR", "CLASSES", "CLASS_S", "CLASS_P",
    "CLASS_N", "CLASS_Q", "DUR", "FG", "QUEUE_CAP", "TOD_KEYFRAMES", "HEAT_PERIODS", "ENGINE_PALETTE", "Palette",
    "design_palette", "bs_palette", "js_round", "md", "cd", "cl", "eo", "eio", "gs", "bump", "mix", "phase",
    "sat", "tone", "srgb_eotf", "srgb_oetf", "transfer", "tod_brightness", "clock_hour", "DEFAULT_DRIVE",
    "POWER_BUDGET", "effective_drive", "reference_output", "pink_from_led", "xorshift32", "scatter_seed",
    "DEFAULT_DITHER", "floor_pixel", "lit_masks",
    "Cell", "AliveTargets", "AliveGeometry", "offline_targets", "apply_local", "alive_geometry",
    "alive_finish", "alive_targets", "frame_family", "ring_window", "button_tone_v5", "pulse_class",
    "ring_alpha", "Effect", "AliveAnimator", "oracle_targets", "oracle_effect", "run_oracle_case",
    "AliveLights",
]
