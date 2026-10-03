"""ALIVE.md section 3 on the host: the "Warm · alive" wire fields (1.0.0-cc5.4, desktop v7).

* tests/fixtures/frames_alive.json: device._frame (host output, key order included, a fixed
  point, a valid v4 frame plus valid section 3 fields) and device.alive_parse (the parser's
  reading, rules.aliveRaw) against the shared fixtures that harness/parse_tests.py
  also runs through the firmware parser (src/cc_frame_parse.cpp).
* Capability gating: the fields go only to a knob with capabilities.alive.version == 1. With
  any other knob every frame line is byte-identical to desktop v6's: the reference is the v6
  device.py itself, loaded from backups/source-snapshots/desktop-v6-start-20260925T013903Z.zip
  (its device.py is the released v6 one; the SHA-256 below pins it). Skipped without the zip.
* DeviceBridge: clock / progress / ledDrive / ledDither added at send time (enter frames, the
  10-minute clock, one progress per post, never repeated by a heartbeat), both write paths
  (paced cc5.2-style and artwork2), and the knob's `lim` event.

No port is opened: every bridge runs on an in-memory fake serial with a fake clock.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from control_center import device, presentation as P  # noqa: E402
from control_center.device import DeviceBridge, _frame, alive_capability, alive_parse  # noqa: E402
from test_cc_contract_v4 import contract_violations  # noqa: E402
from test_cc_device import Clock, FakeSerial, control  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
ALIVE_FIXTURES = FIXTURES / "frames_alive.json"
V4_FIXTURES = FIXTURES / "frames_v4.json"
V6_ZIP = ROOT / "backups" / "source-snapshots" / "desktop-v6-start-20260925T013903Z.zip"
V6_DEVICE = "outputs/nanod-desktop-demo/control_center/device.py"
V6_PRESENTATION = "outputs/nanod-desktop-demo/control_center/presentation.py"
# SHA-256 of the released desktop v6 control_center/device.py (the file this module replaced).
V6_DEVICE_SHA256 = "f652209b21abe98abb5ef8a6d5939ec3124aed48d5cb2eb52e7a36e50180dfbb"

ART = {"version": 1, "width": 120, "height": 120, "format": "RGB565_LE", "chunkBytes": 384,
       "cacheEntries": 8, "available": True, "composited": "scrim80"}
P2 = {"controlCenter": 1, "presentation": 2}
P4 = {"controlCenter": 1, "presentation": 4, "glyphs": "latin-ext-a"}
A2 = {**P4, "artwork": ART, "artwork2": deepcopy(P.ARTWORK2_CAPABILITY)}          # cc5.3
ALIVE = {"version": 1, "fps": 60, "drive": 150}
AL = {**A2, "alive": ALIVE}                                                        # cc5.4
AL4 = {**P4, "alive": ALIVE}                                                       # alive, paced path
NOT_ALIVE = {"cc5.3": A2, "cc5.2": P4, "cc4": P2, "alive-v2": {**A2, "alive": {**ALIVE, "version": 2}},
             "alive-true": {**A2, "alive": {**ALIVE, "version": True}}, "alive-1": {**A2, "alive": 1},
             "alive-p3": {"controlCenter": 1, "presentation": 3, "alive": ALIVE}}
SECTION3 = ("playing", "clock", "progress", "ledDrive", "ledDither")
LATCHED = P.ALIVE_LATCHED_FIELDS


def v4_part(frame):
    """The frame without the section 3 fields (top level and feedback.skip)."""
    out = {k: v for k, v in frame.items() if k not in SECTION3}
    if isinstance(out.get("feedback"), dict):
        out["feedback"] = {k: v for k, v in out["feedback"].items() if k != "skip"}
    return out


def line(frame):
    return (json.dumps({"frame": frame}, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            + "\n").encode("utf-8")


# --- An independent reading of ALIVE.md section 3 (never calls device). -------------------------
def _int(value, low, high):
    return type(value) is int and low <= value <= high


_HOME = ("nowPlaying", "volume", "idle", "notice")
_MODE_LAYOUT = {"VOLUME": "nowPlaying", "RECENTLY ADDED": "recent", "TRACKS": "tracks", "WINDOWS": "windows"}


def alive_violations(frame, caps):
    """Every way the section 3 part of a HOST output breaks ALIVE.md for a knob with `caps`."""
    negotiated = (type(caps.get("presentation")) is int and caps["presentation"] >= 4
                  and isinstance(caps.get("alive"), dict) and type(caps["alive"].get("version")) is int
                  and caps["alive"]["version"] == 1)
    feedback = frame.get("feedback") if isinstance(frame.get("feedback"), dict) else {}
    present = [k for k in SECTION3 if k in frame] + (["feedback.skip"] if "skip" in feedback else [])
    if not negotiated:
        return [f"{name} sent without alive" for name in present]
    bad = []
    layout = frame.get("layout", _MODE_LAYOUT.get(frame.get("mode"), "nowPlaying"))
    if "playing" in frame and (type(frame["playing"]) is not bool or layout not in _HOME):
        bad.append("playing: a bool, on Home layouts only")
    if "clock" in frame and not _int(frame["clock"], 0, 1439):
        bad.append("clock: int 0..1439")
    if "progress" in frame:
        pr = frame["progress"]
        if not (isinstance(pr, dict) and set(pr) == {"pos", "dur"} and _int(pr["pos"], 0, 86400000)
                and _int(pr["dur"], 0, 86400000) and (pr["dur"] == 0 or pr["pos"] <= pr["dur"])):
            bad.append("progress: {pos, dur} ints 0..86400000, pos <= dur unless dur == 0")
    if "ledDrive" in frame and not _int(frame["ledDrive"], 1, 255):
        bad.append("ledDrive: int 1..255")
    if "ledDither" in frame and type(frame["ledDither"]) is not bool:
        bad.append("ledDither: bool")
    if "skip" in feedback and not (feedback.get("kind") == "ok" and type(feedback["skip"]) is int
                                   and feedback["skip"] in (-1, 1)):
        bad.append("feedback.skip: -1 or 1, with kind ok only")
    worst = {**frame, "id": frame.get("id", 0x7FFFFFFF), "clock": 1439, "progress": {"pos": 86400000, "dur": 86400000},
             "ledDrive": 255, "ledDither": False}
    if len(line(worst)) > 1100:
        bad.append(f"budget: {len(line(worst))} B with every latched field at its longest")
    return bad


# --- desktop v6's device.py, the byte-identity reference ------------------------------------------
_V6 = None


def v6_device():
    """control_center.device of desktop v6 (from the source snapshot), as package cc_v6."""
    global _V6
    if _V6 is not None:
        return _V6
    if not V6_ZIP.is_file():
        raise unittest.SkipTest(f"{V6_ZIP.name} not found: no desktop v6 reference")
    with zipfile.ZipFile(V6_ZIP) as archive:
        sources = {"presentation": archive.read(V6_PRESENTATION), "device": archive.read(V6_DEVICE)}
    if hashlib.sha256(sources["device"]).hexdigest() != V6_DEVICE_SHA256:
        raise AssertionError("the snapshot's device.py is not the released desktop v6 one")
    package = types.ModuleType("cc_v6")
    package.__path__ = []
    sys.modules["cc_v6"] = package
    for name in ("presentation", "device"):
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader(f"cc_v6.{name}", loader=None))
        module.__package__ = "cc_v6"
        sys.modules[f"cc_v6.{name}"] = module
        exec(compile(sources[name].decode("utf-8"), f"<desktop v6 control_center/{name}.py>", "exec"),
             module.__dict__)
        setattr(package, name, module)
    _V6 = package.device
    return _V6


class WireSerial(FakeSerial):
    """FakeSerial that advertises `caps` and keeps every written line's exact bytes."""

    def __init__(self, clock, caps):
        super().__init__(clock, capabilities=False)
        self.caps = caps
        self.raw = []

    def write(self, raw):
        self.raw.append(bytes(raw))
        count = super().write(raw)
        if self.writes[-1] == {"capabilities": "?"}:
            self.inject({"capabilities": deepcopy(self.caps)})
        return count

    def frames(self):
        """(kind, frame) of every frame line written: kind "control" or "frame"."""
        out = []
        for message in self.writes:
            if "control" in message:
                out.append(("control", message["control"]["frame"]))
            elif "frame" in message:
                out.append(("frame", message["frame"]))
        return out


