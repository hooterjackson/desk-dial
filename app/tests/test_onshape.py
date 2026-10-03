"""A0 Onshape mode (ONSHAPE.md): the injector, the key grammar, Auto, the controller mode, the
runtime and the fast path. Headless: a recording fake backend, never SendInput, never a window."""
from pathlib import Path
import json
import random
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cc5_support import Clock, FakeDevice, ManualExecutor, windows_snapshot  # noqa: E402
from r3_support import CAPS_V5, CAPS_V6, R3Fixture  # noqa: E402

from control_center import controller as controller_module  # noqa: E402
from control_center import device, navigator_model, onshape, presentation  # noqa: E402
from control_center.controller import Controller, PROFILES  # noqa: E402
from control_center.onshape import (KeyTracker, NullBackend, OnshapeAuto, OnshapeInjector,  # noqa: E402
                                    choose_profile, title_is_onshape, window_is_onshape)
from control_center.runtime import Runtime  # noqa: E402
from control_center.simulation import (SimControls, SimulatedAppleMusic, SimulatedHomeAssistant,  # noqa: E402
                                       SimulatedSonos, SimulatedWindows)
from control_center import ui  # noqa: E402

TILT_SLOT, ORBIT_SLOT, UNDO_SLOT, PAN_SLOT = 0, 1, 2, 3


class FakeBackend:
    """Records every SendInput batch; the cursor follows absolute moves like Windows would."""
    injects = True

    def __init__(self, target=True, swapped=False, modifiers=False, short_after=None):
        self.cursor_pos = (500, 400)
        self.target = target
        self.is_swapped = swapped
        self.modifiers = modifiers
        self.batches = []
        self.short_after = short_after       # the n-th batch (0-based) is short

    def cursor(self):
        return self.cursor_pos

    def target_ok(self, point):
        return self.target(point) if callable(self.target) else self.target

    def onshape_foreground(self):
        return True

    def swapped(self):
        return self.is_swapped

    def drag_threshold(self):
        return 4

    def modifiers_held(self):
        return self.modifiers

    def send(self, events):
        index = len(self.batches)
        self.batches.append(list(events))
        for event in events:
            if event[0] == "move":
                self.cursor_pos = (event[1], event[2])
        if self.short_after is not None and index == self.short_after:
            return len(events) - 1
        return len(events)

    def events(self):
        return [event for batch in self.batches for event in batch]


class InjectorCase(unittest.TestCase):
    CONTROL = 7

    def make(self, **kwargs):
        self.clock = Clock(100.0)
        self.backend = FakeBackend(**kwargs)
        self.inj = OnshapeInjector(self.backend, clock=self.clock, start=False)
        self.inj.activate(self.CONTROL, [0, 1, 2, 3], 127)
        self.inj.step()
        return self.inj

    def post(self, kind, **values):
        values.setdefault("id", self.CONTROL)
        self.inj.post(kind, values)
        self.inj.step()

    def kd(self, raw):
        self.post("button", button=raw, index=raw, pressed=True)

    def ku(self, raw):
        self.post("release", button=raw, index=raw)

    def turn(self, delta=1, times=1):
        for _ in range(times):
            self.post("position", delta=delta)


class DragTests(InjectorCase):
    def test_kd_turns_ku_one_down_the_moves_one_up_and_the_cursor_restored(self):
        self.make()
        self.kd(ORBIT_SLOT)
        self.assertEqual(self.backend.batches, [], "nothing is pressed before the first detent")
        self.turn(1, times=3)
        self.ku(ORBIT_SLOT)
        events = self.backend.events()
        self.assertEqual([e for e in events if e[0] == "down"], [("down", "right")])
        self.assertEqual([e for e in events if e[0] == "up"], [("up", "right")])
        # The first batch: press, out-and-back past the drag threshold (no net move), then the moves.
        self.assertEqual(self.backend.batches[0], [("down", "right"), ("move", 505, 400), ("move", 500, 400)])
        moves = [b for b in self.backend.batches[1:4]]
        self.assertEqual(moves, [[("move", 506, 400)], [("move", 512, 400)], [("move", 518, 400)]])
        self.assertEqual(self.backend.batches[-1], [("up", "right"), ("move", 500, 400)],
                         "the button goes up first, then the cursor goes back to where the drag began")
        self.assertEqual(self.backend.cursor_pos, (500, 400))
        self.assertEqual(self.inj.status()["dragging"], False)

    def test_pan_is_the_middle_button_and_a_negative_turn_moves_left(self):
        self.make()
        self.kd(PAN_SLOT)
        self.turn(-2)
        self.ku(PAN_SLOT)
        self.assertEqual(self.backend.batches[0][0], ("down", "middle"))
        self.assertEqual(self.backend.batches[1], [("move", 488, 400)])
        self.assertEqual(self.backend.batches[-1][0], ("up", "middle"))

    def test_swapped_mouse_buttons_press_the_physical_left_for_onshapes_right_drag(self):
        self.make(swapped=True)
        self.kd(ORBIT_SLOT)
        self.turn(1)
        self.ku(ORBIT_SLOT)
        self.assertEqual(self.backend.batches[0][0], ("down", "left"))
        self.assertEqual(self.backend.batches[-1][0], ("up", "left"))
        self.backend.batches.clear()
        self.kd(PAN_SLOT)
        self.turn(1)
        self.ku(PAN_SLOT)
        self.assertEqual(self.backend.batches[0][0], ("down", "middle"), "the middle button is never swapped")

    def test_the_button_order_maps_raw_keys_to_slots(self):
        self.make()
        self.inj.activate(self.CONTROL, [3, 2, 1, 0], 127)
        self.inj.step()
        self.kd(2)                       # raw 2 is logical slot 1 (orbit) with this order
        self.turn(1)
        self.assertEqual(self.backend.batches[0][0], ("down", "right"))

    def test_another_controls_events_are_ignored(self):
        self.make()
        self.post("button", id=99, button=ORBIT_SLOT)
        self.post("position", id=99, delta=1)
        self.assertEqual(self.backend.batches, [])


class ZoomTests(InjectorCase):
    def test_fractional_wheel_deltas_about_24_notches_per_turn(self):
        self.make()
        self.turn(1, times=127)          # one turn of SMOOTH OPERATOR
        wheel = [e[1] for e in self.backend.events() if e[0] == "wheel"]
        self.assertTrue(all(0 < n < 120 for n in wheel), "sub-notch deltas")
        self.assertAlmostEqual(sum(wheel), 24 * 120, delta=1)
        self.backend.batches.clear()
        self.turn(-1, times=127)
        self.assertAlmostEqual(sum(e[1] for e in self.backend.events()), -24 * 120, delta=1)

    def test_the_rate_follows_the_profile(self):
        self.make()
        self.inj.activate(self.CONTROL, [0, 1, 2, 3], 67)
        self.inj.step()
        self.turn(1, times=67)
        self.assertAlmostEqual(sum(e[1] for e in self.backend.events()), 24 * 120, delta=1)


