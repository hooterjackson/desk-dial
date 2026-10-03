// App profiles (plan §1b-§1d; APP_PROFILES.md, wire 1): the DDAP decoder, the RAM-only store and the upload state
// machine (cc_app_store.h). Pure C99: no recursion, no VLAs, no unaligned reads (every multi-byte field is read a
// byte at a time and assembled), every count and index bounded before use.
//
// The profile model, element set, parameter model and limits are adapted from Karl Malota's (katbinaris) app
// profiles, feat/firmware-esp-idf-quadra NanoDepsidf/src/app_profiles/ (app_profile.h; profile_json.c's range
// checks; host_link.c's upload state machine), with his permission.
#include "cc_app_store.h"
#include <string.h>

// ---------------------------------------------------------------------------------------------------- CRC-32
// zlib's CRC-32, reflected, four bits at a time (a 64-byte table: about 2 cycles per bit less than bitwise).
static const uint32_t kCrcNibble[16] = {
    0x00000000u, 0x1DB71064u, 0x3B6E20C8u, 0x26D930ACu, 0x76DC4190u, 0x6B6B51F4u, 0x4DB26158u, 0x5005713Cu,
    0xEDB88320u, 0xF00F9344u, 0xD6D6A3E8u, 0xCB61B38Cu, 0x9B64C2B0u, 0x86D3D2D4u, 0xA00AE278u, 0xBDBDF21Cu};

uint32_t cc_app_crc32(uint32_t crc, const uint8_t *data, size_t len) {
    crc = ~crc;
    for (size_t i = 0; i < len; ++i) {
        crc ^= data[i];
        crc = (crc >> 4) ^ kCrcNibble[crc & 0x0Fu];
        crc = (crc >> 4) ^ kCrcNibble[crc & 0x0Fu];
    }
    return ~crc;
}

static bool id_char(uint8_t c) {
    return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '-';
}

bool cc_app_id_valid(const char *id) {
    if (id == NULL) return false;
    size_t n = 0;
    while (id[n] != '\0') {
        if (n >= CC_APP_ID_MAX || !id_char((uint8_t)id[n])) return false;
        ++n;
    }
    return n > 0;
}

// ---------------------------------------------------------------------------------------------------- decoder
// Wire limits (APP_PROFILES.md section 3).
#define W_HEADER 16u
#define W_TRAILER 4u
#define W_ICON24 (24u * 24u * 2u)
#define W_ICON48 (48u * 48u * 2u)
#define W_NAME_MAX 15u
#define W_LEGEND_MAX 7u
#define W_LABEL_MAX 23u
#define W_KEY_MAX 7u
#define W_TAB_MAX 6u
#define W_PARAMS_MAX 32u
#define W_SCENES_MAX 128u
#define W_ELEMENTS_MAX 48u
#define W_FRAMES_MAX 16u
#define W_FRAME_MS_MAX 60000u
#define W_RINGS_MAX 8u
#define W_CMDS_MAX 32u
#define W_EL_OP_MAX 14u
#define W_EL_COLOR_MAX 4u
#define W_PV_MAX 9u
#define W_FLOAT_MAX 1e7f
#define W_NONE 0xFFu
#define W_CMD_SEARCH 0x01u
#define W_CMD_DISABLED 0x02u
#define W_CMD_MACRO 0x04u
#define W_MOD_MASK 0x0Fu

// What pass 1 counts: the sizes of the allocation's arrays.
typedef struct {
    size_t rings, cmds, scenes, frames, params, els, icon_bytes, str_bytes;
} counts_t;

// The cursor. `mem` is NULL in pass 1 (validate and count); in pass 2 it is the allocation, and the arrays below
// point into it. `cap` holds pass 1's counts, `n` what pass 2 has used: a write past `cap` is refused (it cannot
// happen with an unchanged blob, but nothing is written outside the allocation even then).
typedef struct {
    const uint8_t *b;
    size_t pos, end;
    int err;
    size_t err_off;
    bool fill;
    counts_t n, cap;
    cc_app_profile_t *p;
    app_ring_t *rings;
    app_cmd_t *cmds;
    app_scene_t *scenes;
    app_keyframe_t *frames;
    app_param_t *params;
    app_el_t *els;
    uint8_t *icons;
    char *strs;
    // Feature bits the content needs (section 4).
    uint32_t features;
} rd_t;

static void fail(rd_t *r, int code, size_t off) {
    if (r->err == CC_APP_OK) {
        r->err = code;
        r->err_off = off;
    }
}

static bool need(rd_t *r, size_t bytes) {
    if (r->err != CC_APP_OK) return false;
    if (bytes > r->end - r->pos) {   // pos <= end always
        fail(r, CC_APP_E_SHORT, r->pos);
        return false;
    }
    return true;
}

static uint8_t u8(rd_t *r) {
    if (!need(r, 1)) return 0;
    return r->b[r->pos++];
}

static uint16_t u16(rd_t *r) {
    if (!need(r, 2)) return 0;
    const uint16_t v = (uint16_t)(r->b[r->pos] | ((uint16_t)r->b[r->pos + 1] << 8));
    r->pos += 2;
    return v;
}

static uint32_t le32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint32_t u32(rd_t *r) {
    if (!need(r, 4)) return 0;
    const uint32_t v = le32(r->b + r->pos);
    r->pos += 4;
    return v;
}

