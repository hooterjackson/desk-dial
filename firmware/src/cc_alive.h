#pragma once
#include <stdint.h>
#include "cc_presentation.h"
#include "cc_lights.h"

// "Warm · alive" LED engine (ALIVE.md revision 2, 1.0.0-cc5.4): the choreography of the Claude
// Design handoff design_handoff_led_choreography/ (RC) and of the r2.1 master's "Browse and Snap"
// (BS) on the alive ring geometry of ALIVE.md section 5. Python twin: control_center/alive_lights.py
// (float64).
//
// Platform-neutral (no Arduino/FastLED/ESP-IDF), C++11 and float32 (the ESP32-S3
// FPU is single precision: float math only, no heap). Compiled unchanged by the
// firmware, by harness/alive_tests.py (MSVC /W4 /WX) and by
// cpp11_gate.py (gnu++11). Every table is a namespace-scope constexpr.
//
// Three layers (ALIVE.md section 4), each testable on its own:
// 1. Targets  cc_alive_targets(): the frame (with the local cursor applied) to
//    per-segment / per-button (colour role, class, alpha) and the animator flags
//    (sections 5, 6.3). Revision 2 draws the alive geometry directly (the M13 half-step,
//    the M2 value gate, the re-centred window M9 / M15, lists M3, Up next M14, the Seek lap).
// 2. Animator CCAliveAnimator: RC draw() plus BS draw()'s new and changed recipes (bloom in a
//    colour, half, scatter, the stationary fail), ported verbatim: damping, the effect queue,
//    the continuous layers, compose and the tone map (sections 7, 8). Outputs e in 0..1 design
//    space. Its play()/step() pair is also the oracle test entry (both oracles, 11.1 / 11.2).
// 3. Output   cc_alive_output(): sRGB EOTF, drive, power limit and quantisation to 0xRRGGBB
//    (section 9): dither off by default with the F-T brightness floor on target-lit LEDs, the
//    temporal dither only on request (ledDither:true; the 2026-09-26 user ruling, 12.7).
// CCAlive owns the three layers plus the event detection of section 6.
//
// Conventions (as cc_lights.h): frame and accent colours are 0xRRGGBB; the
// palette is float design space (section 2); ring arrays are LOGICAL (segment 0
// at twelve o'clock, clockwise; cc_ring_address() maps them to the wire);
// buttons are the frame's slots, left to right. Times are uint32 ms and every
// elapsed time is (uint32_t)(now - start), so the millis() wrap is harmless.
//
// Lead rulings of ALIVE.md section 12 this engine implements: R1 (6.1 pending
// excludes activity offline, D15), R2 (the 5.4 tint needs an ACCENT cursor), R3
// (the song hand needs the last Home frame's playing == true; absent = not
// playing), R5 (the float palette below, B = 16920), R6 (one 'down' snapshot per
// queue slot), D19 (tick length round(x + 1e-4)), the master additions M1-M31 that concern the
// engine (12.3), [r2.2] M32 (the liked heart PINK 0.30, `unlike` reserved) and M33 (the Working
// comet reads seek- / play-next-in-flight as activity pending; nothing new in the engine), and
// Q1 (12.5: the End stop on every push, in CCAliveKnob).
//
// Presentation 6 (ALIVE.md section 15, Desk Dial r3 release 1): the family LIGHTS (layouts lights, lightsbig,
// scenes), the ring styles bri / ctemp / clusters on the r3 arc (45 segments from 38 clockwise through the top
// to 22; 23..37 stay free), the Kelvin colour as an ACCENT drawn as is (never sat(), no WARM fallback, no
// volume amber / red, no near-max embers), the classes T / R / O / L / F, the LIGHTS ok = a 700 ms green
// wash of the whole ring (CC_FLASH_WASH) and the active-mode button (lit on) at 0.90 in LIGHTS.

