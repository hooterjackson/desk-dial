"""DD-RES-013: control_center.paths keeps only the LEGACY_HOME_NAME constant for the pre-rename home;
the unreferenced legacy_home() helper is gone (the migration lives in the PowerShell installer)."""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center import paths  # noqa: E402


class LegacyHomeHelperRemoved(unittest.TestCase):
    def test_no_legacy_home_function(self):
        self.assertFalse(hasattr(paths, "legacy_home"))
        tree = ast.parse((ROOT / "control_center" / "paths.py").read_text(encoding="utf-8"))
        defs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        self.assertNotIn("legacy_home", defs)

    def test_constant_and_home_kept(self):
        self.assertEqual(paths.LEGACY_HOME_NAME, "NanoDControlCenter")
        self.assertEqual(paths.home().name, paths.HOME_NAME)

    def test_no_caller_left(self):
        sources = [ROOT / "standalone.py", *(ROOT / "control_center").rglob("*.py")]
        for path in sources:
            if "__pycache__" in path.parts:
                continue
            self.assertNotIn("legacy_home(", path.read_text(encoding="utf-8"), str(path))


if __name__ == "__main__":
    unittest.main()