def base_frames():
    cases = {c["name"]: c for c in json.loads(V4_FIXTURES.read_text(encoding="utf-8"))["cases"]}
    pick = {"home": "v4-home-now-playing", "volume": "v4-home-volume-external-over-idle",
            "tracks": "v4-tracks-no-previous", "recent": "v4-recent-item-colour", "windows": "v4-windows-window-rule"}
    return {key: deepcopy(cases[name]["input"]) for key, name in pick.items()}


BASE = base_frames()


def home(**extra):
    return {**deepcopy(BASE["home"]), **extra}


class AliveFixtureTests(unittest.TestCase):
    """The shared fixture file the firmware parser is also tested against (parse_tests.py)."""

    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(ALIVE_FIXTURES.read_text(encoding="utf-8"))
        cls.cases = cls.doc["cases"]

    def setUp(self):
        device._strip_logged.clear()

    def test_cases_are_self_describing(self):
        names = [case["name"] for case in self.cases]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(self.doc["rules"]), {"host", "firmwareOutput", "firmwareRaw", "aliveRaw", "gating",
                                                  "budget"})
        for case in self.cases:
            with self.subTest(case=case["name"]):
                self.assertTrue(case["name"].startswith(("alive-", "gate-alive-")))
                self.assertEqual(set(case), {"name", "note", "capabilities", "input", "expect", "rawParity", "alive"})
                self.assertIs(case["expect"]["accept"], True, "a section 3 field never makes the host raise")
                self.assertEqual(set(case["alive"]), {"accept", "stored"} if case["alive"]["accept"] else {"accept"})
                negotiated = alive_capability(case["capabilities"]) is not None
                self.assertEqual(negotiated, case["name"].startswith("alive-"))
                if not case["alive"]["accept"]:
                    self.assertFalse(case["rawParity"], "the parser rejects what the host strips")

    def test_host_adapter_matches_every_case_byte_for_byte(self):
        for case in self.cases:
            with self.subTest(case=case["name"]):
                sent = _frame(deepcopy(case["input"]), deepcopy(case["capabilities"]))
                self.assertEqual(line(sent), line(case["expect"]["output"]))

    def test_host_output_is_a_fixed_point(self):
        for case in self.cases:
            with self.subTest(case=case["name"]):
                output = case["expect"]["output"]
                self.assertEqual(line(_frame(deepcopy(output), deepcopy(case["capabilities"]))), line(output))

    def test_alive_parse_is_the_raw_verdict(self):
        # rules.aliveRaw: the Python reading of what a 1.0.0-cc5.4 parser does with the raw input.
        for case in self.cases:
            with self.subTest(case=case["name"]):
                stored, invalid = alive_parse(deepcopy(case["input"]))
                self.assertEqual(not invalid, case["alive"]["accept"], invalid)
                if case["alive"]["accept"]:
                    self.assertEqual(stored, case["alive"]["stored"])
                # The parser stores exactly what the host sends for every section 3 field it kept.
                sent_stored, sent_invalid = alive_parse(case["expect"]["output"])
                self.assertEqual(sent_invalid, [])
                if alive_capability(case["capabilities"]) is not None and case["alive"]["accept"]:
                    self.assertEqual(sent_stored, case["alive"]["stored"], "a valid raw input survives the host")

    def test_every_output_satisfies_both_contracts(self):
        for case in self.cases:
            with self.subTest(case=case["name"]):
                output, caps = case["expect"]["output"], case["capabilities"]
                self.assertEqual(alive_violations(output, caps), [])
                v4_caps = {k: v for k, v in caps.items() if k != "alive"}
                self.assertEqual(contract_violations(v4_part(output), v4_caps), [])

    def test_alive_reader_is_not_vacuous(self):
        valid = home(playing=True, clock=5)
        self.assertEqual(alive_violations(valid, AL), [])
        for frame, caps, reason in (
                (valid, A2, "sent without alive"),
                ({**BASE["recent"], "playing": True}, AL, "Home layouts only"),
                (home(clock=1440), AL, "clock"),
                (home(progress={"pos": 3, "dur": 2}), AL, "progress"),
                (home(progress={"pos": 1, "dur": 2, "x": 0}), AL, "progress"),
                (home(ledDrive=0), AL, "ledDrive"),
                (home(ledDither=0), AL, "ledDither"),
                (home(feedback={"kind": "err", "seq": 1, "skip": 1}), AL, "feedback.skip"),
                (home(title="x" * 400), AL, "budget")):
            with self.subTest(reason=reason):
                self.assertTrue(any(reason in problem for problem in alive_violations(frame, caps)))

    def test_every_field_has_valid_boundary_and_invalid_cases(self):
        kept, rejected = {}, {}
        for case in self.cases:
            if alive_capability(case["capabilities"]) is None:
                continue
            fields = [k for k in SECTION3 if k in case["input"]]
            if "skip" in (case["input"].get("feedback") or {}):
                fields.append("feedback.skip")
            for name in fields:
                (kept if case["alive"]["accept"] else rejected).setdefault(name, []).append(case["name"])
        for name in (*SECTION3, "feedback.skip"):
            with self.subTest(field=name):
                self.assertGreaterEqual(len(kept.get(name, [])), 2, "valid and boundary cases")
                self.assertGreaterEqual(len(rejected.get(name, [])), 3, "invalid cases")
        print(f"\n[alive wire] {len(self.cases)} fixture cases; kept/rejected per field: "
              + ", ".join(f"{n} {len(kept.get(n, []))}/{len(rejected.get(n, []))}" for n in (*SECTION3, "feedback.skip")))

    def test_gate_cases_are_desktop_v6_output(self):
        v6 = v6_device()
        for case in self.cases:
            if case["name"].startswith("gate-"):
                with self.subTest(case=case["name"]):
                    self.assertEqual(line(v6._frame(deepcopy(case["input"]), deepcopy(case["capabilities"]))),
                                     line(case["expect"]["output"]))

    def test_budget_cases(self):
        cases = {c["name"]: c for c in self.cases}
        for name in ("alive-windows-budget", "alive-home-budget"):
            with self.subTest(case=name):
                case = cases[name]
                sent = case["expect"]["output"]
                for field in LATCHED:
                    self.assertIn(field, sent)
                size = device.frame_line_bytes({**sent, **P.ALIVE_LATCHED_WORST})
                self.assertLessEqual(size, P.FRAME_BUDGET_BYTES)
                for field in ("title", "subtitle"):
                    self.assertEqual(sent[field], case["input"][field], "drawn text is never shortened")
                print(f"\n[alive wire] {name}: {size} B with every section 3 field")
        self.assertEqual(cases["alive-home-budget"]["expect"]["output"]["value"], "100%", "Home digits are drawn")


