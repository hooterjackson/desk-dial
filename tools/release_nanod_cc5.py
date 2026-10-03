"""Record one public release of the Desk Dial + knob pair in firmware/release.json (FW-PUB-004).

Reads the packaged manifest of the chosen binary of the current release (publicVersion and reportedVersion, written
by package_nanod_cc5.py) and Desk Dial's ProductVersion (desktop-version.txt), checks the release rules
(tooling.release_version_problems: ProductVersion == the public version, the reported firmware string starts with it
and ends with the binary letter, no internal cc id in a public version, one SHA-256 per version) and, with --write,
writes release.json. A public version already recorded for another image stops: a changed image needs a new public
version. No port, no device, no build. Without --write it only prints what it would record.
"""
import argparse
import json
import sys

import nanod_cc5_tooling as t


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    choices = t.binary_choices(t.CURRENT)
    parser.add_argument("--binary", choices=list(choices) or None,
                        default="F" if "F" in choices else (choices or (None,))[0],
                        help="the binary this release ships (default: F, the shipped binary)")
    parser.add_argument("--write", action="store_true", help="write release.json (default: print only)")
    args = parser.parse_args(argv)
    p = t.CURRENT.binary_profile(args.binary) if args.binary else t.CURRENT
    if not p.manifest.is_file():
        raise SystemExit(f"{p.manifest.name} is missing; package the binary first")
    product = t.desktop_product_version()
    entry = t.release_entry(t.load_json(p.manifest), product)
    record = t.load_json(t.RELEASE_RECORD) if t.RELEASE_RECORD.is_file() else {}
    updated = t.add_release(record, entry)
    problems = t.release_version_problems(updated, product)
    print(json.dumps(entry, indent=2))
    if problems:
        raise SystemExit("release.json would break the release rules: " + "; ".join(problems))
    if args.write:
        if t.RELEASE_RECORD.is_file():
            t.archive_existing(t.RELEASE_RECORD)
        t.RELEASE_RECORD.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {t.RELEASE_RECORD.name}: {entry['version']} = {entry['firmware']['reportedVersion']}")
    else:
        print("Not written (pass --write).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
