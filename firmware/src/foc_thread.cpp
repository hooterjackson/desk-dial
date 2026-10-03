#include "./foc_thread.h"
#include "utils.h"
#include "HapticCommander.h"
#include "./com_thread.h"
#include "control_center.h"
#include "cc_sleep.h"
#include "cc_diag.h"
#include "cc_haptic_fx.h"
#include "cc_boot_cal.h"


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

// A2 app canvas (1.0.0-cc5.6): the knob's total sensor angle in 1e-4 rad, one aligned word written once per FOC
// pass and read by the LCD thread (the cube follows the knob locally, cc_app_canvas.h). Only differences are used.
// FW-BUG-032: a genuinely wrapping count (cc_haptic_fx.h CCAngleWord), never a float-to-int cast of the total angle.
static volatile int32_t app_angle = 0;
static CCAngleWord app_angle_word;
int32_t cc_app_angle_read() { return app_angle; }

// FW-BUG-022 (cc_diag.cpp, the boot PD read): true when the RDO_STATUS read worked; `position` the RDO's object
// position (0 = no explicit contract), `millivolts` the sink PDO's voltage there (0 = unknown), `nvmRewritten` when
// init_pd() (re)programmed the sink PDOs this boot (the contract still follows the old table until a power cycle).
bool cc_boot_pd_contract(uint32_t& position, uint32_t& millivolts, bool& nvmRewritten);

namespace {
// FW-TST-009 (cc_boot_cal.h): the motor's calibration in the header's terms.
static_assert(CC_BOOT_CAL_NOT_SET == NOT_SET, "cc_boot_cal.h: NOT_SET is SimpleFOC's");
static_assert(static_cast<int>(Direction::CW) == CC_BOOT_CAL_CW && static_cast<int>(Direction::CCW) == CC_BOOT_CAL_CCW &&
              static_cast<int>(Direction::UNKNOWN) == CC_BOOT_CAL_UNKNOWN, "cc_boot_cal.h: SimpleFOC's Direction values");
CCBootCal boot_cal_of(const BLDCMotor& m) {
    CCBootCal c;
    c.direction = static_cast<int>(m.sensor_direction);
    c.zero = m.zero_electric_angle;
    return c;
}

// r4 FEEL (1.0.0-cc5.7, plan F2; cc_haptic_fx.h, HAPTICS.md). FOC task state; the diag copy below is what other tasks
// read (single writer, plain word stores, refreshed every kFeelDiagUs).
CCSpinTrip spin_trip;
CCCalTripGuard cal_trip_guard;         // FW-BUG-046: the direction rule counts trips since the last calibration
float supply_volts = 5.0f;
bool supply_assumed = false;           // FW-BUG-022: no readable contract voltage, the supply was assumed (diag)
bool offline_active = false;           // the offline system volume mode (plan F3) is running
HapticState offline_saved;             // the native state it replaced
// Offline volume's fixed profile (HAPTICS.md "Offline volume"): REGULAR, 36 detents per turn (one 2 % Windows step
// each), positions 0..200 re-centred to 100 after every step, so it never meets an end stop.
constexpr uint16_t kOfflineCentre = 100;
DetentProfile offline_profile() {
    DetentProfile p;
    p.mode = HapticMode::REGULAR; p.start_pos = 0; p.end_pos = 2 * kOfflineCentre; p.detent_count = 36;
    p.vernier = 1; p.kxForce = false; p.output_ramp = 10000.0f; p.detent_strength = 3.0f;
    return p;
}
volatile CCFocFeelDiag feel_diag = {};
uint32_t feel_diag_at = 0;
constexpr uint32_t kFeelDiagUs = 100000;
// Recalibration save handshake (cc_haptic_fx.h CCCalHandshake, FW-TST-010): the FOC task offers the new calibration
// only while its output is zero, the COM task takes it under this lock, writes Preferences and marks it done.
portMUX_TYPE cal_mux = portMUX_INITIALIZER_UNLOCKED;
struct CCCalPortLock {
    void lock() { portENTER_CRITICAL(&cal_mux); }
    void unlock() { portEXIT_CRITICAL(&cal_mux); }
};
CCCalPortLock cal_lock;
CCCalHandshake<CCCalPortLock> cal_handshake(cal_lock);
}

