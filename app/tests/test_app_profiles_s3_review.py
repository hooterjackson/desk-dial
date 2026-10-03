"""S3 adversarial review of the Desk Dial side of app profiles: each class is one finding (DD-<n>), proven here first.
Fakes only: a recording backend (never SendInput), temporary folders, no network, no window."""
from dataclasses import replace
from pathlib import Path
import json
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cc5_support import Clock  # noqa: E402
from test_app_engine import Backend  # noqa: E402

from control_center import app_engine as E, app_profiles as ap, keymap  # noqa: E402

PROFILES = Path(__file__).resolve().parents[1] / "profiles"
CONTROL = 5
LWIN, ENTER, R_KEY, TAB, F4_KEY, ESC, W_KEY = 0xE3, 0x28, 0x15, 0x2B, 0x3D, 0x29, 0x1A
CMD, OPT, CTRL = 8, 4, 1                      # Karl's KEYBOARD_MODIFIER_LEFTGUI / LEFTALT / LEFTCTRL


def karl_doc(pid="evil", **extra):
    """Karl's Blender template as a new profile with a tap slot on button 1 (its macro or chord fires on press)."""
    doc = json.loads((PROFILES / "karl" / "blender.json").read_text(encoding="ascii"))
    doc.update(id=pid, name=pid.upper())
    doc.update(extra)
    return doc


def write_pair(folder, doc, overlay=None):
    folder.mkdir(parents=True, exist_ok=True)
    karl = folder / f"{doc['id']}.json"
    karl.write_text(json.dumps(doc), encoding="ascii")
    side = None
    if overlay is not None:
        side = folder / f"{doc['id']}.windows.json"
        side.write_text(json.dumps(overlay), encoding="ascii")
    return karl, side


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def load(self, doc, overlay=None):
        return ap.load_pair(*write_pair(self.tmp / "in", doc, overlay))

    def refused(self, doc, overlay=None):
        with self.assertRaises(ap.ProfileError) as caught:
            self.load(doc, overlay)
        return " ".join(caught.exception.problems)


