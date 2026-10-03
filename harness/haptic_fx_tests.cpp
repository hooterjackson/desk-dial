// r4 FEEL + SOUND (1.0.0-cc5.7, plan F2 / F3): host checks of the unchanged firmware headers src/cc_haptic_fx.h and
// src/audio/cc_sound.h, and of the frame parser's `haptic` object (src/cc_frame_parse.cpp). haptic_fx_tests.py builds
// this with MSVC /W4 /WX and runs it with the parity cases it writes (argv[1]).
//
//   1. the token table (r4 4.2 translated; the ratios kept: brightness heavier than volume, coarse > list > value >
//      fine), the reduced fallbacks, the parse / name round trip;
//   2. the laws (SAW, SINE with SAW's peak, VISCOSE), the wall (continuous, 1x -> 3x the centre stiffness, capped,
//      folded), damping, feel.fade, hold.tension's four stages;
//   3. the effect player: pulse shapes and timing (thump 2 pulses 12 ms apart, refuse 3 x 30 ms at most once a
//      second, error 3 x 70 ms), the 4 ms no re-fire, no pulses while coasting, freeze only at low speed, the
//      reduced fallbacks, and the sounds each effect asks for;
//   4. a knob model (rigid rotor, the FOC loop's detent counting as haptic.cpp does it): an effect never creates or
//      loses a detent at rest or during a constant-speed turn;
//   5. the wall fold-back (I2t) and the self-spin trip against the flipped-torque model (where the thresholds come
//      from) and ordinary hand motion (no false trip);
//   6. the uint16 range fix; the cross-task words (effect post / take, hold.tension, recalibration requests);
//   7. the click bank, the master level, the request ring (newest wins), the voice (cut and restart after 4 ms,
//      repeats), the underrun rule;
//   8. the `haptic` frame object: the parity cases (accept, token, seq) that device.py haptic_parse() also reads.
#include <ArduinoJson.h>

#include "cc_frame_parse.h"
#include "cc_haptic_fx.h"
#include "cc_boot_cal.h"
#include "cc_sleep.h"
#include "haptic_bounds.h"
#include "audio/cc_sound.h"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <atomic>
#include <mutex>
#include <thread>
#include <vector>

