#pragma once
// Pure decisions of the LCD thread (lcd_thread.cpp): no LVGL, no RTOS, no Arduino. Header-only so the host test
// (harness/lcd_thread_tests.py, MSVC) runs this exact code; the device compiles it in gnu++11.
#include <stdint.h>

#include "cc_sleep.h"   // CCSleepFoc (FW-BUG-045)
#include "cc_boot_cal.h"   // CCMotorCal (FW-PUB-006, FW-BUG-030)

// FW-PERF-009: lcd_manager (the 1 s LVGL timer) re-set the native profile's name and description on every run, and
// lv_label_set_text() invalidates the label (and reallocates its text) even when nothing changed, so the panel
// redrew both labels once a second at rest. The texts are applied when an LcdCommand arrived since the last
// application on the value screen (handleLcdCommand() counts them), on the first run there, and on every run
// while the timed modal (data3) is pending, whose 5 s timer lives in that same block.
struct CCLcdManagerGate {
    bool applied;    // the block ran at least once on the value screen
    uint32_t seq;    // the command count it ran for
};
// True when lcd_manager must run its value-screen block now.
inline bool cc_lcd_manager_due(const CCLcdManagerGate& gate, bool valueScreen, uint32_t commandSeq, bool modalPending) {
    if (!valueScreen) return false;
    return !gate.applied || gate.seq != commandSeq || modalPending;
}
// After the block ran for commandSeq.
inline void cc_lcd_manager_applied(CCLcdManagerGate& gate, uint32_t commandSeq) {
    gate.applied = true;
    gate.seq = commandSeq;
}

// FW-PERF-010: lcdRefrUsAvg / lcdRefrUsMax were since boot (a lifetime mean, the boot's full-screen refreshes in the
// max), so after hours neither could show a change in the renderer. They are windowed like lcdFps: the refreshes of
// one perfWindow() second are summed here and published when the window closes (0 when none reached the panel).
struct CCRefrWindow {
    uint32_t count;   // refreshes that reached the panel in this window
    uint32_t usMax;   // the longest, us
    uint64_t usSum;   // their total, us
};
// One refresh that flushed pixels (LV_EVENT_REFR_READY, after the final dmaWait).
inline void cc_refr_window_add(CCRefrWindow& w, uint32_t us) {
    ++w.count;
    w.usSum += us;
    if (us > w.usMax) w.usMax = us;
}
// The window closes: its mean and max (0, 0 without a refresh), and the next window starts empty.
inline void cc_refr_window_close(CCRefrWindow& w, uint32_t& avgUs, uint32_t& maxUs) {
    avgUs = w.count ? static_cast<uint32_t>(w.usSum / w.count) : 0u;
    maxUs = w.usMax;
    w.count = 0;
    w.usMax = 0;
    w.usSum = 0;
}

// The offline layer's "first native input" (PRESENTATION_V5.md 8.10; AL 8.1: an FOC position change or a button
// state change while unclaimed), from what the caller samples on every pass while the layer shows: a position (the
// LCD thread passes its native motion count, CCNativeMotion below; the harness a fake FOC position) and a native
// button edge counter (every debounced press and release the unclaimed button handler saw; 0 when the caller has
// no such source). Counters, not the key mask: a press and its release can both fall between two samples. Latched
// until reset. (Moved here from cc_display.cpp unchanged, FW-BUG-042.)
struct CCOfflineInput {
    bool armed;          // the reference values below were taken (the layer's first pass)
    bool native;         // native input seen since then (kept until the next claim)
    uint16_t pos;        // position (motion count) at the first pass
    uint32_t keyEdges;   // button edge counter at the first pass
};
// Every pass while the offline layer shows (before cc_display_offline()); returns `native`.
inline bool cc_offline_input_update(CCOfflineInput& input, uint16_t pos, uint32_t keyEdges) {
    if (!input.armed) {
        input.armed = true;
        input.native = false;
        input.pos = pos;
        input.keyEdges = keyEdges;
    } else if (pos != input.pos || keyEdges != input.keyEdges) {
        input.native = true;
    }
    return input.native;
}
// The offline layer was left (a claim, a handback): the next update takes new references.
inline void cc_offline_input_reset(CCOfflineInput& input) {
    input.armed = false;
    input.native = false;
}

