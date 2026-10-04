"""Import Karl's app profiles as JSON (plan sections 2 and 5c; S1 DD-A).

Karl Malota's (katbinaris) profiles live as C data in ``feat/firmware-esp-idf-quadra``
(``NanoDepsidf/src/app_profiles/``); his own host test ``tools/profile_json_test`` writes each built-in as
``"format": 1`` JSON with his ``profile_json.c``. This script builds that test **unchanged** and keeps
its output: adapted from his ``tools/profile_json_test/run.sh``, with his permission.

Steps:

1. Karl's tree: ``--karl <clone>`` (his repo root or its ``NanoDepsidf``), else a shallow clone of
   ``https://github.com/katbinaris/NanoD_RatchetH1`` ``--branch feat/firmware-esp-idf-quadra`` (``--ref``
   checks out a commit) into a temporary folder.
2. cJSON v1.7.18, pinned by SHA-256 (``cJSON.c``, ``cJSON.h``, ``LICENSE``): ``--cjson <dir>``, else
   downloaded from the tag and verified. Never committed.
3. ``class/hid/hid.h``: generated here from the USB HID usage table (TinyUSB's names and values, only the
   ``#define``s Karl's sources use: keys, modifier bits, mouse buttons), so no TinyUSB checkout is needed
   on either compiler. ``msvc_gnu.h`` (MSVC only) blanks ``__attribute__``.
4. Build: MSVC on Windows (``msvc_env()`` from ``harness/app_canvas_tests.py``, or a Developer
   prompt's ``cl``), or ``cc`` / ``gcc`` elsewhere with Karl's own run.sh flags (the GitHub Action).
5. Run it with a dump folder: Karl's test checks every built-in round-trips, then writes the JSON.
6. Validate every file with ``control_center.app_profiles`` (the code Desk Dial ships). Nothing is
   written if one fails.
7. Write ``--out`` (default ``profiles/karl``): the JSON files byte for byte, files Karl dropped removed,
   and ``SOURCE.json`` (his commit, cJSON pin, each file's SHA-256 and size).
8. Print a change summary against the previous files (added / removed / renamed commands, rings, broken
   sidecar references, size changes); ``--summary <file>`` also writes it (the Action's PR body).

Usage: python tools/profiles/import_karl.py [--karl DIR] [--ref SHA] [--out DIR] [--cjson DIR]
       [--compiler auto|msvc|gcc] [--from-json DIR] [--summary FILE] [--sidecars DIR]
``--from-json`` skips the build and imports JSON files Karl committed himself.
Exit 0 = imported (changed or not), 1 = a problem (nothing written).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center import app_profiles as ap  # noqa: E402

KARL_REPO = "https://github.com/katbinaris/NanoD_RatchetH1"
KARL_BRANCH = "feat/firmware-esp-idf-quadra"
CJSON_TAG = "v1.7.18"
CJSON_URL = "https://raw.githubusercontent.com/DaveGamble/cJSON/" + CJSON_TAG + "/{name}"
CJSON_SHA256 = {
    "cJSON.c": "75c51de8fa40ac9d7a99319c6330719bd692eb81c0a869265f3d4c682533f9b9",
    "cJSON.h": "0578cc29132912edbc88f83207a8fc76e5db3db0605497e909a9384ef3cc474b",
    "LICENSE": "a36dda207c36db5818729c54e7ad4e8b0c6fba847491ba64f372c1a2037b6d5c",
}
# The harness that owns the MSVC paths (harness/app_canvas_tests.py msvc_env): beside a worktree
# (ex/worktrees/work) or beside the shared tree (ex/work); NANOD_LCD_PREVIEW overrides.
MSVC_ENV_FROM = tuple(Path(p) for p in (os.environ.get("NANOD_LCD_PREVIEW"), ROOT.parent / "harness",
                                        ROOT.parent / "harness") if p)
DOWNLOAD_MAX = 256 * 1024

# USB HID usage names as TinyUSB's class/hid/hid.h spells them (HID_KEY_<name>), 0x28..0xA4 in order.
_HID_NAMED = (
    "ENTER ESCAPE BACKSPACE TAB SPACE MINUS EQUAL BRACKET_LEFT BRACKET_RIGHT BACKSLASH EUROPE_1 SEMICOLON "
    "APOSTROPHE GRAVE COMMA PERIOD SLASH CAPS_LOCK F1 F2 F3 F4 F5 F6 F7 F8 F9 F10 F11 F12 PRINT_SCREEN "
    "SCROLL_LOCK PAUSE INSERT HOME PAGE_UP DELETE END PAGE_DOWN ARROW_RIGHT ARROW_LEFT ARROW_DOWN ARROW_UP "
    "NUM_LOCK KEYPAD_DIVIDE KEYPAD_MULTIPLY KEYPAD_SUBTRACT KEYPAD_ADD KEYPAD_ENTER KEYPAD_1 KEYPAD_2 KEYPAD_3 "
    "KEYPAD_4 KEYPAD_5 KEYPAD_6 KEYPAD_7 KEYPAD_8 KEYPAD_9 KEYPAD_0 KEYPAD_DECIMAL EUROPE_2 APPLICATION POWER "
    "KEYPAD_EQUAL F13 F14 F15 F16 F17 F18 F19 F20 F21 F22 F23 F24 EXECUTE HELP MENU SELECT STOP AGAIN UNDO CUT "
    "COPY PASTE FIND MUTE VOLUME_UP VOLUME_DOWN LOCKING_CAPS_LOCK LOCKING_NUM_LOCK LOCKING_SCROLL_LOCK "
    "KEYPAD_COMMA KEYPAD_EQUAL_SIGN KANJI1 KANJI2 KANJI3 KANJI4 KANJI5 KANJI6 KANJI7 KANJI8 KANJI9 LANG1 LANG2 "
    "LANG3 LANG4 LANG5 LANG6 LANG7 LANG8 LANG9 ALTERNATE_ERASE SYSREQ_ATTENTION CANCEL CLEAR PRIOR RETURN "
    "SEPARATOR OUT OPER CLEAR_AGAIN CRSEL_PROPS EXSEL").split()
_HID_MODS = ("CONTROL_LEFT SHIFT_LEFT ALT_LEFT GUI_LEFT CONTROL_RIGHT SHIFT_RIGHT ALT_RIGHT GUI_RIGHT").split()
_KEYBOARD_MODIFIER = ("LEFTCTRL LEFTSHIFT LEFTALT LEFTGUI RIGHTCTRL RIGHTSHIFT RIGHTALT RIGHTGUI").split()
_MOUSE_BUTTON = ("LEFT RIGHT MIDDLE BACKWARD FORWARD").split()


class ImportProblem(RuntimeError):
    pass


# ------------------------------------------------------------------ inputs
def hid_header():
    """The generated class/hid/hid.h (only #defines; TinyUSB's names and the USB HID usage values)."""
    rows = [("NONE", 0)]
    rows += [(chr(ord("A") + i), 0x04 + i) for i in range(26)]
    rows += [(d, 0x1E + i) for i, d in enumerate("1234567890")]
    rows += [(name, 0x28 + i) for i, name in enumerate(_HID_NAMED)]
    rows += [(name, 0xE0 + i) for i, name in enumerate(_HID_MODS)]
    lines = ["// Generated: HID key codes from TinyUSB class/hid/hid.h (USB HID usage table), for the host build only.",
             "#pragma once"]
    lines += [f"#define {'HID_KEY_' + name:<34}0x{value:02X}" for name, value in rows]
    lines += [f"#define KEYBOARD_MODIFIER_{name} (1u << {i})" for i, name in enumerate(_KEYBOARD_MODIFIER)]
    lines += [f"#define MOUSE_BUTTON_{name} (1u << {i})" for i, name in enumerate(_MOUSE_BUTTON)]
    return "\n".join(lines) + "\n"


def write_shims(folder):
    folder = Path(folder)
    (folder / "class" / "hid").mkdir(parents=True, exist_ok=True)
    (folder / "class" / "hid" / "hid.h").write_text(hid_header(), newline="\n")
    (folder / "msvc_gnu.h").write_text("#pragma once\n#define __attribute__(x)\n", newline="\n")
    return folder


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_cjson(folder):
    folder = Path(folder)
    for name, want in CJSON_SHA256.items():
        path = folder / name
        if not path.is_file():
            raise ImportProblem(f"cJSON: {path} is missing")
        if sha256(path) != want:
            raise ImportProblem(f"cJSON: {name} is not the pinned {CJSON_TAG} file (SHA-256 differs)")
    return folder


def fetch_cjson(folder, opener=urllib.request.urlopen):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name in CJSON_SHA256:
        request = urllib.request.Request(CJSON_URL.format(name=name), headers={"User-Agent": "DeskDial-import"})
        with opener(request, timeout=30) as response:
            data = response.read(DOWNLOAD_MAX + 1)
        if len(data) > DOWNLOAD_MAX:
            raise ImportProblem(f"cJSON: {name} is larger than expected")
        (folder / name).write_bytes(data)
    return check_cjson(folder)


def karl_root(path):
    """Karl's NanoDepsidf folder (given his repo root or the folder itself)."""
    path = Path(path)
    for candidate in (path / "NanoDepsidf", path):
        if (candidate / "src" / "app_profiles" / "profile_json.c").is_file() and \
                (candidate / "tools" / "profile_json_test" / "test.c").is_file():
            return candidate
    raise ImportProblem(f"{path}: not Karl's tree (no NanoDepsidf/src/app_profiles/profile_json.c)")


def karl_sources(root):
    return [root / "tools" / "profile_json_test" / "test.c", *sorted((root / "src" / "app_profiles").glob("*.c")),
            *sorted((root / "src" / "app_profiles" / "icons").glob("*.c"))]


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def check_ref(ref):
    """S3 review DD-9: a ref is never read as a git option ("--upload-pack=...", "-c...")."""
    if ref is not None and (not isinstance(ref, str) or ref.startswith("-")):
        raise ImportProblem(f"--ref {ref!r}: a commit or branch name, never starting with -")
    return ref


def clone(dest, ref=None):
    check_ref(ref)
    git("clone", "--quiet", "--depth", "50", "--branch", KARL_BRANCH, KARL_REPO, str(dest))
    if ref:
        try:
            git("checkout", "--quiet", "--end-of-options", ref, cwd=dest)
        except subprocess.CalledProcessError:
            git("fetch", "--quiet", "--depth", "1", "--end-of-options", "origin", ref, cwd=dest)
            git("checkout", "--quiet", "FETCH_HEAD", cwd=dest)
    return dest


def karl_commit(path):
    try:
        return git("rev-parse", "HEAD", cwd=path)
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


# ------------------------------------------------------------------ build
def msvc_env():
    """The harness's MSVC environment (app_canvas_tests.msvc_env), else a Developer prompt's cl."""
    for folder in MSVC_ENV_FROM:
        if not (folder / "app_canvas_tests.py").is_file():
            continue
        sys.path.insert(0, str(folder))
        try:
            from app_canvas_tests import msvc_env as harness_env  # the harness's toolchain
            cl, env = harness_env()
            if Path(cl).is_file():
                return cl, env
        except ImportError:
            pass
        finally:
            sys.path.remove(str(folder))
    cl = shutil.which("cl")
    if cl:
        return Path(cl), dict(os.environ)
    raise ImportProblem("MSVC: no cl.exe (run from a Developer prompt, or next to harness)")


def build(root, cjson, shim, out, compiler="auto"):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    srcs = [*karl_sources(root), Path(cjson) / "cJSON.c"]
    if compiler == "auto":
        compiler = "msvc" if sys.platform == "win32" else "gcc"
    if compiler == "msvc":
        cl, env = msvc_env()
        exe = out / "profile_json_test.exe"
        cmd = [str(cl), "/nologo", "/TC", "/std:c17", "/experimental:c11atomics", "/O1", "/D_CRT_SECURE_NO_WARNINGS",
               f"/FI{Path(shim) / 'msvc_gnu.h'}", f"/I{shim}", f"/I{root / 'src'}", f"/I{cjson}",
               f"/I{root / 'tools' / 'profile_json_test'}", *map(str, srcs), f"/Fe{exe}", "/Fo" + str(out) + os.sep]
    else:
        cc = shutil.which("cc") or shutil.which("gcc")
        if not cc:
            raise ImportProblem("no cc / gcc on PATH")
        exe = out / "profile_json_test"
        env = dict(os.environ)
        cmd = [cc, "-std=gnu11", "-Wall", "-Wno-unused-function", "-O1", "-g", "-fsanitize=undefined",
               "-Wno-deprecated-declarations", "-I", str(root / "src"), "-I", str(cjson), "-I", str(shim),
               "-I", str(root / "tools" / "profile_json_test"), *map(str, srcs), "-o", str(exe)]
    result = subprocess.run(cmd, cwd=out, env=env, capture_output=True, text=True)
    if result.returncode:
        raise ImportProblem(f"build failed:\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}")
    return exe


def dump(exe, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([str(exe), str(folder)], capture_output=True, text=True)
    if result.returncode:
        raise ImportProblem(f"Karl's profile_json_test failed:\n{result.stdout[-3000:]}")
    return result.stdout


# ------------------------------------------------------------------ check and compare
def load_new(folder):
    """{file name: bytes} of a dump or Karl's own JSON, every file validated (ImportProblem lists all)."""
    files, problems = {}, []
    for path in sorted(Path(folder).glob("*.json")):
        if path.name.endswith(".windows.json") or path.name == "SOURCE.json":
            continue
        raw = path.read_bytes()
        try:
            doc = ap.read_json(raw, path.name)
        except ap.ProfileError as exc:
            problems.extend(exc.problems)
            continue
        found = ap.validate_karl(doc)
        problems.extend(f"{path.name}: {p}" for p in found)
        if not found and doc["id"] != path.stem:
            problems.append(f'{path.name}: says it is "{doc["id"]}"')
        files[path.name] = raw
    if problems:
        raise ImportProblem("Karl's files fail validation:\n" + "\n".join(f"  {p}" for p in problems))
    if not files:
        raise ImportProblem(f"{folder}: no profile JSON")
    return files


def _commands(doc):
    return [(ring.get("name"), [(c.get("name"), c.get("key"), c.get("phrase")) for c in ring.get("cmds") or ()])
            for ring in doc.get("rings") or ()]


def _wire_size(raw, name, sidecar):
    try:
        return len(ap._load_docs(raw, name, sidecar, "bundled", None).wire())
    except ap.ProfileError:
        return None


def summarize(old_dir, new_files, sidecar_dir, commit):
    """Markdown: what changed against the previous import."""
    old_dir, sidecar_dir = Path(old_dir), Path(sidecar_dir)
    old = {p.name: p.read_bytes() for p in sorted(old_dir.glob("*.json")) if p.name != "SOURCE.json"} \
        if old_dir.is_dir() else {}
    lines = [f"Karl's profiles at `{commit[:12]}` ({KARL_REPO}, `{KARL_BRANCH}`).", ""]
    changed = False
    for name in sorted(set(old) | set(new_files)):
        pid = name[:-5]
        before, after = old.get(name), new_files.get(name)
        if before == after:
            lines.append(f"- `{pid}`: unchanged ({len(after)} B)")
            continue
        changed = True
        if before is None:
            lines.append(f"- `{pid}`: **added** ({len(after)} B)")
        elif after is None:
            lines.append(f"- `{pid}`: **removed** (was {len(before)} B)")
            continue
        else:
            lines.append(f"- `{pid}`: changed, {len(before)} -> {len(after)} B")
        new_doc = json.loads(after)
        old_doc = json.loads(before) if before else {}
        old_rings, new_rings = dict(_commands(old_doc)), dict(_commands(new_doc))
        for ring in [r for r in new_rings if r not in old_rings]:
            lines.append(f"  - ring added: {ring} ({len(new_rings[ring])} commands)")
        for ring in [r for r in old_rings if r not in new_rings]:
            lines.append(f"  - ring removed: {ring}")
        for ring, cmds in new_rings.items():
            if ring not in old_rings:
                continue
            was = old_rings[ring]
            old_names = [c[0] for c in was]
            new_names = [c[0] for c in cmds]
            gone = [n for n in old_names if n not in new_names]
            came = [n for n in new_names if n not in old_names]
            for i, (name_new, key, phrase) in enumerate(cmds):
                if name_new in came and i < len(was) and was[i][0] in gone and (was[i][1], was[i][2]) == (key, phrase):
                    lines.append(f"  - {ring}: renamed {was[i][0]} -> {name_new}")
                    gone.remove(was[i][0])
                    came.remove(name_new)
            lines += [f"  - {ring}: command added: {n}" for n in came]
            lines += [f"  - {ring}: command removed: {n}" for n in gone]
            for c_new in cmds:
                c_old = next((c for c in was if c[0] == c_new[0]), None)
                if c_old and c_old != c_new:
                    lines.append(f"  - {ring}/{c_new[0]}: key or phrase changed")
        sidecar = sidecar_dir / f"{pid}.windows.json"
        if sidecar.is_file():
            try:
                problems = ap.validate_overlay(ap.read_json(sidecar, sidecar.name), new_doc)
            except ap.ProfileError as exc:
                problems = exc.problems
            for p in problems:
                lines.append(f"  - **broken sidecar reference** in {sidecar.name}: {p}")
        old_wire = _wire_size(before, name, sidecar if sidecar.is_file() else None) if before else None
        new_wire = _wire_size(after, name, sidecar if sidecar.is_file() else None)
        if old_wire != new_wire:
            lines.append(f"  - wire profile: {old_wire or '-'} -> {new_wire or 'does not compile'} B")
    if not changed:
        lines.append("")
        lines.append("No change.")
    return "\n".join(lines) + "\n", changed


def source_record(commit, files, origin):
    return {"repo": KARL_REPO, "branch": KARL_BRANCH, "commit": commit, "origin": origin,
            "exporter": "tools/profiles/import_karl.py (Karl's tools/profile_json_test, unchanged)",
            "cjson": CJSON_TAG,
            "files": {name: {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
                      for name, raw in sorted(files.items())}}


def write_out(out, files, record, changed=True):
    """Write the profiles and SOURCE.json. With no profile changed, an existing SOURCE.json is kept as it is: it names
    the commit the files were imported from, and rewriting only its commit field for an unrelated commit of Karl's
    would give the Action a diff and open a review PR with nothing to review. True when SOURCE.json was kept."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name, raw in files.items():
        ap._atomic_write(out / name, raw)
    for stale in out.glob("*.json"):
        if stale.name not in files and stale.name != "SOURCE.json":
            stale.unlink()
    if not changed and (out / "SOURCE.json").is_file():
        return True
    ap._atomic_write(out / "SOURCE.json", (json.dumps(record, indent=2) + "\n").encode("ascii"))
    return False


# ------------------------------------------------------------------ main
def run(args, work):
    work = Path(work)
    if args.from_json:
        dump_dir = Path(args.from_json)
        commit = args.commit or (karl_commit(args.karl) if args.karl else "unknown")
        origin = "json"
    else:
        if args.karl:
            tree = Path(args.karl)
        else:
            tree = clone(work / "karl", args.ref)
        root = karl_root(tree)
        commit = args.commit or karl_commit(tree)
        cjson = check_cjson(args.cjson) if args.cjson else fetch_cjson(work / "cjson")
        shim = write_shims(work / "shim")
        exe = build(root, cjson, shim, work / "build", args.compiler)
        dump_dir = work / "json"
        print(dump(exe, dump_dir), end="")
        origin = "built-ins"
    files = load_new(dump_dir)
    summary, changed = summarize(args.out, files, args.sidecars, commit)
    if write_out(args.out, files, source_record(commit, files, origin), changed):
        kept = json.loads((Path(args.out) / "SOURCE.json").read_text(encoding="ascii")).get("commit", "?")
        summary += f"SOURCE.json kept (still `{kept}`): no profile changed, so there is nothing to review.\n"
    if args.summary:
        Path(args.summary).write_text(summary, encoding="ascii", newline="\n")
    print(summary, end="")
    return changed


def parser():
    p = argparse.ArgumentParser(description="Import Karl's app profiles as JSON (profiles/karl).")
    p.add_argument("--karl", help="Karl's clone (repo root or NanoDepsidf); default: clone it")
    p.add_argument("--ref", help="a commit to check out after cloning")
    p.add_argument("--commit", help=argparse.SUPPRESS)
    p.add_argument("--out", default=str(ROOT / "profiles" / "karl"))
    p.add_argument("--sidecars", default=None, help="the sidecars' folder (default: --out's parent)")
    p.add_argument("--cjson", help="a folder with the pinned cJSON.c, cJSON.h and LICENSE")
    p.add_argument("--compiler", choices=("auto", "msvc", "gcc"), default="auto")
    p.add_argument("--from-json", help="import Karl's own JSON files from this folder (no build)")
    p.add_argument("--summary", help="also write the change summary here (Markdown)")
    p.add_argument("--keep", help="keep the work folder here")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    args.sidecars = args.sidecars or str(Path(args.out).parent)
    try:
        check_ref(args.ref)
        if args.keep:
            Path(args.keep).mkdir(parents=True, exist_ok=True)
            run(args, args.keep)
        else:
            with tempfile.TemporaryDirectory(prefix="karl-import-") as work:
                run(args, work)
    except (ImportProblem, subprocess.CalledProcessError, OSError) as exc:
        print(f"PROBLEM  {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