namespace {
int failures = 0, checks = 0;
void expect(bool ok, const char* what, int line) {
    ++checks;
    if (!ok) {
        ++failures;
        std::printf("FAIL line %d: %s\n", line, what);
    }
}
#define EXPECT(cond) expect((cond), #cond, __LINE__)
bool near(double a, double b, double tol) { return std::fabs(a - b) <= tol; }

// ---------------------------------------------------------------------------------------------------------- 1
void token_tests() {
    for (uint8_t i = 1; i < CC_FEEL_COUNT; ++i) {
        uint8_t back = 0;
        EXPECT(cc_feel_parse(cc_feel_name(i), back) && back == i);
    }
    uint8_t out = 99;
    EXPECT(!cc_feel_parse("", out) && !cc_feel_parse("wall.bounce", out) && !cc_feel_parse("feel.fade", out) &&
           !cc_feel_parse("detent.List", out) && !cc_feel_parse(nullptr, out) && out == 99);
    const CCFeelParams value = cc_feel_params(CC_FEEL_VALUE, false), dimmer = cc_feel_params(CC_FEEL_DIMMER, false),
                       list = cc_feel_params(CC_FEEL_LIST, false), coarse = cc_feel_params(CC_FEEL_COARSE, false),
                       fine = cc_feel_params(CC_FEEL_FINE, false), scrub = cc_feel_params(CC_FEEL_SCRUB, false),
                       light = cc_feel_params(CC_FEEL_LIGHT, false), spin = cc_feel_params(CC_FEEL_FREE_SPIN, false),
                       legacy = cc_feel_params(CC_FEEL_LEGACY, false);
    // Volume keeps today's strength (Kp 3 = the legacy P) and density (the profile's: 0).
    // 2026-09-30 (every interaction has a sound and a haptic): a light pulse and a softer tock on every volume detent.
    EXPECT(value.law == CC_LAW_SINE && value.detents == 0 && value.kp == legacy.kp && value.pulse == 15 &&
           value.sound.sound == CC_SOUND_WOOD && value.sound.level == 45 && value.coast);
    // Brightness is heavier than volume (r4 9: Kd 0.04 vs 0.01), same well.
    EXPECT(dimmer.law == CC_LAW_SINE && dimmer.kp == value.kp && near(dimmer.kd, 4.0 * value.kd, 1e-6));
    // Lists click, coarse is a rotary switch, fine clicks lighter and higher.
    EXPECT(list.law == CC_LAW_SAW && list.detents == 20 && list.pulse > 0 && list.sound.sound == CC_SOUND_WOOD &&
           list.sound.level == 60 && !list.coast);
    EXPECT(coarse.law == CC_LAW_SAW && coarse.detents == 12 && coarse.kp > list.kp && coarse.sound.sound == CC_SOUND_THUD &&
           coarse.sound.level == 70);
    EXPECT(fine.law == CC_LAW_SAW && fine.detents == 36 && fine.kp < value.kp && fine.sound.sound == CC_SOUND_FINE &&
           fine.sound.level == 40);
    EXPECT(near(list.kp / value.kp, 6.0 / 3.0, 1e-6) && near(coarse.kp / value.kp, 11.0 / 3.0, 1e-6) &&
           near(fine.kp / value.kp, 2.5 / 3.0, 1e-6));
    // Brightness ticks a little heavier than volume; the fluid feels click quietly with no pulse; fluids have no well.
    EXPECT(dimmer.pulse == 20 && dimmer.sound.sound == CC_SOUND_WOOD && dimmer.sound.level == 50 && dimmer.pulse > value.pulse);
    EXPECT(scrub.pulse == 0 && scrub.sound.sound == CC_SOUND_FINE && scrub.sound.level == 30 && light.pulse == 0 &&
           light.sound.sound == CC_SOUND_FINE);
    // Reduced haptics keeps them silent (the r4 section 7 fallbacks).
    EXPECT(cc_feel_params(CC_FEEL_VALUE, true).sound.sound == CC_SOUND_NONE &&
           cc_feel_params(CC_FEEL_SCRUB, true).sound.sound == CC_SOUND_NONE);
    EXPECT(scrub.law == CC_LAW_VISCOSE && scrub.kp == 0.0f && near(scrub.kd, 0.08, 1e-6) && light.law == CC_LAW_VISCOSE &&
           near(light.kd, 0.02, 1e-6));
    // free.spin is the list feel with coasting.
    EXPECT(spin.law == list.law && spin.detents == list.detents && spin.coast && spin.pulse == list.pulse);
    // Reduced haptics (r4 4.2 / 7): pulses -> soft steps, no coasting, silent detents; values go viscous.
    const CCFeelParams rv = cc_feel_params(CC_FEEL_VALUE, true), rd = cc_feel_params(CC_FEEL_DIMMER, true),
                       rl = cc_feel_params(CC_FEEL_LIST, true), rc = cc_feel_params(CC_FEEL_COARSE, true),
                       rf = cc_feel_params(CC_FEEL_FINE, true), rs = cc_feel_params(CC_FEEL_FREE_SPIN, true);
    EXPECT(rv.law == CC_LAW_VISCOSE && near(rv.kd, 0.02, 1e-6) && rd.law == CC_LAW_VISCOSE && near(rd.kd, 0.05, 1e-6));
    EXPECT(rl.law == CC_LAW_SINE && rl.pulse == 0 && rl.sound.sound == CC_SOUND_NONE && !rl.coast);
    EXPECT(rc.law == CC_LAW_SINE && near(rc.kp, 6.0, 1e-6) && rc.pulse == 0 && rf.law == CC_LAW_SINE && rf.pulse == 0);
    EXPECT(!rs.coast && rs.pulse == 0);
    for (uint8_t fx = 1; fx < CC_HFX_COUNT; ++fx) {
        uint8_t back = 0;
        EXPECT(cc_fx_parse(cc_fx_name(fx), back) && back == fx);
    }
    EXPECT(!cc_fx_parse("confirm", out) && !cc_fx_parse("", out) && !cc_fx_parse("nudge", out));
}

// ---------------------------------------------------------------------------------------------------------- 2
void law_tests() {
    const float w = 0.3f;
    EXPECT(near(cc_law_spring(CC_LAW_SAW, 3.0f, 0.05f, w), 0.15, 1e-6));
    EXPECT(near(cc_law_spring(CC_LAW_SAW, 3.0f, -0.05f, w), -0.15, 1e-6));
    EXPECT(near(cc_law_spring(CC_LAW_SAW, 11.0f, 0.1f, w), CC_HAPTIC_SPRING_AMPS, 1e-6));   // limited like the PID
    // SINE: SAW's peak (kp w / 2) at a quarter pitch, zero at the centre and the midpoint.
    const float peak = 1.0f * w * 0.5f;
    EXPECT(near(cc_law_spring(CC_LAW_SINE, 1.0f, w / 4.0f, w), peak, 1e-5));
    EXPECT(near(cc_law_spring(CC_LAW_SINE, 1.0f, 0.0f, w), 0.0, 1e-6) && near(cc_law_spring(CC_LAW_SINE, 1.0f, w / 2.0f, w), 0.0, 1e-5));
    EXPECT(near(cc_law_spring(CC_LAW_SAW, 1.0f, w / 2.0f, w), peak, 1e-6));
    EXPECT(cc_law_spring(CC_LAW_VISCOSE, 3.0f, 0.1f, w) == 0.0f);
    EXPECT(near(cc_law_slope(CC_LAW_SINE, 2.0f), 2.0 * 3.14159265, 1e-4) && cc_law_slope(CC_LAW_SAW, 2.0f) == 2.0f);
    // The wall: 0 at the centre, continuous with the well's centre stiffness, 3x one pitch out, capped, monotonic.
    const float k = 3.0f;
    EXPECT(cc_wall_volts(k, 0.0f, w, 2.2f) == 0.0f && cc_wall_volts(k, -0.1f, w, 2.2f) == 0.0f);
    const float tiny = 1e-4f;
    EXPECT(near(cc_wall_volts(k, tiny, w, 2.2f) / tiny, k * CC_HAPTIC_PHASE_OHMS, 0.05));
    EXPECT(near(cc_wall_volts(0.5f, w, w, 100.0f), 3.0 * 0.5 * CC_HAPTIC_PHASE_OHMS * w, 1e-4));
    EXPECT(cc_wall_volts(k, 1.0f, w, 2.2f) == 2.2f && cc_wall_volts(k, 1.0f, w, 1.1f) == 1.1f);
    float last = 0.0f;
    bool monotonic = true;
    for (int i = 1; i <= 400; ++i) {
        const float v = cc_wall_volts(0.3f, static_cast<float>(i) * 0.002f, w, 2.2f);
        if (v < last) monotonic = false;
        last = v;
    }
    EXPECT(monotonic);
    EXPECT(cc_wall_volts(0.0f, 0.01f, w, 2.2f) > 0.0f);   // a viscous feel still walls
    // Damping: opposes the motion, zero inside the noise deadband.
    EXPECT(cc_damping(0.02f, 0.3f) == 0.0f && cc_damping(0.02f, -0.4f) == 0.0f && cc_damping(0.0f, 10.0f) == 0.0f);
    EXPECT(near(cc_damping(0.02f, 10.8f), -0.2, 1e-6) && near(cc_damping(0.02f, -10.8f), 0.2, 1e-6) &&
           cc_damping(0.02f, 0.75f) == 0.0f);
    // feel.fade: 0 -> 1 over the fade, 1 without one.
    EXPECT(cc_fade_factor(0, 120) == 0.0f && near(cc_fade_factor(60000, 120), 0.5, 1e-6) && cc_fade_factor(120000, 120) == 1.0f &&
           cc_fade_factor(5, 0) == 1.0f && CC_FEEL_FADE_MS == 120 && CC_FEEL_WAKE_FADE_MS == 150);
    // hold.tension: four stages from 0.0375 to 0.12 over the hold, none at maturity (the landing) or without one.
    EXPECT(near(cc_hold_kd(0, 1000), 0.0375, 1e-6) && near(cc_hold_kd(249, 1000), 0.0375, 1e-6) &&
           near(cc_hold_kd(250, 1000), 0.065, 1e-6) && near(cc_hold_kd(500, 1000), 0.0925, 1e-6) &&
           near(cc_hold_kd(999, 1000), 0.12, 1e-6) && cc_hold_kd(1000, 1000) == 0.0f && cc_hold_kd(10, 0) == 0.0f);
    int stages = 0;
    float prev = -1.0f;
    for (uint32_t t = 0; t < 600; ++t) {
        const float kd = cc_hold_kd(t, 600);
        if (kd != prev) { ++stages; prev = kd; }
    }
    EXPECT(stages == 4);   // r4 open question 1: four steps, never a per-tick ramp
    EXPECT(cc_hold_tension_ms(0, true, false, false) == 600 && cc_hold_tension_ms(0, false, true, false) == 0 &&
           cc_hold_tension_ms(3, false, true, false) == 1000 && cc_hold_tension_ms(3, true, false, false) == 0 &&
           cc_hold_tension_ms(1, true, true, false) == 0 && cc_hold_tension_ms(0, true, true, true) == 0);
}

// ---------------------------------------------------------------------------------------------------------- 3
// Impacts seen in a volts() trace: rises of sign x volts above 0.6 V (an impact's leading lobe; a tail stays below
// 0.37 V). `peak` gets the largest |volts|.
int pulse_count(CCFxPlayer& p, uint32_t start, uint32_t ms, float* peak = nullptr, float sign = 1.0f) {
    int count = 0;
    bool in = false;
    float top = 0.0f;
    for (uint32_t t = 0; t < ms * 1000u; t += 50) {
        const float v = p.volts(start + t);
        if (std::fabs(v) > top) top = std::fabs(v);
        const bool impact = sign * v > 0.6f;
        if (impact && !in) ++count;
        in = impact;
    }
    if (peak) *peak = top;
    return count;
}

void effect_tests() {
    // The pulse: one full sine period in 4 ms (+1 at 1 ms, -1 at 3 ms, zero net impulse), a small tail to 24 ms.
    EXPECT(near(cc_fx_pulse_shape(1000), 1.0, 1e-3) && near(cc_fx_pulse_shape(3000), -1.0, 1e-3) &&
           near(cc_fx_pulse_shape(0), 0.0, 1e-6) && std::fabs(cc_fx_pulse_shape(2000)) < 0.01f &&
           std::fabs(cc_fx_pulse_shape(3999)) < 0.01f && cc_fx_pulse_shape(24000) == 0.0f);
    double impulse = 0.0;
    for (uint32_t t = 0; t < CC_HFX_IMPACT_US; t += 10) impulse += cc_fx_pulse_shape(t) * 10e-6;
    EXPECT(std::fabs(impulse) < 1e-5);
    float tail = 0.0f;
    for (uint32_t t = 4000; t < 24000; t += 10) tail = std::fmax(tail, std::fabs(cc_fx_pulse_shape(t)));
    EXPECT(tail > 0.1f && tail <= 1.0f / 6.0f + 1e-4f);
    CCSoundCue cue;
    {
        CCFxPlayer p;
        float peak = 0.0f;
        EXPECT(p.start(CC_HFX_TICK, false, 1000, 0.0f, false, cue) && cue.sound == CC_SOUND_WOOD && cue.level == 60 && cue.repeats == 1);
        EXPECT(pulse_count(p, 1000, 60, &peak) == 1 && near(peak, 0.6 * CC_HAPTIC_CAP_VOLTS, 0.02));
    }
    {   // thump: two full pulses 12 ms apart, the thump at 100 % (the loudest sound: full scale at soundVolume 100).
        CCFxPlayer p;
        EXPECT(p.start(CC_HFX_THUMP, false, 0, 0.0f, false, cue) && cue.sound == CC_SOUND_THUMP && cue.level == 100);
        EXPECT(std::fabs(p.volts(1000)) > 2.0f && std::fabs(p.volts(13000)) > 2.0f);
        EXPECT(pulse_count(p, 0, 80) == 2);
    }
    {   // refuse: three pulses 30 ms apart at 60 %, three wood tocks 30 ms apart at 40 %; at most once a second.
        CCFxPlayer p;
        float peak = 0.0f;
        EXPECT(p.start(CC_HFX_REFUSE, false, 0, 0.0f, false, cue) && cue.sound == CC_SOUND_WOOD && cue.level == 40 &&
               cue.repeats == 3 && cue.gapMs == 30);
        EXPECT(pulse_count(p, 0, 120, &peak) == 3 && near(peak, 0.6 * CC_HAPTIC_CAP_VOLTS, 0.05));
        EXPECT(!p.start(CC_HFX_REFUSE, false, 500000, 0.0f, false, cue));
        EXPECT(p.start(CC_HFX_REFUSE, false, 1000001, 0.0f, false, cue));
    }
    {   // error: three full pulses 70 ms apart, three tick-thuds 70 ms apart at 60 %.
        CCFxPlayer p;
        EXPECT(p.start(CC_HFX_ERROR, false, 0, 0.0f, false, cue) && cue.sound == CC_SOUND_THUD && cue.repeats == 3 && cue.gapMs == 70);
        EXPECT(std::fabs(p.volts(141000)) > 2.0f);
        CCFxPlayer q;
        q.start(CC_HFX_ERROR, false, 0, 0.0f, false, cue);
        EXPECT(pulse_count(q, 0, 200) == 3);
    }
    {   // nudges are signed, confirm.off is one softer pulse with the lower thump.
        CCFxPlayer l, r, o;
        EXPECT(l.start(CC_HFX_NUDGE_LEFT, false, 0, 0.0f, false, cue) && cue.sound == CC_SOUND_THUD && l.volts(1000) < -1.0f);
        EXPECT(r.start(CC_HFX_NUDGE_RIGHT, false, 0, 0.0f, false, cue) && r.volts(1000) > 1.0f);
        EXPECT(o.start(CC_HFX_OFF, false, 0, 0.0f, false, cue) && cue.sound == CC_SOUND_THUMP && cue.level == 70 &&
               pulse_count(o, 0, 60) == 1);
    }
    {   // Reduced haptics: thump -> one pulse, buzzes -> one nudge (and one sound), nudge unsigned, tick 50 %.
        CCFxPlayer a, b, c, d, e;
        float peak = 0.0f;
        EXPECT(a.start(CC_HFX_THUMP, true, 0, 0.0f, false, cue) && pulse_count(a, 0, 80) == 1);
        EXPECT(b.start(CC_HFX_REFUSE, true, 0, 0.0f, false, cue) && pulse_count(b, 0, 120) == 1 && cue.repeats == 1);
        EXPECT(c.start(CC_HFX_ERROR, true, 0, 0.0f, false, cue) && pulse_count(c, 0, 200) == 1 && cue.repeats == 1);
        EXPECT(d.start(CC_HFX_NUDGE_LEFT, true, 0, 0.0f, false, cue) && d.volts(1000) > 0.0f);
        EXPECT(e.start(CC_HFX_TICK, true, 0, 0.0f, false, cue) && pulse_count(e, 0, 60, &peak) == 1 &&
               near(peak, 0.5 * CC_HAPTIC_CAP_VOLTS, 0.02));
    }
    {   // No re-fire inside a pulse's 4 ms impact; a cut after it; a detent pulse never cuts an event.
        CCFxPlayer p;
        EXPECT(p.start(CC_HFX_TICK, false, 0, 0.0f, false, cue));
        EXPECT(!p.start(CC_HFX_THUMP, false, 3000, 0.0f, false, cue));
        EXPECT(!p.start(CC_HFX_DETENT, false, 5000, 0.0f, false, cue, 1, 35));
        EXPECT(p.start(CC_HFX_THUMP, false, 5000, 0.0f, false, cue));
        EXPECT(p.counters().played == 2 && p.counters().dropped == 2);
    }
    {   // FW-DES-005: a host event during a detent pulse's 4 ms impact still plays, with its sound (it was taken from
        // the cross-task word already: a refusal lost it). A detent pulse still never re-fires inside a detent impact.
        CCFxPlayer p;
        const CCSoundCue tock = cc_feel_params(CC_FEEL_VALUE, false).sound;
        EXPECT(p.start(CC_HFX_DETENT, false, 0, 3.0f, false, cue, 1, 15, tock) && cue.sound == CC_SOUND_WOOD);
        EXPECT(!p.start(CC_HFX_DETENT, false, 1000, 3.0f, false, cue, 1, 15, tock));
        EXPECT(p.start(CC_HFX_THUMP, false, 2000, 3.0f, false, cue) && cue.sound == CC_SOUND_THUMP && cue.level == 100);
        EXPECT(pulse_count(p, 2000, 80) == 2 && p.counters().played == 1 && p.counters().pulses == 1 &&
               p.counters().dropped == 1);
        CCFxPlayer q;   // every event token, at every point of a detent impact (2 s apart: refuse's 1 s rate limit)
        uint32_t base = 2000000u;
        for (uint8_t fx = CC_HFX_TICK; fx < CC_HFX_COUNT; ++fx)
            for (uint32_t at = 0; at < CC_HFX_IMPACT_US; at += 500, base += 2000000u) {
                EXPECT(q.start(CC_HFX_DETENT, false, base, 3.0f, false, cue, 1, 20, tock));
                EXPECT(q.start(fx, false, base + at, 3.0f, false, cue) && cue.sound != CC_SOUND_NONE);
            }
        EXPECT(q.counters().dropped == 0);
    }
    {   // Coasting: nothing starts. Freeze: only from rest; a turn plays without one.
        CCFxPlayer p;
        EXPECT(!p.start(CC_HFX_TICK, false, 0, 40.0f, true, cue) && cue.sound == CC_SOUND_NONE);
        EXPECT(!p.start(CC_HFX_DETENT, false, 0, 40.0f, true, cue, 1, 35));
        EXPECT(p.start(CC_HFX_TICK, false, 0, 0.5f, false, cue) && p.frozen(1000) && p.frozen(24000 + 59000) &&
               !p.frozen(24000 + 61000));
        CCFxPlayer q;
        EXPECT(q.start(CC_HFX_TICK, false, 0, 5.0f, false, cue) && !q.frozen(1000));
        CCFxPlayer r;
        EXPECT(r.start(CC_HFX_DETENT, false, 0, 0.0f, false, cue, -1, 35, cc_feel_params(CC_FEEL_LIST, false).sound) &&
               cue.sound == CC_SOUND_WOOD && r.volts(1000) < 0.0f && r.counters().pulses == 1);
        CCFxPlayer s;
        EXPECT(!s.start(CC_HFX_DETENT, false, 0, 0.0f, false, cue, 1, 0));   // a token without a pulse
        EXPECT(!s.start(CC_HFX_NONE, false, 0, 0.0f, false, cue) && !s.start(CC_HFX_COUNT, false, 0, 0.0f, false, cue));
    }
    {   // Never above the cap on its own (the loop adds and clamps).
        CCFxPlayer p;
        p.start(CC_HFX_THUMP, false, 0, 0.0f, false, cue);
        float top = 0.0f;
        for (uint32_t t = 0; t < 40000; t += 20) top = std::fmax(top, std::fabs(p.volts(t)));
        EXPECT(top <= CC_HAPTIC_CAP_VOLTS * 1.2f);
    }
}

// ---------------------------------------------------------------------------------------------------------- 4, 5
// The knob model. A rigid rotor (knob + rotor, J), a gimbal motor (Kt, R, back-EMF Ke = Kt), viscous friction, and
// the FOC loop of haptic.cpp's token mode: nearest-detent attractor with the 25 % hysteresis gate, bounded positions,
// the r4 law (spring / wall / damping / effect, the effect freezing the position from rest), 60 us passes and the
// SimpleFOC velocity LPF (10 ms). `flip` models a wrong calibration (the torque sign reversed). Motor constants are
// assumptions (HAPTICS.md "Model"): J 3.25e-6 kg m^2 (a 20 g, 30 mm knob plus the rotor), Kt 0.04 N m/A.
struct Knob {
    double J = 3.25e-6, Kt = 0.04, friction = 2e-6;
    double theta = 0.0, omega = 0.0, lpf = 0.0;
    bool flip = false;
    // loop state
    CCFeelParams p = cc_feel_params(CC_FEEL_LIST, false);
    uint8_t feel = CC_FEEL_LIST;
    float w = 0.0f, origin = 0.0f, attract = 0.0f, lastAttract = 0.0f;
    int pos = 0, lo = 0, hi = 1000;
    bool atLimit = false, legacy = false;
    // haptic.cpp's wasAtLimit: set for the pass that steps inward off a bound, cleared by bounds_handler() in the same
    // pass (after the rest gate read it as busy).
    bool wasAtLimit = false;
    CCFxPlayer fx;
    CCFoldback fold;
    CCSpinTrip trip;
    bool tripEnabled = true;
    bool restEnabled = false;          // haptic.cpp's rest gate (off by default: the older cases predate it)
    CCRestGate rest;
    // haptic.cpp wall_refused(): once per refused detent (cleared back in the committed detent), the wall thud (not in
    // the legacy loop) and FW-BUG-036's rest_.refused(). `thudNow` marks the pass that thudded.
    bool refusedSet = false;
    float refusedAttract = 0.0f;
    int thuds = 0;
    bool thudNow = false;
    // haptic.cpp's feel.fade on the wall, restarted (CC_FEEL_FADE_MS) on the pass that wakes from rest (off by default).
    bool fadeEnabled = false;
    CCFeelFade fade;
    float lastWallV = 0.0f;            // the wall volts applied this pass (after the rest gate)
    void refused() {
        if (refusedSet && refusedAttract == attract) return;
        refusedSet = true;
        refusedAttract = attract;
        rest.refused();
        if (!legacy) { ++thuds; thudNow = true; }
    }
    uint32_t now = 0;
    float lastUq = 0.0f;
    bool frozenBefore = false;
    double freezeStart = 0.0;
    uint32_t freezeUs = 0;             // FW-BUG-033: the time and filtered velocity when the freeze began
    float freezeVelocity = 0.0f;
    void setFeel(uint8_t f, int detents) {
        feel = f; p = cc_feel_params(f, false); legacy = f == CC_FEEL_LEGACY;
        w = static_cast<float>(2.0 * 3.14159265358979 / (p.detents ? p.detents : detents));
        origin = attract = lastAttract = static_cast<float>(theta);
    }
    // FW-BUG-010: haptic.cpp plays the token's detent pulse on every counted detent (detent_pulse()) when
    // `detentPulses` is set; `posUps` / `posDowns` count the position's steps each way.
    bool detentPulses = false;
    int posUps = 0, posDowns = 0;
    void counted(int dir) {
        if (dir > 0) ++posUps; else ++posDowns;
        if (!detentPulses || legacy || !p.pulse) return;
        CCSoundCue cue;
        const bool coasting = p.coast && std::fabs(lpf) > CC_HAPTIC_COAST_RAD_S;
        fx.start(CC_HFX_DETENT, false, now, static_cast<float>(lpf), coasting, cue, static_cast<int8_t>(-dir), p.pulse, p.sound);
    }
    // haptic.cpp detent_handler() (the model's sensor counts up with the angle).
    void handler() {
        if (attract > lastAttract) { if (pos < hi) { if (atLimit) wasAtLimit = true; ++pos; lastAttract = attract; atLimit = false; counted(1); } else { atLimit = true; refused(); } }
        else { if (pos > lo) { if (atLimit) wasAtLimit = true; --pos; lastAttract = attract; atLimit = false; counted(-1); } else { atLimit = true; refused(); } }
    }
    // haptic.cpp find_detent(): the attractor from the grid (index x w + origin), the committed detent kept when the
    // index is the same (FW-BUG-010: never a phantom step from float rounding).
    void findDetent() {
        const float hyst = w * 0.25f, th = static_cast<float>(theta);
        if (th < attract - hyst || th > attract + hyst) attract = cc_detent_angle(cc_detent_index(th, origin, w), origin, w);
        if (attract != lastAttract && cc_detent_index(attract, origin, w) == cc_detent_index(lastAttract, origin, w))
            attract = lastAttract;
        if (attract != lastAttract) handler();
        else refusedSet = false;           // back in the committed detent: the next refused detent is a new hit
    }
    // haptic.cpp end_freeze(): in a viscous feel, the grid moves with the pulses' displacement (cc_freeze_absorb(),
    // FW-BUG-033: the shift less the hand's turn); the detents crossed meanwhile (the turn) are counted one at a time
    // (a bound stops the count).
    void endFreeze() {
        const float shift = static_cast<float>(theta - freezeStart);
        const float absorb = cc_freeze_absorb(!legacy && p.law == CC_LAW_VISCOSE, freezeVelocity, static_cast<float>(lpf),
                                              static_cast<float>(now - freezeUs) * 1e-6f, shift, w);
        origin += absorb; attract += absorb; lastAttract += absorb;
        const long target = cc_detent_index(static_cast<float>(theta), origin, w);
        int steps = static_cast<int>(target - cc_detent_index(lastAttract, origin, w));
        for (int i = 0; i < 256 && steps != 0; ++i) {
            attract = cc_detent_angle(cc_detent_index(lastAttract, origin, w) + (steps > 0 ? 1 : -1), origin, w);
            handler();
            if (atLimit) break;
            steps += steps > 0 ? -1 : 1;
        }
    }
    float output() {
        const float vel = static_cast<float>(lpf);
        float spring = 0.0f, wallV = 0.0f;
        const float d = static_cast<float>(theta) - lastAttract;
        float pen = 0.0f;
        int outward = 0;
        if (pos >= hi && d > 0.0f) { pen = d; outward = 1; }
        else if (pos <= lo && d < 0.0f) { pen = -d; outward = -1; }
        if (legacy) {
            // haptic.cpp's legacy loop: P 3 on the error clamped to +-w, zero above 30 rad/s, limited to 0.4 A.
            float e = lastAttract - static_cast<float>(theta);
            if (std::fabs(vel) > 30.0f) e = 0.0f;
            e = e > w ? w : (e < -w ? -w : e);
            spring = 3.0f * e;
            spring = spring > 0.4f ? 0.4f : (spring < -0.4f ? -0.4f : spring);
        } else if (pen > 0.0f) {
            wallV = cc_wall_volts(cc_law_slope(p.law, p.kp), pen, w, CC_HAPTIC_CAP_VOLTS * fold.factor()) *
                    (fadeEnabled ? fade.factor(now) : 1.0f);
            spring = -static_cast<float>(outward) * wallV / CC_HAPTIC_PHASE_OHMS;
        } else {
            const bool coast = p.coast && std::fabs(vel) > CC_HAPTIC_COAST_RAD_S;
            spring = coast ? 0.0f : cc_law_spring(p.law, p.kp, lastAttract - static_cast<float>(theta), w);
        }
        float out = spring + (legacy ? 0.0f : cc_damping(p.kd, vel)) + fx.volts(now) / CC_HAPTIC_PHASE_OHMS;
        out = out > CC_HAPTIC_CAP_AMPS ? CC_HAPTIC_CAP_AMPS : (out < -CC_HAPTIC_CAP_AMPS ? -CC_HAPTIC_CAP_AMPS : out);
        if (restEnabled) {
            // haptic.cpp's busy terms (HN-TST-001): an effect playing, the pass stepping off a bound, the detent count
            // frozen (frozenBefore is this pass's freeze). The token loop's `kd > fp_.kd` (hold.tension) is never true
            // here: the model has no hold.tension.
            const bool busy = fx.busy(now) || wasAtLimit || frozenBefore;
            const bool wasAsleep = rest.asleep();
            if (rest.step(now, static_cast<float>(theta), lastAttract - static_cast<float>(theta), vel, busy,
                          cc_rest_wake_rad(w))) { out = 0.0f; wallV = 0.0f; }
            else if (wasAsleep && fadeEnabled) fade.start(CC_FEEL_FADE_MS, now);
        }
        lastWallV = wallV;
        fold.step(wallV, 60e-6f);         // FW-TST-001: the wall volts applied, after the rest gate (as haptic.cpp)
        if (!atLimit && wasAtLimit) wasAtLimit = false;   // bounds_handler() clears it (its recovery loop is not modelled)
        return out;
    }
    // One 60 us pass; `hand` N m of external torque, or a velocity source when `drive` is set.
    void step(double hand, bool drive = false, double driveOmega = 0.0) {
        const double dt = 60e-6;
        thudNow = false;
        const bool frozen = fx.frozen(now);
        if (frozen && !frozenBefore) { freezeStart = theta; freezeUs = now; freezeVelocity = static_cast<float>(lpf); }
        if (!frozen && frozenBefore) endFreeze();
        frozenBefore = frozen;
        if (!frozen) findDetent();
        float amps = output();
        if (tripEnabled && trip.step(static_cast<float>(lpf), static_cast<float>(dt))) fx.cancel();
        if (trip.latched()) amps = 0.0f;
        lastUq = amps * CC_HAPTIC_PHASE_OHMS;
        const double current = (static_cast<double>(lastUq) - Kt * omega) / CC_HAPTIC_PHASE_OHMS;   // back-EMF
        const double torque = (flip ? -1.0 : 1.0) * Kt * current - friction * omega + hand;
        if (drive) omega = driveOmega;
        else omega += torque / J * dt;
        theta += omega * dt;
        lpf += (omega - lpf) * (dt / (0.01 + dt));
        now += 60;
    }
    void run(double seconds, double hand = 0.0) {
        const int n = static_cast<int>(seconds / 60e-6);
        for (int i = 0; i < n; ++i) step(hand);
    }
};

void model_tests() {
    CCSoundCue cue;
    // At rest: every event, in every feel, leaves the position where it was.
    const uint8_t feels[] = {CC_FEEL_VALUE, CC_FEEL_DIMMER, CC_FEEL_LIST, CC_FEEL_COARSE, CC_FEEL_FINE, CC_FEEL_SCRUB,
                             CC_FEEL_LIGHT};
    const uint8_t events[] = {CC_HFX_TICK, CC_HFX_THUMP, CC_HFX_NUDGE_LEFT, CC_HFX_NUDGE_RIGHT, CC_HFX_REFUSE, CC_HFX_ERROR,
                              CC_HFX_OFF};
    for (uint8_t f : feels) {
        for (uint8_t e : events) {
            Knob k;
            k.setFeel(f, 67);
            k.pos = 500;
            k.run(0.05);
            const int before = k.pos;
            EXPECT(k.fx.start(e, false, k.now, static_cast<float>(k.lpf), false, cue));
            k.run(0.6);
            if (k.pos != before) std::printf("  feel %s event %s: position %d -> %d\n", cc_feel_name(f), cc_fx_name(e), before, k.pos);
            EXPECT(k.pos == before);
        }
    }
    // A constant-speed turn (the hand is a velocity source): the same count with and without effects and pulses.
    for (uint8_t f : feels) {
        int counts[2] = {0, 0};
        for (int withFx = 0; withFx < 2; ++withFx) {
            Knob k;
            k.setFeel(f, 67);
            k.pos = 500;
            for (int i = 0; i < static_cast<int>(1.0 / 60e-6); ++i) {
                if (withFx && i % 800 == 0) k.fx.start(i % 1600 ? CC_HFX_TICK : CC_HFX_THUMP, false, k.now, static_cast<float>(k.lpf), false, cue);
                k.step(0.0, true, 6.0);
            }
            counts[withFx] = k.pos - 500;
        }
        EXPECT(counts[0] == counts[1] && counts[0] > 0);
    }
}

// 2026-09-30, the user: at Lights 100 % the knob never went quiet, then woke at the lightest touch. Resting at the
// bound it sleeps; a light touch into the wall (1 degree) leaves it asleep; a push past the end, let go, settles at the
// bound and falls asleep again.
void wall_rest_tests() {
    {
        Knob k;
        k.setFeel(CC_FEEL_DIMMER, 67);
        k.restEnabled = true;
        k.lo = 0; k.hi = 100; k.pos = 100;
        k.run(0.5);
        EXPECT(k.rest.asleep());
        // A light touch into the wall: the finger carries the knob about 1.7 degrees, then holds it.
        for (int i = 0; i < static_cast<int>(0.3 / 60e-6); ++i) k.step(0.0, true, 0.1);
        for (int i = 0; i < static_cast<int>(0.3 / 60e-6); ++i) k.step(0.0, true, 0.0);
        EXPECT(k.rest.asleep() && k.rest.wakes() == 0 && k.pos == 100);
        // A real push past the end (one detent and more) wakes it.
        for (int i = 0; i < static_cast<int>(0.3 / 60e-6); ++i) k.step(0.0, true, 0.5);
        EXPECT(!k.rest.asleep() && k.rest.wakes() == 1 && k.pos == 100);
    }
    for (int variant = 0; variant < 1; ++variant) {
        Knob k;
        k.setFeel(CC_FEEL_DIMMER, 67);
        k.restEnabled = true;
        k.lo = 0; k.hi = 100; k.pos = 100;
        k.run(0.2);
        k.run(0.25, 0.004);                     // lean into the wall (4 mN m)
        k.run(0.02, -0.002);                    // a flick back as the finger lifts
        double maxOmega = 0.0;
        for (int i = 0; i < static_cast<int>(1.5 / 60e-6); ++i) {
            k.step(0.0);
            if (i > static_cast<int>(1.0 / 60e-6)) maxOmega = std::max(maxOmega, std::fabs(k.omega));
        }
        std::printf("  wall let-go: pos %d, |omega| max over the last 0.5 s %.3f rad/s, asleep %d, sleeps %u, wakes %u\n",
                    k.pos, maxOmega, k.rest.asleep() ? 1 : 0, k.rest.sleeps(), k.rest.wakes());
        EXPECT(k.pos == 100 && maxOmega < 0.05 && k.rest.asleep() && k.rest.sleeps() >= 1);
    }
    {   // FW-TST-001: asleep at the bound with a finger resting 2 degrees past the end (below the 5.37 degree wake
        // distance, and below half a detent, 2.69 degrees, where FW-BUG-036's refused detent wakes it) for a minute:
        // the output stays zero, so the fold-back stays cool and the next push is full force.
        Knob k;
        k.setFeel(CC_FEEL_DIMMER, 67);
        k.restEnabled = true;
        k.tripEnabled = false;
        k.lo = 0; k.hi = 100; k.pos = 100;
        k.run(0.5);
        EXPECT(k.rest.asleep());
        const double deg2 = 2.0 * 3.14159265358979 / 180.0;
        const double target = k.theta + deg2;
        while (k.theta < target) k.step(0.0, true, 0.05);
        for (int i = 0; i < static_cast<int>(60.0 / 60e-6); ++i) k.step(0.0, true, 0.0);
        if (k.fold.factor() != 1.0f || k.fold.energy() != 0.0f)
            std::printf("  FW-TST-001 asleep past the bound: fold %.3f, energy %.1f V^2 s, asleep %d\n",
                        k.fold.factor(), k.fold.energy(), k.rest.asleep() ? 1 : 0);
        EXPECT(k.rest.asleep() && k.rest.wakes() == 0 && k.pos == 100);
        EXPECT(k.fold.factor() == 1.0f && k.fold.energy() == 0.0f && k.fold.events() == 0);
        // Awake and pushing into the wall the same way, the fold-back does integrate (the gate is the only change).
        k.restEnabled = false;
        k.run(0.01);
        EXPECT(k.fold.energy() > 0.0f);
    }
    // The wake distance: one detent, between 2.5 degrees and one volume detent (5.4 degrees).
    const double deg = 3.14159265358979 / 180.0;
    EXPECT(near(cc_rest_wake_rad(static_cast<float>(2.0 * 3.14159265358979 / 67.0)), 2.0 * 3.14159265358979 / 67.0, 1e-6));
    EXPECT(near(cc_rest_wake_rad(static_cast<float>(2.0 * 3.14159265358979 / 20.0)), 2.0 * 3.14159265358979 / 67.0, 1e-6));
    EXPECT(near(cc_rest_wake_rad(static_cast<float>(1.0 * deg)), 2.5 * deg, 1e-6));
}

// FW-BUG-036 (2026-10-03, the user): asleep at an end stop, a push outward refuses the next detent (half a detent past
// the bound: the thud and cc_wall_hit). That refused detent wakes the rest gate, so the thud and the first nonzero wall
// output come in the same pass, before the wake distance; the wall then fades in (feel.fade on waking) and never drops
// to zero while the push goes on. Never a thud with zero force.
void bound_push_thud_and_force_coincide() {
    const double deg = 3.14159265358979 / 180.0;
    const uint8_t feels[] = {CC_FEEL_VALUE, CC_FEEL_DIMMER, CC_FEEL_FINE};
    for (uint8_t f : feels) {
        for (int dir = 1; dir >= -1; dir -= 2) {
            Knob k;
            k.setFeel(f, 67);
            k.restEnabled = true;
            k.fadeEnabled = true;
            k.tripEnabled = false;
            k.lo = 0; k.hi = 100; k.pos = dir > 0 ? 100 : 0;
            k.run(0.5);
            EXPECT(k.rest.asleep() && k.thuds == 0);
            const double start = k.theta;
            int thudPass = -1, firstWallPass = -1, zeroAfter = 0;
            float thudWall = 0.0f, thudOut = 0.0f, wall10ms = 0.0f;
            double thudAt = 0.0;
            const int n = static_cast<int>(0.6 / 60e-6);
            for (int i = 0; i < n; ++i) {
                k.step(0.0, true, dir * 0.15);              // a slow push outward (velocity source)
                const float out = k.lastUq / CC_HAPTIC_PHASE_OHMS;
                if (firstWallPass < 0 && k.lastWallV > 0.0f) firstWallPass = i;
                if (k.thudNow && thudPass < 0) {
                    thudPass = i; thudWall = k.lastWallV; thudOut = out;
                    thudAt = std::fabs(k.theta - start);
                }
                if (thudPass >= 0 && i > thudPass) {
                    if (k.lastWallV <= 0.0f || out * dir >= 0.0f) ++zeroAfter;   // the wall pushes back (inward)
                    if (i == thudPass + static_cast<int>(0.01 / 60e-6)) wall10ms = k.lastWallV;
                }
            }
            const float unfaded = cc_wall_volts(cc_law_slope(k.p.law, k.p.kp), static_cast<float>(thudAt), k.w,
                                                CC_HAPTIC_CAP_VOLTS);
            std::printf("  FW-BUG-036 %s dir %+d: thud at %.2f deg (wake distance %.2f), thud pass %d, first wall pass %d,"
                        " wall %.3f V, out %.4f A, wall 10 ms on %.3f V (unfaded %.3f), zero-force passes after %d\n",
                        cc_feel_name(f), dir, thudAt / deg, cc_rest_wake_rad(k.w) / deg, thudPass, firstWallPass,
                        thudWall, thudOut, wall10ms, unfaded, zeroAfter);
            EXPECT(k.thuds == 1 && k.pos == (dir > 0 ? 100 : 0));
            EXPECT(thudPass >= 0 && thudPass == firstWallPass);           // the thud and the first wall force together
            EXPECT(thudWall > 0.0f && thudOut * dir < 0.0f);              // never a thud with zero force
            EXPECT(thudAt < cc_rest_wake_rad(k.w) - 0.2 * deg);            // woken by the refusal, not the distance
            EXPECT(near(thudAt, 0.5 * k.w, 0.3 * deg));                   // the refusal: half a detent past the bound
            EXPECT(k.rest.wakes() == 1 && !k.rest.asleep());
            EXPECT(zeroAfter == 0);                                       // the wall stays on while the push goes on
            EXPECT(wall10ms > 0.0f && wall10ms < 0.5f * unfaded);          // and fades in (feel.fade on waking stays)
        }
    }
    {   // An ordinary turn is unchanged: asleep off the bounds, a push of less than the wake distance crosses no bound,
        // refuses nothing and leaves it asleep.
        Knob k;
        k.setFeel(CC_FEEL_LIST, 67);
        k.restEnabled = true;
        k.tripEnabled = false;
        k.pos = 500;
        k.run(0.5);
        EXPECT(k.rest.asleep());
        const double start = k.theta;
        while (k.theta - start < 1.5 * deg) k.step(0.0, true, 0.1);
        for (int i = 0; i < static_cast<int>(0.05 / 60e-6); ++i) k.step(0.0, true, 0.0);
        EXPECT(k.rest.asleep() && k.rest.wakes() == 0 && k.thuds == 0);
    }
    {   // The gate's own rule: refused() makes the next step busy (it wakes), once; it falls asleep again afterwards.
        CCRestGate g;
        uint32_t t = 0;
        for (int i = 0; i < 6000; ++i, t += 60) g.step(t, 0.0f, 0.0f, 0.0f, false);
        EXPECT(g.asleep());
        g.refused();
        EXPECT(!g.step(t, 0.0f, 0.0f, 0.0f, false) && !g.asleep() && g.wakes() == 1);
        for (int i = 0; i < 6000; ++i) { t += 60; g.step(t, 0.0f, 0.0f, 0.0f, false); }
        EXPECT(g.asleep() && g.sleeps() == 2);
    }
}

void foldback_tests() {
    // A lean into the wall at full force: it folds after the budget and holds at 50 %, then recovers after release.
    CCFoldback f;
    double t = 0.0, foldedAt = -1.0;
    for (; t < 60.0; t += 0.001) {
        f.step(CC_HAPTIC_CAP_VOLTS * f.factor(), 0.001f);
        if (foldedAt < 0.0 && f.folding()) foldedAt = t;
    }
    const double expected = CC_FOLD_BUDGET_V2S / (CC_HAPTIC_CAP_VOLTS * CC_HAPTIC_CAP_VOLTS - CC_FOLD_COOL_V2);
    EXPECT(foldedAt > 0.0 && near(foldedAt, expected, 0.5));
    EXPECT(f.factor() >= CC_FOLD_MIN - 1e-4f && f.factor() <= CC_FOLD_MIN + 0.05f && f.events() == 1);
    double recovered = -1.0;
    for (double r = 0.0; r < 120.0; r += 0.001) {
        f.step(0.0f, 0.001f);
        if (recovered < 0.0 && f.factor() >= 0.999f) recovered = r;
    }
    EXPECT(recovered > 0.0 && f.factor() == 1.0f);
    // Short pushes never fold.
    CCFoldback g;
    for (int push = 0; push < 100; ++push) {
        for (int i = 0; i < 500; ++i) g.step(2.2f, 0.001f);
        for (int i = 0; i < 1500; ++i) g.step(0.0f, 0.001f);
    }
    EXPECT(!g.folding() && g.factor() == 1.0f && g.events() == 0);
    // The model: leaning on the wall of a 20-item list for a minute.
    Knob k;
    k.setFeel(CC_FEEL_LIST, 20);
    k.hi = 0; k.lo = 0;
    k.tripEnabled = false;
    double minVolts = 10.0;
    for (int i = 0; i < static_cast<int>(60.0 / 60e-6); ++i) {
        k.step(0.03);                                   // 30 mN m: more than the wall's 16.6 mN m
        if (i > static_cast<int>(40.0 / 60e-6)) minVolts = std::fmin(minVolts, std::fabs(static_cast<double>(k.lastUq)));
    }
    EXPECT(k.fold.events() >= 1 && minVolts >= CC_FOLD_MIN * CC_HAPTIC_CAP_VOLTS - 0.05);
}

double time_to_trip(Knob& k, double seconds, double hand = 0.0) {
    for (int i = 0; i < static_cast<int>(seconds / 60e-6); ++i) {
        k.step(hand);
        if (k.trip.latched()) return i * 60e-6;
    }
    return -1.0;
}

void trip_tests() {
    // The flipped-torque model (a wrong calibration). A detent well only buzzes (no spin); a wall or a viscous feel
    // runs away. The trip must latch within a few seconds of each runaway, in the token loop and the legacy loop.
    {   // Flipped, the wells become hills: the knob tumbles from hill to hill (a spin through the list).
        Knob k; k.flip = true; k.setFeel(CC_FEEL_LIST, 20); k.pos = 10; k.theta += 0.02;
        const double t = time_to_trip(k, 10.0);
        std::printf("  flipped detents (detent.list): trip at %.2f s\n", t);
        EXPECT(t > 0.0 && t < 8.0);
    }
    {
        Knob k; k.flip = true; k.setFeel(CC_FEEL_LIST, 20); k.lo = 0; k.hi = 0; k.theta += 0.01;
        const double t = time_to_trip(k, 6.0);
        std::printf("  flipped wall (detent.list): trip at %.2f s\n", t);
        EXPECT(t > 0.0 && t < 3.5);
    }
    {
        Knob k; k.flip = true; k.setFeel(CC_FEEL_LIGHT, 67); k.omega = 2.0;
        const double t = time_to_trip(k, 6.0);
        std::printf("  flipped viscous (fluid.light): trip at %.2f s\n", t);
        EXPECT(t > 0.0 && t < 3.5);
    }
    {
        Knob k; k.flip = true; k.setFeel(CC_FEEL_LEGACY, 67); k.lo = 0; k.hi = 0; k.theta += 0.01;
        const double t = time_to_trip(k, 8.0);
        std::printf("  flipped wall (legacy loop): trip at %.2f s\n", t);
        EXPECT(t > 0.0 && t < 5.0);
    }
    {   // After a trip the output stays zero; clear() (a claim or a key press) arms it again.
        Knob k; k.flip = true; k.setFeel(CC_FEEL_SCRUB, 67); k.omega = 3.0;
        EXPECT(time_to_trip(k, 6.0) > 0.0);
        k.run(0.2);
        EXPECT(k.lastUq == 0.0f && k.trip.trips() == 1);
        k.trip.clear();
        EXPECT(!k.trip.latched() && k.trip.score() == 0.0f);
    }
    // Ordinary hands, correct torque: a hard flick (free spin), a long list scroll at 12 rad/s, a 1.5 s spin at
    // 25 rad/s, and pushing through a wall: no trip.
    {
        Knob k; k.setFeel(CC_FEEL_FREE_SPIN, 20); k.pos = 50; k.hi = 200;
        for (int i = 0; i < static_cast<int>(0.05 / 60e-6); ++i) k.step(0.06);
        k.run(5.0);
        EXPECT(!k.trip.latched());
    }
    {
        Knob k; k.setFeel(CC_FEEL_LIST, 20); k.hi = 100000;
        for (int i = 0; i < static_cast<int>(10.0 / 60e-6); ++i) k.step(0.0, true, 12.0);
        EXPECT(!k.trip.latched());
    }
    {
        Knob k; k.setFeel(CC_FEEL_LIGHT, 67); k.hi = 60000; k.pos = 30000;
        for (int i = 0; i < static_cast<int>(1.5 / 60e-6); ++i) k.step(0.0, true, 25.0);
        k.run(2.0);
        EXPECT(!k.trip.latched());
    }
    {
        Knob k; k.setFeel(CC_FEEL_LIST, 20); k.lo = 0; k.hi = 0;
        for (int i = 0; i < static_cast<int>(0.5 / 60e-6); ++i) k.step(0.0, true, 8.0);
        k.run(1.0);
        EXPECT(!k.trip.latched());
    }
    // The pure timer: 2 s at speed latches; gaps decay at half rate.
    CCSpinTrip t;
    for (int i = 0; i < 1999; ++i) t.step(20.0f, 0.001f);
    EXPECT(!t.latched());
    for (int i = 0; i < 2; ++i) t.step(20.0f, 0.001f);
    EXPECT(t.latched() && t.trips() == 1);
    CCSpinTrip u;
    for (int cycle = 0; cycle < 100; ++cycle) {
        for (int i = 0; i < 600; ++i) u.step(20.0f, 0.001f);     // 0.6 s fast
        for (int i = 0; i < 1400; ++i) u.step(2.0f, 0.001f);     // 1.4 s slow
    }
    EXPECT(!u.latched());
}

// FW-BUG-046 test_cal_direction_rule_ignores_cleared_trip: the recalibration direction rule (CCCalTripGuard, as
// foc_thread.cpp recalibrate() asks it) accepts a changed direction on the request bit, a latch at request time or a
// trip since the last successful calibration, never for a trip a calibration has already answered.
void trip_step_to_latch(CCSpinTrip& t) { for (int i = 0; i < 2100 && !t.latched(); ++i) t.step(20.0f, 0.001f); }
void test_cal_direction_rule_ignores_cleared_trip() {
    CCSpinTrip trip;
    CCCalTripGuard guard;
    EXPECT(!guard.acceptDirection(false, trip) && guard.acceptDirection(true, trip));   // boot: no trip, no change
    trip_step_to_latch(trip);
    EXPECT(trip.latched() && guard.acceptDirection(false, trip));                       // latched at request time
    trip.clear();                                                                       // a key press clears it
    EXPECT(!trip.latched() && trip.trips() == 1 && guard.acceptDirection(false, trip)); // tripped since the last cal
    guard.calibrated(trip);                                                             // a run succeeded
    EXPECT(!guard.acceptDirection(false, trip));          // the cleared trip before it no longer accepts a change
    EXPECT(guard.acceptDirection(true, trip));            // the request bit still does
    trip_step_to_latch(trip);
    EXPECT(trip.trips() == 2 && guard.acceptDirection(false, trip));   // latched now
    trip.clear();
    EXPECT(guard.acceptDirection(false, trip));           // a new trip since that calibration
    guard.calibrated(trip);
    EXPECT(!guard.acceptDirection(false, trip));
}

// FW-BUG-032 test_app_angle_word_wraps: the app canvas angle word (CCAngleWord, published by foc_thread.cpp) follows
// the sensor's whole turns + in-turn angle as a wrapping count. Started at 0x7FFFFF00 and far past the ~34k turns where
// int32(angle * 1e4) saturated, a steady turn steps it by the small deltas through 0x7FFFFFFF -> 0x80000000 with no
// jump or stall, and the sum of the unsigned differences a reader takes matches the turn to within 1e-4 rad.
void test_app_angle_word_wraps() {
    CCAngleWord w(0x7FFFFF00u);
    const double step = 0.0021;                 // rad per FOC pass (a quick turn)
    const double twoPi = 2.0 * 3.14159265358979323846;
    int32_t turns = 34200;                      // ~214,900 rad: past the old cast's range
    double inTurn = 6.2;
    EXPECT(w.step(turns, static_cast<float>(inTurn)) == static_cast<int32_t>(0x7FFFFF00u));
    uint32_t prev = w.word();
    double total = 0.0;
    int64_t summed = 0;
    bool crossed = false, smooth = true;
    for (int i = 0; i < 400; ++i) {
        inTurn += step; total += step;
        if (inTurn >= twoPi) { inTurn -= twoPi; ++turns; }   // the sensor's turn boundary
        w.step(turns, static_cast<float>(inTurn));
        const int32_t d = static_cast<int32_t>(w.word() - prev);   // the reader's unsigned difference
        if (d < 20 || d > 22) smooth = false;
        if (prev <= 0x7FFFFFFFu && w.word() >= 0x80000000u) crossed = true;
        summed += d;
        prev = w.word();
    }
    EXPECT(crossed && smooth);
    EXPECT(std::llabs(summed - static_cast<int64_t>(std::llround(total * 1e4))) <= 1);
    // Backwards through the same wrap, and a whole-turn boundary going down.
    int64_t back = 0;
    for (int i = 0; i < 400; ++i) {
        inTurn -= step;
        if (inTurn < 0.0) { inTurn += twoPi; --turns; }
        w.step(turns, static_cast<float>(inTurn));
        back += static_cast<int32_t>(w.word() - prev);
        prev = w.word();
    }
    EXPECT(std::llabs(back + summed) <= 1 && w.word() - 0x7FFFFF00u + 1u <= 2u);
    // The whole-turn count wrapping too (2^31 turns) is one ordinary step.
    CCAngleWord z;
    z.step(INT32_MAX, 6.28f);
    z.step(INT32_MIN, 0.0021f);
    EXPECT(z.value() >= 52 && z.value() <= 54);   // 2 pi - 6.28 + 0.0021 rad = 52.9e-4 rad
}

// FW-RES-011 test_foc_reseed_after_motor_driven_motion: a recalibration while asleep moves the shaft with the motor
// (the alignment sweep and the pole check). foc_thread.cpp then disables the driver and starts the sleep watcher over
// (sleep_foc = CCSleepFoc(), stepped once asleep in the same pass so motorOff() holds for the rest of it) at the
// new angle: the motor-driven travel is no input (no wake), the motor stays off,
// and a hand's turn after the quiet window still wakes the knob. The old watcher read the same travel as a wake.
void test_foc_reseed_after_motor_driven_motion() {
    const float angle = 1.0f;
    uint32_t now = 1000;
    CCSleepFoc foc;
    foc.step(now, angle, false);
    EXPECT(foc.step(now += 10, angle, true).action == CC_SLEEP_MOTOR_DISABLE && foc.motorOff());
    now += kCCSleepDisableQuietMs + 100;                                  // asleep past the quiet window
    EXPECT(!foc.step(now, angle, true).input);
    {   // the control: the recalibration's own motion, read by the untouched watcher, is a wake turn
        CCSleepFoc stale = foc;
        EXPECT(stale.step(now + 3000, angle + 0.5f, true).input);
    }
    now += 3000;                                                          // the recalibration ran (~3 s)
    foc = CCSleepFoc();                                                   // foc_thread.cpp: still asleep -> start over
    EXPECT(!foc.motorOff());                                              // the fresh watcher alone reads "awake" ...
    CCSleepFocStep s = foc.step(now, angle + 0.5f, true);                 // ... so it is stepped in the same pass
    EXPECT(!s.input && s.action == CC_SLEEP_MOTOR_DISABLE && foc.motorOff());   // off again, no wake
    // The rest of that pass gates on motorOff(): offline volume, the spin trip, host effects (discarded) and the
    // haptic loop (the zero-output branch) all see the knob asleep, before the next pass's watcher step.
    EXPECT(foc.motorOff());
    s = foc.step(now += 20, angle + 0.52f, true);                         // the shaft settling after release
    EXPECT(!s.input && s.action == CC_SLEEP_MOTOR_KEEP && foc.motorOff());
    s = foc.step(now += kCCSleepDisableQuietMs, angle + 0.52f, true);
    EXPECT(!s.input && s.action == CC_SLEEP_MOTOR_KEEP && foc.motorOff());
    s = foc.step(now += 50, angle + 0.52f + 2.0f * kCCSleepWakeRad, true);   // a hand's turn: the wake
    EXPECT(s.input && foc.motorOff());
}

// FW-BUG-031 test_successful_recalibration_clears_trip_latch: a latch from a wrong calibration holds the output at
// zero; a failed recalibration leaves it latched (CCCalTripGuard::calibrated() is only called on CC_CAL_OK), a
// successful one clears it, and the next detent has a nonzero output again.
void test_successful_recalibration_clears_trip_latch() {
    Knob k; k.flip = true; k.setFeel(CC_FEEL_SCRUB, 67); k.omega = 3.0;
    CCCalTripGuard guard;
    EXPECT(time_to_trip(k, 6.0) > 0.0);
    k.run(0.2);
    EXPECT(k.trip.latched() && k.lastUq == 0.0f);
    // A failed run (restored, re-enabled): nothing clears the latch; the output stays zero.
    k.omega = 0.0; k.lpf = 0.0; k.setFeel(CC_FEEL_LIST, 20);   // a detent feel: off-centre pulls back
    k.theta += k.w * 0.2; k.step(0.0);
    EXPECT(k.trip.latched() && k.lastUq == 0.0f);
    // A successful run: the torque is right again, the detents re-anchored, the latch cleared.
    k.flip = false; k.omega = 0.0; k.lpf = 0.0; k.setFeel(CC_FEEL_LIST, 20);
    guard.calibrated(k.trip);
    EXPECT(!k.trip.latched() && k.trip.trips() == 1 && !guard.acceptDirection(false, k.trip));
    k.theta += k.w * 0.2; k.step(0.0);
    EXPECT(!k.trip.latched() && k.lastUq != 0.0f);
}

// FW-TST-010 cal_handshake_tests: the recalibration save handshake (CCCalHandshake, foc_thread.cpp save_through_com()
// / cc_cal_take_save() / cc_cal_saved()) with an injected clock: offer / take / saved -> SAVED; no take within 1.5 s ->
// TIMEOUT and the offer can no longer be taken; a take with no saved() -> TIMEOUT within the 3 s write bound (it used to
// wait forever), a late saved() is ignored; and a two-thread race of 1e5 offers never takes one twice and never
// reports SAVED without its take.
struct HostCalLock {
    std::mutex m;
    void lock() { m.lock(); }
    void unlock() { m.unlock(); }
};
void cal_handshake_tests() {
    HostCalLock lock;
    CCCalHandshake<HostCalLock> h(lock);
    cc_haptic_detail::Shared& s = cc_haptic_detail::shared();
    int32_t d = 0;
    float z = 0.0f;
    EXPECT(h.poll(5) == CC_CAL_POLL_TIMEOUT);                   // nothing offered: no wait
    h.offer(1, 2.5f, 100);
    EXPECT(h.poll(101) == CC_CAL_POLL_WAIT);
    EXPECT(h.take(d, z) && d == 1 && z == 2.5f && !h.take(d, z));
    EXPECT(h.poll(102) == CC_CAL_POLL_WAIT);
    h.saved(true);
    EXPECT(h.poll(103) == CC_CAL_POLL_SAVED && s.calSave == CC_CAL_SAVE_NONE);
    // FW-BUG-028: a refused NVS write is reported failed and ends the wait at once (not after the 3 s write bound),
    // never as SAVED; a later report is ignored.
    h.offer(1, 2.5f, 200);
    EXPECT(h.take(d, z));
    EXPECT(h.poll(201) == CC_CAL_POLL_WAIT);
    h.saved(false);
    EXPECT(s.calSave == CC_CAL_SAVE_FAILED);
    EXPECT(h.poll(202) == CC_CAL_POLL_FAILED && s.calSave == CC_CAL_SAVE_NONE);
    h.saved(true);
    EXPECT(s.calSave == CC_CAL_SAVE_NONE && h.poll(203) == CC_CAL_POLL_TIMEOUT);
    // A failure report without a take never ends an offer.
    h.offer(1, 2.5f, 300);
    h.saved(false);
    EXPECT(s.calSave == CC_CAL_SAVE_READY && h.poll(301) == CC_CAL_POLL_WAIT);
    EXPECT(h.take(d, z));
    h.saved(false);
    EXPECT(h.poll(302) == CC_CAL_POLL_FAILED);
    // Not taken: 1.5 s, then the COM task cannot take it any more.
    h.offer(-1, 1.0f, 1000);
    EXPECT(h.poll(1000 + CC_CAL_SAVE_TIMEOUT_MS - 1) == CC_CAL_POLL_WAIT);
    EXPECT(h.poll(1000 + CC_CAL_SAVE_TIMEOUT_MS) == CC_CAL_POLL_TIMEOUT && !h.take(d, z) && s.calSave == CC_CAL_SAVE_NONE);
    // Taken just before the take deadline: the write bound runs from the take, not from the offer.
    h.offer(1, 1.0f, 2000);
    EXPECT(h.take(d, z));
    EXPECT(h.poll(2000 + CC_CAL_SAVE_TIMEOUT_MS) == CC_CAL_POLL_WAIT);
    h.saved(true);
    EXPECT(h.poll(2000 + CC_CAL_SAVE_TIMEOUT_MS + 1) == CC_CAL_POLL_SAVED);
    // Taken, never reported written (a stalled or starved flash write): TIMEOUT within the write bound.
    h.offer(1, 1.0f, 5000);
    EXPECT(h.take(d, z));
    EXPECT(h.poll(5001) == CC_CAL_POLL_WAIT && h.poll(5001 + CC_CAL_WRITE_TIMEOUT_MS - 1) == CC_CAL_POLL_WAIT);
    EXPECT(h.poll(5001 + CC_CAL_WRITE_TIMEOUT_MS) == CC_CAL_POLL_TIMEOUT && s.calSave == CC_CAL_SAVE_NONE);
    h.saved(true);                                              // the late write's report: ignored
    EXPECT(s.calSave == CC_CAL_SAVE_NONE);
    h.saved(false);                                             // a late failure report too
    EXPECT(s.calSave == CC_CAL_SAVE_NONE);
    h.offer(1, 1.0f, 9000);
    h.saved(true);                                              // a stale report never completes a new offer
    EXPECT(h.poll(9001) == CC_CAL_POLL_WAIT && s.calSave == CC_CAL_SAVE_READY);
    EXPECT(h.poll(9000 + CC_CAL_SAVE_TIMEOUT_MS) == CC_CAL_POLL_TIMEOUT);
    // millis() wrap.
    h.offer(1, 1.0f, 0xFFFFFF00u);
    EXPECT(h.poll(0xFFFFFF00u + CC_CAL_SAVE_TIMEOUT_MS - 1u) == CC_CAL_POLL_WAIT &&
           h.poll(0xFFFFFF00u + CC_CAL_SAVE_TIMEOUT_MS) == CC_CAL_POLL_TIMEOUT);
    // The race: the COM task takes whatever is offered (and reports one in three written, one in three refused:
    // FW-BUG-028) while the FOC task offers, polls at the take deadline at once on every other cycle (the timeout racing the take), and moves its clock past
    // the write bound when it waits long.
    const int cycles = 100000;
    std::vector<uint8_t> takes(cycles, 0), results(cycles, 0);
    std::atomic<bool> stop(false);
    std::thread com([&]() {
        int32_t id = 0;
        float zero = 0.0f;
        while (!stop.load()) {
            if (h.take(id, zero)) {
                if (id >= 0 && id < cycles) ++takes[static_cast<size_t>(id)];
                if (id % 3 != 0) h.saved(id % 3 == 2);
            }
        }
    });
    uint32_t clock = 100000;
    for (int i = 0; i < cycles; ++i) {
        clock += 10000;
        h.offer(i, 0.0f, clock);
        uint32_t now = clock + (i % 2 == 0 ? CC_CAL_SAVE_TIMEOUT_MS : 0u);
        uint8_t r = CC_CAL_POLL_WAIT;
        for (int spin = 0; (r = h.poll(now)) == CC_CAL_POLL_WAIT; ++spin) {
            if (spin % 200 == 199) now += CC_CAL_WRITE_TIMEOUT_MS;
            std::this_thread::yield();
        }
        results[static_cast<size_t>(i)] = r;
    }
    stop.store(true);
    com.join();
    int twice = 0, savedUntaken = 0, savedUnsaved = 0, saved = 0, timeouts = 0, failed = 0, failedWrong = 0;
    for (int i = 0; i < cycles; ++i) {
        if (takes[static_cast<size_t>(i)] > 1) ++twice;
        if (results[static_cast<size_t>(i)] == CC_CAL_POLL_SAVED) {
            ++saved;
            if (takes[static_cast<size_t>(i)] != 1) ++savedUntaken;
            if (i % 3 != 2) ++savedUnsaved;
        } else if (results[static_cast<size_t>(i)] == CC_CAL_POLL_FAILED) {
            ++failed;
            if (i % 3 != 1 || takes[static_cast<size_t>(i)] != 1) ++failedWrong;
        } else {
            ++timeouts;
        }
    }
    std::printf("  cal handshake race: %d offers, %d saved, %d failed, %d timed out\n", cycles, saved, failed, timeouts);
    EXPECT(twice == 0 && savedUntaken == 0 && savedUnsaved == 0 && saved > 0 && timeouts > 0 && failed > 0 &&
           failedWrong == 0);
    EXPECT(s.calSave == CC_CAL_SAVE_NONE);
}

// ---------------------------------------------------------------------------------------------------------- 6
// FW-BUG-022 supply_unknown_fails_safe_high: the supply the driver scales its duty with never sits below VBUS, so the
// 2.2 V cap (and every voltage under it) reaches the motor at most at its own value: cap x VBUS / supply <= 2.2 V.
// Rows: (read ok, RDO object position, contract volts read, NVM rewritten this boot, the VBUS it can be, supply).
void supply_tests() {
    struct Row { bool readOk; uint32_t position, contract; bool rewritten; float vbus[4]; float supply; bool assumed; };
    const Row rows[] = {
        {false, 0, 0, false, {5, 9, 9, 9}, 9.0f, true},       // the read failed: the highest sink PDO
        {true, 0, 0, false, {5, 5, 5, 5}, 5.0f, false},       // no contract: a plain PC port, unchanged
        {true, 1, 5, false, {5, 5, 5, 5}, 5.0f, false},
        {true, 2, 9, false, {9, 9, 9, 9}, 9.0f, false},       // our 9 V PDO
        {true, 2, 12, false, {12, 12, 12, 12}, 12.0f, false}, // a foreign NVM table: the contract's own voltage
        {true, 3, 15, false, {15, 15, 15, 15}, 15.0f, false},
        {true, 3, 20, false, {20, 20, 20, 20}, 20.0f, false},
        {true, 5, 0, false, {5, 9, 9, 9}, 9.0f, true},        // 9 V listed past position 3: voltage unknown
        {true, 2, 0, false, {5, 9, 9, 9}, 9.0f, true},        // the sink PDO read failed
        {true, 3, 15, true, {5, 15, 20, 9}, 20.0f, true},     // NVM rewritten this boot: the old table, up to 20 V
        {false, 0, 0, true, {5, 9, 15, 20}, 20.0f, true},
        // Review: a read that worked with no contract is VBUS 5 V whatever the NVM holds, so the first boot of a
        // new knob (factory table rewritten, empty calibration) on a PC port keeps the full feel and alignment field.
        {true, 0, 0, true, {5, 5, 5, 5}, 5.0f, false},
        {true, 2, 9, true, {5, 9, 15, 20}, 20.0f, true},      // rewritten and a contract: the old table, up to 20 V
        {true, 7, 0, true, {5, 9, 15, 20}, 20.0f, true},      // rewritten, position past the table
        // A foreign 2-PDO table (5/20 V, say): init_pd() (plan F8) checks the PDO voltages, so it is a rewrite boot
        // and a failed read there is 20 V, never 9 V (a 9 V guess against 20 V VBUS would be 2.2x the cap).
        {false, 0, 0, true, {5, 20, 20, 20}, 20.0f, true},
        {true, 2, 0, true, {5, 20, 20, 20}, 20.0f, true},
    };
    for (const Row& r : rows) {
        const float supply = cc_supply_volts(r.readOk, r.position, r.contract, r.rewritten);
        EXPECT(supply == r.supply);
        EXPECT(cc_supply_assumed(r.readOk, r.position, r.contract, r.rewritten) == r.assumed);
        for (float vbus : r.vbus) EXPECT(CC_HAPTIC_CAP_VOLTS * vbus / supply <= CC_HAPTIC_CAP_VOLTS + 1e-6f);
    }
    // The old rule's over-drive is gone: unknown never maps to 5 V (1.8x at 9 V).
    EXPECT(cc_supply_volts(false, 0, 0, false) == 9.0f && cc_supply_volts(true, 4, 0, false) == 9.0f);
    EXPECT(cc_supply_volts(true, 2, 21, false) == 9.0f && cc_supply_volts(true, 2, 4, false) == 9.0f);
    // First boot after an NVM rewrite on a PC port: 5 V, not 20 V (the old rule scaled every voltage, the 2.2 V
    // alignment cap included, by 5/20: about 0.55 V at the motor).
    EXPECT(cc_supply_volts(true, 0, 0, true) == 5.0f && !cc_supply_assumed(true, 0, 0, true));
    EXPECT(CC_HAPTIC_CAP_VOLTS * 5.0f / cc_supply_volts(true, 0, 0, true) == CC_HAPTIC_CAP_VOLTS);
    // Every (read, position, contract, rewrite) whose VBUS can exceed 9 V on a 5/9/9 table never maps below 9 V
    // unless the position-0 rule (USB default) or the read contract voltage says so.
    for (int ok = 0; ok < 2; ++ok)
        for (uint32_t pos = 0; pos < 8; ++pos)
            for (uint32_t v = 0; v <= 21; ++v)
                for (int rw = 0; rw < 2; ++rw) {
                    const float s = cc_supply_volts(ok != 0, pos, v, rw != 0);
                    if (ok && pos == 0) EXPECT(s == 5.0f);
                    else if (rw) EXPECT(s == 20.0f);
                    else EXPECT(s >= 9.0f || (ok && v >= 5 && v <= 20 && s == static_cast<float>(v)));
                }
}

// FW-TST-009 boot_cal_tests: the stored pair -> what initFOC() starts from (cc_cal_from_nvs), whether the boot
// aligns (anything not whole: SimpleFOC aligns when the direction is UNKNOWN or the zero NOT_SET), and whether the
// boot stores what the alignment found (cc_boot_cal_store).
void boot_cal_tests() {
    const float nan = std::nanf(""), inf = HUGE_VALF;
    struct Row { const char* name; int byte; float zero; int direction; bool aligns; };
    const Row rows[] = {
        {"empty NVS", 0, CC_BOOT_CAL_NOT_SET, CC_BOOT_CAL_UNKNOWN, true},
        {"CW", 1, 2.5f, CC_BOOT_CAL_CW, false},
        {"CCW as int8", -1, 0.0f, CC_BOOT_CAL_CCW, false},
        {"CCW as byte", 255, 6.2831f, CC_BOOT_CAL_CCW, false},
        {"invalid byte 2", 2, 1.0f, CC_BOOT_CAL_UNKNOWN, true},
        {"invalid byte 128", 128, 1.0f, CC_BOOT_CAL_UNKNOWN, true},
        {"invalid byte -2", -2, 1.0f, CC_BOOT_CAL_UNKNOWN, true},
        {"NaN zero", 1, nan, CC_BOOT_CAL_UNKNOWN, true},
        {"infinite zero", 255, inf, CC_BOOT_CAL_UNKNOWN, true},
        {"negative zero angle", 1, -0.5f, CC_BOOT_CAL_UNKNOWN, true},
        {"zero past 2 pi", 1, 7.0f, CC_BOOT_CAL_UNKNOWN, true},
        {"direction without its zero", 1, CC_BOOT_CAL_NOT_SET, CC_BOOT_CAL_UNKNOWN, true},
        {"zero without its direction", 0, 3.0f, CC_BOOT_CAL_UNKNOWN, true},
    };
    for (const Row& r : rows) {
        const CCBootCal c = cc_cal_from_nvs(r.byte, r.zero);
        const bool aligns = c.direction == CC_BOOT_CAL_UNKNOWN || c.zero == CC_BOOT_CAL_NOT_SET;
        if (c.direction != r.direction || aligns != r.aligns) std::printf("  boot_cal row: %s\n", r.name);
        EXPECT(c.direction == r.direction && aligns == r.aligns);
        // Never half a calibration: unknown direction <-> zero NOT_SET; a known pair keeps its exact zero.
        EXPECT((c.direction == CC_BOOT_CAL_UNKNOWN) == (c.zero == CC_BOOT_CAL_NOT_SET));
        if (!r.aligns) EXPECT(c.zero == r.zero);
        // The boot: an alignment that succeeds stores a whole pair; one that fails (initResult 0) never stores.
        CCBootCal found;
        found.direction = CC_BOOT_CAL_CCW; found.zero = 4.25f;
        EXPECT(cc_boot_cal_store(c, aligns ? found : c, 1, true) == aligns);
        EXPECT(!cc_boot_cal_store(c, aligns ? found : c, 0, true));
    }
    // Either value changing stores (a re-aligned zero alone too); nothing changed, or a non-whole result, does not.
    CCBootCal a, b;
    a.direction = CC_BOOT_CAL_CW; a.zero = 1.0f;
    b = a; b.zero = 1.5f;
    EXPECT(cc_boot_cal_store(a, b, 1, true) && !cc_boot_cal_store(a, a, 1, true));
    b = a; b.direction = CC_BOOT_CAL_CCW;
    EXPECT(cc_boot_cal_store(a, b, 1, true));
    b = a; b.direction = CC_BOOT_CAL_UNKNOWN; b.zero = 2.0f;
    EXPECT(!cc_boot_cal_store(a, b, 1, true));
    b = a; b.zero = nan;
    EXPECT(!cc_boot_cal_store(a, b, 1, true));
}

// FW-PUB-006 boot_calibration_not_stored_when_pole_check_fails: a hand on the knob during the first-boot sweep
// (the shaft moves 0.5x, or 1.5x, the expected 2 pi / 7 per electrical turn): initFOC() still returns 1, but the pair
// is not stored (the next boot aligns again) and the state says UNSTORED; a clean sweep stores and says READY. The
// LCD's hands-off cue is up exactly while ALIGNING.
void boot_pole_tests() {
    const float expected = 2.0f * CC_HAPTIC_PI / 7.0f;
    CCBootCal empty = cc_cal_from_nvs(0, CC_BOOT_CAL_NOT_SET), found;
    found.direction = CC_BOOT_CAL_CW; found.zero = 3.1f;
    struct Row { float movedX; bool poleOk; bool stored; uint8_t state; };
    const Row rows[] = {{1.0f, true, true, CC_MOTOR_CAL_READY}, {0.5f, false, false, CC_MOTOR_CAL_UNSTORED},
                        {1.5f, false, false, CC_MOTOR_CAL_UNSTORED}, {0.95f, true, true, CC_MOTOR_CAL_READY},
                        {-1.0f, true, true, CC_MOTOR_CAL_READY}};
    for (const Row& r : rows) {
        const bool pole = cc_boot_pp_check(expected * r.movedX, 7);
        EXPECT(pole == r.poleOk);
        int stores = 0;   // the boot path: storeCalibration() only when cc_boot_cal_store() says so
        if (cc_boot_cal_store(empty, found, 1, pole)) ++stores;
        EXPECT((stores == 1) == r.stored);
        EXPECT(cc_boot_cal_outcome(1, true, pole) == r.state);
    }
    EXPECT(cc_boot_cal_outcome(0, true, true) == CC_MOTOR_CAL_FAILED && cc_boot_cal_outcome(1, false, false) == CC_MOTOR_CAL_READY);
    EXPECT(!cc_boot_cal_store(empty, found, 0, true) && !cc_boot_pp_check(1.0f, 0));
    EXPECT(cc_motor_cal_state() == CC_MOTOR_CAL_STARTING && !cc_motor_cal_hands_off());
    cc_motor_cal_post(CC_MOTOR_CAL_ALIGNING);
    EXPECT(cc_motor_cal_hands_off());
    cc_motor_cal_post(CC_MOTOR_CAL_UNSTORED);
    EXPECT(!cc_motor_cal_hands_off() && cc_motor_cal_state() == CC_MOTOR_CAL_UNSTORED);
    cc_motor_cal_post(CC_MOTOR_CAL_STARTING);
}

// FW-BUG-030 wake_does_not_enable_uncalibrated_motor: foc_thread.cpp's sleep glue (CCSleepFoc DISABLE / ENABLE) with
// a motor whose boot alignment failed (SimpleFOC motor_status calib_failed, driver disabled by initFOC()): the wake's
// ENABLE leaves the driver disabled and diag motorReady is false; a calibrated motor is enabled as before. The one
// boot retry runs after CC_BOOT_RETRY_IDLE_MS idle, once.
void boot_wake_tests() {
    enum Status { CALIB_FAILED, READY };
    for (int ready = 0; ready < 2; ++ready) {
        const Status status = ready ? READY : CALIB_FAILED;
        bool enabled = ready != 0;          // initFOC() disabled the driver on its failure
        int enables = 0;
        CCSleepFoc foc;
        uint32_t now = 0;
        const float angle = 0.0f;           // shaftAngle() of an uncalibrated motor: always 0
        foc.step(now, angle, false);
        now += 10;
        EXPECT(foc.step(now, angle, true).action == CC_SLEEP_MOTOR_DISABLE);
        enabled = false;
        now += kCCSleepDisableQuietMs + 10;
        foc.step(now, angle, true);         // asleep
        bool sawEnable = false;
        for (uint32_t t = 0; t < kCCSleepSettleMaxMs + 100 && !sawEnable; t += 10) {   // a button wake
            const CCSleepFocStep step = foc.step(now + t, angle, false);
            if (step.action == CC_SLEEP_MOTOR_ENABLE) {
                sawEnable = true;
                if (cc_motor_wake_enable(status == READY)) { enabled = true; ++enables; }
            }
        }
        EXPECT(sawEnable);
        const bool motorReady = status == READY;   // diag motorReady
        EXPECT(enabled == (ready != 0) && enables == ready && motorReady == (ready != 0));
    }
    CCBootRetry retry;
    EXPECT(!retry.step(100000, true, false) && !retry.pending());   // nothing failed: never
    retry.failed(0);
    EXPECT(retry.pending() && !retry.step(1000, true, false) && !retry.step(4000, false, false));   // a key: restarts
    EXPECT(!retry.step(4000 + CC_BOOT_RETRY_IDLE_MS - 1, true, false) &&
           retry.step(4000 + CC_BOOT_RETRY_IDLE_MS, true, false));
    EXPECT(retry.done() && !retry.pending() && !retry.step(60000, true, false));
    retry.failed(70000);                                       // a second failure is final: replug
    EXPECT(!retry.pending() && !retry.step(200000, true, false));

    // Review: the boot alignment failed, Desk Dial (claimed: never idle) runs a Recalibrate that succeeds inside one
    // blocked loop pass, then releases. On the next pass the knob is idle and > 5 s went by, but the motor is ready:
    // the retry never runs (it would re-sweep a just-calibrated motor and could undo it).
    {
        CCBootRetry r;
        r.failed(0);
        uint32_t t = 0;
        for (; t < 3000; t += 10) EXPECT(!r.step(t, false, false));   // claimed
        t += 8000;                                                    // recalibrate() blocks the loop, succeeds
        EXPECT(!r.step(t, true, true) && !r.pending() && r.done());
        for (; t < 600000; t += 10) EXPECT(!r.step(t, true, true) && !r.step(t, true, false));
        r.failed(t);                                                  // a later failure does not re-arm it
        EXPECT(!r.pending() && !r.step(t + 100000, true, false));
    }
    // A ready motor while the retry waits (any time): it never fires.
    for (uint32_t readyAt = 0; readyAt <= 2 * CC_BOOT_RETRY_IDLE_MS; readyAt += 250) {
        CCBootRetry r;
        r.failed(0);
        bool fired = false;
        for (uint32_t t = 0; t <= 4 * CC_BOOT_RETRY_IDLE_MS; t += 50) {
            const bool due = r.step(t, true, t >= readyAt);
            fired = fired || due;
            if (due) EXPECT(t < readyAt);
        }
        EXPECT(fired == (readyAt > CC_BOOT_RETRY_IDLE_MS));
    }
}

void misc_tests() {
    // The uint16 range fix (1.0.0-cc5.6's Onshape buzz): 0..65535 is 65536 positions, never 0.
    EXPECT(cc_positions(0, 65535) == 65536u && cc_positions(0, 0) == 1u && cc_positions(5, 4) == 1u && cc_positions(10, 20) == 11u);
    EXPECT(cc_scaled_position(8000, 10) == 65535u && cc_scaled_position(100, 10) == 1000u && cc_scaled_position(7, 0) == 7u);
    supply_tests();
    EXPECT(cc_cal_pole_check(0.8976f, 7) && !cc_cal_pole_check(0.4f, 7) && !cc_cal_pole_check(1.8f, 7) && cc_cal_pole_check(-0.9f, 7));
    // Effect words: each post is taken once, the newest wins.
    uint32_t seen = cc_haptic_detail::shared().fxWord;
    EXPECT(cc_fx_take(seen) == CC_HFX_NONE);
    cc_fx_post(CC_HFX_TICK);
    cc_fx_post(CC_HFX_THUMP);
    EXPECT(cc_fx_take(seen) == CC_HFX_THUMP && cc_fx_take(seen) == CC_HFX_NONE);
    cc_fx_post(CC_HFX_THUMP);
    EXPECT(cc_fx_take(seen) == CC_HFX_THUMP);   // the same token twice plays twice
    // hold.tension words.
    cc_hold_tension_post(1000, 600);
    EXPECT(near(cc_hold_tension_kd(1000), 0.0375, 1e-6) && near(cc_hold_tension_kd(1500), 0.12, 1e-6) &&
           cc_hold_tension_kd(1600) == 0.0f && near(cc_hold_tension_kd(900), 0.0375, 1e-6));
    cc_hold_tension_post(0, 0);
    EXPECT(cc_hold_tension_kd(1200) == 0.0f);
    // Recalibration requests move a counter; the accept flag rides on the word.
    const uint32_t before = cc_haptic_detail::shared().calRequest;
    cc_cal_request(false);
    const uint32_t one = cc_haptic_detail::shared().calRequest;
    cc_cal_request(true);
    const uint32_t two = cc_haptic_detail::shared().calRequest;
    EXPECT(one != before && (one & CC_CAL_ACCEPT_DIRECTION) == 0 && two != one && (two & CC_CAL_ACCEPT_DIRECTION) != 0);
    EXPECT(!std::strcmp(cc_cal_outcome_name(CC_CAL_FAIL_DIRECTION), "direction-changed") && !std::strcmp(cc_cal_state_name(CC_CAL_RUNNING), "running"));
    cc_offline_wanted_set(true);
    const int32_t steps = cc_offline_steps();
    cc_offline_step(3);
    cc_offline_step(-1);
    EXPECT(cc_offline_wanted() && cc_offline_steps() == steps + 2);
    // FW-BUG-042: a +1 and a -1 between two samples cancel in the signed sum but still count as motion.
    const int32_t signedBefore = cc_offline_steps();
    const uint32_t moves = cc_offline_moves();
    cc_offline_step(1);
    cc_offline_step(-1);
    EXPECT(cc_offline_steps() == signedBefore && cc_offline_moves() == moves + 2u);
    cc_offline_step(-3);
    cc_offline_step(0);
    EXPECT(cc_offline_moves() == moves + 5u && cc_offline_steps() == signedBefore - 3);
    cc_offline_step(3);
    cc_offline_wanted_set(false);
    EXPECT(!cc_offline_wanted());
}

// ---------------------------------------------------------------------------------------------------------- 7
void sound_tests() {
    static int16_t memory[CC_SOUND_BANK_SAMPLES];
    CCSoundBank bank;
    bank.render(memory);
    uint16_t len = 0;
    const int16_t* wood = bank.data(CC_SOUND_WOOD, len);
    EXPECT(wood && len == 110);
    int peak = 0;
    for (uint16_t i = 0; i < len; ++i) peak = std::max(peak, std::abs(static_cast<int>(wood[i])));
    EXPECT(peak > 10000 && peak <= 32000 && std::abs(static_cast<int>(wood[len - 1])) < 400);   // decayed by 5 ms
    const int16_t* thud = bank.data(CC_SOUND_THUD, len);
    EXPECT(thud && len == 1103);
    const int16_t* thump = bank.data(CC_SOUND_THUMP, len);
    int thumpPeak = 0;
    for (uint16_t i = 0; i < len; ++i) thumpPeak = std::max(thumpPeak, std::abs(static_cast<int>(thump[i])));
    EXPECT(thump && len == 882 && thumpPeak >= 29000 && thumpPeak <= 30000);   // normalised to a 30000 peak
    // 2026-09-30, by ear: the knob's speaker does not play 110 Hz, so the thump is 110 Hz's harmonics 2..6 (no
    // fundamental) over a 1.2 kHz attack: over the first 20 ms its 110 Hz DFT bin is far below the 220 Hz one.
    auto bin = [&](double hz) {
        double re = 0.0, im = 0.0;
        for (uint16_t i = 0; i < 441; ++i) {
            const double w = 2.0 * 3.14159265358979 * hz * i / CC_SOUND_RATE;
            re += thump[i] * std::cos(w); im += thump[i] * std::sin(w);
        }
        return std::sqrt(re * re + im * im);
    };
    EXPECT(bin(110.0) < 0.5 * bin(220.0));
    // The thud's body is 330 Hz (Karl's 100 Hz body did not play either).
    const int16_t* thudBody = bank.data(CC_SOUND_THUD, len);
    auto thudBin = [&](double hz) {
        double re = 0.0, im = 0.0;
        for (uint16_t i = 0; i < 882; ++i) {
            const double w = 2.0 * 3.14159265358979 * hz * i / CC_SOUND_RATE;
            re += thudBody[i] * std::cos(w); im += thudBody[i] * std::sin(w);
        }
        return std::sqrt(re * re + im * im);
    };
    EXPECT(thudBin(330.0) > 2.0 * thudBin(100.0));
    const int16_t* fine = bank.data(CC_SOUND_FINE, len);
    // The fine click is the tock at twice the pitch: more zero crossings in the same 5 ms.
    auto crossings = [](const int16_t* s, uint16_t n) { int c = 0; for (uint16_t i = 1; i < n; ++i) if ((s[i - 1] < 0) != (s[i] < 0)) ++c; return c; };
    EXPECT(fine && len == 110 && crossings(fine, 110) > crossings(wood, 110) * 3 / 2);
    EXPECT(!bank.data(CC_SOUND_NONE, len) && len == 0);
    // The master volume is a percent (soundVolume, 2026-09-30); the older `sound` levels map to 0 / 40 / 70 / 100.
    const CCSoundCue tock = {CC_SOUND_WOOD, 60, 1, 0}, thumpCue = {CC_SOUND_THUMP, 100, 1, 0};
    EXPECT(cc_sound_gain(tock, 0) == 0 && cc_sound_gain(tock, 50) == 30 && cc_sound_gain(tock, 100) == 60 &&
           cc_sound_gain(tock, 250) == 60 && cc_sound_gain(CC_SOUND_SILENT, 100) == 0);
    EXPECT(cc_sound_gain(thumpCue, 100) == 100 && cc_sound_gain(thumpCue, 1) == 1);          // 100 % = full scale
    EXPECT(cc_sound_volume_of_level(0) == 0 && cc_sound_volume_of_level(1) == 40 && cc_sound_volume_of_level(2) == 70 &&
           cc_sound_volume_of_level(3) == 100 && cc_sound_volume_of_level(4) == 0);
    EXPECT(cc_sound_level_of_volume(0) == 0 && cc_sound_level_of_volume(1) == 1 && cc_sound_level_of_volume(40) == 1 &&
           cc_sound_level_of_volume(41) == 2 && cc_sound_level_of_volume(70) == 2 && cc_sound_level_of_volume(71) == 3 &&
           cc_sound_level_of_volume(100) == 3);
    // The ring: the loudest wins (here also the newest); a full ring drops; the others are superseded.
    CCSoundRing ring;
    for (uint8_t i = 0; i < CC_SOUND_RING + 2; ++i) {
        CCSoundRequest r = {CC_SOUND_WOOD, static_cast<uint8_t>(i + 1), 1, 0};
        ring.push(r);
    }
    CCSoundRequest got;
    EXPECT(ring.dropped() == 2 && ring.popNext(got) && got.gain == CC_SOUND_RING && ring.empty() && !ring.popNext(got) &&
           ring.superseded() == CC_SOUND_RING - 1u);
    // FW-BUG-021: a press thump (gain 100) then a tock (gain 27) in one HMI wait: the thump plays, the tock is
    // superseded (it used to be the other way round, and the thump was lost uncounted).
    {
        CCSoundRing press;
        const CCSoundRequest pressThump = {CC_SOUND_THUMP, 100, 1, 0}, tock27 = {CC_SOUND_WOOD, 27, 1, 0};
        press.push(pressThump);
        press.push(tock27);
        CCSoundRequest next = {};
        EXPECT(press.popNext(next) && next.sound == CC_SOUND_THUMP && next.gain == 100 && press.superseded() == 1 &&
               press.dropped() == 0 && press.empty());
        // Equal gains (a spin): the newest of them still wins, after wrapping round the ring.
        for (uint8_t i = 0; i < 3 * CC_SOUND_RING; ++i) {
            const CCSoundRequest t = {CC_SOUND_WOOD, 27, static_cast<uint8_t>(i + 1), 0};
            press.push(t);
            if (i % 5 == 4) { EXPECT(press.popNext(next) && next.repeats == i + 1); }
        }
        EXPECT(press.popNext(next) && next.repeats == 3 * CC_SOUND_RING && press.empty());
        // A single waiting request is not superseded.
        const uint32_t before = press.superseded();
        press.push(tock27);
        EXPECT(press.popNext(next) && next.gain == 27 && press.superseded() == before);
    }
    // The voice: three tocks 30 ms apart; the gain scales; silence between.
    CCSoundVoice voice;
    CCSoundRequest refuse = {CC_SOUND_WOOD, 100, 3, 30};
    voice.start(refuse, bank);
    static int16_t out[CC_SOUND_RATE / 5];
    voice.render(out, CC_SOUND_RATE / 5);
    // An onset: a sample above 2000 after at least 40 exactly silent samples (the gap between plays).
    int onsets = 0, quiet = 1000;
    uint32_t second = 0;
    for (uint32_t i = 0; i < CC_SOUND_RATE / 5; ++i) {
        const int a = std::abs(static_cast<int>(out[i]));
        if (a > 2000 && quiet >= 40) { ++onsets; if (onsets == 2) second = i; }
        quiet = out[i] == 0 ? quiet + 1 : 0;
    }
    EXPECT(onsets == 3 && !voice.active() && near(static_cast<double>(second) / CC_SOUND_RATE, 0.030, 0.002));
    // Cut and restart only after 4 ms of the current sound.
    CCSoundVoice cut;
    CCSoundRequest thumpReq = {CC_SOUND_THUMP, 50, 1, 0};
    cut.start(thumpReq, bank);
    EXPECT(!cut.canRetrigger());
    cut.render(out, CC_SOUND_RETRIGGER_SAMPLES);
    EXPECT(cut.canRetrigger());
    CCSoundRequest half = {CC_SOUND_WOOD, 50, 1, 0};
    cut.start(half, bank);
    cut.render(out, 110);
    int top = 0;
    for (int i = 0; i < 110; ++i) top = std::max(top, std::abs(static_cast<int>(out[i])));
    EXPECT(top <= 16001 && top > 5000 && cut.played() == 2);
    cut.render(out, 10);
    EXPECT(!cut.active());
    // A silent request only stops the voice.
    CCSoundRequest none = {CC_SOUND_NONE, 50, 1, 0};
    cut.start(thumpReq, bank);
    cut.start(none, bank);
    EXPECT(!cut.active());
    // The underrun rule: only a sound already playing that finds the whole DMA free.
    // FW-BUG-018: counted against the depth the driver can refill (buf_cnt - 1 buffers, 320 frames), not the 384 of
    // the whole ring, which a write after the DMA ran dry never reaches.
    EXPECT(cc_sound_underrun(true, CC_SOUND_DMA_CAPACITY) && !cc_sound_underrun(false, CC_SOUND_DMA_CAPACITY) &&
           CC_SOUND_DMA_CAPACITY == 384 && CC_SOUND_DMA_WRITABLE == 320);
    EXPECT(cc_sound_underrun(true, 5 * 64) && !cc_sound_underrun(true, 4 * 64) && !cc_sound_underrun(false, 5 * 64) &&
           !cc_sound_underrun(true, CC_SOUND_DMA_WRITABLE - 1));
    // A model of audio_loop() against the IDF 4.4 writer: the DMA queue takes at most CC_SOUND_DMA_WRITABLE frames
    // and plays them out in real time. A thump with HMI passes every 3 ms never underruns; one pass delayed 20 ms
    // mid-sound (> 14.5 ms of queued audio) runs it dry and counts exactly one underrun.
    auto runWriter = [&](uint32_t delayedPass) {
        CCSoundVoice v;
        const CCSoundRequest thumpPlay = {CC_SOUND_THUMP, 100, 1, 0};
        static int16_t chunk[CC_SOUND_DMA_FRAMES];
        uint32_t queued = 0, pendingFrames = 0, underruns = 0;
        bool pending = false, started = false;
        for (uint32_t pass = 0; pass < 40; ++pass) {
            const uint32_t elapsedMs = pass == delayedPass ? 20u : 3u;
            const uint32_t playedOut = elapsedMs * CC_SOUND_RATE / 1000u;
            queued = queued > playedOut ? queued - playedOut : 0u;
            const bool playingBefore = v.active() || pending;
            if (!started) { v.start(thumpPlay, bank); started = true; }
            uint32_t accepted = 0;
            while (v.active() || pending) {
                if (!pending) { v.render(chunk, CC_SOUND_DMA_FRAMES); pendingFrames = CC_SOUND_DMA_FRAMES; pending = true; }
                const uint32_t room = CC_SOUND_DMA_WRITABLE - queued;
                const uint32_t frames = pendingFrames < room ? pendingFrames : room;
                queued += frames; accepted += frames; pendingFrames -= frames;
                if (pendingFrames == 0) pending = false;
                if (frames == 0) break;
            }
            if (cc_sound_underrun(playingBefore, accepted)) ++underruns;
        }
        return underruns;
    };
    EXPECT(runWriter(1000u) == 0u && runWriter(4u) == 1u);
}

// ---------------------------------------------------------------------------------------------------------- 8
void parse_cases(const char* path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) { EXPECT(false && "cases file"); return; }
    std::stringstream buffer;
    buffer << in.rdbuf();
    JsonDocument cases;
    if (deserializeJson(cases, buffer.str())) { EXPECT(false && "cases json"); return; }
    static CCFrame frame;
    int n = 0;
    for (JsonVariantConst c : cases.as<JsonArrayConst>()) {
        ++n;
        const bool ok = cc_parse_frame(c["frame"], frame);
        const bool want = c["accept"].as<bool>();
        if (ok != want) std::printf("  case %s: accept %d, expected %d\n", c["name"].as<const char*>(), ok, want);
        EXPECT(ok == want);
        if (ok && want) {
            const uint32_t fx = c["fx"].as<uint32_t>(), seq = c["seq"].as<uint32_t>();
            if (frame.hapticFx != fx || frame.hapticSeq != seq)
                std::printf("  case %s: fx %u seq %u, expected %u %u\n", c["name"].as<const char*>(), frame.hapticFx, frame.hapticSeq, fx, seq);
            EXPECT(frame.hapticFx == fx && frame.hapticSeq == seq);
        }
    }
    std::printf("haptic_fx_tests: %d haptic frame parity case(s)\n", n);
}
}  // namespace

