// "Warm · alive" LED engine checks (ALIVE.md section 11). Built by alive_tests.py with
// MSVC /W4 /WX together with the unchanged firmware units ../firmware/src/
// cc_alive.cpp, cc_lights.cpp and cc_frame_parse.cpp (ArduinoJson, as light_tests).
//
// Part 1 - direct checks: the section 2 float palette [R5] (the OETF of the user's picks;
// section 9 maps WARM -> #FF8424 and AMBER -> #FF3A0A exactly at drive 255, dither off, and
// lands within 1 of the warmth test's scale8 wire bytes at drive 150; B = 16920 is the
// warmth test's load), the output stage (11.4 minus the led_wire part), sat(),
// md/cd/Math.round JS semantics, time-of-day keyframes, the effect queue (FG kill,
// replacement, [D12] eviction order, one snapshot per live 'down' [R6]), sleep timing (6.1),
// the targets layer (5.x, the [R2] tint), the local cursor (6.3), the event detection (6.2,
// 6.4, the [D19] tick-length tie rule), the song hand [R3], the Sonos-off notice [R1],
// the HMI's local-input sampler CCAliveKnob (6.2: a control id reused after a release or a
// companion restart only seeds; alive_tests.py pins its hmi_thread.cpp wiring), the palette
// roles through the animator and the per-frame cost.
//
// Part 2 - the design oracles: RC (11.1), argv[1] = tests/fixtures/alive_oracle.json, and [r2] BS
// (11.2, the r2.1 "Browse and Snap" draw()), argv[3] = tests/fixtures/alive_oracle_bs.json (each
// optional; skipped with a message when absent). The BS fixture carries its palette in
// designConstants (WARM/HOT/GREEN/RED/AMBER/PINK), reduced motion per view ("rm": play()'s drop
// list and the stationary fail) and effects with side/seed/colour; an effect play() dropped under
// reduced motion ("dropped") must be dropped by the port too. Every case replays through ONE
// CCAliveAnimator:
// the view -> CCAliveTargets (warm:true = the case's warm colour, else c/255), the
// case's warm/hot/todB plus the fixture's designConstants GRN/RED/BLUE (the design's
// literal effect colours) as the palette, the effects with their explicit t0 and params
// (play()), then step(t, dt); e must match within the fixture tolerance (2e-3) per
// channel. designConstants DUR, FG, the bloom spark and the initial cur/bcur/tint state
// must equal the port's. "designUncapped" cases exceed the [D12] cap in the design: the
// runner attributes each eviction, follows the evicted effects with the design's play()/
// draw() rules, checks the fixture's queue/live counts at every step and compares every
// step at which the design no longer draws an evicted effect.
// `--cases` (anywhere in argv) prints one line per oracle case.
//
// Part 3 - twin sequences (11.3), argv[2] = alive_sequences.json (optional; skipped when
// absent). Written from the Python engine (control_center/alive_lights.py) by
// tests/tools/make_alive_sequences.py (alive_tests.py regenerates it first). Format (version 2):
//   {"version": 2, "tolerance": 0.002, "byteTolerance": 1, "eScale": 100000,
//    "frames": [wire frame, ...],                 // cc_parse_frame(); "playing" and
//                                                 // feedback.skip are read from the raw object
//    "cases": {name: {"note": text, "steps": [{
//       "now": uint32,
//       "ops": [{"op": "reset"|"claim"|"release"|"reveal"} | {"op": "detent", "delta": int}
//               | {"op": "limit", "dir": -1|1} | {"op": "press", "slot": 0..3}
//               | {"op": "clock", "minute": 0..1439} | {"op": "progress", "pos": int, "dur": int}],
//               // optional; applied in order before render; each op may carry "t" (default: now)
//       "frame": int,                             // optional index into frames; absent = none
//       "local": [pos, max],                      // optional 6.3 local position; absent = none
//       "drive": int (default 150), "dither": bool (default false),
//       "expect": {"e": [192 ints],               // e * eScale: ring 0..59 then buttons 0..3, r g b
//                  "bytes": [64 x 0xRRGGBB],      // optional: output(), dither off; ring then buttons
//                  "lit": "16 hex digits",        // with bytes: the F-T mask (bit i ring, 60 + j button)
//                  "asleep": bool, "cursor": int, "flash": 0|1|2 (CCFlashKind),
//                  "fx": [[type, t0, kill|null, params...], ...],      // the queue after the render
//                  "animating": bool}}]}}}                            // optional (knife edges omitted)
//   One CCAlive per case (constructed = reset(0)); render(now, frame, local, extra) at every
//   step, then output(drive, dither): e within tolerance per channel, bytes within
//   byteTolerance, the rest exactly. "fx" rows carry the params the type's draw() recipe
//   reads (fxRowMatches): boot at home; down/wake/bloom/fail/reveal at; tick at dir len;
//   bound at dir r g b; sweep at dir; fill/drain at n; shimmer from to; wash at r g b; press n.
//   `--cases` also prints one line per sequence.
//   [r2] Frames are parsed by cc_parse_frame with PRESENTATION_V5 (the v7 host's layouts, lap, now,
//   card, lit, colour, moment); a probe fails loudly if the parser lacks it. Ops add
//   {"op": "rm", "on"} (setReducedMotion), {"op": "tuning", "pink", "volFull"} (setTuning),
//   {"op": "knob", "id", "pos", "pushing", "max"} (one pass of CCAliveKnob, [Q1]: its detent and
//   limit go to the engine) and {"op": "knobReset"}; "expect.lim" lists the limits the knob ops of
//   the step fired. fx rows: bloom at r g b; half at side r g b; scatter at seed (within 1e-5).
//   [r2.2] "expect.pending" (optional, bool; the sequences that record it) is the 6.1 pending flag
//   of the render, targets().pending: the Working comet (M33: no gap across two Seek jumps).
//   [user 2026-09-26] Dither off (the default since the user's ruling, ALIVE.md 12.7) applies the F-T
//   floor: "bytes" include it, "lit" is Python's mask, which cc_alive_lit(targets()) must equal, and
//   sequenceFloor() checks visibility and the dominant channel of every floored LED exactly.
//
// [user 2026-09-26] Part 1 adds floorChecks() (9 step 4: the F-T unit cases, the mask, dither on
// unchanged, the engine's offline marks) and Part 2 compares the knob's output stage with each
// oracle step's "bytes" (oracleBytes(): within 1, the floor decision identical outside a band).
#include <ArduinoJson.h>
#include "cc_alive.h"
#include "cc_frame_parse.h"
#include "cc_lights.h"
#include "cc_presentation.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

namespace {
long long checks = 0;
int failures = 0;

void report(const std::string& message) {
    ++failures;
    if (failures <= 80) std::printf("FAIL: %s\n", message.c_str());
}

void require(bool condition, const std::string& message) {
    ++checks;
    if (!condition) report(message);
}

std::string num(double value) {
    char text[48];
    std::snprintf(text, sizeof(text), "%.6g", value);
    return text;
}

std::string hex(uint32_t value) {
    char text[16];
    std::snprintf(text, sizeof(text), "#%06X", static_cast<unsigned>(value));
    return text;
}

bool near(double a, double b, double tolerance) { return std::fabs(a - b) <= tolerance; }

bool readFile(const char* path, std::string& out) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return false;
    std::stringstream buffer;
    buffer << in.rdbuf();
    out = buffer.str();
    return true;
}

double eotfExact(double e) {
    e = e < 0.0 ? 0.0 : (e > 1.0 ? 1.0 : e);
    return e <= 0.04045 ? e / 12.92 : std::pow((e + 0.055) / 1.055, 2.4);
}

// The sRGB OETF (ALIVE.md section 2: how the palette is derived from the LED picks).
double oetfExact(double c) { return c <= 0.0031308 ? 12.92 * c : 1.055 * std::pow(c, 1.0 / 2.4) - 0.055; }

// FastLED 3.6 scale8 with FASTLED_SCALE8_FIXED 1 (the firmware's fastled_config.h): what the
// native profile path put on the wire at brightness `scale` during the warmth test.
int scale8(int c, int scale) { return (c * (1 + scale)) >> 8; }

// e with eotfExact(e) == target (0..1), by bisection.
float inverseEotf(double target) {
    double lo = 0.0, hi = 1.0;
    for (int k = 0; k < 60; ++k) {
        const double mid = (lo + hi) / 2.0;
        if (eotfExact(mid) < target) lo = mid; else hi = mid;
    }
    return static_cast<float>((lo + hi) / 2.0);
}

uint32_t pack(int r, int g, int b) {
    return (static_cast<uint32_t>(r) << 16) | (static_cast<uint32_t>(g) << 8) | static_cast<uint32_t>(b);
}

int chan(uint32_t rgb, int shift) { return static_cast<int>((rgb >> shift) & 255u); }

// ------------------------------------------------------------- frame builders
void setButtons(CCFrame& f, const uint8_t icons[4], const bool enabled[4]) {
    for (int k = 0; k < 4; ++k) {
        f.buttons[k].icon = icons[k];
        f.buttons[k].iconSent = true;
        f.buttons[k].enabled = enabled[k];
    }
}

CCFrame volume(int v, bool colored = true, int confirmed = -1, bool external = false, uint8_t activity = CC_IDLE) {
    CCFrame f;
    std::strcpy(f.mode, "VOLUME");
    f.layoutId = CC_LAYOUT_VOLUME;
    f.ringStyle = CC_RING_LEVEL;
    f.ringValue = static_cast<uint8_t>(v);
    f.confirmedVolume = static_cast<uint8_t>(confirmed < 0 ? v : confirmed);
    f.ringExternal = external;
    f.coloredLeds = colored;
    f.activity = activity;
    const uint8_t icons[4] = {CC_ICON_PAUSE, CC_ICON_LIST, CC_ICON_WIN, CC_ICON_TRACKS};
    const bool enabled[4] = {true, true, true, true};
    setButtons(f, icons, enabled);
    return f;
}

uint32_t accentOf(int j) { return pack(0xC0 - j, 0x40 + j, 0x20); }

CCFrame list(int count, int index, bool windows = false, int more = -1) {
    CCFrame f;
    std::strcpy(f.mode, windows ? "WINDOWS" : "RECENTLY ADDED");
    f.layoutId = windows ? CC_LAYOUT_WINDOWS : CC_LAYOUT_RECENT;
    f.ringStyle = CC_RING_SELECTION;
    f.ringCount = static_cast<uint16_t>(count);
    f.ringIndex = static_cast<uint16_t>(index);
    f.ringFirst = cc_window_first(f.ringIndex, f.ringCount);
    f.ringMoreIndex = more;
    f.coloredLeds = true;
    const int width = count - f.ringFirst < 20 ? count - f.ringFirst : 20;
    for (int k = 0; k < width; ++k) f.ringColors[k] = accentOf(f.ringFirst + k);
    f.ringColorCount = static_cast<uint8_t>(width);
    const uint8_t recentIcons[4] = {CC_ICON_BACK, CC_ICON_HOME, CC_ICON_WIN, CC_ICON_PLAY};
    const uint8_t windowsIcons[4] = {CC_ICON_CANCEL, CC_ICON_HOME, CC_ICON_WIN, CC_ICON_SWITCH};
    const bool enabled[4] = {true, true, true, true};
    setButtons(f, windows ? windowsIcons : recentIcons, enabled);
    return f;
}

CCFrame transport(int index) {
    CCFrame f = list(3, index);
    std::strcpy(f.mode, "TRACKS");
    f.layoutId = CC_LAYOUT_TRACKS;
    f.ringStyle = CC_RING_TRANSPORT;
    f.ringColorCount = 0;
    return f;
}

CCFrame withFeedback(CCFrame f, uint8_t kind, uint32_t seq) {
    f.feedbackPresent = true;
    f.feedbackKind = kind;
    f.feedbackSeq = seq;
    return f;
}

CCAliveFrameExtra extraOf(int8_t playing, int8_t skip = 0) {
    CCAliveFrameExtra x;
    x.playing = playing;
    x.skip = skip;
    return x;
}

int countType(const CCAliveAnimator& a, uint8_t type) {
    int n = 0;
    for (uint8_t k = 0; k < a.effectCount(); ++k) if (a.effect(k).type == type) ++n;
    return n;
}

const CCAliveEffect* lastOf(const CCAliveAnimator& a, uint8_t type) {
    const CCAliveEffect* found = nullptr;
    for (uint8_t k = 0; k < a.effectCount(); ++k) if (a.effect(k).type == type) found = &a.effect(k);
    return found;
}

// ------------------------------------------------------------- part 1: direct checks
void outputChecks() {
    // Transfer curve points and the LUT against the formula (section 9.1, [D3]).
    const double points[] = {0.0, 0.01, 0.04045, 0.05, 0.1, 0.25, 0.5, 0.741176, 0.78, 0.9, 0.99, 1.0};
    for (double e : points)
        require(near(cc_alive_eotf(static_cast<float>(e)), eotfExact(e), 1e-4), "eotf(" + num(e) + ") within 1e-4");
    require(cc_alive_eotf(-0.3f) == 0.0f && cc_alive_eotf(1.7f) == 1.0f && cc_alive_eotf(0.0f) == 0.0f &&
            cc_alive_eotf(1.0f) == 1.0f, "eotf clamps e to 0..1");
    require(near(cc_alive_eotf(0.04045f), 0.04045 / 12.92, 1e-5) && near(cc_alive_eotf(0.02f), 0.02 / 12.92, 1e-5),
            "eotf linear segment up to 0.04045");
    require(near(cc_alive_eotf(0.5f), 0.21404114, 1e-5), "eotf(0.5) = 0.2140");
    double worst = 0.0;
    for (int k = 0; k <= 200000; ++k) {
        const double e = k / 200000.0;
        worst = std::fmax(worst, std::fabs(cc_alive_eotf(static_cast<float>(e)) - eotfExact(e)));
    }
    require(worst <= 1e-4, "eotf LUT within 1e-4 of the formula everywhere (max " + num(worst) + ")");
    std::printf("output: eotf LUT max error %.2e over 200001 points\n", worst);

    // Drive (section 9.2).
    require(cc_alive_drive(false, 200, 255) == 150 && cc_alive_drive(false, 200, 100) == 100 &&
            cc_alive_drive(true, 200, 255) == 200 && cc_alive_drive(true, 200, 120) == 120 &&
            cc_alive_drive(true, 1, 255) == 1, "drive: default min(150, max), latched clamped to max");

    CCAliveRingE ringE;
    CCAliveButtonE buttonE;
    CCAliveDither residual;
    uint32_t ring[CC_RING_LEDS], buttons[4];

    // Palette (section 2, [R5]): float design-space constants. WARM and AMBER are the sRGB OETF
    // (the inverse of the section 9 EOTF) of the LED colours the user picked, within the 6
    // significant digits they are stored with; [user 2026-09-26] HOT == WARM (was mix(WARM, white, 0.5)).
    const float* const palette[6] = {CCAliveSpec::warm, CCAliveSpec::hot, CCAliveSpec::green, CCAliveSpec::red,
                                     CCAliveSpec::amber, CCAliveSpec::blue};
    const char* names[6] = {"WARM", "HOT", "GREEN", "RED", "AMBER", "BLUE"};
    const uint32_t warmPick = 0xFF8424, amberPick = 0xFF3A0A, redPick = 0xFF0000;
    for (int q = 0; q < 3; ++q) {
        const int shift = 16 - 8 * q;
        require(near(CCAliveSpec::warm[q], oetfExact(chan(warmPick, shift) / 255.0), 1e-6),
                "WARM[" + num(q) + "] is the OETF of the pick #FF8424");
        require(near(CCAliveSpec::amber[q], oetfExact(chan(amberPick, shift) / 255.0), 1e-6),
                "AMBER[" + num(q) + "] is the OETF of the pick #FF3A0A");
        require(CCAliveSpec::hot[q] == CCAliveSpec::warm[q], "HOT == WARM [user 2026-09-26]");
    }
    require(CCAliveSpec::warm[0] == 1.0f && CCAliveSpec::warm[1] == 0.746862f && CCAliveSpec::warm[2] == 0.411645f &&
            CCAliveSpec::hot[0] == 1.0f && CCAliveSpec::hot[1] == 0.746862f && CCAliveSpec::hot[2] == 0.411645f &&
            CCAliveSpec::amber[0] == 1.0f && CCAliveSpec::amber[1] == 0.514232f &&
            CCAliveSpec::amber[2] == 0.218649f, "WARM / HOT / AMBER are the section 2 table's constants");
    require(CCAliveSpec::green[0] == 0.0f && CCAliveSpec::green[1] == 1.0f && CCAliveSpec::green[2] == 98.0f / 255.0f &&
            CCAliveSpec::red[0] == 1.0f && CCAliveSpec::red[1] == 0.0f && CCAliveSpec::red[2] == 0.0f &&
            CCAliveSpec::blue[0] == 40.0f / 255.0f && CCAliveSpec::blue[1] == 140.0f / 255.0f &&
            CCAliveSpec::blue[2] == 1.0f, "GREEN 0,1,98/255; RED 1,0,0; BLUE 40/255,140/255,1");
    const CCAlivePalette engine = cc_alive_palette();
    const float* const roles[6] = {engine.warm, engine.hot, engine.green, engine.red, engine.amber, engine.blue};
    bool same = true;
    for (int p = 0; p < 6; ++p)
        for (int q = 0; q < 3; ++q) same = same && roles[p][q] == palette[p][q];
    require(same, "cc_alive_palette() is the section 2 constants, unrounded");

    // Section 9 at drive 255, dither off: WARM -> #FF8424 and AMBER -> #FF3A0A exactly (the user's
    // picks), RED -> #FF0000; every colour equals the float64 formula, on a ring LED and a button.
    uint32_t full[6] = {};
    std::printf("output: palette at drive 255 through the sRGB EOTF:");
    for (int p = 0; p < 6; ++p) {
        std::memset(&residual, 0, sizeof(residual));
        std::memset(ringE, 0, sizeof(ringE));
        std::memset(buttonE, 0, sizeof(buttonE));
        for (int c = 0; c < 3; ++c) ringE[0][c] = buttonE[1][c] = palette[p][c];
        cc_alive_output(ringE, buttonE, 255, false, residual, ring, buttons);
        uint32_t expected = 0;
        for (int c = 0; c < 3; ++c)
            expected = (expected << 8) | static_cast<uint32_t>(std::floor(eotfExact(palette[p][c]) * 255.0 + 0.5));
        require(ring[0] == expected && buttons[1] == expected,
                std::string("palette ") + names[p] + " at drive 255 is " + hex(expected));
        full[p] = ring[0];
        std::printf(" %s %s", names[p], hex(ring[0]).c_str());
    }
    std::printf("\n");
    require(full[0] == warmPick, "WARM at drive 255, dither off, is the pick #FF8424 exactly (" + hex(full[0]) + ")");
    require(full[4] == amberPick, "AMBER at drive 255, dither off, is the pick #FF3A0A exactly (" + hex(full[4]) + ")");
    require(full[3] == redPick, "RED at drive 255 is #FF0000");

    // The warmth test (2026-09-25): the native profile showed the picks at FastLED brightness 150,
    // so the wire carried FastLED 3.6 scale8 bytes (FASTLED_SCALE8_FIXED 1: (c * 151) >> 8). Section
    // 9 at the default drive 150, dither off, lands within +-1 of them per channel.
    const uint32_t picks[3] = {warmPick, amberPick, redPick};
    const float* const pickColours[3] = {CCAliveSpec::warm, CCAliveSpec::amber, CCAliveSpec::red};
    std::printf("output: the picks at drive 150 vs the warmth test's scale8 wire bytes:");
    for (int k = 0; k < 3; ++k) {
        std::memset(&residual, 0, sizeof(residual));
        std::memset(ringE, 0, sizeof(ringE));
        std::memset(buttonE, 0, sizeof(buttonE));
        for (int c = 0; c < 3; ++c) ringE[9][c] = pickColours[k][c];
        cc_alive_output(ringE, buttonE, 150, false, residual, ring, buttons);
        int worstDiff = 0;
        for (int shift = 16; shift >= 0; shift -= 8)
            worstDiff = std::max(worstDiff, std::abs(chan(ring[9], shift) - scale8(chan(picks[k], shift), 150)));
        require(worstDiff <= 1, "pick " + hex(picks[k]) + " at drive 150 is " + hex(ring[9]) +
                                    ", within 1 of the warmth test's scale8 bytes");
        std::printf(" %s -> %s (scale8 #%02X%02X%02X)", hex(picks[k]).c_str(), hex(ring[9]).c_str(),
                    scale8(chan(picks[k], 16), 150), scale8(chan(picks[k], 8), 150), scale8(chan(picks[k], 0), 150));
    }
    std::printf("\n");

    // Power limit [D17]: everything at full at drive 150 -> S = 204 * 150 = 30600 > 16920.
    for (int i = 0; i < CC_RING_LEDS; ++i) ringE[i][0] = ringE[i][1] = ringE[i][2] = 1.0f;
    for (int j = 0; j < 4; ++j) buttonE[j][0] = buttonE[j][1] = buttonE[j][2] = 1.0f;
    std::memset(&residual, 0, sizeof(residual));
    cc_alive_output(ringE, buttonE, 150, false, residual, ring, buttons);
    const double scaled = 150.0 * 16920.0 / 30600.0;           // 82.94
    const uint32_t q = static_cast<uint32_t>(std::floor(scaled + 0.5));
    require(ring[0] == pack(static_cast<int>(q), static_cast<int>(q), static_cast<int>(q)) && buttons[3] == ring[0],
            "power limit scales every v by B/S (83 per channel)");
    long long load = 0;
    for (int i = 0; i < CC_RING_LEDS; ++i) load += chan(ring[i], 16) + chan(ring[i], 8) + chan(ring[i], 0);
    for (int j = 0; j < 4; ++j) load += 2 * (chan(buttons[j], 16) + chan(buttons[j], 8) + chan(buttons[j], 0));
    require(std::llabs(load - 16920) <= 68 * 3 / 2, "power-limited load is B = 16920 within rounding (" +
            num(static_cast<double>(load)) + ")");
    require(CCAliveSpec::powerBudget == 16920.0f && 68 * (255 + 132 + 36) * 150 == 16920 * 255,
            "B = 68 * (255 + 132 + 36) * 150 / 255 = 16920 exactly [D17][R5]");
    // B is the warmth test's proven load: all 68 LEDs (60 ring + 4 slots x 2) at WARM, drive 150,
    // sum to B, so they are not scaled: every LED is (150, 78, 21), within 1 of the scale8 wire
    // bytes (150, 77, 21) the warmth test showed.
    double warmLoad = 0.0;
    for (int i = 0; i < CC_RING_LEDS; ++i)
        for (int c = 0; c < 3; ++c) ringE[i][c] = CCAliveSpec::warm[c];
    for (int j = 0; j < 4; ++j)
        for (int c = 0; c < 3; ++c) buttonE[j][c] = CCAliveSpec::warm[c];
    for (int c = 0; c < 3; ++c) warmLoad += 68.0 * eotfExact(CCAliveSpec::warm[c]) * 150.0;
    require(near(warmLoad, 16920.0, 0.05), "68 WARM LEDs at drive 150 sum to B (" + num(warmLoad) + ")");
    std::memset(&residual, 0, sizeof(residual));
    cc_alive_output(ringE, buttonE, 150, false, residual, ring, buttons);
    bool warmUnscaled = true;
    for (int i = 0; i < CC_RING_LEDS; ++i) warmUnscaled = warmUnscaled && ring[i] == pack(150, 78, 21);
    for (int j = 0; j < 4; ++j) warmUnscaled = warmUnscaled && buttons[j] == pack(150, 78, 21);
    require(warmUnscaled && std::abs(78 - scale8(0x84, 150)) <= 1 && scale8(0xFF, 150) == 150 &&
            scale8(0x24, 150) == 21, "68 WARM LEDs at drive 150 (= B) are unscaled (150,78,21)");
    std::memset(buttonE, 0, sizeof(buttonE));
    // Just over and just under B.
    std::memset(ringE, 0, sizeof(ringE));
    for (int i = 0; i < CC_RING_LEDS; ++i) ringE[i][0] = ringE[i][1] = ringE[i][2] = 1.0f;
    cc_alive_output(ringE, buttonE, 94, false, residual, ring, buttons);   // S = 180 * 94 = 16920: not over
    require(ring[5] == pack(94, 94, 94), "S == B is not scaled");
    cc_alive_output(ringE, buttonE, 95, false, residual, ring, buttons);   // S = 17100 > B: 94.0
    require(ring[5] == pack(94, 94, 94), "S just above B scales down to B");

    // Dither (section 9.4): the long-run mean equals v within 0.02, residuals stay bounded.
    const double targets[] = {0.3, 0.02, 1.7, 12.25, 100.5, 254.6, 0.5, 3.999};
    for (double v : targets) {
        const float e = inverseEotf(v / 255.0);
        const double exact = static_cast<double>(cc_alive_eotf(e)) * 255.0;
        std::memset(ringE, 0, sizeof(ringE));
        std::memset(buttonE, 0, sizeof(buttonE));
        ringE[7][1] = e;
        buttonE[2][0] = e;
        std::memset(&residual, 0, sizeof(residual));
        double sum = 0.0, sumButton = 0.0, worstResidual = 0.0;
        const int frames = 20000;
        for (int k = 0; k < frames; ++k) {
            cc_alive_output(ringE, buttonE, 255, true, residual, ring, buttons);
            sum += chan(ring[7], 8);
            sumButton += chan(buttons[2], 16);
            worstResidual = std::fmax(worstResidual, std::fabs(residual.ring[7][1]));
            worstResidual = std::fmax(worstResidual, std::fabs(residual.buttons[2][0]));
        }
        require(near(sum / frames, exact, 0.02), "dither mean of v " + num(exact) + " is " + num(sum / frames));
        require(near(sumButton / frames, exact, 0.02), "button dither mean of v " + num(exact));
        require(worstResidual <= 0.5 + 1e-4, "dither residual bounded by 0.5 (v " + num(exact) + ": " +
                num(worstResidual) + ")");
    }
    // Residual bounds under random e, every channel.
    uint32_t seed = 12345u;
    double worstRandom = 0.0;
    std::memset(&residual, 0, sizeof(residual));
    for (int frame = 0; frame < 2000; ++frame) {
        for (int i = 0; i < CC_RING_LEDS; ++i)
            for (int c = 0; c < 3; ++c) {
                seed = seed * 1664525u + 1013904223u;
                ringE[i][c] = static_cast<float>(seed >> 8) / 16777216.0f * 1.2f - 0.1f;
            }
        cc_alive_output(ringE, buttonE, static_cast<uint8_t>(1 + frame % 255), true, residual, ring, buttons);
        for (int i = 0; i < CC_RING_LEDS; ++i)
            for (int c = 0; c < 3; ++c) worstRandom = std::fmax(worstRandom, std::fabs(residual.ring[i][c]));
    }
    require(worstRandom <= 0.5 + 1e-4, "residuals stay within +-0.5 for random input (" + num(worstRandom) + ")");
    // Dither off: q = floor(v + 0.5) and the residuals are zeroed.
    std::memset(ringE, 0, sizeof(ringE));
    ringE[3][0] = inverseEotf(10.4 / 255.0);
    ringE[3][2] = inverseEotf(10.6 / 255.0);
    cc_alive_output(ringE, buttonE, 255, false, residual, ring, buttons);
    bool zero = true;
    for (int i = 0; i < CC_RING_LEDS; ++i)
        for (int c = 0; c < 3; ++c) zero = zero && residual.ring[i][c] == 0.0f;
    require(ring[3] == pack(10, 0, 11) && zero, "dither off rounds half up and zeroes the residuals");
}

