"""The Onshape SendInput goldens (plan sections 4c and 6, S1 DD-B): today's tuned Onshape input, recorded before the
generic app engine replaced it (tests/onshape_input_golden.py), replayed byte for byte. Headless: a recording fake
backend, never SendInput."""
from pathlib import Path
import hashlib
import json
import logging
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import onshape_input_golden as golden  # noqa: E402


def stored(name):
    return (golden.GOLDENS / f"{name}.json").read_text(encoding="utf-8")


class GoldenManifestTests(unittest.TestCase):
    def test_every_script_has_its_golden_and_the_manifest_hashes_match(self):
        manifest = json.loads((golden.GOLDENS / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(manifest), sorted(golden.SCRIPTS))
        for name, entry in manifest.items():
            self.assertEqual(hashlib.sha256(stored(name).encode("utf-8")).hexdigest(), entry["sha256"], name)

    def test_the_goldens_cover_what_the_plan_names(self):
        def kinds(name):
            record = json.loads(stored(name))
            return {e[0] for b in record["batches"] for e in b["events"]}, record

        zoom, _ = kinds("zoom_both_ways_67")
        self.assertEqual(zoom, {"wheel"})
        drag, _ = kinds("tilt_drag_direction_change")
        self.assertLessEqual({"down", "up", "move"}, drag)
        search, record = kinds("wheel_search_command")
        self.assertEqual(search, {"key", "char"})
        times = [b["t"] for b in record["batches"]]
        self.assertAlmostEqual(times[1] - times[0], 0.25, places=6, msg="the search's open wait")
        self.assertAlmostEqual(times[2] - times[1], 0.41, places=6, msg="the result wait (on the 10 ms walk)")
        param_a, _ = kinds("param_mode_a")
        self.assertIn("wheel", param_a)
        _, record = kinds("undo_tap_a0")
        self.assertEqual(record["feedback"], ["undo", "refused"])
        for name in ("focus_loss_mid_drag", "session_change_mid_drag", "short_send_mid_drag", "exception_mid_drag",
                     "foreground_change_mid_drag", "lifecycle_disconnect_mid_drag"):
            record = json.loads(stored(name))
            self.assertTrue(record["status"]["releases"], name)


class GoldenReplayTests(unittest.TestCase):
    """The Onshape injector (onshape.OnshapeInjector) reproduces every golden."""

    make = staticmethod(golden.legacy_injector)

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def test_every_script_replays_exactly(self):
        for name, script in golden.SCRIPTS.items():
            with self.subTest(name):
                self.assertEqual(golden.canonical(golden.run(script, self.make)), stored(name))


def bundled_onshape():
    from control_center.app_profiles import load_pair
    profiles = Path(__file__).resolve().parents[1] / "profiles"
    return load_pair(profiles / "karl" / "onshape.json", profiles / "onshape.windows.json")


class GenericEngineReplayTests(GoldenReplayTests):
    """THE GATE (plan section 4c): the generic engine (app_engine.AppInjector + ProfileApp, every chord resolved
    through keymap at send time) running the bundled Onshape profile (Karl's onshape.json + Desk Dial's sidecar)
    reproduces today's tuned Onshape input exactly."""

    @staticmethod
    def make(backend, clock):
        from control_center.app_engine import AppInjector
        return AppInjector(backend, clock=clock, start=False, profile=bundled_onshape())


class FacadeWithBundledProfileReplayTests(GoldenReplayTests):
    """The Onshape facade fed the bundled profile (what the runtime activates it with) replays them too."""

    @staticmethod
    def make(backend, clock):
        from control_center.onshape import OnshapeInjector
        return OnshapeInjector(backend, clock=clock, start=False, profile=bundled_onshape())


if __name__ == "__main__":
    unittest.main()
