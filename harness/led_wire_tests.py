"""1.0.0-cc5.2 LED wire encoder checks. Python stdlib + MSVC only; no device, no USB.

1. Runs cpp11_gate.py: every shared unit (cc_led_wire.cpp included) must compile in the
   device's gnu++11, and the firmware source rules must hold (no FastLED clockless
   controller, no other RMT user).
2. Compiles led_wire_tests.cpp with the unchanged firmware unit cc_led_wire.cpp (MSVC /W4
   /WX) and runs it: the RMT item words equal FastLED 3.6.0's WS2811 mOne/mZero recomputed
   from FastLED's formulas; MSB first, 8 items per byte, whole bytes only.
3. Cross-checks the runner's pseudo-random frames (build/led-wire-tests/led_wire_actual.jsonl)
   against this script's own encoder, written from the WS2811 timing alone.
4. 1.0.0-cc5.4 (ALIVE.md section 9 step 5): the wire carries the alive engine's bytes q exactly.
   The runner (linked with the unchanged cc_alive.cpp and cc_lights.cpp) re-types FastLED 3.6.0's
   output stage and proves wire == q at brightness 255 with FastLED's dithering disabled, for
   every byte value, both colour orders, every orientation and the real engine's frames. This
   script pins what that proof rests on: every FastLED line the runner re-types, in
   .pio/libdeps/nanofoc_d/FastLED (version 3.6.0); the firmware's LED setup (no colour
   correction, temperature or power limit anywhere in src/, ring RGB and buttons GRB); and the
   hmi_thread.cpp lines the runner mirrors (brightness 255 and DISABLE_DITHER before the one
   FastLED.show(), the ring write through cc_ring_address(), the button pairs).

Exit status is non-zero on any mismatch.
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
out_dir = root / 'build' / 'led-wire-tests'
fastled_src = firmware / '.pio' / 'libdeps' / 'nanofoc_d' / 'FastLED' / 'src'

# Part 4: the FastLED 3.6.0 source lines led_wire_tests.cpp re-types (file -> exact snippets).
FASTLED_PINS = {
    'fastled_config.h': ['#define FASTLED_SCALE8_FIXED 1'],
    'lib8tion/scale8.h': ['return (((uint16_t)i) * (1+(uint16_t)(scale))) >> 8;'],
    'lib8tion/math8.h': ['unsigned int t = i + j;', 'if( t > 255) t = 255;'],
    # The ESP32-S3 (Xtensa) is neither __arm__ nor __AVR__: lib8tion's C fallback.
    'lib8tion.h': ['#if defined(__arm__)', '#elif defined(__AVR__)', '// unspecified architecture, so',
                   '#define SCALE8_C 1', '#define QADD8_C 1'],
    'color.h': ['UncorrectedColor=0xFFFFFF', 'UncorrectedTemperature=0xFFFFFF'],
    'pixeltypes.h': ['RGB=0012,', 'GRB=0102,', ': r((colorcode >> 16) & 0xFF), g((colorcode >> 8) & 0xFF), '
                     'b((colorcode >> 0) & 0xFF)'],
    'controller.h': [
        '#define RO(X) RGB_BYTE(RGB_ORDER, X)', '#define RGB_BYTE(RO,X) (((RO)>>(3*(2-(X)))) & 0x3)',
        '#define DISABLE_DITHER 0x00', '#define BINARY_DITHER 0x01',
        'm_ColorCorrection(UncorrectedColor), m_ColorTemperature(UncorrectedTemperature), m_DitherMode(BINARY_DITHER)',
        'show(m_Data, m_nLeds, getAdjustment(brightness));',
        'return computeAdjustment(scale, m_ColorCorrection, m_ColorTemperature);',
        'uint32_t work = (((uint32_t)cc)+1) * (((uint32_t)ct)+1) * scale;', 'work /= 0x10000L;',
        'adj.raw[i] = work & 0xFF;',
        'PixelController<RGB_ORDER, LANES, MASK> pixels(data, nLeds < 0 ? -nLeds : nLeds, scale, getDither());',
        'case BINARY_DITHER: init_binary_dithering(); break;',
        'default: d[0]=d[1]=d[2]=e[0]=e[1]=e[2]=0; break;',
        '#define MAX_LIKELY_UPDATE_RATE_HZ     400', '#define MIN_ACCEPTABLE_DITHER_RATE_HZ  50',
        'e[i] = s ? (256/s) + 1 : 0;', 'd[i] = scale8(Q, e[i]);', 'if(d[i]) (--d[i]);', 'if(e[i]) --e[i];',
        'return b ? qadd8(b, pc.d[RO(SLOT)]) : 0;', 'return scale8(b, pc.mScale.raw[RO(SLOT)]);',
        'return scale<SLOT>(pc, pc.dither<SLOT>(pc, pc.loadByte<SLOT>(pc)));',
        'd[0] = e[0] - d[0];',
    ],
    'FastLED.h': ['void show() { show(m_Scale); }', 'void setBrightness(uint8_t scale) { m_Scale = scale; }'],
    'FastLED.cpp': ['if(m_pPowerFunc) {', 'if(m_nFPS < 100) { pCur->setDither(0); }', 'pCur->showLeds(scale);',
                    'pCur->setDither(ditherMode);'],
}
# Part 4: hmi_thread.cpp lines the runner mirrors (the write-out and the engine frame's show).
HMI_PINS = [
    'constexpr uint8_t kKeyLedPairs[4][2] = {{3, 4}, {2, 5}, {1, 6}, {0, 7}};',
    'CCLedController<RGB, NANO_LED_A_NUM> ringLeds(ringStrip);',
    'CCLedController<LED_COL_ORDER, NANO_LED_B_NUM> buttonLeds(buttonStrip);',
    'leds[cc_ring_address(i, orientation)] = CRGB(cc_light_ring[i]);',
    'const CRGB color(cc_light_buttons[cc_physical_button(i)]);',
    'ledsp[kKeyLedPairs[i][0]] = ledsp[kKeyLedPairs[i][1]] = color;',
]

# WS2811 on the RMT at 40 MHz (25 ns ticks): FastLED's 320/320/640 ns chipset timing gives
# a one of 625 ns high + 625 ns low and a zero of 300 ns high + 950 ns low.
TICK_NS = 25
ONE_NS, ZERO_NS = (625, 625), (300, 950)


def item(high_ns, low_ns):
    """rmt_item32_t word: duration0 (15 bits), level0 = 1, duration1 (15 bits), level1 = 0."""
    return (high_ns // TICK_NS) | (1 << 15) | ((low_ns // TICK_NS) << 16)


def encode(data):
    return [item(*(ONE_NS if (byte >> bit) & 1 else ZERO_NS)) for byte in data for bit in range(7, -1, -1)]


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
    exe = out_dir / 'led_wire_tests.exe'
    subprocess.run([
        str(cl), '/nologo', '/EHsc', '/std:c++14', '/W4', '/WX', '/O2', '/D_CRT_SECURE_NO_WARNINGS',
        f'/I{firmware / "src"}',
        str(root / 'led_wire_tests.cpp'), str(firmware / 'src' / 'cc_led_wire.cpp'),
        str(firmware / 'src' / 'cc_alive.cpp'), str(firmware / 'src' / 'cc_lights.cpp'),
        f'/Fo{out_dir}\\', f'/Fe{exe}',
    ], cwd=out_dir, env=env, check=True)
    return exe


def cross_check(actual: Path) -> int:
    lines = actual.read_text(encoding='utf-8').splitlines()
    if len(lines) != 200:
        raise SystemExit(f'FAIL: expected 200 frames from the runner, got {len(lines)}')
    bits = 0
    for number, line in enumerate(lines):
        frame = json.loads(line)
        if frame['items'] != encode(frame['bytes']):
            raise SystemExit(f'FAIL: frame {number}: C++ items differ from the independent encoder')
        bits += len(frame['items'])
    return bits


def code(text: str) -> str:
    """C/C++ source without comments (block and line), so a pin never matches a comment."""
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    return re.sub(r'//[^\n]*', '', text)


def pins() -> int:
    """Part 4's premises, as source text: FastLED 3.6.0 re-typed lines, the firmware LED setup and
    the hmi_thread.cpp lines the runner mirrors. Returns the number of pins checked."""
    count = 0
    library = json.loads((fastled_src.parent / 'library.json').read_text(encoding='utf-8'))
    if library.get('version') != '3.6.0':
        raise SystemExit(f'FAIL: FastLED is {library.get("version")}, the wire proof re-types 3.6.0')
    for name, snippets in FASTLED_PINS.items():
        text = (fastled_src / name).read_text(encoding='utf-8', errors='replace')
        for snippet in snippets:
            if snippet not in text:
                raise SystemExit(f'FAIL: FastLED {name} no longer has: {snippet}')
            count += 1
    nanofoc = code((firmware / 'include' / 'nanofoc_d.h').read_text(encoding='utf-8', errors='replace'))
    if not re.search(r'#define\s+LED_COL_ORDER\s+GRB\b', nanofoc):
        raise SystemExit('FAIL: include/nanofoc_d.h: LED_COL_ORDER is not GRB (the runner models buttons as GRB)')
    count += 1
    # Nothing in the firmware changes FastLED's colour adjustment or its scale (power limiting).
    for path in sorted((firmware / 'src').rglob('*.[ch]*')):
        text = code(path.read_text(encoding='utf-8', errors='replace'))
        for call in ('setCorrection', 'setTemperature', 'setMaxPowerInVoltsAndMilliamps', 'setMaxPowerInMilliWatts'):
            if re.search(rf'\b{call}\s*\(', text):
                raise SystemExit(f'FAIL: src/{path.name} calls FastLED {call}(): the wire proof assumes the defaults')
        count += 1
    hmi = code((firmware / 'src' / 'hmi_thread.cpp').read_text(encoding='utf-8', errors='replace'))
    for snippet in HMI_PINS:
        if snippet not in hmi:
            raise SystemExit(f'FAIL: hmi_thread.cpp no longer has: {snippet}')
        count += 1
    # The engine frame: brightness 255 and DISABLE_DITHER, then the one FastLED.show().
    if hmi.count('FastLED.show();') != 1:
        raise SystemExit('FAIL: hmi_thread.cpp must have exactly one FastLED.show()')
    start = hmi.find('renderUs = renderAlive(')
    engine = hmi[start:hmi.index('FastLED.show();')] if start >= 0 else ''
    if not re.search(r'FastLED\.setBrightness\(255\);\s*FastLED\.setDither\(DISABLE_DITHER\);', engine):
        raise SystemExit('FAIL: hmi_thread.cpp: the engine frame must set brightness 255 and DISABLE_DITHER '
                         'between renderAlive() and FastLED.show()')
    count += 2
    return count


def main() -> int:
    started = time.time()
    assert item(*ONE_NS) == 0x00198019 and item(*ZERO_NS) == 0x0026800C, 'independent item words'
    pinned = pins()
    subprocess.run([sys.executable, str(root / 'cpp11_gate.py')], check=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    exe = compile_runner()
    actual = out_dir / 'led_wire_actual.jsonl'
    subprocess.run([str(exe), str(actual)], check=True)
    bits = cross_check(actual)
    print(f'PASS: alive wire == q at FastLED brightness 255 (DISABLE_DITHER); {pinned} source pin(s) '
          f'(FastLED 3.6.0, firmware LED setup, hmi_thread.cpp write-out)')
    print(f'PASS: cc_led_encode == independent WS2811 encoder over 200 pseudo-random frames ({bits} bits) '
          f'[{time.time() - started:.1f} s]')
    return 0


if __name__ == '__main__':
    sys.exit(main())
