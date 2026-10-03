// artwork2 media store checks (1.0.0-cc5.3). Built by media_tests.py with MSVC /W4 /WX together
// with the unchanged firmware header ../firmware/src/cc_media_store.h and unit
// src/cc_jpeg.cpp (through tjpgd_shim/ and LVGL's TJpgDec R0.03). Written in the C++11 subset
// (the firmware is gnu++11).
//
// Part 1 - trace parity. argv[1] is media_store_traces.json, the fixture the companion's
// FakeKnob replays too. Each case builds one CCMediaStore with the case's configuration and
// replays its steps with the shared runner rules: "control"/"release" set the active control ID
// and cancel the upload; "frame" sets both frame keys, then adopts each (or releases the
// display when the key is empty) unless noAdopt; "adopt" adopts; "media" runs the request and
// compares the mediaAck byte for byte (key order included); after a successful miss commit
// whose key equals the kind's frame key the runner adopts it; "check" compares each part it
// carries: every slot's [valid, key, stamp], displayed, clock and receiving (the store's
// receiving(): an upload context that is not a begin hit). validateJpeg true checks covers with
// the real cc_jpeg_validate. A kind whose config says "available": false gets neither memory nor
// slots, as cc_media.cpp leaves a store it could not allocate (its slot table is empty).
//
// Before part 1, argv[5] lists every cover payload the reference Model of media_tests.py judged
// while building the fixture, with its verdict: cc_jpeg_validate must agree on each.
//
// Part 2 - direct assertions: CRC-32, base64, keys, media line detection, parse replies, the
// COM thread's line transport (cc_bad_line_reply, CCLineAssembler's oversize and expiry rules,
// cc_com_idle_ticks: ARTWORK2.md section 3), unavailable stores, every slot pinned, adoption
// pointers, receiving(), counters, version, frame key normalisation, the device configuration
// and (argv[2], the host's presentation.ARTWORK2_CAPABILITY serialised by media_tests.py) the
// capability object byte for byte, key order included.
//
// Part 3 (CC_MEDIA_WIRING: media_tests.py links a verbatim copy of src/control_center.cpp, the
// real src/cc_media.cpp and src/cc_frame_parse.cpp, against host stubs of Arduino, FreeRTOS,
// the heap, the preset manager and the FOC thread): the control_center.cpp media wiring through
// cc_handle_command/cc_take_request/cc_service. The capability object in the full reply
// (after artwork, before diag; rxBytes 0 when the queue is not in internal RAM); a media line
// gets exactly one reply: the mediaAck ahead of release, control and frame, while capabilities,
// diag and art (cc5.2's order) are dispatched before media and answer alone; frame keys set by an
// accepted control and an accepted frame only (a stale or invalid frame, a busy or invalid
// control change nothing), observed through the store's pinning on the real device
// configuration; the upload cancelled by a new control (and rebound to its ID), a release and a
// lease expiry (at the next service pass, or at the next media line), and never by a stale media
// ID or a rejected control; media lines never renew the lease, frames do. Raw bytes routed as
// com_thread.cpp routes them (CCLineAssembler, cc_bad_line_reply): an oversize or non-JSON media
// line gets exactly one parse mediaAck from the real cc_media_parse_reply, counted in
// mediaErrors. argv[3] is a valid windows frame (frames_v4.json v4-windows-icon-key), argv[4] a
// valid 240x240 cover.
#include <ArduinoJson.h>
#include "cc_jpeg.h"
#include "cc_media.h"
#include "cc_media_store.h"
#if defined(CC_MEDIA_WIRING)
#include <esp_heap_caps.h>
#include "HapticProfileManager.h"   // the stub (media_tests.py puts the stubs before src/)
#include "cc_artwork.h"
#include "cc_diag.h"
#include "cc_serial_out.h"
#include "control_center.h"
#include "foc_thread.h"             // the stub
#include "haptic_bounds.h"          // 1.0.0-cc5.5 F1: haptic_profile_sanitize()
#include "cc_haptic_fx.h"           // FW-BUG-029: the recalibration words (cc_haptic_detail::shared())
#endif

#include <algorithm>
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
    if (failures <= 60) std::printf("FAIL: %s\n", message.c_str());
}

void require(bool condition, const std::string& message) {
    ++checks;
    if (!condition) report(message);
}

std::string num(long long value) {
    char text[32];
    std::snprintf(text, sizeof(text), "%lld", value);
    return text;
}

std::string dump(JsonVariantConst value) {
    std::string text;
    serializeJson(value, text);
    return text;
}

bool jpeg_check(const uint8_t* data, uint32_t bytes) {
    uint16_t w = 0, h = 0;
    return cc_jpeg_validate(data, bytes, &w, &h);
}

bool accept_all(const uint8_t*, uint32_t) { return true; }

const char* const kKinds[] = {"cover", "icon"};

// One store with its own memory, like cc_media.cpp (heap here instead of PSRAM).
struct Harness {
    CCMediaStore store;
    CCMediaConfig config;
    std::vector<uint8_t> memory[2], scratch;
    std::vector<CCMediaSlot> slots[2];
    uint32_t activeId = 0;

    void init(const CCMediaConfig& c, CCMediaCoverCheck check, bool coverMemory = true, bool withScratch = true) {
        config = c;
        for (uint8_t k = 0; k < 2; ++k) {
            memory[k].assign(static_cast<size_t>(c.kinds[k].entries + 1) * c.kinds[k].slotBytes, 0xA5);
            slots[k].assign(c.kinds[k].entries + 1, CCMediaSlot());
        }
        scratch.assign(c.chunkBytes, 0);
        store.init(c, coverMemory ? memory[0].data() : nullptr, slots[0].data(), memory[1].data(), slots[1].data(),
                   withScratch ? scratch.data() : nullptr, check);
    }

    // One media request; returns the serialised mediaAck object and applies the runner's
    // adoption rule after a successful miss commit.
    std::string media(JsonVariantConst request) {
        JsonDocument out;
        const uint32_t before = store.version();
        store.handle(request, activeId, out["mediaAck"].to<JsonObject>());
        if (store.version() != before) {
            const char* kind = request["kind"] | "";
            const char* key = request["key"] | "";
            const uint8_t k = static_cast<uint8_t>(std::strcmp(kind, "icon") == 0 ? CC_MEDIA_ICON : CC_MEDIA_COVER);
            if (std::strcmp(store.frameKey(k), key) == 0) store.adopt(k, key, nullptr, nullptr);
        }
        return dump(out["mediaAck"]);
    }

    std::string media(const std::string& json) {
        JsonDocument request;
        deserializeJson(request, json);
        return media(request.as<JsonVariantConst>());
    }

    // The trace runner's store: a kind that is not available has neither memory nor slots, the
    // shape cc_media.cpp leaves when an allocation failed.
    void init_available(const CCMediaConfig& c, CCMediaCoverCheck check, const bool (&available)[2]) {
        init(c, check);
        store.init(c, available[0] ? memory[0].data() : nullptr, available[0] ? slots[0].data() : nullptr,
                   available[1] ? memory[1].data() : nullptr, available[1] ? slots[1].data() : nullptr,
                   scratch.data(), check);
    }
};

CCMediaConfig config_from(JsonObjectConst c) {
    CCMediaConfig config;
    config.kinds[CC_MEDIA_COVER].entries = c["cover"]["entries"];
    config.kinds[CC_MEDIA_COVER].slotBytes = c["cover"]["slotBytes"];
    config.kinds[CC_MEDIA_COVER].minBytes = 1;
    config.kinds[CC_MEDIA_COVER].maxBytes = c["cover"]["maxBytes"];
    config.kinds[CC_MEDIA_ICON].entries = c["icon"]["entries"];
    config.kinds[CC_MEDIA_ICON].slotBytes = c["icon"]["slotBytes"];
    config.kinds[CC_MEDIA_ICON].minBytes = c["icon"]["bytes"];
    config.kinds[CC_MEDIA_ICON].maxBytes = c["icon"]["bytes"];
    config.chunkBytes = c["chunkBytes"];
    config.haveKeys = c["haveKeys"];
    config.validateCovers = c["validateJpeg"] | false;
    return config;
}

long long media_steps = 0, check_steps = 0, other_steps = 0;

// Each part the step carries (slots, displayed, clock, receiving), like the Python runner.
void compare_check(Harness& h, JsonObjectConst step, const std::string& where) {
    for (uint8_t k = 0; k < 2; ++k) {
        if (!step["slots"].isNull()) {
            // An unallocated kind has no slot table (cc_media.cpp passes no slots).
            const uint32_t count = h.store.available(k) ? h.store.slotCount(k) : 0;
            JsonArrayConst expected = step["slots"][kKinds[k]].as<JsonArrayConst>();
            require(!step["slots"][kKinds[k]].isNull() && expected.size() == count,
                    where + ": " + kKinds[k] + " slot count " + num(count) + ", expected " +
                        dump(step["slots"][kKinds[k]]));
            for (uint32_t i = 0; i < count && i < expected.size(); ++i) {
                const CCMediaSlot& slot = h.store.slot(k, i);
                JsonArrayConst row = expected[i].as<JsonArrayConst>();
                const std::string actual = std::string("[") + (slot.valid ? "true" : "false") + ",\"" + slot.key +
                                           "\"," + num(slot.stamp) + "]";
                require(row[0].as<bool>() == slot.valid && std::strcmp(row[1] | "", slot.key) == 0 &&
                            row[2].as<long long>() == static_cast<long long>(slot.stamp),
                        where + ": " + kKinds[k] + " slot " + num(i) + " is " + actual + ", expected " + dump(row));
            }
        }
        if (!step["displayed"].isNull())
            require(step["displayed"][kKinds[k]].is<long long>() &&
                        step["displayed"][kKinds[k]].as<long long>() == h.store.displayed(k),
                    where + ": " + kKinds[k] + " displayed " + num(h.store.displayed(k)) + ", expected " +
                        dump(step["displayed"][kKinds[k]]));
        if (!step["clock"].isNull())
            require(step["clock"][kKinds[k]].is<long long>() &&
                        step["clock"][kKinds[k]].as<long long>() == static_cast<long long>(h.store.clock(k)),
                    where + ": " + kKinds[k] + " clock " + num(h.store.clock(k)) + ", expected " +
                        dump(step["clock"][kKinds[k]]));
    }
    if (!step["receiving"].isNull())
        require(step["receiving"].is<bool>() && step["receiving"].as<bool>() == h.store.receiving(),
                where + ": receiving " + std::string(h.store.receiving() ? "true" : "false") + ", expected " +
                    dump(step["receiving"]));
}