// A u8 that must be <= max (else CC_APP_E_RANGE at its offset).
static uint8_t u8_max(rd_t *r, uint8_t max) {
    const size_t off = r->pos;
    const uint8_t v = u8(r);
    if (v > max) fail(r, CC_APP_E_RANGE, off);
    return v;
}

// A finite f32 within +-1e7 (else CC_APP_E_FLOAT at its offset).
static float f32(rd_t *r) {
    const size_t off = r->pos;
    const uint32_t bits = u32(r);
    if (r->err != CC_APP_OK) return 0.0f;
    float v;
    memcpy(&v, &bits, sizeof v);
    if ((bits & 0x7F800000u) == 0x7F800000u || v > W_FLOAT_MAX || v < -W_FLOAT_MAX) {
        fail(r, CC_APP_E_FLOAT, off);
        return 0.0f;
    }
    return v;
}

// Space for `count` items of an array in pass 2 (NULL in pass 1, or when pass 1's count would be exceeded).
static size_t take(rd_t *r, size_t *used, size_t cap, size_t count) {
    const size_t at = *used;
    if (count > cap - at) {   // at <= cap always
        fail(r, CC_APP_E_MEMORY, 0);
        return 0;
    }
    *used += count;
    return at;
}

// A str field: u8 len (min..max) + printable ASCII 0x20..0x7E. Pass 2 returns its NUL-terminated copy; an empty
// string is NULL when `null_empty` (and then takes no space), else "". The length is CC_APP_E_STRING at the length
// byte, a bad byte CC_APP_E_STRING at that byte. `id` checks the id syntax instead (CC_APP_E_ID at the length byte).
static const char *str(rd_t *r, uint8_t min, uint8_t max, bool null_empty, bool id) {
    const size_t off = r->pos;
    const uint8_t len = u8(r);
    if (r->err != CC_APP_OK) return NULL;
    if (len < min || len > max) {
        fail(r, id ? CC_APP_E_ID : CC_APP_E_STRING, off);
        return NULL;
    }
    if (!need(r, len)) return NULL;
    const uint8_t *text = r->b + r->pos;
    for (uint8_t i = 0; i < len; ++i) {
        if (id ? !id_char(text[i]) : (text[i] < 0x20u || text[i] > 0x7Eu)) {
            fail(r, id ? CC_APP_E_ID : CC_APP_E_STRING, id ? off : r->pos + i);
            return NULL;
        }
    }
    r->pos += len;
    if (len == 0 && null_empty) return NULL;
    if (!r->fill) {
        r->n.str_bytes += (size_t)len + 1u;
        return NULL;
    }
    const size_t at = take(r, &r->n.str_bytes, r->cap.str_bytes, (size_t)len + 1u);
    if (r->err != CC_APP_OK) return NULL;
    char *out = r->strs + at;
    memcpy(out, text, len);
    out[len] = '\0';
    return out;
}

// An element list: u8 count (0..48) + count x 9 bytes (op 0..14, color 0..4, the rest any value: Karl's
// profile_json.c r_elements ranges). Pass 2 returns the copy (NULL when empty).
static const app_el_t *elements(rd_t *r, uint8_t *count_out) {
    const size_t off = r->pos;
    const uint8_t n = u8(r);
    *count_out = 0;
    if (r->err != CC_APP_OK) return NULL;
    if (n > W_ELEMENTS_MAX) {
        fail(r, CC_APP_E_COUNT, off);
        return NULL;
    }
    if (!need(r, (size_t)n * 9u)) return NULL;
    for (uint8_t i = 0; i < n; ++i) {
        const uint8_t *e = r->b + r->pos + (size_t)i * 9u;
        if (e[0] > W_EL_OP_MAX) { fail(r, CC_APP_E_RANGE, r->pos + (size_t)i * 9u); return NULL; }
        if (e[1] > W_EL_COLOR_MAX) { fail(r, CC_APP_E_RANGE, r->pos + (size_t)i * 9u + 1u); return NULL; }
    }
    app_el_t *out = NULL;
    if (!r->fill) {
        r->n.els += n;
    } else if (n) {
        const size_t at = take(r, &r->n.els, r->cap.els, n);
        if (r->err != CC_APP_OK) return NULL;
        out = r->els + at;
        for (uint8_t i = 0; i < n; ++i) {
            const uint8_t *e = r->b + r->pos + (size_t)i * 9u;
            out[i].op = e[0];
            out[i].color = e[1];
            out[i].x = (int8_t)e[2];
            out[i].y = (int8_t)e[3];
            out[i].w = e[4];
            out[i].h = e[5];
            out[i].arg = e[6];
            out[i].d = e[7];
            out[i].flags = e[8];
        }
    }
    r->pos += (size_t)n * 9u;
    *count_out = n;
    return out;
}

