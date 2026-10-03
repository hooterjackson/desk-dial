"""alive LED engine (control_center.alive_lights) against ALIVE.md revision 2 and both design oracles.

Contract: firmware/ALIVE.md (revision 2). Layers are tested on their own: helpers and
constants, targets (section 5 + 6.3, written out from the contract text: the M13 half-step, the M2
value gate, the M9 / M15 window, lists M3, Up next M14, the lap, the M18 button tones), animator
(sections 7-8, design draw()), engine events (section 6 with the r2 moments, reduced motion, the
M22 hold, tuning), time of day, song hand, the effect queue and the HMI sampler twin with the Q1
push detector. The ORACLE tests replay tests/fixtures/alive_oracle.json (tests/js/alive_oracle.cjs,
the RC draw()) and tests/fixtures/alive_oracle_bs.json (tests/js/alive_oracle_bs.cjs, the r2.1
Browse and Snap draw(), 11.2) through AliveAnimator and compare every tone-mapped value of every
step within the fixture's tolerance; both fixtures are required.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center import alive_lights as al  # noqa: E402
from control_center import preview_lights as pl  # noqa: E402
from control_center import presentation as P  # noqa: E402

ORACLE = ROOT / "tests" / "fixtures" / "alive_oracle.json"
BS_ORACLE = ROOT / "tests" / "fixtures" / "alive_oracle_bs.json"
Cell = al.Cell
WARM, AMBER, RED, GREEN, BLUE = al.WARM, al.AMBER, al.RED, al.GREEN, al.BLUE
S = al.CLASS_S


def f(rgb):
    return tuple(x / 255 for x in rgb)


def warm(cls, alpha):
    return Cell(WARM, al.ROLE_WARM, cls, alpha)


# ------------------------------------------------------------------ frame builders
def _buttons(*spec):
    return [{"label": label, "enabled": enabled, "icon": icon} for label, enabled, icon in spec]


HOME_BUTTONS = _buttons(("Pause", True, "pause"), ("Browse", True, "list"), ("Win", True, "win"),
                        ("Tracks", True, "tracks"))
PAUSED_BUTTONS = _buttons(("Play", True, "play"), ("Browse", True, "list"), ("Win", True, "win"),
                          ("Tracks", True, "tracks"))
LIST_BUTTONS = _buttons(("Back", True, "back"), ("Home", True, "home"), ("Win", True, "win"),
                        ("Play", True, "play"))
WINDOWS_BUTTONS = _buttons(("Cancel", True, "cancel"), ("Home", True, "home"), ("Win", True, "win"),
                           ("Switch", True, "switch"))


def home_frame(v=54, c=None, led="color", external=False, activity="idle", layout="nowPlaying",
               buttons=HOME_BUTTONS, **extra):
    frame = {"id": 1, "mode": "VOLUME", "target": "Hall", "value": f"{v}%", "detail": "", "status": "",
             "activity": activity, "layout": layout, "ledStyle": led,
             "confirmedVolume": v if c is None else c, "buttons": buttons,
             "ring": {"style": "level", "value": v, "index": 0, "count": 101, "external": external}}
    frame.update(extra)
    return frame


def accent(j):
    return 0xC00000 | (2 * j) << 8 | (0xFF - j)   # distinct, saturated, never white


def list_frame(count=10, index=2, windows=False, led="color", colors="auto", unavailable=0, more=-1,
               activity="idle", first="auto", buttons=None, **extra):
    ring = {"style": "selection", "value": 0, "index": index, "count": count,
            "unavailable": unavailable, "moreIndex": more}
    start = P.window_first(index, count) if first == "auto" else first
    if first is not None:
        ring["first"] = start
    else:
        start = P.window_first(index, count)
    if colors == "auto":
        colors = [accent(j) for j in range(start, start + min(20, count - start))]
    if colors is not None:
        ring["colors"] = colors
    frame = {"id": 1, "mode": "WINDOWS" if windows else "RECENTLY ADDED", "target": "Hall", "value": "",
             "detail": "", "status": "", "activity": activity, "layout": "windows" if windows else "recent",
             "ledStyle": led, "buttons": buttons or (WINDOWS_BUTTONS if windows else LIST_BUTTONS),
             "ring": ring}
    frame.update(extra)
    return frame


def tracks_frame(index=1, no_prev=False, activity="idle", **extra):
    frame = {"id": 1, "mode": "TRACKS", "target": "Hall", "value": "", "detail": "", "status": "",
             "activity": activity, "layout": "tracks", "ledStyle": "color", "buttons": LIST_BUTTONS,
             "ring": {"style": "transport", "value": 0, "index": index, "count": 3,
                      "unavailable": 1 if no_prev else 0}}
    frame.update(extra)
    return frame


def slot(j, count):
    return ((j - (count - 1) // 2) * 3) % 60


def sat_accent(j):
    return al.sat(al.rgb_tuple(accent(j)))


def lit(cells):
    return {i: c for i, c in enumerate(cells) if c is not None}


# Contract tables written out independently of the module (section 5.2, revision 2).
# [r3] ALIVE.md 15.3: the Lights classes T 0.08, R 0.12, O 0.18, L 0.34, F 0.50 (both tables).
R3_AWAKE = {"T": 0.08, "R": 0.12, "O": 0.18, "L": 0.34, "F": 0.50, "M": 0.10,   # [r3] 15.7 M: the marker ring
            "W": 0.60}                                                        # [r3.1] 15.9 W: the queue's playing row
AWAKE_WARM = {"P": 0.14, 1: 0.30, "Q": 0.45, 2: 0.62, "N": 0.70, "S": 0.81, 3: 1.0, 4: 1.0, **R3_AWAKE}
AWAKE_SEMANTIC = {"P": 0.14, 1: 0.45, "Q": 0.45, 2: 0.62, "N": 0.70, "S": 0.81, 3: 1.0, 4: 1.0, **R3_AWAKE}
# [user 2026-09-26, ALIVE.md 12.8] resting = one steady dim warm white: every class at 0.34 (was BS's
# 0.05 / 0.10 / 0.16 and D10's 0.13); time of day never dims it below 0.80.
RESTING = {"P": 0.34, 1: 0.34, "Q": 0.34, 2: 0.34, "N": 0.34, "S": 0.34, 3: 0.34, 4: 0.34,
           "T": 0.0, "R": 0.0, "O": 0.0, "L": 0.34, "F": 0.34,   # [r3] 15.3: the unfilled Lights cells rest dark
           "M": 0.0,                                             # [r3] 15.7: the marker ring's rest of the arc
           "W": 0.34}                                            # [r3.1] 15.9: the queue's playing row rests lit
REST_TOD_MIN = 0.80


# ======================================================================= helpers
class HelperTests(unittest.TestCase):
    def test_palette_constants(self):
        """ALIVE.md section 2 as corrected by R5: float design-space constants, the firmware's
        CCAliveSpec values; WARM / AMBER are the sRGB OETF of the user's LED picks."""
        self.assertEqual(al.WARM, (1.0, 0.746862, 0.411645))
        self.assertEqual(al.HOT, (1.0, 0.746862, 0.411645))     # [user 2026-09-26] HOT == WARM
        self.assertEqual((al.GREEN, al.RED, al.AMBER, al.BLUE),
                         ((0.0, 1.0, 98 / 255), (1.0, 0.0, 0.0), (1.0, 0.514232, 0.218649),
                          (40 / 255, 140 / 255, 1.0)))
        for colour in (al.WARM, al.HOT, al.GREEN, al.RED, al.AMBER, al.BLUE):
            self.assertTrue(all(type(x) is float for x in colour), colour)       # never rounded ints

        def oetf(c):
            return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
        for value, pick in ((al.WARM, (255, 132, 36)), (al.AMBER, (255, 58, 10))):
            for got, led in zip(value, pick):
                self.assertAlmostEqual(got, oetf(led / 255), delta=1e-6)          # 6 significant digits
        self.assertEqual(al.HOT, al.WARM)       # [user 2026-09-26] was mix(WARM, white, 0.5)
        self.assertEqual(al.ROLE_COLOUR, {"warm": al.WARM, "green": al.GREEN, "red": al.RED,
                                          "amber": al.AMBER, "blue": al.BLUE, "pink": al.PINK})
        # [r2][M25] PINK: the candidate 255,40,90 in design space (never sat(): sat() would give 255,11,68).
        self.assertEqual(al.PINK, (1.0, 40 / 255, 90 / 255))
        self.assertEqual(al.sat((255, 40, 90)), (255, 11, 68))
        engine = al.ENGINE_PALETTE
        self.assertEqual((engine.warm, engine.hot), (WARM, al.HOT))              # stored, not re-derived
        self.assertEqual((engine.green, engine.red, engine.blue, engine.amber, engine.pink),
                         (GREEN, RED, BLUE, AMBER, al.PINK))
        design = al.design_palette((1, 0.6, 0.3), (1, 0.8, 0.65))
        self.assertEqual((design.green, design.red, design.blue),
                         ((0, 1, 0.384), (1, 0.094, 0), (0.157, 0.549, 1)))

    def test_timing_and_level_constants(self):
        self.assertEqual(al.DUR, {"boot": 2800, "down": 1800, "wake": 520, "tick": 180, "bound": 460,
                                  "bloom": 900, "fail": 700, "sweep": 640, "fill": 760, "drain": 860,
                                  "shimmer": 1000, "wash": 1100, "reveal": 450, "press": 220, "pending": 2800,
                                  "half": 900, "scatter": 700})
        self.assertEqual(al.FG, {"boot", "down", "bloom", "fail", "sweep", "fill", "drain", "shimmer", "wash",
                                 "half", "scatter"})
        self.assertEqual(al.REDUCED_MOTION_DROP, {"wake", "tick", "sweep", "scatter", "reveal"})
        self.assertEqual(al.QUEUE_CAP, 8)
        self.assertEqual((al.ALPHA_AWAKE_WARM, al.ALPHA_AWAKE_SEMANTIC, al.ALPHA_REST),
                         (AWAKE_WARM, AWAKE_SEMANTIC, RESTING))
        self.assertEqual(al.REST_TOD_MIN, REST_TOD_MIN)                 # [user 2026-09-26]
        self.assertEqual(al.ALPHA_VOL_FULL, {2: 1.0, "S": 1.0})
        # [r2.2][M32] the liked heart is tone `liked` (VOC 1.2 CCButtonTone 7): PINK 0.30, not 1.0.
        self.assertEqual(al.BUTTON_TONES, {"dim": ("warm", 1, 0.14), "stop": ("red", 2, 1.0), "liked": ("pink", 1, 0.30),
                                           "on": ("warm", 3, 1.0), "off": ("warm", 1, 0.30), "go": ("green", 3, 1.0),
                                           "paused": ("green", 3, 1.0), "nav": ("warm", 2, 0.70),
                                           "active": ("warm", 3, 0.90)})   # [r3] 15.4
        self.assertEqual((al.BUTTON_REST_HIGH, al.BUTTON_REST_LOW, al.BUTTON_REST_SPLIT), (0.34, 0.26, 0.5))   # [user 2026-09-26]
        self.assertEqual(al.MOMENT_HOLD_MS, {"queued": 640, "shuffle": 700, "like": 900, "snap": 900, "wash": 1100,
                                             "bloom": 900})
        self.assertEqual((al.SCATTER_ORDER, al.RNG_SEED), ((0, 4, 8, 3, 7, 2, 6, 1, 5), 0x2545F491))
        self.assertEqual((al.SLEEP_MS, al.SLEEP_EXTERNAL_MS, al.SLEEP_RECHECK_MS, al.MAX_DT_MS),
                         (5000, 3200, 1000, 50))

    def test_js_round_is_half_toward_plus_infinity(self):
        cases = {2.5: 3, -2.5: -2, -0.5: 0, 0.5: 1, 1.4999999: 1, -1.5: -1, 0.49999999999999994: 0,
                 7: 7, -7: -7, 5.5: 6, -5.500001: -6}
        for x, want in cases.items():
            with self.subTest(x=x):
                self.assertEqual(al.js_round(x), want)

    def test_md_follows_the_js_remainder(self):
        def js_md(i):                    # ((Math.round(i) % 60) + 60) % 60 with fmod
            r = al.js_round(i)
            return math.fmod(math.fmod(r, 60) + 60, 60)
        for i in (-121, -61, -60.5, -60, -59.5, -1, -0.5, 0, 0.5, 2.5, 59, 59.5, 60, 61, 119.49, 180):
            with self.subTest(i=i):
                self.assertEqual(al.md(i), js_md(i))
        self.assertEqual((al.md(-1), al.md(60), al.md(2.5), al.md(-0.5), al.md(-60.5)), (59, 0, 3, 0, 0))

    def test_cd_follows_the_js_remainder(self):
        def js_cd(i, j):
            return math.fmod(math.fmod(i - j, 60) + 90, 60) - 30
        for i in range(-70, 71, 7):
            for j in (0, 5, 29, 30, 31, 59):
                with self.subTest(i=i, j=j):
                    self.assertEqual(al.cd(i, j), js_cd(i, j))
        for x in (10.5, -10.5, 29.5, 30.5, -29.5, -30.5, 59.25):
            self.assertAlmostEqual(al.cd(x, 0), js_cd(x, 0), places=12)
        self.assertEqual((al.cd(0, 59), al.cd(59, 0), al.cd(30, 0), al.cd(0, 30)), (1, -1, -30, -30))

    def test_easing_helpers_match_the_design_formulas(self):
        for u in (-0.2, 0, 0.1, 0.25, 0.5, 0.75, 0.99, 1, 1.3):
            c = min(1, max(0, u))
            self.assertAlmostEqual(al.eo(u), 1 - (1 - c) ** 3, places=15)
            self.assertAlmostEqual(al.eio(u), 4 * c ** 3 if c < 0.5 else 1 - (-2 * c + 2) ** 3 / 2, places=15)
        self.assertEqual(al.gs(0, 3), 1)
        self.assertAlmostEqual(al.gs(3, 3), math.exp(-0.5), places=15)
        self.assertEqual((al.bump(99, 100, 200), al.bump(201, 100, 200)), (0, 0))
        self.assertAlmostEqual(al.bump(150, 100, 200), 1, places=15)
        self.assertEqual(al.mix((0, 0.5, 1), (1, 1, 1), 0.5), (0.5, 0.75, 1.0))
        self.assertEqual((al.phase(5200 * 7 + 1300, 5200), al.phase(0, 1400)), (0.25, 0))

    def test_sat(self):
        self.assertIsNone(al.sat((100, 110, 120)))            # max - min < 30: WARM
        self.assertIsNone(al.sat((0, 0, 29)))
        self.assertIsNone(al.sat((0, 0, 0)))
        self.assertEqual(al.sat((0, 0, 30)), (0, 0, 255))
        self.assertEqual(al.sat((255, 0, 0)), (255, 0, 0))
        self.assertEqual(al.sat((0, 255, 98)), (0, 255, 98))
        self.assertEqual(al.sat((88, 101, 242)), (32, 51, 255))   # Discord fallback colour
        self.assertEqual(al.sat((217, 119, 87)), (255, 90, 37))
        # A warm-looking frame colour is an ordinary accent: classification never compares values.
        self.assertEqual(al.sat((255, 189, 105)), (255, 160, 38))
        for c in ((12, 200, 44), (250, 251, 90), (60, 60, 200), (199, 23, 180)):
            got = al.sat(c)
            mn, mx = min(c), max(c)
            want = tuple(math.floor(max(0, x - mn * 0.75) / (mx - mn * 0.75) * 255 + 0.5) for x in c)
            self.assertEqual(got, want)
            self.assertTrue(all(type(x) is int for x in got))
            self.assertEqual(max(got), 255)

    def test_sat_rounds_half_away_from_zero(self):
        # 1/102*255 == 2.5 exactly in binary64: the half rounds up.
        self.assertEqual(1 / 102 * 255, 2.5)
        self.assertEqual(al.sat((102, 1, 0)), (255, 3, 0))

    def test_tone_map_knee(self):
        self.assertEqual(al.tone(0.78, 0.5, 0.1), (0.78, 0.5, 0.1))
        r, g, b = al.tone(1.0, 0.5, 0.25)
        k = 0.78 + 0.22 * (1 - math.exp(-(1 - 0.78) / 0.22))
        self.assertAlmostEqual(r, k, places=15)
        self.assertAlmostEqual(g / r, 0.5, places=15)      # hue kept
        self.assertAlmostEqual(b / r, 0.25, places=15)
        self.assertLess(al.tone(3, 0, 0)[0], 1.0)

    def test_srgb_eotf(self):
        self.assertEqual((al.srgb_eotf(0), al.srgb_eotf(1), al.srgb_eotf(-0.2), al.srgb_eotf(1.5)), (0, 1, 0, 1))
        self.assertEqual(al.srgb_eotf(0.04045), 0.04045 / 12.92)
        self.assertAlmostEqual(al.srgb_eotf(0.5), ((0.5 + 0.055) / 1.055) ** 2.4, places=15)
        self.assertAlmostEqual(al.srgb_eotf(0.5), 0.21404, places=5)
        self.assertIs(al.transfer, al.srgb_eotf)
        values = [al.srgb_eotf(k / 255) for k in range(256)]
        self.assertEqual(values, sorted(values))

    def test_palette_led_values_under_the_transfer(self):
        """Section 2's LED column through section 9 (sRGB EOTF [D3], drive, dither off).

        At drive 255 WARM is #FF8424 and AMBER #FF3A0A exactly (the user's picks), RED #FF0000,
        on a ring LED and a button. At the default drive 150 the picks land within 1 count per
        channel of the warmth test's wire bytes: the native profile showed them at FastLED
        brightness 150, i.e. FastLED 3.6 scale8 with FASTLED_SCALE8_FIXED 1, (c * 151) >> 8.
        Mirrors alive_tests.cpp outputChecks().
        """
        dark = [(0.0, 0.0, 0.0)] * 60
        dark_buttons = [(0.0, 0.0, 0.0)] * 4

        def out(colour, drive):
            ring, buttons = al.reference_output([colour] + dark[1:], [dark_buttons[0], colour] + dark_buttons[2:],
                                                drive)
            self.assertEqual(ring[0], buttons[1])
            return ring[0]
        self.assertEqual(out(WARM, 255), 0xFF8424)
        self.assertEqual(out(AMBER, 255), 0xFF3A0A)
        self.assertEqual(out(RED, 255), 0xFF0000)
        self.assertEqual(out(al.HOT, 255), 0xFF8424)                  # [user 2026-09-26] HOT == WARM
        self.assertEqual(out(GREEN, 255), 0x00FF1F)                    # section 2: approximately #00FF1F

        def scale8(c, scale=150):
            return (c * (1 + scale)) >> 8
        for pick, colour in ((0xFF8424, WARM), (0xFF3A0A, AMBER), (0xFF0000, RED)):
            got = out(colour, 150)
            with self.subTest(pick=f"#{pick:06X}", got=f"#{got:06X}"):
                for shift in (16, 8, 0):
                    self.assertLessEqual(abs((got >> shift & 255) - scale8(pick >> shift & 255)), 1)
        self.assertEqual((out(WARM, 150), out(AMBER, 150)), (0x964E15, 0x962206))   # (150,78,21), (150,34,6)
        self.assertEqual((scale8(0xFF), scale8(0x84), scale8(0x24)), (150, 77, 21))

    def test_power_budget_is_the_warmth_test_load(self):
        """[D17][R5] B = 68 * (255 + 132 + 36) * 150 / 255 = 16920 exactly: 68 LEDs at WARM at drive
        150 sum to B, so they are not scaled, and every LED is (150, 78, 21)."""
        self.assertEqual(68 * (255 + 132 + 36) * 150, 16920 * 255)
        self.assertEqual(al.POWER_BUDGET, 16920)
        load = 68 * sum(al.srgb_eotf(x) for x in WARM) * al.DEFAULT_DRIVE
        self.assertAlmostEqual(load, 16920, delta=0.05)
        ring, buttons = al.reference_output([WARM] * 60, [WARM] * 4)
        self.assertEqual(set(ring) | set(buttons), {0x964E15})

    def test_reference_output_dither_off(self):
        dark = [(0.0, 0.0, 0.0)] * 60
        self.assertEqual(al.reference_output(dark, [(0.0, 0.0, 0.0)] * 4), ([0] * 60, [0] * 4))
        one = [(1.0, 1.0, 1.0)] + dark[1:]
        ring, buttons = al.reference_output(one, [(1.0, 0.0, 0.0)] + [(0.0, 0.0, 0.0)] * 3)
        self.assertEqual((ring[0], ring[1], buttons[0]), (0x969696, 0, 0x960000))      # drive 150
        e = 0.5
        v = al.srgb_eotf(e) * 150
        self.assertEqual(al.reference_output([(e, e, e)] + dark[1:], [(0.0,) * 3] * 4)[0][0],
                         math.floor(v + 0.5) * 0x010101)
        self.assertEqual(al.POWER_BUDGET, 16920.0)
        full, _ = al.reference_output([(1.0, 1.0, 1.0)] * 60, [(0.0,) * 3] * 4)
        self.assertEqual(full[0], 0x5E5E5E)                  # S 27000 > 16920: 150 * 16920 / 27000 = 94
        _, lit_buttons = al.reference_output(dark, [(1.0, 1.0, 1.0)] * 4, drive=255)
        self.assertEqual(lit_buttons, [0xFFFFFF] * 4)        # 8 LEDs * 3 * 255 = 6120: no limit
        self.assertEqual((al.effective_drive(), al.effective_drive(None, 51), al.effective_drive(200, 180),
                          al.effective_drive(90)), (150, 51, 180, 90))

    def test_time_of_day_keyframes(self):
        for hour, factor in al.TOD_KEYFRAMES:
            self.assertAlmostEqual(al.tod_brightness(hour), factor, places=15)
        self.assertAlmostEqual(al.tod_brightness(6.5), 0.775, places=12)
        self.assertAlmostEqual(al.tod_brightness(15), 1.0, places=12)
        self.assertAlmostEqual(al.tod_brightness(23.25), 0.6, places=12)
        # No half-hour rounding [D18]: 21:25 is 21.41667 h, not 21.5.
        hour = al.clock_hour(21 * 60 + 25, 0)
        self.assertAlmostEqual(hour, 21 + 25 / 60, places=12)
        self.assertAlmostEqual(al.tod_brightness(hour), 0.85 - 0.2 * (hour - 20) / 2.5, places=12)
        # Elapsed time advances the clock and wraps at midnight.
        self.assertAlmostEqual(al.clock_hour(1439, 120000), 1 / 60, places=12)
        self.assertAlmostEqual(al.clock_hour(600, 90 * 60000), 11.5, places=12)

    def test_heat_periods_are_whole_ms(self):
        self.assertEqual(len(al.HEAT_PERIODS), 60)
        for i, period in enumerate(al.HEAT_PERIODS):
            self.assertIs(type(period), int)
            self.assertLessEqual(abs(period - 2 * math.pi * (380 + (i * 97) % 260)), 0.5)
        self.assertEqual(al.HEAT_PERIODS[:2], (2388, 2997))


