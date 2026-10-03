"""tools/profiles/make_index.py (plan section 5b, S1 DD-C): profiles/index.json from profiles/karl/*.json and the
sidecars, deterministic, readable by profile_updates.parse_index, and the committed file is current. Headless."""
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from control_center import app_profiles, profile_updates as pu  # noqa: E402


def _tool(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"profiles_tool_{name}", REPO / "tools" / "profiles" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


make_index = _tool("make_index")
PROFILES = REPO / "profiles"


class MakeIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.folder = self.tmp / "profiles"
        shutil.copytree(PROFILES, self.folder, ignore=shutil.ignore_patterns("index.json"))

    def run_tool(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = make_index.main(["--profiles", str(self.folder), *args])
        return code, out.getvalue(), err.getvalue()

    def test_every_karl_file_with_its_sidecar_relative_to_profiles(self):
        index = make_index.build_index(self.folder)
        self.assertEqual(index["format"], 1)
        ids = [e["id"] for e in index["profiles"]]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(set(ids), {p.stem for p in (PROFILES / "karl").glob("*.json")} - {"SOURCE"})
        for entry in index["profiles"]:
            with self.subTest(id=entry["id"]):
                data = (self.folder / entry["file"]).read_bytes()
                self.assertEqual(entry["file"], f"karl/{entry['id']}.json")
                self.assertEqual((entry["sha256"], entry["bytes"]), (hashlib.sha256(data).hexdigest(), len(data)))
                self.assertEqual(entry["desk_dial_min"], make_index.DESK_DIAL_MIN)
                overlay = entry["overlay"]
                side = (self.folder / overlay["file"]).read_bytes()
                self.assertEqual(overlay["file"], f"{entry['id']}.windows.json")
                self.assertEqual((overlay["sha256"], overlay["bytes"]), (hashlib.sha256(side).hexdigest(), len(side)))
        self.assertEqual(len(pu.parse_index(make_index.render(index))), len(ids), "Desk Dial reads what it writes")

    def test_no_sidecar_no_overlay_entry(self):
        (self.folder / "blender.windows.json").unlink()
        entry = next(e for e in make_index.build_index(self.folder)["profiles"] if e["id"] == "blender")
        self.assertNotIn("overlay", entry)

    def test_deterministic_and_check(self):
        self.assertEqual(self.run_tool()[0], 0)
        first = (self.folder / "index.json").read_bytes()
        self.assertEqual(self.run_tool()[0:2], (0, "profiles/index.json is up to date\n"))
        self.assertEqual((self.folder / "index.json").read_bytes(), first)
        self.assertTrue(first.endswith(b"}\n") and b"\r" not in first)
        self.assertEqual(self.run_tool("--check")[0], 0)
        doc = json.loads((self.folder / "karl" / "figma.json").read_text(encoding="ascii"))
        doc["name"] = "FIGMA 2"
        (self.folder / "karl" / "figma.json").write_text(json.dumps(doc), encoding="ascii")
        code, _out, err = self.run_tool("--check")
        self.assertEqual(code, 1)
        self.assertIn("out of date", err)
        self.assertEqual((self.folder / "index.json").read_bytes(), first, "--check writes nothing")

    def test_a_bad_profile_writes_nothing(self):
        (self.folder / "karl" / "figma.json").write_text("{\"format\": 1}", encoding="ascii")
        code, _out, err = self.run_tool()
        self.assertEqual(code, 1)
        self.assertIn("figma.json", err)
        self.assertFalse((self.folder / "index.json").exists())

    def test_a_bad_minimum_version_is_refused(self):
        self.assertEqual(self.run_tool("--desk-dial-min", "soon")[0], 1)
        self.assertEqual(self.run_tool("--desk-dial-min", "2.1")[0], 0)
        self.assertIn('"desk_dial_min": "2.1"', (self.folder / "index.json").read_text(encoding="ascii"))

    def test_the_committed_index_is_current(self):
        self.assertEqual((PROFILES / "index.json").read_bytes(), make_index.render(make_index.build_index(PROFILES)),
                         "run tools/profiles/make_index.py")

    def test_the_library_never_reads_the_index_as_a_profile(self):
        library = app_profiles.Library(PROFILES)
        self.assertNotIn("index", [p.id for p in library.profiles()])
        self.assertFalse([p for p in library.problems if "index" in p])


if __name__ == "__main__":
    unittest.main()
