"""lv_conf.h sync gate (FW-RES-001 / review of HN-DES-002).

build.py step 2 regenerates harness/lv_conf.h from the firmware's
include/lv_conf.h and refuses to run when a pinned firmware value is missing.
This test runs that exact step (extracted from build.py, nothing compiled) and
checks that:
  1. it does not exit, i.e. build.py's pinned values (LV_MEM_SIZE, colour
     depth) match the firmware file as it is now;
  2. the tracked lcd-preview/lv_conf.h is byte-identical to what build.py
     would write, so an unmodified build.py run leaves the tree clean;
  3. LV_MEM_SIZE is a >= 80 KB floor: 64/79 KB are rejected, 80/96/128 KB accepted.

Run: python work/audit/tools/with_lock.py harness -- python harness/lvconf_sync_tests.py
"""
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parent
firmware = root.parent / 'firmware'
failures = []


def check(ok, message):
    print(('PASS ' if ok else 'FAIL ') + message)
    if not ok:
        failures.append(message)


build_src = (root / 'build.py').read_text(encoding='utf-8')
start = build_src.index('HOST_OVERRIDES = [')
end = build_src.index('# 1. C++11 gate')
step_start = build_src.index('# 2. Firmware lv_conf.h')
step_end = build_src.index("config_path = root / 'lv_conf.h'")
scope = {'root': root, 'firmware': firmware, 're': re}
exec(build_src[start:end], scope)
try:
    exec(build_src[step_start:step_end], scope)
    check(True, 'build.py step 2 accepts the firmware lv_conf.h')
except SystemExit as exc:
    check(False, f'build.py step 2 exits: {exc}')
    scope['config'] = None

fw_conf = (firmware / 'include' / 'lv_conf.h').read_bytes()
fw_mem = re.search(rb'^[ \t]*#define[ \t]+LV_MEM_SIZE[ \t]+(\([^)]*\))', fw_conf, re.M)
check(fw_mem is not None, f'firmware lv_conf.h defines LV_MEM_SIZE ({fw_mem.group(1).decode() if fw_mem else None})')

# 3. build.py checks LV_MEM_SIZE as a >= 80 KB floor (FW-RES-001 cross-lane follow-up), not a pinned
#    literal: run step 2 against copies of the firmware file with the pool rewritten.
check("rb'#define LV_MEM_SIZE (" not in build_src, 'build.py no longer pins an LV_MEM_SIZE literal')


def step2_accepts(pool_kb):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        fake = Path(tmp)
        (fake / 'include').mkdir()
        conf = re.sub(rb'(#define[ \t]+LV_MEM_SIZE[ \t]+)\([^)]*\)',
                      lambda m: m.group(1) + b'(%d * 1024U)' % pool_kb, fw_conf, count=1)
        (fake / 'include' / 'lv_conf.h').write_bytes(conf)
        trial = {'root': root, 'firmware': fake, 're': re}
        exec(build_src[start:end], trial)
        try:
            exec(build_src[step_start:step_end], trial)
            return True
        except SystemExit:
            return False


for pool_kb, ok in ((64, False), (79, False), (80, True), (96, True), (128, True)):
    check(step2_accepts(pool_kb) == ok, f'build.py step 2 {"accepts" if ok else "rejects"} LV_MEM_SIZE ({pool_kb} * 1024U)')

tracked = (root / 'lv_conf.h').read_bytes()
check(scope['config'] is not None and tracked == scope['config'],
      'tracked lcd-preview/lv_conf.h equals build.py output (run build.py and commit lv_conf.h if not)')

# 4. The prose that describes the harness config matches the firmware file:
#    pool size (KB) and assert handler (FW-RES-001 moved 64 KB/while(1) to 80 KB/abort()).
kb = re.search(rb'\((\d+)\s*\*\s*1024U?\)', fw_mem.group(1)) if fw_mem else None
handler = re.search(rb'^[ \t]*#define[ \t]+LV_ASSERT_HANDLER[ \t]+(\S+?);?[ \t]*$', fw_conf, re.M)
docs = {name: (root / name).read_text(encoding='utf-8') for name in ('README.md', 'main.cpp', 'build.py', 'cc5_report.py')}
if kb:
    size = kb.group(1).decode()
    check(f'`LV_MEM_SIZE` {size} KB' in docs['README.md'], f'README states LV_MEM_SIZE {size} KB')
    check(f'{size} KB heap' in docs['main.cpp'], f'main.cpp header states {size} KB heap')
    for name, text in docs.items():
        stale = sorted(set(re.findall(r'\b(\d+) KB heap|LV_MEM_SIZE`? (\d+) KB|of (\d+) KB', text)))
        stale = [v for group in stale for v in group if v and v != size]
        check(not stale, f'{name} names no other LVGL pool size (found {stale})')
check(handler is not None and handler.group(1) == b'abort()', 'firmware assert handler is abort()')
for name, text in docs.items():
    check('while(1)' not in text, f'{name} does not describe the assert handler as while(1)')

print(f"lvconf_sync_tests: {'PASS' if not failures else f'FAIL ({len(failures)})'}")
sys.exit(1 if failures else 0)