void cc_foc_feel_diag(CCFocFeelDiag& out) {
    out.feel = feel_diag.feel; out.reduced = feel_diag.reduced; out.sound = feel_diag.sound;
    out.supplyDeciVolts = feel_diag.supplyDeciVolts; out.supplyAssumed = feel_diag.supplyAssumed;
    out.motorReady = feel_diag.motorReady; out.motorCal = feel_diag.motorCal;
    out.fxPlayed = feel_diag.fxPlayed; out.fxPulses = feel_diag.fxPulses; out.fxDropped = feel_diag.fxDropped;
    out.foldPct = feel_diag.foldPct; out.foldEvents = feel_diag.foldEvents;
    out.tripLatched = feel_diag.tripLatched; out.trips = feel_diag.trips;
    out.restAsleep = feel_diag.restAsleep; out.restSleeps = feel_diag.restSleeps; out.restWakes = feel_diag.restWakes;
    out.offline = feel_diag.offline;
}

// COM task: take the calibration the FOC task offers (true once), then report the write's result (cc_cal_saved(ok):
// FW-BUG-028, false when NVS refused it; the FOC wait then ends at once with save-timeout and the old calibration).
bool cc_cal_take_save(MotorCalibration& cal) {
    int32_t direction = 0;
    float zero = 0.0f;
    if (!cal_handshake.take(direction, zero)) return false;
    cal.direction = static_cast<int8_t>(direction);
    cal.zero_angle = zero;
    return true;
}
void cc_cal_saved(bool ok) { cal_handshake.saved(ok); }



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

    // 1.0.0-cc5.7 (plan F2): the motor driver runs from switched VBUS (Karl Malota's NanoFOC_D schematic: STSPIN233
    // VS = Vmot = VBUS through Q2), so a 9 V PD contract gave every commanded voltage (the 2.2 V cap included) 1.8x
    // its value. The supply the duty is scaled with now follows the contract read at boot (cc_diag cc_boot_pd):
    // FW-BUG-022, it fails safe high (cc_supply_volts()): 5 V only with no contract (a plain PC port: nothing
    // changes there, even on the first boot right after an NVM rewrite), the contract's own voltage when it is
    // known, else the highest sink PDO (20 V when the sink table was rewritten this boot and the read failed or found
    // a contract). Assuming too high only weakens the feel; too low over-drove the motor.
    {
        uint32_t pdPosition = 0, pdMillivolts = 0;
        bool pdRewritten = false;
        const bool pdRead = cc_boot_pd_contract(pdPosition, pdMillivolts, pdRewritten);
        const uint32_t pdVolts = (pdMillivolts + 500u) / 1000u;
        supply_assumed = CC_SUPPLY_FROM_PD && cc_supply_assumed(pdRead, pdPosition, pdVolts, pdRewritten);
        supply_volts = CC_SUPPLY_FROM_PD ? cc_supply_volts(pdRead, pdPosition, pdVolts, pdRewritten) : 5.0f;
    }
    driver.voltage_power_supply = supply_volts;
    driver.voltage_limit = 5.0f;

    driver.init();
    motor.linkSensor(&encoder);
    motor.linkDriver(&driver);
    motor.LPF_velocity.Tf = 0.01f;
    motor.current_limit = 1.22;
    // 1.0.0-cc5.5 (F1): the motor's output is capped at 2.2 V (it was the driver's 5 V). The haptic PID
    // (haptic.cpp default_pid, output limit 0.4) times the phase resistance (5.3 ohm, kept: it acts as the
    // gain of torque voltage mode) peaks at 2.12 V, so no detent or end stop feels different; the cap
    // bounds everything else (a register write, another control mode, the alignment). motor.init() also
    // clamps voltage_sensor_align to it, so a first-boot or requested recalibration aligns at <= 2.2 V.
    // HapticCommander never lets a {"R":...} register write raise it again (HapticCommander.h).
    motor.voltage_limit = kMotorVoltageCap;
    motor.init();
    Direction dir = motor.sensor_direction;
    if (dir == Direction::UNKNOWN) {
        com_thread.put_string_message(StringMessage(new String("Calibration required..."), StringMessageType::STRING_MESSAGE_DEBUG));
    }
    // FW-TST-009: stored when the alignment succeeded and either value changed (cc_boot_cal.h), never only on a
    // direction change: a re-aligned zero was lost and the zero re-aligned on every boot.
    const CCBootCal calBefore = boot_cal_of(motor);
    // FW-PUB-006: an alignment shows "hands off" on the LCD (cc_motor_cal_hands_off()) and waits 1 s first, so a
    // hand can leave the knob before the sweep; only an alignment whose pole-pair check passed is stored.
    const bool aligning = calBefore.direction == CC_BOOT_CAL_UNKNOWN;
    if (aligning) { cc_motor_cal_post(CC_MOTOR_CAL_ALIGNING); vTaskDelay(1000 / portTICK_PERIOD_MS); }
    motor.pp_check_result = false;
    int initResult = motor.initFOC();
    const bool poleOk = motor.pp_check_result;
    cc_motor_cal_post(cc_boot_cal_outcome(initResult, aligning, poleOk));
    if (aligning && initResult != 0 && !poleOk) {
        com_thread.put_string_message(StringMessage(new String("Calibration pole check failed: not stored, aligns again next boot"), StringMessageType::STRING_MESSAGE_ERROR));
    }
    if (cc_boot_cal_store(calBefore, boot_cal_of(motor), initResult, poleOk)) {
        com_thread.put_string_message(StringMessage(new String("Storing calibration in Preferences..."), StringMessageType::STRING_MESSAGE_DEBUG));
        MotorCalibration cal = { motor.sensor_direction, motor.zero_electric_angle };
        if (!DeviceSettings::getInstance().storeCalibration(cal)) {   // FW-BUG-028: a refused NVS write is said
            com_thread.put_string_message(StringMessage(new String("Storing calibration failed: Preferences refused the write"), StringMessageType::STRING_MESSAGE_ERROR));
        }
    }
    // FW-BUG-030: the outcome is kept (cc_motor_cal_state(), diag motorReady / motorCal); a failure is retried once
    // after a few idle seconds (boot_retry below), and a wake never enables an uncalibrated motor.
    CCBootRetry boot_retry;
    if (initResult == 0) {
        com_thread.put_string_message(StringMessage(new String("Motor init failed!"), StringMessageType::STRING_MESSAGE_ERROR));
        boot_retry.failed(static_cast<uint32_t>(xTaskGetTickCount() * portTICK_PERIOD_MS));
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
    // r4 (1.0.0-cc5.7): the newest effect word seen (nothing posted before boot plays), a fade owed to the arm
    // re-anchor, the key mask of the last pass (a new press clears the trip), the trip clock, the recalibration count.
    CCFxIntake fx_intake(cc_haptic_detail::shared().fxWord);
    bool fade_owed = false;
    uint8_t last_keys = 0;
    uint32_t trip_us = micros();
    uint32_t cal_seen = cc_haptic_detail::shared().calRequest;
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
                // r4: native haptics are the legacy loop, silent; an effect still playing stops.
                haptic.set_feel(CC_FEEL_LEGACY, false, 0, 0);
                haptic.cancel_effects();
                fade_owed = false;
            } else {
                // A claim while the offline volume mode runs (a host that opened the port without DTR): the native
                // state comes back first, so `previous` (restored at the release) is the profile's, never offline's.
                if (offline_active) exit_offline(serial_last_pos);
                const bool claim = !runtime_active;
                if (!runtime_active) { previous = haptic.haptic_state; xQueueReset(_q_haptic_in); }
                runtime_active = true; runtime_id = control.id;
                // r4 FEEL: the token's density replaces the preset's detent count (0 keeps it: detent.value / dimmer
                // keep BINARIS BEER's 67); feel.fade on a claim or a change of token / reduced haptics.
                DetentProfile profile = control.profile;
                const uint8_t feel = CC_HAPTIC_TOKENS ? control.feel : static_cast<uint8_t>(CC_FEEL_LEGACY);
                const CCFeelParams params = cc_feel_params(feel, control.reducedHaptics);
                if (feel != CC_FEEL_LEGACY && params.detents) profile.detent_count = params.detents;
                const bool fade = feel != CC_FEEL_LEGACY &&
                                  (claim || feel != haptic.feel() || control.reducedHaptics != haptic.reduced());
                haptic.rebase_runtime(profile, control.position);
                haptic.set_feel(feel, control.reducedHaptics, control.sound, fade ? CC_FEEL_FADE_MS : 0);
                fade_owed = fade;
                if (claim) spin_trip.clear();       // plan F2: a claim clears the self-spin latch
            }
            serial_last_pos = haptic.haptic_state.current_pos;
            xQueueReset(_q_angleevt_out);
            cc_motor_applied(runtime_id, serial_last_pos);
        }
        if (runtime_active && cc_can_arm(runtime_id)) {
            // Motion while labels/LEDs were being installed is not a new control gesture.
            haptic.rebase_runtime(haptic.haptic_state.detent_profile,haptic.haptic_state.current_pos);
            // r4 feel.fade: the grid moved again, so the fade runs from here (no notch drops under the finger).
            if (fade_owed) { haptic.restart_fade(CC_FEEL_FADE_MS); fade_owed = false; }
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
            // FW-BUG-030: only a calibrated motor is energised (a failed alignment left it uncommutated).
            if (cc_motor_wake_enable(motor.motor_status == FOCMotorStatus::motor_ready)) motor.enable();
            haptic.reanchor();
            haptic.restart_fade(CC_FEEL_WAKE_FADE_MS);   // r4: "detents fade in over 150 ms" after a wake
            serial_last_pos = haptic.haptic_state.current_pos;
        }
        // FW-BUG-030: a failed boot alignment is retried once, after CC_BOOT_RETRY_IDLE_MS idle (no key held, not
        // claimed, awake, no recalibration request pending), and never once the motor is ready (a recalibration
        // succeeded meanwhile: the retry is disarmed).
        if (boot_retry.step(static_cast<uint32_t>(xTaskGetTickCount() * portTICK_PERIOD_MS),
                            cc_live_key_state() == 0 && !runtime_active && !cc_claimed() && !sleep_foc.motorOff() &&
                            cc_haptic_detail::shared().calRequest == cal_seen,
                            motor.motor_status == FOCMotorStatus::motor_ready)) {
            retry_boot_alignment();
            serial_last_pos = haptic.haptic_state.current_pos;
        }
        // r4 (plan F2): a requested recalibration (never while claimed: control_center refuses the command then).
        if (cc_haptic_detail::shared().calRequest != cal_seen) {
            const uint32_t request = cc_haptic_detail::shared().calRequest;
            cal_seen = request;
            recalibrate(cal_trip_guard.acceptDirection((request & CC_CAL_ACCEPT_DIRECTION) != 0, spin_trip),
                        runtime_active || cc_claimed(), sleep_foc.motorOff());
            // FW-RES-011: a recalibration while the sleep has the motor off (host lines never wake the knob) enabled
            // the driver for the alignment, and nothing turned it off again: the bridge kept switching while asleep,
            // or the alignment's own shaft motion read as a turn and woke the knob. The driver goes off again; asleep,
            // the sleep watcher starts over at the new shaft angle and is stepped once right here, asleep: it primes
            // and disables now (the driver is already off, its input is false), so motorOff() stays true for the
            // rest of this pass (no offline, trip, host effect or haptic loop runs asleep) and its quiet window,
            // counted from now, absorbs the shaft settling. Only a hand's turn after it wakes the knob.
            if (sleep_foc.motorOff()) {
                motor.disable();
                if (cc_sleep_state() == CC_SLEEP_ASLEEP) {
                    sleep_foc = CCSleepFoc();
                    sleep_foc.step(static_cast<uint32_t>(xTaskGetTickCount() * portTICK_PERIOD_MS),
                                   motor.shaft_angle, true);
                }
            }
            serial_last_pos = haptic.haptic_state.current_pos;
        }
        // r4 offline system volume (plan F3): wanted by the HMI (no host on the port for 2 s), never while claimed or
        // asleep. Each step is counted for the HMI's Consumer reports and the position goes back to the centre.
        const bool want_offline = CC_OFFLINE_VOLUME && cc_offline_wanted() && !runtime_active && !cc_claimed() &&
                                  !sleep_foc.motorOff();
        if (want_offline && !offline_active) enter_offline(serial_last_pos);
        else if (!want_offline && offline_active) exit_offline(serial_last_pos);
        // Self-spin trip (plan F2; cc_haptic_fx.h CCSpinTrip): a new key press clears the latch; while latched the
        // output is zero (sleep and wake keep it: the motor comes back with a zero output).
        const uint8_t keys = cc_live_key_state();
        if (keys & static_cast<uint8_t>(~last_keys)) spin_trip.clear();
        last_keys = keys;
        const uint32_t trip_now = micros();
        const float trip_dt = static_cast<float>(static_cast<uint32_t>(trip_now - trip_us)) * 1e-6f;
        trip_us = trip_now;
        if (CC_HAPTIC_TRIP && !sleep_foc.motorOff() && spin_trip.step(motor.shaft_velocity, trip_dt)) haptic.cancel_effects();
        // r4 host effects (frame `haptic`, posted by the COM task): only for the claimed control, awake, untripped.
        // FW-BUG-007: while the output is held for a re-entry (applied, not yet ready) the post waits in fxWord and
        // plays, pulse and sound together, on the first pass that runs the haptic loop (cc_haptic_fx.h CCFxIntake).
        const bool reentry_hold = cc_claimed() && cc_input_id() != runtime_id;
        const uint8_t fx = fx_intake.step(static_cast<uint32_t>(xTaskGetTickCount() * portTICK_PERIOD_MS),
                                          !runtime_active || sleep_foc.motorOff() || spin_trip.latched(), reentry_hold);
        if (fx != CC_HFX_NONE) haptic.play_effect(fx);
        if (spin_trip.latched() && !sleep_foc.motorOff()) { motor.loopFOC(); motor.move(0); }
        else if (sleep_foc.motorOff() || (cc_claimed() && cc_input_id() != runtime_id)) { motor.loopFOC(); motor.move(0); } else haptic.haptic_loop();
        if (offline_active && haptic.haptic_state.current_pos != kOfflineCentre) {
            cc_offline_step(static_cast<int32_t>(haptic.haptic_state.current_pos) - static_cast<int32_t>(kOfflineCentre));
            haptic.haptic_state.current_pos = kOfflineCentre;   // re-centred: the grid is untouched, no end stop
            haptic.haptic_state.last_pos = kOfflineCentre;
            serial_last_pos = kOfflineCentre;
        }
        // A2: the app canvas cube (no extra sensor read; FW-BUG-032: the wrapping word, CCAngleWord).
        app_angle = app_angle_word.step(encoder.getFullRotations(), encoder.getMechanicalAngle());
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
        // 1.0.0-cc5.5 (F1): loop rate, loop gaps and the q-axis voltage against the cap ({"diag":"?"}
        // focLoopHz, focLoopUsMax, uqAbsMax, uqCapMs; cc_diag.h). A few word stores per pass.
        cc_diag_foc_pass(static_cast<uint32_t>(micros()), motor.voltage.q, motor.voltage_limit);
        if (static_cast<uint32_t>(now - feel_diag_at) >= kFeelDiagUs) { feel_diag_at = now; publishFeelDiag(); }
    }

};

