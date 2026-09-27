"""cc5 LED renderer parity (Stage 5). Python stdlib + MSVC only; no device, no USB.

1. Runs cpp11_gate.py: every shared unit (cc_lights.cpp included) must compile
   in the device's gnu++11 (MSVC below cannot go under C++14).
2. Regenerates light_pixels.json from the companion's reference model
   (tests/tools/make_light_sequences.py): each sequence is replayed through ONE
   control_center.preview_lights.PreviewLights, recording the logical ring,
   buttons, cursor, flash, lastSeq, onset times, the pure target and the
   stateless button pixels at every step.
3. Compiles light_tests.cpp with the unchanged firmware units cc_lights.cpp and
   cc_frame_parse.cpp (MSVC /W4 /WX). The C++ runner parses every frame with
   cc_parse_frame(), replays each sequence through one CCLightRenderer and
   compares every recorded value bit-exactly (plus the physical ring in the four
   mounting orientations), then runs its direct assertions.
4. Cross-checks the runner's own output (build/light-tests/light_actual.jsonl)
   against the fixture: logical ring and buttons, and the physical ring against
   this script's independent wiring model (native top pin per orientation,
   walking the wired addresses downward to move clockwise).

Writes light_pixels.json and build/light-tests/*. Exit status is non-zero on any
mismatch.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parent
firmware = root.parent / 'firmware'
companion = root.parent / 'app'
arduinojson = firmware / '.pio' / 'libdeps' / 'nanofoc_d' / 'ArduinoJson' / 'src'
out_dir = root / 'build' / 'light-tests'
fixture_path = root / 'light_pixels.json'
TOP_PIN = (0, 45, 30, 15)

sys.path.insert(0, str(companion / 'tests' / 'tools'))
sys.path.insert(0, str(companion))
import make_light_sequences  # noqa: E402  (companion reference model; read-only)


def physical_model(logical, orientation):
    """Independent wiring model: top pin per mounting, clockwise = next lower wired address."""
    physical = [0] * 60
    pin = TOP_PIN[orientation]
    for color in logical:
        physical[pin] = color
        pin = 59 if pin == 0 else pin - 1
    return physical


def msvc_env():
    msvc = Path('C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Tools/MSVC/14.44.35207')
    sdk = Path('C:/Program Files (x86)/Windows Kits/10')
    sdk_include = sorted((sdk / 'Include').iterdir(), key=lambda p: p.name)[-1]
    sdk_lib = sdk / 'Lib' / sdk_include.name
    env = {key.upper(): value for key, value in os.environ.items()}
    env['INCLUDE'] = ';'.join(str(path) for path in (
        msvc / 'include', sdk_include / 'ucrt', sdk_include / 'shared', sdk_include / 'um'))
    env['LIB'] = ';'.join(str(path) for path in (
        msvc / 'lib/x64', sdk_lib / 'ucrt/x64', sdk_lib / 'um/x64'))
    return msvc / 'bin/Hostx64/x64/cl.exe', env


def compile_runner() -> Path:
    cl, env = msvc_env()
    exe = out_dir / 'light_tests.exe'
    subprocess.run([
        str(cl), '/nologo', '/EHsc', '/std:c++14', '/W4', '/WX', '/O2', '/D_CRT_SECURE_NO_WARNINGS',
        f'/I{firmware / "src"}',
        # ArduinoJson is third-party: its own warnings are not ours (the gnu++11 gate parses it too).
        f'/external:I{arduinojson}', '/external:W0',
        str(root / 'light_tests.cpp'), str(firmware / 'src' / 'cc_lights.cpp'),
        str(firmware / 'src' / 'cc_frame_parse.cpp'),
        f'/Fo{out_dir}\\', f'/Fe{exe}',
    ], cwd=out_dir, env=env, check=True)
    return exe


def cross_check(data, actual_path: Path) -> int:
    """Compare the C++ output file with the fixture; returns the number of values compared."""
    expected = [(name, i, step) for name, case in data['cases'].items() for i, step in enumerate(case['steps'])]
    lines = actual_path.read_text(encoding='utf-8').splitlines()
    if len(lines) != len(expected):
        raise SystemExit(f'FAIL: C++ reported {len(lines)} step(s), fixture has {len(expected)}')
    compared = 0
    for line, (name, index, step) in zip(lines, expected):
        got = json.loads(line)
        where = f'{name} step {index}'
        if (got['case'], got['step']) != (name, index):
            raise SystemExit(f'FAIL: {where}: C++ output is out of order ({got["case"]} {got["step"]})')
        if got['ring'] != step['ring']:
            raise SystemExit(f'FAIL: {where}: C++ logical ring differs from PreviewLights')
        if got['buttons'] != step['buttons']:
            raise SystemExit(f'FAIL: {where}: C++ buttons differ from PreviewLights')
        for orientation in range(4):
            if got['physical'][orientation] != physical_model(step['ring'], orientation):
                raise SystemExit(f'FAIL: {where}: C++ physical ring (orientation {orientation}) '
                                 'differs from the wiring model')
        compared += 60 + 4 + 4 * 60
    return compared


def main() -> int:
    started = time.time()
    # 1. Fail fast if a shared unit is not valid gnu++11.
    subprocess.run([sys.executable, str(root / 'cpp11_gate.py')], check=True)
    # 2. Reference sequences from the Python model.
    data = make_light_sequences.build()
    text = make_light_sequences.dumps(data)
    previous = fixture_path.read_text(encoding='utf-8') if fixture_path.is_file() else ''
    fixture_path.write_text(text, encoding='utf-8', newline='\n')
    steps = sum(len(case['steps']) for case in data['cases'].values())
    print(f"light_tests: fixture {'unchanged' if previous == text else 'regenerated'}: "
          f"{make_light_sequences.summary(data)} ({len(text.encode('utf-8'))} bytes)", flush=True)
    # 3. C++ runner: parity + direct assertions.
    out_dir.mkdir(parents=True, exist_ok=True)
    exe = compile_runner()
    actual = out_dir / 'light_actual.jsonl'
    subprocess.run([str(exe), str(fixture_path), str(actual)], check=True)
    # 4. Independent cross-check of the C++ output.
    compared = cross_check(data, actual)
    print(f'PASS: C++ CCLightRenderer == PreviewLights over {len(data["cases"])} sequence(s), {steps} step(s); '
          f'cross-check {compared} value(s) incl. physical rings (4 orientations) '
          f'[{time.time() - started:.1f} s]')
    return 0


if __name__ == '__main__':
    sys.exit(main())
