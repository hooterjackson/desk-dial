#pragma once
#include <ArduinoJson.h>
#include <stddef.h>
#include <stdint.h>
#include "cc_presentation.h"

// Contract-v4/v5 frame parser (PRESENTATION_V4.md sections 2-4, PRESENTATION_V5.md 3-7). Platform-neutral:
// it depends only on ArduinoJson and cc_presentation.h, and is compiled
// unchanged by the firmware, by harness/parse_tests.py (MSVC /W4 /WX,
// parity with tests/fixtures/frames_v4.json) and by cpp11_gate.py (gnu++11).
//
// Required fields that are missing or malformed reject the frame. A present
// optional field with an invalid value also rejects it (section 4 "Parsers
// reject"); unknown fields are ignored so older companions stay compatible.
// An absent ring.first is never rejected (rules.absentFirst).
// iconKey (1.0.0-cc5.3, ARTWORK2.md section 6) is the exception to the strict rule: a malformed
// value, or one on a layout other than windows, is stripped ("") and never rejects the frame.
// ALIVE.md section 3 (1.0.0-cc5.4) follows the strict rule: an invalid clock (int 0..1439),
// playing (bool), progress ({pos, dur} ints 0..86400000, pos <= dur unless dur == 0),
// feedback.skip (int -1 or 1), ledDrive (int 1..255) or ledDither (bool) rejects the frame,
// on every layout and feedback kind. A valid playing is then kept only on the Home layouts
// (nowPlaying/volume/idle/notice) and a valid skip only with kind ok; elsewhere they are
// stripped to their defaults (-1, 0). device.py alive_parse() and _frame() read them
// identically (parity: tests/fixtures/frames_alive.json).
// PRESENTATION_V5.md sections 3-7 (1.0.0-cc5.4, presentation 5) follow the same rules (3.3): the
// layouts seek/explorer/upnext, the ring style lap (1 <= count <= CC_LAP_COUNT_MAX, index < count),
// ring.now (int -1..count-1) and ring.card (bool; true needs count >= 2 and now == count - 2 on a
// selection ring of layout upnext), button lit ("on"/"off"), the nine v5 icons, feedback
// moment/side/color (with kind ok: skip and moment together, or snap without side, reject) and the
// latched reducedMotion, ledPink (int 0..0xFFFFFF) and ledVolFull. Every present value is validated
// on every layout; then now/card are kept only on selection + upnext, a valid ring.unavailable is
// stripped on upnext, moment only with ok, side only with snap, color only with snap/started.
// device.py v5_parse() is the Python reading (parity: tests/fixtures/frames_v5.json).
// Presentation 6 (PRESENTATION_V5.md section 19, Desk Dial r3 release 1) follows the same rules: the layouts
// lights / lightsbig / scenes, the ring styles bri / ctemp (ring.kelvin int 2200..6500 required) and clusters
// (1 <= count <= 20, index < count), ring.kelvin validated on every style and kept only on bri / ctemp,
// valueUnit ("%" | "K", kept on lightsbig), prevTitle / nextTitle (text <= 64 B, kept on scenes) and the six
// icons bulb thermo power wand house album. The Python reading is lcd_preview.v6_parse() (parity:
// harness/fixtures/frames_v6.json, parse_tests.py).
// A2 (1.0.0-cc5.6, CONTROL_CENTER.md "App canvas"): the optional `app` object (CCFrame::app, CCAppState) follows
// the strict rule on any layout; device.py app_parse() is the Python reading (parity: harness/
// app_canvas_tests.py).
// App profiles (APP_PROFILES.md section 8): app.id is any 1..11 characters of [a-z0-9_-] and app.crc an optional
// u32; an id that is not loaded (or a crc that differs) is accepted and drawn as "Loading..." by the LCD thread --
// the one exception to the strict rule. Slots knob / f1..f4 follow the legacy tokens; index goes to 32; param gains axis (0..3) and
// plane (bool). The frame
// cases are in harness/app_store_tests.py.
// r4 FEEL (1.0.0-cc5.7, HAPTICS.md "Events"): the optional `haptic` object ({"token", "seq"}; CCFrame::hapticFx /
// hapticSeq) follows the strict rule on any layout; device.py haptic_parse() is the Python reading (parity:
// harness/haptic_fx_tests.py).

// A JSON integer (never a bool or float) within [lo, hi]. `out` is written
// only on success.
bool cc_json_uint(JsonVariantConst value, uint32_t lo, uint32_t hi, uint32_t& out);

// FW-RES-007: a JSON string as a C token for cc_fx_parse() / cc_feel_parse(), or nullptr when the value is not a
// string or holds an embedded NUL (strcmp would read "confirm.tick\u0000junk" as "confirm.tick"). Length-aware,
// like every other token match in cc_frame_parse.cpp; device.py rejects the same values.
const char* cc_json_token(JsonVariantConst value);

// UTF-8 text into a NUL-terminated buffer of `capacity` bytes. Rejects
// non-strings, malformed UTF-8 (overlong, surrogates, > U+10FFFF, truncated
// sequences) and control characters < 0x20, including an embedded NUL. Longer
// text keeps the longest prefix of whole code points within capacity-1 bytes.
bool cc_json_text(JsonVariantConst value, char* out, size_t capacity);

// Parses one frame object into `frame`, which is reset to the CCFrame defaults
// first. Returns false to reject; `frame` is then unspecified. An "id", when
// present, must be 1..0x7FFFFFFF (the frame command requires it separately).
bool cc_parse_frame(JsonVariantConst value, CCFrame& frame);

// Wire token of an enum value (diagnostics and tests); nullptr when out of range.
enum CCTokenSet : uint8_t {
    CC_TOKENS_ACTIVITY, CC_TOKENS_LAYOUT, CC_TOKENS_TITLE_TONE, CC_TOKENS_LINE_TONE,
    CC_TOKENS_RING_STYLE, CC_TOKENS_ICON, CC_TOKENS_FEEDBACK, CC_TOKENS_TONE,
    CC_TOKENS_LIT, CC_TOKENS_MOMENT,  // presentation 5: CCButtonLit, CCFeedbackMoment
    CC_TOKENS_UNIT,                   // presentation 6: CCValueUnit
    CC_TOKENS_CRUMB                   // presentation 6 (section 19.9): CCCrumb
};
const char* cc_token_name(CCTokenSet set, uint8_t value);
