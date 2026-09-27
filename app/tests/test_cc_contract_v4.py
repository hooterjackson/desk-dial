"""Presentation contract v4 on the host: validation, gating, slimming, budget, robustness.

No port is opened: every bridge runs on an in-memory fake serial with a fake clock.
"""
import base64
from copy import deepcopy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import device, presentation
from control_center.controller import Controller, Screen
from control_center.device import DeviceBridge, PacedSerial, _frame
from test_cc_device import Clock, FakeSerial, control

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "frames_v4.json"
P2 = {"controlCenter": 1, "presentation": 2}
P4 = {"controlCenter": 1, "presentation": 4, "glyphs": "latin-ext-a"}
ART = {"version": 1, "width": 120, "height": 120, "format": "RGB565_LE", "chunkBytes": 384,
       "cacheEntries": 8, "available": True, "composited": "scrim80"}
# cc5.3: cc5.2's capabilities plus artwork2 (ARTWORK2.md section 1).
A2 = {**P4, "artwork": ART, "artwork2": deepcopy(presentation.ARTWORK2_CAPABILITY)}
ICON_KEY = "a1b2c3d4e5f60718"  # 16 characters, as artwork.icon_key() makes them

# --- An independent reading of PRESENTATION_V4.md (sections 2-4 and 8). ----------
# It never calls device._frame, so fixture outputs are checked against the
# contract itself rather than against the adapter that generated them.
_TEXT = {"mode": 24, "target": 64, "value": 64, "detail": 96, "status": 64, "title": 96, "subtitle": 96,
         "counter": 24, "volumeCaption": 96, "heading": 32, "meta": 96}
_V4_ONLY = {"restLayout", "heading", "meta", "titleTone", "metaTone", "statusTone", "page", "artDim", "feedback"}
_TOP = {"id", "mode", "target", "value", "detail", "status", "title", "subtitle", "counter", "activity", "layout",
        "volumeVisible", "volumeCaption", "confirmedVolume", "ledStyle", "artKey", "iconKey", "buttons",
        "ring"} | _V4_ONLY
_ICONS = {"play", "pause", "list", "win", "tracks", "back", "home", "more", "prev", "next", "switch", "cancel", ""}
_LAYOUTS = {"nowPlaying", "volume", "idle", "recent", "tracks", "windows", "notice"}
_ENUMS = {"activity": {"idle", "loading", "pending", "error", "unavailable", "offline"},
          "restLayout": {"nowPlaying", "idle"}, "titleTone": {"ink", "muted"},
          "metaTone": {"meta", "secondary", "error", "success"},
          "statusTone": {"meta", "secondary", "error", "success"}, "ledStyle": {"white", "color"}}
_V4_DEFAULTS = {"titleTone": "ink", "metaTone": "meta", "statusTone": "meta", "artDim": False, "page": 0,
                "heading": "", "meta": "", "artKey": "", "iconKey": ""}
_RING_DEFAULTS = {"first": 0, "unavailable": 0, "moreIndex": -1, "external": False}
_MODE_LAYOUT = {"VOLUME": "nowPlaying", "RECENTLY ADDED": "recent", "TRACKS": "tracks", "WINDOWS": "windows"}


def _int(value, low, high):
    return type(value) is int and low <= value <= high


def _glyph_ok(ch, latin):
    code = ord(ch)
    if not latin:
        return 0x20 <= code <= 0x7E
    return 0x20 <= code <= 0x7E or 0xA0 <= code <= 0x17F or ch in "·–—‘’“”•…"


def _artwork2_negotiated(caps):
    """ARTWORK2.md section 1, read independently: presentation >= 4 and every artwork2 field
    exactly (type and value) as frozen; extra fields ignored."""
    def same(value, expected):
        if isinstance(expected, dict):
            return isinstance(value, dict) and all(k in value and same(value[k], v) for k, v in expected.items())
        return type(value) is type(expected) and value == expected
    level = caps.get("presentation", 0)
    return type(level) is int and level >= 4 and same(caps.get("artwork2"), presentation.ARTWORK2_CAPABILITY)


