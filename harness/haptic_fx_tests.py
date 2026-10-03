"""r4 FEEL + SOUND checks (1.0.0-cc5.7, plan F2 / F3; firmware HAPTICS.md). Python stdlib + MSVC only; no device, no USB.

1. Runs cpp11_gate.py: cc_haptic_fx.h and audio/cc_sound.h compile in the device's gnu++11 (their generated units),
   with every other shared unit.
2. Compiles haptic_fx_tests.cpp against the unchanged firmware headers src/cc_haptic_fx.h and src/audio/cc_sound.h
   and the frame parser src/cc_frame_parse.cpp (MSVC /W4 /WX) and runs it: the token table and its reduced
   fallbacks, the laws, the wall, damping, feel.fade, hold.tension, the effect player, the knob model (no detent
   created or lost by an effect at rest or during a turn), the fold-back, the self-spin trip against the flipped-
   torque model and ordinary hands, the uint16 range fix, the cross-task words, the click bank / ring / voice and
   the underrun rule, and the `haptic` frame parity cases written below.
3. The same parity cases through control_center/device.py haptic_parse() (the host's reading of the firmware rule).
4. Pins the firmware wiring the runner's model rests on, as source text (comments ignored): the uint16 fix and the
   explicit D rule, the supply from the PD contract before driver.init(), the token dispatch and the freeze, the wall
   hits once per refused detent, the old sound triggers gone and AUDIO_EN on, HID report 4 appended and F24
   unchanged (exactly one key code, one timed release per press), consumer usages never waking the PC, the key
   actions suppressed offline, the capabilities (knobVolume included), the trip wiring, hold.tension posts,
   recalibration routing, the rest gate's busy terms and one-detent wake distance in both loops, the fade on waking,
   the wall thud's legacy / reduced gate and the fold-back's applied-volts input (each pin is checked to fail on a
   reverted line).

Exit status is non-zero on any failure.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

root = Path(__file__).resolve().parent
firmware = root.parent / 'firmware'
src = firmware / 'src'
companion = root.parent / 'app'
arduinojson = firmware / '.pio' / 'libdeps' / 'nanofoc_d' / 'ArduinoJson' / 'src'
out_dir = root / 'build' / 'haptic-fx-tests'
MSVC = Path('C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Tools/MSVC/14.44.35207')
WINDOWS_SDK = Path('C:/Program Files (x86)/Windows Kits/10')

BASE = {"mode": "VOLUME", "target": "", "value": "", "detail": "", "status": "",
        "buttons": [{"label": "", "enabled": False, "icon": ""}] * 4,
        "ring": {"style": "off", "value": 0, "index": 0, "count": 0}}
FX = {"confirm.tick": 1, "confirm.thump": 2, "nudge.left": 3, "nudge.right": 4, "refuse.buzz": 5, "error.buzz": 6,
      "confirm.off": 7}


def cases():
    """(name, haptic value or None when absent, accept, fx, seq)."""
    out = [("absent", None, True, 0, 0)]
    for token, fx in FX.items():
        out.append((f"token {token}", {"token": token, "seq": 7}, True, fx, 7))
    out += [
        ("seq max", {"token": "confirm.tick", "seq": 0x7FFFFFFF}, True, 1, 0x7FFFFFFF),
        ("extra key ignored", {"token": "nudge.left", "seq": 3, "side": 1}, True, 3, 3),
        ("seq 0", {"token": "confirm.tick", "seq": 0}, False, 0, 0),
        ("seq too big", {"token": "confirm.tick", "seq": 0x80000000}, False, 0, 0),
        ("seq float", {"token": "confirm.tick", "seq": 1.0}, False, 0, 0),
        ("seq bool", {"token": "confirm.tick", "seq": True}, False, 0, 0),
        ("seq missing", {"token": "confirm.tick"}, False, 0, 0),
        ("token unknown", {"token": "confirm.boom", "seq": 1}, False, 0, 0),
        ("token empty", {"token": "", "seq": 1}, False, 0, 0),
        ("token wall", {"token": "wall.bounce", "seq": 1}, False, 0, 0),
        ("token feel", {"token": "detent.list", "seq": 1}, False, 0, 0),
        ("token number", {"token": 1, "seq": 1}, False, 0, 0),
        ("token missing", {"seq": 1}, False, 0, 0),
        ("not an object", "confirm.tick", False, 0, 0),
        ("null", "__null__", False, 0, 0),
    ]
    return out


def write_cases(path: Path) -> list:
    table = []
    for name, value, accept, fx, seq in cases():
        frame = dict(BASE)
        if value == "__null__":
            frame["haptic"] = None
        elif value is not None:
            frame["haptic"] = value
        table.append({"name": name, "frame": frame, "accept": accept, "fx": fx, "seq": seq})
    path.write_text(json.dumps(table), encoding='utf-8')
    return table


def host_parity(table) -> int:
    sys.path.insert(0, str(companion))
    from control_center import device   # noqa: E402
    for case in table:
        value = case["frame"].get("haptic", "__absent__")
        if value == "__absent__":
            continue
        stored, ok = device.haptic_parse(value)
        if ok != case["accept"]:
            raise SystemExit(f'FAIL: device.haptic_parse {case["name"]}: ok {ok}, firmware rule {case["accept"]}')
        if ok and (stored["fx"] != case["fx"] or stored["seq"] != case["seq"]):
            raise SystemExit(f'FAIL: device.haptic_parse {case["name"]}: {stored}')
    return len(table)


def compile_runner() -> Path:
    sdk_include = sorted((WINDOWS_SDK / 'Include').iterdir(), key=lambda p: p.name)[-1]
    sdk_lib = WINDOWS_SDK / 'Lib' / sdk_include.name
    env = {key.upper(): value for key, value in os.environ.items()}
    env['INCLUDE'] = ';'.join(str(path) for path in (
        MSVC / 'include', sdk_include / 'ucrt', sdk_include / 'shared', sdk_include / 'um'))
    env['LIB'] = ';'.join(str(path) for path in (MSVC / 'lib/x64', sdk_lib / 'ucrt/x64', sdk_lib / 'um/x64'))
    exe = out_dir / 'haptic_fx_tests.exe'
    subprocess.run([
        str(MSVC / 'bin/Hostx64/x64/cl.exe'), '/nologo', '/EHsc', '/std:c++14', '/W4', '/WX', '/O2',
        '/D_CRT_SECURE_NO_WARNINGS', f'/I{src}', f'/external:I{arduinojson}', '/external:W0',
        str(root / 'haptic_fx_tests.cpp'), str(src / 'cc_frame_parse.cpp'), f'/Fo{out_dir}\\', f'/Fe{exe}',
    ], cwd=out_dir, env=env, check=True)
    return exe


def code(text: str) -> str:
    """C/C++ source without comments (block and line), whitespace collapsed."""
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    text = re.sub(r'//[^\n]*', '', text)
    return re.sub(r'\s+', ' ', text)


def read(name: str) -> str:
    return code((src / name).read_text(encoding='utf-8', errors='replace'))


def pins() -> int:
    count = 0

    def need(text, pattern, what):
        nonlocal count
        if not re.search(pattern, text):
            raise SystemExit(f'FAIL: {what} (pattern {pattern!r} not found)')
        count += 1

    def never(text, pattern, what):
        nonlocal count
        if re.search(pattern, text):
            raise SystemExit(f'FAIL: {what} (pattern {pattern!r} found)')
        count += 1

    haptic, foc, hmi = read('haptic.cpp'), read('foc_thread.cpp'), read('hmi_thread.cpp')
    center, com, audio = read('control_center.cpp'), read('com_thread.cpp'), read('audio/audio.cpp')
    commander, diag = read('HapticCommander.cpp'), read('cc_diag.cpp')
    ini = (firmware / 'platformio.ini').read_text(encoding='utf-8')
    # The uint16 range fix and the explicit D rule.
    never(haptic, r'uint16_t total_positions', 'haptic.cpp: the position count is 32-bit')
    need(haptic, r'const uint32_t total_positions = cc_positions\(haptic_state\.detent_profile\.start_pos, '
                 r'haptic_state\.detent_profile\.end_pos\);', 'haptic.cpp: cc_positions() counts the range')
    need(haptic, r'haptic_pid->D = 0\.0f;', 'haptic.cpp: the D term is explicitly never used')
    never(haptic, r'effective_(?:start|end)_pos \*=', 'haptic.cpp: VERNIER bounds scale without a uint16 wrap')
    need(haptic, r'cc_scaled_position\(haptic_state\.detent_profile\.start_pos, scale\), '
                 r'cc_scaled_position\(haptic_state\.detent_profile\.end_pos, scale\), haptic_state\.last_limit_position\)',
         'haptic.cpp: bounds_handler() restores inward with unwrapped bounds')
    # Token dispatch, freeze, walls.
    need(haptic, r'if \(!frozen\) find_detent\(\);', 'haptic.cpp: the effect freeze gates the detent count')
    need(haptic, r'if \(feel_ != CC_FEEL_LEGACY\) token_target\(\); else haptic_target\(\);',
         'haptic.cpp: token mode only with a feel; the legacy loop otherwise')
    need(haptic, r'void HapticInterface::wall_refused\(int8_t dir\) \{ if \(refusedSet_ && refusedAttract_ == '
                 r'haptic_state\.attract_angle\) return;.*?cc_wall_hit\(dir\);',
         'haptic.cpp: cc_wall_hit() once per refused detent')
    # FW-BUG-036: the refused detent wakes a sleeping rest gate, so the wall's force comes with its thud.
    need(haptic, r'void HapticInterface::wall_refused\(int8_t dir\) \{ if \(refusedSet_ && refusedAttract_ == '
                 r'haptic_state\.attract_angle\) return; refusedSet_ = true; refusedAttract_ = haptic_state\.attract_angle; '
                 r'rest_\.refused\(\); cc_wall_hit\(dir\);',
         'haptic.cpp: wall_refused() wakes the rest gate (rest_.refused()) with the wall hit and its thud')
    need(read('cc_haptic_fx.h'), r'void refused\(\) \{ refused_ = true; \} .*?bool step\(uint32_t nowUs, float angle, '
                                 r'float error, float velocity, bool busy, float wakeRad = CC_REST_WAKE_RAD\) \{ '
                                 r'if \(refused_\) \{ busy = true; refused_ = false; \}',
         'cc_haptic_fx.h: CCRestGate counts a refused detent as busy on its next step')
    if len(re.findall(r'wall_refused\((?:1|-1)\);', haptic)) != 4:
        raise SystemExit('FAIL: haptic.cpp: every LIMIT_POS / LIMIT_NEG branch reports its refused detent')
    count += 1
    for name in [p for p in src.rglob('*') if p.suffix in ('.cpp', '.h') and p.name not in ('haptic.cpp', 'cc_wall.h')]:
        if 'cc_wall_hit(' in code(name.read_text(encoding='utf-8', errors='replace')):
            raise SystemExit(f'FAIL: {name.name} calls cc_wall_hit(): only the FOC haptic loop reports walls')
    count += 1
    need(haptic, r'float out = default_pid\(error\) \+ fx_\.volts\(now\) / CC_HAPTIC_PHASE_OHMS;',
         'haptic.cpp: the legacy loop adds only an effect to the PID output')
    # Rest sleep (2026-09-30): both loops zero their output through the rest gate while the knob sits still.
    count += 1
    if len(re.findall(r'if \(rest_\.step\(now, motor->shaft_angle, haptic_state\.last_attract_angle - motor->shaft_angle,', haptic)) != 2:
        raise SystemExit('FAIL: haptic.cpp: token_target() and haptic_target() both gate their output through rest_.step()')
    # HN-TST-001: what the rest gate counts as busy and how far a sleeping knob must turn to wake (one detent, 2.5 to
    # 5.4 degrees, end stops included), in both loops; the legacy loop has no hold.tension term.
    need(haptic, r'const bool busy = fx_\.busy\(now\) \|\| haptic_state\.wasAtLimit \|\| frozen_; if \(rest_\.step\(now, '
                 r'motor->shaft_angle, haptic_state\.last_attract_angle - motor->shaft_angle, motor->shaft_velocity, busy, '
                 r'cc_rest_wake_rad\(haptic_state\.detent_width\)\)\) \{ out = 0\.0f; haptic_pid->reset\(\); \}',
         'haptic.cpp: haptic_target() rests unless an effect, a bound exit or a freeze is busy; wakes at one detent')
    need(haptic, r'const bool busy = fx_\.busy\(now\) \|\| kd > fp_\.kd \|\| haptic_state\.wasAtLimit \|\| frozen_;',
         'haptic.cpp: token_target() is busy with an effect, hold.tension, a bound exit or a freeze')
    need(haptic, r'if \(rest_\.step\(now, motor->shaft_angle, haptic_state\.last_attract_angle - motor->shaft_angle, velocity, '
                 r'busy, cc_rest_wake_rad\(w\)\)\)',
         'haptic.cpp: token_target() passes its busy terms and the one-detent wake distance to the rest gate')
    # The wake fade: the asleep state is read before the step, so the pass that wakes restarts feel.fade.
    need(haptic, r'const bool wasAsleep = rest_\.asleep\(\); if \(rest_\.step\([^;]*?\)\) \{[^{}]*\} '
                 r'else if \(wasAsleep\) \{ restart_fade\(CC_FEEL_FADE_MS\); \}',
         'haptic.cpp: waking from rest fades the spring and the wall back in (restart_fade(CC_FEEL_FADE_MS))')
    # The wall thud: once per refused detent, never in the legacy loop or under reduced haptics.
    need(haptic, r'cc_wall_hit\(dir\); #if CC_HAPTIC_FX if \(feel_ != CC_FEEL_LEGACY && !reduced_\) \{ const CCSoundCue '
                 r'wall = \{CC_SOUND_THUD, 50, 1, 0\}; cc_sound_post\(wall, sound_\); \} #endif \}',
         'haptic.cpp: wall_refused() thuds once per refused detent, not in legacy or reduced haptics')
    # The fold-back's input: the wall's volts under the folded cap, the same volts the spring applies.
    need(haptic, r'const float cap = CC_HAPTIC_CAP_VOLTS \* \(CC_HAPTIC_FOLDBACK \? fold_\.factor\(\) : 1\.0f\); '
                 r'wallVolts_ = cc_wall_volts\(cc_law_slope\(fp_\.law, fp_\.kp\), pen, w, cap\) \* fade_\.factor\(now\); '
                 r'spring = -static_cast<float>\(outward\) \* '
                 r'wallVolts_ / CC_HAPTIC_PHASE_OHMS;',
         'haptic.cpp: the wall volts (under the fold-back cap) are what the spring applies and the fold-back counts')
    # Supply from the PD contract, before the driver scales anything.
    # FW-BUG-022: the contract with its read status, position and NVM rewrite (fails safe high), before driver.init().
    need(foc, r'const bool pdRead = cc_boot_pd_contract\(pdPosition, pdMillivolts, pdRewritten\); .*?'
              r'supply_volts = CC_SUPPLY_FROM_PD \? cc_supply_volts\(pdRead, pdPosition, pdVolts, pdRewritten\) : 5\.0f; \} '
              r'driver\.voltage_power_supply = supply_volts; driver\.voltage_limit = 5\.0f; driver\.init\(\);',
         'foc_thread.cpp: voltage_power_supply from the PD contract before driver.init()')
    never(foc, r'cc_boot_pd_volts\(\)', 'foc_thread.cpp: the supply never comes from the lossy pdVolts word (FW-BUG-022)')
    need(foc, r'feel_diag\.supplyAssumed = supply_assumed;', 'foc_thread.cpp: diag reports an assumed supply (FW-BUG-022)')
    # Trip, effects, feel on requests.
    need(foc, r'if \(spin_trip\.latched\(\) && !sleep_foc\.motorOff\(\)\) \{ motor\.loopFOC\(\); motor\.move\(0\); \}',
         'foc_thread.cpp: a latched trip holds a zero output')
    need(foc, r'if \(keys & static_cast<uint8_t>\(~last_keys\)\) spin_trip\.clear\(\);', 'foc_thread.cpp: a key press clears the trip')
    need(foc, r'if \(claim\) spin_trip\.clear\(\);', 'foc_thread.cpp: a claim clears the trip')
    need(foc, r'haptic\.set_feel\(feel, control\.reducedHaptics, control\.sound, fade \? CC_FEEL_FADE_MS : 0\);',
         'foc_thread.cpp: each control sets its feel')
    need(foc, r'haptic\.reanchor\(\); haptic\.restart_fade\(CC_FEEL_WAKE_FADE_MS\);', 'foc_thread.cpp: detents fade in after a wake')
    # Sound: the old triggers are gone, audio is on.
    never(hmi, r'chime_wav|play_audio\(|key_audio_file', 'hmi_thread.cpp: no boot chime and no key clack')
    never(audio, r'Serial\.println|XT_I2S|play_haptic_audio', 'audio.cpp: no busy "x" line, no XT player, no detent sample')
    need(haptic, r'void HapticInterface::UserHapticEventCallback\(HapticEvt event, float currentAngle, uint16_t currentPos\)'
                 r'\{ \(void\)event; \(void\)currentAngle; \(void\)currentPos; \}',
         'haptic.cpp: the user callback plays nothing')
    for gone in ('WavData22m.cpp', 'WavData22s.cpp', 'WavData44s.cpp'):
        if (src / 'audio' / gone).exists():
            raise SystemExit(f'FAIL: src/audio/{gone} still exists (the WAV samples are gone)')
    count += 1
    if not re.search(r'^\s*-DAUDIO_EN=1\s*$', ini, re.M):
        raise SystemExit('FAIL: platformio.ini: -DAUDIO_EN=1 (plan F3) is not on')
    count += 1
    need(audio, r'cfg\.sample_rate = CC_SOUND_RATE;.*?cfg\.dma_buf_count = CC_SOUND_DMA_BUFFERS; cfg\.dma_buf_len = '
                r'CC_SOUND_DMA_FRAMES;.*?cfg\.tx_desc_auto_clear = true;', 'audio.cpp: 22.05 kHz, 6 x 64 frames, auto-clear')
    need(audio, r'i2s_write\(I2S_NUM_0, reinterpret_cast<const uint8_t\*>\(stereo_\) \+ pendingOffset_ \* 4u, '
                r'pendingFrames_ \* 4u, &written, 0\);', 'audio.cpp: non-blocking writes')
    need(audio, r'stereo_\[2 \* i\] = stereo_\[2 \* i \+ 1\] = mono\[i\];', 'audio.cpp: the same sample in both slots')
    # HID: report 4 appended, F24 unchanged, consumer never wakes, offline suppresses the profile's actions.
    need(hmi, r'TUD_HID_REPORT_DESC_KEYBOARD\( HID_REPORT_ID\(RID_KEYBOARD\) \), TUD_HID_REPORT_DESC_MOUSE ?\( '
              r'HID_REPORT_ID\(RID_MOUSE\) \), TUD_HID_REPORT_DESC_GAMEPAD\( HID_REPORT_ID\(RID_GAMEPAD\) \), '
              r'#if CC_OFFLINE_VOLUME TUD_HID_REPORT_DESC_CONSUMER\( HID_REPORT_ID\(RID_CONSUMER\) \) #endif',
         'hmi_thread.cpp: the Consumer collection is appended as report ID 4')
    need(hmi, r'RID_KEYBOARD = 1, RID_MOUSE = 2, RID_GAMEPAD = 3, RID_CONSUMER = 4,', 'hmi_thread.cpp: report IDs 1..3 unchanged')
    if hmi.count('current_key_codes[0] = 0x73;') != 1 or hmi.count('cc_f24_release_at = millis() + 60;') != 1:
        raise SystemExit('FAIL: hmi_thread.cpp: exactly one F24 key code and one timed release per press')
    count += 1
    if hmi.count('remoteWakeup(') != 1:
        raise SystemExit('FAIL: hmi_thread.cpp: only the keyboard / mouse / gamepad path may wake the PC')
    consumer = re.search(r'void HmiThread::handleConsumer\(\) \{(.*?)\n?void HmiThread::handleMidi', hmi)
    if not consumer or 'remoteWakeup' in consumer.group(1) or 'if (TinyUSBDevice.suspended()) { offline_steps_seen = steps;' not in consumer.group(1):
        raise SystemExit('FAIL: hmi_thread.cpp: consumer usages are dropped, never sent, while suspended')
    count += 1
    need(hmi, r'if \(!claimed && !offline_now\) updateValue\(\);', 'hmi_thread.cpp: the knob value is suppressed offline')
    if len(re.findall(r'if \(!offline_now\) \{ for \(int i=0; i<hmi_thread\.hmi_config\.keys\[index\]\.num_pressed_actions;', hmi)) != 2:
        raise SystemExit('FAIL: hmi_thread.cpp: the key actions are suppressed offline (press and release)')
    count += 1
    need(hmi, r'static_cast<uint32_t>\(now - cdc_closed_at\) >= kOfflineAfterMs', 'hmi_thread.cpp: offline after 2 s closed')
    need(hmi, r'cc_hold_tension_post\(static_cast<uint32_t>\(millis\(\)\), ms\);', 'hmi_thread.cpp: hold.tension starts on the press')
    if hmi.count('cc_hold_tension_post(0, 0);') != 2:
        raise SystemExit('FAIL: hmi_thread.cpp: hold.tension ends on the release and on the landing')
    count += 1
    # Capabilities and the claim's fields.
    need(center, r'c\["feel"\] = 1; c\["hapticFx"\] = 1; c\["knobSound"\] = 1; c\["offlineVolume"\] = 1; '
                 r'c\["recalibration"\] = 1;', 'control_center.cpp: the r4 capabilities')
    need(center, r'c\["knobVolume"\] = 1;', 'control_center.cpp: the knobVolume capability (soundVolume 0..100)')
    need(center, r'if \(claim\) hapticSeen = incoming\.hapticSeq;', 'control_center.cpp: a claim seeds the haptic seq')
    if center.count('cc_fx_post(incoming.hapticFx);') != 2:
        raise SystemExit('FAIL: control_center.cpp: a control re-entry and a frame each play a new haptic seq')
    count += 1
    # Recalibration routing.
    never(commander, r'initFOC|motor->disable|motor->enable', 'HapticCommander.cpp: no bare recalibration on the register')
    need(commander, r'if \(value==1\) cc_cal_request\(false\);', 'HapticCommander.cpp: the register asks the FOC task')
    need(com, r'cc_cal_request\(acceptDirection\);', 'com_thread.cpp: {"recalibrate":...} asks the FOC task')
    need(com, r'if \(cc_cal_take_save\(cal\)\) \{ cc_wdt_unwatch\(CC_LIVE_COM\); '
              r'const bool stored = DeviceSettings::getInstance\(\)\.storeCalibration\(cal\); cc_wdt_watch\(CC_LIVE_COM\); '
              r'cc_cal_saved\(stored\); \}', 'com_thread.cpp: the save handshake (FW-BUG-028: the store result reported)')
    need(diag, r'd\["supplyVolts"\] = .*?d\["audioUnderruns"\] = sound\.underruns;', 'cc_diag.cpp: the r4 diag fields')
    return count


def test_register_writes_are_allow_listed() -> int:
    """FW-BUG-003: commsToRegister runs only for haptic_register_write_allowed() registers (0x50, 0x81), the old
    deny list is gone, and after an allowed write the haptic loop's modes and the cap are put back."""
    commander = read('HapticCommander.cpp')
    header = code((src / 'HapticCommander.h').read_text(encoding='utf-8', errors='replace'))
    fx = code((src / 'cc_haptic_fx.h').read_text(encoding='utf-8', errors='replace'))
    if 'haptic_register_refused' in commander + header:
        raise SystemExit('FAIL: HapticCommander: the deny list (haptic_register_refused) is gone (FW-BUG-003)')
    if not re.search(r'constexpr bool haptic_register_write_allowed\(uint8_t reg\) \{ return reg == CC_REG_VOLTAGE_LIMIT '
                     r'\|\| reg == CC_REG_RECALIBRATE; \}', fx) or 'CC_REG_VOLTAGE_LIMIT = 0x50;' not in fx \
            or 'CC_REG_RECALIBRATE = 0x81;' not in fx:
        raise SystemExit('FAIL: cc_haptic_fx.h: haptic_register_write_allowed() allows exactly 0x50 and 0x81')
    if 'CC_REG_VOLTAGE_LIMIT == SimpleFOCRegister::REG_VOLTAGE_LIMIT' not in header:
        raise SystemExit('FAIL: HapticCommander.h: the allow-list numbers are tied to SimpleFOC register numbers')
    if commander.count('commsToRegister(') != 1:
        raise SystemExit('FAIL: HapticCommander.cpp: exactly one commsToRegister() call')
    block = re.search(r'else if \(haptic_register_write_allowed\(reg\)\) \{(.*?)\}', commander)
    if not block or 'SimpleFOCRegisters::regs->commsToRegister(*this, reg, motor);' not in block.group(1):
        raise SystemExit('FAIL: HapticCommander.cpp: commsToRegister() only behind haptic_register_write_allowed()')
    for line in ('motor->voltage_limit = haptic_voltage_in_cap(motor->voltage_limit);',
                 'motor->voltage_sensor_align = haptic_voltage_in_cap(motor->voltage_sensor_align);',
                 'motor->controller = MotionControlType::torque;',
                 'motor->torque_controller = TorqueControlType::voltage;',
                 'motor->foc_modulation = FOCModulationType::SpaceVectorPWM;',
                 'motor->phase_resistance = CC_HAPTIC_PHASE_OHMS;'):
        if line not in block.group(1):
            raise SystemExit(f'FAIL: HapticCommander.cpp: after an allowed write: {line}')
    return 4


