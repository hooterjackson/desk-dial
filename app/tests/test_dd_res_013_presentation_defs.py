"""DD-RES-013: control_center/presentation.py carries no dead helpers or constants. Every top-level
function, class and module constant it defines occurs somewhere other than its own definition across
control_center/, standalone.py, the tests, the design-reference generators and the tooling.
The deleted names (list_slot, volume_segment, the presentation-only volume_steps, LAYOUT_DOWNGRADE,
QUEUE_RING_STYLES, MARKER_RING_STYLES) were mirrored by no contract test or firmware source."""
import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT.parent / "tools"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PRESENTATION = ROOT / "control_center" / "presentation.py"
DELETED = ("list_slot", "volume_segment", "volume_steps", "LAYOUT_DOWNGRADE", "QUEUE_RING_STYLES",
           "MARKER_RING_STYLES")


def corpus():
    paths = [*(ROOT / "control_center").rglob("*.py"), *(ROOT / "tests").rglob("*.py"), *ROOT.glob("*.py"),
             *(ROOT / "design-reference").rglob("*.py")]
    if WORK.is_dir():
        paths += [*WORK.glob("*.py"), *(WORK / "probes").glob("*.py"), *(WORK / "stage_checks").glob("*.py")]
    this = Path(__file__).resolve()
    counts = {}
    for p in paths:
        if "__pycache__" in p.parts or p.resolve() == this:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", text):
            counts[m.group()] = counts.get(m.group(), 0) + 1
    return counts


def top_level_names(tree):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node.lineno, node.name
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        yield node.lineno, n.id


class PresentationDefs(unittest.TestCase):
    def test_no_unreferenced_presentation_names(self):
        counts = corpus()
        tree = ast.parse(PRESENTATION.read_text(encoding="utf-8"))
        dead = [f"presentation.py:{line} {name}" for line, name in top_level_names(tree)
                if not name.startswith("__") and counts.get(name, 0) <= 1]
        self.assertEqual(dead, [], "unreferenced top-level names in presentation.py")

    def test_deleted_names_are_gone(self):
        from control_center import presentation
        for name in DELETED:
            self.assertFalse(hasattr(presentation, name), name)

    def test_kept_neighbours_still_hold(self):
        from control_center import presentation as P
        self.assertIn("queue", P.RING_STYLES_V6)
        self.assertIn("marker", P.RING_STYLES_V6)
        self.assertEqual(P.LAYOUT_DOWNGRADE_V6["lights"], "recent")
        self.assertEqual(P.VOLUME_END, 25)


if __name__ == "__main__":
    unittest.main()
