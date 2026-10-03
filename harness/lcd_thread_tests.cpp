// Pure decisions of the LCD thread: the firmware's src/cc_lcd_logic.h, unchanged (MSVC /W4 /WX).
// lcd_thread_tests.py compiles and runs this; lcd_thread_lvgl_tests.cpp holds the cases that need LVGL.
#include "cc_lcd_logic.h"
#include "cc_boot_cal.h"   // the FOC task's calibration state word (FW-PUB-006)

#include <cstdio>
#include <string>

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

// FW-PERF-009: lcd_manager's value-screen block runs on the first run there, after every new command and while
// the timed modal is pending; never on another screen; not again for the same command.
void manager_gate() {
    CCLcdManagerGate g = {};
    EXPECT(!cc_lcd_manager_due(g, false, 0, false));    // another screen (the boot splash): nothing
    EXPECT(cc_lcd_manager_due(g, true, 0, false));      // first run on the value screen
    cc_lcd_manager_applied(g, 0);
    for (int i = 0; i < 60; ++i) EXPECT(!cc_lcd_manager_due(g, true, 0, false));   // a minute at rest
    EXPECT(cc_lcd_manager_due(g, true, 1, false));      // a new LcdCommand
    cc_lcd_manager_applied(g, 1);
    EXPECT(!cc_lcd_manager_due(g, true, 1, false));
    EXPECT(cc_lcd_manager_due(g, true, 1, true));       // the modal's 5 s timer runs in the block
    EXPECT(!cc_lcd_manager_due(g, false, 2, true));     // never on another screen
    EXPECT(cc_lcd_manager_due(g, true, 2, false));      // ... applied when the value screen is back
    cc_lcd_manager_applied(g, 0xFFFFFFFFu);
    EXPECT(cc_lcd_manager_due(g, true, 0, false));      // the count wraps: still a change
}

// FW-PERF-010 refr_avg_is_per_window: lcdRefrUsAvg / lcdRefrUsMax describe the last window only. After a window of
// 30 ms refreshes, a window of 2 ms refreshes reads 2000 / 2000 (the since-boot form read about 16,000 / 30,000);
// a window without a refresh reads 0 / 0, like lcdFps.
void refr_window() {
    CCRefrWindow w = {};
    uint32_t avg = 1, max = 1;
    cc_refr_window_close(w, avg, max);
    EXPECT(avg == 0 && max == 0);                         // at rest: nothing reached the panel
    for (int i = 0; i < 30; ++i) cc_refr_window_add(w, 30000);
    cc_refr_window_add(w, 298169);                        // a boot-time full-screen refresh
    cc_refr_window_close(w, avg, max);
    EXPECT(max == 298169);
    EXPECT(avg == (30u * 30000u + 298169u) / 31u);
    for (int i = 0; i < 80; ++i) cc_refr_window_add(w, 2000);
    cc_refr_window_close(w, avg, max);
    EXPECT(avg == 2000);
    EXPECT(max == 2000);
    cc_refr_window_close(w, avg, max);
    EXPECT(avg == 0 && max == 0);
    // 1000 refreshes near the 32-bit limit each: the sum is 64-bit, the mean exact.
    for (int i = 0; i < 1000; ++i) cc_refr_window_add(w, 0xFFFFFFF0u);
    cc_refr_window_close(w, avg, max);
    EXPECT(avg == 0xFFFFFFF0u && max == 0xFFFFFFF0u);
    // A 2x faster renderer is a 2x smaller mean in the next window, whatever came before.
    for (int i = 0; i < 60; ++i) cc_refr_window_add(w, 8200);
    cc_refr_window_close(w, avg, max);
    const uint32_t before = avg;
    for (int i = 0; i < 60; ++i) cc_refr_window_add(w, 4100);
    cc_refr_window_close(w, avg, max);
    EXPECT(before == 2 * avg);
}

// FW-BUG-042 offline_volume_entry_is_not_native_input: the offline layer and the offline system volume.
struct Offline {
    CCNativeMotion motion;
    CCOfflineInput input;
    uint32_t now;
    // One LCD pass with the offline layer up; returns the layer's `native`.
    bool pass(uint16_t pos, bool wanted, int32_t steps, uint32_t keyEdges = 0, uint32_t dtMs = 5) {
        now += dtMs;
        return cc_offline_input_update(input, cc_native_motion_step(motion, pos, wanted, steps, now), keyEdges);
    }
};

