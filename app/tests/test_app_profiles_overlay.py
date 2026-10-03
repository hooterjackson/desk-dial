"""app_profiles sidecars (plan sections 1a, 3a, 4b-4d; S1 DD-A): the "overlay": 1 rules, the effective model,
and the bundled sidecars - Onshape's effective profile equals today's tuned layout (onshape_app.RINGS, the
onshape.py constants, ONSHAPE.md sections 1 / 5 / 13 / 15 / 16); Figma and Plasticity map Cmd -> Ctrl and
Option -> Alt; Blender and AutoCAD are basic. Headless."""
from pathlib import Path
import copy
import json
import math
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import app_profiles as ap, onshape, onshape_app  # noqa: E402
from control_center.app_profiles import ProfileError, load_pair, read_json, validate_overlay  # noqa: E402
from control_center.keymap import parse_chord  # noqa: E402

PROFILES = Path(__file__).resolve().parents[1] / "profiles"
IDS = ("onshape", "figma", "plasticity", "blender", "autocad")


def bundled(pid):
    return load_pair(PROFILES / "karl" / f"{pid}.json", PROFILES / f"{pid}.windows.json")


def karl(pid):
    return read_json(PROFILES / "karl" / f"{pid}.json")


def sidecar(pid):
    return read_json(PROFILES / f"{pid}.windows.json")