class TargetTests(InjectorCase):
    def test_a_refusal_at_most_once_per_burst(self):
        self.make(target=False)
        self.turn(1, times=5)
        self.kd(ORBIT_SLOT)
        self.turn(1, times=3)
        self.ku(ORBIT_SLOT)
        self.assertEqual(self.backend.batches, [], "never an input outside Onshape's content")
        self.assertEqual(self.inj.take_events(), ["refused"])
        self.clock.advance(0.9)          # a quiet idle deadline ends the burst
        self.turn(1)
        self.assertEqual(self.inj.take_events(), ["refused"])
        self.assertEqual(self.inj.status()["refusals"], 2)

    def test_a_drag_started_on_the_model_keeps_going_when_the_cursor_leaves(self):
        self.make(target=lambda point: point == (500, 400))
        self.kd(ORBIT_SLOT)
        self.turn(1, times=3)
        self.assertEqual(len([e for e in self.backend.events() if e[0] == "move"]), 5)
        self.assertEqual(self.inj.take_events(), [])


class UndoTests(InjectorCase):
    def test_a_tap_on_3_is_one_atomic_ctrl_z(self):
        self.make()
        self.kd(UNDO_SLOT)
        self.ku(UNDO_SLOT)
        self.assertEqual(self.backend.batches, [[("key", 0x11, False), ("key", 0x5A, False), ("key", 0x5A, True),
                                                 ("key", 0x11, True)]])
        self.assertEqual(self.inj.take_events(), ["undo"])

    def test_undo_is_skipped_while_a_modifier_is_physically_held(self):
        self.make(modifiers=True)
        self.kd(UNDO_SLOT)
        self.ku(UNDO_SLOT)
        self.assertEqual(self.backend.batches, [])
        self.assertEqual(self.inj.status()["undoSkipped"], 1)

    def test_no_undo_after_a_turn_during_the_press(self):
        self.make()
        self.kd(UNDO_SLOT)
        self.turn(1)
        self.ku(UNDO_SLOT)
        self.assertFalse([e for e in self.backend.events() if e[0] == "key"])
        self.assertNotIn("undo", self.inj.take_events())

    def test_no_undo_after_a_matured_hold(self):
        self.make()
        self.kd(UNDO_SLOT)
        self.post("hold", button=UNDO_SLOT, raw=UNDO_SLOT)
        self.ku(UNDO_SLOT)
        self.assertFalse([e for e in self.backend.events() if e[0] == "key"])


class ReleaseTests(InjectorCase):
    def pressed(self):
        self.make()
        self.kd(ORBIT_SLOT)
        self.turn(1)
        self.backend.batches.clear()

    def assert_released(self, reason):
        events = self.backend.events()
        self.assertIn(("up", "right"), events)
        self.assertEqual(events[-1], ("move", 500, 400))
        self.assertIn(reason, self.inj.status()["releases"])
        self.assertFalse(self.inj.status()["dragging"])

    def test_the_watchdog_releases_after_the_idle_deadline(self):
        self.pressed()
        self.clock.advance(0.79)
        self.inj.step()
        self.assertEqual(self.backend.batches, [], "a slow orbit is not chopped")
        self.clock.advance(0.02)
        self.inj.step()
        self.assert_released("idle")

    def test_the_idle_deadline_is_a_setting(self):
        self.pressed()
        self.inj.set_idle_ms(1500)
        self.inj.step()
        self.clock.advance(1.0)
        self.inj.step()
        self.assertEqual(self.backend.batches, [])
        self.clock.advance(0.6)
        self.inj.step()
        self.assert_released("idle")

    def test_every_lost_knob_kind_releases(self):
        for kind in ("disconnected", "released", "error", "closed"):
            with self.subTest(kind=kind):
                self.pressed()
                self.inj.post(kind, {"message": "x"})
                self.inj.step()
                self.assert_released(kind)
                self.assertFalse(self.inj.status()["active"])

    def test_shutdown_releases(self):
        self.pressed()
        self.inj.close()
        self.assert_released("shutdown")

    def test_an_exception_releases_everything(self):
        self.pressed()
        self.backend.cursor = Mock(side_effect=RuntimeError("boom"))
        with self.assertLogs("control_center.onshape", "ERROR"):
            self.turn(1)
        self.assertIn(("up", "right"), self.backend.events())
        self.assertIn("exception", self.inj.status()["releases"])
        self.assertEqual(self.inj.status()["errors"], 1)

    def test_focus_loss_and_the_session_change_release(self):
        for reason in ("focus", "session"):
            with self.subTest(reason=reason):
                self.pressed()
                self.inj.release_all(reason)
                self.inj.step()
                self.assert_released(reason)

    def test_a_short_sendinput_return_releases_everything(self):
        self.make()
        self.backend.short_after = 1     # the first move after the press is short
        self.kd(ORBIT_SLOT)
        self.turn(1)
        self.assertEqual(self.backend.events()[-2:], [("up", "right"), ("move", 500, 400)])
        self.assertIn("short", self.inj.status()["releases"])
        self.assertFalse(self.inj.status()["dragging"])

    def test_a_short_press_batch_still_lets_the_button_up(self):
        self.make(short_after=0)
        self.kd(ORBIT_SLOT)
        self.turn(1)
        self.assertEqual(self.backend.batches[-1], [("up", "right"), ("move", 500, 400)])

    def test_a_short_undo_lets_ctrl_up(self):
        self.make(short_after=0)
        self.kd(UNDO_SLOT)
        self.ku(UNDO_SLOT)
        self.assertEqual(self.backend.batches[-1], [("key", 0x5A, True), ("key", 0x11, True)])

    def test_ready_without_the_modifier_ends_the_drag(self):
        self.pressed()
        self.post("ready", held=0)
        self.assert_released("ready")

    def test_deactivate_releases_and_stops(self):
        self.pressed()
        self.inj.deactivate("mode")
        self.inj.step()
        self.assert_released("mode")
        self.turn(1)
        self.assertEqual(len(self.backend.batches), 1, "inactive: nothing more")

    def test_the_thread_runs_the_watchdog_on_its_own(self):
        backend = FakeBackend()
        inj = OnshapeInjector(backend, idle_ms=200)
        try:
            inj.activate(3, [0, 1, 2, 3], 127)
            inj.post("button", {"id": 3, "button": ORBIT_SLOT})
            inj.post("position", {"id": 3, "delta": 1})
            import time
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and "idle" not in inj.status()["releases"]:
                time.sleep(0.02)
            self.assertIn("idle", inj.status()["releases"])
        finally:
            inj.close()