// FW-BUG-042: the FOC position is not native motion while the offline system volume (plan F3) comes and goes.
// enter_offline() rebases the position to its centre (100) and exit_offline() back to the native one, with no
// input; while it runs every detent is re-centred in the same FOC pass, so a turn never shows as a position change.
// Fed the raw position, the layer swapped "Open Desk Dial on your PC" for "Knob controls still work" about 2 s
// after the port closed, and offline turns were invisible to it. This counts native motion instead (wrapping):
//   * a change of the offline step count (cc_offline_steps(): one per offline detent) is motion;
//   * a position change is motion only while the offline volume is not wanted (cc_offline_wanted()) and not
//     within kCCOfflineRebaseSettleMs of it being wanted or released (the FOC applies the rebase on its next
//     pass, after the HMI's flag); in that time the position sample only follows the rebases.
constexpr uint32_t kCCOfflineRebaseSettleMs = 50;
struct CCNativeMotion {
    bool primed;
    bool wanted;          // the offline volume was wanted at the last sample
    uint16_t pos;         // the last position sample
    int32_t steps;        // the last offline step count
    uint32_t changedMs;   // when `wanted` last changed
    uint16_t count;       // native motion seen (wrapping)
};
// Every pass that needs it; returns the motion count (feed it to cc_offline_input_update() as `pos`).
inline uint16_t cc_native_motion_step(CCNativeMotion& m, uint16_t pos, bool offlineWanted, int32_t offlineSteps,
                                      uint32_t nowMs) {
    if (!m.primed) {
        m.primed = true;
        m.wanted = offlineWanted;
        m.pos = pos;
        m.steps = offlineSteps;
        m.changedMs = nowMs - kCCOfflineRebaseSettleMs;   // no settle pending
        m.count = 0;
        return m.count;
    }
    if (offlineSteps != m.steps) {
        m.steps = offlineSteps;
        ++m.count;
    }
    if (offlineWanted != m.wanted) {
        m.wanted = offlineWanted;
        m.changedMs = nowMs;
    }
    const bool rebasing = offlineWanted || static_cast<uint32_t>(nowMs - m.changedMs) < kCCOfflineRebaseSettleMs;
    if (pos != m.pos) {
        if (!rebasing) ++m.count;
        m.pos = pos;
    }
    return m.count;
}

// FW-BUG-043: the screen a native handback loads. The boot splash (ui_bootimg) is never returned to: its
// SCREEN_LOADED handler schedules the 3.3 s fade to the value screen again, so a claim made during the splash
// handed back to "DESK DIAL IS BOOTING..." for about 3.6 s while native control was already active. Without a
// previous screen, or when it was the splash, the value screen.
template <typename Screen>
inline Screen* cc_handback_screen(Screen* previous, Screen* splash, Screen* valueScreen) {
    return previous == nullptr || previous == splash ? valueScreen : previous;
}

// FW-BUG-045: the app canvas must not move for the turn that wakes the knob. The FOC swallows the wake turn (the
// motor stays off, no position moves, until the knob has been still kCCSleepSettleMs; CCSleepFoc), but the canvas
// follows the raw shaft angle (cc_app_angle_read()) and the LCD thread skips its step() while asleep: on the first
// awake pass the canvas saw the whole wake turn as one diff (below its 2 rad re-anchor guard) and orbited, zoomed or
// panned the cube, and turns during the post-wake settle moved it too. This hold feeds the canvas the shaft angle
// minus the travel made while the motor is off: asleep, and until the same CCSleepFoc rule the FOC runs (fed the
// same angle and sleep state, here on the LCD pass) would enable it again. The canvas then sees no change for the
// swallowed travel and every turn after it one-for-one.
class CCAppAngleHold {
public:
    CCAppAngleHold() : primed_(false), last_(0), offset_(0), base_(0) {}
    // Every LCD pass (also while asleep or with the canvas down): raw = cc_app_angle_read() (1e-4 rad), asleep =
    // cc_sleep_state() == CC_SLEEP_ASLEEP. Returns the angle the canvas gets.
    // FW-BUG-032: the raw word wraps modulo 2^32, so the CCSleepFoc mirror is fed a float rebuilt from the wrapped
    // difference to a uint32 base (no 429k rad jump at the wrap, full float resolution at any raw). The base moves
    // only while the motor is on, where the mirror's "moved" does not reach the hold; with the motor off the
    // frame stays put (one sleep and settle span far less than kRebase).
    int32_t step(int32_t raw, bool asleep, uint32_t nowMs) {
        const uint32_t now = static_cast<uint32_t>(raw);
        if (!primed_) {
            primed_ = true;
            last_ = now;
            base_ = now;
        }
        int32_t rel = static_cast<int32_t>(now - base_);
        if (!motor_.motorOff() && (rel > kRebase || rel < -kRebase)) {
            base_ = now;
            rel = 0;
        }
        motor_.step(nowMs, static_cast<float>(rel) * 1e-4f, asleep);
        if (asleep || motor_.motorOff()) offset_ += now - last_;   // swallowed: wrapping arithmetic
        last_ = now;
        return static_cast<int32_t>(now - offset_);
    }
    // The mirror of the FOC's motor-off window (tests, diag).
    bool holding() const { return motor_.motorOff(); }

private:
    static constexpr int32_t kRebase = 1 << 20;   // ~105 rad: float exact to the count below 2^24
    CCSleepFoc motor_;
    bool primed_;
    uint32_t last_, offset_, base_;
};

