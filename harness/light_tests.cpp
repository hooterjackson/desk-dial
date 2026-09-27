// cc5 LED renderer checks (Stage 5). Built by light_tests.py with MSVC /W4 /WX
// together with the unchanged firmware units ../firmware/src/cc_lights.cpp
// and cc_frame_parse.cpp. Written in the C++11 subset (the firmware is gnu++11).
//
// Part 1 - sequence parity. argv[1] is light_pixels.json, generated from the
// companion's Python reference model (tests/tools/make_light_sequences.py):
//   {"frames": [wire frame...], "cases": {name: {"steps": [step...]}}}
// Every frame goes through the firmware's own cc_parse_frame(). Each case is
// replayed through ONE CCLightRenderer, and at every step the renderer must
// match PreviewLights bit-exactly: logical ring, the physical ring for the four
// mounting orientations (against an independent wiring model), buttons, cursor,
// flash, lastSeq, the pure target (cc_ring_target with the recorded onset times)
// and the stateless cc_render_buttons(). argv[2] (optional) receives the actual
// C++ output as JSON lines for light_tests.py's own cross-check.
//
// Part 2 - direct assertions: physical anchors, the bottom gap, lit counts,
// thresholds, list collisions, helpers, tone table, defensive rules, seeding.
#include <ArduinoJson.h>
#include "cc_frame_parse.h"
#include "cc_lights.h"
#include "cc_presentation.h"

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

std::string hex(uint32_t value) {
    char text[16];
    std::snprintf(text, sizeof(text), "0x%06X", static_cast<unsigned>(value));
    return text;
}

std::string num(long long value) {
    char text[32];
    std::snprintf(text, sizeof(text), "%lld", value);
    return text;
}

// Hardware model, independent of the renderer's modulo expression: keep the
// native top pin of each mounting, then walk the wired addresses downward to
// move clockwise (0 = top, 15 = right, 30 = bottom, 45 = left).
int physicalAt(int clockwise, int orientation) {
    static const int topPin[4] = {0, 45, 30, 15};
    int pin = topPin[orientation & 3];
    int steps = ((clockwise % 60) + 60) % 60;
    while (steps--) pin = pin == 0 ? 59 : pin - 1;
    return pin;
}

uint8_t peakOf(uint32_t color) {
    const uint8_t r = static_cast<uint8_t>((color >> 16) & 255), g = static_cast<uint8_t>((color >> 8) & 255),
                  b = static_cast<uint8_t>(color & 255);
    const uint8_t rg = r > g ? r : g;
    return rg > b ? rg : b;
}

// ------------------------------------------------------------ part 1: parity
struct Parity {
    int cases, steps, frames;
    long long values;
};

bool readFile(const char* path, std::string& out) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return false;
    std::stringstream buffer;
    buffer << in.rdbuf();
    out = buffer.str();
    return true;
}

// Compares one value; reports only the first mismatch of a step (the caller
// stops the case after a failing step so one bug does not flood the log).
// `what` names the value; `a`/`b` (when >= 0) are appended as [a] / (pin b).
// The message is only built on a mismatch: millions of values are compared.
bool same(const std::string& where, const char* what, long long expected, long long actual, Parity& p,
          int a = -1, int b = -1) {
    ++checks;
    ++p.values;
    if (expected == actual) return true;
    std::string label = what;
    if (a >= 0) label += "[" + num(a) + "]";
    if (b >= 0) label += " (pin " + num(b) + ")";
    report(where + ": " + label + " expected " + num(expected) + " (" + hex(static_cast<uint32_t>(expected)) +
           ") got " + num(actual) + " (" + hex(static_cast<uint32_t>(actual)) + ")");
    return false;
}

