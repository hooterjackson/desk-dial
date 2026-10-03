"""FW-BUG-017 diag pins (lane F2: cc_diag.*). Python stdlib (+ the xtensa toolchain for --firmware-syntax).

main.cpp's cc_lvgl_layout_ok() compares LVGL's compiled lv_obj_t size with src/'s; lcd_thread.cpp halts the screen
when they differ. These rules pin, over comment-stripped source, that {"diag":"?"} reports it:
  1. cc_diag.cpp includes nanofoc_d.h (the declaration) and cc_diag_boot() sets
     lvglLayout = cc_lvgl_layout_ok() ? "ok" : "mixed";
  2. control_center.cpp calls cc_diag_boot() for the diag reply;
  3. cc_lvgl_layout_ok() is declared in nanofoc_d.h and defined in main.cpp from lv_obj_class.instance_size.
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

firmware = media_tests.firmware


def code(text: str) -> str:
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    return re.sub(r'//[^\n]*', ' ', text)


def flat(rel: str) -> str:
    return re.sub(r'\s+', '', code((firmware / rel).read_text(encoding='utf-8', errors='replace')))


def boot_body(unit: str) -> str:
    match = re.search(r'voidcc_diag_boot\(JsonObjectd\)\{(.*?)\n?\}(?=namespace|void|$)', unit, flags=re.S)
    return match.group(1) if match else ''


def rules() -> bool:
    unit = flat('src/cc_diag.cpp')
    cc = flat('src/control_center.cpp')
    header = flat('include/nanofoc_d.h')
    main_cpp = flat('src/main.cpp')
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        ok &= cond
        print(f'{"PASS" if cond else "FAIL"} {name}')

    body = boot_body(unit)
    check('cc_diag.cpp includes nanofoc_d.h', '#include"nanofoc_d.h"' in unit)
    check('cc_diag_boot() found', bool(body))
    check('cc_diag_boot() reports lvglLayout ok/mixed',
          'd["lvglLayout"]=cc_lvgl_layout_ok()?"ok":"mixed";' in body)
    check('control_center.cpp calls cc_diag_boot(d)', 'cc_diag_boot(d);' in cc)
    check('nanofoc_d.h declares cc_lvgl_layout_ok()', 'boolcc_lvgl_layout_ok();' in header)
    check('main.cpp defines it from lv_obj_class.instance_size',
          'boolcc_lvgl_layout_ok(){returnlv_obj_class.instance_size==sizeof(lv_obj_t);}' in main_cpp)
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--firmware-syntax', action='store_true')
    args = parser.parse_args()
    ok = rules()
    if args.firmware_syntax:
        ok &= media_tests.firmware_syntax(['cc_diag.cpp'])
    print(f'{"PASS" if ok else "FAIL"}: diag lvglLayout pins')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