class TiltTests(InjectorCase):
    """Hold 1 + turn = TILT (7.2.2.0): Onshape's right-drag along y (vertical motion pitches the view), with orbit's
    burst / threshold / restore / watchdog / target machinery and the same travel per turn; no tap, no hold action."""

    def test_kd_turns_ku_one_right_drag_along_y_and_the_cursor_restored(self):
        self.make()
        self.kd(TILT_SLOT)
        self.assertEqual(self.backend.batches, [], "nothing is pressed before the first detent")
        self.turn(1, times=3)
        self.ku(TILT_SLOT)
        events = self.backend.events()
        self.assertEqual([e for e in events if e[0] == "down"], [("down", "right")])
        self.assertEqual([e for e in events if e[0] == "up"], [("up", "right")])
        self.assertFalse([e for e in events if e[0] in ("wheel", "key")], "no zoom, no key")
        # The threshold's out-and-back runs along the drag's own axis (y): no net move, no sideways spin.
        self.assertEqual(self.backend.batches[0], [("down", "right"), ("move", 500, 405), ("move", 500, 400)])
        self.assertEqual(self.backend.batches[1:4], [[("move", 500, 406)], [("move", 500, 412)], [("move", 500, 418)]],
                         "clockwise drags down (TILT_DRAG_SIGN), x never moves")
        self.assertEqual(self.backend.batches[-1], [("up", "right"), ("move", 500, 400)])
        self.assertEqual(self.backend.cursor_pos, (500, 400))
        self.assertEqual((self.inj.status()["drags"], self.inj.status()["dragging"]), (1, False))
        self.assertEqual(onshape.TILT_DRAG_SIGN, 1)

    def test_counter_clockwise_drags_up_and_the_travel_per_turn_is_orbits(self):
        self.make()
        self.inj.activate(self.CONTROL, [0, 1, 2, 3], 67)
        self.inj.step()
        self.kd(TILT_SLOT)
        self.turn(-1, times=67)                  # one turn of BINARIS BEER
        tilt_y = self.backend.cursor_pos[1] - 400
        self.ku(TILT_SLOT)
        self.backend.batches.clear()
        self.kd(ORBIT_SLOT)
        self.turn(1, times=67)
        orbit_x = self.backend.cursor_pos[0] - 500
        self.assertLess(tilt_y, 0)
        self.assertEqual(-tilt_y, orbit_x, "the same px per turn as orbit (PX_PER_TURN)")
        self.assertAlmostEqual(orbit_x, onshape.PX_PER_TURN, delta=67)

    def test_swapped_mouse_buttons_press_the_physical_left(self):
        self.make(swapped=True)
        self.kd(TILT_SLOT)
        self.turn(1)
        self.ku(TILT_SLOT)
        self.assertEqual(self.backend.batches[0][0], ("down", "left"))
        self.assertEqual(self.backend.batches[-1][0], ("up", "left"))

    def test_the_watchdog_releases_a_tilt_after_the_idle_deadline(self):
        self.make()
        self.kd(TILT_SLOT)
        self.turn(1)
        self.backend.batches.clear()
        self.clock.advance(0.79)
        self.inj.step()
        self.assertEqual(self.backend.batches, [])
        self.clock.advance(0.02)
        self.inj.step()
        self.assertEqual(self.backend.batches, [[("up", "right"), ("move", 500, 400)]])
        self.assertIn("idle", self.inj.status()["releases"])

    def test_a_refusal_off_the_model(self):
        self.make(target=False)
        self.kd(TILT_SLOT)
        self.turn(1, times=3)
        self.ku(TILT_SLOT)
        self.assertEqual(self.backend.batches, [])
        self.assertEqual(self.inj.take_events(), ["refused"])

    def test_switching_1_to_2_ends_the_tilt_and_orbits_along_x(self):
        self.make()
        self.kd(TILT_SLOT)
        self.turn(1)
        self.kd(ORBIT_SLOT)                      # the newest modifier wins: the tilt drag ends at once
        self.assertEqual(self.backend.batches[-1], [("up", "right"), ("move", 500, 400)])
        self.assertIn("switch", self.inj.status()["releases"])
        self.backend.batches.clear()
        self.turn(1)
        self.assertEqual(self.backend.batches, [[("down", "right"), ("move", 505, 400), ("move", 500, 400)],
                                                [("move", 506, 400)]])
        self.ku(ORBIT_SLOT)
        self.backend.batches.clear()
        self.turn(1)                             # 1 is still down: tilt again
        self.assertEqual(self.backend.batches[0][1], ("move", 500, 405))

    def test_the_knob_alone_still_zooms(self):
        self.make()
        self.kd(TILT_SLOT)
        self.ku(TILT_SLOT)
        self.turn(1, times=127)
        self.assertEqual({e[0] for e in self.backend.events()}, {"wheel"})

    def test_kh_and_a_tap_on_1_send_nothing(self):
        self.make()
        self.kd(0)
        self.post("hold", button=0, raw=0)       # the firmware's 600 ms kh of slot 0
        self.ku(0)
        self.kd(0)
        self.ku(0)
        self.assertEqual(self.backend.batches, [])
        self.assertEqual(self.inj.take_events(), [])


class ChordInjectorTests(InjectorCase):
    """Desk Dial's Home chord: while 3+ buttons are down nothing new starts (no drag, zoom, Undo)."""

    def test_pressing_the_four_one_by_one_ends_the_drag_and_starts_nothing(self):
        self.make()
        self.kd(ORBIT_SLOT)
        self.turn(1, times=2)                    # an orbit drag with one key down is fine
        self.kd(0)                               # two down: 1 is the newest modifier, so the turn tilts
        self.turn(1)
        self.assertTrue(self.inj.status()["dragging"])
        self.assertEqual(self.inj.status()["action"], "tilt")
        self.backend.batches.clear()
        self.kd(UNDO_SLOT)                       # the third key: the chord; the drag ends at once
        self.assertEqual(self.backend.batches, [[("up", "right"), ("move", 500, 400)]])
        self.assertIn("chord", self.inj.status()["releases"])
        self.backend.batches.clear()
        self.turn(1, times=5)                    # no zoom, no drag
        self.kd(PAN_SLOT)
        self.turn(-3)
        self.post("hold", button=0, raw=0)
        self.post("hold", button=PAN_SLOT, raw=PAN_SLOT)
        for slot in (UNDO_SLOT, 0, ORBIT_SLOT, PAN_SLOT):
            self.ku(slot)                        # tap 3 would be Undo: not in a chord
        self.assertEqual(self.backend.batches, [])
        self.assertEqual(self.inj.take_events(), [])
        self.assertEqual(self.inj.status()["drags"], 2, "the orbit, then the tilt; nothing in the chord")

    def test_a_chord_key_still_down_keeps_the_chord_until_released(self):
        self.make()
        for slot in (0, ORBIT_SLOT, UNDO_SLOT):
            self.kd(slot)
        self.ku(0)
        self.ku(UNDO_SLOT)
        self.turn(1, times=3)                    # 2 is still down from the chord: no orbit, no tilt
        self.assertEqual(self.backend.batches, [])
        self.ku(ORBIT_SLOT)
        self.turn(1, times=127)                  # the chord is over: the knob zooms again
        self.assertTrue([e for e in self.backend.events() if e[0] == "wheel"])
        self.kd(UNDO_SLOT)
        self.ku(UNDO_SLOT)
        self.assertEqual(self.inj.take_events(), ["undo"], "and 3 taps Undo again")


class KeyTrackerTests(unittest.TestCase):
    def test_a_turn_drops_the_tap_and_the_hold(self):
        keys = KeyTracker()
        keys.down(0)
        keys.turn()
        self.assertIsNone(keys.hold(0))
        self.assertIsNone(keys.up(0))
        keys.down(0)
        self.assertEqual(keys.hold(0), "hold")
        self.assertIsNone(keys.up(0), "a matured hold is not also a tap")
        keys.down(2)
        self.assertEqual(keys.up(2), "tap")

    def test_the_newest_modifier_wins_and_ready_reseeds(self):
        keys = KeyTracker()
        keys.down(1)
        keys.down(3)
        self.assertEqual(keys.action(), "pan")
        keys.up(3)
        self.assertEqual(keys.action(), "orbit")
        keys.seed(0)
        self.assertEqual((keys.action(), keys.mask), ("zoom", 0))
        keys.seed(1 << 3)
        self.assertEqual(keys.action(), "pan")
        self.assertIsNone(keys.up(3), "a press seen only through ready.held never taps")
        keys.down(0)
        self.assertEqual((keys.modifier_slot(), keys.action()), (0, "tilt"))
        keys.down(1)
        self.assertEqual(keys.action(), "orbit")
        keys.up(1)
        self.assertEqual(keys.action(), "tilt")
        self.assertEqual(keys.up(0), "tap", "never turned: a tap (it sends nothing)")


    def test_three_keys_down_is_a_chord_with_no_tap_hold_or_modifier(self):
        keys = KeyTracker()
        keys.down(1)
        keys.down(2)
        self.assertFalse(keys.chording)
        self.assertEqual(keys.action(), "orbit")
        keys.down(0)
        self.assertTrue(keys.chording)
        self.assertEqual((keys.modifier_slot(), keys.action(), keys.count), (None, "zoom", 3))
        keys.down(3)
        self.assertEqual(keys.mask, 0xF)
        self.assertIsNone(keys.hold(0))
        self.assertIsNone(keys.hold(3))
        self.assertEqual([keys.up(s) for s in (2, 0, 3)], [None, None, None])
        self.assertTrue(keys.chording, "2 is still down from the chord")
        keys.down(2)
        self.assertIsNone(keys.up(2), "pressed during the chord: chorded too")
        self.assertIsNone(keys.up(1))
        self.assertFalse(keys.chording)
        keys.down(2)
        self.assertEqual(keys.up(2), "tap", "the chord is over")