static void walk_params(rd_t *r) {
    const size_t off = r->pos;
    const uint8_t count = u8(r);
    if (r->err != CC_APP_OK) return;
    if (count > W_PARAMS_MAX) { fail(r, CC_APP_E_COUNT, off); return; }
    size_t base = 0;
    if (!r->fill) r->n.params += count;
    else base = take(r, &r->n.params, r->cap.params, count);
    for (uint8_t i = 0; i < count && r->err == CC_APP_OK; ++i) {
        app_param_t q;
        memset(&q, 0, sizeof q);
        q.label = str(r, 1, W_LABEL_MAX, false, false);
        q.label_neg = str(r, 0, W_LABEL_MAX, true, false);
        for (int s = 0; s < 3; ++s) q.steps[s] = f32(r);
        q.free_step = f32(r);
        const size_t start_off = r->pos;
        q.start = f32(r);
        q.min = f32(r);
        q.max = f32(r);
        if (r->err == CC_APP_OK && !(q.min <= q.start && q.start <= q.max)) fail(r, CC_APP_E_RANGE, start_off);
        q.decimals = u8_max(r, 4);
        const size_t flags_off = r->pos;
        q.flags = u8(r);
        if (q.flags & ~(uint8_t)(APP_PARAM_DEG | APP_PARAM_AXES | APP_PARAM_PLANES | APP_PARAM_UNIFORM))
            fail(r, CC_APP_E_RANGE, flags_off);
        if (q.flags & (APP_PARAM_AXES | APP_PARAM_PLANES | APP_PARAM_UNIFORM))
            r->features |= CC_APP_FEAT_PARAM_CONSTRAINTS;
        q.visual = u8_max(r, W_PV_MAX);
        q.modes = u8_max(r, 15);
        q.axis_default = u8_max(r, APP_AXIS_UNIFORM);
        q.field = u8_max(r, 1) != 0;
        if (r->fill && r->err == CC_APP_OK) r->params[base + i] = q;
    }
}

static void walk_scenes(rd_t *r) {
    const size_t off = r->pos;
    const uint8_t count = u8(r);
    if (r->err != CC_APP_OK) return;
    if (count > W_SCENES_MAX) { fail(r, CC_APP_E_COUNT, off); return; }
    size_t base = 0;
    if (!r->fill) r->n.scenes += count;
    else base = take(r, &r->n.scenes, r->cap.scenes, count);
    for (uint8_t i = 0; i < count && r->err == CC_APP_OK; ++i) {
        app_scene_t s;
        memset(&s, 0, sizeof s);
        s.base = elements(r, &s.n_base);
        const size_t frames_off = r->pos;
        const uint8_t n_frames = u8(r);
        if (r->err != CC_APP_OK) return;
        if (n_frames > W_FRAMES_MAX) { fail(r, CC_APP_E_COUNT, frames_off); return; }
        size_t fbase = 0;
        if (!r->fill) r->n.frames += n_frames;
        else if (n_frames) fbase = take(r, &r->n.frames, r->cap.frames, n_frames);
        for (uint8_t f = 0; f < n_frames && r->err == CC_APP_OK; ++f) {
            app_keyframe_t k;
            memset(&k, 0, sizeof k);
            const size_t ms_off = r->pos;
            k.ms = u16(r);
            if (r->err == CC_APP_OK && k.ms > W_FRAME_MS_MAX) fail(r, CC_APP_E_RANGE, ms_off);
            k.el = elements(r, &k.n);
            if (r->fill && r->err == CC_APP_OK) r->frames[fbase + f] = k;
        }
        if (r->fill && r->err == CC_APP_OK) {
            s.n_frames = n_frames;
            s.frames = n_frames ? r->frames + fbase : NULL;
            r->scenes[base + i] = s;
        }
    }
}

// Rings come after params and scenes, so their indexes are checked against the final counts.
static void walk_rings(rd_t *r, uint8_t n_scenes, uint8_t n_params) {
    const size_t off = r->pos;
    const uint8_t count = u8(r);
    if (r->err != CC_APP_OK) return;
    if (count > W_RINGS_MAX) { fail(r, CC_APP_E_COUNT, off); return; }
    size_t base = 0;
    if (!r->fill) r->n.rings += count;
    else base = take(r, &r->n.rings, r->cap.rings, count);
    for (uint8_t i = 0; i < count && r->err == CC_APP_OK; ++i) {
        app_ring_t g;
        memset(&g, 0, sizeof g);
        g.name = str(r, 1, W_LABEL_MAX, false, false);
        g.tab = str(r, 1, W_TAB_MAX, false, false);
        g.slot = u8_max(r, APP_SLOTS - 1);
        const size_t cmds_off = r->pos;
        const uint8_t n_cmds = u8(r);
        if (r->err != CC_APP_OK) return;
        if (n_cmds < 1 || n_cmds > W_CMDS_MAX) { fail(r, CC_APP_E_COUNT, cmds_off); return; }
        size_t cbase = 0;
        if (!r->fill) r->n.cmds += n_cmds;
        else cbase = take(r, &r->n.cmds, r->cap.cmds, n_cmds);
        for (uint8_t c = 0; c < n_cmds && r->err == CC_APP_OK; ++c) {
            app_cmd_t m;
            memset(&m, 0, sizeof m);
            m.name = str(r, 1, W_LABEL_MAX, false, false);
            const size_t flags_off = r->pos;
            const uint8_t flags = u8(r);
            if (flags & ~(uint8_t)(W_CMD_SEARCH | W_CMD_DISABLED | W_CMD_MACRO)) fail(r, CC_APP_E_RANGE, flags_off);
            if (flags & W_CMD_DISABLED) r->features |= CC_APP_FEAT_DISABLED_CMDS;
            m.search = (flags & W_CMD_SEARCH) != 0;
            m.flags = (uint8_t)(((flags & W_CMD_DISABLED) ? APP_CMD_DISABLED : 0) |
                                ((flags & W_CMD_MACRO) ? APP_CMD_MACRO : 0));
            m.modifier = u8_max(r, W_MOD_MASK);
            const size_t key_off = r->pos;
            m.key = str(r, 0, W_KEY_MAX, true, false);
            // "empty when search or macro": the key of a search or macro command is never drawn.
            if (r->err == CC_APP_OK && (flags & (W_CMD_SEARCH | W_CMD_MACRO)) && r->b[key_off] != 0)
                fail(r, CC_APP_E_RANGE, key_off);
            const size_t scene_off = r->pos;
            const uint8_t scene = u8(r);
            if (r->err == CC_APP_OK && scene != W_NONE && scene >= n_scenes) fail(r, CC_APP_E_INDEX, scene_off);
            const size_t param_off = r->pos;
            const uint8_t param = u8(r);
            if (r->err == CC_APP_OK && param != W_NONE && param >= n_params) fail(r, CC_APP_E_INDEX, param_off);
            if (r->fill && r->err == CC_APP_OK) {
                m.scene = scene == W_NONE ? NULL : r->scenes + scene;
                m.param = param == W_NONE ? NULL : r->params + param;
                r->cmds[cbase + c] = m;
            }
        }
        if (r->fill && r->err == CC_APP_OK) {
            g.count = n_cmds;
            g.cmds = r->cmds + cbase;
            r->rings[base + i] = g;
        }
    }
}