void replay(JsonObjectConst testCase) {
    const std::string name = testCase["name"] | "?";
    static Harness h;   // large for the real configuration: never on the stack
    JsonObjectConst configObject = testCase["config"].as<JsonObjectConst>();
    const CCMediaConfig config = config_from(configObject);
    const bool available[2] = {configObject["cover"]["available"] | true, configObject["icon"]["available"] | true};
    h.init_available(config, jpeg_check, available);
    h.activeId = 0;
    size_t index = 0;
    for (JsonObjectConst step : testCase["steps"].as<JsonArrayConst>()) {
        const std::string where = name + " step " + num(static_cast<long long>(index++));
        const std::string what = step["do"] | "";
        if (what == "control") {
            h.activeId = step["id"];
            h.store.cancelUpload();
            ++other_steps;
        } else if (what == "release") {
            h.activeId = 0;
            h.store.cancelUpload();
            ++other_steps;
        } else if (what == "frame") {
            h.store.setFrameKey(CC_MEDIA_COVER, step["artKey"] | "");
            h.store.setFrameKey(CC_MEDIA_ICON, step["iconKey"] | "");
            if (!(step["noAdopt"] | false)) {
                for (uint8_t k = 0; k < 2; ++k) {
                    if (h.store.frameKey(k)[0]) h.store.adopt(k, h.store.frameKey(k), nullptr, nullptr);
                    else h.store.releaseDisplay(k);
                }
            }
            ++other_steps;
        } else if (what == "adopt") {
            const uint8_t k = static_cast<uint8_t>(std::strcmp(step["kind"] | "", "icon") == 0 ? CC_MEDIA_ICON
                                                                                               : CC_MEDIA_COVER);
            h.store.adopt(k, step["key"] | "", nullptr, nullptr);
            ++other_steps;
        } else if (what == "media") {
            const std::string actual = h.media(step["req"]);
            const std::string expected = dump(step["ack"]);
            require(actual == expected, where + ": mediaAck " + actual + ", expected " + expected);
            ++media_steps;
        } else if (what == "check") {
            compare_check(h, step, where);
            ++check_steps;
        } else {
            report(where + ": unknown step " + what);
        }
    }
}

// ---------------------------------------------------------------------------
// Part 2.

CCMediaConfig small_config(uint32_t entries = 3) {
    CCMediaConfig config;
    config.kinds[CC_MEDIA_COVER].entries = entries;
    config.kinds[CC_MEDIA_COVER].slotBytes = 64;
    config.kinds[CC_MEDIA_COVER].minBytes = 1;
    config.kinds[CC_MEDIA_COVER].maxBytes = 64;
    config.kinds[CC_MEDIA_ICON].entries = entries;
    config.kinds[CC_MEDIA_ICON].slotBytes = 16;
    config.kinds[CC_MEDIA_ICON].minBytes = 16;
    config.kinds[CC_MEDIA_ICON].maxBytes = 16;
    config.chunkBytes = 8;
    config.haveKeys = 4;
    config.validateCovers = false;
    return config;
}

std::string upload(Harness& h, const char* kind, const char* key, const std::string& data) {
    char line[256];
    const uint32_t crc = cc_media_crc32(reinterpret_cast<const uint8_t*>(data.data()), data.size());
    std::snprintf(line, sizeof(line), "{\"id\":%u,\"op\":\"begin\",\"kind\":\"%s\",\"key\":\"%s\",\"bytes\":%u,\"crc32\":%u}",
                  static_cast<unsigned>(h.activeId), kind, key, static_cast<unsigned>(data.size()), static_cast<unsigned>(crc));
    std::string last = h.media(line);
    static const char* alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    for (size_t at = 0; at < data.size(); at += 8) {
        const std::string chunk = data.substr(at, 8);
        std::string encoded;
        for (size_t i = 0; i < chunk.size(); i += 3) {
            uint32_t word = static_cast<uint8_t>(chunk[i]) << 16;
            if (i + 1 < chunk.size()) word |= static_cast<uint32_t>(static_cast<uint8_t>(chunk[i + 1])) << 8;
            if (i + 2 < chunk.size()) word |= static_cast<uint8_t>(chunk[i + 2]);
            encoded += alphabet[(word >> 18) & 63];
            encoded += alphabet[(word >> 12) & 63];
            encoded += i + 1 < chunk.size() ? alphabet[(word >> 6) & 63] : '=';
            encoded += i + 2 < chunk.size() ? alphabet[word & 63] : '=';
        }
        std::snprintf(line, sizeof(line), "{\"id\":%u,\"op\":\"data\",\"kind\":\"%s\",\"key\":\"%s\",\"offset\":%u,\"data\":\"%s\"}",
                      static_cast<unsigned>(h.activeId), kind, key, static_cast<unsigned>(at), encoded.c_str());
        last = h.media(line);
    }
    std::snprintf(line, sizeof(line), "{\"id\":%u,\"op\":\"commit\",\"kind\":\"%s\",\"key\":\"%s\"}",
                  static_cast<unsigned>(h.activeId), kind, key);
    return h.media(line);
}

void crc_and_base64() {
    const char* check = "123456789";
    require(cc_media_crc32(reinterpret_cast<const uint8_t*>(check), 9) == 0xCBF43926u, "CRC-32 check value");
    require(cc_media_crc32(nullptr, 0) == 0, "CRC-32 of nothing");
    uint32_t running = 0xFFFFFFFFu;
    running = cc_media_crc_update(running, reinterpret_cast<const uint8_t*>(check), 4);
    running = cc_media_crc_update(running, reinterpret_cast<const uint8_t*>(check) + 4, 5);
    require((running ^ 0xFFFFFFFFu) == 0xCBF43926u, "CRC-32 in two chunks");

    struct Case { const char* text; const char* decoded; size_t size; };
    const Case cases[] = {
        {"QQ==", "A", 1}, {"QR==", "A", 1}, {"QUI=", "AB", 2}, {"QUJD", "ABC", 3}, {"QUJDRA==", "ABCD", 4},
        {"////", "\xFF\xFF\xFF", 3}, {"++++", "\xFB\xEF\xBE", 3},
        {"", nullptr, 0}, {"QQ", nullptr, 0}, {"QUJD=", nullptr, 0}, {"QUJD====", nullptr, 0}, {"A===", nullptr, 0},
        {"====", nullptr, 0}, {"QQ=A", nullptr, 0}, {"QUI=QUI=", nullptr, 0}, {"QU JD", nullptr, 0},
        {"QUJD\n", nullptr, 0}, {"@@@@", nullptr, 0}, {"QUJD-_==", nullptr, 0}, {"QUJDREVGR0hJ", nullptr, 0},
    };
    for (const Case& c : cases) {
        uint8_t out[8] = {};
        const size_t size = cc_media_base64_decode(c.text, std::strlen(c.text), out, 8);
        const bool expected = c.decoded != nullptr;
        require(size == c.size && (!expected || std::memcmp(out, c.decoded, c.size) == 0),
                std::string("base64 \"") + c.text + "\" decoded " + num(static_cast<long long>(size)) + " bytes");
    }
    uint8_t out[4] = {};
    require(cc_media_base64_decode("QUJDRA==", 8, out, 3) == 0, "base64 over capacity");
    require(cc_media_base64_decode("QUJDRA==", 8, out, 4) == 4, "base64 at capacity");
    const char nul[] = {'Q', 'Q', '\0', '='};
    require(cc_media_base64_decode(nul, 4, out, 4) == 0, "base64 with an embedded NUL");

    require(cc_media_key_valid("aZ09_-", 6), "key alphabet");
    require(cc_media_key_valid("abcdefghijklmnopqrstuvwx", 24), "24-character key");
    require(!cc_media_key_valid("abcdefghijklmnopqrstuvwxy", 25), "25-character key");
    require(!cc_media_key_valid("", 0), "empty key");
    require(!cc_media_key_valid("a b", 3) && !cc_media_key_valid("a/b", 3) && !cc_media_key_valid("a.b", 3), "key characters");
    require(!cc_media_key_valid("a\0b", 3), "key with an embedded NUL");

    require(cc_media_is_line("{\"media\":{}}", 12), "media line");
    require(cc_media_is_line(" \t\r{\"media\"", 11), "media line after whitespace");
    require(!cc_media_is_line("{\"mediaAck\":{}}", 15), "mediaAck is not a media line");
    require(!cc_media_is_line("{ \"media\":{}}", 13), "space inside the brace");
    require(!cc_media_is_line("{\"art\":{}}", 10) && !cc_media_is_line("{\"medi", 6), "other lines");
}

void parse_replies() {
    struct Case { std::string line; const char* reply; };
    const std::string pad(200, ' ');
    const Case cases[] = {
        {"{\"media\":{\"id\":7,\"op\":\"data\",\"kind\":\"cover\",\"key\":\"abc_-9\",\"offset\":0,\"data\":\"QQ",
         "{\"op\":\"parse\",\"error\":\"parse\",\"id\":7,\"key\":\"abc_-9\"}"},
        {"{\"media\":{\"id\" : 2147483647 ,\"key\" : \"k\"}", "{\"op\":\"parse\",\"error\":\"parse\",\"id\":2147483647,\"key\":\"k\"}"},
        {"{\"media\":{\"id\":2147483648,\"key\":\"k\"", "{\"op\":\"parse\",\"error\":\"parse\",\"key\":\"k\"}"},
        {"{\"media\":{\"id\":9999999999,\"key\":\"k\"", "{\"op\":\"parse\",\"error\":\"parse\",\"key\":\"k\"}"},
        {"{\"media\":{\"id\":12345678901,\"key\":\"k\"", "{\"op\":\"parse\",\"error\":\"parse\",\"key\":\"k\"}"},
        {"{\"media\":{\"id\":0,\"key\":\"k\"", "{\"op\":\"parse\",\"error\":\"parse\",\"key\":\"k\"}"},
        {"{\"media\":{\"id\":07,\"key\":\"k\"", "{\"op\":\"parse\",\"error\":\"parse\",\"key\":\"k\"}"},
        {"{\"media\":{\"id\":7.5,\"key\":\"k\"", "{\"op\":\"parse\",\"error\":\"parse\",\"key\":\"k\"}"},
        {"{\"media\":{\"id\":-7,\"key\":\"k\"", "{\"op\":\"parse\",\"error\":\"parse\",\"key\":\"k\"}"},
        {"{\"media\":{\"id\":\"7\",\"key\":\"k\"", "{\"op\":\"parse\",\"error\":\"parse\",\"key\":\"k\"}"},
        {"{\"media\":{\"id\":7", "{\"op\":\"parse\",\"error\":\"parse\"}"},          // not delimited
        {"{\"media\":{\"id\":7,\"key\":\"abcdefghijklmnopqrstuvwx\"}",
         "{\"op\":\"parse\",\"error\":\"parse\",\"id\":7,\"key\":\"abcdefghijklmnopqrstuvwx\"}"},
        {"{\"media\":{\"id\":7,\"key\":\"abcdefghijklmnopqrstuvwxy\"}", "{\"op\":\"parse\",\"error\":\"parse\",\"id\":7}"},
        {"{\"media\":{\"id\":7,\"key\":\"\"}", "{\"op\":\"parse\",\"error\":\"parse\",\"id\":7}"},
        {"{\"media\":{\"id\":7,\"key\":\"a b\"}", "{\"op\":\"parse\",\"error\":\"parse\",\"id\":7}"},
        {"{\"media\":{\"id\":7,\"key\":\"abc", "{\"op\":\"parse\",\"error\":\"parse\",\"id\":7}"},   // unterminated
        {"{\"media\":{\"key\":5,\"id\":8}", "{\"op\":\"parse\",\"error\":\"parse\",\"id\":8}"},
        {"{\"media\":" + pad + "\"id\":7,\"key\":\"k\"}", "{\"op\":\"parse\",\"error\":\"parse\"}"},   // beyond 192 bytes
        {"{\"media\":{\"id\":7," + std::string(150, ' ') + "\"key\":\"abcdefghijkl\"",
         "{\"op\":\"parse\",\"error\":\"parse\",\"id\":7,\"key\":\"abcdefghijkl\"}"},
        {"{\"media\":{\"id\":7," + std::string(166, ' ') + "\"key\":\"abcdefghijkl\"",
         "{\"op\":\"parse\",\"error\":\"parse\",\"id\":7}"},          // the key runs past byte 192
        // The 192-byte bound itself (ARTWORK2.md 4.3 step 1): the key's closing quote at byte
        // index 191 is inside the scan, at 192 it is not; likewise the id's delimiter.
        {"{\"media\":{\"id\":7," + std::string(155, ' ') + "\"key\":\"abcdefghijkl\"",
         "{\"op\":\"parse\",\"error\":\"parse\",\"id\":7,\"key\":\"abcdefghijkl\"}"},   // quote at 191
        {"{\"media\":{\"id\":7," + std::string(156, ' ') + "\"key\":\"abcdefghijkl\"",
         "{\"op\":\"parse\",\"error\":\"parse\",\"id\":7}"},                            // quote at 192
        {"{\"media\":{" + std::string(175, ' ') + "\"id\":7,\"key\":\"k\"}",
         "{\"op\":\"parse\",\"error\":\"parse\",\"id\":7}"},                            // ',' at 191
        {"{\"media\":{" + std::string(176, ' ') + "\"id\":7,\"key\":\"k\"}",
         "{\"op\":\"parse\",\"error\":\"parse\"}"},                                     // ',' at 192
        {"", "{\"op\":\"parse\",\"error\":\"parse\"}"},
    };
    for (const Case& c : cases) {
        JsonDocument out;
        char key[CC_MEDIA_KEY_CHARS + 1];
        cc_media_parse_ack(c.line.data(), c.line.size(), out["mediaAck"].to<JsonObject>(), key);
        const std::string actual = dump(out["mediaAck"]);
        require(actual == c.reply, "parse reply for " + c.line.substr(0, 60) + "...: " + actual + ", expected " + c.reply);
    }
}

