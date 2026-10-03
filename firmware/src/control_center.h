#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
#include "haptic_api.h"
#include "cc_presentation.h"

// Runtime-only host session. No persisted profile, calibration or motor gain changes.
struct CCControl {
    bool release = false;
    uint32_t id = 0;
    DetentProfile profile;
    uint16_t position = 0;
    // r4 FEEL + SOUND (1.0.0-cc5.7, plan F2/F3; HAPTICS.md), each from the control command and never stored on the
    // knob: `feel` (capability feel 1; CCFeel, 0 = none: the legacy haptic loop), `reducedHaptics` (the r4 section
    // 7 fallbacks) and `sound`: the master volume percent 0..100, from `soundVolume` (capability knobVolume 1) or the
    // older `sound` level (capability knobSound 1; 0 off, 1 Low, 2 Medium, 3 High; cc_sound_volume_of_level). A
    // control without them (any older host) gets 0 / false / 0: the 1.0.0-cc5.6 feel and no sound.
    uint8_t feel = 0;
    bool reducedHaptics = false;
    uint8_t sound = 0;
};
bool cc_handle_command(JsonDocument& doc);
void cc_service(); // serial replies, only from COM thread
bool cc_claimed();
// FW-BUG-029: the COM task asked the FOC task for a recalibration (after cc_cal_request()); a {"control"} is refused
// ("Recalibrating; wait for calibrated") from then until that run has finished.
void cc_cal_requested();
bool cc_timeout_notice(); // True only after a lease timeout has restored native control.
uint32_t cc_input_id(); // zero while entering/releasing
// The session's current frame. Its `reducedMotion` is the EFFECTIVE latched value (PRESENTATION_V5
// 7.1: latched on acceptance, kept by frames without the field, false after every claim);
// `reducedMotionPresent` still says whether this frame's wire carried the field.
bool cc_snapshot(CCFrame& frame, uint32_t& id, uint32_t& version, uint8_t& windowsButton);
// Cheap change peek for the LCD thread. The value changes (never repeats in
// practice) whenever anything cc_snapshot()/cc_timeout_notice() could report
// differently: frame version, artwork version, every session phase transition
// (including releasing -> idle) and timeout-notice changes. Read it BEFORE
// cc_snapshot(); an equal value on the next pass means the snapshot is current.
uint32_t cc_presentation_state();
bool cc_take_request(CCControl& request); // FOC thread also enforces lease
void cc_motor_applied(uint32_t id, uint16_t position);
bool cc_can_arm(uint32_t id);
void cc_motor_ready(uint32_t id, uint16_t position);
void cc_hmi_applied(uint32_t id);
void cc_lcd_applied(uint32_t id);
// F24 for this raw press (PRESENTATION_V5 11.4): ready (ready line sent), windowsHidEnabled, raw ==
// windowsButton, and that raw's physical slot is enabled with icon `win` (the cc5.4 icon gate).
bool cc_is_windows_button(uint8_t index);
uint8_t cc_physical_button(uint8_t rawIndex);
// {"diag":"?"} sources (bytes). The LCD thread publishes the LVGL heap (it is the
// only thread allowed to call LVGL) and its own stack high-water mark; the HMI
// thread publishes its stack. Both call these periodically; the COM thread reads.
void cc_diag_lcd(uint32_t lvglFree, uint32_t lvglMinFree, uint32_t stackLcd);
void cc_diag_hmi(uint32_t stackHmi);

