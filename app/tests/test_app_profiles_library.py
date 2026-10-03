"""app_profiles.Library (plan sections 3a and 5a, S1 DD-A): sources by id (user > updates > bundled), the
sidecar from the highest source that fits, bad files skipped and the last good kept, owner rules merged
into detection, import (validate fully, then an atomic copy into user/), the stable order, and the
paths.profiles_*_dir folders. Temporary folders only; headless."""
from pathlib import Path
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import app_profiles as ap, paths  # noqa: E402
from control_center.app_profiles import Library, ProfileError  # noqa: E402

PROFILES = Path(__file__).resolve().parents[1] / "profiles"
IDS = ["onshape", "figma", "plasticity", "blender", "autocad"]


def karl(pid):
    return json.loads((PROFILES / "karl" / f"{pid}.json").read_text())


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc) if not isinstance(doc, str) else doc)
    return path


class LibraryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.updates = self.tmp / "updates"
        self.user = self.tmp / "user"

    def lib(self, **kw):
        return Library(PROFILES, self.updates, self.user, **kw)


class SourceTests(LibraryCase):
    def test_bundled_order_and_sources(self):
        lib = self.lib()
        self.assertEqual(lib.problems, [])
        self.assertEqual([p.id for p in lib.profiles()], IDS)
        self.assertEqual({p.source for p in lib.profiles()}, {"bundled"})
        self.assertIsNone(lib.get("nope"))
        self.assertEqual(lib.get("onshape").status, "tested")

    def test_others_sort_by_name_after_the_five(self):
        for pid, name in (("zz", "ALPHA"), ("aa", "ZULU")):
            write(self.user / f"{pid}.json", dict(karl("blender"), id=pid, name=name))
        self.assertEqual([p.id for p in self.lib().profiles()], IDS + ["zz", "aa"])

    def test_precedence_and_bundled_sidecar_kept(self):
        write(self.updates / "onshape.json", dict(karl("onshape"), name="ONSHAPE UPD"))
        lib = self.lib()
        p = lib.get("onshape")
        self.assertEqual((p.source, p.name, p.status), ("updates", "ONSHAPE UPD", "tested"))
        self.assertEqual(p.slots["f1"].label, "TILT")                         # the bundled sidecar still applies
        write(self.user / "onshape.json", dict(karl("onshape"), name="ONSHAPE MINE"))
        self.assertEqual(lib.reload(), [])
        self.assertEqual((lib.get("onshape").source, lib.get("onshape").name), ("user", "ONSHAPE MINE"))

    def test_user_sidecar_alone_applies_to_bundled_karl(self):
        write(self.user / "figma.windows.json", {"overlay": 1, "status": "tested", "keys": {"ALIGN/TIDY UP": "f9"}})
        p = self.lib().get("figma")
        self.assertEqual((p.source, p.status), ("bundled", "tested"))
        self.assertEqual(p.rings[1].commands[6].chord.key.label, "F9")

    def test_bad_files_are_skipped_with_problems(self):
        write(self.user / "figma.json", "{not json")
        write(self.updates / "figma.json", dict(karl("figma"), name=""))
        lib = self.lib()
        self.assertEqual(lib.get("figma").source, "bundled")
        self.assertTrue(any(p.startswith("user: figma.json: not valid JSON") for p in lib.problems), lib.problems)
        self.assertTrue(any(p.startswith("updates: figma.json: name") for p in lib.problems), lib.problems)

    def test_broken_sidecar_falls_back_to_the_next(self):
        write(self.user / "onshape.windows.json", {"overlay": 1, "keys": {"MODEL/GONE": "f1"}})
        lib = self.lib()
        self.assertEqual(lib.get("onshape").slots["f1"].label, "TILT")
        self.assertTrue(any("MODEL/GONE" in p for p in lib.problems), lib.problems)

    def test_last_good_kept(self):
        write(self.user / "mine.json", dict(karl("blender"), id="mine", name="MINE"))
        lib = self.lib()
        self.assertEqual(lib.get("mine").name, "MINE")
        write(self.user / "mine.json", "{}")
        problems = lib.reload()
        self.assertEqual(lib.get("mine").name, "MINE")
        self.assertIn("mine: kept the last good version", problems)

    def test_file_name_must_be_the_id(self):
        write(self.user / "other.json", karl("blender"))
        write(self.user / "Bad Name.json", karl("blender"))
        lib = self.lib()
        self.assertIsNone(lib.get("other"))
        self.assertTrue(any('says it is "blender"' in p for p in lib.problems))
        self.assertTrue(any("the file name must be the profile id" in p for p in lib.problems))

    def test_missing_folders_are_fine(self):
        lib = Library(PROFILES, self.tmp / "none", None)
        self.assertEqual(len(lib.profiles()), 5)
        self.assertEqual(Library(None).profiles(), [])


