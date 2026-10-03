"""DD-BUG-038 (D2 side): the simulator's speaker room, Home Assistant areas and single light carry
neutral names, never a personal room name; the scenes still belong to the simulator's first area.
Headless: no Tk, no ports, no network."""
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.simulation import (SIM_AREA_LIGHTS, SIM_AREAS, SimControls,  # noqa: E402
                                       SimulatedHomeAssistant, SimulatedSonos)

SOURCE = Path(__file__).resolve().parents[1] / "control_center" / "simulation.py"
ROOM = re.compile(r"\b(Hall|HALL)\b|[\"']hall[\"']|\bsim-hall\b")


class NeutralSimulatorTests(unittest.TestCase):
    def test_no_room_name_in_the_simulator_source(self):
        lines = SOURCE.read_text(encoding="utf-8").splitlines()
        hits = [n for n, line in enumerate(lines, 1) if ROOM.search(line)]
        self.assertEqual(hits, [])

    def test_speaker_room_is_neutral(self):
        state = SimulatedSonos(SimControls()).state
        self.assertEqual((state["room_id"], state["room_label"]), ("sim-demo", "Demo"))
        self.assertEqual(state["group_label"], "Demo · Stereo pair")

    def test_first_area_is_the_default_and_owns_the_scenes(self):
        area_id, name = SIM_AREAS[0]
        self.assertEqual((area_id, name), ("demo", "Demo"))
        self.assertEqual(sorted(SIM_AREAS)[0][0], area_id, "the first area also sorts first")
        self.assertEqual(sum(1 for _, _, area, _ in SIM_AREA_LIGHTS if area == area_id), 3)
        ha = SimulatedHomeAssistant(SimControls(), area=area_id)
        state = ha.read_state()
        self.assertEqual((state["area_id"], state["name"], state["count"]), (area_id, name, 3))

    def test_single_light_shape_is_neutral(self):
        ha = SimulatedHomeAssistant(SimControls())
        self.assertEqual(ha.light_entity, "light.demo")
        self.assertEqual(ha.read_state()["entity"], "light.demo")


if __name__ == "__main__":
    unittest.main()
