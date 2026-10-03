// cc5.4 LCD harness (PRESENTATION_V5.md section 15.3, gate A4): the firmware's own renderer
// (src/cc_display.cpp), frame parser (src/cc_frame_parse.cpp), icons and generated fonts on the
// firmware lv_conf.h (LVGL 9.0.0, 80 KB heap, PARTIAL 11,520 B draw buffer).
//
// 1. Cases: every case of app/tests/fixtures/cc5_frames.json (presentation-4
//    wire frames, drawn with the v5 geometry: section 2.3), every input of tests/fixtures/
//    frames_v5.json that a cc5.4 parser accepts (every v5 layout, token and state), harness-only v4
//    and v5 frames, the artwork2 cases and the offline screen. Each frame goes through
//    cc_parse_frame(), is rendered twice -- an art-less twin (artKey cleared) and the real frame
//    with its cover -- settled on a fake tick, and captured with a layout dump (every object's
//    role, box, opacity, text lines, ink rows, text_opa of the shadow twins).
// 2. Timelines on a steppable fake LVGL tick (lv_tick_set_cb after lv_init): the fixture
//    sequences, the artwork2 timelines and the v5 ones (the section 8.7 flip table, text at rest,
//    ink crossfades, reduced motion, Seek digits, the offline screen, art show/hide, twin-fade
//    probes); each step is rendered at its time, its diagnostics recorded, and frames captured at
//    key times. A twin-fade probe also renders the fading layer at opacity 255 and hidden (the
//    group-composited reference of `twin_fade`).
// 3. R5 (section 12.5.7): a scripted fake decoder behind CCDisplayMedia::requestCover/pollCover/
//    cancelCover (per-request delay in 15 MCU bands; a cancel stops it at the next band and it
//    completes aborted, as the shipped cc_art_decode.cpp does with cc_jpeg.cpp's abort hook, 12.5.4
//    step 2) runs the art_async cases a-h; the harness re-renders the current frame when a decode
//    finishes, as lcd_thread does.
// 3b. cadence: lcdLateRefrs / lcdMaxGapMs (section 12.3) through cc_anim_cadence_poll() with binary
//    A's 16 ms period and a 1 ms loop over the v5 tweens, next to the flush-to-flush metric it
//    replaced; offline_input: cc_offline_input_update() (section 8.10 first native input).
// 4. copy: every knob string of cc54_copy.json rendered in its element (layout dumps only).
// 4b. Presentation 6 (PRESENTATION_V5.md section 19, Desk Dial r3 release 1): every accepted case of
//    fixtures/frames_v6.json (group "v6") and every screen of r3-handoff/r3_screens.json (group "r3",
//    cases/r3.<id>; r3_sheet.py builds r3-handoff/contact-sheet-r3.png from them).
// 5. vectors: the frames_v5.json shared vectors (mmss, accent_ink, the 5.2 tone table) through
//    cc_presentation.h, and an accent/sat grid for the Python parity check.
// 6. LVGL heap peak/fragmentation and the host-frame redraw latency.
// 4c. r4 motion (design_handoff_nano_d_r4 README 3.2, MOTION.md): timelines r4-moments / r4-reduced (M1-M15 with the
//    input moments driven through cc_display_input() and cc_display_wall(), as lcd_thread does every pass) and
//    r4-tour (the README section 8 motion tour on the r3 screens; r4_tour_sheet.py builds the review sheet).
// --one-buffer <out>: the artwork2 cases, timelines and handback with a single art buffer.
// The same main.cpp built with CC_DISPLAY_FULL_LAYERS=1 (lcd-preview-full, CMakeLists.txt) renders
// every animated layer at 240 x 240: cc54_report.py `v5_bounded` compares the two runs.
//
// Output: <out>/cases/*.ppm, <out>/timelines/<seq>/*.ppm, <out>/render-index.json,
// <out>/lvgl-heap.json. build.py converts the PPMs to PNG; cc54_report.py checks.
#include "lvgl.h"
#include <ArduinoJson.h>
#include "cc_art_decode.h"   // cc_art_decode_result(): the task's result mapping (header only)
#include "cc_display.h"
#include "cc_crumbs.h"      // FW-DES-001: the crumb masks for the fit oracle
#include "src/core/lv_global.h"   // FW-DES-003: the running lv_anim list (anims a render starts)
#include "cc_frame_parse.h"
#include "cc_icons.h"
#include "cc_icon_morph.h"
#include "fonts/cc_fonts.h"
#if NANOD_JPEG_FIRMWARE
#include "cc_jpeg.h"
#endif

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <deque>
#include <filesystem>
#include <fstream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#ifndef CC_DISPLAY_FULL_LAYERS
#define CC_DISPLAY_FULL_LAYERS 0
#endif
#ifndef CC_TEXT_TWINS
#define CC_TEXT_TWINS 1
#endif

namespace fs = std::filesystem;

static constexpr int WIDTH = 240, HEIGHT = 240;
// Same draw path as the knob: PARTIAL mode with a 1/10-screen buffer (lcd_thread.cpp
// DRAW_BUF_SIZE = 240*240/10*2 = 11,520 B).
alignas(4) static unsigned char draw_buffer[WIDTH * HEIGHT / 10 * 2];
static_assert(sizeof(draw_buffer) == 11520, "draw buffer must match the firmware");
// The panel stand-in: a full RGB565 frame outside the LVGL heap, filled by flush.
static std::array<uint16_t, WIDTH * HEIGHT> framebuffer;
// Caller-owned 240x240 RGB565 artwork buffers, front and back (PSRAM on the knob).
alignas(4) static uint8_t art240[2][CC_ART240_BYTES];
static std::map<std::string, std::vector<uint8_t>> artFixtures;

// ------------------------------------------------------ artwork2 stand-in --
#if !NANOD_JPEG_FIRMWARE
bool harness_jpeg_decode_240(const uint8_t* jpeg, uint32_t bytes, uint16_t* dst);  // jpeg_standin.cpp
#endif
static std::map<std::string, std::vector<uint8_t>> mediaFixtures[2];  // every artwork2 fixture, by name
struct MediaStandIn {
    std::map<std::string, std::vector<uint8_t>> committed[2];
    std::string displayed[2];
    uint32_t adopts[2] = {}, hits[2] = {}, releases[2] = {};
    uint32_t decodes = 0, decodeFailures = 0;
};
static MediaStandIn store;

static bool standInAdopt(uint8_t kind, const char* key, const uint8_t** data, uint32_t* bytes) {
    if (kind > CC_DISPLAY_MEDIA_ICON) return false;
    ++store.adopts[kind];
    const auto it = store.committed[kind].find(key);
    if (it == store.committed[kind].end()) {
        store.displayed[kind].clear();  // cc_media.h: a miss shows no media (displayed = -1)
        return false;
    }
    ++store.hits[kind];
    store.displayed[kind] = key;
    *data = it->second.data();
    *bytes = static_cast<uint32_t>(it->second.size());
    return true;
}

static void standInRelease(uint8_t kind) {
    if (kind > CC_DISPLAY_MEDIA_ICON) return;
    ++store.releases[kind];
    store.displayed[kind].clear();
}

static bool decodeCover240(const uint8_t* jpeg, uint32_t bytes, uint16_t* dst) {
#if NANOD_JPEG_FIRMWARE
    return cc_jpeg_decode_240(jpeg, bytes, dst);
#else
    return harness_jpeg_decode_240(jpeg, bytes, dst);
#endif
}

// Fake milliseconds one synchronous decode takes (Step::decodeMs): the knob's tick keeps running
// while the LCD thread decodes inside cc_display_render(), and no LVGL timer runs meanwhile.
static uint32_t fakeNow = 0;
static uint32_t decodeFakeMs = 0;

static bool standInDecode(const uint8_t* jpeg, uint32_t bytes, uint16_t* dst) {
    ++store.decodes;
    fakeNow += decodeFakeMs;
    const bool ok = decodeCover240(jpeg, bytes, dst);
    if (!ok) ++store.decodeFailures;
    return ok;
}

static void commitMedia(uint8_t kind, const std::string& name) {
    const auto it = mediaFixtures[kind].find(name);
    if (it == mediaFixtures[kind].end()) throw std::runtime_error("Unknown artwork2 fixture " + name);
    store.committed[kind][name] = it->second;
}

static void resetStore() {
    store.committed[0].clear();
    store.committed[1].clear();
}

static void dumpMedia(JsonObject o) {
    JsonObject m = o["media"].to<JsonObject>();
    const char* kinds[2] = {"cover", "icon"};
    for (int k = 0; k < 2; ++k) {
        if (store.displayed[k].empty()) m[kinds[k]] = nullptr;
        else m[kinds[k]] = store.displayed[k];
    }
}

// ------------------------------------------------------------ R5 fake --
// The decode task of section 12.5 as the firmware ships it (src/cc_art_decode.cpp with
// src/cc_jpeg.cpp's abort hook, 12.5.4 step 2, lead ruling R-f): one request at a time, a
// per-request delay on the fake tick, the result polled once. The delay is split into the 15 MCU
// bands of a 240 px 4:2:0 cover (rows of 16 px): band k starts at startedAt + k * delay / 15, and
// before it the decoder reads `cancel` (cc_jpeg_decode_240(jpeg, bytes, dst, &cancel) polls between
// MCU rows) and stops there with CC_JPEG_ABORTED once it is set; its part-written pixels are the
// caller's to discard. A decode that reaches its end writes its pixels and completes OK or FAILED.
// Either way the task's result is cc_art_decode_result(decoded, cancel) (cc_art_decode.h), the same
// mapping the firmware task uses: an abort stays aborted even after a spin back cleared `cancel`,
// and an OK with `cancel` set at the end is aborted (superseded during the last band). It writes
// only into the posted back buffer and checks that the front buffer never changes meanwhile.
constexpr uint32_t kFakeBands = 15;   // 240 / 16: MCU rows of a 4:2:0 cover (cc_jpeg.cpp poll points)
struct FakeDecoder {
    bool installed = false;
    bool busy = false, done = false, cancel = false;
    std::string key;
    std::vector<uint8_t> jpeg;
    uint16_t* dst = nullptr;
    int dstIndex = -1;
    uint32_t startedAt = 0;
    uint32_t polled = 0;          // bands whose poll has passed (0 .. kFakeBands)
    uint32_t delayMs = 120;
    uint8_t result = CC_DECODE_OK;
    uint32_t version = 0;
    uint32_t requests = 0, refused = 0, completions = 0, aborts = 0, failures = 0, frontWrites = 0;
    std::vector<uint8_t> front;  // the other buffer's bytes at the post
    std::string bufferKey[2];    // the key whose pixels the fake wrote into each buffer
    std::vector<std::string> events;
};
static FakeDecoder fake;

static void fakeEvent(const std::string& what) {
    fake.events.push_back(std::to_string(fakeNow) + " " + what);
}

static bool fakeRequest(const char* key, const uint8_t* jpeg, uint32_t bytes, uint16_t* dst) {
    if (fake.busy) { ++fake.refused; fakeEvent(std::string("refused ") + key); return false; }
    fake.busy = true;
    fake.done = false;
    fake.cancel = false;
    fake.key = key;
    fake.jpeg.assign(jpeg, jpeg + bytes);   // the request copies the payload (as lcd_thread does)
    fake.dst = dst;
    fake.dstIndex = reinterpret_cast<uint8_t*>(dst) == art240[0] ? 0 : 1;
    fake.bufferKey[fake.dstIndex].clear();
    const int other = 1 - fake.dstIndex;
    fake.front.assign(art240[other], art240[other] + CC_ART240_BYTES);
    fake.startedAt = fakeNow;
    fake.polled = 0;
    ++fake.requests;
    fakeEvent(std::string("post ") + key + " -> buffer " + std::to_string(fake.dstIndex));
    return true;
}

static bool fakePoll(char* key, uint32_t cap, uint8_t* result) {
    if (!fake.done) return false;
    std::snprintf(key, cap, "%s", fake.key.c_str());
    *result = fake.result;
    fake.done = false;
    fake.busy = false;
    const int other = 1 - fake.dstIndex;
    if (std::memcmp(fake.front.data(), art240[other], CC_ART240_BYTES) != 0) ++fake.frontWrites;
    fakeEvent(std::string("consumed ") + fake.key + " result " + std::to_string(fake.result));
    return true;
}

static void fakeCancel(bool cancel) {
    fake.cancel = cancel;
    fakeEvent(std::string(cancel ? "cancel " : "uncancel ") + fake.key);
}

static void fakeComplete(CCJpegResult decoded) {
    fake.result = cc_art_decode_result(decoded, fake.cancel);   // cc_art_decode.cpp run()
    if (fake.result == CC_DECODE_FAILED) ++fake.failures;
    else if (fake.result == CC_DECODE_ABORTED) ++fake.aborts;
    fake.done = true;
    ++fake.completions;
    ++fake.version;
    fakeEvent(std::string("done ") + fake.key + " result " + std::to_string(fake.result) +
              (decoded == CC_JPEG_ABORTED ? " (stopped before band " + std::to_string(fake.polled) + ")" : ""));
}

// One fake millisecond of the decode task: the band polls that are due (an abort ends the decode at
// once), then, once the full delay has passed, the pixels and the result (cc_art_decode.cpp run()).
static void fakeTick() {
    if (!fake.busy || fake.done) return;
    const uint32_t elapsed = fakeNow - fake.startedAt;
    while (fake.polled < kFakeBands && elapsed >= fake.polled * fake.delayMs / kFakeBands) {
        if (fake.cancel) {
            fakeComplete(CC_JPEG_ABORTED);
            return;
        }
        ++fake.polled;
    }
    if (elapsed < fake.delayMs) return;
    const bool ok = decodeCover240(fake.jpeg.data(), static_cast<uint32_t>(fake.jpeg.size()), fake.dst);
    if (ok) fake.bufferKey[fake.dstIndex] = fake.key;   // the back buffer holds its pixels, whatever the result
    fakeComplete(ok ? CC_JPEG_OK : CC_JPEG_FAILED);
}

static lv_display_t* display = nullptr;
static uint32_t flushes = 0;
static size_t peakUsed = 0;
static uint32_t fakeTickCb() { return fakeNow; }

// The lcdLateRefrs / lcdMaxGapMs measure lcd_thread.cpp used before cc5.4's cadence fix: the
// interval between two refreshes that flushed pixels while animations were listed, from a
// timestamp kept across tweens. Replayed next to cc_anim_cadence_poll() in the cadence run only.
struct FlushGapMetric {
    bool on = false;
    uint32_t periodMs = 16, px = 0, lastReadyMs = 0, late = 0, maxGapMs = 0;
};
static FlushGapMetric flushGap;
static void flushGapStart(lv_event_t*) { flushGap.px = 0; }
static void flushGapReady(lv_event_t*) {
    if (!flushGap.on || flushGap.px == 0) return;   // nothing was invalid: no panel refresh
    const bool animating = lv_anim_count_running() > 0;
    if (animating && flushGap.lastReadyMs) {
        const uint32_t gap = fakeNow - flushGap.lastReadyMs;
        flushGap.maxGapMs = std::max(flushGap.maxGapMs, gap);
        if (gap * 2 > 3u * flushGap.periodMs) ++flushGap.late;
    }
    flushGap.lastReadyMs = animating ? fakeNow : 0;
}
// cc_anim_cadence_poll() after every lv_timer_handler() pass, as lcd_thread's loop does (cadence run).
static CCAnimCadence* cadenceProbe = nullptr;
static uint32_t cadenceRuns = 0, cadenceSeenRun = 0;

static void flush(lv_display_t* disp, const lv_area_t* area, uint8_t* data) {
    const auto* source = reinterpret_cast<const uint16_t*>(data);
    for (int y = area->y1; y <= area->y2; ++y) {
        for (int x = area->x1; x <= area->x2; ++x) {
            const uint16_t color = *source++;
            if (x < 0 || x >= WIDTH || y < 0 || y >= HEIGHT) continue;
            framebuffer[static_cast<size_t>(y) * WIDTH + x] = color;
        }
    }
    ++flushes;
    flushGap.px += static_cast<uint32_t>((area->x2 - area->x1 + 1) * (area->y2 - area->y1 + 1));
    lv_display_flush_ready(disp);
}

static size_t lvglUsedNow() {
    lv_mem_monitor_t monitor{};
    lv_mem_monitor(&monitor);
    return monitor.total_size - monitor.free_size;
}
static size_t usedBeforeCreate = 0, usedAfterCreate = 0, usedAfterFirstFrame = 0;   // FW-RES-001: one-time growth vs the soak rounds

static std::string heapWhere, heapContext;   // where the sampled peak happened (timeline id / step, fake ms)
static void sampleHeap() {
    lv_mem_monitor_t monitor{};
    lv_mem_monitor(&monitor);
    const size_t used = monitor.total_size - monitor.free_size;
    if (used > peakUsed) heapWhere = heapContext + " @" + std::to_string(fakeNow);
    peakUsed = std::max(peakUsed, used);
}

// The lcd_thread loop's re-render triggers: the frame on screen is rendered again when the fake
// decoder finishes (cc_art_decode_version), and the offline layer is re-applied every pass.
static const CCFrame* liveFrame = nullptr;
static const uint8_t* liveArt = nullptr;
static uint32_t renderedDecodeVersion = 0;
static bool offlineLive = false;
// lcd_thread's offline input (section 8.10): every pass feeds cc_offline_input_update() the FOC
// position and the native button edge counter; a timeline's native input is one tap (a press and
// its release) that falls entirely between two passes, which a key-mask sample would miss.
static CCOfflineInput offlineIn = {};
static uint16_t fakePos = 0;
static uint32_t fakeKeyEdges = 0;
// r4: the physical buttons down (cc_display_input() every pass, as lcd_thread's render_host_frame does).
static uint8_t fakeKeys = 0;
static uint32_t reRenders = 0;
static lv_obj_t* hostScreen = nullptr;
// FW-DES-007: the native value screen's offline PC volume view (cc_display.cpp, C linkage; ui_valueScreen.c binds it
// to ui_dataScreen / ui_posIndicator / ui_Arc1 with hmi_thread.cpp's hmi_pc_volume_source). Here a stand-in value
// screen and this fake source: the offline volume mode and the FOC's running step count.
extern "C" {
void cc_native_pc_volume_attach(lv_obj_t* group, lv_obj_t* number, lv_obj_t* arc, bool (*source)(int32_t* steps));
void cc_native_pc_volume_poll(void);
bool cc_native_pc_volume_shown(void);
}
static bool fakePcVolumeActive = false;
static int32_t fakePcVolumeSteps = 0;
static bool fakePcVolumeSource(int32_t* steps) {
    *steps = fakePcVolumeSteps;
    return fakePcVolumeActive;
}
// Which key the art image shows (async runs): logged on every change.
struct ShownLog { uint32_t at; std::string key; };
static std::vector<ShownLog> shownLog;
static bool trackShown = false;

static std::string shownKey() {
    lv_obj_t* artObj = nullptr;
    // art is the first child of the stage (the screen's first child)
    lv_obj_t* stageObj = lv_obj_get_child(hostScreen, 0);
    if (stageObj) artObj = lv_obj_get_child(stageObj, 0);
    if (!artObj || lv_obj_has_flag(artObj, LV_OBJ_FLAG_HIDDEN) || lv_obj_get_style_opa(artObj, 0) == 0) return "";
    const auto* dsc = static_cast<const lv_image_dsc_t*>(lv_image_get_src(artObj));
    if (!dsc) return "";
    const int index = dsc->data == art240[0] ? 0 : dsc->data == art240[1] ? 1 : -1;
    return index < 0 ? "?" : fake.bufferKey[index].empty() ? "#" + std::to_string(index) : fake.bufferKey[index];
}

static void noteShown() {
    if (!trackShown) return;
    const std::string key = shownKey();
    if (shownLog.empty() || shownLog.back().key != key) shownLog.push_back({fakeNow, key});
}

// Advances the fake clock, running LVGL's timers (animations, refresh) as the firmware loop does.
static void advance(uint32_t ms, uint32_t step = 4) {
    while (ms) {
        const uint32_t s = std::min(step, ms);
        for (uint32_t k = 0; k < s; ++k) {
            ++fakeNow;
            if (fake.installed) fakeTick();
        }
        ms -= s;
        if (fake.installed && fake.version != renderedDecodeVersion && liveFrame) {
            renderedDecodeVersion = fake.version;
            cc_display_render(*liveFrame, liveArt);
            ++reRenders;
        }
        if (offlineLive) cc_display_offline(cc_offline_input_update(offlineIn, fakePos, fakeKeyEdges));
        else cc_display_input(fakeKeys);
        lv_timer_handler();
        if (cadenceProbe) {
            cc_anim_cadence_poll(*cadenceProbe, false);
            const uint32_t run = lv_anim_get_timer()->last_run;
            if (run != cadenceSeenRun && lv_anim_count_running() > 0) ++cadenceRuns;
            cadenceSeenRun = run;
        }
        noteShown();
        sampleHeap();
    }
}

static void writePpm(const fs::path& path) {
    fs::create_directories(path.parent_path());
    FILE* file = nullptr;
    fopen_s(&file, path.string().c_str(), "wb");
    if (!file) throw std::runtime_error("Could not create " + path.string());
    std::fprintf(file, "P6\n%d %d\n255\n", WIDTH, HEIGHT);
    for (uint16_t color : framebuffer) {
        const unsigned char rgb[3] = {
            static_cast<unsigned char>(((color >> 11) & 31) * 255 / 31),
            static_cast<unsigned char>(((color >> 5) & 63) * 255 / 63),
            static_cast<unsigned char>((color & 31) * 255 / 31)};
        std::fwrite(rgb, 1, sizeof(rgb), file);
    }
    std::fclose(file);
}

// Exact state at the current fake time: animations evaluated now, full redraw.
static void present() {
    lv_anim_refr_now();
    lv_obj_invalidate(lv_screen_active());
    lv_refr_now(display);
    sampleHeap();
}

// A full redraw without re-evaluating animations (twin-fade probes change an animated style).
static void presentStatic() {
    lv_obj_invalidate(lv_screen_active());
    lv_refr_now(display);
}

// ------------------------------------------------------------ layout dump --
static std::map<const void*, std::string> iconNames;

static int fontPx(const lv_font_t* font) {
    const std::pair<const lv_font_t*, int> known[] = {
        {&cc_font_12, 12}, {&cc_font_14, 14}, {&cc_font_16, 16}, {&cc_font_22, 22}, {&cc_font_48, 48},
        {&cc_font_48t, 48}};
    for (const auto& k : known) if (k.first == font) return k.second;
    return 0;
}

static const char* fontName(const lv_font_t* font) {
    if (font == &cc_font_12) return "cc_font_12";
    if (font == &cc_font_14) return "cc_font_14";
    if (font == &cc_font_16) return "cc_font_16";
    if (font == &cc_font_22) return "cc_font_22";
    if (font == &cc_font_48) return "cc_font_48";
    if (font == &cc_font_48t) return "cc_font_48t";
    return "?";
}

static std::string hex(uint32_t rgb) {
    char buffer[8];
    std::snprintf(buffer, sizeof(buffer), "#%06X", rgb & 0xFFFFFF);
    return buffer;
}

static uint32_t rgbOf(lv_color_t c) { return lv_color_to_u32(c) & 0xFFFFFF; }

static uint32_t decodeAt(const std::string& s, size_t& i) {
    uint32_t letter = static_cast<uint8_t>(s[i]);
    const size_t n = letter >= 0xF0 ? 4 : letter >= 0xE0 ? 3 : letter >= 0xC0 ? 2 : 1;
    if (n > 1) {
        letter &= n == 4 ? 0x07u : n == 3 ? 0x0Fu : 0x1Fu;
        for (size_t j = 1; j < n && i + j < s.size(); ++j) letter = (letter << 6) | (s[i + j] & 0x3F);
    }
    i += n;
    return letter;
}