class TitleMatchTests(unittest.TestCase):
    TABLE = (
        ("chrome.exe", "Bracket | Onshape - Google Chrome", True),
        ("chrome.exe", "Onshape - Google Chrome", True),
        ("chrome.exe", "Bracket - Onshape - Google Chrome", True),
        ("chrome.exe", "Bracket | Onshape - Google Chrome - Someone", True),
        ("msedge.exe", "Bracket | Onshape - Microsoft​ Edge", True),
        ("msedge.exe", "Bracket | Onshape and 3 more pages - Personal - Microsoft Edge", True),
        ("msedge.exe", "Bracket | Onshape - Profile 1 - Microsoft Edge", True),
        ("MSEDGE.EXE", "Bracket | Onshape - Microsoft Edge", True),
        ("chrome.exe", "Onshape - Google Search - Google Chrome", False),
        ("chrome.exe", "Onshape tutorial | YouTube - Google Chrome", False),
        ("chrome.exe", "Onshape - Wikipedia - Google Chrome", False),
        ("chrome.exe", "My onshape notes - Google Docs - Google Chrome", False),
        ("chrome.exe", "Google Chrome", False),
        ("chrome.exe", "", False),
        ("firefox.exe", "Bracket | Onshape - Mozilla Firefox", False),
        ("notepad.exe", "Bracket | Onshape", False),
        ("chrome.exe", None, False),
    )

    def test_the_title_table(self):
        for exe, title, expected in self.TABLE:
            with self.subTest(exe=exe, title=title):
                self.assertIs(window_is_onshape(exe, title), expected)

    def test_a_tab_switch_within_one_window_is_seen(self):
        titles = {"t": "Bracket | Onshape - Google Chrome"}
        hooks = []

        class FakeUser:
            def SetWinEventHook(self, *args):
                hooks.append(args)
                return len(hooks)

            def UnhookWinEvent(self, hook):
                return True

        windows = Mock()
        windows.u = FakeUser()
        windows.foreground.return_value = 0x1234
        windows.pid.return_value = 42
        windows.exe.return_value = "chrome.exe"
        windows.is_onshape.side_effect = lambda hwnd: window_is_onshape("chrome.exe", titles["t"])
        clock = Clock(10.0)
        watcher = onshape.FocusWatcher(windows, clock=clock, hook=False)
        self.assertTrue(watcher.focused())
        self.assertEqual(hooks[-1][0], onshape.EVENT_OBJECT_NAMECHANGE, "the browser's name changes are hooked")
        self.assertEqual(hooks[-1][4], 42, "only the foreground browser's process")
        titles["t"] = "Inbox - Gmail - Google Chrome"      # another tab of the same window
        clock.advance(0.05)
        self.assertTrue(watcher.focused(), "cached between name changes")
        watcher._callbacks[1](None, onshape.EVENT_OBJECT_NAMECHANGE, 0x1234, 0, 0, 0, 0)
        self.assertFalse(watcher.focused(), "the NAMECHANGE marks it stale")
        titles["t"] = "Bracket | Onshape - Google Chrome"
        clock.advance(0.3)
        self.assertTrue(watcher.focused(), "the 250 ms poll is the fallback")
        watcher.close()


class ContentWidgetTests(unittest.TestCase):
    """WindowFromPoint must be the browser's content widget whose root is Onshape in front."""

    def make(self, at_point, classes, roots, foreground=100, onshape_roots=(100,)):
        windows = object.__new__(onshape.OnshapeWindows)
        user = Mock()
        user.WindowFromPoint.side_effect = lambda point: at_point
        user.GetAncestor.side_effect = lambda hwnd, flag: roots.get(hwnd, hwnd)
        user.GetForegroundWindow.return_value = foreground
        windows.u, windows.k, windows._exes = user, None, {}
        windows.classes = onshape.CONTENT_CLASSES
        windows.class_name = lambda hwnd: classes.get(hwnd, "")
        windows.is_onshape = lambda hwnd: hwnd in onshape_roots
        return windows

    def test_the_tab_strip_is_refused(self):
        windows = self.make(100, {100: "Chrome_WidgetWin_1"}, {})
        with patch.object(onshape, "W", Mock()):
            self.assertFalse(windows.target_ok((10, 10)))

    def test_the_content_widget_of_onshape_is_accepted(self):
        windows = self.make(200, {200: "Chrome_RenderWidgetHostHWND"}, {200: 100})
        with patch.object(onshape, "W", Mock()):
            self.assertTrue(windows.target_ok((500, 400)))

    def test_another_windows_content_or_a_background_onshape_is_refused(self):
        other = self.make(300, {300: "Chrome_RenderWidgetHostHWND"}, {300: 555})
        background = self.make(200, {200: "Chrome_RenderWidgetHostHWND"}, {200: 100}, foreground=555)
        not_onshape = self.make(200, {200: "Chrome_RenderWidgetHostHWND"}, {200: 100}, onshape_roots=())
        with patch.object(onshape, "W", Mock()):
            self.assertFalse(other.target_ok((1, 1)))
            self.assertFalse(background.target_ok((1, 1)))
            self.assertFalse(not_onshape.target_ok((1, 1)))

    def test_the_class_list_is_configurable(self):
        self.assertEqual(onshape.normal_classes(["Chrome_RenderWidgetHostHWND", "MyEdgeWidget"]),
                         ("Chrome_RenderWidgetHostHWND", "MyEdgeWidget"))
        self.assertEqual(onshape.normal_classes([]), onshape.CONTENT_CLASSES)
        self.assertEqual(onshape.normal_classes("x"), onshape.CONTENT_CLASSES)