bool runSequences(const char* fixturePath, const char* actualPath, Parity& p) {
    std::string text;
    if (!readFile(fixturePath, text)) {
        report(std::string("cannot read ") + fixturePath);
        return false;
    }
    JsonDocument doc;
    const DeserializationError error = deserializeJson(doc, text);
    if (error) {
        report(std::string("fixture JSON: ") + error.c_str());
        return false;
    }
    JsonArrayConst frames = doc["frames"].as<JsonArrayConst>();
    JsonObjectConst cases = doc["cases"].as<JsonObjectConst>();
    require(!frames.isNull() && frames.size() > 0 && !cases.isNull() && cases.size() > 0,
            "fixture has frames and cases");
    std::vector<CCFrame> parsed(frames.size());
    for (size_t i = 0; i < frames.size(); ++i)
        require(cc_parse_frame(frames[i], parsed[i]), "cc_parse_frame accepts fixture frame " + num(static_cast<long long>(i)));
    p.frames = static_cast<int>(frames.size());

    FILE* actual = actualPath ? std::fopen(actualPath, "wb") : nullptr;
    if (actualPath) require(actual != nullptr, std::string("can write ") + actualPath);

    for (JsonPairConst entry : cases) {
        const std::string name = entry.key().c_str();
        JsonArrayConst steps = entry.value()["steps"].as<JsonArrayConst>();
        require(!steps.isNull() && steps.size() > 0, name + ": has steps");
        ++p.cases;
        CCLightRenderer renderer;
        size_t index = 0;
        for (JsonVariantConst item : steps) {
            JsonObjectConst step = item.as<JsonObjectConst>();
            const std::string where = name + " step " + num(static_cast<long long>(index));
            ++p.steps;
            const uint32_t f = step["f"].as<uint32_t>();
            if (!step["f"].is<uint32_t>() || f >= parsed.size()) {
                report(where + ": bad frame index");
                break;
            }
            const CCFrame& frame = parsed[f];
            if (step["reset"].as<bool>()) renderer.reset();
            const uint32_t controlId = step["control_id"].as<uint32_t>();
            const uint32_t now = step["now_ms"].as<uint32_t>();
            const uint8_t pressed = step["pressed"].as<uint8_t>();
            uint32_t ring[CC_RING_LEDS], buttons[4];
            renderer.render(frame, controlId, now, pressed, ring, buttons);

            bool ok = true;
            JsonArrayConst ringExpected = step["ring"].as<JsonArrayConst>();
            JsonArrayConst buttonsExpected = step["buttons"].as<JsonArrayConst>();
            ok = ok && same(where, "ring length", 60, static_cast<long long>(ringExpected.size()), p);
            ok = ok && same(where, "buttons length", 4, static_cast<long long>(buttonsExpected.size()), p);
            if (!ok) break;
            uint32_t expected[CC_RING_LEDS];
            for (int k = 0; k < CC_RING_LEDS; ++k) {
                expected[k] = ringExpected[k].as<uint32_t>();
                ok = same(where, "logical ring", expected[k], ring[k], p, k) && ok;
            }
            for (uint8_t o = 0; o < 4 && ok; ++o) {
                uint32_t physical[CC_RING_LEDS];
                cc_ring_physical(ring, o, physical);
                static const char* const labels[4] = {"orientation 0 clockwise", "orientation 1 clockwise",
                                                      "orientation 2 clockwise", "orientation 3 clockwise"};
                for (int k = 0; k < CC_RING_LEDS && ok; ++k) {
                    const int pin = physicalAt(k, o);
                    ok = same(where, labels[o], expected[k], physical[pin], p, k, pin);
                }
            }
            for (int b = 0; b < 4; ++b)
                ok = same(where, "button", buttonsExpected[b].as<uint32_t>(), buttons[b], p, b) && ok;
            ok = same(where, "cursor", step["cursor"].as<int>(), renderer.cursor(), p) && ok;
            ok = same(where, "flash", step["flash"].as<int>(), renderer.flash(), p) && ok;
            ok = same(where, "lastSeq", step["last_seq"].as<uint32_t>(), renderer.lastSeq(), p) && ok;

            // Pure target builder with the onset times and flash the model used.
            CCLedCell cells[CC_RING_LEDS];
            const uint8_t cursor = cc_ring_target(frame, step["pending_ms"].as<uint32_t>(),
                                                  step["loading_ms"].as<uint32_t>(),
                                                  step["flash"].as<uint8_t>(), cells);
            ok = same(where, "target cursor", step["cursor"].as<int>(), cursor, p) && ok;
            uint32_t targetRgb[CC_RING_LEDS] = {};
            uint8_t targetLevel[CC_RING_LEDS] = {};
            for (JsonVariantConst cellItem : step["cells"].as<JsonArrayConst>()) {
                JsonArrayConst row = cellItem.as<JsonArrayConst>();
                const int segment = row[0].as<int>();
                if (segment < 0 || segment >= CC_RING_LEDS) { ok = false; report(where + ": bad cell row"); break; }
                targetRgb[segment] = row[1].as<uint32_t>();
                targetLevel[segment] = row[2].as<uint8_t>();
            }
            for (int k = 0; k < CC_RING_LEDS; ++k) {
                ok = same(where, "target rgb", targetRgb[k], cells[k].rgb, p, k) && ok;
                ok = same(where, "target level", targetLevel[k], cells[k].level, p, k) && ok;
            }
            uint32_t stateless[4];
            cc_render_buttons(frame, pressed, stateless);
            JsonArrayConst statelessExpected = step["button_pixels"].as<JsonArrayConst>();
            for (int b = 0; b < 4; ++b)
                ok = same(where, "button_pixels", statelessExpected[b].as<uint32_t>(), stateless[b], p, b) && ok;

            if (actual) {
                std::fprintf(actual, "{\"case\":\"%s\",\"step\":%u,\"ring\":[", name.c_str(), static_cast<unsigned>(index));
                for (int k = 0; k < CC_RING_LEDS; ++k) std::fprintf(actual, "%s%u", k ? "," : "", static_cast<unsigned>(ring[k]));
                std::fprintf(actual, "],\"buttons\":[");
                for (int b = 0; b < 4; ++b) std::fprintf(actual, "%s%u", b ? "," : "", static_cast<unsigned>(buttons[b]));
                std::fprintf(actual, "],\"physical\":[");
                for (uint8_t o = 0; o < 4; ++o) {
                    uint32_t physical[CC_RING_LEDS];
                    cc_ring_physical(ring, o, physical);
                    std::fprintf(actual, "%s[", o ? "," : "");
                    for (int k = 0; k < CC_RING_LEDS; ++k)
                        std::fprintf(actual, "%s%u", k ? "," : "", static_cast<unsigned>(physical[k]));
                    std::fprintf(actual, "]");
                }
                std::fprintf(actual, "]}\n");
            }
            ++index;
            if (!ok) break;   // later steps of this case depend on the state that diverged
        }
    }
    if (actual) std::fclose(actual);
    return true;
}