// The body after the header, up to the trailer: identical in both passes.
static void walk(rd_t *r) {
    cc_app_profile_t q;
    memset(&q, 0, sizeof q);
    q.id = str(r, 1, CC_APP_ID_MAX, false, true);
    q.name = str(r, 1, W_NAME_MAX, false, false);
    for (int i = 0; i < 4; ++i) q.legend[i] = str(r, 0, W_LEGEND_MAX, false, false);
    q.visual = u8_max(r, APP_VISUAL_SHAPE);
    const size_t shape_off = r->pos;
    q.shape = u8_max(r, APP_SHAPE_OCTA);
    if (r->err == CC_APP_OK && q.visual == APP_VISUAL_LABEL && q.shape != APP_SHAPE_CUBE)
        fail(r, CC_APP_E_RANGE, shape_off);   // "0 when visual = label"
    q.shape_style = u8_max(r, APP_STYLE_THICK);
    q.stepped = u8_max(r, 1) != 0;
    r->features |= q.visual == APP_VISUAL_SHAPE ? CC_APP_FEAT_SHAPE : CC_APP_FEAT_LABEL_VISUAL;
    if (q.shape != APP_SHAPE_CUBE || q.shape_style != APP_STYLE_FACE) r->features |= CC_APP_FEAT_SHAPE_EXT;
    for (int i = 0; i < 3; ++i) {
        const size_t off = r->pos;
        q.plasma_heat[i] = u32(r);
        if (q.plasma_heat[i] > 0xFFFFFFu) fail(r, CC_APP_E_RANGE, off);
    }
    const size_t icons_off = r->pos;
    const uint8_t icons = u8(r);
    if (icons & ~0x03u) fail(r, CC_APP_E_RANGE, icons_off);
    for (int i = 0; i < 2; ++i) {
        if (!(icons & (1u << i))) continue;
        const size_t bytes = i == 0 ? W_ICON24 : W_ICON48;
        if (!need(r, bytes)) return;
        if (!r->fill) {
            r->n.icon_bytes += bytes;
        } else {
            const size_t at = take(r, &r->n.icon_bytes, r->cap.icon_bytes, bytes);
            if (r->err != CC_APP_OK) return;
            memcpy(r->icons + at, r->b + r->pos, bytes);
            if (i == 0) q.icon24 = r->icons + at;
            else q.icon48 = r->icons + at;
        }
        r->pos += bytes;
    }
    for (int i = 0; i < APP_SLOTS; ++i) {
        q.slots[i].kind = u8_max(r, APP_KIND_COMMANDS);
        q.slots[i].fx = u8_max(r, APP_FX_FLASH);
        const size_t button_off = r->pos;
        q.slots[i].button = u8(r);
        if (q.slots[i].button > 3 && q.slots[i].button != W_NONE) fail(r, CC_APP_E_RANGE, button_off);
        q.slots[i].label = str(r, 0, W_LABEL_MAX, false, false);
    }
    q.search_modifier = u8_max(r, W_MOD_MASK);
    q.search_key = str(r, 0, W_KEY_MAX, false, false);
    const size_t params_at = r->fill ? r->n.params : 0;
    walk_params(r);
    const uint8_t n_params = (uint8_t)(r->fill ? r->n.params - params_at : r->n.params);
    const size_t scenes_at = r->fill ? r->n.scenes : 0;
    walk_scenes(r);
    const uint8_t n_scenes = (uint8_t)(r->fill ? r->n.scenes - scenes_at : r->n.scenes);
    const size_t rings_at = r->fill ? r->n.rings : 0;
    walk_rings(r, n_scenes, n_params);
    if (r->err != CC_APP_OK) return;
    if (r->fill) {
        q.ring_count = (uint8_t)(r->n.rings - rings_at);
        q.rings = q.ring_count ? r->rings + rings_at : NULL;
        q.has_slots = true;
        *r->p = q;
    }
}

#define ALIGN8(x) (((x) + 7u) & ~(size_t)7u)