class AutoTests(unittest.TestCase):
    def test_enter_at_once_exit_half_a_second_after_the_loss(self):
        auto = OnshapeAuto()
        self.assertEqual(auto.update(1.0, "auto", True, False, True), "enter")
        self.assertTrue(auto.pending)
        self.assertIsNone(auto.update(1.1, "auto", True, True, True))
        self.assertIsNone(auto.update(2.0, "auto", False, True, True))
        self.assertIsNone(auto.update(2.4, "auto", False, True, True))
        self.assertEqual(auto.update(2.5, "auto", False, True, True), "exit")

    def test_a_short_loss_is_forgiven(self):
        auto = OnshapeAuto()
        auto.update(2.0, "auto", False, True, True)
        auto.update(2.3, "auto", True, True, True)
        self.assertIsNone(auto.update(2.9, "auto", False, True, True))

    def test_a_user_exit_waits_for_loss_and_regain(self):
        auto = OnshapeAuto()
        auto.suppress()
        self.assertIsNone(auto.update(1.0, "auto", True, False, True))
        self.assertIsNone(auto.update(5.0, "auto", True, False, True))
        self.assertIsNone(auto.update(6.0, "auto", False, False, True))
        self.assertEqual(auto.update(7.0, "auto", True, False, True), "enter")

    def test_never_while_it_cannot_enter_or_not_auto(self):
        auto = OnshapeAuto()
        self.assertIsNone(auto.update(1.0, "auto", True, False, False))
        self.assertFalse(auto.pending)
        for setting in ("off", "manual"):
            self.assertIsNone(auto.update(1.0, setting, True, False, True))
            self.assertIsNone(auto.update(9.0, setting, False, True, True), "Manual stays until the user leaves")


class ControllerTests(R3Fixture):
    def enter(self):
        self.assertTrue(self.c.enter_onshape("test"))
        self.c.drain()

    def test_the_mode_tables(self):
        self.assertIn("onshape", controller_module.MODES)
        self.assertEqual(PROFILES["onshape"], "BINARIS BEER")   # 2026-09-30: the 127-detent profiles buzzed
        self.assertEqual(controller_module.MODE_TITLES["onshape"], "ONSHAPE")

    def test_entry_is_recentred_on_the_fine_profile(self):
        self.c.onshape_profile = "SHAVED OPERATOR"
        self.assertTrue(self.c.enter_onshape("test"))
        enter = [e for e in self.c.drain() if e["kind"] == "device_enter"][-1]["control"]
        self.assertEqual((enter["min"], enter["max"], enter["position"], enter["profile"]),
                         (0, 60000, 30000, "SHAVED OPERATOR"))
        self.assertFalse(enter["windowsHidEnabled"])

    def test_a_far_travel_is_recentred_after_a_quiet_moment(self):
        self.enter()
        first = self.c.control_id
        self.turn_to(30000 + 25001)
        self.tick(0.5)
        enter = [e for e in self.c.drain() if e["kind"] == "device_enter"]
        self.assertEqual(enter[-1]["control"]["position"], 30000)
        self.assertGreater(self.c.control_id, first)

    def test_the_frame(self):
        self.enter()
        frame = self.frame()
        self.assertEqual((frame["layout"], frame["heading"], frame["title"]), ("nowPlaying", "ONSHAPE", "ZOOM"))
        self.assertEqual([b["label"] for b in frame["buttons"]], ["Tilt", "Orbit", "Undo", "Pan"])
        self.assertEqual([b["icon"] for b in frame["buttons"]], ["expand", "shuffle", "back", "expand"])
        self.assertEqual(frame["subtitle"], "1 tilt · 2 orbit · 4 pan")
        self.assertTrue(all(b["icon"] in presentation.ICONS_V6 for b in frame["buttons"]))
        self.assertEqual(frame["ring"]["style"], "off")
        self.assertNotIn("holdMarker", frame)
        self.assertNotIn("crumb", frame)
        self.assertEqual(self.c.hold_action(), "")
        self.c.onshape_input("down", ORBIT_SLOT)
        frame = self.frame()
        self.assertEqual(frame["title"], "ORBIT")
        self.assertEqual(frame["buttons"][1].get("lit"), "on")
        self.c.onshape_input("down", PAN_SLOT)
        self.assertEqual(self.frame()["title"], "PAN")
        self.c.onshape_input("up", PAN_SLOT)
        self.c.onshape_input("up", ORBIT_SLOT)
        self.assertEqual(self.frame()["title"], "ZOOM")
        self.c.onshape_input("refused")
        frame = self.frame()
        self.assertEqual(frame["title"], "Point at the model")
        self.assertEqual((frame["feedback"]["kind"], frame["feedback"]["moment"]), ("err", "refused"))
        self.tick(2.1)
        self.assertEqual(self.frame()["title"], "ZOOM")

    def test_every_frame_passes_the_device_validator(self):
        self.enter()
        for step in (None, ("down", ORBIT_SLOT), ("down", PAN_SLOT), ("refused",), ("undo",)):
            if step:
                self.c.onshape_input(*step)
            with self.subTest(step=step):
                wire = self.wire(CAPS_V6)
                self.assertEqual(wire["layout"], "nowPlaying")
                self.assertEqual(wire["heading"], "ONSHAPE")
                self.assertLessEqual(device.frame_line_bytes(wire), presentation.FRAME_BUDGET_BYTES_V5)
                stored, invalid = device.v5_parse(dict(device._frame({"id": 3, **self.c.frame()}, CAPS_V5)))
                self.assertEqual(invalid, [])

    def test_hold_1_is_tilt_and_never_home(self):
        self.enter()
        self.c.onshape_input("down", 0)
        frame = self.frame()
        self.assertEqual((frame["title"], frame["subtitle"]), ("TILT", "Turn to tilt"), "hold 1 + turn tilts (7.2.2.0)")
        self.assertEqual(frame["buttons"][0].get("lit"), "on")
        self.assertIsNone(frame["buttons"][1].get("lit"))
        self.c.onshape_input("turn", None, 1)
        self.c.onshape_input("hold", 0)
        self.c.hold(0, self.c.control_id)    # the firmware's kh of slot 0 (600 ms) does nothing here
        self.assertEqual(self.c.screen.mode, "onshape")
        self.c.onshape_input("up", 0)
        self.assertIsNone(self.transient(), "a turn during the press drops its tap")
        self.c.onshape_input("down", 0)
        self.c.onshape_input("hold", 0)
        self.c.onshape_input("up", 0)
        self.assertEqual(self.c.screen.mode, "onshape", "a hold on 1 alone never leaves")
        self.assertIsNone(self.transient(), "a matured hold is no tap")
        self.c.onshape_input("down", 0)
        self.c.onshape_input("up", 0)
        self.assertEqual(self.transient(), "Hold all 4 for Home", "a tap on 1 sends nothing, only says how to leave")
        self.assertEqual(self.c.onshape_user_exits, 0)

    def test_three_keys_down_say_how_to_finish_the_home_chord(self):
        self.enter()
        for slot in (0, ORBIT_SLOT):
            self.c.onshape_input("down", slot)
        self.assertNotEqual(self.frame().get("status"), "Hold all 4 for Home")
        self.c.onshape_input("down", UNDO_SLOT)
        frame = self.frame()
        self.assertEqual((frame["status"], frame["title"]), ("Hold all 4 for Home", "ZOOM"))
        self.assertIsNone(frame["buttons"][1].get("lit"), "no orbit while the chord builds")
        self.assertFalse(self.c.onshape_chord_due())
        self.c.onshape_input("down", PAN_SLOT)
        self.tick(0.9921875)
        self.assertFalse(self.c.onshape_chord_due())
        self.tick(0.0078125)
        self.assertTrue(self.c.onshape_chord_due())
        self.assertEqual(self.c.screen.mode, "onshape", "the controller's tick never fires it: the runtime does")
        self.assertTrue(self.c.onshape_home_chord())
        self.assertEqual((self.c.screen.mode, self.c.onshape_user_exits), ("launcher", 1))

    def test_a_ready_mask_of_all_four_never_starts_the_home_chord(self):
        self.enter()
        self.c.onshape_input("ready", 0xF)
        self.tick(2.0)
        self.assertFalse(self.c.onshape_chord_due())

    def test_presentation_6_only(self):
        self.c.set_spaces(False)
        self.assertFalse(self.c.enter_onshape("test"))
        self.c.set_spaces(True)
        self.enter()
        self.c.set_spaces(False)
        self.assertEqual(self.c.screen.mode, "home", "an older knob never keeps the mode")

    def test_never_over_an_overlay_or_seek(self):
        self.press(1)                        # the launcher's Win: the picker is opening
        effect = self.one("windows_open")
        self.assertFalse(self.c.enter_onshape("auto"))
        self.c.complete(effect["request"], windows_snapshot(4))
        self.assertEqual(self.c.screen.mode, "windows")
        self.assertFalse(self.c.enter_onshape("auto"))
        self.hold()
        self.tick(1.0)                       # past the launcher's overshoot guard
        self.press(0)                        # Music
        self.press(2)                        # Tracks
        self.press(2)                        # Seek
        self.assertEqual(self.c.screen.mode, "seek")
        self.assertFalse(self.c.enter_onshape("auto"))

    def test_no_sonos_volume_writes_while_pending_or_active(self):
        self.turn_to(40)                     # a volume target not yet written
        self.c.onshape_pending = True
        self.turn_to(45)
        self.assertEqual(self.c.desired_volume, 40, "pending: the knob no longer sets volume")
        self.tick(0.2)
        self.assertFalse([e for e in self.c.drain() if e["kind"] == "volume"])
        self.c.onshape_pending = False
        self.enter()
        self.assertIsNone(self.c.desired_volume, "the unsent target is dropped on entry")
        self.turn_to(40000)
        self.tick(0.5)
        self.assertFalse([e for e in self.c.drain() if e["kind"] == "volume"])

    def test_disconnect_leaves_the_mode(self):
        self.enter()
        self.c.disconnected()
        self.assertEqual(self.c.screen.mode, "launcher")


