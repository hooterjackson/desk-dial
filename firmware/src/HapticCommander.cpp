
#include "./HapticCommander.h"
#include "cc_haptic_fx.h"

HapticCommander::HapticCommander(BLDCMotor* motor) : motor(motor) {};

bool HapticCommander::handleMessage(String* message) {
    // FW-BUG-035: the register number (0..255) and the recalibration value (0 / 1) are range-checked before any
    // dispatch (cc_haptic_fx.h cc_reg_command_check): atoi() into a uint8_t aliased 385 or -127 to 129 =
    // REG_RECALIBRATE. A refused command is answered as an error (FocThread::handleMessage), nothing runs.
    uint8_t reg = 0;
    const uint8_t check = cc_reg_command_check(message->c_str(), reg);
    if (check != CC_REG_CMD_OK) {
        message->clear();
        message->concat(check == CC_REG_CMD_BAD_REGISTER ? "R: register must be 0..255" : "R: recalibrate value must be 0 or 1");
        msg_in = NULL;
        return false;
    }
    msg_in = (char*)message->c_str();
    msg_in = strchr(msg_in, '=');
    if (msg_in != NULL) {
        if (reg==REG_RECALIBRATE) {
            uint8_t value = 0; *this >> value;
            // 1.0.0-cc5.7 (plan F2): the register runs the same recalibration as {"recalibrate":true} (the FOC task's
            // FocThread::recalibrate(): pole check, direction rule, restore on failure, the save handshake), never
            // the old bare initFOC() that could keep a flipped direction and never saved.
            if (value==1) cc_cal_request(false);
        }
        else if (haptic_register_write_allowed(reg)) {
            SimpleFOCRegisters::regs->commsToRegister(*this, reg, motor);
            // 1.0.0-cc5.5 (F1): no register write raises the output above the cap (HapticCommander.h). Both
            // limits stay in [0, cap]: NaN or above -> the cap; negative -> 0 (SimpleFOC's _constrain() with a
            // negative limit would return |limit|, i.e. could exceed the cap).
            motor->voltage_limit = haptic_voltage_in_cap(motor->voltage_limit);
            motor->voltage_sensor_align = haptic_voltage_in_cap(motor->voltage_sensor_align);
            // FW-BUG-003 (defence in depth): whatever a write touched, the haptic loop's modes stand: torque
            // control in voltage mode with the phase resistance set (Uq = target x R, clamped to voltage_limit).
            motor->controller = MotionControlType::torque;
            motor->torque_controller = TorqueControlType::voltage;
            motor->foc_modulation = FOCModulationType::SpaceVectorPWM;
            motor->phase_resistance = CC_HAPTIC_PHASE_OHMS;
        }
        // FW-BUG-003: any other write is refused; the reply below carries the unchanged value.
    }
    msg_out = message;
    sendRegister(reg);
    msg_in = NULL;
    return true;
};



void HapticCommander::sendRegister(uint8_t reg) {
    msg_out->clear();
    msg_out->concat('r');
    msg_out->concat((int)reg);
    msg_out->concat('=');
    if (reg==REG_RECALIBRATE) {
        msg_out->concat("0");
    }
    else
        SimpleFOCRegisters::regs->registerToComms(*this, reg, motor);
};



RegisterIO& HapticCommander::operator<<(float value) {
    msg_out->concat(String(value, 4));
    return *this;
};

RegisterIO& HapticCommander::operator<<(uint32_t value) {
    msg_out->concat(value);
    return *this;
};

RegisterIO& HapticCommander::operator<<(uint8_t value) {
    msg_out->concat(value);
    return *this;
};

RegisterIO& HapticCommander::operator>>(float& value) {
    if (msg_in != NULL) {
        msg_in++; // skip the separator
        value = atoff(msg_in);
        msg_in = strchr(msg_in, ','); // next position, if any
    }
    return *this;
};


// FW-BUG-035: an integer register value outside its type's range (or no number) leaves `value` unchanged, never
// truncated into range.
RegisterIO& HapticCommander::operator>>(uint32_t& value) {
    if (msg_in != NULL) {
        msg_in++; // skip the separator
        long long v = 0;
        const char* end = msg_in;
        if (cc_parse_ranged(msg_in, 0, 0xFFFFFFFFLL, v, end)) value = static_cast<uint32_t>(v);
        msg_in = strchr(msg_in, ','); // next position, if any
    }
    return *this;
};


RegisterIO& HapticCommander::operator>>(uint8_t& value) {
    if (msg_in != NULL) {
        msg_in++; // skip the separator
        long long v = 0;
        const char* end = msg_in;
        if (cc_parse_ranged(msg_in, 0, 255, v, end)) value = static_cast<uint8_t>(v);
        msg_in = strchr(msg_in, ','); // next position, if any
    }
    return *this;
};


