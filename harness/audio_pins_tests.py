"""Audio lane source pins: every CCSoundCounters field reaches diag. Python stdlib only; no device, no USB.

FW-BUG-021: CCSoundRing::popNext counts the waiting requests a louder (or newer, equal) one outranked. The count
must be visible on the device as diag `audioSuperseded`, like the other counters (audioReady, audioPlayed,
audioUnderruns, audioDropped). This pins the chain end to end:
  1. audio.h CCSoundCounters declares the field and audio.cpp counters() fills it (F6, always checked);
  2. cc_diag.cpp publishes d["audio<Field>"] = sound.<field> and cc_diag.h lists the key (F2, cc_diag.*);
  3. CONTROL_CENTER.md and HAPTICS.md document the key (docs).
Steps 2 and 3 belong to other lanes. Without --strict a missing key there prints PENDING and does not fail the run,
so this file can land before the F2 change; the integration stage runs it with --strict.

Usage: python audio_pins_tests.py [--strict]
Exit status is non-zero on any failure.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parent
firmware = root.parent / 'firmware'


def code(text: str) -> str:
    """The source without comments, whitespace collapsed."""
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    text = re.sub(r'//[^\n]*', ' ', text)
    return re.sub(r'\s+', ' ', text)


def counter_fields(header: str) -> list[str]:
    m = re.search(r'struct CCSoundCounters \{(.*?)\};', code(header))
    if not m:
        raise SystemExit('FAIL: struct CCSoundCounters not found in audio.h')
    return re.findall(r'\b(?:uint32_t|bool)\s+(\w+)\s*;', m.group(1))


def main(argv: list[str]) -> int:
    strict = '--strict' in argv
    src = firmware / 'src'
    fails: list[str] = []
    pending: list[str] = []
    checks = 0

    def check(ok: bool, msg: str, own: bool = True) -> None:
        nonlocal checks
        checks += 1
        if not ok:
            (fails if own or strict else pending).append(msg)

    fields = counter_fields((src / 'audio' / 'audio.h').read_text(encoding='utf-8'))
    check('superseded' in fields, 'audio.h: CCSoundCounters has no `superseded` field')
    audio_cpp = code((src / 'audio' / 'audio.cpp').read_text(encoding='utf-8'))
    check('c.superseded = ring.superseded();' in audio_cpp, 'audio.cpp: counters() does not fill superseded')

    diag_cpp = code((src / 'cc_diag.cpp').read_text(encoding='utf-8'))
    diag_h = (src / 'cc_diag.h').read_text(encoding='utf-8')
    docs = {name: (firmware / name).read_text(encoding='utf-8') for name in ('CONTROL_CENTER.md', 'HAPTICS.md')}
    for field in fields:
        key = 'audio' + field[0].upper() + field[1:]
        check(re.search(r'd\["' + key + r'"\]\s*=\s*sound\.' + field + r'\s*;', diag_cpp) is not None,
              f'cc_diag.cpp: no d["{key}"] = sound.{field}; (F2)', own=False)
        check(f'"{key}"' in diag_h, f'cc_diag.h: key list lacks "{key}" (F2)', own=False)
    # The docs only need to name the new key (the older ones are already documented where they belong).
    for name, text in docs.items():
        check('audioSuperseded' in text, f'{name}: diag key audioSuperseded not documented (docs)', own=False)
    # HAPTICS.md Sound > Requests describes popNext's rule: the loudest waiting request, not the newest.
    requests = re.sub(r'\s+', ' ', docs['HAPTICS.md'])
    check('takes the newest one' not in requests, 'HAPTICS.md: Requests still says the HMI task takes the newest one',
          own=False)
    check('takes the loudest waiting one (the newest among equal gains)' in requests,
          'HAPTICS.md: Requests does not say the HMI task takes the loudest waiting one', own=False)

    for msg in pending:
        print('PENDING:', msg)
    for msg in fails:
        print('FAIL:', msg)
    status = 'FAIL' if fails else 'PASS'
    print(f'{status}: audio pins, {checks} checks, {len(fails)} failures, {len(pending)} pending other lanes'
          f'{" (strict)" if strict else ""}')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
