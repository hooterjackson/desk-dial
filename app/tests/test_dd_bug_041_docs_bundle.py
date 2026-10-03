"""DD-BUG-041 (docs side): the install steps in DESKTOP.md and the bundle line in README.md name the bundle
Build-Desktop.ps1 builds by default ($Dist), so following the docs installs what was just built.
The bundle name is read from Build-Desktop.ps1, so a later version bump must update the docs too."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def build_dist():
    return re.search(r"^\s*\[string\]\$Dist = '([^']+)'", read("Build-Desktop.ps1"), re.M).group(1)


class DocsBundleTests(unittest.TestCase):
    def build_and_install_section(self):
        text = read("DESKTOP.md")
        start = text.index("## Build and install")
        end = text.index("Desktop rollback:", start)
        return text[start:end]

    def test_desktop_md_install_steps_name_the_built_bundle(self):
        dist = build_dist()
        section = self.build_and_install_section()
        self.assertIn(f"`{dist}\\DeskDial\\DeskDial.exe --smoke-test`", section)
        self.assertIn(f"`Install-Desktop.ps1 -Bundle {dist} -Mirror -DryRun`", section)
        self.assertIn(f"`Install-Desktop.ps1 -Bundle {dist} -Mirror`", section)
        self.assertIn(f"installer defaults to `-Bundle {dist}`", " ".join(section.split()))
        # No install command or smoke-test path in the section names another bundle.
        for named in re.findall(r"-Bundle (desktop-dist-[\w-]+)", section):
            self.assertEqual(named, dist)
        for named in re.findall(r"(desktop-dist-[\w-]+)\\DeskDial\\DeskDial\.exe --smoke-test", section):
            self.assertEqual(named, dist)

    def test_installer_default_matches_the_docs(self):
        bundle = re.search(r"\[string\]\$Bundle = '([^']+)'", read("Install-Desktop.ps1")).group(1)
        self.assertEqual(bundle, build_dist())

    def test_readme_bundle_line_names_the_built_bundle(self):
        line = next(l for l in read("README.md").splitlines() if l.startswith("- Bundle: "))
        self.assertEqual(re.search(r"`(desktop-dist-[\w-]+)`", line).group(1), build_dist())


if __name__ == "__main__":
    unittest.main()
