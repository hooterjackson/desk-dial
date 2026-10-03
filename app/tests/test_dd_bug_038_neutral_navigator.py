"""DD-BUG-038 (D8 side): the Navigator model's docstring and the Navigator render's lights sample
carry a neutral area name, never a personal room name. Headless: no Tk, no ports, no network."""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from control_center.stage.scenes import navigator_render as R  # noqa: E402

SOURCES = [ROOT / "control_center" / "navigator_model.py",
           ROOT / "control_center" / "stage" / "scenes" / "navigator_render.py"]
ROOM = re.compile(r"\b(Hall|HALL)\b|[\"']hall[\"']|\blight\.den\b")


class NeutralNavigatorTests(unittest.TestCase):
    def test_no_room_name_in_the_navigator_sources(self):
        for path in SOURCES:
            lines = path.read_text(encoding="utf-8").splitlines()
            hits = [n for n, line in enumerate(lines, 1) if ROOM.search(line)]
            self.assertEqual(hits, [], path.name)

    def test_lights_sample_uses_the_simulator_area_name(self):
        self.assertEqual(R._lights()["name"], "Demo")


if __name__ == "__main__":
    unittest.main()