int cc_app_decode(const uint8_t *blob, size_t len, const cc_app_alloc_t *alloc, cc_app_profile_t **out,
                  size_t *fail_offset) {
    size_t scratch_offset = 0;
    if (fail_offset == NULL) fail_offset = &scratch_offset;
    *fail_offset = 0;
    if (out != NULL) *out = NULL;
    if (blob == NULL || out == NULL || alloc == NULL || alloc->alloc == NULL) {
        return CC_APP_E_MEMORY;
    }
    rd_t r;
    memset(&r, 0, sizeof r);
    r.b = blob;
    r.end = len;
    // Header.
    if (!need(&r, 4)) { *fail_offset = r.err_off; return r.err; }
    if (memcmp(blob, "DDAP", 4) != 0) return CC_APP_E_MAGIC;
    r.pos = 4;
    const uint8_t wire = u8(&r);
    if (r.err == CC_APP_OK && wire != CC_APP_WIRE_VERSION) { *fail_offset = 4; return CC_APP_E_WIRE; }
    const uint8_t reserved8 = u8(&r);
    if (r.err == CC_APP_OK && reserved8 != 0) { *fail_offset = 5; return CC_APP_E_RANGE; }
    const uint16_t reserved16 = u16(&r);
    if (r.err == CC_APP_OK && reserved16 != 0) { *fail_offset = 6; return CC_APP_E_RANGE; }
    const uint32_t total = u32(&r);
    if (r.err == CC_APP_OK && (total != len || total > CC_APP_WIRE_MAX_BYTES)) {
        *fail_offset = 8;
        return CC_APP_E_TOTAL;
    }
    const uint32_t features = u32(&r);
    if (r.err == CC_APP_OK && len < W_HEADER + W_TRAILER) fail(&r, CC_APP_E_SHORT, len);
    if (r.err != CC_APP_OK) { *fail_offset = r.err_off; return r.err; }
    const uint32_t crc = le32(blob + len - W_TRAILER);
    if (cc_app_crc32(0, blob, len - W_TRAILER) != crc) { *fail_offset = len - W_TRAILER; return CC_APP_E_CRC; }
    if (features & ~CC_APP_FEATURES_SUPPORTED) { *fail_offset = 12; return CC_APP_E_FEATURE; }

    // Pass 1: every rule, and the sizes.
    r.end = len - W_TRAILER;
    walk(&r);
    if (r.err == CC_APP_OK && r.pos != r.end) fail(&r, CC_APP_E_TRAILING, r.pos);
    // The header's bits must be exactly what the content uses ("Set when", section 4).
    if (r.err == CC_APP_OK && features != r.features) fail(&r, CC_APP_E_FEATURE, 12);
    if (r.err != CC_APP_OK) { *fail_offset = r.err_off; return r.err; }

    // One allocation: the profile, then each array (8-byte aligned), the icons and the strings.
    const counts_t n = r.n;
    const size_t at_rings = ALIGN8(sizeof(cc_app_profile_t));
    const size_t at_cmds = ALIGN8(at_rings + n.rings * sizeof(app_ring_t));
    const size_t at_scenes = ALIGN8(at_cmds + n.cmds * sizeof(app_cmd_t));
    const size_t at_frames = ALIGN8(at_scenes + n.scenes * sizeof(app_scene_t));
    const size_t at_params = ALIGN8(at_frames + n.frames * sizeof(app_keyframe_t));
    const size_t at_els = ALIGN8(at_params + n.params * sizeof(app_param_t));
    const size_t at_icons = at_els + n.els * sizeof(app_el_t);
    const size_t at_strs = at_icons + n.icon_bytes;
    const size_t bytes = at_strs + n.str_bytes;
    uint8_t *mem = (uint8_t *)alloc->alloc(alloc->ctx, bytes);
    if (mem == NULL) return CC_APP_E_MEMORY;
    memset(mem, 0, bytes);

    // Pass 2: the same walk, writing.
    rd_t w;
    memset(&w, 0, sizeof w);
    w.b = blob;
    w.pos = W_HEADER;
    w.end = len - W_TRAILER;
    w.fill = true;
    w.cap = n;
    w.p = (cc_app_profile_t *)mem;
    w.rings = (app_ring_t *)(mem + at_rings);
    w.cmds = (app_cmd_t *)(mem + at_cmds);
    w.scenes = (app_scene_t *)(mem + at_scenes);
    w.frames = (app_keyframe_t *)(mem + at_frames);
    w.params = (app_param_t *)(mem + at_params);
    w.els = (app_el_t *)(mem + at_els);
    w.icons = mem + at_icons;
    w.strs = (char *)(mem + at_strs);
    walk(&w);
    if (w.err != CC_APP_OK || w.pos != w.end) {   // the blob changed under us: never hand out a partial profile
        if (alloc->free) alloc->free(alloc->ctx, mem);
        *fail_offset = w.err_off;
        return w.err != CC_APP_OK ? w.err : CC_APP_E_MEMORY;
    }
    w.p->crc = crc;
    w.p->features = features;
    *out = w.p;
    return CC_APP_OK;
}

// ---------------------------------------------------------------------------------------------------- store
// Records: up to CC_APP_STORE_SLOTS live entries, plus retired ones still acquired by the LCD task (freed at their
// last release) and the one being decoded (reserved: counted in the budget, not yet visible).
#define RECORDS (2u * CC_APP_STORE_SLOTS)

