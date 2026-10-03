"""FW-PUB-004 (Desk Dial side): the app names its own public version next to the knob's firmware version.

desktop-version.txt's ProductVersion is the public version of the pair (FileVersion keeps its own series, 7.4.0.0); Build-Desktop.ps1
bundles the file so the frozen app reads the same string; the Settings status strip's Knob column shows both the
knob's firmwareVersion ("<public>+<build id>.<binary letter>") and Desk Dial's version. No Tk, port or network.
"""
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from control_center import ui  # noqa: E402

VERSION_TXT = "        StringStruct('FileVersion', '7.3.2.0'),\n        StringStruct('ProductVersion', '{}')])\n"


def runtime(connected=True, supported=True, status="Knob ready"):
    return SimpleNamespace(device_connected=connected, device_supported=supported, device_status=status,
                           controller=SimpleNamespace(state={"online": False}), music_signin_expired=False,
                           apple=SimpleNamespace(has_credentials=lambda: True))


class AppVersionTests(unittest.TestCase):
    def test_product_version_is_the_public_version(self):
        text = (ROOT / "desktop-version.txt").read_text(encoding="utf-8")
        self.assertIn("StringStruct('FileVersion', '7.4.1.0')", text)
        self.assertIn("filevers=(7, 4, 1, 0)", text)
        product = ui.app_version(text)
        self.assertRegex(product, r"^\d+\.\d+\.\d+$")
        self.assertNotRegex(product, r"(?i)cc\d")
        self.assertEqual(product, "2.0.0")
        fixed = re.search(r"prodvers=\((\d+), (\d+), (\d+), (\d+)\)", text).groups()
        self.assertEqual(".".join(fixed[:3]), product, "the fixed product version matches the string")

    def test_app_version_parses_and_never_raises(self):
        self.assertEqual(ui.app_version(VERSION_TXT.format("2.0.0")), "2.0.0")
        self.assertIsNone(ui.app_version("no version here"))
        self.assertIsNone(ui.app_version(VERSION_TXT.format("")))
        self.assertIsNone(ui.app_version(VERSION_TXT.format("9" * 41)))
        with mock.patch.object(ui, "APP_VERSION_FILE", ROOT / "no-such-file.txt"), \
                mock.patch.object(ui, "_APP_VERSION", []):
            self.assertIsNone(ui.app_version())
        with mock.patch.object(ui, "_APP_VERSION", []):
            self.assertEqual(ui.app_version(), "2.0.0")          # the real file, read once
            self.assertEqual(ui.app_version(), "2.0.0")

    def test_strip_shows_both_versions(self):
        knob = ui.strip_model(runtime(), firmware="2.0.0+cc5.7.F", app="2.0.0")[0]
        self.assertEqual(knob["detail"], "USB · firmware 2.0.0+cc5.7.F · Desk Dial 2.0.0")
        # The app version shows when no firmware string is known and when the knob is not connected.
        self.assertEqual(ui.strip_model(runtime(), app="2.0.0")[0]["detail"], "USB · Desk Dial 2.0.0")
        waiting = ui.strip_model(runtime(connected=False), app="2.0.0")[0]["detail"]
        self.assertTrue(waiting.endswith(" · Desk Dial 2.0.0"))
        released = ui.strip_model(runtime(supported=False, status="Host control released"), app="2.0.0")[0]
        self.assertEqual(released["detail"], "Host control released · Desk Dial 2.0.0")
        # No app version: the detail is unchanged.
        self.assertEqual(ui.strip_model(runtime(), firmware="2.0.0+cc5.7.F")[0]["detail"],
                         "USB · firmware 2.0.0+cc5.7.F")
        # firmware_version accepts the reported string (up to 40 characters).
        self.assertLessEqual(len("2.0.0+cc5.7.F"), 40)

    def test_settings_window_passes_the_app_version(self):
        source = (ROOT / "control_center" / "ui.py").read_text(encoding="utf-8")
        body = source[source.index("    def status_strip(self):"):source.index("    def _strip_columns(self):")]
        self.assertIn("app=app_version()", body)

    def test_build_bundles_the_version_file(self):
        script = (ROOT / "Build-Desktop.ps1").read_text(encoding="utf-8")
        self.assertIn("$versionData = $versionFile + ';.'", script)
        build = next(line for line in script.splitlines() if "-m PyInstaller" in line)
        self.assertIn("--add-data $versionData ", build)
        self.assertIn("--version-file $versionFile ", build)
        self.assertEqual(ui.APP_VERSION_FILE, ui.APP_DIR / "desktop-version.txt")


if __name__ == "__main__":
    unittest.main()
