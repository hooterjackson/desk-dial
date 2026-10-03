// r4 FEEL (1.0.0-cc5.7, plan stage F2; HAPTICS.md): the haptic token engine's pure parts, header-only and
// platform-neutral (no Arduino, no SimpleFOC), so harness/haptic_fx_tests.py compiles this same file with
// MSVC and cpp11_gate.py with the device's gnu++11. The FOC thread (haptic.cpp, foc_thread.cpp) drives it.
//
// Design source: Claude Design r4 (design_handoff_nano_d_r4 README sections 2, 4 and 6; prototypes/haptic-lab.js).
// The effect player, the pulse shape and the token table are adapted from Karl Malota's NanoD_RatchetH1
// feat/firmware-esp-idf-quadra (control_task.c / haptic_params.h), used with his permission; the numbers are
// translated to this firmware's units (below), the ratios between tokens are kept.
//
// Units. The haptic loop commands a "current" target (SimpleFOC torque/voltage mode with phase_resistance set:
// Uq = target x R, R = 5.3 ohm), clamped by motor.voltage_limit (the 2.2 V cap, F1). The legacy detent PID has
// P = 3 A/rad and an output limit of 0.4 A (2.12 V). Karl's Kp / Kd are voltage-mode numbers; here the token
// Kp is in A/rad with detent.value's Kp 3 == today's detent strength (so Home volume keeps today's BINARIS BEER
// strength, user ruling "feel must not change"), and every other Kp / Kd keeps Karl's ratio to it (Kd in
// A/(rad/s) = Karl's number x CC_HAPTIC_KD_SCALE, 1 by default; tuned by feel on the hardware).
//
// C++11 (cpp11_gate.py): namespace-scope constexpr only, constexpr functions are single return statements.
#pragma once

#include <errno.h>
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

// ---------------------------------------------------------------------------------------------------------------
// Feature switches (plan F2 "a -D flag for each feature"). Every one defaults on; -D<NAME>=0 builds without it.
// The runtime off switch is the host: a control without `feel` runs the legacy (1.0.0-cc5.6) haptic loop exactly.
#ifndef CC_HAPTIC_TOKENS
#define CC_HAPTIC_TOKENS 1      // the `feel` tokens (laws, Kp/Kd, density, feel.fade, hold.tension)
#endif
#ifndef CC_HAPTIC_FX
#define CC_HAPTIC_FX 1          // the effect player (frame `haptic` events, detent pulses)
#endif
#ifndef CC_HAPTIC_WALL
#define CC_HAPTIC_WALL 1        // the r4 end-stop wall law (token mode only)
#endif
#ifndef CC_HAPTIC_FOLDBACK
#define CC_HAPTIC_FOLDBACK 1    // the I2t fold-back of the wall
#endif
#ifndef CC_HAPTIC_TRIP
#define CC_HAPTIC_TRIP 1        // the self-spin trip (every mode)
#endif
#ifndef CC_SUPPLY_FROM_PD
#define CC_SUPPLY_FROM_PD 1     // driver.voltage_power_supply from the negotiated PD contract (fails safe high)
#endif
#ifndef CC_OFFLINE_VOLUME
#define CC_OFFLINE_VOLUME 1     // HID Consumer Control volume while no host has the port open (plan F3)
#endif
#ifndef CC_HAPTIC_KD_SCALE
#define CC_HAPTIC_KD_SCALE 1.0f // A/(rad/s) per Karl-Kd unit (see the header comment)
#endif

// ---------------------------------------------------------------------------------------------------------------
// Motor constants (foc_thread.cpp / haptic.cpp use the same numbers).
constexpr float CC_HAPTIC_PHASE_OHMS = 5.3f;     // BLDCMotor(7, 5.3): target (A) x R = Uq (V)
constexpr float CC_HAPTIC_CAP_VOLTS = 2.2f;      // motor.voltage_limit (F1)
constexpr float CC_HAPTIC_CAP_AMPS = CC_HAPTIC_CAP_VOLTS / CC_HAPTIC_PHASE_OHMS;
constexpr float CC_HAPTIC_SPRING_AMPS = 0.4f;    // the legacy PID output limit (default_pid), kept for springs
constexpr float CC_HAPTIC_COAST_RAD_S = 30.0f;   // the legacy "> 30 rad/s: zero spring" coasting speed
constexpr float CC_HAPTIC_DAMP_DEADBAND = 0.8f;  // rad/s: velocity noise below this is not damped (0.5 until
                                                 // 2026-09-30: the user still felt a buzz while awake)
constexpr float CC_HAPTIC_PI = 3.14159265358979f;

// ---------------------------------------------------------------------------------------------------------------
// Feel tokens (control `feel`, capability `feel` 1). Append-only; 0 = no token (legacy haptics).
enum CCFeel : uint8_t {
    CC_FEEL_LEGACY = 0, CC_FEEL_VALUE, CC_FEEL_DIMMER, CC_FEEL_LIST, CC_FEEL_COARSE, CC_FEEL_FINE,
    CC_FEEL_SCRUB, CC_FEEL_LIGHT, CC_FEEL_FREE_SPIN, CC_FEEL_COUNT
};
constexpr const char* CC_FEEL_TOKENS[CC_FEEL_COUNT] = {
    "", "detent.value", "detent.dimmer", "detent.list", "detent.coarse", "detent.fine",
    "fluid.scrub", "fluid.light", "free.spin"};

inline const char* cc_feel_name(uint8_t feel) { return feel < CC_FEEL_COUNT ? CC_FEEL_TOKENS[feel] : ""; }
// A wire token (never "") -> CCFeel. False for anything else ("wall.bounce" is not a turn feel: walls are
// always on; "feel.fade" / "hold.tension" are the knob's own modifiers).
inline bool cc_feel_parse(const char* token, uint8_t& out) {
    if (!token || !*token) return false;
    for (uint8_t i = 1; i < CC_FEEL_COUNT; ++i)
        if (!strcmp(token, CC_FEEL_TOKENS[i])) { out = i; return true; }
    return false;
}

// Sounds (plan F3; r4 section 6). The click bank renders these once into RAM (cc_sound.h).
enum CCSound : uint8_t { CC_SOUND_NONE = 0, CC_SOUND_WOOD, CC_SOUND_THUD, CC_SOUND_FINE, CC_SOUND_THUMP, CC_SOUND_COUNT };
// One sound request: `repeats` plays (1..3) of `sound`, their starts `gapMs` apart, at `level` % of full scale
// (before the host's master level). A zero sound or level is silent.
struct CCSoundCue {
    uint8_t sound;
    uint8_t level;
    uint8_t repeats;
    uint8_t gapMs;
};
constexpr CCSoundCue CC_SOUND_SILENT = {CC_SOUND_NONE, 0, 0, 0};
// The host's master level (control `sound`, capability knobSound 1): 0 off, 1 Low, 2 Medium, 3 High.
constexpr uint32_t CC_SOUND_MASTER_LEVEL_MAX = 3;
// The master volume percent (control `soundVolume`, capability knobVolume 1; 2026-09-30): 100 = the thump at full scale.
constexpr uint32_t CC_SOUND_VOLUME_MAX = 100;

// Laws (r4 4.1: SAW / SINE / VISCOSE).
enum CCLaw : uint8_t { CC_LAW_SAW = 0, CC_LAW_SINE, CC_LAW_VISCOSE };

// One token's parameters (r4 4.2, translated; HAPTICS.md "Tokens").
struct CCFeelParams {
    uint8_t law;
    uint8_t detents;     // per turn; 0 = the control's profile (detent.value / dimmer keep BINARIS BEER's 67)
    float kp;            // A/rad (3 = today's detent strength); 0 for VISCOSE
    float kd;            // A/(rad/s)
    uint8_t pulse;       // the detent pulse, % of the cap (0 = none)
    bool coast;          // zero spring above CC_HAPTIC_COAST_RAD_S (free spin); pulses are dropped meanwhile
    CCSoundCue sound;    // the detent sound
};

inline CCFeelParams cc_feel_make(uint8_t law, uint8_t detents, float kp, float kdKarl, uint8_t pulse, bool coast,
                                 CCSoundCue sound) {
    CCFeelParams p;
    p.law = law; p.detents = detents; p.kp = kp; p.kd = kdKarl * CC_HAPTIC_KD_SCALE;
    p.pulse = pulse; p.coast = coast; p.sound = sound;
    return p;
}