// ------------------------------------------------------ part 2: direct checks
void setButtons(CCFrame& f, const char* const labels[4], const uint8_t icons[4], const bool enabled[4]) {
    for (int k = 0; k < 4; ++k) {
        std::strncpy(f.buttons[k].label, labels[k], sizeof(f.buttons[k].label) - 1);
        f.buttons[k].icon = icons[k];
        f.buttons[k].iconSent = true;
        f.buttons[k].enabled = enabled[k];
    }
}

CCFrame volume(int v, bool colored, int confirmed = -1, bool external = false, uint8_t activity = CC_IDLE) {
    CCFrame f;
    std::strcpy(f.mode, "VOLUME");
    f.layoutId = CC_LAYOUT_VOLUME;
    f.ringStyle = CC_RING_LEVEL;
    f.ringValue = static_cast<uint8_t>(v);
    f.confirmedVolume = static_cast<uint8_t>(confirmed < 0 ? v : confirmed);
    f.ringExternal = external;
    f.coloredLeds = colored;
    f.activity = activity;
    const char* const labels[4] = {"Pause", "Browse", "Win", "Tracks"};
    const uint8_t icons[4] = {CC_ICON_PAUSE, CC_ICON_LIST, CC_ICON_WIN, CC_ICON_TRACKS};
    const bool enabled[4] = {true, true, true, true};
    setButtons(f, labels, icons, enabled);
    return f;
}

uint32_t accentOf(int j) {
    return (static_cast<uint32_t>(0x40 + j) << 16) | (static_cast<uint32_t>(0x80 + j) << 8) | 0x11u;
}

CCFrame list(int count, int index, int more = -1, bool windows = false) {
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
    const char* const labels[4] = {"Back", "Home", "Win", "Play"};
    const uint8_t icons[4] = {CC_ICON_BACK, CC_ICON_HOME, CC_ICON_WIN, CC_ICON_PLAY};
    const bool enabled[4] = {true, true, true, true};
    setButtons(f, labels, icons, enabled);
    return f;
}

CCFrame transport(int index, bool noPrev = false) {
    CCFrame f = list(3, index);
    std::strcpy(f.mode, "TRACKS");
    f.layoutId = CC_LAYOUT_TRACKS;
    f.ringStyle = CC_RING_TRANSPORT;
    f.ringColorCount = 0;
    f.ringUnavailable = noPrev ? 1u : 0u;
    return f;
}

// One snapped render (a fresh renderer), logical output.
void renderOnce(const CCFrame& f, uint32_t (&ring)[CC_RING_LEDS], uint32_t (&buttons)[4], uint32_t now = 1000) {
    CCLightRenderer renderer;
    renderer.render(f, 1, now, 0, ring, buttons);
}

int litCount(const uint32_t (&ring)[CC_RING_LEDS]) {
    int count = 0;
    for (int k = 0; k < CC_RING_LEDS; ++k) if (ring[k]) ++count;
    return count;
}

int litCells(const CCLedCell (&cells)[CC_RING_LEDS]) {
    int count = 0;
    for (int k = 0; k < CC_RING_LEDS; ++k) if (cells[k].level) ++count;
    return count;
}

