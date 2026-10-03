"""DD-BUG-018: tray "Show knob" with an r3 knob shows the Navigator (the floating knob is then held
with the reason 'navigator' and ignores a peek), and it reports False when nothing can show, so the
tray never does a silent no-op. Headless: a real controller and Navigator, a recording backend, the
app method called on a stand-in object; no Tk, no ports."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r3_support import R3Fixture  # noqa: E402
from test_r3_navigator_model import Backend, Runtime  # noqa: E402
from control_center import ui  # noqa: E402
from control_center.navigator import Navigator  # noqa: E402


class SuppressedOverlay:
    """The KnobOverlay peek contract: False while a suppression reason holds."""
    def __init__(self, reasons=()):
        self.reasons = set(reasons)
        self.peeks = []
        self.state = "hidden"

    def peek(self, seconds=2.5):
        self.peeks.append(seconds)
        return not self.reasons


def app_for(nav, overlay, runtime):
    app = SimpleNamespace(navigator=nav, overlay=overlay, runtime=runtime, failure_counts={})
    app._log_failure = lambda key, message: None
    app.peek = lambda seconds=2.5: ui.ControlCenterApp.peek(app, seconds)
    app.peek_available = lambda: ui.ControlCenterApp.peek_available(app)
    return app


class ShowKnobTests(R3Fixture):
    def setUp(self):
        super().setUp()
        self.t = [100.0]
        self.backend = Backend()
        self.nav = Navigator(self.backend, clock=lambda: self.t[0])
        self.rt = Runtime(self.c)
        self.overlay = SuppressedOverlay({"navigator"})
        self.app = app_for(self.nav, self.overlay, self.rt)

    def tick(self, dt=0.0):
        self.t[0] += dt
        return self.nav.update(self.rt, self.c.frame())

    def test_show_knob_with_r3_knob_shows_navigator(self):
        self.nav.set_mode("auto")
        self.rt.touch_seq += 1
        self.assertTrue(self.tick())
        self.tick(30.0)                                   # well past every auto-hide
        self.assertFalse(self.backend.posts[-1]["visible"], "auto-hidden before the tray click")
        self.assertTrue(self.app.peek_available())
        self.assertTrue(self.app.peek(2.5))
        self.assertEqual(self.overlay.peeks, [], "the held floating knob is not asked")
        self.assertTrue(self.tick(0.016))
        self.assertTrue(self.backend.posts[-1]["visible"], "visible within one tick")

    def test_navigator_off_peeks_the_floating_knob(self):
        self.nav.set_mode("off")
        self.assertFalse(self.tick())
        self.overlay.reasons.clear()                      # ui releases 'navigator' on hand-back
        self.assertTrue(self.app.peek_available())
        self.assertTrue(self.app.peek(2.5))
        self.assertEqual(self.overlay.peeks, [2.5])

    def test_disconnected_knob_reports_nothing_to_show(self):
        self.nav.set_mode("auto")
        self.tick()
        self.rt.device_connected = False
        self.tick(0.1)
        self.assertFalse(self.app.peek_available(), "the tray disables Show knob")
        self.assertFalse(self.app.peek(2.5))

    def test_no_navigator_disconnected_overlay_peek_is_false(self):
        overlay = SuppressedOverlay({"disconnected"})
        runtime = SimpleNamespace(device_connected=False)
        app = app_for(None, overlay, runtime)
        self.assertFalse(app.peek_available())
        self.assertFalse(app.peek(2.5))
        overlay.reasons.clear()
        runtime.device_connected = True
        self.assertTrue(app.peek_available())
        self.assertTrue(app.peek(2.5))

    def test_disabled_overlay_cannot_peek(self):
        overlay = SuppressedOverlay()
        overlay.state = "disabled"
        app = app_for(None, overlay, SimpleNamespace(device_connected=True))
        self.assertFalse(app.peek_available())
        self.assertFalse(app.peek(2.5))
        self.assertEqual(overlay.peeks, [])


if __name__ == "__main__":
    unittest.main()