// r4 section 4.2 table with its reduced-haptics column (section 7: pulses -> soft steps, no coasting; walls stay).
// value / dimmer keep today's coasting (a fast volume spin coasts as it always has; HAPTICS.md deviation D1).
inline CCFeelParams cc_feel_params(uint8_t feel, bool reduced) {
    // Levels x 2 of r4 section 6 (2026-09-30, by ear: the r4 30 / 35 / 20 were near silent on the knob), so the thump,
    // the loudest sound, is full scale at soundVolume 100; the ratios between sounds are r4's.
    const CCSoundCue wood = {CC_SOUND_WOOD, 60, 1, 0}, thud = {CC_SOUND_THUD, 70, 1, 0}, fine = {CC_SOUND_FINE, 40, 1, 0};
    // 2026-09-30, the user: every interaction has a sound and a haptic. Volume and brightness detents tick (a light
    // pulse and a softer tock; brightness a little heavier, as its feel is), and the fluid feels (Seek, Onshape orbit /
    // pan) click quietly on every count they report (sound only: a fluid feel has no detents to pulse against).
    const CCSoundCue valueTock = {CC_SOUND_WOOD, 45, 1, 0}, dimmerTock = {CC_SOUND_WOOD, 50, 1, 0},
                     fluidClick = {CC_SOUND_FINE, 30, 1, 0};
    switch (feel) {
        case CC_FEEL_VALUE:
            return reduced ? cc_feel_make(CC_LAW_VISCOSE, 0, 0.0f, 0.02f, 0, false, CC_SOUND_SILENT)
                           : cc_feel_make(CC_LAW_SINE, 0, 3.0f, 0.01f, 15, true, valueTock);
        case CC_FEEL_DIMMER:
            return reduced ? cc_feel_make(CC_LAW_VISCOSE, 0, 0.0f, 0.05f, 0, false, CC_SOUND_SILENT)
                           : cc_feel_make(CC_LAW_SINE, 0, 3.0f, 0.04f, 20, true, dimmerTock);
        case CC_FEEL_LIST:
            return reduced ? cc_feel_make(CC_LAW_SINE, 20, 6.0f, 0.01f, 0, false, CC_SOUND_SILENT)
                           : cc_feel_make(CC_LAW_SAW, 20, 6.0f, 0.01f, 35, false, wood);
        case CC_FEEL_FREE_SPIN:
            return reduced ? cc_feel_make(CC_LAW_SINE, 20, 6.0f, 0.01f, 0, false, CC_SOUND_SILENT)
                           : cc_feel_make(CC_LAW_SAW, 20, 6.0f, 0.01f, 35, true, wood);
        case CC_FEEL_COARSE:
            return reduced ? cc_feel_make(CC_LAW_SINE, 12, 6.0f, 0.02f, 0, false, CC_SOUND_SILENT)
                           : cc_feel_make(CC_LAW_SAW, 12, 11.0f, 0.02f, 50, false, thud);
        case CC_FEEL_FINE:
            return reduced ? cc_feel_make(CC_LAW_SINE, 36, 2.5f, 0.01f, 0, false, CC_SOUND_SILENT)
                           : cc_feel_make(CC_LAW_SAW, 36, 2.5f, 0.01f, 25, false, fine);
        case CC_FEEL_SCRUB:
            return reduced ? cc_feel_make(CC_LAW_VISCOSE, 0, 0.0f, 0.08f, 0, false, CC_SOUND_SILENT)
                           : cc_feel_make(CC_LAW_VISCOSE, 0, 0.0f, 0.08f, 0, false, fluidClick);
        case CC_FEEL_LIGHT:
            return reduced ? cc_feel_make(CC_LAW_VISCOSE, 0, 0.0f, 0.02f, 0, false, CC_SOUND_SILENT)
                           : cc_feel_make(CC_LAW_VISCOSE, 0, 0.0f, 0.02f, 0, false, fluidClick);
        default:
            // Legacy: today's loop (haptic.cpp keeps the PID path; these numbers only describe it).
            return cc_feel_make(CC_LAW_SAW, 0, 3.0f, 0.0f, 0, true, CC_SOUND_SILENT);
    }
}

// ---------------------------------------------------------------------------------------------------------------
// The detent laws (amps; `error` = attractor - shaft in rad, `width` = the detent pitch in rad). SAW is the legacy
// linear well (P x error, the attractor flips at the midpoint). SINE is a smooth well with SAW's peak: A sin(2 pi e/w),
// A = kp w / 2, zero at the midpoint (soft steps; HAPTICS.md "SINE peak matching"). VISCOSE has no well.
inline float cc_law_spring(uint8_t law, float kp, float error, float width) {
    if (law == CC_LAW_VISCOSE || width <= 0.0f) return 0.0f;
    const float e = error > width ? width : (error < -width ? -width : error);
    const float out = law == CC_LAW_SINE ? kp * (width * 0.5f) * sinf(2.0f * CC_HAPTIC_PI * e / width) : kp * e;
    return out > CC_HAPTIC_SPRING_AMPS ? CC_HAPTIC_SPRING_AMPS : (out < -CC_HAPTIC_SPRING_AMPS ? -CC_HAPTIC_SPRING_AMPS : out);
}

// A law's stiffness at the well's centre (A/rad): SAW kp, SINE kp x pi (A sin(2 pi e / w) with A = kp w / 2).
inline float cc_law_slope(uint8_t law, float kp) {
    return law == CC_LAW_SINE ? kp * CC_HAPTIC_PI : (law == CC_LAW_VISCOSE ? 0.0f : kp);
}

// The r4 wall (4.3, "wall.bounce"): past the bound detent's centre by `pen` rad (> 0), a spring whose stiffness
// ramps from the law's centre stiffness `kp` (cc_law_slope, so the push-back starts exactly as the well would) to
// 3 x that one pitch out ("the next detent becomes a wall; 0 -> 3 x Kp"), in VOLTS, capped at `capVolts` (the
// 2.2 V cap times the fold-back factor). No step and no zero crossing: the push-back grows the further you go.
// Kp in A/rad is converted with R. A viscous token (no well) walls with detent.value's SAW stiffness, 3 A/rad.
inline float cc_wall_volts(float kp, float pen, float width, float capVolts) {
    if (pen <= 0.0f || capVolts <= 0.0f) return 0.0f;
    const float k = (kp > 0.0f ? kp : 3.0f) * CC_HAPTIC_PHASE_OHMS;           // V/rad
    const float ramp = width > 0.0f ? (pen >= width ? 1.0f : pen / width) : 1.0f;
    const float volts = k * (1.0f + 2.0f * ramp) * pen;
    return volts > capVolts ? capVolts : volts;
}