int brightestPin(const uint32_t (&physical)[CC_RING_LEDS]) {
    int selected = 0;
    for (int k = 1; k < CC_RING_LEDS; ++k)
        if (peakOf(physical[k]) > peakOf(physical[selected])) selected = k;
    return selected;
}

int slotOf(int j, int count) {
    const int c0 = (count - 1) / 2;
    return (((j - c0) * 3) % 60 + 60) % 60;
}

void physicalChecks() {
    // Orientation-1 (verified upright mounting) anchors.
    require(cc_ring_address(0, 1) == 45, "orientation 1: twelve o'clock is physical LED 45");
    require(cc_ring_address(15, 1) == 30, "orientation 1: three o'clock is physical LED 30");
    require(cc_ring_address(30, 1) == 15, "orientation 1: six o'clock is physical LED 15");
    require(cc_ring_address(45, 1) == 0, "orientation 1: nine o'clock is physical LED 0");
    for (int o = 0; o < 4; ++o)
        for (int k = -60; k < 120; ++k)
            require(cc_ring_address(k, static_cast<uint8_t>(o)) == physicalAt(k, o),
                    "address() matches the wiring model, orientation " + num(o) + " segment " + num(k));
    require(cc_ring_address(0, 5) == cc_ring_address(0, 1), "orientation uses its low two bits only");

    uint32_t ring[CC_RING_LEDS], buttons[4], physical[CC_RING_LEDS];
    renderOnce(transport(1), ring, buttons);
    cc_ring_physical(ring, 1, physical);
    require(brightestPin(physical) == 45 && physical[45] == cc_led_drive(CCLed::white, CCLed::L2),
            "orientation 1: Tracks Neutral lights physical LED 45 at L2");
    renderOnce(transport(0), ring, buttons);
    cc_ring_physical(ring, 1, physical);
    require(physical[53] == cc_led_drive(CCLed::white, CCLed::L3) && physical[52] == physical[53],
            "orientation 1: Tracks Prev (segments 52/53) lights physical LEDs 53/52 at L3");
    renderOnce(transport(2), ring, buttons);
    cc_ring_physical(ring, 1, physical);
    require(physical[38] == cc_led_drive(CCLed::white, CCLed::L3) && physical[37] == physical[38],
            "orientation 1: Tracks Next (segments 7/8) lights physical LEDs 38/37 at L3");

    // Volume: the bottom gap 26..34 stays dark and the lit counts are 2/29/51,
    // in every mounting, both styles, confirmed/external/pending variants.
    for (int colored = 0; colored < 2; ++colored) {
        const int counts[3][2] = {{0, 2}, {54, 29}, {100, 51}};
        for (int c = 0; c < 3; ++c) {
            renderOnce(volume(counts[c][0], colored != 0), ring, buttons);
            for (uint8_t o = 0; o < 4; ++o) {
                cc_ring_physical(ring, o, physical);
                require(litCount(physical) == counts[c][1],
                        "volume " + num(counts[c][0]) + " lights " + num(counts[c][1]) + " LEDs, orientation " + num(o));
            }
        }
        for (int v = 0; v <= 100; ++v) {
            const int confirmed[3] = {v, 0, 100};
            for (int c = 0; c < 3; ++c) {
                renderOnce(volume(v, colored != 0, confirmed[c], v % 3 == 0), ring, buttons);
                for (uint8_t o = 0; o < 4; ++o) {
                    cc_ring_physical(ring, o, physical);
                    for (int k = 26; k <= 34; ++k)
                        require(physical[physicalAt(k, o)] == 0,
                                "volume " + num(v) + "/" + num(confirmed[c]) + " keeps segment " + num(k) +
                                " dark, orientation " + num(o));
                }
            }
        }
    }
}