// ------------------------------------------------------------------ constants
namespace CCAliveSpec {
// Palette (section 2, [R5]): design space, 0..1 per channel, before the section 9
// transfer. WARM and AMBER are the sRGB OETF (the exact inverse of the section 9
// EOTF) of the LED colours the user picked on the hardware on 2026-09-25, c = LED/255:
// c <= 0.0031308 ? 12.92 c : 1.055 c^(1/2.4) - 0.055. Stored as floats (>= 6
// significant digits), never as rounded 8-bit ints (those miss the picks by one
// count) and never re-derived at run time. At drive 255 with dither off, section 9
// maps WARM to #FF8424 and AMBER to #FF3A0A exactly (alive_tests.cpp outputChecks).
constexpr float warm[3] = {1.0f, 0.746862f, 0.411645f};      // [user][D1] fixed all day: LED #FF8424
// [user 2026-09-26] chases, song hand and accents use the same warm white (was mix(WARM, white, 0.5)).
constexpr float hot[3] = {1.0f, 0.746862f, 0.411645f};       // == WARM
constexpr float green[3] = {0.0f, 1.0f, 98.0f / 255.0f};     // confirm
constexpr float red[3] = {1.0f, 0.0f, 0.0f};                 // [user][D2] >= 90 %, Cancel, Fail: #FF0000
constexpr float amber[3] = {1.0f, 0.514232f, 0.218649f};     // [user][D2] 80-90 %, offline marks: #FF3A0A
constexpr float blue[3] = {40.0f / 255.0f, 140.0f / 255.0f, 1.0f};   // changed elsewhere
// [r2][M25] PINK (the liked heart, the Like bloom): its own role, never sat(); the candidate
// 255,40,90 (section 14 Q2), LED output at full ~ #FF051A. setTuning() replaces it at run time.
// [r2.2][M32] the liked heart button draws it at buttonLiked (0.30), the Like bloom at full.
constexpr float pink[3] = {1.0f, 40.0f / 255.0f, 90.0f / 255.0f};
constexpr uint8_t satMinSpread = 30;        // sat(): max - min below this -> WARM

// Section 5.2 alpha per CCAliveClass (none, 1, 2, S, 3, 4, P, N, Q). [r2][M1] the semantic body
// (class 2) and half-step (S) are 0.62 / 0.81 like warm; ledVolFull restores AL's 1.00.
// [r3] (15.3) T 0.08, R 0.12 (unused since the user ruling of 2026-09-29: the unfilled arc is off; kept, append-only), O 0.18 (clusters not selected), L 0.34 (bri
// filled at rest), F 0.50 (ctemp filled at rest): the same in both tables (the Kelvin cells are ACCENT).
// [r3] (15.7) M 0.10: the r3 marker ring's rest of the arc (the Windows ring, README r3 section 3).
// [r3.1] (15.9) W 0.60: the queue ring's playing row (warm white); it rests at 0.34 like every lit mark.
constexpr float alphaAwakeWarm[16] = {0.0f, 0.30f, 0.62f, 0.81f, 1.00f, 1.00f, 0.14f, 0.70f, 0.45f,
                                      0.08f, 0.12f, 0.18f, 0.34f, 0.50f, 0.10f, 0.60f};
constexpr float alphaAwakeSemantic[16] = {0.0f, 0.45f, 0.62f, 0.81f, 1.00f, 1.00f, 0.14f, 0.70f, 0.45f,
                                          0.08f, 0.12f, 0.18f, 0.34f, 0.50f, 0.10f, 0.60f};
constexpr float alphaVolFull = 1.00f;       // [M24] semantic class 2 / S with ledVolFull
// Resting: BS's thresholds (>= 0.99 -> 0.16, >= 0.5 -> 0.10, else 0.05) except S (D10: 0.13).
// [user 2026-09-26] resting = one steady dim warm white. 0.34 keeps ~(8..11, 5..6, 1..2) counts at drive 150,
// enough for the LEDs to show the warm hue (0.05-0.16 gave 0-3 counts, which shifted colour).
// [r3] (15.3) resting keeps the one steady warm white: L and F (the filled arc) rest at 0.34 like every other
// lit class; T, R and O (the unfilled track, the ctemp remainder, the scenes not selected) rest dark, so the
// resting ring still reads as the level / the selected scene.
constexpr float alphaResting[16] = {0.0f, 0.34f, 0.34f, 0.34f, 0.34f, 0.34f, 0.34f, 0.34f, 0.34f,
                                    0.0f, 0.0f, 0.0f, 0.34f, 0.34f, 0.0f, 0.34f};
constexpr float restTodMin = 0.80f;         // time of day dims resting, never below this (hue floor)
constexpr float alphaOverride = 1.0f;       // external / flash |k| <= 1
constexpr float alphaFlashEdge = 0.5f;      // flash |k| == 2
constexpr float alphaOffline = 0.12f;       // amber marks at 0, 5, ... 55
constexpr uint8_t offlinePitch = 5;
// Section 5.3 button alphas ([r2] on 1.0, off 0.30; [r2.2][M32] the liked heart PINK 0.30, row 4)
// and the [M18] resting rule (the liked heart, below the split, rests at WARM 0.04).
constexpr float buttonNav = 0.70f, buttonDim = 0.14f, buttonGo = 1.0f, buttonStop = 1.0f;
constexpr float buttonOn = 1.0f, buttonOff = 0.30f, buttonLiked = 0.30f;
constexpr float buttonRestHigh = 0.34f, buttonRestLow = 0.26f, buttonRestSplit = 0.5f;   // [user 2026-09-26]
// [r3] (15.4) README r3 section 3 "active mode warm L 0.9": a lit-on button of the LIGHTS family.
constexpr float buttonActive = 0.90f;

// [r3] (15.2) the Lights arc: 45 segments clockwise from 38 (7:30) through the top to 22; clusters: 3 each.
constexpr uint8_t arcStart = 38, arcLength = 45, clusterWidth = 3;
// [r3] (15.5) LIGHTS ok: the whole ring GREEN at 0.68 for 700 ms (README r3 section 3 "Scene ran").
constexpr uint32_t lightsWashMs = 700;
constexpr float lightsWashAlpha = 0.68f;
// [r3] (15.7, README r3 sections 1 and 3) the unavailable press: segments 26..34 RED 0.9 for 320 ms (no fail
// shake); the matured hold 1: the whole ring WARM 0.68 for 400 ms; the hold-1 progress ring: the r3 arc fills
// WARM (class 4, 1.0) 0 -> 45 over the 600 ms hold, shown from 12 %, on a frame with a crumb only.
// r4 (design_handoff_nano_d_r4 README 3.4, ALIVE.md 16): the deny glow is 480 ms in 255,60,40 (was 320 ms RED).
constexpr uint32_t refusedFlashMs = 480;
constexpr uint32_t refusedRgb = 0xFF3C28u;
constexpr float refusedAlpha = 0.9f;
constexpr uint8_t refusedFirst = 26, refusedLast = 34;
constexpr uint32_t homeFlashMs = 400;
constexpr float homeFlashAlpha = 0.68f;
constexpr uint32_t holdRingMs = 600, holdShowPct = 12;
// Desk Dial r3.1: the button-4 hold ring. While physical slot 3 is held (enabled on the frame, any screen incl.
// the launcher Home), the same r3 arc fills WARM 0 -> 45 over the 1000 ms hold (the kh of every button but
// slot 0), shown from 12 %, then (once) the same WARM home flash; the release cancels it.
constexpr uint32_t hold4RingMs = 1000;
// [r3.1] design delta (r3.1 prototype L922-924, L667-672): the button-4 ring shows from 15 % (150 ms), only on a
// frame with holdMarker; at 1000 ms the full arc waits (<= 600 ms) for the host's landing: the first new feedback
// seq within 1500 ms of the maturity lands it. A plain ok is CC_FLASH_LAND (the whole ring 0.68 for 450 ms in the
// Kelvin colour of a bri / ctemp frame, else WARM: the Home domain swap), ok + moment queued is CC_FLASH_QUEUE
// (the whole ring GREEN 0.68 for 600 ms, instead of the queued sweep). Anything else lands as usual.
constexpr uint32_t hold4ShowPct = 15;
constexpr uint32_t landingWindowMs = 1500, landingWaitMs = 600;
// r4 M12: a plain-ok landing is the domain-swap sweep (no wash); landFlashMs is its window (the prototype's 800 ms).
constexpr uint32_t landFlashMs = 800, queueFlashMs = 600;
constexpr float landFlashAlpha = 0.68f;
// [r3.1] (15.9) the queue ring's playing row: warm white 255,232,205 (the r3.1 prototype's WW).
constexpr uint32_t queueNowRgb = 0xFFE8CDu;
// [r3] (15.7) the marker ring: a white marker (240,240,240) +-1 on the arc, the rest class M.
constexpr uint32_t markerRgb = 0xF0F0F0u;

// Section 6 timing (ms).
constexpr uint32_t sleepInputMs = 5000;
constexpr uint32_t sleepExternalMs = 3200;
constexpr uint32_t sleepRecheckMs = 1000;
constexpr uint32_t maxFrameGapMs = 50;       // dt = min(50, now - lastRender)
constexpr uint32_t velocityGapMs = 400;      // spin velocity resets after this gap
constexpr uint32_t velocityMinMs = 16;
// [D19] Tick length len = round(x + tickTieBias), x = clamp((vel - 4)/14) * 7. Integer-ms detent
// gaps make exact .5 ties routine (a detent 90 ms after a rest: vel = 450/90 = 5, x = 0.5); they
// round half up as Math.round does in exact arithmetic. The bias absorbs the float32 (knob) /
// float64 (desktop) accumulation error so both ports agree (found by the 11.3 twin replay).
// Side effect, part of D19: a pre-round value within 1e-4 below a tie also rounds up.
constexpr float tickTieBias = 1.0e-4f;
// [r2][M22] a feedback moment holds sleep for its effect's nominal duration (6.4 rows c-h).
constexpr uint16_t holdQueuedMs = 640, holdShuffleMs = 700, holdLikeMs = 900, holdSnapMs = 900;
constexpr uint16_t holdStartedWashMs = 1100, holdStartedBloomMs = 900;

// Section 7: effect durations (ms), indexed by CCAliveEffectType; pending is
// the design's own (never started by the engine, kept for the oracle). [r2] half 900, scatter 700.
constexpr uint16_t durations[17] = {2800, 1800, 520, 180, 460, 2800, 900, 700, 640, 760, 860, 1000, 1100, 450, 220,
                                    900, 700};
// Foreground set (boot, down, bloom, fail, sweep, fill, drain, shimmer, wash, [r2] half, scatter).
constexpr bool foreground[17] = {true, true, false, false, false, false, true, true, true, true, true, true, true,
                                 false, false, true, true};
constexpr uint8_t queueCapacity = 8;         // [D12]
constexpr float killFadeMs = 120.0f;
constexpr float duckDepth = 0.35f;
// [r2][M5] scatter: r2.1's spread (BS:657), one xorshift32 per engine seeded in reset().
constexpr uint8_t scatterOrder[9] = {0, 4, 8, 3, 7, 2, 6, 1, 5};
constexpr float scatterStepMs = 55.0f, scatterBumpMs = 260.0f;
constexpr uint32_t rngSeed = 0x2545F491u;
// [r2][M23] half: segment k (1..29) lights when 20|k - 15| <= min(ms, 300) + 10.
constexpr int halfGrowMs = 300;
constexpr float halfHoldMs = 380.0f, halfFadeMs = 520.0f;
// [r2] 5.1.6 the Seek lap: unplayed ticks every 5th segment.
constexpr uint8_t lapTick = 5;

// Section 8.2 damping time constants (ms).
constexpr float tauRingAsleepUp = 400.0f, tauRingAsleepDown = 700.0f;
constexpr float tauRingCursorUp = 10.0f, tauRingUp = 55.0f, tauRingDown = 140.0f;
constexpr float tauButtonAsleepUp = 400.0f, tauButtonAsleepDown = 700.0f;
constexpr float tauButtonUp = 40.0f, tauButtonDown = 160.0f;
constexpr float tauColour = 70.0f, tauColourSnap = 1.0f, colourSnapBelow = 0.02f;
constexpr float tauTint = 220.0f;
constexpr float cursorTargetAt = 0.9f;       // awake ring target >= 0.9 rises with tauRingCursorUp
// Periods (ms) for the integer-modulo phases [D11].
constexpr uint32_t restBreathMs = 5200, offlineBreathMs = 2600, pausedPlayMs = 2600, workingLapMs = 1400;
// Near-max ember periods P_i = round(2*pi*(380 + (i*97 mod 260))) [D11].
constexpr uint16_t heatPeriodMs[60] = {
    2388, 2997, 3607, 2582, 3192, 3801, 2777, 3387, 3996, 2972, 3581, 2557, 3167, 3776, 2752,
    3362, 3971, 2947, 3556, 2532, 3142, 3751, 2727, 3336, 3946, 2922, 3531, 2507, 3116, 3726,
    2702, 3311, 3921, 2897, 3506, 2482, 3091, 3701, 2677, 3286, 3896, 2871, 3481, 2457, 3066,
    3676, 2652, 3261, 3870, 2846, 3456, 2432, 3041, 3651, 2626, 3236, 3845, 2821, 3431, 2406};
// Tone map soft knee.
constexpr float toneKnee = 0.78f, toneRange = 0.22f;

// Section 8.3 time of day: (hour, resting brightness factor) keyframes.
constexpr float todHours[8] = {0.0f, 5.0f, 8.0f, 13.0f, 17.0f, 20.0f, 22.5f, 24.0f};
constexpr float todFactors[8] = {0.55f, 0.60f, 0.95f, 1.00f, 1.00f, 0.85f, 0.65f, 0.55f};

// Section 9 output.
constexpr uint8_t defaultDrive = 150;
// [user 2026-09-26] (ALIVE.md 9 step 4, 12.7) Temporal dither is OFF unless a latched ledDither:true
// turns it on: at the resting / offline levels (0-3 counts) it toggled most LEDs by one count every
// frame (hardware flicker, cc5.4 binary A). Dither off applies the F-T floor (cc_alive_output).
constexpr bool defaultDither = false;
// [D17][R5] B = 68 * (255 + 132 + 36) * 150 / 255 = 16920 exactly: the warmth test's proven
// load (68 LEDs at #FF8424, brightness 150). cc_alive.cpp static_asserts the arithmetic.
constexpr float powerBudget = 16920.0f;
constexpr uint8_t buttonLedsPerSlot = 2;

// r4 (design_handoff_nano_d_r4 README 3.3 / 3.4; ALIVE.md section 16), after the animator:
// - every ring and button LED eases towards the animator's e, exponential tau 50 ms: nothing ever steps;
// - a wall (limit) glows the 5 LEDs at that end of the arc (the cursor +-2) warm white 255,232,205 at L 0.9, a bloom
//   (rise 90 ms E.out, fall 420 ms E.io) blended over whatever they show;
// - M12 the domain swap: after a plain-ok hold-4 landing each LED starts easing to the new ring i x 8.7 ms after the
//   landing (clockwise from 12 o'clock), 200 ms each (the 50 ms easer).
constexpr float easeTauMs = 50.0f;
constexpr float easeSnap = 1.0e-6f;         // |target - shown| below this lands on the target
constexpr uint32_t wallGlowRgb = 0xFFE8CDu;
constexpr float wallGlowAlpha = 0.9f;
constexpr int wallGlowHalf = 2;
constexpr float glowRiseMs = 90.0f, glowFallMs = 420.0f;
constexpr float sweepStepMs = 8.7f;

// [Q1] (12.5) the End stop on every push: the re-arm hold-off (tuned in the turning test,
// 40-150 ms) and the spacing of the ring's bound / the wire lim.
constexpr uint32_t limRearmMs = 75;
constexpr uint32_t limGapMs = 150;
}

