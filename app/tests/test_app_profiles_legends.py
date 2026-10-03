"""Blender and AutoCAD legends (plan section 4d, S1 DD-B): Karl's empty templates label button 4 MENU, his firmware's
long-press menu key, which Desk Dial doesn't have (the profile is chosen on the PC; Home is the 4-button chord). The
sidecars blank the legend, so the knob never names a key that does nothing. Headless."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.app_profiles import load_pair, read_json  # noqa: E402

PROFILES = Path(__file__).resolve().parents[1] / "profiles"


class BasicLegendTests(unittest.TestCase):
    def test_karl_names_a_menu_key_the_sidecar_blanks_it(self):
        for pid in ("blender", "autocad"):
            with self.subTest(pid):
                self.assertIn("MENU", read_json(PROFILES / "karl" / f"{pid}.json")["legend"])
                profile = load_pair(PROFILES / "karl" / f"{pid}.json", PROFILES / f"{pid}.windows.json")
                self.assertEqual(profile.legend, ("", "", "", ""))
                self.assertEqual({s.kind for name, s in profile.slots.items() if name != "knob"}, {"none"},
                                 "no button does anything: nothing to label")
                self.assertEqual(profile.slots["knob"].kind, "wheel")
                self.assertNotIn(b"MENU", profile.wire())

    def test_no_bundled_profile_labels_a_menu_key(self):
        for path in PROFILES.glob("*.windows.json"):
            pid = path.name[:-len(".windows.json")]
            profile = load_pair(PROFILES / "karl" / f"{pid}.json", path)
            self.assertNotIn("MENU", profile.legend, pid)


if __name__ == "__main__":
    unittest.main()
