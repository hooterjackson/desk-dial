// r4 wall events (design_handoff_nano_d_r4 README section 3.3 / 4.3): the FOC side counts every refused detent at
// a bound (the end-stop "wall"); the UI side (cc_display M13 wall stretch, cc_alive end-of-arc LEDs) compares the
// count with the one it last saw and plays one bounce per new hit, towards `cc_wall_dir()` (+1 past the end /
// max, -1 past the start / min). Single writer (the FOC thread, cc_wall_hit), any number of readers; header-only.
#pragma once

#include <stdint.h>

#if defined(ARDUINO)
#include <atomic>
#endif

namespace cc_wall_detail {
#if defined(ARDUINO)
inline std::atomic<uint32_t>& count() { static std::atomic<uint32_t> c{0}; return c; }
inline std::atomic<int8_t>& dir() { static std::atomic<int8_t> d{0}; return d; }
#else
inline volatile uint32_t& count() { static volatile uint32_t c = 0; return c; }
inline volatile int8_t& dir() { static volatile int8_t d = 0; return d; }
#endif
}  // namespace cc_wall_detail

// FOC thread: a detent was refused at a bound (dir +1 = past the end / max, -1 = past the start / min).
inline void cc_wall_hit(int8_t dir) {
    cc_wall_detail::dir() = dir >= 0 ? static_cast<int8_t>(1) : static_cast<int8_t>(-1);
    cc_wall_detail::count() = cc_wall_detail::count() + 1;
}
// UI side: the running hit count (compare with the last one seen) and the latest direction.
inline uint32_t cc_wall_count() { return cc_wall_detail::count(); }
inline int8_t cc_wall_dir() { return cc_wall_detail::dir(); }