static void dumpLabelLines(JsonObject o, lv_obj_t* obj, const lv_area_t& a) {
    const char* text = lv_label_get_text(obj);
    const lv_font_t* font = lv_obj_get_style_text_font(obj, 0);
    const int32_t ascent = font->line_height - font->base_line;
    const int32_t letterSpace = lv_obj_get_style_text_letter_space(obj, 0);
    const int32_t lineSpace = lv_obj_get_style_text_line_space(obj, 0);
    const lv_text_align_t align = static_cast<lv_text_align_t>(lv_obj_get_style_text_align(obj, 0));
    JsonArray lines = o["lines"].to<JsonArray>();
    std::string all = text ? text : "";
    size_t start = 0;
    int k = 0;
    while (start <= all.size()) {
        size_t end = all.find('\n', start);
        if (end == std::string::npos) end = all.size();
        const std::string line = all.substr(start, end - start);
        JsonObject l = lines.add<JsonObject>();
        const int32_t top = a.y1 + k * (font->line_height + lineSpace);
        const int32_t width = lv_text_get_width(line.c_str(), static_cast<uint32_t>(line.size()), font, letterSpace);
        const int32_t boxW = a.x2 - a.x1 + 1;
        const int32_t left = align == LV_TEXT_ALIGN_CENTER ? a.x1 + (boxW - width) / 2 : a.x1;
        int32_t inkTop = 1 << 20, inkBottom = -(1 << 20);
        // Pen x of every glyph (lv_draw_label's walk: kerned whole-pixel advances + letter space).
        JsonArray pens = l["pens"].to<JsonArray>();
        int32_t pen = left;
        for (size_t i = 0; i < line.size();) {
            const uint32_t letter = decodeAt(line, i);
            size_t j = i;
            const uint32_t next = j < line.size() ? decodeAt(line, j) : 0;
            lv_font_glyph_dsc_t g{};
            const bool found = lv_font_get_glyph_dsc(font, &g, letter, next);
            pens.add(pen);
            const int32_t adv = found ? g.adv_w : 0;
            if (adv > 0) pen += adv + letterSpace;
            if (!found || !g.box_h || !g.box_w) continue;
            inkTop = std::min<int32_t>(inkTop, top + ascent - g.box_h - g.ofs_y);
            inkBottom = std::max<int32_t>(inkBottom, top + ascent - g.ofs_y - 1);
        }
        l["text"] = line;
        l["top"] = top;
        l["baseline"] = top + ascent;
        l["x1"] = left;
        l["x2"] = left + width - 1;
        l["width"] = width;
        if (inkBottom >= inkTop) { l["ink_top"] = inkTop; l["ink_bottom"] = inkBottom; }
        ++k;
        start = end + 1;
        if (end == all.size()) break;
    }
}

// ------------------------------------------------------------- fit oracle --
// An independent "could the full wire text be shown without U+2026?" answer for each
// frame-driven label (cc54_report.py ellipsis_honest). It does not reuse the renderer's split
// choice, only the contract's rules: a line's capacity is the label box width clamped to the r104
// safe chord (r112 for the heading) of the full text's ink rows (centred on the label), spaces are
// break opportunities, and a word wider than a line may be broken at any code point.
static const CCFrame* dumpFrame = nullptr;
static std::map<std::string, int> roleOrdinal;

static bool sourceOf(const std::string& role, int ordinal, const CCFrame& f, std::string& out) {
    const bool lights = f.layoutId == CC_LAYOUT_LIGHTS || f.layoutId == CC_LAYOUT_LIGHTSBIG;   // presentation 6
    if (role == "home.title" || role == "list.title" || role == "tracks.title" || role == "windows.title" ||
        role == "seek.caption" || role == "scenes.title") out = f.title;
    else if (role == "scenes.prev") out = f.prevTitle;
    else if (role == "scenes.next") out = f.nextTitle;
    else if (role == "scenes.meta" || (role == "status" && lights)) out = f.meta;
    else if (role == "home.artist" || role == "list.subtitle" || role == "tracks.subtitle" || role == "windows.app")
        out = f.subtitle;
    else if (role == "list.meta" || role == "tracks.meta" || role == "windows.meta" || role == "seek.line") out = f.meta;
    else if (role == "status") out = f.status;
    else if (role == "volume.caption") out = f.volumeCaption[0] ? f.volumeCaption : f.title;
    else if (role == "idle.word" && ordinal >= 0 && ordinal < 4) out = f.buttons[ordinal].label;
    else return false;  // heading (fallback chain), tile initial, digits, Seek time, twins: checked elsewhere
    return true;
}

static int32_t measure(const std::string& s, const lv_font_t* font, int32_t letterSpace) {
    return lv_text_get_width(s.c_str(), static_cast<uint32_t>(s.size()), font, letterSpace);
}

// FW-DES-001 oracle: half-width around x 120 that keeps a centred line 2 px clear of every crumb mask pixel with
// alpha >= 32 (both parts) over rows [top, bottom]. The list title's first line takes it (cc_display.cpp).
static int32_t crumbClearOracle(uint8_t crumb, int32_t top, int32_t bottom) {
    int32_t half = 120;
    for (int part = 0; part < 2; ++part) {
        const CCCrumbMask* m = crumb == CC_CRUMB_NONE ? nullptr : cc_crumb_mask(crumb, part == 1);
        if (!m || !m->w) continue;
        for (int32_t y = std::max<int32_t>(top, m->y); y <= std::min<int32_t>(bottom, m->y + m->h - 1); ++y)
            for (int32_t x = 0; x < m->w; ++x) {
                if (m->data[(y - m->y) * m->w + x] < 32) continue;
                const int32_t px = m->x + x;
                half = std::min<int32_t>(half, (px < 120 ? 119 - px : px - 120) - 2);
            }
    }
    return std::max<int32_t>(half, 0);
}

static int32_t chordHalf(int32_t top, int32_t bottom, int32_t radius) {
    int32_t half = 120;
    for (int32_t y = top; y <= bottom; ++y) {
        const int32_t d = y < 120 ? 120 - y : y + 1 - 120;
        int32_t h = 0;
        while (d < radius && (h + 1) * (h + 1) <= radius * radius - d * d) ++h;
        half = std::min(half, h);
    }
    return half;
}

static bool fitsLines(const std::string& s, const lv_font_t* font, int32_t ls, const std::vector<int32_t>& caps) {
    if (measure(s, font, ls) <= caps[0]) return true;
    if (caps.size() < 2) return false;
    for (size_t i = 0; i < s.size(); ++i) {  // break at a space
        if (s[i] != ' ') continue;
        size_t end1 = i, start2 = i;
        while (end1 && s[end1 - 1] == ' ') --end1;
        while (start2 < s.size() && s[start2] == ' ') ++start2;
        if (end1 && start2 < s.size() && measure(s.substr(0, end1), font, ls) <= caps[0] &&
            measure(s.substr(start2), font, ls) <= caps[1])
            return true;
    }
    const int32_t narrow = std::min(caps[0], caps[1]);
    for (size_t a = 0; a < s.size();) {  // break inside a word wider than a line
        while (a < s.size() && s[a] == ' ') ++a;
        size_t b = a;
        while (b < s.size() && s[b] != ' ') ++b;
        if (b > a && measure(s.substr(a, b - a), font, ls) > narrow)
            for (size_t p = a + 1; p < b; ++p)
                if ((static_cast<uint8_t>(s[p]) & 0xC0u) != 0x80u && measure(s.substr(0, p), font, ls) <= caps[0] &&
                    measure(s.substr(p), font, ls) <= caps[1])
                    return true;
        a = b;
    }
    return false;
}

static void dumpFit(JsonObject o, lv_obj_t* obj, const std::string& role) {
    const int ordinal = roleOrdinal[role]++;
    std::string source;
    if (!dumpFrame || !sourceOf(role, ordinal, *dumpFrame, source)) return;
    const lv_font_t* font = lv_obj_get_style_text_font(obj, 0);
    const int32_t ls = lv_obj_get_style_text_letter_space(obj, 0);
    const int32_t lineSpace = lv_obj_get_style_text_line_space(obj, 0);
    const int32_t ascent = font->line_height - font->base_line;
    int32_t tx = 0, ty = 0;
    for (lv_obj_t* p = obj; p; p = lv_obj_get_parent(p)) {
        tx += lv_obj_get_style_translate_x(p, 0);
        ty += lv_obj_get_style_translate_y(p, 0);
    }
    lv_area_t a;
    lv_obj_get_coords(obj, &a);
    const int32_t x = a.x1 - tx, y = a.y1 - ty, w = a.x2 - a.x1 + 1, h = a.y2 - a.y1 + 1;
    const int lines = h >= 2 * font->line_height ? 2 : 1;
    int32_t inkTop = ascent, inkBottom = ascent - 1;
    for (size_t i = 0; i < source.size();) {
        const uint32_t letter = decodeAt(source, i);
        lv_font_glyph_dsc_t g{};
        if (!lv_font_get_glyph_dsc(font, &g, letter, 0) || !g.box_h || !g.box_w) continue;
        inkTop = std::min<int32_t>(inkTop, ascent - g.box_h - g.ofs_y);
        inkBottom = std::max<int32_t>(inkBottom, ascent - g.ofs_y - 1);
    }
    const int32_t centerX = x + w / 2;
    const int32_t offset = centerX > 120 ? centerX - 120 : 120 - centerX;
    std::vector<int32_t> caps;
    for (int k = 0; k < lines; ++k) {
        const int32_t top = y + k * (font->line_height + lineSpace);
        int32_t cap = std::max<int32_t>(0, std::min<int32_t>(w, 2 * (chordHalf(top + inkTop, top + inkBottom, 104) - offset)));
        if (k == 0 && role == "list.title")
            cap = std::min<int32_t>(cap, 2 * crumbClearOracle(dumpFrame->crumb, top + inkTop, top + inkBottom));
        caps.push_back(cap);
    }
    JsonObject fit = o["fit"].to<JsonObject>();
    fit["source"] = source;
    fit["source_width"] = measure(source, font, ls);
    JsonArray capacity = fit["capacity"].to<JsonArray>();
    for (int32_t c : caps) capacity.add(c);
    fit["fits"] = fitsLines(source, font, ls, caps);
}

static int artSourceIndex(lv_obj_t* obj) {
    const auto* dsc = static_cast<const lv_image_dsc_t*>(lv_image_get_src(obj));
    if (!dsc) return -1;
    return dsc->data == art240[0] ? 0 : dsc->data == art240[1] ? 1 : -1;
}

static void dumpTree(JsonArray out, lv_obj_t* obj, bool hiddenAbove) {
    const char* role = static_cast<const char*>(lv_obj_get_user_data(obj));
    const bool hidden = hiddenAbove || lv_obj_has_flag(obj, LV_OBJ_FLAG_HIDDEN);
    lv_area_t a;
    lv_obj_get_coords(obj, &a);
    JsonObject o = out.add<JsonObject>();
    o["role"] = role ? role : "";
    o["hidden"] = hidden;
    o["x1"] = a.x1; o["y1"] = a.y1; o["x2"] = a.x2; o["y2"] = a.y2;
    o["opa"] = lv_obj_get_style_opa(obj, 0);
    o["opa_eff"] = lv_obj_get_style_opa_recursive(obj, 0);
    o["tx"] = lv_obj_get_style_translate_x(obj, 0);
    o["ty"] = lv_obj_get_style_translate_y(obj, 0);
    if (lv_obj_check_type(obj, &lv_label_class)) {
        const lv_font_t* font = lv_obj_get_style_text_font(obj, 0);
        o["type"] = "label";
        o["text"] = lv_label_get_text(obj);
        o["font"] = fontPx(font);
        o["font_name"] = fontName(font);
        o["ascent"] = font->line_height - font->base_line;
        o["letter_space"] = lv_obj_get_style_text_letter_space(obj, 0);
        o["color"] = hex(rgbOf(lv_obj_get_style_text_color(obj, 0)));
        o["text_opa"] = lv_obj_get_style_text_opa(obj, 0);
        dumpLabelLines(o, obj, a);
        if (role) dumpFit(o, obj, role);
    } else if (lv_obj_check_type(obj, &lv_image_class)) {
        o["type"] = "image";
        const void* src = lv_image_get_src(obj);
        const auto it = iconNames.find(src);
        const bool appIcon = role && std::strcmp(role, "windows.icon") == 0;
        o["icon"] = it != iconNames.end() ? it->second.c_str() : appIcon ? "app" : (src ? "art" : "");
        if (it != iconNames.end()) {
            const auto* dsc = static_cast<const lv_image_dsc_t*>(src);
            o["mask_max"] = *std::max_element(dsc->data, dsc->data + dsc->data_size);
        }
        if (role && std::strcmp(role, "art") == 0) o["art_src"] = artSourceIndex(obj);
        o["recolor"] = hex(rgbOf(lv_obj_get_style_image_recolor(obj, 0)));
        o["image_opa"] = lv_obj_get_style_image_opa(obj, 0);
        o["scale_x"] = lv_image_get_scale_x(obj);   // r4 M7 / M8 / M11 (256 = 1.0)
        o["scale_y"] = lv_image_get_scale_y(obj);
    } else {
        o["type"] = "box";
        if (lv_obj_get_style_bg_opa(obj, 0)) o["bg"] = hex(rgbOf(lv_obj_get_style_bg_color(obj, 0)));
    }
    if (hidden) return;  // a hidden subtree draws nothing
    const uint32_t count = lv_obj_get_child_count(obj);
    for (uint32_t i = 0; i < count; ++i) dumpTree(out, lv_obj_get_child(obj, static_cast<int32_t>(i)), hidden);
}

static lv_obj_t* findRole(lv_obj_t* obj, const char* role) {
    const char* r = static_cast<const char*>(lv_obj_get_user_data(obj));
    if (r && std::strcmp(r, role) == 0) return obj;
    const uint32_t count = lv_obj_get_child_count(obj);
    for (uint32_t i = 0; i < count; ++i)
        if (lv_obj_t* hit = findRole(lv_obj_get_child(obj, static_cast<int32_t>(i)), role)) return hit;
    return nullptr;
}

static bool drawn(lv_obj_t* obj) {
    if (!obj) return false;
    for (lv_obj_t* p = obj; p; p = lv_obj_get_parent(p))
        if (lv_obj_has_flag(p, LV_OBJ_FLAG_HIDDEN)) return false;
    return lv_obj_get_style_opa_recursive(obj, 0) > 0;
}

static void dumpStats(JsonObject o, const CCDisplayStats& before) {
    const CCDisplayStats& s = cc_display_stats();
    o["animations"] = s.animations - before.animations;
    o["text_sets"] = s.textSets - before.textSets;
    o["slides"] = s.slides - before.slides;
    o["art_upscales"] = s.artUpscales - before.artUpscales;
    o["art_decodes"] = s.artDecodes - before.artDecodes;
    o["art_decode_errors"] = s.artDecodeErrors - before.artDecodeErrors;
    o["art_reuses"] = s.artReuses - before.artReuses;
    o["icon_loads"] = s.iconLoads - before.iconLoads;
    o["art_decode_requests"] = s.artDecodeRequests - before.artDecodeRequests;
    o["art_decode_aborts"] = s.artDecodeAborts - before.artDecodeAborts;
    o["art_decode_stale"] = s.artDecodeStale - before.artDecodeStale;
    o["ink_fades"] = s.inkFades - before.inkFades;
    o["line_fades"] = s.lineFades - before.lineFades;
    o["glides"] = s.glides - before.glides;              // r4 M4 / M5
    o["track_changes"] = s.trackChanges - before.trackChanges;
    o["presses"] = s.presses - before.presses;           // M7
    o["pops"] = s.pops - before.pops;                    // M8
    o["morphs"] = s.morphs - before.morphs;              // M9
    o["hold_fills"] = s.holdFills - before.holdFills;    // M10
    o["landings"] = s.landings - before.landings;
    o["wall_bounces"] = s.wallBounces - before.wallBounces;   // M13
    o["last_slide"] = s.lastSlide;
    o["screen_change"] = s.lastScreenChange;
    o["changed"] = s.lastChanged;
    o["animated"] = s.lastAnimated;
}

// Captures the active screen now: PPM + layout dump. probe: a twin-fade probe ("content",
// "track" or "volume"): the same instant with that layer at opacity 255 and hidden.
static void capture(JsonObject entry, const fs::path& out, const std::string& file, const CCFrame* frame = nullptr,
                    const char* probe = nullptr, bool png = true) {
    present();
    if (png) {
        writePpm(out / (file + ".ppm"));
        entry["file"] = file + ".png";
    }
    entry["time_ms"] = fakeNow;
    entry["anims_running"] = lv_anim_count_running();
    dumpMedia(entry);
    dumpFrame = frame;
    roleOrdinal.clear();
    dumpTree(entry["layout"].to<JsonArray>(), lv_screen_active(), false);
    dumpFrame = nullptr;
    if (probe && png) {
        lv_obj_t* layer = findRole(lv_screen_active(), probe);
        if (!layer) throw std::runtime_error(std::string("twin probe: no layer ") + probe);
        const lv_opa_t opa = lv_obj_get_style_opa(layer, 0);
        const bool hidden = lv_obj_has_flag(layer, LV_OBJ_FLAG_HIDDEN);
        JsonObject p = entry["probe"].to<JsonObject>();
        p["role"] = probe;
        p["opa"] = opa;
        p["opa_eff"] = lv_obj_get_style_opa_recursive(layer, 0);
        lv_obj_set_style_opa(layer, LV_OPA_COVER, 0);
        lv_obj_remove_flag(layer, LV_OBJ_FLAG_HIDDEN);
        presentStatic();
        writePpm(out / (file + ".full.ppm"));
        p["full"] = file + ".full.png";
        lv_obj_add_flag(layer, LV_OBJ_FLAG_HIDDEN);
        presentStatic();
        writePpm(out / (file + ".under.ppm"));
        p["under"] = file + ".under.png";
        lv_obj_set_style_opa(layer, opa, 0);
        if (!hidden) lv_obj_remove_flag(layer, LV_OBJ_FLAG_HIDDEN);
        presentStatic();
    }
}