class ValidationTests(unittest.TestCase):
    def setUp(self):
        device._strip_logged.clear()

    def test_capability_needs_version_1_on_presentation_4(self):
        self.assertEqual(alive_capability(AL), ALIVE)
        self.assertEqual(alive_capability(AL4), ALIVE)
        self.assertEqual(alive_capability({"presentation": 4, "alive": {"version": 1}}), {"version": 1})
        for caps in NOT_ALIVE.values():
            with self.subTest(caps=caps):
                self.assertIsNone(alive_capability(caps))
        for caps in (None, {}, {"alive": ALIVE}, {"presentation": "4", "alive": ALIVE},
                     {**P4, "alive": {"version": 1.0}}, {**P4, "alive": {"fps": 60}}, {**P4, "alive": [1]}):
            self.assertIsNone(alive_capability(caps))

    def test_invalid_values_are_stripped_and_logged_by_name_only(self):
        invalid = {"clock": 1440, "playing": "yes", "progress": {"pos": 9, "dur": 3}, "ledDrive": 0,
                   "ledDither": "secret-value"}
        for name, value in invalid.items():
            with self.subTest(field=name):
                device._strip_logged.clear()
                with self.assertLogs("control_center.device", "WARNING") as logs:
                    sent = _frame(home(**{name: value}), AL)
                self.assertNotIn(name, sent)
                self.assertEqual(sent, _frame(home(), AL), "the rest of the frame is sent unchanged")
                self.assertTrue(any(name in entry for entry in logs.output))
                self.assertFalse(any("secret-value" in entry for entry in logs.output), "values are never logged")
        with self.assertLogs("control_center.device", "WARNING") as logs:
            sent = _frame(home(feedback={"kind": "ok", "seq": 4, "skip": 0}), AL)
        self.assertEqual(sent["feedback"], {"kind": "ok", "seq": 4}, "only skip is stripped")
        self.assertTrue(any("feedback.skip" in entry for entry in logs.output))

    def test_scope_strips_silently(self):
        for key in ("recent", "tracks", "windows"):
            with self.subTest(layout=key), self.assertNoLogs("control_center.device", "WARNING"):
                self.assertNotIn("playing", _frame({**BASE[key], "playing": True}, AL))
        with self.assertNoLogs("control_center.device", "WARNING"):
            sent = _frame(home(feedback={"kind": "err", "seq": 4, "skip": 1}), AL)
        self.assertEqual(sent["feedback"], {"kind": "err", "seq": 4})
        # Validation first: an invalid value is a (logged) strip on every layout.
        with self.assertLogs("control_center.device", "WARNING"):
            _frame({**BASE["recent"], "playing": 1}, AL)

    def test_without_alive_everything_is_dropped_silently(self):
        frame = home(playing=True, clock=5, progress={"pos": 1, "dur": 2}, ledDrive=9, ledDither=True,
                     feedback={"kind": "ok", "seq": 3, "skip": 1})
        for label, caps in NOT_ALIVE.items():
            with self.subTest(caps=label), self.assertNoLogs("control_center.device", "WARNING"):
                sent = _frame(deepcopy(frame), caps)
                for name in SECTION3:
                    self.assertNotIn(name, sent)
                self.assertNotIn("skip", sent.get("feedback", {}))
        with self.assertNoLogs("control_center.device", "WARNING"):
            _frame(home(clock="bad", playing=None, feedback={"kind": "ok", "seq": 3, "skip": 5}), A2)

    def test_alive_parse_validates_before_scoping(self):
        stored, invalid = alive_parse({**BASE["recent"], "playing": "x"})
        self.assertEqual(invalid, ["playing"])
        stored, invalid = alive_parse({**BASE["recent"], "playing": False})
        self.assertEqual((stored["playing"], invalid), (-1, []))
        stored, invalid = alive_parse(home(feedback={"kind": "err", "seq": 1, "skip": 7}))
        self.assertEqual(invalid, ["feedback.skip"])
        self.assertEqual(alive_parse("not a frame"), (alive_parse({})[0], []))
        # A mode that is not text never raises (the v4 part rejects that frame anyway).
        self.assertEqual(alive_parse({"mode": ["x"], "playing": True})[0]["playing"], 1)


