"""The generic app engine (plan sections 3b / 4 / 6, S1 DD-B): Figma and Plasticity scripted against a recording
backend (never SendInput), macros and taps, the command search, parameter mode for number fields and handles (axis /
plane / uniform), keys resolved per layout ("Not on this keyboard"), extended keys, the secure-desktop gate, release
on a profile switch, the Home chord for every profile, and Onshape's built-in profile equal to the bundled one."""
from dataclasses import replace
from pathlib import Path
import math
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cc5_support import Clock  # noqa: E402
from onshape_input_golden import RecordingBackend  # noqa: E402

from control_center import app_engine as E, keymap, onshape, onshape_app  # noqa: E402
from control_center.app_profiles import MacroStep, load_pair  # noqa: E402
from control_center.keymap import parse_chord  # noqa: E402

PROFILES = Path(__file__).resolve().parents[1] / "profiles"
CONTROL = 5
F1, F2, F3, F4 = 0, 1, 2, 3
DE_SCAN = {"/": 0x0137, ".": 0xBE, "-": 0xBD, ",": 0xBC}      # German QWERTZ: '/' is Shift+7


def bundled(pid):
    return load_pair(PROFILES / "karl" / f"{pid}.json", PROFILES / f"{pid}.windows.json")


class Backend(RecordingBackend):
    """The golden recorder plus the app-profile hooks: a layout (VkKeyScanExW table), the input desktop."""

    def __init__(self, clock, layout=None):
        super().__init__(clock)
        self.layout = layout                 # None = US
        self.desktop = True
        self.profiles = []

    def resolve_chord(self, chord):
        scan = (lambda ch, hkl: self.layout.get(ch, -1)) if self.layout is not None else E.us_vk_key_scan
        return keymap.resolve_chord(chord, 0x0407, vk_key_scan=scan)

    def desktop_ok(self):
        return self.desktop

    def set_profile(self, profile):
        self.profiles.append(profile.id)

    def events(self):
        return [tuple(e) for _, batch in self.batches for e in batch]

    def keys(self):
        """Key events as (vk, up) pairs, the extended flag as a third item when set."""
        return [(e[1], e[2]) + ((True,) if len(e) > 3 and e[3] else ()) for e in self.events() if e[0] == "key"]

    def text(self):
        return "".join(e[1] for e in self.events() if e[0] == "char" and not e[2])


def vk(text):
    return keymap.parse_chord(text).key.vk


def chord_keys(text):
    """The (vk, up) pairs of one chord, modifiers in ctrl / shift / alt order."""
    chord = parse_chord(text)
    mods = [keymap.MOD_VK[m] for m in E.ordered_mods(chord.mods)]
    k = chord.key.vk
    return [(m, False) for m in mods] + [(k, False), (k, True)] + [(m, True) for m in reversed(mods)]


class EngineCase(unittest.TestCase):
    PROFILE = "figma"
    DETENTS = 48

    def setUp(self):
        self.clock = Clock(50.0)
        self.backend = Backend(self.clock)
        self.profile = bundled(self.PROFILE)
        self.inj = E.AppInjector(self.backend, clock=self.clock, start=False, profile=self.profile)
        self.inj.activate(CONTROL, [0, 1, 2, 3], self.DETENTS, app=True)
        self.inj.step()

    def post(self, kind, **values):
        values.setdefault("id", CONTROL)
        self.inj.post(kind, values)
        self.inj.step()

    def kd(self, b):
        self.post("button", button=b, index=b)

    def ku(self, b):
        self.post("release", button=b, index=b)

    def turn(self, delta=1, times=1):
        for _ in range(times):
            self.post("position", delta=delta)

    def wait(self, seconds):
        end = self.clock() + seconds
        while self.clock() < end - 1e-9:
            self.clock.advance(min(0.01, end - self.clock()))
            self.inj.step()

    def tap(self, b):
        self.kd(b)
        self.wait(0.05)
        self.ku(b)

    def state(self):
        return self.inj.app_state()