// Damping (amps) from the filtered shaft velocity, with a small deadband against sensor noise.
// Rest sleep (2026-09-30, the user: "the knob constantly delicately vibrates ... make the haptic engine come to life on
// interactions and go back to sleep with no interactions"). At rest the spring answers the angle sensor's noise and
// the damping the velocity estimate's noise, many times a second: a fine buzz under the finger. After the knob has
// sat on its detent, still, for CC_REST_IDLE_MS the output is zero (asleep: silent and still). It wakes, and the
// force eases back in through the output ramp, the moment the shaft moves CC_REST_WAKE_RAD from where it fell asleep,
// the attractor moves away from it (a new control re-anchors, a detent is crossed), or anything plays (`busy`: an
// effect, a hold's tension, a wall, the limit handler). Thresholds in shaft radians: asleep within 0.3 degrees, woken
// by 2.5 degrees (the user's checks, 2026-09-30: 0.5 and then 1.5 still woke on a touch; 2.5 is still inside half a
// volume detent, 2.7 of 5.4 degrees, so a turn wakes it before the next step) and far above the MT6701's noise
// (14 bits: 0.022 degrees a count).
constexpr uint32_t CC_REST_IDLE_MS = 250;
constexpr float CC_REST_BAND_RAD = 0.3f * CC_HAPTIC_PI / 180.0f;    // |error| to fall asleep
constexpr float CC_REST_WAKE_RAD = 2.5f * CC_HAPTIC_PI / 180.0f;    // movement, or |error|, that wakes it
constexpr float CC_REST_VELOCITY_RAD_S = 0.8f;                      // |velocity| to fall asleep
// The wake distance of a profile (2026-09-30, the user: "make haptics kick in after the first detent"): one detent
// width, at least CC_REST_WAKE_RAD and at most one volume detent (67 a turn, 5.4 degrees), so a touch never wakes it.
// A pulsed feel wakes earlier in practice: its first counted step (half a detent) plays a pulse and a click (busy).
constexpr float CC_REST_WAKE_MAX_RAD = 2.0f * CC_HAPTIC_PI / 67.0f;
inline float cc_rest_wake_rad(float detentWidth) {
    return detentWidth > CC_REST_WAKE_MAX_RAD ? CC_REST_WAKE_MAX_RAD
                                              : (detentWidth < CC_REST_WAKE_RAD ? CC_REST_WAKE_RAD : detentWidth);
}
// At a bound the knob rests against the wall's edge like anywhere else: a push into the wall wakes it only once it
// has moved the wake distance (2026-09-30, the user: at Lights 100 % the lightest touch woke it and the stiff wall
// buzzed). While asleep the wall exerts nothing; once awake it fades in over CC_FEEL_FADE_MS (no kick).
// FW-BUG-036 (2026-10-03, the user): a detent refused at a bound (the wall thud and cc_wall_hit, half a detent past
// the bound) is busy: refused() wakes the gate on its next step, so the wall's force comes with its thud instead of
// about 2.7 degrees later (67 a turn). Only that event; an ordinary push still wakes at the wake distance.
class CCRestGate {
public:
    CCRestGate() : asleep_(false), quiet_(false), refused_(false), sleepAngle_(0.0f), quietSinceUs_(0), sleeps_(0),
                   wakes_(0) {}
    // A detent was refused at a bound (HapticInterface::wall_refused): the next step counts as busy.
    void refused() { refused_ = true; }
    // One pass: returns true while the output must be zero. `error` is attractor - shaft (radians).
    bool step(uint32_t nowUs, float angle, float error, float velocity, bool busy, float wakeRad = CC_REST_WAKE_RAD) {
        if (refused_) { busy = true; refused_ = false; }
        if (asleep_) {
            const float moved = angle - sleepAngle_;
            if (busy || moved > wakeRad || moved < -wakeRad || error > wakeRad || error < -wakeRad) {
                asleep_ = false;
                quiet_ = false;
                ++wakes_;
            }
            return asleep_;
        }
        const bool still = !busy && error < CC_REST_BAND_RAD && error > -CC_REST_BAND_RAD &&
                           velocity < CC_REST_VELOCITY_RAD_S && velocity > -CC_REST_VELOCITY_RAD_S;
        if (!still) { quiet_ = false; return false; }
        if (!quiet_) { quiet_ = true; quietSinceUs_ = nowUs; return false; }
        if (static_cast<uint32_t>(nowUs - quietSinceUs_) < CC_REST_IDLE_MS * 1000u) return false;
        asleep_ = true;
        sleepAngle_ = angle;
        ++sleeps_;
        return true;
    }
    void wake() { if (asleep_) ++wakes_; asleep_ = false; quiet_ = false; }
    bool asleep() const { return asleep_; }
    uint32_t sleeps() const { return sleeps_; }
    uint32_t wakes() const { return wakes_; }

private:
    bool asleep_, quiet_, refused_;
    float sleepAngle_;
    uint32_t quietSinceUs_, sleeps_, wakes_;
};

inline float cc_damping(float kd, float velocity, float deadband = CC_HAPTIC_DAMP_DEADBAND) {
    if (kd <= 0.0f) return 0.0f;
    const float mag = velocity < 0.0f ? -velocity : velocity;
    if (mag <= deadband) return 0.0f;
    const float v = velocity < 0.0f ? -(mag - deadband) : (mag - deadband);
    return -kd * v;
}

// feel.fade (r4 4.2): Kp ramps 0 -> target over `fadeMs` after a context change (120 ms; 150 ms after a sleep wake).
inline float cc_fade_factor(uint32_t elapsedUs, uint32_t fadeMs) {
    if (fadeMs == 0) return 1.0f;
    const float x = static_cast<float>(elapsedUs) / (static_cast<float>(fadeMs) * 1000.0f);
    return x >= 1.0f ? 1.0f : (x <= 0.0f ? 0.0f : x);
}
constexpr uint32_t CC_FEEL_FADE_MS = 120;
constexpr uint32_t CC_FEEL_WAKE_FADE_MS = 150;
// FW-BUG-037: one feel.fade (FOC thread only; HapticInterface::set_feel() / restart_fade() start it). A fade is
// cleared on the first pass after it completes, so its factor stays 1 until the next start. It was kept forever and
// recomputed from (now - start) on every pass: 2^32 us (71.6 min) later without a restart (a knob held into the wall,
// hold.tension, never still), the uint32 difference wrapped to a small number and the spring and the wall vanished
// and faded back in under the finger.
class CCFeelFade {
public:
    CCFeelFade() : startUs_(0), ms_(0) {}
    void start(uint32_t fadeMs, uint32_t nowUs) { ms_ = fadeMs; startUs_ = nowUs; }
    float factor(uint32_t nowUs) {
        if (ms_ == 0) return 1.0f;
        const uint32_t elapsed = nowUs - startUs_;
        if (elapsed / 1000u >= ms_) { ms_ = 0; return 1.0f; }   // complete: cleared (no uint32 overflow in ms x 1000)
        return cc_fade_factor(elapsed, ms_);
    }
    bool fading() const { return ms_ != 0; }

private:
    uint32_t startUs_, ms_;
};

// hold.tension (r4 4.2; open question 1 answered: 4 stages, no per-tick ramp): while button 1 (600 ms) or 4
// (1000 ms) is held for its secondary action, Kd steps 0.01 -> 0.12 in four stages (25 % each); none from the
// hold's maturity on (the landing is the host's thump) or after the release. Returns 0 when no stage applies.
constexpr float CC_HOLD_KD_START = 0.01f;
constexpr float CC_HOLD_KD_END = 0.12f;
inline float cc_hold_kd(uint32_t elapsedMs, uint32_t durationMs) {
    if (durationMs == 0 || elapsedMs >= durationMs) return 0.0f;
    const uint32_t stage = (elapsedMs * 4u) / durationMs;                        // 0..3
    return (CC_HOLD_KD_START + (CC_HOLD_KD_END - CC_HOLD_KD_START) * static_cast<float>(stage + 1u) / 4.0f) *
           CC_HAPTIC_KD_SCALE;
}

// ---------------------------------------------------------------------------------------------------------------
// Event effects (frame `haptic`, capability `hapticFx` 1). Append-only wire tokens; 0 = none.
enum CCFx : uint8_t {
    CC_HFX_NONE = 0, CC_HFX_TICK, CC_HFX_THUMP, CC_HFX_NUDGE_LEFT, CC_HFX_NUDGE_RIGHT, CC_HFX_REFUSE, CC_HFX_ERROR,
    CC_HFX_OFF, CC_HFX_COUNT,
    CC_HFX_DETENT = 0x40     // internal: a detent pulse of a pulsed token (never on the wire)
};
constexpr const char* CC_HFX_TOKENS[CC_HFX_COUNT] = {
    "", "confirm.tick", "confirm.thump", "nudge.left", "nudge.right", "refuse.buzz", "error.buzz", "confirm.off"};
inline const char* cc_fx_name(uint8_t fx) { return fx < CC_HFX_COUNT ? CC_HFX_TOKENS[fx] : ""; }
inline bool cc_fx_parse(const char* token, uint8_t& out) {
    if (!token || !*token) return false;
    for (uint8_t i = 1; i < CC_HFX_COUNT; ++i)
        if (!strcmp(token, CC_HFX_TOKENS[i])) { out = i; return true; }
    return false;
}