def test_profile_manager_uses_the_slot_rules() -> int:
    """FW-SEC-001: HapticProfileManager looks names up through haptic_profile_find() (never "" -> a free slot),
    add("") is refused, remove() of the current profile moves current to the next named profile, a rename keeps a
    usable name, and a reload never keeps a freed slot as current (the runner models the same rules)."""
    pm = read('HapticProfileManager.cpp')
    rules = [
        (r'HapticProfile\* HapticProfileManager::get\(String name\) \{ const int i = haptic_profile_find\(profiles, '
         r'MAX_PROFILES, name\); return i>=0 \? &profiles\[i\] : nullptr; \}', 'get() through haptic_profile_find()'),
        (r'HapticProfile\* HapticProfileManager::add\(String name\) \{ if \(name\.length\(\)==0\) return nullptr;',
         'add("") refused'),
        (r'void HapticProfileManager::remove\(String name\) \{ const int i = haptic_profile_find\(profiles, MAX_PROFILES, '
         r'name\); if \(i<0\) return; profiles\[i\]\.profile_name = ""; if \(current_profile==&profiles\[i\]\) \{ const '
         r'int next = haptic_profile_next_named\(profiles, MAX_PROFILES, i\); if \(next>=0\) current_profile = '
         r'&profiles\[next\]; \} \}', 'remove() of the current profile moves to the next named one'),
        (r'HapticProfile\* HapticProfileManager::setCurrentProfile\(String name\)\{ HapticProfile\* profile = get\(name\);',
         'setCurrentProfile() through get()'),
        (r'if \(current_profile==nullptr \|\| current_profile->profile_name==""\) current_profile = profile;',
         'fromSPIFFS() never keeps a freed slot current'),
        (r'if \(obj\["name"\]\.is<String>\(\) && haptic_profile_name_ok\(obj\["name"\]\.as<String>\(\)\)\) \{ '
         r'profile_name = obj\["name"\]\.as<String>\(\); dirty = true; \}', 'a rename keeps a usable name'),
    ]
    for pattern, what in rules:
        if not re.search(pattern, pm):
            raise SystemExit(f'FAIL: HapticProfileManager.cpp: {what} (FW-SEC-001)')
    if 'update_field(obj, name, profile_name)' in pm or re.search(r'profiles\[i\]\.profile_name==name', pm):
        raise SystemExit('FAIL: HapticProfileManager.cpp: a raw name lookup or rename is back (FW-SEC-001)')
    return len(rules) + 1