class FigmaTests(EngineCase):
    def test_the_knob_zooms_with_ctrl_wheel_16_notches_a_turn(self):
        self.turn(1, self.DETENTS)
        wheels = [e for e in self.backend.events() if e[0] == "wheel"]
        self.assertEqual(sum(e[1] for e in wheels), 16 * 120)
        # 48 detents: 40 a detent (fractional notches, as Onshape's zoom), Ctrl held around each.
        self.assertEqual(self.backend.batches[0][1], [["key", 0x11, False], ["wheel", 40], ["key", 0x11, True]])

    def test_hold_1_and_turn_undoes_and_redoes_12_a_turn_and_a_tap_undoes(self):
        self.kd(F1)
        self.turn(1, self.DETENTS)
        self.assertEqual(self.backend.keys(), chord_keys("ctrl+shift+z") * 12)
        self.turn(-1, 4)
        self.ku(F1)
        self.assertEqual(self.backend.keys()[-4:], chord_keys("ctrl+z"))
        self.backend.batches.clear()
        self.tap(F1)
        self.assertEqual(self.backend.keys(), chord_keys("ctrl+z"), "tap 1 = Undo (Karl's tap)")
        self.assertEqual(self.inj.app_status()["taps"], 1)

    def test_a_held_turn_is_never_also_a_tap(self):
        self.kd(F2)
        self.turn(1, 4)
        self.ku(F2)
        self.assertEqual(self.backend.keys(), chord_keys("enter"))
        self.backend.batches.clear()
        self.tap(F2)
        self.assertEqual(self.backend.keys(), chord_keys("shift+2"))

    def test_the_wheel_has_no_tap_so_it_shows_at_once_and_runs_on_release(self):
        self.kd(F3)
        self.assertEqual(self.state()["wheel"], {"ring": 0, "index": 1})
        self.turn(1, 4 * 2)                      # 48 detents: 4 per entry
        self.assertEqual(self.state()["wheel"]["index"], 3)
        self.ku(F3)
        self.assertEqual(self.backend.keys(), chord_keys("ctrl+alt+g"), "STRUCTURE 3: WRAP IN FRAME")
        self.assertEqual(self.state()["echo"], {"ring": 0, "index": 3, "seq": 1})

    def test_ring_jumps_by_the_rings_slot_button(self):
        self.kd(F3)
        self.kd(F1)
        self.ku(F1)
        self.assertEqual(self.state()["wheel"]["ring"], 1, "F1 steps STRUCTURE -> ALIGN")
        self.kd(F4)
        self.ku(F4)
        self.assertEqual(self.state()["wheel"]["ring"], 3, "F4: UTILITY")
        self.kd(F2)
        self.ku(F2)
        self.assertEqual(self.state()["wheel"]["ring"], 2, "F2: COMPONENTS")
        self.assertEqual(self.backend.events(), [], "ring keys send nothing (no tap, no turn)")

    def test_a_search_command_opens_ctrl_k_types_the_phrase_and_enters(self):
        self.kd(F3)
        self.kd(F2)
        self.ku(F2)                              # COMPONENTS
        self.turn(1, 4 * 2)                      # GO TO MAIN
        self.ku(F3)
        self.wait(0.8)
        self.assertEqual(self.backend.keys(), chord_keys("ctrl+k") + chord_keys("enter"))
        self.assertEqual(self.backend.text(), "go to main component")
        times = [round(t - 50.0, 2) for t, _ in self.backend.batches]
        self.assertLess(abs(times[1] - times[0] - 0.25), 0.015, "the open wait (on the 10 ms walk)")
        self.assertLess(abs(times[2] - times[1] - 0.40), 0.015, "the result wait")

    def test_the_home_chord_does_nothing_on_the_way(self):
        self.kd(F1)
        self.kd(F2)
        self.kd(F4)
        self.turn(1, 8)
        for b in (F1, F2, F4):
            self.ku(b)
        self.assertEqual(self.backend.events(), [])
        self.assertTrue(self.inj.keys.count == 0)

    def test_off_target_refuses_once_and_sends_nothing(self):
        self.backend.target = False
        self.kd(F1)
        self.turn(1, 8)
        self.ku(F1)
        self.assertEqual(self.backend.events(), [])
        self.assertEqual(self.inj.take_events(), [E.REFUSED])

    def test_focus_elsewhere_refuses_keys(self):
        self.backend.focus = False
        self.tap(F1)
        self.assertEqual(self.backend.events(), [])
        self.assertEqual(self.inj.take_events(), [E.FOCUS_REFUSED])


