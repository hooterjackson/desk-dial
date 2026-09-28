// Inactivity dim / sleep (2026-09-28): host checks of the unchanged firmware header
// src/cc_sleep.h (sleep_tests.py compiles this with MSVC /W4 /WX and runs it).
//   1. the timer: awake -> dim -> asleep, the reset rules, swallow-first-input, 0 = stage off,
//      millis() wrap, a racing input stamped after the caller's clock, the idle cap;
//   2. the FOC knob watcher: the rotation threshold (noise below it never counts), disable once,
//      the cogging quiet window, the wake turn, the settle before enable, the settle cap, a button
//      wake (no motion) enabling at once, and a sleep racing a turn;
//   3. the button swallow bookkeeping (press + long press + release of the waking press only);
//   4. the backlight clamp.
#include "cc_sleep.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>

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

constexpr float kDeg = 0.017453292519943f;

void machine_tests() {
    // Defaults are the user's decisions: 10 min dim, 60 min sleep.
    EXPECT(kCCSleepDimMs == 600000u);
    EXPECT(kCCSleepOffMs == 3600000u);
    EXPECT(kCCSleepDimDuty == 640);

    CCSleepMachine m;
    m.begin(1000);
    EXPECT(m.tick(1000) == CC_SLEEP_AWAKE);
    EXPECT(m.tick(1000 + 599999) == CC_SLEEP_AWAKE);
    EXPECT(m.tick(1000 + 600000) == CC_SLEEP_DIM);
    EXPECT(m.idleMs(1000 + 600000) == 600000u);
    // An input while dim: awake again, not swallowed (it acts normally), timer restarts.
    EXPECT(!m.input(1000 + 700000));
    EXPECT(m.state() == CC_SLEEP_AWAKE);
    EXPECT(m.tick(1000 + 700000 + 599999) == CC_SLEEP_AWAKE);
    EXPECT(m.tick(1000 + 700000 + 600000) == CC_SLEEP_DIM);
    EXPECT(m.tick(1000 + 700000 + 3599999) == CC_SLEEP_DIM);
    EXPECT(m.tick(1000 + 700000 + 3600000) == CC_SLEEP_ASLEEP);
    // Asleep stays asleep with time (no host input exists in this API: only input() wakes).
    EXPECT(m.tick(1000 + 700000 + 3600000 + 86400000u) == CC_SLEEP_ASLEEP);
    // The first input wakes and is swallowed; the next one acts normally.
    const uint32_t wakeAt = 1000 + 700000 + 3600000 + 86400000u + 5;
    EXPECT(m.input(wakeAt));
    EXPECT(m.state() == CC_SLEEP_AWAKE);
    EXPECT(m.idleMs(wakeAt) == 0u);
    EXPECT(!m.input(wakeAt + 10));
    EXPECT(m.tick(wakeAt + 20) == CC_SLEEP_AWAKE);

    // Jumping straight past both timeouts in one tick goes to asleep (a long HMI stall).
    CCSleepMachine j;
    j.begin(0);
    EXPECT(j.tick(4000000) == CC_SLEEP_ASLEEP);

    // Awake inputs keep the timer fresh forever.
    CCSleepMachine k;
    k.begin(0);
    for (uint32_t t = 0; t < 10u * 3600000u; t += 500000) {
        EXPECT(!k.input(t));
        EXPECT(k.tick(t + 499999) == CC_SLEEP_AWAKE);
    }

    // Test timeouts (-DCC_SLEEP_DIM_MS=20000 -DCC_SLEEP_OFF_MS=60000 equivalent).
    CCSleepMachine s(20000, 60000);
    s.begin(0);
    EXPECT(s.tick(19999) == CC_SLEEP_AWAKE);
    EXPECT(s.tick(20000) == CC_SLEEP_DIM);
    EXPECT(s.tick(60000) == CC_SLEEP_ASLEEP);

    // 0 disables a stage.
    CCSleepMachine noDim(0, 60000);
    noDim.begin(0);
    EXPECT(noDim.tick(59999) == CC_SLEEP_AWAKE);
    EXPECT(noDim.tick(60000) == CC_SLEEP_ASLEEP);
    CCSleepMachine noOff(20000, 0);
    noOff.begin(0);
    EXPECT(noOff.tick(20000) == CC_SLEEP_DIM);
    EXPECT(noOff.tick(0x3FFFFFFFu) == CC_SLEEP_DIM);
    // Dim longer than off: straight to asleep at off.
    CCSleepMachine inverted(90000, 60000);
    inverted.begin(0);
    EXPECT(inverted.tick(60000) == CC_SLEEP_ASLEEP);

    // millis() wrap: the timer runs across 0xFFFFFFFF -> 0.
    CCSleepMachine w;
    const uint32_t start = 0xFFFFFFFFu - 100000u;
    w.begin(start);
    EXPECT(w.tick(start + 599999u) == CC_SLEEP_AWAKE);       // wrapped
    EXPECT(w.idleMs(start + 599999u) == 599999u);
    EXPECT(w.tick(start + 600000u) == CC_SLEEP_DIM);
    EXPECT(w.tick(start + 3600000u) == CC_SLEEP_ASLEEP);
    EXPECT(w.input(start + 3600001u));

    // A racing input on another core, stamped after this caller read its clock: idle 0, never a
    // wrapped "very long idle" (that would put the knob to sleep at once).
    CCSleepMachine r;
    r.begin(0);
    r.input(5001);
    EXPECT(r.idleMs(5000) == 0u);
    EXPECT(r.tick(5000) == CC_SLEEP_AWAKE);

    // The idle cap: after days asleep the reported idle saturates and never wraps.
    CCSleepMachine c;
    c.begin(0);
    uint32_t t = 0;
    for (int i = 0; i < 400; ++i) { t += 86400000u / 4; c.tick(t); }   // 100 days, ticked every 6 h
    EXPECT(c.state() == CC_SLEEP_ASLEEP);
    EXPECT(c.idleMs(t) == kCCSleepIdleCap);
    EXPECT(c.idleMs(t + 1000) >= kCCSleepIdleCap);
    EXPECT(c.input(t + 1000));
}

