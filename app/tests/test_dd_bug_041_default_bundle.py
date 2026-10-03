"""DD-BUG-041: Install-Desktop.ps1's default bundle is the one Build-Desktop.ps1 builds by default, so
"Build-Desktop.ps1, then Install-Desktop.ps1" installs what was just built. Both scripts are read only."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


class DefaultBundleTests(unittest.TestCase):
    def test_installer_default_bundle_matches_build_default(self):
        build, install = read("Build-Desktop.ps1"), read("Install-Desktop.ps1")
        dist = re.search(r"^\s*\[string\]\$Dist = '([^']+)'", build, re.M).group(1)
        bundle = re.search(r"^\s*\[string\]\$Bundle = '([^']+)'", install, re.M).group(1)
        self.assertEqual(bundle, dist)
        rollback = re.findall(r"'([\w-]+)'", re.search(r"\$rollbackFolders = @\(([^)]*)\)", build).group(1))
        self.assertNotIn(bundle, rollback, "the default must not be a bundle the build refuses as a rollback")
        # Nor a pinned rollback bundle (those install as the old name).
        pinned = re.findall(r"'(desktop-dist-v\d)' = '[0-9A-F]{64}'", install)
        self.assertTrue(pinned)
        self.assertNotIn(bundle, pinned)

    def test_the_documented_install_steps_name_the_default_bundle(self):
        install = read("Install-Desktop.ps1")
        bundle = re.search(r"\[string\]\$Bundle = '([^']+)'", install).group(1)
        header = install[:install.index("[string]$Bundle")]
        self.assertIn(f"{bundle}\\DeskDial\\DeskDial.exe --smoke-test", header)
        self.assertIn(f"Install-Desktop.ps1 -Bundle {bundle} -Mirror -DryRun", header)
        self.assertIn(f"Install-Desktop.ps1 -Bundle {bundle} -Mirror;", header)


if __name__ == "__main__":
    unittest.main()
