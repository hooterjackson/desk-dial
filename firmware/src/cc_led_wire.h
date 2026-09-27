#pragma once
#include <stddef.h>
#include <stdint.h>

// WS2811 wire encoding for the LED transport (1.0.0-cc5.2). Platform-neutral: no
// Arduino, FastLED or ESP-IDF includes. Compiled unchanged by the firmware, by
// harness/led_wire_tests.py (MSVC /W4 /WX) and by cpp11_gate.py (gnu++11).
//
// One RMT item encodes one data bit: `high` ticks at level 1, then `low` ticks at
// level 0 (the ESP32-S3 rmt_item32_t layout: duration0:15, level0:1, duration1:15,
// level1:1). The RMT channel clock is APB 80 MHz / CC_LED_RMT_CLK_DIV = 40 MHz, one
// tick 25 ns. The tick counts are exactly what FastLED 3.6.0's clockless RMT driver
// produced for `WS2811` (WS2811Controller800Khz: T1 = T2 = C_NS(320) = 77, T3 =
// C_NS(640) = 154 CPU cycles at 240 MHz, divided by 6 CPU cycles per RMT tick):
//   one  = T1+T2 high, T3 low    = 25 / 25 ticks = 625 / 625 ns
//   zero = T1 high,    T2+T3 low = 12 / 38 ticks = 300 / 950 ns
// 50 ticks = 1.25 us per bit. Bytes go out MSB first, in the order FastLED's
// PixelController produced them (colour order already applied).

constexpr uint32_t CC_LED_RMT_CLK_DIV = 2;
constexpr uint32_t CC_LED_ONE_HIGH_TICKS = 25;
constexpr uint32_t CC_LED_ONE_LOW_TICKS = 25;
constexpr uint32_t CC_LED_ZERO_HIGH_TICKS = 12;
constexpr uint32_t CC_LED_ZERO_LOW_TICKS = 38;
constexpr size_t CC_LED_ITEMS_PER_BYTE = 8;

// One RMT item word: `high` ticks at level 1, then `low` ticks at level 0.
constexpr uint32_t cc_led_rmt_item(uint32_t high, uint32_t low) {
    return (high & 0x7FFFu) | (1u << 15) | ((low & 0x7FFFu) << 16);
}

constexpr uint32_t CC_LED_ITEM_ONE = cc_led_rmt_item(CC_LED_ONE_HIGH_TICKS, CC_LED_ONE_LOW_TICKS);
constexpr uint32_t CC_LED_ITEM_ZERO = cc_led_rmt_item(CC_LED_ZERO_HIGH_TICKS, CC_LED_ZERO_LOW_TICKS);

// Encodes whole bytes into `items` (8 per byte, MSB first) while they fit in
// `capacity` items; returns the number of items written (a multiple of 8). A byte
// that does not fit is not started, so the result never ends mid-byte.
size_t cc_led_encode(const uint8_t* bytes, size_t count, uint32_t* items, size_t capacity);
