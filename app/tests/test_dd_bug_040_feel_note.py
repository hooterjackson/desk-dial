"""DD-BUG-040: Settings > Knob's feel note matches ID-SOUND-ALL (every interaction has a sound and a
haptic): it never tells users that values, walls or fluid turns are silent. Headless."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import ui  # noqa: E402


class KnobCopyTests(unittest.TestCase):
    def test_feel_note_matches_sound_all(self):
        note = ui.KNOB_FEEL_NOTE.lower()
        self.assertNotIn("silent", note)
        self.assertNotIn("silence", note)
        for word in ("turn", "wall", "press", "sound", "haptic", "volume"):
            self.assertIn(word, note)

    def test_reduced_haptics_copy_is_kept(self):
        self.assertIn("Reduced haptics", ui.KNOB_FEEL_NOTE)
        self.assertIn("the ends still stop the knob", ui.KNOB_FEEL_NOTE)


if __name__ == "__main__":
    unittest.main()