void foc_tests() {
    EXPECT(kCCSleepWakeRad > 1.99f * kDeg && kCCSleepWakeRad < 2.01f * kDeg);

    // Awake: sensor noise below the threshold never counts; a 2 degree turn does, once per 2 degrees.
    CCSleepFoc f;
    uint32_t now = 0;
    const float base = 1.2345f;
    CCSleepFocStep st = f.step(now, base, false);
    EXPECT(!st.input && st.action == CC_SLEEP_MOTOR_KEEP);
    int inputs = 0;
    for (int i = 0; i < 2000; ++i) {
        const float noise = ((i * 7919) % 200 - 100) * 0.0001f;   // +-0.01 rad (0.57 degree)
        st = f.step(++now, base + noise, false);
        inputs += st.input;
        EXPECT(st.action == CC_SLEEP_MOTOR_KEEP);
    }
    EXPECT(inputs == 0);
    st = f.step(++now, base + 1.9f * kDeg, false);
    EXPECT(!st.input);
    st = f.step(++now, base + 2.05f * kDeg, false);
    EXPECT(st.input);
    st = f.step(++now, base + 3.0f * kDeg, false);
    EXPECT(!st.input);                                            // 0.95 degree since the reference
    st = f.step(++now, base - 0.5f * kDeg, false);
    EXPECT(st.input);                                             // back 2.55 degrees
    EXPECT(!f.motorOff());

    // Asleep: disable exactly once; nothing is an input yet.
    float angle = base - 0.5f * kDeg;
    st = f.step(++now, angle, true);
    EXPECT(st.action == CC_SLEEP_MOTOR_DISABLE && !st.input);
    EXPECT(f.motorOff());
    st = f.step(++now, angle, true);
    EXPECT(st.action == CC_SLEEP_MOTOR_KEEP && !st.input);
    // The rotor settles into a cogging position within the quiet window: not a wake.
    const uint32_t offAt = now - 1;
    angle += 2.4f * kDeg;
    for (; now < offAt + kCCSleepDisableQuietMs - 1; ++now) {
        st = f.step(now, angle, true);
        EXPECT(!st.input && st.action == CC_SLEEP_MOTOR_KEEP);
    }
    // After it, noise stays silent for an hour of passes (every 50 ms here).
    for (int i = 0; i < 72000; ++i) {
        now += 50;
        const float noise = ((i * 104729) % 200 - 100) * 0.0001f;
        st = f.step(now, angle + noise, true);
        EXPECT(!st.input && st.action == CC_SLEEP_MOTOR_KEEP);
        if (st.input) break;
    }
    EXPECT(f.motorOff());
    // The wake turn: the first 2 degrees are the input (the glue swallows it) ...
    angle += 2.2f * kDeg;
    st = f.step(++now, angle, true);
    EXPECT(st.input && st.action == CC_SLEEP_MOTOR_KEEP);
    // ... the glue woke the machine: the motor stays off while the knob keeps turning ...
    const uint32_t wokeAt = now;
    for (int i = 0; i < 40; ++i) {
        angle += 0.5f * kDeg;
        st = f.step(now += 10, angle, false);
        EXPECT(st.action == CC_SLEEP_MOTOR_KEEP);
        EXPECT(f.motorOff());
    }
    // ... and comes back (enable + re-anchor) once the knob has been still for the settle time.
    const uint32_t stillFrom = now;
    bool enabled = false;
    while (!enabled && now < stillFrom + 1000) {
        st = f.step(++now, angle, false);
        enabled = st.action == CC_SLEEP_MOTOR_ENABLE;
        EXPECT(!st.input);
    }
    EXPECT(enabled);
    EXPECT(now - stillFrom + 50 >= kCCSleepSettleMs && now - stillFrom <= kCCSleepSettleMs + 50);
    EXPECT(now - wokeAt < kCCSleepSettleMaxMs);
    EXPECT(!f.motorOff());
    // The reference is the re-anchor angle: no input for standing still after it.
    st = f.step(++now, angle, false);
    EXPECT(!st.input && st.action == CC_SLEEP_MOTOR_KEEP);

    // The settle cap: a knob that keeps turning is re-enabled after kCCSleepSettleMaxMs.
    CCSleepFoc g;
    now = 1000;
    angle = 0.0f;
    g.step(now, angle, false);
    g.step(++now, angle, true);                                  // disable
    now += kCCSleepDisableQuietMs + 10;
    angle += 3.0f * kDeg;
    st = g.step(now, angle, true);
    EXPECT(st.input);                                            // the wake
    const uint32_t capFrom = now;
    enabled = false;
    while (!enabled && now < capFrom + 5000) {
        angle += 3.0f * kDeg;                                    // 3 degrees every 20 ms
        now += 20;
        st = g.step(now, angle, false);
        enabled = st.action == CC_SLEEP_MOTOR_ENABLE;
    }
    EXPECT(enabled);
    EXPECT(now - capFrom >= kCCSleepSettleMaxMs && now - capFrom <= kCCSleepSettleMaxMs + 40);

    // A button wake with the knob still: enable on the first awake pass.
    CCSleepFoc b;
    now = 50000;
    b.step(now, 0.3f, false);
    b.step(++now, 0.3f, true);
    for (int i = 0; i < 100; ++i) b.step(now += 100, 0.3f, true);
    st = b.step(++now, 0.3f, false);
    EXPECT(st.action == CC_SLEEP_MOTOR_ENABLE && !st.input);

    // A turn racing the sleep: the pass that disables never reports the turn as a wake.
    CCSleepFoc race;
    now = 0;
    race.step(now, 0.0f, false);
    st = race.step(++now, 5.0f * kDeg, true);
    EXPECT(st.action == CC_SLEEP_MOTOR_DISABLE && !st.input);

    // The FOC clock wraps too.
    CCSleepFoc wrap;
    now = 0xFFFFFFFFu - 100u;
    wrap.step(now, 0.0f, false);
    wrap.step(++now, 0.0f, true);
    now += kCCSleepDisableQuietMs + 5;                           // wrapped
    st = wrap.step(now, 2.5f * kDeg, true);
    EXPECT(st.input);
    for (int i = 0; i < 40; ++i) { st = wrap.step(now += 10, 2.5f * kDeg, false); if (st.action) break; }
    EXPECT(st.action == CC_SLEEP_MOTOR_ENABLE);
}

