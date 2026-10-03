#pragma once

// Inactivity dim / sleep (user decisions 2026-09-28). Platform-neutral, header-only logic
// (harness/sleep_tests.py runs it on the host; cpp11_gate.py checks it in gnu++11), plus
// the firmware glue's declarations (cc_sleep.cpp).
//
//   awake --(CC_SLEEP_DIM_MS without physical input)--> dim --(CC_SLEEP_OFF_MS)--> asleep
//
// Only physical input counts: a button press/release (hmi_thread.cpp) and a knob rotation of at
// least CC_SLEEP_WAKE_DEG of shaft angle (foc_thread.cpp, CCSleepFoc). Host lines never reset the
// timer and never wake the knob. Dim: backlight clamped to CC_SLEEP_DIM_DUTY (LEDs and motor as
// they are); an input while dim restores it and acts normally. Asleep: backlight 0, every LED 0,
// the motor driver disabled; the first input only wakes (it is swallowed) and the FOC re-anchors
// the detents at the shaft angle it finds, so the value does not jump.
//
// Timeouts are compile-time constants; a build can shorten them for testing, e.g.
// -DCC_SLEEP_DIM_MS=20000 -DCC_SLEEP_OFF_MS=60000. 0 disables that stage.

#include <stdint.h>
#include <math.h>

#ifndef CC_SLEEP_DIM_MS
#define CC_SLEEP_DIM_MS 600000UL        // 10 minutes
#endif
#ifndef CC_SLEEP_OFF_MS
#define CC_SLEEP_OFF_MS 3600000UL       // 60 minutes
#endif
#ifndef CC_SLEEP_DIM_DUTY
#define CC_SLEEP_DIM_DUTY 640           // of LEDC_MAX_BLK 3200 (12-bit LEDC): about 20 %
#endif
#ifndef CC_SLEEP_WAKE_DEG
#define CC_SLEEP_WAKE_DEG 2             // knob rotation that counts as input (shaft degrees)
#endif

enum CCSleepState : uint8_t { CC_SLEEP_AWAKE = 0, CC_SLEEP_DIM = 1, CC_SLEEP_ASLEEP = 2 };

constexpr uint32_t kCCSleepDimMs = CC_SLEEP_DIM_MS;
constexpr uint32_t kCCSleepOffMs = CC_SLEEP_OFF_MS;
constexpr uint16_t kCCSleepDimDuty = CC_SLEEP_DIM_DUTY;
constexpr float kCCSleepWakeRad = CC_SLEEP_WAKE_DEG * 0.017453292519943f;
// FOC side (CCSleepFoc): after the driver is disabled the rotor may settle into a cogging
// position (7 pole pairs: a few degrees at most); motion in this window only re-seeds the
// reference. After a wake the motor stays off until the knob has been still this long (or at most
// kCCSleepSettleMaxMs), so the whole wake turn is swallowed, not only its first degrees.
constexpr uint32_t kCCSleepDisableQuietMs = 500;
constexpr uint32_t kCCSleepSettleMs = 300;
constexpr uint32_t kCCSleepSettleMaxMs = 2000;
// idleMs saturates here (about 12.4 days; tick() keeps it there) so it never wraps with millis().
// A difference that reads as negative (int32) is an input another task stamped after this
// caller read its clock: idle 0, never a wrapped "very long idle".
constexpr uint32_t kCCSleepIdleCap = 0x40000000u;

inline const char* cc_sleep_state_name(uint8_t state) {
    return state == CC_SLEEP_DIM ? "dim" : state == CC_SLEEP_ASLEEP ? "asleep" : "awake";
}

// The backlight duty for the duty the display path wants, in `state`.
inline uint16_t cc_sleep_duty(uint8_t state, uint16_t wanted) {
    if (state == CC_SLEEP_ASLEEP) return 0;
    if (state == CC_SLEEP_DIM && wanted > kCCSleepDimDuty) return kCCSleepDimDuty;
    return wanted;
}