// r4 FEEL diag words (cc_diag.cpp reports them): refreshed ten times a second by the FOC task.
void FocThread::publishFeelDiag() {
    const CCFxCounters& fx = haptic.effect_counters();
    feel_diag.feel = haptic.feel();
    feel_diag.reduced = haptic.reduced();
    feel_diag.sound = haptic.sound_level();
    feel_diag.supplyDeciVolts = static_cast<uint16_t>(supply_volts * 10.0f + 0.5f);
    feel_diag.supplyAssumed = supply_assumed;
    feel_diag.motorReady = motor.motor_status == FOCMotorStatus::motor_ready;
    feel_diag.motorCal = cc_motor_cal_state();
    feel_diag.restAsleep = haptic.rest().asleep();
    feel_diag.restSleeps = haptic.rest().sleeps();
    feel_diag.restWakes = haptic.rest().wakes();
    feel_diag.fxPlayed = fx.played;
    feel_diag.fxPulses = fx.pulses;
    feel_diag.fxDropped = fx.dropped;
    feel_diag.foldPct = static_cast<uint8_t>(haptic.foldback().factor() * 100.0f + 0.5f);
    feel_diag.foldEvents = haptic.foldback().events();
    feel_diag.tripLatched = spin_trip.latched();
    feel_diag.trips = spin_trip.trips();
    feel_diag.offline = offline_active;
}

