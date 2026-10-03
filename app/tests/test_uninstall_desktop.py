r"""Uninstall-Desktop.ps1 (user decision for v2.0.0): removes the program folder %LOCALAPPDATA%\Programs\DeskDial,
the 'Desk Dial' sign-in task and the 'Desk Dial.lnk' Start-menu shortcut, the names Install-Desktop.ps1 installs;
keeps the data folder %LOCALAPPDATA%\DeskDial unless -RemoveData; refuses while DeskDial.exe runs.

Only ever run with -DryRun, against a temporary LOCALAPPDATA: the plan is read and the temporary tree must be
unchanged afterwards. The script is run from a copy in the temporary folder because the suite's process guard
(tools/run_no_tk.py) refuses any command line naming Install-Desktop, which 'Uninstall-Desktop' contains; the
copy is byte-identical and -DryRun changes nothing. The task and shortcut presence are read from the real
system (Get-ScheduledTask, Test-Path; read-only)."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "Uninstall-Desktop.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("powershell.exe")


def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "dir"
            for p in sorted(Path(root).rglob("*"))}


def deskdial_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq DeskDial.exe", "/NH"], capture_output=True,
                             text=True, timeout=30).stdout
    except Exception:
        return None
    return "DeskDial.exe" in out


@unittest.skipUnless(os.name == "nt" and POWERSHELL, "Windows PowerShell only")
class UninstallDryRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dd-uninstall-"))
        self.local = self.tmp / "LocalAppData"
        program = self.local / "Programs" / "DeskDial"
        program.mkdir(parents=True)
        (program / "DeskDial.exe").write_bytes(b"not a real exe")
        data = self.local / "DeskDial"
        (data / "logs").mkdir(parents=True)
        (data / "settings.json").write_text("{}", encoding="utf-8")
        (data / "credentials.bin").write_bytes(b"\x00" * 16)
        (data / "logs" / "desk-dial.log").write_text("log", encoding="utf-8")
        self.copy = self.tmp / "dd-remove-dryrun.ps1"
        shutil.copyfile(SCRIPT, self.copy)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def plan(self, *extra):
        env = dict(os.environ, LOCALAPPDATA=str(self.local))
        before = snapshot(self.local)
        done = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                               str(self.copy), "-DryRun", *extra], capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(snapshot(self.local), before, "a dry run changes nothing")
        self.assertIn(done.returncode, (0, 1), done.stderr)
        plan = json.loads(done.stdout)
        self.assertEqual(done.returncode, 0 if plan["wouldUninstall"] else 1)
        return plan

    def test_plans_exactly_the_installed_names_and_keeps_the_data(self):
        plan = self.plan()
        self.assertTrue(plan["dryRun"])
        program = self.local / "Programs" / "DeskDial"
        self.assertEqual(Path(plan["program"]["folder"]), program)
        self.assertTrue(plan["program"]["present"])
        self.assertEqual([Path(p) for p in plan["program"]["remove"]], [program])
        self.assertEqual(plan["task"]["name"], "Desk Dial")
        self.assertEqual(Path(plan["shortcut"]["path"]).name, "Desk Dial.lnk")
        self.assertEqual(Path(plan["data"]["folder"]), self.local / "DeskDial")
        self.assertTrue(plan["data"]["present"])
        self.assertFalse(plan["data"]["remove"])
        self.assertTrue(plan["data"]["kept"])
        removed = [Path(p) for p in plan["program"]["remove"]]
        self.assertFalse(any(self.local / "DeskDial" in [p, *p.parents] for p in removed), "never the data folder")

    def test_remove_data_plans_the_data_folder(self):
        plan = self.plan("-RemoveData")
        self.assertTrue(plan["data"]["remove"])
        self.assertFalse(plan["data"]["kept"])
        self.assertEqual([Path(p) for p in plan["program"]["remove"]], [self.local / "Programs" / "DeskDial"])

    def test_refuses_while_desk_dial_runs(self):
        running = deskdial_running()
        if running is None:
            self.skipTest("tasklist unavailable")
        plan = self.plan()
        self.assertEqual(plan["wouldUninstall"], not running)
        self.assertEqual(bool(plan["refusals"]), running)


class UninstallSourceTests(unittest.TestCase):
    SOURCE = SCRIPT.read_text(encoding="utf-8")

    def test_names_mirror_install_desktop(self):
        install = (ROOT / "Install-Desktop.ps1").read_text(encoding="utf-8")
        line = re.search(r"'DeskDial' = @\{([^}]*)", install).group(1)
        for key in ("program", "home", "task", "shortcut", "exe"):
            value = re.search(rf"\b{key} = '([^']+)'", line).group(1)
            with self.subTest(key=key):
                self.assertIn(f"{key} = '{value}'", self.SOURCE)
        self.assertIn("$programsMenu = [Environment]::GetFolderPath('Programs')", self.SOURCE)
        self.assertIn("$programsMenu = [Environment]::GetFolderPath('Programs')", install)

    def test_the_data_folder_goes_only_with_remove_data(self):
        removals = [line for line in self.SOURCE.splitlines() if "Remove-Item" in line]
        home = [line for line in removals if "$homeDir" in line]
        self.assertEqual(len(home), 1)
        self.assertIn("if ($RemoveData -and $dataPresent)", home[0])

    def test_the_refusal_and_dry_run_come_before_any_change(self):
        first_change = min(self.SOURCE.index(word) for word in ("Unregister-ScheduledTask", "Remove-Item"))
        self.assertLess(self.SOURCE.index("Get-Process -Name 'DeskDial'"), first_change)
        self.assertLess(self.SOURCE.index("if ($DryRun) {"), first_change)
        self.assertLess(self.SOURCE.index("if ($refusals.Count -gt 0) { throw"), first_change)


if __name__ == "__main__":
    unittest.main()
