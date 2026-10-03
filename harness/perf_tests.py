"""perf.py / lcd-perf checks (host only, no device). Builds lcd-perf through perf.py's own build() and checks:

1. period (HN-PERF-003): lcd-perf records period_ms, defaults to binary F's 12 ms (perf.py and perf.cpp agree),
   and a 12 ms profile samples M1 more often than the 16 ms one (more refreshes per push cycle).
2. optimisation (HN-PERF-001): build/ and build-perf-conf/ (here with an unchanged copy of lv_conf.h) both build
   every profiled target at /O2 and record it with the lv_conf.h hash; their scenario medians (the median of seven
   interleaved full-length runs: a run's median now and then drops ~30 % on this PC, so the best run is not stable) agree within 15 %; --compare refuses files with different or unrecorded flags.
3. repeats (HN-PERF-002): perf.py --repeat 9 --out DIR writes DIR/<label>.json (nothing under perf/), interleaves the
   rows variants, and records per scenario every run's median with their min and median; two invocations agree on
   the median of run medians within 20 %, a bound for a shared, busy PC (quiet, they agree within ~5 %). Min-of-medians
   is recorded but not held to a bound: a run now and then drops ~30 % (more so while other builds run), so the best
   of five moves more than the median of five. That 20 % bound is a sanity check only; the ranking is what the finding
   is about: per scenario the paired ratio rows48/rows24 (median over rounds of each round's ratio) and the ratio of
   the medians must fall on the same side of 1 in both invocations, each at least 0.05 from 1, and the two paired
   ratios must agree within 0.08 (under the 11-19 % effect being ranked).

Exit status is non-zero on any failure. Run under the harness lock (with_lock.py harness -- ...).
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import statistics
import sys
import tempfile

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
import perf  # noqa: E402

CYCLES = 6
REPEAT = 9   # rounds per invocation in repeat_checks: 5 (the default) let a busy PC move the paired ratio ~0.07
RANK_MARGIN = 0.05   # every rows48/rows24 ratio must sit at least this far from 1 (a decisive ranking)
RATIO_AGREE = 0.08   # paired ratios of two invocations agree within this. 0.05 held on the art scenarios but not
                     # on m1_bench_noart at ~88 % CPU from parallel builds (single rounds 0.65-0.98; paired 0.83 vs 0.88)
failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(('ok   ' if ok else 'FAIL ') + what)
    if not ok:
        failures.append(what)


def period_checks(exe: Path) -> None:
    src = (root / 'perf.cpp').read_text(encoding='utf-8')
    m = re.search(r'uint32_t periodMs = (\d+);', src)
    check(m is not None and int(m.group(1)) == perf.DEFAULT_PERIOD_MS == 12,
          'perf.cpp and perf.py default the period to 12 ms (binary F)')
    default = perf.subprocess.run([str(exe), '--rows', '24', '--cycles', str(CYCLES)], capture_output=True, text=True,
                                  check=True, timeout=600)
    check(perf.json.loads(default.stdout)['period_ms'] == 12, 'lcd-perf without --period records period_ms 12')
    p12 = perf.run(exe, 24, CYCLES, 12)
    p16 = perf.run(exe, 24, CYCLES, 16)
    check(p12['period_ms'] == 12 and p16['period_ms'] == 16, 'lcd-perf --period N records period_ms N')
    r12 = p12['scenarios']['m1_bench_noart']['refreshes'] / CYCLES
    r16 = p16['scenarios']['m1_bench_noart']['refreshes'] / CYCLES
    check(r12 > r16, f'M1 refreshes per cycle rise at 12 ms ({r12:.1f}) over 16 ms ({r16:.1f})')


def flag_checks(exe: Path) -> None:
    same = root / 'build-perf-conf' / 'conf-unchanged'
    same.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / 'lv_conf.h', same / 'lv_conf.h')
    exe_conf = perf.build(same)
    plain, conf = perf.build_info(), perf.build_info(same)
    for info in (plain, conf):
        check(all('/O2' in f.split() for f in info['release_flags'].values()) and set(info['release_flags']) == set(perf.PROFILED),
              f"{info['build_dir']} records release_flags with /O2 on every profiled target: {info['release_flags']}")
    check(plain['lv_conf_sha256'] == conf['lv_conf_sha256'], 'an unchanged lv_conf.h copy records the same hash')
    check(plain['release_flags'] == conf['release_flags'], 'build/ and build-perf-conf/ build at the same level')
    a, b = [], []
    for _ in range(7):   # interleaved, so a slow spell on the PC hits both
        a.append(perf.run(exe, 24, 24, 12))
        b.append(perf.run(exe_conf, 24, 24, 12))
    for name in a[0]['scenarios']:
        ma = statistics.median(x['scenarios'][name]['us_median'] for x in a)
        mb = statistics.median(x['scenarios'][name]['us_median'] for x in b)
        check(abs(mb - ma) <= 0.15 * max(ma, mb), f'{name}: build/ {ma:.0f} us vs build-perf-conf/ {mb:.0f} us within 15 %')
    with tempfile.TemporaryDirectory() as tmp:
        base = {'rows24': {**a[0], **plain}}
        files = {}
        for tag, edit in (('ok', {}), ('od', {'release_flags': {t: '/Od' for t in perf.PROFILED}}), ('old', None)):
            d = {'rows24': dict(base['rows24'])}
            if edit is None:
                d['rows24'].pop('release_flags')
            else:
                d['rows24'].update(edit)
            files[tag] = Path(tmp) / f'{tag}.json'
            files[tag].write_text(perf.json.dumps(d), encoding='utf-8')
        check(perf.compare(files['ok'], files['ok']) == 0, '--compare accepts two /O2 files')
        for tag in ('od', 'old'):
            try:
                perf.compare(files['ok'], files[tag])
                refused = False
            except SystemExit:
                refused = True
            check(refused, f'--compare refuses a file with {"/Od" if tag == "od" else "no recorded"} release_flags')


def repeat_checks() -> None:
    tracked = sorted(p.name for p in (root / 'perf').iterdir())
    with tempfile.TemporaryDirectory() as tmp:
        docs = []
        for k in range(2):
            perf.main([f'repeat{k}', '--rows', '24,48', '--repeat', str(REPEAT), '--out', tmp])
            docs.append(perf.json.loads((Path(tmp) / f'repeat{k}.json').read_text(encoding='utf-8')))
    check(sorted(p.name for p in (root / 'perf').iterdir()) == tracked, '--out leaves the tracked perf/ untouched')
    for key in ('rows24', 'rows48'):
        res = docs[0][key]
        ok = res.get('repeat') == REPEAT and all(
            len(sc['us_medians']) == REPEAT and sc['us_median_min'] == min(sc['us_medians'])
            and sc['us_median_of_runs'] == statistics.median(sc['us_medians']) for sc in res['scenarios'].values())
        check(ok, f'{key}: every scenario records {REPEAT} run medians with their min and median')
        for name in res['scenarios']:
            m0, m1 = (d[key]['scenarios'][name]['us_median_of_runs'] for d in docs)
            lo0, lo1 = (d[key]['scenarios'][name]['us_median_min'] for d in docs)
            # Sanity bound only: absolute timings drift with machine load.
            check(abs(m1 - m0) < 0.20 * max(m0, m1), f'{key} {name}: median of run medians {m0:.0f} vs {m1:.0f} us '
                  f'within 20 % (sanity; min {lo0:.0f} vs {lo1:.0f})')
    # Ranking: the finding is about ordering rows48 against rows24 (an 11-19 % effect). Round k runs
    # both variants back to back, so the per-round ratio cancels a slow spell on the PC; its median
    # over the rounds is the paired ratio. Checks per scenario:
    #  - ranking: in both invocations the paired ratio AND the ratio of the recorded medians fall on
    #    the same side of 1, each at least RANK_MARGIN away from it (a decisive ranking, not a tie);
    #  - stability: the two paired ratios agree within RATIO_AGREE, well under the effect, so the
    #    measured size of the win holds too.
    # (The ratio of medians alone moved 0.83 -> 0.94 under load where the paired one held 0.81-0.83.)
    for name in docs[0]['rows24']['scenarios']:
        rm, rp = [], []
        for d in docs:
            a, b = (d[key]['scenarios'][name] for key in ('rows24', 'rows48'))
            rm.append(b['us_median_of_runs'] / a['us_median_of_runs'])
            rp.append(statistics.median(y / x for x, y in zip(a['us_medians'], b['us_medians'])))
        sides = {r < 1 for r in rm + rp}
        decisive = all(abs(r - 1) >= RANK_MARGIN for r in rm + rp)
        check(len(sides) == 1 and decisive,
              f'{name}: both invocations rank {"rows48" if rp[0] < 1 else "rows24"} faster, decisively (paired ratio '
              f'{rp[0]:.3f} vs {rp[1]:.3f}, ratio of medians {rm[0]:.3f} vs {rm[1]:.3f}, each >= {RANK_MARGIN} from 1)')
        check(abs(rp[0] - rp[1]) < RATIO_AGREE,
              f'{name}: rows48/rows24 paired ratio {rp[0]:.3f} vs {rp[1]:.3f} agrees within {RATIO_AGREE}')


def main() -> int:
    exe = perf.build()
    period_checks(exe)
    flag_checks(exe)
    repeat_checks()
    print(f'perf_tests: {len(failures)} failure(s)')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
