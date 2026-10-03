"""The owner's S3 decisions on app profiles, each class one decision, proven here first. Fakes only: a recording
backend (never SendInput), temporary folders, no network, no window."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_app_engine import Backend, EngineCase, chord_keys  # noqa: E402

from control_center import app_detect as D, app_engine as E, onshape  # noqa: E402
from control_center.app_profiles import Detect, MacroStep  # noqa: E402
from control_center.keymap import parse_chord  # noqa: E402

CONTROL = 5
F1, F2, F3, F4 = 0, 1, 2, 3


# ================================================================================================ decision 3
class FreshBackend(Backend):
    """Backend plus the fresh keyboard-focus check: each call's time is kept; ``fresh`` is its answer (the cached
    ``focus`` answer stays True, as a 0.25 s cache would)."""

    def __init__(self, clock, layout=None):
        super().__init__(clock, layout)
        self.fresh = True
        self.fresh_calls = []

    def focus_fresh(self, point):
        self.fresh_calls.append(self.clock())
        return self.fresh


class RecheckCase(EngineCase):
    """Figma (website rules: a browser app) with a macro command: ``chord, wait <ms>, text, Enter``."""
    PROFILE = "figma"
    WAIT_MS = 150
    DETECT = None

    def setUp(self):
        super().setUp()
        self.backend = FreshBackend(self.clock)
        self.inj = E.AppInjector(self.backend, clock=self.clock, start=False, profile=self.profile)
        p = self.profile
        macros = {"SAVE_AS": (MacroStep("key", parse_chord("ctrl+shift+s"), None, 0),
                              MacroStep("wait", None, None, self.WAIT_MS),
                              MacroStep("text", None, "draft 2", 0), MacroStep("key", parse_chord("enter"), None, 0))}
        ring = p.rings[0]
        cmds = (replace(ring.commands[0], kind="macro", chord=None, macro="SAVE_AS"), *ring.commands[1:])
        self.profile = replace(p, macros=macros, rings=(replace(ring, commands=cmds),) + p.rings[1:])
        if self.DETECT is not None:
            self.profile = replace(self.profile, detect=self.DETECT)
        self.inj.activate(CONTROL, [0, 1, 2, 3], self.DETENTS, app=True, profile=self.profile)
        self.inj.step()

    def run_macro(self):
        self.kd(F3)
        self.ku(F3)                              # STRUCTURE 1: the macro
        self.wait(0.4)


class BrowserRecheckTests(RecheckCase):
    def test_typed_text_after_a_chord_waits_for_a_fresh_focus_check(self):
        self.run_macro()
        self.assertEqual(self.backend.text(), "draft 2")
        self.assertEqual(len(self.backend.fresh_calls), 1, "one fresh check, right before the text")
        chord_at, text_at = self.backend.batches[0][0], self.backend.batches[1][0]
        self.assertLessEqual(self.backend.fresh_calls[0], text_at)
        self.assertGreaterEqual(self.backend.fresh_calls[0] - chord_at, E.TEXT_SETTLE_S - 1e-9)
        self.assertLess(abs(text_at - chord_at - 0.15), 0.015, "a longer wait of the macro's own is kept as it is")
        self.assertEqual(E.TEXT_SETTLE_S, 0.06)

    def test_a_failed_fresh_check_refuses_sends_nothing_more_and_releases(self):
        self.backend.fresh = False
        released = []
        release = self.inj._release_everything
        self.inj._release_everything = lambda reason: (released.append(reason), release(reason))
        self.run_macro()
        self.assertEqual(self.backend.keys(), chord_keys("ctrl+shift+s"), "the chord went; no text, no Enter")
        self.assertEqual(self.backend.text(), "")
        self.assertEqual(self.inj.take_events(), [E.FOCUS_REFUSED], "the existing 'Click the app first' refusal")
        self.assertEqual(released, ["focus_recheck"])
        self.assertEqual(self.inj.app_status()["focusRecheckRefused"], 1)
        self.assertEqual(self.inj._macro, [], "the rest of the command is dropped")

    def test_the_search_phrase_is_rechecked_and_keeps_its_open_wait(self):
        self.kd(F3)
        self.kd(F2)
        self.ku(F2)                              # COMPONENTS
        self.turn(1, 4 * 2)                      # GO TO MAIN (a search command)
        self.ku(F3)
        self.wait(0.8)
        self.assertEqual(self.backend.text(), "go to main component")
        self.assertEqual(len(self.backend.fresh_calls), 1)
        times = [t for t, _ in self.backend.batches]
        self.assertLess(abs(times[1] - times[0] - 0.25), 0.015, "the open wait is longer than the settle: unchanged")

    def test_a_chord_without_text_needs_no_fresh_check(self):
        self.tap(F1)
        self.assertTrue(self.backend.events())
        self.assertEqual(self.backend.fresh_calls, [])


class ShortWaitBrowserTests(RecheckCase):
    WAIT_MS = 20

    def test_a_short_wait_is_stretched_to_the_settle(self):
        self.run_macro()
        self.assertEqual(self.backend.text(), "draft 2")
        chord_at, text_at = self.backend.batches[0][0], self.backend.batches[1][0]
        self.assertGreaterEqual(text_at - chord_at, E.TEXT_SETTLE_S - 1e-9)
        self.assertLess(text_at - chord_at, E.TEXT_SETTLE_S + 0.015)

    def test_text_with_no_wait_after_the_chord_settles_too(self):
        self.assertEqual(E.with_text_rechecks([("chord", 1), ("text", "a")], settle=True),
                         [("chord", 1), ("wait", E.TEXT_SETTLE_S), ("recheck",), ("text", "a")])
        self.assertEqual(E.with_text_rechecks([("chord", 1), ("wait", 0.02), ("text", "a"), ("text", "b")],
                                              settle=True),
                         [("chord", 1), ("wait", 0.06), ("recheck",), ("text", "a"), ("recheck",), ("text", "b")])
        self.assertEqual(E.with_text_rechecks([("text", "a"), ("chord", 1)], settle=True),
                         [("text", "a"), ("chord", 1)], "text before any chord: the normal gates only")


class DesktopRecheckTests(RecheckCase):
    """A desktop app (no website rules): no settle, but the fresh process check still runs before the text."""
    WAIT_MS = 20
    DETECT = Detect(exe=("Figma.exe",))

    def test_no_settle_but_a_fresh_check(self):
        self.run_macro()
        self.assertEqual(self.backend.text(), "draft 2")
        chord_at, text_at = self.backend.batches[0][0], self.backend.batches[1][0]
        self.assertLess(abs(text_at - chord_at - 0.02), 0.015)
        self.assertEqual(len(self.backend.fresh_calls), 1)


class ParamDigitsRecheckTests(EngineCase):
    """Parameter digits (Plasticity's numeric entry on OK) get the fresh check and keep their tuned 50 ms wait."""
    PROFILE = "plasticity"

    def setUp(self):
        super().setUp()
        self.backend = FreshBackend(self.clock)
        self.inj = E.AppInjector(self.backend, clock=self.clock, start=False, profile=self.profile)
        self.inj.activate(CONTROL, [0, 1, 2, 3], self.DETENTS, app=True)
        self.inj.step()
        self.kd(F3)
        self.wait(0.3)
        self.ku(F3)                              # SOLID / EXTRUDE: E, then its enter key D
        self.kd(F4)
        self.turn(1, 6)                          # two exact 1.0 steps
        self.ku(F4)
        self.backend.batches.clear()

    def test_the_digits_are_rechecked(self):
        self.tap(F3)                             # OK: Tab, 50 ms, the digits, Enter
        self.wait(0.2)
        self.assertEqual(self.backend.text(), "2.00")
        self.assertEqual(len(self.backend.fresh_calls), 1)
        tab_at, digits_at = self.backend.batches[0][0], self.backend.batches[1][0]
        self.assertLess(abs(digits_at - tab_at - E.PARAM_NUMERIC_WAIT_S), 0.015)

    def test_a_failed_check_types_no_digits_and_no_enter(self):
        self.backend.fresh = False
        self.tap(F3)
        self.wait(0.2)
        self.assertEqual(self.backend.keys(), chord_keys("tab"))
        self.assertEqual(self.backend.text(), "")
        self.assertEqual(self.inj.take_events(), [E.FOCUS_REFUSED])


class FreshWindowsCheckTests(unittest.TestCase):
    def test_the_browser_check_bypasses_the_cache_and_needs_the_document_focus(self):
        windows = object.__new__(onshape.OnshapeWindows)
        answers = []
        windows.focus_in_page = lambda point: answers.pop(0)
        answers[:] = [True]
        self.assertTrue(windows.keyboard_ok((1, 1)))         # cached True for 0.25 s
        answers[:] = [False]
        self.assertFalse(windows.keyboard_ok_fresh((1, 1)), "the address bar has it now: the cache is bypassed")
        self.assertFalse(windows.keyboard_ok((1, 1)), "and the fresh answer refreshes the cache")
        windows._key_focus = None
        answers[:] = [None]
        self.assertFalse(windows.keyboard_ok_fresh((1, 1)), "can't tell is not the page's document focus")

    def test_the_desktop_check_is_the_focus_windows_process(self):
        windows = D.AppWindows.__new__(D.AppWindows)
        windows.profile = _blender()
        windows.foreground = lambda: 0x200
        windows.pid = lambda hwnd: 8
        windows.exe = lambda pid: "blender.exe"
        windows.focus_pid = lambda: 8
        self.assertTrue(windows.keyboard_ok_fresh((1, 1)))
        windows.focus_pid = lambda: 9
        self.assertFalse(windows.keyboard_ok_fresh((1, 1)))

    def test_the_win32_backend_asks_the_fresh_check(self):
        backend = onshape.Win32Backend.__new__(onshape.Win32Backend)
        seen = []
        backend.windows = type("W", (), {"keyboard_ok_fresh": lambda self, point: seen.append(point) or True})()
        self.assertTrue(backend.focus_fresh((3, 4)))
        self.assertEqual(seen, [(3, 4)])
        backend.windows = object()
        self.assertFalse(backend.focus_fresh((3, 4)), "a windows object without the check fails closed")

    def test_the_null_backend_refuses(self):
        self.assertFalse(E.NullBackend().focus_fresh((0, 0)))


def _blender():
    from test_app_engine import bundled
    return bundled("blender")


if __name__ == "__main__":
    unittest.main()
