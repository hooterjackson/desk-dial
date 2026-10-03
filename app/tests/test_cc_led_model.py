"""cc5 LED model (control_center.preview_lights) against knob-model.js and PRESENTATION_V4.md section 5.

Golden: tests/fixtures/knob_golden.json, produced by tests/js/knob_golden.cjs from
the design's knob-model.js with NanoModel.COLORS pre-populated from
tests/fixtures/dominant_reference.json, and mapped to v4 frames by
tests/tools/knob_adapter.py. The Python TARGET pattern (pulse phase fixed to the
model's tick parity) must equal the model for every case, except the deliberate
deviations of contract section 9, listed in DEVIATIONS with their own expected
values (never skipped wholesale).

Regenerate after a deliberate change (node is needed only for the golden):
    node tests\\js\\knob_golden.cjs design-reference\\design_handoff_nano_d_artwork_color\\knob-model.js tests\\fixtures\\dominant_reference.json tests\\fixtures\\knob_golden.json
    .venv\\Scripts\\python.exe tests\\tools\\make_cc5_frames.py
"""
from collections import Counter
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tests" / "tools"
for _path in (str(ROOT), str(TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from control_center import device, presentation as P  # noqa: E402
from control_center import preview_lights as pl  # noqa: E402
from control_center.preview_lights import (  # noqa: E402
    OFF, PreviewLights, blend, button_ink, button_light, button_pixels, button_targets,
    cell_drive, ease, pending_level, loading_level, ring_pixels, ring_target, scale,
)
import knob_adapter as ka  # noqa: E402
import led_hue_report  # noqa: E402
import make_cc5_frames  # noqa: E402
import make_light_sequences  # noqa: E402

GOLDEN = ka.load_golden()
ADAPTER = ka.Adapter(GOLDEN)
CASES = {case["id"]: case for case in GOLDEN["cases"]}
LEDS = ("white", "color")
W, G, R = P.LED_WHITE, P.LED_GREEN, P.LED_RED
AMBER, VRED = P.LED_AMBER, P.LED_VOLUME_RED
L0, L1, L2, L3, L4, LS = P.L0, P.L1, P.L2, P.L3, P.L4, P.LEVEL_SHOULDER
VOLC = {led: [ka.color_int(text) for text in GOLDEN["constants"]["volColors"][led]] for led in LEDS}
CAPS_V4 = {"presentation": 4, "glyphs": "latin-ext-a"}
U32 = 2 ** 32
HOLD_PROBE_MS = 12 * P.PULSE_MS   # 3120: an even (HIGH) phase, but past the 3 s hold

# --------------------------------------------------------------------------
# Contract section 9 deviations. Each entry names its source and is applied as
# an explicit patch of the model's own ring (or, for 4/5/8, checked with its
# own expected value below). Every one must be exercised by the golden.
DEVIATIONS = {
    "odd-shoulder": "9.1 / 5.2 step 4: odd v adds put(35+n-1, volc(n-1), LS=74)",
    "pending-decrease": "9.2 / 5.2 step 3: k = n+1..nc at L1 while a decrease is pending",
    "windows-pending-white": "9.3 / 5.3: the Windows pending pulse is white (model: app colour)",
    "pending-hold": "9.4 / 5.6: the pending pulse holds L1 after 3 s (model: pulses forever)",
    "window-rule": "9.5 / 4: more than 20 entries draw only the 20-entry window (model collides)",
    "disconnected": "9.8: disconnected hands control back to the native UI; the host sends no frame",
}


def _level_geometry(frame):
    ring = frame["ring"]
    v = ring["value"]
    c = frame.get("confirmedVolume", v)
    return v, (v + 1) // 2, (c + 1) // 2


def _flash_segments(frame, cursor):
    return {(cursor + d) % 60 for d in (-1, 0, 1)} if frame.get("feedback") else set()


def patch_pending_decrease(case, led, frame, cells):
    """Deviation 2: the span above the requested value down to the confirmed one, L1."""
    if frame["ring"]["style"] != "level" or frame["activity"] == "offline":
        return
    v, n, nc = _level_geometry(frame)
    flashed = _flash_segments(frame, (35 + n) % 60)
    for k in range(n + 1, nc + 1):
        if (35 + k) % 60 not in flashed:
            cells[(35 + k) % 60] = (VOLC[led][k], L1)


def patch_odd_shoulder(case, led, frame, cells):
    """Deviation 1: the odd-v shoulder (overwritten by a flash on cursor-1)."""
    if frame["ring"]["style"] != "level" or frame["activity"] == "offline":
        return
    v, n, _ = _level_geometry(frame)
    if v % 2 and n >= 1 and (35 + n - 1) % 60 not in _flash_segments(frame, (35 + n) % 60):
        cells[(35 + n - 1) % 60] = (VOLC[led][n - 1], LS)


def patch_windows_pending_white(case, led, frame, cells):
    """Deviation 3: keep the model's pulse level, draw it white."""
    if frame["layout"] != "windows" or frame["activity"] != "pending":
        return
    ring = frame["ring"]
    segment = ((ring["index"] - (ring["count"] - 1) // 2) * 3) % 60
    cells[segment] = (W, cells[segment][1])


PATCHES = (("pending-decrease", patch_pending_decrease), ("odd-shoulder", patch_odd_shoulder),
           ("windows-pending-white", patch_windows_pending_white))


def expected_cells(case, led, tick=0):
    """(frame, expected cells, deviations that changed the model ring) for one golden case."""
    frame = ADAPTER.case_frame(case, led)
    if frame is None:
        return None, None, {"disconnected"}
    used = set()
    model = case["views"][led]["ring"] if tick == 0 else case["tick1"][led]
    cells = ka.model_cells(model)
    if "windowed" in case:
        # Deviation 5: the model's own drawing of the 20-entry window (outside entries closed).
        windowed = ka.model_cells(case["windowed"][led])
        if windowed != cells:
            used.add("window-rule")
        cells = windowed
    for name, patch in PATCHES:
        before = list(cells)
        patch(case, led, frame, cells)
        if cells != before:
            used.add(name)
    return frame, cells, used


def target(frame, tick=0, pending_ms=None):
    phase = ka.Adapter.pulse_ms(tick) if pending_ms is None else pending_ms
    return ring_target(frame, phase, phase, ka.Adapter.flash_kind(frame))[0]


# ------------------------------------------------------------ frame builders
def _buttons(*spec):
    return [{"label": label, "enabled": enabled, "icon": icon} for label, enabled, icon in spec]


HOME_BUTTONS = _buttons(("Pause", True, "pause"), ("Browse", True, "list"), ("Win", True, "win"), ("Tracks", True, "tracks"))
LIST_BUTTONS = _buttons(("Back", True, "back"), ("Home", True, "home"), ("Win", True, "win"), ("Play", True, "play"))


def volume_frame(v, c=None, led="color", external=False, activity="idle", feedback=None):
    frame = {"id": 1, "mode": "VOLUME", "target": "Hall", "value": f"{v}%", "detail": "", "status": "",
             "activity": activity, "layout": "nowPlaying", "ledStyle": led,
             "confirmedVolume": v if c is None else c, "buttons": HOME_BUTTONS,
             "ring": {"style": "level", "value": v, "index": 0, "count": 101, "external": external}}
    if feedback:
        frame["feedback"] = feedback
    return frame


def accent(j):
    return 0xC00000 | (2 * j) << 8 | (0xFF - j)   # distinct for j <= 127, non-zero, never white


def list_frame(count, index, led="color", colors="auto", unavailable=0, more=-1, windows=False,
               activity="idle", first="auto", feedback=None):
    ring = {"style": "selection", "value": 0, "index": index, "count": count,
            "unavailable": unavailable, "moreIndex": more}
    start = P.window_first(index, count) if first == "auto" else first
    if first is not None:
        ring["first"] = start
    if colors == "auto":
        colors = [accent(j) for j in range(start, start + min(20, count - start))]
    if colors is not None:
        ring["colors"] = colors
    frame = {"id": 1, "mode": "WINDOWS" if windows else "RECENTLY ADDED", "target": "Hall", "value": "",
             "detail": "", "status": "", "activity": activity, "layout": "windows" if windows else "recent",
             "ledStyle": led, "buttons": LIST_BUTTONS, "ring": ring}
    if feedback:
        frame["feedback"] = feedback
    return frame


def transport_frame(index, no_prev=False, activity="idle", mask=None):
    return {"id": 1, "mode": "TRACKS", "target": "Hall", "value": "", "detail": "", "status": "",
            "activity": activity, "layout": "tracks", "ledStyle": "color", "buttons": LIST_BUTTONS,
            "ring": {"style": "transport", "value": 0, "index": index, "count": 3,
                     "unavailable": (1 if no_prev else 0) if mask is None else mask}}


def lit(cells):
    return {i: cell for i, cell in enumerate(cells) if cell[1]}


def slot(j, count):
    return ((j - (count - 1) // 2) * 3) % 60


# ======================================================================= golden
class GoldenTests(unittest.TestCase):
    def test_every_case_matches_the_model_except_listed_deviations(self):
        used, compared = Counter(), 0
        for case in GOLDEN["cases"]:
            for led in LEDS:
                for tick in ((0, 1) if "tick1" in case else (0,)):
                    frame, cells, deviations = expected_cells(case, led, tick)
                    used.update(deviations)
                    if frame is None:
                        continue
                    compared += 1
                    with self.subTest(case=case["id"], led=led, tick=tick):
                        self.assertEqual(target(frame, tick), cells)
        self.assertGreaterEqual(compared, 780)
        for name in DEVIATIONS:
            if name != "pending-hold":   # checked with its own probe below
                with self.subTest(deviation=name):
                    self.assertGreater(used[name], 0, f"deviation {name} is never exercised")

    def test_pending_hold_deviation(self):
        """Deviation 4: at 3120 ms the model (tick parity even) is HIGH; the contract holds L1."""
        probed = 0
        for case in GOLDEN["cases"]:
            if "tick1" not in case:
                continue
            for led in LEDS:
                frame = ADAPTER.case_frame(case, led)
                if frame is None or frame["activity"] != "pending":
                    continue
                probed += 1
                _, high, _ = expected_cells(case, led, 0)
                _, low, _ = expected_cells(case, led, 1)
                with self.subTest(case=case["id"], led=led):
                    self.assertNotEqual(high, low)                                   # the model pulses
                    self.assertEqual(target(frame, pending_ms=10 * P.PULSE_MS), high)  # 2600: still pulsing
                    self.assertEqual(target(frame, pending_ms=HOLD_PROBE_MS), low)    # expected: held at L1
        self.assertGreaterEqual(probed, 10)

    def test_deviation_expected_values(self):
        """Hand-written expected values, one or more per deviation."""
        def ours(case_id, led="color", **kw):
            return target(ADAPTER.case_frame(CASES[case_id], led), **kw)

        def model(case_id, led="color"):
            return ka.model_cells(CASES[case_id]["views"][led]["ring"])

        # 1. home-turn, v 55 (n 28): shoulder segment 35+27 = 62 -> 2 at LS; the model leaves L2.
        self.assertEqual(ours("home-turn")[2], (W, LS))
        self.assertEqual(model("home-turn")[2], (W, L2))
        # 1. home-pend, v 61 over confirmed 54: shoulder 35+30 -> 5 at LS over the L1 pending span.
        self.assertEqual((ours("home-pend")[5], model("home-pend")[5]), ((W, LS), (W, L1)))
        # 2. vol-0-down (v 0, confirmed 9 -> nc 5): 36..40 white L1; the model leaves them dark.
        self.assertEqual([ours("vol-0-down")[i] for i in range(36, 41)], [(W, L1)] * 5)
        self.assertEqual([model("vol-0-down")[i] for i in range(36, 41)], [OFF] * 5)
        # 2. vol-88-down (n 44, confirmed 97 -> nc 49): 20..24 are k 45..49, volume red at L1.
        self.assertEqual([ours("vol-88-down")[i] for i in range(20, 25)], [(VRED, L1)] * 5)
        # 3. pend-wi-claude (idx 1 of 9 -> segment 51): white L3 pulse; the model pulses Claude orange.
        self.assertEqual(ours("pend-wi-claude")[51], (W, L3))
        self.assertEqual(model("pend-wi-claude")[51], (0xFF8C66, L3))
        self.assertEqual(ours("pend-wi-chrome", tick=1)[54], (W, L1))
        # 4. pend-ra-p2 (cursor segment 0): L3 at 2600 ms, held L1 at 3120 ms and later.
        self.assertEqual(ours("pend-ra-p2", pending_ms=2600)[0], (W, L3))
        for ms in (3000, HOLD_PROBE_MS, 60000):
            self.assertEqual(ours("pend-ra-p2", pending_ms=ms)[0], (W, L1))
        # 5. wi-n45-i30: window first 21, exactly the slots of entries 21..40 (57, 0, 3, ..., 54).
        cells = ours("wi-n45-i30")
        self.assertEqual(CASES["wi-n45-i30"]["windowed"]["first"], 21)
        self.assertEqual(set(lit(cells)), {slot(j, 45) for j in range(21, 41)})
        self.assertEqual(len(lit(model("wi-n45-i30"))), 20)   # the model's 45 landmarks collide on 20 slots
        self.assertNotEqual(cells, model("wi-n45-i30"))
        # 8. Disconnected: no frame; the model draws segment 0 and dark buttons instead.
        for case_id in ("disc", "stress-disconnected", "disc-reconnecting"):
            self.assertIsNone(ADAPTER.case_frame(CASES[case_id], "color"))
        self.assertEqual(lit(model("disc")), {0: (W, L1)})
        self.assertEqual(lit(model("disc-reconnecting")), {0: (W, L2)})

    def test_buttons_match_the_model_tone_table(self):
        for case in GOLDEN["cases"]:
            for led in LEDS:
                frame = ADAPTER.case_frame(case, led)
                if frame is None:
                    self.assertTrue(all(b["l"] == 0 for b in case["views"][led]["buttons"]))
                    continue
                with self.subTest(case=case["id"], led=led):
                    ours = [button_light(frame, i) if button_light(frame, i)[1] else OFF for i in range(4)]
                    self.assertEqual(ours, ka.model_buttons(case["views"][led]["buttons"]))
                    self.assertEqual([P.button_tone(i, b["icon"], b["enabled"]) for i, b in enumerate(frame["buttons"])],
                                     [f["tone"] for f in case["views"]["white"]["foot"]])

    def test_colour_mode_lists_have_non_white_landmarks(self):
        found = {"recent": [], "windows": []}
        for case in GOLDEN["cases"]:
            frame = ADAPTER.case_frame(case, "color")
            if frame is None or frame["layout"] not in found or frame["ring"]["style"] != "selection":
                continue
            landmarks = [cell for cell in target(frame) if cell[1] == L1 and cell[0] != W]
            if landmarks:
                found[frame["layout"]].append(case["id"])
        self.assertIn("led-recent", found["recent"])
        self.assertIn("led-win-claude", found["windows"])
        self.assertIn("led-win-chrome", found["windows"])
        # The same cases are pure white in white mode.
        for case_id in ("led-recent", "led-win-claude"):
            self.assertTrue(all(c == W for c, l in target(ADAPTER.case_frame(CASES[case_id], "white")) if l))

    def test_injected_colours_are_the_reference(self):
        reference = json.loads(ka.REFERENCE.read_text(encoding="utf-8"))["colors"]
        tints = GOLDEN["constants"]["tints"]
        for key, value in reference.items():
            self.assertEqual(tints[key], value, key)
        self.assertEqual(tints["app:Discord"], "88,101,242")   # knob-model COLOR_FALLBACK
        self.assertTrue(any(v for k, v in tints.items() if k.startswith("al:")))
        self.assertTrue(any(v for k, v in tints.items() if k.startswith("app:")))

    def test_golden_frames_survive_the_host_adapter_unchanged_for_leds(self):
        for case in GOLDEN["cases"]:
            for led in LEDS:
                frame = ADAPTER.case_frame(case, led)
                if frame is None:
                    continue
                with self.subTest(case=case["id"], led=led):
                    wire = device._frame(frame, CAPS_V4)
                    self.assertEqual(device._frame(wire, CAPS_V4), wire)
                    for tick in (0, 1):
                        self.assertEqual(target(wire, tick), target(frame, tick))
                    self.assertEqual(button_targets(wire), button_targets(frame))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_golden_fixture_is_current(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "golden.json"
            done = subprocess.run([shutil.which("node"), str(ka.GOLDEN_JS), str(ka.MODEL_JS), str(ka.REFERENCE), str(out)],
                                  capture_output=True, text=True, encoding="utf-8", timeout=180)
            self.assertEqual(done.returncode, 0, done.stderr[-2000:])
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), GOLDEN)


# ================================================================== LED model
class VolumeTests(unittest.TestCase):
    def test_lit_counts_and_bottom_gap(self):
        for led in LEDS:
            for v, count in ((0, 2), (54, 29), (100, 51)):
                self.assertEqual(len(lit(ring_target(volume_frame(v, led=led))[0])), count, (led, v))
            for v in range(101):
                cells = ring_target(volume_frame(v, led=led))[0]
                self.assertEqual([cells[i] for i in range(26, 35)], [OFF] * 9, v)

    def test_every_percent_changes_the_ring(self):
        for led in LEDS:
            for confirmed in (None, 54):
                previous = None
                for v in range(101):
                    cells = ring_target(volume_frame(v, confirmed, led))[0]
                    drive = [cell_drive(c) for c in cells]
                    if previous is not None:
                        self.assertNotEqual(drive, previous, (led, confirmed, v))
                    previous = drive

    def test_odd_shoulder_geometry(self):
        for v in range(1, 101, 2):
            n = (v + 1) // 2
            cells, cursor = ring_target(volume_frame(v, led="white"))
            self.assertEqual(cursor, (35 + n) % 60)
            self.assertEqual(cells[(35 + n - 1) % 60], (W, LS), v)
            self.assertEqual(cells[cursor], (W, L3))

    def test_amber_and_red_thresholds(self):
        def expected(k):
            return VRED if k >= 45 else AMBER if k >= 40 else W
        for v in range(101):
            n = (v + 1) // 2
            cells, cursor = ring_target(volume_frame(v))
            self.assertEqual(cells[cursor][0], expected(n), v)
            for k in range(n + 1):
                self.assertEqual(cells[(35 + k) % 60][0], expected(k), (v, k))
        def endpoint(v):
            cells, cursor = ring_target(volume_frame(v))
            return cells[cursor][0]
        self.assertEqual([endpoint(v) for v in (78, 79, 88, 89)], [W, AMBER, AMBER, VRED])
        for v in range(79):
            self.assertNotIn(AMBER, {c for c, _ in lit(ring_target(volume_frame(v))[0]).values()}, v)
        for v in range(89):
            self.assertNotIn(VRED, {c for c, _ in lit(ring_target(volume_frame(v))[0]).values()}, v)
        # Segment 25 is both the end mark and k 50: red at 100 %.
        self.assertEqual(ring_target(volume_frame(100))[0][25], (VRED, L3))
        self.assertEqual(ring_target(volume_frame(99))[0][25], (VRED, L3))
        self.assertEqual(ring_target(volume_frame(97))[0][25], (W, L1))

    def test_confirmed_body_pending_spans_and_external(self):
        cells, cursor = ring_target(volume_frame(61, 54))          # increase pending
        self.assertEqual([cells[(35 + k) % 60][1] for k in range(28, 31)], [L1, L1, LS])
        self.assertEqual(cells[(35 + 27) % 60], (W, L2))
        cells, cursor = ring_target(volume_frame(40, 60))          # decrease pending
        self.assertEqual(cursor, 55)
        self.assertEqual([cells[(35 + k) % 60] for k in range(21, 31)], [(W, L1)] * 10)
        self.assertEqual(ring_target(volume_frame(54, external=True))[0][2], (W, L4))

    def test_home_offline_endpoint(self):
        cells, cursor = ring_target(volume_frame(61, 41, activity="offline"))
        self.assertEqual((lit(cells), cursor), ({56: (W, L1)}, 56))

    def test_white_mode_purity(self):
        for v in range(101):
            for confirmed in (v, max(0, v - 9), min(100, v + 9)):
                colours = {c for c, _ in lit(ring_target(volume_frame(v, confirmed, "white", v % 3 == 0))[0]).values()}
                self.assertEqual(colours, {W}, (v, confirmed))
        for n in (1, 9, 11, 21, 45):
            for frame in (list_frame(n, n - 1, "white", unavailable=1), list_frame(n, 0, "white", windows=True, unavailable=1),
                          list_frame(n, n // 2, "white", activity="pending", windows=True)):
                colours = {c for c, _ in lit(ring_target(frame, 0, 0)[0]).values()}
                self.assertEqual(colours, {W}, n)
        colours = {c for c, _ in lit(ring_target(transport_frame(2, activity="pending"))[0]).values()}
        self.assertEqual(colours, {W})


class ListTests(unittest.TestCase):
    def test_lists_have_no_collisions_in_the_drawn_window(self):
        for n in (1, 2, 9, 11, 16, 20, 21, 45, 80):
            for index in sorted({0, n // 2, n - 1}):
                first = P.window_first(index, n)
                width = min(20, n - first)
                slots = [slot(j, n) for j in range(first, first + width)]
                with self.subTest(n=n, index=index):
                    self.assertEqual(len(set(slots)), width)
                    cells, cursor = ring_target(list_frame(n, index))
                    self.assertEqual(set(lit(cells)), set(slots))
                    self.assertEqual(cursor, slot(index, n))
                    self.assertEqual(cells[cursor], (accent(index), L3))
                    for j in range(first, first + width):
                        if j != index:
                            self.assertEqual(cells[slot(j, n)], (accent(j), L1))

    def test_more_double_landmark_never_collides(self):
        for n in (2, 9, 11, 20):
            more = n - 1
            cells, _ = ring_target(list_frame(n, 0, more=more))
            landmarks = {slot(j, n) for j in range(n)}
            self.assertNotIn((slot(more, n) + 1) % 60, landmarks)
            self.assertEqual(cells[(slot(more, n) + 1) % 60], (W, L1))
            self.assertEqual(cells[slot(more, n)], (W, L1))      # More itself is white
            cells, cursor = ring_target(list_frame(n, more, more=more))
            self.assertEqual((cells[cursor], cells[(cursor + 1) % 60]), ((W, L3), (W, L3)))

    def test_unavailable_cursor_recent_white_windows_app_colour(self):
        cells, cursor = ring_target(list_frame(9, 3, unavailable=1 << 3))
        self.assertEqual(cells[cursor], (W, L2))
        cells, cursor = ring_target(list_frame(9, 3, unavailable=1 << 3, windows=True))
        self.assertEqual(cells[cursor], (accent(3), L2))
        # A gap where an unavailable entry would sit.
        cells, _ = ring_target(list_frame(9, 0, unavailable=1 << 5))
        self.assertEqual(cells[slot(5, 9)], OFF)

    def test_absent_and_invalid_first_follow_the_window_rule(self):
        relative = [accent(100 + k) for k in range(20)]
        # Absent first, derived 21: colours relative to 0 are ignored -> all white.
        cells, _ = ring_target(list_frame(45, 30, colors=relative, first=None, unavailable=1))
        self.assertEqual(set(lit(cells)), {slot(j, 45) for j in range(21, 41)})
        self.assertEqual({c for c, _ in lit(cells).values()}, {W})
        # Absent first, derived 0: colours kept.
        cells, _ = ring_target(list_frame(45, 5, colors=relative, first=None))
        self.assertEqual(cells[slot(0, 45)], (relative[0], L1))
        # Present and valid first 21: colours relative to 21.
        cells, _ = ring_target(list_frame(45, 30, colors=relative, first=21))
        self.assertEqual(cells[slot(21, 45)], (relative[0], L1))
        # Present but invalid first: replaced by the host window, relative data dropped.
        cells, _ = ring_target(list_frame(45, 30, colors=relative, first=0))
        self.assertEqual({c for c, _ in lit(cells).values()}, {W})
        self.assertEqual(len(lit(cells)), 20)

    def test_off_and_invalid_rings_are_dark(self):
        frame = list_frame(9, 3)
        frame["ring"] = {"style": "off", "value": 0, "index": 0, "count": 0}
        self.assertEqual(ring_target(frame), ([OFF] * 60, 0))
        self.assertEqual(ring_target(list_frame(3, 0) | {"ring": {"style": "selection", "value": 0, "index": 3, "count": 3}})[0], [OFF] * 60)


class TransportTests(unittest.TestCase):
    def test_transport_landmarks_and_selection(self):
        cells, cursor = ring_target(transport_frame(1))
        self.assertEqual((lit(cells), cursor), ({52: (W, L1), 53: (W, L1), 0: (W, L2), 7: (W, L1), 8: (W, L1)}, 0))
        cells, cursor = ring_target(transport_frame(0))
        self.assertEqual((cells[52], cells[53], cells[0], cursor), ((W, L3), (W, L3), (W, L1), 52))
        cells, cursor = ring_target(transport_frame(2))
        self.assertEqual((cells[7], cells[8], cursor), ((W, L3), (W, L3), 8))

    def test_no_previous(self):
        for index in (0, 1, 2):
            cells, cursor = ring_target(transport_frame(index, no_prev=True))
            self.assertEqual((cells[52], cells[53]), (OFF, OFF))
            self.assertEqual(cursor, (52, 0, 8)[index])
        cells, cursor = ring_target(transport_frame(0, no_prev=True), flash="err")
        self.assertEqual([cells[i] for i in (51, 52, 53)], [(R, L3)] * 3)
        # bit2 (no Next): the Next landmarks are still drawn.
        self.assertEqual(ring_target(transport_frame(1, mask=4))[0][7], (W, L1))

    def test_transport_pending_pulses_the_selected_pair(self):
        for index, pair in ((0, (52, 53)), (2, (7, 8)), (1, (0,))):
            for ms, level in ((0, L3), (260, L1), (520, L3), (HOLD_PROBE_MS, L1)):
                cells, _ = ring_target(transport_frame(index, activity="pending"), ms)
                self.assertEqual([cells[i] for i in pair], [(W, level)] * len(pair), (index, ms))


class PulseTests(unittest.TestCase):
    def test_pending_phase_table_and_hold(self):
        table = {0: L3, 259: L3, 260: L1, 519: L1, 520: L3, 2859: L3, 2860: L1, 2999: L1,
                 3000: L1, 3119: L1, 3120: L1, 3380: L1, 10 ** 6: L1}
        self.assertEqual({ms: pending_level(ms) for ms in table}, table)

    def test_loading_phase_table_without_hold(self):
        table = {0: L2, 259: L2, 260: L1, 520: L2, 2860: L1, 3120: L2, 5200: L2, 5460: L1}
        self.assertEqual({ms: loading_level(ms) for ms in table}, table)

    def test_loading_draws_only_segment_zero(self):
        for ms, level in ((0, L2), (260, L1), (3120, L2)):
            cells, cursor = ring_target(list_frame(11, 10, more=10, activity="loading"), 0, ms)
            self.assertEqual((lit(cells), cursor), ({0: (W, level)}, 0))

    def test_pending_onset_hold_and_reset(self):
        lights, t0 = PreviewLights(), 1000
        pending = list_frame(9, 3, activity="pending")
        cursor = slot(3, 9)
        outputs = {}
        for t in range(t0, t0 + 4001, 10):
            outputs[t - t0] = lights.render(pending, 1, t)[0][cursor]
        self.assertEqual(outputs[0], scale(W, L3))            # starts HIGH at onset
        self.assertEqual(outputs[520], scale(W, L3))          # every rise is instant
        self.assertEqual(outputs[2600], scale(W, L3))         # last HIGH phase
        self.assertTrue(all(outputs[ms] == scale(W, L1) for ms in range(3120, 4001, 10)))
        peaks = [pl.peak(outputs[ms]) for ms in range(2860, 4001, 10)]
        self.assertEqual(peaks, sorted(peaks, reverse=True))   # no rise after the last HIGH phase
        # Condition ends, then starts again: HIGH at the new onset (anchored at t0 it would be phase 19, L1).
        lights.render(list_frame(9, 3), 1, t0 + 5000)
        self.assertEqual(lights.render(pending, 1, t0 + 5130)[0][cursor], scale(W, L3))
        lights.render(pending, 1, t0 + 5130 + 260)                # phase 1 starts: decay begins
        self.assertNotEqual(lights.render(pending, 1, t0 + 5130 + 270)[0][cursor], scale(W, L3))

    def test_loading_onset_resets(self):
        lights = PreviewLights()
        loading = list_frame(11, 0, more=10, activity="loading")
        lights.render(loading, 1, 0)
        lights.render(loading, 1, 260)                                        # L1 phase: decay begins
        self.assertNotEqual(lights.render(loading, 1, 300)[0][0], scale(W, L2))
        lights.render(list_frame(11, 0, more=10), 1, 400)
        self.assertEqual(lights.render(loading, 1, 430)[0][0], scale(W, L2))      # new onset (old anchor: L1 phase)


class FlashTests(unittest.TestCase):
    def test_flash_across_control_id_change_and_seeding(self):
        lights = PreviewLights()
        first = list_frame(9, 1, feedback={"kind": "ok", "seq": 5})
        lights.render(first, 1, 0)
        self.assertIsNone(lights.flash)                         # seeded by the first frame
        self.assertEqual(lights.last_seq, 5)
        lights.render(volume_frame(54, feedback={"kind": "ok", "seq": 5}), 2, 10)
        self.assertIsNone(lights.flash)                         # same seq on another control
        lights.render(volume_frame(54), 2, 20)                  # no feedback: lastSeq unchanged
        self.assertEqual(lights.last_seq, 5)
        ring, _ = lights.render(volume_frame(54, feedback={"kind": "ok", "seq": 6}), 3, 30)
        self.assertEqual(lights.flash, "ok")                    # new seq on a new control id
        self.assertEqual([ring[i] for i in (1, 2, 3)], [scale(G, L4)] * 3)
        ring, _ = lights.render(volume_frame(54, feedback={"kind": "ok", "seq": 6}), 3, 30 + 649)
        self.assertEqual(ring[2], scale(G, L4))
        ring, _ = lights.render(volume_frame(54, feedback={"kind": "ok", "seq": 6}), 3, 30 + 650)
        self.assertIsNone(lights.flash)
        ring, _ = lights.render(volume_frame(54), 3, 30 + 650 + 260)
        self.assertEqual(ring[2], scale(W, L3))                 # decayed to the endpoint

    def test_no_flash_after_construction_or_reset_seeding(self):
        lights = PreviewLights()
        ring, _ = lights.render(list_frame(9, 4, feedback={"kind": "err", "seq": 9}), 1, 0)
        self.assertIsNone(lights.flash)
        self.assertNotIn(scale(R, L3), ring)
        lights.reset()
        lights.render(list_frame(9, 4, feedback={"kind": "err", "seq": 10}), 1, 100)
        self.assertIsNone(lights.flash)
        lights.render(list_frame(9, 4, feedback={"kind": "err", "seq": 10}), 1, 200)
        self.assertIsNone(lights.flash)
        ring, _ = lights.render(list_frame(9, 4, feedback={"kind": "err", "seq": 11}), 1, 300)
        self.assertEqual([ring[i] for i in (59, 0, 1)], [scale(R, L3)] * 3)
        ring, _ = lights.render(list_frame(9, 4), 1, 300 + 899)
        self.assertEqual(ring[0], scale(R, L3))
        lights.render(list_frame(9, 4), 1, 300 + 900)
        self.assertIsNone(lights.flash)
        # A first frame without feedback seeds "none": the next feedback flashes.
        fresh = PreviewLights()
        fresh.render(list_frame(9, 4), 1, 0)
        fresh.render(list_frame(9, 4, feedback={"kind": "ok", "seq": 1}), 1, 10)
        self.assertEqual(fresh.flash, "ok")

    def test_flash_cases_render_through_the_state_machine(self):
        for case in GOLDEN["cases"]:
            frame = ADAPTER.case_frame(case, "color")
            if not frame or "feedback" not in frame:
                continue
            lights = PreviewLights()
            quiet = {k: v for k, v in frame.items() if k != "feedback"}
            lights.render(quiet, 1, 0)
            lights.render(frame, 1, 100)
            ring, _ = lights.render(frame, 1, 100 + 260)
            with self.subTest(case=case["id"]):
                self.assertEqual(ring, [cell_drive(c) for c in target(frame)])


class DampingTests(unittest.TestCase):
    def test_instant_rise_and_monotone_decay_to_the_exact_target(self):
        lights = PreviewLights()
        before, after = list_frame(9, 4), list_frame(9, 5)     # cursor moves from segment 0 to 3
        lights.render(before, 1, 0)
        start, previous = 100, None
        for t in range(start, start + 301):
            ring, _ = lights.render(after, 1, t)
            self.assertEqual(ring[3], scale(accent(5), L3))    # rise: instant
            channels = [(ring[0] >> s) & 255 for s in (16, 8, 0)]
            if previous is not None:
                self.assertTrue(all(a <= b for a, b in zip(channels, previous)), t)
            if t == start:
                self.assertEqual(ring[0], scale(accent(4), L3))
            if t - start >= P.DECAY_MS:
                self.assertEqual(ring[0], scale(accent(4), L1))
            previous = channels
        # A single render at exactly 260 ms also lands on the target.
        lights = PreviewLights()
        lights.render(before, 1, 0)
        lights.render(after, 1, 50)
        self.assertEqual(lights.render(after, 1, 50 + 260)[0][0], scale(accent(4), L1))

    def test_ease_lut_interpolation(self):
        self.assertEqual([ease(t, 260) for t in (0, 260, 1000)], [0, 255, 255])
        self.assertEqual(ease(16, 260), 65)                     # x = 256: LUT[0] + 67 * 256 / 260
        values = [ease(t, 260) for t in range(0, 261)]
        self.assertEqual(values, sorted(values))
        self.assertEqual(ease(65, 260), P.EASE_LUT[4])          # 65 ms = 4/16 exactly
        self.assertEqual(pl.toward(0xFFFFFF, 0x000000, 255), 0)
        self.assertEqual(pl.toward(0x102030, 0x0A0B0C, 128), 0x0D161E)   # C truncation (floor gives 0x0C151D)

    def test_snap_on_reset(self):
        lights = PreviewLights()
        lights.render(list_frame(9, 4), 1, 0)
        ring, _ = lights.render(list_frame(9, 5), 1, 10)
        self.assertEqual(ring[0], scale(accent(4), L3))        # decay just started
        lights.reset()
        ring, buttons = lights.render(list_frame(9, 5), 1, 20)
        self.assertEqual(ring, [cell_drive(c) for c in ring_target(list_frame(9, 5))[0]])
        self.assertEqual(buttons, button_targets(list_frame(9, 5)))

    def test_millis_wrap(self):
        base = U32 - 100
        lights = PreviewLights()
        pending = list_frame(9, 3, activity="pending")
        cursor = slot(3, 9)
        at = lambda ms: lights.render(pending, 1, (base + ms) % U32)[0][cursor]
        self.assertEqual(at(0), scale(W, L3))
        self.assertEqual(at(259), scale(W, L3))                # crosses the wrap at +100
        for ms in range(260, 520, 10):
            at(ms)
        self.assertEqual(at(520), scale(W, L3))                # phase 2, across the wrap
        for ms in range(530, 3200, 10):
            at(ms)
        self.assertEqual(at(3200), scale(W, L1))               # held
        # Decay and flash timing across the wrap (unmasked times behave the same).
        lights = PreviewLights()
        lights.render(list_frame(9, 4), 1, base)
        lights.render(list_frame(9, 5, feedback={"kind": "ok", "seq": 3}), 1, base + 50)
        self.assertEqual(lights.flash, "ok")
        lights.render(list_frame(9, 5, feedback={"kind": "ok", "seq": 3}), 1, base + 50 + 649)
        self.assertEqual(lights.flash, "ok")
        ring, _ = lights.render(list_frame(9, 5), 1, base + 50 + 650)
        self.assertIsNone(lights.flash)
        ring, _ = lights.render(list_frame(9, 5), 1, base + 50 + 650 + 260)
        self.assertEqual(ring, [cell_drive(c) for c in ring_target(list_frame(9, 5))[0]])


class ButtonTests(unittest.TestCase):
    def test_tone_table(self):
        cases = {
            (0, "", True): (0, L0), (3, "", True): (0, L0),
            (0, "cancel", True): (R, L2), (0, "cancel", False): (W, L1),
            (3, "play", True): (G, L3), (3, "prev", True): (G, L3), (3, "next", True): (G, L3),
            (3, "switch", True): (G, L3), (3, "play", False): (W, L1),
            (3, "more", True): (W, L2), (3, "tracks", True): (W, L2), (0, "play", True): (W, L2),
            (1, "cancel", True): (W, L2), (0, "back", True): (W, L2), (2, "win", True): (W, L2),
        }
        for (index, icon, enabled), light in cases.items():
            buttons = [{"label": "", "enabled": True, "icon": ""} for _ in range(4)]
            buttons[index] = {"label": "x", "enabled": enabled, "icon": icon}
            frame = {"buttons": buttons}
            with self.subTest(index=index, icon=icon, enabled=enabled):
                self.assertEqual(button_light(frame, index), light)
                self.assertEqual(button_ink(frame, index), light[0])
                self.assertEqual(button_targets(frame)[index], scale(*light))

    def test_press_highlight(self):
        frame = {"buttons": _buttons(("Cancel", True, "cancel"), ("Home", False, "home"), ("", True, ""), ("Play", True, "play"))}
        drive = button_targets(frame)
        pressed = button_pixels(frame, pressed=0b1111)
        self.assertEqual(pressed[0], blend(drive[0], W, 36))
        self.assertEqual(pressed[3], blend(drive[3], W, 36))
        self.assertEqual(pressed[1:3], drive[1:3])              # disabled and empty: no highlight
        self.assertEqual(button_pixels(frame), drive)

    def test_button_fade_220ms(self):
        go = {"buttons": _buttons(("Back", True, "back"), ("Home", True, "home"), ("Win", True, "win"), ("Play", True, "play"))}
        dim = {"buttons": _buttons(("Back", True, "back"), ("Home", True, "home"), ("Win", True, "win"), ("Play", False, "play"))}
        for a, b in ((go, dim), (dim, go)):
            lights = PreviewLights()
            ring_frame = list_frame(9, 4)
            _, buttons = lights.render({**ring_frame, **a}, 1, 0)
            self.assertEqual(buttons[3], button_targets(a)[3])
            previous = None
            for t in range(10, 10 + 231):
                _, buttons = lights.render({**ring_frame, **b}, 1, t)
                if t == 10:
                    self.assertEqual(buttons[3], button_targets(a)[3])
                if t == 60:
                    self.assertNotIn(buttons[3], (button_targets(a)[3], button_targets(b)[3]))
                if t - 10 >= P.BUTTON_FADE_MS:
                    self.assertEqual(buttons[3], button_targets(b)[3])
                previous = buttons[3]
            self.assertEqual(previous, button_targets(b)[3])
        # The press highlight is applied to the shown (faded) colour while held.
        lights = PreviewLights()
        _, buttons = lights.render({**list_frame(9, 4), **go}, 1, 0, pressed=0b1000)
        self.assertEqual(buttons[3], blend(button_targets(go)[3], W, 36))


class ContractPinTests(unittest.TestCase):
    """Independent literal pins of PRESENTATION_V4.md section 5 (never derived from the code under test)."""

    def test_levels_shoulder_and_lut(self):
        self.assertEqual(P.LEVELS, (0, 15, 46, 102, 204))
        self.assertEqual((P.L0, P.L1, P.L2, P.L3, P.L4), (0, 15, 46, 102, 204))
        self.assertEqual(P.LEVEL_SHOULDER, 74)
        self.assertEqual(P.EASE_LUT, (0, 67, 123, 165, 195, 216, 230, 239, 245, 249, 252, 253, 254, 255, 255, 255, 255))
        self.assertEqual(pl.LEVELS, (0, 15, 46, 102, 204))

    def test_palette(self):
        self.assertEqual((P.LED_WHITE, P.LED_GREEN, P.LED_RED, P.LED_AMBER, P.LED_VOLUME_RED),
                         (0xFFFFFF, 0x46E178, 0xFF4834, 0xFF961E, 0xFF3723))
        self.assertEqual((pl.WHITE, pl.GREEN, pl.RED, pl.AMBER, pl.VOLUME_RED),
                         (0xFFFFFF, 0x46E178, 0xFF4834, 0xFF961E, 0xFF3723))
        self.assertEqual(pl.TONE_LIGHT, {"none": (0, 0), "dim": (0xFFFFFF, 15), "stop": (0xFF4834, 46),
                                         "go": (0x46E178, 102), "nav": (0xFFFFFF, 46)})

    def test_timings_and_cap(self):
        self.assertEqual((P.PULSE_MS, P.PENDING_HOLD_MS, P.DECAY_MS, P.BUTTON_FADE_MS, P.FLASH_OK_MS, P.FLASH_ERR_MS),
                         (260, 3000, 260, 220, 650, 900))
        self.assertEqual((pl.PRESS_BLEND, pl.FASTLED_CAP), (36, 51))


class FlashDurationTests(unittest.TestCase):
    def test_ok_lasts_650_and_err_900_ms(self):
        """The cursor is the external endpoint (W L4, peak 204): when a flash ends it rises back
        instantly, so the ring itself shows exactly when each flash stops."""
        cursor, endpoint = 2, scale(W, L4)                  # v 54: vseg = 35 + 27 = 62 -> 2
        expected = {"ok": [scale(G, L4), endpoint, endpoint, endpoint],
                    "err": [scale(R, L3), scale(R, L3), scale(R, L3), endpoint]}
        for kind, cells in expected.items():
            lights, start = PreviewLights(), 1000
            quiet = volume_frame(54, external=True)
            self.assertEqual(lights.render(quiet, 1, 0)[0][cursor], endpoint)   # seeds, no flash
            flashing = volume_frame(54, external=True, feedback={"kind": kind, "seq": 2})
            ring, _ = lights.render(flashing, 1, start)
            # cursor+-1 (body L2) rise to the flash at once; the brighter cursor decays into it.
            self.assertEqual([ring[i] for i in (1, 2, 3)], [cells[0], endpoint, cells[0]], kind)
            seen = [lights.render(flashing, 1, start + ms)[0][cursor] for ms in (649, 650, 899, 900)]
            with self.subTest(kind=kind):
                self.assertEqual(seen, cells)
                self.assertIsNone(lights.flash)

    def test_err_is_still_on_where_ok_has_ended(self):
        for kind, active in (("ok", False), ("err", True)):
            lights = PreviewLights()
            lights.render(list_frame(9, 4), 1, 0)
            lights.render(list_frame(9, 4, feedback={"kind": kind, "seq": 7}), 1, 100)
            ring, _ = lights.render(list_frame(9, 4), 1, 100 + 700)
            self.assertEqual(lights.flash is not None, active, kind)
            self.assertEqual(ring[0] == scale(R, L3), active, kind)


class DurationProbeTests(unittest.TestCase):
    """Intermediate values pin the 260 ms decay and the 220 ms fade (end states alone cannot:
    the LUT reaches 255 at 13/16 of either duration)."""

    def test_ring_decay_uses_260_ms(self):
        # List cursor 0 (W L3 via a zero accent) moves away: segment 0 decays W L3 -> accent L1.
        before, after = list_frame(9, 4, colors=[0] * 9), list_frame(9, 5, colors=[0] * 9)
        probes = {65: 0x242424, 130: 0x131313}               # LUT[4] = 195, LUT[8] = 245 over 260 ms
        for ms, value in probes.items():
            lights = PreviewLights()
            lights.render(before, 1, 0)
            lights.render(after, 1, 10)
            ring, _ = lights.render(after, 1, 10 + ms)
            with self.subTest(ms=ms):
                self.assertEqual(ring[0], value)
                self.assertEqual(ring[0], pl.toward(0x666666, 0x0F0F0F, P.EASE_LUT[ms * 16 // 260]))
                self.assertNotEqual(ring[0], pl.toward(0x666666, 0x0F0F0F, ease(ms, 220)))   # not the fade curve

    def test_button_fade_uses_220_ms(self):
        go = {"buttons": _buttons(("Back", True, "back"), ("Home", True, "home"), ("Win", True, "win"), ("Play", True, "play"))}
        dim = {"buttons": _buttons(("Back", True, "back"), ("Home", True, "home"), ("Win", True, "win"), ("Play", False, "play"))}
        self.assertEqual((button_targets(go)[3], button_targets(dim)[3]), (0x1C5A30, 0x0F0F0F))
        probes = {55: 0x132117, 110: 0x101211}               # LUT[4] = 195, LUT[8] = 245 over 220 ms
        for ms, value in probes.items():
            lights = PreviewLights()
            lights.render({**list_frame(9, 4), **go}, 1, 0)
            lights.render({**list_frame(9, 4), **dim}, 1, 10)
            _, buttons = lights.render({**list_frame(9, 4), **dim}, 1, 10 + ms)
            with self.subTest(ms=ms):
                self.assertEqual(buttons[3], value)
                self.assertNotEqual(buttons[3], pl.toward(0x1C5A30, 0x0F0F0F, ease(ms, 260)))   # not the decay curve

    def test_equal_peak_hue_change_snaps(self):
        """Instant rise at EQUAL peak: body k 40, 41 go W L2 (0x2E2E2E) <-> AMBER L2 (0x2E1B05) at once."""
        lights = PreviewLights()
        segments = ((35 + 40) % 60, (35 + 41) % 60)
        ring, _ = lights.render(volume_frame(84, led="white"), 1, 0)
        self.assertEqual([ring[i] for i in segments], [0x2E2E2E] * 2)
        ring, _ = lights.render(volume_frame(84, led="color"), 1, 1)
        self.assertEqual(scale(AMBER, L2), 0x2E1B05)
        self.assertEqual([ring[i] for i in segments], [0x2E1B05] * 2)
        ring, _ = lights.render(volume_frame(84, led="white"), 1, 2)
        self.assertEqual([ring[i] for i in segments], [0x2E2E2E] * 2)
        # A LOWER target decays instead: k 41 becomes the pending-decrease span (W L1) and
        # still shows W L2 when its 260 ms decay starts.
        ring, _ = lights.render(volume_frame(80, 84, led="white"), 1, 3)
        self.assertEqual(ring[(35 + 41) % 60], 0x2E2E2E)
        ring, _ = lights.render(volume_frame(80, 84, led="white"), 1, 3 + P.DECAY_MS)
        self.assertEqual(ring[(35 + 41) % 60], 0x0F0F0F)


class ReviewFixTests(unittest.TestCase):
    def test_button_fade_never_replays_after_a_millis_wrap(self):
        go = {"buttons": _buttons(("Back", True, "back"), ("Home", True, "home"), ("Win", True, "win"), ("Play", True, "play"))}
        dim = {"buttons": _buttons(("Back", True, "back"), ("Home", True, "home"), ("Win", True, "win"), ("Play", False, "play"))}
        lights, start = PreviewLights(), U32 - 90
        lights.render({**list_frame(9, 4), **go}, 1, start - 10)
        lights.render({**list_frame(9, 4), **dim}, 1, start)                 # fade starts
        _, mid = lights.render({**list_frame(9, 4), **dim}, 1, start + 50)
        _, done = lights.render({**list_frame(9, 4), **dim}, 1, start + 300)
        self.assertNotEqual(mid[3], done[3])
        self.assertEqual(done[3], 0x0F0F0F)
        # 2**32 ms later "now" is start + 50 again: the finished fade must not replay.
        _, later = lights.render({**list_frame(9, 4), **dim}, 1, start + 50 + U32)
        self.assertEqual(later[3], 0x0F0F0F)
        self.assertEqual(lights._button_fading, [False] * 4)

    def test_unknown_icons_are_normalised_like_the_host(self):
        raw = list_frame(9, 4)
        raw["buttons"] = [{"label": "A", "enabled": True, "icon": "bogus"}, {"label": "B", "enabled": True, "icon": 5},
                          {"label": "C", "enabled": True, "icon": "PLAY"}, {"label": "D", "enabled": True, "icon": "play"}]
        sent = device._frame(raw, CAPS_V4)
        self.assertEqual([b["icon"] for b in sent["buttons"]], ["", "", "", "play"])
        self.assertEqual([button_light(raw, i) for i in range(4)], [OFF, OFF, OFF, (G, L3)])
        self.assertEqual([button_light(raw, i) for i in range(4)], [button_light(sent, i) for i in range(4)])
        self.assertEqual(button_pixels(raw, 0b1111), button_pixels(sent, 0b1111))   # no press highlight on none
        self.assertEqual(PreviewLights().render(raw, 1, 0, 0b1111)[1], PreviewLights().render(sent, 1, 0, 0b1111)[1])
        # Absent icon (legacy frame): the host sends "" for v4, so the preview shows none too.
        self.assertEqual(button_light({"buttons": [{"label": "Play", "enabled": True}]}, 0), OFF)


class LightSequenceFixtureTests(unittest.TestCase):
    """The firmware parity fixture (harness/light_pixels.json, via light_tests.py)."""

    @classmethod
    def setUpClass(cls):
        cls.data = make_light_sequences.build()

    def test_sequences_cover_the_stage5_list(self):
        cases = self.data["cases"]
        required = ["volume-white-sweep", "volume-color-fast-turns", "volume-pending-up-down",
                    "volume-thresholds-styles", "volume-external", "volume-home-offline",
                    "recent-loading-page1", "pending-onset-hold", "transport", "flash-seq-and-control-id",
                    "flash-reset-seeding", "decay-tails", "millis-wrap", "buttons-tones-fade-press",
                    "golden-scenarios", "golden-fast", "list-first-absent-present", "list-more-and-unavailable",
                    "list-windows-detection"]
        required += [f"recent-n{n}" for n in (1, 2, 9, 11, 16, 20, 21, 45, 80)]
        for name in required:
            self.assertIn(name, cases)
            self.assertTrue(cases[name]["steps"], name)
        steps = [s for case in cases.values() for s in case["steps"]]
        self.assertGreater(len(steps), 4000)
        self.assertTrue(any(s["flash"] == 1 for s in steps) and any(s["flash"] == 2 for s in steps))
        self.assertTrue(any(s["reset"] for s in steps))
        self.assertTrue(any(s["now_ms"] > U32 - 1000 for s in steps) and any(s["now_ms"] < 1000 for s in steps))
        self.assertTrue(any(s["pending_ms"] >= P.PENDING_HOLD_MS for s in steps))
        self.assertTrue(any(s["loading_ms"] > 0 for s in steps))
        self.assertTrue(any(s["pressed"] for s in steps))

    def test_replay_is_deterministic_and_matches_the_stateless_model_on_snaps(self):
        again = make_light_sequences.build()
        self.assertEqual(make_light_sequences.dumps(again), make_light_sequences.dumps(self.data))
        frames = self.data["frames"]
        for name, case in self.data["cases"].items():
            first = case["steps"][0]
            cells = ring_target(frames[first["f"]], first["pending_ms"], first["loading_ms"],
                                {0: None, 1: "ok", 2: "err"}[first["flash"]])[0]
            with self.subTest(case=name):
                self.assertEqual(first["ring"], [cell_drive(c) for c in cells])   # first render snaps


class CompatibilityTests(unittest.TestCase):
    def test_legacy_importers_keep_working(self):
        self.assertEqual((pl.WARM, pl.RED, pl.GREEN, pl.COOL), (W, R, G, W))
        self.assertEqual(scale(0xFFFFFF, 10), 0x0A0A0A)
        frame = volume_frame(54, led="white", activity="pending")
        self.assertEqual(ring_pixels(frame, 880), [cell_drive(c) for c in ring_target(frame, 880, 880)[0]])
        self.assertEqual(len(button_pixels(frame)), 4)
        ring, buttons = PreviewLights().render(frame, 7, 123456)
        self.assertEqual((len(ring), len(buttons)), (60, 4))


# ================================================================ diagnostics
class HueReportTests(unittest.TestCase):
    def test_post_cap_hue_report_is_written(self):
        """Informational: which L1 accents collapse or lose hue after the FastLED cap (never fails on content)."""
        report = led_hue_report.build(GOLDEN)
        path = led_hue_report.write(report)
        self.assertTrue(path.is_file())
        self.assertGreater(report["summary"]["accents"], 5)
        self.assertTrue(report["rows"][0].keys() >= {"name", "accent", "L1", "L2", "L3"})
        print(f"\n[cc5 LED hue report] {path.name}: L1 loses hue: "
              f"{', '.join(report['summary']['L1_loses_hue']) or 'none'}; "
              f"L1 collapses to <=1: {', '.join(report['summary']['L1_collapse_le1']) or 'none'}")


# ================================================================ cc5 frames
class Cc5FramesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(make_cc5_frames.OUTPUT.read_text(encoding="utf-8"))

    def test_fixture_is_current(self):
        self.assertEqual(make_cc5_frames.dumps(make_cc5_frames.build(GOLDEN)),
                         make_cc5_frames.OUTPUT.read_text(encoding="utf-8"))

    def test_every_scenario_and_stress_state_is_present_and_valid(self):
        ids = {case["id"] for case in self.data["cases"]}
        for case in GOLDEN["cases"]:
            if case["group"] in ("scenario", "stress", "ledRows"):
                self.assertIn(case["id"], ids)
        arts = Counter()
        for case in self.data["cases"]:
            frame = case["frame"]
            with self.subTest(case=case["id"]):
                arts[case["art"]] += 1
                if frame is None:
                    self.assertIn("Deviation 8", case["note"])
                    continue
                self.assertEqual(device._frame(frame, CAPS_V4), frame)
                self.assertEqual(frame["ledStyle"], "color")
                self.assertEqual(case["art"] or "", frame.get("artKey", ""))
                if frame["layout"] in ("windows", "notice"):
                    self.assertIsNone(case["art"])
                self.assertEqual(case["leds"]["ring"], [cell_drive(c) for c in target(frame)])
        self.assertEqual(arts[ka.ART_BRIGHT], 1)
        self.assertGreater(arts[ka.ART_HALL], 10)
        self.assertGreater(arts[None], 5)

    def test_field_map_details(self):
        cases = {case["id"]: case for case in self.data["cases"]}
        noprev = cases["tr-noprev"]["frame"]
        self.assertEqual((noprev["title"], noprev["titleTone"], noprev["meta"]),
                         ("Previous track", "muted", "Previous unavailable"))
        self.assertTrue(cases["ra-na"]["frame"]["artDim"])
        self.assertNotIn("artDim", cases["tr-noprev"]["frame"])
        self.assertEqual(cases["home"]["frame"]["value"], "54%")
        self.assertEqual(cases["home-off"]["frame"]["layout"], "notice")
        self.assertEqual(cases["home-pidle"]["frame"]["layout"], "idle")
        self.assertEqual((cases["home-turn"]["frame"]["layout"], cases["home-turn"]["frame"]["restLayout"]),
                         ("volume", "nowPlaying"))
        self.assertEqual(cases["ra-more-p2"]["frame"]["page"], 1)
        self.assertEqual(cases["ra-more-p2"]["frame"]["heading"], "RECENTLY ADDED · P2")
        self.assertEqual(cases["ra-load-p2"]["frame"]["page"], 1)
        self.assertEqual(cases["wi-closed"]["tile"], {"letter": "T", "opacity": 0.35})
        self.assertEqual(cases["wi-closed"]["frame"]["ring"]["unavailable"], 1 << 4)
        self.assertEqual(cases["flash-ok-tracks"]["frame"]["feedback"], {"kind": "ok", "seq": 1})

    def test_sequences_carry_animation_expectations(self):
        sequences = {q["id"]: q for q in self.data["sequences"]}
        slides = [s["expect"]["slide"] for s in sequences["screen-deeper-back"]["steps"] if s["expect"]["slide"]]
        self.assertEqual(slides, [20, 20, -20, -20, 20, -20])
        heartbeat = sequences["heartbeat-identical"]["steps"]
        self.assertTrue(heartbeat[-1]["expect"]["identical"])
        reveal = sequences["volume-reveal-hide"]["steps"]
        self.assertTrue(any(s["expect"].get("volumeReveal") for s in reveal))
        self.assertTrue(any(s["expect"].get("volumeHide") for s in reveal))
        idle = sequences["idle-entry-exit"]["steps"]
        self.assertTrue(any(s["expect"].get("idleEnter") for s in idle))
        self.assertTrue(any(s["expect"].get("idleExit") for s in idle))
        external = sequences["external-volume"]["steps"]
        self.assertTrue(any(s["frame"]["ring"].get("external") for s in external))
        tracks = sequences["tracks-skip-recentre"]["steps"]
        self.assertEqual([s["expect"]["slide"] for s in tracks[2:]], [0] * (len(tracks) - 2))
        self.assertTrue(any(s["expect"].get("flash") == "ok" for s in tracks))


if __name__ == "__main__":
    unittest.main()