typedef struct {
    cc_app_profile_t *p;   // NULL = free (or reserved)
    cc_app_alloc_t mem;    // what allocated p
    size_t bytes;
    uint32_t pins;         // acquires not yet released
    uint32_t drawn;        // LRU stamp: the store clock at the last acquire (or the upload)
    bool live;             // false = retired: no acquire finds it any more
    bool reserved;
    char id[CC_APP_ID_MAX + 1];
    uint32_t crc;
} record_t;

typedef struct {
    bool active;
    char id[CC_APP_ID_MAX + 1];
    uint32_t bytes, crc, received, last_ms;
    uint8_t *buf;
    cc_app_alloc_t mem;
} upload_t;

static struct {
    cc_app_store_hooks_t hooks;
    record_t rec[RECORDS];
    uint32_t clock;
    upload_t up;
} S;

static void lock(void) { if (S.hooks.lock) S.hooks.lock(S.hooks.lock_ctx); }
static void unlock(void) { if (S.hooks.unlock) S.hooks.unlock(S.hooks.lock_ctx); }

// Frees collected while the lock was held, done after it is released.
typedef struct {
    void *memory[RECORDS + 1];
    cc_app_alloc_t mem[RECORDS + 1];
    size_t count;
} free_list_t;

static void retire_locked(record_t *e, free_list_t *frees) {
    if (e->pins == 0) {
        if (e->p != NULL && frees->count < RECORDS + 1) {
            frees->memory[frees->count] = e->p;
            frees->mem[frees->count] = e->mem;
            ++frees->count;
        }
        memset(e, 0, sizeof *e);
    } else {
        e->live = false;   // the last release frees it
    }
}

static void free_all(free_list_t *frees) {
    for (size_t i = 0; i < frees->count; ++i)
        if (frees->mem[i].free) frees->mem[i].free(frees->mem[i].ctx, frees->memory[i]);
    frees->count = 0;
}

static void upload_drop(void) {
    if (S.up.buf != NULL && S.up.mem.free) S.up.mem.free(S.up.mem.ctx, S.up.buf);
    memset(&S.up, 0, sizeof S.up);
}

void cc_app_store_init(const cc_app_store_hooks_t *hooks) {
    upload_drop();
    free_list_t frees;
    frees.count = 0;
    lock();
    for (size_t i = 0; i < RECORDS; ++i) {
        record_t *e = &S.rec[i];
        if (e->p != NULL || e->reserved) retire_locked(e, &frees);
    }
    unlock();
    free_all(&frees);
    // Records still acquired stay (retired) until released.
    if (hooks != NULL) S.hooks = *hooks;
    else memset(&S.hooks, 0, sizeof S.hooks);
}

const cc_app_profile_t *cc_app_store_acquire(const char *id, uint32_t crc) {
    if (id == NULL) return NULL;
    const cc_app_profile_t *found = NULL;
    lock();
    for (size_t i = 0; i < RECORDS; ++i) {
        record_t *e = &S.rec[i];
        if (e->p != NULL && e->live && e->crc == crc && strcmp(e->id, id) == 0) {
            ++e->pins;
            e->drawn = ++S.clock;
            found = e->p;
            break;
        }
    }
    unlock();
    if (found == NULL && crc == 0 && strcmp(id, "onshape") == 0) found = &cc_app_profile_onshape;
    return found;
}

void cc_app_store_release(const cc_app_profile_t *p) {
    if (p == NULL || p == &cc_app_profile_onshape) return;
    free_list_t frees;
    frees.count = 0;
    lock();
    for (size_t i = 0; i < RECORDS; ++i) {
        record_t *e = &S.rec[i];
        if (e->p == p && e->pins > 0) {
            --e->pins;
            if (!e->live && e->pins == 0) retire_locked(e, &frees);
            break;
        }
    }
    unlock();
    free_all(&frees);
}

size_t cc_app_store_list(cc_app_store_item_t *items, size_t max) {
    size_t count = 0;
    bool taken[RECORDS];
    memset(taken, 0, sizeof taken);
    lock();
    while (count < max) {   // most recently drawn first
        int best = -1;
        for (size_t i = 0; i < RECORDS; ++i) {
            const record_t *e = &S.rec[i];
            if (!taken[i] && e->p != NULL && e->live && (best < 0 || e->drawn > S.rec[best].drawn)) best = (int)i;
        }
        if (best < 0) break;
        taken[best] = true;
        memcpy(items[count].id, S.rec[best].id, sizeof items[count].id);
        items[count].crc = S.rec[best].crc;
        ++count;
    }
    unlock();
    return count;
}

// The decode allocator of an upload's end: it runs only after pass 1 accepted the whole blob, so it makes room in
// the store first (APP_PROFILES.md section 7: replace the older copy with the same id; evict the least recently
// drawn while 4 would be loaded or the budget exceeded) and reserves a record, then allocates.
typedef struct {
    const uint8_t *blob;
    bool busy;          // the store cannot make room
    bool id_mismatch;   // the blob names another id than begin
} end_ctx_t;

static record_t *lru_locked(const bool *victim, int same, bool unpinned_only) {
    record_t *best = NULL;
    for (size_t i = 0; i < RECORDS; ++i) {
        record_t *e = &S.rec[i];
        if (e->p == NULL || !e->live || victim[i] || (int)i == same || (unpinned_only && e->pins)) continue;
        if (best == NULL || e->drawn < best->drawn) best = e;
    }
    return best;
}

