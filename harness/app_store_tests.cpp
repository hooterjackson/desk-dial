// App profiles harness (plan §6, S1 FW-A): the DDAP decoder, the RAM-only store, the upload state machine, the
// appProfile request and the frame's `app` fields. Built by app_store_tests.py with MSVC /W4 /WX together with the
// unchanged firmware units cc_app_store.c, cc_app_onshape.c, cc_app_icons.c (C), cc_app_store_msg.cpp and
// cc_frame_parse.cpp; built a second time with /fsanitize=address for the fuzz and the thread stress.
//
// Modes (argv[1]):
//   decode <blobs.bin>         blobs.bin = records {u32 len, u8 fail_alloc, len bytes}. One JSON line per blob:
//                              {"code","offset","bytes","bounds","profile"} -- profile is the whole decoded struct
//                              (app_store_tests.py compares it field by field with its encoder's model).
//   script <script.jsonl>      one JSON op per line (init, msg, acquire, release, list, stats, poll, frame, heap);
//                              one JSON result line per op.
//   fuzz <corpus.bin> <count> <seed>   deterministic mutation fuzz over the corpus; one JSON summary line.
//   threads <corpus.bin> <rounds>      the LCD task's acquire / release against the COM task's uploads (std::mutex
//                              hooks); one JSON summary line.
// Every decoded profile is checked: each pointer it holds lies inside its one allocation ("bounds").
#include <ArduinoJson.h>
#include "cc_app_store.h"
#include "cc_app_store_msg.h"
#include "cc_frame_parse.h"
#include "cc_presentation.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace {
// ------------------------------------------------------------------------------------------------ allocator
struct TestAlloc {
    std::map<void*, size_t> blocks;
    size_t liveBytes = 0, peakBytes = 0, calls = 0;
    int failNext = 0;         // fail this many of the next allocations
    size_t limit = SIZE_MAX;  // fail when liveBytes would exceed it (PSRAM exhausted)
    std::mutex m;
};
TestAlloc g_alloc;

void* test_alloc(void* ctx, size_t bytes) {
    TestAlloc& a = *static_cast<TestAlloc*>(ctx);
    std::lock_guard<std::mutex> guard(a.m);
    ++a.calls;
    if (a.failNext > 0) { --a.failNext; return nullptr; }
    if (bytes > a.limit || a.liveBytes > a.limit - bytes) return nullptr;
    void* p = std::malloc(bytes ? bytes : 1);
    if (!p) return nullptr;
    a.blocks[p] = bytes;
    a.liveBytes += bytes;
    if (a.liveBytes > a.peakBytes) a.peakBytes = a.liveBytes;
    return p;
}

void test_free(void* ctx, void* p) {
    TestAlloc& a = *static_cast<TestAlloc*>(ctx);
    std::lock_guard<std::mutex> guard(a.m);
    auto it = a.blocks.find(p);
    if (it == a.blocks.end()) {
        std::printf("{\"fatal\":\"free of an unknown block\"}\n");
        std::exit(3);
    }
    a.liveBytes -= it->second;
    a.blocks.erase(it);
    std::free(p);
}

size_t block_size(const void* p) {
    std::lock_guard<std::mutex> guard(g_alloc.m);
    auto it = g_alloc.blocks.find(const_cast<void*>(p));
    return it == g_alloc.blocks.end() ? 0 : it->second;
}

// Lock hooks: a std::mutex, plus a depth check (the store never takes its lock twice).
std::mutex g_mutex;
std::atomic<int> g_depth{0};
std::atomic<int> g_depthErrors{0};
void hook_lock(void*) {
    g_mutex.lock();
    if (++g_depth != 1) ++g_depthErrors;
}
void hook_unlock(void*) {
    --g_depth;
    g_mutex.unlock();
}

void store_init(bool locks) {
    cc_app_store_hooks_t hooks = {};
    hooks.mem.alloc = test_alloc;
    hooks.mem.free = test_free;
    hooks.mem.ctx = &g_alloc;
    if (locks) {
        hooks.lock = hook_lock;
        hooks.unlock = hook_unlock;
    }
    cc_app_store_init(&hooks);
}

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
    if ((s->n_base == 0) != (s->base == nullptr)) b.ok = false;
    for (uint8_t f = 0; f < s->n_frames; ++f) {
        const app_keyframe_t& k = s->frames[f];
        b.check(k.el, k.n);
        if ((k.n == 0) != (k.el == nullptr)) b.ok = false;
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
    return u(cc_app_crc32(0, icon, bytes));
}