// Colour roles (section 5.1). ACCENT is an app/album colour after sat(). [r2] PINK 7 (append-only).
enum CCAliveRole : uint8_t {
    CC_ALIVE_ROLE_NONE, CC_ALIVE_ROLE_WARM, CC_ALIVE_ROLE_GREEN, CC_ALIVE_ROLE_RED,
    CC_ALIVE_ROLE_AMBER, CC_ALIVE_ROLE_BLUE, CC_ALIVE_ROLE_ACCENT, CC_ALIVE_ROLE_PINK
};
// Classes (section 5.2), append-only: 0 none, 1, 2, S (half-step), 3, 4; [r2] P (Up next played
// 0.14), N (now playing 0.70), Q (Up next upcoming, the unavailable list cursor: 0.45).
// [r3] T 9 (0.08), R 10 (0.12), O 11 (0.18), L 12 (0.34), F 13 (0.50): the Lights rings (ALIVE.md 15.3).
enum CCAliveClass : uint8_t {
    CC_ALIVE_CLASS_NONE, CC_ALIVE_CLASS_1, CC_ALIVE_CLASS_2, CC_ALIVE_CLASS_S, CC_ALIVE_CLASS_3, CC_ALIVE_CLASS_4,
    CC_ALIVE_CLASS_P, CC_ALIVE_CLASS_N, CC_ALIVE_CLASS_Q,
    CC_ALIVE_CLASS_T, CC_ALIVE_CLASS_R, CC_ALIVE_CLASS_O, CC_ALIVE_CLASS_L, CC_ALIVE_CLASS_F,
    CC_ALIVE_CLASS_M,    // [r3] 14 (0.10): the marker ring's rest (ALIVE.md 15.7)
    CC_ALIVE_CLASS_W     // [r3.1] 15 (0.60): the queue ring's playing row (ALIVE.md 15.9)
};
// Layout families (Home = nowPlaying/volume/idle/notice; tracks = tracks/seek). OFFLINE = unclaimed.
// [r2] explorer 5, upnext 6 (append-only).
// [r3] LIGHTS 7 (lights, lightsbig, scenes; ALIVE.md 15.1).
enum CCAliveFamily : uint8_t {
    CC_ALIVE_HOME, CC_ALIVE_RECENT, CC_ALIVE_TRACKS, CC_ALIVE_WINDOWS, CC_ALIVE_OFFLINE,
    CC_ALIVE_EXPLORER, CC_ALIVE_UPNEXT, CC_ALIVE_LIGHTS
};
// Section 7 effects, in the order of CCAliveSpec::durations. [r2] half 15, scatter 16.
enum CCAliveEffectType : uint8_t {
    CC_FX_BOOT, CC_FX_DOWN, CC_FX_WAKE, CC_FX_TICK, CC_FX_BOUND, CC_FX_PENDING, CC_FX_BLOOM, CC_FX_FAIL,
    CC_FX_SWEEP, CC_FX_FILL, CC_FX_DRAIN, CC_FX_SHIMMER, CC_FX_WASH, CC_FX_REVEAL, CC_FX_PRESS,
    CC_FX_HALF, CC_FX_SCATTER, CC_FX_TYPES
};

