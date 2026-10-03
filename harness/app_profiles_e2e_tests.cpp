// App profiles end to end (plan §6, S3): Desk Dial's real profiles, compiled by its Python compiler
// (control_center/app_profiles.py), through the knob's REAL decoder, store and serial upload handler, drawn by the
// knob's REAL app canvas renderer. Built by app_profiles_e2e_tests.py with MSVC /W4 /WX together with the unchanged
// firmware units cc_app_store.c, cc_app_onshape.c, cc_app_icons.c (C), cc_app_store_msg.cpp, cc_frame_parse.cpp and
// the renderer (cc_app_canvas.cpp, cc_app_gfx.cpp, cc_app_fonts.cpp, cc_app_shape.cpp, cc_app_cards.cpp,
// cc_app_screens.cpp). Unlike app_canvas_tests.cpp there is NO store shim: cc_app_store_acquire / _release are the
// store's own. cc_app_canvas.cpp alone is compiled with /Dcc_app_store_acquire=e2e_store_acquire (and _release), so
// its calls land in the counting pass-throughs below, which call the real store.
//
// Input (argv[1]): a JSON file written by app_profiles_e2e_tests.py:
//   {"decode": ["<b64 blob>", ...],          each through cc_app_decode() on its own (an exact-size heap copy)
//    "upload": ["{\"appProfile\":{...}}", ...],  wire lines into cc_app_profile_command(), as the COM task does
//    "render": [{"name", "steps": [{"t", "line"?, "angle"?, "buttons"?, "skip"?, "snap"?}...]}...]}
// Output (stdout), one JSON object per line:
//   decode: {"kind":"decode","code","offset","bytes","bounds","profile"}   (profile: the whole decoded struct, icons
//           as hex so the script can hash them)
//   upload: {"kind":"upload","line","reply"}   (reply: the object under "appProfile", or null when none)
//   render: {"kind":"render","name","view","frames","lastFills","lastCalls","guard","snaps","leases","nulls","leaked"}
//           and argv[2]/<name>.ppm / .rgb565 (+ <name>@<t> for snaps), as app_canvas_tests.cpp writes them.
//   list:   {"kind":"list","reply"}            (the store's list after every render)
#include <ArduinoJson.h>
#include "cc_app_canvas.h"
#include "cc_app_profile.h"
#include "cc_app_store.h"
#include "cc_app_store_msg.h"
#include "cc_frame_parse.h"
#include "cc_presentation.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

namespace {
// ------------------------------------------------------------------------------------------------ allocator
std::map<void*, size_t> g_blocks;

void* e2e_alloc(void*, size_t bytes) {
    void* p = std::malloc(bytes ? bytes : 1);
    if (p) g_blocks[p] = bytes;
    return p;
}

void e2e_free(void*, void* p) {
    auto it = g_blocks.find(p);
    if (it == g_blocks.end()) {
        std::printf("{\"fatal\":\"free of an unknown block\"}\n");
        std::exit(3);
    }
    g_blocks.erase(it);
    std::free(p);
}

int g_lockDepth = 0, g_lockErrors = 0;
void e2e_lock(void*) {
    if (++g_lockDepth != 1) ++g_lockErrors;
}
void e2e_unlock(void*) { --g_lockDepth; }

// Leases seen by the renderer (cc_app_canvas.cpp's calls, renamed at its compile).
uint32_t g_acquired = 0, g_released = 0, g_nulls = 0;
} // namespace

extern "C" const cc_app_profile_t* e2e_store_acquire(const char* id, uint32_t crc) {
    const cc_app_profile_t* p = cc_app_store_acquire(id, crc);
    if (p != nullptr) ++g_acquired;
    else ++g_nulls;
    return p;
}

extern "C" void e2e_store_release(const cc_app_profile_t* p) {
    if (p != nullptr) ++g_released;
    cc_app_store_release(p);
}

