"""COM protocol pins (lane F2: com_thread.cpp, cc_serial_out.*, control_center.cpp). Python stdlib + MSVC.

1. Source rules over the firmware units the host cannot compile (com_thread.cpp pulls in the
   FreeRTOS tasks, SPIFFS and the profile manager). Comments are stripped first. Each rule names
   the finding it pins.
2. protocol_tests.cpp linked with src/cc_serial_out.cpp unchanged against a fake TinyUSB CDC and a
   simulated clock (STUBS below), MSVC /W4 /WX, and run. It also compiles the body of
   com_thread.cpp's {"profiles":"#all"} branch, cut verbatim from the source (SNIPPETS below),
   against a fake profile manager with blank slots, and the {"profiles":[...]} delete branch
   (re-dispatch when the current profile is removed).
3. --firmware-syntax: also syntax-checks com_thread.cpp and cc_serial_out.cpp with their exact
   PlatformIO command lines (media_tests.firmware_syntax: xtensa g++ -fsyntax-only, no build).
   While src/lcd_thread.h still lacks CC_LCD_COMMAND_BY_VALUE (lane F3 applies
   work/audit/patches/FW-BUG-006.patch), com_thread.cpp is checked a second time against that
   patch's lcd_thread.h (an overlay copy of both), so its by-value path compiles too.

Diagnostics that other lanes own (DeviceSettings.cpp, HapticProfile*.cpp) are listed as PENDING
until they move to cc_send_note(); --strict turns PENDING into a failure.

Writes build/protocol-tests/*. Exit status is non-zero on any failure.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
import media_tests  # noqa: E402  (read-only: MSVC environment, ArduinoJson path, firmware syntax gate)

firmware = media_tests.firmware
src = firmware / 'src'
out_dir = root / 'build' / 'protocol-tests'


def code(text: str) -> str:
    """Source without comments (rules match code only; string literals stay)."""
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    text = re.sub(r'//[^\n]*', ' ', text)
    return text


def read(name: str) -> str:
    return code((src / name).read_text(encoding='utf-8', errors='replace'))


def function_body(text: str, signature: str) -> str:
    """The brace-balanced body that follows the first match of `signature` (a regex)."""
    match = re.search(signature, text)
    if not match:
        return ''
    start = text.index('{', match.end() - 1 if text[match.end() - 1] == '{' else match.end())
    depth = 0
    for i in range(start, len(text)):
        depth += {'{': 1, '}': -1}.get(text[i], 0)
        if depth == 0:
            return text[start:i + 1]
    return ''


RAW_WRITE = re.compile(r'serializeJson\s*\([^;]*,\s*Serial\s*\)|Serial\s*\.\s*(?:print|println|printf|write)\s*\(')
# Units whose writes run on the COM task (lane F2's own), held to the bounded writer.
COM_UNITS = ('com_thread.cpp', 'control_center.cpp', 'cc_media.cpp', 'cc_diag.cpp', 'cc_frame_parse.cpp')
# Other lanes' units the COM task calls (save / load / profile updates): PENDING until they use cc_send_note().
COM_CALLEES = ('DeviceSettings.cpp', 'HapticProfileManager.cpp', 'HapticProfileUpdater.cpp')


def source_rules(strict: bool) -> bool:
    ok = True

    def need(condition: bool, what: str):
        nonlocal ok
        print(f'{"PASS" if condition else "FAIL"} {what}')
        ok &= bool(condition)

    # FW-BUG-001: no raw (unbounded) serial write on any COM path.
    for unit in COM_UNITS:
        hits = [m.group(0) for m in RAW_WRITE.finditer(read(unit))]
        need(not hits, f'FW-BUG-001: {unit} writes only through cc_send_json/cc_send_line'
                       + (f' (found {hits})' if hits else ''))
    out = read('cc_serial_out.cpp')
    note = function_body(out, r'void\s+cc_send_note\s*\([^)]*\)\s*\{')
    # FW-BUG-002: the "#all" listing walks every slot and skips blank ones.
    profiles = function_body(read('com_thread.cpp'), r'void\s+ComThread::handleProfilesCommand\s*\([^)]*\)\s*\{')
    need('pm.size()' not in profiles and re.search(r'i\s*<\s*MAX_PROFILES', profiles),
         'FW-BUG-002: {"profiles":"#all"} iterates MAX_PROFILES slots, not pm.size()')
    # FW-RES-002: no String is allocated for {"message":...} (no consumer; it was never freed), and
    # handleLine allocates a String only for the {"R":...} motor command.
    line = function_body(read('com_thread.cpp'), r'void\s+ComThread::handleLine\s*\([^)]*\)\s*\{')
    news = re.findall(r'new\s+String\s*\(([^)]*)\)', line)
    need(news == ['cmd'], f'FW-RES-002: handleLine allocates a String only for an R command (found {news})')
    # FW-BUG-006: the LCD command carries its text by value; the COM side copies (lcd_text) and never
    # hands the LCD task a pointer to a String it may reassign.
    com = read('com_thread.cpp')
    by_value = com.split('#if defined(CC_LCD_COMMAND_BY_VALUE)')[1:]
    by_value = [block.split('#else')[0].split('#endif')[0] for block in by_value]
    need(len(by_value) >= 3 and not any(re.search(r'=\s*&', block) for block in by_value)
         and sum(block.count('lcd_text(') for block in by_value) >= 7,
         'FW-BUG-006: com_thread.cpp copies screen and profile text into the LcdCommand by value')
    # FW-BUG-006 review: the LCD holds copies, so deleting the current profile through
    # {"profiles":[...]} must re-dispatch every config (setCurrentProfile()'s sequence).
    array = branch_body(profiles, r'p\s*\.\s*is\s*<\s*JsonArray\s*>\s*\(\s*\)')
    tail = array.split('pm.remove(')[-1] if 'pm.remove(' in array else ''
    need(re.search(r'previous\s*=\s*pm\.getCurrentProfile\(\)', array)
         and all(f'dispatch{kind}Config()' in tail for kind in ('Haptic', 'Led', 'Hmi', 'Audio', 'Lcd')),
         'FW-BUG-006 review: {"profiles":[...]} re-dispatches all configs when the current profile is removed')
    # FW-SEC-001: a {"profiles":[...]} list that keeps no existing profile is refused before anything is removed.
    refusal = re.search(r'if\s*\(\s*!\s*keepsOne\s*\)\s*\{[^}]*return\s*;', array)
    need(bool(refusal) and 'pm.remove(' in array and refusal.start() < array.index('pm.remove('),
         'FW-SEC-001: {"profiles":[...]} refuses a list that would delete every profile')
    # FW-SEC-001 follow-up: ComThread::setCurrentProfile returns before the manager call on an empty name, and does
    # not apply the creation rule (isProfileNameOk), so a legacy-named profile stays selectable.
    current = function_body(com, r'void\s+ComThread::setCurrentProfile\s*\([^)]*\)\s*\{')
    guard = re.search(r'if\s*\(\s*name\s*\.\s*length\s*\(\s*\)\s*==\s*0\s*\)\s*return\s*;', current)
    select = re.search(r'HapticProfileManager::getInstance\s*\(\s*\)\s*\.\s*setCurrentProfile\s*\(', current)
    need(bool(guard and select and guard.start() < select.start()) and 'isProfileNameOk' not in current,
         'FW-SEC-001: test_empty_current_name_is_ignored (setCurrentProfile("") returns before selecting; '
         'legacy names stay selectable)')
    header = read('lcd_thread.h')
    command = re.search(r'class\s+LcdCommand\s*\{(.*?)\};', header, flags=re.S)
    if 'CC_LCD_COMMAND_BY_VALUE' in header:
        need(command and 'String' not in command.group(1) and '*' not in command.group(1),
             'FW-BUG-006: lcd_command_owns_its_text (LcdCommand has no String* members)')
    else:
        print(f'{"FAIL" if strict else "PENDING"} FW-BUG-006: lcd_thread.h still passes String* '
              '(lane F3: work/audit/patches/FW-BUG-006.patch)')
        ok &= not strict
    # FW-BUG-027: updates.name goes through isProfileNameOk() before the profile is assigned (`*p = obj`).
    command = function_body(com, r'void\s+ComThread::handleProfileCommand\s*\([^)]*\)\s*\{')
    checked = re.search(r'isProfileNameOk\s*\(\s*new_name\s*\)', command)
    assigned = re.search(r'\*\s*p\s*=\s*obj\s*;', command)
    need(bool(checked and assigned and checked.start() < assigned.start()),
         'FW-BUG-027: test_profile_rename_validates_name (isProfileNameOk(new_name) runs before *p = obj)')
    # FW-BUG-027 review: an existing profile is looked up before the name rule, which guards only creation.
    lookup = re.search(r'p\s*=\s*pm\s*\[\s*pname\s*\]\s*;', command)
    rule = re.search(r'isProfileNameOk\s*\(\s*pname\s*\)', command)
    create = re.search(r'pm\s*\.\s*add\s*\(\s*pname\s*\)', command)
    need(bool(lookup and rule and create and lookup.start() < rule.start() < create.start()),
         'FW-BUG-027 review: test_legacy_profile_name_stays_readable (pm[pname] before isProfileNameOk(pname) before pm.add)')
    # FW-BUG-004: each handleEvents() pass drains a bounded number of key and angle events.
    events = function_body(com, r'void\s+ComThread::handleEvents\s*\(\s*\)\s*\{')
    need(re.search(r'keyBudget\s*>\s*0\s*&&\s*hmi_thread\.get_key_event', events)
         and re.search(r'angleBudget\s*>\s*0\s*&&\s*foc_thread\.get_angle_event', events)
         and '--keyBudget' in events and '--angleBudget' in events,
         'FW-BUG-004: handleEvents drains at most kKeyEventsPerPass key and kAngleEventsPerPass angle events')
    need(re.search(r'kStalled\)\s*\{[^}]*txDead\s*=\s*true', out) and re.search(r'if\s*\(\s*txDead\s*\)', out),
         'FW-BUG-004: cc_serial_out latches a stalled host and drops later replies at once')
    need(bool(note) and re.search(r'availableForWrite\s*\(\s*\)\s*<', note) and 'vTaskDelay' not in note
         and 'fifo_write' not in note, 'FW-BUG-001: cc_send_note writes only what fits now and never waits')
    # FW-BUG-028: the recalibration is reported saved only when storeCalibration() says NVS holds it (a failed store
    # is reported failed and ends the FOC wait at once: CC_CAL_FAIL_SAVE; haptic_fx_tests.cpp cal_handshake_tests).
    calib = re.sub(r'\s+', ' ', function_body(com, r'void\s+ComThread::serviceCalibration\s*\(\s*\)\s*\{'))
    stored = re.search(r'const bool stored = DeviceSettings::getInstance\(\)\.storeCalibration\(cal\);', calib)
    saved = re.findall(r'cc_cal_saved\s*\([^)]*\)', calib)
    need(bool(stored) and saved == ['cc_cal_saved(stored)'] and calib.index('cc_cal_saved(stored)') > stored.start(),
         'FW-BUG-028: serviceCalibration reports storeCalibration\'s result (saved only when it returned true)')
    pending = []
    for unit in COM_CALLEES:
        hits = len(RAW_WRITE.findall(read(unit)))
        if hits:
            pending.append(f'{unit} ({hits})')
    if pending:
        print(f'{"FAIL" if strict else "PENDING"} FW-BUG-001: raw Serial prints on COM paths owned by other lanes: '
              + ', '.join(pending))
        ok &= not strict
    else:
        print('PASS FW-BUG-001: DeviceSettings / HapticProfile* diagnostics use cc_send_note')
    return ok


STUBS = {
    'Arduino.h': '''#pragma once
// Host stub (protocol_pins_tests.py): what src/cc_serial_out.cpp uses. protocol_tests.cpp
// defines the fake CDC and the simulated clock.
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <string>
uint32_t millis();
uint32_t micros();
void taskYIELD();
void vTaskDelay(uint32_t ticks);
class FakeSerial {
public:
    int availableForWrite();
    size_t write(const uint8_t* data, size_t size);
};
extern FakeSerial Serial;
// Enough of Arduino's String for serializeJson(doc, String&) (ArduinoJson's generic writer).
class String {
public:
    String(const char* text = "") : text_(text ? text : "") {}
    const char* c_str() const { return text_.c_str(); }
    size_t length() const { return text_.size(); }
    size_t write(uint8_t c) { text_.push_back(static_cast<char>(c)); return 1; }
    size_t write(const uint8_t* data, size_t size) { text_.append(reinterpret_cast<const char*>(data), size); return size; }
private:
    std::string text_;
};
''',
}


def branch_body(text: str, condition: str) -> str:
    """The statements inside the `if (<condition>) {...}` block (regex `condition`), verbatim."""
    body = function_body(text, r'if\s*\(\s*' + condition + r'\s*\)\s*\{')
    return body[1:-1] if body else ''


def write_snippets(stubs: Path) -> bool:
    """Cuts the firmware statements protocol_tests.cpp compiles against its fakes."""
    com = read('com_thread.cpp')
    profiles = function_body(com, r'void\s+ComThread::handleProfilesCommand\s*\([^)]*\)\s*\{')
    found = re.search(r'template\s*<\s*size_t\s+N\s*>\s*void\s+lcd_text\s*\(', com)
    lcd_text = ''
    if found:
        tail = com[found.start():]
        lcd_text = tail.split('{', 1)[0] + function_body(tail, r'lcd_text[^{]*\{')
    put = function_body(com, r'void\s+ComThread::put_string_message\s*\([^)]*\)\s*\{')
    # FW-BUG-005 / FW-BUG-027 / FW-SEC-004: the profile name rule, {"profile":...,"updates":...} and {"save":true}.
    name_limit = re.findall(r'static\s+constexpr\s+(?:unsigned|size_t)\s+kProfile\w+MaxBytes\s*=\s*\d+\s*;', com)
    name_ok = function_body(com, r'bool\s+ComThread::isProfileNameOk\s*\([^)]*\)\s*\{')
    profile_command = function_body(com, r'void\s+ComThread::handleProfileCommand\s*\([^)]*\)\s*\{')
    line = function_body(com, r'void\s+ComThread::handleLine\s*\([^)]*\)\s*\{')
    save = branch_body(line, r'doc\s*\[\s*"save"\s*\]\s*\.\s*as\s*<\s*bool\s*>\s*\(\s*\)\s*==\s*true')
    snippets = {'profiles_all.inc': branch_body(profiles, r's\s*==\s*"#all"'),
                'profiles_array.inc': branch_body(profiles, r'p\s*\.\s*is\s*<\s*JsonArray\s*>\s*\(\s*\)'),
                'put_string_message.inc': put[1:-1] if put else '',
                'lcd_text.inc': lcd_text,
                'profile_name_limit.inc': chr(10).join(name_limit),
                'profile_name_ok.inc': name_ok,
                'profile_command.inc': profile_command,
                'profile_save.inc': save,
                'event_caps.inc': chr(10).join(re.findall(r'constexpr\s+uint8_t\s+k(?:Key|Angle)EventsPerPass\s*=\s*\d+\s*;', com))}
    ok = True
    for name, body in snippets.items():
        if not body.strip():
            print(f'FAIL snippet {name}: not found in com_thread.cpp')
            ok = False
        (stubs / name).write_text(body + '\n', encoding='utf-8', newline='\n')
    return ok


def by_value_syntax() -> bool:
    """com_thread.cpp and lcd_thread.cpp with FW-BUG-006.patch applied, until lane F3 applies it to src/."""
    if 'CC_LCD_COMMAND_BY_VALUE' in (src / 'lcd_thread.h').read_text(encoding='utf-8', errors='replace'):
        return True                   # the plain firmware_syntax run covered com_thread.cpp and lcd_thread.cpp
    import json
    import shutil
    import tempfile
    patch = root.parent / 'audit' / 'patches' / 'FW-BUG-006.patch'
    # Outside any git work tree (git apply inside one ignores paths outside its cwd); the compiler
    # still runs from the firmware root, so the command lines' relative -I paths hold.
    overlay = Path(tempfile.mkdtemp(prefix='protocol-overlay-'))
    (overlay / 'src').mkdir(parents=True)
    for name in ('lcd_thread.h', 'lcd_thread.cpp', 'com_thread.cpp'):
        shutil.copy(src / name, overlay / 'src' / name)
    applied = subprocess.run(['git', 'apply', str(patch)], cwd=overlay, capture_output=True, text=True)
    if not applied.returncode and 'CC_LCD_COMMAND_BY_VALUE' not in (overlay / 'src' / 'lcd_thread.h').read_text():
        applied = subprocess.CompletedProcess(applied.args, 1, '', 'patched header lacks CC_LCD_COMMAND_BY_VALUE')
    if applied.returncode:
        print(f'FAIL FW-BUG-006: the patch does not apply to src/lcd_thread.*' + chr(10) + applied.stderr)
        shutil.rmtree(overlay, ignore_errors=True)
        return False
    database = json.loads((firmware / 'compile_commands.json').read_text(encoding='utf-8'))
    good = True
    for unit in ('com_thread.cpp', 'lcd_thread.cpp'):
        entry = next(e for e in database if Path(e['file']).as_posix().endswith('src/' + unit))
        command = entry['command']
        source = Path(entry['file']).as_posix().replace('/', chr(92))
        command = command.replace(f'-o {entry.get("output") or ""} -c ', '-fsyntax-only -Wall -Wextra ', 1)
        command = command.replace(' -MMD ', ' ')
        command = command[:-len(source)] + str(overlay / 'src' / unit)
        result = subprocess.run(command, cwd=entry['directory'], capture_output=True, text=True,
                                encoding='utf-8', errors='replace')
        text = (result.stdout + result.stderr).strip()
        ours = [line for line in text.splitlines()
                if re.search(r'(com_thread\.cpp|lcd_thread\.(h|cpp)):\d+:\d+: (error|warning)', line)]
        passed = result.returncode == 0 and not ours
        print(f'{"PASS" if passed else "FAIL"} FW-BUG-006: {unit} compiles against the by-value LcdCommand '
              '(patched overlay, xtensa g++ -fsyntax-only)')
        if not passed:
            print(text[-6000:])
        good &= passed
    shutil.rmtree(overlay, ignore_errors=True)
    return good


def host_tests() -> bool:
    stubs = out_dir / 'stubs'
    stubs.mkdir(parents=True, exist_ok=True)
    if not write_snippets(stubs):
        return False
    for name, text in STUBS.items():
        path = stubs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='\n')
    cl, env = media_tests.msvc_env()
    exe = out_dir / 'protocol_tests.exe'
    result = subprocess.run([
        str(cl), '/nologo', '/EHsc', '/std:c++14', '/W4', '/WX', '/O2', '/D_CRT_SECURE_NO_WARNINGS',
        f'/I{stubs}', f'/I{src}', f'/external:I{media_tests.arduinojson}', '/external:W0',
        str(root / 'protocol_tests.cpp'), str(src / 'cc_serial_out.cpp'),
        f'/Fo{out_dir}\\', f'/Fe{exe}',
    ], cwd=out_dir, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        print((result.stdout + result.stderr)[-6000:])
        print('FAIL protocol_tests.cpp: MSVC /W4 /WX build')
        return False
    return subprocess.run([str(exe)]).returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--firmware-syntax', action='store_true',
                        help='also syntax-check com_thread.cpp, cc_serial_out.cpp and lcd_thread.cpp (xtensa g++ -fsyntax-only)')
    parser.add_argument('--strict', action='store_true', help='other lanes\' PENDING items fail too')
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    started = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = source_rules(args.strict)
    ok &= host_tests()
    if args.firmware_syntax:
        ok &= media_tests.firmware_syntax(['com_thread.cpp', 'cc_serial_out.cpp', 'lcd_thread.cpp'])
        ok &= by_value_syntax()
    print(f'{"PASS" if ok else "FAIL"}: protocol pins [{time.time() - started:.1f} s]')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
