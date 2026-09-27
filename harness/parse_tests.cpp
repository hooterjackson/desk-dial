// Firmware frame-parser parity runner (Stage 2). Built by parse_tests.py with
// MSVC /W4 /WX together with the unchanged firmware unit
// ../firmware/src/cc_frame_parse.cpp.
//
// Input: a JSON-lines file written by parse_tests.py. Each entry is
//   {"name", "kind", "line_b64", "accept", "text": {field: bytes}, "fields": {field: value}}
// where line_b64 is the exact wire line ({"frame":...}) in base64, so byte
// sequences that are not valid UTF-8 can be exercised too. The runner parses
// the line with ArduinoJson exactly as the COM thread does, feeds "frame" to
// cc_parse_frame(), and compares accept/reject, every listed stored text field
// (byte-identical) and every listed typed field, including the 1.0.0-cc5.4
// ALIVE.md section 3 fields (playing, feedbackSkip, clock, progress, ledDrive,
// ledDither; null = absent) and the PRESENTATION_V5.md section 15.1 `stored` set
// (ringNow, ringCard, lit[4], color[4], icon[4], feedbackKind, feedbackMoment,
// feedbackSide, feedbackColor, reducedMotion, ledPink, ledVolFull; null = absent).
// Exit status 1 on any mismatch.
//
// With CC_V4_PARSER the same runner is built against the cc5.3 (presentation 4)
// parser snapshot instead (parse_tests.py extracts it from the cc5.3 source zip):
// rules.downgrade feeds it every presentation-4 host output of frames_v5.json.
// The ALIVE and v5 field checks do not exist there.
//
// --frames <cases.jsonl>: the entries are lines recorded from a companion
// session (parse_tests.py --frames). Each entry additionally has "wire"
// ("frame" or "control") and "cc4". The runner applies the command checks
// control_center.cpp applies around cc_parse_frame (frame id; control id,
// bounds, position, windowsButton, buttonOrder, windowsHidEnabled), requires
// acceptance, compares every stored text field with the text of the line
// itself (as ArduinoJson decodes it; "" when absent) and with the Python
// expectations, and checks the typed fields. With "cc4" and CC4_PARSER, the
// line is also parsed by the installed cc4 firmware's parser (a verbatim
// excerpt generated into cc4_parser.inc) and its stored text compared too.
// Ends with one "CAPTURE-SUMMARY {json}" line.
#include <ArduinoJson.h>
#include "cc_frame_parse.h"
#include "cc_presentation.h"

#include <cstdio>
#include <cstring>
#include <fstream>
#include <map>
#include <string>
#include <string.h>
#include <vector>

#if defined(CC4_PARSER)
// The installed cc4 firmware's own frame parser (presentation 2), excerpted
// verbatim into `namespace cc4` by parse_tests.py --frames. Its device (gcc)
// build accepted the implicit narrowing of uint32_t ring values into the
// uint8_t/uint16_t CCFrame fields; only that MSVC warning is silenced, and only
// for the excerpt. The harness code itself stays /W4 /WX.
#ifdef _MSC_VER
#pragma warning(push)
#pragma warning(disable : 4244)
#endif
#include "cc4_parser.inc"
#ifdef _MSC_VER
#pragma warning(pop)
#endif
#endif

namespace {
int failures = 0;
std::map<std::string, int> kinds, textChecks, fieldChecks;

std::string decode_base64(const std::string& input) {
    static const std::string alphabet =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string out;
    unsigned buffer = 0;
    int bits = 0;
    for (char c : input) {
        if (c == '=') break;
        const size_t index = alphabet.find(c);
        if (index == std::string::npos) continue;
        buffer = (buffer << 6) | static_cast<unsigned>(index);
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            out.push_back(static_cast<char>((buffer >> bits) & 0xFF));
        }
    }
    return out;
}

std::string printable(const char* bytes, size_t size) {
    std::string out;
    for (size_t i = 0; i < size; ++i) {
        const unsigned char c = static_cast<unsigned char>(bytes[i]);
        if (c >= 0x20 && c < 0x7F && c != '\\') out.push_back(static_cast<char>(c));
        else {
            char hex[8];
            std::snprintf(hex, sizeof(hex), "\\x%02X", c);
            out += hex;
        }
    }
    return out;
}

