"""HN-BUG-003 (repair half): harness/build.py pins NANOD_LV_CONF_DIR to the lcd-preview folder on every
CMake configure, so a scratch value left in build/CMakeCache.txt (by hand or perf.py) is reset. build.py runs a
build at import, so this reads its source and evaluates the pins list with stand-in paths: no build, no port."""
import ast
from pathlib import Path
import unittest

BUILD_PY = Path(__file__).resolve().parents[2] / "harness" / "build.py"
CMAKELISTS = BUILD_PY.parent / "CMakeLists.txt"


def pins_node():
    tree = ast.parse(BUILD_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "pins" for t in node.targets):
            return node.value
    raise AssertionError("build.py has no pins assignment")


@unittest.skipUnless(BUILD_PY.is_file(), "harness/build.py not present")
class BuildPinsTests(unittest.TestCase):
    def evaluated_pins(self, root):
        code = compile(ast.Expression(pins_node()), str(BUILD_PY), "eval")
        return eval(code, {}, {"root": root, "firmware": root.parent / "firmware"})

    def test_pins_lv_conf_dir_to_harness_folder(self):
        root = Path("C:/stand-in/harness")
        pins = self.evaluated_pins(root)
        self.assertIn(f"-DNANOD_LV_CONF_DIR={root.as_posix()}", pins)

    def test_existing_pins_kept(self):
        root = Path("C:/stand-in/harness")
        pins = self.evaluated_pins(root)
        self.assertIn("-DNANOD_FIRMWARE_SRC=C:/stand-in/firmware/src", pins)
        self.assertIn("-DNANOD_TJPGD_SHIM=C:/stand-in/harness/tjpgd_shim", pins)
        self.assertEqual(len([p for p in pins if p.startswith("-DNANOD_LV_CONF_DIR=")]), 1)

    def test_pins_used_on_configure(self):
        source = BUILD_PY.read_text(encoding="utf-8")
        self.assertIn("'-A', 'x64'] + pins", source)

    def test_pinned_value_takes_default_branch(self):
        # The pinned value equals CMAKE_CURRENT_SOURCE_DIR, so no LV_CONF_PATH override is compiled in.
        cmake = CMAKELISTS.read_text(encoding="utf-8")
        self.assertIn("if(NOT NANOD_LV_CONF_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)", cmake)


if __name__ == "__main__":
    unittest.main()
