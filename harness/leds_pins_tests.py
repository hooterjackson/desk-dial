"""LED lane source pins for firmware code the host harness cannot compile (hmi_thread.cpp needs FastLED/Arduino).
Python stdlib only; no device, no USB.

FW-BUG-039 (native_led_enable_false_is_dark): a profile's ledEnable:false (led_api.h led_enable) keeps the native
(profile) LEDs dark. HmiThread::nativeLeds() must, when !led_config.led_enable, fill the whole ring black and draw
the button pairs through nativeKeyLeds(), and leave before the idle animation / halvesPointer; nativeKeyLeds() must
give every button pair black when !led_config.led_enable. The default (led_enable = true) is unchanged.

Usage: python leds_pins_tests.py [path/to/hmi_thread.cpp]   (default: the firmware's src/hmi_thread.cpp)
Exit status is non-zero on any failure.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parent
firmware = root.parent / 'firmware'


def code(text: str) -> str:
    """The source without comments, whitespace collapsed."""
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    text = re.sub(r'//[^\n]*', ' ', text)
    return re.sub(r'\s+', ' ', text)


def body(src: str, name: str) -> str:
    """The body of `void HmiThread::<name>()` (brace matched)."""
    m = re.search(r'void HmiThread::' + name + r'\(\)\s*\{', src)
    if not m:
        raise SystemExit(f'FAIL: HmiThread::{name}() not found')
    depth, i = 1, m.end()
    while depth and i < len(src):
        depth += {'{': 1, '}': -1}.get(src[i], 0)
        i += 1
    return src[m.end():i - 1]


def native_led_enable_false_is_dark(src: str) -> list[str]:
    fails = []
    native = body(src, 'nativeLeds')
    gate = re.search(r'if \( ?!led_config\.led_enable ?\) ?\{(.*?)return; ?\}', native)
    if not gate:
        fails.append('nativeLeds(): no early `if (!led_config.led_enable) { ... return; }`')
    else:
        inner = gate.group(1)
        if not re.search(r'for \(int i = 0; i < NANO_LED_A_NUM; i\+\+\) leds\[i\] = CRGB::Black;', inner):
            fails.append('nativeLeds(): the disabled path must fill all NANO_LED_A_NUM ring LEDs CRGB::Black')
        if 'nativeKeyLeds();' not in inner:
            fails.append('nativeLeds(): the disabled path must draw the (dark) button pairs via nativeKeyLeds()')
        for later in ('IdleLeds(', 'halvesPointer('):
            pos = native.find(later)
            if pos != -1 and pos < gate.start():
                fails.append(f'nativeLeds(): {later} runs before the led_enable gate')
    keys = body(src, 'nativeKeyLeds')
    if not re.search(r'!led_config\.led_enable \? CRGB\(CRGB::Black\)', keys):
        fails.append('nativeKeyLeds(): a disabled profile must give every button pair CRGB::Black')
    return fails


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else firmware / 'src' / 'hmi_thread.cpp'
    src = code(path.read_text(encoding='utf-8', errors='replace'))
    fails = native_led_enable_false_is_dark(src)
    for f in fails:
        print(f'FAIL: FW-BUG-039 {f}')
    if fails:
        print(f'FAIL: leds pins ({len(fails)} failure(s)) in {path.name}')
        return 1
    print('PASS: leds pins: native_led_enable_false_is_dark (nativeLeds / nativeKeyLeds honour ledEnable)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