def test_profile_change_action_round_trips() -> int:
    """FW-BUG-011: a KA_PROFILE_CHANGE key action is written with the type keyActionFromJSON() reads back, so a
    saved 'change to profile X' binding survives a reboot; the legacy "profiles" spelling still parses."""
    pm = read('HapticProfileManager.cpp')
    written = re.search(r'case keyActionType::KA_PROFILE_CHANGE: obj\["type"\] = "([a-z_]+)"; obj\["name"\] = '
                        r'action\.profile; break;', pm)
    parsed = re.search(r'else if \(\(type=="([a-z_]+)" \|\| type=="([a-z_]+)"\) && obj\["name"\]\.is<String>\(\)\) '
                       r'\{ action\.type = keyActionType::KA_PROFILE_CHANGE; action\.profile = obj\["name"\]\.as<String>\(\);', pm)
    if not written or not parsed:
        raise SystemExit('FAIL: HapticProfileManager.cpp: the KA_PROFILE_CHANGE write / read (FW-BUG-011)')
    if written.group(1) != 'profile' or written.group(1) not in parsed.groups() or 'profiles' not in parsed.groups():
        raise SystemExit(f'FAIL: HapticProfileManager.cpp: KA_PROFILE_CHANGE written as {written.group(1)!r}, read as '
                         f'{parsed.groups()} (must write "profile" and read "profile" and the legacy "profiles")')
    return 1