# ================================================================================================ DD-1
class DangerousChordTests(TmpCase):
    """DD-1 (P0): a profile could bind chords that leave the app. The gates are checked before each SendInput, but a
    Win press opens Start asynchronously and Windows hands the keys typed next to its search box: a macro
    [Win] [text "cmd /c ..."] [Enter] ran a program from a profile file. Such chords are refused at load (the
    import shows why) and again at send time."""

    def macro_profile(self, steps, overlay=None):
        doc = karl_doc(macros=[{"name": "RUN", "steps": steps}],
                       slots={"knob": {"kind": "wheel", "label": "SCROLL", "sign": 1},
                              "f1": {"kind": "tap", "label": "GO", "macro": "RUN"}})
        return doc, overlay or {"overlay": 1, "detect": {"exe": ["evil.exe"]}}

    def test_a_win_key_macro_is_refused(self):
        doc, overlay = self.macro_profile([{"key": [0, LWIN]}, {"text": "cmd /c calc"}, {"key": [0, ENTER]}])
        self.assertIn("Windows key", self.refused(doc, overlay))

    def test_win_r_through_gui_win_is_refused(self):
        doc, overlay = self.macro_profile([{"key": [CMD, R_KEY]}, {"wait": 300}, {"text": "calc"},
                                           {"key": [0, ENTER]}],
                                          {"overlay": 1, "gui": "win", "detect": {"exe": ["evil.exe"]}})
        self.assertIn("this option was removed", self.refused(doc, overlay), "S3 decision: no gui option at all")
        del overlay["gui"]
        macro = self.load(doc, overlay).macros["RUN"]
        self.assertEqual(macro[0].chord.mods, frozenset({"ctrl"}), "Cmd is always Ctrl: Cmd+R is Ctrl+R")

    def test_alt_tab_alt_f4_ctrl_esc_are_refused(self):
        for key in ([OPT, TAB], [OPT, F4_KEY], [CTRL, ESC], [CTRL | 2, ESC]):
            with self.subTest(key=key):
                doc, overlay = self.macro_profile([{"key": key}])
                self.refused(doc, overlay)

    def test_a_sidecar_chord_is_refused_too(self):
        doc = karl_doc(slots={"knob": {"kind": "wheel", "label": "SCROLL", "sign": 1}})
        for chord in ("win+r", "alt+f4", "alt+shift+tab", "ctrl+shift+esc"):
            with self.subTest(chord=chord):
                overlay = {"overlay": 1, "detect": {"exe": ["evil.exe"]},
                           "slots": {"f1": {"kind": "keys", "label": "X", "cw": chord, "ccw": "z"}}}
                self.assertIn("blocked", self.refused(doc, overlay))

    def test_browser_reserved_chords_are_refused_for_a_website_profile_only(self):
        doc = karl_doc(slots={"knob": {"kind": "wheel", "label": "SCROLL", "sign": 1},
                              "f1": {"kind": "tap", "label": "X", "cw": [CTRL, W_KEY]}})
        web = {"overlay": 1, "detect": {"host": ["evil.example.com"]}}
        self.assertIn("blocked", self.refused(doc, web))
        desktop = self.load(doc, {"overlay": 1, "detect": {"exe": ["evil.exe"]}})
        self.assertEqual(keymap.chord_text(desktop.slots["f1"].cw), "ctrl+w")

    def test_validate_overlay_reports_it(self):
        doc, overlay = self.macro_profile([{"key": [0, LWIN]}])
        self.assertTrue(any("blocked" in p for p in ap.validate_overlay(overlay, doc)))

    def test_shipped_profiles_still_load(self):
        lib = ap.Library(PROFILES)
        self.assertEqual(lib.problems, [])
        self.assertEqual(len(lib.profiles()), 5)

    def test_the_engine_refuses_a_blocked_chord_that_reached_it(self):
        """Defence in depth: a profile built around the validator (or a rule that made it a website profile) still
        sends nothing of a command holding a blocked chord."""
        doc, overlay = self.macro_profile([{"text": "x"}])
        profile = self.load(doc, overlay)
        win_r = keymap.parse_chord("win+r")
        macros = {"RUN": (ap.MacroStep("key", win_r, None, 0), ap.MacroStep("text", None, "calc", 0),
                          ap.MacroStep("key", keymap.parse_chord("enter"), None, 0))}
        profile = replace(profile, macros=macros)
        clock = Clock(50.0)
        backend = Backend(clock)
        backend.target_ok = lambda point: True
        backend.focus_ok = lambda point: True
        inj = E.AppInjector(backend, clock=clock, start=False, profile=profile)
        inj.activate(CONTROL, [0, 1, 2, 3], 48, app=True)
        inj.step()
        inj.post("button", {"id": CONTROL, "button": 0, "index": 0})
        inj.step()
        self.assertEqual(backend.events(), [])
        self.assertIn(E.DISABLED_REFUSED, inj.take_events())

    def test_blocked_reasons(self):
        self.assertIsNone(keymap.blocked(keymap.parse_chord("ctrl+alt+t")))
        self.assertIsNone(keymap.blocked(keymap.parse_chord("ctrl+w")))
        self.assertIsNotNone(keymap.blocked(keymap.parse_chord("ctrl+w"), browser=True))
        self.assertIsNone(keymap.blocked(keymap.parse_chord("alt+d"), browser=True))      # Figma's ALIGN RIGHT
        self.assertIsNotNone(keymap.blocked(keymap.parse_chord("f12"), browser=True))
        self.assertIsNotNone(keymap.blocked(keymap.parse_chord("ctrl+shift+j"), browser=True))
        self.assertIsNotNone(keymap.blocked(keymap.parse_chord("lwin")))
        self.assertIsNotNone(keymap.blocked(keymap.parse_chord("alt+space")))


