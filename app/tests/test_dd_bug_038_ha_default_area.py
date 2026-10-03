"""DD-BUG-038: the Home Assistant area picker prefers no personal room name."""
import inspect
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import home_assistant as ha  # noqa: E402


class DefaultAreaTests(unittest.TestCase):
    def test_configured_area_wins(self):
        rows = [("attic", "Attic", 0), ("hall", "Hall", 3)]
        self.assertEqual(ha.default_area(rows, "attic"), "attic")
        self.assertEqual(ha.default_area(rows, "hall"), "hall")

    def test_no_area_name_is_preferred(self):
        rows = [("attic", "Attic", 0), ("hall", "Hall", 3), ("kitchen", "Kitchen", 2)]
        self.assertEqual(ha.default_area(rows), "attic")
        self.assertEqual(ha.default_area(rows, "gone"), "attic", "an unknown configured area falls back to the first")

    def test_empty(self):
        self.assertEqual(ha.default_area([]), "")
        self.assertEqual(ha.default_area(None, "hall"), "")

    def test_no_room_literal_in_module(self):
        source = inspect.getsource(ha)
        self.assertNotIn('"Hall"', source)
        self.assertNotIn('== "hall"', source)


if __name__ == "__main__":
    unittest.main()