def test_fx_intake_wiring() -> int:
    """FW-BUG-007: the FOC pass takes host effects through CCFxIntake, deferring them while the output is held for
    a re-entry (the runner's test_event_posted_while_entering_is_felt_after_ready models the same pass)."""
    foc = read('foc_thread.cpp')
    rules = [
        (r'CCFxIntake fx_intake\(cc_haptic_detail::shared\(\)\.fxWord\);', 'the intake starts at the boot word'),
        (r'const bool reentry_hold = cc_claimed\(\) && cc_input_id\(\) != runtime_id; const uint8_t fx = '
         r'fx_intake\.step\(static_cast<uint32_t>\(xTaskGetTickCount\(\) \* portTICK_PERIOD_MS\), !runtime_active '
         r'\|\| sleep_foc\.motorOff\(\) \|\| spin_trip\.latched\(\), reentry_hold\); if \(fx != CC_HFX_NONE\) '
         r'haptic\.play_effect\(fx\);', 'effects are deferred while held for a re-entry, dropped while discarded'),
        (r'reentry_hold\); if \(fx != CC_HFX_NONE\) haptic\.play_effect\(fx\); if \(spin_trip\.latched\(\) && '
         r'!sleep_foc\.motorOff\(\)\) \{ motor\.loopFOC\(\); motor\.move\(0\); \} else if \(sleep_foc\.motorOff\(\) '
         r'\|\| \(cc_claimed\(\) && cc_input_id\(\) != runtime_id\)\) \{ motor\.loopFOC\(\); motor\.move\(0\); \} '
         r'else haptic\.haptic_loop\(\);', 'the same re-entry gate (as reentry_hold) holds the output'),
    ]
    for pattern, what in rules:
        if not re.search(pattern, foc):
            raise SystemExit(f'FAIL: foc_thread.cpp: {what} (FW-BUG-007)')
    if 'cc_fx_take(' in foc:
        raise SystemExit('FAIL: foc_thread.cpp: a bare cc_fx_take() is back (FW-BUG-007)')
    return len(rules) + 1


def test_recalibrate_failure_reenables_motor() -> int:
    """FW-BUG-009: when a recalibration fails, the restoring initFOC() is followed by motor.enable() (unless the
    sleep has the motor off), and a restore that fails too reports init-failed."""
    foc = read('foc_thread.cpp')
    block = re.search(r'if \(outcome != CC_CAL_OK\) \{(.*?)\} haptic\.reanchor\(\);', foc)
    if not block:
        raise SystemExit('FAIL: foc_thread.cpp: the recalibration failure branch (FW-BUG-009)')
    body = block.group(1)
    if not re.search(r'motor\.sensor_direction = oldDirection; motor\.zero_electric_angle = oldZero; if \(motor\.initFOC\(\)\) '
                     r'\{ if \(!motorOff\) motor\.enable\(\); \} else outcome = CC_CAL_FAIL_INIT;', body):
        raise SystemExit('FAIL: foc_thread.cpp: a failed recalibration restores, then motor.enable() (FW-BUG-009)')
    if not re.search(r'recalibrate\(cal_trip_guard\.acceptDirection\(\(request & CC_CAL_ACCEPT_DIRECTION\) != 0, spin_trip\), '
                     r'runtime_active \|\| cc_claimed\(\), sleep_foc\.motorOff\(\)\);', foc):
        raise SystemExit('FAIL: foc_thread.cpp: recalibrate() is told whether the sleep has the motor off (FW-BUG-009)')
    return 2


def test_native_profile_switch_rebases() -> int:
    """FW-BUG-008: handleHapticConfig() applies a native profile through rebase_runtime(profile, start_pos) (the grid
    at the shaft angle, as the release and offline paths do); the offline branch still stores the state it restores.
    The runner's test_native_profile_switch_counts_from_any_shaft_angle models the same load."""
    foc = read('foc_thread.cpp')
    block = re.search(r'void FocThread::handleHapticConfig\(\) \{(.*?)\};', foc)
    if not block or not re.search(r'if \(offline_active\) offline_saved = HapticState\(profile\); else '
                                  r'haptic\.rebase_runtime\(profile, profile\.start_pos\);', block.group(1)):
        raise SystemExit('FAIL: foc_thread.cpp: handleHapticConfig() rebases a native profile at the shaft (FW-BUG-008)')
    if 'haptic.haptic_state = HapticState(' in block.group(1):
        raise SystemExit('FAIL: foc_thread.cpp: a native profile is assigned with its grid at angle 0 (FW-BUG-008)')
    return 2


