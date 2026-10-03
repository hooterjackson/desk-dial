// LCD thread decisions against a real LVGL 9 display (the firmware's pinned LVGL, the firmware lv_conf.h).
// lcd_thread_tests.py compiles this with MSVC and runs it. It drives the firmware's own src/cc_lcd_logic.h the way
// lcd_thread.cpp does; a flush callback counts what reaches the "panel".
//
// FW-PERF-009 native_rest_is_still: lcd_manager (a 1 s LVGL timer) on the value screen with an unchanged native
//   profile. Control (the old form, every run re-sets name and description): the panel is redrawn every second.
//   Gated (CCLcdManagerGate): 10 s at rest flush nothing; a new LcdCommand reaches the panel within 1 s.
// FW-BUG-043 claim_during_boot_splash_hands_back_to_value_screen: the boot splash's SCREEN_LOADED handler schedules
//   the 330 ms fade to the value screen after 3300 ms (ui.c ui_event_bootimg). Desk Dial claims 1 s into the splash
//   and later releases. Control (the old handback, the previous screen): the splash is back with the fade pending,
//   "DESK DIAL IS BOOTING..." for about 3.6 s. Fixed (cc_handback_screen): the value screen at once, nothing pending.
// FW-PUB-006 cal_cue_over_boot_screens: the FOC task posts CC_MOTOR_CAL_ALIGNING (cc_boot_cal.h) for the first-boot
//   alignment (1 s settle + sweep), across the boot splash's fade to the value screen. The cue runs the firmware's
//   own cal_cue_apply() (lcd_thread_tests.py copies it verbatim out of lcd_thread.cpp into cal_cue_fw.inc) with the
//   firmware's font: "Calibrating - hands off" reaches the panel on the first pass, stays over both screens, sits
//   inside the round panel, goes when the alignment ends, shows again for the FW-BUG-030 retry (the same object),
//   and nothing is redrawn at rest.
// FW-BUG-030 cal_failed_cue: a failed alignment (CC_MOTOR_CAL_FAILED) turns the same label into "Calibration failed -
//   replug", inside the round panel, held without redraws; the retry's ALIGNING turns it back into "hands off", and a
//   READY afterwards hides it.
#include "cc_lcd_logic.h"
#include "cc_boot_cal.h"

#include <lvgl.h>

#include <cstdio>
#include <cstring>

extern "C" {
LV_FONT_DECLARE(ui_font_SGK100h16)   // src/fonts/ui_font_SGK100h16.c (compiled as C)
}
namespace fw {
#include "cal_cue_fw.inc"            // lcd_thread.cpp: cal_cue, cal_cue_label, cal_cue_apply() (generated copy)
}  // namespace fw

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
constexpr uint32_t PASS_MS = 5;
constexpr uint32_t PERIOD_MS = 12;   // binary F's refresh period

uint32_t now_ms = 1000;
uint32_t tick_cb() { return now_ms; }

int flushes = 0;
uint8_t draw_buf[W * ROWS * 2];

void flush_cb(lv_display_t* disp, const lv_area_t*, uint8_t*) {
    ++flushes;
    lv_display_flush_ready(disp);
}