void fail(const std::string& name, const std::string& what) {
    ++failures;
    std::printf("FAIL %s: %s\n", name.c_str(), what.c_str());
}

const char* stored_text(const CCFrame& f, const std::string& field) {
    if (field == "mode") return f.mode;
    if (field == "target") return f.target;
    if (field == "value") return f.value;
    if (field == "detail") return f.detail;
    if (field == "status") return f.status;
    if (field == "title") return f.title;
    if (field == "subtitle") return f.subtitle;
    if (field == "counter") return f.counter;
    if (field == "heading") return f.heading;
    if (field == "meta") return f.meta;
    if (field == "artKey") return f.artKey;
    if (field == "iconKey") return f.iconKey;   // 1.0.0-cc5.3
    if (field == "volumeCaption") return f.volumeCaption;
    if (field.size() == 6 && field.compare(0, 5, "label") == 0 && field[5] >= '0' && field[5] <= '3')
        return f.buttons[field[5] - '0'].label;
    return nullptr;
}

std::string token(CCTokenSet set, uint8_t value) {
    const char* name = cc_token_name(set, value);
    return name ? name : "<out of range>";
}

bool expect_string(const std::string& name, const std::string& field, const std::string& actual,
                   JsonVariantConst expected) {
    if (!expected.is<const char*>() || actual != expected.as<const char*>()) {
        fail(name, field + ": stored \"" + actual + "\", expected " +
             (expected.is<const char*>() ? "\"" + std::string(expected.as<const char*>()) + "\"" : "a string"));
        return false;
    }
    return true;
}

bool expect_int(const std::string& name, const std::string& field, long long actual, JsonVariantConst expected) {
    if (expected.is<bool>() || !expected.is<long long>() || actual != expected.as<long long>()) {
        fail(name, field + ": stored " + std::to_string(actual) + ", expected " +
             (expected.is<long long>() ? std::to_string(expected.as<long long>()) : std::string("an integer")));
        return false;
    }
    return true;
}

bool expect_bool(const std::string& name, const std::string& field, bool actual, JsonVariantConst expected) {
    if (!expected.is<bool>() || actual != expected.as<bool>()) {
        fail(name, field + ": stored " + (actual ? "true" : "false") + ", unexpected");
        return false;
    }
    return true;
}

// An optional latched ALIVE.md section 3 field: null = absent (present flag false, value the
// CCFrame default), otherwise present with that value.
bool expect_latched(const std::string& name, const std::string& field, bool present, long long actual,
                    long long absentValue, JsonVariantConst expected) {
    if (expected.isNull()) {
        if (present || actual != absentValue) {
            fail(name, field + ": stored " + std::to_string(actual) + (present ? " (present)" : "") +
                       ", expected absent");
            return false;
        }
        return true;
    }
    if (!present) { fail(name, field + ": absent, expected present"); return false; }
    return expected.is<bool>() ? expect_bool(name, field, actual != 0, expected)
                               : expect_int(name, field, actual, expected);
}