class OnshapeEquivalenceTests(unittest.TestCase):
    """The effective Onshape model is today's tuned Onshape mode, field by field."""

    @classmethod
    def setUpClass(cls):
        cls.p = bundled("onshape")

    def test_rings_equal_onshape_app(self):
        p = self.p
        self.assertEqual([r.name for r in p.rings], [r.name for r in onshape_app.RINGS])
        for ring, old in zip(p.rings, onshape_app.RINGS):
            self.assertEqual(p.slots[ring.slot].button, old.slot, ring.name)
            self.assertEqual([c.name for c in ring.commands], [c.name for c in old.commands])
            for cmd, want in zip(ring.commands, old.commands):
                with self.subTest(f"{ring.name}/{cmd.name}"):
                    self.assertFalse(cmd.disabled)
                    if want.search:
                        self.assertEqual((cmd.kind, cmd.phrase, cmd.chord), ("actions", want.phrase, None))
                    else:
                        self.assertEqual(cmd.kind, "keys")
                        self.assertEqual(cmd.chord.mods, frozenset(want.mods))
                        self.assertEqual(cmd.chord.key.label, want.key)
                        self.assertIsNone(cmd.chord.key.char)            # letters and digits: by VK
                        self.assertEqual(cmd.chord.key.vk, onshape.chord_vk(want.key))
                    if want.param is None:
                        self.assertIsNone(cmd.param)
                    else:
                        got, old_p = cmd.param, want.param
                        self.assertEqual((got.label, got.start, got.min, got.max, got.decimals, got.steps, got.unit),
                                         (old_p.label, old_p.start, old_p.minimum, old_p.maximum, old_p.decimals,
                                          old_p.steps, old_p.unit))
        self.assertEqual(p.slots["f3"].button, onshape_app.WHEEL_SLOT)

    def test_search_and_param_keys(self):
        p = self.p
        mods, key = onshape_app.SEARCH_CHORD
        self.assertEqual((p.search.mods, p.search.key.label), (frozenset(mods), key))
        self.assertEqual(p.search_open_ms, round(onshape_app.SEARCH_OPEN_S * 1000))
        self.assertEqual(p.search_result_ms, round(onshape_app.SEARCH_RESULT_S * 1000))
        pk = p.param_keys
        self.assertTrue(pk.field)
        self.assertEqual(pk.step_mods, tuple(frozenset(m) for m in onshape_app.STEP_MODIFIERS))
        self.assertEqual(pk.scroll_sign, 1)
        self.assertEqual(pk.select_all, parse_chord("ctrl+a"))
        self.assertEqual((pk.confirm.key.label, pk.cancel.key.label), ("ENTER", "ESC"))

    def test_slot_model(self):
        s = self.p.slots
        knob = s["knob"]
        self.assertEqual((knob.kind, knob.button, knob.wheel_mods, knob.sign, knob.label, knob.fx),
                         ("wheel", None, frozenset(), 1, "ZOOM", "zoom"))
        self.assertEqual(knob.notches_per_turn, onshape.ZOOM_NOTCHES_PER_TURN)
        self.assertEqual(knob.feel, onshape.FALLBACK_PROFILE)
        self.assertEqual(knob.detents, onshape.DEFAULT_DETENTS_PER_TURN)
        drags = {name: s[name] for name in ("f1", "f2", "f4")}
        self.assertEqual({d.button: d.label.lower() for d in drags.values()}, onshape.KeyTracker.MODIFIERS)
        self.assertEqual((drags["f1"].kind, drags["f1"].drag_buttons, drags["f1"].axis_y, drags["f1"].sign),
                         ("drag", frozenset({"right"}), True, onshape.TILT_DRAG_SIGN))
        self.assertEqual((drags["f2"].kind, drags["f2"].drag_buttons, drags["f2"].axis_y),
                         ("drag", frozenset({"right"}), False))
        self.assertEqual((drags["f4"].kind, drags["f4"].drag_buttons, drags["f4"].axis_y),
                         ("drag", frozenset({"middle"}), False))
        for d in drags.values():
            self.assertEqual(round(d.px_per_rad * 2 * math.pi), onshape.PX_PER_TURN)
            self.assertEqual(d.drag_mods, frozenset())
            self.assertIsNone(d.tap)                                    # tap 1 sends nothing; 2 and 4 neither
            self.assertIsNone(d.feel)                                   # fluid while a modifier is held (r4)
            self.assertIsNone(d.detents)
        wheel = s["f3"]
        self.assertEqual((wheel.kind, wheel.button, wheel.tap), ("commands", 2, parse_chord("ctrl+z")))
        mods, key = onshape_app.UNDO_CHORD
        self.assertEqual((wheel.tap.mods, wheel.tap.key.label), (frozenset(mods), key))
        self.assertTrue(self.p.home_chord)
        self.assertEqual(self.p.legend, ("TILT", "ORBIT", "WHEEL", "PAN"))
        self.assertEqual((self.p.status, self.p.name), ("tested", "ONSHAPE"))

    def test_detection_is_onshape_mode(self):
        d = self.p.detect
        self.assertEqual(d.exe, ())
        self.assertEqual(tuple(d.content_class), onshape.CONTENT_CLASSES)
        self.assertEqual(set(d.exclude_host), onshape.NOT_ONSHAPE_HOSTS)
        for host in ("cad.onshape.com", "acme.onshape.com", "www.onshape.com", "onshape.com", "learn.onshape.com",
                     "evilonshape.com", "cad.onshape.com.evil.net", "figma.com", ""):
            self.assertEqual(d.matches_host(host), onshape.host_is_onshape(host), host)

    def test_karl_onshape_differs_and_the_sidecar_overrides(self):
        raw = load_pair(PROFILES / "karl" / "onshape.json")
        self.assertEqual((raw.slots["f1"].kind, raw.slots["f1"].label), ("wheel", "ZOOM"))
        self.assertEqual(raw.slots["f3"].tap, parse_chord("ctrl+z"))        # Cmd+Z -> Ctrl+Z by default
        self.assertEqual(raw.legend, ("ZOOM", "ORBIT", "WHEEL", "PAN"))


