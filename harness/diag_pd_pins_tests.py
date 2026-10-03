"""FW-BUG-022 diag pins (lane F2: cc_diag.*). Python stdlib (+ the xtensa toolchain for --firmware-syntax).

foc_thread.cpp picks the motor driver's supply from the PD contract read at boot through
cc_boot_pd_contract() (declared locally there), and init_pd() flags a sink PDO table rewrite through
cc_boot_pd_nvm_rewritten(). These rules pin, over comment-stripped source:
  1. cc_diag.h declares both, with the exact signature foc_thread.cpp declares (else the firmware does not link);
  2. cc_diag.cpp defines them: the return is pdChecked && pdRead, position is RDO bits 30:28, millivolts the
     sink PDO voltage, nvmRewritten a flag only cc_boot_pd_nvm_rewritten() sets;
  3. cc_diag_live() reports supplyAssumed next to supplyVolts;
  4. (lane F8) hmi_thread.cpp init_pd() reads the contract before the NVM write, rewrites exactly when the sink
     table is not ours, and calls cc_boot_pd_nvm_rewritten() before cc_boot_pd() stores the pre-rewrite read;
     --strict turns PENDING into a failure.
--firmware-syntax: also syntax-checks cc_diag.cpp and foc_thread.cpp (media_tests.firmware_syntax).
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

SIGNATURE = r'bool\s+cc_boot_pd_contract\s*\(\s*uint32_t\s*&\s*position\s*,\s*uint32_t\s*&\s*millivolts\s*,\s*bool\s*&\s*nvmRewritten\s*\)'


def code(text: str) -> str:
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    return re.sub(r'//[^\n]*', ' ', text)


def read(name: str) -> str:
    return code((src / name).read_text(encoding='utf-8', errors='replace'))


def body(text: str, signature: str) -> str:
    match = re.search(signature + r'\s*\{', text)
    if not match:
        return ''
    start = match.end() - 1
    depth = 0
    for i in range(start, len(text)):
        depth += {'{': 1, '}': -1}.get(text[i], 0)
        if depth == 0:
            return text[start:i + 1]
    return ''


def squash(text: str) -> str:
    return re.sub(r'\s+', '', text)


def rules(strict: bool) -> bool:
    header, unit, foc, hmi = (read(n) for n in ('cc_diag.h', 'cc_diag.cpp', 'foc_thread.cpp', 'hmi_thread.cpp'))
    ok = True

    def check(name: str, cond: bool, pending: bool = False) -> None:
        nonlocal ok
        status = 'PASS' if cond else ('PENDING' if pending and not strict else 'FAIL')
        if status == 'FAIL':
            ok = False
        print(f'{status} {name}')

    check('cc_diag.h declares cc_boot_pd_contract', re.search(SIGNATURE + r'\s*;', header) is not None)
    check('foc_thread.cpp declares the same signature', re.search(SIGNATURE + r'\s*;', foc) is not None)
    check('cc_diag.h declares cc_boot_pd_nvm_rewritten',
          re.search(r'void\s+cc_boot_pd_nvm_rewritten\s*\(\s*\)\s*;', header) is not None)
    contract = squash(body(unit, SIGNATURE))
    check('cc_boot_pd_contract is defined', bool(contract))
    check('  returns pdChecked && pdRead', 'power.pdChecked&&power.pdRead' in contract and 'returnread;' in contract)
    check('  position is RDO bits 30:28', '(power.pdRdo>>28)&0x7u' in contract and 'position=' in contract)
    check('  millivolts is the sink PDO voltage', 'millivolts=' in contract and 'power.pdMillivolts' in contract)
    check('  nvmRewritten is the rewrite flag', 'nvmRewritten=power.pdNvmRewritten;' in contract)
    rewritten = squash(body(unit, r'void\s+cc_boot_pd_nvm_rewritten\s*\(\s*\)'))
    check('cc_boot_pd_nvm_rewritten sets the flag', rewritten == '{power.pdNvmRewritten=true;}')
    check('the flag defaults to false', re.search(r'bool\s+pdNvmRewritten\s*=\s*false\s*;', unit) is not None)
    check('only cc_boot_pd_nvm_rewritten writes the flag',
          len(re.findall(r'pdNvmRewritten\s*=(?!=)', unit)) == 2)   # the default and the setter
    live = squash(body(unit, r'void\s+cc_diag_live\s*\([^)]*\)'))
    check('cc_diag_live reports supplyAssumed after supplyVolts',
          'd["supplyAssumed"]=feel.supplyAssumed;' in live
          and live.find('d["supplyVolts"]') < live.find('d["supplyAssumed"]'))
    init_pd = squash(body(hmi, r'PowerType\s+HmiThread::init_pd\s*\(\s*\)'))
    # Lane F8 (6a3b774): the contract is read BEFORE the NVM write, and the store gets that read plus the flag.
    rdo_read = init_pd.find('constboolrdoOk=stusb_read32(kStusbRdoStatus,rdo);')
    nvm_write = init_pd.find('usb_pd.write();')
    flag = init_pd.find('if(nvmRewritten)cc_boot_pd_nvm_rewritten();')
    store = init_pd.find('cc_boot_pd(rdoOk,rdo,millivolts);')
    check('hmi_thread.cpp init_pd() reads the RDO before the NVM write (lane F8)',
          rdo_read >= 0 and nvm_write >= 0 and rdo_read < nvm_write, pending=True)
    check('hmi_thread.cpp init_pd() rewrites exactly when the sink table is not ours (lane F8)',
          'constboolnvmRewritten=!sinkTableOurs;' in init_pd and 'if(nvmRewritten){' in init_pd, pending=True)
    check('hmi_thread.cpp init_pd() flags the rewrite before it stores the read, once (lane F8)',
          flag >= 0 and store > flag and init_pd.count('cc_boot_pd_nvm_rewritten()') == 1
          and init_pd.count('cc_boot_pd(') == 1, pending=True)
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--firmware-syntax', action='store_true')
    parser.add_argument('--strict', action='store_true')
    args = parser.parse_args()
    ok = rules(args.strict)
    if args.firmware_syntax:
        ok &= media_tests.firmware_syntax(['cc_diag.cpp', 'foc_thread.cpp'])
    print(f'{"PASS" if ok else "FAIL"}: diag PD pins')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