void volumeChecks() {
    CCLedCell cells[CC_RING_LEDS];
    for (int v = 0; v <= 100; ++v) {
        const int n = (v + 1) / 2;
        const uint8_t cursor = cc_ring_target(volume(v, true), 0, 0, CC_FLASH_NONE, cells);
        require(cursor == (35 + n) % 60, "volume cursor is vseg(v), v " + num(v));
        const uint32_t endpoint = n >= 45 ? CCLed::volumeRed : (n >= 40 ? CCLed::amber : CCLed::white);
        require(cells[cursor].rgb == endpoint && cells[cursor].level == CCLed::L3,
                "colour endpoint threshold (k 40 amber, 45 red), v " + num(v));
        if (v & 1) require(cells[(35 + n - 1) % 60].level == CCLed::shoulder, "odd v shoulder at LS, v " + num(v));
        cc_ring_target(volume(v, false, v % 7 == 0 ? 0 : v), 0, 0, CC_FLASH_NONE, cells);
        for (int k = 0; k < CC_RING_LEDS; ++k)
            if (cells[k].level) require(cells[k].rgb == CCLed::white, "white mode is pure white, v " + num(v));
    }
    cc_ring_target(volume(78, true), 0, 0, CC_FLASH_NONE, cells);
    require(cells[(35 + 39) % 60].rgb == CCLed::white, "v 78 endpoint (k 39) is white");
    cc_ring_target(volume(100, true), 0, 0, CC_FLASH_NONE, cells);
    require(cells[25].rgb == CCLed::volumeRed && cells[25].level == CCLed::L3, "segment 25 is red at 100 %");
    cc_ring_target(volume(54, true, 54, true), 0, 0, CC_FLASH_NONE, cells);
    require(cells[2].level == CCLed::L4, "external endpoint is L4");
    const uint8_t offline = cc_ring_target(volume(61, true, 41, false, CC_OFFLINE), 0, 0, CC_FLASH_NONE, cells);
    require(offline == 56 && litCells(cells) == 1 && cells[56].rgb == CCLed::white && cells[56].level == CCLed::L1,
            "Home offline lights only vseg(confirmed), white L1");
    cc_ring_target(volume(40, true, 60), 0, 0, CC_FLASH_NONE, cells);
    for (int k = 21; k <= 30; ++k)
        require(cells[(35 + k) % 60].level == CCLed::L1, "pending decrease span is L1, k " + num(k));
}

void listChecks() {
    const int counts[] = {1, 2, 9, 11, 16, 20, 21, 45, 80};
    CCLedCell cells[CC_RING_LEDS];
    for (int n : counts) {
        const int indexes[3] = {0, n / 2, n - 1};
        for (int i : indexes) {
            const CCFrame f = list(n, i);
            const int first = f.ringFirst, width = n - first < 20 ? n - first : 20;
            const uint8_t cursor = cc_ring_target(f, 0, 0, CC_FLASH_NONE, cells);
            require(cursor == slotOf(i, n), "list cursor slot, n " + num(n) + " index " + num(i));
            require(litCells(cells) == width, "list lights exactly its window without collisions, n " + num(n) +
                    " index " + num(i));
            for (int j = first; j < first + width; ++j) {
                const CCLedCell& c = cells[slotOf(j, n)];
                require(c.rgb == accentOf(j) && c.level == (j == i ? CCLed::L3 : CCLed::L1),
                        "list landmark/cursor accent, n " + num(n) + " entry " + num(j));
            }
            if (n >= 2) {
                cc_ring_target(list(n, i, n - 1), 0, 0, CC_FLASH_NONE, cells);
                require(litCells(cells) == width + 1,
                        "More adds one double landmark (never a collision), n " + num(n) + " index " + num(i));
            }
        }
    }
    // Unavailable cursor: Recent white L2, Windows accent L2; a gap elsewhere.
    CCFrame recent = list(9, 3);
    recent.ringUnavailable = (1u << 3) | (1u << 5);
    uint8_t cursor = cc_ring_target(recent, 0, 0, CC_FLASH_NONE, cells);
    require(cells[cursor].rgb == CCLed::white && cells[cursor].level == CCLed::L2, "Recent unavailable cursor is white L2");
    require(cells[slotOf(5, 9)].level == 0, "an unavailable Recent entry leaves a gap");
    CCFrame windows = list(9, 3, -1, true);
    windows.ringUnavailable = 1u << 3;
    cursor = cc_ring_target(windows, 0, 0, CC_FLASH_NONE, cells);
    require(cells[cursor].rgb == accentOf(3) && cells[cursor].level == CCLed::L2, "closed window cursor keeps its app colour");
    // Defensive window rule on a directly populated frame (the parser rejects these).
    CCFrame invalid = list(45, 30);
    invalid.ringFirst = 0;   // index 30 is outside [0, 20)
    cc_ring_target(invalid, 0, 0, CC_FLASH_NONE, cells);
    bool white = true;
    for (int k = 0; k < CC_RING_LEDS; ++k) if (cells[k].level && cells[k].rgb != CCLed::white) white = false;
    require(white && litCells(cells) == 20, "invalid first: host window, relative colours dropped");
    CCFrame longColors = list(9, 2);
    longColors.ringColorCount = 10;
    cc_ring_target(longColors, 0, 0, CC_FLASH_NONE, cells);
    require(cells[slotOf(0, 9)].rgb == CCLed::white, "a colour list longer than the window is dropped");
    CCFrame loading = list(11, 10, 10);
    loading.activity = CC_LOADING;
    cursor = cc_ring_target(loading, 0, 260, CC_FLASH_NONE, cells);
    require(cursor == 0 && litCells(cells) == 1 && cells[0].level == CCLed::L1, "loading draws only segment 0");
}

