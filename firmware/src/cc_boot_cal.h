// FW-TST-009: the boot calibration's pure rules, header-only and platform-neutral (no Arduino, no SimpleFOC), so
// harness/haptic_fx_tests.cpp compiles this same file with MSVC and cpp11_gate.py with the device's gnu++11.
// foc_thread.cpp applies them: setCalibration() (main.cpp hands it the Preferences values) and the boot store after
// initFOC().
//
// Directions are SimpleFOC's Direction values: CW 1, CCW -1, UNKNOWN 0. Preferences keeps the direction as an
// unsigned byte (putUChar): CCW reads back as 255 through a uint8_t, -1 through MotorCalibration's int8_t.
#pragma once

#include <math.h>
#include <stdint.h>

constexpr float CC_BOOT_CAL_NOT_SET = -12345.0f;              // SimpleFOC NOT_SET (foc_thread.cpp static_asserts it)
constexpr float CC_BOOT_CAL_ZERO_MAX = 6.2832f;               // zero_electric_angle is _normalizeAngle()d: [0, 2 pi]
constexpr int CC_BOOT_CAL_CW = 1;
constexpr int CC_BOOT_CAL_CCW = -1;
constexpr int CC_BOOT_CAL_UNKNOWN = 0;

struct CCBootCal {
    int direction;   // CC_BOOT_CAL_CW / CC_BOOT_CAL_CCW / CC_BOOT_CAL_UNKNOWN
    float zero;      // the zero electric angle, or CC_BOOT_CAL_NOT_SET
};

// A zero electric angle the alignment can be skipped with (NaN and the infinities fail every comparison / range).
inline bool cc_boot_cal_zero_ok(float zero) {
    return zero == zero && zero >= 0.0f && zero <= CC_BOOT_CAL_ZERO_MAX;
}

// The stored pair -> what initFOC() starts from. Only a whole, plausible pair is used: a direction byte of 0 / 1 /
// 255 (-1) and a finite zero in [0, 2 pi]. Anything else (another firmware's byte, a NaN zero, a missing key: the
// direction without its zero or the zero without its direction) starts uncalibrated, so initFOC() runs the whole
// alignment (direction and zero together, with its pole-pair check) and the boot store writes a consistent pair.
// Before this, any byte other than 0 / 1 read as CCW, any float was taken as the zero, and a known direction with
// zero NOT_SET re-aligned the zero on every boot without ever saving (the store fired only on a direction change).
inline CCBootCal cc_cal_from_nvs(int directionByte, float zero) {
    const int direction = directionByte == 1 ? CC_BOOT_CAL_CW
                        : (directionByte == 255 || directionByte == -1) ? CC_BOOT_CAL_CCW
                        : CC_BOOT_CAL_UNKNOWN;
    CCBootCal out;
    const bool whole = direction != CC_BOOT_CAL_UNKNOWN && cc_boot_cal_zero_ok(zero);
    out.direction = whole ? direction : CC_BOOT_CAL_UNKNOWN;
    out.zero = whole ? zero : CC_BOOT_CAL_NOT_SET;
    return out;
}

// The boot store (after initFOC()): true when the alignment succeeded (initResult != 0), its pole-pair check passed,
// it left a whole calibration, and that differs from what the boot started with (either value: a re-aligned zero is
// stored too). FW-PUB-006: a hand dragging the knob during the first-boot sweep moves the shaft the wrong distance;
// SimpleFOC only logs the failed pole-pair check and initFOC() still returns 1, so the bad pair was stored and every
// later boot skipped the alignment with it (weak / inverted torque, a buzz or a runaway) until a recalibration.
// `poleCheckOk` is SimpleFOC's pp_check_result of this alignment (cc_boot_pp_check() models it): on a failure the
// calibration stays in RAM for this session only and the next boot aligns again.
inline bool cc_boot_cal_store(const CCBootCal& before, const CCBootCal& after, int initResult, bool poleCheckOk) {
    if (initResult == 0 || !poleCheckOk) return false;
    if (after.direction == CC_BOOT_CAL_UNKNOWN || !cc_boot_cal_zero_ok(after.zero)) return false;
    return after.direction != before.direction || after.zero != before.zero;
}

