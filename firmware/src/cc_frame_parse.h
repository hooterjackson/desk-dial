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

// A JSON integer (never a bool or float) within [lo, hi]. `out` is written
// only on success.
bool cc_json_uint(JsonVariantConst value, uint32_t lo, uint32_t hi, uint32_t& out);

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
    CC_TOKENS_LIT, CC_TOKENS_MOMENT   // presentation 5: CCButtonLit, CCFeedbackMoment
};
const char* cc_token_name(CCTokenSet set, uint8_t value);
