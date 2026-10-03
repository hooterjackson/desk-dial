"""FW-RES-001: the LVGL pool after a soak (host harness evidence + firmware lv_conf.h source rules).

The knob (cc5.7 F) read lvglMinFree 28,476 B after 42 h against the 30,720 B gate of PRESENTATION_V5.md 12.2.
main.cpp replays every named timeline and every accepted case frame SOAK_ROUNDS more times after the evidence
run and writes the LVGL pool's used bytes after each round to render-index.json "soak". This checks:

1. no growth: every round ends within 1 KB of the first round and the rounds never grow monotonically
   (a renderer that allocates per frame, per screen change or per animation fails here);
2. the firmware pool: include/lv_conf.h LV_MEM_SIZE is at least 80 KB and its x64 host low-water projected onto
   that size (TLSF overhead as measured, sampled peak use; 8-byte pointers, so an upper bound for the
   ESP32-S3) keeps >= 30,720 B free;
3. the assert handler is abort() (a prompt, diagnosable reset), never a while(1) hang.

Usage: python display_soak_tests.py [harness-output-dir]   (default: rendered/, written by build.py)
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LV_CONF = ROOT.parent / 'firmware' / 'include' / 'lv_conf.h'
MIN_FREE_GATE = 30 * 1024
MIN_POOL = 80 * 1024
GROWTH_TOLERANCE = 1024


def firmware_conf():
    text = LV_CONF.read_text(encoding='utf-8')
    code = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    size = re.search(r'^\s*#define\s+LV_MEM_SIZE\s+\((\d+)\s*\*\s*1024U?\)', code, re.M)
    handler = re.search(r'^\s*#define\s+LV_ASSERT_HANDLER\s+(.+?)\s*$', code, re.M)
    include = re.search(r'^\s*#define\s+LV_ASSERT_HANDLER_INCLUDE\s+(\S+)', code, re.M)
    return (int(size.group(1)) * 1024 if size else None, handler.group(1) if handler else None,
            include.group(1) if include else None)


def check(out):
    failures = []
    pool, handler, include = firmware_conf()
    if pool is None or pool < MIN_POOL:
        failures.append(f'lv_conf.h LV_MEM_SIZE {pool} < {MIN_POOL}')
    if handler != 'abort();':
        failures.append(f'lv_conf.h LV_ASSERT_HANDLER is {handler!r}, want abort();')
    if include != '<stdlib.h>':
        failures.append(f'lv_conf.h LV_ASSERT_HANDLER_INCLUDE is {include!r}, want <stdlib.h> (abort())')

    index = json.loads((out / 'render-index.json').read_text(encoding='utf-8'))
    soak = index.get('soak')
    if not soak:
        failures.append(f'{out / "render-index.json"}: no "soak" (main.cpp predates FW-RES-001?)')
        return failures
    rounds = soak['used_after_round']
    if len(rounds) < 3 or soak['timelines'] < 10 or soak['cases'] < 100:
        failures.append(f'soak too small: {len(rounds)} rounds, {soak["timelines"]} timelines, {soak["cases"]} cases')
    if any(abs(r - rounds[0]) > GROWTH_TOLERANCE for r in rounds):
        failures.append(f'LVGL used bytes drift across soak rounds: {rounds}')
    if len(rounds) >= 3 and all(b > a for a, b in zip(rounds, rounds[1:])):
        failures.append(f'LVGL used bytes grow every soak round: {rounds}')

    heap = index['heap']
    overhead = heap['lv_mem_size'] - heap['total_size']            # TLSF control structure, as measured
    peak = max(heap['peak_used_sampled'], heap['max_used'], max(rounds))
    projected = (pool or 0) - overhead - peak
    if projected < MIN_FREE_GATE:
        failures.append(f'projected low-water {projected} B on a {pool} B pool (x64 peak {peak} B, overhead '
                        f'{overhead} B) < {MIN_FREE_GATE} B')
    print(f'soak: {len(rounds)} rounds x ({soak["timelines"]} timelines + {soak["cases"]} cases), used after each '
          f'{rounds}; cc_display_create {soak["used_after_create"] - soak["used_before_create"]} B (x64); '
          f'pool {pool} B, projected low-water {projected} B (gate {MIN_FREE_GATE})')
    return failures


def main(argv):
    out = Path(argv[1]) if len(argv) > 1 else ROOT / 'rendered'
    failures = check(out)
    for failure in failures:
        print('FAIL', failure)
    print('display_soak_tests:', 'FAIL' if failures else 'PASS')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