// Feeds `bytes` at time `now`; returns one character per byte ('.' none, 'C' complete, 'O'
// oversize, 'D' discarded) and appends each completed line (and each oversize prefix, marked
// with a leading '!') to `lines`.
std::string feed(CCLineAssembler& assembler, const std::string& bytes, uint32_t now, std::vector<std::string>& lines) {
    std::string events;
    for (char c : bytes) {
        const CCLineEvent event = assembler.feed(c, now);
        if (event == CC_COM_LINE_COMPLETE) {
            require(assembler.text()[assembler.length()] == 0, "com: a complete line is NUL-terminated");
            lines.push_back(std::string(assembler.text(), assembler.length()));
        } else if (event == CC_COM_LINE_OVERSIZE) {
            lines.push_back("!" + std::string(assembler.text(), assembler.length()));
        }
        events += event == CC_COM_LINE_COMPLETE ? 'C' : event == CC_COM_LINE_OVERSIZE ? 'O'
                  : event == CC_COM_LINE_DISCARDED ? 'D' : '.';
    }
    return events;
}

// The COM thread's line transport (cc_media_store.h, run by com_thread.cpp): which reply a bad
// line gets, line assembly with the oversize rule (exactly one reply per oversize line, no
// fragment glued onto the next line) and the idle sleep rule of ARTWORK2.md section 3.
void com_transport() {
    struct Pick { const char* line; CCBadLineReply reply; };
    const Pick picks[] = {
        {"{\"media\":{\"id\":7,\"op\":\"data\"", CC_BAD_LINE_MEDIA}, {" \t\r{\"media\":", CC_BAD_LINE_MEDIA},
        {"{\"art\":{\"id\":7,\"op\":\"data\"", CC_BAD_LINE_ART}, {"\t {\"art\"", CC_BAD_LINE_ART},
        {"{\"art\":{\"id\":1},\"media\":{\"id\":1}", CC_BAD_LINE_ART},     // art first, as in cc5.2
        {"{\"mediaAck\":{}", CC_BAD_LINE_ERROR}, {"{\"artAck\":{}", CC_BAD_LINE_ERROR},
        {"{\"artwork\":1", CC_BAD_LINE_ERROR}, {"{ \"media\":{}", CC_BAD_LINE_ERROR},
        {"{\"frame\":{\"media\":1", CC_BAD_LINE_ERROR}, {"{\"medi", CC_BAD_LINE_ERROR}, {"{\"ar", CC_BAD_LINE_ERROR},
        {"\n{\"media\":", CC_BAD_LINE_ERROR}, {"", CC_BAD_LINE_ERROR},
    };
    for (const Pick& p : picks)
        require(cc_bad_line_reply(p.line, std::strlen(p.line)) == p.reply,
                std::string("com: bad-line reply for \"") + p.line + "\"");
    require(cc_art_is_line("{\"art\"", 6) && !cc_art_is_line("{\"art", 5), "com: art line prefix");

    // Idle sleep (ARTWORK2.md section 3): 1 tick while any condition holds, else 10.
    for (int bits = 0; bits < 16; ++bits) {
        const bool partial = (bits & 1) != 0, queued = (bits & 2) != 0, receiving = (bits & 4) != 0,
                   handled = (bits & 8) != 0;
        const uint32_t since[] = {0, 1, 19, 20, 21, 1000, 0xFFFFFFFFu};
        for (uint32_t ms : since) {
            const uint32_t expected = partial || queued || receiving || (handled && ms < 20) ? 1u : 10u;
            require(cc_com_idle_ticks(partial, queued, receiving, handled, ms) == expected,
                    "com: idle ticks for partial " + num(partial) + ", queued " + num(queued) + ", receiving " +
                        num(receiving) + ", handled " + num(handled) + " " + num(ms) + " ms ago");
        }
    }
    require(CC_COM_RECENT_LINE_MS == 20 && CC_COM_BUSY_TICKS == 1 && CC_COM_IDLE_TICKS == 10, "com: idle constants");

    // Line assembly on a small buffer (capacity 8).
    char small[9];
    CCLineAssembler a(small, 8);
    std::vector<std::string> lines;
    require(!a.partial(), "com: nothing pending at start");
    require(feed(a, "abc\n", 100, lines) == "...C" && lines.back() == "abc" && !a.partial(), "com: a line");
    require(feed(a, "de", 100, lines) == ".." && a.partial(), "com: a partial line is pending");
    require(feed(a, "\n", 100, lines) == "C" && lines.back() == "de", "com: the next line starts empty");
    require(feed(a, "\n", 100, lines) == "C" && lines.back().empty(), "com: an empty line");
    require(feed(a, "12345678\n", 100, lines) == "........C" && lines.back() == "12345678", "com: a line at capacity");
    require(feed(a, "ab\r\n", 100, lines) == "...C" && lines.back() == "ab\r", "com: a CR stays in the line (JSON whitespace)");
    lines.clear();
    require(feed(a, "123456789abc\n", 100, lines) == "........O...D", "com: one oversize event, then the discarded newline");
    require(lines.size() == 1 && lines[0] == "!12345678", "com: the oversize reply sees the first 8 bytes, nothing completes");
    require(!a.partial() && feed(a, "x\n", 100, lines) == ".C" && lines.back() == "x",
            "com: after an oversize line the next line is whole");
    lines.clear();
    require(feed(a, "123456789", 200, lines) == "........O" && a.partial(), "com: an oversize line being dropped is pending");
    a.expire(2199, 2000);
    require(a.partial(), "com: 1999 ms after the last byte the line is kept");
    a.expire(2200, 2000);
    require(!a.partial(), "com: 2000 ms after the last byte the line is dropped");
    require(feed(a, "ok\n", 3000, lines) == "..C" && lines.back() == "ok", "com: after an expiry the next line is whole");
    require(feed(a, "abc", 0xFFFFFF00u, lines) == "..." && a.partial(), "com: a partial line before the clock wraps");
    a.expire(0x000006CFu, 2000);
    require(a.partial(), "com: expiry across the clock wrap (1999 ms)");
    a.expire(0x000006D0u, 2000);
    require(!a.partial(), "com: expiry across the clock wrap (2000 ms)");
    require(feed(a, "de\n", 0x00000700u, lines) == "..C" && lines.back() == "de", "com: no fragment glued after an expiry");
    a.expire(0x7FFFFFFFu, 2000);
    require(!a.partial() && a.length() == 2 && std::string(a.text()) == "de", "com: expiry never touches a handled line");

    // The COM thread's capacity: a 5000-byte media line gets exactly one oversize event, whose
    // prefix is answered as media with the id and key of its first 192 bytes.
    static char buffer[4096 + 1];
    CCLineAssembler com(buffer, 4096);
    std::string big = "{\"media\":{\"id\":9,\"op\":\"data\",\"kind\":\"cover\",\"key\":\"big\",\"offset\":0,\"data\":\"";
    big += std::string(5000 - big.size() - 3, 'A') + "\"}}";
    lines.clear();
    const std::string events = feed(com, big + "\n", 0, lines);
    require(events.size() == 5001 && std::count(events.begin(), events.end(), 'O') == 1 &&
                std::count(events.begin(), events.end(), 'D') == 1 && events.find('C') == std::string::npos &&
                events[4096] == 'O' && events[5000] == 'D',
            "com: a 5000-byte line: one oversize event at byte 4097, its newline discarded, nothing completes");
    require(lines.size() == 1 && lines[0].size() == 4097 &&
                cc_bad_line_reply(lines[0].data() + 1, lines[0].size() - 1) == CC_BAD_LINE_MEDIA,
            "com: the oversize prefix is 4096 bytes of a media line");
    JsonDocument out;
    char key[CC_MEDIA_KEY_CHARS + 1];
    cc_media_parse_ack(lines[0].data() + 1, lines[0].size() - 1, out["mediaAck"].to<JsonObject>(), key);
    require(dump(out["mediaAck"]) == "{\"op\":\"parse\",\"error\":\"parse\",\"id\":9,\"key\":\"big\"}",
            "com: the oversize media line's parse reply: " + dump(out["mediaAck"]));
    require(feed(com, "{\"media\":{}}\n", 0, lines).back() == 'C' && lines.back() == "{\"media\":{}}",
            "com: the line after an oversize one is whole");
}

void availability() {
    Harness h;
    h.init(small_config(), accept_all, false);   // cover memory missing
    h.activeId = 3;
    require(!h.store.available(CC_MEDIA_COVER) && h.store.available(CC_MEDIA_ICON), "per-kind availability");
    require(h.media("{\"id\":9,\"op\":\"have\",\"kind\":\"cover\",\"keys\":[\"a\"]}") ==
                "{\"id\":9,\"op\":\"have\",\"kind\":\"cover\",\"error\":\"Media unavailable\"}",
            "an unavailable store answers before the control check");
    require(h.media("{\"id\":3,\"op\":\"begin\",\"kind\":\"cover\",\"key\":\"a\",\"bytes\":1,\"crc32\":0}") ==
                "{\"id\":3,\"op\":\"begin\",\"kind\":\"cover\",\"key\":\"a\",\"offset\":0,\"error\":\"Media unavailable\"}",
            "unavailable begin");
    require(h.media("{\"id\":3,\"op\":\"x\",\"kind\":\"cover\"}") ==
                "{\"id\":3,\"kind\":\"cover\",\"offset\":0,\"error\":\"Unknown media operation\"}",
            "the operation check comes first");
    require(h.media("{\"id\":3,\"op\":\"have\",\"kind\":\"icon\",\"keys\":[\"a\"]}") ==
                "{\"id\":3,\"op\":\"have\",\"kind\":\"icon\",\"have\":[false]}",
            "the other kind still works");
    const uint8_t* data = nullptr;
    require(!h.store.adopt(CC_MEDIA_COVER, "a", &data, nullptr) && h.store.displayed(CC_MEDIA_COVER) == -1,
            "no adoption from an unavailable store");
    h.init(small_config(), accept_all, true, false);   // no scratch buffer: nothing available
    require(!h.store.available(CC_MEDIA_COVER) && !h.store.available(CC_MEDIA_ICON), "no scratch, no store");
}

