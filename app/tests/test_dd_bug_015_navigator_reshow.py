"""DD-BUG-015: a Navigator card re-shown from a warm (hidden) scene marks the scene open again, so
the 600 s idle release never destroys a card that is on screen. Headless: fake device, host, clock."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import navigator_model as NM  # noqa: E402
from control_center.stage.scenes import navigator_render as R  # noqa: E402

STATES = {name: (snap, pressed) for name, snap, pressed in R.design_states()}


def content(name):
    snap, pressed = STATES[name]
    return NM.build_content(snap, pressed=pressed)


class EngineLifecycle(unittest.TestCase):
    def test_reshown_card_is_not_released_after_600_s(self):
        rig = R.HeadlessNavigator(R.desktop_image())
        rig.post(content("home"))
        rig.advance(500)
        rig.post(content("home"), visible=False)          # auto-hide: idle_since = T
        rig.advance(1000)
        self.assertIsNotNone(rig.engine.policy.idle_since)
        rig.clk.advance(300.0)
        rig.post(content("music"))                        # re-shown from the warm scene
        rig.advance(500)
        self.assertTrue(rig.engine.shown)
        self.assertTrue(rig.engine.policy.scene_open)
        self.assertIsNone(rig.engine.policy.idle_since)
        creates = rig.engine.counters["device_creates"]
        rig.clk.advance(301.0)                            # T + 600 s, the card still on screen
        rig.engine.process()
        self.assertIsNotNone(rig.engine.device)
        self.assertIsNotNone(rig.engine.scene)
        self.assertTrue(rig.engine.shown)
        self.assertTrue(rig.engine.scene.visible)
        self.assertEqual(rig.engine.counters["device_releases"], 0)
        self.assertEqual(rig.engine.counters["device_creates"], creates)

    def test_hidden_card_is_still_released_after_600_s(self):
        rig = R.HeadlessNavigator(R.desktop_image())
        rig.post(content("home"))
        rig.advance(500)
        rig.post(content("home"), visible=False)
        rig.advance(1000)
        rig.post(content("home"))
        rig.advance(500)
        rig.post(content("home"), visible=False)          # hidden again: the 600 s count restarts
        rig.advance(1000)
        rig.clk.advance(601.0)
        rig.engine.process()
        self.assertIsNone(rig.engine.device)


if __name__ == "__main__":
    unittest.main()