// ----------------------------------------------------------------- inputs --
static std::vector<uint8_t> readFile(const fs::path& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) throw std::runtime_error("Missing " + path.string());
    return std::vector<uint8_t>((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
}

static const uint8_t* artFor(JsonVariantConst name) {
    if (!name.is<const char*>()) return nullptr;
    const auto it = artFixtures.find(name.as<const char*>());
    if (it == artFixtures.end()) throw std::runtime_error(std::string("Unknown art fixture ") + name.as<const char*>());
    return it->second.data();
}

static bool parseFrame(JsonVariantConst json, CCFrame& frame) { return cc_parse_frame(json, frame); }

// A frame from a base JSON object plus top-level replacements (each value is raw JSON text).
using Patch = std::vector<std::pair<std::string, std::string>>;
static std::string patched(const char* base, const Patch& patch) {
    JsonDocument doc;
    if (DeserializationError error = deserializeJson(doc, base)) throw std::runtime_error(std::string("base: ") + error.c_str());
    for (const auto& kv : patch) {
        if (kv.second == "null") { doc.remove(kv.first); continue; }
        JsonDocument value;
        if (DeserializationError error = deserializeJson(value, kv.second))
            throw std::runtime_error("patch " + kv.first + ": " + error.c_str());
        doc[kv.first] = value.as<JsonVariantConst>();
    }
    std::string text;
    serializeJson(doc, text);
    return text;
}

static std::string quoted(const std::string& text) {
    JsonDocument doc;
    doc.set(text);
    std::string out;
    serializeJson(doc, out);
    return out;
}

// v5 frames (a v7 host's shapes; PRESENTATION_V5.md sections 3-8, K3 button maps).
static const char* const HOME5 = R"({"id":501,"mode":"HOME","target":"Hall","value":"54%","detail":"","status":"","layout":"nowPlaying","title":"Pressure Front","subtitle":"Mira Vale","artKey":"k-hall","volumeCaption":"Pressure Front","buttons":[{"label":"Pause","enabled":true,"icon":"pause"},{"label":"Browse","enabled":true,"icon":"list"},{"label":"Tracks","enabled":true,"icon":"tracks"},{"label":"Win","enabled":true,"icon":"win"}],"ring":{"style":"level","value":54,"index":0,"count":101}})";
static const char* const IDLE5 = R"({"id":502,"mode":"HOME","target":"Hall","value":"54%","detail":"","status":"Paused","layout":"idle","restLayout":"idle","title":"Pressure Front","subtitle":"Mira Vale","artKey":"k-hall","volumeCaption":"Paused · Pressure Front","buttons":[{"label":"Play","enabled":true,"icon":"play"},{"label":"Browse","enabled":true,"icon":"list"},{"label":"Tracks","enabled":true,"icon":"tracks"},{"label":"Win","enabled":true,"icon":"win"}],"ring":{"style":"level","value":54,"index":0,"count":101}})";
static const char* const RECENT5 = R"({"id":503,"mode":"RECENTLY ADDED","target":"Hall","value":"","detail":"","status":"","layout":"recent","heading":"RECENTLY ADDED","title":"Night Channel","subtitle":"Velvet Circuit","meta":"3 / 24","artKey":"k-bright","buttons":[{"label":"Back","enabled":true,"icon":"back"},{"label":"Open","enabled":true,"icon":"expand"},{"label":"Play next","enabled":true,"icon":"playnext"},{"label":"Play","enabled":true,"icon":"play"}],"ring":{"style":"selection","value":0,"index":2,"count":24,"first":0}})";
static const char* const EXPLORER5 = R"({"id":504,"mode":"RECENTLY ADDED","target":"Hall","value":"","detail":"","status":"","layout":"explorer","heading":"RECENT","page":0,"title":"Slow Orbit","subtitle":"Linnéa Holm","meta":"2 / 8","artKey":"k-hall","buttons":[{"label":"Back","enabled":true,"icon":"back"},{"label":"Recent","enabled":true,"icon":"clock","lit":"on"},{"label":"Playlists","enabled":true,"icon":"playlists","lit":"off"},{"label":"Play","enabled":true,"icon":"play"}],"ring":{"style":"selection","value":0,"index":1,"count":8}})";
static const char* const UPNEXT5 = R"({"id":505,"mode":"RECENTLY ADDED","target":"Hall","value":"","detail":"","status":"","layout":"upnext","heading":"UP NEXT","title":"Satellite Hearts","subtitle":"Linnéa Holm","meta":"6 / 12","artKey":"k-bright","buttons":[{"label":"Back","enabled":true,"icon":"back"},{"label":"Shuffle","enabled":true,"icon":"shuffle","lit":"off"},{"label":"Like","enabled":true,"icon":"heart"},{"label":"Play","enabled":true,"icon":"play"}],"ring":{"style":"selection","value":0,"index":5,"count":12,"now":4}})";
static const char* const TRACKS5 = R"({"id":506,"mode":"TRACKS","target":"Hall","value":"","detail":"","status":"","layout":"tracks","heading":"TRACKS","title":"Turn to choose","subtitle":"Now: Pressure Front","meta":"4 / 12","artKey":"k-hall","buttons":[{"label":"Back","enabled":true,"icon":"back"},{"label":"Up next","enabled":true,"icon":"expand"},{"label":"Seek","enabled":true,"icon":"seek"},{"label":"Skip","enabled":true,"icon":"next"}],"ring":{"style":"transport","value":0,"index":1,"count":3}})";
static const char* const SEEK5 = R"({"id":507,"mode":"TRACKS","target":"Hall","value":"","detail":"","status":"","layout":"seek","heading":"SEEK","title":"Pressure Front","meta":"of 4:47","artKey":"k-hall","buttons":[{"label":"Back","enabled":true,"icon":"back"},{"label":"Up next","enabled":true,"icon":"expand"},{"label":"Seek","enabled":true,"icon":"seek","lit":"on"},{"label":"Skip","enabled":false,"icon":"next"}],"ring":{"style":"lap","value":0,"index":74,"count":287}})";
static const char* const WINDOWS5 = R"({"id":508,"mode":"WINDOWS","target":"DESKTOP","value":"","detail":"","status":"","layout":"windows","title":"Quarterly planning — engineering roadmap review","subtitle":"Microsoft Teams","meta":"","buttons":[{"label":"Back","enabled":true,"icon":"back"},{"label":"Left","enabled":true,"icon":"snapleft"},{"label":"Right","enabled":true,"icon":"snapright"},{"label":"Switch","enabled":true,"icon":"switch"}],"ring":{"style":"selection","value":0,"index":3,"count":9}})";
static const char* const NOTICE5 = R"({"id":509,"mode":"HOME","target":"Hall","value":"","detail":"","status":"","layout":"notice","title":"Sonos unavailable","subtitle":"Looking for Sonos…","meta":"Windows still works","metaTone":"secondary","buttons":[{"label":"Play","enabled":false,"icon":"play"},{"label":"Browse","enabled":true,"icon":"list"},{"label":"Tracks","enabled":false,"icon":"tracks"},{"label":"Win","enabled":true,"icon":"win"}],"ring":{"style":"off","value":0,"index":0,"count":0}})";

// Harness-only v4 frames (slimmed v4 wire JSON; a v2 legacy frame without layout).
struct Synthetic { const char* id; const char* name; const char* art; const char* json; };
static const Synthetic SYNTHETIC[] = {
    {"syn-windows-long-meta", "Windows · long title + error meta (line 2 vs meta)", nullptr,
     R"({"id":900,"mode":"WINDOWS","target":"DESKTOP","value":"","detail":"","status":"","title":"Quarterly planning — engineering roadmap review and follow-ups","subtitle":"Microsoft Teams","layout":"windows","meta":"Didn’t come forward · retry","metaTone":"error","buttons":[{"label":"Cancel","enabled":true,"icon":"cancel"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Switch","enabled":true,"icon":"switch"}],"ring":{"style":"selection","value":0,"index":3,"count":9}})"},
    {"syn-recent-p12", "Recently Added P12 · heading fallback chain", "art-bright-120",
     R"({"id":901,"mode":"RECENTLY ADDED","target":"Hall","value":"","detail":"","status":"","title":"Ásæla ljós","subtitle":"North of June","layout":"recent","heading":"RECENTLY ADDED · P12","meta":"4/11 · Replaces queue","page":11,"artKey":"art-bright-120","buttons":[{"label":"Back","enabled":true,"icon":"back"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Play","enabled":true,"icon":"play"}],"ring":{"style":"selection","value":0,"index":3,"count":11,"moreIndex":10}})"},
    {"syn-accents", "Latin Extended-A title, subtitle and meta", "art-hall-120",
     R"({"id":902,"mode":"RECENTLY ADDED","target":"Hall","value":"","detail":"","status":"","title":"Łódź · Kraków — Žižek’s “Ďábel” in Ōsaka","subtitle":"Dvořák, Chopin & Ősz Ünnepe","layout":"recent","heading":"RECENTLY ADDED","meta":"7/11 · Ŧest ŀine – ĳ ŉ ſ","artKey":"art-hall-120","buttons":[{"label":"Back","enabled":true,"icon":"back"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Play","enabled":true,"icon":"play"}],"ring":{"style":"selection","value":0,"index":6,"count":11}})"},
    {"syn-legacy-v2-volume", "Presentation-2 legacy frame (layout derived from mode)", nullptr,
     R"({"id":903,"mode":"VOLUME","target":"Hall","value":"54%","detail":"Varanda","status":"Paused","title":"Varanda","subtitle":"Ana Ribeira","counter":"","activity":"idle","volumeVisible":false,"buttons":[{"label":"Play","enabled":true,"color":16777215,"icon":"play"},{"label":"Browse","enabled":true,"color":16777215,"icon":"list"},{"label":"Win","enabled":true,"color":16777215,"icon":"win"},{"label":"Tracks","enabled":true,"color":16777215,"icon":"tracks"}],"ring":{"style":"level","value":54,"index":0,"count":101}})"},
    {"syn-win-handoff", "Windows · one over-wide word (file name) fits two lines, no ellipsis", nullptr,
     R"({"id":904,"mode":"WINDOWS","target":"DESKTOP","value":"","detail":"","status":"","title":"HANDOFF_NOTES.md","subtitle":"Visual Studio Code","layout":"windows","meta":"","buttons":[{"label":"Cancel","enabled":true,"icon":"cancel"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Switch","enabled":true,"icon":"switch"}],"ring":{"style":"selection","value":0,"index":1,"count":9}})"},
    {"syn-win-diag-log", "Windows · hyphenated over-wide file name + error meta, no ellipsis", nullptr,
     R"({"id":905,"mode":"WINDOWS","target":"DESKTOP","value":"","detail":"","status":"","title":"cc5-stage6-lcd-diagnostics.log","subtitle":"Notepad","layout":"windows","meta":"Didn’t come forward · retry","metaTone":"error","buttons":[{"label":"Cancel","enabled":true,"icon":"cancel"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Switch","enabled":true,"icon":"switch"}],"ring":{"style":"selection","value":0,"index":2,"count":9}})"},
    {"syn-win-supercal", "Windows · over-wide first word + short words, no ellipsis", nullptr,
     R"({"id":906,"mode":"WINDOWS","target":"DESKTOP","value":"","detail":"","status":"","title":"Supercalifragilisticexpialidocious is ok","subtitle":"Microsoft Word","layout":"windows","meta":"","buttons":[{"label":"Cancel","enabled":true,"icon":"cancel"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Switch","enabled":true,"icon":"switch"}],"ring":{"style":"selection","value":0,"index":4,"count":9}})"},
    {"syn-win-late-word", "Windows · over-wide word after a short one, no ellipsis", nullptr,
     R"({"id":907,"mode":"WINDOWS","target":"DESKTOP","value":"","detail":"","status":"","title":"Notes Pneumonoultramicroscopic","subtitle":"OneNote","layout":"windows","meta":"","buttons":[{"label":"Cancel","enabled":true,"icon":"cancel"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Switch","enabled":true,"icon":"switch"}],"ring":{"style":"selection","value":0,"index":5,"count":9}})"},
    {"syn-win-overflow", "Windows · over-wide words that cannot fit two lines: U+2026", nullptr,
     R"({"id":908,"mode":"WINDOWS","target":"DESKTOP","value":"","detail":"","status":"","title":"Supercalifragilisticexpialidocious_Supercalifragilisticexpialidocious_final_v2.docx","subtitle":"Microsoft Word","layout":"windows","meta":"","buttons":[{"label":"Cancel","enabled":true,"icon":"cancel"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Switch","enabled":true,"icon":"switch"}],"ring":{"style":"selection","value":0,"index":6,"count":9}})"},
    {"syn-win-words-overflow", "Windows · many words that cannot fit two lines: whole words + U+2026", nullptr,
     R"({"id":909,"mode":"WINDOWS","target":"DESKTOP","value":"","detail":"","status":"","title":"Quarterly planning review with the engineering and design teams, follow-ups and notes","subtitle":"Microsoft Teams","layout":"windows","meta":"","buttons":[{"label":"Cancel","enabled":true,"icon":"cancel"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Switch","enabled":true,"icon":"switch"}],"ring":{"style":"selection","value":0,"index":7,"count":9}})"},
    {"syn-recent-long-word", "Recently Added · 22 px over-wide word fits two lines, no ellipsis", nullptr,
     R"({"id":910,"mode":"RECENTLY ADDED","target":"Hall","value":"","detail":"","status":"","title":"Supercalifragilistic","subtitle":"Original Studio Cast","layout":"recent","heading":"RECENTLY ADDED","meta":"2/11 · Replaces queue","buttons":[{"label":"Back","enabled":true,"icon":"back"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Play","enabled":true,"icon":"play"}],"ring":{"style":"selection","value":0,"index":1,"count":11}})"},
    // DD-DES-002: a non-Latin title as Desk Dial sends it to a latin-ext-a knob. The source is 5 Hangul syllables,
    // a space, an emoji and " Mix"; control_center.device._device_text gives one "?" per unsupported character.
    // cc54_report.py `nonlatin_title` recomputes that title with the Desk Dial code and checks this case draws it.
    {"syn-nonlatin", "Recently Added · non-Latin title (5 Hangul + emoji -> ????? ? Mix)", nullptr,
     R"({"id":911,"mode":"RECENTLY ADDED","target":"Room","value":"","detail":"","status":"","title":"????? ? Mix","subtitle":"Various Artists","layout":"recent","heading":"RECENTLY ADDED","meta":"5/11","buttons":[{"label":"Back","enabled":true,"icon":"back"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Play","enabled":true,"icon":"play"}],"ring":{"style":"selection","value":0,"index":4,"count":11}})"},
};

// Harness-only v5 states that frames_v5.json does not draw (section 8.6; 5.2/5.3 inks).
struct V5Case { const char* id; const char* name; const char* art; const char* base; Patch patch; };
static std::vector<V5Case> v5Cases() {
    return {
        {"v5-idle-paused", "Home idle, paused: Play green (5.2 row 9)", nullptr, IDLE5, {}},
        {"v5-idle-nothing", "Home idle, nothing playing: Play and Tracks dim #5A5A5A", nullptr, IDLE5,
         {{"status", "\"\""}, {"title", "\"Nothing playing\""}, {"subtitle", "\"\""}, {"artKey", "\"\""},
          {"buttons", R"([{"label":"Play","enabled":false,"icon":"play"},{"label":"Browse","enabled":true,"icon":"list"},{"label":"Tracks","enabled":false,"icon":"tracks"},{"label":"Win","enabled":true,"icon":"win"}])"}}},
        {"v5-idle-v6-label", "Home idle from a v6 host: Play/Pause label ellipsized (2.3)", nullptr, IDLE5,
         {{"buttons", R"([{"label":"Play/Pause","enabled":true,"icon":"play"},{"label":"Browse","enabled":true,"icon":"list"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Tracks","enabled":true,"icon":"tracks"}])"}}},
        {"v5-home-paused", "Home paused: status Paused, slot 0 Play green", "art-hall-120", HOME5,
         {{"status", "\"Paused\""}, {"buttons", R"([{"label":"Play","enabled":true,"icon":"play"},{"label":"Browse","enabled":true,"icon":"list"},{"label":"Tracks","enabled":true,"icon":"tracks"},{"label":"Win","enabled":true,"icon":"win"}])"}}},
        {"v5-home-starting", "Home starting: status Starting…, Play/Pause dimmed", "art-hall-120", HOME5,
         {{"status", "\"Starting…\""}, {"buttons", R"([{"label":"Play","enabled":false,"icon":"play"},{"label":"Browse","enabled":true,"icon":"list"},{"label":"Tracks","enabled":true,"icon":"tracks"},{"label":"Win","enabled":true,"icon":"win"}])"}}},
        {"v5-home-group", "Home status Speaker group changed (error)", "art-hall-120", HOME5,
         {{"status", "\"Speaker group changed\""}, {"statusTone", "\"error\""}}},
        {"v5-volume", "Volume reveal (Now playing caption)", "art-hall-120", HOME5,
         {{"layout", "\"volume\""}, {"value", "\"100%\""}, {"volumeCaption", "\"Now playing\""}, {"status", "\"Maximum\""}}},
        {"v5-notice", "Notice: Sonos unavailable / Looking for Sonos… / Windows still works", nullptr, NOTICE5, {}},
        {"v5-recent-queueing", "Recently Added: Queueing… 3 of 12", "art-bright-120", RECENT5,
         {{"meta", "\"Queueing… 3 of 12\""}}},
        {"v5-recent-finding", "Recently Added: Finding songs… [r2.2]", "art-bright-120", RECENT5,
         {{"meta", "\"Finding songs…\""}}},
        {"v5-recent-stage-error", "Recently Added: Couldn’t open on screen (error) [r2.2]", "art-bright-120", RECENT5,
         {{"meta", "\"Couldn’t open on screen\""}, {"metaTone", "\"error\""}}},
        {"v5-recent-na", "Recently Added: unavailable item (muted title, artDim)", "art-bright-120", RECENT5,
         {{"titleTone", "\"muted\""}, {"artDim", "true"}, {"meta", "\"Not available\""},
          {"buttons", R"([{"label":"Back","enabled":true,"icon":"back"},{"label":"Open","enabled":true,"icon":"expand"},{"label":"Play next","enabled":false,"icon":"playnext"},{"label":"Play","enabled":false,"icon":"play"}])"}}},
        {"v5-explorer-fav", "Explorer FAVOURITES tab (tab 1)", "art-hall-120", EXPLORER5,
         {{"heading", "\"FAVOURITES\""}, {"page", "1"}, {"title", "\"Favorite Songs\""}, {"subtitle", "\"34 songs\""},
          {"buttons", R"([{"label":"Back","enabled":true,"icon":"back"},{"label":"Recent","enabled":true,"icon":"clock","lit":"off"},{"label":"Playlists","enabled":true,"icon":"playlists","lit":"on"},{"label":"Play","enabled":true,"icon":"play"}])"}}},
        {"v5-explorer-empty", "Explorer FAVOURITES empty: No favourites yet / Star one in Music", nullptr, EXPLORER5,
         {{"heading", "\"FAVOURITES\""}, {"page", "1"}, {"title", "\"No favourites yet\""}, {"subtitle", "\"Star one in Music\""},
          {"meta", "\"\""}, {"artKey", "\"\""}, {"ring", R"({"style":"off","value":0,"index":0,"count":0})"},
          {"buttons", R"([{"label":"Back","enabled":true,"icon":"back"},{"label":"Recent","enabled":true,"icon":"clock","lit":"off"},{"label":"Playlists","enabled":true,"icon":"playlists","lit":"on"},{"label":"Play","enabled":false,"icon":"play"}])"}}},
        {"v5-upnext-liked", "Up next, liked row: filled heart #A3244A (tone liked, [r2.2])", "art-bright-120", UPNEXT5,
         {{"meta", "\"Liked\""}, {"buttons", R"([{"label":"Back","enabled":true,"icon":"back"},{"label":"Shuffle","enabled":true,"icon":"shuffle","lit":"off"},{"label":"Liked","enabled":true,"icon":"heart","lit":"on"},{"label":"Play","enabled":true,"icon":"play"}])"}}},
        {"v5-upnext-unlike", "Up next, press on a liked row: Unfavourite in Music app [r2.2]", "art-bright-120", UPNEXT5,
         {{"meta", "\"Unfavourite in Music app\""}, {"buttons", R"([{"label":"Back","enabled":true,"icon":"back"},{"label":"Shuffle","enabled":true,"icon":"shuffle","lit":"on"},{"label":"Liked","enabled":true,"icon":"heart","lit":"on"},{"label":"Play","enabled":true,"icon":"play"}])"}}},
        {"v5-upnext-card", "Up next, Sonos shuffle card: Shuffled by Sonos", "art-bright-120", UPNEXT5,
         {{"title", "\"Shuffled by Sonos\""}, {"subtitle", "\"\""}, {"meta", "\"8 / 8\""},
          {"ring", R"({"style":"selection","value":0,"index":7,"count":8,"now":6,"card":true})"}}},
        {"v5-upnext-loading", "Up next loading: Loading queue…, ring off", nullptr, UPNEXT5,
         {{"title", "\"\""}, {"subtitle", "\"\""}, {"meta", "\"Loading queue…\""}, {"artKey", "\"\""}, {"activity", "\"loading\""},
          {"ring", R"({"style":"off","value":0,"index":0,"count":0})"}}},
        {"v5-seek-0", "Seek 0:00", "art-hall-120", SEEK5, {{"ring", R"({"style":"lap","value":0,"index":0,"count":287})"}}},
        {"v5-seek-959", "Seek 9:59", "art-hall-120", SEEK5, {{"ring", R"({"style":"lap","value":0,"index":599,"count":3600})"}}},
        {"v5-seek-5959", "Seek 59:59", "art-hall-120", SEEK5, {{"ring", R"({"style":"lap","value":0,"index":3599,"count":3600})"}}},
        {"v5-seek-99959", "Seek 999:58 (the widest lap time)", "art-hall-120", SEEK5,
         {{"meta", "\"of 999:59\""}, {"ring", R"({"style":"lap","value":0,"index":59998,"count":59999})"}}},
        {"v5-seek-jumping", "Seek Jumping… [r2.2]", "art-hall-120", SEEK5, {{"meta", "\"Jumping…\""}}},
        {"v5-seek-failed", "Seek Didn’t jump · try again (error)", "art-hall-120", SEEK5,
         {{"meta", "\"Didn’t jump · try again\""}, {"metaTone", "\"error\""}}},
        {"v5-seek-no-lap", "Seek layout without a lap ring: no time", "art-hall-120", SEEK5,
         {{"ring", R"({"style":"transport","value":0,"index":1,"count":3})"}}},
        {"v5-tracks-shuffle", "Tracks under Sonos shuffle", "art-hall-120", TRACKS5,
         {{"subtitle", "\"Next: shuffle pick\""}, {"meta", "\"4 / 12 · shuffle\""}, {"ring", R"({"style":"transport","value":0,"index":2,"count":3})"}}},
        {"v5-tracks-noprev", "Tracks, previous unavailable (prev #555555)", "art-hall-120", TRACKS5,
         {{"title", "\"Previous track\""}, {"subtitle", "\"Start of queue\""}, {"meta", "\"Previous unavailable\""},
          {"ring", R"({"style":"transport","value":0,"index":0,"count":3,"unavailable":1})"}}},
        {"v5-windows-accent", "Windows letter tile on the app accent (sat, #FFFFFF initial)", nullptr, WINDOWS5,
         {{"ledStyle", "\"color\""}, {"ring", R"({"style":"selection","value":0,"index":3,"count":9,"colors":[5025616,16711680,65280,32768,255,0,1052688,16777215,8421504]})"}}},
        {"v5-windows-snap-navy", "Windows, left side assigned to a navy app: accent_ink lift #4040FF", nullptr, WINDOWS5,
         {{"meta", "\"Left: Teams · pick right\""},
          {"buttons", R"([{"label":"Back","enabled":true,"icon":"back"},{"label":"Left","enabled":true,"icon":"snapleft","lit":"on","color":128},{"label":"Right","enabled":true,"icon":"snapright"},{"label":"Switch","enabled":true,"icon":"switch"}])"}}},
        {"v5-windows-snap-warm", "Windows, right side assigned to a monochrome app: #FFFFFF (P5-6)", nullptr, WINDOWS5,
         {{"meta", "\"Right: Terminal · pick left\""},
          {"buttons", R"([{"label":"Back","enabled":true,"icon":"back"},{"label":"Left","enabled":true,"icon":"snapleft"},{"label":"Right","enabled":true,"icon":"snapright","lit":"on"},{"label":"Switch","enabled":true,"icon":"switch"}])"}}},
        {"v5-windows-empty", "Windows, empty snapshot: No eligible windows", nullptr, WINDOWS5,
         {{"title", "\"No eligible windows\""}, {"subtitle", "\"\""}, {"ring", R"({"style":"selection","value":0,"index":0,"count":1})"}}},
        {"v5-heading-legacy", "Legacy long heading: drop tracking, then ellipsis", "art-bright-120", RECENT5,
         {{"heading", "\"RECENTLY ADDED FROM ALL SOURCES\""}}},
    };
}

// artwork2 harness cases (ARTWORK2.md section 7).
struct Artwork2Case {
    const char* id;
    const char* name;
    const char* cover;
    bool coverDrawn;
    const char* icon;
    const char* json;
};
static const Artwork2Case ARTWORK2_CASES[] = {
    {"a2-np-hall", "artwork2 · Now Playing, 240 px JPEG cover", "a2-hall", true, nullptr,
     R"({"id":960,"mode":"VOLUME","target":"Hall","value":"54%","detail":"","status":"","title":"Pressure Front","subtitle":"Mira Vale","layout":"nowPlaying","artKey":"a2-hall","volumeCaption":"Pressure Front","buttons":[{"label":"Pause","enabled":true,"icon":"pause"},{"label":"Browse","enabled":true,"icon":"list"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Tracks","enabled":true,"icon":"tracks"}],"ring":{"style":"level","value":54,"index":0,"count":101}})"},
    {"a2-np-detail", "artwork2 · Now Playing, 1 px detail cover (only a 240 px path draws it)", "a2-detail", true,
     nullptr,
     R"({"id":968,"mode":"VOLUME","target":"Hall","value":"54%","detail":"","status":"","title":"Fine Lines","subtitle":"Resolution Test","layout":"nowPlaying","artKey":"a2-detail","volumeCaption":"Fine Lines","buttons":[{"label":"Pause","enabled":true,"icon":"pause"},{"label":"Browse","enabled":true,"icon":"list"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Tracks","enabled":true,"icon":"tracks"}],"ring":{"style":"level","value":54,"index":0,"count":101}})"},
    {"a2-np-bright-dim", "artwork2 · Now Playing, bright 240 px JPEG cover, artDim", "a2-bright", true, nullptr,
     R"({"id":961,"mode":"VOLUME","target":"Hall","value":"54%","detail":"","status":"Sonos unavailable","statusTone":"error","title":"Harbour Song","subtitle":"Lumen Park","layout":"nowPlaying","artKey":"a2-bright","artDim":true,"volumeCaption":"Harbour Song","buttons":[{"label":"Play","enabled":false,"icon":"play"},{"label":"Browse","enabled":true,"icon":"list"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Tracks","enabled":false,"icon":"tracks"}],"ring":{"style":"level","value":54,"index":0,"count":101}})"},
    {"a2-recent-bright", "artwork2 · Recently Added, bright 240 px JPEG cover", "a2-bright", true, nullptr,
     R"({"id":962,"mode":"RECENTLY ADDED","target":"Hall","value":"","detail":"","status":"","title":"Perihelion","subtitle":"Linnéa Holm","layout":"recent","heading":"RECENTLY ADDED","meta":"3/11 · Replaces queue","artKey":"a2-bright","buttons":[{"label":"Back","enabled":true,"icon":"back"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Play","enabled":true,"icon":"play"}],"ring":{"style":"selection","value":0,"index":2,"count":11}})"},
    {"a2-recent-hall-dim", "artwork2 · Recently Added, not available: 240 px JPEG cover, artDim", "a2-hall", true, nullptr,
     R"({"id":963,"mode":"RECENTLY ADDED","target":"Hall","value":"","detail":"","status":"","title":"Glass Weather","subtitle":"Lumen Park","layout":"recent","heading":"RECENTLY ADDED","meta":"6/11 · Not available","titleTone":"muted","artKey":"a2-hall","artDim":true,"buttons":[{"label":"Back","enabled":true,"icon":"back"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Play","enabled":false,"icon":"play"}],"ring":{"style":"selection","value":0,"index":5,"count":11,"unavailable":32}})"},
    {"a2-tracks-hall", "artwork2 · Tracks, 240 px JPEG cover", "a2-hall", true, nullptr,
     R"({"id":964,"mode":"TRACKS","target":"Hall","value":"","detail":"","status":"","title":"Turn to choose","subtitle":"Now: Pressure Front","layout":"tracks","heading":"TRACKS","meta":"One press, one skip","artKey":"a2-hall","buttons":[{"label":"Back","enabled":true,"icon":"back"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Skip","enabled":true,"icon":"next"}],"ring":{"style":"transport","value":0,"index":1,"count":3}})"},
    {"a2-tracks-bright-dim", "artwork2 · Tracks, bright 240 px JPEG cover, artDim", "a2-bright", true, nullptr,
     R"({"id":965,"mode":"TRACKS","target":"Hall","value":"","detail":"","status":"","title":"Turn to choose","subtitle":"Now: Harbour Song","layout":"tracks","heading":"TRACKS","meta":"Skip unavailable","metaTone":"error","artKey":"a2-bright","artDim":true,"buttons":[{"label":"Back","enabled":true,"icon":"back"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Skip","enabled":false,"icon":"next"}],"ring":{"style":"transport","value":0,"index":1,"count":3}})"},
    {"a2-np-decode-fail", "artwork2 · Now Playing, committed cover TJpgDec cannot decode: no art", "a2-progressive", false,
     nullptr,
     R"({"id":966,"mode":"VOLUME","target":"Hall","value":"54%","detail":"","status":"","title":"Pressure Front","subtitle":"Mira Vale","layout":"nowPlaying","artKey":"a2-progressive","volumeCaption":"Pressure Front","buttons":[{"label":"Pause","enabled":true,"icon":"pause"},{"label":"Browse","enabled":true,"icon":"list"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Tracks","enabled":true,"icon":"tracks"}],"ring":{"style":"level","value":54,"index":0,"count":101}})"},
    {"a2-np-cover-absent", "artwork2 · Now Playing, cover not committed yet: no art", nullptr, false, nullptr,
     R"({"id":967,"mode":"VOLUME","target":"Hall","value":"54%","detail":"","status":"","title":"Pressure Front","subtitle":"Mira Vale","layout":"nowPlaying","artKey":"a2-absent","volumeCaption":"Pressure Front","buttons":[{"label":"Pause","enabled":true,"icon":"pause"},{"label":"Browse","enabled":true,"icon":"list"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Tracks","enabled":true,"icon":"tracks"}],"ring":{"style":"level","value":54,"index":0,"count":101}})"},
    {"a2-win-icon", "artwork2 · Windows, app icon on the tile", nullptr, false, "ic-code",
     R"({"id":970,"mode":"WINDOWS","target":"DESKTOP","value":"","detail":"","status":"","title":"cc_display.cpp — NanoD_RatchetH1","subtitle":"Visual Studio Code","layout":"windows","iconKey":"ic-code","buttons":[{"label":"Cancel","enabled":true,"icon":"cancel"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Switch","enabled":true,"icon":"switch"}],"ring":{"style":"selection","value":0,"index":1,"count":9}})"},
    {"a2-win-icon-closed", "artwork2 · Windows, closed entry with an app icon (tile group 0.35)", nullptr, false, "ic-chat",
     R"({"id":971,"mode":"WINDOWS","target":"DESKTOP","value":"","detail":"","status":"","title":"#general","subtitle":"Slack","layout":"windows","meta":"Closed · can’t switch","titleTone":"muted","iconKey":"ic-chat","buttons":[{"label":"Cancel","enabled":true,"icon":"cancel"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Switch","enabled":false,"icon":"switch"}],"ring":{"style":"selection","value":0,"index":4,"count":9,"unavailable":16}})"},
    {"a2-win-icon-nosub", "artwork2 · Windows, app icon without a subtitle (tile shown)", nullptr, false, "ic-code",
     R"({"id":972,"mode":"WINDOWS","target":"DESKTOP","value":"","detail":"","status":"","title":"Untitled","subtitle":"","layout":"windows","iconKey":"ic-code","buttons":[{"label":"Cancel","enabled":true,"icon":"cancel"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Switch","enabled":true,"icon":"switch"}],"ring":{"style":"selection","value":0,"index":2,"count":9}})"},
    {"a2-win-letter-lower", "artwork2 · Windows, no icon: lower-case app name, upper-case initial", nullptr, false, nullptr,
     R"({"id":973,"mode":"WINDOWS","target":"DESKTOP","value":"","detail":"","status":"","title":"#random","subtitle":"slack","layout":"windows","buttons":[{"label":"Cancel","enabled":true,"icon":"cancel"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Switch","enabled":true,"icon":"switch"}],"ring":{"style":"selection","value":0,"index":3,"count":9}})"},
    {"a2-win-icon-miss", "artwork2 · Windows, iconKey not in the store: letter tile", nullptr, false, "ic-chat",
     R"({"id":974,"mode":"WINDOWS","target":"DESKTOP","value":"","detail":"","status":"","title":"Terminal session","subtitle":"codex","layout":"windows","iconKey":"ic-missing","buttons":[{"label":"Cancel","enabled":true,"icon":"cancel"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Switch","enabled":true,"icon":"switch"}],"ring":{"style":"selection","value":0,"index":5,"count":9}})"},
    {"a2-win-letter-accent", "artwork2 · Windows, non-ASCII initial drawn as is", nullptr, false, nullptr,
     R"({"id":975,"mode":"WINDOWS","target":"DESKTOP","value":"","detail":"","status":"","title":"Réunion d’équipe","subtitle":"écran partagé","layout":"windows","buttons":[{"label":"Cancel","enabled":true,"icon":"cancel"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Switch","enabled":true,"icon":"switch"}],"ring":{"style":"selection","value":0,"index":6,"count":9}})"},
};