// [12.7 amendment] The engine frame by frame (16/17/17 ms, dither off, the default path): on every
// target-lit LED over consecutive frames, no floored byte has more counts than the plain byte next to
// it in time, and no channel moves against its value (every v_c rising while some q_c falls, or the
// reverse). `frame` null: the offline breath; else claimed on it at 1000 ms with the clock at `minute`
// and measured once asleep and damped. [user 2026-09-26] (ALIVE.md 12.8) resting is one steady warm white
// at 0.34 (no breath, time of day >= 0.80): asleep, the floor is never needed and no byte changes.
void floorContinuity(const char* label, const CCFrame* frame, uint16_t minute) {
    static CCAlive engine;
    engine.reset(0);
    uint32_t start = 0;
    if (frame) {
        start = 1000;
        engine.claim(start);
        engine.setClock(start, minute);
    }
    const uint32_t settle = start + (frame ? 11000u : 2000u), stop = settle + 8000u;
    static float prevV[64][3];
    static uint32_t prevQ[64];
    static bool prevLit[64], prevFloored[64], prevVisible[64];
    bool have = false;
    int floored = 0, changes = 0, brighter = 0, against = 0;
    std::string first;
    const int steps[3] = {16, 17, 17};
    int k = 0;
    for (uint32_t now = start; now < stop; now += static_cast<uint32_t>(steps[k++ % 3])) {
        engine.render(now, frame, -1, -1);
        uint32_t ring[CC_RING_LEDS], buttons[4], plainRing[CC_RING_LEDS], plainButtons[4];
        engine.output(150, CCAliveSpec::defaultDither, ring, buttons);
        CCAliveDither zero;
        std::memset(&zero, 0, sizeof(zero));
        cc_alive_output(engine.ringE(), engine.buttonE(), 150, false, zero, plainRing, plainButtons);
        uint64_t ringLit = 0;
        uint8_t buttonLit = 0;
        cc_alive_lit(engine.targets(), ringLit, buttonLit);
        if (now < settle) continue;
        for (int i = 0; i < 64; ++i) {
            const float* e = i < 60 ? engine.ringE()[i] : engine.buttonE()[i - 60];
            const float v[3] = {cc_alive_eotf(e[0]), cc_alive_eotf(e[1]), cc_alive_eotf(e[2])};   // a common scale
            const uint32_t q = i < 60 ? ring[i] : buttons[i - 60], plain = i < 60 ? plainRing[i] : plainButtons[i - 60];
            const bool lit = i < 60 ? ((ringLit >> i) & 1u) != 0u : ((buttonLit >> (i - 60)) & 1u) != 0u;
            const bool isFloored = q != plain, visible = plain != 0u;
            floored += isFloored;
            if (have) {
                changes += q != prevQ[i];
                if (lit && prevLit[i]) {
                    const int sumPrev = chan(prevQ[i], 16) + chan(prevQ[i], 8) + chan(prevQ[i], 0);
                    const int sumNow = chan(q, 16) + chan(q, 8) + chan(q, 0);
                    const bool bad1 = (prevFloored[i] && visible && sumPrev > sumNow) ||
                                      (isFloored && prevVisible[i] && sumNow > sumPrev);
                    bool up = true, down = true, qUp = true, qDown = true;
                    for (int c = 0, shift = 16; c < 3; ++c, shift -= 8) {
                        up = up && v[c] >= prevV[i][c];
                        down = down && v[c] <= prevV[i][c];
                        qUp = qUp && chan(q, shift) >= chan(prevQ[i], shift);
                        qDown = qDown && chan(q, shift) <= chan(prevQ[i], shift);
                    }
                    const bool bad2 = (up && !qUp) || (!up && down && !qDown);
                    brighter += bad1;
                    against += bad2;
                    if ((bad1 || bad2) && first.empty())
                        first = std::string(label) + " at " + num(static_cast<int>(now)) + " ms, LED " + num(i) + ": " +
                                hex(prevQ[i]) + " -> " + hex(q);
                }
            }
            for (int c = 0; c < 3; ++c) prevV[i][c] = v[c];
            prevQ[i] = q;
            prevLit[i] = lit;
            prevFloored[i] = isFloored;
            prevVisible[i] = visible;
        }
        have = true;
    }
    const bool exercised = frame ? floored == 0 && changes == 0 : floored > 50 && changes > 0;
    require(brighter == 0 && against == 0 && exercised,
            std::string("floor continuity, ") + label + ": " + num(brighter) + " floored byte(s) brighter than the plain "
                "byte next to them, " + num(against) + " channel(s) against their value (" + first + "); " +
                num(floored) + " floored LED-frames, " + num(changes) + " byte changes");
}

// [user 2026-09-26] ALIVE.md 9 step 4 / 12.7: dither is off by default, and dither off applies rule
// F-T to the LEDs whose target is lit: a lit LED whose plain rounding is dark while m = max_c v_c > 0
// shows one count on its dominant channel (v_c == m; a tie lights every tied channel), the rest 0:
// the byte plain rounding shows just above m = 0.5 (the channel rule amended the same day; the first
// reading, round(v_c / m), also lit a channel >= m / 2 and made a breathing mark jump, 12.7).
void floorChecks() {
    require(!CCAliveSpec::defaultDither, "section 9: the engine's temporal dither is off by default (12.7)");
    CCAliveRingE ringE;
    CCAliveButtonE buttonE;
    CCAliveDither residual;
    uint32_t ring[CC_RING_LEDS], buttons[4];
    // One LED at v = (r, g, b) counts (drive 255, nothing else lit, so no power limit).
    auto set = [](float (&e)[3], double r, double g, double b) {
        e[0] = r > 0.0 ? inverseEotf(r / 255.0) : 0.0f;
        e[1] = g > 0.0 ? inverseEotf(g / 255.0) : 0.0f;
        e[2] = b > 0.0 ? inverseEotf(b / 255.0) : 0.0f;
    };
    struct Case { double r, g, b; bool lit; uint32_t want; const char* what; };
    const Case cases[] = {
        {0.498, 0.238, 0.208, true, pack(1, 0, 0), "the dim WARM mark (0.498, 0.238, 0.208) floors to #010000"},
        {0.0, 0.314, 0.124, true, pack(0, 1, 0), "a dim GREEN (0, 0.314, 0.124) floors to #000100"},
        {0.3, 0.154, 0.066, true, pack(1, 0, 0), "a dim AMBER (0.3, 0.154, 0.066): its dominant red only (not #010100)"},
        {0.2, 0.2, 0.05, true, pack(1, 1, 0), "equal dominant channels both light (ties)"},
        {0.11, 0.06, 0.11, true, pack(1, 0, 1), "a red / blue tie lights both, green (>= m / 2) stays 0"},
        {0.25, 0.2499, 0.0, true, pack(1, 0, 0), "nearly a tie: the dominant channel only"},
        {0.498, 0.238, 0.208, false, 0u, "an unlit tail (target not lit) stays dark"},
        {0.0, 0.0, 0.0, true, 0u, "a lit target with e = 0 (m = 0) stays dark"},
        {0.8, 0.45, 0.0, true, pack(1, 0, 0), "a visible lit LED keeps plain rounding (no floor)"},
        {0.52, 0.3, 0.3, true, pack(1, 0, 0), "m just above 0.5 rounds to 1 plainly (the floor is below it)"},
    };
    for (const Case& c : cases) {
        std::memset(ringE, 0, sizeof(ringE));
        std::memset(buttonE, 0, sizeof(buttonE));
        std::memset(&residual, 0, sizeof(residual));
        set(ringE[17], c.r, c.g, c.b);
        set(buttonE[2], c.r, c.g, c.b);
        cc_alive_output(ringE, buttonE, 255, false, residual, ring, buttons, c.lit ? (uint64_t(1) << 17) : 0u,
                        static_cast<uint8_t>(c.lit ? 4u : 0u));
        require(ring[17] == c.want && buttons[2] == c.want,
                std::string(c.what) + " (ring " + hex(ring[17]) + ", button " + hex(buttons[2]) + ")");
        // The masks default to no floor: a direct call without them is the plain output.
        cc_alive_output(ringE, buttonE, 255, false, residual, ring, buttons);
        require(c.r >= 0.5 || (ring[17] == 0u && buttons[2] == 0u), std::string(c.what) + ": no masks, no floor");
    }
    // The floor is per LED: a lit neighbour's floor does not light an unlit one (bit 18 not set).
    std::memset(ringE, 0, sizeof(ringE));
    set(ringE[17], 0.3, 0.1, 0.0);
    set(ringE[18], 0.3, 0.1, 0.0);
    cc_alive_output(ringE, buttonE, 255, false, residual, ring, buttons, uint64_t(1) << 17, 0);
    require(ring[17] == pack(1, 0, 0) && ring[18] == 0u, "the floor follows the mask bit of each segment");
    cc_alive_output(ringE, buttonE, 255, false, residual, ring, buttons, uint64_t(1) << 59, 0);
    require(ring[17] == 0u, "bit 59 floors segment 59 only");
    // After the [D17] power limit: 59 segments at full white (lit), segment 59 at a dim WARM (lit).
    // S = 59 * 3 * 150 = 26550 > B: the dim segment (0.59, 0.43, 0.24 counts before the limit) is
    // scaled to (0.38, 0.28, 0.15), below one count, and the floor lights its red (1, 0, 0).
    for (int i = 0; i < CC_RING_LEDS; ++i) ringE[i][0] = ringE[i][1] = ringE[i][2] = 1.0f;
    for (int c = 0; c < 3; ++c) ringE[59][c] = CCAliveSpec::warm[c] * 0.05f;
    std::memset(buttonE, 0, sizeof(buttonE));
    cc_alive_output(ringE, buttonE, 150, false, residual, ring, buttons, (uint64_t(1) << 60) - 1u, 0);
    long long load = 0;
    for (int i = 0; i < CC_RING_LEDS; ++i) load += chan(ring[i], 16) + chan(ring[i], 8) + chan(ring[i], 0);
    const double dim = eotfExact(CCAliveSpec::warm[0] * 0.05) * 150.0 * 16920.0 / (59 * 3 * 150.0 +
                       (eotfExact(CCAliveSpec::warm[0] * 0.05) + eotfExact(CCAliveSpec::warm[1] * 0.05) +
                        eotfExact(CCAliveSpec::warm[2] * 0.05)) * 150.0);
    require(dim < 0.5 && ring[59] == pack(1, 0, 0) && ring[0] == pack(96, 96, 96),
            "the floor applies after the power limit (dim segment " + num(dim) + " -> " + hex(ring[59]) + ")");
    require(load <= 16920 + 68 * 3, "the floor adds at most one count per channel to the limited load (" +
                                        num(static_cast<double>(load)) + ")");
    // Dither on: the masks change nothing (the floor is the dither-off path only).
    uint32_t seed = 777u;
    CCAliveDither a, b;
    std::memset(&a, 0, sizeof(a));
    std::memset(&b, 0, sizeof(b));
    bool same = true;
    for (int frame = 0; frame < 500; ++frame) {
        for (int i = 0; i < CC_RING_LEDS; ++i)
            for (int c = 0; c < 3; ++c) {
                seed = seed * 1664525u + 1013904223u;
                ringE[i][c] = static_cast<float>(seed >> 8) / 16777216.0f * 0.06f;   // 0..~0.8 counts
            }
        for (int j = 0; j < 4; ++j)
            for (int c = 0; c < 3; ++c) buttonE[j][c] = ringE[j][c];
        uint32_t ringA[CC_RING_LEDS], ringB[CC_RING_LEDS], buttonsA[4], buttonsB[4];
        cc_alive_output(ringE, buttonE, 150, true, a, ringA, buttonsA, ~uint64_t(0), 15);
        cc_alive_output(ringE, buttonE, 150, true, b, ringB, buttonsB);
        same = same && std::memcmp(ringA, ringB, sizeof(ringA)) == 0 && std::memcmp(buttonsA, buttonsB, sizeof(buttonsA)) == 0;
    }
    require(same, "dither on: the F-T masks change no byte (ledDither:true keeps the residual dither)");
    // The masks of a render's targets: class != none and alpha > 0.
    static CCAliveTargets t;
    std::memset(&t, 0, sizeof(t));
    t.ring[0].cls = CC_ALIVE_CLASS_1;
    t.ring[0].alpha = 0.05f;
    t.ring[33].cls = CC_ALIVE_CLASS_S;
    t.ring[33].alpha = 0.0f;                         // a class without alpha is not lit
    t.ring[59].cls = CC_ALIVE_CLASS_4;
    t.ring[59].alpha = 1.0f;
    t.ring[7].alpha = 0.5f;                          // alpha without a class is not lit
    t.buttons[3].cls = CC_ALIVE_CLASS_1;
    t.buttons[3].alpha = 0.04f;
    uint64_t ringLit = 0;
    uint8_t buttonLit = 0;
    cc_alive_lit(t, ringLit, buttonLit);
    require(ringLit == ((uint64_t(1) << 0) | (uint64_t(1) << 59)) && buttonLit == 8u,
            "cc_alive_lit: bit i / j where the target has a class and alpha > 0");
    // The engine: offline marks at the dim point of the breath are floored (dither off, the default),
    // every unlit segment stays dark, and dither on never floors.
    static CCAlive engine;
    engine.reset(0);
    int flooredFrames = 0, darkMarkFrames = 0;
    bool unlitDark = true;
    for (uint32_t now = 0; now <= 6000; now += 16) {
        engine.render(now, nullptr, 0, -1);
        engine.output(150, CCAliveSpec::defaultDither, ring, buttons);
        uint32_t plain[CC_RING_LEDS], plainButtons[4];
        CCAliveDither zero;
        std::memset(&zero, 0, sizeof(zero));
        cc_alive_output(engine.ringE(), engine.buttonE(), 150, false, zero, plain, plainButtons);
        bool floored = false;
        for (int i = 0; i < CC_RING_LEDS; ++i) {
            if (i % CCAliveSpec::offlinePitch) { unlitDark = unlitDark && ring[i] == plain[i]; continue; }
            if (now >= 1000 && ring[i] == 0u) ++darkMarkFrames;      // after the power-up reveal
            if (ring[i] != plain[i]) floored = true;
        }
        flooredFrames += floored;
    }
    require(flooredFrames > 20 && darkMarkFrames == 0 && unlitDark,
            "offline marks: floored at the dim point of the breath (" + num(flooredFrames) +
                " frames), never dark after the reveal, unlit segments untouched");
    // [12.7 amendment] Continuity through the breath: the offline marks, and the resting ring and
    // buttons asleep on Home at 00:00 and 23:00 (where the proportional rule toggled a second channel;
    // [user 2026-09-26] 12.8: now steady and never floored).
    floorContinuity("offline", nullptr, 0);
    CCFrame home = volume(54);
    floorContinuity("asleep 00:00", &home, 0);
    floorContinuity("asleep 23:00", &home, 23 * 60);
}

void satChecks() {
    bool accent = false;
    require(cc_alive_sat(pack(217, 119, 87), accent) == pack(255, 90, 37) && accent, "sat(217,119,87) = 255,90,37");
    require(cc_alive_sat(pack(128, 128, 128), accent) == 0u && !accent, "grey falls back to WARM (0, no accent)");
    require(cc_alive_sat(pack(100, 129, 100), accent) == 0u && !accent, "spread 29 falls back to WARM");
    cc_alive_sat(pack(100, 130, 100), accent);
    require(accent, "spread 30 re-saturates");
    require(cc_alive_sat(pack(0, 0, 30), accent) == pack(0, 0, 255) && accent, "sat(0,0,30) = 0,0,255");
    require(cc_alive_sat(pack(15, 0, 30), accent) == pack(128, 0, 255), "exact .5 rounds up: 127.5 -> 128");
    // Exhaustive against the design's float64 formula (JS Math.round, v >= 0).
    long long mismatches = 0, warmCount = 0;
    for (uint32_t rgb = 0; rgb <= 0xFFFFFFu; ++rgb) {
        const int c[3] = {chan(rgb, 16), chan(rgb, 8), chan(rgb, 0)};
        const int mx = std::max(c[0], std::max(c[1], c[2])), mn = std::min(c[0], std::min(c[1], c[2]));
        const uint32_t got = cc_alive_sat(rgb, accent);
        uint32_t expected = 0;
        if (mx - mn >= 30) {
            expected = 0;
            for (int k = 0; k < 3; ++k) {
                const double v = std::fmax(0.0, c[k] - mn * 0.75) / (mx - mn * 0.75) * 255.0;
                expected = (expected << 8) | static_cast<uint32_t>(std::floor(v + 0.5));
            }
        } else {
            ++warmCount;
        }
        if (got != expected || accent != (mx - mn >= 30)) ++mismatches;
    }
    require(mismatches == 0, "sat() equals the float64 design formula for all 2^24 colours (" +
            num(static_cast<double>(mismatches)) + " mismatches)");
    std::printf("sat: 16777216 colours checked, %lld fall back to WARM\n", warmCount);
}

void jsChecks() {
    struct R { float x, r; };
    const R rounds[] = {{0.5f, 1.0f}, {-0.5f, 0.0f}, {1.5f, 2.0f}, {-1.5f, -1.0f}, {2.4999f, 2.0f}, {-2.5f, -2.0f},
                        {-2.6f, -3.0f}, {59.5f, 60.0f}};
    for (const R& r : rounds) require(cc_alive_js_round(r.x) == r.r, "Math.round(" + num(r.x) + ") = " + num(r.r));
    struct M { float i; int md; };
    const M mds[] = {{0.0f, 0}, {59.0f, 59}, {60.0f, 0}, {-1.0f, 59}, {0.5f, 1}, {-0.5f, 0}, {-1.5f, 59},
                     {2.5f, 3}, {-2.5f, 58}, {119.4f, 59}, {-60.0f, 0}, {-61.0f, 59}, {85.0f, 25}, {59.5f, 0}};
    for (const M& m : mds) require(cc_alive_md(m.i) == m.md, "md(" + num(m.i) + ") = " + num(m.md));
    struct C { float i, j, cd; };
    const C cds[] = {{0, 0, 0},    {1, 0, 1},      {0, 1, -1},     {30, 0, -30},    {0, 30, -30},
                     {29, 0, 29},  {31, 0, -29},   {59, 0, -1},    {0, 59, 1},      {-90, 0, -30},
                     {10.5f, 0, 10.5f}, {-0.5f, 0, -0.5f}, {29.5f, 0, 29.5f}, {30.5f, 0, -29.5f},
                     {125, 3, 2},  {-61, 0, -1},   {7, 52, 15},    {52, 7, -15},    {35, 25, 10}};
    for (const C& c : cds)
        require(cc_alive_cd(c.i, c.j) == c.cd, "cd(" + num(c.i) + ", " + num(c.j) + ") = " + num(c.cd));
    for (int i = -130; i <= 190; ++i)
        for (int j = -70; j <= 130; j += 7) {
            const int expected = ((((i - j) % 60) + 90) % 60) - 30;   // C++ % == JS % on integers
            if (cc_alive_cd(static_cast<float>(i), static_cast<float>(j)) != static_cast<float>(expected)) {
                report("cd(" + num(i) + ", " + num(j) + ") integer grid");
                return;
            }
        }
    ++checks;
}

