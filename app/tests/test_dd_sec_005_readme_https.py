"""DD-SEC-005 (docs side): the README documents that the Home Assistant address can be https://
(certificate verified) and that with http:// the token travels unencrypted unless Home Assistant
runs on the same PC. Pure file read: no Tk, no ports, no network."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReadmeHomeAssistantHttps(unittest.TestCase):
    def setUp(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        # The Home Assistant paragraph (one bullet), whitespace collapsed.
        match = re.search(r"^- Home Assistant.*?(?=^\S|^- |\Z)", text, re.M | re.S)
        self.assertIsNotNone(match, "README has no Home Assistant bullet")
        self.section = " ".join(match.group(0).split())

    def test_https_is_documented_with_certificate_verification(self):
        self.assertIn("`https://`", self.section)
        self.assertRegex(self.section, r"certificate is verified")

    def test_http_cleartext_warning_with_same_pc_exception(self):
        self.assertIn("`http://`", self.section)
        self.assertRegex(self.section, r"token travels unencrypted")
        self.assertRegex(self.section, r"unless Home Assistant runs on the same PC")

    def test_matches_the_settings_note_text(self):
        # The README promise matches what Settings shows (lane commit for DD-SEC-005).
        ui = (ROOT / "control_center" / "ui.py").read_text(encoding="utf-8")
        self.assertIn("The token travels unencrypted on your network", ui)
        self.assertIn("note under the address", self.section)


if __name__ == "__main__":
    unittest.main()