// The pulse (Karl's click: impact 4 ms + tail 20 ms @ 70 Hz at 1/6 of the impact). The impact is ONE FULL sine
// period in the 4 ms (+ then -, "phase-signed": the sign says which lobe leads, so a nudge leans its way), so its net
// impulse is zero: a free knob is not flung off its detent (haptic_fx_tests.cpp's model: a half-sine thump moved a
// resting 67-detent knob by a whole detent). The tail fades linearly to zero. Volts per unit amplitude; t in us.
constexpr uint32_t CC_HFX_IMPACT_US = 4000;
constexpr uint32_t CC_HFX_TAIL_US = 20000;
constexpr uint32_t CC_HFX_PULSE_US = CC_HFX_IMPACT_US + CC_HFX_TAIL_US;
inline float cc_fx_pulse_shape(uint32_t tUs) {
    if (tUs < CC_HFX_IMPACT_US) return sinf(2.0f * CC_HAPTIC_PI * static_cast<float>(tUs) / static_cast<float>(CC_HFX_IMPACT_US));
    if (tUs < CC_HFX_PULSE_US) {
        const float t = static_cast<float>(tUs - CC_HFX_IMPACT_US);
        return (1.0f / 6.0f) * sinf(2.0f * CC_HAPTIC_PI * 70.0f * t * 1e-6f) * (1.0f - t / static_cast<float>(CC_HFX_TAIL_US));
    }
    return 0.0f;
}

// One effect: up to three pulses (start offsets, % of the cap), a sign (+1 / -1; nudge left = -1) and its sound.
struct CCFxShape {
    uint8_t count;
    uint16_t atMs[3];
    uint8_t frac[3];
    int8_t sign;
    CCSoundCue sound;
};
inline CCFxShape cc_fx_make(uint8_t count, uint16_t a0, uint16_t a1, uint16_t a2, uint8_t frac, int8_t sign,
                            CCSoundCue sound) {
    CCFxShape s;
    s.count = count; s.atMs[0] = a0; s.atMs[1] = a1; s.atMs[2] = a2;
    s.frac[0] = s.frac[1] = s.frac[2] = frac; s.sign = sign; s.sound = sound;
    return s;
}
// r4 4.2 events with their reduced fallbacks, and the section 6 sounds (every sound follows its haptic: a reduced
// buzz is one pulse and one sound). confirm.off (Lights "All off", r4 4.4 "4 = off: 1 pulse"; 6 "lights off:
// BUTTON_THUMP at lower amplitude") is the one token added to the r4 list.
inline CCFxShape cc_fx_shape(uint8_t fx, bool reduced) {
    // Levels x 2 of r4 section 6 (2026-09-30; r4: 30 / 50 / 35 / 30, refuse 20, error 30): the thump is full scale.
    const CCSoundCue tick = {CC_SOUND_WOOD, 60, 1, 0}, thump = {CC_SOUND_THUMP, 100, 1, 0},
                     off = {CC_SOUND_THUMP, 70, 1, 0}, nudge = {CC_SOUND_THUD, 60, 1, 0};
    const CCSoundCue refuse = {CC_SOUND_WOOD, 40, static_cast<uint8_t>(reduced ? 1 : 3), 30};
    const CCSoundCue error = {CC_SOUND_THUD, 60, static_cast<uint8_t>(reduced ? 1 : 3), 70};
    switch (fx) {
        case CC_HFX_TICK: return cc_fx_make(1, 0, 0, 0, reduced ? 50 : 60, 1, tick);
        case CC_HFX_THUMP: return reduced ? cc_fx_make(1, 0, 0, 0, 60, 1, thump) : cc_fx_make(2, 0, 12, 0, 100, 1, thump);
        case CC_HFX_OFF: return cc_fx_make(1, 0, 0, 0, reduced ? 50 : 80, 1, off);
        case CC_HFX_NUDGE_LEFT: return cc_fx_make(1, 0, 0, 0, reduced ? 50 : 80, static_cast<int8_t>(reduced ? 1 : -1), nudge);
        case CC_HFX_NUDGE_RIGHT: return cc_fx_make(1, 0, 0, 0, reduced ? 50 : 80, 1, nudge);
        case CC_HFX_REFUSE: return reduced ? cc_fx_make(1, 0, 0, 0, 80, 1, refuse) : cc_fx_make(3, 0, 30, 60, 60, 1, refuse);
        case CC_HFX_ERROR: return reduced ? cc_fx_make(1, 0, 0, 0, 80, 1, error) : cc_fx_make(3, 0, 70, 140, 100, 1, error);
        default: return cc_fx_make(0, 0, 0, 0, 0, 1, CC_SOUND_SILENT);
    }
}

// FW-BUG-010: the detent grid's index of an angle (round((angle - origin) / w), as find_detent() places its
// attractors). Two attractors with the same index are the same detent, whatever their float rounding: an attractor
// stepped from another (end_freeze()) and one recomputed from the shaft may differ in the last bits.
inline long cc_detent_index(float angle, float origin, float width) {
    return lroundf((angle - origin) / width);
}
// The attractor of grid index `index` (the same arithmetic as find_detent(): index x width, then + origin).
inline float cc_detent_angle(long index, float origin, float width) {
    float a = static_cast<float>(index);
    a *= width;
    a += origin;
    return a;
}