void button_tests() {
    CCSleepButtons b;
    // A normal press/long/release passes.
    EXPECT(!b.filter(0, CC_SLEEP_KEY_PRESS, false));
    EXPECT(!b.filter(0, CC_SLEEP_KEY_OTHER, false));
    EXPECT(!b.filter(0, CC_SLEEP_KEY_RELEASE, false));
    // The waking press: press, long press and release are all dropped; other buttons unaffected.
    EXPECT(b.filter(2, CC_SLEEP_KEY_PRESS, true));
    EXPECT(b.swallowed() == 0x4);
    EXPECT(b.filter(2, CC_SLEEP_KEY_OTHER, false));
    EXPECT(!b.filter(1, CC_SLEEP_KEY_PRESS, false));
    EXPECT(!b.filter(1, CC_SLEEP_KEY_RELEASE, false));
    EXPECT(b.filter(2, CC_SLEEP_KEY_RELEASE, false));
    EXPECT(b.swallowed() == 0);
    // The next press of the same button acts normally.
    EXPECT(!b.filter(2, CC_SLEEP_KEY_PRESS, false));
    EXPECT(!b.filter(2, CC_SLEEP_KEY_RELEASE, false));
    // A release that wakes (its press was before the sleep) is never dropped: key state stays right.
    EXPECT(!b.filter(3, CC_SLEEP_KEY_RELEASE, false));
}

void backlight_tests() {
    EXPECT(cc_sleep_duty(CC_SLEEP_AWAKE, 3200) == 3200);
    EXPECT(cc_sleep_duty(CC_SLEEP_AWAKE, 320) == 320);
    EXPECT(cc_sleep_duty(CC_SLEEP_DIM, 3200) == 640);          // the PC-driven render's MAX, dimmed
    EXPECT(cc_sleep_duty(CC_SLEEP_DIM, 320) == 320);           // the native 5 s dim stays below
    EXPECT(cc_sleep_duty(CC_SLEEP_ASLEEP, 3200) == 0);
    EXPECT(cc_sleep_duty(CC_SLEEP_ASLEEP, 320) == 0);
    EXPECT(std::strcmp(cc_sleep_state_name(CC_SLEEP_AWAKE), "awake") == 0);
    EXPECT(std::strcmp(cc_sleep_state_name(CC_SLEEP_DIM), "dim") == 0);
    EXPECT(std::strcmp(cc_sleep_state_name(CC_SLEEP_ASLEEP), "asleep") == 0);
}
}  // namespace

int main() {
    machine_tests();
    foc_tests();
    button_tests();
    backlight_tests();
    std::printf("sleep_tests: %d check(s), %d failure(s)\n", checks, failures);
    return failures ? EXIT_FAILURE : EXIT_SUCCESS;
}