class BundledSidecarTests(unittest.TestCase):
    def test_every_bundled_pair_loads(self):
        for pid in IDS:
            with self.subTest(pid):
                self.assertEqual(validate_overlay(sidecar(pid), karl(pid)), [])
                p = bundled(pid)
                self.assertEqual(p.id, pid)
                self.assertEqual(p.warnings, ())
                self.assertTrue(p.home_chord)

    def test_status_and_detection(self):
        want = {"onshape": ("tested", (), ("cad.onshape.com", "*.onshape.com")),
                "figma": ("community", ("Figma.exe",), ("figma.com", "www.figma.com")),
                "plasticity": ("community", ("Plasticity.exe",), ()),
                "blender": ("basic", ("blender.exe",), ()),
                "autocad": ("basic", ("acad.exe",), ())}
        for pid, (status, exe, host) in want.items():
            p = bundled(pid)
            self.assertEqual((p.status, p.detect.exe, p.detect.host), (status, exe, host), pid)
        figma = bundled("figma").detect
        self.assertTrue(figma.matches_exe(r"C:\Users\someone\AppData\Local\Figma\app-1\Figma.exe"))
        self.assertTrue(figma.matches_exe("figma.exe"))
        self.assertFalse(figma.matches_exe("FigmaAgent.exe"))
        self.assertTrue(figma.matches_host("www.figma.com"))
        self.assertFalse(figma.matches_host("help.figma.com"))

    def test_basic_profiles_scroll_only(self):
        for pid in ("blender", "autocad"):
            p = bundled(pid)
            self.assertEqual(p.rings, ())
            self.assertEqual(p.slots["knob"].kind, "wheel")
            self.assertEqual([s.kind for name, s in p.slots.items() if name != "knob"], ["none"] * 4)

    def test_figma_default_mapping(self):
        p = bundled("figma")
        chords = {f"{r.name}/{c.name}": c.chord for r in p.rings for c in r.commands}
        for ref, text in {"STRUCTURE/ADD AUTO LAYOUT": "shift+a", "STRUCTURE/REMOVE AUTO LAYOUT": "shift+alt+a",
                          "STRUCTURE/WRAP IN FRAME": "ctrl+alt+g", "STRUCTURE/GROUP": "ctrl+g",
                          "ALIGN/ALIGN LEFT": "alt+a", "ALIGN/ALIGN CENTER": "alt+h", "ALIGN/ALIGN RIGHT": "alt+d",
                          "ALIGN/ALIGN TOP": "alt+w", "ALIGN/ALIGN MIDDLE": "alt+v", "ALIGN/ALIGN BOTTOM": "alt+s",
                          "ALIGN/TIDY UP": "ctrl+alt+t", "COMPONENTS/CREATE COMPONENT": "ctrl+alt+k",
                          "COMPONENTS/DETACH INSTANCE": "ctrl+alt+b", "UTILITY/COPY PROPERTIES": "ctrl+alt+c",
                          "UTILITY/PASTE PROPERTIES": "ctrl+alt+v", "UTILITY/RENAME": "ctrl+r",
                          "UTILITY/RUN LAST PLUGIN": "ctrl+alt+p"}.items():
            self.assertEqual(chords[ref], parse_chord(text), ref)
        self.assertEqual(p.search, parse_chord("ctrl+k"))
        self.assertEqual(p.slots["knob"].wheel_mods, frozenset({"ctrl"}))
        self.assertEqual((p.slots["f1"].cw, p.slots["f1"].ccw), (parse_chord("ctrl+shift+z"), parse_chord("ctrl+z")))
        self.assertEqual((p.slots["f2"].cw, p.slots["f2"].ccw), (parse_chord("enter"), parse_chord("shift+enter")))
        self.assertEqual(p.slots["f3"].kind, "commands")

    def test_plasticity_default_mapping(self):
        p = bundled("plasticity")
        chords = {c.name: c.chord for r in p.rings for c in r.commands}
        for name, text in {"EXTRUDE": "e", "FILLET": "b", "BOOLEAN": "q", "CUT": "c", "MOVE": "g", "ROTATE": "r",
                           "SCALE": "s", "DUPLICATE": "shift+d", "MIRROR": "alt+x", "DELETE": "shift+x",
                           "CONTROL POINTS": "1", "ALL TYPES": "tab", "INVERT": "alt+a", "FRONT": "num1",
                           "RIGHT": "num3", "TOP": "num7", "PERSPECTIVE": "num5", "FOCUS": "/", "ISOLATE": ".",
                           "UNISOLATE": "alt+."}.items():
            self.assertEqual(chords[name], parse_chord(text), name)
        self.assertEqual(p.search, parse_chord("f"))
        knob = p.slots["knob"]
        self.assertEqual((knob.kind, knob.drag_buttons, knob.drag_mods, knob.axis_y, knob.sign, knob.haptic),
                         ("drag", frozenset({"middle"}), frozenset({"ctrl"}), True, -1, "viscose"))
        rot = next(c.param for r in p.rings for c in r.commands if c.name == "ROTATE")
        self.assertEqual((rot.deg, rot.axes, rot.planes, rot.axis_default), (True, True, False, 2))
        self.assertEqual(p.param_keys.axis, (parse_chord("x"), parse_chord("y"), parse_chord("z")))
        self.assertEqual(p.param_keys.numeric, parse_chord("tab"))