void helperChecks() {
    require(cc_led_ease(0, 260) == 0 && cc_led_ease(260, 260) == 255 && cc_led_ease(1000, 260) == 255, "ease ends");
    require(cc_led_ease(16, 260) == 65, "ease(16, 260) = LUT[0] + 67 * 256 / 260 = 65");
    require(cc_led_ease(65, 260) == CCLed::easeLut[4], "ease at an exact 1/16 step is the LUT entry");
    require(cc_led_ease(130, 260) == CCLed::easeLut[8], "ease at the midpoint is LUT[8] = 245");
    uint8_t previous = 0;
    for (uint32_t t = 0; t <= 260; ++t) {
        require(cc_led_ease(t, 260) >= previous, "ease is monotone");
        previous = cc_led_ease(t, 260);
    }
    require(cc_led_toward(0x102030, 0x0A0B0C, 128) == 0x0D161E, "toward truncates toward zero");
    require(cc_led_toward(0xFFFFFF, 0, 255) == 0 && cc_led_toward(0, 0xFFFFFF, 0) == 0, "toward ends");
    require(cc_led_drive(0xFFFFFF, CCLed::L1) == 0x0F0F0F && cc_led_drive(CCLed::green, CCLed::L4) == 0x38B460,
            "drive = (c * level + 127) / 255");
    const uint32_t pendingTimes[] = {0, 259, 260, 519, 520, 2859, 2860, 2999, 3000, 3120, 1000000};
    const uint8_t pendingLevels[] = {102, 102, 15, 15, 102, 102, 15, 15, 15, 15, 15};
    for (int k = 0; k < 11; ++k)
        require(cc_led_pending_level(pendingTimes[k]) == pendingLevels[k], "pending phase table at " + num(pendingTimes[k]));
    const uint32_t loadingTimes[] = {0, 259, 260, 520, 2860, 3120, 5200, 5460};
    const uint8_t loadingLevels[] = {46, 46, 15, 46, 15, 46, 46, 15};
    for (int k = 0; k < 8; ++k)
        require(cc_led_loading_level(loadingTimes[k]) == loadingLevels[k], "loading phase table at " + num(loadingTimes[k]));
    require(CCLed::levels[0] == 0 && CCLed::levels[1] == 15 && CCLed::levels[2] == 46 && CCLed::levels[3] == 102 &&
            CCLed::levels[4] == 204 && CCLed::shoulder == 74, "levels 0/15/46/102/204, LS 74");
    require(CCLed::pulseMs == 260 && CCLed::pendingHoldMs == 3000 && CCLed::decayMs == 260 &&
            CCLed::buttonFadeMs == 220 && CCLed::flashOkMs == 650 && CCLed::flashErrMs == 900, "timings");
}

void buttonChecks() {
    CCFrame f = list(9, 4);
    struct Row { uint8_t slot, icon; bool enabled; uint32_t rgb; uint8_t level; };
    const Row rows[] = {
        {0, CC_ICON_NONE, true, 0, 0}, {3, CC_ICON_NONE, true, 0, 0},
        {0, CC_ICON_CANCEL, true, CCLed::red, CCLed::L2}, {0, CC_ICON_CANCEL, false, CCLed::white, CCLed::L1},
        {3, CC_ICON_PLAY, true, CCLed::green, CCLed::L3}, {3, CC_ICON_PREV, true, CCLed::green, CCLed::L3},
        {3, CC_ICON_NEXT, true, CCLed::green, CCLed::L3}, {3, CC_ICON_SWITCH, true, CCLed::green, CCLed::L3},
        {3, CC_ICON_PLAY, false, CCLed::white, CCLed::L1}, {3, CC_ICON_MORE, true, CCLed::white, CCLed::L2},
        {3, CC_ICON_TRACKS, true, CCLed::white, CCLed::L2}, {0, CC_ICON_PLAY, true, CCLed::white, CCLed::L2},
        {1, CC_ICON_CANCEL, true, CCLed::white, CCLed::L2}, {2, CC_ICON_WIN, true, CCLed::white, CCLed::L2},
    };
    for (const Row& row : rows) {
        CCFrame g = f;
        g.buttons[row.slot].icon = row.icon;
        g.buttons[row.slot].iconSent = true;
        g.buttons[row.slot].enabled = row.enabled;
        const CCLedCell light = cc_button_light(g, row.slot);
        require(light.rgb == row.rgb && light.level == row.level,
                "tone table slot " + num(row.slot) + " icon " + num(row.icon) + (row.enabled ? " on" : " off"));
    }
    uint32_t out[4];
    f.buttons[1].enabled = false;
    cc_render_buttons(f, 0x0F, out);
    require(out[0] != cc_led_drive(CCLed::white, CCLed::L2) && out[1] == cc_led_drive(CCLed::white, CCLed::L1),
            "press highlights enabled buttons only");
}

