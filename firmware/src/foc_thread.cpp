#include "./foc_thread.h"
#include "utils.h"
#include "HapticCommander.h"
#include "./com_thread.h"
#include "control_center.h"
#include "cc_sleep.h"


/*
    FOC Thread runs BLDCHaptic Library in estimated current mode
    It sends and receives data from Com Thread.
*/


// global variables
BLDCMotor motor = BLDCMotor(7, 5.3);
BLDCDriver3PWM driver = BLDCDriver3PWM(PIN_IN_U, PIN_IN_V, PIN_IN_W, PIN_EN_U, PIN_EN_V, PIN_EN_W);

MagneticSensorMT6701SSI encoder(PIN_MAG_CS);

HapticInterface haptic = HapticInterface(&motor);
HapticCommander commander = HapticCommander(&motor);



FocThread::FocThread(const uint8_t task_core) : Thread("FOC", 8192, 1, task_core) {
    _q_motor_in = xQueueCreate(5, sizeof( String* ));
    _q_haptic_in = xQueueCreate(2, sizeof( DetentProfile ));
    _q_angleevt_out = xQueueCreate(5, sizeof( AngleEvt ));
    assert(_q_motor_in != NULL);
    assert(_q_haptic_in != NULL);
    assert(_q_angleevt_out != NULL);
}

FocThread::~FocThread() {}


void FocThread::init(DetentProfile& initialConfig) {
    haptic.haptic_state = HapticState(initialConfig);
};


void FocThread::run() {
    SPIClass* spi = new SPIClass(HSPI);
    spi->begin(PIN_MAG_CLK, PIN_MAG_DO, -1, PIN_MAG_CS);
    encoder.init(spi);

    driver.voltage_power_supply = 5.0f; // TODO global settings
    driver.voltage_limit = 5.0f;

    driver.init();
    motor.linkSensor(&encoder);
    motor.linkDriver(&driver);
    motor.LPF_velocity.Tf = 0.01f;
    motor.current_limit = 1.22;
    motor.init();
    Direction dir = motor.sensor_direction;
    if (dir == Direction::UNKNOWN) {
        com_thread.put_string_message(StringMessage(new String("Calibration required..."), StringMessageType::STRING_MESSAGE_DEBUG));
    }
    int initResult = motor.initFOC();
    if (motor.sensor_direction != dir && initResult != 0) {
        com_thread.put_string_message(StringMessage(new String("Storing calibration in Preferences..."), StringMessageType::STRING_MESSAGE_DEBUG));
        MotorCalibration cal = { motor.sensor_direction, motor.zero_electric_angle };
        DeviceSettings::getInstance().storeCalibration(cal);
    }
    if (initResult == 0) {
        com_thread.put_string_message(StringMessage(new String("Motor init failed!"), StringMessageType::STRING_MESSAGE_ERROR));
    }
    haptic.init();
    haptic.motor->sensor_offset = haptic.motor->shaft_angle;
    // float lastang = encoder.getAngle();
    // unsigned long ts = micros();
    uint16_t serial_last_pos = 0;
    bool runtime_active = false;
    HapticState previous;
    uint32_t runtime_id = 0;
    CCSleepFoc sleep_foc;   // inactivity sleep: the knob watcher and the motor on/off (cc_sleep.h)
    while (true) {
        CCControl control;
        if (cc_take_request(control)) {
            if (control.release) {
                if (runtime_active) {
                    haptic.rebase_runtime(previous.detent_profile, previous.current_pos);
                    // Retain any runtime gains that existed before host ownership.
                    haptic.haptic_state.detent_strength_unit = previous.detent_strength_unit;
                    haptic.haptic_state.endstop_strength_unit = previous.endstop_strength_unit;
                    haptic.haptic_state.attract_hysteresis = previous.attract_hysteresis;
                }
                runtime_active = false; runtime_id = 0;
            } else {
                if (!runtime_active) { previous = haptic.haptic_state; xQueueReset(_q_haptic_in); }
                runtime_active = true; runtime_id = control.id;
                haptic.rebase_runtime(control.profile, control.position);
            }
            serial_last_pos = haptic.haptic_state.current_pos;
            xQueueReset(_q_angleevt_out);
            cc_motor_applied(runtime_id, serial_last_pos);
        }
        if (runtime_active && cc_can_arm(runtime_id)) {
            // Motion while labels/LEDs were being installed is not a new control gesture.
            haptic.rebase_runtime(haptic.haptic_state.detent_profile,haptic.haptic_state.current_pos);
            serial_last_pos = haptic.haptic_state.current_pos;
            xQueueReset(_q_angleevt_out);
            cc_motor_ready(runtime_id,serial_last_pos);
        }
        // Inactivity sleep (cc_sleep.h), on this thread only: the driver is disabled while the
        // knob sleeps and the shaft angle is still read (loopFOC()/move() update it with the motor
        // off), so a turn can wake it. No haptic loop runs while the motor is off: the position
        // cannot move, so no p event, native value or LED detent comes from the wake turn. On
        // enable the detents are re-anchored at the shaft angle found (same position).
        const CCSleepFocStep sleepStep = sleep_foc.step(static_cast<uint32_t>(xTaskGetTickCount() * portTICK_PERIOD_MS),
                                                        motor.shaft_angle, cc_sleep_state() == CC_SLEEP_ASLEEP);
        if (sleepStep.input) cc_sleep_input();
        if (sleepStep.action == CC_SLEEP_MOTOR_DISABLE) motor.disable();
        else if (sleepStep.action == CC_SLEEP_MOTOR_ENABLE) {
            motor.enable();
            haptic.reanchor();
            serial_last_pos = haptic.haptic_state.current_pos;
        }
        if (sleep_foc.motorOff() || (cc_claimed() && cc_input_id() != runtime_id)) { motor.loopFOC(); motor.move(0); }
        else haptic.haptic_loop();
        float ang = encoder.getAngle();
        unsigned long now = micros();
        // if (fabs(ang - lastang) >= angleEventMinAngle && now - ts >= angleEventMinMicroseconds) {
        if (haptic.haptic_state.current_pos != serial_last_pos){
            AngleEvt ae = { haptic.haptic_state.current_pos, runtime_id };
            if (!cc_claimed() || cc_input_id() == runtime_id) {
                if (xQueueSend(_q_angleevt_out, &ae, (TickType_t)0) != pdTRUE) {
                    // Positions are absolute: retain newest state rather than lose it.
                    AngleEvt discarded;
                    xQueueReceive(_q_angleevt_out, &discarded, (TickType_t)0);
                    xQueueSend(_q_angleevt_out, &ae, (TickType_t)0);
                }
            }
            serial_last_pos = haptic.haptic_state.current_pos;
        }
        
        
        handleMessage();
        handleHapticConfig();
    }
        
};