void todChecks() {
    const float hours[] = {0.0f, 5.0f, 8.0f, 13.0f, 17.0f, 20.0f, 22.5f, 24.0f};
    const double factors[] = {0.55, 0.60, 0.95, 1.00, 1.00, 0.85, 0.65, 0.55};
    for (int k = 0; k < 8; ++k)
        require(near(cc_alive_tod_brightness(hours[k]), factors[k], 1e-6), "ToD keyframe " + num(hours[k]));
    const float mids[] = {2.5f, 6.5f, 10.5f, 15.0f, 18.5f, 21.25f, 23.25f, 12.0f};
    const double midFactors[] = {0.575, 0.775, 0.975, 1.0, 0.925, 0.75, 0.60, 0.99};
    for (int k = 0; k < 8; ++k)
        require(near(cc_alive_tod_brightness(mids[k]), midFactors[k], 1e-5), "ToD linear at " + num(mids[k]));
    static CCAlive engine;
    engine.reset(0);
    require(engine.todB(123456) == 1.0f, "no latched clock: todB = 1");
    engine.setClock(1000, 1200);                       // 20:00
    require(near(engine.todB(1000), 0.85, 1e-5), "clock 20:00 -> 0.85");
    require(near(engine.todB(1000 + 90u * 60000u), 0.73, 1e-4), "20:00 + 90 min -> 0.73 (continuous [D18])");
    engine.setClock(5000, 1439);                       // 23:59, then past midnight
    require(near(engine.todB(5000 + 2u * 60000u), 0.55 + 0.05 * (1.0 / 60.0) / 5.0, 1e-5), "the clock wraps at 1440");
    engine.setClock(0, 780);                           // 13:00 + one day later
    require(near(engine.todB(86400000u + 60000u), 1.0, 1e-6), "a day later is the same hour");
    engine.reset(0);
    require(engine.todB(1000) == 1.0f, "reset clears the clock latch");
}

// Tone map of section 8.5 in double (the reference for the checks below).
void toneRef(double (&e)[3]) {
    const double mx = std::max(e[0], std::max(e[1], e[2]));
    if (mx <= 0.78) return;
    const double k = (0.78 + 0.22 * (1.0 - std::exp(-(mx - 0.78) / 0.22))) / mx;
    for (double& x : e) x *= k;
}

// Every live 'down' draws its OWN snapshot (the design's play() keeps e.snap / e.bsnap per
// effect, line 231; ALIVE.md section 7), however many releases fall inside one 120 ms kill fade
// (lease flapping). A down every 16 ms for 20 steps, the damped state changing in between; up
// to 8 downs are live at once (the [D12] cap evicts only downs the design no longer draws). A
// shadow animator with the same targets and no effects gives cur * a after each step (its e,
// below the knee). The downs mask every ring target (m = 0 before ms 1250) and every button
// (bm = 0); their snapshot splats have factor 1 on segments o = 0..40 before ms 280 and on
// button slots 0..2 before ms 200, and the button splat carries no amp. So at every step
// e = tone(sum of amp * snap) per segment and tone(sum of bsnap) per button, amp = 1 for the
// newest down and 1 - (t - kill) / 120 for the killed ones.
void downSnapshotChecks(const CCAlivePalette& palette) {
    static CCAliveAnimator flap, shadow;
    static float snaps[20][CC_RING_LEDS][3], bsnaps[20][4][3];
    flap.reset();
    shadow.reset();
    CCAliveTargets tg;
    std::memset(&tg, 0, sizeof(tg));
    tg.family = CC_ALIVE_HOME;
    tg.todB = 1.0f;
    tg.songProg = -1.0f;
    CCAliveRingE flapE, shadowE;
    CCAliveButtonE flapB, shadowB;
    const int at = 10, steps = 20;
    double worst = 0.0;
    int mostLive = 0;
    bool countsMatch = true;
    for (int n = 0; n < steps; ++n) {
        const uint32_t t = 1000u + 16u * static_cast<uint32_t>(n);
        for (int i = at; i <= at + 40; ++i) {                  // o = 0..40 lit, a new state every step
            CCAliveCell& c = tg.ring[i];
            c.cls = CC_ALIVE_CLASS_2;
            c.role = CC_ALIVE_ROLE_ACCENT;
            c.rgb = pack((37 * i + 53 * n) % 256, (91 * i + 17 * n + 40) % 256, (13 * i + 71 * n + 90) % 256);
            c.alpha = 0.05f + 0.25f * static_cast<float>((i + 3 * n) % 7) / 6.0f;
        }
        for (int j = 0; j < 3; ++j) {                          // slots 0..2 lit, slot 3 dark
            CCAliveCell& b = tg.buttons[j];
            b.cls = CC_ALIVE_CLASS_2;
            b.role = CC_ALIVE_ROLE_ACCENT;
            b.rgb = pack((60 * j + 45 * n) % 256, (100 + 33 * n + 20 * j) % 256, (200 + 7 * n * j) % 256);
            b.alpha = 0.1f + 0.2f * static_cast<float>((j + n) % 3) / 2.0f;
        }
        shadow.step(t, 16, tg, palette, shadowE, shadowB);
        flap.step(t, 16, tg, palette, flapE, flapB);
        if (n > 0) {
            double ring[CC_RING_LEDS][3] = {}, buttons[4][3] = {};
            int live = 0;
            for (int k = n - 8 < 0 ? 0 : n - 8; k < n; ++k, ++live) {
                const double amp = k == n - 1 ? 1.0 : 1.0 - 16.0 * static_cast<double>(n - k - 1) / 120.0;
                for (int i = 0; i < CC_RING_LEDS; ++i)
                    for (int q = 0; q < 3; ++q) ring[i][q] += amp * snaps[k][i][q];
                for (int j = 0; j < 4; ++j)
                    for (int q = 0; q < 3; ++q) buttons[j][q] += bsnaps[k][j][q];
            }
            mostLive = std::max(mostLive, live);
            countsMatch = countsMatch && flap.effectCount() == live;
            for (int i = 0; i < CC_RING_LEDS; ++i) {
                toneRef(ring[i]);
                for (int q = 0; q < 3; ++q) worst = std::max(worst, std::fabs(flapE[i][q] - ring[i][q]));
            }
            for (int j = 0; j < 4; ++j) {
                toneRef(buttons[j]);
                for (int q = 0; q < 3; ++q) worst = std::max(worst, std::fabs(flapB[j][q] - buttons[j][q]));
            }
        }
        std::memcpy(snaps[n], shadowE, sizeof(shadowE));       // cur * a now (e below the knee)
        std::memcpy(bsnaps[n], shadowB, sizeof(shadowB));
        CCAliveEffect down = cc_alive_effect(CC_FX_DOWN, t);
        down.at = static_cast<float>(at);
        flap.play(down);
    }
    require(worst < 1e-5 && mostLive == 8 && countsMatch && flap.evictions() > 0,
            "every live down draws its own snapshot (8 at once, max error " + num(worst) + ")");
}

void queueChecks() {
    CCAliveAnimator a;
    CCAliveEffect bloom = cc_alive_effect(CC_FX_BLOOM, 0), fail = cc_alive_effect(CC_FX_FAIL, 100);
    a.play(bloom);
    a.play(fail);
    require(a.effectCount() == 2 && a.effect(0).killed && a.effect(0).kill == 100 && !a.effect(1).killed,
            "an FG start kills the running FG effect at its t0");
    CCAliveEffect wash = cc_alive_effect(CC_FX_WASH, 150);
    a.play(wash);
    require(a.effect(0).kill == 100 && a.effect(1).killed && a.effect(1).kill == 150,
            "a killed effect keeps its first kill time");
    a.play(cc_alive_effect(CC_FX_TICK, 160));
    a.play(cc_alive_effect(CC_FX_PRESS, 160));
    require(!a.effect(3).killed && !a.effect(2).killed, "tick and press never kill (and wash is alive)");
    a.play(cc_alive_effect(CC_FX_WAKE, 170));
    a.play(cc_alive_effect(CC_FX_WAKE, 180));
    require(countType(a, CC_FX_WAKE) == 1 && lastOf(a, CC_FX_WAKE)->t0 == 180, "wake replaces wake");
    a.play(cc_alive_effect(CC_FX_REVEAL, 190));
    a.play(cc_alive_effect(CC_FX_REVEAL, 200));
    a.play(cc_alive_effect(CC_FX_BOUND, 200));
    a.play(cc_alive_effect(CC_FX_BOUND, 210));
    require(countType(a, CC_FX_REVEAL) == 1 && countType(a, CC_FX_BOUND) == 1 && a.effectCount() == 8,
            "reveal and bound replace their own type; queue now 8");
    // Full: the oldest killed effect goes first (bloom), then fail.
    a.play(cc_alive_effect(CC_FX_TICK, 220));
    require(a.effectCount() == 8 && a.effect(0).type == CC_FX_FAIL, "full queue drops the oldest killed effect");
    a.play(cc_alive_effect(CC_FX_TICK, 230));
    require(a.effect(0).type == CC_FX_WASH && countType(a, CC_FX_FAIL) == 0, "... then the next killed effect");
    // No killed effect left: the oldest tick.
    a.play(cc_alive_effect(CC_FX_PRESS, 240));
    require(countType(a, CC_FX_TICK) == 2 && lastOf(a, CC_FX_TICK)->t0 == 230, "then the oldest tick");
    // Only presses and others: the oldest press.
    CCAliveAnimator b;
    for (uint32_t k = 0; k < 8; ++k) b.play(cc_alive_effect(CC_FX_PRESS, k));
    b.play(cc_alive_effect(CC_FX_REVEAL, 10));
    require(b.effectCount() == 8 && b.effect(0).type == CC_FX_PRESS && b.effect(0).t0 == 1 &&
            b.effect(7).type == CC_FX_REVEAL, "then the oldest press");
    // Neither killed, tick nor press: the oldest effect.
    CCAliveAnimator c;
    c.play(cc_alive_effect(CC_FX_WASH, 0));
    c.play(cc_alive_effect(CC_FX_WAKE, 1));
    c.play(cc_alive_effect(CC_FX_REVEAL, 2));
    c.play(cc_alive_effect(CC_FX_BOUND, 3));
    for (uint32_t k = 0; k < 4; ++k) c.play(cc_alive_effect(CC_FX_PENDING, 4 + k));
    c.play(cc_alive_effect(CC_FX_PENDING, 9));
    require(c.effectCount() == 8 && c.effect(0).type == CC_FX_WAKE && c.effect(7).t0 == 9,
            "else the oldest effect");
    // FG kill fades over 120 ms; effects end at u > 1.
    CCAliveAnimator d;
    CCAliveTargets targets;
    std::memset(&targets, 0, sizeof(targets));
    targets.family = CC_ALIVE_HOME;
    targets.todB = 1.0f;
    targets.songProg = -1.0f;
    const CCAlivePalette palette = cc_alive_palette();
    CCAliveRingE ringE;
    CCAliveButtonE buttonE;
    d.play(cc_alive_effect(CC_FX_BLOOM, 0));
    d.play(cc_alive_effect(CC_FX_FAIL, 100));
    d.step(219, 16, targets, palette, ringE, buttonE);
    require(d.effectCount() == 2, "killed bloom still fading at kill + 119");
    d.step(220, 1, targets, palette, ringE, buttonE);
    require(d.effectCount() == 1 && d.effect(0).type == CC_FX_FAIL, "killed bloom dropped at amp <= 0 (kill + 120)");
    d.step(800, 50, targets, palette, ringE, buttonE);
    require(d.effectCount() == 1, "fail alive at u = 1");
    d.step(801, 1, targets, palette, ringE, buttonE);
    require(d.effectCount() == 0, "fail dropped at u > 1");
    // Down snapshots cur * a at play time.
    CCAliveAnimator s;
    CCAliveTargets lit = targets;
    lit.ring[10].cls = CC_ALIVE_CLASS_3;
    lit.ring[10].role = CC_ALIVE_ROLE_WARM;
    lit.ring[10].alpha = 1.0f;
    for (uint32_t t = 0; t <= 1000; t += 16) s.step(t, 16, lit, palette, ringE, buttonE);
    CCAliveEffect down = cc_alive_effect(CC_FX_DOWN, 1000);
    down.at = 10.0f;
    s.play(down);
    std::memset(&lit.ring, 0, sizeof(lit.ring));
    lit.offline = true;
    s.step(1016, 16, lit, palette, ringE, buttonE);
    const double knee = 0.78 + 0.22 * (1.0 - std::exp(-1.0));   // tone() of a channel at 1.0
    require(near(ringE[10][0], knee, 2e-3) && near(ringE[10][1], palette.warm[1] * knee, 2e-3),
            "down holds the (tone-mapped) snapshot at the cursor at ms 16");
    s.step(2100, 50, lit, palette, ringE, buttonE);
    require(ringE[10][0] > 0.05f, "the ember still glows at 1100 ms");
    s.step(2250, 50, lit, palette, ringE, buttonE);
    require(ringE[10][0] < 1e-3f, "the ember has died at 1250 ms");
    downSnapshotChecks(palette);
}

// Sleep timing (6.1) and the wake effect, through the engine.
void sleepChecks() {
    static CCAlive engine;
    engine.reset(0);
    CCFrame home = volume(54);
    engine.claim(100);
    engine.render(100, &home, -1, -1);
    require(!engine.asleep() && engine.claimed(), "claim: awake");
    engine.render(5099, &home, -1, -1);
    require(!engine.asleep(), "awake 1 ms before 5000 ms");
    engine.render(5100, &home, -1, -1);
    require(engine.asleep(), "asleep 5000 ms after the claim (an input)");
    require(countType(engine.animator(), CC_FX_WAKE) == 0, "no wake while falling asleep");
    engine.detent(6000, 1);
    engine.render(6000, &home, -1, -1);
    require(!engine.asleep() && countType(engine.animator(), CC_FX_WAKE) == 1 &&
            countType(engine.animator(), CC_FX_TICK) == 1, "a detent wakes: wake + tick");
    engine.render(10999, &home, -1, -1);
    require(!engine.asleep(), "the detent pushed sleep to 11000");
    engine.render(11000, &home, -1, -1);
    require(engine.asleep(), "asleep at 11000");
    // Pending blocks sleep with a 1000 ms recheck.
    CCFrame pendingHome = volume(60, true, 40);
    engine.press(12000, 1);
    engine.render(12000, &home, -1, -1);
    require(!engine.asleep() && countType(engine.animator(), CC_FX_PRESS) == 1, "a press wakes");
    engine.render(16999, &pendingHome, -1, -1);
    require(!engine.asleep() && engine.targets().pending, "pending (displayed != confirmed)");
    engine.render(17000, &pendingHome, -1, -1);
    require(!engine.asleep(), "pending at the deadline: recheck in 1000 ms");
    engine.render(17500, &home, -1, -1);
    require(!engine.asleep(), "not before the recheck");
    engine.render(18000, &home, -1, -1);
    require(engine.asleep(), "asleep at the 1000 ms recheck once no longer pending");
    // Pending while asleep: effectiveAsleep false (and a wake), stateAsleep kept.
    engine.render(18100, &pendingHome, -1, -1);
    require(!engine.asleep() && countType(engine.animator(), CC_FX_WAKE) == 1, "pending forces awake (wake plays)");
    engine.render(18200, &home, -1, -1);
    require(engine.asleep(), "back to rest once the answer lands");
    // A flash forces awake and blocks sleep.
    CCFrame ok = withFeedback(home, CC_FEEDBACK_OK, 7);
    engine.render(18300, &ok, -1, -1);
    require(!engine.asleep() && engine.flash() == CC_FLASH_OK, "an ok flash forces awake");
    engine.render(18949, &ok, -1, -1);
    require(!engine.asleep() && engine.flash() == CC_FLASH_OK, "ok flash window 650 ms");
    engine.render(18950, &ok, -1, -1);
    require(engine.asleep() && engine.flash() == CC_FLASH_NONE, "flash over: effectively asleep again");
    // External rising edge: input with a 3200 ms sleep.
    CCFrame ext = volume(54, true, 54, true);
    engine.render(20000, &ext, -1, -1);
    require(!engine.asleep() && countType(engine.animator(), CC_FX_SHIMMER) == 1, "EXT wakes and shimmers");
    engine.render(23199, &ext, -1, -1);
    require(!engine.asleep(), "EXT: awake until 3200 ms");
    engine.render(23200, &ext, -1, -1);
    require(engine.asleep(), "EXT: asleep at 3200 ms");
    // Inputs while unclaimed are ignored; release -> offline.
    engine.release(24000);
    engine.detent(24010, 1);
    engine.press(24010, 0);
    engine.render(24016, nullptr, -1, -1);
    require(!engine.asleep() && engine.targets().offline && countType(engine.animator(), CC_FX_DOWN) == 1 &&
            countType(engine.animator(), CC_FX_TICK) == 0 && countType(engine.animator(), CC_FX_PRESS) == 0,
            "release: offline, down, unclaimed inputs ignored");
}

// Revision 2 frame builders (PRESENTATION_V5 3.6 storage): a v5 selection window
// (first = clamp(index - 10, 0, count - 20), VOC-R03), Up next, the Seek lap, lit buttons.
CCFrame listV5(int count, int index, uint8_t layout = CC_LAYOUT_RECENT) {
    CCFrame f = list(count, index, layout == CC_LAYOUT_WINDOWS);
    f.layoutId = layout;
    f.ringFirst = static_cast<uint16_t>(count <= 20 ? 0 : std::max(0, std::min(index - 10, count - 20)));
    const int width = count - f.ringFirst < 20 ? count - f.ringFirst : 20;
    for (int k = 0; k < 20; ++k) f.ringColors[k] = k < width ? accentOf(f.ringFirst + k) : 0u;
    f.ringColorCount = static_cast<uint8_t>(width);
    return f;
}

CCFrame upnext(int count, int index, int now, bool card = false) {
    CCFrame f = listV5(count, index, CC_LAYOUT_UPNEXT);
    std::strcpy(f.mode, "RECENTLY ADDED");
    f.ringNow = now;
    f.ringCard = card;
    return f;
}

CCFrame lap(int t, int d) {
    CCFrame f = transport(1);
    f.layoutId = CC_LAYOUT_SEEK;
    f.ringStyle = CC_RING_LAP;
    f.ringIndex = static_cast<uint16_t>(t);
    f.ringCount = static_cast<uint16_t>(d);
    return f;
}

uint32_t satOf(uint32_t rgb) {
    bool accent = false;
    const uint32_t s = cc_alive_sat(rgb, accent);
    return accent ? s : 0u;
}

int litCount(const CCAliveTargets& t) {
    int n = 0;
    for (int i = 0; i < CC_RING_LEDS; ++i) if (t.ring[i].cls != CC_ALIVE_CLASS_NONE) ++n;
    return n;
}

bool cellIs(const CCAliveCell& c, uint8_t role, uint8_t cls, float alpha, uint32_t rgb = 0) {
    return c.role == role && c.cls == cls && near(c.alpha, alpha, 1e-6) && (role != CC_ALIVE_ROLE_ACCENT || c.rgb == rgb);
}

int slotOf(int j, int c0) { return (((j - c0) * 3) % 60 + 60) % 60; }

CCAliveTargetState stateOf(bool asleep, uint8_t flash = CC_FLASH_NONE, uint32_t pendingMs = 0, int32_t localIndex = -1,
                           bool volFull = false) {
    CCAliveTargetState s;
    s.offline = false;
    s.asleep = asleep;
    s.flash = flash;
    s.pendingMs = pendingMs;
    s.localValue = -1;
    s.localIndex = localIndex;
    s.volFull = volFull;
    return s;
}

