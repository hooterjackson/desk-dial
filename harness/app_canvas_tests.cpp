// A2 app canvas harness (1.0.0-cc5.6). Built by app_canvas_tests.py with MSVC /W4 /WX together with the
// unchanged firmware units: cc_frame_parse.cpp (the `app` object), cc_app_canvas.cpp, cc_app_gfx.cpp,
// cc_app_fonts.cpp, cc_app_shape.cpp, cc_app_cards.cpp, cc_app_screens.cpp and the C data cc_app_onshape.c /
// cc_app_icons.c.
//
// Input (argv[1]): a JSON file written by app_canvas_tests.py:
//   {"parse": [{"name", "line"}...], "render": [{"name", "steps": [{"t", "line"?, "angle", "buttons"}...]}...]}
// Each `line` is a whole {"frame":...} wire line, parsed with ArduinoJson and cc_parse_frame() exactly as the
// COM thread does. Output (stdout), one JSON object per line:
//   parse:  {"kind":"parse","name","accept","app":{...stored CCAppState...}}
//   render: {"kind":"render","name","view","frames","fills","drawUs","ppm","guard","snaps"} and argv[2]/<name>.ppm
//           (240 x 240, the RGB565 buffer expanded to 8 bits per channel) plus argv[2]/<name>.rgb565 (the raw
//           buffer, little-endian: the goldens hash it). A step with "snap": true also dumps the buffer as it is
//           after that step's pass, as <name>@<t>.ppm / .rgb565 (mid-animation goldens). "guard": the guard
//           bands around the canvas are intact (no write outside the 240 x 240 buffer).
// The render loop is the LCD thread's: a pass every millisecond between two scripted steps (the angle moves
// linearly), CCAppCanvas::update() whenever a step carries a new frame, step() every pass (none for "skip").
//
// App profiles (plan section 6, S1 FW-B): the canvas takes its profile from the store (cc_app_store_acquire /
// _release). This harness serves it: the built-in Onshape for ("onshape", 0), or -- when a case or a step says
// "profile": "<fixture>" (app_canvas_fixtures.c) -- that fixture for the frame's id, "none" = not loaded (the
// Loading screen). Every acquire that returned a profile must be released within the same pass: "leases" reports
// the acquires and releases of the case, "leaked" any pass that ended holding one.
#include <ArduinoJson.h>
#include "cc_frame_parse.h"
#include "cc_presentation.h"
#include "cc_app_canvas.h"
#include "cc_app_profile.h"

#include <chrono>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

extern "C" {
void app_canvas_fixtures_init(void);
const cc_app_profile_t* app_canvas_fixture(const char* name);
}

namespace {
// The harness's store (the stand-in for FW-A's cc_app_store until it lands on the branch).
bool g_serve_fixture = false;                 // a case / step chose what the store holds
const cc_app_profile_t* g_served = nullptr;   // ... that fixture, or nullptr: nothing loaded
uint32_t g_acquired = 0, g_released = 0;
} // namespace

extern "C" const cc_app_profile_t* cc_app_store_acquire(const char* id, uint32_t crc) {
    const cc_app_profile_t* p = nullptr;
    if (g_serve_fixture) p = g_served;
    else if (id != nullptr && std::strcmp(id, "onshape") == 0 && crc == 0) p = &cc_app_profile_onshape;
    if (p != nullptr) ++g_acquired;
    return p;
}

extern "C" void cc_app_store_release(const cc_app_profile_t* p) {
    if (p != nullptr) ++g_released;
}

