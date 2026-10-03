#include "haptic.h"
#include "haptic_api.h"
#include "haptic_bounds.h"
#include "utils.h"
#include "cc_wall.h"
#include "audio/audio.h"   // cc_sound_post(): every sound follows its haptic (1.0.0-cc5.7, plan F3)

/*
    Quick Swap between Legacy PCB and Production PCB
*/
#define PRODUCTION_PCB 1

/**
 * Handful of default profiles that you can quickly explore.
*/


PIDController default_pid(5.0, 0.0, 0.004, 10000, 0.4);

DetentProfile default_profile{
    .mode = HapticMode::REGULAR,
    .start_pos = 0,
    .end_pos =255,
    .detent_count = 60,
    .vernier = 5,
    .kxForce = false
};

DetentProfile DefaultProgressiveForceProfile{
    .mode = HapticMode::REGULAR,
    .start_pos = 0,
    .end_pos = 120,
    .detent_count = 20,
    .vernier = 10,
    .kxForce = false
};

DetentProfile DefaultVernierProfile{
    .mode = HapticMode::VERNIER,
    .start_pos = 0,
    .end_pos = 120,
    .detent_count = 20,
    .vernier = 10,
    .kxForce = true
};

// Custom profile to implement and change externally.
extern DetentProfile tempProfile;

/**
 * Constructors and deconstructors.
*/
HapticState::HapticState(void){
    load_profile(default_profile, default_profile.start_pos);
};

HapticState::HapticState(DetentProfile profile){
    load_profile(profile, profile.start_pos);
};

HapticState::HapticState(DetentProfile profile, uint16_t position){
    load_profile(profile, position);
};

// FW-BUG-034: whether a position comes with the profile is explicit (hasPosition, true for every constructor). It was
// the in-band 0xFFFF, so a valid position 65535 (a control 0..65535, a native profile restored at 65535) took the
// "no position" branch and the knob answered p 0.
void HapticState::load_profile(DetentProfile profile, uint16_t new_position, bool hasPosition){
    // 1.0.0-cc5.5 (F1): detentCount >= 1, vernier >= 1, endPos >= startPos (haptic_bounds.h); a valid
    // profile is unchanged.
    haptic_profile_sanitize(profile);
    uint16_t isVernier = profile.mode == HapticMode::VERNIER ? profile.vernier : 1;
   
    num_detents = profile.end_pos - profile.start_pos;
    detent_width = _2PI / profile.detent_count;

    if(profile.mode == HapticMode::VERNIER)
        detent_width /= profile.vernier;

    // Without a position, the current one is kept inside the profile's bounds, scaled as detent_handler() counts them
    // (FW-BUG-034: it clamped to the unscaled start / end in VERNIER mode).
    current_pos = haptic_load_position(hasPosition, new_position, current_pos,
                                       cc_scaled_position(profile.start_pos, isVernier),
                                       cc_scaled_position(profile.end_pos, isVernier));

    last_pos = current_pos;
    detent_profile = profile;
}

HapticState::~HapticState() {};

HapticInterface::HapticInterface(BLDCMotor* _motor){
    motor = _motor;
    haptic_pid = &default_pid;
    haptic_state = HapticState(default_profile);
};

HapticInterface::HapticInterface(BLDCMotor* _motor, PIDController* _pid){
    motor = _motor;
    haptic_pid = _pid;
    haptic_state = HapticState(default_profile);
};

void HapticInterface::init(void){
    motor->velocity_limit = 10000;
    motor->controller = MotionControlType::torque;
    motor->foc_modulation = FOCModulationType::SpaceVectorPWM;
};

