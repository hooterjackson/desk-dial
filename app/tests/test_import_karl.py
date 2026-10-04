"""tools/profiles/import_karl.py and validate.py (plan section 5c, S1 DD-A) on a fake Karl tree and fixture JSON:
the generated hid.h, the cJSON pin, the build command lines (MSVC and Karl's gcc flags), validation before
anything is written, SOURCE.json, the change summary (added / removed / renamed commands, broken sidecar
references, sizes) and the validate CLI's exit codes. No network, no compiler, no clone. Headless."""
from pathlib import Path
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _tool(name):
    """tools/profiles/<name>.py under a unique module name (the suite shares one process)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"profiles_tool_{name}", REPO / "tools" / "profiles" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


import_karl = _tool("import_karl")
validate = _tool("validate")

from control_center import keymap  # noqa: E402

PROFILES = REPO / "profiles"


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def fake_karl(self):
        root = self.tmp / "clone" / "NanoDepsidf"
        for rel in ("src/app_profiles/profile_json.c", "src/app_profiles/app_profiles.c", "src/app_profiles/figma.c",
                    "src/app_profiles/icons/figma_24.c", "tools/profile_json_test/test.c"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("/* fake */\n")
        return root

    def karl_json(self, folder, ids=("onshape", "figma", "plasticity", "blender", "autocad")):
        folder.mkdir(parents=True, exist_ok=True)
        for pid in ids:
            shutil.copy(PROFILES / "karl" / f"{pid}.json", folder / f"{pid}.json")
        return folder

    def args(self, **kw):
        out = kw.pop("out", self.tmp / "out")
        argv = ["--out", str(out), "--sidecars", str(kw.pop("sidecars", PROFILES))]
        for k, v in kw.items():
            argv += [f"--{k.replace('_', '-')}", str(v)]
        args = import_karl.parser().parse_args(argv)
        return args

    def run_quiet(self, args):
        with redirect_stdout(io.StringIO()) as out:
            changed = import_karl.run(args, self.tmp / "work")
        return changed, out.getvalue()


class InputTests(Case):
    def test_hid_header_has_every_key_desk_dial_sends(self):
        text = import_karl.hid_header()
        self.assertIn("#define HID_KEY_A                         0x04", text)
        self.assertIn("#define HID_KEY_KEYPAD_1                  0x59", text)
        self.assertIn("#define HID_KEY_GUI_RIGHT                 0xE7", text)
        self.assertIn("#define KEYBOARD_MODIFIER_LEFTGUI (1u << 3)", text)
        self.assertIn("#define MOUSE_BUTTON_MIDDLE (1u << 2)", text)
        values = {int(line.split()[-1], 16) for line in text.splitlines() if line.startswith("#define HID_KEY_")}
        for usage in range(256):
            try:
                keymap.from_hid(usage)
            except ValueError:
                continue
            self.assertIn(usage, values)
        self.assertEqual(len(values), 1 + 26 + 10 + (0xA4 - 0x28 + 1) + 8)

    def test_shims(self):
        folder = import_karl.write_shims(self.tmp / "shim")
        self.assertTrue((folder / "class" / "hid" / "hid.h").is_file())
        self.assertEqual((folder / "msvc_gnu.h").read_text(), "#pragma once\n#define __attribute__(x)\n")

    def test_cjson_pin(self):
        folder = self.tmp / "cjson"
        folder.mkdir()
        with self.assertRaises(import_karl.ImportProblem):
            import_karl.check_cjson(folder)
        for name in import_karl.CJSON_SHA256:
            (folder / name).write_bytes(b"not cjson")
        with self.assertRaises(import_karl.ImportProblem) as ctx:
            import_karl.check_cjson(folder)
        self.assertIn("not the pinned v1.7.18", str(ctx.exception))
        pins = {name: hashlib.sha256(b"not cjson").hexdigest() for name in import_karl.CJSON_SHA256}
        with mock.patch.dict(import_karl.CJSON_SHA256, pins):
            self.assertEqual(import_karl.check_cjson(folder), folder)

    def test_cjson_download_is_verified(self):
        urls = []

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def opener(request, timeout):
            urls.append(request.full_url)
            return Response(b"x" * 10)
        with self.assertRaises(import_karl.ImportProblem):
            import_karl.fetch_cjson(self.tmp / "dl", opener=opener)
        self.assertTrue(all(u.startswith("https://raw.githubusercontent.com/DaveGamble/cJSON/v1.7.18/") for u in urls))
        pins = {name: hashlib.sha256(b"x" * 10).hexdigest() for name in import_karl.CJSON_SHA256}
        with mock.patch.dict(import_karl.CJSON_SHA256, pins):
            self.assertEqual(import_karl.fetch_cjson(self.tmp / "dl2", opener=opener), self.tmp / "dl2")
        with self.assertRaises(import_karl.ImportProblem):
            import_karl.fetch_cjson(self.tmp / "dl3", opener=lambda r, timeout: Response(b"x" * (300 * 1024)))

    def test_karl_root(self):
        root = self.fake_karl()
        self.assertEqual(import_karl.karl_root(root.parent), root)
        self.assertEqual(import_karl.karl_root(root), root)
        with self.assertRaises(import_karl.ImportProblem):
            import_karl.karl_root(self.tmp)
        names = [p.name for p in import_karl.karl_sources(root)]
        self.assertEqual(names, ["test.c", "app_profiles.c", "figma.c", "profile_json.c", "figma_24.c"])


class BuildTests(Case):
    def test_msvc_command(self):
        root = self.fake_karl()
        seen = []

        def fake_run(cmd, **kw):
            seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        with mock.patch.object(import_karl, "msvc_env", return_value=(Path("cl.exe"), {})), \
                mock.patch.object(import_karl.subprocess, "run", fake_run):
            exe = import_karl.build(root, self.tmp / "cjson", self.tmp / "shim", self.tmp / "b", "msvc")
        cmd = seen[0]
        self.assertEqual(exe.name, "profile_json_test.exe")
        for flag in ("/TC", "/std:c17", "/experimental:c11atomics", f"/FI{self.tmp / 'shim' / 'msvc_gnu.h'}",
                     f"/I{root / 'src'}", f"/I{root / 'tools' / 'profile_json_test'}"):
            self.assertIn(flag, cmd)
        self.assertIn(str(self.tmp / "cjson" / "cJSON.c"), cmd)
        self.assertIn(str(root / "src" / "app_profiles" / "profile_json.c"), cmd)

    def test_gcc_command_uses_karls_flags(self):
        root = self.fake_karl()
        seen = []

        def fake_run(cmd, **kw):
            seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        with mock.patch.object(import_karl.shutil, "which", return_value="/usr/bin/cc"), \
                mock.patch.object(import_karl.subprocess, "run", fake_run):
            import_karl.build(root, self.tmp / "cjson", self.tmp / "shim", self.tmp / "b", "gcc")
        cmd = seen[0]
        self.assertEqual(cmd[:8], ["/usr/bin/cc", "-std=gnu11", "-Wall", "-Wno-unused-function", "-O1", "-g",
                                   "-fsanitize=undefined", "-Wno-deprecated-declarations"])

    def test_build_and_dump_failures(self):
        root = self.fake_karl()
        failed = subprocess.CompletedProcess([], 2, "error C2065", "")
        with mock.patch.object(import_karl, "msvc_env", return_value=(Path("cl.exe"), {})), \
                mock.patch.object(import_karl.subprocess, "run", return_value=failed):
            with self.assertRaises(import_karl.ImportProblem) as ctx:
                import_karl.build(root, self.tmp, self.tmp, self.tmp / "b", "msvc")
            self.assertIn("error C2065", str(ctx.exception))
            with self.assertRaises(import_karl.ImportProblem):
                import_karl.dump(self.tmp / "x.exe", self.tmp / "d")

    def test_build_path_end_to_end_with_a_fake_compiler(self):
        root = self.fake_karl()
        fixtures = self.karl_json(self.tmp / "fixture")

        def fake_dump(exe, folder):
            shutil.copytree(fixtures, folder, dirs_exist_ok=True)
            return "all good\n"
        with mock.patch.object(import_karl, "check_cjson", side_effect=lambda d: Path(d)), \
                mock.patch.object(import_karl, "build", return_value=self.tmp / "x.exe") as build, \
                mock.patch.object(import_karl, "dump", side_effect=fake_dump), \
                mock.patch.object(import_karl, "karl_commit", return_value="55e47cbb3134"):
            changed, out = self.run_quiet(self.args(karl=root.parent, cjson=self.tmp / "cj"))
        self.assertTrue(changed)
        self.assertEqual(build.call_args[0][0], root)
        record = json.loads((self.tmp / "out" / "SOURCE.json").read_text())
        self.assertEqual((record["commit"], record["origin"], record["cjson"]), ("55e47cbb3134", "built-ins", "v1.7.18"))
        for name in ("onshape.json", "figma.json"):
            self.assertEqual((self.tmp / "out" / name).read_bytes(), (PROFILES / "karl" / name).read_bytes())

    def test_no_karl_means_a_clone(self):
        with mock.patch.object(import_karl, "git") as git:
            import_karl.clone(self.tmp / "k", ref="abc123")
        first = git.call_args_list[0][0]
        self.assertEqual(first[:6], ("clone", "--quiet", "--depth", "50", "--branch", "feat/firmware-esp-idf-quadra"))
        self.assertEqual(first[6], "https://github.com/katbinaris/NanoD_RatchetH1")
        self.assertEqual(git.call_args_list[1][0], ("checkout", "--quiet", "--end-of-options", "abc123"))

    def test_a_ref_is_never_an_option(self):
        """S3 review DD-9: --ref went to git as is, so "--upload-pack=..." or "-c..." was read as a git option. A ref
        starting with "-" is refused, and refs reach git after --end-of-options."""
        for ref in ("--upload-pack=touch /tmp/x", "-cuser.name=x", "-"):
            with self.subTest(ref=ref):
                with mock.patch.object(import_karl, "git") as git:
                    with self.assertRaises(import_karl.ImportProblem):
                        import_karl.clone(self.tmp / "k", ref=ref)
                self.assertEqual(git.call_args_list, [], "nothing runs")
        with mock.patch.object(import_karl, "git") as git, redirect_stderr(io.StringIO()) as err:
            self.assertEqual(import_karl.main(["--ref=--upload-pack=x", "--out", str(self.tmp / "out")]), 1)
        self.assertEqual(git.call_args_list, [])
        self.assertIn("--ref", err.getvalue())

    def test_a_fetched_ref_comes_after_end_of_options(self):
        calls = []

        def git(*args, cwd=None):
            calls.append(args)
            if args[0] == "checkout" and args[-1] == "abc123":
                raise subprocess.CalledProcessError(1, "git")
            return ""
        with mock.patch.object(import_karl, "git", git):
            import_karl.clone(self.tmp / "k", ref="abc123")
        self.assertEqual(calls[2], ("fetch", "--quiet", "--depth", "1", "--end-of-options", "origin", "abc123"))
        self.assertEqual(calls[3], ("checkout", "--quiet", "FETCH_HEAD"))


class ImportTests(Case):
    def test_bundled_files_record(self):
        """profiles/karl/SOURCE.json describes the committed files exactly (Karl's 55e47cb)."""
        record = json.loads((PROFILES / "karl" / "SOURCE.json").read_text())
        self.assertEqual(record["commit"], "55e47cbb313416ca678936b51e5c1988ef5590d4")
        files = {p.name for p in (PROFILES / "karl").glob("*.json")} - {"SOURCE.json"}
        self.assertEqual(set(record["files"]), files)
        for name, info in record["files"].items():
            raw = (PROFILES / "karl" / name).read_bytes()
            self.assertEqual((hashlib.sha256(raw).hexdigest(), len(raw)), (info["sha256"], info["bytes"]), name)

    def test_unchanged_import(self):
        src = self.karl_json(self.tmp / "src")
        out = self.karl_json(self.tmp / "out")
        changed, text = self.run_quiet(self.args(from_json=src, commit="abc"))
        self.assertFalse(changed)
        self.assertIn("No change.", text)
        self.assertIn("- `onshape`: unchanged (20801 B)", text)

    def test_unchanged_import_keeps_source_json_so_no_pr_opens(self):
        """A new commit of Karl's that leaves every profile byte-identical changes nothing on disk: SOURCE.json keeps
        the commit the files were imported from, so the Action finds no diff and opens no review PR (PR #1 was only
        SOURCE.json's commit field)."""
        src = self.karl_json(self.tmp / "src")
        out = self.karl_json(self.tmp / "out")
        self.run_quiet(self.args(from_json=src, commit="old-commit"))
        before = (out / "SOURCE.json").read_bytes()
        changed, text = self.run_quiet(self.args(from_json=src, commit="new-commit"))
        self.assertFalse(changed)
        self.assertEqual((out / "SOURCE.json").read_bytes(), before)
        self.assertIn("No change.", text)
        self.assertIn("SOURCE.json kept (still `old-commit`)", text)

    def test_unchanged_import_still_writes_a_missing_source_json(self):
        src = self.karl_json(self.tmp / "src")
        out = self.karl_json(self.tmp / "out")
        (out / "SOURCE.json").unlink(missing_ok=True)
        self.run_quiet(self.args(from_json=src, commit="first"))
        self.assertEqual(json.loads((out / "SOURCE.json").read_text())["commit"], "first")

    def test_changes_are_summarised(self):
        src = self.karl_json(self.tmp / "src", ("onshape", "figma", "plasticity", "blender"))
        self.karl_json(self.tmp / "out")
        onshape = json.loads((src / "onshape.json").read_text())
        onshape["rings"][0]["cmds"][1]["name"] = "PUSH PULL"          # EXTRUDE renamed (same key)
        onshape["rings"][2]["cmds"].append({"name": "SPLINE", "key": [0, 25]})
        del onshape["rings"][3]["cmds"][-1]                           # SECTION removed
        onshape["rings"][1]["cmds"][0]["phrase"] = "boolean union"
        (src / "onshape.json").write_text(json.dumps(onshape))
        figma = json.loads((src / "figma.json").read_text())
        figma["rings"].append({"name": "TEXT", "tab": "TEXT", "slot": "f4", "cmds": [{"name": "BOLD", "key": [8, 5]}]})
        (src / "figma.json").write_text(json.dumps(figma))
        (src / "mine.json").write_text(json.dumps(dict(json.loads((src / "blender.json").read_text()), id="mine")))
        summary = self.tmp / "summary.md"
        changed, text = self.run_quiet(self.args(from_json=src, commit="0123456789abcdef", summary=summary))
        self.assertTrue(changed)
        self.assertEqual(summary.read_text(), text)
        for line in ("Karl's profiles at `0123456789ab`", "- `autocad`: **removed** (was 7838 B)",
                     "- `mine`: **added**", "MODEL: renamed EXTRUDE -> PUSH PULL", "SKETCH: command added: SPLINE",
                     "VIEW: command removed: SECTION", "MODIFY/BOOLEAN: key or phrase changed",
                     "ring added: TEXT (1 commands)",
                     "**broken sidecar reference** in onshape.windows.json: params.\"MODEL/EXTRUDE\"",
                     "wire profile:"):
            self.assertIn(line, text)
        self.assertFalse((self.tmp / "out" / "autocad.json").exists())
        self.assertTrue((self.tmp / "out" / "mine.json").exists())
        self.assertEqual(json.loads((self.tmp / "out" / "SOURCE.json").read_text())["origin"], "json")

    def test_invalid_file_writes_nothing(self):
        src = self.karl_json(self.tmp / "src", ("figma",))
        (src / "figma.json").write_text(json.dumps(dict(json.loads((src / "figma.json").read_text()), name="")))
        (src / "other.json").write_text(json.dumps(dict(json.loads((PROFILES / "karl" / "blender.json").read_text()))))
        out = self.karl_json(self.tmp / "out", ("figma",))
        before = (out / "figma.json").read_bytes()
        with redirect_stderr(io.StringIO()) as err:
            code = import_karl.main(["--from-json", str(src), "--out", str(out), "--sidecars", str(PROFILES)])
        self.assertEqual(code, 1)
        self.assertIn("figma.json: name: 1..15 characters", err.getvalue())
        self.assertIn('other.json: says it is "blender"', err.getvalue())
        self.assertEqual((out / "figma.json").read_bytes(), before)
        self.assertFalse((out / "SOURCE.json").exists())


class ValidateCliTests(Case):
    def run_cli(self, *argv):
        with redirect_stdout(io.StringIO()) as out:
            code = validate.main(list(map(str, argv)))
        return code, out.getvalue()

    def test_bundled_folder(self):
        code, text = self.run_cli(PROFILES)
        self.assertEqual(code, 0, text)
        self.assertEqual(text.count("\nok  ") + text.startswith("ok  "), 5)
        self.assertIn("onshape     tested    wire", text)
        self.assertIn("crc 0x", text)

    def test_single_files(self):
        self.assertEqual(self.run_cli(PROFILES / "figma.windows.json")[0], 0)
        self.assertEqual(self.run_cli(PROFILES / "karl" / "plasticity.json")[0], 0)

    def test_problems_exit_1(self):
        bad = self.tmp / "figma.json"
        bad.write_text(json.dumps(dict(json.loads((PROFILES / "karl" / "figma.json").read_text()), legend=[])))
        code, text = self.run_cli(bad)
        self.assertEqual(code, 1)
        self.assertIn("PROBLEM  figma.json: legend: 4 texts", text)
        orphan = self.tmp / "o" / "x.windows.json"
        orphan.parent.mkdir()
        orphan.write_text("{}")
        self.assertEqual(self.run_cli(orphan)[0], 1)
        self.assertEqual(self.run_cli(orphan.parent)[0], 1)
        self.assertEqual(self.run_cli(self.tmp / "missing")[0], 1)
        self.assertEqual(self.run_cli()[0], 2)


if __name__ == "__main__":
    unittest.main()
