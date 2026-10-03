"""DD-BUG-044: retiring the other name's program folder must not depend on the repository's drive.

Windows PowerShell 5.1 cannot move a directory across volumes, so the planned backup now sits in the new
identity's home under %LOCALAPPDATA% (the program folder's own volume), and the cleanup step moves the folder
before it removes the shortcut: a failed move leaves the other install whole. Install-Desktop.ps1 is read only
(never run by a test); Install-UserData.ps1 runs for real against a temporary folder only."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")


class PlannedBackupTests(unittest.TestCase):
    def test_backup_is_planned_in_the_home_not_the_repository(self):
        script = (ROOT / "Install-Desktop.ps1").read_text(encoding="utf-8")
        line = re.search(r"^\$programBackup = (.+)$", script, re.M).group(1)
        self.assertTrue(line.startswith("Join-Path $homeDir "), line)
        self.assertNotIn("$PSScriptRoot", line)
        # $homeDir is under %LOCALAPPDATA%, like the program folder it receives.
        self.assertIn("$homeDir = Join-Path $env:LOCALAPPDATA $id.home", script)
        self.assertIn("$otherInstall = Join-Path $env:LOCALAPPDATA $other.program", script)
        self.assertLess(script.index("$homeDir = Join-Path"), script.index("$programBackup = "))

    def test_cleanup_moves_the_folder_before_removing_the_shortcut(self):
        script = (ROOT / "Install-UserData.ps1").read_text(encoding="utf-8")
        cleanup = script[script.index("if ($Step -eq 'cleanup')"):script.index("step = 'cleanup'")]
        self.assertLess(cleanup.index("Move-Item -LiteralPath $p.otherProgram"),
                        cleanup.index("Remove-Item -LiteralPath $p.otherShortcut"))


@unittest.skipUnless(sys.platform == "win32" and POWERSHELL.is_file(), "Windows PowerShell")
class CleanupStepTests(unittest.TestCase):
    def run_cleanup(self, base, backup):
        menu = base / "menu"
        menu.mkdir()
        shortcut = menu / "Old.lnk"
        shortcut.write_bytes(b"lnk")
        program = base / "programs" / "old-app"
        program.mkdir(parents=True)
        (program / "Old.exe").write_bytes(b"exe")
        plan = base / "install-step.json"
        plan.write_text(json.dumps({"otherShortcut": str(shortcut), "otherProgram": str(program),
                                    "programBackup": str(backup)}), encoding="utf-8")
        report = base / "diagnostics" / "desktop-install-cleanup.json"
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(ROOT / "Install-UserData.ps1"), "-Plan", str(plan), "-Step", "cleanup",
                               "-Report", str(report)], capture_output=True, text=True, timeout=120,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return done, json.loads(report.read_text(encoding="utf-8-sig")), shortcut, program

    def test_same_volume_backup_moves_then_removes_shortcut(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            backup = base / "home" / "backups" / "program-Old-20260101T000000Z"
            done, result, shortcut, program = self.run_cleanup(base, backup)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual((result["passed"], result["shortcutRemoved"]), (True, True))
            self.assertFalse(program.exists())
            self.assertTrue((backup / "Old.exe").is_file())
            self.assertFalse(shortcut.exists())

    def test_backup_on_another_volume_leaves_the_other_install_whole(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            here = base.drive.upper()
            letter = next(c for c in "QRSTUVWXYZ" if f"{c}:" != here)
            backup = Path(f"{letter}:\\deskdial-test-backups\\program-Old")
            done, result, shortcut, program = self.run_cleanup(base, backup)
            self.assertEqual(done.returncode, 1, done.stderr)
            self.assertEqual((result["passed"], result["stage"]), (False, "program"))
            self.assertIn("same volume", result["detail"])
            # Nothing of the other install was touched: folder and shortcut both stay.
            self.assertTrue((program / "Old.exe").is_file())
            self.assertTrue(shortcut.is_file())


if __name__ == "__main__":
    unittest.main()