# ================================================================================================ DD-2
class ShellTargetTests(TmpCase):
    """DD-2 (P1): a profile's detection could name a shell, a terminal or Windows' own shell (Start, Explorer): its
    macros' text then went into a command line (and Enter ran it), all through the gates, since that program WAS the
    detected app. Such programs are refused as rules (sidecar, settings) and never pass the cursor gate."""

    SHELLS = ("cmd.exe", "PowerShell.exe", "pwsh.exe", "WindowsTerminal.exe", "wt.exe", "conhost.exe",
              "OpenConsole.exe", "explorer.exe", "StartMenuExperienceHost.exe", "SearchHost.exe", "wsl.exe",
              "bash.exe", "mshta.exe", "regedit.exe", "Taskmgr.exe")

    def test_the_sidecar_cannot_target_a_shell(self):
        doc = karl_doc()
        for exe in self.SHELLS:
            with self.subTest(exe=exe):
                problems = ap.validate_overlay({"overlay": 1, "detect": {"exe": [exe]}}, doc)
                self.assertTrue(any("program file name" in p for p in problems), problems)
        self.assertEqual(ap.validate_overlay({"overlay": 1, "detect": {"exe": ["Figma.exe"]}}, doc), [])

    def test_settings_rules_cannot_target_a_shell(self):
        from control_center import ui
        with self.assertRaises(ValueError):
            ui.normal_rule("exe", r"C:\Windows\System32\cmd.exe")
        self.assertEqual(ui.normal_app_rules({"figma": {"exe": ["WindowsTerminal.exe", "Figma.exe"]}}),
                         {"figma": {"exe": ["Figma.exe"]}})

    def test_the_cursor_gate_refuses_a_shell_whatever_the_profile_says(self):
        from control_center import app_detect as D
        from test_app_detect import FakeWindows
        profile = replace(self.load(karl_doc(), {"overlay": 1, "detect": {"exe": ["evil.exe"]}}),
                          detect=ap.Detect(exe=("cmd.exe",)))
        w = FakeWindows()
        w.exes[8] = "cmd.exe"
        w.fg, w.under = 0x200, 0x201
        self.assertFalse(D.gate_target(w, profile, (1, 1)))


# ================================================================================================ DD-3
class EvictionTests(unittest.TestCase):
    """DD-3 (P2, also the firmware review's): the knob's store is an LRU of 4 profiles in 128 KB, but Desk Dial kept
    every (id, crc) it ever loaded for the whole connection. After a 5th app (or a full budget) evicted one, switching
    back sent its id / crc and the knob drew "Loading..." until a reconnect. Each activation of an app now re-checks
    (the bridge's list answers "present" without sending the profile again, or the profile uploads again), with the
    text screen meanwhile; Onshape stays on the built-in canvas and is never uploaded."""

    def test_returning_to_an_app_rechecks_the_knob_before_drawing_its_canvas(self):
        from test_app_runtime import FakeDetector, Harness
        detector = FakeDetector(("figma", "exe"))
        h = Harness(self, detector=detector, modes={"figma": "auto", "plasticity": "auto", "onshape": "auto"})
        h.tick(1000.0)
        h.injector.step()
        h.loaded("figma")
        h.tick(1000.1)
        self.assertIn("app", h.frame())
        detector.value = ("plasticity", "exe")
        h.tick(1000.2)
        h.tick(1000.3)
        h.loaded("plasticity")
        detector.value = ("figma", "exe")              # back: the knob may have evicted Figma meanwhile
        h.tick(1000.4)
        h.injector.step()
        h.tick(1000.5)
        self.assertEqual(h.c.app_id(), "figma")
        self.assertNotIn("app", h.frame(), "no canvas the knob may not have: the text screen until it says so")
        self.assertEqual([u["id"] for u in h.uploads()], ["figma", "plasticity", "figma"])
        figma = h.library.get("figma")
        h.event("app-profile", id="figma", crc=figma.wire_crc, state="present", bytes=len(figma.wire()), ms=3)
        h.tick(1000.6)
        self.assertEqual(h.frame()["app"]["id"], "figma")
        self.assertEqual(len(h.uploads()), 3, "one check per activation, not one per tick")
        detector.value = ("onshape", "host")
        h.tick(1000.7)
        h.tick(1000.8)
        self.assertEqual(h.c.app_id(), "onshape")
        self.assertNotIn("onshape", [u["id"] for u in h.uploads()], "Onshape is never uploaded")