// The timer. Times are millis() (uint32_t, wrap-safe differences). Not thread-safe by itself:
// the firmware glue holds a spinlock around every call.
class CCSleepMachine {
public:
    CCSleepMachine(uint32_t dimMs = kCCSleepDimMs, uint32_t offMs = kCCSleepOffMs)
        : dimMs_(dimMs), offMs_(offMs), last_(0), state_(CC_SLEEP_AWAKE) {}
    void begin(uint32_t now) { last_ = now; state_ = CC_SLEEP_AWAKE; }
    // A physical input at `now`: back to awake with a fresh timer. True when it woke the knob from
    // asleep, i.e. the input must be swallowed (it acts only as the wake).
    bool input(uint32_t now) {
        const bool swallow = state_ == CC_SLEEP_ASLEEP;
        last_ = now;
        state_ = CC_SLEEP_AWAKE;
        return swallow;
    }
    // Advances the state at `now` (never backwards: only input() wakes); returns it.
    uint8_t tick(uint32_t now) {
        uint32_t idle = idleMs(now);
        if (idle >= kCCSleepIdleCap) { last_ = now - kCCSleepIdleCap; idle = kCCSleepIdleCap; }
        if (state_ == CC_SLEEP_AWAKE && dimMs_ && idle >= dimMs_) state_ = CC_SLEEP_DIM;
        if (state_ != CC_SLEEP_ASLEEP && offMs_ && idle >= offMs_) state_ = CC_SLEEP_ASLEEP;
        return state_;
    }
    uint8_t state() const { return state_; }
    uint32_t idleMs(uint32_t now) const {
        const uint32_t idle = now - last_;
        if (static_cast<int32_t>(idle) < 0) return 0;          // stamped after `now` was read
        return idle > kCCSleepIdleCap ? kCCSleepIdleCap : idle;
    }

private:
    uint32_t dimMs_, offMs_, last_;
    uint8_t state_;
};

// FOC-thread knob watcher: one step per FOC pass with the shaft angle (rad) and whether the
// session is asleep. `input`: the knob turned at least the threshold since the last reference
// (a physical input to report). `action`: what the FOC must do to the motor this pass.
enum CCSleepMotorAction : uint8_t { CC_SLEEP_MOTOR_KEEP = 0, CC_SLEEP_MOTOR_DISABLE = 1, CC_SLEEP_MOTOR_ENABLE = 2 };
struct CCSleepFocStep {
    bool input;
    uint8_t action;
};

class CCSleepFoc {
public:
    explicit CCSleepFoc(float threshold = kCCSleepWakeRad)
        : threshold_(threshold), ref_(0.0f), primed_(false), off_(false), waking_(false),
          offAt_(0), movedAt_(0), wakeAt_(0) {}
    // `now` in any millisecond clock this thread uses consistently.
    CCSleepFocStep step(uint32_t now, float angle, bool asleep) {
        CCSleepFocStep out = {false, CC_SLEEP_MOTOR_KEEP};
        if (!primed_) { ref_ = angle; primed_ = true; movedAt_ = now; }
        bool moved = false;
        if (fabsf(angle - ref_) >= threshold_) { ref_ = angle; movedAt_ = now; moved = true; }
        if (!off_) {
            if (asleep) {
                off_ = true; waking_ = false; offAt_ = now; ref_ = angle;
                out.action = CC_SLEEP_MOTOR_DISABLE;
                return out;                       // a turn racing the sleep is not a wake
            }
            out.input = moved;
            return out;
        }
        if (asleep) {
            waking_ = false;
            if (static_cast<uint32_t>(now - offAt_) < kCCSleepDisableQuietMs) { ref_ = angle; return out; }
            out.input = moved;                    // the wake (the glue swallows it)
            return out;
        }
        // Woken (by this knob or a button): motor still off until the knob is still.
        if (!waking_) { waking_ = true; wakeAt_ = now; }
        out.input = moved;                        // keeps the timer fresh; not swallowed any more
        if (static_cast<uint32_t>(now - movedAt_) >= kCCSleepSettleMs ||
            static_cast<uint32_t>(now - wakeAt_) >= kCCSleepSettleMaxMs) {
            off_ = false; waking_ = false; ref_ = angle;
            out.action = CC_SLEEP_MOTOR_ENABLE;   // enable + re-anchor at `angle`
        }
        return out;
    }
    bool motorOff() const { return off_; }

private:
    float threshold_, ref_;
    bool primed_, off_, waking_;
    uint32_t offAt_, movedAt_, wakeAt_;
};

