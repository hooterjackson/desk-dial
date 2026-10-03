"""lcd-preview README checks (HN-BUG-001). Python stdlib only; no build, no device.

1. Every script the README names exists (in lcd-preview/, or work/ for the workspace tools), so no instruction
   points at a removed script.
2. The retired Stage-1 contact_sheet.py (it read before-*.ppm rasters that main.cpp no longer writes and build.py
   deletes, and crashed with FileNotFoundError) is gone and the README no longer tells anyone to run it.

Exit status is non-zero on any failure.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parent
work = root.parent


def main() -> int:
    failures = []
    text = (root / 'README.md').read_text(encoding='utf-8')
    names = sorted(set(re.findall(r'(?<![\w/.-])([A-Za-z0-9_]+\.py)\b', text)))
    for name in names:
        if not ((root / name).is_file() or (work / 'tools' / name).is_file()):
            failures.append(f'README names {name}, which does not exist')
    if 'contact_sheet.py' in text:
        failures.append('README still names contact_sheet.py')
    if (root / 'contact_sheet.py').exists():
        failures.append('contact_sheet.py still exists (it reads before-*.ppm rasters nothing writes)')
    for f in failures:
        print('FAIL ' + f)
    print(f'{"PASS" if not failures else "FAIL"} README scripts: {len(names)} named, {len(failures)} failure(s)')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