class PlasticityTests(EngineCase):
    PROFILE = "plasticity"
    DETENTS = 48

    def test_the_knob_alone_zooms_with_ctrl_middle_drag_up(self):
        self.turn(1, 2)
        events = self.backend.events()
        self.assertEqual(events[:3], [("key", 0x11, False), ("down", "middle"), ("move", 500, 405)])
        px = round(round(120 * 2 * math.pi) / self.DETENTS)
        self.assertEqual(events[-1], ("move", 500, 400 - 2 * px), "sign -1: a clockwise turn drags up (zoom in)")
        self.wait(0.9)                           # the idle deadline lets go
        self.assertEqual(self.backend.events()[-3:], [("up", "middle"), ("key", 0x11, True), ("move", 500, 400)])

    def test_hold_2_orbits_with_middle_drag_hold_4_pans_with_right_drag(self):
        self.kd(F2)
        self.turn(1)
        self.assertIn(("down", "middle"), self.backend.events())
        self.kd(F4)
        self.turn(1)
        self.ku(F4)
        self.ku(F2)
        events = self.backend.events()
        self.assertIn(("down", "right"), events)
        self.assertEqual(events.count(("down", "middle")), events.count(("up", "middle")))
        self.assertEqual(events.count(("down", "right")), events.count(("up", "right")))

    def test_tap_3_is_undo_and_the_wheel_waits_250_ms(self):
        self.tap(F3)
        self.assertEqual(self.backend.keys(), chord_keys("ctrl+z"))
        self.assertEqual(self.inj.take_events(), [E.UNDO])
        self.kd(F3)
        self.assertNotIn("wheel", self.state())
        self.wait(0.3)
        self.assertEqual(self.state()["wheel"], {"ring": 0, "index": 1})

    def run_command(self, ring_button_presses, entries):
        self.kd(F3)
        self.wait(0.3)
        for b in ring_button_presses:
            self.kd(b)
            self.ku(b)
        self.turn(1, 4 * (entries - 1))
        self.ku(F3)

    def test_move_starts_handle_parameter_mode_with_the_x_constraint(self):
        self.run_command([F1], 1)                # EDIT / MOVE: G, then X (axis_default 0)
        self.assertEqual(self.backend.keys(), chord_keys("g") + chord_keys("x"))
        param = self.state()["param"]
        self.assertEqual((param["ring"], param["index"], param["axis"], param["plane"]), (1, 1, 0, False))
        # Free clicks: 48 a turn, 0.1 each, the pointer moves 16 px a click (the handle follows it).
        self.backend.batches.clear()
        self.turn(1, 3)
        self.assertEqual([e for e in self.backend.events()], [("move", 516, 400), ("move", 532, 400),
                                                                ("move", 548, 400)])
        self.assertEqual(self.state()["param"]["value"], 300)

    def test_axis_taps_cycle_x_y_z_plane_and_send_the_constraint(self):
        self.run_command([F1], 1)                # MOVE: axes + planes
        self.backend.batches.clear()
        self.tap(F1)                             # X again: its plane (Shift+X)
        self.assertEqual(self.backend.keys(), chord_keys("shift+x"))
        self.assertEqual((self.state()["param"]["axis"], self.state()["param"]["plane"]), (0, True))
        self.backend.batches.clear()
        self.tap(F2)                             # Y
        self.assertEqual(self.backend.keys(), chord_keys("y"))
        self.tap(F4)                             # Z
        self.assertEqual(self.state()["param"]["axis"], 2)

    def test_scale_reaches_uniform(self):
        self.run_command([F1], 3)                # EDIT / SCALE: axis_default 3 = uniform: S
        self.assertEqual(self.backend.keys(), chord_keys("s") + chord_keys("s"))
        self.assertEqual(self.state()["param"]["axis"], 3)
        self.tap(F1)                             # X
        self.tap(F1)                             # X plane
        self.backend.batches.clear()
        self.tap(F1)                             # uniform
        self.assertEqual(self.backend.keys(), chord_keys("s"))
        self.assertEqual(self.state()["param"]["axis"], 3)

    def test_held_steps_are_exact_and_typed_in_on_confirm(self):
        self.run_command([], 1)                  # SOLID / EXTRUDE: E, then its enter key D
        self.assertEqual(self.backend.keys(), chord_keys("e") + chord_keys("d"))
        self.backend.batches.clear()
        self.kd(F4)                              # the 1.0 step, 16 a turn
        self.turn(1, 6)                          # 48 detents: 3 per step -> 2 steps
        self.ku(F4)
        self.assertEqual(self.backend.events(), [], "steps move nothing; the value is typed on confirm")
        self.assertEqual(self.state()["param"]["value"], 2000)
        self.tap(F3)                             # OK
        self.wait(0.2)
        self.assertEqual(self.backend.keys(), chord_keys("tab") + chord_keys("enter"))
        self.assertEqual(self.backend.text(), "2.00")
        self.assertNotIn("param", self.state())
        self.assertEqual(self.state()["echo"]["index"], 1)

    def test_hold_3_cancels_with_escape(self):
        self.run_command([], 1)
        self.backend.batches.clear()
        self.kd(F3)
        self.wait(0.7)
        self.ku(F3)
        self.assertEqual(self.backend.keys(), chord_keys("esc"))
        self.assertNotIn("echo", self.state())

    def test_a_key_the_layout_cant_type_refuses_and_sends_nothing(self):
        self.backend.layout = DE_SCAN
        self.run_command([F4], 5)                # VIEW / FOCUS '/': Shift+7 on German QWERTZ
        self.assertEqual(self.backend.events(), [])
        self.assertEqual(self.inj.take_events(), [E.KEYBOARD_REFUSED])
        self.assertNotIn("echo", self.state())
        self.assertEqual(self.inj.app_status()["keyboardRefused"], 1)
        self.backend.batches.clear()
        self.wait(1.0)
        self.run_command([F4], 6)                # ISOLATE '.': fine on that layout
        self.assertEqual(self.backend.keys(), [(0xBE, False), (0xBE, True)])

    def test_the_secure_desktop_sends_nothing_and_releases_everything(self):
        self.kd(F2)
        self.turn(1, 2)
        self.backend.desktop = False             # UAC / the lock screen
        before = len(self.backend.batches)
        self.turn(1)
        self.assertEqual(self.backend.batches[before:][0][1][0], ["up", "middle"], "only the release goes out")
        self.assertEqual(len(self.backend.batches), before + 1)
        self.assertEqual(self.inj.status()["releases"].get("secure_desktop"), 1)
        self.ku(F2)
        self.tap(F3)
        self.assertEqual(len(self.backend.batches), before + 1, "no Undo on the secure desktop")
        self.backend.desktop = True
        self.wait(1.0)
        self.tap(F3)
        self.assertEqual(self.backend.keys()[-4:], chord_keys("ctrl+z"))

    def test_a_profile_switch_releases_every_held_input(self):
        self.kd(F4)
        self.turn(1, 2)
        self.assertTrue(self.inj.status()["dragging"])
        self.inj.activate(CONTROL, [0, 1, 2, 3], self.DETENTS, app=True, profile=bundled("figma"))
        self.inj.step()
        self.assertFalse(self.inj.status()["dragging"])
        self.assertEqual(self.backend.events()[-2:], [("up", "right"), ("move", 500, 400)])
        self.assertEqual(self.inj.status()["releases"].get("profile"), 1)
        self.assertEqual(self.backend.profiles, ["plasticity", "figma"])
        self.assertEqual(self.inj.app_status()["profile"], "figma")