// One ring segment or button target. Plain aggregate (C++11).
struct CCAliveCell {
    // ROLE_ACCENT: the sat() colour 0xRRGGBB (integer by section 2's sat(); the animator
    // draws rgb / 255). Every other role: 0; the animator takes the colour from its
    // CCAlivePalette by role (WARM, GREEN, RED, AMBER, BLUE, PINK), so the palette is never
    // rounded to 8 bits [R5].
    uint32_t rgb;
    float alpha;     // section 5.2 / 5.3 alpha; 0 when unlit
    uint8_t cls;     // CCAliveClass; CC_ALIVE_CLASS_NONE = unlit
    uint8_t role;    // CCAliveRole
    bool volRed;     // ring: the final role is RED (feeds the near-max embers)
};

// Targets plus the flags the animator needs (section 5.4).
struct CCAliveTargets {
    CCAliveCell ring[CC_RING_LEDS];
    CCAliveCell buttons[4];
    uint8_t family;      // CCAliveFamily
    uint8_t style;       // [r2] CCRingStyle (MODE on transport <-> lap)
    uint8_t cursor;      // logical cursor segment (0 when offline or dark)
    bool asleep;         // effectiveAsleep (6.1)
    bool offline;        // unclaimed (8.1)
    bool pending;        // 6.1: Working comet
    bool heat;           // Home, awake, displayed volume >= 90
    bool pausedPlay;     // Home, awake, slot 0 is the green paused Play
    bool tintOn;         // [r2] recent/explorer/upnext/windows, awake, cursor lit with role ACCENT [R2]
    float tint[3];       // the cursor accent / 255 when tintOn
    float songProg;      // song hand position 0..1, or < 0 when hidden (8.4, [R3])
    float todB;          // time-of-day resting brightness (8.3)
};