void pins_and_adoption() {
    // entries 1: S = 2, so the displayed slot and the frame key's slot can pin everything.
    Harness h;
    h.init(small_config(1), accept_all);
    h.activeId = 4;
    require(upload(h, "cover", "a", "first cover") == "{\"id\":4,\"op\":\"commit\",\"kind\":\"cover\",\"key\":\"a\",\"offset\":11}",
            "commit a");
    require(upload(h, "cover", "b", "second") == "{\"id\":4,\"op\":\"commit\",\"kind\":\"cover\",\"key\":\"b\",\"offset\":6}",
            "commit b");
    const uint8_t* data = nullptr;
    uint32_t bytes = 0;
    require(h.store.adopt(CC_MEDIA_COVER, "a", &data, &bytes) && h.store.displayed(CC_MEDIA_COVER) == 0,
            "adopt a: displayed 0");
    require(data == h.memory[0].data() && bytes == 11 && std::memcmp(data, "first cover", 11) == 0,
            "the adopted pointer is the slot's own bytes");
    const uint32_t stamp = h.store.slot(CC_MEDIA_COVER, 0).stamp;
    require(h.store.adopt(CC_MEDIA_COVER, "a", &data, &bytes) && h.store.slot(CC_MEDIA_COVER, 0).stamp == stamp,
            "adopting the displayed slot again does not touch it");
    h.store.setFrameKey(CC_MEDIA_COVER, "b");
    const uint32_t evictions = h.store.evictions(), errors = h.store.errors();
    require(h.media("{\"id\":4,\"op\":\"begin\",\"kind\":\"icon\",\"key\":\"n\",\"bytes\":16,\"crc32\":0}") ==
                "{\"id\":4,\"op\":\"begin\",\"kind\":\"icon\",\"key\":\"n\",\"offset\":0}",
            "an icon upload in progress");
    require(h.store.receiving(), "the icon upload is receiving");
    require(h.media("{\"id\":4,\"op\":\"begin\",\"kind\":\"cover\",\"key\":\"c\",\"bytes\":3,\"crc32\":0}") ==
                "{\"id\":4,\"op\":\"begin\",\"kind\":\"cover\",\"key\":\"c\",\"offset\":0,\"error\":\"Media unavailable\"}",
            "every slot pinned: Media unavailable");
    require(h.store.evictions() == evictions && h.store.errors() == errors + 1 && h.store.slot(CC_MEDIA_COVER, 0).valid &&
                h.store.slot(CC_MEDIA_COVER, 1).valid,
            "every slot pinned: no slot changes");
    require(!h.store.uploadActive() && !h.store.receiving(),
            "every slot pinned: the miss still cancelled the upload in progress first (ARTWORK2.md 4.4)");
    h.store.setFrameKey(CC_MEDIA_COVER, "k234567890123456789012345");   // too long: pins nothing
    require(h.store.frameKey(CC_MEDIA_COVER)[0] == 0, "a 25-character frame key pins nothing");
    h.store.setFrameKey(CC_MEDIA_COVER, "k2345678901234567890123456789012345678901234567890123456789012345");
    require(h.store.frameKey(CC_MEDIA_COVER)[0] == 0, "a v1-length artKey pins nothing");
    h.store.setFrameKey(CC_MEDIA_COVER, "b");
    require(std::strcmp(h.store.frameKey(CC_MEDIA_COVER), "b") == 0, "frame key kept");
    h.store.releaseDisplay(CC_MEDIA_COVER);
    require(h.store.displayed(CC_MEDIA_COVER) == -1, "release display");
    require(h.media("{\"id\":4,\"op\":\"begin\",\"kind\":\"cover\",\"key\":\"c\",\"bytes\":3,\"crc32\":0}") ==
                "{\"id\":4,\"op\":\"begin\",\"kind\":\"cover\",\"key\":\"c\",\"offset\":0}",
            "the unpinned slot is the victim");
    require(!h.store.slot(CC_MEDIA_COVER, 0).valid && h.store.slot(CC_MEDIA_COVER, 1).valid &&
                h.store.evictions() == evictions + 1 && std::strcmp(h.store.slot(CC_MEDIA_COVER, 0).key, "a") == 0,
            "eviction at begin keeps the key, counts once");
    require(h.store.receiving(), "a miss upload is receiving");
    require(!h.store.adopt(CC_MEDIA_COVER, "a", &data, &bytes) && h.store.displayed(CC_MEDIA_COVER) == -1,
            "an evicted key is not adopted");
    h.store.cancelUpload();
    require(!h.store.receiving() && !h.store.uploadActive(), "cancel ends the upload");
    require(h.media("{\"id\":4,\"op\":\"begin\",\"kind\":\"cover\",\"key\":\"b\",\"bytes\":6,\"crc32\":" +
                    std::to_string(cc_media_crc32(reinterpret_cast<const uint8_t*>("second"), 6)) + "}") ==
                "{\"id\":4,\"op\":\"begin\",\"kind\":\"cover\",\"key\":\"b\",\"offset\":6}",
            "begin hit");
    require(h.store.uploadActive() && !h.store.receiving(), "a hit context is not receiving");
    const uint32_t version = h.store.version(), commits = h.store.commits();
    require(h.media("{\"id\":4,\"op\":\"commit\",\"kind\":\"cover\",\"key\":\"b\"}") ==
                "{\"id\":4,\"op\":\"commit\",\"kind\":\"cover\",\"key\":\"b\",\"offset\":6}",
            "hit commit");
    require(h.store.version() == version && h.store.commits() == commits + 1, "a hit commit counts but bumps no version");
    require(upload(h, "icon", "i", std::string(16, 'x')) ==
                "{\"id\":4,\"op\":\"commit\",\"kind\":\"icon\",\"key\":\"i\",\"offset\":16}",
            "icon commit");
    require(h.store.version() == version + 1, "a miss commit bumps the version");
    require(h.store.adopt(CC_MEDIA_ICON, "i", &data, &bytes) && data == h.memory[1].data() && bytes == 16,
            "icon adoption");
    require(!h.store.adopt(CC_MEDIA_ICON, "", &data, &bytes) && h.store.displayed(CC_MEDIA_ICON) == -1,
            "an empty key releases the display");
}

void capability(const char* expected) {
    JsonDocument out;
    cc_media_capability_fields(out["artwork2"].to<JsonObject>(), true, CC_MEDIA_RX_BYTES);
    const std::string actual = dump(out["artwork2"]);
    require(actual == expected, "artwork2 capability " + actual + ", expected " + expected);
    JsonDocument off;
    cc_media_capability_fields(off["artwork2"].to<JsonObject>(), false, 256);
    const std::string degraded = dump(off["artwork2"]);
    require(degraded.find("\"available\":false,") != std::string::npos &&
                degraded.find("\"rxBytes\":256,") != std::string::npos,
            "artwork2 capability without stores and with the default queue: " + degraded);
}

void device_config() {
    const CCMediaConfig c = cc_media_device_config();
    require(c.kinds[CC_MEDIA_COVER].entries == 24 && c.kinds[CC_MEDIA_COVER].slotBytes == 32768 &&
                c.kinds[CC_MEDIA_COVER].minBytes == 1 && c.kinds[CC_MEDIA_COVER].maxBytes == 32768,
            "device cover store: 24 entries (25 slots) of 32768 B, 1..32768 B");
    require(c.kinds[CC_MEDIA_ICON].entries == 48 && c.kinds[CC_MEDIA_ICON].slotBytes == 2048 &&
                c.kinds[CC_MEDIA_ICON].minBytes == 2048 && c.kinds[CC_MEDIA_ICON].maxBytes == 2048,
            "device icon store: 48 entries (49 slots) of exactly 2048 B");
    require(c.chunkBytes == 2048 && c.haveKeys == 24 && c.validateCovers, "device chunk, have and decode check");
    require(CC_MEDIA_RX_BYTES == 8192 && CC_MEDIA_COVER_SIZE == 240 && CC_MEDIA_ICON_SIZE == 32 &&
                CC_MEDIA_ICON_BYTES == CC_MEDIA_ICON_SIZE * CC_MEDIA_ICON_SIZE * 2 && CC_MEDIA_VERSION == 1 &&
                CC_MEDIA_KEY_CHARS == 24,
            "capability constants");
    // A full device store on the host: 24 covers and 48 icons plus the staging slots.
    static Harness h;
    h.init(c, accept_all);
    h.activeId = 1;
    for (uint32_t i = 0; i < 25; ++i) {
        const std::string key = "c" + std::to_string(i);
        upload(h, "cover", key.c_str(), std::string(1 + i, static_cast<char>('a' + i)));
    }
    for (uint32_t i = 0; i < 25; ++i)
        require(h.store.slot(CC_MEDIA_COVER, i).valid, "device cover slot " + num(i) + " committed");
    upload(h, "cover", "c25", "z");
    require(h.store.slot(CC_MEDIA_COVER, 0).valid && std::strcmp(h.store.slot(CC_MEDIA_COVER, 0).key, "c25") == 0,
            "the 26th cover evicts the least recently used (slot 0)");
    require(h.store.evictions() == 1 && h.store.commits() == 26, "device store counters");
}

std::string read_file(const char* path) {
    std::ifstream file(path, std::ios::binary);
    std::stringstream text;
    text << file.rdbuf();
    return text.str();
}

// media_tests.py's reference Model decides the fixture's "Media decode failed" acks with a
// marker pre-scan (jpeg_valid) that is only right for payloads the ROM decoder's prepare would
// not reject on its tables. Every cover payload it judged while building the fixture is listed
// here ("1 path" or "0 path" per line) and must get the same verdict from cc_jpeg_validate, so
// a misjudged payload is named here, before the replay reports it as a store mismatch.
void model_verdicts(const char* manifest) {
    std::ifstream file(manifest);
    std::string line;
    long long listed = 0;
    while (std::getline(file, line)) {
        if (line.size() < 3) continue;
        const bool expected = line[0] == '1';
        const std::string path = line.substr(2);
        const std::string data = read_file(path.c_str());
        uint16_t w = 0, h = 0;
        const bool actual = cc_jpeg_validate(reinterpret_cast<const uint8_t*>(data.data()),
                                             static_cast<uint32_t>(data.size()), &w, &h);
        require(actual == expected, "the reference Model's jpeg_valid() says " + std::string(expected ? "valid" : "invalid") +
                                        " but cc_jpeg_validate says " + (actual ? "valid" : "invalid") + " for " + path +
                                        ": build fixture covers from gray_jpeg() or host-encoder output");
        ++listed;
    }
    require(listed > 0, "model verdicts: " + std::string(manifest) + " lists no cover payload");
}
}  // namespace

#if defined(CC_MEDIA_WIRING)
// ---------------------------------------------------------------------------
// Part 3: the firmware functions control_center.cpp and cc_media.cpp link against, as host
// stubs (declared by the real src/ headers or by media_tests.py's stub headers).