void HapticInterface::haptic_loop(void){
    correct_pid(); // Adjust PID (Derivative Gain)
    // 1.0.0-cc5.7 (plan F2): an effect that started at rest freezes the detent position until it has played and
    // settled (cc_haptic_fx.h CCFxPlayer::frozen): a pulse never creates or loses a detent. During a turn it never
    // freezes, so no count is lost.
    const uint32_t freezeNow = micros();
    const bool frozen = fx_.frozen(freezeNow);
    if (frozen && !frozen_) {
        freezeAngle_ = motor->shaft_angle;
        freezeUs_ = freezeNow;                    // FW-BUG-033: the time and the hand's speed at the start
        freezeVelocity_ = motor->shaft_velocity;
    }
    if (!frozen && frozen_) end_freeze();
    frozen_ = frozen;
    if (!frozen) find_detent(); // Calculate attraction angle depending on configured distance position.
    if (feel_ != CC_FEEL_LEGACY) token_target(); // r4 token law (feel), walls, damping, effects
    else haptic_target(); // PID Command (1.0.0-cc5.6 exactly, plus a host effect when one plays)
}

void HapticInterface::rebase_runtime(DetentProfile profile, uint16_t position) {
    // Do not modify sensor calibration or force parameters. Translate the existing wells.
    haptic_state = HapticState(profile, position);
    haptic_state.detent_origin = motor->shaft_angle;
    haptic_state.attract_angle = motor->shaft_angle;
    haptic_state.last_attract_angle = motor->shaft_angle;
    haptic_pid->reset();
    motor->move(0);
}

void HapticInterface::reanchor(void) {
    haptic_state.detent_origin = motor->shaft_angle;
    haptic_state.attract_angle = motor->shaft_angle;
    haptic_state.last_attract_angle = motor->shaft_angle;
    haptic_state.atLimit = false;
    haptic_state.wasAtLimit = false;
    haptic_state.last_pos = haptic_state.current_pos;
    haptic_pid->reset();
    motor->move(0);
}

/**
 * Handles scaling the P term error and clamping error to prevent overshoot.
 * The scaled P error helps to prevent steady state error due to lack of I term (for "rolling" reasons).
 * When roll mode is triggered, I term is added back in.
*/
void HapticInterface::correct_pid(void)
{
    bool clipping;

    // Derivative upper and lower strength are very small
    float d_lower_strength = haptic_state.detent_strength_unit * 0.008;
    float d_upper_strength = haptic_state.detent_strength_unit * 0.004;
    float d_lower_pos_width = radians(3);
    float d_upper_pos_width = radians(8);
    float raw = d_lower_strength;
    raw += (d_upper_strength - d_lower_strength)/(d_upper_pos_width - d_lower_pos_width);
    raw *= haptic_state.detent_width - d_lower_pos_width;
    

    // 1.0.0-cc5.7 (plan F2): the position count in 32 bits and an explicit D rule. It was a uint16_t
    // (end - start + 1), which wrapped to 0 for a range 65,536 positions wide (Onshape's 0..65535 before Desk
    // Dial 7.2.2) and so switched on this D term (the clamped `raw` above): the knob buzzed. A valid range has at
    // least one position, so the D term is never used, exactly as in every earlier release on every range that did
    // not wrap. Real damping comes from the r4 tokens (Kd on the filtered shaft velocity, token_target()), never
    // from this PID's derivative.
    const uint32_t total_positions = cc_positions(haptic_state.detent_profile.start_pos, haptic_state.detent_profile.end_pos);
    (void)raw;
    (void)total_positions;
    haptic_pid->D = 0.0f;

    // Check if within range and apply voltage/current limit.
    if (haptic_state.attract_angle <= haptic_state.last_attract_angle - haptic_state.detent_width)
        clipping = true;

    else if (haptic_state.attract_angle >= haptic_state.last_attract_angle + haptic_state.detent_width)
        clipping = true;

    else
        clipping = false;

    haptic_pid->P = clipping ? haptic_state.endstop_strength_unit : haptic_state.detent_strength_unit;
    
    
    if(haptic_state.wasAtLimit)
    haptic_pid->P = 0;
}

/** 
 * Utility function used for handling detent profile changes
*/
void HapticInterface::offset_detent(void){
    motor->sensor_offset = motor->shaft_angle;
    haptic_state.attract_angle = 0.0;
    haptic_state.last_attract_angle = 0.0;
}

