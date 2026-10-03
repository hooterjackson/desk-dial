"""FU-1: Settings > Knob's notes (Onshape mode, Reduced haptics, the reversed-direction note) were clipped on
the left and at the end: inside the Knob page's ScrollPage the page is narrower by the scrollbar, the notes in a
choice group lose the group's right gap as well, and a note wrapped at a fixed 540 px asked for more width than
that; Tk's packer squeezed the label and its centred text lost both ends. Now each note's wraplength follows its
container's width (track_note_wrap / note_wrap_width) and the note is left-anchored.

Headless: the layout model below is Settings' own geometry (the window width, the body's padding, the
scrollbar, the group gap); stand-in widgets replace the Label and its container; no Tk window is created."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import ui  # noqa: E402

UI_SOURCE = (Path(__file__).resolve().parents[1] / "control_center" / "ui.py").read_text(encoding="utf-8")

BODY_PADX = 24                                  # Settings' body frame (padx=24 each side)
SCROLLBAR = {1.0: 17, 1.25: 21, 1.5: 26, 2.0: 34}   # Windows' vertical scrollbar width per scaling
LABEL_CHROME = 6                                # tk.Label padx 1 + borderwidth 2, both sides


def knob_row_width(window_width=ui.SETUP_SIZE[0], scaling=1.0, scrolled=True):
    """Width of a section row on the Knob page: the host less the scrollbar while the page scrolls."""
    host = window_width - 2 * BODY_PADX
    return host - (SCROLLBAR[scaling] if scrolled else 0)


class FakeLabel:
    def __init__(self, wraplength):
        self.options = {"wraplength": wraplength, "padx": 1, "borderwidth": 2, "highlightthickness": 0,
                        "anchor": "center", "justify": "center"}

    def cget(self, option):
        return self.options[option]

    def configure(self, **options):
        self.options.update(options)

    def reqwidth(self):
        return self.options["wraplength"] + 2 * (self.options["padx"] + self.options["borderwidth"]
                                                 + self.options["highlightthickness"])


class FakeContainer:
    def __init__(self, width=1):
        self.width, self.bindings = width, {}

    def winfo_width(self):
        return self.width

    def bind(self, sequence, func, add=None):
        self.bindings.setdefault(sequence, []).append(func)

    def resize(self, width):
        self.width = width
        for func in self.bindings.get("<Configure>", []):
            func(SimpleNamespace(width=width))


class NoteWrapModelTests(unittest.TestCase):
    def test_the_fixed_wrap_did_not_fit_the_scrolled_knob_page(self):
        # The finding: at 100 % the group in a scrolled Knob page has 507 px; a 540 px wrap asks for 546.
        self.assertGreater(ui.SETUP_NOTE_WRAP + LABEL_CHROME, knob_row_width() - ui.SETTINGS_GROUP_GAP)

    def test_a_group_note_fits_its_row_at_every_scaling(self):
        for scaling in SCROLLBAR:
            for window in (ui.SETUP_SIZE[0], 616, 720, 900):
                for scrolled in (True, False):
                    row = knob_row_width(window, scaling, scrolled)
                    wrap = ui.note_wrap_width(row, ui.SETTINGS_GROUP_GAP, LABEL_CHROME)
                    with self.subTest(scaling=scaling, window=window, scrolled=scrolled):
                        self.assertLessEqual(wrap + LABEL_CHROME + ui.SETTINGS_GROUP_GAP, row, "never squeezed")
                        self.assertLessEqual(wrap, ui.SETUP_NOTE_WRAP, "never wider than the usual wrap")
                        self.assertGreaterEqual(wrap, ui.NOTE_MIN_WRAP)

    def test_a_wide_page_keeps_the_usual_wrap(self):
        self.assertEqual(ui.note_wrap_width(2000, ui.SETTINGS_GROUP_GAP), ui.SETUP_NOTE_WRAP)

    def test_an_unknown_width_keeps_the_usual_wrap(self):
        for width in (1, 0, None, "x"):
            self.assertEqual(ui.note_wrap_width(width, ui.SETTINGS_GROUP_GAP), ui.SETUP_NOTE_WRAP)

    def test_a_tiny_width_keeps_a_readable_floor(self):
        self.assertEqual(ui.note_wrap_width(120, ui.SETTINGS_GROUP_GAP), ui.NOTE_MIN_WRAP)


class TrackNoteWrapTests(unittest.TestCase):
    def test_the_note_follows_its_rows_width_and_is_left_anchored(self):
        note, row = FakeLabel(ui.SETUP_NOTE_WRAP), FakeContainer()
        self.assertIs(ui.track_note_wrap(note, row, ui.SETTINGS_GROUP_GAP), note)
        self.assertEqual((note.options["anchor"], note.options["justify"]), ("w", "left"))
        self.assertEqual(note.options["wraplength"], ui.SETUP_NOTE_WRAP, "unmapped: the usual wrap")
        for scaling in SCROLLBAR:
            width = knob_row_width(scaling=scaling)
            row.resize(width)
            with self.subTest(scaling=scaling):
                self.assertLessEqual(note.reqwidth() + ui.SETTINGS_GROUP_GAP, width)
        row.resize(knob_row_width(scrolled=False))          # the scrollbar went away: wider again
        self.assertEqual(note.reqwidth() + ui.SETTINGS_GROUP_GAP, knob_row_width(scrolled=False))

    def test_a_stand_in_container_without_add_keeps_the_fixed_wrap(self):
        class OldBind(FakeContainer):
            def bind(self, sequence, func):          # the runtime-overlay tests' stand-in signature
                raise AssertionError("not reached")
        note = FakeLabel(ui.SETUP_NOTE_WRAP)
        self.assertIs(ui.track_note_wrap(note, OldBind()), note)
        self.assertEqual(note.options["wraplength"], ui.SETUP_NOTE_WRAP)

    def test_the_chrome_is_read_from_the_label(self):
        note = FakeLabel(540)
        note.options.update(padx=4, borderwidth=0, highlightthickness=1)
        self.assertEqual(ui.label_chrome(note), 10)
        self.assertEqual(ui.label_chrome(object()), ui.NOTE_CHROME)


class KnobPageSourceTests(unittest.TestCase):
    def test_the_knob_notes_track_their_rows(self):
        for name, container in (("APPS_POINTER_NOTE", "apps_row"), ("KNOB_FEEL_NOTE", "haptics_row"),
                                ("PICKER_BACKGROUND_FALLBACK_NOTE", "switcher_row")):
            start = UI_SOURCE.index(f"{name}, 9,", UI_SOURCE.index("def segmented"))
            line_start = UI_SOURCE.rindex("\n", 0, start)
            call = UI_SOURCE[line_start:UI_SOURCE.index(".pack(", start)]
            with self.subTest(note=name):
                self.assertIn("track_note_wrap(", call)
                self.assertIn(container, call)
                self.assertIn("SETTINGS_GROUP_GAP", call)
        start = UI_SOURCE.index("DIRECTION_CHANGED_NOTE, 9,")
        self.assertIn("track_note_wrap(", UI_SOURCE[UI_SOURCE.rindex("\n", 0, start):start])

    def test_the_group_gap_is_the_one_the_notes_subtract(self):
        self.assertIn('group.pack(side="left", padx=(0, SETTINGS_GROUP_GAP))', UI_SOURCE)


if __name__ == "__main__":
    unittest.main()