// The whole decoded profile. Scenes and params are written where commands reference them, with their offset in
// the allocation ("at"), so the test can check that one wire index is one shared struct.
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
    if ((p->ring_count == 0) != (p->rings == nullptr)) b.ok = false;
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
                   (m.scene ? scene_json(m.scene, b) : std::string("null")) + ",\"scene_at\":" +
                   (m.scene ? u(static_cast<size_t>(reinterpret_cast<const uint8_t*>(m.scene) - b.base))
                            : std::string("null")) +
                   ",\"param\":" + (m.param ? param_json(m.param, b) : std::string("null")) + ",\"param_at\":" +
                   (m.param ? u(static_cast<size_t>(reinterpret_cast<const uint8_t*>(m.param) - b.base))
                            : std::string("null")) + "}";
        }
        out += "]}";
    }
    out += "],\"crc\":" + u(p->crc) + ",\"features\":" + u(p->features) + "}";
    bounds = b.ok;
    return out;
}

// Walks every pointer (the fuzz: an accepted mutation must still be a sound profile).
bool profile_sound(const cc_app_profile_t* p, size_t size) {
    bool bounds = false;
    (void)profile_json(p, size, bounds);
    return bounds;
}

// ------------------------------------------------------------------------------------------------ files
std::vector<uint8_t> read_file(const char* path) {
    std::ifstream in(path, std::ios::binary);
    return std::vector<uint8_t>((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}

struct Blob {
    std::vector<uint8_t> bytes;
    bool failAlloc = false;
};

std::vector<Blob> read_blobs(const char* path) {
    const std::vector<uint8_t> file = read_file(path);
    std::vector<Blob> out;
    size_t at = 0;
    while (at + 5 <= file.size()) {
        const size_t len = file[at] | (file[at + 1] << 8) | (file[at + 2] << 16) | (static_cast<size_t>(file[at + 3]) << 24);
        Blob b;
        b.failAlloc = file[at + 4] != 0;
        at += 5;
        if (len > file.size() - at) break;
        b.bytes.assign(file.begin() + static_cast<std::ptrdiff_t>(at), file.begin() + static_cast<std::ptrdiff_t>(at + len));
        at += len;
        out.push_back(std::move(b));
    }
    return out;
}

// Decodes from an exact-size heap copy, so ASan sees any read past the blob.
int decode_exact(const std::vector<uint8_t>& bytes, cc_app_profile_t** out, size_t* offset, bool failAlloc) {
    uint8_t* copy = static_cast<uint8_t*>(std::malloc(bytes.size() ? bytes.size() : 1));
    if (!bytes.empty()) std::memcpy(copy, bytes.data(), bytes.size());
    const cc_app_alloc_t alloc = {test_alloc, test_free, &g_alloc};
    if (failAlloc) g_alloc.failNext = 1;
    const int code = cc_app_decode(copy, bytes.size(), &alloc, out, offset);
    g_alloc.failNext = 0;
    std::free(copy);
    return code;
}

int mode_decode(const char* path) {
    for (const Blob& b : read_blobs(path)) {
        cc_app_profile_t* p = nullptr;
        size_t offset = 0;
        const int code = decode_exact(b.bytes, &p, &offset, b.failAlloc);
        std::string line = "{\"code\":" + u(static_cast<unsigned>(code)) + ",\"offset\":" + u(offset);
        if (p) {
            const size_t size = block_size(p);
            bool bounds = false;
            const std::string json = profile_json(p, size, bounds);
            line += ",\"bytes\":" + u(size) + ",\"bounds\":" + (bounds ? "true" : "false") + ",\"profile\":" + json;
            test_free(&g_alloc, p);
        } else if (code == CC_APP_OK) {
            line += ",\"profile\":null";
        }
        std::printf("%s,\"live\":%zu}\n", line.c_str(), g_alloc.blocks.size());
    }
    return 0;
}

// ------------------------------------------------------------------------------------------------ script
// ArduinoJson allocation model of one line's parse: every block, with where the ESP32-S3 malloc policy puts it
// (CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL 4096: a request below 4096 B is internal RAM, else PSRAM first).
struct CountingAllocator : ArduinoJson::Allocator {
    std::map<void*, size_t> blocks;
    size_t cur = 0, peak = 0, curInternal = 0, peakInternal = 0, largest = 0;
    void add(void* p, size_t n) {
        blocks[p] = n;
        cur += n;
        if (n < 4096) curInternal += n;
        if (cur > peak) peak = cur;
        if (curInternal > peakInternal) peakInternal = curInternal;
        if (n > largest) largest = n;
    }
    void remove(void* p) {
        auto it = blocks.find(p);
        if (it == blocks.end()) return;
        cur -= it->second;
        if (it->second < 4096) curInternal -= it->second;
        blocks.erase(it);
    }
    void* allocate(size_t n) override {
        void* p = std::malloc(n);
        if (p) add(p, n);
        return p;
    }
    void deallocate(void* p) override {
        remove(p);
        std::free(p);
    }
    // A move (heap_caps_realloc into another region): the new block exists before the old one is freed.
    void* reallocate(void* p, size_t n) override {
        void* q = std::malloc(n);
        if (!q) return nullptr;
        add(q, n);
        if (p) {
            std::memcpy(q, p, std::min(n, blocks.count(p) ? blocks[p] : 0));
            deallocate(p);
        }
        return q;
    }
};

std::vector<const cc_app_profile_t*> g_handles;

std::string app_state_json(const CCAppState& a) {
    return "{\"id\":" + esc(a.id) + ",\"crc\":" + u(a.crc) + ",\"slot\":" + u(a.slot) + ",\"refused\":" +
           (a.refused ? "true" : "false") + ",\"flash\":" + u(a.flash) + ",\"wheel\":" + (a.wheel ? "true" : "false") +
           ",\"wheelRing\":" + u(a.wheelRing) + ",\"wheelIndex\":" + u(a.wheelIndex) + ",\"param\":" +
           (a.param ? "true" : "false") + ",\"paramRing\":" + u(a.paramRing) + ",\"paramIndex\":" + u(a.paramIndex) +
           ",\"paramTyped\":" + (a.paramTyped ? "true" : "false") + ",\"paramStep\":" + u(a.paramStep) +
           ",\"paramValue\":" + std::to_string(a.paramValue) + ",\"paramBump\":" + u(a.paramBump) + ",\"echoSeq\":" +
           u(a.echoSeq) + ",\"echoRing\":" + u(a.echoRing) + ",\"echoIndex\":" + u(a.echoIndex) + ",\"paramAxis\":" +
           std::to_string(a.paramAxis) + ",\"paramPlane\":" + (a.paramPlane ? "true" : "false") + ",\"present\":" +
           (cc_app_present(a) ? "true" : "false") + "}";
}

CCFrame g_frame;

std::string run_op(JsonObjectConst op) {
    const std::string name = op["op"] | "";
    if (name == "init") {
        g_alloc.failNext = 0;
        g_alloc.limit = SIZE_MAX;
        store_init(true);
        return "{\"ok\":true}";
    }
    if (name == "alloc") {   // {"failNext": n, "limit": bytes | -1}
        g_alloc.failNext = op["failNext"] | 0;
        const long long limit = op["limit"] | -1LL;
        g_alloc.limit = limit < 0 ? SIZE_MAX : static_cast<size_t>(limit);
        return "{\"ok\":true}";
    }
    if (name == "msg") {     // a whole serial line, parsed as the COM task does
        const std::string line = op["line"] | "";
        JsonDocument doc;
        if (deserializeJson(doc, line.data(), line.size())) return "{\"parse\":false}";
        if (!doc.containsKey("appProfile")) return "{\"routed\":false}";
        JsonDocument reply;
        const bool sent = cc_app_profile_command(doc["appProfile"], op["now"] | 0u, reply["appProfile"].to<JsonObject>());
        std::string text;
        serializeJson(reply, text);
        return "{\"sent\":" + std::string(sent ? "true" : "false") + ",\"reply\":" + (sent ? text : "null") +
               ",\"active\":" + (cc_app_upload_active() ? "true" : "false") + "}";
    }
    if (name == "heap") {    // the ArduinoJson heap of one line's parse and its reply
        const std::string line = op["line"] | "";
        CountingAllocator parse, answer;
        size_t total = 0, internal = 0;
        {
            JsonDocument doc(&parse);
            if (deserializeJson(doc, line.data(), line.size())) return "{\"parse\":false}";
            JsonDocument reply(&answer);
            cc_app_profile_command(doc["appProfile"], op["now"] | 0u, reply["appProfile"].to<JsonObject>());
            std::string text;
            serializeJson(reply, text);
            total = parse.cur + answer.cur;
            internal = parse.curInternal + answer.curInternal;
        }
        return "{\"lineBytes\":" + u(line.size()) + ",\"parsePeak\":" + u(parse.peak) + ",\"parsePeakInternal\":" +
               u(parse.peakInternal) + ",\"parseLargest\":" + u(parse.largest) + ",\"heldAfterParse\":" + u(total) +
               ",\"heldInternal\":" + u(internal) + ",\"replyPeak\":" + u(answer.peak) + "}";
    }
    if (name == "acquire") {
        const std::string id = op["id"] | "";
        const cc_app_profile_t* p = cc_app_store_acquire(op["null"] | false ? nullptr : id.c_str(), op["crc"] | 0u);
        g_handles.push_back(p);
        return "{\"h\":" + u(g_handles.size() - 1) + ",\"null\":" + (p ? "false" : "true") + ",\"builtin\":" +
               (p == &cc_app_profile_onshape ? "true" : "false") + ",\"name\":" + esc(p ? p->name : nullptr) +
               ",\"crc\":" + u(p ? p->crc : 0) + ",\"allocated\":" + (p && block_size(p) ? "true" : "false") + "}";
    }
    if (name == "release") {
        const size_t h = op["h"] | 0u;
        const bool readable = h < g_handles.size() && g_handles[h] != nullptr &&
                              (g_handles[h] == &cc_app_profile_onshape || block_size(g_handles[h]) != 0);
        std::string name_before = readable ? g_handles[h]->name : "";
        if (h < g_handles.size()) cc_app_store_release(g_handles[h]);
        return "{\"readable\":" + std::string(readable ? "true" : "false") + ",\"name\":" + esc(name_before.c_str()) + "}";
    }
    if (name == "list") {
        cc_app_store_item_t items[8];
        const size_t n = cc_app_store_list(items, op["max"] | 8u);
        std::string out = "{\"loaded\":[";
        for (size_t i = 0; i < n; ++i)
            out += std::string(i ? "," : "") + "{\"id\":" + esc(items[i].id) + ",\"crc\":" + u(items[i].crc) + "}";
        return out + "]}";
    }
    if (name == "stats") {
        return "{\"blocks\":" + u(g_alloc.blocks.size()) + ",\"liveBytes\":" + u(g_alloc.liveBytes) + ",\"active\":" +
               (cc_app_upload_active() ? "true" : "false") + ",\"depthErrors\":" + u(static_cast<size_t>(g_depthErrors)) +
               "}";
    }
    if (name == "poll") {
        cc_app_upload_poll(op["now"] | 0u);
        return "{\"active\":" + std::string(cc_app_upload_active() ? "true" : "false") + "}";
    }
    if (name == "data_null") {   // the C API's own guard: a NULL b64
        const cc_app_up_result_t r = cc_app_upload_data(op["off"] | 0u, nullptr, 0, op["now"] | 0u, nullptr);
        return "{\"result\":" + esc(cc_app_up_error_name(r)) + "}";
    }
    if (name == "frame") {   // {"frame": {...}} through the real cc_parse_frame
        const std::string line = op["line"] | "";
        JsonDocument doc;
        if (deserializeJson(doc, line.data(), line.size())) return "{\"parse\":false}";
        const bool accept = cc_parse_frame(doc["frame"], g_frame);
        return "{\"accept\":" + std::string(accept ? "true" : "false") + ",\"app\":" +
               (accept ? app_state_json(g_frame.app) : std::string("null")) + "}";
    }
    if (name == "sizes") {
        return "{\"CCFrame\":" + u(sizeof(CCFrame)) + ",\"CCAppState\":" + u(sizeof(CCAppState)) + "}";
    }
    return "{\"error\":\"unknown op\"}";
}

int mode_script(const char* path) {
    std::ifstream in(path, std::ios::binary);
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty()) continue;
        JsonDocument op;
        if (deserializeJson(op, line)) {
            std::printf("{\"error\":\"bad op\"}\n");
            continue;
        }
        std::printf("%s\n", run_op(op.as<JsonObjectConst>()).c_str());
    }
    return 0;
}