// Section 5 targets, written out from ALIVE.md revision 2 (not derived from the engine's code).
void targetChecks() {
    static CCAliveTargets t;
    const CCAliveTargetState awake = stateOf(false), rest = stateOf(true);
    const uint8_t W = CC_ALIVE_ROLE_WARM, A = CC_ALIVE_ROLE_ACCENT, AM = CC_ALIVE_ROLE_AMBER, R = CC_ALIVE_ROLE_RED;
    const uint8_t C1 = CC_ALIVE_CLASS_1, C2 = CC_ALIVE_CLASS_2, C3 = CC_ALIVE_CLASS_3, S = CC_ALIVE_CLASS_S;
    auto seg = [](int k) { return (35 + k) % 60; };

    // 5.1.2 volume [M1, M2, M13].
    CCFrame v54 = volume(54);
    cc_alive_targets(&v54, awake, t);
    require(t.family == CC_ALIVE_HOME && t.cursor == seg(27) && !t.pending && !t.heat, "v54: cursor 35 + 27 = 2");
    require(cellIs(t.ring[2], W, C3, 1.0f) && cellIs(t.ring[36], W, C2, 0.62f) && cellIs(t.ring[25], W, C1, 0.30f) &&
            t.ring[30].cls == CC_ALIVE_CLASS_NONE && litCount(t) == 29, "v54: body 0.62, endpoint 1.0, bound 25 0.30");
    for (int j = 0; j < 4; ++j) require(cellIs(t.buttons[j], W, C2, 0.70f), "Home nav buttons WARM 0.70");
    CCFrame v55 = volume(55);
    cc_alive_targets(&v55, awake, t);
    require(t.cursor == seg(27) && cellIs(t.ring[seg(27)], W, C3, 1.0f) && cellIs(t.ring[seg(28)], W, S, 0.81f) &&
            litCount(t) == 30, "[M13] v55: endpoint 35 + 27, the half-step lights the NEXT segment at 0.81");
    cc_alive_targets(&v55, rest, t);
    require(t.asleep && near(t.ring[seg(28)].alpha, 0.34, 1e-6) && near(t.ring[seg(27)].alpha, 0.34, 1e-6) &&
            near(t.ring[36].alpha, 0.34, 1e-6) && near(t.ring[25].alpha, 0.34, 1e-6) && t.ring[seg(28)].role == W,
            "[user 2026-09-26] resting: one level 0.34 (bound, body, S [D10], endpoint), all WARM");
    require(near(t.buttons[0].alpha, 0.34, 1e-6), "a resting nav button 0.34 [M18, user 2026-09-26]");
    CCFrame v85 = volume(85);
    cc_alive_targets(&v85, awake, t);
    require(cellIs(t.ring[seg(42)], AM, C3, 1.0f) && cellIs(t.ring[seg(43)], AM, S, 0.81f) &&
            cellIs(t.ring[seg(41)], AM, C2, 0.62f) && cellIs(t.ring[seg(40)], AM, C2, 0.62f) &&
            cellIs(t.ring[seg(39)], W, C2, 0.62f), "[M1] v85: the amber body 0.62 and half-step 0.81 like warm");
    CCAliveTargetState full = awake;
    full.volFull = true;
    cc_alive_targets(&v85, full, t);
    require(cellIs(t.ring[seg(41)], AM, C2, 1.0f) && cellIs(t.ring[seg(43)], AM, S, 1.0f) &&
            cellIs(t.ring[seg(39)], W, C2, 0.62f), "[M24] ledVolFull: the semantic body and half-step at 1.00");
    CCFrame v79 = volume(79);
    cc_alive_targets(&v79, awake, t);
    require(cellIs(t.ring[seg(39)], W, C3, 1.0f) && cellIs(t.ring[seg(40)], W, S, 0.81f),
            "[M2] v79: gated on the value too: the half-step at k 40 is WARM (79 < 80)");
    CCFrame v89 = volume(89);
    cc_alive_targets(&v89, awake, t);
    require(cellIs(t.ring[seg(44)], AM, C3, 1.0f) && cellIs(t.ring[seg(45)], AM, S, 0.81f),
            "[M2] v89: the endpoint and half-step are AMBER, not RED (89 < 90)");
    CCFrame v95 = volume(95);
    cc_alive_targets(&v95, awake, t);
    require(t.heat && cellIs(t.ring[seg(47)], R, C3, 1.0f) && t.ring[seg(47)].volRed && t.ring[seg(47)].rgb == 0u &&
            cellIs(t.ring[seg(48)], R, S, 0.81f) && cellIs(t.ring[seg(45)], R, C2, 0.62f) && !t.ring[seg(44)].volRed &&
            t.ring[seg(44)].role == AM, ">= 90 %: RED from k 45 flagged volRed, AMBER 40..44, heat on");
    cc_alive_targets(&v95, rest, t);
    require(!t.heat && t.ring[seg(47)].role == W && !t.ring[seg(47)].volRed, "resting: everything WARM, no heat");
    CCFrame v99 = volume(99), v100 = volume(100);
    cc_alive_targets(&v99, awake, t);
    require(t.cursor == 24 && cellIs(t.ring[24], R, C3, 1.0f) && cellIs(t.ring[25], R, S, 0.81f),
            "[M13] v99: endpoint 24 RED 1.0, half-step 25 RED 0.81 over the bound mark");
    cc_alive_targets(&v100, awake, t);
    require(t.cursor == 25 && cellIs(t.ring[25], R, C3, 1.0f), "v100: endpoint 25 RED 1.0");
    CCFrame v0 = volume(0);
    cc_alive_targets(&v0, awake, t);
    require(t.cursor == 35 && cellIs(t.ring[35], W, C3, 1.0f) && cellIs(t.ring[25], W, C1, 0.30f) && litCount(t) == 2,
            "v0: the endpoint on the lower bound, the upper bound mark");
    CCFrame dec = volume(40, true, 60);                  // pending decrease: k 21..30 class 1 on the confirmed value
    cc_alive_targets(&dec, awake, t);
    require(t.pending && cellIs(t.ring[seg(20)], W, C3, 1.0f) && cellIs(t.ring[seg(21)], W, C1, 0.30f) &&
            cellIs(t.ring[seg(30)], W, C1, 0.30f) && t.ring[seg(31)].cls == CC_ALIVE_CLASS_NONE,
            "pending decrease span on the confirmed value (P4 5.2)");
    CCFrame decAmber = volume(70, true, 96);             // [M2] the span coloured by the confirmed value
    cc_alive_targets(&decAmber, awake, t);
    require(cellIs(t.ring[seg(46)], R, C1, 0.45f) && cellIs(t.ring[seg(41)], AM, C1, 0.45f) &&
            cellIs(t.ring[seg(35)], W, C3, 1.0f), "[M2] the pending-decrease span in col(k, confirmed)");
    CCFrame inc = volume(60, true, 40);                  // pending increase: the span above confirmed is class 1
    cc_alive_targets(&inc, awake, t);
    require(cellIs(t.ring[seg(20)], W, C2, 0.62f) && cellIs(t.ring[seg(21)], W, C1, 0.30f) &&
            cellIs(t.ring[seg(30)], W, C3, 1.0f), "pending increase: 21..29 class 1, endpoint 30");
    CCFrame white95 = volume(95, false);
    cc_alive_targets(&white95, awake, t);
    require(t.ring[seg(47)].role == W && !t.ring[seg(47)].volRed && t.ring[seg(48)].role == W, "white: WARM only [D16]");
    CCFrame notice = volume(61, true, 41, false, CC_OFFLINE);
    notice.layoutId = CC_LAYOUT_NOTICE;
    cc_alive_targets(&notice, awake, t);
    require(litCount(t) == 1 && t.cursor == seg(20) && cellIs(t.ring[seg(20)], W, C1, 0.30f) && !t.pending,
            "Sonos-off notice [D15]: WARM class 1 at 35 + floor(c/2) only [M13], not pending [R1]");
    // 5.2 overrides.
    CCFrame ext = volume(54, true, 54, true);
    cc_alive_targets(&ext, awake, t);
    require(t.ring[1].role == CC_ALIVE_ROLE_BLUE && cellIs(t.ring[2], CC_ALIVE_ROLE_BLUE, CC_ALIVE_CLASS_4, 1.0f) &&
            t.ring[3].role == CC_ALIVE_ROLE_BLUE && t.ring[4].role != CC_ALIVE_ROLE_BLUE, "external: cursor +-1 BLUE 1.0");
    cc_alive_targets(&ext, rest, t);
    require(t.ring[1].role != CC_ALIVE_ROLE_BLUE, "external only while awake");
    cc_alive_targets(&v54, stateOf(false, CC_FLASH_OK), t);
    require(cellIs(t.ring[0], CC_ALIVE_ROLE_GREEN, CC_ALIVE_CLASS_4, 0.5f) && t.ring[1].alpha == 1.0f &&
            t.ring[4].role == CC_ALIVE_ROLE_GREEN && t.ring[4].alpha == 0.5f && t.ring[5].role != CC_ALIVE_ROLE_GREEN,
            "ok flash: cursor-2..+2 GREEN 1 / 0.5");
    cc_alive_targets(&v95, stateOf(false, CC_FLASH_ERR), t);
    require(t.ring[seg(47)].role == R && t.ring[seg(49)].alpha == 0.5f, "err flash: RED");
    CCAliveTargetState offline = awake;
    offline.offline = true;
    cc_alive_targets(&v54, offline, t);
    int marks = 0;
    for (int i = 0; i < CC_RING_LEDS; ++i)
        if (t.ring[i].cls != CC_ALIVE_CLASS_NONE) {
            ++marks;
            require(i % 5 == 0 && cellIs(t.ring[i], AM, C1, 0.12f), "offline marks: AMBER 0.12 at every 5th segment");
        }
    bool buttonsOff = true;
    for (int j = 0; j < 4; ++j) buttonsOff = buttonsOff && t.buttons[j].cls == CC_ALIVE_CLASS_NONE;
    require(marks == 12 && buttonsOff && t.offline && t.family == CC_ALIVE_OFFLINE, "offline: 12 marks, buttons off");

    // 5.3 buttons [M8, M18, M25].
    CCFrame paused = volume(40);
    paused.buttons[0].icon = CC_ICON_PLAY;
    paused.buttons[3].enabled = false;
    cc_alive_targets(&paused, awake, t);
    require(cellIs(t.buttons[0], CC_ALIVE_ROLE_GREEN, C3, 1.0f) && t.pausedPlay, "[M8] paused Play: GREEN 1.0, pausedPlay");
    require(cellIs(t.buttons[3], W, C1, 0.14f), "disabled: WARM 0.14");
    cc_alive_targets(&paused, rest, t);
    require(!t.pausedPlay && cellIs(t.buttons[0], W, C3, 0.34f) && near(t.buttons[3].alpha, 0.26, 1e-6),
            "[M18] resting: 0.34 for awake >= 0.5, 0.26 below [user 2026-09-26]");
    paused.buttons[0].enabled = false;
    cc_alive_targets(&paused, awake, t);
    require(!t.pausedPlay && near(t.buttons[0].alpha, 0.14, 1e-6), "a disabled Play is dim, not paused Play");
    CCFrame win = list(9, 4, true);
    cc_alive_targets(&win, awake, t);
    require(cellIs(t.buttons[0], R, C2, 1.0f) && cellIs(t.buttons[3], CC_ALIVE_ROLE_GREEN, C3, 1.0f),
            "legacy Cancel (slot 0) RED 1.0, Switch GREEN 1.0");
    CCFrame lits = listV5(9, 4, CC_LAYOUT_UPNEXT);
    lits.buttons[1].icon = CC_ICON_SHUFFLE;
    lits.buttons[1].lit = CC_LIT_OFF;
    lits.buttons[2].icon = CC_ICON_HEART;
    lits.buttons[2].lit = CC_LIT_ON;
    lits.buttons[3].icon = CC_ICON_PLAY;
    lits.buttons[0].icon = CC_ICON_BACK;
    cc_alive_targets(&lits, awake, t);
    require(cellIs(t.buttons[0], W, C2, 0.70f) && cellIs(t.buttons[1], W, C1, 0.30f) &&
            cellIs(t.buttons[2], CC_ALIVE_ROLE_PINK, C1, 0.30f) && cellIs(t.buttons[3], CC_ALIVE_ROLE_GREEN, C3, 1.0f),
            "Up next: Back nav 0.70, Shuffle off 0.30, [r2.2][M32] the liked heart PINK 0.30 (tone liked), Play GREEN");
    cc_alive_targets(&lits, rest, t);
    require(near(t.buttons[1].alpha, 0.26, 1e-6) && cellIs(t.buttons[2], W, C1, 0.26f),
            "[M18] off rests at 0.26; [M32] the liked heart rests WARM 0.26 [user 2026-09-26]");
    lits.buttons[2].color = 0x2050A0;                     // row 4 before row 5: never sat()
    cc_alive_targets(&lits, awake, t);
    require(cellIs(t.buttons[2], CC_ALIVE_ROLE_PINK, C1, 0.30f), "[M32] a coloured liked heart stays PINK 0.30");
    lits.buttons[2].color = 0;
    lits.buttons[1].lit = CC_LIT_ON;
    lits.coloredLeds = false;
    cc_alive_targets(&lits, awake, t);
    require(cellIs(t.buttons[1], W, C3, 1.0f) && cellIs(t.buttons[2], CC_ALIVE_ROLE_PINK, C1, 0.30f),
            "on WARM 1.0; [M25] PINK kept under Warm only");
    lits.buttons[2].enabled = false;
    cc_alive_targets(&lits, awake, t);
    require(cellIs(t.buttons[2], W, C1, 0.14f), "disabled beats lit");
    CCFrame snap = listV5(7, 2, CC_LAYOUT_WINDOWS);
    snap.buttons[1].icon = CC_ICON_SNAPLEFT;
    snap.buttons[1].lit = CC_LIT_ON;
    snap.buttons[1].color = 0x2050A0;
    snap.buttons[2].icon = CC_ICON_SNAPRIGHT;
    snap.buttons[0].icon = CC_ICON_BACK;
    cc_alive_targets(&snap, awake, t);
    require(cellIs(t.buttons[1], A, C3, 1.0f, satOf(0x2050A0)) && cellIs(t.buttons[2], W, C2, 0.70f) &&
            cellIs(t.buttons[0], W, C2, 0.70f), "snap: the assigned side in sat(app colour) 1.0 [VOC-D02]; unassigned nav");
    snap.buttons[1].color = 0x808890;
    cc_alive_targets(&snap, awake, t);
    require(cellIs(t.buttons[1], W, C3, 1.0f), "a grey snap colour (sat fallback) is WARM 1.0");
    snap.buttons[1].color = 0x2050A0;
    snap.coloredLeds = false;
    cc_alive_targets(&snap, awake, t);
    require(cellIs(t.buttons[1], W, C3, 1.0f), "Warm only: the snap colour is WARM 1.0");

    // 5.1.3 lists [M3, M9, M31].
    cc_alive_targets(&win, awake, t);
    const uint32_t sat4 = satOf(accentOf(4));
    require(t.family == CC_ALIVE_WINDOWS && t.cursor == 0 && cellIs(t.ring[0], A, C3, 1.0f, sat4) &&
            cellIs(t.ring[3], A, C1, 0.45f, satOf(accentOf(5))), "list: accents after sat, landmark 0.45, cursor 1.0");
    require(t.tintOn && near(t.tint[0], chan(sat4, 16) / 255.0, 1e-6) && near(t.tint[2], chan(sat4, 0) / 255.0, 1e-6),
            "tint = the cursor accent / 255");
    cc_alive_targets(&win, rest, t);
    require(!t.tintOn && t.ring[0].role == W, "no tint while resting");
    CCFrame grey = list(9, 4);
    grey.ringColors[4] = 0x808080;
    grey.ringColors[5] = 0;
    cc_alive_targets(&grey, awake, t);
    require(cellIs(t.ring[0], W, C3, 1.0f) && !t.tintOn && cellIs(t.ring[3], W, C1, 0.30f),
            "a grey accent and colour 0 are WARM (landmark 0.30); no tint [R2]");
    cc_alive_targets(&win, stateOf(false, CC_FLASH_OK), t);
    require(t.ring[t.cursor].role == CC_ALIVE_ROLE_GREEN && !t.tintOn, "a flash cursor is not an ACCENT: no tint [R2]");
    CCFrame more = list(9, 8, false, 8);
    cc_alive_targets(&more, awake, t);
    require(cellIs(t.ring[slotOf(8, 4)], W, C3, 1.0f) && t.ring[slotOf(8, 4) + 1].cls == CC_ALIVE_CLASS_NONE &&
            litCount(t) == 9, "[M3] a legacy More is one warm item (no second cell)");
    CCFrame na = list(9, 4);
    na.ringUnavailable = (1u << 4) | (1u << 6);
    cc_alive_targets(&na, awake, t);
    require(cellIs(t.ring[0], A, CC_ALIVE_CLASS_Q, 0.45f, sat4) && t.ring[slotOf(6, 4)].cls == CC_ALIVE_CLASS_NONE,
            "[M3] an unavailable cursor keeps its colour at 0.45 (class Q); an unavailable landmark is a gap");
    CCFrame naWin = list(9, 4, true);
    naWin.ringUnavailable = 1u << 4;
    cc_alive_targets(&naWin, awake, t);
    require(cellIs(t.ring[0], A, CC_ALIVE_CLASS_Q, 0.45f, sat4), "... in Windows too (was 1.0 semantic class 2)");
    CCFrame pend = list(9, 4);
    pend.activity = CC_PENDING;
    cc_alive_targets(&pend, stateOf(false, CC_FLASH_NONE, 0), t);
    require(t.pending && cellIs(t.ring[0], A, C3, 1.0f, sat4), "[M3] a pending Recent cursor pulses in its colour (high)");
    cc_alive_targets(&pend, stateOf(false, CC_FLASH_NONE, 260), t);
    require(cellIs(t.ring[0], A, C1, 0.45f, sat4), "... low phase class 1 0.45");
    cc_alive_targets(&pend, stateOf(false, CC_FLASH_NONE, 3000), t);
    require(cellIs(t.ring[0], A, C1, 0.45f, sat4), "... held at class 1 after 3000 ms");
    CCFrame loading = list(11, 3);
    loading.activity = CC_LOADING;
    cc_alive_targets(&loading, awake, t);
    require(t.pending && litCount(t) == 0 && t.cursor == 0, "[M31] a loading list: no cells, the Working comet only");
    CCFrame offStyle = volume(0);
    offStyle.ringStyle = CC_RING_OFF;
    offStyle.layoutId = CC_LAYOUT_RECENT;
    offStyle.activity = CC_LOADING;
    cc_alive_targets(&offStyle, awake, t);
    require(t.pending && litCount(t) == 0, "K1's loading form (style off + loading): comet only");
    CCFrame empty = list(1, 0);
    empty.ringCount = 0;
    cc_alive_targets(&empty, awake, t);
    require(litCount(t) == 0 && t.cursor == 0, "count 0: no cells");
    CCFrame l45 = listV5(45, 30);                       // [M9] first 20, c0 = 29
    cc_alive_targets(&l45, awake, t);
    require(t.cursor == slotOf(30, 29) && cellIs(t.ring[slotOf(30, 29)], A, C3, 1.0f, satOf(accentOf(30))) &&
            cellIs(t.ring[slotOf(20, 29)], A, C1, 0.45f, satOf(accentOf(20))) &&
            cellIs(t.ring[slotOf(39, 29)], A, C1, 0.45f, satOf(accentOf(39))) && litCount(t) == 20,
            "[M9] the 20-entry window re-centred on the transmitted window (c0 = first + 9)");
    // 6.3 local cursor with the [M15] re-centring.
    CCFrame out;
    require(cc_alive_apply_local(l45, 35, 44, out) && out.ringIndex == 35 && out.ringFirst == 20, "local index applied");
    int32_t localValue = 0, localIndex = 0;
    require(cc_alive_local(l45, 35, 44, localValue, localIndex) && localIndex == 35 && localValue == -1,
            "cc_alive_local: the index, no frame copy");
    cc_alive_targets(&l45, stateOf(false, CC_FLASH_NONE, 0, 35), t);
    require(t.cursor == slotOf(35, 34) && cellIs(t.ring[slotOf(35, 34)], A, C3, 1.0f, satOf(accentOf(35))) &&
            cellIs(t.ring[slotOf(25, 34)], A, C1, 0.45f, satOf(accentOf(25))) &&
            t.ring[slotOf(40, 34)].cls == CC_ALIVE_CLASS_NONE && litCount(t) == 15,
            "[M15] local 35: F' 25, c0' 34; entries 40..44 not transmitted yet stay unlit");
    require(cc_alive_apply_local(l45, 44, 44, out), "local 44");
    cc_alive_targets(&l45, stateOf(false, CC_FLASH_NONE, 0, 44), t);
    require(t.cursor == slotOf(44, 34) && cellIs(t.ring[slotOf(44, 34)], W, C3, 1.0f) && !t.tintOn,
            "[M15] an untransmitted local cursor is WARM class 3");
    require(cc_alive_selected_color(l45, 44) == 0 && cc_alive_selected_color(l45) == satOf(accentOf(30)) &&
            cc_alive_selected_color(l45, 35) == satOf(accentOf(35)),
            "6.4 selected accent: sat(acc(index)); 0 when not transmitted");
    CCFrame l9 = list(9, 4);
    require(cc_alive_apply_local(l9, 6, 8, out) && out.ringIndex == 6, "selection: index = local");
    require(!cc_alive_apply_local(l9, 6, 9, out), "selection needs local_max == count - 1");
    require(!cc_alive_apply_local(pend, 6, 8, out) && !cc_alive_apply_local(loading, 6, 10, out),
            "selection: not while pending/loading");

    // 5.1.4 Up next [M14].
    CCFrame q = upnext(12, 0, 4);
    q.ringColors[7] = 0;                                 // a warm (colour 0) upcoming row: Q 0.45 too
    cc_alive_targets(&q, awake, t);
    require(t.family == CC_ALIVE_UPNEXT && t.cursor == slotOf(0, 5) &&
            cellIs(t.ring[slotOf(0, 5)], A, C3, 1.0f, satOf(accentOf(0))) &&
            cellIs(t.ring[slotOf(2, 5)], A, CC_ALIVE_CLASS_P, 0.14f, satOf(accentOf(2))) &&
            cellIs(t.ring[slotOf(4, 5)], A, CC_ALIVE_CLASS_N, 0.70f, satOf(accentOf(4))) &&
            cellIs(t.ring[slotOf(5, 5)], A, CC_ALIVE_CLASS_Q, 0.45f, satOf(accentOf(5))) &&
            cellIs(t.ring[slotOf(7, 5)], W, CC_ALIVE_CLASS_Q, 0.45f) && t.tintOn,
            "Up next: played 0.14, now 0.70, upcoming 0.45 in any role, cursor 1.0; tint");
    q.ringUnavailable = 1u << 5;                         // K1 strips it on upnext; the engine ignores it
    cc_alive_targets(&q, awake, t);
    require(cellIs(t.ring[slotOf(5, 5)], A, CC_ALIVE_CLASS_Q, 0.45f, satOf(accentOf(5))), "no Up next entry is unavailable");
    cc_alive_targets(&q, rest, t);
    require(near(t.ring[slotOf(2, 5)].alpha, 0.34, 1e-6) && near(t.ring[slotOf(4, 5)].alpha, 0.34, 1e-6) &&
            near(t.ring[slotOf(5, 5)].alpha, 0.34, 1e-6), "resting P, N, Q all 0.34 [user 2026-09-26]");
    CCFrame card = upnext(6, 5, 4, true);
    cc_alive_targets(&card, awake, t);
    require(t.cursor == slotOf(5, 2) && t.ring[slotOf(5, 2)].cls == CC_ALIVE_CLASS_NONE && litCount(t) == 5 && !t.tintOn &&
            cc_alive_selected_color(card) == 0, "[M14] focus on the card: no landmark, no cursor cell; moments at its slot");
    card.ringIndex = 4;
    card.ringColors[5] = 0x10E020;                       // the card's colour slot is ignored
    cc_alive_targets(&card, awake, t);
    require(cellIs(t.ring[slotOf(4, 2)], A, C3, 1.0f, satOf(accentOf(4))) && t.ring[slotOf(5, 2)].cls == CC_ALIVE_CLASS_NONE,
            "the card never draws, whatever its colour");

    // 5.1.5 Tracks and 5.1.6 the Seek lap.
    CCFrame tr = transport(2);
    cc_alive_targets(&tr, awake, t);
    require(t.family == CC_ALIVE_TRACKS && t.cursor == 8 && cellIs(t.ring[7], W, C3, 1.0f) && cellIs(t.ring[0], W, C1, 0.30f) &&
            cellIs(t.ring[52], W, C1, 0.30f), "transport Next: all WARM");
    tr = transport(0);
    cc_alive_targets(&tr, awake, t);
    require(t.cursor == 52 && cellIs(t.ring[53], W, C3, 1.0f), "[M4] the Prev cursor stays 52");
    tr = transport(1);
    tr.activity = CC_PENDING;
    cc_alive_targets(&tr, stateOf(false, CC_FLASH_NONE, 300), t);
    require(t.cursor == 0 && cellIs(t.ring[0], W, C1, 0.30f), "the selected Tracks cell pulses");
    CCFrame seek = lap(74, 300);
    cc_alive_targets(&seek, awake, t);
    require(t.family == CC_ALIVE_TRACKS && t.style == CC_RING_LAP && t.cursor == 14 && cellIs(t.ring[14], W, C3, 1.0f) &&
            cellIs(t.ring[0], W, C2, 0.62f) && cellIs(t.ring[13], W, C2, 0.62f) && cellIs(t.ring[15], W, C1, 0.30f) &&
            t.ring[16].cls == CC_ALIVE_CLASS_NONE && cellIs(t.ring[20], W, C1, 0.30f) && cellIs(t.ring[55], W, C1, 0.30f) &&
            t.ring[59].cls == CC_ALIVE_CLASS_NONE && litCount(t) == 24,
            "the lap: T 74 of 300 -> head 14, 0..13 at 0.62, 15, 20, ... 55 at 0.30 (ALIVE 5.1.6 example)");
    seek.activity = CC_PENDING;
    cc_alive_targets(&seek, stateOf(false, CC_FLASH_NONE, 300), t);
    require(t.pending && cellIs(t.ring[14], W, C3, 1.0f), "[M28] Jumping...: the comet, no pulse on the lap");
    seek = lap(297, 300);
    cc_alive_targets(&seek, awake, t);
    require(t.cursor == 59 && cellIs(t.ring[58], W, C2, 0.62f), "T_end: head 59");
    require(!cc_alive_apply_local(seek, 3, 5, out), "[M11] no local cursor on the lap");
    CCFrame ex = listV5(24, 3, CC_LAYOUT_EXPLORER);
    cc_alive_targets(&ex, awake, t);
    require(t.family == CC_ALIVE_EXPLORER && t.tintOn, "explorer: its own family, tinted");
    // The palette roles through the animator are checked by paletteRoleChecks().
}