def test_detent_pulses_never_freeze_and_the_grid_is_indexed() -> int:
    """FW-BUG-010: a detent pulse never freezes the count (CCFxPlayer::start), find_detent() keeps the committed
    detent when the recomputed attractor has its grid index, and end_freeze() steps through grid attractors
    (cc_detent_angle), never last + w. The runner's test_slow_turn_with_detent_pulses_counts_every_detent models it."""
    haptic = read('haptic.cpp')
    fx = code((src / 'cc_haptic_fx.h').read_text(encoding='utf-8', errors='replace'))
    if 'freeze_ = !detent && speed < CC_HFX_FREEZE_RAD_S;' not in fx:
        raise SystemExit('FAIL: cc_haptic_fx.h: a detent pulse never freezes the count (FW-BUG-010)')
    if not re.search(r'cc_detent_index\(haptic_state\.attract_angle, haptic_state\.detent_origin, haptic_state\.detent_width\) '
                     r'== cc_detent_index\(haptic_state\.last_attract_angle, haptic_state\.detent_origin, '
                     r'haptic_state\.detent_width\)\) haptic_state\.attract_angle = haptic_state\.last_attract_angle; '
                     r'if\(haptic_state\.last_attract_angle != haptic_state\.attract_angle\)\{ detent_handler\(\);', haptic):
        raise SystemExit('FAIL: haptic.cpp: find_detent() compares grid indices before counting (FW-BUG-010)')
    block = re.search(r'void HapticInterface::end_freeze\(void\) \{(.*?)\n?void HapticInterface::wall_refused', haptic)
    if not block or 'haptic_state.attract_angle = cc_detent_angle(from + (steps > 0 ? 1 : -1), origin, w);' not in block.group(1) \
            or 'last_attract_angle + (steps' in block.group(1):
        raise SystemExit('FAIL: haptic.cpp: end_freeze() steps through grid attractors (FW-BUG-010)')
    return 3


def test_foldback_counts_applied_wall_volts() -> int:
    """FW-TST-001: token_target() steps the fold-back after the rest gate with the wall volts actually applied (0 while
    the gate zeroes the output). The runner's wall_rest_tests 'asleep past the bound' case models the same order."""
    haptic = read('haptic.cpp')
    block = re.search(r'void HapticInterface::token_target\(void\) \{(.*?)motor->move\(out\); \}', haptic)
    if not block:
        raise SystemExit('FAIL: haptic.cpp: token_target() not found (FW-TST-001)')
    body = block.group(1)
    if body.count('fold_.step(') != 1 or not re.search(
            r'if \(rest_\.step\(.*?\)\) \{ out = 0\.0f; springOut_ = 0\.0f; wallVolts_ = 0\.0f; \} else if \(wasAsleep\) '
            r'\{ restart_fade\(CC_FEEL_FADE_MS\); \} #if CC_HAPTIC_FOLDBACK fold_\.step\(wallVolts_, dt\); #endif', body):
        raise SystemExit('FAIL: haptic.cpp: the fold-back steps after the rest gate with the applied wall volts (FW-TST-001)')
    return 1


def test_register_numbers_are_range_checked() -> int:
    """FW-BUG-035: HapticCommander::handleMessage() checks the whole command (cc_reg_command_check) before any
    dispatch and returns false (no recalibration, no register write) when it refuses; FocThread::handleMessage()
    answers a refusal as {"error":...}; no atoi() is left (the integer readers use cc_parse_ranged). The runner's
    test_register_number_out_of_range_is_refused checks the rule itself."""
    commander = read('HapticCommander.cpp')
    foc = read('foc_thread.cpp')
    if not re.search(r'bool HapticCommander::handleMessage\(String\* message\) \{ uint8_t reg = 0; const uint8_t check = '
                     r'cc_reg_command_check\(message->c_str\(\), reg\); if \(check != CC_REG_CMD_OK\) \{ message->clear\(\);'
                     r'[^{}]*?msg_in = NULL; return false; \}', commander):
        raise SystemExit('FAIL: HapticCommander.cpp: the command is range-checked before any dispatch (FW-BUG-035)')
    if 'atoi(' in commander:
        raise SystemExit('FAIL: HapticCommander.cpp: an atoi() truncation is back (FW-BUG-035)')
    if commander.count('cc_parse_ranged(msg_in, ') != 2:
        raise SystemExit('FAIL: HapticCommander.cpp: operator>>(uint8_t&) and (uint32_t&) range-check (FW-BUG-035)')
    if not re.search(r'const bool ok = commander\.handleMessage\(message\); StringMessage smsg\(message, ok \? '
                     r'StringMessageType::STRING_MESSAGE_MOTOR : StringMessageType::STRING_MESSAGE_ERROR\);', foc):
        raise SystemExit('FAIL: foc_thread.cpp: a refused register command is answered as an error (FW-BUG-035)')
    return 4


def test_profile_files_match_exact_names() -> int:
    """FW-BUG-038: toSPIFFS() keeps a stored profile file only when it is exactly a live profile's "<name>.json"
    (haptic_bounds.h haptic_profile_file_kept); no suffix match is left. The runner's
    test_deleted_profile_with_suffix_name_is_removed checks the rule."""
    pm = read('HapticProfileManager.cpp')
    block = re.search(r'void HapticProfileManager::toSPIFFS\(\) \{(.*?)if \(profiles\[i\]\.profile_name!="" && '
                      r'profiles\[i\]\.dirty\)', pm)
    body = block.group(0) if block else ''
    if 'const bool found = haptic_profile_file_kept(profiles, MAX_PROFILES, filename.c_str());' not in body:
        raise SystemExit('FAIL: HapticProfileManager.cpp: toSPIFFS() keeps only exact "<name>.json" files (FW-BUG-038)')
    if re.search(r'endsWith\(profiles\[i\]\.profile_name', pm):
        raise SystemExit('FAIL: HapticProfileManager.cpp: a suffix match of a profile file is back (FW-BUG-038)')
    return 2


def test_rest_and_thud_pins_catch_reverts() -> int:
    """HN-TST-001: each new wiring pin fails when its source line is reverted (pins() run on mutated source text)."""
    global read
    original = read
    mutations = [
        ('control_center.cpp', 'c["knobVolume"] = 1;', ''),
        ('haptic.cpp', 'const bool busy = fx_.busy(now) || haptic_state.wasAtLimit || frozen_;',
         'const bool busy = fx_.busy(now) || frozen_;'),
        ('haptic.cpp', 'motor->shaft_velocity, busy, cc_rest_wake_rad(haptic_state.detent_width))',
         'motor->shaft_velocity, busy, haptic_state.detent_width)'),
        ('haptic.cpp', 'const bool busy = fx_.busy(now) || kd > fp_.kd || haptic_state.wasAtLimit || frozen_;',
         'const bool busy = fx_.busy(now) || haptic_state.wasAtLimit || frozen_;'),
        ('haptic.cpp', 'velocity, busy, cc_rest_wake_rad(w))', 'velocity, false, cc_rest_wake_rad(w))'),
        ('haptic.cpp', 'velocity, busy, cc_rest_wake_rad(w))', 'velocity, busy, w * 2.0f)'),
        ('haptic.cpp', 'restart_fade(CC_FEEL_FADE_MS); }', '}'),
        ('haptic.cpp', 'rest_.refused();', ''),
        ('cc_haptic_fx.h', 'if (refused_) { busy = true; refused_ = false; }', 'refused_ = false;'),
        ('haptic.cpp', 'if (feel_ != CC_FEEL_LEGACY && !reduced_) { const CCSoundCue wall',
         'if (feel_ != CC_FEEL_LEGACY) { const CCSoundCue wall'),
        ('haptic.cpp', 'if (feel_ != CC_FEEL_LEGACY && !reduced_) { const CCSoundCue wall',
         'if (!reduced_) { const CCSoundCue wall'),
        ('haptic.cpp', '(CC_HAPTIC_FOLDBACK ? fold_.factor() : 1.0f)', '1.0f'),
        ('haptic.cpp', 'spring = -static_cast<float>(outward) * wallVolts_ / CC_HAPTIC_PHASE_OHMS;',
         'spring = -static_cast<float>(outward) * cc_wall_volts(cc_law_slope(fp_.law, fp_.kp), pen, w, cap) / '
         'CC_HAPTIC_PHASE_OHMS;'),
    ]
    caught = 0
    try:
        for name, before, after in mutations:
            text = original(name)
            if before not in text:
                raise SystemExit(f'FAIL: HN-TST-001 mutation target not in {name}: {before!r}')

            def mutated(n, _name=name, _before=before, _after=after):
                t = original(n)
                return t.replace(_before, _after, 1) if n == _name else t
            read = mutated
            try:
                pins()
            except SystemExit as failure:
                if not str(failure).startswith('FAIL'):
                    raise
                caught += 1
                continue
            raise SystemExit(f'FAIL: HN-TST-001: pins() still passes with {name} {before!r} -> {after!r}')
    finally:
        read = original
    return caught


