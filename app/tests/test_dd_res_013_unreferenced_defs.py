"""DD-RES-013: no top-level function or class of the stage / Navigator code is dead: each name occurs
somewhere other than its own ``def`` across control_center/, standalone.py, the tests, the
design-reference generators and the tooling. Names reached by ``getattr`` dispatch are allowed (their prefixes are listed below)."""
import ast
import re
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT.parent / "tools"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# getattr dispatch prefixes (the names are built at run time, so their def is their only literal)
DISPATCH_PREFIXES = ("_press_", "_frame_", "_buttons_", "_build_", "_update_")

SCANNED = sorted([*(ROOT / "control_center" / "stage").rglob("*.py"),
                  *(ROOT / "control_center").glob("navigator*.py"),
                  *(ROOT / "control_center").glob("lcd_preview.py")])


def corpus():
    paths = [*(ROOT / "control_center").rglob("*.py"), *(ROOT / "tests").rglob("*.py"), *ROOT.glob("*.py"),
             *(ROOT / "design-reference").rglob("*.py")]
    if WORK.is_dir():
        paths += [*WORK.glob("*.py"), *(WORK / "probes").glob("*.py"), *(WORK / "stage_checks").glob("*.py")]
    counts = {}
    for p in paths:
        if "__pycache__" in p.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", text):
            counts[m.group()] = counts.get(m.group(), 0) + 1
    return counts


class UnreferencedDefs(unittest.TestCase):
    def test_no_unreferenced_top_level_defs(self):
        self.assertTrue(SCANNED)
        counts = corpus()
        dead = []
        for path in SCANNED:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                name = node.name
                if name.startswith("__") or name.startswith(DISPATCH_PREFIXES):
                    continue
                if counts.get(name, 0) <= 1:
                    dead.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno} {name}")
        self.assertEqual(dead, [], "unreferenced top-level defs")

    def test_design_reference_stage_attributes_exist(self):
        """Every ``R.<name>`` a design-reference generator reads from a stage module it imports
        ``as R`` (or any alias) still exists there, so a cleanup cannot break the generators."""
        import importlib
        checked = 0
        missing = []
        for path in sorted((ROOT / "design-reference").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            aliases = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("control_center"):
                    for a in node.names:
                        aliases[a.asname or a.name] = f"{node.module}.{a.name}"
            if not aliases:
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                        and node.value.id in aliases):
                    target = aliases[node.value.id]
                    parent, _, leaf = target.rpartition(".")
                    mod = getattr(importlib.import_module(parent), leaf, None)
                    if mod is None:
                        mod = importlib.import_module(target)
                    if not isinstance(mod, types.ModuleType):
                        continue  # an imported function or class, not a module
                    checked += 1
                    if not hasattr(mod, node.attr):
                        missing.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno} {target}.{node.attr}")
        self.assertGreater(checked, 0)
        self.assertEqual(missing, [], "design-reference reads names its stage module no longer has")


if __name__ == "__main__":
    unittest.main()