// Rest sleep (2026-09-30: the knob buzzed faintly at rest; cc_haptic_fx.h CCRestGate).
void rest_tests() {
    const float deg = static_cast<float>(3.14159265358979 / 180.0);
    {   // Still on the detent: awake for CC_REST_IDLE_MS, then asleep (the output is zero).
        CCRestGate g;
        uint32_t t = 0;
        bool asleep = false;
        for (; t < 240000; t += 1000) asleep = g.step(t, 1.0f, 0.1f * deg, 0.2f, false);
        EXPECT(!asleep && !g.asleep());
        for (; t < 300000; t += 1000) asleep = g.step(t, 1.0f, 0.1f * deg, 0.2f, false);
        EXPECT(asleep && g.asleep() && g.sleeps() == 1);
        // Sensor noise (0.2 degrees, a moment of velocity noise) and a finger resting on the knob (1 degree) never
        // wake it.
        for (int i = 0; i < 100; ++i, t += 1000)
            EXPECT(g.step(t, 1.0f + (i % 2 ? 0.2f : -0.2f) * deg, 0.2f * deg, (i % 2 ? 3.0f : -3.0f), false));
        EXPECT(g.step(t, 1.0f + 1.0f * deg, 1.0f * deg, 1.0f, false));
        EXPECT(g.step(t, 1.0f + 2.0f * deg, 2.0f * deg, 1.0f, false));          // a firmer touch (2 degrees): still asleep
        // A 2.6 degree turn wakes it at once.
        EXPECT(!g.step(t, 1.0f + 2.6f * deg, 0.0f, 0.5f, false) && g.wakes() == 1);
    }
    {   // Anything playing wakes it, and keeps it awake.
        CCRestGate g;
        uint32_t t = 0;
        for (; t < 400000; t += 1000) g.step(t, 0.0f, 0.0f, 0.0f, false);
        EXPECT(g.asleep());
        EXPECT(!g.step(t, 0.0f, 0.0f, 0.0f, true) && g.wakes() == 1);
        for (t += 1000; t < 900000; t += 1000) EXPECT(!g.step(t, 0.0f, 0.0f, 0.0f, true));
    }
    {   // A new attractor (a re-anchor, a crossed detent) wakes it through the error, not the angle.
        CCRestGate g;
        uint32_t t = 0;
        for (; t < 400000; t += 1000) g.step(t, 0.0f, 0.0f, 0.0f, false);
        EXPECT(g.asleep() && !g.step(t, 0.0f, 3.0f * deg, 0.0f, false));
    }
    {   // Never asleep off the detent, while turning, or the idle time restarts after any motion.
        CCRestGate g;
        uint32_t t = 0;
        for (; t < 1000000; t += 1000) EXPECT(!g.step(t, 0.0f, 0.5f * deg, 0.0f, false));
        for (; t < 2000000; t += 1000) EXPECT(!g.step(t, 0.0f, 0.0f, 2.0f, false));
        for (; t < 2200000; t += 1000) g.step(t, 0.0f, 0.0f, 0.0f, false);   // 200 ms still: not yet asleep
        g.step(t, 0.0f, 0.0f, 5.0f, false);                      // a flick: the 250 ms start again
        for (t += 1000; t < 2440000; t += 1000) EXPECT(!g.step(t, 0.0f, 0.0f, 0.0f, false));
        for (; t < 2600000; t += 1000) g.step(t, 0.0f, 0.0f, 0.0f, false);
        EXPECT(g.asleep());
    }
}