// "Warm · alive" LEDs (1.0.0-cc5.4, ALIVE.md sections 3 and 10.1).
//
// Latched frame fields. The COM task latches clock, progress, ledDrive and ledDither when it
// ACCEPTS a control or frame command that carries them (next_version()), stamped with the
// knob's millis() of that acceptance, under the session lock; never on an HMI pass, so a frame
// the HMI never snapshots (two accepted between two passes) still latches. `seq` moves on
// every acceptance that latched at least one field, and each time-stamped field keeps the seq
// of its own latch, so the HMI re-applies only the fields that moved (re-applying an older
// progress would undo the engine's pause freeze). ledDrive/ledDither stay latched until reboot.
// Presentation 5 (PRESENTATION_V5 sections 7.1 and 7.3; ALIVE.md 3, 3.2) adds reducedMotion,
// which every claim (unclaimed -> claimed) resets to false before the claiming control's own
// frame latches it, and the LED tuning fields ledPink / ledVolFull, kept until reboot like
// ledDrive. motionSeq / tuningSeq are the seq of their newest latch (or claim reset), so the
// HMI applies them to the engine only when they moved.
struct CCAliveLatch {
    uint32_t seq = 0;                      // 0 = nothing latched since boot
    uint32_t clockSeq = 0;                 // seq of the newest clock latch (0 = none)
    uint16_t clockMinute = 0;              // 0..1439
    uint32_t clockAt = 0;                  // millis() at its acceptance
    uint32_t progressSeq = 0;              // seq of the newest progress latch (0 = none)
    uint32_t progressPos = 0, progressDur = 0;   // ms; dur 0 clears
    uint32_t progressAt = 0;               // millis() at its acceptance
    bool ledDrivePresent = false;
    uint8_t ledDrive = 0;                  // 1..255 (the HMI clamps it to ledMaxBrightness)
    bool ledDitherPresent = false;
    bool ledDither = false;                // unset = off (CCAliveSpec::defaultDither, ALIVE.md 9)
    uint32_t motionSeq = 0;                // seq of the newest reducedMotion latch or claim reset
    bool reducedMotion = false;            // section 7.1; false after every claim
    uint32_t tuningSeq = 0;                // seq of the newest ledPink / ledVolFull latch (0 = none)
    bool ledPinkPresent = false;
    uint32_t ledPink = 0;                  // 0..0xFFFFFF; 0 = the built-in PINK (section 7.3)
    bool ledVolFullPresent = false;
    bool ledVolFull = false;
};
// HMI task: copies the latch into `out` and returns true when its seq differs from `seen`.
bool cc_alive_latch(CCAliveLatch& out, uint32_t seen);
// HMI task: the effective default drive, min(150, ledMaxBrightness) (ALIVE.md section 9), which
// {"capabilities":"?"} reports as alive.drive. 150 until the HMI task first publishes it.
void cc_alive_default_drive(uint8_t drive);
// HMI task: an end-stop push of control `id` (ALIVE.md 12.5 [Q1]: every push into a bound, from
// CCAliveKnob), dir -1 at position 0 and +1 at max. One slot (the newest wins). The COM task's
// cc_service() sends it as {"id":<id>,"lim":<dir>} only while `id` is the ready control, at most
// one per 150 ms (a push inside that spacing is dropped, never delayed), and drops it otherwise.
void cc_post_limit(uint32_t id, int8_t dir);

// Presentation 5 knob -> host input (PRESENTATION_V5 section 11; 1.0.0-cc5.4).
//
// HMI task: the raw bitmask 0..15 of the buttons down now (HmiThread::keyState), published on
// every change. The ready line carries it as "ks" (11.3), and a deferred hold is sent only while
// its raw is still down (11.2 step 5). One byte: atomic.
void cc_publish_key_state(uint8_t mask);
// COM task only. A hold (kh, 11.2) whose KeyEvt carries control id 0 matured while no control was
// ready (the session was entering): latch it in the one pendingHold slot. It is sent as
// {"id":<ready id>,"ks":mask,"kh":raw} right after the next ready line of the session (at once
// when that line already went), if the raw is still down; a key-up of that raw, a release and a
// new claim clear the slot, and a re-entry (a new control of the same session) keeps it. A hold
// seen while idle or releasing is dropped. At most one kh per physical press.
void cc_hold_deferred(uint8_t raw);
// COM task only: a key-up of `raw`, seen whether or not the event is forwarded (11.2 step 5).
void cc_hold_key_up(uint8_t raw);
// COM task only: a kh line sent directly (a hold of the ready control), for diag holdEvents.
void cc_hold_sent();
// 1.0.0-cc5.5 (F1), COM task only: the clear-only key state of position lines. cc_key_line_sent(): a kd,
// ku or kh line of the ready control went out with `ks` = mask (the ready line and a deferred kh record
// theirs inside control_center.cpp). cc_live_key_state(): the HMI's published mask now.
// cc_position_key_state(): the `ks` a position line of the ready control carries, reported & live, so a
// position line can clear a bit the host still holds (a key-up lost to a full key queue) but never set
// one; while key events are still queued (keyEventsPending, read by the caller AFTER `live`: the HMI
// queues a ku before it publishes the cleared bit) it reports the last mask unchanged, so a key-up on
// its way is never pre-empted by a position line. An installed v7 Desk Dial, which copies any `ks` into
// its pressed mask, therefore never loses a kd or a ku to a position line.
void cc_key_line_sent(uint8_t mask);
uint8_t cc_live_key_state();
uint8_t cc_position_key_state(uint8_t live, bool keyEventsPending);

// Native button input while unclaimed (PRESENTATION_V5 8.10; ALIVE.md 8.1: "an FOC position
// change or a button state change while unclaimed"), for the LCD's offline screen.
//
// HMI task only: one button edge (kEventPressed or kEventReleased) handled by the unclaimed
// (native) branch of the button handler. The native long press is not an edge (11.2 step 3).
void cc_native_button_edge();
// Any task: the number of native button edges since boot (wraps; one aligned word that only the
// HMI task writes). The LCD thread keeps the value it saw when the offline layer appeared; any
// other value later is the first native input (the sub-line swaps to `Knob controls still work`),
// as a position change is. A counter rather than the key mask: a tap that is over between two LCD
// passes leaves the mask unchanged but moves the counter.
uint32_t cc_native_button_seq();
