"""Write profiles/index.json, the list Desk Dial's optional profile fetch reads (plan section 5b; S1 DD-C).

Usage: python tools/profiles/make_index.py [--profiles DIR] [--desk-dial-min VERSION] [--check]

One entry per Karl file ``karl/<id>.json`` (``SOURCE.json`` is not a profile), sorted by id::

    {"id": "figma", "file": "karl/figma.json", "sha256": "...", "bytes": 18501, "desk_dial_min": "2.0.0",
     "overlay": {"file": "figma.windows.json", "sha256": "...", "bytes": 1234}}

Paths are relative to the repo's ``profiles/`` (``control_center.profile_updates.BASE_URL`` + the path is
the download). ``overlay`` is there when the sidecar ``<id>.windows.json`` is. ``desk_dial_min`` is the
oldest Desk Dial (public version) that reads these files: the first one with app profiles reads format 1
and overlay 1, so it only moves when the format does.

Every pair is validated with the code Desk Dial ships (``app_profiles.load_pair``) first; a bad pair is an
error and nothing is written. The output is deterministic (sorted keys, two-space indent, LF, a final
newline), so the public repo's Action can regenerate it and commit only real changes. ``--check`` writes
nothing and exits 1 when the file on disk differs. Exit 0 = written / up to date, 1 = a problem, 2 = usage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center import app_profiles as ap  # noqa: E402
from control_center import profile_updates as pu  # noqa: E402

DESK_DIAL_MIN = "2.0.0"


def _file(folder, rel):
    data = (folder / rel).read_bytes()
    return {"file": rel, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def build_index(profiles_dir, desk_dial_min=DESK_DIAL_MIN):
    """The index document for ``profiles_dir`` (the repo's profiles/). Raises ap.ProfileError."""
    profiles_dir = Path(profiles_dir)
    if pu.version_tuple(desk_dial_min) is None:
        raise ap.ProfileError(f"--desk-dial-min {desk_dial_min!r}: a version like 2.0.0")
    karl = profiles_dir / "karl"
    files = sorted(p for p in karl.glob("*.json") if p.name not in ("SOURCE.json", "index.json"))
    problems, entries = [], []
    for path in files:
        pid = path.stem
        if ap.reserved_id(path.name):
            problems.append(f"{path.name}: {ap.RESERVED_ID_PROBLEM}")          # DD-7: never opened
            continue
        sidecar = profiles_dir / f"{pid}.windows.json"
        try:
            profile = ap.load_pair(path, sidecar if sidecar.is_file() else None)
        except ap.ProfileError as exc:
            problems.extend(exc.problems)
            continue
        if profile.id != pid:
            problems.append(f"{path.name}: says it is \"{profile.id}\"")
            continue
        entry = {"id": pid, **_file(profiles_dir, f"karl/{path.name}"), "desk_dial_min": desk_dial_min}
        if sidecar.is_file():
            entry["overlay"] = _file(profiles_dir, sidecar.name)
        entries.append(entry)
    if len(entries) > pu.INDEX_PROFILES_MAX:
        problems.append(f"{len(entries)} profiles; Desk Dial reads up to {pu.INDEX_PROFILES_MAX}")
    if not entries and not problems:
        problems.append(f"{karl}: no Karl files")
    if problems:
        raise ap.ProfileError(problems)
    return {"format": pu.INDEX_FORMAT, "profiles": entries}


def render(index):
    text = json.dumps(index, indent=2, sort_keys=True) + "\n"
    data = text.encode("ascii")
    pu.parse_index(data)                      # what we write, Desk Dial must read (and within its cap)
    if len(data) > pu.INDEX_MAX:
        raise ap.ProfileError(f"index.json: {len(data)} bytes; Desk Dial reads up to {pu.INDEX_MAX}")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description="Write profiles/index.json")
    parser.add_argument("--profiles", default=str(ROOT / "profiles"))
    parser.add_argument("--desk-dial-min", default=DESK_DIAL_MIN)
    parser.add_argument("--check", action="store_true", help="exit 1 when index.json is out of date")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    folder = Path(args.profiles)
    try:
        data = render(build_index(folder, args.desk_dial_min))
    except ap.ProfileError as exc:
        for problem in exc.problems:
            print(problem, file=sys.stderr)
        return 1
    target = folder / "index.json"
    current = target.read_bytes() if target.is_file() else None
    if args.check:
        if current != data:
            print("profiles/index.json is out of date: run tools/profiles/make_index.py", file=sys.stderr)
            return 1
        print("profiles/index.json is up to date")
        return 0
    if current != data:
        ap._atomic_write(target, data)
        print(f"wrote {target} ({len(data)} bytes)")
    else:
        print("profiles/index.json is up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