// The player (FOC thread only). Plan F2: micros() timing, amplitude a fraction of the cap, the caller clamps
// spring + damping + effect to the cap, the detent position is frozen only when |velocity| is small at the start,
// no pulses while coasting, no re-fire inside an event's 4 ms impact (a host event cuts a detent pulse at any time),
// refuse.buzz at most once per second.
constexpr float CC_HFX_FREEZE_RAD_S = 2.0f;        // below this at the start: freeze the detent position
constexpr uint32_t CC_HFX_SETTLE_US = 60000;       // ... until the pulses end plus this settle
constexpr uint32_t CC_HFX_REFUSE_GAP_US = 1000000; // refuse.buzz: at most one per second
// FW-BUG-033: the end of an effect's freeze in a viscous feel (no well to pull the knob back): how far the detent grid
// moves with the knob, so the pulses' own displacement never counts as a turn. That is the shift less the hand's turn
// over the freeze, estimated from the speed at its start and at its end (the knob has settled by then: the pulses
// end CC_HFX_SETTLE_US earlier), and never more than CC_HFX_ABSORB_DETENTS of a detent (the largest displacement of
// any effect at rest is under 0.6 detent: error.buzz in fluid.light). The rest of the shift, the hand's turn, is
// counted (moving the grid by the whole shift lost the turn: a count per tick, 3-4 per error.buzz while turning
// Onshape orbit / pan or Seek at under 2 rad/s). 0 outside a viscous feel or at or above the freeze speed (the
// whole shift is counted then, as before).
constexpr float CC_HFX_ABSORB_DETENTS = 0.75f;
inline float cc_freeze_absorb(bool viscous, float startVelocity, float endVelocity, float elapsedS, float shift,
                              float width) {
    const float endSpeed = endVelocity < 0.0f ? -endVelocity : endVelocity;
    if (!viscous || endSpeed >= CC_HFX_FREEZE_RAD_S || width <= 0.0f) return 0.0f;
    const float pulses = shift - 0.5f * (startVelocity + endVelocity) * elapsedS;
    const float bound = CC_HFX_ABSORB_DETENTS * width;
    return pulses > bound ? bound : (pulses < -bound ? -bound : pulses);
}
struct CCFxCounters {
    uint32_t played;      // events started (not detent pulses)
    uint32_t pulses;      // detent pulses started
    uint32_t dropped;     // refused starts (coasting, impact, rate limit, detent under an event)
};
class CCFxPlayer {
public:
    CCFxPlayer() : active_(false), event_(false), freeze_(false), startUs_(0), endUs_(0), freezeEndUs_(0),
                   lastRefuseUs_(0), refused_(false) {
        shape_ = cc_fx_make(0, 0, 0, 0, 0, 1, CC_SOUND_SILENT);
        counters_.played = counters_.pulses = counters_.dropped = 0;
    }
    // An event (CCFx 1..) or a detent pulse (CC_HFX_DETENT with `detentSign` and `detentFrac`). Returns true and
    // fills `cue` (the sound to play with it) when the effect starts.
    bool start(uint8_t fx, bool reduced, uint32_t nowUs, float velocity, bool coasting, CCSoundCue& cue,
               int8_t detentSign = 1, uint8_t detentFrac = 0, CCSoundCue detentSound = CC_SOUND_SILENT) {
        cue = CC_SOUND_SILENT;
        const bool detent = fx == CC_HFX_DETENT;
        if (coasting || (detent && detentFrac == 0) || (!detent && (fx == CC_HFX_NONE || fx >= CC_HFX_COUNT))) {
            ++counters_.dropped;
            return false;
        }
        busy(nowUs);   // expire
        // 4 ms no re-fire inside an event's impact, or a detent pulse inside a detent pulse's. FW-DES-005: a host
        // event pre-empts a detent pulse at any time: it was taken from the cross-task word already (cc_fx_take /
        // CCFxIntake), so a refusal here lost the event and its sound (~8 % of events while turning a pulsed feel).
        if (active_ && (event_ || detent) && inImpact(nowUs)) { ++counters_.dropped; return false; }
        if (detent && active_ && event_) { ++counters_.dropped; return false; }  // an event is playing
        if (fx == CC_HFX_REFUSE && refused_ && static_cast<uint32_t>(nowUs - lastRefuseUs_) < CC_HFX_REFUSE_GAP_US) {
            ++counters_.dropped;
            return false;
        }
        if (detent) {
            shape_ = cc_fx_make(1, 0, 0, 0, detentFrac, detentSign >= 0 ? 1 : -1, detentSound);
            ++counters_.pulses;
        } else {
            shape_ = cc_fx_shape(fx, reduced);
            ++counters_.played;
            if (fx == CC_HFX_REFUSE) { refused_ = true; lastRefuseUs_ = nowUs; }
        }
        active_ = true; event_ = !detent; startUs_ = nowUs;
        const uint32_t lastAt = static_cast<uint32_t>(shape_.atMs[shape_.count ? shape_.count - 1 : 0]) * 1000u;
        endUs_ = nowUs + lastAt + CC_HFX_PULSE_US;
        const float speed = velocity < 0.0f ? -velocity : velocity;
        // FW-BUG-010: a detent pulse never freezes: it plays because a detent was just counted, so the knob is turning,
        // and on a slow turn (< 2 rad/s, 16-20 detents a second at 67 a turn) chained freezes held back the count,
        // dropped pulses and miscounted at their ends. Only an event that starts at rest freezes.
        freeze_ = !detent && speed < CC_HFX_FREEZE_RAD_S;
        freezeEndUs_ = endUs_ + CC_HFX_SETTLE_US;
        cue = shape_.sound;
        return true;
    }
    // The effect's voltage now (signed; 0 when idle). The caller adds it to the loop's output and clamps.
    float volts(uint32_t nowUs) {
        if (!busy(nowUs)) return 0.0f;
        const uint32_t t = nowUs - startUs_;
        float v = 0.0f;
        for (uint8_t i = 0; i < shape_.count; ++i) {
            const uint32_t at = static_cast<uint32_t>(shape_.atMs[i]) * 1000u;
            if (t >= at) v += cc_fx_pulse_shape(t - at) * (static_cast<float>(shape_.frac[i]) / 100.0f);
        }
        return v * CC_HAPTIC_CAP_VOLTS * static_cast<float>(shape_.sign);
    }
    // True while the detent position must stay frozen (an effect that started at rest, plus its settle).
    bool frozen(uint32_t nowUs) const {
        return freeze_ && static_cast<int32_t>(freezeEndUs_ - nowUs) > 0;
    }
    bool busy(uint32_t nowUs) {
        if (active_ && static_cast<int32_t>(endUs_ - nowUs) <= 0) active_ = false;
        return active_;
    }
    void cancel() { active_ = false; freeze_ = false; }
    const CCFxCounters& counters() const { return counters_; }

private:
    bool inImpact(uint32_t nowUs) const {
        const uint32_t t = nowUs - startUs_;
        for (uint8_t i = 0; i < shape_.count; ++i) {
            const uint32_t at = static_cast<uint32_t>(shape_.atMs[i]) * 1000u;
            if (t >= at && t < at + CC_HFX_IMPACT_US) return true;
        }
        return false;
    }
    bool active_, event_, freeze_;
    uint32_t startUs_, endUs_, freezeEndUs_, lastRefuseUs_;
    bool refused_;
    CCFxShape shape_;
    CCFxCounters counters_;
};

// ---------------------------------------------------------------------------------------------------------------
// Wall fold-back (plan F2): an I2t budget in V^2.s at the wall only. The energy integrates the APPLIED wall volts
// squared minus a cooling rate; over the budget the wall force ramps down to at least 50 %, below half the
// budget it recovers through a slew limit. At 50 % the applied (1.1 V)^2 equals the cooling rate, so a lean that
// continues holds there. Provisional numbers (HAPTICS.md: to be calibrated by the 3-minute wall-lean test).
constexpr float CC_FOLD_BUDGET_V2S = 100.0f;     // about 20 s at the full 2.2 V
constexpr float CC_FOLD_COOL_V2 = 1.21f;         // (1.1 V)^2 per second
constexpr float CC_FOLD_MIN = 0.5f;
constexpr float CC_FOLD_DOWN_PER_S = 1.0f;
constexpr float CC_FOLD_UP_PER_S = 0.25f;
class CCFoldback {
public:
    CCFoldback() : energy_(0.0f), factor_(1.0f), folding_(false), events_(0) {}
    // `appliedVolts`: the wall voltage actually commanded this pass (0 away from the wall); dt in seconds.
    void step(float appliedVolts, float dtS) {
        if (dtS <= 0.0f) return;
        if (dtS > 0.1f) dtS = 0.1f;
        energy_ += (appliedVolts * appliedVolts - CC_FOLD_COOL_V2) * dtS;
        if (energy_ < 0.0f) energy_ = 0.0f;
        if (energy_ > 2.0f * CC_FOLD_BUDGET_V2S) energy_ = 2.0f * CC_FOLD_BUDGET_V2S;
        if (!folding_ && energy_ >= CC_FOLD_BUDGET_V2S) { folding_ = true; ++events_; }
        else if (folding_ && energy_ <= 0.5f * CC_FOLD_BUDGET_V2S) folding_ = false;
        if (folding_) {
            factor_ -= CC_FOLD_DOWN_PER_S * dtS;
            if (factor_ < CC_FOLD_MIN) factor_ = CC_FOLD_MIN;
        } else {
            factor_ += CC_FOLD_UP_PER_S * dtS;
            if (factor_ > 1.0f) factor_ = 1.0f;
        }
    }
    float factor() const { return factor_; }
    float energy() const { return energy_; }
    bool folding() const { return folding_; }
    uint32_t events() const { return events_; }

private:
    float energy_, factor_;
    bool folding_;
    uint32_t events_;
};

// ---------------------------------------------------------------------------------------------------------------
// Self-spin trip (plan F2). Derived from the flipped-torque model in harness/haptic_fx_tests.cpp (HAPTICS.md
// "Self-spin trip"): with the torque sign flipped (a wrong calibration), a detent well turns unstable at its centre
// and stable at its midpoint (a buzz, not a spin), but a wall and a viscous feel drive the knob away for good: it
// runs to its back-EMF speed (tens of rad/s) or, in the legacy loop, oscillates around the 30 rad/s coasting speed.
// No hand spins the knob that fast for that long, so the trip is a leaky "fast for too long" timer: while |v| >=
// CC_TRIP_RAD_S the score rises at 1/s, otherwise it falls at 0.5/s; at CC_TRIP_SCORE_S it latches. The latch
// zeroes the motor output until the next claim or a key press; sleep / wake keeps it (foc_thread.cpp).
constexpr float CC_TRIP_RAD_S = 15.0f;
constexpr float CC_TRIP_SCORE_S = 2.0f;
constexpr float CC_TRIP_DECAY = 0.5f;
class CCSpinTrip {
public:
    CCSpinTrip() : score_(0.0f), latched_(false), trips_(0) {}
    // Returns true on the pass it latches.
    bool step(float velocity, float dtS) {
        if (latched_ || dtS <= 0.0f) return false;
        if (dtS > 0.1f) dtS = 0.1f;
        const float speed = velocity < 0.0f ? -velocity : velocity;
        score_ += speed >= CC_TRIP_RAD_S ? dtS : -CC_TRIP_DECAY * dtS;
        if (score_ < 0.0f) score_ = 0.0f;
        if (score_ >= CC_TRIP_SCORE_S) { latched_ = true; ++trips_; return true; }
        return false;
    }
    bool latched() const { return latched_; }
    void clear() { latched_ = false; score_ = 0.0f; }
    uint32_t trips() const { return trips_; }
    float score() const { return score_; }

private:
    float score_;
    bool latched_;
    uint32_t trips_;
};