// SimpleFOC's pole-pair check (BLDCMotor::alignSensor(): one electrical turn must move the shaft 2 pi / pole pairs,
// |moved x pp - 2 pi| <= 0.5) for the host model; the firmware reads motor.pp_check_result.
inline bool cc_boot_pp_check(float movedRad, int polePairs) {
    const float m = movedRad < 0.0f ? -movedRad : movedRad;
    const float e = m * static_cast<float>(polePairs) - 6.28318531f;
    return polePairs > 0 && e <= 0.5f && e >= -0.5f;
}

// The motor's calibration state, FOC task -> other tasks (one aligned word, single writer). The LCD shows a
// "hands off" cue while ALIGNING (FW-PUB-006). UNSTORED: running on a calibration whose pole-pair check failed, kept in
// RAM only (the next boot aligns again).
enum CCMotorCal : uint8_t {
    CC_MOTOR_CAL_STARTING = 0, CC_MOTOR_CAL_ALIGNING, CC_MOTOR_CAL_READY, CC_MOTOR_CAL_UNSTORED, CC_MOTOR_CAL_FAILED
};
namespace cc_boot_cal_detail {
inline volatile uint32_t& motor_cal_word() { static volatile uint32_t word = CC_MOTOR_CAL_STARTING; return word; }
}  // namespace cc_boot_cal_detail
inline void cc_motor_cal_post(uint8_t state) { cc_boot_cal_detail::motor_cal_word() = state; }
inline uint8_t cc_motor_cal_state() { return static_cast<uint8_t>(cc_boot_cal_detail::motor_cal_word()); }
inline bool cc_motor_cal_hands_off() { return cc_motor_cal_state() == CC_MOTOR_CAL_ALIGNING; }
// After the boot alignment: what the FOC task posts.
inline uint8_t cc_boot_cal_outcome(int initResult, bool aligned, bool poleCheckOk) {
    return initResult == 0 ? CC_MOTOR_CAL_FAILED
         : (aligned && !poleCheckOk) ? CC_MOTOR_CAL_UNSTORED
         : CC_MOTOR_CAL_READY;
}

// FW-BUG-030: a boot whose alignment failed (initFOC() 0: e.g. the knob held, no movement seen) leaves SimpleFOC's
// motor_status calib_failed, the driver disabled and the direction UNKNOWN (shaftAngle() is always 0: no detents, no
// events, no turn-to-wake). The inactivity sleep's wake enabled the driver unconditionally, energising an
// uncommutated motor (a constant electrical angle). Only a calibrated motor is enabled on a wake.
inline bool cc_motor_wake_enable(bool motorReady) { return motorReady; }

// ... and the alignment is retried ONCE, after the knob has been idle (no key held, not claimed, not asleep) for
// CC_BOOT_RETRY_IDLE_MS since the failure (the LCD shows "hands off" again while it runs; a second failure stays
// failed: "calibration failed - replug").
constexpr uint32_t CC_BOOT_RETRY_IDLE_MS = 5000;
class CCBootRetry {
public:
    CCBootRetry() : armed_(false), done_(false), sinceMs_(0) {}
    void failed(uint32_t nowMs) { if (!done_) { armed_ = true; sinceMs_ = nowMs; } }
    // One FOC pass: true exactly once, when the retry is due. `motorReady` (SimpleFOC motor_status == motor_ready):
    // a motor calibrated some other way meanwhile (a Desk Dial Recalibrate) disarms the retry for good, so it never
    // re-sweeps a motor that was just calibrated (FW-BUG-030 review).
    bool step(uint32_t nowMs, bool idle, bool motorReady) {
        if (!armed_) return false;
        if (motorReady) { armed_ = false; done_ = true; return false; }
        if (!idle) { sinceMs_ = nowMs; return false; }
        if (static_cast<uint32_t>(nowMs - sinceMs_) < CC_BOOT_RETRY_IDLE_MS) return false;
        armed_ = false; done_ = true;
        return true;
    }
    bool pending() const { return armed_; }
    bool done() const { return done_; }

private:
    bool armed_, done_;
    uint32_t sinceMs_;
};