# ================================================================================================ DD-5
class SidecarImportReadTests(TmpCase):
    """DD-5 (P3): Library.import_file read the sibling .windows.json with an unbounded read_bytes() (a huge file was
    read whole before the size check), and validated a second read of the file but wrote the first: a sidecar swapped
    in between was written unchecked. The size is checked before reading (FILE_MAX), and the bytes written are exactly
    the bytes validated."""

    def setUp(self):
        super().setUp()
        self.user = self.tmp / "user"
        self.lib = ap.Library(PROFILES, self.tmp / "updates", self.user)
        self.karl, self.side = write_pair(self.tmp / "in", karl_doc("myapp"), {"overlay": 1, "colour": "red"})

    def test_a_huge_sidecar_is_refused_before_it_is_read(self):
        self.side.write_bytes(b" " * (ap.FILE_MAX + 1))
        original = Path.read_bytes

        def guarded(path):
            if path.name.endswith(".windows.json"):
                raise AssertionError("the sidecar was read whole")
            return original(path)
        with mock.patch.object(Path, "read_bytes", guarded):
            with self.assertRaises(ap.ProfileError) as caught:
                self.lib.import_file(self.karl)
        self.assertIn("myapp.windows.json: bigger than 128 KB", caught.exception.problems)
        self.assertFalse(self.user.exists() and any(self.user.iterdir()))

    def test_the_bytes_written_are_the_bytes_validated(self):
        good = json.dumps({"overlay": 1, "detect": {"exe": ["myapp.exe"]}}).encode("ascii")
        original = ap.read_json

        def swap_then_read(source, name="profile"):
            if isinstance(source, Path) and source == self.side:
                source.write_bytes(good)               # swapped after the first read, before the check
            return original(source, name)
        with mock.patch.object(ap, "read_json", swap_then_read):
            with self.assertRaises(ap.ProfileError) as caught:
                self.lib.import_file(self.karl)
        self.assertTrue(any("colour" in p for p in caught.exception.problems), caught.exception.problems)
        self.assertFalse(self.user.exists() and any(self.user.iterdir()), "nothing unchecked is written")

    def test_a_good_pair_still_imports_byte_for_byte(self):
        raw = json.dumps({"overlay": 1, "detect": {"exe": ["myapp.exe"]}}).encode("ascii")
        self.side.write_bytes(raw)
        self.assertEqual(self.lib.import_file(self.karl).source, "user")
        self.assertEqual((self.user / "myapp.windows.json").read_bytes(), raw)


# ================================================================================================ DD-6
import test_app_profiles_upload as _upload  # noqa: E402


class UploadRetryDrainTests(unittest.TestCase):
    """DD-6 (P3): the upload's one retry was consumed by the stale reply to a line already sent. After a failed begin
    the bridge had already written the first data line (a begin that works gets no reply), and the knob answers that
    line "order"; after a late ack, the ack itself arrives during the retry. Either reply failed the retry at once. The
    retry now drains first: a `list` line, every reply ignored until the list's answer (the knob answers in order)."""

    setUp = _upload.UploadTests.setUp
    events = _upload.UploadTests.events
    run_passes = _upload.UploadTests.run_passes
    upload = _upload.UploadTests.upload

    def test_a_failed_begin_retries_once_and_loads(self):
        self.serial.delay = 0.02                     # the first data line is out before the begin's error is back
        self.serial.fail = ["begin"]
        events = self.upload()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["state"], "loaded", events)
        self.assertEqual(self.serial.store["figma"], (self.profile.wire_crc, self.profile.wire()))

    def test_a_late_ack_retries_once_and_loads(self):
        self.serial.late = {2250: 1.2}               # the second ack comes after the 1 s timeout
        events = self.upload()
        self.assertEqual(events[0]["state"], "loaded", events)
        self.assertEqual(self.serial.store["figma"], (self.profile.wire_crc, self.profile.wire()))

    def test_a_late_ok_is_found_by_the_drain_list(self):
        self.serial.late = {}
        self.bridge._dispatch("app_profile", self.request)
        self.serial.store["figma"] = (self.profile.wire_crc, self.profile.wire())   # the knob did load it
        self.bridge._service()
        self.bridge._app_upload.update(waiting=None, stage="begin")
        self.bridge._app_profile_fail("timeout")                                    # as a timed-out end
        self.run_passes()
        self.assertEqual(self.events("app-profile")[0]["state"], "present")

    def test_without_a_list_answer_the_retry_begins_after_the_timeout(self):
        self.bridge._dispatch("app_profile", self.request)
        self.bridge._service()
        self.bridge._app_profile_fail("timeout")
        self.assertEqual(self.bridge._app_upload["stage"], "drain")
        self.bridge._app_profile_reply({"error": "order"})
        self.bridge._app_profile_reply({"ack": 2250})
        self.assertIsNotNone(self.bridge._app_upload, "stale replies are ignored while draining")
        self.assertEqual(self.events("app-profile"), [])


