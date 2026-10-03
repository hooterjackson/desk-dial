// r4 render-speed profile (design_handoff_nano_d_r4 README section 9: ">= 30 fps during M1, M4 and M13 with
// artwork on screen"; plan "Measured 2026-09-30: render time is the bottleneck"). Host-only, no USB.
//
// The firmware's own renderer (src/cc_display.cpp), parser, icons, crumbs and fonts on the firmware lv_conf.h
// (LVGL 9.0.0, 64 KB heap), PARTIAL mode with the knob's draw buffer (11,520 B = 24 rows; --rows N tries
// another height), a fake tick stepped by the knob's LVGL period (--period N, default 12 ms: binary F's
// CC_LCD_PERIOD_MS; 16 reproduces binary D and the older perf/*.json). Each scenario alternates two
// frames (or fires a wall / detent) many times and records, for every refresh that flushed pixels:
//   - host time inside lv_timer_handler() (QueryPerformanceCounter; Release build of LVGL, x64). Absolute
//     numbers are the PC's, not the ESP32-S3's; ratios between variants and scenarios are what carries over;
//   - pixels flushed and draw-buffer chunks (flush calls): the SPI share and the per-chunk re-walk;
//   - objects that LVGL renders through an intermediate layer (transform, opa_layered, blend mode,
//     clip_corner with a radius): each would allocate an ARGB8888 layer (LV_DRAW_SW_LAYER_SIMPLE_BUF_SIZE
//     slices) -- the plan's leading suspect;
//   - A8 image draws that LVGL 9.0.0's bin decoder copies (decode_alpha_only(): lv_malloc + memcpy of the
//     WHOLE mask on every draw, i.e. on every chunk the image touches, with LV_CACHE_DEF_SIZE 0), counted
//     with a pass-through decoder at the head of the list, and the bytes that copy would move.
// Output: JSON on stdout (perf.py saves it).
#include "lvgl.h"
#include <ArduinoJson.h>
#include "cc_display.h"
#include "cc_frame_parse.h"
#include "src/core/lv_global.h"
#if __has_include("cc_wall.h")
#include "cc_wall.h"
#endif

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