class OverlayRuleTests(unittest.TestCase):
    def setUp(self):
        self.karl = karl("figma")
        self.base = {"overlay": 1}

    def problems(self, **extra):
        doc = dict(self.base, **extra)
        return validate_overlay(doc, self.karl)

    def bad(self, fragment, **extra):
        problems = self.problems(**extra)
        self.assertTrue(any(fragment in p for p in problems), (fragment, problems))

    def test_minimal_and_version(self):
        self.assertEqual(self.problems(), [])
        self.assertTrue(validate_overlay({}, self.karl))
        self.assertTrue(validate_overlay({"overlay": 2}, self.karl))
        self.assertTrue(validate_overlay({"overlay": True}, self.karl))
        self.assertEqual(validate_overlay([], self.karl), ["not a JSON object"])

    def test_unknown_keys(self):
        self.bad('unknown key', colour="red")
        self.bad("detect.window_title", detect={"window_title": ["x"]})
        self.bad("slots.knob.speed", slots={"knob": {"speed": 3}})
        self.bad("slots.f9", slots={"f9": {}})
        self.bad("unknown key (unit)", params={"*/X": {"scale": 1}})

    def test_status_gui_notes_legend(self):
        self.bad("status", status="great")
        # S3 decision: the "gui" option is gone (Karl's Cmd is always Ctrl; "keys" overrides one shortcut). A sidecar
        # that still has it is refused in plain words, whatever its value.
        for value in ("ctrl", "win", "alt"):
            problems = self.problems(gui=value)
            self.assertEqual(problems, [ap.GUI_REMOVED], value)
        self.assertEqual(ap.GUI_REMOVED, "gui: this option was removed. Karl's Cmd is always Ctrl on "
                                                   "Windows; use \"keys\" to change a single shortcut.")
        self.assertNotIn("gui", ap.OVERLAY_KEYS)
        self.bad("notes", notes=["x" * 401])
        self.bad("notes", notes=["caf\u00e9"])
        self.bad("legend", legend=["A", "B"])
        self.bad("legend[0]", legend=["LONGERX1", None, None, None])
        self.assertEqual(self.problems(legend=["A", None, None, None]), [])

    def test_privacy_rules_are_bare(self):
        for host in ("https://www.figma.com", "www.figma.com/file/abc", "www.figma.com:443", "figma", "*.", "*",
                     "user@figma.com", "www.figma.com?x=1", "WWW.FIGMA.COM ", "a..b.com", "-a.com", ""):
            self.bad("bare host", detect={"host": [host]})
        for exe in (r"C:\Program Files\Figma\Figma.exe", "Figma", "../Figma.exe", "*.exe", "Fig ma.exe\n", "a/b.exe"):
            self.bad("program file name", detect={"exe": [exe]})
        self.bad("window class", detect={"content_class": ["has space"]})
        self.bad("a list of up to 32", detect={"host": ["a.com"] * 33})
        self.assertEqual(self.problems(detect={"exe": ["Figma.exe"], "host": ["*.figma.com", "figma.com"],
                                               "exclude_host": ["help.figma.com"],
                                               "content_class": ["Chrome_RenderWidgetHostHWND"]}), [])

    def test_keys(self):
        self.assertEqual(self.problems(keys={"ALIGN/TIDY UP": "ctrl+alt+t", "*/RENAME": "f2",
                                             "UTILITY/COPY PROPERTIES": None,
                                             "STRUCTURE/GROUP": {"chord": None, "disabled_reason": "Use Ctrl+G"},
                                             "@search": "ctrl+/"}), [])
        self.bad("no command called that", keys={"ALIGN/NOPE": "ctrl+z"})
        self.bad("no command called that", keys={"*/NOPE": "ctrl+z"})
        self.bad("no command called that", keys={"TIDY UP": "ctrl+z"})
        self.bad('"cmd+z"', keys={"ALIGN/TIDY UP": "cmd+z"})
        self.bad("a chord", keys={"ALIGN/TIDY UP": 5})
        self.bad("unknown name", keys={"@menu": "f1"})
        self.bad("only goes with chord null", keys={"ALIGN/TIDY UP": {"chord": "f1", "disabled_reason": "x"}})
        self.bad("unknown key", keys={"ALIGN/TIDY UP": {"chord": None, "why": "x"}})

    def test_key_overrides_apply(self):
        doc = dict(self.base, keys={"ALIGN/TIDY UP": "ctrl+alt+y", "*/RENAME": "f2", "UTILITY/COPY PROPERTIES": None,
                                    "STRUCTURE/GROUP": {"chord": None, "disabled_reason": "Not in Figma for Windows"},
                                    "COMPONENTS/GO TO MAIN": "ctrl+alt+m", "@search": "ctrl+/"})
        p = ap._build(self.karl, doc, source="bundled", karl_sha256="", rules=None)
        cmds = {f"{r.name}/{c.name}": c for r in p.rings for c in r.commands}
        self.assertEqual(cmds["ALIGN/TIDY UP"].chord, parse_chord("ctrl+alt+y"))
        self.assertEqual(cmds["UTILITY/RENAME"].chord, parse_chord("f2"))
        self.assertEqual((cmds["UTILITY/COPY PROPERTIES"].disabled, cmds["UTILITY/COPY PROPERTIES"].disabled_reason,
                          cmds["UTILITY/COPY PROPERTIES"].chord), (True, "Not on Windows", None))
        self.assertEqual(cmds["STRUCTURE/GROUP"].disabled_reason, "Not in Figma for Windows")
        self.assertEqual((cmds["COMPONENTS/GO TO MAIN"].kind, cmds["COMPONENTS/GO TO MAIN"].phrase),
                         ("keys", None))
        self.assertEqual(p.search, parse_chord("ctrl+/"))
        blob = ap.decode_wire(p.wire())
        self.assertTrue(blob["features"] & ap.F_DISABLED_CMDS)
        flags = {f"{r['name']}/{c['name']}": c for r in blob["rings"] for c in r["cmds"]}
        self.assertEqual(flags["UTILITY/COPY PROPERTIES"]["flags"], ap.CMD_DISABLED)
        self.assertEqual(flags["COMPONENTS/GO TO MAIN"]["flags"], 0)
        self.assertEqual((flags["ALIGN/TIDY UP"]["mod"], flags["ALIGN/TIDY UP"]["key"]), (1 | 4, "Y"))

    def test_slots(self):
        self.assertEqual(self.problems(slots={"knob": {"notches_per_turn": 24, "feel": "BINARIS BEER", "detents": 67},
                                              "f1": {"tap": "ctrl+z", "cw": None, "modifier": "ctrl+shift"},
                                              "f4": {"button": 1}, "f2": {"button": 3}}), [])
        self.bad("slots.knob.button", slots={"knob": {"button": 0}})
        self.bad("slots.f1.button", slots={"f1": {"button": 4}})
        self.bad("already selects", slots={"f1": {"button": 1}})
        self.bad("notches_per_turn", slots={"knob": {"notches_per_turn": 0}})
        self.bad("slots.knob.detents", slots={"knob": {"detents": 1001}})
        self.bad("slots.knob.feel", slots={"knob": {"feel": ""}})
        self.bad("slots.knob.haptic", slots={"knob": {"haptic": "rough"}})
        self.bad("slots.f1.tap", slots={"f1": {"tap": "hyper+z"}})
        self.bad("slots.f1.modifier", slots={"f1": {"modifier": "cmd"}})
        self.bad("slots.f1.macro", slots={"f1": {"macro": "NOPE"}})
        self.bad("slots.f1.kind", slots={"f1": {"kind": "fly"}})

    def test_params(self):
        k = karl("onshape")
        self.assertEqual(validate_overlay({"overlay": 1, "params": {"*/EXTRUDE": {"unit": "in"}}}, k), [])
        self.assertTrue(validate_overlay({"overlay": 1, "params": {"*/SKETCH": {"unit": "mm"}}}, k))
        self.assertTrue(validate_overlay({"overlay": 1, "params": {"*/EXTRUDE": {"unit": "millimetre"}}}, k))
        self.assertTrue(validate_overlay({"overlay": 1, "params": {"*/NOPE": {"unit": "mm"}}}, k))

    def test_broken_karl_update_breaks_the_pair(self):
        """Karl renames a command the sidecar names: the pair is refused, with the reference in the message."""
        k = karl("onshape")
        k["rings"][0]["cmds"][1]["name"] = "EXTRUDE2"
        problems = validate_overlay(sidecar("onshape"), k)
        self.assertTrue(any('params."MODEL/EXTRUDE"' in p for p in problems), problems)

    def test_search_needed(self):
        doc = dict(self.base, keys={"@search": None})
        self.assertTrue(any("search" in p for p in validate_overlay(doc, self.karl)))

    def test_load_pair_names_the_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "figma.windows.json"
            bad.write_text(json.dumps({"overlay": 1, "keys": {"X/Y": "f1"}}))
            with self.assertRaises(ProfileError) as ctx:
                load_pair(PROFILES / "karl" / "figma.json", bad)
            self.assertTrue(ctx.exception.problems[0].startswith("figma.windows.json: keys."))
            broken = copy.deepcopy(karl("figma"))
            broken["name"] = ""
            kp = Path(tmp) / "figma.json"
            kp.write_text(json.dumps(broken))
            with self.assertRaises(ProfileError) as ctx:
                load_pair(kp)
            self.assertEqual(ctx.exception.problems, ["figma.json: name: 1..15 characters"])

    def test_unmappable_karl_key_disables_the_command(self):
        k = karl("figma")
        k["rings"][0]["cmds"][0]["key"] = [0, 0x32]                 # Europe 1: no Windows key
        k["slots"]["f1"]["tap"] = [8, 0x32]
        k["rings"][1]["cmds"][0]["key"] = [9, 4]                    # Ctrl+Cmd+A: collapses to Ctrl+A
        p = ap._build(k, {}, source="user", karl_sha256="", rules=None)
        cmd = p.rings[0].commands[0]
        self.assertEqual((cmd.disabled, cmd.disabled_reason, cmd.chord), (True, "No Windows key", None))
        self.assertIsNone(p.slots["f1"].tap)
        self.assertEqual(len(p.warnings), 3)
        self.assertTrue(any("collapse" in w for w in p.warnings))


class ReadmeTests(unittest.TestCase):
    def test_the_author_guide_example_is_a_valid_figma_sidecar(self):
        text = (PROFILES / "README.md").read_text(encoding="utf-8")
        example = text.split("```json", 1)[1].split("```", 1)[0]
        self.assertEqual(validate_overlay(json.loads(example), karl("figma")), [])
        for key in ap.OVERLAY_KEYS:
            self.assertIn(f"| `{key}", text)


if __name__ == "__main__":
    unittest.main()
