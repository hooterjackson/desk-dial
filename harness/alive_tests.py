"""1.0.0-cc5.4 "Warm · alive" LED engine checks (ALIVE.md section 11). Python stdlib + MSVC only;
no device, no USB.

1. Runs cpp11_gate.py: every shared unit (cc_alive.cpp included) must compile in the device's
   gnu++11, and the firmware source rules must hold. Pins the hmi_thread.cpp wiring of the
   local-input sampler CCAliveKnob (6.2, [Q1]) that the runner's knob checks model, the [M29]
   handover, the 10.1 cadence, the latched fields, and the kh / hid input wiring (PRESENTATION_V5
   11.2, 11.4) of hmi_thread.cpp and com_thread.cpp; the 12.3 diag wiring (every
   nanod_cc5_tooling.LCD_DIAG_FIELDS key in the {"diag":"?"} reply, lcdDma / artAsync as booleans)
   and the 8.10 native button edges (HMI -> the LCD's offline screen). [user 2026-09-26] Pins the
   section 9 dither default (off, ALIVE.md 12.7) in the firmware and the Python twin.
2. Regenerates alive_sequences.json (the 11.3 twin replay) from the companion's Python engine
   (tests/tools/make_alive_sequences.py, control_center/alive_lights.py), as light_tests.py
   regenerates light_pixels.json.
3. Compiles alive_tests.cpp with the unchanged firmware units cc_alive.cpp, cc_lights.cpp and
   cc_frame_parse.cpp (MSVC /W4 /WX, ArduinoJson as a system include, exactly as light_tests.py).
4. Runs it: the direct checks (output stage, sat, JS md/cd/round, time of day, effect queue,
   sleep timing, the revision 2 targets, local cursor, events, the [r2] moments / reduced motion /
   hold / tuning, song hand, the local-input sampler with the [Q1] push detector, per-frame cost),
   then
   - the design oracle, tests/fixtures/alive_oracle.json in the companion (tests/js/alive_oracle.cjs;
     skipped with a message while it is absent),
   - [r2] the second design oracle on the r2.1 Browse and Snap draw() (ALIVE.md 11.2, gate A2),
     tests/fixtures/alive_oracle_bs.json (tests/js/alive_oracle_bs.cjs), and
   - the twin sequences: every frame through the firmware's cc_parse_frame, every case through
     one CCAlive; e within 2e-3, output bytes (dither off) within 1, asleep / cursor / flash /
     effect queue / animating exactly. The format is in alive_tests.cpp.
   [user 2026-09-26] Dither off (the default) applies the F-T floor: both oracles' expect.bytes and
   the sequences' bytes include it; the runner checks the knob's output stage against them (within
   1, the floor decision / dominant channel exactly) and the F-T masks against Python's.

Writes alive_sequences.json and build/alive-tests/*. Exit status is non-zero on any failure.
`python alive_tests.py --cases` also prints one line per design-oracle case and per sequence.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import time

root = Path(__file__).resolve().parent
firmware = root.parent / 'firmware'
companion = root.parent / 'app'
arduinojson = firmware / '.pio' / 'libdeps' / 'nanofoc_d' / 'ArduinoJson' / 'src'
out_dir = root / 'build' / 'alive-tests'
oracle_path = companion / 'tests' / 'fixtures' / 'alive_oracle.json'
bs_oracle_path = companion / 'tests' / 'fixtures' / 'alive_oracle_bs.json'
sequences_path = root / 'alive_sequences.json'

sys.path.insert(0, str(companion / 'tests' / 'tools'))
sys.path.insert(0, str(companion))
import make_alive_sequences  # noqa: E402  (companion Python engine; read-only)


def msvc_env():
    """The MSVC 2022 Build Tools environment light_tests.py uses."""
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


def code(text: str) -> str:
    """C/C++ source without comments (block and line), so a pin never matches a comment."""
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    return re.sub(r'//[^\n]*', '', text)


def hmi_knob_wiring() -> int:
    """The hmi_thread.cpp wiring the runner's CCAliveKnob checks model (ALIVE.md 6.2): the sampler
    is reset on every claim/release transition, on every unclaimed pass and whenever a pass has no
    ready control (or the ready control changed during the FOC reads), and its events are the only
    source of detent/limit. [Q1] (12.5) it samples the push through the read-only FOC accessor;
    [M29] (8.1) the native handover lasts until the next claim (no 5 s return, no startReveal);
    10.1 the deadline cadence 16/17/17 ms with its resynchronisation; section 3 the latched
    reducedMotion and tuning fields reach the engine. Returns the number of pins checked."""
    hmi = code((firmware / 'src' / 'hmi_thread.cpp').read_text(encoding='utf-8', errors='replace'))
    compact = re.sub(r'\s+', ' ', hmi)
    pins = [
        (r'if \(active\) alive\.claim\(now\); else alive\.release\(now\); alive_knob\.reset\(\);',
         'claim/release transition resets the sampler'),
        (r'if \(!input\) \{ alive_knob\.reset\(\); return; \}', 'no ready control resets the sampler'),
        (r'if \(cc_input_id\(\) != input\) \{ alive_knob\.reset\(\); return; \}',
         'a control change during the reads resets the sampler'),
        (r'return; \} alive_knob\.reset\(\); if \(alive_native_input\(\)\)', 'an unclaimed pass resets the sampler'),
        # ALIVE.md 12.5 [Q1]: the push sample (atLimit && the attractor moved past the bound), read
        # through the one read-only FOC accessor, with the pass time.
        (r'const bool pushing = foc_thread\.pass_limit_push\(\);', 'the push is the read-only FOC accessor [Q1]'),
        (r'const CCAliveKnobEvents events = alive_knob\.sample\(now, input, pos, pushing, max\);',
         'the ready control is sampled through CCAliveKnob with the push [Q1]'),
        # [M29] native input hands the LEDs to the native path until the next claim.
        (r'if \(alive_native_input\(\)\) alive_mode = CC_LED_MODE_NATIVE; if \(alive_mode == CC_LED_MODE_NATIVE\) '
         r'nativeLeds\(\);', 'the native handover lasts until the next claim [M29]'),
        # 10.1 the deadline cadence (exactly 60.0 fps) and its resynchronisation.
        (r'constexpr uint8_t kAliveFrameSteps\[3\] = \{16, 17, 17\};', 'the 16/17/17 ms deadline cadence (10.1)'),
        (r'if \(late > static_cast<int32_t>\(kAliveFrameSteps\[alive_frame_step\]\)\) alive_next_show = '
         r'static_cast<uint32_t>\(currentMillis\);', 'more than one period late: resynchronise (10.1)'),
        (r'alive_next_show \+= kAliveFrameSteps\[alive_frame_step\]; alive_frame_step = '
         r'static_cast<uint8_t>\(\(alive_frame_step \+ 1\) % 3\);', 'the deadline advances 16, 17, 17 (10.1)'),
    ]
    for pattern, what in pins:
        if not re.search(pattern, compact):
            raise SystemExit(f'FAIL: hmi_thread.cpp: {what} (pattern {pattern!r} not found)')
    for call in ('alive.detent(', 'alive.limit(', 'cc_post_limit(', 'alive.setReducedMotion(', 'alive.setTuning('):
        if compact.count(call) != 1:
            raise SystemExit(f'FAIL: hmi_thread.cpp must call {call}...) exactly once')
    for gone, why in (('kNativeHoldMs', '[M29] withdrew the 5 s native-handover return'),
                      ('startReveal', '[M29] withdrew the native-handover reveal'),
                      ('pass_at_limit(', '[Q1] samples the push, not the atLimit edge'),
                      ('kAliveFrameMs', '10.1 replaced the flat 16 ms step')):
        if gone in compact:
            raise SystemExit(f'FAIL: hmi_thread.cpp still uses {gone} ({why})')
    if 'knob_id' in compact or 'knob_pos' in compact or 'knob_at_limit' in compact:
        raise SystemExit('FAIL: hmi_thread.cpp keeps a local-input binding outside CCAliveKnob')
    print('alive_tests: hmi_thread.cpp samples the knob with the [Q1] push detector; [M29] handover; '
          '16/17/17 cadence; latched reducedMotion / tuning', flush=True)
    return len(pins) + 5 + 4 + 1


def dither_default_wiring() -> int:
    """[user 2026-09-26] ALIVE.md 9 step 4 / 12.7: the knob's temporal dither is off unless a latched
    ledDither:true turns it on. Pinned where the default lives: CCAliveSpec::defaultDither, the HMI's
    unset-latch fallback, the two latch structs' defaults (an absent field stores false) and the
    Python twin's DEFAULT_DITHER. Returns the number of pins checked."""
    src = firmware / 'src'
    flat = lambda name: re.sub(r'\s+', ' ', code((src / name).read_text(encoding='utf-8', errors='replace')))  # noqa: E731
    pins = [
        ('cc_alive.h', r'constexpr bool defaultDither = false;', 'CCAliveSpec::defaultDither is false'),
        ('hmi_thread.cpp', r'alive\.output\(drive, alive_latch\.ledDitherPresent \? alive_latch\.ledDither : '
                           r'CCAliveSpec::defaultDither, cc_light_ring, cc_light_buttons\);',
         'an unset ledDither falls back to CCAliveSpec::defaultDither'),
        ('cc_presentation.h', r'bool ledDitherPresent = false; bool ledDither = false;', 'CCFrame: absent ledDither is false'),
        ('control_center.h', r'bool ledDitherPresent = false; bool ledDither = false;',
         'CCAliveLatch: unset ledDither is false'),
    ]
    for name, pattern, what in pins:
        if not re.search(pattern, flat(name)):
            raise SystemExit(f'FAIL: {name}: {what} (pattern {pattern!r} not found)')
    if make_alive_sequences.al.DEFAULT_DITHER is not False:
        raise SystemExit('FAIL: control_center/alive_lights.py DEFAULT_DITHER must be False (12.7)')
    print('alive_tests: section 9 dither default off (12.7) pinned in cc_alive.h, hmi_thread.cpp, '
          'cc_presentation.h, control_center.h and alive_lights.py', flush=True)
    return len(pins) + 1