class BridgeCase(unittest.TestCase):
    CAPS = AL

    def setUp(self):
        device._strip_logged.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.minute = 754
        self.serial = WireSerial(self.clock, self.CAPS)
        self.bridge = DeviceBridge(self.temp.name, lambda port: self.serial, request_timeout=0.1, autostart=False,
                                   clock=self.clock, local_minute=lambda: self.minute)

    def connect(self):
        self.bridge._connect("COM-FAKE")

    def written(self, kind, action):
        """Run `action`; exactly one new frame line of `kind` must be written: its frame."""
        count = len(self.serial.frames())
        action()
        frames = self.serial.frames()
        self.assertEqual([k for k, _frame in frames[count:]], [kind])
        return frames[-1][1]

    def enter(self, ident=1, frame=None):
        return self.written("control", lambda: self.bridge._enter({**control(ident), "frame": frame or home()}))

    def send(self, frame=None):
        return self.written("frame", lambda: self.bridge._frame({**(frame or home()), "id": self.bridge.ready_id}))

    def beat(self, seconds=DeviceBridge.HEARTBEAT_SECONDS):
        self.clock.now += seconds
        return self.written("frame", self.bridge._heartbeat)

    def events(self):
        out = []
        while not self.bridge.events.empty():
            out.append(self.bridge.events.get_nowait())
        return out


