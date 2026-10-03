"""TL-TST-001 comment pin: haptic.cpp's legacy-loop move() comment names rest sleep.

The comment above the legacy loop's output once claimed the PID output alone was "exactly 1.0.0-cc5.6". Rest sleep
(ID-REST-250MS) now also zeroes the output and resets the PID while the knob rests, so the comment must say so, and
the rest gate it describes must still sit before the one move().
"""
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parent
firmware = root.parent / 'firmware'


def main() -> int:
    fails: list[str] = []
    src = (firmware / 'src' / 'haptic.cpp').read_text(encoding='utf-8')
    if 'is below the cap: exactly 1.0.0-cc5.6.' in src:
        fails.append('haptic.cpp: the legacy-loop comment still claims the output is exactly 1.0.0-cc5.6')
    comment = re.search(r'// 1\.0\.0-cc5\.7: a host effect \(frame `haptic`\) adds its pulses to the PID output.*?\n'
                        r'((?:\s*//[^\n]*\n)+)\s*const uint32_t now = micros\(\);', src)
    if not comment or 'rest sleep' not in comment.group(0) or 'resets the PID' not in comment.group(0) \
            or 'zeroes the output' not in comment.group(0):
        fails.append('haptic.cpp: the legacy-loop comment does not say rest sleep zeroes the output and resets the PID')
    if not re.search(r'out = 0\.0f;\s*haptic_pid->reset\(\);\s*\}\s*motor->move\(out > CC_HAPTIC_CAP_AMPS', src):
        fails.append('haptic.cpp: the rest gate (out = 0, PID reset) no longer sits before the legacy move()')
    for msg in fails:
        print('FAIL:', msg)
    print(f'{"FAIL" if fails else "PASS"}: haptic rest comment pins, 3 checks, {len(fails)} failures')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