// Event detection (6.2, 6.4) through the engine.
void eventChecks() {
    static CCAlive engine;
    engine.reset(0);
    require(countType(engine.animator(), CC_FX_REVEAL) == 1 && engine.targets().offline, "reset: offline + reveal");
    CCFrame home = volume(54);
    CCFrame seeded = withFeedback(home, CC_FEEDBACK_OK, 3);
    engine.render(0, nullptr, -1, -1);
    engine.claim(1000);
    engine.render(1000, &seeded, -1, -1, extraOf(1));
    const CCAliveEffect* boot = lastOf(engine.animator(), CC_FX_BOOT);
    require(boot && boot->home && boot->t0 == 1000, "claim: boot on the first frame, home = Home");
    require(countType(engine.animator(), CC_FX_BLOOM) == 0 && engine.flash() == CC_FLASH_NONE &&
            countType(engine.animator(), CC_FX_REVEAL) == 0, "the first frame only seeds (no flash, no reveal)");
    engine.render(1016, &seeded, -1, -1, extraOf(1));
    require(countType(engine.animator(), CC_FX_BLOOM) == 0, "the seeded seq never flashes");
    // Feedback ok -> bloom at the new cursor; err -> fail; skip -> sweep.
    CCFrame ok = withFeedback(home, CC_FEEDBACK_OK, 4);
    engine.render(1100, &ok, -1, -1, extraOf(1));
    const CCAliveEffect* bloom = lastOf(engine.animator(), CC_FX_BLOOM);
    require(bloom && bloom->at == 2.0f && engine.flash() == CC_FLASH_OK, "ok: bloom at the cursor + flash");
    require(engine.animator().effect(0).killed, "bloom (FG) kills the boot");
    CCFrame err = withFeedback(volume(60), CC_FEEDBACK_ERR, 5);
    engine.render(1200, &err, -1, -1, extraOf(1));
    const CCAliveEffect* fail = lastOf(engine.animator(), CC_FX_FAIL);
    require(fail && fail->at == 5.0f && engine.flash() == CC_FLASH_ERR, "err: fail at the new cursor");
    CCFrame skip = withFeedback(transport(1), CC_FEEDBACK_OK, 6);
    engine.render(1300, &skip, -1, -1, extraOf(-1, -1));
    const CCAliveEffect* sweep = lastOf(engine.animator(), CC_FX_SWEEP);
    require(sweep && sweep->dir == -1 && sweep->at == 5.0f && countType(engine.animator(), CC_FX_REVEAL) == 1,
            "ok with skip -1: sweep anticlockwise from the PREVIOUS cursor [D9][M21]; the mode change reveals");
    // Recent with an accent, then ok on Home: wash with the previous accent at the previous cursor [D7].
    CCFrame recent = list(9, 6);
    engine.render(1400, &recent, -1, -1);
    CCFrame recentPending = recent;
    recentPending.activity = CC_PENDING;
    engine.render(1450, &recentPending, -1, -1);
    CCFrame started = withFeedback(home, CC_FEEDBACK_OK, 7);
    engine.render(1500, &started, -1, -1, extraOf(1));
    const CCAliveEffect* wash = lastOf(engine.animator(), CC_FX_WASH);
    bool accent = false;
    const uint32_t sat6 = cc_alive_sat(accentOf(6), accent);
    require(wash && wash->at == 6.0f && near(wash->c[0], chan(sat6, 16) / 255.0, 1e-6) &&
            near(wash->c[1], chan(sat6, 8) / 255.0, 1e-6), "album start from Recent washes its accent [D7]");
    require(countType(engine.animator(), CC_FX_FILL) == 0, "no fill across Recent -> Home [D8]");
    // PLAY/PAUSE between consecutive Home frames that both carry playing.
    engine.render(1600, &home, -1, -1, extraOf(0));
    const CCAliveEffect* drain = lastOf(engine.animator(), CC_FX_DRAIN);
    require(drain && drain->n == 27, "playing true -> false: drain, n = (54 + 1) / 2 = 27");
    CCFrame v55 = volume(55);
    engine.render(1700, &v55, -1, -1, extraOf(1));
    const CCAliveEffect* fill = lastOf(engine.animator(), CC_FX_FILL);
    require(fill && fill->n == 28, "playing false -> true: fill, n = (55 + 1) / 2 = 28");
    engine.render(1800, &v55, -1, -1, extraOf(-1));
    engine.render(1900, &v55, -1, -1, extraOf(0));
    const CCAliveEffect* drain2 = lastOf(engine.animator(), CC_FX_DRAIN);
    require(!drain2 || drain2->t0 != 1900, "an absent playing never fires PLAY/PAUSE");
    // EXT: shimmer from the previous cursor to the new one.
    CCFrame ext = volume(70, true, 70, true);
    engine.render(2000, &ext, -1, -1, extraOf(0));
    const CCAliveEffect* shimmer = lastOf(engine.animator(), CC_FX_SHIMMER);
    require(shimmer && shimmer->from == 2.0f && shimmer->to == 10.0f, "EXT: shimmer from 2 (v55, M13) to 10");
    engine.render(2100, &ext, -1, -1, extraOf(0));
    require(countType(engine.animator(), CC_FX_SHIMMER) == 1, "EXT fires on the rising edge only");
    // Detents: velocity, tick length and direction; local cursor moves the tick.
    engine.detent(3000, 1);
    engine.render(3000, &home, 55, 100, extraOf(0));
    const CCAliveEffect* tick = lastOf(engine.animator(), CC_FX_TICK);
    require(tick && tick->at == 2.0f && tick->len == 0 && engine.velocity() == 0.0f,
            "first detent: vel 0, len 0, at the local cursor (55: 35 + 27 [M13])");
    require(tick && tick->dir == -1, "tick dir = sign(cd(new, old)) (10 -> 2)");
    engine.detent(3020, 1);
    engine.render(3020, &home, 56, 100, extraOf(0));
    tick = lastOf(engine.animator(), CC_FX_TICK);
    require(near(engine.velocity(), 22.5, 1e-4) && tick && tick->len == 7 && tick->dir == 1,
            "20 ms later: vel 22.5, len 7, dir +1");
    engine.detent(3040, 2);
    engine.render(3040, &home, 58, 100, extraOf(0));
    tick = lastOf(engine.animator(), CC_FX_TICK);
    require(tick && tick->dir == 1 && tick->at == 4.0f, "cursor 3 -> 4 (58 %)");
    engine.detent(3060, -1);
    engine.render(3060, &home, 58, 100, extraOf(0));
    tick = lastOf(engine.animator(), CC_FX_TICK);
    require(tick && tick->dir == -1 && tick->at == 4.0f, "cursor unchanged: dir = sign(delta)");
    engine.detent(3600, 2);
    engine.render(3600, &home, 59, 100, extraOf(0));
    require(engine.velocity() == 0.0f, "a gap over 400 ms resets the velocity");
    engine.detent(3650, 2);
    engine.render(3650, &home, 61, 100, extraOf(0));
    require(near(engine.velocity(), 0.45 * 1000.0 * 2.0 / 50.0, 1e-3), "velocity counts |delta|");
    // Limit: bound at the cursor, colour of the cursor target, no tick.
    const int ticks = countType(engine.animator(), CC_FX_TICK);
    CCFrame v100 = volume(100);
    engine.limit(3700, 1);
    engine.render(3700, &v100, -1, -1, extraOf(0));
    const CCAliveEffect* bound = lastOf(engine.animator(), CC_FX_BOUND);
    require(bound && bound->at == 25.0f && bound->dir == 1 && near(bound->c[0], 1.0, 1e-6) &&
            near(bound->c[1], 0.0, 1e-6) && countType(engine.animator(), CC_FX_TICK) == ticks,
            "limit: bound at 25 in the cursor's RED, no tick [D4]");
    // Press: the slot.
    engine.press(3800, 2);
    engine.render(3800, &home, -1, -1, extraOf(0));
    const CCAliveEffect* press = lastOf(engine.animator(), CC_FX_PRESS);
    require(press && press->n == 2, "press: slot 2");
    // Mode change Home -> Windows reveals; release -> down at the last cursor.
    CCFrame win = list(9, 7, true);
    engine.render(3900, &win, -1, -1);
    require(lastOf(engine.animator(), CC_FX_REVEAL) && lastOf(engine.animator(), CC_FX_REVEAL)->t0 == 3900,
            "MODE: reveal");
    engine.release(4000);
    const CCAliveEffect* down = lastOf(engine.animator(), CC_FX_DOWN);
    require(down && down->at == 9.0f && down->t0 == 4000, "release: down at the last claimed cursor");
    engine.render(4016, nullptr, -1, -1);
    require(engine.targets().offline && !engine.claimed(), "released: offline targets");
    // Claim into Recent: boot with home = false.
    engine.claim(5000);
    engine.render(5000, &win, -1, -1);
    boot = lastOf(engine.animator(), CC_FX_BOOT);
    require(boot && !boot->home && boot->t0 == 5000, "claim into Windows: boot home = false");
    const CCAliveEffect* downNow = lastOf(engine.animator(), CC_FX_DOWN);
    require(downNow && downNow->killed && downNow->kill == 5000, "boot kills the running down");
    // A claimed render without a frame: dark targets, no events, the flash window still ends.
    CCFrame okWin = withFeedback(win, CC_FEEDBACK_OK, 9);
    engine.render(6100, &okWin, -1, -1);
    require(engine.flash() == CC_FLASH_OK, "ok flash on Windows");
    engine.render(6200, nullptr, -1, -1);
    require(engine.claimed() && !engine.targets().offline && engine.targets().ring[9].cls == CC_ALIVE_CLASS_NONE &&
            engine.flash() == CC_FLASH_OK, "claimed without a frame: dark, flash running");
    engine.render(6750, nullptr, -1, -1);
    require(engine.flash() == CC_FLASH_NONE, "the flash window ends without frames too");
    // Detents at the frame of the claim: no previous cursor, dir = sign(delta).
    engine.release(7000);
    engine.claim(7100);
    engine.detent(7100, -1);
    engine.render(7100, &home, -1, -1);
    const CCAliveEffect* first = lastOf(engine.animator(), CC_FX_TICK);
    require(first && first->dir == -1 && first->at == 2.0f && countType(engine.animator(), CC_FX_REVEAL) == 0,
            "a detent on the seeding frame ticks with sign(delta); no MODE event");
}

// [D19] 6.2 tick length ties: len = round(x + 1e-4), x = clamp((vel - 4)/14) * 7, so the exact
// .5 ties that whole-ms detent gaps produce round up in float32 (here) and float64 (the desktop)
// alike. Pinned side effect of D19: a pre-round value less than 1e-4 below a tie rounds up too,
// where exact Math.round rounds down; 1.8e-4 below, it rounds down. Mirrors
// test_alive_lights.py test_tick_length_tie_rule.
int tieLength(const uint32_t* gaps, int count) {
    static CCAlive engine;
    engine.reset(0);
    CCFrame home = volume(54);
    engine.claim(1000);
    engine.render(1000, &home, -1, -1);
    uint32_t t = 2000;
    engine.detent(t, 1);                                  // the first detent: velocity 0
    engine.render(t, &home, 55, 100);
    for (int k = 0; k < count; ++k) {
        t += gaps[k];
        engine.detent(t, 1);
        engine.render(t, &home, 56 + k, 100);
    }
    const CCAliveEffect* tick = lastOf(engine.animator(), CC_FX_TICK);
    return tick && tick->t0 == t ? tick->len : -1;
}

void tieChecks() {
    const uint32_t tie[] = {90}, window[] = {83, 223}, below[] = {224, 57};
    require(CCAliveSpec::tickTieBias == 1.0e-4f, "tickTieBias is 1e-4 [D19] (as the Python twin)");
    require(tieLength(tie, 1) == 1, "exact tie x = 0.5 (vel 5): len 1, half up as Math.round in exact arithmetic");
    require(tieLength(window, 2) == 1, "x = 0.4999325 (inside the 1e-4 window below the tie): len 1 (Math.round: 0)");
    require(tieLength(below, 2) == 2, "x = 2.4998238 (1.8e-4 below the tie): len 2, as Math.round");
}

// Song hand (8.4) and the animating() flag.
void songChecks() {
    static CCAlive engine;
    engine.reset(0);
    CCFrame home = volume(54);
    engine.claim(0);
    engine.setProgress(0, 60000, 240000);
    engine.render(0, &home, -1, -1, extraOf(1));
    require(engine.targets().songProg < 0.0f, "no song hand while awake");
    for (uint32_t t = 16; t <= 4500; t += 16) engine.render(t, &home, -1, -1, extraOf(1));
    require(!engine.animating(), "awake, idle, converged: not animating");
    engine.render(5000, &home, -1, -1, extraOf(1));
    require(engine.asleep() && near(engine.targets().songProg, 65000.0 / 240000.0, 1e-5), "asleep: hand at pos/dur");
    require(engine.ringE()[16][0] == 0.0f && engine.ringE()[16][1] == 0.0f && engine.ringE()[16][2] == 0.0f,
            "[user 2026-09-26] the hand is latched but not drawn at rest (segment 16 stays dark)");
    require(engine.animating(), "resting counts as animating");
    engine.render(8000, &home, -1, -1, extraOf(0));   // paused: freeze
    require(engine.targets().songProg < 0.0f, "hidden once a Home frame says playing:false");
    engine.render(20000, &home, -1, -1, extraOf(1));
    require(near(engine.targets().songProg, 68000.0 / 240000.0, 1e-5), "resumed from the frozen position");
    engine.render(21000, &home, -1, -1, extraOf(1));
    require(near(engine.targets().songProg, (68000.0 + 1000.0) / 240000.0, 1e-5),
            "progress froze while paused and resumes from there");
    engine.setProgress(21000, 0, 0);
    engine.render(21016, &home, -1, -1, extraOf(1));
    require(engine.targets().songProg < 0.0f, "dur 0 clears the hand");
    CCFrame recent = list(9, 4);
    engine.setProgress(22000, 1000, 2000);
    engine.render(22000, &recent, -1, -1);
    require(engine.targets().songProg < 0.0f, "no hand outside Home");
    engine.render(40000, &home, -1, -1, extraOf(1));
    engine.render(46000, &home, -1, -1, extraOf(1));
    require(engine.asleep() && engine.targets().songProg == 1.0f, "progress clamps at 1");
    // [R3] a Home frame without playing counts as not playing: the hand hides and the progress
    // freezes, as with playing:false; a later true resumes from the frozen position.
    engine.setProgress(46000, 10000, 100000);
    engine.render(47000, &home, -1, -1, extraOf(1));
    require(engine.asleep() && near(engine.targets().songProg, 11000.0 / 100000.0, 1e-5), "hand at 11 s");
    engine.render(48000, &home, -1, -1, extraOf(-1));
    require(engine.asleep() && engine.targets().songProg < 0.0f, "an absent playing hides the hand [R3]");
    engine.render(60000, &home, -1, -1, extraOf(-1));
    require(engine.targets().songProg < 0.0f, "still hidden while playing stays absent [R3]");
    engine.render(61000, &home, -1, -1, extraOf(1));
    require(engine.asleep() && near(engine.targets().songProg, 12000.0 / 100000.0, 1e-5),
            "an absent playing froze the progress at 12 s; true resumes from there [R3]");
    engine.render(62000, &home, -1, -1, extraOf(1));
    require(near(engine.targets().songProg, 13000.0 / 100000.0, 1e-5), "and runs again");
    // A Home family that never said playing: no hand (the new session's first frames omit it).
    engine.release(63000);
    engine.claim(63100);
    engine.render(63100, &home, -1, -1, extraOf(-1));
    engine.render(70000, &home, -1, -1, extraOf(-1));
    require(engine.asleep() && engine.targets().songProg < 0.0f, "no hand while playing is only ever absent [R3]");
}

// [R1] The Home Sonos-off notice with a stale request (displayed 61 != confirmed 41) is never
// pending: no Working comet, and it rests at the 5000 ms deadline instead of re-checking.
void noticeRestChecks() {
    static CCAlive engine;
    engine.reset(0);
    CCFrame notice = volume(61, true, 41, false, CC_OFFLINE);
    notice.layoutId = CC_LAYOUT_NOTICE;
    engine.claim(0);
    engine.render(0, &notice, -1, -1, extraOf(-1));
    require(!engine.asleep() && !engine.targets().pending, "notice: awake after the claim, not pending [R1]");
    engine.render(4999, &notice, -1, -1, extraOf(-1));
    engine.render(5000, &notice, -1, -1, extraOf(-1));
    require(engine.asleep() && !engine.targets().pending, "notice: rests at the deadline (not pending) [R1]");
    CCFrame stale = volume(61, true, 41);                 // the same request with Sonos up: pending
    engine.render(5100, &stale, -1, -1, extraOf(-1));
    require(!engine.asleep() && engine.targets().pending, "the same stale request on the volume layout is pending");
}

CCFrame withMoment(CCFrame f, uint32_t seq, uint8_t moment, uint32_t color = 0, int8_t side = 0) {
    f = withFeedback(f, CC_FEEDBACK_OK, seq);
    f.feedbackMoment = moment;
    f.feedbackColor = color;
    f.feedbackSide = side;
    return f;
}

bool colourIs(const float (&c)[3], const float (&want)[3], double tol = 1e-6) {
    return near(c[0], want[0], tol) && near(c[1], want[1], tol) && near(c[2], want[2], tol);
}

bool colourIsRgb(const float (&c)[3], uint32_t rgb) {
    return near(c[0], chan(rgb, 16) / 255.0, 1e-6) && near(c[1], chan(rgb, 8) / 255.0, 1e-6) &&
           near(c[2], chan(rgb, 0) / 255.0, 1e-6);
}

// [r2] 6.4 rows c-h (the feedback moments), row i on the new list families, MODE on transport <-> lap,
// 6.5 reduced motion, the [M22] hold, the [M5] PRNG and set_tuning, through the engine.
void momentChecks() {
    static CCAlive engine;
    engine.reset(0);
    require(engine.rng() == CCAliveSpec::rngSeed && !engine.reducedMotion() && !engine.volFull(), "reset: seeded PRNG");
    CCFrame q = upnext(12, 6, 4);
    engine.claim(0);
    engine.render(0, &q, -1, -1);
    engine.render(3000, &q, -1, -1);
    const float cursor = static_cast<float>(engine.cursor());
    // c: queued -> a sweep from 12 o'clock, clockwise; no flash; the hold (640).
    CCFrame f = withMoment(q, 1, CC_MOMENT_QUEUED);
    engine.render(3100, &f, -1, -1);
    const CCAliveEffect* sweep = lastOf(engine.animator(), CC_FX_SWEEP);
    require(sweep && sweep->t0 == 3100 && sweep->at == 0.0f && sweep->dir == 1 && engine.flash() == CC_FLASH_NONE &&
            engine.holdMs() == 640, "c queued: sweep at 0, dir +1, no flash [M7], hold 640 [M22]");
    // d: shuffle -> one PRNG draw, then scatter with the seed.
    f = withMoment(q, 2, CC_MOMENT_SHUFFLE);
    engine.render(3200, &f, -1, -1);
    const uint32_t rng1 = cc_alive_xorshift32(CCAliveSpec::rngSeed);
    const CCAliveEffect* scatter = lastOf(engine.animator(), CC_FX_SCATTER);
    require(engine.rng() == rng1 && scatter && scatter->seed == cc_alive_scatter_seed(rng1) && scatter->at == cursor &&
            scatter->seed >= 0.0f && scatter->seed < 60.0f && engine.holdMs() == 700 && engine.flash() == CC_FLASH_NONE,
            "d shuffle: seed = 60 (xorshift32(0x2545F491) >> 8) / 2^24, hold 700");
    require(std::fabs(static_cast<double>(cc_alive_scatter_seed(rng1)) - 60.0 * static_cast<double>(rng1 >> 8) / 16777216.0) <
                4e-6, "the float32 seed is the correctly rounded double evaluation");
    // e: like -> a PINK bloom at the cursor; f: unlike -> nothing, and it ends the running hold.
    f = withMoment(q, 3, CC_MOMENT_LIKE);
    engine.render(3300, &f, -1, -1);
    const CCAliveEffect* bloom = lastOf(engine.animator(), CC_FX_BLOOM);
    require(bloom && bloom->t0 == 3300 && bloom->at == cursor && colourIs(bloom->c, CCAliveSpec::pink) &&
            engine.holdMs() == 900 && engine.flash() == CC_FLASH_NONE, "e like: PINK bloom at the cursor, hold 900");
    const int before = engine.animator().effectCount();
    f = withMoment(q, 4, CC_MOMENT_UNLIKE);
    engine.render(3310, &f, -1, -1);
    require(engine.animator().effectCount() == before && engine.holdMs() == 0 && engine.flash() == CC_FLASH_NONE,
            "f unlike: nothing, no flash, no hold");
    // i on upnext: a plain ok washes the previous selected accent at the previous cursor [D7][M10].
    f = withFeedback(q, CC_FEEDBACK_OK, 5);
    engine.render(3400, &f, -1, -1);
    const CCAliveEffect* wash = lastOf(engine.animator(), CC_FX_WASH);
    require(wash && wash->t0 == 3400 && wash->at == cursor && colourIsRgb(wash->c, satOf(accentOf(6))) &&
            engine.flash() == CC_FLASH_OK && engine.holdMs() == 0, "i: from Up next, the D7 wash with a flash");
    // g: snap -> the half-wash on its side in sat(colour); colour 0 or Warm only -> WARM.
    CCFrame w = listV5(7, 2, CC_LAYOUT_WINDOWS);
    engine.render(3500, &w, -1, -1);
    f = withMoment(w, 6, CC_MOMENT_SNAP, 0x2050A0, -1);
    engine.render(3600, &f, -1, -1);
    const CCAliveEffect* half = lastOf(engine.animator(), CC_FX_HALF);
    require(half && half->side == -1 && colourIsRgb(half->c, satOf(0x2050A0)) && engine.holdMs() == 900 &&
            engine.flash() == CC_FLASH_NONE, "g snap left: half, side -1, sat(colour), hold 900");
    f = withMoment(w, 7, CC_MOMENT_SNAP, 0, 1);
    engine.render(3700, &f, -1, -1);
    half = lastOf(engine.animator(), CC_FX_HALF);
    require(half && half->t0 == 3700 && half->side == 1 && colourIs(half->c, CCAliveSpec::warm), "g snap colour 0: WARM");
    CCFrame wWhite = w;
    wWhite.coloredLeds = false;
    f = withMoment(wWhite, 8, CC_MOMENT_SNAP, 0x2050A0, 1);
    engine.render(3800, &f, -1, -1);
    half = lastOf(engine.animator(), CC_FX_HALF);
    require(half && half->t0 == 3800 && colourIs(half->c, CCAliveSpec::warm), "g snap under Warm only: WARM");
    // h: started -> a wash in the started colour at the new (Home) cursor, or a green bloom when warm;
    // the same render's playing change never fills [M16].
    CCFrame home = volume(54);
    engine.render(3900, &home, -1, -1, extraOf(0));
    f = withMoment(home, 9, CC_MOMENT_STARTED, 0x3080F0);
    engine.render(4000, &f, -1, -1, extraOf(1));
    wash = lastOf(engine.animator(), CC_FX_WASH);
    require(wash && wash->t0 == 4000 && wash->at == 2.0f && colourIsRgb(wash->c, satOf(0x3080F0)) &&
            engine.holdMs() == 1100 && !lastOf(engine.animator(), CC_FX_FILL), "h started: wash at the Home cursor, no fill");
    f = withMoment(home, 10, CC_MOMENT_STARTED, 0);
    engine.render(4100, &f, -1, -1, extraOf(0));
    bloom = lastOf(engine.animator(), CC_FX_BLOOM);
    require(bloom && bloom->t0 == 4100 && colourIs(bloom->c, CCAliveSpec::green) && engine.holdMs() == 900 &&
            !lastOf(engine.animator(), CC_FX_DRAIN), "h started warm: green bloom [M16], no drain");
    // b wins over a moment (a legacy frame with both); the skip sweeps from the previous cursor [M21].
    CCFrame tr = transport(1);
    engine.render(4200, &tr, -1, -1);
    CCFrame skip = withMoment(transport(1), 11, CC_MOMENT_LIKE);
    engine.render(4300, &skip, -1, -1, extraOf(-1, 1));
    sweep = lastOf(engine.animator(), CC_FX_SWEEP);
    require(sweep && sweep->t0 == 4300 && sweep->dir == 1 && sweep->at == 0.0f && engine.flash() == CC_FLASH_OK,
            "b beats a moment: the skip sweep with its flash");
    // MODE on transport <-> lap (Seek enter / exit); none on an explorer tab switch.
    auto revealAt = [](const CCAlive& en, uint32_t t0) {
        const CCAliveEffect* r = lastOf(en.animator(), CC_FX_REVEAL);
        return r != nullptr && r->t0 == t0;
    };
    CCFrame seek = lap(74, 300);
    engine.render(4400, &seek, -1, -1);
    require(revealAt(engine, 4400), "Seek enter: reveal (tracks: transport -> lap)");
    engine.render(4900, &tr, -1, -1);
    require(revealAt(engine, 4900), "Seek exit: reveal (lap -> transport)");
    CCFrame tab0 = listV5(24, 3, CC_LAYOUT_EXPLORER), tab1 = listV5(2, 0, CC_LAYOUT_EXPLORER);
    tab1.page = 1;
    engine.render(5500, &tab0, -1, -1);
    require(revealAt(engine, 5500), "explorer open: reveal");
    engine.render(5600, &tab1, -1, -1);
    require(!revealAt(engine, 5600) && revealAt(engine, 5500), "an explorer tab switch is no MODE");
    // 6.5 reduced motion: wake/tick/sweep/scatter/reveal dropped; the PRNG still draws; fail stays.
    engine.setReducedMotion(6100, true);
    require(engine.reducedMotion() && engine.animator().reducedMotion(), "setReducedMotion latches");
    const uint32_t rngBefore = engine.rng();
    const int scatters = countType(engine.animator(), CC_FX_SCATTER);
    f = withMoment(tab1, 12, CC_MOMENT_SHUFFLE);
    engine.render(6200, &f, -1, -1);
    require(engine.rng() == cc_alive_xorshift32(rngBefore) && countType(engine.animator(), CC_FX_SCATTER) <= scatters &&
            engine.holdMs() == 700, "rm: the scatter is dropped but the seed is drawn and the hold runs");
    engine.detent(6300, 1);
    engine.render(6300, &tab1, 1, 1);
    require(!lastOf(engine.animator(), CC_FX_TICK) || lastOf(engine.animator(), CC_FX_TICK)->t0 != 6300, "rm: no tick");
    engine.render(6400, &home, -1, -1);
    require(!revealAt(engine, 6400), "rm: no reveal on MODE");
    f = withFeedback(home, CC_FEEDBACK_ERR, 13);
    engine.render(6500, &f, -1, -1);
    require(lastOf(engine.animator(), CC_FX_FAIL) && lastOf(engine.animator(), CC_FX_FAIL)->t0 == 6500 &&
            engine.flash() == CC_FLASH_ERR, "rm: the fail stays (stationary at draw time)");
    engine.setReducedMotion(6600, false);
    // [M22] a moment holds sleep: a like 20 ms before the deadline keeps the knob awake 900 ms.
    static CCAlive sleeper;
    sleeper.reset(0);
    sleeper.claim(0);
    sleeper.render(0, &q, -1, -1);
    f = withMoment(q, 20, CC_MOMENT_LIKE);
    sleeper.render(4980, &f, -1, -1);
    sleeper.render(5000, &f, -1, -1);
    require(!sleeper.asleep(), "a moment hold at the deadline: recheck, awake");
    sleeper.render(5879, &f, -1, -1);
    require(!sleeper.asleep() && sleeper.holdMs() == 900, "still held 899 ms after the moment");
    sleeper.render(6000, &f, -1, -1);
    require(sleeper.asleep() && sleeper.holdMs() == 0, "asleep at the recheck after the hold");
    f = withMoment(q, 21, CC_MOMENT_QUEUED);
    sleeper.render(6100, &f, -1, -1);
    require(!sleeper.asleep() && lastOf(sleeper.animator(), CC_FX_WAKE) &&
            lastOf(sleeper.animator(), CC_FX_WAKE)->t0 == 6100, "a moment forces awake (wake plays)");
    // 3.2 tuning [M24]: ledPink is the OETF of the LED colour; 0 restores the constant.
    engine.setTuning(7000, 0xFF051A, false);
    const float tuned[3] = {static_cast<float>(oetfExact(1.0)), static_cast<float>(oetfExact(5.0 / 255.0)),
                            static_cast<float>(oetfExact(26.0 / 255.0))};
    require(colourIs(engine.palette().pink, tuned, 1e-5) && colourIs(engine.palette().pink, CCAliveSpec::pink, 1e-2),
            "ledPink #FF051A: PINK = the OETF of the LED colour (within one LED count of the constant)");
    engine.setTuning(7000, 0x00FF00, true);
    require(near(engine.palette().pink[0], 0.0, 1e-6) && near(engine.palette().pink[1], 1.0, 1e-5) && engine.volFull(),
            "ledPink #00FF00 -> OETF (0, 1, 0); ledVolFull latched");
    engine.setTuning(7000, 0, false);
    require(colourIs(engine.palette().pink, CCAliveSpec::pink) && !engine.volFull(), "0 restores PINK");
    engine.reset(8000);
    require(engine.rng() == CCAliveSpec::rngSeed, "reset reseeds the PRNG");
}