namespace {
// The canvas with a guard band on each side: a write outside the 240 x 240 buffer shows up as a changed guard.
constexpr size_t kGuard = 4096;
constexpr uint16_t kGuardWord = 0xA55A;
std::vector<uint16_t> g_mem(240 * 240 + 2 * kGuard, kGuardWord);
uint16_t* const g_frame = g_mem.data() + kGuard;

bool guard_intact() {
    for (size_t i = 0; i < kGuard; i++)
        if (g_mem[i] != kGuardWord || g_mem[kGuard + 240 * 240 + i] != kGuardWord) return false;
    return true;
}
ccui::PlasmaTables g_tables;

bool parse_line(const std::string& line, CCFrame& frame) {
    JsonDocument doc;
    if (deserializeJson(doc, line)) return false;
    return cc_parse_frame(doc["frame"], frame);
}

void write_app(const CCAppState& a) {
    // App profiles: the id is text (a cc5.6 CCAppState's index 1 reads "onshape"), with the frame's crc.
    const char* id = cc_app_id_text(a.id);
    std::printf("{\"id\":\"%s\",\"crc\":%u,\"slot\":%u,\"refused\":%s,\"flash\":%u,\"wheel\":%s,\"wheelRing\":%u,"
                "\"wheelIndex\":%u,\"param\":%s,\"paramRing\":%u,\"paramIndex\":%u,\"paramTyped\":%s,\"paramStep\":%u,"
                "\"paramValue\":%d,\"paramBump\":%u,\"echoSeq\":%u,\"echoRing\":%u,\"echoIndex\":%u}",
                id ? id : "", static_cast<unsigned>(cc_app_state_crc(a)), a.slot, a.refused ? "true" : "false",
                static_cast<unsigned>(a.flash), a.wheel ? "true" : "false", a.wheelRing, a.wheelIndex,
                a.param ? "true" : "false", a.paramRing, a.paramIndex, a.paramTyped ? "true" : "false", a.paramStep,
                static_cast<int>(a.paramValue), static_cast<unsigned>(a.paramBump), static_cast<unsigned>(a.echoSeq),
                a.echoRing, a.echoIndex);
}

bool write_ppm(const std::string& path) {
    std::ofstream out(path, std::ios::binary);
    if (!out) return false;
    out << "P6\n240 240\n255\n";
    for (int i = 0; i < 240 * 240; i++) {
        const uint16_t v = g_frame[i];
        const unsigned r = (v >> 11) & 0x1F, g = (v >> 5) & 0x3F, b = v & 0x1F;
        const char px[3] = {static_cast<char>((r << 3) | (r >> 2)), static_cast<char>((g << 2) | (g >> 4)),
                            static_cast<char>((b << 3) | (b >> 2))};
        out.write(px, 3);
    }
    return static_cast<bool>(out);
}

bool write_raw(const std::string& path) {
    std::ofstream out(path, std::ios::binary);
    if (!out) return false;
    for (int i = 0; i < 240 * 240; i++) {
        const char px[2] = {static_cast<char>(g_frame[i] & 0xFF), static_cast<char>(g_frame[i] >> 8)};
        out.write(px, 2);
    }
    return static_cast<bool>(out);
}

bool dump(const std::string& base) { return write_ppm(base + ".ppm") && write_raw(base + ".rgb565"); }

const char* view_name(CCAppView v) {
    switch (v) {
        case CC_APP_VIEW_WHEEL: return "wheel";
        case CC_APP_VIEW_PARAM: return "param";
        case CC_APP_VIEW_ECHO: return "echo";
        case CC_APP_VIEW_IDLE: return "idle";
        case CC_APP_VIEW_LOADING: return "loading";
        default: return "main";
    }
}
} // namespace