namespace wiring_state {
uint32_t now = 0;                                  // millis()
std::vector<std::string> sent;                     // every serial reply line, in order
uint32_t rxInternalBytes = CC_MEDIA_RX_BYTES;      // cc_boot_rx_queue_internal_bytes()
HapticProfile regular;                             // the "Regular" preset
}  // namespace wiring_state

uint32_t millis() { return wiring_state::now; }
SemaphoreHandle_t xSemaphoreCreateMutex() {
    static int mutex = 0;
    return &mutex;
}
int xSemaphoreTake(SemaphoreHandle_t, uint32_t) { return 1; }
int xSemaphoreGive(SemaphoreHandle_t) { return 1; }
FocThread foc_thread;
HapticProfileManager& HapticProfileManager::getInstance() {
    static HapticProfileManager manager;
    return manager;
}
HapticProfile* HapticProfileManager::operator[](String name) {
    return std::strcmp(name.c_str(), "Regular") == 0 ? &wiring_state::regular : nullptr;
}
void cc_send_json(const JsonDocument& doc) {
    std::string text;
    serializeJson(doc, text);
    wiring_state::sent.push_back(text);
}
void cc_send_line(const char* text) { wiring_state::sent.push_back(text); }
uint32_t cc_tx_stalls() { return 0; }
uint32_t cc_tx_dropped_bytes() { return 0; }
bool cc_art_available() { return true; }
void cc_art_command(JsonVariant, uint32_t, const char*) { wiring_state::sent.push_back("{\"artAck\":\"stub\"}"); }
uint32_t cc_art_version() { return 0; }
void cc_crumb_com(uint8_t, uint8_t, uint32_t) {}
void cc_diag_boot(JsonObject) {}
void cc_diag_live(JsonObject) {}
void cc_led_diag(JsonObject) {}
void cc_diag_media(JsonObject) {}
// PRESENTATION_V5 12.3: the real serialisation (cc_diag.h) on a stand-in of cc_display.h's
// CCLcdPerf (the wiring build has no LVGL), in place of cc_diag.cpp's cc_lcd_perf_read() copy.
namespace wiring_state {
struct LcdPerf {
    uint32_t lcdFps, lcdFpsAnimMin, lcdRefrUsMax, lcdRefrUsAvg, lcdRenderUsMax, lcdFlushUs, lcdPxPerRefr,
        lcdFullRefrs, lcdLateRefrs, lcdMaxGapMs, lcdBusyPct, core0IdlePct, lcdSpiHz, lcdDma, lcdPeriodMs, artAsync,
        artDecodeRequests, artDecodeAborts, artDecodeStale, stackArtDec, lcdMosiSig, buildBinary;
};
LcdPerf lcdPerf = {};
uint32_t lcdPipelineReads = 0;
}  // namespace wiring_state
void cc_diag_lcd_pipeline(JsonObject d) {
    ++wiring_state::lcdPipelineReads;
    cc_diag_lcd_perf_fields(d, wiring_state::lcdPerf);
}
uint32_t cc_boot_rx_queue_internal_bytes() { return wiring_state::rxInternalBytes; }
void cc_live_foc() {}