// FW-PUB-006: the motor alignment (first boot, and the FW-BUG-030 retry of a failed one) needs the knob untouched,
// and nothing on the knob said so. While the FOC task posts CC_MOTOR_CAL_ALIGNING (cc_boot_cal.h
// cc_motor_cal_hands_off(): the 1 s settle and the sweep) the LCD thread shows kCCCalCueText on LVGL's top layer,
// over whatever screen is up; it goes when the alignment ends. Nothing else on the knob changes. The cue is touched
// only when the state changes (no redraw at rest).
constexpr char kCCCalCueText[] ="Calibrating - hands off";
// FW-BUG-030: once the motor alignment has failed for good the same label reads kCCCalFailedCueText (the motor stays
// disabled: no detents, no turn-to-wake). A failed BOOT alignment is retried once by the FOC task after 5 s idle
// (cc_boot_cal.h CCBootRetry), so its first FAILED shows nothing: the retry posts ALIGNING ("hands off" again), then
// READY / UNSTORED (no cue) or FAILED again, which is final ("replug"). A FAILED after the boot settled on a working
// outcome (a Desk Dial recalibration that left the motor uncalibrated) has no retry and shows the text at once.
constexpr char kCCCalFailedCueText[] = "Calibration failed - replug";
constexpr int16_t kCCCalCueOffsetY = -36;   // above the bottom edge (LV_ALIGN_BOTTOM_MID), inside the round panel
enum CCCalCueAction : uint8_t { CC_CAL_CUE_KEEP = 0, CC_CAL_CUE_SHOW, CC_CAL_CUE_HIDE, CC_CAL_CUE_SHOW_FAILED };
struct CCCalCue {
    bool shown;      // the "hands off" text is on the top layer now
    bool failed;     // the "calibration failed" text is on the top layer now (FW-BUG-030)
    bool settled;    // the boot alignment has posted its outcome (anything but STARTING / ALIGNING seen)
    bool retryDue;   // that outcome was FAILED and the one boot retry has not started yet (FW-BUG-030)
};
// Every LCD pass, with cc_motor_cal_state() (the FOC task's word): what to do with the cue this pass.
inline uint8_t cc_cal_cue_step(CCCalCue& cue, uint8_t calState) {
    const bool handsOff = calState == CC_MOTOR_CAL_ALIGNING;
    const bool failedNow = calState == CC_MOTOR_CAL_FAILED;
    if (!cue.settled) {
        if (calState != CC_MOTOR_CAL_STARTING && !handsOff) { cue.settled = true; cue.retryDue = failedNow; }
    } else if (cue.retryDue && !failedNow) {
        cue.retryDue = false;   // the retry is aligning, or a recalibration made the motor ready (retry disarmed)
    }
    const bool failed = failedNow && !cue.retryDue;
    if (handsOff == cue.shown && failed == cue.failed) return CC_CAL_CUE_KEEP;
    cue.shown = handsOff;
    cue.failed = failed;
    return handsOff ? CC_CAL_CUE_SHOW : (failed ? CC_CAL_CUE_SHOW_FAILED : CC_CAL_CUE_HIDE);
}
