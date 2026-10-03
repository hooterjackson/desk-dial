"""FW-BUG-040 pins for HapticProfile::keyActionFromJSON (HapticProfileManager.cpp). Python stdlib + MSVC.

The host cannot compile HapticProfileManager.cpp whole (SPIFFS, the profile manager, audio), so the body of
keyActionFromJSON is cut verbatim from the source and compiled, MSVC /W4 /WX, against the real ArduinoJson and
src/hmi_api.h (String = std::string), then run:

- a midi action (channel 1, cc 7) updated with {"type":"key"} and no keyCodes leaves hid.num == 0 and no code,
  so a press sends nothing (hmi_thread.cpp sends exactly hid.num codes, boot_tests empty_keycodes_sends_nothing);
- a key action with codes [4,5,6] updated with keyCodes [9] leaves only code 9 (no stale codes past num);
- a key action updated with {"type":"key"} and no keyCodes keeps its codes (an update without keyCodes is not a clear).

Writes build/keyaction-tests/*. Exit status is non-zero on any failure.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
import media_tests  # noqa: E402  (read-only: MSVC environment, ArduinoJson path)

src = media_tests.firmware / 'src'
out_dir = root / 'build' / 'keyaction-tests'


def code(text: str) -> str:
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    return re.sub(r'//[^\n]*', ' ', text)


def function_body(text: str, signature: str) -> str:
    match = re.search(signature, text)
    if not match:
        return ''
    start = text.index('{', match.start())
    depth = 0
    for i in range(start, len(text)):
        depth += {'{': 1, '}': -1}.get(text[i], 0)
        if depth == 0:
            return text[start:i + 1]
    return ''


TEST = r'''
#include <ArduinoJson.h>
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <string>
#define String std::string
#include "hmi_api.h"
using std::min;

#define update_field(obj, prop, field) if (!obj[#prop].isNull()) { field = obj[#prop].as<decltype(field)>(); dirty = true; }

struct Parser {
    bool dirty = false;
    void keyActionFromJSON(JsonObject& obj, keyAction& action)
#include "key_action_body.inc"
};

static int failures = 0;
static void check(bool ok, const char* what) {
    std::printf("%s %s\n", ok ? "PASS" : "FAIL", what);
    if (!ok) ++failures;
}

static void apply(const char* json, keyAction& action) {
    JsonDocument doc;
    deserializeJson(doc, json);
    JsonObject obj = doc.as<JsonObject>();
    Parser p;
    p.keyActionFromJSON(obj, action);
}

int main() {
    {
        keyAction a = keyAction();
        apply("{\"type\":\"midi\",\"channel\":1,\"cc\":7,\"val\":100}", a);
        check(a.type == KA_MIDI && a.midi.channel == 1 && a.midi.cc == 7, "FW-BUG-040: control: the midi action parses");
        apply("{\"type\":\"key\"}", a);
        bool clean = a.type == KA_KEY && a.hid.num == 0;
        for (int k = 0; k < MAX_KEY_KEYCODES; ++k) clean = clean && a.hid.key_codes[k] == 0;
        check(clean, "FW-BUG-040: midi -> {type:key} without keyCodes: hid.num 0, no codes (a press sends nothing)");
    }
    {
        keyAction a = keyAction();
        apply("{\"type\":\"key\",\"keyCodes\":[4,5,6]}", a);
        check(a.type == KA_KEY && a.hid.num == 3 && a.hid.key_codes[2] == 6, "FW-BUG-040: control: a three-code binding");
        apply("{\"type\":\"key\",\"keyCodes\":[9]}", a);
        check(a.hid.num == 1 && a.hid.key_codes[0] == 9 && a.hid.key_codes[1] == 0 && a.hid.key_codes[2] == 0,
              "FW-BUG-040: a shorter keyCodes list leaves no stale codes past its count");
        apply("{\"type\":\"key\"}", a);
        check(a.hid.num == 1 && a.hid.key_codes[0] == 9, "FW-BUG-040: key -> {type:key} without keyCodes keeps its codes");
    }
    {
        keyAction a = keyAction();
        apply("{\"type\":\"mouse\",\"buttons\":3}", a);
        apply("{\"type\":\"key\",\"keyCodes\":[]}", a);
        check(a.type == KA_KEY && a.hid.num == 0 && a.hid.key_codes[0] == 0, "FW-BUG-040: mouse -> key with keyCodes []: empty");
    }
    return failures ? 1 : 0;
}
'''


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    stubs = out_dir / 'stubs'
    (stubs / 'common').mkdir(parents=True, exist_ok=True)
    (stubs / 'common' / 'foc_utils.h').write_text('#pragma once\n', encoding='utf-8')
    body = function_body(code((src / 'HapticProfileManager.cpp').read_text(encoding='utf-8', errors='replace')),
                         r'void\s+HapticProfile::keyActionFromJSON\s*\([^)]*\)\s*\{')
    if not body:
        print('FAIL FW-BUG-040: keyActionFromJSON not found in HapticProfileManager.cpp')
        return 1
    (stubs / 'key_action_body.inc').write_text(body + '\n', encoding='utf-8', newline='\n')
    test = out_dir / 'keyaction_tests.cpp'
    test.write_text(TEST, encoding='utf-8', newline='\n')
    cl, env = media_tests.msvc_env()
    exe = out_dir / 'keyaction_tests.exe'
    result = subprocess.run([
        str(cl), '/nologo', '/EHsc', '/std:c++14', '/W4', '/WX', '/O2', '/D_CRT_SECURE_NO_WARNINGS',
        '/wd5208', '/wd4244',  # firmware typedef'd structs with a String member; min(int)->uint8_t as on the knob
        f'/I{stubs}', f'/I{src}', f'/external:I{media_tests.arduinojson}', '/external:W0',
        str(test), f'/Fo{out_dir}\\', f'/Fe{exe}',
    ], cwd=out_dir, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        print((result.stdout + result.stderr)[-6000:])
        print('FAIL keyaction_tests.cpp: MSVC /W4 /WX build')
        return 1
    return subprocess.run([str(exe)]).returncode


if __name__ == '__main__':
    raise SystemExit(main())