namespace {
// ------------------------------------------------------------------------------------------------ JSON out
std::string esc(const char* s) {
    if (!s) return "null";
    std::string out = "\"";
    for (; *s; ++s) {
        const unsigned char c = static_cast<unsigned char>(*s);
        if (c == '"' || c == '\\') { out += '\\'; out += static_cast<char>(c); }
        else if (c < 0x20 || c > 0x7E) { char b[8]; std::snprintf(b, sizeof b, "\\u%04x", c); out += b; }
        else out += static_cast<char>(c);
    }
    return out + "\"";
}

std::string num(float f) {
    char b[48];
    std::snprintf(b, sizeof b, "%.9g", static_cast<double>(f));
    return b;
}

std::string u(unsigned long long v) { return std::to_string(v); }

// Pointer bounds: every pointer of a decoded profile inside [base, base + size).
struct Bounds {
    const uint8_t* base;
    size_t size;
    bool ok = true;
    template <typename T> void check(const T* p, size_t count) {
        if (p == nullptr) return;
        const uint8_t* b = reinterpret_cast<const uint8_t*>(p);
        if (b < base || b + count * sizeof(T) > base + size) ok = false;
    }
    void str(const char* s) {
        if (s == nullptr) return;
        const uint8_t* b = reinterpret_cast<const uint8_t*>(s);
        if (b < base || b >= base + size) { ok = false; return; }
        if (!std::memchr(b, 0, static_cast<size_t>(base + size - b))) ok = false;
    }
};

std::string els_json(const app_el_t* el, uint8_t n) {
    std::string out = "[";
    for (uint8_t i = 0; i < n; ++i) {
        const app_el_t& e = el[i];
        if (i) out += ",";
        out += "[" + u(e.op) + "," + u(e.color) + "," + std::to_string(e.x) + "," + std::to_string(e.y) + "," +
               u(e.w) + "," + u(e.h) + "," + u(e.arg) + "," + u(e.d) + "," + u(e.flags) + "]";
    }
    return out + "]";
}

std::string scene_json(const app_scene_t* s, Bounds& b) {
    b.check(s, 1);
    b.check(s->base, s->n_base);
    b.check(s->frames, s->n_frames);
    std::string out = "{\"base\":" + els_json(s->base, s->n_base) + ",\"frames\":[";
    for (uint8_t f = 0; f < s->n_frames; ++f) {
        const app_keyframe_t& k = s->frames[f];
        b.check(k.el, k.n);
        if (f) out += ",";
        out += "{\"ms\":" + u(k.ms) + ",\"el\":" + els_json(k.el, k.n) + "}";
    }
    return out + "]}";
}

std::string param_json(const app_param_t* q, Bounds& b) {
    b.check(q, 1);
    b.str(q->label);
    b.str(q->label_neg);
    return "{\"label\":" + esc(q->label) + ",\"label_neg\":" + esc(q->label_neg) + ",\"steps\":[" + num(q->steps[0]) +
           "," + num(q->steps[1]) + "," + num(q->steps[2]) + "],\"free_step\":" + num(q->free_step) + ",\"start\":" +
           num(q->start) + ",\"min\":" + num(q->min) + ",\"max\":" + num(q->max) + ",\"decimals\":" + u(q->decimals) +
           ",\"flags\":" + u(q->flags) + ",\"visual\":" + u(q->visual) + ",\"modes\":" + u(q->modes) +
           ",\"axis_default\":" + u(q->axis_default) + ",\"field\":" + (q->field ? "true" : "false") + "}";
}

std::string icon_json(const uint8_t* icon, size_t bytes, Bounds& b) {
    if (!icon) return "null";
    b.check(icon, bytes);
    static const char hex[] = "0123456789abcdef";
    std::string out = "\"";
    for (size_t i = 0; i < bytes; ++i) {
        out += hex[icon[i] >> 4];
        out += hex[icon[i] & 15];
    }
    return out + "\"";
}

std::string profile_json(const cc_app_profile_t* p, size_t size, bool& bounds) {
    Bounds b{reinterpret_cast<const uint8_t*>(p), size};
    b.check(p, 1);
    std::string out = "{\"id\":" + esc(p->id) + ",\"name\":" + esc(p->name) + ",\"legend\":[";
    b.str(p->id);
    b.str(p->name);
    for (int i = 0; i < 4; ++i) {
        b.str(p->legend[i]);
        out += (i ? "," : "") + esc(p->legend[i]);
    }
    out += "],\"visual\":" + u(p->visual) + ",\"shape\":" + u(p->shape) + ",\"style\":" + u(p->shape_style) +
           ",\"stepped\":" + (p->stepped ? "true" : "false") + ",\"plasma\":[" + u(p->plasma_heat[0]) + "," +
           u(p->plasma_heat[1]) + "," + u(p->plasma_heat[2]) + "],\"icon24\":" + icon_json(p->icon24, 1152, b) +
           ",\"icon48\":" + icon_json(p->icon48, 4608, b) + ",\"has_slots\":" + (p->has_slots ? "true" : "false") +
           ",\"slots\":[";
    for (int i = 0; i < APP_SLOTS; ++i) {
        const cc_app_slot_t& s = p->slots[i];
        b.str(s.label);
        out += std::string(i ? "," : "") + "{\"kind\":" + u(s.kind) + ",\"fx\":" + u(s.fx) + ",\"button\":" +
               u(s.button) + ",\"label\":" + esc(s.label) + "}";
    }
    b.str(p->search_key);
    out += "],\"search\":{\"mod\":" + u(p->search_modifier) + ",\"key\":" + esc(p->search_key) + "},\"rings\":[";
    b.check(p->rings, p->ring_count);
    for (uint8_t r = 0; r < p->ring_count; ++r) {
        const app_ring_t& g = p->rings[r];
        b.str(g.name);
        b.str(g.tab);
        b.check(g.cmds, g.count);
        out += std::string(r ? "," : "") + "{\"name\":" + esc(g.name) + ",\"tab\":" + esc(g.tab) + ",\"slot\":" +
               u(g.slot) + ",\"cmds\":[";
        for (uint8_t c = 0; c < g.count; ++c) {
            const app_cmd_t& m = g.cmds[c];
            b.str(m.name);
            b.str(m.key);
            out += std::string(c ? "," : "") + "{\"name\":" + esc(m.name) + ",\"search\":" +
                   (m.search ? "true" : "false") + ",\"flags\":" + u(m.flags) + ",\"mod\":" + u(m.modifier) +
                   ",\"key\":" + esc(m.key) + ",\"scene\":" +
                   (m.scene ? scene_json(m.scene, b) : std::string("null")) +
                   ",\"param\":" + (m.param ? param_json(m.param, b) : std::string("null")) + "}";
        }
        out += "]}";
    }
    out += "],\"crc\":" + u(p->crc) + ",\"features\":" + u(p->features) + "}";
    bounds = b.ok;
    return out;
}

// ------------------------------------------------------------------------------------------------ decode
std::vector<uint8_t> b64_decode(const char* s) {
    auto val = [](char c) -> int {
        if (c >= 'A' && c <= 'Z') return c - 'A';
        if (c >= 'a' && c <= 'z') return c - 'a' + 26;
        if (c >= '0' && c <= '9') return c - '0' + 52;
        if (c == '+') return 62;
        if (c == '/') return 63;
        return -1;
    };
    std::vector<uint8_t> out;
    uint32_t acc = 0;
    int bits = 0;
    for (; *s; ++s) {
        const int v = val(*s);
        if (v < 0) continue;   // '=' padding
        acc = (acc << 6) | static_cast<uint32_t>(v);
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            out.push_back(static_cast<uint8_t>((acc >> bits) & 0xFF));
        }
    }
    return out;
}