class RuntimeHarness:
    def __init__(self, testcase, level=6, injector=None, focus=None):
        patcher = patch("control_center.runtime.ThreadPoolExecutor", ManualExecutor)
        patcher.start()
        testcase.addCleanup(patcher.stop)
        self.device = FakeDevice()
        self.c = Controller(clock=Clock(), rng=random.Random(3))
        self.runtime = Runtime(self.c, SimulatedSonos(), SimulatedAppleMusic(), SimulatedWindows(), self.device,
                               ha=SimulatedHomeAssistant(SimControls()), onshape=injector, onshape_focus=focus)
        testcase.addCleanup(self.runtime.shutdown)
        profiles = {name: {"knob": [{"haptic": {"detentCount": 127}}]} for name in ("BINARIS BEER", "SMOOTH OPERATOR")}
        self.device.events.put({"kind": "connected", "profiles": profiles,
                                "capabilities": {"controlCenter": True, "presentation": level}})
        self.runtime.poll()
        self.ready()

    def ready(self, held=0):
        self.device.events.put({"kind": "ready", "id": self.c.control_id, "held": held})
        self.runtime.poll()

    def event(self, kind, **values):
        values.setdefault("id", self.c.control_id)
        self.device.events.put({"kind": kind, **values})
        self.runtime.poll()


class Focus:
    def __init__(self, value=False):
        self.value = value

    def focused(self, now=None):
        return self.value

    def close(self):
        pass


class RuntimeTests(unittest.TestCase):
    def test_auto_enters_with_onshape_in_front_and_leaves_after_the_loss(self):
        focus = Focus()
        injector = OnshapeInjector(FakeBackend(), start=False)
        h = RuntimeHarness(self, injector=injector, focus=focus)
        h.runtime.set_onshape_mode("auto")
        focus.value = True
        h.runtime.poll()
        self.assertEqual(h.c.screen.mode, "onshape")
        enter = [c for c in h.device.commands if c[0] == "enter"][-1][1]
        self.assertEqual((enter["profile"], enter["position"]), ("BINARIS BEER", 30000))
        self.assertEqual(h.runtime.onshape_fast_state(), "active")
        injector.step()
        self.assertTrue(injector.status()["active"])
        focus.value = False
        with patch("control_center.runtime.time.monotonic", side_effect=[1000.0, 1000.0, 1000.0, 1000.0]):
            h.runtime.poll()
        self.assertEqual(h.c.screen.mode, "onshape", "not at once")
        with patch("control_center.runtime.time.monotonic", return_value=1000.6):
            h.runtime.poll()
        self.assertEqual(h.c.screen.mode, "launcher")
        injector.step()
        self.assertFalse(injector.status()["active"])

    def test_hold_1_never_exits(self):
        focus = Focus(True)
        h = RuntimeHarness(self, focus=focus)
        h.runtime.set_onshape_mode("auto")
        h.runtime.poll()
        h.ready()
        self.assertEqual(h.c.screen.mode, "onshape")
        h.event("button", button=0, index=0)
        h.event("hold", button=0, raw=0)
        h.event("release", button=0, index=0)
        self.assertEqual(h.c.screen.mode, "onshape")
        self.assertFalse(h.runtime.onshape_auto.suppressed)

    def test_a_turn_during_the_press_drops_the_tap_and_the_hold(self):
        h = RuntimeHarness(self)
        h.runtime.set_onshape_mode("manual")
        self.assertIsNone(h.runtime.toggle_onshape())
        h.ready()
        h.event("button", button=0, index=0)
        h.event("position", p=32769, position=32769, delta=1)
        h.event("hold", button=0, raw=0)
        h.event("release", button=0, index=0)
        self.assertEqual(h.c.screen.mode, "onshape")
        self.assertIsNone(h.c._transient())

    def test_the_held_mask_follows_kd_release_and_ready(self):
        h = RuntimeHarness(self)
        h.runtime.button_order = [0, 1, 3, 2]

        def event(kind, **values):             # events only (a press may enter a screen: that clears the mask)
            h.device.events.put({"kind": kind, "id": h.c.control_id, **values})
            h.runtime._device_events()
        h.runtime.on_button_probe = lambda raw: None
        event("button", button=3, index=3)
        self.assertEqual(h.runtime.held_mask, 1 << 3)
        event("release", button=3, index=3)
        self.assertEqual(h.runtime.held_mask, 0)
        h.runtime.on_button_probe = None
        h.device.events.put({"kind": "ready", "id": h.c.control_id, "held": 1 << 2})
        h.runtime._device_events()            # (an enter later in the same poll clears it again)
        self.assertEqual(h.runtime.held_mask, 1 << 3, "logical slot 2 is raw 3 with this order")
        h.event("disconnected")
        self.assertEqual(h.runtime.held_mask, 0)

    def test_no_sonos_volume_while_active(self):
        h = RuntimeHarness(self)
        h.runtime.set_onshape_mode("manual")
        h.runtime.toggle_onshape()
        h.ready()
        for p in (32769, 32770, 32771):
            h.event("position", p=p, position=p, delta=1)
        h.runtime.poll()
        self.assertFalse([e for e in h.c.pending.values() if e["kind"] == "volume"])
        self.assertIsNone(h.c.desired_volume)

    def test_presentation_5_never_enters(self):
        focus = Focus(True)
        h = RuntimeHarness(self, level=5, focus=focus)
        h.runtime.set_onshape_mode("auto")
        h.runtime.poll()
        self.assertEqual(h.c.screen.mode, "home")
        h.runtime.set_onshape_mode("manual")
        self.assertIn("firmware", h.runtime.toggle_onshape())

    def test_the_tray_toggle_and_off(self):
        h = RuntimeHarness(self)
        self.assertIn("Settings", h.runtime.toggle_onshape(), "Off: the tray explains")
        h.runtime.set_onshape_mode("manual")
        self.assertEqual(h.runtime.onshape_menu_text(), "Onshape mode")
        self.assertIsNone(h.runtime.toggle_onshape())
        self.assertEqual(h.runtime.onshape_menu_text(), "Leave Onshape mode")
        h.runtime.set_onshape_mode("off")
        self.assertEqual(h.c.screen.mode, "launcher")

    def test_lost_knob_and_shutdown_release_the_injector(self):
        injector = Mock()
        injector.take_events.return_value = []
        h = RuntimeHarness(self, injector=injector)
        h.runtime.set_onshape_mode("manual")
        h.runtime.toggle_onshape()
        h.runtime.poll()
        injector.activate.assert_called_with(h.c.control_id, [0, 1, 2, 3], 127, app=False)   # A2: no appCanvas
        h.event("released")
        injector.deactivate.assert_called()
        h.runtime.shutdown()
        injector.close.assert_called()

    def test_injector_results_reach_the_knob_and_status_has_no_titles(self):
        injector = OnshapeInjector(FakeBackend(target=False), start=False)
        focus = Focus(True)
        h = RuntimeHarness(self, injector=injector, focus=focus)
        h.runtime.set_onshape_mode("manual")
        h.runtime.toggle_onshape()
        h.runtime.poll()
        h.ready()
        injector.step()
        injector.post("position", {"id": h.c.control_id, "delta": 1})
        injector.step()
        h.runtime.poll()
        self.assertEqual(h.c.frame()["title"], "Point at the model")
        status = h.runtime.onshape_status()
        self.assertEqual((status["mode"], status["active"], status["refusals"]), ("manual", True, 1))
        text = json.dumps(status)
        self.assertNotIn("Onshape -", text)
        self.assertEqual(set(status), {"mode", "active", "pending", "focused", "suppressed", "profile", "refusals",
                                       "injector"})

    def test_the_profile_falls_back_when_the_inventory_lacks_it(self):
        self.assertEqual(choose_profile({"BINARIS BEER": {}}), ("BINARIS BEER", 67))
        # 2026-09-30: never the 127-detent profiles (they buzzed); BINARIS BEER's own detent count is used.
        self.assertEqual(choose_profile({"SMOOTH OPERATOR": {"knob": [{"haptic": {"detentCount": 127}}]},
                                         "BINARIS BEER": {"knob": [{"haptic": {"detentCount": 67}}]}}),
                         ("BINARIS BEER", 67))
        self.assertEqual(choose_profile({"SHAVED OPERATOR": {}})[0], "BINARIS BEER")

    def test_orbit_travel_per_turn_stays_the_same_on_any_profile(self):
        from control_center import onshape as O
        inj = O.OnshapeInjector(start=False)
        self.assertEqual(inj.px, 11)
        self.assertEqual(O.OnshapeInjector(start=False, px_per_detent=6).px, 6)


