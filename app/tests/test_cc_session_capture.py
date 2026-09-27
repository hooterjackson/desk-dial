"""End-to-end wire capture: every line a scripted desktop-v7 session makes the real DeviceBridge write.

tests/tools/capture_session_frames.py drives the real v7 Controller + Runtime + DeviceBridge
through a knob session against a cc5.4 (presentation 5 + alive + artwork2), a cc5.3
(presentation 4 + artwork2: the PRESENTATION_V5.md section 2.2 downgrade), a cc5 (presentation 4,
v1 art) and a cc4 (presentation 2) fake knob; the artwork2 knobs sit behind the CDC receive-queue
model with COM stalls and the media store model. These tests check the recorded lines on the host
side (line limits, the frame budgets, the bridge encoding, the adapter fixed point, an independent
contract reading per presentation, coverage of the K3 grammar and the knob input of section 11)
and then replay them through the real firmware parser (harness/parse_tests.py --frames,
MSVC): every frame and control line must be accepted by the cc5.4 parser with stored text and
fields identical to the line, and the installed cc4 parser must accept every legacy line. No port,
network, window or user data is touched; the capture and the parser build live in a temporary
directory.
"""
import ast
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tests" / "tools"
for _path in (str(ROOT), str(TOOLS), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from control_center import device, presentation  # noqa: E402
from control_center.controller import PROFILES  # noqa: E402
import capture_session_frames as capture_tool  # noqa: E402
from test_cc_contract_v4 import contract_violations  # noqa: E402
import test_cc_contract_v5 as v5  # noqa: E402  (the contract's tables, written out independently)

WORK = ROOT.parent / "tools"
PARSE_TESTS = WORK.parent / "harness" / "parse_tests.py"
ARDUINOJSON = WORK.parent / "firmware" / ".pio" / "libdeps" / "nanofoc_d" / "ArduinoJson" / "src"
CL_EXE = Path("C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Tools/MSVC/14.44.35207"
              "/bin/Hostx64/x64/cl.exe")
FIRMWARE_PARSER = (PARSE_TESTS.is_file() and ARDUINOJSON.is_dir() and CL_EXE.is_file()
                   and (WORK.parent / "firmware" / "src" / "cc_frame_parse.cpp").is_file())
HOME = {"nowPlaying", "volume", "idle", "notice"}
V5_TOP = {"id", "mode", "target", "value", "detail", "status", "title", "subtitle", "counter", "activity", "layout",
          "restLayout", "heading", "meta", "titleTone", "metaTone", "statusTone", "page", "volumeVisible",
          "volumeCaption", "confirmedVolume", "ledStyle", "artKey", "artDim", "iconKey", "feedback", "buttons", "ring",
          "playing", "clock", "progress", "ledDrive", "ledDither", "reducedMotion", "ledPink", "ledVolFull"}
GRAMMAR_ICONS = {"back", "clock", "expand", "heart", "list", "next", "pause", "play", "playlists", "playnext", "prev",
                 "seek", "shuffle", "snapleft", "snapright", "switch", "tracks", "win"}   # K3 3.1, every token


def parser_text_fields():
    """parse_tests.TEXT_FIELDS, read from source (12 fields, plus iconKey from 1.0.0-cc5.3)."""
    for node in ast.parse(PARSE_TESTS.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "TEXT_FIELDS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("parse_tests.TEXT_FIELDS not found")


def frame_of(record):
    message = json.loads(record["line"])
    return message["frame"] if record["kind"] == "frame" else message["control"]["frame"]


def v5_violations(frame, caps):
    """Every way `frame` breaks PRESENTATION_V5.md sections 3-7 and 14 for a presentation-5 knob
    advertising `caps` (empty when valid): an independent reading, with test_cc_contract_v5's tables."""
    bad = []

    def need(ok, what):
        if not ok:
            bad.append(what)

    def uint(value, low, high):
        return type(value) is int and low <= value <= high
    alive = isinstance(caps.get("alive"), dict)
    need(set(frame) <= V5_TOP, f"unknown fields {sorted(set(frame) - V5_TOP)}")
    for name in ("mode", "target", "value", "detail", "status", "buttons", "ring"):
        need(name in frame, f"required {name}")
    layout = v5.layout_of(frame)
    need(layout in v5.LAYOUTS_V5, "layout token")
    for name, capacity in presentation.TEXT_CAPACITY.items():
        if name in frame:
            need(isinstance(frame[name], str) and len(frame[name].encode("utf-8")) <= capacity
                 and not any(ord(c) < 0x20 for c in frame[name]), f"{name} text")
    ring = frame["ring"]
    count, index = ring["count"], ring["index"]
    need(ring["style"] in v5.STYLES_V5 and uint(ring["value"], 0, 100) and uint(index, 0, 65535)
         and uint(count, 0, 65535), "ring required fields")
    if count > 20:                                                     # 4.2 (P5-R9)
        need("first" in ring and ring["first"] == v5.clamp(index - 10, 0, count - 20), "first by the v5 window rule")
    else:
        need("first" not in ring, "first omitted when count <= 20")
    first = ring.get("first", 0)
    window = max(0, min(20, count - first))
    if ring["style"] in ("selection", "transport"):
        need(index < count, "index < count")
    if ring["style"] == "lap":
        need(1 <= count <= v5.LAP_MAX and index < count, "lap bounds (4.3)")
    if "colors" in ring:
        need(frame.get("ledStyle") == "color" and ring["style"] == "selection" and len(ring["colors"]) <= window,
             "colors only in colour mode on a selection ring, within the window")
    if "unavailable" in ring:
        need(layout != "upnext" and 0 < ring["unavailable"] < 1 << window, "unavailable mask (never on upnext)")
    upnext = ring["style"] == "selection" and layout == "upnext"
    if "now" in ring:
        need(upnext and -1 < ring["now"] < count, "now only on upnext (4.4)")
    if "card" in ring:
        need(upnext and ring["card"] is True and count >= 2 and ring.get("now") == count - 2, "card (4.4)")
    for key, default in (("moreIndex", -1), ("external", False)):
        need(ring.get(key, "absent") != default, f"slimming: ring.{key}")
    buttons = frame["buttons"]
    need(isinstance(buttons, list) and len(buttons) == 4, "four buttons")
    for slot, button in enumerate(buttons):
        need(set(button) <= {"label", "enabled", "icon", "lit", "color"} and type(button["enabled"]) is bool
             and len(button["label"].encode("utf-8")) <= 16, f"button {slot}")
        need(button.get("icon") in v5.ICONS_V5, f"button {slot} icon")
        need(button.get("lit", "on") in ("on", "off"), f"button {slot} lit")
        if "color" in button:
            need(button.get("lit") == "on" and button["icon"] != "heart" and uint(button["color"], 1, 0xFFFFFF),
                 f"button {slot} colour only lit on (5.1)")
    feedback = frame.get("feedback")
    if feedback is not None:
        need(set(feedback) <= {"kind", "seq", "skip", "moment", "side", "color"} and feedback["kind"] in ("ok", "err")
             and uint(feedback["seq"], 1, 0x7FFFFFFF), "feedback")
        if "moment" in feedback:
            need(feedback["kind"] == "ok" and feedback["moment"] in v5.MOMENTS - {"unlike"} and "skip" not in feedback,
                 "moment (6; unlike is reserved, never sent)")
        need(("side" in feedback) == (feedback.get("moment") == "snap"), "side only with snap")
        if "color" in feedback:
            need(feedback.get("moment") in ("snap", "started") and feedback["color"] != 0, "moment colour")
    if "playing" in frame:
        need(type(frame["playing"]) is bool and layout in HOME, "playing on Home layouts only")
    latched = {"clock": lambda v: uint(v, 0, 1439), "ledDrive": lambda v: uint(v, 1, 255),
               "ledDither": lambda v: type(v) is bool, "ledVolFull": lambda v: type(v) is bool,
               "ledPink": lambda v: uint(v, 0, 0xFFFFFF), "reducedMotion": lambda v: type(v) is bool,
               "progress": lambda v: isinstance(v, dict) and uint(v.get("pos"), 0, 86400000)
               and uint(v.get("dur"), 0, 86400000) and (v["dur"] == 0 or v["pos"] <= v["dur"])}
    for name, valid in latched.items():
        if name in frame:
            need(valid(frame[name]), f"{name} value")
            need(alive or name == "reducedMotion", f"{name} only with alive")
    for key, default in (("titleTone", "ink"), ("metaTone", "meta"), ("statusTone", "meta"), ("artDim", False),
                         ("page", 0), ("heading", ""), ("meta", ""), ("artKey", ""), ("iconKey", "")):
        need(not (key in frame and frame[key] == default and type(frame[key]) is type(default)), f"slimming: {key}")
    need("counter" not in frame, "slimming: counter omitted (3.1)")
    if layout not in HOME:
        for key in ("volumeCaption", "confirmedVolume", "restLayout", "volumeVisible"):
            need(key not in frame, f"slimming: {key} only on Home")
    need(v5.line_bytes({**frame, "id": frame.get("id", 0x7FFFFFFF)}) <= v5.BUDGET_V5, "budget 1,400 B (14.1)")
    return bad


class SessionCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="nanod-session-capture-")
        cls.path = Path(cls.temp.name) / "session.jsonl"
        cls.records, cls.summary = capture_tool.capture(cls.path)
        cls.presented = [r for r in cls.records if r["kind"] in ("frame", "control")]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def session(self, name, kinds=("frame", "control")):
        return [r for r in self.records if r["session"] == name and r["kind"] in kinds]

    def seen(self, name, fields=("title", "subtitle", "meta", "status", "heading")):
        return {(field, frame.get(field)) for frame in map(frame_of, self.session(name)) for field in fields}

    def test_the_sessions_are_the_v7_compatibility_rows(self):
        """PRESENTATION_V5.md 2.1: the knobs a desktop v7 host meets."""
        caps = capture_tool.SESSIONS
        self.assertEqual(list(caps), ["p5", "a2", "p4", "p2"])
        self.assertEqual((caps["p5"]["presentation"], caps["a2"]["presentation"], caps["p4"]["presentation"],
                          caps["p2"]["presentation"]), (5, 4, 4, 2))
        self.assertIsNotNone(device.alive_capability(caps["p5"]))
        self.assertIsNone(device.alive_capability(caps["a2"]))
        self.assertIsNotNone(device.artwork2_capability(caps["p5"]))
        self.assertIsNotNone(device.artwork2_capability(caps["a2"]))
        self.assertIsNone(device.artwork2_capability(caps["p4"]))

    def test_the_session_ran_cleanly(self):
        for name, counts in self.summary.items():
            with self.subTest(session=name):
                self.assertEqual(counts["refusals"], [], "the knob refused a line")
                self.assertEqual(counts["bridgeErrors"], [], "the bridge failed")
                events = counts["events"]
                self.assertNotIn("error", events)
                self.assertEqual(events["ready"], counts["controls"], "every entry was acknowledged")
                self.assertEqual(counts["knobInput"]["ready"], counts["controls"])
                self.assertEqual((events["connected"], events["released"]), (1, 1))
                self.assertGreaterEqual(counts["controls"], 50)
                self.assertGreaterEqual(counts["frames"], 250)
                self.assertGreater(counts["toasts"], 10, "K3 12: the toasts of the starts, skips, snaps and Switch")
        self.assertEqual(self.summary["p4"]["events"]["artwork-ready"], self.summary["p4"]["artOps"]["commit"])
        self.assertEqual(self.summary["p2"]["artOps"], {}, "no art for firmware without the capability")

    def test_the_jsonl_file_holds_every_line(self):
        on_disk = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(on_disk, self.records)
        self.assertEqual([r["n"] for r in on_disk], list(range(1, len(on_disk) + 1)))

    def test_every_line_fits_the_firmware_line_buffer(self):
        for record in self.records:
            self.assertLessEqual(record["bytes"], capture_tool.LINE_LIMIT, record["step"])

    def test_frames_fit_the_frame_budget(self):
        """K1 14.1 (1,400 B with the latched reserve) on cc5.4; V4's 1,100 B on every other knob."""
        for name, caps in capture_tool.SESSIONS.items():
            budget, _reserve = device.frame_budget(caps)
            self.assertEqual(budget, presentation.FRAME_BUDGET_BYTES_V5 if name == "p5"
                             else presentation.FRAME_BUDGET_BYTES)
            for record in self.session(name):
                with self.subTest(session=name, n=record["n"], step=record["step"]):
                    if record["kind"] == "frame":
                        self.assertLessEqual(record["bytes"], budget)
                    # The same frame as a {"frame":…} line with the largest id (entry frames too).
                    self.assertLessEqual(device.frame_line_bytes(frame_of(record)), budget)

    def test_lines_are_the_bridge_encoding(self):
        for record in self.presented:
            message = json.loads(record["line"])
            encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            self.assertEqual(encoded, record["line"], record["step"])
            self.assertEqual(len(encoded.encode("utf-8")) + 1, record["bytes"])

    def test_frames_are_fixed_points_of_the_host_adapter(self):
        for name, caps in capture_tool.SESSIONS.items():
            for record in self.session(name):
                frame = frame_of(record)
                with self.subTest(session=name, n=record["n"], step=record["step"]):
                    self.assertEqual(device._frame(deepcopy(frame), caps), frame,
                                     "re-validating a sent frame changes nothing (nothing stripped or trimmed)")

    def test_frames_conform_to_the_contract(self):
        for name, caps in capture_tool.SESSIONS.items():
            control_id = None
            for record in self.session(name):
                frame = frame_of(record)
                with self.subTest(session=name, n=record["n"], step=record["step"]):
                    if caps["presentation"] >= presentation.PRESENTATION_V5:
                        self.assertEqual(v5_violations(frame, caps), [])
                    else:
                        self.assertEqual(contract_violations(frame, caps), [])   # V4 and the 2.2 downgrade
                    if record["kind"] == "control":
                        control = json.loads(record["line"])["control"]
                        self.assertNotIn("id", frame)
                        self.assertIn(control["profile"], PROFILES.values())
                        # VOC 6.1 / K1 11.4: windowsButton = buttonOrder[3] (raw); HID only on Home.
                        self.assertEqual((control["min"], control["windowsButton"], control["buttonOrder"]),
                                         (0, 3, [0, 1, 2, 3]))
                        self.assertEqual(control["windowsHidEnabled"], v5.layout_of(frame) in HOME,
                                         "windowsHidEnabled = (mode == home)")
                        self.assertLessEqual(control["position"], control["max"])
                        self.assertTrue(control_id is None or control["id"] > control_id, "ids advance")
                        control_id = control["id"]
                    else:
                        self.assertEqual(frame["id"], control_id, "a frame always belongs to the latest entry")

    def test_the_script_reached_every_scenario(self):
        p5, a2, p4, p2 = (self.summary[name] for name in ("p5", "a2", "p4", "p2"))
        # Presentation 5: every v5 token the v7 grammar uses (K3 3.1; K1 3.6).
        self.assertEqual(set(p5["layouts"]), set(presentation.LAYOUTS))
        self.assertEqual(set(p5["ringStyles"]), set(presentation.RING_STYLES))
        self.assertEqual(set(p5["icons"]), GRAMMAR_ICONS)
        self.assertEqual(set(p5["lit"]), {"on", "off"})
        self.assertEqual(set(p5["moments"]), {"queued", "shuffle", "like", "snap", "started"}, "never unlike")
        self.assertEqual(set(p5["skips"]), {-1, 1})
        self.assertGreater(p5["buttonColors"], 0, "an assigned snap side's accent")
        self.assertGreater(p5["now"], 0)
        self.assertEqual(set(p5["pages"]), {0, 1}, "explorer tabs")
        self.assertEqual(set(p5["latched"]), {"clock", "progress", "ledDrive", "ledDither", "reducedMotion",
                                              "ledPink", "ledVolFull"})
        self.assertGreater(p5["reducedMotion"], 0)
        self.assertGreater(p5["playing"], 0)
        # The presentation-4 knobs get the section 2.2 downgrade of the same session.
        for counts in (a2, p4):
            self.assertEqual(set(counts["layouts"]), set(presentation.LAYOUTS_V4))
            self.assertEqual(set(counts["ringStyles"]), set(presentation.RING_STYLES_V4))
            self.assertLessEqual(set(counts["icons"]), set(presentation.ICONS_V4))
            self.assertEqual((counts["lit"], counts["moments"], counts["skips"], counts["latched"],
                              counts["buttonColors"], counts["now"]), ([], [], [], [], 0, 0))
            self.assertLessEqual({0, 1, 2}, set(counts["pages"]), "explorer tab t -> page 1 + t, Up next -> page 1")
        for counts in (p5, a2, p4):
            # "unavailable" is a K1 activity token the v7 controller never sends (K3 5.2.3: muted + artDim).
            self.assertEqual(set(counts["activities"]), set(presentation.ACTIVITIES) - {"unavailable"})
            self.assertEqual(set(counts["ledStyles"]), {"color", "white"})
            self.assertEqual(set(counts["feedback"]), {"ok", "err"})
            self.assertGreaterEqual(counts["artKeys"], 5)
            self.assertGreater(counts["artDim"], 0)
            self.assertGreater(counts["restIdle"], 0)
            self.assertGreater(counts["withColors"], 0)
            self.assertEqual(counts["maxColors"], presentation.RING_WINDOW)
            self.assertLessEqual({0, 1, 2, 4, 20, 24}, set(counts["windowFirst"]), "detents across the 20-entry window")
            self.assertGreater(counts["unavailableMasks"], 0)
            self.assertGreater(counts["external"], 0)
            self.assertGreater(counts["nonAscii"], 0)
        self.assertEqual(set(p4["artOps"]), {"begin", "data", "commit"})
        full_transfer = 120 * 120 * 2 // 384
        self.assertLess(p4["artOps"]["data"], p4["artOps"]["begin"] * full_transfer, "some covers were cached")
        self.assertGreater(p4["artwork"]["hostHits"], 0, "revisited covers swap in from the host memory cache")
        self.assertEqual(p4["artwork"]["failed"], 1, "the one cover that never loads")
        # Legacy: the same session, stripped for cc4.
        self.assertEqual(set(p2["layouts"]), set(presentation.LAYOUTS_V4) - {"notice"})
        self.assertEqual((p2["nonAscii"], p2["withColors"], p2["artKeys"], p2["feedback"]), (0, 0, 0, []))

        seen = self.seen("p5")
        for expected in [("title", "Looking for Sonos…"), ("status", "Setting…"), ("status", "Changed on Sonos"),
                         ("status", "Maximum"), ("status", "Minimum"), ("status", "Pausing…"), ("status", "Paused"),
                         ("status", "Starting…"), ("status", "Didn’t start"), ("status", "Album unavailable"),
                         ("title", "Sonos unavailable"), ("status", "Sonos unavailable"),
                         ("heading", "TRACKS"), ("title", "Turn to choose"), ("title", "Next track"),
                         ("title", "Previous track"), ("meta", "Press 4 to skip"), ("meta", "Skipping…"),
                         ("meta", "End of queue"), ("meta", "Previous unavailable"),
                         ("heading", "SEEK"), ("meta", "Jumping…"), ("meta", "Stops 3 s before end"),
                         ("heading", "UP NEXT"), ("meta", "Loading queue…"), ("meta", "Liked"),
                         ("meta", "Unfavourite in Music app"), ("meta", "Shuffle on"),
                         ("heading", "RECENTLY ADDED"), ("meta", "Loading…"), ("meta", "44 / 44 · end"),
                         ("meta", "Not available"), ("meta", "Finding songs…"), ("meta", "Queued next"),
                         ("heading", "RECENT"), ("heading", "FAVOURITES"), ("subtitle", "12 songs"),
                         ("meta", "Closed · can’t switch"), ("meta", "Didn’t come forward · retry"),
                         ("title", "No eligible windows"), ("title", "Apple Music sign-in expired"),
                         ("title", "Library not loaded"), ("title", "Nothing recently added")]:
            self.assertIn(expected, seen)
        self.assertTrue(any(field == "meta" and text and text.startswith("Left: ") for field, text in seen),
                        "an assigned snap side's meta")
        self.assertFalse(any(text and text.startswith("Queueing… 0 of") for _field, text in seen), "C5-69")

        frames = [frame_of(r) for r in self.session("p4")]
        windows = [f for f in frames if f.get("layout") == "windows" and f["ring"]["count"] > 20]
        self.assertTrue(any(f["ring"].get("unavailable") for f in windows), "20+ windows with closed ones")

    def test_presentation_5_knob_input(self):
        """K1 11: `ks` in ready, one `kh` per hold (a hold goes Home), `hid:1` on the F24 press (the host
        drops that edge), `lim`; none of them on older knobs."""
        p5 = self.summary["p5"]
        self.assertEqual((p5["knobInput"]["kh"], p5["events"]["hold"]), (1, 1))
        # K3 4.1/4.2, K1 11.2: the hold is held in Seek, so its press is Seek's Back to Tracks and its
        # `kh` then meets Tracks and goes Home (a hold on Home would be a no-op and prove nothing).
        self.assertEqual(p5["holds"], [{"step": "hold/seek-home", "held": "tracks", "after": "home"}])
        entries = [v5.layout_of(frame_of(r)) for r in self.session("p5", ("control",)) if r["step"] == "hold/seek-home"]
        self.assertEqual(entries[:-1], ["tracks", "seek", "tracks"])
        self.assertIn(entries[-1], HOME, "the kh's Home entry, with no Back pressed after it")
        # K1 11.1/11.3: the Back's Tracks entry and the kh's Home entry are both built while Button 1 is
        # still down: their readies carry ks 1 (raw 0), which the host reports as `held` 1 (logical 0).
        self.assertEqual(p5["readyKs"], [["hold/seek-home", 1], ["hold/seek-home", 1]])
        self.assertEqual(p5["readyHeld"], [1, 1])
        self.assertGreater(p5["knobInput"]["hid"], 0)
        self.assertEqual((p5["knobInput"]["lim"], p5["events"]["limit"]), (1, 1))
        for name in ("a2", "p4", "p2"):
            counts = self.summary[name]
            self.assertFalse({"kh", "hid", "lim"} & set(counts["knobInput"]), name)
            self.assertFalse({"hold", "limit"} & set(counts["events"]), name)
            # No `kh`: the held press is the Back alone (the script's second Back reaches Home); no
            # `ks` in ready (absent = 0, 11.3).
            self.assertEqual(counts["holds"], [{"step": "hold/seek-home", "held": "tracks", "after": "tracks"}], name)
            self.assertEqual((counts["readyKs"], counts["readyHeld"]), ([], []), name)
        # A Win press opened the picker once per press, whatever path it took.
        for name in capture_tool.SESSIONS:
            steps = [r["step"] for r in self.session(name) if r["kind"] == "control"
                     and v5.layout_of(frame_of(r)) == "windows"]
            self.assertTrue(steps, name)

    def test_diag_is_asked_once_a_minute_and_read_only(self):
        """PRESENTATION_V5.md 12.3; K3 6.5: the runtime's request_diag() reaches every knob that
        advertises `diag`, at most one line a minute, each answered with one `diag` event; cc4 has none."""
        for name in ("p5", "a2", "p4"):
            counts = self.summary[name]
            with self.subTest(session=name):
                lines = [r for r in self.session(name, ("query",)) if r["line"] == '{"diag":"?"}']
                self.assertGreaterEqual(len(lines), 1)
                self.assertEqual((counts["diagLines"], counts["knobInput"]["diag"], counts["events"]["diag"]),
                                 (len(lines),) * 3)
                self.assertIn("diag/once-a-minute", [r["step"] for r in lines])
                times = [r["t"] for r in lines]
                self.assertTrue(all(b - a >= 60.0 for a, b in zip(times, times[1:])), times)
                self.assertGreaterEqual(times[0], 60.0 + min(r["t"] for r in self.session(name, ("control",))),
                                        "the first a minute after the claim")
        self.assertEqual(self.summary["p2"]["diagLines"], 0)
        self.assertNotIn("diag", self.summary["p2"]["events"])

    def test_artwork2_session_transport(self):
        # ARTWORK2.md section 3: with artwork2 negotiated every line is one whole write and
        # no v1 art line is sent; without it the 64 B / 5 ms pacing stays exactly as before.
        for name in ("p5", "a2"):
            counts = self.summary[name]
            with self.subTest(session=name):
                writes = counts["media"]["writes"]
                self.assertEqual(writes["wholeLines"], writes["calls"])
                self.assertEqual(writes["calls"], counts["lines"], "one write per recorded line")
                self.assertGreater(writes["maxBytes"], capture_tool.PacedSerial.CHUNK_BYTES)
                self.assertEqual(counts["artOps"], {})
                # The CDC model with seeded 30-100 ms COM stalls never overflowed.
                cdc = counts["media"]["cdc"]
                self.assertEqual((cdc["droppedBytes"], cdc["damagedWrites"]), (0, 0))
                self.assertGreater(cdc["stalls"], 10)
                self.assertLess(cdc["highWater"], presentation.ARTWORK2_CAPABILITY["rxBytes"])
                self.assertEqual(cdc["lines"], counts["lines"])
        for name in ("p4", "p2"):
            with self.subTest(session=name):
                self.assertEqual(self.summary[name]["media"]["writes"]["maxBytes"],
                                 capture_tool.PacedSerial.CHUNK_BYTES)
                self.assertEqual(self.summary[name]["mediaOps"], {})
                self.assertEqual(self.summary[name]["iconKeys"], 0)

    def test_artwork2_session_media(self):
        for name in ("p5", "a2"):
            counts = self.summary[name]
            with self.subTest(session=name):
                media = counts["media"]
                self.assertEqual(media["errors"], [], "the knob refused no media line")
                self.assertNotIn("media-error", counts["events"])
                self.assertEqual(sum(media["acks"].values()), sum(counts["mediaOps"].values()), "one reply per line")
                self.assertTrue(counts["mediaOps"], "the runtime pushes its wanted lists")
                ready = counts["events"].get("media-ready", 0)
                self.assertEqual(media["commits"], counts["mediaOps"].get("commit", 0))
                self.assertLessEqual(media["commits"], ready)
                self.assertLessEqual(ready, counts["mediaOps"].get("begin", 0))
                self.assertGreater(counts["iconKeys"], 0, "app icons on the Windows layout")
                records = self.session(name, ("media",))
                self.assertEqual({r["media"] for r in records} - {"cover", "icon"}, set())
                self.assertTrue(all(r["id"] is not None for r in records), "every media line carries the control id")
                for record in records:
                    if record["op"] == "have":
                        keys = json.loads(record["line"])["media"]["keys"]
                        self.assertTrue(1 <= len(keys) <= presentation.MEDIA_HAVE_KEYS)

    def test_text_is_adapted_and_cut_at_code_points(self):
        for name in ("p5", "a2"):
            frames = [frame_of(r) for r in self.session(name)]
            texts = {value for f in frames for value in f.values() if isinstance(value, str)}
            with self.subTest(session=name):
                self.assertIn("x" * 91 + "éé", texts, "96-byte capacity: the é that would straddle it is dropped whole")
                self.assertIn("Überlänge " * 8, texts, "an over-capacity artist, cut at a whole code point")
                self.assertIn('Quotes "and" \\backslashes\\', texts, "JSON escapes on the wire")
                self.assertIn('Say "Hello" \\ Goodbye', texts, "JSON escapes on the wire")
                self.assertIn("Straße ? Mix for Night", texts, "controls cleaned, a glyph outside latin-ext-a replaced")
                self.assertIn("Café finale – ½ time ?", texts, "NFC, compatibility forms, unsupported glyphs")
                self.assertIn("Now: Say \"Hello\" \\ Goo…", texts, "K3 5.4.3: the 14 px line fitted with an ellipsis")
        legacy = {value for f in map(frame_of, self.session("p2")) for value in f.values() if isinstance(value, str)}
        self.assertIn("Cafe finale - 1?2 time ?", legacy, "cc4: ASCII fallback")
        for record in self.presented:
            for name, capacity in presentation.TEXT_CAPACITY.items():
                text = frame_of(record).get(name, "")
                self.assertLessEqual(len(text.encode("utf-8")), capacity, (record["step"], name))

    def test_the_capture_is_deterministic(self):
        again, _summary = capture_tool.capture()
        self.assertEqual(again, self.records)

    @unittest.skipUnless(FIRMWARE_PARSER, "MSVC, ArduinoJson or the firmware parser is unavailable")
    def test_the_firmware_parser_accepts_every_recorded_line(self):
        build = Path(self.temp.name) / "parse-frames"
        done = subprocess.run([sys.executable, str(PARSE_TESTS), "--frames", str(self.path), "--out", str(build)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        output = done.stdout + done.stderr
        self.assertEqual(done.returncode, 0, output[-4000:])
        lines = [line for line in output.splitlines() if line.startswith("CAPTURE-SUMMARY ")]
        self.assertEqual(len(lines), 1, output[-2000:])
        summary = json.loads(lines[0].split(" ", 1)[1])
        self.assertEqual((summary["lines"], summary["accepted"], summary["rejected"]),
                         (len(self.presented), len(self.presented), 0))
        self.assertEqual((summary["inputTextDiffs"], summary["expectedTextDiffs"], summary["failures"]), (0, 0, 0))
        fields = parser_text_fields()
        self.assertEqual(summary["inputTextChecks"], (len(fields) + 4) * len(self.presented),
                         f"{len(fields)} text fields + 4 labels per line")
        if summary["cc4Parser"]:
            legacy = len(self.session("p2"))
            self.assertEqual((summary["cc4Lines"], summary["cc4Accepted"], summary["cc4TextDiffs"]), (legacy, legacy, 0))


class FakeKnobButtonStateTests(unittest.TestCase):
    """The capture's fake knob reports the buttons physically down, as the firmware does (K1 11.1-11.3):
    in every `ks`, in the `ready` of an entry built while a button is held, and it sends a `kh` only
    for a raw that is still down (11.2 step 5)."""

    def knob(self, caps):
        clock = capture_tool.Clock()
        return capture_tool.FakeKnob(clock, caps, capture_tool.Recorder(clock), "test")

    def claim(self, knob, control_id):
        knob.write(json.dumps({"control": {"id": control_id, "position": 1, "max": 2}}).encode("utf-8") + b"\n")

    def sent(self, knob):
        lines = [json.loads(line) for line in bytes(knob.buffer).decode("utf-8").splitlines()]
        knob.buffer.clear()
        return lines

    def test_a_ready_built_while_a_button_is_down_carries_it(self):
        knob = self.knob(capture_tool.CC54_CAPABILITIES)
        self.claim(knob, 1)
        self.assertEqual(self.sent(knob), [{"ready": 1, "p": 1, "ks": 0}])
        knob.down(0)
        self.claim(knob, 2)            # the held press's Back re-entered the knob
        knob.long_press(0)
        self.claim(knob, 3)            # the kh's Home entry, Button 1 still down
        knob.up(0)
        knob.long_press(0)             # released: no kh (11.2 step 5)
        self.claim(knob, 4)
        self.assertEqual(self.sent(knob), [
            {"id": 1, "kd": 0, "ks": 1}, {"ready": 2, "p": 1, "ks": 1}, {"id": 2, "ks": 1, "kh": 0},
            {"ready": 3, "p": 1, "ks": 1}, {"id": 3, "ku": 0, "ks": 0}, {"ready": 4, "p": 1, "ks": 0}])
        self.assertEqual(knob.ready_ks, [("", 1), ("", 1)])
        self.assertEqual((knob.sent["kh"], knob.held), (1, 0))

    def test_a_press_while_another_button_is_held_keeps_its_bit(self):
        knob = self.knob(capture_tool.CC54_CAPABILITIES)
        self.claim(knob, 1)
        self.sent(knob)
        knob.down(0)
        knob.press(2)
        knob.up(0)
        self.assertEqual(self.sent(knob), [{"id": 1, "kd": 0, "ks": 1}, {"id": 1, "kd": 2, "ks": 5},
                                           {"id": 1, "ku": 2, "ks": 1}, {"id": 1, "ku": 0, "ks": 0}])

    def test_older_knobs_send_no_ks_in_ready_and_no_kh(self):
        for caps in (capture_tool.CC53_CAPABILITIES, capture_tool.CC4_CAPABILITIES):
            knob = self.knob(caps)
            with self.subTest(presentation=caps["presentation"]):
                knob.down(0)
                self.claim(knob, 1)
                knob.long_press(0)
                knob.up(0)
                self.assertEqual(self.sent(knob), [{"id": 0, "kd": 0, "ks": 1}, {"ready": 1, "p": 1},
                                                   {"id": 1, "ku": 0, "ks": 0}])
                self.assertEqual((knob.ready_ks, knob.sent["kh"]), ([], 0))


if __name__ == "__main__":
    unittest.main()
