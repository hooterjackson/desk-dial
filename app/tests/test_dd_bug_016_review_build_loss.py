"""DD-BUG-016 (review): a device that warms up fine but is lost while the Navigator builds or first
shows its scene (CreateVisual, the show Commit) counts as a failed creation attempt: at most three
creates, policy COLD, no zero-second wake, the removed reason logged once, every dead device
released. The next open of the card (after a hide) may try again. Headless: fake device, host and
clock; no window, no GPU."""
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


def broken_rig(op):
    """Every new device fails ``op`` once with DXGI_ERROR_DEVICE_REMOVED."""
    rig = R.HeadlessNavigator(R.desktop_image())
    rig.logs = []
    rig.engine.log = rig.logs.append
    make = rig.engine.device_factory

    def factory(mon):
        dev = make(mon)
        dev.fail_next(op, com.DXGI_ERROR_DEVICE_REMOVED)
        return dev
    rig.engine.device_factory = factory
    rig.make = make
    return rig


class BuildLoss(unittest.TestCase):
    def _run_posts(self, op):
        rig = broken_rig(op)
        waits = []
        names = ("home", "music")
        for i in range(20):                                # 20 posts 0.1 s apart, then quiet turns
            rig.engine.post({"content": content(names[i % 2]), "visible": True, "eligible": True,
                             "reduced": False, "art": {}})
            waits.append(rig.engine.process())
            rig.clk.advance(0.1)
        for _ in range(20):
            waits.append(rig.engine.process())
            rig.clk.advance(0.25)
        return rig, waits

    def _check_capped(self, rig, waits):
        e = rig.engine
        self.assertLessEqual(e.counters["device_creates"], 3, e.counters)
        self.assertEqual(len(rig.devices), e.counters["device_creates"])
        self.assertEqual(e.policy.state, COLD)
        self.assertIsNone(e.device)
        self.assertNotIn(0.0, waits[1:])
        self.assertEqual(len([m for m in rig.logs if "GetDeviceRemovedReason" in m]), 1, rig.logs)
        for dev in rig.devices:
            self.assertEqual(dev.alive(), 0, "a dead device or a half-built scene stayed alive")

    def test_create_visual_loss_is_capped(self):
        rig, waits = self._run_posts("CreateVisual")
        self._check_capped(rig, waits)

    def test_show_commit_loss_is_capped(self):
        rig, waits = self._run_posts("Commit")
        self._check_capped(rig, waits)

    def test_next_open_after_the_cap_tries_again_and_shows(self):
        rig, _ = self._run_posts("CreateVisual")
        before = rig.engine.counters["device_creates"]
        rig.engine.device_factory = rig.make               # the driver is back
        rig.post(content("home"), visible=False)           # the card hides ...
        rig.post(content("home"))                         # ... and opens again
        self.assertEqual(rig.engine.counters["device_creates"], before + 1)
        self.assertTrue(rig.engine.shown)
        self.assertEqual(rig.engine.policy.state, WARM)
        self.assertFalse(rig.engine.fresh)
        self.assertFalse(rig.engine.removed_reason_logged, "a device that showed may log its own loss")

    def test_a_shown_device_lost_later_still_recreates_at_once(self):
        rig = R.HeadlessNavigator(R.desktop_image())
        rig.logs = []
        rig.engine.log = rig.logs.append
        rig.post(content("home"))
        rig.advance(500)
        rig.dev.fail_next("Commit", com.DXGI_ERROR_DEVICE_REMOVED)
        rig.post(content("music"))
        self.assertEqual(len(rig.devices), 2)
        self.assertTrue(rig.engine.shown)
        self.assertEqual(rig.engine.policy.state, WARM)
        self.assertEqual(rig.devices[0].alive(), 0)


if __name__ == "__main__":
    unittest.main()