// Offline system volume (plan F3): the fixed profile at the centre, the native state kept for the way back.
void FocThread::enter_offline(uint16_t& serialLastPos) {
    offline_saved = haptic.haptic_state;
    haptic.rebase_runtime(offline_profile(), kOfflineCentre);
    haptic.set_feel(CC_FEEL_LEGACY, false, 0, 0);
    offline_active = true;
    serialLastPos = haptic.haptic_state.current_pos;
}
void FocThread::exit_offline(uint16_t& serialLastPos) {
    haptic.rebase_runtime(offline_saved.detent_profile, offline_saved.current_pos);
    haptic.haptic_state.detent_strength_unit = offline_saved.detent_strength_unit;
    haptic.haptic_state.endstop_strength_unit = offline_saved.endstop_strength_unit;
    haptic.haptic_state.attract_hysteresis = offline_saved.attract_hysteresis;
    offline_active = false;
    serialLastPos = haptic.haptic_state.current_pos;
}

// Recalibration (plan F2; HAPTICS.md "Recalibration"), on this task, the motor's only owner. SimpleFOC's alignment
// (initFOC with the direction and zero unknown: it sweeps, then holds the field at 3 pi / 2 to read the zero angle,
// at <= the 2.2 V cap), then the pole-pair check (one electrical turn open-loop must move the shaft 2 pi / 7 +- 25 %),
// then the direction rule: a changed direction is accepted only after a self-spin trip since the last successful
// calibration, while the trip is latched, or when the request says so (acceptDirection, CCCalTripGuard; FW-BUG-046).
// A failure restores the old calibration and re-enables; a success is saved through the COM task (the handshake:
// this task holds a zero output while the flash write runs: 1.5 s at most for the take, 3 s for the write), then the
// detents are re-anchored.
void FocThread::recalibrate(bool acceptDirection, bool claimed, bool motorOff) {
    cc_haptic_detail::Shared& s = cc_haptic_detail::shared();
    uint8_t outcome = CC_CAL_OK;
    if (claimed) outcome = CC_CAL_FAIL_CLAIMED;
    const Direction oldDirection = motor.sensor_direction;
    const float oldZero = motor.zero_electric_angle;
    if (outcome == CC_CAL_OK) {
        s.calState = CC_CAL_RUNNING;
        haptic.cancel_effects();
        motor.move(0); motor.loopFOC();
        motor.disable();
        vTaskDelay(1000 / portTICK_PERIOD_MS);
        motor.sensor_direction = Direction::UNKNOWN;
        motor.zero_electric_angle = NOT_SET;
        motor.enable();
        if (!motor.initFOC()) outcome = CC_CAL_FAIL_INIT;
        if (outcome == CC_CAL_OK) {
            // The pole-pair check: hold at 3 pi / 2, then one electrical turn in 500 steps, then release.
            const float volts = motor.voltage_sensor_align;
            motor.setPhaseVoltage(volts, 0, _3PI_2);
            vTaskDelay(700 / portTICK_PERIOD_MS);
            encoder.update();
            const float start = encoder.getAngle();
            for (int i = 0; i <= 500; ++i) {
                motor.setPhaseVoltage(volts, 0, _3PI_2 + _2PI * static_cast<float>(i) / 500.0f);
                encoder.update();
                delay(2);
            }
            encoder.update();
            const float moved = encoder.getAngle() - start;
            motor.setPhaseVoltage(0, 0, 0);
            if (!cc_cal_pole_check(moved, motor.pole_pairs)) outcome = CC_CAL_FAIL_POLES;
        }
        if (outcome == CC_CAL_OK && oldDirection != Direction::UNKNOWN && motor.sensor_direction != oldDirection &&
            !acceptDirection) outcome = CC_CAL_FAIL_DIRECTION;
        if (outcome == CC_CAL_OK) {
            s.calState = CC_CAL_SAVING;
            if (!save_through_com()) outcome = CC_CAL_FAIL_SAVE;
        }
        if (outcome != CC_CAL_OK) {
            // Restore and re-enable with the old values (initFOC skips the alignment when both are known).
            motor.sensor_direction = oldDirection;
            motor.zero_electric_angle = oldZero;
            // FW-BUG-009: a failed alignment (a finger on the knob) leaves initFOC() having called disable(), and a
            // successful restore never enables again: loopFOC()/move() returned early and the knob was limp until a
            // sleep wake or a reboot. Enabled again once restored (unless the sleep has the motor off: its wake
            // enables it); a restore that fails too is reported as init-failed and the motor stays off.
            if (motor.initFOC()) { if (!motorOff) motor.enable(); }
            else outcome = CC_CAL_FAIL_INIT;
        }
        haptic.reanchor();
    }
    // FW-BUG-030: a recalibration that leaves the motor calibrated clears a failed boot; one that leaves it
    // uncalibrated says so (the LCD's "calibration failed" cue, diag motorCal). FW-BUG-031 / FW-BUG-046: a success
    // clears the self-spin latch (detents and walls come back) and marks the calibration for the direction rule.
    if (outcome == CC_CAL_OK) { cc_motor_cal_post(CC_MOTOR_CAL_READY); cal_trip_guard.calibrated(spin_trip); }
    else if (motor.motor_status != FOCMotorStatus::motor_ready) cc_motor_cal_post(CC_MOTOR_CAL_FAILED);
    s.calOutcome = outcome;
    s.calResult = s.calResult + 1u;
    s.calState = CC_CAL_IDLE;
}