// Typed (non-text) CCFrame fields, by the names parse_tests.py uses.
bool check_field(const std::string& name, const CCFrame& f, const std::string& field, JsonVariantConst expected) {
    if (field == "activity") return expect_string(name, field, token(CC_TOKENS_ACTIVITY, f.activity), expected);
    if (field == "layout") return expect_string(name, field, token(CC_TOKENS_LAYOUT, f.layoutId), expected);
    if (field == "restLayout") return expect_string(name, field, token(CC_TOKENS_LAYOUT, f.restLayout), expected);
    if (field == "titleTone") return expect_string(name, field, token(CC_TOKENS_TITLE_TONE, f.titleTone), expected);
    if (field == "metaTone") return expect_string(name, field, token(CC_TOKENS_LINE_TONE, f.metaTone), expected);
    if (field == "statusTone") return expect_string(name, field, token(CC_TOKENS_LINE_TONE, f.statusTone), expected);
    if (field == "ledStyle") return expect_string(name, field, f.coloredLeds ? "color" : "white", expected);
    if (field == "page") return expect_int(name, field, f.page, expected);
    if (field == "confirmedVolume") return expect_int(name, field, f.confirmedVolume, expected);
    if (field == "artDim") return expect_bool(name, field, f.artDim, expected);
    if (field == "feedback") {
        if (expected.isNull()) {
            if (f.feedbackPresent) { fail(name, "feedback: stored, expected absent"); return false; }
            return true;
        }
        if (!f.feedbackPresent) { fail(name, "feedback: absent, expected present"); return false; }
        return expect_string(name, "feedback.kind", token(CC_TOKENS_FEEDBACK, f.feedbackKind), expected["kind"]) &&
               expect_int(name, "feedback.seq", f.feedbackSeq, expected["seq"]);
    }
#ifndef CC_V4_PARSER
    // 1.0.0-cc5.4 (ALIVE.md section 3).
    if (field == "playing") return expect_int(name, field, f.playing, expected);
    if (field == "feedbackSkip") return expect_int(name, field, f.feedbackSkip, expected);
    if (field == "clock") return expect_latched(name, field, f.clockPresent, f.clockMinute, 0, expected);
    if (field == "ledDrive") return expect_latched(name, field, f.ledDrivePresent, f.ledDrive, 0, expected);
    // Absent: ledDither false (the 2026-09-26 user ruling, ALIVE.md 9 / 12.7: dither off by default).
    if (field == "ledDither") return expect_latched(name, field, f.ledDitherPresent, f.ledDither ? 1 : 0, 0, expected);
    if (field == "progress") {
        if (expected.isNull()) {
            if (f.progressPresent || f.progressPos || f.progressDur) {
                fail(name, "progress: stored, expected absent");
                return false;
            }
            return true;
        }
        if (!f.progressPresent) { fail(name, "progress: absent, expected present"); return false; }
        return expect_int(name, "progress.pos", f.progressPos, expected["pos"]) &&
               expect_int(name, "progress.dur", f.progressDur, expected["dur"]);
    }
    // PRESENTATION_V5.md section 15.1 `stored` (1.0.0-cc5.4, presentation 5).
    if (field == "ringNow") return expect_int(name, field, f.ringNow, expected);
    if (field == "ringCard") return expect_bool(name, field, f.ringCard, expected);
    if (field == "feedbackKind") {
        if (expected.isNull()) {
            if (f.feedbackPresent) { fail(name, "feedbackKind: stored, expected no feedback"); return false; }
            return true;
        }
        if (!f.feedbackPresent) { fail(name, "feedbackKind: no feedback stored"); return false; }
        return expect_string(name, field, token(CC_TOKENS_FEEDBACK, f.feedbackKind), expected);
    }
    if (field == "feedbackMoment") {
        if (expected.isNull()) {
            if (f.feedbackMoment != CC_MOMENT_NONE) {
                fail(name, "feedbackMoment: stored " + token(CC_TOKENS_MOMENT, f.feedbackMoment) + ", expected none");
                return false;
            }
            return true;
        }
        return expect_string(name, field, token(CC_TOKENS_MOMENT, f.feedbackMoment), expected);
    }
    if (field == "feedbackSide") return expect_int(name, field, f.feedbackSide, expected);
    if (field == "feedbackColor") return expect_int(name, field, f.feedbackColor, expected);
    if (field == "reducedMotion")
        return expect_latched(name, field, f.reducedMotionPresent, f.reducedMotion ? 1 : 0, 0, expected);
    if (field == "ledPink") return expect_latched(name, field, f.ledPinkPresent, f.ledPink, 0, expected);
    if (field == "ledVolFull")
        return expect_latched(name, field, f.ledVolFullPresent, f.ledVolFull ? 1 : 0, 0, expected);
    if (field == "lit" || field == "color" || field == "icon") {
        if (!expected.is<JsonArrayConst>() || expected.size() != 4) {
            fail(name, field + ": expectation is not a list of four");
            return false;
        }
        bool same = true;
        for (uint8_t slot = 0; slot < 4; ++slot) {
            const CCButton& button = f.buttons[slot];
            JsonVariantConst want = expected[slot];
            const std::string label = field + "[" + std::to_string(slot) + "]";
            if (field == "lit") {
                if (want.isNull()) {
                    if (button.lit != CC_LIT_NONE) {
                        fail(name, label + ": stored " + token(CC_TOKENS_LIT, button.lit) + ", expected absent");
                        same = false;
                    }
                } else if (!expect_string(name, label, token(CC_TOKENS_LIT, button.lit), want)) {
                    same = false;
                }
            } else if (field == "color") {
                if (!expect_int(name, label, button.color, want)) same = false;
            } else if (!expect_string(name, label, token(CC_TOKENS_ICON, button.icon), want)) {
                same = false;
            }
        }
        return same;
    }
#endif
    if (field == "ringStyle") return expect_string(name, field, token(CC_TOKENS_RING_STYLE, f.ringStyle), expected);
    if (field == "ringValue") return expect_int(name, field, f.ringValue, expected);
    if (field == "ringIndex") return expect_int(name, field, f.ringIndex, expected);
    if (field == "ringCount") return expect_int(name, field, f.ringCount, expected);
    if (field == "ringFirst") return expect_int(name, field, f.ringFirst, expected);
    if (field == "ringUnavailable") return expect_int(name, field, f.ringUnavailable, expected);
    if (field == "ringMoreIndex") return expect_int(name, field, f.ringMoreIndex, expected);
    if (field == "ringExternal") return expect_bool(name, field, f.ringExternal, expected);
    if (field == "ringColors") {
        if (!expected.is<JsonArrayConst>()) { fail(name, "ringColors: expectation is not a list"); return false; }
        JsonArrayConst colors = expected.as<JsonArrayConst>();
        bool same = colors.size() == f.ringColorCount;
        for (size_t k = 0; same && k < colors.size(); ++k)
            same = colors[k].as<uint32_t>() == f.ringColors[k];
        if (!same) fail(name, "ringColors: stored " + std::to_string(f.ringColorCount) +
                              " colour(s), expected " + std::to_string(colors.size()) + " different value(s)");
        return same;
    }
    if (field.size() >= 2) {
        const char last = field[field.size() - 1];
        if (last >= '0' && last <= '3') {
            const uint8_t slot = static_cast<uint8_t>(last - '0');
            const std::string base = field.substr(0, field.size() - 1);
            const CCButton& button = f.buttons[slot];
            if (base == "enabled") return expect_bool(name, field, button.enabled, expected);
            if (base == "icon") return expect_string(name, field, token(CC_TOKENS_ICON, button.icon), expected);
            if (base == "iconSent") return expect_bool(name, field, button.iconSent, expected);
            if (base == "tone") return expect_string(name, field, token(CC_TOKENS_TONE, cc_button_tone(f, slot)), expected);
            if (base == "ink") return expect_int(name, field, cc_button_ink(f, slot), expected);
        }
    }
    fail(name, "unknown expectation field " + field);
    return false;
}

