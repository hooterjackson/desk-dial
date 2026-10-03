
#pragma once

#include "comms/SimpleFOCRegisters.h"
#include "BLDCMotor.h"
#include "cc_haptic_fx.h"


#define REG_RECALIBRATE 0x81

// 1.0.0-cc5.5 (F1): the motor output cap (foc_thread.cpp sets motor.voltage_limit to it before
// motor.init()). No {"R":"<reg>=<value>"} register command can raise the motor's output above it:
//   * FW-BUG-003: writes are allow-listed (cc_haptic_fx.h haptic_register_write_allowed): only
//     REG_VOLTAGE_LIMIT 0x50 and REG_RECALIBRATE 0x81. Every other write is answered with the unchanged
//     value: a control mode, torque mode, PID limit, phase resistance or supply write could otherwise
//     route a voltage past motor->voltage_limit (velocity mode with phase_resistance unset, a frozen PWM
//     vector in dc_current mode, raw phase voltages) or past the haptic loop's move(0) zero paths;
//   * after the voltage limit write, motor->voltage_limit and motor->voltage_sensor_align are clamped
//     back to the cap (0x50 may lower them, never raise them), and the motion / torque mode, the
//     modulation and the phase resistance are put back to the haptic loop's (defence in depth).
// SimpleFOC clamps every commanded Uq/Ud to motor->voltage_limit in move() and in the alignment.
constexpr float kMotorVoltageCap = 2.2f;

// A voltage limit brought into [0, kMotorVoltageCap] (NaN and anything above -> the cap, negative -> 0).
constexpr float haptic_voltage_in_cap(float volts) {
    return volts < 0.0f ? 0.0f : (volts <= kMotorVoltageCap ? volts : kMotorVoltageCap);
}
static_assert(haptic_voltage_in_cap(5.0f) == kMotorVoltageCap && haptic_voltage_in_cap(1.5f) == 1.5f &&
              haptic_voltage_in_cap(-3.0f) == 0.0f && haptic_voltage_in_cap(kMotorVoltageCap) == kMotorVoltageCap,
              "HapticCommander: the voltage cap clamp");

// The allow-list's register numbers are SimpleFOC's (cc_haptic_fx.h cannot include SimpleFOCRegisters.h).
static_assert(CC_REG_VOLTAGE_LIMIT == SimpleFOCRegister::REG_VOLTAGE_LIMIT && CC_REG_RECALIBRATE == REG_RECALIBRATE,
              "HapticCommander: the register write allow-list numbers");



/**
 * HapticCommander is an implementation of SimpleFOC RegisiterIO that operates on
 * messages received as Strings from the comms thread via ESP32 xQueue.
 * 
 * It provides the bridge between SimpleFOC motor registers and the rest of the
 * comms code.
 */
class HapticCommander : public RegisterIO {
public:
    HapticCommander(BLDCMotor* motor);
    virtual ~HapticCommander() = default;

    // false: the command was refused (FW-BUG-035); `message` then holds the error text, nothing was dispatched.
    bool handleMessage(String* message);
    void sendRegister(uint8_t reg);

    RegisterIO& operator<<(float value);
    RegisterIO& operator<<(uint32_t value);
    RegisterIO& operator<<(uint8_t value);
    RegisterIO& operator>>(float& value);
    RegisterIO& operator>>(uint32_t& value);
    RegisterIO& operator>>(uint8_t& value);

protected:
    BLDCMotor* motor;
    char* msg_in;
    String* msg_out;
};