// FW-BUG-003: {"R":...} register writes are allow-listed: only the voltage limit (0x50) and the recalibration (0x81).
void test_register_number_out_of_range_is_refused();
void register_tests() {
    int allowed = 0;
    for (int reg = 0; reg < 256; ++reg) {
        const bool ok = haptic_register_write_allowed(static_cast<uint8_t>(reg));
        if (ok) ++allowed;
        EXPECT(ok == (reg == 0x50 || reg == 0x81));
    }
    EXPECT(allowed == 2);
    // The writes the finding used: control mode, torque mode, velocity PID limit, phase resistance; and the supply /
    // raw phase voltage writes the old deny list refused.
    const uint8_t refused[] = {0x05, 0x06, 0x16, 0x33, 0x39, 0x51, 0x53, 0x55, 0x56, 0x60, 0x61, 0x63, 0x64};
    for (uint8_t reg : refused) EXPECT(!haptic_register_write_allowed(reg));
    test_register_number_out_of_range_is_refused();
}

// FW-BUG-035: {"R":...} numbers are range-checked, never truncated into a uint8_t (HapticCommander::handleMessage runs
// cc_reg_command_check() first and dispatches nothing when it refuses; operator>> uses cc_parse_ranged()).
void test_register_number_out_of_range_is_refused() {
    uint8_t reg = 7;
    // Aliases of 129 = REG_RECALIBRATE and 0x50 = REG_VOLTAGE_LIMIT: refused, the register untouched.
    const char* badRegister[] = {"385=1", "-127=1", "336=0.5", "256", "-1", "", "=1", "x=1", "129x=1", "99999999999999999999=1"};
    for (const char* cmd : badRegister) {
        reg = 7;
        const uint8_t r = cc_reg_command_check(cmd, reg);
        if (r != CC_REG_CMD_BAD_REGISTER) std::printf("  FW-BUG-035 \"%s\": %u\n", cmd, r);
        EXPECT(r == CC_REG_CMD_BAD_REGISTER && reg == 7);
    }
    // A recalibration value other than 0 / 1 (257 read as uint8_t 1 started one): refused.
    const char* badValue[] = {"129=257", "129=2", "129=-1", "129=", "129=x", "129=1x", "129=1.0"};
    for (const char* cmd : badValue) EXPECT(cc_reg_command_check(cmd, reg) == CC_REG_CMD_BAD_VALUE);
    // Still accepted: the recalibration, reads, the voltage limit write, any register 0..255 (the allow-list decides
    // what a write may change, this only stops aliasing).
    EXPECT(cc_reg_command_check("129=1", reg) == CC_REG_CMD_OK && reg == 129);
    EXPECT(cc_reg_command_check("129=0", reg) == CC_REG_CMD_OK && reg == 129);
    EXPECT(cc_reg_command_check("129", reg) == CC_REG_CMD_OK && reg == 129);
    EXPECT(cc_reg_command_check("80=1.5", reg) == CC_REG_CMD_OK && reg == 80);
    EXPECT(cc_reg_command_check("80", reg) == CC_REG_CMD_OK && reg == 80);
    EXPECT(cc_reg_command_check("0", reg) == CC_REG_CMD_OK && reg == 0);
    EXPECT(cc_reg_command_check("255=3", reg) == CC_REG_CMD_OK && reg == 255);
    EXPECT(cc_reg_command_check(" 5=1", reg) == CC_REG_CMD_OK && reg == 5);
    // The integer readers' range (operator>>): out of range leaves the value, in range reads it.
    long long v = 42;
    const char* end = nullptr;
    EXPECT(!cc_parse_ranged("256", 0, 255, v, end) && v == 42);
    EXPECT(!cc_parse_ranged("-1", 0, 255, v, end) && v == 42);
    EXPECT(!cc_parse_ranged("4294967296", 0, 0xFFFFFFFFLL, v, end) && v == 42);
    EXPECT(!cc_parse_ranged("abc", 0, 255, v, end) && v == 42);
    EXPECT(cc_parse_ranged("255,1", 0, 255, v, end) && v == 255 && *end == ',');
    EXPECT(cc_parse_ranged("4294967295", 0, 0xFFFFFFFFLL, v, end) && v == 4294967295LL);
}

