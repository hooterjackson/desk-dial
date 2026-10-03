"""DD-RES-013: the unreferenced compat property Runtime._pending_tap is gone; the pending-tap state
lives only in Runtime._pending_taps (read by held_for / _release_tap)."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "control_center" / "runtime.py"


def runtime_class():
    tree = ast.parse(RUNTIME.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Runtime":
            return node
    raise AssertionError("class Runtime not found")


class PendingTapCompatRemoved(unittest.TestCase):
    def test_compat_property_removed(self):
        names = {n.name for n in runtime_class().body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertNotIn("_pending_tap", names)
        self.assertIn("held_for", names)
        self.assertIn("_release_tap", names)

    def test_no_reader_of_singular_name(self):
        hits = []
        paths = [*(ROOT / "control_center").rglob("*.py"), *(ROOT / "tests").rglob("*.py"), *ROOT.glob("*.py")]
        for p in paths:
            if "__pycache__" in p.parts or p.resolve() == Path(__file__).resolve():
                continue
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                stripped = line.replace("_pending_taps", "")
                if "_pending_tap" in stripped:
                    hits.append(f"{p.relative_to(ROOT).as_posix()}:{i}")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
