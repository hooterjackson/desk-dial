"""FW-BUG-030 diag pins (lane F2: cc_diag.*). Python stdlib (+ the xtensa toolchain for --firmware-syntax).

The FOC task publishes motorReady (SimpleFOC motor_status == motor_ready) and motorCal (cc_boot_cal.h CCMotorCal)
through cc_foc_feel_diag(). These rules pin, over comment-stripped source:
  1. cc_diag_live() reports motorReady from feel.motorReady and motorCal as a name of feel.motorCal;
  2. the name table follows the CCMotorCal enum order exactly: starting, aligning, ready, unstored, failed;
  3. an out-of-range value never indexes past the table (name_of bounds check);
  4. the CCFocFeelDiag struct carries both fields and foc_thread.cpp fills them.
--firmware-syntax: also syntax-checks cc_diag.cpp (media_tests.firmware_syntax).
Exit status is non-zero on any failure.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
import media_tests  # noqa: E402

src = media_tests.firmware / 'src'
NAMES = ['starting', 'aligning', 'ready', 'unstored', 'failed']


def code(text: str) -> str:
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    return re.sub(r'//[^\n]*', ' ', text)


def read(name: str) -> str:
    return code((src / name).read_text(encoding='utf-8', errors='replace'))


def squash(text: str) -> str:
    return re.sub(r'\s+', '', text)


def enum_order(header: str) -> list[str]:
    match = re.search(r'enum\s+CCMotorCal\s*:\s*uint8_t\s*\{(.*?)\}', header, flags=re.S)
    if not match:
        return []
    names = [part.split('=')[0].strip() for part in match.group(1).split(',') if part.strip()]
    return [n.replace('CC_MOTOR_CAL_', '').lower() for n in names]


def rules() -> bool:
    unit, cal, foc_h, foc = (read(n) for n in ('cc_diag.cpp', 'cc_boot_cal.h', 'foc_thread.h', 'foc_thread.cpp'))
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        if not cond:
            ok = False
        print(f'{"PASS" if cond else "FAIL"} {name}')

    flat = squash(unit)
    check('cc_diag.cpp includes cc_boot_cal.h', '#include"cc_boot_cal.h"' in flat)
    check('diag motorReady = feel.motorReady', 'd["motorReady"]=feel.motorReady;' in flat)
    check('diag motorCal = name_of(kMotorCal, feel.motorCal)', 'd["motorCal"]=name_of(kMotorCal,feel.motorCal);' in flat)
    table = re.search(r'kMotorCal\[\]=\{([^}]*)\}', flat)
    got = re.findall(r'"([^"]*)"', table.group(1)) if table else []
    check(f'kMotorCal is {NAMES}', got == NAMES)
    check('CCMotorCal enum order matches the names', enum_order(cal) == NAMES)
    check('a static_assert ties the table to the enum',
          'static_assert(CC_MOTOR_CAL_STARTING==0&&CC_MOTOR_CAL_ALIGNING==1&&CC_MOTOR_CAL_READY==2&&'
          'CC_MOTOR_CAL_UNSTORED==3&&CC_MOTOR_CAL_FAILED==4' in flat)
    check('name_of bounds-checks the index', 'returnindex<N?names[index]:"?";' in flat)
    check('CCFocFeelDiag has motorReady and motorCal',
          re.search(r'bool\s+motorReady\s*;', foc_h) is not None and re.search(r'uint8_t\s+motorCal\s*;', foc_h) is not None)
    check('foc_thread.cpp copies both into the diag snapshot',
          'out.motorReady=feel_diag.motorReady;' in squash(foc) and 'out.motorCal=feel_diag.motorCal;' in squash(foc))
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--firmware-syntax', action='store_true')
    args = parser.parse_args()
    ok = rules()
    if args.firmware_syntax:
        ok &= media_tests.firmware_syntax(['cc_diag.cpp'])
    print(f'{"PASS" if ok else "FAIL"}: diag motor calibration pins')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
