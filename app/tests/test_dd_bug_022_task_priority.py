"""DD-BUG-022: the sign-in task is registered at normal priority (Task Scheduler's default, 7, starts the process
BELOW_NORMAL). Install-Desktop.ps1 is read only (never run by a test, review finding RN-R4); the settings object is
built in a separate PowerShell, never registered."""
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")


class StartupTaskPriorityTests(unittest.TestCase):
    def test_startup_task_runs_at_normal_priority(self):
        script = (ROOT / "Install-Desktop.ps1").read_text(encoding="utf-8")
        line = next(l for l in script.splitlines() if l.startswith("$settings = New-ScheduledTaskSettingsSet"))
        self.assertRegex(line, r"\s-Priority 4\s")
        # That settings object is the one the sign-in task is registered with.
        register = next(l for l in script.splitlines() if l.startswith("Register-ScheduledTask -TaskName $id.task"))
        self.assertIn("-Settings $settings", register)
        self.assertLess(script.index(line), script.index(register))

    @unittest.skipUnless(sys.platform == "win32" and POWERSHELL.is_file(), "Windows PowerShell")
    def test_the_cmdlet_default_is_below_normal_and_4_is_normal(self):
        command = ("(New-ScheduledTaskSettingsSet).Priority; (New-ScheduledTaskSettingsSet -Priority 4).Priority")
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", command],
                              capture_output=True, text=True, timeout=120,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(re.findall(r"\d+", done.stdout), ["7", "4"])


if __name__ == "__main__":
    unittest.main()
