"""Inactivity dim / sleep checks (user decisions 2026-09-28). Python stdlib + MSVC only; no device, no USB.

1. Runs cpp11_gate.py: every shared unit, cc_sleep.h's generated unit included, must compile in the
   device's gnu++11, and the firmware source rules must hold.
2. Compiles sleep_tests.cpp against the unchanged firmware header src/cc_sleep.h (MSVC /W4 /WX) and runs
   it: the timer (awake -> dim -> asleep, reset rules, swallow-first-input, millis() wrap, a racing input,
   the idle cap), the FOC knob watcher (threshold vs noise, disable once, the cogging quiet window, the
   wake turn and its settle, the settle cap, a button wake), the button swallow bookkeeping and the
   backlight clamp.
3. Pins the firmware wiring the runner's logic rests on, as source text (comments ignored):
   * the backlight: no ledcWrite() outside lcd_backlight_apply(), which writes cc_sleep_duty(); the
     PC-driven render asks for LEDC_MAX_BLK through lcd_backlight(); the LCD loop applies the state
     every pass;
   * the LEDs: exactly one FastLED.show() (led_wire_tests.py), preceded by the all-zero fill while
     asleep;
   * the buttons: the swallow filter is the first statement of the button handler (before the claimed
     and native branches), the HMI ticks the timer every pass;
   * the motor: motor.disable() / motor.enable() only in foc_thread.cpp (the FOC task), driven by
     CCSleepFoc, with haptic.reanchor() right after enable, and no haptic loop while the motor is off;
   * host lines never touch the timer: cc_sleep_input() is called only from hmi_thread.cpp (buttons)
     and foc_thread.cpp (rotation); the diag reply carries sleepState / idleMs.

Exit status is non-zero on any failure.
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
src = firmware / 'src'
out_dir = root / 'build' / 'sleep-tests'


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
    exe = out_dir / 'sleep_tests.exe'
    subprocess.run([
        str(cl), '/nologo', '/EHsc', '/std:c++14', '/W4', '/WX', '/O2', '/D_CRT_SECURE_NO_WARNINGS',
        f'/I{src}', str(root / 'sleep_tests.cpp'), f'/Fo{out_dir}\\', f'/Fe{exe}',
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

    lcd, hmi, foc, diag = read('lcd_thread.cpp'), read('hmi_thread.cpp'), read('foc_thread.cpp'), read('cc_diag.cpp')
    haptic = read('haptic.cpp')
    # Backlight.
    if lcd.count('ledcWrite(') != 1:
        raise SystemExit('FAIL: lcd_thread.cpp: every backlight write must go through lcd_backlight_apply()')
    need(lcd, r'static void lcd_backlight_apply\(\) \{ const uint16_t duty = cc_sleep_duty\(cc_sleep_state\(\), '
              r'blk_wanted\); if \(static_cast<int32_t>\(duty\) != blk_written\) \{ ledcWrite\(LEDC_CH_LCD_BKL, duty\);',
         'lcd_thread.cpp: the one backlight write is cc_sleep_duty() of the wanted duty')
    need(lcd, r'timed_render\(frame, cc_art_pixels\(frame\.artKey\)\);.*?lcd_backlight\(LEDC_MAX_BLK\);',
         'lcd_thread.cpp: the PC-driven render asks for LEDC_MAX_BLK through lcd_backlight() (clamped)')
    need(lcd, r'lv_timer_handler\(\); lcd_backlight_apply\(\);', 'lcd_thread.cpp: the state is applied every pass')
    for name in [p.name for p in src.iterdir() if p.suffix in ('.cpp', '.h', '.c') and p.name != 'lcd_thread.cpp']:
        if 'ledcWrite(' in read(name):
            raise SystemExit(f'FAIL: src/{name} writes the LEDC (the backlight belongs to lcd_thread.cpp)')
    count += 1
    # LEDs.
    if hmi.count('FastLED.show();') != 1:
        raise SystemExit('FAIL: hmi_thread.cpp must have exactly one FastLED.show()')
    need(hmi, r'if \(cc_sleep_state\(\) == CC_SLEEP_ASLEEP\) \{ fill_solid\(leds, NANO_LED_A_NUM, CRGB::Black\); '
              r'fill_solid\(ledsp, NANO_LED_B_NUM, CRGB::Black\); \} cc_crumb_hmi\(CC_HMI_STEP_SHOW\); FastLED\.show\(\);',
         'hmi_thread.cpp: all-zero LED frames while asleep, right before the one show')
    # Buttons and the timer.
    need(hmi, r'void HmiThreadButtonHandler::handleEvent\(AceButton\* button, uint8_t eventType, uint8_t buttonState\) '
              r'\{ const bool pressed = eventType == AceButton::kEventPressed; const bool released = eventType == '
              r'AceButton::kEventReleased; const bool woke = \(pressed \|\| released\) && cc_sleep_input\(\) && pressed; '
              r'if \(sleep_buttons\.filter\(index, pressed \? CC_SLEEP_KEY_PRESS : released \? CC_SLEEP_KEY_RELEASE : '
              r'CC_SLEEP_KEY_OTHER, woke\)\) return; if \(cc_claimed\(\)\) \{',
         'hmi_thread.cpp: the swallow filter runs first in the button handler, before both branches')
    need(hmi, r'handleConfig\(\); cc_sleep_tick\(\);', 'hmi_thread.cpp: the timer ticks every HMI pass')
    # Motor (FOC task only).
    for name in [p.name for p in src.iterdir() if p.suffix in ('.cpp', '.h')]:
        text = read(name)
        # HapticCommander.cpp: the stock recalibrate command, run by FocThread::handleMessage() (FOC task).
        if name not in ('foc_thread.cpp', 'HapticCommander.cpp') and re.search(r'\bmotor(?:->|\.)(?:disable|enable)\(', text):
            raise SystemExit(f'FAIL: src/{name} enables/disables the motor (only the FOC task may)')
        if name not in ('hmi_thread.cpp', 'foc_thread.cpp', 'cc_sleep.cpp', 'cc_sleep.h') and 'cc_sleep_input(' in text:
            raise SystemExit(f'FAIL: src/{name} calls cc_sleep_input(): only physical input (HMI buttons, FOC '
                             'rotation) may reset the timer')
    count += 2
    need(foc, r'if \(sleepStep\.input\) cc_sleep_input\(\); if \(sleepStep\.action == CC_SLEEP_MOTOR_DISABLE\) '
              r'motor\.disable\(\); else if \(sleepStep\.action == CC_SLEEP_MOTOR_ENABLE\) \{ motor\.enable\(\); '
              r'haptic\.reanchor\(\);',
         'foc_thread.cpp: disable / enable + re-anchor from CCSleepFoc on the FOC task')
    need(foc, r'if \(sleep_foc\.motorOff\(\) \|\| \(cc_claimed\(\) && cc_input_id\(\) != runtime_id\)\) '
              r'\{ motor\.loopFOC\(\); motor\.move\(0\); \} else haptic\.haptic_loop\(\);',
         'foc_thread.cpp: no haptic loop (no position change) while the motor is off')
    need(haptic, r'void HapticInterface::reanchor\(void\) \{ haptic_state\.detent_origin = motor->shaft_angle; '
                 r'haptic_state\.attract_angle = motor->shaft_angle; haptic_state\.last_attract_angle = motor->shaft_angle;',
         'haptic.cpp: reanchor() moves the detent grid to the shaft angle')
    if 'current_pos =' in re.search(r'void HapticInterface::reanchor\(void\) \{(.*?)\}', haptic).group(1):
        raise SystemExit('FAIL: haptic.cpp: reanchor() must keep the position')
    count += 1
    # Diag.
    need(diag, r'd\["sleepState"\] = cc_sleep_state_name\(sleep\.state\); d\["idleMs"\] = sleep\.idleMs;',
         'cc_diag.cpp: {"diag":"?"} reports sleepState and idleMs')
    return count


def main() -> int:
    started = time.time()
    pinned = pins()
    subprocess.run([sys.executable, str(root / 'cpp11_gate.py')], check=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    exe = compile_runner()
    subprocess.run([str(exe)], check=True)
    print(f'PASS: inactivity dim / sleep logic (cc_sleep.h) and {pinned} firmware wiring pin(s) '
          f'[{time.time() - started:.1f} s]')
    return 0


if __name__ == '__main__':
    sys.exit(main())