lv_display_t* make_display() {
    lv_display_t* disp = lv_display_create(W, H);
    lv_display_set_default(disp);
    lv_display_set_flush_cb(disp, flush_cb);
    lv_display_set_buffers(disp, draw_buf, nullptr, sizeof(draw_buf), LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_timer_set_period(lv_display_get_refr_timer(disp), PERIOD_MS);
    lv_timer_set_period(lv_anim_get_timer(), PERIOD_MS);
    return disp;
}

// Passes of the LCD loop (lv_timer_handler every PASS_MS) for `ms`; returns the flushes.
int run_ms(uint32_t ms) {
    const int before = flushes;
    for (uint32_t t = 0; t < ms; t += PASS_MS) {
        lv_timer_handler();
        now_ms += PASS_MS;
    }
    return flushes - before;
}

// ------------------------------------------------------------------------------------------- FW-PERF-009 --
struct Manager {
    lv_obj_t* valueScreen;
    lv_obj_t* name;
    lv_obj_t* desc;
    bool gated;
    CCLcdManagerGate gate;
    uint32_t seq;          // handleLcdCommand()'s count
    char title[48];
    char data1[96];
    int blockRuns;
};
Manager mgr;

// lcd_manager's value-screen block (lcd_thread.cpp), name and description (the modal stays empty here).
void manager_cb(lv_timer_t*) {
    Manager& m = mgr;
    if (m.gated && !cc_lcd_manager_due(m.gate, lv_screen_active() == m.valueScreen, m.seq, false)) return;
    if (lv_screen_active() == m.valueScreen) {
        ++m.blockRuns;
        lv_obj_remove_flag(m.name, LV_OBJ_FLAG_HIDDEN);
        lv_label_set_text_fmt(m.name, "%s", m.title);
        lv_obj_remove_flag(m.desc, LV_OBJ_FLAG_HIDDEN);
        lv_label_set_text_fmt(m.desc, "%s", m.data1);
    }
    if (m.gated) cc_lcd_manager_applied(m.gate, m.seq);
}

void command(const char* title, const char* data1) {
    std::snprintf(mgr.title, sizeof(mgr.title), "%s", title);
    std::snprintf(mgr.data1, sizeof(mgr.data1), "%s", data1);
    ++mgr.seq;
}

void native_rest(bool gated) {
    lv_display_t* disp = make_display();
    std::memset(&mgr, 0, sizeof(mgr));
    mgr.gated = gated;
    mgr.valueScreen = lv_screen_active();
    lv_obj_set_style_bg_color(mgr.valueScreen, lv_color_black(), 0);
    mgr.name = lv_label_create(mgr.valueScreen);
    lv_obj_set_width(mgr.name, lv_pct(78));
    lv_label_set_long_mode(mgr.name, LV_LABEL_LONG_DOT);   // as ui_valueScreen.c's ui_profileName
    lv_obj_align(mgr.name, LV_ALIGN_CENTER, 0, 41);
    lv_obj_add_flag(mgr.name, LV_OBJ_FLAG_HIDDEN);
    mgr.desc = lv_label_create(mgr.valueScreen);
    lv_obj_set_width(mgr.desc, 150);
    lv_obj_align(mgr.desc, LV_ALIGN_CENTER, 0, 70);
    lv_obj_add_flag(mgr.desc, LV_OBJ_FLAG_HIDDEN);
    command("A PROFILE NAME LONG ENOUGH TO BE CUT WITH DOTS", "Detents, 67 a turn");
    lv_timer_t* t = lv_timer_create(manager_cb, 1000, nullptr);
    lv_timer_ready(t);
    lv_refr_now(disp);
    run_ms(2000);                                   // the first application and its redraw
    const int rest = run_ms(10000);
    const int runs = mgr.blockRuns;
    std::printf("native rest (%s): %d flushes in 10 s, %d block runs\n", gated ? "gated" : "control", rest, runs);
    if (!gated) {
        EXPECT(rest >= 9);                          // the finding: redrawn once a second with nothing changed
    } else {
        EXPECT(rest == 0);                          // lcdFps 0, lcdFlushUs 0 at rest
        EXPECT(runs == 1);
        command("ANOTHER", "Changed");              // a new LcdCommand: on glass within 1 s
        const int changed = run_ms(1000);
        EXPECT(changed > 0);
        EXPECT(std::strcmp(lv_label_get_text(mgr.desc), "Changed") == 0);
        EXPECT(run_ms(5000) == 0);                  // and still again afterwards
        // A command while another screen is up is applied when the value screen returns.
        lv_obj_t* other = lv_obj_create(nullptr);
        lv_screen_load(other);
        command("THIRD", "Later");
        run_ms(2000);
        EXPECT(std::strcmp(lv_label_get_text(mgr.desc), "Changed") == 0);
        lv_screen_load(mgr.valueScreen);
        run_ms(1100);
        EXPECT(std::strcmp(lv_label_get_text(mgr.desc), "Later") == 0);
        lv_obj_delete(other);
    }
    lv_timer_delete(t);
    lv_display_delete(disp);
}

// ------------------------------------------------------------------------------------------- FW-BUG-043 --
lv_obj_t* splash_target = nullptr;
void splash_event(lv_event_t* e) {
    // ui.c ui_event_bootimg -> _ui_screen_change(&ui_valueScreen, LV_SCR_LOAD_ANIM_FADE_OUT, 330, 3300, ...)
    if (lv_event_get_code(e) == LV_EVENT_SCREEN_LOADED)
        lv_screen_load_anim(splash_target, LV_SCR_LOAD_ANIM_FADE_OUT, 330, 3300, false);
}

void claim_during_splash(bool fixed) {
    lv_display_t* disp = make_display();
    lv_obj_t* splash = lv_obj_create(nullptr);
    lv_obj_t* value = lv_obj_create(nullptr);
    lv_obj_t* host = lv_obj_create(nullptr);
    splash_target = value;
    lv_obj_add_event_cb(splash, splash_event, LV_EVENT_ALL, nullptr);
    lv_screen_load(splash);                          // ui_init(): lv_disp_load_scr(ui_bootimg)
    run_ms(1000);
    EXPECT(lv_screen_active() == splash);
    lv_obj_t* previous = lv_screen_active();         // render_host_frame(): entering
    lv_screen_load(host);
    run_ms(2000);
    EXPECT(lv_screen_active() == host);              // the pending splash fade does not take the host screen away
    lv_obj_t* back = fixed ? cc_handback_screen(previous, splash, value) : (previous ? previous : value);
    lv_screen_load(back);                            // hand_back()
    run_ms(PASS_MS);
    lv_obj_t* first = lv_screen_active();
    int splashMs = 0;
    for (uint32_t t = 0; t < 6000; t += PASS_MS) {
        if (lv_screen_active() == splash) splashMs += static_cast<int>(PASS_MS);
        run_ms(PASS_MS);
    }
    std::printf("claim during splash (%s): splash shown %d ms after the handback\n", fixed ? "fixed" : "control",
                splashMs);
    if (!fixed) {
        EXPECT(first == splash);                     // the finding
        EXPECT(splashMs >= 3300);
    } else {
        EXPECT(first == value);
        EXPECT(splashMs == 0);
        EXPECT(lv_screen_active() == value);
        EXPECT(lv_anim_count_running() == 0);        // no load animation pending
    }
    // The helper itself: no previous screen -> the value screen; any other native screen is kept.
    EXPECT(cc_handback_screen<lv_obj_t>(nullptr, splash, value) == value);
    EXPECT(cc_handback_screen(host, splash, value) == host);
    lv_display_delete(disp);
}

// ------------------------------------------------------------------------------------------- FW-PUB-006 --
// One LCD pass: the cue step as LcdThread::run() does it, then lv_timer_handler(). Returns the flushes.
int cue_pass() {
    fw::cal_cue_apply(cc_cal_cue_step(fw::cal_cue, cc_motor_cal_state()));
    return run_ms(PASS_MS);
}
int cue_passes(uint32_t ms) {
    int f = 0;
    for (uint32_t t = 0; t < ms; t += PASS_MS) f += cue_pass();
    return f;
}
// Every corner of the object inside the round 240 px panel.
bool inside_round_panel(lv_obj_t* o) {
    lv_area_t a;
    lv_obj_get_coords(o, &a);
    const int32_t xs[2] = {a.x1, a.x2}, ys[2] = {a.y1, a.y2};
    for (int32_t x : xs)
        for (int32_t y : ys) {
            const double dx = x - 119.5, dy = y - 119.5;
            if (dx * dx + dy * dy > 119.5 * 119.5) return false;
        }
    return a.x1 >= 0 && a.y1 >= 0 && a.x2 < W && a.y2 < H;
}

void cal_cue_over_boot_screens() {
    lv_display_t* disp = make_display();
    lv_obj_t* splash = lv_obj_create(nullptr);
    lv_obj_t* value = lv_obj_create(nullptr);
    lv_obj_set_style_bg_color(splash, lv_color_black(), 0);
    lv_obj_t* msg = lv_label_create(splash);         // ui_bootimg.c ui_bootMsg
    lv_label_set_text(msg, "DESK DIAL\nIS BOOTING...");
    lv_obj_set_style_text_font(msg, &ui_font_SGK100h16, 0);
    lv_obj_set_align(msg, LV_ALIGN_CENTER);
    splash_target = value;
    lv_obj_add_event_cb(splash, splash_event, LV_EVENT_ALL, nullptr);
    lv_screen_load(splash);
    cc_motor_cal_post(CC_MOTOR_CAL_STARTING);
    cue_passes(200);                                  // the LCD thread starts before the FOC task
    EXPECT(fw::cal_cue_label == nullptr);
    EXPECT(cue_passes(300) == 0);                     // splash at rest
    cc_motor_cal_post(CC_MOTOR_CAL_ALIGNING);         // foc_thread.cpp: before the 1 s settle
    int shown = cue_pass();
    for (int i = 0; i < 4 && shown == 0; ++i) shown += cue_pass();   // within one refresh period (12 ms)
    EXPECT(shown > 0);
    lv_obj_t* label = fw::cal_cue_label;
    EXPECT(label != nullptr);
    if (label == nullptr) { lv_display_delete(disp); return; }
    EXPECT(lv_obj_get_parent(label) == lv_layer_top());
    EXPECT(!lv_obj_has_flag(label, LV_OBJ_FLAG_HIDDEN));
    EXPECT(std::strcmp(lv_label_get_text(label), "Calibrating - hands off") == 0);
    EXPECT(lv_obj_get_style_text_font(label, LV_PART_MAIN) == &ui_font_SGK100h16);
    lv_area_t a;
    lv_obj_get_coords(label, &a);
    std::printf("cal cue: %d x %d px at (%d, %d)\n", static_cast<int>(lv_area_get_width(&a)),
                static_cast<int>(lv_area_get_height(&a)), static_cast<int>(a.x1), static_cast<int>(a.y1));
    EXPECT(inside_round_panel(label));
    lv_area_t m;
    lv_obj_get_coords(msg, &m);
    EXPECT(a.y1 > m.y2);                              // below the boot message, not over it
    // The settle and sweep span the splash's 3.3 s fade to the value screen: the cue stays over both.
    cue_passes(4000);
    EXPECT(lv_screen_active() == value);
    EXPECT(!lv_obj_has_flag(label, LV_OBJ_FLAG_HIDDEN) && fw::cal_cue_label == label);
    EXPECT(cue_passes(1000) == 0);                    // shown and still: nothing redrawn
    cc_motor_cal_post(cc_boot_cal_outcome(0, true, true));   // FW-BUG-030: the boot alignment failed
    EXPECT(cue_passes(50) > 0);                       // the cue's area is redrawn without it: the retry is due
    EXPECT(lv_obj_has_flag(label, LV_OBJ_FLAG_HIDDEN));
    EXPECT(cue_passes(2000) == 0);                    // the idle wait before the retry: no "replug", nothing drawn
    EXPECT(lv_obj_has_flag(label, LV_OBJ_FLAG_HIDDEN));
    // FW-BUG-030: the retry of a failed alignment shows the same cue again; failing too, it reads "replug".
    cc_motor_cal_post(CC_MOTOR_CAL_ALIGNING);
    EXPECT(cue_passes(50) > 0);
    EXPECT(fw::cal_cue_label == label && !lv_obj_has_flag(label, LV_OBJ_FLAG_HIDDEN));
    EXPECT(lv_obj_get_child_count(lv_layer_top()) == 1);
    cc_motor_cal_post(cc_boot_cal_outcome(0, true, false));   // failed again
    EXPECT(cue_passes(50) > 0);                       // FW-BUG-030: the failed text reaches the panel
    EXPECT(fw::cal_cue_label == label && !lv_obj_has_flag(label, LV_OBJ_FLAG_HIDDEN));
    EXPECT(std::strcmp(lv_label_get_text(label), "Calibration failed - replug") == 0);
    EXPECT(lv_obj_get_child_count(lv_layer_top()) == 1);
    lv_obj_update_layout(label);
    lv_obj_get_coords(label, &a);
    std::printf("cal failed cue: %d x %d px at (%d, %d)\n", static_cast<int>(lv_area_get_width(&a)),
                static_cast<int>(lv_area_get_height(&a)), static_cast<int>(a.x1), static_cast<int>(a.y1));
    EXPECT(inside_round_panel(label));
    EXPECT(a.x1 + a.x2 >= W - 2 && a.x1 + a.x2 <= W);   // still centred after the text change
    EXPECT(cue_passes(2000) == 0);                    // held until the state changes, nothing redrawn
    EXPECT(!lv_obj_has_flag(label, LV_OBJ_FLAG_HIDDEN));
    cc_motor_cal_post(CC_MOTOR_CAL_ALIGNING);         // a retry / recalibration: "hands off" on the same label
    EXPECT(cue_passes(50) > 0);
    EXPECT(std::strcmp(lv_label_get_text(label), "Calibrating - hands off") == 0);
    EXPECT(!lv_obj_has_flag(label, LV_OBJ_FLAG_HIDDEN));
    cc_motor_cal_post(CC_MOTOR_CAL_READY);            // calibrated: the cue goes
    EXPECT(cue_passes(50) > 0);
    EXPECT(lv_obj_has_flag(label, LV_OBJ_FLAG_HIDDEN));
    EXPECT(cue_passes(1000) == 0);
    lv_display_delete(disp);                          // deletes the top layer and the cue with it
    fw::cal_cue_label = nullptr;
    fw::cal_cue = CCCalCue{};
}
}  // namespace

int main() {
    lv_init();
    lv_tick_set_cb(tick_cb);
    native_rest(false);
    native_rest(true);
    claim_during_splash(false);
    claim_during_splash(true);
    cal_cue_over_boot_screens();
    std::printf("%s: %d check(s), %d failure(s)\n", failures ? "FAIL" : "PASS", checks, failures);
    return failures ? 1 : 0;
}