// 6.2 local input (CCAliveKnob, the firmware HMI's FOC sampler) [F1/W2] and [Q1] (12.5).
bool pushEvents(CCAliveKnob& k, uint32_t now, uint32_t id, int pos, bool pushing, int max, int32_t delta, int8_t limit) {
    const CCAliveKnobEvents e = k.sample(now, id, static_cast<uint16_t>(pos), pushing, static_cast<uint16_t>(max));
    return e.delta == delta && e.limit == limit;
}

// Samples every 10 ms from `from` to `to` (exclusive) with a fixed position and push state; returns
// the limits fired.
int pushRun(CCAliveKnob& k, uint32_t from, uint32_t to, uint32_t id, int pos, bool pushing, int max) {
    int fired = 0;
    for (uint32_t t = from; t < to; t += 10)
        if (k.sample(t, id, static_cast<uint16_t>(pos), pushing, static_cast<uint16_t>(max)).limit) ++fired;
    return fired;
}

void knobChecks() {
    CCAliveKnob k;
    require(!k.valid() && k.id() == 0, "knob: nothing sampled yet");
    require(pushEvents(k, 0, 3, 30, false, 100, 0, 0), "knob: the first sample only seeds");
    require(k.valid() && k.id() == 3 && k.pos() == 30 && k.max() == 100, "knob: the seed is the local position");
    require(pushEvents(k, 10, 3, 35, false, 100, 5, 0), "knob: +5 within one control");
    require(pushEvents(k, 20, 4, 60, false, 100, 0, 0) && k.id() == 4, "knob: a host re-enter (new id) only seeds");
    k.reset();
    require(!k.valid() && k.id() == 0, "knob: reset forgets the control");
    require(pushEvents(k, 30, 4, 45, false, 100, 0, 0), "knob: id 4 reused after a release only seeds [F1/W2]");
    require(pushEvents(k, 40, 4, 46, false, 100, 1, 0), "knob: ... and then counts its own detents");
    // [Q1] the first push after arriving at a bound fires at once (arriving does not set pushing).
    require(pushEvents(k, 50, 4, 100, false, 100, 54, 0), "Q1: arriving at max is a detent, no limit");
    require(pushEvents(k, 60, 4, 100, true, 100, 0, 1), "Q1: the first push fires at once");
    require(pushRun(k, 70, 2060, 4, 100, true, 100) == 0, "Q1: held against the bound for 2 s: one");
    // Spring back for 100 ms, push again: a second bound and lim.
    require(pushRun(k, 2060, 2160, 4, 100, false, 100) == 0 && pushEvents(k, 2160, 4, 100, true, 100, 0, 1),
            "Q1: push, spring back 100 ms, push again: two");
    // A push 60 ms after springing back (under lim_rearm_ms 75): none.
    require(pushRun(k, 2170, 2400, 4, 100, true, 100) == 0 && pushRun(k, 2400, 2460, 4, 100, false, 100) == 0 &&
            pushEvents(k, 2460, 4, 100, true, 100, 0, 0), "Q1: a push 60 ms after springing back: none");
    // The attractor chattering at 20 ms for 300 ms during one push: one.
    int fired = pushRun(k, 2470, 2800, 4, 100, false, 100);
    for (uint32_t t = 2800; t < 3100; t += 20)
        fired += k.sample(t, 4, 100, ((t - 2800) / 20) % 2 == 0, 100).limit ? 1 : 0;
    require(fired == 1, "Q1: attractor chatter at 20 ms for 300 ms during one push: one");
    // The gap: a re-armed push within 150 ms of the previous fire does not fire.
    CCAliveKnob g;
    g.sample(0, 5, 0, false, 40);
    require(pushEvents(g, 10, 5, 0, true, 40, 0, -1) && pushEvents(g, 20, 5, 0, false, 40, 0, 0) &&
            pushEvents(g, 100, 5, 0, true, 40, 0, 0), "Q1: re-armed (90 ms) but 90 ms after the fire: none (lim_gap_ms)");
    require(pushEvents(g, 110, 5, 0, false, 40, 0, 0) && pushEvents(g, 200, 5, 0, true, 40, 0, -1),
            "Q1: at the lower bound, dir -1, once spaced and re-armed");
    CCAliveKnob mid;
    require(pushEvents(mid, 0, 9, 20, false, 40, 0, 0) && pushEvents(mid, 10, 9, 20, true, 40, 0, 0),
            "a push away from both bounds gives no limit");
    // A new control id, a release or a pass without a ready control: the next sample only seeds.
    CCAliveKnob r;
    r.sample(0, 6, 40, false, 40);
    r.sample(10, 6, 40, true, 40);                        // fires
    r.sample(20, 6, 40, false, 40);
    require(pushEvents(r, 200, 7, 40, true, 40, 0, 0), "Q1: a new control id only seeds (even pushing)");
    require(pushEvents(r, 210, 0, 40, true, 40, 0, 0) && !r.valid(), "id 0 is no ready control");
    require(pushEvents(r, 220, 7, 40, true, 40, 0, 0), "after id 0 the same id only seeds");
    r.reset();
    require(pushEvents(r, 400, 7, 40, true, 40, 0, 0), "after a release: seeds");
    require(pushEvents(r, 420, 7, 40, false, 40, 0, 0) && pushEvents(r, 500, 7, 40, true, 40, 0, 1),
            "... then a push 100 ms after the seed's push fires (the seed saw it pushing)");
    CCAliveKnob one;
    require(pushEvents(one, 0, 8, 0, false, 0, 0, 0) && pushEvents(one, 10, 8, 0, true, 0, 0, -1),
            "a one-position control (max 0): limit -1");

    // The HMI flow through the engine: session A ends on control 3; the companion restarts and
    // session B's first ready control is 3 again at another position: no tick, no bound [F1/W2].
    static CCAlive engine;
    engine.reset(0);
    CCAliveKnob hmi;
    const CCFrame a = volume(30);
    engine.claim(0);
    hmi.reset();
    engine.render(0, &a, -1, -1, extraOf(1));
    uint32_t now = 16;
    CCAliveKnobEvents e = hmi.sample(now, 3, 30, false, 100);
    engine.render(now, &a, hmi.pos(), hmi.max(), extraOf(1));
    require(e.delta == 0 && e.limit == 0, "knob flow: session A seeds");
    now += 16;
    e = hmi.sample(now, 3, 35, false, 100);
    if (e.delta) engine.detent(now, e.delta);
    engine.render(now, &a, hmi.pos(), hmi.max(), extraOf(1));
    require(e.delta == 5 && countType(engine.animator(), CC_FX_TICK) == 1, "knob flow: session A's turn ticks");
    now += 3000;
    engine.render(now, &a, hmi.pos(), hmi.max(), extraOf(1));
    engine.release(now);
    hmi.reset();
    engine.render(now + 16, nullptr, 0, -1);
    now += 5000;
    engine.render(now, nullptr, 0, -1);
    require(countType(engine.animator(), CC_FX_TICK) == 0, "knob flow: no tick left from session A");
    const CCFrame b = volume(45);
    engine.claim(now);
    hmi.reset();
    engine.render(now, &b, -1, -1, extraOf(1));
    now += 16;
    e = hmi.sample(now, 3, 45, true, 100);
    if (e.delta) engine.detent(now, e.delta);
    if (e.limit) engine.limit(now, e.limit);
    engine.render(now, &b, hmi.pos(), hmi.max(), extraOf(1));
    require(e.delta == 0 && e.limit == 0, "knob flow: session B's first ready sample of reused id 3 only seeds");
    require(countType(engine.animator(), CC_FX_TICK) == 0 && countType(engine.animator(), CC_FX_BOUND) == 0,
            "knob flow: no tick or bound at session B's claim");
}

// The animator draws the palette roles with the section 2 floats (never rounded to 8 bits):
// a converged AMBER / WARM / RED target is tone(palette colour * alpha).
void paletteRoleChecks() {
    static CCAliveTargets t;
    static CCAliveAnimator animator;
    const CCAliveTargetState awake = stateOf(false);
    const CCAlivePalette palette = cc_alive_palette();
    CCFrame v95 = volume(95);
    cc_alive_targets(&v95, awake, t);
    t.heat = false;                                        // no embers: a steady target
    animator.reset();
    CCAliveRingE ringE;
    CCAliveButtonE buttonE;
    for (uint32_t now = 0; now <= 3000; now += 16) animator.step(now, 16, t, palette, ringE, buttonE);
    const int amberAt = (35 + 42) % 60, redAt = (35 + 48) % 60, warmAt = 36;
    require(t.ring[amberAt].role == CC_ALIVE_ROLE_AMBER && t.ring[redAt].role == CC_ALIVE_ROLE_RED &&
            t.ring[warmAt].role == CC_ALIVE_ROLE_WARM, "volume 95: AMBER, RED and WARM targets");
    double worst = 0.0;
    const struct { int at; const float* c; double a; } cells[3] = {
        {amberAt, CCAliveSpec::amber, t.ring[amberAt].alpha}, {redAt, CCAliveSpec::red, t.ring[redAt].alpha},
        {warmAt, CCAliveSpec::warm, t.ring[warmAt].alpha}};
    for (const auto& cell : cells) {
        double e[3] = {cell.c[0] * cell.a, cell.c[1] * cell.a, cell.c[2] * cell.a};
        toneRef(e);
        for (int q = 0; q < 3; ++q) worst = std::fmax(worst, std::fabs(ringE[cell.at][q] - e[q]));
    }
    double b[3] = {CCAliveSpec::warm[0] * 0.70, CCAliveSpec::warm[1] * 0.70, CCAliveSpec::warm[2] * 0.70};
    toneRef(b);
    for (int q = 0; q < 3; ++q) worst = std::fmax(worst, std::fabs(buttonE[1][q] - b[q]));
    require(worst < 1e-5, "converged palette-role targets draw the section 2 floats (max error " + num(worst) + ")");
}

// Per-frame cost on this PC (MSVC /O2): render + output of a busy frame.
void costChecks() {
    static CCAlive engine;
    engine.reset(0);
    CCFrame busy = volume(95, true, 60);          // pending (comet) + heat embers
    engine.claim(0);
    uint32_t ring[CC_RING_LEDS], buttons[4];
    const int frames = 20000;
    double worst = 0.0, total = 0.0;
    uint32_t now = 0;
    for (int k = 0; k < frames; ++k) {
        now += 16;
        if (k % 20 == 0) engine.detent(now, 1);
        if (k % 40 == 0) engine.press(now, static_cast<uint8_t>(k % 4));
        CCFrame f = busy;
        if (k % 60 == 0) f = withFeedback(busy, (k / 60) % 2 ? CC_FEEDBACK_OK : CC_FEEDBACK_ERR,
                                          static_cast<uint32_t>(k / 60 + 1));
        const auto start = std::chrono::steady_clock::now();
        engine.render(now, &f, -1, -1, extraOf(1));
        engine.output(150, CCAliveSpec::defaultDither, ring, buttons);   // the default path (F-T)
        const double us = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - start).count();
        total += us;
        if (k > 100) worst = std::fmax(worst, us);
    }
    std::printf("cost: render + output %.2f us/frame mean, %.1f us max over %d busy frames (PC, MSVC /O2)\n",
                total / frames, worst, frames);
    require(total / frames < 200.0, "per-frame cost sane on the PC");
}

// ------------------------------------------------------------- part 2: design oracle
struct OracleStats {
    int cases, steps, compared, skipped, failedCases, uncapped, dropped;
    long long values;
    double worst, tolerance;
    // [user 2026-09-26] expect.bytes: section 9 at drive 150, dither off, with the F-T floor.
    int byteSteps, worstByte;
    long long byteValues, floored, band;
};

// [user 2026-09-26] ALIVE.md 11.1 / 11.2 with 9 step 4: the knob's output stage (cc_alive_output,
// float32, the LUT EOTF) on the oracle's own e (expect ring / buttons, rounded to 1e-5) and the
// masks of the step's persistent view (cc_alive_lit of the view's targets: entry non-null, a > 0)
// against the oracle's float64 bytes (tests/js referenceOutput()): every channel within 1, and the
// floor decision identical outside a band of kFloorBand counts around the 0.5-count threshold: where
// the oracle floored a lit LED (0 < m < 0.5 - band) the knob floors it too (visible, every channel
// <= 1), with one count on the dominant channel (v_c == m) and 0 on every channel whose v / m is more
// than the band below 1 (a near-tie may split between float64 and float32).
constexpr double kFloorBand = 1e-3;

bool oracleBytes(JsonObjectConst expect, const CCAliveTargets& targets, OracleStats& s, std::string& bad) {
    JsonArrayConst ring = expect["ring"].as<JsonArrayConst>(), buttons = expect["buttons"].as<JsonArrayConst>();
    JsonArrayConst bytes = expect["bytes"].as<JsonArrayConst>();
    if (bytes.size() != 64 || ring.size() != 60 || buttons.size() != 4) {
        bad = "expect.bytes needs 64 values (regenerate the oracle fixture)";
        return false;
    }
    static CCAliveRingE ringE;
    static CCAliveButtonE buttonE;
    double lin[64][3], total = 0.0;
    for (int k = 0; k < 64; ++k) {
        JsonArrayConst e = k < 60 ? ring[k].as<JsonArrayConst>() : buttons[k - 60].as<JsonArrayConst>();
        for (int c = 0; c < 3; ++c) {
            const double x = e[c].as<double>();
            if (k < 60) ringE[k][c] = static_cast<float>(x); else buttonE[k - 60][c] = static_cast<float>(x);
            lin[k][c] = eotfExact(x) * 150.0;
        }
        total += (k < 60 ? 1.0 : 2.0) * (lin[k][0] + lin[k][1] + lin[k][2]);
    }
    const double limit = total > 16920.0 ? 16920.0 / total : 1.0;
    uint64_t ringLit = 0;
    uint8_t buttonLit = 0;
    cc_alive_lit(targets, ringLit, buttonLit);
    CCAliveDither residual;
    std::memset(&residual, 0, sizeof(residual));
    uint32_t outRing[CC_RING_LEDS], outButtons[4];
    cc_alive_output(ringE, buttonE, 150, false, residual, outRing, outButtons, ringLit, buttonLit);
    ++s.byteSteps;
    for (int k = 0; k < 64; ++k) {
        const uint32_t want = bytes[static_cast<size_t>(k)].as<uint32_t>(), got = k < 60 ? outRing[k] : outButtons[k - 60];
        const std::string led = k < 60 ? "ring[" + num(k) + "]" : "button[" + num(k - 60) + "]";
        for (int shift = 16; shift >= 0; shift -= 8) {
            const int diff = std::abs(chan(want, shift) - chan(got, shift));
            ++s.byteValues;
            if (diff > s.worstByte) s.worstByte = diff;
            if (diff > 1) {
                bad = "bytes " + led + " oracle " + hex(want) + ", knob " + hex(got);
                return false;
            }
        }
        const bool lit = k < 60 ? ((ringLit >> k) & 1u) != 0u : ((buttonLit >> (k - 60)) & 1u) != 0u;
        const double v[3] = {lin[k][0] * limit, lin[k][1] * limit, lin[k][2] * limit};
        const double m = std::fmax(v[0], std::fmax(v[1], v[2]));
        if (!lit || !(m > 0.0) || m >= 0.5 + kFloorBand) continue;
        if (m > 0.5 - kFloorBand) {
            ++s.band;
            continue;
        }
        ++s.floored;                                   // the oracle floored this lit LED
        bool same = want != 0u && got != 0u;
        for (int c = 0, shift = 16; c < 3; ++c, shift -= 8) {
            same = same && chan(want, shift) <= 1 && chan(got, shift) <= 1;
            if (v[c] == m) same = same && chan(want, shift) == 1 && chan(got, shift) == 1;
            else if (v[c] / m < 1.0 - kFloorBand) same = same && chan(want, shift) == 0 && chan(got, shift) == 0;
        }
        if (!same) {
            bad = "F-T floor on " + led + " (m " + num(m) + "): oracle " + hex(want) + ", knob " + hex(got);
            return false;
        }
    }
    return true;
}

const char* const kEffectNames[CC_FX_TYPES] = {"boot", "down", "wake", "tick", "bound", "pending", "bloom", "fail",
                                               "sweep", "fill", "drain", "shimmer", "wash", "reveal", "press",
                                               "half", "scatter"};

uint8_t effectType(const char* name) {
    for (uint8_t k = 0; k < CC_FX_TYPES; ++k)
        if (name && !std::strcmp(name, kEffectNames[k])) return k;
    return CC_FX_TYPES;
}

uint8_t familyOf(const char* name) {
    if (!name) return CC_ALIVE_HOME;
    if (!std::strcmp(name, "recent")) return CC_ALIVE_RECENT;
    if (!std::strcmp(name, "tracks")) return CC_ALIVE_TRACKS;
    if (!std::strcmp(name, "windows")) return CC_ALIVE_WINDOWS;
    if (!std::strcmp(name, "offline")) return CC_ALIVE_OFFLINE;
    if (!std::strcmp(name, "explorer")) return CC_ALIVE_EXPLORER;
    if (!std::strcmp(name, "upnext")) return CC_ALIVE_UPNEXT;
    return CC_ALIVE_HOME;
}

void rgbOf(JsonVariantConst value, float (&out)[3]) {
    for (int c = 0; c < 3; ++c) out[c] = static_cast<float>(value[c].as<double>());
}

CCAliveCell oracleCell(JsonVariantConst cell) {
    CCAliveCell out;
    std::memset(&out, 0, sizeof(out));
    if (cell.isNull()) return out;
    out.rgb = pack(cell["c"][0].as<int>(), cell["c"][1].as<int>(), cell["c"][2].as<int>());
    out.role = cell["warm"].as<bool>() ? CC_ALIVE_ROLE_WARM : CC_ALIVE_ROLE_ACCENT;
    out.cls = CC_ALIVE_CLASS_1;                  // lit
    out.alpha = static_cast<float>(cell["a"].as<double>());
    out.volRed = cell["volRed"].as<bool>();
    return out;
}

