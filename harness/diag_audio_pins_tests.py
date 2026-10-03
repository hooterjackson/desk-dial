"""FW-BUG-021 diag pins (lane F2: cc_diag.*, plus CONTROL_CENTER.md). Python stdlib only.

The sound ring (audio/cc_sound.h CCSoundRing::popNext) plays the loudest waiting request, the newest among equal
gains, and counts the others as superseded. These rules pin that the counter reaches the diag and its docs:
  1. cc_diag.cpp cc_diag_live() publishes d["audioSuperseded"] = sound.superseded (comment-stripped source);
  2. popNext() still picks with >= on gain (newest among equals), the behaviour the docs describe;
  3. cc_diag.h's diag key list names "audioSuperseded" with both cases (louder one; newer one of equal gain);
  4. CONTROL_CENTER.md's additive Diag key list names `audioSuperseded` with both cases.
Exit status is non-zero on any failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
firmware = root.parent / 'firmware'
src = firmware / 'src'


def raw(path: Path) -> str:
    return path.read_text(encoding='utf-8', errors='replace')


def code(text: str) -> str:
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    return re.sub(r'//[^\n]*', ' ', text)


def flat(text: str) -> str:
    text = re.sub(r'//', ' ', text)
    return re.sub(r'\s+', ' ', text)


def main() -> int:
    failures: list[str] = []

    diag_cpp = code(raw(src / 'cc_diag.cpp'))
    if not re.search(r'd\s*\[\s*"audioSuperseded"\s*\]\s*=\s*sound\.superseded\s*;', diag_cpp):
        failures.append('cc_diag.cpp: cc_diag_live() must publish d["audioSuperseded"] = sound.superseded')

    ring = code(raw(src / 'audio' / 'cc_sound.h'))
    if not re.search(r'\.gain\s*>=\s*slots_\s*\[\s*best\s*%\s*CC_SOUND_RING\s*\]\s*\.gain', ring):
        failures.append('audio/cc_sound.h: popNext() must keep the newest among equal gains (>=); '
                        'update the audioSuperseded docs if this changes')

    both = re.compile(r'audioSuperseded.{0,40}?outranked by a louder one, or by a newer one of equal gain')
    header = flat(raw(src / 'cc_diag.h'))
    if not both.search(header):
        failures.append('cc_diag.h: the diag key list must describe "audioSuperseded" '
                        '(outranked by a louder one, or by a newer one of equal gain)')

    doc = flat(raw(firmware / 'CONTROL_CENTER.md'))
    m = re.search(r'\*\*Diag\*\* \(additive\):(.*?)Compatibility:', doc)
    if not m:
        failures.append('CONTROL_CENTER.md: no "**Diag** (additive):" key list found')
    elif not both.search(m.group(1)):
        failures.append('CONTROL_CENTER.md: the additive Diag key list must name `audioSuperseded` '
                        '(outranked by a louder one, or by a newer one of equal gain)')

    for f in failures:
        print('FAIL: ' + f, flush=True)
    if failures:
        return 1
    print('PASS: diag_audio_pins_tests (audioSuperseded published and documented, FW-BUG-021)', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