static void *store_alloc(void *ctx, size_t n) {
    end_ctx_t *c = (end_ctx_t *)ctx;
    // The blob is valid here: its id is the str at offset 16.
    const uint8_t id_len = c->blob[W_HEADER];
    if (id_len != strlen(S.up.id) || memcmp(c->blob + W_HEADER + 1, S.up.id, id_len) != 0) {
        c->id_mismatch = true;
        return NULL;
    }
    if (n > CC_APP_STORE_BUDGET) return NULL;   // can never fit: decode 13
    free_list_t frees;
    frees.count = 0;
    bool victim[RECORDS];
    memset(victim, 0, sizeof victim);
    lock();
    int same = -1;
    size_t live = 0, used = 0, free_records = 0;
    for (size_t i = 0; i < RECORDS; ++i) {
        const record_t *e = &S.rec[i];
        if (e->p != NULL || e->reserved) used += e->bytes;
        if (e->p == NULL && !e->reserved) ++free_records;
        if (e->p != NULL && e->live) {
            ++live;
            if (strcmp(e->id, S.up.id) == 0) same = (int)i;
        }
    }
    // The same id is replaced at commit (no "Loading..." frame in between) unless its bytes are needed first.
    size_t live_after = live + 1u - (same >= 0 ? 1u : 0u);
    bool same_early = false, ok = true;
    while (ok && live_after > CC_APP_STORE_SLOTS) {
        record_t *v = lru_locked(victim, same, false);
        if (v == NULL) { ok = false; break; }
        victim[v - S.rec] = true;
        --live_after;
        if (v->pins == 0) { used -= v->bytes; ++free_records; }
    }
    while (ok && used + n > CC_APP_STORE_BUDGET) {
        record_t *v = lru_locked(victim, same, true);
        if (v != NULL) {
            victim[v - S.rec] = true;
            used -= v->bytes;
            ++free_records;
        } else if (same >= 0 && !same_early && S.rec[same].pins == 0) {
            same_early = true;
            used -= S.rec[same].bytes;
            ++free_records;
        } else {
            ok = false;
        }
    }
    if (ok && free_records == 0) ok = false;
    record_t *slot = NULL;
    if (ok) {
        for (size_t i = 0; i < RECORDS; ++i) if (victim[i]) retire_locked(&S.rec[i], &frees);
        if (same_early) retire_locked(&S.rec[same], &frees);
        for (size_t i = 0; i < RECORDS && slot == NULL; ++i)
            if (S.rec[i].p == NULL && !S.rec[i].reserved) slot = &S.rec[i];
        if (slot != NULL) {
            memset(slot, 0, sizeof *slot);
            slot->reserved = true;
            slot->bytes = n;
        }
    }
    unlock();
    free_all(&frees);
    if (slot == NULL) {
        c->busy = true;
        return NULL;
    }
    void *memory = S.hooks.mem.alloc ? S.hooks.mem.alloc(S.hooks.mem.ctx, n) : NULL;
    if (memory == NULL) {
        lock();
        memset(slot, 0, sizeof *slot);
        unlock();
    }
    return memory;
}

static void store_free(void *ctx, void *memory) {
    (void)ctx;
    lock();
    for (size_t i = 0; i < RECORDS; ++i)
        if (S.rec[i].reserved) memset(&S.rec[i], 0, sizeof S.rec[i]);
    unlock();
    if (S.hooks.mem.free) S.hooks.mem.free(S.hooks.mem.ctx, memory);
}

// ---------------------------------------------------------------------------------------------------- upload
const char *cc_app_up_error_name(cc_app_up_result_t result) {
    switch (result) {
        case CC_APP_UP_CRC: return "crc";
        case CC_APP_UP_SIZE: return "size";
        case CC_APP_UP_ORDER: return "order";
        case CC_APP_UP_BUSY: return "busy";
        case CC_APP_UP_WIRE: return "wire";
        case CC_APP_UP_DECODE: return "decode";
        default: return NULL;
    }
}

bool cc_app_upload_active(void) { return S.up.active; }

void cc_app_upload_poll(uint32_t now_ms) {
    if (S.up.active && (uint32_t)(now_ms - S.up.last_ms) >= CC_APP_UPLOAD_STALL_MS) upload_drop();
}

cc_app_up_result_t cc_app_upload_begin(const char *id, uint32_t bytes, uint32_t crc, uint32_t wire, uint32_t now_ms) {
    upload_drop();   // one upload at a time: a begin aborts the earlier one
    if (wire != CC_APP_WIRE_VERSION) return CC_APP_UP_WIRE;
    if (bytes == 0 || bytes > CC_APP_WIRE_MAX_BYTES) return CC_APP_UP_SIZE;
    if (!cc_app_id_valid(id)) return CC_APP_UP_ORDER;
    if (S.hooks.mem.alloc == NULL) return CC_APP_UP_BUSY;
    uint8_t *buf = (uint8_t *)S.hooks.mem.alloc(S.hooks.mem.ctx, bytes);
    if (buf == NULL) return CC_APP_UP_BUSY;
    S.up.active = true;
    memcpy(S.up.id, id, strlen(id) + 1u);   // 1..11 characters and the NUL, checked above
    S.up.bytes = bytes;
    S.up.crc = crc;
    S.up.received = 0;
    S.up.last_ms = now_ms;
    S.up.buf = buf;
    S.up.mem = S.hooks.mem;
    return CC_APP_UP_OK;
}

