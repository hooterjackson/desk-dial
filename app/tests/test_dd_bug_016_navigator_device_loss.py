"""DD-BUG-016: the Navigator handles a lost D3D device as the stage engine does: it releases the
scene and the device, logs the removed reason once and recreates (at most twice, 1 s apart); a dead
warm device is never reused. Headless: the fake device, host and clock; no window, no GPU."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import navigator_model as NM  # noqa: E402
from control_center.stage import com  # noqa: E402
from control_center.stage.device import COLD, WARM  # noqa: E402
from control_center.stage.scenes import navigator_render as R  # noqa: E402

STATES = {name: (snap, pressed) for name, snap, pressed in R.design_states()}


def content(name):
    snap, pressed = STATES[name]
    return NM.build_content(snap, pressed=pressed)


def rig_with_log():
    rig = R.HeadlessNavigator(R.desktop_image())
    rig.logs = []
    rig.engine.log = rig.logs.append
    return rig


class EngineLifecycle(unittest.TestCase):
    def test_lost_device_is_released_and_recreated(self):
        rig = rig_with_log()
        rig.post(content("home"))
        rig.advance(500)
        first = rig.dev
        first.fail_next("Commit", com.DXGI_ERROR_DEVICE_REMOVED)
        rig.post(content("music"))                         # the update's Commit: DEVICE_REMOVED
        self.assertEqual(first.alive(), 0, "the dead device is released, every object")
        self.assertEqual(rig.engine.counters["device_lost"], 1)
        self.assertEqual(len([m for m in rig.logs if "GetDeviceRemovedReason" in m]), 1)
        self.assertEqual(len(rig.devices), 2, "the wanted card recreates a new device at once")
        self.assertIsNot(rig.engine.device, first)
        self.assertEqual(rig.engine.policy.state, WARM)
        self.assertTrue(rig.engine.shown)
        rig.advance(500)
        rig.post(content("home"))
        self.assertIs(rig.engine.device, rig.devices[-1])
        self.assertEqual(rig.dev.violations, [])

    def test_dead_warm_device_is_not_reused_at_the_next_show(self):
        rig = rig_with_log()
        rig.post(content("home"))
        rig.advance(500)
        rig.post(content("home"), visible=False)
        rig.advance(1000)
        first = rig.dev
        first.fail_next("CheckDeviceState", com.DXGI_ERROR_DEVICE_REMOVED)   # a TDR while hidden
        rig.post(content("music"))
        self.assertEqual(len(rig.devices), 2)
        self.assertIs(rig.engine.device, rig.devices[-1])
        self.assertEqual(first.alive(), 0)
        self.assertTrue(rig.engine.shown)

    def test_loss_in_warm_up_is_capped_and_does_not_spin(self):
        rig = rig_with_log()
        make = rig.engine.device_factory

        def factory(mon):
            dev = make(mon)
            dev.fail_next("GetFrameStatistics", com.DXGI_ERROR_DEVICE_REMOVED)
            return dev
        rig.engine.device_factory = factory
        rig.post(content("home"))
        waits = []
        for _ in range(40):
            waits.append(rig.engine.process())
            rig.clk.advance(0.25)
        self.assertLessEqual(rig.engine.counters["device_creates"], 3)
        self.assertIsNone(rig.engine.device)
        self.assertEqual(rig.engine.policy.state, COLD)
        self.assertNotIn(0.0, waits[1:])
        self.assertEqual(len([m for m in rig.logs if "GetDeviceRemovedReason" in m]), 1)

    def test_loss_while_hidden_does_not_wake_the_thread(self):
        rig = rig_with_log()
        rig.post(content("home"))
        rig.advance(500)
        rig.dev.fail_next("Commit", com.DXGI_ERROR_DEVICE_REMOVED)
        rig.post(content("home"), visible=False)           # the hide's Commit fails
        self.assertIsNone(rig.engine.device)
        wake = rig.engine.process()
        self.assertTrue(wake is None or wake > 0.5, wake)
        rig.post(content("music"))                         # the next show creates a device
        self.assertTrue(rig.engine.shown)
        self.assertEqual(len(rig.devices), 2)


if __name__ == "__main__":
    unittest.main()