namespace {
constexpr int W = 240, H = 240;
uint32_t periodMs = 12;   // --period: binary F's CC_LCD_PERIOD_MS
alignas(4) unsigned char drawBuf[W * H * 2];
uint16_t framebuffer[W * H];
alignas(4) uint8_t art240[2][CC_ART240_BYTES];
std::vector<uint8_t> art120[2];
lv_display_t* display = nullptr;
uint32_t fakeNow = 0;
uint32_t tickCb() { return fakeNow; }

uint32_t flushCalls = 0, flushPx = 0;
void flush(lv_display_t* disp, const lv_area_t* area, uint8_t* px) {
    const uint16_t* src = reinterpret_cast<const uint16_t*>(px);
    for (int y = area->y1; y <= area->y2; ++y)
        for (int x = area->x1; x <= area->x2; ++x) {
            const uint16_t c = *src++;
            if (x >= 0 && x < W && y >= 0 && y < H) framebuffer[y * W + x] = c;
        }
    ++flushCalls;
    flushPx += static_cast<uint32_t>((area->x2 - area->x1 + 1) * (area->y2 - area->y1 + 1));
    lv_display_flush_ready(disp);
}

// Pass-through decoder at the head of the decoder list: counts A8 variable-image lookups (each one is a
// draw that the bin decoder would copy in full) and never claims an image.
uint32_t a8Draws = 0, a8Bytes = 0, rgbDraws = 0;
lv_result_t countInfo(lv_image_decoder_t*, const void* src, lv_image_header_t*) {
    if (lv_image_src_get_type(src) == LV_IMAGE_SRC_VARIABLE) {
        const lv_image_dsc_t* d = static_cast<const lv_image_dsc_t*>(src);
        if (d->header.cf == LV_COLOR_FORMAT_A8) { ++a8Draws; a8Bytes += d->header.stride * d->header.h; }
        else ++rgbDraws;
    }
    return LV_RESULT_INVALID;
}
lv_result_t countOpen(lv_image_decoder_t*, lv_image_decoder_dsc_t*) { return LV_RESULT_INVALID; }

// Objects that LVGL 9.0.0 refreshes through a layer (lv_refr.c refr_obj / calculate_layer_type, plus
// clip_corner with a radius), among the drawn (not hidden) objects.
void countLayers(lv_obj_t* obj, uint32_t& layered, uint32_t& transformed, uint32_t& objects, uint32_t& opaBelow) {
    if (lv_obj_has_flag(obj, LV_OBJ_FLAG_HIDDEN)) return;
    ++objects;
    const bool transform = lv_obj_get_style_transform_rotation(obj, 0) != 0 ||
                           lv_obj_get_style_transform_scale_x(obj, 0) != 256 ||
                           lv_obj_get_style_transform_scale_y(obj, 0) != 256 ||
                           lv_obj_get_style_transform_skew_x(obj, 0) != 0 || lv_obj_get_style_transform_skew_y(obj, 0) != 0;
    const bool simple = lv_obj_get_style_opa_layered(obj, 0) != LV_OPA_COVER ||
                        lv_obj_get_style_blend_mode(obj, 0) != LV_BLEND_MODE_NORMAL ||
                        (lv_obj_get_style_clip_corner(obj, 0) && lv_obj_get_style_radius(obj, 0) > 0 &&
                         lv_obj_get_child_count(obj) > 0);
    if (transform) ++transformed;
    if (transform || simple) ++layered;
    if (lv_obj_get_style_opa(obj, 0) < LV_OPA_COVER) ++opaBelow;
    for (uint32_t i = 0; i < lv_obj_get_child_count(obj); ++i)
        countLayers(lv_obj_get_child(obj, static_cast<int32_t>(i)), layered, transformed, objects, opaBelow);
}

double qpcUs() {
    static LARGE_INTEGER f = {};
    if (!f.QuadPart) QueryPerformanceFrequency(&f);
    LARGE_INTEGER t;
    QueryPerformanceCounter(&t);
    return static_cast<double>(t.QuadPart) * 1e6 / static_cast<double>(f.QuadPart);
}

struct Sample { double us; uint32_t px, chunks; uint32_t a8, a8Bytes, a8Direct; };
struct Stats {
    std::vector<Sample> refreshes;
    uint32_t maxLayered = 0, maxTransformed = 0, maxObjects = 0, maxOpaBelow = 0, renders = 0;
    double renderUs = 0;
};

// One LVGL pass at the knob's cadence: advance the fake tick one period, run the timers once.
void pass(Stats& s) {
    fakeNow += periodMs;
    flushCalls = flushPx = a8Draws = a8Bytes = 0;
    uint32_t layered = 0, transformed = 0, objects = 0, opaBelow = 0;
    countLayers(lv_screen_active(), layered, transformed, objects, opaBelow);
    const uint32_t direct0 = cc_display_stats().a8Direct;
    const double t0 = qpcUs();
    lv_timer_handler();
    const double us = qpcUs() - t0;
    if (flushPx) s.refreshes.push_back({us, flushPx, flushCalls, a8Draws, a8Bytes, cc_display_stats().a8Direct - direct0});
    s.maxLayered = std::max(s.maxLayered, layered);
    s.maxTransformed = std::max(s.maxTransformed, transformed);
    s.maxObjects = std::max(s.maxObjects, objects);
    s.maxOpaBelow = std::max(s.maxOpaBelow, opaBelow);
}

void render(Stats& s, const CCFrame& f, const uint8_t* art) {
    const double t0 = qpcUs();
    cc_display_render(f, art);
    s.renderUs += qpcUs() - t0;
    ++s.renders;
    // lcd_thread presents a changed render at once (lv_refr_now); the timer carries the animation.
    flushCalls = flushPx = a8Draws = a8Bytes = 0;
    const uint32_t direct0 = cc_display_stats().a8Direct;
    const double t1 = qpcUs();
    lv_refr_now(display);
    const double us = qpcUs() - t1;
    if (flushPx) s.refreshes.push_back({us, flushPx, flushCalls, a8Draws, a8Bytes, cc_display_stats().a8Direct - direct0});
}

// `ms` of knob time as the nearest whole number of LVGL passes (at 16 ms: exactly the passes of the 16 ms-only
// profile, so older perf/*.json stay comparable at --period 16).
void settle(Stats* s, uint32_t ms) {
    Stats scratch;
    const uint32_t passes = (ms + periodMs / 2) / periodMs;
    for (uint32_t k = 0; k < passes; ++k) pass(s ? *s : scratch);
}

// Per-task-type host time: the SW draw unit's dispatch_cb takes one task per call (lv_draw_sw.c dispatch());
// the wrapper peeks the task it will take (the same lookup) and times the call.
int32_t (*swDispatch)(lv_draw_unit_t*, lv_layer_t*) = nullptr;
double taskUs[32] = {};
uint32_t taskCount[32] = {};
uint64_t taskArea[32] = {};
int32_t timedDispatch(lv_draw_unit_t* unit, lv_layer_t* layer) {
    lv_draw_task_t* t = lv_draw_get_next_available_task(layer, nullptr, 1 /* DRAW_UNIT_ID_SW */);
    const int type = t ? static_cast<int>(t->type) & 31 : -1;
    lv_area_t a = t ? t->area : lv_area_t{0, 0, -1, -1};
    const double t0 = qpcUs();
    const int32_t taken = swDispatch(unit, layer);
    if (type >= 0 && taken > 0) {
        taskUs[type] += qpcUs() - t0;
        ++taskCount[type];
        lv_area_t clipped;
        if (_lv_area_intersect(&clipped, &a, &layer->_clip_area)) taskArea[type] += lv_area_get_size(&clipped);
    }
    return taken;
}
void installTaskTimer() {
    lv_draw_unit_t* u = LV_GLOBAL_DEFAULT()->draw_info.unit_head;
    if (u && !swDispatch) { swDispatch = u->dispatch_cb; u->dispatch_cb = timedDispatch; }
}
void resetTaskTimer() { std::memset(taskUs, 0, sizeof(taskUs)); std::memset(taskCount, 0, sizeof(taskCount)); std::memset(taskArea, 0, sizeof(taskArea)); }
void emitTasks(JsonObject o, uint32_t refreshes) {
    static const char* const names[] = {"fill", "border", "box_shadow", "label", "image", "layer", "line", "arc",
                                        "triangle", "mask_rectangle", "mask_bitmap", "vector"};
    for (int k = 0; k < 12; ++k) {
        if (!taskCount[k]) continue;
        JsonObject e = o[names[k]].to<JsonObject>();
        e["us_per_refresh"] = taskUs[k] / refreshes;
        e["tasks_per_refresh"] = static_cast<double>(taskCount[k]) / refreshes;
        e["clipped_px_per_refresh"] = static_cast<double>(taskArea[k]) / refreshes;
    }
}

// Objects by their renderer role tag (cc_display.cpp tag(): the user_data string).
void byRole(lv_obj_t* obj, const char* suffix, bool prefix, std::vector<lv_obj_t*>& out) {
    const char* role = static_cast<const char*>(lv_obj_get_user_data(obj));
    if (role) {
        const size_t n = std::strlen(role), k = std::strlen(suffix);
        if (prefix ? std::strncmp(role, suffix, k) == 0 : (n >= k && std::strcmp(role + n - k, suffix) == 0)) out.push_back(obj);
    }
    for (uint32_t i = 0; i < lv_obj_get_child_count(obj); ++i) byRole(lv_obj_get_child(obj, static_cast<int32_t>(i)), suffix, prefix, out);
}

// Median host time of `reps` full redraws of the content box (the area M1 / M13 invalidate every frame).
double contentRedrawUs(int reps) {
    std::vector<lv_obj_t*> content;
    byRole(lv_screen_active(), "content", true, content);
    std::vector<double> us;
    for (int r = 0; r < reps; ++r) {
        lv_obj_invalidate(content.front());
        const double t0 = qpcUs();
        lv_refr_now(display);
        us.push_back(qpcUs() - t0);
    }
    std::sort(us.begin(), us.end());
    return us[us.size() / 2];
}

void setHidden(std::vector<lv_obj_t*>& objs, bool hidden) {
    for (lv_obj_t* o : objs) {
        if (hidden) lv_obj_add_flag(o, LV_OBJ_FLAG_HIDDEN);
        else lv_obj_remove_flag(o, LV_OBJ_FLAG_HIDDEN);
    }
}

bool parse(const char* json, CCFrame& f) {
    JsonDocument doc;
    if (deserializeJson(doc, json)) return false;
    f = CCFrame();
    return cc_parse_frame(doc.as<JsonVariantConst>(), f);
}

void emit(JsonObject o, const Stats& s) {
    std::vector<double> us;
    double sum = 0, pxSum = 0, chunkSum = 0, a8Sum = 0, a8ByteSum = 0, directSum = 0;
    for (const Sample& r : s.refreshes) {
        us.push_back(r.us);
        sum += r.us;
        pxSum += r.px;
        chunkSum += r.chunks;
        a8Sum += r.a8;
        a8ByteSum += r.a8Bytes;
        directSum += r.a8Direct;
    }
    std::sort(us.begin(), us.end());
    const size_t n = us.size();
    o["refreshes"] = n;
    o["us_median"] = n ? us[n / 2] : 0.0;
    o["us_mean"] = n ? sum / n : 0.0;
    o["us_p90"] = n ? us[std::min(n - 1, n * 9 / 10)] : 0.0;
    o["px_mean"] = n ? pxSum / n : 0.0;
    o["chunks_mean"] = n ? chunkSum / n : 0.0;
    // Each A8 draw looks its source up twice (lv_draw_image() task creation, then the draw's decoder open).
    o["a8_draws_per_refresh"] = n ? a8Sum / 2 / n : 0.0;
    // Draws the renderer's own A8 decoder served straight from flash (no copy); the rest went through LVGL's bin
    // decoder, which copies the whole mask.
    o["a8_direct_per_refresh"] = n ? directSum / n : 0.0;
    const double copied = n ? (a8Sum / 2 - directSum) / n : 0.0;
    o["a8_copied_per_refresh"] = copied > 0 ? copied : 0.0;
    o["a8_copy_bytes_per_refresh"] = copied > 0 ? a8ByteSum / 2 / n * copied / (a8Sum / 2 / n) : 0.0;
    o["layered_objects_max"] = s.maxLayered;
    o["transformed_objects_max"] = s.maxTransformed;
    o["drawn_objects_max"] = s.maxObjects;
    o["objects_below_opa255_max"] = s.maxOpaBelow;
    o["render_us_mean"] = s.renders ? s.renderUs / s.renders : 0.0;
}

// Frames (the lcd_bench.py pair, and the same pair with covers).
const char* const MUSIC = R"({"id":17,"mode":"VOLUME","target":"Hall + 1 room","value":"31%","detail":"x","status":"","title":"Straße ? Mix for Night","subtitle":"DJ Ørsted","activity":"idle","buttons":[{"label":"Home","enabled":true,"icon":"house"},{"label":"Recent","enabled":true,"icon":"album"},{"label":"Tracks","enabled":true,"icon":"tracks"},{"label":"Pause","enabled":true,"icon":"pause"}],"ring":{"style":"level","value":31,"index":0,"count":101,"first":0},"layout":"nowPlaying","heading":"MUSIC","restLayout":"nowPlaying","volumeCaption":"Straße ? Mix for Night","confirmedVolume":31,"playing":true,"crumb":"music","ledStyle":"color"%ART%})";
const char* const RECENT_LOADING = R"({"id":18,"mode":"RECENTLY ADDED","target":"Hall + 1 room","value":"","detail":"","status":"","title":"","subtitle":"","activity":"loading","buttons":[{"label":"Back","enabled":true,"icon":"back"},{"label":"Full screen","enabled":true,"icon":"expand"},{"label":"Playlists","enabled":true,"icon":"playlists"},{"label":"Play","enabled":false,"icon":"play"}],"ring":{"style":"off","value":0,"index":0,"count":0},"layout":"recent","heading":"RECENTLY ADDED","meta":"Loading…","crumb":"recent","holdMarker":true,"ledStyle":"color"})";
const char* const RECENT_ITEM = R"({"id":18,"mode":"RECENTLY ADDED","target":"Hall + 1 room","value":"","detail":"","status":"","title":"%TITLE%","subtitle":"%SUB%","activity":"idle","buttons":[{"label":"Back","enabled":true,"icon":"back"},{"label":"Full screen","enabled":true,"icon":"expand"},{"label":"Playlists","enabled":true,"icon":"playlists"},{"label":"Play","enabled":true,"icon":"play"}],"ring":{"style":"selection","value":0,"index":%INDEX%,"count":24,"first":0},"layout":"recent","heading":"RECENTLY ADDED","meta":"%META%","crumb":"recent","holdMarker":true,"ledStyle":"color"%ART%})";

std::string sub(std::string s, const std::string& key, const std::string& value) {
    for (size_t at; (at = s.find(key)) != std::string::npos;) s.replace(at, key.size(), value);
    return s;
}

std::string recentItem(int index, bool art) {
    static const char* const titles[4] = {"Night Channel", "Midnight Arcade", "Glass Weather", "Tidal Glass"};
    static const char* const subs[4] = {"Velvet Circuit", "Air", "Lumen Park", "Oskar Lind Trio"};
    std::string s = RECENT_ITEM;
    s = sub(s, "%TITLE%", titles[index % 4]);
    s = sub(s, "%SUB%", subs[index % 4]);
    s = sub(s, "%INDEX%", std::to_string(index));
    s = sub(s, "%META%", std::to_string(index + 1) + " / 24");
    s = sub(s, "%ART%", art ? std::string(",\"artKey\":\"k-") + (index % 2 ? "bright" : "hall") + "\"" : "");
    return s;
}
}  // namespace