/**
 * Handles motor level control of the detent (haptic texture map) and triggering 
 * updates into the haptic abstraction for detent index and bounding information.
 * This function could be greatly simplified if you don't need to entertain the idea of 
 * an asymmetric texture map, but I didn't want to lock out any functionality yet. 
 * 
 * Separate positive and negative error so that we can have asymmetric haptic textures.
 * Use this for when your fine and coarse detents are straddling the current detent.
*/
void HapticInterface::find_detent(void)
{
    /**
     * hysteresisType is used to handle whether the detents are linear in strength or progressively stronger.
     * We then generate new bounds for the detent based on the hysteresis (as a percentage)
    */
    float detentHysteresis;
    float minHysteresis;
    float maxHysteresis;

    // Special handling for progressive force modes.
    if(!haptic_state.detent_profile.kxForce){
        detentHysteresis = haptic_state.detent_width * haptic_state.attract_hysteresis;
        minHysteresis = haptic_state.attract_angle - detentHysteresis;
        maxHysteresis = haptic_state.attract_angle + detentHysteresis;
    }
    else{
        // 0.1 is a correction factor to compensate for the large hysteresis in normal modes, to make the force per detent reasonable.
        detentHysteresis = 0.15 * haptic_state.attract_hysteresis * -1.0;
        minHysteresis = haptic_state.attract_angle * (1.0 - detentHysteresis);
        maxHysteresis = haptic_state.attract_angle * (1.0 + detentHysteresis);
    }

    if(motor->shaft_angle < minHysteresis){
        // Knob is turned less than detent (left half of texture graph)
        haptic_state.attract_angle = round((motor->shaft_angle - haptic_state.detent_origin) / haptic_state.detent_width);
        haptic_state.attract_angle *= haptic_state.detent_width;
        haptic_state.attract_angle += haptic_state.detent_origin;
    }
    else if(motor->shaft_angle > maxHysteresis){
        // Knob is turned more than detent (right half of texture graph)
        haptic_state.attract_angle = round((motor->shaft_angle - haptic_state.detent_origin) / haptic_state.detent_width);
        haptic_state.attract_angle *= haptic_state.detent_width;
        haptic_state.attract_angle += haptic_state.detent_origin;
    }

    // FW-BUG-010: the committed detent recomputed from the shaft is the committed detent, even when its float
    // differs in the last bits (an attractor stepped by end_freeze()): compare grid indices, never raw angles, so
    // rounding never counts a phantom step.
    if (haptic_state.last_attract_angle != haptic_state.attract_angle && haptic_state.detent_width > 0.0f &&
        cc_detent_index(haptic_state.attract_angle, haptic_state.detent_origin, haptic_state.detent_width) ==
            cc_detent_index(haptic_state.last_attract_angle, haptic_state.detent_origin, haptic_state.detent_width))
        haptic_state.attract_angle = haptic_state.last_attract_angle;

    // If there has been a change in the haptic attractor
    if(haptic_state.last_attract_angle != haptic_state.attract_angle){
        detent_handler();
    }
    else refusedSet_ = false;   // back in the committed detent: the next refused detent at a bound is a new hit
}