// ------------------------------------------------------------------- main --
static std::vector<uint32_t> captureOffsets(JsonVariantConst expect) {
    std::vector<uint32_t> at = {0};
    auto add = [&](std::initializer_list<uint32_t> times) { at.insert(at.end(), times); };
    if (expect["volumeReveal"] | false) add({50, 150, 190, 230, 340, 390, 460});
    if (expect["volumeHide"] | false) add({100, 170, 190, 240});
    if (expect["idleEnter"] | false) add({160, 200, 245, 290, 335, 380, 560, 800, 1100});
    if (expect["idleExit"] | false) add({90, 140, 160, 280, 420, 510});
    if ((expect["slide"] | 0) != 0 || (expect["screenFade"] | false)) add({40, 60, 110, 160, 220, 240, 300, 380, 420});
    // r4 key times (MOTION.md): M2 / M3 reveal, M11 stagger, M6 line rise, and the r4 moment probes.
    if (expect["volumeReveal"] | false) add({130, 160, 220});
    if (expect["volumeHide"] | false) add({130, 160, 350, 640});
    if (expect["idleEnter"] | false) add({240});
    if (expect["idleExit"] | false) add({350, 640});
    if (expect["lineFade"] | false) add({240, 560});
    if (expect["glide"] | false) add({20, 60, 120, 200, 300, 420});
    if (expect["press"] | false) add({35, 70, 150, 300, 640});
    if (expect["hold"] | false) add({250, 500, 750, 1000, 1100});
    if (expect["wall"] | false) add({45, 90, 150, 250, 400, 650});
    if (expect["pop"] | false) add({40, 100, 150, 200, 300, 640});
    if (expect["tour"] | false) add({60, 120, 240, 420});
    if (expect["flash"].is<const char*>()) add({300});
    if (expect["artLate"] | false) add({30, 60, 120, 240, 270, 480, 520});
    if (expect["artFade"] | false) add({60, 120, 180, 240, 300});
    if (expect["lineFade"] | false) add({40, 80, 120, 160, 200});
    if (expect["inkFade"] | false) add({40, 80, 120, 160, 200});
    if (expect["offlineIn"] | false) add({80, 160, 220, 240, 300});
    if (expect["offlineOut"] | false) add({80, 140, 220, 240, 300, 420, 500});
    if (expect["iconArrive"] | false) add({30});
    if (expect["twinFade"].is<const char*>()) add({20, 40, 60, 80, 100, 120, 140, 160, 180, 200});
    std::sort(at.begin(), at.end());
    at.erase(std::unique(at.begin(), at.end()), at.end());
    return at;
}

using Commits = std::vector<std::pair<uint8_t, std::string>>;  // artwork2 (kind, fixture name)

enum StepAction : uint8_t { STEP_FRAME, STEP_OFFLINE, STEP_OFFLINE_NATIVE, STEP_HANDBACK,
                            STEP_KEYS,    // r4: the physical buttons down become `keys` (cc_display_input)
                            STEP_WALL };  // r4: a wall hit towards `wall` (cc_display_wall)

struct Step {
    uint32_t t;
    const CCFrame* frame;
    const uint8_t* art;
    JsonVariantConst expect;
    std::string label;
    Commits commits = {};  // artwork2 commits just before this render (lcd_thread re-renders on them)
    uint32_t decodeMs = 0;  // fake ms each synchronous JPEG decode of this render takes
    uint8_t action = STEP_FRAME;
    uint8_t keys = 0;       // STEP_KEYS
    int8_t wall = 0;        // STEP_WALL
};

// FW-DES-003: the animations a render starts. Before the render every running anim is stamped (lv_anim_t
// user_data, which cc_display never uses); afterwards the unstamped ones are new: their duration, delay
// (lv_anim_start stores -delay in act_time) and the role of the object they animate ("" for a struct var).
static int animStamp = 0;
static void stampAnims() {
    lv_ll_t* ll = &LV_GLOBAL_DEFAULT()->anim_state.anim_ll;
    for (void* n = _lv_ll_get_head(ll); n; n = _lv_ll_get_next(ll, n)) static_cast<lv_anim_t*>(n)->user_data = &animStamp;
}
static void collectObjs(lv_obj_t* obj, std::map<const void*, std::string>& out) {
    const char* role = static_cast<const char*>(lv_obj_get_user_data(obj));
    out[obj] = role ? role : "";
    for (uint32_t i = 0; i < lv_obj_get_child_count(obj); ++i) collectObjs(lv_obj_get_child(obj, i), out);
}
static void dumpStartedAnims(JsonArray out) {
    std::map<const void*, std::string> objs;
    if (hostScreen) collectObjs(hostScreen, objs);
    lv_ll_t* ll = &LV_GLOBAL_DEFAULT()->anim_state.anim_ll;
    for (void* n = _lv_ll_get_head(ll); n; n = _lv_ll_get_next(ll, n)) {
        const lv_anim_t* a = static_cast<const lv_anim_t*>(n);
        if (a->user_data == &animStamp) continue;
        JsonObject o = out.add<JsonObject>();
        const auto it = objs.find(a->var);
        o["role"] = it != objs.end() ? it->second : std::string();
        o["duration"] = a->duration;
        o["delay"] = a->act_time < 0 ? -a->act_time : 0;
        o["from"] = a->start_value;
        o["to"] = a->end_value;
    }
}

static bool pngCaptures = true;   // false in the full-layers run's copy pass

// Captures are timed from the end of their step's render: a render that decodes with
// Step::decodeMs set returns decodeMs later on the fake tick, and the render's animations must
// start from that moment.
static void runTimeline(JsonObject seqOut, const std::string& id, const std::vector<Step>& steps, const fs::path& out) {
    resetStore();
    offlineLive = false;
    for (const auto& commit : steps.front().commits) commitMedia(commit.first, commit.second);
    const CCDisplayStats base = cc_display_stats();
    cc_display_render(*steps.front().frame, steps.front().art);
    liveFrame = steps.front().frame;
    liveArt = steps.front().art;
    advance(1200);
    JsonObject baseline = seqOut["baseline"].to<JsonObject>();
    dumpStats(baseline, base);
    const uint32_t start = fakeNow;
    struct Event { uint32_t at; int kind; size_t step; uint32_t offset; };  // kind 0 = render, 1 = capture
    std::vector<Event> events;
    for (size_t i = 1; i < steps.size(); ++i) {
        events.push_back({start + steps[i].t, 0, i, 0});
        for (uint32_t offset : captureOffsets(steps[i].expect)) events.push_back({start + steps[i].t + offset, 1, i, offset});
    }
    std::stable_sort(events.begin(), events.end(), [](const Event& a, const Event& b) {
        return a.at != b.at ? a.at < b.at : a.kind < b.kind;
    });
    JsonArray stepsOut = seqOut["steps"].to<JsonArray>();
    JsonArray captures = seqOut["captures"].to<JsonArray>();
    std::vector<uint32_t> renderMs(steps.size(), 0);
    for (const Event& e : events) {
        const uint32_t at = e.at + (e.kind == 1 ? renderMs[e.step] : 0);
        if (at > fakeNow) advance(at - fakeNow, 1);
        const Step& step = steps[e.step];
        heapContext = id + " / " + step.label;
        if (e.kind == 0) {
            JsonObject s = stepsOut.add<JsonObject>();
            s["t"] = step.t;
            s["label"] = step.label;
            s["expect"] = step.expect;
            s["action"] = step.action;
            if (step.frame) {
                s["layout"] = step.frame->layoutId;
                s["rest_layout"] = step.frame->restLayout;
            }
            if (!step.commits.empty()) {
                JsonArray committed = s["commits"].to<JsonArray>();
                for (const auto& commit : step.commits) {
                    commitMedia(commit.first, commit.second);
                    committed.add(commit.second);
                }
            }
            const CCDisplayStats before = cc_display_stats();
            const uint16_t runningBefore = lv_anim_count_running();
            const uint32_t flushesBefore = flushes;
            const uint32_t renderStart = fakeNow;
            stampAnims();
            if (step.action == STEP_FRAME) {
                offlineLive = false;
                decodeFakeMs = step.decodeMs;
                cc_display_render(*step.frame, step.art);
                decodeFakeMs = 0;
                liveFrame = step.frame;
                liveArt = step.art;
            } else if (step.action == STEP_HANDBACK) {
                offlineLive = false;
                cc_display_release_media();
                liveFrame = nullptr;
            } else if (step.action == STEP_KEYS) {
                fakeKeys = step.keys;
                cc_display_input(fakeKeys);
                s["keys"] = step.keys;
            } else if (step.action == STEP_WALL) {
                cc_display_wall(step.wall);
                s["wall"] = step.wall;
            } else {
                // As render_host_frame: a claim or a handback reset the input, so the layer's first
                // pass takes new references; a native tap bumps the edge counter by 2.
                if (!offlineLive) cc_offline_input_reset(offlineIn);
                offlineLive = true;
                if (step.action == STEP_OFFLINE_NATIVE) fakeKeyEdges += 2;
                cc_display_offline(cc_offline_input_update(offlineIn, fakePos, fakeKeyEdges));
                liveFrame = nullptr;
            }
            renderMs[e.step] = fakeNow - renderStart;
            JsonObject r = s["render"].to<JsonObject>();
            dumpStats(r, before);
            r["render_ms"] = renderMs[e.step];
            r["anims_running_before"] = runningBefore;
            r["anims_running_after"] = lv_anim_count_running();
            dumpStartedAnims(r["anims_started"].to<JsonArray>());
            lv_refr_now(display);
            r["redraw_flushes"] = flushes - flushesBefore;
            dumpMedia(r);
            sampleHeap();
        } else {
            JsonObject c = captures.add<JsonObject>();
            c["step"] = static_cast<uint32_t>(e.step);
            c["step_t"] = step.t;
            c["offset"] = e.offset;
            char name[64];
            std::snprintf(name, sizeof(name), "%05u-s%02u+%04u", static_cast<unsigned>(e.at - start),
                          static_cast<unsigned>(e.step), static_cast<unsigned>(e.offset));
            const char* probe = step.expect["twinFade"].is<const char*>() ? step.expect["twinFade"].as<const char*>() : nullptr;
            capture(c, out, (fs::path("timelines") / id / name).generic_string(), nullptr, probe, pngCaptures);
        }
    }
    advance(1200);
    offlineLive = false;
    fakeKeys = 0;
    cc_display_input(0);
}

// FW-RES-001 soak: a timeline replayed without captures or JSON (the same render/input dispatch as
// runTimeline), so main() can repeat every named timeline and record the LVGL pool after each round.
// The knob lost ~18.6 KB of its pool over 42 h; a renderer that keeps allocating per frame, per screen
// change or per animation shows here as used bytes growing from round to round.
static void soakTimeline(const std::vector<Step>& steps) {
    resetStore();
    offlineLive = false;
    for (const auto& commit : steps.front().commits) commitMedia(commit.first, commit.second);
    cc_display_render(*steps.front().frame, steps.front().art);
    liveFrame = steps.front().frame;
    liveArt = steps.front().art;
    advance(1200);
    std::vector<size_t> order;
    for (size_t i = 1; i < steps.size(); ++i) order.push_back(i);
    std::stable_sort(order.begin(), order.end(), [&](size_t a, size_t b) { return steps[a].t < steps[b].t; });
    const uint32_t start = fakeNow;
    for (size_t i : order) {
        const Step& step = steps[i];
        if (start + step.t > fakeNow) advance(start + step.t - fakeNow, 1);
        for (const auto& commit : step.commits) commitMedia(commit.first, commit.second);
        if (step.action == STEP_FRAME) {
            offlineLive = false;
            decodeFakeMs = step.decodeMs;
            cc_display_render(*step.frame, step.art);
            decodeFakeMs = 0;
            liveFrame = step.frame;
            liveArt = step.art;
        } else if (step.action == STEP_HANDBACK) {
            offlineLive = false;
            cc_display_release_media();
            liveFrame = nullptr;
        } else if (step.action == STEP_KEYS) {
            fakeKeys = step.keys;
            cc_display_input(fakeKeys);
        } else if (step.action == STEP_WALL) {
            cc_display_wall(step.wall);
        } else {
            if (!offlineLive) cc_offline_input_reset(offlineIn);
            offlineLive = true;
            if (step.action == STEP_OFFLINE_NATIVE) fakeKeyEdges += 2;
            cc_display_offline(cc_offline_input_update(offlineIn, fakePos, fakeKeyEdges));
            liveFrame = nullptr;
        }
        lv_refr_now(display);
    }
    advance(1200);
    offlineLive = false;
    fakeKeys = 0;
    cc_display_input(0);
}

// Frames kept alive for a timeline (CCFrame storage with stable addresses).
struct FrameBank {
    std::deque<CCFrame> frames;
    const CCFrame* parse(const std::string& json) {
        JsonDocument doc;
        if (DeserializationError error = deserializeJson(doc, json))
            throw std::runtime_error(std::string("frame JSON: ") + error.c_str() + " in " + json.substr(0, 80));
        frames.emplace_back();
        if (!cc_parse_frame(doc.as<JsonVariantConst>(), frames.back()))
            throw std::runtime_error("frame rejected by cc_parse_frame: " + json.substr(0, 160));
        return &frames.back();
    }
    const CCFrame* make(const char* base, const Patch& patch = {}) { return parse(patched(base, patch)); }
};

