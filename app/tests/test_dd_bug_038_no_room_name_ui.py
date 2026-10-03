"""DD-BUG-038 (D3 side): no personal room name in the Settings / main-window sources this lane owns,
nor in the Settings copy rendered before an area is known; the simulator's Home Assistant area comes
from the simulator's own list. Headless: sources and the page model only (no Tk window, no network)."""
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import ui  # noqa: E402
from control_center.simulation import SIM_AREAS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "control_center"
OWNED = ("ui.py", "credentials.py", "paths.py", "overlay.py", "knob_face.py")
# The room name as copy ("Hall", "HALL") or as an area id; overlay.py's ctypes ("hall", ...) denominator is not one.
ROOM = re.compile(r"\b(Hall|HALL)\b|area\s*=\s*[\"']hall[\"']")


class NoRoomNameTests(unittest.TestCase):
    def test_no_literal_room_name_in_the_owned_sources(self):
        for name in OWNED:
            with self.subTest(file=name):
                hits = [n for n, line in enumerate((ROOT / name).read_text(encoding="utf-8").splitlines(), 1)
                        if ROOM.search(line)]
                self.assertEqual(hits, [], f"{name} lines {hits}")

    def test_settings_copy_before_an_area_is_known(self):
        model = ui.HaSettingsModel({})
        texts = [model.placeholder(), model.area_name(), ui.HA_CHOOSE_AREA]
        model.edit_address("http://ha.lan:8123")
        model.edit_token("typed-test-token")
        model.begin_test()
        model.finish_test({"ok": False, "outcome": "offline"}, model.generation)
        texts.append(model.placeholder())
        try:
            ui.ha_form_values("http://ha.lan:8123", "", [], token="t")
        except ValueError as error:
            texts.append(str(error))
        for text in texts:
            with self.subTest(text=text):
                self.assertIsNone(ROOM.search(text))
        self.assertEqual(model.placeholder(), "Fix the connection to see what’s in your area.")

    def test_the_speaker_field_is_neutral(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn('entry("Speaker IP"', source)

    def test_the_simulator_area_comes_from_the_simulator(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn("SimulatedHomeAssistant(controls, area=SIM_AREAS[0][0])", source)
        self.assertTrue(SIM_AREAS and SIM_AREAS[0][0])


if __name__ == "__main__":
    unittest.main()