def test_profile_desc_and_tag_are_capped() -> int:
    """FW-BUG-027: HapticProfile::operator= (every update and every profile loaded from SPIFFS) caps profile_desc at
    kHapticProfileDescMaxBytes (50) and profile_tag at kHapticProfileTagMaxBytes (20) through haptic_profile_text_keep()
    after reading them; the runner's test_profile_desc_and_tag_are_capped checks the rule."""
    pm = read('HapticProfileManager.cpp')
    body = re.search(r'HapticProfile& HapticProfile::operator=\(JsonObject& obj\) \{(.*?)if \(!obj\["keys"\]\.isNull\(\)\)', pm)
    body = body.group(1) if body else ''
    rules = [
        (r'update_field\(obj, desc, profile_desc\);.*?const unsigned keep = haptic_profile_text_keep\(profile_desc, '
         r'kHapticProfileDescMaxBytes\); if \(keep < profile_desc\.length\(\)\) \{ profile_desc = '
         r'profile_desc\.substring\(0, keep\); dirty = true; \}', 'desc capped after it is read'),
        (r'update_field\(obj, profileTag, profile_tag\);.*?const unsigned keep = haptic_profile_text_keep\(profile_tag, '
         r'kHapticProfileTagMaxBytes\); if \(keep < profile_tag\.length\(\)\) \{ profile_tag = '
         r'profile_tag\.substring\(0, keep\); dirty = true; \}', 'tag capped after it is read'),
    ]
    for pattern, what in rules:
        if not re.search(pattern, body, re.S):
            raise SystemExit(f'FAIL: HapticProfileManager.cpp: operator=: {what} (FW-BUG-027)')
    bounds = read('haptic_bounds.h')
    for pattern in (r'kHapticProfileDescMaxBytes = 50;', r'kHapticProfileTagMaxBytes = 20;'):
        if not re.search(pattern, bounds):
            raise SystemExit(f'FAIL: haptic_bounds.h: {pattern} (FW-BUG-027)')
    return len(rules) + 2


def test_boot_calibration_uses_the_rules() -> int:
    """FW-TST-009: setCalibration() maps the stored pair through cc_cal_from_nvs() (no raw "else CCW", no raw zero),
    and the boot store after initFOC() is decided by cc_boot_cal_store() (either value changed, init succeeded). The
    runner's boot_cal_tests table checks the rules."""
    foc = read('foc_thread.cpp')
    block = re.search(r'void FocThread::setCalibration\(MotorCalibration& cal\)\{(.*?)\};', foc)
    if not block or 'const CCBootCal c = cc_cal_from_nvs(cal.direction, cal.zero_angle);' not in block.group(1)             or 'haptic.motor->zero_electric_angle = c.zero;' not in block.group(1) or 'cal.zero_angle;' in block.group(1):
        raise SystemExit('FAIL: foc_thread.cpp: setCalibration() validates the stored pair (FW-TST-009)')
    if not re.search(r'const CCBootCal calBefore = boot_cal_of\(motor\); .*?int initResult = motor\.initFOC\(\); .*?'
                     r'if \(cc_boot_cal_store\(calBefore, boot_cal_of\(motor\), initResult', foc):
        raise SystemExit('FAIL: foc_thread.cpp: the boot store is decided by cc_boot_cal_store() (FW-TST-009)')
    if re.search(r'motor\.sensor_direction != dir && initResult != 0', foc):
        raise SystemExit('FAIL: foc_thread.cpp: the direction-only boot store is back (FW-TST-009)')
    if 'static_assert(CC_BOOT_CAL_NOT_SET == NOT_SET' not in foc:
        raise SystemExit('FAIL: foc_thread.cpp: cc_boot_cal.h NOT_SET is tied to SimpleFOC (FW-TST-009)')
    return 4


def test_boot_store_needs_the_pole_check() -> int:
    """FW-PUB-006: the boot store is gated on SimpleFOC's pp_check_result of this alignment (reset before initFOC()),
    an alignment posts ALIGNING (the LCD's hands-off cue) and waits 1 s first, and the outcome is posted after. The
    runner's boot_pole_tests checks the rules."""
    foc = read('foc_thread.cpp')
    rules = [
        (r'const bool aligning = calBefore\.direction == CC_BOOT_CAL_UNKNOWN; if \(aligning\) \{ '
         r'cc_motor_cal_post\(CC_MOTOR_CAL_ALIGNING\); vTaskDelay\(1000 / portTICK_PERIOD_MS\); \}', 'hands off, 1 s settle'),
        (r'motor\.pp_check_result = false; int initResult = motor\.initFOC\(\); const bool poleOk = motor\.pp_check_result; '
         r'cc_motor_cal_post\(cc_boot_cal_outcome\(initResult, aligning, poleOk\)\);', 'the pole check of this alignment'),
        (r'if \(cc_boot_cal_store\(calBefore, boot_cal_of\(motor\), initResult, poleOk\)\) \{ .*?'
         r'if \(!DeviceSettings::getInstance\(\)\.storeCalibration\(cal\)\) \{ com_thread\.put_string_message\(',
         'the store needs the pole check, and a refused store is logged (FW-BUG-028)'),
    ]
    for pattern, what in rules:
        if not re.search(pattern, foc):
            raise SystemExit(f'FAIL: foc_thread.cpp: {what} (FW-PUB-006)')
    if len(re.findall(r'storeCalibration\(', foc)) != 1:
        raise SystemExit('FAIL: foc_thread.cpp: exactly one boot storeCalibration() (FW-PUB-006)')
    return len(rules) + 1


def test_wake_never_enables_an_uncalibrated_motor() -> int:
    """FW-BUG-030: the sleep wake enables the driver only when SimpleFOC's motor_status is motor_ready; a failed boot
    alignment arms the one retry (after CC_BOOT_RETRY_IDLE_MS idle) and the diag publishes motorReady / motorCal; the
    retry saves through the COM handshake like recalibrate(). The runner's boot_wake_tests models the wake."""
    foc = read('foc_thread.cpp')
    rules = [
        (r'else if \(sleepStep\.action == CC_SLEEP_MOTOR_ENABLE\) \{ if \(cc_motor_wake_enable\(motor\.motor_status == '
         r'FOCMotorStatus::motor_ready\)\) motor\.enable\(\); haptic\.reanchor\(\);', 'the wake enables only a ready motor'),
        (r'if \(initResult == 0\) \{ [^{}]*?boot_retry\.failed\(', 'a failed boot arms the retry'),
        (r'if \(boot_retry\.step\(static_cast<uint32_t>\(xTaskGetTickCount\(\) \* portTICK_PERIOD_MS\), '
         r'cc_live_key_state\(\) == 0 && !runtime_active && !cc_claimed\(\) && !sleep_foc\.motorOff\(\)',
         'the retry waits for an idle, awake, unclaimed knob'),
        (r'if \(boot_retry\.step\([^;{]*?cc_haptic_detail::shared\(\)\.calRequest == cal_seen, '
         r'motor\.motor_status == FOCMotorStatus::motor_ready\)\) \{ retry_boot_alignment\(\);',
         'a ready motor (a recalibration succeeded meanwhile) disarms the retry'),
        (r'feel_diag\.motorReady = motor\.motor_status == FOCMotorStatus::motor_ready;', 'diag motorReady'),
        (r'bool FocThread::retry_boot_alignment\(\) \{.*?motor\.pp_check_result = false; const int initResult = '
         r'motor\.initFOC\(\);.*?cc_boot_cal_store\(calBefore, boot_cal_of\(motor\), initResult, poleOk\) && '
         r'!save_through_com\(\)', 'the retry stores through the COM handshake, pole check gated'),
        (r's\.calState = CC_CAL_SAVING; if \(!save_through_com\(\)\) outcome = CC_CAL_FAIL_SAVE;',
         'recalibrate() saves through the same handshake'),
    ]
    for pattern, what in rules:
        if not re.search(pattern, foc):
            raise SystemExit(f'FAIL: foc_thread.cpp: {what} (FW-BUG-030)')
    if foc.count('motor.enable()') != 4:
        raise SystemExit('FAIL: foc_thread.cpp: motor.enable() only on a ready wake, a recalibration (run, restore) and the boot retry '
                         '(FW-BUG-030)')
    return len(rules) + 1


