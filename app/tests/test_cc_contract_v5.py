"""Presentation contract v5 (firmware/PRESENTATION_V5.md) against tests/fixtures/frames_v5.json.

Every `expect.output` is checked against an independent reading of the contract (tokens, the
window rule, scope strips, slimming, the byte budget and, for presentation-4 knobs, the section 2.2
downgrade), the host (device._frame) must reproduce each output exactly, and device.v5_parse must
give each `v5` verdict. The firmware half of the parity (the cc5.4 parser, and the cc5.3 parser for
the downgrade) is harness/parse_tests.py. The shared vectors (mmss, accent_ink, the 5.2
tone table) are checked against a second reading of sections 4.3, 5.2 and 5.3.
"""
from copy import deepcopy
import json
import logging
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import device, presentation as P  # noqa: E402

FIXTURES = json.loads((Path(__file__).resolve().parent / "fixtures" / "frames_v5.json").read_text(encoding="utf-8"))
CASES = FIXTURES["cases"]
BY_NAME = {case["name"]: case for case in CASES}

# The contract's tables, written out again here (not imported), so a changed constant fails.
LAYOUTS_V4 = {"nowPlaying", "volume", "idle", "recent", "tracks", "windows", "notice"}
LAYOUTS_V5 = LAYOUTS_V4 | {"seek", "explorer", "upnext"}
STYLES_V4 = {"off", "level", "selection", "transport"}
STYLES_V5 = STYLES_V4 | {"lap"}
ICONS_V4 = {"", "play", "pause", "list", "win", "tracks", "back", "home", "more", "prev", "next", "switch", "cancel"}
NEW_ICONS = {"expand": "more", "clock": "list", "playlists": "list", "playnext": "more", "seek": "tracks",
             "shuffle": "switch", "heart": "more", "snapleft": "prev", "snapright": "next"}   # 2.2
ICONS_V5 = ICONS_V4 | set(NEW_ICONS)
MOMENTS = {"queued", "shuffle", "like", "unlike", "snap", "started"}
HOME = {"nowPlaying", "volume", "idle", "notice"}
ALIVE_FIELDS = {"playing", "clock", "progress", "ledDrive", "ledDither"}
TUNING_FIELDS = {"ledPink", "ledVolFull"}
LAP_MAX = 59999
BUDGET_V4, BUDGET_V5 = 1100, 1400
# Section 14.1: ALIVE's worst latched values, "reducedMotion":false, and the 38 B of tuning fields.
RESERVE_ALIVE = {"clock": 1439, "progress": {"pos": 86400000, "dur": 86400000}, "ledDrive": 255, "ledDither": False}
RESERVE_V5 = {"reducedMotion": False}
RESERVE_TUNING = {"ledPink": 16777215, "ledVolFull": False}


def level(case):
    value = case["capabilities"].get("presentation", 0)
    return value if type(value) is int else 0


def alive(case):
    cap = case["capabilities"].get("alive")
    return level(case) >= 4 and isinstance(cap, dict) and type(cap.get("version")) is int and cap["version"] == 1


