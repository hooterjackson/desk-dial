"""DD-BUG-010 (D3 side): when a successful Home Assistant test could not read the area list (no
WebSocket and a non-admin token; the template API is admin-only), the Settings page shows the test's
``areas_note`` in place of an empty area list. Headless: the page model only (no Tk, no network)."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import ui  # noqa: E402
from control_center.home_assistant import AREAS_NEED_ADMIN  # noqa: E402

ADDRESS = "http://ha.example:8123"


def tested(result, config=None):
    model = ui.HaSettingsModel(config or {"ha_base_url": ADDRESS}, saved_token=True)
    model.edit_token("test-token")
    base, error = model.begin_test()
    assert base and error is None
    model.finish_test(result, model.generation)
    return model


def ok(areas=(), note="", details=None):
    return {"ok": True, "outcome": "ok", "version": "", "entities": {}, "areas": list(areas),
            "area_details": details or {}, "default_area": areas[0][0] if areas else "", "areas_note": note}


class AreasNoteTests(unittest.TestCase):
    def test_note_replaces_the_empty_area_list(self):
        model = tested(ok(note=AREAS_NEED_ADMIN))
        self.assertEqual(model.status, "ok")
        self.assertEqual(model.areas_note(), AREAS_NEED_ADMIN)
        self.assertIsNone(model.lists())
        self.assertEqual(model.placeholder(), AREAS_NEED_ADMIN)
        self.assertTrue(model.placeholder().startswith("Connected, but the area list needs"))

    def test_note_also_wins_over_a_saved_area_with_no_details(self):
        model = tested(ok(note=AREAS_NEED_ADMIN), {"ha_base_url": ADDRESS, "ha_area": "area_one"})
        self.assertIsNone(model.lists())
        self.assertEqual(model.placeholder(), AREAS_NEED_ADMIN)

    def test_no_note_keeps_the_lists(self):
        model = tested(ok(areas=[("area_one", "Area One", 1)]))
        self.assertEqual(model.areas_note(), "")
        self.assertEqual(model.placeholder(), "")
        self.assertIsNotNone(model.lists())

    def test_note_ignored_when_areas_were_read(self):
        model = tested(ok(areas=[("area_one", "Area One", 1)], note=AREAS_NEED_ADMIN))
        self.assertEqual(model.areas_note(), "")
        self.assertIsNotNone(model.lists())

    def test_missing_or_bad_note_is_no_note(self):
        result = ok()
        del result["areas_note"]
        self.assertEqual(tested(result).areas_note(), "")
        self.assertEqual(tested(ok(note=None)).areas_note(), "")

    def test_failed_test_shows_no_note(self):
        model = tested({"ok": False, "outcome": "offline"})
        self.assertEqual(model.areas_note(), "")
        self.assertNotEqual(model.placeholder(), AREAS_NEED_ADMIN)


if __name__ == "__main__":
    unittest.main()
