"""FW-PUB-004 diag pins (lane F2: cc_diag.*). Python stdlib (+ the xtensa toolchain for --firmware-syntax).

Settings "firmwareVersion" now carries the public version ("<public>+<build id>.<letter>", cc_fw_version.h), so the
diag keeps the internal build id visible. These rules pin, over comment-stripped source:
  1. cc_diag_boot() writes "firmwareBuild" = cc_fw_build() (cc_fw_version.h: NANO_FIRMWARE_VERSION, the internal
     id), never the public cc_fw_version(); cc_diag_lcd_pipeline() stays the one cc_lcd_perf_read() copy
     (alive_tests) and no src unit names NANO_FIRMWARE_VERSION itself (boot_pins_tests);
  2. platformio.ini still defines NANO_FIRMWARE_VERSION (else cc_fw_build() does not exist);
  3. control_center.cpp still calls cc_diag_boot() for the diag reply.
--firmware-syntax: also syntax-checks cc_diag.cpp with its PlatformIO line (media_tests.firmware_syntax).
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
from diag_pd_pins_tests import body, code, squash  # noqa: E402

src = media_tests.firmware / 'src'


def rules() -> bool:
    unit = code((src / 'cc_diag.cpp').read_text(encoding='utf-8', errors='replace'))
    center = code((src / 'control_center.cpp').read_text(encoding='utf-8', errors='replace'))
    ini = (media_tests.firmware / 'platformio.ini').read_text(encoding='utf-8', errors='replace')
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        if not cond:
            ok = False
        print(f'{"PASS" if cond else "FAIL"} {name}')

    boot = squash(body(unit, r'void\s+cc_diag_boot\s*\(\s*JsonObject\s+d\s*\)'))
    header = code((src / 'cc_fw_version.h').read_text(encoding='utf-8', errors='replace'))
    check('cc_diag_boot is defined', bool(boot))
    check('  writes "firmwareBuild" = cc_fw_build()', 'd["firmwareBuild"]=cc_fw_build();' in boot)
    check('  "firmwareBuild" is written once in cc_diag.cpp', unit.count('"firmwareBuild"') == 1)
    check('  the internal id, not the public version', 'cc_fw_version(' not in boot)
    check('cc_diag.cpp includes cc_fw_version.h', '#include "cc_fw_version.h"' in unit)
    check('cc_fw_build() returns NANO_FIRMWARE_VERSION',
          'inline const char* cc_fw_build() { return NANO_FIRMWARE_VERSION; }' in header)
    check('platformio.ini defines NANO_FIRMWARE_VERSION',
          re.search(r'^\s*-DNANO_FIRMWARE_VERSION=\S+\s*$', ini, flags=re.M) is not None)
    check('control_center.cpp calls cc_diag_boot(d)', 'cc_diag_boot(d);' in center)
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--firmware-syntax', action='store_true')
    args = parser.parse_args()
    ok = rules()
    if args.firmware_syntax:
        ok &= media_tests.firmware_syntax(['cc_diag.cpp'])
    print(f'{"PASS" if ok else "FAIL"}: diag build pins')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