// FW-BUG-046: the recalibration direction rule's trip term (foc_thread.cpp recalibrate()). A changed direction is
// accepted when the request says so (the user confirmed), when the trip is latched now, or when the knob tripped
// since the last successful calibration (the boot's, a recalibration's or the boot retry's). The lifetime count
// (trips() > 0) kept accepting after a trip a calibration had already answered: a later run with a finger on the
// knob that read the opposite direction was saved, and every boot after ran the walls / viscous feels away.
class CCCalTripGuard {
public:
    CCCalTripGuard() : tripsAtCal_(0) {}
    bool acceptDirection(bool requested, const CCSpinTrip& trip) const {
        return requested || trip.latched() || trip.trips() != tripsAtCal_;
    }
    // A calibration succeeded (and is in use): trips before it no longer speak against it, and FW-BUG-031 the trip
    // latch is cleared (a latch from the old calibration held the output at zero, detents and walls off, until a key
    // press, after a recalibration that answered ok). A failed run never calls this: the latch stays.
    void calibrated(CCSpinTrip& trip) { trip.clear(); tripsAtCal_ = trip.trips(); }

private:
    uint32_t tripsAtCal_;
};

// ---------------------------------------------------------------------------------------------------------------
// FW-BUG-032: the app canvas angle word (foc_thread.cpp cc_app_angle_read()), the knob's total turn in 1e-4 rad as a
// genuinely wrapping 32-bit count. It was int32(getAngle() * 1e4): past +-214748 rad (~34k turns) the float-to-int
// cast is undefined (it saturates on the ESP32, the canvas then saw no change and the cube stopped), and the float
// total itself loses resolution long before that. Here each pass adds the small turn since the last one, taken from
// the sensor's whole-turn count and in-turn angle (both exact), rounded to 1e-4 rad with the remainder carried, into
// an unsigned word that wraps modulo 2^32. Readers use differences only, in unsigned (wrapping) arithmetic.
constexpr float CC_ANGLE_WORD_PER_RAD = 10000.0f;
class CCAngleWord {
public:
    explicit CCAngleWord(uint32_t start = 0)
        : word_(start), lastTurns_(0), lastRad_(0.0f), residue_(0.0f), primed_(false) {}
    // One pass: the sensor's full rotations and its in-turn angle (rad). Returns the word as the int32 it publishes.
    int32_t step(int32_t fullRotations, float inTurnRad) {
        if (!primed_) { primed_ = true; lastTurns_ = fullRotations; lastRad_ = inTurnRad; return value(); }
        const int32_t turns = static_cast<int32_t>(static_cast<uint32_t>(fullRotations) - static_cast<uint32_t>(lastTurns_));
        const float units = (static_cast<float>(turns) * 2.0f * CC_HAPTIC_PI + (inTurnRad - lastRad_)) *
                            CC_ANGLE_WORD_PER_RAD + residue_;
        const float rounded = floorf(units + 0.5f);
        residue_ = units - rounded;
        word_ += static_cast<uint32_t>(static_cast<int32_t>(rounded));
        lastTurns_ = fullRotations;
        lastRad_ = inTurnRad;
        return value();
    }
    int32_t value() const { return static_cast<int32_t>(word_); }
    uint32_t word() const { return word_; }

private:
    uint32_t word_;
    int32_t lastTurns_;
    float lastRad_, residue_;
    bool primed_;
};

// ---------------------------------------------------------------------------------------------------------------
// Cross-task words (single writer each, plain aligned 32-bit stores; header-only like cc_wall.h).
namespace cc_haptic_detail {
struct Shared {
    volatile uint32_t fxWord;        // COM -> FOC: (seq << 8) | CCFx, one store (a newer post replaces an unplayed one)
    volatile uint32_t holdStartMs;   // HMI -> FOC: hold.tension start (millis) ...
    volatile uint32_t holdDurationMs;//  ... and its duration; 0 = none (cleared first while the pair changes)
    volatile uint32_t holdSeq;       // HMI: moves with every post (diag / tests)
    volatile uint32_t offlineWanted; // HMI -> FOC: 1 while the offline Consumer volume mode is wanted
    volatile int32_t offlineSteps;   // FOC -> HMI: volume steps (+ up / - down), a running count (HMI keeps its own)
    volatile uint32_t offlineMoves;  // FOC -> HMI: offline detents in either direction (wrapping; FW-BUG-042)
    volatile uint32_t calRequest;    // COM -> FOC: recalibration requests (a counter), bit 31 = accept a direction change
    volatile uint32_t calState;      // FOC -> COM: CCCalState
    volatile uint32_t calResult;     // FOC -> COM: a counter of finished runs
    volatile uint32_t calOutcome;    // FOC -> COM: CCCalOutcome of the last finished run
    volatile uint32_t calSave;       // COM <-> FOC save handshake (CCCalSave)
    volatile int32_t calDirection;   // FOC -> COM: the calibration to store (valid with CC_CAL_SAVE_READY)
    volatile float calZero;
};
inline Shared& shared() { static Shared s = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.0f}; return s; }
}  // namespace cc_haptic_detail

// COM task (a frame / control accepted with a new `haptic`): the effect to play next.
inline void cc_fx_post(uint8_t fx) {
    cc_haptic_detail::Shared& s = cc_haptic_detail::shared();
    const uint32_t seq = ((s.fxWord >> 8) + 1u) & 0xFFFFFFu;
    s.fxWord = (seq << 8) | fx;
}
// FOC task: a new effect since `seen` (updated), or CC_HFX_NONE.
inline uint8_t cc_fx_take(uint32_t& seen) {
    const uint32_t word = cc_haptic_detail::shared().fxWord;
    if (word == seen) return CC_HFX_NONE;
    seen = word;
    return static_cast<uint8_t>(word & 0xFFu);
}

// FW-BUG-007: the FOC task's effect intake. Desk Dial can arm a haptic and re-enter in the same step (a list source
// confirm.tick, the hold-1 Home thump): the COM task posts the effect with the new control, but until that control's
// ready line (cc_input_id() == the applied id, 53-355 ms measured) the FOC pass holds a zero output and never runs the
// haptic loop, the only caller of the effect's volts. Taken then, the pulse (24-164 ms) expired unfelt while its sound
// played. So a post is left in fxWord while the output is held for a re-entry (`defer`) and plays, with its sound, on
// the first ungated pass; a newer post replaces it (the newest wins, as before). One held longer than
// CC_FX_DEFER_MAX_MS (above the 355 ms worst re-entry) is dropped unplayed: no stale pulse long after the gesture.
// `discard` (no control claimed, the motor asleep, the self-spin latch) drops a post as before.
constexpr uint32_t CC_FX_DEFER_MAX_MS = 400;
class CCFxIntake {
public:
    explicit CCFxIntake(uint32_t seen) : seen_(seen), waitWord_(0), waitSinceMs_(0), waiting_(false) {}
    // One FOC pass at `nowMs`: the effect to play now, or CC_HFX_NONE.
    uint8_t step(uint32_t nowMs, bool discard, bool defer) {
        const uint32_t word = cc_haptic_detail::shared().fxWord;
        if (word == seen_) { waiting_ = false; return CC_HFX_NONE; }
        if (!waiting_ || word != waitWord_) { waiting_ = true; waitWord_ = word; waitSinceMs_ = nowMs; }
        if (discard || static_cast<uint32_t>(nowMs - waitSinceMs_) > CC_FX_DEFER_MAX_MS) {
            seen_ = word; waiting_ = false;
            return CC_HFX_NONE;
        }
        if (defer) return CC_HFX_NONE;
        seen_ = word; waiting_ = false;
        return static_cast<uint8_t>(word & 0xFFu);
    }
    bool waiting() const { return waiting_; }

private:
    uint32_t seen_, waitWord_, waitSinceMs_;
    bool waiting_;
};