class HomeChordRuntimeTests(unittest.TestCase):
    """All four buttons held 1.0 s (from the 4th press) = Home; the runtime fires it (release first, swallow the
    four buttons' later holds and releases, suppress Auto until Onshape loses and regains the foreground)."""

    def entered(self, injector=None):
        self.focus = Focus(True)
        h = RuntimeHarness(self, injector=injector, focus=self.focus)
        h.runtime.set_onshape_mode("auto")
        h.runtime.poll()
        h.ready()
        self.assertEqual(h.c.screen.mode, "onshape")
        return h

    def press_all(self, h, order=(1, 0, 2, 3), gap=0.25):
        for raw in order:
            h.event("button", button=raw, index=raw)
            h.c.clock.advance(gap)

    def test_fires_at_one_second_from_the_fourth_press_and_suppresses_auto(self):
        h = self.entered()
        self.press_all(h)                                   # the 4th press at +0.75 s, then +0.25 s
        h.c.clock.advance(0.7421875)                        # 0.9921875 s since the 4th press
        h.runtime.poll()
        self.assertEqual(h.c.screen.mode, "onshape")
        h.c.clock.advance(0.0078125)
        h.runtime.poll()
        self.assertEqual(h.c.screen.mode, "launcher")
        self.assertEqual(h.c.onshape_user_exits, 1)
        self.assertTrue(h.runtime.onshape_auto.suppressed)
        h.runtime.poll()
        self.assertEqual(h.c.screen.mode, "launcher", "Auto waits")
        self.focus.value = False
        h.runtime.poll()
        self.focus.value = True
        h.runtime.poll()
        self.assertEqual(h.c.screen.mode, "onshape", "until Onshape lost and regained the foreground")

    def test_any_release_before_one_second_cancels(self):
        h = self.entered()
        self.press_all(h, gap=0.0)
        h.c.clock.advance(0.875)
        h.event("release", button=2, index=2)
        h.c.clock.advance(0.5)
        h.runtime.poll()
        self.assertEqual(h.c.screen.mode, "onshape")
        h.event("button", button=2, index=2)               # all four again: a new 1.0 s from this press
        h.c.clock.advance(0.9921875)
        h.runtime.poll()
        self.assertEqual(h.c.screen.mode, "onshape")
        h.c.clock.advance(0.0078125)
        h.runtime.poll()
        self.assertEqual(h.c.screen.mode, "launcher")

    def test_after_it_fires_the_four_buttons_holds_and_releases_are_swallowed(self):
        h = self.entered()
        domain = h.c.home_domain
        self.press_all(h, order=(0, 1, 2, 3), gap=0.0)
        h.c.clock.advance(1.0)
        h.runtime.poll()
        self.assertEqual(h.c.screen.mode, "launcher")
        h.ready(held=0xF)                                   # the Home control's ready: all four still down
        h.event("hold", button=3, raw=3)                    # button 4's 1.0 s kh, late: never Home's hold 4
        h.event("hold", button=0, raw=0)
        self.assertEqual(h.c.home_domain, domain)
        for raw in (0, 1, 2, 3):
            h.event("release", button=raw, index=raw)       # no tap on Home (1 would open Music)
        h.runtime.poll()
        self.assertEqual(h.c.screen.mode, "launcher")
        self.assertEqual(h.runtime._chord_swallow, set())
        self.assertEqual(h.runtime._pending_taps, {})
        h.c.clock.advance(1.5)                              # past the launcher's overshoot guard
        h.event("button", button=0, index=0)                # the next press is an ordinary one again
        h.event("release", button=0, index=0)
        self.assertNotEqual(h.c.screen.mode, "launcher")

    def test_the_injector_releases_everything_and_stops(self):
        injector = OnshapeInjector(FakeBackend(), start=False)
        h = self.entered(injector)
        injector.step()
        control = h.c.control_id
        injector.post("button", {"id": control, "button": ORBIT_SLOT})
        injector.post("position", {"id": control, "delta": 2})
        injector.step()
        self.assertTrue(injector.status()["dragging"])
        h.event("button", button=1, index=1)
        for raw in (0, 2, 3):
            injector.post("button", {"id": control, "button": raw})
            h.event("button", button=raw, index=raw)
        injector.step()
        self.assertFalse(injector.status()["dragging"], "the drag ended when the third key went down")
        h.c.clock.advance(1.0)
        h.runtime.poll()
        injector.step()
        self.assertEqual(h.c.screen.mode, "launcher")
        self.assertFalse(injector.status()["active"])
        before = injector.status()
        for raw in (0, 1, 2, 3):
            injector.post("release", {"id": control, "button": raw})
        injector.post("position", {"id": control, "delta": 5})
        injector.step()
        after = injector.status()
        self.assertEqual((after["undo"], after["wheel"], after["drags"]), (before["undo"], before["wheel"], 1))

    def test_hold_1_or_three_keys_never_fire_it(self):
        h = self.entered()
        for raw in (0, 1, 2):
            h.event("button", button=raw, index=raw)
        h.event("hold", button=0, raw=0)
        h.c.clock.advance(3.0)
        h.runtime.poll()
        self.assertEqual(h.c.screen.mode, "onshape")


