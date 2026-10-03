"""FU-3: the Apple Team ID field in Settings > Music starts empty. No Team ID-shaped literal (10 characters,
uppercase letters and digits mixed) is shipped anywhere in the app source. Source scan only; no Tk."""
import re
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "control_center"
UI_SOURCE = (PACKAGE / "ui.py").read_text(encoding="utf-8")
# A quoted 10-character run of A-Z / 0-9 with at least one letter and one digit (the Team ID shape).
TEAM_ID_LITERAL = re.compile(r"""["'](?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*[0-9])[A-Z0-9]{10}["']""")


class TeamIdDefaultTests(unittest.TestCase):
    def test_the_team_id_entry_has_no_default(self):
        lines = [line for line in UI_SOURCE.splitlines() if 'entry("Apple Team ID"' in line]
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r'entry\("Apple Team ID", parent=pages\["music"\]\)')

    def test_no_team_id_shaped_literal_in_the_app_source(self):
        hits = []
        for path in sorted(PACKAGE.rglob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if TEAM_ID_LITERAL.search(line):
                    hits.append(f"{path.name}:{number}")
        self.assertEqual(hits, [], "a pre-filled Apple Team ID would ship the author's own")

    def test_the_pattern_catches_a_team_id_shape(self):
        self.assertTrue(TEAM_ID_LITERAL.search('entry("Apple Team ID", "AB12CD34EF")'))
        self.assertFalse(TEAM_ID_LITERAL.search('"FAVOURITES" "0123456789" "AUTOMATION"'))


if __name__ == "__main__":
    unittest.main()