// The save handshake (cc_haptic_fx.h CCCalHandshake): the calibration is offered to the COM task, which writes
// Preferences; this task holds a zero output meanwhile. False when the COM task did not take it within
// CC_CAL_SAVE_TIMEOUT_MS, or took it and did not report it written within CC_CAL_WRITE_TIMEOUT_MS (FW-TST-010), or
// reported the NVS write refused (CC_CAL_POLL_FAILED, FW-BUG-028: the caller restores the old direction and zero)
// (recalibrate(), and the FW-BUG-030 boot retry: Preferences is written by the COM task only once the threads run).
bool FocThread::save_through_com() {
    cal_handshake.offer(static_cast<int32_t>(motor.sensor_direction), motor.zero_electric_angle, millis());
    while (true) {
        motor.loopFOC(); motor.move(0);        // zero output while the COM task writes the flash
        const uint8_t poll = cal_handshake.poll(millis());
        if (poll != CC_CAL_POLL_WAIT) return poll == CC_CAL_POLL_SAVED;
        vTaskDelay(1);
    }
}

// FW-BUG-030: the one retry of a failed boot alignment (the boot path's rules: hands off and a 1 s settle first, the
// pole check gates the store). The direction and zero are still unknown, so initFOC() runs the whole alignment.
bool FocThread::retry_boot_alignment() {
    haptic.cancel_effects();
    motor.sensor_direction = Direction::UNKNOWN;
    motor.zero_electric_angle = NOT_SET;
    const CCBootCal calBefore = boot_cal_of(motor);
    cc_motor_cal_post(CC_MOTOR_CAL_ALIGNING);
    vTaskDelay(1000 / portTICK_PERIOD_MS);
    motor.enable();
    motor.pp_check_result = false;
    const int initResult = motor.initFOC();   // disables the driver again on a failure
    const bool poleOk = motor.pp_check_result;
    cc_motor_cal_post(cc_boot_cal_outcome(initResult, true, poleOk));
    if (cc_boot_cal_store(calBefore, boot_cal_of(motor), initResult, poleOk) && !save_through_com())
        cc_motor_cal_post(CC_MOTOR_CAL_UNSTORED);   // running, not stored: the next boot aligns again
    if (initResult == 0)
        com_thread.put_string_message(StringMessage(new String("Motor init failed again: replug the knob, hands off"), StringMessageType::STRING_MESSAGE_ERROR));
    haptic.reanchor();
    if (initResult != 0) cal_trip_guard.calibrated(spin_trip);   // FW-BUG-046: a calibration in use from here
    return initResult != 0;
}