def line_bytes(frame):
    return len(json.dumps({"frame": {**frame, "id": frame.get("id", 0x7FFFFFFF)}}, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8")) + 1


def clamp(value, low, high):
    return max(low, min(value, high))


def mmss(seconds):
    minutes, rest = divmod(seconds, 60)
    return "%d:%02d" % (minutes, rest)


def layout_of(frame):
    if isinstance(frame.get("layout"), str):
        return frame["layout"]
    return {"RECENTLY ADDED": "recent", "TRACKS": "tracks", "WINDOWS": "windows"}.get(frame.get("mode"), "nowPlaying")


def sat(color):
    """ALIVE.md section 2 sat(), from its text (exact rationals, half away from zero)."""
    from fractions import Fraction
    rgb = [(color >> 16) & 255, (color >> 8) & 255, color & 255]
    mx, mn = max(rgb), min(rgb)
    if mx - mn < 30:
        return None
    out = 0
    for x in rgb:
        value = Fraction(max(0, 4 * x - 3 * mn), 4 * mx - 3 * mn) * 255
        rounded = int(value + Fraction(1, 2))   # value >= 0: floor(v + 1/2) is half away from zero
        out = out << 8 | rounded
    return out


def luminance(color):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(color >> 16 & 255) + 0.7152 * lin(color >> 8 & 255) + 0.0722 * lin(color & 255)


def accent_ink(color):
    """Section 5.3, from its text."""
    s = sat(color) if color else None
    if s is None:
        return 0xFFFFFF
    for j in range(9):
        m = 0
        for shift in (16, 8, 0):
            c = s >> shift & 255
            m = m << 8 | (c + ((255 - c) * j + 4) // 8)
        if luminance(m) >= 0.10:
            return m
    raise AssertionError("j = 8 is white")


def tone_and_ink(slot, icon, enabled, lit, color, layout):
    """Section 5.2's table, first match wins."""
    rows = [
        (lambda: icon == "", "none", 0),
        (lambda: not enabled, "dim", 0x5A5A5A),
        (lambda: slot == 0 and icon == "cancel", "stop", 0xFF8474),
        (lambda: lit == "on" and icon == "heart", "liked", 0xA3244A),   # [r2.2] row 4 (P5-R29)
        (lambda: lit == "on" and color != 0, "on", accent_ink(color) if color else None),
        (lambda: lit == "on", "on", 0xFFFFFF),
        (lambda: lit == "off", "off", 0x7A7A7A),
        (lambda: slot == 3 and icon in ("play", "prev", "next", "switch"), "go", 0x6ED996),
        (lambda: layout in HOME and slot == 0 and icon == "play", "go", 0x6ED996),
        (lambda: True, "nav", 0xE6E6E6),
    ]
    for test, tone, ink in rows:
        if test():
            return tone, ink
    raise AssertionError("unreachable")


class FixtureShapeTests(unittest.TestCase):
    def test_format_and_unique_names(self):
        self.assertEqual(set(FIXTURES), {"contract", "about", "rules", "cases", "vectors"})
        self.assertIn("PRESENTATION_V5.md", FIXTURES["contract"])
        for rule in ("host", "firmwareOutput", "firmwareRaw", "v5Raw", "downgrade", "windowRule", "card", "moment",
                     "lap", "budget"):
            self.assertIn(rule, FIXTURES["rules"])
        self.assertEqual(len(BY_NAME), len(CASES))
        for case in CASES:
            with self.subTest(case=case["name"]):
                self.assertEqual(set(case), {"name", "note", "capabilities", "input", "expect", "rawParity", "v5"})
                self.assertIn(level(case), (2, 4, 5))
                self.assertEqual(set(case["expect"]), {"accept", "output"} if case["expect"]["accept"] else {"accept"})
                self.assertEqual(set(case["v5"]), {"accept", "stored"} if case["v5"]["accept"] else {"accept"})
                if case["v5"]["accept"]:
                    self.assertEqual(set(case["v5"]["stored"]), {
                        "layout", "page", "ringStyle", "ringIndex", "ringCount", "ringFirst", "ringNow", "ringCard",
                        "ringUnavailable", "lit", "color", "icon", "feedbackKind", "feedbackMoment", "feedbackSide",
                        "feedbackColor", "feedbackSkip", "reducedMotion", "ledPink", "ledVolFull"})

    def test_fixture_is_what_its_generator_writes(self):
        """tests/tools/make_frames_v5.py regenerates the fixture byte for byte (no hand edits, no stale
        vectors: WP3-REV-2)."""
        import importlib.util
        path = Path(__file__).resolve().parent / "tools" / "make_frames_v5.py"
        spec = importlib.util.spec_from_file_location("make_frames_v5_under_test", path)
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        fixture = Path(__file__).resolve().parent / "fixtures" / "frames_v5.json"
        self.assertEqual(generator.render(), fixture.read_bytes().decode("utf-8"),
                         "frames_v5.json is stale; run tests/tools/make_frames_v5.py")

    def test_required_case_families_are_present(self):
        names = set(BY_NAME)
        required = {
            # each new layout token, p5 accepted and p4 mapped
            "v5-seek-p5", "v5-seek-p4", "v5-explorer-tab0-p5", "v5-explorer-tab1-p5", "v5-explorer-tab0-p4",
            "v5-explorer-tab1-p4", "v5-upnext-p5", "v5-upnext-p4",
            # lap valid and invalid
            "lap-count-1", "lap-count-59999", "lap-count-0", "lap-count-60000", "lap-index-equals-count",
            "lap-value-missing",
            # now
            "now-valid", "now-minus-two", "now-equals-count", "now-bool", "now-stripped-on-recent",
            "now-stripped-on-explorer", "now-stripped-on-transport", "now-stripped-on-level", "now-large-int32",
            # card
            "card-valid", "card-now-not-count-minus-2", "card-count-below-2", "card-not-bool", "card-stripped-on-recent",
            # unavailable on upnext
            "unavailable-upnext-stripped", "unavailable-upnext-card-stripped", "unavailable-upnext-beyond-window",
            # lit and colour
            "lit-on-off", "lit-invalid-token", "lit-with-empty-icon", "lit-with-disabled",
            "color-without-lit-host-strips", "heart-lit-on-no-colour",
            # icons
            "icon-legacy-home", "icon-legacy-more", "icon-legacy-cancel", "icon-unknown",
            # moments
            "moment-invalid-token", "moment-with-skip-alive", "moment-snap-without-side", "moment-side-without-snap",
            "moment-color-started", "moment-color-snap", "moment-color-like", "moment-color-out-of-range",
            # latched
            "reduced-motion-true", "reduced-motion-false", "reduced-motion-invalid",
            "led-pink-0", "led-pink-1", "led-pink-max", "led-pink-invalid-minus-one", "led-pink-invalid-over",
            "led-pink-invalid-bool", "led-pink-invalid-string", "led-pink-invalid-float",
            "led-vol-full-true", "led-vol-full-false", "led-vol-full-invalid-int", "led-vol-full-invalid-string",
            "tuning-without-alive", "tuning-p4", "tuning-p4-alive",
            # budget and gating
            "budget-windows-worst", "budget-windows-escape-heavy", "gating-p5-no-alive", "gating-p4-no-v5",
        }
        self.assertLessEqual(required, names, sorted(required - names))
        for token in NEW_ICONS:
            self.assertIn(f"icon-{token}-p5", names)
            self.assertIn(f"icon-{token}-p4", names)
        for moment in MOMENTS:
            for suffix in ("ok", "err", "p4"):
                self.assertIn(f"moment-{moment}-{suffix}", names)

    def test_large_now_stores_as_int32_on_both_sides(self):
        case = BY_NAME["now-large-int32"]
        ring = case["input"]["ring"]
        self.assertEqual((ring["count"], ring["index"], ring["now"], ring["card"], ring["first"]),
                         (40002, 40001, 40000, True, 39982))
        self.assertEqual(case["v5"]["stored"]["ringNow"], 40000)
        self.assertEqual(case["expect"]["output"]["ring"]["now"], 40000)


class HostTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)   # stripped fields are logged by design

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_host_reproduces_every_output(self):
        for case in CASES:
            with self.subTest(case=case["name"]):
                if case["expect"]["accept"]:
                    self.assertEqual(device._frame(deepcopy(case["input"]), case["capabilities"]),
                                     case["expect"]["output"])
                else:
                    with self.assertRaises(ValueError):
                        device._frame(deepcopy(case["input"]), case["capabilities"])

    def test_v5_parse_gives_every_verdict(self):
        for case in CASES:
            with self.subTest(case=case["name"]):
                stored, invalid = device.v5_parse(deepcopy(case["input"]))
                self.assertEqual(not invalid, case["v5"]["accept"], invalid)
                if case["v5"]["accept"]:
                    self.assertEqual(stored, case["v5"]["stored"])

    def test_presentation_4_keeps_every_v5_window(self):
        """WP3-REV-1: a v7 controller sends v5 windows (first = clamp(index-10, 0, count-20)) whatever the knob;
        the presentation-4 output, read by a V4 parser (an absent first derived as clamp(index-9, ...)), must give
        the same first, colours and mask for every index, and be a fixed point of the host."""
        caps = BY_NAME["window-v5-first-0-index-10-p4"]["capabilities"]
        for count in (21, 30, 41, 45):
            for index in range(count):
                first = clamp(index - 10, 0, count - 20)
                window = min(20, count - first)
                ring = {"style": "selection", "value": 0, "index": index, "count": count, "first": first,
                        "colors": [0x100000 + k for k in range(window)], "unavailable": 1 << (index - first)}
                frame = {**deepcopy(BY_NAME["window-v5-first-0-index-10-p4"]["input"]), "ring": ring}
                with self.subTest(count=count, index=index):
                    out = device._frame(deepcopy(frame), caps)
                    sent = out["ring"]
                    read_first = sent.get("first", clamp(index - 9, 0, count - 20))
                    self.assertEqual(read_first, first)
                    self.assertEqual((sent["colors"], sent["unavailable"]), (ring["colors"], ring["unavailable"]))
                    stored, invalid = device.v5_parse(deepcopy(out))
                    self.assertEqual((invalid, stored["ringFirst"], stored["ringUnavailable"]),
                                     ([], first, ring["unavailable"]))
                    self.assertEqual(device._frame(deepcopy(out), caps), out)

    def test_output_is_idempotent(self):
        """A host output fed to the host again comes back unchanged (it is already a wire frame)."""
        for case in CASES:
            output = case["expect"].get("output")
            if output is None or level(case) < 4:
                continue
            with self.subTest(case=case["name"]):
                self.assertEqual(device._frame(deepcopy(output), case["capabilities"]), output)


class OutputContractTests(unittest.TestCase):
    """Each host output against sections 2.2, 3-7 and 14 read independently."""

    def outputs(self, minimum=0, maximum=99):
        for case in CASES:
            if case["expect"]["accept"] and minimum <= level(case) <= maximum:
                yield case, case["expect"]["output"]

    def test_presentation_5_outputs(self):
        for case, out in self.outputs(5, 5):
            with self.subTest(case=case["name"]):
                layout, ring = layout_of(out), out["ring"]
                self.assertIn(layout, LAYOUTS_V5)
                self.assertIn(ring["style"], STYLES_V5)
                count, index = ring["count"], ring["index"]
                # 4.2: first always sent when count > 20, satisfying the window rule; never when count <= 20.
                if count > 20:
                    self.assertIn("first", ring)
                    self.assertTrue(ring["first"] <= index < ring["first"] + 20 or ring["style"] in ("off", "level"))
                    if "first" not in case["input"]["ring"]:
                        self.assertEqual(ring["first"], clamp(index - 10, 0, count - 20))
                else:
                    self.assertNotIn("first", ring)
                first = ring.get("first", 0)
                window = max(0, min(20, count - first))
                if ring["style"] == "lap":
                    self.assertTrue(1 <= count <= LAP_MAX and index < count)
                if "colors" in ring:
                    self.assertEqual((out.get("ledStyle"), ring["style"]), ("color", "selection"))
                    self.assertLessEqual(len(ring["colors"]), window)
                if "unavailable" in ring:
                    self.assertNotEqual(layout, "upnext")
                    self.assertTrue(0 < ring["unavailable"] < 1 << window)
                upnext = ring["style"] == "selection" and layout == "upnext"
                if "now" in ring:
                    self.assertTrue(upnext and -1 < ring["now"] < count)
                if "card" in ring:
                    self.assertTrue(upnext and ring["card"] is True)
                    self.assertTrue(count >= 2 and ring.get("now") == count - 2)
                for key, default in (("moreIndex", -1), ("external", False)):
                    self.assertNotEqual(ring.get(key, "absent"), default)
                for slot, button in enumerate(out["buttons"]):
                    self.assertIn(button["icon"], ICONS_V5)
                    if "lit" in button:
                        self.assertIn(button["lit"], ("on", "off"))
                    if "color" in button:
                        self.assertEqual(button.get("lit"), "on")
                        self.assertNotEqual(button["icon"], "heart")
                        self.assertTrue(0 < button["color"] <= 0xFFFFFF)
                feedback = out.get("feedback")
                if feedback is not None:
                    self.assertLessEqual(set(feedback), {"kind", "seq", "skip", "moment", "side", "color"})
                    if "moment" in feedback:
                        self.assertEqual(feedback["kind"], "ok")
                        self.assertIn(feedback["moment"], MOMENTS)
                        self.assertNotIn("skip", feedback)
                    self.assertEqual("side" in feedback, feedback.get("moment") == "snap")
                    if "color" in feedback:
                        self.assertIn(feedback.get("moment"), ("snap", "started"))
                        self.assertNotEqual(feedback["color"], 0)
                if "reducedMotion" in out:
                    self.assertIs(type(out["reducedMotion"]), bool)
                self.assertEqual(bool(ALIVE_FIELDS & set(out)) and not alive(case), False)
                self.assertEqual(bool(TUNING_FIELDS & set(out)) and not alive(case), False)
                self.slimmed(out, layout)
                reserve = {**RESERVE_V5, **(RESERVE_ALIVE if alive(case) else {}),
                           **(RESERVE_TUNING if alive(case) else {})}
                self.assertLessEqual(line_bytes({**out, **reserve}), BUDGET_V5)

    def slimmed(self, out, layout):
        """Section 14.2 / P4 section 8: defaults and legacy fields omitted."""
        for key, default in (("titleTone", "ink"), ("metaTone", "meta"), ("statusTone", "meta"), ("artDim", False),
                             ("page", 0), ("heading", ""), ("meta", ""), ("artKey", ""), ("iconKey", "")):
            self.assertFalse(key in out and out[key] == default and type(out[key]) is type(default), key)
        self.assertNotIn("counter", out)
        if layout not in HOME:
            for key in ("volumeCaption", "confirmedVolume", "restLayout", "volumeVisible"):
                self.assertNotIn(key, out)

    def test_presentation_4_outputs_are_v4_frames(self):
        for case, out in self.outputs(4, 4):
            with self.subTest(case=case["name"]):
                layout, ring = layout_of(out), out["ring"]
                self.assertIn(layout, LAYOUTS_V4)
                self.assertIn(ring["style"], STYLES_V4)
                self.assertNotIn("now", ring)
                self.assertNotIn("card", ring)
                for button in out["buttons"]:
                    self.assertIn(button["icon"], ICONS_V4)
                    self.assertNotIn("lit", button)
                    self.assertNotIn("color", button)
                if "feedback" in out:
                    self.assertLessEqual(set(out["feedback"]), {"kind", "seq", "skip"})
                self.assertFalse({"reducedMotion", *TUNING_FIELDS} & set(out))
                if not alive(case):
                    self.assertFalse(ALIVE_FIELDS & set(out))
                # P4 section 8 / P5 4.2: first 0 is omitted only where the parser's derivation for an
                # absent first (V4's clamp(index-9, 0, count-20)) is 0 too; any other first is sent.
                v4_derived = clamp(ring["index"] - 9, 0, ring["count"] - 20) if ring["count"] > 20 else 0
                if "first" in ring:
                    self.assertTrue(ring["first"] <= ring["index"] < ring["first"] + 20)
                    self.assertFalse(ring["first"] == 0 and v4_derived == 0)
                else:
                    self.assertEqual(v4_derived, 0)
                self.slimmed(out, layout)
                reserve = RESERVE_ALIVE if alive(case) else {}
                self.assertLessEqual(line_bytes({**out, **reserve}), BUDGET_V4)

    def test_presentation_4_downgrade_rows(self):
        """Section 2.2, row by row, from each input."""
        for case, out in self.outputs(0, 4):
            inp = case["input"]
            layout = inp.get("layout")
            with self.subTest(case=case["name"]):
                if layout == "seek":
                    self.assertEqual(out["layout"], "tracks")
                    lap = inp["ring"]["style"] == "lap"
                    self.assertEqual(out["title"], mmss(inp["ring"]["index"]) if lap else "")
                    self.assertEqual(out["subtitle"], inp.get("title", ""))
                    self.assertEqual(out["ring"], {"style": "off", "value": 0, "index": 1, "count": 3})
                    if level(case) >= 4:
                        self.assertEqual(out.get("heading"), inp.get("heading"))
                        self.assertEqual(out.get("meta"), inp.get("meta"))
                elif layout in ("explorer", "upnext"):
                    self.assertEqual(out["layout"], "recent")
                    if level(case) >= 4:
                        expected = 1 if layout == "upnext" else min(255, 1 + inp.get("page", 0))
                        self.assertEqual(out["page"], expected)
                        self.assertEqual(out.get("heading"), inp.get("heading"))
                    else:
                        self.assertNotIn("page", out)
                elif inp["ring"]["style"] == "lap":
                    self.assertEqual(out["ring"], {"style": "off", "value": 0, "index": 0, "count": 0})
                for sent, button in zip(inp["buttons"], out["buttons"]):
                    icon = sent.get("icon", "")
                    self.assertEqual(button.get("icon"), NEW_ICONS.get(icon, icon))
                feedback = inp.get("feedback")
                if level(case) >= 4 and isinstance(feedback, dict):
                    if feedback.get("moment") == "unlike" and feedback.get("kind") == "ok":
                        self.assertNotIn("feedback", out)
                    else:
                        self.assertEqual({k: v for k, v in out["feedback"].items() if k != "skip"},
                                         {"kind": feedback["kind"], "seq": feedback["seq"]})
                if level(case) < 4:
                    for key in ("heading", "meta", "page", "feedback", "titleTone", "metaTone", "artDim"):
                        self.assertNotIn(key, out)
                    self.assertTrue(all(isinstance(b.get("color"), int) for b in out["buttons"]))

    def test_no_downgraded_icon_turns_green(self):
        """Section 2.2: none of the nine new tokens lands on slot 3 in the r2.1 maps, so the V4 go rule never
        applies to a downgraded icon (and snapleft/snapright map to prev/next on slots 1 and 2 only)."""
        for case, out in self.outputs(4, 4):
            sent = case["input"]["buttons"][3].get("icon", "")
            with self.subTest(case=case["name"]):
                if sent in NEW_ICONS:
                    self.assertNotIn(NEW_ICONS[sent], ("play", "prev", "next", "switch"))

    def test_scope_strips_are_silent_and_identical(self):
        """3.3 rule 3: valid out-of-scope values are dropped by the host and stored as defaults by the parser."""
        expectations = {
            "now-stripped-on-recent": ("ringNow", -1, "ring", "now"),
            "now-stripped-on-explorer": ("ringNow", -1, "ring", "now"),
            "now-stripped-on-transport": ("ringNow", -1, "ring", "now"),
            "now-stripped-on-level": ("ringNow", -1, "ring", "now"),
            "card-stripped-on-recent": ("ringCard", False, "ring", "card"),
            "unavailable-upnext-stripped": ("ringUnavailable", 0, "ring", "unavailable"),
            "moment-side-without-snap": ("feedbackSide", 0, "feedback", "side"),
            "moment-color-like": ("feedbackColor", 0, "feedback", "color"),
            "moment-queued-err": ("feedbackMoment", None, "feedback", "moment"),
        }
        for name, (stored_key, default, parent, key) in expectations.items():
            case = BY_NAME[name]
            with self.subTest(case=name):
                self.assertTrue(case["expect"]["accept"] and case["v5"]["accept"] and case["rawParity"])
                self.assertIn(key, case["input"][parent])
                self.assertNotIn(key, case["expect"]["output"][parent])
                self.assertEqual(case["v5"]["stored"][stored_key], default)

    def test_invalid_values_strip_on_the_host_and_reject_on_the_parser(self):
        """3.3 rule 2: an invalid present optional value is stripped by the host (never an error), rejected by
        the firmware; required ring violations (lap bounds) are errors on both."""
        for case in CASES:
            with self.subTest(case=case["name"]):
                if not case["v5"]["accept"] and case["expect"]["accept"]:
                    self.assertFalse(case["rawParity"])
                if not case["expect"]["accept"]:
                    self.assertFalse(case["v5"]["accept"])

    def test_budget_worst_cases(self):
        """14.1: the worst realistic frames fit 1,400 B with the 148 B latched reserve, untouched; an
        escape-heavy one is shortened (V4's order) until it fits."""
        reserve = {**RESERVE_V5, **RESERVE_ALIVE, **RESERVE_TUNING}
        self.assertEqual(sum(len(json.dumps({k: v}, separators=(",", ":"))) - 1 for k, v in RESERVE_TUNING.items()), 38)
        for name in ("budget-windows-worst", "budget-windows-worst-16b-labels", "budget-upnext-worst",
                     "budget-explorer-worst", "budget-home-worst", "budget-seek-worst"):
            case = BY_NAME[name]
            out = case["expect"]["output"]
            with self.subTest(case=name):
                self.assertLessEqual(line_bytes({**out, **reserve}), BUDGET_V5)
                for key in ("title", "subtitle", "meta", "volumeCaption"):
                    self.assertEqual(out.get(key, ""), case["input"].get(key, ""))
        heavy = BY_NAME["budget-windows-escape-heavy"]
        self.assertGreater(line_bytes({**heavy["input"], **reserve}), BUDGET_V5)
        out = heavy["expect"]["output"]
        self.assertLessEqual(line_bytes({**out, **reserve}), BUDGET_V5)
        self.assertGreater(line_bytes({**out, **reserve}), BUDGET_V5 - 4)   # shortened only as far as needed
        self.assertTrue(set(out["title"]) <= {'"'} and set(out["subtitle"]) <= {'"'})

    def test_window_rule_cases(self):
        self.assertEqual(BY_NAME["window-v5-index-10"]["expect"]["output"]["ring"]["first"], 0)
        self.assertEqual(len(BY_NAME["window-v5-index-10"]["expect"]["output"]["ring"]["colors"]), 20)
        self.assertEqual(BY_NAME["window-v4-index-10"]["expect"]["output"]["ring"]["first"], 1)
        self.assertNotIn("colors", BY_NAME["window-v4-index-10"]["expect"]["output"]["ring"])
        self.assertEqual(BY_NAME["window-v5-index-30"]["expect"]["output"]["ring"]["first"], 20)
        self.assertEqual(BY_NAME["window-absent-first-derived-v4"]["v5"]["stored"]["ringFirst"], 21)
        # WP3-REV-1: a v5-rule first 0 at index 10 (V4 derives 1) keeps its explicit 0 for cc5.3, with the
        # colours and the unavailable mask; at index 9 (V4 derives 0 too) presentation 4 still omits it.
        for name in ("window-v5-first-0-index-10-p4", "window-v5-first-0-index-10-p4-alive"):
            case = BY_NAME[name]
            self.assertEqual(level(case), 4)
            self.assertEqual((case["input"]["ring"]["first"], case["input"]["ring"]["index"],
                              case["input"]["ring"]["count"]), (0, 10, 41))
            ring = case["expect"]["output"]["ring"]
            self.assertEqual((ring["first"], len(ring["colors"]), ring["unavailable"]), (0, 20, 1 << 10), name)
            self.assertEqual(ring["colors"], case["input"]["ring"]["colors"])
        upnext = BY_NAME["window-v5-first-0-index-10-upnext-p4"]["expect"]["output"]
        self.assertEqual((upnext["layout"], upnext["ring"]["first"], len(upnext["ring"]["colors"])), ("recent", 0, 20))
        self.assertNotIn("first", BY_NAME["window-first-0-index-9-p4"]["expect"]["output"]["ring"])
        self.assertEqual(BY_NAME["window-first-0-index-9-p5"]["expect"]["output"]["ring"]["first"], 0)


class VectorTests(unittest.TestCase):
    """The shared vectors against a second reading of sections 4.3, 5.2 and 5.3."""

    def test_mmss(self):
        for seconds, text in FIXTURES["vectors"]["mmss"]:
            self.assertEqual(text, mmss(seconds))
            self.assertEqual(P.mmss(seconds), text)
        self.assertIn([74, "1:14"], FIXTURES["vectors"]["mmss"])
        self.assertIn([59998, "999:58"], FIXTURES["vectors"]["mmss"])

    def test_accent_ink(self):
        self.assertIn([0x000080, 0x4040FF], FIXTURES["vectors"]["accentInk"])   # the contract's example
        for color, ink in FIXTURES["vectors"]["accentInk"]:
            with self.subTest(color=hex(color)):
                self.assertEqual(accent_ink(color), ink)
                self.assertEqual(P.accent_ink(color), ink)
                self.assertGreaterEqual(luminance(ink), 0.10)

    def test_tones(self):
        vectors = FIXTURES["vectors"]["tones"]
        self.assertGreaterEqual(len(vectors), 600)
        # [r2.2] (P5-R29, OQ-5): the liked heart is the derived tone `liked` in #A3244A; #FF285A is only the
        # desktop row heart, never an LCD ink.
        self.assertIn(("liked", 0xA3244A), {(v["tone"], v["ink"]) for v in vectors})
        self.assertNotIn(0xFF285A, {v["ink"] for v in vectors})
        self.assertEqual({v["tone"] for v in vectors}, {"none", "dim", "stop", "liked", "on", "off", "go", "nav"})
        for v in vectors:
            with self.subTest(**v):
                tone, ink = tone_and_ink(v["slot"], v["icon"], v["enabled"], v["lit"], v["color"], v["layout"])
                self.assertEqual((v["tone"], v["ink"]), (tone, ink))
                args = (v["slot"], v["icon"], v["enabled"], v["lit"])
                self.assertEqual(P.button_tone_v5(*args, v["layout"]), tone)
                self.assertEqual(P.button_ink_v5(*args, v["color"], v["layout"]), ink)


if __name__ == "__main__":
    unittest.main()
