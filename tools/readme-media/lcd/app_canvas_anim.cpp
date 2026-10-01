// app-canvas-anim: renders a scripted drive of the knob firmware's Onshape app canvas (CCAppCanvas,
// cc_app_canvas.cpp and the cc_app_* drawing units; Karl Malota's UI, adapted with permission) on a fake
// millisecond tick and writes one 240x240 RGB888 raster per output frame.
//
// Usage: app-canvas-anim <script.json> <out.rgb>
//
// script.json:
//   { "fps": 30, "duration_ms": 9000, "start_ms": 0, "min_frame_ms": 12,
//     "steps": [ { "t": <ms>, "line": "<whole {\"frame\":...} wire line>"?, "angle": <int32, 1e-4 rad>?,
//                  "buttons": <mask, bit n = physical button n held>? }, ... ] }
//
// The drive is the LCD thread's, as work/lcd-preview/app_canvas_tests.cpp scripts it: a pass every
// millisecond; between two steps the angle moves linearly and the buttons hold; a step that carries a
// `line` goes through ArduinoJson and cc_parse_frame() like the COM thread's, its `app` object entering
// the canvas (first line) or updating it (later lines); step() runs every pass and draws into the canvas's
// own RGB565 frame only when the firmware's pacing says so (min_frame_ms = CC_LCD_PERIOD_MS, 12 on the F
// binary), so between draws the buffer holds what the panel shows. After start_ms the buffer is captured
// on the first ms at or after k * 1000 / fps (the knob_anim.cpp rule). Headless: no window, no USB.
//
// README_NO_LOGO is a CMake-level source substitution (lcd/CMakeLists.txt compiles the generated
// lcd/app_icons_nologo.c in place of cc_app_icons.c, whose icon arrays are const); this file only reports it.
#include <ArduinoJson.h>
#include "cc_frame_parse.h"
#include "cc_presentation.h"
#include "cc_app_canvas.h"

#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr int W = 240, H = 240;
std::vector<uint16_t> g_frame(static_cast<size_t>(W) * H);
ccui::PlasmaTables g_tables;

struct Step {
    uint32_t t = 0;
    bool hasLine = false, hasAngle = false, hasButtons = false;
    CCAppState app;
    int32_t angle = 0;
    uint8_t buttons = 0;
};

std::string readText(const char* path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error(std::string("cannot read ") + path);
    return std::string((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}

bool parseLine(const std::string& line, CCFrame& frame) {
    JsonDocument doc;
    if (deserializeJson(doc, line)) return false;
    return cc_parse_frame(doc["frame"], frame);
}
} // namespace

int main(int argc, char** argv) try {
    if (argc < 3) {
        std::fprintf(stderr, "usage: app-canvas-anim <script.json> <out.rgb>\n");
        return 2;
    }
    const std::string text = readText(argv[1]);
    JsonDocument script;
    if (DeserializationError e = deserializeJson(script, text))
        throw std::runtime_error(std::string("script: ") + e.c_str());
    const uint32_t fps = script["fps"] | 30u;
    const uint32_t duration = script["duration_ms"] | 3000u;
    const uint32_t start = script["start_ms"] | 0u;
    const uint32_t minFrameMs = script["min_frame_ms"] | 12u;

    std::vector<Step> steps;
    static CCFrame frame;
    for (JsonObjectConst s : script["steps"].as<JsonArrayConst>()) {
        Step st;
        st.t = s["t"] | 0u;
        if (!steps.empty() && st.t < steps.back().t) throw std::runtime_error("steps must be in time order");
        if (s["line"].is<const char*>()) {
            if (!parseLine(s["line"].as<std::string>(), frame) || frame.app.id == 0)
                throw std::runtime_error("step at " + std::to_string(st.t) +
                                         " ms: the frame line was rejected or has no app");
            st.hasLine = true;
            st.app = frame.app;
        }
        if (s["angle"].is<int>()) { st.hasAngle = true; st.angle = s["angle"].as<int32_t>(); }
        if (s["buttons"].is<unsigned>()) {
            st.hasButtons = true;
            st.buttons = static_cast<uint8_t>(s["buttons"].as<unsigned>());
        }
        steps.push_back(st);
    }

    FILE* out = nullptr;
    fopen_s(&out, argv[2], "wb");
    if (!out) throw std::runtime_error(std::string("cannot create ") + argv[2]);

    ccui::plasma_init(g_tables);
    CCAppCanvas canvas;
    canvas.begin(g_frame.data(), &g_tables, minFrameMs);
    bool entered = false;
    int32_t angle = 0;          // the angle at the last step (the interpolation start)
    uint8_t buttons = 0;
    uint32_t stepT = 0;         // time of the last step
    size_t next = 0;
    std::vector<uint8_t> rgb(static_cast<size_t>(W) * H * 3);
    uint32_t frames = 0, draws = 0;
    const uint32_t end = start + duration;
    for (uint32_t now = 0; now <= end; ++now) {
        CCAppInputs in;
        in.nowMs = now;
        if (next < steps.size() && steps[next].t <= now) {
            // The step's own pass (several steps at one ms apply in order; one pass follows the last).
            while (next < steps.size() && steps[next].t <= now) {
                const Step& s = steps[next++];
                if (s.hasAngle) angle = s.angle;
                if (s.hasButtons) buttons = s.buttons;
                in.angle = angle;
                in.buttons = buttons;
                if (s.hasLine) {
                    if (!entered) { canvas.enter(s.app, in); entered = true; }
                    else canvas.update(s.app, now);
                }
            }
            stepT = now;
        } else if (next < steps.size() && steps[next].hasAngle) {
            // Between two steps the angle moves linearly toward the next step's angle (the harness rule).
            const Step& s = steps[next];
            in.angle = angle + static_cast<int32_t>(static_cast<int64_t>(s.angle - angle) * (now - stepT) / (s.t - stepT));
        } else {
            in.angle = angle;
        }
        in.buttons = buttons;
        if (entered && canvas.step(in)) ++draws;
        if (now >= start) {
            const uint64_t rel = now - start;
            if (rel * fps >= static_cast<uint64_t>(frames) * 1000u && rel < duration) {
                for (size_t i = 0; i < g_frame.size(); ++i) {
                    const uint16_t c = g_frame[i];
                    rgb[3 * i] = static_cast<uint8_t>(((c >> 11) & 31) * 255 / 31);
                    rgb[3 * i + 1] = static_cast<uint8_t>(((c >> 5) & 63) * 255 / 63);
                    rgb[3 * i + 2] = static_cast<uint8_t>((c & 31) * 255 / 31);
                }
                std::fwrite(rgb.data(), 1, rgb.size(), out);
                ++frames;
            }
        }
    }
    std::fclose(out);
#ifdef README_NO_LOGO
    const char* logo = "no-logo badge";
#else
    const char* logo = "firmware icon";
#endif
    std::printf("app-canvas-anim: %u frames (%u fps, %u ms, %u canvas draws, %s)\n", frames, fps, duration, draws, logo);
    return 0;
} catch (const std::exception& e) {
    std::fprintf(stderr, "app-canvas-anim: %s\n", e.what());
    return 1;
}