class MacroAndKeyTests(EngineCase):
    PROFILE = "figma"

    def setUp(self):
        super().setUp()
        p = self.profile
        macros = {"SAVE_AS": (MacroStep("key", parse_chord("ctrl+shift+s"), None, 0), MacroStep("wait", None, None, 150),
                              MacroStep("text", None, "draft 2", 0), MacroStep("key", parse_chord("enter"), None, 0))}
        ring = p.rings[0]
        cmds = (replace(ring.commands[0], kind="macro", chord=None, macro="SAVE_AS"),
                replace(ring.commands[1], chord=parse_chord("ctrl+delete")),
                replace(ring.commands[2], disabled=True, disabled_reason="Not on Windows"), *ring.commands[3:])
        slots = dict(p.slots, f2=replace(p.slots["f2"], tap=None, tap_macro="SAVE_AS"),
                     f4=replace(p.slots["f4"], kind="tap", cw=parse_chord("left"), macro=None))
        self.profile = replace(p, macros=macros, rings=(replace(ring, commands=cmds),) + p.rings[1:], slots=slots)
        self.inj.activate(CONTROL, [0, 1, 2, 3], self.DETENTS, app=True, profile=self.profile)
        self.inj.step()

    def test_a_macro_command_runs_its_keys_text_and_waits(self):
        self.kd(F3)
        self.ku(F3)                              # STRUCTURE 1: the macro
        self.assertEqual(self.backend.keys(), chord_keys("ctrl+shift+s"))
        self.wait(0.2)
        self.assertEqual(self.backend.text(), "draft 2")
        self.assertEqual(self.backend.keys()[-2:], [(0x0D, False), (0x0D, True)])
        gap = self.backend.batches[1][0] - self.backend.batches[0][0]
        self.assertLess(abs(gap - 0.15), 0.015, "the macro's wait (on the 10 ms walk)")

    def test_a_tap_macro(self):
        self.tap(F2)
        self.wait(0.3)
        self.assertEqual(self.backend.text(), "draft 2")

    def test_extended_keys_carry_the_extended_flag(self):
        self.kd(F3)
        self.turn(1, 4)
        self.ku(F3)                              # STRUCTURE 2: Ctrl+Delete
        self.assertEqual(self.backend.keys(), [(0x11, False), (0x2E, False, True), (0x2E, True, True), (0x11, True)])
        self.backend.batches.clear()
        self.kd(F4)                              # a tap kind slot fires on the press: Left (extended)
        self.assertEqual(self.backend.keys(), [(0x25, False, True), (0x25, True, True)])

    def test_a_disabled_command_refuses(self):
        self.kd(F3)
        self.turn(1, 8)
        self.ku(F3)
        self.assertEqual(self.backend.events(), [])
        self.assertEqual(self.inj.take_events(), [E.DISABLED_REFUSED])
        self.assertNotIn("echo", self.state())


