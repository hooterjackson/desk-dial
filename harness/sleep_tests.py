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

4. FW-BUG-016: compiles the firmware's pinned LVGL with the firmware lv_conf.h (cached under
   build/sleep-tests/lvgl) and runs sleep_lvgl_tests.cpp: the firmware's src/cc_sleep_lcd.h against a real
   LVGL display; 10 s asleep with the host animating must flush nothing, the wake pass must flush the whole
   screen with the latest frame (the old one-shot timer pause is run as a control and must be caught).

Exit status is non-zero on any failure.
"""
from __future__ import annotations

import hashlib
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


LVGL = firmware / '.pio' / 'libdeps' / 'nanofoc_d' / 'lvgl'
lvgl_dir = out_dir / 'lvgl'


def build_lvgl() -> Path:
    """LVGL (the firmware's pinned copy) compiled with the firmware lv_conf.h into lvgl_dir/lvgl.lib; reused while
    lv_conf.h and the source list are unchanged. Host override as build.py: LV_USE_TFT_ESPI 1 -> 0."""
    cl, env = msvc_env()
    conf = (firmware / 'include' / 'lv_conf.h').read_bytes()
    conf, n = re.subn(rb'^([ \t]*#define[ \t]+LV_USE_TFT_ESPI[ \t]+)1\b', rb'\g<1>0', conf, flags=re.M)
    if n != 1:
        raise SystemExit('FAIL: firmware lv_conf.h: expected one "#define LV_USE_TFT_ESPI 1"')
    conf_dir = lvgl_dir / 'conf'
    obj_dir = lvgl_dir / 'obj'
    conf_dir.mkdir(parents=True, exist_ok=True)
    obj_dir.mkdir(parents=True, exist_ok=True)
    sources = sorted(str(p) for p in (LVGL / 'src').rglob('*.c'))
    stamp = hashlib.sha256(conf + '\n'.join(sources).encode()).hexdigest()
    lib = lvgl_dir / 'lvgl.lib'
    stamp_file = lvgl_dir / 'stamp.txt'
    if lib.exists() and stamp_file.exists() and stamp_file.read_text() == stamp:
        return conf_dir
    (conf_dir / 'lv_conf.h').write_bytes(conf)
    for old in obj_dir.rglob('*.obj'):
        old.unlink()
    lines = ['/nologo', '/c', '/O2', '/W0', '/MP', '/DLV_CONF_INCLUDE_SIMPLE', '/DLV_LVGL_H_INCLUDE_SIMPLE',
             '/D_CRT_SECURE_NO_WARNINGS', f'/I"{conf_dir}"', f'/I"{LVGL}"']
    # /MP with one /Fo directory needs unique basenames; compile groups of unique names.
    groups: list[list[str]] = []
    for s in sources:
        name = Path(s).stem
        for group in groups:
            if all(Path(o).stem != name for o in group):
                group.append(s)
                break
        else:
            groups.append([s])
    objs = []
    for gi, group in enumerate(groups):
        gdir = obj_dir / f'g{gi}'
        gdir.mkdir(exist_ok=True)
        grsp = lvgl_dir / f'lvgl{gi}.rsp'
        grsp.write_text('\n'.join(lines + [f'/Fo"{gdir}\\\\"'] + [f'"{s}"' for s in group]) + '\n', encoding='utf-8')
        subprocess.run([str(cl), f'@{grsp}'], cwd=lvgl_dir, env=env, check=True, stdout=subprocess.DEVNULL)
        objs += [str(gdir / (Path(s).stem + '.obj')) for s in group]
    lib_exe = cl.parent / 'lib.exe'
    lrsp = lvgl_dir / 'lib.rsp'
    lrsp.write_text('\n'.join(['/nologo', f'/OUT:"{lib}"'] + [f'"{o}"' for o in objs]) + '\n', encoding='utf-8')
    subprocess.run([str(lib_exe), f'@{lrsp}'], cwd=lvgl_dir, env=env, check=True)
    stamp_file.write_text(stamp)
    return conf_dir


def compile_lvgl_runner() -> Path:
    """sleep_lvgl_tests.cpp + the firmware's src/cc_sleep_lcd.h against a real LVGL display (FW-BUG-016)."""
    conf_dir = build_lvgl()
    cl, env = msvc_env()
    exe = out_dir / 'sleep_lvgl_tests.exe'
    subprocess.run([
        str(cl), '/nologo', '/EHsc', '/std:c++14', '/W4', '/WX', '/O2', '/D_CRT_SECURE_NO_WARNINGS',
        '/DLV_CONF_INCLUDE_SIMPLE', '/DLV_LVGL_H_INCLUDE_SIMPLE', '/external:W0',
        f'/external:I{conf_dir}', f'/external:I{LVGL}', f'/I{src}', str(root / 'sleep_lvgl_tests.cpp'),
        f'/Fo{out_dir}\\', f'/Fe{exe}', '/link', str(lvgl_dir / 'lvgl.lib'),
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
    # FW-BUG-017: the one write outside the gate is cc_lvgl_layout_halt()'s full backlight for the mixed lv_conf.h
    # error screen, which runs before any sleep state and never returns (lcd_thread_tests.py pins its body).
    halt = re.search(r'static void cc_lvgl_layout_halt\(\) \{[^{}]*?ledcWrite\(LEDC_CH_LCD_BKL, LEDC_MAX_BLK\); '
                     r'while \(1\) \{ cc_wdt_feed\(\); vTaskDelay\(1000 / portTICK_PERIOD_MS\); \} \}', lcd)
    if not halt:
        raise SystemExit('FAIL: lcd_thread.cpp: cc_lvgl_layout_halt() holds the backlight on and never returns')
    gated = lcd[:halt.start()] + lcd[halt.end():]
    if gated.count('ledcWrite(') != 1:
        raise SystemExit('FAIL: lcd_thread.cpp: every backlight write must go through lcd_backlight_apply()')
    count += 1
    need(lcd, r'static void lcd_backlight_apply\(\) \{ const uint16_t duty = cc_sleep_duty\(lcd_sleep_gate\.backlightState\('
              r'cc_sleep_state\(\)\), blk_wanted\); if \(static_cast<int32_t>\(duty\) != blk_written\) \{ '
              r'ledcWrite\(LEDC_CH_LCD_BKL, duty\);',
         'lcd_thread.cpp: the one backlight write is cc_sleep_duty() of the wanted duty, dark until the wake refresh')
    # FW-BUG-016: nothing drawn while asleep. Every immediate refresh goes through lcd_refr_now() (a no-op while
    # dark), except the one wake refresh; the refresh timer is paused on sleep and resumed on the wake, and the
    # wake refresh (whole screen, on glass) runs after the pass's render and before the backlight returns.
    need(lcd, r'static void lcd_refr_now\(\) \{ if \(!lcd_sleep_gate\.dark\(\)\) lv_refr_now\(nullptr\); \}',
         'lcd_thread.cpp: lcd_refr_now() draws nothing while dark')
    if lcd.count('lv_refr_now(') != 2:
        raise SystemExit('FAIL: lcd_thread.cpp: every lv_refr_now() goes through lcd_refr_now() but the wake refresh')
    # FW-BUG-016 review: LVGL resumes the refresh timer on every invalidation, so the dark handling lives in
    # cc_sleep_lcd.h (invalidation off + the timer held paused while dark), proven against a real LVGL display by
    # sleep_lvgl_tests.cpp; here the loop must use exactly that code and nothing else may touch the timer.
    need(lcd, r'const uint8_t lcdSleepStep = cc_sleep_lcd_step\(lcd_sleep_lvgl, cc_sleep_state\(\)\); '
              r'cc_crumb_lcd\(CC_LCD_STEP_HOST\); render_host_frame\(\); if \(lcdSleepStep == CC_SLEEP_LCD_RESUME\) \{ '
              r'cc_sleep_lcd_dark\(lcd_sleep_lvgl, false\); if \(!app_on\) \{ cc_crumb_lcd\(CC_LCD_STEP_REFRESH\); '
              r'lv_obj_invalidate\(lv_screen_active\(\)\); lv_refr_now\(nullptr\); cc_panel_wait\(\); \} '
              r'lcd_sleep_gate\.refreshed\(\); \}.*?lv_timer_handler\(\); lcd_backlight_apply\(\);',
         'lcd_thread.cpp: dark for LVGL on sleep; on the wake render, refresh the whole screen, then the backlight')
    need(lcd, r'lv_display_t \* disp = lv_display_create\(TFT_WIDTH, TFT_HEIGHT\);.*?'
              r'cc_sleep_lcd_attach\(lcd_sleep_lvgl, disp, lcd_sleep_gate\);.*?while \(1\)',
         'lcd_thread.cpp: the REFR_REQUEST hold is attached after lv_display_create(), before the loop')
    for banned in ('lv_timer_pause(lv_display_get_refr_timer', 'lv_timer_resume(lv_display_get_refr_timer',
                   'lv_display_enable_invalidation('):
        if banned in lcd:
            raise SystemExit(f'FAIL: lcd_thread.cpp: {banned} outside cc_sleep_lcd.h')
    sleep_lcd = read('cc_sleep_lcd.h')
    need(sleep_lcd, r'if \(s->gate->dark\(\)\) lv_timer_pause\(lv_display_get_refr_timer\(s->disp\)\);',
         'cc_sleep_lcd.h: a refresh request while dark pauses the refresh timer again')
    need(sleep_lcd, r'lv_display_add_event_cb\(disp, cc_sleep_lcd_refr_request, LV_EVENT_REFR_REQUEST, &s\);',
         'cc_sleep_lcd.h: the hold is a REFR_REQUEST handler')
    need(sleep_lcd, r'if \(step == CC_SLEEP_LCD_PAUSE\) cc_sleep_lcd_dark\(s, true\);',
         'cc_sleep_lcd.h: the sleep edge turns LVGL dark')
    count += 2
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
              r'motor\.disable\(\); else if \(sleepStep\.action == CC_SLEEP_MOTOR_ENABLE\) \{ '
              r'if \(cc_motor_wake_enable\(motor\.motor_status == FOCMotorStatus::motor_ready\)\) motor\.enable\(\); '
              r'haptic\.reanchor\(\);',
         'foc_thread.cpp: disable / enable (a calibrated motor only, FW-BUG-030) + re-anchor from CCSleepFoc on the FOC task')
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
    lvgl_exe = compile_lvgl_runner()
    subprocess.run([str(lvgl_exe)], check=True)
    print(f'PASS: inactivity dim / sleep logic (cc_sleep.h) and {pinned} firmware wiring pin(s) '
          f'[{time.time() - started:.1f} s]')
    return 0


if __name__ == '__main__':
    sys.exit(main())
