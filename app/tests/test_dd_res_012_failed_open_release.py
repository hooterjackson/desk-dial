"""DD-RES-012: a music stage open whose scene build raises releases the half-built scene: its own
surfaces go, its art jobs are forgotten, the frost is released and the open is refused (device).
Headless: the fake device, host and capture; no window, no GPU."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image  # noqa: E402

from control_center.stage.scenes.common import SceneBase  # noqa: E402
from test_stage_engine import Rig  # noqa: E402


class FakeArt:
    def __init__(self):
        self.owned = {}
        self.forgotten = []

    def add(self, owner, key):
        self.owned.setdefault(owner, set()).add(key)

    def forget(self, owner, *, running=True):
        self.forgotten.append(owner)
        self.owned.pop(owner, None)


ART = FakeArt()
BUILT = []


class BrokenScene(SceneBase):
    surface = "explorer"

    def __init__(self, ctx, payload):
        super().__init__(ctx, payload, art=ART)
        BUILT.append(self)

    def build(self, payload, container):
        self.own_surface(Image.new("RGB", (8, 8), (10, 20, 30)), "own.card")
        ART.add(self.owner, ("art", "cover-1"))
        raise RuntimeError("build failed after own_surface")


class FailedBuildRelease(unittest.TestCase):
    def setUp(self):
        ART.owned.clear()
        ART.forgotten.clear()
        BUILT.clear()

    def test_failed_scene_build_releases_scene_surfaces_and_jobs(self):
        r = Rig(scenes={"explorer": BrokenScene})
        ev = r.open()
        self.assertEqual(ev, [("refused", {"surface": "explorer", "reason": "device"})])
        self.assertEqual(len(BUILT), 1)
        scene = BUILT[0]
        self.assertTrue(scene.closed)
        self.assertEqual(scene.surfaces, [])
        self.assertEqual(ART.forgotten, [scene.owner])
        self.assertEqual(ART.owned, {})
        dev = r.dev
        live = [o for o in dev.objects.values() if o["kind"] == "surface" and not o["released"]
                and o["name"] in ("own.card", "frost")]
        self.assertEqual(live, [])
        self.assertEqual(dev.violations, [])
        self.assertIsNone(r.engine.building)
        self.assertIsNone(r.engine.scene)

    def test_next_open_after_a_failed_build_opens(self):
        r = Rig(scenes={"explorer": BrokenScene})
        r.open()
        from control_center.stage.probe_scene import ProbeScene
        r.engine.scenes["explorer"] = ProbeScene
        self.assertEqual(r.open(), [("opened", {"surface": "explorer"})])
        self.assertIsNone(r.engine.building)
        self.assertEqual(r.dev.violations, [])


if __name__ == "__main__":
    unittest.main()