void offline_input() {
    // The finding: Desk Dial exits, the lease expires with the knob at 37, the layer arms; 2 s after the port closed
    // the HMI wants the offline volume and the FOC rebases 37 -> 100 (a pass later), no input anywhere.
    {
        Offline o = {};
        o.now = 1000;
        EXPECT(!o.pass(37, false, 0));                 // the layer's first pass: references taken
        for (int i = 0; i < 40; ++i) EXPECT(!o.pass(37, false, 0));
        EXPECT(!o.pass(37, true, 0));                  // HMI: wanted; the FOC has not rebased yet
        EXPECT(!o.pass(100, true, 0));                 // enter_offline(): 37 -> 100
        EXPECT(!o.pass(101, true, 0));                 // a sample between a detent and its re-centring ...
        EXPECT(!o.pass(100, true, 0));                 // ... is not counted twice: the step count is
        for (int i = 0; i < 400; ++i) EXPECT(!o.pass(100, true, 0));   // 2 s at rest: still "Open Desk Dial"
        EXPECT(o.pass(100, true, 1));                  // one offline detent (re-centred in its FOC pass)
        EXPECT(o.pass(100, true, 1));                  // latched until the next claim
        cc_offline_input_reset(o.input);               // a claim
        EXPECT(!o.pass(100, true, 1));
    }
    // Control: the raw FOC position (the old feed) sees the rebase as input and every offline detent as nothing.
    {
        CCOfflineInput raw = {};
        EXPECT(!cc_offline_input_update(raw, 37, 0));
        EXPECT(cc_offline_input_update(raw, 100, 0));  // the finding's swap without input
        CCOfflineInput raw2 = {};
        EXPECT(!cc_offline_input_update(raw2, 100, 0));
        EXPECT(!cc_offline_input_update(raw2, 100, 0)); // a detent, re-centred in the same FOC pass: invisible
    }
    // Leaving the offline volume without a claim (a terminal opened the port; the knob went to sleep and the FOC
    // left it): exit_offline() rebases 100 -> 37 a pass after the flag; a real turn afterwards counts.
    {
        Offline o = {};
        o.now = 5000;
        EXPECT(!o.pass(100, true, 4));
        EXPECT(!o.pass(100, false, 4));                // flag down, the FOC not yet rebased
        EXPECT(!o.pass(37, false, 4, 0, 1));           // exit_offline(): 100 -> 37
        for (int i = 0; i < 12; ++i) EXPECT(!o.pass(37, false, 4));   // 60 ms: the settle is over
        EXPECT(o.pass(38, false, 4));                  // a native detent
    }
    // Asleep while offline: the FOC leaves the offline volume (motor off) and enters it again on the wake; the flag
    // stays up, the rebases both ways are not input.
    {
        Offline o = {};
        o.now = 9000;
        EXPECT(!o.pass(100, true, 7));
        EXPECT(!o.pass(37, true, 7));                  // exit_offline() on the sleep
        for (int i = 0; i < 100; ++i) EXPECT(!o.pass(37, true, 7, 0, 100));
        EXPECT(!o.pass(100, true, 7));                 // enter_offline() after the wake
        EXPECT(o.pass(100, true, 6));                  // a detent down
    }
    // No offline volume (a knob no Desk Dial has claimed yet, FW-BUG-013): a native turn or a button edge counts.
    {
        Offline o = {};
        o.now = 100;
        EXPECT(!o.pass(10, false, 0));
        EXPECT(!o.pass(10, false, 0));
        EXPECT(o.pass(11, false, 0));
        Offline k = {};
        EXPECT(!k.pass(10, false, 0, 3));
        EXPECT(k.pass(10, false, 0, 4));
    }
    // The motion count is primed by its first sample, whenever that is (a claim in between moved the position).
    {
        Offline o = {};
        o.now = 0xFFFFFFF0u;                           // and millis() wraps during the settle
        EXPECT(!o.pass(50, true, 0));
        EXPECT(!o.pass(50, false, 0));
        EXPECT(!o.pass(12, false, 0, 0, 20));
        for (int i = 0; i < 12; ++i) EXPECT(!o.pass(12, false, 0));
        EXPECT(o.pass(13, false, 0));
    }
}