class LatchedFieldTests(BridgeCase):
    """cc5.4 with artwork2 (frames are flushed whole)."""

    def test_alive_property_follows_the_capabilities(self):
        self.assertFalse(self.bridge.alive)
        self.connect()
        self.assertTrue(self.bridge.alive)
        self.bridge._disconnect()
        self.assertFalse(self.bridge.alive)

    def test_every_enter_frame_carries_the_clock_and_latest_frame_never_does(self):
        self.connect()
        self.assertEqual(self.enter(1)["clock"], 754)
        self.assertNotIn("clock", self.bridge.latest_frame)
        self.assertEqual(self.send().get("clock"), None, "not again within 10 minutes")
        self.assertNotIn("clock", self.beat())
        self.minute = 755
        self.clock.now += 30
        self.assertEqual(self.enter(2)["clock"], 755, "every control frame")

    def test_clock_again_in_the_next_frame_after_ten_minutes(self):
        self.connect()
        self.enter(1)
        self.clock.now += P.ALIVE_CLOCK_RESEND_SECONDS - 1
        self.assertNotIn("clock", self.send())
        self.clock.now += 1
        self.minute = 764
        self.assertEqual(self.send()["clock"], 764)
        self.assertNotIn("clock", self.send())
        self.assertNotIn("clock", self.beat())
        # A heartbeat is the next frame line too, with the local time of that moment.
        self.minute = 775
        self.assertEqual(self.beat(P.ALIVE_CLOCK_RESEND_SECONDS)["clock"], 775)
        self.assertNotIn("clock", self.beat())

    def test_progress_is_sent_once_and_a_heartbeat_never_repeats_it(self):
        self.connect()
        self.enter(1)
        self.bridge.post_progress(83000, 245000)
        self.assertNotIn("progress", self.bridge.latest_frame)
        self.assertEqual(self.send()["progress"], {"pos": 83000, "dur": 245000})
        self.assertNotIn("progress", self.beat())
        self.assertNotIn("progress", self.send())
        self.bridge.post_progress(1000, 2000)
        self.bridge.post_progress(1500, 2000)          # the newer post wins
        self.assertEqual(self.beat()["progress"], {"pos": 1500, "dur": 2000}, "or the next heartbeat carries it")
        self.assertNotIn("progress", self.beat())
        self.bridge.post_progress(0, 0)
        self.assertEqual(self.send()["progress"], {"pos": 0, "dur": 0}, "dur 0 clears")

    def test_progress_normalisation_and_rejection(self):
        self.connect()
        self.enter(1)
        self.bridge.post_progress(245500, 245000)       # extrapolation overshoot
        self.assertEqual(self.send()["progress"], {"pos": 245000, "dur": 245000})
        self.bridge.post_progress(5000, 0)
        self.assertEqual(self.send()["progress"], {"pos": 0, "dur": 0})
        for pos, dur in ((-1, 10), (1, -1), (1, 86400001), (True, 10), (1.5, 10), (1, None), ("1", 10)):
            with self.subTest(pos=pos, dur=dur):
                device._strip_logged.clear()
                with self.assertLogs("control_center.device", "WARNING"):
                    self.bridge.post_progress(pos, dur)
                self.assertNotIn("progress", self.send())

    def test_progress_posted_before_the_enter_rides_in_it(self):
        self.connect()
        self.bridge.post_progress(10, 20)
        self.assertEqual(self.enter(1)["progress"], {"pos": 10, "dur": 20})
        self.assertNotIn("progress", self.send())

    def test_reconnect_forgets_a_pending_progress(self):
        self.connect()
        self.enter(1)
        self.bridge.post_progress(10, 20)
        self.bridge._disconnect()
        self.connect()
        self.assertNotIn("progress", self.enter(1))

    def test_led_tuning_in_every_enter_frame_and_once_after_a_change(self):
        self.bridge.set_led_tuning(200, False)
        self.connect()
        sent = self.enter(1)
        self.assertEqual((sent["ledDrive"], sent["ledDither"]), (200, False))
        self.assertNotIn("ledDrive", self.send())
        self.bridge.set_led_tuning(200, False)          # unchanged: nothing new to send
        self.assertNotIn("ledDrive", self.beat())
        self.bridge.set_led_tuning(120, None)           # dither no longer configured
        sent = self.send()
        self.assertEqual(sent["ledDrive"], 120)
        self.assertNotIn("ledDither", sent)
        self.assertNotIn("ledDrive", self.beat())
        sent = self.enter(2)
        self.assertEqual(sent["ledDrive"], 120)
        self.assertNotIn("ledDither", sent)
        self.bridge.set_led_tuning(None, None)
        self.assertEqual({k for k in self.enter(3) if k in LATCHED}, {"clock"})

    def test_invalid_led_tuning_is_ignored_and_logged(self):
        for drive, dither in ((0, None), (256, None), (True, None), (None, 1), (None, "on")):
            with self.subTest(drive=drive, dither=dither):
                device._strip_logged.clear()
                with self.assertLogs("control_center.device", "WARNING"):
                    self.bridge.set_led_tuning(drive, dither)
        self.connect()
        self.assertEqual({k for k in self.enter(1) if k in LATCHED}, {"clock"})

    def test_latched_fields_in_a_submitted_frame_are_ignored(self):
        self.connect()
        with self.assertLogs("control_center.device", "WARNING") as logs:
            sent = self.enter(1, home(clock=1, progress={"pos": 1, "dur": 2}, ledDrive=3))
        self.assertEqual({k: sent[k] for k in LATCHED if k in sent}, {"clock": 754})
        self.assertTrue(any("progress" in entry for entry in logs.output))
        sent = self.send(home(progress={"pos": 1, "dur": 2}, ledDither=True))
        self.assertFalse(set(LATCHED) & set(sent))
        self.assertFalse(set(LATCHED) & set(self.bridge.latest_frame))

    def test_frame_content_passes_the_validator(self):
        self.connect()
        self.enter(1)
        sent = self.send(home(playing=False, feedback={"kind": "ok", "seq": 5, "skip": -1}))
        self.assertEqual((sent["playing"], sent["feedback"]), (False, {"kind": "ok", "seq": 5, "skip": -1}))
        self.assertEqual(self.beat()["playing"], False, "content is part of latest_frame")
        self.assertNotIn("playing", self.send({**BASE["recent"], "playing": True}))

    def test_all_fields_on_one_line_fit_the_budget(self):
        self.bridge.set_led_tuning(255, False)
        self.connect()
        self.minute = 1439
        self.bridge.post_progress(86400000, 86400000)
        self.enter(1)
        self.bridge.post_progress(86400000, 86400000)
        self.bridge.set_led_tuning(254, True)
        self.clock.now += P.ALIVE_CLOCK_RESEND_SECONDS
        payload = json.loads(json.dumps(home(playing=True, feedback={"kind": "ok", "seq": 0x7FFFFFFF, "skip": -1})))
        payload.update(title="“" * 32, subtitle="\\" * 96, volumeCaption='"' * 96, detail="D" * 96)
        sent = self.send(payload)
        self.assertTrue(set(LATCHED) <= set(sent))
        size = len(self.serial.raw[-1])
        self.assertLessEqual(size, P.FRAME_BUDGET_BYTES)
        print(f"\n[alive wire] escape-heavy Home line with every section 3 field: {size} B")


