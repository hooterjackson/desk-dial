"""DD-BUG-020: Settings > Knob no longer clips its sounds row, volume slider and Recalibrate on a
short work area (100-150 % scaling): the page scrolls (ScrollPage) and Settings never grows past
the work area (refit_height's limit, settings_height_limit). Headless: stand-in widgets replace
tkinter's Frame / Canvas / Scrollbar, and a stand-in Wm window; no Tk window is created."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tkinter as tk  # noqa: E402

from control_center import ui  # noqa: E402

UI_SOURCE = (Path(__file__).resolve().parents[1] / "control_center" / "ui.py").read_text(encoding="utf-8")


class FakeWidget:
    def __init__(self, master=None, **options):
        self.master = master
        self.options = dict(options)
        self.bindings = {}
        self.packed = False
        self.pack_options = None
        self.reqheight = 1
        self.height = 1
        self.width = 1
        self.rooty = 0
        self.mapped = True

    def bind(self, sequence, func, add=None):
        self.bindings.setdefault(sequence, []).append(func)

    def pack(self, **options):
        self.packed, self.pack_options = True, options

    def pack_forget(self):
        self.packed = False

    def configure(self, **options):
        self.options.update(options)

    config = configure

    def winfo_toplevel(self):
        return TOP

    def winfo_reqheight(self):
        return self.reqheight

    def winfo_height(self):
        return self.height

    def winfo_width(self):
        return self.width

    def winfo_rooty(self):
        return self.rooty

    def winfo_ismapped(self):
        return self.mapped


class FakeCanvas(FakeWidget):
    def __init__(self, master=None, **options):
        super().__init__(master, **options)
        self.first = 0.0
        self.items, self.scrolls = {}, []

    def create_window(self, x, y, **options):
        self.items[1] = dict(options)
        return 1

    def itemconfigure(self, item, **options):
        self.items[item].update(options)

    def yview(self, *args):
        return (self.first, min(1.0, self.first + self.height / max(1, self.inner_height())))

    def inner_height(self):
        return self.items[1]["window"].reqheight

    def yview_scroll(self, number, what):
        self.scrolls.append((number, what))

    def yview_moveto(self, fraction):
        self.first = float(fraction)


class FakeScrollbar(FakeWidget):
    def set(self, *args):
        pass


TOP = FakeWidget()


def make_page():
    TOP.bindings.clear()
    with patch.object(ui.tk, "Frame", FakeWidget), patch.object(ui.tk, "Canvas", FakeCanvas), \
            patch.object(ui.tk, "Scrollbar", FakeScrollbar):
        return ui.ScrollPage(FakeWidget(), "#000000")


# The Knob page's modelled need at 100 % (the finding's 1216 px) and the rows that were clipped. The last row was
# Recalibrate motor; since D-RECAL (v2.0.0, ui.SHOW_RECALIBRATE = False) it is hidden and the model's last row
# stands for whichever row ends the page: the scroll geometry is the same.
KNOB_NEED_100 = 1216
SLIDER_ROW_100 = (930, 990)          # the sounds row with the volume slider
LAST_ROW_100 = (1170, 1216)          # the last row of the page


class SettingsKnobPageFitTests(unittest.TestCase):
    def test_volume_slider_and_last_row_visible_at_1000px(self):
        for scaling in (1.33, 2.0):
            factor = scaling / 1.3333
            need = int(KNOB_NEED_100 * factor)
            view = 1000 - 260                 # 600x1000: the strip, page list, note and Save take the rest
            page = make_page()
            page.inner.reqheight = need
            page.canvas.width, page.canvas.height = 552, view
            page._sync()
            self.assertEqual(page.canvas.options["height"], need, "asks for every row (grows when it can)")
            self.assertEqual(page.canvas.options["scrollregion"], (0, 0, 552, need), "every row is reachable")
            self.assertTrue(page.bar.packed, f"scrollbar shown at scaling {scaling}")
            self.assertEqual(page.canvas.items[1]["width"], 552)
            for top, bottom in (SLIDER_ROW_100, LAST_ROW_100):
                top, bottom = int(top * factor), int(bottom * factor)
                widget = SimpleNamespace(winfo_rooty=lambda top=top: top, winfo_height=lambda h=bottom - top: h)
                page.see(widget)
                first_px = page.canvas.first * need
                self.assertLessEqual(first_px, top + 1e-6)
                self.assertGreaterEqual(first_px + view, bottom - 1e-6, f"row fully visible at {scaling}")

    def test_wheel_scrolls_only_while_shown_and_needed(self):
        page = make_page()
        wheel = TOP.bindings["<MouseWheel>"][0]
        page.inner.reqheight, page.canvas.width, page.canvas.height = 1216, 552, 700
        page._sync()
        self.assertEqual(wheel(SimpleNamespace(delta=-120)), "break")
        self.assertEqual(page.canvas.scrolls, [(ui.ScrollPage.WHEEL_UNITS, "units")])
        page.outer.mapped = False                 # another page is shown
        self.assertIsNone(wheel(SimpleNamespace(delta=-120)))
        self.assertEqual(len(page.canvas.scrolls), 1)

    def test_scrollbar_hides_when_everything_fits(self):
        page = make_page()
        page.inner.reqheight, page.canvas.width, page.canvas.height = 1216, 552, 700
        page._sync()
        self.assertTrue(page.bar.packed)
        page.canvas.first = 0.4
        page.canvas.height = 1300
        page._sync()
        self.assertFalse(page.bar.packed)
        self.assertEqual(page.canvas.first, 0.0, "back at the top")

    def test_scroll_fraction_math(self):
        self.assertIsNone(ui.scroll_fraction_for(10, 50, 500, 600, 0.0), "nothing scrolls")
        self.assertIsNone(ui.scroll_fraction_for(10, 50, 1000, 400, 0.0), "already visible")
        self.assertAlmostEqual(ui.scroll_fraction_for(900, 950, 1000, 400, 0.0), 0.55)
        self.assertAlmostEqual(ui.scroll_fraction_for(100, 150, 1000, 400, 0.5), 0.1)
        self.assertAlmostEqual(ui.scroll_fraction_for(990, 1100, 1000, 400, 0.0), 0.6, msg="clamped to the end")

    def test_without_a_canvas_the_rows_go_in_the_page_frame(self):
        def no_canvas(*args, **kwargs):
            raise AttributeError("a stand-in parent has no tk")
        with patch.object(ui.tk, "Frame", FakeWidget), patch.object(ui.tk, "Canvas", no_canvas):
            page = ui.ScrollPage(FakeWidget(), "#000000")
        self.assertIs(page.inner, page.outer)
        self.assertFalse(page.scrollable())
        page._sync()
        page.see(SimpleNamespace())

    def test_the_knob_page_is_built_in_a_scroll_page(self):
        self.assertIn('scrollers[key] = ScrollPage(host, BG)', UI_SOURCE)
        self.assertIn('shells[key], pages[key] = scrollers[key].outer, scrollers[key].inner', UI_SOURCE)
        self.assertNotIn("pages[current[0]].pack_forget()", UI_SOURCE)


class FakeWm(tk.Wm):
    """A stand-in top-level for fit_height / refit_height (no Tk)."""
    def __init__(self, reqheight, screen, mapped=(600, 850)):
        self.reqheight, self.screen, self.size, self.geometries = reqheight, screen, mapped, []

    def update_idletasks(self):
        pass

    def winfo_reqheight(self):
        return self.reqheight

    def winfo_screenheight(self):
        return self.screen

    def winfo_ismapped(self):
        return True

    def winfo_width(self):
        return self.size[0]

    def winfo_height(self):
        return self.size[1]

    def geometry(self, spec=None):
        self.geometries.append(spec)


class WorkAreaClampTests(unittest.TestCase):
    def test_limit_is_the_work_area_room(self):
        self.assertEqual(ui.settings_height_limit((0, 0, 1920, 1020), (20, 49)), 971)
        self.assertEqual(ui.settings_height_limit((0, 0, 800, 300), (0, 30)), ui.SETTINGS_MIN_HEIGHT)
        self.assertIsNone(ui.settings_height_limit(None))

    def test_refit_never_grows_past_the_work_area(self):
        # 1080p at 125 %: screen - 80 = 1000, but the work area leaves 971 px of client height.
        window = FakeWm(reqheight=1400, screen=1080)
        size = [600, 850]
        limit = ui.settings_height_limit((0, 0, 1920, 1020), (20, 49))
        self.assertEqual(ui.refit_height(window, size, limit=lambda: limit), 971)
        self.assertEqual(window.geometries, ["600x971"])
        self.assertEqual(size, [600, 971])

    def test_refit_without_limit_is_unchanged(self):
        window = FakeWm(reqheight=1400, screen=1080)
        self.assertEqual(ui.refit_height(window, [600, 850]), 1000)

    def test_a_failing_limit_falls_back_to_the_screen_cap(self):
        def broken():
            raise OSError("no work area")
        window = FakeWm(reqheight=1400, screen=1080)
        self.assertEqual(ui.refit_height(window, [600, 850], limit=broken), 1000)

    def test_settings_refits_pass_the_limit(self):
        self.assertIn("refit_height(win, fitted, limit=height_limit)", UI_SOURCE)
        self.assertNotIn("refit_height(win, fitted)\n", UI_SOURCE)


if __name__ == "__main__":
    unittest.main()
