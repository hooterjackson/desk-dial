"""FW-PUB-004 follow-up: finalize_nanod_cc5.py's settings check accepts the knob's reported "firmwareVersion" in
either form (the internal id of an image built before FW-PUB-004, or "<public>+<build>.<letter>") for this release
AND for the from-release, so a later release whose from-image already reports the composed form still finalizes.
Pure function tests on settings_version_ok; no port, no device, no build."""
import unittest

import test_cc5_tooling as base

t = base.t

INI = """[env:nanofoc_d]
platform = espressif32
build_flags =
\t-DNANO_FIRMWARE_VERSION=\\"1.0.0-cc5.7\\"
\t-DNANO_FIRMWARE_PUBLIC=\\"1.0.0\\"
"""


@base.needs_tooling
class FinalizeSettingsVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.finalize = base.load_script("finalize_nanod_cc5.py")

    def setUp(self):
        self.p = t.PROFILES["cc5.7"].binary_profile("F")
        self.ok = self.finalize.settings_version_ok

    def test_after_accepts_composed_and_internal_forms(self):
        for after in ("1.0.0+cc5.7.F", "1.0.0-cc5.7"):
            self.assertTrue(self.ok(self.p.from_version, after, self.p, ini_text=INI, record={}), after)

    def test_after_refuses_other_strings(self):
        for after in ("1.0.0+cc5.7.D", "1.0.0+cc5.6.F", "", None, "1.0.0-cc5.6"):
            self.assertFalse(self.ok(self.p.from_version, after, self.p, ini_text=INI, record={}), after)

    def test_before_accepts_internal_from_version(self):
        self.assertTrue(self.ok("1.0.0-cc5.6", "1.0.0+cc5.7.F", self.p, ini_text=INI, record={}))

    def test_before_refuses_other_strings(self):
        for before in ("1.0.0-cc5.5", "1.0.0+cc5.7.F", "", None, "1.0.0+cc5.6.F"):
            self.assertFalse(self.ok(before, "1.0.0+cc5.7.F", self.p, ini_text=INI, record={}), before)

    def test_before_accepts_composed_form_recorded_in_release_json(self):
        record = {"releases": [{"version": "1.0.0", "firmware": {
            "reportedVersion": "1.0.0+cc5.6.F", "internalVersion": "1.0.0-cc5.6", "binary": "F"}}]}
        self.assertTrue(self.ok("1.0.0+cc5.6.F", "1.0.0+cc5.7.F", self.p, ini_text=INI, record=record))
        wrong_binary = {"releases": [{"version": "1.0.0", "firmware": {
            "reportedVersion": "1.0.0+cc5.6.D", "internalVersion": "1.0.0-cc5.6", "binary": "D"}}]}
        self.assertFalse(self.ok("1.0.0+cc5.6.D", "1.0.0+cc5.7.F", self.p, ini_text=INI, record=wrong_binary))

    def test_main_uses_the_helper(self):
        source = base.WORK.joinpath("finalize_nanod_cc5.py").read_text(encoding="utf-8")
        self.assertIn('settings_version_ok(before_settings.get("firmwareVersion"), '
                      'after_settings.get("firmwareVersion"), p)', source)
        self.assertNotIn('before_settings.get("firmwareVersion") == p.from_version', source)


if __name__ == "__main__":
    unittest.main()
