// Inactivity dim / sleep glue (cc_sleep.h). The machine is shared by the HMI task (buttons and the
// per-pass tick), the FOC task (knob rotation) and the COM task (diag), under one short spinlock;
// the state is also mirrored in one byte for lock-free reads (LCD backlight, LEDs, FOC).
#include "cc_sleep.h"
#include <Arduino.h>
#include "com_thread.h"

namespace {
portMUX_TYPE sleepLock = portMUX_INITIALIZER_UNLOCKED;
CCSleepMachine machine;              // timer from boot (millis() 0)
volatile uint8_t sleepState = CC_SLEEP_AWAKE;
}

bool cc_sleep_input() {
    const uint32_t now = static_cast<uint32_t>(millis());
    portENTER_CRITICAL(&sleepLock);
    const bool swallow = machine.input(now);
    sleepState = machine.state();
    portEXIT_CRITICAL(&sleepLock);
    // A wake is a physical interaction: the native path's stock 5 s idle dim (com_thread
    // global_sleep_flag) restarts too, so the screen comes back at its full brightness. The
    // swallowed input itself sends nothing. One aligned word; the COM task writes "now" too.
    if (swallow) com_thread.ts_last_activity = millis();
    return swallow;
}

uint8_t cc_sleep_tick() {
    const uint32_t now = static_cast<uint32_t>(millis());
    portENTER_CRITICAL(&sleepLock);
    const uint8_t state = machine.tick(now);
    sleepState = state;
    portEXIT_CRITICAL(&sleepLock);
    return state;
}

uint8_t cc_sleep_state() { return sleepState; }

CCSleepSnapshot cc_sleep_snapshot() {
    const uint32_t now = static_cast<uint32_t>(millis());
    CCSleepSnapshot s;
    portENTER_CRITICAL(&sleepLock);
    s.state = machine.state();
    s.idleMs = machine.idleMs(now);
    portEXIT_CRITICAL(&sleepLock);
    return s;
}