// Colours the animator draws with, 0..1 design space: the targets of the palette
// roles and the effect colours. The engine uses cc_alive_palette() (section 2, PINK
// tuned by setTuning); the oracles inject the designs' own (RC: warmAt(hour) warm/hot and
// GRN/RED/BLUE; BS: its WARM/HOT/GREEN/RED/AMBER/PINK; their targets carry explicit colours).
struct CCAlivePalette {
    float warm[3], hot[3], green[3], red[3], amber[3], blue[3], pink[3];
};

// One queued effect (the design's play() parameters). Only the fields its type
// uses matter; cc_alive_effect() zeroes the rest.
struct CCAliveEffect {
    uint32_t t0;     // start (ms)
    uint32_t kill;   // FG fade start, valid when killed
    float at;        // segment: down wake tick bound pending bloom fail sweep wash half scatter
    float from, to;  // shimmer
    float c[3];      // bound, wash, [r2] bloom and half colour (0..1)
    float seed;      // [r2] scatter: 0 <= seed < 60
    int16_t n;       // fill/drain arc length; press slot 0..3
    int16_t len;     // tick tail
    int8_t dir;      // tick, bound, sweep: +1 / -1
    int8_t side;     // [r2] half: -1 left (segments 31..59, Button 2), +1 right (1..29, Button 3)
    uint8_t type;    // CCAliveEffectType
    bool home;       // boot: draw in along the volume arc
    bool killed;     // set by play() on an FG start
    uint8_t snap;    // down: its own snapshot slot 0..queueCapacity-1 (set by play())
};
CCAliveEffect cc_alive_effect(uint8_t type, uint32_t t0);

// ------------------------------------------------------------------ helpers
// JS Math.round (half toward +infinity), as float.
float cc_alive_js_round(float x);
// md(i) = ((round(i) % 60) + 60) % 60 with the JS remainder (design line 103).
int cc_alive_md(float i);
// cd(i, j) = ((((i - j) % 60) + 90) % 60) - 30 with the JS remainder, -30..30 (line 104).
float cc_alive_cd(float i, float j);
// sat() of section 2 on integer channels, rounding half away from zero exactly.
// Returns the re-saturated colour and sets accent = true, or returns 0 and sets
// accent = false when max - min < 30 (the WARM fallback: role WARM, whose colour
// is the palette's).
uint32_t cc_alive_sat(uint32_t rgb, bool& accent);
// Family of a frame's layout ([r2] 5.4: every layout mapped explicitly).
uint8_t cc_alive_family(const CCFrame& frame);
// 6.1 pending: activity pending/loading, or Home with a level ring whose
// displayed value (localValue when >= 0, else ringValue) differs from confirmedVolume, except
// with activity offline [R1]: the Home Sonos-off notice [D15] draws only the confirmed endpoint
// and never shows the Working comet.
bool cc_alive_pending(const CCFrame& frame, int32_t localValue = -1);
// Displayed volume of a level ring: localValue when >= 0, else ringValue (sanitised 0..100).
uint8_t cc_alive_displayed_volume(const CCFrame& frame, int32_t localValue = -1);
// 6.3 local cursor [D14], for the LEDs only, without copying the frame: value >= 0 is the level
// ring's displayed value, index >= 0 the selection / transport ring's index (both -1 when the
// rules do not apply; never on the [r2] lap ring [M11]; [r3] the bri ring takes value with localMax 100, the
// clusters ring index with localMax count - 1, the ctemp ring never). localMax < 0 means "no local
// position". Returns true when applied. The selection ring keeps the host frame's window: the
// targets re-centre on the local index [M15].
bool cc_alive_local(const CCFrame& frame, int32_t localPos, int32_t localMax, int32_t& value, int32_t& index);
// The same as a frame copy (tests): out = frame with the local value or index applied.
bool cc_alive_apply_local(const CCFrame& frame, int32_t localPos, int32_t localMax, CCFrame& out);
// The selected entry's accent for 6.4 (D7): sat(acc(index)) of a selection ring before any
// pending override, or 0 when WARM or none (loading, More, the Up next card, colour 0, white
// LEDs, not transmitted, or not a selection ring). localIndex as in CCAliveTargetState.
uint32_t cc_alive_selected_color(const CCFrame& frame, int32_t localIndex = -1);
// 8.3 resting brightness factor at `hour` (0..24), linear between keyframes.
float cc_alive_tod_brightness(float hour);
// The production palette: the section 2 float constants (CCAliveSpec).
CCAlivePalette cc_alive_palette();
// [r2][M24] PINK for a ledPink value: 0 = the built-in constant, else the per-channel sRGB OETF
// of the LED colour (the section 2 derivation, applied at run time only for tuning).
void cc_alive_pink(uint32_t ledPink, float (&out)[3]);
// [r2][M5] one xorshift32 step and the scatter seed of a state: 60 (x >> 8) / 2^24, in float32
// (the correctly rounded value of the contract's double evaluation: one rounding, as exact).
uint32_t cc_alive_xorshift32(uint32_t x);
float cc_alive_scatter_seed(uint32_t x);

