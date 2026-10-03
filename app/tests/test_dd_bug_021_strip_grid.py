"""DD-BUG-021: with the Home Assistant column the Settings strip is two rows of two, so every
column gets half of the 600 px window instead of the fourth being clipped. Stand-in widgets
(no Tk window): the layout is checked structurally and against a conservative text width."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import ui  # noqa: E402

WINDOW = ui.SETUP_SIZE[0]
PADDING = 2 * 16 + 1                 # column padx on both sides + the hairline


class Widget:
    def __init__(self, parent=None, *args, **kwargs):
        self.parent, self.values, self.packed, self.children = parent, dict(kwargs), None, []
        if isinstance(parent, Widget):
            parent.children.append(self)

    def configure(self, **kwargs):
        self.values.update(kwargs)

    def pack(self, *args, **kwargs):
        self.packed = kwargs

    def pack_forget(self):
        self.packed = None


def build(columns):
    with patch.object(ui.tk, "Frame", Widget), \
            patch.object(ui, "label", lambda parent, text, *a, **k: Widget(parent, text=text, **k)), \
            patch.object(ui, "button", lambda parent, text, command, **k: Widget(parent, text=text, command=command)):
        return ui.SettingsStrip(Widget(), {}, columns=columns)


def runtime(**lights):
    state = {"online": True, "room_label": "Room", "source": "queue", "host": ""}
    controller = SimpleNamespace(state=state, lights=SimpleNamespace(
        online=False, reason="auth", configured=True, known=True, scenes=[], name="", on=False))
    return SimpleNamespace(device_connected=False, device_supported=True, controller=controller,
                           music_signin_expired=True, apple=None, ha=SimpleNamespace(read_state=lambda: {}))


def text_px(text, points, bold=True):
    """A generous width estimate for Segoe UI at 100 % (bold average glyph ~0.62 em, 96 dpi)."""
    return len(text) * points * 96 / 72 * (0.62 if bold else 0.55)


class StripGridTests(unittest.TestCase):
    def rows(self, strip):
        return [[c for c in row.children if c.values.get("padx") == 16] for row in strip._rows]

    def test_three_columns_stay_one_row(self):
        strip = build(3)
        self.assertEqual([len(r) for r in self.rows(strip)], [3])
        self.assertEqual(strip.columns[0]["detail"].values["wraplength"], 160)

    def test_four_columns_fit_600px_as_two_rows_of_two(self):
        strip = build(4)
        self.assertEqual([len(r) for r in self.rows(strip)], [2, 2])
        self.assertIs(strip._rows[1].packed.get("before"), strip._rule, "both rows sit above the rule")
        inner = WINDOW / 2 - PADDING
        model = ui.strip_model(runtime())
        self.assertEqual(len(model), 4)
        strip.update(model)
        for column, entry in zip(strip.columns, model):
            with self.subTest(column=entry["name"]):
                self.assertLessEqual(column["detail"].values["wraplength"], inner)
                self.assertLessEqual(8 + 8 + text_px(entry["state"], 11), inner)      # mark + gap + state
                self.assertLessEqual(2 * 10 + text_px(entry["action"], 9), inner)     # button padx + text

    def test_the_app_asks_for_the_models_column_count(self):
        app = object.__new__(ui.ControlCenterApp)
        app.status_strip = lambda: [{}] * 4
        self.assertEqual(app._strip_columns(), 4)
        app.status_strip = lambda: 1 / 0
        self.assertEqual(app._strip_columns(), 3)


if __name__ == "__main__":
    unittest.main()