def hmi_input_wiring() -> int:
    """PRESENTATION_V5 11.2 / 11.4 (VOC 2.5): the kh hold and the hid tag, as source pins. The HMI
    turns AceButton's long press on (no suppression, no repeat); [r3.1] each press sets its raw's delay from
    its physical slot (600 ms at slot 0, 1000 ms elsewhere) and the claimed branch queues a hold for every
    raw, and tags a key down that fired F24; the native branch
    ignores the long press entirely; the COM task sends kh / hid and routes an entering hold to the
    deferred slot. These pins hold the wiring only: the control_center.cpp behaviour (the deferred
    slot, ks in ready, the F24 icon gate) needs a host run of that unit (media_tests.py's wiring
    stubs), and the HMI side the hardware window (one kh per hold). Returns the number of pins
    checked."""
    hmi = re.sub(r'\s+', ' ', code((firmware / 'src' / 'hmi_thread.cpp').read_text(encoding='utf-8', errors='replace')))
    com = re.sub(r'\s+', ' ', code((firmware / 'src' / 'com_thread.cpp').read_text(encoding='utf-8', errors='replace')))
    pins = [
        (hmi, r'->setFeature\(ButtonConfig::kFeatureLongPress\);', 'long press on'),
        (hmi, r'->setLongPressDelay\(kHoldMs\);', 'long-press delay kHoldMs'),
        (hmi, r'constexpr uint16_t kHoldMs = 600;', 'hold_ms 600'),
        (hmi, r'constexpr uint16_t kHoldOtherMs = 1000;', '[r3.1] hold_ms 1000 off slot 0'),
        (hmi, r'if \(eventType == AceButton::kEventPressed\) \{ button->getButtonConfig\(\)->setLongPressDelay\('
              r'cc_physical_button\(index\) == 0 \? kHoldMs : kHoldOtherMs\);',
         '[r3.1] a claimed press sets its hold delay by physical slot'),
        (hmi, r'if \(eventType == AceButton::kEventLongPressed\) \{ KeyEvt evt = \{kKeyEvtHold,',
         '[r3.1] a claimed long press is a hold on every raw'),
        (hmi, r'KeyEvt evt = \{kKeyEvtHold, index, hmi_thread\.keyState, cc_input_id\(\)\};', 'the hold KeyEvt'),
        (hmi, r'if \(eventType == AceButton::kEventLongPressed\) return;', 'the native branch ignores the long press'),
        (hmi, r'static_cast<uint8_t>\(eventType \| \(hid \? kKeyEvtHid : 0\)\)', 'a key down that fired F24 is tagged'),
        (com, r'eventDoc\["kh"\] = keyNum;', 'COM sends kh'),
        (com, r'if \(hid\) eventDoc\["hid"\] = 1;', 'COM sends hid on kd'),
        (com, r'cc_hold_deferred\(keyNum\);', 'an entering hold goes to the deferred slot'),
        (com, r'if \(type == AceButton::kEventReleased\) cc_hold_key_up\(keyNum\);',
         'every key-up COM sees clears the deferred hold'),
    ]
    for text, pattern, what in pins:
        if not re.search(pattern, text):
            raise SystemExit(f'FAIL: kh / hid wiring: {what} (pattern {pattern!r} not found)')
    for forbidden in ('kFeatureSuppressAfterLongPress', 'kFeatureRepeatPress', 'kFeatureSuppressAll'):
        if forbidden in hmi:
            raise SystemExit(f'FAIL: hmi_thread.cpp sets {forbidden} (K1 11.2: kEventReleased must still follow)')
    print('alive_tests: kh / hid wiring (K1 11.2, 11.4) pinned in hmi_thread.cpp and com_thread.cpp', flush=True)
    return len(pins) + 3