# ================================================================================================ DD-7
class ReservedIdTests(TmpCase):
    """DD-7 (P3): a profile id that is a Windows device name (con, prn, aux, nul, com0-9, lpt0-9) names a file Windows
    opens as that device ("nul.json" reads empty, "com1.json" opens a port). Refused, case-insensitive and with any
    extension, by the validator, the importer, the Library's file scan, the updater's index and make_index. No such
    file is ever created here: the scans are fed the paths."""

    RESERVED = ("con", "prn", "aux", "nul", "com0", "com1", "com9", "lpt0", "lpt1", "lpt9")

    def test_the_names(self):
        for name in self.RESERVED + ("CON", "Nul.json", "lpt1.windows.json", "com9.txt", "AUX.tar.gz"):
            self.assertTrue(ap.reserved_id(name), name)
        for name in ("console", "com", "com10", "lpt", "nul1", "auxx", "figma", "con_1", "c-on"):
            self.assertFalse(ap.reserved_id(name), name)
        self.assertFalse(ap.valid_id("nul"))
        self.assertTrue(ap.valid_id("figma"))

    def test_the_validator_refuses_them(self):
        for pid in self.RESERVED:
            with self.subTest(pid=pid):
                problems = ap.validate_karl(karl_doc(pid))
                self.assertIn(ap.RESERVED_ID_PROBLEM, problems)

    def test_the_importer_refuses_them_and_writes_nothing(self):
        user = self.tmp / "user"
        lib = ap.Library(PROFILES, self.tmp / "updates", user)
        doc = karl_doc("aux")
        source = self.tmp / "in" / "download.json"               # a safe file name holding a reserved id
        source.parent.mkdir(parents=True)
        source.write_text(json.dumps(doc), encoding="ascii")
        with self.assertRaises(ap.ProfileError) as caught:
            lib.import_file(source)
        self.assertIn(f"download.json: {ap.RESERVED_ID_PROBLEM}", caught.exception.problems)
        self.assertFalse(user.exists() and any(user.iterdir()))
        with mock.patch.object(Path, "stat", side_effect=AssertionError("opened")):
            with self.assertRaises(ap.ProfileError) as caught:
                lib.import_file(self.tmp / "in" / "COM1.json")              # picked by name: never opened
        self.assertEqual(caught.exception.problems, [f"COM1.json: {ap.RESERVED_ID_PROBLEM}"])

    def test_the_library_scan_skips_the_file_unread(self):
        user = self.tmp / "user"
        lib = ap.Library(PROFILES, self.tmp / "updates", user)
        fake = user / "nul.json"
        real_files = ap._karl_files
        with mock.patch.object(ap, "_karl_files", lambda folder: real_files(folder) + ([fake] if folder == user else [])),                 mock.patch.object(ap, "load_pair", refuse(fake)):
            problems = lib.reload()
        self.assertTrue(any("nul.json" in p and "Windows device name" in p for p in problems), problems)
        self.assertEqual(len(lib.profiles()), 5)

    def test_the_updater_index_refuses_them(self):
        from control_center import profile_updates as pu
        entry = {"id": "com1", "file": "karl/com1.json", "sha256": "0" * 64, "bytes": 10, "desk_dial_min": "2.0.0"}
        data = json.dumps({"format": pu.INDEX_FORMAT, "profiles": [entry]}).encode("ascii")
        with self.assertRaises(pu.UpdateError):
            pu.parse_index(data)
        entry.update(id="com10", file="karl/com10.json")
        self.assertEqual(len(pu.parse_index(json.dumps({"format": pu.INDEX_FORMAT, "profiles": [entry]})
                                            .encode("ascii"))), 1)

    def test_make_index_refuses_them_unread(self):
        sys.path.insert(0, str(PROFILES.parent / "tools" / "profiles"))
        import make_index
        fake = PROFILES / "karl" / "lpt1.json"
        real_glob = Path.glob

        def glob(path, pattern):
            found = list(real_glob(path, pattern))
            return found + [fake] if path == PROFILES / "karl" else found
        with mock.patch.object(Path, "glob", glob), mock.patch.object(ap, "load_pair", refuse(fake)):
            with self.assertRaises(ap.ProfileError) as caught:
                make_index.build_index(PROFILES)
        self.assertTrue(any("lpt1.json" in p and "Windows device name" in p for p in caught.exception.problems),
                        caught.exception.problems)