// FW-BUG-045: the app angle hold. Awake with the motor on, the held angle moves one-for-one with the shaft; asleep and
// in the post-wake settle (the FOC's motor-off window, the same CCSleepFoc rule) it does not move at all.
void app_angle_hold() {
    CCAppAngleHold h;
    uint32_t now = 1000;
    int32_t raw = -5000;
    int32_t held = h.step(raw, false, now);
    EXPECT(held == raw);
    EXPECT(!h.holding());
    for (int i = 0; i < 10; ++i) {                 // awake turns pass through
        raw += 123;
        now += 5;
        const int32_t was = held;
        held = h.step(raw, false, now);
        EXPECT(held - was == 123);
    }
    const int32_t asleepAt = held;
    for (int i = 0; i < 300; ++i) {                // asleep 1.5 s, cogging creep and a wake turn
        raw += i < 200 ? 1 : 20;
        now += 5;
        EXPECT(h.step(raw, true, now) == asleepAt);
    }
    EXPECT(h.holding());
    for (int i = 0; i < 20; ++i) {                 // woken: the turn goes on, the motor stays off
        raw += 150;
        now += 5;
        EXPECT(h.step(raw, false, now) == asleepAt);
    }
    int passes = 0;
    while (h.holding() && passes < 1000) {         // still: the motor comes back after the settle
        now += 5;
        EXPECT(h.step(raw, false, now) == asleepAt);
        ++passes;
    }
    EXPECT(!h.holding());
    // kCCSleepSettleMs after the last 2 deg of travel the FOC counted (up to two passes before the turn ended).
    std::printf("app angle hold: motor back %d ms after the wake turn ended\n", passes * 5);
    EXPECT(passes * 5 >= static_cast<int>(kCCSleepSettleMs) - 15 && passes * 5 <= static_cast<int>(kCCSleepSettleMs) + 10);
    raw += 77;
    now += 5;
    EXPECT(h.step(raw, false, now) == asleepAt + 77);   // one-for-one again, from where it was
    // A settle that never ends (the knob keeps turning): the FOC enables the motor after kCCSleepSettleMaxMs anyway.
    CCAppAngleHold k;
    uint32_t t = 0;
    int32_t a = 0;
    k.step(a, false, t);
    for (int i = 0; i < 200; ++i) { t += 5; k.step(a, true, t); }
    int holdingMs = 0;
    for (int i = 0; i < 1000; ++i) {
        a += 400;
        t += 5;
        k.step(a, false, t);
        if (k.holding()) holdingMs += 5;
    }
    EXPECT(holdingMs >= static_cast<int>(kCCSleepSettleMaxMs) - 5 && holdingMs <= static_cast<int>(kCCSleepSettleMaxMs) + 5);
    // The shaft angle wraps the 32-bit range (a long life of turns): the held angle still moves one-for-one.
    CCAppAngleHold w;
    int32_t big = 0x7FFFFF00;
    int32_t h0 = w.step(big, false, 0);
    big = static_cast<int32_t>(static_cast<uint32_t>(big) + 0x200u);
    const int32_t h1 = w.step(big, false, 5);
    EXPECT(static_cast<uint32_t>(h1) - static_cast<uint32_t>(h0) == 0x200u);
    h0 = h1;
    // FW-BUG-032: the motor-off mirror sees the wrapped difference, not float(raw). A woken knob resting on the
    // int32 wrap with one count of sensor jitter (0x7FFFFFFF <-> 0x80000000) is still: the motor comes back
    // kCCSleepSettleMs after the wake turn, not kCCSleepSettleMaxMs (float(raw) jumped 429k rad every pass).
    {
        CCAppAngleHold j;
        uint32_t tj = 0;
        int32_t rj = static_cast<int32_t>(0x7FFFFFFFu - 20u * 600u);
        const int32_t held0 = j.step(rj, false, tj);
        for (int i = 0; i < 150; ++i) { tj += 5; EXPECT(j.step(rj, true, tj) == held0); }   // asleep 750 ms
        for (int i = 0; i < 20; ++i) {               // woken: the wake turn runs up to the wrap
            tj += 5;
            rj = static_cast<int32_t>(static_cast<uint32_t>(rj) + 600u);   // 3.4 deg a pass: counted travel
            EXPECT(j.step(rj, false, tj) == held0);
        }
        int still = 0;
        while (j.holding() && still < 1000) {        // jitter across the wrap, one count each way
            tj += 5;
            rj = (still & 1) ? 0x7FFFFFFF : static_cast<int32_t>(0x80000000u);
            j.step(rj, false, tj);
            ++still;
        }
        std::printf("app angle hold: jitter on the int32 wrap, motor back %d ms after the wake turn\n", still * 5);
        EXPECT(still * 5 >= static_cast<int>(kCCSleepSettleMs) - 15 && still * 5 <= static_cast<int>(kCCSleepSettleMs) + 10);
        tj += 5;
        rj = static_cast<int32_t>(0x80000000u + 50u);
        const int32_t heldNow = j.step(rj, false, tj);
        tj += 5;
        rj = static_cast<int32_t>(static_cast<uint32_t>(rj) + 33u);
        EXPECT(static_cast<uint32_t>(j.step(rj, false, tj)) - static_cast<uint32_t>(heldNow) == 33u);
    }
    // FW-BUG-032: a long turn one way (many rebase spans, through the wrap) keeps one-for-one tracking, and the
    // sleep / wake / settle timing afterwards is the same as near zero.
    {
        CCAppAngleHold r;
        uint32_t tr = 0;
        uint32_t ur = 0x10000000u;
        int32_t prev = r.step(static_cast<int32_t>(ur), false, tr);
        for (int i = 0; i < 4000; ++i) {             // 4000 x 0x100000 counts: ~2.5 wraps of the word
            ur += 0x100000u;
            tr += 5;
            const int32_t hr = r.step(static_cast<int32_t>(ur), false, tr);
            EXPECT(static_cast<uint32_t>(hr) - static_cast<uint32_t>(prev) == 0x100000u);
            EXPECT(!r.holding());
            prev = hr;
        }
        for (int i = 0; i < 150; ++i) { tr += 5; EXPECT(r.step(static_cast<int32_t>(ur), true, tr) == prev); }
        EXPECT(r.holding());
        for (int i = 0; i < 20; ++i) { ur += 600u; tr += 5; EXPECT(r.step(static_cast<int32_t>(ur), false, tr) == prev); }
        int settle = 0;
        while (r.holding() && settle < 1000) { tr += 5; r.step(static_cast<int32_t>(ur), false, tr); ++settle; }
        EXPECT(settle * 5 >= static_cast<int>(kCCSleepSettleMs) - 15 && settle * 5 <= static_cast<int>(kCCSleepSettleMs) + 10);
    }
}