int main(int argc, char** argv) {
    int rows = 24;
    int cycles = 24;
    std::string fixtures = NANOD_FIXTURE_DIR;
    for (int i = 1; i < argc; ++i) {
        if (!std::strcmp(argv[i], "--rows") && i + 1 < argc) rows = std::atoi(argv[++i]);
        else if (!std::strcmp(argv[i], "--cycles") && i + 1 < argc) cycles = std::atoi(argv[++i]);
        else if (!std::strcmp(argv[i], "--period") && i + 1 < argc) periodMs = static_cast<uint32_t>(std::atoi(argv[++i]));
    }
    if (periodMs < 1 || periodMs > 100) {
        std::fprintf(stderr, "--period must be 1..100 ms\n");
        return 2;
    }
    for (int k = 0; k < 2; ++k) {
        std::ifstream in(fixtures + (k ? "/art-bright-120.rgb565" : "/art-hall-120.rgb565"), std::ios::binary);
        art120[k].assign(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
        if (art120[k].size() != CC_ART120_BYTES) { std::fprintf(stderr, "art fixture missing\n"); return 2; }
    }
    lv_init();
    lv_tick_set_cb(tickCb);
    display = lv_display_create(W, H);
    lv_display_set_color_format(display, LV_COLOR_FORMAT_RGB565);
    lv_display_set_buffers(display, drawBuf, nullptr, static_cast<uint32_t>(W * rows * 2), LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_flush_cb(display, flush);
    lv_timer_set_period(lv_display_get_refr_timer(display), periodMs);
    lv_timer_set_period(lv_anim_get_timer(), periodMs);
    // lv_image_decoder_create() inserts at the head of the list: the counter sees every lookup first.

    CCDisplayMedia media = {};
    cc_display_set_media(media);
    lv_screen_load(cc_display_create(art240[0], art240[1]));
    // After cc_display_create(): the counter is inserted at the head of the decoder list, ahead of the renderer's
    // own A8 decoder, so it sees every lookup.
    lv_image_decoder_t* counter = lv_image_decoder_create();
    lv_image_decoder_set_info_cb(counter, countInfo);
    lv_image_decoder_set_open_cb(counter, countOpen);   // get_info() skips a decoder without one
    installTaskTimer();

    JsonDocument out;
    out["draw_rows"] = rows;
    out["period_ms"] = periodMs;
    out["cycles"] = cycles;
    JsonObject scen = out["scenarios"].to<JsonObject>();

    CCFrame music, musicArt, loading;
    if (!parse(sub(MUSIC, "%ART%", "").c_str(), music) || !parse(sub(MUSIC, "%ART%", ",\"artKey\":\"k-hall\"").c_str(), musicArt) ||
        !parse(RECENT_LOADING, loading)) {
        std::fprintf(stderr, "frame parse failed\n");
        return 2;
    }
    out["crumb_parsed"] = music.crumb;
    std::vector<CCFrame> items(4), itemsArt(4);
    for (int k = 0; k < 4; ++k)
        if (!parse(recentItem(k, false).c_str(), items[k]) || !parse(recentItem(k, true).c_str(), itemsArt[k])) {
            std::fprintf(stderr, "item parse failed\n");
            return 2;
        }
    const uint8_t* hall = art120[0].data();
    const uint8_t* bright = art120[1].data();

    // M1 push, the lcd_bench.py pair (no covers): Music <-> Recently Added loading, 500 ms apart.
    {
        Stats s;
        render(s, music, nullptr);
        settle(nullptr, 1000);
        s = Stats();
        for (int c = 0; c < cycles; ++c) {
            render(s, c % 2 ? music : loading, nullptr);
            settle(&s, 496);
        }
        emit(scen["m1_bench_noart"].to<JsonObject>(), s);
    }
    // M1 push with artwork on both screens: Music (hall) <-> Recently Added item (bright).
    {
        Stats s;
        render(s, musicArt, hall);
        settle(nullptr, 1000);
        s = Stats();
        for (int c = 0; c < cycles; ++c) {
            if (c % 2) render(s, musicArt, hall);
            else render(s, itemsArt[1], bright);
            settle(&s, 496);
        }
        emit(scen["m1_art"].to<JsonObject>(), s);
    }
    // M4 list glide with artwork: one detent every 130 ms (a steady turn) through Recently Added items.
    {
        Stats s;
        render(s, itemsArt[0], hall);
        settle(nullptr, 1000);
        s = Stats();
        for (int c = 0; c < cycles * 2; ++c) {
            const int k = c % 4;
            render(s, itemsArt[k], k % 2 ? bright : hall);
            settle(&s, 128);
        }
        emit(scen["m4_art"].to<JsonObject>(), s);
    }
    // M13 wall stretch with artwork: a push at the start of the list every 700 ms.
    {
        Stats s;
        render(s, itemsArt[0], hall);
        settle(nullptr, 1000);
        s = Stats();
        for (int c = 0; c < cycles; ++c) {
            cc_display_wall(c % 2 ? 1 : -1);
            settle(&s, 704);
        }
        emit(scen["m13_art"].to<JsonObject>(), s);
    }
    // Static breakdown: full redraws of the content box (240 x 136) on the settled Music screen with its cover,
    // with parts switched off one at a time (host us, median of 200). Shows where a moving frame's time goes.
    {
        Stats s;
        render(s, musicArt, hall);
        settle(nullptr, 1500);
        JsonObject b = out["content_redraw_breakdown_us"].to<JsonObject>();
        std::vector<lv_obj_t*> twins, art, labels, content;
        byRole(lv_screen_active(), ".twin", false, twins);
        byRole(lv_screen_active(), "art", true, art);
        byRole(lv_screen_active(), "content", true, content);
        resetTaskTimer();
        b["full"] = contentRedrawUs(200);
        emitTasks(out["content_redraw_tasks"].to<JsonObject>(), 200);
        setHidden(twins, true);
        b["no_twins"] = contentRedrawUs(200);
        setHidden(twins, false);
        setHidden(art, true);
        b["no_art"] = contentRedrawUs(200);
        setHidden(twins, true);
        b["no_art_no_twins"] = contentRedrawUs(200);
        setHidden(twins, false);
        setHidden(art, false);
        lv_obj_set_style_opa(content.front(), 128, 0);
        b["content_opa_128"] = contentRedrawUs(200);
        lv_obj_set_style_opa(content.front(), 255, 0);
        lv_obj_set_style_opa(art.front(), 128, 0);
        b["art_opa_128"] = contentRedrawUs(200);
        lv_obj_set_style_opa(art.front(), 255, 0);
        b["full_again"] = contentRedrawUs(200);
    }
    lv_mem_monitor_t mon;
    lv_mem_monitor(&mon);
    out["lvgl_heap_max_used"] = mon.max_used;
    out["lvgl_heap_total"] = mon.total_size;
    static char text[1 << 16];
    serializeJsonPretty(out, text, sizeof(text));
    std::printf("%s\n", text);
    return 0;
}
