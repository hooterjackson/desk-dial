"""FU-2: Settings > Home Assistant after a successful Test connection: the lights list overflowed and, with
four lights, the fourth row was cut at the Save / Cancel rule. Now the lists grow Settings when they appear
(ControlCenterApp._refit_setup, capped at the work area as DD-BUG-020) and scroll in a ScrollPage between the
status rule and the Save rule for what still does not fit; the footer is packed first, so it is never
squeezed. Headless: stand-in widgets (the DD-BUG-020 ones) and a stand-in Wm; no Tk window is created."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from control_center import ui  # noqa: E402
from test_dd_bug_020_settings_knob_fit import FakeWm, make_page  # noqa: E402

UI_SOURCE = (Path(__file__).resolve().parents[1] / "control_center" / "ui.py").read_text(encoding="utf-8")
HA_PAGE = UI_SOURCE[UI_SOURCE.index("def _build_ha_page"):]
HA_PAGE = HA_PAGE[:HA_PAGE.index("\n    def ", 10)]

# The lists at 100 % (Segoe UI): a caption 29 px (8 pt bold + pady 10 / 4), a row 26 px (11 pt + pady 3 / 3).
CAPTION, ROW = 29, 26


def lists_layout(lights, scenes):
    """(top, bottom) px of every row in the lists, and their total height."""
    rows, y = [], CAPTION
    for _ in range(lights):
        rows.append((y, y + ROW))
        y += ROW
    y += CAPTION
    for _ in range(scenes):
        rows.append((y, y + ROW))
        y += ROW
    return rows, y


class HaListsScrollTests(unittest.TestCase):
    def test_the_fourth_light_and_every_scene_are_reachable(self):
        rows, need = lists_layout(lights=4, scenes=3)
        view = rows[3][0] + ROW // 2            # the finding: the Save rule cut the fourth light in half
        page = make_page()
        page.inner.reqheight = need
        page.canvas.width, page.canvas.height = 535, view
        page._sync()
        self.assertEqual(page.canvas.options["height"], need, "asks for every row, so Settings grows first")
        self.assertEqual(page.canvas.options["scrollregion"], (0, 0, 535, need))
        self.assertTrue(page.bar.packed, "what the work area cannot fit scrolls")
        for top, bottom in rows:
            widget = SimpleNamespace(winfo_rooty=lambda top=top: top, winfo_height=lambda h=bottom - top: h)
            page.see(widget)
            first = page.canvas.first * need
            with self.subTest(row=(top, bottom)):
                self.assertLessEqual(first, top + 1e-6)
                self.assertGreaterEqual(first + view, bottom - 1e-6, "the row is fully above the Save rule")

    def test_nothing_scrolls_when_the_lists_fit(self):
        _rows, need = lists_layout(lights=2, scenes=1)
        page = make_page()
        page.inner.reqheight, page.canvas.width, page.canvas.height = need, 535, need + 40
        page._sync()
        self.assertFalse(page.bar.packed)


class RefitSetupTests(unittest.TestCase):
    def refit(self, window, size, work=(0, 0, 1920, 1020), frame=(20, 49)):
        app = SimpleNamespace(setup_window=window, setup_size=size)
        with patch.object(ui, "primary_work_area", lambda _window=None: work), \
                patch.object(ui, "window_frame_extent", lambda dpi=None: frame):
            return ui.ControlCenterApp._refit_setup(app)

    def test_the_lists_grow_settings_up_to_the_work_area(self):
        window, size = FakeWm(reqheight=930, screen=1080), [600, 850]
        self.assertEqual(self.refit(window, size), 930, "every light fits: Settings grows to show it")
        self.assertEqual((window.geometries, size), (["600x930"], [600, 930]))
        window, size = FakeWm(reqheight=1400, screen=1080), [600, 850]
        self.assertEqual(self.refit(window, size), 971, "never under the taskbar; the lists scroll instead")

    def test_without_settings_nothing_happens(self):
        self.assertIsNone(self.refit(None, [600, 850]))
        self.assertIsNone(self.refit(FakeWm(reqheight=900, screen=1080), None))

    def test_a_failing_refit_never_raises(self):
        app = SimpleNamespace(setup_window=FakeWm(reqheight=900, screen=1080), setup_size=[600, 850])
        with patch.object(ui, "refit_height", side_effect=RuntimeError("boom")), \
                self.assertLogs(ui._log, level="ERROR"):
            self.assertIsNone(ui.ControlCenterApp._refit_setup(app))


class HaPageSourceTests(unittest.TestCase):
    def test_the_lists_live_in_a_scroll_page_after_the_footer(self):
        self.assertIn("scroller = ScrollPage(page, BG)", HA_PAGE)
        self.assertIn("content = scroller.inner", HA_PAGE)
        self.assertLess(HA_PAGE.index('footer.pack(side="bottom"'), HA_PAGE.index("scroller.outer.pack("),
                        "the footer is packed first: a short window squeezes the lists, never Save")
        self.assertIn("lists = tk.Frame(content, bg=BG)", HA_PAGE)

    def test_new_lists_refit_settings(self):
        start = HA_PAGE.index('rows(lights_box, data["lights"]')
        self.assertIn("self._refit_setup()", HA_PAGE[start:HA_PAGE.index("saved_label.configure", start)])

    def test_the_notice_uses_the_same_refit(self):
        self.assertEqual(UI_SOURCE.count("limit=lambda: settings_height_limit(primary_work_area(window)"), 1)


if __name__ == "__main__":
    unittest.main()