// HMI task: hold.tension starts (button 1 or 4 held for its secondary action) or ends (duration 0).
inline void cc_hold_tension_post(uint32_t startMs, uint32_t durationMs) {
    cc_haptic_detail::Shared& s = cc_haptic_detail::shared();
    s.holdDurationMs = 0;              // readers see "none" while the pair changes
    s.holdStartMs = startMs;
    s.holdDurationMs = durationMs;
    s.holdSeq = s.holdSeq + 1u;
}
// FOC task: the hold.tension Kd now (0 = none).
inline float cc_hold_tension_kd(uint32_t nowMs) {
    const cc_haptic_detail::Shared& s = cc_haptic_detail::shared();
    const uint32_t duration = s.holdDurationMs;
    if (!duration) return 0.0f;
    const uint32_t start = s.holdStartMs;
    if (static_cast<int32_t>(nowMs - start) < 0) return cc_hold_kd(0, duration);
    return cc_hold_kd(nowMs - start, duration);
}
// hold.tension applies to (r4 4.4): button 1 (physical slot 0) held on a screen with a crumb (hold 1 = Home,
// 600 ms), button 4 (slot 3) held on a screen whose frame declares holdMarker (1000 ms); never on the app canvas.
constexpr uint32_t CC_HOLD1_MS = 600;
constexpr uint32_t CC_HOLD4_MS = 1000;
inline uint32_t cc_hold_tension_ms(uint8_t physicalSlot, bool crumb, bool holdMarker, bool appCanvas) {
    return appCanvas ? 0u : (physicalSlot == 0 && crumb ? CC_HOLD1_MS : (physicalSlot == 3 && holdMarker ? CC_HOLD4_MS : 0u));
}

// Offline system volume (plan F3), HMI <-> FOC.
inline void cc_offline_wanted_set(bool on) { cc_haptic_detail::shared().offlineWanted = on ? 1u : 0u; }
inline bool cc_offline_wanted() { return cc_haptic_detail::shared().offlineWanted != 0u; }
inline void cc_offline_step(int32_t delta) {
    cc_haptic_detail::Shared& s = cc_haptic_detail::shared();
    s.offlineSteps = s.offlineSteps + delta;
    s.offlineMoves = s.offlineMoves + static_cast<uint32_t>(delta < 0 ? -static_cast<int64_t>(delta) : delta);
}
inline int32_t cc_offline_steps() { return cc_haptic_detail::shared().offlineSteps; }
// FW-BUG-042 (hardening): a monotonic count of offline detents, |delta| summed. Unlike the signed cc_offline_steps(),
// a +1 and a -1 landing between two LCD samples still move it, so it reads as native motion.
inline uint32_t cc_offline_moves() { return cc_haptic_detail::shared().offlineMoves; }

// Recalibration (plan F2): states the FOC task reports, the outcome of a run and the save handshake.
enum CCCalState : uint8_t { CC_CAL_IDLE = 0, CC_CAL_RUNNING, CC_CAL_SAVING };
enum CCCalOutcome : uint8_t {
    CC_CAL_OK = 0, CC_CAL_FAIL_INIT, CC_CAL_FAIL_POLES, CC_CAL_FAIL_DIRECTION, CC_CAL_FAIL_SAVE, CC_CAL_FAIL_CLAIMED
};
constexpr const char* CC_CAL_OUTCOMES[6] = {"ok", "init-failed", "pole-check-failed", "direction-changed",
                                            "save-timeout", "claimed"};
enum CCCalSave : uint8_t { CC_CAL_SAVE_NONE = 0, CC_CAL_SAVE_READY, CC_CAL_SAVE_WRITING, CC_CAL_SAVE_DONE,
                           CC_CAL_SAVE_FAILED };
constexpr uint32_t CC_CAL_SAVE_TIMEOUT_MS = 1500;
constexpr uint32_t CC_CAL_ACCEPT_DIRECTION = 0x80000000u;
// FW-TST-010: the save handshake (foc_thread.cpp save_through_com(), cc_cal_take_save(), cc_cal_saved()) as one class
// on the shared words, every transition under the caller's lock (`Lock`: lock() / unlock(); the device's is a
// portMUX critical section), the clock injected. The FOC task offers the calibration and polls each pass while it
// holds a zero output; the COM task takes it (once per offer) and reports it saved. The FOC wait ends on SAVED, on
// CC_CAL_SAVE_TIMEOUT_MS with the offer not taken (the COM task can no longer take it), or on CC_CAL_WRITE_TIMEOUT_MS
// after the take with no saved(): a stalled or starved flash write no longer holds the knob at zero output forever
// (outcome save-timeout; a late saved() is ignored, the write itself may still land: it is a calibration that passed
// every check, and the next boot uses it). FW-BUG-028: the COM task reports the write's result; a refused or short
// NVS write (saved(false)) ends the wait at once as FAILED, treated like the timeout (outcome save-timeout, the old
// direction and zero restored: NVS still holds the previous calibration after a failed put).
constexpr uint32_t CC_CAL_WRITE_TIMEOUT_MS = 3000;
enum CCCalPoll : uint8_t { CC_CAL_POLL_WAIT = 0, CC_CAL_POLL_SAVED, CC_CAL_POLL_TIMEOUT, CC_CAL_POLL_FAILED };
template <typename Lock>
class CCCalHandshake {
public:
    explicit CCCalHandshake(Lock& lock) : lock_(lock), offeredMs_(0), takenMs_(0), takenSeen_(false) {}
    // FOC task: offer the calibration to store.
    void offer(int32_t direction, float zero, uint32_t nowMs) {
        cc_haptic_detail::Shared& s = cc_haptic_detail::shared();
        offeredMs_ = nowMs; takenSeen_ = false;
        lock_.lock();
        s.calDirection = direction;
        s.calZero = zero;
        s.calSave = CC_CAL_SAVE_READY;
        lock_.unlock();
    }
    // COM task: true once per offer, with the calibration to write.
    bool take(int32_t& direction, float& zero) {
        cc_haptic_detail::Shared& s = cc_haptic_detail::shared();
        bool taken = false;
        lock_.lock();
        if (s.calSave == CC_CAL_SAVE_READY) {
            s.calSave = CC_CAL_SAVE_WRITING;
            direction = s.calDirection;
            zero = s.calZero;
            taken = true;
        }
        lock_.unlock();
        return taken;
    }
    // COM task: the taken calibration's write result, ok when NVS holds it (ignored unless a take is outstanding).
    void saved(bool ok) {
        cc_haptic_detail::Shared& s = cc_haptic_detail::shared();
        lock_.lock();
        if (s.calSave == CC_CAL_SAVE_WRITING) s.calSave = ok ? CC_CAL_SAVE_DONE : CC_CAL_SAVE_FAILED;
        lock_.unlock();
    }
    // FOC task, each pass after offer(): WAIT, SAVED, FAILED or TIMEOUT; on any end the words are back to NONE.
    uint8_t poll(uint32_t nowMs) {
        cc_haptic_detail::Shared& s = cc_haptic_detail::shared();
        uint8_t result = CC_CAL_POLL_WAIT;
        lock_.lock();
        const uint32_t save = s.calSave;
        if (save == CC_CAL_SAVE_DONE) {
            result = CC_CAL_POLL_SAVED;
        } else if (save == CC_CAL_SAVE_FAILED) {
            result = CC_CAL_POLL_FAILED;
        } else if (save == CC_CAL_SAVE_READY) {
            if (static_cast<uint32_t>(nowMs - offeredMs_) >= CC_CAL_SAVE_TIMEOUT_MS) result = CC_CAL_POLL_TIMEOUT;
        } else if (save == CC_CAL_SAVE_WRITING) {
            if (!takenSeen_) { takenSeen_ = true; takenMs_ = nowMs; }
            if (static_cast<uint32_t>(nowMs - takenMs_) >= CC_CAL_WRITE_TIMEOUT_MS) result = CC_CAL_POLL_TIMEOUT;
        } else {
            result = CC_CAL_POLL_TIMEOUT;   // nothing offered
        }
        if (result != CC_CAL_POLL_WAIT) s.calSave = CC_CAL_SAVE_NONE;
        lock_.unlock();
        return result;
    }

private:
    Lock& lock_;
    uint32_t offeredMs_, takenMs_;
    bool takenSeen_;
};
// COM task ({"recalibrate":...}, or the legacy {"R":"129=1"}): ask the FOC task for one run.
inline void cc_cal_request(bool acceptDirection) {
    cc_haptic_detail::Shared& s = cc_haptic_detail::shared();
    const uint32_t count = ((s.calRequest & ~CC_CAL_ACCEPT_DIRECTION) + 1u) & ~CC_CAL_ACCEPT_DIRECTION;
    s.calRequest = count | (acceptDirection ? CC_CAL_ACCEPT_DIRECTION : 0u);
}
inline const char* cc_cal_outcome_name(uint32_t outcome) { return outcome < 6u ? CC_CAL_OUTCOMES[outcome] : "?"; }
inline const char* cc_cal_state_name(uint32_t state) {
    return state == CC_CAL_RUNNING ? "running" : (state == CC_CAL_SAVING ? "saving" : "idle");
}
// The pole-pair check: one electrical turn open-loop must move the shaft 2 pi / pole pairs, within 25 %.
inline bool cc_cal_pole_check(float movedRad, int polePairs) {
    if (polePairs <= 0) return false;
    const float expected = 2.0f * CC_HAPTIC_PI / static_cast<float>(polePairs);
    const float moved = movedRad < 0.0f ? -movedRad : movedRad;
    return moved >= expected * 0.75f && moved <= expected * 1.25f;
}

