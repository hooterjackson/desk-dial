"""DD-DES-006: Home's hold-4 domain swap (music <-> lights, the mode stays ``launcher``) slides the
Navigator's content laterally like the knob (M12/M14: 28 u on SPRING.snap 416 ms, 240 ms fade),
towards Lights from the right and back from the left; reduced motion is a 160 ms fade only. Same-kind
updates in the same mode stay in place. Headless (recording fake device), no window, no GPU."""
import dataclasses
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import navigator_model as NM  # noqa: E402
from control_center.stage.scenes import navigator as NS  # noqa: E402
from control_center.stage.scenes import navigator_render as R  # noqa: E402
from control_center.stage.scenes import navigator_engine as NE  # noqa: E402

STATES = {name: (snap, pressed) for name, snap, pressed in R.design_states()}
K = 2.0                                     # the headless rig's scale


def home(domain=None, **extra):
    snap, pressed = STATES["home"]
    snap = dict(snap, **extra)
    if domain == "lights":
        snap["home_domain"] = "lights"
        snap["lights"] = R._lights()
    return NM.build_content(snap, pressed=pressed)


class HomeDomainSwap(unittest.TestCase):
    def rig(self, reduced=False):
        rig = R.HeadlessNavigator(R.desktop_image(), reduced=reduced)
        rig.post(home())
        rig.advance(600)
        return rig

    def test_contents_are_same_mode_different_kind(self):
        music, lights = home(), home("lights")
        self.assertEqual((music.mode, lights.mode), ("launcher", "launcher"))
        self.assertEqual((music.kind, lights.kind), ("now", "lights"))

    def test_home_domain_swap_slides_laterally(self):
        rig = self.rig()
        pad = float(K * NS.PAD)
        rig.post(home("lights"))                                   # hold 4: to Lights, from the right
        f = rig.engine.scene.body_x.func
        self.assertEqual((f.v0, f.v1, round(f.dur, 3)), (pad + K * NS.SWAP_U, pad, NS.SWAP_X_MS / 1000))
        self.assertAlmostEqual(rig.engine.scene.body_op.func.dur, NS.SWAP_OP_MS / 1000)
        rig.advance(600)
        rig.post(home())                                           # back to music: from the left
        f = rig.engine.scene.body_x.func
        self.assertEqual((f.v0, f.v1, round(f.dur, 3)), (pad - K * NS.SWAP_U, pad, NS.SWAP_X_MS / 1000))

    def test_reduced_motion_is_a_160_ms_fade(self):
        rig = self.rig(reduced=True)
        rig.post(home("lights"))
        sc = rig.engine.scene
        self.assertAlmostEqual(sc.body_op.func.dur, NS.REDUCED_SWAP_MS / 1000)
        self.assertEqual(sc.body_x.func.v, float(K * NS.PAD))    # a jump: no slide

    def test_direction_rules(self):
        d = NE.NavigatorEngine._direction
        music, lights = home(), home("lights")
        self.assertEqual(d(None, lights, music), 1)
        self.assertEqual(d(None, music, lights), -1)
        self.assertEqual(d(None, music, dataclasses.replace(music, volume=10)), 0, "same-kind update")
        self.assertEqual(d(None, lights, lights), 0)
        self.assertEqual(d(None, music, None), 0)


if __name__ == "__main__":
    unittest.main()
