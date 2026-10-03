"""DD-BUG-044 (docs): DESKTOP.md and rename-desk-dial.md describe where the installer now moves the other
name's program folder (the new home's backups\\program-<other name>-<UTC>, on the program folder's volume)
and that it moves before the other shortcut is removed. Reads text files only."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "DESKTOP.md"
RENAME = ROOT / "design-reference" / "ui-v2-analysis" / "rename-desk-dial.md"
NEW_PATH = "%LOCALAPPDATA%\\DeskDial\\backups\\program-NanoDControlCenter-<UTC>"


def flat(path):
    return " ".join(path.read_text(encoding="utf-8").split())


class DocsBackupPathTests(unittest.TestCase):
    def test_old_repository_backup_path_is_gone(self):
        for doc in (DESKTOP, RENAME):
            self.assertNotIn("desktop-program-", doc.read_text(encoding="utf-8"), doc.name)

    def test_desktop_md_names_the_home_backup_and_the_order(self):
        text = flat(DESKTOP)
        self.assertIn(NEW_PATH, text)
        self.assertIn("same volume as the program folder", text)
        move = text.index(NEW_PATH)
        self.assertLess(move, text.index("then removes its shortcut", move))
        self.assertIn("%LOCALAPPDATA%\\NanoDControlCenter\\backups\\", text)

    def test_rename_doc_names_the_home_backup_and_the_order(self):
        text = flat(RENAME)
        self.assertEqual(text.count(NEW_PATH), 2)
        for start in (i for i in range(len(text)) if text.startswith(NEW_PATH, i)):
            lnk = text.index("Nano_D++ Control Center.lnk", start)
            self.assertLess(lnk - start, 200)

    def test_docs_match_the_installer(self):
        script = (ROOT / "Install-Desktop.ps1").read_text(encoding="utf-8")
        self.assertIn('Join-Path $homeDir "backups\\program-$($other.name)-$stamp"', script)


if __name__ == "__main__":
    unittest.main()