int main(int argc, char** argv) try {
    const bool oneBuffer = argc > 1 && std::strcmp(argv[1], "--one-buffer") == 0;
    const int arg = oneBuffer ? 2 : 1;
    const fs::path out = argc > arg ? fs::path(argv[arg]) : fs::path(oneBuffer ? "cc54-handoff/one-buffer" : "cc54-handoff");
    const fs::path fixtures = argc > arg + 1 ? fs::path(argv[arg + 1]) : fs::path(NANOD_FIXTURE_DIR);
    const fs::path framesPath = argc > arg + 2 ? fs::path(argv[arg + 2]) : fs::path(NANOD_FRAMES_JSON);
    const fs::path artwork2Dir = argc > arg + 3 ? fs::path(argv[arg + 3]) : fs::path(NANOD_ARTWORK2_DIR);
    const fs::path framesV5Path = fs::path(NANOD_FRAMES_V5_JSON);
    const fs::path copyPath = fs::path(NANOD_COPY_JSON);
    const fs::path framesV6Path = fs::path(NANOD_FRAMES_V6_JSON);
    const fs::path r3ScreensPath = fs::path(NANOD_R3_SCREENS_JSON);
    fs::create_directories(out);

    lv_init();
    lv_tick_set_cb(fakeTickCb);  // after lv_init(), which resets LVGL globals
    display = lv_display_create(WIDTH, HEIGHT);
    lv_display_set_color_format(display, LV_COLOR_FORMAT_RGB565);
    lv_display_set_buffers(display, draw_buffer, nullptr, sizeof(draw_buffer), LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_flush_cb(display, flush);

    const char* names[] = {"play", "pause", "list", "win", "tracks", "back", "home", "more", "prev", "next",
                           "switch", "cancel", "expand", "clock", "playlists", "playnext", "seek", "shuffle",
                           "heart", "snapleft", "snapright", "dotfill", "heartfill", "ok", "dot", "warn", "usb",
                           "bulb", "thermo", "power", "wand", "house", "album"};   // presentation 6
    for (const char* name : names)
        for (int size : {16, 20, 26})
            if (const lv_image_dsc_t* dsc = cc_icon(name, size)) iconNames[dsc] = std::string(name) + "@" + std::to_string(size);
    for (uint8_t k = 1; k <= CC_ICON_MORPH_FRAMES; ++k)   // r4 M9 frames
        iconNames[cc_icon_morph(k)] = "morph" + std::to_string(k) + "@20";

    for (const char* name : {"art-hall-120", "art-bright-120"}) {
        artFixtures[name] = readFile(fixtures / (std::string(name) + ".rgb565"));
        if (artFixtures[name].size() != CC_ART120_BYTES)
            throw std::runtime_error(std::string("Artwork fixture is not 120x120 RGB565: ") + name);
    }
    artFixtures["late-bright-120"] = artFixtures["art-bright-120"];
    {
        // A white cover composited the way the host sends every v5 cover (PRESENTATION_V5.md 8.4:
        // pixel = cover x 0.8 x (1 - s(y)), s linear through (0, 0.60), (108, 0.72), (148.8, 0.92),
        // (168, 1.0)): the brightest backdrop a twin can fade over (P5-13's bound), as a v1 120 px cover.
        std::vector<uint8_t> scrim(CC_ART120_BYTES);
        for (int y = 0; y < 120; ++y) {
            const double row = 2.0 * y + 1.0;   // centre of the two 240 px rows this row becomes
            double s = 1.0;
            if (row < 108.0) s = 0.60 + 0.12 * row / 108.0;
            else if (row < 148.8) s = 0.72 + 0.20 * (row - 108.0) / 40.8;
            else if (row < 168.0) s = 0.92 + 0.08 * (row - 148.8) / 19.2;
            const int v = static_cast<int>(255.0 * 0.8 * (1.0 - s) + 0.5);
            const uint16_t c = static_cast<uint16_t>((((v * 31 + 127) / 255) << 11) | (((v * 63 + 127) / 255) << 5) |
                                                     ((v * 31 + 127) / 255));
            for (int x = 0; x < 120; ++x) {
                scrim[2 * (y * 120 + x)] = static_cast<uint8_t>(c & 0xFF);
                scrim[2 * (y * 120 + x) + 1] = static_cast<uint8_t>(c >> 8);
            }
        }
        artFixtures["scrim-white-120"] = scrim;
    }

    {
        const std::vector<uint8_t> text = readFile(artwork2Dir / "manifest.json");
        JsonDocument manifest;
        if (DeserializationError error = deserializeJson(manifest, reinterpret_cast<const char*>(text.data()), text.size()))
            throw std::runtime_error(std::string("artwork2 manifest.json: ") + error.c_str());
        for (const char* group : {"covers", "broken", "icons"}) {
            const uint8_t kind = std::strcmp(group, "icons") == 0 ? CC_DISPLAY_MEDIA_ICON : CC_DISPLAY_MEDIA_COVER;
            for (JsonVariantConst item : manifest[group].as<JsonArrayConst>()) {
                std::vector<uint8_t> bytes = readFile(artwork2Dir / item["file"].as<std::string>());
                if (bytes.size() != item["bytes"].as<size_t>() ||
                    (kind == CC_DISPLAY_MEDIA_ICON && bytes.size() != CC_ICON_BYTES))
                    throw std::runtime_error("artwork2 fixture size mismatch: " + item["file"].as<std::string>());
                mediaFixtures[kind][item["name"].as<std::string>()] = std::move(bytes);
            }
        }
    }
    // Keys no other case or timeline uses, so their timelines start with neither display buffer
    // holding them (a real decode on arrival); a5-* for the R5 timelines.
    std::vector<std::pair<std::string, std::string>> coverAliases = {
        {"a2-late", "a2-bright"}, {"a2-swap-a", "a2-hall"}, {"a2-swap-b", "a2-bright"}, {"a2-slide", "a2-bright"}};
    {
        const char* cycle[3] = {"a2-hall", "a2-bright", "a2-detail"};
        for (int k = 0; k < 40; ++k) {
            char key[16];
            std::snprintf(key, sizeof(key), "a5-k%02d", k);
            coverAliases.push_back({key, cycle[k % 3]});
        }
        coverAliases.push_back({"a5-fail", "a2-progressive"});
    }
    for (const auto& alias : coverAliases)
        mediaFixtures[CC_DISPLAY_MEDIA_COVER][alias.first] = mediaFixtures[CC_DISPLAY_MEDIA_COVER].at(alias.second);
    CCDisplayMedia lookups = {};
    lookups.adopt = standInAdopt;
    lookups.release = standInRelease;
    lookups.decodeCover = standInDecode;
    cc_display_set_media(lookups);

    const std::vector<uint8_t> framesText = readFile(framesPath);
    JsonDocument fixture;
    if (DeserializationError error = deserializeJson(fixture, reinterpret_cast<const char*>(framesText.data()), framesText.size()))
        throw std::runtime_error(std::string("cc5_frames.json: ") + error.c_str());
    const std::vector<uint8_t> v5Text = readFile(framesV5Path);
    JsonDocument v5Fixture;
    if (DeserializationError error = deserializeJson(v5Fixture, reinterpret_cast<const char*>(v5Text.data()), v5Text.size()))
        throw std::runtime_error(std::string("frames_v5.json: ") + error.c_str());

    usedBeforeCreate = lvglUsedNow();
    lv_obj_t* screen = cc_display_create(art240[0], oneBuffer ? nullptr : art240[1]);
    hostScreen = screen;
    lv_screen_load(screen);
    sampleHeap();
    usedAfterCreate = lvglUsedNow();

    JsonDocument index;
    index["about"] = oneBuffer ? "cc5.4 LCD harness, one art buffer (main.cpp --one-buffer); checked by cc54_report.py"
                               : "cc5.4 LCD harness renders (harness/main.cpp); checked by cc54_report.py";
    index["art_buffers"] = oneBuffer ? 1 : 2;
    index["full_layers"] = CC_DISPLAY_FULL_LAYERS;
    index["text_twins"] = CC_TEXT_TWINS;
    index["frames"] = framesPath.generic_string();
    index["frames_v5"] = framesV5Path.generic_string();
    index["copy_table"] = copyPath.generic_string();
    index["artwork2_fixtures"] = artwork2Dir.generic_string();
    index["jpeg_glue"] = NANOD_JPEG_GLUE;
    index["firmware_src"] = NANOD_FIRMWARE_SRC_DIR;
    index["tjpgd_shim"] = NANOD_TJPGD_SHIM_DIR;
    JsonObject aliases = index["artwork2_aliases"].to<JsonObject>();
    for (const auto& alias : coverAliases) aliases[alias.first] = alias.second;
    {
        JsonObject decoded = index["artwork2_decoded"].to<JsonObject>();
        std::vector<uint16_t> pixels(240u * 240u);
        fs::create_directories(out / "decoded");
        for (const auto& item : mediaFixtures[CC_DISPLAY_MEDIA_COVER]) {
            bool alias = false;
            for (const auto& a : coverAliases) alias = alias || item.first == a.first;
            if (alias) continue;
            if (!decodeCover240(item.second.data(), static_cast<uint32_t>(item.second.size()), pixels.data())) {
                decoded[item.first] = nullptr;
                continue;
            }
            const std::string file = "decoded/" + item.first + ".rgb565";
            std::ofstream(out / file, std::ios::binary)
                .write(reinterpret_cast<const char*>(pixels.data()), static_cast<std::streamsize>(pixels.size() * 2));
            decoded[item.first] = file;
        }
    }
    JsonArray cases = index["cases"].to<JsonArray>();
    int rejected = 0;

    auto renderCase = [&](const std::string& id, const std::string& name, const std::string& group,
                          JsonVariantConst frameJson, const uint8_t* art, const char* artName,
                          const Commits& commits) {
        JsonObject c = cases.add<JsonObject>();
        c["id"] = id;
        c["name"] = name;
        c["group"] = group;
        if (artName) c["art"] = artName;
        resetStore();
        if (!commits.empty()) {
            JsonArray committed = c["commits"].to<JsonArray>();
            for (const auto& commit : commits) {
                commitMedia(commit.first, commit.second);
                committed.add(commit.second);
            }
        }
        static CCFrame frame;
        if (!parseFrame(frameJson, frame)) {
            c["kind"] = "rejected";
            ++rejected;
            std::fprintf(stderr, "cc_parse_frame rejected case %s\n", id.c_str());
            return;
        }
        c["kind"] = "frame";
        c["wire"] = frameJson;
        c["layout_id"] = frame.layoutId;
        c["rest_layout_id"] = frame.restLayout;
        c["page"] = frame.page;
        c["art_key"] = frame.artKey;
        c["icon_key"] = frame.iconKey;
        c["art_dim"] = frame.artDim;
        c["playing"] = frame.playing;          // [r3.1] a paused Home cover draws at image_opa CC_ART_PAUSED_OPA (255)
        static CCFrame twin;
        twin = frame;
        twin.artKey[0] = '\0';
        CCDisplayStats before = cc_display_stats();
        cc_display_render(twin, nullptr);
        advance(1200);
        JsonObject noart = c["noart"].to<JsonObject>();
        dumpStats(noart["stats"].to<JsonObject>(), before);
        capture(noart, out, "cases/" + id + ".noart", &twin);
        before = cc_display_stats();
        cc_display_render(frame, art);
        JsonObject render = c["render"].to<JsonObject>();
        dumpStats(render["stats"].to<JsonObject>(), before);
        advance(1200);
        capture(render, out, "cases/" + id, &frame);
        if (!usedAfterFirstFrame) usedAfterFirstFrame = lvglUsedNow();
    };

    // The offline screen (section 8.10): from a settled Home render, initial and after native input.
    auto renderOffline = [&](const std::string& id, const std::string& name, bool native, const uint8_t* art,
                             const CCFrame& from) {
        JsonObject c = cases.add<JsonObject>();
        c["id"] = id;
        c["name"] = name;
        c["group"] = "offline";
        c["kind"] = "offline";
        c["native"] = native;
        resetStore();
        cc_display_render(from, art);
        advance(1200);
        CCDisplayStats before = cc_display_stats();
        cc_display_offline(false);
        if (native) {
            advance(400);
            cc_display_offline(true);
        }
        for (int k = 0; k < 300; ++k) { cc_display_offline(native); advance(4); }
        JsonObject render = c["render"].to<JsonObject>();
        dumpStats(render["stats"].to<JsonObject>(), before);
        capture(render, out, "cases/" + id);
        JsonObject noart = c["noart"].to<JsonObject>();
        capture(noart, out, "cases/" + id + ".noart");
        cc_display_render(from, art);   // leave it (the next claim)
        advance(1200);
    };

    // FW-DES-007: the native value screen in offline PC volume mode (no Desk Dial: the knob sends Consumer volume
    // keys and cannot read the PC level). A stand-in of ui_valueScreen.c (black screen, ui_dataScreen's 100 % x 50 %
    // centred flex column, ui_posIndicator with a "100" in a knob font, ui_Arc1's styles at 100 of 0..200: the
    // offline profile re-centres there after every step) with the firmware's own PC volume view bound to it. Only
    // the view's label and tick are drawn in these renders: the stand-ins (number, arc, and the profile name and
    // "MIDI CC 7" description labels of the flex column) are hidden or muted (kind "native"; cc54_report.py
    // native_pc_volume checks the layouts, the ring pixels and the transitions recorded here).
    auto renderNativePcVolume = [&]() {
        // The knob builds its value screen at boot, apart from the CC display, and the harness never builds the
        // real one: this stand-in screen is held out of the CC display's heap peak (section 12.2) and measured on
        // its own instead (heap_* below; cc54_report.py native_pc_volume bounds the firmware view's share).
        const size_t savedPeak = peakUsed;
        const std::string savedWhere = heapWhere;
        const size_t heapEntry = lvglUsedNow();
        peakUsed = 0;
        heapContext = "native-pc-volume";
        lv_obj_t* value = lv_obj_create(nullptr);
        lv_obj_remove_flag(value, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_style_bg_color(value, lv_color_hex(0x000000), 0);
        lv_obj_set_style_bg_opa(value, 255, 0);
        lv_obj_t* data = lv_obj_create(value);
        lv_obj_remove_style_all(data);
        lv_obj_set_size(data, lv_pct(100), lv_pct(50));
        lv_obj_set_align(data, LV_ALIGN_CENTER);
        lv_obj_set_flex_flow(data, LV_FLEX_FLOW_COLUMN);
        lv_obj_set_flex_align(data, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
        lv_obj_set_style_pad_row(data, 8, 0);
        lv_obj_set_user_data(data, const_cast<char*>("native.data"));
        lv_obj_t* number = lv_obj_create(data);
        lv_obj_remove_style_all(number);
        lv_obj_set_size(number, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
        lv_obj_set_user_data(number, const_cast<char*>("native.number"));
        lv_obj_t* digits = lv_label_create(number);
        lv_obj_set_style_text_font(digits, &cc_font_48t, 0);
        lv_obj_set_style_text_color(digits, lv_color_hex(0xFFFFFF), 0);
        lv_label_set_text(digits, "100");
        lv_obj_set_user_data(digits, const_cast<char*>("native.number.digits"));
        // ui_profileName / ui_profileDesc: the flex column's other two children, shown at boot by
        // ComThread::dispatchLcdConfig with the native profile's name and generateDescription's text (stand-in
        // fonts: the SquareLine ones need C++20 here; widths, colours, letter space and alignment as on the knob).
        lv_obj_t* profileName = lv_label_create(data);
        lv_obj_set_width(profileName, lv_pct(78));
        lv_label_set_long_mode(profileName, LV_LABEL_LONG_DOT);
        lv_obj_set_style_text_font(profileName, &cc_font_16, 0);
        lv_obj_set_style_text_color(profileName, lv_color_hex(0xFF7D00), 0);
        lv_obj_set_style_text_letter_space(profileName, 1, 0);
        lv_obj_set_style_text_align(profileName, LV_TEXT_ALIGN_CENTER, 0);
        lv_label_set_text(profileName, "Profile 1");
        lv_obj_set_user_data(profileName, const_cast<char*>("native.profile.name"));
        lv_obj_t* profileDesc = lv_label_create(data);
        lv_obj_set_width(profileDesc, 150);
        lv_obj_set_style_text_font(profileDesc, &cc_font_16, 0);
        lv_obj_set_style_text_color(profileDesc, lv_color_hex(0x9D9D9D), 0);
        lv_obj_set_style_text_letter_space(profileDesc, 1, 0);
        lv_obj_set_style_text_line_space(profileDesc, 1, 0);
        lv_obj_set_style_text_align(profileDesc, LV_TEXT_ALIGN_CENTER, 0);
        lv_label_set_text(profileDesc, "MIDI CC 7");
        lv_obj_set_user_data(profileDesc, const_cast<char*>("native.profile.desc"));
        lv_obj_t* arc = lv_arc_create(value);
        lv_obj_set_size(arc, lv_pct(98), lv_pct(98));
        lv_obj_set_align(arc, LV_ALIGN_CENTER);
        lv_obj_remove_flag(arc, LV_OBJ_FLAG_CLICKABLE);
        lv_arc_set_bg_angles(arc, 89, 88);
        lv_obj_set_style_arc_color(arc, lv_color_hex(0x282828), LV_PART_MAIN);
        lv_obj_set_style_arc_width(arc, 2, LV_PART_MAIN);
        lv_obj_set_style_arc_rounded(arc, false, LV_PART_MAIN);
        lv_obj_set_style_arc_color(arc, lv_color_hex(0xFF7D00), LV_PART_INDICATOR);
        lv_obj_set_style_arc_width(arc, 2, LV_PART_INDICATOR);
        lv_obj_set_style_arc_rounded(arc, false, LV_PART_INDICATOR);
        lv_obj_set_style_radius(arc, 12, LV_PART_KNOB);
        lv_obj_set_style_bg_color(arc, lv_color_hex(0xFFFFFF), LV_PART_KNOB);
        lv_obj_set_style_border_color(arc, lv_color_hex(0x000000), LV_PART_KNOB);
        lv_obj_set_style_border_width(arc, 5, LV_PART_KNOB);
        lv_arc_set_range(arc, 0, 200);
        lv_arc_set_value(arc, 100);
        lv_obj_set_user_data(arc, const_cast<char*>("native.arc"));
        lv_screen_load(value);
        fakePcVolumeActive = false;
        fakePcVolumeSteps = 7;   // steps from before the mode never tick
        const size_t heapBeforeView = lvglUsedNow();
        cc_native_pc_volume_attach(data, number, arc, fakePcVolumeSource);
        const size_t heapView = lvglUsedNow() - heapBeforeView;
        advance(100);
        bool beforeNumber = drawn(number), beforeArc = drawn(arc), beforeShown = cc_native_pc_volume_shown();
        bool beforeProfile = drawn(profileName) && drawn(profileDesc);
        auto addCase = [&](const char* id, const char* name, const char* tick) {
            JsonObject c = cases.add<JsonObject>();
            c["id"] = id;
            c["name"] = name;
            c["group"] = "native";
            c["kind"] = "native";
            c["tick"] = tick;
            JsonObject render = c["render"].to<JsonObject>();
            capture(render, out, std::string("cases/") + id);
            return c;
        };
        fakePcVolumeActive = true;
        advance(400);
        JsonObject rest = addCase("native-pc-volume", "Offline PC volume (native screen): PC volume, no number, no arc", "");
        JsonObject t = rest["transitions"].to<JsonObject>();
        t["before_number_drawn"] = beforeNumber;
        t["before_arc_drawn"] = beforeArc;
        t["before_shown"] = beforeShown;
        t["entry_ticked"] = drawn(findRole(value, "pcvol.tick"));
        t["before_profile_drawn"] = beforeProfile;
        t["mode_profile_drawn"] = drawn(profileName) || drawn(profileDesc);
        // lcd_thread.cpp owns the labels' HIDDEN flags: the mode must leave them as they were (shown here).
        t["mode_profile_hidden_flag"] = lv_obj_has_flag(profileName, LV_OBJ_FLAG_HIDDEN) ||
                                        lv_obj_has_flag(profileDesc, LV_OBJ_FLAG_HIDDEN);
        {
            lv_obj_t* box = findRole(value, "pcvol");
            lv_area_t a;
            lv_obj_get_coords(box, &a);
            t["box_x1"] = a.x1; t["box_y1"] = a.y1; t["box_x2"] = a.x2; t["box_y2"] = a.y2;
        }
        ++fakePcVolumeSteps;
        advance(40);
        addCase("native-pc-volume-up", "Offline PC volume: + tick on a volume-up step", "+");
        advance(100);
        t["tick_up_at_140_ms"] = drawn(findRole(value, "pcvol.tick"));
        advance(300);
        t["tick_up_at_440_ms"] = drawn(findRole(value, "pcvol.tick"));
        fakePcVolumeSteps -= 2;
        advance(40);
        addCase("native-pc-volume-down", "Offline PC volume: - tick on a volume-down step", "-");
        advance(400);
        t["tick_down_at_440_ms"] = drawn(findRole(value, "pcvol.tick"));
        fakePcVolumeActive = false;
        advance(100);
        t["exit_number_drawn"] = drawn(number);
        t["exit_arc_drawn"] = drawn(arc);
        t["exit_view_drawn"] = drawn(findRole(value, "pcvol"));
        t["exit_profile_drawn"] = drawn(profileName) && drawn(profileDesc);
        t["exit_shown"] = cc_native_pc_volume_shown();
        lv_screen_load(hostScreen);
        lv_obj_delete(value);   // the view's delete event stops its timer
        advance(100);
        t["released_on_delete"] = !cc_native_pc_volume_shown();
        heapContext.clear();
        t["heap_entry"] = static_cast<uint32_t>(heapEntry);
        t["heap_peak"] = static_cast<uint32_t>(peakUsed);
        t["heap_view_bytes"] = static_cast<uint32_t>(heapView);
        t["heap_after_delete"] = static_cast<uint32_t>(lvglUsedNow());
        peakUsed = savedPeak;
        heapWhere = savedWhere;
    };

    FrameBank bank;
    const uint8_t* den = artFixtures.at("art-hall-120").data();
    const uint8_t* bright = artFixtures.at("art-bright-120").data();

    if (!oneBuffer) {
        for (JsonVariantConst item : fixture["cases"].as<JsonArrayConst>()) {
            const char* artName = item["art"].is<const char*>() ? item["art"].as<const char*>() : nullptr;
            if (item["frame"].isNull()) {
                renderOffline(item["id"].as<std::string>(), item["name"].as<std::string>() + " (offline screen)", false,
                              den, *bank.make(HOME5));
                continue;
            }
            renderCase(item["id"].as<const char*>(), item["name"].as<const char*>(), item["group"].as<const char*>(),
                       item["frame"], artFor(item["art"]), artName, Commits());
        }
    }
    std::vector<JsonDocument> syntheticDocs(oneBuffer ? 0 : sizeof(SYNTHETIC) / sizeof(SYNTHETIC[0]));
    for (size_t i = 0; i < syntheticDocs.size(); ++i) {
        if (DeserializationError error = deserializeJson(syntheticDocs[i], SYNTHETIC[i].json))
            throw std::runtime_error(std::string("synthetic ") + SYNTHETIC[i].id + ": " + error.c_str());
        const uint8_t* art = SYNTHETIC[i].art ? artFixtures.at(SYNTHETIC[i].art).data() : nullptr;
        renderCase(SYNTHETIC[i].id, SYNTHETIC[i].name, "synthetic", syntheticDocs[i].as<JsonVariantConst>(), art,
                   SYNTHETIC[i].art, Commits());
    }
    // frames_v5.json: every input a cc5.4 parser accepts (v5.accept), drawn with the v1 Hall
    // fixture as the cover of whatever artKey it names.
    std::deque<JsonDocument> v5Docs;
    if (!oneBuffer) {
        for (JsonVariantConst item : v5Fixture["cases"].as<JsonArrayConst>()) {
            if (!(item["v5"]["accept"] | false)) continue;
            const std::string name = item["name"].as<std::string>();
            v5Docs.emplace_back();
            v5Docs.back().set(item["input"]);
            const bool hasArt = item["input"]["artKey"].is<const char*>() && item["input"]["artKey"].as<std::string>().size();
            renderCase("v5." + name, item["note"].as<std::string>().substr(0, 120), "v5", v5Docs.back().as<JsonVariantConst>(),
                       hasArt ? den : nullptr, hasArt ? "art-hall-120" : nullptr, Commits());
        }
        for (const V5Case& v : v5Cases()) {
            v5Docs.emplace_back();
            deserializeJson(v5Docs.back(), patched(v.base, v.patch));
            JsonVariantConst key = v5Docs.back()["artKey"];
            const bool hasArt = key.is<const char*>() && key.as<std::string>().size() && v.art;
            renderCase(v.id, v.name, "v5syn", v5Docs.back().as<JsonVariantConst>(),
                       hasArt ? artFixtures.at(v.art).data() : nullptr, hasArt ? v.art : nullptr, Commits());
        }
        // Presentation 6: the parser fixture's accepted frames, then the r3 contact-sheet screens.
        const std::vector<uint8_t> v6Text = readFile(framesV6Path);
        JsonDocument v6Fixture;
        if (DeserializationError error = deserializeJson(v6Fixture, reinterpret_cast<const char*>(v6Text.data()), v6Text.size()))
            throw std::runtime_error(std::string("frames_v6.json: ") + error.c_str());
        for (JsonVariantConst item : v6Fixture["cases"].as<JsonArrayConst>()) {
            if (!(item["expect"]["accept"] | false)) continue;
            v5Docs.emplace_back();
            v5Docs.back().set(item["input"]);
            renderCase("v6." + item["name"].as<std::string>(), item["note"].as<std::string>().substr(0, 120), "v6",
                       v5Docs.back().as<JsonVariantConst>(), nullptr, nullptr, Commits());
        }
        const std::vector<uint8_t> r3Text = readFile(r3ScreensPath);
        JsonDocument r3Screens;
        if (DeserializationError error = deserializeJson(r3Screens, reinterpret_cast<const char*>(r3Text.data()), r3Text.size()))
            throw std::runtime_error(std::string("r3_screens.json: ") + error.c_str());
        for (JsonVariantConst item : r3Screens["screens"].as<JsonArrayConst>()) {
            v5Docs.emplace_back();
            v5Docs.back().set(item["frame"]);
            const char* artName = item["art"].is<const char*>() ? item["art"].as<const char*>() : nullptr;
            renderCase("r3." + item["id"].as<std::string>(), item["name"].as<std::string>(), "r3",
                       v5Docs.back().as<JsonVariantConst>(), artFor(item["art"]), artName, Commits());
        }
        renderOffline("v5-offline", "Offline: Waiting for PC / Open Desk Dial on your PC", false, den, *bank.make(HOME5));
        renderOffline("v5-offline-native", "Offline after native input: Knob controls still work", true, den,
                      *bank.make(HOME5));
        renderNativePcVolume();
    }
    std::vector<JsonDocument> artwork2Docs(sizeof(ARTWORK2_CASES) / sizeof(ARTWORK2_CASES[0]));
    for (size_t i = 0; i < artwork2Docs.size(); ++i) {
        const Artwork2Case& a2 = ARTWORK2_CASES[i];
        if (DeserializationError error = deserializeJson(artwork2Docs[i], a2.json))
            throw std::runtime_error(std::string("artwork2 case ") + a2.id + ": " + error.c_str());
        Commits commits;
        if (a2.cover) commits.push_back({static_cast<uint8_t>(CC_DISPLAY_MEDIA_COVER), a2.cover});
        if (a2.icon) commits.push_back({static_cast<uint8_t>(CC_DISPLAY_MEDIA_ICON), a2.icon});
        renderCase(a2.id, a2.name, "artwork2", artwork2Docs[i].as<JsonVariantConst>(), nullptr,
                   a2.coverDrawn ? a2.cover : nullptr, commits);
    }

    // copy (section 15.3): every knob string in its element (layout dumps only).
    if (!oneBuffer && !CC_DISPLAY_FULL_LAYERS) {
        const std::vector<uint8_t> copyText = readFile(copyPath);
        JsonDocument copy;
        if (DeserializationError error = deserializeJson(copy, reinterpret_cast<const char*>(copyText.data()), copyText.size()))
            throw std::runtime_error(std::string("cc54_copy.json: ") + error.c_str());
        JsonArray copyOut = index["copy"].to<JsonArray>();
        const std::map<std::string, const char*> bases = {{"recent", RECENT5}, {"nowPlaying", HOME5},
                                                          {"tracks", TRACKS5}, {"seek", SEEK5}, {"windows", WINDOWS5},
                                                          {"volume", HOME5}, {"idle", IDLE5}};
        for (JsonVariantConst s : copy["strings"].as<JsonArrayConst>()) {
            const std::string element = s["element"].as<std::string>();
            JsonVariantConst e = copy["elements"][element];
            const std::string layout = e["layout"].as<std::string>(), field = e["field"].as<std::string>();
            const std::string text = s["text"].as<std::string>();
            const std::string role = e["role"].as<std::string>();
            JsonObject c = copyOut.add<JsonObject>();
            c["id"] = s["id"];
            c["text"] = text;
            c["element"] = element;
            c["limit"] = e["limit"];
            if (e["lines"].is<int>()) c["lines_want"] = e["lines"];
            if (s["placeholder"].is<bool>()) c["placeholder"] = s["placeholder"];
            if (s["exception"].is<const char*>()) c["exception"] = s["exception"];
            const CCFrame* f = nullptr;
            if (layout == "offline") {
                // Firmware-local strings (section 8.10): the offline layer draws its own copy; the
                // label is compared with the VOC text below. field "native": after native input.
                cc_display_render(*bank.make(HOME5, {{"artKey", "\"\""}}), nullptr);
                advance(1200);
                cc_display_offline(false);
                advance(400);
                if (field == "native") cc_display_offline(true);
                for (int k = 0; k < 100; ++k) { cc_display_offline(field == "native"); advance(4); }
            } else {
                Patch patch = {{"layout", quoted(layout)}, {"artKey", "\"\""}};
                if (field == "label0") {
                    JsonDocument b;
                    deserializeJson(b, R"([{"label":"","enabled":true,"icon":"play"},{"label":"Browse","enabled":true,"icon":"list"},{"label":"Tracks","enabled":true,"icon":"tracks"},{"label":"Win","enabled":true,"icon":"win"}])");
                    b[0]["label"] = text;
                    std::string buttons;
                    serializeJson(b, buttons);
                    patch.push_back({"buttons", buttons});
                } else {
                    patch.push_back({field, quoted(text)});
                }
                f = bank.make(bases.at(layout), patch);
                cc_display_render(*f, nullptr);
                advance(1200);
            }
            // The whole string on one line in the element's font and tracking (lv_text_get_width,
            // the renderer's widthOf): what a one-line element needs, whether or not it wrapped.
            if (lv_obj_t* label = findRole(lv_screen_active(), role.c_str())) {
                c["natural_width"] = lv_text_get_width(text.c_str(), static_cast<uint32_t>(text.size()),
                                                       lv_obj_get_style_text_font(label, 0),
                                                       lv_obj_get_style_text_letter_space(label, 0));
            }
            JsonObject rendered = c["render"].to<JsonObject>();
            capture(rendered, out, "copy/" + s["id"].as<std::string>(), f, nullptr, false);
            // Keep only the element's label (and its twin) in the dump.
            JsonArray kept = c["labels"].to<JsonArray>();
            for (JsonVariantConst o : rendered["layout"].as<JsonArrayConst>()) {
                const std::string r = o["role"].as<std::string>();
                if (r == role && !(o["hidden"] | true)) kept.add(o);
            }
            c.remove("render");
        }
    }

    // vectors (section 17: accent_ink, mmss and the 5.2 tone table through cc_presentation.h).
    if (!oneBuffer && !CC_DISPLAY_FULL_LAYERS) {
        JsonObject vectors = index["vectors"].to<JsonObject>();
        JsonArray mm = vectors["mmss"].to<JsonArray>();
        for (JsonVariantConst v : v5Fixture["vectors"]["mmss"].as<JsonArrayConst>()) {
            char text[12];
            cc_mmss(v[0].as<uint32_t>(), text, sizeof(text));
            JsonArray row = mm.add<JsonArray>();
            row.add(v[0]);
            row.add(text);
        }
        JsonArray ai = vectors["accentInk"].to<JsonArray>();
        for (JsonVariantConst v : v5Fixture["vectors"]["accentInk"].as<JsonArrayConst>()) {
            JsonArray row = ai.add<JsonArray>();
            row.add(v[0]);
            row.add(cc_accent_ink(v[0].as<uint32_t>()));
        }
        JsonArray tones = vectors["tones"].to<JsonArray>();
        for (JsonVariantConst v : v5Fixture["vectors"]["tones"].as<JsonArrayConst>()) {
            CCFrame f;
            const std::string layout = v["layout"].as<std::string>();
            for (uint8_t k = 0; k <= CC_LAYOUT_UPNEXT; ++k)
                if (const char* token = cc_token_name(CC_TOKENS_LAYOUT, k)) if (layout == token) f.layoutId = k;
            const uint8_t slot = v["slot"].as<uint8_t>();
            const std::string icon = v["icon"].as<std::string>();
            for (uint8_t k = 0; k <= CC_ICON_SNAPRIGHT; ++k)
                if (const char* token = cc_token_name(CC_TOKENS_ICON, k)) if (icon == token) f.buttons[slot].icon = k;
            f.buttons[slot].iconSent = true;
            f.buttons[slot].enabled = v["enabled"].as<bool>();
            f.buttons[slot].color = v["color"].as<uint32_t>();
            const std::string lit = v["lit"].is<const char*>() ? v["lit"].as<std::string>() : "";
            f.buttons[slot].lit = lit == "on" ? CC_LIT_ON : lit == "off" ? CC_LIT_OFF : CC_LIT_NONE;
            JsonObject row = tones.add<JsonObject>();
            row["in"] = v;
            const char* tone = cc_token_name(CC_TOKENS_TONE, cc_button_tone(f, slot));
            row["tone"] = tone ? tone : "?";
            row["ink"] = cc_button_ink(f, slot);
        }
        // accent_ink and sat() over a grid (every 17th level per channel plus odd steps) for the Python parity.
        JsonArray grid = vectors["accentGrid"].to<JsonArray>();
        for (uint32_t r = 0; r < 256; r += 15)
            for (uint32_t g = 0; g < 256; g += 15)
                for (uint32_t b = 0; b < 256; b += 15) {
                    const uint32_t c = (r << 16) | (g << 8) | b;
                    uint32_t s = 0;
                    JsonArray row = grid.add<JsonArray>();
                    row.add(c);
                    row.add(cc_accent_ink(c));
                    row.add(cc_sat(c, s) ? static_cast<int64_t>(s) : -1);
                }
    }

    // Timelines: the fixture sequences on the fake tick.
    JsonArray timelines = index["timelines"].to<JsonArray>();
    std::vector<std::vector<CCFrame>> frameStore;
    for (JsonVariantConst seq : fixture["sequences"].as<JsonArrayConst>()) {
        if (oneBuffer) break;
        JsonArrayConst stepsJson = seq["steps"].as<JsonArrayConst>();
        frameStore.emplace_back(stepsJson.size());
        std::vector<CCFrame>& frames = frameStore.back();
        std::vector<Step> steps;
        size_t k = 0;
        for (JsonVariantConst s : stepsJson) {
            if (!parseFrame(s["frame"], frames[k])) throw std::runtime_error(std::string("sequence frame rejected in ") + seq["id"].as<const char*>());
            std::string label = s["action"].isNull() ? "baseline" : s["action"]["t"].as<std::string>();
            steps.push_back({s["t"].as<uint32_t>(), &frames[k], artFor(s["art"]), s["expect"], label});
            ++k;
        }
        JsonObject seqOut = timelines.add<JsonObject>();
        seqOut["id"] = seq["id"];
        seqOut["name"] = seq["name"];
        runTimeline(seqOut, seq["id"].as<std::string>(), steps, out);
    }

    // Expectation objects for the harness timelines (every one exists before any reference to it).
    JsonDocument expectDoc;
    JsonObject ex = expectDoc.to<JsonObject>();
    ex["none"].to<JsonObject>();
    ex["identical"]["identical"] = true;
    ex["deeper"]["slide"] = 28;
    ex["back"]["slide"] = -28;
    ex["same"]["slide"] = 0;
    // FW-DES-004: Recently Added's source toggle: no slide, the crumb crossfades (captures at the line-fade times).
    ex["sourceToggle"]["slide"] = 0;
    ex["sourceToggle"]["lineFade"] = true;
    ex["sourceToggle"]["sourceToggle"] = true;
    ex["late"]["artLate"] = true;
    ex["icon"]["iconArrive"] = true;
    ex["artFade"]["artFade"] = true;
    ex["artFade"]["slide"] = 0;
    ex["artFadeDeeper"]["artFade"] = true;
    ex["artFadeDeeper"]["slide"] = 28;
    ex["artFadeBack"]["artFade"] = true;
    ex["artFadeBack"]["slide"] = -28;
    ex["line"]["lineFade"] = true;
    ex["line"]["slide"] = 0;
    ex["ink"]["inkFade"] = true;
    ex["ink"]["slide"] = 0;
    ex["inkDeeper"]["inkFade"] = true;
    ex["inkDeeper"]["slide"] = 28;
    ex["inkBack"]["inkFade"] = true;
    ex["inkBack"]["slide"] = -28;
    ex["idleIn"]["idleEnter"] = true;
    ex["idleOut"]["idleExit"] = true;
    ex["reveal"]["volumeReveal"] = true;
    ex["hide"]["volumeHide"] = true;
    ex["offIn"]["offlineIn"] = true;
    ex["offNative"]["lineFade"] = true;
    ex["offOut"]["offlineOut"] = true;
    ex["reducedSlide"]["screenFade"] = true;
    ex["reducedSlide"]["slide"] = 0;
    ex["reducedSlide"]["reduced"] = true;
    ex["reducedReveal"]["volumeReveal"] = true;
    ex["reducedReveal"]["reduced"] = true;
    ex["reducedHide"]["volumeHide"] = true;
    ex["reducedHide"]["reduced"] = true;
    ex["reducedIdle"]["idleEnter"] = true;
    ex["reducedIdle"]["reduced"] = true;
    ex["reducedIdleOut"]["idleExit"] = true;
    ex["reducedIdleOut"]["reduced"] = true;
    ex["twinContent"]["twinFade"] = "content";
    ex["twinContent"]["slide"] = 28;
    ex["twinTrack"]["twinFade"] = "track";
    ex["twinTrack"]["volumeReveal"] = true;
    ex["twinVolume"]["twinFade"] = "volume";
    ex["twinVolume"]["volumeHide"] = true;
    ex["seek"]["slide"] = 0;
    ex["seek"]["seek"] = true;
    ex["footerStatic"]["slide"] = 28;
    ex["footerStatic"]["footerStatic"] = true;
    // r4 moment probes (captureOffsets above).
    ex["glide"]["glide"] = true;
    ex["glide"]["slide"] = 0;
    ex["press"]["press"] = true;
    ex["hold"]["hold"] = true;
    ex["hold"]["press"] = true;
    ex["wall"]["wall"] = true;
    ex["pop"]["pop"] = true;
    ex["pop"]["slide"] = 0;
    ex["popLine"]["pop"] = true;
    ex["popLine"]["lineFade"] = true;
    ex["popLine"]["slide"] = 0;
    ex["reveal4"]["volumeReveal"] = true;
    ex["hide4"]["volumeHide"] = true;
    ex["tour"]["tour"] = true;
    auto E = [&](const char* key) -> JsonVariantConst { return expectDoc[key]; };

    struct Named { std::string id; std::string name; std::vector<Step> steps; };
    std::vector<Named> named;

    // Harness-only timeline: a cover whose pixels arrive after its key (late arrival: hidden, then
    // a 240 ms fade, section 8.4), then idle entry/exit.
    if (!oneBuffer) {
        const CCFrame* lateNp = bank.parse(R"({"id":950,"mode":"VOLUME","target":"Hall","value":"54%","detail":"","status":"","title":"Harbour Song","subtitle":"Lumen Park","layout":"nowPlaying","artKey":"late-bright-120","volumeCaption":"Harbour Song","buttons":[{"label":"Pause","enabled":true,"icon":"pause"},{"label":"Browse","enabled":true,"icon":"list"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Tracks","enabled":true,"icon":"tracks"}],"ring":{"style":"level","value":54,"index":0,"count":101}})");
        const CCFrame* lateIdle = bank.parse(patched(R"({"id":950,"mode":"VOLUME","target":"Hall","value":"54%","detail":"","status":"","title":"Harbour Song","subtitle":"Lumen Park","layout":"idle","restLayout":"idle","artKey":"late-bright-120","volumeCaption":"Harbour Song","buttons":[{"label":"Pause","enabled":true,"icon":"pause"},{"label":"Browse","enabled":true,"icon":"list"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Tracks","enabled":true,"icon":"tracks"}],"ring":{"style":"level","value":54,"index":0,"count":101}})", {}));
        JsonDocument winDoc;
        deserializeJson(winDoc, SYNTHETIC[0].json);
        const CCFrame* win = bank.parse(SYNTHETIC[0].json);
        named.push_back({"art-late-idle", "Late cover arrival (240 ms fade), idle fade-out and return (harness-only)", {
            {0, win, nullptr, E("none"), "baseline"},
            {0, lateNp, nullptr, E("none"), "key-without-pixels"},
            {600, lateNp, artFixtures.at("late-bright-120").data(), E("late"), "pixels-arrive"},
            {1600, lateIdle, nullptr, E("idleIn"), "idle-enter"},
            {3400, lateNp, nullptr, E("idleOut"), "idle-exit"},
        }});
    }

    // v5 timelines (section 8.7-8.10).
    if (!oneBuffer) {
        const CCFrame* home = bank.make(HOME5);
        const CCFrame* recent = bank.make(RECENT5);
        const CCFrame* recent2 = bank.make(RECENT5, {{"title", "\"Kill for Love\""}, {"meta", "\"4 / 24\""},
                                                     {"ring", R"({"style":"selection","value":0,"index":3,"count":24,"first":0})"}});
        const CCFrame* explorer0 = bank.make(EXPLORER5);
        const CCFrame* explorer1 = bank.make(EXPLORER5, {{"heading", "\"FAVOURITES\""}, {"page", "1"}, {"subtitle", "\"34 songs\""},
            {"buttons", R"([{"label":"Back","enabled":true,"icon":"back"},{"label":"Recent","enabled":true,"icon":"clock","lit":"off"},{"label":"Playlists","enabled":true,"icon":"playlists","lit":"on"},{"label":"Play","enabled":true,"icon":"play"}])"}});
        const CCFrame* upnext = bank.make(UPNEXT5);
        const CCFrame* tracks = bank.make(TRACKS5);
        const CCFrame* tracksNext = bank.make(TRACKS5, {{"title", "\"Next track\""}, {"subtitle", "\"Next: Paper Lanterns\""},
            {"meta", "\"Press 4 to skip\""}, {"ring", R"({"style":"transport","value":0,"index":2,"count":3})"}});
        const CCFrame* seek = bank.make(SEEK5);
        const CCFrame* windows = bank.make(WINDOWS5);
        const CCFrame* homeHeld = bank.make(HOME5, {{"id", "511"}});
        named.push_back({"v5-flips", "Section 8.7 flip table (one timeline, every r2.1 flip)", {
            {0, home, den, E("none"), "baseline"},
            {600, recent, bright, E("deeper"), "home-to-recent"},
            {1400, recent2, bright, E("same"), "recent-detent"},
            {1800, explorer0, den, E("deeper"), "recent-to-explorer"},
            {2600, explorer1, den, E("deeper"), "tab-0-to-1"},
            {3400, explorer0, den, E("back"), "tab-1-to-0"},
            {4200, recent, bright, E("back"), "explorer-to-recent"},
            {5000, home, den, E("back"), "recent-to-home"},
            {5800, tracks, den, E("deeper"), "home-to-tracks"},
            {6600, tracksNext, den, E("same"), "tracks-detent"},
            {7000, seek, den, E("same"), "tracks-to-seek"},
            {7800, upnext, bright, E("deeper"), "seek-to-upnext"},
            {8600, tracks, den, E("back"), "upnext-to-tracks"},
            {9400, seek, den, E("same"), "seek-on"},
            {10000, tracks, den, E("same"), "seek-off"},
            {10600, home, den, E("back"), "tracks-to-home"},
            {11400, windows, nullptr, E("deeper"), "home-to-windows"},
            {12200, home, den, E("back"), "windows-to-home"},
            {13000, upnext, bright, E("deeper"), "home-to-upnext"},
            {13800, homeHeld, den, E("back"), "hold-to-home"},
            {14600, bank.make(HOME5, {{"id", "512"}}), den, E("same"), "control-id-change"},
            {15200, bank.make(HOME5, {{"layout", "\"notice\""}, {"artKey", "\"\""}, {"title", "\"Sonos unavailable\""},
                                     {"subtitle", "\"Looking for Sonos…\""}, {"meta", "\"Windows still works\""}}), nullptr,
             E("same"), "home-layout-change"},
        }});

        // Footer static: a screen change whose buttons do not change (recent -> upnext with the same
        // four buttons): identical footer pixels in every capture.
        const char* sameButtons = R"([{"label":"Back","enabled":true,"icon":"back"},{"label":"Open","enabled":true,"icon":"expand"},{"label":"Play next","enabled":true,"icon":"playnext"},{"label":"Play","enabled":true,"icon":"play"}])";
        named.push_back({"v5-footer-static", "The footer never moves or fades on a screen change", {
            {0, recent, bright, E("none"), "baseline"},
            {600, bank.make(UPNEXT5, {{"buttons", sameButtons}}), bright, E("footerStatic"), "recent-to-upnext"},
            {1600, bank.make(EXPLORER5, {{"buttons", sameButtons}}), den, E("footerStatic"), "upnext-to-explorer"},
        }});

        // Text at rest (section 8.5.4): meta and status fade in over 160 ms; titles, sub-lines,
        // the Seek time and the Seek line swap instantly; a change on a screen change never fades.
        named.push_back({"v5-rest", "Meta/status 160 ms fades at rest; instant titles and Seek lines", {
            {0, recent, bright, E("none"), "baseline"},
            {600, bank.make(RECENT5, {{"meta", "\"Finding songs…\""}}), bright, E("line"), "meta-change"},
            {1200, bank.make(RECENT5, {{"meta", "\"Finding songs…\""}, {"title", "\"Kill for Love\""}}), bright, E("line"), "title-change"},
            {1800, bank.make(RECENT5, {{"meta", "\"Queueing… 1 of 4\""}}), bright, E("line"), "meta-and-title"},
            {2400, bank.make(RECENT5, {{"meta", "\"Queueing… 1 of 4\""}}), bright, E("identical"), "heartbeat-after-fade"},
            {2500, bank.make(RECENT5, {{"meta", "\"Queueing… 1 of 4\""}}), bright, E("identical"), "heartbeat"},
            {3000, home, den, E("back"), "to-home"},
            {3800, bank.make(HOME5, {{"status", "\"Paused\""}}), den, E("line"), "status-change"},
            {4400, bank.make(HOME5, {{"status", "\"Paused\""}, {"title", "\"Paper Lanterns\""}}), den, E("line"), "home-title"},
            {5000, tracks, den, E("deeper"), "to-tracks"},
            {5800, bank.make(TRACKS5, {{"meta", "\"Skipping…\""}}), den, E("line"), "tracks-meta"},
            {6400, seek, den, E("same"), "to-seek"},
            {7000, bank.make(SEEK5, {{"meta", "\"Jumping…\""}}), den, E("line"), "seek-line"},
            {7600, bank.make(SEEK5, {{"meta", "\"Jumping…\""}, {"ring", R"({"style":"lap","value":0,"index":79,"count":287})"}}), den,
             E("line"), "seek-time"},
            {8200, windows, nullptr, E("deeper"), "to-windows"},
            {9000, bank.make(WINDOWS5, {{"meta", "\"Switching…\""}}), nullptr, E("line"), "windows-meta"},
            {9600, bank.make(RECENT5, {{"meta", "\"Queued next\""}}), bright, E("artFadeBack"), "meta-with-screen-change"},
        }});

        // Ink crossfades (section 5.2): 160 ms OUT from the ink shown; glyph swaps instant.
        const CCFrame* liked = bank.make(UPNEXT5, {{"meta", "\"Liked\""}, {"buttons", R"([{"label":"Back","enabled":true,"icon":"back"},{"label":"Shuffle","enabled":true,"icon":"shuffle","lit":"off"},{"label":"Liked","enabled":true,"icon":"heart","lit":"on"},{"label":"Play","enabled":true,"icon":"play"}])"}});
        const CCFrame* shuffled = bank.make(UPNEXT5, {{"meta", "\"Shuffle on\""}, {"buttons", R"([{"label":"Back","enabled":true,"icon":"back"},{"label":"Shuffle","enabled":true,"icon":"shuffle","lit":"on"},{"label":"Liked","enabled":true,"icon":"heart","lit":"on"},{"label":"Play","enabled":true,"icon":"play"}])"}});
        const CCFrame* idleNothing = bank.make(IDLE5, {{"status", "\"\""}, {"artKey", "\"\""}, {"buttons", R"([{"label":"Play","enabled":false,"icon":"play"},{"label":"Browse","enabled":true,"icon":"list"},{"label":"Tracks","enabled":false,"icon":"tracks"},{"label":"Win","enabled":true,"icon":"win"}])"}});
        const CCFrame* idlePaused = bank.make(IDLE5, {{"artKey", "\"\""}});
        named.push_back({"v5-ink", "Tone ink crossfades: like lands (heartfill), Shuffle on, explorer tabs, idle Play", {
            {0, upnext, bright, E("none"), "baseline"},
            {600, liked, bright, E("ink"), "like-lands"},
            {1200, shuffled, bright, E("ink"), "shuffle-on"},
            {1800, bank.make(UPNEXT5, {{"meta", "\"Shuffle on\""}, {"buttons", R"([{"label":"Back","enabled":true,"icon":"back"},{"label":"Shuffle","enabled":true,"icon":"shuffle","lit":"on"},{"label":"Liked","enabled":true,"icon":"heart","lit":"on"},{"label":"Play","enabled":true,"icon":"play"}])"}}), bright,
             E("identical"), "heartbeat"},
            {2400, explorer0, den, E("inkDeeper"), "to-explorer"},
            {3200, explorer1, den, E("inkDeeper"), "tab-switch"},
            {4000, idleNothing, nullptr, E("inkBack"), "to-idle-nothing"},
            {5500, idlePaused, nullptr, E("ink"), "play-becomes-available"},
        }});

        // Reduced motion (section 8.9): no translate anywhere; fades and the stagger unchanged.
        const CCFrame* homeReduced = bank.make(HOME5, {{"reducedMotion", "true"}});
        const CCFrame* volumeFrame = bank.make(HOME5, {{"layout", "\"volume\""}, {"value", "\"55%\""}});
        const CCFrame* idleFrame = bank.make(IDLE5);
        named.push_back({"v5-reduced", "reducedMotion true: content fade only, reveal/idle opacity only", {
            {0, home, den, E("none"), "baseline"},
            {100, homeReduced, den, E("identical"), "latch-reduced"},
            {600, recent, bright, E("reducedSlide"), "home-to-recent"},
            {1400, home, den, E("reducedSlide"), "recent-to-home"},
            {2200, volumeFrame, den, E("reducedReveal"), "reveal"},
            {3800, home, den, E("reducedHide"), "reveal-out"},
            {5000, idleFrame, den, E("reducedIdle"), "idle-in"},
            {7000, home, den, E("reducedIdleOut"), "idle-out"},
            {8000, bank.make(HOME5, {{"reducedMotion", "false"}}), den, E("none"), "latch-full"},
            {8600, recent, bright, E("deeper"), "full-motion-again"},
        }});

        // Seek digits (sections 8.6.8, 10): detents redraw the time only; tabular cells.
        std::vector<Step> seekSteps = {{0, tracks, den, E("none"), "baseline"},
                                       {600, bank.make(SEEK5, {{"ring", R"({"style":"lap","value":0,"index":0,"count":59999})"}}), den, E("seek"), "0:00"}};
        const uint32_t seconds[] = {1, 9, 10, 59, 60, 61, 74, 119, 480, 599, 600, 601, 999, 1234, 3599, 3600, 3601, 35999, 59998};
        uint32_t t = 900;
        for (uint32_t s : seconds) {
            char ring[96], label[16];
            std::snprintf(ring, sizeof(ring), R"({"style":"lap","value":0,"index":%u,"count":59999})", s);
            cc_mmss(s, label, sizeof(label));
            seekSteps.push_back({t, bank.make(SEEK5, {{"ring", ring}}), den, E("seek"), label});
            t += 300;
        }
        named.push_back({"v5-seek", "Seek time per detent: cc_font_48t, no animation, fixed digit cells", seekSteps});

        // Offline screen (section 8.10): entry, native input, the next claim.
        // The baseline draws an artwork2 cover so the display-pin release after the fade is visible.
        const CCFrame* homeA2 = bank.make(HOME5, {{"artKey", "\"a2-hall\""}});
        named.push_back({"v5-offline", "Offline layer: entry, native input, return on the next claim", {
            {0, homeA2, nullptr, E("none"), "baseline", {{static_cast<uint8_t>(CC_DISPLAY_MEDIA_COVER), "a2-hall"}}},
            {600, nullptr, nullptr, E("offIn"), "lease-expired", {}, 0, STEP_OFFLINE},
            {1600, nullptr, nullptr, E("offNative"), "native-input", {}, 0, STEP_OFFLINE_NATIVE},
            {2600, recent, bright, E("offOut"), "claim", {}, 0, STEP_FRAME},
            {3600, nullptr, nullptr, E("offIn"), "lease-expired-again", {}, 0, STEP_OFFLINE},
            {4600, nullptr, nullptr, E("none"), "handback", {}, 0, STEP_HANDBACK},
            {5000, home, den, E("none"), "claim-after-handback"},
        }});

        // Art show/hide (section 8.4): 240 ms OUT fades; instant swaps over a visible cover.
        named.push_back({"v5-art", "Cover show/hide 240 ms: Windows, idle, notice, artKey \"\"; instant swaps", {
            {0, home, den, E("none"), "baseline"},
            {600, windows, nullptr, E("artFadeDeeper"), "to-windows"},
            {1600, home, den, E("artFadeBack"), "from-windows"},
            {2600, idleFrame, den, E("artFade"), "to-idle"},
            {4400, home, den, E("artFade"), "from-idle"},
            {5400, bank.make(NOTICE5), nullptr, E("artFade"), "to-notice"},
            {6400, home, den, E("artFade"), "from-notice"},
            {7400, bank.make(HOME5, {{"artKey", "\"\""}}), den, E("artFade"), "key-cleared"},
            {8400, home, den, E("artFade"), "key-back"},
            {9400, bank.make(HOME5, {{"artKey", "\"k-swap\""}, {"title", "\"Paper Lanterns\""}}), bright, E("artFade"), "instant-swap"},
        }});

        // Twin-fade probes (P5-13): the content, track and volume fades.
        // Over the brightest cover a v5 composite can be (white through the scrim, section 8.4).
        const uint8_t* scrim = artFixtures.at("scrim-white-120").data();
        const CCFrame* homeScrim = bank.make(HOME5, {{"artKey", "\"k-scrim\""}});
        named.push_back({"v5-twin-fade", "Twin fades vs a group-composited reference (content, track, volume)", {
            {0, homeScrim, scrim, E("none"), "baseline"},
            {600, bank.make(RECENT5, {{"artKey", "\"k-scrim\""}}), scrim, E("twinContent"), "content-fade"},
            {1600, homeScrim, scrim, E("none"), "home"},
            {2600, bank.make(HOME5, {{"artKey", "\"k-scrim\""}, {"layout", "\"volume\""}, {"value", "\"55%\""}}), scrim,
             E("twinTrack"), "reveal"},
            {3200, homeScrim, scrim, E("twinVolume"), "reveal-out"},
        }});

        // r4 motion moments (README 3.2): one timeline through M1-M15 on presentation-6 frames with covers, and the
        // same script under reduced motion (every moment a 160 ms opacity crossfade).
        auto r4Steps = [&](bool reduced) -> std::vector<Step> {
            const std::string rm = reduced ? "true" : "false";
            const Patch music = {{"crumb", "\"music\""}, {"playing", "true"}, {"holdMarker", "true"}, {"reducedMotion", rm}};
            auto homeWith = [&](Patch extra) { Patch p = music; p.insert(p.end(), extra.begin(), extra.end()); return bank.make(HOME5, p); };
            const char* playButtons = R"([{"label":"Play","enabled":true,"icon":"play"},{"label":"Browse","enabled":true,"icon":"list"},{"label":"Tracks","enabled":true,"icon":"tracks"},{"label":"Win","enabled":true,"icon":"win"}])";
            const CCFrame* home4 = homeWith({});
            const CCFrame* reveal4 = homeWith({{"layout", "\"volume\""}, {"value", "\"55%\""}});
            const CCFrame* song4 = homeWith({{"title", "\"Paper Lanterns\""}, {"volumeCaption", "\"Paper Lanterns\""}});
            const CCFrame* paused4 = homeWith({{"title", "\"Paper Lanterns\""}, {"volumeCaption", "\"Paper Lanterns\""},
                                               {"playing", "false"}, {"status", "\"Paused\""}, {"buttons", playButtons}});
            auto recentAt = [&](int index, const char* title, const char* extraMeta, bool feedback) {
                char ring[96], meta[64];
                std::snprintf(ring, sizeof(ring), R"({"style":"selection","value":0,"index":%d,"count":24,"first":0})", index);
                std::snprintf(meta, sizeof(meta), "\"%s\"", extraMeta);
                Patch p = {{"crumb", "\"recent\""}, {"holdMarker", "true"}, {"reducedMotion", rm}, {"ring", ring},
                           {"title", std::string("\"") + title + "\""}, {"meta", meta}};
                if (feedback) p.push_back({"feedback", R"({"kind":"ok","seq":7})"});
                return bank.make(RECENT5, p);
            };
            const CCFrame* r2 = recentAt(2, "Night Channel", "3 / 24", false);
            const CCFrame* r3 = recentAt(3, "Kill for Love", "4 / 24", false);
            const CCFrame* r4 = recentAt(4, "Lady", "5 / 24", false);
            const CCFrame* r5 = recentAt(5, "Tick of the Clock", "6 / 24", false);
            const CCFrame* r4b = recentAt(4, "Lady", "5 / 24", false);
            const CCFrame* queued = recentAt(4, "Lady", "Queued \xC2\xB7 Lady", true);
            // HN-DES-002: the wall on every other bounded layout (after the M1 back, which still leaves the list):
            // Volume 100 % / 0 %, Windows last, Scenes first, Seek 0:00, Up next last (the content moves 9 px towards
            // the wall whatever the layout).
            const CCFrame* vol100 = homeWith({{"layout", "\"volume\""}, {"value", "\"100%\""},
                                              {"ring", R"({"style":"level","value":100,"index":0,"count":101})"}});
            const CCFrame* vol0 = homeWith({{"layout", "\"volume\""}, {"value", "\"0%\""},
                                            {"ring", R"({"style":"level","value":0,"index":0,"count":101})"}});
            const CCFrame* windowsLast = bank.make(WINDOWS5, {{"reducedMotion", rm}, {"meta", "\"9 / 9\""},
                                                              {"ring", R"({"style":"selection","value":0,"index":8,"count":9})"}});
            const CCFrame* scenesFirst = bank.make(WINDOWS5, {
                {"reducedMotion", rm}, {"mode", "\"LIGHTS\""}, {"target", "\"LIGHTS\""}, {"layout", "\"scenes\""},
                {"heading", "\"SCENES\""}, {"title", "\"Scene 1\""}, {"prevTitle", "\"\""}, {"nextTitle", "\"Scene 2\""},
                {"subtitle", "\"\""}, {"meta", "\"1 / 5\""}, {"ring", R"({"style":"clusters","value":0,"index":0,"count":5})"},
                {"buttons", R"([{"label":"Back","enabled":true,"icon":"back"},{"label":"","enabled":false,"icon":""},{"label":"","enabled":false,"icon":""},{"label":"Run","enabled":true,"icon":"switch"}])"}});
            const CCFrame* seek0 = bank.make(SEEK5, {{"reducedMotion", rm}, {"value", "\"0:00\""},
                                                    {"ring", R"({"style":"lap","value":0,"index":0,"count":287})"}});
            const CCFrame* upNextLast = bank.make(UPNEXT5, {{"reducedMotion", rm}, {"meta", "\"12 / 12\""},
                                                            {"ring", R"({"style":"selection","value":0,"index":11,"count":12,"now":4})"}});
            std::vector<Step> v = {
                {0, home4, den, E("none"), "baseline"},
                {600, reveal4, den, E("reveal4"), "M2-reveal"},
                {2000, home4, den, E("hide4"), "M3-reveal-out"},
                {3200, song4, bright, E("glide"), "M5-track-change"},
                {4200, paused4, bright, E("popLine"), "M8-M9-M6-pause"},
                {5200, song4, bright, E("pop"), "M8-M9-play"},
                {6200, r2, bright, E(reduced ? "reducedSlide" : "deeper"), "M1-M15-push-recent"},
                {7200, r3, bright, E("glide"), "M4-detent"},
                {7330, r4, bright, E("glide"), "M4-fast-1"},
                {7460, r5, bright, E("glide"), "M4-fast-2"},
                {8200, r4b, bright, E("glide"), "M4-back"},
                {9000, nullptr, nullptr, E("hold"), "M7-M10-hold-4-down", {}, 0, STEP_KEYS, 8},
                {10100, queued, bright, E("popLine"), "M8-landing-queued"},
                {10300, nullptr, nullptr, E("press"), "hold-4-up", {}, 0, STEP_KEYS, 0},
                {11000, nullptr, nullptr, E("press"), "M7-press-2", {}, 0, STEP_KEYS, 2},
                {11300, nullptr, nullptr, E("press"), "M7-release-2", {}, 0, STEP_KEYS, 0},
                {12000, nullptr, nullptr, E("hold"), "M10-early-release-down", {}, 0, STEP_KEYS, 8},
                {12400, nullptr, nullptr, E("press"), "M10-early-release-up", {}, 0, STEP_KEYS, 0},
                {13200, nullptr, nullptr, E("wall"), "M13-wall-start", {}, 0, STEP_WALL, 0, -1},
                {14000, nullptr, nullptr, E("wall"), "M13-wall-end", {}, 0, STEP_WALL, 0, 1},
                {14120, nullptr, nullptr, E("wall"), "M13-wall-again", {}, 0, STEP_WALL, 0, 1},
                {15000, home4, den, E(reduced ? "reducedSlide" : "back"), "M1-M15-back-to-music"},
                {16000, vol100, den, E("none"), "M13-volume-100"},
                {16800, nullptr, nullptr, E("wall"), "M13-wall-volume-100", {}, 0, STEP_WALL, 0, 1},
                {17600, vol0, den, E("none"), "M13-volume-0"},
                {18400, nullptr, nullptr, E("wall"), "M13-wall-volume-0", {}, 0, STEP_WALL, 0, -1},
                {19200, windowsLast, nullptr, E("none"), "M13-windows-last"},
                {20000, nullptr, nullptr, E("wall"), "M13-wall-windows-last", {}, 0, STEP_WALL, 0, 1},
                {20800, scenesFirst, nullptr, E("none"), "M13-scenes-first"},
                {21600, nullptr, nullptr, E("wall"), "M13-wall-scenes-first", {}, 0, STEP_WALL, 0, -1},
                {22400, seek0, den, E("none"), "M13-seek-0"},
                {23200, nullptr, nullptr, E("wall"), "M13-wall-seek-0", {}, 0, STEP_WALL, 0, -1},
                {24000, upNextLast, bright, E("none"), "M13-up-next-last"},
                {24800, nullptr, nullptr, E("wall"), "M13-wall-up-next-last", {}, 0, STEP_WALL, 0, 1},
                {25600, home4, den, E(reduced ? "reducedSlide" : "none"), "M13-bounded-home"},
                // The latch goes back to full motion (the next timelines start without it).
                {26600, bank.make(HOME5, {{"crumb", "\"music\""}, {"playing", "true"}, {"holdMarker", "true"},
                                          {"reducedMotion", "false"}}), den, E("none"), "latch-full"},
            };
            return v;
        };
        named.push_back({"r4-moments", "r4 moments M1-M15 (README 3.2): push, reveal, glides, status, press, pop, morph, "
                                       "hold fill, wall, crumb", r4Steps(false)});
        named.push_back({"r4-reduced", "r4 moments under reduced motion: 160 ms opacity crossfades only", r4Steps(true)});
        // FW-DES-004: Recently Added's source toggle (button 3) recent -> playlists -> recent on the same group and
        // page: the crumb crossfades (M15) and the labels change in place; never a screen change, slide or glide.
        {
            auto source = [&](const char* crumb, int index, int count, const char* title, const char* meta) {
                char ring[96];
                std::snprintf(ring, sizeof(ring), R"({"style":"selection","value":0,"index":%d,"count":%d,"first":0})",
                              index, count);
                return bank.make(RECENT5, {{"crumb", std::string("\"") + crumb + "\""}, {"ring", ring},
                                           {"title", std::string("\"") + title + "\""},
                                           {"meta", std::string("\"") + meta + "\""}});
            };
            named.push_back({"r4-source-toggle", "Recently Added source toggle: crumb crossfade, labels in place", {
                {0, source("recent", 2, 24, "Night Channel", "3 / 24"), bright, E("none"), "baseline"},
                {800, source("playlists", 0, 9, "Late Night Mix", "1 / 9"), bright, E("sourceToggle"), "to-playlists"},
                {1800, source("recent", 2, 24, "Night Channel", "3 / 24"), bright, E("sourceToggle"), "back-to-recent"},
            }});
        }

        // r4 motion tour (README section 8) on the r3 screens (the Desk Dial captures of r3-handoff).
        {
            const std::vector<uint8_t> tourText = readFile(r3ScreensPath);
            static JsonDocument tourScreens;
            if (DeserializationError error = deserializeJson(tourScreens, reinterpret_cast<const char*>(tourText.data()), tourText.size()))
                throw std::runtime_error(std::string("r3_screens.json (tour): ") + error.c_str());
            auto screenOf = [&](const char* id, Patch patch = {}) -> std::pair<const CCFrame*, const uint8_t*> {
                for (JsonVariantConst item : tourScreens["screens"].as<JsonArrayConst>()) {
                    if (item["id"] != id) continue;
                    std::string text;
                    serializeJson(item["frame"], text);
                    return {bank.make(text.c_str(), patch), artFor(item["art"])};
                }
                throw std::runtime_error(std::string("tour: unknown r3 screen ") + id);
            };
            std::vector<Step> tour;
            auto frameAt = [&](uint32_t t, const char* id, const char* label, Patch patch = {}) {
                const auto f = screenOf(id, patch);
                tour.push_back({t, f.first, f.second, E("tour"), label});
            };
            auto keysAt = [&](uint32_t t, uint8_t keys, const char* label) {
                tour.push_back({t, nullptr, nullptr, E("tour"), label, {}, 0, STEP_KEYS, keys});
            };
            auto wallAt = [&](uint32_t t, int8_t dir, const char* label) {
                tour.push_back({t, nullptr, nullptr, E("tour"), label, {}, 0, STEP_WALL, 0, dir});
            };
            frameAt(0, "cap-home", "baseline", {{"holdMarker", "true"}});
            frameAt(600, "cap-home-turn", "0.6 Turn: volume reveal (M2)");
            frameAt(2000, "cap-home", "M3 reveal out", {{"holdMarker", "true"}});
            frameAt(2600, "cap-home-1", "2.6 Push into Music (M1, crumb)");
            frameAt(3500, "cap-music-2", "3.5 Push into Recently Added (M1, M15)", {{"holdMarker", "true"}});
            frameAt(4400, "cap-recent-turn", "4.4 List glides one row per notch (M4)", {{"holdMarker", "true"}});
            frameAt(4900, "cap-music-2", "4.9 glide back (M4)", {{"holdMarker", "true"}});
            wallAt(5700, -1, "5.7 Turn past the start: wall (M13)");
            keysAt(7000, 8, "7.0 Hold 4: icon fills (M10)");
            frameAt(8050, "cap-recent-hold-4", "8.05 lands with a pop, Queued (M8, M6)", {{"holdMarker", "true"}, {"feedback", R"({"kind":"ok","seq":41})"}});
            keysAt(8200, 0, "8.2 release");
            frameAt(9200, "cap-recent-3", "9.2 Tap 3: Playlists");
            frameAt(10200, "cap-playlists-3", "10.2 back");
            frameAt(11200, "cap-recent-1", "11.2 Back to Music (M1 reverse)");
            frameAt(12100, "cap-recent-1", "12.1 Pause: bars melt into the triangle (M9, M8)",
                    {{"playing", "false"}, {"status", "\"Paused\""},
                     {"buttons", R"([{"label":"Home","enabled":true,"icon":"house"},{"label":"Recent","enabled":true,"icon":"album"},{"label":"Tracks","enabled":true,"icon":"tracks"},{"label":"Play","enabled":true,"icon":"play"}])"}});
            frameAt(13300, "cap-recent-1", "13.3 Play (M9, M8)", {{"playing", "true"}});
            frameAt(14400, "cap-music-3", "14.4 Tracks (M1)");
            frameAt(15300, "cap-tracks-turn", "15.3 browse (M4)");
            frameAt(16300, "cap-tracks-4", "16.3 jump (M5)");
            keysAt(17400, 1, "17.4 Hold 1 (M7)");
            keysAt(18000, 0, "18.0 release");
            frameAt(18000, "cap-hold-1-from-music", "18.0 Home (M1 back)", {{"holdMarker", "true"}});
            keysAt(18800, 8, "18.8 Hold 4 on Home (M10)");
            frameAt(19850, "cap-home-hold-4", "19.85 lands: Lights (M12 ring, M1 lateral)", {{"holdMarker", "true"}, {"feedback", R"({"kind":"ok","seq":42})"}});
            keysAt(19900, 0, "19.9 release");
            frameAt(20600, "cap-home-lights-turn", "20.6 Brightness (M2)");
            // HN-DES-002: the brightness reaches 100 % (20.6 shows 66 %), settled before the turn past it.
            frameAt(21300, "cap-home-lights-turn", "21.3 Brightness at 100 % (M2)",
                    {{"value", "\"100\""}, {"subtitle", "\"100% \xC2\xB7 3200 K\""},
                     {"ring", R"({"style":"bri","value":100,"index":0,"count":0,"kelvin":3200})"}});
            wallAt(21800, 1, "21.8 Past 100 % (M13)");
            frameAt(23600, "cap-home-hold-4-again", "23.6 Hold 4 back to volume (M1)");
            frameAt(25200, "cap-home-2", "25.2 Windows: open (M1)");
            frameAt(26000, "cap-windows-turn", "26.0 turn (M4)");
            keysAt(26800, 2, "26.8 snap left (M7)");
            keysAt(27000, 0, "27.0 release");
            frameAt(27900, "cap-windows-3", "27.9 switch");
            named.push_back({"r4-tour", "r4 motion tour (README section 8) on the r3 screens", tour});
        }
    }

    // artwork2 timelines (ARTWORK2.md section 7; the late fade is v5's 240 ms, section 8.4).
    {
        std::deque<CCFrame> a2Frames;
        auto frameOf = [&](const char* json) -> const CCFrame* {
            JsonDocument doc;
            if (DeserializationError error = deserializeJson(doc, json))
                throw std::runtime_error(std::string("artwork2 timeline frame: ") + error.c_str());
            a2Frames.emplace_back();
            if (!parseFrame(doc.as<JsonVariantConst>(), a2Frames.back()))
                throw std::runtime_error("artwork2 timeline frame rejected");
            return &a2Frames.back();
        };
        auto caseFrame = [&](const char* id) -> const CCFrame* {
            for (const Artwork2Case& a2 : ARTWORK2_CASES)
                if (!std::strcmp(a2.id, id)) return frameOf(a2.json);
            throw std::runtime_error(std::string("unknown artwork2 case ") + id);
        };
        auto withArt = [&](const CCFrame* base, const char* key) -> const CCFrame* {
            a2Frames.push_back(*base);
            std::snprintf(a2Frames.back().artKey, sizeof(a2Frames.back().artKey), "%s", key);
            return &a2Frames.back();
        };
        auto copyOf = [&](const CCFrame* base) -> const CCFrame* {
            a2Frames.push_back(*base);
            return &a2Frames.back();
        };
        const uint8_t COVER = CC_DISPLAY_MEDIA_COVER, ICON = CC_DISPLAY_MEDIA_ICON;
        const CCFrame* np = caseFrame("a2-np-hall");
        const CCFrame* win = caseFrame("a2-win-icon");
        named.push_back({"a2-heartbeat", "artwork2: identical frames re-render nothing (JPEG cover, app icon)", {
            {0, np, nullptr, E("none"), "baseline", {{COVER, "a2-hall"}}},
            {1000, copyOf(np), nullptr, E("identical"), "heartbeat"},
            {1500, copyOf(np), nullptr, E("identical"), "unrelated-commit-home", {{COVER, "a2-bright"}, {ICON, "ic-chat"}}},
            {2000, win, nullptr, E("deeper"), "windows", {{ICON, "ic-code"}}},
            {3500, copyOf(win), nullptr, E("identical"), "heartbeat"},
            {4000, copyOf(win), nullptr, E("identical"), "unrelated-commit-windows", {{COVER, "a2-detail"}, {ICON, "ic-late"}}},
        }});
        const CCFrame* waiting = frameOf(
            R"({"id":980,"mode":"WINDOWS","target":"DESKTOP","value":"","detail":"","status":"","title":"ARTWORK2.md — NanoD_RatchetH1","subtitle":"Visual Studio Code","layout":"windows","iconKey":"ic-late","buttons":[{"label":"Cancel","enabled":true,"icon":"cancel"},{"label":"Home","enabled":true,"icon":"home"},{"label":"Win","enabled":true,"icon":"win"},{"label":"Switch","enabled":true,"icon":"switch"}],"ring":{"style":"selection","value":0,"index":1,"count":9}})");
        named.push_back({"a2-icon-late", "artwork2: an app icon committed after its frame appears at once", {
            {0, waiting, nullptr, E("none"), "baseline"},
            {300, copyOf(waiting), nullptr, E("identical"), "letter-meanwhile"},
            {600, copyOf(waiting), nullptr, E("icon"), "icon-arrives", {{ICON, "ic-late"}}},
            {1200, copyOf(waiting), nullptr, E("identical"), "heartbeat"},
        }});
        const CCFrame* lateFrame = withArt(np, "a2-late");
        named.push_back({"a2-cover-late", "artwork2: a JPEG cover committed after its frame fades in (240 ms)", {
            {0, win, nullptr, E("none"), "baseline"},
            {0, lateFrame, nullptr, E("none"), "key-without-pixels"},
            {600, copyOf(lateFrame), nullptr, E("late"), "cover-arrives", {{COVER, "a2-late"}}},
            {1600, copyOf(lateFrame), nullptr, E("identical"), "heartbeat"},
        }});
        const CCFrame* swapA = withArt(caseFrame("a2-recent-hall-dim"), "a2-swap-a");
        const CCFrame* swapB = withArt(caseFrame("a2-recent-bright"), "a2-swap-b");
        named.push_back({"a2-swap", "artwork2: front/back swap between two JPEG covers", {
            {0, swapA, nullptr, E("none"), "baseline", {{COVER, "a2-swap-a"}, {COVER, "a2-swap-b"}}},
            {500, swapB, nullptr, E("none"), "decode-b"},
            {1000, copyOf(swapA), nullptr, E("none"), "back-to-a"},
            {1500, copyOf(swapA), nullptr, E("identical"), "heartbeat"},
        }});
        const CCFrame* broken = withArt(np, "a2-progressive");
        named.push_back({"a2-decode-fail", "artwork2: a decode failure shows no art and is not retried", {
            {0, np, nullptr, E("none"), "baseline", {{COVER, "a2-hall"}, {COVER, "a2-progressive"}}},
            {500, broken, nullptr, E("none"), "decode-fails"},
            {1000, copyOf(broken), nullptr, E("identical"), "heartbeat"},
            {1500, copyOf(np), nullptr, E("artFade"), "other-key"},   // the hidden cover shows again: 240 ms
            {2000, copyOf(broken), nullptr, E("none"), "key-again"},
        }});
        const uint32_t SIM_DECODE_MS = 150;
        index["sim_decode_ms"] = SIM_DECODE_MS;
        const CCFrame* slideTo = withArt(caseFrame("a2-recent-bright"), "a2-slide");
        named.push_back({"a2-slide-decode", "artwork2: a 150 ms decode does not shorten the screen change", {
            {0, np, nullptr, E("none"), "baseline", {{COVER, "a2-hall"}}},
            {500, slideTo, nullptr, E("deeper"), "slide-decode", {{COVER, "a2-slide"}}, SIM_DECODE_MS},
            {1500, copyOf(np), nullptr, E("back"), "slide-back", {}, SIM_DECODE_MS},
        }});

        for (const Named& t : named) {
            JsonObject seqOut = timelines.add<JsonObject>();
            seqOut["id"] = t.id;
            seqOut["name"] = t.name;
            runTimeline(seqOut, t.id, t.steps, out);
        }

        // Native handback and the return (lcd_thread.cpp: cc_display_release_media()).
        JsonArray handback = index["handback"].to<JsonArray>();
        auto record = [&](const char* label, const CCDisplayStats& before) {
            JsonObject s = handback.add<JsonObject>();
            s["label"] = label;
            dumpStats(s, before);
            dumpMedia(s);
            JsonArray releases = s["releases"].to<JsonArray>();
            releases.add(store.releases[0]);
            releases.add(store.releases[1]);
            s["art_shown"] = drawn(findRole(screen, "art"));
            s["icon_shown"] = drawn(findRole(screen, "windows.icon"));
        };
        auto renderSettled = [&](const CCFrame* f, const char* label) {
            const CCDisplayStats before = cc_display_stats();
            cc_display_render(*f, nullptr);
            advance(1200);
            record(label, before);
        };
        auto handBack = [&](const char* label) {
            const CCDisplayStats before = cc_display_stats();
            cc_display_release_media();
            record(label, before);
        };
        resetStore();
        commitMedia(COVER, "a2-hall");
        renderSettled(np, "host-cover");
        handBack("handback-cover");
        renderSettled(copyOf(np), "return-cover");
        commitMedia(ICON, "ic-code");
        renderSettled(win, "host-icon");
        handBack("handback-icon");
        resetStore();
        renderSettled(copyOf(np), "return-evicted");
        renderSettled(copyOf(win), "windows-evicted");

        // R5 (section 12.5.7): the asynchronous decode with the scripted fake decoder (two buffers only).
        if (!oneBuffer) {
            CCDisplayMedia async = lookups;
            async.requestCover = fakeRequest;
            async.pollCover = fakePoll;
            async.cancelCover = fakeCancel;
            cc_display_set_media(async);
            fake.installed = true;
            renderedDecodeVersion = fake.version;
            JsonArray asyncOut = index["art_async"].to<JsonArray>();
            const CCFrame* recentBase = frameOf(ARTWORK2_CASES[3].json);   // a2-recent-bright
            auto keyed = [&](const char* key) { return withArt(recentBase, key); };
            // samePass: the step's frame lands in the LCD pass that sees a decode completing at t
            // (render_host_frame renders once per pass with whatever is current), so its render,
            // not a re-render of the previous frame, consumes that result.
            struct AsyncStep {
                uint32_t t; const CCFrame* frame; uint8_t action; const char* label; bool samePass = false;
            };
            auto runAsync = [&](const char* id, const char* what, uint32_t delay, std::vector<AsyncStep> steps,
                                std::vector<std::string> commits) {
                resetStore();
                for (const std::string& c : commits) commitMedia(COVER, c);
                fake.delayMs = delay;
                fake.events.clear();
                shownLog.clear();
                // Start from a settled frame whose cover is already shown (a5-k39, decoded to rest).
                commitMedia(COVER, "a5-k39");
                const CCFrame* start = keyed("a5-k39");
                cc_display_render(*start, nullptr);
                liveFrame = start;
                advance(1200);
                trackShown = true;
                noteShown();
                const CCDisplayStats before = cc_display_stats();
                const uint32_t t0 = fakeNow;
                const uint32_t requests0 = fake.requests, aborts0 = fake.aborts, front0 = fake.frontWrites;
                JsonObject o = asyncOut.add<JsonObject>();
                o["id"] = id;
                o["name"] = what;
                o["delay_ms"] = delay;
                // cc_art_decode.cpp + cc_jpeg.cpp's hook: a cancel stops the decode at the next MCU band;
                // band_ms is the longest wait for a poll (and the last band), ceil(delay / 15).
                o["abort_model"] = "mcu-band";
                o["band_ms"] = (delay + kFakeBands - 1) / kFakeBands;
                JsonArray stepLog = o["steps"].to<JsonArray>();
                for (const AsyncStep& s : steps) {
                    if (s.samePass && t0 + s.t > fakeNow) {
                        if (t0 + s.t > fakeNow + 1) advance(t0 + s.t - 1 - fakeNow, 1);
                        ++fakeNow;
                        fakeTick();
                        renderedDecodeVersion = fake.version;   // read before the render, as lcd_thread does
                    } else if (t0 + s.t > fakeNow) {
                        advance(t0 + s.t - fakeNow, 1);
                    }
                    JsonObject so = stepLog.add<JsonObject>();
                    so["t"] = s.t;
                    so["label"] = s.label;
                    if (s.action == STEP_HANDBACK) {
                        cc_display_release_media();
                        liveFrame = nullptr;
                    } else {
                        cc_display_render(*s.frame, nullptr);
                        liveFrame = s.frame;
                        so["key"] = std::string(s.frame->artKey);   // copied: ArduinoJson links const char*
                        so["layout"] = s.frame->layoutId;
                    }
                    so["shown"] = shownKey();
                }
                advance(1500, 1);
                trackShown = false;
                JsonObject st = o["stats"].to<JsonObject>();
                dumpStats(st, before);
                o["requests"] = fake.requests - requests0;
                o["aborts"] = fake.aborts - aborts0;
                o["front_writes"] = fake.frontWrites - front0;
                o["busy_at_end"] = fake.busy;
                JsonArray shown = o["shown"].to<JsonArray>();
                for (const ShownLog& s : shownLog) {
                    JsonArray row = shown.add<JsonArray>();
                    row.add(s.at - t0);
                    row.add(s.key);
                }
                JsonArray ev = o["events"].to<JsonArray>();
                for (const std::string& e : fake.events) ev.add(e);
                o["final_shown"] = shownKey();
                liveFrame = nullptr;
            };
            const CCFrame* A = keyed("a5-k00");
            const CCFrame* B = keyed("a5-k01");
            const CCFrame* C = keyed("a5-k02");
            runAsync("a-keys-inside-one-decode", "A -> B -> C inside one decode: only C is ever shown", 120,
                     {{0, A, 0, "A"}, {30, B, 0, "B"}, {60, C, 0, "C"}}, {"a5-k00", "a5-k01", "a5-k02"});
            runAsync("b-previous-stays", "the previous cover stays until the decode completes", 150,
                     {{0, keyed("a5-k03"), 0, "D"}}, {"a5-k03"});
            // F arrives in the pass that sees E's decode complete (the task read `cancel` unset): E's
            // ok result is stale when the F render consumes it. A cancel before the completion would
            // stop it at the next band and make it aborted instead (run a).
            runAsync("d-stale-discarded", "a decode finished for a key that moved on is discarded (stale ok)", 125,
                     {{0, keyed("a5-k04"), 0, "E"}, {125, keyed("a5-k05"), 0, "F", true}}, {"a5-k04", "a5-k05"});
            runAsync("e-failed-hides", "a failed decode hides the cover", 100, {{0, keyed("a5-fail"), 0, "broken"}},
                     {"a5-fail"});
            runAsync("f-no-art-layout", "a no-art layout during a decode cancels it; nothing shows after", 150,
                     {{0, keyed("a5-k06"), 0, "G"}, {40, win, 0, "windows"}}, {"a5-k06"});
            runAsync("f-release", "a release during a decode cancels it", 150,
                     {{0, keyed("a5-k07"), 0, "H"}, {40, nullptr, STEP_HANDBACK, "release"}}, {"a5-k07"});
            runAsync("g-spin-back", "a spin back to the running key before the abort lands", 120,
                     {{0, keyed("a5-k08"), 0, "I"}, {25, keyed("a5-k09"), 0, "J"}, {30, keyed("a5-k08"), 0, "I again"}},
                     {"a5-k08", "a5-k09"});
            // The same spin back one pass too late: the decoder stopped at band 4 (+32, `cancel` set
            // at +25) and I's frame lands in the pass that consumes that abort. The abort is discarded
            // (never a failure: the key is not marked failed, the cover not hidden) and the key is
            // posted again at once (12.5.4 step 5). Keys of its own (k30/k31): the run before leaves
            // k08 in a display buffer, which would be reused instead of decoded.
            runAsync("g-spin-back-after-abort", "a spin back in the pass that consumes the abort: I is posted again", 120,
                     {{0, keyed("a5-k30"), 0, "I"}, {25, keyed("a5-k31"), 0, "J"},
                      {32, keyed("a5-k30"), 0, "I again", true}},
                     {"a5-k30", "a5-k31"});
            {
                // cc_art_decode_result() (cc_art_decode.h), the task's mapping, over its whole domain.
                JsonArray map = index["art_decode_result"].to<JsonArray>();
                const CCJpegResult decodedValues[3] = {CC_JPEG_OK, CC_JPEG_FAILED, CC_JPEG_ABORTED};
                const char* decodedNames[3] = {"ok", "failed", "aborted"};
                const char* resultNames[3] = {"ok", "failed", "aborted"};   // CC_DECODE_OK, _FAILED, _ABORTED
                for (int d = 0; d < 3; ++d)
                    for (int c = 0; c < 2; ++c) {
                        JsonObject row = map.add<JsonObject>();
                        row["decoded"] = decodedNames[d];
                        row["cancelled_at_end"] = c == 1;
                        const uint8_t r = cc_art_decode_result(decodedValues[d], c == 1);
                        row["result"] = r < 3 ? resultNames[r] : "?";
                    }
            }
            {
                // (h) at the harness's decode time and at the ends of the device range (46-154 ms,
                // 12.5.5): the decode in flight at the last detent stops at its next band, so the
                // resting cover waits one decode time plus at most one band (12.5.4 step 2).
                std::vector<AsyncStep> spin;
                std::vector<std::string> commits;
                for (int k = 0; k < 20; ++k) {
                    char key[16];
                    std::snprintf(key, sizeof(key), "a5-k%02d", 10 + k);
                    commits.push_back(key);
                    spin.push_back({static_cast<uint32_t>(k * 83), keyed(key), 0, "detent"});
                }
                runAsync("h-spin-20-keys", "a 20-key spin at 12 detents/s: when the resting cover arrives (120 ms decodes)",
                         120, spin, commits);
                runAsync("h-spin-20-keys-d46", "the 20-key spin with 46 ms decodes (shorter than a detent)", 46, spin,
                         commits);
                runAsync("h-spin-20-keys-d154", "the 20-key spin with 154 ms decodes", 154, spin, commits);
            }
            fake.installed = false;
            cc_display_set_media(lookups);
        }
    }

    // Section 12.3 lcdLateRefrs / lcdMaxGapMs: cc_anim_cadence_poll() (lcd_thread's sampler) with
    // binary A's timing -- refresh and animation timers at 16 ms, one loop pass (render, then
    // lv_timer_handler) per 1 ms, lv_refr_now() after every changed render -- through every kind of
    // v5 tween. The pipeline here never stalls, so any late interval is a false alarm; the flush-to-
    // flush measure it replaced is replayed alongside. Then one injected 60 ms stall must count.
    if (!oneBuffer && !CC_DISPLAY_FULL_LAYERS) {
        JsonObject cad = index["cadence"].to<JsonObject>();
        // Pure vectors of cc_anim_cadence_sample(): {last_run, animating} sequences at period 16.
        struct CadenceVector { const char* name; std::vector<std::pair<uint32_t, bool>> samples; uint32_t late, gap; };
        const std::vector<CadenceVector> vectors = {
            {"idle only", {{100, false}, {116, false}}, 0, 0},
            {"on time", {{100, true}, {100, true}, {116, true}, {132, true}, {148, true}}, 0, 16},
            {"24 ms is not late, 25 is", {{100, true}, {124, true}, {149, true}}, 1, 25},
            {"an episode's first run is no interval", {{100, true}, {116, false}, {2000, true}, {2016, true}}, 0, 16},
            {"a stale last_run at priming is the next run's base", {{100, true}, {150, false}, {990, true}, {1006, true}},
             0, 16},
            {"wrap-around", {{0xFFFFFFF8u, true}, {8, true}, {24, true}}, 0, 16},
            {"a 60 ms stall", {{100, true}, {116, true}, {176, true}, {192, true}}, 1, 60},
        };
        JsonArray vout = cad["vectors"].to<JsonArray>();
        for (const CadenceVector& v : vectors) {
            CCAnimCadence c = {};
            for (const auto& sample : v.samples) cc_anim_cadence_sample(c, sample.first, sample.second, 16);
            JsonObject o = vout.add<JsonObject>();
            o["name"] = v.name;
            o["late"] = c.lateRuns;
            o["max_gap_ms"] = c.maxGapMs;
            o["want_late"] = v.late;
            o["want_max_gap_ms"] = v.gap;
        }

        const uint32_t period = 16;
        lv_timer_t* refrTimer = lv_display_get_refr_timer(display);
        lv_timer_set_period(refrTimer, period);
        lv_timer_set_period(lv_anim_get_timer(), period);
        lv_display_add_event_cb(display, flushGapStart, LV_EVENT_REFR_START, nullptr);
        lv_display_add_event_cb(display, flushGapReady, LV_EVENT_REFR_READY, nullptr);
        resetStore();
        const CCFrame* home = bank.make(HOME5);
        const CCFrame* recent = bank.make(RECENT5);
        const CCFrame* detent = bank.make(RECENT5, {{"title", "\"Kids\""}, {"subtitle", "\"MGMT\""}, {"meta", "\"4 / 24\""}});
        const CCFrame* volume = bank.make(HOME5, {{"layout", "\"volume\""}, {"value", "\"55%\""}});
        const CCFrame* idle = bank.make(IDLE5);
        const CCFrame* noArt = bank.make(HOME5, {{"artKey", "\"\""}});
        cc_display_render(*home, den);
        advance(1200);
        struct CadenceStep { uint32_t t; const CCFrame* frame; const uint8_t* art; uint8_t action; const char* label; };
        const std::vector<CadenceStep> script = {
            {0, recent, bright, STEP_FRAME, "slide-deeper"},
            {600, home, den, STEP_FRAME, "slide-back"},
            {1200, volume, den, STEP_FRAME, "volume-reveal"},
            {1800, home, den, STEP_FRAME, "volume-hide"},
            {2400, idle, den, STEP_FRAME, "idle-enter"},
            {3400, home, den, STEP_FRAME, "idle-exit"},
            {4400, recent, bright, STEP_FRAME, "slide-deeper-again"},
            {6600, detent, bright, STEP_FRAME, "detent-2s-after-the-slide"},
            {7400, noArt, nullptr, STEP_FRAME, "cover-hide"},
            {8000, home, den, STEP_FRAME, "cover-show"},
            {8600, nullptr, nullptr, STEP_OFFLINE, "offline-in"},
            {9400, nullptr, nullptr, STEP_OFFLINE_NATIVE, "native-tap"},
            {10200, home, den, STEP_FRAME, "claim"},
        };
        CCAnimCadence cadence = {};
        flushGap = FlushGapMetric{};
        flushGap.on = true;
        flushGap.periodMs = period;
        cadenceRuns = 0;
        cadenceSeenRun = lv_anim_get_timer()->last_run;
        cadenceProbe = &cadence;
        offlineLive = false;
        const uint32_t t0 = fakeNow;
        JsonArray stepsOut = cad["steps"].to<JsonArray>();
        for (const CadenceStep& s : script) {
            if (t0 + s.t > fakeNow) advance(t0 + s.t - fakeNow, 1);
            if (s.action == STEP_FRAME) {
                offlineLive = false;
                cc_display_render(*s.frame, s.art);
            } else {
                if (!offlineLive) cc_offline_input_reset(offlineIn);
                offlineLive = true;
                if (s.action == STEP_OFFLINE_NATIVE) fakeKeyEdges += 2;
                cc_display_offline(cc_offline_input_update(offlineIn, fakePos, fakeKeyEdges));
            }
            const bool changed = cc_display_stats().lastChanged;
            if (changed) lv_refr_now(display);   // lcd_thread presents every changed render at once
            JsonObject o = stepsOut.add<JsonObject>();
            o["t"] = s.t;
            o["label"] = s.label;
            o["animated"] = cc_display_stats().lastAnimated;
            o["late"] = cadence.lateRuns;
            o["max_gap_ms"] = cadence.maxGapMs;
            o["flush_gap_late"] = flushGap.late;
            o["flush_gap_max_ms"] = flushGap.maxGapMs;
        }
        advance(1200, 1);
        offlineLive = false;
        JsonObject perfect = cad["perfect"].to<JsonObject>();
        perfect["period_ms"] = period;
        perfect["loop_ms"] = 1;
        perfect["late"] = cadence.lateRuns;
        perfect["max_gap_ms"] = cadence.maxGapMs;
        perfect["anim_timer_runs"] = cadenceRuns;
        perfect["flush_gap_late"] = flushGap.late;
        perfect["flush_gap_max_ms"] = flushGap.maxGapMs;

        // One stall: 60 ms without a loop pass (a synchronous decode, a long refresh) mid-slide.
        CCAnimCadence stalled = {};
        cadenceProbe = &stalled;
        cc_display_render(*recent, bright);
        lv_refr_now(display);
        advance(100, 1);
        fakeNow += 60;
        advance(900, 1);
        JsonObject stall = cad["stall"].to<JsonObject>();
        stall["stall_ms"] = 60;
        stall["late"] = stalled.lateRuns;
        stall["max_gap_ms"] = stalled.maxGapMs;
        cadenceProbe = nullptr;

        // FW-BUG-044 cadence_ignores_paused_lvgl: an app frame arrives mid-slide, so lcd_thread skips
        // lv_timer_handler() (app_on) while the slide stays listed and the animation timer's last_run stays
        // frozen; 500 such 1 ms passes. Then the app exits: the host frame is rendered again (a slide starts, as
        // render_host_frame() does after app_exit()) and LVGL resumes. With the pause passed to the poll
        // (lcd_thread's perfCadence(app_on)) the session ends the episode: nothing late, no session-long gap.
        // The control polls the same passes as if LVGL ran (the old perfCadence()) and must count the gap.
        for (int fixed = 0; fixed < 2; ++fixed) {
            CCAnimCadence app = {};
            cadenceProbe = &app;
            cc_display_render(*home, den);
            lv_refr_now(display);
            advance(40, 1);
            const uint32_t lateBefore = app.lateRuns;
            const bool listed = lv_anim_count_running() > 0;
            const uint32_t frozenRun = lv_anim_get_timer()->last_run;
            cadenceProbe = nullptr;
            for (int pass = 0; pass < 500; ++pass) {
                ++fakeNow;
                cc_anim_cadence_poll(app, fixed != 0);
            }
            cc_display_render(*recent, bright);
            lv_refr_now(display);
            cadenceProbe = &app;
            advance(600, 1);
            cadenceProbe = nullptr;
            JsonObject o = cad[fixed ? "app_session" : "app_session_control"].to<JsonObject>();
            o["passes"] = 500;
            o["listed_at_entry"] = listed;
            o["timer_ran_after"] = lv_anim_get_timer()->last_run != frozenRun;
            o["late_before"] = lateBefore;
            o["late"] = app.lateRuns;
            o["max_gap_ms"] = app.maxGapMs;
        }
        flushGap.on = false;
        lv_timer_set_period(refrTimer, LV_DEF_REFR_PERIOD);
        lv_timer_set_period(lv_anim_get_timer(), LV_DEF_REFR_PERIOD);

        // cc_offline_input_update() vectors: passes of {pos, keyEdges} (reset: a claim or handback
        // before that pass), then whether native input was seen at the last pass.
        struct OfflinePass { uint16_t pos; uint32_t edges; bool reset; };
        struct OfflineVector { const char* name; std::vector<OfflinePass> passes; bool want; };
        const std::vector<OfflineVector> offlineVectors = {
            {"first pass only arms", {{10, 5, false}}, false},
            {"nothing moved", {{10, 5, false}, {10, 5, false}, {10, 5, false}}, false},
            {"a knob turn", {{10, 5, false}, {11, 5, false}}, true},
            {"a tap between two passes (press + release)", {{10, 5, false}, {10, 7, false}}, true},
            {"a press still held", {{10, 5, false}, {10, 6, false}}, true},
            {"latched after the position returns", {{10, 5, false}, {11, 5, false}, {10, 5, false}}, true},
            {"edge counter wrap", {{10, 0xFFFFFFFFu, false}, {10, 0, false}}, true},
            {"no button source (edges 0), knob still", {{10, 0, false}, {10, 0, false}}, false},
            {"a claim resets: the next layer re-arms", {{10, 5, false}, {11, 5, false}, {11, 5, true}, {11, 5, false}},
             false},
        };
        JsonArray oout = cad["offline_input"].to<JsonArray>();
        for (const OfflineVector& v : offlineVectors) {
            CCOfflineInput in = {};
            bool native = false;
            for (const OfflinePass& pass : v.passes) {
                if (pass.reset) cc_offline_input_reset(in);
                native = cc_offline_input_update(in, pass.pos, pass.edges);
            }
            JsonObject o = oout.add<JsonObject>();
            o["name"] = v.name;
            o["native"] = native;
            o["want"] = v.want;
        }
    }

    // Host-frame redraw latency: a non-animated text change waits for the refresh timer unless
    // lv_refr_now().
    if (!oneBuffer) {
        JsonObject latency = index["latency"].to<JsonObject>();
        const CCFrame* detents[2] = {nullptr, nullptr};
        static CCFrame a, b;
        for (JsonVariantConst item : fixture["cases"].as<JsonArrayConst>()) {
            const std::string id = item["id"].as<std::string>();
            if (id == "ra-item") parseFrame(item["frame"], a), detents[0] = &a;
            if (id == "ra-hounds") parseFrame(item["frame"], b), detents[1] = &b;
        }
        if (!detents[0] || !detents[1]) throw std::runtime_error("latency frames missing");
        cc_display_render(*detents[0], den);
        advance(1200);
        JsonArray waits = latency["timer_wait_ms"].to<JsonArray>();
        JsonArray gaps = latency["gap_ms"].to<JsonArray>();
        uint32_t worst = 0;
        bool anyAnimated = false;
        for (uint32_t gap = 0; gap <= 32; gap += 4) {
            cc_display_render(*detents[1], den);
            for (uint32_t first = flushes, guard = 0; flushes == first && guard < 200; ++guard) advance(1, 1);
            if (gap) advance(gap, 1);
            cc_display_render(*detents[0], den);
            anyAnimated = anyAnimated || cc_display_stats().lastAnimated;
            const uint32_t before = flushes;
            uint32_t waited = 0;
            while (flushes == before && waited < 200) { advance(1, 1); ++waited; }
            gaps.add(gap);
            waits.add(waited);
            worst = std::max(worst, waited);
        }
        latency["animated_in_sample"] = anyAnimated;
        cc_display_render(*detents[1], den);
        const uint32_t before = flushes;
        const auto t0 = std::chrono::steady_clock::now();
        lv_refr_now(display);
        const auto t1 = std::chrono::steady_clock::now();
        latency["timer_wait_worst_ms"] = worst;
        latency["lv_def_refr_period_ms"] = LV_DEF_REFR_PERIOD;
        latency["refr_now_flushes"] = flushes - before;
        latency["refr_now_host_us"] = std::chrono::duration_cast<std::chrono::microseconds>(t1 - t0).count();
        latency["note"] = "lcd_thread calls lv_refr_now() after a render with lastChanged && !lastAnimated: the change "
                          "reaches the panel in the same pass instead of waiting up to LV_DEF_REFR_PERIOD for the "
                          "refresh timer; host time is informative only (ESP32-S3 SPI transfer dominates).";
    }

    // FW-RES-001: every named timeline replayed SOAK_ROUNDS more times (no captures); the LVGL pool's
    // used bytes after each round go to render-index.json "soak" (display_soak_tests.py: no growth).
    if (!oneBuffer && !CC_DISPLAY_FULL_LAYERS) {
        constexpr int SOAK_ROUNDS = 4;
        JsonObject soak = index["soak"].to<JsonObject>();
        soak["rounds"] = SOAK_ROUNDS;
        soak["timelines"] = static_cast<uint32_t>(named.size());
        soak["used_before_create"] = static_cast<uint32_t>(usedBeforeCreate);
        soak["used_after_create"] = static_cast<uint32_t>(usedAfterCreate);
        soak["used_after_first_frame"] = static_cast<uint32_t>(usedAfterFirstFrame);
        soak["used_before_soak"] = static_cast<uint32_t>(lvglUsedNow());
        JsonArray usedAfter = soak["used_after_round"].to<JsonArray>();
        JsonArray freeBiggest = soak["free_biggest_after_round"].to<JsonArray>();
        heapContext = "soak";
        uint32_t soakCases = 0;
        for (int round = 0; round < SOAK_ROUNDS; ++round) {
            for (const Named& t : named) soakTimeline(t.steps);
            // Every accepted case frame again (every layout, token and state), with its cover when it had one.
            resetStore();
            for (JsonVariantConst c : index["cases"].as<JsonArrayConst>()) {
                if (c["kind"] != "frame") continue;
                static CCFrame soakFrame;
                if (!parseFrame(c["wire"], soakFrame)) continue;
                liveFrame = nullptr;
                const auto art = c["art"].is<const char*>() ? artFixtures.find(c["art"].as<const char*>()) : artFixtures.end();
                cc_display_render(soakFrame, art != artFixtures.end() ? art->second.data() : nullptr);
                advance(600);
                if (round == 0) ++soakCases;
            }
            liveFrame = nullptr;
            lv_mem_monitor_t m{};
            lv_mem_monitor(&m);
            usedAfter.add(static_cast<uint32_t>(m.total_size - m.free_size));
            freeBiggest.add(static_cast<uint32_t>(m.free_biggest_size));
        }
        soak["cases"] = soakCases;
    }

    lv_mem_monitor_t monitor{};
    lv_mem_monitor(&monitor);
    JsonObject heap = index["heap"].to<JsonObject>();
    heap["lv_mem_size"] = static_cast<uint32_t>(LV_MEM_SIZE);
    heap["total_size"] = static_cast<uint32_t>(monitor.total_size);
    heap["free_size"] = static_cast<uint32_t>(monitor.free_size);
    heap["free_biggest_size"] = static_cast<uint32_t>(monitor.free_biggest_size);
    heap["max_used"] = static_cast<uint32_t>(monitor.max_used);
    heap["peak_used_sampled"] = static_cast<uint32_t>(peakUsed);
    heap["peak_where"] = heapWhere;
    heap["used_pct"] = monitor.used_pct;
    heap["frag_pct"] = monitor.frag_pct;
    heap["pointer_bytes"] = static_cast<uint32_t>(sizeof(void*));
    heap["note"] = "Host x64 build: LVGL objects carry 8-byte pointers, so this over-estimates the ESP32-S3 (4-byte) use.";
    index["rejected_frames"] = rejected;
    index["re_renders"] = reRenders;
    const CCDisplayStats& s = cc_display_stats();
    JsonObject totals = index["display_stats"].to<JsonObject>();
    totals["renders"] = s.renders;
    totals["text_sets"] = s.textSets;
    totals["animations"] = s.animations;
    totals["slides"] = s.slides;
    totals["art_upscales"] = s.artUpscales;
    totals["art_decodes"] = s.artDecodes;
    totals["art_decode_errors"] = s.artDecodeErrors;
    totals["art_reuses"] = s.artReuses;
    totals["icon_loads"] = s.iconLoads;
    totals["art_decode_requests"] = s.artDecodeRequests;
    totals["art_decode_aborts"] = s.artDecodeAborts;
    totals["art_decode_stale"] = s.artDecodeStale;
    totals["ink_fades"] = s.inkFades;
    totals["line_fades"] = s.lineFades;
    JsonObject standIn = index["media_standin"].to<JsonObject>();
    standIn["adopts"] = store.adopts[0] + store.adopts[1];
    standIn["hits"] = store.hits[0] + store.hits[1];
    standIn["releases"] = store.releases[0] + store.releases[1];
    standIn["decodes"] = store.decodes;
    standIn["decode_failures"] = store.decodeFailures;

    std::string text;
    serializeJsonPretty(index, text);
    std::ofstream(out / "render-index.json", std::ios::binary) << text;
    std::string heapText;
    serializeJsonPretty(heap, heapText);
    std::ofstream(out / "lvgl-heap.json", std::ios::binary) << heapText;
    std::printf("cc5.4 harness%s: %u cases, %u timelines, %d rejected; LVGL heap max_used %u B, sampled peak %u B "
                "(%.1f%% of %u), frag %u%%\n",
                CC_DISPLAY_FULL_LAYERS ? " (full layers)" : "",
                static_cast<unsigned>(cases.size()), static_cast<unsigned>(timelines.size()), rejected,
                static_cast<unsigned>(monitor.max_used), static_cast<unsigned>(peakUsed),
                100.0 * static_cast<double>(std::max<size_t>(peakUsed, monitor.max_used)) / LV_MEM_SIZE,
                static_cast<unsigned>(LV_MEM_SIZE), static_cast<unsigned>(monitor.frag_pct));
    lv_deinit();
    return rejected ? 1 : 0;
} catch (const std::exception& error) {
    std::fprintf(stderr, "lcd-preview failed: %s\n", error.what());
    return 1;
}
