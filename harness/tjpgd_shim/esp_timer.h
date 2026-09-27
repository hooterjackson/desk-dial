#pragma once
// Host shim for ESP-IDF's esp_timer_get_time() (microseconds since start, int64_t), used by
// src/cc_jpeg.cpp for the decode duration. See esp_rom_tjpgd.h in this directory.
#include <stdint.h>
#include <chrono>

inline int64_t esp_timer_get_time() {
    return static_cast<int64_t>(std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count());
}