class PacedLatchedFieldTests(LatchedFieldTests):
    """The same with a cc5.4 knob without artwork2 (frames written by _frame / _heartbeat)."""
    CAPS = AL4


class LimitEventTests(BridgeCase):
    def test_lim_of_the_ready_control_is_a_limit_event(self):
        self.connect()
        self.enter(1)
        self.events()
        for message in ({"id": 1, "lim": 1}, {"id": 1, "lim": -1}, {"id": 1, "lim": 1, "p": 20}):
            self.serial.inject(message)
        self.bridge._read()
        events = [e for e in self.events() if e["kind"] == "limit"]
        self.assertEqual(events, [{"kind": "limit", "id": 1, "dir": 1}, {"kind": "limit", "id": 1, "dir": -1},
                                  {"kind": "limit", "id": 1, "dir": 1}])

    def test_other_lim_messages_are_ignored_without_error(self):
        self.connect()
        self.serial.inject({"id": 1, "lim": 1})     # before any control is ready
        self.bridge._read()
        self.enter(1)
        for message in ({"id": 2, "lim": 1}, {"lim": 1}, {"id": 1, "lim": 0}, {"id": 1, "lim": 2},
                        {"id": 1, "lim": True}, {"id": 1, "lim": "1"}, {"id": 1, "lim": None}, {"id": 1, "lim": 1.0}):
            self.serial.inject(message)
        self.bridge._read()
        self.bridge._service()
        self.assertEqual([e for e in self.events() if e["kind"] in ("limit", "error", "disconnected")], [])
        self.assertIsNotNone(self.bridge.serial)
        self.assertEqual(self.bridge.ready_id, 1)

    def test_desktop_v6_ignores_lim_without_error(self):
        # ALIVE.md section 1: an old host's _consume reads only p/ks/ku/kd of an id-tagged message.
        v6 = v6_device()
        serial = WireSerial(self.clock, A2)
        bridge = v6.DeviceBridge(self.temp.name, lambda port: serial, request_timeout=0.1, autostart=False,
                                 clock=self.clock)
        bridge._connect("COM-FAKE")
        bridge._enter({**control(1), "frame": home()})
        while not bridge.events.empty():
            bridge.events.get_nowait()
        for message in ({"id": 1, "lim": 1}, {"id": 1, "lim": -1}, {"id": 2, "lim": 1}, {"lim": 1}):
            serial.inject(message)
        bridge._read()
        bridge._service()
        self.assertTrue(bridge.events.empty(), "no event, no error")
        self.assertIsNotNone(bridge.serial)
        self.assertEqual(bridge.ready_id, 1)