// The entry's "text" (byte-identical stored strings) and "fields" (typed values)
// against an accepted frame. Returns the number of mismatching text fields.
int compare_expectations(const std::string& name, const std::string& kind, const CCFrame& frame,
                         JsonObjectConst entry) {
    int differ = 0;
    for (JsonPairConst pair : entry["text"].as<JsonObjectConst>()) {
        const std::string field = pair.key().c_str();
        const char* stored = stored_text(frame, field);
        if (!stored) { fail(name, "unknown text field " + field); ++differ; continue; }
        const JsonString expected = pair.value().as<JsonString>();
        ++textChecks[kind];
        if (std::strlen(stored) != expected.size() || std::memcmp(stored, expected.c_str(), expected.size())) {
            ++differ;
            fail(name, field + ": stored \"" + printable(stored, std::strlen(stored)) + "\", expected \"" +
                       printable(expected.c_str(), expected.size()) + "\"");
        }
    }
    for (JsonPairConst pair : entry["fields"].as<JsonObjectConst>()) {
        ++fieldChecks[kind];
        check_field(name, frame, pair.key().c_str(), pair.value());
    }
    return differ;
}

void run_entry(JsonObjectConst entry) {
    const std::string name = entry["name"] | "<unnamed>";
    const std::string kind = entry["kind"] | "<kind>";
    const std::string line = decode_base64(entry["line_b64"] | "");
    const bool accept = entry["accept"] | false;
    ++kinds[kind];

    JsonDocument doc;
    DeserializationError error = deserializeJson(doc, line.data(), line.size());
    if (error) { fail(name, std::string("wire line is not JSON: ") + error.c_str()); return; }
    static CCFrame frame; // Same as the COM thread: never a CCFrame on the stack.
    const bool accepted = cc_parse_frame(doc["frame"], frame);
    if (accepted != accept) {
        fail(name, std::string(accepted ? "accepted" : "rejected") + ", expected " + (accept ? "accept" : "reject"));
        return;
    }
    if (!accepted) return;
    compare_expectations(name, kind, frame, entry);
}