int main(int argc, char** argv) {
    if (argc < 3) {
        std::fprintf(stderr, "usage: app_canvas_tests <cases.json> <out-dir>\n");
        return 2;
    }
    std::ifstream in(argv[1], std::ios::binary);
    std::stringstream text;
    text << in.rdbuf();
    JsonDocument cases;
    if (deserializeJson(cases, text.str())) {
        std::fprintf(stderr, "cases: invalid JSON\n");
        return 2;
    }
    const std::string out_dir = argv[2];
    static CCFrame frame;

    for (JsonObjectConst c : cases["parse"].as<JsonArrayConst>()) {
        const bool accept = parse_line(c["line"].as<std::string>(), frame);
        std::printf("{\"kind\":\"parse\",\"name\":\"%s\",\"accept\":%s,\"app\":", c["name"].as<const char*>(),
                    accept ? "true" : "false");
        if (accept) write_app(frame.app); else std::printf("null");
        // DD-SEC-001: outside "app" (device.app_parse does not store it), so the parity check stays exact.
        std::printf(",\"refusedFocus\":%s}\n", accept && frame.app.refusedFocus ? "true" : "false");
    }

    ccui::plasma_init(g_tables);
    app_canvas_fixtures_init();
    for (JsonObjectConst c : cases["render"].as<JsonArrayConst>()) {
        const std::string name = c["name"].as<std::string>();
        std::fill(g_mem.begin(), g_mem.end(), kGuardWord);
        std::fill(g_frame, g_frame + 240 * 240, static_cast<uint16_t>(0));
        CCAppCanvas canvas;
        canvas.begin(g_frame, &g_tables, c["minFrameMs"] | 16u);
        std::string snaps;
        bool entered = false, leaked = false;
        g_acquired = g_released = 0;
        g_serve_fixture = false;
        g_served = nullptr;
        // "profile": the store holds this fixture (or "none": nothing) for the frame's id, for the whole case.
        auto serve = [](JsonVariantConst v) -> bool {
            if (v.isNull()) return true;
            const char* fixture = v.as<const char*>();
            g_serve_fixture = true;
            g_served = std::strcmp(fixture, "none") == 0 ? nullptr : app_canvas_fixture(fixture);
            return g_served != nullptr || std::strcmp(fixture, "none") == 0;
        };
        if (!serve(c["profile"])) {
            std::fprintf(stderr, "%s: unknown fixture\n", name.c_str());
            return 1;
        }
        uint32_t frames = 0, fills = 0, drawUsMax = 0, lastFills = 0, lastCalls = 0;
        uint32_t t = 0;
        int32_t angle = 0;
        uint8_t buttons = 0;
        bool bad = false;
        for (JsonObjectConst s : c["steps"].as<JsonArrayConst>()) {
            const uint32_t to = s["t"] | t;
            const int32_t toAngle = s["angle"] | angle;
            const uint8_t toButtons = static_cast<uint8_t>(s["buttons"] | static_cast<unsigned>(buttons));
            // Passes up to the step (1 ms apart, the angle moving linearly), then the step's own pass. A step with
            // "skip": true jumps the clock without the passes in between (uptime-wrap cases: 2^31 ms in one step).
            const bool skip = s["skip"] | false;
            for (uint32_t now = t + 1; entered && !skip && now < to; ++now) {
                CCAppInputs inputs;
                inputs.nowMs = now;
                // FW-BUG-032: the angle word wraps modulo 2^32: the step and the sum in unsigned arithmetic.
                const int32_t span = static_cast<int32_t>(static_cast<uint32_t>(toAngle) - static_cast<uint32_t>(angle));
                const int32_t part = static_cast<int32_t>(static_cast<int64_t>(span) * (now - t) / (to - t));
                inputs.angle = static_cast<int32_t>(static_cast<uint32_t>(angle) + static_cast<uint32_t>(part));
                inputs.buttons = buttons;
                ccui::take_fill_count();
                ccui::take_fill_calls();
                const auto t0 = std::chrono::steady_clock::now();
                const bool drew = canvas.step(inputs);
                leaked = leaked || g_acquired != g_released;
                if (drew) {
                    const auto us = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - t0).count();
                    ++frames;
                    lastFills = ccui::take_fill_count();
                    lastCalls = ccui::take_fill_calls();
                    fills += lastFills;
                    if (static_cast<uint32_t>(us) > drawUsMax) drawUsMax = static_cast<uint32_t>(us);
                }
            }
            t = to; angle = toAngle; buttons = toButtons;
            CCAppInputs inputs;
            inputs.nowMs = t;
            inputs.angle = angle;
            inputs.buttons = buttons;
            if (!serve(s["profile"])) {   // a step may change what the store holds (Loading -> loaded)
                std::fprintf(stderr, "%s: unknown fixture\n", name.c_str());
                return 1;
            }
            if (s.containsKey("line")) {
                if (!parse_line(s["line"].as<std::string>(), frame) || !cc_app_state_present(frame.app)) {
                    std::fprintf(stderr, "%s: step at %u ms: the frame line was rejected or has no app\n", name.c_str(), t);
                    bad = true;
                    break;
                }
                if (!entered) { canvas.enter(frame.app, inputs); entered = true; }
                else canvas.update(frame.app, t);
            }
            ccui::take_fill_count();
            ccui::take_fill_calls();
            const bool drew = entered && canvas.step(inputs);
            leaked = leaked || g_acquired != g_released;
            if (drew) {
                ++frames;
                lastFills = ccui::take_fill_count();
                lastCalls = ccui::take_fill_calls();
                fills += lastFills;
            }
            if (s["snap"] | false) {
                const std::string snap = name + "@" + std::to_string(t);
                if (!dump(out_dir + "/" + snap)) {
                    std::fprintf(stderr, "cannot write %s\n", snap.c_str());
                    return 1;
                }
                snaps += (snaps.empty() ? "\"" : ",\"") + snap + "\"";
            }
        }
        if (bad) return 1;
        if (!dump(out_dir + "/" + name)) {
            std::fprintf(stderr, "cannot write %s\n", name.c_str());
            return 1;
        }
        std::printf("{\"kind\":\"render\",\"name\":\"%s\",\"view\":\"%s\",\"frames\":%u,\"fills\":%u,\"lastFills\":%u,"
                    "\"lastCalls\":%u,\"drawUsMax\":%u,\"ppm\":\"%s.ppm\",\"guard\":%s,\"snaps\":[%s],"
                    "\"leases\":%u,\"leaked\":%s}\n",
                    name.c_str(), view_name(canvas.view()), frames, fills, lastFills, lastCalls, drawUsMax, name.c_str(),
                    guard_intact() ? "true" : "false", snaps.c_str(), g_acquired, leaked ? "true" : "false");
    }
    return 0;
}