class DesktopV6IdentityTests(unittest.TestCase):
    """Without `alive` every frame line is byte-identical to desktop v6's (ALIVE.md section 1)."""

    def session(self, module, caps):
        """One scripted session; the exact bytes of every line written and the event kinds."""
        clock = Clock()
        serial = WireSerial(clock, caps)
        with tempfile.TemporaryDirectory() as temp:
            options = {"request_timeout": 0.1, "autostart": False, "clock": clock}
            if module is device:
                options["local_minute"] = lambda: 754
            bridge = module.DeviceBridge(temp, lambda port: serial, **options)
            if module is device:
                bridge.set_led_tuning(200, False)
            bridge._connect("COM-FAKE")
            bridge._enter({**control(1), "frame": home(playing=True, feedback={"kind": "ok", "seq": 3, "skip": 1})})
            bridge._service()
            if module is device:
                bridge.post_progress(83000, 245000)
            bridge._frame({**BASE["volume"], "playing": False, "clock": 9, "id": 1})
            clock.now += 0.6
            bridge._service()
            clock.now += 601
            bridge._frame({**BASE["tracks"], "feedback": {"kind": "ok", "seq": 4, "skip": -1}, "id": 1})
            bridge._service()
            serial.inject({"id": 1, "lim": 1})
            bridge._service()
            bridge._enter({**control(2), "frame": {**BASE["recent"], "playing": True, "ledDrive": 5}})
            clock.now += 0.6
            bridge._service()
            bridge._frame({**BASE["windows"], "progress": {"pos": 1, "dur": 2}, "id": 2})
            clock.now += 0.6
            bridge._service()
            bridge._disconnect()
        return serial.raw

    def test_bridge_lines_are_byte_identical_without_alive(self):
        v6 = v6_device()
        for label, caps in NOT_ALIVE.items():
            with self.subTest(caps=label):
                device._strip_logged.clear()
                new, old = self.session(device, caps), self.session(v6, caps)
                self.assertGreaterEqual(len(old), 12)
                self.assertEqual(new, old)
        # ... and with alive they are not (the check is not vacuous).
        self.assertNotEqual(self.session(device, AL), self.session(v6, AL))

    def test_frames_are_byte_identical_without_alive(self):
        v6 = v6_device()
        inputs = [c["input"] for c in json.loads(V4_FIXTURES.read_text(encoding="utf-8"))["cases"]]
        inputs += [c["input"] for c in json.loads(ALIVE_FIXTURES.read_text(encoding="utf-8"))["cases"]]
        compared = 0
        for label, caps in NOT_ALIVE.items():
            for index, value in enumerate(inputs):
                with self.subTest(caps=label, case=index):
                    try:
                        old = line(v6._frame(deepcopy(value), deepcopy(caps)))
                    except ValueError:
                        old = None
                    try:
                        new = line(_frame(deepcopy(value), deepcopy(caps)))
                    except ValueError:
                        new = None
                    self.assertEqual(new, old)
                    compared += 1
        self.assertGreater(compared, 1000)


if __name__ == "__main__":
    unittest.main()
