"""FOC thread source pins (lane F1: foc_thread.cpp). Python stdlib only.

foc_thread.cpp pulls in FreeRTOS and SimpleFOC, so the host cannot compile it; these rules read the
source (comments stripped). Each rule names the finding it pins. Exit status is non-zero on failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
src = root.parent / 'firmware' / 'src'


def code(text: str) -> str:
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    return re.sub(r'//[^\n]*', ' ', text)


def function_body(text: str, signature: str) -> str:
    match = re.search(signature, text)
    if not match:
        return ''
    start = text.index('{', match.end())
    depth = 0
    for i in range(start, len(text)):
        depth += {'{': 1, '}': -1}.get(text[i], 0)
        if depth == 0:
            return text[start:i + 1]
    return ''


def main() -> int:
    foc = code((src / 'foc_thread.cpp').read_text(encoding='utf-8', errors='replace'))
    body = re.sub(r'\s+', '', function_body(foc, r'void\s+FocThread::put_motor_command\s*\(\s*String\s*\*\s*\w+\s*\)'))
    failures = []
    if not body:
        failures.append('FW-RES-002: FocThread::put_motor_command not found')
    else:
        # The send's result is checked and the String is deleted when the 5-deep queue is full.
        if not re.search(r'xQueueSend\(_q_motor_in,&(\w+),\(TickType_t\)0\)!=pdTRUE\)\s*\{?delete\1;', body):
            failures.append('FW-RES-002: put_motor_command must delete the String when xQueueSend '
                            'to _q_motor_in fails (full queue leaks it)')
        if 'nullptr' not in body:
            failures.append('FW-RES-002: put_motor_command must still ignore a null message')
    # The consumer hands the String back to the COM task, which owns its deletion (no double free).
    if 'com_thread.put_string_message(smsg)' not in re.sub(r'\s+', '', foc):
        failures.append('FW-RES-002: FOC consumer no longer returns the String to the COM task')
    for f in failures:
        print('FAIL', f)
    print(f'foc_pins_tests: {"FAIL" if failures else "OK"} ({len(failures)} failure(s))')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