// FW-SEC-001: the profile manager's slot rules (haptic_bounds.h), on a model of HapticProfileManager's slot array:
// get() / setCurrentProfile() / remove() / the "#all" answer exactly as HapticProfileManager.cpp uses the helpers.
struct SlotProfile { std::string profile_name; };
struct SlotManager {
    SlotProfile profiles[10];
    int current = -1;
    int get(const std::string& name) const { return haptic_profile_find(profiles, 10, name); }
    void setCurrent(const std::string& name) { const int i = get(name); if (i >= 0) current = i; }
    void remove(const std::string& name) {
        const int i = get(name);
        if (i < 0) return;
        profiles[i].profile_name.clear();
        if (current == i) { const int next = haptic_profile_next_named(profiles, 10, i); if (next >= 0) current = next; }
    }
    void rename(int i, const std::string& name) { if (haptic_profile_name_ok(name)) profiles[i].profile_name = name; }
    bool currentListed() const {   // the "#all" answer: current is one of the listed (named) profiles
        if (current < 0 || profiles[current].profile_name.empty()) return false;
        for (const SlotProfile& p : profiles) if (!p.profile_name.empty() && p.profile_name == profiles[current].profile_name) return true;
        return false;
    }
};
void test_empty_current_name_never_selects_a_blank_slot() {
    SlotManager m;
    m.profiles[0].profile_name = "A"; m.profiles[1].profile_name = "B"; m.profiles[3].profile_name = "C";
    m.setCurrent("A");
    EXPECT(m.current == 0 && m.currentListed());
    EXPECT(m.get("") == -1 && m.get("Z") == -1 && m.get("C") == 3);
    m.setCurrent("");                         // {"current":""}: keeps A
    EXPECT(m.current == 0 && m.currentListed());
    m.setCurrent("missing");                  // an unknown (or stale NVS) name keeps the current one
    EXPECT(m.current == 0);
    m.rename(0, "");                          // a rename to "" is refused: the slot keeps its name
    EXPECT(m.profiles[0].profile_name == "A" && m.currentListed());
    m.rename(0, std::string(17, 'x'));       // FW-BUG-005: 17 bytes overflow the 31-char SPIFFS path
    EXPECT(m.profiles[0].profile_name == "A");
    m.remove("A");                            // deleting the current profile moves to the next named one
    EXPECT(m.current == 1 && m.profiles[1].profile_name == "B" && m.currentListed());
    m.setCurrent("C");
    m.remove("C");                            // wraps round to the first named slot
    EXPECT(m.current == 1 && m.currentListed());
    m.remove("B");                            // nothing left: no named slot to move to
    EXPECT(haptic_profile_next_named(m.profiles, 10, 1) == -1);
    EXPECT(haptic_profile_name_ok(std::string("A")) && haptic_profile_name_ok(std::string(16, 'x')) &&
           !haptic_profile_name_ok(std::string()) && !haptic_profile_name_ok(std::string(17, 'x')) &&
           !haptic_profile_name_ok(std::string(20, 'x')));
    EXPECT(std::string("/profiles/").size() + 16 + std::string(".json").size() <= 31);   // the longest name's path fits
    EXPECT(haptic_profile_next_named(m.profiles, 10, -1) == -1);
    m.profiles[9].profile_name = "Z";
    EXPECT(haptic_profile_next_named(m.profiles, 10, -1) == 9 && haptic_profile_next_named(m.profiles, 10, 9) == 9);
}

