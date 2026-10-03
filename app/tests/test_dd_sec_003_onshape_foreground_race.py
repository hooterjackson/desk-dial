"""DD-SEC-003: a foreground change during the target check or mid-drag never lets input land in the new window.
Headless: a recording fake backend and a fake user32; never SendInput."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cc5_support import Clock  # noqa: E402
from test_onshape import FakeBackend  # noqa: E402

from control_center import onshape  # noqa: E402
from control_center.onshape import OnshapeInjector  # noqa: E402

ORBIT = 1


class ForegroundBackend(FakeBackend):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.front = 100

    def foreground(self):
        return self.front


class DragForegroundTests(unittest.TestCase):
    CONTROL = 7

    def make(self):
        self.clock = Clock(100.0)
        self.backend = ForegroundBackend()
        self.inj = OnshapeInjector(self.backend, clock=self.clock, start=False)
        self.inj.activate(self.CONTROL, [0, 1, 2, 3], 127)
        self.inj.step()
        return self.inj

    def post(self, kind, **values):
        self.inj.post(kind, {"id": self.CONTROL, **values})
        self.inj.step()

    def test_drag_ends_when_foreground_changes_mid_drag(self):
        self.make()
        self.post("button", button=ORBIT)
        self.post("position", delta=1)                       # the drag starts: right button down, one move
        self.assertEqual(self.backend.batches[0][0], ("down", "right"))
        origin = (500, 400)
        sent_before = len(self.backend.batches)
        self.backend.front = 555                             # another app takes the foreground
        self.clock.advance(0.01)
        self.post("position", delta=1)
        later = [e for b in self.backend.batches[sent_before:] for e in b]
        self.assertEqual(later, [("up", "right"), ("move",) + origin], "button up, cursor home, no relative move")
        self.assertEqual(self.inj.status()["releases"].get("foreground"), 1)
        self.assertFalse(self.inj.status()["dragging"])

    def test_a_steady_foreground_keeps_dragging(self):
        self.make()
        self.post("button", button=ORBIT)
        self.post("position", delta=1)
        self.clock.advance(0.01)
        self.post("position", delta=1)
        self.assertTrue(self.inj.status()["dragging"])
        self.assertEqual(self.inj.status()["releases"].get("foreground"), None)

    def test_a_backend_without_foreground_is_unchanged(self):
        self.clock = Clock(100.0)
        self.backend = FakeBackend()
        self.inj = OnshapeInjector(self.backend, clock=self.clock, start=False)
        self.inj.activate(self.CONTROL, [0, 1, 2, 3], 127)
        self.inj.step()
        self.post("button", button=ORBIT)
        self.post("position", delta=1)
        self.post("position", delta=1)
        self.assertTrue(self.inj.status()["dragging"])


class TargetForegroundTests(unittest.TestCase):
    def make(self, foregrounds):
        windows = object.__new__(onshape.OnshapeWindows)
        user = Mock()
        user.WindowFromPoint.side_effect = lambda point: 200
        user.GetAncestor.side_effect = lambda hwnd, flag: 100
        user.GetForegroundWindow.side_effect = list(foregrounds)
        windows.u, windows.k, windows._exes = user, None, {}
        windows.classes = onshape.CONTENT_CLASSES
        windows.class_name = lambda hwnd: "Chrome_RenderWidgetHostHWND"
        windows.is_onshape = lambda hwnd: hwnd == 100
        return windows

    def test_a_foreground_change_during_the_onshape_lookup_is_refused(self):
        with patch.object(onshape, "W", Mock()):
            self.assertFalse(self.make([100, 555]).target_ok((1, 1)))
            self.assertTrue(self.make([100, 100]).target_ok((1, 1)))


if __name__ == "__main__":
    unittest.main()