bool oracleView(JsonObjectConst view, float todB, CCAliveTargets& t, std::string& error) {
    JsonArrayConst ring = view["ring"].as<JsonArrayConst>(), buttons = view["buttons"].as<JsonArrayConst>();
    if (ring.size() != 60 || buttons.size() != 4) {
        error = "view needs ring[60] and buttons[4]";
        return false;
    }
    for (int i = 0; i < 60; ++i) t.ring[i] = oracleCell(ring[i]);
    for (int j = 0; j < 4; ++j) t.buttons[j] = oracleCell(buttons[j]);
    t.asleep = view["asleep"].as<bool>();
    t.offline = view["offline"].as<bool>();
    t.pending = view["pending"].as<bool>();
    t.family = familyOf(view["family"].as<const char*>());
    t.cursor = static_cast<uint8_t>(view["cursor"].as<int>());
    t.heat = view["heat"].as<bool>();
    t.pausedPlay = view["pausedPlay"].as<bool>();
    t.tintOn = !view["tint"].isNull();
    t.tint[0] = t.tint[1] = t.tint[2] = 0.0f;
    if (t.tintOn) rgbOf(view["tint"], t.tint);
    t.songProg = view["songProg"].isNull() ? -1.0f : static_cast<float>(view["songProg"].as<double>());
    t.todB = todB;
    return true;
}

CCAliveEffect oracleEffect(JsonObjectConst fx, const CCAlivePalette& palette, bool& ok) {
    const uint8_t type = effectType(fx["type"].as<const char*>());
    ok = type < CC_FX_TYPES;
    CCAliveEffect e = cc_alive_effect(type, fx["t0"].as<uint32_t>());
    e.at = static_cast<float>(fx["at"] | 0.0);
    e.dir = static_cast<int8_t>(fx["dir"] | 0);
    e.n = static_cast<int16_t>(fx["n"] | 0);
    e.len = static_cast<int16_t>(fx["len"] | 0);
    e.from = static_cast<float>(fx["from"] | 0.0);
    e.to = static_cast<float>(fx["to"] | 0.0);
    e.home = fx["home"] | false;
    e.side = static_cast<int8_t>(fx["side"] | 0);             // [r2] half
    e.seed = static_cast<float>(fx["seed"] | 0.0);            // [r2] scatter
    if (!fx["c"].isNull()) rgbOf(fx["c"], e.c);
    else if (type == CC_FX_BLOOM) std::memcpy(e.c, palette.green, sizeof(e.c));   // RC: the bloom is GRN
    return e;
}

// The fixture's "designConstants": the design's literal effect colours (GRN, RED, BLUE)
// are this test's palette inputs; DUR, FG, the bloom spark and draw()'s initial state
// (cur, bcur, tint) must equal the port's own.
void initialStateCheck(JsonObjectConst k, const CCAlivePalette& palette) {
    JsonArrayConst curInit = k["curInit"].as<JsonArrayConst>(), bcurInit = k["bcurInit"].as<JsonArrayConst>(),
                   tintInit = k["tintInit"].as<JsonArrayConst>();
    if (curInit.size() != 4 || bcurInit.size() != 4 || tintInit.size() != 3) {
        report("oracle designConstants: curInit[4], bcurInit[4] and tintInit[3] are required");
        return;
    }
    // One 1 ms step from reset(): ring 0 and button 0 lit black at alpha 1, the rest dark.
    static CCAliveAnimator probe;
    static CCAliveTargets t;
    probe.reset();
    std::memset(&t, 0, sizeof(t));
    t.family = CC_ALIVE_HOME;
    t.songProg = -1.0f;
    t.todB = 1.0f;
    t.ring[0].cls = CC_ALIVE_CLASS_1;
    t.ring[0].role = CC_ALIVE_ROLE_ACCENT;
    t.ring[0].rgb = 0;
    t.ring[0].alpha = 1.0f;
    t.buttons[0] = t.ring[0];
    CCAliveRingE ring;
    CCAliveButtonE buttons;
    probe.step(1000, 1, t, palette, ring, buttons);
    // draw() lines 274-296 on that step (initial state: lines 151-153): ring 0 rises with tau 10 (target >= 0.9) and its
    // colour glides to black (tau 70, or 1 below a = 0.02); ring 1 falls with tau 140,
    // keeps its colour and gets the tint residue (tau 220) * 0.06; button 0 rises with
    // tau 40 and glides (tau 70); button 1 falls with tau 160.
    const double a = curInit[3].as<double>(), b = bcurInit[3].as<double>();
    const double ring0 = a + (1.0 - a) * (1.0 - std::exp(-1.0 / 10.0));
    const double ringK = 1.0 - std::exp(-1.0 / (ring0 < 0.02 ? 1.0 : 70.0));
    const double ring1 = a * std::exp(-1.0 / 140.0);
    const double button0 = b + (1.0 - b) * (1.0 - std::exp(-1.0 / 40.0));
    const double buttonK = 1.0 - std::exp(-1.0 / 70.0);
    const double button1 = b * std::exp(-1.0 / 160.0);
    double worst = 0.0;
    for (int q = 0; q < 3; ++q) {
        const double c = curInit[q].as<double>(), bc = bcurInit[q].as<double>();
        const double tint = tintInit[q].as<double>() * std::exp(-1.0 / 220.0) * 0.06;
        worst = std::fmax(worst, std::fabs(ring[0][q] - c * (1.0 - ringK) * ring0));
        worst = std::fmax(worst, std::fabs(ring[1][q] - (c * ring1 + tint)));
        worst = std::fmax(worst, std::fabs(buttons[0][q] - bc * (1.0 - buttonK) * button0));
        worst = std::fmax(worst, std::fabs(buttons[1][q] - bc * button1));
    }
    require(worst <= 1e-6, "animator reset() state equals the design's curInit/bcurInit/tintInit (error " +
                               num(worst) + ")");
}

// The design's DUR / FG against the port's, for every effect the design has (RC: its 15; BS: 14,
// with [r2] half and scatter). `covered` collects the checked types. The RC fixture carries the
// literal effect colours GRN / RED / BLUE; the BS fixture its palette WARM / HOT / GREEN / RED /
// AMBER / PINK (section 2; BS's WARM is also its warm marker, isW).
bool designConstants(JsonObjectConst k, bool bs, CCAlivePalette& colours, bool (&covered)[CC_FX_TYPES]) {
    const char* const keys[2][6] = {{"GRN", "RED", "BLUE", "GRN", "GRN", "GRN"},
                                    {"WARM", "HOT", "GREEN", "RED", "AMBER", "PINK"}};
    bool present = !k.isNull();
    for (int q = 0; q < 6 && present; ++q) present = k[keys[bs ? 1 : 0][q]].size() == 3;
    if (!present) {
        report(bs ? "BS oracle: designConstants with WARM, HOT, GREEN, RED, AMBER and PINK is required"
                  : "oracle: designConstants with GRN, RED and BLUE is required");
        return false;
    }
    colours = cc_alive_palette();
    if (bs) {
        rgbOf(k["WARM"], colours.warm);
        rgbOf(k["HOT"], colours.hot);
        rgbOf(k["GREEN"], colours.green);
        rgbOf(k["RED"], colours.red);
        rgbOf(k["AMBER"], colours.amber);
        rgbOf(k["PINK"], colours.pink);
    } else {
        rgbOf(k["GRN"], colours.green);
        rgbOf(k["RED"], colours.red);
        rgbOf(k["BLUE"], colours.blue);
    }
    JsonObjectConst dur = k["DUR"].as<JsonObjectConst>();
    JsonArrayConst fg = k["FG"].as<JsonArrayConst>();
    for (JsonVariantConst name : fg)
        require(effectType(name.as<const char*>()) < CC_FX_TYPES && !dur[name.as<const char*>()].isNull(),
                "design FG entry is known to the port and has a duration");
    for (JsonPairConst entry : dur) {
        const uint8_t type = effectType(entry.key().c_str());
        const std::string name = entry.key().c_str();
        require(type < CC_FX_TYPES, "design effect " + name + " is known to the port");
        if (type >= CC_FX_TYPES) continue;
        covered[type] = true;
        require(entry.value().is<int>() && entry.value().as<int>() == CCAliveSpec::durations[type],
                "DUR." + name + " equals the design's");
        bool designFg = false;
        for (JsonVariantConst item : fg)
            if (item.as<const char*>() && name == item.as<const char*>()) designFg = true;
        // BS drops boot / shimmer / pending from its FG list only because it has no such effects.
        require(designFg == CCAliveSpec::foreground[type], "FG membership of " + name + " equals the design's");
    }
    if (!bs) {
        // draw() line 349: the bloom spark is mix(GRN, white, 0.3); the port computes it from the colour.
        JsonArrayConst spark = k["bloomSpark"].as<JsonArrayConst>();
        bool sparkOk = spark.size() == 3;
        for (int q = 0; q < 3 && sparkOk; ++q)
            sparkOk = near(spark[q].as<double>(), colours.green[q] + (1.0 - colours.green[q]) * 0.3, 1e-6);
        require(sparkOk, "bloom spark mix(GRN, white, 0.3) equals the design's");
        colours.warm[0] = colours.warm[1] = colours.warm[2] = 1.0f;   // the case's warm/hot replace these
        colours.hot[0] = colours.hot[1] = colours.hot[2] = 1.0f;
    } else {
        JsonArrayConst drop = k["rmDrop"].as<JsonArrayConst>();
        bool same = drop.size() == 5;
        for (JsonVariantConst item : drop) {
            const uint8_t type = effectType(item.as<const char*>());
            same = same && (type == CC_FX_WAKE || type == CC_FX_TICK || type == CC_FX_SWEEP || type == CC_FX_SCATTER ||
                            type == CC_FX_REVEAL);
        }
        require(same, "BS play()'s reduced-motion drop list is wake, tick, sweep, scatter, reveal (6.5)");
    }
    initialStateCheck(k, colours);
    return true;
}

// An effect the [D12] cap evicted from the port's queue that the design (no cap) still
// holds. The design keeps drawing it until u > 1 or its kill fade ends; a later FG start
// can still kill it, and a later wake/reveal/bound can replace it (play() lines 233-234).
struct Evicted {
    uint8_t type;
    bool killed;
    uint32_t t0, kill;
};

bool replacesOwnType(uint8_t type) { return type == CC_FX_WAKE || type == CC_FX_REVEAL || type == CC_FX_BOUND; }

bool sameEffect(const CCAliveEffect& a, const CCAliveEffect& b) {
    return a.type == b.type && a.t0 == b.t0 && a.killed == b.killed && (!a.killed || a.kill == b.kill) &&
           a.at == b.at && a.from == b.from && a.to == b.to && a.n == b.n && a.len == b.len && a.dir == b.dir &&
           a.home == b.home && a.c[0] == b.c[0] && a.c[1] == b.c[1] && a.c[2] == b.c[2];
}

// animator.play(e), attributing any [D12] eviction by diffing the queue against the
// design's play() (kills, then replacement), which keeps every survivor in order.
void playTracked(CCAliveAnimator& animator, const CCAliveEffect& e, std::vector<Evicted>& evicted,
                 const std::string& where) {
    const bool fg = CCAliveSpec::foreground[e.type];
    for (Evicted& x : evicted)
        if (fg && CCAliveSpec::foreground[x.type] && !x.killed) {
            x.killed = true;
            x.kill = e.t0;
        }
    if (!fg && replacesOwnType(e.type))
        evicted.erase(std::remove_if(evicted.begin(), evicted.end(),
                                     [&e](const Evicted& x) { return x.type == e.type; }),
                      evicted.end());
    std::vector<CCAliveEffect> expected;
    for (uint8_t k = 0; k < animator.effectCount(); ++k) {
        CCAliveEffect x = animator.effect(k);
        if (fg && CCAliveSpec::foreground[x.type] && !x.killed) {
            x.killed = true;
            x.kill = e.t0;
        }
        if (!fg && replacesOwnType(e.type) && x.type == e.type) continue;
        expected.push_back(x);
    }
    const uint32_t before = animator.evictions();
    animator.play(e);
    const uint32_t dropped = animator.evictions() - before;
    const size_t kept = animator.effectCount() - 1u;           // the new effect is last
    const bool counted = dropped <= 1u && kept + dropped == expected.size() &&
                         sameEffect(animator.effect(static_cast<uint8_t>(kept)), e);
    require(counted, where + ": play() keeps the survivors and appends the new effect");
    if (!counted || dropped == 0u) return;
    size_t victim = 0;
    while (victim < kept && sameEffect(expected[victim], animator.effect(static_cast<uint8_t>(victim)))) ++victim;
    bool ordered = true;
    for (size_t k = victim; k < kept; ++k)
        ordered = ordered && sameEffect(expected[k + 1u], animator.effect(static_cast<uint8_t>(k)));
    require(ordered, where + ": a [D12] eviction removes exactly one effect and keeps the order");
    const Evicted x = {expected[victim].type, expected[victim].killed, expected[victim].t0, expected[victim].kill};
    evicted.push_back(x);
}

// The design's draw() filter on the evicted effects at t (lines 318-321): drops those with
// u > 1 or amp <= 0. Returns true when the design still draws one of them at t.
bool designStillDraws(std::vector<Evicted>& evicted, uint32_t t) {
    std::vector<Evicted> live;
    for (const Evicted& x : evicted) {
        if (t - x.t0 > CCAliveSpec::durations[x.type]) continue;
        if (x.killed && static_cast<float>(t - x.kill) >= CCAliveSpec::killFadeMs) continue;
        live.push_back(x);
    }
    evicted.swap(live);
    return !evicted.empty();
}

bool runOracle(const char* path, bool perCase, OracleStats& s, bool bs, bool (&covered)[CC_FX_TYPES]) {
    std::string text;
    const char* label = bs ? "BS oracle" : "oracle";
    if (!readFile(path, text)) {
        std::printf("%s: SKIPPED - %s is absent (it is produced by tests/js/%s)\n", label, path,
                    bs ? "alive_oracle_bs.cjs" : "alive_oracle.cjs");
        return false;
    }
    JsonDocument doc;
    const DeserializationError error = deserializeJson(doc, text);
    if (error) {
        report(std::string("oracle JSON: ") + error.c_str());
        return true;
    }
    require(doc["version"].as<int>() == 1, "oracle version 1");
    const double tolerance = doc["tolerance"] | 0.002;
    s.tolerance = tolerance;
    JsonArrayConst cases = doc["cases"].as<JsonArrayConst>();
    require(!cases.isNull() && cases.size() > 0, "oracle has cases");
    CCAlivePalette designColours;
    if (!designConstants(doc["designConstants"].as<JsonObjectConst>(), bs, designColours, covered)) return true;
    static CCAliveAnimator animator;
    static CCAliveTargets targets;
    CCAliveRingE ringE;
    CCAliveButtonE buttonE;
    std::vector<Evicted> evicted;
    for (JsonObjectConst c : cases) {
        const std::string name = c["name"].as<const char*>() ? c["name"].as<const char*>() : "?";
        ++s.cases;
        animator.reset();
        evicted.clear();
        std::memset(&targets, 0, sizeof(targets));
        targets.family = CC_ALIVE_HOME;
        targets.songProg = -1.0f;
        CCAlivePalette palette = designColours;
        if (!bs) {
            rgbOf(c["warm"], palette.warm);
            rgbOf(c["hot"], palette.hot);
        }
        animator.setReducedMotion(false);
        const float todB = static_cast<float>(c["todB"].as<double>());
        targets.todB = todB;
        // "designUncapped" cases queue more than 8 effects in the design, which has no cap.
        // Every step is replayed; a step is compared unless the design still draws an
        // effect the [D12] cap evicted (then e differs by that effect, as contracted).
        // The design's queue/live counts must equal the port's queue plus those effects.
        const bool uncapped = c["designUncapped"] | false;
        int compared = 0, skipped = 0, index = 0;
        double caseWorst = 0.0;
        bool caseOk = true;
        for (JsonObjectConst step : c["steps"].as<JsonArrayConst>()) {
            ++s.steps;
            const uint32_t t = step["t"].as<uint32_t>();
            const std::string where = std::string(label) + " " + name + " step " + num(index) + " (t " + num(t) + ")";
            std::string viewError;
            if (!step["view"].isNull()) {
                if (!oracleView(step["view"].as<JsonObjectConst>(), todB, targets, viewError)) {
                    report(where + ": " + viewError);
                    caseOk = false;
                    break;
                }
                animator.setReducedMotion(step["view"]["rm"] | false);   // [r2] BS's rm (6.5)
            }
            for (JsonObjectConst fx : step["effects"].as<JsonArrayConst>()) {
                bool known = false;
                const CCAliveEffect e = oracleEffect(fx, palette, known);
                if (!known) {
                    report(where + ": unknown effect type");
                    caseOk = false;
                    continue;
                }
                if (fx["dropped"] | false) {                  // BS play() dropped it under reduced motion
                    const uint8_t queued = animator.effectCount();
                    require(!animator.play(e) && animator.effectCount() == queued,
                            where + ": " + kEffectNames[e.type] + " dropped under reduced motion, as BS play()");
                    ++s.dropped;
                    continue;
                }
                playTracked(animator, e, evicted, where);
            }
            {                                            // [user 2026-09-26] the output stage (9 step 4)
                std::string bad;
                ++checks;
                if (!oracleBytes(step["expect"].as<JsonObjectConst>(), targets, s, bad)) {
                    report(where + ": " + bad);
                    caseOk = false;
                    break;
                }
            }
            const size_t designQueue = animator.effectCount() + evicted.size();
            if (uncapped) {
                require(step["queue"].is<int>() && step["queue"].as<int>() == static_cast<int>(designQueue),
                        where + ": design queue " + num(step["queue"] | -1) + " = port " +
                            num(animator.effectCount()) + " + evicted " + num(static_cast<double>(evicted.size())));
            }
            animator.step(t, step["dt"].as<uint32_t>(), targets, palette, ringE, buttonE);
            const bool diverged = designStillDraws(evicted, t);
            if (uncapped) {
                const size_t designLive = animator.effectCount() + evicted.size();
                require(step["live"].is<int>() && step["live"].as<int>() == static_cast<int>(designLive),
                        where + ": design live " + num(step["live"] | -1) + " = port " +
                            num(animator.effectCount()) + " + evicted " + num(static_cast<double>(evicted.size())));
            }
            if (diverged) {                              // [D12]: the design draws an effect the cap dropped
                ++skipped;
                ++index;
                continue;
            }
            JsonArrayConst ring = step["expect"]["ring"].as<JsonArrayConst>();
            JsonArrayConst buttons = step["expect"]["buttons"].as<JsonArrayConst>();
            if (ring.size() != 60 || buttons.size() != 4) {
                report(where + ": expect needs ring[60] and buttons[4]");
                caseOk = false;
                break;
            }
            double stepWorst = 0.0;
            std::string firstBad;
            for (int i = 0; i < 64; ++i) {
                for (int q = 0; q < 3; ++q) {
                    const double expected = i < 60 ? ring[i][q].as<double>() : buttons[i - 60][q].as<double>();
                    const double got = i < 60 ? ringE[i][q] : buttonE[i - 60][q];
                    const double err = std::fabs(expected - got);
                    ++s.values;
                    if (err > stepWorst) stepWorst = err;
                    if (err > tolerance && firstBad.empty())
                        firstBad = std::string(i < 60 ? "ring[" + num(i) : "button[" + num(i - 60)) + "][" + num(q) +
                                   "] expected " + num(expected) + " got " + num(got);
                }
            }
            ++checks;
            ++compared;
            caseWorst = std::fmax(caseWorst, stepWorst);
            if (!firstBad.empty()) {
                report(where + ": " + firstBad + " (max error " + num(stepWorst) + ")");
                caseOk = false;
                break;                                   // later steps depend on the diverged state
            }
            ++index;
        }
        s.worst = std::fmax(s.worst, caseWorst);
        s.compared += compared;
        s.skipped += skipped;
        const int total = static_cast<int>(c["steps"].size());
        if (uncapped) {
            ++s.uncapped;
            require(animator.evictions() > 0, "oracle " + name + ": designUncapped case must exceed the 8-effect cap");
            require(compared + skipped == total || !caseOk, "oracle " + name + ": every step replayed");
            if (caseOk)
                std::printf("oracle: %s: %u [D12] eviction(s); %d of %d step(s) compared, %d skipped while the "
                            "design still draws an evicted effect; design queue/live counts reproduced\n",
                            name.c_str(), static_cast<unsigned>(animator.evictions()), compared, total, skipped);
        } else {
            require(animator.evictions() == 0 && skipped == 0,
                    "oracle " + name + ": stays within the 8-effect cap (not designUncapped)");
        }
        if (perCase)
            std::printf("%s case %-32s %s %3d/%3d step(s) compared, max |e - design| %.2e\n", label, name.c_str(),
                        caseOk ? "PASS" : "FAIL", compared, total, caseWorst);
        if (!caseOk) ++s.failedCases;
    }
    return true;
}

// ------------------------------------------------------------- part 3: twin sequences
struct SequenceStats {
    int cases, steps, frames, failedCases, byteSteps, knobOps;
    long long values, bytes, effects, flags, lims;
    double worst, tolerance;
    int worstByte;
    std::string worstAt;
    long long litMasks, floored;                   // [user 2026-09-26] F-T (9 step 4)
};

// [user 2026-09-26] The twin replay's F-T checks on a step with bytes (dither off): the engine's mask
// (cc_alive_lit of its targets) equals Python's "lit" (16 hex digits, bit i = segment i, bit 60 + j =
// button slot j); a lit LED is visible in both ports or in neither; and on an LED Python floored (its
// largest channel below 0.5 - kSeqFloorBand counts, estimated from its e) both ports show one count on
// Python's dominant channel with every channel <= 1, and 0 on every channel more than kSeqFloorBand
// counts below the dominant one (12.7: the dominant-only rule). The band covers the e tolerance (2e-3
// in e is 0.024 counts at drive 150 in the linear toe).
constexpr double kSeqFloorBand = 0.05;

bool sequenceFloor(JsonObjectConst expect, const CCAlive& engine, const uint32_t (&ring)[CC_RING_LEDS],
                   const uint32_t (&buttons)[4], double eScale, int drive, SequenceStats& s, std::string& bad) {
    const char* text = expect["lit"].as<const char*>();
    if (!text || std::strlen(text) != 16) {
        bad = "expect.lit needs 16 hex digits with the bytes";
        return false;
    }
    const uint64_t want = std::strtoull(text, nullptr, 16);
    uint64_t ringLit = 0;
    uint8_t buttonLit = 0;
    cc_alive_lit(engine.targets(), ringLit, buttonLit);
    const uint64_t mask = ringLit | (static_cast<uint64_t>(buttonLit) << 60);
    ++s.litMasks;
    if (mask != want) {
        char got[24];
        std::snprintf(got, sizeof(got), "%016llx", static_cast<unsigned long long>(mask));
        bad = std::string("F-T mask ") + got + ", Python " + text;
        return false;
    }
    JsonArrayConst e = expect["e"].as<JsonArrayConst>(), bytes = expect["bytes"].as<JsonArrayConst>();
    double lin[64][3], total = 0.0;
    for (int k = 0; k < 64; ++k) {
        for (int c = 0; c < 3; ++c) lin[k][c] = eotfExact(e[static_cast<size_t>(k * 3 + c)].as<double>() / eScale) * drive;
        total += (k < 60 ? 1.0 : 2.0) * (lin[k][0] + lin[k][1] + lin[k][2]);
    }
    const double limit = total > 16920.0 ? 16920.0 / total : 1.0;
    for (int k = 0; k < 64; ++k) {
        if (!((mask >> k) & 1u)) continue;
        const uint32_t py = bytes[static_cast<size_t>(k)].as<uint32_t>(), cpp = k < 60 ? ring[k] : buttons[k - 60];
        const std::string led = k < 60 ? "ring[" + num(k) + "]" : "button[" + num(k - 60) + "]";
        if ((py != 0u) != (cpp != 0u)) {
            bad = "F-T visibility of " + led + ": Python " + hex(py) + ", C++ " + hex(cpp);
            return false;
        }
        const double v[3] = {lin[k][0] * limit, lin[k][1] * limit, lin[k][2] * limit};
        const double m = std::fmax(v[0], std::fmax(v[1], v[2]));
        if (!(m > 0.0) || m >= 0.5 - kSeqFloorBand) continue;
        ++s.floored;
        const int top = v[0] >= v[1] && v[0] >= v[2] ? 0 : (v[1] >= v[2] ? 1 : 2);
        const int shift = 16 - 8 * top;
        bool ok = chan(py, shift) == 1 && chan(cpp, shift) == 1;
        for (int c = 0, q = 16; c < 3; ++c, q -= 8) {
            ok = ok && chan(py, q) <= 1 && chan(cpp, q) <= 1;
            if (v[c] < m - kSeqFloorBand) ok = ok && chan(py, q) == 0 && chan(cpp, q) == 0;
        }
        if (!ok) {
            bad = "F-T floor on " + led + " (m ~" + num(m) + "): Python " + hex(py) + ", C++ " + hex(cpp) +
                  ", dominant channel " + num(top);
            return false;
        }
    }
    return true;
}