// FW-BUG-027: haptic_profile_name_ok() refuses what ComThread::isProfileNameOk refuses: '/' and control bytes
// (< 0x20, 0x7F) besides the 1..16 byte length, so no rename path can make "/profiles/<a>/<b>.json" or a cut path.
void test_profile_name_refuses_slash_and_control_bytes() {
    EXPECT(haptic_profile_name_ok(std::string("Volume")) && haptic_profile_name_ok(std::string("a b-c_d.e~")) &&
           haptic_profile_name_ok(std::string("\xC3\xA9t\xC3\xA9")) && haptic_profile_name_ok(std::string(" ")));
    EXPECT(!haptic_profile_name_ok(std::string("a/b")) && !haptic_profile_name_ok(std::string("/")) &&
           !haptic_profile_name_ok(std::string("ab/")));
    EXPECT(!haptic_profile_name_ok(std::string("a\x01")) && !haptic_profile_name_ok(std::string("\x1F")) &&
           !haptic_profile_name_ok(std::string("a\tb")) && !haptic_profile_name_ok(std::string("a\nb")) &&
           !haptic_profile_name_ok(std::string("a\x7F")));
    EXPECT(!haptic_profile_name_ok(std::string("a\0b", 3)));           // an embedded NUL
    EXPECT(!haptic_profile_name_ok(std::string()) && !haptic_profile_name_ok(std::string(17, 'x')));
}