// ---------------------------------------------------------------------------
// --frames: lines recorded from a companion session.
const char* const kTextFields[] = {"mode", "target", "value", "detail", "status", "title", "subtitle",
                                   "counter", "heading", "meta", "artKey", "volumeCaption", "iconKey"};

struct CaptureStats {
    int lines = 0, accepted = 0, rejected = 0, inputTexts = 0, inputDiffs = 0, expectedDiffs = 0;
    int cc4Lines = 0, cc4Accepted = 0, cc4Rejected = 0, cc4InputTexts = 0, cc4Diffs = 0;
};
std::map<std::string, CaptureStats> captureStats;

// Stored text against the same field of the line itself, as ArduinoJson decodes
// it ("" when the field is absent).
bool same_as_input(const std::string& name, const std::string& field, const char* stored, JsonVariantConst input) {
    std::string sent;
    if (!input.isNull()) {
        if (!input.is<const char*>()) { fail(name, field + ": the input is not a string"); return false; }
        const JsonString value = input.as<JsonString>();
        sent.assign(value.c_str(), value.size());
    }
    const size_t size = std::strlen(stored);
    if (size == sent.size() && !std::memcmp(stored, sent.data(), size)) return true;
    fail(name, field + " differs from the line: stored \"" + printable(stored, size) + "\", sent \"" +
               printable(sent.data(), sent.size()) + "\"");
    return false;
}

// What control_center.cpp (cc_handle_command) checks around cc_parse_frame.
bool command_valid(const std::string& name, const std::string& wire, JsonObjectConst message) {
    uint32_t value = 0;
    if (wire == "frame") {
        if (!cc_json_uint(message["frame"]["id"], 1, 0x7FFFFFFF, value)) {
            fail(name, "REJECTED: frame id missing or outside 1..0x7FFFFFFF (\"Invalid control frame\")");
            return false;
        }
        return true;
    }
    if (wire != "control" || !message["control"].is<JsonObjectConst>()) {
        fail(name, "REJECTED: not a frame or control command");
        return false;
    }
    JsonObjectConst control = message["control"].as<JsonObjectConst>();
    if (control.containsKey("windowsHidEnabled") && !control["windowsHidEnabled"].is<bool>()) {
        fail(name, "REJECTED: windowsHidEnabled is not a boolean");
        return false;
    }
    if (!control["buttonOrder"].isNull()) {
        JsonArrayConst order = control["buttonOrder"].as<JsonArrayConst>();
        unsigned seen = 0;
        bool valid = order.size() == 4;
        for (size_t i = 0; valid && i < 4; ++i) {
            valid = cc_json_uint(order[i], 0, 3, value) && !(seen & (1u << value));
            seen |= 1u << value;
        }
        if (!valid) { fail(name, "REJECTED: invalid buttonOrder"); return false; }
    }
    uint32_t lo = 0, hi = 0;
    const char* profile = control["profile"] | "";
    if (!cc_json_uint(control["id"], 1, 0x7FFFFFFF, value) || !cc_json_uint(control["min"], 0, 0, lo) ||
        !cc_json_uint(control["max"], 0, 65535, hi) || !cc_json_uint(control["position"], lo, hi, value) ||
        !cc_json_uint(control["windowsButton"], 0, 3, value) || !*profile) {
        fail(name, "REJECTED: control id, bounds, position, windowsButton or profile");
        return false;
    }
    return true;
}

// Stored text and labels against the line; returns the number of differences.
int compare_with_input(const std::string& name, const CCFrame& frame, JsonVariantConst sent, CaptureStats& stats) {
    int differ = 0;
    for (const char* field : kTextFields) {
        ++stats.inputTexts;
        if (!same_as_input(name, field, stored_text(frame, field), sent[field])) ++differ;
    }
    for (size_t slot = 0; slot < 4; ++slot) {
        ++stats.inputTexts;
        if (!same_as_input(name, "label" + std::to_string(slot), frame.buttons[slot].label, sent["buttons"][slot]["label"]))
            ++differ;
    }
    return differ;
}