// ------------------------------------------------------------------------------------------------ fuzz
uint64_t g_rng;
uint32_t rnd() {   // xorshift64*
    g_rng ^= g_rng >> 12;
    g_rng ^= g_rng << 25;
    g_rng ^= g_rng >> 27;
    return static_cast<uint32_t>((g_rng * 2685821657736338717ULL) >> 32);
}
uint32_t below(uint32_t n) { return n ? rnd() % n : 0; }

void put32(std::vector<uint8_t>& b, size_t at, uint32_t v) {
    if (at + 4 > b.size()) return;
    for (int i = 0; i < 4; ++i) b[at + static_cast<size_t>(i)] = static_cast<uint8_t>(v >> (8 * i));
}

// Header total and trailer CRC made consistent again, so the mutation reaches the body walk.
void reseal(std::vector<uint8_t>& b) {
    if (b.size() < 20) return;
    put32(b, 8, static_cast<uint32_t>(b.size()));
    put32(b, b.size() - 4, cc_app_crc32(0, b.data(), b.size() - 4));
}

int mode_fuzz(const char* path, long count, uint64_t seed) {
    const std::vector<Blob> corpus = read_blobs(path);
    if (corpus.empty()) { std::printf("{\"error\":\"empty corpus\"}\n"); return 2; }
    g_rng = seed ? seed : 1;
    std::map<int, long> codes;
    long accepted = 0, unsound = 0, kinds[6] = {0, 0, 0, 0, 0, 0};
    for (long i = 0; i < count; ++i) {
        std::vector<uint8_t> b = corpus[below(static_cast<uint32_t>(corpus.size()))].bytes;
        const uint32_t kind = below(6);
        ++kinds[kind];
        const size_t body = b.size() > 20 ? b.size() - 20 : 0;   // between header and trailer
        bool sealed = below(8) != 0;                             // most mutations keep total and crc right
        switch (kind) {
            case 0: {   // truncation (or a cut in the body when resealed)
                const size_t keep = below(static_cast<uint32_t>(b.size() + 1));
                if (sealed && body) {
                    const size_t cut = 16 + below(static_cast<uint32_t>(body));
                    b.erase(b.begin() + static_cast<std::ptrdiff_t>(cut), b.end() - 4);
                } else {
                    b.resize(keep);
                }
                break;
            }
            case 1: {   // bit flips
                const uint32_t flips = 1 + below(8);
                for (uint32_t f = 0; f < flips && !b.empty(); ++f) b[below(static_cast<uint32_t>(b.size()))] ^= static_cast<uint8_t>(1u << below(8));
                break;
            }
            case 2: {   // a length lie: a byte of the body set to a small or big value (string lengths, counts)
                if (body) {
                    static const uint8_t kLies[] = {0, 1, 2, 7, 8, 11, 12, 15, 16, 23, 24, 32, 33, 48, 49, 127, 128, 129, 254, 255};
                    const uint32_t n = 1 + below(3);
                    for (uint32_t k = 0; k < n; ++k) b[16 + below(static_cast<uint32_t>(body))] = kLies[below(sizeof kLies)];
                }
                break;
            }
            case 3: {   // count inflation: bytes inserted (or removed) in the body
                if (body) {
                    const size_t at = 16 + below(static_cast<uint32_t>(body));
                    if (below(2)) {
                        const uint32_t n = 1 + below(64);
                        b.insert(b.begin() + static_cast<std::ptrdiff_t>(at), n, static_cast<uint8_t>(below(256)));
                    } else {
                        const size_t n = std::min<size_t>(1 + below(16), b.size() - 4 - at);
                        b.erase(b.begin() + static_cast<std::ptrdiff_t>(at), b.begin() + static_cast<std::ptrdiff_t>(at + n));
                    }
                }
                break;
            }
            case 4: {   // a header field (total, features, wire, reserved) or the trailer
                static const size_t kAt[] = {4, 5, 6, 8, 9, 12, 13};
                if (b.size() > 16) b[kAt[below(7)]] ^= static_cast<uint8_t>(1 + below(255));
                sealed = below(2) != 0;
                break;
            }
            default: {  // random bytes in a random run
                if (body) {
                    const size_t at = 16 + below(static_cast<uint32_t>(body));
                    const size_t n = std::min<size_t>(1 + below(32), b.size() - 4 - at);
                    for (size_t k = 0; k < n; ++k) b[at + k] = static_cast<uint8_t>(rnd());
                }
                break;
            }
        }
        if (sealed && kind != 0) reseal(b);
        else if (sealed && kind == 0 && body) reseal(b);
        cc_app_profile_t* p = nullptr;
        size_t offset = 0;
        const int code = decode_exact(b, &p, &offset, below(64) == 0);
        ++codes[code];
        if (code == CC_APP_OK) {
            ++accepted;
            if (!p || !profile_sound(p, block_size(p))) ++unsound;
            if (p) test_free(&g_alloc, p);
        } else if (p != nullptr || offset > b.size()) {
            ++unsound;
        }
    }
    std::string hist = "{";
    bool first = true;
    for (const auto& kv : codes) {
        hist += std::string(first ? "" : ",") + "\"" + std::to_string(kv.first) + "\":" + std::to_string(kv.second);
        first = false;
    }
    hist += "}";
    std::printf("{\"cases\":%ld,\"accepted\":%ld,\"unsound\":%ld,\"leaked\":%zu,\"codes\":%s,\"kinds\":[%ld,%ld,%ld,%ld,%ld,%ld]}\n",
                count, accepted, unsound, g_alloc.blocks.size(), hist.c_str(), kinds[0], kinds[1], kinds[2], kinds[3],
                kinds[4], kinds[5]);
    return unsound || !g_alloc.blocks.empty() ? 1 : 0;
}