def test_cal_direction_rule_wiring() -> int:
    """FW-BUG-046: recalibrate() is told to accept a changed direction by CCCalTripGuard (request bit, a latch now, a
    trip since the last successful calibration), never by the lifetime trip count; a successful run and a successful
    boot retry mark the calibration. The runner's test_cal_direction_rule_ignores_cleared_trip models the rule."""
    foc = read('foc_thread.cpp')
    rules = [
        (r'recalibrate\(cal_trip_guard\.acceptDirection\(\(request & CC_CAL_ACCEPT_DIRECTION\) != 0, spin_trip\),',
         'the direction rule asks the guard'),
        (r'if \(outcome == CC_CAL_OK\) \{ cc_motor_cal_post\(CC_MOTOR_CAL_READY\); cal_trip_guard\.calibrated\(spin_trip\);',
         'a successful recalibration marks the calibration'),
        (r'if \(initResult != 0\) cal_trip_guard\.calibrated\(spin_trip\);', 'a successful boot retry marks it'),
    ]
    for pattern, what in rules:
        if not re.search(pattern, foc):
            raise SystemExit(f'FAIL: foc_thread.cpp: {what} (FW-BUG-046)')
    if re.search(r'spin_trip\.trips\(\) > 0', foc):
        raise SystemExit('FAIL: foc_thread.cpp: the lifetime trip count accepts a direction change again (FW-BUG-046)')
    return len(rules) + 1


def test_app_angle_is_a_wrapping_word() -> int:
    """FW-BUG-032: the app canvas angle is published from CCAngleWord (whole turns + in-turn angle, a wrapping count),
    never as a float-to-int32 cast of the total angle. The runner's test_app_angle_word_wraps models the word."""
    foc = read('foc_thread.cpp')
    if not re.search(r'app_angle = app_angle_word\.step\(encoder\.getFullRotations\(\), encoder\.getMechanicalAngle\(\)\);', foc):
        raise SystemExit('FAIL: foc_thread.cpp: the app angle comes from the wrapping word (FW-BUG-032)')
    if re.search(r'app_angle = static_cast<int32_t>\(', foc):
        raise SystemExit('FAIL: foc_thread.cpp: the float-to-int32 app angle cast is back (FW-BUG-032)')
    return 2


def test_recalibration_while_asleep_leaves_the_motor_off() -> int:
    """FW-RES-011: after a recalibration that ran while the sleep had the motor off, the driver is disabled again and,
    asleep, the sleep watcher starts over at the new shaft angle and is stepped once (asleep) in the same pass, before
    the offline / trip / host effect / haptic loop gates read motorOff(). The runner's
    test_foc_reseed_after_motor_driven_motion models the watcher."""
    foc = read('foc_thread.cpp')
    if not re.search(r'runtime_active \|\| cc_claimed\(\), sleep_foc\.motorOff\(\)\); if \(sleep_foc\.motorOff\(\)\) \{ '
                     r'motor\.disable\(\); if \(cc_sleep_state\(\) == CC_SLEEP_ASLEEP\) \{ sleep_foc = CCSleepFoc\(\); '
                     r'sleep_foc\.step\(static_cast<uint32_t>\(xTaskGetTickCount\(\) \* portTICK_PERIOD_MS\), '
                     r'motor\.shaft_angle, true\); \} \} serial_last_pos = haptic\.haptic_state\.current_pos; \}'
                     r' const bool want_offline = ', foc):
        raise SystemExit('FAIL: foc_thread.cpp: a recalibration while asleep leaves the driver off and re-seeds the '
                         'sleep watcher, stepped in the same pass before the motorOff() gates (FW-RES-011)')
    return 1


def test_cal_save_goes_through_the_handshake_class() -> int:
    """FW-TST-010: the FOC task's save wait and the COM task's take / saved are thin callers of CCCalHandshake (the
    runner's cal_handshake_tests: the write bound, the take deadline, the two-thread race); no hand-rolled wait on
    calSave is left in foc_thread.cpp."""
    foc = read('foc_thread.cpp')
    rules = [
        (r'CCCalHandshake<CCCalPortLock> cal_handshake\(cal_lock\);', 'one handshake on the port lock'),
        (r'bool cc_cal_take_save\(MotorCalibration& cal\) \{ [^{}]*?if \(!cal_handshake\.take\(direction, zero\)\) return false;',
         'the COM take'),
        (r'void cc_cal_saved\(bool ok\) \{ cal_handshake\.saved\(ok\); \}', 'the COM saved report, with its result (FW-BUG-028)'),
        (r'bool FocThread::save_through_com\(\) \{ cal_handshake\.offer\([^;]*?, millis\(\)\); while \(true\) \{ '
         r'motor\.loopFOC\(\); motor\.move\(0\); const uint8_t poll = cal_handshake\.poll\(millis\(\)\); '
         r'if \(poll != CC_CAL_POLL_WAIT\) return poll == CC_CAL_POLL_SAVED; vTaskDelay\(1\); \} \}',
         'the FOC wait holds a zero output and ends on the handshake poll'),
    ]
    for pattern, what in rules:
        if not re.search(pattern, foc):
            raise SystemExit(f'FAIL: foc_thread.cpp: {what} (FW-TST-010)')
    if re.search(r'\bcalSave\b', foc):
        raise SystemExit('FAIL: foc_thread.cpp: a hand-rolled calSave wait is back (FW-TST-010)')
    return len(rules) + 1


def test_successful_recalibration_clears_the_latch() -> int:
    """FW-BUG-031: CCCalTripGuard::calibrated() clears the trip latch, and recalibrate() calls it only after a run
    that answered ok (after haptic.reanchor()); a failed run keeps the latch. The runner's
    test_successful_recalibration_clears_trip_latch models it on the knob."""
    fx = code((src / 'cc_haptic_fx.h').read_text(encoding='utf-8', errors='replace'))
    foc = read('foc_thread.cpp')
    if not re.search(r'void calibrated\(CCSpinTrip& trip\) \{ trip\.clear\(\); tripsAtCal_ = trip\.trips\(\); \}', fx):
        raise SystemExit('FAIL: cc_haptic_fx.h: a successful calibration clears the trip latch (FW-BUG-031)')
    if not re.search(r'haptic\.reanchor\(\); \} if \(outcome == CC_CAL_OK\) \{ cc_motor_cal_post\(CC_MOTOR_CAL_READY\); '
                     r'cal_trip_guard\.calibrated\(spin_trip\); \}', foc):
        raise SystemExit('FAIL: foc_thread.cpp: only an ok recalibration, after the re-anchor, clears the latch (FW-BUG-031)')
    if len(re.findall(r'cal_trip_guard\.calibrated\(', foc)) != 2:
        raise SystemExit('FAIL: foc_thread.cpp: the latch is cleared only by an ok recalibration or boot retry (FW-BUG-031)')
    return 3


def test_load_profile_position_is_explicit() -> int:
    """FW-BUG-034: no in-band 0xFFFF "no position" sentinel. load_profile() takes hasPosition (default true, so every
    constructor and rebase_runtime() pass their position, 65535 included) and loads through haptic_load_position()
    with the scaled bounds (the runner's test_rebase_keeps_position_65535)."""
    haptic = read('haptic.cpp')
    header = read('haptic.h')
    if re.search(r'0xFFFF', haptic):
        raise SystemExit('FAIL: haptic.cpp: a 0xFFFF position sentinel is back (FW-BUG-034)')
    if not re.search(r'void load_profile\(DetentProfile profile, uint16_t position, bool hasPosition = true\);', header):
        raise SystemExit('FAIL: haptic.h: load_profile() takes an explicit hasPosition, true by default (FW-BUG-034)')
    if not re.search(r'void HapticState::load_profile\(DetentProfile profile, uint16_t new_position, bool hasPosition\)\{', haptic):
        raise SystemExit('FAIL: haptic.cpp: load_profile() has no default sentinel position (FW-BUG-034)')
    if not re.search(r'current_pos = haptic_load_position\(hasPosition, new_position, current_pos, '
                     r'cc_scaled_position\(profile\.start_pos, isVernier\), cc_scaled_position\(profile\.end_pos, isVernier\)\);',
                     haptic):
        raise SystemExit('FAIL: haptic.cpp: load_profile() loads through haptic_load_position() with scaled bounds (FW-BUG-034)')
    return 4


