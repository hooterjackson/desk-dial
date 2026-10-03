#pragma once

#include <Arduino.h>
#include <SimpleFOC.h>
#include <SimpleFOCDrivers.h>
#include "encoders/mt6701/MagneticSensorMT6701SSI.h"
#include <motor.h>
#include "haptic_api.h"
#include "cc_haptic_fx.h"

/**
 * Define start and end positions. These are the physical detent limits.
 * Coarse index and fine index track where in that range the dial is currently pointing.
 * Coarse num and fine num are the number of detents for each region. 
 * 
*/

class HapticState 
{
public:
    HapticState(void);
    HapticState(DetentProfile profile);
    HapticState(DetentProfile profile, uint16_t positon);
    ~HapticState();

    DetentProfile detent_profile;
    DetentProfile DefaultProgressiveForceProfile;
    DetentProfile DefaultVernierProfile;
    DetentProfile TempProfile;

    uint16_t current_pos = 0;
    uint16_t last_pos = 0; 

    float attract_angle = 0.0; 
    float detent_origin = 0.0; // Runtime coordinate origin; force curve is unchanged.
    float last_attract_angle = 0.0;
    float attract_hysteresis = 0.25;

    float detent_strength_unit = 3; // PID (estimated) Current Limit
    float endstop_strength_unit = 1; // PID (estimated) Current Limit

    bool atLimit = false;
    bool wasAtLimit = false;
    uint16_t last_limit_position = 0;

    //General parameters loaded from profile
    uint16_t num_detents;
    float detent_width;

    // FW-BUG-034: `position` is used when hasPosition is set (every constructor); otherwise the current position is
    // kept, clamped to the profile's (scaled) bounds. Never an in-band sentinel: 65535 is a valid position.
    void load_profile(DetentProfile profile, uint16_t position, bool hasPosition = true);
};

class HapticInterface
{
public:
    HapticState haptic_state;   // Haptic state

    BLDCMotor* motor;
    PIDController* haptic_pid;

    // All the various constructors.
    HapticInterface(BLDCMotor* _motor);
    HapticInterface(BLDCMotor* _motor, PIDController* _pid);

    void init(void);
    void haptic_loop(void);
    void rebase_runtime(DetentProfile profile, uint16_t position);
    // Inactivity wake (cc_sleep.h): the current profile, position and gains kept, the detent grid
    // and attractor moved to the shaft angle (as rebase_runtime does), limit flags cleared.
    void reanchor(void);
    void HapticEventCallback(HapticEvt);
    void UserHapticEventCallback(HapticEvt, float, uint16_t);

    // r4 feel (1.0.0-cc5.7, plan F2; cc_haptic_fx.h, HAPTICS.md). The FOC thread calls these; nothing else does.
    // set_feel(): the control's token (CC_FEEL_LEGACY = today's loop exactly), reduced haptics, the claim's sound
    // level (0 off .. 3) and a feel.fade length (0 = no fade). The detent density of the token is applied by the
    // caller before rebase_runtime() (the profile's detent_count).
    void set_feel(uint8_t feel, bool reduced, uint8_t sound, uint32_t fadeMs);
    void restart_fade(uint32_t fadeMs);      // feel.fade again (the arm re-anchor, a sleep wake); token mode only
    uint8_t feel() const { return feel_; }
    bool reduced() const { return reduced_; }
    uint8_t sound_level() const { return sound_; }
    const CCRestGate& rest() const { return rest_; }
    // A host event (CCFx) now: its pulses (and its sound) start unless the player refuses (cc_haptic_fx.h).
    bool play_effect(uint8_t fx);
    void cancel_effects() { fx_.cancel(); }
    const CCFxCounters& effect_counters() const { return fx_.counters(); }
    const CCFoldback& foldback() const { return fold_; }
    float wall_volts() const { return wallVolts_; }
    bool coasting() const;

private:
    void offset_detent(void);
    void find_detent(void);
    void detent_handler(void);
    void bounds_handler(float);
    void update_position(void);
    void haptic_target(void);
    void correct_pid(void);
    // r4 (token mode): the output of one pass, the wall's outward penetration, a refused detent at a bound and a
    // detent pulse.
    void token_target(void);
    float wall_penetration(int8_t& outward) const;
    void wall_refused(int8_t dir);
    void detent_pulse(int8_t positionDir);
    void end_freeze(void);
    int8_t angle_sign_of_increase() const;

    uint8_t feel_ = CC_FEEL_LEGACY;
    bool reduced_ = false;
    uint8_t sound_ = 0;
    CCFeelParams fp_ = cc_feel_params(CC_FEEL_LEGACY, false);
    CCFeelFade fade_;                  // feel.fade (FW-BUG-037: cleared once complete, so a micros() wrap never re-runs it)
    CCFxPlayer fx_;
    CCRestGate rest_;                  // rest sleep (2026-09-30): zero output while the knob sits still
    CCFoldback fold_;
    float springOut_ = 0.0f, wallVolts_ = 0.0f;
    uint32_t lastUs_ = 0;
    bool lastUsSet_ = false;
    // The attractor of the last refused detent at a bound (cc_wall_hit once per refused detent, not per pass).
    bool refusedSet_ = false;
    float refusedAttract_ = 0.0f;
    // The effect freeze (haptic_loop): whether the last pass was frozen, and the shaft angle, time and velocity when it
    // began (FW-BUG-033: end_freeze() tells the hand's turn from the pulses' displacement).
    bool frozen_ = false;
    float freezeAngle_ = 0.0f;
    uint32_t freezeUs_ = 0;
    float freezeVelocity_ = 0.0f;
};