void decode_one(const std::vector<uint8_t>& bytes) {
    // An exact-size heap copy: the decoder must not need a byte past the blob.
    uint8_t* copy = static_cast<uint8_t*>(std::malloc(bytes.size() ? bytes.size() : 1));
    if (!bytes.empty()) std::memcpy(copy, bytes.data(), bytes.size());
    const cc_app_alloc_t alloc = {e2e_alloc, e2e_free, nullptr};
    cc_app_profile_t* p = nullptr;
    size_t offset = 0;
    const int code = cc_app_decode(copy, bytes.size(), &alloc, &p, &offset);
    std::free(copy);
    std::string line = "{\"kind\":\"decode\",\"code\":" + u(static_cast<unsigned>(code)) + ",\"offset\":" + u(offset);
    if (p) {
        const size_t size = g_blocks.count(p) ? g_blocks[p] : 0;
        bool bounds = false;
        const std::string json = profile_json(p, size, bounds);
        line += ",\"bytes\":" + u(size) + ",\"bounds\":" + (bounds ? "true" : "false") + ",\"profile\":" + json;
        e2e_free(nullptr, p);
    }
    std::printf("%s}\n", line.c_str());
}

// ------------------------------------------------------------------------------------------------ upload / list
std::string command(const std::string& line, uint32_t now) {
    JsonDocument doc;
    if (deserializeJson(doc, line)) return "\"bad line\"";
    JsonDocument reply;
    JsonObject obj = reply.to<JsonObject>();
    if (!cc_app_profile_command(doc["appProfile"], now, obj)) return "null";
    std::string out;
    serializeJson(reply, out);
    return out;
}

// ------------------------------------------------------------------------------------------------ render
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