void FocThread::put_motor_command(String* message) {
    if (message!=nullptr)
        xQueueSend(_q_motor_in, &message, (TickType_t)0);
};


void FocThread::put_haptic_config(DetentProfile& profile) {
    xQueueSend(_q_haptic_in, &profile, (TickType_t)0);
};




bool FocThread::get_angle_event(AngleEvt* evt) {
    return xQueueReceive(_q_angleevt_out, evt, (TickType_t)0);
};



uint16_t FocThread::pass_actual_pos(){

    uint16_t pointer = (foc_thread.get_motor_angle() / 6.283185307179586f) * 360;
    pointer %= 360; // Ensure pointer value is within the range [0, 360)
    return pointer;
}

uint16_t FocThread::pass_cur_pos(){
    return haptic.haptic_state.current_pos;
}

uint16_t FocThread::pass_start_pos(){
    return haptic.haptic_state.detent_profile.start_pos;
}

uint16_t FocThread::pass_end_pos(){
    return haptic.haptic_state.detent_profile.end_pos;
}

uint16_t FocThread::pass_last_pos(){
    return haptic.haptic_state.last_pos;
}

bool FocThread::pass_at_limit(){
    return haptic.haptic_state.atLimit;
}

// ALIVE.md 12.5 [Q1]: read-only (foc_thread.h).
bool FocThread::pass_limit_push(){
    const HapticState& state = haptic.haptic_state;
    return state.atLimit && state.attract_angle != state.last_attract_angle;
}





float FocThread::get_motor_angle() {
    return motor.shaft_angle;
};

void FocThread::handleMessage() {
    String* message = nullptr;
    if (xQueueReceive(_q_motor_in, &message, (TickType_t)0)) {
        if (message!=nullptr) {
            Serial.println("Received and handling message: "+*message);
            commander.handleMessage(message);
            StringMessage smsg(message, StringMessageType::STRING_MESSAGE_MOTOR);
            com_thread.put_string_message(smsg); // message String* is returned to comms thread, where it is deleted if necessary
        }
    }
};


void FocThread::handleHapticConfig() {
    if (cc_claimed()) return;
    DetentProfile profile;
    if (xQueueReceive(_q_haptic_in, &profile, (TickType_t)0)) {
        // apply haptic config to motor
        haptic.haptic_state = HapticState(profile);
    }
};



void FocThread::setCalibration(MotorCalibration& cal){
    haptic.motor->zero_electric_angle = cal.zero_angle;
    haptic.motor->sensor_direction = cal.direction==0 ? Direction::UNKNOWN : ( cal.direction==1 ? Direction::CW : Direction::CCW);
};



