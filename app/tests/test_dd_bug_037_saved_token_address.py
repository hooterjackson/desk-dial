"""DD-BUG-037: Settings > Home Assistant sends the saved token only to the saved address. An edited
address with an empty token field needs the token typed: begin_test refuses and the page never builds
a probe with the saved token. Headless: the page model and the page source (no Tk, no network)."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import ui  # noqa: E402

SAVED = {"ha_base_url": "http://ha-a.lan:8123", "ha_area": "office"}


class SavedTokenAddressTests(unittest.TestCase):
    def test_a_saved_token_is_not_sent_to_a_new_address(self):
        model = ui.HaSettingsModel(SAVED, saved_token=True)
        model.edit_address("http://ha-b.lan:8123")
        self.assertFalse(model.saved_token_applies())
        self.assertEqual(model.begin_test(), (None, ui.HA_TOKEN_FOR_ADDRESS))
        self.assertEqual(model.status, "error")

    def test_the_saved_address_still_uses_the_saved_token(self):
        for address in ("http://ha-a.lan:8123", "http://ha-a.lan:8123/", "  HTTP://HA-A.lan:8123 "):
            with self.subTest(address=address):
                model = ui.HaSettingsModel(SAVED, saved_token=True)
                model.edit_address(address)
                self.assertTrue(model.saved_token_applies())
                self.assertIsNone(model.begin_test()[1])

    def test_a_typed_token_works_for_any_address(self):
        model = ui.HaSettingsModel(SAVED, saved_token=True)
        model.edit_address("http://ha-b.lan:8123")
        model.edit_token("typed-test-token")
        self.assertEqual(model.begin_test(), ("http://ha-b.lan:8123", None))

    def test_no_saved_address_means_no_saved_token_use(self):
        model = ui.HaSettingsModel({}, saved_token=True)
        self.assertFalse(model.saved_token_applies())
        self.assertEqual(model.begin_test()[0], None)

    def test_save_to_a_new_address_needs_the_typed_token(self):
        model = ui.HaSettingsModel(SAVED, saved_token=True)
        model.edit_address("http://ha-b.lan:8123")
        model.status, model.result = "ok", {"ok": True, "areas": [("office", "Office", 1)]}   # e.g. simulator
        with self.assertRaises(ValueError):
            model.save_values()
        model.edit_token("typed-test-token")
        model.status, model.result = "ok", {"ok": True, "areas": [("office", "Office", 1)]}
        self.assertEqual(model.save_values()["ha_base_url"], "http://ha-b.lan:8123")
        model.mark_saved(1.0)
        self.assertEqual(model.saved_address, "http://ha-b.lan:8123")
        model.edit_token("")
        self.assertTrue(model.saved_token_applies(), "after Save the token belongs to the new address")

    def test_the_page_loads_the_saved_token_only_when_it_applies(self):
        source = Path(ui.__file__).read_text(encoding="utf-8")
        self.assertIn("load_token(store) if model.saved_token_applies() else", source)
        self.assertNotIn("model.token.strip() or load_token(store)\n", source)


if __name__ == "__main__":
    unittest.main()