// ------------------------------------------------------------------ targets
struct CCAliveTargetState {
    bool offline;        // unclaimed: the offline override, the frame is ignored
    bool asleep;         // effectiveAsleep
    uint8_t flash;       // CCFlashKind of the running flash window
    uint32_t pendingMs;  // the pending pulse onset's elapsed time (5.1.8)
    int32_t localValue;  // 6.3: the level ring's local displayed value, -1 = the frame's
    int32_t localIndex;  // 6.3: the selection / transport ring's local index, -1 = the frame's;
                         // a selection ring re-centres on it [M15]
    bool volFull;        // [M24] latched ledVolFull
    int16_t holdFill;    // [r3] 15.7: the hold-1 (or [r3.1] button-4) progress ring's filled arc segments, 0 = none
};
// Pure targets function (sections 5.1-5.4) of the host frame with the local cursor of `state`
// (cc_alive_local); `frame` may be null (dark, or offline). songProg = -1, todB = 1: the engine
// fills those.
void cc_alive_targets(const CCFrame* frame, const CCAliveTargetState& state, CCAliveTargets& out);

// ------------------------------------------------------------------ animator
typedef float CCAliveRingE[CC_RING_LEDS][3];
typedef float CCAliveButtonE[4][3];

class CCAliveAnimator {
public:
    CCAliveAnimator();
    // Dark (a = 0, colour 1,0.64,0.33 as the design), empty queue, no tint. Keeps the
    // reduced-motion flag (a latch of the engine).
    void reset();
    // The design's play(): [r2] under reduced motion wake/tick/sweep/scatter/reveal are dropped
    // before anything else (BS:579; not queued, kill nothing). An FG effect kills (kill = t0)
    // every running FG effect; wake/reveal/bound replace their own type; tick/press accumulate.
    // A full queue (8) first drops the oldest killed effect, else the oldest
    // tick, else the oldest press, else the oldest effect. 'down' snapshots the
    // current damped state (cur * a) here into a slot of its own, kept for its
    // whole life (the design's per-effect e.snap / e.bsnap, line 231). Returns false when dropped.
    bool play(const CCAliveEffect& effect);
    // The design's draw(t, dt) up to the compose loops: e in 0..1 design space.
    void step(uint32_t t, uint32_t dt, const CCAliveTargets& targets, const CCAlivePalette& palette,
              CCAliveRingE& ring, CCAliveButtonE& buttons);
    // [r2] 6.5 reduced motion: play()'s drop list and the stationary fail (read at draw time).
    void setReducedMotion(bool on) { reducedMotion_ = on; }
    bool reducedMotion() const { return reducedMotion_; }
    // Any queued effect, damping residue > 1/1024 or a continuous layer active
    // (as of the last step).
    bool animating() const { return animating_; }
    uint8_t effectCount() const { return count_; }
    const CCAliveEffect& effect(uint8_t index) const { return fx_[index]; }
    // Effects dropped by the [D12] cap since reset() (diagnostics and tests).
    uint32_t evictions() const { return evictions_; }

private:
    struct Light { float r, g, b, a; };
    void add(int i, const float* c, float a);
    void addAt(float i, const float* c, float a);
    void addG(float pos, float w, const float* c, float a);
    void addB(int j, const float* c, float a);
    void comet(float head, float dir, int len, const float* c0, const float* c1, float a);
    bool draw(CCAliveEffect& e, uint32_t t, const CCAlivePalette& palette, float& duck);
    void remove(uint8_t index);
    uint8_t freeSnapshot() const;

    Light cur_[CC_RING_LEDS], bcur_[4];
    float tint_[3];
    CCAliveEffect fx_[CCAliveSpec::queueCapacity];
    uint8_t count_;
    uint32_t evictions_;
    // 'down' snapshots, one slot per queue entry (8 x 768 B).
    float snap_[CCAliveSpec::queueCapacity][CC_RING_LEDS][3], bsnap_[CCAliveSpec::queueCapacity][4][3];
    // Per-step scratch, kept in the object (never on the stack).
    float m_[CC_RING_LEDS], bm_[4], o_[CC_RING_LEDS][3], ob_[4][3];
    bool animating_;
    bool reducedMotion_;
};

// ------------------------------------------------------------------ output
// Temporal dither residuals, one per LED channel (buttons: one per slot, its
// two LEDs show the same value).
struct CCAliveDither {
    float ring[CC_RING_LEDS][3];
    float buttons[4][3];
};
// sRGB EOTF of e clamped to 0..1 (LUT, within 1e-4 of the formula).
float cc_alive_eotf(float e);
// Effective drive: min(150, max) by default, the latched ledDrive clamped to max.
uint8_t cc_alive_drive(bool latched, uint8_t ledDrive, uint8_t ledMaxBrightness);
// Section 9: v = eotf(e) * drive; power limit over 60 ring + 8 button LEDs;
// quantise (dithered: residuals persist; off: residuals zeroed). Outputs
// 0xRRGGBB per logical ring segment and per button slot.
// [user 2026-09-26] F-T floor (step 4, dither off only): an LED whose bit is set in ringLit (bit i =
// logical segment i) or buttonLit (bit j = slot j), i.e. whose design target is lit, and whose plain
// rounding is dark although m = max_c v_c > 0, shows one count on its dominant channel: q_c = 1 where
// v_c == m (ties light every tied channel), the rest 0 (12.7: continuous with plain rounding at
// m = 0.5). Every other LED keeps plain rounding. The default masks (0) mean no floor, so a direct
// call without them is the plain section 9 output.
void cc_alive_output(const CCAliveRingE& ringE, const CCAliveButtonE& buttonE, uint8_t drive, bool dither,
                     CCAliveDither& residuals, uint32_t (&ring)[CC_RING_LEDS], uint32_t (&buttons)[4],
                     uint64_t ringLit = 0, uint8_t buttonLit = 0);