// Register writes ({"R":"<reg>=<value>"}, HapticCommander; FW-BUG-003): an allow-list. Only the voltage limit
// (REG_VOLTAGE_LIMIT 0x50, which HapticCommander only ever lowers into the 2.2 V cap) and the recalibration request
// (REG_RECALIBRATE 0x81, routed to the FOC task) can be written. Every other write (the control / torque mode, the
// PID limits, the phase resistance, the modulation, the supply, raw phase voltages, ...) is answered with the
// unchanged value: changing any of them could put a voltage on the windings that no longer goes through the cap or
// through the haptic loop's zero paths (rest sleep, the trip latch, the recalibration hold). Reads stay open.
constexpr uint8_t CC_REG_VOLTAGE_LIMIT = 0x50;
constexpr uint8_t CC_REG_RECALIBRATE = 0x81;
constexpr bool haptic_register_write_allowed(uint8_t reg) {
    return reg == CC_REG_VOLTAGE_LIMIT || reg == CC_REG_RECALIBRATE;
}
static_assert(haptic_register_write_allowed(0x50) && haptic_register_write_allowed(0x81) &&
              !haptic_register_write_allowed(0x05) && !haptic_register_write_allowed(0x06) &&
              !haptic_register_write_allowed(0x16) && !haptic_register_write_allowed(0x33) &&
              !haptic_register_write_allowed(0x39) && !haptic_register_write_allowed(0x53) &&
              !haptic_register_write_allowed(0x55) && !haptic_register_write_allowed(0x56) &&
              !haptic_register_write_allowed(0x60) && !haptic_register_write_allowed(0x61) &&
              !haptic_register_write_allowed(0x63) && !haptic_register_write_allowed(0x64),
              "cc_haptic_fx: the register write allow-list");

// FW-BUG-035: the numbers of a {"R":"<reg>[=<value>]"} command are range-checked, never truncated. atoi() into a
// uint8_t aliased 385 (and -127) to 129 = REG_RECALIBRATE and 336 to 0x50; a value of 257 read as 1 and started a
// motor-moving recalibration. cc_parse_ranged(): a decimal integer (leading blanks and a sign allowed) in [lo, hi];
// false for no digits, overflow or out of range (`out` untouched); `end` is where the number stopped.
inline bool cc_parse_ranged(const char* s, long long lo, long long hi, long long& out, const char*& end) {
    end = s;
    if (s == nullptr) return false;
    char* stop = nullptr;
    errno = 0;
    const long long v = strtoll(s, &stop, 10);
    if (stop == s || errno == ERANGE || v < lo || v > hi) return false;
    end = stop;
    out = v;
    return true;
}
enum CCRegCheck : uint8_t { CC_REG_CMD_OK = 0, CC_REG_CMD_BAD_REGISTER, CC_REG_CMD_BAD_VALUE };
// The command as a whole: the register 0..255 followed by '=' or the end; the recalibration value 0 or 1. Anything
// else is refused before any dispatch (HapticCommander replies {"error":...}).
inline uint8_t cc_reg_command_check(const char* cmd, uint8_t& reg) {
    long long n = 0;
    const char* end = cmd;
    if (!cc_parse_ranged(cmd, 0, 255, n, end) || (*end != '=' && *end != '\0')) return CC_REG_CMD_BAD_REGISTER;
    reg = static_cast<uint8_t>(n);
    if (*end == '=' && reg == CC_REG_RECALIBRATE) {
        long long v = 0;
        const char* vend = end + 1;
        if (!cc_parse_ranged(end + 1, 0, 1, v, vend) || *vend != '\0') return CC_REG_CMD_BAD_VALUE;
    }
    return CC_REG_CMD_OK;
}

// The supply the driver scales its duty with (plan F2). The STSPIN233 runs from VBUS, so the duty is U / supply and
// the motor sees U x VBUS / supply: a supply assumed LOWER than VBUS over-drives every commanded voltage, the 2.2 V
// cap included (FW-BUG-022: unknown -> 5 V gave 1.8x at 9 V and 3-4x at 15-20 V). So it fails safe HIGH:
//   * the RDO read worked and there is no explicit contract (object position 0: a plain PC / Type-C port) -> 5 V;
//   * the read worked and the contract's voltage is known (5..20 V, the sink PDO at its position) -> that voltage;
//   * the read failed, or the position is outside the sink table (voltage unknown) -> the highest sink PDO
//     init_pd() programs (9 V). Safe only because init_pd() leaves the NVM alone only when the sink table is
//     5/9/9 V (it checks the PDO voltages, not only the count: plan F8); any other table is rewritten this boot;
//   * the sink PDOs were (re)written to NVM this boot and the read failed or found a contract (position != 0):
//     that contract was negotiated against the OLD table, which holds until a power cycle (the factory table
//     reaches 20 V) -> 20 V, the highest PD fixed supply;
//   * a read that worked with no contract (position 0) is 5 V whatever the NVM holds: without an explicit
//     contract VBUS is the USB default, so the first boot of a new knob on a PC port keeps the full feel and its
//     alignment runs at full field (FW-BUG-022 review).
// `contractVolts`: the sink PDO's voltage at the position, in whole volts (0 = unknown).
constexpr float CC_SUPPLY_USB_VOLTS = 5.0f;        // no contract: USB default
constexpr float CC_SUPPLY_SINK_MAX_VOLTS = 9.0f;   // the highest sink PDO init_pd() programs
constexpr float CC_SUPPLY_PD_MAX_VOLTS = 20.0f;    // the highest USB PD fixed supply
inline float cc_supply_volts(bool readOk, uint32_t position, uint32_t contractVolts, bool nvmRewritten) {
    return (readOk && position == 0u) ? CC_SUPPLY_USB_VOLTS
         : nvmRewritten ? CC_SUPPLY_PD_MAX_VOLTS
         : !readOk ? CC_SUPPLY_SINK_MAX_VOLTS
         : (contractVolts >= 5u && contractVolts <= 20u) ? static_cast<float>(contractVolts)
         : CC_SUPPLY_SINK_MAX_VOLTS;
}
// True when cc_supply_volts() had to assume the supply (no readable contract voltage): diag supplyAssumed.
inline bool cc_supply_assumed(bool readOk, uint32_t position, uint32_t contractVolts, bool nvmRewritten) {
    if (readOk && position == 0u) return false;
    return nvmRewritten || !readOk || !(contractVolts >= 5u && contractVolts <= 20u);
}

// FW-TST-008: bounds_handler()'s recovery loop (a knob leaving an end stop while still spinning) gives up after this
// long, so continuous movement at a bound never starves the FOC task's other work (requests, the rest gate, the
// lease). Pinned by harness/haptic_fx_tests.py.
constexpr unsigned long CC_BOUNDS_RECOVERY_US = 2000;

// uint16 detent ranges (the 1.0.0-cc5.6 wrap fix): the position count of [start, end] in 32 bits, and a VERNIER
// position scaled into uint16 without wrapping (clamped at 65535).
inline uint32_t cc_positions(uint16_t start, uint16_t end) {
    return end >= start ? static_cast<uint32_t>(end) - static_cast<uint32_t>(start) + 1u : 1u;
}
inline uint16_t cc_scaled_position(uint16_t pos, uint16_t scale) {
    const uint32_t v = static_cast<uint32_t>(pos) * static_cast<uint32_t>(scale ? scale : 1u);
    return static_cast<uint16_t>(v > 65535u ? 65535u : v);
}