class BuiltinOnshapeTests(unittest.TestCase):
    """The built-in Onshape profile (no files needed) equals the bundled one on everything the engine reads."""

    def test_builtin_equals_bundled(self):
        built, files = onshape_app.builtin_onshape_profile(), bundled("onshape")
        for name in ("knob", "f1", "f2", "f3", "f4"):
            a, b = built.slots[name], files.slots[name]
            with self.subTest(name):
                self.assertEqual((a.kind, a.button, a.drag_buttons, a.drag_mods, a.axis_y, a.sign, a.wheel_mods,
                                  a.tap, a.tap_macro, a.cw, a.ccw, a.macro),
                                 (b.kind, b.button, b.drag_buttons, b.drag_mods, b.axis_y, b.sign, b.wheel_mods,
                                  b.tap, b.tap_macro, b.cw, b.ccw, b.macro))
                self.assertEqual(E.px_per_turn(a), E.px_per_turn(b))
                self.assertEqual(a.notches_per_turn, b.notches_per_turn)
        self.assertEqual(len(built.rings), len(files.rings))
        for ra, rb in zip(built.rings, files.rings):
            self.assertEqual((ra.name, ra.slot), (rb.name, rb.slot))
            for ca, cb in zip(ra.commands, rb.commands):
                self.assertEqual((ca.name, ca.kind, ca.chord, ca.phrase, ca.disabled), (cb.name, cb.kind, cb.chord,
                                                                                       cb.phrase, cb.disabled))
                if ca.param is not None:
                    pa, pb = ca.param, cb.param
                    self.assertEqual((pa.start, pa.min, pa.max, pa.decimals, pa.steps, pa.unit, pa.axes, pa.enter),
                                     (pb.start, pb.min, pb.max, pb.decimals, pb.steps, pb.unit, pb.axes, pb.enter))
        self.assertEqual((built.search, built.search_open_ms, built.search_result_ms),
                         (files.search, files.search_open_ms, files.search_result_ms))
        ka, kb = built.param_keys, files.param_keys
        self.assertEqual((ka.confirm, ka.cancel, ka.field, ka.step_mods, ka.scroll_sign, ka.select_all, ka.numeric),
                         (kb.confirm, kb.cancel, kb.field, kb.step_mods, kb.scroll_sign, kb.select_all, kb.numeric))
        self.assertEqual(built.legend, files.legend)
        self.assertEqual(built.detect.host, files.detect.host)
        self.assertEqual(set(built.detect.exclude_host), set(files.detect.exclude_host))

    def test_the_facade_is_the_engine(self):
        self.assertTrue(issubclass(onshape.OnshapeInjector, E.AppInjector))
        self.assertTrue(issubclass(onshape.KeyTracker, E.SlotTracker))
        self.assertTrue(issubclass(onshape_app.OnshapeApp, E.ProfileApp))
        self.assertIs(onshape.NullBackend, E.NullBackend)
        self.assertIs(onshape.ShortSend, E.ShortSend)