// One render case, driven exactly as app_canvas_tests.cpp drives it (the LCD thread's loop: a pass per ms).
bool render(JsonObjectConst c, const std::string& out_dir) {
    static CCFrame frame;
    const std::string name = c["name"].as<std::string>();
    std::fill(g_mem.begin(), g_mem.end(), kGuardWord);
    std::fill(g_frame, g_frame + 240 * 240, static_cast<uint16_t>(0));
    CCAppCanvas canvas;
    canvas.begin(g_frame, &g_tables, c["minFrameMs"] | 16u);
    std::string snaps;
    bool entered = false, leaked = false;
    g_acquired = g_released = g_nulls = 0;
    uint32_t frames = 0, lastFills = 0, lastCalls = 0, t = 0;
    int32_t angle = 0;
    uint8_t buttons = 0;
    for (JsonObjectConst s : c["steps"].as<JsonArrayConst>()) {
        const uint32_t to = s["t"] | t;
        const int32_t toAngle = s["angle"] | angle;
        const uint8_t toButtons = static_cast<uint8_t>(s["buttons"] | static_cast<unsigned>(buttons));
        const bool skip = s["skip"] | false;
        for (uint32_t now = t + 1; entered && !skip && now < to; ++now) {
            CCAppInputs inputs;
            inputs.nowMs = now;
            const int32_t span = static_cast<int32_t>(static_cast<uint32_t>(toAngle) - static_cast<uint32_t>(angle));
            const int32_t part = static_cast<int32_t>(static_cast<int64_t>(span) * (now - t) / (to - t));
            inputs.angle = static_cast<int32_t>(static_cast<uint32_t>(angle) + static_cast<uint32_t>(part));
            inputs.buttons = buttons;
            ccui::take_fill_count();
            ccui::take_fill_calls();
            const bool drew = canvas.step(inputs);
            leaked = leaked || g_acquired != g_released;
            if (drew) {
                ++frames;
                lastFills = ccui::take_fill_count();
                lastCalls = ccui::take_fill_calls();
            }
        }
        t = to; angle = toAngle; buttons = toButtons;
        CCAppInputs inputs;
        inputs.nowMs = t;
        inputs.angle = angle;
        inputs.buttons = buttons;
        if (s.containsKey("line")) {
            if (!parse_line(s["line"].as<std::string>(), frame) || !cc_app_state_present(frame.app)) {
                std::fprintf(stderr, "%s: step at %u ms: the frame line was rejected or has no app\n", name.c_str(), t);
                return false;
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
        }
        if (s["snap"] | false) {
            const std::string snap = name + "@" + std::to_string(t);
            if (!dump(out_dir + "/" + snap)) return false;
            snaps += (snaps.empty() ? "\"" : ",\"") + snap + "\"";
        }
    }
    if (!dump(out_dir + "/" + name)) return false;
    std::printf("{\"kind\":\"render\",\"name\":\"%s\",\"view\":\"%s\",\"frames\":%u,\"lastFills\":%u,\"lastCalls\":%u,"
                "\"guard\":%s,\"snaps\":[%s],\"leases\":%u,\"nulls\":%u,\"leaked\":%s}\n",
                name.c_str(), view_name(canvas.view()), frames, lastFills, lastCalls, guard_intact() ? "true" : "false",
                snaps.c_str(), g_acquired, g_nulls, leaked ? "true" : "false");
    return true;
}
} // namespace

int main(int argc, char** argv) {
    if (argc < 3) {
        std::fprintf(stderr, "usage: app_profiles_e2e_tests <cases.json> <out-dir>\n");
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

    for (JsonVariantConst blob : cases["decode"].as<JsonArrayConst>()) decode_one(b64_decode(blob.as<const char*>()));
    std::printf("{\"kind\":\"decoded\",\"live\":%zu}\n", g_blocks.size());

    cc_app_store_hooks_t hooks = {};
    hooks.mem.alloc = e2e_alloc;
    hooks.mem.free = e2e_free;
    hooks.lock = e2e_lock;
    hooks.unlock = e2e_unlock;
    cc_app_store_init(&hooks);
    uint32_t now = 1;
    for (JsonVariantConst line : cases["upload"].as<JsonArrayConst>()) {
        const std::string l = line.as<std::string>();
        std::printf("{\"kind\":\"upload\",\"line\":%u,\"reply\":%s}\n", now, command(l, now).c_str());
        now += 5;
    }

    ccui::plasma_init(g_tables);
    const std::string list = "{\"appProfile\":{\"op\":\"list\"}}";
    for (JsonObjectConst c : cases["render"].as<JsonArrayConst>()) {
        if (!render(c, out_dir)) {
            std::fprintf(stderr, "%s: render failed\n", c["name"].as<const char*>());
            return 1;
        }
        std::printf("{\"kind\":\"list\",\"reply\":%s}\n", command(list, now).c_str());
    }
    std::printf("{\"kind\":\"end\",\"lockErrors\":%d,\"lockDepth\":%d,\"blocks\":%zu}\n", g_lockErrors, g_lockDepth,
                g_blocks.size());
    return 0;
}
