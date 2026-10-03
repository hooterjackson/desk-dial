// FW-BUG-045 test_wake_turn_does_not_move_cube: the app canvas (the firmware's unchanged cc_app_* units) driven the way
// lcd_thread.cpp drives it, a pass every 5 ms: the hold (src/cc_lcd_logic.h CCAppAngleHold) is stepped every pass
// with the raw shaft angle and the sleep state; the canvas steps only while awake, with the held angle. Compiled by
// lcd_thread_tests.py (MSVC /W4 /WX).
//
// Timeline (zoom slot, the default): rest, then asleep 1 s; the user turns 0.35 rad to wake (the sleep state turns
// awake once the turn passes 2 deg, the turn goes on), then lets go. Control (the raw angle, as before): the first
// awake pass draws a zoomed cube for a turn the host never got. Fixed: nothing is drawn for the wake turn or a turn
// inside the post-wake settle; a turn once the motor is back zooms one-for-one.
#include "cc_lcd_logic.h"
#include "cc_app_canvas.h"

#include <cstdio>
#include <cstring>
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

constexpr uint32_t PASS_MS = 5;
constexpr int32_t WAKE_UNITS = 349 + 1;   // CC_SLEEP_WAKE_DEG (2 deg) in 1e-4 rad: the turn that wakes the knob

uint16_t frame[240 * 240];
ccui::PlasmaTables tables;

struct Rig {
    bool fixed;
    CCAppCanvas canvas;
    CCAppAngleHold hold;
    uint32_t now;
    int32_t raw;
    bool asleep;
    int draws;
    // One LCD pass (render_host_frame()'s app branch).
    bool pass() {
        now += PASS_MS;
        const int32_t held = hold.step(raw, asleep, now);
        if (asleep) return false;
        CCAppInputs in;
        in.nowMs = now;
        in.angle = fixed ? held : raw;
        in.buttons = 0;
        const bool drew = canvas.step(in);
        if (drew) ++draws;
        return drew;
    }
    int passes(int n) {
        const int before = draws;
        for (int i = 0; i < n; ++i) pass();
        return draws - before;
    }
};

void wake_turn(bool fixed) {
    Rig r;
    r.fixed = fixed;
    r.now = 100000;
    r.raw = 123456;   // anywhere on the shaft
    r.asleep = false;
    r.draws = 0;
    tables.ready = false;
    r.canvas.begin(frame, &tables, 12);
    CCAppState state;
    std::strcpy(state.id, "onshape");   // the built-in Onshape (app profiles: the id is text)
    state.slot = CC_APP_SLOT_ZOOM;
    CCAppInputs in;
    in.nowMs = r.now;
    in.angle = fixed ? r.hold.step(r.raw, false, r.now) : r.raw;
    r.canvas.enter(state, in);
    EXPECT(r.passes(60) > 0);                  // the first frame
    EXPECT(r.passes(60) == 0);                 // at rest: nothing
    const std::vector<uint16_t> before(frame, frame + 240 * 240);

    r.asleep = true;
    r.passes(200);                             // 1 s asleep (the canvas does not step)
    // The wake turn: 0.35 rad over 100 ms; the sleep state turns awake once it passes 2 deg.
    const int32_t start = r.raw;
    for (int i = 1; i <= 20; ++i) {
        r.raw = start + 3500 * i / 20;
        if (r.raw - start >= WAKE_UNITS) r.asleep = false;
        r.pass();
    }
    r.passes(31);                              // 155 ms: the knob still, the FOC's motor still off
    std::printf("wake turn (%s): %d draw(s) for the wake turn and its settle\n", fixed ? "fixed" : "control",
                r.draws - 1);
    if (!fixed) {
        EXPECT(r.draws > 1);                   // the finding: the cube zoomed for the swallowed wake turn
        return;
    }
    EXPECT(r.draws == 1);                      // only the first frame, before the sleep
    EXPECT(std::memcmp(before.data(), frame, sizeof(frame)) == 0);
    EXPECT(r.hold.holding());                  // the motor-off settle is still running (300 ms of stillness)
    // A turn inside the settle (the FOC's motor still off, no position moves): swallowed too.
    for (int i = 1; i <= 10; ++i) {
        r.raw += 100;
        r.pass();
    }
    EXPECT(r.draws == 1);
    r.passes(80);                              // 400 ms still: the FOC enables the motor again
    EXPECT(!r.hold.holding());
    EXPECT(r.draws == 1);
    // A turn with the motor on zooms the cube, one-for-one from where it was.
    for (int i = 1; i <= 10; ++i) {
        r.raw += 350;
        r.pass();
    }
    EXPECT(r.draws > 1);
}
}  // namespace

int main() {
    wake_turn(false);
    wake_turn(true);
    std::printf("%s: %d check(s), %d failure(s)\n", failures ? "FAIL" : "PASS", checks, failures);
    return failures ? 1 : 0;
}