class FastPathTests(unittest.TestCase):
    def make(self, state):
        overlay, navigator, injector = Mock(), Mock(), Mock()
        fast = ui.FastPath(overlay=overlay, navigator=navigator)
        fast.onshape, fast.onshape_state = injector, state
        return fast, overlay, navigator, injector

    def test_navigator_and_floating_knob_get_nothing_while_onshape_is_on(self):
        for state in ("pending", "active"):
            with self.subTest(state=state):
                fast, overlay, navigator, injector = self.make(state)
                self.assertTrue(fast.handle("position", {"id": 4, "position": 9, "delta": 1}, 1.0))
                self.assertTrue(fast.handle("button", {"id": 4, "button": 1}, 1.0))
                overlay.post_input.assert_not_called()
                navigator.note_turn.assert_not_called()
                navigator.note_press.assert_not_called()
                self.assertEqual([c.args[0] for c in injector.post.call_args_list], ["position", "button"])

    def test_off_keeps_the_floating_knob_and_navigator(self):
        fast, overlay, navigator, injector = self.make("off")
        fast.handle("position", {"id": 4, "position": 9, "delta": 1}, 1.0)
        overlay.post_input.assert_called()
        navigator.note_turn.assert_called_once_with()

    def test_the_other_kinds_are_forwarded_only_enqueued(self):
        fast, overlay, navigator, injector = self.make("off")
        for kind in ("release", "hold", "ready", "disconnected", "released", "error", "closed"):
            self.assertFalse(fast.handle(kind, {"id": 4}, 1.0))
        self.assertEqual([c.args[0] for c in injector.post.call_args_list],
                         ["release", "hold", "ready", "disconnected", "released", "error", "closed"])
        overlay.post_input.assert_not_called()

    def test_install_forwards_every_kind_the_injector_needs(self):
        bridge = Mock()
        seen = []
        bridge._emit = lambda kind, **values: seen.append(kind)
        fast = Mock()
        self.assertTrue(ui.install_fast_path(bridge, fast))
        for kind in ("position", "release", "ready", "released", "connected"):
            bridge._emit(kind, id=1)
        self.assertEqual([c.args[0] for c in fast.handle.call_args_list], ["position", "release", "ready", "released"])
        self.assertEqual(seen, ["position", "release", "ready", "released", "connected"])


class NavigatorTests(unittest.TestCase):
    def test_the_navigator_has_no_onshape_card_yet(self):
        self.assertIsNone(navigator_model.build_content({"mode": "onshape", "frame": {}, "state": {}}))
        self.assertEqual(navigator_model.KEY_WORDS["onshape"], ("Tilt", "Orbit", "Undo", "Pan"))


class SimulatorTests(unittest.TestCase):
    def test_the_simulator_and_the_smoke_test_never_inject(self):
        app = object.__new__(ui.ControlCenterApp)
        app.smoke, app.config = False, {}
        self.assertEqual(app.onshape_provider(False), (None, None, None))
        app.smoke = True
        self.assertEqual(app.onshape_provider(True), (None, None, None))

    def test_the_default_runtime_has_no_injector_and_the_null_backend_sends_nothing(self):
        h = RuntimeHarness(self)
        self.assertIsNone(h.runtime.onshape)
        backend = NullBackend()
        self.assertFalse(backend.injects)
        injector = OnshapeInjector(backend, start=False)
        injector.activate(1)
        injector.post("position", {"id": 1, "delta": 3})
        injector.step()
        self.assertEqual(injector.status()["wheel"], 0)

    def test_settings_default_off_and_validated(self):
        with patch.object(ui, "DATA_DIR", Path(__file__).resolve().parent / "no-such-dir"):
            config = ui.ControlCenterApp.load_config()
        self.assertEqual((config["onshape_mode"], config["onshape_idle_ms"]), ("off", 800))
        self.assertEqual(config["onshape_content_classes"], ["Chrome_RenderWidgetHostHWND"])
        self.assertEqual(onshape.normal_mode("sometimes"), "off")
        self.assertEqual(onshape.normal_idle_ms(10), 200)
        self.assertIn("onshape", ui.MODE_DESCRIPTIONS)




class AddressBarDetectionTests(unittest.TestCase):
    """2026-09-30: Onshape's tab titles never say "Onshape" ("scarlett solo | Focusrite ..."), so Auto also
    reads the browser's address bar host (UI Automation); cached per (window, title)."""

    def test_hosts(self):
        from control_center import onshape as O
        for host, ok in (("cad.onshape.com", True), ("acme.onshape.com", True), ("www.onshape.com", False),
                         ("learn.onshape.com", False), ("onshape.com", False), ("google.com", False),
                         ("cad.onshape.com.evil.com", False), ("", False), (None, False)):
            with self.subTest(host=host):
                self.assertEqual(O.host_is_onshape(host), ok)

    def test_host_of(self):
        from control_center.browser_url import host_of
        self.assertEqual(host_of("cad.onshape.com/documents/abc/w/def"), "cad.onshape.com")
        self.assertEqual(host_of("https://CAD.Onshape.com:443/x"), "cad.onshape.com")
        self.assertEqual(host_of(""), "")

    def test_is_onshape_reads_the_address_bar_once_per_title(self):
        from control_center import onshape as O
        calls = []
        w = O.OnshapeWindows.__new__(O.OnshapeWindows)
        w._exes = {}
        w.exe = lambda pid: "chrome.exe"
        w.pid = lambda hwnd: 7
        titles = {1: "scarlett solo | Focusrite Scarlett"}

        class U:
            @staticmethod
            def GetWindowTextW(hwnd, buffer, size):
                buffer.value = titles[hwnd]
        w.u = U()
        w.address_host = lambda hwnd: calls.append(hwnd) or "cad.onshape.com"
        self.assertTrue(w.is_onshape(1))
        self.assertTrue(w.is_onshape(1))
        self.assertEqual(calls, [1], "cached for the same window and title")
        titles[1] = "Inbox - Gmail"
        w.address_host = lambda hwnd: calls.append(hwnd) or "mail.google.com"
        self.assertFalse(w.is_onshape(1))
        w.exe = lambda pid: "notepad.exe"
        self.assertFalse(w.is_onshape(1))




class HapticRangeTests(unittest.TestCase):
    def test_the_onshape_range_fits_the_knobs_uint16_position_count(self):
        """2026-09-30: haptic.cpp counts end - start + 1 in a uint16; 0..65535 wrapped to 0 and turned on its
        derivative term (the Onshape-only buzz). Every mode's control range must stay below 65535 positions."""
        from control_center.controller import ONSHAPE_BOUNDS
        low, high, centre = ONSHAPE_BOUNDS
        self.assertLess(high - low + 1, 65536)
        self.assertTrue(low < centre < high)


if __name__ == "__main__":
    unittest.main()