static int b64_value(char c) {
    if (c >= 'A' && c <= 'Z') return c - 'A';
    if (c >= 'a' && c <= 'z') return c - 'a' + 26;
    if (c >= '0' && c <= '9') return c - '0' + 52;
    if (c == '+') return 62;
    if (c == '/') return 63;
    return -1;
}

// The decoded size of padded standard base64 (a non-empty multiple of 4 characters, '=' only as the last one or
// two), or 0 when the length or padding is invalid. The same rule as cc_media_base64_decode (ARTWORK2.md).
static size_t b64_size(const char *text, size_t size) {
    if (size == 0 || size % 4u) return 0;
    size_t pad = 0;
    if (text[size - 1] == '=') pad = text[size - 2] == '=' ? 2u : 1u;
    return size / 4u * 3u - pad;
}

// Decodes into out[0 .. b64_size); false on any character outside the alphabet (or a misplaced '=').
static bool b64_decode(const char *text, size_t size, uint8_t *out) {
    const size_t decoded = b64_size(text, size);
    const size_t pad = size / 4u * 3u - decoded;
    size_t written = 0;
    for (size_t i = 0; i < size; i += 4) {
        uint32_t word = 0;
        for (size_t j = 0; j < 4; ++j) {
            const char c = text[i + j];
            int value = 0;   // a final '=' counts as 0
            if (!(c == '=' && i + 4 == size && j >= 4 - pad)) {
                value = b64_value(c);
                if (value < 0) return false;
            }
            word = (word << 6) | (uint32_t)value;
        }
        out[written++] = (uint8_t)(word >> 16);
        if (written < decoded) out[written++] = (uint8_t)(word >> 8);
        if (written < decoded) out[written++] = (uint8_t)word;
    }
    return true;
}

cc_app_up_result_t cc_app_upload_data(uint32_t off, const char *b64, size_t b64_len, uint32_t now_ms, uint32_t *next) {
    cc_app_upload_poll(now_ms);
    if (!S.up.active) return CC_APP_UP_ORDER;
    cc_app_up_result_t result = CC_APP_UP_OK;
    const size_t decoded = (b64 != NULL && b64_len <= CC_APP_B64_MAX) ? b64_size(b64, b64_len) : 0;
    if (b64 == NULL || off != S.up.received) result = CC_APP_UP_ORDER;
    else if (decoded == 0 || decoded > S.up.bytes - S.up.received) result = CC_APP_UP_SIZE;
    else if (!b64_decode(b64, b64_len, S.up.buf + S.up.received)) result = CC_APP_UP_SIZE;
    if (result != CC_APP_UP_OK) {
        upload_drop();
        return result;
    }
    S.up.received += (uint32_t)decoded;
    S.up.last_ms = now_ms;
    if (next != NULL) *next = S.up.received;
    return CC_APP_UP_OK;
}

cc_app_up_result_t cc_app_upload_end(uint32_t now_ms, cc_app_up_end_t *result) {
    cc_app_up_end_t scratch;
    if (result == NULL) result = &scratch;
    memset(result, 0, sizeof *result);
    cc_app_upload_poll(now_ms);
    if (!S.up.active) return CC_APP_UP_ORDER;
    cc_app_up_result_t status = CC_APP_UP_OK;
    if (S.up.received != S.up.bytes) {
        status = CC_APP_UP_SIZE;
    } else if (S.up.bytes >= W_TRAILER && cc_app_crc32(0, S.up.buf, S.up.bytes - W_TRAILER) != S.up.crc) {
        status = CC_APP_UP_CRC;
    } else {
        end_ctx_t ctx;
        memset(&ctx, 0, sizeof ctx);
        ctx.blob = S.up.buf;
        const cc_app_alloc_t alloc = {store_alloc, store_free, &ctx};
        cc_app_profile_t *profile = NULL;
        size_t offset = 0;
        const int code = cc_app_decode(S.up.buf, S.up.bytes, &alloc, &profile, &offset);
        if (code != CC_APP_OK) {
            status = ctx.busy ? CC_APP_UP_BUSY : CC_APP_UP_DECODE;
            result->decode = ctx.id_mismatch ? CC_APP_E_ID : code;
            result->offset = ctx.id_mismatch ? W_HEADER : offset;
        } else {
            free_list_t frees;
            frees.count = 0;
            lock();
            for (size_t i = 0; i < RECORDS; ++i) {   // the older copy with the same id, if still live
                record_t *e = &S.rec[i];
                if (e->p != NULL && e->live && strcmp(e->id, S.up.id) == 0) retire_locked(e, &frees);
            }
            for (size_t i = 0; i < RECORDS; ++i) {
                record_t *e = &S.rec[i];
                if (!e->reserved) continue;
                e->reserved = false;
                e->p = profile;
                e->mem = S.hooks.mem;
                e->live = true;
                e->pins = 0;
                e->drawn = ++S.clock;
                memcpy(e->id, S.up.id, sizeof e->id);
                e->crc = profile->crc;
                break;
            }
            unlock();
            free_all(&frees);
            memcpy(result->id, S.up.id, sizeof result->id);
            result->crc = profile->crc;
        }
    }
    upload_drop();
    return status;
}