// The V4 model's tones are frozen (PRESENTATION_V4 5.9, = presentation.button_tone and cc5.3's
// cc_button_tone): cc_button_tone_v4 ignores every presentation-5 input -- `lit`, `color`, the
// Home paused-Play go row and the v5 icon tokens -- while cc_button_tone (PRESENTATION_V5 5.2)
// derives on / off / liked / Home go from them. The v4 lights and the press highlight follow v4.
void v4ToneChecks() {
    struct Row {
        uint8_t layout, slot, icon, lit;
        uint32_t color;
        bool enabled;
        uint8_t v4, v5;
    };
    const Row rows[] = {
        {CC_LAYOUT_NOW_PLAYING, 0, CC_ICON_PLAY, CC_LIT_NONE, 0, true, CC_TONE_NAV, CC_TONE_GO},    // paused Home Play
        {CC_LAYOUT_IDLE, 0, CC_ICON_PLAY, CC_LIT_NONE, 0, true, CC_TONE_NAV, CC_TONE_GO},
        {CC_LAYOUT_RECENT, 0, CC_ICON_PLAY, CC_LIT_NONE, 0, true, CC_TONE_NAV, CC_TONE_NAV},
        {CC_LAYOUT_UPNEXT, 2, CC_ICON_HEART, CC_LIT_ON, 0, true, CC_TONE_NAV, CC_TONE_LIKED},      // [r2.2] liked
        {CC_LAYOUT_EXPLORER, 1, CC_ICON_CLOCK, CC_LIT_ON, 0, true, CC_TONE_NAV, CC_TONE_ON},
        {CC_LAYOUT_EXPLORER, 2, CC_ICON_PLAYLISTS, CC_LIT_OFF, 0, true, CC_TONE_NAV, CC_TONE_OFF},
        {CC_LAYOUT_WINDOWS, 1, CC_ICON_SNAPLEFT, CC_LIT_ON, 0x2D7FF9, true, CC_TONE_NAV, CC_TONE_ON},
        {CC_LAYOUT_TRACKS, 3, CC_ICON_NEXT, CC_LIT_OFF, 0, true, CC_TONE_GO, CC_TONE_OFF},
        {CC_LAYOUT_TRACKS, 3, CC_ICON_NEXT, CC_LIT_ON, 0, false, CC_TONE_DIM, CC_TONE_DIM},
        {CC_LAYOUT_RECENT, 0, CC_ICON_CANCEL, CC_LIT_ON, 0, true, CC_TONE_STOP, CC_TONE_STOP},
        {CC_LAYOUT_SEEK, 1, CC_ICON_SEEK, CC_LIT_NONE, 0, true, CC_TONE_NAV, CC_TONE_NAV},
        {CC_LAYOUT_UPNEXT, 3, CC_ICON_NONE, CC_LIT_ON, 0, true, CC_TONE_NONE, CC_TONE_NONE},
    };
    for (const Row& row : rows) {
        CCFrame g = list(9, 4);
        g.layoutId = row.layout;
        g.buttons[row.slot].icon = row.icon;
        g.buttons[row.slot].iconSent = true;
        g.buttons[row.slot].enabled = row.enabled;
        g.buttons[row.slot].lit = row.lit;
        g.buttons[row.slot].color = row.color;
        const std::string where = "v4 tone layout " + num(row.layout) + " slot " + num(row.slot) + " icon " +
                                  num(row.icon) + " lit " + num(row.lit);
        require(cc_button_tone_v4(g, row.slot) == row.v4, where + ": v4");
        require(cc_button_tone(g, row.slot) == row.v5, where + ": v5 (the LCD's table, unchanged)");
        const CCLedCell light = cc_button_light(g, row.slot);
        const CCLedCell want = row.v4 == CC_TONE_DIM ? CCLedCell{CCLed::white, CCLed::L1} :
                               row.v4 == CC_TONE_STOP ? CCLedCell{CCLed::red, CCLed::L2} :
                               row.v4 == CC_TONE_GO ? CCLedCell{CCLed::green, CCLed::L3} :
                               row.v4 == CC_TONE_NAV ? CCLedCell{CCLed::white, CCLed::L2} : CCLedCell{0, CCLed::L0};
        require(light.rgb == want.rgb && light.level == want.level, where + ": v4 light");
        uint32_t pressed[4], idle[4];
        cc_render_buttons(g, static_cast<uint8_t>(1u << row.slot), pressed);
        cc_render_buttons(g, 0, idle);
        const bool pressable = row.v4 == CC_TONE_NAV || row.v4 == CC_TONE_GO || row.v4 == CC_TONE_STOP;
        require((pressed[row.slot] != idle[row.slot]) == pressable, where + ": v4 press highlight");
        require(idle[row.slot] == cc_led_drive(want.rgb, want.level), where + ": stateless v4 drive");
    }
    // A slot beyond the four buttons is none in both tables.
    const CCFrame g = list(9, 4);
    require(cc_button_tone_v4(g, 4) == CC_TONE_NONE, "v4 tone slot 4 is none");
}

