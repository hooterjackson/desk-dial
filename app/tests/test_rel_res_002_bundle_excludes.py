"""REL-RES-002: the release bundle leaves out Pillow's AVIF codec, lxml.objectify/html/doctestcompare, doctest, pdb
and Tcl's tzdata. Build-Desktop.ps1 is read only (no build, no pip); the app's own modules are imported in a child
Python where the excluded modules cannot be imported, as in the frozen bundle. If a bundle built with these
exclusions is on disk it is checked too."""
from pathlib import Path
import re
import subprocess
import sys
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = ("PIL.AvifImagePlugin", "PIL._avif", "lxml.objectify", "lxml.html", "lxml.doctestcompare", "doctest", "pdb")


def build_script():
    return (ROOT / "Build-Desktop.ps1").read_text(encoding="utf-8")


def pyinstaller_line():
    return next(line for line in build_script().splitlines() if "-m PyInstaller" in line)


class BuildExcludesTests(unittest.TestCase):
    def test_every_unused_module_is_excluded(self):
        line = pyinstaller_line()
        self.assertEqual(sorted(re.findall(r"--exclude-module (\S+)", line)), sorted(EXCLUDED))
        self.assertTrue(line.rstrip().endswith(" standalone.py"), "the excludes precede the entry script")
        for kept in ("lxml.etree", "PIL.JpegImagePlugin", "unittest"):
            self.assertNotIn(f"--exclude-module {kept}", line)

    def test_tzdata_is_dropped_after_the_build_and_before_the_smoke_test(self):
        script = build_script()
        path = "$tzdata = Join-Path $distRoot 'DeskDial\\_internal\\_tcl_data\\tzdata'"
        self.assertIn(path, script)
        removal = script.index("if (Test-Path -LiteralPath $tzdata) { Remove-Item -LiteralPath $tzdata -Recurse -Force }")
        self.assertLess(script.index("if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }"), removal)
        self.assertLess(script.index(path), removal)
        self.assertLess(removal, script.index("if ($SkipSmoke) {"))
        self.assertLess(removal, script.index("-ArgumentList '--smoke-test', '--headless'"))
        # Only the build output's tzdata: nothing else is removed by the build.
        self.assertEqual(len(re.findall(r"Remove-Item", script)), 1)

    def test_the_app_runs_without_the_excluded_modules(self):
        hidden = re.findall(r"--hidden-import (control_center\.[\w.]+|windows_actions)\b", pyinstaller_line())
        self.assertIn("control_center.home_assistant", hidden)
        child = textwrap.dedent(f"""
            import importlib.abc, sys
            EXCLUDED = {EXCLUDED!r}
            class Block(importlib.abc.MetaPathFinder):
                def find_spec(self, name, path=None, target=None):
                    if any(name == bad or name.startswith(bad + ".") for bad in EXCLUDED):
                        raise ImportError("excluded from the bundle: " + name)
                    return None
            for name in EXCLUDED:
                sys.modules.pop(name, None)
            sys.meta_path.insert(0, Block())
            sys.path.insert(0, {str(ROOT)!r})
            import importlib
            for name in {hidden!r} + ["standalone", "soco", "soco.data_structures_entry", "soco.zonegroupstate",
                                      "lxml.etree", "requests"]:
                importlib.import_module(name)
            from PIL import Image
            Image.init()
            assert "JPEG" in Image.OPEN and "PNG" in Image.OPEN and "JPEG" in Image.SAVE, sorted(Image.OPEN)
            assert "AVIF" not in Image.OPEN
            import standalone
            standalone.smoke_artwork2()
            for name in EXCLUDED:
                assert name not in sys.modules, name
            print("ok")
        """)
        done = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True, timeout=300, cwd=str(ROOT),
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(done.returncode, 0, done.stderr[-3000:])
        self.assertEqual(done.stdout.strip().splitlines()[-1], "ok")

    def test_a_bundle_built_with_the_excludes_has_none_of_them(self):
        dist = re.search(r"\[string\]\$Dist = '([^']+)'", build_script()).group(1)
        internal = ROOT / dist / "DeskDial" / "_internal"
        exe = ROOT / dist / "DeskDial" / "DeskDial.exe"
        if not exe.is_file() or exe.stat().st_mtime < (ROOT / "Build-Desktop.ps1").stat().st_mtime:
            self.skipTest("no bundle built with these exclusions yet (the integration stage builds it)")
        self.assertEqual(list(internal.glob("PIL/_avif*")), [])
        self.assertEqual(list(internal.glob("lxml/objectify*")), [])
        self.assertFalse((internal / "lxml" / "html").exists())
        self.assertFalse((internal / "_tcl_data" / "tzdata").exists())
        total = sum(p.stat().st_size for p in (ROOT / dist / "DeskDial").rglob("*") if p.is_file())
        self.assertLess(total, 58 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
