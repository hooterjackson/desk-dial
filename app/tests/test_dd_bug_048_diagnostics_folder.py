"""DD-BUG-048: diagnostics\\ is gitignored, so a fresh checkout has no such folder. The installer creates it before
any check (the dry run's plan and every report go there) and Install-UserData.ps1 creates its report's folder
before the first write. Install-Desktop.ps1 is read only (never run by a test, review finding RN-R4);
Install-UserData.ps1 runs for real against a temporary folder only."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")


class InstallerCreatesDiagnosticsTests(unittest.TestCase):
    def test_diagnostics_is_not_part_of_a_fresh_checkout(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertTrue(any(line.strip().rstrip("/") == "diagnostics" for line in ignored), ignored)

    def test_the_installer_creates_diagnostics_before_any_check_or_write(self):
        script = (ROOT / "Install-Desktop.ps1").read_text(encoding="utf-8")
        create = script.index("New-Item -ItemType Directory -Path $diagnostics -Force | Out-Null")
        self.assertLess(script.index("$diagnostics = Join-Path $PSScriptRoot 'diagnostics'"), create)
        for later in ("# Checks, in this order, before anything changes.", "if ($DryRun) {\n    # Names and sizes only",
                      "Set-Content -LiteralPath $planPath", "Invoke-UserDataStep 'install' (Join-Path $diagnostics",
                      "(Join-Path $diagnostics 'desktop-startup-task.xml')"):
            with self.subTest(after=later):
                self.assertLess(create, script.index(later))
        # Every use of the folder comes after it is created.
        uses = [i for i in range(len(script)) if script.startswith("Join-Path $diagnostics", i)]
        self.assertTrue(uses)
        self.assertGreater(min(uses), create)


@unittest.skipUnless(sys.platform == "win32" and POWERSHELL.is_file(), "Windows PowerShell")
class UserDataReportFolderTests(unittest.TestCase):
    def run_step(self, plan, report, step):
        return subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(ROOT / "Install-UserData.ps1"), "-Plan", str(plan), "-Step", step,
                               "-Report", str(report)], capture_output=True, text=True, timeout=120,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def test_cleanup_writes_its_report_into_a_missing_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            plan = base / "install-step.json"
            plan.write_text(json.dumps({"otherShortcut": str(base / "menu" / "Old.lnk"),
                                        "otherProgram": str(base / "programs" / "old-app"),
                                        "programBackup": str(base / "backups" / "old")}), encoding="utf-8")
            report = base / "diagnostics" / "desktop-install-cleanup.json"
            self.assertFalse(report.parent.exists())
            done = self.run_step(plan, report, "cleanup")
            self.assertEqual(done.returncode, 0, done.stderr)
            result = json.loads(report.read_text(encoding="utf-8-sig"))
            self.assertEqual((result["passed"], result["step"]), (True, "cleanup"))

    def test_a_failure_is_still_reported_into_a_missing_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            report = base / "diagnostics" / "nested" / "desktop-user-data.json"
            done = self.run_step(base / "no-such-plan.json", report, "install")
            self.assertEqual(done.returncode, 1, done.stderr)
            result = json.loads(report.read_text(encoding="utf-8-sig"))
            self.assertEqual((result["passed"], result["stage"]), (False, "plan"))


if __name__ == "__main__":
    unittest.main()
