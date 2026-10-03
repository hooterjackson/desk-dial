"""Boot / HMI pins (lane F8: hmi_thread.*, DeviceSettings.*, main.cpp, platformio.ini). Python stdlib + MSVC.

hmi_thread.cpp pulls in FreeRTOS, TinyUSB, FastLED and AceButton, so the host cannot compile it whole.

1. Source rules over hmi_thread.cpp / DeviceSettings.cpp / platformio.ini (comments stripped first). Each rule
   names the finding it pins.
2. boot_tests.cpp, MSVC /W4 /WX, against fakes: the firmware statements it runs are cut verbatim from
   hmi_thread.cpp (SNIPPETS below) and compiled inside a stand-in of the HMI state, so the test exercises the
   shipped code, not a copy of it.
3. --firmware-syntax: also syntax-checks hmi_thread.cpp and DeviceSettings.cpp with their exact PlatformIO
   command lines (xtensa g++ -fsyntax-only, no build; firmware_syntax() below).

Writes build/boot-tests/*. Exit status is non-zero on any failure.
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
import media_tests  # noqa: E402  (read-only: MSVC environment, firmware path)

firmware = media_tests.firmware
src = firmware / 'src'
out_dir = root / 'build' / 'boot-tests'


def code(text: str) -> str:
    """Source without comments (rules match code only; string literals stay)."""
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    text = re.sub(r'//[^\n]*', ' ', text)
    return text


def read(name: str) -> str:
    return code((src / name).read_text(encoding='utf-8', errors='replace'))


def function_body(text: str, signature: str) -> str:
    """The brace-balanced body that follows the first match of `signature` (a regex ending in '{')."""
    match = re.search(signature, text)
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
    return re.sub(r'\s+', ' ', text)


def lib_deps() -> dict:
    """platformio.ini [env:nanofoc_d] lib_deps as {name: (owner, version)}; a bare framework library maps to None."""
    text = (firmware / 'platformio.ini').read_text(encoding='utf-8')
    section = re.search(r'^\[env:nanofoc_d\]$(.*?)(?=^\[|\Z)', text, flags=re.M | re.S).group(1)
    block = re.search(r'^lib_deps\s*=[^\n]*\n((?:[ \t]+[^\n]*\n)+)', section, flags=re.M).group(1)
    out = {}
    for line in block.splitlines():
        line = line.split(';', 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r'([^/@]+)/([^@]+?)\s*@\s*([0-9][^\s]*)', line)
        if match:
            out[match.group(2).strip()] = (match.group(1).strip(), match.group(3))
        else:
            out[line] = None
    return out


def resolved_libdeps() -> dict:
    """{name: (owner, version)} of every library PlatformIO installed for nanofoc_d (its .piopm manifest)."""
    import json
    out = {}
    for manifest in sorted((firmware / '.pio' / 'libdeps' / 'nanofoc_d').glob('*/.piopm')):
        data = json.loads(manifest.read_text(encoding='utf-8'))
        out[data['name']] = (data['spec']['owner'], data['version'])
    return out


def source_rules() -> bool:
    ok = True

    def need(condition, what: str):
        nonlocal ok
        print(f'{"PASS" if condition else "FAIL"} {what}')
        ok &= bool(condition)

    hmi = read('hmi_thread.cpp')
    flat = squash(hmi)
    settings = squash(read('DeviceSettings.cpp'))
    # FW-BUG-013: the offline volume arms only after a claim, persisted, loaded at boot.
    init = squash(function_body(hmi, r'void\s+HmiThread::init\s*\([^)]*\)\s*\{'))
    need('offline_armed = DeviceSettings::getInstance().loadHostSeen();' in init,
         'FW-BUG-013: init() loads the host_seen flag before the threads start')
    need(re.search(r'if \(claimed != cc_was_claimed\) \{[^}]*if \(claimed\) offline_arm_on_claim\(\);', flat),
         'FW-BUG-013: the claim edge arms the offline volume')
    need(re.search(r'bool DeviceSettings::loadHostSeen\(\) \{ return nano_preferences\.getBool\("host_seen", false\);',
                   settings) and
         re.search(r'void DeviceSettings::storeHostSeen\(\) \{ nano_preferences\.putBool\("host_seen", true\);', settings),
         'FW-BUG-013: host_seen is one NVS bool, false until written')
    need(len(re.findall(r'storeHostSeen\(\)', hmi)) == 1,
         'FW-BUG-013: the HMI writes host_seen from offline_arm_on_claim() only')
    need('if (!claimed && !offline_now) updateValue();' in flat,
         'FW-BUG-013: the knob value is gated on offline_now alone (runs while the mode is not armed)')
    # FW-BUG-014: the loop enters the offline volume through offlineTick() (which lets go of held HID state).
    need(re.search(r'cc_sleep_tick\(\); offlineTick\(static_cast<uint32_t>\(millis\(\)\)\);', flat)
         and len(re.findall(r'\boffline_update\(', hmi)) == 2,
         'FW-BUG-014: run() calls offlineTick(), the only caller of offline_update()')
    need(re.search(r'if \(claimed != cc_was_claimed\) \{ releaseHeldHid\(\);', flat),
         'FW-BUG-014: the claim edge lets go through the same releaseHeldHid()')
    receive = squash(function_body(hmi, r'void\s+HmiThread::receiveHmiConfig\s*\(\s*\)\s*\{'))
    need(re.search(r'xSemaphoreGive\(_hmi_config_mutex\); if \(taken\) releaseHeldHid\(\);', receive),
         'FW-BUG-015: a taken hmiConfig lets go of the old one\'s HID state, outside the mutex')
    # FW-SEC-002: every library PlatformIO resolved (.pio/libdeps/<env>/*/.piopm) and the image compiles is pinned in
    # lib_deps at that exact version (owner/name@version), so a fresh clone builds the verified set; Wire is the
    # framework's own. UNBUILT_TRANSITIVE are TinyUSB dependencies PlatformIO downloads but never compiles: a lib_deps
    # entry is always compiled, so they must stay OUT of lib_deps (pinning them would add code to the image).
    unbuilt = {'Adafruit SPIFlash', 'Adafruit NeoPixel'}
    deps = lib_deps()
    resolved = resolved_libdeps()
    need(resolved, f'FW-SEC-002: resolved libraries found under .pio/libdeps ({len(resolved)})')
    for name, (owner, version) in sorted(resolved.items()):
        if name in unbuilt:
            continue
        need(deps.get(name) == (owner, version),
             f'FW-SEC-002: lib_deps pins {owner}/{name}@{version} (has {deps.get(name)})')
    need(not (unbuilt & set(deps)), f'FW-SEC-002: lib_deps leaves the unbuilt {sorted(unbuilt)} out')
    built_dir = firmware / '.pio' / 'build' / 'nanofoc_d'
    built = {d.name for lib in built_dir.glob('lib*') if lib.is_dir() for d in lib.iterdir() if d.is_dir()}
    if built:
        need(not (unbuilt & built), f'FW-SEC-002: the last build compiled none of {sorted(unbuilt)}')
        unpinned = sorted((built & set(resolved)) - set(deps))
        need(not unpinned, f'FW-SEC-002: every compiled .pio/libdeps library is in lib_deps ({unpinned})')
    extra = sorted(set(deps) - set(resolved) - {'Wire'})
    need(not extra, f'FW-SEC-002: nothing in lib_deps that PlatformIO did not resolve ({extra})')
    native = function_body(hmi, r'void\s+HmiThread::nativeLeds\s*\(\s*\)\s*\{')
    sets = re.findall(r'FastLED\.setBrightness\(([^;]*)\);', native)
    need(len(sets) == 2 and all(s.startswith('min(led_max_brightness, ') for s in sets),
         f'FW-BUG-012: every native setBrightness is clamped by led_max_brightness ({sets})')
    # FW-BUG-028: the calibration is one checked NVS entry (behaviour: boot_settings_tests.cpp).
    store = squash(function_body(read('DeviceSettings.cpp'),
                                 r'bool\s+DeviceSettings::storeCalibration\s*\([^)]*\)\s*\{'))
    need(len(re.findall(r'nano_preferences\.put\w+\(', store)) == 1 and
         'if (nano_preferences.putBytes("cal", &blob, sizeof blob) != sizeof blob) return false;' in store,
         'FW-BUG-028: storeCalibration makes one putBytes and checks the length it wrote')
    need(not re.search(r'put(UChar|Float)\("(direction|zero_angle)"', settings),
         'FW-BUG-028: the two-key calibration pair is never written again')
    ok &= release_strings(need)
    # FW-PUB-004: the knob reports "<public>+<build id>.<binary>"; the internal id stays NANO_FIRMWARE_VERSION.
    defines = dict(re.fullmatch(r'-D(\w+)=?(.*)', f).groups() for f in build_flags() if f.startswith('-D'))
    public = defines.get('NANO_FIRMWARE_PUBLIC', '')
    need(re.fullmatch(r'"\d+\.\d+\.\d+"', public), f'FW-PUB-004: NANO_FIRMWARE_PUBLIC is a plain semver ({public})')
    need(re.fullmatch(r'"\d+\.\d+\.\d+-cc\d+\.\d+"', defines.get('NANO_FIRMWARE_VERSION', '')),
         'FW-PUB-004: NANO_FIRMWARE_VERSION stays the internal build id the tooling keys on')
    ctor = squash(function_body(read('DeviceSettings.cpp'), r'DeviceSettings::DeviceSettings\s*\(\s*\)\s*\{'))
    # FW-BUG-001: the save / load / init diagnostics run on the COM task off the task watchdog; a raw print to a
    # host that stopped reading would hang it, so they go through cc_send_note() (never waits).
    unit = read('DeviceSettings.cpp')
    raw = re.findall(r'serializeJson\s*\([^;]*,\s*Serial\s*\)|Serial\s*\.\s*(?:print|println|printf|write)\s*\(', unit)
    need(not raw and '#include "cc_serial_out.h"' in unit and len(re.findall(r'cc_send_note\s*\(', unit)) == 11,
         f'FW-BUG-001: DeviceSettings.cpp writes its 11 diagnostics only through cc_send_note() (raw: {raw})')
    need('firmwareVersion = String(cc_fw_version());' in ctor,
         'FW-PUB-004: settings firmwareVersion is cc_fw_version() (public + build id + binary)')
    main_cpp = read('main.cpp')
    need('Serial.println(cc_fw_version());' in squash(main_cpp) and 'NANO_FIRMWARE_VERSION' not in main_cpp,
         'FW-PUB-004: the boot banner prints the same reported version')
    users = [p.name for p in src.rglob('*.c*') if 'NANO_FIRMWARE_VERSION' in code(p.read_text('utf-8', 'replace'))]
    need(not users, f'FW-PUB-004: no unit reports the internal id directly ({users})')
    return ok


def build_flags() -> list:
    """platformio.ini [env:nanofoc_d] build_flags tokens (shlex-split like SCons ParseFlags; ';' lines dropped)."""
    import shlex
    text = (firmware / 'platformio.ini').read_text(encoding='utf-8')
    section = re.search(r'^\[env:nanofoc_d\]$(.*?)(?=^\[|\Z)', text, flags=re.M | re.S).group(1)
    block = re.search(r'^build_flags\s*=[^\n]*\n((?:[ \t]+[^\n]*\n)+)', section, flags=re.M).group(1)
    out = []
    for line in block.splitlines():
        line = line.strip()
        if line and not line.startswith(';'):
            out += shlex.split(line, posix=True)
    return out


def home_prefix_hits(data: bytes) -> int:
    """Occurrences of the build host's home directory (either slash, any case) in `data`."""
    home = str(Path.home())
    forms = {home.replace('\\', '/').lower().encode(), home.replace('/', '\\').lower().encode()}
    lowered = data.lower()
    return sum(lowered.count(form) for form in forms)


