"""DD-BUG-036: while the display is off / asleep or the session is locked the Navigator stays hidden
whatever state Tk posts (a pinned card's status line changes every second), and takes no backdrop
captures. Each cause clears only on its own end (unlock only on WTS_SESSION_UNLOCK, a session
connect only ends a disconnect, a user-attended resume only ends a suspend, display on ends the
display-off and the suspend); a pinned card comes back when none is left. Headless: the fake device, host,
clock and a synchronous capture; no window, no GPU."""
import dataclasses
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import navigator_model as NM  # noqa: E402
from control_center.stage import host as HO  # noqa: E402
from control_center.stage.scenes import navigator_engine as N  # noqa: E402
from control_center.stage.scenes import navigator_render as R  # noqa: E402

STATES = {name: (snap, pressed) for name, snap, pressed in R.design_states()}


def content(name, **changes):
    snap, pressed = STATES[name]
    c = NM.build_content(snap, pressed=pressed)
    return dataclasses.replace(c, **changes) if changes else c


def pinned_rig():
    rig = R.HeadlessNavigator(R.desktop_image())
    rig.post(content("music"))
    rig.advance(600)
    assert rig.engine.shown and rig.engine.scene.visible
    return rig


def notice(rig, kind):
    rig.engine._notice(kind)
    rig.engine.process()


def changing_states(rig, n):
    base = content("music")
    for i in range(n):
        rig.post(dataclasses.replace(base, title=f"{base.title} {i}"))     # changes every second
        rig.advance(1000)