// FW-BUG-027: HapticProfile::operator= caps the description at 50 and the tag at 20 bytes (what the COM command
// accepts), cut at a UTF-8 character boundary, so a profile loaded from an older file cannot exceed them either.
void test_profile_desc_and_tag_are_capped() {
    EXPECT(kHapticProfileDescMaxBytes == 50 && kHapticProfileTagMaxBytes == 20);
    EXPECT(haptic_profile_text_keep(std::string(), 50) == 0);
    EXPECT(haptic_profile_text_keep(std::string(50, 'd'), 50) == 50);          // at the cap: kept whole
    EXPECT(haptic_profile_text_keep(std::string(51, 'd'), 50) == 50);
    EXPECT(haptic_profile_text_keep(std::string(400, 'd'), 50) == 50);
    EXPECT(haptic_profile_text_keep(std::string(20, 't'), 20) == 20);
    EXPECT(haptic_profile_text_keep(std::string(21, 't'), 20) == 20);
    // "e-acute" is 2 bytes: 19 ASCII + C3 A9 would cut between the bytes at 20, so 19 are kept.
    EXPECT(haptic_profile_text_keep(std::string(19, 'a') + "\xC3\xA9", 20) == 19);
    EXPECT(haptic_profile_text_keep(std::string(18, 'a') + "\xC3\xA9" + "z", 20) == 20);   // ends on a boundary
    // A 3-byte character (E2 82 AC) straddling the cap at 20 is dropped whole.
    EXPECT(haptic_profile_text_keep(std::string(18, 'a') + "\xE2\x82\xAC", 20) == 18);
    EXPECT(haptic_profile_text_keep(std::string(19, 'a') + "\xE2\x82\xAC", 20) == 19);
    // The model of operator=: an over-long update is cut, a short one kept.
    std::string desc = std::string(60, 'x');
    desc = desc.substr(0, haptic_profile_text_keep(desc, kHapticProfileDescMaxBytes));
    EXPECT(desc.size() == 50);
}

// FW-BUG-007: an effect posted with a control re-entry is felt once the control is ready. The FOC pass model: the
// output is held (move(0), no haptic loop, so no effect volts) while the applied control is not yet the input
// (reentry), CCFxIntake decides what plays, CCFxPlayer plays it in the passes that run the haptic loop.
void test_event_posted_while_entering_is_felt_after_ready() {
    const uint32_t holdMs = 60;   // measured enter -> ready 53-65 ms
    {   // The old order (take while held): the tick expired before the first ungated pass.
        CCFxPlayer old;
        CCSoundCue cue;
        EXPECT(old.start(CC_HFX_TICK, false, 0, 0.0f, false, cue));
        EXPECT(old.volts(holdMs * 1000u) == 0.0f);
    }
    uint32_t seen = cc_haptic_detail::shared().fxWord;
    CCFxIntake intake(seen);
    CCFxPlayer player;
    cc_fx_post(CC_HFX_TICK);                       // Desk Dial: the re-entry and its confirm.tick, one step
    int startedAt = -1;
    CCSoundCue startedCue = CC_SOUND_SILENT;
    float maxVolts = 0.0f;
    for (uint32_t ms = 0; ms < 300; ++ms) {
        const bool reentry = ms < holdMs;
        const uint8_t fx = intake.step(ms, false, reentry);
        if (fx != CC_HFX_NONE) {
            CCSoundCue cue;
            if (player.start(fx, false, ms * 1000u, 0.0f, false, cue)) { startedAt = static_cast<int>(ms); startedCue = cue; }
        }
        if (!reentry) for (uint32_t us = 0; us < 1000; us += 100) {   // the haptic loop's passes in this ms
            const float v = std::fabs(player.volts(ms * 1000u + us));
            if (v > maxVolts) maxVolts = v;
        }
    }
    EXPECT(startedAt == static_cast<int>(holdMs));          // the first ungated pass, never while held
    EXPECT(startedCue.sound != CC_SOUND_NONE && startedCue.level > 0);   // its sound posted in the same pass
    EXPECT(maxVolts > 0.1f);                                 // and the pulse is felt
    EXPECT(player.counters().played == 1);
    {   // Newest wins while held; a later pass sees nothing new.
        CCFxIntake in2(cc_haptic_detail::shared().fxWord);
        cc_fx_post(CC_HFX_TICK);
        EXPECT(in2.step(0, false, true) == CC_HFX_NONE && in2.waiting());
        cc_fx_post(CC_HFX_THUMP);
        EXPECT(in2.step(10, false, true) == CC_HFX_NONE);
        EXPECT(in2.step(20, false, false) == CC_HFX_THUMP && in2.step(21, false, false) == CC_HFX_NONE && !in2.waiting());
    }
    {   // A post held past CC_FX_DEFER_MAX_MS is dropped (no stale pulse), and one while discarding is dropped.
        CCFxIntake in3(cc_haptic_detail::shared().fxWord);
        cc_fx_post(CC_HFX_TICK);
        for (uint32_t ms = 1000; ms <= 1000 + CC_FX_DEFER_MAX_MS; ++ms) EXPECT(in3.step(ms, false, true) == CC_HFX_NONE);
        EXPECT(in3.step(1001 + CC_FX_DEFER_MAX_MS, false, true) == CC_HFX_NONE && !in3.waiting());
        EXPECT(in3.step(1002 + CC_FX_DEFER_MAX_MS, false, false) == CC_HFX_NONE);
        cc_fx_post(CC_HFX_TICK);
        EXPECT(in3.step(2000, true, false) == CC_HFX_NONE && in3.step(2001, false, false) == CC_HFX_NONE);
        cc_fx_post(CC_HFX_TICK);                   // ungated: plays at once, as before
        EXPECT(in3.step(2002, false, false) == CC_HFX_TICK);
    }
}