void FocThread::put_motor_command(String* message) {
    // FW-RES-002: the queue holds only the pointer; a full 5-deep queue would drop it and leak the String.
    if (message!=nullptr && xQueueSend(_q_motor_in, &message, (TickType_t)0) != pdTRUE)
        delete message;
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
            // 1.0.0-cc5.5 (F1): no String building and no Serial.println() on the FOC thread (it wrote to
            // the port unsynchronised with the COM task's replies). The command's answer still reaches the
            // host as {"r":"r<reg>=<value>"} from the COM task (STRING_MESSAGE_MOTOR below).
            // FW-BUG-035: a refused command (register or value out of range) is answered {"error":...}.
            const bool ok = commander.handleMessage(message);
            StringMessage smsg(message, ok ? StringMessageType::STRING_MESSAGE_MOTOR : StringMessageType::STRING_MESSAGE_ERROR);
            com_thread.put_string_message(smsg); // message String* is returned to comms thread, where it is deleted if necessary
        }
    }
};


void FocThread::handleHapticConfig() {
    if (cc_claimed()) return;
    DetentProfile profile;
    if (xQueueReceive(_q_haptic_in, &profile, (TickType_t)0)) {
        // apply haptic config to motor (1.0.0-cc5.7: while the offline volume mode runs, to the state it restores;
        // exit_offline() rebases it then). FW-BUG-008: the detent grid is anchored at the current shaft angle (as
        // the release and offline paths do), never at angle 0: the multi-turn shaft angle drifts, and a grid at 0
        // refused every turn on one side and spun the knob back towards 0 hands off.
        if (offline_active) offline_saved = HapticState(profile);
        else haptic.rebase_runtime(profile, profile.start_pos);
    }
};



// FW-TST-009: only a whole, plausible stored pair is used (cc_cal_from_nvs()); anything else starts uncalibrated, so
// initFOC() aligns direction and zero together and the boot stores the pair.
void FocThread::setCalibration(MotorCalibration& cal){
    const CCBootCal c = cc_cal_from_nvs(cal.direction, cal.zero_angle);
    haptic.motor->zero_electric_angle = c.zero;
    haptic.motor->sensor_direction = c.direction == CC_BOOT_CAL_CW ? Direction::CW
                                   : (c.direction == CC_BOOT_CAL_CCW ? Direction::CCW : Direction::UNKNOWN);
};