// ------------------------------------------------------------------------------------------------ threads
// The LCD task (acquire, read every pointer, release) against the COM task (uploads that replace and evict),
// through the msg layer and std::mutex hooks. Under ASan a free while acquired is a use-after-free report.
std::string b64(const uint8_t* data, size_t n) {
    static const char* k = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string out;
    for (size_t i = 0; i < n; i += 3) {
        const uint32_t w = (static_cast<uint32_t>(data[i]) << 16) | (i + 1 < n ? data[i + 1] << 8 : 0) | (i + 2 < n ? data[i + 2] : 0);
        out += k[(w >> 18) & 63];
        out += k[(w >> 12) & 63];
        out += i + 1 < n ? k[(w >> 6) & 63] : '=';
        out += i + 2 < n ? k[w & 63] : '=';
    }
    return out;
}

std::string upload_lines_reply(const std::vector<uint8_t>& blob, const char* id, uint32_t now) {
    const uint32_t crc = blob.size() >= 4 ? cc_app_crc32(0, blob.data(), blob.size() - 4) : 0;
    std::string last;
    auto send = [&](const std::string& line) {
        JsonDocument doc, reply;
        deserializeJson(doc, line);
        if (cc_app_profile_command(doc["appProfile"], now, reply["appProfile"].to<JsonObject>())) {
            last.clear();
            serializeJson(reply, last);
        }
    };
    send("{\"appProfile\":{\"op\":\"begin\",\"id\":\"" + std::string(id) + "\",\"bytes\":" + u(blob.size()) +
         ",\"crc\":" + u(crc) + ",\"wire\":1}}");
    for (size_t off = 0; off < blob.size(); off += 2250)
        send("{\"appProfile\":{\"op\":\"data\",\"off\":" + u(off) + ",\"b64\":\"" +
             b64(blob.data() + off, std::min<size_t>(2250, blob.size() - off)) + "\"}}");
    send("{\"appProfile\":{\"op\":\"end\"}}");
    return last;
}

