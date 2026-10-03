// FW-BUG-016 (review): the LCD while asleep, against a real LVGL 9 display (the firmware's pinned LVGL, the
// firmware lv_conf.h). sleep_tests.py compiles this with MSVC and runs it.
//
// Drives the firmware's own src/cc_sleep_lcd.h with a loop shaped like lcd_thread.cpp's: every pass steps the
// gate, renders a changing host frame (label text, position, a flex child's width -> layout), presents some
// frames immediately (lcd_refr_now: skipped while dark), runs the wake refresh on RESUME and then
// lv_timer_handler(); an endless lv_anim runs throughout. A flush callback counts flushes and keeps a
// framebuffer.
//   1. Awake: flushes happen (the rig can see drawing at all).
//   2. Control: the previous form (a one-shot lv_timer_pause on the sleep edge) flushes while asleep, because
//      every invalidation resumes the refresh timer (LV_EVENT_REFR_REQUEST). The check must see that bug.
//   3. Fixed: 10 s asleep with the host animating: zero flushes, zero refresh starts, invalidation off.
//   4. Wake pass: the whole screen is flushed once, after the latest frame, and equals a fresh full redraw.
//   5. After the wake the refresh timer works again; a second sleep/wake cycle behaves the same, the
//      invalidation counter stays balanced; cc_sleep_lcd_dark() is idempotent.
#include "cc_sleep_lcd.h"

#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

