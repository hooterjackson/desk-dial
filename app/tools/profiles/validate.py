"""Check app profiles the way Desk Dial loads them (plan section 5c step 4; S1 DD-A).

Usage: python tools/profiles/validate.py <file or folder> [...]

* A folder: every Karl file in it (``karl/*.json`` and ``*.json``) with its sidecar ``<id>.windows.json``
  from the same folder, as ``app_profiles.Library`` pairs them (the bundled ``profiles/`` folder, an
  ``updates/`` or ``user/`` folder).
* A Karl file ``<id>.json``: checked, with its sidecar if one sits next to it or one folder up.
* A sidecar ``<id>.windows.json``: checked against its Karl file (next to it, or in ``karl/`` beside it).

Prints one line per profile (status, wire size, CRC, feature bits) and every problem in plain words.
Exit status 0 = all good, 1 = a problem, 2 = usage. The same code Desk Dial ships (control_center.app_profiles);
nothing is run from a profile.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center import app_profiles as ap  # noqa: E402


def _sidecar_for(karl_path, pid):
    for folder in (karl_path.parent, karl_path.parent.parent):
        candidate = folder / f"{pid}.windows.json"
        if candidate.is_file():
            return candidate
    return None


def _karl_for(sidecar_path):
    pid = sidecar_path.name[: -len(".windows.json")]
    for candidate in (sidecar_path.with_name(f"{pid}.json"), sidecar_path.parent / "karl" / f"{pid}.json"):
        if candidate.is_file():
            return candidate
    return None


def pairs(target):
    """(karl path, sidecar path or None) to check for a file or folder, or a problem string."""
    target = Path(target)
    if target.is_dir():
        out = []
        for karl in ap._karl_files(target):
            sidecar = target / f"{karl.stem}.windows.json"
            out.append((karl, sidecar if sidecar.is_file() else None))
        known = {k.stem for k, _ in out}
        for sidecar in sorted(target.glob("*.windows.json")):
            pid = sidecar.name[: -len(".windows.json")]
            if pid not in known:
                out.append(f"{sidecar.name}: no Karl file {pid}.json next to it or in karl/")
        return out or [f"{target}: no profiles in this folder"]
    if not target.is_file():
        return [f"{target}: no such file or folder"]
    if target.name.endswith(".windows.json"):
        karl = _karl_for(target)
        return [(karl, target)] if karl else [f"{target.name}: no Karl file for it next to it or in karl/"]
    return [(target, _sidecar_for(target, target.stem))]


def check(target):
    """(lines, problems) for one file or folder."""
    lines, problems = [], []
    for item in pairs(target):
        if isinstance(item, str):
            problems.append(item)
            continue
        karl, sidecar = item
        try:
            p = ap.load_pair(karl, sidecar)
        except ap.ProfileError as exc:
            problems.extend(exc.problems)
            continue
        if p.id != karl.stem:
            problems.append(f'{karl.name}: says it is "{p.id}" (the file name must be the id)')
            continue
        blob = p.wire()
        lines.append(f"ok  {p.id:<11} {p.status:<9} wire {len(blob):>5} B  crc 0x{p.wire_crc:08x}  "
                     f"features {p.features:>2}  rings {len(p.rings)}  "
                     f"{'sidecar ' + sidecar.name if sidecar else 'no sidecar'}")
        lines.extend(f"    warning: {w}" for w in p.warnings)
    return lines, problems


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    bad = False
    for target in argv:
        lines, problems = check(target)
        for line in lines:
            print(line)
        for problem in problems:
            print(f"PROBLEM  {problem}")
        bad = bad or bool(problems)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