#if defined(CC4_PARSER)
const char* cc4_text(const cc4::CCFrame& f, const std::string& field) {
    if (field == "mode") return f.mode;
    if (field == "target") return f.target;
    if (field == "value") return f.value;
    if (field == "detail") return f.detail;
    if (field == "status") return f.status;
    if (field == "title") return f.title;
    if (field == "subtitle") return f.subtitle;
    if (field == "counter") return f.counter;
    return nullptr;
}

// The frame a cc4 command handler hands to parse_frame(), the same way it does.
JsonVariant cc4_target(JsonDocument& doc, const std::string& wire) {
    if (wire == "control") {
        JsonVariant control = doc["control"];
        return control["frame"];
    }
    return doc["frame"];
}

void run_cc4(const std::string& name, const std::string& line, const std::string& wire, CaptureStats& stats) {
    ++stats.cc4Lines;
    JsonDocument doc; // cc4 parses a mutable JsonVariant, as on the device
    if (deserializeJson(doc, line.data(), line.size())) { ++stats.cc4Rejected; fail(name, "cc4: line is not JSON"); return; }
    JsonVariant target = cc4_target(doc, wire);
    static cc4::CCFrame frame;
    frame = cc4::CCFrame(); // cc4 parses into a fresh `CCFrame incoming` per command
    if (!cc4::parse_frame(target, frame)) {
        ++stats.cc4Rejected;
        fail(name, "REJECTED by the installed cc4 parser");
        return;
    }
    ++stats.cc4Accepted;
    const JsonVariantConst sent = target;
    static const char* const fields[] = {"mode", "target", "value", "detail", "status", "title", "subtitle", "counter"};
    for (const char* field : fields) {
        ++stats.cc4InputTexts;
        if (!same_as_input(name, std::string("cc4 ") + field, cc4_text(frame, field), sent[field])) ++stats.cc4Diffs;
    }
    for (size_t slot = 0; slot < 4; ++slot) {
        ++stats.cc4InputTexts;
        if (!same_as_input(name, "cc4 label" + std::to_string(slot), frame.buttons[slot].label, sent["buttons"][slot]["label"]))
            ++stats.cc4Diffs;
    }
}
#endif

void run_capture_entry(JsonObjectConst entry) {
    const std::string name = entry["name"] | "<unnamed>";
    const std::string kind = entry["kind"] | "<kind>";
    const std::string wire = entry["wire"] | "";
    const std::string line = decode_base64(entry["line_b64"] | "");
    CaptureStats& stats = captureStats[kind];
    ++kinds[kind];
    ++stats.lines;
    JsonDocument doc;
    DeserializationError error = deserializeJson(doc, line.data(), line.size());
    if (error || !doc.is<JsonObjectConst>()) {
        ++stats.rejected;
        fail(name, "REJECTED: the line is not a JSON object");
        return;
    }
    const JsonObjectConst message = doc.as<JsonObjectConst>();
    const JsonVariantConst sent = wire == "control" ? message["control"]["frame"] : message["frame"];
    static CCFrame frame; // Same as the COM thread: never a CCFrame on the stack.
    if (!command_valid(name, wire, message)) { ++stats.rejected; return; }
    if (!cc_parse_frame(sent, frame)) {
        ++stats.rejected;
        fail(name, "REJECTED by cc_parse_frame");
        return;
    }
    ++stats.accepted;
    stats.inputDiffs += compare_with_input(name, frame, sent, stats);
    stats.expectedDiffs += compare_expectations(name, kind, frame, entry);
#if defined(CC4_PARSER)
    if (entry["cc4"] | false) run_cc4(name, line, wire, stats);
#endif
}