// FW-PUB-006 cal_cue_follows_the_alignment: the LCD pass steps the cue with cc_motor_cal_state(), the word the FOC
// task posts (cc_boot_cal.h). The cue shows once when an alignment starts (first boot, the FW-BUG-030 retry), changes
// once when it ends, and is not touched on the passes between (no redraw at rest).
// FW-BUG-030: a failed BOOT alignment shows nothing while its one retry is due (5 s idle); the retry's ALIGNING shows
// "hands off" again; a second FAILED (the retry done) reads "Calibration failed - replug" (SHOW_FAILED) and stays.
uint8_t cue_pass(CCCalCue& cue) { return cc_cal_cue_step(cue, cc_motor_cal_state()); }
uint8_t post_pass(CCCalCue& cue, uint8_t state) { cc_motor_cal_post(state); return cue_pass(cue); }
void cal_cue() {
    CCCalCue cue = {};
    int shows = 0, hides = 0, fails = 0;
    auto passes = [&](int n) {
        for (int i = 0; i < n; ++i) {
            const uint8_t a = cue_pass(cue);
            if (a == CC_CAL_CUE_SHOW) ++shows;
            if (a == CC_CAL_CUE_HIDE) ++hides;
            if (a == CC_CAL_CUE_SHOW_FAILED) ++fails;
        }
    };
    // failed_boot_then_retry: STARTING -> ALIGNING (hands off) -> FAILED (nothing: the retry is due) -> ALIGNING
    // (hands off again) -> FAILED (the retry is done: "calibration failed - replug", held).
    cc_motor_cal_post(CC_MOTOR_CAL_STARTING);
    passes(50);                                          // the LCD runs before the FOC task aligns: no cue
    EXPECT(shows == 0 && hides == 0 && fails == 0 && !cue.shown && !cue.failed && !cue.settled);
    cc_motor_cal_post(CC_MOTOR_CAL_ALIGNING);            // boot: the 1 s settle, then the sweep
    passes(1);
    EXPECT(shows == 1 && cue.shown);                     // on the first pass
    passes(600);                                         // about 3 s of passes
    EXPECT(shows == 1 && hides == 0 && cue.shown && !cue.settled);   // shown, not re-applied
    cc_motor_cal_post(cc_boot_cal_outcome(0, true, true));
    EXPECT(cc_motor_cal_state() == CC_MOTOR_CAL_FAILED);
    EXPECT(cue_pass(cue) == CC_CAL_CUE_HIDE && !cue.shown && !cue.failed && cue.settled && cue.retryDue);
    passes(1000);                                        // about 5 s of passes before the retry: no "replug" yet
    EXPECT(shows == 1 && hides == 0 && fails == 0 && !cue.failed && cue.retryDue);
    cc_motor_cal_post(CC_MOTOR_CAL_ALIGNING);            // the retry: "hands off" again
    EXPECT(cue_pass(cue) == CC_CAL_CUE_SHOW && cue.shown && !cue.failed && !cue.retryDue);
    passes(200);
    cc_motor_cal_post(cc_boot_cal_outcome(0, true, false));   // the retry failed too: final
    EXPECT(cue_pass(cue) == CC_CAL_CUE_SHOW_FAILED && cue.failed && !cue.shown);
    passes(2000);
    EXPECT(shows == 1 && hides == 0 && fails == 0 && cue.failed);   // stays until the state changes
    cc_motor_cal_post(CC_MOTOR_CAL_READY);               // a Desk Dial recalibration that succeeds: the cue goes
    EXPECT(cue_pass(cue) == CC_CAL_CUE_HIDE && !cue.failed && !cue.shown);
    passes(1000);
    EXPECT(shows == 1 && hides == 0 && fails == 0);
    EXPECT(post_pass(cue, CC_MOTOR_CAL_FAILED) == CC_CAL_CUE_SHOW_FAILED);   // a later failed recalibration: at once

    // retry_succeeds: FAILED (nothing) -> ALIGNING (hands off) -> READY / UNSTORED (no cue), no "replug" ever.
    const uint8_t ends[] = {cc_boot_cal_outcome(1, true, true), cc_boot_cal_outcome(1, true, false)};
    EXPECT(ends[0] == CC_MOTOR_CAL_READY && ends[1] == CC_MOTOR_CAL_UNSTORED);
    for (uint8_t end : ends) {
        CCCalCue r = {};
        int rf = 0;
        EXPECT(post_pass(r, CC_MOTOR_CAL_STARTING) == CC_CAL_CUE_KEEP);
        EXPECT(post_pass(r, CC_MOTOR_CAL_ALIGNING) == CC_CAL_CUE_SHOW);
        EXPECT(post_pass(r, CC_MOTOR_CAL_FAILED) == CC_CAL_CUE_HIDE);
        EXPECT(post_pass(r, CC_MOTOR_CAL_ALIGNING) == CC_CAL_CUE_SHOW);
        EXPECT(post_pass(r, end) == CC_CAL_CUE_HIDE);
        for (int i = 0; i < 500; ++i) if (cue_pass(r) != CC_CAL_CUE_KEEP) ++rf;
        EXPECT(rf == 0 && !r.shown && !r.failed);
    }
    // stored_cal_init_fails: no alignment at boot (STARTING -> FAILED): nothing until the retry, then as above.
    CCCalCue st = {};
    EXPECT(post_pass(st, CC_MOTOR_CAL_STARTING) == CC_CAL_CUE_KEEP);
    EXPECT(post_pass(st, CC_MOTOR_CAL_FAILED) == CC_CAL_CUE_KEEP && st.retryDue && !st.failed);
    EXPECT(post_pass(st, CC_MOTOR_CAL_ALIGNING) == CC_CAL_CUE_SHOW);
    EXPECT(post_pass(st, CC_MOTOR_CAL_FAILED) == CC_CAL_CUE_SHOW_FAILED);
    // recalibrated_while_retry_due: FAILED (retry due) -> READY (the FOC task disarms the retry): no cue, and a later
    // FAILED (a failed recalibration, no retry left) shows "replug" at once.
    CCCalCue rc = {};
    EXPECT(post_pass(rc, CC_MOTOR_CAL_FAILED) == CC_CAL_CUE_KEEP && rc.retryDue);
    EXPECT(post_pass(rc, CC_MOTOR_CAL_READY) == CC_CAL_CUE_KEEP && !rc.retryDue);
    EXPECT(post_pass(rc, CC_MOTOR_CAL_FAILED) == CC_CAL_CUE_SHOW_FAILED);
    // A stored calibration (no alignment at boot): the word goes STARTING -> READY and the cue never appears.
    CCCalCue quiet = {};
    cc_motor_cal_post(CC_MOTOR_CAL_STARTING);
    EXPECT(cue_pass(quiet) == CC_CAL_CUE_KEEP);
    cc_motor_cal_post(cc_boot_cal_outcome(1, false, false));
    EXPECT(cue_pass(quiet) == CC_CAL_CUE_KEEP && !quiet.shown && !quiet.failed && quiet.settled && !quiet.retryDue);
    EXPECT(std::string(kCCCalCueText) == "Calibrating - hands off");
    EXPECT(std::string(kCCCalFailedCueText) == "Calibration failed - replug");
}
}  // namespace

int main() {
    manager_gate();
    refr_window();
    offline_input();
    app_angle_hold();
    cal_cue();
    std::printf("%s: %d check(s), %d failure(s)\n", failures ? "FAIL" : "PASS", checks, failures);
    return failures ? 1 : 0;
}