def lcd_diag_fields() -> tuple:
    """nanod_cc5_tooling.LCD_DIAG_FIELDS (the hardware window's PRESENTATION_V5 12.3 list) followed by
    LCD_FIX_DIAG_FIELDS (the fix binaries' lcdMosiSig and build, 12.3; kept apart in the tooling
    because the companion's device.DIAG_LCD_FIELDS mirrors LCD_DIAG_FIELDS), read without importing
    the tooling."""
    import ast
    tree = ast.parse((root.parent / 'tools' / 'nanod_cc5_tooling.py').read_text(encoding='utf-8'))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if getattr(t, 'id', None) in ('LCD_DIAG_FIELDS', 'LCD_FIX_DIAG_FIELDS'):
                    found[t.id] = tuple(ast.literal_eval(node.value))
    if 'LCD_DIAG_FIELDS' not in found or 'LCD_FIX_DIAG_FIELDS' not in found:
        raise SystemExit('FAIL: nanod_cc5_tooling.py defines no LCD_DIAG_FIELDS / LCD_FIX_DIAG_FIELDS')
    return found['LCD_DIAG_FIELDS'] + found['LCD_FIX_DIAG_FIELDS']


def diag_and_native_wiring() -> int:
    """PRESENTATION_V5 12.3 (VOC-K1c) and 8.10, as source pins (media_tests.py runs both through
    cc_handle_command on the host). The {"diag":"?"} reply carries every LCD_DIAG_FIELDS key of the
    tooling: control_center.cpp writes enterMs* / hold* and calls cc_diag_lcd_pipeline() once, whose
    cc_diag.cpp body serialises one cc_lcd_perf_read() copy through cc_diag.h's
    cc_diag_lcd_perf_fields() (lcdDma / artAsync as booleans); the registration hook that nothing
    registered is gone; media_tests.cpp checks the same list. The HMI's unclaimed button branch
    reports every press/release edge (cc_native_button_edge) for the LCD's offline screen. Returns
    the number of pins checked."""
    src = firmware / 'src'
    read = lambda name: code((src / name).read_text(encoding='utf-8', errors='replace'))  # noqa: E731
    flat = lambda text: re.sub(r'\s+', ' ', text)  # noqa: E731
    fields = lcd_diag_fields()
    center, diag_h, diag_cpp, hmi = read('control_center.cpp'), read('cc_diag.h'), read('cc_diag.cpp'), read('hmi_thread.cpp')
    branch = re.search(r'if \(doc\["diag"\].*?cc_send_json\(out\); return true;', flat(center))
    if not branch:
        raise SystemExit('FAIL: control_center.cpp: no {"diag":"?"} branch')
    if branch.group(0).count('cc_diag_lcd_pipeline(d);') != 1 or flat(center).count('cc_diag_lcd_pipeline(') != 1:
        raise SystemExit('FAIL: control_center.cpp: the diag reply must call cc_diag_lcd_pipeline(d) exactly once')
    if not re.search(r'void cc_diag_lcd_pipeline\(JsonObject d\) \{ cc_diag_lcd_perf_fields\(d, cc_lcd_perf_read\(\)\); \}',
                     flat(diag_cpp)):
        raise SystemExit('FAIL: cc_diag.cpp: cc_diag_lcd_pipeline must serialise one cc_lcd_perf_read() copy')
    template = re.search(r'template <typename Perf> void cc_diag_lcd_perf_fields\(JsonObject d, const Perf& p\) \{(.*?)\}',
                         flat(diag_h))
    if not template:
        raise SystemExit('FAIL: cc_diag.h: no cc_diag_lcd_perf_fields template')
    lcd_keys = re.findall(r'd\["(\w+)"\] = ', template.group(1))
    com_keys = re.findall(r'd\["(\w+)"\] = ', branch.group(0))
    missing = [k for k in fields if k not in lcd_keys and k not in com_keys]
    if missing:
        raise SystemExit(f'FAIL: the diag reply lacks 12.3 field(s) {missing}')
    if sorted(lcd_keys) != sorted(set(lcd_keys)) or not set(lcd_keys) <= set(fields):
        raise SystemExit(f'FAIL: cc_diag_lcd_perf_fields writes a key twice or outside 12.3: {lcd_keys}')
    for key in ('lcdDma', 'artAsync'):
        if f'd["{key}"] = p.{key} != 0;' not in template.group(1):
            raise SystemExit(f'FAIL: cc_diag_lcd_perf_fields: {key} must be a JSON boolean (lcd_binary tests `is True`)')
    for name in [p.name for p in src.iterdir() if p.suffix in ('.cpp', '.h')]:
        text = read(name)
        for gone in ('cc_diag_set_lcd_reporter', 'CCDiagReporter', 'lcdReporter'):
            if gone in text:
                raise SystemExit(f'FAIL: src/{name} keeps {gone} (the 12.3 fields are wired directly)')
    runner = (root / 'media_tests.cpp').read_text(encoding='utf-8')
    listed = re.search(r'kDiagFields\[\] = \{(.*?)\};', runner, flags=re.S)
    if not listed or tuple(re.findall(r'"(\w+)"', listed.group(1))) != fields:
        raise SystemExit('FAIL: media_tests.cpp kDiagFields differs from nanod_cc5_tooling.LCD_DIAG_FIELDS')
    # 8.10 / AL 8.1: a native button edge is native input for the offline screen too.
    native = (r'if \(eventType == AceButton::kEventLongPressed\) return; if \(eventType == AceButton::kEventPressed \|\| '
              r'eventType == AceButton::kEventReleased\) \{ native_button = true; cc_native_button_edge\(\); \}')
    if not re.search(native, flat(hmi)) or flat(hmi).count('cc_native_button_edge(') != 1:
        raise SystemExit('FAIL: hmi_thread.cpp: the unclaimed branch must report each press/release edge once '
                         '(cc_native_button_edge)')
    lcd = read('lcd_thread.cpp')
    if 'cc_native_button_seq()' in lcd:
        print('alive_tests: lcd_thread.cpp reads cc_native_button_seq() (8.10 button edges on the offline screen)')
    else:
        print('alive_tests: NOTE lcd_thread.cpp does not read cc_native_button_seq() yet: the offline sub-line swaps '
              'on a knob turn only (8.10 button edges; LCD package handoff)', flush=True)
    print(f'alive_tests: diag carries all {len(fields)} 12.3 fields; native button edges reach the LCD accessor',
          flush=True)
    return 10