namespace {
std::string frameText, coverJpeg;   // argv[3] (a valid windows frame), argv[4] (a valid cover)
long long wiringChecks = 0;

std::vector<std::string> run(const std::string& line) {
    wiring_state::sent.clear();
    JsonDocument doc;
    const DeserializationError error = deserializeJson(doc, line);
    require(!error, "wiring: the test line is JSON: " + line.substr(0, 80));
    require(cc_handle_command(doc), "wiring: cc_handle_command handled " + line.substr(0, 80));
    return wiring_state::sent;
}

// The single reply to `line` ("" and a failure unless there is exactly one).
std::string one(const std::string& line) {
    const std::vector<std::string> replies = run(line);
    require(replies.size() == 1, "wiring: exactly one reply to " + line.substr(0, 90) + ", got " +
                                     num(static_cast<long long>(replies.size())) +
                                     (replies.empty() ? std::string() : ": " + replies[0]));
    return replies.size() == 1 ? replies[0] : std::string();
}

void expect(const std::string& line, const std::string& reply, const std::string& what) {
    const std::string actual = one(line);
    require(actual == reply, "wiring: " + what + ": " + actual + ", expected " + reply);
}

void silent(const std::string& line, const std::string& what) {
    const std::vector<std::string> replies = run(line);
    require(replies.empty(), "wiring: " + what + ": no reply expected, got " + (replies.empty() ? "" : replies[0]));
}

std::string frame_object(uint32_t id, const char* art, const char* icon) {
    JsonDocument frame;
    deserializeJson(frame, frameText);
    frame["id"] = id;
    frame["artKey"] = art;
    frame["iconKey"] = icon;
    std::string text;
    serializeJson(frame, text);
    return text;
}
std::string frame_line(uint32_t id, const char* art, const char* icon) {
    return "{\"frame\":" + frame_object(id, art, icon) + "}";
}
std::string control_object(uint32_t id, const char* art, const char* icon, const char* profile = "Regular",
                           const char* extra = "") {
    return "{\"id\":" + num(id) + ",\"min\":0,\"max\":10,\"position\":0,\"windowsButton\":2,\"profile\":\"" +
           profile + "\"" + extra + ",\"frame\":" + frame_object(id, art, icon) + "}";
}
std::string control_line(uint32_t id, const char* art, const char* icon, const char* profile = "Regular",
                         const char* extra = "") {
    return "{\"control\":" + control_object(id, art, icon, profile, extra) + "}";
}

std::string base64(const std::string& data) {
    static const char* alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string encoded;
    for (size_t i = 0; i < data.size(); i += 3) {
        uint32_t word = static_cast<uint32_t>(static_cast<uint8_t>(data[i])) << 16;
        if (i + 1 < data.size()) word |= static_cast<uint32_t>(static_cast<uint8_t>(data[i + 1])) << 8;
        if (i + 2 < data.size()) word |= static_cast<uint8_t>(data[i + 2]);
        encoded += alphabet[(word >> 18) & 63];
        encoded += alphabet[(word >> 12) & 63];
        encoded += i + 1 < data.size() ? alphabet[(word >> 6) & 63] : '=';
        encoded += i + 2 < data.size() ? alphabet[word & 63] : '=';
    }
    return encoded;
}

std::string head(uint32_t id, const char* op, const char* kind) {
    return "{\"id\":" + num(id) + ",\"op\":\"" + op + "\",\"kind\":\"" + kind + "\"";
}
std::string media(const std::string& body) { return "{\"media\":" + body + "}"; }
std::string begin_body(uint32_t id, const char* kind, const std::string& key, const std::string& data) {
    const uint32_t crc = cc_media_crc32(reinterpret_cast<const uint8_t*>(data.data()), data.size());
    return head(id, "begin", kind) + ",\"key\":\"" + key + "\",\"bytes\":" + num(static_cast<long long>(data.size())) +
           ",\"crc32\":" + num(crc) + "}";
}
std::string data_body(uint32_t id, const char* kind, const std::string& key, size_t offset, const std::string& chunk) {
    return head(id, "data", kind) + ",\"key\":\"" + key + "\",\"offset\":" + num(static_cast<long long>(offset)) +
           ",\"data\":\"" + base64(chunk) + "\"}";
}
std::string commit_body(uint32_t id, const char* kind, const std::string& key) {
    return head(id, "commit", kind) + ",\"key\":\"" + key + "\"}";
}
std::string have_body(uint32_t id, const char* kind, const std::vector<std::string>& keys) {
    std::string list;
    for (const std::string& key : keys) list += (list.empty() ? "\"" : ",\"") + key + "\"";
    return head(id, "have", kind) + ",\"keys\":[" + list + "]}";
}
std::string ack(uint32_t id, const char* op, const char* kind, const std::string& key, size_t offset,
                const char* error = nullptr) {
    return "{\"mediaAck\":" + head(id, op, kind) + ",\"key\":\"" + key + "\",\"offset\":" +
           num(static_cast<long long>(offset)) + (error ? std::string(",\"error\":\"") + error + "\"" : std::string()) +
           "}}";
}
std::string have_ack(uint32_t id, const char* kind, const std::string& result, const char* error = nullptr) {
    return "{\"mediaAck\":" + head(id, "have", kind) +
           (error ? std::string(",\"error\":\"") + error + "\"" : ",\"have\":" + result) + "}}";
}

void upload(uint32_t id, const char* kind, const std::string& key, const std::string& data) {
    expect(media(begin_body(id, kind, key, data)), ack(id, "begin", kind, key, 0), "begin " + key);
    for (size_t at = 0; at < data.size(); at += CC_MEDIA_CHUNK_BYTES) {
        const std::string chunk = data.substr(at, CC_MEDIA_CHUNK_BYTES);
        expect(media(data_body(id, kind, key, at, chunk)), ack(id, "data", kind, key, at + chunk.size()), "data " + key);
    }
    expect(media(commit_body(id, kind, key)), ack(id, "commit", kind, key, data.size()), "commit " + key);
}
void have(uint32_t id, const char* kind, const std::vector<std::string>& keys, const std::string& result,
          const std::string& what) {
    expect(media(have_body(id, kind, keys)), have_ack(id, kind, result), what);
}
std::string icon_payload(int n) {
    std::string data(CC_MEDIA_ICON_BYTES, '\0');
    for (size_t i = 0; i < data.size(); ++i) data[i] = static_cast<char>((n * 31 + static_cast<int>(i) * 7) & 0xFF);
    return data;
}
std::string key_of(const char* prefix, int n) { return prefix + num(n); }

void service_expect(const std::string& reply, const std::string& what) {
    wiring_state::sent.clear();
    cc_service();
    require(wiring_state::sent.size() == 1 && wiring_state::sent[0] == reply,
            "wiring: " + what + ": " + (wiring_state::sent.empty() ? std::string("no reply") : wiring_state::sent[0]) +
                ", expected " + reply);
}

// Mirrors com_thread.cpp's COM loop over raw bytes: the same CCLineAssembler (capacity 4096)
// and cc_bad_line_reply, the real cc_handle_command and cc_media_parse_reply. ComThread's own
// art parse reply and bare errors are recorded as "art-parse" and {"error":...}. Returns every
// reply sent, in order.
std::vector<std::string> com_route(const std::string& bytes) {
    static char buffer[4096 + 1];
    static CCLineAssembler assembler(buffer, 4096);
    wiring_state::sent.clear();
    for (char c : bytes) {
        const CCLineEvent event = assembler.feed(c, wiring_state::now);
        const bool oversize = event == CC_COM_LINE_OVERSIZE;
        if (event != CC_COM_LINE_COMPLETE && !oversize) continue;
        const char* line = assembler.text();
        const size_t length = assembler.length();
        const char* error = "Command too large";
        if (!oversize) {
            JsonDocument doc;
            if (!deserializeJson(doc, line, length)) {
                cc_handle_command(doc);   // a native command would follow in com_thread.cpp
                continue;
            }
            error = "JSON parse error";
        }
        switch (cc_bad_line_reply(line, length)) {
            case CC_BAD_LINE_ART: wiring_state::sent.push_back("art-parse"); break;
            case CC_BAD_LINE_MEDIA: cc_media_parse_reply(line, length); break;
            default: wiring_state::sent.push_back(std::string("{\"error\":\"") + error + "\"}"); break;
        }
    }
    return wiring_state::sent;
}

// FW-BUG-029: a recalibration owns the motor for 5-6 s. From {"recalibrate":true} (com_thread.cpp calls
// cc_cal_requested() after cc_cal_request()) until the FOC task reports the run finished, and while it reports
// running or saving, a control is refused and the session stays idle (phase 0): it never sits in "entering" while
// the motor sweeps, nor loses its lease before it is applied.
void test_control_refused_while_calibrating(CCControl& request) {
    cc_haptic_detail::Shared& cal = cc_haptic_detail::shared();
    require(!cc_claimed(), "wiring FW-BUG-029: starts idle");
    wiring_state::now = 400000;
    cc_cal_request(false);
    cc_cal_requested();                                  // the FOC task has not started the run yet
    expect(control_line(10, "cv0", ""), "{\"error\":\"Recalibrating; wait for calibrated\"}",
           "FW-BUG-029: a control between the request and the run is refused");
    cal.calState = CC_CAL_RUNNING;
    wiring_state::now = 403000;
    expect(control_line(10, "cv0", ""), "{\"error\":\"Recalibrating; wait for calibrated\"}",
           "FW-BUG-029: a control during the motor alignment is refused");
    require(!cc_claimed() && !cc_take_request(request), "wiring FW-BUG-029: phase stays 0, nothing requested");
    cal.calState = CC_CAL_SAVING;
    expect(control_line(10, "cv0", ""), "{\"error\":\"Recalibrating; wait for calibrated\"}",
           "FW-BUG-029: a control while the calibration is saved is refused");
    cal.calState = CC_CAL_IDLE;                          // FocThread::recalibrate() ends: outcome, result, idle
    cal.calOutcome = CC_CAL_OK;
    cal.calResult = cal.calResult + 1u;
    wiring_state::now = 406000;
    silent(control_line(10, "cv0", ""), "FW-BUG-029: once calibrated, a control is accepted");
    require(cc_take_request(request) && request.id == 10 && !request.release && cc_claimed(),
            "wiring FW-BUG-029: control 10 entering after the run");
    silent("{\"release\":true}", "FW-BUG-029: release control 10");
    require(cc_take_request(request) && request.release, "wiring FW-BUG-029: release requested");
    service_expect("{\"released\":true}", "FW-BUG-029: release completes");
    require(!cc_claimed(), "wiring FW-BUG-029: idle again");
}

void wiring_tests(const std::string& capability) {
    const long long before = checks;
    HapticProfile& preset = wiring_state::regular;   // what control_center.cpp requires of a preset
    preset.hmi_config.knob.num = 1;
    DetentProfile& haptic = preset.hmi_config.knob.values[0].haptic;
    std::memset(&haptic, 0, sizeof(haptic));
    haptic.mode = REGULAR;
    haptic.detent_count = 10;
    haptic.output_ramp = 1.0f;
    cc_media_init();
    require(cc_media_available(CC_MEDIA_COVER) && cc_media_available(CC_MEDIA_ICON), "wiring: both stores allocated");
    CCControl request;

    // 1. The capability object in the full reply: after artwork, before diag, byte for byte.
    const std::string caps = one("{\"capabilities\":\"?\"}");
    const size_t art = caps.find("\"artwork\":{"), art2 = caps.find("\"artwork2\":{");
    require(art != std::string::npos && art2 != std::string::npos && art < art2 &&
                caps.find("\"artwork2\":" + capability + ",\"diag\":1}}") != std::string::npos,
            "wiring: capabilities carry artwork2 after artwork and before diag: " + caps);
    wiring_state::rxInternalBytes = 0;               // the queue landed in PSRAM (diag rxQueue "psram")
    require(one("{\"capabilities\":\"?\"}").find("\"paced\":false,\"rxBytes\":0,") != std::string::npos,
            "wiring: rxBytes 0 when the receive queue is not in internal RAM");
    wiring_state::rxInternalBytes = CC_MEDIA_RX_BYTES;

    // 2. No session: stale, one reply per media line.
    expect(media(have_body(1, "cover", {"a"})), have_ack(1, "cover", "", "Stale media control"), "no session");

    // 3. An accepted control pins its frame's keys: artKey cv0 (covers), iconKey ic0 (icons).
    wiring_state::now = 1000;
    silent(control_line(5, "cv0", "ic0"), "control 5");
    require(cc_take_request(request) && request.id == 5 && !request.release && cc_claimed(), "wiring: control 5 entering");
    for (int i = 0; i < 25; ++i) upload(5, "cover", key_of("cv", i), coverJpeg);   // 25 slots (24 + staging)
    expect(media(begin_body(5, "cover", "cv25", coverJpeg)), ack(5, "begin", "cover", "cv25", 0), "begin cv25");
    have(5, "cover", {"cv1"}, "[false]", "the control's artKey pinned cv0 (the oldest): cv1 was evicted");
    have(5, "cover", {"cv0"}, "[true]", "cv0 kept");
    for (int i = 0; i < 49; ++i) upload(5, "icon", key_of("ic", i), icon_payload(i));   // 49 slots
    expect(media(begin_body(5, "icon", "ic49", icon_payload(49))), ack(5, "begin", "icon", "ic49", 0), "begin ic49");
    have(5, "icon", {"ic1"}, "[false]", "the control's iconKey pinned ic0 (the oldest): ic1 was evicted");
    have(5, "icon", {"ic0"}, "[true]", "ic0 kept");

    // 4. A stale frame and an invalid frame set no frame key (ic2 stays unpinned).
    expect(frame_line(4, "cv0", "ic2"), "{\"error\":\"Stale control frame\"}", "stale frame");
    expect("{\"frame\":{\"id\":5,\"iconKey\":\"ic2\"}}", "{\"error\":\"Invalid control frame\"}", "invalid frame");
    const std::string ic49 = icon_payload(49);
    expect(media(data_body(5, "icon", "ic49", 0, ic49)), ack(5, "data", "icon", "ic49", 2048), "data ic49");
    expect(media(commit_body(5, "icon", "ic49")), ack(5, "commit", "icon", "ic49", 2048), "commit ic49");
    expect(media(begin_body(5, "icon", "ic50", icon_payload(50))), ack(5, "begin", "icon", "ic50", 0), "begin ic50");
    have(5, "icon", {"ic2"}, "[false]", "ic2 (the oldest unpinned) was evicted: the rejected frames pinned nothing");

    // 5. An accepted frame moves the icon pin to ic3 and does not end the upload.
    silent(frame_line(5, "cv0", "ic3"), "frame 5");
    const std::string ic50 = icon_payload(50);
    expect(media(data_body(5, "icon", "ic50", 0, ic50)), ack(5, "data", "icon", "ic50", 2048), "a frame keeps the upload");
    expect(media(commit_body(5, "icon", "ic50")), ack(5, "commit", "icon", "ic50", 2048), "commit ic50");
    expect(media(begin_body(5, "icon", "ic51", icon_payload(51))), ack(5, "begin", "icon", "ic51", 0), "begin ic51");
    have(5, "icon", {"ic4"}, "[false]", "the accepted frame pinned ic3 (the oldest): ic4 was evicted");
    have(5, "icon", {"ic3"}, "[true]", "ic3 kept");

    // 6. A busy control, invalid controls and a stale media ID leave the upload running.
    const std::string ic52 = icon_payload(52);
    expect(media(begin_body(5, "icon", "ic52", ic52)), ack(5, "begin", "icon", "ic52", 0), "begin ic52");
    expect(control_line(5, "cv0", "ic9"), "{\"error\":\"Control ID must advance; wait for release before reconnecting\"}",
           "busy control (the ID does not advance)");
    expect(control_line(6, "cv0", "ic9", "Nope"), "{\"error\":\"Invalid control or unknown existing profile\"}",
           "unknown preset");
    expect(control_line(6, "cv0", "ic9", "Regular", ",\"windowsHidEnabled\":5"),
           "{\"error\":\"Windows HID enable must be a boolean\"}", "invalid control field");
    // FW-RES-007: the feel token is matched length-aware, like device.py (FEEL_TOKENS): a NUL suffix is no token.
    expect(control_line(6, "cv0", "ic9", "Regular", ",\"feel\":\"detent.value\\u0000zz\""),
           "{\"error\":\"Invalid feel token\"}", "FW-RES-007: a NUL-suffixed feel token is refused");
    expect(control_line(6, "cv0", "ic9", "Regular", ",\"feel\":\"detent.value\\u0000\""),
           "{\"error\":\"Invalid feel token\"}", "FW-RES-007: a feel token with a trailing NUL is refused");
    require(!cc_take_request(request), "wiring: rejected controls request nothing");
    expect(media(data_body(4, "icon", "ic52", 0, ic52)), ack(4, "data", "icon", "ic52", 0, "Stale media control"),
           "a stale media ID");
    require(cc_media_receiving(), "wiring: rejected controls and a stale media ID keep the upload");
    expect(media(data_body(5, "icon", "ic52", 0, ic52)), ack(5, "data", "icon", "ic52", 2048), "data ic52");
    expect(media(commit_body(5, "icon", "ic52")), ack(5, "commit", "icon", "ic52", 2048), "commit ic52");

    // 7. Dispatch: a media line gets exactly one reply. It is the mediaAck ahead of release,
    // control and frame; capabilities, diag and art are dispatched before media (one reply,
    // theirs).
    const std::string haveIc52 = have_body(5, "icon", {"ic52"});
    expect("{\"media\":" + haveIc52 + ",\"release\":true}", have_ack(5, "icon", "[true]"), "media before release");
    require(cc_claimed() && !cc_take_request(request), "wiring: the release beside media was not handled");
    expect("{\"media\":" + haveIc52 + ",\"control\":" + control_object(6, "cv0", "") + "}", have_ack(5, "icon", "[true]"),
           "media before control");
    require(!cc_take_request(request), "wiring: the control beside media was not handled");
    expect("{\"media\":" + haveIc52 + ",\"frame\":" + frame_object(5, "cv0", "ic9") + "}", have_ack(5, "icon", "[true]"),
           "media before frame");
    expect("{\"art\":{\"id\":5},\"media\":" + haveIc52 + "}", "{\"artAck\":\"stub\"}", "art before media (unchanged)");
    // cc_handle_command's order is capabilities, diag, art, then media (cc5.2's order kept for the
    // v1 commands): a line that also holds capabilities:"?" or diag:"?" gets that reply alone,
    // never a mediaAck too. The host never combines them (one command per line).
    const std::string capsMedia = one("{\"capabilities\":\"?\",\"media\":" + haveIc52 + "}");
    require(capsMedia.compare(0, 17, "{\"capabilities\":{") == 0 && capsMedia.find("mediaAck") == std::string::npos,
            "wiring: capabilities before media, one reply: " + capsMedia.substr(0, 90));
    const std::string diagMedia = one("{\"media\":" + haveIc52 + ",\"diag\":\"?\"}");
    require(diagMedia.compare(0, 9, "{\"diag\":{") == 0 && diagMedia.find("mediaAck") == std::string::npos,
            "wiring: diag before media, one reply: " + diagMedia.substr(0, 90));
    expect("{\"media\":5}", "{\"mediaAck\":{\"offset\":0,\"error\":\"Unknown media operation\"}}", "media not an object");
    expect("{\"media\":null}", "{\"mediaAck\":{\"offset\":0,\"error\":\"Unknown media operation\"}}", "media null");

    // 8. A new control ends the upload and rebinds media to its ID (no spurious cancel after).
    const std::string ic53 = icon_payload(53);
    expect(media(begin_body(5, "icon", "ic53", ic53)), ack(5, "begin", "icon", "ic53", 0), "begin ic53");
    silent(control_line(6, "cv0", ""), "control 6");
    require(cc_take_request(request) && request.id == 6, "wiring: control 6 entering");
    require(!cc_media_receiving(), "wiring: an accepted control ends the upload at once");
    expect(media(data_body(6, "icon", "ic53", 0, ic53)), ack(6, "data", "icon", "ic53", 0, "No matching media upload"),
           "the upload ended with the old control");
    upload(6, "icon", "ic53", ic53);
    expect(media(have_body(5, "icon", {"ic53"})), have_ack(5, "icon", "", "Stale media control"), "the old ID is stale");

    // 9. A release ends the upload at once; media is stale while releasing; the release completes.
    const std::string ic54 = icon_payload(54);
    expect(media(begin_body(6, "icon", "ic54", ic54)), ack(6, "begin", "icon", "ic54", 0), "begin ic54");
    silent("{\"release\":true}", "release");
    require(!cc_media_receiving(), "wiring: a release ends the upload at once");
    expect(media(data_body(6, "icon", "ic54", 0, ic54)), ack(6, "data", "icon", "ic54", 0, "Stale media control"),
           "media while releasing");
    require(cc_take_request(request) && request.release, "wiring: release requested");
    service_expect("{\"released\":true}", "release completes");
    require(!cc_claimed(), "wiring: idle after the release");

    // 10. Media lines never renew the lease; the service pass after the expiry ends the upload.
    wiring_state::now = 100000;
    silent(control_line(7, "cv0", ""), "control 7");
    require(cc_take_request(request) && request.id == 7, "wiring: control 7 entering");
    const std::string cover = coverJpeg;
    expect(media(begin_body(7, "cover", "cz1", cover)), ack(7, "begin", "cover", "cz1", 0), "begin cz1");
    wiring_state::now = 101000;
    expect(media(data_body(7, "cover", "cz1", 0, cover.substr(0, 100))), ack(7, "data", "cover", "cz1", 100), "data cz1");
    wiring_state::now = 101900;
    have(7, "cover", {"cv0"}, "[true]", "have at 1900 ms");
    wiring_state::now = 101999;
    require(!cc_take_request(request) && cc_claimed(), "wiring: 1999 ms after the control the lease holds");
    wiring_state::now = 102000;
    require(cc_take_request(request) && request.release,
            "wiring: the lease expires 2000 ms after the control: media lines did not renew it");
    require(cc_media_receiving(), "wiring: the FOC thread's expiry leaves the upload to the COM thread");
    service_expect("{\"released\":true,\"reason\":\"lease-expired\"}", "lease expiry release");
    require(!cc_media_receiving(), "wiring: the service pass after a lease expiry ends the upload");

    // 11. Frames do renew the lease.
    wiring_state::now = 200000;
    silent(control_line(8, "cv0", ""), "control 8");
    require(cc_take_request(request) && request.id == 8, "wiring: control 8 entering");
    wiring_state::now = 201500;
    silent(frame_line(8, "cv0", ""), "frame 8");
    wiring_state::now = 203499;
    require(!cc_take_request(request) && cc_claimed(), "wiring: a frame renewed the lease");
    wiring_state::now = 203500;
    require(cc_take_request(request) && request.release, "wiring: 2000 ms after the frame the lease expires");
    service_expect("{\"released\":true,\"reason\":\"lease-expired\"}", "lease expiry after a frame");

    // 12. An expiry noticed by the next media line (before any service pass) ends the upload too.
    wiring_state::now = 300000;
    silent(control_line(9, "cv0", ""), "control 9");
    require(cc_take_request(request) && request.id == 9, "wiring: control 9 entering");
    expect(media(begin_body(9, "cover", "cz2", cover)), ack(9, "begin", "cover", "cz2", 0), "begin cz2");
    wiring_state::now = 302000;
    require(cc_take_request(request) && request.release, "wiring: control 9 lease expired");
    require(cc_media_receiving(), "wiring: still receiving before the COM thread notices");
    expect(media(data_body(9, "cover", "cz2", 0, cover.substr(0, 100))),
           ack(9, "data", "cover", "cz2", 0, "Stale media control"), "media after the expiry");
    require(!cc_media_receiving(), "wiring: the media line after an expiry ended the upload");
    service_expect("{\"released\":true,\"reason\":\"lease-expired\"}", "control 9 released");
    test_control_refused_while_calibrating(request);
    const CCMediaCounters counters = cc_media_counters();
    require(counters.commits == 25 + 49 + 4 && counters.evictions == 6,
            "wiring: counters commits " + num(counters.commits) + ", evictions " + num(counters.evictions));

    // 13. The COM thread's routing of raw bytes (com_route mirrors com_thread.cpp): exactly one
    // reply per line, the parse replies of the real cc_media.cpp counted in mediaErrors.
    uint32_t errors = cc_media_counters().errors;
    std::string big = "{\"media\":{\"id\":9,\"op\":\"data\",\"kind\":\"cover\",\"key\":\"cz3\",\"offset\":0,\"data\":\"";
    big += std::string(5000 - big.size() - 3, 'A') + "\"}}";
    std::vector<std::string> replies = com_route(big + "\n");
    require(replies.size() == 1 && replies[0] == "{\"mediaAck\":{\"op\":\"parse\",\"error\":\"parse\",\"id\":9,\"key\":\"cz3\"}}",
            "wiring: an oversize media line gets exactly one parse mediaAck: " + num(static_cast<long long>(replies.size())) +
                (replies.empty() ? std::string() : " " + replies[0]));
    require(cc_media_counters().errors == errors + 1, "wiring: the oversize parse reply counts in mediaErrors");
    replies = com_route("{\"media\":{\"id\":9,\"op\":\"commit\",\"kind\":\"cover\",\"key\":\"cz3\"\n");
    require(replies.size() == 1 && replies[0] == "{\"mediaAck\":{\"op\":\"parse\",\"error\":\"parse\",\"id\":9,\"key\":\"cz3\"}}",
            "wiring: a media line that is not JSON gets exactly one parse mediaAck");
    require(cc_media_counters().errors == errors + 2, "wiring: the JSON parse reply counts in mediaErrors");
    replies = com_route(std::string(4100, ' ') + "\n" + "{\"frame\":1\n");
    require(replies.size() == 2 && replies[0] == "{\"error\":\"Command too large\"}" &&
                replies[1] == "{\"error\":\"JSON parse error\"}",
            "wiring: other oversize and non-JSON lines get their bare errors");
    require(cc_media_counters().errors == errors + 2, "wiring: bare errors are not media errors");
    replies = com_route("{\"art\":{\"id\":3,\"key\":\"k\"\n");
    require(replies.size() == 1 && replies[0] == "art-parse", "wiring: an art line that is not JSON is answered as art");
    replies = com_route(media(have_body(9, "cover", {"cv0"})) + "\n" + media(have_body(9, "cover", {"cv0"})) + "\r\n");
    require(replies.size() == 2 && replies[0] == have_ack(9, "cover", "", "Stale media control") && replies[1] == replies[0],
            "wiring: whole media lines written back to back get one reply each");
    require(cc_media_counters().errors == errors + 4, "wiring: media error replies count in mediaErrors");

    // 14. {"diag":"?"} carries every PRESENTATION_V5 12.3 field (VOC-K1c; alive_tests.py holds this
    // list equal to nanod_cc5_tooling.LCD_DIAG_FIELDS + LCD_FIX_DIAG_FIELDS): control_center.cpp's four and, through one
    // cc_diag_lcd_pipeline() per reply, the LCD thread's, with lcdDma and artAsync as JSON booleans
    // (the tooling's binary A fallback tests `is True`). 12.6 errata E-lcd adds lcdMosiSig (an integer,
    // 103 = FSPID on the data line, 102 = binary A's defect) and "build" (the ladder letter of
    // CC_BUILD_BINARY, a string; absent when the image has no ladder id, as in A, B and C). Binary D
    // (A's pipeline), binary E (C's), then an image without a ladder id (A's pipeline, A's defect).
    static const char* const kDiagFields[] = {
        "lcdFps", "lcdFpsAnimMin", "lcdRefrUsMax", "lcdRefrUsAvg", "lcdRenderUsMax", "lcdFlushUs", "lcdPxPerRefr",
        "lcdFullRefrs", "lcdLateRefrs", "lcdMaxGapMs", "lcdBusyPct", "core0IdlePct", "lcdSpiHz", "enterMsLast",
        "enterMsMax", "holdEvents", "holdDeferred", "lcdDma", "lcdPeriodMs", "artAsync", "artDecodeRequests",
        "artDecodeAborts", "artDecodeStale", "stackArtDec", "lcdMosiSig", "build"};
    struct DiagBinary { uint32_t dma, periodMs, async, mosiSig, build; const char* letter; const char* label; };
    // 1.0.0-cc5.5 adds binary F (CC_BUILD_BINARY 6: D's pipeline at a 12 ms LCD period, diag build "F").
    static const DiagBinary kBinaries[] = {{1, 16, 1, 103, 4, "D", "binary D"}, {0, 33, 0, 103, 5, "E", "binary E"},
                                           {1, 12, 1, 103, 6, "F", "binary F"},
                                           {1, 16, 1, 102, 0, nullptr, "no ladder id"}};
    for (const DiagBinary& binary : kBinaries) {
        wiring_state::LcdPerf& p = wiring_state::lcdPerf;
        p.lcdFps = 58; p.lcdFpsAnimMin = 47; p.lcdRefrUsMax = 9100; p.lcdRefrUsAvg = 4200; p.lcdRenderUsMax = 3100;
        p.lcdFlushUs = 210000; p.lcdPxPerRefr = 14400; p.lcdFullRefrs = 12; p.lcdLateRefrs = 3; p.lcdMaxGapMs = 41;
        p.lcdBusyPct = 37; p.core0IdlePct = 55; p.lcdSpiHz = 80000000; p.lcdDma = binary.dma;
        p.lcdPeriodMs = binary.periodMs; p.artAsync = binary.async; p.artDecodeRequests = 7; p.artDecodeAborts = 2;
        p.artDecodeStale = 1; p.stackArtDec = 2900; p.lcdMosiSig = binary.mosiSig; p.buildBinary = binary.build;
        const uint32_t reads = wiring_state::lcdPipelineReads;
        const std::string reply = one("{\"diag\":\"?\"}");
        const std::string label = binary.label;
        require(wiring_state::lcdPipelineReads == reads + 1, "wiring: one LCD pipeline read per diag reply (" + label + ")");
        JsonDocument parsed;
        require(!deserializeJson(parsed, reply), "wiring: the diag reply is JSON");
        JsonObjectConst d = parsed["diag"];
        for (const char* key : kDiagFields) {
            if (std::string(key) == "build") continue;   // a string, or absent: checked below
            require(d[key].is<uint32_t>() || d[key].is<bool>(), std::string("wiring: diag carries 12.3 ") + key + " (" +
                                                                    label + "): " + reply.substr(0, 120));
        }
        if (binary.letter) {
            require(d["build"].is<const char*>() && std::string(d["build"].as<const char*>()) == binary.letter &&
                        reply.find(std::string("\"build\":\"") + binary.letter + "\"") != std::string::npos,
                    "wiring: diag build is the ladder letter " + std::string(binary.letter) + " (" + label + ")");
        } else {
            require(!d["build"].is<const char*>() && reply.find("\"build\"") == std::string::npos,
                    "wiring: diag has no build field without a ladder id (" + label + ")");
        }
        require(d["lcdDma"].is<bool>() && d["lcdDma"].as<bool>() == (binary.dma != 0) &&
                    d["artAsync"].is<bool>() && d["artAsync"].as<bool>() == (binary.async != 0) &&
                    reply.find(std::string("\"lcdDma\":") + (binary.dma ? "true" : "false")) != std::string::npos &&
                    reply.find(std::string("\"artAsync\":") + (binary.async ? "true" : "false")) != std::string::npos,
                "wiring: lcdDma and artAsync are JSON booleans (" + label + ")");
        const struct { const char* key; uint32_t value; } numbers[] = {
            {"lcdFps", 58}, {"lcdFpsAnimMin", 47}, {"lcdRefrUsMax", 9100}, {"lcdRefrUsAvg", 4200},
            {"lcdRenderUsMax", 3100}, {"lcdFlushUs", 210000}, {"lcdPxPerRefr", 14400}, {"lcdFullRefrs", 12},
            {"lcdLateRefrs", 3}, {"lcdMaxGapMs", 41}, {"lcdBusyPct", 37}, {"core0IdlePct", 55},
            {"lcdSpiHz", 80000000}, {"lcdPeriodMs", binary.periodMs}, {"artDecodeRequests", 7},
            {"artDecodeAborts", 2}, {"artDecodeStale", 1}, {"stackArtDec", binary.async ? 2900u : 0u},
            {"lcdMosiSig", binary.mosiSig}};
        for (const auto& number : numbers) {
            require(d[number.key].is<uint32_t>() && d[number.key].as<uint32_t>() == number.value,
                    std::string("wiring: diag ") + number.key + " = " + num(number.value) + " (" + label + ")");
        }
    }

    // 15. PRESENTATION_V5 8.10 (ALIVE.md 8.1): the native button edges the HMI's unclaimed branch
    // reports are readable by the LCD thread, one step per edge; command lines never move them.
    const uint32_t edges = cc_native_button_seq();
    cc_native_button_edge();
    require(cc_native_button_seq() == edges + 1u, "wiring: a native button edge moves cc_native_button_seq()");
    cc_native_button_edge();
    one("{\"diag\":\"?\"}");
    require(cc_native_button_seq() == edges + 2u, "wiring: one step per edge; a diag line moves nothing");

    // 16. 1.0.0-cc5.5 F1: the `ks` of the ready control's position lines (com_thread.cpp handleEvents()) is the
    // mask last reported on a key line AND the live mask, so it only clears bits; while a key event is still
    // queued it is the last reported mask unchanged (a ku on its way is never pre-empted).
    cc_publish_key_state(0x3);
    cc_key_line_sent(0x3);                                              // kd 0, kd 1 went out (ks 3)
    require(cc_position_key_state(cc_live_key_state(), false) == 0x3, "wiring F1: position ks = reported & live");
    cc_publish_key_state(0x1);                                          // raw 1 released; its ku still queued
    require(cc_position_key_state(cc_live_key_state(), true) == 0x3, "wiring F1: a queued key event holds the mask");
    require(cc_position_key_state(cc_live_key_state(), false) == 0x1,
            "wiring F1: no event queued: a lost key-up is cleared");
    cc_publish_key_state(0x5);                                          // raw 2 pressed; its kd not sent yet
    require(cc_position_key_state(cc_live_key_state(), false) == 0x1, "wiring F1: a position line never sets a bit");
    cc_key_line_sent(0x5);                                              // kd 2 went out
    require(cc_position_key_state(cc_live_key_state(), false) == 0x5, "wiring F1: the kd's mask is reported next");
    cc_publish_key_state(0x10 | 0x4);                                   // only the four raw bits count
    require(cc_live_key_state() == 0x4 && cc_position_key_state(cc_live_key_state(), false) == 0x4,
            "wiring F1: the live mask is the four raw buttons");
    cc_publish_key_state(0);
    cc_key_line_sent(0);
    require(cc_position_key_state(cc_live_key_state(), false) == 0, "wiring F1: all up");

    // 17. 1.0.0-cc5.5 F1: haptic profile validation (haptic_bounds.h, applied in HapticState::load_profile() and
    // HapticProfile's JSON load): detent_count >= 1, vernier >= 1, end_pos >= start_pos; a valid profile unchanged.
    DetentProfile valid{};
    valid.mode = REGULAR; valid.start_pos = 0; valid.end_pos = 255; valid.detent_count = 60; valid.vernier = 5;
    DetentProfile copy = valid;
    require(!haptic_profile_sanitize(copy) && copy.detent_count == 60 && copy.vernier == 5 && copy.start_pos == 0 &&
                copy.end_pos == 255 && copy.mode == REGULAR,
            "wiring F1: a valid profile is left exactly as it was");
    DetentProfile broken = valid;
    broken.detent_count = 0; broken.vernier = 0; broken.start_pos = 40; broken.end_pos = 10;
    require(haptic_profile_sanitize(broken) && broken.detent_count == 1 && broken.vernier == 1 &&
                broken.start_pos == 40 && broken.end_pos == 40 && broken.mode == REGULAR,
            "wiring F1: detentCount 0, vernier 0 and endPos < startPos are repaired");
    require(!haptic_profile_sanitize(broken), "wiring F1: sanitizing twice changes nothing");
    wiringChecks = checks - before;
}
}  // namespace
// FW-RES-006: art_ack_never_echoes_invalid_op_or_key. cc_artwork.cpp's artAck goes through
// cc_art_ack() (src/cc_artwork.h): op is echoed only when it is begin/data/commit and key only
// when it is a valid content key, else "". For an op/key with \u0001, 0xFF or 300 B, the reply
// must be strict JSON (strict UTF-8, no byte < 0x20) and echo neither.
bool strict_utf8_line(const std::string& s) {
    for (size_t i = 0; i < s.size();) {
        const unsigned char c = static_cast<unsigned char>(s[i]);
        if (c < 0x20 || c == 0x7F) return false;
        size_t n = c < 0x80 ? 0 : (c & 0xE0) == 0xC0 && c >= 0xC2 ? 1 : (c & 0xF0) == 0xE0 ? 2
                 : (c & 0xF8) == 0xF0 && c <= 0xF4 ? 3 : 99;
        if (n == 99 || i + n >= s.size()) return false;
        for (size_t k = 1; k <= n; ++k)
            if ((static_cast<unsigned char>(s[i + k]) & 0xC0) != 0x80) return false;
        i += n + 1;
    }
    return true;
}
std::string art_ack_line(uint32_t id, const char* key, const char* op, const char* error) {
    JsonDocument out;
    cc_art_ack(out["artAck"].to<JsonObject>(), id, key, op, 0, error);
    std::string line;
    serializeJson(out, line);
    return line;
}
void art_ack_never_echoes_invalid_op_or_key() {
    const std::string big(300, 'a');
    const std::string ctl = std::string("be\x01gin");
    const std::string ff = std::string("k\xFFy");
    const char* bad[] = {ctl.c_str(), ff.c_str(), big.c_str(), "art key", "", "\x1f"};
    for (const char* b : bad) {
        const std::string asOp = art_ack_line(7, "cover_1", b, "Unknown artwork operation");
        const std::string asKey = art_ack_line(7, b, "data", "Stale artwork selection");
        require(asOp == "{\"artAck\":{\"id\":7,\"key\":\"cover_1\",\"op\":\"\",\"offset\":0,"
                        "\"error\":\"Unknown artwork operation\"}}", "art ack: invalid op not echoed: " + asOp);
        require(asKey == "{\"artAck\":{\"id\":7,\"key\":\"\",\"op\":\"data\",\"offset\":0,"
                         "\"error\":\"Stale artwork selection\"}}", "art ack: invalid key not echoed: " + asKey);
        const std::string both = art_ack_line(0, b, b, "Stale artwork selection");
        for (const std::string* line : {&asOp, &asKey, &both}) {
            JsonDocument back;
            require(strict_utf8_line(*line) && !deserializeJson(back, *line) && back["artAck"].is<JsonObject>(),
                    "art ack: strict JSON line");
        }
    }
    require(art_ack_line(3, "cover_1", "Begin", "Unknown artwork operation").find("\"op\":\"\"") != std::string::npos,
            "art ack: op match is exact");
    const std::string key64(64, 'k');
    for (const char* op : {"begin", "data", "commit"})
        require(art_ack_line(3, key64.c_str(), op, nullptr) ==
                    "{\"artAck\":{\"id\":3,\"key\":\"" + key64 + "\",\"op\":\"" + op + "\",\"offset\":0}}",
                std::string("art ack: valid op/key echoed for ") + op);
    require(art_ack_line(3, (key64 + "k").c_str(), "begin", nullptr).find("\"key\":\"\"") != std::string::npos,
            "art ack: 65-byte key not echoed");
    require(cc_art_valid_key("Ab-9_z") && !cc_art_valid_key(nullptr) && !cc_art_valid_key("a.b"), "art key rule");
}
#endif  // CC_MEDIA_WIRING

