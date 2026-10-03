"""DD-BUG-038 (D1 side): the controller's speaker label before the first music update, and its
fallbacks, are a neutral 'Speaker', never a personal room name. Headless: no Tk, no ports, no network."""
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.controller import Controller  # noqa: E402

SOURCE = Path(__file__).resolve().parents[1] / "control_center" / "controller.py"
ROOM = re.compile(r"\b(Hall|HALL)\b")


class ControllerNeutralLabelTests(unittest.TestCase):
    def test_default_group_label_is_neutral(self):
        controller = Controller(clock=lambda: 0.0)
        self.assertEqual(controller.state["group_label"], "Speaker")
        self.assertEqual(controller._target(), "Speaker")

    def test_fallbacks_when_labels_are_missing(self):
        controller = Controller(clock=lambda: 0.0)
        controller.state.pop("group_label", None)
        self.assertEqual(controller._target(), "Speaker")
        controller.state["group_room_count"] = 3
        controller.state.pop("room_label", None)
        self.assertEqual(controller._target(), "Speaker + 2 rooms")

    def test_known_labels_still_win(self):
        controller = Controller(clock=lambda: 0.0)
        controller.state.update(group_label="Kitchen", room_label="Kitchen", group_room_count=2)
        self.assertEqual(controller._target(), "Kitchen + 1 room")

    def test_no_room_name_in_the_controller_source(self):
        lines = SOURCE.read_text(encoding="utf-8").splitlines()
        hits = [n for n, line in enumerate(lines, 1) if ROOM.search(line)]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