namespace {
int failures = 0, checks = 0;

void expect(bool ok, const char* what, int line) {
    ++checks;
    if (!ok) {
        ++failures;
        std::printf("FAIL line %d: %s\n", line, what);
    }
}
#define EXPECT(cond) expect((cond), #cond, __LINE__)

constexpr int W = 240, H = 240, ROWS = 24;
constexpr uint32_t PASS_MS = 5;        // one LCD pass (vTaskDelay(1) plus the work)
constexpr uint32_t PERIOD_MS = 16;     // refresh and anim period (CC_LCD_PERIOD_MS order)

uint32_t now_ms = 1000;
uint32_t tick_cb() { return now_ms; }

struct Counters {
    int flushes = 0;
    long long flushedPx = 0;
    int refrStarts = 0;
};
Counters counters;
std::vector<uint16_t> fb(W * H, 0);
uint8_t draw_buf[W * ROWS * 2];

void flush_cb(lv_display_t* disp, const lv_area_t* area, uint8_t* px) {
    ++counters.flushes;
    counters.flushedPx += lv_area_get_size(area);
    const uint16_t* src = reinterpret_cast<const uint16_t*>(px);
    const int w = lv_area_get_width(area);
    for (int y = area->y1; y <= area->y2; ++y)
        std::memcpy(&fb[y * W + area->x1], src + (y - area->y1) * w, static_cast<size_t>(w) * 2);
    lv_display_flush_ready(disp);
}
void refr_start_cb(lv_event_t*) { ++counters.refrStarts; }

void anim_x(void* obj, int32_t v) { lv_obj_set_y(static_cast<lv_obj_t*>(obj), v); }

enum Mode { OLD_ONE_SHOT, FIXED };

struct Rig {
    lv_display_t* disp;
    lv_obj_t* label;
    lv_obj_t* box;
    lv_obj_t* child;
    CCSleepLcdGate gate;
    CCSleepLcd lcd;
    Mode mode;
    int frame;
    std::string latest;
    bool wakeImageMatches;  // the wake refresh's image equals a fresh full redraw at that moment
};

void rig_create(Rig& r, Mode mode) {
    r.mode = mode;
    r.frame = 0;
    r.disp = lv_display_create(W, H);
    lv_display_set_default(r.disp);
    lv_display_set_flush_cb(r.disp, flush_cb);
    lv_display_set_buffers(r.disp, draw_buf, nullptr, sizeof(draw_buf), LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_timer_set_period(lv_display_get_refr_timer(r.disp), PERIOD_MS);
    lv_timer_set_period(lv_anim_get_timer(), PERIOD_MS);
    lv_display_add_event_cb(r.disp, refr_start_cb, LV_EVENT_REFR_START, nullptr);
    if (mode == FIXED) cc_sleep_lcd_attach(r.lcd, r.disp, r.gate);

    lv_obj_t* scr = lv_screen_active();
    lv_obj_set_style_bg_color(scr, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);
    r.label = lv_label_create(scr);
    lv_obj_set_style_text_color(r.label, lv_color_white(), 0);
    lv_obj_align(r.label, LV_ALIGN_CENTER, 0, 0);
    r.box = lv_obj_create(scr);
    lv_obj_set_size(r.box, 200, 40);
    lv_obj_align(r.box, LV_ALIGN_BOTTOM_MID, 0, -20);
    lv_obj_set_flex_flow(r.box, LV_FLEX_FLOW_ROW);
    r.child = lv_obj_create(r.box);
    lv_obj_set_size(r.child, 20, 20);
    lv_obj_t* dot = lv_obj_create(scr);
    lv_obj_set_size(dot, 12, 12);
    lv_obj_set_x(dot, 30);
    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, dot);
    lv_anim_set_exec_cb(&a, anim_x);
    lv_anim_set_values(&a, 10, 200);
    lv_anim_set_duration(&a, 900);
    lv_anim_set_playback_duration(&a, 900);
    lv_anim_set_repeat_count(&a, LV_ANIM_REPEAT_INFINITE);
    lv_anim_start(&a);
    // Initial draw.
    lv_refr_now(r.disp);
}

void rig_delete(Rig& r) {
    lv_anim_delete_all();
    lv_display_delete(r.disp);
}

// The host frame of this pass (render_host_frame()): changed text, position, a layout change.
void render_host_frame(Rig& r) {
    ++r.frame;
    char text[32];
    std::snprintf(text, sizeof(text), "frame %d", r.frame);
    r.latest = text;
    lv_label_set_text(r.label, text);
    lv_obj_set_x(r.label, r.frame % 40 - 20);
    lv_obj_set_width(r.child, 10 + r.frame % 60);
    // A non-animated change presented at once (cc_display lastChanged -> lcd_refr_now()).
    if (r.frame % 4 == 0 && !r.gate.dark()) lv_refr_now(nullptr);
}

// One pass of lcd_thread.cpp's loop (app canvas down).
void pass(Rig& r, uint8_t state) {
    uint8_t step;
    if (r.mode == FIXED) {
        step = cc_sleep_lcd_step(r.lcd, state);
    } else {
        step = r.gate.step(state);
        if (step == CC_SLEEP_LCD_PAUSE) lv_timer_pause(lv_display_get_refr_timer(r.disp));
    }
    render_host_frame(r);
    if (step == CC_SLEEP_LCD_RESUME) {
        if (r.mode == FIXED) cc_sleep_lcd_dark(r.lcd, false);
        else lv_timer_resume(lv_display_get_refr_timer(r.disp));
        lv_obj_invalidate(lv_screen_active());
        lv_refr_now(nullptr);
        r.gate.refreshed();
        // The image on glass after the wake refresh equals a fresh full redraw of the current tree (same tick).
        const std::vector<uint16_t> woke = fb;
        lv_obj_invalidate(lv_screen_active());
        lv_refr_now(nullptr);
        r.wakeImageMatches = woke == fb;
    }
    lv_timer_handler();
    now_ms += PASS_MS;
}

int run(Rig& r, uint8_t state, int passes) {
    const int before = counters.flushes;
    for (int i = 0; i < passes; ++i) pass(r, state);
    return counters.flushes - before;
}

void control_old_form() {
    Rig r;
    rig_create(r, OLD_ONE_SHOT);
    EXPECT(run(r, CC_SLEEP_AWAKE, 200) > 0);
    const int asleep = run(r, CC_SLEEP_ASLEEP, 2000);
    std::printf("control (one-shot pause): %d flushes in 10 s asleep\n", asleep);
    EXPECT(asleep > 0);  // the reviewer's finding: the old form keeps drawing while dark
    run(r, CC_SLEEP_AWAKE, 1);
    rig_delete(r);
}

void sleep_cycle(Rig& r, int cycle) {
    std::printf("cycle %d\n", cycle);
    EXPECT(run(r, CC_SLEEP_AWAKE, 200) > 0);
    EXPECT(lv_display_is_invalidation_enabled(r.disp));

    // Asleep with the host animating: nothing drawn or flushed, not even a refresh start, for 10 s.
    counters.refrStarts = 0;
    const int asleep = run(r, CC_SLEEP_ASLEEP, 2000);
    std::printf("  asleep: %d flushes, %d refresh starts in 10 s\n", asleep, counters.refrStarts);
    EXPECT(asleep == 0);
    EXPECT(counters.refrStarts == 0);
    EXPECT(r.gate.dark());
    EXPECT(!lv_display_is_invalidation_enabled(r.disp));
    EXPECT(lv_timer_get_paused(lv_display_get_refr_timer(r.disp)));
    // A direct invalidation or a layout change while dark must not restart the refresh timer.
    lv_obj_invalidate(lv_screen_active());
    lv_obj_set_width(r.child, 33);  // layout change: LV_EVENT_REFR_REQUEST without an invalid area
    EXPECT(lv_timer_get_paused(lv_display_get_refr_timer(r.disp)));
    lv_timer_handler();
    EXPECT(counters.refrStarts == 0);

    // The wake pass: the latest frame, then one whole-screen refresh.
    const long long pxBefore = counters.flushedPx;
    r.wakeImageMatches = false;
    const int wake = run(r, CC_SLEEP_AWAKE, 1);
    EXPECT(wake > 0);
    EXPECT(counters.flushedPx - pxBefore >= static_cast<long long>(W) * H);
    EXPECT(!r.gate.dark());
    EXPECT(lv_display_is_invalidation_enabled(r.disp));
    EXPECT(r.latest == lv_label_get_text(r.label));
    EXPECT(r.wakeImageMatches);

    // Awake again: the refresh timer draws changed frames.
    EXPECT(run(r, CC_SLEEP_AWAKE, 200) > 0);
}

void fixed_form() {
    Rig r;
    rig_create(r, FIXED);
    sleep_cycle(r, 1);
    sleep_cycle(r, 2);
    // Idempotent: the invalidation counter is held at most once.
    cc_sleep_lcd_dark(r.lcd, true);
    cc_sleep_lcd_dark(r.lcd, true);
    EXPECT(!lv_display_is_invalidation_enabled(r.disp));
    cc_sleep_lcd_dark(r.lcd, false);
    EXPECT(lv_display_is_invalidation_enabled(r.disp));
    cc_sleep_lcd_dark(r.lcd, false);
    EXPECT(lv_display_is_invalidation_enabled(r.disp));
    lv_obj_invalidate(lv_screen_active());
    EXPECT(!lv_timer_get_paused(lv_display_get_refr_timer(r.disp)));
    rig_delete(r);
}
}  // namespace

int main() {
    lv_init();
    lv_tick_set_cb(tick_cb);
    control_old_form();
    fixed_form();
    std::printf("%s: %d checks, %d failures (LCD asleep against LVGL)\n", failures ? "FAIL" : "PASS", checks, failures);
    return failures ? 1 : 0;
}