# ======================================================================= output floor
JS_ORACLES = (ROOT / "tests" / "js" / "alive_oracle.cjs", ROOT / "tests" / "js" / "alive_oracle_bs.cjs")
DARK = (0.0, 0.0, 0.0)


def counts_to_e(v, drive=255):
    """Design-space e whose section 9 value at ``drive`` is ``v`` counts per channel (no power limit)."""
    return tuple(al.srgb_oetf(x / drive) if x > 0 else 0.0 for x in v)


def one_led(v, lit, drive=255, segment=17, slot=2):
    """reference_output with one ring segment and one button slot at ``v`` counts, both flagged ``lit``."""
    ring, buttons = [DARK] * 60, [DARK] * 4
    ring[segment] = buttons[slot] = counts_to_e(v, drive)
    ring_lit = [i == segment and lit for i in range(60)]
    button_lit = [j == slot and lit for j in range(4)]
    out_ring, out_buttons = al.reference_output(ring, buttons, drive, ring_lit, button_lit)
    plain_ring, plain_buttons = al.reference_output(ring, buttons, drive)
    return out_ring[segment], out_buttons[slot], plain_ring[segment], plain_buttons[slot]


class OutputFloorTests(unittest.TestCase):
    """[user 2026-09-26] ALIVE.md section 9 step 4 and 12.7: the knob's temporal dither is off by
    default, and dither off applies rule F-T to the LEDs whose target is lit: a lit LED whose plain
    rounding is dark while m = max v > 0 shows one count on its dominant channel (v_c == m; a tie
    lights each tied channel), the byte plain rounding shows just above m = 0.5 (the channel rule
    amended the same day). The Python twin of firmware cc_alive_output (alive_tests.cpp floorChecks)
    and of the oracles' referenceOutput()."""

    def test_dither_is_off_by_default(self):
        self.assertIs(al.DEFAULT_DITHER, False)

    def test_floor_unit_cases(self):
        cases = [
            ((0.498, 0.238, 0.208), True, 0x010000),      # the dim WARM mark: dominant only
            ((0.0, 0.314, 0.124), True, 0x000100),        # a dim GREEN
            ((0.3, 0.154, 0.066), True, 0x010000),        # a dim AMBER: its dominant red only (not #010100)
            ((0.2, 0.2, 0.05), True, 0x010100),           # equal dominant channels both light
            ((0.11, 0.06, 0.11), True, 0x010001),         # a red / blue tie lights both, green stays 0
            ((0.498, 0.238, 0.208), False, 0),            # an unlit tail stays dark
            ((0.0, 0.0, 0.0), True, 0),                   # m = 0 stays dark
            ((0.8, 0.45, 0.0), True, 0x010000),           # visible: plain rounding, no floor
            ((0.52, 0.3, 0.3), True, 0x010000),           # m just above 0.5: plain
        ]
        for v, lit, want in cases:
            with self.subTest(v=v, lit=lit):
                ring, button, plain_ring, plain_button = one_led(v, lit)
                self.assertEqual((ring, button), (want, want))
                if max(v) < 0.5:
                    self.assertEqual((plain_ring, plain_button), (0, 0))    # no masks: no floor

    def test_floor_pixel(self):
        self.assertEqual(al.floor_pixel((0.498, 0.238, 0.208)), (1, 0, 0))
        self.assertEqual(al.floor_pixel((0.25, 0.125, 0.0)), (1, 0, 0))     # m / 2 no longer lights
        self.assertEqual(al.floor_pixel((0.25, 0.2499, 0.0)), (1, 0, 0))    # nearly a tie: still the dominant only
        self.assertEqual(al.floor_pixel((0.25, 0.25, 0.0)), (1, 1, 0))      # a tie lights both
        self.assertEqual(al.floor_pixel((0.1, 0.1, 0.1)), (1, 1, 1))
        self.assertEqual(al.floor_pixel((0.0, 0.0, 0.0)), (0, 0, 0))
        self.assertEqual(al.floor_pixel((1e-30, 0.0, 5e-31)), (1, 0, 0))

    def test_the_floor_is_plain_rounding_just_above_half_a_count(self):
        """[12.7 amendment] The floored byte is what plain rounding shows once the same colour reaches
        m = 0.5 (in the EOTF's linear toe a mark's channel ratios stay put while it breathes), so a mark
        breathing through half a count passes through the floor without a jump."""
        for v in ((0.3, 0.154, 0.066), (0.4, 0.374, 0.2), (0.2, 0.2, 0.05), (0.11, 0.06, 0.11), (0.0, 0.314, 0.124),
                  (0.49, 0.2449, 0.0)):
            with self.subTest(v=v):
                m = max(v)
                above = tuple(math.floor(x * (0.5 + 1e-9) / m + 0.5) for x in v)
                self.assertEqual(al.floor_pixel(v), above)

    def test_floor_applies_after_the_power_limit(self):
        """59 lit segments at full white and a dim WARM segment 59: S = 26550 > B scales the dim
        segment to (0.38, 0.28, 0.15) counts and the floor lights its red (1, 0, 0) (floorChecks)."""
        ring = [(1.0, 1.0, 1.0)] * 59 + [tuple(x * 0.05 for x in WARM)]
        out, _ = al.reference_output(ring, [DARK] * 4, 150, [True] * 60, [False] * 4)
        plain, _ = al.reference_output(ring, [DARK] * 4, 150)
        self.assertEqual((out[59], plain[59], out[0]), (0x010000, 0, 0x606060))
        with self.assertRaises(ValueError):
            al.reference_output(ring, [DARK] * 4, 150, [True] * 59, [False] * 4)

    def test_lit_masks_follow_the_targets(self):
        rig = Rig(0)
        ring_lit, button_lit = rig.eng.lit_masks()
        self.assertEqual(ring_lit, [i % al.OFFLINE_PITCH == 0 for i in range(60)])    # the offline marks
        self.assertEqual(button_lit, [False] * 4)
        rig.claim(1000, home_frame(54))
        rig.render(1016)
        ring_lit, button_lit = rig.eng.lit_masks()
        tg = rig.eng.targets
        self.assertEqual(ring_lit, [c is not None and c.alpha > 0 for c in tg.ring])
        self.assertEqual(button_lit, [c is not None and c.alpha > 0 for c in tg.buttons])
        self.assertTrue(any(ring_lit) and all(button_lit))
        self.assertEqual(al.lit_masks(tg), (ring_lit, button_lit))

    def test_offline_marks_stay_visible_through_the_breath(self):
        """The 12 amber marks at the dim point of the offline breath round to dark without the floor;
        with it (the default) every mark stays lit and the unlit segments stay dark."""
        eng = al.AliveLights(0)
        floored = 0
        for now in range(0, 6001, 16):
            ring_e, button_e = eng.render(now)
            ring, buttons = al.reference_output(ring_e, button_e, 150, *eng.lit_masks())
            plain, _ = al.reference_output(ring_e, button_e, 150)
            for i in range(60):
                if i % al.OFFLINE_PITCH:
                    self.assertEqual(ring[i], plain[i])
                    continue
                if now >= 1000:
                    self.assertNotEqual(ring[i], 0, (now, i))
                floored += ring[i] != plain[i]
            self.assertEqual(buttons, [0] * 4)
        self.assertGreater(floored, 100)

    def test_the_floor_is_continuous_through_the_breath(self):
        """[12.7 amendment] Frame by frame (16/17/17 ms) through the breaths the floor serves -- the 12 amber
        offline marks, and the resting ring and buttons asleep on Home at night -- a target-lit LED never
        shows a floored byte with more counts than the plain byte next to it in time, and no channel moves
        against its value (every v_c rising while some q_c falls, or the reverse). The first channel rule,
        round(v / m), failed both: the amber marks went #010000 -> #010100 (floored) -> #010000.
        [user 2026-09-26, ALIVE.md 12.8] Resting is now one steady warm white at 0.34 (no breath, time of day
        >= 0.80): asleep, the floor is never needed and no byte changes once settled."""
        def csum(q):
            return (q >> 16) + (q >> 8 & 255) + (q & 255)

        runs = [("offline", None, None), ("asleep 00:00", home_frame(54), 0), ("asleep 23:00", home_frame(54), 23 * 60)]
        for label, frame, minute in runs:
            with self.subTest(label):
                eng = al.AliveLights(0)
                start = 0
                if frame is not None:
                    start = 1000
                    eng.claim(start)
                    eng.set_clock(start, minute)
                settle = start + (al.SLEEP_MS + 6000 if frame is not None else 2000)
                prev, now, k, floored, changes = None, start, 0, 0, 0
                while now < settle + 8000:
                    ring_e, button_e = eng.render(now, frame)
                    lit = sum(eng.lit_masks(), [])
                    out = sum(al.reference_output(ring_e, button_e, 150, *eng.lit_masks()), [])
                    plain = sum(al.reference_output(ring_e, button_e, 150), [])
                    v = [[al.srgb_eotf(x) for x in c] for c in ring_e + button_e]     # the scale is common
                    cur = [(lit[i], v[i], out[i], out[i] != plain[i], plain[i] != 0) for i in range(64)]
                    if prev is not None and now >= settle:
                        for i, ((l0, v0, q0, f0, p0), (l1, v1, q1, f1, p1)) in enumerate(zip(prev, cur)):
                            changes += q0 != q1
                            if not (l0 and l1):
                                continue
                            where = (label, now, i, "%06X -> %06X" % (q0, q1))
                            self.assertFalse(f0 and p1 and csum(q0) > csum(q1), where)
                            self.assertFalse(f1 and p0 and csum(q1) > csum(q0), where)
                            b0 = (q0 >> 16, q0 >> 8 & 255, q0 & 255)
                            b1 = (q1 >> 16, q1 >> 8 & 255, q1 & 255)
                            if all(y >= x for x, y in zip(v0, v1)):
                                self.assertTrue(all(y >= x for x, y in zip(b0, b1)), where)
                            elif all(y <= x for x, y in zip(v0, v1)):
                                self.assertTrue(all(y <= x for x, y in zip(b0, b1)), where)
                    if now >= settle:
                        floored += sum(1 for c in cur if c[3])
                    prev = cur
                    now += (16, 17, 17)[k % 3]
                    k += 1
                if frame is None:
                    self.assertGreater(floored, 50, label)              # the floor serves the offline marks
                    self.assertGreater(changes, 0, label)               # and the marks do breathe
                else:                                                   # [user 2026-09-26] steady rest
                    self.assertEqual((floored, changes), (0, 0), label)

    def test_oracle_bytes_are_this_reference_exactly(self):
        """Both oracles' expect.bytes (tests/js referenceOutput(), float64) equal reference_output() on
        the same rounded e with the masks of the persistent view, byte for byte; the floor changes
        only dark target-lit LEDs, and only to one count per channel."""
        for path in (ORACLE, BS_ORACLE):
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["output"]["drive"], al.DEFAULT_DRIVE)
            self.assertEqual((data["output"]["dither"], data["output"]["floor"], data["output"]["floorChannels"]),
                             (False, "F-T", "dominant"))
            steps = floored = 0
            for case in data["cases"]:
                view = None
                for step in case["steps"]:
                    view = step.get("view", view)
                    ring_lit, button_lit = al.lit_masks(al.oracle_targets(view))
                    expect = step["expect"]
                    ring, buttons = al.reference_output(expect["ring"], expect["buttons"], al.DEFAULT_DRIVE, ring_lit,
                                                        button_lit)
                    plain = sum(al.reference_output(expect["ring"], expect["buttons"], al.DEFAULT_DRIVE), [])
                    steps += 1
                    with self.subTest(oracle=path.name, case=case["name"], t=step["t"]):
                        self.assertEqual(ring + buttons, expect["bytes"])
                    for k, (got, was) in enumerate(zip(ring + buttons, plain)):
                        if got != was:
                            floored += 1
                            self.assertTrue((ring_lit + button_lit)[k] and was == 0, (case["name"], step["t"], k))
                            self.assertLessEqual(max(got >> 16, got >> 8 & 255, got & 255), 1)
                            # one count on the dominant channel(s) only
                            e = (expect["ring"] + expect["buttons"])[k]
                            top = max(e)
                            self.assertEqual(got, sum(1 << (16 - 8 * c) for c in range(3) if e[c] == top),
                                             (case["name"], step["t"], k))
            self.assertGreater(steps, 2000)
            # [user 2026-09-26, 12.8] BS now rests at 0.34 (its resting marks are visible): the floor serves
            # its offline marks and fades only.
            self.assertGreater(floored, 1000 if path == ORACLE else 200, path.name)

    def test_the_ruling_report_is_current(self):
        """diagnostics/cc5.4-alive-floor-report.json (tests/tools/alive_floor_report.py) is the evidence of
        the 12.7 ruling: current with both oracles, the oracles' bytes are plain rounding except on the
        F-T marks, and the chosen dominant-only channel rule is the one continuous with plain rounding
        (no floored byte brighter than its neighbours in time, no channel against its value) with the
        lowest mean hue error against the cells' full-level colours."""
        sys.path.insert(0, str(ROOT / "tests" / "tools"))
        try:
            import alive_floor_report as report_tool
        finally:
            sys.path.remove(str(ROOT / "tests" / "tools"))
        report = report_tool.build()
        self.assertTrue(report_tool.REPORT.is_file(), "run tests/tools/alive_floor_report.py")
        self.assertEqual(report_tool.REPORT.read_text(encoding="utf-8"), report_tool.dumps(report),
                         "the floor report is out of date: run tests/tools/alive_floor_report.py")
        self.assertEqual(report["counts"]["oracleBytes"],
                         {"visibleChangedFromPlain": 0, "unlitChangedFromPlain": 0, "marksNotFT": 0})
        self.assertGreater(report["counts"]["marksToFloor"], 1000)
        full = {name: c["hueErrorVsFullLevelColour"] for name, c in report["candidates"].items()}
        self.assertEqual(min(full, key=lambda name: full[name]["mean"]), "dominant-only")
        self.assertEqual((report["choice"]["rule"], report["choice"]["channels"]), ("F-T", "dominant-only"))
        continuity = report["continuity"]["candidates"]
        self.assertEqual((continuity["dominant-only"]["flooredBrighterThanAdjacentPlain"],
                          continuity["dominant-only"]["channelAgainstValue"]), (0, 0))
        self.assertGreater(continuity["proportional"]["flooredBrighterThanAdjacentPlain"], 100)
        self.assertGreater(continuity["dominant-only"]["flooredLedFrames"], 1000)
        self.assertEqual(report["knifeEdge"]["identicalBytesEitherSide"], report["knifeEdge"]["ledStepsWithinBand"])
        self.assertLessEqual(report["power"]["maxCountsAddedPerStep"], report["power"]["bound"])

    def test_the_oracle_fixtures_are_current(self):
        """Both oracle scripts reproduce their committed fixtures byte for byte (e, views, effects and the
        12.7 bytes), from the design files in design-reference/."""
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        design = ROOT / "design-reference"
        runs = ((JS_ORACLES[0], design / "design_handoff_led_choreography", ORACLE),
                (JS_ORACLES[1], design / "design_handoff_nano_d_master_r2.1" / "prototypes", BS_ORACLE))
        with tempfile.TemporaryDirectory() as folder:
            for script, source, fixture in runs:
                out = Path(folder) / fixture.name
                done = subprocess.run([node, str(script), str(source), str(out)], capture_output=True, text=True,
                                      encoding="utf-8", timeout=300)
                self.assertEqual(done.returncode, 0, done.stderr[-2000:])
                self.assertEqual(out.read_bytes(), fixture.read_bytes(), f"{fixture.name} is out of date: node "
                                 f"tests/js/{script.name} {source.relative_to(ROOT)} tests/fixtures/{fixture.name}")

    def test_the_two_js_reference_outputs_are_one_copy(self):
        blocks = []
        for path in JS_ORACLES:
            text = path.read_text(encoding="utf-8")
            start, end = text.index("// BEGIN referenceOutput"), text.index("// END referenceOutput")
            blocks.append(text[start:end])
        self.assertEqual(blocks[0], blocks[1])
        self.assertIn("q = v.map(x => (x >= m ? 1 : 0))", blocks[0])
        self.assertNotIn("Math.floor(x / m + 0.5)", blocks[0])


# ======================================================================= targets
# Revision 2 (ALIVE.md 5.1-5.4) written out independently of the module: the volume arc, the list
# window and the Up next classes from the contract text.
def contract_volume(v, c=None, led="color", external=False, asleep=False, vol_full=False):
    """5.1.2 [M1, M2, M13] + 5.2: {segment: Cell} and the cursor."""
    c = v if c is None else c
    colour = led == "color"

    def col(k, x):
        if not colour:
            return "warm"
        return "red" if x >= 90 and k >= 45 else "amber" if x >= 80 and k >= 40 else "warm"
    cells = {}

    def put(k, role, cls):
        cells[(35 + k) % 60] = (role, cls)
    e, n, nc = v // 2, (v + 1) // 2, (c + 1) // 2
    put(0, "warm", 1)
    put(50, "warm", 1)
    for k in range(n + 1):
        put(k, col(k, v), 2 if k <= nc else 1)
    for k in range(n + 1, nc + 1):
        put(k, col(k, c), 1)
    if v % 2:
        put(e + 1, col(e + 1, v), S)
    put(e, col(e, v), 4 if external else 3)
    return {i: role_cell(role, cls, asleep, vol_full) for i, (role, cls) in cells.items()}, (35 + e) % 60


PALETTE_ROLE = {"warm": WARM, "amber": AMBER, "red": RED, "green": GREEN, "blue": BLUE, "pink": al.PINK}