int mode_threads(const char* path, long rounds) {
    const std::vector<Blob> corpus = read_blobs(path);
    if (corpus.empty()) { std::printf("{\"error\":\"empty corpus\"}\n"); return 2; }
    store_init(true);
    std::atomic<bool> stop{false};
    std::atomic<long> draws{0}, hits{0};
    static const char* kIds[] = {"a", "b", "c", "d", "e", "f"};
    std::thread lcd([&] {
        uint32_t x = 7;
        while (!stop) {
            x = x * 1103515245u + 12345u;
            const char* id = kIds[(x >> 16) % 6];
            // crc 0 never matches an upload here; the reader asks for whatever is loaded under that id.
            cc_app_store_item_t items[8];
            const size_t n = cc_app_store_list(items, 8);
            uint32_t crc = 0;
            for (size_t i = 0; i < n; ++i) if (!std::strcmp(items[i].id, id)) crc = items[i].crc;
            const cc_app_profile_t* p = cc_app_store_acquire(id, crc);
            ++draws;
            if (p) {
                ++hits;
                volatile uint32_t sum = 0;   // read every element, as a draw would
                for (uint8_t r = 0; r < p->ring_count; ++r)
                    for (uint8_t c = 0; c < p->rings[r].count; ++c) {
                        const app_cmd_t& m = p->rings[r].cmds[c];
                        sum = sum + static_cast<uint32_t>(m.name[0]);
                        if (m.scene)
                            for (uint8_t e = 0; e < m.scene->n_base; ++e) sum = sum + m.scene->base[e].op;
                    }
                if (p->icon48) sum = sum + p->icon48[4607];
                std::this_thread::yield();
                cc_app_store_release(p);
            }
        }
    });
    long ok = 0, busy = 0, other = 0;
    for (long i = 0; i < rounds; ++i) {
        const Blob& blob = corpus[static_cast<size_t>(i) % corpus.size()];
        // Re-id the blob: the corpus profiles are all valid; their ids are rewritten to one of six and resealed.
        std::vector<uint8_t> b = blob.bytes;
        const char* id = kIds[i % 6];
        const uint8_t old_len = b[16];
        b.erase(b.begin() + 17, b.begin() + 17 + old_len);
        b.insert(b.begin() + 17, id, id + std::strlen(id));
        b[16] = static_cast<uint8_t>(std::strlen(id));
        reseal(b);
        const std::string reply = upload_lines_reply(b, id, static_cast<uint32_t>(i));
        if (reply.find("\"ok\":true") != std::string::npos) ++ok;
        else if (reply.find("busy") != std::string::npos) ++busy;
        else ++other;
    }
    stop = true;
    lcd.join();
    store_init(true);   // frees every entry (nothing is acquired any more)
    std::printf("{\"rounds\":%ld,\"ok\":%ld,\"busy\":%ld,\"other\":%ld,\"draws\":%ld,\"hits\":%ld,\"leaked\":%zu,"
                "\"depthErrors\":%d}\n", rounds, ok, busy, other, static_cast<long>(draws), static_cast<long>(hits),
                g_alloc.blocks.size(), static_cast<int>(g_depthErrors));
    return other || !g_alloc.blocks.empty() || g_depthErrors ? 1 : 0;
}
}  // namespace

int main(int argc, char** argv) {
    if (argc < 3) {
        std::fprintf(stderr, "usage: app_store_tests decode|script|fuzz|threads <file> [...]\n");
        return 2;
    }
    const std::string mode = argv[1];
    if (mode == "probe") {   // the ASan self-test: one byte read past a heap block must be reported
        volatile uint8_t* block = static_cast<uint8_t*>(std::malloc(16));
        const int index = std::atoi(argv[2]);   // 16: one past the end
        const int value = block[index];
        std::free(const_cast<uint8_t*>(block));
        std::printf("{\"read\":%d}\n", value);
        return 0;
    }
    if (mode == "decode") return mode_decode(argv[2]);
    if (mode == "script") return mode_script(argv[2]);
    if (mode == "fuzz" && argc >= 5) return mode_fuzz(argv[2], std::atol(argv[3]), std::strtoull(argv[4], nullptr, 10));
    if (mode == "threads" && argc >= 4) return mode_threads(argv[2], std::atol(argv[3]));
    std::fprintf(stderr, "bad arguments\n");
    return 2;
}
