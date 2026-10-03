"""FW-BUG-001 pins for the units the COM task calls (DeviceSettings.cpp, HapticProfileManager.cpp,
HapticProfileUpdater.cpp). Python stdlib only; the host cannot compile these units whole with SPIFFS.

Each unit runs its diagnostics on the COM task (save / load / profile updates), so it must write them
through cc_send_note() (the bounded writer in cc_serial_out.*) and never through a raw Serial print or
serializeJson(..., Serial). Comments are stripped first. Exit status is non-zero on any failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
src = root.parent / 'firmware' / 'src'

RAW_WRITE = re.compile(r'serializeJson\s*\([^;]*,\s*Serial\s*\)|Serial\s*\.\s*(?:print|println|printf|write)\s*\(')
NOTE = re.compile(r'\bcc_send_note\s*\(')
INCLUDE = re.compile(r'#\s*include\s*"(?:\./)?cc_serial_out\.h"')
# Minimum cc_send_note() calls per unit: the diagnostics the finding counted (some prints were joined
# into one note per message, so the floor is the number of messages, not of print calls).
UNITS = {'DeviceSettings.cpp': 11, 'HapticProfileManager.cpp': 10, 'HapticProfileUpdater.cpp': 1}


def code(text: str) -> str:
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    return re.sub(r'//[^\n]*', ' ', text)


def check(name: str, text: str, floor: int) -> list[str]:
    body = code(text)
    errors = []
    raw = [m.group(0) for m in RAW_WRITE.finditer(body)]
    if raw:
        errors.append(f'{name}: raw serial write on a COM path {raw}')
    if not INCLUDE.search(body):
        errors.append(f'{name}: does not include cc_serial_out.h')
    notes = len(NOTE.findall(body))
    if notes < floor:
        errors.append(f'{name}: {notes} cc_send_note() calls, expected at least {floor}')
    return errors


def self_test() -> None:
    """The rules catch the regression they pin."""
    bad = '#include "cc_serial_out.h"\nvoid f(){ Serial.println("x"); cc_send_note("y"); }'
    assert check('bad', bad, 1), 'a raw Serial.println passed'
    assert check('json', '#include "cc_serial_out.h"\nvoid f(){ serializeJson(doc, Serial); cc_send_note("y"); }', 1)
    assert check('noinc', 'void f(){ cc_send_note("y"); }', 1), 'a missing include passed'
    good = '#include "./cc_serial_out.h"\nvoid f(){ // Serial.println("old")\n cc_send_note("y"); }'
    assert not check('good', good, 1), 'a commented-out print failed'


def main() -> int:
    self_test()
    ok = True
    for name, floor in UNITS.items():
        errors = check(name, (src / name).read_text(encoding='utf-8', errors='replace'), floor)
        for error in errors:
            print(f'FAIL FW-BUG-001: {error}')
        if not errors:
            print(f'PASS FW-BUG-001: {name} writes its diagnostics only through cc_send_note()')
        ok &= not errors
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