// The F-T masks of a render's targets: bit i / j set when that ring segment / button slot has a lit
// target (class != none and alpha > 0), the Python twin's AliveLights.lit_masks().
void cc_alive_lit(const CCAliveTargets& targets, uint64_t& ringLit, uint8_t& buttonLit);

// ------------------------------------------------------------------ engine
// Frame fields of ALIVE.md section 3 the integration hands over next to the frame (the parser
// stores them in CCFrame.playing / feedbackSkip too; this struct stays the authority for them,
// so a caller can render a frame with or without them). The [r2] v5 fields (moment, side,
// colour, ring now/card, button lit/colour, the lap style) are read from CCFrame (PRESENTATION_V5
// 3.6), which the parser fills.
struct CCAliveFrameExtra {
    int8_t playing;  // Home frames: -1 absent, 0 false, 1 true (absent counts as not playing [R3])
    int8_t skip;     // feedback.skip: 0 absent, -1 / 1 (only meaningful with feedback ok)
};

// Section 4 engine. One static instance owns the LEDs while it runs.
class CCAlive {
public:
    CCAlive();
    // Power-up: offline state (8.1) + reveal. Clears every latch (clock, progress, reduced
    // motion, tuning), the PRNG and the residuals; the next render has dt = 0.
    void reset(uint32_t now);
    // unclaimed -> claimed: ONLINE. Counts as an input; boot starts on the next
    // render with home = the family of that first frame, which only seeds 6.4.
    void claim(uint32_t now);
    // claimed -> unclaimed: OFFLINE; 'down' snapshots the current damped state
    // at the last claimed cursor.
    void release(uint32_t now);
    // Queued inputs (processed by render in the order of section 4); ignored
    // while unclaimed. detent: local position moved by delta != 0.
    void detent(uint32_t now, int32_t delta);
    void limit(uint32_t now, int8_t dir);           // end stop, -1 at 0, +1 at max
    void press(uint32_t now, uint8_t slot);         // physical slot 0..3
    // [r3] 15.7: the release of physical slot `slot` (hmi_thread's kEventReleased while claimed). Slot 0's
    // press and release bound the hold-1 progress ring; [r3.1] slot 3's the button-4 hold ring.
    void keyUp(uint32_t now, uint8_t slot);
    // Latched host fields (section 3). minute 0..1439; dur 0 clears progress.
    void setClock(uint32_t now, uint16_t minute);
    void setProgress(uint32_t now, uint32_t pos, uint32_t dur);
    // [r2] 6.5 the latched reducedMotion [M17]; K1 resets the latch at a claim, the engine
    // keeps whatever the integration applies.
    void setReducedMotion(uint32_t now, bool on);
    // [r2] 3.2 the latched tuning fields [M24]: ledPink (0 = the built-in PINK; else the LED
    // colour whose OETF becomes PINK) and ledVolFull (semantic body / half-step at 1.00).
    void setTuning(uint32_t now, uint32_t pinkLed, bool volFull);
    // ([M29] withdrew the native handover's 5 s return and its reveal: there is no startReveal();
    // a reveal starts only from reset() and the 6.4 MODE rule.)
    // One frame: targets, events (section 4 order) and the animator step. `frame`
    // is the last accepted frame while claimed (null when unclaimed). localMax < 0:
    // no local position (the FOC control is not the frame's, or not ready).
    void render(uint32_t now, const CCFrame* frame, int32_t localPos, int32_t localMax);
    void render(uint32_t now, const CCFrame* frame, int32_t localPos, int32_t localMax,
                const CCAliveFrameExtra& extra);
    // Section 9 on the last render's e, with the engine's dither residuals; with dither off, the F-T
    // floor on the LEDs whose last-render target is lit (cc_alive_lit(targets())).
    void output(uint8_t drive, bool dither, uint32_t (&ring)[CC_RING_LEDS], uint32_t (&buttons)[4]);

    const CCAliveRingE& ringE() const { return ringE_; }
    const CCAliveButtonE& buttonE() const { return buttonE_; }
    const CCAliveTargets& targets() const { return targets_; }
    const CCAliveAnimator& animator() const { return animator_; }
    const CCAlivePalette& palette() const { return palette_; }
    bool asleep() const { return targets_.asleep; }
    uint8_t cursor() const { return targets_.cursor; }
    // The animator, or the r4 output easer still moving, or a wall glow / domain sweep running.
    bool animating() const { return animator_.animating() || easeResidue_ > 1.0f / 1024.0f || wallOn_ || sweepOn_; }
    float easeResidue() const { return easeResidue_; }    // r4: the largest |target - eased| of the last render
    bool wallGlow() const { return wallOn_; }
    bool sweeping() const { return sweepOn_; }
    bool claimed() const { return claimed_; }
    uint8_t flash() const { return flash_; }
    // [M22] the running moment hold's length (0 = none).
    uint16_t holdMs() const { return holdMs_; }
    float velocity() const { return vel_; }
    uint32_t rng() const { return rng_; }                  // [M5] the PRNG state
    bool reducedMotion() const { return animator_.reducedMotion(); }
    bool volFull() const { return volFull_; }
    // Time-of-day factor at `now` (1 without a latched clock).
    float todB(uint32_t now) const;

private:
    struct Input { uint32_t now; int32_t value; };
    void wakeInput(uint32_t sleepAt);
    void playAt(uint8_t type, uint32_t now, float at);
    void feedback(const CCFrame& f, uint32_t now, const CCAliveFrameExtra& extra);
    bool feedbackEffect(uint32_t now, float at);
    uint32_t onsets(const CCFrame& f, uint32_t now);
    void song(uint32_t now, int8_t playing);
    void cursorColour(float (&c)[3]) const;

