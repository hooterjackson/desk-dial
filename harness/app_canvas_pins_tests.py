"""App canvas pins (lane F7: src/cc_app_*). Python stdlib only.

Pins comments and wiring the host app canvas test cannot see. Each check names the finding it pins.
Exit status is non-zero on any failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
src = root.parent / 'firmware' / 'src'


def read(name: str) -> str:
    return (src / name).read_text(encoding='utf-8')


def fw_bug_045() -> list:
    """FW-BUG-045: the kCCAppJump guard covers a new control only; the wake turn is removed upstream."""
    fails = []
    canvas = read('cc_app_canvas.cpp')
    body = canvas[canvas.index('void CCAppCanvas::track_angle('):]
    guard = body.index('kCCAppJump')
    head = body[:guard]
    if re.search(r'new control,\s*wake', head) or 'wake): not a turn' in head:
        fails.append('track_angle comment still says the jump guard covers the wake turn')
    if 'CCAppAngleHold' not in head:
        fails.append('track_angle comment does not point at CCAppAngleHold')
    if 'class CCAppAngleHold' not in read('cc_lcd_logic.h'):
        fails.append('cc_lcd_logic.h has no CCAppAngleHold')
    lcd = read('lcd_thread.cpp')
    if not re.search(r'^\s*CCAppAngleHold\s+\w+\s*;', lcd, flags=re.M):
        fails.append('lcd_thread.cpp does not hold the app angle through CCAppAngleHold')
    return fails


def app_profiles_store() -> list:
    """App profiles (plan section 1e, S1 FW-B): the LCD thread enters the canvas on a present app object (the id is
    text: `app.id != 0` would always be true), and the canvas holds no profile pointer between passes (it acquires
    the frame's profile from the store per pass and releases it)."""
    fails = []
    lcd = read('lcd_thread.cpp')
    if re.search(r'app\.id\s*!=\s*0', lcd):
        fails.append('lcd_thread.cpp still tests app.id != 0')
    if 'cc_app_state_present(frame.app)' not in lcd:
        fails.append('lcd_thread.cpp does not gate the app canvas on cc_app_state_present(frame.app)')
    header = read('cc_app_canvas.h')
    members = header[header.index('class CCAppCanvas'):]
    if re.search(r'const\s+(cc_app_profile_t|app_scene_t|app_cmd_t|app_ring_t|app_param_t)\s*\*\s*\w+_\s*[;=]', members):
        fails.append('CCAppCanvas keeps a pointer into a profile across passes')
    canvas = read('cc_app_canvas.cpp')
    if 'cc_app_store_acquire' not in canvas or 'cc_app_store_release' not in canvas:
        fails.append('cc_app_canvas.cpp does not acquire / release through the store')
    if re.search(r'cc_app_profile\s*\(', canvas):
        fails.append('cc_app_canvas.cpp still looks profiles up by the cc5.6 index')
    return fails


def app_id_is_text() -> list:
    """App profiles (plan section 1f, S3 integration): CCAppState::id is a char[12] profile id, so `app.id == 0` /
    `app.id != 0` compiles without a warning and compares the array's address (always false / true). Every test for
    an app frame goes through cc_app_present(); a merged guard written the old way broke DD-BUG-053's landing."""
    fails = []
    files = sorted(src.glob('*.c*')) + sorted(src.glob('*.h'))
    files += [f for f in sorted(root.glob('*.c*')) + sorted(root.glob('*.h')) if f.suffix in ('.c', '.cpp', '.h')]
    for path in files:
        text = path.read_text(encoding='utf-8', errors='replace')
        for n, line in enumerate(text.splitlines(), 1):
            code = line.split('//', 1)[0]
            if re.search(r'\bapp\.id\s*[!=]=\s*0\b|\b0\s*[!=]=\s*[\w>.-]*app\.id\b|!\s*[\w>.-]*app\.id\b', code):
                fails.append(f'{path.name}:{n}: tests app.id against 0; use cc_app_present()')
    return fails


def main() -> int:
    ok = True
    for name, check in (('FW-BUG-045 jump guard comment / wake hold', fw_bug_045),
                        ('app profiles: canvas gate and per-pass store leases', app_profiles_store),
                        ('app profiles: app frames tested with cc_app_present, never app.id vs 0', app_id_is_text)):
        fails = check()
        print(f'{"PASS" if not fails else "FAIL"} {name}')
        for f in fails:
            print(f'  - {f}')
        ok = ok and not fails
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