def contract_violations(frame, caps):
    """Every way `frame` breaks the contract for firmware advertising `caps` (empty when valid)."""
    v4 = caps.get("presentation", 0) >= 4
    latin = v4 and caps.get("glyphs") == "latin-ext-a"
    bad = []

    def need(ok, what):
        if not ok:
            bad.append(what)
    need(isinstance(frame, dict), "frame object")
    if not bad:
        need(set(frame) <= _TOP, f"unknown fields {sorted(set(frame) - _TOP)}")
        if "id" in frame:
            need(_int(frame["id"], 1, 0x7FFFFFFF), "id range")
        for name in ("mode", "target", "value", "detail", "status", "buttons", "ring"):
            need(name in frame, f"required {name}")
        for name, capacity in _TEXT.items():
            if name in frame:
                text = frame[name]
                need(isinstance(text, str) and len(text.encode("utf-8")) <= capacity, f"{name} capacity")
                need(isinstance(text, str) and all(_glyph_ok(c, latin) for c in text), f"{name} glyphs")
        for name, allowed in _ENUMS.items():
            if name in frame:
                need(frame[name] in allowed, f"{name} token")
        if "layout" in frame:
            need(frame["layout"] in (_LAYOUTS if v4 else _LAYOUTS - {"notice"}), "layout token")
        if "artKey" in frame:
            need(isinstance(frame["artKey"], str) and len(frame["artKey"]) <= 64
                 and all(c.isascii() and (c.isalnum() or c in "_-") for c in frame["artKey"]), "artKey")
        if "iconKey" in frame:
            # ARTWORK2.md section 6: [A-Za-z0-9_-]{0,24}, only with artwork2 and only on Windows.
            key = frame["iconKey"]
            need(isinstance(key, str) and len(key) <= 24
                 and all(c.isascii() and (c.isalnum() or c in "_-") for c in key), "iconKey")
            layout = frame.get("layout", _MODE_LAYOUT.get(frame.get("mode"), "nowPlaying"))
            need(_artwork2_negotiated(caps) and layout == "windows",
                 "iconKey only with artwork2 negotiated on the windows layout")
        if "page" in frame:
            need(_int(frame["page"], 0, 255), "page")
        if "confirmedVolume" in frame:
            need(_int(frame["confirmedVolume"], 0, 100), "confirmedVolume")
        for name in ("volumeVisible", "artDim"):
            if name in frame:
                need(type(frame[name]) is bool, name)
        if "feedback" in frame:
            fb = frame["feedback"]
            need(isinstance(fb, dict) and set(fb) == {"kind", "seq"} and fb["kind"] in ("ok", "err")
                 and _int(fb["seq"], 1, 0x7FFFFFFF), "feedback")
        buttons = frame.get("buttons")
        need(isinstance(buttons, list) and len(buttons) == 4, "four buttons")
        for slot, button in enumerate(buttons if isinstance(buttons, list) else []):
            need(isinstance(button, dict) and set(button) <= {"label", "enabled", "icon", "color"}
                 and isinstance(button.get("label"), str) and len(button["label"].encode()) <= 16
                 and all(_glyph_ok(c, latin) for c in button["label"]) and type(button.get("enabled")) is bool,
                 f"button {slot}")
            if not isinstance(button, dict):
                continue
            if "icon" in button or v4:
                need(button.get("icon") in _ICONS, f"button {slot} icon (required for v4)")
            if v4:
                need("color" not in button, f"button {slot} color is omitted for v4")
            else:
                need(_int(button.get("color"), 0, 0xFFFFFF), f"button {slot} color (cc4 requires it)")
        ring = frame.get("ring")
        need(isinstance(ring, dict) and ring.get("style") in ("off", "level", "selection", "transport")
             and _int(ring.get("value"), 0, 100) and _int(ring.get("index"), 0, 65535)
             and _int(ring.get("count"), 0, 65535), "ring required fields")
        if isinstance(ring, dict) and not bad:
            index, count = ring["index"], ring["count"]
            if ring["style"] in ("selection", "transport"):
                need(index < count, "index < count")
            if not v4:
                need(set(ring) == {"style", "value", "index", "count"}, "legacy ring has no v4 fields")
            else:
                need(set(ring) <= {"style", "value", "index", "count", *_RING_DEFAULTS, "colors"}, "ring fields")
                first = ring.get("first", 0)
                need(_int(first, 0, 65535) and first <= index < first + 20, "window rule first <= index < first+20")
                need(count > 20 or first == 0, "first is 0 when count <= 20")
                window = max(0, min(20, count - first)) if type(first) is int else 0
                if "colors" in ring:
                    colors = ring["colors"]
                    need(isinstance(colors, list) and len(colors) <= window
                         and all(_int(c, 0, 0xFFFFFF) for c in colors), "colors within the window")
                    need(frame.get("ledStyle") == "color" and ring["style"] == "selection",
                         "colors only in colour mode on a selection ring")
                if "unavailable" in ring:
                    need(_int(ring["unavailable"], 0, (1 << window) - 1), "mask bits within the window")
                if "moreIndex" in ring:
                    need(_int(ring["moreIndex"], -1, count - 1), "moreIndex range")
                if "external" in ring:
                    need(type(ring["external"]) is bool, "external")
                for name, default in _RING_DEFAULTS.items():
                    if name == "first" and count > 20 and max(0, min(index - 9, count - 20)) != 0:
                        # PRESENTATION_V5.md 4.2 (P5-R9, WP3-REV-1): a v7 host windows with
                        # clamp(index - 10, …); where V4's derivation for an absent first
                        # (clamp(index - 9, …)) is not 0, the explicit first 0 must be sent.
                        continue
                    need(name not in ring or ring[name] != default or type(ring[name]) is not type(default),
                         f"slimming: ring.{name} default omitted")
        if v4:
            need("counter" not in frame, "slimming: counter omitted")
            for name, default in _V4_DEFAULTS.items():
                need(name not in frame or frame[name] != default or type(frame[name]) is not type(default),
                     f"slimming: default {name} omitted")
            layout = frame.get("layout", _MODE_LAYOUT.get(frame.get("mode"), "nowPlaying"))
            if layout not in ("nowPlaying", "volume", "idle", "notice"):
                for name in ("volumeCaption", "confirmedVolume", "restLayout", "volumeVisible"):
                    need(name not in frame, f"slimming: {name} only on Home")
            line = json.dumps({"frame": {**frame, "id": frame.get("id", 0x7FFFFFFF)}}, ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8")
            need(len(line) + 1 <= 1100, f"budget: {len(line) + 1} B > 1100 B")
        else:
            need(not set(frame) & _V4_ONLY, f"v4-only fields {sorted(set(frame) & _V4_ONLY)} sent to presentation < 4")
    return bad


def v4_frame(**extra):
    value = {"mode": "RECENTLY ADDED", "target": "Den", "value": "Déjà Vu", "detail": "Beyoncé",
             "status": "", "title": "Déjà Vu", "subtitle": "Beyoncé", "counter": "3 / 10",
             "activity": "idle", "layout": "recent", "heading": "RECENTLY ADDED · P2",
             "meta": "3/11 · Replaces queue", "titleTone": "ink", "metaTone": "meta",
             "statusTone": "meta", "page": 1, "artDim": False, "ledStyle": "color", "artKey": "al_1",
             "volumeCaption": "Night Drive", "confirmedVolume": 28, "volumeVisible": False,
             "restLayout": "nowPlaying", "feedback": {"kind": "ok", "seq": 9},
             "buttons": [{"label": "Back", "enabled": True, "icon": "back", "color": 1},
                         {"label": "Home", "enabled": True, "icon": "home"},
                         {"label": "Win", "enabled": True, "icon": "win"},
                         {"label": "Play", "enabled": True, "icon": "play"}],
             "ring": {"style": "selection", "value": 0, "index": 2, "count": 11, "first": 0,
                      "colors": [0x46E178] * 11, "unavailable": 0b100, "moreIndex": 10, "external": False}}
    value.update(extra)
    return value


class FixtureTests(unittest.TestCase):
    """The shared fixture file the firmware parser will be tested against."""

    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(FIXTURES.read_text(encoding="utf-8"))

    def test_fixture_cases_are_self_describing(self):
        names = [case["name"] for case in self.doc["cases"]]
        self.assertEqual(len(names), len(set(names)))
        kinds = {name.split("-")[0] for name in names}
        self.assertTrue({"v4", "v2", "gate", "req", "opt", "mb"} <= kinds)
        for case in self.doc["cases"]:
            with self.subTest(case=case["name"]):
                self.assertIn(case["capabilities"].get("presentation"), (2, 3, 4))
                self.assertIsInstance(case["expect"]["accept"], bool)
                self.assertEqual("output" in case["expect"], case["expect"]["accept"])
                self.assertIsInstance(case["rawParity"], bool)

    def test_host_adapter_matches_every_fixture(self):
        for case in self.doc["cases"]:
            with self.subTest(case=case["name"]):
                if case["expect"]["accept"]:
                    self.assertEqual(_frame(deepcopy(case["input"]), case["capabilities"]),
                                     case["expect"]["output"])
                else:
                    with self.assertRaises(ValueError):
                        _frame(deepcopy(case["input"]), case["capabilities"])

    def test_host_output_is_a_fixed_point(self):
        # Re-validating what the host sends never changes it: the firmware can store it verbatim.
        for case in self.doc["cases"]:
            if case["expect"]["accept"]:
                with self.subTest(case=case["name"]):
                    output = case["expect"]["output"]
                    self.assertEqual(_frame(deepcopy(output), case["capabilities"]), output)

    def test_every_accepted_output_satisfies_the_contract(self):
        # Checked against the independent contract reading above, not against _frame.
        for case in self.doc["cases"]:
            if case["expect"]["accept"]:
                with self.subTest(case=case["name"]):
                    self.assertEqual(contract_violations(case["expect"]["output"], case["capabilities"]), [])

    def test_contract_reader_is_not_vacuous(self):
        valid = next(c for c in self.doc["cases"] if c["name"] == "v4-windows-window-rule")["expect"]["output"]
        self.assertEqual(contract_violations(valid, P4), [])
        broken = [
            ({**valid, "ring": {"style": "selection", "value": 0, "index": 30, "count": 45}}, "window rule"),
            ({**valid, "ring": {**valid["ring"], "first": 31}}, "window rule"),
            ({**valid, "ring": {**valid["ring"], "colors": [1] * 21}}, "colors within"),
            ({**valid, "ring": {**valid["ring"], "unavailable": 1 << 20}}, "mask bits"),
            ({**valid, "buttons": [{"label": "Cancel", "enabled": True}] + valid["buttons"][1:]}, "icon"),
            ({**valid, "counter": "1 / 2"}, "counter"),
            ({**valid, "title": "Ω"}, "title glyphs"),
            ({**valid, "detail": "x" * 97}, "detail capacity"),
            ({**valid, "iconKey": "a1b2c3d4e5f60718"}, "iconKey only with artwork2"),
        ]
        for frame, reason in broken:
            with self.subTest(reason=reason):
                self.assertTrue(any(reason in problem for problem in contract_violations(frame, P4)))

    def test_hand_written_expectations(self):
        # Written from the contract text; independent of the generator.
        cases = {c["name"]: c for c in self.doc["cases"]}
        window = {"style": "selection", "value": 0, "index": 30, "count": 45, "first": 21}
        rings = {
            "v4-windows-window-rule": {**window, "colors": [0x4285F4] * 20, "unavailable": (1 << 19) | 1},
            "v4-windows-derived-first": window,
            "v4-windows-derived-first-drops-relative": window,
            "v4-windows-early-index-keeps-relative": {"style": "selection", "value": 0, "index": 5, "count": 45,
                                                      "colors": [0x4285F4] * 20, "unavailable": 1},
            "v4-windows-tail-window": {"style": "selection", "value": 0, "index": 44, "count": 45, "first": 25},
            "opt-ring-first-after-index": window,
            "opt-ring-first-window-miss": window,
            "opt-ring-first-small-count": {"style": "selection", "value": 0, "index": 2, "count": 11, "moreIndex": 10},
            "opt-ring-off-index-past-count": {"style": "off", "value": 0, "index": 0, "count": 0},
            "v4-tracks-no-previous": {"style": "transport", "value": 0, "index": 0, "count": 3, "unavailable": 1},
            "v4-home-now-playing": {"style": "level", "value": 54, "index": 0, "count": 101},
        }
        for name, ring in rings.items():
            with self.subTest(case=name):
                self.assertEqual(cases[name]["expect"]["output"]["ring"], ring)
        for name in ("opt-button-icon", "v4-button-without-icon"):
            with self.subTest(case=name):
                self.assertEqual(cases[name]["expect"]["output"]["buttons"][0],
                                 {"label": "Pause", "enabled": True, "icon": ""})
        budget = cases["v4-windows-budget-trims-detail"]["expect"]["output"]
        self.assertEqual((budget["detail"], budget["target"], len(budget["ring"]["colors"])), ("", "DESKTOP", 20))
        # rules.absentFirst: an absent first is derived with the host window rule, never
        # defaulted to 0, so a parser accepts that raw input (v2 senders never send first).
        self.assertIn("absentFirst", self.doc["rules"])
        for name in ("v4-windows-derived-first", "v4-windows-derived-first-drops-relative", "v4-windows-tail-window"):
            with self.subTest(case=name):
                self.assertNotIn("first", cases[name]["input"]["ring"])
                self.assertTrue(cases[name]["rawParity"])

    def test_icon_key_cases(self):
        # ARTWORK2.md section 6, written from the contract text: kept only with artwork2 on the
        # windows layout; otherwise the frame is exactly the one without iconKey.
        cases = {c["name"]: c for c in self.doc["cases"]}
        windows = cases["v4-windows-window-rule"]["expect"]["output"]
        recent = cases["v4-recent-item-colour"]["expect"]["output"]
        kept = {"v4-windows-icon-key": ICON_KEY, "v4-windows-icon-key-24": "Icon_KEY-0123456789abcde"}
        for name, key in kept.items():
            with self.subTest(case=name):
                case = cases[name]
                self.assertEqual(case["capabilities"]["artwork2"], presentation.ARTWORK2_CAPABILITY)
                self.assertEqual(case["expect"]["output"], {**windows, "iconKey": key})
                self.assertTrue(case["rawParity"])
        # An invalid iconKey is stripped by the host AND by the parser (never a rejection, unlike
        # artKey), so its raw input keeps rawParity: identical accept/strip results (section 10).
        stripped = {"v4-windows-icon-key-empty": (windows, True), "opt-icon-key-long": (windows, True),
                    "opt-icon-key-bad-chars": (windows, True), "opt-icon-key-not-text": (windows, True),
                    "gate-icon-key-recent-layout": (recent, True),
                    "gate-icon-key-without-artwork2": (windows, True),
                    "gate-icon-key-malformed-artwork2": (windows, True)}
        for name, (expected, raw) in stripped.items():
            with self.subTest(case=name):
                case = cases[name]
                self.assertIn("iconKey", case["input"])
                self.assertEqual(case["expect"]["output"], expected)
                self.assertEqual(case["rawParity"], raw)
        self.assertEqual(len(cases["opt-icon-key-long"]["input"]["iconKey"]), 25)
        self.assertNotIn("artwork2", cases["gate-icon-key-without-artwork2"]["capabilities"])
        budget = cases["v4-windows-icon-key-budget"]["expect"]["output"]
        line = json.dumps({"frame": budget}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.assertLessEqual(len(line) + 1, presentation.FRAME_BUDGET_BYTES)
        self.assertEqual(budget["iconKey"], ICON_KEY)
        self.assertEqual(budget["detail"], "", "the section 8 trim order absorbs the key")
        self.assertIn("iconKey", self.doc["rules"])

    def test_raw_parity_rings_are_accepted_under_the_window_rule(self):
        # For every case a parser must accept raw: a present first satisfies the window rule,
        # and an absent one is the host rule's derivation (rules.absentFirst).
        for case in self.doc["cases"]:
            if not (case["rawParity"] and case["expect"]["accept"]):
                continue
            with self.subTest(case=case["name"]):
                raw, sent = case["input"]["ring"], case["expect"]["output"]["ring"]
                index, count = raw["index"], raw["count"]
                first = raw.get("first", presentation.window_first(index, count))
                self.assertTrue(first <= index < first + 20 and (count > 20 or first == 0), raw)
                v4 = case["capabilities"]["presentation"] >= 4
                self.assertEqual(sent.get("first", 0), first if v4 else 0)

    def test_recorded_long_v2_windows_list_is_accepted_with_a_derived_first(self):
        # The installed cc4-era companion never sends first. With more than 20 windows and a
        # selection at 20 or above, a rejection would loop it through reconnects on cc5.
        cases = {c["name"]: c for c in self.doc["cases"]}
        for name in ("v2-windows-long-to-cc5", "v2-windows-long-last-to-cc5"):
            with self.subTest(case=name):
                case = cases[name]
                ring = case["input"]["ring"]
                self.assertNotIn("first", ring)
                self.assertGreater(ring["count"], presentation.RING_WINDOW)
                self.assertGreaterEqual(ring["index"], presentation.RING_WINDOW)
                self.assertTrue(case["expect"]["accept"] and case["rawParity"])
                self.assertEqual(case["expect"]["output"]["ring"]["first"],
                                 presentation.window_first(ring["index"], ring["count"]))
        legacy = cases["v2-windows-long-to-cc4"]
        self.assertTrue(legacy["expect"]["accept"])
        self.assertEqual(legacy["expect"]["output"], legacy["input"], "presentation 2: sent unchanged")

    def test_recorded_v2_frames_are_accepted_at_every_presentation(self):
        recorded = [c for c in self.doc["cases"] if c["name"].startswith("v2-")]
        self.assertGreaterEqual(len(recorded), 10)
        for case in recorded:
            for caps in (P2, {"presentation": 3}, P4):
                with self.subTest(case=case["name"], caps=caps["presentation"] if "presentation" in caps else 0):
                    _frame(deepcopy(case["input"]), caps)


class ValidationTests(unittest.TestCase):
    def setUp(self):
        device._strip_logged.clear()

    def test_required_fields_still_reject(self):
        for name, value in (("mode", None), ("target", 3), ("value", ["x"]), ("detail", "a\x1fb"),
                            ("status", "\n")):
            with self.subTest(field=name), self.assertRaises(ValueError):
                _frame(v4_frame(**{name: value}), P4)
        for missing in ("mode", "target", "value", "detail", "status", "buttons", "ring"):
            broken = v4_frame()
            del broken[missing]
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                _frame(broken, P4)
        for ring in ({"style": "selection", "value": 0, "index": 11, "count": 11},
                     {"style": "transport", "value": 0, "index": 0, "count": 0},
                     {"style": "level", "value": 101, "index": 0, "count": 101},
                     {"style": "level", "value": 5, "index": -1, "count": 101},
                     {"style": "glow", "value": 5, "index": 0, "count": 1}):
            with self.subTest(ring=ring), self.assertRaises(ValueError):
                _frame(v4_frame(ring=ring), P4)
        button = {"label": "Back", "enabled": "yes"}
        with self.assertRaises(ValueError):
            _frame(v4_frame(buttons=[button] * 4), P4)
        with self.assertRaises(ValueError):
            _frame(v4_frame(id=0), P4)

    def test_invalid_optional_fields_are_stripped_and_logged_never_raised(self):
        invalid = {"activity": "blink", "layout": "grid", "restLayout": "tracks", "heading": "a\tb",
                   "meta": 7, "titleTone": "error", "metaTone": "ink", "statusTone": "loud",
                   "page": 300, "artDim": 1, "ledStyle": "rgb", "artKey": "../x",
                   "confirmedVolume": -1, "volumeVisible": "no", "volumeCaption": None,
                   "feedback": {"kind": "ok", "seq": 0}, "title": "\x07", "subtitle": 5,
                   "counter": {}, "mystery": True}
        with self.assertLogs("control_center.device", "WARNING") as logs:
            result = _frame(v4_frame(**invalid), P4)
        for name in invalid:
            self.assertNotIn(name, result)
        self.assertEqual(result["mode"], "RECENTLY ADDED")
        self.assertTrue(logs.output)
        self.assertFalse(any("../x" in line or "mystery" in line for line in logs.output),
                         "logs name fields, never their values or arbitrary keys")

    def test_strip_logging_is_rate_limited(self):
        with self.assertLogs("control_center.device", "WARNING") as logs:
            for _ in range(50):
                _frame(v4_frame(activity="blink"), P4)
        self.assertEqual(len(logs.output), 1)

    def test_invalid_ring_options_are_stripped(self):
        ring = v4_frame()["ring"]
        cases = [({"colors": [1] * 12}, "colors"), ({"colors": [-1]}, "colors"),
                 ({"colors": "red"}, "colors"), ({"unavailable": 1 << 11}, "unavailable"),
                 ({"unavailable": -1}, "unavailable"), ({"moreIndex": 11}, "moreIndex"),
                 ({"moreIndex": -2}, "moreIndex"), ({"external": 1}, "external"),
                 ({"available": [True] * 11}, "available")]
        for change, name in cases:
            with self.subTest(change=change):
                result = _frame(v4_frame(ring={**ring, **change}), P4)["ring"]
                self.assertNotIn(name, result)
                self.assertEqual((result["style"], result["index"], result["count"]), ("selection", 2, 11))

    def test_window_rule_and_relative_fields(self):
        base = {"style": "selection", "value": 0, "index": 30, "count": 45}
        ok = _frame(v4_frame(ring={**base, "first": 21, "colors": [5] * 20, "unavailable": (1 << 20) - 1}), P4)
        self.assertEqual((ok["ring"]["first"], len(ok["ring"]["colors"]), ok["ring"]["unavailable"]),
                         (21, 20, (1 << 20) - 1))
        self.assertEqual(presentation.window_first(30, 45), 21)
        # Last page of a long list: the window may hold fewer than 20 entries.
        tail = _frame(v4_frame(ring={**base, "index": 44, "first": 25, "colors": [5] * 20}), P4)["ring"]
        self.assertEqual(tail["first"], 25)
        # An invalid first is replaced by the host window; the relative fields that
        # referred to it are dropped (the rest of the frame is sent).
        for first in (10, 31, 45, -1, True, "21"):
            with self.subTest(first=first):
                ring = _frame(v4_frame(ring={**base, "first": first, "colors": [5] * 5, "unavailable": 1}), P4)["ring"]
                self.assertEqual(ring, {**base, "first": 21})
        # No first at all: derived; colours relative to the implicit 0 only survive when it stays 0.
        self.assertEqual(_frame(v4_frame(ring={**base, "colors": [5] * 5}), P4)["ring"], {**base, "first": 21})
        early = _frame(v4_frame(ring={**base, "index": 9, "colors": [5] * 5, "unavailable": 3}), P4)["ring"]
        self.assertEqual(early, {**base, "index": 9, "colors": [5] * 5, "unavailable": 3})
        short = _frame(v4_frame(ring={"style": "selection", "value": 0, "index": 3, "count": 11, "first": 1}), P4)
        self.assertNotIn("first", short["ring"])
        tail = _frame(v4_frame(ring={**base, "index": 44, "first": 25, "colors": [5] * 21}), P4)["ring"]
        self.assertNotIn("colors", tail)

    def test_host_window_always_satisfies_the_rule(self):
        # Section 4 host rule for every selection a list can have, including > 20 entries.
        for count in (1, 2, 19, 20, 21, 22, 40, 45, 300):
            for index in range(count):
                for extra in ({}, {"first": 0}, {"first": index}, {"first": max(0, index - 25)}):
                    ring = _frame(v4_frame(ring={"style": "selection", "value": 0, "index": index,
                                                 "count": count, **extra}), P4)["ring"]
                    first = ring.get("first", 0)
                    if not (0 <= first <= index < first + 20 and (count > 20 or first == 0)):
                        self.fail(f"count {count} index {index} {extra}: first {first}")
                    if "first" not in extra or not (extra["first"] <= index < extra["first"] + 20
                                                    and (count > 20 or extra["first"] == 0)):
                        self.assertEqual(first, presentation.window_first(index, count))
        # An off/level ring's index is unused; one no window can hold is reset, never rejected.
        for style, count in (("off", 0), ("off", 5), ("level", 101)):
            ring = _frame(v4_frame(ring={"style": style, "value": 0, "index": 400, "count": count}), P4)["ring"]
            self.assertEqual((ring["index"], ring.get("first", 0)), (0, 0))

    def test_v4_buttons_always_carry_an_icon(self):
        buttons = v4_frame()["buttons"]
        buttons[0] = {"label": "Back", "enabled": True}
        buttons[1] = {**buttons[1], "icon": "stop"}
        sent = _frame(v4_frame(buttons=buttons), P4)["buttons"]
        self.assertEqual([b["icon"] for b in sent], ["", "", "win", "play"])
        legacy = _frame(v4_frame(buttons=buttons), P2)["buttons"]
        self.assertNotIn("icon", legacy[0], "presentation < 4 keeps the legacy shape (icon optional)")

    def test_transport_mask_bounds(self):
        ring = {"style": "transport", "value": 0, "index": 1, "count": 3}
        self.assertEqual(_frame(v4_frame(ring={**ring, "unavailable": 0b101}), P4)["ring"]["unavailable"], 5)
        self.assertNotIn("unavailable", _frame(v4_frame(ring={**ring, "unavailable": 8}), P4)["ring"])

    def test_feedback_validation(self):
        for good in ({"kind": "ok", "seq": 1}, {"kind": "err", "seq": 0x7FFFFFFF}):
            self.assertEqual(_frame(v4_frame(feedback=good), P4)["feedback"], good)
        extra = _frame(v4_frame(feedback={"kind": "ok", "seq": 3, "note": "x"}), P4)["feedback"]
        self.assertEqual(extra, {"kind": "ok", "seq": 3})
        for bad in ({"kind": "ok"}, {"kind": "info", "seq": 1}, {"kind": "ok", "seq": 0x80000000},
                    {"kind": "ok", "seq": True}, "ok", None):
            with self.subTest(bad=bad):
                self.assertNotIn("feedback", _frame(v4_frame(feedback=bad), P4))


class GatingTests(unittest.TestCase):
    def test_presentation_2_strips_v4_and_keeps_legacy_fields(self):
        result = _frame(v4_frame(), P2)
        for name in ("restLayout", "heading", "meta", "titleTone", "metaTone", "statusTone", "page",
                     "artDim", "feedback"):
            self.assertNotIn(name, result)
        self.assertEqual(set(result["ring"]), {"style", "value", "index", "count"})
        for name in ("counter", "volumeCaption", "confirmedVolume", "volumeVisible", "ledStyle", "layout"):
            self.assertIn(name, result)
        self.assertEqual((result["title"], result["subtitle"]), ("Deja Vu", "Beyonce"))
        # Colour kept when valid, derived from the tone rule when absent (cc4 requires it).
        self.assertEqual([b["color"] for b in result["buttons"]], [1, 0xF0EEE7, 0xF0EEE7, 0x66C991])
        self.assertEqual(result["artKey"], "", "no artwork capability: never name a cover")
        self.assertEqual(_frame(v4_frame(layout="notice"), P2)["layout"], "nowPlaying")
        self.assertEqual(_frame(v4_frame(), {})["title"], "Deja Vu", "no capabilities means legacy ASCII")

    def test_presentation_3_keeps_art_key_when_artwork_is_advertised(self):
        caps = {"controlCenter": 1, "presentation": 3, "artwork": ART}
        result = _frame(v4_frame(layout="notice"), caps)
        self.assertEqual((result["artKey"], result["layout"]), ("al_1", "nowPlaying"))
        self.assertNotIn("heading", result)
        self.assertEqual(result["title"], "Deja Vu")

    def test_presentation_4_keeps_advertised_glyphs_and_transliterates_the_rest(self):
        text = "Beyoncé — Déjà Vu… “Straße” · Łódź • ǅ Ω 🎵"
        result = _frame(v4_frame(title=text), P4)
        self.assertEqual(result["title"], "Beyoncé — Déjà Vu… “Straße” · Łódź • Dz ? ?")
        # Without a glyphs capability everything is ASCII (Ł has no decomposition).
        self.assertEqual(_frame(v4_frame(title=text), {"presentation": 4})["title"],
                         "Beyonce - Deja Vu... \"Strasse\" / ?odz / Dz ? ?")
        self.assertEqual(_frame(v4_frame(title="Café"), P4)["title"], "Café")
        self.assertEqual(_frame(v4_frame(heading="RECENT · P2"), P4)["heading"], "RECENT · P2")

    def test_v4_slimming(self):
        result = _frame(v4_frame(page=0, artDim=False, heading="", meta="", artKey="",
                                 feedback={"kind": "ok", "seq": 2}), P4)
        for name in ("titleTone", "metaTone", "statusTone", "page", "artDim", "heading", "meta", "artKey",
                     "counter", "volumeCaption", "confirmedVolume", "restLayout", "volumeVisible"):
            self.assertNotIn(name, result)
        self.assertNotIn("color", result["buttons"][0])
        ring = result["ring"]
        self.assertEqual(set(ring), {"style", "value", "index", "count", "colors", "unavailable", "moreIndex"})
        # Non-default values survive.
        kept = _frame(v4_frame(titleTone="muted", metaTone="error", statusTone="success", artDim=True), P4)
        self.assertEqual((kept["titleTone"], kept["metaTone"], kept["statusTone"], kept["artDim"], kept["page"]),
                         ("muted", "error", "success", True, 1))
        # Home keeps its caption, confirmed volume, rest layout and legacy visibility.
        home = _frame(v4_frame(mode="VOLUME", layout="volume", restLayout="idle", volumeVisible=True,
                               ring={"style": "level", "value": 30, "index": 0, "count": 101,
                                     "external": True, "moreIndex": -1}), P4)
        self.assertEqual((home["volumeCaption"], home["confirmedVolume"], home["restLayout"], home["volumeVisible"]),
                         ("Night Drive", 28, "idle", True))
        self.assertEqual(home["ring"], {"style": "level", "value": 30, "index": 0, "count": 101, "external": True})
        # Accents only travel in colour mode on a selection ring.
        self.assertNotIn("colors", _frame(v4_frame(ledStyle="white"), P4)["ring"])
        self.assertNotIn("colors", _frame(v4_frame(ring={"style": "level", "value": 1, "index": 0, "count": 101,
                                                         "colors": [1]}), P4)["ring"])

    def test_bridge_gates_on_negotiated_capabilities(self):
        for caps, expect_heading in ((P2, False), (P4, True)):
            with self.subTest(presentation=caps["presentation"]), tempfile.TemporaryDirectory() as temp:
                clock = Clock()
                serial = FakeSerial(clock)
                bridge = DeviceBridge(temp, lambda port: serial, request_timeout=0.1, autostart=False, clock=clock)
                bridge._connect("COM-FAKE")
                bridge.capabilities = dict(caps)
                bridge._enter({**control(), "frame": v4_frame()})
                self.assertEqual("heading" in serial.writes[-1]["control"]["frame"], expect_heading)
                bridge._frame({**v4_frame(), "id": 1})
                sent = serial.writes[-1]["frame"]
                self.assertEqual("heading" in sent, expect_heading)
                self.assertEqual("color" in sent["buttons"][3], not expect_heading)


class IconKeyTests(unittest.TestCase):
    """ARTWORK2.md section 6 on the host: validated like artKey, gated, slimmed, budgeted."""

    def setUp(self):
        device._strip_logged.clear()

    def windows(self, **extra):
        value = v4_frame(mode="WINDOWS", layout="windows", title="Research notes", subtitle="Chrome",
                         ring={"style": "selection", "value": 0, "index": 2, "count": 11})
        value.update(extra)
        return value

    def test_valid_keys_are_kept_on_windows_with_artwork2(self):
        for key in (ICON_KEY, "x", "Z" * 24, "a-b_c"):
            with self.subTest(key=key):
                sent = _frame(self.windows(iconKey=key), A2)
                self.assertEqual(sent["iconKey"], key)
                self.assertEqual(contract_violations(sent, A2), [])
                self.assertEqual(_frame(deepcopy(sent), A2), sent, "a fixed point")

    def test_malformed_keys_are_stripped_and_logged_never_raised(self):
        for key in ("k" * 25, "a/b", "a b", "\u00e4", "a\nb", None, 7, True, ["a"], {"a": 1}):
            with self.subTest(key=key):
                device._strip_logged.clear()
                with self.assertLogs("control_center.device", "WARNING") as logs:
                    sent = _frame(self.windows(iconKey=key), A2)
                self.assertNotIn("iconKey", sent)
                self.assertEqual(sent["title"], "Research notes", "the rest of the frame is sent")
                self.assertTrue(any("iconKey" in line for line in logs.output))
                if isinstance(key, str) and len(key) > 2:
                    self.assertFalse(any(key in line for line in logs.output), "the value is never logged")

    def test_gating_strips_silently(self):
        unavailable = deepcopy(A2)
        unavailable["artwork2"]["available"] = False
        for caps, frame in ((P4, self.windows()), (P2, self.windows()), (unavailable, self.windows()),
                            ({**A2, "presentation": 3}, self.windows()),
                            (A2, v4_frame()), (A2, v4_frame(mode="VOLUME", layout="nowPlaying")),
                            (A2, self.windows(layout="notice"))):
            with self.subTest(caps=sorted(caps), layout=frame.get("layout")):
                with self.assertNoLogs("control_center.device", "WARNING"):
                    sent = _frame({**frame, "iconKey": ICON_KEY}, caps)
                self.assertNotIn("iconKey", sent)
                self.assertEqual(sent, _frame(frame, caps), "nothing else changes")

    def test_layout_derived_from_mode(self):
        legacy = self.windows()
        del legacy["layout"]
        self.assertEqual(_frame({**legacy, "iconKey": ICON_KEY}, A2)["iconKey"], ICON_KEY)
        home = v4_frame(mode="VOLUME")
        del home["layout"]
        self.assertNotIn("iconKey", _frame({**home, "iconKey": ICON_KEY}, A2))

    def test_empty_key_is_slimmed(self):
        sent = _frame(self.windows(iconKey=""), A2)
        self.assertNotIn("iconKey", sent)
        self.assertEqual(sent, _frame(self.windows(), A2))

    def test_art_key_is_unchanged_with_artwork2(self):
        # artKey names either kind of cover (section 2): a 24-character JPEG key passes as before.
        jpeg_key = "0123456789abcdef01234567"
        self.assertEqual(_frame(v4_frame(artKey=jpeg_key), A2)["artKey"], jpeg_key)
        self.assertNotIn("artKey", _frame(v4_frame(artKey=""), A2))


class MultibyteTests(unittest.TestCase):
    def test_truncation_never_splits_a_code_point(self):
        cases = {"title": ("a" + "…" * 32, "a" + "…" * 31), "heading": ("…" * 11, "…" * 10),
                 "mode": ("É" * 13, "É" * 12), "status": ("ł" * 33, "ł" * 32),
                 "meta": ("é" * 48, "é" * 48), "volumeCaption": ("“" * 33, "“" * 32)}
        for name, (text, expected) in cases.items():
            with self.subTest(field=name):
                value = v4_frame(mode="VOLUME", layout="nowPlaying")  # Home keeps volumeCaption
                value[name] = text
                stored = _frame(value, P4)[name]
                self.assertEqual(stored, expected)
                self.assertLessEqual(len(stored.encode()), presentation.TEXT_CAPACITY[name])
        buttons = v4_frame()["buttons"]
        buttons[0] = {**buttons[0], "label": "a" + "é" * 8}
        self.assertEqual(_frame(v4_frame(buttons=buttons), P4)["buttons"][0]["label"], "a" + "é" * 7)
        for text in ("家庭" * 40, "🎵" * 40):
            stored = _frame(v4_frame(title=text), P4)["title"]
            self.assertLessEqual(len(stored.encode()), 96)
            self.assertNotIn("�", stored)

    def test_del_and_controls_are_never_sent_as_glyphs(self):
        # U+007F is ASCII but not a glyph (U+0020-007E); C1 controls are outside every set.
        self.assertEqual(device._lcd_text("a\x7fb\x85c"), "a?b?c")
        for caps in (P4, {"presentation": 4}, P2):
            with self.subTest(presentation=caps["presentation"], glyphs=caps.get("glyphs")):
                buttons = deepcopy(v4_frame()["buttons"])
                buttons[0]["label"] = "B\x7f"
                out = _frame(v4_frame(title="a\x7fb", status="x\x7f", buttons=buttons), caps)
                self.assertEqual((out["title"], out["status"], out["buttons"][0]["label"]), ("a?b", "x?", "B?"))
                self.assertEqual(contract_violations(out, caps), [])
                self.assertEqual(_frame(v4_frame(title="a\x85b"), caps)["title"], "a?b")

    def test_utf8_truncate_helper(self):
        self.assertEqual(presentation.utf8_truncate("ab€", 4), "ab")
        self.assertEqual(presentation.utf8_truncate("ab€", 5), "ab€")
        self.assertEqual(presentation.utf8_truncate("🎵🎵", 7), "🎵")


class ArtSerial(FakeSerial):
    """Line-assembling fake knob (works behind PacedSerial) that acknowledges art lines."""
    timeout = 0.05

    def __init__(self, clock, *, blocking=False, ack_art=True):
        super().__init__(clock, capabilities=False)  # replies with v4 capabilities below
        self.pending = b""
        self.blocking = blocking
        self.ack_art = ack_art
        self.total = 0

    def __setattr__(self, name, value):
        if name == "timeout":
            raise AssertionError("The bridge must never change the port timeout")
        super().__setattr__(name, value)

    def write(self, raw):
        self.pending += raw
        while b"\n" in self.pending:
            line, self.pending = self.pending.split(b"\n", 1)
            super().write(line + b"\n")
            message = self.writes[-1]
            if message == {"capabilities": "?"}:
                self.inject({"capabilities": {"controlCenter": 1, "presentation": 4,
                                              "glyphs": "latin-ext-a", "artwork": ART}})
            elif "art" in message and self.ack_art:
                art = message["art"]
                if art["op"] == "begin":
                    self.total, offset = art["bytes"], 0
                elif art["op"] == "data":
                    offset = art["offset"] + len(base64.b64decode(art["data"]))
                else:
                    offset = self.total
                self.inject({"artAck": {"id": art["id"], "key": art["key"], "op": art["op"], "offset": offset}})
        return len(raw)

    def read(self, size):
        if not self.blocking:
            return super().read(size)
        # pyserial semantics: read(size) returns early only once `size` bytes are
        # buffered; otherwise it waits for the port's 50 ms timeout.
        self.reads.append(size)
        self.clock.now += self.timeout if len(self.buffer) < size else 0.0005
        data = bytes(self.buffer[:size])
        del self.buffer[:size]
        return data


class ArtBridgeCase(unittest.TestCase):
    def make_bridge(self, **serial_options):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.serial = ArtSerial(self.clock, **serial_options)
        self.paced = PacedSerial(self.serial, sleep=lambda _: None)
        self.addCleanup(lambda: self.assertNotIn("timeout", vars(self.paced),
                                                 "never set a timeout through PacedSerial"))
        self.bridge = DeviceBridge(self.temp.name, lambda port: self.paced,
                                   request_timeout=0.2, autostart=False, clock=self.clock)
        self.bridge._connect("COM-FAKE")
        self.assertEqual(self.bridge.capabilities["presentation"], 4)
        self.bridge._enter({**control(), "frame": {**v4_frame(), "artKey": "coverA"}})
        self.events()
        return self.bridge

    def events(self):
        output = []
        while not self.bridge.events.empty():
            output.append(self.bridge.events.get_nowait())
        return output

    def queue(self, data=None):
        self.bridge._queue_artwork({"id": 1, "key": "coverA", "data": data if data is not None else b"\x12\x34" * 14400})


class ArtworkRobustnessTests(ArtBridgeCase):
    def test_size_or_format_mismatch_is_an_artwork_error_only(self):
        self.make_bridge()
        for data in (b"\x00" * 10, "not bytes", bytes(240 * 240 * 2)):
            self.queue(data)
            events = self.events()
            self.assertEqual([(e["kind"], e["reason"]) for e in events], [("artwork-error", "size")])
            self.assertIsNone(self.bridge._artwork)
        self.bridge.capabilities["artwork"] = {**ART, "format": "RGB888"}
        self.queue()
        self.assertEqual([(e["kind"], e["reason"]) for e in self.events()], [("artwork-error", "unsupported")])
        self.bridge._queue_artwork(["not", "a", "payload"])
        self.assertEqual(self.events()[0]["reason"], "invalid")
        self.bridge._queue_artwork({"id": 1, "key": "", "data": b""})
        self.assertEqual(self.events(), [], "an empty key is 'no art', not an error")
        self.assertEqual(self.bridge.ready_id, 1)

    def outstanding_chunk(self):
        self.serial.ack_art = False
        self.queue()
        self.bridge._artwork_step()  # begin
        self.bridge._consume({"artAck": {"id": 1, "key": "coverA", "op": "begin", "offset": 0}})
        self.bridge._artwork_step()  # data 0, now outstanding
        self.assertEqual(self.serial.writes[-1]["art"]["op"], "data")
        self.assertIsNotNone(self.bridge._artwork["waiting"])

    def test_parse_art_ack_aborts_without_disarming(self):
        self.make_bridge()
        self.outstanding_chunk()
        self.bridge._consume({"artAck": {"id": 1, "key": "other", "op": "parse", "error": "parse"}})
        self.assertIsNotNone(self.bridge._artwork, "a parse reply for another key is not ours")
        self.bridge._consume({"artAck": {"op": "parse", "error": "parse"}})  # id/key not recovered
        event, = self.events()
        self.assertEqual((event["kind"], event["reason"], event["transient"], event["retrying"]),
                         ("artwork-error", "parse", True, False))
        self.assertIsNone(self.bridge._artwork)
        self.assertEqual(self.bridge.ready_id, 1)

    def test_any_error_ack_for_the_active_transfer_aborts(self):
        self.make_bridge()
        self.outstanding_chunk()
        self.bridge._consume({"artAck": {"id": 1, "key": "coverA", "op": "commit", "error": "Stale artwork selection"}})
        event, = self.events()
        self.assertEqual((event["reason"], event["transient"]), ("rejected", False))
        self.assertIsNone(self.bridge._artwork)
        self.assertNotIn("Stale", event["message"], "firmware text is not relayed")

    def test_bare_parse_error_during_outstanding_chunk_retries_once(self):
        self.make_bridge()
        self.outstanding_chunk()
        self.serial.inject({"error": "JSON parse error", "msg": "InvalidInput"})
        self.bridge._read()  # must not raise
        event, = self.events()
        self.assertEqual((event["kind"], event["reason"], event["retrying"]), ("artwork-error", "parse", True))
        self.assertEqual(self.bridge.ready_id, 1)
        self.bridge._artwork_step()
        self.assertEqual(self.serial.writes[-1]["art"]["op"], "begin", "the transfer restarts once")
        self.bridge._consume({"artAck": {"id": 1, "key": "coverA", "op": "begin", "offset": 0}})
        self.bridge._artwork_step()
        self.bridge._consume({"error": "Command too large"})
        event, = self.events()
        self.assertEqual((event["retrying"], event["transient"]), (False, False))
        self.assertIsNone(self.bridge._artwork)
        self.assertEqual(self.bridge.ready_id, 1)
        # With nothing outstanding the same reply is fatal again, exactly as before.
        with self.assertRaises(OSError):
            self.bridge._consume({"error": "JSON parse error"})

    def test_non_art_errors_stay_fatal(self):
        self.make_bridge()
        with self.assertRaises(OSError):
            self.bridge._consume({"error": "Invalid control frame"})
        self.outstanding_chunk()
        with self.assertRaises(OSError):
            self.bridge._consume({"error": "Invalid control frame"})

    def test_timeout_is_transient_and_non_fatal(self):
        self.make_bridge()
        self.outstanding_chunk()
        self.clock.now += 0.21
        self.bridge._artwork_step()
        event, = self.events()
        self.assertEqual((event["reason"], event["transient"], event["retrying"]), ("timeout", True, False))
        self.assertEqual(self.bridge.ready_id, 1)


class ArtLineRaceTests(ArtBridgeCase):
    """The reply to an art line may arrive after the host dropped that transfer (section 7)."""
    COVER_B = {"id": 1, "key": "coverB", "data": b"\x56\x78" * 14400}

    def setUp(self):
        self.make_bridge()
        self.serial.ack_art = False
        self.queue()
        self.bridge._artwork_step()  # begin
        self.bridge._consume({"artAck": {"id": 1, "key": "coverA", "op": "begin", "offset": 0}})
        self.bridge._artwork_step()  # data chunk 0: its reply is still in flight
        self.assertEqual(self.serial.writes[-1]["art"]["op"], "data")
        self.events()

    def late_bare_error(self):
        self.serial.inject({"error": "JSON parse error", "msg": "InvalidInput"})
        self.bridge._read()  # must not raise (a raise here is a fatal disconnect in _run)

    def assert_art_only(self, key="coverA", retrying=False):
        event, = self.events()
        self.assertEqual((event["kind"], event["key"], event["reason"], event["retrying"]),
                         ("artwork-error", key, "parse", retrying))
        self.assertEqual(self.bridge.control_id, self.bridge.ready_id)
        self.assertIsNotNone(self.bridge.ready_id)

    def assert_nothing_outstanding(self):
        with self.assertRaises(OSError):
            self.bridge._consume({"error": "JSON parse error"})

    def test_selection_change_drops_the_transfer_then_the_reply_arrives(self):
        self.bridge._frame({**v4_frame(), "id": 1, "artKey": "coverB"})
        self.assertIsNone(self.bridge._artwork)
        self.late_bare_error()
        self.assert_art_only()
        self.assert_nothing_outstanding()

    def test_art_cleared_by_a_frame_then_the_reply_arrives(self):
        self.bridge._frame({**v4_frame(), "id": 1, "artKey": ""})
        self.late_bare_error()
        self.assert_art_only()
        self.assert_nothing_outstanding()

    def test_timeout_abort_then_the_late_reply_arrives(self):
        self.clock.now += 0.21
        self.bridge._artwork_step()
        self.assertEqual(self.events()[0]["reason"], "timeout")
        self.late_bare_error()
        self.assert_art_only()
        self.assert_nothing_outstanding()

    def test_new_entry_while_the_chunk_is_in_flight(self):
        self.serial.inject({"error": "JSON parse error", "msg": "InvalidInput"})  # already on the wire
        self.bridge._enter({**control(ident=2), "frame": {**v4_frame(), "artKey": "coverA"}})
        self.assertEqual(self.bridge.ready_id, 2)
        events = self.events()
        self.assertEqual([e["kind"] for e in events], ["artwork-error", "ready"])
        self.assertEqual((events[0]["id"], events[0]["key"], events[0]["retrying"]), (1, "coverA", False))

    def test_replies_are_attributed_in_line_order(self):
        self.bridge._frame({**v4_frame(), "id": 1, "artKey": "coverB"})
        self.bridge._queue_artwork(dict(self.COVER_B))
        self.bridge._artwork_step()  # coverB begin; coverA's chunk reply is still ahead of it
        self.late_bare_error()
        self.assert_art_only("coverA")
        self.assertEqual((self.bridge._artwork["key"], self.bridge._artwork["waiting"][0]), ("coverB", "begin"),
                         "an older line's failure never aborts the new transfer")
        self.late_bare_error()  # this one answers coverB's begin: abort with one retry
        self.assert_art_only("coverB", retrying=True)
        self.assertEqual(self.bridge._artwork["stage"], "begin")

    def test_parse_ack_without_id_for_a_dropped_line_is_reported_only(self):
        self.bridge._frame({**v4_frame(), "id": 1, "artKey": "coverB"})
        self.bridge._queue_artwork(dict(self.COVER_B))
        self.bridge._artwork_step()
        self.bridge._consume({"artAck": {"op": "parse", "error": "parse"}})
        self.assert_art_only("coverA")
        self.assertIsNotNone(self.bridge._artwork["waiting"])

    def test_an_unanswered_line_expires(self):
        self.clock.now += DeviceBridge.ART_LINE_GRACE * self.bridge.request_timeout + 0.01
        self.bridge._artwork_step()  # timeout abort
        self.events()
        self.assert_nothing_outstanding()

    def test_run_loop_survives_the_race(self):
        # End to end through _run (whose handler would emit `error` and disconnect).
        self.serial.inject({"error": "JSON parse error", "msg": "InvalidInput"})
        self.bridge.commands.put(("frame", {**v4_frame(), "id": 1, "artKey": "coverB"}))
        self.bridge.commands.put(("close", None))
        self.bridge._run()
        kinds = [e["kind"] for e in self.events()]
        self.assertEqual(kinds[0], "artwork-error")
        self.assertNotIn("error", kinds)
        self.assertEqual(self.serial.writes[-1], {"release": True}, "closed normally, not after a failure")


class ReadPacingTests(ArtBridgeCase):
    def loop_once(self):
        self.bridge._heartbeat()
        self.bridge._read()
        self.bridge._artwork_step()

    def test_idle_reads_are_bounded_by_the_port_timeout(self):
        self.make_bridge(blocking=True)
        self.serial.reads.clear()
        start = self.clock.now
        for _ in range(1000):
            if self.clock.now - start >= 1.0:
                break
            self.loop_once()
        else:
            self.fail("idle loop spun without the port timeout")
        self.assertLessEqual(len(self.serial.reads), 21)
        self.assertTrue(all(size >= 1 for size in self.serial.reads), "never a zero-byte/zero-timeout read")

    def test_art_transfer_needs_about_one_read_per_chunk(self):
        self.make_bridge(blocking=True)
        self.serial.reads.clear()
        self.queue()
        lines = 2 + math.ceil(28800 / 384)
        start = self.clock.now
        for _ in range(10 * lines):
            self.loop_once()
            if self.bridge._artwork is None:
                break
        self.assertEqual(self.events()[-1]["kind"], "artwork-ready")
        self.assertLessEqual(len(self.serial.reads), lines + 2)
        self.assertTrue(all(1 <= size <= DeviceBridge.READ_LIMIT for size in self.serial.reads))
        # Buffered acknowledgements are consumed at once: no 50 ms stall per chunk.
        self.assertLess(self.clock.now - start, 0.5)

    def test_buffered_bytes_are_read_in_one_call(self):
        self.make_bridge()
        for position in range(2, 12):
            self.serial.inject({"id": 1, "p": position})
        self.serial.reads.clear()
        self.bridge._read()
        self.assertEqual(len(self.serial.reads), 1)
        self.assertEqual([e["position"] for e in self.events()], list(range(2, 12)))


def encoded_line(sent):
    return (json.dumps({"frame": sent}, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            + "\n").encode("utf-8")


class BudgetTests(unittest.TestCase):
    TITLE = ("Quarterly planning — draft review " * 4).encode()[:96].decode("utf-8", "ignore")

    def windows_frame(self, title, app):
        """Section 8 worst case: 40 windows (20 sent), colour mode, a failed-switch flash."""
        c = Controller()
        c.state.update(online=True)
        items = [{"id": str(i), "title": title, "app": app, "available": i % 2 == 0} for i in range(40)]
        c.screen = Screen(mode="windows", index=30, status="", windows={"items": items, "origin": {}})
        c.feedback_seq = 0x7FFFFFFF - 1  # the failed switch below flashes with the largest seq
        c.complete(c.request("windows_activate", item=items[30]), False)
        self.assertEqual(c.feedback, {"kind": "err", "seq": 0x7FFFFFFF})
        value = {"id": 0x7FFFFFFF, **c.frame()}
        first = presentation.window_first(30, 40)
        value.update(ledStyle="color", artKey="", meta="Didn’t come forward · retry", metaTone="error",
                     titleTone="muted")
        value["ring"].update(first=first, colors=[0xFFFFFF] * 20, unavailable=(1 << 20) - 1)
        sent = _frame(value, P4)
        self.assertEqual(len(sent["ring"]["colors"]), 20)
        self.assertEqual(contract_violations(sent, P4), [])
        self.assertEqual(len(encoded_line(sent)), device.frame_line_bytes(sent))
        return sent

    def worst_case_line(self, app):
        title = self.TITLE
        self.assertGreaterEqual(len(title.encode()), 94)
        sent = self.windows_frame(title, app)
        self.assertEqual(len(sent["title"].encode()), len(title.encode()))
        self.assertEqual(sent["subtitle"], presentation.utf8_truncate(app, 96), "what the v4 renderer draws is kept")
        return sent, encoded_line(sent)

    def test_worst_case_windows_frame_fits_the_budget(self):
        # App names are capped by the 96-byte detail/subtitle capacity; the longest
        # (ASCII and multibyte) and an overlong one are the worst cases.
        for app in ("Microsoft Visual Studio Code Insiders", "A" * 60, "A" * 96, "É" * 48, "Ł" * 200):
            with self.subTest(app_bytes=len(app.encode())):
                sent, line = self.worst_case_line(app)
                gaps = math.ceil(len(line) / PacedSerial.CHUNK_BYTES) - 1
                serial_ms = gaps * PacedSerial.GAP_SECONDS * 1000
                self.assertLessEqual(len(line), presentation.FRAME_BUDGET_BYTES,
                                     f"{len(line)} B worst-case frame; paced serial time {serial_ms:.0f} ms")
                self.assertEqual(len(line), device.frame_line_bytes(sent))
                # Recorded per-frame serial time at 64 B / 5 ms pacing (write time itself excluded).
                self.assertLessEqual(serial_ms, 90, f"{len(line)} B -> {serial_ms:.0f} ms")

    def test_worst_case_windows_frame_with_an_icon_key_fits_the_budget(self):
        # ARTWORK2.md section 6: the 1,100 B budget is unchanged; a key adds at most 12 + 24 + 1
        # bytes and the section 8 trim order absorbs it without shortening drawn text.
        for key in (ICON_KEY, "k" * 24):
            for app in ("Microsoft Visual Studio Code Insiders", "A" * 96, "\u00c9" * 48):
                with self.subTest(key=len(key), app_bytes=len(app.encode())):
                    plain = self.windows_frame(self.TITLE, app)
                    value = {**plain, "iconKey": key, "detail": app, "value": self.TITLE, "target": "DESKTOP"}
                    sent = _frame(value, A2)
                    self.assertEqual(sent["iconKey"], key)
                    self.assertLessEqual(len(encoded_line(sent)), presentation.FRAME_BUDGET_BYTES)
                    self.assertEqual((sent["title"], sent["subtitle"]), (plain["title"], plain["subtitle"]))
                    self.assertEqual(contract_violations(sent, A2), [])

    def test_worst_case_frames_with_every_alive_field_fit_the_budget(self):
        # ALIVE.md section 3 (1.0.0-cc5.4): the 1,100 B budget still holds with clock, playing,
        # progress, ledDrive and ledDither all present. On an alive knob the host reserves the
        # longest value of every latched field (the bridge adds them at send time), and the legacy
        # trim absorbs them without shortening drawn text.
        from test_cc_controller import state
        alive = {**A2, "alive": {"version": 1, "fps": 60, "drive": 150}}
        latched = presentation.ALIVE_LATCHED_WORST
        sizes = {}
        for app in ("Microsoft Visual Studio Code Insiders", "A" * 96, "É" * 48):
            with self.subTest(frame="windows", app_bytes=len(app.encode())):
                plain = self.windows_frame(self.TITLE, app)
                value = {**plain, "detail": app, "value": self.TITLE, "target": "DESKTOP"}
                sent = _frame(value, alive)
                line = encoded_line({**sent, **latched})
                self.assertLessEqual(len(line), presentation.FRAME_BUDGET_BYTES)
                self.assertEqual((sent["title"], sent["subtitle"]), (plain["title"], plain["subtitle"]))
                sizes[f"windows, {len(app.encode())} B app"] = len(line)
        home = Controller()
        home.complete(home.request("state"), state(title=self.TITLE, artist="É" * 48, playback="PLAYING"))
        home.feedback_seq = 0x7FFFFFFF - 1
        home._feedback("ok")
        for reveal in (False, True):
            with self.subTest(frame="home", reveal=reveal):
                if reveal:
                    home.turn(1)
                value = {"id": 0x7FFFFFFF, **home.frame(), "ledStyle": "color", "artKey": "k" * 24,
                         "playing": True}
                value["feedback"] = {**value["feedback"], "skip": 1}
                sent = _frame(value, alive)
                self.assertEqual((sent["playing"], sent["feedback"]["skip"]), (True, 1))
                line = encoded_line({**sent, **latched})
                self.assertLessEqual(len(line), presentation.FRAME_BUDGET_BYTES)
                self.assertEqual({k: sent[k] for k in ("title", "subtitle", "volumeCaption", "value")},
                                 {k: _frame(deepcopy(value), A2)[k] for k in ("title", "subtitle", "volumeCaption",
                                                                             "value")},
                                 "drawn text as without alive")
                sizes[f"home{', volume reveal' if reveal else ''}"] = len(line)
        print("\n[alive budget] worst-case lines with every section 3 field: "
              + ", ".join(f"{name} {size} B" for name, size in sizes.items()))

    def test_budget_trims_only_legacy_text_and_only_when_needed(self):
        sent, _ = self.worst_case_line("Microsoft Visual Studio Code Insiders")
        self.assertEqual(sent["detail"], "Microsoft Visual Studio Code Insiders", "under budget: unchanged")
        with self.assertLogs("control_center.device", "WARNING") as logs:
            device._strip_logged.clear()
            sent, _ = self.worst_case_line("A" * 96)
        self.assertEqual((sent["detail"], sent["target"]), ("", "DESKTOP"))
        self.assertEqual(sent["value"], presentation.utf8_truncate(self.TITLE, 64), "value only when detail is not enough")
        self.assertTrue(any("detail emptied" in line for line in logs.output))
        # Presentation 2 frames are never trimmed: cc4 draws detail.
        legacy = _frame({**v4_frame(), "detail": "A" * 96, "title": "B" * 96, "subtitle": "C" * 96}, P2)
        self.assertEqual(legacy["detail"], "A" * 96)

    # JSON escapes: `"` and `\` take two bytes on the wire, so a 96-byte title made of
    # them is 192 line bytes (and its legacy `value` copy another 128).
    BS = "\\"
    ESCAPED = {"quoted title": ('"' * 96, "Microsoft Visual Studio Code Insiders"),
               "backslash title": (BS * 96, "A" * 96),
               "quoted path title": (('"C:' + BS + 'Users' + BS + 'x"') * 8, "É" * 48),
               "quoted title and app": ('"' * 96, '"' * 96),
               "backslash title and app": (BS * 96, BS * 96),
               "mixed title and app": (('"' + BS) * 48, (BS + '"' + "é") * 24)}

    def test_escaped_windows_titles_and_app_names_fit_the_budget(self):
        for name, (title, app) in self.ESCAPED.items():
            with self.subTest(case=name):
                sent = self.windows_frame(title, app)
                line = encoded_line(sent)
                self.assertLessEqual(len(line), presentation.FRAME_BUDGET_BYTES, f"{len(line)} B")
                self.assertGreater(len(line), 1000, "a real worst case, not a trivially small frame")
                self.assertEqual((sent["value"], sent["detail"]), ("", ""), "the legacy title/app copies go first")
                self.assertTrue(sent["title"] and title.startswith(sent["title"]))
                self.assertTrue(sent["subtitle"] and presentation.utf8_truncate(app, 96).startswith(sent["subtitle"]))
                self.assertEqual(_frame(deepcopy(sent), P4), sent, "a fixed point")

    def test_escapes_in_one_field_only_trim_legacy_text(self):
        # The legacy value/detail/target copies absorb one escaped field: nothing drawn changes.
        for name in ("quoted title", "backslash title", "quoted path title"):
            title, app = self.ESCAPED[name]
            with self.subTest(case=name):
                sent = self.windows_frame(title, app)
                self.assertEqual(sent["title"], presentation.utf8_truncate(title, 96))
                self.assertEqual(sent["subtitle"], presentation.utf8_truncate(app, 96))

    def test_escapes_in_title_and_app_shorten_the_drawn_text_as_a_last_resort(self):
        title, app = self.ESCAPED["quoted title and app"]
        with self.assertLogs("control_center.device", "WARNING") as logs:
            device._strip_logged.clear()
            sent = self.windows_frame(title, app)
        size = device.frame_line_bytes(sent)
        self.assertTrue(presentation.FRAME_BUDGET_BYTES - 2 < size <= presentation.FRAME_BUDGET_BYTES,
                        f"shortened just enough: {size} B")
        self.assertLessEqual(abs(len(sent["title"]) - len(sent["subtitle"])), 1, "the longest text shrinks first")
        for name in ("title", "subtitle"):
            self.assertTrue(any(f"field {name} shortened" in line for line in logs.output), name)
        self.assertFalse(any("over the size budget" in line for line in logs.output))

    def test_escaped_home_and_recent_frames_fit_and_home_keeps_its_digits(self):
        from test_cc_controller import state
        for text in ('"' * 96, self.BS * 96):
            with self.subTest(text=text[0]):
                home = Controller()
                home.complete(home.request("state"), state(title=text, artist=text, playback="PAUSED_PLAYBACK",
                                                           can_play=True))
                home.feedback_seq = 0x7FFFFFFF - 1
                home._feedback("err")
                for reveal in (False, True):
                    if reveal:
                        home.turn(1)
                    value = {"id": 0x7FFFFFFF, **home.frame(), "ledStyle": "color", "artKey": "a" * 64}
                    sent = _frame(value, P4)
                    self.assertLessEqual(len(encoded_line(sent)), presentation.FRAME_BUDGET_BYTES)
                    self.assertEqual(sent["value"], "29%" if reveal else "28%", "Home draws value")
                    self.assertEqual(contract_violations(sent, P4), [])
                # Desktop v7 (K3 5.2): the flat Recently Added list reached by Browse, not v6's
                # Screen(pages=...) (kept only as a compat shim); item 5 is unavailable (artDim).
                recent = Controller()
                recent.complete(recent.request("state"), state())
                recent.button(1, recent.control_id)
                (browse,) = [e for e in recent.drain() if e["kind"] == "recent"]
                items = [{"id": str(i), "title": text, "artist": text, "kind": "album", "available": i != 5}
                         for i in range(10)]
                recent.complete(browse["request"], {"items": items, "offset": 0, "limit": 25, "total": 10,
                                                    "complete": True, "visit": recent.recent.visit})
                recent.position(5, recent.control_id)
                self.assertEqual((recent.screen.mode, recent.frame()["layout"], recent.frame().get("artDim")),
                                 ("recent", "recent", True))
                recent.feedback_seq = 0x7FFFFFFF - 1
                recent._feedback("err")
                value = {"id": 0x7FFFFFFF, **recent.frame(), "ledStyle": "color", "artKey": "a" * 64}
                value["ring"]["colors"] = [0xFFFFFF] * value["ring"]["count"]
                sent = _frame(value, P4)
                self.assertLessEqual(len(encoded_line(sent)), presentation.FRAME_BUDGET_BYTES)
                self.assertEqual(sent["value"], "", "a legacy copy of the title outside Home")
                self.assertEqual((sent["artDim"], sent["ring"]["unavailable"]), (True, 1 << 5))
                self.assertEqual(contract_violations(sent, P4), [])


class OutsideTextTests(unittest.TestCase):
    """Outside metadata (Sonos titles, window captions) never makes presentation fatal."""
    CAPS = (P2, {"controlCenter": 1, "presentation": 4}, P4)

    def controllers(self):
        """Home, and the picker reached the v7 way: a knob session (set_hardware lands on Home,
        C5-2), Home's Button 4 (Win) -> windows_open -> the snapshot -> the knob's ready."""
        from test_cc_controller import state
        home = Controller()
        home.complete(home.request("state"), state(title="Morning Show\nwith Guest", artist="Radio\tOne\r\n"))
        home.drain()
        home.set_hardware(True)
        windows = Controller()
        windows.complete(windows.request("state"), state())
        windows.drain()
        windows.set_hardware(True)
        windows.drain()
        windows.device_ready(windows.control_id)
        windows.button(3, windows.control_id)
        opened = next(effect for effect in windows.drain() if effect["kind"] == "windows_open")
        windows.complete(opened["request"], {"items": [
            {"id": "1", "hwnd": 11, "pid": 2, "title": "Report\tFinal.xlsx - Excel", "app": "Excel\x7f",
             "available": True}], "index": 0, "origin": {"hwnd": 0, "pid": 0}})
        windows.drain()
        windows.device_ready(windows.control_id)
        self.assertEqual(windows.screen.mode, "windows")
        return {"home": home, "windows": windows}

    def test_clean_text_helper(self):
        self.assertEqual(presentation.clean_text("a\r\nb\tc\x7fd\x00"), "a b c d ")
        self.assertEqual(presentation.clean_text("Déjà · Vu"), "Déjà · Vu")

    def test_titles_with_controls_give_valid_frames_on_every_projection(self):
        # K3 5.7.2: the picker's knob frame carries the window title as ``title`` (v4 used ``value``).
        expected = {"home": ("title", "Morning Show with Guest"), "windows": ("title", "Report Final.xlsx - Excel")}
        for name, controller in self.controllers().items():
            for projection in (controller.frame(), controller.control()["frame"]):
                with self.subTest(screen=name):
                    field, text = expected[name]
                    self.assertEqual(projection[field], text)
                    texts = [v for v in projection.values() if isinstance(v, str)]
                    texts += [b["label"] for b in projection["buttons"]]
                    self.assertFalse([t for t in texts if any(ord(c) < 0x20 or c == "\x7f" for c in t)])
                    for caps in self.CAPS:
                        self.assertEqual(contract_violations(_frame(deepcopy(projection), caps), caps), [])

    def test_titles_with_controls_never_reach_the_fatal_error_path(self):
        for name, controller in self.controllers().items():
            for serial_type in (FakeSerial, ArtSerial):
                with self.subTest(screen=name, serial=serial_type.__name__), tempfile.TemporaryDirectory() as temp:
                    clock = Clock()
                    serial = serial_type(clock)
                    bridge = DeviceBridge(temp, lambda port: serial, request_timeout=0.1, autostart=False, clock=clock)
                    bridge.commands.put(("connect", "COM-FAKE"))
                    bridge.commands.put(("enter", {**control(), "frame": controller.control()["frame"]}))
                    bridge.commands.put(("frame", {**controller.frame(), "id": 1}))
                    bridge.commands.put(("close", None))
                    bridge._run()
                    kinds = []
                    while not bridge.events.empty():
                        kinds.append(bridge.events.get_nowait()["kind"])
                    self.assertIn("ready", kinds)
                    self.assertNotIn("error", kinds)
                    sent = [w["frame"] for w in serial.writes if "frame" in w]
                    self.assertTrue(sent, "the frame reached the knob")
                    self.assertFalse(any(ord(c) < 0x20 for c in json.dumps(sent[-1], ensure_ascii=False)))


if __name__ == "__main__":
    unittest.main()