def marker_rest_off() -> int:
    """[user 2026-10-03] FW-BUG-026: the r3 Windows marker ring draws only the white marker +-1; the rest of the
    arc is off (no sub-floor dim segments, like the Lights arcs and the queue ring; ALIVE.md 15.7). Pins that
    neither draw_marker (cc_alive.cpp) nor the twin's _draw_marker puts class M, that CC_ALIVE_CLASS_M stays in
    the enum, and the twin's targets for the r3-refused-marker frames; byte parity of the two engines is the
    sequences' (step 4). Returns the number of checks."""
    al = make_alive_sequences.al
    cpp = (firmware / 'src' / 'cc_alive.cpp').read_text(encoding='utf-8', errors='replace').replace('\r\n', '\n')
    body = re.search(r'int draw_marker\(.*?\n}\n', cpp, re.S)
    if not body or 'CC_ALIVE_CLASS_M' in body.group(0) or 'CC_ALIVE_CLASS_3, markerRgb' not in body.group(0):
        raise SystemExit('FAIL: cc_alive.cpp draw_marker must draw the marker +-1 only (no class M rest)')
    header = (firmware / 'src' / 'cc_alive.h').read_text(encoding='utf-8', errors='replace')
    if not re.search(r'\bCC_ALIVE_CLASS_M,', header):
        raise SystemExit('FAIL: cc_alive.h must keep CC_ALIVE_CLASS_M in the enum (append-only)')
    import ast
    import inspect
    import textwrap
    fn = ast.parse(textwrap.dedent(inspect.getsource(al._draw_marker))).body[0]
    names = {n.id for stmt in fn.body[1:] for n in ast.walk(stmt) if isinstance(n, ast.Name)}   # body[0]: docstring
    if 'CLASS_M' in names or 'MARKER_RGB' not in names:
        raise SystemExit('FAIL: alive_lights._draw_marker must draw the marker +-1 only (no class M rest)')
    arc = [(38 + k) % 60 for k in range(45)]
    checks = 3
    for count, index in ((8, 0), (8, 3), (8, 7), (1, 0), (24, 11)):
        span = max(1, count - 1)
        pos = (2 * index * 44 + span) // (2 * span)
        for asleep in (False, True):
            t = al.alive_targets(make_alive_sequences.windows_r3(count, index).frame, state_asleep=asleep)
            for k, seg in enumerate(arc):
                cell = t.ring[seg]
                if (cell is None) != (abs(k - pos) > 1) or (cell is not None and cell.cls != 3):
                    raise SystemExit(f'FAIL: marker ring count {count} index {index} asleep {asleep}: arc {k} '
                                     f'is {cell!r} (marker +-1 class 3 only)')
            checks += 1
    print('alive_tests: [user 2026-10-03] the marker ring rest is off (draw_marker, _draw_marker, 10 twin frames)',
          flush=True)
    return checks