int main(int argc, char** argv) {
    if (argc < 3) {
        std::printf("usage: media_tests media_store_traces.json artwork2-capability-json\n");
        return 2;
    }
    std::ifstream file(argv[1], std::ios::binary);
    std::stringstream text;
    text << file.rdbuf();
    const std::string json = text.str();
    JsonDocument fixture;
    const DeserializationError error = deserializeJson(fixture, json);
    if (error) {
        std::printf("FAIL: %s is not JSON: %s\n", argv[1], error.c_str());
        return 1;
    }
    require(fixture["version"] == 1, "fixture version 1");
    const long long beforeVerdicts = checks;
    if (argc >= 6) model_verdicts(argv[5]);
    else report("usage: argv[5] (the reference Model's cover verdicts) is missing");
    const long long verdictChecks = checks - beforeVerdicts;
    long long cases = 0;
    for (JsonObjectConst testCase : fixture["cases"].as<JsonArrayConst>()) {
        replay(testCase);
        ++cases;
    }
    const long long afterReplay = checks, parityChecks = afterReplay - beforeVerdicts - verdictChecks;
    crc_and_base64();
    parse_replies();
    com_transport();
    availability();
    pins_and_adoption();
    device_config();
    capability(argv[2]);
    const long long directChecks = checks - afterReplay;
#if defined(CC_MEDIA_WIRING)
    if (argc < 5) {
        report("wiring: usage media_tests traces.json capability frame.json cover.jpg");
    } else {
        frameText = read_file(argv[3]);
        coverJpeg = read_file(argv[4]);
        wiring_tests(argv[2]);
    }
    art_ack_never_echoes_invalid_op_or_key();
    std::printf("media_tests: control_center.cpp media wiring: %lld check(s)\n", wiringChecks);
#endif
    std::printf("media_tests: %lld case(s): %lld media ack(s), %lld check step(s), %lld other step(s); "
                "%lld Model cover verdict(s), %lld parity check(s), %lld direct check(s), %d failure(s)\n",
                cases, media_steps, check_steps, other_steps, verdictChecks, parityChecks, directChecks, failures);
    return failures ? 1 : 0;
}