// The LCD while asleep (FW-BUG-016; LCD thread, once per pass before the host frame). The panel is dark,
// so nothing may be drawn or flushed: host frames are still rendered into the LVGL tree (it stays current)
// but no lv_refr_now() runs and the display refresh timer is paused. On the wake the screen is invalidated
// and refreshed once, and only then may the backlight return: dark() stays true through the wake pass
// until refreshed() is called, and backlightState() keeps the backlight at 0 until then.
enum CCSleepLcdStep : uint8_t { CC_SLEEP_LCD_KEEP = 0, CC_SLEEP_LCD_PAUSE = 1, CC_SLEEP_LCD_RESUME = 2 };
class CCSleepLcdGate {
public:
    CCSleepLcdGate() : dark_(false) {}
    // `state`: cc_sleep_state() read once for this pass. PAUSE: pause the refresh timer (now dark).
    // RESUME: resume it, render the latest frame, invalidate + refresh the whole screen, refreshed().
    uint8_t step(uint8_t state) {
        const bool asleep = state == CC_SLEEP_ASLEEP;
        if (asleep && !dark_) { dark_ = true; return CC_SLEEP_LCD_PAUSE; }
        if (!asleep && dark_) return CC_SLEEP_LCD_RESUME;
        return CC_SLEEP_LCD_KEEP;
    }
    // The wake refresh reached the panel.
    void refreshed() { dark_ = false; }
    // True: skip every lv_refr_now() (the panel is dark, or the wake refresh has not run yet).
    bool dark() const { return dark_; }
    // The sleep state the backlight follows: asleep until the wake refresh has run.
    uint8_t backlightState(uint8_t live) const { return dark_ ? static_cast<uint8_t>(CC_SLEEP_ASLEEP) : live; }

private:
    bool dark_;
};

// Button wake-swallow bookkeeping (HMI thread): a press that woke the knob is swallowed with its
// long press and its release, so the host never sees a hold or a key up without its key down.
// kind: CC_SLEEP_KEY_PRESS, _RELEASE or _OTHER (long press ...). True: drop this event.
enum CCSleepKeyKind : uint8_t { CC_SLEEP_KEY_PRESS = 0, CC_SLEEP_KEY_RELEASE = 1, CC_SLEEP_KEY_OTHER = 2 };
class CCSleepButtons {
public:
    CCSleepButtons() : swallowed_(0) {}
    // wokeByThis: this press woke the knob (cc_sleep_input() returned true for it).
    bool filter(uint8_t index, uint8_t kind, bool wokeByThis) {
        const uint8_t bit = static_cast<uint8_t>(1u << (index & 7u));
        if (kind == CC_SLEEP_KEY_PRESS) {
            if (wokeByThis) { swallowed_ = static_cast<uint8_t>(swallowed_ | bit); return true; }
            swallowed_ = static_cast<uint8_t>(swallowed_ & ~bit);
            return false;
        }
        const bool drop = (swallowed_ & bit) != 0;
        if (kind == CC_SLEEP_KEY_RELEASE) swallowed_ = static_cast<uint8_t>(swallowed_ & ~bit);
        return drop;
    }
    uint8_t swallowed() const { return swallowed_; }

private:
    uint8_t swallowed_;
};

// ---- firmware glue (cc_sleep.cpp) --------------------------------------------------------------
struct CCSleepSnapshot {
    uint8_t state;
    uint32_t idleMs;
};
// A physical input (any task): true when it woke the knob and must be swallowed.
bool cc_sleep_input();
// HMI task, every pass: advances the timer; returns the state.
uint8_t cc_sleep_tick();
// Any task: the current state (one byte).
uint8_t cc_sleep_state();
// COM task ({"diag":"?"}).
CCSleepSnapshot cc_sleep_snapshot();
