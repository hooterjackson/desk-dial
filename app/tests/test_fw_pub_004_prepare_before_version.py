"""FW-PUB-004 follow-up: prepare_nanod_cc5_install.py's before-inventory check accepts the from-release's reported
"firmwareVersion" in either form (the internal id of an image built before FW-PUB-004, the composed form of its
profile, or the reportedVersion release.json records for the from image). Pure function tests on
before_version_ok; no port, no device, no build."""
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
class PrepareBeforeVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepare = base.load_script("prepare_nanod_cc5_install.py")

    def setUp(self):
        self.p = t.PROFILES["cc5.7"].binary_profile("F")
        self.ok = self.prepare.before_version_ok

    def test_accepts_internal_from_version(self):
        self.assertTrue(self.ok(self.p.from_version, self.p, ini_text=INI, record={}))

    def test_refuses_other_strings(self):
        for value in ("1.0.0-cc5.5", "1.0.0-cc5.7", "1.0.0+cc5.7.F", "", None, "1.0.0+cc5.6.F"):
            self.assertFalse(self.ok(value, self.p, ini_text=INI, record={}), value)

    def test_accepts_composed_form_of_the_from_profile(self):
        fp = t.from_profile(self.p)
        ini = INI.replace("1.0.0-cc5.7", fp.version)
        composed = t.knob_reported_version(fp, self.p.from_binary, ini_text=ini)
        self.assertNotEqual(composed, fp.version)
        self.assertTrue(self.ok(composed, self.p, ini_text=ini, record={}))

    def test_accepts_composed_form_recorded_in_release_json(self):
        record = {"releases": [{"version": "1.0.0", "firmware": {
            "reportedVersion": "1.0.0+cc5.6.F", "internalVersion": "1.0.0-cc5.6", "binary": "F"}}]}
        self.assertTrue(self.ok("1.0.0+cc5.6.F", self.p, ini_text=INI, record=record))
        wrong_binary = {"releases": [{"version": "1.0.0", "firmware": {
            "reportedVersion": "1.0.0+cc5.6.D", "internalVersion": "1.0.0-cc5.6", "binary": "D"}}]}
        self.assertFalse(self.ok("1.0.0+cc5.6.D", self.p, ini_text=INI, record=wrong_binary))

    def test_main_uses_the_helper(self):
        source = base.WORK.joinpath("prepare_nanod_cc5_install.py").read_text(encoding="utf-8")
        self.assertIn('before_version_ok(inventory.get("settings", {}).get("firmwareVersion"), p)', source)
        self.assertNotIn('inventory.get("settings", {}).get("firmwareVersion") != p.from_version', source)


if __name__ == "__main__":
    unittest.main()