class Win32InputTests(unittest.TestCase):
    """Win32Backend builds INPUT records only (never SendInput): the extended flag and one layout read a batch."""

    def setUp(self):
        try:
            import windows_actions as wa
        except Exception:  # pragma: no cover
            self.skipTest("windows_actions unavailable")
        self.wa = wa

    def backend(self):
        from onshape_input_golden import FakeUser

        class User(FakeUser):
            reads = 0

            def GetKeyboardLayout(self, thread):
                User.reads += 1
                return 0x04090409

        b = onshape.Win32Backend.__new__(onshape.Win32Backend)
        b._INPUT, b._INPUT_KEYBOARD, b._INPUT_MOUSE = self.wa.INPUT, self.wa.INPUT_KEYBOARD, self.wa.INPUT_MOUSE
        b._KEYUP, b._WHEEL = self.wa.KEYEVENTF_KEYUP, self.wa.MOUSEEVENTF_WHEEL
        b.u = User()
        b._send_input = lambda n, buffer, size: n
        return b, User

    def test_extended_keys_get_the_flag_and_others_dont(self):
        b, _ = self.backend()
        self.assertEqual(b._input(("key", 0x25, False)).ki.dwFlags, E.KEYEVENTF_EXTENDEDKEY)       # VK_LEFT
        self.assertEqual(b._input(("key", 0x2E, True)).ki.dwFlags, E.KEYEVENTF_EXTENDEDKEY | 0x0002)  # Delete up
        self.assertEqual(b._input(("key", 0x0D, False, True)).ki.dwFlags, E.KEYEVENTF_EXTENDEDKEY)   # numpad Enter
        self.assertEqual(b._input(("key", 0x0D, False)).ki.dwFlags, 0)
        self.assertEqual(b._input(("key", 0x5A, False)).ki.dwFlags, 0)
        self.assertEqual(b._input(("char", "e", False)).ki.dwFlags, E.KEYEVENTF_UNICODE)

    def test_resolve_and_send_read_the_layout_once(self):
        b, User = self.backend()
        hit = b.resolve_chord(parse_chord("ctrl+left"))
        self.assertEqual(hit, (0x25, frozenset({"ctrl"})))
        b.send(E.chord_events(("ctrl",), (0x25, True)))
        self.assertEqual(User.reads, 1, "DD-SEC-004's per-batch read serves the resolution too")
        b.send([("key", 0x5A, False), ("key", 0x5A, True)])
        self.assertEqual(User.reads, 2)


if __name__ == "__main__":
    unittest.main()