def scons_local():
    """PlatformIO's bundled SCons (tool-scons/scons-local-*) under the pinned core dir, or None."""
    import os
    cores = [os.environ.get('PLATFORMIO_CORE_DIR'), firmware.parents[3] / 'pio-knob', Path.home() / '.platformio']
    for core in cores:
        if core:
            found = sorted(Path(core).glob('packages/tool-scons/scons-local-*'))
            if found:
                return found[-1]
    return None


def prefix_map_tests(need) -> bool:
    """FW-PUB-003 (review): the -fmacro-prefix-map flags come from scripts/path_prefix_map.py as already expanded,
    single CCFLAGS items, so a packages or project path with a space stays one compiler argument. Proven with
    PlatformIO's own SCons: the old build_flags token splits such a path in two, the script's item does not."""
    import importlib.util
    good = True

    def check(condition, what):
        nonlocal good
        need(condition, what)
        good &= bool(condition)

    ini = (firmware / 'platformio.ini').read_text(encoding='utf-8')
    scripts = re.search(r'^extra_scripts\s*=([^\n]*\n(?:[ \t]+[^\n]*\n)*)', ini, flags=re.M)
    check(scripts and 'pre:scripts/path_prefix_map.py' in scripts.group(1).split(),
          'FW-PUB-003: platformio.ini runs scripts/path_prefix_map.py before the build')
    check(not any('macro-prefix-map' in flag for flag in build_flags()),
          'FW-PUB-003: build_flags carry no -fmacro-prefix-map token (SCons would split a path with a space)')
    script = firmware / 'scripts' / 'path_prefix_map.py'
    spec = importlib.util.spec_from_file_location('path_prefix_map', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    packages = r'C:\Users\someone Last\.platformio\packages'
    project = 'D:/Knob $Work/NanoD_RatchetH1/'
    flags = module.prefix_map_flags([(project, '.'), (packages, 'pio-pkgs')])
    check(flags == ['-fmacro-prefix-map=D:/Knob $$Work/NanoD_RatchetH1=.',
                    r'-fmacro-prefix-map=D:\Knob $$Work\NanoD_RatchetH1=.',
                    r'-fmacro-prefix-map=C:\Users\someone Last\.platformio\packages=pio-pkgs',
                    '-fmacro-prefix-map=C:/Users/someone Last/.platformio/packages=pio-pkgs'],
          f'FW-PUB-003: both slash forms per root, no trailing separator, project first, $ escaped ({flags})')

    class FakeEnv:
        appended = []
        def subst(self, text):
            return {'$PROJECT_DIR': project, '$PROJECT_PACKAGES_DIR': packages}[text]
        def Append(self, **kw):
            self.appended.append(kw)
    fake = FakeEnv()
    scope = {'__name__': 'SCons', 'Import': lambda name: scope.__setitem__(name, fake)}
    exec(compile(script.read_text(encoding='utf-8'), str(script), 'exec'), scope)
    check(fake.appended == [{'CCFLAGS': flags}],
          f'FW-PUB-003: as a pre-script it appends the expanded maps to the global CCFLAGS ({len(fake.appended)} call)')

    scons = scons_local()
    if scons is None:
        print('INFO FW-PUB-003: PlatformIO tool-scons not installed here; the SCons expansion check is skipped')
        return good
    sys.path.insert(0, str(scons))
    try:
        import SCons.Environment
        import SCons.Platform.win32
        import SCons.Subst
    finally:
        sys.path.remove(str(scons))
    spaced = 'D:/Knob Work/NanoD_RatchetH1'   # SCons itself expands a '$' inside PROJECT_DIR, so none here
    env = SCons.Environment.Environment(tools=[], PROJECT_DIR=spaced, PROJECT_PACKAGES_DIR=packages)
    scope = {'__name__': 'SCons', 'Import': lambda name: scope.__setitem__(name, env)}
    exec(compile(script.read_text(encoding='utf-8'), str(script), 'exec'), scope)
    args = [str(arg) for arg in env.subst_list('$CCFLAGS')[0]]
    expected = module.prefix_map_flags([(spaced, '.'), (packages, 'pio-pkgs')])
    check(args == expected, f'FW-PUB-003: SCons {scons.name} expands each map to exactly one argument ({args})')
    line = ' '.join(SCons.Subst.escape_list(env.subst_list('$CCFLAGS')[0], SCons.Platform.win32.escape))
    check(f'"-fmacro-prefix-map={packages}=pio-pkgs"' in line,
          'FW-PUB-003: on the Windows command line the packages map with a space is one quoted argument')
    old = SCons.Environment.Environment(tools=[], PROJECT_PACKAGES_DIR=packages)
    old.Append(CCFLAGS=['-fmacro-prefix-map=$PROJECT_PACKAGES_DIR=pio-pkgs'])
    split = [str(arg) for arg in old.subst_list('$CCFLAGS')[0]]
    check(len(split) == 2, f'FW-PUB-003: control: the former build_flags token splits that path in two ({split})')
    return good


def release_strings(need) -> bool:
    """FW-PUB-003: the image carries no absolute build path. GCC's -fmacro-prefix-map rewrites __FILE__ for the
    framework packages and the project (libdeps included); every firmware.bin built after platformio.ini last
    changed must hold the home directory 0 times (older images, built before the flags, are reported, not judged)."""
    good = prefix_map_tests(need)
    ini_time = (firmware / 'platformio.ini').stat().st_mtime
    judged = 0
    for image in sorted((firmware / '.pio').glob('build*/nanofoc_d/firmware.bin')):
        if image.stat().st_mtime < ini_time:
            continue
        judged += 1
        hits = home_prefix_hits(image.read_bytes())
        need(hits == 0, f'FW-PUB-003: {image.parent.parent.name}/firmware.bin holds the home directory {hits} times')
        good &= hits == 0
    print(f'INFO FW-PUB-003: {judged} firmware.bin built since platformio.ini changed '
          f'(the integration build is judged here)')
    return good


STUBS = {
    'Arduino.h': '''#pragma once
// Host stub (boot_pins_tests.py): what hmi_api.h needs (String in keyAction).
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <string>
class String {
public:
    String(const char* text = "") : text_(text ? text : "") {}
    bool operator!=(const char* other) const { return text_ != (other ? other : ""); }
    bool operator==(const char* other) const { return text_ == (other ? other : ""); }
    const char* c_str() const { return text_.c_str(); }
private:
    std::string text_;
};
''',
    'common/foc_utils.h': '#pragma once\n',
}


def snippets() -> dict:
    hmi = read('hmi_thread.cpp')
    out = {}
    # The offline volume's state block, from the CDC flags to offline_armed (FW-BUG-013).
    block = re.search(r'bool cdc_primed.*?bool offline_armed = false;', hmi, flags=re.S)
    out['offline_state.inc'] = block.group(0) if block else ''
    out['offline_update.inc'] = function_body(hmi, r'void\s+offline_update\s*\(\s*uint32_t\s+now\s*\)\s*\{')
    out['offline_arm_on_claim.inc'] = function_body(hmi, r'void\s+offline_arm_on_claim\s*\(\s*\)\s*\{')
    claim = function_body(hmi, r'if\s*\(\s*claimed\s*!=\s*cc_was_claimed\s*\)\s*\{')
    out['claim_edge.inc'] = claim
    # FW-BUG-014 / -015: the HID state the key actions build and handleHid() reports.
    out['handle_key_action.inc'] = function_body(hmi, r'void\s+HmiThread::handleKeyAction\s*\([^)]*\)\s*\{')
    # MSVC takes designated initializers only in C++20, where hmi_api.h's typedef'd unnamed structs with default
    # member initializers are refused: the gamepad report's `.field = value` list becomes positional (same order
    # as TinyUSB's hid_gamepad_report_t and the fake), nothing else in the body changes.
    hid = function_body(hmi, r'void\s+HmiThread::handleHid\s*\(\s*\)\s*\{')
    out['handle_hid.inc'] = re.sub(r'hid_gamepad_report_t report = \{[^}]*\}',
                                   lambda m: re.sub(r'\.(\w+)\s*=\s*', r'/* \1 */ ', m.group(0)), hid)
    out['offline_tick.inc'] = function_body(hmi, r'void\s+HmiThread::offlineTick\s*\([^)]*\)\s*\{')
    # FW-BUG-041: the native knob value's MIDI CC (clamped before it is narrowed to a byte).
    # FW-TST-012: the offline volume's Consumer press / release pairing.
    out['handle_consumer.inc'] = function_body(hmi, r'void\s+HmiThread::handleConsumer\s*\(\s*\)\s*\{')
    out['update_value.inc'] = function_body(hmi, r'void\s+HmiThread::updateValue\s*\(\s*\)\s*\{')
    out['release_held_hid.inc'] = function_body(hmi, r'void\s+HmiThread::releaseHeldHid\s*\(\s*\)\s*\{')
    out['receive_hmi_config.inc'] = function_body(hmi, r'void\s+HmiThread::receiveHmiConfig\s*\(\s*\)\s*\{')
    out['native_leds.inc'] = function_body(hmi, r'void\s+HmiThread::nativeLeds\s*\(\s*\)\s*\{')
    handler = function_body(hmi, r'void\s+HmiThreadButtonHandler::handleEvent\s*\([^)]*\)\s*\{')
    switch = function_body(handler, r'switch\s*\(\s*eventType\s*\)\s*\{')
    out['native_switch.inc'] = 'switch (eventType) ' + switch if switch else ''
    return out


def host_tests() -> bool:
    stubs = out_dir / 'stubs'
    stubs.mkdir(parents=True, exist_ok=True)
    ok = True
    for name, body in snippets().items():
        if not body.strip():
            print(f'FAIL snippet {name}: not found in hmi_thread.cpp')
            ok = False
        (stubs / name).write_text(body + '\n', encoding='utf-8', newline='\n')
    for name, text in STUBS.items():
        path = stubs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='\n')
    if not ok:
        return False
    cl, env = media_tests.msvc_env()
    exe = out_dir / 'boot_tests.exe'
    result = subprocess.run([
        str(cl), '/nologo', '/EHsc', '/std:c++17', '/W4', '/WX', '/wd5208', '/wd4456', '/wd4244', '/O2', '/D_CRT_SECURE_NO_WARNINGS',
        f'/I{stubs}', f'/I{src}', str(root / 'boot_tests.cpp'), f'/Fo{out_dir}\\', f'/Fe{exe}',
    ], cwd=out_dir, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        print((result.stdout + result.stderr)[-6000:])
        print('FAIL boot_tests.cpp: MSVC /W4 /WX build')
        return False
    return subprocess.run([str(exe)]).returncode == 0


SETTINGS_STUBS = {
    'Arduino.h': r'''#pragma once
// Host stub (boot_pins_tests.py, boot_settings_tests.cpp): what DeviceSettings.cpp and ArduinoJson's Arduino
// String / Stream / Print support use.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <string>
#define HEX 16
class String {
public:
    String(const char* text = "") : text_(text ? text : "") {}
    String(uint64_t value, int base) { char b[32]; snprintf(b, sizeof b, base == HEX ? "%llx" : "%llu", (unsigned long long)value); text_ = b; }
    String& operator=(const char* text) { text_ = text ? text : ""; return *this; }
    bool concat(const char* text) { text_ += text ? text : ""; return true; }
    size_t length() const { return text_.size(); }
    const char* c_str() const { return text_.c_str(); }
    bool operator==(const char* other) const { return text_ == (other ? other : ""); }
    friend String operator+(const char* left, const String& right) { return String((std::string(left) + right.text_).c_str()); }
private:
    std::string text_;
};
class Print {
public:
    virtual ~Print() {}
    virtual size_t write(uint8_t c) = 0;
    virtual size_t write(const uint8_t* s, size_t n) { size_t i = 0; while (i < n && write(s[i])) ++i; return i; }
};
class Printable {
public:
    virtual ~Printable() {}
    virtual size_t printTo(Print& p) const = 0;
};
class Stream : public Print {
public:
    virtual int read() = 0;
    size_t readBytes(char* buffer, size_t length) { size_t n = 0; int c; while (n < length && (c = read()) >= 0) buffer[n++] = (char)c; return n; }
};
inline int fake_serial_raw_writes = 0;   // FW-BUG-001: DeviceSettings never writes Serial directly
struct FakeSerial {
    void println(const char*) { ++fake_serial_raw_writes; }
    void print(const char*) { ++fake_serial_raw_writes; }
} Serial;
struct FakeEsp { uint64_t getEfuseMac() { return 0x1234abcdULL; } } ESP;
''',
    'SPIFFS.h': r'''#pragma once
// Host stub: an in-memory SPIFFS. Files are committed on close().
#include <map>
#include <memory>
#include "Arduino.h"
inline std::map<std::string, std::string>& fake_spiffs_files() { static std::map<std::string, std::string> files; return files; }
class File : public Stream {
public:
    File() {}
    File(const std::string& path, bool writing) : state_(std::make_shared<State>()) {
        state_->path = path; state_->writing = writing;
        if (!writing) state_->data = fake_spiffs_files()[path];
    }
    explicit operator bool() const { return state_ != nullptr; }
    int read() override { if (!state_ || state_->pos >= state_->data.size()) return -1; return (unsigned char)state_->data[state_->pos++]; }
    size_t write(uint8_t c) override { if (!state_) return 0; state_->data.push_back((char)c); return 1; }
    using Print::write;
    void close() { if (state_ && state_->writing) fake_spiffs_files()[state_->path] = state_->data; state_.reset(); }
private:
    struct State { std::string path, data; size_t pos = 0; bool writing = false; };
    std::shared_ptr<State> state_;
};
struct FakeSpiffs {
    bool begin(bool) { return true; }
    bool exists(const char* path) { return fake_spiffs_files().count(path) != 0; }
    File open(const char* path, const char* mode) { return File(path, mode[0] == 'w'); }
} SPIFFS;
''',
    'Preferences.h': r'''#pragma once
// Host stub: ESP32 Preferences over an in-memory NVS. Every put is one atomic entry write (as NVS is); the test can
// fail the next put (fail_puts) or stop the "power" after N entry writes (power_cut_after: later writes are lost).
#include <map>
#include <string>
#include <vector>
#include "Arduino.h"
class Preferences {
public:
    std::map<std::string, std::vector<uint8_t>> entries;
    std::vector<std::string> writes;     // keys in write order (puts and removes)
    int fail_puts = 0;
    int power_cut_after = -1;            // >= 0: entry writes allowed before the cut
    bool begin(const char*, bool) { return true; }
    bool isKey(const char* key) { return entries.count(key) != 0; }
    bool remove(const char* key) { if (!allowed(key)) return false; return entries.erase(key) != 0; }
    size_t putBytes(const char* key, const void* value, size_t len) { return put(key, value, len); }
    size_t putUChar(const char* key, uint8_t value) { return put(key, &value, 1); }
    size_t putFloat(const char* key, float value) { return put(key, &value, sizeof value); }
    size_t putBool(const char* key, bool value) { uint8_t v = value; return put(key, &v, 1); }
    size_t putString(const char* key, String value) { return put(key, value.c_str(), value.length()); }
    size_t getBytesLength(const char* key) { return isKey(key) ? entries[key].size() : 0; }
    size_t getBytes(const char* key, void* buf, size_t maxLen) {
        if (!isKey(key) || entries[key].size() > maxLen) return 0;
        memcpy(buf, entries[key].data(), entries[key].size()); return entries[key].size();
    }
    uint8_t getUChar(const char* key, uint8_t fallback) { return isKey(key) && entries[key].size() == 1 ? entries[key][0] : fallback; }
    float getFloat(const char* key, float fallback) {
        if (!isKey(key) || entries[key].size() != sizeof(float)) return fallback;
        float v; memcpy(&v, entries[key].data(), sizeof v); return v;
    }
    bool getBool(const char* key, bool fallback) { return isKey(key) && entries[key].size() == 1 ? entries[key][0] != 0 : fallback; }
    String getString(const char* key, const char* fallback) {
        if (!isKey(key)) return String(fallback);
        return String(std::string(entries[key].begin(), entries[key].end()).c_str());
    }
private:
    bool allowed(const char* key) {
        if (power_cut_after == 0) return false;
        if (power_cut_after > 0) --power_cut_after;
        writes.push_back(key);
        return true;
    }
    size_t put(const char* key, const void* value, size_t len) {
        if (fail_puts > 0) { --fail_puts; return 0; }
        if (!allowed(key)) return 0;
        const uint8_t* p = static_cast<const uint8_t*>(value);
        entries[key] = std::vector<uint8_t>(p, p + len);
        return len;
    }
};
''',
    'common/foc_utils.h': '#pragma once\n#define NOT_SET -12345.0f\n',
}


def settings_tests() -> bool:
    """boot_settings_tests.cpp: src/DeviceSettings.cpp compiled whole (MSVC /W4 /WX) against ArduinoJson and fakes."""
    stubs = out_dir / 'settings-stubs'
    for name, text in SETTINGS_STUBS.items():
        path = stubs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='\n')
    cl, env = media_tests.msvc_env()
    exe = out_dir / 'boot_settings_tests.exe'
    result = subprocess.run([
        str(cl), '/nologo', '/EHsc', '/std:c++17', '/W4', '/WX', '/wd5208', '/wd4244', '/wd4458', '/O2',
        '/D_CRT_SECURE_NO_WARNINGS', '/DARDUINOJSON_ENABLE_ARDUINO_STRING=1', '/DARDUINOJSON_ENABLE_ARDUINO_STREAM=1',
        '/DARDUINOJSON_ENABLE_ARDUINO_PRINT=1', '/DARDUINOJSON_ENABLE_PROGMEM=0',
        f'/I{stubs}', f'/I{src}', f'/I{firmware / "include"}', f'/external:I{media_tests.arduinojson}',
        '/external:W0', str(root / 'boot_settings_tests.cpp'), f'/Fo{out_dir}\\', f'/Fe{exe}',
    ], cwd=out_dir, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        print((result.stdout + result.stderr)[-6000:])
        print('FAIL boot_settings_tests.cpp: MSVC /W4 /WX build')
        return False
    return subprocess.run([str(exe)]).returncode == 0


def lvconf_guard_tests() -> bool:
    """FW-BUG-017: (1) scripts/lvconf_guard.py puts lv_conf.h's hash into every compile command, so a changed
    lv_conf.h rebuilds every object; (2) main.cpp's cc_lvgl_layout_ok() trips on an image whose LVGL objects were
    compiled with LV_OBJ_STYLE_CACHE 0 and its src/ units with 1 (MSVC, two translation units, one link)."""
    import importlib.util
    import shutil
    ok = True

    def need(condition, what: str):
        nonlocal ok
        print(f'{"PASS" if condition else "FAIL"} {what}')
        ok &= bool(condition)

    ini = (firmware / 'platformio.ini').read_text(encoding='utf-8')
    need(re.search(r'^extra_scripts\s*=(?:[^\n]*\n[ \t]+)*?[ \t]*pre:scripts/lvconf_guard\.py\s*$', ini, flags=re.M),
         'FW-BUG-017: platformio.ini runs scripts/lvconf_guard.py before the build')
    need('-DLV_CONF_PATH=$PROJECT_DIR/include/lv_conf.h' in build_flags(),
         'FW-BUG-017: the guard hashes the lv_conf.h LV_CONF_PATH names (include/lv_conf.h)')
    script = firmware / 'scripts' / 'lvconf_guard.py'
    spec = importlib.util.spec_from_file_location('lvconf_guard', script)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    work = out_dir / 'lvconf'
    shutil.rmtree(work, ignore_errors=True)
    conf = (firmware / 'include' / 'lv_conf.h').read_bytes()
    projects = {}
    for name, data in {'same': conf, 'same-crlf': conf.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'),
                       'cache0': re.sub(rb'(#define\s+LV_OBJ_STYLE_CACHE\s+)1', rb'\g<1>0', conf),
                       'mem': re.sub(rb'(#define\s+LV_MEM_SIZE\s+)', rb'\g<1>8 + ', conf)}.items():
        (work / name / 'include').mkdir(parents=True, exist_ok=True)
        (work / name / 'include' / 'lv_conf.h').write_bytes(data)
        projects[name] = guard.lv_conf_define(str(work / name))
    real = guard.lv_conf_define(str(firmware))
    need(projects['same'] == real and projects['same-crlf'] == real,
         f'FW-BUG-017: unchanged lv_conf.h (either line ending) keeps {real[0]}={real[1]}: nothing rebuilds')
    need(projects['cache0'] != real, 'FW-BUG-017: LV_OBJ_STYLE_CACHE 1 -> 0 changes the define: every object rebuilds')
    need(projects['mem'] != real, 'FW-BUG-017: an LV_MEM_SIZE change changes the define: every object rebuilds')

    class FakeEnv:
        appended = []
        def subst(self, text):
            return str(firmware) if text == '$PROJECT_DIR' else text
        def Append(self, **kw):
            self.appended.append(kw)
    fake = FakeEnv()
    scope = {'__name__': 'SCons', 'Import': lambda name: scope.__setitem__(name, fake)}
    exec(compile(script.read_text(encoding='utf-8'), str(script), 'exec'), scope)
    need(fake.appended == [{'CPPDEFINES': [real]}],
         f'FW-BUG-017: as a PlatformIO pre-script it appends the define to the global CPPDEFINES ({fake.appended})')

    # (2) the boot check, against LVGL's real headers and the firmware's own guard body.
    lvgl = firmware / '.pio' / 'libdeps' / 'nanofoc_d' / 'lvgl'
    lv_obj_c = (lvgl / 'src' / 'core' / 'lv_obj.c').read_text(encoding='utf-8')
    need(re.search(r'const lv_obj_class_t lv_obj_class = \{[^}]*\.instance_size = \(sizeof\(lv_obj_t\)\)', lv_obj_c),
         'FW-BUG-017: LVGL records its compiled sizeof(lv_obj_t) as lv_obj_class.instance_size')
    body = function_body(read('main.cpp'), r'bool\s+cc_lvgl_layout_ok\s*\(\s*\)\s*\{')
    need(body, 'FW-BUG-017: main.cpp defines cc_lvgl_layout_ok()')
    need(re.search(r'if \(!cc_lvgl_layout_ok\(\)\) \{ Serial\.println\("ERROR: LVGL', squash(read('main.cpp'))),
         'FW-BUG-017: setup() reports a mixed image on the console')
    host_conf = (root / 'lv_conf.h').read_text(encoding='utf-8')
    for cache in (0, 1):
        folder = work / f'conf{cache}'
        folder.mkdir(parents=True, exist_ok=True)
        text, count = re.subn(r'(#define\s+LV_OBJ_STYLE_CACHE\s+)1', rf'\g<1>{cache}', host_conf)
        need(count == 1, f'FW-BUG-017: host lv_conf.h with LV_OBJ_STYLE_CACHE {cache}')
        (folder / 'lv_conf.h').write_text(text, encoding='utf-8', newline='\n')
    (work / 'lvgl_obj.c').write_text(
        '/* LVGL\'s lv_obj.c as far as the guard reads it: the class records sizeof(lv_obj_t) under its lv_conf.h. */\n'
        '#include "lvgl.h"\nconst lv_obj_class_t lv_obj_class = { .instance_size = (sizeof(lv_obj_t)) };\n',
        encoding='utf-8', newline='\n')
    (work / 'guard.cpp').write_text(
        '#include <stdio.h>\n#include "lvgl.h"\n'
        '// cc_lvgl_layout_ok(), cut verbatim from src/main.cpp\nbool cc_lvgl_layout_ok()\n' + body + '\n'
        'int main() { printf("%u %u\\n", (unsigned)lv_obj_class.instance_size, (unsigned)sizeof(lv_obj_t));\n'
        '  return cc_lvgl_layout_ok() ? 0 : 3; }\n', encoding='utf-8', newline='\n')
    cl, env = media_tests.msvc_env()
    common = ['/nologo', '/W3', '/DLV_CONF_INCLUDE_SIMPLE', '/DLV_LVGL_H_INCLUDE_SIMPLE', '/D_CRT_SECURE_NO_WARNINGS',
              f'/I{lvgl}']
    results = {}
    for lib_cache, src_cache in ((0, 1), (1, 1), (1, 0)):
        tag = f'lib{lib_cache}-src{src_cache}'
        objs = []
        for unit, cache in (('lvgl_obj.c', lib_cache), ('guard.cpp', src_cache)):
            obj = work / f'{tag}-{Path(unit).stem}.obj'
            r = subprocess.run([str(cl), *common, '/EHsc' if unit.endswith('.cpp') else '/TC',
                                f'/I{work / f"conf{cache}"}', '/c', str(work / unit), f'/Fo{obj}'],
                               cwd=work, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
            if r.returncode:
                print((r.stdout + r.stderr)[-3000:])
            objs.append(obj)
        exe = work / f'{tag}.exe'
        r = subprocess.run([str(cl), '/nologo', *map(str, objs), f'/Fe{exe}'], cwd=work, env=env,
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode or not exe.exists():
            print((r.stdout + r.stderr)[-3000:])
            need(False, f'FW-BUG-017: {tag} host link')
            continue
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        results[tag] = (run.returncode, run.stdout.strip())
    need(results.get('lib1-src1', (None,))[0] == 0,
         f'FW-BUG-017: one lv_conf.h (STYLE_CACHE 1 everywhere): the guard passes {results.get("lib1-src1")}')
    need(results.get('lib0-src1', (None,))[0] == 3,
         f'FW-BUG-017: LVGL built with STYLE_CACHE 0, src/ with 1 (the cc5.7 failure): the guard trips '
         f'{results.get("lib0-src1")}')
    need(results.get('lib1-src0', (None,))[0] == 3,
         f'FW-BUG-017: the reverse mix trips it too {results.get("lib1-src0")}')
    return ok


def firmware_syntax(units) -> bool:
    """xtensa g++ -fsyntax-only with each unit's exact compile_commands.json line (no build, no PlatformIO).
    Fails on any error; hmi_thread.cpp carries warnings older than this lane (see WARNING_BUDGET), so
    warnings are counted against WARNING_BUDGET instead of failing outright."""
    import json
    database = json.loads((firmware / 'compile_commands.json').read_text(encoding='utf-8'))
    entries = {Path(e['file']).as_posix(): e for e in database}
    ok = True
    for unit in units:
        entry = entries[f'src/{unit}']
        command, source, output = entry['command'], str(Path(entry['file'])), entry['output']
        command = command.replace(f'-o {output} -c ', '-fsyntax-only -Wall -Wextra ', 1).replace(' -MMD ', ' ')
        # compile_commands.json is as old as its last `pio run -t compiledb`: a -D platformio.ini gained since
        # (FW-PUB-004's NANO_FIRMWARE_PUBLIC) is added in the database's own quoting.
        for flag in build_flags():
            name = re.match(r'-D(\w+)', flag)
            if name and f'-D{name.group(1)}=' not in command and f'-D{name.group(1)} ' not in command:
                quoted = flag.replace('"', '\\"')
                command = command.replace('-fsyntax-only ', f'-fsyntax-only {quoted} ', 1)
        command = command[:-len(source)] + str(Path('src') / unit)
        result = subprocess.run(command, cwd=entry['directory'], capture_output=True, text=True,
                                encoding='utf-8', errors='replace')
        text = (result.stdout + result.stderr).strip()
        errors = [line for line in text.splitlines() if re.match(r'^src\W[^:]+:\d+:\d+: error', line)]
        warnings = [line for line in text.splitlines() if re.match(r'^src\W[^:]+:\d+:\d+: warning', line)]
        good = result.returncode == 0 and not errors and len(warnings) <= WARNING_BUDGET.get(unit, 0)
        print(f'{"PASS" if good else "FAIL"} {unit}: xtensa g++ -fsyntax-only ({len(errors)} errors, '
              f'{len(warnings)} warnings, budget {WARNING_BUDGET.get(unit, 0)})')
        if not good:
            print(text[-6000:])
            ok = False
    return ok


# src/ warnings each unit had before lane F8's fixes (run's unused timers, the native KeyEvt initializer, the
# KA_NONE switch, updateValue's _constrain, IdleLeds' statics); none is in code this lane touches.
WARNING_BUDGET = {'hmi_thread.cpp': 10, 'DeviceSettings.cpp': 0, 'main.cpp': 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--firmware-syntax', action='store_true',
                        help='also syntax-check hmi_thread.cpp, DeviceSettings.cpp and main.cpp (xtensa g++ -fsyntax-only)')
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    started = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = source_rules()
    ok &= host_tests()
    ok &= lvconf_guard_tests()
    ok &= settings_tests()
    if args.firmware_syntax:
        ok &= firmware_syntax(['hmi_thread.cpp', 'DeviceSettings.cpp', 'main.cpp'])
    print(f'{"PASS" if ok else "FAIL"}: boot pins [{time.time() - started:.1f} s]')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
