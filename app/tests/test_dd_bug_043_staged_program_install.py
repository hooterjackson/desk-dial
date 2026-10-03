"""DD-BUG-043: the program folder is staged in <program>.new, verified there and swapped in whole, so a failed copy
leaves the previous program exactly as it was. Install-Desktop.ps1 itself is never run (review finding RN-R4: it reads
the real process list, Task Scheduler and Start menu): only the text of its Install-ProgramFolder function is copied
into a temporary script, and that runs against temporary folders only."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")


def function_text(name="Install-ProgramFolder"):
    script = (ROOT / "Install-Desktop.ps1").read_text(encoding="utf-8")
    start = script.index(f"function {name}(")
    depth, i = 0, script.index("{", start)
    for i in range(i, len(script)):
        if script[i] == "{":
            depth += 1
        elif script[i] == "}":
            depth -= 1
            if depth == 0:
                return script[start:i + 1]
    raise AssertionError("unbalanced function body")


def listing(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


class StagedInstallSourceTests(unittest.TestCase):
    def test_the_installer_installs_the_program_only_through_the_staged_function(self):
        script = (ROOT / "Install-Desktop.ps1").read_text(encoding="utf-8")
        body = function_text()
        outside = script.replace(body, "")
        self.assertIn("Install-ProgramFolder -Source $bundle -Target $install -MirrorBundle ([bool]$Mirror)", outside)
        for verb in ("Copy-Item -Destination $install", "Remove-Item -LiteralPath $stale"):
            self.assertNotIn(verb, script)
        # Staged and verified before the live folder is touched.
        self.assertLess(body.index('throw "Bundle verification failed: $relative"'),
                        body.index("Move-Item -LiteralPath $Target -Destination $previous"))
        self.assertLess(script.index("exit 0\n}"), script.index("function Install-ProgramFolder"), "never in a dry run")


@unittest.skipUnless(sys.platform == "win32" and POWERSHELL.is_file(), "Windows PowerShell")
class StagedInstallSandboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.bundle, self.live = base / "bundle" / "App", base / "Programs" / "App"
        (self.bundle / "_internal").mkdir(parents=True)
        (self.bundle / "App.exe").write_bytes(b"MZ new app")
        (self.bundle / "_internal" / "lib.dll").write_bytes(b"new lib")
        (self.bundle / "_internal" / "big.pyd").write_bytes(b"new pyd" * 1000)
        (self.live / "_internal").mkdir(parents=True)
        (self.live / "App.exe").write_bytes(b"MZ old app")
        (self.live / "_internal" / "lib.dll").write_bytes(b"old lib")
        (self.live / "_internal" / "stale.dll").write_bytes(b"only in the old bundle")

    def install(self, mirror=True, lock=None):
        base = Path(self.temp.name)
        harness = base / "harness.ps1"
        # The lock (no sharing) makes Copy-Item fail on that bundle file partway through the copy.
        held = f"[IO.File]::Open('{lock}', 'Open', 'Read', 'None')" if lock else "$null"
        lines = ["$ErrorActionPreference = 'Stop'", function_text(), f"$held = {held}", "$code = 0",
                 "try {",
                 f"    Install-ProgramFolder -Source '{self.bundle}' -Target '{self.live}' -MirrorBundle ${str(mirror).lower()}",
                 "    'installed'",
                 "} catch { 'THREW: ' + $_.Exception.Message; $code = 3 }",
                 "if ($held) { $held.Close() }", "exit $code"]
        harness.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(harness)], capture_output=True, text=True, timeout=120,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def leftovers(self):
        return sorted(p.name for p in self.live.parent.iterdir() if p.name != "App")

    def test_a_mirror_install_replaces_the_program_with_the_bundle(self):
        done = self.install()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(listing(self.live), listing(self.bundle))
        self.assertEqual(self.leftovers(), [], "no .new or .old left behind")

    def test_without_mirror_files_the_bundle_does_not_ship_stay(self):
        done = self.install(mirror=False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        want = dict(listing(self.bundle), **{"_internal\\stale.dll": hashlib.sha256(b"only in the old bundle").hexdigest()})
        self.assertEqual(listing(self.live), want)
        self.assertEqual(self.leftovers(), [])

    def test_failed_copy_leaves_previous_program_intact(self):
        before = listing(self.live)
        done = self.install(lock=self.bundle / "_internal" / "big.pyd")
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertIn("THREW:", done.stdout)
        self.assertEqual(listing(self.live), before, "the previous program folder is unchanged")
        self.assertEqual(self.leftovers(), [], "the staged copy is removed")

    def test_a_previous_program_left_in_old_is_restored_and_survives_a_failure(self):
        before = listing(self.live)
        self.live.rename(self.live.with_name("App.old"))       # a run stopped between the two renames
        done = self.install(lock=self.bundle / "App.exe")
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertEqual(listing(self.live), before)
        self.assertEqual(self.leftovers(), [])
        done = self.install()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(listing(self.live), listing(self.bundle))
        self.assertEqual(self.leftovers(), [])


if __name__ == "__main__":
    unittest.main()