/**
 * If there has been an update in the physical location of the detent, this function helps handle
 * the abstraction in terms of detent index and firing off HapticEventCallback.
*/
void HapticInterface::detent_handler(void){
    // Logic for handling detent update events.
    // 1.0.0-cc5.7 (plan F2, the uint16 audit): a VERNIER bound is scaled in 32 bits and clamped at 65535 (it
    // wrapped for end_pos x vernier > 65535).
    const uint16_t scale = haptic_state.detent_profile.mode == HapticMode::VERNIER ? haptic_state.detent_profile.vernier : 1;
    const uint16_t effective_start_pos = cc_scaled_position(haptic_state.detent_profile.start_pos, scale);
    const uint16_t effective_end_pos = cc_scaled_position(haptic_state.detent_profile.end_pos, scale);

    // Check if we are increasing or decreasing detent
    if(haptic_state.last_attract_angle > haptic_state.attract_angle){

        #if PRODUCTION_PCB
        if(motor->sensor_direction == Direction::CCW){
        #else 
        if(motor->sensor_direction != Direction::CCW){
        #endif
            // Check that we are at limit
            if(haptic_state.current_pos > effective_start_pos){
                if(haptic_state.atLimit)
                    haptic_state.wasAtLimit = true;

                haptic_state.atLimit = false;
                haptic_state.current_pos--;
                haptic_state.last_attract_angle = haptic_state.attract_angle;

                HapticEventCallback(HapticEvt::DECREASE);
                detent_pulse(-1);
            }
            else{
                HapticEventCallback(HapticEvt::LIMIT_NEG);
                haptic_state.atLimit = true;
                wall_refused(-1);
            }
        }
        else{
            // Check that we are at limit
            if(haptic_state.current_pos < effective_end_pos){
                if(haptic_state.atLimit)
                    haptic_state.wasAtLimit = true;
                                   
                haptic_state.atLimit = false;
                haptic_state.current_pos++;
                haptic_state.last_attract_angle = haptic_state.attract_angle;

                HapticEventCallback(HapticEvt::INCREASE);
                detent_pulse(1);
            }
            else{
                HapticEventCallback(HapticEvt::LIMIT_POS);
                haptic_state.atLimit = true;
                wall_refused(1);
            }
        }
    
    }
    else{
        #if PRODUCTION_PCB
        if(motor->sensor_direction == Direction::CCW){
        #else
        if(motor->sensor_direction != Direction::CCW){
        #endif
            // Check if we are at limit
            if(haptic_state.current_pos < effective_end_pos){
                if(haptic_state.atLimit)
                    haptic_state.wasAtLimit = true;
                    
                haptic_state.atLimit = false; 
                haptic_state.current_pos++;   
                haptic_state.last_attract_angle = haptic_state.attract_angle;

                HapticEventCallback(HapticEvt::INCREASE);
                detent_pulse(1);
            }
            else{
                HapticEventCallback(HapticEvt::LIMIT_POS);
                haptic_state.atLimit = true;
                haptic_state.wasAtLimit = false;
                wall_refused(1);
            }
        }
        else{
            // Check if we are at limit
            if(haptic_state.current_pos > effective_start_pos){
                if(haptic_state.atLimit)
                    haptic_state.wasAtLimit = true;

                haptic_state.atLimit = false;  
                haptic_state.current_pos--;  
                haptic_state.last_attract_angle = haptic_state.attract_angle;

                HapticEventCallback(HapticEvt::DECREASE);
                detent_pulse(-1);
            }
            else{
                HapticEventCallback(HapticEvt::LIMIT_NEG);
                haptic_state.atLimit = true;
                wall_refused(-1);
            }
        }
    }

    if (haptic_state.atLimit) haptic_state.last_limit_position = haptic_state.current_pos;
    if (!haptic_state.atLimit){
        HapticEventCallback(HapticEvt::EITHER);
    }
}

/**
 * Handling the position error and limit to within a detent, as well as clearing wasAtLimit flag.
*/
void HapticInterface::haptic_target(void)
{
    float error = haptic_state.last_attract_angle - motor->shaft_angle;
    float error_threshold = haptic_state.detent_width * 0.0075; // 0.75% gives good snap without ringing
    // default_pid.output_ramp = haptic_state.detent_profile.output_ramp;
    haptic_pid->output_ramp = haptic_state.detent_profile.output_ramp;
     // Prevent knob velocity from getting too high and overshooting.
    // If the position error is small, reduce strength to prevent oscillation
    if(fabsf(error) < error_threshold)
        error *= 0.75;

    else if(fabsf(motor->shaft_velocity) > 30){

        // Prevent knob velocity from getting too high and overshooting.
        // Low values of this actually provide pretty interesting feeling where knob is smooth while 
        // rotating quickly by hand but snappy during fine adjust.
        error = 0.0;
    }
    else {
        error = CLAMP(
            error,
            -haptic_state.detent_width,
            haptic_state.detent_width
        );
    }

    // When re-entering valid bounds, quickly try to get back to attract angle without involving haptics to prevent sliding into a further detent
    // 1.0.0-cc5.5 (F1): braces made explicit, behaviour unchanged. The indentation suggested that the
    // else covered both calls, but only loopFOC() was conditional: move() has always run after
    // bounds_handler() too (bounds_handler() runs its own loopFOC()/move() pairs; this move() sets the
    // target the next pass's loopFOC() applies). Kept exactly so: F1 changes no feel.
    if(!haptic_state.atLimit && haptic_state.wasAtLimit){
        bounds_handler(haptic_state.detent_width);
    }
    else {
        motor->loopFOC();
    }
    // 1.0.0-cc5.7: a host effect (frame `haptic`) adds its pulses to the PID output, clamped to the cap. Without
    // one, fx_.volts() is 0 and the PID output (limit 0.4 A) is below the cap, as in 1.0.0-cc5.6, except that
    // rest sleep (below) now zeroes the output and resets the PID while the knob rests.
    const uint32_t now = micros();
    float out = default_pid(error) + fx_.volts(now) / CC_HAPTIC_PHASE_OHMS;
    // Rest sleep (2026-09-30; cc_haptic_fx.h CCRestGate), in the legacy loop too: zero output while the knob sits still
    // on its detent; the PID restarts from 0 on waking (its output ramp eases the force back in).
    const bool busy = fx_.busy(now) || haptic_state.wasAtLimit || frozen_;
    if (rest_.step(now, motor->shaft_angle, haptic_state.last_attract_angle - motor->shaft_angle, motor->shaft_velocity,
                   busy, cc_rest_wake_rad(haptic_state.detent_width))) {
        out = 0.0f;
        haptic_pid->reset();
    }
    motor->move(out > CC_HAPTIC_CAP_AMPS ? CC_HAPTIC_CAP_AMPS : (out < -CC_HAPTIC_CAP_AMPS ? -CC_HAPTIC_CAP_AMPS : out));
}

/**
 * Handles the transition from out of bounds to in bounds movement 
 * to prevent overshooting by escaping from the haptic loop to settle the response.
*/
void HapticInterface::bounds_handler(float detent_width)
{
    float error = 0.0;
    const unsigned long recoveryStarted = micros();

    while(fabsf(motor->shaft_velocity) > 1.0){
        // Return to the main loop promptly so input/configuration and the lease
        // cannot be starved by continuous movement at a boundary.
        if ((unsigned long)(micros() - recoveryStarted) >= CC_BOUNDS_RECOVERY_US) break;
        error = haptic_state.attract_angle - motor->shaft_angle;
        // If you are driving the motor by hand, skip out of here so that you don't feel dragging on the knob
        if(fabsf(error) > (detent_width * 2))
            break;

        motor->loopFOC();
        motor->move(default_pid(error));
    }

    const uint16_t scale = haptic_state.detent_profile.mode == HapticMode::VERNIER ? haptic_state.detent_profile.vernier : 1;
    // 1.0.0-cc5.7 (the uint16 audit): the scaled bounds without wrapping (cc_scaled_position).
    haptic_state.current_pos = inward_from_boundary(
        cc_scaled_position(haptic_state.detent_profile.start_pos, scale),
        cc_scaled_position(haptic_state.detent_profile.end_pos, scale),
        haptic_state.last_limit_position);

    // Clear boundary exit flag
    haptic_state.wasAtLimit = false;
}
// Internal detent update handler.
void HapticInterface::HapticEventCallback(HapticEvt event){
    UserHapticEventCallback(event, motor->shaft_angle, haptic_state.current_pos);
}

// 1.0.0-cc5.7 (plan F3): the user callback no longer plays the per-detent `hard` sample (it lived in audio.cpp and
// fired on every native detent). Detent sounds are the r4 tokens' (detent_pulse()), only for a host that asked.
void HapticInterface::UserHapticEventCallback(HapticEvt event, float currentAngle, uint16_t currentPos){
    (void)event; (void)currentAngle; (void)currentPos;
}

// ---------------------------------------------------------------------------------------------------------------
// r4 feel (1.0.0-cc5.7, plan F2; cc_haptic_fx.h, HAPTICS.md).

void HapticInterface::set_feel(uint8_t feel, bool reduced, uint8_t sound, uint32_t fadeMs) {
#if CC_HAPTIC_TOKENS
    feel_ = feel < CC_FEEL_COUNT ? feel : static_cast<uint8_t>(CC_FEEL_LEGACY);
#else
    (void)feel;
    feel_ = CC_FEEL_LEGACY;
#endif
    reduced_ = reduced;
    sound_ = sound;
    fp_ = cc_feel_params(feel_, reduced_);
    springOut_ = 0.0f;
    wallVolts_ = 0.0f;
    lastUsSet_ = false;
    refusedSet_ = false;
    fade_.start(feel_ != CC_FEEL_LEGACY ? fadeMs : 0, micros());
}

void HapticInterface::restart_fade(uint32_t fadeMs) {
    if (feel_ == CC_FEEL_LEGACY || fadeMs == 0) return;
    fade_.start(fadeMs, micros());
}

bool HapticInterface::coasting() const {
    const float speed = fabsf(motor->shaft_velocity);
    return (feel_ == CC_FEEL_LEGACY || fp_.coast) && speed > CC_HAPTIC_COAST_RAD_S;
}

bool HapticInterface::play_effect(uint8_t fx) {
#if CC_HAPTIC_FX
    CCSoundCue cue;
    if (!fx_.start(fx, reduced_, micros(), motor->shaft_velocity, coasting(), cue)) return false;
    cc_sound_post(cue, sound_);
    return true;
#else
    (void)fx;
    return false;
#endif
}

// The angle sign of a position increase, as detent_handler() counts (PRODUCTION_PCB: a CCW sensor counts up with
// the angle, any other direction counts down).
int8_t HapticInterface::angle_sign_of_increase() const {
#if PRODUCTION_PCB
    return motor->sensor_direction == Direction::CCW ? 1 : -1;
#else
    return motor->sensor_direction != Direction::CCW ? 1 : -1;
#endif
}

// How far (rad, > 0) the shaft is past the centre of the committed detent towards a bound the position is at (0
// when it is not at a bound or leans inward); `outward` is that direction's angle sign.
float HapticInterface::wall_penetration(int8_t& outward) const {
    outward = 0;
    const uint16_t scale = haptic_state.detent_profile.mode == HapticMode::VERNIER ? haptic_state.detent_profile.vernier : 1;
    const uint16_t lo = cc_scaled_position(haptic_state.detent_profile.start_pos, scale);
    const uint16_t hi = cc_scaled_position(haptic_state.detent_profile.end_pos, scale);
    const float d = motor->shaft_angle - haptic_state.last_attract_angle;
    const int8_t inc = angle_sign_of_increase();
    if (haptic_state.current_pos >= hi && d * inc > 0.0f) { outward = inc; return d * inc; }
    if (haptic_state.current_pos <= lo && d * inc < 0.0f) { outward = static_cast<int8_t>(-inc); return -d * inc; }
    return 0.0f;
}

// The end of an effect's freeze (haptic_loop). In a viscous feel there is no well to pull the knob back, so the detent
// grid moves with the pulses' displacement (a pulse never counts as a turn): cc_freeze_absorb(), the shift less the
// hand's turn estimated from the speeds at the freeze's start and end, bounded. FW-BUG-033: the whole shift moved the
// grid when the knob ended below the freeze speed, so a hand turning during the freeze (Onshape orbit / pan, Seek,
// under 2 rad/s) lost those counts. The rest of the shift (the turn), and any turn in another feel, is counted one
// detent at a time through detent_handler(), as the loop would have, so none is lost; a bound stops the count as it
// always does.
void HapticInterface::end_freeze(void) {
    const float shift = motor->shaft_angle - freezeAngle_;
    const float elapsed = static_cast<float>(static_cast<uint32_t>(micros() - freezeUs_)) * 1e-6f;
    const float absorb = cc_freeze_absorb(feel_ != CC_FEEL_LEGACY && fp_.law == CC_LAW_VISCOSE, freezeVelocity_,
                                          motor->shaft_velocity, elapsed, shift, haptic_state.detent_width);
    if (absorb != 0.0f) {
        haptic_state.detent_origin += absorb;
        haptic_state.attract_angle += absorb;
        haptic_state.last_attract_angle += absorb;
    }
    const float w = haptic_state.detent_width;
    if (w <= 0.0f) return;
    // FW-BUG-010: in grid indices; each stepped attractor is the grid's own (cc_detent_angle(), find_detent()'s
    // arithmetic), never last + w (which drifted from the grid by float rounding and counted a phantom step).
    const float origin = haptic_state.detent_origin;
    const long target = cc_detent_index(motor->shaft_angle, origin, w);
    int32_t steps = static_cast<int32_t>(target - cc_detent_index(haptic_state.last_attract_angle, origin, w));
    for (int32_t i = 0; i < 256 && steps != 0; ++i) {
        const long from = cc_detent_index(haptic_state.last_attract_angle, origin, w);
        haptic_state.attract_angle = cc_detent_angle(from + (steps > 0 ? 1 : -1), origin, w);
        detent_handler();
        if (haptic_state.atLimit) break;
        steps += steps > 0 ? -1 : 1;
    }
}

// A detent refused at a bound (LIMIT_POS +1 / LIMIT_NEG -1): once per refused detent (the attractor moved to a new
// detent past the bound), never once per pass. cc_wall.h: the UI's M13 stretch and end-of-arc LEDs.
void HapticInterface::wall_refused(int8_t dir) {
    if (refusedSet_ && refusedAttract_ == haptic_state.attract_angle) return;
    refusedSet_ = true;
    refusedAttract_ = haptic_state.attract_angle;
    rest_.refused();   // FW-BUG-036: a refused detent wakes a sleeping gate this pass, so the wall comes with its thud
    cc_wall_hit(dir);
#if CC_HAPTIC_FX
    // 2026-09-30 (the user: every interaction has a sound): an end stop thuds once per refused detent, with the
    // wall's own force as its haptic. Not in the legacy loop or under reduced haptics.
    if (feel_ != CC_FEEL_LEGACY && !reduced_) {
        const CCSoundCue wall = {CC_SOUND_THUD, 50, 1, 0};
        cc_sound_post(wall, sound_);
    }
#endif
}

// A detent was crossed (position +1 / -1): the token's detent pulse (value / dimmer / list / coarse / fine) against
// the motion, and its sound. A fluid feel (no pulse) plays its sound alone. Never in the legacy loop, reduced haptics
// or while coasting (the player drops it then).
void HapticInterface::detent_pulse(int8_t positionDir) {
#if CC_HAPTIC_FX
    if (feel_ == CC_FEEL_LEGACY) return;
    if (!fp_.pulse) {
        if (fp_.sound.sound != CC_SOUND_NONE && !coasting()) cc_sound_post(fp_.sound, sound_);
        return;
    }
    CCSoundCue cue;
    const int8_t sign = static_cast<int8_t>(-positionDir * angle_sign_of_increase());
    if (fx_.start(CC_HFX_DETENT, reduced_, micros(), motor->shaft_velocity, coasting(), cue, sign, fp_.pulse, fp_.sound))
        cc_sound_post(cue, sound_);
#else
    (void)positionDir;
#endif
}

// One pass of a token feel: the law (SAW / SINE / none) faded in, or the wall past a bound (volts, fold-back,
// never zeroed by coasting), the profile's output ramp on the spring, damping (the token's Kd or hold.tension's),
// the effect, all clamped to the cap. The bound recovery (bounds_handler) and the limit flags are the legacy ones.
void HapticInterface::token_target(void) {
    const uint32_t now = micros();
    const float dt = lastUsSet_ ? static_cast<float>(static_cast<uint32_t>(now - lastUs_)) * 1e-6f : 0.0f;
    lastUs_ = now; lastUsSet_ = true;
    const float w = haptic_state.detent_width;
    const float velocity = motor->shaft_velocity;
    float spring = 0.0f;
    wallVolts_ = 0.0f;
    int8_t outward = 0;
    const float pen = CC_HAPTIC_WALL ? wall_penetration(outward) : 0.0f;
    if (pen > 0.0f && outward != 0) {
        const float cap = CC_HAPTIC_CAP_VOLTS * (CC_HAPTIC_FOLDBACK ? fold_.factor() : 1.0f);
        // The wall fades in with the feel (feel.fade, restarted on waking from rest).
        wallVolts_ = cc_wall_volts(cc_law_slope(fp_.law, fp_.kp), pen, w, cap) *
                     fade_.factor(now);                       // FW-BUG-037: cleared once complete
        spring = -static_cast<float>(outward) * wallVolts_ / CC_HAPTIC_PHASE_OHMS;
        springOut_ = spring;                                  // the wall is never slewed
    } else {
        float error = haptic_state.last_attract_angle - motor->shaft_angle;
        if (fabsf(error) < w * 0.0075f) error *= 0.75f;      // the legacy anti-ringing trim at the centre
        const bool coast = fp_.coast && fabsf(velocity) > CC_HAPTIC_COAST_RAD_S;
        const float kp = fp_.kp * fade_.factor(now);
        spring = (coast || haptic_state.wasAtLimit) ? 0.0f : cc_law_spring(fp_.law, kp, error, w);
        const float ramp = haptic_state.detent_profile.output_ramp;   // A/s, as default_pid applies it
        if (ramp > 0.0f && dt > 0.0f) {
            const float step = ramp * dt;
            if (spring > springOut_ + step) spring = springOut_ + step;
            else if (spring < springOut_ - step) spring = springOut_ - step;
        }
        springOut_ = spring;
    }
    float kd = fp_.kd;
    if (!reduced_) {
        const float hold = cc_hold_tension_kd(static_cast<uint32_t>(millis()));
        if (hold > kd) kd = hold;
    }
    float out = spring + cc_damping(kd, velocity) + fx_.volts(now) / CC_HAPTIC_PHASE_OHMS;
    out = out > CC_HAPTIC_CAP_AMPS ? CC_HAPTIC_CAP_AMPS : (out < -CC_HAPTIC_CAP_AMPS ? -CC_HAPTIC_CAP_AMPS : out);
    // Rest sleep (cc_haptic_fx.h CCRestGate): still on the detent for a moment -> zero output; any movement, a new
    // attractor or anything playing wakes it, and the spring eases back in from 0 (springOut_, the output ramp).
    // Resting at a bound is rest too: a push into the wall wakes it by its distance, like any turn (the wall's
    // penetration is the error then, so a knob held into the wall stays awake), or by its refused detent
    // (FW-BUG-036: wall_refused() -> rest_.refused(), the thud and the wall's force in the same pass).
    const bool busy = fx_.busy(now) || kd > fp_.kd || haptic_state.wasAtLimit || frozen_;
    const bool wasAsleep = rest_.asleep();
    if (rest_.step(now, motor->shaft_angle, haptic_state.last_attract_angle - motor->shaft_angle, velocity, busy,
                   cc_rest_wake_rad(w))) {
        out = 0.0f;
        springOut_ = 0.0f;
        wallVolts_ = 0.0f;                                    // FW-TST-001: the wall applies nothing while asleep
    } else if (wasAsleep) {
        restart_fade(CC_FEEL_FADE_MS);                        // woken: the spring and the wall ease in (feel.fade)
    }
    // The fold-back integrates the wall volts actually applied (FW-TST-001: after the rest gate; a finger resting past
    // the bound while asleep heated a phantom wall and halved the next real push).
#if CC_HAPTIC_FOLDBACK
    fold_.step(wallVolts_, dt);
#endif
    if(!haptic_state.atLimit && haptic_state.wasAtLimit){
        bounds_handler(haptic_state.detent_width);
    }
    else {
        motor->loopFOC();
    }
    motor->move(out);
}

