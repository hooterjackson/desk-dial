"""r4 render-speed profile (perf.cpp): builds the lcd-perf target (MSVC, the same firmware units and lv_conf.h as
build.py) and runs it --repeat times per draw-buffer height, writing <out>/<label>.json.

Usage: perf.py <label> [--rows 24,48] [--cycles 24] [--period 12] [--repeat 5] [--out DIR] [--conf DIR]
       perf.py --compare A.json B.json
--period N: the LVGL refresh / animation period in ms (default 12, binary F's CC_LCD_PERIOD_MS; 16 reproduces
binary D and the older perf/*.json). Recorded as period_ms in every run.
--repeat N: N rounds (default 5), the rows variants interleaved within each round so a slow spell on the PC hits
every variant; one run's median moves 15-40 % on this PC, more than the effects being ranked. Each scenario records
us_medians (every run's), us_median_min and us_median_of_runs; rank variants by those, not by one run.
--out DIR: where <label>.json goes (default perf/, which is tracked: audits write outside the tree).
--conf DIR: compile LVGL with DIR/lv_conf.h instead (a candidate firmware lv_conf.h change), in its own build
directory (build-perf-conf), so the evidence build is never touched.
Every run records release_flags (the MSVC optimisation each profiled target was built with, read from its
.vcxproj) and lv_conf_sha256 (the lv_conf.h compiled); perf.py refuses a build without /O2 (CMakeLists.txt pins
it), and --compare refuses two files whose release_flags differ or are missing (re-take such a file).
Absolute microseconds are the PC's; compare scenarios and variants with each other (see perf.cpp).
Run build.py first once (it generates lv_conf.h from the firmware's include/lv_conf.h).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys

root = Path(__file__).resolve().parent
firmware = root.parent / 'firmware'
cmake = Path('C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe')
DEFAULT_PERIOD_MS = 12   # binary F (lcd_thread.cpp CC_LCD_PERIOD_MS)
PROFILED = ('lvgl', 'firmware_shared', 'lcd-perf')   # the targets lcd-perf's time is spent in


def tool_env() -> dict:
    return {key.upper(): value for key, value in os.environ.items()}


def release_flags(build_dir: Path) -> dict:
    """The Release|x64 optimisation flags of each profiled target, from the generated .vcxproj."""
    level = {'Disabled': '/Od', 'MinSpace': '/O1', 'MaxSpeed': '/O2', 'Full': '/Ox'}
    inline = {'Disabled': '/Ob0', 'OnlyExplicitInline': '/Ob1', 'AnySuitable': '/Ob2'}
    flags = {}
    for target in PROFILED:
        text = (build_dir / f'{target}.vcxproj').read_text(encoding='utf-8', errors='replace')
        m = re.search(r"<ItemDefinitionGroup Condition=\"'\$\(Configuration\)\|\$\(Platform\)'=='Release\|x64'\">"
                      r'.*?<ClCompile>(.*?)</ClCompile>', text, re.S)
        cl = m.group(1) if m else ''

        def tag(name):
            t = re.search(rf'<{name}>(.*?)</{name}>', cl, re.S)
            return t.group(1).strip() if t else ''
        parts = [level.get(tag('Optimization'), '/Od')]   # no <Optimization>: MSVC's default, /Od
        if tag('InlineFunctionExpansion') in inline:
            parts.append(inline[tag('InlineFunctionExpansion')])
        if re.search(r'(^|;)NDEBUG(;|$)', tag('PreprocessorDefinitions')):
            parts.append('/DNDEBUG')
        if target == 'lcd-perf':   # the link: incremental linking routes calls through jump thunks
            inc = re.search(r"<LinkIncremental Condition=\"'\$\(Configuration\)\|\$\(Platform\)'=='Release\|x64'\">(\w+)<", text)
            link = re.search(r"<ItemDefinitionGroup Condition=\"'\$\(Configuration\)\|\$\(Platform\)'=='Release\|x64'\">"
                             r'.*?<Link>(.*?)</Link>', text, re.S)
            no_inc = '/INCREMENTAL:NO' in (link.group(1) if link else '') or (inc and inc.group(1) == 'false')
            parts.append('/INCREMENTAL:NO' if no_inc else '/INCREMENTAL')
        flags[target] = ' '.join(parts)
    return flags


def lv_conf_sha256(conf: Path | None) -> str:
    return hashlib.sha256(((conf or root) / 'lv_conf.h').read_bytes()).hexdigest()


def build_info(conf: Path | None = None) -> dict:
    """What a perf JSON records about the build (and what --compare checks)."""
    build_dir = root / ('build-perf-conf' if conf else 'build')
    return {'build_dir': build_dir.name, 'release_flags': release_flags(build_dir), 'lv_conf_sha256': lv_conf_sha256(conf)}


def build(conf: Path | None = None) -> Path:
    """Configure and build lcd-perf; returns the executable. Refuses a build whose profiled targets lack /O2."""
    env = tool_env()
    pins = [f'-DNANOD_FIRMWARE_SRC={(firmware / "src").as_posix()}', f'-DNANOD_TJPGD_SHIM={(root / "tjpgd_shim").as_posix()}']
    build_dir = root / 'build'
    if conf:
        build_dir = root / 'build-perf-conf'
        pins.append(f'-DNANOD_LV_CONF_DIR={conf.as_posix()}')
    subprocess.run([str(cmake), '-S', str(root), '-B', str(build_dir), '-G', 'Visual Studio 17 2022', '-A', 'x64'] + pins,
                   env=env, check=True, stdout=subprocess.DEVNULL)
    subprocess.run([str(cmake), '--build', str(build_dir), '--config', 'Release', '--parallel', '6', '--target', 'lcd-perf'],
                   env=env, check=True, stdout=subprocess.DEVNULL)
    unoptimised = {t: f for t, f in release_flags(build_dir).items() if '/O2' not in f.split()}
    if unoptimised:
        raise SystemExit(f'perf.py: {build_dir.name} builds {unoptimised} without /O2 (CMakeLists.txt pins it; '
                         f'reconfigure with a clean {build_dir.name}/)')
    return build_dir / 'Release' / 'lcd-perf.exe'


def run(exe: Path, rows: int, cycles: int, period: int) -> dict:
    """One lcd-perf run (JSON from stdout)."""
    out = subprocess.run([str(exe), '--rows', str(rows), '--cycles', str(cycles), '--period', str(period)],
                         env=tool_env(), check=True, capture_output=True, text=True, timeout=600)
    return json.loads(out.stdout)


def compare(a: Path, b: Path) -> int:
    """Per-scenario median ratio B/A; refuses files built at different (or unrecorded) optimisation levels."""
    da, db = (json.loads(Path(x).read_text(encoding='utf-8')) for x in (a, b))
    for key in sorted(set(da) & set(db)):
        fa, fb = da[key].get('release_flags'), db[key].get('release_flags')
        if not fa or not fb:
            raise SystemExit(f'perf.py --compare: {a if not fa else b} {key} has no release_flags (an unpinned '
                             f'build, possibly /Od): re-take it')
        if fa != fb:
            raise SystemExit(f'perf.py --compare: {key} built differently ({fa} vs {fb}); not comparable')
        if da[key].get('period_ms') != db[key].get('period_ms'):
            raise SystemExit(f'perf.py --compare: {key} period {da[key].get("period_ms")} vs {db[key].get("period_ms")} ms')
        def med(d, name):   # the median over repeats when recorded (perf.py --repeat), else the one run's
            sc = d[key]['scenarios'].get(name)
            return sc.get('us_median_of_runs', sc['us_median']) if sc else None
        for name in da[key]['scenarios']:
            ma, mb = med(da, name), med(db, name)
            if mb is not None and ma:
                print(f'{key} {name}: {ma:.0f} -> {mb:.0f} us ({mb / ma:.2f}x)')
    return 0


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    if argv[0] == '--compare':
        return compare(Path(argv[1]), Path(argv[2]))
    label = argv[0]
    rows = [24]
    cycles = 24
    period = DEFAULT_PERIOD_MS
    repeat = 5
    out = root / 'perf'
    rest = argv[1:]
    conf = None
    for i, a in enumerate(rest):
        if a == '--conf':
            conf = Path(rest[i + 1]).resolve()
        if a == '--rows':
            rows = [int(x) for x in rest[i + 1].split(',')]
        elif a == '--cycles':
            cycles = int(rest[i + 1])
        elif a == '--period':
            period = int(rest[i + 1])
        elif a == '--repeat':
            repeat = int(rest[i + 1])
        elif a == '--out':
            out = Path(rest[i + 1]).resolve()
    if repeat < 1:
        raise SystemExit('perf.py: --repeat must be >= 1')
    exe = build(conf)
    info = build_info(conf)
    runs = {r: [] for r in rows}
    for _ in range(repeat):   # interleaved: round k runs every variant once
        for r in rows:
            runs[r].append(run(exe, r, cycles, period))
    results = {}
    for r in rows:
        # The last run's full record (breakdown, tasks, heap), with every run's scenario medians summarised.
        res = {**runs[r][-1], **info, 'repeat': repeat}
        for name, sc in res['scenarios'].items():
            medians = [x['scenarios'][name]['us_median'] for x in runs[r]]
            sc['us_medians'] = medians
            sc['us_median_min'] = min(medians)
            sc['us_median_of_runs'] = statistics.median(medians)
        results[f'rows{r}'] = res
    out.mkdir(parents=True, exist_ok=True)
    (out / f'{label}.json').write_text(json.dumps(results, indent=1), encoding='utf-8')
    for key, res in results.items():
        print(f"{label} {key} period {res['period_ms']} ms, {res['build_dir']} {res['release_flags']}, "
              f"lv_conf.h {res['lv_conf_sha256'][:12]}")
        for name, s in res['scenarios'].items():
            print(f"{label} {key} {name}: {s['refreshes']} refreshes, median over {res['repeat']} runs "
                  f"{s['us_median_of_runs']:.0f} us (min {s['us_median_min']:.0f}), last run mean {s['us_mean']:.0f} us, "
                  f"px {s['px_mean']:.0f}, chunks {s['chunks_mean']:.1f}, A8 draws {s['a8_draws_per_refresh']:.1f} "
                  f"({s.get('a8_copied_per_refresh', s['a8_draws_per_refresh']):.1f} copied, {s['a8_copy_bytes_per_refresh']:.0f} B), layered {s['layered_objects_max']}, "
                  f"objects {s['drawn_objects_max']}")
        print(f"{label} {key} content redraw breakdown (us): {res.get('content_redraw_breakdown_us')}")
        print(f"{label} {key} content redraw tasks: {json.dumps(res.get('content_redraw_tasks'))}")
        print(f"{label} {key} heap max used {res['lvgl_heap_max_used']} of {res['lvgl_heap_total']}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