    CCAliveAnimator animator_;
    CCAlivePalette palette_;
    CCAliveTargets targets_;
    CCAliveRingE ringE_;
    CCAliveButtonE buttonE_;
    CCAliveDither dither_;
    Input presses_[8], detents_[8], limits_[4];
    uint8_t pressCount_, detentCount_, limitCount_;
    // Render clock.
    uint32_t lastRender_;
    bool firstRender_;
    // Claim and sleep (6.1).
    bool claimed_, bootPending_, seeding_, stateAsleep_, prevAsleep_;
    uint32_t sleepAt_;
    // Feedback: the flash (rows a, b, i, j), the [M22] moment hold (rows c-h), the event.
    uint8_t flash_, feedbackKind_, feedbackMoment_;
    bool feedbackEvent_, colorMode_;
    int8_t feedbackSkip_, feedbackSide_;
    uint16_t holdMs_;
    uint32_t feedbackColor_;
    uint32_t lastSeq_, flashStart_, holdStart_, pendingStart_;
    bool pendingOn_;
    // 6.4 memory of the last rendered claimed frame.
    uint8_t prevFamily_, prevStyle_, prevCursor_;
    uint32_t prevAccent_;                // sat'd selected accent, 0 when WARM or none
    bool prevExternal_;
    int8_t prevPlaying_;
    // Spin velocity (6.2).
    float vel_;
    uint32_t lastRot_;
    bool hasRot_;
    // Latches: clock (8.3), progress and the song hand (8.4), [r2] tuning (3.2).
    bool hasClock_, volFull_;
    uint16_t clockMinute_;
    uint32_t clockAt_;
    uint32_t progPos_, progDur_, progAt_;
    int8_t homePlaying_;                 // the last Home frame's playing (-1 absent = not playing [R3])
    // [r3] 15.7 the hold-1 progress ring: slot 0 down since holdAt_ (holdDown_), the home flash played.
    bool holdDown_, holdMatured_, feedbackRefused_;
    uint32_t holdAt_;
    // [r3.1] the button-4 hold ring: slot 3 down since hold4At_ (hold4Down_), its home flash played.
    bool hold4Down_, hold4Matured_;
    uint32_t hold4At_;
    // [r3.1] the landing window of a matured button-4 hold (open since landingAt_).
    bool landingOpen_;
    uint32_t landingAt_;
    uint32_t rng_;                       // [M5] the scatter PRNG (xorshift32)
    // r4 (ALIVE.md 16): the eased output, the wall glow and the domain-swap sweep.
    void r4Layer(uint32_t now, uint32_t dt);
    float eased_[CC_RING_LEDS][3], easedB_[4][3];
    float prevE_[CC_RING_LEDS][3], prevEB_[4][3];   // the previous render's animator e (the easer's first-order hold)
    float easeResidue_;
    bool wallOn_, sweepOn_;
    uint32_t wallAt_, sweepAt_;
    uint8_t wallSeg_;
};

// ------------------------------------------------------------------ local input (firmware HMI)
// ALIVE.md 6.2 local input, sampled from the FOC once per HMI pass while claimed. A detent is a
// position change of the same READY control between two consecutive samples of it. The first
// sample of a control only seeds, and so does every sample after reset(): the HMI resets when a
// pass has no ready control and on every claim and release, so the samples compared always come
// from one uninterrupted ready interval [F1/W2]. A control id reused after a release (the knob
// accepts any id then, and every companion run numbers its controls from 1 again) is a new
// control and never compares with the earlier session's position or limit state.
//
// [Q1] (ALIVE.md 12.5) The End stop fires on every push into a bound: each pass samples
// `pushing` = the FOC is at the limit AND its attractor has moved past the bound
// (atLimit && attract_angle != last_attract_angle, one read-only FOC accessor). A limit fires
// when `pushing` rises from false, provided it has been false for at least limRearmMs (75 ms)
// counted from the last pass that saw it true (the first push after arriving at a bound fires
// at once: arriving does not set `pushing`), and at least limGapMs (150 ms) after the previous
// fire; dir -1 at position 0 and +1 at max (-1 when max is 0: one position, both bounds are 0;
// a push elsewhere gives no limit). A push held against the bound fires once. reset() (a new
// control id, a release, a pass without a ready control) resets the detector with the sampler.
struct CCAliveKnobEvents {
    int32_t delta;   // != 0: detent(now, delta)
    int8_t limit;    // != 0: limit(now, dir) and the {"id","lim"} event
};

class CCAliveKnob {
public:
    CCAliveKnob() { reset(); }
    // No ready control: the next sample of any control only seeds.
    void reset();
    // [Q1] One pass's sample of the ready control `id` (0 = none: same as reset()). `pushing` is
    // FocThread::pass_limit_push() (hmi_thread.cpp alive_sample_knob()).
    CCAliveKnobEvents sample(uint32_t now, uint32_t id, uint16_t pos, bool pushing, uint16_t max);
    bool valid() const { return valid_; }   // the latest pass sampled a ready control
    uint32_t id() const { return id_; }     // that control (0 after reset())
    uint16_t pos() const { return pos_; }
    uint16_t max() const { return max_; }
    bool pushing() const { return pushing_; }

private:
    uint32_t id_, pushAt_, fireAt_;
    uint16_t pos_, max_;
    bool valid_, pushing_, pushSeen_, fired_;
};
