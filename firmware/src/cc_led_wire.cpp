#include "cc_led_wire.h"

size_t cc_led_encode(const uint8_t* bytes, size_t count, uint32_t* items, size_t capacity) {
    size_t written = 0;
    for (size_t i = 0; i < count && capacity - written >= CC_LED_ITEMS_PER_BYTE; ++i) {
        uint32_t value = bytes[i];
        for (size_t bit = 0; bit < CC_LED_ITEMS_PER_BYTE; ++bit) {
            items[written++] = (value & 0x80u) ? CC_LED_ITEM_ONE : CC_LED_ITEM_ZERO;
            value <<= 1;
        }
    }
    return written;
}
