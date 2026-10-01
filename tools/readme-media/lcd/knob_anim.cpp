// knob-anim: renders a scripted sequence of host frames with the knob firmware's own LCD renderer
// (cc_display.cpp on LVGL 9.0.0, the firmware lv_conf.h, PARTIAL mode with the firmware's 11,520 B
// draw buffer), on a fake millisecond tick, and writes one 240x240 RGB888 raster per output frame.
//
// Usage: knob-anim <script.json> <out.rgb> [<png-dir>]
//
// script.json:
//   { "fps": 30, "duration_ms": 6000, "start_ms": 0,
//     "covers": { "<artKey>": "<path to 240 px baseline JPEG>" , ... },
//     "icons":  { "<iconKey>": "<path to 2048 B RGB565 LE 32x32>", ... },
//     "steps":  [ <step>, ... ] }
//
// A step is {"at": <fake ms>, ...} plus exactly one of (the r4 input moments mirror lcd_thread.cpp's
// render_host_frame, src/lcd_thread.cpp:716-720, and the harness's step kinds, work/lcd-preview/main.cpp):
//   "frame":   { ...wire frame (what the companion sends)... }    cc_display_render(); leaves the offline layer
//   "keys":    <bitmask of physical slots down, bit n = slot n>    cc_display_input(mask) now and on EVERY later
//                                                                 fake-ms pass until the next "keys" step
//                                                                 (M7 press squash, M10 hold fill on slot 3)
//   "wall":    +1 | -1                                             cc_display_wall(dir) once (M13 wall stretch)
//   "offline": true | false                                        true: cc_display_offline(native) on every pass
//                                                                 until a frame or "offline": false; "native": true
//                                                                 on the same step flags the first native input
//   "release": true                                                cc_display_release_media() (native handback)
//
// Frames go through the firmware parser cc_parse_frame() and cc_display_render(), exactly like
// lcd_thread on the knob; covers come from a store stand-in (every cover is "committed" from the
// start) and are decoded by the firmware's cc_jpeg.cpp. Output frames are sampled every 1000/fps ms
// after start_ms (an exact present at that tick). With <png-dir>, every sampled frame is also written
// there as <png-dir>/<index>.ppm (binary P6, zero-padded 5-digit index; no image library needed).
// Headless: no window, no USB, no network.
#include "lvgl.h"
#include <ArduinoJson.h>
#include "cc_display.h"
#include "cc_frame_parse.h"
#include "cc_jpeg.h"

#include <array>
#include <cstdio>
#include <cstring>
#include <deque>
#include <filesystem>
#include <fstream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace fs = std::filesystem;

static constexpr int W = 240, H = 240;
alignas(4) static unsigned char drawBuffer[W * H / 10 * 2];   // lcd_thread.cpp DRAW_BUF_SIZE
static std::array<uint16_t, W * H> framebuffer;
alignas(4) static uint8_t art240[2][CC_ART240_BYTES];
static uint32_t fakeNow = 0;
static lv_display_t* display = nullptr;
static std::map<std::string, std::vector<uint8_t>> media[2];

static uint32_t tickCb() { return fakeNow; }

static void flush(lv_display_t* disp, const lv_area_t* area, uint8_t* data) {
    const auto* src = reinterpret_cast<const uint16_t*>(data);
    for (int y = area->y1; y <= area->y2; ++y)
        for (int x = area->x1; x <= area->x2; ++x) {
            const uint16_t c = *src++;
            if (x >= 0 && x < W && y >= 0 && y < H) framebuffer[static_cast<size_t>(y) * W + x] = c;
        }
    lv_display_flush_ready(disp);
}

static bool adopt(uint8_t kind, const char* key, const uint8_t** data, uint32_t* bytes) {
    if (kind > CC_DISPLAY_MEDIA_ICON) return false;
    auto it = media[kind].find(key);
    if (it == media[kind].end()) return false;
    *data = it->second.data();
    *bytes = static_cast<uint32_t>(it->second.size());
    return true;
}
static void release(uint8_t) {}
static bool decode(const uint8_t* jpeg, uint32_t bytes, uint16_t* dst) { return cc_jpeg_decode_240(jpeg, bytes, dst); }