class EngineLifecycle(unittest.TestCase):
    def test_display_off_suppresses_until_display_on(self):
        rig = pinned_rig()
        notice(rig, "display_off")
        notice(rig, "sleep")
        self.assertFalse(rig.engine.shown)
        captures = rig.engine.counters["captures"]
        shows = rig.engine.counters["shows"]
        changing_states(rig, 60)
        self.assertFalse(rig.engine.shown, "the card stays hidden while the display is off")
        self.assertFalse(rig.engine.scene is not None and rig.engine.scene.visible)
        self.assertEqual(rig.engine.counters["captures"], captures, "no backdrop capture while dark")
        self.assertEqual(rig.engine.counters["shows"], shows)
        self.assertTrue(rig.engine.metrics()["suppressed"])
        rig.engine.post_touch()
        rig.engine.process()
        self.assertFalse(rig.engine.shown, "a touch does not show it either")
        notice(rig, "display_on")
        rig.advance(600)
        self.assertTrue(rig.engine.shown, "display on re-shows the pinned card without a content change")
        self.assertTrue(rig.engine.scene.visible)
        self.assertFalse(rig.engine.metrics()["suppressed"])
        self.assertEqual(rig.dev.violations, [])

    def test_lock_suppresses_until_unlock_even_if_the_display_wakes(self):
        rig = pinned_rig()
        rig.engine.input.handle(HO.WM_WTSSESSION_CHANGE, HO.WTS_SESSION_LOCK, 0)
        rig.engine.process()
        self.assertFalse(rig.engine.shown)
        notice(rig, "display_off")
        notice(rig, "display_on")                 # the lock screen lights the display
        changing_states(rig, 5)
        self.assertFalse(rig.engine.shown, "still locked")
        rig.engine.input.handle(HO.WM_WTSSESSION_CHANGE, HO.WTS_SESSION_UNLOCK, 0)
        rig.engine.process()
        rig.advance(600)
        self.assertTrue(rig.engine.shown, "unlock re-shows the pinned card")

    def test_attended_resume_after_suspend_shows_again(self):
        rig = pinned_rig()
        rig.engine.input.handle(HO.WM_POWERBROADCAST, HO.PBT_APMSUSPEND, 0)
        rig.engine.process()
        changing_states(rig, 3)
        self.assertFalse(rig.engine.shown)
        rig.engine.input.handle(HO.WM_POWERBROADCAST, HO.PBT_APMRESUMEAUTOMATIC, 0)
        rig.engine.process()
        changing_states(rig, 3)
        self.assertFalse(rig.engine.shown, "an automatic (possibly unattended) resume shows nothing")
        rig.engine.input.handle(HO.WM_POWERBROADCAST, HO.PBT_APMRESUMESUSPEND, 0)
        rig.engine.process()
        rig.advance(600)
        self.assertTrue(rig.engine.shown)

    def test_resume_with_the_display_still_off_stays_hidden(self):
        rig = pinned_rig()
        rig.engine.input.power_setting = lambda lp: (True, lp)          # lp 0 off, 1 on
        rig.engine.input.handle(HO.WM_POWERBROADCAST, HO.PBT_POWERSETTINGCHANGE, 0)   # display_off + sleep
        rig.engine.input.handle(HO.WM_POWERBROADCAST, HO.PBT_APMSUSPEND, 0)
        rig.engine.process()
        captures = rig.engine.counters["captures"]
        notice(rig, "resume")                      # even a resume notice: the display is still off
        rig.engine.input.handle(HO.WM_POWERBROADCAST, HO.PBT_APMRESUMEAUTOMATIC, 0)
        rig.engine.process()
        changing_states(rig, 10)
        self.assertFalse(rig.engine.shown, "the display is still off")
        self.assertEqual(rig.engine.counters["captures"], captures, "no frost capture with the display off")
        rig.engine.input.handle(HO.WM_POWERBROADCAST, HO.PBT_POWERSETTINGCHANGE, 1)   # display_on
        rig.engine.process()
        rig.advance(600)
        self.assertTrue(rig.engine.shown, "display on brings the pinned card back")

    def test_console_connect_on_the_lock_screen_stays_hidden(self):
        rig = pinned_rig()
        h = rig.engine.input.handle
        h(HO.WM_WTSSESSION_CHANGE, HO.WTS_SESSION_LOCK, 0)
        h(HO.WM_WTSSESSION_CHANGE, HO.WTS_CONSOLE_DISCONNECT, 0)        # fast user switching away
        rig.engine.process()
        h(HO.WM_WTSSESSION_CHANGE, HO.WTS_CONSOLE_CONNECT, 0)           # back, still on the lock screen
        rig.engine.process()
        captures = rig.engine.counters["captures"]
        changing_states(rig, 5)
        self.assertFalse(rig.engine.shown, "a connect is not an unlock")
        self.assertEqual(rig.engine.counters["captures"], captures)
        h(HO.WM_WTSSESSION_CHANGE, HO.WTS_REMOTE_CONNECT, 0)
        rig.engine.process()
        rig.advance(600)
        self.assertFalse(rig.engine.shown)
        h(HO.WM_WTSSESSION_CHANGE, HO.WTS_SESSION_UNLOCK, 0)
        rig.engine.process()
        rig.advance(600)
        self.assertTrue(rig.engine.shown, "unlock re-shows the pinned card")

    def test_disconnect_without_lock_ends_on_connect(self):
        rig = pinned_rig()
        h = rig.engine.input.handle
        h(HO.WM_WTSSESSION_CHANGE, HO.WTS_REMOTE_DISCONNECT, 0)
        rig.engine.process()
        changing_states(rig, 3)
        self.assertFalse(rig.engine.shown)
        h(HO.WM_WTSSESSION_CHANGE, HO.WTS_REMOTE_CONNECT, 0)
        rig.engine.process()
        rig.advance(600)
        self.assertTrue(rig.engine.shown)

    def test_hidden_card_stays_hidden_after_display_on(self):
        rig = pinned_rig()
        rig.post(content("music"), visible=False)
        rig.advance(800)
        notice(rig, "display_off")
        notice(rig, "display_on")
        rig.advance(600)
        self.assertFalse(rig.engine.shown, "only a wanted card comes back")

    def test_host_input_reports_unlock_and_resume(self):
        seen = []
        h = HO.HostInput(HO.ROLE_CLICK_THROUGH, seen.append)
        h.handle(HO.WM_WTSSESSION_CHANGE, HO.WTS_SESSION_UNLOCK, 0)
        h.handle(HO.WM_WTSSESSION_CHANGE, HO.WTS_CONSOLE_CONNECT, 0)
        h.handle(HO.WM_WTSSESSION_CHANGE, HO.WTS_REMOTE_CONNECT, 0)
        h.handle(HO.WM_WTSSESSION_CHANGE, HO.WTS_CONSOLE_DISCONNECT, 0)
        h.handle(HO.WM_POWERBROADCAST, HO.PBT_APMRESUMEAUTOMATIC, 0)
        h.handle(HO.WM_POWERBROADCAST, HO.PBT_APMRESUMESUSPEND, 0)
        self.assertEqual(seen, ["unlock", "session_connect", "session_connect", "session_disconnect",
                                "resume"])
        self.assertTrue(N.FROST_REFRESH_S > 0)

    def test_stage_engine_still_reports_a_session_disconnect_as_lock(self):
        import test_stage_engine as TSE
        r = TSE.Rig()
        h = r.host.input.handle
        h(HO.WM_WTSSESSION_CHANGE, HO.WTS_CONSOLE_DISCONNECT, 0)
        h(HO.WM_WTSSESSION_CHANGE, HO.WTS_REMOTE_DISCONNECT, 0)
        h(HO.WM_WTSSESSION_CHANGE, HO.WTS_CONSOLE_CONNECT, 0)
        h(HO.WM_WTSSESSION_CHANGE, HO.WTS_SESSION_UNLOCK, 0)
        r.run()
        self.assertEqual(r.events(), [("system", {"kind": "lock"}), ("system", {"kind": "lock"})])


if __name__ == "__main__":
    unittest.main()