def compile_runner() -> Path:
    cl, env = msvc_env()
    exe = out_dir / 'alive_tests.exe'
    subprocess.run([
        str(cl), '/nologo', '/EHsc', '/std:c++14', '/W4', '/WX', '/O2', '/D_CRT_SECURE_NO_WARNINGS',
        f'/I{firmware / "src"}',
        # ArduinoJson is third-party: its own warnings are not ours (the gnu++11 gate parses it too).
        f'/external:I{arduinojson}', '/external:W0',
        str(root / 'alive_tests.cpp'), str(firmware / 'src' / 'cc_alive.cpp'),
        str(firmware / 'src' / 'cc_lights.cpp'), str(firmware / 'src' / 'cc_frame_parse.cpp'),
        f'/Fo{out_dir}\\', f'/Fe{exe}',
    ], cwd=out_dir, env=env, check=True)
    return exe


def main() -> int:
    started = time.time()
    # 1. Fail fast if a shared unit is not valid gnu++11.
    subprocess.run([sys.executable, str(root / 'cpp11_gate.py')], check=True)
    print(f'alive_tests: hmi_thread.cpp local-input wiring: {hmi_knob_wiring()} pin(s)', flush=True)
    print(f'alive_tests: section 9 dither default: {dither_default_wiring()} pin(s)', flush=True)
    print(f'alive_tests: kh / hid input wiring: {hmi_input_wiring()} pin(s)', flush=True)
    print(f'alive_tests: 12.3 diag / 8.10 native button wiring: {diag_and_native_wiring()} pin(s)', flush=True)
    print(f'alive_tests: marker ring rest off (FW-BUG-026): {marker_rest_off()} check(s)', flush=True)
    # 2. Twin sequences from the Python engine.
    data = make_alive_sequences.build()
    text = make_alive_sequences.dumps(data)
    previous = sequences_path.read_text(encoding='utf-8') if sequences_path.is_file() else ''
    sequences_path.write_text(text, encoding='utf-8', newline='\n')
    print(f"alive_tests: twin sequences {'unchanged' if previous == text else 'regenerated'}: "
          f"{make_alive_sequences.summary(data)} ({len(text.encode('utf-8'))} bytes)", flush=True)
    # 3. Build the runner.
    out_dir.mkdir(parents=True, exist_ok=True)
    exe = compile_runner()
    # 4. Direct checks, the oracle when present, the sequences.
    for label, path in (('design oracle', oracle_path), ('BS oracle', bs_oracle_path)):
        state = f'{path.stat().st_size} bytes' if path.is_file() else 'absent, will be skipped'
        print(f'alive_tests: {label}: {path} ({state})', flush=True)
    # --cases: one line per oracle case and per sequence (passed through to the runner).
    flags = [arg for arg in sys.argv[1:] if arg == '--cases']
    result = subprocess.run([str(exe), str(oracle_path), str(sequences_path), str(bs_oracle_path), *flags])
    if result.returncode != 0:
        print(f'FAIL: alive_tests.exe exited {result.returncode} [{time.time() - started:.1f} s]')
        return 1
    print(f'PASS: alive engine checks [{time.time() - started:.1f} s]')
    return 0


if __name__ == '__main__':
    sys.exit(main())
