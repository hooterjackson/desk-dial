#pragma once

#include <Arduino.h>
#include "thread_crtp.h"
#include "haptic.h"
#include "nanofoc_d.h"
#include "DeviceSettings.h"
#include "audio/audio_api.h"


class FocThread : public Thread<FocThread> {
    friend class Thread<FocThread>; //Allow Base Thread to invoke protected run()
    friend class HapticInterface;

    public:
        FocThread(const uint8_t task_core);
        ~FocThread();

        void init(DetentProfile& initialConfig);

        void put_motor_command(String* msg);
        void put_haptic_config(DetentProfile& profile);
        bool get_angle_event(AngleEvt* evt);
    

        float get_motor_angle();
        
        uint16_t pass_actual_pos();
        uint16_t pass_cur_pos();
        uint16_t pass_start_pos();
        uint16_t pass_end_pos();
        uint16_t pass_last_pos();
        bool pass_at_limit();
        // ALIVE.md 12.5 [Q1] (1.0.0-cc5.4), read-only: the knob is being pushed past a bound, i.e.
        // the FOC is at the limit AND its attractor has moved past the bound detent
        // (atLimit && attract_angle != last_attract_angle). The haptic code does not advance
        // last_attract_angle during a push, so the two are equal again once the knob springs back
        // to the bound detent. Both are floats the FOC task writes; a torn pair costs one HMI pass,
        // which the re-arm hold-off (lim_rearm_ms) absorbs. Changes nothing in the haptic state.
        bool pass_limit_push();

        void setCalibration(MotorCalibration& cal);

    protected:
        void run();
        void handleMessage();
        void handleHapticConfig();
        // r4 (1.0.0-cc5.7, plan F2 / F3): the feel diag words, the offline volume mode, recalibration.
        void publishFeelDiag();
        void enter_offline(uint16_t& serialLastPos);
        void exit_offline(uint16_t& serialLastPos);
        void recalibrate(bool acceptDirection, bool claimed, bool motorOff);
        bool retry_boot_alignment();   // FW-BUG-030: the one retry of a failed boot alignment
        bool save_through_com();       // the calibration save handshake (recalibrate(), the boot retry)

        float angleEventMinAngle = 0.017453292519943f; // 1° in radians
        uint32_t angleEventMinMicroseconds = 10000; // 100Hz

    private:
        QueueHandle_t _q_motor_in;
        QueueHandle_t _q_haptic_in;
        QueueHandle_t _q_angleevt_out;
};

extern FocThread foc_thread;

// r4 FEEL + SOUND (1.0.0-cc5.7; HAPTICS.md "Diag"): what the FOC task publishes ten times a second for {"diag":"?"}
// (cc_diag.cpp): the claim's token, reduced haptics and sound level, the supply the driver scales with (decivolts),
// the effect counters, the wall fold-back (percent of force, events), the self-spin trip and the offline volume mode.
struct CCFocFeelDiag {
    uint8_t feel;
    bool reduced;
    uint8_t sound;
    uint16_t supplyDeciVolts;
    bool supplyAssumed;          // FW-BUG-022: no readable PD contract voltage, the supply was assumed (fails safe high)
    bool motorReady;             // FW-BUG-030: SimpleFOC motor_status == motor_ready (calibrated; never enabled otherwise)
    uint8_t motorCal;            // FW-BUG-030: cc_boot_cal.h CCMotorCal (aligning / ready / unstored / failed)
    uint32_t fxPlayed, fxPulses, fxDropped;
    uint8_t foldPct;
    uint32_t foldEvents;
    bool tripLatched;
    uint32_t trips;
    bool offline;
    bool restAsleep;             // rest sleep (2026-09-30): the output is zero while the knob sits still
    uint32_t restSleeps, restWakes;
};
void cc_foc_feel_diag(CCFocFeelDiag& out);
// Recalibration save handshake (plan F2), COM task: take the calibration the FOC task offers (true once, while the
// FOC output is held at zero), write it, then cc_cal_saved(ok) with the write's result (FW-BUG-028: false ends the
// FOC wait at once as save-timeout, the old calibration restored).
bool cc_cal_take_save(MotorCalibration& cal);
void cc_cal_saved(bool ok);

// A2 app canvas (1.0.0-cc5.6): the knob's total sensor angle, 1e-4 rad, published by the FOC task every pass
// (a single aligned word; the LCD thread reads it for the app canvas cube). Differences only, taken in unsigned
// arithmetic: the word wraps modulo 2^32 (FW-BUG-032, cc_haptic_fx.h CCAngleWord), about every 68,000 turns.
int32_t cc_app_angle_read();
