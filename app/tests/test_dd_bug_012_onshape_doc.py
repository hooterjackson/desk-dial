"""DD-BUG-012: ONSHAPE.md section 7 documents the address-bar read (Auto and Manual, host only, never stored,
off the Tk thread) and that Off reads nothing. Text-only: no Tk, no ports, no network."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent


def section_7():
    text = (ROOT / "ONSHAPE.md").read_text(encoding="utf-8")
    match = re.search(r"^## 7\..*?(?=^## 8\.)", text, re.S | re.M)
    assert match, "ONSHAPE.md has no section 7"
    return match.group(0)


class OnshapeDocAddressBarTest(unittest.TestCase):
    def test_auto_and_manual_read_the_host_through_ui_automation(self):
        sec = section_7()
        self.assertIn("Address bar (Auto and Manual)", sec)
        self.assertIn("UI Automation", sec)
        self.assertIn("host", sec)
        self.assertRegex(sec, r"never stored or logged")

    def test_the_read_is_off_the_tk_thread_and_bounded(self):
        sec = section_7()
        self.assertIn("AddressVerdicts", sec)
        self.assertIn("ADDRESS_UIA_TIMEOUT_MS", sec)
        self.assertIn("ADDRESS_CACHE_SECONDS", sec)

    def test_off_reads_nothing(self):
        sec = section_7()
        off = sec[sec.index("Off reads nothing"):]
        self.assertIn("No window title", off)
        self.assertIn("no address bar", off)
        self.assertIn("EVENT_OBJECT_NAMECHANGE", off)

    def test_documented_names_exist_in_code(self):
        from control_center import onshape, browser_url
        self.assertTrue(hasattr(onshape, "AddressVerdicts"))
        self.assertTrue(hasattr(onshape, "ADDRESS_UIA_TIMEOUT_MS"))
        self.assertEqual(onshape.ADDRESS_CACHE_SECONDS, 5.0)
        self.assertTrue(callable(browser_url.address_host))
        self.assertTrue(callable(getattr(onshape.FocusWatcher, "pause", None)))


if __name__ == "__main__":
    unittest.main()
