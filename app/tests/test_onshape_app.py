"""A2 (ONSHAPE.md sections 10-13): the command wheel, parameter mode and echo state machine, its Windows shortcut
table, the injector wiring (fake backend, never SendInput), the frame's `app` object and its capability gate
(older firmware keeps A0's text frames). Headless."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cc5_support import Clock  # noqa: E402
from r3_support import CAPS_V5, CAPS_V6, R3Fixture  # noqa: E402
from test_onshape import FakeBackend  # noqa: E402

from control_center import device, onshape_app  # noqa: E402
from control_center.onshape import (OnshapeInjector, chord_events, chord_vk, scroll_events,  # noqa: E402
                                    text_events)
from control_center.onshape_app import (ALT, CTRL, RINGS, SHIFT, OnshapeApp, command,  # noqa: E402
                                        format_value)

HOME, ORBIT, WHEEL, PAN = 0, 1, 2, 3
CAPS_APP = dict(CAPS_V6, appCanvas=1)
SETTLE = ("settle",)                                    # a transaction's end marker (the injector calls settle())
RECHECK = ("recheck",)                                  # S3 decision: a fresh keyboard-focus check before typed digits
# The firmware tree: ex/firmware (the shared tree), or, from a git worktree of this repo, the worktree path
# ../firmware/src (app profiles, S1 DD-B).
FIRMWARE_TABLE = next((path for path in (
    Path(__file__).resolve().parents[2] / "firmware" / "src" / "cc_app_onshape.c",
    Path(__file__).resolve().parents[2] / "firmware" / "src" / "cc_app_onshape.c")
    if path.is_file()), Path(__file__).resolve().parents[2] / "firmware" / "src" / "cc_app_onshape.c")
PROFILES = Path(__file__).resolve().parents[1] / "profiles"


class AppCase(unittest.TestCase):
    def setUp(self):
        self.clock = Clock(10.0)
        self.app = OnshapeApp(120, clock=self.clock)    # 10 detents per wheel entry, 7.5 per step, 2.5 per fine step

    def at(self, seconds):
        self.clock.advance(seconds)
        return self.app.tick()

    def open_wheel(self):
        self.app.down(WHEEL)
        self.at(0.26)
        self.assertTrue(self.app.snapshot().get("wheel"))


class WheelTests(AppCase):
    def test_a_quick_tap_of_3_is_undo_and_never_shows_the_wheel(self):
        self.app.down(WHEEL)
        self.at(0.1)
        self.assertNotIn("wheel", self.app.snapshot())
        self.clock.advance(0.05)
        self.assertEqual(self.app.up(WHEEL), [("undo",)])
        self.assertNotIn("wheel", self.app.snapshot())

    def test_the_wheel_shows_after_250_ms_and_release_runs_the_entry(self):
        self.app.down(WHEEL)
        self.at(0.24)
        self.assertNotIn("wheel", self.app.snapshot())
        self.at(0.02)
        self.assertEqual(self.app.snapshot()["wheel"], {"ring": 0, "index": 1})
        self.assertEqual(self.app.up(WHEEL), [("chord", (SHIFT,), "S"), SETTLE])     # SKETCH
        self.assertNotIn("echo", self.app.snapshot(), "the echo waits until the chord went out")
        self.app.settle()
        snap = self.app.snapshot()
        self.assertNotIn("wheel", snap)
        self.assertEqual(snap["echo"], {"ring": 0, "index": 1, "seq": 1})

    def test_the_first_detent_reveals_without_moving(self):
        self.app.down(WHEEL)
        consumed, actions = self.app.turn(3)
        self.assertTrue(consumed)
        self.assertEqual(actions, [])
        self.assertEqual(self.app.snapshot()["wheel"], {"ring": 0, "index": 1})
        self.assertEqual(self.app.up(WHEEL), [("chord", (SHIFT,), "S"), SETTLE])   # a turned press is never a tap

    def test_twelve_entries_per_turn_with_walls_at_both_ends(self):
        self.open_wheel()
        self.app.turn(9)
        self.assertEqual(self.app.entry, 1)
        self.app.turn(1)
        self.assertEqual(self.app.entry, 2)
        self.app.turn(200)
        self.assertEqual(self.app.entry, 6)                  # MODEL has 6 commands: the wall
        self.app.turn(-10)
        self.assertEqual(self.app.entry, 5)                  # reversing at the wall moves at once
        self.app.turn(-500)
        self.assertEqual(self.app.entry, 0)                  # cancel, the other wall
        self.assertEqual(self.app.up(WHEEL), [])             # releasing on cancel runs nothing
        self.assertNotIn("echo", self.app.snapshot())

    def test_other_keys_jump_rings_and_are_swallowed(self):
        self.open_wheel()
        self.app.down(HOME)
        self.assertEqual(self.app.snapshot()["wheel"]["ring"], 1)   # MODEL -> MODIFY
        self.assertTrue(self.app.swallowed(HOME))
        self.app.up(HOME)
        self.app.down(HOME)
        self.assertEqual(self.app.ring, 0)                          # MODIFY -> MODEL
        self.app.down(ORBIT)
        self.assertEqual(RINGS[self.app.ring].name, "SKETCH")
        self.app.down(PAN)
        self.assertEqual(RINGS[self.app.ring].name, "VIEW")
        self.app.turn(10)
        self.assertEqual(self.app.up(WHEEL), [("chord", (SHIFT,), "4"), SETTLE])   # VIEW 2 = RIGHT
        for slot in (HOME, ORBIT, PAN):
            self.assertTrue(self.app.swallowed(slot))
            self.assertEqual(self.app.up(slot), [])
            self.assertFalse(self.app.swallowed(slot))

    def test_the_wheel_reopens_on_the_last_entry_run_in_that_ring(self):
        self.open_wheel()
        self.app.turn(20)                               # entry 3 = REVOLVE
        self.assertEqual(self.app.up(WHEEL), [("chord", (SHIFT,), "W"), SETTLE])
        self.open_wheel()
        self.assertEqual(self.app.snapshot()["wheel"], {"ring": 0, "index": 3})

    def test_3_while_orbiting_does_nothing(self):
        self.app.down(ORBIT)
        self.app.down(WHEEL)
        self.at(1.0)
        self.assertNotIn("wheel", self.app.snapshot())
        self.assertEqual(self.app.up(WHEEL), [])
        self.assertEqual(self.app.turn(5), (False, []))

    def test_3_while_tilting_does_nothing(self):
        self.app.down(HOME)                             # 7.2.2.0: 1 held is the tilt drag's modifier
        self.app.down(WHEEL)
        self.at(1.0)
        self.assertNotIn("wheel", self.app.snapshot())
        self.assertEqual(self.app.up(WHEEL), [])
        self.assertEqual(self.app.turn(5), (False, []))

    def test_a_search_command_is_alt_c_the_phrase_and_enter(self):
        self.open_wheel()
        self.app.down(HOME)                             # MODIFY
        self.app.up(HOME)
        self.assertEqual(self.app.up(WHEEL), [("chord", (ALT,), "C"), ("wait", 0.25), ("text", "boolean"),
                                              ("wait", 0.40), ("chord", (), "ENTER"), SETTLE])

    def test_chord_closes_an_open_wheel_without_running_it(self):
        self.open_wheel()
        self.app.turn(20)
        self.assertEqual(self.app.chord(HOME), [])
        self.assertFalse(self.app.busy)
        self.assertTrue(self.app.swallowed(WHEEL) and self.app.swallowed(HOME))
        self.assertEqual(self.app.up(WHEEL), [])
        self.assertEqual(self.app.up(HOME), [])
        self.assertNotIn("echo", self.app.snapshot())

    def test_a_lost_release_closes_the_wheel_without_running(self):
        self.open_wheel()
        self.app.seed(0)
        self.assertNotIn("wheel", self.app.snapshot())
        self.assertEqual(self.app.up(WHEEL), [])


class ParamTests(AppCase):
    def start(self, ring=0, index=2):
        self.open_wheel()
        self.app.ring = ring
        self.app.entry = index
        actions = self.app.up(WHEEL)
        self.assertIsNotNone(self.app.param)
        return actions

    def test_extrude_starts_parameter_mode_a(self):
        self.assertEqual(self.start(), [("chord", (SHIFT,), "E"), SETTLE])
        snap = self.app.snapshot()
        self.assertEqual(snap["param"], {"ring": 0, "index": 2, "mode": "A", "value": 0, "step": 1})
        self.assertNotIn("echo", snap)                  # the echo comes on confirm
        self.assertTrue(self.app.busy)

    def test_a_scrolls_one_notch_per_step_with_the_step_modifier(self):
        self.start()
        self.assertEqual(self.app.turn(7), (True, []))            # 7.5 detents per step
        self.assertEqual(self.app.turn(1), (True, [("scroll", 1, ())]))
        self.assertEqual(self.app.snapshot()["param"]["value"], 100)   # +0.1
        self.app.down(PAN)                                         # 4 held: 1.0 with Shift
        self.assertEqual(self.app.turn(-8), (True, [("scroll", -1, (SHIFT,))]))
        self.app.up(PAN)
        self.app.down(HOME)                                        # 1 held: 0.01 with Ctrl, 48 per turn
        self.assertEqual(self.app.turn(3), (True, [("scroll", 1, (CTRL,))]))
        snap = self.app.snapshot()["param"]
        self.assertEqual((snap["value"], snap["step"]), (-890, 0))

    def test_tap_2_switches_to_b_which_holds_clamps_and_retypes_the_value(self):
        self.start()
        self.app.down(ORBIT)
        self.clock.advance(0.1)
        self.app.up(ORBIT)
        self.assertTrue(self.app.typed)
        self.app.param = (0, 2, command(0, 2).param)
        self.app.value = 25.0
        self.app.down(PAN)
        self.assertEqual(self.app.turn(16), (True, []))            # B sends nothing while turning
        self.assertEqual(self.app.snapshot()["param"]["value"], 27000)
        self.app.up(PAN)
        self.assertEqual(self.at(0.2), [])
        self.assertEqual(self.at(0.2), [("chord", (CTRL,), "A"), ("wait", 0.02), RECHECK, ("text", "27.00 mm"),
                                           SETTLE])
        self.app.down(PAN)
        self.app.turn(-8 * 40)                                     # below DEPTH's minimum 0: clamped, bumped
        snap = self.app.snapshot()["param"]
        self.assertEqual((snap["value"], snap["mode"]), (0, "B"))
        self.assertGreaterEqual(snap["bump"], 1)

    def test_tap_3_confirms_with_enter_and_echoes(self):
        self.start()
        self.app.turn(8)
        self.app.down(WHEEL)
        self.clock.advance(0.2)
        self.assertEqual(self.app.up(WHEEL), [("chord", (), "ENTER"), SETTLE])
        self.app.settle()                               # (the injector, once the start chord went out)
        self.assertNotIn("echo", self.app.snapshot())
        self.app.settle()                               # Enter went out: confirmed
        snap = self.app.snapshot()
        self.assertNotIn("param", snap)
        self.assertEqual(snap["echo"], {"ring": 0, "index": 2, "seq": 1})

    def test_b_confirm_types_a_pending_value_first(self):
        self.app.typed = True
        self.start(0, 4)                                # FILLET, B starts at 1.00
        self.assertEqual(self.app.snapshot()["param"]["value"], 1000)
        self.app.turn(8)
        self.app.down(WHEEL)
        self.assertEqual(self.app.up(WHEEL), [("chord", (CTRL,), "A"), ("wait", 0.02), RECHECK, ("text", "1.10 mm"),
                                              SETTLE, ("chord", (), "ENTER"), SETTLE])

    def test_3_held_600_ms_cancels_with_escape(self):
        self.start()
        self.app.down(WHEEL)
        self.clock.advance(0.61)
        self.assertEqual(self.app.up(WHEEL), [("chord", (), "ESCAPE"), SETTLE])
        self.assertNotIn("echo", self.app.snapshot())
        self.assertFalse(self.app.busy)

    def test_1_is_a_step_in_parameter_mode_never_home(self):
        self.start()
        self.app.down(HOME)
        self.assertTrue(self.app.swallowed(HOME))

    def test_format_value(self):
        self.assertEqual(format_value(-0.001, 2), "0.00")
        self.assertEqual(format_value(-4.2, 2), "-4.20")
        self.assertEqual(format_value(25, 2), "25.00")


class ShortcutTableTests(unittest.TestCase):
    """Karl's macOS chords translated for Windows (Onshape help "Keyboard shortcuts": Ctrl for Cmd, Alt for
    Option; tool search Alt+C; numeric fields Ctrl 0.01 / none 0.1 / Shift 1.0)."""
    EXPECTED = {
        "SKETCH": ((SHIFT,), "S"), "EXTRUDE": ((SHIFT,), "E"), "REVOLVE": ((SHIFT,), "W"), "FILLET": ((SHIFT,), "F"),
        "LINE": ((), "L"), "RECTANGLE": ((), "G"), "CIRCLE": ((), "C"), "ARC": ((), "A"), "DIMENSION": ((), "D"),
        "TRIM": ((), "M"), "CONSTRUCTION": ((), "Q"), "FRONT": ((SHIFT,), "1"), "RIGHT": ((SHIFT,), "4"),
        "TOP": ((SHIFT,), "5"), "ISOMETRIC": ((SHIFT,), "7"), "NORMAL TO": ((), "N"), "ZOOM TO FIT": ((), "F"),
        "SECTION": ((SHIFT,), "X"),
    }
    SEARCH = {"CHAMFER": "chamfer", "SHELL": "shell", "BOOLEAN": "boolean", "SPLIT": "split",
              "TRANSFORM": "transform", "PATTERN": "linear pattern", "MIRROR": "mirror", "MOVE FACE": "move face"}

    def test_every_command(self):
        seen = set()
        for ring in RINGS:
            for cmd in ring.commands:
                seen.add(cmd.name)
                if cmd.search:
                    self.assertEqual(cmd.phrase, self.SEARCH[cmd.name])
                    self.assertEqual(cmd.actions()[0], ("chord", (ALT,), "C"))
                else:
                    self.assertEqual((cmd.mods, cmd.key), self.EXPECTED[cmd.name])
                self.assertNotIn("cmd", cmd.mods)         # no macOS modifier survives
        self.assertEqual(seen, set(self.EXPECTED) | set(self.SEARCH))
        self.assertEqual([r.name for r in RINGS], ["MODEL", "MODIFY", "SKETCH", "VIEW"])
        self.assertEqual([r.slot for r in RINGS], [HOME, HOME, ORBIT, PAN])

    def test_the_other_chords(self):
        self.assertEqual(onshape_app.UNDO_CHORD, ((CTRL,), "Z"))
        self.assertEqual(onshape_app.SELECT_ALL, ((CTRL,), "A"))
        self.assertEqual(onshape_app.STEP_MODIFIERS, ((CTRL,), (), (SHIFT,)))
        self.assertEqual([c.name for c in RINGS[0].commands if c.param], ["EXTRUDE", "FILLET", "CHAMFER", "SHELL"])
        self.assertEqual([c.name for c in RINGS[1].commands if c.param], ["TRANSFORM", "MOVE FACE"])

    def test_virtual_keys(self):
        self.assertEqual(chord_events((SHIFT,), "E"), [("key", 0x10, False), ("key", 0x45, False), ("key", 0x45, True),
                                                       ("key", 0x10, True)])
        self.assertEqual(chord_events((ALT,), "C")[0], ("key", 0x12, False))
        self.assertEqual(chord_vk("7"), 0x37)
        self.assertEqual(chord_vk("ENTER"), 0x0D)
        self.assertEqual(chord_vk("ESCAPE"), 0x1B)
        self.assertEqual(text_events("a1"), [("char", "a", False), ("char", "a", True), ("char", "1", False),
                                             ("char", "1", True)])
        self.assertEqual(scroll_events(-2, (CTRL,)), [("key", 0x11, False), ("wheel", -240), ("key", 0x11, True)])

    @unittest.skipUnless(FIRMWARE_TABLE.is_file(), "firmware tree not present")
    def test_the_knob_shows_the_same_table(self):
        table = FIRMWARE_TABLE.read_text(encoding="utf-8")
        for ring in RINGS:
            self.assertIn(f'{{"{ring.name}", "{ring.name}", {len(ring.commands)}, ', table)
            for cmd in ring.commands:
                needle = f'{{"{cmd.name}", {"true" if cmd.search else "false"}, {cmd.display_chord()}'
                self.assertIn(needle, table)
        self.assertIn('APP_MOD_ALT, "C",', table)

    @unittest.skipUnless(FIRMWARE_TABLE.is_file(), "firmware tree not present")
    def test_the_effective_onshape_profile_is_the_built_in_canvas(self):
        """App profiles (plan 1f): Onshape always draws the knob's built-in canvas (id "onshape", crc 0), never its
        uploaded form, so the profile the engine runs (Karl's onshape.json + the sidecar, Windows chords) must be the
        table the canvas draws: rings, their buttons, commands, search flags and the chords' keycaps."""
        from control_center.app_profiles import load_pair
        table = FIRMWARE_TABLE.read_text(encoding="utf-8")
        profile = load_pair(PROFILES / "karl" / "onshape.json", PROFILES / "onshape.windows.json")
        spelled = {"shift": "SHIFT", "ctrl": "APP_MOD_CTRL", "alt": "APP_MOD_ALT"}
        for ring in profile.rings:
            self.assertIn(f'{{"{ring.name}", "{ring.name}", {len(ring.commands)}, ', table)
            for cmd in ring.commands:
                if cmd.kind == "actions":
                    chord = "0, NULL"
                else:
                    mods = [spelled[m] for m in ("ctrl", "shift", "alt") if m in cmd.chord.mods]
                    chord = f'{" | ".join(mods) if mods else "0"}, "{cmd.chord.key.label}"'
                needle = f'{{"{cmd.name}", {"true" if cmd.kind == "actions" else "false"}, {chord}'
                self.assertIn(needle, table, f"{ring.name}/{cmd.name}")
        search = profile.search
        self.assertEqual((sorted(search.mods), search.key.label), (["alt"], "C"))
        self.assertIn('APP_MOD_ALT, "C",', table)
        self.assertEqual([profile.slots[r.slot].button for r in profile.rings], [r.slot for r in RINGS])


class InjectorAppTests(unittest.TestCase):
    CONTROL = 9

    def make(self, app=True, **kwargs):
        self.clock = Clock(100.0)
        self.backend = FakeBackend(**kwargs)
        self.inj = OnshapeInjector(self.backend, clock=self.clock, start=False)
        self.inj.activate(self.CONTROL, [0, 1, 2, 3], 120, app=app)
        self.inj.step()

    def post(self, kind, **values):
        values.setdefault("id", self.CONTROL)
        self.inj.post(kind, values)
        self.inj.step()

    def kd(self, raw):
        self.post("button", button=raw, index=raw)

    def ku(self, raw):
        self.post("release", button=raw, index=raw)

    def test_without_the_app_canvas_hold_3_is_a0(self):
        self.make(app=False)
        self.assertIsNone(self.inj.app_state())
        self.kd(WHEEL)
        self.post("position", delta=10)                     # A0: the knob zooms while 3 is down, no wheel
        self.assertEqual(self.backend.events()[0][0], "wheel")
        self.ku(WHEEL)                                       # a turned press: no Undo
        self.assertIsNone(self.inj.app_state())
        self.backend.batches.clear()
        self.kd(WHEEL)
        self.ku(WHEEL)
        self.assertEqual(self.backend.events(), chord_events((CTRL,), "Z"))

    def test_tap_3_undoes_and_flashes(self):
        self.make()
        self.kd(WHEEL)
        self.clock.advance(0.1)
        self.ku(WHEEL)
        self.assertEqual(self.backend.events(), chord_events((CTRL,), "Z"))
        self.assertEqual(self.inj.app_state()["flash"], 1)

    def test_the_wheel_turn_is_not_zoom_and_the_release_sends_the_chord(self):
        self.make()
        self.kd(WHEEL)
        self.clock.advance(0.3)
        self.inj.step()
        self.assertEqual(self.inj.app_state()["wheel"], {"ring": 0, "index": 1})
        self.post("position", delta=10)
        self.assertEqual(self.backend.events(), [])          # no wheel notches, no drag
        self.assertEqual(self.inj.app_state()["wheel"]["index"], 2)
        self.ku(WHEEL)
        self.assertEqual(self.backend.events(), chord_events((SHIFT,), "E"))
        self.assertEqual(self.inj.app_state()["param"]["mode"], "A")

    def test_hold_1_tilts_with_the_app_canvas_and_the_frame_slot_follows(self):
        self.make()
        self.kd(HOME)
        self.post("position", delta=2)
        self.assertEqual(self.backend.batches[0], [("down", "right"), ("move", 500, 405), ("move", 500, 400)])
        self.assertEqual(self.backend.batches[1][0][0:2], ("move", 500), "a vertical drag: x stays")
        self.assertEqual(self.inj.status()["action"], "tilt")
        self.ku(HOME)
        self.assertEqual(self.backend.batches[-1], [("up", "right"), ("move", 500, 400)])
        self.assertEqual(self.inj.take_events(), [])

    def test_inside_the_wheel_1_steps_model_modify_and_never_tilts(self):
        self.make()
        self.kd(WHEEL)
        self.clock.advance(0.3)
        self.inj.step()
        self.kd(HOME)                                        # MODEL -> MODIFY
        self.assertEqual(self.inj.app_state()["wheel"]["ring"], 1)
        self.post("position", delta=10)                      # the wheel's turn, not a tilt drag
        self.assertEqual(self.inj.app_state()["wheel"]["index"], 2)
        self.ku(HOME)
        self.assertEqual(self.backend.events(), [])
        self.assertEqual(self.inj.status()["drags"], 0)

    def test_in_parameter_mode_1_is_the_fine_step_never_a_tilt(self):
        self.make()
        self.kd(WHEEL)
        self.post("position", delta=1)                       # reveal
        self.post("position", delta=10)                      # EXTRUDE
        self.ku(WHEEL)
        self.backend.batches.clear()
        self.kd(HOME)
        self.post("position", delta=5)                       # 2.5 detents per fine step: two 0.01 steps
        self.assertEqual(self.inj.app_state()["param"]["step"], 0)
        self.assertEqual(self.backend.events(), scroll_events(2, (CTRL,)))
        self.assertEqual(self.inj.status()["drags"], 0)
        self.ku(HOME)

    def test_a_search_macro_waits_between_its_steps(self):
        self.make()
        self.kd(WHEEL)
        self.kd(HOME)                                        # MODIFY; BOOLEAN
        self.ku(HOME)
        self.ku(WHEEL)
        self.assertEqual(self.backend.events(), chord_events((ALT,), "C"))
        self.clock.advance(0.26)
        self.inj.step()
        self.assertEqual(self.backend.events()[-2:], [("char", "n", False), ("char", "n", True)])
        before = len(self.backend.events())
        self.clock.advance(0.2)
        self.inj.step()
        self.assertEqual(len(self.backend.events()), before)
        self.clock.advance(0.25)
        self.inj.step()
        self.assertEqual(self.backend.events()[-2:], chord_events((), "ENTER"))
        self.assertEqual(self.inj.app_state()["echo"], {"ring": 1, "index": 1, "seq": 1})

    def test_parameter_scroll_holds_the_modifier_around_the_notch(self):
        self.make()
        self.kd(WHEEL)
        self.post("position", delta=1)                       # reveal
        self.post("position", delta=10)                      # EXTRUDE
        self.ku(WHEEL)
        self.backend.batches.clear()
        self.kd(HOME)
        self.post("position", delta=3)
        self.assertEqual(self.backend.events(), scroll_events(1, (CTRL,)))

    def test_off_target_commands_are_refused_and_not_sent(self):
        self.make(target=False)
        self.kd(WHEEL)
        self.clock.advance(0.3)
        self.inj.step()
        self.ku(WHEEL)
        self.assertEqual(self.backend.events(), [])
        self.assertEqual(self.inj.take_events(), ["refused"])

    def test_the_home_chord_closes_the_wheel_unrun_and_swallows_every_key(self):
        self.make()
        self.kd(WHEEL)
        self.clock.advance(0.3)
        self.inj.step()
        self.kd(HOME)                                        # MODEL -> MODIFY (the wheel is open)
        self.kd(ORBIT)                                       # the third key: the chord
        self.assertNotIn("wheel", self.inj.app_state())
        self.kd(PAN)
        self.post("position", delta=10)
        for slot in (WHEEL, HOME, ORBIT, PAN):
            self.ku(slot)
        self.assertEqual(self.backend.events(), [], "no entry run, no Undo, no zoom, no drag")
        self.assertNotIn("echo", self.inj.app_state())
        self.kd(WHEEL)
        self.ku(WHEEL)
        self.assertEqual(self.inj.take_events(), ["undo"], "the chord is over: tap 3 is Undo again")

    def test_the_home_chord_in_parameter_mode_sends_neither_ok_nor_cancel(self):
        self.make()
        self.kd(WHEEL)
        self.post("position", delta=1)                       # reveal
        self.post("position", delta=10)                      # EXTRUDE
        self.ku(WHEEL)
        self.backend.batches.clear()
        for slot in (HOME, ORBIT, WHEEL, PAN):
            self.kd(slot)
        self.post("position", delta=30)
        self.clock.advance(0.7)                              # 3 held past the cancel time
        self.inj.step()
        for slot in (ORBIT, WHEEL, HOME, PAN):               # 2 released quickly would be the A/B tap
            self.ku(slot)
        self.assertEqual(self.backend.events(), [])
        state = self.inj.app_state()
        self.assertEqual(state["param"]["mode"], "A", "no A/B switch, parameter mode still open")
        self.kd(WHEEL)
        self.ku(WHEEL)
        self.assertEqual(self.backend.events(), chord_events((), "ENTER"), "OK works again afterwards")

    def test_deactivation_and_a_lost_knob_close_everything_silently(self):
        self.make()
        self.kd(WHEEL)
        self.clock.advance(0.3)
        self.inj.step()
        self.post("disconnected")
        self.assertIsNone(self.inj.app_state())
        self.assertEqual(self.backend.events(), [])


class FrameGateTests(unittest.TestCase):
    FRAME = {"mode": "ONSHAPE", "target": "Onshape", "value": "", "detail": "", "status": "", "layout": "nowPlaying",
             "buttons": [{"label": "Home", "enabled": True, "icon": "house"}] * 4,
             "ring": {"style": "off", "value": 0, "index": 0, "count": 0},
             "app": {"id": "onshape", "slot": "orbit", "flash": 2, "wheel": {"ring": 1, "index": 3}}}

    def test_kept_only_for_an_app_canvas_knob(self):
        self.assertEqual(device._frame(dict(self.FRAME), CAPS_APP)["app"], self.FRAME["app"])
        self.assertNotIn("app", device._frame(dict(self.FRAME), CAPS_V6))            # cc5.5 / cc5.4 D: A0 text
        self.assertNotIn("app", device._frame(dict(self.FRAME), CAPS_V5))            # cc5.3 and older
        self.assertNotIn("app", device._frame(dict(self.FRAME), dict(CAPS_V5, appCanvas=1)))   # presentation 6 only
        self.assertNotIn("app", device._frame(dict(self.FRAME), dict(CAPS_V6, appCanvas=2)))

    def test_the_tilt_slot(self):
        tilt = dict(self.FRAME, app={"id": "onshape", "slot": "tilt"})
        self.assertEqual(device._frame(dict(tilt), CAPS_APP)["app"], {"id": "onshape", "slot": "tilt"})
        stored, ok = device.app_parse({"id": "onshape", "slot": "tilt"})
        self.assertTrue(ok)
        self.assertEqual(stored["slot"], 3, "appended after pan (CCAppSlot CC_APP_SLOT_TILT)")
        self.assertEqual(device.APP_SLOTS, {"zoom": 0, "orbit": 1, "pan": 2, "tilt": 3,   # app profiles append
                                            "knob": 4, "f1": 5, "f2": 6, "f3": 7, "f4": 8})
        self.assertNotIn("app", device._frame(dict(tilt), CAPS_V6), "an older knob never sees it")
        self.assertEqual(device.app_parse({"id": "onshape", "slot": "TILT"}), (None, False))

    def test_an_invalid_object_is_stripped_not_sent(self):
        bad = dict(self.FRAME, app={"id": "onshape", "slot": "idle"})
        self.assertNotIn("app", device._frame(bad, CAPS_APP))

    def test_app_capability(self):
        self.assertTrue(device.app_capability(CAPS_APP))
        self.assertFalse(device.app_capability({"presentation": 6, "appCanvas": True}))
        self.assertFalse(device.app_capability(None))


class ControllerAppTests(R3Fixture):
    def enter(self):
        self.assertTrue(self.c.enter_onshape("test"))
        self.c.drain()

    def test_no_app_object_without_the_injector_state(self):
        self.enter()
        self.assertNotIn("app", self.frame())

    def test_the_frame_carries_the_app_object(self):
        self.enter()
        self.c.onshape_app = {"flash": 3, "wheel": {"ring": 2, "index": 4}}
        frame = self.frame()
        self.assertEqual(frame["app"], {"id": "onshape", "slot": "zoom", "flash": 3, "wheel": {"ring": 2, "index": 4}})
        self.c.onshape_input("down", ORBIT)
        self.assertEqual(self.frame()["app"]["slot"], "orbit")
        self.c.onshape_input("down", HOME)
        self.assertEqual(self.frame()["app"]["slot"], "tilt", "the newest modifier: hold 1 = tilt")
        self.assertTrue(device.app_parse(self.frame()["app"])[1])
        self.c.onshape_input("up", HOME)
        self.assertEqual(self.frame()["app"]["slot"], "orbit")
        self.c.onshape_input("refused")
        self.assertTrue(self.frame()["app"]["refused"])
        # The object is valid for the knob's parser.
        self.assertTrue(device.app_parse(self.frame()["app"])[1])
        self.assertIn("app", device._frame(self.frame(), CAPS_APP))

    def test_hold_1_never_goes_home_anywhere(self):
        # F1 is TILT (7.2.2.0): its kh (600 ms) does nothing in Onshape mode (in the wheel, parameter mode or outside).
        self.enter()
        for app in ({"flash": 0, "wheel": {"ring": 0, "index": 1}},
                    {"flash": 0, "param": {"ring": 0, "index": 2, "mode": "A", "value": 0, "step": 1}}, {"flash": 0}):
            with self.subTest(app=app):
                self.c.onshape_app = app
                self.c.onshape_input("down", HOME)
                self.c.onshape_input("hold", HOME)
                self.c.hold(HOME, self.c.control_id)
                self.c.onshape_input("up", HOME)
                self.assertEqual(self.c.screen.mode, "onshape")
        self.assertEqual(self.c.onshape_user_exits, 0)


class RuntimeAppTests(unittest.TestCase):
    """The runtime activates the injector with the wheel only for an appCanvas knob and puts the injector's state
    into the Onshape frames."""

    def harness(self, capabilities, injector):
        import random
        from unittest.mock import patch
        from cc5_support import FakeDevice, ManualExecutor
        from control_center.controller import Controller
        from control_center.runtime import Runtime
        from control_center.simulation import (SimControls, SimulatedAppleMusic, SimulatedHomeAssistant,
                                               SimulatedSonos, SimulatedWindows)
        patcher = patch("control_center.runtime.ThreadPoolExecutor", ManualExecutor)
        patcher.start()
        self.addCleanup(patcher.stop)
        device_ = FakeDevice()
        c = Controller(clock=Clock(), rng=random.Random(3))
        runtime = Runtime(c, SimulatedSonos(), SimulatedAppleMusic(), SimulatedWindows(), device_,
                          ha=SimulatedHomeAssistant(SimControls()), onshape=injector)
        self.addCleanup(runtime.shutdown)
        profiles = {"SMOOTH OPERATOR": {"knob": [{"haptic": {"detentCount": 127}}]}}
        device_.events.put({"kind": "connected", "profiles": profiles, "capabilities": capabilities})
        runtime.poll()
        device_.events.put({"kind": "ready", "id": c.control_id, "held": 0})
        runtime.poll()
        runtime.set_onshape_mode("manual")
        self.assertIsNone(runtime.toggle_onshape())
        runtime.poll()
        device_.events.put({"kind": "ready", "id": c.control_id, "held": 0})
        runtime.poll()
        return runtime, c, device_

    def frames(self, device_):
        return [cmd[1] for cmd in device_.commands if cmd[0] == "frame"]

    def test_app_canvas_knob(self):
        injector = OnshapeInjector(FakeBackend(), start=False)
        runtime, c, device_ = self.harness(CAPS_APP, injector)
        injector.step()
        self.assertTrue(runtime.app_canvas)
        self.assertIsNotNone(injector.app)
        injector.post("button", {"id": c.control_id, "button": 2, "index": 2})
        injector.post("position", {"id": c.control_id, "delta": 1})
        injector.step()
        runtime.poll()
        frame = self.frames(device_)[-1]
        self.assertEqual(frame["app"]["wheel"], {"ring": 0, "index": 1})
        self.assertEqual(frame["app"]["id"], "onshape")

    def test_older_knob_keeps_a0(self):
        injector = OnshapeInjector(FakeBackend(), start=False)
        runtime, c, device_ = self.harness(dict(CAPS_V6, controlCenter=True), injector)
        injector.step()
        self.assertFalse(runtime.app_canvas)
        self.assertIsNone(injector.app)
        self.assertTrue(all("app" not in f for f in self.frames(device_)))


if __name__ == "__main__":
    unittest.main()
