"""DD-SEC-001: Onshape keystrokes need the keyboard focus inside the page under the cursor, not only the cursor
over the model (the address bar, the find bar or docked DevTools could hold the focus). Headless: a recording fake
backend and a fake UI Automation tree; never SendInput, never COM."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cc5_support import Clock  # noqa: E402
from test_onshape import FakeBackend  # noqa: E402

from control_center import browser_url, onshape  # noqa: E402
from control_center.onshape import OnshapeInjector, chord_events  # noqa: E402

HOME, ORBIT, WHEEL, PAN = 0, 1, 2, 3


class FocusBackend(FakeBackend):
    def __init__(self, focus=True, **kwargs):
        super().__init__(**kwargs)
        self.focus = focus
        self.focus_points = []

    def focus_ok(self, point):
        self.focus_points.append(point)
        return self.focus


class InjectorFocusTests(unittest.TestCase):
    CONTROL = 9

    def make(self, app=True, **kwargs):
        self.clock = Clock(100.0)
        self.backend = FocusBackend(**kwargs)
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

    def keyed(self):
        return [e for e in self.backend.events() if e[0] in ("key", "char")]

    def test_keyboard_actions_refused_when_focus_outside_page(self):
        self.make(focus=False)
        self.kd(WHEEL)                                       # tap 3: Undo
        self.clock.advance(0.1)
        self.ku(WHEEL)
        self.assertEqual(self.inj.take_events(), ["focus_refused"])
        self.clock.advance(1.0)                              # a new burst: one refusal again
        self.kd(WHEEL)
        self.post("position", delta=1)
        self.post("position", delta=40)                      # CHAMFER: Alt+C, "chamfer", Enter
        self.ku(WHEEL)
        self.clock.advance(1.0)
        self.inj.step()
        self.assertEqual(self.keyed(), [], "no Ctrl+Z, no Alt+C, no phrase, no Enter")
        self.assertNotIn("param", self.inj.app_state())
        status = self.inj.status()
        self.assertEqual(status["undo"], 0)
        self.assertGreaterEqual(status["refusals"], 2)
        self.assertGreaterEqual(status["focusRefused"], 2)
        self.backend.batches.clear()
        self.post("position", delta=5)                       # a zoom detent is mouse only: still sent
        self.assertTrue(any(e[0] == "wheel" for e in self.backend.events()))

    def test_b_mode_ok_sends_nothing_when_focus_leaves_the_page(self):
        self.make()
        self.inj.app.typed = True
        self.kd(WHEEL)
        self.post("position", delta=1)
        self.post("position", delta=10)                      # EXTRUDE, B: the value is typed
        self.ku(WHEEL)
        self.backend.batches.clear()
        self.post("position", delta=16)                      # +0.2
        self.backend.focus = False                           # the user clicked the address bar
        self.kd(WHEEL)
        self.ku(WHEEL)                                       # OK: Ctrl+A, "25.20", Enter would go to the omnibox
        self.clock.advance(1.0)
        self.inj.step()
        self.assertEqual(self.keyed(), [])
        self.assertIn("param", self.inj.app_state(), "the dialog is still open: OK can be tried again")

    def test_a_modifier_scroll_needs_the_focus_a_plain_scroll_does_not(self):
        self.make()
        self.kd(WHEEL)
        self.post("position", delta=1)
        self.post("position", delta=10)                      # EXTRUDE, A
        self.ku(WHEEL)
        self.backend.focus = False
        self.backend.batches.clear()
        self.post("position", delta=8)                       # 0.1 step: a plain notch over the field
        self.assertEqual(self.backend.events(), [("wheel", 120)])
        self.backend.batches.clear()
        self.kd(HOME)                                        # 0.01: Ctrl + notch
        self.post("position", delta=3)
        self.assertEqual(self.backend.events(), [])

    def test_with_focus_in_the_page_everything_goes_out(self):
        self.make(app=False)
        self.kd(WHEEL)
        self.ku(WHEEL)
        self.assertEqual(self.backend.events(), chord_events(("ctrl",), "Z"))
        self.assertEqual(self.backend.focus_points, [self.backend.cursor_pos])

    def test_the_null_backend_refuses_keyboard_focus(self):
        self.assertFalse(onshape.NullBackend().focus_ok((0, 0)))


class FakeTree:
    """Elements are names; parents form the UI Automation control view."""

    def __init__(self, parents, documents, at, focused):
        self.parents, self.documents, self._at, self._focused = parents, documents, at, focused
        self.released = []

    def at(self, point):
        return self._at

    def focused(self):
        return self._focused

    def parent(self, element):
        return self.parents.get(element)

    def is_document(self, element):
        return element in self.documents

    def same(self, first, second):
        return first == second

    def release(self, element):
        self.released.append(element)


PARENTS = {"canvas": "frame-doc", "frame-doc": "page-doc", "page-doc": "content", "content": "browser",
           "dialog-field": "page-doc", "omnibox": "toolbar", "toolbar": "browser", "browser": "desktop",
           "devtools-input": "devtools-doc", "devtools-doc": "content"}
DOCUMENTS = {"frame-doc", "page-doc", "devtools-doc"}


class PageFocusTests(unittest.TestCase):
    def check(self, focused, at="canvas"):
        tree = FakeTree(PARENTS, DOCUMENTS, at, focused)
        answer = browser_url.page_holds_focus(tree, (1, 1))
        self.assertTrue(tree.released, "every element is released")
        return answer

    def test_focus_in_the_page_or_its_frames_is_accepted(self):
        self.assertTrue(self.check("dialog-field"))
        self.assertTrue(self.check("canvas"))
        self.assertTrue(self.check("page-doc"))

    def test_the_address_bar_and_docked_devtools_are_refused(self):
        self.assertFalse(self.check("omnibox"))
        self.assertFalse(self.check("devtools-input"))

    def test_unknown_answers_none(self):
        self.assertIsNone(self.check(None))
        self.assertIsNone(self.check("dialog-field", at="toolbar"))

    def test_windows_keyboard_ok_keeps_the_cursor_gate_alone_when_uia_cannot_tell(self):
        windows = object.__new__(onshape.OnshapeWindows)
        answers = iter([None, False, True])
        windows.focus_in_page = lambda point: next(answers)
        self.assertTrue(windows.keyboard_ok((1, 1)))
        windows._key_focus = None
        self.assertFalse(windows.keyboard_ok((1, 1)))
        self.assertFalse(windows.keyboard_ok((1, 1)), "cached within the burst")
        windows._key_focus = None
        self.assertTrue(windows.keyboard_ok((1, 1)))


if __name__ == "__main__":
    unittest.main()