static std::vector<uint8_t> readFile(const fs::path& p) {
    std::ifstream in(p, std::ios::binary);
    if (!in) throw std::runtime_error("cannot read " + p.string());
    return std::vector<uint8_t>((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}

static void present() {
    lv_anim_refr_now();
    lv_obj_invalidate(lv_screen_active());
    lv_refr_now(display);
}

enum StepKind : uint8_t { STEP_FRAME, STEP_KEYS, STEP_WALL, STEP_OFFLINE, STEP_RELEASE };

struct Step {
    uint32_t at;
    StepKind kind;
    CCFrame frame;      // STEP_FRAME
    uint8_t keys;       // STEP_KEYS
    int8_t wall;        // STEP_WALL
    bool offline;       // STEP_OFFLINE: the layer goes up (true) or stops being driven (false)
    bool native;        // STEP_OFFLINE: the layer's first native input
};

static Step parseStep(JsonVariantConst s) {
    Step st = {};
    st.at = s["at"].as<uint32_t>();
    const std::string where = " at " + std::to_string(st.at);
    int kinds = 0;
    if (!s["frame"].isNull()) {
        ++kinds;
        st.kind = STEP_FRAME;
        if (!cc_parse_frame(s["frame"], st.frame)) throw std::runtime_error("frame rejected by cc_parse_frame" + where);
    }
    if (!s["keys"].isNull()) {
        ++kinds;
        st.kind = STEP_KEYS;
        const int keys = s["keys"].as<int>();
        if (keys < 0 || keys > 0x0F) throw std::runtime_error("keys must be a 4-bit mask" + where);
        st.keys = static_cast<uint8_t>(keys);
    }
    if (!s["wall"].isNull()) {
        ++kinds;
        st.kind = STEP_WALL;
        const int dir = s["wall"].as<int>();
        if (dir != 1 && dir != -1) throw std::runtime_error("wall must be +1 or -1" + where);
        st.wall = static_cast<int8_t>(dir);
    }
    if (!s["offline"].isNull()) {
        ++kinds;
        st.kind = STEP_OFFLINE;
        st.offline = s["offline"].as<bool>();
        st.native = s["native"] | false;
    }
    if (!s["release"].isNull()) {
        ++kinds;
        st.kind = STEP_RELEASE;
        if (!s["release"].as<bool>()) throw std::runtime_error("release must be true" + where);
    }
    if (kinds != 1) throw std::runtime_error("a step needs exactly one of frame / keys / wall / offline / release" + where);
    return st;
}

static void writePpm(const fs::path& p, const std::vector<uint8_t>& rgb) {
    FILE* f = nullptr;
    fopen_s(&f, p.string().c_str(), "wb");
    if (!f) throw std::runtime_error("cannot create " + p.string());
    std::fprintf(f, "P6\n%d %d\n255\n", W, H);
    std::fwrite(rgb.data(), 1, rgb.size(), f);
    std::fclose(f);
}

int main(int argc, char** argv) try {
    if (argc < 3) {
        std::fprintf(stderr, "usage: knob-anim <script.json> <out.rgb> [<png-dir>]\n");
        return 2;
    }
    const std::vector<uint8_t> text = readFile(argv[1]);
    JsonDocument script;
    if (DeserializationError e = deserializeJson(script, reinterpret_cast<const char*>(text.data()), text.size()))
        throw std::runtime_error(std::string("script: ") + e.c_str());
    const uint32_t fps = script["fps"] | 30u;
    const uint32_t duration = script["duration_ms"] | 3000u;
    const uint32_t start = script["start_ms"] | 0u;
    if (fps == 0) throw std::runtime_error("fps must be > 0");
    for (JsonPairConst kv : script["covers"].as<JsonObjectConst>())
        media[CC_DISPLAY_MEDIA_COVER][kv.key().c_str()] = readFile(kv.value().as<const char*>());
    for (JsonPairConst kv : script["icons"].as<JsonObjectConst>()) {
        auto bytes = readFile(kv.value().as<const char*>());
        if (bytes.size() != CC_ICON_BYTES) throw std::runtime_error("icon is not 32x32 RGB565");
        media[CC_DISPLAY_MEDIA_ICON][kv.key().c_str()] = std::move(bytes);
    }
    fs::path pngDir;
    if (argc >= 4) {
        pngDir = argv[3];
        fs::create_directories(pngDir);
    }

    lv_init();
    lv_tick_set_cb(tickCb);
    display = lv_display_create(W, H);
    lv_display_set_color_format(display, LV_COLOR_FORMAT_RGB565);
    lv_display_set_buffers(display, drawBuffer, nullptr, sizeof(drawBuffer), LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_flush_cb(display, flush);
    CCDisplayMedia lookups = {};
    lookups.adopt = adopt;
    lookups.release = release;
    lookups.decodeCover = decode;
    cc_display_set_media(lookups);
    lv_obj_t* screen = cc_display_create(art240[0], art240[1]);
    lv_screen_load(screen);

    std::deque<Step> steps;
    for (JsonVariantConst s : script["steps"].as<JsonArrayConst>()) steps.push_back(parseStep(s));
    for (size_t i = 1; i < steps.size(); ++i)
        if (steps[i].at < steps[i - 1].at) throw std::runtime_error("steps must be sorted by \"at\"");

    FILE* out = nullptr;
    fopen_s(&out, argv[2], "wb");
    if (!out) throw std::runtime_error(std::string("cannot create ") + argv[2]);
    std::vector<uint8_t> rgb(static_cast<size_t>(W) * H * 3);
    size_t next = 0;
    uint32_t frames = 0;
    // The per-pass input state, as lcd_thread's render_host_frame samples it every pass (lcd_thread.cpp:716-720):
    // the key mask goes to cc_display_input() on every pass (a changed mask is the edge the renderer acts on, and
    // the hold fill matures inside later calls); while the offline layer is up, cc_display_offline() runs instead
    // (the harness's advance(), work/lcd-preview/main.cpp:369-370).
    uint8_t keys = 0;
    bool offlineLive = false;
    bool offlineNative = false;
    const uint32_t end = start + duration;
    for (fakeNow = 0; fakeNow <= end; ++fakeNow) {
        while (next < steps.size() && steps[next].at <= fakeNow) {
            const Step& st = steps[next++];
            switch (st.kind) {
                case STEP_FRAME:
                    offlineLive = false;
                    cc_display_render(st.frame, nullptr);
                    break;
                case STEP_KEYS:
                    keys = st.keys;
                    break;
                case STEP_WALL:
                    cc_display_wall(st.wall);
                    break;
                case STEP_OFFLINE:
                    offlineLive = st.offline;
                    offlineNative = st.offline && st.native;
                    break;
                case STEP_RELEASE:
                    offlineLive = false;
                    cc_display_release_media();
                    break;
            }
        }
        if (offlineLive) cc_display_offline(offlineNative);
        else cc_display_input(keys);
        lv_timer_handler();
        if (fakeNow >= start) {
            const uint64_t rel = fakeNow - start;
            // A capture on the first tick at or after k * 1000 / fps.
            if (rel * fps >= static_cast<uint64_t>(frames) * 1000u && rel < duration) {
                present();
                for (size_t i = 0; i < framebuffer.size(); ++i) {
                    const uint16_t c = framebuffer[i];
                    rgb[3 * i] = static_cast<uint8_t>(((c >> 11) & 31) * 255 / 31);
                    rgb[3 * i + 1] = static_cast<uint8_t>(((c >> 5) & 63) * 255 / 63);
                    rgb[3 * i + 2] = static_cast<uint8_t>((c & 31) * 255 / 31);
                }
                std::fwrite(rgb.data(), 1, rgb.size(), out);
                if (!pngDir.empty()) {
                    char name[32];
                    std::snprintf(name, sizeof name, "%05u.ppm", frames);
                    writePpm(pngDir / name, rgb);
                }
                ++frames;
            }
        }
    }
    std::fclose(out);
    std::printf("knob-anim: %u frames (%u fps, %u ms)\n", frames, fps, duration);
    const CCDisplayStats& st = cc_display_stats();
    std::printf("knob-anim: stats renders=%u slides=%u presses=%u holdFills=%u landings=%u pops=%u walls=%u "
                "wallBounces=%u morphs=%u glides=%u\n",
                st.renders, st.slides, st.presses, st.holdFills, st.landings, st.pops, st.walls, st.wallBounces,
                st.morphs, st.glides);
    return 0;
} catch (const std::exception& e) {
    std::fprintf(stderr, "knob-anim: %s\n", e.what());
    return 1;
}
