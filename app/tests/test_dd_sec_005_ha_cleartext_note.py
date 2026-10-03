"""DD-SEC-005: Settings > Home Assistant shows a one-line cleartext note under the address when the
token would travel as plain http to a host other than this PC; https:// and loopback stay silent and
http stays supported. Headless: the page's model and the page source only (no Tk window, no network)."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import ui  # noqa: E402


class CleartextNoteTests(unittest.TestCase):
    def test_http_address_shows_cleartext_note(self):
        for address in ("http://ha.lan:8123", "http://homeassistant.local:8123", "HTTP://10.0.0.5:8123",
                        ui.HA_DEFAULT_ADDRESS):
            with self.subTest(address=address):
                self.assertEqual(ui.ha_cleartext_note(address), ui.HA_CLEARTEXT_NOTE)
        self.assertIn("https://", ui.HA_CLEARTEXT_NOTE)

    def test_https_and_loopback_have_no_note(self):
        for address in ("https://ha.lan:8123", "http://127.0.0.1:8123", "http://127.8.0.1", "http://[::1]:8123",
                        "http://localhost:8123", "http://ha.localhost", "", "ha.lan", "ftp://ha.lan",
                        "http://[bad", None):
            with self.subTest(address=address):
                self.assertEqual(ui.ha_cleartext_note(address), "")

    def test_the_model_follows_the_address_edits(self):
        model = ui.HaSettingsModel({})
        self.assertEqual(model.cleartext_note(), ui.HA_CLEARTEXT_NOTE, "the prefilled http default warns")
        model.edit_address("https://ha.lan:8123")
        self.assertEqual(model.cleartext_note(), "")
        model.edit_address("http://ha.lan:8123")
        self.assertEqual(model.cleartext_note(), ui.HA_CLEARTEXT_NOTE)

    def test_http_is_still_accepted(self):
        model = ui.HaSettingsModel({})
        model.edit_address("http://ha.lan:8123")
        model.edit_token("typed-test-token")
        base, error = model.begin_test()
        self.assertEqual((base, error), ("http://ha.lan:8123", None))

    def test_the_page_mirrors_the_note(self):
        source = Path(ui.__file__).read_text(encoding="utf-8")
        start = source.index("def _build_ha_page")
        page = source[start:source.index("\n    def ", start + 10)]
        self.assertIn("model.cleartext_note()", page)


if __name__ == "__main__":
    unittest.main()
