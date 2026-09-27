"""Static gates for the stage package (DESKTOP_STAGE §5.1 P9 / §6.6 H2, §3, §4.4, §4.7.1; WP7a's "no
behaviour change"). Reads source files only."""
import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center.stage import com  # noqa: E402
from control_center.stage import selftest  # noqa: E402

STAGE = ROOT / "control_center" / "stage"


class StaticTests(unittest.TestCase):
    def test_h2_and_safety_scan_is_clean(self):
        res = selftest.static_scan()
        self.assertEqual(res["hits"], [])

    def test_scan_catches_violations(self):
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "engine.py")
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write("import time\n"
                         "def f(h, W):\n"
                         "    time." + "sleep(0.1)\n"
                         "    W.SetFore" + "groundWindow(h)\n"
                         "    W.Show" + "Window(h, 5)\n"
                         "    period = 16" + ".7\n"
                         "    v.SetBitmapInterpolationMode(com.DCOMPOSITION_BITMAP_INTERPOLATION_MODE_NEAREST" +
                         "_NEIGHBOR)\n")
            pkg, root = os.path.join(d, "pkg"), os.path.join(d, "root")
            os.mkdir(pkg)
            os.mkdir(root)
            hits = selftest.static_scan(d, pkg, root)["hits"]
        kinds = " ".join(hits)
        for want in ("timer", "SetFore", "ShowWindow without SW_HIDE", "hard-coded period", "_NEIGHBOR passed"):
            self.assertIn(want, kinds)

    def test_nothing_outside_the_package_imports_the_stage(self):
        """WP7a changes no behaviour: no existing module imports it. The wiring is WP10's, through the
        one sanctioned wiring point ``standalone.py`` (K4 §4.1; the same rule as WP8-R11)."""
        self.assertEqual(selftest.WIRING_POINTS, ("standalone.py",))
        outside = selftest.static_scan()["outside_importers"]
        self.assertEqual([f for f in outside if f not in selftest.WIRING_POINTS], [])

    def test_the_stage_tools_run_by_path_under_isolated_mode(self):
        """The documented commands work (``python -I <path>``; ``-m`` cannot find the package under
        ``-I``): each tool puts the project root on sys.path itself (``--help`` only: nothing is
        measured, created or shown). The package docstring names the picker's modules and the same
        commands."""
        import subprocess
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
        for name in ("bench.py", "selftest.py", "picker_bench.py", "picker_selftest.py"):
            text = (STAGE / name).read_text(encoding="utf-8")
            self.assertNotIn("python -I -m control_center", text, name)
            self.assertIn(f"-I control_center\\\\stage\\\\{name}", text, name)
            p = subprocess.run([sys.executable, "-I", str(STAGE / name), "--help"], cwd=str(ROOT / "tests"), env=env,
                               capture_output=True, text=True, errors="replace", timeout=120)
            self.assertEqual(p.returncode, 0, (name, p.stderr[-800:]))
            self.assertIn("usage:", p.stdout, name)
        doc = (STAGE / "__init__.py").read_text(encoding="utf-8")
        for name in ("picker_chrome", "picker_device", "picker_testing", "picker_bench", "picker_selftest", "scenes"):
            self.assertIn(f"``{name}``", doc)
        self.assertNotIn("-m control_center.stage.selftest", doc)
        self.assertNotIn("no\nmodule outside this package imports it yet", doc)

    def test_no_tk_or_serial_imports_anywhere_in_the_stage(self):
        for p in STAGE.glob("*.py"):
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                for n in names:
                    self.assertFalse(n.split(".")[0] in ("tkinter", "serial", "soco", "requests", "urllib"),
                                     f"{p.name} imports {n}")

    def test_pure_modules_import_without_windows(self):
        """The pure layers must not load DLLs at import (the tests and the fake rely on it)."""
        for p in STAGE.glob("*.py"):
            if p.name in ("win32.py",):
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in tree.body:                              # module level only
                if isinstance(node, ast.ImportFrom) and node.module == "win32" or (
                        isinstance(node, ast.ImportFrom) and node.level == 1 and
                        any(a.name == "win32" for a in node.names)):
                    self.fail(f"{p.name} imports win32 at module level")

    def test_call_styles(self):
        """§4.7.1 with G1-1: setters and statistics reads keep the GIL; anything that can wait
        releases it."""
        py = {k for k, v in com.SLOTS.items() if v[1] == com.PY}
        wf = {k for k, v in com.SLOTS.items() if v[1] == com.WF}
        for name in ("Device.Commit", "Device.WaitForCommitCompletion", "Device.CreateVisual", "Device.CreateSurface",
                     "Device.CreateAnimation", "Surface.BeginDraw", "Surface.EndDraw", "Context.UpdateSubresource",
                     "Device1.CheckDeviceState", "Device.CreateTargetForHwnd"):
            self.assertIn(name, wf)
        for name in ("Visual.SetOffsetX", "Visual.SetOffsetX.anim", "Visual3.SetOpacity", "Animation.AddCubic",
                     "Animation.SetAbsoluteBeginTime", "Visual.AddVisual", "Device.GetFrameStatistics"):
            self.assertIn(name, py)

    def test_struct_sizes(self):
        import ctypes as C
        for struct, size in com.STRUCT_SIZES_X64.items():
            self.assertEqual(C.sizeof(struct), size, struct.__name__)

    def test_overload_order(self):
        """MSVC places the later-declared overload first (RF2 §2.3): object / animation first."""
        s = com.SLOTS
        for obj, val in (("Visual.SetOffsetX.anim", "Visual.SetOffsetX"), ("Visual.SetOffsetY.anim", "Visual.SetOffsetY"),
                         ("Visual.SetTransform.object", "Visual.SetTransform.matrix"),
                         ("Visual.SetClip.object", "Visual.SetClip.rect"),
                         ("Visual3.SetOpacity.anim", "Visual3.SetOpacity"), ("Scale.SetScaleX.anim", "Scale.SetScaleX"),
                         ("EffectGroup.SetOpacity.anim", "EffectGroup.SetOpacity")):
            self.assertEqual(s[obj][0] + 1, s[val][0], obj)


if __name__ == "__main__":
    unittest.main()