// FW-BUG-008: a native profile (handleHapticConfig(), unclaimed) is applied through rebase_runtime(profile,
// start_pos): the detent grid and the attractors sit at the shaft angle found, wherever the multi-turn angle has
// drifted. The old load (HapticState(profile): origin and attractors at angle 0) refused every turn on one side of 0
// and pulled the knob back towards 0 hands off. The legacy loop of the model (native haptics are the legacy loop).
namespace fw_bug_008 {
// handleHapticConfig() as the fix applies a profile: start_pos, the grid at the shaft (rebase); `atZero` = the old load.
void apply_native_profile(Knob& k, bool atZero) {
    k.setFeel(CC_FEEL_LEGACY, 60);              // default_profile: 60 detents, 0..255
    k.lo = 0; k.hi = 255; k.pos = 0;            // current_pos = start_pos
    k.atLimit = false;
    if (atZero) k.origin = k.attract = k.lastAttract = 0.0f;
    else k.origin = k.attract = k.lastAttract = static_cast<float>(k.theta);
}
// Turn by `detents` detents at 1 rad/s (the hand a velocity source), then let go for 0.5 s.
void turn(Knob& k, double detents) {
    const double v = detents > 0 ? 1.0 : -1.0;
    const int n = static_cast<int>(std::fabs(detents) * k.w / 1.0 / 60e-6);
    for (int i = 0; i < n; ++i) k.step(0.0, true, v);
    k.omega = 0.0;
    k.run(0.5);
}
}  // namespace fw_bug_008

void test_native_profile_switch_counts_from_any_shaft_angle() {
    using namespace fw_bug_008;
    const double angles[] = {3.0, -3.0, 12.0, -12.0, 20.0, -20.0};
    for (double a : angles) {
        {   // One detent up, then one down: exactly +1 and -1 from start_pos.
            Knob k;
            k.theta = a;
            apply_native_profile(k, false);
            k.run(0.2);
            EXPECT(k.pos == 0);
            turn(k, 1.0);
            const int up = k.pos;
            turn(k, -1.0);
            if (up != 1 || k.pos != 0) std::printf("  FW-BUG-008 shaft %.0f rad: up %d, back %d\n", a, up, k.pos);
            EXPECT(up == 1 && k.pos == 0);
        }
        {   // Hands off for 5 s: the knob stays on its detent (less than half a detent).
            Knob k;
            k.theta = a;
            apply_native_profile(k, false);
            k.run(5.0);
            EXPECT(std::fabs(k.theta - a) < 0.5 * k.w && k.pos == 0);
        }
    }
    {   // The model reproduces the finding with the old load: below 0 the knob spins itself back towards 0.
        Knob k;
        k.theta = -12.0;
        k.tripEnabled = false;
        apply_native_profile(k, true);
        k.run(5.0);
        EXPECT(std::fabs(k.theta + 12.0) > 10.0 * k.w);
    }
}

// FW-BUG-010: a slow turn in a pulsed feel (16-20 detents a second at 67 a turn) counts exactly as without pulses:
// a detent pulse never freezes the count, and the grid never drifts by float rounding (no phantom or backward step).
// Every counted step starts its pulse.
void test_slow_turn_with_detent_pulses_counts_every_detent() {
    const uint8_t feels[] = {CC_FEEL_VALUE, CC_FEEL_DIMMER, CC_FEEL_LIST, CC_FEEL_COARSE, CC_FEEL_FINE};
    const double speeds[] = {0.5, 1.0, 1.5, 1.9, -0.5, -1.0, -1.5, -1.9};
    for (uint8_t f : feels) {
        for (double v : speeds) {
            int finals[2] = {0, 0};
            Knob kept;
            for (int withPulses = 0; withPulses < 2; ++withPulses) {
                Knob k;
                k.theta = 7.3;                          // off zero: the grid's floats are not exact
                k.setFeel(f, 67);
                k.pos = 500;
                k.detentPulses = withPulses != 0;
                for (int i = 0; i < static_cast<int>(2.0 / 60e-6); ++i) k.step(0.0, true, v);
                for (int i = 0; i < static_cast<int>(0.3 / 60e-6); ++i) k.step(0.0, true, 0.0);
                finals[withPulses] = k.pos;
                if (withPulses) kept = k;
            }
            const int steps = v > 0 ? kept.posUps : kept.posDowns;
            const int backward = v > 0 ? kept.posDowns : kept.posUps;
            const uint32_t pulses = kept.fx.counters().pulses;
            if (finals[0] != finals[1] || backward != 0 || pulses != static_cast<uint32_t>(steps))
                std::printf("  FW-BUG-010 feel %s at %.1f rad/s: pos %d (no pulses %d), backward %d, pulses %u / %d steps\n",
                            cc_feel_name(f), v, finals[1], finals[0], backward, pulses, steps);
            EXPECT(finals[0] == finals[1] && finals[1] != 500);
            EXPECT(backward == 0);
            EXPECT(pulses == static_cast<uint32_t>(steps));
        }
    }
    // The player: a detent pulse never freezes, at any speed; an event from rest still does.
    CCSoundCue cue;
    CCFxPlayer a;
    EXPECT(a.start(CC_HFX_DETENT, false, 0, 0.0f, false, cue, 1, 15) && !a.frozen(1000));
    CCFxPlayer b;
    EXPECT(b.start(CC_HFX_DETENT, false, 0, 1.5f, false, cue, -1, 20) && !b.frozen(1000));
    CCFxPlayer c;
    EXPECT(c.start(CC_HFX_TICK, false, 0, 0.5f, false, cue) && c.frozen(1000));
    // The grid index: an attractor a few ulps off its detent is the same detent; the next one is not.
    const float w = static_cast<float>(2.0 * 3.14159265358979 / 67.0), origin = 7.3f;
    for (long i = -400; i <= 400; ++i) {
        const float a0 = cc_detent_angle(i, origin, w);
        EXPECT(cc_detent_index(a0, origin, w) == i);
        EXPECT(cc_detent_index(std::nextafter(a0, 1e9f), origin, w) == i && cc_detent_index(std::nextafter(a0, -1e9f), origin, w) == i);
        EXPECT(cc_detent_index(a0 + w, origin, w) == i + 1);
    }
}

// FW-BUG-038: HapticProfileManager::toSPIFFS() deletes every stored file that is not exactly a live profile's
// "<name>.json" (haptic_profile_file_kept), so a deleted or renamed profile never comes back on the next boot.
void test_deleted_profile_with_suffix_name_is_removed() {
    SlotProfile live[10];
    live[2].profile_name = "Volume";
    // The deletion pass of toSPIFFS(), on the stored files' names (file.name(): a base name, or a path on older cores).
    const char* files[] = {"Master Volume.json", "Volume.json", "/profiles/Master Volume.json", "/profiles/Volume.json",
                           "MyVolume.json", "Volume.json.json", "Volume", ".json"};
    const bool kept[] = {false, true, false, true, false, false, false, false};
    for (size_t i = 0; i < sizeof(files) / sizeof(files[0]); ++i) {
        const bool k = haptic_profile_file_kept(live, 10, files[i]);
        if (k != kept[i]) std::printf("  FW-BUG-038 \"%s\": kept %d\n", files[i], k ? 1 : 0);
        EXPECT(k == kept[i]);
    }
    // A rename of "Master Volume" to "Volume 2": the old file goes, the new one stays.
    live[0].profile_name = "Volume 2";
    EXPECT(!haptic_profile_file_kept(live, 10, "Master Volume.json") && haptic_profile_file_kept(live, 10, "Volume 2.json") &&
           haptic_profile_file_kept(live, 10, "Volume.json"));
    // Free slots ("") never keep a file, not even ".json".
    SlotProfile none[10];
    EXPECT(!haptic_profile_file_kept(none, 10, ".json") && !haptic_profile_file_kept(none, 10, "Volume.json"));
    EXPECT(haptic_profile_file_is("A.json", "A") && !haptic_profile_file_is("A.json", "") &&
           !haptic_profile_file_is(nullptr, "A") && !haptic_profile_file_is("BA.json", "A"));
}

// FW-BUG-034: HapticState::load_profile()'s position (haptic_bounds.h haptic_load_position()). Every constructor
// (rebase_runtime(), a native profile, a restored one) passes its position with hasPosition set, so 65535 on a
// 0..65535 control is 65535 (the in-band 0xFFFF sentinel loaded it as the fresh state's 0: ready p 0). Without a
// position, the current one is clamped to the scaled bounds detent_handler() counts against (VERNIER included).
void test_rebase_keeps_position_65535() {
    EXPECT(haptic_load_position(true, 65535, 0, 0, 65535) == 65535);
    EXPECT(haptic_load_position(true, 65535, 0, 0, 60000) == 65535);   // a position is taken as given (host-validated)
    EXPECT(haptic_load_position(true, 0, 400, 0, 65535) == 0);
    EXPECT(haptic_load_position(true, 1234, 0, 0, 65535) == 1234);
    // No position: the current one kept inside the bounds.
    EXPECT(haptic_load_position(false, 0xFFFF, 500, 0, 1000) == 500);
    EXPECT(haptic_load_position(false, 0xFFFF, 5, 10, 20) == 10);
    EXPECT(haptic_load_position(false, 0xFFFF, 50, 10, 20) == 20);
    // VERNIER (start 0, end 120, vernier 10): the bounds are 0..1200, so position 900 stays 900 (it was clamped to the
    // unscaled 120).
    EXPECT(haptic_load_position(false, 0xFFFF, 900, cc_scaled_position(0, 10), cc_scaled_position(120, 10)) == 900);
    EXPECT(haptic_load_position(false, 0xFFFF, 1500, cc_scaled_position(0, 10), cc_scaled_position(120, 10)) == 1200);
}

// FW-BUG-033: an effect that starts during a slow fluid turn (< 2 rad/s: Onshape orbit / pan / tilt, Seek) freezes the
// count; at the freeze end the knob is still below 2 rad/s, and the viscous end_freeze() moved the grid by the whole
// shaft movement, the hand's turn included: a count lost per tick, 3-4 per error.buzz. Only a shift within the pulses'
// displacement bound (cc_freeze_absorbs()) moves the grid; a turn is counted. The hand is a velocity source here, so
// the effect cannot move the shaft: the count must equal the effect-free run.
void test_fluid_turn_with_effect_counts_every_detent() {
    CCSoundCue cue;
    const uint8_t feels[] = {CC_FEEL_LIGHT, CC_FEEL_SCRUB};
    const uint8_t events[] = {CC_HFX_TICK, CC_HFX_THUMP, CC_HFX_ERROR};
    const double speeds[] = {0.5, 1.0, 1.9, -1.0};
    for (uint8_t f : feels) {
        for (double speed : speeds) {
            for (uint8_t e : events) {
                int counts[2] = {0, 0};
                for (int withFx = 0; withFx < 2; ++withFx) {
                    Knob k;
                    k.setFeel(f, 67);
                    k.pos = 500;
                    const int n = static_cast<int>(1.5 / 60e-6);
                    for (int i = 0; i < n; ++i) {
                        // Two effects mid-turn (the velocity filter has settled at the hand's speed by then).
                        if (withFx && (i == n / 3 || i == (2 * n) / 3)) {
                            EXPECT(k.fx.start(e, false, k.now, static_cast<float>(k.lpf), false, cue));
                            EXPECT(k.fx.frozen(k.now));      // it starts below 2 rad/s: the count freezes
                        }
                        k.step(0.0, true, speed);
                    }
                    counts[withFx] = k.pos - 500;
                }
                if (counts[0] != counts[1])
                    std::printf("  FW-BUG-033 %s at %.1f rad/s with %s: %d counts, %d without the effect\n", cc_feel_name(f),
                                speed, cc_fx_name(e), counts[1], counts[0]);
                EXPECT(counts[0] == counts[1] && counts[0] != 0);
            }
        }
    }
    // The pulses' own displacement is still absorbed: a still knob takes repeated nudges in one direction without a
    // phantom count (the grid follows the pulses), and the rule itself.
    for (uint8_t f : feels) {
        Knob k;
        k.setFeel(f, 67);
        k.pos = 500;
        k.run(0.05);
        for (int r = 0; r < 12; ++r) {
            EXPECT(k.fx.start(CC_HFX_NUDGE_RIGHT, false, k.now, static_cast<float>(k.lpf), false, cue));
            k.run(0.4);
        }
        if (k.pos != 500) std::printf("  FW-BUG-033 %s: 12 nudges at rest moved the position to %d\n", cc_feel_name(f), k.pos);
        EXPECT(k.pos == 500);
    }
    // The rule: at rest the whole pulse displacement; a steady turn absorbs nothing of the hand's part; bounded; none
    // outside a viscous feel or at the freeze speed.
    const float w = static_cast<float>(2.0 * 3.14159265358979 / 67.0);
    EXPECT(near(cc_freeze_absorb(true, 0.0f, 0.0f, 0.2f, 0.4f * w, w), 0.4f * w, 1e-6));
    EXPECT(near(cc_freeze_absorb(true, 1.0f, 1.0f, 0.2f, 0.2f, w), 0.0, 1e-6));
    EXPECT(near(cc_freeze_absorb(true, -1.0f, -1.0f, 0.2f, -0.2f + 0.3f * w, w), 0.3f * w, 1e-5));
    EXPECT(near(cc_freeze_absorb(true, 0.0f, 0.0f, 0.2f, 3.0f * w, w), CC_HFX_ABSORB_DETENTS * w, 1e-6));
    EXPECT(cc_freeze_absorb(true, 2.5f, 2.5f, 0.2f, 0.5f, w) == 0.0f && cc_freeze_absorb(false, 0.0f, 0.0f, 0.2f, 0.01f, w) == 0.0f);
}

// FW-BUG-037: feel.fade is cleared once complete (CCFeelFade), so the factor stays 1 when micros() wraps 2^32 us
// (71.6 min) past the fade's start without a restart; it ramped 0 -> 1 again then (the spring and the wall vanished).
void fade_wrap_tests() {
    const uint32_t starts[] = {0u, 1000u, 0xFFFFF000u};
    for (uint32_t start : starts) {
        CCFeelFade f;
        EXPECT(f.factor(start) == 1.0f && !f.fading());                // never started: no fade
        f.start(CC_FEEL_FADE_MS, start);
        EXPECT(f.fading() && f.factor(start) == 0.0f);
        EXPECT(near(f.factor(start + 60000u), 0.5, 1e-6));
        EXPECT(f.factor(start + 120001u) == 1.0f && !f.fading());      // complete: cleared
        EXPECT(f.factor(start + 0xFFFFFFF5u) == 1.0f);
        EXPECT(f.factor(start + 1000u) == 1.0f);                       // start + 2^32 + 1000 us (wrapped)
        EXPECT(f.factor(start + 60000u) == 1.0f);
        // A restart fades again, from its own start.
        f.start(CC_FEEL_WAKE_FADE_MS, start + 5000u);
        EXPECT(f.factor(start + 5000u) == 0.0f && near(f.factor(start + 80000u), 0.5, 1e-6));
        EXPECT(f.factor(start + 155000u) == 1.0f && !f.fading());
        // A zero-length start is no fade (set_feel() in the legacy loop).
        f.start(0, start);
        EXPECT(f.factor(start) == 1.0f && !f.fading());
    }
    // A pass that lands exactly on the end, or long after it, completes the fade.
    CCFeelFade g;
    g.start(CC_FEEL_FADE_MS, 7u);
    EXPECT(g.factor(7u + 120000u) == 1.0f && !g.fading());
    g.start(CC_FEEL_FADE_MS, 7u);
    EXPECT(g.factor(7u + 0x80000000u) == 1.0f && !g.fading() && g.factor(7u + 10u) == 1.0f);
}

int main(int argc, char** argv) {
    fade_wrap_tests();
    test_fluid_turn_with_effect_counts_every_detent();
    test_rebase_keeps_position_65535();
    test_deleted_profile_with_suffix_name_is_removed();
    test_native_profile_switch_counts_from_any_shaft_angle();
    test_slow_turn_with_detent_pulses_counts_every_detent();
    token_tests();
    law_tests();
    effect_tests();
    model_tests();
    foldback_tests();
    trip_tests();
    test_cal_direction_rule_ignores_cleared_trip();
    test_app_angle_word_wraps();
    test_foc_reseed_after_motor_driven_motion();
    cal_handshake_tests();
    test_successful_recalibration_clears_trip_latch();
    misc_tests();
    boot_cal_tests();
    boot_pole_tests();
    boot_wake_tests();
    sound_tests();
    rest_tests();
    wall_rest_tests();
    bound_push_thud_and_force_coincide();
    register_tests();
    test_empty_current_name_never_selects_a_blank_slot();
    test_profile_name_refuses_slash_and_control_bytes();
    test_profile_desc_and_tag_are_capped();
    test_event_posted_while_entering_is_felt_after_ready();
    if (argc > 1) parse_cases(argv[1]);
    std::printf("haptic_fx_tests: %d check(s), %d failure(s)\n", checks, failures);
    return failures ? 1 : 0;
}