class RuleTests(LibraryCase):
    def test_owner_rules_merge(self):
        lib = self.lib(rules={"figma": {"exe": ["FigmaBeta.exe"], "host": ["*.figma.com", "figma.com"]},
                              "blender": {"exe": ["blender-launcher.exe"]}})
        self.assertEqual(lib.problems, [])
        self.assertEqual(lib.get("figma").detect.exe, ("Figma.exe", "FigmaBeta.exe"))
        self.assertEqual(lib.get("figma").detect.host, ("figma.com", "www.figma.com", "*.figma.com"))
        self.assertTrue(lib.get("blender").detect.matches_exe("Blender-Launcher.exe"))

    def test_bad_rules_are_refused_and_ignored(self):
        lib = self.lib(rules={"figma": {"host": ["https://figma.com/file/x"], "title": ["x"]}})
        self.assertEqual(lib.get("figma").detect.host, ("figma.com", "www.figma.com"))
        self.assertTrue(any("bare host" in p for p in lib.problems))
        self.assertTrue(any("rules.figma.title" in p for p in lib.problems))
        self.assertTrue(self.lib(rules=[1]).problems)


class ImportTests(LibraryCase):
    def test_import_with_sibling_sidecar(self):
        src = self.tmp / "in"
        write(src / "figma.json", dict(karl("figma"), name="FIGMA NEW"))
        write(src / "figma.windows.json", {"overlay": 1, "status": "tested", "detect": {"exe": ["Figma.exe"]}})
        lib = self.lib()
        p = lib.import_file(src / "figma.json")
        self.assertEqual((p.source, p.name, p.status), ("user", "FIGMA NEW", "tested"))
        self.assertEqual(sorted(f.name for f in self.user.iterdir()), ["figma.json", "figma.windows.json"])
        self.assertEqual((self.user / "figma.json").read_bytes(), (src / "figma.json").read_bytes())

    def test_import_under_another_name_uses_the_id(self):
        src = write(self.tmp / "download (1).json", karl("plasticity"))
        p = self.lib().import_file(src)
        self.assertEqual((p.id, p.source), ("plasticity", "user"))
        self.assertTrue((self.user / "plasticity.json").is_file())

    def test_invalid_import_copies_nothing(self):
        lib = self.lib()
        bad = write(self.tmp / "figma.json", dict(karl("figma"), legend=["A"]))
        with self.assertRaises(ProfileError) as ctx:
            lib.import_file(bad)
        self.assertEqual(ctx.exception.problems, ["figma.json: legend: 4 texts"])
        good = write(self.tmp / "in" / "figma.json", karl("figma"))
        write(self.tmp / "in" / "figma.windows.json", {"overlay": 1, "colour": "red"})
        with self.assertRaises(ProfileError):
            lib.import_file(good)
        renamed = karl("onshape")
        renamed["rings"][0]["cmds"][1]["name"] = "PUSH"                 # the bundled sidecar names MODEL/EXTRUDE
        with self.assertRaises(ProfileError) as ctx:
            lib.import_file(write(self.tmp / "onshape.json", renamed))
        self.assertTrue(any("MODEL/EXTRUDE" in p for p in ctx.exception.problems))
        with self.assertRaises(ProfileError):
            lib.import_file(self.tmp / "missing.json")
        big = self.tmp / "big.json"
        big.write_bytes(b" " * (ap.FILE_MAX + 1))
        with self.assertRaises(ProfileError):
            lib.import_file(big)
        self.assertFalse(self.user.exists() and any(self.user.iterdir()))
        self.assertEqual(lib.get("figma").source, "bundled")

    def test_import_needs_a_user_folder(self):
        with self.assertRaises(ProfileError):
            Library(PROFILES).import_file(PROFILES / "karl" / "figma.json")

    def test_atomic_copy_leaves_no_temp_file_on_failure(self):
        lib = self.lib()
        with mock.patch.object(ap.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                lib.import_file(PROFILES / "karl" / "blender.json")
        self.assertEqual(list(self.user.iterdir()), [])


class PathTests(unittest.TestCase):
    def test_profile_folders(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": r"C:\LAD"}):
            self.assertEqual(paths.profiles_user_dir(frozen=True), Path(r"C:\LAD\DeskDial\data\profiles\user"))
            self.assertEqual(paths.profiles_updates_dir(frozen=True), Path(r"C:\LAD\DeskDial\data\profiles\updates"))
        repo = Path(paths.__file__).resolve().parents[1]
        self.assertEqual(paths.profiles_user_dir(frozen=False), repo / "local" / "profiles" / "user")
        self.assertEqual(paths.profiles_updates_dir(frozen=False), repo / "local" / "profiles" / "updates")
        self.assertEqual(paths.profiles_dir(), repo / "local" / "profiles")       # tests run unfrozen
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.dict(os.environ, {"LOCALAPPDATA": "X"}):
            self.assertEqual(paths.profiles_dir(), Path("X") / "DeskDial" / "data" / "profiles")


if __name__ == "__main__":
    unittest.main()