int capture_summary(int entries) {
    CaptureStats total;
    std::printf("%-12s %6s %8s %8s %11s %6s %9s %8s\n", "kind", "lines", "accepted", "rejected", "text-checks",
                "differ", "cc4-lines", "cc4-ok");
    for (const auto& item : captureStats) {
        const CaptureStats& s = item.second;
        std::printf("%-12s %6d %8d %8d %11d %6d %9d %8d\n", item.first.c_str(), s.lines, s.accepted, s.rejected,
                    s.inputTexts + textChecks[item.first], s.inputDiffs + s.expectedDiffs + s.cc4Diffs, s.cc4Lines,
                    s.cc4Accepted);
        total.lines += s.lines; total.accepted += s.accepted; total.rejected += s.rejected;
        total.inputTexts += s.inputTexts; total.inputDiffs += s.inputDiffs; total.expectedDiffs += s.expectedDiffs;
        total.cc4Lines += s.cc4Lines; total.cc4Accepted += s.cc4Accepted; total.cc4Rejected += s.cc4Rejected;
        total.cc4InputTexts += s.cc4InputTexts; total.cc4Diffs += s.cc4Diffs;
    }
    int expectedTexts = 0, fields = 0;
    for (const auto& item : textChecks) expectedTexts += item.second;
    for (const auto& item : fieldChecks) fields += item.second;
    JsonDocument summary;
    summary["lines"] = total.lines;
    summary["accepted"] = total.accepted;
    summary["rejected"] = total.rejected;
    summary["inputTextChecks"] = total.inputTexts;
    summary["inputTextDiffs"] = total.inputDiffs;
    summary["expectedTextChecks"] = expectedTexts;
    summary["expectedTextDiffs"] = total.expectedDiffs;
    summary["fieldChecks"] = fields;
#if defined(CC4_PARSER)
    summary["cc4Parser"] = true;
#else
    summary["cc4Parser"] = false;
#endif
    summary["cc4Lines"] = total.cc4Lines;
    summary["cc4Accepted"] = total.cc4Accepted;
    summary["cc4Rejected"] = total.cc4Rejected;
    summary["cc4TextChecks"] = total.cc4InputTexts;
    summary["cc4TextDiffs"] = total.cc4Diffs;
    summary["failures"] = failures;
    std::string json;
    serializeJson(summary, json);
    std::printf("CAPTURE-SUMMARY %s\n", json.c_str());
    if (failures || total.lines != entries) {
        std::printf("FAIL: %d mismatch(es) over %d recorded line(s)\n", failures, entries);
        return 1;
    }
    std::printf("PASS: %d recorded line(s) accepted by cc_parse_frame, stored text identical", total.accepted);
#if defined(CC4_PARSER)
    std::printf("; cc4 parser accepted %d legacy line(s)", total.cc4Accepted);
#endif
    std::printf("\n");
    return 0;
}
} // namespace

int main(int argc, char** argv) {
    const bool frames = argc >= 3 && !std::strcmp(argv[1], "--frames");
    const char* path = frames ? argv[2] : (argc >= 2 ? argv[1] : nullptr);
    if (!path) { std::printf("usage: parse_tests <cases.jsonl> | parse_tests --frames <cases.jsonl>\n"); return 2; }
    std::ifstream input(path, std::ios::binary);
    if (!input) { std::printf("FAIL: cannot read %s\n", path); return 2; }
    std::printf("sizeof(CCFrame) = %u bytes, sizeof(CCButton) = %u bytes\n",
                static_cast<unsigned>(sizeof(CCFrame)), static_cast<unsigned>(sizeof(CCButton)));
    std::string text;
    int entries = 0;
    while (std::getline(input, text)) {
        if (text.empty()) continue;
        JsonDocument entry;
        DeserializationError error = deserializeJson(entry, text);
        if (error || !entry.is<JsonObject>()) { fail("<file>", "unreadable case line"); continue; }
        ++entries;
        if (frames) run_capture_entry(entry.as<JsonObjectConst>());
        else run_entry(entry.as<JsonObjectConst>());
    }
    if (frames) return capture_summary(entries);
    for (const auto& kind : kinds)
        std::printf("%-14s %4d case(s), %5d text comparison(s), %5d field comparison(s)\n", kind.first.c_str(),
                    kind.second, textChecks[kind.first], fieldChecks[kind.first]);
    if (failures) {
        std::printf("FAIL: %d mismatch(es) over %d case(s)\n", failures, entries);
        return 1;
    }
    std::printf("PASS: %d parser case(s), 0 mismatches\n", entries);
    return 0;
}
