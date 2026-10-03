"""Profile save pins (FW-SEC-001 follow-up). Python stdlib only, no build.

{"save":true} stores the current profile's name in the settings so the next boot selects it.
When every profile was deleted, the current profile could sit on a freed (blank) slot; storing
its empty name would make the next boot select nothing. The save branch of com_thread.cpp must
therefore call DeviceSettings::storeCurrentProfile() only for a non-null current profile with a
non-empty name (and, per FW-BUG-005, only once that profile is on flash).

Exit status is non-zero on any failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
from protocol_pins_tests import function_body, read  # noqa: E402  (read-only helpers)


def save_branch(com: str) -> str:
    """The body of `if (doc["save"]) {...}` in ComThread's line handler."""
    return function_body(com, r'if\s*\(\s*doc\s*\[\s*"save"\s*\]\s*\)\s*\{')


def guard_of(body: str, call: str) -> str:
    """The condition of the `if (...)` that directly precedes `call` (empty when the call is unguarded)."""
    at = body.find(call)
    if at < 0:
        return ''
    before = body[:at]
    match = None
    for match in re.finditer(r'\bif\s*\(', before):
        pass
    if match is None:
        return ''
    depth, i = 0, match.end() - 1
    for i in range(match.end() - 1, len(before)):
        depth += {'(': 1, ')': -1}.get(before[i], 0)
        if depth == 0:
            break
    condition = before[match.end():i]
    between = before[i + 1:].strip()
    # The guarded statement must follow the condition directly (single statement or an opening brace).
    if between not in ('', '{') and not between.startswith('DeviceSettings'):
        return ''
    return condition


def check(com: str) -> list[str]:
    failures = []
    body = save_branch(com)
    if not body:
        return ['the {"save":true} branch was not found in com_thread.cpp']
    call = 'storeCurrentProfile('
    if body.count(call) != 1:
        failures.append(f'expected one storeCurrentProfile() call in the save branch, found {body.count(call)}')
        return failures
    condition = guard_of(body, call)
    var = re.search(r'storeCurrentProfile\s*\(\s*(\w+)\s*->\s*profile_name', body)
    name = var.group(1) if var else ''
    if not name:
        failures.append('storeCurrentProfile() is not given <current>->profile_name')
        return failures
    if not re.search(rf'\b{name}\s*=\s*pm\s*\.\s*getCurrentProfile\s*\(\s*\)', body):
        failures.append(f'{name} is not taken from pm.getCurrentProfile()')
    if not re.search(rf'\b{name}\s*!=\s*nullptr', condition):
        failures.append(f'storeCurrentProfile() is not guarded by {name}!=nullptr (guard: {condition!r})')
    if not (re.search(rf'\b{name}\s*->\s*profile_name\s*\.\s*length\s*\(\s*\)\s*>\s*0', condition)
            or re.search(rf'isProfileNameOk\s*\(\s*{name}\s*->\s*profile_name\s*\)', condition)):
        failures.append(f'storeCurrentProfile() is not guarded by a non-empty name (guard: {condition!r})')
    if not re.search(rf'!\s*{name}\s*->\s*dirty', condition):
        failures.append(f'storeCurrentProfile() is not guarded by !{name}->dirty (FW-BUG-005)')
    return failures


def self_test() -> list[str]:
    """The rule must reject the unguarded and the null-only forms."""
    failures = []
    head = 'void f(){ if (doc["save"]) { if (x) { HapticProfile* current = pm.getCurrentProfile();\n'
    tail = ' } } }'
    bad = {
        'unguarded': head + 'DeviceSettings::getInstance().storeCurrentProfile(current->profile_name);' + tail,
        'null only': head + 'if (current!=nullptr) DeviceSettings::getInstance()'
                            '.storeCurrentProfile(current->profile_name);' + tail,
    }
    for label, text in bad.items():
        if not check(text):
            failures.append(f'self-test: the {label} form was accepted')
    good = head + ('if (current!=nullptr && current->profile_name.length()>0 && !current->dirty)\n'
                   '  DeviceSettings::getInstance().storeCurrentProfile(current->profile_name);') + tail
    if check(good):
        failures.append(f'self-test: the guarded form was rejected: {check(good)}')
    return failures


def main() -> int:
    failures = self_test() + check(read('com_thread.cpp'))
    for failure in failures:
        print(f'FAIL FW-SEC-001: {failure}')
    if not failures:
        print('PASS FW-SEC-001: {"save":true} stores the current profile name only for a non-null, named, '
              'saved profile')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
