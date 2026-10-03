#pragma once
// The LVGL side of CCSleepLcdGate (FW-BUG-016; LCD thread only, LVGL is not thread-safe). Header-only so the
// host test (harness/sleep_lvgl_tests.cpp, run by sleep_tests.py) drives this exact code against a
// real LVGL display.
//
// While the panel is dark nothing may be drawn or flushed. A one-shot lv_timer_pause() of the display refresh
// timer does not hold in LVGL 9: every invalidation and every layout change sends LV_EVENT_REFR_REQUEST, and
// LVGL's own display handler answers it with lv_timer_resume(refr_timer). So while dark:
//   * invalidation is switched off (lv_display_enable_invalidation): no area is collected, so a refresh that
//     does run finds nothing to draw and flushes nothing;
//   * a REFR_REQUEST handler registered after LVGL's own pauses the refresh timer again (layout changes still
//     request a refresh), so the timer never runs: no layout pass, no REFR_START, no flush.
// The wake pass turns invalidation back on and resumes the timer; the caller then invalidates the whole screen
// and refreshes it once (on glass) before the backlight returns (CCSleepLcdGate::backlightState()).
#include <lvgl.h>

#include "cc_sleep.h"

struct CCSleepLcd {
    lv_display_t* disp;
    CCSleepLcdGate* gate;
    bool invOff;  // this code holds one lv_display_enable_invalidation(false) on disp
};

inline void cc_sleep_lcd_refr_request(lv_event_t* e) {
    const CCSleepLcd* s = static_cast<const CCSleepLcd*>(lv_event_get_user_data(e));
    if (s->gate->dark()) lv_timer_pause(lv_display_get_refr_timer(s->disp));
}

// Once, after lv_display_create() (LVGL's own REFR_REQUEST handler is registered by it, so this one runs after).
inline void cc_sleep_lcd_attach(CCSleepLcd& s, lv_display_t* disp, CCSleepLcdGate& gate) {
    s.disp = disp;
    s.gate = &gate;
    s.invOff = false;
    lv_display_add_event_cb(disp, cc_sleep_lcd_refr_request, LV_EVENT_REFR_REQUEST, &s);
}

// Dark (true) or lit (false) for LVGL; idempotent, the invalidation counter is held at most once.
inline void cc_sleep_lcd_dark(CCSleepLcd& s, bool dark) {
    if (dark != s.invOff) {
        lv_display_enable_invalidation(s.disp, !dark);
        s.invOff = dark;
    }
    if (dark) lv_timer_pause(lv_display_get_refr_timer(s.disp));
    else lv_timer_resume(lv_display_get_refr_timer(s.disp));
}

// First thing of every LCD pass: advances the gate with the pass's sleep state; on the PAUSE edge LVGL goes
// dark. Returns the gate's step (CC_SLEEP_LCD_RESUME: the caller runs the wake refresh after the host frame).
inline uint8_t cc_sleep_lcd_step(CCSleepLcd& s, uint8_t state) {
    const uint8_t step = s.gate->step(state);
    if (step == CC_SLEEP_LCD_PAUSE) cc_sleep_lcd_dark(s, true);
    return step;
}
