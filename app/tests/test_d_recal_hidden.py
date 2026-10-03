"""D-RECAL (user decision for v2.0.0): Settings > Knob does not show Recalibrate motor, because recalibration has
never been rehearsed on hardware. The UI is gated behind ui.SHOW_RECALIBRATE = False; the guard
(RecalibrationGuard, DD-BUG-051), Runtime.recalibrate_motor and the device's recalibrate command stay and keep
their own tests. Reads ui.py's syntax tree only; no Tk window is created."""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from control_center import device, runtime, ui  # noqa: E402

UI_SOURCE = (ROOT / "control_center" / "ui.py").read_text(encoding="utf-8")
TREE = ast.parse(UI_SOURCE)


def gates():
    return [node for node in ast.walk(TREE)
            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "SHOW_RECALIBRATE"]


def string_constants(nodes):
    return {n.value for node in nodes for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


class RecalibrateHiddenTests(unittest.TestCase):
    def test_the_gate_is_off_for_v2_0_0(self):
        self.assertIs(ui.SHOW_RECALIBRATE, False)

    def test_the_button_and_its_direction_row_are_built_only_behind_the_gate(self):
        found = gates()
        self.assertEqual(len(found), 1, "one gate on the Knob page")
        inside = string_constants(found[0].body)
        for text in ("Recalibrate motor", "Keep new direction", "Dismiss"):
            self.assertIn(text, inside)
        # Nowhere else in ui.py is a "Recalibrate motor" button built.
        outside = [n for n in ast.walk(TREE) if isinstance(n, ast.Call) and any(
            isinstance(a, ast.Constant) and a.value == "Recalibrate motor" for a in n.args)]
        inside_calls = [n for n in ast.walk(found[0]) if isinstance(n, ast.Call) and any(
            isinstance(a, ast.Constant) and a.value == "Recalibrate motor" for a in n.args)]
        self.assertEqual(len(outside), len(inside_calls))

    def test_hidden_leaves_no_refresher_for_the_settings_tick(self):
        orelse = gates()[0].orelse
        self.assertTrue(orelse)
        self.assertIn("self._setup_refresh_recal = None", ast.unparse(orelse[0]))

    def test_the_code_path_stays(self):
        self.assertTrue(callable(ui.RecalibrationGuard))
        self.assertTrue(callable(runtime.Runtime.recalibrate_motor))
        self.assertTrue(callable(device.recalibration_capability))
        self.assertIn("recalibrate", (ROOT / "control_center" / "device.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