void rendererChecks() {
    // Seeding: the first frame after construction or reset never flashes.
    CCLightRenderer renderer;
    uint32_t ring[CC_RING_LEDS], buttons[4];
    CCFrame f = list(9, 4);
    f.feedbackPresent = true;
    f.feedbackKind = CC_FEEDBACK_ERR;
    f.feedbackSeq = 9;
    renderer.render(f, 1, 0, 0, ring, buttons);
    require(renderer.flash() == CC_FLASH_NONE && renderer.lastSeq() == 9, "construction seeds lastSeq without a flash");
    f.feedbackSeq = 10;
    renderer.render(f, 2, 10, 0, ring, buttons);
    require(renderer.flash() == CC_FLASH_ERR, "a new seq flashes on another control id");
    require(ring[59] == cc_led_drive(CCLed::red, CCLed::L3) && ring[0] == ring[59] && ring[1] == ring[59],
            "err flash is red L3 on cursor-1..cursor+1");
    renderer.reset();
    f.feedbackSeq = 11;
    renderer.render(f, 2, 20, 0, ring, buttons);
    require(renderer.flash() == CC_FLASH_NONE && renderer.lastSeq() == 11 && ring[0] == cc_led_drive(accentOf(4), CCLed::L3),
            "reset: snap and seed without a flash");
    renderer.render(f, 2, 20 + 899, 0, ring, buttons);
    require(renderer.flash() == CC_FLASH_NONE, "no flash after reset seeding");
    // Post-cap diagnostics (informational): FastLED's global cap 51 without dithering.
    std::printf("post-cap (x51/255, floor, no dither) of the L1 palette:");
    const uint32_t palette[5] = {CCLed::white, CCLed::green, CCLed::red, CCLed::amber, CCLed::volumeRed};
    const char* names[5] = {"W", "G", "R", "AMBER", "VRED"};
    for (int k = 0; k < 5; ++k) {
        const uint32_t drive = cc_led_drive(palette[k], CCLed::L1);
        const uint32_t cap = ((((drive >> 16) & 255) * 51 / 255) << 16) | ((((drive >> 8) & 255) * 51 / 255) << 8) |
                             ((drive & 255) * 51 / 255);
        std::printf(" %s %s->%s", names[k], hex(drive).c_str(), hex(cap).c_str());
    }
    // FastLED.show() switches temporal dithering off for every frame below 100 fps, and the
    // HMI task shows at most every 16 ms, so the knob applies no temporal dithering (cc4
    // through 1.0.0-cc5.2; the cc5.2 transport keeps FastLED.show() and PixelController).
    std::printf(" (no temporal dithering on the knob: FastLED disables it below 100 fps)\n");
}
} // namespace

int main(int argc, char** argv) {
    Parity parity = {0, 0, 0, 0};
    if (argc > 1) runSequences(argv[1], argc > 2 ? argv[2] : nullptr, parity);
    const long long parityChecks = checks;
    physicalChecks();
    volumeChecks();
    listChecks();
    helperChecks();
    buttonChecks();
    v4ToneChecks();
    rendererChecks();
    std::printf("parity: %d case(s), %d step(s), %d frame(s) parsed, %lld value(s) compared\n",
                parity.cases, parity.steps, parity.frames, parity.values);
    std::printf("direct: %lld assertion(s)\n", checks - parityChecks);
    if (failures) {
        std::printf("FAIL: %d of %lld check(s) failed\n", failures, checks);
        return 1;
    }
    std::printf("PASS: %lld light-renderer check(s)\n", checks);
    return 0;
}