bool closeTo(JsonVariantConst value, double expected, double tolerance) {
    return value.is<double>() && std::fabs(value.as<double>() - expected) <= tolerance;
}

// One "fx" row against a queued effect: [type, t0, kill|null, params...] (format above).
bool fxRowMatches(const CCAliveEffect& e, JsonArrayConst row) {
    const uint8_t type = effectType(row[0].as<const char*>());
    if (type != e.type || !row[1].is<uint32_t>() || row[1].as<uint32_t>() != e.t0) return false;
    if (row[2].isNull() == e.killed) return false;
    if (e.killed && (!row[2].is<uint32_t>() || row[2].as<uint32_t>() != e.kill)) return false;
    size_t k = 3;
    auto next = [&row, &k]() { return row[k++]; };
    auto exact = [&next](double expected) { return closeTo(next(), expected, 0.0); };
    auto colour = [&next, &e]() {
        bool ok = true;
        for (int q = 0; q < 3; ++q) ok = closeTo(next(), e.c[q], 2e-6) && ok;
        return ok;
    };
    bool ok = true;
    switch (type) {
        case CC_FX_BOOT: ok = exact(e.at) && exact(e.home ? 1.0 : 0.0); break;
        case CC_FX_TICK: ok = exact(e.at) && exact(e.dir) && exact(e.len); break;
        case CC_FX_BOUND: ok = exact(e.at) && exact(e.dir) && colour(); break;
        case CC_FX_SWEEP: ok = exact(e.at) && exact(e.dir); break;
        case CC_FX_FILL:
        case CC_FX_DRAIN: ok = exact(e.at) && exact(e.n); break;
        case CC_FX_SHIMMER: ok = exact(e.from) && exact(e.to); break;
        case CC_FX_WASH: ok = exact(e.at) && colour(); break;
        case CC_FX_PRESS: ok = exact(e.n); break;
        case CC_FX_BLOOM: ok = exact(e.at) && colour(); break;                      // [r2] the colour
        case CC_FX_HALF: ok = exact(e.at) && exact(e.side) && colour(); break;       // [r2]
        case CC_FX_SCATTER: ok = exact(e.at) && closeTo(next(), e.seed, 1e-5); break;   // [r2][M5] 1e-5
        default: ok = exact(e.at); break;                       // down wake fail reveal
    }
    return ok && row.size() == k;
}

// The effect queue as "type@t0(kill k)[params]", params in the "fx" row order.
std::string fxText(const CCAliveAnimator& a) {
    std::string out = "[";
    for (uint8_t k = 0; k < a.effectCount(); ++k) {
        const CCAliveEffect& e = a.effect(k);
        std::string params;
        switch (e.type) {
            case CC_FX_BOOT: params = num(e.at) + " " + num(e.home ? 1 : 0); break;
            case CC_FX_TICK: params = num(e.at) + " " + num(e.dir) + " " + num(e.len); break;
            case CC_FX_BOUND:
                params = num(e.at) + " " + num(e.dir) + " " + num(e.c[0]) + " " + num(e.c[1]) + " " + num(e.c[2]);
                break;
            case CC_FX_SWEEP: params = num(e.at) + " " + num(e.dir); break;
            case CC_FX_FILL:
            case CC_FX_DRAIN: params = num(e.at) + " " + num(e.n); break;
            case CC_FX_SHIMMER: params = num(e.from) + " " + num(e.to); break;
            case CC_FX_WASH:
            case CC_FX_BLOOM: params = num(e.at) + " " + num(e.c[0]) + " " + num(e.c[1]) + " " + num(e.c[2]); break;
            case CC_FX_HALF:
                params = num(e.at) + " " + num(e.side) + " " + num(e.c[0]) + " " + num(e.c[1]) + " " + num(e.c[2]);
                break;
            case CC_FX_SCATTER: params = num(e.at) + " " + num(e.seed); break;
            case CC_FX_PRESS: params = num(e.n); break;
            default: params = num(e.at); break;
        }
        out += std::string(k ? " " : "") + kEffectNames[e.type] + "@" + num(e.t0) +
               (e.killed ? "(kill " + num(e.kill) + ")" : "") + "[" + params + "]";
    }
    return out + "]";
}

std::string rowsText(JsonArrayConst rows) {
    std::string out = "[";
    bool first = true;
    for (JsonArrayConst row : rows) {
        std::string params;
        for (size_t k = 3; k < row.size(); ++k) params += (k > 3 ? " " : "") + num(row[k].as<double>());
        out += std::string(first ? "" : " ") + (row[0].as<const char*>() ? row[0].as<const char*>() : "?") + "@" +
               num(row[1].as<double>()) + (row[2].isNull() ? "" : "(kill " + num(row[2].as<double>()) + ")") + "[" +
               params + "]";
        first = false;
    }
    return out + "]";
}

bool runSequences(const char* path, bool perCase, SequenceStats& s) {
    std::string text;
    if (!readFile(path, text)) {
        std::printf("sequences: SKIPPED - %s is absent (tests/tools/make_alive_sequences.py produces it)\n", path);
        return false;
    }
    JsonDocument doc;
    const DeserializationError error = deserializeJson(doc, text);
    if (error) {
        report(std::string("sequences JSON: ") + error.c_str());
        return true;
    }
    require(doc["version"].as<int>() == 2, "sequences version 2");
    const double tolerance = doc["tolerance"] | 0.002;
    const int byteTolerance = doc["byteTolerance"] | 1;
    const double eScale = doc["eScale"] | 0.0;
    require(eScale >= 1000.0, "sequences eScale");
    s.tolerance = tolerance;
    if (eScale < 1000.0) return true;
    // [r2] The frames of the v7 host carry PRESENTATION_V5 content: the firmware parser must read it.
    {
        JsonDocument probe;
        const DeserializationError probeError = deserializeJson(probe,
            "{\"id\":1,\"mode\":\"RECENTLY ADDED\",\"target\":\"\",\"value\":\"\",\"detail\":\"\",\"status\":\"\","
            "\"layout\":\"upnext\",\"buttons\":[{\"label\":\"\",\"enabled\":true,\"icon\":\"heart\",\"lit\":\"on\"},"
            "{\"label\":\"\",\"enabled\":true,\"icon\":\"back\"},{\"label\":\"\",\"enabled\":true,\"icon\":\"back\"},"
            "{\"label\":\"\",\"enabled\":true,\"icon\":\"play\"}],\"ring\":{\"style\":\"selection\",\"value\":0,"
            "\"index\":0,\"count\":3,\"now\":1,\"card\":true},\"feedback\":{\"kind\":\"ok\",\"seq\":1,\"moment\":\"like\"}}");
        CCFrame v5;
        const bool v5ok = !probeError && cc_parse_frame(probe.as<JsonObjectConst>(), v5) &&
                          v5.layoutId == CC_LAYOUT_UPNEXT && v5.ringNow == 1 && v5.ringCard &&
                          v5.buttons[0].icon == CC_ICON_HEART && v5.buttons[0].lit == CC_LIT_ON &&
                          v5.feedbackMoment == CC_MOMENT_LIKE;
        require(v5ok, "cc_parse_frame reads PRESENTATION_V5 (layout, now, card, lit, heart, moment)");
        if (!v5ok) return true;
    }
    JsonArrayConst frames = doc["frames"].as<JsonArrayConst>();
    std::vector<CCFrame> parsed(frames.size());
    std::vector<CCAliveFrameExtra> extras(frames.size());
    for (size_t i = 0; i < frames.size(); ++i) {
        require(cc_parse_frame(frames[i], parsed[i]), "cc_parse_frame accepts sequence frame " + num(static_cast<double>(i)));
        extras[i].playing = frames[i]["playing"].is<bool>() ? (frames[i]["playing"].as<bool>() ? 1 : 0) : -1;
        const int skip = frames[i]["feedback"]["skip"] | 0;
        extras[i].skip = static_cast<int8_t>(skip == 1 || skip == -1 ? skip : 0);
    }
    s.frames = static_cast<int>(frames.size());
    static CCAlive engine;
    CCAliveKnob knob;
    uint32_t ring[CC_RING_LEDS], buttons[4];
    for (JsonPairConst entry : doc["cases"].as<JsonObjectConst>()) {
        const std::string name = entry.key().c_str();
        ++s.cases;
        engine.reset(0);
        knob.reset();
        int index = 0;
        double caseWorst = 0.0;
        int caseWorstByte = 0;
        bool caseOk = true;
        JsonArrayConst steps = entry.value()["steps"].as<JsonArrayConst>();
        require(steps.size() > 0, "sequence " + name + " has steps");
        for (JsonObjectConst step : steps) {
            ++s.steps;
            const uint32_t now = step["now"].as<uint32_t>();
            const std::string where = "sequence " + name + " step " + num(index) + " (now " + num(now) + ")";
            std::vector<int> lims;
            for (JsonObjectConst op : step["ops"].as<JsonArrayConst>()) {
                const char* kind = op["op"].as<const char*>();
                const uint32_t t = op["t"].is<uint32_t>() ? op["t"].as<uint32_t>() : now;
                if (!kind) { report(where + ": op without a name"); continue; }
                if (!std::strcmp(kind, "reset")) engine.reset(t);
                else if (!std::strcmp(kind, "claim")) engine.claim(t);
                else if (!std::strcmp(kind, "release")) engine.release(t);
                else if (!std::strcmp(kind, "detent")) engine.detent(t, op["delta"].as<int32_t>());
                else if (!std::strcmp(kind, "limit")) engine.limit(t, static_cast<int8_t>(op["dir"].as<int>()));
                else if (!std::strcmp(kind, "press")) engine.press(t, static_cast<uint8_t>(op["slot"].as<int>()));
                else if (!std::strcmp(kind, "clock")) engine.setClock(t, static_cast<uint16_t>(op["minute"].as<int>()));
                else if (!std::strcmp(kind, "progress")) engine.setProgress(t, op["pos"].as<uint32_t>(), op["dur"].as<uint32_t>());
                else if (!std::strcmp(kind, "rm")) engine.setReducedMotion(t, op["on"].as<bool>());
                else if (!std::strcmp(kind, "tuning")) engine.setTuning(t, op["pink"].as<uint32_t>(), op["volFull"].as<bool>());
                else if (!std::strcmp(kind, "knobReset")) knob.reset();
                else if (!std::strcmp(kind, "knob")) {                  // one HMI pass [Q1]
                    const CCAliveKnobEvents ev = knob.sample(t, op["id"].as<uint32_t>(), op["pos"].as<uint16_t>(),
                                                             op["pushing"].as<bool>(), op["max"].as<uint16_t>());
                    if (ev.delta) engine.detent(t, ev.delta);
                    if (ev.limit) {
                        engine.limit(t, ev.limit);
                        lims.push_back(ev.limit);
                    }
                    ++s.knobOps;
                }
                else report(where + ": unknown op " + kind);
            }
            const CCFrame* frame = nullptr;
            CCAliveFrameExtra extra = extraOf(-1);
            if (step["frame"].is<int>()) {
                const int f = step["frame"].as<int>();
                if (f < 0 || f >= static_cast<int>(parsed.size())) {
                    report(where + ": bad frame index");
                    caseOk = false;
                    break;
                }
                frame = &parsed[static_cast<size_t>(f)];
                extra = extras[static_cast<size_t>(f)];
            }
            int32_t localPos = 0, localMax = -1;
            if (step["local"].is<JsonArrayConst>()) {
                localPos = step["local"][0].as<int32_t>();
                localMax = step["local"][1].as<int32_t>();
            }
            engine.render(now, frame, localPos, localMax, extra);
            engine.output(static_cast<uint8_t>(step["drive"] | 150), step["dither"] | false, ring, buttons);
            JsonObjectConst expect = step["expect"].as<JsonObjectConst>();
            bool ok = true;
            JsonArrayConst eX = expect["e"].as<JsonArrayConst>();
            if (eX.size() == 192) {
                std::string firstBad;
                for (int i = 0; i < 64; ++i)
                    for (int q = 0; q < 3; ++q) {
                        const double expected = eX[static_cast<size_t>(i * 3 + q)].as<double>() / eScale;
                        const double got = i < 60 ? engine.ringE()[i][q] : engine.buttonE()[i - 60][q];
                        const double err = std::fabs(expected - got);
                        ++s.values;
                        caseWorst = std::fmax(caseWorst, err);
                        if (err > s.worst) {
                            s.worst = err;
                            s.worstAt = name + " step " + num(index) + (i < 60 ? " ring[" + num(i) : " button[" + num(i - 60)) +
                                        "][" + num(q) + "]";
                        }
                        if (err > tolerance && firstBad.empty())
                            firstBad = std::string(i < 60 ? "e ring[" + num(i) : "e button[" + num(i - 60)) + "][" +
                                       num(q) + "] Python " + num(expected) + ", C++ " + num(got);
                    }
                ++checks;
                if (!firstBad.empty()) { report(where + ": " + firstBad); ok = false; }
            } else {
                report(where + ": expect.e needs 192 values");
                ok = false;
            }
            if (!expect["bytes"].isNull()) {
                JsonArrayConst bytes = expect["bytes"].as<JsonArrayConst>();
                std::string firstBad;
                for (int i = 0; i < 64 && bytes.size() == 64; ++i) {
                    const uint32_t expected = bytes[static_cast<size_t>(i)].as<uint32_t>();
                    const uint32_t got = i < 60 ? ring[i] : buttons[i - 60];
                    for (int shift = 16; shift >= 0; shift -= 8) {
                        const int diff = std::abs(chan(expected, shift) - chan(got, shift));
                        ++s.bytes;
                        if (diff > s.worstByte) s.worstByte = diff;
                        if (diff > caseWorstByte) caseWorstByte = diff;
                        if (diff > byteTolerance && firstBad.empty())
                            firstBad = std::string(i < 60 ? "bytes ring[" + num(i) : "bytes button[" + num(i - 60)) +
                                       "] Python " + hex(expected) + ", C++ " + hex(got);
                    }
                }
                ++checks;
                ++s.byteSteps;
                if (bytes.size() != 64) { report(where + ": expect.bytes needs 64 values"); ok = false; }
                else if (!firstBad.empty()) { report(where + ": " + firstBad); ok = false; }
                else if (eX.size() == 192) {                     // [user 2026-09-26] F-T
                    std::string bad;
                    ++checks;
                    if (!sequenceFloor(expect, engine, ring, buttons, eScale, step["drive"] | 150, s, bad)) {
                        report(where + ": " + bad);
                        ok = false;
                    }
                }
            }
            if (!expect["asleep"].isNull()) {
                ++checks;
                ++s.flags;
                if (expect["asleep"].as<bool>() != engine.asleep()) {
                    report(where + ": asleep " + (engine.asleep() ? "true" : "false") + ", Python " +
                           (expect["asleep"].as<bool>() ? "true" : "false"));
                    ok = false;
                }
            }
            if (!expect["cursor"].isNull()) {
                ++checks;
                ++s.flags;
                if (expect["cursor"].as<int>() != engine.cursor()) {
                    report(where + ": cursor " + num(engine.cursor()) + ", Python " + num(expect["cursor"].as<int>()));
                    ok = false;
                }
            }
            if (!expect["flash"].isNull()) {
                ++checks;
                ++s.flags;
                if (expect["flash"].as<int>() != engine.flash()) {
                    report(where + ": flash " + num(engine.flash()) + ", Python " + num(expect["flash"].as<int>()));
                    ok = false;
                }
            }
            if (!expect["pending"].isNull()) {           // [r2.2] M33
                ++checks;
                ++s.flags;
                if (expect["pending"].as<bool>() != engine.targets().pending) {
                    report(where + ": pending " + (engine.targets().pending ? "true" : "false") + ", Python " +
                           (expect["pending"].as<bool>() ? "true" : "false"));
                    ok = false;
                }
            }
            if (!expect["animating"].isNull()) {
                ++checks;
                ++s.flags;
                if (expect["animating"].as<bool>() != engine.animating()) {
                    report(where + ": animating " + (engine.animating() ? "true" : "false") + ", Python " +
                           (expect["animating"].as<bool>() ? "true" : "false"));
                    ok = false;
                }
            }
            {
                JsonArrayConst want = expect["lim"].as<JsonArrayConst>();
                bool same = want.size() == lims.size();
                for (size_t k = 0; same && k < lims.size(); ++k) same = want[k].as<int>() == lims[k];
                ++checks;
                s.lims += static_cast<long long>(lims.size());
                if (!same) {
                    report(where + ": the knob fired " + num(static_cast<double>(lims.size())) + " limit(s), Python " +
                           num(static_cast<double>(want.size())));
                    ok = false;
                }
            }
            if (!expect["fx"].isNull()) {
                JsonArrayConst rows = expect["fx"].as<JsonArrayConst>();
                const CCAliveAnimator& animator = engine.animator();
                bool same = rows.size() == animator.effectCount();
                uint8_t k = 0;
                for (JsonArrayConst row : rows) {
                    if (!same) break;
                    same = fxRowMatches(animator.effect(k++), row);
                }
                ++checks;
                s.effects += static_cast<long long>(rows.size());
                if (!same) {
                    report(where + ": effect queue " + fxText(animator) + ", Python " + rowsText(rows));
                    ok = false;
                }
            }
            ++index;
            if (!ok) {
                caseOk = false;
                break;                                   // later steps depend on the diverged state
            }
        }
        if (!caseOk) ++s.failedCases;
        if (perCase)
            std::printf("sequence %-30s %s %4d/%4d step(s), max |e C++ - Python| %.2e, max byte diff %d\n",
                        name.c_str(), caseOk ? "PASS" : "FAIL", index, static_cast<int>(steps.size()), caseWorst,
                        caseWorstByte);
    }
    return true;
}
} // namespace

int main(int argc, char** argv) {
    // alive_tests.exe [oracle.json [sequences.json [oracle_bs.json]]] [--cases]
    bool perCase = false;
    std::vector<const char*> paths;
    for (int k = 1; k < argc; ++k) {
        if (!std::strcmp(argv[k], "--cases")) perCase = true;
        else paths.push_back(argv[k]);
    }
    outputChecks();
    floorChecks();
    satChecks();
    jsChecks();
    todChecks();
    queueChecks();
    sleepChecks();
    targetChecks();
    eventChecks();
    tieChecks();
    songChecks();
    noticeRestChecks();
    momentChecks();
    knobChecks();
    paletteRoleChecks();
    costChecks();
    const long long direct = checks;
    std::printf("direct: %lld assertion(s)\n", direct);

    bool covered[CC_FX_TYPES] = {};
    OracleStats oracle = {0, 0, 0, 0, 0, 0, 0, 0, 0.0, 0.0, 0, 0, 0, 0, 0};
    const bool rcRan = paths.size() > 0 && runOracle(paths[0], perCase, oracle, false, covered);
    if (rcRan)
        std::printf("oracle: %d case(s) (%d designUncapped), %d step(s), %d compared (%d skipped: design draws an "
                    "effect the [D12] cap evicted), %lld value(s), max |e - design| %.2e (tolerance %g), "
                    "%d case(s) failed\n", oracle.cases, oracle.uncapped, oracle.steps, oracle.compared,
                    oracle.skipped, oracle.values, oracle.worst, oracle.tolerance, oracle.failedCases);
    OracleStats bsOracle = {0, 0, 0, 0, 0, 0, 0, 0, 0.0, 0.0, 0, 0, 0, 0, 0};
    const bool bsRan = paths.size() > 2 && runOracle(paths[2], perCase, bsOracle, true, covered);
    if (bsRan)
        std::printf("BS oracle: %d case(s), %d step(s), %d compared, %lld value(s), %d reduced-motion drop(s), "
                    "max |e - design| %.2e (tolerance %g), %d case(s) failed\n", bsOracle.cases, bsOracle.steps,
                    bsOracle.compared, bsOracle.values, bsOracle.dropped, bsOracle.worst, bsOracle.tolerance,
                    bsOracle.failedCases);
    for (const OracleStats* o : {&oracle, &bsOracle}) {   // [user 2026-09-26] section 9 bytes (9 step 4)
        if (!o->byteSteps) continue;
        std::printf("%s output: %d step(s), %lld byte(s) (drive 150, dither off, F-T) within 1 of the oracle's "
                    "float64 bytes, max diff %d; %lld floored lit LED-step(s) identical, %lld in the +-%g band\n",
                    o == &oracle ? "oracle" : "BS oracle", o->byteSteps, o->byteValues, o->worstByte, o->floored,
                    o->band, kFloorBand);
        // [user 2026-09-26] 12.8: BS now rests at 0.34 (visible), so its floor serves offline marks and fades only.
        const long long minFloored = o == &oracle ? 1000 : 200;
        require(o->floored > minFloored, "the oracle's F-T floor is exercised (> " + num(static_cast<int>(minFloored)) +
                " floored LED-steps)");
    }
    if (rcRan && bsRan) {                                 // [r2] 11.2: every port effect has a design twin
        std::string missing;
        for (uint8_t type = 0; type < CC_FX_TYPES; ++type)
            if (!covered[type]) missing += std::string(" ") + kEffectNames[type];
        require(missing.empty(), "the two oracles cover every effect type (missing:" + missing + ")");
    }
    SequenceStats sequences = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.0, 0.0, 0, std::string(), 0, 0};
    if (paths.size() > 1 && runSequences(paths[1], perCase, sequences)) {
        std::printf("sequences: %d case(s), %d step(s), %d frame(s); %lld e value(s), max |e C++ - Python| %.2e "
                    "(%s; tolerance %g); %lld output byte(s) on %d step(s) with dither off, max diff %d; "
                    "%lld queued effect(s) and %lld flag(s) compared; %d knob pass(es), %lld lim; %d case(s) "
                    "failed\n", sequences.cases, sequences.steps, sequences.frames, sequences.values, sequences.worst,
                    sequences.worstAt.c_str(), sequences.tolerance, sequences.bytes, sequences.byteSteps,
                    sequences.worstByte, sequences.effects, sequences.flags, sequences.knobOps, sequences.lims,
                    sequences.failedCases);
        std::printf("sequences: F-T (dither off, the default): %lld mask(s) equal to Python's, %lld floored lit "
                    "LED-step(s) with the dominant channel at one count in both ports\n", sequences.litMasks,
                    sequences.floored);
        require(sequences.litMasks == sequences.byteSteps && sequences.floored > 500,
                "the twin replay checks the F-T mask on every byte step and the floor on > 500 LED-steps");
    }
    if (failures) {
        std::printf("FAIL: %d of %lld check(s) failed\n", failures, checks);
        return 1;
    }
    std::printf("PASS: %lld alive check(s)\n", checks);
    return 0;
}