def role_cell(role, cls, asleep=False, vol_full=False, rgb=None):
    if asleep:
        return Cell(WARM, "warm", cls, RESTING[cls])
    if role == "warm":
        alpha = AWAKE_WARM[cls]
    elif vol_full and cls in (2, S):
        alpha = 1.0
    else:
        alpha = AWAKE_SEMANTIC[cls]
    return Cell(rgb if role == "accent" else PALETTE_ROLE[role], role, cls, alpha)


def v5_first(count, index):
    return 0 if count <= 20 else max(0, min(index - 10, count - 20))


def contract_list(count, index, colors, first=0, unavailable=0, more=-1, upnext=False, now=-1, card=False,
                  local=None, pending_ms=None, led="color"):
    """5.1.1 / 5.1.3 / 5.1.4 / 6.3 [M3, M9, M14, M15]: ({segment: Cell}, cursor, selected accent)."""
    width = min(20, count - first)
    if local is not None and count > 20:
        wf, ww = max(0, min(local - 10, count - 20)), 20
    else:
        wf, ww = first, width
    c0 = wf + (ww - 1) // 2
    cur = index if local is None else local

    def acc(j):
        k = j - first
        if led != "color" or j == more or not 0 <= k < len(colors) or not colors[k]:
            return None
        return al.sat(al.rgb_tuple(colors[k]))

    def cell(j, cls):
        s = acc(j)
        return role_cell("accent" if s else "warm", cls, rgb=s)
    cells = {}
    for j in range(wf, wf + ww):
        k = j - first
        if not 0 <= k < width or (card and j == count - 1) or (not upnext and (unavailable >> k) & 1):
            continue
        cells[((j - c0) * 3) % 60] = cell(j, ("P" if j < now else "N" if j == now else "Q") if upnext else 1)
    cursor = ((cur - c0) * 3) % 60
    if card and cur == count - 1:
        return cells, cursor, None
    sent = first <= cur < first + width
    if not sent:
        cls = 3
    elif cur != more and not upnext and (unavailable >> (cur - first)) & 1:
        cls = "Q"
    else:
        cls = 3
    if pending_ms is not None:
        cls = 1 if pending_ms >= 3000 or (pending_ms // 260) % 2 else 3
    cells[cursor] = cell(cur, cls) if sent else role_cell("warm", cls)
    return cells, cursor, acc(cur) if sent else None


def list5(count, index, layout="recent", colors="auto", activity="idle", unavailable=0, now=None, card=False, **extra):
    """A v5 list frame (first = clamp(index - 10, 0, count - 20), always sent when count > 20)."""
    first = v5_first(count, index)
    width = min(20, count - first)
    ring = {"style": "selection", "value": 0, "index": index, "count": count}
    if count > 20:
        ring["first"] = first
    if colors == "auto":
        colors = [accent(j) for j in range(first, first + width)]
    if colors is not None:
        ring["colors"] = colors
    if unavailable:
        ring["unavailable"] = unavailable
    if now is not None:
        ring["now"] = now
    if card:
        ring["card"] = True
    frame = {"id": 1, "mode": "RECENTLY ADDED", "target": "Hall", "value": "", "detail": "", "status": "",
             "activity": activity, "layout": layout, "ledStyle": "color", "buttons": LIST_BUTTONS, "ring": ring}
    frame.update(extra)
    return frame


def lap_frame(t, d, activity="idle"):
    return {"id": 1, "mode": "TRACKS", "target": "Hall", "value": "", "detail": "", "status": "", "activity": activity,
            "layout": "seek", "ledStyle": "color", "buttons": LIST_BUTTONS,
            "ring": {"style": "lap", "value": 0, "index": t, "count": d}}


class LevelTargetTests(unittest.TestCase):
    def test_every_level_value_matches_the_contract(self):
        """5.1.2 for every v, both styles, awake / resting / ledVolFull, with the M2 value gate."""
        for led in ("color", "white"):
            for v in range(0, 101):
                for asleep, vol_full in ((False, False), (True, False), (False, True)):
                    frame = home_frame(v, led=led)
                    with self.subTest(v=v, led=led, asleep=asleep, vol_full=vol_full):
                        t = al.alive_targets(frame, state_asleep=asleep, vol_full=vol_full)
                        want, cursor = contract_volume(v, led=led, asleep=asleep, vol_full=vol_full)
                        self.assertEqual(lit(t.ring), want)
                        self.assertEqual(t.cursor, cursor)
                        self.assertEqual({i for i, c in lit(t.ring).items() if c.vol_red},
                                         {i for i, c in want.items() if c.role == "red"})
                        self.assertEqual(t.heat, v >= 90 and not asleep)

    def test_pending_spans_match_the_contract(self):
        for v, c in ((40, 60), (60, 40), (70, 96), (97, 81), (1, 0), (0, 3), (100, 0)):
            with self.subTest(v=v, c=c):
                t = al.alive_targets(home_frame(v, c=c))
                want, cursor = contract_volume(v, c)
                self.assertEqual((lit(t.ring), t.cursor, t.pending), (want, cursor, True))

    def test_hand_values(self):
        t = al.alive_targets(home_frame(54))
        self.assertEqual(t.cursor, 2)
        self.assertEqual((t.ring[25], t.ring[35], t.ring[1], t.ring[2]), (warm(1, 0.30), warm(2, 0.62), warm(2, 0.62),
                                                                          warm(3, 1.0)))
        self.assertIsNone(t.ring[3])
        self.assertEqual(len(lit(t.ring)), 29)
        self.assertEqual((t.family, t.pending, t.heat, t.tint, t.asleep), ("home", False, False, None, False))
        # [M13] 55: the endpoint 35 + 27, the half-step on the NEXT segment at 0.81.
        t = al.alive_targets(home_frame(55))
        self.assertEqual((t.cursor, t.ring[2], t.ring[3]), (2, warm(3, 1.0), warm(S, 0.81)))
        # [M1] the amber / red body 0.62, the half-step 0.81 in every role.
        t = al.alive_targets(home_frame(85))
        self.assertEqual((t.cursor, t.ring[17], t.ring[18], t.ring[16], t.ring[14]),
                         (17, Cell(AMBER, "amber", 3, 1.0), Cell(AMBER, "amber", S, 0.81), Cell(AMBER, "amber", 2, 0.62),
                          warm(2, 0.62)))
        # [M2] 79: the half-step at k 40 is WARM (79 < 80); 89: AMBER endpoint and half-step, not RED.
        t = al.alive_targets(home_frame(79))
        self.assertEqual((t.ring[14], t.ring[15]), (warm(3, 1.0), warm(S, 0.81)))
        t = al.alive_targets(home_frame(89))
        self.assertEqual((t.ring[19], t.ring[20]), (Cell(AMBER, "amber", 3, 1.0), Cell(AMBER, "amber", S, 0.81)))
        self.assertFalse(t.heat)
        # 99: endpoint 24 RED, half-step 25 RED 0.81 over the bound mark; 100: endpoint 25.
        t = al.alive_targets(home_frame(99))
        self.assertEqual((t.cursor, t.ring[24], t.ring[25]), (24, Cell(RED, "red", 3, 1.0), Cell(RED, "red", S, 0.81)))
        self.assertTrue(t.ring[24].vol_red and t.heat)
        self.assertEqual(al.alive_targets(home_frame(100)).cursor, 25)
        # [M24] ledVolFull: the semantic body and half-step at 1.00; warm unchanged.
        t = al.alive_targets(home_frame(85), vol_full=True)
        self.assertEqual((t.ring[16].alpha, t.ring[18].alpha, t.ring[14].alpha), (1.0, 1.0, 0.62))

    def test_resting_is_warm_at_resting_levels(self):
        t = al.alive_targets(home_frame(91), state_asleep=True)
        self.assertTrue(t.asleep)
        self.assertEqual((t.ring[20], t.ring[21], t.ring[35], t.ring[25]),
                         (warm(3, 0.34), warm(S, 0.34), warm(2, 0.34), warm(1, 0.34)))   # [user 2026-09-26]
        self.assertFalse(any(c.vol_red for c in lit(t.ring).values()) or t.heat)
        self.assertEqual([b.alpha for b in t.buttons], [0.34] * 4)
        self.assertTrue(all(b.role == "warm" for b in t.buttons))

    def test_pending_blocks_rest(self):
        t = al.alive_targets(home_frame(40, c=50), state_asleep=True)
        self.assertTrue(t.pending and not t.asleep)
        self.assertTrue(al.alive_targets(home_frame(60, c=54)).pending)
        self.assertFalse(al.alive_targets(home_frame(60, c=60)).pending)
        # a moment hold [M22] forces awake like a flash
        self.assertFalse(al.alive_targets(home_frame(60), state_asleep=True, hold=True).asleep)

    def test_external_override(self):
        t = al.alive_targets(home_frame(38, external=True))
        cursor = t.cursor
        self.assertEqual(cursor, (35 + 19) % 60)
        for k in (-1, 0, 1):
            self.assertEqual(t.ring[(cursor + k) % 60], Cell(BLUE, "blue", 4, 1.0))
        self.assertEqual(t.ring[(cursor - 2) % 60], warm(2, 0.62))
        rest = al.alive_targets(home_frame(38, external=True), state_asleep=True)
        self.assertEqual(rest.ring[cursor], warm(4, 0.34))
        self.assertTrue(al.alive_targets(home_frame(38, external=True)).external)

    def test_flash_override_forces_awake(self):
        for kind, role, rgb in (("ok", "green", GREEN), ("err", "red", RED)):
            t = al.alive_targets(home_frame(92), state_asleep=True, flash=kind)
            self.assertFalse(t.asleep)
            self.assertEqual(t.flash, kind)
            for k in (-2, -1, 0, 1, 2):
                self.assertEqual(t.ring[(t.cursor + k) % 60], Cell(rgb, role, 4, 1.0 if abs(k) <= 1 else 0.5))
            self.assertEqual(t.ring[(t.cursor - 3) % 60], Cell(AMBER, "amber", 2, 0.62))    # k 43 [M1]
        t = al.alive_targets(home_frame(38, external=True), flash="ok")
        self.assertEqual(t.ring[t.cursor], Cell(GREEN, "green", 4, 1.0))

    def test_home_notice_offline_endpoint_only(self):
        frame = home_frame(70, c=41, activity="offline", layout="notice")
        t = al.alive_targets(frame)
        self.assertEqual(lit(t.ring), {35 + 20: warm(1, 0.30)})      # [D15] 35 + floor(c/2) [M13]
        self.assertEqual(t.family, "home")
        self.assertFalse(t.pending)                                  # [R1]
        self.assertTrue(al.alive_targets(frame, state_asleep=True).asleep)
        self.assertTrue(al.alive_targets(home_frame(70, c=40)).pending)
        rig = Rig(0)
        rig.claim(0, frame)
        rig.render(4999, frame)
        self.assertFalse(rig.eng.asleep())
        rig.render(5000, frame)
        self.assertTrue(rig.eng.asleep())
        self.assertFalse(rig.eng.targets.pending)

    def test_white_style_is_warm_only(self):
        t = al.alive_targets(home_frame(95, led="white"))
        self.assertTrue(all(c.role == "warm" for c in lit(t.ring).values()))
        self.assertTrue(t.heat)
        self.assertFalse(any(c.vol_red for c in lit(t.ring).values()))
        t = al.alive_targets(home_frame(95, led="white"), flash="err")
        self.assertEqual(t.ring[t.cursor], Cell(RED, "red", 4, 1.0))
        t = al.alive_targets(home_frame(95, led="white", external=True))
        self.assertEqual(t.ring[t.cursor], Cell(BLUE, "blue", 4, 1.0))


class SelectionTargetTests(unittest.TestCase):
    def test_recent_accents_and_tint(self):
        frame = list_frame(10, 2)
        t = al.alive_targets(frame)
        self.assertEqual(t.cursor, slot(2, 10))
        self.assertEqual(t.ring[slot(2, 10)], Cell(sat_accent(2), "accent", 3, 1.0))
        self.assertEqual(t.ring[slot(5, 10)], Cell(sat_accent(5), "accent", 1, 0.45))
        self.assertEqual(t.tint, f(sat_accent(2)))
        self.assertEqual((t.accent, t.family), (sat_accent(2), "recent"))
        rest = al.alive_targets(frame, state_asleep=True)
        self.assertIsNone(rest.tint)
        self.assertEqual(rest.ring[slot(2, 10)], warm(3, 0.34))
        self.assertEqual(rest.accent, sat_accent(2))

    def test_grey_accent_falls_back_to_warm(self):
        frame = list_frame(5, 1, colors=[0x808080, 0x7A7A8A, 0x404050, 0x101010, accent(4)])
        t = al.alive_targets(frame)
        self.assertEqual((t.ring[slot(1, 5)], t.ring[slot(0, 5)]), (warm(3, 1.0), warm(1, 0.30)))
        self.assertEqual(t.ring[slot(4, 5)], Cell(sat_accent(4), "accent", 1, 0.45))
        self.assertIsNone(t.tint)                                  # [R2]
        self.assertIsNone(t.accent)

    def test_tint_needs_an_accent_cursor(self):
        for kind, role in (("ok", "green"), ("err", "red")):
            for frame in (list_frame(9, 1, windows=True), list_frame(10, 2)):
                t = al.alive_targets(frame, flash=kind)
                with self.subTest(kind=kind, layout=frame["layout"]):
                    self.assertEqual(t.ring[t.cursor].role, role)
                    self.assertIsNone(t.tint)
        for layout in ("recent", "explorer", "upnext", "windows"):          # [r2] every list family (M10)
            self.assertEqual(al.alive_targets(list5(9, 1, layout=layout)).tint, f(sat_accent(1)), layout)

    def test_more_is_one_warm_item_and_unavailable_keeps_its_colour(self):
        t = al.alive_targets(list_frame(11, 10, more=10))
        cursor = slot(10, 11)
        self.assertEqual(t.ring[cursor], warm(3, 1.0))
        self.assertIsNone(t.ring[(cursor + 1) % 60])                  # [M3] no second More cell
        self.assertEqual(len(lit(t.ring)), 11)
        self.assertIsNone(t.accent)
        self.assertIsNone(t.tint)
        for windows in (False, True):                                 # [M3] Q 0.45 in its colour
            t = al.alive_targets(list_frame(10, 5, windows=windows, unavailable=1 << 5))
            self.assertEqual(t.ring[slot(5, 10)], Cell(sat_accent(5), "accent", "Q", 0.45))
            self.assertEqual(t.accent, sat_accent(5))
        gap = al.alive_targets(list_frame(9, 1, windows=True, unavailable=1 << 4))
        self.assertIsNone(gap.ring[slot(4, 9)])

    def test_loading_list_is_the_comet_only(self):
        """[M31] a whole list loading: no cells (K1's style off + loading draws the same)."""
        for frame in (list_frame(10, 2, activity="loading"),
                      dict(list_frame(10, 2, activity="loading"), ring={"style": "off", "value": 0, "index": 0, "count": 0})):
            t = al.alive_targets(frame, state_asleep=True)
            self.assertEqual((lit(t.ring), t.cursor, t.pending, t.asleep, t.accent), ({}, 0, True, False, None))
        # An unloaded entry inside a known list: colour 0, a warm landmark; the cursor on it WARM class 3.
        frame = list5(96, 42, colors=[0 if 40 <= j < 48 else accent(j) for j in range(32, 52)])
        t = al.alive_targets(frame)
        self.assertEqual(t.ring[t.cursor], warm(3, 1.0))
        self.assertEqual(t.ring[((40 - 41) * 3) % 60], warm(1, 0.30))
        self.assertFalse(t.pending)

    def test_pending_cursor_pulses_in_its_colour(self):
        """[M3] (D13 extended to every list family): 3 / 1 per 260 ms, 1 after 3 s."""
        for windows in (False, True):
            frame = list_frame(10, 2, windows=windows, activity="pending")
            cursor = slot(2, 10)
            hi = al.alive_targets(frame, pending_ms=0, state_asleep=True)
            self.assertFalse(hi.asleep)
            self.assertEqual(hi.ring[cursor], Cell(sat_accent(2), "accent", 3, 1.0))
            self.assertEqual(al.alive_targets(frame, pending_ms=260).ring[cursor], Cell(sat_accent(2), "accent", 1, 0.45))
            self.assertEqual(al.alive_targets(frame, pending_ms=3120).ring[cursor], Cell(sat_accent(2), "accent", 1, 0.45))
            self.assertEqual(hi.accent, sat_accent(2))
        white = al.alive_targets(list_frame(9, 1, windows=True, activity="pending", led="white"))
        self.assertEqual(white.ring[slot(1, 9)], warm(3, 1.0))

    def test_white_style_lists(self):
        t = al.alive_targets(list_frame(9, 3, windows=True, led="white"))
        self.assertTrue(all(c.role == "warm" for c in lit(t.ring).values()))
        self.assertIsNone(t.tint)
        self.assertIsNone(t.accent)
        self.assertEqual(t.buttons[0], Cell(RED, "red", 2, 1.0))    # legacy Cancel stays red [D16]
        self.assertEqual(t.buttons[3], Cell(GREEN, "green", 3, 1.0))

    def test_recentred_window(self):
        """[M9] the window is re-centred on the transmitted window (c0 = first + 9)."""
        frame = list5(45, 30)
        t = al.alive_targets(frame)
        self.assertEqual(set(lit(t.ring)), {((j - 29) * 3) % 60 for j in range(20, 40)})
        self.assertEqual(t.cursor, 3)
        # A legacy frame (first absent, derived clamp(index - 9)): colours dropped, the window re-centred.
        legacy = list_frame(45, 30, windows=True, first=None)
        t = al.alive_targets(legacy)
        self.assertEqual(set(lit(t.ring)), {((j - 30) * 3) % 60 for j in range(21, 41)})
        self.assertTrue(all(c.role == "warm" for c in lit(t.ring).values()))

    def test_every_list_position_matches_the_contract(self):
        for layout in ("recent", "windows", "explorer"):
            for count in (1, 3, 9, 20, 21, 45, 96):
                for index in range(count):
                    for activity in ("idle", "pending"):
                        mask = 0b100 if count > 3 else 0
                        frame = list5(count, index, layout=layout, activity=activity, unavailable=mask)
                        first = v5_first(count, index)
                        colors = frame["ring"]["colors"]
                        with self.subTest(layout=layout, count=count, index=index, activity=activity):
                            t = al.alive_targets(frame, pending_ms=260 if activity == "pending" else 0)
                            want, cursor, selected = contract_list(
                                count, index, colors, first, mask, pending_ms=260 if activity == "pending" else None)
                            self.assertEqual((lit(t.ring), t.cursor, t.accent), (want, cursor, selected))


class UpNextTargetTests(unittest.TestCase):
    def test_classes(self):
        """5.1.4 [M14]: played P 0.14, now N 0.70, upcoming Q 0.45 in any role, cursor 1.0, absolute now."""
        colors = [accent(j) if j != 7 else 0 for j in range(12)]
        t = al.alive_targets(list5(12, 0, layout="upnext", colors=colors, now=4))
        c0 = 5
        self.assertEqual(t.family, "upnext")
        self.assertEqual(t.ring[((0 - c0) * 3) % 60], Cell(sat_accent(0), "accent", 3, 1.0))
        self.assertEqual(t.ring[((2 - c0) * 3) % 60], Cell(sat_accent(2), "accent", "P", 0.14))
        self.assertEqual(t.ring[((4 - c0) * 3) % 60], Cell(sat_accent(4), "accent", "N", 0.70))
        self.assertEqual(t.ring[((5 - c0) * 3) % 60], Cell(sat_accent(5), "accent", "Q", 0.45))
        self.assertEqual(t.ring[((7 - c0) * 3) % 60], warm("Q", 0.45))
        rest = al.alive_targets(list5(12, 0, layout="upnext", colors=colors, now=4), state_asleep=True)
        self.assertEqual([rest.ring[((j - c0) * 3) % 60].alpha for j in (2, 4, 5)], [0.34, 0.34, 0.34])
        # The split is on absolute indices anywhere in the window.
        for count, index, now in ((40, 25, 30), (40, 39, 38), (96, 50, 12)):
            frame = list5(count, index, layout="upnext", now=now)
            want, cursor, _ = contract_list(count, index, frame["ring"]["colors"], v5_first(count, index), upnext=True,
                                            now=now)
            t = al.alive_targets(frame)
            self.assertEqual((lit(t.ring), t.cursor), (want, cursor), (count, index, now))

    def test_unavailable_never_applies(self):
        a = al.alive_targets(list5(12, 3, layout="upnext", now=4))
        b = al.alive_targets(list5(12, 3, layout="upnext", now=4, unavailable=0b100110))
        self.assertEqual(a.ring, b.ring)

    def test_card(self):
        """[M14] ring.card: entry count - 1 has no landmark and no cursor cell; its colour is ignored."""
        colors = [accent(j) for j in range(5)] + [0]
        t = al.alive_targets(list5(6, 5, layout="upnext", colors=colors, now=4, card=True))
        c0 = 2
        self.assertEqual(t.cursor, ((5 - c0) * 3) % 60)
        self.assertIsNone(t.ring[t.cursor])
        self.assertEqual(len(lit(t.ring)), 5)
        self.assertIsNone(t.tint)
        self.assertIsNone(t.accent)
        other = al.alive_targets(list5(6, 5, layout="upnext", colors=colors[:5] + [0x10E020], now=4, card=True,
                                       unavailable=1 << 5))
        self.assertEqual((other.ring, other.cursor), (t.ring, t.cursor))           # identical unparsed
        t = al.alive_targets(list5(6, 3, layout="upnext", colors=colors, now=4, card=True))
        self.assertEqual(t.ring[t.cursor], Cell(sat_accent(3), "accent", 3, 1.0))
        self.assertIsNone(t.ring[((5 - c0) * 3) % 60])
        # A long card list: the local cursor spun to the untransmitted card draws no cell (L 30, F' 11).
        long = list5(31, 20, layout="upnext", now=29, card=True)
        self.assertEqual(long["ring"]["first"], 10)
        t = al.alive_targets(long, 30, 30)
        self.assertEqual(t.cursor, ((30 - 20) * 3) % 60)
        self.assertIsNone(t.ring[t.cursor])
        want, cursor, _ = contract_list(31, 20, long["ring"]["colors"], 10, upnext=True, now=29, card=True, local=30)
        self.assertEqual((lit(t.ring), t.cursor), (want, cursor))


class LapAndTransportTargetTests(unittest.TestCase):
    def test_transport_is_warm(self):
        t = al.alive_targets(tracks_frame(1))
        self.assertEqual(lit(t.ring), {52: warm(1, 0.30), 53: warm(1, 0.30), 0: warm(2, 0.62),
                                       7: warm(1, 0.30), 8: warm(1, 0.30)})
        self.assertEqual(t.cursor, 0)
        t = al.alive_targets(tracks_frame(2))
        self.assertEqual((t.ring[7], t.ring[8], t.cursor), (warm(3, 1.0), warm(3, 1.0), 8))
        t = al.alive_targets(tracks_frame(0))
        self.assertEqual(t.cursor, 52)                                 # [M4]
        t = al.alive_targets(tracks_frame(0, no_prev=True))
        self.assertEqual((t.cursor, t.ring[52], t.ring[53]), (52, None, None))
        t = al.alive_targets(tracks_frame(2, activity="pending"), pending_ms=260)
        self.assertEqual((t.ring[7], t.ring[8]), (warm(1, 0.30), warm(1, 0.30)))
        self.assertEqual(t.family, "tracks")
        self.assertIsNone(t.tint)

    def test_lap(self):
        """5.1.6: T 74 of D 300 -> head 14; 0..13 at 0.62, 14 at 1.0, 15, 20, ... 55 at 0.30."""
        t = al.alive_targets(lap_frame(74, 300))
        want = {k: warm(2, 0.62) for k in range(14)}
        want.update({k: warm(1, 0.30) for k in range(15, 60, 5)})
        want[14] = warm(3, 1.0)
        self.assertEqual((lit(t.ring), t.cursor, t.family, t.style), (want, 14, "tracks", "lap"))
        self.assertEqual(al.alive_targets(lap_frame(297, 300)).cursor, 59)
        t = al.alive_targets(lap_frame(0, 300))
        self.assertEqual(lit(t.ring), {0: warm(3, 1.0), **{k: warm(1, 0.30) for k in range(5, 60, 5)}})
        for t_s in range(0, 300, 7):
            self.assertEqual(al.alive_targets(lap_frame(t_s, 300)).cursor, min(59, t_s * 60 // 300))
        t = al.alive_targets(lap_frame(74, 300, activity="pending"), pending_ms=260)
        self.assertTrue(t.pending)
        self.assertEqual(t.ring[14], warm(3, 1.0))                     # [M28] no pulse on the lap
        self.assertEqual(al.alive_targets(lap_frame(74, 300), 3, 5).cursor, 14)   # [M11] no local cursor
        self.assertEqual(al.alive_targets(lap_frame(74, 300), state_asleep=True).ring[14], warm(3, 0.34))


class ButtonAndFlagTests(unittest.TestCase):
    def test_button_tones(self):
        t = al.alive_targets(home_frame(54))
        self.assertEqual(t.buttons, [Cell(WARM, "warm", 2, 0.70)] * 4)
        self.assertFalse(t.paused_play)
        frame = list_frame(10, 2, buttons=_buttons(("Back", False, "back"), ("Home", True, "home"),
                                                     ("", False, ""), ("Play", True, "play")))
        t = al.alive_targets(frame)
        self.assertEqual(t.buttons, [Cell(WARM, "warm", 1, 0.14), Cell(WARM, "warm", 2, 0.70),
                                     None, Cell(GREEN, "green", 3, 1.0)])
        t = al.alive_targets(list_frame(9, 1, windows=True))
        self.assertEqual((t.buttons[0], t.buttons[3]), (Cell(RED, "red", 2, 1.0), Cell(GREEN, "green", 3, 1.0)))
        bad = home_frame(54, buttons=_buttons(("X", True, "rocket"), ("Browse", True, "list"),
                                               ("Win", True, "win"), ("Tracks", True, 7)))
        t = al.alive_targets(bad)
        self.assertEqual((t.buttons[0], t.buttons[3]), (None, None))

    def test_v5_tones(self):
        """5.3 [r2][M18][M25]: on 1.0, off 0.30, the liked heart PINK ([r2.2][M32] at 0.30), the snap side in
        sat(colour)."""
        def buttons(*spec):
            return [{"label": "b", "enabled": e, "icon": i, **x} for e, i, x in spec]
        frame = list5(9, 2, layout="upnext", buttons=buttons(
            (True, "back", {}), (True, "shuffle", {"lit": "off"}), (True, "heart", {"lit": "on"}), (True, "play", {})))
        t = al.alive_targets(frame)
        self.assertEqual(t.buttons, [Cell(WARM, "warm", 2, 0.70), Cell(WARM, "warm", 1, 0.30),
                                     Cell(al.PINK, "pink", 1, 0.30), Cell(GREEN, "green", 3, 1.0)])
        rest = al.alive_targets(frame, state_asleep=True)
        self.assertEqual([b.alpha for b in rest.buttons], [0.34, 0.26, 0.26, 0.34])     # [M18] as ruled 2026-09-26; [M32] liked low
        self.assertTrue(all(b.role == "warm" for b in rest.buttons))
        white = al.alive_targets(dict(frame, ledStyle="white"))
        self.assertEqual(white.buttons[2], Cell(al.PINK, "pink", 1, 0.30))               # [M25] kept
        snap = list5(7, 2, layout="windows", buttons=buttons(
            (True, "back", {}), (True, "snapleft", {"lit": "on", "color": 0x2050A0}), (True, "snapright", {}),
            (True, "switch", {})))
        t = al.alive_targets(snap)
        self.assertEqual(t.buttons[1], Cell(al.sat((0x20, 0x50, 0xA0)), "accent", 3, 1.0))
        self.assertEqual(t.buttons[2], Cell(WARM, "warm", 2, 0.70))                      # unassigned: nav
        for colour, led in ((0x808890, "color"), (0x2050A0, "white"), (0, "color")):
            frame = json.loads(json.dumps(snap))
            frame["ledStyle"] = led
            frame["buttons"][1]["color"] = colour
            self.assertEqual(al.alive_targets(frame).buttons[1], Cell(WARM, "warm", 3, 1.0), (colour, led))
        disabled = json.loads(json.dumps(frame))
        disabled["buttons"][1]["enabled"] = False
        self.assertEqual(al.alive_targets(disabled).buttons[1], Cell(WARM, "warm", 1, 0.14))

    def test_r22_liked_heart(self):
        """5.3 row 4 [r2.2][M32] (VOC 2.3 row 4): the liked heart (heart + lit on) is tone `liked`, PINK at 0.30
        (not the 0.14 dim level, not r2.1's 1.0), never sat(), resting WARM 0.26 like `off` [M18] (user 2026-09-26)."""
        def frame(**heart):
            b = {"label": "c", "enabled": True, "icon": "heart", "lit": "on"}
            b.update(heart)
            return list5(9, 2, layout="upnext", buttons=[
                {"label": "a", "enabled": True, "icon": "back"},
                {"label": "b", "enabled": True, "icon": "shuffle", "lit": "off"}, b,
                {"label": "d", "enabled": True, "icon": "play"}])
        liked = frame()
        self.assertEqual(al.button_tone_v5(liked, 2, "upnext"), ("liked", None))
        self.assertEqual(al.alive_targets(liked).buttons[2], Cell(al.PINK, "pink", 1, 0.30))
        self.assertEqual(al.alive_targets(frame(color=0x2050A0)).buttons[2], Cell(al.PINK, "pink", 1, 0.30))  # no sat()
        self.assertEqual(al.alive_targets(liked, state_asleep=True).buttons[2], Cell(WARM, "warm", 1, 0.26))
        self.assertEqual(al.alive_targets(frame(enabled=False)).buttons[2], Cell(WARM, "warm", 1, 0.14))   # row 2 first
        not_liked = frame()
        del not_liked["buttons"][2]["lit"]
        self.assertEqual(al.alive_targets(not_liked).buttons[2], Cell(WARM, "warm", 2, 0.70))              # nav
        # The animator: awake it settles at PINK x 0.30; resting it equals the `off` button (WARM 0.26) exactly.
        eng = al.AliveLights(0)
        eng.claim(0)
        for t in range(0, 3000, 16):
            _, buttons = eng.render(t, liked)
        for got, exp in zip(buttons[2], al.tone(*(x * 0.30 for x in al.PINK))):
            self.assertAlmostEqual(got, exp, places=6)
        for t in range(3000, 12000, 16):
            _, buttons = eng.render(t, liked)
        self.assertTrue(eng.asleep())
        self.assertGreater(buttons[2][0], 0.0)
        for got, off in zip(buttons[2], buttons[1]):
            self.assertAlmostEqual(got, off, places=9)

    def test_paused_play(self):
        t = al.alive_targets(home_frame(54, buttons=PAUSED_BUTTONS))
        self.assertEqual(t.buttons[0], Cell(GREEN, "green", 3, 1.0))
        self.assertTrue(t.paused_play)
        rest = al.alive_targets(home_frame(54, buttons=PAUSED_BUTTONS), state_asleep=True)
        self.assertEqual(rest.buttons[0], Cell(WARM, "warm", 3, 0.34))
        self.assertFalse(rest.paused_play)
        disabled = _buttons(("Play", False, "play"), ("Browse", True, "list"), ("Win", True, "win"),
                            ("Tracks", False, "tracks"))
        t = al.alive_targets(home_frame(54, buttons=disabled))
        self.assertEqual(t.buttons[0], Cell(WARM, "warm", 1, 0.14))
        self.assertFalse(t.paused_play)
        rest = al.alive_targets(home_frame(54, buttons=disabled), state_asleep=True)
        self.assertEqual((rest.buttons[0].alpha, rest.buttons[3].alpha), (0.26, 0.26))
        recent = list_frame(10, 2, buttons=PAUSED_BUTTONS)
        self.assertFalse(al.alive_targets(recent).paused_play)
        self.assertEqual(al.alive_targets(recent).buttons[0], Cell(WARM, "warm", 2, 0.70))

    def test_offline_targets(self):
        for t in (al.alive_targets(home_frame(54), claimed=False), al.alive_targets(None), al.offline_targets()):
            self.assertEqual(lit(t.ring), {i: Cell(AMBER, "amber", 1, 0.12) for i in range(0, 60, 5)})
            self.assertEqual(t.buttons, [None] * 4)
            self.assertTrue(t.offline)
            self.assertEqual((t.family, t.asleep, t.pending, t.heat, t.tint, t.cursor),
                             ("offline", False, False, False, None, 0))

    def test_families(self):
        """5.4 [r2]: every layout mapped explicitly (VOC 1.1)."""
        for layout in ("nowPlaying", "volume", "idle", "notice"):
            self.assertEqual(al.frame_family({"layout": layout}), "home")
        for layout, family in (("recent", "recent"), ("explorer", "explorer"), ("tracks", "tracks"),
                               ("seek", "tracks"), ("upnext", "upnext"), ("windows", "windows")):
            self.assertEqual(al.frame_family({"layout": layout}), family)
        for mode, family in (("VOLUME", "home"), ("RECENTLY ADDED", "recent"), ("TRACKS", "tracks"),
                             ("WINDOWS", "windows"), ("ELSE", "home")):
            self.assertEqual(al.frame_family({"mode": mode}), family)

    def test_playing_only_on_home(self):
        self.assertTrue(al.alive_targets(home_frame(54, playing=True)).playing)
        self.assertIs(al.alive_targets(home_frame(54, playing=False)).playing, False)
        self.assertIsNone(al.alive_targets(home_frame(54)).playing)
        self.assertIsNone(al.alive_targets(home_frame(54, playing=1)).playing)
        self.assertIsNone(al.alive_targets(list_frame(10, 2, playing=True)).playing)

    def test_ring_window_equals_preview_lights(self):
        """The transmitted window (the parser's reading, P4 section 4) is v4's."""
        rings = []
        for count in (0, 1, 5, 20, 21, 45, 300):
            for index in (0, 5, 9, 10, 19, 20, 29, 30, 44, 299):
                for first in ("absent", 0, 5, 10, 21, 25, -1, True, "x"):
                    ring = {"style": "selection", "index": index, "count": count, "unavailable": 0b1011,
                            "colors": [accent(k) for k in range(min(20, max(0, count)))]}
                    if first != "absent":
                        ring["first"] = first
                    rings.append(ring)
        rings.append({"first": 0, "index": 3, "count": 5, "colors": [1, 2, 0x1000000]})
        rings.append({"index": 3, "count": 5, "unavailable": 1 << 9})
        for ring in rings:
            with self.subTest(ring=ring):
                self.assertEqual(al.ring_window(ring, ring["index"], ring["count"]),
                                 pl._ring_window(ring, ring["index"], ring["count"]))


class LocalCursorTests(unittest.TestCase):
    def test_level_local_value(self):
        t = al.alive_targets(home_frame(54), 61, 100)
        self.assertEqual(t.cursor, (35 + 30) % 60)                      # [M13] 35 + floor(61/2)
        self.assertEqual(t.value, 61)
        self.assertTrue(t.pending)
        want, _ = contract_volume(61, 54)
        self.assertEqual(lit(t.ring), want)
        bare = home_frame(54)
        del bare["confirmedVolume"]
        self.assertTrue(al.alive_targets(bare, 58, 100).pending)
        self.assertFalse(al.alive_targets(bare, 54, 100).pending)
        self.assertTrue(al.alive_targets(home_frame(80), 95, 100).heat)

    def test_level_local_value_not_applied(self):
        base = al.alive_targets(home_frame(54))
        for frame, pos, top in ((home_frame(54), 61, 99), (home_frame(54), None, 100), (home_frame(54), 61, None),
                                (home_frame(54), 61.0, 100), (home_frame(54), 61, -1),
                                (home_frame(54, layout="notice"), 61, 100)):
            with self.subTest(pos=pos, top=top, layout=frame["layout"]):
                self.assertEqual(al.alive_targets(frame, pos, top).cursor, base.cursor)
        offline = home_frame(54, c=40, activity="offline")
        self.assertEqual(al.alive_targets(offline, 61, 100).cursor, al.alive_targets(offline).cursor)
        self.assertFalse(al.alive_targets(offline).pending)
        frame = home_frame(54)
        resolved, applied = al.apply_local(frame, 61, 99)
        self.assertFalse(applied)
        self.assertIs(resolved, frame)
        off_ring = home_frame(95)
        off_ring["ring"] = {"style": "off", "value": 95, "index": 0, "count": 0}
        self.assertFalse(al.alive_targets(off_ring).heat)

    def test_local_position_is_clamped(self):
        self.assertEqual(al.alive_targets(home_frame(54), 101, 100).cursor, 25)
        self.assertEqual(al.alive_targets(home_frame(54), -1, 100).cursor, 35)
        self.assertEqual(al.alive_targets(list_frame(10, 2), 12, 9).cursor, slot(9, 10))
        self.assertEqual(al.alive_targets(tracks_frame(1), -4, 2).cursor, 52)

    def test_selection_local_index(self):
        t = al.alive_targets(list_frame(10, 2), 7, 9)
        self.assertEqual(t.cursor, slot(7, 10))
        self.assertEqual(t.ring[slot(7, 10)], Cell(sat_accent(7), "accent", 3, 1.0))
        self.assertEqual(t.ring[slot(2, 10)], Cell(sat_accent(2), "accent", 1, 0.45))
        self.assertEqual(t.accent, sat_accent(7))
        for activity in ("pending", "loading"):
            frame = list_frame(10, 2, activity=activity)
            self.assertEqual(al.alive_targets(frame, 7, 9).cursor, al.alive_targets(frame).cursor)
        self.assertEqual(al.alive_targets(list_frame(10, 2), 7, 10).cursor, slot(2, 10))
        resolved, applied = al.apply_local(list_frame(10, 2), 7, 9)
        self.assertTrue(applied)
        self.assertEqual(resolved["ring"]["index"], 7)

    def test_recentring(self):
        """[M15]: F' = clamp(L - 10, 0, N - 20), c0' = F' + 9; entries not transmitted stay unlit; an
        untransmitted cursor is WARM class 3."""
        frame = list5(45, 30)                                          # transmitted 20..39
        for local in (30, 35, 39, 40, 44, 12, 0):
            want, cursor, selected = contract_list(45, 30, frame["ring"]["colors"], 20, local=local)
            t = al.alive_targets(frame, local, 44)
            with self.subTest(local=local):
                self.assertEqual((lit(t.ring), t.cursor, t.accent), (want, cursor, selected))
        t = al.alive_targets(frame, 44, 44)
        self.assertEqual(t.ring[t.cursor], warm(3, 1.0))
        self.assertIsNone(t.tint)
        self.assertEqual(len(lit(al.alive_targets(frame, 35, 44).ring)), 15)
        short = list_frame(10, 2, first=None)                          # N <= 20: nothing else changes
        self.assertEqual(al.alive_targets(short, 7, 9).ring[slot(7, 10)], Cell(sat_accent(7), "accent", 3, 1.0))
        self.assertNotIn("first", short["ring"])                       # the host frame is never mutated

    def test_transport_local_index(self):
        self.assertEqual(al.alive_targets(tracks_frame(1), 2, 2).cursor, 8)
        self.assertEqual(al.alive_targets(tracks_frame(1, activity="pending"), 2, 2).cursor, 0)
        self.assertEqual(al.alive_targets(tracks_frame(1), 2, 3).cursor, 0)

    # DD-DES-003: twin of lcd-preview/alive_tests.cpp briCases (cc_alive_local). Off frame: max 100,
    # value = pos (0 = off). On frame: max 99, value = pos + 1 (positions 0..99 = 1..100 %).
    BRI_CASES = ((0, 100, 0), (1, 100, 1), (50, 100, 50), (100, 100, 100), (120, 100, 100),
                 (0, 99, 1), (49, 99, 50), (99, 99, 100), (120, 99, 100), (-3, 99, 1))

    def test_bri_local_value_twin(self):
        frame = {"activity": "idle", "ring": {"style": "bri", "value": 40}}
        for pos, top, value in self.BRI_CASES:
            with self.subTest(pos=pos, top=top):
                out, applied, index = al._local(frame, pos, top)
                self.assertTrue(applied)
                self.assertIsNone(index)
                self.assertEqual(out["ring"]["value"], value)
                resolved, applied = al.apply_local(frame, pos, top)
                self.assertTrue(applied)
                self.assertEqual(resolved["ring"]["value"], value)
        self.assertEqual(frame["ring"]["value"], 40)                    # the host frame is never mutated
        for top in (98, 101):
            resolved, applied = al.apply_local(frame, 5, top)
            self.assertFalse(applied)
            self.assertIs(resolved, frame)


# ====================================================================== animator
def targets_with(ring=None, buttons=None, **flags):
    t = al.AliveTargets(ring=ring or [None] * 60, buttons=buttons or [None] * 4, family=flags.pop("family", "home"))
    for key, value in flags.items():
        setattr(t, key, value)
    return t


class AnimatorTests(unittest.TestCase):
    def test_initial_state_and_zero_dt(self):
        a = al.AliveAnimator()
        ring, buttons = a.step(0, 0, targets_with(ring=[warm(3, 1.0)] * 60))
        self.assertEqual(a.ring[0], [1.0, 0.64, 0.33, 0.0])       # design cur init, dt 0 moves nothing
        self.assertEqual(ring, [(0.0, 0.0, 0.0)] * 60)
        self.assertEqual(buttons, [(0.0, 0.0, 0.0)] * 4)

    def test_ring_damping_taus(self):
        def settle(start, target_alpha, dt, asleep=False, tod_b=1.0, now=1300):
            a = al.AliveAnimator()
            for c in a.ring:
                c[3] = start
            tg = targets_with(ring=[warm(3, target_alpha)] * 60, asleep=asleep)
            a.step(now, dt, tg, tod_b=tod_b)
            return a.ring[0][3]
        self.assertAlmostEqual(settle(0, 1.0, 16), 1 - math.exp(-16 / 10), places=12)
        self.assertAlmostEqual(settle(0, 0.62, 16), 0.62 * (1 - math.exp(-16 / 55)), places=12)
        self.assertAlmostEqual(settle(1, 0.30, 16), 1 + (0.30 - 1) * (1 - math.exp(-16 / 140)), places=12)
        # [user 2026-09-26] Resting: ta = alpha * max(todB, 0.80), steady (no breath; now 1300 was a quarter
        # breath); tau 400 up, 700 down.
        for now in (1300, 3900):
            self.assertAlmostEqual(settle(0, 0.34, 16, True, 0.6, now), 0.34 * 0.8 * (1 - math.exp(-16 / 400)), places=12)
            self.assertAlmostEqual(settle(1, 0.34, 16, True, 0.6, now), 1 + (0.34 * 0.8 - 1) * (1 - math.exp(-16 / 700)),
                                   places=12)
            self.assertAlmostEqual(settle(0, 0.34, 16, True, 0.9, now), 0.34 * 0.9 * (1 - math.exp(-16 / 400)), places=12)

    def test_colour_snaps_when_dark_then_follows_at_70ms(self):
        a = al.AliveAnimator()
        tg = targets_with(ring=[Cell(GREEN, "green", 3, 0.01)] * 60)
        a.step(0, 16, tg)
        c = a.ring[0]
        self.assertLess(c[3], 0.02)
        k = 1 - math.exp(-16)
        self.assertAlmostEqual(c[0], 1.0 + (0 - 1.0) * k, places=12)
        a = al.AliveAnimator()
        a.ring[0][3] = 0.5
        a.step(0, 16, targets_with(ring=[Cell(GREEN, "green", 3, 1.0)] + [None] * 59))
        self.assertAlmostEqual(a.ring[0][1], 0.64 + (1.0 - 0.64) * (1 - math.exp(-16 / 70)), places=12)
        self.assertEqual(a.ring[1][:3], [1.0, 0.64, 0.33])       # unlit: colour untouched

    def test_button_taus_breath_and_paused_play(self):
        a = al.AliveAnimator()
        tg = targets_with(buttons=[Cell(GREEN, "green", 3, 1.0), Cell(WARM, "warm", 2, 0.7), None, None],
                          paused_play=True)
        now = 650                                           # cos(2*pi*650/2600) = 0
        a.step(now, 16, tg)
        factor = 0.55 + 0.45 * (0.5 + 0.5 * math.cos(2 * math.pi * now / 2600))
        self.assertAlmostEqual(a.buttons[0][3], 1.0 * factor * (1 - math.exp(-16 / 40)), places=12)
        self.assertAlmostEqual(a.buttons[1][3], 0.7 * (1 - math.exp(-16 / 40)), places=12)
        a.buttons[2][3] = 0.5
        a.step(now + 16, 16, tg)
        self.assertAlmostEqual(a.buttons[2][3], 0.5 * math.exp(-16 / 160), places=12)
        # Asleep: x restK (todB floored at 0.80), tau 400; [user 2026-09-26] no rest breath; no paused-play
        # breath while resting.
        a = al.AliveAnimator()
        rest = targets_with(buttons=[Cell(WARM, "warm", 3, 0.34)] + [None] * 3, paused_play=True, asleep=True)
        a.step(1300, 16, rest, tod_b=0.5)
        self.assertAlmostEqual(a.buttons[0][3], 0.34 * 0.8 * (1 - math.exp(-16 / 400)), places=12)

    def test_offline_breath(self):
        a = al.AliveAnimator()
        now = 2600 * 3 + 650
        a.step(now, 50, al.offline_targets())
        br = 0.6 + 0.4 * math.sin(2 * math.pi * 650 / 2600)
        self.assertAlmostEqual(a.ring[0][3], 0.12 * br * (1 - math.exp(-50 / 55)), places=12)
        self.assertEqual(a.ring[1][3], 0.0)
        self.assertTrue(a.animating())

    def test_heat_embers_only_on_red_segments(self):
        now = 12345
        cells = [None] * 60
        cells[20] = Cell(RED, "red", 3, 1.0)
        cells[19] = Cell(AMBER, "amber", 2, 1.0)
        a = al.AliveAnimator()
        a.step(now, 50, targets_with(ring=cells, heat=True))
        p = al.HEAT_PERIODS[20]
        factor = 0.72 + 0.28 * (0.5 + 0.5 * math.sin(2 * math.pi * (now % p) / p + 1.9 * 20))
        ta = 1.0 * factor
        tau = 10 if ta >= 0.9 else 55
        self.assertAlmostEqual(a.ring[20][3], ta * (1 - math.exp(-50 / tau)), places=12)
        self.assertAlmostEqual(a.ring[19][3], 1 - math.exp(-50 / 10), places=12)
        b = al.AliveAnimator()
        b.step(now, 50, targets_with(ring=cells, heat=False))
        self.assertAlmostEqual(b.ring[20][3], 1 - math.exp(-50 / 10), places=12)

    def test_compose_duck_and_tone(self):
        a = al.AliveAnimator()
        for c in a.ring:
            c[:] = [1.0, 0.5, 0.25, 1.0]
        tg = targets_with(ring=[warm(3, 1.0)] * 60)
        a.play(al.Effect("fill", 0, n=0))                     # FG: ducks; n 0 masks only segment 35
        ring, _ = a.step(380, 0, tg, palette=al.Palette((1.0, 0.5, 0.25)))
        u = 380 / 760
        duck = 0.35 * math.sin(math.pi * u)
        want = al.tone(1.0 * (1 - duck), 0.5 * (1 - duck), 0.25 * (1 - duck))
        for got, exp in zip(ring[10], want):
            self.assertAlmostEqual(got, exp, places=12)
        self.assertLessEqual(max(ring[10]), 0.78)
        # Above the knee the tone map keeps the hue.
        b = al.AliveAnimator()
        for c in b.ring:
            c[:] = [1.0, 0.5, 0.25, 1.0]
        ring, _ = b.step(0, 0, tg)
        self.assertAlmostEqual(ring[0][0], al.tone(1.0, 0.5, 0.25)[0], places=15)

    def test_tint_smoothing_on_unlit_segments(self):
        a = al.AliveAnimator()
        cells = [None] * 60
        cells[0] = Cell((255, 0, 128), "accent", 3, 1.0)
        tint = (1.0, 0.0, 128 / 255)
        ring, _ = a.step(0, 16, targets_with(ring=cells, family="windows", tint=tint))
        k = 1 - math.exp(-16 / 220)
        self.assertAlmostEqual(a.tint[0], k, places=12)
        self.assertAlmostEqual(ring[5][0], k * 0.06, places=12)
        self.assertEqual(ring[5][1], 0.0)
        self.assertAlmostEqual(ring[5][2], tint[2] * k * 0.06, places=12)
        a.step(16, 16, targets_with(ring=cells, family="windows", tint=None))
        self.assertAlmostEqual(a.tint[0], k * math.exp(-16 / 220), places=12)

    def test_working_comet_and_song_hand(self):
        a = al.AliveAnimator()
        ring, _ = a.step(1400 * 5 + 700, 0, targets_with(pending=True))   # head at 60 * 0.5 = 30
        pal = al.ENGINE_PALETTE
        want = [0.0, 0.0, 0.0]
        for k in range(9):                                  # comet(30, +1, 8, HOT, WARM, 0.5)
            pos, alpha = 30 - k, 0.5 * (1 - k / 9) ** 1.7
            colour = pal.hot if k == 0 else pal.warm
            weight = alpha * math.exp(-(30 - pos) ** 2 / (2 * 0.7 ** 2))
            if weight > 0.001:
                want = [w + c * weight for w, c in zip(want, colour)]
        for got, exp in zip(ring[30], al.tone(*want)):
            self.assertAlmostEqual(got, exp, places=12)
        self.assertGreater(ring[29][0], ring[31][0])                    # the tail trails anticlockwise
        self.assertEqual(ring[34], (0.0, 0.0, 0.0))
        self.assertTrue(a.animating())
        b = al.AliveAnimator()
        ring, _ = b.step(0, 0, targets_with(), song_prog=0.25, tod_b=0.5)
        hot = al.ENGINE_PALETTE.hot
        self.assertAlmostEqual(ring[15][1], hot[1] * 0.26 * 0.5, places=12)
        self.assertAlmostEqual(ring[16][1], hot[1] * 0.26 * 0.5 * math.exp(-1 / (2 * 0.75 ** 2)), places=12)
        self.assertEqual(ring[20], (0.0, 0.0, 0.0))                    # 3 w = 2.25 segments reach
        self.assertEqual(hot, al.WARM)                                  # [user 2026-09-26] HOT == WARM
        # [user 2026-09-26] no song-progress hand at rest: the same progress asleep draws nothing.
        ring, _ = al.AliveAnimator().step(0, 0, targets_with(asleep=True), song_prog=0.25, tod_b=0.5)
        self.assertEqual(ring, [(0.0, 0.0, 0.0)] * 60)

    def test_add_ignores_tiny_alphas(self):
        a = al.AliveAnimator()
        a.play(al.Effect("tick", 0, at=10, len=0))
        ring, _ = a.step(179, 0, targets_with())                    # 0.45 (1 - u)^2 < 0.001
        self.assertEqual(ring[10], (0.0, 0.0, 0.0))
        ring, _ = a.step(100, 0, targets_with())
        self.assertGreater(ring[10][0], 0)

    def test_effect_lifetimes_and_kill_fade(self):
        a = al.AliveAnimator()
        a.play(al.Effect("bloom", 0, at=0))
        a.step(900, 0, targets_with())
        self.assertEqual(len(a.effects), 1)                         # u == 1 still drawn
        a.step(901, 0, targets_with())
        self.assertEqual(a.effects, [])
        a.play(al.Effect("bloom", 1000, at=0))
        a.play(al.Effect("fail", 1100, at=0))                       # kills bloom at 1100
        self.assertEqual(a.effects[0].kill, 1100)
        a.step(1219, 0, targets_with())
        self.assertEqual([e.type for e in a.effects], ["bloom", "fail"])
        a.step(1220, 0, targets_with())                             # amp 0: gone
        self.assertEqual([e.type for e in a.effects], ["fail"])

    def test_down_snapshot_and_button_order(self):
        a = al.AliveAnimator()
        for i, c in enumerate(a.ring):
            c[:] = [1.0, 0.5, 0.25, 0.8]
        for c in a.buttons:
            c[:] = [0.0, 1.0, 0.5, 1.0]
        snap, bsnap = a.snapshot()
        self.assertEqual(snap[0], (0.8, 0.4, 0.2))
        a.play(al.Effect("down", 0, at=10, snap=snap, bsnap=bsnap))
        ring, buttons = a.step(100, 0, targets_with())
        self.assertEqual(ring[10], al.tone(0.8, 0.4, 0.2))          # the cursor holds as an ember
        self.assertEqual(ring[11], al.tone(0.8, 0.4, 0.2))          # st = 80 + 59 * 10: not yet
        ring, buttons = a.step(390, 0, targets_with())              # o 59 fades from 670; o 1 from 670+..: j 3 first
        self.assertEqual(buttons[3], (0.0, 0.0, 0.0))                # 120 + 0 * 80 + 160 <= 390
        self.assertGreater(buttons[0][1], 0)                         # 120 + 240 = 360: fading, not gone

    def test_every_live_down_keeps_its_own_snapshot(self):
        """Design play() line 231 keeps e.snap / e.bsnap per effect (ALIVE.md 7), however many
        releases fall inside one 120 ms kill fade (lease flapping); the firmware twin once shared
        two buffers and drew the oldest fading down with a newer snapshot. A down every 16 ms,
        the damped state changing in between; up to 8 are live at once (the [D12] cap evicts only
        downs the design no longer draws). A shadow animator without effects gives cur * a (its
        e, below the knee). The downs mask every target, their splats have factor 1 on o = 0..40
        before ms 280 and on slots 0..2 before ms 200 (the button splat has no amp), so
        e = tone(sum of amp * snap) and tone(sum of bsnap). Mirrors alive_tests.cpp
        downSnapshotChecks()."""
        flap, shadow = al.AliveAnimator(), al.AliveAnimator()
        at, snaps, bsnaps, most, worst = 10, [], [], 0, 0.0
        for n in range(20):
            t = 1000 + 16 * n
            ring = [None] * 60
            for i in range(at, at + 41):
                rgb = ((37 * i + 53 * n) % 256, (91 * i + 17 * n + 40) % 256, (13 * i + 71 * n + 90) % 256)
                ring[i] = Cell(rgb, al.ROLE_ACCENT, 2, 0.05 + 0.25 * ((i + 3 * n) % 7) / 6)
            buttons = [Cell(((60 * j + 45 * n) % 256, (100 + 33 * n + 20 * j) % 256, (200 + 7 * n * j) % 256),
                            al.ROLE_ACCENT, 2, 0.1 + 0.2 * ((j + n) % 3) / 2) for j in range(3)] + [None]
            tg = targets_with(ring=ring, buttons=buttons)
            shadow_ring, shadow_buttons = shadow.step(t, 16, tg)
            ring_e, button_e = flap.step(t, 16, tg)
            if n:
                live = range(max(0, n - 8), n)
                most = max(most, len(live))
                self.assertEqual([e.t0 for e in flap.effects], [1000 + 16 * k for k in live])
                for i in range(60):
                    want = al.tone(*(sum((1.0 if k == n - 1 else 1 - 16 * (n - k - 1) / 120) * snaps[k][i][q]
                                         for k in live) for q in range(3)))
                    worst = max([worst] + [abs(x - y) for x, y in zip(ring_e[i], want)])
                for j in range(4):
                    want = al.tone(*(sum(bsnaps[k][j][q] for k in live) for q in range(3)))
                    worst = max([worst] + [abs(x - y) for x, y in zip(button_e[j], want)])
            self.assertTrue(all(max(c) <= al.TONE_KNEE for c in shadow_ring + shadow_buttons))
            snaps.append(shadow_ring)                                  # cur * a now (e below the knee)
            bsnaps.append(shadow_buttons)
            snap, bsnap = flap.snapshot()
            flap.play(al.Effect("down", t, at=at, snap=snap, bsnap=bsnap))
        self.assertEqual(most, 8)
        self.assertGreater(flap.evictions, 0)
        self.assertLess(worst, 1e-12)


class QueueTests(unittest.TestCase):
    def test_same_type_replacement_and_accumulation(self):
        a = al.AliveAnimator()
        for kind in ("wake", "reveal", "bound"):
            a.play(al.Effect(kind, 0, c=(1, 1, 1)))
            a.play(al.Effect(kind, 5, c=(1, 1, 1)))
        a.play(al.Effect("tick", 0))
        a.play(al.Effect("tick", 1))
        a.play(al.Effect("press", 0, n=1))
        a.play(al.Effect("press", 1, n=1))
        self.assertEqual([(e.type, e.t0) for e in a.effects],
                         [("wake", 5), ("reveal", 5), ("bound", 5), ("tick", 0), ("tick", 1), ("press", 0), ("press", 1)])

    def test_fg_kill_is_set_once(self):
        a = al.AliveAnimator()
        a.play(al.Effect("bloom", 0))
        a.play(al.Effect("tick", 1))
        a.play(al.Effect("fail", 10))
        a.play(al.Effect("wash", 20, c=(1, 0, 0)))
        self.assertEqual([(e.type, e.kill) for e in a.effects],
                         [("bloom", 10), ("tick", None), ("fail", 20), ("wash", None)])

    def test_eviction_order(self):
        a = al.AliveAnimator()
        a.play(al.Effect("bloom", 0))
        a.play(al.Effect("press", 1, n=0))
        for k in range(5):
            a.play(al.Effect("tick", 2 + k))
        a.play(al.Effect("fail", 10))                               # kills bloom; 8 queued
        self.assertEqual(len(a.effects), 8)
        a.play(al.Effect("press", 11, n=1))                         # 1. the oldest killed (bloom)
        self.assertEqual(a.effects[0].type, "press")
        self.assertNotIn("bloom", [e.type for e in a.effects])
        a.play(al.Effect("press", 12, n=2))                         # 2. the oldest tick
        self.assertEqual([e.t0 for e in a.effects if e.type == "tick"], [3, 4, 5, 6])
        a2 = al.AliveAnimator()
        for k in range(4):
            a2.play(al.Effect("press", k, n=0))
        for kind in ("wake", "reveal", "bound", "fail"):
            a2.play(al.Effect(kind, 10, c=(1, 1, 1)))
        a2.play(al.Effect("sweep", 20))                             # kills fail -> evict it (killed)
        self.assertEqual([e.type for e in a2.effects], ["press"] * 4 + ["wake", "reveal", "bound", "sweep"])
        a2.play(al.Effect("press", 30, n=3))                        # 3. no killed, no tick: oldest press
        self.assertEqual([e.t0 for e in a2.effects if e.type == "press"], [1, 2, 3, 30])
        a3 = al.AliveAnimator()
        for kind in ("wake", "reveal", "bound", "shimmer"):
            a3.play(al.Effect(kind, 0, c=(1, 1, 1)))
        a3.effects.extend(al.Effect("pending", 0) for _ in range(4))
        a3.play(al.Effect("wake", 5))                               # replaces wake: 7 left, no eviction
        a3.play(al.Effect("pending", 6))                            # full: 4. the oldest effect
        self.assertEqual(a3.effects[0].type, "bound")
        self.assertEqual(len(a3.effects), 8)
        self.assertEqual(a3.evictions, 1)

    def test_uncapped_never_evicts(self):
        a = al.AliveAnimator(cap=None)
        for k in range(20):
            a.play(al.Effect("tick", k))
        self.assertEqual((len(a.effects), a.evictions), (20, 0))


# ======================================================================== engine
class Rig:
    """An engine whose pushed effects are recorded per render."""

    def __init__(self, now=0):
        self.eng = al.AliveLights(now)
        self.pushed = []
        original = self.eng.animator.play

        def play(effect):
            self.pushed.append(effect)
            return original(effect)
        self.eng.animator.play = play
        self.frame = None

    def render(self, now, frame=None, local_pos=None, local_max=None):
        if frame is not None:
            self.frame = frame
        mark = len(self.pushed)
        self.out = self.eng.render(now, self.frame, local_pos, local_max)
        return self.pushed[mark:]

    def claim(self, now, frame):
        self.eng.claim(now)
        return self.render(now, frame)

    def run(self, start, stop, step=16, frame=None):
        for t in range(start, stop, step):
            self.render(t, frame)


def kinds(effects):
    return [e.type for e in effects]


class EngineLifecycleTests(unittest.TestCase):
    def test_reset_starts_offline_with_reveal(self):
        rig = Rig(0)
        self.assertEqual(kinds(rig.eng.animator.effects), ["reveal"])
        ring, buttons = rig.eng.render(0, home_frame(54))
        self.assertEqual(ring, [(0.0, 0.0, 0.0)] * 60)            # dt 0 on the first render
        self.assertTrue(rig.eng.targets.offline)
        self.assertFalse(rig.eng.asleep())
        self.assertEqual(rig.eng.cursor(), 0)
        rig.eng.render(1000, None)                                  # gap capped at 50 ms
        br = 0.6 + 0.4 * math.sin(2 * math.pi * 1000 / 2600)
        self.assertAlmostEqual(rig.eng.animator.ring[0][3], 0.12 * br * (1 - math.exp(-50 / 55)), places=12)
        _, buttons = rig.eng.render(1016, None)
        self.assertEqual(buttons, [(0.0, 0.0, 0.0)] * 4)           # offline: buttons off
        self.assertEqual(rig.eng.animator.ring[1][3], 0.0)          # only the 12 marks light

    def test_start_reveal_after_native_handover(self):
        rig = Rig(0)
        rig.eng.render(0)
        rig.eng.render(3000)                                        # the power-up reveal is over
        self.assertEqual(rig.eng.animator.effects, [])
        rig.eng.start_reveal(3016)
        self.assertEqual([(e.type, e.t0) for e in rig.eng.animator.effects], [("reveal", 3016)])
        rig.eng.start_reveal(3032)                                  # replaces its own type
        self.assertEqual([(e.type, e.t0) for e in rig.eng.animator.effects], [("reveal", 3032)])
        before, _ = rig.eng.render(3032)
        self.assertEqual(rig.eng.raw[0][0], (0.0, 0.0, 0.0))        # masked at ms 0, unfolds from the top
        ring, _ = rig.eng.render(3032 + 200)                        # (r4: what the LED shows eases there)
        self.assertGreater(ring[0][0], ring[30][0])

    def test_inputs_are_ignored_while_unclaimed(self):
        rig = Rig(0)
        rig.eng.detent(10, 1)
        rig.eng.limit(10, 1)
        rig.eng.press(10, 0)
        self.assertEqual(rig.render(16, home_frame(54)), [])
        self.assertTrue(rig.eng.targets.offline)

    def test_claim_seeds_without_events_and_boots(self):
        rig = Rig(0)
        frame = home_frame(54, external=True, playing=True, feedback={"kind": "ok", "seq": 7})
        pushed = rig.claim(1000, frame)
        self.assertEqual(kinds(pushed), ["boot"])
        self.assertTrue(pushed[0].home)
        self.assertIsNone(rig.eng.targets.flash)
        self.assertEqual(rig.render(1016, frame), [])
        pushed = rig.render(1032, dict(frame, feedback={"kind": "ok", "seq": 8}))
        self.assertEqual(kinds(pushed), ["bloom"])
        self.assertEqual(rig.eng.targets.flash, "ok")
        # A second claim re-seeds: the same seq never replays, a boot runs again.
        rig.eng.release(1100)                                        # immediate: down at 1100
        self.assertEqual([(e.type, e.t0) for e in rig.pushed[-1:]], [("down", 1100)])
        self.assertEqual(rig.render(1116, frame), [])
        pushed = rig.claim(1200, dict(frame, feedback={"kind": "err", "seq": 9}))
        self.assertEqual(kinds(pushed), ["boot"])
        self.assertIsNone(rig.eng.targets.flash)

    def test_boot_home_flag_is_the_first_frame_family(self):
        rig = Rig(0)
        pushed = rig.claim(500, list_frame(10, 2))
        self.assertEqual(kinds(pushed), ["boot"])
        self.assertFalse(pushed[0].home)
        self.assertEqual(rig.eng.animator.effects[-1].type, "boot")
        # Claimed without a frame: dark and awake; boot waits for the first frame.
        rig = Rig(0)
        rig.eng.claim(10)
        self.assertEqual(rig.render(10), [])
        self.assertEqual(lit(rig.eng.targets.ring), {})
        self.assertEqual(kinds(rig.render(26, home_frame(54))), ["boot"])

    def test_release_down_snapshots_and_goes_offline(self):
        rig = Rig(0)
        rig.claim(1000, home_frame(54))
        rig.run(1016, 1500, frame=home_frame(54))
        snapshot = rig.eng.animator.snapshot()
        cursor = rig.eng.cursor()
        self.assertEqual(cursor, 2)
        mark = len(rig.pushed)
        rig.eng.release(1500)
        rig.eng.release(1501)                                        # already released: no-op
        rig.eng.detent(1501, 1)                                      # after release: ignored
        rig.eng.press(1501, 0)
        self.assertEqual(kinds(rig.pushed[mark:]), ["down"])
        down = rig.pushed[mark]
        self.assertEqual((down.at, down.t0), (cursor, 1500))         # the release's own time
        self.assertEqual((down.snap, down.bsnap), snapshot)
        self.assertEqual(rig.render(1504), [])
        self.assertTrue(rig.eng.targets.offline)
        self.assertEqual(rig.eng.targets.buttons, [None] * 4)
        self.assertEqual((rig.eng.cursor(), rig.eng.asleep()), (0, False))
        # down is foreground: it kills the boot that may still run.
        self.assertIn("boot", kinds(rig.eng.animator.effects))
        self.assertTrue(all(e.kill == 1500 for e in rig.eng.animator.effects if e.type == "boot"))

    def test_render_output_shape(self):
        rig = Rig(0)
        rig.claim(0, home_frame(54))
        ring, buttons = rig.eng.render(16, home_frame(54))
        self.assertEqual((len(ring), len(buttons)), (60, 4))
        self.assertTrue(all(len(c) == 3 and all(0 <= x <= 1 for x in c) for c in ring + buttons))


class SleepTests(unittest.TestCase):
    def setUp(self):
        self.rig = Rig(0)
        self.rig.claim(1000, home_frame(54))

    def test_claim_counts_as_input(self):
        self.rig.render(5999)
        self.assertFalse(self.rig.eng.asleep())
        self.rig.render(6000)
        self.assertTrue(self.rig.eng.asleep())
        self.assertEqual(self.rig.eng.targets.ring[2], warm(3, 0.34))

    def test_every_input_restarts_the_timer(self):
        for method, args in (("detent", (1,)), ("limit", (1,)), ("press", (2,))):
            rig = Rig(0)
            rig.claim(1000, home_frame(54))
            getattr(rig.eng, method)(4000, *args)
            rig.render(4010)
            rig.render(8999)
            self.assertFalse(rig.eng.asleep(), method)
            rig.render(9000)
            self.assertTrue(rig.eng.asleep(), method)

    def test_pending_rechecks_every_second(self):
        rig = self.rig
        rig.render(6000, home_frame(60, c=54))                     # pending at the deadline
        self.assertFalse(rig.eng.asleep())
        rig.render(6500, home_frame(60, c=60))                     # answered, awake until the re-check
        rig.render(6999)
        self.assertFalse(rig.eng.asleep())
        rig.render(7000)
        self.assertTrue(rig.eng.asleep())

    def test_flash_rechecks_every_second(self):
        rig = self.rig
        rig.render(5800, home_frame(54, feedback={"kind": "ok", "seq": 3}))   # flash to 6450
        rig.render(6000)
        self.assertFalse(rig.eng.asleep())
        rig.render(6449)
        self.assertEqual(rig.eng.targets.flash, "ok")
        rig.render(6450)
        self.assertIsNone(rig.eng.targets.flash)
        rig.render(6999)
        self.assertFalse(rig.eng.asleep())
        rig.render(7000)
        self.assertTrue(rig.eng.asleep())

    def test_err_flash_window_is_900ms(self):
        rig = self.rig
        rig.render(2000, home_frame(54, feedback={"kind": "err", "seq": 3}))
        rig.render(2899)
        self.assertEqual(rig.eng.targets.flash, "err")
        rig.render(2900)
        self.assertIsNone(rig.eng.targets.flash)

    def test_pending_and_flash_wake_a_resting_knob(self):
        rig = self.rig
        rig.render(6000)
        self.assertTrue(rig.eng.asleep())
        pushed = rig.render(7000, home_frame(60, c=54))             # pending: effectiveAsleep false
        self.assertEqual(kinds(pushed), ["wake"])
        self.assertFalse(rig.eng.asleep())
        self.assertEqual(rig.render(7300, home_frame(60, c=60)), [])  # stateAsleep still true
        self.assertTrue(rig.eng.asleep())
        pushed = rig.render(8000, home_frame(60, c=60, feedback={"kind": "ok", "seq": 4}))
        self.assertEqual(kinds(pushed), ["wake", "bloom"])          # design detect() order
        rig.render(8650)
        self.assertTrue(rig.eng.asleep())

    def test_wake_on_detent_and_press(self):
        rig = self.rig
        rig.render(6000)
        rig.eng.detent(6100, 1)
        pushed = rig.render(6110, home_frame(55), 55, 100)
        self.assertEqual(kinds(pushed), ["wake", "tick"])
        self.assertEqual((pushed[0].at, pushed[1].at), (2, 2))       # 55: 35 + 27 [M13]
        self.assertFalse(rig.eng.asleep())
        self.assertEqual(rig.eng.targets.ring[2], warm(3, 1.0))      # awake targets in this very frame
        rig.render(11099, home_frame(55), 55, 100)
        self.assertFalse(rig.eng.asleep())                           # the detent's own time + 5000
        rig.render(11100, home_frame(55), 55, 100)
        self.assertTrue(rig.eng.asleep())
        rig.eng.press(11200, 3)
        pushed = rig.render(11210)
        self.assertEqual(kinds(pushed), ["press", "wake"])
        self.assertEqual(pushed[0].n, 3)


class InputEventTests(unittest.TestCase):
    def setUp(self):
        self.rig = Rig(0)
        self.rig.claim(1000, home_frame(54))

    def test_tick_length_follows_velocity(self):
        rig = self.rig
        lengths = []
        for k, t in enumerate((2000, 2040, 2080, 2120)):
            rig.eng.detent(t, 1)
            lengths.append(rig.render(t + 1, home_frame(54), 55 + k, 100)[0].len)
        self.assertEqual(lengths, [0, 4, 7, 7])                   # vel 0, 11.25, 17.44, 20.84
        self.assertAlmostEqual(rig.eng._vel, (11.25 * 0.55 + 11.25) * 0.55 + 11.25, places=12)
        rig.eng.detent(2621, 1)                                    # > 400 ms gap: velocity resets
        self.assertEqual(rig.render(2622, home_frame(54), 59, 100)[0].len, 0)
        rig.eng.detent(2631, 3)                                    # dtR min 16, |delta| counts
        tick = rig.render(2632, home_frame(54), 62, 100)[0]
        vel = 1000 * 3 / 16 * 0.45
        self.assertEqual(tick.len, al.js_round(min(1, max(0, (vel - 4) / 14)) * 7))

    def test_tick_length_tie_rule(self):
        """[D19] 6.2 len = round(x + 1e-4) (JS Math.round), x = clamp((vel - 4)/14) * 7, so the exact
        .5 ties that whole-ms detent gaps produce round up in float64 and in the firmware's float32
        alike. Pinned side effect of D19: a pre-round value less than 1e-4 below a tie rounds up
        too, where exact Math.round rounds down; 1.8e-4 below, it rounds down. Mirrors
        alive_tests.cpp tieChecks()."""
        from fractions import Fraction

        def last_len(*gaps):
            rig = Rig(0)
            rig.claim(1000, home_frame(54))
            t = 2000
            for k, gap in enumerate((0,) + gaps):                   # the first detent: velocity 0
                t += gap
                rig.eng.detent(t, 1)
                pushed = rig.render(t, home_frame(54), 55 + k, 100)
            return [e for e in pushed if e.type == "tick"][-1].len

        def exact(*gaps):                                          # exact x and Math.round(x)
            vel = Fraction(0)
            for gap in gaps:
                vel = vel * Fraction(55, 100) + Fraction(45, 100) * Fraction(1000, gap)
            x = (vel - 4) / 14 * 7
            return x, math.floor(x + Fraction(1, 2))
        self.assertEqual(al.TICK_TIE_BIAS, 1e-4)
        self.assertEqual(exact(90), (Fraction(1, 2), 1))
        self.assertEqual(last_len(90), 1)                           # exact tie (vel 5): half up
        x, rounded = exact(83, 223)
        self.assertTrue(Fraction(1, 2) - Fraction(1, 10000) < x < Fraction(1, 2))
        self.assertEqual((rounded, last_len(83, 223)), (0, 1))      # the 1e-4 window: up, not down
        x, rounded = exact(224, 57)
        self.assertTrue(Fraction(5, 2) - Fraction(2, 10000) < x < Fraction(5, 2) - Fraction(1, 10000))
        self.assertEqual((rounded, last_len(224, 57)), (2, 2))      # below the window: as Math.round

    def test_tick_direction(self):
        rig = self.rig
        rig.eng.detent(2000, 1)                                    # 54 -> 55: cursor stays 2 [M13]
        tick = rig.render(2001, home_frame(54), 55, 100)[0]
        self.assertEqual((tick.at, tick.dir), (2, 1))              # sign(delta)
        rig.eng.detent(2500, 1)                                    # 55 -> 56: 2 -> 3
        tick = rig.render(2501, home_frame(54), 56, 100)[0]
        self.assertEqual((tick.at, tick.dir), (3, 1))
        rig.eng.detent(3000, -1)                                   # 56 -> 55: 3 -> 2
        tick = rig.render(3001, home_frame(54), 55, 100)[0]
        self.assertEqual((tick.at, tick.dir), (2, -1))
        rig.eng.detent(3500, -1)                                   # 55 -> 54: stays 2, sign(delta)
        tick = rig.render(3501, home_frame(54), 54, 100)[0]
        self.assertEqual((tick.at, tick.dir), (2, -1))
        rig.render(3600, home_frame(49), 49, 100)                  # cursor 35 + 24 = 59
        rig.eng.detent(4000, 2)
        tick = rig.render(4001, home_frame(49), 51, 100)[0]        # 59 -> 0 wraps clockwise
        self.assertEqual((tick.at, tick.dir), (0, 1))

    def test_bound_colour_and_direction(self):
        rig = self.rig
        rig.render(2000, home_frame(100))
        rig.eng.limit(2010, 1)
        pushed = rig.render(2011)
        self.assertEqual(kinds(pushed), ["bound"])                  # no tick [D4]
        self.assertEqual((pushed[0].at, pushed[0].dir, pushed[0].c), (25, 1, RED))
        rig.render(2100, home_frame(0))
        rig.eng.limit(2110, -1)
        bound = rig.render(2111)[0]
        self.assertEqual((bound.at, bound.dir, bound.c), (35, -1, al.ENGINE_PALETTE.warm))
        self.assertEqual(kinds(rig.eng.animator.effects).count("bound"), 1)   # replaced
        rig.render(2200, list_frame(10, 2))
        rig.eng.limit(2210, -1)
        self.assertEqual(rig.render(2211)[0].c, f(sat_accent(2)))

    def test_input_caps_per_render(self):
        rig = self.rig
        for k in range(10):
            rig.eng.detent(2000 + k, 1)                            # the 9th and 10th merge into the 8th
        self.assertEqual(rig.eng._detents[-1], [2009, 3])
        for _ in range(6):
            rig.eng.limit(2000, 1)
        for k in range(10):
            rig.eng.press(2000, k % 4)
        rig.eng.press(2000, 4)                                     # not a slot
        rig.eng.limit(2000, 0)
        rig.eng.detent(2000, 0)
        pushed = kinds(rig.render(2010))
        self.assertEqual((pushed.count("tick"), pushed.count("bound"), pushed.count("press")), (8, 4, 8))
        self.assertEqual(len(rig.eng.animator.effects), 8)
        self.assertEqual(rig.render(2026), [])                     # consumed

    def test_claim_resets_the_velocity(self):
        rig = self.rig
        rig.eng.detent(2000, 1)
        rig.render(2001)
        rig.eng.detent(2040, 1)
        self.assertEqual(rig.render(2041)[0].len, 4)
        rig.eng.release(2050)
        rig.claim(2060, home_frame(54))
        rig.eng.detent(2080, 1)                                    # 40 ms later, but a new session
        self.assertEqual(rig.render(2081)[0].len, 0)
        self.assertEqual(rig.eng._vel, 0.0)

    def test_fixed_effect_order_in_one_render(self):
        rig = self.rig
        rig.render(6000)
        self.assertTrue(rig.eng.asleep())
        rig.eng.press(6100, 0)
        rig.eng.detent(6101, 1)
        rig.eng.limit(6102, 1)
        pushed = rig.render(6110, list_frame(10, 2, feedback={"kind": "err", "seq": 5}))
        self.assertEqual(kinds(pushed), ["press", "wake", "tick", "bound", "reveal", "fail"])


class FrameEventTests(unittest.TestCase):
    def setUp(self):
        self.rig = Rig(0)
        self.rig.claim(1000, home_frame(54))

    def test_mode_reveal(self):
        rig = self.rig
        self.assertEqual(rig.render(1100, home_frame(54, layout="volume")), [])   # same family
        self.assertEqual(kinds(rig.render(1200, list_frame(10, 2))), ["reveal"])
        self.assertEqual(rig.render(1300, list_frame(10, 3)), [])
        self.assertEqual(kinds(rig.render(1400, tracks_frame(1))), ["reveal"])

    def test_feedback_err_fail_and_skip_sweep(self):
        rig = self.rig
        rig.render(1100, tracks_frame(2))
        pushed = rig.render(1200, tracks_frame(1, feedback={"kind": "ok", "seq": 2, "skip": 1}))
        self.assertEqual(kinds(pushed), ["sweep"])
        self.assertEqual((pushed[0].at, pushed[0].dir), (8, 1))     # at the PREVIOUS cursor [D9][M21]
        pushed = rig.render(1300, tracks_frame(1, feedback={"kind": "ok", "seq": 3, "skip": -1}))
        self.assertEqual((pushed[0].at, pushed[0].dir), (0, -1))
        pushed = rig.render(1400, tracks_frame(1, feedback={"kind": "err", "seq": 4, "skip": 1}))
        self.assertEqual(kinds(pushed), ["fail"])                   # skip only with ok
        pushed = rig.render(1500, tracks_frame(1, feedback={"kind": "ok", "seq": 5, "skip": 2}))
        self.assertEqual(kinds(pushed), ["bloom"])                  # invalid skip ignored
        pushed = rig.render(1600, home_frame(90, feedback={"kind": "err", "seq": 6}))
        self.assertEqual(kinds(pushed), ["reveal", "fail"])
        self.assertEqual(pushed[1].at, 35 + 45 - 60)
        self.assertEqual(rig.render(1700), [])                       # same seq: nothing new
        self.assertEqual(rig.render(1800, home_frame(90, feedback={"kind": "maybe", "seq": 7})), [])

    def test_wash_from_recent_and_windows(self):
        rig = self.rig
        rig.render(1100, list_frame(10, 2))
        rig.render(1200, list_frame(10, 2, activity="pending"))    # cursor pulses WARM
        pushed = rig.render(1300, home_frame(54, feedback={"kind": "ok", "seq": 2}))
        self.assertEqual(kinds(pushed), ["reveal", "wash"])         # [D7] accent despite the pulse
        self.assertEqual((pushed[1].at, pushed[1].c), (slot(2, 10), f(sat_accent(2))))
        rig.render(1400, list_frame(9, 1, windows=True))
        rig.render(1500, list_frame(9, 1, windows=True, activity="pending"))
        pushed = rig.render(1600, home_frame(54, feedback={"kind": "ok", "seq": 3}))
        self.assertEqual((kinds(pushed), pushed[1].at, pushed[1].c),
                         (["reveal", "wash"], slot(1, 9), f(sat_accent(1))))

    def test_bloom_without_an_accent(self):
        for frame in (list_frame(5, 1, colors=[0x808080] * 5), list_frame(10, 2, led="white"),
                      list_frame(11, 10, more=10), home_frame(40)):
            rig = Rig(0)
            rig.claim(1000, home_frame(54))
            rig.render(1100, frame)
            pushed = rig.render(1200, home_frame(54, feedback={"kind": "ok", "seq": 2}))
            with self.subTest(frame=frame["layout"]):
                self.assertEqual(kinds(pushed)[-1], "bloom")
                self.assertEqual((pushed[-1].at, pushed[-1].c), (2, al.GREEN))   # the new cursor, GREEN

    def test_play_pause(self):
        rig = self.rig
        rig.render(1100, home_frame(54, playing=True))
        pushed = rig.render(1200, home_frame(54, playing=False))
        self.assertEqual(kinds(pushed), ["drain"])
        self.assertEqual(pushed[0].n, 27)
        pushed = rig.render(1300, home_frame(55, playing=True))
        self.assertEqual((kinds(pushed), pushed[0].n), (["fill"], 28))
        self.assertEqual(rig.render(1400, home_frame(55)), [])      # absent: no information
        self.assertEqual(rig.render(1500, home_frame(55, playing=False)), [])   # [D8] both must carry it
        pushed = rig.render(1550, home_frame(55, playing=True), 71, 100)
        self.assertEqual((kinds(pushed), pushed[0].n), (["fill"], 36))           # displayed (local) volume
        rig.render(1600, list_frame(10, 2))
        pushed = rig.render(1700, home_frame(55, playing=False, feedback={"kind": "ok", "seq": 9}))
        self.assertEqual(kinds(pushed), ["reveal", "wash"])         # album start washes, no drain
        # 6.4.3 as written: the true that follows an ok frame's false is a change, so fill (FG) cuts
        # the 1100 ms wash (the engine rule; [R4] keeps the host from sending that false) ...
        self.assertEqual(kinds(rig.render(2100, home_frame(55, playing=True))), ["fill"])
        self.assertEqual([e.kill for e in rig.eng.animator.effects if e.type == "wash"], [2100])
        # ... while an ok frame without playing (transport not confirmed yet: [R4]) lets it run out [D8].
        rig.render(2200, list_frame(10, 2))
        pushed = rig.render(2300, home_frame(55, feedback={"kind": "ok", "seq": 10}))
        self.assertEqual(kinds(pushed), ["reveal", "wash"])
        self.assertEqual(rig.render(2700, home_frame(55, playing=True)), [])
        self.assertEqual([(e.t0, e.kill) for e in rig.eng.animator.effects if e.type == "wash"], [(2300, None)])

    def test_external_shimmer_and_short_sleep(self):
        rig = self.rig
        rig.render(2000, home_frame(54))
        pushed = rig.render(2100, home_frame(38, external=True))
        self.assertEqual(kinds(pushed), ["shimmer"])
        self.assertEqual((pushed[0].frm, pushed[0].to), (2, (35 + 19) % 60))
        self.assertEqual(rig.render(2200, home_frame(38, external=True)), [])
        rig.render(5299)
        self.assertFalse(rig.eng.asleep())
        rig.render(5300)                                            # 2100 + 3200
        self.assertTrue(rig.eng.asleep())
        rig.render(5400, home_frame(38))
        pushed = rig.render(5500, home_frame(40, external=True))    # resting: wake then shimmer
        self.assertEqual(kinds(pushed), ["wake", "shimmer"])
        rig.render(5600, list_frame(10, 2, external=True))
        self.assertEqual(kinds(rig.render(5700, home_frame(40, external=True))), ["reveal"])


class TimeOfDayAndSongTests(unittest.TestCase):
    def test_tod_scales_rest_only(self):
        rig = Rig(0)
        rig.claim(1000, home_frame(54, playing=True))
        rig.render(1016)
        self.assertEqual(rig.eng.tod_b, 1.0)                        # no clock latched
        rig.eng.set_clock(1016, 23 * 60)
        rig.render(1032)
        self.assertAlmostEqual(rig.eng.tod_b, al.tod_brightness((23 * 60 + 16 / 60000) / 60), places=12)
        self.assertAlmostEqual(rig.eng.tod_b, 0.65 - 0.1 * (0.5 + 16 / 3600000) / 1.5, places=9)
        rig.render(1032 + 90 * 60000)                               # 00:30 the next day
        self.assertAlmostEqual(rig.eng.tod_b, al.tod_brightness((30 + (16 + 90 * 60000) / 60000 - 90) / 60), places=12)
        self.assertAlmostEqual(rig.eng.tod_b, 0.555, places=6)
        rig.eng.set_clock(0, 1440)                                  # invalid: ignored
        rig.eng.set_clock(0, -1)
        rig.render(1032 + 90 * 60000 + 16)
        self.assertLess(rig.eng.tod_b, 0.6)

    def test_song_hand_latch_and_freeze(self):
        rig = Rig(0)
        rig.claim(1000, home_frame(54, playing=True))
        rig.eng.set_progress(1000, 30000, 200000)
        rig.render(1016)
        self.assertIsNone(rig.eng.song_prog)                        # awake: no hand
        rig.render(6000)
        self.assertTrue(rig.eng.asleep())
        self.assertAlmostEqual(rig.eng.song_prog, (30000 + 5000) / 200000, places=12)
        rig.render(16000, home_frame(54, playing=True))
        self.assertAlmostEqual(rig.eng.song_prog, (30000 + 15000) / 200000, places=12)
        rig.render(20000, home_frame(54, playing=False))            # freezes at 49 s, hand hidden
        self.assertIsNone(rig.eng.song_prog)
        self.assertEqual(rig.eng._prog_pos, 49000)
        rig.render(30000, home_frame(54, playing=True))             # resumes from the frozen position
        rig.render(40000)
        self.assertAlmostEqual(rig.eng.song_prog, (49000 + 10000) / 200000, places=12)
        rig.render(45000, home_frame(54))                           # [R3] absent on Home: not playing
        self.assertTrue(rig.eng.asleep())
        self.assertIsNone(rig.eng.song_prog)                        # hidden ...
        self.assertEqual(rig.eng._prog_pos, 64000)                  # ... and frozen, as with false
        rig.render(48000, home_frame(54))
        self.assertIsNone(rig.eng.song_prog)
        rig.render(50000, list_frame(10, 2))                        # other families never touch it
        rig.render(60000, home_frame(54, playing=True))
        rig.render(61000)
        self.assertTrue(rig.eng.asleep())
        self.assertAlmostEqual(rig.eng.song_prog, (64000 + 1000) / 200000, places=12)
        rig.render(400000)
        self.assertEqual(rig.eng.song_prog, 1.0)                    # clamped
        rig.render(400100, home_frame(54, playing=False))
        self.assertEqual(rig.eng._prog_pos, 200000)                 # frozen at the end, not past it
        rig.render(400200, home_frame(54, playing=True))
        rig.eng.set_progress(400200, 0, 0)                          # dur 0 clears
        rig.render(400216)
        self.assertIsNone(rig.eng.song_prog)

    def test_song_hand_needs_home_rest_and_playing(self):
        rig = Rig(0)
        rig.claim(1000, list_frame(10, 2))
        rig.eng.set_progress(1000, 0, 100000)
        rig.render(7000)
        self.assertTrue(rig.eng.asleep())
        self.assertIsNone(rig.eng.song_prog)                        # not Home, never said playing
        rig.render(7100, home_frame(54))
        rig.render(13000)
        self.assertTrue(rig.eng.asleep())
        self.assertIsNone(rig.eng.song_prog)                        # Home, playing unknown
        rig.render(13016, home_frame(54, playing=True))             # runs from this render
        self.assertEqual(rig.eng.song_prog, 0.0)
        rig.render(14016)
        self.assertAlmostEqual(rig.eng.song_prog, 1000 / 100000, places=12)
        rig.eng.set_progress(14016, 150000, 100000)                 # pos is clamped to dur
        rig.render(14032)
        self.assertEqual(rig.eng.song_prog, 1.0)
        rig.eng.set_progress(14032, -5, 100000)                     # invalid: ignored
        rig.render(14048)
        self.assertEqual(rig.eng.song_prog, 1.0)
        rig.eng.release(14100)
        rig.render(14100)
        self.assertIsNone(rig.eng.song_prog)                        # offline
        rig.eng.claim(15000)
        rig.render(15000, home_frame(54))
        rig.render(21000)
        self.assertTrue(rig.eng.asleep())
        self.assertIsNone(rig.eng.song_prog)                        # the new session never said playing

    def test_song_hand_is_drawn(self):
        rig = Rig(0)
        rig.claim(1000, home_frame(54, playing=True))
        rig.eng.set_progress(1000, 0, 60000 * 60)                   # 1 segment per minute
        rig.eng.set_clock(1000, 12 * 60)
        rig.render(6000)
        prog = rig.eng.song_prog
        head = prog * 60
        self.assertLess(abs(head - 5000 / 60000), 1e-9)
        self.assertTrue(rig.eng.animating())
        # [user 2026-09-26] the progress is latched at rest, but the hand is not drawn there: the render
        # equals the same rest with no progress at all.
        other = Rig(0)
        other.claim(1000, home_frame(54, playing=True))
        other.eng.set_clock(1000, 12 * 60)
        other.render(6000)
        self.assertEqual(rig.out, other.out)


class RobustnessTests(unittest.TestCase):
    def test_uint32_wrap(self):
        start = 0xFFFFFFFF - 3000
        rig = Rig(start)
        rig.claim(start, home_frame(54))
        rig.render((start + 4000) & 0xFFFFFFFF)
        self.assertFalse(rig.eng.asleep())
        rig.render((start + 5000) & 0xFFFFFFFF)
        self.assertTrue(rig.eng.asleep())
        rig.eng.detent((start + 5100) & 0xFFFFFFFF, 1)
        pushed = rig.render((start + 5116) & 0xFFFFFFFF, home_frame(54), 55, 100)
        self.assertEqual(kinds(pushed), ["wake", "tick"])
        out, _ = rig.out
        self.assertEqual(len(out), 60)

    def test_animating(self):
        rig = Rig(0)
        rig.claim(0, home_frame(54))
        for t in range(0, 4000, 16):
            rig.render(t)
        self.assertFalse(rig.eng.animating())                       # settled, awake, no effects
        rig.eng.press(4000, 1)
        rig.render(4000)
        self.assertTrue(rig.eng.animating())
        for t in range(4016, 5000, 16):
            rig.render(t)
        self.assertFalse(rig.eng.animating())
        rig.render(9016)
        self.assertTrue(rig.eng.asleep() and rig.eng.animating())   # breathing

    def test_render_performance(self):
        """A busy frame (6 effects + heat + tint-free Home + pending comet) stays well under 4 ms."""
        rig = Rig(0)
        frame = home_frame(95, c=92, playing=True)
        rig.claim(0, frame)
        now = 16
        times = []
        for k in range(120):
            if k % 20 == 0:
                for kind, kw in (("bloom", {"at": 20}), ("wake", {"at": 20}), ("wash", {"at": 20, "c": (0.2, 0.5, 1)}),
                                 ("tick", {"at": 20, "len": 7}), ("reveal", {}), ("shimmer", {"frm": 5, "to": 20})):
                    rig.eng.animator.play(al.Effect(kind, now, **kw))
                for e in rig.eng.animator.effects:
                    e.kill = None
            t0 = time.perf_counter()
            rig.eng.render(now, frame, 95, 100)
            times.append(time.perf_counter() - t0)
            now += 16
        self.assertLess(statistics.median(times), 0.004)


# ======================================================================== oracle
def _max_error(ring, buttons, expect):
    errors = [abs(g - w) for got, want in zip(ring, expect["ring"]) for g, w in zip(got, want)]
    errors += [abs(g - w) for got, want in zip(buttons, expect["buttons"]) for g, w in zip(got, want)]
    return max(errors)


class OracleTests(unittest.TestCase):
    def test_design_oracle(self):
        """Every step of every case, twice: the uncapped animator (``cap=None``, the design's
        draw() with no queue cap) on all steps, and the production animator (cap 8, [D12]) on
        every step up to its first eviction. Only ``designUncapped`` cases may evict, exactly
        at the first step whose design queue exceeds 8; their ``live`` counts (the design's
        queue after draw) must equal the uncapped animator's."""
        self.assertTrue(ORACLE.exists(), "tests/fixtures/alive_oracle.json is missing: "
                        "node tests/js/alive_oracle.cjs design-reference/design_handoff_led_choreography "
                        "tests/fixtures/alive_oracle.json")
        data = json.loads(ORACLE.read_text(encoding="utf-8"))
        self.assertEqual(data.get("version"), 1)
        tolerance = data.get("tolerance", 0.002)
        design = data.get("designConstants")
        if design is not None:                  # the literals draw() uses must be the ones we inject
            palette = al.design_palette((1, 0.6, 0.3), None)
            self.assertEqual([list(palette.green), list(palette.red), list(palette.blue)],
                             [design["GRN"], design["RED"], design["BLUE"]])
            for got, want in zip(al.mix(palette.green, (1, 1, 1), 0.3), design["bloomSpark"]):
                self.assertAlmostEqual(got, want, places=9)
            self.assertEqual(al.AliveAnimator().ring[0], design["curInit"])
            self.assertEqual(al.AliveAnimator().buttons[0], design["bcurInit"])
            self.assertEqual({k: al.DUR[k] for k in design["DUR"]}, design["DUR"])   # RC's 15 effects
            self.assertEqual(al.FG & set(design["DUR"]), set(design["FG"]))
        steps = capped_compared = after_eviction = 0
        worst = (0.0, None)
        for case in data["cases"]:
            uncapped = bool(case.get("designUncapped"))
            capped = al.run_oracle_case(case)
            shadow = al.run_oracle_case(case, cap=None)
            first_eviction = None
            over = [s["t"] for s in case["steps"] if s.get("queue", 0) > al.QUEUE_CAP]
            for (step, ring, buttons, animator), (_, sring, sbuttons, design) in zip(capped, shadow):
                expect = step["expect"]
                steps += 1
                with self.subTest(case=case["name"], t=step["t"]):
                    self.assertEqual((len(expect["ring"]), len(expect["buttons"])), (al.SEGMENTS, al.BUTTON_SLOTS))
                    self.assertEqual((len(sring), len(sbuttons), len(ring), len(buttons)),
                                     (al.SEGMENTS, al.BUTTON_SLOTS, al.SEGMENTS, al.BUTTON_SLOTS))
                    error = _max_error(sring, sbuttons, expect)          # the design, uncapped
                    if error > worst[0]:
                        worst = (error, (case["name"], step["t"], "uncapped"))
                    self.assertLessEqual(error, tolerance)
                    if "live" in step:
                        self.assertEqual(len(design.effects), step["live"])
                    self.assertLessEqual(len(animator.effects), al.QUEUE_CAP)
                    if animator.evictions and first_eviction is None:
                        first_eviction = step["t"]
                    if first_eviction is None:                           # the production cap, D12
                        error = _max_error(ring, buttons, expect)
                        if error > worst[0]:
                            worst = (error, (case["name"], step["t"], "capped"))
                        self.assertLessEqual(error, tolerance)
                        capped_compared += 1
                    else:
                        after_eviction += 1
            with self.subTest(case=case["name"], check="eviction"):
                self.assertEqual(first_eviction, over[0] if over else None)
                if not uncapped:
                    self.assertIsNone(first_eviction)
        self.assertGreater(steps, 0)
        print(f"\n[alive oracle] {len(data['cases'])} cases, {steps} steps: uncapped animator compared on all "
              f"{steps}, cap-8 animator on {capped_compared} ({after_eviction} after its first D12 eviction "
              f"not compared); worst {worst[0]:.2e} at {worst[1]}")

    def test_bs_oracle(self):
        """[r2] 11.2 (gate A2): the r2.1 Browse and Snap draw() (tests/js/alive_oracle_bs.cjs), with BS's
        palette, its reduced motion (play()'s drop list and the stationary fail) and its half, scatter
        and colour bloom; every step within the tolerance, the production cap never evicting."""
        self.assertTrue(BS_ORACLE.exists(), "tests/fixtures/alive_oracle_bs.json is missing: node "
                        "tests/js/alive_oracle_bs.cjs design-reference/design_handoff_nano_d_master_r2.1/prototypes "
                        "tests/fixtures/alive_oracle_bs.json")
        data = json.loads(BS_ORACLE.read_text(encoding="utf-8"))
        self.assertEqual(data.get("version"), 1)
        tolerance = data.get("tolerance", 0.002)
        design = data["designConstants"]
        palette = al.bs_palette(design)
        self.assertEqual((design["WARM8"], design["PINK8"], design["AMBER8"], design["RED8"], design["GREEN8"]),
                         ([255, 190, 105], [255, 40, 90], [255, 131, 56], [255, 0, 0], [0, 255, 98]))
        self.assertEqual(set(design["rmDrop"]), al.REDUCED_MOTION_DROP)
        self.assertEqual({k: al.DUR[k] for k in design["DUR"]}, design["DUR"])      # half 900, scatter 700
        self.assertEqual(al.FG & set(design["DUR"]), set(design["FG"]))
        self.assertEqual(al.AliveAnimator().ring[0], design["curInit"])
        covered = set(design["DUR"]) | set(json.loads(ORACLE.read_text(encoding="utf-8"))["designConstants"]["DUR"])
        self.assertEqual(covered, set(al.DUR))                            # the two oracles cover every effect
        steps, worst, dropped = 0, (0.0, None), 0
        for case in data["cases"]:
            animator = al.AliveAnimator()
            targets = song = None
            for step in case["steps"]:
                view = step.get("view")
                if view is not None:
                    targets = al.oracle_targets(view)
                    song = view.get("songProg")
                    animator.reduced_motion = bool(view.get("rm"))
                for spec in step.get("effects", ()):
                    got = animator.play(al.oracle_effect(spec, animator, palette))
                    self.assertEqual(got is None, bool(spec.get("dropped")), (case["name"], spec))
                    dropped += got is None
                ring, buttons = animator.step(step["t"], step["dt"], targets, song, case["todB"], palette)
                error = _max_error(ring, buttons, step["expect"])
                steps += 1
                if error > worst[0]:
                    worst = (error, (case["name"], step["t"]))
                with self.subTest(case=case["name"], t=step["t"]):
                    self.assertLessEqual(error, tolerance)
            self.assertEqual(animator.evictions, 0, case["name"])
        self.assertGreater(steps, 2000)
        self.assertGreater(dropped, 4)
        print(f"\n[alive BS oracle] {len(data['cases'])} cases, {steps} steps, {dropped} reduced-motion drops; "
              f"worst {worst[0]:.2e} at {worst[1]}")


class MomentTests(unittest.TestCase):
    """6.4 [r2] rows c-h, the flash rule [M7], the hold [M22], row i on the new list families [M10],
    the M16 PLAY/PAUSE guard and MODE on transport <-> lap."""

    def setUp(self):
        self.rig = Rig(0)
        self.q = list5(12, 6, layout="upnext", now=4)
        self.rig.claim(1000, self.q)
        self.rig.render(4000)

    def moment(self, seq, name, frame=None, **fields):
        base = frame or self.q
        return dict(base, feedback={"kind": "ok", "seq": seq, "moment": name, **fields})

    def test_queued_sweeps_from_twelve(self):
        pushed = self.rig.render(4100, self.moment(2, "queued"))
        self.assertEqual([(e.type, e.at, e.dir) for e in pushed], [("sweep", 0, 1)])
        self.assertIsNone(self.rig.eng.targets.flash)                     # [M7]
        self.assertEqual(self.rig.eng._hold_ms, 640)

    def test_shuffle_draws_the_prng(self):
        rig = self.rig
        seeds = []
        state = al.RNG_SEED
        for seq in (2, 3, 4):
            state = al.xorshift32(state)
            seeds.append(al.scatter_seed(state))
            pushed = rig.render(4100 + 100 * seq, self.moment(seq, "shuffle"))
            self.assertEqual([(e.type, e.at) for e in pushed], [("scatter", rig.eng.cursor())])
            self.assertEqual(pushed[0].seed, seeds[-1])
        self.assertEqual(rig.eng.seeds, seeds)
        self.assertTrue(all(0 <= s < 60 for s in seeds))
        self.assertEqual(al.xorshift32(1), 0x42021)                       # 1 ^ 1<<13 = 0x2001, ^>>17, ^<<5
        self.assertEqual(al.scatter_seed(0xFFFFFFFF), 60 * 0xFFFFFF / 2 ** 24)
        self.assertEqual(rig.eng._hold_ms, 700)

    def test_like_and_unlike(self):
        rig = self.rig
        pushed = rig.render(4100, self.moment(2, "like"))
        self.assertEqual([(e.type, e.at, e.c) for e in pushed], [("bloom", rig.eng.cursor(), al.PINK)])
        self.assertEqual(rig.eng._hold_ms, 900)
        self.assertEqual(rig.render(4200, self.moment(3, "unlike")), [])
        self.assertEqual((rig.eng._hold_ms, rig.eng.targets.flash), (0, None))

    def test_snap_half(self):
        rig = self.rig
        w = list5(7, 2, layout="windows")
        rig.render(4100, w)
        pushed = rig.render(4200, self.moment(2, "snap", w, side=-1, color=0x2050A0))
        self.assertEqual([(e.type, e.side, e.c) for e in pushed], [("half", -1, f(al.sat((0x20, 0x50, 0xA0))))])
        pushed = rig.render(4300, self.moment(3, "snap", w, side=1, color=0))
        self.assertEqual([(e.type, e.side, e.c) for e in pushed], [("half", 1, al.ENGINE_PALETTE.warm)])
        pushed = rig.render(4400, self.moment(4, "snap", dict(w, ledStyle="white"), side=1, color=0x2050A0))
        self.assertEqual(pushed[0].c, al.ENGINE_PALETTE.warm)             # Warm only
        self.assertEqual(rig.eng._hold_ms, 900)

    def test_started(self):
        """Row h [M16]: a wash in the accent at the new cursor, or a green bloom; never fill/drain."""
        rig = self.rig
        rig.render(4100, home_frame(54, playing=False, buttons=PAUSED_BUTTONS))
        pushed = rig.render(4200, self.moment(2, "started", home_frame(54, playing=True), color=0x3070E0))
        self.assertEqual([(e.type, e.at, e.c) for e in pushed], [("wash", 2, f(al.sat((0x30, 0x70, 0xE0))))])
        self.assertEqual(rig.eng._hold_ms, 1100)
        for k, colour in enumerate((0, 0x808890)):
            rig.render(4300 + 200 * k, home_frame(54, playing=False, buttons=PAUSED_BUTTONS))
            pushed = rig.render(4400 + 200 * k, self.moment(3 + k, "started", home_frame(54, playing=True), color=colour))
            self.assertEqual([(e.type, e.c) for e in pushed], [("bloom", al.GREEN)], colour)
            self.assertEqual(rig.eng._hold_ms, 900)
        white = dict(home_frame(54, playing=True), ledStyle="white")
        pushed = rig.render(4800, self.moment(9, "started", white, color=0x3070E0))
        self.assertEqual(kinds(pushed), ["bloom"])                        # warm-only: the green bloom

    def test_row_order_and_the_flash_rule(self):
        rig = self.rig
        pushed = rig.render(4100, dict(self.q, feedback={"kind": "err", "seq": 2, "moment": "like"}))
        self.assertEqual(kinds(pushed), ["fail"])                         # a: err wins
        self.assertEqual(rig.eng.targets.flash, "err")
        rig.render(4200, tracks_frame(2))
        pushed = rig.render(4300, dict(tracks_frame(1), feedback={"kind": "ok", "seq": 3, "skip": 1, "moment": "like"}))
        self.assertEqual([(e.type, e.at, e.dir) for e in pushed], [("sweep", 8, 1)])   # b before c-h; [M21]
        self.assertEqual(rig.eng.targets.flash, "ok")
        pushed = rig.render(4400, dict(tracks_frame(1), feedback={"kind": "ok", "seq": 4, "moment": "like"}))
        self.assertEqual(kinds(pushed), ["bloom"])
        self.assertIsNone(rig.eng.targets.flash)                          # the moment ends the flash
        pushed = rig.render(4500, dict(tracks_frame(1), feedback={"kind": "ok", "seq": 5, "moment": "rocket"}))
        self.assertEqual(kinds(pushed), ["bloom"])                        # an unknown token: row j
        self.assertEqual(rig.eng.targets.flash, "ok")

    def test_row_i_from_the_new_list_families(self):
        for layout in ("explorer", "upnext", "windows", "recent"):
            rig = Rig(0)
            rig.claim(1000, home_frame(54))
            rig.render(2000, list5(12, 6, layout=layout, now=4 if layout == "upnext" else None))
            pushed = rig.render(2100, home_frame(54, feedback={"kind": "ok", "seq": 2}))
            with self.subTest(layout=layout):
                self.assertEqual([(e.type, e.at, e.c) for e in pushed],
                                 [("reveal", 2, None), ("wash", slot(6, 12), f(sat_accent(6)))])
        rig = Rig(0)                                                     # the card: no accent -> bloom
        rig.claim(1000, home_frame(54))
        rig.render(2000, list5(6, 5, layout="upnext", colors=[accent(j) for j in range(5)] + [0], now=4, card=True))
        self.assertEqual(kinds(rig.render(2100, home_frame(54, feedback={"kind": "ok", "seq": 2}))), ["reveal", "bloom"])

    def test_mode_on_transport_lap_and_not_on_a_tab_switch(self):
        rig = self.rig
        self.assertEqual(kinds(rig.render(4100, tracks_frame(1))), ["reveal"])
        self.assertEqual(kinds(rig.render(4200, lap_frame(74, 300))), ["reveal"])       # Seek enter
        self.assertEqual(rig.render(4300, lap_frame(79, 300)), [])
        self.assertEqual(kinds(rig.render(4400, tracks_frame(1))), ["reveal"])          # Seek exit
        self.assertEqual(kinds(rig.render(4500, list5(24, 3, layout="explorer", page=0))), ["reveal"])
        self.assertEqual(rig.render(4600, list5(2, 0, layout="explorer", page=1)), [])  # tab switch
        self.assertEqual(kinds(rig.render(4700, list5(12, 4, layout="upnext", now=4))), ["reveal"])

    def test_the_hold_keeps_the_knob_awake(self):
        rig = Rig(0)
        rig.claim(0, self.q)
        rig.render(4980, self.moment(2, "like"))
        rig.render(5000)
        self.assertFalse(rig.eng.asleep())                               # [M22] re-check
        rig.render(5879)
        self.assertTrue(rig.eng.hold_active(5879) and not rig.eng.asleep())
        rig.render(6000)
        self.assertTrue(rig.eng.asleep())
        pushed = rig.render(6100, self.moment(3, "queued"))
        self.assertEqual(kinds(pushed), ["wake", "sweep"])                # a moment wakes a resting knob
        self.assertEqual(rig.render(6200, self.moment(4, "unlike")), [])
        rig.render(12000)
        self.assertTrue(rig.eng.asleep())


class ReducedMotionTests(unittest.TestCase):
    def test_drop_list_and_the_stationary_fail(self):
        """6.5 [M17]: wake, tick, sweep, scatter, reveal are dropped (not queued, kill nothing); the
        PRNG still draws; boot, bound, bloom, half, wash, press, fill, drain stay."""
        rig = Rig(0)
        rig.eng.set_reduced_motion(0, True)
        self.assertTrue(rig.eng.reduced_motion)
        rig.claim(1000, home_frame(54, playing=True))
        self.assertEqual(kinds(rig.eng.animator.effects), ["boot"])              # kept under reduced motion
        rig.eng.detent(4000, 1)
        self.assertEqual(kinds(rig.render(4001, home_frame(54, playing=True), 55, 100)), ["tick"])   # offered
        self.assertNotIn("tick", kinds(rig.eng.animator.effects))                   # ... and dropped
        rig.render(4100, list5(12, 6, layout="upnext", now=4))
        self.assertNotIn("reveal", [e.type for e in rig.eng.animator.effects if e.t0 == 4100])
        before = [(e.type, e.kill) for e in rig.eng.animator.effects]
        rig.render(4200, dict(list5(12, 6, layout="upnext", now=4), feedback={"kind": "ok", "seq": 2, "moment": "shuffle"}))
        self.assertEqual([(e.type, e.kill) for e in rig.eng.animator.effects if e.t0 != 4200], before)
        self.assertEqual(len(rig.eng.seeds), 1)                                     # drawn regardless
        self.assertEqual(rig.eng._hold_ms, 700)
        rig.render(4300, dict(list5(12, 6, layout="upnext", now=4), feedback={"kind": "ok", "seq": 3, "moment": "like"}))
        self.assertIn("bloom", kinds(rig.eng.animator.effects))
        rig.render(4400, dict(list5(12, 6, layout="upnext", now=4), feedback={"kind": "err", "seq": 4}))
        fail = [e for e in rig.eng.animator.effects if e.type == "fail"][-1]
        a = al.AliveAnimator()
        a.play(al.Effect("fail", 4400, at=fail.at))
        a.reduced_motion = True
        stationary, _ = a.step(4400 + 78, 0, al.AliveTargets(), None, 1.0)
        a.reduced_motion = False
        moving, _ = a.step(4400 + 78, 0, al.AliveTargets(), None, 1.0)
        self.assertEqual(max(range(60), key=lambda i: stationary[i][0]), fail.at)   # pos = at
        self.assertNotEqual(stationary, moving)
        rig.eng.set_reduced_motion(4500, False)
        rig.eng.detent(4600, 1)
        self.assertEqual(kinds(rig.render(4601, list5(12, 7, layout="upnext", now=4), 7, 11)), ["tick"])
        self.assertIn("tick", kinds(rig.eng.animator.effects))

    def test_reset_clears_the_latches(self):
        eng = al.AliveLights(0)
        eng.set_reduced_motion(0, True)
        eng.set_tuning(0, 0x00FF00, True)
        eng.reset(10)
        self.assertEqual((eng.reduced_motion, eng._vol_full, eng.palette.pink, eng._rng), (False, False, al.PINK, al.RNG_SEED))


class TuningTests(unittest.TestCase):
    def test_pink_and_vol_full(self):
        """3.2 [M24]: ledPink is the LED colour at full; PINK = its per-channel OETF; 0 = the constant."""
        eng = al.AliveLights(0)
        self.assertEqual(al.pink_from_led(0), al.PINK)
        led = al.pink_from_led(0xFF051A)
        for got, want in zip(led, al.PINK):
            self.assertAlmostEqual(got, want, delta=0.01)                 # within one LED count
        self.assertEqual(led, tuple(al.srgb_oetf(c / 255) for c in (0xFF, 0x05, 0x1A)))
        for c in (0, 0.002, 0.0031308, 0.2, 0.5, 1.0):
            self.assertAlmostEqual(al.srgb_eotf(al.srgb_oetf(c)), c, places=12)
        eng.set_tuning(0, 0xFF0C30, False)
        self.assertEqual(eng.palette.pink, al.pink_from_led(0xFF0C30))
        eng.claim(0)
        frame = list5(9, 2, layout="upnext", now=4, buttons=[
            {"label": "a", "enabled": True, "icon": "back"}, {"label": "b", "enabled": True, "icon": "shuffle"},
            {"label": "c", "enabled": True, "icon": "heart", "lit": "on"}, {"label": "d", "enabled": True, "icon": "play"}])
        for t in range(0, 3000, 16):
            _, buttons = eng.render(t, frame)
        want = al.tone(*(x * 0.30 for x in eng.palette.pink))
        for got, exp in zip(buttons[2], want):
            self.assertAlmostEqual(got, exp, places=6)                    # the liked heart in the tuned PINK at 0.30 [M32]
        eng.set_tuning(3000, 0, True)
        self.assertEqual((eng.palette.pink, eng._vol_full), (al.PINK, True))
        eng.render(3016, home_frame(85))
        self.assertEqual((eng.targets.ring[16].alpha, eng.targets.ring[18].alpha), (1.0, 1.0))
        eng.set_tuning(3100, -1, False)                                   # out of range: the constant
        self.assertEqual(eng.palette.pink, al.PINK)


class AliveKnobTests(unittest.TestCase):
    """The HMI's local-input sampler twin (CCAliveKnob) with the [Q1] push detector (12.5)."""

    def run_passes(self, knob, start, stop, pushing, pos=100, control=1, top=100, every=10):
        fired = []
        for t in range(start, stop, every):
            delta, limit = knob.sample(t, control, pos, pushing, top)
            if limit:
                fired.append((t, limit))
        return fired

    def test_detents_and_seeding(self):
        k = al.AliveKnob()
        self.assertEqual(k.sample(0, 3, 30, False, 100), (0, 0))         # the first sample only seeds
        self.assertEqual(k.sample(10, 3, 35, False, 100), (5, 0))
        self.assertEqual(k.sample(20, 4, 60, False, 100), (0, 0))        # a new id only seeds
        k.reset()
        self.assertEqual(k.sample(30, 4, 45, False, 100), (0, 0))        # [F1/W2] reused after a release
        self.assertEqual(k.sample(40, 0, 45, True, 100), (0, 0))
        self.assertFalse(k.valid)

    def test_every_push_fires_once(self):
        k = al.AliveKnob()
        k.sample(0, 1, 99, False, 100)
        self.assertEqual(k.sample(10, 1, 100, False, 100), (1, 0))       # arriving: no limit
        self.assertEqual(self.run_passes(k, 20, 320, True), [(20, 1)])   # the first push at once
        self.assertEqual(self.run_passes(k, 320, 420, False), [])        # spring back 100 ms
        self.assertEqual(self.run_passes(k, 420, 2420, True), [(420, 1)])   # a push again; held 2 s: one
        self.assertEqual(self.run_passes(k, 2420, 2480, False), [])
        self.assertEqual(self.run_passes(k, 2480, 2600, True), [])       # 70 ms after the last push: none
        self.assertEqual(self.run_passes(k, 2600, 2800, False), [])
        fired = []
        for n, t in enumerate(range(2800, 3100, 20)):                    # chatter at 20 ms during one push
            if k.sample(t, 1, 100, n % 2 == 0, 100)[1]:
                fired.append(t)
        self.assertEqual(fired, [2800])
        self.assertEqual(al.LIM_REARM_MS, 75)
        self.assertEqual(al.LIM_GAP_MS, 150)

    def test_gap_bounds_and_seeds(self):
        k = al.AliveKnob()
        k.sample(0, 5, 0, False, 40)
        self.assertEqual(k.sample(10, 5, 0, True, 40), (0, -1))
        k.sample(20, 5, 0, False, 40)
        self.assertEqual(k.sample(100, 5, 0, True, 40), (0, 0))          # re-armed, 90 ms after the fire
        k.sample(110, 5, 0, False, 40)
        self.assertEqual(k.sample(200, 5, 0, True, 40), (0, -1))
        mid = al.AliveKnob()
        mid.sample(0, 9, 20, False, 40)
        self.assertEqual(mid.sample(10, 9, 20, True, 40), (0, 0))        # away from both bounds
        one = al.AliveKnob()
        one.sample(0, 8, 0, False, 0)
        self.assertEqual(one.sample(10, 8, 0, True, 0), (0, -1))         # one position: -1
        r = al.AliveKnob()
        r.sample(0, 6, 40, True, 40)                                      # seeded while pushing
        r.sample(10, 6, 40, False, 40)
        self.assertEqual(r.sample(50, 6, 40, True, 40), (0, 0))          # 50 ms after the seed's push
        r.sample(60, 6, 40, False, 40)
        self.assertEqual(r.sample(150, 6, 40, True, 40), (0, 1))


class FrameRateTests(unittest.TestCase):
    """ALIVE.md 11.5 (the engine half; the floating knob's look and hidden renders are K4's): one input
    script sampled at 60, 120, 144, 240 and 360 Hz (integer-ms timestamps) gives e within 0.01 at the
    common instants, and skipping 1-3 vblanks resumes on the curve with no burst. Inputs fall on
    instants every rate samples (multiples of 250 ms), where the effects start in every run: the
    effects and the continuous layers are functions of now, and the damping composes exactly while its
    target holds. A render whose target changes applies the new target over its whole dt (the design's
    draw(t, dt) does the same), so a 60 Hz run starts a change up to one frame's damping ahead of a
    360 Hz run; that offset decays with the damping (tau <= 70 ms, the colour glide), so the comparison
    skips the 250 ms after a script event (400 ms after a sleep transition, whose resting damping has
    tau 700 ms) and checks the curve everywhere else."""

    SCRIPT = {
        0: ("claim", home_frame(54, playing=True)),
        1000: ("detent", 1), 1250: ("detent", 1), 1500: ("press", 2),
        2000: ("frame", list5(24, 6, layout="upnext", now=4)),
        2500: ("frame", dict(list5(24, 6, layout="upnext", now=4), feedback={"kind": "ok", "seq": 2, "moment": "like"})),
        3500: ("frame", dict(list5(24, 6, layout="upnext", now=4), feedback={"kind": "ok", "seq": 3, "moment": "shuffle"})),
        4500: ("frame", home_frame(95, playing=True)),
        5250: ("frame", dict(home_frame(95, playing=True), feedback={"kind": "err", "seq": 4})),
        6000: ("frame", list5(7, 2, layout="windows")),
        6250: ("frame", dict(list5(7, 2, layout="windows"), feedback={"kind": "ok", "seq": 5, "moment": "snap", "side": -1,
                                                                        "color": 0x2050A0})),
    }
    END = 12000
    SETTLE_MS, SLEEP_SETTLE_MS = 250, 400

    def run_at(self, times):
        eng, frame, local, out, done, asleep, flips = al.AliveLights(0), None, None, {}, set(), False, []
        for t in times:
            for at in sorted(k for k in self.SCRIPT if k <= t and k not in done):
                kind, value = self.SCRIPT[at]
                done.add(at)
                if kind == "claim":
                    eng.claim(at)
                    frame, local = value, (54, 100)
                elif kind == "detent":
                    eng.detent(at, value)
                    local = (local[0] + value, 100) if local else None
                elif kind == "press":
                    eng.press(at, value)
                else:
                    frame, local = value, None
            eased = eng.render(t, frame, *(local or (None, None)))
            # The ALIVE.md 11.5 property holds on the animator's e (functions of now + damping); r4's output easer
            # (ALIVE.md 16) then carries each rate's sampling of an effect's own edges for ~tau: checked apart.
            out[t] = (eng.raw[0], eng.raw[1], eased)
            if eng.asleep() != asleep:
                asleep = eng.asleep()
                flips.append(t)
        return out, flips

    def quiet(self, t, flips):
        return not (any(0 <= t - e < self.SETTLE_MS for e in self.SCRIPT)
                    or any(0 <= t - e < self.SLEEP_SETTLE_MS for e in flips))

    # r4 (ALIVE.md 16): the eased output agrees within EASED_TOLERANCE at the common instants.
    EASED_TOLERANCE = 0.12

    @staticmethod
    def error(a, b):
        return max(max(abs(x - y) for x, y in zip(p, q)) for p, q in zip(a[0] + a[1], b[0] + b[1]))

    @staticmethod
    def eased_error(a, b):
        return max(max(abs(x - y) for x, y in zip(p, q)) for p, q in zip(a[2][0] + a[2][1], b[2][0] + b[2][1]))

    def test_rates_agree_at_common_instants(self):
        runs = {}
        for rate in (60, 120, 144, 240, 360):
            n = self.END * rate // 1000
            runs[rate] = self.run_at(sorted({math.floor(k * 1000 / rate + 0.5) for k in range(n + 1)}))
        common = set.intersection(*(set(out) for out, _ in runs.values()))
        ref, flips = runs[360]
        compared = [t for t in sorted(common) if self.quiet(t, flips)]
        self.assertGreater(len(compared), 50)
        worst = max(self.error(runs[rate][0][t], ref[t]) for t in compared for rate in (60, 120, 144, 240))
        self.assertLess(worst, 0.01, worst)
        eased = max(self.eased_error(runs[rate][0][t], ref[t]) for t in compared for rate in (60, 120, 144, 240))
        self.assertLess(eased, self.EASED_TOLERANCE, eased)

    def test_skipped_vblanks_resume_on_the_curve(self):
        base = sorted({math.floor(k * 1000 / 240 + 0.5) for k in range(self.END * 240 // 1000 + 1)})
        skipped = [t for k, t in enumerate(base) if k % 7 not in (3, 4, 5) or t % 250 == 0]   # drop 1-3 in a row
        (full, flips), (gaps, _) = self.run_at(base), self.run_at(skipped)
        compared = [t for t in skipped if self.quiet(t, flips)]
        self.assertGreater(len(compared), 700)
        worst = max(self.error(full[t], gaps[t]) for t in compared)
        self.assertLess(worst, 0.01, worst)
        eased = max(self.eased_error(full[t], gaps[t]) for t in compared)
        self.assertLess(eased, self.EASED_TOLERANCE, eased)

if __name__ == "__main__":
    unittest.main()