def refuse(fake, real_load=ap.load_pair):
    """load_pair that fails the test if it is asked to read ``fake`` (a device name is never opened)."""
    def load(path, *args, **kwargs):
        if Path(path) == fake:
            raise AssertionError(f"{fake.name} was read")
        return real_load(path, *args, **kwargs)
    return load


# ================================================================================================ DD-8
from test_app_engine import EngineCase  # noqa: E402


class MacroQueueCapTests(EngineCase):
    """DD-8 (P3): while a macro waits, every further tap queued behind it, without a bound: hammering a button queued
    dozens of macros that then ran for seconds after the user stopped. At most one pending macro per slot and
    MACRO_QUEUE_MAX pending in all; an extra tap is dropped and counted (status.json app.injector.macrosDropped)."""
    PROFILE = "figma"

    def setUp(self):
        super().setUp()
        p = self.profile
        macros = {"SAVE_AS": (ap.MacroStep("key", keymap.parse_chord("ctrl+shift+s"), None, 0),
                              ap.MacroStep("wait", None, None, 150), ap.MacroStep("text", None, "d", 0))}
        slots = dict(p.slots, f2=replace(p.slots["f2"], tap=None, tap_macro="SAVE_AS"))
        self.profile = replace(p, macros=macros, slots=slots)
        self.inj.activate(CONTROL, [0, 1, 2, 3], self.DETENTS, app=True, profile=self.profile)
        self.inj.step()

    def quick_tap(self, b):
        self.kd(b)
        self.ku(b)

    def test_one_pending_macro_per_slot(self):
        for _ in range(5):
            self.quick_tap(1)                    # F2: the running macro, one pending, three dropped
        self.assertEqual(self.inj.app_status()["macrosDropped"], 3)
        self.wait(1.0)
        self.assertEqual(self.backend.text(), "dd", "the running macro and the one pending")

    def test_a_bounded_total(self):
        self.quick_tap(1)                        # running (waits 150 ms)
        now = self.clock()
        chord = [("chord", keymap.parse_chord("ctrl+z"))]
        results = [self.inj._perform_checked(chord, now, tag=("slot", n)) for n in range(E.MACRO_QUEUE_MAX + 2)]
        self.assertEqual(results, [True] * E.MACRO_QUEUE_MAX + [False, False])
        self.assertEqual(self.inj.app_status()["macrosDropped"], 2)
        self.assertEqual(E.MACRO_QUEUE_MAX, 4)
        self.assertEqual(self.inj.status().get("macrosDropped"), None, "the Onshape golden's status is unchanged")


if __name__ == "__main__":
    unittest.main()