def bounds_recovery_rule(haptic: str, fx: str) -> str:
    """'' when bounds_handler() leaves its recovery loop by CC_BOUNDS_RECOVERY_US (<= 2000 us) before any loopFOC(),
    else what is wrong."""
    m = re.search(r'constexpr unsigned long CC_BOUNDS_RECOVERY_US = (\d+)u?;', fx)
    if not m or not 0 < int(m.group(1)) <= 2000:
        return 'cc_haptic_fx.h: CC_BOUNDS_RECOVERY_US is defined, at most 2000 us'
    body = re.search(r'void HapticInterface::bounds_handler\(float detent_width\) \{(.*?) haptic_state\.wasAtLimit = false; \}',
                     haptic)
    if not body:
        return 'haptic.cpp: bounds_handler() not found'
    loop = re.search(r'const unsigned long recoveryStarted = micros\(\); while\(fabsf\(motor->shaft_velocity\) > 1\.0\)\{ '
                     r'([^{}]*?)motor->loopFOC\(\);', body.group(1))
    if not loop or not re.search(r'if \(\(unsigned long\)\(micros\(\) - recoveryStarted\) >= CC_BOUNDS_RECOVERY_US\) break;',
                                 loop.group(1)):
        return 'haptic.cpp: bounds_handler() breaks on micros() - recoveryStarted >= CC_BOUNDS_RECOVERY_US before loopFOC()'
    return ''


def test_bounds_recovery_is_time_bounded() -> int:
    """FW-TST-008: bounds_handler()'s recovery loop (loopFOC / move until |v| < 1 rad/s) is bounded at 2 ms, so a knob
    spinning at an end stop never starves the FOC task (requests, rest gate, lease). The rule fails on a dropped break,
    a break after loopFOC() or a longer bound."""
    haptic = read('haptic.cpp')
    fx = code((src / 'cc_haptic_fx.h').read_text(encoding='utf-8', errors='replace'))
    problem = bounds_recovery_rule(haptic, fx)
    if problem:
        raise SystemExit(f'FAIL: {problem} (FW-TST-008)')
    brk = 'if ((unsigned long)(micros() - recoveryStarted) >= CC_BOUNDS_RECOVERY_US) break;'
    reverts = [
        (haptic.replace(brk, ''), fx),
        (haptic.replace(brk + ' ', '').replace('motor->loopFOC(); motor->move(default_pid(error));',
                                               'motor->loopFOC(); ' + brk + ' motor->move(default_pid(error));'), fx),
        (haptic, fx.replace('CC_BOUNDS_RECOVERY_US = 2000;', 'CC_BOUNDS_RECOVERY_US = 20000;')),
    ]
    for i, (h, f) in enumerate(reverts):
        if not bounds_recovery_rule(h, f):
            raise SystemExit(f'FAIL: the bounds recovery rule misses revert {i} (FW-TST-008)')
    return 1 + len(reverts)


def test_fluid_freeze_counts_the_turn() -> int:
    """FW-BUG-033: end_freeze() moves the grid only by cc_freeze_absorb() (the shift less the hand's turn, from the
    speeds at the freeze's start and end, bounded) and counts the rest through the stepped path; haptic_loop() records
    the freeze's start time and velocity. The runner's test_fluid_turn_with_effect_counts_every_detent models it with
    the same helper."""
    haptic = read('haptic.cpp')
    rules = [
        (r'if \(frozen && !frozen_\) \{ freezeAngle_ = motor->shaft_angle; freezeUs_ = freezeNow; '
         r'freezeVelocity_ = motor->shaft_velocity; \}', 'haptic_loop() records the freeze start'),
        (r'void HapticInterface::end_freeze\(void\) \{ const float shift = motor->shaft_angle - freezeAngle_; '
         r'const float elapsed = static_cast<float>\(static_cast<uint32_t>\(micros\(\) - freezeUs_\)\) \* 1e-6f; '
         r'const float absorb = cc_freeze_absorb\(feel_ != CC_FEEL_LEGACY && fp_\.law == CC_LAW_VISCOSE, freezeVelocity_, '
         r'motor->shaft_velocity, elapsed, shift, haptic_state\.detent_width\); if \(absorb != 0\.0f\) \{ '
         r'haptic_state\.detent_origin \+= absorb; haptic_state\.attract_angle \+= absorb; '
         r'haptic_state\.last_attract_angle \+= absorb; \} const float w = haptic_state\.detent_width;',
         'end_freeze() moves the grid by cc_freeze_absorb() only, then counts the rest'),
    ]
    for pattern, what in rules:
        if not re.search(pattern, haptic):
            raise SystemExit(f'FAIL: haptic.cpp: {what} (FW-BUG-033)')
    if re.search(r'end_freeze\(void\) \{[^}]*?return; \}', haptic):
        raise SystemExit('FAIL: haptic.cpp: end_freeze() returns before counting the turn (FW-BUG-033)')
    return len(rules) + 1


def test_feel_fade_is_cleared_once_complete() -> int:
    """FW-BUG-037: haptic.cpp keeps feel.fade in one CCFeelFade (cleared once complete, so a micros() wrap 71.6 min
    later never re-runs it): set_feel() and restart_fade() start it, token_target() reads it for the spring and the wall,
    and no hand-rolled (now - start) fade is left. The runner's fade_wrap_tests check the class."""
    haptic = read('haptic.cpp')
    header = read('haptic.h')
    if 'CCFeelFade fade_;' not in header or re.search(r'fadeStartUs_|fadeMs_', header + haptic):
        raise SystemExit('FAIL: haptic.h / haptic.cpp: feel.fade lives in one CCFeelFade (FW-BUG-037)')
    if 'cc_fade_factor(' in haptic:
        raise SystemExit('FAIL: haptic.cpp: a raw cc_fade_factor() fade is back (FW-BUG-037)')
    if len(re.findall(r'fade_\.factor\(now\)', haptic)) != 2:
        raise SystemExit('FAIL: haptic.cpp: the spring and the wall read fade_.factor(now) (FW-BUG-037)')
    if not re.search(r'fade_\.start\(feel_ != CC_FEEL_LEGACY \? fadeMs : 0, micros\(\)\);', haptic) or \
            not re.search(r'void HapticInterface::restart_fade\(uint32_t fadeMs\) \{ if \(feel_ == CC_FEEL_LEGACY \|\| '
                          r'fadeMs == 0\) return; fade_\.start\(fadeMs, micros\(\)\); \}', haptic):
        raise SystemExit('FAIL: haptic.cpp: set_feel() and restart_fade() start the fade (FW-BUG-037)')
    return 4


def main() -> int:
    started = time.time()
    pinned = pins()
    pinned += test_register_writes_are_allow_listed()
    pinned += test_profile_manager_uses_the_slot_rules()
    pinned += test_profile_change_action_round_trips()
    pinned += test_fx_intake_wiring()
    pinned += test_recalibrate_failure_reenables_motor()
    pinned += test_native_profile_switch_rebases()
    pinned += test_detent_pulses_never_freeze_and_the_grid_is_indexed()
    pinned += test_foldback_counts_applied_wall_volts()
    pinned += test_register_numbers_are_range_checked()
    pinned += test_profile_files_match_exact_names()
    pinned += test_profile_desc_and_tag_are_capped()
    pinned += test_boot_calibration_uses_the_rules()
    pinned += test_boot_store_needs_the_pole_check()
    pinned += test_wake_never_enables_an_uncalibrated_motor()
    pinned += test_cal_direction_rule_wiring()
    pinned += test_app_angle_is_a_wrapping_word()
    pinned += test_recalibration_while_asleep_leaves_the_motor_off()
    pinned += test_cal_save_goes_through_the_handshake_class()
    pinned += test_successful_recalibration_clears_the_latch()
    pinned += test_load_profile_position_is_explicit()
    pinned += test_bounds_recovery_is_time_bounded()
    pinned += test_fluid_freeze_counts_the_turn()
    pinned += test_feel_fade_is_cleared_once_complete()
    reverts = test_rest_and_thud_pins_catch_reverts()
    subprocess.run([sys.executable, str(root / 'cpp11_gate.py')], check=True, stdout=subprocess.DEVNULL)
    out_dir.mkdir(parents=True, exist_ok=True)
    table = write_cases(out_dir / 'haptic_cases.json')
    parity = host_parity(table)
    exe = compile_runner()
    subprocess.run([str(exe), str(out_dir / 'haptic_cases.json')], check=True)
    print(f'PASS: r4 feel + sound (cc_haptic_fx.h, audio/cc_sound.h), {parity} haptic parity case(s) on both readings, '
          f'{pinned} firmware wiring pin(s), {reverts} reverted line(s) caught [{time.time() - started:.1f} s]')
    return 0


if __name__ == '__main__':
    sys.exit(main())
